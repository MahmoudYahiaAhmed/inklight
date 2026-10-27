// The library (documents, selection) and imports. An import's progress is what the server reports: the bytes sent,
// then for each file whether it waits, is being read (with the page the OCR has finished, once it says so), is being
// structured, or has ended. Nothing is estimated; a stage the server does not measure is shown as running, not as a
// percentage.

import { $, announce, api, changed, errorBox, fill, h, onChange, plural, store, uploadWithProgress, withToken } from "./dom.js";
import { closeDoc, openDoc, processingTarget, showProcessing, stopProcessing } from "./viewer.js";

const TERMINAL = new Set(["completed", "partial", "failed", "cancelled"]);
const batch = { upload: null, job: null, source: null, dismissed: false };

export async function loadDocs() {
  store.docs = await api("/api/documents");
  for (const id of [...store.selected]) if (!store.docs.some((d) => d.id === id)) store.selected.delete(id);
  renderDocs();
  changed("docs");
}

export function renderDocs() {
  const q = $("#filter").value.trim().toLowerCase();
  const list = $("#docs");
  const docs = store.docs.filter((d) => !q || d.name.toLowerCase().includes(q));
  list.replaceChildren(...(docs.length ? docs.map(docItem)
    : [h("li", { class: "empty-lib" }, store.docs.length ? "No document matches the filter." : "No documents yet. Add some above.")]));
  renderSelection();
}

function docItem(d) {
  const failed = d.status === "failed";
  const pending = d.status === "pending";
  const pages = plural(d.pages, "page");
  const box = h("input", { type: "checkbox", "aria-label": `Select ${d.name}`, checked: store.selected.has(d.id) || null,
    onchange: (e) => { e.target.checked ? store.selected.add(d.id) : store.selected.delete(d.id); renderSelection(); changed("selection"); } });
  return h("li", { class: `doc ${store.open?.id === d.id ? "open" : ""}` },
    box,
    h("button", { class: "doc-open", type: "button", "aria-current": store.open?.id === d.id ? "true" : null,
      onclick: () => { openDoc(d.id, 1); showView("viewer"); } },
      h("span", { class: "doc-name", dir: "auto", title: d.name }, d.name),
      h("span", { class: "doc-meta", title: failed ? d.error || "" : null },
        failed ? h("span", { class: "badge failed" }, "not read") : pending ? h("span", { class: "badge" }, "being read") : null,
        failed ? h("span", { class: "clamp" }, d.error || "") : pending ? "" : `${pages}${d.doc_type && d.doc_type !== "unknown" ? ` · ${d.doc_type}` : ""}`)),
    h("button", { class: "btn quiet icon doc-x", type: "button", title: "Remove from the library", "aria-label": `Remove ${d.name}`,
      onclick: () => removeDoc(d) }, "×"));
}

function renderSelection() {
  const n = store.selected.size;
  const open = store.open ? store.open.name : null;
  fill($("#selection"),
    n ? h("span", {}, `${plural(n, "document")} selected`) : h("span", {}, open ? "Open: " : "Nothing selected", open ? h("b", { dir: "auto" }, open) : null),
    n ? h("button", { class: "btn quiet small", type: "button", onclick: () => { store.selected.clear(); renderDocs(); changed("selection"); } }, "Clear") : null);
}

async function removeDoc(d) {
  if (!confirm(`Remove “${d.name}” from the library? A file you uploaded here is deleted; a file elsewhere is not.`)) return;
  await api(`/api/documents/${d.id}`, { method: "DELETE" });
  store.selected.delete(d.id);
  closeDoc(d.id);
  await loadDocs();
  announce(`${d.name} removed`);
}

// ------------------------------------------------------------------ import

