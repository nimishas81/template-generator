"""Brand kits: the unit people upload, share and generate from.

A kit is everything that makes decks look and read like one brand:

    kits/<id>/kit.json     palette, fonts, wordmark, voice, slide templates,
                           deck skeletons
    kits/<id>/logo.<ext>   optional logo, referenced by kit["brand"]["logo"]

Generation, chat, the Templates tab and every render read from the kit a deck
was made with, so editing a kit restyles every deck that uses it. A deck's own
theme overrides still sit on top.
"""

import base64
import io
import json
import mimetypes
import re
import shutil
import time
import uuid
import zipfile
from pathlib import Path

import fonts

ROOT = Path(__file__).parent
KITS = ROOT / "kits"
KITS.mkdir(exist_ok=True)

DEFAULT_KIT = "starter"
LOGO_EXTS = {".png", ".jpg", ".jpeg", ".svg", ".webp"}
MAX_LOGO_BYTES = 2_000_000

# --- palette roles --------------------------------------------------------------
# The renderer's CSS tokens are named after the palette they were first drawn
# from (green, brown, tan). Kits and the UI talk in roles instead, so a blue
# brand never has to set "green". Order is the order the kit editor shows.

ROLES = [
    # (role, token, label, what it colours)
    ("background",      "ground",       "Background",          "Default slide background"),
    ("background_alt",  "ground-warm",  "Background, alt",     "Quiet alternate background"),
    ("soft",            "cream",        "Soft background",     "Third background and soft cards"),
    ("text",            "ink",          "Headings",            "Headlines and strong text"),
    ("text_secondary",  "ink-soft",     "Secondary text",      "Sub-headings and chip text"),
    ("muted",           "muted",        "Muted text",          "Deks and captions"),
    ("accent",          "green",        "Accent",              "Eyebrows, arrows, badges, rules"),
    ("accent_light",    "green-light",  "Accent, light",       "Diagram agent nodes, highlights"),
    ("accent_pale",     "green-pale",   "Accent, pale",        "Pale accent fills"),
    ("card_tint",       "mint-card",    "Tinted card",         "Tinted cards and pills"),
    ("card_tint_alt",   "teal-card",    "Tinted card, alt",    "Second tinted card style"),
    ("card_dark",       "brown-card",   "Filled card",         "Filled (dark) cards"),
    ("card_dark_label", "tan",          "Label on filled",     "Labels on filled cards and dark slides"),
    ("accent_alt",      "tan-warm",     "Second accent",       "Stat labels; the accent on dark slides"),
    ("text_on_tint",    "brown-deep",   "Text on tints",       "Chip and tag text"),
    ("text_soft",       "brown-soft",   "Soft text",           "Supporting copy on cards"),
    ("tint_warm",       "tan-pale",     "Warm tint",           "Warm fills"),
    ("neutral",         "greige",       "Neutral",             "Neutral cards and diagram inputs"),
    ("dark",            "ground-brown", "Dark background",     "Full-bleed statement slides"),
    ("darkest",         "ground-ink",   "Darkest background",  "The darkest full-bleed slides"),
]
ROLE_TO_TOKEN = {r: t for r, t, _, _ in ROLES}
TOKENS = [t for _, t, _, _ in ROLES]

HEX = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")


def clean_colors(colors) -> dict:
    """Keep known tokens with hex values. Accepts role names too."""
    out = {}
    for k, v in (colors or {}).items():
        k = ROLE_TO_TOKEN.get(k, k)
        v = str(v or "").strip()
        if k in TOKENS and HEX.match(v):
            out[k] = v.lower()
    return out


# --- shape ---------------------------------------------------------------------

def _id(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (text or "kit").lower()).strip("-")[:32]
    return s or "kit"


