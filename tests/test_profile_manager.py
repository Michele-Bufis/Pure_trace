import pytest
from cryptography.exceptions import InvalidTag
from pure_trace.data_layer import ProfileManager, EncryptionManager


def test_create_and_list(tmp_path):
    pm = ProfileManager(tmp_path)
    p = pm.create_profile("Mario Rossi", "password123")
    profiles = pm.list_profiles()
    assert len(profiles) == 1
    assert profiles[0].id == p.id
    # Prima della password si conosce solo l'alias, non il nome del paziente.
    assert profiles[0].alias == "M. R."
    assert profiles[0].name == "M. R."


def test_patient_name_is_not_stored_in_plaintext(tmp_path):
    """Il nome per esteso era leggibile in profile.json da chiunque avesse la SD."""
    pm = ProfileManager(tmp_path)
    p = pm.create_profile("Mario Rossi", "password123")
    on_disk = (p.dir / "profile.json").read_text(encoding="utf-8")
    assert "Mario" not in on_disk and "Rossi" not in on_disk
    assert b"Mario" not in (p.dir / "identity.json").read_bytes()


def test_unlock_recovers_the_real_name(tmp_path):
    pm = ProfileManager(tmp_path)
    created = pm.create_profile("Mario Rossi", "password123")
    locked = pm.list_profiles()[0]
    assert locked.name == "M. R."

    enc = EncryptionManager(locked.dir, "password123")
    unlocked = pm.unlock(locked, enc)
    assert unlocked.name == "Mario Rossi"
    assert unlocked.alias == "M. R."
    assert unlocked.id == created.id


def test_explicit_alias_is_used(tmp_path):
    pm = ProfileManager(tmp_path)
    p = pm.create_profile("Mario Rossi", "password123", alias="Paziente 1")
    assert pm.list_profiles()[0].alias == "Paziente 1"
    assert "Mario" not in (p.dir / "profile.json").read_text(encoding="utf-8")


def test_default_alias_from_initials():
    assert ProfileManager.default_alias("Mario Rossi") == "M. R."
    assert ProfileManager.default_alias("Anna") == "A."
    assert ProfileManager.default_alias("  ") == "Profilo"


def test_legacy_profile_without_alias_still_loads(tmp_path):
    """I profili creati prima di questa modifica hanno il nome in chiaro: resta
    utilizzabile come alias, senza migrazione."""
    import json
    pm = ProfileManager(tmp_path)
    legacy = tmp_path / "legacy-uuid"
    (legacy / "sessions").mkdir(parents=True)
    (legacy / "profile.json").write_text(json.dumps({"name": "Vecchio Profilo"}),
                                         encoding="utf-8")
    EncryptionManager.setup(legacy, "password123")

    profiles = pm.list_profiles()
    assert [p.alias for p in profiles] == ["Vecchio Profilo"]

    enc = EncryptionManager(legacy, "password123")
    unlocked = pm.unlock(profiles[0], enc)      # nessun identity.json
    assert unlocked.name == "Vecchio Profilo"


def test_incomplete_profile_is_hidden_from_picker(tmp_path):
    """Una creazione interrotta lasciava un profilo senza salt.bin: compariva nel
    selettore e al login sollevava FileNotFoundError, non catturato."""
    pm = ProfileManager(tmp_path)
    broken = tmp_path / "broken-uuid"
    (broken / "sessions").mkdir(parents=True)
    (broken / "profile.json").write_text('{"name": "Interrotto"}', encoding="utf-8")

    assert pm.list_profiles() == []


def test_create_profile_is_atomic(tmp_path, monkeypatch):
    """Se la creazione fallisce a metà non deve restare nulla di parziale."""
    pm = ProfileManager(tmp_path)

    def boom(*args, **kwargs):
        raise RuntimeError("interruzione simulata")

    monkeypatch.setattr(EncryptionManager, "setup", staticmethod(boom))
    with pytest.raises(RuntimeError):
        pm.create_profile("Mai Nato", "password123")

    assert pm.list_profiles() == []
    assert list(tmp_path.iterdir()) == []      # nessuna directory residua


def test_created_profile_has_crypto_material(tmp_path):
    pm = ProfileManager(tmp_path)
    p = pm.create_profile("Anna Bianchi", "password123")
    for f in ("profile.json", "salt.bin", ".keycheck"):
        assert (p.dir / f).exists()


def test_load_profile(tmp_path):
    pm = ProfileManager(tmp_path)
    p = pm.create_profile("Luigi Verdi", "pass12345")
    loaded = pm.load_profile(p.id)
    assert loaded.id == p.id
    assert loaded.name == "L. V."      # ancora bloccato: solo l'alias
    assert loaded.id == p.id


def test_multiple_profiles(tmp_path):
    pm = ProfileManager(tmp_path)
    pm.create_profile("Alice", "alicepass1")
    pm.create_profile("Bob", "bobpassword")
    assert len(pm.list_profiles()) == 2


def test_wrong_password_raises(tmp_path):
    pm = ProfileManager(tmp_path)
    p = pm.create_profile("User", "correctpass")
    with pytest.raises(InvalidTag):
        EncryptionManager(p.dir, "wrongpass!")


def test_malformed_profile_dir_skipped(tmp_path):
    bad = tmp_path / "not-a-uuid"
    bad.mkdir()
    pm = ProfileManager(tmp_path)
    assert pm.list_profiles() == []


def test_sessions_dir_created(tmp_path):
    pm = ProfileManager(tmp_path)
    p = pm.create_profile("Test", "testpass1")
    assert (p.dir / "sessions").is_dir()
