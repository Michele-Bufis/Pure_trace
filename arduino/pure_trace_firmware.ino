/*
 * Pure-Trace — Firmware Arduino (ECG front-end)
 * ----------------------------------------------
 * Da caricare con Arduino IDE su Arduino Nano (o Uno).
 *
 * Sensore assunto: AD8232 (SparkFun Single Lead Heart Rate Monitor).
 * Cambia i pin qui sotto se usi un altro collegamento.
 *
 * PROTOCOLLO SERIALE (deve combaciare con pure_trace/ui/acquisition_screen.py):
 *   - "D,<s>,<v>\n"  campione ECG: <s> = contatore 0..255 (wrap), <v> = analogRead
 *                    0..1023  (inviato a 500 Hz). Il contatore permette al PC di
 *                    rilevare campioni persi e ricostruire la base dei tempi.
 *   - "L,0\n"    elettrodi OK (leads-on)
 *   - "L,1\n"    elettrodi staccati (leads-off)
 *   Baud: 115200   ·   Frequenza di campionamento: 500 Hz
 *
 * COLLEGAMENTI AD8232 -> Arduino:
 *   AD8232 OUTPUT -> A0        (segnale ECG analogico)
 *   AD8232 LO+    -> D10       (leads-off detection +)
 *   AD8232 LO-    -> D11       (leads-off detection -)
 *   AD8232 3.3V   -> 3V3
 *   AD8232 GND    -> GND
 *   (SDN non collegato / a 3.3V per tenere il sensore acceso)
 *
 * NOTA alimentazione: l'AD8232 lavora a 3.3V. Alimentalo dal pin 3V3 della
 * Nano, NON dai 5V. Gli ingressi LO+/LO- restano comunque letti come digitali.
 */

// ---- Configurazione pin (modificabile) ----
const int PIN_ECG      = A0;   // uscita analogica del sensore
const int PIN_LO_PLUS  = 10;   // leads-off +
const int PIN_LO_MINUS = 11;   // leads-off -

// ---- Tempistica: 500 Hz => un campione ogni 2000 microsecondi ----
const unsigned long SAMPLE_INTERVAL_US = 2000UL;  // 1.000.000 / 500
unsigned long nextSampleUs = 0;

// ---- Stato leads-off, per inviare "L," solo quando serve ----
int           lastLeadsOff = -1;     // -1 = mai inviato
unsigned long lastLodMs    = 0;
const unsigned long LOD_REFRESH_MS = 100;  // ribadisci lo stato almeno ogni 100 ms

// ---- Contatore di sequenza dei campioni (0..255, wrap automatico) ----
byte sampleSeq = 0;

void setup() {
  Serial.begin(115200);

  // Gli ingressi di leads-off dell'AD8232 vanno letti come digitali.
  pinMode(PIN_LO_PLUS,  INPUT);
  pinMode(PIN_LO_MINUS, INPUT);

  nextSampleUs = micros();
}

void loop() {
  unsigned long now = micros();

  // Scatta solo quando è ora del prossimo campione.
  // Il cast a (long) gestisce correttamente l'overflow di micros() (~70 min).
  if ((long)(now - nextSampleUs) >= 0) {
    nextSampleUs += SAMPLE_INTERVAL_US;

    // Se per backpressure seriale (il PC legge lentamente) siamo rimasti
    // indietro di più di un intervallo, NON inviamo una raffica di campioni
    // "di recupero": falserebbe la base dei tempi addensando campioni con lo
    // stesso istante reale. Risincronizziamo al tempo corrente.
    //
    // I campioni così saltati DEVONO far avanzare il contatore di sequenza:
    // altrimenti il PC riceve numeri contigui e conclude che non manca nulla,
    // mentre il tempo reale è avanzato. Il buco resterebbe invisibile proprio
    // nel caso che il contatore esiste per rilevare, e gli intervalli RR
    // calcolati come indice/fs risulterebbero falsati in silenzio.
    if ((long)(now - nextSampleUs) >= (long)SAMPLE_INTERVAL_US) {
      unsigned long lag = now - nextSampleUs;
      sampleSeq += (byte)(lag / SAMPLE_INTERVAL_US);   // wrap a 256 voluto
      nextSampleUs = now + SAMPLE_INTERVAL_US;
    }

    // --- 1) Stato elettrodi (leads-off) ---
    // L'AD8232 porta HIGH LO+ o LO- quando un elettrodo si stacca.
    int leadsOff = (digitalRead(PIN_LO_PLUS) == HIGH ||
                    digitalRead(PIN_LO_MINUS) == HIGH) ? 1 : 0;

    unsigned long nowMs = millis();
    if (leadsOff != lastLeadsOff || (nowMs - lastLodMs) >= LOD_REFRESH_MS) {
      lastLeadsOff = leadsOff;
      lastLodMs    = nowMs;
      Serial.print("L,");
      Serial.println(leadsOff);   // 0 = OK, 1 = staccati
    }

    // --- 2) Campione ECG ---
    int value = analogRead(PIN_ECG);   // 0..1023 (10 bit)

    // Se il buffer di trasmissione non ha spazio per l'intera riga (max 11 byte,
    // "D,255,1023\n"), Serial.print BLOCCA finché non si libera, ritardando il
    // prossimo analogRead e introducendo jitter nella base dei tempi. Meglio
    // saltare il campione: il contatore avanza comunque, così il PC vede il buco
    // e non interpola dati inventati.
    if (Serial.availableForWrite() >= 12) {
      Serial.print("D,");
      Serial.print(sampleSeq);         // contatore 0..255 (wrap), per rilevare perdite
      Serial.print(',');
      Serial.println(value);
    }
    sampleSeq++;
  }
}
