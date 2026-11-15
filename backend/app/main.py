"""App factory: CORS, request-id middleware, error handlers, routers under /v1."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import (
    analyses,
    auth,
    comparisons,
    fields,
    geo,
    locations,
    meta,
    profitability,
    saved_fields,
    snapshots,
    tiles,
)
from app.core.config import Settings, get_settings
from app.core.errors import install_error_handlers
from app.core.logging import setup_logging
from app.core.middleware import RequestIdMiddleware
from app.core.ratelimit import RateLimiter
from app.services import Services

API_PREFIX = "/v1"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    setup_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.services = Services(settings)
        try:
            yield
        finally:
            await app.state.services.aclose()

    app = FastAPI(
        lifespan=lifespan,
        title="Field Shift API",
        version="0.14.0",
        docs_url=f"{API_PREFIX}/docs",
        openapi_url=f"{API_PREFIX}/openapi-generated.json",
    )
    app.state.settings = settings
    app.state.limiters = {
        name: RateLimiter(settings.rate_limit_requests, settings.rate_limit_window_s)
        for name in ("analyses", "locations", "auth", "comparisons", "profitability", "reports")
    }
    app.state.limiters["password"] = RateLimiter(5, 60)

    install_error_handlers(app)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        # The refresh token is a cookie: the frontend calls /v1/auth/* with `credentials: "include"`.
        # Credentials require explicit origins (never "*"): FRONTEND_ORIGIN and CORS_EXTRA_ORIGINS.
        allow_credentials=True,
        allow_methods=["GET", "HEAD", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
        # ETag, Content-Range, Content-Length: needed by the PMTiles client reading fields.pmtiles.
        expose_headers=[
            "X-Request-Id", "Location", "Retry-After", "ETag", "Content-Range", "Content-Length",
        ],
    )
    # Added last so it is outermost: every response, including CORS preflight, gets an id.
    app.add_middleware(RequestIdMiddleware)

    for r in (
        meta.router, geo.router, locations.router, fields.router, tiles.router, snapshots.router,
        analyses.router, profitability.router, auth.router, saved_fields.router, comparisons.router,
    ):
        app.include_router(r, prefix=API_PREFIX)
    return app


app = create_app()
