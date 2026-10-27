// Inklight workspace: wiring. Choose an operation, choose documents, configure only what it needs, look at the
// result next to its source, review when needed, export.

import "./fields.js";
import "./review.js";
import "./ask.js";
import { $, announce, api, h, storageSet } from "./dom.js";
import { loadDocs, recoverJobs, wireLibrary } from "./library.js";
import { renderOps, selectOp, setStructureInstalled, wireOps } from "./ops.js";
import { wireReview } from "./review.js";
import { wireViewer } from "./viewer.js";

async function loadStatus() {
  const s = await api("/api/status");
  $("#build").textContent = `Inklight ${s.version} · ${s.commit}`;
  setStructureInstalled(Boolean(s.structure?.installed));
  const downloading = Object.values(s.downloads || {}).find((d) => d.state === "downloading");
  const waiting = Object.values(s.downloads || {}).some((d) => d.state === "waiting");
  const chip = $("#status-chip");
  const text = chip.querySelector("span");
  if (downloading || waiting) {
    // "waiting": another Inklight process is downloading the same models; this one has no bytes to count.
    text.textContent = downloading ? `Downloading models ${Math.round((100 * downloading.done) / downloading.total)}%` : "Waiting for models";
    setTimeout(loadStatus, 1500);
  } else {
    text.textContent = s.models.remote?.configured ? "Local + remote model" : "On this computer";
  }
  chip.title = s.models.remote?.configured ? "A remote model is configured for Ask" : "Documents and models stay on this computer";
  $("#set-brain").value = s.brain;
  $("#set-writer").checked = s.use_writer;
  $("#set-info").replaceChildren(
    h("div", {}, `OCR: Inklight OCR · ${s.ocr.dpi} dpi · mode ${s.ocr.mode}`),
    h("div", {}, `Document structure: ${s.structure?.installed ? (s.structure.enabled ? "on for every import" : "installed; used when you extract tables") : "not installed"}`),
    ...Object.entries(s.models).filter(([k]) => k !== "remote").map(([k, v]) => h("div", {}, `Ask ${k} (${v.params}): ${v.installed ? "installed" : "not installed"}`)),
    h("div", {}, `Remote model: ${s.models.remote?.configured ? `configured (${s.models.remote.used_for})` : "off: nothing leaves this computer"}`),
    h("div", {}, `Limits: ${s.limits.max_file_mb} MB per file · ${s.limits.max_pages} pages`),
    h("div", {}, `Library: ${s.stats.documents} documents · ${s.stats.pages} pages`),
    h("div", {}, `Version ${s.version} · ${s.commit}`));
}

// Theme: follow the system, or keep light or dark (stored in this browser only). The button cycles the three.
const THEMES = [["auto", "i-auto", "follows the system"], ["light", "i-sun", "light"], ["dark", "i-moon", "dark"]];
function wireTheme() {
  const btn = $("#theme");
  const show = (name) => {
    const [, icon, words] = THEMES.find(([n]) => n === name);
    btn.querySelector("use").setAttribute("href", `#${icon}`);
    btn.setAttribute("aria-label", `Theme: ${words}. Change theme`);
    btn.title = `Theme: ${words}`;
  };
  let current = document.documentElement.dataset.theme || "auto";
  show(current);
  btn.addEventListener("click", () => {
    current = THEMES[(THEMES.findIndex(([n]) => n === current) + 1) % THEMES.length][0];
    if (current === "auto") delete document.documentElement.dataset.theme; else document.documentElement.dataset.theme = current;
    storageSet("inklight-theme", current);
    show(current);
    announce(`Theme: ${THEMES.find(([n]) => n === current)[2]}`);
  });
}

function wire() {
  wireLibrary();
  wireViewer();
  wireOps();
  wireReview();
  $("#open-settings").addEventListener("click", () => { loadStatus(); $("#settings").showModal(); });
  $("#save-settings").addEventListener("click", async (e) => {
    e.preventDefault();
    await api("/api/settings", { method: "POST", json: { brain: $("#set-brain").value, use_writer: $("#set-writer").checked } });
    $("#settings").close();
    loadStatus();
    announce("Settings applied");
  });
  wireTheme();
  // Continuous animations pause while the page is not visible.
  document.addEventListener("visibilitychange", () => document.body.classList.toggle("paused", document.hidden));
}

wire();
selectOp("text");
loadStatus().catch(() => {});
loadDocs().then(renderOps).then(recoverJobs).catch((err) => {
  $("#docs").replaceChildren(h("li", { class: "empty-lib" }, `The library could not be loaded: ${err.message}`));
});
