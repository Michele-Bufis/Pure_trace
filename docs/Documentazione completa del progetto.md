# Pure-Trace — Documentazione completa del progetto

> Prototipo di ricerca per l'acquisizione e l'analisi di segnale ECG mono-derivazione,
> con classificazione dello stato del paziente rispetto a una baseline fisiologica
> personale. **Non è un dispositivo medico e non va usato a fini diagnostici.**

Questo documento è diviso in tre parti:

- **PARTE 1** — spiegazione teorica del progetto, del suo scopo e delle scelte
  fatte, senza riferimenti al codice. Serve a capire *cosa fa* il sistema e *perché*
  è stato progettato così.
- **PARTE 2** — spiegazione tecnica organizzata per file e per compito, con
  riferimento diretto a classi e funzioni. Serve a capire *come* è implementato
  il software.
- **PARTE 3** — documentazione hardware del prototipo fisico: componenti,
  alimentazione, compatibilità elettromagnetica, sicurezza meccanica/elettrica,
  gestione termica, catena del segnale lato hardware, distinta base e rischi
  residui. Serve a capire *su cosa gira* il software descritto in Parte 2, e
  con quali vincoli e trade-off è stato costruito.

---

# PARTE 1 — Panoramica teorica del progetto

## 1. Che cos'è Pure-Trace

Pure-Trace è un sistema completo (hardware + firmware + applicazione desktop)
che acquisisce un tracciato ECG a singola derivazione da un paziente, lo elabora
in tempo reale per estrarre la frequenza cardiaca e la variabilità cardiaca (HRV),
e — dopo un periodo di apprendimento — confronta ogni nuova registrazione con la
**baseline fisiologica personale** del paziente stesso, segnalando se i parametri
osservati rientrano nella norma individuale o se se ne discostano.

Il progetto è pensato per girare su un **Raspberry Pi con schermo touch 800×480**,
collegato via USB a un **Arduino Nano** che legge un sensore ECG **AD8232**
(SparkFun Single Lead Heart Rate Monitor). L'interfaccia è quindi progettata per
un uso "da consolle" touch, senza tastiera né mouse, in un contesto simile a un
piccolo dispositivo da ambulatorio o da ricerca clinica.

È esplicitamente **un prototipo di ricerca**: non fornisce una diagnosi, non è
calibrato in millivolt clinici, e la sua funzione è individuare *scostamenti
relativi rispetto a sé stesso* (il paziente è il proprio termine di paragone),
non stabilire soglie patologiche assolute.

## 2. Il flusso complessivo, dall'elettrodo allo schermo

1. Gli elettrodi sul paziente sono collegati all'AD8232, che amplifica e
   filtra analogicamente il segnale cardiaco e lo restituisce come tensione
   analogica, insieme a un segnale digitale di "elettrodo staccato" (leads-off).
2. L'Arduino Nano campiona questo segnale a 500 Hz e lo invia via seriale USB
   al Raspberry Pi, insieme allo stato degli elettrodi e a un contatore di
   sequenza che permette di accorgersi se qualche campione va perso lungo la via.
3. L'applicazione desktop (Python/PyQt5) legge il flusso seriale, lo filtra
   digitalmente per rimuovere il rumore di rete e le derive lente, individua i
   battiti (picchi R) e calcola la frequenza cardiaca in tempo reale, mostrando
   il tracciato che scorre a schermo.
4. Quando l'operatore ferma (o esaurisce il tempo del) l'acquisizione, il
   tracciato grezzo viene salvato in formato clinico standard (EDF+), cifrato,
   e analizzato offline per estrarre le metriche di variabilità cardiaca.
5. Queste metriche vengono confrontate con la baseline personale del paziente
   (se sufficientemente popolata) e la sessione riceve un'etichetta:
   nella norma, lieve variazione, fuori baseline, oppure "non valutata" con un
   motivo specifico.
6. La sessione entra a far parte dell'archivio del paziente, consultabile in
   una seconda schermata dove si può rivedere il tracciato, i valori numerici,
   esportare la registrazione in chiaro o eliminarla.

## 3. Perché una baseline personale, e non soglie standard di popolazione

Le metriche di variabilità cardiaca (quanto varia, battito dopo battito,
l'intervallo tra un battito e il successivo) sono fortemente individuali: quello
che è "normale" per una persona può non esserlo per un'altra, a parità di età e
condizioni. Pure-Trace non usa quindi soglie fisse prese da tabelle di
popolazione, ma costruisce, sessione dopo sessione, un **modello statistico
personale** nello spazio delle feature (frequenza cardiaca media, SDNN, RMSSD,
pNN50). Una nuova sessione viene poi giudicata in base a quanto si discosta,
in questo spazio a più dimensioni, dal proprio centro di gravità storico — una
misura chiamata **distanza di Mahalanobis**, che tiene conto anche di come le
diverse metriche co-variano tra loro nella storia di quel singolo paziente.

Perché questo approccio sia statisticamente onesto, servono almeno cinque
sessioni "lunghe" già registrate prima che il sistema inizi a dare un giudizio:
sotto quella soglia il modello non ha abbastanza dati per stimare in modo
affidabile la propria variabilità naturale, e la sessione viene marcata come "in
costruzione della baseline" invece di ricevere un'etichetta.

## 4. Il significato del semaforo GREEN / YELLOW / RED / NEUTRAL

Ogni sessione "lunga" (almeno 60 secondi) con qualità del segnale sufficiente
riceve, una volta che la baseline è pronta, uno dei quattro stati:

- **GREEN** — i parametri rientrano nella variabilità storica abituale del
  paziente.
- **YELLOW** — scostamento intermedio: la sessione si discosta dalla norma
  individuale, ma non in modo estremo.
- **RED** — la sessione si discosta in modo marcato dalla baseline personale.
- **NEUTRAL** — non è stato possibile dare un giudizio, per uno di questi
  motivi distinti (mostrati esplicitamente all'operatore, non genericamente
  come "errore"): la registrazione è troppo breve, il segnale è troppo
  disturbato (troppi artefatti), la baseline è ancora in fase di costruzione,
  oppure il file della baseline risulta illeggibile.

Questa distinzione tra le cause del NEUTRAL è una scelta deliberata di
progetto: confondere "baseline ancora incompleta" con "segnale disturbato"
manderebbe l'operatore a cercare un problema (elettrodi, cavi) che non esiste,
quando in realtà basta semplicemente registrare qualche sessione in più.

Va inoltre notato che una sessione RED partecipa comunque, di norma, alla
baseline futura (è configurabile): l'idea è che la baseline rappresenti la
variabilità naturale del paziente nel tempo, comprese le sue fluttuazioni, e non
solo i suoi "giorni buoni".

## 5. Cosa viene misurato: le metriche di variabilità cardiaca

A partire dagli intervalli tra battiti successivi (intervalli RR), il sistema
calcola quattro grandezze standard in ambito HRV:

- **Frequenza cardiaca media** (derivata dall'intervallo RR medio).
- **SDNN** — deviazione standard degli intervalli RR: quanto, in generale,
  il ritmo cardiaco oscilla nel corso della registrazione.
- **RMSSD** — radice quadrata media delle differenze tra intervalli RR
  successivi: sensibile soprattutto alla componente di variabilità legata al
  sistema nervoso parasimpatico, battito per battito.
- **pNN50** — percentuale di coppie di battiti successivi che differiscono
  di più di 50 millisecondi: un altro indicatore della variabilità a breve
  termine.

Per essere fisiologicamente significative, SDNN/RMSSD/pNN50 richiedono
registrazioni di almeno 60 secondi; sotto quella soglia si riporta solo la
frequenza cardiaca media.

## 6. Qualità del segnale e rigetto degli artefatti

Non tutti i battiti rilevati sono affidabili: un movimento, un contatto
imperfetto dell'elettrodo, un doppio conteggio possono produrre intervalli RR
"impossibili" o comunque anomali rispetto al contesto immediato. Prima di
calcolare qualunque metrica, il sistema:

- scarta gli intervalli fuori dal range fisiologico plausibile (tra 30 e 180
  battiti al minuto);
- confronta ogni intervallo con la mediana di un piccolo intorno di battiti
  vicini, ed esclude quelli che se ne discostano troppo (un artefatto isolato
  non riesce così a "farsi passare da solo", perché la mediana locale è
  robusta fino a diversi artefatti consecutivi, ma non è mai calcolata
  includendo il battito che si sta giudicando);
- richiede un numero minimo di battiti validi e una frazione massima di
  artefatti perché la sessione venga considerata scorabile; altrimenti riceve
  lo stato NEUTRAL con motivo "qualità insufficiente", invitando a ripetere la
  misura.

Questo meccanismo di controllo qualità è distinto e indipendente dalla
classificazione rispetto alla baseline: serve a garantire che si stia
confrontando "segnale buono con segnale buono".

## 7. Il tracciato colorato: due livelli di lettura

Nella schermata di archivio, sotto al tracciato ECG di ogni sessione, viene
disegnata una striscia colorata battito per battito. È importante distinguere
due livelli diversi di colorazione presenti nel sistema, che rispondono a
domande diverse:

- **Colorazione locale della sessione** (quella disegnata sulla striscia e
  sovrapposta al tracciato): mostra quanto ogni singolo intervallo RR si
  discosta dalla *tipica variabilità interna a quella stessa registrazione*.
  È un indicatore di "regolarità del ritmo durante questi pochi minuti", a fini
  puramente visivi, e non richiede alcuna baseline storica.
- **Stato complessivo della sessione** (il semaforo GREEN/YELLOW/RED/NEUTRAL
  descritto sopra, mostrato come etichetta e come colore del bordo della card):
  è invece il giudizio, calcolato una sola volta per l'intera sessione, di
  quanto quella sessione nel suo complesso si discosti dalla baseline
  *storica* del paziente.

Le due cose possono benissimo dare risposte diverse: una sessione può avere un
ritmo internamente molto regolare (striscia tutta verde) ma un valore medio
comunque anomalo rispetto allo storico del paziente (stato RED), o viceversa.

## 8. Privacy e protezione dei dati del paziente

Trattandosi di dati sanitari sensibili destinati a restare su una scheda SD
potenzialmente estraibile dal dispositivo, la protezione dei dati è stata
trattata come requisito di primo piano, non come aggiunta:

- **Ogni profilo paziente è protetto da password.** La password non viene mai
  salvata: da essa si deriva, tramite una funzione di derivazione di chiave
  lenta e con un numero elevato di iterazioni (per resistere a tentativi di
  indovinare la password offline), una chiave di cifratura specifica di quel
  profilo.
- **Il nome reale del paziente non è mai scritto in chiaro su disco.** Nella
  schermata di selezione del profilo, *prima* di inserire la password, viene
  mostrato solo un alias non identificativo (per default le iniziali, es.
  "M. R." per "Mario Rossi"). Il nome per esteso è cifrato e viene recuperato
  solo dopo un login riuscito.
- **Il tracciato ECG grezzo, le metriche HRV e la baseline sono tutti cifrati
  a riposo** con la chiave derivata dalla password del profilo. Nessuno di
  questi file è leggibile estraendo la scheda SD senza conoscere la password.
- **Anche la dimensione dei file cifrati viene mascherata**, imbottendola a
  blocchi fissi prima della cifratura: altrimenti, dalla sola dimensione di un
  file (che dipende dal numero di battiti registrati), si potrebbe risalire
  alla frequenza cardiaca media del paziente senza mai decifrare nulla.
- **Il segnale ECG in chiaro, quando deve necessariamente toccare il
  filesystem** (la libreria usata per il formato clinico EDF+ sa scrivere solo
  su file), viene scritto per quanto possibile in memoria RAM (tmpfs) invece
  che sulla scheda SD, e in ogni caso il file temporaneo viene sovrascritto
  con dati casuali prima di essere cancellato, per non lasciare tracce
  recuperabili sul supporto fisico.
- **L'esportazione di una sessione** (per uso con strumenti clinici esterni
  tipo EDFbrowser) produce deliberatamente un file **non cifrato**: l'utente
  viene avvisato esplicitamente prima di procedere, perché da quel momento la
  protezione ricade sotto la sua responsabilità (es. una chiavetta USB).

## 9. Robustezza operativa, pensata per l'uso "sul campo"

Il dispositivo è pensato per essere usato in autonomia, spesso senza una
console o un tecnico a disposizione in caso di problema. Diverse scelte di
progetto riflettono questo:

- Se l'Arduino non viene trovato, o la connessione USB cade a metà
  registrazione, l'app lo segnala chiaramente e riprova automaticamente,
  distinguendo esplicitamente un problema di collegamento (cavo/porta) da un
  problema di elettrodi scollegati dal paziente: sono due situazioni che
  richiedono azioni diverse da parte dell'operatore.
- Se durante la trasmissione seriale si perdono dei campioni (per
  congestione, cavo instabile, ecc.), il sistema se ne accorge grazie a un
  contatore di sequenza inviato dal firmware, e ricostruisce per interpolazione
  i piccoli buchi, in modo che il calcolo degli intervalli tra i battiti non
  venga falsato da un tempo che è silenziosamente "scivolato".
- La creazione di un nuovo profilo è **atomica**: viene costruita
  interamente in una cartella temporanea nascosta e resa visibile solo a
  lavoro completato, così un'interruzione a metà (blackout, chiusura
  anomala) non lascia un profilo "mezzo fatto" che manderebbe in crash
  l'app al login successivo.
