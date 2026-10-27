// Review and export. The prediction (value, OCR text, confidence, warning, source box) is frozen on the server when a
// review opens; the reviewer decides every field, and the decision is stored next to the prediction, never over it.
// Only approved reviews are exported as approved values; raw extraction is exported separately and says so.

import { announce, api, errorBox, fmt, h, storageGet, storageSet, store } from "./dom.js";
import { showView } from "./library.js";
import { exportButton, registerOp, renderOps, scopeBox } from "./ops.js";
import { openDoc } from "./viewer.js";

const review = { current: null, activeMs: 0, since: null, error: null, fields: "", queue: null };
window.addEventListener("inklight:review-fields", (e) => { review.fields = e.detail; review.current = null; });

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
// The name typed in this page, kept here too: with browser storage blocked it is the only copy.
let typedName = "";
const reviewer = () => (storageGet("inklight-reviewer") || typedName).trim();
function setReviewer(value) { typedName = value.trim(); storageSet("inklight-reviewer", typedName); }

// Every decision, approval and export records who made it, so the name is always on screen where it is used; a
// review opened from the list (or after a reload in another browser) has no name until one is typed here.
function reviewerBar() {
  const input = h("input", { value: reviewer(), placeholder: "Your name (recorded with each decision)", maxlength: "100",
    "aria-label": "Reviewer name", autocomplete: "name" });
  const bar = h("div", { class: `reviewer ${reviewer() ? "" : "missing"}` }, h("label", {}, "Reviewer", input));
  input.addEventListener("input", () => {
    setReviewer(input.value);
    bar.classList.toggle("missing", !input.value.trim());
    if (input.value.trim()) { input.classList.remove("invalid"); bar.querySelector(".warn")?.remove(); }
    for (const b of document.querySelectorAll("[data-needs-name]")) b.disabled = !input.value.trim() || b.dataset.blocked === "1";
  });
  return bar;
}

function needName() {
  if (reviewer()) return false;
  // No re-render: values typed in the decision cells stay where they are.
  const bar = document.querySelector(".reviewer");
  bar?.classList.add("missing");
  const input = bar?.querySelector("input");
  if (input) { input.classList.add("invalid"); input.focus(); }
  announce("Enter your name in the Reviewer field: each decision and approval records who made it.");
  if (bar && !bar.querySelector(".warn")) bar.append(h("span", { class: "warn", role: "alert" }, "Name required"));
  return true;
}

registerOp("review", {
  title: "Review and export",
  help: "Check named values against the page: accept, correct or mark each absent, then approve. Only approved values are exported as approved.",
  steps: () => {
    const r = review.current;
    return [["Open a document", "Name the fields", "Decide each value", "Approve and export"],
      !store.open && !r ? 0 : !r ? 1 : r.status === "open" ? 2 : 3];
  },
  render(body) {
    if (review.error) body.append(errorBox(review.error));
    if (review.current) body.append(reviewCard(review.current));
    else body.append(startForm());
    body.append(exportsCard());
    body.append(queueCard());
  },
});

function startForm() {
  const name = h("input", { value: reviewer(), placeholder: "Your name", maxlength: "100", "aria-label": "Your name", required: true });
  const fields = h("input", { value: review.fields, placeholder: "Fields, e.g. registration number, date (empty: a preset for the document type)", maxlength: "400", "aria-label": "Fields to review", dir: "auto" });
  // What is typed is kept, so a refresh of the panel (a document opened, the list of reviews loaded) never loses it.
  name.addEventListener("input", () => setReviewer(name.value));
  fields.addEventListener("input", () => { review.fields = fields.value; });
  const mode = h("select", { "aria-label": "How to review" },
    h("option", { value: "review" }, "Check the extracted values"),
    h("option", { value: "manual" }, "Type every value myself (extraction hidden)"));
  const form = h("form", { class: "card" },
    scopeBox("open"),
    h("label", {}, "Reviewer", name), h("label", {}, "Fields", fields), h("label", {}, "Mode", mode),
    h("div", { class: "next" }, h("button", { class: "btn primary", type: "submit", disabled: !store.open || null }, "Start review")));
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!name.value.trim()) { name.focus(); return; }
    setReviewer(name.value);
    review.fields = fields.value;
    const btn = form.querySelector("button[type=submit]");
    btn.disabled = true; btn.textContent = "Reading the values…";
    try {
      const list = fields.value.split(",").map((f) => f.trim()).filter(Boolean);
      const r = await api("/api/reviews", { method: "POST", json: { doc_id: store.open.id, reviewer: name.value.trim(), mode: mode.value, cohort: null, fields: list.length ? list : null } });
      show(r);
      review.queue = null;
    } catch (err) { review.error = err.message; }
    renderOps();
  });
  return form;
}

