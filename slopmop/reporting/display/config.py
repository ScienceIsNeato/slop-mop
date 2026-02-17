"""Display configuration constants.

Centralizes magic numbers and visual elements for the dynamic display.
"""

from typing import Dict, Tuple

# Animation settings
REFRESH_RATE_HZ = 10  # Frames per second for animation
REFRESH_INTERVAL = 1.0 / REFRESH_RATE_HZ  # 0.1 seconds

# Default spinner frames (Braille dots pattern - smooth animation)
SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

# Category-specific spinners (#7: distinct spinners per category)
CATEGORY_SPINNERS: Dict[str, Tuple[str, ...]] = {
    "python": ("🐍", "🐍", "🐍", "🐍"),  # Snake animation effect
    "javascript": ("📦", "📦", "📦", "📦"),  # Package
    "security": ("🔐", "🔓", "🔐", "🔓"),  # Lock/unlock
    "quality": ("📊", "📈", "📉", "📊"),  # Charts
    "general": ("🔧", "🔩", "🔧", "🔩"),  # Tools
    "integration": ("🎭", "🎭", "🎭", "🎭"),  # Drama masks
    "pr": ("🔀", "🔀", "🔀", "🔀"),  # Merge
}

# Category display info: (emoji, display_name, header_color_code)
CATEGORY_INFO: Dict[str, Tuple[str, str]] = {
    "python": ("🐍", "Python"),
    "javascript": ("📦", "JavaScript"),
    "security": ("🔐", "Security"),
    "quality": ("📊", "Quality"),
    "general": ("🔧", "General"),
    "integration": ("🎭", "Integration"),
    "pr": ("🔀", "Pull Request"),
}

# Category display order (top to bottom)
CATEGORY_ORDER = [
    "security",
    "python",
    "javascript",
    "quality",
    "general",
    "pr",
    "integration",
]

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

# Box-drawing characters (#6: Unicode box drawing)
BOX_TOP_LEFT = "╭"
BOX_TOP_RIGHT = "╮"
BOX_BOTTOM_LEFT = "╰"
BOX_BOTTOM_RIGHT = "╯"
BOX_HORIZONTAL = "─"
BOX_VERTICAL = "│"
BOX_TEE_RIGHT = "├"
BOX_TEE_LEFT = "┤"

# Category header box drawing
HEADER_LEFT = "┌"
HEADER_RIGHT = "┐"
HEADER_HORIZONTAL = "─"
HEADER_VERTICAL = "│"
CONNECTOR_TEE = "├"
CONNECTOR_END = "└"

# Sparkline characters (#8: timing comparison sparklines)
SPARKLINE_CHARS = " ▁▂▃▄▅▆▇█"

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
