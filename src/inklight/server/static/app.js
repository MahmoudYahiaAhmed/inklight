// Inklight workspace. Vanilla JS; every piece of document text is set via textContent (never innerHTML).
"use strict";

const $ = (s) => document.querySelector(s);
const state = { docs: [], selected: new Set(), viewer: { doc: null, pages: [], page: 1, highlight: null }, job: null };

function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (v !== null && v !== undefined && v !== false) el.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat()) if (c !== null && c !== undefined && c !== false) el.append(c instanceof Node ? c : String(c));
  return el;
}

// Optional server token (INKLIGHT_SERVER_TOKEN): open the workspace at /#token=… — the fragment never reaches logs.
const TOKEN = new URLSearchParams(location.hash.slice(1)).get("token") || "";
const withToken = (url) => (TOKEN ? `${url}${url.includes("?") ? "&" : "?"}token=${encodeURIComponent(TOKEN)}` : url);

async function api(path, opts = {}) {
  const headers = { "X-Inklight": "1", ...(TOKEN ? { "X-Inklight-Token": TOKEN } : {}), ...(opts.headers || {}) };
  if (opts.json !== undefined) { headers["Content-Type"] = "application/json"; opts.body = JSON.stringify(opts.json); }
  const res = await fetch(path, { ...opts, headers });
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch (_) { /* not JSON */ }
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return res.headers.get("content-type")?.includes("json") ? res.json() : res;
}

const fmt = (v) => (typeof v === "number" ? v.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : v ?? "—");

// ------------------------------------------------------------------ library

async function loadDocs() {
  state.docs = await api("/api/documents");
  renderDocs();
  renderScope();
}

function renderDocs() {
  const q = $("#filter").value.toLowerCase();
  const list = $("#docs");
  list.replaceChildren();
  const docs = state.docs.filter((d) => !q || d.name.toLowerCase().includes(q) || d.doc_type.includes(q));
  if (!docs.length) list.append(h("li", { class: "muted", style: "padding:10px" }, state.docs.length ? "No match." : "No documents yet."));
  for (const d of docs) {
    const conf = d.mean_conf == null ? "" : ` · OCR ${(d.mean_conf * 100).toFixed(0)}%`;
    const li = h("li", { class: `doc ${state.selected.has(d.id) ? "selected" : ""} ${state.viewer.doc?.id === d.id ? "active" : ""}`,
      title: "Click to preview · Ctrl/⌘-click to add to the agent's scope" },
      h("div", { class: "doc-name" }, d.name),
      h("div", { class: "doc-meta" }, h("span", { class: `chip ${d.status === "failed" ? "failed" : d.doc_type}` }, d.status === "failed" ? "failed" : d.doc_type),
        `${d.pages} p${conf}`),
      h("button", { class: "doc-x", title: "Remove from library", "aria-label": `Remove ${d.name}`,
        onclick: (e) => { e.stopPropagation(); removeDoc(d); } }, "✕"));
    li.addEventListener("click", (e) => {
      if (e.ctrlKey || e.metaKey) { state.selected.has(d.id) ? state.selected.delete(d.id) : state.selected.add(d.id); renderDocs(); renderScope(); }
      else openDoc(d.id, 1);
    });
    list.append(li);
  }
}

function renderScope() {
  const n = state.selected.size;
  $("#scope-label").textContent = n ? `Scope: ${n} selected document${n > 1 ? "s" : ""} (Ctrl/⌘-click to change)` : `Scope: all ${state.docs.length} documents`;
}

async function removeDoc(d) {
  if (!confirm(`Remove “${d.name}” from the library?`)) return;
  await api(`/api/documents/${d.id}`, { method: "DELETE" });
  state.selected.delete(d.id);
  if (state.viewer.doc?.id === d.id) state.viewer.doc = null;
  await loadDocs();
}

async function upload(files) {
  if (!files.length) return;
  const status = $("#upload-status");
  status.replaceChildren(h("span", { class: "thinking" }, h("span", { class: "scan" }), `Reading ${files.length} file(s)…`));
  const form = new FormData();
  for (const f of files) form.append("files", f, f.name);
  try {
    const res = await api("/api/documents", { method: "POST", body: form });
    const failed = res.failed.map((f) => `${f.file}: ${f.error}`);
    status.textContent = `✓ ${res.documents.length} ready in ${res.seconds}s` + (failed.length ? ` · ✗ ${failed.join("; ")}` : "");
    await loadDocs();
    if (res.documents[0]) openDoc(res.documents[0].id, 1);
  } catch (e) { status.textContent = `✗ ${e.message}`; }
}

