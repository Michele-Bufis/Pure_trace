"""
pure_trace/logging_setup.py
Configurazione del logging applicativo.

Perché esiste
-------------
Il progetto non aveva alcun logging: gli errori venivano ingoiati da ``except``
silenziosi e, su un Raspberry Pi senza console, ogni malfunzionamento era una
caccia al buio. Qui si configura una destinazione unica (stderr + file a
rotazione accanto ai dati), così un problema in campo lascia una traccia.
"""
import logging
import logging.handlers
from pathlib import Path
from typing import Optional

_FORMAT = "%(asctime)s %(levelname)-7s %(name)-28s %(message)s"
_configured = False


def setup(log_dir: Optional[Path] = None, level: int = logging.INFO) -> None:
    """Configura il root logger. Idempotente: chiamate ripetute non duplicano
    gli handler (i test importano i moduli più volte)."""
    global _configured
    if _configured:
        return

    root = logging.getLogger()
    root.setLevel(level)

    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter(_FORMAT))
    root.addHandler(console)

    if log_dir is not None:
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            file_handler = logging.handlers.RotatingFileHandler(
                log_dir / "pure_trace.log", maxBytes=1_000_000, backupCount=3,
                encoding="utf-8",
            )
            file_handler.setFormatter(logging.Formatter(_FORMAT))
            root.addHandler(file_handler)
        except OSError:
            # Un disco pieno o in sola lettura non deve impedire l'avvio.
            root.warning("Impossibile aprire il file di log in %s", log_dir)

    _configured = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
