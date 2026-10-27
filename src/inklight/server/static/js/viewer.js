// The document viewer: the page as the file shows it, the regions that were read, and marks that say what they are
// (search match, source of a value, value to check, table). Stored boxes are in the upright frame of the page
// (p.width x p.height); the image is the page as the file shows it, turned p.rotation degrees counter-clockwise
// from upright (inklight/frames.py), so every box is turned the same way before it is drawn.

import { $, api, changed, fill, h, pageMethod, pageText, readAs, reducedMotion, sourcesOf, store, withToken } from "./dom.js";

const view = { mode: "image", processing: null, fresh: false };
// processing: {jobId, index, label} while a file is being read; fresh: the open document has just been read, so its
// regions appear one after another the first time they are drawn.

export async function openDoc(id, page = 1, marks = [], { fresh = false } = {}) {
  view.processing = null;
  view.fresh = fresh;
  if (store.open?.id !== id) {
    const data = await api(`/api/documents/${id}`);
    store.open = data.document;
    store.pages = data.pages;
    store.structure = data.structure;
  }
  store.page = Math.max(1, Math.min(page, store.pages.length || 1));
  store.marks = marks;
  render();
  changed("open");
}

export async function reloadOpen() {
  if (!store.open) return;
  const id = store.open.id;
  store.open = null;
  await openDoc(id, store.page, store.marks);
}

export function closeDoc(id) {
  if (store.open?.id !== id) return;
  store.open = null; store.pages = []; store.structure = null; store.marks = [];
  render();
  changed("open");
}

export function setMarks(marks, page) {
  store.marks = marks;
  if (page && page !== store.page) store.page = page;
  render();
}

// While a file is being read there is no stored page yet: the viewer shows the file as uploaded, under a quiet
// sweep, with the stage the server reported. Nothing is drawn on the page until the reading is stored.
export function showProcessing(jobId, index, label) {
  const same = view.processing && view.processing.jobId === jobId && view.processing.index === index;
  view.processing = { jobId, index, label };
  if (!same) { store.open = null; store.pages = []; store.marks = []; changed("open"); }
  render();
}

export function processingTarget() { return view.processing; }

export function stopProcessing() {
  if (!view.processing) return;
  view.processing = null;
  render();
}

export function render() {
  const page = $("#page"), img = $("#page-img"), text = $("#page-text"), empty = $("#viewer-empty");
  const proc = $("#processing"), procLabel = $("#processing-label"), overlay = $("#overlay");
  overlay.replaceChildren();
  if (view.processing) {
    const { jobId, index, label } = view.processing;
    $("#viewer-title").textContent = label.name;
    $("#viewer-meta").textContent = "Being read. The page appears with its regions when the reading is stored.";
    $("#page-label").textContent = label.page || "–";
    empty.classList.add("hidden"); text.classList.add("hidden"); page.classList.remove("hidden");
    const src = withToken(`/api/jobs/${jobId}/files/${index}/preview`);
    if (img.dataset.src !== src) {
      img.dataset.src = src; img.classList.add("loading-img"); img.alt = `First page of ${label.name}, as uploaded`;
      img.onload = () => img.classList.remove("loading-img");
      img.src = src;
    }
    // A file that cannot be drawn (a broken PDF) keeps an empty frame with its stage, not the start guide; the
    // failure is remembered, since later renders do not load the image again.
    const failed = img.dataset.failed === src;
    page.classList.toggle("no-preview", failed);
    img.onerror = () => { img.dataset.failed = img.dataset.src; page.classList.add("no-preview"); proc.classList.add("hidden"); };
    // The scan line runs only while the OCR reads; structuring has no per-region progress, so it is a quiet frame.
    proc.classList.toggle("hidden", !label.active || failed);
    proc.classList.toggle("structuring", label.phase === "structuring");
    page.classList.toggle("reading", Boolean(label.active));
    procLabel.classList.remove("hidden");
    procLabel.textContent = label.stage;
    $("#readout").textContent = "";
    return;
  }
  proc.classList.add("hidden"); procLabel.classList.add("hidden"); page.classList.remove("reading", "no-preview");
  const doc = store.open;
  if (!doc) {
    $("#viewer-title").textContent = "No document open";
    $("#viewer-meta").textContent = "Choose a document in the library.";
    $("#page-label").textContent = "–";
    page.classList.add("hidden"); text.classList.add("hidden"); empty.classList.remove("hidden");
    img.removeAttribute("src"); delete img.dataset.src;
    $("#readout").textContent = "";
    return;
  }
  empty.classList.add("hidden");
  const p = store.pages.find((x) => x.number === store.page);
  $("#viewer-title").textContent = doc.name;
  $("#viewer-meta").textContent = meta(doc, p);
  $("#page-label").textContent = `${store.page} / ${store.pages.length}`;
  text.textContent = pageText(p);
  const asText = view.mode === "text" || !p || !p.width;
  page.classList.toggle("hidden", asText);
  text.classList.toggle("hidden", !asText);
  if (asText) { $("#readout").textContent = ""; return; }
  const src = withToken(`/api/documents/${doc.id}/pages/${store.page}/image`);
  if (img.dataset.src !== src) {
    img.dataset.src = src; img.classList.add("loading-img"); img.alt = `Page ${store.page} of ${doc.name}`;
    img.onload = () => img.classList.remove("loading-img");
    img.src = src;
  }
  img.onerror = () => { page.classList.add("hidden"); text.classList.remove("hidden"); };
  drawMarks(p, overlay, img);
}

