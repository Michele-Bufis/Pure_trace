<div align="center">

# Pure-Trace

**An engineering case study in patient-specific cardiac anomaly detection**
Signal processing · applied statistics · encrypted health data · concurrent embedded systems

[![Python](https://img.shields.io/badge/python-3.10%2B-blue?logo=python&logoColor=white)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](./LICENSE)
[![Status](https://img.shields.io/badge/status-research%20prototype-orange)](#disclaimer)

`signal-processing` · `applied-statistics` · `cryptography` · `concurrent-systems` · `embedded-firmware` · `desktop-ui`

</div>

<p align="center">
  <!--
    Suggested hero image: a photo of the assembled device (Raspberry Pi +
    touchscreen + Arduino/AD8232) running the acquisition screen.
    docs/screenshots/hero.png — 1200px wide recommended.
  -->
  <img src="docs/screenshots/hero.png" alt="Pure-Trace device running the acquisition screen" width="800">
</p>

---

## ⚠️ Disclaimer

> **Pure-Trace is a research prototype. It is not a medical device and must
> not be used for diagnostic purposes.** It reports statistical deviations
> from a patient's own historical baseline — it does not diagnose any
> medical condition. The disclaimer is also shown explicitly in the app's
> login screen.

---

## What this is

Pure-Trace is a complete, working system — Arduino firmware, real-time
signal processing, an applied-statistics scoring model, and an encrypted
desktop application — built to answer one specific engineering question:
*can a low-cost single-lead ECG setup detect meaningful, patient-specific
deviations in cardiac variability, end to end, with the same rigor a
production system would need?*

This README documents **what was built and why**, not how to set it up —
the goal is to make the reasoning behind each decision legible, not to hand
over a plug-and-play package.

## The idea

Commercial wearables flag "abnormal" heart rate variability against
population-wide thresholds — the same cutoff for everyone, regardless of a
person's own baseline physiology. Pure-Trace explores a different approach:
build a **personal, per-patient statistical model** instead, and measure how
much a new recording deviates from *that specific person's own history*
rather than from a population average.

The differentiator is deliberately **not** the hardware. The statistical
layer — feature extraction, per-patient Mahalanobis baseline, Hotelling T²
calibration — is designed to be agnostic to whatever ECG front-end feeds it;
any certified sensor could sit in place of the Arduino/AD8232 used here
without changing the algorithm. Two architectural choices reflect that
intent:

- **Raw signal fidelity is never touched.** Filtering is only ever used for
  on-device display and feature extraction — every export is always the
  unprocessed raw signal, so nothing is lost to on-device processing before
  the data reaches a clinician.
- **Local-first, no-cloud data model.** Every artifact is encrypted and kept
  on the device itself, and sessions export to EDF+, a standard clinical
  format independent of this software.

This repository is the proof-of-concept for that idea: it demonstrates that
the full pipeline runs end-to-end, and that the statistical layer holds up
under real edge cases — the subject of the next section.

## Screenshots

<!--
  Replace the placeholders below with real screenshots once available.
  Suggested shots (docs/screenshots/):
    - profile_login.png     -> profile selector + password screen
    - acquisition_live.png  -> live ECG trace + heart rate during a recording
    - archive_list.png      -> session list with status colors
    - session_detail.png    -> full trace + colored RR strip + metrics grid
-->

<table>
  <tr>
    <td align="center"><b>Login / profile selection</b></td>
    <td align="center"><b>Live acquisition</b></td>
  </tr>
  <tr>
    <td><img src="docs/screenshots/profile_login.png" width="380"></td>
    <td><img src="docs/screenshots/acquisition_live.png" width="380"></td>
  </tr>
  <tr>
    <td align="center"><b>Session archive</b></td>
    <td align="center"><b>Session detail</b></td>
  </tr>
  <tr>
    <td><img src="docs/screenshots/archive_list.png" width="380"></td>
    <td><img src="docs/screenshots/session_detail.png" width="380"></td>
  </tr>
</table>

---

## Table of contents

- [Skills & concepts applied](#skills--concepts-applied)
- [Engineering deep dives](#engineering-deep-dives)
- [Architecture](#architecture)
- [Privacy & data model](#privacy--data-model)
- [Tech stack](#tech-stack)
- [Project structure](#project-structure)
- [Production-readiness considerations](#production-readiness-considerations)
- [Full documentation](#full-documentation)

---

## Skills & concepts applied

| Domain | Where it shows up in this project |
|---|---|
| **Digital signal processing** | Real-time IIR notch + bandpass filtering with persistent filter state, adaptive R-peak detection, offline vs. streaming filter equivalence |
| **Applied statistics** | Multivariate outlier detection (Mahalanobis distance), correct small-sample calibration (Hotelling T² instead of χ²), robust (median/MAD) z-scoring |
| **Applied cryptography** | AES-GCM authenticated encryption, PBKDF2 key derivation, side-channel-aware design (padding to hide plaintext length) |
| **Concurrent systems** | Producer/consumer threading (serial ↔ processing ↔ UI), a thread-safe circular buffer, a lock-free O(1) sliding-window maximum |
| **Embedded firmware** | Non-blocking serial I/O, drift-free timing via `micros()`, a fault-tolerant serial protocol with sequence numbers |
| **Resilient systems design** | Atomic file writes, crash-safe multi-step operations, explicit "missing vs. corrupted" data handling |
| **Applied UX** | A touch-first, single-purpose interface designed for a fixed 800×480 embedded display, not a general-purpose desktop app |

## Engineering deep dives

Each of these started as a bug, a wrong assumption, or a "this works but is
it actually correct?" moment. They're the parts of the project worth
reading the code for.

### 1. Calibrating the baseline thresholds correctly, not just plausibly

**Problem.** A new session is flagged `RED` if it's statistically far from
the patient's historical baseline. The obvious way to define "far" is a χ²
threshold on the Mahalanobis distance — that's the textbook formula when
mean and covariance are *known*.

**Why the obvious approach is wrong here.** They aren't known — they're
*estimated* from a handful of previous sessions per patient. Plugging
estimated parameters into a formula that assumes they're exact understates
the real uncertainty. Measured against the intended 1% false-positive rate,
the naive χ² threshold produced roughly **20% false `RED` classifications**
at typical early sample sizes (n≈5) — a model that would cry wolf on a
healthy patient one time in five.

**What was done.** Replaced it with two-sample Hotelling T² theory, which
accounts for the fact that the reference distribution itself is estimated:
the distance is rescaled and compared against an F-distribution with degrees
of freedom tied to the number of sessions and features, only activating once
there are enough sessions for those degrees of freedom to be valid. This is
the difference between a model that is *statistically defensible* and one
that merely looks reasonable in a demo.

*(`analysis_engine.py`, `BaselineModel`; reasoning also documented inline in
`config.py`.)*

### 2. Deciding what "signal fidelity" actually means

**Problem.** The real-time R-peak detector fires on the first sample that
crosses an adaptive threshold — not on the true peak of the R-wave.

**Why it matters.** That lag isn't constant: R-wave amplitude is modulated
by respiration, so the detection lag varies breath to breath. RMSSD, the HRV
metric most sensitive to beat-to-beat variation, picks that variation up
directly as if it were physiological — it isn't, it's a detector artifact.

**What was done.** Offline analysis re-locates every detected peak to its
true local maximum before computing any metric ("apex snapping"). Measured
effect: RMSSD error dropped from roughly **+5% to +1%**. This also clarified
a broader design principle applied throughout the project: filtering and
detection are allowed to be approximate for *display* purposes, but never
for anything that feeds a number the clinician will actually read — and the
raw signal that gets exported is never touched by any of this in the first
place (see [The idea](#the-idea)).

*(`analysis_engine.py`, `_snap_to_apex`.)*

### 3. Not leaking data through metadata

**Problem.** Every derived artifact — the per-beat classification, the HRV
feature file — is AES-GCM encrypted. Encryption hides content. It does
**not** hide length.

**Why it matters.** The per-beat colormap has one byte per heartbeat. Its
file size on disk, without decrypting a single byte, directly reveals beat
count — and therefore average heart rate — to anyone with access to the
storage medium.

**What was done.** Every payload is padded to a fixed block size before
encryption, so ciphertext length stops correlating with the number of
recorded beats. It's a small addition, but it's the difference between "the
data is encrypted" and "the data is actually private" — a distinction that's
easy to miss and rarely tested for.

*(`secure_store.py`, `_pad`/`_unpad`.)*

### 4. Treating "no data" and "corrupted data" as different failure modes

**Problem.** A read helper that returns a sensible default when a file is
missing is convenient — until the same fallback also fires for a file that
exists but fails to decrypt (wrong key, bit rot, partial write).

**Why it matters.** For most files, silently treating "corrupted" as "empty"
is harmless. For the baseline file specifically, it is not: the analysis
pipeline would interpret a decrypt failure as "no baseline yet," rebuild an
empty pool, and **overwrite months of patient history** with it — a data-loss
bug that is invisible until someone notices the baseline "reset itself."

**What was done.** The baseline reader uses a strict mode that raises an
explicit, distinguishable error on decrypt failure instead of degrading to a
default; scoring is disabled until the problem is resolved, and the file is
never rewritten in that state. Every other (lower-stakes) read in the app
still degrades gracefully — this is a deliberate exception, not a global
policy change.

*(`secure_store.py`, `read_json(strict=True)`; `analysis_engine.py`,
`_load_model`.)*

### 5. Real-time performance on hardware that doesn't have much to spare

**Problem.** R-peak detection needs the maximum value in a sliding window,
recomputed on every incoming sample, on a Raspberry Pi.

**Why the obvious approach doesn't scale.** Recomputing `max()` over the
window on every sample is O(window size) per sample — at 500 Hz with a
1-second window, that's a real, measurable amount of wasted CPU on
constrained hardware, and it compounds with everything else the UI thread
needs to do to stay responsive.

**What was done.** A monotonic deque gives an O(1) amortized sliding-window
maximum. The same performance-first mindset shows up elsewhere: offline
filtering processes an entire session as one array operation instead of
looping sample-by-sample (~2000x faster, same numerical result, because the
filter's internal state is threaded through explicitly either way), and
acquisition is split across three cooperating threads — serial I/O,
DSP/detection, and UI rendering — so none of them can stall another.

*(`signal_processing.py`, `RPeakDetector._window_max`, `DigitalFilter`.)*

### 6. Assuming the field will go wrong, because it will

**Problem.** This runs on a Raspberry Pi that can lose power mid-write, an
Arduino connected over a USB cable that can disconnect mid-session, and a
serial link that can drop samples under load — with, potentially, no
technician nearby when it happens.

**What was done, concretely:**
- The firmware keeps a running sample counter even when it has to *skip*
  sending a sample under backpressure, so drops are countable, not silent;
  the app reconstructs short gaps by interpolation instead of letting the
  RR-interval timebase quietly drift.
- Every file write (a new patient profile, a session, the baseline) goes to
  a temp file, is `fsync`'d — file *and* containing directory — then
  atomically renamed, so a power loss never leaves a half-written file
  where a good one should be.
- Profile creation builds the entire profile in a hidden staging directory
  and only renames it into place once complete, so an interrupted creation
  can't leave a half-built profile that crashes the login screen later.

None of these are exotic techniques. What they demonstrate is the habit of
asking "what happens if this specific operation is interrupted halfway
through?" for every operation that touches disk or a wire — not just the
obviously risky ones.

## Architecture

```mermaid
flowchart LR
    A["AD8232 ECG sensor"] --> B["Arduino Nano\n500 Hz sampling"]
    B -->|"USB serial\nD,seq,val / L,0|1"| C["Serial thread"]
    C --> D["Thread-safe\ncircular buffer"]
    D --> E["Processing thread\nnotch + bandpass filter\nR-peak detection"]
    E --> F["Live ECG plot\n+ heart rate"]
    E -.raw samples.-> G["EDF+ writer\nAES-GCM encrypted"]
    G --> H["HRV analysis engine"]
    H --> I["Personal baseline model\nHotelling T² / Mahalanobis"]
    I --> J["GREEN / YELLOW / RED / NEUTRAL"]
    H --> K["Encrypted session archive"]
    K --> L["Archive screen\nreview / export / delete"]
```

The AD8232 front-end amplifies the ECG signal and exposes a leads-off
status; the Arduino samples both at 500 Hz and streams them over serial with
a sequence counter. The desktop app filters the live signal for display and
detection only, while the raw trace is what actually gets saved. On stop,
the session is encrypted, written as EDF+, and analyzed offline: HRV metrics
are computed, checked against the patient's baseline once enough history
exists, and the result is archived alongside the recording.

## Privacy & data model

Health data handling was treated as a first-class design constraint, not an
add-on:

- Each profile is password-protected (PBKDF2-HMAC-SHA256, 200,000
  iterations) → a profile-specific AES-128-GCM key; the password itself is
  never stored.
- The patient's real name, the raw ECG, HRV metrics, and the baseline model
  are all encrypted at rest. Only a non-identifying alias is ever shown
  before login — see [deep dive #3](#3-not-leaking-data-through-metadata) for
  why encryption alone wasn't treated as sufficient.
- Exporting a session for external clinical tools produces a **plaintext**
  file by necessity — the app surfaces an explicit warning before doing so,
  since protection becomes the user's responsibility from that point on.

*(`secure_store.py`, `data_layer.py`.)*

## Tech stack

`Python` · `PyQt5` + `pyqtgraph` (UI/plotting) · `NumPy` / `SciPy` (DSP) ·
`cryptography` (AES-GCM, PBKDF2) · `pyedflib` (EDF+ clinical format) ·
`pyserial` · `Arduino C++` (firmware)

## Project structure

```
pure-trace/
├── firmware/pure_trace_firmware.ino   # Arduino sketch (ECG front-end)
├── pure_trace/                        # application package
│   ├── main.py, config.py
│   ├── data_layer.py, secure_store.py       # profiles, encryption, EDF+
│   ├── analysis_engine.py                   # HRV analysis + baseline model
│   ├── signal_processing.py, serial_port.py # real-time DSP + serial I/O
│   ├── logging_setup.py
│   └── ui/                                  # PyQt5 screens + design system
├── tools/create_profile.py
├── docs/                              # full technical write-up + screenshots
└── requirements.txt
```

Full breakdown of every file, by responsibility, is in the
[technical documentation](#full-documentation).

## Production-readiness considerations

Built with hobbyist-grade parts on purpose, to validate the pipeline and the
statistical layer without waiting on certified hardware. What follows are
choices tied to *this specific build*, not to the underlying approach — a
production version would swap the front-end rather than solve these in
place:

- **Not a diagnostic tool** — reports relative deviations from a personal
  baseline, not medical conditions, by design.
- **This sensor isn't mV-calibrated.** The AD8232 used for the demo doesn't
  provide a calibrated analog output; the app states this explicitly rather
  than implying a precision the hardware doesn't have. A certified front-end
  would provide a calibrated signal with no change to the software
  downstream — the statistical layer only ever consumes derived features.
- **Secure deletion is a mitigation, not a guarantee** on SD/SSD media with
  wear leveling — a property of the storage medium, independent of the
  encryption scheme itself.

## Full documentation

A complete theory + code walkthrough (in Italian) is available in
[`docs/Pure-Trace_documentazione.md`](docs/Pure-Trace_documentazione.md),
covering every design decision in the project, file by file, in more depth
than fits here.

---

<div align="center">

**[Michele Bufis]** · [LinkedIn](https://www.linkedin.com/in/michele-pasquale-bufis-7362242a0) · [michelebufis2002@gmail.com)]

<sub>Built as a research prototype exploring signal processing, applied statistics, and secure data handling on embedded hardware.</sub>

</div>
