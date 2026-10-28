"""Build a brand kit from decks someone uploads.

Takes a PDF export of a deck, slide screenshots, and/or a .pptx, shows them to
Claude, and gets back a kit: the palette mapped onto the renderer's roles, the
closest Google Fonts, the brand's voice, and one slide template per distinct
pattern in the source, rebuilt in this app's layouts.

What it can't do, and says so in the kit's caveats: reproduce photography,
custom illustration or a layout none of the built-in layouts can express.
"""

import base64
import json
import re
import zipfile
from io import BytesIO
from pathlib import Path

import fonts
import kits
from generate import (LAYOUTS, SLIDE_SCHEMA, MODEL, _client, _final_message,
                      _require_key, _text)

MAX_PDF_BYTES = 30_000_000
MAX_IMAGES = 20
IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
               ".webp": "image/webp", ".gif": "image/gif"}
ACCEPTED = {".pdf", ".pptx", *IMAGE_TYPES}

ROLE_PROPS = {
    role: {"type": "string", "description": f"Hex like #1a2b3c. {label}: {what}."}
    for role, _, label, what in kits.ROLES
}

KIT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["name", "description", "wordmark", "palette", "fonts", "voice",
                 "slides", "decks", "caveats"],
    "properties": {
        "name": {"type": "string", "description": "Short kit name, usually the brand, e.g. 'Acme'."},
        "description": {"type": "string",
                        "description": "One sentence on the look: e.g. 'Navy and coral, "
                                       "big serif headlines, lots of white space.'"},
        "wordmark": {"type": "string",
                     "description": "The brand name as it appears on the cover, in its own casing. "
                                    "'' if there is none."},
        "palette": {"type": "object", "additionalProperties": False,
                    "required": list(ROLE_PROPS), "properties": ROLE_PROPS},
        "fonts": {
            "type": "object", "additionalProperties": False,
            "required": ["display", "body", "display_seen", "body_seen"],
            "properties": {
                "display": {"type": "string",
                            "description": "Google Fonts family for headings, exact name as on "
                                           "fonts.google.com."},
                "body": {"type": "string", "description": "Google Fonts family for body copy."},
                "display_seen": {"type": "string",
                                 "description": "The heading face actually used in the source, "
                                                "if you can tell. '' if unsure."},
                "body_seen": {"type": "string", "description": "Same for body copy."},
            },
        },
        "voice": {"type": "string",
                  "description": "6 to 10 concrete writing rules as '- ' lines, derived from the "
                                 "source copy."},
        "slides": {
            "type": "array",
            "items": {
                "type": "object", "additionalProperties": False,
                "required": ["name", "category", "note", "slide"],
                "properties": {
                    "name": {"type": "string", "description": "Template name, e.g. 'Problem 2×2'."},
                    "category": {"type": "string",
                                 "description": "Opening, Problem, Solution, Market, Proof, "
                                                "Diagram, Ask, Closing, or similar."},
                    "note": {"type": "string",
                             "description": "One sentence: when to use it and what makes it this "
                                            "brand's version."},
                    "slide": SLIDE_SCHEMA,
                },
            },
        },
        "decks": {
            "type": "array",
            "items": {
                "type": "object", "additionalProperties": False,
                "required": ["name", "note", "slide_numbers"],
                "properties": {
                    "name": {"type": "string"},
                    "note": {"type": "string", "description": "The arc in one sentence."},
                    "slide_numbers": {"type": "array", "items": {"type": "integer"},
                                      "description": "1-based positions in `slides`, in deck order. "
                                                     "Repeats allowed."},
                },
            },
        },
        "caveats": {"type": "string",
                    "description": "Plain sentences on what the kit could not capture (photos, "
                                   "custom illustrations, a layout with no equivalent, unreadable "
                                   "pages). '' if nothing important."},
    },
}

