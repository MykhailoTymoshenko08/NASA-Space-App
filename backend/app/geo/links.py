"""Turn the pasted string into a point, following map short links server-side.

SSRF rules (backend spec 5.5.4):
- Only short-link hosts (maps.app.goo.gl, goo.gl/maps, maps.apple) are ever fetched. Full Google and
  Apple URLs are parsed locally, never requested.
- Every hop: https only, default port, no userinfo, exact-host allow-list, and the host's DNS answers
  must all be public unicast addresses (no private, loopback, link-local, reserved, multicast...).
- At most 3 redirects, 5 s total, redirects are never auto-followed, response bodies are never read
  (streamed request, only the `Location` header is used).
"""

import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import httpx

from app.core.errors import ApiException
from app.geo.parsers import (
    ALL_HOSTS,
    LinkFamily,
    Point,
    is_short_link,
    looks_like_url,
    normalize_url,
    parse_coordinates,
    parse_map_url,
    split_url,
    unparseable,
    unsupported_link,
)

MAX_HOPS = 3
TOTAL_TIMEOUT_S = 5.0
USER_AGENT = "FieldShift/0.1 (+map link resolver)"

Resolver = Callable[[str], Awaitable[list[str]]]


class BlockedTarget(Exception):
    """A redirect target failed the SSRF checks."""


@dataclass(frozen=True)
class ParsedInput:
    kind: str  # plain_coordinates | google_maps_url | apple_maps_url
    point: Point


async def system_resolver(host: str) -> list[str]:
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    return sorted({i[4][0] for i in infos})


def is_public_ip(addr: str) -> bool:
    ip = ipaddress.ip_address(addr.split("%", 1)[0])
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_global and not (
        ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast
        or ip.is_reserved or ip.is_unspecified
    )


async def check_fetchable(url: str, resolver: Resolver) -> None:
    parts, host, port = split_url(url)
    if parts.scheme != "https":
        raise BlockedTarget(f"scheme {parts.scheme!r}")
    if parts.username or parts.password:
        raise BlockedTarget("userinfo in URL")
    if port not in (None, 443):
        raise BlockedTarget(f"port {port}")
    if not is_short_link(host) or host not in ALL_HOSTS:
        raise BlockedTarget(f"host {host!r} not allowed")
    try:
        ipaddress.ip_address(host)
        raise BlockedTarget("literal IP host")
    except ValueError:
        pass
    addrs = await resolver(host)
    if not addrs or not all(is_public_ip(a) for a in addrs):
        raise BlockedTarget(f"host {host!r} resolves to a non-public address")


def _family_kind(fam: LinkFamily) -> str:
    return "google_maps_url" if fam is LinkFamily.google else "apple_maps_url"


async def _next_location(client: httpx.AsyncClient, url: str) -> str | None:
    async with client.stream("GET", url) as r:  # body is never read
        if r.status_code in (301, 302, 303, 307, 308):
            loc = r.headers.get("location")
            return str(httpx.URL(url).join(loc)) if loc else None
        return None


async def resolve_link(
    url: str,
    client: httpx.AsyncClient,
    resolver: Resolver = system_resolver,
) -> ParsedInput:
    url = normalize_url(url)
    fam, point = parse_map_url(url)  # UNPARSEABLE_INPUT if not a known map link
    first_family = fam
    hops = 0
    try:
        async with asyncio.timeout(TOTAL_TIMEOUT_S):
            while True:
                _, host, _ = split_url(url)
                if point is not None:
                    return ParsedInput(_family_kind(first_family), point)
                if not is_short_link(host):
                    raise unsupported_link()
                if hops >= MAX_HOPS:
                    raise unsupported_link()
                try:
                    await check_fetchable(url, resolver)
                except BlockedTarget as e:
                    raise unsupported_link() from e
                nxt = await _next_location(client, url)
                hops += 1
                if not nxt:
                    raise unsupported_link()
                url = nxt
                try:
                    fam, point = parse_map_url(url)
                except ApiException as e:
                    # Redirected somewhere that is not a map link: stop, never fetch it.
                    raise unsupported_link() from e
    except TimeoutError as e:
        raise unsupported_link() from e
    except httpx.HTTPError as e:
        raise unsupported_link() from e


async def parse_input(
    text: str, client: httpx.AsyncClient, resolver: Resolver = system_resolver
) -> ParsedInput:
    t = text.strip()
    if looks_like_url(t):
        return await resolve_link(t, client, resolver)
    try:
        return ParsedInput("plain_coordinates", parse_coordinates(t))
    except ApiException:
        raise unparseable() from None


def make_link_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        follow_redirects=False,
        timeout=httpx.Timeout(TOTAL_TIMEOUT_S),
        headers={"User-Agent": USER_AGENT},
        trust_env=False,  # ignore proxy env vars
    )
