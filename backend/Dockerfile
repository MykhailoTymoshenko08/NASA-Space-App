# Field Shift backend image with prepared data baked in.
#
# Build the boundary data first (needs tippecanoe + internet), then build from backend/:
#   make data-boundaries
#   docker build -t field-shift-backend .
#   docker run --rm -p 8000:8000 -e FRONTEND_ORIGIN=http://localhost:5173 \
#     -e DATABASE_URL=postgresql://... \
#     -v "$PWD/data/csb_ia_il_ne.pmtiles:/app/data/csb_ia_il_ne.pmtiles:ro" field-shift-backend

# ---------- build stage: resolve dependencies into a venv ----------
FROM python:3.12-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.13.8 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project

# ---------- runtime stage ----------
FROM python:3.12-slim

# Pango/HarfBuzz for WeasyPrint (PDF analysis reports). Fonts are bundled in app/report/assets.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --system --uid 10001 --home /app app
WORKDIR /app

COPY --from=build /app/.venv /app/.venv
COPY app ./app
# Prepared data (gitignored, built by `make data`). Fail the build early if it is missing.
COPY data ./data
# Field polygons are not baked in: they live in PostGIS (DATABASE_URL), and data/csb_ia_il_ne.pmtiles
# is mounted as a volume (docker-compose.yml).
RUN for f in states.json counties.json counties.parquet states.parquet boundaries.pmtiles; do \
        test -s "data/$f" || { echo "data/$f missing: run 'make data' before docker build" >&2; exit 1; }; \
    done \
    && mkdir -p /app/.cache && chown app:app /app/.cache

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    DATA_DIR=/app/data \
    CACHE_DIR=/app/.cache

USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=20s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/v1/health', timeout=2)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
