import json
import os
import shutil
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
from pyedflib import highlevel

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes

from pure_trace import config, secure_store
from pure_trace.logging_setup import get_logger

log = get_logger(__name__)

_PROFILE_SCHEMA = "profile-v2"


class EncryptionManager:
    _SENTINEL = b"PURETRACE_OK"

    def __init__(self, profile_dir: Path, password: str) -> None:
        salt = (profile_dir / "salt.bin").read_bytes()
        key = self._derive_key(password, salt)
        self._aesgcm = AESGCM(key)
        self.decrypt((profile_dir / ".keycheck").read_bytes())

    @staticmethod
    def _derive_key(password: str, salt: bytes) -> bytes:
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=16,
            salt=salt,
            iterations=200_000,
        )
        return kdf.derive(password.encode())

    def encrypt(self, data: bytes) -> bytes:
        nonce = os.urandom(12)
        return nonce + self._aesgcm.encrypt(nonce, data, None)

    def decrypt(self, data: bytes) -> bytes:
        nonce, ct = data[:12], data[12:]
        return self._aesgcm.decrypt(nonce, ct, None)

    @classmethod
    def setup(cls, profile_dir: Path, password: str) -> "EncryptionManager":
        """Initialize salt + keycheck sentinel for a new profile directory."""
        salt = os.urandom(16)
        (profile_dir / "salt.bin").write_bytes(salt)
        key = cls._derive_key(password, salt)
        aesgcm = AESGCM(key)
        nonce = os.urandom(12)
        (profile_dir / ".keycheck").write_bytes(
            nonce + aesgcm.encrypt(nonce, cls._SENTINEL, None)
        )
        return cls(profile_dir, password)


@dataclass
class Profile:
    """``alias`` è l'etichetta in chiaro mostrata dal selettore prima del login.
    ``name`` è il nome reale del paziente: resta cifrato su disco e vale ``alias``
    finché il profilo non viene sbloccato con la password (vedi ``unlock``)."""
    id: str
    name: str
    dir: Path
    alias: str = ""

    def __post_init__(self) -> None:
        if not self.alias:
            self.alias = self.name


class ProfileManager:
    def __init__(self, base_dir: Optional[Path] = None) -> None:
        self._base = Path(base_dir) if base_dir is not None else config.PROFILES_DIR
        self._base.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _is_complete(profile_dir: Path) -> bool:
        """Un profilo è usabile solo se ha anche il materiale crittografico."""
        return all((profile_dir / f).exists()
                   for f in ("profile.json", "salt.bin", ".keycheck"))

    @staticmethod
    def default_alias(name: str) -> str:
        """Etichetta non identificante ricavata dal nome: 'Mario Rossi' -> 'M. R.'"""
        initials = [part[0].upper() for part in name.split() if part]
        return " ".join(f"{i}." for i in initials) or "Profilo"

    def list_profiles(self) -> list[Profile]:
        """Profili elencabili PRIMA della password: si conosce solo l'alias."""
        profiles = []
        for d in self._base.iterdir():
            if not d.is_dir():
                continue
            if not self._is_complete(d):
                # Un profilo incompleto (creazione interrotta) non deve comparire
                # nel selettore: al login sollevava FileNotFoundError su salt.bin,
                # che il dialogo non cattura, e l'app moriva.
                if (d / "profile.json").exists():
                    log.warning("Profilo incompleto ignorato: %s", d.name)
                continue
            try:
                data = json.loads((d / "profile.json").read_text(encoding="utf-8"))
                # Schema legacy: il nome reale era in chiaro qui. Lo si usa come
                # alias, così i profili esistenti continuano a funzionare.
                alias = data.get("alias") or data["name"]
                profiles.append(Profile(id=d.name, name=alias, dir=d, alias=alias))
            except (OSError, ValueError, KeyError):
                log.warning("Profilo illeggibile ignorato: %s", d.name, exc_info=True)
        return sorted(profiles, key=lambda p: p.alias)

    @staticmethod
    def unlock(profile: Profile, enc: EncryptionManager) -> Profile:
        """Recupera il nome reale dal file cifrato, dopo l'autenticazione.

        Sui profili legacy ``identity.json`` non esiste e il nome resta l'alias
        (che per loro coincide col nome reale, già in chiaro su disco)."""
        identity = secure_store.read_json(profile.dir / "identity.json", enc, default=None)
        if isinstance(identity, dict) and identity.get("name"):
            profile.name = identity["name"]
        return profile

    def create_profile(self, name: str, password: str,
                       alias: Optional[str] = None) -> Profile:
        """Crea un profilo in modo atomico: si costruisce in una directory
        temporanea e la si rinomina solo a struttura completa. Interrompendosi a
        metà non resta un profilo mezzo fatto che manda in crash il login.

        Il nome del paziente viene cifrato in ``identity.json``. In chiaro resta
        solo ``alias``, che il selettore deve poter leggere prima della password:
        prima lì c'era il nome per esteso, leggibile da chiunque avesse la SD."""
        profile_id = str(uuid.uuid4())
        alias = alias or self.default_alias(name)
        profile_dir = self._base / profile_id
        staging = self._base / f".{profile_id}.partial"
        try:
            (staging / "sessions").mkdir(parents=True)
            (staging / "profile.json").write_text(
                json.dumps({"schema": _PROFILE_SCHEMA, "alias": alias}),
                encoding="utf-8",
            )
            enc = EncryptionManager.setup(staging, password)
            secure_store.write_json(staging / "identity.json", {"name": name}, enc)
            staging.rename(profile_dir)
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        log.info("Profilo creato: %s", profile_id)
        return Profile(id=profile_id, name=name, dir=profile_dir, alias=alias)

    def load_profile(self, profile_id: str) -> Profile:
        """Profilo ancora bloccato: ``name`` vale l'alias finché non si chiama
        ``unlock`` con la chiave."""
        profile_dir = self._base / profile_id
        data = json.loads((profile_dir / "profile.json").read_text(encoding="utf-8"))
        alias = data.get("alias") or data["name"]
        return Profile(id=profile_id, name=alias, dir=profile_dir, alias=alias)


