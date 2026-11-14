"""Parse pasted text into a point: plain coordinates, Google Maps URLs, Apple Maps URLs.

Pure functions, no network. Short links are followed by app.geo.links, which then calls
`parse_map_url` on the final URL.

Google Maps URL formats: https://developers.google.com/maps/documentation/urls/get-started
Apple Maps URL formats: https://developer.apple.com/library/archive/featuredarticles/iPhoneURLScheme_Reference/MapLinks/MapLinks.html
"""

import re
from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import parse_qs, unquote_plus, urlsplit

from app.core.errors import ApiException, ErrorCode


class LinkFamily(StrEnum):
    google = "google"
    apple = "apple"


# Full-URL hosts we parse. Exact host match only (no suffix matching: "evilgoogle.com").
GOOGLE_HOSTS = {"google.com", "www.google.com", "maps.google.com"}
APPLE_HOSTS = {"maps.apple.com", "maps.apple"}
# Short-link hosts that must be followed server-side to get coordinates.
GOOGLE_SHORT_HOSTS = {"maps.app.goo.gl", "goo.gl"}
APPLE_SHORT_HOSTS = {"maps.apple"}  # e.g. https://maps.apple/p/<id>
ALL_HOSTS = GOOGLE_HOSTS | APPLE_HOSTS | GOOGLE_SHORT_HOSTS


@dataclass(frozen=True)
class Point:
    lat: float
    lon: float


def unparseable(msg: str = "") -> ApiException:
    return ApiException(
        ErrorCode.UNPARSEABLE_INPUT,
        msg
        or "Could not read a location. Paste coordinates like `41.5868, -93.6250` "
        "or a Google Maps / Apple Maps link.",
    )


def unsupported_link() -> ApiException:
    return ApiException(
        ErrorCode.UNSUPPORTED_LINK,
        "This map link does not contain coordinates. Open it, drop a pin on your field, "
        "and paste the coordinates instead (for example `41.5868, -93.6250`).",
    )


# ---------------------------------------------------------------------------
# Plain coordinates
# ---------------------------------------------------------------------------
_NUM = r"[+-]?\d{1,3}(?:\.\d+)?"
_DEG = r"(?:°|º|˚|\s*deg(?:rees)?\b|d\b)"
_MIN = r"(?:'|′|’|‘|\s*m(?:in)?\b)"
_SEC = r"(?:\"|″|”|“|''|′′|\s*s(?:ec)?\b)"
_HEMI = r"[NSEWnsew]"

# One coordinate: optional leading hemisphere, degrees, optional minutes/seconds, optional trailing
# hemisphere. Minutes/seconds need their unit mark so "41 93" is never read as degrees+minutes.
def _component_re(p: str) -> str:
    return (
        rf"(?P<{p}h1>{_HEMI})?\s*"
        rf"(?P<{p}deg>{_NUM})\s*{_DEG}?\s*"
        rf"(?:(?P<{p}min>\d{{1,2}}(?:\.\d+)?)\s*{_MIN}\s*)?"
        rf"(?:(?P<{p}sec>\d{{1,2}}(?:\.\d+)?)\s*{_SEC}\s*)?"
        rf"(?P<{p}h2>{_HEMI})?"
    )


_PAIR = re.compile(
    r"^\s*\(?\s*"
    + _component_re("a")
    + r"\s*(?:[,;/]|\s)\s*"
    + _component_re("b")
    + r"\s*\)?\s*$"
)


def _component(m: re.Match, p: str) -> tuple[float, str | None]:
    deg_s, mins, secs = m.group(f"{p}deg"), m.group(f"{p}min"), m.group(f"{p}sec")
    h1, h2 = m.group(f"{p}h1"), m.group(f"{p}h2")
    if h1 and h2:
        raise unparseable()
    hemi = (h1 or h2 or "").upper() or None
    deg = float(deg_s)
    if mins is not None or secs is not None:
        if "." in deg_s:
            raise unparseable()  # decimal degrees plus minutes makes no sense
        mn = float(mins or 0)
        sc = float(secs or 0)
        if mn >= 60 or sc >= 60:
            raise unparseable()
        value = abs(deg) + mn / 60 + sc / 3600
        if deg_s.startswith("-"):
            value = -value
    else:
        value = deg
    if hemi:
        if value < 0:
            raise unparseable()  # "-41 N" is contradictory
        if hemi in ("S", "W"):
            value = -value
    return value, hemi


def _valid_lat(v: float) -> bool:
    return -90 <= v <= 90


def _valid_lon(v: float) -> bool:
    return -180 <= v <= 180


