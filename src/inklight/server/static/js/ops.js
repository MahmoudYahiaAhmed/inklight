// The operation panel: one operation at a time, with its steps, its scope and one obvious next action.

import { $, announce, api, errorBox, h, loading, onChange, pageMethod, pageText, plural, reducedMotion, saveBlob, store } from "./dom.js";
import { showView, startStructure } from "./library.js";
import { openDoc, setMarks } from "./viewer.js";

const OPS = {};  // name -> { title, help, steps(state) -> [labels, now], render(body) }
export function registerOp(name, op) { OPS[name] = op; }

export function selectOp(name) {
  store.op = name;
  for (const b of document.querySelectorAll(".op")) b.setAttribute("aria-pressed", String(b.dataset.op === name));
  renderOps();
  $("#ops-body").querySelector("input:not([type=checkbox]), textarea")?.focus({ preventScroll: true });
}

export function renderOps() {
  const op = OPS[store.op];
  if (!op) return;
  const [labels, now] = op.steps();
  $("#steps").replaceChildren(...labels.map((l, i) => h("li", { class: `step ${i < now ? "done" : i === now ? "now" : ""}`,
    "aria-current": i === now ? "step" : null }, h("span", {}, l))));
  const body = $("#ops-body");
  // The panel eases in when the operation changes, not on every refresh of the same one.
  if (body.dataset.op !== store.op) {
    body.dataset.op = store.op;
    body.classList.remove("entering");
    void body.offsetWidth;
    body.classList.add("entering");
  }
  body.replaceChildren(h("div", { class: "op-head" },
    h("h2", { class: "op-title" }, op.title, op.experimental ? h("span", { class: "tag" }, "experimental") : null),
    h("p", { class: "op-help" }, op.help)));
  op.render(body);
}

// What to do when an operation has nothing to work on yet: the next action, in words and as a button.
export function startHint(what) {
  const add = h("button", { class: "btn small", type: "button", onclick: () => $("#file").click() }, "Add documents");
  const lib = h("button", { class: "btn small quiet", type: "button", onclick: () => showView("library") }, "Go to the library");
  return h("div", { class: "hint-card" },
    h("span", {}, store.docs.length ? h("b", {}, "Open a document first. ") : h("b", {}, "The library is empty. "),
      store.docs.length ? `Click a name in the library; ${what}` : `Add a PDF, scan or photo; it is read ${store.where}. Then ${what}`),
    h("div", { class: "row" }, store.docs.length ? lib : add));
}

// ------------------------------------------------------------------ shared pieces

export function scopeBox(kind) {
  if (kind === "open") {
    return store.open
      ? h("div", { class: "scope-box" }, "Document: ", h("b", { dir: "auto" }, store.open.name))
      : h("div", { class: "scope-box" }, "No document open. ", h("button", { class: "btn small", type: "button", onclick: () => showView("library") }, "Choose one in the library"));
  }
  const ids = scopeIds();
  const text = store.selected.size ? `${plural(ids.length, "selected document")}` : store.open ? "The open document" : "No document chosen";
  return h("div", { class: "scope-box" }, h("b", {}, text), store.selected.size ? null : h("span", { class: "muted" },
    store.open ? h("span", { dir: "auto" }, ` (${store.open.name}). Tick documents in the library to use several.`) : " Open a document, or tick several in the library."));
}

export function scopeIds() {
  if (store.selected.size) return [...store.selected];
  return store.open ? [store.open.id] : [];
}

// A download that is prepared first (the server builds it), then saved; the button says which.
export function exportButton(label, fetchBlob, name) {
  const btn = h("button", { class: "btn", type: "button" }, label);
  btn.addEventListener("click", async () => {
    const before = btn.textContent;
    btn.disabled = true;
    btn.replaceChildren(h("span", { class: "spinner", "aria-hidden": "true" }), " Preparing…");
    try {
      saveBlob(await fetchBlob(), name);
      btn.textContent = "Saved ✓";
      announce(`${name} saved`);
      setTimeout(() => { btn.textContent = before; btn.disabled = false; }, 1600);
    } catch (err) {
      btn.textContent = before; btn.disabled = false;
      btn.after(errorBox(`Export failed: ${err.message}`));
    }
  });
  return btn;
}

const rawBlob = (fmt) => () => api(`/api/documents/${store.open.id}/export?format=${fmt}`, { raw: true }).then((r) => r.blob());
const stem = () => (store.open?.name || "document").replace(/\.[^.]+$/, "");

