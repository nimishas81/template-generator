"""Conversational editing for a deck.

Claude drives real tools that mutate the deck in place — copy, layout, palette
and typeface — rather than describing changes for you to make by hand. Fonts are
fetched from Google Fonts on demand and self-hosted.
"""

import json

import anthropic
from anthropic import beta_tool
from dotenv import load_dotenv

import fonts
from generate import (COLOR_TOKENS, DIAGRAM_KINDS, GROUNDS, LAYOUTS, SHAPES,
                      VARIANTS, normalize)

load_dotenv(override=True)

from generate import MODEL  # noqa: E402
import kits  # noqa: E402

SLIDE_FIELDS = ["eyebrow", "title", "dek", "footer", "footerAccent",
                "layout", "variant", "ground", "shape", "returnLabel"]
ITEM_FIELDS = ["label", "body", "value", "group"]

SYSTEM = f"""You are editing one slide deck, live, in a deck builder.
Every change you make is applied and re-rendered immediately.

## What the tokens mean

Colours are design-system tokens, not per-element colours. `set_color` changes one
across the whole deck, which keeps it coherent — that is the default and the right
tool for "make it warmer" or "change the accent".

`set_slide_color` overrides a token on a single slide. Reach for it only when the
request is explicitly about one slide ("make slide 4's headline red"). It still
works in tokens, so it recolours everything on that slide drawn with that token —
if a slide's only `ink` text is its headline, setting `ink` there recolours the
headline alone. Say so plainly rather than implying finer control than exists.

The token names are historical; what each one colours is what matters:

{chr(10).join(f"- `{t}`: {label.lower()} ({what.lower()})" for _, t, label, what in kits.ROLES)}

The deck's brand kit sets the base palette. Overrides you set sit on top of it,
and resetting drops back to the kit.

Fonts: `display` is headings, numerals and labels; `body` is running copy.
Any Google Fonts family works — it is downloaded and self-hosted so exports keep
working offline. Use the exact family name from fonts.google.com.

## Layouts

{", ".join(LAYOUTS)}. Card variants: {", ".join(VARIANTS)}.
Variant names are internal: brown = filled dark cards, mint = tinted, teal = second
tint, cream = soft, outline = bordered. Backgrounds: the kit default (empty string),
warm and cream (quiet alternates), brown (dark, full bleed), ink (darkest).

On a `diagram` slide, each item is a node: `label` is the step, `body` a short
sublabel, `value` the chip above it, and `group` the node kind — one of
{", ".join(DIAGRAM_KINDS)}. The legend generates itself from the kinds used, so pick
them meaningfully rather than decoratively. `shape` is "chain" or "loop"; on a loop,
`returnLabel` captions the return path.

## Numbering

Slides and items are numbered from 1, exactly as the app shows them. "Slide 2"
means the second slide. Never offset by one.

## How to work

- Do what was asked and stop. Don't rewrite slides that weren't mentioned, and
  don't "improve" copy nobody complained about.
- When asked for a mood rather than a value ("warmer", "more serious"), pick
  concrete hexes that keep enough contrast to stay readable, and say what you chose.
- Write new copy in the brand's voice (below, if the kit has one): otherwise direct
  and concrete, no marketing throat-clearing, no emoji, no exclamation marks.
- Reply in one or two sentences, plain prose, naming what you changed. No preamble,
  no bullet lists, no restating the whole deck back."""


def _summary(deck: dict) -> str:
    """Compact view of deck state for the model — full JSON is mostly noise."""
    out = [f'Deck "{deck.get("title", "")}" · {len(deck.get("slides", []))} slides']
    theme = deck.get("theme") or {}
    if theme.get("colors"):
        out.append("Colour overrides: " +
                   ", ".join(f"{k}={v}" for k, v in theme["colors"].items()))
    if theme.get("fonts"):
        f = theme["fonts"]
        out.append(f"Font overrides: display={f.get('display', '(kit)')}, "
                   f"body={f.get('body', '(kit)')}")
    # 1-based throughout, matching the slide numbers shown in the app.
    for i, s in enumerate(deck.get("slides", []), start=1):
        head = f'Slide {i}: {s.get("layout")}'
        if s.get("variant"):
            head += f"/{s['variant']}"
        if s.get("ground"):
            head += f" bg={s['ground']}"
        own = ((s.get("theme") or {}).get("colors")) or {}
        if own:
            head += "  own colours: " + ", ".join(f"{k}={v}" for k, v in own.items())
        out.append(head)
        for k in ("eyebrow", "title", "dek", "footer"):
            if s.get(k):
                out.append(f'      {k}: {s[k]}')
        for j, it in enumerate(s.get("items") or [], start=1):
            bits = [f"{k}={it[k]!r}" for k in ITEM_FIELDS if it.get(k)]
            if it.get("bullets"):
                bits.append(f"bullets={len(it['bullets'])}")
            if bits:
                out.append(f"      item {j}: " + ", ".join(bits))
    return "\n".join(out)


