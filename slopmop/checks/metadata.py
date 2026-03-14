"""Built-in gate metadata shared across runtime and documentation."""

from __future__ import annotations

_FORMATTING_WHY = (
    "Inconsistent formatting hides semantic changes inside noisy diffs and slows "
    "review."
)
_COVERAGE_WHY = (
    "Uncovered {language} paths can regress silently because no test proves the "
    "behavior."
)
_UNTESTED_WHY = (
    "Passing compilation is not proof; {language} behavior is only credible when "
    "tests execute it."
)

BUILTIN_GATE_WHY: dict[str, str] = {
    "deceptiveness:bogus-tests.dart": "Fake or empty tests manufacture confidence without proving Dart behavior.",
    "deceptiveness:bogus-tests.js": "Fake or empty tests manufacture confidence without proving JavaScript behavior.",
    "deceptiveness:bogus-tests.py": "Fake or empty tests manufacture confidence without proving Python behavior.",
    "deceptiveness:debugger-artifacts": "Leftover debug code changes runtime behavior, leaks internals, and pollutes diffs.",
    "deceptiveness:gate-dodging": "Weakened gates silently erase protection and teach agents to optimize around the rules.",
    "deceptiveness:hand-wavy-tests.js": "Assertion-free tests let JavaScript code look verified while real behavior stays unchecked.",
    "laziness:broken-templates.py": "Template syntax failures usually surface late, on user paths, instead of during development.",
    "laziness:complexity-creep.py": "High complexity hides edge cases and makes every later change riskier to reason about.",
    "laziness:dead-code.py": "Dead code creates false paths, confuses readers, and keeps obsolete behavior alive in the tree.",
    "laziness:generated-artifacts.dart": "Generated-file drift creates noisy churn and invites edits that will be overwritten later.",
    "laziness:silenced-gates": "Disabled gates normalize lower standards and let regressions slip through quietly.",
    "laziness:sloppy-formatting.dart": _FORMATTING_WHY,
    "laziness:sloppy-formatting.js": _FORMATTING_WHY,
    "laziness:sloppy-formatting.py": _FORMATTING_WHY,
    "laziness:sloppy-frontend.js": "Frontend lint violations often become user-visible state, accessibility, or rendering defects.",
    "myopia:code-sprawl": "Oversized code units exceed local reasoning limits and make safe edits much harder.",
    "myopia:dependency-risk.py": "A clean codebase can still ship exploitable risk through vulnerable dependencies.",
    "myopia:ignored-feedback": "Unresolved review feedback creates looped CI churn and leaves known concerns unclosed.",
    "myopia:just-this-once.py": "Temporary shortcuts calcify into permanent debt when TODOs, hacks, and exemptions go stale.",
    "myopia:source-duplication": "Duplicated logic diverges over time, so each bug fix has to be rediscovered in multiple places.",
    "myopia:string-duplication.py": "Repeated literals hide shared rules and drift into inconsistent behavior across files.",
    "myopia:vulnerability-blindness.py": "Insecure code patterns can be exploitable even when tests and types are green.",
    "overconfidence:coverage-gaps.dart": _COVERAGE_WHY.format(language="Dart"),
    "overconfidence:coverage-gaps.js": _COVERAGE_WHY.format(language="JavaScript"),
    "overconfidence:coverage-gaps.py": _COVERAGE_WHY.format(language="Python"),
    "overconfidence:missing-annotations.dart": "Missing Dart type information weakens static guarantees and hides interface mistakes.",
    "overconfidence:missing-annotations.py": "Missing Python annotations weaken static guarantees and hide interface mistakes.",
    "overconfidence:type-blindness.js": "Unresolved TypeScript types force callers to guess instead of relying on checked contracts.",
    "overconfidence:type-blindness.py": "Unknown Python types force humans and agents to guess about data shape and contracts.",
    "overconfidence:untested-code.dart": _UNTESTED_WHY.format(language="Dart"),
    "overconfidence:untested-code.js": _UNTESTED_WHY.format(language="JavaScript"),
    "overconfidence:untested-code.py": _UNTESTED_WHY.format(language="Python"),
}


def builtin_gate_why(full_name: str) -> str | None:
    """Return the built-in why text for a gate, if one exists."""
    return BUILTIN_GATE_WHY.get(full_name)
