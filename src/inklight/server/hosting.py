"""How the workspace is served: on this computer, as a private workspace on a network, or as a public demo.

* **local** (the default): bound to 127.0.0.1; only this computer can reach it.
* **private**: bound to a network address for one person or a trusted team. Everyone shares one library, so a token
  is required (``INKLIGHT_SERVER_TOKEN``) unless the owner explicitly turns that off.
* **demo**: a public demo. Each visitor gets a temporary library of their own (``demo.py``); nobody reaches the
  owner's library.

The Host-header check is never switched off. On a network bind a browser may use any IP address of the server
(``http://203.0.113.7:8765``): a DNS-rebinding attack always arrives with a domain name, never an IP address. A domain
name (the server's own, or a reverse proxy's) must be listed, through ``--public-url`` or ``--allowed-host``.
"""

from __future__ import annotations

import ipaddress
import os
import socket
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from ..errors import ConfigError

LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "[::1]", "::1"})
LOCAL_BINDS = frozenset({"127.0.0.1", "localhost", "::1"})
ANY_ADDRESS = frozenset({"0.0.0.0", "::"})  # noqa: S104 - names of the wildcard addresses, compared, never bound here


@dataclass(frozen=True)
class DemoLimits:
    """What one public demo server allows. Every visitor's files count against the shared queue and OCR slot."""

    minutes: int = 60  # a session, its files and everything read from them are deleted this long after it starts
    max_sessions: int = 40
    sessions_per_address_per_hour: int = 12
    max_documents: int = 15  # per session
    max_file_mb: float = 10.0
    max_pages: int = 15  # pages read per document
    max_files_per_upload: int = 5
    queue: int = 6  # imports waiting or running, across every visitor; one is read at a time
    requests_per_minute: int = 90  # per session, for requests that change something
    reads_per_minute: int = 600  # per session, every request (the page polls while it imports)
    busy_slots: int = 2  # page renders, questions and field extraction running at once, across every visitor


@dataclass(frozen=True)
class Hosting:
    mode: Literal["local", "private", "demo"] = "local"
    token: str = field(default="", repr=False)  # never in a log or traceback
    allowed_hosts: frozenset[str] = LOCAL_HOSTS
    public_url: str | None = None
    demo: DemoLimits | None = None
    demo_dir: Path | None = None  # None: a new temporary folder, removed when the server stops
    ip_hosts: bool = False  # on a network bind: any IP address is an accepted host (opening the server by its IP)
    stream_progress: bool = True  # False behind a tunnel that holds event streams back: the page asks instead
    extra: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_env(cls) -> Hosting:
        """The settings an app gets when its caller passes none: local, with the environment's token and hosts."""
        extra = {h.strip() for h in os.environ.get("INKLIGHT_ALLOWED_HOSTS", "").split(",") if h.strip()}
        return cls(token=os.environ.get("INKLIGHT_SERVER_TOKEN", ""), allowed_hosts=LOCAL_HOSTS | extra)


def is_local_bind(host: str) -> bool:
    return host in LOCAL_BINDS


def is_ip_host(host: str) -> bool:
    """A Host header's name part that is an IP address (IPv6 in brackets), not a domain name."""
    if host.startswith("[") != host.endswith("]"):
        return False
    try:
        ipaddress.ip_address(host[1:-1] if host.startswith("[") else host)
    except ValueError:
        return False
    return True


def machine_addresses(ipv6: bool = False) -> list[str]:
    """This machine's own addresses that other machines can use, the one on the default route first. Nothing is sent:
    connecting a UDP socket only picks the route. A server behind NAT (a cloud VM) does not see its public address."""
    found: list[str] = []
    for family, probe in ((socket.AF_INET, "192.0.2.1"), *(((socket.AF_INET6, "2001:db8::1"),) if ipv6 else ())):
        try:
            with socket.socket(family, socket.SOCK_DGRAM) as s:
                s.connect((probe, 9))
                found.append(s.getsockname()[0])
        except OSError:
            pass
    try:
        infos = socket.getaddrinfo(socket.gethostname(), None)
    except OSError:
        infos = []
    found += [str(info[4][0]) for info in infos]
    usable = []
    for raw in found:
        try:
            ip = ipaddress.ip_address(raw.split("%")[0])
        except ValueError:
            continue
        if ip.is_loopback or ip.is_link_local or ip.is_unspecified or (ip.version == 6 and not ipv6):
            continue
        text = f"[{ip}]" if ip.version == 6 else str(ip)
        if text not in usable:
            usable.append(text)
    return usable


def parse_public_url(url: str) -> tuple[str, str]:
    """``(url with a trailing slash, its host name)`` for the address visitors open: http(s), a host, an optional
    path (a reverse proxy's prefix), and nothing else."""
    parts = urlsplit(url.strip())
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ConfigError(f"--public-url must be an http:// or https:// address with a host name, not {url!r}")
    if parts.query or parts.fragment or parts.username or parts.password:
        raise ConfigError("--public-url must not contain a query, a fragment or a user name")
    if parts.hostname in ANY_ADDRESS:
        raise ConfigError(
            "0.0.0.0 is where the server listens, not an address a browser can open: give the "
            "machine's IP address or domain name"
        )
    path = parts.path if parts.path.endswith("/") else parts.path + "/"
    host = parts.hostname
    with_brackets = f"[{host}]" if _is_ipv6(host) else host
    netloc = with_brackets + (f":{parts.port}" if parts.port else "")
    return f"{parts.scheme}://{netloc}{path}", with_brackets.lower()


def host_name(raw: str) -> str:
    """A host name as given to --allowed-host (no scheme, no port, no path)."""
    value = raw.strip().lower()
    if not value or any(c in value for c in "/ @") or value in ANY_ADDRESS:
        raise ConfigError(f"--allowed-host takes a host name or IP address, such as docs.example.org, not {raw!r}")
    if value.startswith("["):
        return value.split("]")[0] + "]"
    if _is_ipv6(value):
        return f"[{value}]"
    return value.rsplit(":", 1)[0] if value.count(":") == 1 else value


def _is_ipv6(host: str) -> bool:
    try:
        return isinstance(ipaddress.ip_address(host.strip("[]")), ipaddress.IPv6Address)
    except ValueError:
        return False
