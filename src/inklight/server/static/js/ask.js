// Ask (experimental). Every result says what it is, from what the steps did (agent/runner.py, result_outcome);
// a proposed answer is never shown as a confirmed one.

import { announce, api, errorBox, h, loading, saveBlob, store } from "./dom.js";
import { showView } from "./library.js";
import { registerOp, renderOps, scopeIds } from "./ops.js";
import { openDoc } from "./viewer.js";

const OUTCOMES = {
  extracted: ["raw", "Extracted text or search results", "Shown as found. Nothing was concluded from it."],
  proposed: ["proposed", "Proposed answer: review before use", "Drawn from the documents. Open each cited place and confirm it."],
  supported: ["supported", "Supported answer: value at its printed label", "Read where the label or table cell asked about is printed. OCR can still misread it: check the cited place."],
  partial: ["partial", "Partial result", "Only part of the request was done; the answer says which part."],
  missing_evidence: ["missing", "Missing evidence", "The documents in scope did not show the value asked for."],
  ambiguous: ["ambiguous", "Several candidates: choose one", "More than one value matches. Each opens at its source."],
  unsupported: ["failed", "Not supported", "This request is not something Ask can do."],
  failed: ["failed", "Failed", "An error stopped the request."],
};
const EXAMPLES = ["What is the registration number?", "ما اسم الشركة؟", "Compare the registration number in these documents"];
const ask = { job: null, results: [], error: null, text: "" };

registerOp("ask", {
  experimental: true,
  title: "Ask",
  help: "A question in plain words, answered from the documents with the places it read. Treat every answer as a lead to check.",
  steps: () => [["Choose the scope", "Ask", "Check the sources"], ask.results.length ? 2 : ask.job ? 1 : 0],
  render(body) {
    const n = scopeIds().length;
    body.append(h("div", { class: "scope-box" }, h("b", {}, store.selected.size ? `${n} selected document${n === 1 ? "" : "s"}` : "All documents"),
      h("span", { class: "muted" }, store.selected.size ? "" : " (tick documents in the library to narrow it)")));
    const input = h("textarea", { rows: "2", maxlength: "4000", placeholder: "Ask about the documents", "aria-label": "Your question", dir: "auto" }, ask.text);
    input.addEventListener("input", () => { ask.text = input.value; });
    input.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); form.requestSubmit(); } });
    const form = h("form", { class: "card" }, input,
      h("div", { class: "row" }, h("div", { class: "chips grow" }, ...EXAMPLES.map((x) => h("button", { class: "chip", type: "button", dir: "auto", onclick: () => { input.value = x; ask.text = x; input.focus(); } }, x))),
        ask.job ? h("button", { class: "btn", type: "button", onclick: stop }, "Stop") : null,
        h("button", { class: "btn primary", type: "submit", disabled: ask.job ? true : null }, ask.job ? "Working…" : "Ask")));
    form.addEventListener("submit", (e) => { e.preventDefault(); run(input.value.trim()); });
    body.append(form);
    if (ask.error) body.append(errorBox(ask.error));
    if (ask.job) body.append(h("div", { class: "card" }, loading("Planning, reading and checking against the documents…")));
    body.append(...ask.results.map(resultCard));
  },
});

async function run(request) {
  if (!request || ask.job) return;
  const job = Math.random().toString(36).slice(2, 12);
  Object.assign(ask, { job, error: null });
  renderOps();
  try {
    const r = await api("/api/ask", { method: "POST", json: { request, job_id: job, allow_write: false, doc_ids: store.selected.size ? [...store.selected] : null } });
    ask.results.unshift(r);
    announce(OUTCOMES[r.outcome]?.[1] || r.outcome);
    const first = r.sources[0];
    if (first) openDoc(first.doc_id, first.page, first.bbox ? [{ page: first.page, bbox: first.bbox, kind: "evidence", label: "Source" }] : []);
  } catch (err) { ask.error = err.message; }
  ask.job = null;
  renderOps();
}

function stop() {
  if (ask.job) api(`/api/jobs/${ask.job}/cancel`, { method: "POST" }).then(() => announce("Stopping the request"));
}

