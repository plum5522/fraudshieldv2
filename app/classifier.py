"""Loads the trained text model once and scores messages.

The model file is produced by `python -m ml.train` and committed (1.1 MB), so the API
starts without a training step and every deploy runs the exact model that was evaluated.
"""

from functools import lru_cache
from pathlib import Path

import joblib

from app.textprep import prepare_for_model

MODEL_PATH = Path(__file__).resolve().parent.parent / "models" / "scam_clf.joblib"


class TextClassifier:
    def __init__(self, path: Path = MODEL_PATH):
        bundle = joblib.load(path)
        self._model = bundle["model"]
        self.version: str = bundle["version"]

    def scam_probability(self, message: str) -> float:
        x = prepare_for_model(message)  # identical preparation to training
        return float(self._model.predict_proba([x])[0, 1])


@lru_cache(maxsize=1)
def get_classifier() -> TextClassifier:
    """Load once per process (about 50 ms), then reuse. Also a FastAPI dependency,
    so tests can swap in a fake classifier with fixed outputs."""
    return TextClassifier()
