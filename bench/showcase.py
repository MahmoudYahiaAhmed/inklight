"""Screenshots of the real web workspace for the README, taken by driving a headless Chromium browser.

    inklight serve -c <config> --port 8777            # a library that already holds the showcase documents
    python bench/showcase.py --url http://127.0.0.1:8777 --cases bench/showcase_cases.json --out docs/assets/showcase

Nothing is edited: each case selects documents in the library, types its request into the app's own input and
submits it, waits for the app's own result card, and saves the browser's screenshot. The result JSON the app
received is saved next to each image, so every picture can be checked against what the build returned.
Needs Chrome or Edge, and the ``websocket-client`` package (only for this script).
"""

from __future__ import annotations

import argparse
import base64
import json
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

BROWSERS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    "google-chrome",
    "chromium",
    "msedge",
]


class Page:
    def __init__(self, ws_url: str) -> None:
        import websocket  # websocket-client

        self.ws = websocket.create_connection(ws_url, timeout=120, suppress_origin=True)
        self.n = 0

    def call(self, method: str, **params):  # type: ignore[no-untyped-def]
        self.n += 1
        self.ws.send(json.dumps({"id": self.n, "method": method, "params": params}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == self.n:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result", {})

    def js(self, expression: str):  # type: ignore[no-untyped-def]
        r = self.call("Runtime.evaluate", expression=expression, awaitPromise=True, returnByValue=True)
        if "exceptionDetails" in r:
            raise RuntimeError(r["exceptionDetails"].get("text", "JS error"))
        return r.get("result", {}).get("value")

    def wait(self, expression: str, timeout: float = 120.0) -> None:
        end = time.time() + timeout
        while time.time() < end:
            if self.js(expression):
                return
            time.sleep(0.25)
        raise TimeoutError(expression)

    def shot(self, path: Path) -> None:
        data = self.call("Page.captureScreenshot", format="png", captureBeyondViewport=False)["data"]
        path.write_bytes(base64.b64decode(data))


def launch(port: int, width: int, height: int) -> tuple[subprocess.Popen, str]:
    exe = next((b for b in BROWSERS if Path(b).exists() or shutil.which(b)), None)
    if exe is None:
        sys.exit("no Chrome or Edge found")
    profile = tempfile.mkdtemp(prefix="inklight-shot-")
    proc = subprocess.Popen(
        [
            exe,
            "--headless=new",
            f"--remote-debugging-port={port}",
            f"--window-size={width},{height}",
            f"--user-data-dir={profile}",
            "--hide-scrollbars",
            "--force-device-scale-factor=1",
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for _ in range(100):
        try:
            targets = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/json").read())
            page = next(t for t in targets if t.get("type") == "page")
            return proc, page["webSocketDebuggerUrl"]
        except Exception:  # noqa: BLE001 - the browser is still starting
            time.sleep(0.2)
    proc.kill()
    sys.exit("browser did not start")


def run_case(page: Page, url: str, case: dict, out: Path) -> dict:
    page.call("Page.navigate", url=url)
    page.wait("document.readyState === 'complete' && typeof state !== 'undefined' && state.docs.length > 0")
    names = json.dumps(case.get("documents", []))
    page.js(
        f"state.selected = new Set(state.docs.filter((d) => {names}.includes(d.name)).map((d) => d.id)); "
        "renderDocs(); renderScope(); true"
    )
    # Record the very response the page receives, so the saved JSON is what the picture shows.
    page.js(
        "window.__inklightLast = null; if (!window.__wrapped) { const f = window.fetch; "
        "window.fetch = async (...a) => "
        "{ const r = await f(...a); if (String(a[0]).includes('/api/ask')) r.clone().json().then((j) => "
        "{ window.__inklightLast = j; }); return r; }; window.__wrapped = true; } true"
    )
    page.js(
        f"document.querySelector('#ask-input').value = {json.dumps(case['request'])}; "
        "document.querySelector('#ask-btn').click(); true"
    )
    page.wait("window.__inklightLast !== null && !document.querySelector('#results .thinking')")
    time.sleep(1.5)  # the viewer loads the cited page image
    page.shot(out / f"{case['id']}.png")
    result = page.js("window.__inklightLast")
    (out / f"{case['id']}.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"id": case["id"], "state": result["state"], "answer": result["answer"][:200]}


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--cases", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--port", type=int, default=9333)
    ap.add_argument("--width", type=int, default=1440)
    ap.add_argument("--height", type=int, default=960)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    cases = json.loads(args.cases.read_text(encoding="utf-8"))
    proc, ws = launch(args.port, args.width, args.height)
    try:
        page = Page(ws)
        page.call(
            "Emulation.setDeviceMetricsOverride",
            width=args.width,
            height=args.height,
            deviceScaleFactor=1,
            mobile=False,
        )
        for case in cases:
            print(json.dumps(run_case(page, args.url, case, args.out), ensure_ascii=False))
    finally:
        proc.kill()


if __name__ == "__main__":
    main()
