"""Turn a prompt or a pasted document into a deck in a brand kit's style.

Uses Claude Opus 5 with structured outputs, so the model returns deck JSON that
is guaranteed to match the schema the renderer expects — no prose parsing, no
"model forgot a field" failures.
"""

import json
import os

import anthropic
from dotenv import load_dotenv

# override=True: the shell profile exports a stale ANTHROPIC_API_KEY that would
# otherwise win over the project's .env.
load_dotenv(override=True)

MODEL = os.environ.get("DECK_MODEL") or "claude-opus-5-5"

LAYOUTS = [
    "cover", "section", "statement", "quote", "cards", "columns", "numbered",
    "flow", "stats", "pillrows", "mapping", "cycle", "ledger", "diagram", "bullets",
]
GROUNDS = ["", "warm", "cream", "brown", "ink"]
SHAPES = ["chain", "loop"]
DIAGRAM_KINDS = ["input", "automation", "agent", "human", "output", "accent"]
VARIANTS = ["brown", "mint", "outline", "teal", "cream"]

# --- structured output schema -------------------------------------------------
# Every field is required; unused fields carry "" or []. That keeps the schema
# strict-mode valid (no optional keys, additionalProperties: false everywhere)
# while still letting one flat slide shape serve all eleven layouts.

ITEM_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["label", "body", "bullets", "value", "group"],
    "properties": {
        "label": {"type": "string", "description": "Card title, stat label, or pill text. '' if unused."},
        "body": {"type": "string", "description": "Card body copy or stat caption. '' if using bullets."},
        "bullets": {"type": "array", "items": {"type": "string"},
                    "description": "Bullet lines for 'columns'. [] if using body."},
        "value": {"type": "string",
                  "description": "Big number for 'stats', or the pinned badge on 'columns'. e.g. '$50mn'. '' if unused."},
        "group": {"type": "string",
                  "description": "For 'numbered' only: the heading this card sits under. Cards sharing a group are grouped. '' otherwise."},
    },
}

SLIDE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["layout", "ground", "eyebrow", "title", "dek", "variant",
                 "shape", "returnLabel", "items", "footer", "footerAccent"],
    "properties": {
        "layout": {"type": "string", "enum": LAYOUTS},
        "shape": {"type": "string", "enum": SHAPES,
                  "description": "For 'diagram' only. 'chain' is a straight left-to-right "
                                 "sequence; 'loop' wraps the chain onto multiple rows and "
                                 "draws a return path. '' elsewhere."},
        "returnLabel": {"type": "string",
                        "description": "For a 'loop' diagram: the caption on the return "
                                       "path, e.g. 'each cycle feeds the next'. '' elsewhere."},
        "ground": {"type": "string", "enum": GROUNDS,
                   "description": "Slide background. '' is the kit's default background. Use 'brown' (the kit's dark "
                                  "background) for a full-bleed statement or closing slide, 'ink' for "
                                  "the darkest; 'warm'/'cream' are quiet alternates. Use sparingly — at most two dark slides per deck."},
        "eyebrow": {"type": "string", "description": "Small accent-coloured kicker above the headline, e.g. 'Problem Statement'. '' if none."},
        "title": {"type": "string", "description": "The headline. On 'quote' this is the quote itself."},
        "dek": {"type": "string", "description": "One or two sentences under the headline. '' if none."},
        "variant": {"type": "string", "enum": VARIANTS, "description": "Card treatment for this slide."},
        "items": {"type": "array", "items": ITEM_SCHEMA},
        "footer": {"type": "string", "description": "Closing line beneath the body. '' if none."},
        "footerAccent": {"type": "string", "enum": ["", "green"],
                         "description": "'green' renders the footer as an italic takeaway in the accent colour above a rule."},
    },
}

DECK_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["title", "slides"],
    "properties": {
        "title": {"type": "string", "description": "Deck name, for the file list."},
        "slides": {"type": "array", "items": SLIDE_SCHEMA},
    },
}

