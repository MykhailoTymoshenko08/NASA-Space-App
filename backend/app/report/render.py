"""Render an analysis result to the PDF report (HTML template + CSS, laid out by WeasyPrint).

Fonts, logo and stylesheet ship in `assets/`, so the PDF never fetches anything and looks the same
on every server.
"""

from functools import cache
from pathlib import Path
from urllib.parse import unquote, urlparse

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from app.models import AnalysisOptions, AnalysisResult
from app.report.present import report_context

HERE = Path(__file__).parent
ASSETS = HERE / "assets"
ASSETS_URI = ASSETS.as_uri()


@cache
def _env() -> Environment:
    return Environment(
        loader=FileSystemLoader(HERE / "templates"),
        autoescape=select_autoescape(["html", "j2"]),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )


def report_html(result: AnalysisResult, options: AnalysisOptions | None, job_id: str) -> str:
    return _env().get_template("report.html.j2").render(**report_context(result, options, job_id))


def report_pdf(result: AnalysisResult, options: AnalysisOptions | None, job_id: str) -> bytes:
    # Imported here: WeasyPrint loads Pango at import time, and only this path needs it.
    from weasyprint import HTML

    html = report_html(result, options, job_id)
    # base_url: the stylesheet, fonts and logo resolve from the bundled assets, never the network.
    return HTML(string=html, base_url=f"{ASSETS_URI}/", url_fetcher=local_fetcher()).write_pdf()


def local_fetcher():
    """A WeasyPrint fetcher for bundled files only: a stray URL in a result can never make the server
    fetch a remote or other local resource."""
    from weasyprint.urls import URLFetcher

    class LocalOnly(URLFetcher):
        def fetch(self, url, headers=None):
            if not (url.startswith("data:") or _is_asset(url)):
                raise ValueError(f"report may only load bundled assets, not {url}")
            return super().fetch(url, headers)

    return LocalOnly(allowed_protocols={"file", "data"})


def _is_asset(url: str) -> bool:
    """A file URL inside `assets/` after resolving `..` and symlinks."""
    parsed = urlparse(url)
    if parsed.scheme != "file" or parsed.netloc not in ("", "localhost"):
        return False
    return Path(unquote(parsed.path)).resolve().is_relative_to(ASSETS.resolve())
