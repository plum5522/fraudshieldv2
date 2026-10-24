"""Fused detection: combine what the text says with what people have reported.

    logit(final) = logit(p_text) + W * ln(1 + reporters)

Log-odds addition is how independent evidence combines in Bayesian reasoning: each
signal shifts the odds. ln(1 + n) gives diminishing returns, so the 2nd report moves
the score more than the 50th, and a flood of reports can't grow without limit.

Worked examples (W = 1):
    text 60%, 5 reporters  -> ~90%   (unsure text, well-known scammer: very likely scam)
    text 60%, 0 reporters  -> 60%    (new scammer: the text alone still warns)
    text  5%, 5 reporters  -> ~24%   (fake reports against a normal message can't convict it)

W is set by hand. Learning it would need real outcomes (was this message actually a
scam?) that we don't have yet. That's stated openly rather than hidden.
"""

import math
from dataclasses import dataclass

W = 1.0
EPS = 0.01  # keep p away from 0/1 so logit stays finite

# Tier thresholds on the fused probability.
SUSPICIOUS = 0.30
LIKELY = 0.70
CONFIRMED = 0.85  # 60% text + 5 reporters (~0.90) must land here, not on the edge
CONFIRM_MIN_REPORTERS = 3  # the text alone can never make a message "confirmed"


def _logit(p: float) -> float:
    p = min(max(p, EPS), 1 - EPS)
    return math.log(p / (1 - p))


def _sigmoid(z: float) -> float:
    return 1 / (1 + math.exp(-z))


@dataclass
class Verdict:
    tier: str              # safe | suspicious | likely_scam | confirmed_scam
    probability: float     # fused
    text_probability: float
    reporters: int         # most-reported identifier in the message


def fuse(text_probability: float, reporters: int) -> Verdict:
    p = _sigmoid(_logit(text_probability) + W * math.log1p(reporters))
    if p >= CONFIRMED and reporters >= CONFIRM_MIN_REPORTERS:
        tier = "confirmed_scam"
    elif p >= LIKELY:
        tier = "likely_scam"
    elif p >= SUSPICIOUS:
        tier = "suspicious"
    else:
        tier = "safe"
    return Verdict(tier, round(p, 4), round(text_probability, 4), reporters)