- Anche il salvataggio di ogni file (sessione, baseline, metriche) è
  atomico: si scrive su un file temporaneo, lo si forza sul supporto fisico,
  e solo allora lo si rinomina al posto del file definitivo — un calo di
  tensione a metà scrittura non lascia quindi mai un file troncato e
  illeggibile al posto di uno buono.
- Il sistema distingue esplicitamente "non ho dati" da "ho dati ma sono
  corrotti": se il file della baseline esiste ma non si riesce a decifrarlo,
  l'app non lo tratta come una baseline vuota (che verrebbe silenziosamente
  sovrascritta, perdendo per sempre lo storico del paziente), ma segnala
  l'errore e sospende lo scoring finché il problema non viene risolto
  manualmente.
- È presente un log applicativo persistente su file (con rotazione, per non
  crescere indefinitamente), pensato per poter capire cosa sia successo anche
  su un dispositivo da campo senza schermo di debug collegato.

## 10. L'interfaccia utente

L'app ha due sole schermate principali, pensate per un touchscreen di piccole
dimensioni (800×480) senza tastiera fisica:

- **Acquisizione**: mostra il tracciato ECG in tempo reale, la frequenza
  cardiaca corrente, lo stato degli elettrodi, un selettore della durata
  della registrazione (libera, oppure fissa a 2 minuti) e il grande pulsante
  di avvio/stop. Al termine, mostra l'esito della valutazione.
- **Archivio**: elenca tutte le sessioni salvate per il paziente attivo, più
  recenti in cima, ciascuna con data, durata, stato (colore), e le principali
  metriche in sintesi. Toccando una sessione se ne vede il dettaglio: il
  tracciato completo (scorrevole), la striscia colorata battito-per-battito,
  le quattro metriche numeriche, e i pulsanti per esportare o eliminare la
  registrazione.

Il linguaggio visivo è deliberatamente "clinico ma accessibile": superfici
chiare con una lieve tinta di teal, testo ad alto contrasto, un solo colore di
accento per le azioni, e i soli tre colori verde/ambra/rosso riservati
esclusivamente allo stato clinico, mai usati per altro. I controlli hanno
un'area minima di tocco pensata per l'uso touch (non con il mouse).

Un disclaimer ("prototipo di ricerca, non è un dispositivo medico") è mostrato
esplicitamente nella schermata di login.

## 11. Cosa NON fa (limiti dichiarati)

- Non fornisce una diagnosi clinica: individua solo scostamenti relativi da
  una baseline personale, non condizioni patologiche.
- Il segnale non è calibrato in millivolt clinici standard: il sensore usato
  non fornisce un'uscita calibrata, e questo viene dichiarato esplicitamente
  anche nei metadati del file esportato, per non far credere a chi lo apre con
  strumenti clinici di avere di fronte un tracciato calibrato.
- La cancellazione sicura dei file su schede SD/SSD con wear-levelling non è
  garantita al 100% dalla semplice sovrascrittura: è una mitigazione, non una
  garanzia crittografica assoluta.

---

# PARTE 2 — Guida al codice, per file e per compito

Il progetto è organizzato in un pacchetto Python `pure_trace`, un sottopacchetto
`pure_trace.ui` per l'interfaccia grafica, uno sketch Arduino separato, e uno
script CLI di utilità. Di seguito ogni file, diviso in mini-paragrafi per
compito svolto.

## `pure_trace_firmware.ino` — firmware Arduino (front-end del sensore)

**Compito: definire il protocollo seriale.** Il firmware invia due tipi di
riga di testo terminate da `\n`: `D,<seq>,<val>` per ogni campione ECG (`seq`
un contatore 0–255 con wrap, `val` la lettura ADC grezza 0–1023), e `L,0` /
`L,1` per segnalare rispettivamente elettrodi collegati o staccati. Il baud
rate è fissato a 115200, la frequenza di campionamento a 500 Hz.

**Compito: temporizzazione precisa a 500 Hz.** Il campionamento non usa
`delay()`, ma confronta `micros()` con un prossimo istante target
(`nextSampleUs`), incrementato di 2000 µs a ogni giro; il cast a `long` nel
confronto gestisce correttamente l'overflow di `micros()` dopo circa 70 minuti.

**Compito: risincronizzazione senza falsificare il tempo.** Se il loop
accumula un ritardo di oltre un intervallo di campionamento (perché il PC
legge lentamente dalla seriale), il firmware non recupera i campioni arretrati
inviandoli tutti insieme (il che comprimerebbe artificialmente più campioni
sullo stesso istante reale), ma salta in avanti l'orologio target e **fa
avanzare comunque il contatore di sequenza** del numero di campioni saltati:
è proprio questo contatore che permette al software sul PC di accorgersi del
buco e di gestirlo, invece di vederlo sparire silenziosamente.

**Compito: lettura dello stato elettrodi.** Legge digitalmente i pin LO+ e
LO- dell'AD8232 (alti quando un elettrodo si stacca) e invia una riga `L,`
ogni volta che lo stato cambia, oltre che periodicamente ogni 100 ms come
richiamo, anche se lo stato non cambia.

**Compito: non bloccare il campionamento per la seriale piena.** Prima di
scrivere la riga del campione, verifica che il buffer di trasmissione seriale
abbia spazio sufficiente (`Serial.availableForWrite()`); se non ce n'è,
**salta l'invio di quel campione** (ma incrementa comunque il contatore di
sequenza) invece di lasciare che `Serial.print` blocchi il microcontrollore in
attesa, il che introdurrebbe jitter nella base dei tempi di tutti i campioni
successivi.

