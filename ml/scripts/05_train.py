"""
step 5 - train the crop classifier (LightGBM multiclass, 5 classes), calibrate it, measure it honestly.

input:  data/dataset/crops_train.parquet (step 4), config/candidate_crops.yaml
output: models/crop_model/{model.txt, calibrator.json, feature_list.json, metrics.json, reliability.png}

model: NO class balancing (balancing distorts the probabilities, and the ranking multiplies them), then the
probabilities are calibrated (temperature scaling or isotonic, whichever is better in cross-validation).

two validations on out-of-fold predictions
  (a) MAIN  grouped by field: 5 folds, a field is never in train and test together -> "fields the model has not seen"
  (b)       leave-one-year-out: train on 6 seasons, test the 7th (the same fields are in train -> optimistic for new fields)
calibration is fitted on the out-of-fold probabilities of (a) and judged by cross-fitting: the calibrator is fitted on
80% of the fields and evaluated on the other 20%, so the "after" numbers are not fitted on what they are tested on.
baselines (fitted on the training part only)
  alternation        corn <-> soybean by turns; after any other crop: the state's most common crops
  same_as_last_year  the crop that grew last year
  state_most_common  the state's most common crops
metrics: top-1, top-3, macro-F1, log-loss, Brier, ECE, confusion matrix; extra: rows after corn / after soybean,
per state, and a field-level bootstrap interval for the gain over alternation.

usage: python scripts/05_train.py
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
import yaml
from scipy.optimize import minimize_scalar
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import confusion_matrix, f1_score, log_loss
from sklearn.model_selection import StratifiedGroupKFold

SEED = 42
DROP_COLS = {"field_id", "year", "crop", "slope_source"}
CAT_COLS = ["state_fips", "prev_crop_1", "prev_crop_2", "hydgrp", "drainage_class", "texture_class"]
PARAMS = dict(n_estimators=300, learning_rate=0.05, num_leaves=31, min_child_samples=15, subsample=0.8,
              subsample_freq=1, colsample_bytree=0.7, reg_lambda=1.0, random_state=SEED, n_jobs=-1, verbose=-1)
N_BINS = 10

CLASS_UK = {"corn": "кукурудзу", "soybean": "сою", "winter_wheat": "озиму пшеницю", "sorghum": "сорго",
            "alfalfa": "люцерну"}
BASE_DESC = {
    "prev_crop_1": "що росло на полі торік", "prev_crop_2": "що росло на полі позаторік",
    "lat": "широта поля (північ-південь)", "lon": "довгота поля (схід-захід)", "state_fips": "штат",
    "clay_pct": "вміст глини в ґрунті", "sand_pct": "вміст піску в ґрунті", "om_pct": "органічна речовина в ґрунті",
    "soc_pct": "органічний вуглець у ґрунті", "ph_h2o": "кислотність ґрунту (pH)", "ec_ds_m": "засоленість ґрунту",
    "awc_cm_cm": "здатність ґрунту тримати воду", "kw_factor": "схильність ґрунту до ерозії",
    "hydgrp": "гідрологічна група ґрунту", "drainage_class": "дренаж ґрунту", "texture_class": "текстура ґрунту",
    "slope_pct": "ухил поля", "twi": "індекс вологості рельєфу",
    "gdd_grow": "сума активних температур за сезон (тепло)", "tmean_grow": "середня температура вегетації",
    "tmax_summer": "літня максимальна температура", "heat_days_32": "днів спеки понад 32°C",
    "heat_days_35": "днів сильної спеки понад 35°C", "precip_grow": "опади за вегетацію",
    "precip_spring": "весняні опади", "precip_summer": "літні опади", "et0_grow": "випаровування за вегетацію",
    "water_balance_grow": "водний баланс (опади мінус випаровування)", "max_dry_spell": "найдовша посуха, днів",
    "extreme_rain_days_spring": "днів сильних весняних дощів", "extreme_rain_days_year": "днів сильних дощів за рік",
    "last_spring_frost_doy": "день останнього весняного заморозку", "first_fall_frost_doy": "день першого осіннього заморозку",
    "frost_free_days": "безморозних днів", "srad_grow": "сонячна радіація за сезон", "rh_summer": "літня вологість повітря",
}


def describe_feature(name: str) -> str:
    if name.startswith("norm_"):
        return "типове (середнє за 2017-2025): " + BASE_DESC.get(name[5:], name[5:])
    if name.startswith("lag1_"):
        return "торішнє значення: " + BASE_DESC.get(name[5:], name[5:])
    return BASE_DESC.get(name, name)


# --------------------------------------------------------------------------- data

def load(path: Path, classes: list[str]):
    df = pd.read_parquet(path)
    df = df[df["crop"].isin(classes)].reset_index(drop=True)
    features = [c for c in df.columns if c not in DROP_COLS and df[c].notna().any()]
    levels = {c: sorted(df[c].dropna().unique().tolist()) for c in CAT_COLS if c in features}
    for c in ("prev_crop_1", "prev_crop_2"):  # fixed order so the service can rebuild the same categories
        levels[c] = [*classes, "other"]
    y = df["crop"].map({c: i for i, c in enumerate(classes)}).to_numpy()
    return df, features, levels, y


def make_x(df: pd.DataFrame, features: list[str], levels: dict) -> pd.DataFrame:
    x = df[features].copy()
    for c, lv in levels.items():
        x[c] = pd.Categorical(x[c], categories=lv)
    return x


def fit_predict(train: pd.DataFrame, y_train: np.ndarray, test: pd.DataFrame, features, levels, balanced: bool):
    model = lgb.LGBMClassifier(objective="multiclass", class_weight="balanced" if balanced else None, **PARAMS)
    model.fit(make_x(train, features, levels), y_train)
    assert list(model.classes_) == list(range(len(model.classes_))), "a class is missing from the training part"
    return model, model.predict_proba(make_x(test, features, levels))


# --------------------------------------------------------------------------- baselines

def baseline_scores(kind: str, train: pd.DataFrame, y_train: np.ndarray, test: pd.DataFrame, classes: list[str]):
    """score matrix (n_test x n_classes), higher = more likely. built from the training part only."""
    k = len(classes)
    glob = np.bincount(y_train, minlength=k) / len(y_train)
    freq = pd.DataFrame({"s": train["state_fips"].to_numpy(), "y": y_train}).groupby("s")["y"].apply(
        lambda v: np.bincount(v, minlength=k) / len(v))
    base = np.vstack([freq.get(s, glob) for s in test["state_fips"]])
    if kind == "state_most_common":
        return base
    scores = base.copy()
    idx = {c: i for i, c in enumerate(classes)}
    prev = test["prev_crop_1"].to_numpy()
    if kind == "same_as_last_year":
        for i, p in enumerate(prev):
            if p in idx:
                scores[i, idx[p]] += 2
    elif kind == "alternation":
        corn, soy = idx["corn"], idx["soybean"]
        for i, p in enumerate(prev):
            if p == "corn":
                scores[i, soy] += 2
                scores[i, corn] += 1
            elif p == "soybean":
                scores[i, corn] += 2
                scores[i, soy] += 1
    return scores


BASELINES = ["alternation", "same_as_last_year", "state_most_common"]


# --------------------------------------------------------------------------- metrics

def topk(scores: np.ndarray, y: np.ndarray, k: int) -> float:
    top = np.argsort(-scores, axis=1)[:, :k]
    return float((top == y[:, None]).any(axis=1).mean())


def reliability(p: np.ndarray, y: np.ndarray, top_label: bool) -> list[dict]:
    """bins of predicted probability vs how often it happened. top_label: only the predicted class (confidence vs
    accuracy); otherwise every class probability of every row (classwise)."""
    if top_label:
        conf, hit = p.max(1), (p.argmax(1) == y).astype(float)
    else:
        conf, hit = p.ravel(), (np.arange(p.shape[1])[None, :] == y[:, None]).ravel().astype(float)
    b = np.minimum((conf * N_BINS).astype(int), N_BINS - 1)
    rows = []
    for i in range(N_BINS):
        m = b == i
        rows.append({"bin": f"{i / N_BINS:.1f}-{(i + 1) / N_BINS:.1f}", "n": int(m.sum()),
                     "mean_pred": float(conf[m].mean()) if m.any() else None,
                     "observed": float(hit[m].mean()) if m.any() else None})
    return rows


def ece(rel: list[dict]) -> float:
    n = sum(r["n"] for r in rel)
    return float(sum(r["n"] * abs(r["mean_pred"] - r["observed"]) for r in rel if r["n"]) / n)


def brier(p: np.ndarray, y: np.ndarray) -> float:
    return float(((p - (np.arange(p.shape[1])[None, :] == y[:, None])) ** 2).sum(1).mean())


def metrics(y: np.ndarray, scores: np.ndarray, n_classes: int, is_proba: bool) -> dict:
    pred = scores.argmax(1)
    cm = confusion_matrix(y, pred, labels=range(n_classes))
    out = {
        "top1": float((pred == y).mean()),
        "top3": topk(scores, y, 3),
        "macro_f1": float(f1_score(y, pred, average="macro", labels=range(n_classes), zero_division=0)),
        "log_loss": float(log_loss(y, np.clip(scores, 1e-15, 1), labels=range(n_classes))) if is_proba else None,
        "recall_per_class": (cm.diagonal() / np.maximum(cm.sum(1), 1)).round(4).tolist(),
        "confusion_matrix": cm.tolist(),
    }
    if is_proba:
        out["brier"] = brier(scores, y)
        out["ece_top_label"] = ece(reliability(scores, y, True))
        out["ece_classwise"] = ece(reliability(scores, y, False))
    return out


# --------------------------------------------------------------------------- calibration

def apply_temperature(p: np.ndarray, t: float) -> np.ndarray:
    q = np.clip(p, 1e-12, 1.0) ** (1.0 / t)
    return q / q.sum(1, keepdims=True)


def fit_temperature(p: np.ndarray, y: np.ndarray) -> float:
    res = minimize_scalar(lambda t: log_loss(y, apply_temperature(p, t), labels=range(p.shape[1])),
                          bounds=(0.3, 3.0), method="bounded")
    return float(res.x)


def fit_isotonic(p: np.ndarray, y: np.ndarray) -> list[IsotonicRegression]:
    return [IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip").fit(p[:, c], (y == c).astype(float))
            for c in range(p.shape[1])]


def apply_isotonic(models, p: np.ndarray) -> np.ndarray:
    cal = np.column_stack([m.predict(p[:, c]) for c, m in enumerate(models)])
    cal = np.clip(cal, 1e-6, 1.0)  # never exactly 0: a probability of 0 would erase a crop for good
    return cal / cal.sum(1, keepdims=True)


def cross_fit_calibration(p: np.ndarray, y: np.ndarray, groups: np.ndarray) -> dict:
    """calibrated out-of-fold probabilities where each calibrator never saw the fields it is applied to."""
    out = {"temperature": np.zeros_like(p), "isotonic": np.zeros_like(p)}
    splitter = StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=SEED + 1)
    for tr, te in splitter.split(p, y, groups):
        out["temperature"][te] = apply_temperature(p[te], fit_temperature(p[tr], y[tr]))
        out["isotonic"][te] = apply_isotonic(fit_isotonic(p[tr], y[tr]), p[te])
    return out


def calibrator_to_json(method: str, p: np.ndarray, y: np.ndarray) -> dict:
    """fit on all out-of-fold probabilities and make it storable."""
    if method == "temperature":
        return {"method": "temperature", "temperature": fit_temperature(p, y)}
    models = fit_isotonic(p, y)
    return {"method": "isotonic", "curves": [{"x": m.X_thresholds_.tolist(), "y": m.y_thresholds_.tolist()} for m in models]}


def plot_reliability(path: Path, curves: dict[str, np.ndarray], y: np.ndarray, chosen: str) -> bool:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return False
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.8))
    styles = {"raw": ("#c0392b", "до калібрування"), chosen: ("#1f6fb2", f"після ({chosen})")}
    for ax, top, title in ((axes[0], True, "Найімовірніша культура: впевненість vs влучність"),
                           (axes[1], False, "Усі ймовірності всіх культур")):
        ax.plot([0, 1], [0, 1], "--", color="gray", lw=1, label="ідеально")
        for key, (color, label) in styles.items():
            rel = [r for r in reliability(curves[key], y, top) if r["n"] >= 20]
            ax.plot([r["mean_pred"] for r in rel], [r["observed"] for r in rel], "o-", color=color, label=label)
        ax.set_xlabel("що передбачила модель")
        ax.set_ylabel("як часто це справді було")
        ax.set_title(title, fontsize=10)
        ax.grid(alpha=0.3)
        ax.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)
    return True


# --------------------------------------------------------------------------- validation schemes

def run_scheme(df, y, features, levels, classes, splits, with_ablation: bool):
    """out-of-fold predictions for the model and the baselines over the given (train_idx, test_idx) splits."""
    n, k = len(df), len(classes)
    oof = {"model": np.zeros((n, k))}
    if with_ablation:
        oof["model_balanced"] = np.zeros((n, k))
    for b in BASELINES:
        oof[b] = np.zeros((n, k))
    per_fold = []
    for f, (tr, te) in enumerate(splits):
        t0 = time.time()
        train, test = df.iloc[tr], df.iloc[te]
        _, oof["model"][te] = fit_predict(train, y[tr], test, features, levels, False)
        if with_ablation:
            _, oof["model_balanced"][te] = fit_predict(train, y[tr], test, features, levels, True)
        for b in BASELINES:
            oof[b][te] = baseline_scores(b, train, y[tr], test, classes)
        m = metrics(y[te], oof["model"][te], k, True)
        per_fold.append({"fold": f, "rows": int(len(te)), "top1": m["top1"], "top3": m["top3"], "macro_f1": m["macro_f1"]})
        print(f"    fold {f}: top-1 {m['top1']:.3f}  top-3 {m['top3']:.3f}  macro-F1 {m['macro_f1']:.3f}  ({time.time() - t0:.0f}s)", flush=True)
    return oof, per_fold


def summarize(y, oof, classes, mask=None):
    k = len(classes)
    sel = np.ones(len(y), bool) if mask is None else mask
    res = {}
    for name, s in oof.items():
        res[name] = metrics(y[sel], s[sel], k, is_proba=name in ("model", "model_balanced", "model_calibrated", "state_most_common"))
        res[name]["rows"] = int(sel.sum())
    return res


def bootstrap_gain(correct_a: np.ndarray, correct_b: np.ndarray, groups: np.ndarray, n_boot: int = 2000):
    """mean(a) - mean(b) with a 95% interval, resampling whole fields (rows of one field are not independent)."""
    codes, uniq = pd.factorize(groups)
    sums = np.bincount(codes, weights=correct_a.astype(float) - correct_b.astype(float), minlength=len(uniq))
    cnt = np.bincount(codes, minlength=len(uniq))
    rng = np.random.default_rng(SEED)
    draws = rng.integers(0, len(uniq), size=(n_boot, len(uniq)))
    gains = sums[draws].sum(1) / cnt[draws].sum(1)
    return {"gain": float(sums.sum() / cnt.sum()), "ci95": [float(np.percentile(gains, 2.5)), float(np.percentile(gains, 97.5))]}


# --------------------------------------------------------------------------- shap

def shap_summary(booster, x: pd.DataFrame, features: list[str], classes: list[str], top: int = 15) -> list[dict]:
    """TreeSHAP values straight from lightgbm (pred_contrib). importance = mean |contribution| over rows and classes."""
    k, f = len(classes), len(features)
    contrib = booster.predict(x, pred_contrib=True).reshape(len(x), k, f + 1)[:, :, :f]
    imp = np.abs(contrib).mean(axis=(0, 1))
    per_class = np.abs(contrib).mean(axis=0)  # classes x features
    rows = []
    for j in np.argsort(-imp)[:top]:
        name = features[j]
        c = int(per_class[:, j].argmax())
        col = x[name]
        if str(col.dtype) == "category":
            means = pd.Series(contrib[:, c, j]).groupby(col.to_numpy()).agg(["mean", "size"])
            means = means[means["size"] >= 30]["mean"]
            best = str(means.idxmax()) if len(means) else None
            hint = f"найбільше «за» {CLASS_UK[classes[c]]}, коли значення = {best}"
            direction = None
        else:
            corr = pd.Series(col.astype(float).to_numpy()).corr(pd.Series(contrib[:, c, j]), method="spearman")
            direction = "up" if corr > 0 else "down"
            hint = f"чим більше значення, тим {'більша' if corr > 0 else 'менша'} ймовірність: {CLASS_UK[classes[c]]}"
        rows.append({"feature": name, "plain": describe_feature(name), "importance": float(imp[j]),
                     "share_pct": float(100 * imp[j] / imp.sum()), "main_class": classes[c],
                     "direction": direction, "hint_uk": hint})
    return rows


# --------------------------------------------------------------------------- main

def fmt(m: dict) -> str:
    ll = f"{m['log_loss']:.3f}" if m["log_loss"] is not None else "  -  "
    return f"top-1 {m['top1']:.3f}  top-3 {m['top3']:.3f}  macro-F1 {m['macro_f1']:.3f}  log-loss {ll}"


def print_reliability(raw: np.ndarray, cal: np.ndarray, y: np.ndarray, top_label: bool, title: str) -> None:
    a, b = reliability(raw, y, top_label), reliability(cal, y, top_label)
    print(f"\n  {title}")
    print("    bin        |      BEFORE: n   predicted  observed |      AFTER: n   predicted  observed")
    for ra, rb in zip(a, b):
        f = lambda r: f"{r['n']:>6}   {r['mean_pred']:.3f}     {r['observed']:.3f}" if r["n"] else "     -       -         -"
        print(f"    {ra['bin']:<10} | {f(ra):<36}| {f(rb)}")
    print(f"    ECE: before {ece(a):.4f} -> after {ece(b):.4f}")


def main() -> None:
    p = argparse.ArgumentParser(description="train, calibrate and validate the crop classifier")
    p.add_argument("--data", default="data/dataset/crops_train.parquet")
    p.add_argument("--candidates", default="config/candidate_crops.yaml")
    p.add_argument("--out", default="models/crop_model")
    p.add_argument("--folds", type=int, default=5)
    args = p.parse_args()

    cand = yaml.safe_load(Path(args.candidates).read_text())["crops"]
    classes = [s for s, c in cand.items() if c["model"]]
    df, features, levels, y = load(Path(args.data), classes)
    groups = df["field_id"].to_numpy()
    print(f"{len(df):,} rows, {df['field_id'].nunique():,} fields, {len(features)} features, classes {classes}")

    # (a) grouped by field - the main check. stratified so the rare classes are in every fold.
    print("\n(a) GROUPED BY FIELD (fields unseen by the model), 5 folds")
    splits_a = list(StratifiedGroupKFold(n_splits=args.folds, shuffle=True, random_state=SEED).split(df, y, groups=groups))
    oof_a, per_fold_a = run_scheme(df, y, features, levels, classes, splits_a, with_ablation=True)

    # (b) leave one year out
    print("\n(b) LEAVE ONE YEAR OUT (same fields seen in other years)")
    years = sorted(df["year"].unique())
    splits_b = [(np.where(df["year"] != yr)[0], np.where(df["year"] == yr)[0]) for yr in years]
    oof_b, _ = run_scheme(df, y, features, levels, classes, splits_b, with_ablation=False)

    # ---- calibration (fitted on the out-of-fold probabilities of the main validation)
    print("\ncalibration ...", flush=True)
    raw = oof_a["model"]
    crossfit = cross_fit_calibration(raw, y, groups)
    scores = {name: {"log_loss": float(log_loss(y, pp, labels=range(len(classes)))), "brier": brier(pp, y),
                     "ece_top_label": ece(reliability(pp, y, True)), "ece_classwise": ece(reliability(pp, y, False))}
              for name, pp in {"raw": raw, **crossfit}.items()}
    chosen = min(crossfit, key=lambda k_: scores[k_]["log_loss"])
    calibrated = crossfit[chosen]
    oof_a["model_calibrated"] = calibrated
    calibrator = calibrator_to_json(chosen, raw, y)

    # ---- results
    res_a, res_b = summarize(y, oof_a, classes), summarize(y, oof_b, classes)
    after = {"after_corn": (df["prev_crop_1"] == "corn").to_numpy(), "after_soybean": (df["prev_crop_1"] == "soybean").to_numpy()}
    sub_a = {name: summarize(y, oof_a, classes, m) for name, m in after.items()}
    state_name = {"17": "IL", "19": "IA", "20": "KS", "31": "NE"}
    by_state = {}
    for st in sorted(df["state_fips"].unique()):
        r = summarize(y, oof_a, classes, (df["state_fips"] == st).to_numpy())
        by_state[state_name.get(st, st)] = {n: {k_: v[k_] for k_ in ("rows", "top1", "top3", "macro_f1")}
                                            for n, v in r.items() if n in ("model", "alternation", "state_most_common")}
    per_year_b = {int(yr): {"rows": int((df["year"] == yr).sum()),
                            **{k_: v for k_, v in metrics(y[df["year"] == yr], oof_b["model"][(df["year"] == yr).to_numpy()],
                                                          len(classes), True).items() if k_ in ("top1", "top3", "macro_f1")}}
                  for yr in years}
    top1 = lambda s: (s.argmax(1) == y)
    boot = {
        "all_rows": bootstrap_gain(top1(oof_a["model"]), top1(oof_a["alternation"]), groups),
        "after_corn": bootstrap_gain(top1(oof_a["model"])[after["after_corn"]], top1(oof_a["alternation"])[after["after_corn"]], groups[after["after_corn"]]),
        "after_soybean": bootstrap_gain(top1(oof_a["model"])[after["after_soybean"]], top1(oof_a["alternation"])[after["after_soybean"]], groups[after["after_soybean"]]),
    }

    # ---- final model on all data + shap
    print("final model on all data ...", flush=True)
    final, _ = fit_predict(df, y, df.head(5), features, levels, False)
    x_all = make_x(df, features, levels)
    shap_rows = shap_summary(final.booster_, x_all.sample(min(4000, len(x_all)), random_state=SEED), features, classes)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    final.booster_.save_model(str(out_dir / "model.txt"))
    reloaded = lgb.Booster(model_file=str(out_dir / "model.txt"))
    assert np.allclose(reloaded.predict(x_all.head(200)), final.predict_proba(x_all.head(200)), atol=1e-9), \
        "saved model gives different predictions"
    (out_dir / "calibrator.json").write_text(json.dumps(calibrator))
    (out_dir / "feature_list.json").write_text(json.dumps({
        "classes": classes, "features": features, "categorical": list(levels), "category_levels": levels,
        "params": PARAMS, "class_weight": None, "calibrator": calibrator["method"],
        "note": "build the same categories (pd.Categorical with these levels) before predict, then apply calibrator.json",
    }, indent=2, ensure_ascii=False))
    plotted = plot_reliability(out_dir / "reliability.png", {"raw": raw, chosen: calibrated}, y, chosen)

    metrics_json = {
        "created": pd.Timestamp.now().isoformat(timespec="seconds"),
        "rows": int(len(df)), "fields": int(df["field_id"].nunique()), "classes": classes,
        "class_counts": {c: int((y == i).sum()) for i, c in enumerate(classes)},
        "features": features, "params": PARAMS, "class_weight": None,
        "main_validation": "grouped_by_field",
        "calibration": {"chosen": chosen, "temperature": calibrator.get("temperature"), "cross_fitted_scores": scores,
                        "reliability_top_label": {"before": reliability(raw, y, True), "after": reliability(calibrated, y, True)},
                        "reliability_classwise": {"before": reliability(raw, y, False), "after": reliability(calibrated, y, False)}},
        "grouped_by_field": {"folds": args.folds, "overall": res_a, "per_fold": per_fold_a, "subsets": sub_a,
                             "by_state": by_state, "top1_gain_over_alternation_bootstrap": boot},
        "leave_one_year_out": {"overall": res_b, "per_year": per_year_b},
        "shap_top15": shap_rows,
    }
    (out_dir / "metrics.json").write_text(json.dumps(metrics_json, indent=2, ensure_ascii=False))

    # ---- print
    print("\n" + "=" * 100 + "\nCALIBRATION (cross-fitted on fields: the calibrator never saw the fields it is scored on)\n" + "=" * 100)
    print(f"  {'':<14}{'log-loss':>10}{'Brier':>9}{'ECE top-label':>15}{'ECE classwise':>15}")
    for name, s in scores.items():
        print(f"  {name:<14}{s['log_loss']:>10.4f}{s['brier']:>9.4f}{s['ece_top_label']:>15.4f}{s['ece_classwise']:>15.4f}")
    print(f"  chosen: {chosen}" + (f" (T = {calibrator['temperature']:.3f}; T>1 softens, T<1 sharpens)" if chosen == "temperature" else ""))
    print_reliability(raw, calibrated, y, True, "RELIABILITY, top-label: when the model says 'X% sure', how often is it right?")
    print_reliability(raw, calibrated, y, False, "RELIABILITY, classwise: every crop probability of every row")
    print(f"\n  figure: {out_dir / 'reliability.png'}" if plotted else "\n  (matplotlib missing, no figure)")

    print("\n" + "=" * 100 + "\n(a) GROUPED BY FIELD - fields the model has not seen (MAIN)\n" + "=" * 100)
    for name in ("model", "model_calibrated", "alternation", "same_as_last_year", "state_most_common", "model_balanced"):
        print(f"  {name:<20} {fmt(res_a[name])}")
    for sub, label in (("after_corn", "ROWS AFTER CORN"), ("after_soybean", "ROWS AFTER SOYBEAN")):
        r = sub_a[sub]
        share = pd.Series(y[after[sub]]).value_counts(normalize=True).reindex(range(len(classes))).fillna(0)
        print(f"\n  {label} ({r['model']['rows']:,} rows); what really followed: " +
              ", ".join(f"{classes[i]} {share[i]:.0%}" for i in range(len(classes)) if share[i] > 0.005))
        for name in ("model", "alternation", "same_as_last_year", "state_most_common"):
            print(f"    {name:<20} top-1 {r[name]['top1']:.3f}  top-3 {r[name]['top3']:.3f}  macro-F1 {r[name]['macro_f1']:.3f}")
    print("\n  gain of the model over alternation, top-1 (95% interval, resampling fields):")
    for k_, v in boot.items():
        print(f"    {k_:<14} {100 * v['gain']:+.1f} pp  [{100 * v['ci95'][0]:+.1f}; {100 * v['ci95'][1]:+.1f}]")
    print("\n  by state (top-1: model vs alternation):")
    for st, r in by_state.items():
        print(f"    {st}  rows {r['model']['rows']:>5}   model {r['model']['top1']:.3f}   alternation {r['alternation']['top1']:.3f}"
              f"   gain {100 * (r['model']['top1'] - r['alternation']['top1']):+.1f} pp")
    print("\n  per-class recall of the model:", {c: round(r, 3) for c, r in zip(classes, res_a["model"]["recall_per_class"])})
    print("\n(b) LEAVE ONE YEAR OUT (same fields seen in other years):", fmt(res_b["model"]))
    print("\nTOP-15 FEATURES (SHAP, final model)")
    for i, r in enumerate(shap_rows, 1):
        print(f"{i:>2}. {r['share_pct']:5.1f}%  {r['plain']}  [{r['feature']}]")
    print(f"\nsaved to {out_dir.resolve()}")


if __name__ == "__main__":
    main()
