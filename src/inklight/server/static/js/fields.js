// Extract named fields: each value is read at a printed label of that name and keeps its page and box. A value with
// a warning is marked "check"; a value not found says so. Nothing here is approved: that is Review.

import { announce, api, errorBox, fmt, h, loading, readAs, saveBlob, store } from "./dom.js";
import { showView } from "./library.js";
import { rawNote, registerOp, renderOps, scopeBox, scopeIds, selectOp } from "./ops.js";
import { openDoc } from "./viewer.js";

const EXAMPLES = ["registration number", "date", "total", "company name", "رقم القيد"];
const run = { fields: "", records: null, error: null, chosen: null };

registerOp("fields", {
  title: "Extract fields",
  help: "Name the values you want. Each is read where it is printed next to its label, and keeps its page and place.",
  steps: () => [["Choose documents", "Name the fields", "Check the values", "Review and export"],
    !scopeIds().length ? 0 : run.records && run.records !== "loading" ? 2 : 1],
  render(body) {
    body.append(scopeBox("scope"));
    const input = h("input", { value: run.fields, placeholder: "Fields, separated by commas", "aria-label": "Fields to extract", dir: "auto" });
  input.addEventListener("input", () => { run.fields = input.value; });
    const form = h("form", { class: "row" }, h("div", { class: "grow" }, input),
      h("button", { class: "btn primary", type: "submit", disabled: !scopeIds().length || null }, "Extract"));
    form.addEventListener("submit", (e) => { e.preventDefault(); extract(input.value); });
    body.append(form, h("div", { class: "chips", "aria-label": "Examples" }, ...EXAMPLES.map((x) =>
      h("button", { class: "chip", type: "button", dir: "auto", onclick: () => {
        const have = input.value.split(",").map((s) => s.trim()).filter(Boolean);
        if (!have.includes(x)) input.value = [...have, x].join(", ");
        run.fields = input.value;
        input.focus();
      } }, x))));
    if (run.error) body.append(errorBox(run.error));
    if (run.records === "loading") body.append(h("div", { class: "card" }, loading("Reading each value at its label…")));
    else if (run.records) body.append(rawNote(), resultsCard(run.records), nextActions(run.records));
  },
});

async function extract(text) {
  const fields = text.split(",").map((s) => s.trim().toLowerCase().replace(/\s+/g, "_")).filter(Boolean);
  run.fields = text;
  if (!fields.length) { run.error = "Name at least one field, for example: registration number, date."; renderOps(); return; }
  Object.assign(run, { records: "loading", error: null, chosen: null });
  renderOps();
  try {
    const { records } = await api("/api/extract", { method: "POST", json: { doc_ids: scopeIds(), fields } });
    run.records = records;
    const found = records.reduce((n, r) => n + Object.values(r.fields).filter((v) => v.value != null).length, 0);
    announce(`${found} of ${records.length * fields.length} values found`);
  } catch (err) { run.records = null; run.error = err.message; }
  renderOps();
}

function resultsCard(records) {
  const cols = [...new Set(records.flatMap((r) => Object.keys(r.fields)))];
  return h("div", { class: "card" },
    h("div", { class: "card-head" }, h("span", { class: "card-title" }, "Values"), h("span", {}, "Choose a value to see where it was read.")),
    h("div", { class: "grid-wrap" }, h("table", { class: "grid" },
      h("thead", {}, h("tr", {}, h("th", {}, "document"), ...cols.map((c) => h("th", {}, c.replace(/_/g, " "))))),
      h("tbody", {}, ...records.map((r) => h("tr", {}, h("td", { dir: "auto" }, r.name, h("div", { class: "muted small" }, howRead(r))), ...cols.map((c) => valueCell(r, c))))))));
}

const howRead = (r) => readAs(store.docs.find((d) => d.id === r.doc_id)?.read_as) || "";

function valueCell(r, c) {
  const v = r.fields[c];
  if (!v || v.value == null) {
    return h("td", { class: "none" }, h("span", { class: "label missing" }, "not found"), v?.warning ? h("div", { class: "warn" }, v.warning) : null);
  }
  const check = Boolean(v.warning) || v.confidence < 0.7;
  return h("td", { class: "value", dir: "auto", tabindex: "0", role: "button",
    title: `${v.method} · ${check ? "check this value" : "read at its label"}`,
    onclick: () => showSource(v, check), onkeydown: (e) => { if (e.key === "Enter") showSource(v, check); } },
    String(fmt(v.value)),
    check ? h("div", {}, h("span", { class: "label check" }, "check")) : null,
    v.warning ? h("div", { class: "warn" }, v.warning) : null);
}

function showSource(v, check) {
  if (!v.source) return;
  const s = v.source;
  openDoc(s.doc_id, s.page, s.bbox ? [{ page: s.page, bbox: s.bbox, kind: check ? "check" : "evidence", label: check ? "Check" : "Source", title: v.field }] : []);
  showView("viewer");
}

function nextActions(records) {
  const fields = [...new Set(records.flatMap((r) => Object.keys(r.fields)))];
  return h("div", { class: "next" },
    h("button", { class: "btn", type: "button", onclick: () => downloadRaw(records) }, "Download these values (.csv)"),
    h("button", { class: "btn primary", type: "button", onclick: () => {
      if (records[0]) openDoc(records[0].doc_id, 1);
      window.dispatchEvent(new CustomEvent("inklight:review-fields", { detail: fields.map((f) => f.replace(/_/g, " ")).join(", ") }));
      selectOp("review");
    } }, "Review these values"));
}

function downloadRaw(records) {
  const cols = [...new Set(records.flatMap((r) => Object.keys(r.fields)))];
  const esc = (v) => { let s = v == null ? "" : String(v); if (/^[=+\-@\t\r]/.test(s)) s = "'" + s; return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s; };
  const note = "Raw extraction: not reviewed. A value read by OCR can be misread; OCR confidence is an estimate.";
  const rows = [["document", "read as", ...cols, "note"].map(esc).join(",")]
    .concat(records.map((r, i) => [r.name, howRead(r), ...cols.map((c) => r.fields[c]?.value), i === 0 ? note : ""].map(esc).join(",")));
  saveBlob(new Blob(["﻿" + rows.join("\n")], { type: "text/csv" }), "inklight-values-raw.csv");
  announce("Values saved");
}
