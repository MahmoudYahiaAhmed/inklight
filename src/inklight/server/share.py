"""``inklight serve --share``: a public HTTPS link to a workspace bound to 127.0.0.1, through a Cloudflare quick tunnel.

Cloudflare carries the traffic: ``cloudflared`` (Cloudflare's tunnel client) connects out from this machine to
Cloudflare, which gives a random ``https://<words>.trycloudflare.com`` address and forwards its requests here. No
Cloudflare account is needed; the address changes every time and stops when the command stops. Nothing is opened on
this machine's firewall, and the server listens on 127.0.0.1 only.

The client is fetched only when ``--share`` asks for it: one pinned release from Cloudflare's GitHub releases, checked
against SHA-256 values pinned here, kept in Inklight's cache. Nothing else is downloaded, and no other provider is
ever tried. The token never reaches the tunnel's command line or its output: it is sent by browsers in a header.
"""

from __future__ import annotations

import contextlib
import hashlib
import http.client
import os
import platform
import re
import shutil
import signal
import socket
import ssl
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from ..errors import InklightError
from ..modelstore import cache_root, offline

VERSION = "2026.10.0"
RELEASES = "https://github.com/cloudflare/cloudflared/releases/download"
PROVIDER = "Cloudflare quick tunnel (trycloudflare.com)"
URL_PATTERN = re.compile(r"https://(?!api\.)[a-z0-9-]+\.trycloudflare\.com")  # not the API it asks
READY_PATTERN = re.compile(r"Registered tunnel connection")
# A new tunnel reaches every Cloudflare edge server within seconds, not at once: one good answer is not enough.
CHECKS_IN_A_ROW = 5
EDGE_NAME = "trycloudflare.com"  # its addresses are the Cloudflare edge that serves every quick tunnel
_CHUNK = 1 << 20
# All the tunnel client gets from the environment: where things are, the system's proxy and certificates. Not the
# token, not other credentials.
CLIENT_ENV = frozenset({
    "PATH", "HOME", "USERPROFILE", "TMPDIR", "TEMP", "TMP", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC",
    "LOCALAPPDATA", "APPDATA", "PROGRAMDATA", "LANG", "LC_ALL", "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "ALL_PROXY",
    "http_proxy", "https_proxy", "no_proxy", "all_proxy", "SSL_CERT_FILE", "SSL_CERT_DIR",
})  # fmt: skip
# Runs the client and ends it when Inklight's end of the pipe closes, however Inklight ends (Ctrl+C, a closed
# terminal, kill -9), on every system. Its output is the client's.
GUARD = (
    "import signal, subprocess, sys, threading\n"
    "child = subprocess.Popen(sys.argv[1:], stdin=subprocess.DEVNULL)\n"
    "signal.signal(signal.SIGTERM, lambda *_: child.terminate())\n"
    "def watch():\n"
    "    sys.stdin.buffer.read()\n"
    "    child.terminate()\n"
    "threading.Thread(target=watch, daemon=True).start()\n"
    "sys.exit(child.wait())\n"
)

Progress = Callable[[int, int], None]


class ShareError(InklightError):
    """The public link could not be made or stopped working; the message says what happened and what to try."""


@dataclass(frozen=True)
class Asset:
    name: str  # the release file
    size: int
    sha256: str  # of the release file
    binary_sha256: str  # of the program itself (inside the archive, for macOS)


# From the release's own list and GitHub's digest of each file; the two agree for every file below.
ASSETS: dict[tuple[str, str], Asset] = {
    ("linux", "x86_64"): Asset(
        "cloudflared-linux-amd64",
        40129756,
        "d33ff2d14475178d2012c2c56beba87389ac5ded27649519f198a7d3134a99db",
        "d33ff2d14475178d2012c2c56beba87389ac5ded27649519f198a7d3134a99db",
    ),
    ("linux", "aarch64"): Asset(
        "cloudflared-linux-arm64",
        37687584,
        "e6422b9d4f72d3194bc5a38676f13667c06666523217b842a877d72a80b5ac08",
        "e6422b9d4f72d3194bc5a38676f13667c06666523217b842a877d72a80b5ac08",
    ),
    ("darwin", "x86_64"): Asset(
        "cloudflared-darwin-amd64.tgz",
        21741581,
        "903845b81828c8cb3c5d13d816a2de71c06a3da5785469df8eb0e1b736d92f9f",
        "0560c9ab7281ac3f746055323623ed23bc0405b6dab9400474020cba33a978da",
    ),
    ("darwin", "aarch64"): Asset(
        "cloudflared-darwin-arm64.tgz",
        19809074,
        "a2f79ff7b9420aa537d74af239f376da170bbabeb529aec416002adac6a72e70",
        "72edfd3eea463aef4d5cb89e2e209cecb048cc756c2b01915de2e0ad7cb39830",
    ),
    ("windows", "x86_64"): Asset(
        "cloudflared-windows-amd64.exe",
        55365048,
        "86aee4017b26625cee8484c113558f48effa4cd47f7aa05fcf425604e5d2b23c",
        "86aee4017b26625cee8484c113558f48effa4cd47f7aa05fcf425604e5d2b23c",
    ),
}
_MACHINES = {"amd64": "x86_64", "x86_64": "x86_64", "x64": "x86_64", "arm64": "aarch64", "aarch64": "aarch64"}


