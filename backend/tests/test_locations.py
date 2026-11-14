"""M3: coordinate / map-link parsing, short-link SSRF protections, POST /locations/resolve.

No network: DNS is faked and HTTP is mocked with respx.
"""

import httpx
import pytest
import respx

from app.core.errors import ApiException
from app.geo.links import is_public_ip, make_link_client, parse_input
from app.geo.parsers import LinkFamily, parse_coordinates, parse_map_url
from tests.contract import assert_matches_contract
from tests.fixture_data import F1_POINT

LAT, LON = 41.5868, -93.625


def close(p, lat=LAT, lon=LON, tol=1e-4):
    return abs(p.lat - lat) < tol and abs(p.lon - lon) < tol


# ---------------------------------------------------------------------------
# Plain coordinates
# ---------------------------------------------------------------------------
GOOD_COORDS = [
    "41.5868, -93.6250",
    "41.5868 -93.6250",
    "41.5868,-93.6250",
    "  41.5868 ,  -93.625  ",
    "41.5868;-93.6250",
    "(41.5868, -93.6250)",
    "+41.5868, -93.6250",
    "41.5868N 93.6250W",
    "41.5868 N, 93.6250 W",
    "N41.5868 W93.6250",
    "n 41.5868, w 93.6250",
    "93.6250W 41.5868N",  # hemisphere letters decide order
    "41°35'12.5\"N 93°37'30\"W",
    "41°35′12.5″N 93°37′30″W",  # unicode prime marks
    "41° 35' 12.5\" N, 93° 37' 30\" W",
    "41°35.208'N 93°37.5'W",  # degrees + decimal minutes
    "-93.6250, 41.5868",  # swap rule: first is not a valid lat, is a valid lon
    "41.5868 -93.6250",  # non-breaking space
]


@pytest.mark.parametrize("text", GOOD_COORDS)
def test_good_coordinates(text):
    assert close(parse_coordinates(text))


BAD_COORDS = [
    "",
    "abc",
    "41.5868",
    "41.5868, -93.625, 12",
    "91.0, 200.0",  # neither order valid
    "41.5 N 93.6 N",  # both latitudes
    "41.5 E 93.6 W",  # both longitudes
    "-41.5 N, 93.6 W",  # sign and hemisphere disagree
    "41°75'0\"N 93°0'0\"W",  # minutes >= 60
    "41.5°30'N 93°W",  # decimal degrees with minutes
    "Des Moines, Iowa",
    "1e3, 2e3",
]


@pytest.mark.parametrize("text", BAD_COORDS)
def test_bad_coordinates(text):
    with pytest.raises(ApiException) as ei:
        parse_coordinates(text)
    assert ei.value.code == "UNPARSEABLE_INPUT"


# ---------------------------------------------------------------------------
# Full map URLs (parsed locally, never fetched)
# ---------------------------------------------------------------------------
PIN = (41.6001, -93.6001)
GOOD_URLS = [
    # (url, family, expected (lat, lon))
    ("https://www.google.com/maps/@41.5868,-93.625,15z", "google", (LAT, LON)),
    ("https://www.google.com/maps/@41.5868,-93.625,800m/data=!3m1!1e3", "google", (LAT, LON)),
    ("https://google.com/maps?q=41.5868,-93.625", "google", (LAT, LON)),
    ("https://maps.google.com/?q=41.5868,-93.625", "google", (LAT, LON)),
    ("https://maps.google.com/maps?ll=41.5868,-93.625&z=14", "google", (LAT, LON)),
    ("https://www.google.com/maps/search/?api=1&query=41.5868%2C-93.625", "google", (LAT, LON)),
    ("https://www.google.com/maps?q=loc:41.5868+-93.625", "google", (LAT, LON)),
    # Pin wins over viewport centre.
    (
        "https://www.google.com/maps/place/Some+Farm/@41.59,-93.63,17z/data=!3m1!4b1!4m6!3m5"
        "!1s0x87ee99:0x1!8m2!3d41.6001!4d-93.6001!16s%2Fg%2F11",
        "google",
        PIN,
    ),
    # Coordinates as the place name (DMS, URL-encoded).
    (
        "https://www.google.com/maps/place/41%C2%B035'12.5%22N+93%C2%B037'30.0%22W/"
        "@41.5868,-93.6272,17z",
        "google",
        (41.5868056, -93.625),
    ),
    ("https://www.google.com/maps/search/41.5868,+-93.625?entry=ttu", "google", (LAT, LON)),
    ("www.google.com/maps/@41.5868,-93.625,15z", "google", (LAT, LON)),  # no scheme
    ("https://maps.apple.com/?ll=41.5868,-93.625&q=Dropped%20Pin", "apple", (LAT, LON)),
    ("https://maps.apple.com/place?coordinate=41.5868,-93.625&name=Field", "apple", (LAT, LON)),
    ("https://maps.apple.com/?q=41.5868,-93.625", "apple", (LAT, LON)),
    ("https://maps.apple.com/?sll=41.5868,-93.625&z=10&t=s", "apple", (LAT, LON)),
    ("https://maps.apple.com/?ll=41.6001,-93.6001&sll=41.5868,-93.625", "apple", PIN),
]


