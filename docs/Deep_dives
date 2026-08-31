# Pure-Trace — Deep Dives

Full write-ups for every decision summarized in the README's
[Hardware highlights](../README.md#hardware-highlights) and
[Software highlights](../README.md#software-highlights) sections, in the
same order, with code pointers.

A note on sourcing: the software write-ups below that touch
`signal_processing.py`, `secure_store.py`, `data_layer.py`, and
`config.py` are verified directly against those files' source and their
test suite. The parts that touch `analysis_engine.py` and
`acquisition_screen.py` (the R-peak apex-snapping function, the baseline
model's internals, the serial gap-filling thread) are reconstructed from
`config.py`'s parameters/comments, the test suite that exercises them, and
the project's own prior documentation — their source files were not
available for this pass, and any inference is marked as such inline. The
hardware write-ups are sourced from Part 3 ("Hardware documentation for
the prototype") of `docs/Complete_Project_Documentation.md`.

---

## Hardware

### 1. Choosing battery-only power for galvanic isolation

The concern IEC 60601-1 centers on is electric shock risk from a patient
being connected, however indirectly, to mains-referenced electronics.
Pure-Trace's answer is procedural, not a certified circuit: the device
always runs off its internal 5000 mAh Li-Po (955465 form factor) through an
IP5328P boost module (3.7 V → 5 V, up to 18 W), and it is never charged and
discharged at the same time.

That rule has two separate justifications. The practical one came first:
some IP5328P modules show a voltage-dip failure mode under concurrent
charge/discharge, so the battery is always brought to full charge *before*
a session and never topped up during one. The safety-relevant side effect
is that the whole device is therefore physically unplugged from the mains
for the entire duration of a recording — but this is an operating
procedure the team follows, not a hardware interlock that physically
prevents simultaneous charge-and-use. The only protection circuitry in the
power path is whatever is built into the IP5328P module itself; there's no
separate external BMS.

The power budget is tight but workable: ~10–12 W typical draw (Pi 4B with
display active, Arduino + AD8232, display backlight) against an ~18 W
worst-case peak, versus the module's 18 W maximum — the margin holds
because every component's peak is unlikely to land at the same instant.
The IP5328P also manages the battery's minimum discharge cutoff; the
Raspberry Pi's exact behavior at that cutoff (clean shutdown vs. abrupt
loss of power mid-write) hasn't been verified end-to-end, which is why it
shows up again as a residual risk to the SD card (see the README's
Production-readiness section).

*Sources: `docs/Complete_Project_Documentation.md`, Part 3 §2.5, §2.6, §3,
§6, §11. No
application code is involved in this decision.*

### 2. Tracing an EMI problem to its physical cause

The symptom was intermittent visual artifacts on the display. The root
cause traced back to the IP5328P boost converter's switching inductor,
which operates at 300 kHz–1 MHz per its datasheet, radiating near-field
onto the DSI flex cable a few centimetres away — a cable that is entirely
unshielded and, by necessity, loops (~4 cm diameter) through a tight
interior to absorb its excess length.

The fix is a directional "L"-shaped shield: copper adhesive tape on an
insulating substrate (rigid cardboard or a plastic sheet), interposed
between the converter and the cable. Two choices in that design are worth
calling out specifically:

- **It's deliberately open on two sides**, not a full enclosure. A full
  Faraday cage around the module would also trap the heat it generates,
  fighting the case's natural-convection cooling path through its side
  vents — the shield's geometry was chosen to block the direct
  line-of-sight coupling path to the cable without becoming a thermal
  problem.
- **It's grounded**, via a wire soldered from the copper tape to the GND
  pin on the Arduino's perfboard. Because the Arduino and the Pi already
  share a ground reference through their USB connection, this ties the
  shield into a common low-impedance plane. An ungrounded shield at these
  frequencies doesn't just fail to help — it can behave as a resonant
  antenna of its own, making the coupling worse than doing nothing.

*Sources: `docs/Complete_Project_Documentation.md`, Part 3 §2.4, §4, §7.*

### 3. Rejecting the noise that shielding can't stop

The system has two genuinely different noise sources, and conflating them
would mean applying the wrong fix to at least one:

- The boost converter's switching noise (previous entry) is a **near-field,
  line-of-sight** coupling onto a cable a few centimetres away — physical
  shielding is the natural answer because it interrupts a direct radiative
  path.
- The **ECG electrode leads**, by contrast, are unshielded on purpose (they
  have to touch skin) and act as an antenna for the ambient 50 Hz mains hum
  in the room they happen to be used in — a source that has nothing to do
  with the boost converter and isn't reachable by a shield placed near it.

The second source is rejected digitally instead: a 50 Hz IIR notch filter
(Q = 30) is cascaded, as second-order sections, with the main bandpass
filter before R-peak detection ever sees the signal.

```python
# pure_trace/signal_processing.py
b, a = iirnotch(config.NOTCH_FREQ, Q=config.NOTCH_Q, fs=fs)   # 50.0 Hz, Q=30.0
sos_notch = tf2sos(b, a)
sos_bp = butter(config.BANDPASS_ORDER,
                [config.BANDPASS_LOW, config.BANDPASS_HIGH],   # 0.05–40 Hz, order 4
                btype='bandpass', fs=fs, output='sos')
self._sos = np.vstack([sos_notch, sos_bp])
```

Two coupling paths, two fixes, each applied physically at the point where
the corresponding source actually is — rather than one broad-spectrum
mitigation thrown at the whole system in the hope it covers everything.

*Sources: `pure_trace/signal_processing.py` (`DigitalFilter.__init__`);
`pure_trace/config.py` (`NOTCH_FREQ`, `NOTCH_Q`, `BANDPASS_LOW/HIGH`);
`docs/Complete_Project_Documentation.md`, Part 3 §4.*

### 4. Designing firmware for a link that will drop samples

On the firmware side (per Part 3 of `docs/Complete_Project_Documentation.md`
and the project's
own documentation — the `.ino` source itself wasn't available for direct
review here): the Arduino sends a plain-text protocol, `D,<seq>,<val>\n`
for ECG samples and `L,0`/`L,1\n` for lead-off status, at 500 Hz over a
115200-baud link — about 48% bandwidth utilization, not a lot of headroom.
Timing uses `micros()` rather than `delay()` so the sampling clock doesn't
drift, and before every transmission the firmware checks
`Serial.availableForWrite()`: if the 64-byte TX buffer is full, the sample
is **skipped**, not blocked on — blocking here would stall the sampling
loop and inject jitter into the timing of every sample that follows. The
sequence counter (wrapping 0–255) still advances on a skipped sample, so
the gap is visible to whatever reads the stream instead of silently
disappearing.

On the desktop side (verified directly): a lost or skipped sample is
handled by two purpose-built primitives.

```python
# pure_trace/signal_processing.py
def interpolate_gap(prev: float, curr: float, gap: int) -> List[float]:
    if gap <= 0:
        return []
    return [prev + (curr - prev) * k / (gap + 1) for k in range(1, gap + 1)]
```

The serial-reading thread (`_SerialThread` in `acquisition_screen.py`,
exercised by `tests/test_serial_gap.py` but not directly read here) uses
this to linearly reconstruct small gaps — up to a bounded maximum,
`_MAX_GAP_FILL` — from the sequence-number discontinuity it observes.
Beyond that threshold the gap is treated as real: the samples aren't
invented, they're counted (`dropped`) and the recording is flagged
(`has_unfilled_gap`) so it can be treated as unscorable rather than
silently including fabricated time in the RR-interval timebase.

*Sources: `pure_trace/signal_processing.py` (`interpolate_gap`);
`tests/test_serial_gap.py`; `docs/Complete_Project_Documentation.md`,
Part 3 §2.2.*

---

## Software

### 1. Calibrating the baseline thresholds correctly, not just plausibly

The baseline model classifies a new session by its squared Mahalanobis
distance from the patient's own pool of past feature vectors (mean HR,
SDNN, RMSSD, pNN50). The naive approach — treating that squared distance as
χ²-distributed — implicitly assumes the pool's mean and covariance are
*known*, when in fact they're *estimated* from a handful of sessions.
Treating an estimate as if it were the truth understates the real
uncertainty, and the effect isn't small: per `config.py`'s own comment on
`MIN_BASELINE_SESSIONS`, the χ² approach produced a false-RED rate of
roughly 20% at 5 sessions, against an intended ~1%.

The fix uses two-sample Hotelling T² theory instead: under normality, the
rescaled distance follows an F distribution whose degrees of freedom are
tied to both the pool size and the number of features (4), and the
GREEN/YELLOW and YELLOW/RED thresholds are derived from that F distribution
at the configured quantiles:

```python
# pure_trace/config.py
MIN_BASELINE_SESSIONS = 5    # sessioni lunghe minime prima di scorare
CHI2_GREEN_P = 0.95          # quantile soglia GREEN/YELLOW
CHI2_YELLOW_P = 0.99         # quantile soglia YELLOW/RED
```

(The `CHI2_*` names are a holdover from the discarded χ² approach and no
longer describe what the thresholds are actually computed from — worth a
rename.) Thresholds widen automatically as the pool shrinks, verified by
`tests/test_baseline_model.py::test_thresholds_widen_as_pool_shrinks`, and
the parametrized false-positive-rate test
(`test_false_positive_rate_matches_target`) checks the ~1%/~5% targets
hold at n = 5, 8, 12, and 25. When the pool is too small for the F
distribution to have valid degrees of freedom (n ≤ number of features), the
classification stays NEUTRAL instead of producing a number with no
statistical footing.

*Sources: `pure_trace/config.py` (`MIN_BASELINE_SESSIONS`,
`COV_RIDGE_EPS`, `CHI2_GREEN_P`/`CHI2_YELLOW_P`); `tests/test_baseline_model.py`;
`BaselineModel` in `analysis_engine.py` (source not directly available —
described from its tests and `config.py`).*

### 2. Deciding what signal fidelity actually means

`RPeakDetector` fires the instant a sample first crosses its adaptive
threshold — not on the true peak of the R-wave. That's fine for a live
heart-rate readout, but the lag between "threshold crossed" and "true
apex" isn't constant: R-wave amplitude is itself modulated by breathing, so
the lag jitters from beat to beat. That jitter leaks directly into RMSSD, a
metric defined entirely in terms of *successive* beat-to-beat
differences — exactly the quantity a variable timing lag corrupts.

The offline analysis pass corrects for this with "apex snapping": after
the same threshold-crossing detection, it searches a further window for
the true local maximum before finalizing the beat's index.

```python
# pure_trace/config.py
APEX_SEARCH_S = 0.050   # copre il fronte di salita del QRS (~40 ms),
                         # resta ben sotto il refrattario (200 ms)
```

50 ms is wide enough to cover the QRS upstroke (~40 ms) but comfortably
inside the 200 ms refractory period, so the search can never accidentally
latch onto the *next* beat. Per the project's own account (not
independently re-measured here), this correction reduces RMSSD error from
roughly +5% to roughly +1%.

Critically, this correction is applied only to the **detected R-peak
indices** used for HRV metrics — it never touches the saved signal itself.
`EDFWriter.save()` writes the raw ADC-derived trace, normalized to
[-1, 1] and explicitly labeled `"a.u."` rather than calibrated
millivolts, completely independent of whatever detection or correction
logic runs on top of it. Filtering and detection refinements exist only to
compute better numbers and a better live display; the thing that leaves
the device as an exported session is always the untouched raw waveform.

*Sources: `pure_trace/signal_processing.py` (`RPeakDetector.step`/`process`);
`pure_trace/config.py` (`APEX_SEARCH_S`, `REFRACTORY_MS`);
`pure_trace/data_layer.py` (`EDFWriter.save`); the apex-snapping function
itself, `_snap_to_apex` in `analysis_engine.py`, was not directly
available for this pass.*

### 3. Not leaking data through metadata

AES-GCM is authenticated encryption: it hides the plaintext's content and
guarantees it hasn't been tampered with, but it does nothing to hide the
plaintext's *length* — ciphertext size tracks plaintext size almost
exactly. Two of Pure-Trace's derived files scale directly with the number
of heartbeats in a session: the per-beat colormap (one byte per RR
interval) and the feature file's `rr_peaks` index list. Without
mitigation, anyone with read access to the SD card — no password required —
could infer a session's exact beat count, and from that its average heart
rate, from file size alone.

```python
# pure_trace/secure_store.py
PAD_BLOCK = 4096
_PAD_MAGIC = b"PTPAD1"

def _pad(data: bytes) -> bytes:
    body = _PAD_MAGIC + len(data).to_bytes(8, "big") + data
    return body + b"\x00" * (-len(body) % PAD_BLOCK)
```

Every JSON payload and numpy array is padded to a fixed multiple of 4096
bytes, prefixed with a small 14-byte header (magic + real length), before
being encrypted; `_unpad()` strips it back off after decryption. This is
verified directly: `tests/test_padding.py::test_json_file_size_hides_content_length`
and its `.npy` counterpart confirm that sessions with 60, 90, 120, and 160
beats all produce **identically-sized** encrypted files. Files written
before this mechanism existed are recognized by the *absence* of the magic
bytes and returned unmodified — no migration step, and no ambiguity,
since a real JSON payload starts with `{` and a real `.npy` file starts
with NumPy's own magic string, neither of which collides with `PTPAD1`.

*Sources: `pure_trace/secure_store.py` (`_pad`, `_unpad`, `PAD_BLOCK`,
`_PAD_MAGIC`, `write_json`/`write_npy`); `tests/test_padding.py`.*

### 4. Treating "no data" and "corrupted data" as different failure modes

`secure_store.read_json()`'s default behavior is permissive: a missing
file, a corrupted one, or one encrypted under the wrong key are all
silently replaced by a caller-supplied default. That's the right behavior
almost everywhere — most callers genuinely don't care *why* data isn't
there. It's actively dangerous for exactly one file: the patient's
baseline. If a baseline file exists but is corrupted (a bad sector, an
interrupted write from an older code path), and the reader can't tell that
apart from "no baseline has ever been recorded," the analysis engine would
treat the pool as empty and rebuild it from a single new vector — silently
destroying however many sessions of history existed before, with nothing
in the log to explain why a patient's baseline suddenly "restarted."

```python
# pure_trace/secure_store.py
def read_json(path, enc, default, strict: bool = False):
    ...
    except (InvalidTag, ValueError, OSError) as exc:
        if strict:
            raise DecryptError(str(path)) from exc
        return default
```

`strict=True` exists for exactly this case: a present-but-undecryptable
file raises `DecryptError` instead of degrading to the default, which (per
the project's own account) `analysis_engine.py`'s baseline loader uses to
disable scoring for that patient until a human resolves it, rather than
quietly resetting the model. This is verified directly by
`tests/test_padding.py::test_corrupt_padded_file_still_raises_in_strict_mode`:
a single flipped bit in an otherwise-valid encrypted file makes strict-mode
reading raise, not degrade. Note that `read_npy()` has **no** `strict`
parameter at all — a deliberate asymmetry, since losing the colormap only
costs the local RR-coloring display, not a patient's history.

*Sources: `pure_trace/secure_store.py` (`read_json`, `DecryptError`;
compare with `read_npy`, which lacks `strict`); `tests/test_padding.py`.*

### 5. Real-time performance on hardware that doesn't have much to spare

`RPeakDetector` needs, on every one of 500 samples per second, the maximum
value inside a rolling ~2-second amplitude window (`config.AMPLITUDE_WINDOW_S`)
to set its adaptive detection threshold. Recomputing `max(window)` from
scratch on every sample is O(window) per sample — on a Raspberry Pi 4B
that's simultaneously running the Qt event loop, live `pyqtgraph`
rendering, and a serial-reading thread, that's real CPU budget spent on a
problem with a much cheaper known solution.

```python
# pure_trace/signal_processing.py
def _window_max(self, sample: float) -> float:
    idx = self._sample_index
    while self._maxq and self._maxq[-1][1] <= sample:
        self._maxq.pop()
    self._maxq.append((idx, sample))
    while self._maxq[0][0] <= idx - self._window_size:
        self._maxq.popleft()
    return self._maxq[0][1]
```

`_maxq` is a monotonically decreasing deque of `(index, value)` pairs: the
front is always the current window's maximum. A new sample pops every
smaller value off the back (they can never become the max again while the
new sample is still inside the window) before being appended, and stale
indices age out of the front once they leave the window — giving amortized
O(1) per sample instead of O(window). The subtlety is correctness around
ties and plateaus, where a careless `<` vs `<=` in the eviction comparison
silently changes which index "wins." This is verified bit-for-bit against
a brute-force `max()` reference across five signal types — noise, a
constant signal, an all-negative signal, all-zero, and a repeated-value
plateau — in
`tests/test_rpeak_detector.py::test_running_max_matches_bruteforce_max`.

*Sources: `pure_trace/signal_processing.py` (`RPeakDetector._window_max`,
`self._maxq`); `pure_trace/config.py` (`AMPLITUDE_WINDOW_S`);
`tests/test_rpeak_detector.py`.*

### 6. Assuming the field will go wrong, because it will

The same underlying discipline shows up at several independent layers of
the codebase, each guarding a different window in which the device might
lose power or a connection mid-operation:

**File writes.** `secure_store.atomic_write()` writes to a temp file,
`fsync()`s the file itself, renames it over the destination, then
`fsync()`s the *containing directory* too:

```python
# pure_trace/secure_store.py
with open(tmp, "wb") as fh:
    fh.write(data)
    fh.flush()
    os.fsync(fh.fileno())
tmp.replace(path)
dir_fd = os.open(path.parent, os.O_RDONLY)
try:
    os.fsync(dir_fd)
finally:
    os.close(dir_fd)
```

Without that last `fsync` on the directory, the rename can be durable on
the file's own inode while the directory entry pointing to it is lost in a
crash — a gap that's easy to miss in a naive "atomic write."

**Profile creation.** `ProfileManager.create_profile()` builds an entire
new profile — sessions folder, `profile.json`, `salt.bin`, `.keycheck`,
`identity.json` — inside a hidden staging directory (`.{uuid}.partial`),
and only `os.rename()`s it into place once every file exists. A bare
`except BaseException` removes the staging directory on any failure and
re-raises, so an interruption mid-creation can never leave a half-built
profile visible to the app. `test_profile_manager.py::test_create_profile_is_atomic`
confirms that a simulated failure leaves *nothing* on disk.

**Profile listing.** `ProfileManager._is_complete()` actively filters out
any profile directory missing `salt.bin`, `.keycheck`, or `profile.json`,
rather than assuming every directory found is valid — this exists
specifically because an old, interrupted-creation directory (left over
from before the previous fix existed) would otherwise raise an unhandled
`FileNotFoundError` at login and crash the whole application; now it's
silently skipped with a log warning
(`test_profile_manager.py::test_incomplete_profile_is_hidden_from_picker`).

**Serial data.** `interpolate_gap()` and `CircularBuffer.take_dropped()`
(see [Hardware #4](#4-designing-firmware-for-a-link-that-will-drop-samples))
turn "a sample went missing" from a silent event into either a small,
linearly-reconstructed correction or an explicitly counted drop — either
way, something the rest of the pipeline can see and act on, instead of a
quiet shift in the RR-interval timebase that would corrupt every
downstream HRV metric with no visible symptom.

Each of these is the same idea applied at a different layer: assume the
operation will be interrupted partway through, and design so that an
interruption always leaves either the old, complete state or the new,
complete state — never something in between.

*Sources: `pure_trace/secure_store.py` (`atomic_write`);
`pure_trace/data_layer.py` (`ProfileManager.create_profile`/`list_profiles`/`_is_complete`);
`pure_trace/signal_processing.py` (`interpolate_gap`, `CircularBuffer.take_dropped`);
`tests/test_profile_manager.py`; `tests/test_serial_gap.py`.*