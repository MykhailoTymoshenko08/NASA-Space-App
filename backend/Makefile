.PHONY: install dev test contract-check contract-json lint db data data-boundaries data-csb data-tiles serve-tiles demo docker

UV ?= uv
HOST ?= 127.0.0.1
PORT ?= 8000
COMPOSE ?= docker compose

install:
	$(UV) sync

dev: install
	$(UV) run uvicorn app.main:app --reload --host $(HOST) --port $(PORT)

# Needs PostGIS (`make db`): tests create and drop their own scratch database.
test:
	$(UV) run pytest -q

# Contract tests only: every endpoint's real responses validated against ../contract/openapi.yaml,
# plus a check that openapi.json is in sync with the YAML. CI fails on drift.
contract-check:
	$(UV) run pytest -q -m contract
	$(UV) run python scripts/contract_json.py --check

contract-json:
	$(UV) run python scripts/contract_json.py

lint:
	$(UV) run ruff check app scripts tests

# PostGIS (docker-compose.yml), waits until it accepts connections.
db:
	$(COMPOSE) up -d --wait db

# FORCE=1 rebuilds outputs that already exist.
FORCE_FLAG = $(if $(FORCE),--force,)

data-boundaries:
	$(UV) run python scripts/prepare_boundaries.py $(FORCE_FLAG)

# USDA CSB polygons + crop history for IA, IL, NE into PostGIS (downloads ~3.8 GB once).
data-csb: db
	$(UV) run python scripts/prepare_csb.py import $(FORCE_FLAG)

# data/csb_ia_il_ne.pmtiles from PostGIS (tippecanoe). Host it outside the backend (README).
data-tiles: db
	$(UV) run python scripts/prepare_csb.py tiles $(FORCE_FLAG)

data: data-boundaries data-csb data-tiles

# Local static server for the field PMTiles with Range + CORS (dev stand-in for R2/S3).
TILES_PORT ?= 8787
serve-tiles:
	$(UV) run python scripts/serve_tiles.py --port $(TILES_PORT)

# Boot everything for a demo: install deps, build data if missing, run the API.
demo: install
	@test -f data/boundaries.pmtiles -a -f data/csb_ia_il_ne.pmtiles || $(MAKE) data
	$(UV) run uvicorn app.main:app --host $(HOST) --port $(PORT)

# Image with the boundary data baked in. Field polygons live in PostGIS (DATABASE_URL) and the field
# PMTiles on static hosting (FIELDS_PMTILES_URL), so neither is in the image.
IMAGE ?= field-shift-backend
docker:
	@test -f data/boundaries.pmtiles || $(MAKE) data-boundaries
	docker build -t $(IMAGE) .
