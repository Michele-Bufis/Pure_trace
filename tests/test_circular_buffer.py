import threading
import numpy as np
from pure_trace.signal_processing import CircularBuffer


def test_write_and_read_basic():
    buf = CircularBuffer(maxlen=10)
    buf.write(np.array([1.0, 2.0, 3.0]))
    result = buf.read(3)
    assert list(result) == [1.0, 2.0, 3.0]


def test_read_returns_only_available_when_less_than_requested():
    buf = CircularBuffer(maxlen=10)
    buf.write(np.array([1.0, 2.0]))
    result = buf.read(5)
    assert len(result) == 2


def test_read_empty_returns_empty():
    buf = CircularBuffer(maxlen=10)
    result = buf.read(3)
    assert len(result) == 0


def test_overflow_drops_oldest():
    buf = CircularBuffer(maxlen=4)
    buf.write(np.array([1.0, 2.0, 3.0, 4.0, 5.0]))
    result = buf.read(4)
    assert list(result) == [2.0, 3.0, 4.0, 5.0]


def test_dropped_samples_are_counted_not_silent():
    """L'overflow scarta i campioni più vecchi. Prima accadeva in silenzio: il
    consumatore contava solo quelli letti e la base dei tempi degli RR scivolava."""
    buf = CircularBuffer(maxlen=10)
    buf.write(np.arange(25.0))
    assert buf.take_dropped() == 15
    assert buf.take_dropped() == 0        # il contatore si azzera dopo la lettura
    data = buf.read(100)
    assert len(data) == 10
    assert data[0] == 15.0                # restano gli ultimi 10


def test_no_drops_when_within_capacity():
    buf = CircularBuffer(maxlen=10)
    buf.write(np.arange(6.0))
    buf.write(np.arange(4.0))
    assert buf.take_dropped() == 0


def test_clear_resets_dropped_counter():
    buf = CircularBuffer(maxlen=4)
    buf.write(np.arange(10.0))
    buf.clear()
    assert buf.take_dropped() == 0


def test_clear_empties_buffer():
    buf = CircularBuffer(maxlen=10)
    buf.write(np.array([1.0, 2.0, 3.0]))
    buf.clear()
    assert len(buf.read(10)) == 0


def test_thread_safety():
    buf = CircularBuffer(maxlen=10000)
    errors = []

    def writer():
        try:
            for _ in range(100):
                buf.write(np.ones(50))
        except Exception as e:
            errors.append(e)

    def reader():
        try:
            for _ in range(200):
                buf.read(10)
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=writer) for _ in range(3)]
    threads += [threading.Thread(target=reader) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
