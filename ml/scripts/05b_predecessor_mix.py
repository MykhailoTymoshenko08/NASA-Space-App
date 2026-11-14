"""
step 5b - which previous crops usually come before each crop, per state -> models/crop_model/predecessor_mix.json

Used for `fit_score` in the crop ranking: how well a crop suits the field WITHOUT knowing last year's crop. The model's
probability is averaged over the predecessors that really precede this crop in the state (the pairs of crops of the
two previous years, top 12 pairs of every crop, weights add up to 1). So soybean is judged "after corn, mostly", not
"after soybean".

input:  data/dataset/crops_train.parquet (step 4)
output: models/crop_model/predecessor_mix.json   {state or "ALL": {crop: {"n": rows, "pairs": [[prev_crop_1, prev_crop_2, weight], ...]}}}
        a state with fewer than MIN_ROWS rows of a crop falls back to "ALL" when the ranking reads this file
"""
import json
from pathlib import Path

import pandas as pd

STATES = {"19": "IA", "17": "IL", "20": "KS", "31": "NE"}
TOP = 12


def mix(df: pd.DataFrame) -> dict:
    out = {}
    for crop, g in df.groupby("crop"):
        counts = g.groupby(["prev_crop_1", "prev_crop_2"], dropna=False).size().sort_values(ascending=False).head(TOP)
        w = counts / counts.sum()
        out[crop] = {"n": int(len(g)), "pairs": [[a, (None if pd.isna(b) else b), round(float(x), 4)] for (a, b), x in w.items()]}
    return out


def main() -> None:
    df = pd.read_parquet("data/dataset/crops_train.parquet")
    result = {"ALL": mix(df)}
    for fips, abbr in STATES.items():
        result[abbr] = mix(df[df["state_fips"] == fips])
    path = Path("models/crop_model/predecessor_mix.json")
    path.write_text(json.dumps(result, indent=1))
    for abbr in ("IA", "KS"):
        for crop in ("soybean", "winter_wheat"):
            top = result[abbr].get(crop, {"pairs": []})["pairs"][:3]
            print(f"{abbr} {crop:<13} usually follows:", [(a, round(w, 2)) for a, b, w in top])
    print("saved", path)


if __name__ == "__main__":
    main()
