from datetime import datetime

import numpy as np
import pytest

from pure_trace import config, secure_store
from pure_trace.data_layer import Profile, EncryptionManager
from pure_trace.signal_processing import DigitalFilter
from pure_trace.analysis_engine import (
    HrvAnalyser, save_session_results, extract_rr_intervals,
    detect_rpeak_indices, clean_rr_mask, features_to_vector,
    remove_session_from_baseline,
    NEUTRAL_BASELINE_BUILDING, NEUTRAL_BASELINE_ERROR,
    NEUTRAL_LOW_QUALITY, NEUTRAL_SHORT_SESSION,
    NEUTRAL_DATA_GAP,
    _GREEN, _RED, _NEUTRAL,
)


def _make_heartbeat_signal(n_beats: int, bpm: float = 60.0, fs: int = 500) -> np.ndarray:
    """Synthetic ECG: Gaussian bumps (amplitude=1.0) at regular RR intervals."""
    rr_samples = int(fs * 60.0 / bpm)
    total = (n_beats + 1) * rr_samples
    ecg = np.zeros(total)
    for i in range(n_beats):
        center = rr_samples // 2 + i * rr_samples
        x = np.arange(max(0, center - 10), min(total, center + 11))
        ecg[x] += np.exp(-0.5 * ((x - center) / 3.0) ** 2)
    return ecg.astype(np.float32)


@pytest.fixture
def enc(tmp_path):
    """A real EncryptionManager backed by salt.bin/.keycheck in tmp_path."""
    return EncryptionManager.setup(tmp_path, "pw-test-12345")


@pytest.fixture
def profile(tmp_path):
    (tmp_path / "sessions").mkdir()
    return Profile(id="test", name="Test", dir=tmp_path)


# ---------------------------------------------------------------------------
# _compute_features
# ---------------------------------------------------------------------------

def test_compute_features_mean_rr(profile, enc):
    analyser = HrvAnalyser(profile, enc)
    rr = np.array([1.0, 1.0, 1.0])
    features = analyser._compute_features(rr, 65.0)
    assert abs(features["mean_rr"] - 1.0) < 1e-9
    assert abs(features["sdnn"]) < 1e-9


def test_compute_features_sdnn(profile, enc):
    analyser = HrvAnalyser(profile, enc)
    rr = np.array([0.9, 1.0, 1.1])
    expected_sdnn = float(np.std(rr, ddof=1))
    features = analyser._compute_features(rr, 65.0)
    assert abs(features["sdnn"] - expected_sdnn) < 1e-9


def test_compute_features_rmssd(profile, enc):
    analyser = HrvAnalyser(profile, enc)
    rr = np.array([1.0, 1.1, 1.0])
    diffs = np.diff(rr)
    expected_rmssd = float(np.sqrt(np.mean(diffs ** 2)))
    features = analyser._compute_features(rr, 65.0)
    assert abs(features["rmssd"] - expected_rmssd) < 1e-9


def test_compute_features_pnn50(profile, enc):
    analyser = HrvAnalyser(profile, enc)
    rr = np.array([1.0, 1.06, 1.0, 1.06])
    features = analyser._compute_features(rr, 65.0)
    assert abs(features["pnn50"] - 100.0) < 1e-9


def test_compute_features_single_rr_has_only_mean(profile, enc):
    analyser = HrvAnalyser(profile, enc)
    rr = np.array([0.95])
    features = analyser._compute_features(rr, 65.0)
    assert abs(features["mean_rr"] - 0.95) < 1e-9
    assert features["sdnn"] is None
    assert features["rmssd"] is None
    assert features["pnn50"] is None


def test_rmssd_and_pnn50_use_only_adjacent_valid_pairs(profile, enc):
    """RMSSD e pNN50 sono definiti sulle differenze fra battiti SUCCESSIVI.
    Passando la sola serie ripulita, np.diff scavalcava i battiti rimossi e
    misurava differenze fra intervalli non adiacenti."""
    analyser = HrvAnalyser(profile, enc)
    rr = np.full(40, 0.80)
    rr[20] = 0.40                                   # un battito anomalo
    mask = clean_rr_mask(rr)
    assert not mask[20]

    features = analyser._compute_features(rr, 65.0, mask)
    # A parte l'artefatto la serie è regolare: nessuna variabilità residua.
    assert features["rmssd"] == pytest.approx(0.0, abs=1e-12)
    assert features["pnn50"] == pytest.approx(0.0, abs=1e-12)
    assert features["sdnn"] == pytest.approx(0.0, abs=1e-12)
    assert features["mean_rr"] == pytest.approx(0.80)