def parse_coordinates(text: str) -> Point:
    """Parse `lat, lon` in decimal or DMS, with optional N/S/E/W. Raises UNPARSEABLE_INPUT."""
    s = text.strip().replace(" ", " ")
    m = _PAIR.match(s)
    if not m:
        raise unparseable()
    (a, ha), (b, hb) = _component(m, "a"), _component(m, "b")

    if ha or hb:
        lat_first = ha in ("N", "S") or hb in ("E", "W")
        lon_first = ha in ("E", "W") or hb in ("N", "S")
        if lat_first == lon_first:
            raise unparseable()
        lat, lon = (a, b) if lat_first else (b, a)
    elif _valid_lat(a) and _valid_lon(b):
        lat, lon = a, b
    elif not _valid_lat(a) and _valid_lon(a) and _valid_lat(b):
        # Swap rule: first number cannot be a latitude but is a valid longitude.
        lat, lon = b, a
    else:
        raise unparseable()
    if not (_valid_lat(lat) and _valid_lon(lon)):
        raise unparseable()
    return Point(lat=round(lat, 7), lon=round(lon, 7))


def try_coordinates(text: str) -> Point | None:
    try:
        return parse_coordinates(text)
    except ApiException:
        return None


# ---------------------------------------------------------------------------
# URLs
# ---------------------------------------------------------------------------
_GOOGLE_PIN = re.compile(r"!3d(-?\d+(?:\.\d+)?)!4d(-?\d+(?:\.\d+)?)")
_GOOGLE_AT = re.compile(r"@(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)(?:,(\d+(?:\.\d+)?)([zma]))?")
_URLISH = re.compile(r"^(?:https?://)?[a-z0-9.-]+\.[a-z]{2,}(?:[/?#]|$)", re.I)


def looks_like_url(text: str) -> bool:
    t = text.strip()
    return t.lower().startswith(("http://", "https://")) or bool(_URLISH.match(t))


def normalize_url(text: str) -> str:
    t = text.strip()
    if not t.lower().startswith(("http://", "https://")):
        t = "https://" + t
    return t


def split_url(url: str):
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower().rstrip(".")
        port = parts.port
    except ValueError as e:
        raise unparseable() from e
    return parts, host, port


def link_family(host: str, path: str) -> LinkFamily | None:
    if host in GOOGLE_HOSTS:
        if host == "maps.google.com" or path.startswith("/maps"):
            return LinkFamily.google
        return None
    if host == "goo.gl":
        return LinkFamily.google if path.startswith("/maps") else None
    if host == "maps.app.goo.gl":
        return LinkFamily.google
    if host in APPLE_HOSTS:
        return LinkFamily.apple
    return None


def is_short_link(host: str) -> bool:
    return host in GOOGLE_SHORT_HOSTS or host in APPLE_SHORT_HOSTS


def _pair(lat_s: str, lon_s: str) -> Point | None:
    try:
        lat, lon = float(lat_s), float(lon_s)
    except ValueError:
        return None
    if _valid_lat(lat) and _valid_lon(lon):
        return Point(lat=round(lat, 7), lon=round(lon, 7))
    return None


def _query_coords(qs: dict[str, list[str]], keys: tuple[str, ...]) -> Point | None:
    for k in keys:
        for v in qs.get(k, []):
            v = v.strip()
            if v.lower().startswith("loc:"):
                v = v[4:]
            p = try_coordinates(v)
            if p:
                return p
    return None


def _parse_google(parts) -> Point | None:
    raw_path = unquote_plus(parts.path)
    # 1. Place pin (data=...!3d<lat>!4d<lon>): the actual dropped pin / place, not the viewport.
    pins = _GOOGLE_PIN.findall(parts.path + "?" + parts.query)
    for lat_s, lon_s in reversed(pins):  # last pair is the selected place
        p = _pair(lat_s, lon_s)
        if p:
            return p
    # 2. Query parameters.
    qs = parse_qs(parts.query)
    p = _query_coords(qs, ("q", "query", "ll", "destination", "center"))
    if p:
        return p
    # 3. Coordinates as the place/search name: /maps/place/41°35'12.5"N+93°37'30.0"W/...
    m = re.search(r"/maps/(?:place|search|dir)/([^/@]+)", raw_path)
    if m:
        p = try_coordinates(m.group(1))
        if p:
            return p
    # 4. Viewport centre: /@41.5868,-93.625,15z
    m = _GOOGLE_AT.search(raw_path)
    if m:
        return _pair(m.group(1), m.group(2))
    return None


def _parse_apple(parts) -> Point | None:
    qs = parse_qs(parts.query)
    # ll = pin, coordinate = place, q may hold coordinates, sll = search-near hint (least specific).
    return _query_coords(qs, ("ll", "coordinate", "q", "sll", "center"))


def parse_map_url(url: str) -> tuple[LinkFamily, Point | None]:
    """Return (family, point or None). Raises UNPARSEABLE_INPUT if it is not a known map link."""
    parts, host, _ = split_url(url)
    if parts.scheme not in ("http", "https"):
        raise unparseable()
    fam = link_family(host, parts.path)
    if fam is None:
        raise unparseable(
            "Only Google Maps and Apple Maps links are supported. You can also paste coordinates."
        )
    if fam is LinkFamily.google:
        return fam, _parse_google(parts)
    return fam, _parse_apple(parts)
