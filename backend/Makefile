.PHONY: install dev test contract-check contract-json lint data data-boundaries data-plss demo docker

UV ?= uv
HOST ?= 127.0.0.1
PORT ?= 8000

install:
	$(UV) sync

dev: install
	$(UV) run uvicorn app.main:app --reload --host $(HOST) --port $(PORT)

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

# FORCE=1 rebuilds outputs that already exist (e.g. after changing PILOT_REGION).
FORCE_FLAG = $(if $(FORCE),--force,)

data-boundaries:
	$(UV) run python scripts/prepare_boundaries.py $(FORCE_FLAG)

# BLM PLSS sections + townships for PLSS_STATES; also rebuilds boundary tiles with townships.
data-plss:
	$(UV) run python scripts/prepare_plss.py $(FORCE_FLAG)

data: data-boundaries data-plss

# Boot everything for a demo: install deps, build data if missing, run the API.
demo: install
	@test -f data/fields.pmtiles -a -f data/boundaries.pmtiles || $(MAKE) data
	$(UV) run uvicorn app.main:app --host $(HOST) --port $(PORT)

# Image with data/ baked in. Builds data first if the tiles are missing.
IMAGE ?= field-shift-backend
docker:
	@test -f data/fields.pmtiles -a -f data/boundaries.pmtiles || $(MAKE) data
	docker build -t $(IMAGE) .