@pytest.mark.parametrize("url,family,expected", GOOD_URLS)
def test_good_map_urls(url, family, expected):
    from app.geo.parsers import normalize_url

    fam, p = parse_map_url(normalize_url(url))
    assert fam == LinkFamily(family)
    assert p is not None and close(p, *expected)


@pytest.mark.parametrize(
    "url",
    [
        "https://www.google.com/maps/place/Des+Moines,+IA",  # no coordinates at all
        "https://maps.apple.com/?q=Des%20Moines&address=Des%20Moines",
        "https://maps.apple.com/place?auid=1234567890",
    ],
)
def test_map_urls_without_coordinates(url):
    _, p = parse_map_url(url)
    assert p is None


@pytest.mark.parametrize(
    "url",
    [
        "https://evilgoogle.com/maps/@41.5868,-93.625,15z",
        "https://www.google.com.evil.example/maps/@41.5868,-93.625,15z",
        "https://www.google.com/search?q=41.5868,-93.625",  # google.com but not /maps
        "https://www.bing.com/maps?cp=41.5868~-93.625",
        "ftp://maps.google.com/?q=41.5868,-93.625",
        "https://goo.gl/abc123",  # goo.gl but not /maps
    ],
)
def test_unknown_urls_are_unparseable(url):
    with pytest.raises(ApiException) as ei:
        parse_map_url(url)
    assert ei.value.code == "UNPARSEABLE_INPUT"


# ---------------------------------------------------------------------------
# Short links + SSRF
# ---------------------------------------------------------------------------
async def public_dns(host):
    return ["142.250.80.46"]


def dns(mapping):
    async def _r(host):
        return mapping.get(host, ["142.250.80.46"])

    return _r


FULL = "https://www.google.com/maps/place/X/@41.59,-93.63,17z/data=!3d41.5868!4d-93.625"


async def _parse(text, resolver=public_dns):
    async with make_link_client() as c:
        return await parse_input(text, c, resolver)


@respx.mock
async def test_short_google_link_followed():
    respx.get("https://maps.app.goo.gl/AbCdEf123").mock(
        return_value=httpx.Response(302, headers={"Location": FULL})
    )
    r = await _parse("https://maps.app.goo.gl/AbCdEf123")
    assert r.kind == "google_maps_url" and close(r.point)
    # The full google.com URL itself is never requested.
    assert len(respx.calls) == 1


@respx.mock
async def test_two_hop_goo_gl_chain():
    respx.get("https://goo.gl/maps/old1").mock(
        return_value=httpx.Response(301, headers={"Location": "https://maps.app.goo.gl/new2"})
    )
    respx.get("https://maps.app.goo.gl/new2").mock(
        return_value=httpx.Response(302, headers={"Location": FULL})
    )
    r = await _parse("goo.gl/maps/old1")
    assert close(r.point)


@respx.mock
async def test_apple_short_link_with_coordinates():
    respx.get("https://maps.apple/p/abc").mock(
        return_value=httpx.Response(
            302, headers={"Location": "https://maps.apple.com/place?coordinate=41.5868,-93.625"}
        )
    )
    r = await _parse("https://maps.apple/p/abc")
    assert r.kind == "apple_maps_url" and close(r.point)


@respx.mock
async def test_apple_short_link_without_coordinates_is_unsupported():
    respx.get("https://maps.apple/p/xyz").mock(
        return_value=httpx.Response(
            302, headers={"Location": "https://maps.apple.com/place?auid=123&lsp=9902"}
        )
    )
    with pytest.raises(ApiException) as ei:
        await _parse("https://maps.apple/p/xyz")
    assert ei.value.code == "UNSUPPORTED_LINK"


@respx.mock
async def test_redirect_to_foreign_host_is_not_fetched():
    respx.get("https://maps.app.goo.gl/evil").mock(
        return_value=httpx.Response(302, headers={"Location": "https://evil.example/steal"})
    )
    evil = respx.get("https://evil.example/steal").mock(return_value=httpx.Response(200))
    with pytest.raises(ApiException) as ei:
        await _parse("https://maps.app.goo.gl/evil")
    assert ei.value.code == "UNSUPPORTED_LINK"
    assert not evil.called


@respx.mock
@pytest.mark.parametrize(
    "location",
    [
        "http://169.254.169.254/latest/meta-data/",
        "http://127.0.0.1:8000/v1/health",
        "https://localhost/maps",
        "https://[::1]/maps",
        "file:///etc/passwd",
        "https://maps.app.goo.gl:8443/x",  # allowed host, non-default port
        "https://user:pw@maps.app.goo.gl/x",  # userinfo
        "http://maps.app.goo.gl/x",  # downgrade to http
    ],
)
async def test_ssrf_redirect_targets_blocked(location):
    respx.get("https://maps.app.goo.gl/start").mock(
        return_value=httpx.Response(302, headers={"Location": location})
    )
    with pytest.raises(ApiException) as ei:
        await _parse("https://maps.app.goo.gl/start")
    assert ei.value.code == "UNSUPPORTED_LINK"
    assert len(respx.calls) == 1  # only the allowed first hop was fetched