export async function upload(files) {
  files = [...files];
  if (!files.length) return;
  closeFollow();
  batch.dismissed = false;
  batch.job = null;
  batch.upload = { names: files.map((f) => f.name), loaded: 0, total: files.reduce((s, f) => s + f.size, 0) };
  renderBatch();
  announce(`Uploading ${plural(files.length, "file")}`);
  const form = new FormData();
  for (const f of files) form.append("files", f, f.name);
  try {
    const res = await uploadWithProgress(withToken("/api/documents?background=true"), form, (loaded, total) => {
      batch.upload = { ...batch.upload, loaded, total };
      renderBatch();
    });
    batch.upload = null;
    follow(res.job, { show: true });
  } catch (err) {
    batch.upload = null;
    batch.job = null;
    renderBatch(err.message);
  }
}

export function follow(job, { show = false } = {}) {
  batch.job = job;
  renderBatch();
  if (TERMINAL.has(job.state)) return;
  closeFollow();
  const source = new EventSource(withToken(`/api/jobs/${job.id}/events`));
  batch.source = source;
  let showing = show;
  source.onmessage = (e) => {
    const prev = batch.job;
    const next = JSON.parse(e.data);
    batch.job = next;
    renderBatch();
    reportChanges(prev, next);
    const active = next.active;
    if (showing && active !== null && active !== undefined) showFile(next, active);
    if (TERMINAL.has(next.state)) { closeFollow(); finished(next, showing); showing = false; }
  };
  source.onerror = () => {
    // The browser reconnects by itself; if the job has ended meanwhile, read its final state once.
    if (source.readyState === EventSource.CLOSED) api(`/api/jobs/${job.id}`).then((j) => { batch.job = j; renderBatch(); if (TERMINAL.has(j.state)) finished(j, showing); }).catch(() => {});
  };
}

function closeFollow() {
  if (batch.source) { batch.source.close(); batch.source = null; }
}

function reportChanges(prev, next) {
  if (!prev) return;
  next.files.forEach((f, i) => {
    const before = prev.files[i]?.state;
    if (before === f.state) return;
    if (f.state === "done") announce(`${f.name} read`);
    if (f.state === "failed") announce(`${f.name} could not be read: ${f.error}`);
    if (f.state === "structuring") announce(`${f.name}: finding layout and tables`);
  });
  if (prev.state !== next.state && TERMINAL.has(next.state)) announce(summary(next));
}

function showFile(job, index) {
  const target = processingTarget();
  // Follow the active file only while the viewer shows this import (the user may have opened something else).
  if (store.open && !target) return;
  const f = job.files[index];
  showProcessing(job.id, index, { name: f.name, stage: stageText(f, job.kind), active: ["reading", "structuring"].includes(f.state),
    page: f.pages ? `page ${f.page} of ${f.pages}` : null });
}

async function finished(job, opened) {
  await loadDocs();
  const target = processingTarget();
  const done = job.files.filter((f) => f.state === "done" && f.doc_id);
  if (target && target.jobId === job.id) {
    const f = job.files[target.index];
    const id = f?.doc_id || done[done.length - 1]?.doc_id;
    if (id) openDoc(id, 1, [], { fresh: true });
    else stopProcessing();
  } else if (opened && !store.open && done.length) openDoc(done[0].doc_id, 1, [], { fresh: true });
  if (job.kind === "structure" && store.open && done.some((f) => f.doc_id === store.open.id)) {
    changed("restructured");
  }
}

function stageText(f, kind) {
  if (f.state === "queued") return "Waiting to be read";
  if (f.state === "reading") return f.pages ? `Reading text (OCR): page ${f.page} of ${f.pages} done` : "Reading text (OCR)";
  if (f.state === "structuring") return "Finding layout and tables";
  if (f.state === "done") return kind === "structure" ? "Read again with its structure" : `Read · ${plural(f.pages || 0, "page")}`;
  if (f.state === "failed") return `Not read: ${f.error || "unknown error"}`;
  if (f.state === "cancelled") return "Not read: the import was stopped";
  return f.state;
}

