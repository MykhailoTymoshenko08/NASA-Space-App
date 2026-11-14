.PHONY: install dev test contract-check contract-json lint data data-boundaries data-fields demo

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

data-fields:
	$(UV) run python scripts/prepare_field_data.py $(FORCE_FLAG)

data: data-boundaries data-fields

# Boot everything for a demo: install deps, build data if missing, run the API.
demo: install
	@test -f data/fields.pmtiles -a -f data/boundaries.pmtiles || $(MAKE) data
	$(UV) run uvicorn app.main:app --host $(HOST) --port $(PORT)