// ------------------------------------------------------------------ viewer

async function openDoc(id, page, highlight = null) {
  if (state.viewer.doc?.id !== id) {
    const data = await api(`/api/documents/${id}`);
    state.viewer.doc = data.document;
    state.viewer.pages = data.pages;
  }
  state.viewer.page = Math.max(1, Math.min(page, state.viewer.pages.length || 1));
  state.viewer.highlight = highlight;
  $("#viewer").classList.add("open");
  renderDocs();
  renderPage();
  reviewLabel();
}

function renderPage() {
  const { doc, pages, page, highlight } = state.viewer;
  if (!doc) return;
  const p = pages.find((x) => x.number === page);
  $("#viewer-title").textContent = doc.name;
  $("#viewer-meta").textContent = `${doc.doc_type} · ${doc.pages} page(s) · ${p ? p.source : ""}${doc.mean_conf != null ? ` · OCR ${(doc.mean_conf * 100).toFixed(1)}%` : ""}`;
  $("#page-label").textContent = `${page} / ${pages.length}`;
  $("#page-text").textContent = p ? p.markdown : "";
  const img = $("#page-img");
  const overlay = $("#overlay");
  overlay.replaceChildren();
  if (!p || !p.width) { $("#page").classList.add("hidden"); $("#page-text").classList.remove("hidden"); return; }
  $("#page").classList.toggle("hidden", !$("#page-text").classList.contains("hidden"));
  img.onerror = () => { $("#page").classList.add("hidden"); $("#page-text").classList.remove("hidden"); };
  img.src = withToken(`/api/documents/${doc.id}/pages/${page}/image`);
  const add = (bbox, cls, title) => {
    const [x0, y0, x1, y1] = bbox;
    overlay.append(h("div", { class: `box ${cls}`, title,
      style: `left:${(x0 / p.width) * 100}%;top:${(y0 / p.height) * 100}%;width:${((x1 - x0) / p.width) * 100}%;height:${((y1 - y0) / p.height) * 100}%` }));
  };
  for (const b of p.blocks) if (b.bbox) add(b.bbox, "", `${b.label}${b.conf != null ? ` · ${(b.conf * 100).toFixed(0)}%` : ""}`);
  if (highlight) {
    add(highlight, "hit", "evidence");
    img.onload = () => {
      const wrap = $("#page-wrap");
      wrap.scrollTop = Math.max(0, (highlight[1] / p.height) * img.clientHeight - 120);
    };
  }
}

// ------------------------------------------------------------------ agent

const EXAMPLES = [
  "Read all these invoices and create a CSV of vendor, date, tax, and total",
  "Find every contract that expires within 90 days",
  "Find all invoices above $5,000",
  "Compare these reports and explain the differences",
  "Extract all customer names and flag inconsistent records",
  "What is the sum of all invoice totals?",
  "Find the paragraph about termination notice",
];

function renderExamples() {
  $("#examples").replaceChildren(...EXAMPLES.map((t) => h("button", { class: "example", type: "button", onclick: () => { $("#ask-input").value = t; $("#ask-input").focus(); } }, t)));
}

function sourceRow(s, i) {
  const conf = s.ocr_conf != null ? ` · OCR ${(s.ocr_conf * 100).toFixed(0)}%` : "";
  return h("div", { class: "source", onclick: () => openDoc(s.doc_id, s.page, s.bbox) },
    h("b", {}, `[${i + 1}] ${s.name} p.${s.page}${conf}`),
    h("span", {}, `“${s.excerpt.replace(/\s+/g, " ").slice(0, 220)}${s.excerpt.length > 220 ? "…" : ""}”`));
}