function summary(job) {
  const n = (s) => job.files.filter((f) => f.state === s).length;
  const total = job.files.length;
  if (job.state === "completed") return job.kind === "structure" ? "Structure added" : `${plural(total, "document")} read`;
  if (job.state === "partial") return `${n("done")} of ${total} read · ${n("failed")} could not be read`;
  if (job.state === "cancelled") return `Stopped · ${n("done")} read, ${n("cancelled")} not read`;
  if (job.state === "failed") return job.result?.error ? `Import failed: ${job.result.error}` : `None of ${plural(total, "file")} could be read`;
  return "";
}

function renderBatch(error) {
  const el = $("#batch");
  const { upload: up, job } = batch;
  if (batch.dismissed || (!up && !job && !error)) { el.classList.add("hidden"); return; }
  el.classList.remove("hidden");
  if (error) {
    fill(el, errorBox(`Upload failed: ${error}. Nothing was imported; your files are unchanged.`),
      h("div", { class: "next" }, h("button", { class: "btn quiet small", type: "button", onclick: dismiss }, "Close")));
    return;
  }
  if (up) {
    const pct = up.total ? Math.round((100 * up.loaded) / up.total) : 0;
    fill(el,
      h("div", { class: "batch-head" }, h("b", {}, `Uploading ${plural(up.names.length, "file")}`), h("span", { class: "grow" }), `${pct}%`),
      h("div", { class: "meter", role: "progressbar", "aria-label": "Upload", "aria-valuenow": pct, "aria-valuemin": 0, "aria-valuemax": 100 },
        h("i", { style: `width:${pct}%` })));
    return;
  }
  const running = !TERMINAL.has(job.state);
  const read = job.files.filter((f) => ["done", "failed", "cancelled"].includes(f.state)).length;
  const head = running
    ? `${job.kind === "structure" ? "Adding structure" : "Importing"} · ${read} of ${job.files.length} done`
    : summary(job);
  // An import that ended says how it ended; "done" is neutral: reading a file is not checking its values.
  const ended = { completed: ["raw", "done"], partial: ["partial", "partly done"], cancelled: ["cancelled", "stopped"], failed: ["failed", "failed"] }[job.state];
  fill(el,
    h("div", { class: "batch-head" },
      ended ? h("span", { class: `label ${ended[0]}` }, ended[1]) : h("span", { class: "spinner", "aria-hidden": "true" }),
      h("b", { class: "grow" }, head),
      !running ? h("button", { class: "btn quiet small", type: "button", onclick: dismiss, title: "Hide this summary" }, "Close") : null),
    running ? h("div", { class: "batch-actions" },
      job.cancel_requested ? h("span", { class: "muted" }, "Stopping after the current file…")
        : h("button", { class: "btn small", type: "button", title: "Files not yet started are not read. The file being read is finished.",
            onclick: () => api(`/api/jobs/${job.id}/cancel`, { method: "POST" }).then(() => announce("Stopping after the current file")) }, "Stop after the current file")) : null,
    ...(running ? downloadRows() : []),
    ...job.files.map((f, i) => fileRow(job, f, i)));
  if (running) watchDownloads();
}

// Models are fetched the first time they are needed; while an import runs, the bytes the server has received are
// shown (from /api/status), so a first read that waits for a download says so.
const MODEL_NAMES = { ocr: "OCR", layout: "layout", tables: "table structure", "tables-fast": "table structure" };
let downloads = [];
let poller = null;

function watchDownloads() {
  if (poller) return;
  poller = setInterval(async () => {
    if (!batch.job || TERMINAL.has(batch.job.state)) {
      clearInterval(poller); poller = null; downloads = []; return;
    }
    try {
      const s = await api("/api/status");
      const now = Object.entries(s.downloads || {}).filter(([, d]) => d.state === "downloading");
      if (now.length || downloads.length) { downloads = now; renderBatch(); }
    } catch (_) { /* the next tick tries again */ }
  }, 1500);
}

