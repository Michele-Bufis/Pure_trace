import numpy as np
from pure_trace import config
from pure_trace.signal_processing import CircularBuffer, DigitalFilter, RPeakDetector


def test_config_constants():
    assert config.SAMPLING_RATE == 500
    assert config.DURATION_LONG_S == 120
    assert config.DURATION_MIN_SCORED_S == 60
    assert config.DURATION_MAX_S == 900
    assert config.CIRCULAR_BUFFER_LEN == 60000
    assert config.UI_REFRESH_MS == 40


def test_baseline_config_constants():
    assert config.RR_MIN_S == 0.33
    assert config.RR_MAX_S == 2.0
    assert config.MIN_BASELINE_SESSIONS == 5
    assert config.CHI2_GREEN_P == 0.95
    assert config.CHI2_YELLOW_P == 0.99
    assert config.MAX_ARTIFACT_FRAC == 0.40


def test_data_dir_is_absolute_and_cwd_independent():
    """Avviata da systemd o da un'altra cartella, l'app scriveva profili e log
    in un posto diverso da quello dove li aveva creati."""
    assert config.DATA_DIR.is_absolute()
    assert config.PROFILES_DIR == config.DATA_DIR / "profiles"


def test_profile_manager_defaults_to_config_dir(tmp_path, monkeypatch):
    """Senza base_dir esplicito, ProfileManager deve usare la radice di config,
    non 'data/profiles' relativo alla directory di lavoro corrente."""
    from pure_trace.data_layer import ProfileManager
    monkeypatch.setattr(config, "PROFILES_DIR", tmp_path / "profili")
    altrove = tmp_path / "altrove"
    altrove.mkdir()
    monkeypatch.chdir(altrove)          # cwd diversa dalla radice dei dati

    pm = ProfileManager()

    assert pm._base == tmp_path / "profili"
    assert (tmp_path / "profili").is_dir()
    assert not (altrove / "data").exists()   # niente scritture nella cwd


def test_pipeline_instantiation():
    buf = CircularBuffer(maxlen=1000)
    filt = DigitalFilter(fs=config.SAMPLING_RATE)
    det = RPeakDetector(fs=config.SAMPLING_RATE, refractory_ms=config.REFRACTORY_MS)
    assert buf is not None and filt is not None and det is not None


def test_full_pipeline_60bpm():
    """End-to-end: synthetic 60 bpm through CircularBuffer -> DigitalFilter -> RPeakDetector."""
    fs, duration = 500, 5
    n = fs * duration
    signal = np.zeros(n)
    rr = fs  # 60 bpm
    for i in range(rr // 2, n, rr):
        signal[i] = 1.0

    buf = CircularBuffer(maxlen=n)
    buf.write(signal)

    filt = DigitalFilter(fs=fs)
    det = RPeakDetector(fs=fs)
    chunk = buf.read(n)
    for i, s in enumerate(chunk):
        filtered = filt.process_sample(float(s))
        det.process(filtered, i / fs)

    hr = det.get_hr()
    assert 50 < hr < 70, f"Expected HR ~60 bpm, got {hr:.1f}"


def test_full_pipeline_80bpm():
    fs, duration = 500, 5
    n = fs * duration
    signal = np.zeros(n)
    rr = int(fs * 60 / 80)
    for i in range(rr // 2, n, rr):
        signal[i] = 1.0

    buf = CircularBuffer(maxlen=n)
    buf.write(signal)
    filt = DigitalFilter(fs=fs)
    det = RPeakDetector(fs=fs)
    chunk = buf.read(n)
    for i, s in enumerate(chunk):
        det.process(filt.process_sample(float(s)), i / fs)

    hr = det.get_hr()
    assert 70 < hr < 90, f"Expected HR ~80 bpm, got {hr:.1f}"