function meta(doc, p) {
  const all = readAs(sourcesOf(store.pages));
  const how = all.startsWith("mixed") && p ? `${all} · this page: ${pageMethod(p.source)}` : all;
  const st = store.structure;
  const structure = st?.available ? (st.pages[store.page] || "") : "no document structure";
  const turned = p?.rotation ? `page turned ${p.rotation}°, shown as in the file` : "";
  return [`${doc.pages} page${doc.pages === 1 ? "" : "s"}`, how, structure, turned].filter(Boolean).join(" · ");
}

function drawMarks(p, overlay, img) {
  const turn = (((p.rotation || 0) % 360) + 360) % 360;
  const [ow, oh] = turn === 90 || turn === 270 ? [p.height, p.width] : [p.width, p.height];
  const shown = (x, y) => (turn === 90 ? [y, p.width - x] : turn === 180 ? [p.width - x, p.height - y] : turn === 270 ? [p.height - y, x] : [x, y]);
  const place = (bbox) => {
    const [ax, ay] = shown(bbox[0], bbox[1]);
    const [bx, by] = shown(bbox[2], bbox[3]);
    return [Math.min(ax, bx) / ow, Math.min(ay, by) / oh, Math.abs(bx - ax) / ow, Math.abs(by - ay) / oh];
  };
  const pct = (v) => (Number.isFinite(Number(v)) ? Number(v) * 100 : 0);  // boxes are numbers; anything else is 0
  const style = ([x, y, w, hh]) => `left:${pct(x)}%;top:${pct(y)}%;width:${pct(w)}%;height:${pct(hh)}%`;
  overlay.classList.toggle("no-regions", !$("#show-regions").checked);
  const stagger = view.fresh && !reducedMotion() ? Math.min(18, 600 / Math.max(p.blocks.length, 1)) : 0;
  p.blocks.forEach((b, i) => {
    if (!b.bbox) return;
    overlay.append(h("div", { class: `mark region${view.fresh ? "" : " settled"}`, title: b.label, style: `${style(place(b.bbox))};animation-delay:${i * stagger}ms` }));
  });
  view.fresh = false;
  let first = null;
  const here = store.marks.filter((x) => x.page === store.page && x.bbox);
  for (const m of here) {
    const box = place(m.bbox);
    const el = h("div", { class: `mark ${m.kind}`, title: m.title || "", style: style(box) });
    overlay.append(el);
    if (m.label) overlay.append(h("div", { class: `mark-label ${m.kind}`, style: `left:${pct(box[0])}%;top:${pct(box[1])}%` }, m.label));
    first = first || box;
  }
  // The readout states the stored geometry of what is marked (page pixels, upright frame), or the regions found.
  const b = here[0]?.bbox?.map(Number);
  // The mark's name may be Arabic: it is isolated so the numbers after it keep their order.
  fill($("#readout"), b && b.every(Number.isFinite)
    ? [h("bdi", { dir: "auto" }, here[0].label || here[0].title || here[0].kind),
      ` · p.${store.page} · x ${Math.round(b[0])} y ${Math.round(b[1])} · ${Math.round(b[2] - b[0])}×${Math.round(b[3] - b[1])} px${here.length > 1 ? ` · +${here.length - 1} more` : ""}`]
    : p.blocks.length ? `${p.blocks.length} regions · p.${store.page}${turn ? ` · turned ${turn}°` : ""}` : "");
  if (first) {
    const go = () => {
      const wrap = $("#page-wrap");
      wrap.scrollTo({ top: Math.max(0, first[1] * img.clientHeight - 120), behavior: reducedMotion() ? "auto" : "smooth" });
    };
    if (img.complete && img.naturalWidth && !img.classList.contains("loading-img")) go(); else img.addEventListener("load", go, { once: true });
  }
}

export function wireViewer() {
  $("#prev-page").addEventListener("click", () => store.open && openDoc(store.open.id, store.page - 1, store.marks));
  $("#next-page").addEventListener("click", () => store.open && openDoc(store.open.id, store.page + 1, store.marks));
  const seg = (mode) => {
    view.mode = mode;
    $("#show-image").setAttribute("aria-pressed", String(mode === "image"));
    $("#show-text").setAttribute("aria-pressed", String(mode === "text"));
    render();
  };
  $("#show-image").addEventListener("click", () => seg("image"));
  $("#show-text").addEventListener("click", () => seg("text"));
  $("#show-regions").addEventListener("change", render);
  document.addEventListener("keydown", (e) => {
    if (!store.open || e.target.closest("input, textarea, select")) return;
    if (e.key === "PageDown") { e.preventDefault(); openDoc(store.open.id, store.page + 1, store.marks); }
    if (e.key === "PageUp") { e.preventDefault(); openDoc(store.open.id, store.page - 1, store.marks); }
  });
}
