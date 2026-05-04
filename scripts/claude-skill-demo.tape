# vhs tape: record the live `sm scour` TUI for the README demo gif.
#
# The recording shows three distinct slop-mop findings firing on a single run:
#   1. deceptiveness:bogus-tests.py  — a test that just asserts True
#   2. overconfidence:coverage-gaps.py — two functions with no coverage
#   3. laziness:silenced-gates       — two gates parked in disabled_gates (warn)
#
# Usage:
#   brew install vhs
#   bash scripts/setup-demo-project.sh
#   vhs scripts/claude-skill-demo.tape
#   # output lands at assets/claude-skill-demo.gif
#
# vhs docs: https://github.com/charmbracelet/vhs

Output assets/claude-skill-demo.gif

Set Shell "bash"
Set FontSize 14
Set Width  1100
Set Height 760
Set Padding 24
Set Theme "Catppuccin Mocha"
Set TypingSpeed 60ms
Set PlaybackSpeed 1.0

# Move into the prepared demo project off-camera
Hide
Type "cd /tmp/slopdemo"
Enter
Type "clear"
Enter
Show

Sleep 600ms

# Type the command at human speed. --no-fail-fast so all four target gates
# get a chance to run even if bogus-tests fails early.
Type "sm scour --no-fail-fast"
Sleep 400ms
Enter

# Let the live TUI run to completion. scour with the four target gates +
# their formatter/test deps takes roughly 18-25s on a warm cache. Bump this
# if your machine is slower.
Sleep 28s

# Hold the final result for a beat so the loop has a clear resting frame.
Sleep 4s
