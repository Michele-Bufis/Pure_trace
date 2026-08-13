import numpy as np
import pytest
from datetime import datetime
from pathlib import Path
from pyedflib import highlevel
from pure_trace.data_layer import EncryptionManager, ProfileManager, EDFWriter


@pytest.fixture
def profile_and_enc(tmp_path):
    pm = ProfileManager(tmp_path)
    profile = pm.create_profile("Test User", "testpass123")
    enc = EncryptionManager(profile.dir, "testpass123")
    return profile, enc


def test_save_creates_encrypted_file(profile_and_enc):
    profile, enc = profile_and_enc
    samples = np.random.uniform(-0.5, 0.5, 1000).astype(np.float32)
    path = EDFWriter.save(samples, profile, enc, datetime.now())
    assert path.exists()
    assert path.suffix == ".edf"


def test_decrypted_edf_has_correct_sampling_rate(tmp_path, profile_and_enc):
    profile, enc = profile_and_enc
    samples = np.zeros(1500, dtype=np.float32)
    path = EDFWriter.save(samples, profile, enc, datetime.now())

    raw = enc.decrypt(path.read_bytes())
    tmp_edf = tmp_path / "dec.edf"
    tmp_edf.write_bytes(raw)

    _, signal_headers, _ = highlevel.read_edf(str(tmp_edf))
    assert signal_headers[0]['sample_frequency'] == 500


def test_decrypted_edf_samples_match(tmp_path, profile_and_enc):
    profile, enc = profile_and_enc
    samples = np.linspace(-0.9, 0.9, 1500, dtype=np.float32)
    path = EDFWriter.save(samples, profile, enc, datetime.now())

    raw = enc.decrypt(path.read_bytes())
    tmp_edf = tmp_path / "dec.edf"
    tmp_edf.write_bytes(raw)

    signals, _, _ = highlevel.read_edf(str(tmp_edf))
    np.testing.assert_allclose(signals[0], samples, atol=1e-4)


def test_edf_write_is_atomic_and_leaves_no_temp_file(profile_and_enc):
    """Il .edf veniva scritto direttamente: un calo di tensione a metà lasciava
    un file troncato che l'archivio elencava e che poi falliva la decifratura."""
    profile, enc = profile_and_enc
    samples = np.random.default_rng(0).normal(0, 0.1, 2000).astype(np.float32)
    path = EDFWriter.save(samples, profile, enc, datetime(2026, 7, 10, 12, 0, 0))
    assert enc.decrypt(path.read_bytes())            # integro, non troncato
    assert list(profile.dir.rglob("*.tmp")) == []    # nessun residuo


def test_edf_plaintext_temp_file_is_removed(profile_and_enc):
    """L'EDF in chiaro passa da un file temporaneo: non deve sopravvivere."""
    import tempfile
    profile, enc = profile_and_enc
    before = set(Path(tempfile.gettempdir()).glob("*.edf"))
    EDFWriter.save(np.zeros(1000, dtype=np.float32), profile, enc, datetime.now())
    assert set(Path(tempfile.gettempdir()).glob("*.edf")) == before


def test_too_few_samples_raises(profile_and_enc):
    profile, enc = profile_and_enc
    with pytest.raises(ValueError, match="Too few samples"):
        EDFWriter.save(np.zeros(100, dtype=np.float32), profile, enc, datetime.now())


def test_filename_uses_timestamp(profile_and_enc):
    profile, enc = profile_and_enc
    ts = datetime(2026, 5, 29, 14, 30, 0)
    path = EDFWriter.save(np.zeros(1000, dtype=np.float32), profile, enc, ts)
    assert path.name == "20260529_143000.edf"
