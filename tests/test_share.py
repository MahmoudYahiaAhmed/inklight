"""`inklight serve --share`: the pinned tunnel client, the tunnel's output, the link check, and what is accepted."""

import hashlib
import io
import socket
import tarfile
import time

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from inklight.cli import app as cli_app
from inklight.errors import ConfigError
from inklight.server import create_app, share, share_serve
from inklight.server.launch import check_share, plan
from inklight.server.share import Asset, ShareError, Tunnel, asset_for, check_public, ensure_client
from inklight.server.share_serve import Output, serve_shared

from .conftest import make_settings

TOKEN = "a-long-enough-test-token-1234"
LINK = "https://quiet-river-tests-only.trycloudflare.com/"


@pytest.fixture
def settings(tmp_path):
    return make_settings(tmp_path / "home")


@pytest.fixture
def cache(tmp_path, monkeypatch):
    folder = tmp_path / "cache"
    monkeypatch.setattr(share, "cache_root", lambda: folder)
    monkeypatch.delenv("INKLIGHT_OFFLINE", raising=False)
    monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
    return folder


def _asset(data: bytes, name="cloudflared-linux-amd64", binary: bytes | None = None) -> Asset:
    digest = hashlib.sha256(data).hexdigest()
    return Asset(name, len(data), digest, hashlib.sha256(binary if binary is not None else data).hexdigest())


class _Response(io.BytesIO):
    def __init__(self, data: bytes, url: str) -> None:
        super().__init__(data)
        self.url = url

    def geturl(self) -> str:
        return self.url


def _serve(monkeypatch, data: bytes, calls: list | None = None, final_url: str | None = None):
    def urlopen(request, timeout=None):
        if calls is not None:
            calls.append(request.full_url)
        return _Response(data, final_url or request.full_url)

    monkeypatch.setattr(share.urllib.request, "urlopen", urlopen)


# -- the pinned client ------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("system", "machine", "name"),
    [
        ("Linux", "x86_64", "cloudflared-linux-amd64"),
        ("Linux", "aarch64", "cloudflared-linux-arm64"),
        ("Darwin", "arm64", "cloudflared-darwin-arm64.tgz"),
        ("Darwin", "x86_64", "cloudflared-darwin-amd64.tgz"),
        ("Windows", "AMD64", "cloudflared-windows-amd64.exe"),
    ],
)
def test_each_supported_platform_has_one_pinned_release_file(system, machine, name):
    asset = asset_for(system, machine)
    assert asset.name == name and len(asset.sha256) == 64 and asset.size > 10_000_000


def test_an_unsupported_platform_is_named_not_guessed():
    with pytest.raises(ShareError, match="no tunnel client for linux riscv64"):
        asset_for("Linux", "riscv64")


def test_every_pinned_url_is_the_pinned_version_on_https():
    assert share.RELEASES.startswith("https://github.com/cloudflare/cloudflared/")
    assert share.VERSION == "2026.10.0"


def test_download_is_checked_installed_and_then_reused(cache, monkeypatch):
    data = b"#!/bin/sh\necho tunnel\n"
    calls: list = []
    _serve(monkeypatch, data, calls)
    said: list = []
    path = ensure_client(_asset(data), say=said.append)
    assert path.read_bytes() == data and path.parent.name == f"cloudflared-{share.VERSION}"
    assert calls == [f"{share.RELEASES}/{share.VERSION}/cloudflared-linux-amd64"]
    assert "Downloading Cloudflare's tunnel client" in said[0] and "SHA-256" in said[-1]
    assert ensure_client(_asset(data), say=said.append) == path and len(calls) == 1  # verified copy: no download


def test_a_download_that_does_not_match_its_hash_is_deleted_and_never_run(cache, monkeypatch):
    _serve(monkeypatch, b"something else")
    with pytest.raises(ShareError, match="does not match its pinned SHA-256"):
        ensure_client(_asset(b"the real program"))
    assert not any(p.is_file() for p in cache.rglob("*") if p.suffix != ".yml")


