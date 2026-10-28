/* ============================================================
   Editor
   ============================================================ */

let deck = null;
let deckId = null;
let cur = 0;
let saveTimer = null;

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];

const PLACEHOLDERS = {
  "s-eyebrow": "Eyebrow", "s-title": "Headline", "s-dek": "Supporting line",
  "s-foot": "Closing line", "card-label": "Label", "card-body": "Body",
  "stat-label": "Label", "stat-value": "$0", "stat-caption": "Caption",
  "pill": "Term", "pillrow-text": "Definition",
  "bullet-label": "Label", "bullet-body": "Detail", "cover-logo-text": "Brand",
};

/* --- deck JSON path access ---------------------------------- */

function getPath(obj, path) {
  return path.split(".").reduce((o, k) => (o == null ? o : o[k]), obj);
}
function setPath(obj, path, value) {
  const keys = path.split(".");
  const last = keys.pop();
  let o = obj;
  keys.forEach((k, i) => {
    // Next key numeric => this level is an array, otherwise an object.
    const nextKey = keys[i + 1] ?? last;
    if (o[k] == null) o[k] = /^\d+$/.test(nextKey) ? [] : {};
    o = o[k];
  });
  o[last] = value;
}

/* --- persistence -------------------------------------------- */

function status(text) { $("#status").textContent = text; }

function scheduleSave() {
  status("Saving…");
  clearTimeout(saveTimer);
  saveTimer = setTimeout(save, 700);
}

