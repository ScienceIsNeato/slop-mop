"""Tests for structured gate reasoning metadata and generated docs."""

from __future__ import annotations

import json
from pathlib import Path

from slopmop.checks.metadata import Reasoning


def _reasoning_doc_body(content: str = "") -> str:
    return "# Gate Reasoning\n\n" + content


class TestGateReasoningMetadata:
    def _ensure_fresh_registry(self) -> None:
        import slopmop.checks as checks_mod

        checks_mod._checks_registered = False
        checks_mod.ensure_checks_registered()

    def test_all_builtin_gates_have_reasoning_struct(self) -> None:
        from slopmop.core.registry import get_registry

        self._ensure_fresh_registry()
        registry = get_registry()
        missing: list[str] = []
        for name in registry.list_checks():
            check = registry.get_check(name, {})
            if check is None:
                missing.append(name)
                continue

            reasoning = getattr(check, "reasoning", None)
            if not isinstance(reasoning, Reasoning):
                missing.append(name)
                continue

            if not reasoning.rationale.strip():
                missing.append(name)
                continue

            if not reasoning.tradeoffs.strip():
                missing.append(name)
                continue

            if not reasoning.override_when.strip():
                missing.append(name)

        assert missing == []


class TestGateReasoningDocs:
    def _ensure_fresh_registry(self) -> None:
        import slopmop.checks as checks_mod

        checks_mod._checks_registered = False
        checks_mod.ensure_checks_registered()

    def test_generate_reasoning_doc_contains_structured_sections(self) -> None:
        from slopmop.core.registry import get_registry
        from slopmop.utils.gate_reasoning_docs import generate_reasoning_doc

        self._ensure_fresh_registry()
        registry = get_registry()

        doc = generate_reasoning_doc(registry)
        assert "# Gate Reasoning" in doc
        assert "`overconfidence:coverage-gaps.py`" in doc
        assert "Rationale" in doc
        assert "Tradeoffs" in doc
        assert "Override When" in doc

    def test_check_reasoning_doc_detects_stale_content(self, tmp_path: Path) -> None:
        from slopmop.core.registry import get_registry
        from slopmop.utils.gate_reasoning_docs import check_reasoning_doc

        self._ensure_fresh_registry()
        registry = get_registry()

        path = tmp_path / "GATE_REASONING.md"
        path.write_text(_reasoning_doc_body("stale\n"))

        is_ok, message = check_reasoning_doc(path, registry)
        assert is_ok is False
        assert "stale" in message.lower()

    def test_matching_reasoning_doc_passes(self, tmp_path: Path) -> None:
        from slopmop.core.registry import get_registry
        from slopmop.utils.gate_reasoning_docs import (
            check_reasoning_doc,
            generate_reasoning_doc,
        )

        self._ensure_fresh_registry()
        registry = get_registry()

        path = tmp_path / "GATE_REASONING.md"
        path.write_text(generate_reasoning_doc(registry))

        is_ok, message = check_reasoning_doc(path, registry)
        assert is_ok is True


class TestStaleDocsWiring:
    def test_stale_docs_custom_gate_checks_reasoning_doc(self) -> None:
        config = json.loads(
            Path(
                "/Users/pacey/Documents/SourceCode/slop-mop/.sb_config.json"
            ).read_text()
        )
        stale_docs_gate = next(
            gate for gate in config["custom_gates"] if gate["name"] == "stale-docs"
        )

        assert "generate_gate_reasoning.py --check" in stale_docs_gate["command"]
        assert "generate_gate_reasoning.py --update" in stale_docs_gate["fix_command"]
