"""Template Generator — decks in your own brand, from your own templates.

Upload decks you already have, get a brand kit (palette, fonts, voice, slide
templates), and generate new decks in it.

    python3 app.py     →  http://localhost:5055
"""

import copy
import io
import json
import re
import time
import uuid
from pathlib import Path

from flask import Flask, abort, jsonify, render_template, request, send_file

import chat as deck_chat
import export as exporter
import extract
import kits
from generate import generate_deck, normalize, normalize_slide, rewrite_slide

PORT = int(__import__("os").environ.get("PORT") or 5055)
ROOT = Path(__file__).parent
DECKS = ROOT / "decks"
ART = ROOT / "static" / "img" / "art"
DECKS.mkdir(exist_ok=True)
ART.mkdir(parents=True, exist_ok=True)

app = Flask(__name__)
app.json.sort_keys = False
app.config["MAX_CONTENT_LENGTH"] = 80 * 1024 * 1024  # deck uploads


# --- storage ------------------------------------------------------------------

def deck_path(deck_id: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", deck_id or ""):
        abort(400, "bad deck id")
    return DECKS / f"{deck_id}.json"


def load_deck(deck_id: str) -> dict:
    p = deck_path(deck_id)
    if not p.exists():
        abort(404, "no such deck")
    return json.loads(p.read_text())


def save_deck(deck_id: str, deck: dict) -> dict:
    deck = normalize(deck)
    deck["id"] = deck_id
    deck["updated"] = time.time()
    deck_path(deck_id).write_text(json.dumps(deck, indent=2, ensure_ascii=False))
    return deck


def kit_for(deck: dict) -> dict:
    return kits.load_or_default(deck.get("kit"))


def resolved(deck: dict) -> dict:
    """The deck as the renderer needs it: with its kit's theme, wordmark and logo.

    `_kit` is attached on the way out and stripped by normalize() on the way
    back in, so kit edits flow through to every deck that uses the kit.
    """
    kit = kit_for(deck)
    return {**deck, "kit": kit["id"], "_kit": kits.render_info(kit)}


def slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (text or "deck").lower()).strip("-")[:40]
    return f"{s or 'deck'}-{uuid.uuid4().hex[:6]}"


# --- pages --------------------------------------------------------------------

@app.get("/")
def index():
    return render_template("index.html")


@app.get("/render/<deck_id>")
def render_deck(deck_id):
    """Chrome-clean render of a deck. Playwright prints from exactly this."""
    return render_template("deck.html", deck=json.dumps(resolved(load_deck(deck_id))))


# --- deck CRUD ----------------------------------------------------------------

@app.get("/api/decks")
def list_decks():
    out = []
    for p in DECKS.glob("*.json"):
        try:
            d = json.loads(p.read_text())
        except json.JSONDecodeError:
            continue
        out.append({
            "id": p.stem,
            "kit": d.get("kit") or kits.DEFAULT_KIT,
            "title": d.get("title") or p.stem,
            "slides": len(d.get("slides") or []),
            "updated": d.get("updated") or p.stat().st_mtime,
        })
    out.sort(key=lambda d: d["updated"], reverse=True)
    return jsonify(out)


@app.post("/api/decks")
def create_deck():
    body = request.get_json(force=True) or {}
    brief = (body.get("brief") or "").strip()
    if not brief:
        return jsonify(error="Give me something to work from."), 400
    kit = kits.load_or_default(body.get("kit_id"))
    try:
        deck = generate_deck(
            brief,
            slide_count=int(body.get("slide_count") or 0),
            notes=body.get("notes") or "",
            kit=kit,
        )
    except Exception as e:
        return jsonify(error=str(e)), 500
    deck["kit"] = kit["id"]
    return jsonify(resolved(save_deck(slug(deck.get("title")), deck)))


@app.post("/api/decks/blank")
def create_blank():
    body = request.get_json(silent=True) or {}
    kit = kits.load_or_default(body.get("kit_id"))
    deck = {
        "title": "Untitled deck",
        "kit": kit["id"],
        "slides": [
            {"layout": "cover", "title": "Your headline here",
             "dek": "One sentence on who this is for."},
        ],
    }
    return jsonify(resolved(save_deck(slug("untitled"), deck)))


@app.get("/api/templates")
def list_templates():
    return jsonify(kits.catalogue(kits.load_or_default(request.args.get("kit"))))


@app.post("/api/decks/from-template")
def deck_from_template():
    body = request.get_json(force=True) or {}
    kit = kits.load_or_default(body.get("kit_id"))
    t = kits.get_template(kit, body.get("template_id") or "")
    if not t:
        return jsonify(error="No such template."), 404
    slides = t["slides"] if t["kind"] == "deck" else [t["slide"]]
    deck = {"title": t["name"], "kit": kit["id"], "slides": copy.deepcopy(slides)}
    return jsonify(resolved(save_deck(slug(t["name"]), deck)))


