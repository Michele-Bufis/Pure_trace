import numpy as np
import pytest


@pytest.fixture
def synthetic_ecg_60bpm():
    """5-second synthetic ECG at 500 Hz: 60 bpm spikes."""
    fs = 500
    duration = 5
    n = fs * duration
    signal = np.zeros(n)
    rr = fs  # 1 beat per second = 60 bpm
    for i in range(rr // 2, n, rr):
        signal[i] = 1.0
    timestamps = np.arange(n) / fs
    return signal, timestamps, fs
