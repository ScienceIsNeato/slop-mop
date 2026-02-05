"""Quality checks for code quality metrics.

Cross-cutting quality gates that apply to any project:
- ComplexityCheck: Cyclomatic complexity analysis
- DuplicationCheck: Copy-paste code detection
- LocLockCheck: Lines of code enforcement
"""

from slopmop.checks.quality.complexity import ComplexityCheck
from slopmop.checks.quality.duplication import DuplicationCheck
from slopmop.checks.quality.loc_lock import LocLockCheck

__all__ = ["ComplexityCheck", "DuplicationCheck", "LocLockCheck"]
