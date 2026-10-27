"""Running ``inklight serve --share``: the order of things, and stopping both halves together.

Bind 127.0.0.1 first (a port in use fails before anything is downloaded or opened), fetch the pinned tunnel client,
open the tunnel, start the workspace for the tunnel's exact host name, check the link answers through Cloudflare, and
only then print it. Ctrl+C, the tunnel failing, or the check failing stops the server and the tunnel; the tunnel also
ends if this process is killed outright: it runs under a small guard process that ends it when this process's end
of a pipe closes, which the system does however this process ends (and a job object on Windows ends both).
"""

from __future__ import annotations

import contextlib
import signal
import socket
import threading
import time
from collections.abc import Callable, Generator
from dataclasses import dataclass

import uvicorn
from uvicorn.server import HANDLED_SIGNALS

from ..config import Settings
from ..errors import InklightError
from .launch import plan
from .share import PROVIDER, ShareError, Tunnel, check_public, ensure_client


@dataclass(frozen=True)
class Output:
    say: Callable[[str], None]  # progress notes
    line: Callable[[str, str], None]  # (label, text) of the summary
    fail: Callable[[str], None]  # an error, on stderr
    progress: Callable[[int, int], None] | None = None  # bytes of the client downloaded, of total


class _Server(uvicorn.Server):
    """uvicorn's server, except that a signal is not raised again after shutting down: that would end the process
    before the tunnel is stopped."""

    @contextlib.contextmanager
    def capture_signals(self) -> Generator[None, None, None]:
        if threading.current_thread() is not threading.main_thread():
            yield
            return
        # A closed terminal (SIGHUP) stops it the same way, so the tunnel is stopped too.
        signals = (*HANDLED_SIGNALS, *((signal.SIGHUP,) if hasattr(signal, "SIGHUP") else ()))
        original = {sig: signal.signal(sig, self.handle_exit) for sig in signals}
        try:
            yield
        finally:
            for sig, handler in original.items():
                signal.signal(sig, handler)


def serve_shared(
    settings: Settings,
    out: Output,
    *,
    port: int,
    demo: bool,
    demo_dir: str | None,
    demo_minutes: int | None,
    allowed_hosts: list[str] | None,
) -> bool:
    """Serve until interrupted. True when it stopped because it was asked to, False on a failure (already said)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", port))
    except OSError as exc:
        sock.close()
        out.fail(f"Port {port} on 127.0.0.1 is in use ({exc.strerror}): pass another --port")
        return False
    port = sock.getsockname()[1]  # --port 0: the one the system chose
    tunnel: Tunnel | None = None
    watcher: threading.Thread | None = None
    failed = threading.Event()
    try:
        client = ensure_client(say=out.say, progress=out.progress)
        out.say(f"Opening a public link: {PROVIDER}. Cloudflare carries the traffic; no account is used.")
        tunnel = Tunnel(client, port)
        tunnel.start()
        share_url = tunnel.wait_ready()
        launch = plan(settings, host="127.0.0.1", port=port, demo=demo, demo_dir=demo_dir, demo_minutes=demo_minutes,
                      allowed_hosts=allowed_hosts, share_url=share_url)  # fmt: skip
        from . import create_app

        server = _Server(
            uvicorn.Config(
                create_app(settings, hosting=launch.hosting),
                log_level="warning",
                proxy_headers=True,
                forwarded_allow_ips=launch.proxy_ips,  # the tunnel, on this machine: the visitor's address counts
            )
        )
        watcher = threading.Thread(
            target=_watch, args=(server, tunnel, share_url, launch.lines, out, failed), daemon=True
        )
        watcher.start()
        server.run(sockets=[sock])
    except InklightError as exc:
        out.fail(str(exc))
        failed.set()
    finally:
        if watcher is not None:
            watcher.join(timeout=15)  # it notices the server stopped within a few seconds
        if tunnel is not None:
            tunnel.stop()
        sock.close()
    if not failed.is_set():
        out.say("Stopped the server and the tunnel; the link no longer works.")
    return not failed.is_set()


def _watch(server: _Server, tunnel: Tunnel, url: str, lines: list[tuple[str, str]], out: Output,
           failed: threading.Event) -> None:  # fmt: skip
    """Print the link once the server is up and the link answers through the tunnel; stop the server if the tunnel
    dies."""
    while not server.started and not server.should_exit:
        time.sleep(0.1)
    if server.should_exit:
        return
    try:
        out.say("Server ready; checking the link through Cloudflare …")
        if not check_public(url, stop=lambda: server.should_exit):
            return  # stopped meanwhile
    except ShareError as exc:
        out.fail(str(exc))
        failed.set()
        server.should_exit = True
        return
    for label, text in lines:
        out.line(label, text)
    out.line("", "Press Ctrl+C to stop the server and the tunnel.")
    while not server.should_exit:
        if not tunnel.alive():
            out.fail(tunnel.failure() + " The server is stopping.")
            failed.set()
            server.should_exit = True
            return
        time.sleep(1)