def _tools(deck: dict):
    """Tools bound to this deck. Each mutates `deck` in place."""

    # Every index crossing the tool boundary is 1-based, matching the numbers
    # the app shows. Anything else invites off-by-one edits to the wrong slide.
    def slide_at(number):
        slides = deck.get("slides") or []
        if not 1 <= number <= len(slides):
            return None
        return slides[number - 1]

    def item_at(slide, number):
        items = slide.setdefault("items", [])
        if not 1 <= number <= len(items):
            return None
        return items[number - 1]

    @beta_tool
    def set_color(token: str, hex_value: str) -> str:
        """Override one palette token for this deck.

        Args:
            token: Token name, e.g. "green", "ink", "ground", "brown-card".
            hex_value: Colour as hex, e.g. "#4bc46e".
        """
        if token not in COLOR_TOKENS:
            return f"Unknown token {token!r}. Valid tokens: {', '.join(COLOR_TOKENS)}"
        v = hex_value.strip()
        if not v.startswith("#") or len(v) not in (4, 7, 9):
            return f"{hex_value!r} is not a hex colour."
        deck.setdefault("theme", {}).setdefault("colors", {})[token] = v
        return f"{token} is now {v}."

    @beta_tool
    def reset_colors() -> str:
        """Drop the deck-wide colour overrides and return to the brand kit's palette."""
        (deck.get("theme") or {}).pop("colors", None)
        return "Palette reset to the kit's colours."

    @beta_tool
    def set_slide_color(slide: int, token: str, hex_value: str) -> str:
        """Override a palette token on ONE slide, leaving the rest of the deck alone.

        Use this only when the change is meant to apply to a single slide — to
        make one slide's headline a different colour, for example. For a change
        that should run through the whole deck, use set_color instead.

        Args:
            slide: Slide number as shown in the app, starting at 1.
            token: Token name, e.g. "ink" for the headline, "ground" for the
                background, "green" for the accent.
            hex_value: Colour as hex, e.g. "#b3542a".
        """
        s = slide_at(slide)
        if s is None:
            return f"There is no slide {slide}."
        if token not in COLOR_TOKENS:
            return f"Unknown token {token!r}. Valid tokens: {', '.join(COLOR_TOKENS)}"
        v = hex_value.strip()
        if not v.startswith("#") or len(v) not in (4, 7, 9):
            return f"{hex_value!r} is not a hex colour."
        s.setdefault("theme", {}).setdefault("colors", {})[token] = v
        return f"Slide {slide} {token} is now {v}."

    @beta_tool
    def reset_slide_colors(slide: int) -> str:
        """Remove one slide's colour overrides so it follows the deck again.

        Args:
            slide: Slide number as shown in the app, starting at 1.
        """
        s = slide_at(slide)
        if s is None:
            return f"There is no slide {slide}."
        s.pop("theme", None)
        return f"Slide {slide} follows the deck palette again."

    @beta_tool
    def set_font(role: str, family: str) -> str:
        """Set a typeface, downloading it from Google Fonts if needed.

        Args:
            role: Either "display" (headings, numerals) or "body" (running copy).
            family: Google Fonts family name, e.g. "Fraunces", "Space Grotesk".
        """
        if role not in ("display", "body"):
            return 'role must be "display" or "body".'
        ok, msg = fonts.install(family)
        if not ok:
            return msg
        deck.setdefault("theme", {}).setdefault("fonts", {})[role] = family
        return f"{msg} {role} is now {family}."

    @beta_tool
    def edit_slide(slide: int, field: str, value: str) -> str:
        """Set one field on one slide.

        Args:
            slide: Slide number as shown in the app, starting at 1.
            field: One of eyebrow, title, dek, footer, footerAccent, layout,
                variant, ground, shape, returnLabel. `shape` is "chain" or
                "loop" and applies to diagram slides; `returnLabel` captions a
                loop's return path.
            value: The new value. Empty string clears the field.
        """
        index = slide
        s = slide_at(index)
        if s is None:
            return f"There is no slide {index}."
        if field not in SLIDE_FIELDS:
            return f"Unknown field {field!r}. Valid: {', '.join(SLIDE_FIELDS)}"
        checks = {"layout": LAYOUTS, "variant": VARIANTS, "ground": GROUNDS,
                  "shape": SHAPES + [""], "footerAccent": ["", "green"]}
        if field in checks and value not in checks[field]:
            return f"{value!r} is not valid for {field}. Valid: {checks[field]}"
        s[field] = value
        return f"Slide {index} {field} updated."

    @beta_tool
    def edit_item(slide: int, item: int, field: str, value: str) -> str:
        """Set one field on one card, column, row or step within a slide.

        Args:
            slide: Slide number as shown in the app, starting at 1.
            item: Item number within that slide, starting at 1.
            field: One of label, body, value, group.
            value: The new value.
        """
        s = slide_at(slide)
        if s is None:
            return f"There is no slide {slide}."
        target = item_at(s, item)
        if target is None:
            return f"Slide {slide} has {len(s.get('items') or [])} items."
        if field not in ITEM_FIELDS:
            return f"Unknown field {field!r}. Valid: {', '.join(ITEM_FIELDS)}"
        target[field] = value
        return f"Slide {slide} item {item} {field} updated."

    @beta_tool
    def set_bullets(slide: int, item: int, lines: str) -> str:
        """Replace an item's bullet list.

        Args:
            slide: Slide number as shown in the app, starting at 1.
            item: Item number within that slide, starting at 1.
            lines: One bullet per line. Empty string removes the bullets.
        """
        s = slide_at(slide)
        if s is None:
            return f"There is no slide {slide}."
        target = item_at(s, item)
        if target is None:
            return f"Slide {slide} has {len(s.get('items') or [])} items."
        target["bullets"] = [l for l in lines.split("\n") if l.strip()]
        return f"Slide {slide} item {item} bullets updated."

    @beta_tool
    def add_item(slide: int, label: str, body: str) -> str:
        """Append a card / column / row to a slide.

        Args:
            slide: Slide number as shown in the app, starting at 1.
            label: The item's heading.
            body: The item's copy. May be empty.
        """
        s = slide_at(slide)
        if s is None:
            return f"There is no slide {slide}."
        s.setdefault("items", []).append(
            {"label": label, "body": body, "bullets": [], "value": "", "group": ""})
        return f"Added an item to slide {slide}."

    @beta_tool
    def remove_item(slide: int, item: int) -> str:
        """Delete one card / column / row from a slide.

        Args:
            slide: Slide number as shown in the app, starting at 1.
            item: Item number within that slide, starting at 1.
        """
        s = slide_at(slide)
        if s is None:
            return f"There is no slide {slide}."
        if item_at(s, item) is None:
            return f"Slide {slide} has {len(s.get('items') or [])} items."
        s["items"].pop(item - 1)
        return f"Removed item {item} from slide {slide}."

    @beta_tool
    def add_slide(after_slide: int, layout: str, title: str) -> str:
        """Insert a new slide.

        Args:
            after_slide: Insert after this slide number (1-based). Use 0 to put
                the new slide first.
            layout: One of the deck layouts.
            title: The slide headline.
        """
        if layout not in LAYOUTS:
            return f"{layout!r} is not a layout. Valid: {', '.join(LAYOUTS)}"
        slides = deck.setdefault("slides", [])
        pos = max(0, min(after_slide, len(slides)))
        s = {"layout": layout, "ground": "", "eyebrow": "", "title": title,
             "dek": "", "variant": "mint", "items": [], "footer": "",
             "footerAccent": ""}
        slides.insert(pos, s)
        return f"Inserted a {layout} slide as slide {pos + 1}."

    @beta_tool
    def delete_slide(slide: int) -> str:
        """Delete a slide.

        Args:
            slide: Slide number as shown in the app, starting at 1.
        """
        slides = deck.get("slides") or []
        if not 1 <= slide <= len(slides):
            return f"There is no slide {slide}."
        if len(slides) == 1:
            return "A deck needs at least one slide."
        slides.pop(slide - 1)
        return f"Deleted slide {slide}."

    @beta_tool
    def set_title(title: str) -> str:
        """Rename the deck.

        Args:
            title: The new deck title.
        """
        deck["title"] = title
        return f"Deck renamed to {title!r}."

    return [set_color, reset_colors, set_slide_color, reset_slide_colors, set_font,
            edit_slide, edit_item, set_bullets, add_item, remove_item,
            add_slide, delete_slide, set_title]