def test_compute_features_without_mask_is_backward_compatible(profile, enc):
    analyser = HrvAnalyser(profile, enc)
    rr = np.array([1.00, 1.06, 1.00, 1.06])
    features = analyser._compute_features(rr, 65.0)
    diffs = np.diff(rr)
    assert features["rmssd"] == pytest.approx(float(np.sqrt(np.mean(diffs ** 2))))
    assert features["pnn50"] == pytest.approx(100.0)


def test_compute_features_all_beats_invalid(profile, enc):
    analyser = HrvAnalyser(profile, enc)
    rr = np.array([0.80, 0.80, 0.80])
    features = analyser._compute_features(rr, 65.0, np.zeros(3, dtype=bool))
    assert features["mean_rr"] is None
    assert features["sdnn"] is None


def test_qrs_duration_searches_outward_from_the_r_peak():
    """L'apice ha derivata nulla: onset e offset devono venire dai fianchi."""
    from pure_trace.analysis_engine import qrs_duration_ms

    filtered = np.zeros(500)
    peak = 250
    filtered[225:276] = np.r_[np.linspace(0.0, 1.0, 26),
                                np.linspace(1.0, 0.0, 26)[1:]]
    assert qrs_duration_ms(filtered, peak, fs=500) == pytest.approx(104.0)


# ---------------------------------------------------------------------------
# Aggancio all'apice dell'onda R
# ---------------------------------------------------------------------------

def test_peaks_are_snapped_to_the_local_maximum():
    """Il rilevatore scatta sul primo campione sopra soglia, non sull'apice:
    con ampiezza R modulata dal respiro il ritardo varia da battito a battito e
    finisce dentro RMSSD."""
    fs = 500
    signal = _make_heartbeat_signal(20, bpm=60.0, fs=fs)
    filtered = DigitalFilter(fs=fs).process_array(signal)
    peaks = detect_rpeak_indices(signal, fs)
    assert len(peaks) > 5
    window = int(config.APEX_SEARCH_S * fs)
    for p in peaks:
        lo, hi = max(0, p - window), min(len(filtered), p + window + 1)
        assert filtered[p] == pytest.approx(filtered[lo:hi].max())


def test_snapped_peaks_stay_ordered_and_physiological():
    fs = 500
    peaks = detect_rpeak_indices(_make_heartbeat_signal(30, bpm=60.0, fs=fs), fs)
    gaps = np.diff(peaks)
    assert (gaps > 0).all()
    assert (gaps / fs >= config.RR_MIN_S).all()


# ---------------------------------------------------------------------------
# features_to_vector
# ---------------------------------------------------------------------------

def test_zero_valued_features_are_kept_not_treated_as_missing():
    """Un test di verità (`if not sdnn`) scartava uno SDNN legittimamente nullo."""
    vec = features_to_vector({"mean_rr": 1.0, "sdnn": 0.0, "rmssd": 0.0, "pnn50": 0.0})
    np.testing.assert_allclose(vec, [60.0, 0.0, 0.0, 0.0])


def test_non_positive_mean_rr_is_rejected():
    assert features_to_vector(
        {"mean_rr": 0.0, "sdnn": 1.0, "rmssd": 1.0, "pnn50": 1.0}) is None


# ---------------------------------------------------------------------------
# analyse — casi limite
# ---------------------------------------------------------------------------

def test_analyse_empty_signal_returns_neutral(profile, enc):
    analyser = HrvAnalyser(profile, enc)
    status, colormap, features = analyser.analyse(np.zeros(100, dtype=np.float32))
    assert status == "NEUTRAL"
    assert len(colormap) == 0
    assert features["mean_rr"] is None
    assert features["sdnn"] is None


