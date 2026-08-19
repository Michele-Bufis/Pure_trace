"""
pure_trace/analysis_engine.py
HRV analysis engine — Phase 3, Task 1.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Optional

import numpy as np
from scipy.stats import f as f_dist

from pure_trace import config, secure_store
from pure_trace.signal_processing import DigitalFilter, RPeakDetector

if TYPE_CHECKING:  # il motore di analisi non deve dipendere da pyedflib
    from pure_trace.data_layer import EncryptionManager, Profile

# Colormap uint8 codes
_GREEN = np.uint8(0)
_YELLOW = np.uint8(1)
_RED = np.uint8(2)
_NEUTRAL = np.uint8(255)


def _snap_to_apex(filtered: np.ndarray, crossings: list[int], fs: int) -> list[int]:
    """Sposta ogni rilevamento sull'apice locale dell'onda R.

    ``RPeakDetector`` scatta sul PRIMO campione che supera la soglia, non
    sull'apice. Con ampiezza R costante è un ritardo sistematico che si elide
    nella differenza fra RR; ma l'ampiezza dell'onda R è modulata dal respiro, e
    allora il ritardo varia da battito a battito e finisce dentro RMSSD, che è
    proprio una misura di variazione fra battiti successivi. Misurato con una
    modulazione del 30%: jitter 9.5 ms → 1.6 ms, errore su RMSSD +5.3% → +1.0%.

    La ricerca è limitata a ``APEX_SEARCH_S`` (il fronte di salita dell'onda R),
    quindi non può saltare a un battito successivo né superare il refrattario."""
    window = int(config.APEX_SEARCH_S * fs)
    n = len(filtered)
    return [int(i + np.argmax(filtered[i:min(i + window + 1, n)])) for i in crossings]

#----Calcolo QRS ---
#----Sostituzione di def detect_rpeak con queste 3 funzioni
#def detect_rpeak_indices(raw: np.ndarray, fs: int = config.SAMPLING_RATE) -> np.ndarray:
#    """Indici (in campioni, riferiti a ``raw``) dei picchi R rilevati.

#     Il segnale è filtrato in un'unica chiamata batch, poi i primi
#     ``config.FILTER_WARMUP_S`` secondi vengono scartati: contengono il
#     transitorio di assestamento del passa-alto, che ha ampiezza paragonabile a
#     un'onda R e produrrebbe battiti fantasma. Ogni rilevamento viene infine
#     agganciato all'apice dell'onda R (vedi ``_snap_to_apex``)."""
 #   raw = np.asarray(raw)
  #  filtered = DigitalFilter(fs=fs).process_array(raw)
   # skip = min(int(config.FILTER_WARMUP_S * fs), len(filtered))
    #det = RPeakDetector(fs=fs, refractory_ms=config.REFRACTORY_MS)
    #crossings = [i for i in range(skip, len(filtered))
     #            if det.step(float(filtered[i]))]
    #return np.array(_snap_to_apex(filtered, crossings, fs), dtype=np.int64)
def filter_signal(raw: np.ndarray, fs: int = config.SAMPLING_RATE) -> np.ndarray:
    """Applica DigitalFilter (notch + bandpass) all'intero array in una sola
    chiamata batch. Fattorizzata fuori da ``detect_rpeak_indices`` perché
    ``qrs_duration_ms`` ha bisogno dello stesso segnale filtrato usato per il
    rilevamento dei picchi: senza questa funzione, calcolarlo separatamente
    avrebbe richiesto di filtrare l'intera registrazione due volte."""
    return DigitalFilter(fs=fs).process_array(np.asarray(raw))


def detect_rpeaks(filtered: np.ndarray, fs: int = config.SAMPLING_RATE) -> np.ndarray:
    """Rileva picchi R su un segnale GIA' filtrato.

    I primi ``config.FILTER_WARMUP_S`` secondi vengono scartati: contengono il
    transitorio di assestamento del passa-alto, che ha ampiezza paragonabile a
    un'onda R e produrrebbe battiti fantasma. Ogni rilevamento viene infine
    agganciato all'apice dell'onda R (vedi ``_snap_to_apex``)."""
    skip = min(int(config.FILTER_WARMUP_S * fs), len(filtered))
    det = RPeakDetector(fs=fs, refractory_ms=config.REFRACTORY_MS)
    crossings = [i for i in range(skip, len(filtered))
                 if det.step(float(filtered[i]))]
    return np.array(_snap_to_apex(filtered, crossings, fs), dtype=np.int64)


def detect_rpeak_indices(raw: np.ndarray, fs: int = config.SAMPLING_RATE) -> np.ndarray:
    """Indici (in campioni, riferiti a ``raw``) dei picchi R rilevati.

    Wrapper retro-compatibile: filtra e rileva in un colpo solo. Chi ha
    bisogno anche del segnale filtrato (es. ``qrs_duration_ms``) chiami
    ``filter_signal`` + ``detect_rpeaks`` separatamente, per evitare di
    filtrare due volte lo stesso array."""
    return detect_rpeaks(filter_signal(raw, fs), fs)

# aggiunta di due funzioni per caclolo durata QRS

def qrs_duration_ms(filtered: np.ndarray, r_idx: int,
                    fs: int = config.SAMPLING_RATE) -> Optional[float]:
    """Durata QRS in ms attorno a un picco R già agganciato all'apice.

    Cerca a sinistra/destra del picco il punto in cui la pendenza del segnale
    torna vicina a zero (ritorno alla linea isoelettrica). None se il segmento
    è troppo vicino ai bordi del segnale, la finestra è priva di pendenza
    significativa, o il valore stimato esce dal range fisiologicamente
    plausibile — in quel caso è quasi certamente un artefatto di rilevamento,
    non un vero QRS, e va escluso esattamente come un RR fuori range viene
    escluso da ``clean_rr_mask``."""
    win = int(config.QRS_SEARCH_S * fs)
    start, end = max(0, r_idx - win), min(len(filtered), r_idx + win)
    if end - start < 4:
        return None
    seg = filtered[start:end]
    r_local = r_idx - start
    deriv = np.abs(np.gradient(seg))
    guard = max(1, int(0.010 * fs))  # ~10 ms: raggio della zona di picco, stessa ampiezza usata per calibrare thr, aggiunta per modifica qrs
                        #cambio di zone
    zone_lo = max(0, r_local - guard)
    zone_hi = min(len(deriv), r_local + guard)
    zone = deriv[zone_lo:zone_hi]
   # zone = deriv[max(0, r_local - int(0.02 * fs)):
                # min(len(deriv), r_local + int(0.02 * fs))]
    if zone.size == 0 or zone.max() <= 0:
        return None
    thr = config.QRS_SLOPE_RATIO * zone.max()
    # La ricerca parte FUORI dalla zona di picco (dove la derivata è vicina a
    # zero per definizione, essendo r_local un massimo locale), non dal picco
    # stesso: altrimenti il primo campione controllato soddisfa già la
    # condizione di soglia e onset/offset collassano su r_local, dando
    # sempre durata 0.
    onset = next((i for i in range(zone_lo, 0, -1) if deriv[i] < thr), zone_lo)
    offset = next((i for i in range(zone_hi, len(deriv)) if deriv[i] < thr), zone_hi)

   # onset = next((i for i in range(r_local, 0, -1) if deriv[i] < thr), r_local)
   # offset = next((i for i in range(r_local, len(deriv)) if deriv[i] < thr), r_local)

    dur_ms = (offset - onset) * 1000.0 / fs
    return dur_ms if config.QRS_MIN_MS <= dur_ms <= config.QRS_MAX_MS else None


def extract_qrs_durations(filtered: np.ndarray, peaks: np.ndarray,
                          fs: int = config.SAMPLING_RATE) -> np.ndarray:
    """Durata QRS per ciascun picco, stesso ordine posizionale di ``peaks``.
    ``np.nan`` dove non stimabile (bordo segnale o fuori range fisiologico)."""
    out = np.full(len(peaks), np.nan, dtype=float)
    for i, p in enumerate(peaks):
        d = qrs_duration_ms(filtered, int(p), fs)
        if d is not None:
            out[i] = d
    return out

def extract_rr_intervals(raw: np.ndarray, fs: int = config.SAMPLING_RATE) -> np.ndarray:
    """Apply DigitalFilter + RPeakDetector to raw ECG; return RR intervals in seconds."""
    peaks = detect_rpeak_indices(raw, fs)
    if len(peaks) < 2:
        return np.array([], dtype=np.float64)
    return np.diff(peaks).astype(np.float64) / fs


def clean_rr_mask(rr: np.ndarray) -> np.ndarray:
    """Maschera booleana dei battiti RR validi (stessa lunghezza di rr).

    Un intervallo è valido se è nel range fisiologico [RR_MIN_S, RR_MAX_S] e
    non si discosta oltre ARTIFACT_REL_THRESH dalla mediana di una finestra
    locale di ARTIFACT_WINDOW intervalli (rimuove battiti persi/doppi)."""
    rr = np.asarray(rr, dtype=float)
    n = len(rr)
    mask = np.zeros(n, dtype=bool)
    if n == 0:
        return mask
    in_range = (rr >= config.RR_MIN_S) & (rr <= config.RR_MAX_S)
    if not in_range.any():
        return mask

    half = config.ARTIFACT_WINDOW // 2
    for i in range(n):
        if not in_range[i]:
            continue
        lo, hi = max(0, i - half), min(n, i + half + 1)
        # L'intervallo è escluso dalla propria mediana di riferimento: un
        # artefatto non deve poter sostenere se stesso.
        neighbours = np.concatenate([rr[lo:i], rr[i + 1:hi]])
        local = neighbours[(neighbours >= config.RR_MIN_S)
                           & (neighbours <= config.RR_MAX_S)]
        if len(local) == 0:
            mask[i] = True
            continue
        med = float(np.median(local))
        if med <= 0:
            mask[i] = True
            continue
        mask[i] = abs(rr[i] - med) / med <= config.ARTIFACT_REL_THRESH
    return mask


def quality_ok(valid_beats: int, artifact_fraction: float) -> bool:
    """True se la sessione ha qualità sufficiente per lo scoring."""
    return (valid_beats >= config.MIN_VALID_BEATS
            and artifact_fraction <= config.MAX_ARTIFACT_FRAC)


_FEATURE_NAMES = ["mean_hr", "sdnn", "rmssd", "pnn50","qrs_duration"]
# v2 aggiunge ``session_ids``: senza, cancellare una sessione dall'archivio non
# ne rimuoveva il vettore dalla baseline, e il modello divergeva da ciò che
# l'utente vedeva. Le baseline v1 si caricano ancora, con id ignoti.
_BASELINE_SCHEMA = "mahalanobis-v3"
_BASELINE_SCHEMA_LEGACY = "mahalanobis-v2"

# Perché una sessione non è stata valutata. NEUTRAL da solo non basta: nasconde
# tre situazioni diverse, con tre azioni diverse per chi usa il dispositivo.
NEUTRAL_SHORT_SESSION = "short_session"      # < 60 s: ripeti più lunga
NEUTRAL_LOW_QUALITY = "low_quality"          # troppi artefatti / pochi battiti
NEUTRAL_BASELINE_BUILDING = "baseline_building"  # baseline ancora incompleta
NEUTRAL_BASELINE_ERROR = "baseline_error"    # baseline.json illeggibile


def features_to_vector(features: dict):
    """Converte il dict feature in vettore [mean_hr, sdnn, rmssd, pnn50].
    Ritorna None se una qualsiasi feature è assente (sessione breve)."""
    mean_rr = features.get("mean_rr")
    sdnn = features.get("sdnn")
    rmssd = features.get("rmssd")
    pnn50 = features.get("pnn50")
    #aggiunta qrs_duration
    qrs = features.get("qrs_duration")
    if any(v is None for v in (mean_rr, sdnn, rmssd, pnn50,qrs)):
        return None
    if mean_rr <= 0:                 # guardia contro la divisione per zero
        return None
    # ``sdnn``/``rmssd``/``pnn50/ qrs`` possono legittimamente valere 0.0: un test di
    # verità (``if not sdnn``) li scarterebbe come mancanti.
    return np.array([60.0 / mean_rr, sdnn, rmssd, pnn50, qrs], dtype=float)


class BaselineModel:
    """Modello baseline personale nello spazio feature, scorato via Mahalanobis."""

    def __init__(self, pool, session_ids=None) -> None:
        self._pool = [np.asarray(v, dtype=float) for v in pool]
        # Un id per vettore; None per le baseline legacy, che non sappiamo a
        # quale sessione appartengano e quindi non possiamo rimuovere.
        if session_ids is None:
            session_ids = [None] * len(self._pool)
        self._session_ids = list(session_ids)[:len(self._pool)]
        self._session_ids += [None] * (len(self._pool) - len(self._session_ids))

    @property
    def n(self) -> int:
        return len(self._pool)

    def session_ids_as_list(self):
        return list(self._session_ids)

    def remove_session(self, session_id: str) -> bool:
        """Rimuove il vettore della sessione indicata. True se qualcosa è uscito."""
        keep = [i for i, sid in enumerate(self._session_ids) if sid != session_id]
        if len(keep) == len(self._pool):
            return False
        self._pool = [self._pool[i] for i in keep]
        self._session_ids = [self._session_ids[i] for i in keep]
        return True

    def ready(self) -> bool:
        return self.n >= config.MIN_BASELINE_SESSIONS

    def _mean_cov(self):
        X = np.vstack(self._pool)
        d = X.shape[1]
        mu = X.mean(axis=0)
        if self.n > 1:
            cov = np.atleast_2d(np.cov(X, rowvar=False))
        else:
            cov = np.eye(d)
        cov = cov + config.COV_RIDGE_EPS * np.eye(d)
        return mu, cov

    def mahalanobis2(self, x) -> float:
        mu, cov = self._mean_cov()
        delta = np.asarray(x, dtype=float) - mu
        return float(delta @ np.linalg.solve(cov, delta))

    def _thresholds(self, d: int):
        """Soglie su D² calibrate come Hotelling T² a due campioni (uno solo nuovo).

        D² usa media e covarianza STIMATE su n sessioni, quindi NON è distribuita
        come una χ²: usarla come tale gonfiava i RED falsi (~20% a n=5 invece
        dell'1% atteso). Sotto normalità, D²·k ~ F(d, n−d) con
        k = (n−d)·n / (d·(n+1)·(n−1)). Ritorna None se n−d < 1 (la F non ha
        gradi di libertà validi: il pool è troppo piccolo per calibrare)."""
        n = self.n
        if n - d < 1:
            return None
        k = (n - d) * n / (d * (n + 1.0) * (n - 1.0))
        green_t = float(f_dist.ppf(config.CHI2_GREEN_P, d, n - d)) / k
        yellow_t = float(f_dist.ppf(config.CHI2_YELLOW_P, d, n - d)) / k
        return green_t, yellow_t

    def feature_z(self, x) -> np.ndarray:
        X = np.vstack(self._pool)
        mu = X.mean(axis=0)
        sd = X.std(axis=0, ddof=1) if self.n > 1 else np.ones(X.shape[1])
        sd = np.where(sd > 0, sd, 1.0)
        return (np.asarray(x, dtype=float) - mu) / sd

    def classify(self, x):
        if not self.ready():
            return ("NEUTRAL", float("nan"))
        d = len(np.asarray(x))
        thresholds = self._thresholds(d)
        if thresholds is None:
            return ("NEUTRAL", float("nan"))
        d2 = self.mahalanobis2(x)
        green_t, yellow_t = thresholds
        if d2 <= green_t:
            return ("GREEN", d2)
        if d2 <= yellow_t:
            return ("YELLOW", d2)
        return ("RED", d2)

    def add(self, x, session_id: Optional[str] = None) -> None:
        self._pool.append(np.asarray(x, dtype=float))
        self._session_ids.append(session_id)
        cap = config.FEATURE_POOL_CAP
        if cap and len(self._pool) > cap:
            self._pool = self._pool[-cap:]
            self._session_ids = self._session_ids[-cap:]

    def pool_as_list(self):
        return [v.tolist() for v in self._pool]


class HrvAnalyser:
    """Offline HRV analyser with per-profile baseline tracking."""

    def __init__(self, profile: Profile, enc: EncryptionManager,
                 fs: int = config.SAMPLING_RATE) -> None:
        self._profile = profile
        self._enc = enc
        self._fs = fs
        # True se baseline.json esiste ma non è decifrabile. In quel caso non si
        # scora e soprattutto non si riscrive il file: lo storico è recuperabile.
        self.baseline_error = False
        self._model = self._load_model()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyse(
        self, raw_samples: np.ndarray, session_id: Optional[str] = None
    ) -> tuple[str, np.ndarray, dict]:
        """Analyse a raw ECG array.

        ``session_id`` (lo stem del file di sessione, es. ``20260710_120000``)
        lega il vettore feature alla sessione, così cancellarla dall'archivio lo
        rimuove anche dalla baseline.

        Returns
        -------
        status : 'GREEN' | 'YELLOW' | 'RED' | 'NEUTRAL'
        colormap_uint8 : np.ndarray dtype=uint8, one entry per RR interval
        features : dict with mean_rr, sdnn, rmssd, pnn50 (float or None)
        """
        filtered = filter_signal(raw_samples, self._fs)
        peaks = detect_rpeaks(filtered, self._fs)
        rr = (np.diff(peaks).astype(np.float64) / self._fs
              if len(peaks) >= 2 else np.array([], dtype=np.float64))
        if len(rr) < 2:
            return ("NEUTRAL", np.array([], dtype=np.uint8), {
                "mean_rr": None, "sdnn": None, "rmssd": None, "pnn50": None,"qrs_duration": None,
                "status": "NEUTRAL", "mahalanobis_d2": None, "feature_z": None,
                "rr_peaks": [int(p) for p in peaks],
                "baseline_error": self.baseline_error,
                "neutral_reason": (NEUTRAL_BASELINE_ERROR if self.baseline_error
                                   else NEUTRAL_LOW_QUALITY),
                "baseline_progress": [self._model.n, config.MIN_BASELINE_SESSIONS],
                "quality": {"valid_beats": 0, "artifact_fraction": 1.0},
            })

        mask = clean_rr_mask(rr)
        valid_beats = int(mask.sum())
        artifact_fraction = float(1.0 - valid_beats / len(rr))
        duration_s = len(raw_samples) / self._fs
        # Durata QRS per ogni picco, poi riassunta a mediana dentro _compute_features.
        qrs_durations = extract_qrs_durations(filtered, peaks, self._fs)
        features = self._compute_features(rr, duration_s, mask, qrs_durations)

        colormap = self._build_local_colormap(rr, mask)
        features["status"] = "NEUTRAL"
        features["mahalanobis_d2"] = None
        features["feature_z"] = None
        # Indici dei picchi R: servono all'archivio per disegnare le bande RR
        # senza rieseguire il rilevamento (che girava sul thread della GUI).
        features["rr_peaks"] = [int(p) for p in peaks]
        features["baseline_error"] = self.baseline_error
        features["neutral_reason"] = None
        features["baseline_progress"] = [self._model.n, config.MIN_BASELINE_SESSIONS]
        features["quality"] = {"valid_beats": valid_beats,
                               "artifact_fraction": artifact_fraction}

        if duration_s < config.DURATION_MIN_SCORED_S:
            features["neutral_reason"] = NEUTRAL_SHORT_SESSION
            return ("NEUTRAL", colormap, features)
        if not quality_ok(valid_beats, artifact_fraction):
            features["neutral_reason"] = NEUTRAL_LOW_QUALITY
            return ("NEUTRAL", colormap, features)
        vec = features_to_vector(features)
        if vec is None:
            features["neutral_reason"] = NEUTRAL_LOW_QUALITY
            return ("NEUTRAL", colormap, features)
        if self.baseline_error:
            features["neutral_reason"] = NEUTRAL_BASELINE_ERROR
            return ("NEUTRAL", colormap, features)

        # Scoro contro la baseline che NON include la sessione corrente
        status, d2 = self._model.classify(vec)
        if status == "NEUTRAL":
            features["neutral_reason"] = NEUTRAL_BASELINE_BUILDING
        features["status"] = status
        features["mahalanobis_d2"] = None if np.isnan(d2) else d2
        if self._model.ready():
            z = self._model.feature_z(vec)
            features["feature_z"] = {name: float(z[i])
                                     for i, name in enumerate(_FEATURE_NAMES)}

        # Aggiornamento continuo della baseline, poi persistenza
        if status != "RED" or config.BASELINE_INCLUDE_RED:
            self._model.add(vec, session_id)
            self._save_model()

        # Conteggio DOPO l'inserimento: è quello che l'utente vede come
        # avanzamento ("baseline in costruzione: 4 / 5").
        features["baseline_progress"] = [self._model.n, config.MIN_BASELINE_SESSIONS]
        return (status, colormap, features)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _load_model(self) -> "BaselineModel":
        path = self._profile.dir / "baseline.json"
        try:
            data = secure_store.read_json(path, self._enc, default=None, strict=True)
        except secure_store.DecryptError:
            # File presente ma illeggibile: NON è una baseline vuota. Trattarlo
            # come tale porterebbe a sovrascriverlo alla prima sessione lunga.
            self.baseline_error = True
            return BaselineModel([])
        if isinstance(data, dict) and data.get("schema") == _BASELINE_SCHEMA:
            return BaselineModel(data.get("feature_pool", []),
                                 data.get("session_ids"))
    # Schema assente o precedente (v1/v2): dimensionalità del vettore diversa
    # (4 invece di 5, per l'assenza di qrs_duration), non compatibile con il
    # pool attuale. Si riparte da zero sullo schema nuovo.
        return BaselineModel([])
       # if isinstance(data, dict)
        #    schema = data.get("schema")
         #   if schema == _BASELINE_SCHEMA:
          #      return BaselineModel(data.get("feature_pool", []),
           #                          data.get("session_ids"))
            #if schema == _BASELINE_SCHEMA_LEGACY:
                # v1: nessun id: i vettori restano, ma non sono più associabili
                # alle sessioni e quindi non si rimuovono alla cancellazione.
             #   return BaselineModel(data.get("feature_pool", []))
        #return BaselineModel([])

    def _save_model(self) -> None:
        if self.baseline_error:
            return
        _write_model(self._profile, self._enc, self._model)

    def _extract_rr_intervals(self, raw: np.ndarray) -> np.ndarray:
        """Apply fresh DigitalFilter + RPeakDetector; return RR intervals (seconds)."""
        return extract_rr_intervals(raw, self._fs)
 #modifica compute_features aggiungendo qrs come features
    def _compute_features(self, rr: np.ndarray, duration_s: float,
                          mask: Optional[np.ndarray] = None,
                          qrs_durations: Optional[np.ndarray] = None) -> dict:
        """Compute HRV features from RR intervals.

        ``rr`` è la serie COMPLETA e ``mask`` marca gli intervalli validi. La
        distinzione conta per RMSSD e pNN50, che sono definiti sulle differenze
        fra battiti *successivi*: prima si passava la sola serie ripulita e
        ``np.diff`` scavalcava i battiti rimossi, misurando differenze fra
        intervalli non adiacenti. Media e SDNN usano invece i soli intervalli
        validi, come da prassi.

        Con ``mask=None`` tutti gli intervalli sono considerati validi e adiacenti.
        """
        rr = np.asarray(rr, dtype=float)
        if mask is None:
            mask = np.ones(len(rr), dtype=bool)
        valid = rr[mask]
        N = len(valid)

        #Aggiunta qrs
        def _median_qrs() -> Optional[float]:
            if qrs_durations is None:
                return None
            vals = np.asarray(qrs_durations, dtype=float)
            vals = vals[~np.isnan(vals)]
            return float(np.median(vals)) if len(vals) > 0 else None


        if N == 0:
            return {"mean_rr": None, "sdnn": None, "rmssd": None, "pnn50": None, "qrs_duration": None}

        mean_rr = float(np.mean(valid))
        empty = {"mean_rr": mean_rr, "sdnn": None, "rmssd": None, "pnn50": None, "qrs_duration": None}

        # Sessione breve (<60 s): solo mean_rr
        if N < 2 or duration_s < config.DURATION_MIN_SCORED_S:
            return empty

        # Differenze fra battiti adiacenti nella serie ORIGINALE, entrambi validi.
        diffs = np.diff(rr)[mask[:-1] & mask[1:]]
        if len(diffs) == 0:
            return {"mean_rr": mean_rr, "sdnn": float(np.std(valid, ddof=1)),
                    "rmssd": None, "pnn50": None, "qrs_duration": _median_qrs()}

        return {
            "mean_rr": mean_rr,
            "sdnn": float(np.std(valid, ddof=1)),
            "rmssd": float(np.sqrt(np.mean(diffs ** 2))),
            "pnn50": float(np.sum(np.abs(diffs) > 0.050) / len(diffs) * 100),
            "qrs_duration": _median_qrs(),
        }

    def _build_local_colormap(self, rr: np.ndarray, mask: np.ndarray) -> np.ndarray:
        """Colormap per-RR della DINAMICA LOCALE (solo visualizzazione): z degli
        RR rispetto a mediana/MAD della sessione stessa. Battiti non validi =
        NEUTRAL. Decouplata dallo stato della sessione."""
        rr = np.asarray(rr, dtype=float)
        n = len(rr)
        cm = np.full(n, _NEUTRAL, dtype=np.uint8)
        valid = rr[mask]
        if len(valid) < 2:
            return cm
        med = float(np.median(valid))
        mad = float(np.median(np.abs(valid - med)))
        scale = 1.4826 * mad
        if scale <= 0:
            # MAD nullo (maggioranza di battiti identici): ripiega sullo scarto
            # quadratico medio per restare sensibile a un outlier isolato.
            scale = float(np.std(valid))
        if scale <= 0:
            cm[mask] = _GREEN
            return cm
        z = np.abs(rr - med) / scale
        cm[mask & (z <= config.LOCAL_RR_GREEN_Z)] = _GREEN
        cm[mask & (z > config.LOCAL_RR_GREEN_Z) & (z <= config.LOCAL_RR_YELLOW_Z)] = _YELLOW
        cm[mask & (z > config.LOCAL_RR_YELLOW_Z)] = _RED
        return cm


# ---------------------------------------------------------------------------
# Module-level function
# ---------------------------------------------------------------------------

def _baseline_path(profile: Profile) -> Path:
    return profile.dir / "baseline.json"


def _write_model(profile: Profile, enc: EncryptionManager,
                 model: "BaselineModel") -> None:
    secure_store.write_json(_baseline_path(profile), {
        "schema": _BASELINE_SCHEMA,
        "feature_names": _FEATURE_NAMES,
        "feature_pool": model.pool_as_list(),
        "session_ids": model.session_ids_as_list(),
        "sessions_count": model.n,
    }, enc)


def remove_session_from_baseline(profile: Profile, enc: EncryptionManager,
                                 session_id: str) -> bool:
    """Toglie dalla baseline il vettore della sessione cancellata.

    Senza questo, eliminare una sessione dall'archivio la rimuoveva dalla vista
    ma non dal modello: la baseline continuava a essere influenzata da una
    registrazione che l'utente credeva sparita.

    Ritorna False se la baseline è illeggibile o se la sessione non vi compare
    (ad esempio perché salvata con lo schema v1, privo di id)."""
    analyser = HrvAnalyser(profile, enc)
    if analyser.baseline_error:
        return False
    if not analyser._model.remove_session(session_id):
        return False
    _write_model(profile, enc, analyser._model)
    return True


def save_session_results(
    profile: Profile,
    colormap: np.ndarray,
    features: dict,
    timestamp: datetime,
    enc: EncryptionManager,
) -> None:
    """Persist colormap (.colormap.npy) and features (.features.json) to the
    profile sessions dir, both encrypted at rest with the profile key."""
    ts = timestamp.strftime("%Y%m%d_%H%M%S")
    sessions_dir = profile.dir / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)

    secure_store.write_npy(sessions_dir / f"{ts}.colormap.npy", colormap, enc)
    secure_store.write_json(sessions_dir / f"{ts}.features.json", features, enc)