@app.get("/api/decks/<deck_id>")
def get_deck(deck_id):
    return jsonify(resolved(load_deck(deck_id)))


@app.put("/api/decks/<deck_id>")
def put_deck(deck_id):
    deck_path(deck_id)  # validates the id
    return jsonify(resolved(save_deck(deck_id, request.get_json(force=True) or {})))


@app.delete("/api/decks/<deck_id>")
def delete_deck(deck_id):
    p = deck_path(deck_id)
    if p.exists():
        p.unlink()
    return jsonify(ok=True)


@app.post("/api/decks/<deck_id>/chat")
def chat_turn(deck_id):
    deck = load_deck(deck_id)
    body = request.get_json(force=True) or {}

    if body.get("clear"):
        deck["chat"] = []
        return jsonify(deck=resolved(save_deck(deck_id, deck)), reply="")

    message = (body.get("message") or "").strip()
    if not message:
        return jsonify(error="Say what you'd like changed."), 400

    history = deck.get("chat") or []
    try:
        deck, reply = deck_chat.respond(deck, history, message, kit=kit_for(deck))
    except Exception as e:
        return jsonify(error=str(e)), 500

    deck["chat"] = (history
                    + [{"role": "user", "content": message},
                       {"role": "assistant", "content": reply}])[-40:]
    return jsonify(deck=resolved(save_deck(deck_id, deck)), reply=reply)


@app.post("/api/decks/<deck_id>/slides/<int:idx>/rewrite")
def rewrite(deck_id, idx):
    deck = load_deck(deck_id)
    slides = deck.get("slides") or []
    if not 0 <= idx < len(slides):
        abort(404, "no such slide")
    instruction = (request.get_json(force=True) or {}).get("instruction", "")
    if not instruction.strip():
        return jsonify(error="Tell me what to change."), 400
    try:
        slides[idx] = rewrite_slide(slides[idx], instruction, kit=kit_for(deck))
    except Exception as e:
        return jsonify(error=str(e)), 500
    return jsonify(resolved(save_deck(deck_id, deck)))


# --- art upload ---------------------------------------------------------------

@app.post("/api/art")
def upload_art():
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify(error="No file."), 400
    ext = Path(f.filename).suffix.lower()
    if ext not in {".png", ".jpg", ".jpeg", ".svg", ".webp", ".gif"}:
        return jsonify(error=f"Unsupported file type: {ext}"), 400
    name = f"{uuid.uuid4().hex[:12]}{ext}"
    f.save(ART / name)
    return jsonify(url=f"/static/img/art/{name}")


# --- kits ---------------------------------------------------------------------

def kit_or_404(kit_id: str) -> dict:
    kit = kits.load(kit_id)
    if not kit:
        abort(404, "no such kit")
    return kit


def kit_out(kit: dict) -> dict:
    return {**kit, "render": kits.render_info(kit)}


@app.get("/api/kits")
def list_kits():
    return jsonify([{
        "id": k["id"], "name": k["name"], "description": k.get("description", ""),
        "slides": len(k.get("slides") or []), "decks": len(k.get("decks") or []),
        "builtin": k["id"] == kits.DEFAULT_KIT, "updated": k.get("updated"),
        "cover": next((t["slide"] for t in k.get("slides") or []
                       if t["slide"].get("layout") == "cover"),
                      (k.get("slides") or [{}])[0].get("slide") if k.get("slides") else None),
        "render": kits.render_info(k),
    } for k in kits.list_all()])


@app.get("/api/kits/roles")
def kit_roles():
    return jsonify([{"role": r, "token": t, "label": l, "help": h}
                    for r, t, l, h in kits.ROLES])


@app.get("/api/kits/<kit_id>")
def get_kit(kit_id):
    return jsonify(kit_out(kit_or_404(kit_id)))


@app.put("/api/kits/<kit_id>")
def put_kit(kit_id):
    kit = kit_or_404(kit_id)
    body = request.get_json(force=True) or {}
    for k in ("name", "description", "voice", "slides", "decks"):
        if k in body:
            kit[k] = body[k]
    if "brand" in body:
        kit["brand"]["wordmark"] = (body["brand"] or {}).get("wordmark", "")
    if "theme" in body:
        kit["theme"] = body["theme"] or {}
    return jsonify(kit_out(kits.save(kit, kit_id)))


@app.post("/api/kits/from-upload")
def kit_from_upload():
    files = [(f.filename, f.read()) for f in request.files.getlist("files") if f and f.filename]
    if not files:
        return jsonify(error="Upload at least one deck."), 400
    try:
        kit = extract.build_kit(files, name=request.form.get("name") or "",
                                notes=request.form.get("notes") or "")
    except ValueError as e:
        return jsonify(error=str(e)), 400
    except Exception as e:
        return jsonify(error=str(e)), 500
    return jsonify(kit_out(kit))