async function save() {
  if (!deckId) return;
  try {
    const r = await fetch(`/api/decks/${deckId}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(deck),
    });
    if (!r.ok) throw new Error(await r.text());
    status("Saved");
    setTimeout(() => status(""), 1400);
  } catch (e) {
    status("Save failed");
    console.error(e);
  }
}

/* --- rendering ---------------------------------------------- */

function slide() { return deck.slides[cur]; }

/* Display names for the card treatments and backgrounds. The stored values are
   historical token names; what they look like comes from the kit. */
const VARIANT_NAMES = {
  brown: "Filled", mint: "Tinted", teal: "Tinted, alternate",
  cream: "Soft", outline: "Outline",
};

function renderAll() {
  if (!deck.slides.length) {
    deck.slides.push({ layout: "cards", title: "", items: [], variant: "mint" });
  }
  cur = Math.max(0, Math.min(cur, deck.slides.length - 1));
  renderStage();
  renderThumbs();
  renderInspector();
}

function renderStage() {
  const stage = $("#stage");
  applyTheme(deck);
  setBrand(deck);
  setEditable(true);
  stage.innerHTML = renderSlide(slide(), cur, deck.slides.length);
  wireEditable(stage);
  fitStage();
}

function wireEditable(root) {
  $$("[data-path]", root).forEach(el => {
    el.setAttribute("contenteditable", "plaintext-only");
    el.spellcheck = false;
    const cls = [...el.classList].find(c => PLACEHOLDERS[c]);
    if (cls) el.dataset.placeholder = PLACEHOLDERS[cls];

    el.addEventListener("input", () => {
      // Paths are relative to the deck root; the renderer already scoped them.
      setPath(deck, el.dataset.path, el.innerText.trim());
      scheduleSave();
      renderThumbs();
    });
    el.addEventListener("keydown", e => {
      if (e.key === "Enter" && !e.shiftKey && el.tagName !== "LI") {
        e.preventDefault();
        el.blur();
      }
      if (e.key === "Escape") el.blur();
    });
  });
}

function fitStage() {
  const box = $("#canvas").getBoundingClientRect();
  const scale = Math.min((box.width - 56) / 1920, (box.height - 56) / 1080);
  const stage = $("#stage");
  stage.style.transform = `scale(${scale})`;
  stage.style.width = "1920px";
  stage.style.height = "1080px";
  // Collapse the layout box to the visual size so flex centering stays true.
  stage.style.margin = `${(1080 * scale - 1080) / 2}px ${(1920 * scale - 1920) / 2}px`;
}
window.addEventListener("resize", () => { if (deck) fitStage(); });

function renderThumbs() {
  const wrap = $("#thumbs");
  wrap.innerHTML = "";
  setEditable(false);
  deck.slides.forEach((s, i) => {
    const d = document.createElement("div");
    d.className = "thumb" + (i === cur ? " active" : "");
    d.draggable = true;
    d.dataset.index = i;
    d.innerHTML = `<div class="scaler">${renderSlide(s, i, deck.slides.length)}</div>
                   <div class="n">${i + 1}</div>`;
    d.addEventListener("click", () => { cur = i; renderAll(); });
    wireDrag(d);
    wrap.appendChild(d);
  });
  setEditable(true);
}

/* --- drag to reorder ---------------------------------------- */

let dragFrom = null;
function wireDrag(el) {
  el.addEventListener("dragstart", () => {
    dragFrom = +el.dataset.index;
    el.classList.add("dragging");
  });
  el.addEventListener("dragend", () => {
    el.classList.remove("dragging");
    $$(".thumb").forEach(t => t.classList.remove("drop-target"));
  });
  el.addEventListener("dragover", e => {
    e.preventDefault();
    el.classList.add("drop-target");
  });
  el.addEventListener("dragleave", () => el.classList.remove("drop-target"));
  el.addEventListener("drop", e => {
    e.preventDefault();
    const to = +el.dataset.index;
    if (dragFrom === null || dragFrom === to) return;
    const [moved] = deck.slides.splice(dragFrom, 1);
    deck.slides.splice(to, 0, moved);
    cur = to;
    dragFrom = null;
    renderAll();
    scheduleSave();
  });
}

/* --- inspector ---------------------------------------------- */

function renderInspector() {
  const s = slide();
  const ins = $("#inspector");
  const uses = LAYOUTS[s.layout]?.uses || [];

  const opt = (v, sel, label) =>
    `<option value="${v}"${v === sel ? " selected" : ""}>${label || v}</option>`;

  let html = `
    <h3>Slide ${cur + 1}</h3>
    <div class="field">
      <label>Layout</label>
      <select id="layoutSel">
        ${Object.entries(LAYOUTS).map(([k, v]) => opt(k, s.layout, v.name)).join("")}
      </select>
    </div>`;

  if (uses.includes("variant")) {
    html += `<div class="field"><label>Card style</label>
      <select id="variantSel">${VARIANTS.map(v => opt(v, s.variant || "mint", VARIANT_NAMES[v])).join("")}</select>
    </div>`;
  }

  if (uses.includes("shape")) {
    html += `<div class="field"><label>Shape</label>
      <select id="shapeSel">
        ${opt("chain", s.shape || "chain", "Chain — straight sequence")}
        ${opt("loop", s.shape || "chain", "Loop — wraps and returns")}
      </select></div>`;
    if ((s.shape || "chain") === "loop") {
      html += `<div class="field"><label>Return path caption</label>
        <input type="text" id="returnLabel" placeholder="each cycle feeds the next"
               value="${escAttr(s.returnLabel)}"></div>`;
    }
  }

  html += `<div class="field"><label>Background</label>
    <select id="groundSel">
      ${opt("", s.ground || "", "Default")}
      ${opt("warm", s.ground || "", "Alternate")}
      ${opt("cream", s.ground || "", "Soft")}
      ${opt("brown", s.ground || "", "Dark (full bleed)")}
      ${opt("ink", s.ground || "", "Darkest (full bleed)")}
    </select></div>`;

  if (s.layout === "cover") {
    html += `<div class="field"><label>Cover illustration</label>
      <input type="file" id="artFile" accept="image/*">
      ${s.art ? `<button id="clearArt" style="margin-top:7px">Remove image</button>` : ""}
    </div>`;
  }

  // Per-slide colour overrides. Values shown are this slide's own override if
  // it has one, otherwise whatever it currently resolves to on the canvas.
  const own = (s.theme && s.theme.colors) || {};
  const swatch = (token, label) =>
    `<div style="flex:1">
       <label>${label}</label>
       <input type="color" data-color="${token}" value="${effectiveColor(token, own)}"
              style="height:32px;padding:2px">
     </div>`;
  html += `<hr class="sep"><h3>Colour on this slide</h3>
    <div class="row" style="margin-bottom:9px">
      ${swatch("ink", "Headline")}${swatch("ground", "Background")}${swatch("green", "Accent")}
    </div>
    <button id="resetSlideColor" style="width:100%"
      ${Object.keys(own).length ? "" : "disabled"}>
      ${Object.keys(own).length
        ? `Clear ${Object.keys(own).length} override${Object.keys(own).length > 1 ? "s" : ""}`
        : "Following the deck palette"}
    </button>`;

  if (uses.includes("footer")) {
    html += `<div class="field"><label>
      <input type="checkbox" id="footAccent" style="width:auto;margin-right:6px"
        ${s.footerAccent === "green" ? "checked" : ""}>Footer as accent takeaway
    </label></div>`;
  }

  if (uses.includes("items")) {
    html += `<hr class="sep"><h3>Content</h3><div id="items">`;
    (s.items || []).forEach((it, j) => {
      html += `<div class="item-card">
        <div class="item-head"><span>Item ${j + 1}</span>
          <span>
            <button data-move="${j}" data-dir="-1" ${j === 0 ? "disabled" : ""}>↑</button>
            <button data-move="${j}" data-dir="1" ${j === s.items.length - 1 ? "disabled" : ""}>↓</button>
            <button class="danger" data-del="${j}">✕</button>
          </span>
        </div>
        <input type="text" data-f="label" data-i="${j}" placeholder="Label" value="${escAttr(it.label)}">
        <textarea rows="2" data-f="body" data-i="${j}" placeholder="Body">${escHtml(it.body)}</textarea>`;
      if (s.layout === "diagram") {
        html += `<div class="row">
          <select data-f="group" data-i="${j}">
            ${DIAGRAM_KINDS.map(k =>
              `<option value="${k}"${(it.group || "automation") === k ? " selected" : ""}>${DIAGRAM_KIND_NAMES[k]}</option>`
            ).join("")}
          </select>
          <input type="text" data-f="value" data-i="${j}" placeholder="Chip"
                 value="${escAttr(it.value)}">
        </div>`;
      }
      if (s.layout === "stats" || s.layout === "columns") {
        // (diagram handles its own value field above)
        html += `<input type="text" data-f="value" data-i="${j}"
                   placeholder="${s.layout === "stats" ? "Big number, e.g. $50mn" : "Badge, e.g. 8–12%"}"
                   value="${escAttr(it.value)}">`;
      }
      if (s.layout === "numbered") {
        html += `<input type="text" data-f="group" data-i="${j}"
                   placeholder="Group heading" value="${escAttr(it.group)}">`;
      }
      if (s.layout === "columns") {
        html += `<textarea rows="3" data-f="bullets" data-i="${j}"
                   placeholder="One bullet per line">${escHtml((it.bullets || []).join("\n"))}</textarea>`;
      }
      html += `</div>`;
    });
    html += `</div><button id="addItem" style="width:100%">+ Add item</button>`;
  }

  html += `<hr class="sep"><h3>Rewrite with Claude</h3>
    <div class="field">
      <textarea id="rewriteBox" rows="3"
        placeholder="e.g. tighten the card copy and make the headline a claim"></textarea>
    </div>
    <button id="rewriteBtn" style="width:100%">Rewrite this slide</button>
    <hr class="sep">
    <button id="insertTpl" style="width:100%;margin-bottom:9px">Insert template slide…</button>
    <button id="saveTpl" style="width:100%;margin-bottom:9px">Save slide to the kit</button>
    <div class="row">
      <button id="dupSlide">Duplicate</button>
      <button id="delSlide" class="danger">Delete slide</button>
    </div>`;

  ins.innerHTML = html;
  wireInspector();
}

/* What a token currently resolves to for the slide on the canvas — used to seed
   the colour inputs so they don't all start at black. */
function effectiveColor(token, own) {
  if (own[token]) return own[token];
  const el = $(".stage .slide");
  if (!el) return "#000000";
  const v = getComputedStyle(el).getPropertyValue(`--${token}`).trim();
  return /^#[0-9a-fA-F]{6}$/.test(v) ? v : "#000000";
}

function escHtml(s) {
  return String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
function escAttr(s) { return escHtml(s).replace(/"/g, "&quot;"); }

function wireInspector() {
  const s = slide();

  $("#layoutSel").onchange = e => {
    s.layout = e.target.value;
    seedItems(s);
    renderAll(); scheduleSave();
  };
  const vs = $("#variantSel");
  if (vs) vs.onchange = e => { s.variant = e.target.value; renderAll(); scheduleSave(); };
  const sh = $("#shapeSel");
  if (sh) sh.onchange = e => { s.shape = e.target.value; renderAll(); scheduleSave(); };
  const rl = $("#returnLabel");
  if (rl) rl.oninput = e => { s.returnLabel = e.target.value; renderStage(); scheduleSave(); };
  $("#groundSel").onchange = e => { s.ground = e.target.value; renderAll(); scheduleSave(); };

  const fa = $("#footAccent");
  if (fa) fa.onchange = e => {
    s.footerAccent = e.target.checked ? "green" : "";
    renderStage(); scheduleSave();
  };

  const art = $("#artFile");
  if (art) art.onchange = async e => {
    const f = e.target.files[0];
    if (!f) return;
    const fd = new FormData(); fd.append("file", f);
    const r = await fetch("/api/art", { method: "POST", body: fd });
    const j = await r.json();
    if (j.url) { s.art = j.url; renderAll(); scheduleSave(); }
    else alert(j.error || "Upload failed");
  };
  const ca = $("#clearArt");
  if (ca) ca.onclick = () => { delete s.art; renderAll(); scheduleSave(); };

  $$("#items [data-f]").forEach(el => {
    el.oninput = () => {
      const it = s.items[+el.dataset.i];
      const f = el.dataset.f;
      if (f === "bullets") it.bullets = el.value.split("\n").filter(x => x.trim());
      else it[f] = el.value;
      renderStage(); renderThumbs(); scheduleSave();
    };
  });

  $$("#items [data-del]").forEach(b => b.onclick = () => {
    s.items.splice(+b.dataset.del, 1);
    renderAll(); scheduleSave();
  });
  $$("#items [data-move]").forEach(b => b.onclick = () => {
    const j = +b.dataset.move, dir = +b.dataset.dir;
    const [m] = s.items.splice(j, 1);
    s.items.splice(j + dir, 0, m);
    renderAll(); scheduleSave();
  });
  const ai = $("#addItem");
  if (ai) ai.onclick = () => {
    (s.items ||= []).push({ label: "", body: "", bullets: [], value: "", group: "" });
    renderAll(); scheduleSave();
  };

  $$("[data-color]").forEach(inp => {
    inp.oninput = () => {
      s.theme ||= {};
      (s.theme.colors ||= {})[inp.dataset.color] = inp.value;
      renderStage(); renderThumbs(); scheduleSave();
    };
    // Re-render the inspector only on release, so the picker isn't torn down
    // mid-drag while the colour is still being chosen.
    inp.onchange = () => renderInspector();
  });
  const rsc = $("#resetSlideColor");
  if (rsc) rsc.onclick = () => {
    delete s.theme;
    renderAll(); scheduleSave();
  };

  $("#insertTpl").onclick = showInsertSheet;
  $("#saveTpl").onclick = () => saveSlideToKit(s);

  $("#dupSlide").onclick = () => {
    deck.slides.splice(cur + 1, 0, JSON.parse(JSON.stringify(s)));
    cur++; renderAll(); scheduleSave();
  };
  $("#delSlide").onclick = () => {
    if (deck.slides.length === 1) return alert("A deck needs at least one slide.");
    deck.slides.splice(cur, 1);
    cur = Math.max(0, cur - 1);
    renderAll(); scheduleSave();
  };

  $("#rewriteBtn").onclick = async () => {
    const box = $("#rewriteBox");
    const instruction = box.value.trim();
    if (!instruction) return;
    const btn = $("#rewriteBtn");
    btn.disabled = true; btn.innerHTML = '<span class="spinner"></span> Rewriting…';
    try {
      await save();
      const r = await fetch(`/api/decks/${deckId}/slides/${cur}/rewrite`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ instruction }),
      });
      const j = await r.json();
      if (!r.ok) throw new Error(j.error || "Rewrite failed");
      deck = j;
      renderAll();
    } catch (e) {
      alert(e.message);
    } finally {
      btn.disabled = false; btn.textContent = "Rewrite this slide";
    }
  };
}

/* Give a freshly-switched layout enough items to look like itself. */
function seedItems(s) {
  const need = {
    flow: 3, stats: 3, numbered: 4, columns: 3, pillrows: 4, cards: 4,
    bullets: 3, mapping: 6, cycle: 6, ledger: 6, diagram: 4,
  };
  const n = need[s.layout];
  if (!n) return;
  s.items ||= [];
  while (s.items.length < n) {
    s.items.push({ label: "", body: "", bullets: [], value: "", group: "" });
  }
  // Grouped layouts are meaningless without groups — seed two so the slide
  // renders as its own shape the moment you switch to it.
  const pair = (a, b) =>
    s.items.forEach((it, i) => { if (!it.group) it.group = i < Math.ceil(s.items.length / 2) ? a : b; });
  if (s.layout === "numbered") pair("First theme", "Second theme");
  if (s.layout === "diagram") {
    s.shape ||= "chain";
    // group is the node kind here, not a heading — default rather than pair.
    s.items.forEach(it => { if (!DIAGRAM_KINDS.includes(it.group)) it.group = "automation"; });
  }
  if (s.layout === "mapping") pair("What it learns", "Where it's used");
  if (s.layout === "ledger") pair("Team", "Allocations");
}

/* --- top bar ------------------------------------------------ */

function wireTopbar() {
  $("#deckTitle").oninput = e => { deck.title = e.target.value; scheduleSave(); };
  $("#home").onclick = async () => { await save(); showHome(); };

  const addSlide = () => {
    deck.slides.splice(cur + 1, 0, {
      layout: "cards", eyebrow: "", title: "", dek: "", variant: "mint",
      items: [], footer: "", footerAccent: "",
    });
    cur++; seedItems(deck.slides[cur]); renderAll(); scheduleSave();
  };
  $("#addSlide").onclick = addSlide;
  $("#newSlideBtn").onclick = addSlide;

  const menu = $("#exportMenu");
  $("#exportBtn").onclick = e => { e.stopPropagation(); menu.classList.toggle("open"); };
  document.addEventListener("click", () => menu.classList.remove("open"));
  $$("[data-export]").forEach(b => b.onclick = async () => {
    menu.classList.remove("open");
    await save();
    status("Exporting…");
    window.location = `/api/decks/${deckId}/export/${b.dataset.export}`;
    setTimeout(() => status(""), 2500);
  });

  document.addEventListener("keydown", e => {
    if (e.target.matches("input, textarea, [contenteditable]")) return;
    if (e.key === "ArrowDown" || e.key === "ArrowRight") {
      if (cur < deck.slides.length - 1) { cur++; renderAll(); }
    }
    if (e.key === "ArrowUp" || e.key === "ArrowLeft") {
      if (cur > 0) { cur--; renderAll(); }
    }
  });
}

/* --- chat --------------------------------------------------- */

function inspTab(name) {
  $$(".insp-tabs button").forEach(b => b.classList.toggle("active", b.dataset.itab === name));
  $("#inspector").hidden = name !== "design";
  $("#chatPanel").hidden = name !== "chat";
  if (name === "chat") {
    renderChat();
    $("#chatInput").focus();
  }
}

function renderChat() {
  const log = $("#chatLog");
  const turns = (deck && deck.chat) || [];
  if (!turns.length) {
    log.innerHTML = `<div class="chat-empty">Describe the change you want and it gets
      applied to this deck — copy, layout, palette, or typeface. Fonts are pulled from
      Google Fonts and stored locally, so exports still work offline.</div>`;
    return;
  }
  log.innerHTML = turns.map(t =>
    `<div class="msg ${t.role === "user" ? "user" : "assistant"}">${escHtml(t.content)}</div>`
  ).join("");
  log.scrollTop = log.scrollHeight;
}

async function sendChat() {
  const input = $("#chatInput");
  const message = input.value.trim();
  if (!message || !deckId) return;

  const send = $("#chatSend");
  send.disabled = true;
  input.value = "";

  // Optimistic echo is DOM-only. Pushing it into deck.chat would get persisted
  // by the save() below, and the server would then append the same message
  // again — the turn would show up twice.
  const log = $("#chatLog");
  if (!(deck.chat || []).length) log.innerHTML = "";
  const echo = document.createElement("div");
  echo.className = "msg user";
  echo.textContent = message;
  log.appendChild(echo);
  const pending = document.createElement("div");
  pending.className = "msg thinking";
  pending.innerHTML = '<span class="spinner"></span> Working…';
  log.appendChild(pending);
  log.scrollTop = log.scrollHeight;

  try {
    await save();
    const r = await fetch(`/api/decks/${deckId}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message }),
    });
    const j = await r.json();
    if (!r.ok) throw new Error(j.error || "That didn't work.");
    deck = j.deck;                 // server returns the deck after every tool ran
    cur = Math.min(cur, deck.slides.length - 1);
    $("#deckTitle").value = deck.title || "";   // the agent may have renamed it
    renderAll();                   // re-renders inspector, so restore the tab
    inspTab("chat");
  } catch (e) {
    pending.remove();
    const err = document.createElement("div");
    err.className = "msg error";
    err.textContent = e.message;
    log.appendChild(err);
    log.scrollTop = log.scrollHeight;
  } finally {
    send.disabled = false;
  }
}

