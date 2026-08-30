import numpy as np
import pyqtgraph as pg
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)
from PyQt5.QtGui import QColor
from pure_trace import config
from pure_trace.ui import theme

pg.setConfigOption('background', theme.SURFACE)   # white, to match the ECG card
pg.setConfigOption('foreground', theme.TEXT)


class MessageOverlay(QFrame):
    """Dismissible toast that floats above a screen's normal layout.

    The semantic colour is supplied when displaying the message, so the same
    component can communicate both errors and the outcome of a recording.
    """

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setFixedSize(340, 88)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 8, 10)
        layout.setSpacing(8)

        self._label = QLabel()
        self._label.setWordWrap(True)
        self._label.setStyleSheet(
            f"color:{theme.TEXT};background:transparent;font-size:13px;"
            "font-weight:600;border:none;")
        layout.addWidget(self._label, stretch=1)

        self._close = QPushButton('×')
        self._close.setAccessibleName('Chiudi messaggio')
        self._close.setFixedSize(28, 28)
        self._close.clicked.connect(self.hide)
        layout.addWidget(self._close, alignment=Qt.AlignTop)
        self.hide()

        self._set_tone(theme.RED, theme.RED_SF)

    def _set_tone(self, color: str, background: str) -> None:
        self.setStyleSheet(
            f"background:{background};border:1px solid {color};"
            "border-radius:10px;"
        )
        self._close.setStyleSheet(
            f"QPushButton{{color:{theme.MUTED};background:transparent;border:none;"
            "font-size:24px;font-weight:600;padding:0;}"
            f"QPushButton:hover{{color:{color};background:{theme.SURFACE_2};"
            "border-radius:12px;}"
        )

    def show_message(self, message: str, *, color: str = theme.RED,
                     background: str = theme.RED_SF) -> None:
        self._set_tone(color, background)
        self._label.setText(message)
        self.position_top_right()
        self.show()
        self.raise_()

    def position_top_right(self, top: int = 64, margin: int = 14) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        self.move(max(margin, parent.width() - self.width() - margin), top)


class ErrorOverlay(MessageOverlay):
    """Error-specialised alias retained by screens that only show errors."""

    def show_message(self, message: str) -> None:
        super().show_message(message, color=theme.RED, background=theme.RED_SF)


def _qcolor(hex_color: str, alpha: int) -> QColor:
    c = QColor(hex_color)
    c.setAlpha(alpha)
    return c


def _band_brush(hex_color: str, alpha: int):
    """Translucent fill for an RR band, colour taken from the theme palette."""
    return pg.mkBrush(_qcolor(hex_color, alpha))


_BAND_BRUSHES: dict = {
    code: _band_brush(theme.STRIP[code], theme.BAND_ALPHA[code])
    for code in (0, 1, 2)
}
# Neutral intervals (no baseline / not classified): barely-visible tint so the
# per-beat segmentation is still perceptible inside the plot.
_NEUTRAL_BRUSH = _band_brush(theme.MUTED, 14)
# Faint vertical edge drawn at every RR boundary, so segments are visible even
# when several adjacent intervals share the same colour.
_BAND_EDGE_PEN = pg.mkPen(_qcolor(theme.MUTED, 60), width=1)


class EcgPlotWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._n = config.DISPLAY_WINDOW_S * config.SAMPLING_RATE
        self._buf = np.zeros(self._n)

        self._plot = pg.PlotWidget()
        self._plot.setYRange(-0.8, 1.5)
        self._plot.setXRange(0, self._n)
        self._plot.hideAxis('bottom')
        # Il segnale è ADC normalizzato in [-1, 1], non millivolt calibrati:
        # l'AD8232 non fornisce un'uscita in mV calibrata. Unità arbitrarie.
        self._plot.setLabel('left', 'a.u.', color=theme.MUTED)
        _plot_item = self._plot.getPlotItem()
        _plot_item.showGrid(x=False, y=True, alpha=0.2)
        # Performance: draw only the points currently in view. NO downsampling —
        # it would alter the ECG morphology at different zoom levels (the trace
        # would visibly change as you zoom). Smoothness is kept instead by
        # clipToView plus a zoom-out limit (see show_static), which bounds the
        # number of points drawn at once even on a low-power CPU (Raspberry Pi).
        _plot_item.setClipToView(True)
        self._curve = self._plot.plot(self._buf, pen=pg.mkPen(theme.TRACE, width=1.5))
        self._rr_regions: list = []
        self._static_mode: bool = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._plot)

    def show_static(self, samples: np.ndarray) -> None:
        """Display a full static recording (replaces rolling buffer).

        Shows a readable time window (config.ARCHIVE_WINDOW_S) instead of
        cramming the whole recording into the width; the user pans horizontally
        to see the rest. The Y range is fitted to the waveform so it fills the
        plot vertically."""
        self._static_mode = True
        self.clear_rr_bands()
        self._curve.setData(samples)
        n = len(samples)
        if n == 0:
            return
        vb = self._plot.getViewBox()
        ymin, ymax = float(np.min(samples)), float(np.max(samples))
        pad = (ymax - ymin) * 0.1 or 0.5
        # Fixed time window — no zoom (better on a small touchscreen): you just
        # scroll horizontally. Locking maxXRange == minXRange == window pins the
        # visible span, so wheel/pinch zoom can't change it; only horizontal pan
        # moves it. The span stays constant -> a constant, clinical-paper-like
        # time scale, and the point count on screen is always bounded (smooth).
        window = min(n, config.ARCHIVE_WINDOW_S * config.SAMPLING_RATE)
        vb.setLimits(
            xMin=0, xMax=n, maxXRange=window, minXRange=window,
            yMin=ymin - pad, yMax=ymax + pad,
        )
        # Pan only horizontally; the amplitude scale stays fixed.
        vb.setMouseEnabled(x=True, y=False)
        self._plot.setXRange(0, window, padding=0)
        self._plot.setYRange(ymin - pad, ymax + pad, padding=0)

    def add_rr_bands(self, boundaries: list[int], colormap: np.ndarray) -> None:
        """Paint one translucent vertical band per RR interval *behind* the ECG
        trace, so the coloured segments live inside the plot and pan/zoom
        together with the signal.

        Coloured codes (0/1/2) get their status tint; neutral intervals get a
        barely-visible tint plus a faint edge, so the per-beat segmentation is
        still visible. Tolerant of a small length mismatch between the saved
        colormap and the RR intervals re-extracted from the (quantised) EDF:
        the overlapping portion is rendered."""
        self.clear_rr_bands()
        n = min(len(colormap), max(0, len(boundaries) - 1))
        # Coalesce consecutive intervals with the same code into ONE region:
        # a long run of GREEN becomes a single graphics item instead of dozens,
        # which keeps redraw cheap during pan/zoom.
        i = 0
        while i < n:
            code = int(colormap[i])
            j = i + 1
            while j < n and int(colormap[j]) == code:
                j += 1
            brush = _BAND_BRUSHES.get(code, _NEUTRAL_BRUSH)
            region = pg.LinearRegionItem(
                values=[boundaries[i], boundaries[j]],
                brush=brush,
                movable=False,
                pen=_BAND_EDGE_PEN,
            )
            region.setZValue(-10)
            self._plot.addItem(region)
            self._rr_regions.append(region)
            i = j

    def clear_rr_bands(self) -> None:
        for region in self._rr_regions:
            self._plot.removeItem(region)
        self._rr_regions.clear()

    def append_samples(self, samples: np.ndarray) -> None:
        if self._static_mode:
            return
        n = len(samples)
        if n == 0:
            return
        if n >= self._n:
            # Blocco più lungo della finestra visibile: tenerne solo la coda.
            # Senza questo, l'assegnazione sotto solleva ValueError. Oggi non
            # accade (al più 2000 campioni contro 2500 di finestra), ma solo per
            # coincidenza fra maxsize della coda e DISPLAY_WINDOW_S.
            self._buf[:] = samples[-self._n:]
        else:
            self._buf = np.roll(self._buf, -n)
            self._buf[-n:] = samples
        self._curve.setData(self._buf)

    def clear(self) -> None:
        self._buf[:] = 0.0
        self._curve.setData(self._buf)

    def auto_range(self) -> None:
        """Programmatic equivalent of pressing 'A' in pyqtgraph: auto-fit the
        view to the data. Called at the start of a live recording so the plot
        scales to the signal automatically (no manual 'A' each time)."""
        self._plot.getPlotItem().enableAutoRange()