function recordsTable(records) {
  if (!records.length) return null;
  const cols = [...new Set(records.flatMap((r) => Object.keys(r.fields)))];
  return h("table", { class: "grid" },
    h("thead", {}, h("tr", {}, h("th", {}, "document"), ...cols.map((c) => h("th", {}, c)))),
    h("tbody", {}, ...records.map((r) => h("tr", {}, h("td", {}, r.name), ...cols.map((c) => {
      const v = r.fields[c];
      if (!v || v.value == null) return h("td", { class: "none" }, "—");
      const cls = `cell ${v.confidence < 0.7 || v.warning ? "low" : ""}`;
      const title = `${v.method} · confidence ${(v.confidence * 100).toFixed(0)}%${v.warning ? ` · ${v.warning}` : ""}`;
      return h("td", { class: cls, title, onclick: () => v.source && openDoc(v.source.doc_id, v.source.page, v.source.bbox) },
        fmt(v.value), v.warning ? " ⚠" : "");
    })))));
}

function csvDownload(records) {
  const cols = [...new Set(records.flatMap((r) => Object.keys(r.fields)))];
  const esc = (v) => { let s = v == null ? "" : String(v); if (/^[=+\-@|\t\r]/.test(s)) s = "'" + s; return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s; };
  const rows = [["document", ...cols].map(esc).join(",")].concat(records.map((r) => [r.name, ...cols.map((c) => r.fields[c]?.value)].map(esc).join(",")));
  const url = URL.createObjectURL(new Blob([rows.join("\n")], { type: "text/csv" }));
  h("a", { href: url, download: "inklight-export.csv" }).click();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

function confBar(label, value, title) {
  const pct = Math.round((value || 0) * 100);
  return h("span", { class: `conf ${pct < 50 ? "low" : ""}`, title }, label, " ", h("span", { class: "bar" }, h("i", { style: `width:${pct}%` })), `${pct}%`);
}

function resultCard(r) {
  const table = r.records.length && ["extract", "filter", "aggregate", "inconsistencies", "compare"].includes(r.intent) ? recordsTable(r.records) : null;
  const parts = r.answer.split("\n\n");
  if (parts[0].startsWith("Understood as")) parts.shift();  // shown as its own block below
  const answer = table && ["extract", "filter", "aggregate"].includes(r.intent) ? parts[0] || "" : parts.join("\n\n");
  const understood = (r.interpretation || []).length || (r.not_understood || []).length
    ? h("div", { class: "understood" },
        h("div", {}, h("b", {}, "Understood as: "), (r.interpretation || []).join(" · ")),
        (r.not_understood || []).length ? h("div", { class: "not-applied" }, h("b", {}, "Not applied: "), r.not_understood.map((x) => `“${x}”`).join(", ")) : null)
    : null;
  return h("article", { class: "card" },
    h("div", { class: "card-head" },
      h("div", { class: "req" }, r.request),
      h("span", { class: `state ${r.state}` }, r.state), h("span", {}, r.intent),
      confBar("understood", r.interpretation_confidence, "How sure the agent is that it read your request correctly"),
      confBar("evidence", r.evidence_confidence, "How well the documents support the result (OCR, labels, cross-checks)"),
      h("span", {}, `${Math.round(r.duration_ms)} ms`), h("span", { title: "Which models were used" }, r.brain)),
    understood,
    h("div", { class: "answer" }, answer),
    table,
    r.records.length ? h("div", { class: "actions" }, h("button", { class: "ghost small", type: "button", onclick: () => csvDownload(r.records) }, "Download CSV")) : null,
    r.files_written.length ? h("div", { class: "files muted" }, "Saved: ", ...r.files_written.map((f) => { const n = f.split(/[\\/]/).pop(); return h("a", { href: withToken(`/api/outputs/${encodeURIComponent(n)}`) }, n); })) : null,
    r.sources.length ? h("div", { class: "sources" }, ...r.sources.map(sourceRow)) : null,
    r.warnings.length ? h("div", { class: "warnings" }, ...r.warnings.map((w) => h("div", { class: "warning" }, w))) : null,
    h("details", { class: "trace" }, h("summary", {}, `Execution trace · ${r.trace.length} steps`),
      ...r.trace.map((t) => h("div", { class: "trace-row" }, String(t.index + 1), t.tool,
        h("span", { class: t.status === "ok" ? "ok-t" : t.status === "denied" ? "warn-t" : "bad-t" }, t.status),
        `${Math.round(t.duration_ms)}ms`, t.error || t.summary))));
}

async function runAsk(e) {
  e.preventDefault();
  const request = $("#ask-input").value.trim();
  if (!request) return;
  const out = $("#results");
  const job = Math.random().toString(36).slice(2, 12);
  state.job = job;
  const pending = h("div", { class: "card thinking" }, h("span", { class: "scan" }), "Planning, reading and verifying…");
  out.prepend(pending);
  $("#ask-btn").disabled = true; $("#cancel").classList.remove("hidden");
  try {
    const r = await api("/api/ask", { method: "POST", json: { request, job_id: job, allow_write: $("#allow-write").checked, doc_ids: state.selected.size ? [...state.selected] : null } });
    pending.replaceWith(resultCard(r));
    const first = r.sources[0];
    if (first) openDoc(first.doc_id, first.page, first.bbox);
  } catch (err) {
    pending.replaceWith(h("div", { class: "card" }, h("div", { class: "warning" }, err.message)));
  } finally {
    $("#ask-btn").disabled = false; $("#cancel").classList.add("hidden"); state.job = null;
  }
}

async function runExtract(e) {
  e.preventDefault();
  const fields = $("#extract-fields").value.split(",").map((s) => s.trim().toLowerCase().replace(/\s+/g, "_")).filter(Boolean);
  const ids = state.selected.size ? [...state.selected] : state.docs.filter((d) => d.status === "ready").map((d) => d.id);
  const out = $("#extract-out");
  if (!ids.length) { out.replaceChildren(h("div", { class: "card muted" }, "Add documents first.")); return; }
  out.replaceChildren(h("div", { class: "card thinking" }, h("span", { class: "scan" }), "Extracting…"));
  try {
    const { records } = await api("/api/extract", { method: "POST", json: { doc_ids: ids, fields } });
    out.replaceChildren(h("article", { class: "card" }, h("div", { class: "muted" }, `${records.length} document(s) · click a value to see where it came from · ⚠ = check manually`),
      recordsTable(records), h("div", { class: "actions" }, h("button", { class: "ghost small", type: "button", onclick: () => csvDownload(records) }, "Download CSV"))));
  } catch (err) { out.replaceChildren(h("div", { class: "card warning" }, err.message)); }
}

async function runSearch(e) {
  e.preventDefault();
  const q = $("#search-input").value.trim();
  if (!q) return;
  const hits = await api(`/api/search?q=${encodeURIComponent(q)}&k=15`);
  $("#search-out").replaceChildren(hits.length ? h("article", { class: "card" }, h("div", { class: "muted" }, `${hits.length} passages · ${hits[0].method}`),
    h("div", { class: "sources" }, ...hits.map((x, i) => sourceRow(x.source, i)))) : h("div", { class: "card muted" }, "No matches."));
}

async function loadHistory() {
  const rows = await api("/api/tasks");
  $("#history-out").replaceChildren(h("article", { class: "card" }, rows.length ? h("table", { class: "grid" },
    h("thead", {}, h("tr", {}, ...["when", "intent", "state", "ms", "request"].map((c) => h("th", {}, c)))),
    h("tbody", {}, ...rows.map((r) => h("tr", { style: "cursor:pointer", onclick: async () => {
      const full = await api(`/api/tasks/${r.id}`);
      document.querySelector('[data-tab="ask"]').click();
      $("#results").prepend(resultCard(full));
    } }, h("td", {}, r.created_at.slice(0, 19).replace("T", " ")), h("td", {}, r.intent), h("td", {}, r.state), h("td", {}, Math.round(r.duration_ms)), h("td", {}, r.request))))) : h("div", { class: "muted" }, "No tasks yet.")));
}

// ------------------------------------------------------------------ review
// The prediction (value, OCR text, confidence, warning, source box) is frozen on the server when a review opens.
// The reviewer decides every field; the decision is stored next to the prediction, never over it.

const review = { current: null, activeMs: 0, since: null };

function storageGet(key) { try { return localStorage.getItem(key); } catch (_) { return null; } }
function storageSet(key, value) { try { localStorage.setItem(key, value); } catch (_) { /* private mode */ } }

// Active time: counted only while this page is visible and focused, kept per review across reloads.
function clockStart() {
  if (!review.current || review.since !== null || document.hidden || !document.hasFocus()) return;
  review.since = performance.now();
}
function clockStop() {
  if (review.since === null) return;
  review.activeMs += performance.now() - review.since;
  review.since = null;
  if (review.current) storageSet(`inklight-review-ms-${review.current.id}`, String(Math.round(review.activeMs)));
}
function activeSeconds() { clockStop(); clockStart(); return Math.round(review.activeMs) / 1000; }

const reviewer = () => $("#review-name").value.trim();

function reviewLabel() {
  const d = state.viewer.doc;
  $("#review-doc-label").textContent = d ? `Document: ${d.name}` : "Open a document in the viewer, then start its review.";
}

async function startReview(e) {
  e.preventDefault();
  const d = state.viewer.doc;
  if (!d) { $("#review-out").replaceChildren(h("div", { class: "card warning" }, "Open a document in the viewer first.")); return; }
  if (!reviewer()) { $("#review-name").focus(); return; }
  storageSet("inklight-reviewer", reviewer());
  try {
    const r = await api("/api/reviews", { method: "POST", json: { doc_id: d.id, reviewer: reviewer(), mode: $("#review-mode").value, cohort: $("#review-cohort").value.trim() || null } });
    showReview(r);
    loadQueue();
  } catch (err) { $("#review-out").replaceChildren(h("div", { class: "card warning" }, err.message)); }
}

function showReview(r) {
  clockStop();
  review.current = r;
  review.activeMs = Number(storageGet(`inklight-review-ms-${r.id}`) || 0);
  review.since = null;
  clockStart();
  renderReview();
}

async function decide(field, action, value) {
  try {
    const r = await api(`/api/reviews/${review.current.id}/decide`, { method: "POST", json: { field, action, value: value ?? null, reviewer: reviewer() } });
    review.current = r;
    renderReview();
  } catch (err) { renderReview(err.message); }
}

async function approveReview() {
  try {
    const r = await api(`/api/reviews/${review.current.id}/approve`, { method: "POST", json: { reviewer: reviewer(), active_seconds: activeSeconds() } });
    clockStop();
    review.current = r;
    renderReview();
    loadQueue();
  } catch (err) { renderReview(err.message); }
}

function predictionCell(f, r) {
  if (r.mode === "manual" && r.status === "open") return h("td", { class: "muted" }, "hidden (manual entry)");
  if (f.predicted == null) return h("td", { class: "none" }, "—");
  const low = f.flagged;
  const title = `${f.method || ""} · confidence ${f.confidence == null ? "–" : Math.round(f.confidence * 100) + "%"}${f.warning ? ` · ${f.warning}` : ""}`;
  return h("td", { class: `cell ${low ? "low" : ""}`, title, onclick: () => f.source && openDoc(r.doc_id, f.source.page, f.source.bbox) },
    fmt(f.predicted), low ? " ⚠" : "", f.raw ? h("div", { class: "muted" }, `OCR: “${f.raw}”`) : null,
    f.warning ? h("div", { class: "warning" }, f.warning) : null);
}

function decisionCell(f, r) {
  if (r.status !== "open") return h("td", {}, f.action === "absent" ? "absent" : fmt(f.final), h("div", { class: "muted" }, f.action || ""));
  const input = h("input", { value: f.action && f.action !== "absent" ? String(f.entered ?? f.final ?? "") : "", placeholder: r.mode === "manual" ? "type the value" : "correct value", "aria-label": `Value for ${f.field}` });
  const save = () => decide(f.field, r.mode === "manual" ? "entered" : "corrected", input.value);
  input.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); save(); } });
  return h("td", {}, input,
    h("div", { class: "actions" },
      r.mode === "review" && f.predicted != null ? h("button", { class: "ghost small", type: "button", onclick: () => decide(f.field, "accepted") }, "Accept") : null,
      h("button", { class: "ghost small", type: "button", onclick: save }, r.mode === "manual" ? "Save" : "Save correction"),
      h("button", { class: "ghost small", type: "button", onclick: () => decide(f.field, "absent") }, "Absent")),
    f.action ? h("div", { class: "muted" }, `✓ ${f.action}${f.action === "absent" ? "" : `: ${fmt(f.final)}`}${f.entered && f.entered !== String(f.final) ? ` (typed “${f.entered}”)` : ""}`) : null);
}