## `config.py` — parametri centralizzati del sistema

**Compito: percorsi dei dati.** `DATA_DIR`/`PROFILES_DIR` sono ancorati alla
posizione del pacchetto (non alla cartella di lavoro corrente), così l'app
scrive sempre nello stesso posto indipendentemente da come viene avviata (es.
da systemd). Sovrascrivibile con la variabile d'ambiente `PURE_TRACE_DATA`.

**Compito: parametri seriali e di campionamento.** `SERIAL_PORT` (auto-rilevata
se `None`), `SERIAL_BAUD`, `SERIAL_RETRY_S`, `SAMPLING_RATE` (500 Hz).

**Compito: parametri del filtro digitale.** Frequenza e Q del notch (50 Hz,
per la rete elettrica), banda del passa-banda (0.5–40 Hz) e relativo ordine.

**Compito: parametri di rilevamento del picco R.** Periodo refrattario (200
ms), finestra di stima dell'ampiezza locale, frazione di soglia rispetto al
massimo locale, numero di RR usati per la media mobile della frequenza
cardiaca, e la durata di *warm-up* del filtro (3 s) scartata perché il
passa-alto, partendo da stato nullo su un ingresso con offset DC, produce un
transitorio grande quanto un'onda R.

**Compito: durate delle registrazioni.** Durata "lunga" standard (2 minuti),
tetto di sicurezza per la durata libera (15 minuti), soglia minima sotto la
quale l'HRV non viene calcolata (60 s).

**Compito: parametri di rigetto artefatti.** Range fisiologico degli RR,
soglia di scostamento relativo dalla mediana locale, ampiezza della finestra
mediana (11, dimensionata per tollerare fino a 5 artefatti consecutivi senza
farsi "convincere" da loro), numero minimo di battiti validi e frazione
massima di artefatti tollerata per considerare scorabile una sessione.

**Compito: parametri della baseline/Mahalanobis.** Numero minimo di sessioni
lunghe prima di iniziare a scorare, ridge di regolarizzazione della
covarianza (per garantirne l'invertibilità), capienza massima del pool di
feature (FIFO), se le sessioni RED entrano comunque nella baseline, e i due
quantili di soglia (95° e 99°) usati per calibrare i confini GREEN/YELLOW e
YELLOW/RED.

**Compito: parametri di sola visualizzazione.** Soglie in z-score per la
colorazione locale della dinamica RR e per la tinta dei valori numerici delle
metriche.

## `serial_port.py` — individuazione automatica della porta Arduino

**Compito: trovare la porta giusta su qualunque sistema operativo.** Invece
di una porta fissata a mano (che su un sistema diverso da quello di sviluppo
semplicemente non esiste, causando un fallimento silenzioso del thread
seriale), `find_port()` cerca fra le porte USB disponibili quella il cui VID
corrisponde a uno dei convertitori seriali noti montati sulle schede Arduino
più comuni (CH340/CH341, Arduino ufficiale, FTDI, CP210x); se nessun VID
combacia, prova un secondo criterio basato su pattern noti nel nome del
device (`ttyUSB`, `ttyACM`, `cu.usbserial`, ecc.). Una porta preferita
esplicitamente configurata vince se effettivamente presente, ma viene
ignorata (non blocca l'avvio) se configurata ma assente.

## `signal_processing.py` — elaborazione del segnale in tempo reale

**Compito: ricostruire campioni persi.** `interpolate_gap()` riempie per
interpolazione lineare i campioni mancanti tra due valori noti, mantenendo
coerente la base dei tempi (indice/frequenza) usata per calcolare gli
intervalli RR.

**Compito: coda produttore/consumatore thread-safe.** `CircularBuffer` è una
coda FIFO a lunghezza limitata condivisa fra il thread seriale (che scrive) e
il thread di elaborazione (che legge); in overflow scarta i campioni più
vecchi, ma **conta** quanti ne scarta (`take_dropped()`), così il consumatore
può riallineare il proprio indice temporale invece di lasciarlo scivolare in
silenzio.

**Compito: filtraggio digitale del segnale.** `DigitalFilter` applica in
cascata un filtro notch (per il rumore di rete a 50 Hz) e un passa-banda
0.5–40 Hz (per rimuovere deriva della linea di base e rumore ad alta
frequenza), mantenendo lo stato interno del filtro (`zi`) fra una chiamata e
l'altra sia in modalità campione-per-campione (`process_sample`, per il
flusso live) sia in modalità a blocchi (`process_array`, molto più veloce,
usata per l'analisi offline dell'intera registrazione, dando lo stesso
risultato numerico di N chiamate sequenziali).

**Compito: rilevare i picchi R in tempo reale.** `RPeakDetector` mantiene una
soglia adattiva pari a una frazione del massimo osservato in una finestra
mobile recente (implementata con una **deque monotona** per ottenere il
massimo in tempo costante invece che ricalcolarlo ogni volta su tutta la
finestra), e impone un periodo refrattario minimo fra due rilevamenti
consecutivi per evitare doppi conteggi sullo stesso battito. Espone anche una
frequenza cardiaca corrente calcolata come media mobile degli ultimi
intervalli RR.

## `analysis_engine.py` — analisi offline HRV e modello di baseline

**Compito: rilevamento dei picchi R offline, con precisione al campione.**
`detect_rpeak_indices()` filtra l'intera registrazione in un colpo solo,
scarta il transitorio di warm-up iniziale, individua i superamenti soglia con
lo stesso `RPeakDetector` usato in tempo reale, poi **sposta ogni rilevamento
sull'apice reale dell'onda R** (`_snap_to_apex`): il rilevatore scatta infatti
sul primo campione che supera la soglia, non sul picco, e questo ritardo varia
battito per battito perché l'ampiezza dell'onda R è modulata dal respiro — un
effetto che finirebbe proprio dentro RMSSD, la metrica che misura la
variazione fra battiti successivi (misurato: un errore di circa +5% su RMSSD
si riduce a +1% con questa correzione).

**Compito: rigetto degli artefatti.** `clean_rr_mask()` implementa la logica
descritta nella Parte 1: range fisiologico più scostamento dalla mediana
locale, con l'intervallo giudicato sempre escluso dal calcolo della propria
mediana di riferimento. `quality_ok()` decide se la sessione, nel suo
complesso, è abbastanza pulita da poter essere scorata.

**Compito: preparare il vettore di feature.** `features_to_vector()` converte
il dizionario di metriche HRV in un vettore numerico a 4 dimensioni
`[frequenza media, SDNN, RMSSD, pNN50]`, gestendo correttamente il caso in cui
alcune metriche valgano legittimamente zero (senza scartarle per errore come
se fossero mancanti).

**Compito: il modello di baseline personale.** La classe `BaselineModel`
mantiene il pool storico dei vettori di feature del paziente (con un tetto
massimo, FIFO) insieme all'id della sessione di provenienza di ciascuno (per
poterlo rimuovere se quella sessione viene cancellata dall'archivio).
Calcola media e covarianza campionarie del pool, e classifica un nuovo
vettore in base alla sua **distanza di Mahalanobis al quadrato** da quel
centro.

**Compito: calibrare le soglie in modo statisticamente corretto.** Poiché
media e covarianza sono *stimate* dal pool (non note a priori), la distanza
di Mahalanobis al quadrato non segue una distribuzione χ² come si potrebbe
ingenuamente assumere — usarla come tale avrebbe gonfiato il tasso di falsi
RED fino a circa il 20% con 5 sessioni, contro l'1% atteso. Il modello usa
invece la teoria dell'**Hotelling T² a due campioni** (un solo nuovo punto
contro un pool stimato): sotto normalità, la distanza riscalata segue una
distribuzione F con gradi di libertà legati al numero di sessioni e al numero
di feature, da cui si derivano correttamente le soglie GREEN/YELLOW e
YELLOW/RED ai quantili configurati (95° e 99°). Se il pool è troppo piccolo
perché la F abbia gradi di libertà validi, la classificazione resta NEUTRAL.

