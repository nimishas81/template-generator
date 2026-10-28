"""Export a deck to PDF, PNGs, or a standalone HTML file.

Playwright drives the same page the editor renders, so exports cannot drift
from what you saw on screen — there is no second rendering path to keep in sync.
"""

import base64
import io
import re
import zipfile
from pathlib import Path

from playwright.sync_api import sync_playwright

SLIDE_W, SLIDE_H = 1920, 1080
ROOT = Path(__file__).parent


def _page(pw, scale=1):
    browser = pw.chromium.launch()
    page = browser.new_page(
        viewport={"width": SLIDE_W, "height": SLIDE_H},
        device_scale_factor=scale,
    )
    return browser, page


def _settle(page):
    """Wait for webfonts, otherwise the first slide prints in the fallback face."""
    page.wait_for_selector(".slide", timeout=30_000)
    page.evaluate("document.fonts.ready")
    page.wait_for_timeout(300)


def to_pdf(url: str, out_path: Path) -> Path:
    with sync_playwright() as pw:
        browser, page = _page(pw)
        page.goto(url, wait_until="networkidle")
        _settle(page)
        page.pdf(
            path=str(out_path),
            width=f"{SLIDE_W}px",
            height=f"{SLIDE_H}px",
            print_background=True,
            margin={"top": "0", "bottom": "0", "left": "0", "right": "0"},
        )
        browser.close()
    return out_path


def to_pngs(url: str, out_dir: Path, scale: int = 2) -> list[Path]:
    """One PNG per slide, numbered 1..n.

    Shows a single slide at a time and captures the viewport. The alternatives
    are both worse: element.screenshot scrolls each slide into view and waits
    for it to settle (flaky on a 10,000px page), and a full_page clip makes
    Chromium rasterise the whole deck once per slide — at 2x that is ~83
    megapixels of wasted work per capture.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    with sync_playwright() as pw:
        browser, page = _page(pw, scale=scale)
        page.goto(url, wait_until="networkidle")
        _settle(page)

        count = page.evaluate("document.querySelectorAll('.slide').length")
        for i in range(count):
            page.evaluate(
                """(i) => document.querySelectorAll('.slide')
                       .forEach((el, j) => el.style.display = j === i ? 'flex' : 'none')""",
                i,
            )
            p = out_dir / f"{i + 1}.png"
            page.screenshot(path=str(p), animations="disabled")
            written.append(p)
        browser.close()
    return written


def to_png_zip(url: str, scale: int = 2) -> bytes:
    """PNG-per-slide, zipped, matching the numbering of your Gamma exports."""
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        paths = to_pngs(url, Path(td), scale=scale)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for p in paths:
                z.write(p, p.name)
        return buf.getvalue()


def to_standalone_html(url: str) -> str:
    """A single self-contained .html file — fonts and CSS inlined, no server."""
    with sync_playwright() as pw:
        browser, page = _page(pw)
        page.goto(url, wait_until="networkidle")
        _settle(page)
        html = page.content()
        browser.close()

    css = (ROOT / "static/css/theme.css").read_text()
    fonts_css = (ROOT / "static/fonts/fonts.css").read_text()

    # Fonts the chat installed on demand ship too, or a retheme'd deck would
    # fall back to DM Sans / Inter once the file leaves this machine.
    extra = ROOT / "static/fonts/installed.css"
    if extra.exists():
        fonts_css += "\n" + extra.read_text()

    # Inline each woff2 as a data URI so the file travels on its own.
    def embed(m):
        name = m.group(1)
        f = ROOT / "static/fonts" / name
        if not f.exists():
            return m.group(0)
        b64 = base64.b64encode(f.read_bytes()).decode()
        return f"url(data:font/woff2;base64,{b64})"

    fonts_css = re.sub(r"url\(/static/fonts/([^)]+)\)", embed, fonts_css)
    css = css.replace('@import url("/static/fonts/fonts.css");', fonts_css)

    # Drop the page's stylesheet links and scripts, splice in the CSS. The
    # deck's own theme overrides live in <style id="deck-theme">, which is not
    # a <link>, so it survives and keeps colours and fonts correct.
    html = re.sub(r'<link[^>]*rel="stylesheet"[^>]*>', "", html)
    html = re.sub(r"<script\b[^>]*>.*?</script>", "", html, flags=re.S)
    html = html.replace("</head>", f"<style>{css}</style></head>")
    return html