function renderReview(error) {
  const r = review.current;
  if (!r) { $("#review-out").replaceChildren(); return; }
  const undecided = r.fields.filter((f) => !f.action).length;
  $("#review-out").replaceChildren(h("article", { class: "card" },
    h("div", { class: "card-head" }, h("div", { class: "req" }, r.doc_name), h("span", { class: `state ${r.status === "approved" ? "succeeded" : "partial"}` }, r.status),
      h("span", {}, r.mode), r.cohort ? h("span", {}, r.cohort) : null, h("span", {}, `review ${r.id}`)),
    error ? h("div", { class: "warning" }, error) : null,
    h("div", { class: "muted" }, r.mode === "manual" ? "Type each value from the document, or mark it absent." : "Compare each prediction with the document (click it to see where it came from). ⚠ = flagged for review."),
    h("table", { class: "grid" },
      h("thead", {}, h("tr", {}, ...["field", "prediction", "decision"].map((c) => h("th", {}, c)))),
      h("tbody", {}, ...r.fields.map((f) => h("tr", {}, h("td", {}, f.field), predictionCell(f, r), decisionCell(f, r))))),
    r.status === "open"
      ? h("div", { class: "actions" }, h("button", { class: "primary", type: "button", disabled: undecided > 0, onclick: approveReview }, undecided ? `Decide ${undecided} more field(s) to approve` : "Approve"))
      : h("div", {},
          h("div", { class: "muted" }, `Approved by ${r.approved_by} · ${r.approved_at.slice(0, 19).replace("T", " ")} · active ${r.active_seconds ?? "–"} s`),
          reopenForm(r))));
}

