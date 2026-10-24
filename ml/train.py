"""Train the scam-vs-legitimate text classifier and write models/ + metrics.

Run:  python -m ml.train

Model: TF-IDF (word 1-2 grams + character 2-5 grams) -> logistic regression.
  - Word n-grams catch phrases ("kyc blocked", "digital arrest").
  - Character n-grams catch misspellings, Hinglish spellings and obfuscation ("K.Y.C").
  - Logistic regression gives calibrated probabilities (fusion needs an honest "60%"),
    trains in seconds, and its weights are readable: we can show what it learned.

Three evaluations, from optimistic to honest:
  1. In-distribution: grouped split of the training sources (unseen templates).
  2. Cross-source: train on one dataset, test on the other (a different generator).
     This is the closest thing to "new kinds of message" we can measure.
  3. Real: the documented real scam SMS in data/real/ (small; sanity check, not a score).
"""

import json
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (brier_score_loss, confusion_matrix, precision_score, recall_score,
                             roc_auc_score)
from sklearn.model_selection import GroupShuffleSplit
from sklearn.pipeline import FeatureUnion, Pipeline

from app.textprep import prepare_for_model, template_key

ROOT = Path(__file__).resolve().parent.parent
MODEL_VERSION = "tfidf-lr-" + datetime.now(timezone.utc).strftime("%Y%m%d")
SEED = 42


def load_public() -> pd.DataFrame:
    """Both public datasets in one shape: text, y (1 = scam), source."""
    a = pd.read_csv(ROOT / "data/public/synthetic_audited.csv")
    a = pd.DataFrame({"text": a.text, "y": (a.label == "scam").astype(int), "source": "audited"})
    b = pd.read_csv(ROOT / "data/public/scam_ham_india_en_hinglish_hi.csv")
    b = pd.DataFrame({"text": b.text, "y": (b.label == "scam").astype(int), "source": "india14"})
    df = pd.concat([a, b], ignore_index=True)
    df["x"] = df.text.map(prepare_for_model)
    df["group"] = df.text.map(template_key)
    return df.drop_duplicates("x").reset_index(drop=True)


def build_model() -> Pipeline:
    features = FeatureUnion([
        ("words", TfidfVectorizer(ngram_range=(1, 2), min_df=2, sublinear_tf=True)),
        ("chars", TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 5), min_df=2, sublinear_tf=True)),
    ])
    clf = LogisticRegression(C=4.0, class_weight="balanced", max_iter=3000)
    return Pipeline([("features", features), ("clf", clf)])


def scores(y, p, threshold=0.5) -> dict:
    pred = (p >= threshold).astype(int)
    tn, fp, fn, tp = confusion_matrix(y, pred, labels=[0, 1]).ravel()
    return {
        "n": int(len(y)),
        "auc": round(float(roc_auc_score(y, p)), 4) if len(set(y)) > 1 else None,
        "precision": round(float(precision_score(y, pred, zero_division=0)), 4),
        "recall": round(float(recall_score(y, pred, zero_division=0)), 4),
        "false_positive_rate": round(fp / (fp + tn), 4) if (fp + tn) else None,
        "brier": round(float(brier_score_loss(y, p)), 4),  # calibration: lower is better
        "confusion": {"tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp)},
    }


def top_features(model: Pipeline, k=15) -> dict:
    names = model.named_steps["features"].get_feature_names_out()
    w = model.named_steps["clf"].coef_[0]
    order = np.argsort(w)
    clean = lambda i: names[i].split("__", 1)[1]  # noqa: E731
    return {"scam": [clean(i) for i in order[::-1][:k]], "legit": [clean(i) for i in order[:k]]}


def main():
    df = load_public()
    print(f"{len(df)} unique messages, {df.group.nunique()} templates, {df.y.mean():.0%} scam")
    metrics = {"model_version": MODEL_VERSION, "data": {
        "messages": int(len(df)), "templates": int(df.group.nunique()),
        "by_source": df.source.value_counts().to_dict()}}

    # 1. Grouped split: no template appears on both sides.
    train_idx, test_idx = next(GroupShuffleSplit(n_splits=1, test_size=0.2, random_state=SEED)
                               .split(df, groups=df.group))
    tr, te = df.iloc[train_idx], df.iloc[test_idx]
    m = build_model().fit(tr.x, tr.y)
    metrics["grouped_test"] = scores(te.y.values, m.predict_proba(te.x)[:, 1])

    # 2. Cross-source: each dataset tested by a model that never saw that dataset.
    metrics["cross_source"] = {}
    for held in ["audited", "india14"]:
        a, b = df[df.source != held], df[df.source == held]
        mc = build_model().fit(a.x, a.y)
        metrics["cross_source"][f"test_on_{held}"] = scores(b.y.values, mc.predict_proba(b.x)[:, 1])

    # Final model: all data.
    final = build_model().fit(df.x, df.y)

    # 3. Real documented scams (all positives, so only recall is meaningful).
    real = pd.read_csv(ROOT / "data/real/real_scams.csv")
    p_real = final.predict_proba(real.text.map(prepare_for_model))[:, 1]
    metrics["real_scams"] = {
        "n": int(len(real)),
        "caught_at_0.5": int((p_real >= 0.5).sum()),
        "probabilities": [round(float(p), 3) for p in p_real],
    }
    metrics["top_features"] = top_features(final)

    (ROOT / "models").mkdir(exist_ok=True)
    joblib.dump({"model": final, "version": MODEL_VERSION}, ROOT / "models/scam_clf.joblib")
    (ROOT / "models/metrics.json").write_text(json.dumps(metrics, indent=2, ensure_ascii=False))
    print(json.dumps({k: v for k, v in metrics.items() if k != "top_features"}, indent=2))
    print("top scam features:", metrics["top_features"]["scam"])
    print("top legit features:", metrics["top_features"]["legit"])


if __name__ == "__main__":
    main()