**Compito: orchestrare l'intera analisi di una sessione.** La classe
`HrvAnalyser.analyse()` è il punto d'ingresso: rileva i picchi, calcola gli
intervalli RR, applica il controllo qualità, calcola le metriche HRV, il
colormap locale (per la visualizzazione), classifica la sessione contro la
baseline (che esclude sempre la sessione corrente stessa), **aggiorna e
persiste la baseline** con il nuovo vettore (a meno che non sia RED e la
configurazione lo escluda), e restituisce stato, colormap e dizionario di
feature arricchito (incluso il motivo di un eventuale NEUTRAL e
l'avanzamento verso il completamento della baseline).

**Compito: gestire una baseline illeggibile senza distruggerla.**
`_load_model()` distingue esplicitamente, tramite lettura in modalità
`strict`, un file di baseline **assente** (pool vuoto legittimo) da un file
**presente ma non decifrabile** (baseline "danneggiata"): nel secondo caso lo
scoring viene disabilitato e soprattutto il file non viene mai riscritto,
per non perdere per sempre lo storico del paziente sovrascrivendolo con un
pool vuoto.

**Compito: mantenere coerente la baseline con l'archivio.**
`remove_session_from_baseline()` viene invocata quando l'utente cancella una
sessione dall'archivio: rimuove dal pool il vettore associato a quell'id di
sessione (se presente — le baseline nel vecchio schema senza id non lo
supportano) e ripersiste il modello, così una sessione "sparita" dall'archivio
smette anche di influenzare i giudizi futuri.

**Compito: colormap locale.** `_build_local_colormap()` calcola, per ogni
intervallo RR della sessione, uno z-score robusto (basato su mediana e MAD,
con fallback alla deviazione standard se il MAD è nullo) rispetto alla
distribuzione degli RR di *quella stessa sessione*, e lo traduce in un codice
verde/ambra/rosso/neutro usato solo per la visualizzazione (vedi Parte 1,
§7).

**Compito: persistenza dei risultati.** `save_session_results()` scrive su
disco, cifrati, la colormap (`.colormap.npy`) e il dizionario di feature
(`.features.json`) di ogni sessione analizzata.

## `data_layer.py` — profili, cifratura e formato clinico EDF

**Compito: derivare e gestire la chiave di cifratura del profilo.**
`EncryptionManager` deriva una chiave AES a 128 bit dalla password
dell'utente tramite PBKDF2-HMAC-SHA256 con 200.000 iterazioni e un salt
casuale specifico del profilo, poi usa AES-GCM (cifratura autenticata) per
cifrare/decifrare i dati. Alla creazione viene verificata la password
provando a decifrare un piccolo "sentinel" cifrato in fase di setup
(`.keycheck`): se la password è sbagliata, la decifratura fallisce
immediatamente con un errore di autenticazione, invece di produrre dati
corrotti silenziosamente.

**Compito: modellare un profilo paziente.** Il dataclass `Profile` distingue
esplicitamente `alias` (etichetta non identificativa, visibile prima del
login) da `name` (nome reale, che vale l'alias finché il profilo non viene
sbloccato con la password).

**Compito: elencare i profili senza conoscere la password.**
`ProfileManager.list_profiles()` scansiona la cartella profili e mostra solo
l'alias di ciascuno, ignorando (con un avviso di log) le cartelle
**incomplete** — create ma non finite, ad esempio per un'interruzione durante
la creazione — che altrimenti al login solleverebbero un errore non gestito e
manderebbero in crash l'app.

**Compito: creare un profilo in modo atomico.** `create_profile()` costruisce
l'intero profilo (cartella sessioni, `profile.json` con l'alias in chiaro,
materiale crittografico, `identity.json` con il nome reale cifrato) in una
cartella temporanea nascosta, e la rinomina alla posizione definitiva **solo a
struttura completa**; qualunque eccezione durante la costruzione fa
ripulire la cartella temporanea, così non resta mai un profilo mezzo fatto.

**Compito: sbloccare un profilo dopo il login.** `unlock()` decifra
`identity.json` (se presente) per recuperare il nome reale del paziente; sui
profili "legacy" (creati prima di questa distinzione, dove il nome era già in
chiaro) il nome resta semplicemente uguale all'alias.

**Compito: individuare una directory in RAM.** `volatile_tmp_dir()` restituisce
`/dev/shm` se disponibile e scrivibile, per far transitare l'ECG in chiaro
dalla RAM invece che dalla scheda SD quando possibile (vedi anche
`EDFWriter.save` e la lettura in `archive_screen.py`).

**Compito: cancellazione sicura di un file temporaneo.** `shred()` sovrascrive
il contenuto di un file con byte casuali prima di cancellarlo — una
mitigazione contro il recupero banale dei dati, non una garanzia assoluta su
supporti con wear-levelling (SSD/SD), come dichiarato esplicitamente nel
codice.

