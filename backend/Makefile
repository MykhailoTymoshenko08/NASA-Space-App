.PHONY: install dev test contract-check contract-json lint data data-boundaries data-fields demo

UV ?= uv
HOST ?= 127.0.0.1
PORT ?= 8000

install:
	$(UV) sync

dev:
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

data-boundaries:
	$(UV) run python scripts/prepare_boundaries.py

data-fields:
	$(UV) run python scripts/prepare_field_data.py

data: data-boundaries data-fields

demo:
	@test -f data/fields.pmtiles -a -f data/boundaries.pmtiles || $(MAKE) data
	$(MAKE) dev