def test_unfilled_gap_is_neutral_and_never_enters_baseline(profile, enc):
    status, colormap, features = HrvAnalyser(profile, enc).analyse(
        _make_heartbeat_signal(70), has_unfilled_gap=True)
    assert status == "NEUTRAL"
    assert len(colormap) == 0
    assert features["neutral_reason"] == NEUTRAL_DATA_GAP
    assert HrvAnalyser(profile, enc)._model.n == 0


def test_analyse_short_session_sdnn_is_none(profile, enc):
    # 25 beats at 60 bpm => ~25s, which is < 60s
    signal = _make_heartbeat_signal(25, bpm=60.0)
    analyser = HrvAnalyser(profile, enc)
    status, colormap, features = analyser.analyse(signal)
    assert features["sdnn"] is None


# ---------------------------------------------------------------------------
# Scarto del transitorio del filtro
# ---------------------------------------------------------------------------

def _ad8232_signal(n_beats: int, bpm: float = 60.0, fs: int = 500,
                   amplitude: float = 0.10, dc: float = -0.34) -> np.ndarray:
    """ECG con i livelli reali dell'AD8232: onda R di ampiezza modesta sopra un
    offset DC marcato. È l'offset a eccitare il transitorio del passa-alto a
    0.5 Hz, e l'onda R è abbastanza piccola perché il transitorio la sovrasti."""
    return (_make_heartbeat_signal(n_beats, bpm, fs) * amplitude + dc).astype(np.float32)


def test_warmup_is_discarded_before_peak_detection():
    peaks = detect_rpeak_indices(_ad8232_signal(40))
    assert len(peaks) > 0
    assert peaks[0] >= int(config.FILTER_WARMUP_S * 500)


def test_transient_produces_no_bogus_rr(monkeypatch):
    """Il transitorio di assestamento del filtro ha ampiezza paragonabile a
    un'onda R: senza scartarlo genera un picco fantasma e un intervallo RR non
    fisiologico. Con lo scarto non deve restarne traccia."""
    signal = _ad8232_signal(40)

    # Guardia: senza scarto il difetto si manifesta davvero (altrimenti il test
    # sotto sarebbe vacuo e non proteggerebbe da nulla).
    monkeypatch.setattr(config, "FILTER_WARMUP_S", 0.0)
    rr_no_warmup = extract_rr_intervals(signal)
    bogus = (rr_no_warmup < config.RR_MIN_S) | (rr_no_warmup > config.RR_MAX_S)
    assert bogus.any(), "il segnale di prova non eccita più il transitorio"

    monkeypatch.setattr(config, "FILTER_WARMUP_S", 3.0)
    rr = extract_rr_intervals(signal)
    assert len(rr) > 10
    out_of_range = (rr < config.RR_MIN_S) | (rr > config.RR_MAX_S)
    assert not out_of_range.any(), f"RR non fisiologici: {rr[out_of_range]}"


def test_signal_shorter_than_warmup_yields_no_peaks():
    short = np.zeros(int(config.FILTER_WARMUP_S * 500) - 10, dtype=np.float32)
    assert len(detect_rpeak_indices(short)) == 0


# ---------------------------------------------------------------------------
# rr_peaks persistiti (l'archivio non deve ri-rilevare)
# ---------------------------------------------------------------------------

def test_analyse_persists_rr_peaks_aligned_with_colormap(profile, enc):
    signal = _make_heartbeat_signal(70, bpm=60.0)
    _status, colormap, features = HrvAnalyser(profile, enc).analyse(signal)
    peaks = features["rr_peaks"]
    assert len(peaks) == len(colormap) + 1   # N intervalli <=> N+1 picchi
    assert peaks == sorted(peaks)
    assert all(0 <= p < len(signal) for p in peaks)


def test_rr_peaks_survive_encrypted_round_trip(profile, enc):
    signal = _make_heartbeat_signal(70, bpm=60.0)
    _s, colormap, features = HrvAnalyser(profile, enc).analyse(signal)
    ts = datetime(2026, 7, 10, 12, 0, 0)
    save_session_results(profile, colormap, features, ts, enc)
    path = profile.dir / "sessions" / "20260710_120000.features.json"
    reloaded = secure_store.read_json(path, enc, default={})
    assert reloaded["rr_peaks"] == features["rr_peaks"]


