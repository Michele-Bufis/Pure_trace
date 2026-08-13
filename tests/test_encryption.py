import pytest
from cryptography.exceptions import InvalidTag
from pure_trace.data_layer import EncryptionManager


def test_round_trip(tmp_path):
    EncryptionManager.setup(tmp_path, "password123")
    enc = EncryptionManager(tmp_path, "password123")
    data = b"hello world"
    assert enc.decrypt(enc.encrypt(data)) == data


def test_wrong_password_raises(tmp_path):
    EncryptionManager.setup(tmp_path, "correct")
    with pytest.raises(InvalidTag):
        EncryptionManager(tmp_path, "wrong")


def test_unique_nonce_per_encrypt(tmp_path):
    EncryptionManager.setup(tmp_path, "password123")
    enc = EncryptionManager(tmp_path, "password123")
    data = b"same data"
    c1 = enc.encrypt(data)
    c2 = enc.encrypt(data)
    assert c1 != c2
    assert enc.decrypt(c1) == data
    assert enc.decrypt(c2) == data
