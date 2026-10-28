"""Install Google Fonts on demand, self-hosted.

Fonts are downloaded and served from static/fonts so a deck renders and exports
identically with no network — the same reason DM Sans and Inter are vendored.
"""

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).parent
FONT_DIR = ROOT / "static" / "fonts"
INSTALLED_CSS = FONT_DIR / "installed.css"
INSTALLED_CSS.touch(exist_ok=True)  # gitignored; the pages link it either way

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

# Bundled with the app; never re-downloaded.
BUILT_IN = {"dm sans", "inter"}

# Axis specs tried in order. Variable fonts answer the first, static families
# fall through to the bare name.
SPECS = [
    "{f}:ital,wght@0,300..900;1,300..900",
    "{f}:ital,wght@0,400;0,700;1,400;1,700",
    "{f}:wght@300..900",
    "{f}:wght@400;700",
    "{f}",
]


def _curl(url: str) -> str:
    r = subprocess.run(["curl", "-sS", "-A", UA, url],
                       capture_output=True, text=True, timeout=45)
    return r.stdout if r.returncode == 0 else ""


def installed() -> set[str]:
    """Families available to a deck right now, lowercased."""
    have = set(BUILT_IN)
    if INSTALLED_CSS.exists():
        have |= {m.lower() for m in
                 re.findall(r"font-family:\s*'([^']+)'", INSTALLED_CSS.read_text())}
    return have


def install(family: str) -> tuple[bool, str]:
    """Fetch `family` from Google Fonts and self-host it.

    Returns (ok, message). Already-present families short-circuit, so this is
    safe to call on every request.
    """
    family = (family or "").strip()
    if not family:
        return False, "No font family given."
    if family.lower() in installed():
        return True, f"{family} was already available."

    FONT_DIR.mkdir(parents=True, exist_ok=True)
    q = family.replace(" ", "+")

    css = ""
    for spec in SPECS:
        css = _curl(f"https://fonts.googleapis.com/css2?family={spec.format(f=q)}&display=swap")
        if "@font-face" in css:
            break
    if "@font-face" not in css:
        return False, (f"Google Fonts has no family called \"{family}\". "
                       "Check the exact spelling on fonts.google.com.")

    blocks, seen = [], set()
    for _, subset, block in re.findall(
        r"(/\*\s*([\w-]+)\s*\*/\s*)?(@font-face\s*\{[^}]*\})", css
    ):
        # latin only — other subsets are dead weight for these decks.
        if subset and subset not in ("latin", "latin-ext"):
            continue
        m = re.search(r"url\((https://[^)]+\.woff2)\)", block)
        if not m:
            continue
        src = m.group(1)
        name = src.rsplit("/", 1)[-1]
        if name in seen:
            continue
        seen.add(name)
        target = FONT_DIR / name
        if not target.exists():
            r = subprocess.run(["curl", "-sS", "-A", UA, "-o", str(target), src],
                               capture_output=True, timeout=60)
            if r.returncode != 0 or not target.exists():
                continue
        blocks.append(block.replace(src, f"/static/fonts/{name}"))

    if not blocks:
        return False, f"Found \"{family}\" but could not download any web font files."

    with INSTALLED_CSS.open("a") as fh:
        fh.write("\n".join(blocks) + "\n")
    return True, f"Installed {family} ({len(blocks)} weights)."
