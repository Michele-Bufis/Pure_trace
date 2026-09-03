# Pure-Trace — Complete Project Documentation

> Research prototype for the acquisition and analysis of single-lead ECG signal,
> with patient status classification against a personal physiological baseline.
> **This is not a medical device and must not be used for diagnostic purposes.**

This document is divided into three parts:

- **PART 1** — a theoretical explanation of the project, its purpose, and the
  choices made, with no reference to code. It explains *what* the system does
  and *why* it was designed this way.
- **PART 2** — a technical explanation organized by file and by task, with
  direct references to classes and functions. It explains *how* the software
  is implemented.
- **PART 3** — hardware documentation for the physical prototype: components,
  power system, electromagnetic compatibility, mechanical/electrical safety,
  thermal management, the hardware side of the signal chain, bill of
  materials, and residual risks. It explains *what the software in Part 2
  actually runs on*, and under what constraints and trade-offs it was built.

---

# PART 1 — Theoretical overview of the project

## 1. What Pure-Trace is

Pure-Trace is a complete system (hardware + firmware + desktop application)
that acquires a single-lead ECG trace from a patient, processes it in real
time to extract heart rate and heart rate variability (HRV), and — after a
learning period — compares every new recording against the patient's own
**personal physiological baseline**, flagging whether the observed
parameters fall within that individual's normal range or deviate from it.

The project is designed to run on a **Raspberry Pi with an 800×480 touch
screen**, connected via USB to an **Arduino Nano** that reads an **AD8232**
ECG sensor (SparkFun Single Lead Heart Rate Monitor). The interface is
therefore designed for touch, "kiosk-style" use, with no keyboard or mouse,
in a setting similar to a small outpatient or research device.

It is explicitly **a research prototype**: it does not provide a diagnosis,
it is not calibrated to clinical millivolts, and its function is to detect
*deviations relative to the patient themself* (the patient is their own
reference point), not to establish absolute pathological thresholds.

## 2. The overall flow, from electrode to screen

1. The electrodes on the patient are connected to the AD8232, which
   amplifies and analog-filters the cardiac signal and outputs it as an
   analog voltage, together with a digital "electrode disconnected"
   (leads-off) signal.
2. The Arduino Nano samples this signal at 500 Hz and sends it over USB
   serial to the Raspberry Pi, along with the electrode status and a
   sequence counter that makes it possible to notice if any sample is lost
   along the way.
3. The desktop application (Python/PyQt5) reads the serial stream, digitally
   filters it to remove mains noise and slow drift, detects heartbeats
   (R-peaks), and computes heart rate in real time, displaying the scrolling
   trace on screen.
4. When the operator stops (or the time limit for) the recording, the raw
   trace is saved in a standard clinical format (EDF+), encrypted, and
   analyzed offline to extract heart rate variability metrics.
5. These metrics are compared against the patient's personal baseline (if
   sufficiently populated), and the session is given a label: within normal
   range, mild deviation, out of baseline, or "not scored" with a specific
   reason.
6. The session becomes part of the patient's archive, viewable on a second
   screen where the trace and numeric values can be reviewed, and the
   recording can be exported in plaintext or deleted.

## 3. Why a personal baseline, and not standard population thresholds

Heart rate variability metrics (how much the interval between one heartbeat
and the next varies, beat by beat) are highly individual: what's "normal"
for one person may not be for another, even at the same age and under the
same conditions. Pure-Trace therefore does not use fixed thresholds taken
from population tables; instead, session after session, it builds a
**personal statistical model** in feature space (mean heart rate, SDNN,
RMSSD, pNN50). A new session is then judged on how far it deviates, in this
multi-dimensional space, from its own historical center of gravity — a
measure called the **Mahalanobis distance**, which also accounts for how the
different metrics co-vary with one another across that specific patient's
history.

For this approach to be statistically honest, at least five "long" sessions
must already be recorded before the system starts giving a verdict: below
that threshold the model doesn't have enough data to reliably estimate its
own natural variability, and the session is marked as "baseline still being
built" rather than being given a label.

## 4. What the GREEN / YELLOW / RED / NEUTRAL traffic light means

Every "long" session (at least 60 seconds) with sufficient signal quality
receives, once the baseline is ready, one of four states:

- **GREEN** — the parameters fall within the patient's usual historical
  variability.
- **YELLOW** — an intermediate deviation: the session deviates from the
  individual norm, but not extremely.
- **RED** — the session deviates markedly from the personal baseline.
- **NEUTRAL** — no verdict could be given, for one of these distinct reasons
  (shown explicitly to the operator, not generically as an "error"): the
  recording is too short, the signal is too noisy (too many artifacts), the
  baseline is still being built, or the baseline file turns out to be
  unreadable.

This distinction between the causes of a NEUTRAL result is a deliberate
design choice: conflating "baseline still incomplete" with "noisy signal"
would send the operator looking for a problem (electrodes, cables) that
doesn't exist, when in reality all that's needed is to record a few more
sessions.

It's also worth noting that a RED session still, by default, contributes to
the future baseline (this is configurable): the idea is that the baseline
should represent the patient's natural variability over time, fluctuations
included, not just their "good days."

## 5. What is measured: heart rate variability metrics

Starting from the intervals between successive heartbeats (RR intervals),
the system computes four standard HRV metrics:

- **Mean heart rate** (derived from the mean RR interval).
- **SDNN** — standard deviation of the RR intervals: how much, overall, the
  heart rhythm oscillates over the course of the recording.
- **RMSSD** — root mean square of successive differences between RR
  intervals: mainly sensitive to the variability component linked to the
  parasympathetic nervous system, beat by beat.
- **pNN50** — percentage of pairs of successive beats that differ by more
  than 50 milliseconds: another indicator of short-term variability.

To be physiologically meaningful, SDNN/RMSSD/pNN50 require recordings of at
least 60 seconds; below that threshold only mean heart rate is reported.

## 6. Signal quality and artifact rejection

Not every detected heartbeat is reliable: movement, imperfect electrode
contact, or double-counting can produce RR intervals that are "impossible"
or otherwise anomalous relative to their immediate context. Before computing
any metric, the system:

- discards intervals outside the plausible physiological range (between 30
  and 180 beats per minute);
- compares each interval against the median of a small neighborhood of
  nearby beats, and excludes those that deviate too much from it (an
  isolated artifact can't "sneak itself through" this way, because the local
  median is robust up to several consecutive artifacts, and is never
  computed including the beat currently being judged);
- requires a minimum number of valid beats and a maximum fraction of
  artifacts for a session to be considered scorable; otherwise it receives
  the NEUTRAL state with the reason "insufficient quality," inviting the
  operator to repeat the measurement.

This quality-control mechanism is distinct from, and independent of,
classification against the baseline: its purpose is to ensure "good signal
is being compared with good signal."

## 7. The colored trace: two levels of reading

On the archive screen, below each session's ECG trace, a colored strip is
drawn beat by beat. It's important to distinguish two different levels of
coloring present in the system, which answer different questions:

- **Local session coloring** (the one drawn on the strip and overlaid on the
  trace): shows how much each individual RR interval deviates from the
  *typical variability internal to that same recording*. It's an indicator
  of "how regular the rhythm was during these few minutes," for purely
  visual purposes, and requires no historical baseline.
