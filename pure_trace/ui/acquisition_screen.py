import queue
import threading
import time
from datetime import datetime
from typing import Optional

import numpy as np
import serial
from PyQt5.QtCore import QTimer, Qt
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QFrame, QSizePolicy,
)

from pure_trace import config
from pure_trace.logging_setup import get_logger
from pure_trace.serial_port import find_port
from pure_trace.data_layer import Profile, EncryptionManager, EDFWriter
from pure_trace.analysis_engine import (
    HrvAnalyser, save_session_results,
    NEUTRAL_BASELINE_BUILDING, NEUTRAL_BASELINE_ERROR,
    NEUTRAL_LOW_QUALITY, NEUTRAL_SHORT_SESSION,
)
from pure_trace.signal_processing import (
    CircularBuffer, DigitalFilter, RPeakDetector, interpolate_gap,
)
from pure_trace.ui import theme
from pure_trace.ui.widgets import EcgPlotWidget

log = get_logger(__name__)


class _SerialThread(threading.Thread):
    """Runs continuously. In monitoring mode only checks LOD.
    In recording mode also writes samples to the shared buffer."""

    # Numero massimo di campioni persi consecutivi che ricostruiamo per
    # interpolazione (10 ms a 500 Hz). Oltre questa soglia si tratta di una
    # vera interruzione del flusso: non fabbrichiamo dati fisiologici.
    _MAX_GAP_FILL = 5

    def __init__(self, buf: CircularBuffer, lod_ok: threading.Event,
                 stop: threading.Event, port: Optional[str], baud: int):
        super().__init__(daemon=True)
        self._buf = buf
        self._lod_ok = lod_ok
        self._stop_evt = stop
        self._port = port
        self._baud = baud
        self._recording = threading.Event()
        self._raw_list: list[float] = []
        self._last_seq: Optional[int] = None
        self._last_norm: float = 0.0
        self._dropped: int = 0
        self._error: Optional[str] = None
        self._error_lock = threading.Lock()

    @property
    def error(self) -> Optional[str]:
        """Ultimo errore di connessione, o None se la seriale è attiva."""
        with self._error_lock:
            return self._error

    def _set_error(self, msg: Optional[str]) -> None:
        with self._error_lock:
            if msg != self._error:      # non inondare il log a ogni retry
                if msg is None:
                    log.info('Seriale connessa')
                else:
                    log.error('Seriale: %s', msg)
            self._error = msg

    def set_recording(self, active: bool) -> None:
        if active:
            self._raw_list.clear()
            self._last_seq = None
            self._last_norm = 0.0
            self._dropped = 0
            self._recording.set()
        else:
            self._recording.clear()

    @property
    def dropped(self) -> int:
        """Numero di campioni persi rilevati durante l'ultima registrazione."""
        return self._dropped

    def _ingest(self, seq: Optional[int], normalized: float) -> None:
        """Accoda un campione al buffer condiviso e alla lista grezza.

        Se il firmware fornisce il contatore di sequenza (``seq``) e rileviamo
        campioni mancanti, ricostruiamo i buchi piccoli per interpolazione, così
        la base dei tempi (indice/fs) resta valida per l'analisi HRV. Con il
        firmware legacy (``seq is None``) il comportamento è invariato."""
        if seq is not None and self._last_seq is not None:
            gap = (seq - self._last_seq - 1) & 0xFF
            if 0 < gap <= self._MAX_GAP_FILL:
                for s in interpolate_gap(self._last_norm, normalized, gap):
                    self._buf.write(np.array([s]))
                    self._raw_list.append(s)
                self._dropped += gap
            elif gap > self._MAX_GAP_FILL:
                # Gap troppo grande: vera interruzione, non interpoliamo.
                self._dropped += gap
        self._last_seq = seq
        self._last_norm = normalized
        self._buf.write(np.array([normalized]))
        self._raw_list.append(normalized)

    @property
    def raw_list(self) -> list[float]:
        return self._raw_list

    def _handle_line(self, line: str) -> None:
        if line.startswith('L,'):
            if line[2:] == '0':
                self._lod_ok.set()
            else:
                self._lod_ok.clear()
        elif line.startswith('D,') and self._recording.is_set():
            payload = line[2:]
            seq: Optional[int] = None
            if ',' in payload:
                # Nuovo formato "D,<seq>,<val>": il contatore permette di
                # rilevare campioni persi.
                seq_str, val_str = payload.split(',', 1)
                try:
                    seq = int(seq_str) & 0xFF
                except ValueError:
                    seq = None
            else:
                # Formato legacy "D,<val>" (firmware senza contatore).
                val_str = payload
            try:
                val = int(val_str)
            except ValueError:
                return
            normalized = (val - 512) / 512.0
            self._ingest(seq, normalized)

    def run(self) -> None:
        """Connette, legge, e in caso di errore riprova finché non si chiede lo stop.

        Prima un fallimento all'apertura terminava il thread in silenzio (app
        muta e inutilizzabile), mentre un errore in lettura veniva ingoiato da un
        ``except Exception: continue`` che mandava la CPU al 100% se il cavo USB
        veniva staccato."""
        while not self._stop_evt.is_set():
            port = find_port(self._port)
            if port is None:
                self._set_error('Arduino non rilevato: controlla il cavo USB')
                self._stop_evt.wait(config.SERIAL_RETRY_S)
                continue
            try:
                ser = serial.Serial(port, self._baud, timeout=1)
            except serial.SerialException as exc:
                self._set_error(f'Porta {port} non accessibile: {exc}')
                self._stop_evt.wait(config.SERIAL_RETRY_S)
                continue

            self._set_error(None)
            try:
                with ser:
                    while not self._stop_evt.is_set():
                        line = ser.readline().decode('ascii', errors='ignore').strip()
                        if line:
                            self._handle_line(line)
            except (serial.SerialException, OSError) as exc:
                # Dispositivo scollegato a caldo: segnala, azzera lo stato degli
                # elettrodi e riprova, senza consumare la CPU nel frattempo.
                self._set_error(f'Connessione persa: {exc}')
                self._lod_ok.clear()
                self._stop_evt.wait(config.SERIAL_RETRY_S)