@app.post("/api/kits/import")
def kit_import():
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify(error="No file."), 400
    try:
        kit = kits.import_file(f.filename, f.read())
    except (ValueError, json.JSONDecodeError, Exception) as e:
        return jsonify(error=f"Couldn't import that kit: {e}"), 400
    return jsonify(kit_out(kit))


@app.get("/api/kits/<kit_id>/export")
def kit_export(kit_id):
    kit = kit_or_404(kit_id)
    return send_file(io.BytesIO(kits.export_zip(kit_id)), mimetype="application/zip",
                     as_attachment=True, download_name=f"{kit['name']} (kit).zip")


@app.post("/api/kits/<kit_id>/duplicate")
def kit_duplicate(kit_id):
    kit_or_404(kit_id)
    return jsonify(kit_out(kits.duplicate(kit_id)))


@app.delete("/api/kits/<kit_id>")
def kit_delete(kit_id):
    kit_or_404(kit_id)
    try:
        kits.delete(kit_id)
    except ValueError as e:
        return jsonify(error=str(e)), 400
    return jsonify(ok=True)


@app.post("/api/kits/<kit_id>/logo")
def kit_logo(kit_id):
    kit_or_404(kit_id)
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify(error="No file."), 400
    try:
        return jsonify(kit_out(kits.set_logo(kit_id, f.filename, f.read())))
    except ValueError as e:
        return jsonify(error=str(e)), 400


@app.delete("/api/kits/<kit_id>/logo")
def kit_logo_clear(kit_id):
    kit_or_404(kit_id)
    return jsonify(kit_out(kits.clear_logo(kit_id)))


@app.post("/api/kits/<kit_id>/slides")
def kit_add_slide(kit_id):
    """Save a slide from an open deck as a template in its kit."""
    kit = kit_or_404(kit_id)
    body = request.get_json(force=True) or {}
    slide = normalize_slide(body.get("slide") or {})
    slide.pop("art", None)
    name = (body.get("name") or "").strip() or slide.get("eyebrow") or "Saved slide"
    kit.setdefault("slides", []).append({
        "id": kits.new_template_id(kit, name), "name": name,
        "category": (body.get("category") or "").strip() or "Saved",
        "note": (body.get("note") or "").strip(), "slide": slide,
    })
    return jsonify(kit_out(kits.save(kit, kit_id)))


@app.delete("/api/kits/<kit_id>/slides/<tid>")
def kit_remove_slide(kit_id, tid):
    kit = kit_or_404(kit_id)
    kit["slides"] = [t for t in kit.get("slides") or [] if t["id"] != tid]
    for d in kit.get("decks") or []:
        d["slide_ids"] = [i for i in d["slide_ids"] if i != tid]
    return jsonify(kit_out(kits.save(kit, kit_id)))


# --- export -------------------------------------------------------------------

def render_url(deck_id: str) -> str:
    return f"http://127.0.0.1:{PORT}/render/{deck_id}"


def download_name(deck: dict, deck_id: str, suffix: str) -> str:
    """A filename safe to hand to send_file.

    Always route downloads through send_file's download_name rather than a
    hand-written Content-Disposition: HTTP headers are latin-1, and a title
    like "Acme — Pre-seed Deck" raises UnicodeEncodeError deep in the WSGI
    server, hanging the connection after the export work is already done.
    send_file emits the RFC 5987 filename* form instead.
    """
    title = str(deck.get("title") or deck_id)
    title = re.sub(r"[/\\:]", "-", title).strip() or deck_id
    return f"{title}{suffix}"


@app.get("/api/decks/<deck_id>/export/pdf")
def export_pdf(deck_id):
    deck = load_deck(deck_id)
    out = ROOT / "decks" / f"{deck_id}.pdf"
    exporter.to_pdf(render_url(deck_id), out)
    return send_file(out, as_attachment=True,
                     download_name=download_name(deck, deck_id, ".pdf"))


@app.get("/api/decks/<deck_id>/export/png")
def export_png(deck_id):
    deck = load_deck(deck_id)
    data = exporter.to_png_zip(render_url(deck_id), scale=2)
    return send_file(io.BytesIO(data), mimetype="application/zip",
                     as_attachment=True,
                     download_name=download_name(deck, deck_id, " (png).zip"))


@app.get("/api/decks/<deck_id>/export/html")
def export_html(deck_id):
    deck = load_deck(deck_id)
    html = exporter.to_standalone_html(render_url(deck_id))
    return send_file(io.BytesIO(html.encode("utf-8")), mimetype="text/html",
                     as_attachment=True,
                     download_name=download_name(deck, deck_id, ".html"))


if __name__ == "__main__":
    print(f"\n  Template Generator  →  http://localhost:{PORT}\n")
    app.run(port=PORT, debug=False, threaded=True)