@respx.mock
@pytest.mark.parametrize("addr", ["127.0.0.1", "10.0.0.5", "169.254.169.254", "::1", "fd00::1"])
async def test_short_link_host_resolving_to_private_ip_blocked(addr):
    route = respx.get("https://maps.app.goo.gl/x").mock(return_value=httpx.Response(302))
    with pytest.raises(ApiException) as ei:
        await _parse("https://maps.app.goo.gl/x", resolver=dns({"maps.app.goo.gl": [addr]}))
    assert ei.value.code == "UNSUPPORTED_LINK"
    assert not route.called  # DNS check happens before any request


@respx.mock
async def test_more_than_three_hops_rejected():
    for i in range(5):
        respx.get(f"https://maps.app.goo.gl/h{i}").mock(
            return_value=httpx.Response(302, headers={"Location": f"https://maps.app.goo.gl/h{i + 1}"})
        )
    with pytest.raises(ApiException) as ei:
        await _parse("https://maps.app.goo.gl/h0")
    assert ei.value.code == "UNSUPPORTED_LINK"
    assert len(respx.calls) == 3


@respx.mock
async def test_short_link_200_without_redirect_is_unsupported():
    respx.get("https://maps.app.goo.gl/js").mock(return_value=httpx.Response(200, text="<html>"))
    with pytest.raises(ApiException) as ei:
        await _parse("https://maps.app.goo.gl/js")
    assert ei.value.code == "UNSUPPORTED_LINK"


@respx.mock
async def test_short_link_timeout_is_unsupported():
    respx.get("https://maps.app.goo.gl/slow").mock(side_effect=httpx.ConnectTimeout("slow"))
    with pytest.raises(ApiException) as ei:
        await _parse("https://maps.app.goo.gl/slow")
    assert ei.value.code == "UNSUPPORTED_LINK"


@pytest.mark.parametrize(
    "addr,public",
    [("8.8.8.8", True), ("142.250.80.46", True), ("10.1.2.3", False), ("192.168.0.1", False),
     ("100.64.0.1", False), ("::ffff:127.0.0.1", False), ("2607:f8b0::200e", True), ("0.0.0.0", False)],
)
def test_is_public_ip(addr, public):
    assert is_public_ip(addr) is public


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@pytest.mark.contract
def test_endpoint_plain_coordinates(client):
    r = client.post("/v1/locations/resolve", json={"input": f"{F1_POINT[0]}, {F1_POINT[1]}"})
    assert_matches_contract(r)
    j = r.json()
    assert j["input_kind"] == "plain_coordinates"
    assert j["point"] == {"lat": F1_POINT[0], "lon": F1_POINT[1]}
    assert j["selection"]["source"] == "coordinates"
    assert j["selection"]["field_id"] == "plss:IA050790N0240W0SN140"


@pytest.mark.contract
def test_endpoint_google_url(client):
    r = client.post(
        "/v1/locations/resolve",
        json={"input": f"https://www.google.com/maps/@{F1_POINT[0]},{F1_POINT[1]},15z"},
    )
    assert_matches_contract(r)
    j = r.json()
    assert j["input_kind"] == "google_maps_url"
    assert j["selection"]["source"] == "location_link"


@pytest.mark.contract
@respx.mock
def test_endpoint_short_link(client):
    client.app.state.services.dns_resolver = public_dns
    respx.get("https://maps.app.goo.gl/AbCdEf123").mock(
        return_value=httpx.Response(
            302, headers={"Location": f"https://www.google.com/maps?q={F1_POINT[0]},{F1_POINT[1]}"}
        )
    )
    respx.route(host="localhost").pass_through()
    r = client.post("/v1/locations/resolve", json={"input": "https://maps.app.goo.gl/AbCdEf123"})
    assert_matches_contract(r)
    assert r.json()["input_kind"] == "google_maps_url"


@pytest.mark.contract
@pytest.mark.parametrize(
    "text,code",
    [
        ("hello there", "UNPARSEABLE_INPUT"),
        ("https://www.bing.com/maps?cp=1~2", "UNPARSEABLE_INPUT"),
        ("https://www.google.com/maps/place/Des+Moines,+IA", "UNSUPPORTED_LINK"),
        ("48.8566, 2.3522", "OUTSIDE_COVERAGE"),  # Paris
        ("-33.86, 151.21", "OUTSIDE_COVERAGE"),
    ],
)
def test_endpoint_errors(client, text, code):
    r = client.post("/v1/locations/resolve", json={"input": text})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == code
    assert_matches_contract(r)


@pytest.mark.contract
@pytest.mark.parametrize("body", [{}, {"input": "ab"}, {"input": "x" * 2049}, {"input": 5}])
def test_endpoint_validation(client, body):
    r = client.post("/v1/locations/resolve", json=body)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"
    assert_matches_contract(r)