def test_an_altered_cached_client_is_fetched_again(cache, monkeypatch):
    data = b"real"
    _serve(monkeypatch, data)
    path = ensure_client(_asset(data))
    path.write_bytes(b"tampered")
    calls: list = []
    _serve(monkeypatch, data, calls)
    assert ensure_client(_asset(data)).read_bytes() == data and len(calls) == 1


def test_a_redirect_away_from_https_is_refused(cache, monkeypatch):
    data = b"x"
    _serve(monkeypatch, data, final_url="http://example.org/cloudflared")
    with pytest.raises(ShareError, match="non-https"):
        ensure_client(_asset(data))


def test_nothing_is_downloaded_offline(cache, monkeypatch):
    monkeypatch.setenv("INKLIGHT_OFFLINE", "1")
    _serve(monkeypatch, b"x", calls := [])
    with pytest.raises(ShareError, match="downloads are off"):
        ensure_client(_asset(b"x"))
    assert calls == []


def test_the_macos_archive_is_checked_then_its_program_checked(cache, monkeypatch):
    program = b"macho program"
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        info = tarfile.TarInfo("cloudflared")
        info.size = len(program)
        archive.addfile(info, io.BytesIO(program))
    data = buffer.getvalue()
    _serve(monkeypatch, data)
    path = ensure_client(_asset(data, "cloudflared-darwin-arm64.tgz", binary=program))
    assert path.read_bytes() == program


def test_a_network_failure_says_what_to_do(cache, monkeypatch):
    def urlopen(request, timeout=None):
        raise OSError("no route")

    monkeypatch.setattr(share.urllib.request, "urlopen", urlopen)
    with pytest.raises(ShareError, match="Could not download Cloudflare's tunnel client"):
        ensure_client(_asset(b"x"))


# -- the tunnel's output ---------------------------------------------------------------------------------------


class _Process:
    def __init__(self, lines: list[str], running: bool = True) -> None:
        self.stdout = iter(line + "\n" for line in lines)
        self.running = running

    def poll(self):
        return None if self.running else 1


def _tunnel(tmp_path, lines, running=True) -> Tunnel:
    tunnel = Tunnel(tmp_path / "cloudflared", 8765)
    tunnel._process = _Process(lines, running)  # type: ignore[assignment]
    tunnel._read()
    return tunnel


def test_the_link_is_read_from_the_tunnels_output_once_registered(tmp_path):
    tunnel = _tunnel(tmp_path, [
        "INF Requesting new quick Tunnel on trycloudflare.com...",
        "INF |  https://quiet-river-tests-only.trycloudflare.com                                 |",
        "INF Registered tunnel connection connIndex=0 location=fra08 protocol=quic",
    ])  # fmt: skip
    assert tunnel.wait_ready(timeout=1) == LINK


def test_a_tunnel_that_gives_no_link_fails_with_its_last_output(tmp_path):
    tunnel = _tunnel(tmp_path, ["ERR failed to request quick Tunnel: 429 Too Many Requests"], running=False)
    with pytest.raises(ShareError) as err:
        tunnel.wait_ready(timeout=1)
    assert "did not open a quick tunnel" in str(err.value) and "429 Too Many Requests" in str(err.value)
    assert "Nothing was shared" in str(err.value)


def test_only_a_trycloudflare_https_link_is_taken(tmp_path):
    tunnel = _tunnel(tmp_path, ["see https://evil.example.com and http://plain.trycloudflare.com"], running=False)
    assert tunnel.url is None


# -- the link check --------------------------------------------------------------------------------------------


