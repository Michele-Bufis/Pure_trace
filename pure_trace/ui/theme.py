"""
pure_trace/ui/theme.py
Single source of truth for the visual design of Pure-Trace.

Why this module exists
----------------------
The UI used to hardcode colours inline (``#00d4aa``, ``#555`` …) scattered
across every screen. That made the look inconsistent and impossible to change
in one place. Here every colour lives once, as a named token, and the screens
reference these tokens instead of raw hex.

Design system: **clinical "Accessible & Ethical" light theme**. Near-white
surfaces with a faint teal tint, slate text, a single restrained *clinical teal*
accent, and semantic green/amber/red reserved strictly for medical status.
Card-based hierarchy, ≥44px touch targets, visible focus rings. Body and
secondary text verified ≥ 4.5:1 against the background (WCAG AA). This module
imports NO PyQt5, so it is safe to import in the test environment where Qt is
absent.
"""

# --------------------------------------------------------------------------- #
#  Palette — neutral surfaces (light, faint teal tint)                         #
# --------------------------------------------------------------------------- #
BG        = "#F4F8FA"   # app canvas (very light teal-grey)
SURFACE   = "#FFFFFF"   # raised surfaces: cards, inputs, buttons
SURFACE_2 = "#EDF3F5"   # subtle fills: hover, recessed strips, segmented track
BORDER    = "#D9E3E8"   # hairlines, separators
BORDER_2  = "#C6D5DC"   # stronger border (chevrons, idle outlines)

# --------------------------------------------------------------------------- #
#  Palette — accent + text                                                     #
# --------------------------------------------------------------------------- #
ACCENT    = "#0E7C8B"   # clinical teal — primary actions
ACCENT_D  = "#0A5E6A"   # pressed / active teal
ACCENT_SF = "#E2F2F4"   # teal tint fill (selected chips, soft buttons)
ON_ACCENT = "#FFFFFF"   # text/icon on top of the accent
TEXT      = "#15323A"   # primary text (~13:1 on BG)
MUTED     = "#5A727C"   # secondary text (slate, AA safe on BG)
TRACE     = "#102A30"   # ECG line: near-black, like clinical ECG paper
DANGER    = "#DC2626"   # destructive action (red-600)

# --------------------------------------------------------------------------- #
#  Palette — semantic status (drives the per-RR colormap and session badge)    #
# --------------------------------------------------------------------------- #
GREEN   = "#1B9E4B"     # consistent / dinamica RR locale entro norma   green
YELLOW  = "#D97706"     # scostamento intermedio                        amber
RED     = "#DC2626"     # unusual (Mahalanobis) / outlier RR locale     red
NEUTRAL = MUTED         # no baseline yet / not enough data

# soft tinted backgrounds for status pills/tags (high-contrast coloured text)
GREEN_SF = "#E7F6EC"
AMBER_SF = "#FCEFD9"
RED_SF   = "#FBE6E6"

#: status string -> hex, used by both screens
STATUS = {
    "GREEN":   GREEN,
    "YELLOW":  YELLOW,
    "RED":     RED,
    "NEUTRAL": NEUTRAL,
}

#: status colour -> soft background tint (for pills/tags); default to SURFACE_2
SOFT = {
    GREEN:  GREEN_SF,
    YELLOW: AMBER_SF,
    RED:    RED_SF,
    MUTED:  SURFACE_2,
}

#: human label per status (Italian), for the soft status tags/pills
STATUS_LABEL = {
    "GREEN":   "Nella norma",
    "YELLOW":  "Lieve variazione",
    "RED":     "Fuori baseline",
    "NEUTRAL": "Non valutata",
}

#: colormap uint8 code -> hex (code 255 = neutral band)
STRIP = {
    0:   GREEN,
    1:   YELLOW,
    2:   RED,
    255: BORDER,
}
STRIP_EMPTY = SURFACE_2   # fill colour when a strip has no data

#: alpha (0-255) for translucent RR bands painted over the light ECG plot
BAND_ALPHA = {0: 55, 1: 60, 2: 70}

# --------------------------------------------------------------------------- #
#  Global application stylesheet                                               #
# --------------------------------------------------------------------------- #

