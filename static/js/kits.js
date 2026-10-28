/* ============================================================
   Brand kits: pick, build from uploads, edit, share
   Loaded before editor.js; uses its helpers ($, $$, escHtml,
   previewCard, fitPreviews) at call time.
   ============================================================ */

let KITS = [];
let ROLES = [];

function currentKit() {
  let id = "";
  try { id = localStorage.getItem("kit") || ""; } catch (e) {}
  return KITS.some(k => k.id === id) ? id : (KITS[0] && KITS[0].id) || "starter";
}

function setCurrentKit(id) {
  try { localStorage.setItem("kit", id); } catch (e) {}
  renderKitSelects();
  const active = $("#tabs button.active")?.dataset.tab;
  if (active === "templates") loadTemplates();
  if (active === "kits") loadKits();
}

/* A stand-in deck that carries only a kit's look, for previews. */
function kitPreviewSource(id) {
  const k = KITS.find(x => x.id === id);
  return k ? { _kit: k.render } : {};
}

async function refreshKits() {
  KITS = await (await fetch("/api/kits")).json();
  renderKitSelects();
}

function renderKitSelects() {
  const cur = currentKit();
  $$("[data-kit-select]").forEach(sel => {
    sel.innerHTML = KITS.map(k =>
      `<option value="${k.id}"${k.id === cur ? " selected" : ""}>${escHtml(k.name)}</option>`
    ).join("");
    sel.onchange = () => setCurrentKit(sel.value);
  });
  const k = KITS.find(x => x.id === cur);
  $("#kitCurrent").innerHTML = k ? `Kit: <b>${escHtml(k.name)}</b>` : "";
}

/* Fonts a kit installs land in installed.css; re-fetch it so they show. */
function reloadInstalledFonts() {
  $$('link[href*="/static/fonts/installed.css"]').forEach(l => {
    l.href = `/static/fonts/installed.css?v=${Date.now()}`;
  });
}

async function initKits() {
  ROLES = await (await fetch("/api/kits/roles")).json();
  await refreshKits();
  wireKitUpload();
}

/* --- the Kits tab -------------------------------------------- */

async function loadKits() {
  await refreshKits();
  const cur = currentKit();
  const wrap = $("#kits");
  wrap.innerHTML = `<div class="cards-grid">${KITS.map(k => {
    const prev = k.cover ? previewCard(k.cover, 0, 1, { _kit: k.render })
                         : `<div class="tpl-preview"></div>`;
    return `<div class="tpl-card kit-card${k.id === cur ? " active" : ""}" data-kit="${k.id}">
      ${prev}
      <div class="tpl-meta">
        <div class="name">${escHtml(k.name)}
          ${k.id === cur ? `<span class="chip">in use</span>` : ""}</div>
        <div class="note">${escHtml(k.description || "")}</div>
        <div class="note">${k.slides} slide templates · ${k.decks} deck arcs</div>
      </div>
      <div class="kit-actions">
        ${k.id === cur ? "" : `<button data-act="use">Use</button>`}
        <button data-act="edit">Edit</button>
        <button data-act="dup">Duplicate</button>
        <button data-act="export">Share (.zip)</button>
        ${k.builtin ? "" : `<button class="danger" data-act="del">Delete</button>`}
      </div>
    </div>`;
  }).join("")}</div>`;
  fitPreviews(wrap);

  $$(".kit-card", wrap).forEach(c => {
    const id = c.dataset.kit;
    c.onclick = e => {
      const act = e.target.dataset.act;
      if (!act) return openKitEditor(id);
      e.stopPropagation();
      kitAction(act, id);
    };
  });
}

async function kitAction(act, id) {
  if (act === "use") return setCurrentKit(id);
  if (act === "edit") return openKitEditor(id);
  if (act === "export") { window.location = `/api/kits/${id}/export`; return; }
  if (act === "dup") {
    const r = await fetch(`/api/kits/${id}/duplicate`, { method: "POST" });
    const j = await r.json();
    if (!r.ok) return alert(j.error || "Couldn't duplicate that kit.");
    await refreshKits();
    setCurrentKit(j.id);
    return openKitEditor(j.id);
  }
  if (act === "del") {
    if (!confirm("Delete this kit? Decks made with it will fall back to the Starter kit.")) return;
    const r = await fetch(`/api/kits/${id}`, { method: "DELETE" });
    if (!r.ok) return alert((await r.json()).error || "Couldn't delete that kit.");
    forgetTemplates(id);
    await refreshKits();
    loadKits();
  }
}