def valid_id(kit_id: str) -> bool:
    return bool(re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", kit_id or ""))


def normalize(kit: dict) -> dict:
    """Coerce a kit (from disk, an upload, or the model) into the stored shape."""
    from generate import normalize_slide  # local: generate imports kits

    kit = dict(kit or {})
    out = {
        "id": kit.get("id") or "",
        "name": str(kit.get("name") or "Untitled kit").strip()[:80],
        "description": str(kit.get("description") or "").strip()[:400],
        "brand": {
            "wordmark": str((kit.get("brand") or {}).get("wordmark") or "").strip()[:40],
            "logo": str((kit.get("brand") or {}).get("logo") or ""),
        },
        "theme": {
            "colors": clean_colors((kit.get("theme") or {}).get("colors")),
            "fonts": {
                "display": str(((kit.get("theme") or {}).get("fonts") or {}).get("display") or "DM Sans"),
                "body": str(((kit.get("theme") or {}).get("fonts") or {}).get("body") or "Inter"),
            },
        },
        "voice": str(kit.get("voice") or "").strip(),
        "slides": [],
        "decks": [],
        "source": kit.get("source") or {},
        "updated": kit.get("updated") or time.time(),
    }

    seen = set()
    for t in kit.get("slides") or []:
        t = dict(t or {})
        tid = _id(t.get("id") or t.get("name") or "slide")
        while tid in seen:
            tid = f"{tid}-{uuid.uuid4().hex[:3]}"
        seen.add(tid)
        out["slides"].append({
            "id": tid,
            "name": str(t.get("name") or tid),
            "category": str(t.get("category") or "Slide"),
            "note": str(t.get("note") or ""),
            "slide": normalize_slide(t.get("slide") or {}),
        })

    for d in kit.get("decks") or []:
        d = dict(d or {})
        ids = [i for i in (d.get("slide_ids") or []) if i in seen]
        if not ids:
            continue
        out["decks"].append({
            "id": _id(d.get("id") or d.get("name") or "deck"),
            "name": str(d.get("name") or "Deck"),
            "category": "Deck",
            "note": str(d.get("note") or ""),
            "slide_ids": ids,
        })
    return out


# --- storage -------------------------------------------------------------------

def kit_dir(kit_id: str) -> Path:
    if not valid_id(kit_id):
        raise ValueError("bad kit id")
    return KITS / kit_id


def exists(kit_id: str) -> bool:
    return valid_id(kit_id) and (KITS / kit_id / "kit.json").exists()


def load(kit_id: str) -> dict | None:
    if not exists(kit_id):
        return None
    try:
        kit = json.loads((kit_dir(kit_id) / "kit.json").read_text())
    except json.JSONDecodeError:
        return None
    kit["id"] = kit_id
    return kit


def load_or_default(kit_id: str | None) -> dict:
    return load(kit_id or "") or load(DEFAULT_KIT) or normalize({"id": DEFAULT_KIT})


def new_id(name: str) -> str:
    base = _id(name)
    kid = base
    while (KITS / kid).exists():
        kid = f"{base}-{uuid.uuid4().hex[:4]}"
    return kid


def save(kit: dict, kit_id: str | None = None) -> dict:
    kit = normalize(kit)
    kit_id = kit_id or kit.get("id") or new_id(kit["name"])
    kit["id"] = kit_id
    kit["updated"] = time.time()
    d = kit_dir(kit_id)
    d.mkdir(parents=True, exist_ok=True)
    (d / "kit.json").write_text(json.dumps(kit, indent=2, ensure_ascii=False))
    # Fonts have to be on disk before anything renders in them.
    for fam in kit["theme"]["fonts"].values():
        fonts.install(fam)
    return kit


def delete(kit_id: str):
    if kit_id == DEFAULT_KIT:
        raise ValueError("The starter kit can't be deleted.")
    d = kit_dir(kit_id)
    if d.exists():
        shutil.rmtree(d)


def list_all() -> list[dict]:
    out = []
    for p in sorted(KITS.glob("*/kit.json")):
        kit = load(p.parent.name)
        if kit:
            out.append(kit)
    out.sort(key=lambda k: (k["id"] != DEFAULT_KIT, -(k.get("updated") or 0)))
    return out


# --- logo ----------------------------------------------------------------------

def set_logo(kit_id: str, filename: str, data: bytes) -> dict:
    kit = load(kit_id)
    if not kit:
        raise ValueError("no such kit")
    ext = Path(filename or "").suffix.lower()
    if ext not in LOGO_EXTS:
        raise ValueError(f"Logo must be one of {', '.join(sorted(LOGO_EXTS))}.")
    if len(data) > MAX_LOGO_BYTES:
        raise ValueError("Logo must be under 2 MB.")
    d = kit_dir(kit_id)
    for old in d.glob("logo.*"):
        old.unlink()
    (d / f"logo{ext}").write_bytes(data)
    kit.setdefault("brand", {})["logo"] = f"logo{ext}"
    return save(kit, kit_id)


def clear_logo(kit_id: str) -> dict:
    kit = load(kit_id)
    if not kit:
        raise ValueError("no such kit")
    for old in kit_dir(kit_id).glob("logo.*"):
        old.unlink()
    kit.setdefault("brand", {})["logo"] = ""
    return save(kit, kit_id)


def logo_data_uri(kit: dict) -> str:
    """The logo inlined, so exports and standalone HTML carry it with them."""
    name = (kit.get("brand") or {}).get("logo") or ""
    if not name or "/" in name or not valid_id(kit.get("id") or ""):
        return ""
    p = kit_dir(kit["id"]) / name
    if not p.exists():
        return ""
    mime = mimetypes.guess_type(p.name)[0] or "image/png"
    if p.suffix == ".svg":
        mime = "image/svg+xml"
    return f"data:{mime};base64,{base64.b64encode(p.read_bytes()).decode()}"


# --- what the renderer and the Templates tab need --------------------------------

def render_info(kit: dict) -> dict:
    """The slice of a kit a deck needs to render: theme, wordmark, logo."""
    return {
        "id": kit.get("id"),
        "name": kit.get("name"),
        "theme": kit.get("theme") or {},
        "wordmark": (kit.get("brand") or {}).get("wordmark") or "",
        "logo": logo_data_uri(kit),
    }


def catalogue(kit: dict) -> list[dict]:
    """Deck skeletons then slide templates, with slides resolved for preview."""
    by_id = {t["id"]: t["slide"] for t in kit.get("slides") or []}
    decks = [
        {**d, "kind": "deck",
         "slides": [by_id[i] for i in d["slide_ids"] if i in by_id],
         "count": len(d["slide_ids"])}
        for d in kit.get("decks") or []
    ]
    slides = [{**t, "kind": "slide"} for t in kit.get("slides") or []]
    return decks + slides


def new_template_id(kit: dict, name: str) -> str:
    have = {t["id"] for t in kit.get("slides") or []}
    base = _id(name)
    tid = base
    while tid in have:
        tid = f"{base}-{uuid.uuid4().hex[:3]}"
    return tid


def get_template(kit: dict, template_id: str) -> dict | None:
    return next((t for t in catalogue(kit) if t["id"] == template_id), None)


# --- share: export / import ------------------------------------------------------

def export_zip(kit_id: str) -> bytes:
    kit = load(kit_id)
    if not kit:
        raise ValueError("no such kit")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        shared = {k: v for k, v in kit.items() if k not in ("updated",)}
        z.writestr("kit.json", json.dumps(shared, indent=2, ensure_ascii=False))
        logo = (kit.get("brand") or {}).get("logo")
        if logo and (kit_dir(kit_id) / logo).exists():
            z.write(kit_dir(kit_id) / logo, logo)
    return buf.getvalue()


def import_file(filename: str, data: bytes) -> dict:
    """Import a kit someone shared: a .zip from export_zip, or a bare kit.json."""
    logo_name, logo_bytes = "", b""
    if filename.lower().endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            names = z.namelist()
            kj = next((n for n in names if n.rsplit("/", 1)[-1] == "kit.json"), None)
            if not kj:
                raise ValueError("That zip has no kit.json in it.")
            raw = json.loads(z.read(kj))
            for n in names:
                base = n.rsplit("/", 1)[-1]
                if base.startswith("logo.") and Path(base).suffix.lower() in LOGO_EXTS:
                    info = z.getinfo(n)
                    if info.file_size <= MAX_LOGO_BYTES:
                        logo_name, logo_bytes = base, z.read(n)
                    break
    else:
        raw = json.loads(data)
    if not isinstance(raw, dict) or not (raw.get("slides") or raw.get("theme")):
        raise ValueError("That doesn't look like a kit.")

    raw.pop("id", None)
    raw.setdefault("brand", {})["logo"] = ""
    kit = save(raw, new_id(raw.get("name") or "imported kit"))
    if logo_bytes:
        kit = set_logo(kit["id"], logo_name, logo_bytes)
    return kit


def duplicate(kit_id: str) -> dict:
    kit = load(kit_id)
    if not kit:
        raise ValueError("no such kit")
    copy = json.loads(json.dumps(kit))
    copy["name"] = f"{kit['name']} (copy)"
    copy["brand"]["logo"] = ""
    new = save(copy, new_id(copy["name"]))
    logo = (kit.get("brand") or {}).get("logo")
    if logo and (kit_dir(kit_id) / logo).exists():
        new = set_logo(new["id"], logo, (kit_dir(kit_id) / logo).read_bytes())
    return new
