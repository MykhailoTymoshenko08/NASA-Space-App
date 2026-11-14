"""Validate real HTTP responses against `contract/openapi.yaml` with openapi-core."""

from functools import lru_cache
from urllib.parse import parse_qs, urlparse

import httpx
from openapi_core import OpenAPI
from openapi_core.datatypes import RequestParameters
from werkzeug.datastructures import Headers, ImmutableMultiDict

from app.core.config import REPO_DIR

CONTRACT = REPO_DIR / "contract" / "openapi.yaml"
# Must match `servers[0].url` host so openapi-core can find the path.
BASE_URL = "http://localhost:8000"


@lru_cache
def spec() -> OpenAPI:
    return OpenAPI.from_file_path(str(CONTRACT))


class _Req:
    def __init__(self, r: httpx.Request):
        self._r = r
        u = urlparse(str(r.url))
        self._u = u
        self.parameters = RequestParameters(
            query=ImmutableMultiDict(parse_qs(u.query)),
            header=Headers(dict(r.headers)),
            cookie=ImmutableMultiDict({}),
        )

    @property
    def host_url(self) -> str:
        return f"{self._u.scheme}://{self._u.netloc}"

    @property
    def path(self) -> str:
        return self._u.path

    @property
    def method(self) -> str:
        return self._r.method.lower()

    @property
    def body(self) -> bytes | None:
        return self._r.content or None

    @property
    def content_type(self) -> str:
        return self._r.headers.get("content-type", "")


class _Resp:
    def __init__(self, r: httpx.Response):
        self._r = r

    @property
    def status_code(self) -> int:
        return self._r.status_code

    @property
    def content_type(self) -> str:
        return self._r.headers.get("content-type", "")

    @property
    def headers(self) -> Headers:
        return Headers(dict(self._r.headers))

    @property
    def data(self) -> bytes | str | None:
        # openapi-core validates `type: string, format: binary` bodies as str, not bytes.
        # For binary media types (vector tiles) hand it a lossless latin-1 str; status code,
        # content type and headers are still checked against the contract.
        if not self.content_type.startswith("application/json"):
            return self._r.content.decode("latin-1")
        return self._r.content


def assert_matches_contract(resp: httpx.Response) -> None:
    """Raise if the response (status, content type, body, headers) is not described by the YAML."""
    assert resp.headers.get("x-request-id"), "missing X-Request-Id"
    spec().validate_response(_Req(resp.request), _Resp(resp))
