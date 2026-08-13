import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pytest

from pure_trace import config, secure_store
from pure_trace.data_layer import EncryptionManager
from pure_trace.ui.archive_screen import (
    scan_sessions, rr_band_boundaries, export_session,
    _status_from_features, _tint_color_for_z,
)
from pure_trace.ui import theme


@pytest.fixture
def enc(tmp_path):
    """A real EncryptionManager backed by salt.bin/.keycheck in tmp_path."""
    return EncryptionManager.setup(tmp_path, "pw-test-12345")


# ---------------------------------------------------------------------------
# Helpers shared across tasks
# ---------------------------------------------------------------------------

def _write_session_files(sessions_dir: Path, stem: str,
                          with_colormap: bool = True,
                          with_features: bool = True) -> None:
    """Write stub session files for the given timestamp stem."""
    (sessions_dir / f"{stem}.edf").write_bytes(b"FAKE_EDF")
    if with_colormap:
        colormap = np.array([0, 1, 0, 2], dtype=np.uint8)
        np.save(str(sessions_dir / f"{stem}.colormap"), colormap)
    if with_features:
        features = {"mean_rr": 1.0, "sdnn": 0.05, "rmssd": 0.04, "pnn50": 10.0}
        (sessions_dir / f"{stem}.features.json").write_text(json.dumps(features))


# ---------------------------------------------------------------------------
# Task 2: SessionRecord + scan_sessions
# ---------------------------------------------------------------------------

def test_scan_sessions_all_three_files(tmp_path):
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    _write_session_files(sessions_dir, "20260530_143200")

    records = scan_sessions(sessions_dir)

    assert len(records) == 1
    assert records[0].colormap_path is not None
    assert records[0].features_path is not None
    assert records[0].edf_path.name == "20260530_143200.edf"


def test_scan_sessions_missing_sidecar_files(tmp_path):
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    _write_session_files(sessions_dir, "20260530_143200", with_colormap=False, with_features=False)

    records = scan_sessions(sessions_dir)

    assert len(records) == 1
    assert records[0].colormap_path is None
    assert records[0].features_path is None


def test_scan_sessions_sorted_newest_first(tmp_path):
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    for stem in ["20260528_100000", "20260530_143200", "20260529_090000"]:
        (sessions_dir / f"{stem}.edf").write_bytes(b"x")

    records = scan_sessions(sessions_dir)

    assert records[0].timestamp == datetime(2026, 5, 30, 14, 32, 0)
    assert records[1].timestamp == datetime(2026, 5, 29, 9, 0, 0)
    assert records[2].timestamp == datetime(2026, 5, 28, 10, 0, 0)


def test_scan_sessions_empty_dir(tmp_path):
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()

    records = scan_sessions(sessions_dir)

    assert records == []


# ---------------------------------------------------------------------------
# Task 3: rr_band_boundaries + export_session
# ---------------------------------------------------------------------------

def test_rr_band_boundaries_uses_persisted_peaks():
    # Nessun rilevamento: i confini sono gli indici dei picchi già salvati.
    features = {"rr_peaks": [1500, 2000, 2450, 3000]}
    boundaries = rr_band_boundaries(features, np.zeros(4000), fs=500)
    assert boundaries == [1500, 2000, 2450, 3000]


def test_rr_band_boundaries_recomputes_when_peaks_missing():
    # Sessione legacy senza 'rr_peaks': si rileva di nuovo dal segnale grezzo.
    fs = 500
    raw = np.zeros(fs * 8)
    for i in range(fs // 2, len(raw), fs):   # un picco al secondo
        raw[i] = 1.0
    boundaries = rr_band_boundaries({}, raw, fs=fs)
    assert len(boundaries) >= 2
    # I picchi cadono dopo lo scarto del transitorio e sono distanziati ~1 s.
    assert all(b >= int(config.FILTER_WARMUP_S * fs) for b in boundaries)
    gaps = np.diff(boundaries)
    assert np.allclose(gaps, fs, atol=5)


def test_rr_band_boundaries_empty_when_no_peaks():
    assert rr_band_boundaries({}, np.zeros(1000), fs=500) == []


def test_export_session_writes_edf_and_features(tmp_path, enc):
    edf_bytes = b"FAKE_EDF_CONTENT"
    features = {"sdnn": 0.042, "rmssd": 0.038}
    features_path = tmp_path / "src.features.json"
    secure_store.write_json(features_path, features, enc)  # stored encrypted
    dest = tmp_path / "out" / "session.edf"
    dest.parent.mkdir()

    export_session(edf_bytes, features_path, dest, enc)

    assert dest.read_bytes() == edf_bytes
    dest_features = tmp_path / "out" / "session.features.json"
    assert dest_features.exists()
    # exported features must be PLAINTEXT (readable by external tools)
    assert json.loads(dest_features.read_text()) == features


def test_export_session_no_features_file(tmp_path, enc):
    edf_bytes = b"FAKE_EDF_CONTENT"
    dest = tmp_path / "session.edf"

    export_session(edf_bytes, None, dest, enc)

    assert dest.read_bytes() == edf_bytes


def test_export_session_missing_features_ignored(tmp_path, enc):
    edf_bytes = b"FAKE_EDF_CONTENT"
    features_path = tmp_path / "nonexistent.features.json"
    dest = tmp_path / "session.edf"

    export_session(edf_bytes, features_path, dest, enc)

    assert dest.read_bytes() == edf_bytes
    assert not (tmp_path / "session.features.json").exists()


# ---------------------------------------------------------------------------
# Stato sessione da features + tinta scalari metrici
# ---------------------------------------------------------------------------

def test_status_from_features_reads_stored_status():
    assert _status_from_features({"status": "RED"}) == "RED"


def test_status_from_features_defaults_neutral():
    assert _status_from_features({}) == "NEUTRAL"
    assert _status_from_features({"status": "BOGUS"}) == "NEUTRAL"


def test_tint_color_for_z_bands():
    assert _tint_color_for_z(0.5) == theme.GREEN
    assert _tint_color_for_z(1.5) == theme.YELLOW
    assert _tint_color_for_z(3.0) == theme.RED
    assert _tint_color_for_z(None) == theme.TEXT