def test_the_link_is_printed_only_after_answering_several_times_in_a_row(monkeypatch):
    answers = iter([(530, ""), (200, "<title>Inklight</title>"), (530, "")] + [(200, "Inklight")] * 5)
    seen: list = []

    def edge_get(host, path):
        seen.append((host, path))
        return next(answers)

    monkeypatch.setattr(share, "_edge_get", edge_get)
    monkeypatch.setattr(share.time, "sleep", lambda s: None)
    check_public(LINK, timeout=30)
    assert len(seen) == 8 and seen[0] == ("quiet-river-tests-only.trycloudflare.com", "/")


def test_a_link_that_never_answers_is_not_printed(monkeypatch):
    monkeypatch.setattr(share, "_edge_get", lambda host, path: (530, "error code: 1033"))
    clock = iter(range(0, 1000, 10))
    monkeypatch.setattr(share.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(share.time, "sleep", lambda s: None)
    with pytest.raises(ShareError, match=r"did not answer through it .* \(HTTP 530\)"):
        check_public(LINK, timeout=60)


# -- what --share accepts --------------------------------------------------------------------------------------


def test_share_needs_a_real_token_for_a_private_workspace():
    for env, problem in (({}, "is not set"), ({"INKLIGHT_SERVER_TOKEN": "short"}, "is too short")):
        with pytest.raises(ConfigError) as err:
            check_share(host="127.0.0.1", public_url=None, demo=False, no_token=False, trusted_proxies=None, env=env)
        assert problem in str(err.value) and "--share --demo" in str(err.value)
    check_share(host="127.0.0.1", public_url=None, demo=False, no_token=False, trusted_proxies=None,
                env={"INKLIGHT_SERVER_TOKEN": TOKEN})  # fmt: skip
    check_share(host="127.0.0.1", public_url=None, demo=True, no_token=False, trusted_proxies=None, env={})


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"host": "0.0.0.0"}, "listens on 127.0.0.1 only"),
        ({"public_url": "https://docs.example.org/"}, "leave out --public-url"),
        ({"trusted_proxies": ["10.0.0.1"]}, "leave out --trusted-proxy"),
        ({"no_token": True}, "--no-token is refused"),
    ],
)
def test_share_refuses_options_that_would_expose_more(kwargs, message):
    base = {"host": "127.0.0.1", "public_url": None, "demo": False, "no_token": False, "trusted_proxies": None}
    with pytest.raises(ConfigError, match=message):
        check_share(**{**base, **kwargs}, env={"INKLIGHT_SERVER_TOKEN": TOKEN})


def test_a_shared_workspace_accepts_the_tunnels_exact_host_only(settings):
    launch = plan(settings, host="127.0.0.1", port=8765, share_url=LINK, env={"INKLIGHT_SERVER_TOKEN": TOKEN})
    hosting = launch.hosting
    assert hosting.mode == "private" and hosting.token == TOKEN and hosting.public_url == LINK
    assert "quiet-river-tests-only.trycloudflare.com" in hosting.allowed_hosts and not hosting.ip_hosts
    assert not hosting.stream_progress and launch.proxy_ips == "127.0.0.1" and launch.open_url is None
    text = "\n".join(f"{label} {line}" for label, line in launch.lines)
    assert f"public link {LINK}" in text and "127.0.0.1:8765 (this machine only" in text and TOKEN not in text
    client = TestClient(create_app(settings, hosting=hosting), base_url=LINK.rstrip("/"))
    token = {"X-Inklight-Token": TOKEN}
    assert client.get("/api/status", headers=token).json()["hosting"]["stream_progress"] is False
    client.cookies.clear()  # the first good request set the access cookie
    assert client.get("/api/status").status_code == 401
    for other in ("other-words-here.trycloudflare.com", "trycloudflare.com", "203.0.113.7"):
        assert client.get("/api/status", headers={**token, "host": other}).status_code == 403, other


