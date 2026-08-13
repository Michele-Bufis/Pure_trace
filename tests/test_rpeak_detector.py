import collections

import numpy as np
import pytest
from pure_trace.signal_processing import RPeakDetector


def _reference_peaks(samples, fs=500, refractory_ms=200):
    """Riferimento O(n) per campione: soglia = 0.6 * max(finestra 2 s), calcolata
    con un max esplicito. Il detector usa una deque monotona O(1): deve dare
    esattamente gli stessi picchi."""
    window = fs * 2
    refractory = int(fs * refractory_ms / 1000)
    buf = collections.deque(maxlen=window)
    last, idx, peaks = -refractory, 0, []
    for i, s in enumerate(samples):
        buf.append(s)
        idx += 1
        if len(buf) < window // 4:
            continue
        peak_val = max(buf)
        if peak_val <= 0:
            continue
        if s >= 0.6 * peak_val and (idx - last) >= refractory:
            last = idx
            peaks.append(i)
    return peaks


@pytest.mark.parametrize("name,signal", [
    ("rumore", np.random.default_rng(0).normal(0, 1, 12000)),
    ("costante", np.full(4000, 0.7)),
    ("negativo", -np.abs(np.random.default_rng(1).normal(0, 1, 4000))),
    ("zeri", np.zeros(4000)),
    # plateau e valori ripetuti: il caso in cui una deque monotona sbaglia
    # facilmente la gestione dei pareggi
    ("plateau", np.repeat(np.random.default_rng(2).integers(0, 3, 800).astype(float), 5)),
])
def test_running_max_matches_bruteforce_max(name, signal):
    det = RPeakDetector(fs=500)
    got = [i for i, s in enumerate(signal) if det.step(float(s))]
    assert got == _reference_peaks(signal), f"picchi divergenti su '{name}'"


def _make_ecg(hr_bpm=60, duration_s=5, fs=500):
    n = duration_s * fs
    signal = np.zeros(n)
    rr = int(fs * 60 / hr_bpm)
    peak_indices = list(range(rr // 2, n, rr))
    for idx in peak_indices:
        if idx < n:
            signal[idx] = 1.0
    timestamps = np.arange(n) / float(fs)
    return signal, timestamps, peak_indices


def test_detects_peaks_at_60bpm():
    sig, ts, expected = _make_ecg(hr_bpm=60, duration_s=10)
    det = RPeakDetector(fs=500)
    detected = [i for i, (s, t) in enumerate(zip(sig, ts)) if det.process(s, t) is not None]
    assert len(detected) >= len(expected) - 2


def test_refractory_blocks_double_detection():
    det = RPeakDetector(fs=500, refractory_ms=200)
    sig = np.zeros(1000)
    sig[250] = 1.0
    sig[275] = 1.0  # 50 ms later — within 200 ms refractory
    ts = np.arange(1000) / 500.0
    peaks = [t for s, t in zip(sig, ts) if det.process(s, t) is not None]
    assert len(peaks) <= 1, f"Expected ≤1 peak, got {len(peaks)}"


def test_hr_60bpm():
    sig, ts, _ = _make_ecg(hr_bpm=60, duration_s=10)
    det = RPeakDetector(fs=500)
    for s, t in zip(sig, ts):
        det.process(s, t)
    assert abs(det.get_hr() - 60.0) < 5.0, f"HR={det.get_hr():.1f}, expected ~60"


def test_hr_80bpm():
    sig, ts, _ = _make_ecg(hr_bpm=80, duration_s=10)
    det = RPeakDetector(fs=500)
    for s, t in zip(sig, ts):
        det.process(s, t)
    assert abs(det.get_hr() - 80.0) < 5.0, f"HR={det.get_hr():.1f}, expected ~80"


def test_reset_clears_state():
    sig, ts, _ = _make_ecg(hr_bpm=60, duration_s=5)
    det = RPeakDetector(fs=500)
    for s, t in zip(sig, ts):
        det.process(s, t)
    assert det.get_hr() > 0
    det.reset()
    assert det.get_hr() == 0.0
    assert len(det.get_rr_intervals()) == 0


def test_rr_intervals_capped_at_8():
    sig, ts, _ = _make_ecg(hr_bpm=60, duration_s=20)
    det = RPeakDetector(fs=500)
    for s, t in zip(sig, ts):
        det.process(s, t)
    assert len(det.get_rr_intervals()) <= 8
