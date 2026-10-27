// Shared helpers. Every piece of document text is set with textContent (h() never parses HTML).

export const $ = (s, root = document) => root.querySelector(s);
export const $$ = (s, root = document) => [...root.querySelectorAll(s)];

export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") el.className = v;
    else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2), v);
    else if (v !== null && v !== undefined && v !== false) el.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat()) if (c !== null && c !== undefined && c !== false) el.append(c instanceof Node ? c : String(c));
  return el;
}

// Requests go to paths relative to the page, so the workspace works at a reverse proxy's prefix
// (https://example.org/inklight/) as well as at the root.
export const withToken = (path) => path.replace(/^\//, "");

// A private workspace's token (INKLIGHT_SERVER_TOKEN): given once as #token=… or typed when asked, kept for this tab
// only and removed from the address bar. It goes in a header; the server answers with a cookie that previews and
// progress streams carry, so the token itself never appears in a URL or a log.
const TOKEN_KEY = "inklight.token";
function readToken() {
  const given = new URLSearchParams(location.hash.slice(1)).get("token");
  if (given) {
    try { sessionStorage.setItem(TOKEN_KEY, given); } catch (_) { /* storage blocked: kept for this page only */ }
    history.replaceState(null, "", location.pathname + location.search);
    return given;
  }
  try { return sessionStorage.getItem(TOKEN_KEY) || ""; } catch (_) { return ""; }
}
let TOKEN = readToken();
const HEADERS = () => ({ "X-Inklight": "1", ...(TOKEN ? { "X-Inklight-Token": TOKEN } : {}) });

function askForToken() {
  const typed = window.prompt(TOKEN ? "That access token was not accepted. Enter the workspace's access token:"
                                    : "This Inklight workspace needs its access token:");
  if (!typed) return false;
  TOKEN = typed.trim();
  try { sessionStorage.setItem(TOKEN_KEY, TOKEN); } catch (_) { /* kept for this page only */ }
  return true;
}

export async function api(path, opts = {}) {
  const headers = { ...HEADERS(), ...(opts.headers || {}) };
  if (opts.json !== undefined) { headers["Content-Type"] = "application/json"; opts.body = JSON.stringify(opts.json); }
  const res = await fetch(withToken(path), { ...opts, headers });
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch (_) { /* not JSON */ }
    if (res.status === 401 && detail === "Missing or wrong token" && askForToken()) return api(path, opts);
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  // A download wants the bytes as served (a JSON file included), not the parsed value: { raw: true } returns the
  // Response itself.
  if (opts.raw) return res;
  return res.headers.get("content-type")?.includes("json") ? res.json() : res;
}

// An upload with real byte progress (fetch cannot report it).
export function uploadWithProgress(path, form, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", path);
    for (const [k, v] of Object.entries(HEADERS())) xhr.setRequestHeader(k, v);
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(e.loaded, e.total);
    xhr.onload = () => {
      let body = null;
      try { body = JSON.parse(xhr.responseText); } catch (_) { /* not JSON */ }
      if (xhr.status >= 200 && xhr.status < 300) resolve(body);
      else reject(new Error(body?.detail || xhr.statusText || `HTTP ${xhr.status}`));
    };
    xhr.onerror = () => reject(new Error("The connection to Inklight was lost"));
    xhr.send(form);
  });
}

// replaceChildren with the empty entries (null, undefined, false) left out, as h() does.
export function fill(el, ...children) {
  el.replaceChildren(...children.flat().filter((c) => c !== null && c !== undefined && c !== false));
}

export const reducedMotion = () => matchMedia("(prefers-reduced-motion: reduce)").matches;

// Status changes are announced once, politely; repeated identical messages are skipped.
let lastAnnounced = "";
export function announce(text) {
  if (!text || text === lastAnnounced) return;
  lastAnnounced = text;
  const el = $("#announcer");
  el.textContent = "";
  requestAnimationFrame(() => { el.textContent = text; });
}

export function saveBlob(blob, name) {
  const url = URL.createObjectURL(blob);
  h("a", { href: url, download: name }).click();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

export function storageGet(key) { try { return localStorage.getItem(key); } catch (_) { return null; } }
export function storageSet(key, value) { try { localStorage.setItem(key, value); } catch (_) { /* private mode */ } }

export const fmt = (v) => (typeof v === "number" ? v.toLocaleString(undefined, { maximumFractionDigits: 2 }) : v ?? "—");
// How a page's text was obtained, in the same words as the CLI (src/inklight/read_as.py). Only a page read by OCR is
// called OCR: a .txt file is plain text, a digital PDF its text layer.
const READ_AS = { plain: "plain text", text: "PDF text layer", hybrid: "PDF text layer and OCR", ocr: "OCR", error: "page failed" };
export const pageMethod = (source) => READ_AS[source] || source || "unknown";
export function readAs(counts) {
  const read = Object.entries(counts || {}).filter(([k, n]) => n && k !== "error").sort((a, b) => b[1] - a[1]);
  if (!read.length) return counts?.error ? "page failed" : "";
  if (read.length === 1) return pageMethod(read[0][0]);
  return "mixed: " + read.map(([k, n]) => `${n} page${n === 1 ? "" : "s"} ${pageMethod(k)}`).join(", ");
}
export const sourcesOf = (pages) => pages.reduce((acc, p) => ({ ...acc, [p.source]: (acc[p.source] || 0) + 1 }), {});

export const plural = (n, one, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

export function loading(text) {
  return h("div", { class: "loading", role: "status" }, h("span", { class: "spinner", "aria-hidden": "true" }), text);
}

export function errorBox(text) {
  return h("div", { class: "error-box", role: "alert" }, text);
}

// A tiny shared store: modules subscribe to changes of the open document, the selection and the library.
const listeners = new Set();
export const store = {
  docs: [], selected: new Set(), open: null, pages: [], page: 1, structure: null, op: "text",
  marks: [], jobs: new Map(),
  where: "on this computer",  // where documents are read: "on the server" when the workspace is hosted
  pollProgress: false,  // ask for an import's progress instead of streaming it (the server says so behind a tunnel)
};
export function changed(what) { for (const fn of listeners) fn(what); }
export function onChange(fn) { listeners.add(fn); }

// A page's text for reading on screen: the regions in reading order (a table region reads "header: value", row by
// row), or the OCR lines when there are no regions. Downloads keep the stored text as it is.
export function pageText(p) {
  if (!p) return "";
  const blocks = (p.blocks || []).map((b) => b.text.trim()).filter(Boolean);
  if (blocks.length) return blocks.join("\n\n");
  return (p.lines || []).map((l) => l.text).join("\n");
}
