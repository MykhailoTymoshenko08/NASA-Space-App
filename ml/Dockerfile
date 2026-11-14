# FieldShift ML service. The build context is the repository root; deploy/data (precomputed counties + POWER cells) is in git,
# so `docker compose up --build` works from a clean clone. Refresh it with scripts/11_prepare_deploy.py after new data.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=8001 ML_MODE=real

# lightgbm needs the OpenMP runtime. (no curl: the healthcheck uses python)
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements-service.txt .
# lightgbm 4 imports scipy.sparse at start-up, but nothing else of scipy: install it without dependencies and keep only
# scipy.sparse (+ its _lib/_external), dropping stats, optimize, special, linalg ... and the BLAS libs (~120 MB). It needs numpy and narwhals.
# Then the image drops what is never run: package test suites, pyarrow flight, python's own tests, bytecode caches.
RUN grep -v '^lightgbm' requirements-service.txt > /tmp/req.txt \
    && pip install --no-compile -r /tmp/req.txt \
    && pip install --no-compile --no-deps "lightgbm>=4.3" narwhals scipy \
    && SP=/usr/local/lib/python3.12/site-packages \
    && rm -rf $SP/scipy.libs \
    && (cd $SP/scipy && for d in */; do case "$d" in _lib/|_external/|sparse/) ;; *) rm -rf "$d";; esac; done) \
    && python -c "import lightgbm, scipy.sparse, pandas, pyarrow.parquet, numpy" \
    && find $SP -type d \( -name tests -o -name test \) -prune -exec rm -rf {} + \
    && rm -f $SP/pyarrow/libarrow_flight* \
    && rm -rf /usr/local/lib/python3.12/test /usr/local/lib/python3.12/idlelib /usr/local/lib/python3.12/turtledemo \
    && find /usr/local -name __pycache__ -type d -prune -exec rm -rf {} + \
    && python -c "import lightgbm, scipy.sparse, pandas, pyarrow.parquet, numpy" \
    && rm -rf /tmp/req.txt

COPY ml_service ml_service
COPY scripts/03_soil_ssurgo.py scripts/03_soil_ssurgo.py
COPY config config
COPY models/crop_model models/crop_model
# precomputed counties + the POWER cells they use (+ Lina's files when installed)
COPY deploy/data data

# runs as a normal user; the SDA answers are cached on disk, so that folder must be writable
RUN useradd --create-home app && mkdir -p data/features/ssurgo_cache && chown -R app:app /app
USER app

EXPOSE 8001
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD ["python", "-c", "import os,urllib.request; urllib.request.urlopen('http://localhost:%s/ml/health' % os.environ.get('PORT','8001'), timeout=4)"]

# the port comes from the PORT variable (many hosts set it themselves)
CMD ["sh", "-c", "exec uvicorn ml_service.main:app --host 0.0.0.0 --port ${PORT}"]
