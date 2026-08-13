import numpy as np

from pure_trace import config
from pure_trace.analysis_engine import clean_rr_mask, quality_ok


def test_smooth_physiological_series_all_valid():
    rr = np.array([0.83, 0.85, 0.84, 0.86, 0.83, 0.85])
    assert clean_rr_mask(rr).tolist() == [True] * 6


def test_out_of_range_intervals_rejected():
    rr = np.array([0.85, 0.20, 0.84, 3.0, 0.85])  # 0.20s e 3.0s fuori range
    mask = clean_rr_mask(rr)
    assert mask[1] == False
    assert mask[3] == False
    assert mask[0] == True and mask[2] == True and mask[4] == True


def test_local_jump_rejected():
    # un battito doppio rispetto ai vicini (errore di detection)
    rr = np.array([0.80, 0.80, 1.60, 0.80, 0.80])
    mask = clean_rr_mask(rr)
    assert mask[2] == False
    assert mask[0] and mask[1] and mask[3] and mask[4]


def test_empty_returns_empty():
    assert clean_rr_mask(np.array([])).tolist() == []


def test_burst_of_artifacts_does_not_hijack_the_local_median():
    """Con una finestra da 5, tre artefatti consecutivi ne erano la maggioranza:
    la mediana locale diventava l'artefatto, che veniva accettato mentre la
    frazione di artefatti riportata restava 0%."""
    rr = np.full(60, 0.80)
    rr[30:33] = 0.40                      # nel range fisiologico, ma anomali
    mask = clean_rr_mask(rr)
    assert not mask[30] and not mask[31] and not mask[32]
    assert mask.sum() == 57               # solo i tre artefatti scartati


def test_burst_up_to_half_the_window_is_rejected():
    tolerated = config.ARTIFACT_WINDOW // 2
    for k in range(1, tolerated + 1):
        rr = np.full(60, 0.80)
        rr[30:30 + k] = 0.40
        mask = clean_rr_mask(rr)
        assert not mask[30:30 + k].any(), f"raffica di {k} non rilevata"


def test_interval_does_not_validate_itself():
    """Un artefatto isolato non deve entrare nella propria mediana di riferimento."""
    rr = np.full(11, 0.80)
    rr[5] = 0.40
    assert not clean_rr_mask(rr)[5]


def test_heart_rate_drift_is_not_mistaken_for_artifacts():
    """La mediana locale segue la deriva: una salita 60 -> 110 bpm è fisiologica."""
    rr = np.linspace(1.0, 60 / 110, 200)
    assert clean_rr_mask(rr).all()


def test_bradycardia_and_tachycardia_are_valid():
    for bpm in (45, 100, 150):
        rr = np.full(40, 60.0 / bpm)
        assert clean_rr_mask(rr).all(), f"{bpm} bpm scartato"


def test_quality_ok_true_when_enough_clean_beats():
    assert quality_ok(valid_beats=120, artifact_fraction=0.02) is True


def test_quality_ok_false_when_too_few_beats():
    assert quality_ok(valid_beats=10, artifact_fraction=0.0) is False


def test_quality_ok_false_when_too_many_artifacts():
    assert quality_ok(valid_beats=120, artifact_fraction=0.5) is False
