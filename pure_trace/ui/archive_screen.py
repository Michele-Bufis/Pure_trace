from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
from pyedflib import highlevel

from pure_trace import config, secure_store
from pure_trace.analysis_engine import (
    detect_rpeak_indices, remove_session_from_baseline,
)
from pure_trace.data_layer import (
    EncryptionManager, Profile, shred, volatile_tmp_dir,
)
from pure_trace.logging_setup import get_logger
from pure_trace.ui import theme

log = get_logger(__name__)

try:
    from PyQt5.QtCore import QThread, Qt, QTimer, pyqtSignal
    from PyQt5.QtGui import QColor, QFont, QPainter
    from PyQt5.QtWidgets import (
        QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel,
        QMessageBox, QPushButton, QScrollArea, QScroller,
        QStackedWidget, QVBoxLayout, QWidget,
    )
    from pure_trace.ui.widgets import EcgPlotWidget, ErrorOverlay
    _HAS_QT = True
except ImportError:
    _HAS_QT = False
    QWidget = object  # type: ignore[assignment,misc]
    QThread = object  # type: ignore[assignment,misc]
    pyqtSignal = lambda *a, **kw: None  # type: ignore[assignment,misc]


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class SessionRecord:
    timestamp: datetime
    edf_path: Path
    colormap_path: Optional[Path]
    features_path: Optional[Path]


def scan_sessions(sessions_dir: Path) -> list[SessionRecord]:
    """Scan sessions directory; return SessionRecords sorted newest-first."""
    if not sessions_dir.exists():
        return []

    stems: dict[str, dict[str, Path]] = {}
    for f in sessions_dir.iterdir():
        if not f.is_file():
            continue
        name = f.name
        if name.endswith(".colormap.npy"):
            stem = name[: -len(".colormap.npy")]
            stems.setdefault(stem, {})["colormap"] = f
        elif name.endswith(".features.json"):
            stem = name[: -len(".features.json")]
            stems.setdefault(stem, {})["features"] = f
        elif name.endswith(".edf"):
            stem = name[: -len(".edf")]
            stems.setdefault(stem, {})["edf"] = f

    records: list[SessionRecord] = []
    for stem, files in stems.items():
        if "edf" not in files:
            continue
        try:
            ts = datetime.strptime(stem, "%Y%m%d_%H%M%S")
        except ValueError:
            continue
        records.append(SessionRecord(
            timestamp=ts,
            edf_path=files["edf"],
            colormap_path=files.get("colormap"),
            features_path=files.get("features"),
        ))

    return sorted(records, key=lambda r: r.timestamp, reverse=True)


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

def rr_band_boundaries(features: dict, raw: np.ndarray, fs: int) -> list[int]:
    """Confini (in campioni) delle N bande RR: sono gli indici degli N+1 picchi R.

    Gli indici sono persistiti in ``features['rr_peaks']`` al momento
    dell'analisi. Le sessioni salvate prima di questa modifica non li hanno: in
    quel caso si rileva di nuovo (operazione costosa, da non fare mai sul thread
    della GUI). Prima i confini erano ricavati dal cumulato degli RR partendo da
    zero, il che disallineava le bande dal tracciato: il primo picco non cade in
    corrispondenza del campione 0."""
    peaks = features.get("rr_peaks")
    if isinstance(peaks, list) and len(peaks) >= 2:
        return [int(p) for p in peaks]
    return [int(p) for p in detect_rpeak_indices(raw, fs)]


def export_session(
    edf_bytes: bytes,
    features_path: Optional[Path],
    dest_edf: Path,
    enc,
) -> None:
    """Write decrypted EDF bytes to dest_edf; write the features JSON alongside
    in PLAINTEXT (decrypted), so the exported bundle is readable by external
    tools like EDFbrowser."""
    dest_edf.parent.mkdir(parents=True, exist_ok=True)
    dest_edf.write_bytes(edf_bytes)
    features = secure_store.read_json(features_path, enc, default=None)
    if isinstance(features, dict):
        dest_features = dest_edf.parent / (dest_edf.stem + ".features.json")
        dest_features.write_text(
            json.dumps(features, ensure_ascii=False), encoding="utf-8"
        )


