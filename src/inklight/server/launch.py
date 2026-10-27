"""What ``inklight serve`` binds, accepts and tells the person starting it. Pure: decided and tested without a server.

Nothing here claims a server is reachable from elsewhere: a wildcard bind (0.0.0.0) is reported as the listening
address, never as a browser address, and a public address is only ever the one the owner gave (``--public-url``) or
the tunnel's own, once ``--share`` has checked it answers (``share.py``).
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from ..config import Settings
from ..errors import ConfigError
from .hosting import (
    ANY_ADDRESS,
    LOCAL_HOSTS,
    DemoLimits,
    Hosting,
    host_name,
    is_local_bind,
    machine_addresses,
    parse_public_url,
)

TOKEN_ENV = "INKLIGHT_SERVER_TOKEN"  # noqa: S105 - the variable's name, not a secret
SHARE_TOKEN_MIN = 16  # a shared workspace is on the internet: a short token could be guessed
MAKE_TOKEN = 'python -c "import secrets; print(secrets.token_urlsafe(24))"'  # noqa: S105 - a command that makes one


@dataclass(frozen=True)
class Launch:
    hosting: Hosting
    lines: list[tuple[str, str]]  # (label, text) for the start-up summary
    warnings: list[str] = field(default_factory=list)
    open_url: str | None = None  # a browser is opened here only for a local workspace on a machine with a display
    proxy_ips: str | None = None  # uvicorn's forwarded_allow_ips; None: forwarded headers are ignored


def plan(
    settings: Settings,
    *,
    host: str,
    port: int,
    public_url: str | None = None,
    allowed_hosts: list[str] | None = None,
    demo: bool = False,
    demo_dir: str | None = None,
    demo_minutes: int | None = None,
    no_token: bool = False,
    trusted_proxies: list[str] | None = None,
    open_browser: bool = True,
    env: dict[str, str] | None = None,
    addresses: list[str] | None = None,
    share_url: str | None = None,
) -> Launch:
    env = dict(os.environ) if env is None else env
    if share_url is not None:
        return _shared(settings, port=port, share_url=share_url, demo=demo, demo_dir=demo_dir,
                       demo_minutes=demo_minutes, allowed_hosts=allowed_hosts, env=env)  # fmt: skip
    token = env.get(TOKEN_ENV, "")
    public_url = public_url or env.get("INKLIGHT_PUBLIC_URL") or None
    local = is_local_bind(host)
    wildcard = host in ANY_ADDRESS

    hosts = set(LOCAL_HOSTS)
    hosts |= {host_name(h) for h in env.get("INKLIGHT_ALLOWED_HOSTS", "").split(",") if h.strip()}
    hosts |= {host_name(h) for h in allowed_hosts or []}
    url = None
    if public_url:
        url, public_host = parse_public_url(public_url)
        hosts.add(public_host)
    if not local and not wildcard:
        hosts.add(host_name(host))  # a specific address this machine listens on can be opened as it is

    mode: Literal["local", "private", "demo"] = "demo" if demo else ("local" if local else "private")
    if mode == "private" and not token and not no_token:
        raise ConfigError(
            f"Serving on {host} lets other machines connect to your library, so it needs an access token.\n"
            f"Make one with  {MAKE_TOKEN}\n"
            f"and start with  {TOKEN_ENV}=<token> inklight serve --host {host} ...\n"
            "Visitors enter the token when the page asks for it. (--no-token serves without one: only on a network "
            "you trust completely.)"
        )
    limits = None
    if demo:
        limits = DemoLimits() if demo_minutes is None else DemoLimits(minutes=demo_minutes)
    hosting = Hosting(
        mode=mode,
        token=token,
        allowed_hosts=frozenset(hosts),
        public_url=url,
        demo=limits,
        demo_dir=Path(demo_dir).expanduser() if demo_dir else None,
        ip_hosts=not local,  # opening the server by an IP address works, as with any web server
    )

    lines: list[tuple[str, str]] = []
    warnings: list[str] = []
    shown_host = f"[{host}]" if ":" in host else host
    if local:
        url = url or f"http://{shown_host}:{port}/"
        lines.append(("workspace", url))
    else:
        where = "every network interface of this machine" if wildcard else "this address only"
        lines.append(("listening", f"{shown_host}:{port} ({where})"))
        if wildcard:
            lines.append(("", f"{host} is where the server listens, not an address to open in a browser"))
        if url:
            lines.append(("workspace", f"{url}  (from --public-url; not checked from here)"))
        if wildcard:
            own = machine_addresses(ipv6=host == "::") if addresses is None else addresses
            links = [f"http://{a}:{port}/" for a in own]
            label = "also" if url else "workspace"
            for i, link in enumerate(links):
                lines.append((label if i == 0 else "", link + ("  (this machine's addresses; not checked from "
                                                                "elsewhere)" if i == 0 else "")))  # fmt: skip
            url = url or (links[0] if links else None)
            lines.append(("", f"or this machine's public IP address (a cloud server's), if TCP {port} reaches it"))
        elif not url:
            url = f"http://{shown_host}:{port}/"
            lines.append(("workspace", f"{url}  (not checked from here)"))
        names = sorted(h for h in hosts - LOCAL_HOSTS if not h[0].isdigit() and not h.startswith("["))
        lines.append(("hosts", ", ".join(["localhost", "any IP address", *names]) + "  (other host names are refused; "
                               "add a domain with --public-url or --allowed-host)"))  # fmt: skip
        lines.append(("network", f"other machines reach it only if TCP {port} is open inbound (the machine's "
                                 "firewall, the cloud's security group), or through a reverse proxy"))  # fmt: skip
    if mode == "demo":
        lim = limits or DemoLimits()
        folder = str(hosting.demo_dir) if hosting.demo_dir else "a new temporary folder, removed when the server stops"
        lines.append(
            (
                "mode",
                f"public demo: every visitor gets a temporary library of their own, deleted "
                f"{lim.minutes} minutes after it starts; the library at {settings.home} is not used",
            )
        )
        lines.append(("demo data", folder))
        lines.append(("limits", f"{lim.max_documents} documents per visitor, {lim.max_file_mb:g} MB and "
                                f"{lim.max_pages} pages each; one import is read at a time, {lim.queue} at most "
                                "waiting"))  # fmt: skip
        if token:
            lines.append(("access", f"a token is required ({TOKEN_ENV})"))
        if (url or "").startswith("https://") and not (trusted_proxies or env.get("INKLIGHT_TRUSTED_PROXIES")):
            warnings.append("Behind an HTTPS proxy, pass --trusted-proxy <its address>: otherwise every visitor seems "
                            "to come from the proxy, and the limit on new sessions per address applies to all of "
                            "them together.")  # fmt: skip
        if not local and not (url or "").startswith("https://"):
            warnings.append("A public demo should be served over HTTPS (a reverse proxy in front): without it, "
                            "visitors' files and session cookies cross the network unencrypted.")  # fmt: skip
    else:
        lines.append(("library", f"{settings.home}  (INKLIGHT_HOME to change)"))
        if mode == "private":
            lines.append(("access", "private workspace: everyone who can reach it shares this one library"))
            if token:
                lines.append(("token", f"required ({TOKEN_ENV}); visitors enter it when the page asks. It is not "
                                       "printed here."))  # fmt: skip
            else:
                warnings.append("Serving without a token (--no-token): anyone who can reach this port can read, "
                                "add and delete documents in your library.")  # fmt: skip
            if not (url or "").startswith("https://"):
                warnings.append("Without HTTPS (a reverse proxy in front), the token and documents cross the network "
                                "unencrypted.")  # fmt: skip
    proxies = [p.strip() for p in (trusted_proxies or env.get("INKLIGHT_TRUSTED_PROXIES", "").split(",")) if p.strip()]
    if proxies:
        lines.append(("proxy", f"X-Forwarded-For and -Proto are trusted from {', '.join(proxies)} only"))
    open_url = url if (open_browser and local and _has_display(env)) else None
    return Launch(hosting, lines, warnings, open_url, ",".join(proxies) or None)


def check_share(*, host: str, public_url: str | None, demo: bool, no_token: bool,
                trusted_proxies: list[str] | None, env: dict[str, str] | None = None) -> None:  # fmt: skip
    """Refuse a ``--share`` that would expose more than asked, before anything is downloaded or started."""
    env = dict(os.environ) if env is None else env
    if not is_local_bind(host):
        raise ConfigError("--share listens on 127.0.0.1 only (the tunnel connects to it there): leave out --host")
    if public_url or env.get("INKLIGHT_PUBLIC_URL"):
        raise ConfigError("--share makes its own public address: leave out --public-url (and INKLIGHT_PUBLIC_URL)")
    if trusted_proxies:
        raise ConfigError("--share trusts only the tunnel on this machine: leave out --trusted-proxy")
    if demo:
        return
    if no_token:
        raise ConfigError("--share puts your library on the internet, so it always needs a token: --no-token is "
                          "refused. To let anyone try Inklight, use --share --demo (a temporary library per "
                          "visitor).")  # fmt: skip
    token = env.get(TOKEN_ENV, "")
    if len(token) < SHARE_TOKEN_MIN:
        problem = "is too short" if token else "is not set"
        raise ConfigError(
            f"--share puts your library on the internet, so it needs an access token, and {TOKEN_ENV} {problem} "
            f"(at least {SHARE_TOKEN_MIN} characters).\n"
            f"Make one with  {MAKE_TOKEN}\n"
            f"and start with  {TOKEN_ENV}=<token> inklight serve --share\n"
            "Visitors enter the token when the page asks; it is never put in the link. To let anyone try Inklight "
            "without your library, use --share --demo."
        )


def _shared(settings: Settings, *, port: int, share_url: str, demo: bool, demo_dir: str | None,
            demo_minutes: int | None, allowed_hosts: list[str] | None, env: dict[str, str]) -> Launch:  # fmt: skip
    """``--share``: bound to 127.0.0.1, reached through a tunnel at ``share_url``. Accepted hosts: localhost and the
    tunnel's exact host name. The tunnel is the only proxy, and it connects from this machine."""
    url, tunnel_host = parse_public_url(share_url)
    hosts = set(LOCAL_HOSTS) | {tunnel_host} | {host_name(h) for h in allowed_hosts or []}
    limits = None
    if demo:
        limits = DemoLimits() if demo_minutes is None else DemoLimits(minutes=demo_minutes)
    token = env.get(TOKEN_ENV, "")
    hosting = Hosting(
        mode="demo" if demo else "private",
        token=token,
        allowed_hosts=frozenset(hosts),
        public_url=url,
        demo=limits,
        demo_dir=Path(demo_dir).expanduser() if demo_dir else None,
        stream_progress=False,  # a quick tunnel holds event streams back
    )
    lines: list[tuple[str, str]] = [
        ("public link", url),
        ("", "through a Cloudflare quick tunnel; the link changes every time and stops when this command stops"),
        ("listening", f"127.0.0.1:{port} (this machine only; the tunnel connects here)"),
        ("hosts", f"localhost and {tunnel_host} only"),
    ]
    if demo:
        lim = limits or DemoLimits()
        folder = str(hosting.demo_dir) if hosting.demo_dir else "a new temporary folder, removed when the server stops"
        lines.append(("mode", f"public demo: anyone with the link gets a temporary library of their own, deleted "
                              f"{lim.minutes} minutes after it starts; the library at {settings.home} is not "
                              "used"))  # fmt: skip
        lines.append(("demo data", folder))
        lines.append(("limits", f"{lim.max_documents} documents per visitor, {lim.max_file_mb:g} MB and "
                                f"{lim.max_pages} pages each; one import is read at a time, {lim.queue} at most "
                                "waiting"))  # fmt: skip
        if token:
            lines.append(("access", f"a token is required ({TOKEN_ENV})"))
    else:
        lines.append(("library", f"{settings.home}  (INKLIGHT_HOME to change)"))
        lines.append(("access", "private workspace: everyone with the link and the token shares this one library"))
        lines.append(("token", f"required ({TOKEN_ENV}); visitors enter it when the page asks. It is not in the "
                               "link and not printed here."))  # fmt: skip
    return Launch(hosting, lines, [], None, "127.0.0.1")


def _has_display(env: dict[str, str]) -> bool:
    """A browser can be opened: Windows and macOS, or Linux with a graphical session."""
    if sys.platform.startswith("linux"):
        return bool(env.get("DISPLAY") or env.get("WAYLAND_DISPLAY"))
    return True
