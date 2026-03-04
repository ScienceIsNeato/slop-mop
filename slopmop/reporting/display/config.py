"""Display configuration constants.

Centralizes magic numbers and visual elements for the dynamic display.
"""

# Animation settings
REFRESH_RATE_HZ = 10  # Frames per second for animation
REFRESH_INTERVAL = 1.0 / REFRESH_RATE_HZ  # 0.1 seconds

# Default spinner frames (Braille dots pattern - smooth animation)
SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

# Waiting indicator frames for pending checks (gentle pulse)
WAITING_FRAMES = ["○", "○", "◌", "◌"]

# Column widths for right-aligned content
TIME_COLUMN_WIDTH = 12  # "Time Elapsed"
ETA_COLUMN_WIDTH = 14  # "Est. Time Rem."

# Dot leader characters for animated fill on running checks
DOT_CHAR = "·"
PULSE_CHAR = "•"
PULSE_WIDTH = 3  # How many chars wide the bright pulse is

# Progress bar characters
PROGRESS_FILL = "█"
PROGRESS_EMPTY = "░"

# Terminal defaults
DEFAULT_TERMINAL_WIDTH = 80

# Output preview limits (for failure details)
MAX_PREVIEW_LINES = 10
MAX_PREVIEW_WIDTH = 60  # Max chars for inline failure preview

# Stop timeout (seconds to wait for animation thread)
STOP_TIMEOUT = 0.5

# Minimum progress bar width before falling back to simple display
MIN_PROGRESS_BAR_WIDTH = 12
MIN_BAR_CONTENT_WIDTH = 5  # Minimum bar content (inside brackets)

# Category display order — flaw categories first, then meta
CATEGORY_ORDER = [
    "overconfidence",
    "deceptiveness",
    "laziness",
    "myopia",
    "pr",
]

# Category header line character
HEADER_DASH = "─"

# Indent for check lines under category headers
CHECK_INDENT = "   "  # 3 spaces

# Overrun severity thresholds (IQR units above Tukey fence).
# The Tukey fence is Q3 + 1.5 × IQR — the textbook outlier boundary.
# iqr_over() returns 0 at the fence, so these thresholds measure how
# far *past* it the elapsed time has gone, in multiples of IQR.
#
#   below fence:  no color   — within expected statistical range
#   0 – 1 IQR:    yellow     — mild outlier (Q3+1.5×IQR to Q3+2.5×IQR)
#   1 – 2.5 IQR:  orange     — moderate outlier
#   ≥ 2.5 IQR:   red        — extreme outlier (Q3+4.0×IQR)
OVERRUN_WARN_IQR = 0.0  # Yellow (any amount past Tukey fence)
OVERRUN_CAUTION_IQR = 1.0  # Orange (Q3 + 2.5×IQR)
OVERRUN_ALERT_IQR = 2.5  # Red (Q3 + 4.0×IQR)

# Minimum number of samples before IQR-based thresholds kick in.
# Quartiles need at least 5 data points to be meaningful; with
# fewer we fall back to a simple "over 2× median" heuristic.
MIN_SAMPLES_FOR_IQR = 5

# Column widths for status word (done/skipped)
STATUS_COLUMN_WIDTH = 8  # "skipped" = 7 + 1 padding

# ── Two-panel column layout ─────────────────────────────────────
# The completed-check and header lines use two horizontal sections:
#   LEFT:   icon + name + status
#   RIGHT:  timing data (actual time, history sparkline)
# Scope metrics (files, LOC) are shown only in the final summary line.

# Timing columns (right panel)
TIMING_TIME_WIDTH = (
    12  # this-run duration     e.g. "      0.5s"  (header: "act duration")
)
TIMING_AVG_WIDTH = (
    12  # expected duration     e.g. "      0.2s"  (header: "exp duration")
)
TIMING_SPARK_WIDTH = 8  # sparkline history    e.g. "⸱⸱⸱█▅▅▄▁"
TIMING_SEP = "  "  # gap between timing sub-columns

# Column header labels — built from the same width constants as data
# rows so columns align vertically.  Kept as module-level strings for
# convenience; referenced by build_column_header_line().
TIMING_HEADER = (
    "act duration".rjust(TIMING_TIME_WIDTH)
    + TIMING_SEP
    + "exp duration".rjust(TIMING_AVG_WIDTH)
    + TIMING_SEP
    + "history".ljust(TIMING_SPARK_WIDTH)
)
