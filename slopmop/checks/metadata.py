"""Built-in gate metadata shared across runtime and documentation."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from slopmop.checks.base import BaseCheck


@dataclass(frozen=True)
class Reasoning:
    """Structured rationale metadata for a gate.

    The intent is to state the default case clearly, admit the actual cost,
    and name the narrow situations where the default should bend.
    """

    rationale: str
    tradeoffs: str
    override_when: str

    def to_dict(self) -> dict[str, str]:
        return {
            "rationale": self.rationale,
            "tradeoffs": self.tradeoffs,
            "override_when": self.override_when,
        }


def _reasoning(rationale: str, tradeoffs: str, override_when: str) -> Reasoning:
    return Reasoning(
        rationale=rationale,
        tradeoffs=tradeoffs,
        override_when=override_when,
    )


def _coverage_reasoning(language: str) -> Reasoning:
    return _reasoning(
        rationale=(
            f"If changed {language} code can land without tests proving it, coverage "
            "turns decorative and the hole just moves around the repo."
        ),
        tradeoffs=(
            "Coverage work slows down spikes and sometimes forces harness cleanup "
            "before the feature feels done."
        ),
        override_when=(
            "Bend this for short-lived spikes, active incidents, or other explicitly "
            "time-critical work with agreement that the coverage debt gets paid back."
        ),
    )


def _untested_reasoning(language: str) -> Reasoning:
    return _reasoning(
        rationale=(
            f"Passing compilation is not proof; if {language} code never executes under "
            "test, you are still guessing."
        ),
        tradeoffs=(
            "Full test runs cost real time, especially in slower suites or flaky "
            "legacy harnesses."
        ),
        override_when=(
            "Use discretion during incident response or truly throwaway spikes where "
            "fast feedback matters more than full proof."
        ),
    )


def _formatting_reasoning() -> Reasoning:
    return _reasoning(
        rationale=(
            "Formatting noise hides the real change and makes review slower than it "
            "needs to be."
        ),
        tradeoffs=(
            "It can feel like busywork when you are in the middle of a real fix and "
            "the code already runs."
        ),
        override_when=(
            "Relax it briefly for throwaway spikes or incident patches, not for normal "
            "feature work headed to review."
        ),
    )


def _missing_annotations_reasoning(language: str) -> Reasoning:
    return _reasoning(
        rationale=(
            f"Missing {language} annotations turn interfaces into vibes and push type "
            "noise downstream for somebody else to untangle."
        ),
        tradeoffs=(
            "Adding annotations can expose a bigger cleanup than the line that first "
            "tripped the gate."
        ),
        override_when=(
            "Bend this for short spikes or throwaway glue code, not for stable surfaces "
            "other code is going to lean on."
        ),
    )


def _type_blindness_reasoning(language: str) -> Reasoning:
    return _reasoning(
        rationale=(
            f"If the type checker cannot tell what something is in {language}, humans "
            "and agents are left guessing too."
        ),
        tradeoffs=(
            "Strict typing often drags surrounding ambiguity into the light, so the "
            "fix can widen before it narrows."
        ),
        override_when=(
            "Bend this for spikes or incident work where you are explicitly buying "
            "short-term ambiguity to move faster."
        ),
    )


def _bogus_tests_reasoning(language: str) -> Reasoning:
    return _reasoning(
        rationale=(
            f"A fake {language} test suite is worse than no test suite because it "
            "teaches people to trust green lies."
        ),
        tradeoffs=(
            "The strict version can be annoying when you sketch a test first and plan "
            "to fill the assertions in a minute later."
        ),
        override_when=(
            "Fine to relax briefly in draft-only local work, not in committed code that "
            "is pretending to be review-ready."
        ),
    )


@lru_cache(maxsize=1)
def _deceptiveness_reasoning_entries() -> tuple[tuple[type[BaseCheck], Reasoning], ...]:
    from slopmop.checks.dart import (
        DartBogusTestsCheck,
    )
    from slopmop.checks.javascript.bogus_tests import JavaScriptBogusTestsCheck
    from slopmop.checks.javascript.eslint_expect import JavaScriptExpectCheck
    from slopmop.checks.quality import (
        BogusTestsCheck,
        DebuggerArtifactsCheck,
        GateDodgingCheck,
    )

    return (
        (DartBogusTestsCheck, _bogus_tests_reasoning("Dart")),
        (JavaScriptBogusTestsCheck, _bogus_tests_reasoning("JavaScript")),
        (BogusTestsCheck, _bogus_tests_reasoning("Python")),
        (
            DebuggerArtifactsCheck,
            _reasoning(
                rationale=(
                    "Leftover breakpoints are the kind of tiny accident that can wreck a real "
                    "run in embarrassingly expensive ways."
                ),
                tradeoffs=(
                    "The only real cost is a little friction when you are actively debugging "
                    "and want quick iteration."
                ),
                override_when=(
                    "Fine in local scratch work; not fine once the change is headed toward a "
                    "commit or a PR."
                ),
            ),
        ),
        (
            GateDodgingCheck,
            _reasoning(
                rationale=(
                    "If the fix is 'turn the smoke alarm down,' the repo learns the wrong "
                    "lesson and the next regression walks right in."
                ),
                tradeoffs=(
                    "Sometimes legit threshold tuning is necessary, and this gate makes you "
                    "prove the difference instead of waving at it."
                ),
                override_when=(
                    "Override only when the threshold itself is wrong and you are intentionally "
                    "recalibrating policy, not when the current diff is just inconvenient."
                ),
            ),
        ),
        (
            JavaScriptExpectCheck,
            _reasoning(
                rationale=(
                    "If JavaScript tests never assert, the suite is just theater with npm "
                    "around it."
                ),
                tradeoffs=(
                    "Assertion-enforcement can be noisy while a test is half-written or when a "
                    "framework hides assertions behind helpers."
                ),
                override_when=(
                    "Bend this only for draft local work or framework edge cases you have "
                    "explicitly accounted for."
                ),
            ),
        ),
    )


@lru_cache(maxsize=1)
def _laziness_structural_reasoning_entries() -> (
    tuple[tuple[type[BaseCheck], Reasoning], ...]
):
    from slopmop.checks.dart import DartGeneratedArtifactsCheck
    from slopmop.checks.general.jinja2_templates import TemplateValidationCheck
    from slopmop.checks.quality import (
        ComplexityCheck,
        ConfigDebtCheck,
        DeadCodeCheck,
        RepeatedCodeCheck,
    )

    return (
        (
            RepeatedCodeCheck,
            _reasoning(
                rationale=(
                    "Copy-pasted blocks diverge in slow motion until every bug fix becomes a "
                    "scavenger hunt across near-identical code."
                ),
                tradeoffs=(
                    "Deduping too early can create the wrong abstraction and make simple code "
                    "feel clever for no reason."
                ),
                override_when=(
                    "Hold off when the repeated code is still genuinely in discovery mode and the "
                    "shared shape is not stable yet."
                ),
            ),
        ),
        (
            TemplateValidationCheck,
            _reasoning(
                rationale=(
                    "Template bugs like to wait until a user path hits them, which is a lousy "
                    "time to discover syntax errors."
                ),
                tradeoffs=(
                    "Template validation can be noisy in repos with partials or unconventional "
                    "render-context setup."
                ),
                override_when=(
                    "Relax it only for prototypes or repos where the template is not actually "
                    "part of the shipped path yet."
                ),
            ),
        ),
        (
            ComplexityCheck,
            _reasoning(
                rationale=(
                    "Big branching functions are where edge cases go to hide and future fixes "
                    "go to die."
                ),
                tradeoffs=(
                    "Refactors to reduce complexity can be broader and riskier than the "
                    "immediate bug fix that triggered the work."
                ),
                override_when=(
                    "Bend this during incident stabilization, then come back and split the "
                    "function once the fire is out."
                ),
            ),
        ),
        (
            DeadCodeCheck,
            _reasoning(
                rationale=(
                    "Dead code makes the map lie. People read paths that do not matter and miss "
                    "the ones that do."
                ),
                tradeoffs=(
                    "Static dead-code tools can false-positive on dynamic hooks, plugins, and "
                    "intentionally indirect entrypoints."
                ),
                override_when=(
                    "Override for known dynamic entrypoints with a concrete explanation, not "
                    "because the deletion is inconvenient right now."
                ),
            ),
        ),
        (
            DartGeneratedArtifactsCheck,
            _reasoning(
                rationale=(
                    "Checking in generated junk is how you turn diffs into static and invite "
                    "edits that get wiped later."
                ),
                tradeoffs=(
                    "Sometimes the generated output is the artifact you actually need to ship "
                    "or preserve as a fixture."
                ),
                override_when=(
                    "Allow it when the generated file is intentionally versioned, not when it is "
                    "just local build fallout hitching a ride."
                ),
            ),
        ),
        (
            ConfigDebtCheck,
            _reasoning(
                rationale=("A disabled gate is usually debt with a welcome mat on it."),
                tradeoffs=(
                    "Sometimes a gate really is wrong for the repo or temporarily broken by "
                    "external churn."
                ),
                override_when=(
                    "Override only when disabling is an explicit policy choice with a tracked "
                    "reason, not as a drive-by escape hatch."
                ),
            ),
        ),
    )


@lru_cache(maxsize=1)
def _laziness_polish_reasoning_entries() -> (
    tuple[tuple[type[BaseCheck], Reasoning], ...]
):
    from slopmop.checks.dart import DartFormatCheck
    from slopmop.checks.javascript.eslint_quick import FrontendCheck
    from slopmop.checks.javascript.lint_format import JavaScriptLintFormatCheck
    from slopmop.checks.python.lint_format import PythonLintFormatCheck

    return (
        (DartFormatCheck, _formatting_reasoning()),
        (JavaScriptLintFormatCheck, _formatting_reasoning()),
        (PythonLintFormatCheck, _formatting_reasoning()),
        (
            FrontendCheck,
            _reasoning(
                rationale=(
                    "Frontend lint issues have a habit of turning into visible bugs, state "
                    "leaks, or accessibility damage."
                ),
                tradeoffs=(
                    "Quick lint passes can bark at work-in-progress code while a larger "
                    "refactor is still mid-flight."
                ),
                override_when=(
                    "Relax it briefly during spikes or refactors in motion, not for settled code "
                    "headed to review."
                ),
            ),
        ),
    )


@lru_cache(maxsize=1)
def _myopia_scope_reasoning_entries() -> tuple[tuple[type[BaseCheck], Reasoning], ...]:
    from slopmop.checks.pr.comments import PRCommentsCheck
    from slopmop.checks.python.coverage import PythonDiffCoverageCheck
    from slopmop.checks.quality import LocLockCheck
    from slopmop.checks.security import SecurityLocalCheck

    return (
        (
            LocLockCheck,
            _reasoning(
                rationale=(
                    "Once files and functions get too big, nobody can safely reason about them "
                    "in one pass, including the model."
                ),
                tradeoffs=(
                    "Splitting code takes time and can feel like ceremony while you are still "
                    "exploring the shape of the solution."
                ),
                override_when=(
                    "Bend this for short spikes while the design is still liquid, then pay the "
                    "split tax before the code hardens."
                ),
            ),
        ),
        (
            SecurityLocalCheck,
            _reasoning(
                rationale=(
                    "Your code can be clean and still ship someone else's CVE to production."
                ),
                tradeoffs=(
                    "Dependency audits can produce noisy or low-signal findings, especially "
                    "when advisories lag behind reality."
                ),
                override_when=(
                    "Temporarily waive only with a conscious risk call, usually during incident "
                    "work or when the upstream fix path is outside your control."
                ),
            ),
        ),
        (
            PRCommentsCheck,
            _reasoning(
                rationale=(
                    "Unresolved review threads turn the PR loop into Groundhog Day and hide "
                    "known concerns in plain sight."
                ),
                tradeoffs=(
                    "Sometimes a thread is stale, blocked on reviewer input, or attached to code "
                    "that has changed shape since the comment landed."
                ),
                override_when=(
                    "Override only when you have explicitly resolved the thread state with "
                    "evidence or you are waiting on human clarification."
                ),
            ),
        ),
        (
            PythonDiffCoverageCheck,
            _reasoning(
                rationale=(
                    "If changed lines can land untested, overall coverage becomes a nice story "
                    "the PR does not actually obey."
                ),
                tradeoffs=(
                    "Diff coverage can be painful on legacy code where touching one line exposes "
                    "a whole untested neighborhood."
                ),
                override_when=(
                    "Bend this for spikes, emergency patches, or intentionally exploratory diffs "
                    "with an agreed follow-up to close the gap."
                ),
            ),
        ),
    )


@lru_cache(maxsize=1)
def _myopia_risk_reasoning_entries() -> tuple[tuple[type[BaseCheck], Reasoning], ...]:
    from slopmop.checks.quality import AmbiguityMinesCheck, StringDuplicationCheck
    from slopmop.checks.security import SecurityCheck

    return (
        (
            AmbiguityMinesCheck,
            _reasoning(
                rationale=(
                    "Duplicate function names across files create ambiguity mines — copy-paste "
                    "artifacts that diverge silently until every bug fix is a scavenger hunt."
                ),
                tradeoffs=(
                    "False positives on lifecycle names and protocol implementations can be "
                    "noisy; the noqa suppression keeps intentional cases clean."
                ),
                override_when=(
                    "Suppress when the duplication is structural (strategy pattern, test doubles) "
                    "and add `# noqa: ambiguity-mine` with an explanation."
                ),
            ),
        ),
        (
            StringDuplicationCheck,
            _reasoning(
                rationale=(
                    "Repeated literals hide shared rules and make the repo drift by typo instead "
                    "of design."
                ),
                tradeoffs=(
                    "Not every repeated string deserves an abstraction, and the gate can tempt "
                    "people into inventing constants nobody needed."
                ),
                override_when=(
                    "Override for truly incidental repeats like local test data or tiny messages "
                    "that are not carrying shared business meaning."
                ),
            ),
        ),
        (
            SecurityCheck,
            _reasoning(
                rationale=(
                    "Code can pass tests and types and still be an own-goal from a security "
                    "perspective."
                ),
                tradeoffs=(
                    "Security scanners throw false positives and sometimes demand context they "
                    "cannot infer from static analysis."
                ),
                override_when=(
                    "Waive only with a specific risk decision and rationale, not because the "
                    "scanner is inconvenient."
                ),
            ),
        ),
    )


@lru_cache(maxsize=1)
def _overconfidence_reasoning_entries() -> (
    tuple[tuple[type[BaseCheck], Reasoning], ...]
):
    from slopmop.checks.dart import (
        DartCoverageCheck,
        FlutterAnalyzeCheck,
        FlutterTestsCheck,
    )
    from slopmop.checks.javascript.coverage import JavaScriptCoverageCheck
    from slopmop.checks.javascript.tests import JavaScriptTestsCheck
    from slopmop.checks.javascript.types import JavaScriptTypesCheck
    from slopmop.checks.python.coverage import PythonCoverageCheck
    from slopmop.checks.python.static_analysis import PythonStaticAnalysisCheck
    from slopmop.checks.python.tests import PythonTestsCheck
    from slopmop.checks.python.type_checking import PythonTypeCheckingCheck

    return (
        (DartCoverageCheck, _coverage_reasoning("Dart")),
        (JavaScriptCoverageCheck, _coverage_reasoning("JavaScript")),
        (PythonCoverageCheck, _coverage_reasoning("Python")),
        (FlutterAnalyzeCheck, _missing_annotations_reasoning("Dart")),
        (PythonStaticAnalysisCheck, _missing_annotations_reasoning("Python")),
        (JavaScriptTypesCheck, _type_blindness_reasoning("TypeScript")),
        (PythonTypeCheckingCheck, _type_blindness_reasoning("Python")),
        (FlutterTestsCheck, _untested_reasoning("Dart")),
        (JavaScriptTestsCheck, _untested_reasoning("JavaScript")),
        (PythonTestsCheck, _untested_reasoning("Python")),
    )


@lru_cache(maxsize=1)
def _builtin_reasoning_entries() -> tuple[tuple[type[BaseCheck], Reasoning], ...]:
    return (
        *_deceptiveness_reasoning_entries(),
        *_laziness_structural_reasoning_entries(),
        *_laziness_polish_reasoning_entries(),
        *_myopia_scope_reasoning_entries(),
        *_myopia_risk_reasoning_entries(),
        *_overconfidence_reasoning_entries(),
    )


@lru_cache(maxsize=1)
def _builtin_reasoning_by_check_class() -> dict[type[BaseCheck], Reasoning]:
    return dict(_builtin_reasoning_entries())


@lru_cache(maxsize=1)
def _builtin_reasoning_by_full_name() -> dict[str, Reasoning]:
    return {
        check_class({}).full_name: reasoning
        for check_class, reasoning in _builtin_reasoning_entries()
    }


def builtin_reasoning_for_check_class(
    check_class: type[BaseCheck],
) -> Reasoning | None:
    """Return built-in reasoning metadata keyed by the check class itself."""
    return _builtin_reasoning_by_check_class().get(check_class)


def builtin_gate_reasoning(full_name: str) -> Reasoning | None:
    """Return built-in reasoning metadata for a gate name.

    This derived lookup exists for compatibility with name-based callers.
    """
    return _builtin_reasoning_by_full_name().get(full_name)


def builtin_gate_rationale(full_name: str) -> str | None:
    """Return the built-in rationale text for a gate, if one exists."""
    reasoning = builtin_gate_reasoning(full_name)
    if reasoning is None:
        return None
    return reasoning.rationale
