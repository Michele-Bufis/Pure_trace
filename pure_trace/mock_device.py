"""Protocol-compatible Arduino/AD8232 mock used by ``DEBUG=1``.

The acquisition code deliberately consumes this through ``readline()`` just
like a pyserial connection.  This keeps the serial parser, buffering, DSP and
UI on the same path used by the real device.
"""

import math
import time


class MockSerialDevice:
    """A small subset of :class:`serial.Serial` that emits firmware lines.

    It sends a stable, synthetic single-lead ECG at 500 Hz and periodically
    reports electrodes connected (``L,0``), matching the Arduino protocol.
    ``realtime=False`` is useful only for fast unit tests.
    """

    def __init__(self, *, sample_rate: int = 500, realtime: bool = True):
        self.sample_rate = sample_rate
        self.realtime = realtime
        self._sequence = 0
        self._sample = 0
        self._closed = False
        self._next_lod_sample = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    def close(self) -> None:
        self._closed = True

    def readline(self) -> bytes:
        if self._closed:
            return b""
        if self.realtime:
            time.sleep(1.0 / self.sample_rate)

        # The firmware sends lead-off status roughly twice per second.  Doing
        # this before the sample gives the UI an immediate connected state.
        if self._sample >= self._next_lod_sample:
            self._next_lod_sample = self._sample + self.sample_rate // 2
            return b"L,0\n"

        value = self._ecg_adc_value(self._sample / self.sample_rate)
        line = f"D,{self._sequence},{value}\n".encode("ascii")
        self._sequence = (self._sequence + 1) & 0xFF
        self._sample += 1
        return line

    @staticmethod
    def _ecg_adc_value(t: float) -> int:
        """Return a plausible AD8232 ADC sample with a 72 bpm rhythm."""
        phase = (t % (60.0 / 72.0)) / (60.0 / 72.0)

        def wave(center: float, width: float, amplitude: float) -> float:
            distance = min(abs(phase - center), 1.0 - abs(phase - center))
            return amplitude * math.exp(-0.5 * (distance / width) ** 2)

        # P-QRS-T morphology plus very small baseline wander and mains residue.
        ecg = (
            wave(0.18, 0.025, 35.0)
            - wave(0.36, 0.010, 55.0)
            + wave(0.40, 0.012, 330.0)
            - wave(0.44, 0.014, 80.0)
            + wave(0.68, 0.055, 75.0)
            + 10.0 * math.sin(2.0 * math.pi * 0.25 * t)
            + 2.0 * math.sin(2.0 * math.pi * 50.0 * t)
        )
        return max(0, min(1023, round(512.0 + ecg)))
