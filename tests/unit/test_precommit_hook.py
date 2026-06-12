"""Tests for the pre-commit framework hook entry point (sm hook).

Covers:
  - onboard-status gating: fresh / init_done repos warn and exit 0
  - onboarded repos delegate to the real validation verb
  - exit code propagation from the delegated run
  - .pre-commit-hooks.yaml manifest shape
"""

import argparse
from pathlib import Path
from unittest.mock import patch

import yaml

from slopmop.cli.precommit_hook import cmd_hook

REPO_ROOT = Path(__file__).resolve().parents[2]


def _hook_args(verb: str, project_root: Path) -> argparse.Namespace:
    return argparse.Namespace(hook_verb=verb, project_root=str(project_root))


class TestOnboardGating:
    def test_fresh_repo_warns_and_passes(self, tmp_path, capsys):
        exit_code = cmd_hook(_hook_args("swab", tmp_path))

        assert exit_code == 0
        out = capsys.readouterr().out
        assert "not onboarded" in out
        assert "sm init" in out

    def test_init_done_repo_warns_and_passes(self, tmp_path, capsys):
        (tmp_path / ".sb_config.json").write_text("{}")

        exit_code = cmd_hook(_hook_args("swab", tmp_path))

        assert exit_code == 0
        out = capsys.readouterr().out
        assert "not onboarded" in out
        # init already ran — remedy should not tell them to re-run it
        assert "sm refit --start" in out

    def test_scour_verb_also_gated(self, tmp_path, capsys):
        exit_code = cmd_hook(_hook_args("scour", tmp_path))

        assert exit_code == 0
        assert "not onboarded" in capsys.readouterr().out

    def test_unknown_verb_rejected(self, tmp_path):
        exit_code = cmd_hook(_hook_args("buff", tmp_path))

        assert exit_code == 2


class TestOnboardedDelegation:
    def _onboard(self, tmp_path: Path) -> None:
        (tmp_path / ".sb_config.json").write_text("{}")
        (tmp_path / ".slopmop").mkdir()

    def test_swab_delegates_with_porcelain_and_no_timeout(self, tmp_path):
        self._onboard(tmp_path)

        with patch("slopmop.sm.main", return_value=0) as sm_main:
            exit_code = cmd_hook(_hook_args("swab", tmp_path))

        assert exit_code == 0
        argv = sm_main.call_args.args[0]
        assert argv[0] == "swab"
        assert "--porcelain" in argv
        assert "--swabbing-timeout" in argv
        assert argv[argv.index("--swabbing-timeout") + 1] == "0"
        assert str(tmp_path) in argv

    def test_scour_delegates_without_swab_timeout(self, tmp_path):
        self._onboard(tmp_path)

        with patch("slopmop.sm.main", return_value=0) as sm_main:
            exit_code = cmd_hook(_hook_args("scour", tmp_path))

        assert exit_code == 0
        argv = sm_main.call_args.args[0]
        assert argv[0] == "scour"
        assert "--porcelain" in argv
        assert "--swabbing-timeout" not in argv

    def test_failure_exit_code_propagates(self, tmp_path):
        self._onboard(tmp_path)

        with patch("slopmop.sm.main", return_value=1):
            exit_code = cmd_hook(_hook_args("swab", tmp_path))

        assert exit_code == 1


class TestManifest:
    """The .pre-commit-hooks.yaml manifest this repo exports."""

    def _manifest(self):
        manifest_path = REPO_ROOT / ".pre-commit-hooks.yaml"
        assert manifest_path.exists(), ".pre-commit-hooks.yaml missing from repo root"
        return yaml.safe_load(manifest_path.read_text())

    def test_exports_swab_and_scour_hooks(self):
        hooks = {h["id"]: h for h in self._manifest()}
        assert "slopmop-swab" in hooks
        assert "slopmop-scour" in hooks

    def test_swab_runs_at_commit_scour_at_push(self):
        hooks = {h["id"]: h for h in self._manifest()}
        assert hooks["slopmop-swab"]["stages"] == ["pre-commit"]
        assert hooks["slopmop-scour"]["stages"] == ["pre-push"]

    def test_entries_use_gated_hook_verb(self):
        # Hooks must go through `sm hook` (onboard-gated), never bare verbs.
        for hook in self._manifest():
            assert hook["entry"].startswith("sm hook "), hook["id"]

    def test_hooks_run_whole_repo_not_filenames(self):
        for hook in self._manifest():
            assert hook["pass_filenames"] is False, hook["id"]
            assert hook["always_run"] is True, hook["id"]


class TestCliWiring:
    """sm hook is reachable through the real parser."""

    def test_parser_accepts_hook_verb(self):
        from slopmop.sm import create_parser

        parser = create_parser()
        parsed = parser.parse_args(["hook", "swab"])
        assert parsed.verb == "hook"
        assert parsed.hook_verb == "swab"

    def test_parser_rejects_invalid_hook_verb(self):
        import pytest

        from slopmop.sm import create_parser

        parser = create_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["hook", "buff"])

    def test_main_dispatches_hook_to_cmd_hook(self, tmp_path):
        from slopmop.sm import main

        # Fresh tmp repo → onboard gate trips → exit 0 without running gates
        exit_code = main(["hook", "swab", "--project-root", str(tmp_path)])
        assert exit_code == 0
