"""Detect structured metadata that claims things the page never says.

Deceptiveness: an agent bolts rich structured data onto a page — "look, I
added FAQ schema!" — but the JSON-LD asserts questions and answers that
appear nowhere in the visible copy, or is malformed so the rich result
silently never renders. The metadata is theatre: it tells crawlers and
search engines a story the actual page does not back up. Google's own
structured-data policy requires the markup to match visible content;
markup that doesn't is a manual-action risk, not a feature.

What this gate catches (PURE, stdlib parsing — no network):

  malformed JSON-LD
      A ``<script type="application/ld+json">`` block that does not parse.
      The page advertises structured data; search engines drop it on the
      floor. The agent "added schema" that does nothing. Fix: make it valid
      JSON.

  FAQ answer/question not on the page
      A FAQPage entry whose question or answer text is absent from the
      visible page. The structured data promises a Q&A the reader can never
      see. Fix: make the JSON-LD mirror the on-page FAQ (or remove it).
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import ClassVar, List, Tuple

from slopmop.checks.base import (
    EXCLUDE_DIRS_DESCRIPTION,
    SCOPE_EXCLUDED_DIRS,
    BaseCheck,
    CheckRole,
    ConfigField,
    Flaw,
    GateCategory,
    GateLevel,
    RemediationChurn,
    ToolContext,
)
from slopmop.checks.general._web_meta import (
    HtmlMeta,
    extract_faq_pairs,
    flatten_text,
    iter_html_files,
    parse_html,
)
from slopmop.core.result import CheckResult, CheckStatus, Finding, FindingLevel

_EXCLUDED = SCOPE_EXCLUDED_DIRS | {"node_modules", "vendor", "dist", "build"}

# Answers can be long; compare a leading slice so trivial trailing-markup
# differences don't mask genuine "this text is nowhere on the page" drift.
_ANSWER_PREFIX = 80


class UnfoundedMetadataCheck(BaseCheck):
    """Flag structured data that asserts content the page does not show.

    A PURE scan of every page's JSON-LD: each block must parse, and any
    FAQPage question/answer text must actually appear in the visible page
    copy. Catches "I added FAQ schema" theatre where the markup promises a
    Q&A the reader never sees, plus malformed blocks that silently fail.

    PURE check — stdlib JSON/HTML parsing, no external tools or network.

    Level: swab (cheap, deterministic — safe on every commit).

    Configuration:
      exclude_dirs: [] — additional directories to skip.

    Re-check:
      sm swab -g deceptiveness:unfounded-metadata --verbose
    """

    tool_context: ClassVar[ToolContext] = ToolContext.PURE
    role = CheckRole.DIAGNOSTIC
    level = GateLevel.SWAB
    remediation_churn = RemediationChurn.DOWNSTREAM_CHANGES_VERY_UNLIKELY

    @property
    def name(self) -> str:
        return "unfounded-metadata"

    @property
    def display_name(self) -> str:
        return "🎭 Unfounded Metadata (structured-data parity)"

    @property
    def gate_description(self) -> str:
        return (
            "🎭 Catches structured data that claims things the page never says: "
            "malformed JSON-LD, FAQ schema whose Q&A isn't in the visible copy"
        )

    @property
    def category(self) -> GateCategory:
        return GateCategory.DECEPTIVENESS

    @property
    def flaw(self) -> Flaw:
        return Flaw.DECEPTIVENESS

    @property
    def config_schema(self) -> List[ConfigField]:
        return [
            ConfigField(
                name="exclude_dirs",
                field_type="string[]",
                default=[],
                description=EXCLUDE_DIRS_DESCRIPTION,
                permissiveness="more_is_stricter",
            ),
        ]

    def is_applicable(self, project_root: str) -> bool:
        return bool(iter_html_files(Path(project_root), self._excluded()))

    def skip_reason(self, project_root: str) -> str:
        return "No HTML pages found"

    def _excluded(self) -> set[str]:
        return _EXCLUDED | set(self.config.get("exclude_dirs") or [])

    def run(self, project_root: str) -> CheckResult:
        start = time.perf_counter()
        root = Path(project_root)
        pages = iter_html_files(root, self._excluded())

        findings: List[Finding] = []
        for page in pages:
            rel = page.relative_to(root).as_posix()
            findings += self._scan_page(rel, parse_html(page))

        return self._result(findings, len(pages), time.perf_counter() - start)

    @staticmethod
    def _scan_page(rel: str, meta: HtmlMeta) -> List[Finding]:
        findings: List[Finding] = []
        page_text = flatten_text(meta.visible_text)
        for raw in meta.jsonld_blocks:
            try:
                data = json.loads(raw)
            except (ValueError, TypeError):
                findings.append(
                    Finding(
                        message=(
                            "malformed JSON-LD block — search engines will drop "
                            "this structured data silently"
                        ),
                        level=FindingLevel.ERROR,
                        file=rel,
                        rule_id="malformed-jsonld",
                    )
                )
                continue
            findings += _faq_parity_findings(rel, data, page_text)
        return findings

    def _result(
        self, findings: List[Finding], page_count: int, elapsed: float
    ) -> CheckResult:
        if not findings:
            return self._create_result(
                status=CheckStatus.PASSED,
                duration=elapsed,
                output=(
                    f"Structured data matches the page ({page_count} page(s) checked)"
                ),
            )
        preview = "\n".join(f"  {f.file}: {f.message}" for f in findings[:20])
        more = f"\n  … and {len(findings) - 20} more" if len(findings) > 20 else ""
        return self._create_result(
            status=CheckStatus.FAILED,
            duration=elapsed,
            output=f"{preview}{more}",
            findings=findings,
            error=(
                f"Found {len(findings)} unfounded-metadata issue(s) across "
                f"{page_count} page(s)."
            ),
            fix_suggestion=(
                "Make structured data match what the page actually shows:\n"
                "  - every JSON-LD block must be valid JSON\n"
                "  - FAQ schema questions/answers must appear in the visible copy\n"
                "    (generate the JSON-LD FROM the page, don't hand-write it)\n"
                "To suppress a directory, add it to\n"
                "  deceptiveness.gates.unfounded-metadata.exclude_dirs in .sb_config.json"
            ),
        )


def _faq_parity_findings(rel: str, data: object, page_text: str) -> List[Finding]:
    """Flag FAQ questions/answers whose text is absent from the visible page."""
    findings: List[Finding] = []
    for question, answer in extract_faq_pairs(data):
        for label, text, rule in _faq_targets(question, answer):
            normalized = flatten_text(text)
            # Only answers get the length cap; questions are short and must
            # match in full so long questions aren't silently truncated.
            needle = (
                normalized[:_ANSWER_PREFIX]
                if rule == "faq-answer-not-on-page"
                else normalized
            ).strip()
            if needle and needle not in page_text:
                findings.append(
                    Finding(
                        message=(
                            f"FAQ {label} in structured data is not on the page: "
                            f"{text.strip()[:80]!r}"
                        ),
                        level=FindingLevel.ERROR,
                        file=rel,
                        rule_id=rule,
                    )
                )
    return findings


def _faq_targets(question: str, answer: str) -> List[Tuple[str, str, str]]:
    return [
        ("question", question, "faq-question-not-on-page"),
        ("answer", answer, "faq-answer-not-on-page"),
    ]
