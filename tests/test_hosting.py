"""Serving beyond this computer: what `inklight serve` binds, accepts and says, and the private workspace's token."""

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from inklight.cli import app as cli_app
from inklight.errors import ConfigError
from inklight.server import create_app
from inklight.server.hosting import Hosting, host_name, parse_public_url
from inklight.server.launch import plan

from .conftest import make_settings

H = {"X-Inklight": "1"}


@pytest.fixture
def settings(tmp_path):
    return make_settings(tmp_path / "home")


def _text(launch):
    return "\n".join(f"{label} {text}" for label, text in launch.lines)


def test_local_default_is_unchanged(settings):
    launch = plan(settings, host="127.0.0.1", port=8765, env={})
    assert launch.lines[0] == ("workspace", "http://127.0.0.1:8765/")
    assert launch.hosting.mode == "local" and not launch.hosting.token
    assert "library" in _text(launch) and not launch.warnings
    assert launch.proxy_ips is None  # forwarded headers ignored unless a proxy is named


def test_a_network_bind_needs_a_token(settings):
    with pytest.raises(ConfigError) as err:
        plan(settings, host="0.0.0.0", port=8765, env={})
    assert "INKLIGHT_SERVER_TOKEN" in str(err.value) and "secrets.token_urlsafe" in str(err.value)
    launch = plan(settings, host="0.0.0.0", port=8765, no_token=True, env={})
    assert launch.hosting.mode == "private" and any("without a token" in w for w in launch.warnings)


def test_wildcard_bind_is_reported_as_a_bind_address_not_a_url(settings):
    launch = plan(
        settings, host="0.0.0.0", port=8765, public_url="http://203.0.113.7:8765", env={"INKLIGHT_SERVER_TOKEN": "s3"}
    )
    text = _text(launch)
    assert "listening 0.0.0.0:8765 (every network interface" in text
    assert "not an address to open in a browser" in text
    assert "workspace http://203.0.113.7:8765/  (from --public-url; not checked from here)" in text
    assert "TCP 8765 is open inbound" in text and "http://127.0.0.1" not in text
    assert "203.0.113.7" in launch.hosting.allowed_hosts and launch.hosting.token == "s3"
    assert "s3" not in text  # the token is never printed
    assert launch.open_url is None  # never a browser for a network bind
    assert any("HTTPS" in w for w in launch.warnings)


def test_wildcard_without_public_url_says_who_can_connect(settings):
    text = _text(plan(settings, host="0.0.0.0", port=9000, env={"INKLIGHT_SERVER_TOKEN": "x"}))
    assert "http://localhost:9000/ on this machine" in text and "--public-url" in text


def test_public_url_rules():
    assert parse_public_url("https://docs.example.org/inklight") == (
        "https://docs.example.org/inklight/",
        "docs.example.org",
    )
    assert parse_public_url("http://[2001:db8::1]:8765") == ("http://[2001:db8::1]:8765/", "[2001:db8::1]")
    for bad in ("http://0.0.0.0:8765", "ftp://x.org", "https://x.org/?a=1", "x.org", "https://u:p@x.org"):
        with pytest.raises(ConfigError):
            parse_public_url(bad)
    assert host_name("Docs.Example.org:443") == "docs.example.org"
    with pytest.raises(ConfigError):
        host_name("https://docs.example.org")


def test_no_browser_on_a_headless_linux(settings, monkeypatch):
    monkeypatch.setattr("sys.platform", "linux")
    assert plan(settings, host="127.0.0.1", port=8765, env={}).open_url is None
    assert plan(settings, host="127.0.0.1", port=8765, env={"DISPLAY": ":0"}).open_url == "http://127.0.0.1:8765/"


def test_trusted_proxy_is_explicit(settings):
    launch = plan(settings, host="127.0.0.1", port=8765, trusted_proxies=["127.0.0.1"], env={})
    assert launch.proxy_ips == "127.0.0.1" and "trusted from 127.0.0.1 only" in _text(launch)


def test_cli_refuses_a_network_bind_without_a_token(tmp_path, monkeypatch):
    monkeypatch.setenv("INKLIGHT_HOME", str(tmp_path / "home"))
    monkeypatch.setattr("uvicorn.run", lambda *a, **k: pytest.fail("must not start"))
    result = CliRunner().invoke(cli_app, ["serve", "--host", "0.0.0.0", "--no-open"])
    assert result.exit_code != 0 and "access token" in result.output


def test_cli_serves_a_private_workspace_without_printing_the_token(tmp_path, monkeypatch):
    monkeypatch.setenv("INKLIGHT_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("INKLIGHT_SERVER_TOKEN", "very-secret-token-123")
    started = {}
    monkeypatch.setattr("uvicorn.run", lambda app, **kw: started.update(kw))
    result = CliRunner().invoke(
        cli_app,
        ["serve", "--host", "0.0.0.0", "--public-url", "https://docs.example.org/inklight/", "--trusted-proxy",
         "127.0.0.1"],
    )  # fmt: skip
    assert result.exit_code == 0, result.output
    assert "very-secret-token-123" not in result.output
    assert "https://docs.example.org/inklight/" in result.output and "0.0.0.0:8765" in result.output
    assert started["host"] == "0.0.0.0" and started["proxy_headers"] and started["forwarded_allow_ips"] == "127.0.0.1"


def test_public_url_host_is_accepted_and_others_refused(settings):
    hosting = Hosting(mode="private", token="t", allowed_hosts=frozenset({"203.0.113.7"}))
    c = TestClient(create_app(settings, hosting=hosting), base_url="http://203.0.113.7:8765")
    assert c.get("/api/status", headers={"X-Inklight-Token": "t"}).status_code == 200
    assert c.get("/", headers={"host": "evil.example"}).status_code == 403
    status = c.get("/api/status").json()["hosting"]
    assert status == {"mode": "private", "shared_library": True}


def test_private_workspace_rejects_requests_without_the_token(settings):
    hosting = Hosting(mode="private", token="t", allowed_hosts=frozenset({"testserver"}))
    c = TestClient(create_app(settings, hosting=hosting))
    for method, path in (("get", "/api/documents"), ("get", "/api/jobs"), ("get", "/api/reviews"),
                         ("post", "/api/search")):  # fmt: skip
        assert getattr(c, method)(path, headers=H).status_code == 401, path
    assert c.get("/").status_code == 200  # the page itself loads, then asks for the token


def test_workspace_uses_relative_urls_so_a_proxy_prefix_works():
    """Every request the page makes is relative to the page, so /inklight/ behind a proxy reaches /inklight/api/..."""
    from pathlib import Path

    static = Path(__file__).resolve().parents[1] / "src" / "inklight" / "server" / "static"
    html = (static / "index.html").read_text(encoding="utf-8")
    assert 'src="/' not in html and 'href="/' not in html
    for js in (static / "js").glob("*.js"):
        text = js.read_text(encoding="utf-8")
        for needle in ('fetch("/', "fetch('/", 'EventSource("/', "EventSource(`/", 'xhr.open("POST", "/'):
            assert needle not in text, (js.name, needle)
        for line in text.splitlines():
            if "EventSource(" in line or ".src = " in line and "/api/" in line or "xhr.open(" in line:
                assert "withToken(" in line or "path" in line, (js.name, line)
