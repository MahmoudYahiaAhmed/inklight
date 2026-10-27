"""What ``inklight serve`` binds, accepts and tells the person starting it. Pure: decided and tested without a server.

Nothing here claims a server is reachable from elsewhere: a wildcard bind (0.0.0.0) is reported as the listening
address, never as a browser address, and a public address is only ever the one the owner gave (``--public-url``).
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
) -> Launch:
    env = dict(os.environ) if env is None else env
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


def _has_display(env: dict[str, str]) -> bool:
    """A browser can be opened: Windows and macOS, or Linux with a graphical session."""
    if sys.platform.startswith("linux"):
        return bool(env.get("DISPLAY") or env.get("WAYLAND_DISPLAY"))
    return True
