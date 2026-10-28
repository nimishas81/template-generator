/* ============================================================
   Layout registry + renderer
   Shared by the editor and the export pipeline so that what you
   see in the browser is byte-identical to what Playwright prints.
   ============================================================ */

const LAYOUTS = {
  cover:     { name: "Cover",        uses: ["title", "dek", "art"] },
  section:   { name: "Section",      uses: ["eyebrow", "title", "dek"] },
  statement: { name: "Statement",    uses: ["title", "dek"] },
  quote:     { name: "Quote",        uses: ["title", "dek"] },
  cards:     { name: "Card grid",    uses: ["eyebrow", "title", "dek", "items", "variant", "footer"] },
  columns:   { name: "Columns",      uses: ["eyebrow", "title", "dek", "items", "variant", "footer"] },
  numbered:  { name: "Numbered",     uses: ["eyebrow", "title", "dek", "items", "variant", "footer"] },
  flow:      { name: "Flow",         uses: ["eyebrow", "title", "dek", "items", "variant", "footer"] },
  stats:     { name: "Stats",        uses: ["eyebrow", "title", "items", "footer"] },
  pillrows:  { name: "Pill rows",    uses: ["eyebrow", "title", "dek", "items", "footer"] },
  mapping:   { name: "Mapping",      uses: ["eyebrow", "title", "dek", "items", "footer"] },
  cycle:     { name: "Loop",         uses: ["eyebrow", "title", "dek", "items", "variant", "footer"] },
  diagram:   { name: "Diagram",      uses: ["eyebrow", "title", "dek", "items", "shape", "footer"] },
  ledger:    { name: "Ledger",       uses: ["eyebrow", "title", "dek", "items", "footer"] },
  bullets:   { name: "Bullets",      uses: ["eyebrow", "title", "dek", "items", "footer"] },
};

const VARIANTS = ["brown", "mint", "outline", "teal", "cream"];
const SHAPES = ["chain", "loop"];

/* Node kinds for the diagram layout. Order here is the legend's fallback order. */
const DIAGRAM_KINDS = ["input", "automation", "agent", "human", "output", "accent"];
const DIAGRAM_KIND_NAMES = {
  input: "Input", automation: "Automation", agent: "Agent",
  human: "Human", output: "Output", accent: "Highlight",
};

const ARROW_RIGHT =
  '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true">' +
  '<path d="M3 12h14M13 6l6 6-6 6" stroke="currentColor" stroke-width="3.2" ' +
  'stroke-linecap="round" stroke-linejoin="round"/></svg>';

/* Solid block arrow, as used on the flywheel and expansion slides. */
const ARROW_FAT =
  '<svg viewBox="0 0 24 24" aria-hidden="true">' +
  '<path d="M2 9.2h11V4l9 8-9 8v-5.2H2z" fill="currentColor"/></svg>';

const DEG = { right: 0, down: 90, left: 180, up: 270 };
function arrow(dir, fat) {
  const svg = fat ? ARROW_FAT : ARROW_RIGHT;
  const d = DEG[dir] || 0;
  return d ? svg.replace("<svg ", `<svg style="transform:rotate(${d}deg)" `) : svg;
}

/* Palette tokens a deck is allowed to override. Anything outside this list is
   ignored, so a bad suggestion can't inject arbitrary CSS. */
const THEME_TOKENS = [
  "green", "green-light", "green-pale", "mint-card", "teal-card",
  "ink", "ink-soft", "brown-card", "brown-deep", "brown-soft", "muted",
  "tan", "tan-warm", "tan-pale", "cream", "greige",
  "ground", "ground-warm", "ground-brown", "ground-ink",
];

/* The resolved theme for a deck: its brand kit first, then the deck's own
   overrides on top. `deck._kit` is attached by the server on every read. */
function mergedTheme(deck) {
  const kit = (deck && deck._kit && deck._kit.theme) || {};
  const own = (deck && deck.theme) || {};
  return {
    colors: { ...(kit.colors || {}), ...(own.colors || {}) },
    fonts: { ...(kit.fonts || {}), ...(own.fonts || {}) },
  };
}