class _ProcessingThread(threading.Thread):
    def __init__(self, buf: CircularBuffer, results: queue.Queue,
                 stop: threading.Event):
        super().__init__(daemon=True)
        self._buf = buf
        self._results = results
        self._stop_evt = stop
        self._filter = DigitalFilter(fs=config.SAMPLING_RATE)
        self._detector = RPeakDetector(
            fs=config.SAMPLING_RATE, refractory_ms=config.REFRACTORY_MS,
        )
        self._sample_index = 0
        self._warmup_samples = int(config.FILTER_WARMUP_S * config.SAMPLING_RATE)
        self._queue_drops = 0

    def run(self) -> None:
        while not self._stop_evt.is_set():
            # I campioni scartati per overflow non arriveranno mai qui, ma il
            # tempo è comunque passato: l'indice deve tenerne conto, altrimenti
            # gli intervalli RR della frequenza cardiaca live si accorciano.
            dropped = self._buf.take_dropped()
            if dropped:
                log.warning('Buffer in overflow: %d campioni persi', dropped)
                self._sample_index += dropped
            chunk = self._buf.read(10)
            if len(chunk) == 0:
                time.sleep(0.002)
                continue
            filtered = self._filter.process_array(chunk)
            for i, s in enumerate(filtered):
                idx = self._sample_index + i
                # Durante l'assestamento del filtro il segnale contiene un
                # transitorio grande quanto un'onda R: il tracciato lo mostra,
                # ma non deve produrre battiti fantasma nella frequenza cardiaca.
                if idx < self._warmup_samples:
                    continue
                self._detector.process(float(s), idx / config.SAMPLING_RATE)
            self._sample_index += len(chunk)
            hr = self._detector.get_hr()
            try:
                self._results.put_nowait((filtered, hr))
            except queue.Full:
                # La GUI non sta drenando: il tracciato avrà dei buchi. Non è
                # fatale (l'analisi usa i campioni grezzi del thread seriale),
                # ma va detto invece che sparire.
                self._queue_drops += 1
                if self._queue_drops % 100 == 1:
                    log.warning('Coda di rendering piena: %d blocchi scartati',
                                self._queue_drops)

    @property
    def detector(self) -> RPeakDetector:
        return self._detector