def test_a_shared_demo_needs_no_token_and_keeps_the_owners_library_out(settings):
    launch = plan(settings, host="127.0.0.1", port=8765, share_url=LINK, demo=True, env={})
    assert launch.hosting.mode == "demo" and not launch.hosting.token and launch.proxy_ips == "127.0.0.1"
    assert "is not used" in "\n".join(text for _, text in launch.lines)


def test_normal_serve_still_streams_progress(settings):
    launch = plan(settings, host="127.0.0.1", port=8765, env={})
    assert launch.hosting.stream_progress and launch.hosting.public_url is None


def test_share_without_a_token_fails_before_downloading_anything(monkeypatch, tmp_path):
    monkeypatch.delenv("INKLIGHT_SERVER_TOKEN", raising=False)
    monkeypatch.setenv("INKLIGHT_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(share, "ensure_client", lambda **_: pytest.fail("nothing may be downloaded"))
    result = CliRunner().invoke(cli_app, ["serve", "--share"])
    assert result.exit_code == 1 and "INKLIGHT_SERVER_TOKEN" in result.output


def test_a_port_in_use_fails_before_the_tunnel(settings, monkeypatch):
    monkeypatch.setattr(share_serve, "ensure_client", lambda **_: pytest.fail("nothing may be downloaded"))
    busy = socket.socket()
    busy.bind(("127.0.0.1", 0))
    busy.listen()
    failures: list = []
    out = Output(say=lambda t: None, line=lambda a, b: None, fail=failures.append)
    try:
        ok = serve_shared(settings, out, port=busy.getsockname()[1], demo=False, demo_dir=None, demo_minutes=None,
                          allowed_hosts=None)  # fmt: skip
    finally:
        busy.close()
    assert not ok and "is in use" in failures[0]


def test_serve_help_describes_share():
    import re

    result = CliRunner().invoke(cli_app, ["serve", "--help"], env={"COLUMNS": "200", "NO_COLOR": "1", "TERM": "dumb"})
    text = re.sub(r"\x1b\[[0-9;]*m", "", result.output)  # CI forces colour; the codes split option names
    assert "--share" in text and "Cloudflare" in text


def test_the_page_asks_for_progress_when_the_server_says_streams_are_held_back():
    from pathlib import Path

    static = Path(create_app.__code__.co_filename).parent / "static" / "js"
    library = (static / "library.js").read_text(encoding="utf-8")
    main = (static / "main.js").read_text(encoding="utf-8")
    assert "store.pollProgress" in library and "STREAM_WAIT_MS" in library  # also when a proxy holds a stream back
    assert "stream_progress === false" in main


def test_the_guard_ends_the_client_when_inklights_pipe_closes():
    import subprocess
    import sys

    guard = subprocess.Popen(
        [sys.executable, "-I", "-c", share.GUARD, sys.executable, "-c", "import time; time.sleep(120)"],
        stdin=subprocess.PIPE,
    )
    time.sleep(1)
    assert guard.poll() is None
    guard.stdin.close()  # what the system does when Inklight ends, however it ends
    assert guard.wait(timeout=20) is not None


def test_the_client_gets_neither_the_token_nor_other_credentials():
    assert "INKLIGHT_SERVER_TOKEN" not in share.CLIENT_ENV and "PATH" in share.CLIENT_ENV
    assert not any("TOKEN" in k or "KEY" in k or "SECRET" in k for k in share.CLIENT_ENV)


def test_cloudflares_api_address_is_never_taken_for_the_link(tmp_path):
    tunnel = _tunnel(tmp_path, [
        'ERR Error unmarshaling QuickTunnel response url="https://api.trycloudflare.com/tunnel"',
        "INF |  https://quiet-river-tests-only.trycloudflare.com  |",
    ], running=False)  # fmt: skip
    assert tunnel.url == LINK


def test_the_link_check_stops_when_the_server_does(monkeypatch):
    monkeypatch.setattr(share, "_edge_get", lambda host, path: pytest.fail("no request after stopping"))
    assert check_public(LINK, stop=lambda: True) is False