function wireKitUpload() {
  const input = $("#kitFiles"), drop = $("#kitDrop"), text = $("#kitDropText");
  let files = [];
  const show = () => {
    drop.classList.toggle("has-files", files.length > 0);
    text.textContent = files.length
      ? files.map(f => f.name).join(", ")
      : "Drop PDF, PPTX or slide images here, or click to choose";
  };
  input.onchange = () => { files = [...input.files]; show(); };
  drop.ondragover = e => { e.preventDefault(); drop.classList.add("over"); };
  drop.ondragleave = () => drop.classList.remove("over");
  drop.ondrop = e => {
    e.preventDefault(); drop.classList.remove("over");
    files = [...e.dataTransfer.files]; show();
  };

  $("#kitBuild").onclick = async () => {
    if (!files.length) return input.click();
    const btn = $("#kitBuild");
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span> Reading your decks…';
    $("#kitUpErr").innerHTML = "";
    const fd = new FormData();
    files.forEach(f => fd.append("files", f));
    fd.append("name", $("#kitName").value);
    fd.append("notes", $("#kitNotes").value);
    try {
      const r = await fetch("/api/kits/from-upload", { method: "POST", body: fd });
      const j = await r.json().catch(() => ({ error: `Upload failed (${r.status}).` }));
      if (!r.ok) throw new Error(j.error || "Couldn't build a kit from that.");
      files = []; input.value = ""; show();
      $("#kitName").value = ""; $("#kitNotes").value = "";
      reloadInstalledFonts();
      await refreshKits();
      setCurrentKit(j.id);
      openKitEditor(j.id);
    } catch (e) {
      $("#kitUpErr").innerHTML = `<div class="err">${escHtml(e.message)}</div>`;
    } finally {
      btn.disabled = false; btn.textContent = "Build kit";
    }
  };

  $("#kitImport").onchange = async e => {
    const f = e.target.files[0];
    if (!f) return;
    const fd = new FormData(); fd.append("file", f);
    const r = await fetch("/api/kits/import", { method: "POST", body: fd });
    const j = await r.json();
    e.target.value = "";
    if (!r.ok) return alert(j.error || "Couldn't import that kit.");
    reloadInstalledFonts();
    await refreshKits();
    setCurrentKit(j.id);
  };
}

/* --- kit editor ---------------------------------------------- */

let KIT = null;   // the working copy being edited

async function openKitEditor(id) {
  const r = await fetch(`/api/kits/${id}`);
  if (!r.ok) return alert("Couldn't open that kit.");
  KIT = await r.json();
  $("#kitEdTitle").textContent = `Edit kit: ${KIT.name}`;
  $("#kitEdStatus").textContent = "";
  $("#kitSheet").hidden = false;   // visible first: previews size to their box
  renderKitEditor();
}

function kitColor(token) {
  const own = (KIT.theme.colors || {})[token];
  if (own) return own;
  // Fall back to the base value in theme.css, so the picker shows the truth.
  const v = getComputedStyle(document.documentElement).getPropertyValue(`--${token}`).trim();
  return /^#[0-9a-fA-F]{6}$/.test(v) ? v : "#000000";
}

function kitDraftSource() {
  return { _kit: { ...KIT.render, theme: KIT.theme, wordmark: KIT.brand.wordmark } };
}