class AcquisitionScreen(QWidget):
    # None = durata libera: è l'operatore a fermare la registrazione.
    _DURATIONS = {'Libera': None, '2 min': config.DURATION_LONG_S}

    def __init__(self, profile: Profile, enc: EncryptionManager, parent=None):
        super().__init__(parent)
        self._profile = profile
        self._enc = enc
        self._selected_duration = config.DURATION_LONG_S
        self._recording = False
        self._elapsed_s = 0

        self._lod_ok = threading.Event()
        self._serial_stop = threading.Event()
        self._proc_stop = threading.Event()
        self._results_queue: queue.Queue = queue.Queue(maxsize=200)
        self._buf = CircularBuffer(maxlen=config.CIRCULAR_BUFFER_LEN)

        self._serial_thread: Optional[_SerialThread] = None
        self._proc_thread: Optional[_ProcessingThread] = None
        self._elapsed_timer: Optional[QTimer] = None
        self._serial_error_shown = False
        self._lod_state: Optional[str] = None

        self._build_ui()

        self._lod_timer = QTimer(self)
        self._lod_timer.timeout.connect(self._refresh_lod_indicator)
        self._lod_timer.start(250)

        self._clock_timer = QTimer(self)
        self._clock_timer.timeout.connect(self._refresh_clock)
        self._clock_timer.start(1000)
        self._refresh_clock()

        self._render_timer = QTimer(self)
        self._render_timer.timeout.connect(self._render_tick)

    # ------------------------------------------------------------------ #
    #  UI construction                                                     #
    # ------------------------------------------------------------------ #

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_top_bar())

        body = QHBoxLayout()
        body.setContentsMargins(14, 14, 14, 14)
        body.setSpacing(14)
        body.addWidget(self._build_ecg_card(), stretch=1)
        body.addWidget(self._build_rail())
        root.addLayout(body, stretch=1)

    # -- top bar (brand · profile · clock · leads pill) -------------------- #
    def _build_top_bar(self) -> QFrame:
        bar = QFrame()
        bar.setFixedHeight(50)
        bar.setStyleSheet(theme.top_bar_qss())
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(16, 0, 16, 0)
        lay.setSpacing(12)

        logo = QLabel('+')
        logo.setFixedSize(26, 26)
        logo.setAlignment(Qt.AlignCenter)
        logo.setStyleSheet(theme.brand_logo_qss())
        lay.addWidget(logo)
        brand = QLabel('Pure-Trace')
        brand.setFont(QFont('Sans', 13, QFont.Bold))
        brand.setStyleSheet('border:none')
        lay.addWidget(brand)

        chip = QLabel(self._profile.name)
        chip.setStyleSheet(theme.chip_qss())
        lay.addWidget(chip)
        lay.addStretch()

        self._clock_label = QLabel('--:--')
        self._clock_label.setStyleSheet(theme.clock_qss())
        lay.addWidget(self._clock_label)

        self._lod_label = QLabel('● Elettrodi non rilevati')
        self._lod_label.setStyleSheet(theme.leads_pill_qss(ok=False))
        lay.addWidget(self._lod_label)
        return bar

    # -- ECG card (header + plot) ------------------------------------------ #
    def _build_ecg_card(self) -> QFrame:
        card = QFrame()
        card.setStyleSheet(theme.card_qss())
        lay = QVBoxLayout(card)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        head = QFrame()
        head.setStyleSheet(f'QFrame{{border:none;border-bottom:1px solid {theme.BORDER}}}')
        hl = QHBoxLayout(head)
        hl.setContentsMargins(16, 10, 16, 10)
        lead = QLabel('ECG · Derivazione I')
        lead.setFont(QFont('Sans', 11, QFont.Bold))
        lead.setStyleSheet('border:none')
        hl.addWidget(lead)
        hl.addStretch()
        gain = QLabel('500 Hz · ampiezza norm.')
        gain.setStyleSheet(theme.section_label_qss())
        hl.addWidget(gain)
        lay.addWidget(head)

        self._ecg = EcgPlotWidget()
        self._ecg.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        lay.addWidget(self._ecg, stretch=1)
        return card

    # -- right rail (HR · duration · REC · result) ------------------------- #
    def _build_rail(self) -> QWidget:
        rail = QWidget()
        rail.setFixedWidth(232)
        lay = QVBoxLayout(rail)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)

        # HR hero card
        hr_card = QFrame()
        hr_card.setStyleSheet(theme.card_qss())
        hc = QVBoxLayout(hr_card)
        hc.setContentsMargins(16, 14, 16, 14)
        hc.setSpacing(2)
        hr_cap = QLabel('FREQUENZA CARDIACA')
        hr_cap.setStyleSheet(theme.section_label_qss())
        hc.addWidget(hr_cap)
        self._hr_label = QLabel('--')
        self._hr_label.setStyleSheet(theme.hr_value_qss())
        hc.addWidget(self._hr_label)
        hr_unit = QLabel('bpm')
        hr_unit.setStyleSheet(f'color:{theme.MUTED};font-size:14px;font-weight:600;border:none')
        hc.addWidget(hr_unit)
        lay.addWidget(hr_card)

        # Duration segmented control
        seg_card = QFrame()
        seg_card.setStyleSheet(theme.card_qss())
        sc = QVBoxLayout(seg_card)
        sc.setContentsMargins(14, 12, 14, 12)
        sc.setSpacing(8)
        seg_cap = QLabel('DURATA ACQUISIZIONE')
        seg_cap.setStyleSheet(theme.section_label_qss())
        sc.addWidget(seg_cap)
        track = QFrame()
        track.setStyleSheet(theme.segment_track_qss())
        tl = QHBoxLayout(track)
        tl.setContentsMargins(4, 4, 4, 4)
        tl.setSpacing(4)
        self._btn_free = QPushButton('Libera')
        self._btn_2min = QPushButton('2 min')
        for btn, key in ((self._btn_free, 'Libera'), (self._btn_2min, '2 min')):
            btn.setCheckable(True)
            btn.setStyleSheet(theme.segment_button_qss())
            btn.clicked.connect(lambda _, k=key: self._set_duration(k))
            tl.addWidget(btn)
        self._btn_2min.setChecked(True)
        sc.addWidget(track)
        lay.addWidget(seg_card)

        lay.addStretch()

        # Result banner (hidden until an acquisition completes)
        self._result_frame = QFrame()
        self._result_frame.setVisible(False)
        rl = QVBoxLayout(self._result_frame)
        rl.setContentsMargins(0, 0, 0, 0)
        self._result_label = QLabel()
        self._result_label.setFont(QFont('Sans', 12))
        self._result_label.setWordWrap(True)
        rl.addWidget(self._result_label)
        lay.addWidget(self._result_frame)

        # Big REC button
        self._rec_btn = QPushButton('● Avvia acquisizione')
        self._rec_btn.setEnabled(False)
        self._rec_btn.setFixedHeight(64)
        self._rec_btn.setFont(QFont('Sans', 15, QFont.Bold))
        self._rec_btn.setStyleSheet(theme.rec_button_qss())
        self._rec_btn.clicked.connect(self._on_rec_clicked)
        lay.addWidget(self._rec_btn)
        return rail

    # ------------------------------------------------------------------ #
    #  Public API                                                          #
    # ------------------------------------------------------------------ #

    def start_monitoring(self) -> None:
        """Open serial port and begin LOD monitoring. Call once at app start."""
        self._serial_stop.clear()
        self._serial_thread = _SerialThread(
            self._buf, self._lod_ok, self._serial_stop,
            config.SERIAL_PORT, config.SERIAL_BAUD,
        )
        self._serial_thread.start()

    @staticmethod
    def _neutral_message(features: dict) -> str:
        """NEUTRAL nasconde tre situazioni distinte, con azioni distinte: una
        baseline ancora incompleta non è un'acquisizione fallita, e dirlo con lo
        stesso testo mandava l'utente a cercare un problema inesistente."""
        reason = (features or {}).get('neutral_reason')
        if reason == NEUTRAL_BASELINE_BUILDING:
            done, needed = (features.get('baseline_progress')
                            or [0, config.MIN_BASELINE_SESSIONS])
            if done >= needed:
                # La sessione corrente è stata inserita ma valutata contro la
                # baseline PRECEDENTE, che non era ancora completa: dire "5 / 5"
                # accanto a un esito neutro sembrerebbe un errore.
                return ('Registrazione valida. Baseline completata: '
                        'la prossima sessione sarà valutata')
            return (f'Registrazione valida. Baseline in costruzione: '
                    f'{done} / {needed} sessioni')
        if reason == NEUTRAL_SHORT_SESSION:
            return (f'Registrazione troppo breve per la valutazione '
                    f'(minimo {config.DURATION_MIN_SCORED_S} s)')
        if reason == NEUTRAL_LOW_QUALITY:
            return 'Segnale troppo disturbato: controlla gli elettrodi e ripeti'
        if reason == NEUTRAL_BASELINE_ERROR:
            return 'Baseline illeggibile: sessione salvata, nessuna valutazione'
        return 'Acquisizione non sufficiente per la valutazione'

    def shutdown(self) -> None:
        """Ferma i thread e attende la loro uscita. Chiamata alla chiusura della
        finestra: prima main.py toccava gli attributi privati e non attendeva."""
        if self._recording:
            self._stop_recording()
        self._proc_stop.set()
        self._serial_stop.set()
        for thread in (self._proc_thread, self._serial_thread):
            if thread is not None and thread.is_alive():
                thread.join(timeout=2.0)
                if thread.is_alive():
                    log.warning('%s non terminato entro 2 s',
                                type(thread).__name__)
        self._proc_thread = None
        self._serial_thread = None
        log.info('Acquisizione terminata')

    def show_result(self, status: str, features: Optional[dict] = None) -> None:
        """Display analysis result. status: 'GREEN'|'YELLOW'|'RED'|'NEUTRAL'"""
        messages = {
            'GREEN':  'Parametri nella norma rispetto alla tua baseline',
            'YELLOW': 'Lievi variazioni rispetto alla tua baseline',
            'RED':    'Variazioni significative rispetto alla tua baseline',
        }
        status = status if status in messages else 'NEUTRAL'
        text = messages.get(status) or self._neutral_message(features or {})
        self._result_label.setText(text)
        self._result_label.setStyleSheet(theme.result_box_qss(theme.STATUS[status]))
        self._result_frame.setVisible(True)

    # ------------------------------------------------------------------ #
    #  Internal slots                                                      #
    # ------------------------------------------------------------------ #

    def _set_duration(self, key: str) -> None:
        self._selected_duration = self._DURATIONS[key]
        self._btn_free.setChecked(key == 'Libera')
        self._btn_2min.setChecked(key == '2 min')

    def _refresh_clock(self) -> None:
        self._clock_label.setText(datetime.now().strftime('%H:%M'))

    _LOD_LABELS = {
        'serial': ('● Sensore scollegato', False),
        'off':    ('● Elettrodi non rilevati', False),
        'ok':     ('● Elettrodi OK', True),
    }

    def _refresh_lod_indicator(self) -> None:
        # Un guasto della seriale non è un problema di elettrodi: distinguerli,
        # altrimenti l'utente vede "elettrodi non rilevati" e cerca la causa
        # sul paziente invece che sul cavo USB.
        serial_error = self._serial_thread.error if self._serial_thread else None
        if serial_error is not None:
            state = 'serial'
        else:
            state = 'ok' if self._lod_ok.is_set() else 'off'

        # Riapplicare il QSS a ogni tick (4 volte al secondo) costa a Qt un
        # riparsing inutile: si aggiorna solo quando lo stato cambia davvero.
        if state != self._lod_state:
            text, ok = self._LOD_LABELS[state]
            self._lod_label.setText(text)
            self._lod_label.setStyleSheet(theme.leads_pill_qss(ok=ok))
            self._lod_state = state

        if self._recording:
            return

        if state == 'serial':
            self._rec_btn.setEnabled(False)
            if not self._serial_error_shown:
                self._show_error(serial_error)
                self._serial_error_shown = True
            return

        # Il banner si nasconde solo se stava mostrando l'errore seriale: il
        # flag va alzato quando lo si mostra davvero, non quando l'errore esiste.
        # Altrimenti un'interruzione avvenuta DURANTE la registrazione faceva
        # sparire da solo l'esito appena mostrato.
        if self._serial_error_shown:
            self._result_frame.setVisible(False)
            self._serial_error_shown = False
        self._rec_btn.setEnabled(state == 'ok')

    def _show_error(self, message: str) -> None:
        self._result_label.setText(message)
        self._result_label.setStyleSheet(theme.result_box_qss(theme.RED))
        self._result_frame.setVisible(True)

    def _on_rec_clicked(self) -> None:
        if not self._recording:
            self._start_recording()
        else:
            self._stop_recording()

    def _start_recording(self) -> None:
        self._recording = True
        self._elapsed_s = 0
        self._result_frame.setVisible(False)
        self._ecg.clear()
        self._ecg.auto_range()   # auto-fit the plot (no manual 'A' needed)
        self._hr_label.setText('--')
        self._rec_btn.setStyleSheet(theme.rec_button_qss(recording=True))
        self._buf.clear()
        self._results_queue = queue.Queue(maxsize=200)

        if self._serial_thread:
            self._serial_thread.set_recording(True)

        # Un Event NUOVO per ogni registrazione. Riusando lo stesso oggetto, un
        # eventuale thread precedente ancora vivo sarebbe stato "resuscitato"
        # dalla clear() e avrebbe consumato campioni in parallelo al nuovo.
        self._proc_stop = threading.Event()
        self._proc_thread = _ProcessingThread(
            self._buf, self._results_queue, self._proc_stop,
        )
        self._proc_thread.start()
        self._render_timer.start(config.UI_REFRESH_MS)

        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.timeout.connect(self._on_second_tick)
        self._elapsed_timer.start(1000)

    @staticmethod
    def _mmss(seconds: int) -> str:
        return f'{seconds // 60}:{seconds % 60:02d}'

    def _on_second_tick(self) -> None:
        self._elapsed_s += 1
        if self._selected_duration is None:
            # Durata libera: il tempo sale ed è l'operatore a fermare. Il limite
            # massimo è solo una rete di sicurezza contro una registrazione
            # dimenticata in corso.
            self._rec_btn.setText(f'■ STOP  ({self._mmss(self._elapsed_s)})')
            if self._elapsed_s >= config.DURATION_MAX_S:
                self._stop_recording()
            return
        remaining = self._selected_duration - self._elapsed_s
        self._rec_btn.setText(f'■ STOP  ({remaining}s)')
        if self._elapsed_s >= self._selected_duration:
            self._stop_recording()

    def _stop_recording(self) -> None:
        self._recording = False
        if self._serial_thread:
            self._serial_thread.set_recording(False)
        self._proc_stop.set()
        if self._proc_thread:
            # Attende l'uscita effettiva prima di leggere i campioni: senza join
            # il thread poteva ancora consumare dal buffer condiviso.
            self._proc_thread.join(timeout=1.0)
            if self._proc_thread.is_alive():
                log.warning('Thread di elaborazione non terminato entro 1 s')
            self._proc_thread = None
        self._render_timer.stop()
        if self._elapsed_timer:
            self._elapsed_timer.stop()
        self._rec_btn.setText('● Avvia acquisizione')
        self._rec_btn.setStyleSheet(theme.rec_button_qss())
        ok, status, features = self._save_session()
        if ok:
            self.show_result(status, features)

    def _save_session(self) -> tuple[bool, str, dict]:
        """Save encrypted EDF+ and run HRV analysis. Returns (success, status, features)."""
        if not self._serial_thread:
            return False, 'NEUTRAL', {}
        raw = np.array(self._serial_thread.raw_list, dtype=np.float32)
        ts = datetime.now()
        try:
            EDFWriter.save(raw, self._profile, self._enc, ts)
        except ValueError:
            # Meno di 1 s di dati: con la durata libera è un tocco accidentale
            # su STOP, non un guasto. Va detto, non ignorato in silenzio.
            log.info('Registrazione scartata: solo %d campioni', len(raw))
            self._show_error('Registrazione troppo breve: nulla da salvare')
            return False, 'NEUTRAL', {}
        except Exception:
            log.exception('Salvataggio della sessione fallito')
            self._show_error('Salvataggio fallito')
            return False, 'NEUTRAL', {}
        analyser = HrvAnalyser(self._profile, self._enc)
        # Lo stem del file di sessione è anche l'id del vettore in baseline.
        status, colormap, features = analyser.analyse(
            raw, session_id=ts.strftime('%Y%m%d_%H%M%S'))
        save_session_results(self._profile, colormap, features, ts, self._enc)
        if analyser.baseline_error:
            # La registrazione è salvata, ma la baseline non è decifrabile: non
            # viene sovrascritta e nessuno scoring è possibile finché non si
            # ripristina (o si rimuove) baseline.json.
            log.error('baseline.json non decifrabile: scoring disabilitato')
            self._show_error(self._neutral_message(features))
            return False, 'NEUTRAL', features
        if self._serial_thread.dropped:
            log.warning('Campioni persi durante la registrazione: %d',
                        self._serial_thread.dropped)
        return True, status, features

    def _render_tick(self) -> None:
        chunks = []
        last_hr: Optional[float] = None
        while True:
            try:
                filtered_chunk, hr = self._results_queue.get_nowait()
                chunks.append(filtered_chunk)
                last_hr = hr
            except queue.Empty:
                break
        if chunks:
            self._ecg.append_samples(np.concatenate(chunks))
        if last_hr is not None and last_hr > 0:
            self._hr_label.setText(f'{last_hr:.0f}')
