"""Display configuration constants.

Centralizes magic numbers and visual elements for the dynamic display.
"""

# Animation settings
REFRESH_RATE_HZ = 10  # Frames per second for animation
REFRESH_INTERVAL = 1.0 / REFRESH_RATE_HZ  # 0.1 seconds

# Spinner frames (Braille dots pattern - smooth animation)
SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

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

# Stop timeout (seconds to wait for animation thread)
STOP_TIMEOUT = 0.5

# Minimum progress bar width before falling back to simple display
MIN_PROGRESS_BAR_WIDTH = 12
MIN_BAR_CONTENT_WIDTH = 5  # Minimum bar content (inside brackets)