function renderKitEditor() {
  const k = KIT;
  const caveats = (k.source && k.source.caveats) || "";
  const files = (k.source && k.source.files) || [];
  const fonts = k.theme.fonts || {};
  const seen = (k.source && k.source.fonts_seen) || {};

  $("#kitEdBody").innerHTML = `
    ${caveats ? `<div class="kit-caveat"><b>What this kit couldn't capture.</b> ${escHtml(caveats)}</div>` : ""}
    <div class="kit-ed-grid">
      <div>
        <h3>Identity</h3>
        <label>Name</label><input type="text" id="ke-name" value="${escAttr(k.name)}">
        <label>Description</label><input type="text" id="ke-desc" value="${escAttr(k.description)}">
        <label>Wordmark <span class="muted">(shown on covers when there's no logo)</span></label>
        <input type="text" id="ke-word" value="${escAttr(k.brand.wordmark)}">
        <label>Logo</label>
        <div class="kit-logo-row">
          ${k.render.logo ? `<img src="${k.render.logo}" alt="">` : `<span class="muted">None</span>`}
          <label class="btn-like">Upload…<input type="file" id="ke-logo" accept=".png,.jpg,.jpeg,.svg,.webp" hidden></label>
          ${k.render.logo ? `<button id="ke-logo-clear">Remove</button>` : ""}
        </div>

        <h3>Fonts <span class="muted" style="text-transform:none;letter-spacing:0">(any Google Fonts family)</span></h3>
        <label>Headings${seen.display ? ` <span class="muted">· source used ${escHtml(seen.display)}</span>` : ""}</label>
        <input type="text" id="ke-fd" value="${escAttr(fonts.display || "DM Sans")}">
        <label>Body${seen.body ? ` <span class="muted">· source used ${escHtml(seen.body)}</span>` : ""}</label>
        <input type="text" id="ke-fb" value="${escAttr(fonts.body || "Inter")}">

        <h3>Palette</h3>
        <div id="ke-roles">${ROLES.map(r => `
          <div class="role-row">
            <input type="color" data-token="${r.token}" value="${kitColor(r.token)}">
            <div class="rl">${escHtml(r.label)}<small>${escHtml(r.help)}</small></div>
            <input type="text" data-hex="${r.token}" value="${kitColor(r.token)}">
          </div>`).join("")}
        </div>
      </div>

      <div>
        <h3>Preview</h3>
        <div class="kit-tpls" id="ke-preview"></div>

        <h3>Voice <span class="muted" style="text-transform:none;letter-spacing:0">(rules the generator writes by)</span></h3>
        <textarea id="ke-voice" rows="9">${escHtml(k.voice)}</textarea>

        <h3>Slide templates (${k.slides.length})</h3>
        <div class="kit-tpls" id="ke-tpls"></div>
        ${files.length ? `<p class="muted" style="font-size:12px;margin-top:12px">Built from: ${files.map(escHtml).join(", ")}</p>` : ""}
      </div>
    </div>`;

  renderKitPreview();
  renderKitTemplates();
  wireKitEditor();
}

function renderKitPreview() {
  const pick = [];
  const by = l => KIT.slides.find(t => t.slide.layout === l && !pick.includes(t));
  [by("cover"), KIT.slides.find(t => t.slide.ground === "brown" || t.slide.ground === "ink"),
   KIT.slides.find(t => ["cards", "columns", "flow", "stats"].includes(t.slide.layout))]
    .forEach(t => { if (t && !pick.includes(t)) pick.push(t); });
  KIT.slides.forEach(t => { if (pick.length < 3 && !pick.includes(t)) pick.push(t); });
  const src = kitDraftSource();
  const box = $("#ke-preview");
  box.innerHTML = `<div class="cards-grid">${pick.map(t =>
    `<div class="tpl-card">${previewCard(t.slide, 0, 1, src)}</div>`).join("")}</div>`;
  fitPreviews(box);
}

function renderKitTemplates() {
  const src = kitDraftSource();
  const box = $("#ke-tpls");
  box.innerHTML = KIT.slides.length ? `<div class="cards-grid">${KIT.slides.map(t => `
    <div class="tpl-card">
      ${previewCard(t.slide, 0, 1, src)}
      <div class="tpl-meta">
        <div class="name">${escHtml(t.name)} <span class="chip">${escHtml(t.category)}</span></div>
        <div class="note">${escHtml(t.note)}</div>
      </div>
      <div class="kit-actions"><button class="danger" data-rm="${t.id}">Remove</button></div>
    </div>`).join("")}</div>`
    : `<div class="empty">No templates yet. Open a deck and use “Save slide to the kit”.</div>`;
  fitPreviews(box);
  $$("[data-rm]", box).forEach(b => b.onclick = () => {
    KIT.slides = KIT.slides.filter(t => t.id !== b.dataset.rm);
    KIT.decks.forEach(d => (d.slide_ids = d.slide_ids.filter(i => i !== b.dataset.rm)));
    renderKitTemplates();
    renderKitPreview();
  });
}

function wireKitEditor() {
  const setColor = (token, v) => {
    if (!/^#[0-9a-fA-F]{6}$/.test(v)) return;
    (KIT.theme.colors ||= {})[token] = v.toLowerCase();
    $(`[data-token="${token}"]`).value = v;
    $(`[data-hex="${token}"]`).value = v;
    renderKitPreview();
  };
  $$("[data-token]").forEach(i => (i.oninput = () => setColor(i.dataset.token, i.value)));
  $$("[data-hex]").forEach(i => (i.onchange = () => setColor(i.dataset.hex, i.value.trim())));
  $("#ke-word").oninput = e => { KIT.brand.wordmark = e.target.value; renderKitPreview(); };

  $("#ke-logo").onchange = async e => {
    const f = e.target.files[0];
    if (!f) return;
    await saveKit();  // keep unsaved edits before the round trip
    const fd = new FormData(); fd.append("file", f);
    const r = await fetch(`/api/kits/${KIT.id}/logo`, { method: "POST", body: fd });
    const j = await r.json();
    if (!r.ok) return alert(j.error || "Upload failed.");
    KIT = j; renderKitEditor();
  };
  const lc = $("#ke-logo-clear");
  if (lc) lc.onclick = async () => {
    await saveKit();
    KIT = await (await fetch(`/api/kits/${KIT.id}/logo`, { method: "DELETE" })).json();
    renderKitEditor();
  };
}

function collectKitForm() {
  KIT.name = $("#ke-name").value.trim() || KIT.name;
  KIT.description = $("#ke-desc").value.trim();
  KIT.brand.wordmark = $("#ke-word").value.trim();
  KIT.voice = $("#ke-voice").value;
  KIT.theme.fonts = { display: $("#ke-fd").value.trim() || "DM Sans",
                      body: $("#ke-fb").value.trim() || "Inter" };
}

async function saveKit() {
  collectKitForm();
  $("#kitEdStatus").textContent = "Saving…";
  const r = await fetch(`/api/kits/${KIT.id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      name: KIT.name, description: KIT.description, voice: KIT.voice,
      brand: KIT.brand, theme: KIT.theme, slides: KIT.slides, decks: KIT.decks,
    }),
  });
  const j = await r.json();
  if (!r.ok) { $("#kitEdStatus").textContent = "Save failed"; return; }
  KIT = j;
  forgetTemplates(KIT.id);
  reloadInstalledFonts();
  $("#kitEdStatus").textContent = "Saved";
  $("#kitEdTitle").textContent = `Edit kit: ${KIT.name}`;
  await refreshKits();
}

document.addEventListener("DOMContentLoaded", () => {
  $("#kitEdSave").onclick = async () => { await saveKit(); renderKitEditor(); };
  $("#kitEdClose").onclick = () => {
    $("#kitSheet").hidden = true;
    if ($("#tabs button.active")?.dataset.tab === "kits") loadKits();
  };
  $("#kitSheet").onclick = e => { if (e.target.id === "kitSheet") $("#kitEdClose").click(); };
});

/* --- from the editor: save the current slide into its kit ------ */

async function saveSlideToKit(s) {
  const kitName = deck._kit?.name || "the kit";
  const name = prompt(`Save this slide as a template in ${kitName}. Name it:`,
                      s.eyebrow || LAYOUTS[s.layout]?.name || "Saved slide");
  if (name === null) return;
  const r = await fetch(`/api/kits/${deck.kit}/slides`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ slide: s, name }),
  });
  if (!r.ok) return alert("Couldn't save that slide to the kit.");
  forgetTemplates(deck.kit);
  status(`Saved to ${kitName}`);
  setTimeout(() => status(""), 1800);
}
