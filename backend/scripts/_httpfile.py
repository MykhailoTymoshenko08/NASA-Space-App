"""Read-only, seekable file object over HTTP range requests (for remote Parquet footers/row groups)."""

import io

import httpx
from _common import USER_AGENT


class HttpRangeFile(io.RawIOBase):
    def __init__(self, url: str, timeout: float = 120.0):
        self.url = url
        self._c = httpx.Client(
            headers={"User-Agent": USER_AGENT}, timeout=timeout, follow_redirects=True
        )
        r = self._c.head(url)
        r.raise_for_status()
        if r.headers.get("accept-ranges") != "bytes":
            raise RuntimeError(f"{url} does not support range requests")
        self.size = int(r.headers["content-length"])
        self.pos = 0
        self.bytes_read = 0

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self.pos

    def seek(self, offset: int, whence: int = 0) -> int:
        if whence == 0:
            self.pos = offset
        elif whence == 1:
            self.pos += offset
        else:
            self.pos = self.size + offset
        return self.pos

    def read(self, n: int = -1) -> bytes:
        if n is None or n < 0:
            n = self.size - self.pos
        if n == 0 or self.pos >= self.size:
            return b""
        end = min(self.pos + n, self.size) - 1
        for attempt in range(4):
            try:
                r = self._c.get(self.url, headers={"Range": f"bytes={self.pos}-{end}"})
                r.raise_for_status()
                break
            except httpx.HTTPError:
                if attempt == 3:
                    raise
        data = r.content
        self.pos += len(data)
        self.bytes_read += len(data)
        return data

    def readinto(self, b) -> int:
        data = self.read(len(b))
        b[: len(data)] = data
        return len(data)

    def close(self) -> None:
        self._c.close()
        super().close()