SYSTEM = f"""You turn a brand's existing presentation decks into a reusable brand kit for a
deck generator. The generator renders every slide through a fixed set of layouts and
a palette of colour roles, so your job is to translate the source into those terms
faithfully — not to redesign it.

## Palette

Fill every role with a hex colour taken from the source. Where the source has no
colour for a role, derive one from its palette (a lighter tint of the accent, a
darker shade of the background) rather than inventing a new hue. Hard rules:

- `text` on `background` must be readable (WCAG 4.5:1 or better).
- `dark` and `darkest` are full-bleed backgrounds with near-white text on them, so
  they must be genuinely dark. If the source has no dark slides, use a deep shade
  of its main brand colour.
- `card_dark` holds near-white body text and `card_dark_label` labels: dark again.
- `accent` sits behind white text on badges and pills: saturated enough for that.
- Tints (`card_tint`, `card_tint_alt`, `accent_pale`, `soft`, `neutral`) are light.

## Fonts

Name the closest Google Fonts family for headings and for body copy, spelled
exactly as on fonts.google.com. If the source uses a Google font, use that. If it
uses a commercial face, pick the nearest free match (e.g. Helvetica → Inter,
Futura → Jost, Gotham → Montserrat, Garamond → EB Garamond, Avenir → Nunito Sans).

## Voice

Six to ten rules someone could follow to write new slides that sound like these:
headline style (claims or topics, length, casing), eyebrow style, sentence length,
how numbers are written, words and devices the brand uses or avoids. Concrete and
checkable, quoting short examples of phrasing from the source where useful. Never
quote real figures, prices, metrics, client or people's names in the voice rules:
describe the format instead ("figures with units, e.g. '$Xmn'"). Not adjectives
like "professional" or "engaging".

## Slide templates

One template per distinct pattern in the source — typically 8 to 16. Skip exact
repeats. For each, choose the layout from this app's set that best reproduces it:

{", ".join(LAYOUTS)}

- `cover`: opening; `section`: a divider or a full-bleed statement (set `ground`
  to "brown" for the dark version); `statement`: one centred line; `quote`.
- `cards` (2–6 equal cards), `columns` (bulleted columns with an optional badge
  value), `numbered` (themes, each with cards; set `group`), `flow` (3 stages with
  arrows), `stats` (2–4 big numbers), `pillrows` (term → definition), `mapping`
  (two pill columns; `group` = column heading; `value` "ghost"/"solid"), `cycle`
  (exactly 6 steps), `ledger` (two columns of line items with amounts), `diagram`
  (typed nodes; `group` = input/automation/agent/human/output/accent; `shape`
  chain or loop), `bullets` (plain list).
- `variant` is the card treatment: "brown" = filled dark cards, "mint" = tinted,
  "teal" = second tint, "cream" = soft, "outline" = bordered. `ground`: "" default
  background, "warm"/"cream" alternates, "brown" dark, "ink" darkest.

Copy in the templates is placeholder text that teaches the pattern: same structure,
same number of items, same eyebrow style, similar length, written in the brand's
voice but generic ("The headline as a claim, not a topic"). Never carry over real
figures, client names, people's names, emails, phone numbers or anything
confidential from the source. The cover already shows the wordmark or logo above
the title, so a cover template's title is the deck's claim, never the brand name
again. Use the source's section names as eyebrows where
they are generic ("The Problem", "How it works").

## Deck arcs

One to four deck skeletons built from your templates, in slide order: the source's
own arc first, then shorter variants it implies (a short narrative, an update).
Reference templates by their 1-based position in `slides`.

## Caveats

Say plainly what the kit cannot reproduce."""


# --- reading uploads -------------------------------------------------------------