# ---------------------------------------------------------------------------
# Persistenza baseline (schema mahalanobis-v1)
# ---------------------------------------------------------------------------

def test_model_roundtrip_persists_pool(profile, enc):
    analyser = HrvAnalyser(profile, enc)
    analyser._model.add(np.array([60.0, 0.05, 0.04, 10.0]))
    analyser._save_model()
    reloaded = HrvAnalyser(profile, enc)
    assert reloaded._model.n == 1


def test_corrupt_baseline_is_never_overwritten(profile, enc):
    """Un byte corrotto non deve distruggere lo storico del paziente.

    Prima: read_json degradava a 'nessun dato', il pool ripartiva vuoto e la
    prima sessione lunga sovrascriveva baseline.json. Perdita silenziosa e
    irreversibile."""
    path = profile.dir / "baseline.json"
    secure_store.write_json(path, {
        "schema": "mahalanobis-v1",
        "feature_pool": [[60.0, 0.05, 0.04, 10.0]] * 12,
    }, enc)
    original = path.read_bytes()

    corrupted = bytearray(original)
    corrupted[30] ^= 0x01
    path.write_bytes(bytes(corrupted))

    analyser = HrvAnalyser(profile, enc)
    assert analyser.baseline_error is True
    assert analyser._model.n == 0            # non si scora su dati fantasma

    # una sessione lunga e valida NON deve riscrivere il file
    analyser.analyse(_make_heartbeat_signal(70, bpm=60.0))
    assert path.read_bytes() == bytes(corrupted), "baseline sovrascritta!"


def test_missing_baseline_is_not_an_error(profile, enc):
    """File assente => pool vuoto, comportamento normale (non è corruzione)."""
    analyser = HrvAnalyser(profile, enc)
    assert analyser.baseline_error is False
    assert analyser._model.n == 0


def test_baseline_error_surfaces_in_features(profile, enc):
    path = profile.dir / "baseline.json"
    path.write_bytes(b"non-decifrabile-affatto")
    _s, _cm, features = HrvAnalyser(profile, enc).analyse(
        _make_heartbeat_signal(70, bpm=60.0))
    assert features["baseline_error"] is True


def test_old_schema_baseline_resets(profile, enc):
    # vecchio formato (frozen/_pool) => deve ripartire da zero
    secure_store.write_json(
        profile.dir / "baseline.json",
        {"sessions_count": 5, "frozen": True, "rr_mean": 1.0, "rr_std": 0.5},
        enc,
    )
    analyser = HrvAnalyser(profile, enc)
    assert analyser._model.n == 0


# ---------------------------------------------------------------------------
# Colormap dinamica RR locale
# ---------------------------------------------------------------------------

def test_local_colormap_marks_artifacts_neutral(profile, enc):
    analyser = HrvAnalyser(profile, enc)
    rr = np.array([0.80, 0.80, 1.60, 0.80, 0.80, 0.80])  # idx2 artefatto
    mask = np.array([True, True, False, True, True, True])
    cm = analyser._build_local_colormap(rr, mask)
    assert cm[2] == _NEUTRAL
    assert len(cm) == len(rr)


def test_local_colormap_uniform_is_green(profile, enc):
    analyser = HrvAnalyser(profile, enc)
    rr = np.full(10, 0.85)
    mask = np.ones(10, dtype=bool)
    cm = analyser._build_local_colormap(rr, mask)
    assert np.all(cm == _GREEN)


def test_local_colormap_outlier_beat_is_red(profile, enc):
    analyser = HrvAnalyser(profile, enc)
    rr = np.array([0.85, 0.85, 0.85, 0.85, 0.85, 0.85, 0.85, 0.85, 0.85, 1.10])
    mask = np.ones(10, dtype=bool)
    cm = analyser._build_local_colormap(rr, mask)
    assert _RED in cm


# ---------------------------------------------------------------------------
# analyse — scoring per-sessione (Mahalanobis)
# ---------------------------------------------------------------------------