def _system(kit: dict | None) -> str:
    if not kit:
        return SYSTEM
    out = [SYSTEM, f"\n\n## Brand kit: {kit.get('name')}"]
    f = (kit.get("theme") or {}).get("fonts") or {}
    out.append(f"\nKit fonts: display {f.get('display', 'DM Sans')}, body {f.get('body', 'Inter')}.")
    if (kit.get("voice") or "").strip():
        out.append(f"\n\n### Voice\n\n{kit['voice'].strip()}")
    return "".join(out)


def respond(deck: dict, history: list, message: str,
            kit: dict | None = None) -> tuple[dict, str]:
    """Run one conversational turn. Returns (updated deck, reply text)."""
    client = anthropic.Anthropic()

    msgs = []
    for turn in history[-12:]:  # recent context is enough; decks are re-sent each turn
        if turn.get("role") in ("user", "assistant") and turn.get("content"):
            msgs.append({"role": turn["role"], "content": turn["content"]})
    msgs.append({
        "role": "user",
        "content": f"<deck_state>\n{_summary(deck)}\n</deck_state>\n\n{message.strip()}",
    })

    runner = client.beta.messages.tool_runner(
        model=MODEL,
        max_tokens=8000,
        system=_system(kit),
        tools=_tools(deck),
        messages=msgs,
        output_config={"effort": "medium"},
    )

    last = None
    for m in runner:
        last = m

    if last is None:
        raise RuntimeError("No response from the model.")
    if last.stop_reason == "refusal":
        raise RuntimeError("The model declined that request.")

    reply = " ".join(b.text for b in last.content if b.type == "text").strip()
    return normalize(deck), reply or "Done."