/* The theme as bare declarations, e.g. `--green:#123456;`. */
function themeDecls(deck) {
  const t = (deck && (deck._kit || deck.theme)) ? mergedTheme(deck) : {};
  const out = [];
  for (const [k, v] of Object.entries(t.colors || {})) {
    if (THEME_TOKENS.includes(k) && /^#[0-9a-fA-F]{3,8}$/.test(String(v))) {
      out.push(`--${k}:${v};`);
    }
  }
  const q = f => `"${String(f).replace(/["\\]/g, "")}"`;
  if (t.fonts && t.fonts.display) out.push(`--display:${q(t.fonts.display)},"DM Sans",sans-serif;`);
  if (t.fonts && t.fonts.body) out.push(`--body:${q(t.fonts.body)},"Inter",sans-serif;`);
  return out.join("");
}

function themeCSS(deck) {
  const d = themeDecls(deck);
  return d ? `:root{${d}}` : "";
}

/* Inline form for card previews. Custom properties inherit, so putting them on
   a wrapper themes just that subtree — the Projects grid shows several decks at
   once and a global :root rule would leak the last one across all of them. */
function themeAttr(deck) {
  const d = themeDecls(deck);
  return d ? ` style="${d}"` : "";
}

/* Writes the deck's overrides into a single style tag, replacing any previous
   one. Called by the editor on every render and once by the export page. */
function applyTheme(deck) {
  let el = document.getElementById("deck-theme");
  if (!el) {
    el = document.createElement("style");
    el.id = "deck-theme";
    document.head.appendChild(el);
  }
  el.textContent = themeCSS(deck);
}