def asset_for(system: str | None = None, machine: str | None = None) -> Asset:
    system = (system or platform.system()).lower()
    raw = (machine or platform.machine()).lower()
    asset = ASSETS.get((system, _MACHINES.get(raw, raw)))
    if asset is None:
        raise ShareError(
            f"--share has no tunnel client for {system} {raw}: it supports Linux (x86-64, ARM64), macOS and "
            "64-bit Windows. Use a reverse proxy instead (docs/HOSTING.md)."
        )
    return asset


def binary_path(asset: Asset) -> Path:
    name = "cloudflared.exe" if asset.name.endswith(".exe") else "cloudflared"
    return cache_root() / "tools" / f"cloudflared-{VERSION}" / name


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def ensure_client(
    asset: Asset | None = None, *, say: Callable[[str], None] = lambda _: None, progress: Progress | None = None
) -> Path:
    """The pinned tunnel client, verified; downloaded (and announced) only if it is not in the cache yet."""
    asset = asset or asset_for()
    target = binary_path(asset)
    if target.is_file() and _sha256(target) == asset.binary_sha256:
        return target
    if offline():
        raise ShareError(
            f"--share needs Cloudflare's tunnel client (cloudflared {VERSION}), and downloads are off "
            "(INKLIGHT_OFFLINE). Run once with network access to fetch it."
        )
    url = f"{RELEASES}/{VERSION}/{asset.name}"
    say(f"Downloading Cloudflare's tunnel client, cloudflared {VERSION} ({asset.size / 1e6:.0f} MB), from {url}")
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, name = tempfile.mkstemp(prefix=asset.name + ".", suffix=".part", dir=target.parent)
    os.close(handle)
    part = Path(name)
    try:
        _download(url, part, asset.size, progress)
        if _sha256(part) != asset.sha256:
            raise ShareError(
                f"The downloaded {asset.name} does not match its pinned SHA-256 and was deleted; nothing was run. "
                "Try again; if it keeps failing, the download is being altered on the way."
            )
        try:
            _install(part, target, asset)
        except OSError as exc:
            raise ShareError(
                f"Could not keep the tunnel client in {target.parent} ({exc}). If another Inklight is using it, "
                "stop that one first."
            ) from exc
    finally:
        part.unlink(missing_ok=True)
    if _sha256(target) != asset.binary_sha256:
        target.unlink(missing_ok=True)
        raise ShareError(f"The tunnel client inside {asset.name} does not match its pinned SHA-256; it was deleted")
    say(f"Checked its SHA-256 and kept it in {target.parent}")
    return target


def _download(url: str, part: Path, size: int, progress: Progress | None) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "inklight"})  # noqa: S310 - a fixed https URL
    try:
        with urllib.request.urlopen(request, timeout=60) as response, part.open("wb") as out:  # noqa: S310
            if not str(response.geturl()).startswith("https://"):
                raise ShareError("The tunnel client's download was redirected to a non-https address")
            have = 0
            while have < size and (chunk := response.read(min(_CHUNK, size - have))):
                out.write(chunk)  # never more than the pinned size
                have += len(chunk)
                if progress:
                    progress(have, size)
    except (OSError, urllib.error.URLError) as exc:
        raise ShareError(
            f"Could not download Cloudflare's tunnel client ({type(exc).__name__}: {exc}). Check the network "
            "connection and try again."
        ) from exc


