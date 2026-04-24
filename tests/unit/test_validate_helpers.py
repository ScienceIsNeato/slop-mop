"""Tests for helper functions in slopmop.cli.validate."""

from __future__ import annotations

import argparse
from pathlib import Path

from slopmop.cli.validate import (
    _parse_quality_gates,
    _print_header,
    _resolve_swabbing_timeout,
)


class TestResolveSwabbingTimeout:
    def _ns(self, **kwargs) -> argparse.Namespace:
        return argparse.Namespace(**kwargs)

    def test_returns_none_when_no_arg_and_no_config(self, tmp_path: Path):
        ns = self._ns(swabbing_timeout=None)
        assert _resolve_swabbing_timeout(ns, tmp_path) is None

    def test_cli_arg_takes_priority(self, tmp_path: Path):
        ns = self._ns(swabbing_timeout=45)
        result = _resolve_swabbing_timeout(ns, tmp_path)
        assert result == 45

    def test_reads_swabbing_timeout_from_config(self, tmp_path: Path):
        import json

        (tmp_path / ".sb_config.json").write_text(
            json.dumps({"swabbing_timeout": 60}), encoding="utf-8"
        )
        ns = self._ns(swabbing_timeout=None)
        result = _resolve_swabbing_timeout(ns, tmp_path)
        assert result == 60

    def test_backward_compat_swabbing_time_key(self, tmp_path: Path):
        """Deprecated swabbing_time key is read when swabbing_timeout absent."""
        import json

        (tmp_path / ".sb_config.json").write_text(
            json.dumps({"swabbing_time": 30}), encoding="utf-8"
        )
        ns = self._ns(swabbing_timeout=None)
        result = _resolve_swabbing_timeout(ns, tmp_path, preloaded_config=None)
        assert result == 30

    def test_preloaded_config_swabbing_time_compat(self, tmp_path: Path):
        """preloaded_config with old swabbing_time key is read correctly."""
        ns = self._ns(swabbing_timeout=None)
        result = _resolve_swabbing_timeout(
            ns, tmp_path, preloaded_config={"swabbing_time": 25}
        )
        assert result == 25


class TestParseQualityGates:
    def _ns(self, gates):
        return argparse.Namespace(quality_gates=gates)

    def test_returns_none_when_no_gates(self):
        assert _parse_quality_gates(self._ns(None)) is None

    def test_returns_none_when_empty(self):
        assert _parse_quality_gates(self._ns([])) is None

    def test_single_gate(self):
        result = _parse_quality_gates(self._ns(["myopia:code-sprawl"]))
        assert result == ["myopia:code-sprawl"]

    def test_comma_separated_gates_are_split(self):
        result = _parse_quality_gates(
            self._ns(["myopia:code-sprawl,laziness:dead-code.py"])
        )
        assert result == ["myopia:code-sprawl", "laziness:dead-code.py"]

    def test_multiple_args_are_merged(self):
        result = _parse_quality_gates(
            self._ns(["myopia:code-sprawl", "laziness:dead-code.py"])
        )
        assert result == ["myopia:code-sprawl", "laziness:dead-code.py"]


class TestPrintHeader:
    def test_no_timeout_prints_basic_banner(self, capsys):
        ns = argparse.Namespace()
        _print_header(Path("/tmp"), [], ns)
        captured = capsys.readouterr()
        assert "scanning the code" in captured.out

    def test_with_timeout_includes_budget(self, capsys):
        ns = argparse.Namespace()
        _print_header(Path("/tmp"), [], ns, swabbing_timeout=30)
        captured = capsys.readouterr()
        assert "30s" in captured.out