// Reopening an approved review needs a reason; the history keeps both approvals and the reason.
function reopenForm(r) {
  const reason = h("input", { placeholder: "Why reopen? (required)", maxlength: "500", "aria-label": "Reason for reopening" });
  return h("div", { class: "actions" }, reason,
    h("button", { class: "ghost small", type: "button", onclick: async () => {
      if (!reviewer()) { $("#review-name").focus(); return; }
      if (!reason.value.trim()) { reason.focus(); return; }
      try {
        const reopened = await api(`/api/reviews/${r.id}/reopen`, { method: "POST", json: { reviewer: reviewer(), reason: reason.value.trim() } });
        showReview(reopened);
        loadQueue();
      } catch (err) { renderReview(err.message); }
    } }, "Reopen"));
}

async function loadQueue() {
  try {
    const [open, approved] = await Promise.all([api("/api/reviews?status=open"), api("/api/reviews?status=approved")]);
    const row = (r, detail) => h("div", { class: "source", onclick: async () => { showReview(await api(`/api/reviews/${r.id}`)); openDoc(r.doc_id, 1); } },
      h("b", {}, r.doc_name), h("span", {}, `${r.mode} · ${r.cohort || "no cohort"} · ${detail}`));
    $("#review-queue").replaceChildren(
      h("article", { class: "card" }, h("div", { class: "muted" }, `${open.length} open review(s)`),
        ...open.map((r) => row(r, `opened by ${r.opened_by} · ${r.fields.filter((f) => !f.action).length} undecided`))),
      h("article", { class: "card" }, h("div", { class: "muted" }, `${approved.length} approved review(s) — open one to reopen it`),
        ...approved.slice(-20).reverse().map((r) => row(r, `approved by ${r.approved_by} · ${r.approved_at.slice(0, 16).replace("T", " ")}`))));
  } catch (err) { $("#review-queue").replaceChildren(h("div", { class: "card warning" }, err.message)); }
}