function show(r) {
  clockStop();
  review.current = r;
  review.error = null;
  review.activeMs = Number(storageGet(`inklight-review-ms-${r.id}`) || 0);
  review.since = null;
  clockStart();
}

async function decide(field, action, value) {
  if (needName()) return;
  try {
    review.current = await api(`/api/reviews/${review.current.id}/decide`, { method: "POST", json: { field, action, value: value ?? null, reviewer: reviewer() } });
    review.error = null;
    renderOps();
    const row = document.querySelector(`[data-field="${CSS.escape(field)}"]`);
    row?.classList.add("done-flash");
    announce(`${field.replace(/_/g, " ")}: ${action}`);
  } catch (err) { review.error = err.message; renderOps(); }
}

function reviewCard(r) {
  const undecided = r.fields.filter((f) => !f.action).length;
  const approved = r.status !== "open";
  return h("div", { class: "card" },
    h("div", { class: "card-head" }, h("span", { class: "card-title", dir: "auto" }, r.doc_name),
      approved ? h("span", { class: "label approved" }, "approved")
        : undecided ? h("span", { class: "label check" }, `${undecided} to decide`) : h("span", { class: "label raw" }, "ready to approve"),
      h("span", {}, r.mode === "manual" ? "typing every value" : "checking extracted values")),
    approved ? null : reviewerBar(),
    h("p", { class: "muted" }, r.mode === "manual" ? "Type each value from the page, or mark it absent." : "Choose a prediction to see where it was read. Values marked “check” need a closer look."),
    h("div", { class: "grid-wrap" }, h("table", { class: "grid review-table" },
      h("thead", {}, h("tr", {}, ...["field", "extracted", "decision"].map((c) => h("th", {}, c)))),
      h("tbody", {}, ...r.fields.map((f) => h("tr", { "data-field": f.field }, h("td", {}, f.field.replace(/_/g, " ")), predictionCell(f, r), decisionCell(f, r)))))),
    approved
      ? h("div", {}, h("p", { class: "muted" }, `Approved by ${r.approved_by} · ${r.approved_at.slice(0, 19).replace("T", " ")}`), reopenForm(r),
          h("div", { class: "next" }, h("button", { class: "btn", type: "button", onclick: () => { review.current = null; renderOps(); } }, "Review another document")))
      : h("div", { class: "next" },
          h("button", { class: "btn quiet", type: "button", onclick: () => { clockStop(); review.current = null; renderOps(); } }, "Back"),
          h("button", { class: "btn primary", type: "button", disabled: undecided > 0 || !reviewer() || null, onclick: approve,
            "data-needs-name": "", "data-blocked": undecided > 0 ? "1" : "0" },
            undecided ? `Decide ${undecided} more to approve` : "Approve")));
}

async function approve() {
  if (needName()) return;
  try {
    review.current = await api(`/api/reviews/${review.current.id}/approve`, { method: "POST", json: { reviewer: reviewer(), active_seconds: activeSeconds() } });
    clockStop();
    review.queue = null;
    announce("Review approved");
  } catch (err) { review.error = err.message; }
  renderOps();
}

function predictionCell(f, r) {
  if (r.mode === "manual" && r.status === "open") return h("td", { class: "muted" }, "hidden while you type");
  if (f.predicted == null) return h("td", { class: "none" }, h("span", { class: "label missing" }, "not found"), f.warning ? h("div", { class: "warn" }, f.warning) : null);
  const go = () => f.source && (openDoc(r.doc_id, f.source.page, f.source.bbox ? [{ page: f.source.page, bbox: f.source.bbox, kind: f.flagged ? "check" : "evidence", label: f.flagged ? "Check" : "Source" }] : []), showView("viewer"));
  return h("td", { class: "value", dir: "auto", tabindex: "0", role: "button", onclick: go, onkeydown: (e) => { if (e.key === "Enter") go(); } },
    String(fmt(f.predicted)),
    f.flagged ? h("div", {}, h("span", { class: "label check" }, "check")) : null,
    f.raw && f.raw !== String(f.predicted) ? h("div", { class: "muted" }, `As read: “${f.raw}”`) : null,
    f.warning ? h("div", { class: "warn" }, f.warning) : null);
}

