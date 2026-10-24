"""The ONE function that turns a raw message into model input.

Training (ml/train.py) and the live API both call this, so the model always sees text
prepared exactly the way it was trained on. If the two drifted apart (say, training
masked links but serving didn't), accuracy would silently collapse in production. This
bug is common enough to have a name: training/serving skew.
"""

import re

from app.extract import clean_message, mask_entities
from app.trust import is_trusted


def _placeholder(entity):
    # A link to an official site (sbi.co.in, *.gov.in) is real evidence of a legitimate
    # message, and we know it at serving time, so the model gets to see that difference.
    return "<SAFE_URL>" if is_trusted(entity) else None


def prepare_for_model(text: str) -> str:
    text = clean_message(text)                    # drop "Airtel Warning: SPAM |" labels (leakage)
    text = mask_entities(text, _placeholder)      # UPI/phone/link -> <UPI> <PHONE> <URL> / <SAFE_URL>
    text = re.sub(r"\d", "0", text)  # "Rs 3022" and "Rs 499" look the same: amounts are noise
    return re.sub(r"\s+", " ", text).strip()


def template_key(text: str) -> str:
    """Groups template copies together for train/test splitting.

    Synthetic datasets repeat one template with different names, cities and numbers
    ("Dear Neha, your library book..." / "Dear Suresh, your library book..."). If copies
    of a template land in both train and test, the test just measures memorisation.
    Dropping digits and capitalised words (names, places) collapses copies to one key.
    """
    words = prepare_for_model(text).split()
    kept = [w for i, w in enumerate(words) if i == 0 or not w[:1].isupper()]
    return " ".join(kept).lower()