async function exportReviews() {
  if (!reviewer()) { $("#review-name").focus(); return; }
  try {
    const res = await api("/api/reviews/export", { method: "POST", json: { actor: reviewer(), format: "csv", cohort: $("#review-cohort").value.trim() || null } });
    const url = URL.createObjectURL(await res.blob());
    h("a", { href: url, download: "inklight-reviews.csv" }).click();
    setTimeout(() => URL.revokeObjectURL(url), 2000);
  } catch (err) { $("#review-out").replaceChildren(h("div", { class: "card warning" }, err.message)); }
}

// ------------------------------------------------------------------ settings

async function loadStatus() {
  const s = await api("/api/status");
  const loaded = Object.entries(s.models).filter(([k, v]) => k !== "remote" && v.installed).map(([k, v]) => `${k} ${v.params}`);
  $("#brain-pill").textContent = s.brain === "rules" || !loaded.length ? "rules · offline" : loaded.join(" + ");
  $("#brain-pill").title = `Brain mode: ${s.brain}`;
  $("#set-brain").value = s.brain;
  $("#set-writer").checked = s.use_writer;
  $("#set-models").replaceChildren(...Object.entries(s.models).filter(([k]) => k !== "remote").map(([k, v]) =>
    h("div", {}, `${v.installed ? "✓" : "✗"} ${k} (${v.params}) — ${v.repo}${v.installed ? "" : " · run `inklight models pull`"}`)),
    h("div", {}, `Remote model: ${s.models.remote.configured ? `configured (${s.models.remote.used_for})` : "off — nothing leaves this machine"}`));
  $("#set-info").replaceChildren(
    h("div", {}, `OCR: Indra · ${s.ocr.dpi} dpi · mode ${s.ocr.mode}`),
    h("div", {}, `Limits: ${s.limits.max_file_mb} MB/file · ${s.limits.max_pages} pages · ${s.limits.max_steps} steps · ${s.limits.task_timeout_s}s/task`),
    h("div", {}, `Privacy: text stored locally = ${s.privacy.store_text}; document text in logs = ${s.privacy.log_document_text}`),
    h("div", {}, `Outputs: ${s.outputs}`), h("div", {}, `Library: ${s.stats.documents} docs · ${s.stats.pages} pages · ${s.stats.chunks} chunks · v${s.version}`));
}