- **Overall session status** (the GREEN/YELLOW/RED/NEUTRAL traffic light
  described above, shown as a label and as the card's border color): this,
  instead, is the verdict — computed once for the entire session — of how
  much that session as a whole deviates from the patient's *historical*
  baseline.

The two can very well give different answers: a session can have an
internally very regular rhythm (an all-green strip) but a mean value that is
still anomalous relative to the patient's history (RED status), or vice
versa.

## 8. Privacy and protection of patient data

Since this is sensitive health data destined to live on an SD card that
could potentially be removed from the device, data protection was treated as
a first-class requirement, not an afterthought:

- **Every patient profile is password-protected.** The password is never
  stored: a slow key-derivation function with a high iteration count (to
  resist offline password-guessing attempts) derives from it an encryption
  key specific to that profile.
- **The patient's real name is never written to disk in plaintext.** On the
  profile-selection screen, *before* the password is entered, only a
  non-identifying alias is shown (by default, the initials, e.g. "M. R." for
  "Mario Rossi"). The full name is encrypted and only retrieved after a
  successful login.
- **The raw ECG trace, HRV metrics, and baseline are all encrypted at
  rest** with a key derived from the profile's password. None of these
  files can be read by pulling the SD card without knowing the password.
- **Even the size of encrypted files is masked**, by padding them to fixed
  blocks before encryption: otherwise, from the size of a file alone (which
  depends on the number of recorded heartbeats), one could infer the
  patient's average heart rate without ever decrypting anything.
- **The plaintext ECG signal, when it must necessarily touch the
  filesystem** (the library used for the EDF+ clinical format can only write
  to a file), is written to RAM (tmpfs) whenever possible instead of to the
  SD card, and in any case the temporary file is overwritten with random
  data before being deleted, so that no recoverable trace is left on the
  physical storage medium.
- **Exporting a session** (for use with external clinical tools such as
  EDFbrowser) deliberately produces an **unencrypted** file: the user is
  explicitly warned before proceeding, because from that point on
  protection becomes their responsibility (e.g., a USB drive).

## 9. Operational robustness, built for "field" use

The device is meant to be used autonomously, often with no console or
technician available if something goes wrong. Several design choices reflect
this:

- If the Arduino isn't found, or the USB connection drops mid-recording, the
  app reports it clearly and retries automatically, explicitly
  distinguishing a connection problem (cable/port) from a problem with
  electrodes disconnected from the patient: these are two situations that
  call for different actions from the operator.
- If samples are lost during serial transmission (due to congestion, an
  unstable cable, etc.), the system notices thanks to a sequence counter
  sent by the firmware, and reconstructs small gaps by interpolation, so
  that the calculation of intervals between heartbeats isn't thrown off by
  time that has silently "slipped."
- Creating a new profile is **atomic**: it's built entirely inside a hidden
  temporary folder and made visible only once complete, so an interruption
  halfway through (power loss, abnormal shutdown) never leaves a "half-made"
  profile that would crash the app on the next login.
- Saving any file (session, baseline, metrics) is likewise atomic: it's
  written to a temporary file, forced onto physical storage, and only then
  renamed into place of the final file — a power dip mid-write therefore
  never leaves a truncated, unreadable file where a good one should be.
- The system explicitly distinguishes "I have no data" from "I have data but
  it's corrupted": if the baseline file exists but can't be decrypted, the
  app does not treat it as an empty baseline (which would be silently
  overwritten, permanently losing the patient's history), but instead
  raises the error and suspends scoring until the problem is resolved
  manually.
- A persistent application log is kept on file (with rotation, so it doesn't
  grow indefinitely), designed so that a malfunction in the field — on a
  Raspberry Pi with no debug screen attached — still leaves a traceable
  record.

## 10. The user interface

The app has only two main screens, designed for a small touchscreen
(800×480) with no physical keyboard:

- **Acquisition**: shows the live ECG trace, current heart rate, electrode
  status, a recording-duration selector (free-running, or a fixed 2
  minutes), and the large start/stop button. At the end, it shows the
  evaluation result.
- **Archive**: lists all saved sessions for the active patient, most recent
  first, each with date, duration, status (color), and the main metrics in
  summary. Tapping a session opens its detail view: the full (scrollable)
  trace, the beat-by-beat colored strip, the four numeric metrics, and
  buttons to export or delete the recording.

The visual language is deliberately "clinical but approachable": light
surfaces with a faint teal tint, high-contrast text, a single accent color
for actions, and only the three green/amber/red colors reserved exclusively
for clinical status, never used for anything else. Controls have a minimum
touch-target size designed for touch use (not for a mouse).

A disclaimer ("research prototype, not a medical device") is shown
explicitly on the login screen.

## 11. What it does NOT do (stated limitations)

- It does not provide a clinical diagnosis: it only detects relative
  deviations from a personal baseline, not medical conditions.
- The signal is not calibrated to standard clinical millivolts: the sensor
  used does not provide a calibrated output, and this is stated explicitly,
  including in the exported file's metadata, so that anyone opening it with
  clinical tools isn't led to believe they're looking at a calibrated
  trace.
- Secure file deletion on SD/SSD media with wear leveling is not 100%
  guaranteed by simple overwriting: it's a mitigation, not an absolute
  cryptographic guarantee.

---

# PART 2 — Code guide, by file and by task

The project is organized as a Python package `pure_trace`, a subpackage
`pure_trace.ui` for the graphical interface, a separate Arduino sketch, and
a CLI utility script. Below is every file, broken down into mini-paragraphs
by the task it performs.

## `pure_trace_firmware.ino` — Arduino firmware (sensor front-end)

**Task: define the serial protocol.** The firmware sends two kinds of text
lines terminated by `\n`: `D,<seq>,<val>` for each ECG sample (`seq` a
wrapping 0–255 counter, `val` the raw ADC reading, 0–1023), and `L,0` /
`L,1` to report electrodes connected or disconnected, respectively. The baud
rate is fixed at 115200, the sampling rate at 500 Hz.

**Task: precise timing at 500 Hz.** Sampling doesn't use `delay()`; instead
it compares `micros()` against a next target instant (`nextSampleUs`),
incremented by 2000 µs each cycle. The cast to `long` in the comparison
correctly handles `micros()` overflow after about 70 minutes.

**Task: resynchronizing without falsifying time.** If the loop accumulates a
delay of more than one sampling interval (because the PC is reading the
serial port slowly), the firmware doesn't catch up on the backlog by sending
all the missed samples at once (which would artificially compress multiple
samples into the same real instant); instead it jumps the target clock
forward and **still advances the sequence counter** by the number of
skipped samples — it's exactly this counter that lets the PC-side software
notice the gap and handle it, instead of watching it silently disappear.

**Task: reading electrode status.** It digitally reads the AD8232's LO+ and
LO- pins (high when an electrode comes loose) and sends an `L,` line
whenever the state changes, as well as periodically every 100 ms as a
keep-alive, even if the state hasn't changed.

**Task: not blocking sampling when the serial link is full.** Before writing
the sample line, it checks that the serial transmit buffer has enough room
(`Serial.availableForWrite()`); if it doesn't, **it skips sending that
sample** (but still increments the sequence counter) instead of letting
`Serial.print` block the microcontroller while it waits, which would
introduce jitter into the timebase of every subsequent sample.

## `config.py` — centralized system parameters

**Task: data paths.** `DATA_DIR`/`PROFILES_DIR` are anchored to the
package's location (not to the current working directory), so the app
always writes to the same place regardless of how it's launched (e.g., from
systemd). Overridable via the `PURE_TRACE_DATA` environment variable.

**Task: serial and sampling parameters.** `SERIAL_PORT` (auto-detected if
`None`), `SERIAL_BAUD`, `SERIAL_RETRY_S`, `SAMPLING_RATE` (500 Hz).

**Task: digital filter parameters.** Notch frequency and Q (50 Hz, Q=30,
for mains power); bandpass band and order (currently **0.05–40 Hz**, order
4). The low cutoff was lowered from an earlier 0.5 Hz specifically because,
per the in-code comment, at 0.5 Hz the ST segment came out visibly
distorted. A separate comment elsewhere in the same file (on
`FILTER_WARMUP_S`) still refers to "the 0.5 Hz highpass" — that comment is
now stale and should be updated to match the current 0.05 Hz value; a unit
test (`test_digital_filter.py::test_sample_by_sample_matches_batch`) also
still hardcodes a `0.5` Hz reference filter for its cross-check, which is
worth revisiting for the same reason.

**Task: QRS onset/offset parameters.** A separate set of parameters governs
measuring the width of the QRS complex once an R-peak has already been
anchored: a ±100 ms search window around the peak (`QRS_SEARCH_S`) within
which the local slope is tracked outward from the peak; the edge of the
complex is taken to be the point where that slope drops below 5% of the
steepest slope found near the R-peak (`QRS_SLOPE_RATIO`) — i.e. where the
trace is judged to have returned to isoelectric. The resulting duration is
only accepted if it falls between 60 and 150 ms (`QRS_MIN_MS`/`QRS_MAX_MS`);
outside that range it's treated as a detection artifact rather than a
genuinely unusual QRS width. *(`analysis_engine.py`'s source wasn't
available for this documentation pass — this paragraph is reconstructed
from `config.py`'s parameters and their comments, not from the function
that actually consumes them, so the exact function name and how the
resulting width is used downstream — a stored feature, a quality gate, or
purely diagnostic — could not be confirmed here.)*

**Task: R-peak detection parameters.** Refractory period (200 ms), local
amplitude estimation window, threshold fraction relative to the local
maximum, number of RR intervals used for the heart rate moving average, and
the filter *warm-up* duration (3 s) discarded because the highpass filter,
starting from a zero state on an input with a DC offset, produces a
transient as large as an R-wave.

**Task: recording durations.** Standard "long" duration (2 minutes), a
safety ceiling for free-running duration (15 minutes), the minimum threshold
below which HRV is not computed (60 s).

**Task: artifact-rejection parameters.** Physiological RR range, relative
deviation threshold from the local median, width of the median window (11,
sized to tolerate up to 5 consecutive artifacts without being "won over" by
them), minimum number of valid beats, and maximum tolerated fraction of
artifacts for a session to be considered scorable.

**Task: baseline/Mahalanobis parameters.** Minimum number of long sessions
before scoring begins, covariance regularization ridge (to guarantee
invertibility), maximum capacity of the feature pool (FIFO), whether RED
sessions still enter the baseline, and the two threshold quantiles (95th and
99th) used to calibrate the GREEN/YELLOW and YELLOW/RED boundaries.

**Task: display-only parameters.** Z-score thresholds for local RR dynamics
coloring and for tinting the numeric metric values.

## `serial_port.py` — automatic Arduino port detection

**Task: finding the right port on any operating system.** Instead of a
hardcoded port (which, on a system other than the development one, simply
doesn't exist, causing the serial thread to fail silently), `find_port()`
searches the available USB ports for one whose VID matches one of the known
serial converters fitted to the most common Arduino boards (CH340/CH341,
official Arduino, FTDI, CP210x); if no VID matches, it falls back to a
second criterion based on known patterns in the device name (`ttyUSB`,
`ttyACM`, `cu.usbserial`, etc.). An explicitly configured preferred port
wins if it's actually present, but is ignored (and doesn't block startup)
if configured but absent.

## `signal_processing.py` — real-time signal processing

**Task: reconstructing lost samples.** `interpolate_gap()` fills in missing
samples between two known values by linear interpolation, keeping the
timebase (index/frequency) used to compute RR intervals consistent.

**Task: a thread-safe producer/consumer queue.** `CircularBuffer` is a
bounded-length FIFO queue shared between the serial thread (which writes)
and the processing thread (which reads); on overflow it drops the oldest
samples, but **counts** how many it drops (`take_dropped()`), so the
consumer can realign its own time index instead of letting it silently
drift. `read(n)` never blocks and never pads: it returns however many
samples are actually available (up to `n`), popped destructively from the
front of the queue.

**Task: digital filtering of the signal.** `DigitalFilter` applies a notch
filter (for 50 Hz mains noise) and a 0.5–40 Hz bandpass filter (to remove
baseline drift and high-frequency noise) in cascade, keeping the filter's
internal state (`zi`) between calls both in sample-by-sample mode
(`process_sample`, for the live stream) and in block mode (`process_array`,
much faster, used for offline analysis of an entire recording, giving the
same numerical result as N sequential calls).

**Task: real-time R-peak detection.** `RPeakDetector` maintains an adaptive
threshold equal to a fraction of the maximum observed in a recent moving
window (implemented with a **monotonic deque** to get the maximum in
constant time instead of recomputing it over the whole window every time),
and enforces a minimum refractory period between two consecutive detections
to avoid double-counting the same beat. It also exposes a current heart
rate, computed as a moving average of the most recent RR intervals.
Detection also stays disabled until the amplitude window itself has filled
to at least a quarter of its length (`window_size // 4`) — a second,
distinct warm-up from the 3-second filter transient discarded offline
(`config.FILTER_WARMUP_S`): this one exists simply because a mostly-empty
window has no meaningful maximum to threshold against yet, independent of
how settled the filter itself is.

## `mock_device.py` — protocol-compatible mock device (DEBUG=1)

**Task: emitting the exact same line protocol as the real Arduino.**
`MockSerialDevice` is consumed through `readline()` just like a pyserial
connection, and emits the identical two message types the firmware sends:
`D,<seq>,<val>\n` samples and `L,0\n` lead-off status, with the sequence
counter wrapping at 256 (`& 0xFF`) exactly as the firmware does. This keeps
the serial parser, buffering, DSP, and UI on the same code path whether the
data comes from hardware or from the mock.

**Task: a plausible, deliberately imperfect synthetic ECG.** `_ecg_adc_value()`
builds a 72 bpm waveform as a sum of Gaussian "bumps" for the P, Q, R, S,
and T waves (positioned and scaled by hand, with the R-wave the dominant
one), plus **two intentional imperfections**: a slow 0.25 Hz sinusoid for
baseline wander, and a small 50 Hz sinusoid standing in for mains
interference. The 50 Hz component in particular means the notch filter has
something real to remove even when running against the mock — useful for
noticing at a glance, without any hardware attached, whether the filter
pipeline is actually doing something.

**Task: a known limitation of the mock.** `readline()` always returns
`L,0` (electrodes connected); the mock has no code path for reporting
`L,1` (lead-off). It's therefore useful for exercising recording, live
rendering, filtering, and the archive, but **cannot** be used to test the
UI's handling of a disconnected-electrode state — that still requires the
physical AD8232.

**Task: fast, deterministic tests.** `realtime=False` skips the
`time.sleep(1/sample_rate)` between lines, so a test can drain thousands of
samples instantly instead of waiting in real time.



**Task: sample-accurate offline R-peak detection.**
`detect_rpeak_indices()` filters the entire recording in one pass, discards
the initial warm-up transient, finds threshold crossings using the same
`RPeakDetector` used in real time, then **snaps each detection to the true
apex of the R-wave** (`_snap_to_apex`): the detector actually fires on the
first sample that crosses the threshold, not on the peak, and this lag
varies beat by beat because R-wave amplitude is modulated by breathing — an
effect that would leak directly into RMSSD, the metric that measures
variation between successive beats (measured: an error of roughly +5% on
RMSSD is reduced to +1% with this correction). The search window used for
this correction is 50 ms (`config.APEX_SEARCH_S`) — wide enough to cover
the QRS upstroke (~40 ms) but comfortably under the 200 ms refractory
period, so it can never latch onto the following beat.

**Task: artifact rejection.** `clean_rr_mask()` implements the logic
described in Part 1: physiological range plus deviation from the local
median, with the interval being judged always excluded from the computation
of its own reference median. `quality_ok()` decides whether the session, as
a whole, is clean enough to be scored.

**Task: preparing the feature vector.** `features_to_vector()` converts the
dictionary of HRV metrics into a 4-dimensional numeric vector `[mean heart
rate, SDNN, RMSSD, pNN50]`, correctly handling the case where some metrics
are legitimately zero (without mistakenly discarding them as if they were
missing).

**Task: the personal baseline model.** The `BaselineModel` class maintains
the patient's historical pool of feature vectors (with a maximum cap, FIFO)
together with the id of the session each one came from (so it can be
removed if that session is deleted from the archive). It computes the
sample mean and covariance of the pool, and classifies a new vector based on
its **squared Mahalanobis distance** from that center.

**Task: calibrating the thresholds correctly, statistically.** Since the
mean and covariance are *estimated* from the pool (not known a priori), the
squared Mahalanobis distance does not follow a χ² distribution as one might
naively assume — using it as such would have inflated the false-RED rate to
roughly 20% with 5 sessions, against an intended 1%. The model instead uses
**two-sample Hotelling T²** theory (a single new point against an estimated
pool): under normality, the rescaled distance follows an F distribution
with degrees of freedom tied to the number of sessions and the number of
features, from which the GREEN/YELLOW and YELLOW/RED thresholds are
correctly derived at the configured quantiles (95th and 99th). If the pool
is too small for the F distribution to have valid degrees of freedom, the
classification stays NEUTRAL.

**Task: orchestrating the full analysis of a session.** The
`HrvAnalyser.analyse()` class method is the entry point: it detects the
peaks, computes the RR intervals, applies the quality check, computes the
HRV metrics, the local colormap (for display), classifies the session
against the baseline (which always excludes the current session itself),
**updates and persists the baseline** with the new vector (unless it's RED
and the configuration excludes it), and returns the status, colormap, and an
enriched feature dictionary (including the reason for any NEUTRAL result and
progress toward completing the baseline).

**Task: handling an unreadable baseline without destroying it.**
`_load_model()` explicitly distinguishes, via a `strict`-mode read, a
**missing** baseline file (a legitimately empty pool) from a file that's
**present but not decryptable** (a "damaged" baseline): in the second case,
scoring is disabled and, crucially, the file is never rewritten, so as not
to permanently lose the patient's history by overwriting it with an empty
pool.

**Task: keeping the baseline consistent with the archive.**
`remove_session_from_baseline()` is invoked when the user deletes a session
from the archive: it removes the vector associated with that session id
from the pool (if present — baselines in the old schema without ids don't
support this) and re-persists the model, so that a session "removed" from
the archive also stops influencing future verdicts.

**Task: local colormap.** `_build_local_colormap()` computes, for every RR
interval in the session, a robust z-score (based on median and MAD, falling
back to standard deviation if the MAD is zero) relative to the distribution
of RR intervals *within that same session*, and translates it into a
green/amber/red/neutral code used purely for display (see Part 1, §7).

**Task: persisting results.** `save_session_results()` writes the encrypted
colormap (`.colormap.npy`) and feature dictionary (`.features.json`) of
every analyzed session to disk.

## `data_layer.py` — profiles, encryption, and the clinical EDF format

**Task: deriving and managing the profile's encryption key.**
`EncryptionManager` derives a 128-bit AES key from the user's password using
PBKDF2-HMAC-SHA256 with 600,000 iterations and a profile-specific random
salt, then uses AES-GCM (authenticated encryption) to encrypt/decrypt data.
On creation, the password is verified by attempting to decrypt a small
"sentinel" encrypted during setup (`.keycheck`): if the password is wrong,
decryption fails immediately with an authentication error, instead of
silently producing corrupted data.

**Task: modelling a patient profile.** The `Profile` dataclass explicitly
distinguishes `alias` (a non-identifying label, visible before login) from
`name` (the real name, which equals the alias until the profile is unlocked
with the password).

**Task: listing profiles without knowing the password.**
`ProfileManager.list_profiles()` scans the profiles folder and shows only
each one's alias, ignoring (with a log warning) **incomplete** folders —
created but never finished, for instance due to an interruption during
creation — which would otherwise raise an unhandled error at login and
crash the app.

**Task: creating a profile atomically.** `create_profile()` builds the
entire profile (sessions folder, `profile.json` with the plaintext alias,
cryptographic material, `identity.json` with the encrypted real name) in a
hidden temporary folder, and renames it to its final location **only once
the structure is complete**; any exception during construction cleans up
the temporary folder, so a half-made profile is never left behind.
(`profile.json` also carries a `schema` tag, currently `"profile-v2"`,
reserved for future format migrations.)

**Task: unlocking a profile after login.** `unlock()` decrypts
`identity.json` (if present) to retrieve the patient's real name; on
"legacy" profiles (created before this distinction existed, where the name
was already stored in plaintext) the name simply stays equal to the alias.

**Task: locating a RAM directory.** `volatile_tmp_dir()` returns `/dev/shm`
if available and writable, so the plaintext ECG can transit through RAM
instead of the SD card whenever possible (see also `EDFWriter.save` and the
read path in `archive_screen.py`).

**Task: securely deleting a temporary file.** `shred()` overwrites a file's
contents with random bytes before deleting it — a mitigation against
trivial data recovery, not an absolute guarantee on wear-leveling media
(SSD/SD), as explicitly stated in the code.

**Task: writing the trace in clinical EDF+ format.** `EDFWriter.save()`
writes the signal (sampled at 500 Hz, normalized to [-1, 1], explicitly
labeled in "arbitrary units" rather than calibrated millivolts, because the
sensor used doesn't provide a calibrated output) to a temporary EDF+ file
(in RAM if possible), reads it back as bytes, overwrites and deletes it
(`shred`), then encrypts the resulting bytes and writes them **atomically**
into the profile's sessions folder. It explicitly rejects recordings that
are too short (fewer than 500 samples), raising an error handled upstream.
(One coupling worth flagging: the `500` written into the EDF signal header
is a literal, not a read of `config.SAMPLING_RATE` — the two would need to
be kept in sync by hand if the sampling rate is ever changed.)

## `secure_store.py` — encryption at rest for derived data

**Task: hiding data length, not just content.** Before encrypting any JSON
payload or numpy array, `_pad()` pads it to a fixed multiple of 4096 bytes
(preceded by a small header carrying the real length, so it can later be
removed with `_unpad`); without this precaution, the on-disk size alone of
`*.colormap.npy` or `*.features.json` (one byte per heartbeat) would reveal
the number of heartbeats — and therefore, indirectly, the average heart
rate — to anyone with access to the SD card, without ever needing to decrypt
anything. Files written before this mechanism was introduced are recognized
(by the absence of the initial "magic" bytes) and returned as-is, with no
migration needed.

**Task: atomic writes resilient to a power interruption.**
`atomic_write()` writes to a temporary file, forces the write onto physical
storage (`fsync` on the file *and* on the containing directory — without
the latter, the directory entry itself could be lost), and only then
renames the temporary file into place of the final one.

**Task: reading/writing encrypted JSON and numpy arrays.**
`write_json`/`read_json` and `write_npy`/`read_npy` wrap encryption, padding,
and atomic writes for the two formats used in the project. Reading has a
`strict` parameter: normally a missing, corrupted, or wrong-key-encrypted
file is silently replaced with a default value — convenient behavior
wherever missing data is normal — but for the baseline (where conflating
"missing" with "corrupted" would cause the silent loss of the patient's
history) `strict=True` is used, which explicitly raises `DecryptError`
instead of degrading gracefully.

## `logging_setup.py` — application diagnostics

**Task: giving a console-less device a trail.** `setup()` configures a
single root logger with two destinations: the console (stderr) and a
rotating file (max 1 MB, 3 backup copies) written next to the application's
data, so that a malfunction in the field — on a Raspberry Pi with no debug
screen attached — still leaves a traceable record. The function is
idempotent (repeated calls don't duplicate handlers) and tolerates a full or
read-only filesystem without preventing the app from starting.

## `main.py` — entry point and main window

**Task: starting the application.** `main()` configures logging, creates the
Qt application with the style and global stylesheet defined in `theme.py`,
and shows the profile-selection dialog. Cancelling that dialog exits
immediately via `sys.exit(0)` — no main window is ever built. On successful
login, the main window opens in one of three distinct modes, not a single
"full-screen": a fixed 800×480 window (not fullscreen) when `DEBUG=1`, to
compare the layout against the physical device's proportions on an
ordinary desktop; maximized (not fullscreen) under WSL, because WSLg can
render a fullscreen Qt window without forwarding pointer input to it; and
true fullscreen otherwise, for the physical appliance.

**Task: orchestrating the two screens.** `MainWindow` contains a
`QStackedWidget` with `AcquisitionScreen` (page 0) and `ArchiveScreen` (page
1), plus a `TabBar` at the bottom to switch between them; when switching to
the archive, its session list is reloaded (`load()`), so any just-recorded
sessions appear immediately. Live monitoring on the acquisition screen
starts immediately when the main window is constructed
(`self._acq.start_monitoring()`), before the operator has even switched to
that tab — the ECG trace and heart rate are always live in the background,
not something the operator has to opt into.

**Task: clean shutdown.** `ESC` quits the app (handy during development on a
PC); `closeEvent` explicitly calls `shutdown()` on the acquisition screen
before accepting the close event, to stop the serial and processing threads
in an orderly way.

## `profile_dialog.py` — login screen

**Task: showing the profile list and collecting the password.**
`ProfileSelectionDialog` lists the profiles (aliases only, before
authentication), takes the password, and on confirmation attempts to build
an `EncryptionManager` for the selected profile.

**Task: distinguishing types of login failure.** A wrong password
(`InvalidTag`, i.e. AES-GCM authentication failure) shows "Wrong password"
and allows retrying; a profile with missing/unreadable cryptographic files
(`OSError`/`ValueError`, e.g. a missing `salt.bin`) instead shows "Damaged
profile: cannot be opened" — before this handling was added, it was an
uncaught error that closed the entire application.

**Task: unlocking the real name after success.** Once authenticated, it
calls `ProfileManager.unlock()` to decrypt the patient's real name and makes
it available to the rest of the app via `get_result()`.

## `theme.py` — design system (no application logic)

**Task: centralizing every color in one place.** Defines the entire palette
as named constants (surfaces, text, accent, and the three semantic colors
GREEN/YELLOW/RED plus NEUTRAL), so no hex color is scattered across the
screen files.

**Task: providing the global stylesheet.** `global_stylesheet()` applies a
consistent style to every standard Qt widget (buttons, text fields, lists,
scrollbars, tooltips), with minimum 44px touch targets and visible focus
outlines — requirements for a clinical touch device.

**Task: providing per-component style functions.** One function per reused
visual element (card, status pill, record button, status tag, metric chip,
etc.), so every screen composes its style without ever writing hex by hand.

## `widgets.py` — the reusable ECG plot widget

**Task: drawing the ECG trace.** `EcgPlotWidget` wraps a
`pyqtgraph.PlotWidget` configured with the Y axis fixed to a range
consistent with the normalized signal, the unit labeled "a.u." (not mV),
and optimized to draw only the points currently in view (`clipToView`) with
no downsampling applied (which would otherwise visibly change the wave's
morphology at different zoom levels).

**Task: live mode (rolling buffer).** `append_samples()` scrolls a
fixed-length circular buffer (the visible window, in seconds), correctly
handling the edge case of a block longer than the window itself.

**Task: static mode (reviewing a saved session).** `show_static()` displays
the entire recording, but limits the visible time window to a fixed
interval (`ARCHIVE_WINDOW_S`) that can only be scrolled horizontally, not
zoomed: this always keeps the number of drawn points bounded (and therefore
smooth, even on a Raspberry Pi), and gives a constant time scale, "like ECG
graph paper."

**Task: drawing colored bands per RR interval.** `add_rr_bands()` draws, behind
the trace, a translucent colored region for every classified RR interval,
**merging consecutive intervals that share the same color code into a
single graphical region** (instead of drawing dozens of separate ones), to
keep redraws cheap during scrolling. It's tolerant of small length mismatches
between the saved colormap and the RR intervals re-extracted from a
(possibly quantized) EDF file.

## `acquisition_screen.py` — live acquisition

**Task: reading the serial port on a dedicated thread.** `_SerialThread`
runs continuously, opens the port (auto-detected via `find_port`), reads
line by line, and interprets the two message types (`L,` for electrode
status, `D,` for samples); if the port isn't found or the connection is
lost, it reports the error and retries at regular intervals **without
burning 100% CPU** (a defect present before this version, where a read
error was swallowed by a tight loop with no pause).

**Task: detecting and reconstructing lost samples during recording.**
`_ingest()` compares the received sequence counter against the last known
one: if a small number of samples is missing (up to 5, i.e. 10 ms at 500
Hz), it reconstructs them by linear interpolation (see
`signal_processing.interpolate_gap`); beyond that threshold it treats the
interruption as real and doesn't invent physiological data that isn't
there, simply counting the lost samples.

**Task: real-time signal processing on a second thread.**
`_ProcessingThread` consumes the shared circular buffer, applies the digital
filter in blocks, feeds the R-peak detector sample by sample (discarding the
initial warm-up transient), accounts for any samples dropped due to buffer
overflow in the time index, computes the current heart rate, and places the
filtered block plus the updated HR onto a queue consumed by the UI. If the
UI can't keep up, excess blocks are dropped with a periodic log warning
(not on every occurrence, to avoid flooding the log) — the trace may show
small visual gaps, but the final analysis will still use the complete raw
samples saved by the serial thread.

**Task: building the screen's interface.** `AcquisitionScreen` assembles the
top bar (brand, profile, clock, electrode indicator), the ECG trace card,
and the fixed side column with the heart-rate card, the duration selector
(free-running / 2 minutes), the result banner, and the large record button.

**Task: distinguishing the causes of a disabled button.**
`_refresh_lod_indicator()` (called 4 times per second) distinguishes three
states — serial error, electrodes disconnected, electrodes OK — updating
the style only when the state actually changes (so Qt isn't forced to
recompute the stylesheet on every tick), and enables the record button only
when electrodes are actually connected.

**Task: managing a recording's lifecycle.**
`_start_recording()`/`_stop_recording()` start/stop the processing thread
dedicated to the current session (a **new** `Event` for every recording, to
prevent a not-yet-terminated previous thread from being "resurrected" by a
`clear()` of the shared buffer), manage the countdown (or the stopwatch, in
free-running mode, with a 15-minute safety ceiling), and update the button's
text and style.

**Task: saving and analyzing the just-recorded session.**
`_save_session()` writes the encrypted raw trace to EDF+ (`EDFWriter.save`),
explicitly handling the case of a too-short recording (under 1 second,
typically an accidental tap on STOP) as a "soft" error reported to the user
rather than a crash; it then runs the HRV analysis (`HrvAnalyser.analyse`)
using the same timestamp as the baseline's session id, saves the colormap
and features, and handles the case of an undecryptable baseline by showing
an explanatory message instead of a generic state.

**Task: updating the on-screen trace without blocking the UI.**
`_render_tick()`, called periodically by a `QTimer` (roughly 25 fps), drains
the queue of filtered blocks produced by the processing thread and appends
them to the plot, also updating the heart-rate label.

**Task: distinct messages for each NEUTRAL cause.** `_neutral_message()`
translates the technical reason (`neutral_reason`) returned by the analysis
engine into an understandable, specific message for the operator (session
too short, signal too noisy, baseline still building with an "X / Y" count,
unreadable baseline), instead of a generic "not scored."

**Task: orderly shutdown of all threads.** `shutdown()`, called when the
window closes, stops any recording in progress, signals both threads to
stop, and waits for them to exit with a timeout, logging a warning if they
don't terminate in time.

## `archive_screen.py` — browsing the session archive

**Task: rebuilding the session list from the filesystem.**
`scan_sessions()` groups the three files that make up a session (`.edf`,
`.colormap.npy`, `.features.json`) by "stem" (filename without
extension/suffix), discarding sessions missing the main EDF file, and sorts
the result from most recent.

**Task: retrieving RR-band boundaries for drawing.**
`rr_band_boundaries()` preferentially uses the R-peak indices already saved
in the features at analysis time (`rr_peaks`); only for "legacy" sessions
saved before this field existed does it recompute the peaks from scratch —
an expensive operation, which for this reason always runs outside the UI
thread (see `_DecryptThread`).

**Task: exporting a session in plaintext.** `export_session()` writes the
decrypted EDF and, if available, the decrypted features as plaintext JSON
alongside it, for use with external tools; the calling UI always shows an
explicit warning before proceeding (see `_on_export_clicked`), because from
that point on the file is no longer password-protected.

**Task: drawing the summary colored strip.** `ColormapStripWidget` draws a
colored rectangle for each classified RR interval (local color, see Part 1
§7), filling with a neutral color where there's no data.

**Task: showing the four metrics with a deviation tint.**
`MetricsGridWidget` shows SDNN, RMSSD, pNN50, and mean RR frequency in four
cards, coloring each value according to its own z-score relative to the
baseline (`_tint_color_for_z`): green/amber/red depending on how much that
individual metric — not just the overall status — deviates from the
patient's history.

**Task: drawing a session-list row.** `_SessionRowWidget` composes the
date, estimated duration, colored status label, an excerpt of the main
metrics, and the miniature colored strip; it distinguishes a tap from a
list-scrolling gesture by measuring finger movement between
`mousePressEvent` and `mouseReleaseEvent` (a card is only opened if the
finger hasn't moved more than a minimum threshold).

**Task: managing the scrollable session list.** `SessionListWidget` builds
the top bar, the session count, and rebuilds the list of cards every time
`load()` is called (e.g. when switching to the archive tab, or after a
deletion).

**Task: decrypting and preparing a session outside the UI thread.**
`_DecryptThread` (a dedicated `QThread`) decrypts the EDF, writes it
temporarily (in RAM if possible) so it can be read with the EDF library,
overwrites and deletes it right afterward (`shred`), and — only if the
session has a colormap — computes the RR-band boundaries; all of this
potentially slow work (including any re-detection of peaks on legacy
sessions) stays off the graphics thread so the interface doesn't freeze.

**Task: showing a session's detail view.** `SessionDetailWidget` composes
the header (date, status), the trace card with three possible states
(loading, trace ready, error), the color legend, the summary strip, the
four-metric grid, and the export/delete buttons; it starts a new
`_DecryptThread` every time a session is opened, carefully disconnecting the
signals of any previous thread still running, so a now-stale result can't
overwrite the current one.

**Task: deleting a session consistently.** `_on_delete_clicked()`, after
explicit user confirmation, **first** removes the corresponding vector from
the baseline and **only if that succeeds** deletes the session's three
files: the order is deliberate, because deleting the files first and then
failing to update the baseline would leave an "orphaned," unrecoverable
vector in the model, whereas the reverse (failing the baseline update
without touching the files) leaves the data consistent with itself.

**Task: orchestrating list and detail.** `ArchiveScreen` switches, via a
`QStackedWidget`, between the session list and a session's detail view,
reloading the list after every deletion.

**Task: the app's main navigation.** `TabBar` provides the two navigation
buttons (Acquisition/Archive) plus an always-reachable exit button —
necessary because the app runs full-screen, with no operating-system title
bar.

## `create_profile.py` — command-line utility

**Task: creating a patient profile from the terminal.** A standalone script
that asks for a name (encrypted), an optional alias (defaulting to the
initials, computed by `ProfileManager.default_alias`), and a password
(requested twice for confirmation, minimum 8 characters, read without echo
via `getpass`), then calls `ProfileManager.create_profile()`. It's the
intended way to populate the profile list before the graphical app is used
for the first time.

## `requirements.txt` — project dependencies

Lists the libraries used and their minimum version: `PyQt5` (graphical
interface), `pyqtgraph` (high-performance ECG plotting), `pyserial`
(communication with the Arduino), `scipy` and `numpy` (digital filtering and
numerical computation), `cryptography` (AES-GCM encryption and PBKDF2 key
derivation), `pyedflib` (reading/writing the EDF+ clinical format), `pytest`
(tests).

---

# PART 3 — Hardware documentation for the prototype

The first two parts describe what the software does and how it's built.
This part describes the physical device that software runs on: a multi-node
embedded system enclosed in a 3D-printed case (roughly 7 × 6 × 3 cm), which
acquires the ECG, processes it, and presents the HRV index on a touch
display. As with the software, every choice is documented together with its
trade-off: this is a research prototype, and the limitations chosen
consciously matter just as much as the solutions adopted.

## 1. System architecture

```
[ECG electrodes]
       │ analog signal (mV)
       ▼
  [AD8232]          amplifies, coarsely filters, detects lead-off
       │ amplified analog signal (centered ~Vs/2)
       ▼
[Arduino Nano]      samples at 500 Hz (10-bit ADC), serializes
       │ USB serial, 115200 baud
       ▼
[Raspberry Pi 4B]   digital filtering, HRV analysis, display
       │ MIPI DSI
       ▼
 [4.3" display]
```

**Power plan:**

```
[Li-Po battery, 3.7V]
       │
  [IP5328P]          boost 3.7V → 5V, up to 18W
       │ USB-C 5V/3A
       ▼
[Raspberry Pi 4B]
       │ USB-A → USB-C
       ▼
[Arduino Nano]
```

## 2. Main components

### 2.1 Raspberry Pi 4B

| Parameter | Value |
|---|---|
| SoC | Broadcom BCM2711 |
| CPU | 4× ARM Cortex-A72 @ 1.5 GHz |
| RAM | 8 GB LPDDR4 |
| Required power | 5 V / 3 A (15 W nominal) |
| Current peaks | up to ~3.5 A during boot + active display |
| Display interface | MIPI DSI (friction-latch flex connector) |
| Arduino connection | USB-A ↔ USB-C |
| Storage | microSD (single point of failure — see §11) |

**Power-related criticality.** The Pi 4B is particularly sensitive to
undervoltage. Voltages below ~4.75 V trigger the kernel warning
`"Under-voltage detected!"`, CPU thermal throttling, and, in the worst
cases, SD card corruption during write spikes. The IP5328P module was
chosen specifically to guarantee the required stability (see §3).

**DSI connector.** The MIPI DSI connector's latch is friction-based, with
no positive locking mechanism. Every open/close cycle of the case
mechanically stresses this connection: before every presentation, after
final assembly, the flex cable must be verified as properly seated.

### 2.2 Arduino Nano

| Parameter | Value |
|---|---|
| MCU | ATmega328P (CH340 USB-serial clone) |
| ECG sampling rate | 500 Hz |
| ADC resolution | 10-bit (0–1023) on a 5V reference → ~4.9 mV/LSB |
| Serial interface | 115200 baud, text-based protocol |
| Bandwidth used | ~5.5 kB/s out of 11.5 kB/s available (~48%) |
| Power | 5V from USB (sourced from the Pi) |

**Serial protocol** (the same one described on the firmware side in Part 2):

```
D,<seq>,<val>\n    ECG sample (seq = counter 0..255, val = 0..1023)
L,0\n              electrodes connected
L,1\n              electrodes disconnected (lead-off)
```

The `seq` sequence counter is what lets the Pi notice lost samples: a gap in
the numbering signals that time has advanced with no data, allowing for
interpolation or a conscious discard instead of a silent drift in the
timebase.

**The bandwidth margin is thin.** 48% serial bandwidth utilization doesn't
leave a lot of headroom. The firmware calls `Serial.availableForWrite()`
before transmitting: if the 64-byte TX buffer is full, the sample is
skipped (still advancing the counter) instead of blocking the acquisition
loop and introducing jitter into the timebase — the same logic already
described for the firmware in Part 2.

### 2.3 AD8232 ECG sensor

| Parameter | Value |
|---|---|
| Type | Single-Lead Heart Rate Monitor Front-End |
| Gain | ~100× (adjustable) |
| Typical ECG input voltage | 1–3 mV |
| Output voltage | centered around Vs/2 (~2.5 V on 5V) |
| Built-in filtering | 0.5 Hz highpass + integrated lowpass |
| Lead-off detection | yes, via the LOD+ and LOD− pins |
| Power | 3.3–5V (powered from the Arduino) |

**DC offset and the filtering transient.** The AD8232 outputs the signal
centered around Vs/2. At startup, the Pi's digital highpass filter (0.5 Hz)
reacts to this DC gradient with a transient whose amplitude is comparable
to that of an R-wave, which dies out in about 3 seconds — this is exactly
the reason, also explained in Part 1 and in the `config.py` comment, why
the first 3 seconds of every acquisition are discarded
(`FILTER_WARMUP_S = 3.0`) before R-peak detection begins.

**Lead-off.** Detection of disconnected electrodes is handled at the
firmware level (Arduino) and transmitted to the Pi via the serial protocol
(`L,0` / `L,1`). Electrodes coming loose during a recording does not
interrupt acquisition: the artifact remains visible on the trace and is
handled by the software's artifact filter (Part 2, `analysis_engine.py`).

**Margin on the T/R ratio after filtering.** The Pi's 0.5–40 Hz digital
bandpass filter attenuates the T-wave more than the R-wave. The filtered
T/R ratio drops to ~13%, against the R-peak detection threshold of 60%: a
margin of 47 percentage points, enough to avoid the T-wave being mistaken
for a double beat.

### 2.4 Waveshare 4.3" MIPI DSI display

| Parameter | Value |
|---|---|
| Diagonal | 4.3 inches |
| Resolution | 800 × 480 px |
| Interface | MIPI DSI (Display Serial Interface) |
| Touch | capacitive |
| Connection | 15-pin FFC flex cable, 1.0 mm pitch |
| Typical power draw | ~1–2 W |

**DSI flex cable.** The cable forms a wide-radius loop (roughly 4 cm in
diameter) inside the case to absorb the excess length in a tight space. A
loop geometry is preferred over sharp folds because it doesn't induce
mechanical fatigue on the cable under static conditions: the loop sits in a
fixed position and isn't stressed during normal use (no repeated flexing
cycles).

**EMI vulnerability.** The DSI flex cable is the system's most
EMI-vulnerable component, since it's unshielded and positioned close to the
IP5328P switching converter. The mitigation adopted is described in §4.

### 2.5 5000 mAh Li-Po battery

| Parameter | Value |
|---|---|
| Form factor | 955465 (9.5 × 54 × 65 mm) |
| Nominal capacity | 5000 mAh |
| Nominal voltage | 3.7 V |
| Maximum charge voltage | 4.2 V |
| Maximum continuous discharge current | ~4.5 A (sufficient for the required 15 W) |
| Total energy | ~18.5 Wh |
| Estimated runtime at full load (15 W) | ~60–70 minutes |
| Runtime at medium load (10–12 W) | ~90–100 minutes |

**Usage.** The battery is always brought to full charge before a
presentation. Simultaneous charge-while-discharge operation is not
supported, which eliminates the risk of voltage dips associated with that
operating mode on some IP5328P modules.

**Expansion.** The physical space inside the case allows enough margin to
accommodate slight cell swelling (normal over charge cycles), without this
creating mechanical pressure on adjacent components.

**Discharge cutoff.** The IP5328P module manages the cell's minimum
discharge threshold; below that threshold the system shuts down. The Pi
4B's behavior at this shutdown needs to be verified during testing (see
§11 — this is the most concrete risk to the SD card).

### 2.6 IP5328P boost module

| Parameter | Value |
|---|---|
| Chip | IP5328P |
| Topology | DC-DC switching boost |
| Input voltage | 3.0–4.2 V (from the Li-Po) |
| Output voltage | 5 V regulated |
| Maximum output power | 18 W (Power Delivery) |
| Maximum output current | ~3.6 A at 5 V |
| Typical switching frequency | 300 kHz – 1 MHz (per datasheet) |
| Typical efficiency | ~85–92% at full load |

**EMI noise source.** The switching converter generates electromagnetic
noise concentrated at the switching frequency and its harmonics; the
boost's inductor is the main radiating component (a varying magnetic
field). The switching frequency is well distinct from the 50 Hz mains, but
its harmonics can still interfere with the DSI flex cable and the serial
data lines. The mitigation is described in §4.

## 3. Power system

**Power chain:**

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
    └─── Waveshare display (powered via DSI from the Pi)
```

**Power budget:**

| Component | Typical draw | Peak draw |
|---|---|---|
| Raspberry Pi 4B (medium load, display active) | ~8–10 W | ~15 W |
| Arduino Nano + AD8232 | ~0.5 W | ~1 W |
| Waveshare 4.3" display | ~1–2 W | ~2 W |
| **Total** | **~10–12 W** | **~18 W** |

The IP5328P module supplies up to 18 W: the margin relative to the
theoretical peak is thin, but sufficient, because simultaneous peaks from
every component are unlikely under normal operating conditions.

**Power stability.** The Pi 4B requires a stable voltage ≥ 4.75 V. The
IP5328P module guarantees regulation even with the battery at low charge
(≥ 3.0 V). Verifying the absence of undervoltage under real load (active
display + simultaneous ECG acquisition) is part of the final test before a
presentation.

## 4. Electromagnetic compatibility (EMC)

**Noise sources in the system:**

| Source | Type of interference | Main victim |
|---|---|---|
| IP5328P (switching) | radiated + conducted, 300 kHz–1 MHz | DSI flex cable, Arduino |
| ECG electrode cables | antenna for 50 Hz mains interference | AD8232 |
| Mains power (environment) | conducted via charging line | IP5328P |

**Mitigation strategy — two levels, hardware and software.**

*Hardware level — Shielding Baffle (partial Faraday cage).* An "L"-shaped
directional shield (side wall + roof) is physically interposed between the
IP5328P module (source) and the DSI flex cable (victim). The "L" geometry
is deliberate: it doesn't fully enclose the module, leaving the opposite
sides open for thermal ventilation.

- **Structure:** rigid cardboard or a plastic sheet as an insulating
  substrate.
- **Conductor:** copper adhesive tape on the outer side.
- **Inner insulation:** the side facing the module stays insulated, to
  avoid accidental short-circuits with the module's pins.
- **Grounding:** the copper tape is connected via a wire to the GND pin on
  the perfboard (Arduino). Since the Arduino and Pi share ground through
  USB, a common low-impedance reference plane exists.

**Why grounding is mandatory, not optional.** At high frequencies, noise
propagation is dominated by line-of-sight: interrupting the direct path
between the inductor and the flex cable knocks down the radiated field at
the victim component. Without grounding, however, the shield would behave
like a resonant antenna itself, amplifying the interference instead of
attenuating it.

*Software level — digital notch filter.* The signal acquired by the AD8232
passes through a 50 Hz IIR notch filter (Q = 30) implemented on the Pi
(`signal_processing.py`, Part 2): it's the digital answer to the same
problem the shield solves in the analog domain. The consistency between the
two measures — physical shielding at 300 kHz–1 MHz and digital filtering at
50 Hz — reflects the fact that the noise sources are distinct: the
switching converter on one hand, the environment's mains power on the
other. Neither measure alone would cover both sources.

**Differential cable routing.** Cables are routed to minimize coupling
between power lines and signal lines: the Pi → Arduino data cable runs
through the upper zone of the case, separated from the power lines; the
Module → Pi power cable runs under the display, shielded by its own braid;
the DSI flex cable is protected by the Shielding Baffle described above.

## 5. Wiring and routing

**Cable map:**

| Cable | Path | Length | Notes |
|---|---|---|---|
| USB-C (Pi power) | IP5328P → Pi 4B | 10–15 cm | runs under the display; shielded braid; 3A support mandatory |
| USB-A ↔ USB-C (Arduino data + power) | Pi 4B → Arduino Nano | 10–15 cm | upper zone of the case; shielded braid |
| FFC 15-pin 1.0 mm (DSI display) | Pi 4B → Waveshare 4.3" | 30 cm | wide-radius loop (~4 cm Ø); protected by the Shielding Baffle |
| ECG electrode cables | AD8232 → electrodes | free length | unshielded; act as antennas for 50 Hz mains interference (mitigated by the digital notch filter) |
| Shield GND cable | Copper shielding → perfboard GND | short | soldered to the shared Pi/Arduino ground plane |

**DSI flex cable geometry.** The cable forms a nearly complete loop (about
300° of arc, ~4 cm in diameter) that absorbs the excess length without
sharp folds. The bend radius is well above the typical fatigue limit for
standard FFC cables (5–10 times the pitch, i.e. ~5–10 mm: the loop's radius
here is ~20 mm). The cable stays in a static position and doesn't undergo
cyclic flexing during use.

## 6. Mechanical isolation and electrical safety

**Battery / IP5328P module spacer.** The IP5328P module's PCB is positioned
above the Li-Po cell. The pins and components on the underside of the PCB
could, without protection, mechanically puncture the cell's Mylar
enclosure, causing an internal short circuit with a risk of thermal
runaway. The measure adopted is a layer of insulating material (spongy
double-sided tape or a plastic/FR4 sheet) interposed between the underside
of the module and the top surface of the cell, with a thickness sufficient
to maintain separation even under transport vibration.

**Isolating the flex cable from the battery.** The DSI flex cable's loop
runs close to the battery's enclosure. The contact point between the
cable's longitudinal edge (a clean cut) and the cell's surface is protected
by the same insulating spacer that separates the module from the cell,
eliminating the risk of Mylar abrasion.

**Li-Po cell safety:**

- The cell is never charged during the prototype's operational use.
- The physical space inside the case allows margin for slight cell
  swelling.
- No external protection circuit (BMS) is present beyond the one built
  into the IP5328P module: it is recommended not to fully discharge the
  cell, nor to leave it charging unattended.

## 7. Thermal management

**Heat sources:**

| Component | Typical dissipated power | Temperature limit |
|---|---|---|
| BCM2711 (Pi 4B) | ~4–5 W at full load | 85°C (junction) |
| IP5328P | ~1.5–2.5 W (~88% efficiency) | ~125°C (junction, typical datasheet value) |
| Li-Po battery | heating from discharge current | 45–50°C (maximum allowed) |

**Raspberry Pi 4B — no heatsink.** For a session up to 30 minutes long, the
BCM2711 package's thermal inertia is enough to prevent thermal throttling.
The junction-to-air thermal resistance with no heatsink is ~30–40°C/W; at
4–5 W of dissipation and a 25°C ambient temperature, the estimated
*steady-state* junction temperature would be ~145–225°C — above the limit,
but steady state isn't reached within 30 minutes precisely because of the
package's thermal inertia. A session extending beyond 60 minutes would
require adding a heatsink.

**IP5328P — natural ventilation.** The case has vents on the right side, and
the Shielding Baffle (§4) is open on two sides (top, and the side opposite
the vents) specifically to avoid obstructing airflow around the inductor
and the chip. The heat generated by the converter is therefore dissipated
by natural convection toward the vents, limiting heat transfer to the
battery underneath.

**Li-Po battery — thermal protection.** The insulating spacer between the
module and the battery (§6) also reduces direct thermal conduction; the
system's vertical layout maintains physical separation between the hot
source (IP5328P) and the temperature-sensitive cell.

## 8. 3D-printed case

| Parameter | Value |
|---|---|
| External dimensions | ~7 × 6 × 3 cm |
| Material | PLA or PETG (assumed from color and appearance) |
| Color | bright green |
| Ventilation slots | right side |
| Opening | removable lid (no hinge) |

**Mechanical considerations:**

- The vents are on the right side, consistent with the position of the
  IP5328P module and its point of maximum heat generation.
- The lid has no positive locking mechanism (press-fit or screwed closure,
  to be verified): every open/close cycle can therefore stress the internal
  connections, particularly the DSI connector (see §2.1).
- The dimensions force a vertically stacked layout: Pi 4B at the bottom,
  battery and IP5328P module above it, display and Arduino on the top
  level.

## 9. The ECG signal chain — hardware side

This section completes, from the hardware side, the processing chain
already described on the software side in Part 1 (§5) and Part 2
(`signal_processing.py`):

```
Human body
    │ differential signal ~1–3 mV
    ▼
Electrodes (3-lead: RA, LA, RL/shield)
    │ unshielded cables → antennas for 50 Hz common-mode interference
    ▼
AD8232
    ├─ differential amplification (~100×): ECG signal 100–300 mV
    ├─ built-in filtering (partial removal of baseline drift)
    ├─ reference centered at Vs/2 (~2.5 V on 5V)
    └─ lead-off detection (current threshold across the electrodes)
    │ single-ended analog signal on the OUTPUT pin
    ▼
Arduino Nano — analog pin A0
    ├─ 10-bit ADC, 0–5V → 4.9 mV/LSB resolution
    ├─ 500 Hz sampling (via micros(), not delay())
    └─ serialization → USB, 115200 baud
    │
    ▼ USB (implicit galvanic isolation)
    │
Raspberry Pi 4B
    ├─ deserialization (SerialThread)
    ├─ cascaded digital IIR filter, SOS form:
    │    ├─ 50 Hz notch (Q=30): removes mains interference
    │    └─ Butterworth 0.05–40 Hz bandpass (order 4): removes DC drift and EMG noise
    ├─ R-peak detector (adaptive threshold, 0.6×max, 200 ms refractory)
    └─ HRV analysis → display
```

**Why USB rather than SPI/I2C between the Pi and the Arduino.** This choice
offers implicit galvanic isolation within commercial shielded USB cables,
protocol robustness (USB autonomously handles error detection and
retransmission), and the absence of unshielded signal lines crossing the
case — with SPI/I2C, the clock and data lines would have run through the
interior unshielded. The trade-off is the serialization's inherent latency:
at 500 Hz and 115200 baud, each sample takes ~0.2–0.3 ms from the ADC to
arrival on the Pi, entirely acceptable for an HRV application (which
operates on timescales of hundreds of milliseconds, not microseconds).

## 10. Bill of materials (BOM)

| Qty | Component | Key specs |
|---|---|---|
| 1 | Raspberry Pi 4B | 8 GB RAM |
| 1 | Arduino Nano | CH340 USB-serial clone |
| 1 | AD8232 ECG sensor | SparkFun or compatible |
| 1 | Waveshare 4.3" display | MIPI DSI, capacitive touch, 800×480 |
| 1 | Li-Po battery | 5000 mAh, 955465 form factor |
| 1 | IP5328P boost module | 5V / 18W, Power Delivery |
| 1 | FFC cable, 15-pin, 1.0 mm | 30 cm, for the DSI display |
| 1 | USB-C ↔ USB-C cable | 10–15 cm, 3A-rated, for Pi power |
| 1 | USB-A ↔ USB-C cable | 10–15 cm, for the Arduino |
| 1 | Roll of copper adhesive tape | conductive, for the Shielding Baffle |
| 1 | Rigid cardboard or plastic sheet | insulating substrate for the Shielding Baffle |
| 1 | Spongy double-sided tape | insulating spacer, battery/module |
| 1 | Perfboard | mounting and GND point for the shield |
| 1 | 3D-printed case | ~7×6×3 cm, with side vents |
| 3 | ECG electrodes | with cables and clips (RA/LA/RL set) |

## 11. Known limitations and residual risks

**Hardware risks:**

| Risk | Probability | Impact | Mitigation |
|---|---|---|---|
| SD card corruption on sudden power-off (battery cutoff) | Medium | High (no boot) | Discharge testing down to cutoff; SD image backup; software overlayfs |
| DSI connector failure after open/close cycles | Low | High (no display) | Verify connection after final assembly; limit the number of cycles |
| Pi 4B thermal throttling beyond 60 minutes | Medium | Medium (slowdown) | Not critical for sessions ≤ 30 min; add a heatsink for extended use |
| Li-Po enclosure puncture from module pins | Low (with spacer) | Very high (thermal runaway) | Insulating spacer mandatory between module and cell |
| EMI interference on the DSI flex cable | Low (with shielding) | Medium (video artifacts) | Shielding Baffle + grounding |

**Intrinsic limitations:**

- **No mV calibration.** The AD8232 doesn't provide a calibrated output:
  the signal is in normalized ADC units [0, 1023]. Absolute millivolt
  values cannot be derived without specific hardware calibration —
  consistent with what's already stated in Part 1 and in the exported
  EDF+ file's metadata (`data_layer.py`, Part 2).
- **Single lead.** The system acquires only Lead I (RA−LA): it's not
  possible to build a 12-lead ECG, nor to detect events that manifest
  mainly on other leads.
- **Unshielded electrodes.** The electrode cables act as antennas for 50 Hz
  common-mode interference. The mitigation is the digital notch filter, not
  physical shielding: in environments with strong mains interference (older
  buildings, nearby industrial equipment), the AD8232's CMRR alone might
  not be enough.
- **SD card as a single point of failure.** There is no storage redundancy:
  an SD card failure during a presentation renders the system unable to
  boot — the most concrete risk among those listed above, which is why it
  appears twice in this document (here and in §2.1/§2.5).