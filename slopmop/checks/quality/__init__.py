"""Quality checks for code quality metrics.

Cross-cutting quality gates that apply to any project:
- AmbiguityMinesCheck: Duplicate function-name detection (AST)
- BogusTestsCheck: Detect tests that don't actually test anything
- ComplexityCheck: Cyclomatic complexity analysis
- ConfigDebtCheck: Stale, disabled, or scoped-out config detection
- DeadCodeCheck: Unused code detection via vulture
- RepeatedCodeCheck: Copy-paste code detection (jscpd)
- StringDuplicationCheck: Duplicate string literal detection
- LocLockCheck: Lines of code enforcement
- DebuggerArtifactsCheck: Cross-language debugger artifact detection
"""

from slopmop.checks.quality.ambiguity_mines import AmbiguityMinesCheck
from slopmop.checks.quality.bogus_tests import BogusTestsCheck
from slopmop.checks.quality.complexity import ComplexityCheck
from slopmop.checks.quality.config_debt import ConfigDebtCheck
from slopmop.checks.quality.dead_code import DeadCodeCheck
from slopmop.checks.quality.debugger_artifacts import DebuggerArtifactsCheck
from slopmop.checks.quality.duplicate_strings import StringDuplicationCheck
from slopmop.checks.quality.duplication import RepeatedCodeCheck
from slopmop.checks.quality.gate_dodging import GateDodgingCheck
from slopmop.checks.quality.loc_lock import LocLockCheck

__all__ = [
    "AmbiguityMinesCheck",
    "BogusTestsCheck",
    "ComplexityCheck",
    "ConfigDebtCheck",
    "DeadCodeCheck",
    "DebuggerArtifactsCheck",
    "GateDodgingCheck",
    "RepeatedCodeCheck",
    "StringDuplicationCheck",
    "LocLockCheck",
]
