import os
from pathlib import Path

# Radice dei dati (profili cifrati e log). Ancorata alla posizione del pacchetto,
# non alla directory di lavoro: avviata da systemd o da un'altra cartella, l'app
# scriveva profili e log in un posto diverso da quello dove li aveva creati.
# Sovrascrivibile con la variabile d'ambiente PURE_TRACE_DATA.
DATA_DIR = Path(os.environ.get(
    "PURE_TRACE_DATA", Path(__file__).resolve().parent.parent / "data"))
PROFILES_DIR = DATA_DIR / "profiles"

# None = rilevamento automatico della porta dell'Arduino (vedi serial_port.py).
# Impostare una stringa (es. "/dev/ttyUSB0" o "COM4") solo per forzarla.
SERIAL_PORT = None
SERIAL_BAUD = 115200
SERIAL_RETRY_S = 2.0  # attesa fra i tentativi di (ri)connessione
SAMPLING_RATE = 500  # Hz

NOTCH_FREQ = 50.0 #da valutare quando metteremo la batteria. Potenzailemnete può rimanere così
NOTCH_Q = 30.0
BANDPASS_LOW = 0.05 # da 0.5 a 0.05 si rischia che i tratti st siano molto storti
BANDPASS_HIGH = 40.0 #Anche questo da valutare con un acquisizione. Toccherebbe fa psd
BANDPASS_ORDER = 4

REFRACTORY_MS = 200
AMPLITUDE_WINDOW_S = 2
THRESHOLD_FRACTION = 0.6
HR_SMOOTHING_PEAKS = 8

# Secondi iniziali scartati prima di cercare i picchi R. Il passa-alto a 0.5 Hz
# parte da stato nullo mentre l'ingresso ha l'offset DC dell'AD8232: ne risulta
# un transitorio di ampiezza paragonabile a un'onda R che si esaurisce in ~3 s.
# Scartarlo evita battiti fantasma e un primo intervallo RR non fisiologico.
FILTER_WARMUP_S = 3.0

# Finestra entro cui cercare l'apice dell'onda R dopo il superamento della
# soglia. Copre il fronte di salita del QRS (~40 ms) e resta ben sotto il
# refrattario (200 ms), quindi non può agganciare il battito successivo.
APEX_SEARCH_S = 0.050

#----- Parametri Calcolo QRS -----
# Finestra di ricerca onset/offset QRS attorno al picco già agganciato
# all'apice. Copre QRS 80-120 ms con margine su entrambi i lati.
QRS_SEARCH_S = 0.100
# Soglia di pendenza relativa (rispetto al picco di derivata vicino al
# picco R) sotto la quale il segnale è considerato tornato isoelettrico.
QRS_SLOPE_RATIO = 0.05
# Range di plausibilità fisiologica: fuori da qui è quasi certamente un
# artefatto di rilevamento, non un vero QRS largo/stretto.
QRS_MIN_MS = 60.0
QRS_MAX_MS = 150.0
#-------

DURATION_LONG_S = 120
# Durata "libera": è l'operatore a fermare la registrazione. Il limite serve solo
# come rete di sicurezza (memoria, e una registrazione dimenticata in corso).
DURATION_MAX_S = 900          # 15 min
# Sotto i 60 s l'analisi HRV non produce metriche (vedi HrvAnalyser.analyse).
DURATION_MIN_SCORED_S = 60
CIRCULAR_BUFFER_LEN = SAMPLING_RATE * DURATION_LONG_S  # 60000

UI_REFRESH_MS = 40   # ~25 fps
DISPLAY_WINDOW_S = 5  # seconds of ECG visible on screen at once (live)
ARCHIVE_WINDOW_S = 8  # fixed seconds visible when reviewing a saved recording (no zoom, scroll only)

# --- Filtro artefatti RR / qualità segnale ---
RR_MIN_S = 0.33              # 180 bpm
RR_MAX_S = 2.0               # 30 bpm
ARTIFACT_REL_THRESH = 0.20   # scarto max dalla mediana locale
# Ampiezza (dispari) della finestra mediana locale. Una mediana regge finché gli
# artefatti sono meno della metà della finestra: con 5 bastavano 3 battiti
# anomali consecutivi perché la mediana DIVENTASSE l'artefatto, che veniva così
# accettato mentre i battiti buoni venivano scartati. Con 11 si tollerano fino a
# 5 artefatti consecutivi, senza penalizzare le variazioni di frequenza (la
# mediana locale segue comunque la deriva).
ARTIFACT_WINDOW = 11
MIN_VALID_BEATS = 30         # battiti validi minimi per scorare una sessione lunga
MAX_ARTIFACT_FRAC = 0.40     # frazione artefatti oltre cui la qualità è insufficiente

# --- Baseline / Mahalanobis ---
# Soglie calibrate via Hotelling T² (non χ²): media e covarianza sono STIMATE dal
# pool, non note. Con la χ² il tasso di RED falsi era ~20% a n=5 invece dell'1%
# atteso. Serve n >= n_feature + 1 perché la F abbia gradi di libertà validi.
MIN_BASELINE_SESSIONS = 5    # sessioni lunghe minime prima di scorare
COV_RIDGE_EPS = 1e-9         # ridge per garantire l'invertibilità
FEATURE_POOL_CAP = 100       # cap FIFO del pool di vettori feature
BASELINE_INCLUDE_RED = True  # le sessioni RED entrano comunque nella baseline
CHI2_GREEN_P = 0.95          # quantile soglia GREEN/YELLOW
CHI2_YELLOW_P = 0.99         # quantile soglia YELLOW/RED

