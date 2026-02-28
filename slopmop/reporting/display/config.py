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

# Overrun severity thresholds (standard deviations above mean).
# When a check's elapsed time rises above mean + Nσ the progress
# indicator escalates colour.
#   0-1σ: normal       — within expected variance
#   1-2σ: yellow       — taking notably longer
#   2-3σ: orange/amber — something may be wrong
#   ≥ 3σ: red          — significantly over expected time
OVERRUN_WARN_SIGMA = 1.0  # Yellow
OVERRUN_CAUTION_SIGMA = 2.0  # Orange
OVERRUN_ALERT_SIGMA = 3.0  # Red

# Minimum number of samples before standard-deviation-based
# thresholds kick in.  With fewer samples the std dev is unreliable
# so we fall back to a simple "over 2× mean" heuristic.
MIN_SAMPLES_FOR_SIGMA = 3

# Column widths for status word (passed/failed/etc.)
STATUS_COLUMN_WIDTH = 8  # "passed" = 6, "failed" = 6, "skipped" = 7, padding