BASE_SYSTEM = """You build presentation decks in one brand's house style. The brand kit below sets
the voice and the slide patterns this brand already uses.

## Layout vocabulary

Pick the layout that fits the content. Do not default to one layout repeatedly.

- `cover` — opening slide. title + dek. No eyebrow, no items.
- `section` — a divider announcing a new part. eyebrow + title, optional dek.
- `statement` — one centred sentence that lands hard. Use sparingly, max once or twice.
- `quote` — a verbatim quote. Put the quote in `title`, the attribution in `dek`.
- `cards` — 2 to 6 parallel points of roughly equal weight. items = label + body.
- `columns` — 2 to 4 columns of bullets, each optionally pinned with a `value` badge.
  Use when each column has several supporting facts rather than one paragraph.
- `numbered` — two or three numbered themes, each holding its own small cards.
  Set `group` on every item to the theme it belongs to.
- `flow` — a sequence of 3 stages joined by arrows. Cause and effect, or a pipeline.
- `stats` — 2 to 4 headline numbers. items = label + value + body caption.
  The `label` is a short tag of 1 to 4 words ("Reach", "Beachhead", "1-year target"),
  never a sentence. The sentence goes in `body`. `value` is the bare figure.
- `pillrows` — a labelled term mapped to its definition, 3 to 5 rows. Good for taxonomies.
- `mapping` — two columns of pills joined by one arrow: what goes in, what comes out.
  Set `group` on every item to its column heading. Set `value` to "ghost" for items
  that are planned rather than live, "solid" for the one that is emphasised.
- `cycle` — exactly 6 steps in a closed loop, for a flywheel or feedback loop.
  Each item is one step; use `label` only, kept to a short phrase.
- `ledger` — two columns of line items with amounts, for use of funds, pricing, or a
  hiring plan. `group` is the column heading, `label` the line, `body` an optional
  sub-line, `value` the amount. An item with an empty `label` renders as a footnote
  under its column.
- `diagram` — a workflow or pipeline as typed nodes joined by arrows. Each item is a
  node: `label` is the step, `body` a short sublabel, `value` the small chip above it,
  and `group` the node kind — one of input, automation, agent, human, output, accent.
  The legend builds itself from the kinds you use, so use them meaningfully. Set
  `shape` to "loop" for a feedback cycle (it wraps rows and draws a return path, and
  `returnLabel` captions that path) or "chain" for a straight sequence.
- `bullets` — a plain list. The fallback when nothing more structured fits.

## Rules that matter

- Slide copy is not prose. Headlines are claims, not topics: "Outputs multiplied but
  outcomes didn't", never "Overview of the problem".
- Card body copy runs 1 to 3 short sentences. If it needs more, it is two cards.
- Never invent statistics, company names, customer names, or dollar figures. Use only
  numbers present in the source material. If the user gave you no numbers, do not
  produce a `stats` slide.
- `variant` is per-slide, not per-card. Alternate across the deck so consecutive
  slides don't look identical — `brown` is the filled dark card and reads as
  heavy/problem, `mint` (tinted) and `outline` as lighter/solution, `teal` is a second
  tint, `cream` reads as neutral. The names are internal; the kit sets the colours.
- Set `footerAccent` to "green" only for a genuine closing takeaway on that slide.
- Write in the brand's voice (below). Where the kit says nothing, default to direct
  and concrete, with no marketing throat-clearing, emoji or exclamation marks.

## Scope

Deliver exactly the deck asked for at the length asked for. If no length is given,
8 to 14 slides. Do not add appendix, thank-you, agenda, or Q&A slides unless asked.
Cover the substance and stop — do not pad with filler sections."""


def _client():
    return anthropic.Anthropic()


def _final_message(client, **kwargs):
    """Stream a request and return the final message.

    Streams because a full deck plus adaptive thinking can run long enough to
    trip the SDK's non-streaming timeout guard. Opts into server-side refusal
    fallbacks where the account has the beta, and degrades quietly where it
    does not.
    """
    try:
        with client.beta.messages.stream(
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            **kwargs,
        ) as stream:
            return stream.get_final_message()
    except (anthropic.BadRequestError, anthropic.PermissionDeniedError, TypeError):
        with client.messages.stream(**kwargs) as stream:
            return stream.get_final_message()


def kit_system(kit: dict | None) -> str:
    """BASE_SYSTEM plus the kit's voice and the slide patterns it already uses.

    The patterns go in as compact examples, not as a script: they show the model
    what this brand's slides look like so it reaches for the same layouts and
    card treatments, without copying their placeholder copy.
    """
    if not kit:
        return BASE_SYSTEM
    parts = [BASE_SYSTEM, f"\n\n## The brand kit: {kit.get('name') or 'Untitled'}"]
    if kit.get("description"):
        parts.append(f"\n{kit['description']}")
    if (kit.get("voice") or "").strip():
        parts.append(f"\n\n### Voice\n\n{kit['voice'].strip()}")
    examples = []
    for t in (kit.get("slides") or [])[:24]:
        s = t.get("slide") or {}
        bits = [f"- **{t.get('name')}** ({s.get('layout')}"]
        if s.get("variant") and s.get("layout") in ("cards", "columns", "numbered", "flow", "cycle"):
            bits.append(f", variant {s['variant']}")
        if s.get("ground"):
            bits.append(f", ground {s['ground']}")
        bits.append(")")
        if t.get("note"):
            bits.append(f": {t['note']}")
        if s.get("eyebrow"):
            bits.append(f' Eyebrow style: "{s["eyebrow"]}".')
        examples.append("".join(bits))
    if examples:
        parts.append(
            "\n\n### Slide patterns this brand uses\n\n"
            "Prefer these layouts and treatments, in roughly this proportion. "
            "Their copy is placeholder text; never reuse it.\n\n" + "\n".join(examples)
        )
    arcs = [f"- {d['name']}: {d.get('note', '')}" for d in (kit.get("decks") or [])]
    if arcs:
        parts.append("\n\n### Deck arcs this brand uses\n\n" + "\n".join(arcs))
    return "".join(parts)