def _baseline_pool_from_signal(profile, enc, vec, n=5):
    """Scrive una baseline pronta (n vettori = vec) nello schema nuovo."""
    secure_store.write_json(profile.dir / "baseline.json", {
        "schema": "mahalanobis-v1",
        "feature_names": ["mean_hr", "sdnn", "rmssd", "pnn50"],
        "feature_pool": [list(vec)] * n,
        "sessions_count": n,
    }, enc)


def test_analyse_neutral_before_baseline_but_pool_grows(profile, enc):
    signal = _make_heartbeat_signal(70, bpm=60.0)  # sessione lunga
    analyser = HrvAnalyser(profile, enc)
    status, _, features = analyser.analyse(signal)
    assert status == "NEUTRAL"                 # baseline non pronta
    assert HrvAnalyser(profile, enc)._model.n == 1   # ma il pool è cresciuto


def test_analyse_short_session_is_neutral_and_no_update(profile, enc):
    signal = _make_heartbeat_signal(25, bpm=60.0)  # ~25 s < 60 s
    analyser = HrvAnalyser(profile, enc)
    status, _, features = analyser.analyse(signal)
    assert status == "NEUTRAL"
    assert features["sdnn"] is None
    assert HrvAnalyser(profile, enc)._model.n == 0


def test_analyse_insufficient_quality_is_neutral(profile, enc):
    # 70 s di segnale con battiti ogni 7 s => RR fuori range => qualità insufficiente
    fs = 500
    total = fs * 70
    ecg = np.zeros(total, dtype=np.float32)
    for c in range(fs * 3, total, fs * 7):
        ecg[c] = 1.0
    analyser = HrvAnalyser(profile, enc)
    status, _, features = analyser.analyse(ecg)
    assert status == "NEUTRAL"
    assert HrvAnalyser(profile, enc)._model.n == 0


def test_analyse_consistent_session_is_green(profile, enc):
    signal = _make_heartbeat_signal(70, bpm=60.0)
    rr = extract_rr_intervals(signal)
    vec = features_to_vector(
        HrvAnalyser(profile, enc)._compute_features(rr[clean_rr_mask(rr)], 70.0)
    )
    _baseline_pool_from_signal(profile, enc, vec, n=6)
    status, _, features = HrvAnalyser(profile, enc).analyse(signal)
    assert status == "GREEN"
    assert features["feature_z"] is not None


def test_analyse_deviant_session_is_red(profile, enc):
    # baseline stretta intorno a 120 bpm, sessione reale a 60 bpm => RED
    tight = np.array([120.0, 0.005, 0.004, 0.5])
    _baseline_pool_from_signal(profile, enc, tight, n=6)
    signal = _make_heartbeat_signal(70, bpm=60.0)
    status, _, _ = HrvAnalyser(profile, enc).analyse(signal)
    assert status == "RED"


# ---------------------------------------------------------------------------
# neutral_reason: NEUTRAL non è una causa sola
# ---------------------------------------------------------------------------

def test_neutral_reason_short_session(profile, enc):
    _s, _cm, features = HrvAnalyser(profile, enc).analyse(
        _make_heartbeat_signal(25, bpm=60.0))          # ~26 s
    assert features["neutral_reason"] == NEUTRAL_SHORT_SESSION


def test_neutral_reason_low_quality(profile, enc):
    fs, total = 500, 500 * 70
    ecg = np.zeros(total, dtype=np.float32)
    for c in range(fs * 4, total, fs * 7):             # RR di 7 s: fuori range
        ecg[c] = 1.0
    _s, _cm, features = HrvAnalyser(profile, enc).analyse(ecg)
    assert features["neutral_reason"] == NEUTRAL_LOW_QUALITY


def test_neutral_reason_baseline_building_reports_progress(profile, enc):
    _s, _cm, features = HrvAnalyser(profile, enc).analyse(
        _make_heartbeat_signal(70, bpm=60.0))
    assert features["neutral_reason"] == NEUTRAL_BASELINE_BUILDING
    done, needed = features["baseline_progress"]
    assert (done, needed) == (1, config.MIN_BASELINE_SESSIONS)


def test_neutral_reason_baseline_error(profile, enc):
    (profile.dir / "baseline.json").write_bytes(b"illeggibile")
    _s, _cm, features = HrvAnalyser(profile, enc).analyse(
        _make_heartbeat_signal(70, bpm=60.0))
    assert features["neutral_reason"] == NEUTRAL_BASELINE_ERROR