function esc(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

/* A field the editor can click into. `path` addresses it in the deck JSON. */
function field(tag, cls, path, value, extra) {
  const v = esc(value);
  if (!v && !EDITABLE) return "";
  return `<${tag} class="${cls}" data-path="${path}"${extra || ""}>${v}</${tag}>`;
}

/* EDITABLE is flipped to false by the export renderer so empty
   placeholder fields don't print as blank boxes. */
let EDITABLE = true;
function setEditable(v) { EDITABLE = !!v; }

/* The brand on the cover: the kit's logo if it has one, else its wordmark as
   styled text. Set per render, because previews show several kits at once. */
let LOGO_SRC = "";
let WORDMARK = "";
function setLogoSrc(v) { LOGO_SRC = v || ""; }
function setBrand(deck) {
  const k = (deck && deck._kit) || {};
  LOGO_SRC = k.logo || (deck && deck.logoSrc) || "";
  WORDMARK = k.wordmark || "";
}

function head(s, i) {
  let h = "";
  h += field("div", "s-eyebrow", `slides.${i}.eyebrow`, s.eyebrow);
  h += field("h1", "s-title", `slides.${i}.title`, s.title);
  h += field("div", "s-dek", `slides.${i}.dek`, s.dek);
  return `<div class="s-head">${h}</div>`;
}

function foot(s, i) {
  if (!s.footer && !EDITABLE) return "";
  const accent = s.footerAccent ? ` data-accent="${esc(s.footerAccent)}"` : "";
  return field("div", "s-foot", `slides.${i}.footer`, s.footer, accent);
}

function cardHTML(item, i, j, variant, extraCls) {
  const v = esc(variant || "mint");
  let inner = field("div", "card-label", `slides.${i}.items.${j}.label`, item.label);

  if (item.bullets && item.bullets.length) {
    const lis = item.bullets.map((b, k) =>
      `<li data-path="slides.${i}.items.${j}.bullets.${k}">${esc(b)}</li>`
    ).join("");
    inner += `<ul class="card-bullets">${lis}</ul>`;
  } else {
    inner += field("div", "card-body", `slides.${i}.items.${j}.body`, item.body);
  }
  return `<div class="card ${extraCls || ""}" data-variant="${v}">${inner}</div>`;
}

/* --- per-layout body renderers --- */

const BODY = {
  cover(s, i) {
    // The kit's logo, else its wordmark as styled text, else nothing.
    let logo = "";
    if (s.logo !== false) {
      if (LOGO_SRC) logo = `<div class="cover-logo"><img src="${esc(LOGO_SRC)}" alt="${esc(WORDMARK)}"></div>`;
      else if (WORDMARK) logo = `<div class="cover-logo cover-logo-text">${esc(WORDMARK)}</div>`;
    }
    const art = s.art ? `<div class="cover-art"><img src="${esc(s.art)}" alt=""></div>` : "";
    return `<div class="cover-copy">${logo}${head(s, i)}</div>${art}`;
  },

  cards(s, i) {
    const n = (s.items || []).length;
    const cols = n <= 1 ? 1 : n === 2 || n === 4 ? 2 : n >= 7 ? 4 : 3;
    const cards = (s.items || []).map((it, j) => cardHTML(it, i, j, s.variant)).join("");
    return `<div class="grid" data-cols="${cols}">${cards}</div>`;
  },

  columns(s, i) {
    const n = Math.max(1, (s.items || []).length);
    const cards = (s.items || []).map((it, j) => {
      let c = cardHTML(it, i, j, s.variant || "outline", "col-card");
      if (it.value) {
        const badge = field("div", "stat-badge", `slides.${i}.items.${j}.value`, it.value);
        c = c.replace(/<\/div>$/, badge + "</div>");
      }
      return c;
    }).join("");
    return `<div class="grid" data-cols="${Math.min(n, 4)}">${cards}</div>`;
  },

  numbered(s, i) {
    const groups = [];
    (s.items || []).forEach((it, j) => {
      const key = it.group || "";
      let g = groups.find(x => x.key === key);
      if (!g) { g = { key, items: [] }; groups.push(g); }
      g.items.push({ it, j });
    });
    const html = groups.map((g, gi) => {
      const cards = g.items.map(({ it, j }) =>
        cardHTML(it, i, j, s.variant || "outline")).join("");
      const label = g.key
        ? `<div class="num-head"><div class="num-dot">${gi + 1}</div>` +
          `<div class="num-label" data-path="slides.${i}.items.${g.items[0].j}.group">${esc(g.key)}</div></div>`
        : "";
      return `<div class="num-group">${label}<div class="num-cards">${cards}</div></div>`;
    }).join("");
    return `<div class="numbered" data-cols="${Math.min(groups.length, 3)}">${html}</div>`;
  },

  flow(s, i) {
    const parts = [];
    (s.items || []).forEach((it, j) => {
      if (j) parts.push(`<div class="flow-arrow">${ARROW_RIGHT}</div>`);
      parts.push(cardHTML(it, i, j, s.variant || "brown"));
    });
    return `<div class="flow">${parts.join("")}</div>`;
  },

  stats(s, i) {
    const html = (s.items || []).map((it, j) =>
      `<div class="stat">` +
      field("div", "stat-label", `slides.${i}.items.${j}.label`, it.label) +
      field("div", "stat-value", `slides.${i}.items.${j}.value`, it.value) +
      field("div", "stat-caption", `slides.${i}.items.${j}.body`, it.body) +
      `</div>`).join("");
    // data-n drives type scaling: four numerals need to be smaller than two.
    return `<div class="stats" data-n="${(s.items || []).length}">${html}</div>`;
  },

  pillrows(s, i) {
    const html = (s.items || []).map((it, j) =>
      `<div class="pillrow">` +
      field("div", "pill", `slides.${i}.items.${j}.label`, it.label) +
      `<div class="pillrow-arrow">${ARROW_RIGHT}</div>` +
      field("div", "pillrow-text", `slides.${i}.items.${j}.body`, it.body) +
      `</div>`).join("");
    return `<div class="pillrows">${html}</div>`;
  },

  /* Two pill columns joined by one arrow: "what it learns" -> "where it's used".
     `group` picks the column, `value` sets pill emphasis (solid / ghost). */
  mapping(s, i) {
    const cols = [];
    (s.items || []).forEach((it, j) => {
      const key = it.group || "";
      let c = cols.find(x => x.key === key);
      if (!c) { c = { key, items: [] }; cols.push(c); }
      c.items.push({ it, j });
    });
    const col = c => {
      const pills = c.items.map(({ it, j }) => {
        const state = ["solid", "ghost"].includes(it.value) ? it.value : "";
        return field("div", "map-pill", `slides.${i}.items.${j}.label`, it.label,
                     state ? ` data-state="${state}"` : "");
      }).join("");
      const head = c.key
        ? `<div class="map-head" data-path="slides.${i}.items.${c.items[0].j}.group">${esc(c.key)}</div>`
        : "";
      return `<div class="map-col">${head}${pills}</div>`;
    };
    const left = cols[0] ? col(cols[0]) : "<div></div>";
    const right = cols[1] ? col(cols[1]) : "<div></div>";
    return `<div class="mapping">${left}` +
           `<div class="map-arrow">${arrow("right", true)}</div>${right}</div>`;
  },

  /* Six steps in a closed loop. Reading order is clockwise: the top row runs
     left to right, the bottom row right to left, so item 6 sits under item 1. */
  cycle(s, i) {
    const items = (s.items || []).slice(0, 6);
    const cells = [
      { r: 1, c: 1 }, { r: 1, c: 3 }, { r: 1, c: 5 },
      { r: 3, c: 5 }, { r: 3, c: 3 }, { r: 3, c: 1 },
    ];
    let html = items.map((it, j) => {
      const { r, c } = cells[j];
      const label = field("div", "card-label", `slides.${i}.items.${j}.label`, it.label);
      return `<div class="card" data-variant="${esc(s.variant || "mint")}"` +
             ` style="grid-row:${r};grid-column:${c}">` +
             `<div class="cycle-n">${j + 1}</div>${label}</div>`;
    }).join("");

    // Connectors, drawn only where both neighbouring steps exist.
    const link = (r, c, dir) =>
      `<div class="cycle-arrow" style="grid-row:${r};grid-column:${c}">${arrow(dir, true)}</div>`;
    if (items.length > 1) html += link(1, 2, "right");
    if (items.length > 2) html += link(1, 4, "right");
    if (items.length > 3) html += link(2, 5, "down");
    if (items.length > 4) html += link(3, 4, "left");
    if (items.length > 5) html += link(3, 2, "left");
    if (items.length > 5) html += link(2, 1, "up");
    return `<div class="cycle">${html}</div>`;
  },

  /* Two columns of line items with amounts — the "Ask" slide. `group` picks the
     column, `value` is the amount. An item with no label renders as a note. */
  ledger(s, i) {
    const cols = [];
    (s.items || []).forEach((it, j) => {
      const key = it.group || "";
      let c = cols.find(x => x.key === key);
      if (!c) { c = { key, items: [] }; cols.push(c); }
      c.items.push({ it, j });
    });
    const html = cols.slice(0, 2).map((c, ci) => {
      const rows = c.items.map(({ it, j }) => {
        if (!it.label && it.body) {
          return field("div", "led-note", `slides.${i}.items.${j}.body`, it.body);
        }
        const left =
          field("div", "led-label", `slides.${i}.items.${j}.label`, it.label) +
          (it.body || EDITABLE
            ? field("div", "led-sub", `slides.${i}.items.${j}.body`, it.body)
            : "");
        return `<div class="led-row"><div>${left}</div>` +
               field("div", "led-value", `slides.${i}.items.${j}.value`, it.value) +
               `</div>`;
      }).join("");
      const head = c.key
        ? `<div class="led-head">` +
          `<div class="led-head-label" data-path="slides.${i}.items.${c.items[0].j}.group">${esc(c.key)}</div>` +
          `</div>`
        : "";
      return `<div class="led-col" data-style="${ci === 0 ? "filled" : "ruled"}">${head}${rows}</div>`;
    }).join("");
    return `<div class="ledger">${html}</div>`;
  },

  /* Typed node chain. `group` is the node kind (drives colour and the legend),
     `value` is the chip above the node, `body` the sublabel. `shape: "loop"`
     serpentines the chain and draws a return path. */
  diagram(s, i) {
    const items = s.items || [];
    const loop = s.shape === "loop";
    // Balance the rows rather than filling the first: 6 nodes reads far better
    // as 3+3 than as 5+1.
    const perRow = loop
      ? Math.ceil(items.length / Math.max(1, Math.ceil(items.length / 5)))
      : items.length;

    const rows = [];
    for (let j = 0; j < items.length; j += perRow) {
      rows.push(items.slice(j, j + perRow).map((it, k) => ({ it, j: j + k })));
    }

    const kindOf = it => (DIAGRAM_KINDS.includes(it.group) ? it.group : "automation");

    const cell = ({ it, j }) => {
      const kind = kindOf(it);
      const chip = field("div", "dgm-chip", `slides.${i}.items.${j}.value`, it.value,
                         ` data-kind="${kind}"`);
      const label = field("div", "dgm-label", `slides.${i}.items.${j}.label`, it.label);
      const sub = field("div", "dgm-sub", `slides.${i}.items.${j}.body`, it.body);
      return `<div class="dgm-cell" style="flex:1">${chip}` +
             `<div class="dgm-node" data-kind="${kind}">${label}${sub}</div></div>`;
    };

    const rowHTML = rows.map((row, r) => {
      const parts = [];
      row.forEach((entry, k) => {
        if (k) parts.push(`<div class="dgm-arrow">${ARROW_RIGHT}</div>`);
        parts.push(cell(entry));
      });
      // Pad a short final row so its columns line up with the rows above.
      // On a reversed row these render at the left, which is where the gap
      // belongs — the path enters from the row above on the right.
      for (let k = row.length; k < perRow; k++) {
        parts.push('<div class="dgm-spacer"></div>');
      }
      // Odd rows reverse so the chain reads as one continuous path.
      const dir = loop && r % 2 === 1 ? ' data-dir="rtl"' : "";
      const rowEl = `<div class="dgm-row" data-n="${perRow}"${dir}>${parts.join("")}</div>`;
      // Drop connector into the next row, on the side the path exits from.
      const drop = (loop && r < rows.length - 1)
        ? `<div class="dgm-drop" data-side="${r % 2 === 0 ? "right" : "left"}" ` +
          `style="--n:${perRow}">${arrow("right", false)}</div>`
        : "";
      return rowEl + drop;
    }).join("");

    // Legend, in the order the kinds first appear.
    const used = [];
    items.forEach(it => { const k = kindOf(it); if (!used.includes(k)) used.push(k); });
    const legend = used.length > 1
      ? `<div class="dgm-legend">${used.map(k =>
          `<div class="dgm-legend-item"><span class="dgm-swatch" data-kind="${k}"></span>` +
          `${DIAGRAM_KIND_NAMES[k] || k}</div>`).join("")}</div>`
      : "";

    const ret = loop
      ? `<div class="dgm-return">` +
        `<div class="dgm-return-track">${ARROW_RIGHT}<div class="dgm-return-line"></div></div>` +
        field("div", "dgm-return-label", `slides.${i}.returnLabel`,
              s.returnLabel || "each cycle feeds the next") +
        `</div>`
      : "";

    return `<div class="diagram">${legend}<div class="dgm-rows">${rowHTML}</div>${ret}</div>`;
  },

  bullets(s, i) {
    const html = (s.items || []).map((it, j) =>
      `<div class="bullet-row"><div class="bullet-dot"></div><div>` +
      field("span", "bullet-label", `slides.${i}.items.${j}.label`, it.label) +
      (it.label && it.body ? " " : "") +
      field("span", "bullet-body", `slides.${i}.items.${j}.body`, it.body) +
      `</div></div>`).join("");
    return `<div class="bullets">${html}</div>`;
  },
};

function renderSlide(s, i, total) {
  const layout = LAYOUTS[s.layout] ? s.layout : "cards";
  const ground = s.ground ? ` data-ground="${esc(s.ground)}"` : "";

  let html;
  if (layout === "cover") {
    html = `<div class="s-body">${BODY.cover(s, i)}</div>`;
  } else {
    const body = BODY[layout] ? `<div class="s-body">${BODY[layout](s, i)}</div>` : "";
    html = head(s, i) + body + foot(s, i);
  }

  const num = `<div class="page-num">${i + 1} / ${total}</div>`;
  // A slide's own colour overrides ride as inline custom properties, so they
  // beat the deck's :root values for this slide only.
  return `<section class="slide" data-layout="${layout}"${ground}` +
         ` data-index="${i}"${themeAttr(s)}>${html}${num}</section>`;
}

function renderDeck(deck) {
  const slides = deck.slides || [];
  return slides.map((s, i) => renderSlide(s, i, slides.length)).join("");
}

if (typeof module !== "undefined") {
  module.exports = { renderDeck, renderSlide, LAYOUTS, VARIANTS, SHAPES, THEME_TOKENS,
                     DIAGRAM_KINDS, DIAGRAM_KIND_NAMES,
                     setEditable, setLogoSrc, setBrand, applyTheme, themeCSS, themeAttr };
}