def _pptx_digest(data: bytes) -> tuple[str, list[dict]]:
    """Theme colours, theme fonts and per-slide text from a .pptx, plus its
    embedded cover thumbnail if there is one. Slides themselves can't be
    rendered without PowerPoint or LibreOffice, so the text and theme carry it."""
    lines, images = [], []
    try:
        z = zipfile.ZipFile(BytesIO(data))
    except zipfile.BadZipFile:
        return "That .pptx could not be opened.", []
    names = z.namelist()

    theme = next((n for n in sorted(names) if re.match(r"ppt/theme/theme\d+\.xml$", n)), None)
    if theme:
        x = z.read(theme).decode("utf-8", "ignore")
        cs = re.search(r"<a:clrScheme[^>]*>(.*?)</a:clrScheme>", x, re.S)
        if cs:
            pairs = re.findall(r"<a:(\w+)>\s*<a:(?:srgbClr val|sysClr[^>]*lastClr)=\"([0-9A-Fa-f]{6})\"",
                               cs.group(1))
            if pairs:
                lines.append("Theme colours: " + ", ".join(f"{k} #{v}" for k, v in pairs))
        major = re.search(r"<a:majorFont>\s*<a:latin typeface=\"([^\"]*)\"", x)
        minor = re.search(r"<a:minorFont>\s*<a:latin typeface=\"([^\"]*)\"", x)
        if major or minor:
            lines.append(f"Theme fonts: headings {major.group(1) if major else '?'}, "
                         f"body {minor.group(1) if minor else '?'}")

    slides = sorted((n for n in names if re.match(r"ppt/slides/slide\d+\.xml$", n)),
                    key=lambda n: int(re.search(r"(\d+)", n.rsplit("/", 1)[-1]).group(1)))
    used_fonts, used_colors = set(), {}
    for i, n in enumerate(slides[:60], start=1):
        x = z.read(n).decode("utf-8", "ignore")
        used_fonts |= set(re.findall(r"<a:latin typeface=\"([^\"+][^\"]*)\"", x))
        for c in re.findall(r"<a:srgbClr val=\"([0-9A-Fa-f]{6})\"", x):
            used_colors[c.lower()] = used_colors.get(c.lower(), 0) + 1
        paras = []
        for p in re.findall(r"<a:p>(.*?)</a:p>", x, re.S):
            t = "".join(re.findall(r"<a:t>([^<]*)</a:t>", p)).strip()
            if t:
                paras.append(t)
        lines.append(f"\nSlide {i}:\n" + ("\n".join(f"  {t}" for t in paras) or "  (no text)"))
    if used_fonts:
        lines.insert(0, "Fonts used on slides: " + ", ".join(sorted(used_fonts)))
    if used_colors:
        top = sorted(used_colors.items(), key=lambda kv: -kv[1])[:16]
        lines.insert(0, "Colours used on slides (most used first): " +
                     ", ".join(f"#{c}" for c, _ in top))

    for n in names:
        if n.lower().startswith("docprops/thumbnail.") and n.lower().endswith((".jpeg", ".jpg", ".png")):
            mt = "image/png" if n.lower().endswith(".png") else "image/jpeg"
            images.append({"type": "image", "source": {
                "type": "base64", "media_type": mt,
                "data": base64.b64encode(z.read(n)).decode()}})
    return "\n".join(lines), images


def _content(files: list[tuple[str, bytes]], notes: str) -> tuple[list, list[str]]:
    blocks, names, texts = [], [], []
    image_count = 0
    for filename, data in files:
        ext = Path(filename).suffix.lower()
        if ext not in ACCEPTED:
            raise ValueError(f"{filename}: upload a PDF, a .pptx, or slide images (PNG/JPG).")
        names.append(filename)
        if ext == ".pdf":
            if len(data) > MAX_PDF_BYTES:
                raise ValueError(f"{filename} is over 30 MB. Export a compressed PDF.")
            blocks.append({"type": "document", "title": filename, "source": {
                "type": "base64", "media_type": "application/pdf",
                "data": base64.b64encode(data).decode()}})
        elif ext == ".pptx":
            digest, thumbs = _pptx_digest(data)
            texts.append(f"<pptx name=\"{filename}\">\n{digest}\n</pptx>")
            blocks.extend(thumbs)
        else:
            image_count += 1
            if image_count > MAX_IMAGES:
                continue
            blocks.append({"type": "image", "source": {
                "type": "base64", "media_type": IMAGE_TYPES[ext],
                "data": base64.b64encode(data).decode()}})
    if not names:
        raise ValueError("Upload at least one deck: a PDF, a .pptx, or slide images.")

    ask = ["These are the brand's existing decks. Build the kit."]
    if any(Path(n).suffix.lower() == ".pptx" for n in names):
        ask.append("For .pptx files you have the theme, the colours and fonts in use, and "
                   "each slide's text, but not the rendered slides; infer layouts from the "
                   "text structure and say so in the caveats.")
    if texts:
        ask.append("\n\n".join(texts))
    if image_count > MAX_IMAGES:
        ask.append(f"(Only the first {MAX_IMAGES} of {image_count} images were included.)")
    if notes.strip():
        ask.append(f"Direction from the person uploading:\n{notes.strip()}")
    blocks.append({"type": "text", "text": "\n\n".join(ask)})
    return blocks, names


