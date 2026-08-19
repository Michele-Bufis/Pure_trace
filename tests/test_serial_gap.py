"""Test della ricostruzione dei campioni seriali persi (interpolate_gap).

Un campione seriale perso, se non ricostruito, fa slittare in silenzio la base
dei tempi (timestamp = indice/fs) usata dall'analisi HRV. interpolate_gap
riempie i buchi piccoli per interpolazione lineare, mantenendo l'allineamento.
"""
import numpy as np
import threading

from pure_trace.signal_processing import CircularBuffer, interpolate_gap
from pure_trace.ui.acquisition_screen import _SerialThread


def test_no_gap_returns_empty():
    assert interpolate_gap(0.0, 1.0, 0) == []
    assert interpolate_gap(0.0, 1.0, -3) == []


def test_single_missing_sample_is_midpoint():
    assert interpolate_gap(0.0, 1.0, 1) == [0.5]


def test_two_missing_samples_evenly_spaced():
    assert interpolate_gap(0.0, 3.0, 2) == [1.0, 2.0]


def test_descending_segment():
    np.testing.assert_allclose(interpolate_gap(1.0, 0.0, 3), [0.75, 0.5, 0.25])


def test_count_matches_gap():
    for gap in range(1, 6):
        assert len(interpolate_gap(-1.0, 1.0, gap)) == gap


def test_values_stay_within_endpoints():
    out = interpolate_gap(-0.4, 0.9, 4)
    assert all(-0.4 < v < 0.9 for v in out)
    # monotòni crescenti tra gli estremi
    assert out == sorted(out)


def test_large_serial_gap_marks_recording_not_scorable():
    """Un buco non interpolato non deve essere trattato come tempo inesistente."""
    thread = _SerialThread(CircularBuffer(100), threading.Event(),
                           threading.Event(), None, 115200)
    thread.set_recording(True)
    thread._ingest(0, 0.0)
    thread._ingest(thread._MAX_GAP_FILL + 2, 1.0)

    assert thread.has_unfilled_gap is True
    assert thread.dropped == thread._MAX_GAP_FILL + 1
