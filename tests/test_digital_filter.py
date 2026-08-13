import numpy as np
from pure_trace.signal_processing import DigitalFilter


def _sine(freq_hz, duration_s=2.0, fs=500, amplitude=1.0):
    t = np.linspace(0, duration_s, int(duration_s * fs), endpoint=False)
    return amplitude * np.sin(2 * np.pi * freq_hz * t)


def _process(filt, signal):
    return np.array([filt.process_sample(float(s)) for s in signal])


def test_notch_attenuates_50hz():
    filt = DigitalFilter()
    sig = _sine(50.0)
    out = _process(filt, sig)
    rms_in = np.sqrt(np.mean(sig[250:] ** 2))
    rms_out = np.sqrt(np.mean(out[250:] ** 2))
    assert rms_out < rms_in * 0.1, f"50 Hz not attenuated: rms_in={rms_in:.4f} rms_out={rms_out:.4f}"


def test_passband_10hz_passes():
    filt = DigitalFilter()
    sig = _sine(10.0)
    out = _process(filt, sig)
    rms_in = np.sqrt(np.mean(sig[250:] ** 2))
    rms_out = np.sqrt(np.mean(out[250:] ** 2))
    assert rms_out > rms_in * 0.7, f"10 Hz attenuated too much: rms_in={rms_in:.4f} rms_out={rms_out:.4f}"


def test_dc_removed():
    filt = DigitalFilter()
    sig = np.ones(1000)
    out = _process(filt, sig)
    assert abs(out[-1]) < 0.05, f"DC not removed: last sample = {out[-1]:.4f}"


def test_sample_by_sample_matches_batch():
    from scipy.signal import sosfilt, butter, iirnotch, tf2sos
    filt = DigitalFilter()
    sig = _sine(10.0, duration_s=1.0)
    out_incremental = _process(filt, sig)

    b, a = iirnotch(50.0, Q=30.0, fs=500)
    sos_notch = tf2sos(b, a)
    sos_bp = butter(4, [0.5, 40.0], btype='bandpass', fs=500, output='sos')
    sos = np.vstack([sos_notch, sos_bp])
    out_batch = sosfilt(sos, sig)

    np.testing.assert_allclose(out_incremental, out_batch, atol=1e-10)


def test_process_array_matches_sample_by_sample():
    """L'analisi offline filtra in batch, il live campione per campione: i due
    percorsi devono produrre lo stesso segnale, bit per bit."""
    rng = np.random.default_rng(0)
    sig = rng.normal(0, 1, 4000)
    out_incremental = _process(DigitalFilter(), sig)
    out_batch = DigitalFilter().process_array(sig)
    np.testing.assert_allclose(out_incremental, out_batch, atol=1e-12)


def test_process_array_is_stateful_across_blocks():
    rng = np.random.default_rng(1)
    sig = rng.normal(0, 1, 3000)
    out_full = DigitalFilter().process_array(sig)
    filt = DigitalFilter()
    out_split = np.concatenate([filt.process_array(sig[:1000]),
                                filt.process_array(sig[1000:])])
    np.testing.assert_allclose(out_full, out_split, atol=1e-12)


def test_process_array_empty_returns_empty():
    assert DigitalFilter().process_array(np.array([])).size == 0


def test_state_persists_across_calls():
    sig = _sine(10.0, duration_s=1.0)
    half = len(sig) // 2

    filt1 = DigitalFilter()
    out_split = np.concatenate([_process(filt1, sig[:half]), _process(filt1, sig[half:])])

    filt2 = DigitalFilter()
    out_full = _process(filt2, sig)

    np.testing.assert_allclose(out_split, out_full, atol=1e-10)
