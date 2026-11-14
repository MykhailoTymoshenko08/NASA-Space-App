"""Local static server for the field PMTiles file: HTTP Range + CORS, a dev stand-in for R2/S3.

PMTiles clients read the archive with Range requests, so a server without Range support (Python's
`http.server`, most static page hosts) does not work. This one serves files from DATA_DIR with:
  - GET and HEAD, single `Range: bytes=a-b` / `a-` / `-n` (206 + Content-Range), else 200
  - ETag (size + mtime), Accept-Ranges: bytes
  - CORS only for the allowed origins (default FRONTEND_ORIGIN): methods GET, HEAD; header Range;
    exposed headers ETag, Content-Range, Content-Length; OPTIONS preflight.

Usage: uv run python scripts/serve_tiles.py [--port 8787] [--origin http://localhost:5173 ...]
"""

import argparse
import os
import re
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from _common import data_dir

from app.core.config import get_settings

RANGE_RE = re.compile(r"^bytes=(\d*)-(\d*)$")
CHUNK = 1 << 20


def make_handler(root: Path, origins: set[str]):
    class Handler(BaseHTTPRequestHandler):
        server_version = "field-shift-tiles/1"

        def _cors(self) -> None:
            origin = self.headers.get("Origin")
            if origin and origin in origins:
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")
                self.send_header("Access-Control-Expose-Headers", "ETag, Content-Range, Content-Length")

        def _file(self) -> Path | None:
            name = self.path.split("?", 1)[0].lstrip("/")
            # Only plain file names directly in root: no sub-paths, no traversal.
            if not name or "/" in name or name.startswith(".") or not name.endswith(".pmtiles"):
                return None
            p = root / name
            return p if p.is_file() else None

        def do_OPTIONS(self) -> None:  # noqa: N802 - http.server naming
            self.send_response(HTTPStatus.NO_CONTENT)
            self._cors()
            if self.headers.get("Origin") in origins:
                self.send_header("Access-Control-Allow-Methods", "GET, HEAD")
                self.send_header("Access-Control-Allow-Headers", "Range")
                self.send_header("Access-Control-Max-Age", "86400")
            self.end_headers()

        def do_HEAD(self) -> None:  # noqa: N802
            self._serve(body=False)

        def do_GET(self) -> None:  # noqa: N802
            self._serve(body=True)

        def _serve(self, body: bool) -> None:
            p = self._file()
            if p is None:
                self.send_response(HTTPStatus.NOT_FOUND)
                self._cors()
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            st = p.stat()
            size = st.st_size
            etag = f'"{size:x}-{int(st.st_mtime):x}"'
            start, end, status = 0, size - 1, HTTPStatus.OK
            rng = self.headers.get("Range")
            if rng:
                m = RANGE_RE.match(rng.strip())
                if m and (m.group(1) or m.group(2)):
                    a, b = m.group(1), m.group(2)
                    if a:
                        start, end = int(a), min(int(b), size - 1) if b else size - 1
                    else:
                        start, end = max(size - int(b), 0), size - 1
                    status = HTTPStatus.PARTIAL_CONTENT
                if status == HTTPStatus.PARTIAL_CONTENT and start > end:
                    self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                    self._cors()
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
            length = end - start + 1
            self.send_response(status)
            self._cors()
            self.send_header("Content-Type", "application/vnd.pmtiles")
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("ETag", etag)
            self.send_header("Cache-Control", "public, max-age=3600")
            self.send_header("Content-Length", str(length))
            if status == HTTPStatus.PARTIAL_CONTENT:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.end_headers()
            if not body:
                return
            with p.open("rb") as f:
                f.seek(start)
                left = length
                while left > 0:
                    chunk = f.read(min(CHUNK, left))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    left -= len(chunk)

    return Handler


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=int(os.environ.get("TILES_PORT", 8787)))
    ap.add_argument("--origin", action="append", help="allowed CORS origin (repeatable)")
    args = ap.parse_args()
    origins = set(args.origin or [get_settings().frontend_origin])
    root = data_dir()
    print(f"serving {root}/*.pmtiles on http://{args.host}:{args.port} (CORS: {sorted(origins)})")
    ThreadingHTTPServer((args.host, args.port), make_handler(root, origins)).serve_forever()


if __name__ == "__main__":
    main()