def global_stylesheet() -> str:
    """QSS applied once at app startup (``app.setStyleSheet``).

    Styles every standard widget coherently — including the ones the screens
    never styled by hand (lists, inputs, scrollbars, tooltips). Touch targets
    are ≥ 44px and focus rings are visible, as required for a touchscreen
    medical device.
    """
    return f"""
    QWidget {{
        background: {BG};
        color: {TEXT};
        font-family: 'Figtree', 'Inter', 'Segoe UI', 'Noto Sans', 'DejaVu Sans', sans-serif;
        font-size: 15px;
    }}
    QPushButton {{
        background: {SURFACE};
        color: {TEXT};
        border: 1px solid {BORDER};
        border-radius: 10px;
        padding: 10px 16px;
        min-height: 44px;
    }}
    QPushButton:hover    {{ border-color: {ACCENT}; }}
    QPushButton:pressed  {{ background: {SURFACE_2}; }}
    QPushButton:focus    {{ border: 2px solid {ACCENT}; outline: none; }}
    QPushButton:disabled {{ color: {MUTED}; border-color: {BORDER}; }}

    QLineEdit {{
        background: {SURFACE};
        border: 1.5px solid {BORDER};
        border-radius: 11px;
        padding: 12px 14px;
        min-height: 44px;
        selection-background-color: {ACCENT};
        selection-color: {ON_ACCENT};
    }}
    QLineEdit:focus {{ border: 2px solid {ACCENT}; }}

    QListWidget {{
        background: {SURFACE};
        border: 1px solid {BORDER};
        border-radius: 11px;
        outline: none;
        padding: 4px;
    }}
    QListWidget::item          {{ padding: 13px; border-radius: 8px; }}
    QListWidget::item:hover    {{ background: {SURFACE_2}; }}
    QListWidget::item:selected {{ background: {ACCENT_SF}; color: {ACCENT}; }}

    QScrollArea {{ border: none; }}
    QScrollBar:vertical {{ background: {BG}; width: 10px; margin: 0; }}
    QScrollBar::handle:vertical {{
        background: {BORDER_2}; border-radius: 5px; min-height: 30px;
    }}
    QScrollBar::handle:vertical:hover {{ background: {MUTED}; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}

    QToolTip {{
        background: {SURFACE}; color: {TEXT};
        border: 1px solid {BORDER}; padding: 6px; border-radius: 6px;
    }}
    """


# --------------------------------------------------------------------------- #
#  Component-specific QSS builders                                             #
#  (kept here so NO raw hex lives in the screen files)                         #
# --------------------------------------------------------------------------- #

def card_qss() -> str:
    """Generic raised card: white surface, hairline border, rounded."""
    return (
        f"QFrame{{background:{SURFACE};border:1px solid {BORDER};border-radius:16px}}"
    )


def top_bar_qss() -> str:
    """The slim app header bar (brand + profile + clock + status)."""
    return (
        f"QFrame{{background:{SURFACE};border:none;"
        f"border-bottom:1px solid {BORDER}}}"
    )


def brand_logo_qss() -> str:
    """Small rounded teal tile holding the wordmark glyph."""
    return (
        f"color:{ON_ACCENT};background:{ACCENT};border-radius:7px;"
        f"font-size:14px;font-weight:bold"
    )


def chip_qss() -> str:
    """Profile chip in the top bar."""
    return (
        f"color:{TEXT};background:{SURFACE_2};border:1px solid {BORDER};"
        f"border-radius:14px;padding:5px 12px;font-size:13px;font-weight:600"
    )


def clock_qss() -> str:
    return f"color:{TEXT};font-size:14px;font-weight:600;border:none"


def leads_pill_qss(ok: bool) -> str:
    """Leads-off status pill: soft tinted background, coloured text + dot."""
    color = GREEN if ok else RED
    bg = GREEN_SF if ok else RED_SF
    return (
        f"color:{color};background:{bg};border-radius:14px;"
        f"padding:6px 13px;font-size:13px;font-weight:600"
    )


def segment_button_qss() -> str:
    """One cell of the duration segmented control (30s / 2 min toggle)."""
    return (
        f"QPushButton{{background:transparent;color:{MUTED};"
        f"border:none;border-radius:8px;padding:9px;min-height:40px;font-weight:600}}"
        f"QPushButton:checked{{background:{SURFACE};color:{ACCENT};"
        f"border:1px solid {BORDER}}}"
    )


def segment_track_qss() -> str:
    """The recessed track that holds the segmented control buttons."""
    return f"QFrame{{background:{SURFACE_2};border-radius:11px}}"


def section_label_qss() -> str:
    """Tiny uppercase caption above a control group / metric."""
    return (
        f"color:{MUTED};font-size:11px;font-weight:600;"
        f"letter-spacing:1px;border:none"
    )


