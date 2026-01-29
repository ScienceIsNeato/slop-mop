"""Quality checks for code quality metrics.

Cross-cutting quality gates that apply to any project:
- ComplexityCheck: Cyclomatic complexity analysis
- DuplicationCheck: Copy-paste code detection
"""

from slopmop.checks.quality.complexity import ComplexityCheck
from slopmop.checks.quality.duplication import DuplicationCheck

__all__ = ["ComplexityCheck", "DuplicationCheck"]
