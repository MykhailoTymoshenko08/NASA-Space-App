"""App factory: CORS, request-id middleware, error handlers, routers under /v1."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import fields, geo, meta, tiles
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
            app.state.services.close()

    app = FastAPI(
        lifespan=lifespan,
        title="Field Shift API",
        version="0.2.0",
        docs_url=f"{API_PREFIX}/docs",
        openapi_url=f"{API_PREFIX}/openapi-generated.json",
    )
    app.state.settings = settings
    app.state.limiters = {
        name: RateLimiter(settings.rate_limit_requests, settings.rate_limit_window_s)
        for name in ("analyses", "locations")
    }

    install_error_handlers(app)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_origin],
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=["X-Request-Id", "Location", "Retry-After"],
    )
    # Added last so it is outermost: every response, including CORS preflight, gets an id.
    app.add_middleware(RequestIdMiddleware)

    for r in (meta.router, geo.router, fields.router, tiles.router):
        app.include_router(r, prefix=API_PREFIX)
    return app


app = create_app()
