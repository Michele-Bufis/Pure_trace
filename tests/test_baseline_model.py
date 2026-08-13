import numpy as np
import pytest

from pure_trace import config
from pure_trace.analysis_engine import (
    features_to_vector, _FEATURE_NAMES, BaselineModel,
)


def test_feature_names_order():
    assert _FEATURE_NAMES == ["mean_hr", "sdnn", "rmssd", "pnn50"]


def test_vector_from_full_features():
    feats = {"mean_rr": 1.0, "sdnn": 0.05, "rmssd": 0.04, "pnn50": 10.0}
    vec = features_to_vector(feats)
    np.testing.assert_allclose(vec, [60.0, 0.05, 0.04, 10.0])


def test_vector_none_when_short_session():
    feats = {"mean_rr": 1.0, "sdnn": None, "rmssd": None, "pnn50": None}
    assert features_to_vector(feats) is None


def test_not_ready_below_min_sessions():
    m = BaselineModel([[60.0, 0.05, 0.04, 10.0]] * 4)
    assert m.ready() is False
    status, d2 = m.classify(np.array([60.0, 0.05, 0.04, 10.0]))
    assert status == "NEUTRAL"
    assert np.isnan(d2)


def test_diagonal_mahalanobis_known_value():
    # pool 2D, n=5 (<10) => covarianza diagonale; var per colonna = 1.0
    pool = [[0, 0], [2, 0], [0, 2], [2, 2], [1, 1]]
    m = BaselineModel(pool)
    d2 = m.mahalanobis2(np.array([3.0, 1.0]))  # delta=[2,0], var=[1,1]
    assert abs(d2 - 4.0) < 1e-3


def test_identical_pool_is_invertible():
    m = BaselineModel([[1.0, 1.0]] * 5)
    # varianza nulla + ridge => nessuna eccezione, distanza ~0 al centro
    assert abs(m.mahalanobis2(np.array([1.0, 1.0]))) < 1e-3


def test_classify_green_at_center():
    pool = [[0, 0], [2, 0], [0, 2], [2, 2], [1, 1]]
    m = BaselineModel(pool)
    status, _ = m.classify(np.array([1.0, 1.0]))  # = media => d2≈0
    assert status == "GREEN"


def test_classify_red_when_far():
    pool = [[0, 0], [2, 0], [0, 2], [2, 2], [1, 1]]
    m = BaselineModel(pool)
    status, _ = m.classify(np.array([10.0, 10.0]))
    assert status == "RED"


# ---------------------------------------------------------------------------
# Calibrazione delle soglie (Hotelling T², non χ²)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("n", [5, 8, 12, 25])
def test_false_positive_rate_matches_target(n):
    """Una sessione realmente normale deve essere RED ~1% delle volte e
    YELLOW-o-RED ~5%, a QUALSIASI dimensione del pool.

    Con le soglie χ² (media e covarianza trattate come note, mentre sono
    stimate) il tasso di RED falsi era ~20% a n=5: un paziente sano riceveva un
    allarme rosso una volta su cinque. Questo test blocca quella regressione."""
    rng = np.random.default_rng(20260710)
    d = len(_FEATURE_NAMES)
    trials = 1500
    red = yellow_or_red = 0
    for _ in range(trials):
        model = BaselineModel(list(rng.normal(size=(n, d))))
        status, _ = model.classify(rng.normal(size=d))
        if status == "RED":
            red += 1
        if status in ("RED", "YELLOW"):
            yellow_or_red += 1
    red_rate = red / trials
    flag_rate = yellow_or_red / trials
    # bande generose: qui interessa escludere il 20%, non validare la 3a cifra
    assert red_rate < 0.030, f"n={n}: RED falsi {red_rate:.1%}, attesi ~1%"
    assert flag_rate < 0.085, f"n={n}: YELLOW+RED falsi {flag_rate:.1%}, attesi ~5%"


def test_neutral_when_pool_too_small_to_calibrate(monkeypatch):
    """Con n <= n_feature la F non ha gradi di libertà validi: niente scoring."""
    monkeypatch.setattr(config, "MIN_BASELINE_SESSIONS", 3)
    model = BaselineModel([[1.0, 2.0, 3.0, 4.0]] * 4)   # n=4, d=4 => n-d=0
    assert model.ready() is True
    status, d2 = model.classify(np.array([9.0, 9.0, 9.0, 9.0]))
    assert status == "NEUTRAL"
    assert np.isnan(d2)


def test_thresholds_widen_as_pool_shrinks():
    """Meno sessioni => più incertezza sulla stima => soglie più larghe."""
    rng = np.random.default_rng(3)
    pool = list(rng.normal(size=(40, 4)))
    small = BaselineModel(pool[:6])._thresholds(4)
    large = BaselineModel(pool)._thresholds(4)
    assert small[0] > large[0] and small[1] > large[1]


def test_add_respects_cap(monkeypatch):
    from pure_trace import config
    monkeypatch.setattr(config, "FEATURE_POOL_CAP", 3)
    m = BaselineModel([[1.0, 1.0]])
    for _ in range(5):
        m.add(np.array([2.0, 2.0]))
    assert m.n == 3