function wireChat() {
  $$(".insp-tabs button").forEach(b => b.onclick = () => inspTab(b.dataset.itab));
  $("#chatSend").onclick = sendChat;
  $("#chatInput").onkeydown = e => {
    // Enter sends; Shift+Enter for a newline.
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendChat(); }
  };
  $("#chatClear").onclick = async () => {
    if (!deckId || !confirm("Clear this conversation?")) return;
    const r = await fetch(`/api/decks/${deckId}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ clear: true }),
    });
    const j = await r.json();
    if (r.ok) { deck = j.deck; renderChat(); }
  };
}

/* --- home: shared preview rendering -------------------------- */

/* Renders a real slide into a card preview, scaled to whatever width the grid
   gave it. Same renderer as the editor, so previews can't misrepresent. */
function previewCard(slide, index, total, themeSource) {
  setEditable(false);
  setBrand(themeSource);
  const html = renderSlide(slide, index, total);
  setEditable(true);
  if (deck) setBrand(deck);
  // Deck theme scoped to this card, not :root — see themeAttr. The slide's own
  // overrides are already inline on the .slide element from renderSlide.
  return `<div class="tpl-preview"><div class="scaler"${themeAttr(themeSource)}>${html}</div></div>`;
}

function fitPreviews(root) {
  $$(".tpl-preview", root).forEach(box => {
    const scale = box.clientWidth / 1920;
    const s = $(".scaler", box);
    if (s) s.style.transform = `scale(${scale})`;
  });
}

/* --- home: tabs --------------------------------------------- */

function switchTab(name) {
  $$("#tabs button").forEach(b => b.classList.toggle("active", b.dataset.tab === name));
  $$(".panel").forEach(p => (p.hidden = p.dataset.panel !== name));
  if (name === "projects") loadProjects();
  if (name === "templates") loadTemplates();
  if (name === "kits") loadKits();
}

async function loadProjects() {
  const wrap = $("#projects");
  const decks = await (await fetch("/api/decks")).json();
  $("#projCount").textContent = decks.length || "";
  if (!decks.length) {
    wrap.innerHTML = `<div class="empty">Nothing here yet — generate a deck or start
      from a template.</div>`;
    return;
  }
  // Fetch each deck so the card can preview its real first slide.
  const full = await Promise.all(
    decks.map(d => fetch(`/api/decks/${d.id}`).then(r => r.json()).catch(() => null))
  );
  wrap.innerHTML = `<div class="cards-grid">${decks.map((d, i) => {
    const first = full[i]?.slides?.[0];
    const prev = first ? previewCard(first, 0, d.slides, full[i])
                       : `<div class="tpl-preview"></div>`;
    return `<div class="tpl-card" data-id="${d.id}">
      ${prev}
      <div class="tpl-meta"><div class="name">${escHtml(d.title)}
        <span class="chip">${escHtml(full[i]?._kit?.name || "")}</span></div></div>
      <div class="tpl-foot">
        <span class="meta">${d.slides} slides · ${new Date(d.updated * 1000).toLocaleDateString()}</span>
        <button class="del" data-del="${d.id}">Delete</button>
      </div>
    </div>`;
  }).join("")}</div>`;
  fitPreviews(wrap);

  $$(".tpl-card", wrap).forEach(c => c.onclick = e => {
    if (e.target.dataset.del) return;
    open(c.dataset.id);
  });
  $$("[data-del]", wrap).forEach(b => b.onclick = async e => {
    e.stopPropagation();
    if (!confirm("Delete this deck? This cannot be undone.")) return;
    await fetch(`/api/decks/${b.dataset.del}`, { method: "DELETE" });
    loadProjects();
  });
}

const TEMPLATES = {};
async function fetchTemplates(kitId) {
  kitId = kitId || currentKit();
  if (!TEMPLATES[kitId]) {
    TEMPLATES[kitId] = await (await fetch(`/api/templates?kit=${encodeURIComponent(kitId)}`)).json();
  }
  return TEMPLATES[kitId];
}
function forgetTemplates(kitId) {
  if (kitId) delete TEMPLATES[kitId];
  else Object.keys(TEMPLATES).forEach(k => delete TEMPLATES[k]);
}

async function loadTemplates() {
  const wrap = $("#templates");
  const all = await fetchTemplates();
  const kitTheme = await kitPreviewSource(currentKit());

  // Two groups only. Splitting slides across eight one-item category groups
  // left the grid mostly empty; the category rides on the card instead.
  const groups = [
    { key: "Full decks", items: all.filter(t => t.kind === "deck") },
    { key: "Slide templates", items: all.filter(t => t.kind === "slide") },
  ].filter(g => g.items.length);

  wrap.innerHTML = groups.map(g => `
    <div class="tpl-group">
      <h4>${escHtml(g.key)}</h4>
      <div class="cards-grid">${g.items.map(t => {
        const slide = t.kind === "deck" ? t.slides[0] : t.slide;
        const badge = t.kind === "deck" ? `${t.count} slides` : LAYOUTS[slide.layout]?.name || "";
        return `<div class="tpl-card" data-tpl="${t.id}">
          ${previewCard(slide, 0, t.kind === "deck" ? t.count : 1, kitTheme)}
          <span class="badge">${escHtml(badge)}</span>
          <div class="tpl-meta">
            <div class="name">${escHtml(t.name)}
              <span class="chip">${escHtml(t.category)}</span></div>
            <div class="note">${escHtml(t.note)}</div>
          </div>
        </div>`;
      }).join("")}</div>
    </div>`).join("");

  // The badge is positioned against .tpl-preview, so move it inside.
  $$(".tpl-card", wrap).forEach(c => {
    const b = $(".badge", c), p = $(".tpl-preview", c);
    if (b && p) p.appendChild(b);
  });
  fitPreviews(wrap);

  $$(".tpl-card", wrap).forEach(c => c.onclick = async () => {
    c.style.opacity = ".5";
    const r = await fetch("/api/decks/from-template", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ template_id: c.dataset.tpl, kit_id: currentKit() }),
    });
    const j = await r.json();
    c.style.opacity = "";
    if (r.ok) open(j.id); else alert(j.error || "Could not start that template.");
  });
}

function wireHome() {
  $$("#tabs button").forEach(b => b.onclick = () => switchTab(b.dataset.tab));

  $("#blankBtn").onclick = async () => {
    const d = await (await fetch("/api/decks/blank", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ kit_id: currentKit() }),
    })).json();
    open(d.id);
  };

  $("#genBtn").onclick = async () => {
    const brief = $("#brief").value.trim();
    if (!brief) return $("#brief").focus();
    const btn = $("#genBtn");
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span> Building your deck…';
    $("#genErr").innerHTML = "";
    try {
      const r = await fetch("/api/decks", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          brief,
          slide_count: +$("#count").value || 0,
          notes: $("#notes").value,
          kit_id: currentKit(),
        }),
      });
      const j = await r.json();
      if (!r.ok) throw new Error(j.error || "Generation failed");
      open(j.id);
    } catch (e) {
      $("#genErr").innerHTML = `<div class="err">${escHtml(e.message)}</div>`;
    } finally {
      btn.disabled = false; btn.textContent = "Generate deck";
    }
  };
}

/* --- insert a template slide into the open deck -------------- */

async function showInsertSheet() {
  const sheet = $("#insertSheet");
  const list = $("#insertList");
  const all = (await fetchTemplates(deck.kit)).filter(t => t.kind === "slide");
  list.innerHTML = `<div class="cards-grid">${all.map(t => `
    <div class="tpl-card" data-tpl="${t.id}">
      ${previewCard(t.slide, 0, 1, deck)}
      <div class="tpl-meta">
        <div class="name">${escHtml(t.name)}</div>
        <div class="note">${escHtml(t.note)}</div>
      </div>
    </div>`).join("")}</div>`;
  sheet.hidden = false;
  fitPreviews(list);

  $$(".tpl-card", list).forEach(c => c.onclick = () => {
    const t = all.find(x => x.id === c.dataset.tpl);
    deck.slides.splice(cur + 1, 0, JSON.parse(JSON.stringify(t.slide)));
    cur++;
    sheet.hidden = true;
    renderAll(); scheduleSave();
  });
}

/* --- view switching ----------------------------------------- */

function showHome() {
  deck = null; deckId = null;
  location.hash = "";
  $("#editorView").hidden = true;
  $("#homeView").hidden = false;
  const active = $("#tabs button.active")?.dataset.tab || "generate";
  switchTab(active);
}

async function open(id) {
  const r = await fetch(`/api/decks/${id}`);
  if (!r.ok) return showHome();
  deck = await r.json();
  deckId = id;
  cur = 0;
  location.hash = id;
  $("#homeView").hidden = true;
  $("#editorView").hidden = false;
  $("#deckTitle").value = deck.title || "";
  inspTab("design");
  renderAll();
}

(async function boot() {
  wireTopbar();
  wireHome();
  await initKits();
  wireChat();
  $("#insertClose").onclick = () => ($("#insertSheet").hidden = true);
  $("#insertSheet").onclick = e => {
    if (e.target.id === "insertSheet") $("#insertSheet").hidden = true;
  };

  const id = location.hash.slice(1);
  if (id) {
    const r = await fetch(`/api/decks/${id}`);
    if (r.ok) return open(id);
  }
  showHome();
})();