function decisionCell(f, r) {
  if (r.status !== "open") return h("td", { dir: "auto" }, f.action === "absent" ? "absent" : String(fmt(f.final)), h("div", { class: "muted" }, f.action || ""));
  const input = h("input", { dir: "auto", value: f.action && f.action !== "absent" ? String(f.entered ?? f.final ?? "") : "",
    placeholder: r.mode === "manual" ? "type the value" : "correct value", "aria-label": `Value for ${f.field.replace(/_/g, " ")}` });
  const save = () => decide(f.field, r.mode === "manual" ? "entered" : "corrected", input.value);
  input.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); save(); } });
  return h("td", {}, input,
    h("div", { class: "row" },
      r.mode === "review" && f.predicted != null ? h("button", { class: "btn small", type: "button", onclick: () => decide(f.field, "accepted") }, "Accept") : null,
      h("button", { class: "btn small", type: "button", onclick: save }, r.mode === "manual" ? "Save" : "Save correction"),
      h("button", { class: "btn small quiet", type: "button", onclick: () => decide(f.field, "absent") }, "Absent")),
    f.action ? h("div", { class: "decided" }, `✓ ${f.action}${f.action === "absent" ? "" : `: ${fmt(f.final)}`}`) : null);
}

// Reopening an approved review needs a reason; the history keeps both approvals and the reason.
function reopenForm(r) {
  const reason = h("input", { placeholder: "Why reopen? (required)", maxlength: "500", "aria-label": "Reason for reopening" });
  return h("div", { class: "row" }, h("div", { class: "grow" }, reason),
    h("button", { class: "btn small", type: "button", onclick: async () => {
      if (!reason.value.trim()) { reason.focus(); return; }
      if (needName()) return;
      try { show(await api(`/api/reviews/${r.id}/reopen`, { method: "POST", json: { reviewer: reviewer(), reason: reason.value.trim() } })); review.queue = null; }
      catch (err) { review.error = err.message; }
      renderOps();
    } }, "Reopen"));
}

function exportsCard() {
  const approvedCsv = () => {
    if (!reviewer()) return Promise.reject(new Error("Enter your name in the Reviewer field first: exports record who made them"));
    return api("/api/reviews/export", { method: "POST", json: { actor: reviewer(), format: "csv", cohort: null }, raw: true }).then((res) => res.blob());
  };
  return h("div", { class: "card" },
    h("div", { class: "card-head" }, h("span", { class: "card-title" }, "Export")),
    review.current && review.current.status !== "open" ? reviewerBar() : null,  // the start form and an open review show their own
    h("p", { class: "note approved" }, h("span", { class: "label approved" }, "Approved values"),
      " Every approved review, one row per field: the extracted value, the decision, who approved it and where it was read."),
    h("div", { class: "next" }, exportButton("Download approved values (.csv)", approvedCsv, "inklight-approved.csv")),
    store.open ? h("p", { class: "note raw" }, h("span", { class: "label raw" }, "Raw extraction"), " The open document as read, not reviewed: use Extract text or Extract tables.") : null);
}

function queueCard() {
  const card = h("div", { class: "card" }, h("div", { class: "card-head" }, h("span", { class: "card-title" }, "Reviews")));
  if (!review.queue) {
    const wait = h("p", { class: "muted" }, "Loading…");
    card.append(wait);
    Promise.all([api("/api/reviews?status=open"), api("/api/reviews?status=approved")])
      .then(([open, approved]) => { review.queue = { open, approved }; wait.replaceWith(...queueRows()); })
      .catch((err) => wait.replaceWith(errorBox(err.message)));
    return card;
  }
  card.append(...queueRows());
  return card;
}

// A review stays when its document is removed from the library: it opens, and says the page cannot be shown.
async function openReview(r) {
  try { show(await api(`/api/reviews/${r.id}`)); }
  catch (err) { review.error = err.message; renderOps(); return; }
  try { await openDoc(r.doc_id, 1); }
  catch (_) { review.error = "This review's document is no longer in the library, so its page cannot be shown. Its values can still be decided and exported."; }
  renderOps();
}

function queueRows() {
  const row = (r, detail) => h("button", { class: "result", type: "button", onclick: () => openReview(r) },
    h("b", { dir: "auto" }, r.doc_name), h("span", { class: "muted" }, detail));
  const { open, approved } = review.queue;
  return [
    h("p", { class: "muted" }, `${open.length} open · ${approved.length} approved`),
    ...open.map((r) => row(r, `open · ${r.fields.filter((f) => !f.action).length} to decide`)),
    ...approved.slice(-10).reverse().map((r) => row(r, `approved by ${r.approved_by} · ${r.approved_at.slice(0, 16).replace("T", " ")}`))];
}

export function wireReview() {
  document.addEventListener("visibilitychange", () => (document.hidden ? clockStop() : clockStart()));
  window.addEventListener("blur", clockStop);
  window.addEventListener("focus", clockStart);
  window.addEventListener("beforeunload", clockStop);
}
