"""L'imbottitura nasconde la LUNGHEZZA del testo in chiaro.

La cifratura autenticata nasconde il contenuto, non la sua dimensione. La
colormap contiene un byte per battito e ``features.json`` un indice per picco R:
dalle dimensioni dei file, senza password, si ricavava il numero esatto di
battiti — e quindi la frequenza cardiaca media del paziente.
"""
import numpy as np
import pytest

from pure_trace import secure_store
from pure_trace.data_layer import EncryptionManager


@pytest.fixture
def enc(tmp_path):
    return EncryptionManager.setup(tmp_path, "pw-test-12345")


def test_pad_unpad_round_trip():
    for payload in (b"", b"x", b"a" * 5000, bytes(range(256))):
        padded = secure_store._pad(payload)
        assert len(padded) % secure_store.PAD_BLOCK == 0
        assert secure_store._unpad(padded) == payload


def test_unpad_passes_through_unpadded_legacy_data():
    """I file scritti prima di questa modifica non hanno il magic: vanno letti
    tali e quali, senza migrazione."""
    for legacy in (b'{"sdnn": 0.05}', b"\x93NUMPY\x01\x00"):
        assert secure_store._unpad(legacy) == legacy


def test_json_file_size_hides_content_length(tmp_path, enc):
    """Sessioni con numeri di battiti molto diversi devono produrre file della
    stessa dimensione."""
    sizes = set()
    for n_beats in (60, 90, 120, 160):
        path = tmp_path / f"{n_beats}.features.json"
        secure_store.write_json(path, {"rr_peaks": list(range(n_beats))}, enc)
        sizes.add(path.stat().st_size)
    assert len(sizes) == 1, f"la dimensione rivela il numero di battiti: {sizes}"


def test_npy_file_size_hides_beat_count(tmp_path, enc):
    sizes = set()
    for n_beats in (60, 90, 120, 160):
        path = tmp_path / f"{n_beats}.colormap.npy"
        secure_store.write_npy(path, np.zeros(n_beats, dtype=np.uint8), enc)
        sizes.add(path.stat().st_size)
    assert len(sizes) == 1, f"la dimensione rivela il numero di battiti: {sizes}"


def test_padded_json_round_trip(tmp_path, enc):
    path = tmp_path / "a.json"
    obj = {"sdnn": 0.05, "rr_peaks": list(range(200)), "testo": "àèìòù"}
    secure_store.write_json(path, obj, enc)
    assert secure_store.read_json(path, enc, default=None) == obj


def test_padded_npy_round_trip(tmp_path, enc):
    path = tmp_path / "a.npy"
    arr = np.arange(300, dtype=np.uint8)
    secure_store.write_npy(path, arr, enc)
    np.testing.assert_array_equal(
        secure_store.read_npy(path, enc, default=np.array([])), arr)


def test_legacy_unpadded_files_are_still_readable(tmp_path, enc):
    """Un file cifrato SENZA imbottitura (formato precedente) deve continuare a
    leggersi: i profili esistenti non vanno migrati."""
    import io
    import json

    json_path = tmp_path / "legacy.json"
    json_path.write_bytes(enc.encrypt(json.dumps({"sdnn": 0.05}).encode("utf-8")))
    assert secure_store.read_json(json_path, enc, default=None) == {"sdnn": 0.05}

    npy_path = tmp_path / "legacy.npy"
    buf = io.BytesIO()
    np.save(buf, np.array([1, 2, 3], dtype=np.uint8))
    npy_path.write_bytes(enc.encrypt(buf.getvalue()))
    np.testing.assert_array_equal(
        secure_store.read_npy(npy_path, enc, default=np.array([])), [1, 2, 3])


def test_corrupt_padded_file_still_raises_in_strict_mode(tmp_path, enc):
    path = tmp_path / "a.json"
    secure_store.write_json(path, {"a": 1}, enc)
    blob = bytearray(path.read_bytes())
    blob[30] ^= 0x01
    path.write_bytes(bytes(blob))
    with pytest.raises(secure_store.DecryptError):
        secure_store.read_json(path, enc, default=None, strict=True)
