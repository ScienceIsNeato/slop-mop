"""Quality checks for code quality metrics.

Cross-cutting quality gates that apply to any project:
- ComplexityCheck: Cyclomatic complexity analysis
- DuplicationCheck: Copy-paste code detection
"""

from slopbucket.checks.quality.complexity import ComplexityCheck
from slopbucket.checks.quality.duplication import DuplicationCheck

__all__ = ["ComplexityCheck", "DuplicationCheck"]
