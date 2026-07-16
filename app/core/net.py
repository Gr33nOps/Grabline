"""Networking helpers: a central httpx client factory that understands every
proxy scheme, proxy-URL validation, and a best-effort VPN check.

httpx speaks HTTP, HTTPS and SOCKS5 (with ``socksio``) natively; SOCKS4/4a it
does not, so those route through an httpx-socks transport. Every httpx client
in the app is built here so one proxy setting covers all of them.
"""

from __future__ import annotations

import socket
from typing import Any
from urllib.parse import urlsplit

import httpx

#: Proxy schemes Grabline accepts.
PROXY_SCHEMES = ("http", "https", "socks5", "socks5h", "socks4", "socks4a")
_SOCKS4 = ("socks4", "socks4a")


def validate_proxy(url: str) -> str | None:
    """None if ``url`` is a usable proxy address (or blank), else a message."""
    url = url.strip()
    if not url:
        return None
    parts = urlsplit(url)
    if parts.scheme not in PROXY_SCHEMES:
        return f"Proxy must start with one of: {', '.join(s + '://' for s in PROXY_SCHEMES)}"
    if not parts.hostname:
        return "The proxy address needs a host, e.g. socks5://127.0.0.1:1080"
    return None


def _client_kwargs(proxy: str | None) -> dict[str, Any]:
    """httpx.Client kwargs that apply ``proxy``. SOCKS4/4a get an httpx-socks
    transport; everything else uses httpx's own proxy support."""
    if not proxy:
        return {}
    scheme = urlsplit(proxy).scheme
    if scheme in _SOCKS4:
        from httpx_socks import SyncProxyTransport

        return {"transport": SyncProxyTransport.from_url(proxy)}
    return {"proxy": proxy}


def build_client(
    *,
    proxy: str | None = None,
    bypass_hosts: tuple[str, ...] = (),
    user_agent: str | None = None,
    **kwargs: Any,
) -> httpx.Client:
    """An httpx.Client honoring ``proxy`` for any supported scheme.

    ``bypass_hosts`` connect directly even with a proxy set; ``user_agent``
    overrides the default UA header for every request from this client."""
    client_kwargs = _client_kwargs(proxy)
    if proxy and bypass_hosts:
        mounts = dict(client_kwargs.get("mounts") or {})
        for host in bypass_hosts:
            mounts[f"all://{host}"] = httpx.HTTPTransport()
            mounts[f"all://*.{host}"] = httpx.HTTPTransport()
        client_kwargs["mounts"] = mounts
    if user_agent:
        headers = dict(kwargs.pop("headers", None) or {})
        headers.setdefault("User-Agent", user_agent)
        kwargs["headers"] = headers
    return httpx.Client(**client_kwargs, **kwargs)


#: Interface-name fragments that strongly suggest a VPN / tunnel is up.
_VPN_HINTS = ("tun", "tap", "wg", "ppp", "utun", "ipsec", "nordlynx", "proton", "mullvad", "wintun")


def detect_vpn() -> bool:
    """True when a VPN-like network interface appears to be up. A heuristic -
    it looks for tunnel adapters (WireGuard, OpenVPN, IKEv2, ...), so it is a
    hint, not a guarantee. Never raises."""
    try:
        import psutil

        stats = psutil.net_if_stats()
    except Exception:  # pragma: no cover - no psutil / permissions
        return False
    for name, info in stats.items():
        lowered = name.lower()
        if getattr(info, "isup", False) and any(hint in lowered for hint in _VPN_HINTS):
            return True
    return False


def active_vpn_interfaces() -> list[str]:
    """The names of the up VPN-like interfaces (for the dashboard tooltip)."""
    try:
        import psutil

        stats = psutil.net_if_stats()
    except Exception:  # pragma: no cover
        return []
    return [
        name
        for name, info in stats.items()
        if getattr(info, "isup", False) and any(h in name.lower() for h in _VPN_HINTS)
    ]


def resolves(host: str) -> bool:  # pragma: no cover - trivial DNS probe
    try:
        socket.getaddrinfo(host, None)
        return True
    except OSError:
        return False