# ---------------------------------------------------------------------------
# Colour constants and status utilities
# ---------------------------------------------------------------------------

if _HAS_QT:
    _STRIP_COLORS: dict = {code: QColor(hex_) for code, hex_ in theme.STRIP.items()}


def _status_from_features(features: dict) -> str:
    """Stato sessione memorizzato (Mahalanobis), o NEUTRAL se assente/ignoto."""
    s = features.get("status")
    return s if s in ("GREEN", "YELLOW", "RED", "NEUTRAL") else "NEUTRAL"


def _tint_color_for_z(z) -> str:
    """Colore di tinta di uno scalare metrico dato lo scostamento per-feature z."""
    if z is None:
        return theme.TEXT
    az = abs(float(z))
    if az <= config.METRIC_TINT_GREEN_Z:
        return theme.GREEN
    if az <= config.METRIC_TINT_YELLOW_Z:
        return theme.YELLOW
    return theme.RED


def _load_colormap(path: Optional[Path], enc) -> np.ndarray:
    return secure_store.read_npy(path, enc, default=np.array([], dtype=np.uint8))


def _load_features(path: Optional[Path], enc) -> dict:
    data = secure_store.read_json(path, enc, default={})
    return data if isinstance(data, dict) else {}


# ---------------------------------------------------------------------------
# ColormapStripWidget
# ---------------------------------------------------------------------------