# --- guard rails the model can't be trusted with ---------------------------------

def _lum(hexv: str) -> float:
    h = hexv.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def _contrast(a: str, b: str) -> float:
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def _fix_palette(colors: dict) -> list[str]:
    """Enforce the rules the renderer depends on. Returns what was changed."""
    fixed = []
    ink, ground = colors.get("ink"), colors.get("ground")
    if ink and ground and _contrast(ink, ground) < 4.5:
        colors["ink"] = "#161b26" if _lum(ground) > 0.4 else "#f8f8f6"
        fixed.append("darkened the heading colour for contrast")
    deep = colors.get("ink") or "#161b26"
    for token, label in (("ground-brown", "dark background"),
                         ("ground-ink", "darkest background"),
                         ("brown-card", "filled card")):
        v = colors.get(token)
        if v and _contrast(v, "#fffaf5") < 4.5:
            colors[token] = deep if _contrast(deep, "#fffaf5") >= 4.5 else "#1e2a44"
            fixed.append(f"used a darker {label} so white text stays readable")
    return fixed


def build_kit(files: list[tuple[str, bytes]], name: str = "", notes: str = "") -> dict:
    """Uploads in, saved kit out."""
    _require_key()
    content, names = _content(files, notes)

    message = _final_message(
        _client(),
        model=MODEL,
        max_tokens=48000,
        system=SYSTEM,
        messages=[{"role": "user", "content": content}],
        output_config={
            "effort": "high",
            "format": {"type": "json_schema", "schema": KIT_SCHEMA},
        },
    )
    raw = json.loads(_text(message))

    colors = kits.clean_colors(raw.get("palette"))
    fixes = _fix_palette(colors)

    font_notes = []
    chosen = {}
    for role, default in (("display", "DM Sans"), ("body", "Inter")):
        fam = (raw.get("fonts") or {}).get(role) or default
        ok, msg = fonts.install(fam)
        if not ok:
            font_notes.append(f"{fam} isn't on Google Fonts, so {role} uses {default}")
            fam = default
        chosen[role] = fam

    templates = raw.get("slides") or []
    ids = [kits._id(t.get("name") or f"slide-{i}") for i, t in enumerate(templates, 1)]
    seen, uniq = set(), []
    for i in ids:
        j = i
        while j in seen:
            j = f"{i}-{len(seen)}"
        seen.add(j)
        uniq.append(j)
    for t, tid in zip(templates, uniq):
        t["id"] = tid
    decks = []
    for d in raw.get("decks") or []:
        order = [uniq[n - 1] for n in d.get("slide_numbers") or [] if 1 <= n <= len(uniq)]
        if order:
            decks.append({"name": d.get("name"), "note": d.get("note"), "slide_ids": order})

    caveats = " ".join(x for x in [
        (raw.get("caveats") or "").strip(),
        ("Adjusted: " + "; ".join(fixes) + ".") if fixes else "",
        ("Fonts: " + "; ".join(font_notes) + ".") if font_notes else "",
    ] if x)

    kit = {
        "name": (name or raw.get("name") or "My brand").strip(),
        "description": raw.get("description") or "",
        "brand": {"wordmark": raw.get("wordmark") or "", "logo": ""},
        "theme": {"colors": colors, "fonts": chosen},
        "voice": raw.get("voice") or "",
        "slides": templates,
        "decks": decks,
        "source": {
            "files": names,
            "fonts_seen": {k: (raw.get("fonts") or {}).get(f"{k}_seen") or ""
                           for k in ("display", "body")},
            "caveats": caveats,
            "model": MODEL,
        },
    }
    return kits.save(kit, kits.new_id(kit["name"]))