function downloadRows() {
  const mb = (n) => (n / 1e6).toFixed(0);
  return downloads.map(([key, d]) => {
    const pct = d.total ? Math.round((100 * d.done) / d.total) : 0;
    return h("div", { class: "file" }, h("span", { class: "dot active", "aria-hidden": "true" }),
      h("span", { class: "file-name" }, `Downloading the ${MODEL_NAMES[key] || key} models (first use)`),
      h("span", { class: "file-state" }, `${mb(d.done)} of ${mb(d.total)} MB`),
      h("div", { class: "meter", role: "progressbar", "aria-label": `Model download ${pct}%`, "aria-valuenow": pct, "aria-valuemin": 0, "aria-valuemax": 100 },
        h("i", { style: `width:${pct}%` })));
  });
}

function fileRow(job, f, i) {
  const active = ["reading", "structuring"].includes(f.state);
  const dot = f.state === "done" ? "done" : f.state === "failed" ? "failed" : f.state === "cancelled" ? "cancelled" : active ? "active" : "";
  const known = f.state === "reading" && f.pages;
  const pct = known ? Math.round((100 * f.page) / f.pages) : 0;
  return h("div", { class: "file" },
    h("span", { class: `dot ${dot}`, "aria-hidden": "true" }),
    h("button", { class: "doc-open file-name", type: "button", dir: "auto", title: active ? "Show it while it is read" : f.doc_id ? "Open" : f.name,
      onclick: () => { if (f.doc_id) openDoc(f.doc_id, 1); else if (active) { stopProcessing(); store.open = null; showFile(job, i); } showView("viewer"); } }, f.name),
    h("span", { class: `file-state ${f.state === "failed" ? "bad" : ""}` }, stageText(f, job.kind)),
    active ? h("div", { class: `meter ${known ? "" : "indeterminate"}`, role: "progressbar", "aria-label": `${f.name}: ${stageText(f, job.kind)}`,
      ...(known ? { "aria-valuenow": pct, "aria-valuemin": 0, "aria-valuemax": 100 } : {}) }, h("i", { style: known ? `width:${pct}%` : "" })) : null);
}

function dismiss() {
  batch.dismissed = true;  // closes the display only; a running job keeps going (Stop is the button that stops it)
  renderBatch();
}

export async function recoverJobs() {
  try {
    const jobs = await api("/api/jobs");
    const running = jobs.find((j) => !TERMINAL.has(j.state));
    if (running) { follow(running, { show: !store.open }); announce("An import is still running; showing its progress"); }
  } catch (_) { /* nothing to recover */ }
}

export function startStructure(docId) {
  return api(`/api/documents/${docId}/structure`, { method: "POST" }).then((res) => { batch.dismissed = false; follow(res.job); return res.job; });
}

// ------------------------------------------------------------------ views on a narrow screen

export function showView(name) {
  const app = $("#app");
  app.dataset.view = name;
  for (const b of document.querySelectorAll(".mobile-views button")) b.setAttribute("aria-pressed", String(b.dataset.view === name));
}

export function wireLibrary() {
  const drop = $("#drop");
  drop.addEventListener("click", () => $("#file").click());
  drop.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); $("#file").click(); } });
  for (const t of ["dragenter", "dragover"]) drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.add("over"); });
  for (const t of ["dragleave", "drop"]) drop.addEventListener(t, () => drop.classList.remove("over"));
  drop.addEventListener("drop", (e) => { e.preventDefault(); upload(e.dataTransfer.files); });
  $("#file").addEventListener("change", (e) => { upload(e.target.files); e.target.value = ""; });
  $("#filter").addEventListener("input", renderDocs);
  for (const b of document.querySelectorAll(".mobile-views button")) b.addEventListener("click", () => showView(b.dataset.view));
  onChange((what) => { if (what === "open") renderDocs(); });
}