class ColormapStripWidget(QWidget):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._colormap: np.ndarray = np.array([], dtype=np.uint8)

    def set_colormap(self, colormap: np.ndarray) -> None:
        self._colormap = colormap
        self.update()

    def paintEvent(self, _event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.setOpacity(0.75)
        n = len(self._colormap)
        w, h = self.width(), self.height()
        if n == 0:
            painter.fillRect(0, 0, w, h, QColor(theme.STRIP_EMPTY))
        else:
            for i, code in enumerate(self._colormap):
                x0 = int(i * w / n)
                x1 = int((i + 1) * w / n)
                painter.fillRect(x0, 0, max(1, x1 - x0), h,
                                 _STRIP_COLORS.get(int(code), QColor(theme.STRIP[255])))
        painter.end()


# ---------------------------------------------------------------------------
# MetricsGridWidget
# ---------------------------------------------------------------------------

_METRICS_DEF = [
    ("sdnn",    "SDNN",    "ms", 1000.0),
    ("rmssd",   "RMSSD",   "ms", 1000.0),
    ("pnn50",   "pNN50",   "%",  1.0),
    ("mean_rr", "Mean RR", "ms", 1000.0),
    ("qrs_duration", "QRS",     "ms", 1.0),
]


class MetricsGridWidget(QWidget):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        grid = QGridLayout(self)
        grid.setSpacing(4)
        grid.setContentsMargins(0, 0, 0, 0)
        self._value_labels: dict[str, object] = {}
        for i, (key, display, unit, _) in enumerate(_METRICS_DEF):
            card = QFrame()
            card.setStyleSheet(theme.metric_card_qss())
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(13, 7, 13, 7)
            card_layout.setSpacing(1)
            lbl = QLabel(display.upper())
            lbl.setStyleSheet(theme.section_label_qss())
            val = QLabel("—")
            val.setStyleSheet(theme.metric_value_qss(active=False))
            card_layout.addWidget(lbl)
            card_layout.addWidget(val)
            grid.addWidget(card, 0, i)          # single row of four cards
            self._value_labels[key] = val

    def set_features(self, features: dict) -> None:
        # Tinta ∝ scostamento per-feature dalla baseline (z). Per la card mean_rr
        # si usa lo z di mean_hr (stessa magnitudo di scostamento del ritmo).
        fz = features.get("feature_z") or {}
        zkey = {"sdnn": "sdnn", "rmssd": "rmssd", "pnn50": "pnn50", "mean_rr": "mean_hr", "qrs_duration": "qrs_duration"}
        for key, _, unit, scale in _METRICS_DEF:
            lbl = self._value_labels[key]
            raw_val = features.get(key)
            if raw_val is None:
                lbl.setText("—")
                lbl.setStyleSheet(theme.metric_value_qss(active=False))
                continue
            try:
                display_val = raw_val * scale
                color = _tint_color_for_z(fz.get(zkey[key]))
                lbl.setText(f"{display_val:.0f} {unit}")
                lbl.setStyleSheet(theme.metric_value_tint_qss(color))
            except (TypeError, ValueError):
                lbl.setText("—")
                lbl.setStyleSheet(theme.metric_value_qss(active=False))


# ---------------------------------------------------------------------------
# _SessionRowWidget
# ---------------------------------------------------------------------------

class _SessionRowWidget(QWidget):
    clicked: pyqtSignal = pyqtSignal(object)  # emits SessionRecord

    def __init__(self, record: SessionRecord, enc,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._record = record
        self._enc = enc
        self._press_pos = None
        self._build()
        self.setCursor(Qt.PointingHandCursor)

    def _build(self) -> None:
        # Outer widget only provides the gap between cards; the visible card is
        # an inner QFrame so border-radius / hover styling actually paints.
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 5, 0, 5)
        outer.setSpacing(0)

        card = QFrame()
        card.setStyleSheet(theme.session_card_qss())
        outer.addWidget(card)

        colormap = _load_colormap(self._record.colormap_path, self._enc)
        features = _load_features(self._record.features_path, self._enc)
        status   = _status_from_features(features)
        color    = theme.STATUS[status]

        row = QHBoxLayout(card)
        row.setContentsMargins(0, 0, 12, 0)
        row.setSpacing(0)

        # ── coloured status bar (full height, flush left) ─────────
        statbar = QFrame()
        statbar.setFixedWidth(5)
        statbar.setStyleSheet(
            f"background:{color};border-top-left-radius:12px;"
            f"border-bottom-left-radius:12px"
        )
        row.addWidget(statbar)

        center = QVBoxLayout()
        center.setContentsMargins(14, 11, 14, 11)
        center.setSpacing(7)

        # line 1: date · duration pill · status tag
        line1 = QHBoxLayout()
        line1.setSpacing(10)
        date_str = self._record.timestamp.strftime("%d %b %Y · %H:%M")
        date_lbl = QLabel(date_str)
        date_lbl.setStyleSheet(f"color:{theme.TEXT};font-size:14px;font-weight:600;border:none")
        line1.addWidget(date_lbl)
        dur = QLabel(self._duration_str(colormap, features))
        dur.setStyleSheet(theme.dur_pill_qss())
        line1.addWidget(dur)
        line1.addStretch()
        tag = QLabel(theme.STATUS_LABEL[status].upper())
        tag.setStyleSheet(theme.status_tag_qss(color))
        line1.addWidget(tag)
        center.addLayout(line1)

        # line 2: metric chips, or a muted note for short sessions
        if features.get("sdnn") is not None:
            center.addWidget(self._metrics_row(features))
        else:
            no_m = QLabel("Sessione breve — nessuna metrica")
            no_m.setStyleSheet(f"color:{theme.MUTED};font-size:11px;border:none")
            center.addWidget(no_m)

        # line 3: thin colormap strip
        if len(colormap) > 0:
            strip = ColormapStripWidget()
            strip.set_colormap(colormap)
            strip.setFixedHeight(4)
            center.addWidget(strip)

        row.addLayout(center, stretch=1)

        chevron = QLabel("›")
        chevron.setStyleSheet(f"color:{theme.BORDER_2};font-size:22px;border:none")
        row.addWidget(chevron)

    @staticmethod
    def _duration_str(colormap: np.ndarray, features: dict) -> str:
        n = len(colormap)
        mean_rr = features.get("mean_rr")
        if n > 0 and mean_rr:
            secs = n * mean_rr
            return f"{secs / 60:.0f} min" if secs >= 60 else f"{secs:.0f} s"
        return "< 1 min"

    @staticmethod
    def _metrics_row(features: dict) -> QWidget:
        box = QWidget()
        lay = QHBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        for key, label, unit, scale in (_METRICS_DEF[0], _METRICS_DEF[1],_METRICS_DEF[2], _METRICS_DEF[4]):  # sdnn, rmssd, pnn50, qrs
            v = features.get(key)
            if v is None:
                continue
            chip = QLabel(f"{label}  {v * scale:.0f} {unit}")
            chip.setStyleSheet(theme.metric_chip_qss())
            lay.addWidget(chip)
        lay.addStretch()
        return box

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        # Remember where the touch started; the open happens on release only if
        # the finger didn't travel (i.e. it was a tap, not a scroll drag).
        self._press_pos = event.pos()

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[override]
        if self._press_pos is None:
            return
        travelled = (event.pos() - self._press_pos).manhattanLength()
        self._press_pos = None
        if travelled < 16:          # a tap — not a scroll gesture
            self.clicked.emit(self._record)


# ---------------------------------------------------------------------------
# SessionListWidget
# ---------------------------------------------------------------------------

class SessionListWidget(QWidget):
    session_clicked: pyqtSignal = pyqtSignal(object)  # emits SessionRecord

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_top_bar())

        # Section heading: "Archivio  ·  N sessioni"
        head = QHBoxLayout()
        head.setContentsMargins(18, 12, 18, 4)
        title = QLabel("Archivio")
        title.setStyleSheet(f"color:{theme.TEXT};font-size:17px;font-weight:700;border:none")
        head.addWidget(title)
        self._count_label = QLabel("")
        self._count_label.setStyleSheet(f"color:{theme.MUTED};font-size:13px;border:none")
        head.addWidget(self._count_label)
        head.addStretch()
        root.addLayout(head)

        self._empty_label = QLabel("Nessuna sessione registrata")
        self._empty_label.setAlignment(Qt.AlignCenter)
        self._empty_label.setStyleSheet(f"color: {theme.MUTED}; font-size: 14px;")
        self._empty_label.setVisible(False)
        root.addWidget(self._empty_label, stretch=1)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        # Kinetic touch scrolling: a press-drag scrolls the list (instead of
        # the touch being treated as an immediate tap on a row). A genuine tap
        # is still delivered to the row (see _SessionRowWidget release logic).
        QScroller.grabGesture(
            self._scroll.viewport(), QScroller.LeftMouseButtonGesture
        )
        self._container = QWidget()
        self._vbox = QVBoxLayout(self._container)
        self._vbox.setContentsMargins(16, 4, 16, 12)
        self._vbox.setSpacing(0)
        self._vbox.addStretch()
        self._scroll.setWidget(self._container)
        root.addWidget(self._scroll, stretch=1)

    def _build_top_bar(self) -> QFrame:
        bar = QFrame()
        bar.setFixedHeight(50)
        bar.setStyleSheet(theme.top_bar_qss())
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(16, 0, 16, 0)
        lay.setSpacing(12)

        logo = QLabel("+")
        logo.setFixedSize(26, 26)
        logo.setAlignment(Qt.AlignCenter)
        logo.setStyleSheet(theme.brand_logo_qss())
        lay.addWidget(logo)
        brand = QLabel("Pure-Trace")
        brand.setFont(QFont("Sans", 13, QFont.Bold))
        brand.setStyleSheet("border:none")
        lay.addWidget(brand)

        self._profile_chip = QLabel("")
        self._profile_chip.setStyleSheet(theme.chip_qss())
        lay.addWidget(self._profile_chip)
        lay.addStretch()

        self._clock_label = QLabel("--:--")
        self._clock_label.setStyleSheet(theme.clock_qss())
        lay.addWidget(self._clock_label)

        self._clock_timer = QTimer(self)
        self._clock_timer.timeout.connect(self._refresh_clock)
        self._clock_timer.start(1000)
        self._refresh_clock()
        return bar

    def _refresh_clock(self) -> None:
        from datetime import datetime as _dt
        self._clock_label.setText(_dt.now().strftime("%H:%M"))

    def load(self, profile: Profile, enc) -> None:
        self._profile_chip.setText(profile.name)
        # Remove all rows (keep the trailing stretch)
        while self._vbox.count() > 1:
            item = self._vbox.takeAt(0)
            if (w := item.widget()):
                w.deleteLater()

        records = scan_sessions(profile.dir / "sessions")
        n = len(records)
        self._count_label.setText(
            "nessuna sessione" if n == 0 else
            f"· {n} session{'e' if n == 1 else 'i'}"
        )

        if not records:
            self._empty_label.setVisible(True)
            self._scroll.setVisible(False)
            return

        self._empty_label.setVisible(False)
        self._scroll.setVisible(True)
        for record in records:
            row = _SessionRowWidget(record, enc)
            row.clicked.connect(self.session_clicked)
            self._vbox.insertWidget(self._vbox.count() - 1, row)