export function rawNote() {
  return h("p", { class: "note raw" }, h("span", { class: "label raw" }, "Raw extraction"), " As read, not reviewed. A value read by OCR can be misread, and OCR confidence is only an estimate.");
}

// ------------------------------------------------------------------ extract text

registerOp("text", {
  title: "Extract text",
  help: "The text of a document as it was read, page by page. Nothing is interpreted.",
  steps: () => [["Choose a document", "Read the text", "Export"], store.open ? 1 : 0],
  render(body) {
    if (!store.open) { body.append(startHint("its text appears here, page by page, and downloads as .txt or .json.")); return; }
    body.append(scopeBox("open"));
    const p = store.pages.find((x) => x.number === store.page);
    body.append(rawNote(),
      h("div", { class: "card" },
        h("div", { class: "card-head" }, h("span", { class: "card-title" }, `Page ${store.page} of ${store.pages.length}`),
          p ? h("span", {}, `read as ${pageMethod(p.source)}`) : null),
        h("pre", { class: "text-out", dir: "auto" }, pageText(p) || "(no text on this page)"),
        h("div", { class: "row" },
          h("button", { class: "btn small", type: "button", disabled: store.page <= 1 || null, onclick: () => openDoc(store.open.id, store.page - 1) }, "Previous page"),
          h("button", { class: "btn small", type: "button", disabled: store.page >= store.pages.length || null, onclick: () => openDoc(store.open.id, store.page + 1) }, "Next page"),
          h("span", { class: "grow" }),
          h("button", { class: "btn small", type: "button", onclick: (e) => copyText(e.target, p) }, "Copy page"))),
      h("div", { class: "next" },
        exportButton("Download all text (.txt)", rawBlob("txt"), `${stem()}-raw.txt`),
        exportButton("Text with boxes (.json)", rawBlob("json"), `${stem()}-raw.json`)));
  },
});

async function copyText(btn, p) {
  try {
    await navigator.clipboard.writeText(pageText(p));
    btn.textContent = "Copied ✓";
  } catch (_) { btn.textContent = "Copy not allowed here"; }
  setTimeout(() => { btn.textContent = "Copy page"; }, 1500);
}

// ------------------------------------------------------------------ extract tables

let structureInstalled = false;
export function setStructureInstalled(v) { structureInstalled = v; }

registerOp("tables", {
  title: "Extract tables",
  help: "Rows, columns and header cells, recovered by document structure. Cells hold the OCR text.",
  steps: () => [["Choose a document", "Find tables", "Check and export"], !store.open ? 0 : store.structure?.available ? 2 : 1],
  render(body) {
    if (!store.open) { body.append(startHint("its tables appear here with their header rows, and download as .csv.")); return; }
    body.append(scopeBox("open"));
    if (!store.structure?.available) {
      body.append(h("div", { class: "card" },
        h("p", {}, "This document was read without document structure, so its tables were not recovered."),
        structureInstalled
          ? h("div", { class: "next" }, h("button", { class: "btn primary", type: "button", onclick: async (e) => {
              e.target.disabled = true;
              try { await startStructure(store.open.id); e.target.replaceWith(h("p", { class: "muted" }, "Reading it again with structure. Progress is shown in the library; the tables appear here when it ends.")); }
              catch (err) { e.target.disabled = false; e.target.after(errorBox(err.message)); }
            } }, "Read it again with structure"))
          : h("p", { class: "muted" }, "Document structure is not installed. Install it with: pip install \"inklight[structure]\"")));
      return;
    }
    const out = h("div", { class: "card" }, loading("Loading the tables…"));
    body.append(rawNote(), out);
    const id = store.open.id;
    api(`/api/documents/${id}/tables`).then((tables) => {
      if (store.open?.id !== id || store.op !== "tables") return;
      out.replaceWith(...(tables.length ? tables.map(tableCard) : [h("div", { class: "card muted" }, "No table found in this document.")]),
        h("div", { class: "next" }, tables.length ? exportButton("Download tables (.csv)", rawBlob("tables.csv"), `${stem()}-tables.csv`) : null));
      announce(tables.length ? `${plural(tables.length, "table")} found` : "No table found");
    }).catch((err) => out.replaceWith(errorBox(`The tables could not be loaded: ${err.message}`)));
  },
});