function resultCard(r) {
  const [cls, label, help] = OUTCOMES[r.outcome] || ["raw", r.outcome, ""];
  const parts = r.answer.split("\n\n").filter((p) => !p.startsWith("Understood as"));
  return h("div", { class: "card" },
    h("div", { class: "card-head" }, h("span", { class: `label ${cls}` }, label)),
    h("p", { class: "muted" }, help),
    h("div", { class: "card-title", dir: "auto" }, r.request),
    r.comparison ? comparison(r) : h("pre", { class: "text-out", dir: "auto" }, parts.join("\n\n")),
    candidates(r),
    r.records.length ? h("div", { class: "next" }, h("button", { class: "btn small", type: "button", onclick: () => csv(r.records) }, "Download values (.csv)")) : null,
    r.sources.length ? h("div", { class: "results" }, ...r.sources.map((s, i) => h("button", { class: "result", type: "button",
      onclick: () => { openDoc(s.doc_id, s.page, s.bbox ? [{ page: s.page, bbox: s.bbox, kind: "evidence", label: `Source ${i + 1}` }] : []); showView("viewer"); } },
      h("b", { dir: "auto" }, `[${i + 1}] ${s.name} · page ${s.page}`),
      h("span", { dir: "auto" }, `“${s.excerpt.replace(/\s+/g, " ").slice(0, 200)}${s.excerpt.length > 200 ? "…" : ""}”`)))) : null,
    r.warnings.length ? h("div", {}, ...r.warnings.map((w) => h("div", { class: "warn" }, `⚠ ${w}`))) : null,
    h("details", { class: "trace" }, h("summary", {}, `How it was done · ${r.trace.length} steps`),
      ...r.trace.map((t) => h("div", { class: "trace-row" }, String(t.index + 1), t.tool, t.status, `${Math.round(t.duration_ms)} ms`, t.error || t.summary))));
}

function candidates(r) {
  if (!r.candidates?.length) return null;
  const chosen = h("div", { dir: "auto" });
  return h("div", {}, h("p", { class: "muted" }, "Choose the value you mean; it opens at its source:"),
    h("div", { class: "chips" }, ...r.candidates.map((c) => h("button", { class: "chip", type: "button", dir: "auto",
      onclick: (e) => {
        for (const el of e.target.parentElement.children) el.classList.toggle("on", el === e.target);
        openDoc(c.source.doc_id, c.source.page, c.source.bbox ? [{ page: c.source.page, bbox: c.source.bbox, kind: "check", label: "Your choice" }] : []);
        chosen.replaceChildren(h("span", { class: "label proposed" }, "your choice"), " ", c.value,
          h("span", { class: "muted" }, ` · ${c.context || c.source.name}. Check it at the source and use Review to approve it.`));
      } }, `${c.value} · ${c.context || c.source.name}`))), chosen);
}

function comparison(r) {
  const c = r.comparison;
  const verdict = { matches: "supported", differs: "check", "cannot determine": "missing" }[c.verdict] || "raw";
  return h("div", {},
    h("div", { class: "grid-wrap" }, h("table", { class: "grid" },
      h("thead", {}, h("tr", {}, ...["document", c.field, "where"].map((x) => h("th", { dir: "auto" }, x)))),
      h("tbody", {}, ...c.values.map((v) => h("tr", {},
        h("td", { dir: "auto" }, v.document),
        h("td", { dir: "auto", class: v.status === "found" ? "" : "none" }, v.status === "found" ? v.value : v.status === "several candidates" ? `several: ${v.candidates.join(", ")}` : "not found",
          ...(v.warnings || []).map((w) => h("div", { class: "warn" }, `⚠ ${w}`))),
        h("td", {}, v.source ? h("button", { class: "btn small", type: "button", onclick: () => openDoc(v.source.doc_id, v.source.page, v.source.bbox ? [{ page: v.source.page, bbox: v.source.bbox, kind: "evidence", label: "Source" }] : []) }, `page ${v.source.page}`) : "—")))))),
    h("p", {}, h("span", { class: `label ${verdict}` }, c.verdict)));
}

function csv(records) {
  const cols = [...new Set(records.flatMap((r) => Object.keys(r.fields)))];
  const esc = (v) => { let s = v == null ? "" : String(v); if (/^[=+\-@\t\r]/.test(s)) s = "'" + s; return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s; };
  const rows = [["document", ...cols].map(esc).join(",")].concat(records.map((r) => [r.name, ...cols.map((c) => r.fields[c]?.value)].map(esc).join(",")));
  saveBlob(new Blob(["﻿" + rows.join("\n")], { type: "text/csv" }), "inklight-ask-values.csv");
}
