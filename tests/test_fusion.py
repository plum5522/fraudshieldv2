import pytest

from app.fusion import fuse


def test_doc_example_unsure_text_plus_reports():
    v = fuse(0.60, 5)
    assert v.probability == pytest.approx(0.90, abs=0.01)
    assert v.tier == "confirmed_scam"


def test_new_scammer_text_alone_warns():
    v = fuse(0.60, 0)
    assert v.probability == pytest.approx(0.60, abs=0.001)
    assert v.tier == "suspicious"


def test_fake_reports_cannot_convict_normal_message():
    v = fuse(0.05, 5)
    assert v.probability == pytest.approx(0.24, abs=0.01)
    assert v.tier in ("safe", "suspicious")


def test_text_alone_never_confirmed():
    v = fuse(0.99, 0)
    assert v.tier == "likely_scam"


def test_diminishing_returns():
    gain = lambda a, b: fuse(0.5, b).probability - fuse(0.5, a).probability  # noqa: E731
    assert gain(0, 1) > gain(10, 11) > 0


def test_more_reports_never_lower_the_score():
    probs = [fuse(0.3, n).probability for n in range(0, 50)]
    assert probs == sorted(probs)


def test_extreme_inputs_stay_finite():
    # p = 0 or 1 would make logit infinite; inputs are clamped to [0.01, 0.99] first
    assert 0 < fuse(0.0, 0).probability < 0.05
    assert fuse(1.0, 10_000).probability <= 1.0