function tableCard(t) {
  const stagger = reducedMotion() ? 0 : Math.min(40, 400 / Math.max(t.rows.length, 1));
  return h("div", { class: "card" },
    h("div", { class: "card-head" }, h("span", { class: "card-title" }, `Table ${t.index}`), h("span", {}, `page ${t.page}`),
      h("span", {}, `${plural(t.rows.length, "row")} × ${Math.max(...t.rows.map((r) => r.length))} columns`),
      h("span", { class: "grow" }),
      h("button", { class: "btn small", type: "button", onclick: () => showTableOnPage(t) }, "Show on page")),
    h("div", { class: "grid-wrap" }, h("table", { class: "grid" }, h("tbody", {}, ...t.rows.map((row, r) =>
      h("tr", { class: stagger ? "reveal" : "", style: stagger ? `animation-delay:${r * stagger}ms` : null },
        ...row.map((cell) => h(t.header_rows.includes(r) ? "th" : "td", { dir: "auto" }, cell))))))));
}

function showTableOnPage(t) {
  const page = store.pages.find((p) => p.number === t.page);
  // The table's own region (its block refers to it); every table region of the page when no block does.
  const tables = (page?.blocks || []).filter((b) => b.label === "Table" && b.bbox);
  const own = tables.filter((b) => b.ref === `#/tables/${t.index - 1}`);
  const boxes = own.length ? own : tables;
  const marks = boxes.map((b) => ({ page: t.page, bbox: b.bbox, kind: "table", title: "Table region", label: `Table ${t.index}` }));
  if (store.page !== t.page) openDoc(store.open.id, t.page, marks); else setMarks(marks, t.page);
  showView("viewer");
}

// ------------------------------------------------------------------ search

const search = { q: "", hits: null, active: -1, error: null };

registerOp("search", {
  title: "Search",
  help: "Find passages across every document, in Arabic or English. Each match opens at its place on the page.",
  steps: () => [["Search", "Open a match"], search.hits?.length ? 1 : 0],
  render(body) {
    const input = h("input", { type: "search", value: search.q, placeholder: "Words to find, e.g. رقم القيد or registration number",
      "aria-label": "Search the library", dir: "auto" });
    input.addEventListener("input", () => { search.q = input.value; });
    const form = h("form", { class: "row" }, h("div", { class: "grow" }, input), h("button", { class: "btn primary", type: "submit" }, "Search"));
    form.addEventListener("submit", (e) => { e.preventDefault(); runSearch(input.value.trim()); });
    body.append(form);
    if (search.error) body.append(errorBox(search.error));
    if (search.hits === "loading") body.append(loading("Searching…"));
    else if (search.hits) {
      body.append(h("p", { class: "muted" }, search.hits.length ? `${plural(search.hits.length, "match", "matches")} · choose one to open it` : "No passage matches."),
        h("div", { class: "results", role: "list" }, ...search.hits.map((x, i) => hitButton(x.source, i))));
    }
  },
});

async function runSearch(q) {
  if (!q) return;
  Object.assign(search, { q, hits: "loading", active: -1, error: null });
  renderOps();
  try {
    search.hits = await api(`/api/search?q=${encodeURIComponent(q)}&k=20`);
    announce(search.hits.length ? `${plural(search.hits.length, "match", "matches")}` : "No match");
  } catch (err) { search.hits = null; search.error = err.message; }
  renderOps();
}

function hitButton(s, i) {
  return h("button", { class: `result ${search.active === i ? "active" : ""}`, type: "button", role: "listitem",
    onclick: () => {
      search.active = i;
      openDoc(s.doc_id, s.page, s.bbox ? [{ page: s.page, bbox: s.bbox, kind: "hit", title: "Search match" }] : []);
      showView("viewer");
    } },
    h("b", { dir: "auto" }, `${s.name} · page ${s.page}`),
    h("span", { dir: "auto" }, `“${s.excerpt.replace(/\s+/g, " ").slice(0, 220)}${s.excerpt.length > 220 ? "…" : ""}”`));
}

export function wireOps() {
  for (const b of document.querySelectorAll(".op")) b.addEventListener("click", () => { selectOp(b.dataset.op); showView("ops"); });
  onChange((what) => {
    if (what === "open") renderOps();
    if ((what === "selection" || what === "docs") && store.op !== "tables") refreshWhenIdle();
    if (what === "restructured") import("./viewer.js").then((v) => v.reloadOpen());
  });
}

// A change in the library (an import ending, a document ticked) refreshes the panel, but not under the user's
// fingers: while a field of the panel has focus, the refresh waits until it is left.
let pending = false;
function refreshWhenIdle() {
  const active = document.activeElement;
  if (active && $("#ops-body").contains(active) && active.matches("input, textarea, select")) {
    if (!pending) {
      pending = true;
      active.addEventListener("blur", () => { pending = false; setTimeout(renderOps, 0); }, { once: true });
    }
    return;
  }
  renderOps();
}