def _install(part: Path, target: Path, asset: Asset) -> None:
    handle, name = tempfile.mkstemp(prefix=target.name + ".", suffix=".new", dir=target.parent)
    os.close(handle)
    staged = Path(name)
    try:
        _write_program(part, staged, asset)
        staged.chmod(0o755)
        os.replace(staged, target)
    finally:
        staged.unlink(missing_ok=True)


def _write_program(part: Path, staged: Path, asset: Asset) -> None:
    if asset.name.endswith(".tgz"):
        with tarfile.open(part, "r:gz") as archive:
            members = [m for m in archive.getmembers() if m.isfile() and m.name.lstrip("./") == "cloudflared"]
            member = members[0] if members else None
            source = archive.extractfile(member) if member is not None else None
            if source is None:
                raise ShareError(f"{asset.name} does not hold the cloudflared program")
            with source, staged.open("wb") as out:
                shutil.copyfileobj(source, out)
    else:
        shutil.copyfile(part, staged)


class Tunnel:
    """One ``cloudflared`` quick tunnel to ``http://127.0.0.1:<port>``. Its output is kept (the last lines, for a
    failure message), never printed: it holds nothing secret, but it is noisy."""

    def __init__(self, client: Path, port: int) -> None:
        self.client = client
        self.port = port
        self.url: str | None = None
        self.lines: deque[str] = deque(maxlen=40)
        self._registered = threading.Event()
        self._found = threading.Event()
        self._process: subprocess.Popen[str] | None = None
        self._job: object = None
        self._config = client.parent / "empty-config.yml"  # so a ~/.cloudflared/config.yml is never used

    def start(self) -> None:
        self._config.write_text("", encoding="utf-8")
        env = {k: v for k, v in os.environ.items() if k in CLIENT_ENV}
        kwargs: dict[str, object] = {}
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
        else:
            kwargs["start_new_session"] = True  # Ctrl+C reaches Inklight, which stops the tunnel itself
        self._process = subprocess.Popen(  # noqa: S603 - a fixed, hash-checked program and fixed arguments
            [
                sys.executable,
                "-I",
                "-c",
                GUARD,
                str(self.client),
                "tunnel",
                "--config",
                str(self._config),
                "--no-autoupdate",
                "--grace-period",
                "1s",
                "--url",
                f"http://127.0.0.1:{self.port}",
            ],  # fmt: skip
            stdin=subprocess.PIPE,  # closed by stop(), or by the system when Inklight ends: the guard ends the client
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            **kwargs,  # type: ignore[call-overload]
        )
        if sys.platform == "win32":
            self._job = _kill_on_close(self._process)
        threading.Thread(target=self._read, name="inklight-tunnel-log", daemon=True).start()

    def _read(self) -> None:
        assert self._process is not None and self._process.stdout is not None  # noqa: S101 - set by start()
        for line in self._process.stdout:
            self.lines.append(line.rstrip())
            if self.url is None and (match := URL_PATTERN.search(line)):
                self.url = match.group(0) + "/"
                self._found.set()
            if READY_PATTERN.search(line):
                self._registered.set()
        self._found.set()
        self._registered.set()

    def wait_ready(self, timeout: float = 60.0) -> str:
        """The tunnel's public URL, once Cloudflare has registered the connection."""
        deadline = time.monotonic() + timeout
        for event in (self._found, self._registered):
            if not event.wait(max(0.0, deadline - time.monotonic())) or not self.alive() or self.url is None:
                raise ShareError(self._failure("Cloudflare did not open a quick tunnel"))
        return self.url  # type: ignore[return-value]

    def alive(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def _failure(self, what: str) -> str:
        tail = "\n".join(f"    {line}" for line in list(self.lines)[-8:]) or "    (no output)"
        return (
            f"{what}. Its last output:\n{tail}\nQuick tunnels need outbound HTTPS (TCP 443) or UDP 7844 to "
            "Cloudflare, and Cloudflare may limit them. Nothing was shared; try again in a minute."
        )

    def failure(self) -> str:
        return self._failure("The tunnel stopped")

    def stop(self) -> None:
        process = self._process
        if process is None:
            return
        if process.stdin is not None:
            with contextlib.suppress(OSError):
                process.stdin.close()  # the guard ends the client, then itself
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            if sys.platform == "win32":
                process.kill()  # the job object ends the client with it
            else:
                with contextlib.suppress(OSError):
                    os.killpg(process.pid, signal.SIGKILL)  # the guard and the client share a session
            process.wait(timeout=5)
        if process.stdout is not None:
            with contextlib.suppress(OSError):
                process.stdout.close()
        if self._job is not None:
            _close_handle(self._job)
            self._job = None


def check_public(url: str, timeout: float = 60.0, stop: Callable[[], bool] = lambda: False) -> bool:
    """The workspace page answers through the tunnel: the link printed is one that works, not just one received.

    The request goes to Cloudflare's edge (the address of trycloudflare.com) with TLS checked for the tunnel's own
    host name, so it takes the same path as a visitor's, without asking this machine's DNS about a name minutes old
    (a resolver that asked too early remembers "no such name" for a while)."""
    host = urlsplit(url).hostname or ""
    deadline = time.monotonic() + timeout
    problem = "no answer"
    good = 0
    while time.monotonic() < deadline:
        if stop():
            return False
        try:
            status, body = _edge_get(host, urlsplit(url).path or "/")
            if status == 200 and "Inklight" in body:
                good += 1
                if good >= CHECKS_IN_A_ROW:
                    return True
                time.sleep(1)
                continue
            problem = f"HTTP {status}"
        except (OSError, http.client.HTTPException) as exc:
            problem = f"{type(exc).__name__}: {exc}"
        good = 0
        time.sleep(2)
    raise ShareError(
        f"The tunnel opened {url}, but the workspace did not answer through it within {timeout:.0f} s ({problem}). "
        "Nothing is shared. Try again in a minute."
    )


class _EdgeConnection(http.client.HTTPSConnection):
    """HTTPS to ``host`` through a given Cloudflare edge address; the certificate is checked for ``host``."""

    def __init__(self, address: str, host: str) -> None:
        super().__init__(host, 443, timeout=10)
        self.address = address
        self.tls = ssl.create_default_context()

    def connect(self) -> None:
        raw = socket.create_connection((self.address, 443), self.timeout)
        self.sock = self.tls.wrap_socket(raw, server_hostname=self.host)


def _edge_get(host: str, path: str) -> tuple[int, str]:
    edge = socket.getaddrinfo(EDGE_NAME, 443, type=socket.SOCK_STREAM)
    last: Exception = OSError(f"no address for {EDGE_NAME}")
    for *_, sockaddr in edge:
        conn = _EdgeConnection(str(sockaddr[0]), host)
        try:
            conn.request("GET", path, headers={"User-Agent": "inklight-share-check"})
            response = conn.getresponse()
            return response.status, response.read(65536).decode("utf-8", "replace")
        except OSError as exc:
            last = exc
        finally:
            conn.close()
    raise last


def _kill_on_close(process: subprocess.Popen[str]) -> object:  # pragma: no cover - Windows only
    """A job object that ends the tunnel when Inklight's process ends, however it ends."""
    if sys.platform != "win32":
        return None
    import ctypes
    from ctypes import wintypes

    class Basic(ctypes.Structure):
        _fields_ = [
            ("a", ctypes.c_int64),
            ("b", ctypes.c_int64),
            ("flags", wintypes.DWORD),
            ("min_ws", ctypes.c_size_t),
            ("max_ws", ctypes.c_size_t),
            ("procs", wintypes.DWORD),
            ("affinity", ctypes.c_size_t),
            ("priority", wintypes.DWORD),
            ("scheduling", wintypes.DWORD),
        ]

    class Extended(ctypes.Structure):
        _fields_ = [
            ("basic", Basic),
            ("io", ctypes.c_uint64 * 6),
            ("proc_mem", ctypes.c_size_t),
            ("job_mem", ctypes.c_size_t),
            ("peak_proc", ctypes.c_size_t),
            ("peak_job", ctypes.c_size_t),
        ]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    job = kernel.CreateJobObjectW(None, None)
    if not job:
        return None
    info = Extended()
    info.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    ok = kernel.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info))  # extended limits
    if not ok or not kernel.AssignProcessToJobObject(job, int(process._handle)):  # type: ignore[attr-defined]
        kernel.CloseHandle(job)
        return None
    return job


def _close_handle(handle: object) -> None:  # pragma: no cover - Windows only
    if sys.platform != "win32":
        return
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32")
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle(handle)


__all__ = ["PROVIDER", "VERSION", "ShareError", "Tunnel", "asset_for", "check_public", "ensure_client"]
