import collections
import threading
from typing import List, Optional
import numpy as np
from scipy.signal import butter, sosfilt, iirnotch, tf2sos

from pure_trace import config


def interpolate_gap(prev: float, curr: float, gap: int) -> List[float]:
    """Ricostruisce ``gap`` campioni persi tra ``prev`` (escluso) e ``curr``
    (escluso) per interpolazione lineare.

    Serve quando un campione seriale va perso: senza ricostruirlo la base dei
    tempi usata dall'analisi HRV (timestamp = indice/fs) slitterebbe in
    silenzio, falsando gli intervalli RR. Riempire il buco con campioni
    interpolati mantiene l'allineamento temporale. Restituisce una lista vuota
    se ``gap <= 0``.
    """
    if gap <= 0:
        return []
    return [prev + (curr - prev) * k / (gap + 1) for k in range(1, gap + 1)]


class CircularBuffer:
    """Coda FIFO limitata fra il thread seriale (produttore) e quello di
    elaborazione (consumatore).

    In overflow la deque scarta i campioni più vecchi. Prima accadeva in
    silenzio: il consumatore contava solo i campioni *letti*, quindi la base dei
    tempi (indice/fs) da cui si ricavano gli intervalli RR scivolava senza che
    nessuno se ne accorgesse. Ora gli scarti sono contati ed esposti, così il
    consumatore può riallineare l'indice e segnalarli."""

    def __init__(self, maxlen: int):
        self._maxlen = maxlen
        self._buf: collections.deque = collections.deque(maxlen=maxlen)
        self._lock = threading.Lock()
        self._dropped = 0

    def write(self, samples: np.ndarray) -> None:
        with self._lock:
            values = samples.tolist()
            overflow = len(self._buf) + len(values) - self._maxlen
            if overflow > 0:
                self._dropped += overflow
            self._buf.extend(values)

    def read(self, n: int) -> np.ndarray:
        with self._lock:
            available = min(n, len(self._buf))
            return np.array([self._buf.popleft() for _ in range(available)])

    def take_dropped(self) -> int:
        """Numero di campioni scartati per overflow dall'ultima chiamata."""
        with self._lock:
            dropped, self._dropped = self._dropped, 0
            return dropped

    def clear(self) -> None:
        with self._lock:
            self._buf.clear()
            self._dropped = 0


class DigitalFilter:
    def __init__(self, fs: int = config.SAMPLING_RATE):
        b, a = iirnotch(config.NOTCH_FREQ, Q=config.NOTCH_Q, fs=fs)
        sos_notch = tf2sos(b, a)
        sos_bp = butter(config.BANDPASS_ORDER,
                        [config.BANDPASS_LOW, config.BANDPASS_HIGH],
                        btype='bandpass', fs=fs, output='sos')
        self._sos = np.vstack([sos_notch, sos_bp])
        self._zi = np.zeros((len(self._sos), 2))

    def process_sample(self, sample: float) -> float:
        out, self._zi = sosfilt(self._sos, np.array([sample]), zi=self._zi)
        return float(out[0])

    def process_array(self, samples: np.ndarray) -> np.ndarray:
        """Filtra un blocco in una sola chiamata a ``sosfilt``, avanzando lo
        stato esattamente come farebbero N ``process_sample`` consecutive.

        Per l'analisi offline questo è ~2000x più veloce del ciclo campione per
        campione, che pagava l'overhead di scipy su array da un elemento."""
        x = np.asarray(samples, dtype=np.float64)
        if x.size == 0:
            return np.array([], dtype=np.float64)
        out, self._zi = sosfilt(self._sos, x, zi=self._zi)
        return out


class RPeakDetector:
    def __init__(self, fs: int = config.SAMPLING_RATE,
                 refractory_ms: int = config.REFRACTORY_MS):
        self._fs = fs
        self._refractory_samples = int(fs * refractory_ms / 1000)
        self._window_size = fs * config.AMPLITUDE_WINDOW_S
        # Deque monotona decrescente di (indice, valore): la testa è sempre il
        # massimo della finestra corrente. Sostituisce ``max(buf)``, che era
        # O(finestra) per campione (1000 confronti a ogni campione a 500 Hz).
        self._maxq: collections.deque = collections.deque()
        self._threshold_fraction = config.THRESHOLD_FRACTION
        self._last_peak_sample = -self._refractory_samples
        self._sample_index = 0
        self._rr_intervals: collections.deque = collections.deque(
            maxlen=config.HR_SMOOTHING_PEAKS)
        self._last_peak_time: Optional[float] = None

    def _window_max(self, sample: float) -> float:
        idx = self._sample_index
        while self._maxq and self._maxq[-1][1] <= sample:
            self._maxq.pop()
        self._maxq.append((idx, sample))
        while self._maxq[0][0] <= idx - self._window_size:
            self._maxq.popleft()
        return self._maxq[0][1]

    def step(self, sample: float) -> bool:
        """Consuma un campione filtrato; True se è un picco R rilevato."""
        self._sample_index += 1
        peak_val = self._window_max(sample)
        if self._sample_index < self._window_size // 4:
            return False
        if peak_val <= 0:
            return False
        threshold = self._threshold_fraction * peak_val
        samples_since_last = self._sample_index - self._last_peak_sample
        if sample >= threshold and samples_since_last >= self._refractory_samples:
            self._last_peak_sample = self._sample_index
            return True
        return False

    def process(self, sample: float, timestamp: float) -> Optional[float]:
        if not self.step(sample):
            return None
        rr: Optional[float] = None
        if self._last_peak_time is not None:
            rr = timestamp - self._last_peak_time
            self._rr_intervals.append(rr)
        self._last_peak_time = timestamp
        return rr

    def get_hr(self) -> float:
        if not self._rr_intervals:
            return 0.0
        return 60.0 / float(np.mean(list(self._rr_intervals)))

    def get_rr_intervals(self) -> np.ndarray:
        return np.array(list(self._rr_intervals))

    def reset(self) -> None:
        self._maxq.clear()
        self._sample_index = 0
        self._last_peak_sample = -self._refractory_samples
        self._rr_intervals.clear()
        self._last_peak_time = None