def volatile_tmp_dir() -> Optional[str]:
    """Directory in RAM, se disponibile.

    ``pyedflib`` sa scrivere/leggere solo su un percorso, quindi l'ECG in chiaro
    tocca il filesystem prima di essere cifrato. Su Linux (e sul Raspberry Pi)
    ``/dev/shm`` è un tmpfs: i byte non finiscono mai sulla scheda SD, dove un
    ``unlink`` non sovrascrive nulla e resterebbero recuperabili."""
    shm = Path("/dev/shm")
    if shm.is_dir() and os.access(shm, os.W_OK):
        return str(shm)
    return None


def shred(path: Path) -> None:
    """Sovrascrive il contenuto prima di rimuoverlo. Non è una cancellazione
    sicura su SSD/SD con wear levelling, ma toglie il caso banale."""
    try:
        size = path.stat().st_size
        with open(path, "r+b") as fh:
            fh.write(os.urandom(size))
            fh.flush()
            os.fsync(fh.fileno())
    except OSError:
        pass
    path.unlink(missing_ok=True)


class EDFWriter:
    @staticmethod
    def save(
        raw_samples: np.ndarray,
        profile: Profile,
        enc: EncryptionManager,
        timestamp: datetime,
    ) -> Path:
        if len(raw_samples) < 500:
            raise ValueError(f"Too few samples: {len(raw_samples)} (minimum 500)")

        with tempfile.NamedTemporaryFile(suffix=".edf", delete=False,
                                         dir=volatile_tmp_dir()) as f:
            tmp_path = Path(f.name)

        try:
            # Il segnale memorizzato è ADC normalizzato in [-1, 1], NON mV
            # calibrati (l'AD8232 non dà un'uscita in mV calibrata). Usiamo
            # "a.u." (unità arbitrarie) per non dichiarare una calibrazione
            # fisiologica inesistente a chi apre l'EDF (es. EDFbrowser).
            signal_headers = [highlevel.make_signal_header(
                "ECG",
                dimension="a.u.",
                sample_frequency=500,
                physical_min=-1.0,
                physical_max=1.0,
            )]
            header = highlevel.make_header(
                patientname=profile.name,
                patientcode=profile.id[:8],
            )
            highlevel.write_edf(
                str(tmp_path),
                [raw_samples.astype(np.float64)],
                signal_headers,
                header,
            )
            edf_bytes = tmp_path.read_bytes()
        finally:
            shred(tmp_path)

        encrypted = enc.encrypt(edf_bytes)
        out_path = profile.dir / "sessions" / f"{timestamp.strftime('%Y%m%d_%H%M%S')}.edf"
        # Scrittura atomica come per i sidecar: un calo di tensione a metà
        # lasciava un .edf troncato, che l'archivio elencava e che poi falliva la
        # decifratura all'apertura.
        secure_store.atomic_write(out_path, encrypted)
        return out_path