# ---------------------------------------------------------------------------
# _DecryptThread
# ---------------------------------------------------------------------------

class _DecryptThread(QThread):
    # (raw, edf_bytes, boundaries, colormap)
    finished_ok:  pyqtSignal = pyqtSignal(object, object, object, object)
    finished_err: pyqtSignal = pyqtSignal(str)

    def __init__(self, record: SessionRecord, enc: "EncryptionManager",
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._record = record
        self._enc    = enc

    def run(self) -> None:
        try:
            encrypted = self._record.edf_path.read_bytes()
            edf_bytes = self._enc.decrypt(encrypted)
            # Come in EDFWriter: l'EDF in chiaro passa da un tmpfs quando c'è,
            # e viene comunque sovrascritto prima di essere rimosso.
            with tempfile.NamedTemporaryFile(suffix=".edf", delete=False,
                                             dir=volatile_tmp_dir()) as fh:
                tmp = Path(fh.name)
                fh.write(edf_bytes)
            try:
                signals, _, _ = highlevel.read_edf(str(tmp))
                raw = signals[0].astype(np.float32)
            finally:
                shred(tmp)

            # Le bande RR si calcolano QUI, non nella slot della GUI: per una
            # sessione legacy senza 'rr_peaks' serve un rilevamento completo,
            # che congelerebbe l'interfaccia per secondi sul Raspberry Pi.
            colormap = _load_colormap(self._record.colormap_path, self._enc)
            boundaries: list[int] = []
            if len(colormap) > 0:
                features = _load_features(self._record.features_path, self._enc)
                boundaries = rr_band_boundaries(features, raw, config.SAMPLING_RATE)
            self.finished_ok.emit(raw, edf_bytes, boundaries, colormap)
        except Exception as exc:
            self.finished_err.emit(str(exc))


# ---------------------------------------------------------------------------
# SessionDetailWidget
# ---------------------------------------------------------------------------

class SessionDetailWidget(QWidget):
    back_requested: pyqtSignal = pyqtSignal()
    deleted: pyqtSignal = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._record:    Optional[SessionRecord] = None
        self._edf_bytes: Optional[bytes]         = None
        self._thread:    Optional[_DecryptThread] = None
        self._enc = None
        self._profile: Optional["Profile"] = None
        self._build_ui()
        self._error_overlay = ErrorOverlay(self)

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._error_overlay.position_top_right()

    def _show_error(self, message: str) -> None:
        self._error_overlay.show_message(message)

    # ── construction ──────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 8, 16, 10)
        root.setSpacing(8)

        # Header: back icon-button · date (single line) · status pill — kept
        # compact so the bottom action buttons keep their full height on the
        # short 480 px Raspberry Pi display.
        header = QHBoxLayout()
        header.setSpacing(10)
        back_btn = QPushButton("‹")
        back_btn.setFixedSize(34, 34)
        back_btn.setFont(QFont("Sans", 17))
        back_btn.setStyleSheet(theme.icon_button_qss())
        back_btn.clicked.connect(self.back_requested)
        header.addWidget(back_btn)

        self._date_label = QLabel()
        self._date_label.setTextFormat(Qt.RichText)
        self._date_label.setStyleSheet("border:none")
        header.addWidget(self._date_label)
        header.addStretch()

        self._status_lbl = QLabel()
        self._status_lbl.setStyleSheet(theme.status_pill_qss(theme.MUTED))
        header.addWidget(self._status_lbl)
        root.addLayout(header)

        # ECG card: header strip + plot stack (spinner|plot|error)
        ecg_card = QFrame()
        ecg_card.setStyleSheet(theme.card_qss())
        cardl = QVBoxLayout(ecg_card)
        cardl.setContentsMargins(0, 0, 0, 0)
        cardl.setSpacing(0)
        chead = QFrame()
        chead.setStyleSheet(f"QFrame{{border:none;border-bottom:1px solid {theme.BORDER}}}")
        chl = QHBoxLayout(chead)
        chl.setContentsMargins(16, 6, 16, 6)
        clead = QLabel("Tracciato registrato")
        clead.setFont(QFont("Sans", 11, QFont.Bold))
        clead.setStyleSheet("border:none")
        chl.addWidget(clead)
        chl.addStretch()
        chint = QLabel("scorri per esplorare · finestra 8 s")
        chint.setStyleSheet(theme.section_label_qss())
        chl.addWidget(chint)
        cardl.addWidget(chead)

        self._plot_stack = QStackedWidget()

        spinner = QLabel("Caricamento…")
        spinner.setAlignment(Qt.AlignCenter)
        spinner.setStyleSheet(f"color: {theme.MUTED}; font-size: 13px;")
        self._plot_stack.addWidget(spinner)

        self._ecg = EcgPlotWidget()
        self._plot_stack.addWidget(self._ecg)

        self._err_label = QLabel()
        self._err_label.setAlignment(Qt.AlignCenter)
        self._err_label.setWordWrap(True)
        self._err_label.setStyleSheet(f"color: {theme.RED}; font-size: 12px;")
        self._plot_stack.addWidget(self._err_label)

        # The plot expands to fill the available height (stretch=1); a minimum
        # keeps it readable on the small Raspberry Pi touchscreen.
        self._plot_stack.setMinimumHeight(120)
        cardl.addWidget(self._plot_stack, stretch=1)
        root.addWidget(ecg_card, stretch=1)

        # Colour legend
        legend = QHBoxLayout()
        legend.setSpacing(16)
        for hex_color, text in [
            (theme.GREEN, "nella norma"),
            (theme.YELLOW, "lieve variazione"),
            (theme.RED, "fuori baseline"),
        ]:
            dot = QLabel(f"● {text}")
            dot.setStyleSheet(f"color: {hex_color}; font-size: 11px; border:none")
            legend.addWidget(dot)
        legend.addStretch()
        root.addLayout(legend)

        # Colormap strip — thin summary of the whole recording, beat-by-beat
        self._strip = ColormapStripWidget()
        self._strip.setFixedHeight(5)
        root.addWidget(self._strip)

        # Metrics (single row of four cards)
        self._metrics = MetricsGridWidget()
        root.addWidget(self._metrics)

        # Action buttons (export + delete) on one compact row to save height
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        self._export_btn = QPushButton("Esporta EDF")
        self._export_btn.setEnabled(False)
        self._export_btn.setFixedHeight(44)
        self._export_btn.setFont(QFont("Sans", 13))
        self._export_btn.setStyleSheet(theme.export_button_qss())
        self._export_btn.clicked.connect(self._on_export_clicked)
        btn_row.addWidget(self._export_btn, stretch=1)

        self._delete_btn = QPushButton("Elimina")
        self._delete_btn.setFixedHeight(44)
        self._delete_btn.setFixedWidth(150)
        self._delete_btn.setFont(QFont("Sans", 13))
        self._delete_btn.setStyleSheet(theme.delete_button_qss())
        self._delete_btn.clicked.connect(self._on_delete_clicked)
        btn_row.addWidget(self._delete_btn)

        root.addLayout(btn_row)

    # ── public API ────────────────────────────────────────────────────────

    def load(self, record: SessionRecord, enc: "EncryptionManager",
             profile: Optional["Profile"] = None) -> None:
        self._record    = record
        self._enc       = enc
        self._profile   = profile
        self._edf_bytes = None
        self._export_btn.setEnabled(False)
        self._plot_stack.setCurrentIndex(0)  # spinner

        # Date + status from the (encrypted) sidecar files — small, fast to
        # decrypt, no need to decrypt the full EDF yet.
        date_main = record.timestamp.strftime("%d %B %Y")
        date_sub  = record.timestamp.strftime("%H:%M · derivazione I")
        self._date_label.setText(
            f"<span style='font-size:14px;font-weight:600;color:{theme.TEXT}'>{date_main}</span>"
            f"  <span style='font-size:12px;color:{theme.MUTED}'>{date_sub}</span>"
        )
        colormap = _load_colormap(record.colormap_path, enc)
        features = _load_features(record.features_path, enc)
        status   = _status_from_features(features)
        self._status_lbl.setText(f"●  {theme.STATUS_LABEL[status]}")
        self._status_lbl.setStyleSheet(theme.status_pill_qss(theme.STATUS[status]))
        self._strip.set_colormap(colormap)
        self._metrics.set_features(features)

        # Start background decrypt.
        # Il thread esegue un run() senza event loop, quindi quit() non avrebbe
        # effetto. Non lo si attende però sul thread della GUI (bloccava
        # l'interfaccia se si toccavano due sessioni di seguito): si scollegano i
        # suoi segnali, così il risultato ormai obsoleto non sovrascrive quello
        # nuovo, e lo si lascia terminare da solo.
        if self._thread is not None and self._thread.isRunning():
            for signal in (self._thread.finished_ok, self._thread.finished_err):
                try:
                    signal.disconnect()
                except TypeError:
                    pass                      # nessuno slot collegato
            self._thread.finished.connect(self._thread.deleteLater)
        self._thread = _DecryptThread(record, enc, self)
        self._thread.finished_ok.connect(self._on_decrypt_ok)
        self._thread.finished_err.connect(self._on_decrypt_err)
        self._thread.start()

    # ── slots ─────────────────────────────────────────────────────────────

    def _on_decrypt_ok(self, raw: object, edf_bytes: object,
                       boundaries: object, colormap: object) -> None:
        raw_arr: np.ndarray = raw  # type: ignore[assignment]
        self._edf_bytes = edf_bytes  # type: ignore[assignment]
        self._ecg.show_static(raw_arr)
        bounds: list = boundaries  # type: ignore[assignment]
        cmap: np.ndarray = colormap  # type: ignore[assignment]
        if len(bounds) >= 2 and len(cmap) > 0:
            self._ecg.add_rr_bands(bounds, cmap)
        self._plot_stack.setCurrentIndex(1)
        self._export_btn.setEnabled(True)

    def _on_decrypt_err(self, msg: str) -> None:
        self._plot_stack.setCurrentIndex(1)
        self._show_error(f"Errore di lettura: {msg}")

    def _on_export_clicked(self) -> None:
        if not self._edf_bytes or not self._record:
            return
        # L'export produce file NON cifrati: chi lo usa deve saperlo prima di
        # scriverli su una chiavetta, non dopo.
        confirm = QMessageBox.warning(
            self, "Esportazione non cifrata",
            "Il file esportato NON sarà protetto da password: conterrà il "
            "tracciato ECG e il nome del paziente in chiaro.\n\nContinuare?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        default_name = self._record.timestamp.strftime("%Y%m%d_%H%M%S") + ".edf"
        dest, _ = QFileDialog.getSaveFileName(
            self, "Esporta sessione", default_name, "EDF files (*.edf)"
        )
        if not dest:
            return
        try:
            export_session(self._edf_bytes, self._record.features_path, Path(dest), self._enc)
            # Il percorso è scelto dall'utente e può contenere il nome del
            # paziente (es. /media/usb/mario_rossi.edf): non finisce nel log,
            # che è in chiaro. Si registra solo QUALE sessione è stata esportata.
            log.info("Sessione %s esportata in chiaro",
                     self._record.timestamp.strftime("%Y%m%d_%H%M%S"))
        except Exception as exc:
            log.exception("Export fallito")
            self._show_error(f"Esportazione fallita: {exc}")

    def _on_delete_clicked(self) -> None:
        if not self._record:
            return
        reply = QMessageBox.question(
            self,
            "Eliminare la sessione?",
            "Questa acquisizione verrà eliminata definitivamente. Continuare?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        session_id = self._record.timestamp.strftime("%Y%m%d_%H%M%S")

        # Prima la baseline, poi i file: se la rimozione dal modello fallisce si
        # interrompe e i dati restano coerenti fra loro. All'inverso, cancellare
        # i file lasciando il vettore nel modello lo renderebbe irrecuperabile.
        if self._profile is not None:
            try:
                removed = remove_session_from_baseline(
                    self._profile, self._enc, session_id)
                if not removed:
                    log.info('Sessione %s non presente in baseline '
                             '(schema legacy o mai scorata)', session_id)
            except Exception as exc:
                log.exception('Rimozione dalla baseline fallita')
                self._show_error(
                    f"Impossibile aggiornare la baseline: {exc}\n"
                    f"La sessione NON è stata eliminata.")
                return

        for p in (self._record.edf_path, self._record.colormap_path,
                  self._record.features_path):
            if p:
                try:
                    p.unlink(missing_ok=True)
                except OSError:
                    log.exception('Impossibile eliminare %s', p)
        log.info('Sessione %s eliminata', session_id)
        self.deleted.emit()


# ---------------------------------------------------------------------------
# ArchiveScreen
# ---------------------------------------------------------------------------

class ArchiveScreen(QWidget):
    def __init__(self, profile: "Profile", enc: "EncryptionManager",
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._profile = profile
        self._enc     = enc

        self._stack  = QStackedWidget()
        self._list   = SessionListWidget()
        self._detail = SessionDetailWidget()
        self._stack.addWidget(self._list)    # page 0
        self._stack.addWidget(self._detail)  # page 1

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._stack)

        self._list.session_clicked.connect(self._show_detail)
        self._detail.back_requested.connect(self._show_list)
        self._detail.deleted.connect(self._on_deleted)

    def load(self) -> None:
        """Refresh the session list. Call each time the archive tab is activated."""
        self._list.load(self._profile, self._enc)
        self._stack.setCurrentIndex(0)

    def _show_detail(self, record: SessionRecord) -> None:
        self._detail.load(record, self._enc, self._profile)
        self._stack.setCurrentIndex(1)

    def _show_list(self) -> None:
        self._stack.setCurrentIndex(0)

    def _on_deleted(self) -> None:
        # Session files removed → refresh the list and return to it.
        self._list.load(self._profile, self._enc)
        self._stack.setCurrentIndex(0)


# ---------------------------------------------------------------------------
# TabBar
# ---------------------------------------------------------------------------

class TabBar(QWidget):
    tab_changed: pyqtSignal = pyqtSignal(int)
    exit_requested: pyqtSignal = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(52)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        _style = theme.tab_button_qss()
        self._btn_rec     = QPushButton("●  Acquisizione")
        self._btn_archive = QPushButton("☰  Archivio")
        for btn in (self._btn_rec, self._btn_archive):
            btn.setCheckable(True)
            btn.setFont(QFont("Sans", 13))
            btn.setStyleSheet(_style)
            layout.addWidget(btn)

        # Exit button (✕) — always reachable from the bottom bar so the
        # fullscreen app can be closed by touch, with no window title bar.
        self._btn_exit = QPushButton("✕")
        self._btn_exit.setFont(QFont("Sans", 15))
        self._btn_exit.setFixedWidth(64)
        self._btn_exit.setStyleSheet(_style)
        self._btn_exit.clicked.connect(self.exit_requested)
        layout.addWidget(self._btn_exit)

        self._btn_rec.setChecked(True)
        self._btn_rec.clicked.connect(lambda: self._select(0))
        self._btn_archive.clicked.connect(lambda: self._select(1))

    def _select(self, index: int) -> None:
        self._btn_rec.setChecked(index == 0)
        self._btn_archive.setChecked(index == 1)
        self.tab_changed.emit(index)