def _require_key():
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Copy .env.example to .env and add your key."
        )


def _text(message) -> str:
    # Refusals arrive as a 200, so check before touching content.
    if message.stop_reason == "refusal":
        detail = getattr(getattr(message, "stop_details", None), "explanation", None)
        raise RuntimeError(f"The model declined this request ({detail or 'no explanation given'}).")
    text = next((b.text for b in message.content if b.type == "text"), "")
    if not text:
        raise RuntimeError(f"Empty response (stop_reason={message.stop_reason}).")
    return text


def generate_deck(brief: str, slide_count: int = 0, notes: str = "",
                  kit: dict | None = None) -> dict:
    """Build a deck from a brief, an outline, or a full pasted document."""
    _require_key()

    ask = [f"Build a deck from the following.\n\n<source>\n{brief.strip()}\n</source>"]
    if slide_count:
        ask.append(f"\nMake it exactly {slide_count} slides.")
    if notes.strip():
        ask.append(f"\nAdditional direction:\n{notes.strip()}")

    message = _final_message(
        _client(),
        model=MODEL,
        max_tokens=32000,
        system=kit_system(kit),
        messages=[{"role": "user", "content": "".join(ask)}],
        output_config={
            "effort": "high",
            "format": {"type": "json_schema", "schema": DECK_SCHEMA},
        },
    )
    return normalize(json.loads(_text(message)))


def rewrite_slide(slide: dict, instruction: str, kit: dict | None = None) -> dict:
    """Rewrite a single slide in place from a plain-English instruction."""
    _require_key()
    message = _final_message(
        _client(),
        model=MODEL,
        max_tokens=8000,
        system=kit_system(kit),
        messages=[{
            "role": "user",
            "content": (
                "Here is one slide of an existing deck:\n\n"
                f"{json.dumps(slide, indent=2)}\n\n"
                f"Rewrite it: {instruction.strip()}\n\n"
                "Return the single revised slide. Keep everything the instruction "
                "does not ask you to change."
            ),
        }],
        output_config={
            "effort": "medium",
            "format": {"type": "json_schema", "schema": SLIDE_SCHEMA},
        },
    )
    out = normalize_slide(json.loads(_text(message)))
    if slide.get("art"):
        out["art"] = slide["art"]
    return out


# --- shape guards -------------------------------------------------------------
# Structured outputs guarantee the schema, but decks also arrive from disk and
# from hand edits, so normalize on every path into the renderer.

from kits import TOKENS as COLOR_TOKENS, clean_colors  # noqa: E402


def normalize_slide(s: dict) -> dict:
    s = dict(s or {})
    theme = s.get("theme") or {}
    colors = clean_colors(theme.get("colors"))
    if colors:
        s["theme"] = {"colors": colors}
    else:
        s.pop("theme", None)
    s["layout"] = s.get("layout") if s.get("layout") in LAYOUTS else "cards"
    s["variant"] = s.get("variant") if s.get("variant") in VARIANTS else "mint"
    s["ground"] = s.get("ground") if s.get("ground") in GROUNDS else ""
    s["shape"] = s.get("shape") if s.get("shape") in SHAPES else ""
    for k in ("eyebrow", "title", "dek", "footer", "footerAccent", "returnLabel"):
        s[k] = str(s.get(k) or "")
    items = []
    for it in s.get("items") or []:
        it = dict(it or {})
        bullets = [str(b) for b in (it.get("bullets") or []) if str(b).strip()]
        items.append({
            "label": str(it.get("label") or ""),
            "body": str(it.get("body") or ""),
            "bullets": bullets,
            "value": str(it.get("value") or ""),
            "group": str(it.get("group") or ""),
        })
    s["items"] = items
    return s


def normalize(deck: dict) -> dict:
    deck = dict(deck or {})
    deck["title"] = str(deck.get("title") or "Untitled deck")
    deck["slides"] = [normalize_slide(s) for s in (deck.get("slides") or [])]
    deck.pop("_kit", None)  # resolved at read time, never stored
    if deck.get("theme"):
        t = deck["theme"]
        colors = clean_colors(t.get("colors"))
        fonts_ = {k: str(v) for k, v in (t.get("fonts") or {}).items()
                  if k in ("display", "body") and v}
        deck["theme"] = {k: v for k, v in (("colors", colors), ("fonts", fonts_)) if v}
        if not deck["theme"]:
            deck.pop("theme")
    return deck