**Compito: scrivere il tracciato in formato clinico EDF+.**
`EDFWriter.save()` scrive il segnale (campionato a 500 Hz, normalizzato in
[-1, 1], esplicitamente etichettato in "unità arbitrarie" e non in millivolt
calibrati, perché il sensore usato non fornisce un'uscita calibrata) in un
file EDF+ temporaneo (in RAM se possibile), lo legge come bytes, lo sovrascrive
e cancella (`shred`), poi cifra i bytes risultanti e li scrive **in modo
atomico** nella cartella sessioni del profilo. Rifiuta esplicitamente
registrazioni troppo corte (meno di 500 campioni) sollevando un errore
gestito a monte.

## `secure_store.py` — cifratura a riposo dei dati derivati

**Compito: nascondere anche la lunghezza dei dati, non solo il contenuto.**
Prima di cifrare qualunque payload JSON o array numpy, `_pad()` lo imbottisce
a un multiplo fisso di 4096 byte (preceduto da un piccolo header con la
lunghezza reale, per poterlo poi rimuovere con `_unpad`); senza questo
accorgimento, la sola dimensione su disco di `*.colormap.npy` o
`*.features.json` (un byte per battito) rivelerebbe il numero di battiti — e
quindi, indirettamente, la frequenza cardiaca media — a chiunque avesse
accesso alla scheda SD, anche senza mai riuscire a decifrare nulla. I file
scritti prima dell'introduzione di questo meccanismo vengono riconosciuti
(assenza del "magic" iniziale) e restituiti così come sono, senza bisogno di
migrazione.

**Compito: scrittura atomica e resistente a un'interruzione di corrente.**
`atomic_write()` scrive su un file temporaneo, forza la scrittura sul
supporto fisico (`fsync` sul file *e* sulla directory che lo contiene — senza
il secondo, la voce di directory stessa potrebbe andare persa), e solo allora
rinomina il file temporaneo al posto di quello definitivo.

**Compito: leggere/scrivere JSON e array numpy cifrati.** `write_json`/
`read_json` e `write_npy`/`read_npy` incapsulano cifratura, padding e
scrittura atomica per i due formati usati nel progetto. La lettura ha un
parametro `strict`: normalmente un file assente, corrotto o cifrato con
un'altra chiave viene silenziosamente sostituito da un valore di default,
comportamento comodo ovunque un dato mancante sia normale; ma per la
baseline (dove confondere "assente" con "corrotta" causerebbe la perdita
silenziosa dello storico del paziente) si usa `strict=True`, che solleva
esplicitamente `DecryptError` invece di degradare.

## `logging_setup.py` — diagnostica applicativa

**Compito: dare una traccia a un dispositivo senza console.** `setup()`
configura un unico logger radice con due destinazioni: la console (stderr) e
un file a rotazione (max 1 MB, 3 copie di backup) scritto accanto ai dati
dell'applicazione, così un malfunzionamento in campo — su un Raspberry Pi
senza schermo di debug collegato — lascia comunque una traccia consultabile.
La funzione è idempotente (chiamate ripetute non duplicano gli handler) e
tollera un filesystem pieno o in sola lettura senza impedire l'avvio dell'app.

## `main.py` — punto d'ingresso e finestra principale

**Compito: avviare l'applicazione.** `main()` configura il logging, crea
l'applicazione Qt con lo stile e il foglio di stile globali definiti in
`theme.py`, mostra il dialogo di selezione profilo e, solo se l'utente si
autentica con successo, apre la finestra principale a schermo intero.

**Compito: orchestrare le due schermate.** `MainWindow` contiene uno
`QStackedWidget` con `AcquisitionScreen` (pagina 0) e `ArchiveScreen` (pagina
1), più una `TabBar` in basso per passare dall'una all'altra; quando si passa
all'archivio, ne viene ricaricato l'elenco sessioni (`load()`), così eventuali
sessioni appena registrate compaiono subito.

**Compito: chiusura pulita.** `ESC` chiude l'app (comodo in sviluppo su PC);
`closeEvent` chiama esplicitamente `shutdown()` sulla schermata di
acquisizione prima di accettare la chiusura, per fermare in modo ordinato i
thread seriale e di elaborazione.

## `profile_dialog.py` — schermata di login

**Compito: mostrare l'elenco profili e raccogliere la password.**
`ProfileSelectionDialog` elenca i profili (solo alias, prima
dell'autenticazione), fa inserire la password, e alla conferma prova a
costruire un `EncryptionManager` per il profilo selezionato.

**Compito: distinguere i tipi di fallimento del login.** Una password errata
(`InvalidTag`, cioè fallimento dell'autenticazione AES-GCM) mostra "Password
errata" e permette di riprovare; un profilo con file crittografici
mancanti/illeggibili (`OSError`/`ValueError`, ad esempio `salt.bin`
mancante) mostra invece "Profilo danneggiato" — prima di questa gestione era
un errore non catturato che chiudeva l'intera applicazione.

**Compito: sblocco del nome reale dopo il successo.** Una volta autenticato,
chiama `ProfileManager.unlock()` per decifrare il nome reale del paziente e
lo rende disponibile al resto dell'app tramite `get_result()`.

## `theme.py` — sistema di design (nessuna logica applicativa)

**Compito: centralizzare ogni colore in un unico posto.** Definisce l'intera
palette come costanti nominate (superfici, testo, accento, e i tre colori
semantici GREEN/YELLOW/RED più NEUTRAL), così nessun colore esadecimale è
sparso nei file delle schermate.

**Compito: fornire il foglio di stile globale.** `global_stylesheet()`
applica uno stile coerente a tutti i widget Qt standard (pulsanti, campi di
testo, liste, scrollbar, tooltip), con aree di tocco minime di 44px e
contorni di focus visibili, requisiti per un dispositivo touch clinico.

**Compito: fornire funzioni di stile per componente.** Una funzione per
ciascun elemento visivo riutilizzato (card, pillola di stato, pulsante di
registrazione, tag di stato, chip metrico, ecc.), così ogni schermata compone
lo stile senza mai scrivere hex a mano.

## `widgets.py` — il grafico ECG riutilizzabile

**Compito: disegnare il tracciato ECG.** `EcgPlotWidget` incapsula un
`pyqtgraph.PlotWidget` configurato con l'asse Y fissato in un range coerente
con il segnale normalizzato, l'unità dichiarata "u.a." (non mV), e ottimizzato
per disegnare solo i punti in vista (`clipToView`) senza applicare alcun
sotto-campionamento (che altrimenti farebbe cambiare visibilmente la
morfologia dell'onda a zoom diversi).

**Compito: modalità live (rolling buffer).** `append_samples()` fa scorrere
un buffer circolare a lunghezza fissa (la finestra visibile in secondi),
gestendo correttamente anche il caso limite di un blocco più lungo della
finestra stessa.

**Compito: modalità statica (revisione di una sessione salvata).**
`show_static()` mostra l'intera registrazione, ma limita la finestra
temporale visibile a un intervallo fisso (`ARCHIVE_WINDOW_S`) su cui si può
solo scorrere orizzontalmente, non zoomare: questo mantiene sempre limitato
(e quindi fluido, anche su Raspberry Pi) il numero di punti disegnati, e dà
una scala temporale costante, "tipo carta millimetrata ECG".

**Compito: disegnare le bande colorate per intervallo RR.**
`add_rr_bands()` disegna, dietro al tracciato, una regione traslucida colorata
per ogni intervallo RR classificato, **fondendo in un'unica regione grafica**
le sequenze di intervalli consecutivi con lo stesso codice colore (invece di
disegnarne dozzine separate), per mantenere leggero il ridisegno durante lo
scorrimento. È tollerante a un piccolo disallineamento fra la lunghezza della
colormap salvata e gli RR ricalcolati da un EDF eventualmente quantizzato.

## `acquisition_screen.py` — acquisizione dal vivo

**Compito: leggere la seriale in un thread dedicato.** `_SerialThread` gira
in continuazione, apre la porta (auto-rilevata tramite `find_port`), legge
riga per riga e interpreta i due tipi di messaggio (`L,` per lo stato
elettrodi, `D,` per i campioni); in caso di porta non trovata o connessione
persa, segnala l'errore e riprova a intervalli regolari **senza consumare CPU
al 100%** (un difetto presente prima di questa versione, dove un errore di
lettura veniva ingoiato da un ciclo stretto senza pausa).

**Compito: rilevare e ricostruire campioni persi durante la registrazione.**
`_ingest()` confronta il contatore di sequenza ricevuto con l'ultimo noto: se
manca un piccolo numero di campioni (fino a 5, cioè 10 ms a 500 Hz), li
ricostruisce per interpolazione lineare (vedi `signal_processing.
interpolate_gap`); oltre quella soglia considera l'interruzione reale e non
inventa dati fisiologici che non ci sono, limitandosi a conteggiare i
campioni persi.

**Compito: elaborare il segnale in tempo reale su un secondo thread.**
`_ProcessingThread` consuma il buffer circolare condiviso, applica il filtro
digitale a blocchi, alimenta il rilevatore di picchi R campione per campione
(scartando il transitorio di warm-up iniziale), tiene conto degli eventuali
campioni scartati per overflow del buffer nell'indice temporale, calcola la
frequenza cardiaca corrente e mette il blocco filtrato più la HR aggiornata in
una coda consumata dalla UI. Se la UI non riesce a tenere il passo, i blocchi
in eccesso vengono scartati con un avviso di log periodico (non a ogni
occorrenza, per non intasare il log) — il tracciato può avere dei piccoli
buchi visivi, ma l'analisi finale userà comunque i campioni grezzi completi
salvati dal thread seriale.

**Compito: costruire l'interfaccia della schermata.** `AcquisitionScreen`
assembla la barra superiore (marchio, profilo, orologio, indicatore
elettrodi), la card del tracciato ECG, e la colonna laterale fissa con la
card della frequenza cardiaca, il selettore di durata (libera / 2 minuti), il
banner del risultato e il grande pulsante di registrazione.

**Compito: distinguere le cause di un pulsante disabilitato.**
`_refresh_lod_indicator()` (chiamato 4 volte al secondo) distingue tre stati —
errore seriale, elettrodi staccati, elettrodi OK — aggiornando lo stile solo
quando lo stato cambia davvero (per non forzare Qt a ricalcolare il foglio di
stile a ogni tick), e abilita il pulsante di registrazione solo con elettrodi
effettivamente connessi.

**Compito: gestire il ciclo di vita di una registrazione.**
`_start_recording()`/`_stop_recording()` avviano/fermano il thread di
elaborazione dedicato alla sessione corrente (un `Event` **nuovo** ad ogni
registrazione, per evitare che un thread precedente non ancora terminato
venga "resuscitato" da un `clear()` del buffer condiviso), gestiscono il
conto alla rovescia (o il cronometro, in modalità libera, con un tetto di
sicurezza a 15 minuti) e aggiornano il testo e lo stile del pulsante.

**Compito: salvare e analizzare la sessione appena registrata.**
`_save_session()` scrive il tracciato grezzo cifrato in EDF+
(`EDFWriter.save`), gestendo esplicitamente il caso di registrazione troppo
breve (meno di 1 secondo, tipicamente un tocco accidentale su STOP) come
errore "morbido" segnalato all'utente e non come crash; poi esegue l'analisi
HRV (`HrvAnalyser.analyse`) usando lo stesso timestamp come id di sessione per
la baseline, salva colormap e feature, e gestisce il caso di baseline non
decifrabile mostrando un messaggio esplicativo invece di uno stato generico.

**Compito: aggiornare il tracciato a schermo senza bloccare la UI.**
`_render_tick()`, chiamato periodicamente da un `QTimer` (circa 25 fps),
svuota la coda dei blocchi filtrati prodotti dal thread di elaborazione e li
appende al grafico, aggiornando anche l'etichetta della frequenza cardiaca.

**Compito: messaggi differenziati per ogni causa di NEUTRAL.**
`_neutral_message()` traduce il motivo tecnico (`neutral_reason`) restituito
dal motore di analisi in un messaggio comprensibile e specifico per
l'operatore (sessione troppo breve, segnale troppo disturbato, baseline in
costruzione con conteggio "X / Y", baseline illeggibile), invece di un
generico "non valutata".

**Compito: arresto ordinato di tutti i thread.** `shutdown()`, chiamato alla
chiusura della finestra, ferma un'eventuale registrazione in corso, segnala
lo stop a entrambi i thread e ne attende l'uscita con timeout, loggando un
avviso se non terminano in tempo.

## `archive_screen.py` — consultazione dell'archivio sessioni

**Compito: ricostruire l'elenco delle sessioni dal filesystem.**
`scan_sessions()` raggruppa per "stem" (nome file senza estensione/suffisso)
i tre file che compongono una sessione (`.edf`, `.colormap.npy`,
`.features.json`), scartando le sessioni prive del file EDF principale, e
ordina il risultato dal più recente.

**Compito: recuperare i confini delle bande RR per il disegno.**
`rr_band_boundaries()` usa preferibilmente gli indici dei picchi R già
salvati nelle feature al momento dell'analisi (`rr_peaks`); solo per sessioni
"legacy" salvate prima che questo campo esistesse, ricalcola i picchi da zero
— un'operazione costosa che per questo viene sempre eseguita fuori dal thread
della UI (vedi `_DecryptThread`).

**Compito: esportare una sessione in chiaro.** `export_session()` scrive
l'EDF decifrato e, se disponibile, le feature decifrate in JSON in chiaro
accanto ad esso, per l'uso con strumenti esterni; la UI chiamante mostra
sempre un avviso esplicito prima di procedere (vedi
`_on_export_clicked`), perché da quel momento il file non è più protetto da
password.

**Compito: disegnare la striscia colorata riassuntiva.**
`ColormapStripWidget` disegna un rettangolo colorato per ciascun intervallo
RR classificato (colore locale, vedi Parte 1 §7), riempiendo con un colore
neutro quando non ci sono dati.

**Compito: mostrare le quattro metriche con tinta di scostamento.**
`MetricsGridWidget` mostra SDNN, RMSSD, pNN50 e frequenza RR media in quattro
card, colorando ciascun valore in base al proprio z-score rispetto alla
baseline (`_tint_color_for_z`): verde/ambra/rosso a seconda di quanto quella
singola metrica, e non solo lo stato complessivo, si discosti dallo storico.

**Compito: disegnare una riga dell'elenco sessioni.** `_SessionRowWidget`
compone data, durata stimata, etichetta di stato colorata, un estratto delle
metriche principali e la striscia colorata in miniatura; distingue un tocco
da un gesto di scorrimento della lista misurando lo spostamento del dito fra
`mousePressEvent` e `mouseReleaseEvent` (una card viene aperta solo se il
dito non si è spostato più di una soglia minima).

**Compito: gestire l'elenco scorrevole delle sessioni.** `SessionListWidget`
costruisce la barra superiore, il conteggio sessioni, e ricostruisce
l'elenco delle card ogni volta che viene richiamato `load()` (ad esempio
quando si passa alla scheda archivio, o dopo una cancellazione).

**Compito: decifrare e preparare una sessione fuori dal thread della UI.**
`_DecryptThread` (un `QThread` dedicato) decifra l'EDF, lo scrive
temporaneamente (in RAM se possibile) per poterlo leggere con la libreria
EDF, lo sovrascrive e cancella subito dopo (`shred`), e — solo se la sessione
ha una colormap — calcola i confini delle bande RR; tutto questo lavoro
potenzialmente lento (incluso l'eventuale ri-rilevamento dei picchi su
sessioni legacy) resta fuori dal thread grafico per non congelare
l'interfaccia.

**Compito: mostrare il dettaglio di una sessione.** `SessionDetailWidget`
compone header (data, stato), la card del tracciato con tre stati possibili
(caricamento, tracciato pronto, errore), la legenda dei colori, la striscia
riassuntiva, la griglia delle quattro metriche, e i pulsanti di esportazione
ed eliminazione; avvia un nuovo `_DecryptThread` ad ogni sessione aperta,
scollegando con cura i segnali di un eventuale thread precedente ancora in
esecuzione, così un risultato ormai obsoleto non può sovrascrivere quello
nuovo.

**Compito: eliminare una sessione in modo coerente.** `_on_delete_clicked()`,
dopo conferma esplicita dell'utente, rimuove **prima** il vettore
corrispondente dalla baseline e **solo se questo riesce** cancella i tre file
della sessione: l'ordine è deliberato, perché cancellare prima i file e
fallire poi l'aggiornamento della baseline lascerebbe un vettore "orfano" e
irrecuperabile nel modello, mentre l'inverso (fallire la baseline e non
toccare i file) lascia i dati coerenti fra loro.

**Compito: orchestrare lista e dettaglio.** `ArchiveScreen` alterna, tramite
uno `QStackedWidget`, fra l'elenco e il dettaglio di una sessione, ricaricando
l'elenco dopo ogni eliminazione.

**Compito: navigazione principale dell'app.** `TabBar` fornisce i due
pulsanti di navigazione (Acquisizione/Archivio) più un pulsante di uscita
sempre raggiungibile — necessario perché l'app gira a schermo intero, senza
alcuna barra del titolo del sistema operativo.

## `create_profile.py` — utility a riga di comando

**Compito: creare un profilo paziente da terminale.** Script standalone che
chiede nome (cifrato), alias opzionale (di default le iniziali, calcolate da
`ProfileManager.default_alias`) e password (richiesta due volte per conferma,
lunghezza minima di 8 caratteri, letta senza eco tramite `getpass`), poi
chiama `ProfileManager.create_profile()`. È il modo previsto per popolare
l'elenco profili prima del primo utilizzo dell'app grafica.

## `requirements.txt` — dipendenze del progetto

Elenca le librerie usate e la loro versione minima: `PyQt5` (interfaccia
grafica), `pyqtgraph` (grafico ECG performante), `pyserial` (comunicazione con
l'Arduino), `scipy` e `numpy` (filtraggio digitale e calcolo numerico),
`cryptography` (cifratura AES-GCM e derivazione chiave PBKDF2), `pyedflib`
(lettura/scrittura del formato clinico EDF+), `pytest` (test).

---

# PARTE 3 — Documentazione hardware del prototipo

Le prime due parti descrivono cosa fa il software e come è costruito. Questa
parte descrive il dispositivo fisico su cui quel software gira: un sistema
embedded multi-nodo racchiuso in un case stampato in 3D (circa 7 × 6 × 3 cm),
che acquisisce l'ECG, lo elabora e presenta l'indice HRV su un display touch.
Come per il software, ogni scelta è documentata insieme al suo trade-off:
questo è un prototipo di ricerca, e i limiti scelti consapevolmente contano
tanto quanto le soluzioni adottate.

## 1. Architettura del sistema

```
[Elettrodi ECG]
       │ segnale analogico (mV)
       ▼
  [AD8232]          amplifica, filtra grossolanamente, rileva lead-off
       │ segnale analogico amplificato (centrato ~Vs/2)
       ▼
[Arduino Nano]      campiona a 500 Hz (ADC 10 bit), serializza
       │ USB seriale 115200 baud
       ▼
[Raspberry Pi 4B]   filtraggio digitale, analisi HRV, display
       │ MIPI DSI
       ▼
 [Display 4.3"]
```

**Piano di alimentazione:**

```
[Batteria Li-Po 3.7V]
       │
  [IP5328P]          boost 3.7V → 5V, fino a 18W
       │ USB-C 5V/3A
       ▼
[Raspberry Pi 4B]
       │ USB-A → USB-C
       ▼
[Arduino Nano]
```

## 2. Componenti principali

### 2.1 Raspberry Pi 4B

| Parametro | Valore |
|---|---|
| SoC | Broadcom BCM2711 |
| CPU | 4× ARM Cortex-A72 @ 1.5 GHz |
| RAM | 8 GB LPDDR4 |
| Alimentazione richiesta | 5 V / 3 A (15 W nominali) |
| Picchi di corrente | fino a ~3.5 A durante boot + display attivo |
| Interfaccia display | MIPI DSI (connettore flat a latch a frizione) |
| Connessione Arduino | USB-A ↔ USB-C |
| Storage | microSD (single point of failure — vedi §11) |

**Criticità energetiche.** Il Pi 4B è particolarmente sensibile
all'undervoltage. Tensioni inferiori a ~4.75 V causano il kernel warning
`"Under-voltage detected!"`, thermal throttling della CPU e, nei casi
peggiori, corruzione della scheda SD durante i picchi di scrittura. Il
modulo IP5328P è stato scelto proprio per garantire la stabilità richiesta
(vedi §3).

**Connettore DSI.** Il latch del connettore MIPI DSI è a frizione, senza
meccanismo di lock positivo. Ogni ciclo di apertura/chiusura del case
sollecita meccanicamente la connessione: prima di ogni presentazione, dopo
l'assemblaggio finale, va verificato che il flat sia correttamente inserito.

### 2.2 Arduino Nano

| Parametro | Valore |
|---|---|
| MCU | ATmega328P (clone CH340 USB-Serial) |
| Frequenza di campionamento ECG | 500 Hz |
| Risoluzione ADC | 10 bit (0–1023) su riferimento 5V → ~4.9 mV/LSB |
| Interfaccia seriale | 115200 baud, protocollo testuale |
| Banda occupata | ~5.5 kB/s su 11.5 kB/s disponibili (~48%) |
| Alimentazione | 5V da USB (proveniente dal Pi) |

**Protocollo seriale** (lo stesso descritto lato firmware in Parte 2):

```
D,<seq>,<val>\n    campione ECG (seq = contatore 0..255, val = 0..1023)
L,0\n              elettrodi collegati
L,1\n              elettrodi staccati (lead-off)
```

Il contatore di sequenza `seq` è ciò che permette al Pi di accorgersi di
campioni persi: un buco nella numerazione segnala che il tempo è avanzato
senza dati, e consente l'interpolazione o lo scarto consapevole invece di
uno scivolamento silenzioso della base dei tempi.

**Il margine di banda è sottile.** Il 48% di occupazione della banda
seriale non lascia moltissimo margine. Il firmware chiama
`Serial.availableForWrite()` prima di trasmettere: se il buffer TX da 64
byte è pieno, il campione viene saltato (con avanzamento comunque del
contatore) invece di bloccare il loop di acquisizione e introdurre jitter
nella base dei tempi — la stessa logica già descritta per il firmware in
Parte 2.

### 2.3 Sensore ECG AD8232

| Parametro | Valore |
|---|---|
| Tipo | Single-Lead Heart Rate Monitor Front-End |
| Guadagno | ~100× (regolabile) |
| Tensione di ingresso ECG tipica | 1–3 mV |
| Tensione di uscita | centrata attorno a Vs/2 (~2.5 V su 5V) |
| Filtro integrato | passa-alto 0.5 Hz + passa-basso integrato |
| Rilevamento lead-off | sì, via pin LOD+ e LOD− |
| Alimentazione | 3.3–5V (alimentato da Arduino) |

**Offset DC e transitorio di filtraggio.** L'AD8232 emette il segnale
centrato attorno a Vs/2. All'accensione, il filtro digitale passa-alto del
Pi (0.5 Hz) reagisce a questo gradiente DC con un transitorio la cui
ampiezza è paragonabile a quella di un'onda R, e che si esaurisce in circa
3 secondi — è esattamente la ragione, spiegata anche in Parte 1 e nel
commento di `config.py`, per cui i primi 3 secondi di ogni acquisizione
vengono scartati (`FILTER_WARMUP_S = 3.0`) prima di iniziare a cercare i
picchi R.

**Lead-off.** Il rilevamento di elettrodi staccati è gestito a livello
firmware (Arduino) e trasmesso al Pi via protocollo seriale (`L,0` /
`L,1`). Il distacco degli elettrodi durante la registrazione non interrompe
l'acquisizione: l'artefatto resta visibile sul tracciato e viene gestito dal
filtro artefatti del software (Parte 2, `analysis_engine.py`).

**Margine sul rapporto T/R dopo filtraggio.** Il filtro digitale
passa-banda 0.5–40 Hz del Pi attenua l'onda T più dell'onda R. Il rapporto
T/R filtrato scende al ~13%, contro la soglia di rilevamento del picco R al
60%: un margine di 47 punti percentuali, sufficiente a evitare che l'onda T
venga scambiata per un doppio battito.

### 2.4 Display Waveshare 4.3" MIPI DSI

| Parametro | Valore |
|---|---|
| Diagonale | 4.3 pollici |
| Risoluzione | 800 × 480 px |
| Interfaccia | MIPI DSI (Display Serial Interface) |
| Touch | capacitivo |
| Connessione | cavo flat FFC 15-pin 1.0 mm pitch |
| Consumo tipico | ~1–2 W |

**Cavo flat DSI.** Il cavo forma un loop ad ampio raggio (circa 4 cm di
diametro) all'interno del case per gestire l'eccesso di lunghezza nello
spazio ridotto. La geometria a loop è preferita a pieghe secche perché non
induce fatica meccanica sul cavo in condizioni statiche: il loop è in
posizione fissa e non viene sollecitato durante il normale utilizzo (nessun
ciclo di flessione ripetuta).

**Vulnerabilità EMI.** Il cavo flat DSI è il componente più vulnerabile
alle interferenze elettromagnetiche del sistema, perché non schermato e
posizionato in prossimità del convertitore switching IP5328P. La
mitigazione adottata è descritta al §4.

### 2.5 Batteria Li-Po 5000 mAh

| Parametro | Valore |
|---|---|
| Formato | 955465 (9.5 × 54 × 65 mm) |
| Capacità nominale | 5000 mAh |
| Tensione nominale | 3.7 V |
| Tensione di carica massima | 4.2 V |
| Corrente di scarica massima continua | ~4.5 A (sufficiente per i 15 W richiesti) |
| Energia totale | ~18.5 Wh |
| Autonomia stimata a carico pieno (15 W) | ~60–70 minuti |
| Autonomia a carico medio (10–12 W) | ~90–100 minuti |

**Utilizzo.** La batteria viene portata sempre a piena carica prima della
presentazione. Non è previsto l'utilizzo in ricarica contemporanea
all'erogazione, il che elimina il rischio di dip di tensione legati a quel
modo operativo su alcuni moduli IP5328P.

**Espansione.** Lo spazio fisico nel case prevede un margine sufficiente ad
accomodare un lieve gonfiore della cella (normale nei cicli di carica),
senza che questo generi pressioni meccaniche sui componenti adiacenti.

**Cutoff di scarica.** Il modulo IP5328P gestisce la soglia minima di
scarica della cella: sotto tale soglia il sistema si spegne. Il
comportamento del Pi 4B a questo spegnimento va verificato in fase di
collaudo (vedi §11 — è il rischio più concreto per la scheda SD).

### 2.6 Modulo Boost IP5328P

| Parametro | Valore |
|---|---|
| Chip | IP5328P |
| Topologia | DC-DC switching boost |
| Tensione di ingresso | 3.0–4.2 V (da Li-Po) |
| Tensione di uscita | 5 V regolata |
| Potenza massima erogata | 18 W (Power Delivery) |
| Corrente massima erogata | ~3.6 A a 5 V |
| Frequenza di switching tipica | 300 kHz – 1 MHz (da datasheet) |
| Efficienza tipica | ~85–92% a carico pieno |

**Sorgente di disturbo EMI.** Il convertitore switching genera disturbi
elettromagnetici concentrati alla frequenza di switching e ai suoi
armonici; l'induttore del boost è il componente radiante principale (campo
magnetico variabile). La frequenza di switching è ben distinta dai 50 Hz di
rete, ma i suoi armonici possono comunque interferire con il cavo flat DSI
e con le linee dati seriali. La mitigazione è descritta al §4.

## 3. Sistema di alimentazione

**Catena di potenza:**

```
Li-Po 3.7V (5000 mAh)
    │
    ├─── IP5328P (boost 3.7V → 5V, 18W max)
    │         │
    │         └─── USB-C → Raspberry Pi 4B (5V / 3A)
    │                           │
    │                           └─── USB-A → Arduino Nano (5V, ~100–200 mA)
    │                                             │
    │                                             └─── AD8232 (3.3–5V, ~3.5 mA)
    │
    └─── Display Waveshare (alimentato via DSI dalla Pi)
```

**Budget di potenza:**

| Componente | Consumo tipico | Consumo picco |
|---|---|---|
| Raspberry Pi 4B (carico medio, display attivo) | ~8–10 W | ~15 W |
| Arduino Nano + AD8232 | ~0.5 W | ~1 W |
| Display Waveshare 4.3" | ~1–2 W | ~2 W |
| **Totale** | **~10–12 W** | **~18 W** |

Il modulo IP5328P eroga fino a 18 W: il margine rispetto al picco teorico è
minimo, ma sufficiente, perché i picchi simultanei di tutti i componenti
sono improbabili in condizioni operative normali.

**Stabilità dell'alimentazione.** Il Pi 4B richiede una tensione stabile
≥ 4.75 V. Il modulo IP5328P garantisce la regolazione anche con la batteria
a bassa carica (≥ 3.0 V). La verifica dell'assenza di undervoltage sotto
carico reale (display attivo + acquisizione ECG contemporanea) fa parte del
collaudo finale prima della presentazione.

## 4. Compatibilità elettromagnetica (EMC)

**Sorgenti di disturbo nel sistema:**

| Sorgente | Tipo di disturbo | Vittima principale |
|---|---|---|
| IP5328P (switching) | irradiato + condotto, 300 kHz–1 MHz | cavo flat DSI, Arduino |
| Cavi elettrodo ECG | antenna per disturbo di rete 50 Hz | AD8232 |
| Rete elettrica (ambiente) | condotto su linea di ricarica | IP5328P |

**Strategia di mitigazione — due livelli, hardware e software.**

*Livello hardware — Shielding Baffle (gabbia di Faraday parziale).* Uno
schermo direzionale a forma di "L" (parete laterale + tetto) è interposto
fisicamente tra il modulo IP5328P (sorgente) e il cavo flat DSI (vittima).
La geometria a "L" è deliberata: non racchiude completamente il modulo,
lasciando liberi i lati opposti per la ventilazione termica.

- **Struttura:** cartoncino rigido o foglio di plastica come substrato isolante.
- **Conduttore:** nastro adesivo in rame sul lato esterno.
- **Isolamento interno:** il lato rivolto verso il modulo resta isolato, per
  evitare cortocircuiti accidentali con i pin del modulo.
- **Messa a terra:** il nastro di rame è connesso via cavo al pin GND della
  scheda millefori (Arduino). Poiché Arduino e Pi condividono la massa
  tramite USB, esiste un piano di riferimento comune a bassa impedenza.

**Perché la messa a terra è indispensabile, non opzionale.** Alle alte
frequenze, la propagazione del disturbo è dominata dalla line-of-sight:
interrompendo il percorso diretto tra induttore e cavo flat si abbatte il
campo irradiato sul componente vittima. Senza la messa a terra, però, lo
schermo si comporterebbe esso stesso come un'antenna risonante,
amplificando il disturbo invece di attenuarlo.

*Livello software — filtro notch digitale.* Il segnale acquisito
dall'AD8232 passa attraverso un filtro IIR notch a 50 Hz (Q = 30)
implementato sul Pi (`signal_processing.py`, Parte 2): è la risposta
digitale allo stesso problema che lo shield risolve nell'analogico. La
coerenza tra le due misure — schermatura fisica a 300 kHz–1 MHz e filtro
digitale a 50 Hz — riflette il fatto che le sorgenti di disturbo sono
distinte: il convertitore switching da un lato, la rete elettrica
dell'ambiente dall'altro. Nessuna delle due misure, da sola, coprirebbe
entrambe le sorgenti.

**Routing differenziale dei cavi.** I cavi sono instradati per minimizzare
l'accoppiamento tra linee di potenza e linee di segnale: il cavo dati
Pi → Arduino passa nella zona superiore del case, separata dalle linee di
potenza; il cavo di alimentazione Modulo → Pi passa sotto il display,
schermato dalla propria calza; il cavo flat DSI è protetto dallo Shielding
Baffle descritto sopra.

## 5. Cablaggio e routing

**Mappa dei cavi:**

| Cavo | Percorso | Lunghezza | Note |
|---|---|---|---|
| USB-C (alimentazione Pi) | IP5328P → Pi 4B | 10–15 cm | passa sotto il display; calza schermata; supporto 3A obbligatorio |
| USB-A ↔ USB-C (dati+alimentazione Arduino) | Pi 4B → Arduino Nano | 10–15 cm | zona superiore del case; calza schermata |
| FFC 15-pin 1.0 mm (display DSI) | Pi 4B → Waveshare 4.3" | 30 cm | loop ad ampio raggio (~4 cm Ø); protetto da Shielding Baffle |
| Cavi elettrodo ECG | AD8232 → elettrodi | lunghezza libera | schermatura non presente; agiscono da antenne per il 50 Hz di rete (mitigato dal notch digitale) |
| Cavo GND shield | Schermatura rame → GND millefori | corto | saldato al piano di massa comune Pi/Arduino |

**Geometria del cavo flat DSI.** Il cavo forma un loop quasi completo
(circa 300° di arco, ~4 cm di diametro) che assorbe la lunghezza in eccesso
senza pieghe secche. Il raggio di curvatura è ampiamente superiore al
limite di fatica tipico per cavi FFC standard (5–10 volte il passo, cioè
~5–10 mm: il raggio del loop qui è ~20 mm). Il cavo resta in posizione
statica e non subisce flessioni cicliche durante l'utilizzo.

## 6. Isolamento meccanico e sicurezza elettrica

**Distanziale batteria / modulo IP5328P.** Il PCB del modulo IP5328P è
posizionato sopra la cella Li-Po. I pin e i componenti sul ventre del PCB
potrebbero, in assenza di protezione, perforare meccanicamente l'involucro
in Mylar della cella, causando un cortocircuito interno con rischio di
thermal runaway. La misura adottata è uno strato di materiale isolante
(nastro biadesivo spugnoso o foglio di plastica/FR4) interposto tra il
ventre del modulo e la superficie superiore della cella, con spessore
sufficiente a mantenere la separazione anche sotto le vibrazioni di
trasporto.

**Isolamento del cavo flat dalla batteria.** Il loop del cavo flat DSI
transita in prossimità dell'involucro della batteria. Il punto di contatto
tra il bordo longitudinale del cavo (taglio netto) e la superficie della
cella è protetto dallo stesso distanziale isolante che separa il modulo
dalla cella, eliminando il rischio di abrasione del Mylar.

**Sicurezza della cella Li-Po:**

- La cella non viene mai caricata durante il funzionamento operativo del prototipo.
- Lo spazio fisico nel case prevede margine per un lieve gonfiore della cella.
- Non è presente alcun circuito di protezione esterno (BMS) oltre a quello
  integrato nel modulo IP5328P: si raccomanda di non scaricare completamente
  la cella né di lasciarla in carica incustodita.

## 7. Gestione termica

**Sorgenti di calore:**

| Componente | Potenza dissipata tipica | Temperatura limite |
|---|---|---|
| BCM2711 (Pi 4B) | ~4–5 W a pieno carico | 85°C (junction) |
| IP5328P | ~1.5–2.5 W (efficienza ~88%) | ~125°C (junction, dato tipico) |
| Batteria Li-Po | riscaldamento per corrente di scarica | 45–50°C (massima ammissibile) |

**Raspberry Pi 4B — nessun dissipatore.** Per una sessione fino a 30
minuti, l'inerzia termica del package BCM2711 è sufficiente a prevenire il
thermal throttling. La resistenza termica junction-to-air senza dissipatore
è ~30–40°C/W; a 4–5 W di dissipazione e con temperatura ambiente di 25°C, la
temperatura di giunzione stimata *a regime* sarebbe ~145–225°C — sopra il
limite, ma il regime non viene raggiunto entro 30 minuti proprio grazie
all'inerzia termica del package. Una sessione estesa oltre i 60 minuti
richiederebbe un dissipatore.

**IP5328P — ventilazione naturale.** Il case ha feritoie sul lato destro, e
lo Shielding Baffle (§4) è aperto su due lati (superiore e lato opposto
alle feritoie) proprio per non ostacolare il flusso d'aria attorno
all'induttore e al chip. Il calore generato dal convertitore viene quindi
smaltito per convezione naturale verso le feritoie, limitando il
trasferimento di calore verso la batteria sottostante.

**Batteria Li-Po — protezione termica.** Il distanziale isolante tra
modulo e batteria (§6) riduce anche la conduzione termica diretta; il
layout verticale del sistema mantiene una separazione fisica tra la
sorgente calda (IP5328P) e la cella, sensibile alla temperatura.

## 8. Case stampato in 3D

| Parametro | Valore |
|---|---|
| Dimensioni esterne | ~7 × 6 × 3 cm |
| Materiale | PLA o PETG (presunto da colore e aspetto) |
| Colore | verde brillante |
| Feritoie di ventilazione | lato destro |
| Apertura | coperchio rimovibile (no cerniera) |

**Considerazioni meccaniche:**

- Le feritoie sono sul lato destro, coerentemente con la posizione del
  modulo IP5328P e del relativo punto di massima generazione di calore.
- Il coperchio non ha un meccanismo di lock positivo (chiusura a pressione
  o a vite, da verificare): ogni ciclo di apertura/chiusura può quindi
  sollecitare le connessioni interne, in particolare il connettore DSI
  (vedi §2.1).
- Le dimensioni impongono un layout a stacking verticale: Pi 4B sul fondo,
  batteria e modulo IP5328P sopra, display e Arduino sul piano superiore.

## 9. Catena del segnale ECG — lato hardware

Questa sezione completa, dal lato hardware, la catena di elaborazione già
descritta software-side in Parte 1 (§5) e Parte 2 (`signal_processing.py`):

```
Corpo umano
    │ segnale differenziale ~1–3 mV
    ▼
Elettrodi (3 poli: RA, LA, RL/shield)
    │ cavi non schermati → antenne per disturbo comune 50 Hz
    ▼
AD8232
    ├─ amplificazione differenziale (~100×): segnale ECG 100–300 mV
    ├─ filtro integrato (rimozione parziale della deriva di base)
    ├─ riferimento centrato a Vs/2 (~2.5 V su 5V)
    └─ rilevamento lead-off (soglia di corrente sugli elettrodi)
    │ segnale analogico single-ended su pin OUTPUT
    ▼
Arduino Nano — pin analogico A0
    ├─ ADC 10 bit, 0–5V → risoluzione 4.9 mV/LSB
    ├─ campionamento a 500 Hz (timer via micros(), non delay())
    └─ serializzazione → USB 115200 baud
    │
    ▼ USB (isolamento galvanico implicito)
    │
Raspberry Pi 4B
    ├─ deserializzazione (SerialThread)
    ├─ Filtro IIR digitale in cascata SOS:
    │    ├─ Notch 50 Hz (Q=30): rimuove disturbo di rete
    │    └─ Butterworth passa-banda 0.5–40 Hz (ord. 4): rimuove deriva DC e rumore EMG
    ├─ Rilevatore picchi R (soglia adattiva 0.6×max, refrattario 200 ms)
    └─ Analisi HRV → display
```

**Perché USB e non SPI/I2C tra Pi e Arduino.** La scelta offre isolamento
galvanico implicito nei cavi USB schermati commerciali, robustezza del
protocollo (USB gestisce autonomamente rilevamento errori e ritrasmissione)
e assenza di linee di segnale non schermate che attraversano il case — con
SPI/I2C, le linee di clock e dati avrebbero attraversato lo spazio interno
senza protezione. Il limite è la latenza intrinseca della serializzazione:
a 500 Hz e 115200 baud, ogni campione impiega ~0.2–0.3 ms dall'ADC
all'arrivo sul Pi, del tutto accettabile per un'applicazione HRV (che
lavora su scale di tempo di centinaia di millisecondi, non di
microsecondi).

## 10. Distinta base (BOM)

| Quantità | Componente | Specifiche chiave |
|---|---|---|
| 1 | Raspberry Pi 4B | 8 GB RAM |
| 1 | Arduino Nano | clone CH340 USB-Serial |
| 1 | Sensore ECG AD8232 | SparkFun o compatibile |
| 1 | Display Waveshare 4.3" | MIPI DSI, touch capacitivo, 800×480 |
| 1 | Batteria Li-Po | 5000 mAh, formato 955465 |
| 1 | Modulo Boost IP5328P | 5V / 18W, Power Delivery |
| 1 | Cavo FFC 15-pin 1.0 mm | 30 cm, per display DSI |
| 1 | Cavo USB-C ↔ USB-C | 10–15 cm, supporto 3A, per alimentazione Pi |
| 1 | Cavo USB-A ↔ USB-C | 10–15 cm, per Arduino |
| 1 | Rotolo nastro adesivo in rame | conduttivo, per Shielding Baffle |
| 1 | Cartoncino rigido o foglio plastica | substrato isolante per Shielding Baffle |
| 1 | Nastro biadesivo spugnoso | distanziale isolante batteria/modulo |
| 1 | Scheda millefori | mounting e punto GND per shield |
| 1 | Case 3D stampato | ~7×6×3 cm, con feritoie laterali |
| 3 | Elettrodi ECG | con cavi e clip (set RA/LA/RL) |

## 11. Limiti noti e rischi residui

**Rischi hardware:**

| Rischio | Probabilità | Impatto | Mitigazione |
|---|---|---|---|
| Corruzione scheda SD a power-off improvviso (cutoff batteria) | Media | Alta (no boot) | Test di scarica fino al cutoff; backup immagine SD; overlayfs software |
| Failure connettore DSI dopo cicli open/close | Bassa | Alta (no display) | Verifica connessione dopo assemblaggio finale; limitare i cicli |
| Thermal throttling Pi 4B oltre i 60 minuti | Media | Media (rallentamento) | Non critico per sessioni ≤ 30 min; aggiungere dissipatore per uso prolungato |
| Perforazione involucro Li-Po da pin modulo | Bassa (con distanziale) | Altissima (thermal runaway) | Distanziale isolante obbligatorio tra modulo e cella |
| Interferenza EMI su cavo flat DSI | Bassa (con shield) | Media (artefatti video) | Shielding Baffle + messa a terra |

**Limiti intrinseci del prototipo:**

- **Nessuna calibrazione in mV.** L'AD8232 non fornisce un'uscita
  calibrata: il segnale è in unità ADC normalizzate [0, 1023]. Non è
  possibile ricavare valori assoluti in millivolt senza una calibrazione
  hardware specifica — coerente con quanto già dichiarato in Parte 1 e nei
  metadati del file EDF+ esportato (`data_layer.py`, Parte 2).
- **Singola derivazione.** Il sistema acquisisce solo la derivazione I
  (RA−LA): non è possibile costruire un ECG a 12 derivazioni, né rilevare
  eventi che si manifestano principalmente su derivazioni diverse.
- **Elettrodi non schermati.** I cavi elettrodo agiscono da antenne per il
  disturbo di modo comune a 50 Hz. La mitigazione è il filtro notch
  digitale, non la schermatura fisica: in ambienti con forte disturbo di
  rete (edifici datati, apparecchiature industriali vicine), il CMRR
  dell'AD8232 potrebbe non bastare da solo.
- **Scheda SD come single point of failure.** Non c'è ridondanza di
  storage: un guasto della SD durante la presentazione rende il sistema non
  avviabile — il rischio più concreto tra quelli elencati sopra, ed è per
  questo che compare due volte in questo documento (qui e in §2.1/§2.5).