// ------------------------------------------------------------------ wiring

function wire() {
  document.querySelectorAll(".tab").forEach((t) => t.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((x) => x.classList.toggle("active", x === t));
    document.querySelectorAll(".panel").forEach((p) => p.classList.toggle("active", p.id === `panel-${t.dataset.tab}`));
    if (t.dataset.tab === "history") loadHistory();
    if (t.dataset.tab === "review") { reviewLabel(); loadQueue(); }
  }));
  $("#review-name").value = storageGet("inklight-reviewer") || "";
  $("#review-form").addEventListener("submit", startReview);
  $("#review-export").addEventListener("click", exportReviews);
  document.addEventListener("visibilitychange", () => (document.hidden ? clockStop() : clockStart()));
  window.addEventListener("blur", clockStop);
  window.addEventListener("focus", clockStart);
  window.addEventListener("beforeunload", clockStop);
  const drop = $("#drop");
  drop.addEventListener("dragover", (e) => { e.preventDefault(); drop.classList.add("over"); });
  drop.addEventListener("dragleave", () => drop.classList.remove("over"));
  drop.addEventListener("drop", (e) => { e.preventDefault(); drop.classList.remove("over"); upload([...e.dataTransfer.files]); });
  drop.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") $("#file").click(); });
  $("#file").addEventListener("change", (e) => { upload([...e.target.files]); e.target.value = ""; });
  $("#filter").addEventListener("input", renderDocs);
  $("#ask-form").addEventListener("submit", runAsk);
  $("#ask-input").addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("#ask-form").requestSubmit(); } });
  $("#cancel").addEventListener("click", () => state.job && api(`/api/jobs/${state.job}/cancel`, { method: "POST" }));
  $("#extract-form").addEventListener("submit", runExtract);
  $("#search-form").addEventListener("submit", runSearch);
  $("#prev-page").addEventListener("click", () => state.viewer.doc && openDoc(state.viewer.doc.id, state.viewer.page - 1));
  $("#next-page").addEventListener("click", () => state.viewer.doc && openDoc(state.viewer.doc.id, state.viewer.page + 1));
  $("#toggle-text").addEventListener("click", () => { $("#page-text").classList.toggle("hidden"); $("#page").classList.toggle("hidden"); });
  $("#page").addEventListener("dblclick", () => $("#page").classList.toggle("show-blocks"));
  $("#close-viewer").addEventListener("click", () => $("#viewer").classList.remove("open"));
  $("#open-settings").addEventListener("click", () => { loadStatus(); $("#settings").showModal(); });
  $("#save-settings").addEventListener("click", async (e) => {
    e.preventDefault();
    await api("/api/settings", { method: "POST", json: { brain: $("#set-brain").value, use_writer: $("#set-writer").checked } });
    $("#settings").close(); loadStatus();
  });
}

wire();
renderExamples();
loadDocs().catch((e) => { $("#upload-status").textContent = `✗ ${e.message}`; });
loadStatus().catch(() => {});
