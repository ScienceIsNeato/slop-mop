"""Quality checks for code quality metrics.

Cross-cutting quality gates that apply to any project:
- BogusTestsCheck: Detect tests that don't actually test anything
- ComplexityCheck: Cyclomatic complexity analysis
- DeadCodeCheck: Unused code detection via vulture
- SourceDuplicationCheck: Copy-paste code detection (jscpd)
- StringDuplicationCheck: Duplicate string literal detection
- LocLockCheck: Lines of code enforcement
"""

from slopmop.checks.quality.bogus_tests import BogusTestsCheck
from slopmop.checks.quality.complexity import ComplexityCheck
from slopmop.checks.quality.dead_code import DeadCodeCheck
from slopmop.checks.quality.duplicate_strings import StringDuplicationCheck
from slopmop.checks.quality.duplication import SourceDuplicationCheck
from slopmop.checks.quality.gate_dodging import GateDodgingCheck
from slopmop.checks.quality.loc_lock import LocLockCheck

__all__ = [
    "BogusTestsCheck",
    "ComplexityCheck",
    "DeadCodeCheck",
    "GateDodgingCheck",
    "SourceDuplicationCheck",
    "StringDuplicationCheck",
    "LocLockCheck",
]