def rec_button_qss(*, recording: bool = False) -> str:
    """Big record/stop button. Accent (primary) when idle, muted while recording."""
    if recording:
        return (
            f"QPushButton{{background:{SURFACE_2};color:{TEXT};"
            f"border:1px solid {BORDER};border-radius:14px}}"
        )
    return (
        f"QPushButton{{background:{ACCENT};color:{ON_ACCENT};border:none;border-radius:14px}}"
        f"QPushButton:pressed{{background:{ACCENT_D}}}"
        f"QPushButton:disabled{{background:{SURFACE_2};color:{MUTED}}}"
    )


def hr_value_qss() -> str:
    """The big heart-rate number (hero metric)."""
    return f"color:{ACCENT};font-size:60px;font-weight:bold;border:none"


def result_box_qss(color: str) -> str:
    """Result banner after an acquisition: readable dark text, status shown by
    a coloured left border (keeps text contrast high)."""
    return (
        f"color:{TEXT};background:{SURFACE_2};border-left:4px solid {color};"
        f"padding:12px;border-radius:10px"
    )


def status_pill_qss(color: str) -> str:
    """Soft status pill: coloured text + matching tinted background (the dot is a
    separate label). Falls back to a neutral fill for unknown colours."""
    bg = SOFT.get(color, SURFACE_2)
    return (
        f"color:{color};background:{bg};font-size:13px;font-weight:600;"
        f"padding:6px 13px;border-radius:14px"
    )


def status_tag_qss(color: str) -> str:
    """Small uppercase status tag used in the archive list rows."""
    bg = SOFT.get(color, SURFACE_2)
    return (
        f"color:{color};background:{bg};font-size:11px;font-weight:bold;"
        f"padding:3px 10px;border-radius:12px"
    )


def dur_pill_qss() -> str:
    """Duration pill (e.g. '2 min') in an archive row."""
    return (
        f"color:{MUTED};background:{SURFACE_2};font-size:12px;"
        f"padding:2px 9px;border-radius:10px"
    )


def metric_chip_qss() -> str:
    """Inline metric chip (SDNN 48 ms …) in an archive row."""
    return (
        f"color:{MUTED};background:{SURFACE_2};border:1px solid {BORDER};"
        f"font-size:11px;padding:3px 9px;border-radius:7px"
    )


def metric_value_qss(active: bool) -> str:
    """Big number inside a metric card; strong text when present, muted for '—'."""
    color = TEXT if active else MUTED
    return f"color:{color};font-size:22px;font-weight:bold;border:none"


def metric_value_tint_qss(color: str) -> str:
    """Come metric_value_qss(active=True) ma con colore di scostamento."""
    return f"color:{color};font-size:22px;font-weight:bold;border:none"


def metric_card_qss() -> str:
    return (
        f"QFrame{{background:{SURFACE};border-radius:12px;border:1px solid {BORDER}}}"
    )


def session_card_qss() -> str:
    """A single tappable session row, styled as a card."""
    return (
        f"QFrame{{background:{SURFACE};border:1px solid {BORDER};border-radius:12px}}"
        f"QFrame:hover{{border-color:{ACCENT}}}"
    )


def icon_button_qss() -> str:
    """Square icon button (back arrow in the detail header)."""
    return (
        f"QPushButton{{background:{SURFACE};color:{TEXT};"
        f"border:1px solid {BORDER};border-radius:10px;"
        "padding:0;min-width:0;min-height:0}"
        f"QPushButton:pressed{{background:{SURFACE_2}}}"
    )


def export_button_qss() -> str:
    """Primary action — filled teal."""
    return (
        f"QPushButton{{background:{ACCENT};color:{ON_ACCENT};"
        f"border:none;border-radius:11px;min-height:0;font-weight:600}}"
        f"QPushButton:pressed{{background:{ACCENT_D}}}"
        f"QPushButton:disabled{{background:{SURFACE_2};color:{MUTED}}}"
    )


def delete_button_qss() -> str:
    """Destructive action (delete) — danger outline."""
    return (
        f"QPushButton{{background:{SURFACE};color:{DANGER};"
        f"border:1.5px solid {DANGER};border-radius:11px;min-height:0;font-weight:600}}"
        f"QPushButton:disabled{{background:{SURFACE};color:{MUTED};border-color:{BORDER}}}"
    )


def tab_button_qss() -> str:
    return (
        f"QPushButton{{background:{SURFACE};color:{MUTED};border:none;"
        f"border-top:2.5px solid transparent;font-size:12px;font-weight:600;min-height:0}}"
        f"QPushButton:checked{{color:{ACCENT};border-top:2.5px solid {ACCENT}}}"
    )
