"""
pure_trace/secure_store.py
Encrypted-at-rest helpers for the small *derived-data* sidecar files:
per-profile baseline, per-session HRV features and the per-RR colormap.

Why this exists
---------------
EDFWriter already encrypts the raw ECG. But the files derived from it —
``baseline.json`` (RR statistics), ``*.features.json`` (SDNN/RMSSD/…) and
``*.colormap.npy`` (per-beat classification) — were written in plaintext, so
anyone with the SD card could read sensitive medical data without the
password. These helpers give them the same AES-128-GCM protection as the EDF,
using the profile's EncryptionManager.

(The patient name in ``profile.json`` is left in plaintext on purpose: the
login screen must list profiles *before* a password is entered.)

All readers degrade gracefully: a missing, corrupt, or legacy-plaintext file
yields the supplied ``default`` instead of raising — so the app keeps working
and old plaintext files simply read as "no data" until recreated.
"""
from __future__ import annotations

import io
import json
import os
from pathlib import Path
from typing import TYPE_CHECKING, Optional

import numpy as np
from cryptography.exceptions import InvalidTag

if TYPE_CHECKING:  # evita di trascinare pyedflib solo per un'annotazione
    from pure_trace.data_layer import EncryptionManager


class DecryptError(Exception):
    """Il file esiste ma non è decifrabile (corrotto, o cifrato con altra chiave)."""


# La cifratura nasconde il contenuto, non la sua lunghezza. La colormap contiene
# un byte per battito e ``features.json`` un indice per picco R: dalle dimensioni
# dei file, senza password, si ricavava il numero esatto di battiti e quindi la
# frequenza cardiaca media. Il testo in chiaro viene quindi imbottito a multipli
# di un blocco prima di essere cifrato.
PAD_BLOCK = 4096
_PAD_MAGIC = b"PTPAD1"
_PAD_HEADER = len(_PAD_MAGIC) + 8   # magic + lunghezza reale su 8 byte


def _pad(data: bytes) -> bytes:
    body = _PAD_MAGIC + len(data).to_bytes(8, "big") + data
    return body + b"\x00" * (-len(body) % PAD_BLOCK)


def _unpad(blob: bytes) -> bytes:
    """Rimuove l'imbottitura. I file scritti prima di questa modifica non hanno
    il magic e vengono restituiti tali e quali: nessuna migrazione necessaria.
    (Nessun ambiguità: un JSON inizia con '{', un .npy con '\\x93NUMPY'.)"""
    if not blob.startswith(_PAD_MAGIC):
        return blob
    length = int.from_bytes(blob[len(_PAD_MAGIC):_PAD_HEADER], "big")
    return blob[_PAD_HEADER:_PAD_HEADER + length]


def atomic_write(path: Path, data: bytes) -> None:
    """Write via a temp file + rename so a crash never leaves a half file.

    Il rename è atomico solo se i dati sono già sul supporto: senza ``fsync`` un
    calo di tensione del Raspberry Pi può lasciare il nome nuovo su un contenuto
    non ancora scritto. Si sincronizza anche la directory, altrimenti la voce di
    directory stessa può andare persa."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        with open(tmp, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        tmp.replace(path)
        dir_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def write_json(path: Path, obj, enc: EncryptionManager) -> None:
    payload = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    atomic_write(path, enc.encrypt(_pad(payload)))


def read_json(path: Optional[Path], enc: EncryptionManager, default, strict: bool = False):
    """Legge un JSON cifrato.

    Con ``strict=True`` un file presente ma illeggibile solleva ``DecryptError``
    invece di degradare a ``default``. Serve dove confondere "nessun dato" con
    "dato corrotto" causa perdita di dati: la baseline veniva riletta come pool
    vuoto e poi sovrascritta, distruggendo lo storico del paziente in silenzio."""
    if not path or not path.exists():
        return default
    try:
        return json.loads(_unpad(enc.decrypt(path.read_bytes())).decode("utf-8"))
    except (InvalidTag, ValueError, OSError) as exc:
        if strict:
            raise DecryptError(str(path)) from exc
        return default


def write_npy(path: Path, arr: np.ndarray, enc: EncryptionManager) -> None:
    buf = io.BytesIO()
    np.save(buf, arr)
    atomic_write(path, enc.encrypt(_pad(buf.getvalue())))


def read_npy(path: Optional[Path], enc: EncryptionManager, default: np.ndarray) -> np.ndarray:
    if not path or not path.exists():
        return default
    try:
        return np.load(io.BytesIO(_unpad(enc.decrypt(path.read_bytes()))))
    except (InvalidTag, ValueError, OSError):
        return default
