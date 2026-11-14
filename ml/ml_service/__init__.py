"""FieldShift ML service (mock engine, contract v1)."""

# "-mock" marks that numbers come from a simple deterministic model, not the trained one
MODEL_VERSION = "0.1.0-mock"

# demo region and years from the api contract
COVERAGE_STATES = ("IA", "IL", "NE", "KS")
COVERAGE_YEARS = (2018, 2025)