def test_scored_session_has_no_neutral_reason(profile, enc):
    signal = _make_heartbeat_signal(70, bpm=60.0)
    rr = extract_rr_intervals(signal)
    vec = features_to_vector(
        HrvAnalyser(profile, enc)._compute_features(rr[clean_rr_mask(rr)], 70.0))
    _baseline_pool_from_signal(profile, enc, vec, n=6)
    status, _cm, features = HrvAnalyser(profile, enc).analyse(signal)
    assert status == "GREEN"
    assert features["neutral_reason"] is None


# ---------------------------------------------------------------------------
# Cancellare una sessione la toglie anche dalla baseline
# ---------------------------------------------------------------------------

def test_delete_session_removes_its_baseline_vector(profile, enc):
    signal = _make_heartbeat_signal(70, bpm=60.0)
    for sid in ("20260701_100000", "20260702_100000", "20260703_100000"):
        HrvAnalyser(profile, enc).analyse(signal, session_id=sid)
    assert HrvAnalyser(profile, enc)._model.n == 3

    assert remove_session_from_baseline(profile, enc, "20260702_100000") is True
    model = HrvAnalyser(profile, enc)._model
    assert model.n == 2
    assert "20260702_100000" not in model.session_ids_as_list()


def test_removing_unknown_session_is_a_noop(profile, enc):
    HrvAnalyser(profile, enc).analyse(_make_heartbeat_signal(70, bpm=60.0),
                                      session_id="20260701_100000")
    assert remove_session_from_baseline(profile, enc, "20261231_235959") is False
    assert HrvAnalyser(profile, enc)._model.n == 1


def test_legacy_v1_baseline_loads_without_session_ids(profile, enc):
    """Le baseline v1 restano utilizzabili: i vettori valgono, ma non sono
    associati a una sessione e quindi non si rimuovono."""
    secure_store.write_json(profile.dir / "baseline.json", {
        "schema": "mahalanobis-v1",
        "feature_pool": [[60.0, 0.05, 0.04, 10.0]] * 6,
    }, enc)
    model = HrvAnalyser(profile, enc)._model
    assert model.n == 6
    assert model.session_ids_as_list() == [None] * 6
    assert remove_session_from_baseline(profile, enc, "20260701_100000") is False


def test_corrupt_baseline_blocks_session_removal(profile, enc):
    (profile.dir / "baseline.json").write_bytes(b"illeggibile")
    assert remove_session_from_baseline(profile, enc, "20260701_100000") is False


# ---------------------------------------------------------------------------
# save_session_results (cifrato)
# ---------------------------------------------------------------------------

def test_save_session_results_creates_files(profile, enc):
    colormap = np.array([0, 1, 2, 255], dtype=np.uint8)
    features = {"mean_rr": 1.0, "sdnn": 0.05, "rmssd": 0.04, "pnn50": 10.0}
    ts = datetime(2026, 5, 29, 10, 0, 0)
    save_session_results(profile, colormap, features, ts, enc)

    sessions_dir = profile.dir / "sessions"
    colormap_path = sessions_dir / "20260529_100000.colormap.npy"
    features_path = sessions_dir / "20260529_100000.features.json"

    assert colormap_path.exists()
    assert features_path.exists()

    # Files on disk must NOT be readable without the key (encrypted at rest).
    with pytest.raises(Exception):
        np.load(str(colormap_path))

    loaded_colormap = secure_store.read_npy(colormap_path, enc, np.array([], dtype=np.uint8))
    np.testing.assert_array_equal(loaded_colormap, colormap)

    loaded_features = secure_store.read_json(features_path, enc, default={})
    assert loaded_features == features


# ---------------------------------------------------------------------------
# extract_rr_intervals
# ---------------------------------------------------------------------------

def test_extract_rr_intervals_public_returns_same_as_private(profile, enc):
    signal = _make_heartbeat_signal(10, bpm=60.0)
    analyser = HrvAnalyser(profile, enc)
    rr_private = analyser._extract_rr_intervals(signal)
    rr_public = extract_rr_intervals(signal)
    np.testing.assert_array_equal(rr_private, rr_public)
