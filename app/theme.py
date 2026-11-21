"""The single place for every value the end user sees.

Colour, spacing, type steps and the status vocabulary live here and nowhere
else, so a change lands once. Chart palettes are the validated reference
instance: the 3-slot categorical set clears all-pairs CVD and normal-vision
floors in both modes, and the ordinal funnel ramp clears monotone lightness
with visible step gaps. Dark steps are selected for the dark surface, not an
automatic flip of the light ones.
"""

from __future__ import annotations

import streamlit as st

# --- Spacing ------------------------------------------------------------
# Base 8; the multiples the app writes are 4, 8, 16, 24, 32.
SPACE_BASE = 8
SPACE = {"xs": 4, "sm": 8, "md": 16, "lg": 24, "xl": 32}

# --- Chart surfaces (the validator's reference) --------------------------
SURFACE = {"light": "#fcfcfb", "dark": "#1a1a19"}

# Text tokens for chart labels: values and names wear text colour, never a
# series colour, and each mode has its own step.
TEXT_PRIMARY = {"light": "#0b0b0b", "dark": "#f0efec"}
TEXT_SECONDARY = {"light": "#52514e", "dark": "#c3c2b7"}

# --- Categorical slots, fixed order, never cycled -----------------------
CATEGORICAL = {
    "light": ["#2a78d6", "#eb6834", "#1baf7a", "#eda100",
              "#e87ba4", "#008300", "#6250d6", "#e34948"],
    "dark": ["#3987e5", "#d95926", "#199e70", "#c98500",
             "#d55181", "#0ca30c", "#9085e9", "#e66767"],
}

# Single hue for magnitude (one series, sorted bars, heat values).
SEQUENTIAL = {"light": "#2a78d6", "dark": "#3987e5"}

# Ordinal ramp for the approval funnel: light->dark, gaps >= 0.06 L.
ORDINAL = {
    "light": ["#86b6ef", "#5598e7", "#2a78d6", "#1c5cab", "#104281"],
    "dark": ["#184f95", "#256abf", "#3987e5", "#6da7ec", "#9ec5f4"],
}

# Status palette — fixed, never themed, never reused as a series colour.
STATUS_COLOUR = {
    "good": "#0ca30c",
    "warning": "#fab219",
    "serious": "#ec835a",
    "critical": "#d03b3b",
}

# --- Application status vocabulary --------------------------------------
# Every status carries a badge colour AND an icon, so colour never carries
# the meaning on its own.
APP_STATUSES = [
    "Draft",
    "Submitted",
    "Under Verification",
    "Correction Required",
    "Approved",
    "Rejected",
    "Locked",
]

STATUS_BADGE = {
    "Draft": ("grey", ":material/edit_note:"),
    "Submitted": ("blue", ":material/outbox:"),
    "Under Verification": ("violet", ":material/fact_check:"),
    "Correction Required": ("orange", ":material/report:"),
    "Approved": ("green", ":material/verified:"),
    "Rejected": ("red", ":material/cancel:"),
    "Locked": ("primary", ":material/lock:"),
}

# Secondary vocabularies, same shape.
DECISION_BADGE = {
    "Approved": ("green", ":material/check_circle:"),
    "Rejected": ("red", ":material/cancel:"),
    "Sent Back": ("orange", ":material/undo:"),
    "Hold": ("grey", ":material/pause_circle:"),
    "Escalated": ("violet", ":material/arrow_upward:"),
    "Pending": ("blue", ":material/schedule:"),
}

CORRECTION_BADGE = {
    "Open": ("orange", ":material/report:"),
    "Assigned": ("blue", ":material/assignment_ind:"),
    "Responded": ("violet", ":material/reply:"),
    "Closed": ("green", ":material/task_alt:"),
}

UNLOCK_BADGE = {
    "Requested": ("orange", ":material/key:"),
    "Approved": ("green", ":material/lock_open:"),
    "Rejected": ("red", ":material/cancel:"),
    "Relocked": ("primary", ":material/lock:"),
}

VERIFICATION_BADGE = {
    "Pass": ("green", ":material/check_circle:"),
    "Fail": ("red", ":material/error:"),
}


def mode() -> str:
    """The theme the viewer is actually looking at: 'light' or 'dark'.

    A base forced in config wins, because Streamlit renders it whatever the
    viewer's system says — while st.context.theme would still report the
    system preference. With no base forced (the shipped config), the two agree.
    """
    try:
        forced = st.get_option("theme.base")
    except Exception:  # pragma: no cover
        forced = None
    if forced in ("light", "dark"):
        return forced
    try:
        kind = getattr(st.context.theme, "type", None)
    except Exception:  # pragma: no cover - older runtimes / bare script runs
        kind = None
    return kind if kind in ("light", "dark") else "light"


def categorical(n: int = 3) -> list[str]:
    """The first n categorical slots, in fixed order, for the live theme."""
    slots = CATEGORICAL[mode()]
    if n > len(slots):
        raise ValueError("a 9th series folds into 'Other' or facets; it is never a new hue")
    return slots[:n]


def sequential() -> str:
    return SEQUENTIAL[mode()]


def ordinal(n: int = 5) -> list[str]:
    ramp = ORDINAL[mode()]
    return ramp[:n]


def surface() -> str:
    return SURFACE[mode()]


def text_secondary() -> str:
    return TEXT_SECONDARY[mode()]
