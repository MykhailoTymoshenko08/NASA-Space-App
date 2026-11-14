"""Regenerate contract/openapi.json from openapi.yaml, or check they are in sync (--check)."""

import json
import sys
from pathlib import Path

import yaml

CONTRACT = Path(__file__).resolve().parents[2] / "contract"


def render() -> str:
    data = yaml.safe_load((CONTRACT / "openapi.yaml").read_text())
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def main() -> int:
    out = CONTRACT / "openapi.json"
    text = render()
    if "--check" in sys.argv:
        if json.loads(out.read_text()) != json.loads(text):
            print("contract/openapi.json is out of date: run `make contract-json`", file=sys.stderr)
            return 1
        print("openapi.json in sync")
        return 0
    out.write_text(text)
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
