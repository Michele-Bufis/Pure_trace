"""
pure_trace/serial_port.py
Individuazione automatica della porta seriale dell'Arduino.

Perché esiste
-------------
``config.SERIAL_PORT`` era fissato a ``"COM4"`` (Windows) mentre il dispositivo
gira su Raspberry Pi, dove il Nano si presenta come ``/dev/ttyUSB0``. Con la
porta sbagliata il thread seriale terminava in silenzio: nessun campione,
``L,`` mai ricevuto, pulsante di acquisizione disabilitato per sempre e nessun
messaggio d'errore. Sembrava un problema di elettrodi.

Qui la porta viene cercata per VID USB del convertitore seriale, così lo stesso
codice funziona su Pi, Linux, macOS e Windows senza riconfigurazione.
"""
from typing import Optional

# VID dei convertitori USB-seriale montati sulle schede Arduino più comuni.
_KNOWN_VENDOR_IDS = {
    0x1A86,  # QinHeng CH340/CH341 — Arduino Nano cloni (il nostro caso)
    0x2341,  # Arduino SA (Uno, Mega, Nano ufficiale)
    0x2A03,  # Arduino SRL (.org)
    0x0403,  # FTDI FT232 — Nano vecchie revisioni
    0x10C4,  # Silicon Labs CP210x
}

_DEVICE_HINTS = ("ttyUSB", "ttyACM", "cu.usbserial", "cu.wchusbserial")


def _list_ports():
    from serial.tools import list_ports  # import pigro: non serve nei test
    return list(list_ports.comports())


def find_port(preferred: Optional[str] = None, ports=None) -> Optional[str]:
    """Restituisce il device della porta dell'Arduino, o None se non trovato.

    ``preferred`` (di norma ``config.SERIAL_PORT``) vince se è effettivamente
    presente fra le porte enumerate; se è configurato ma assente viene ignorato,
    così una configurazione stantia non impedisce l'avvio.
    """
    if ports is None:
        ports = _list_ports()

    if preferred:
        for p in ports:
            if p.device == preferred:
                return p.device

    for p in ports:
        if getattr(p, "vid", None) in _KNOWN_VENDOR_IDS:
            return p.device

    for p in ports:
        if any(hint in p.device for hint in _DEVICE_HINTS):
            return p.device

    return None
