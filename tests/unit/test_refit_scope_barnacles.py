"""Scope must survive the path from config file to the tool that rewrites files.

Onboarding a repo that had scoped every category to one package reformatted
and committed 46 files, 38 of them outside that scope, unprompted (#357). The
scope was declared in three different ways and honoured in none, because the
formatting pass never loaded the config at all.

These pin each link in that chain separately, so a future break names itself.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any, Dict

import pytest

from slopmop.checks.base import resolve_tool_paths
from slopmop.checks.python.lint_format import PythonLintFormatCheck
from slopmop.core.registry import get_registry


def _loaded_config(root: Path) -> Dict[str, Any]:
    """Config as the CLI resolves it, not the raw file.

    The raw dict skips the merge that injects repo-wide filters, so a test
    reading the file directly would not exercise the path a real run takes.
    """
    from slopmop.sm import load_config

    return load_config(root)


def _commit_initial_repo(root: Path) -> None:
    """Make *root* a git repo with one commit.

    Named for what it does rather than the tool it uses: a second bare
    ``_git`` helper alongside the one in test_refit_drain_functional.py — same
    name, different signature, different ``check`` behaviour — is the exact
    ambiguity the myopia gate exists to catch.
    """
    for args in (
        ("init",),
        ("config", "user.email", "t@t.t"),
        ("config", "user.name", "t"),
        ("add", "-A"),
        ("commit", "-m", "init"),
    ):
        subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


@pytest.fixture
def scoped_repo(tmp_path: Path) -> Path:
    """A repo scoped to one package, with code outside it — the reported shape."""
    (tmp_path / "paperbot").mkdir()
    (tmp_path / "crypto15m").mkdir()
    (tmp_path / "paperbot" / "bot.py").write_text("x=1\n")
    (tmp_path / "crypto15m" / "trader.py").write_text("y=2\n")
    (tmp_path / "backtest_grid.py").write_text("z=3\n")
    (tmp_path / "demo.py").write_text("w=4\n")

    config: Dict[str, Any] = {
        "exclude_paths": ["crypto15m"],
        "laziness": {
            "enabled": True,
            "include_dirs": ["paperbot"],
            "gates": {"sloppy-formatting.py": {"enabled": True}},
        },
    }
    (tmp_path / ".sb_config.json").write_text(json.dumps(config))

    _commit_initial_repo(tmp_path)
    return tmp_path


class TestResolverHonoursIncludeDirs:
    """The resolver is the single place that decides what any tool sees."""

    def test_include_dirs_narrows_to_the_named_directory(
        self, scoped_repo: Path
    ) -> None:
        paths = resolve_tool_paths(
            str(scoped_repo), extensions={".py"}, include_dirs=["paperbot"]
        )
        assert paths == ["paperbot/bot.py"]

    def test_loose_root_files_are_excluded(self, scoped_repo: Path) -> None:
        """The 13 loose scripts in the report were root files, not a package."""
        paths = resolve_tool_paths(
            str(scoped_repo), extensions={".py"}, include_dirs=["paperbot"]
        )
        assert not any(p in ("backtest_grid.py", "demo.py") for p in paths)

    def test_absent_include_dirs_still_means_whole_project(
        self, scoped_repo: Path
    ) -> None:
        """The default must not change — this gate rewrites what it is given."""
        paths = resolve_tool_paths(str(scoped_repo), extensions={".py"})
        assert "backtest_grid.py" in paths
        assert "paperbot/bot.py" in paths

    def test_dot_is_treated_as_unscoped(self, scoped_repo: Path) -> None:
        explicit = resolve_tool_paths(
            str(scoped_repo), extensions={".py"}, include_dirs=["."]
        )
        implicit = resolve_tool_paths(str(scoped_repo), extensions={".py"})
        assert explicit == implicit

    def test_nested_include_keeps_its_ancestors(self, tmp_path: Path) -> None:
        """include_dirs=['a/b'] must still descend through 'a' in the walk."""
        (tmp_path / "a" / "b").mkdir(parents=True)
        (tmp_path / "a" / "b" / "keep.py").write_text("k=1\n")
        (tmp_path / "a" / "skip.py").write_text("s=1\n")
        # No git init: exercise the walk fallback, not git's listing.
        paths = resolve_tool_paths(
            str(tmp_path), extensions={".py"}, include_dirs=["a/b"]
        )
        joined = " ".join(paths)
        assert "keep.py" in joined or "a/b" in joined
        assert "skip.py" not in joined


class TestFormattingGateIsScoped:
    def test_gate_reads_category_level_include_dirs(self, scoped_repo: Path) -> None:
        """Set beside `gates`, not inside it — the form the report used."""
        config = _loaded_config(scoped_repo)
        check = get_registry().get_check("laziness:sloppy-formatting.py", config)
        assert check is not None
        assert check.config.get("include_dirs") == ["paperbot"]

    def test_targets_stay_inside_the_configured_scope(self, scoped_repo: Path) -> None:
        config = _loaded_config(scoped_repo)
        check = get_registry().get_check("laziness:sloppy-formatting.py", config)
        assert check is not None
        targets = check._get_python_targets(str(scoped_repo))
        assert targets == ["paperbot/bot.py"], targets

    def test_include_dirs_is_declared_so_it_is_discoverable(self) -> None:
        """An undeclared key is one nobody can find and nothing validates."""
        fields = {f.name for f in PythonLintFormatCheck({}).config_schema}
        assert "include_dirs" in fields

    def test_unscoped_gate_is_unchanged(self, scoped_repo: Path) -> None:
        check = PythonLintFormatCheck({})
        targets = check._get_python_targets(str(scoped_repo))
        assert "backtest_grid.py" in targets


class TestCategoryConfigInheritance:
    """Category-level keys were read by nobody and reported by nobody."""

    def test_scope_keys_reach_every_gate_in_the_category(self) -> None:
        config = {
            "laziness": {
                "enabled": True,
                "include_dirs": ["paperbot"],
                "gates": {"sloppy-formatting.py": {"enabled": True}},
            }
        }
        reg = get_registry()
        gate_cfg = reg._extract_gate_config("laziness:sloppy-formatting.py", config)
        assert gate_cfg.get("include_dirs") == ["paperbot"]

    def test_gate_level_setting_wins_over_the_category(self) -> None:
        config = {
            "laziness": {
                "include_dirs": ["paperbot"],
                "gates": {"sloppy-formatting.py": {"include_dirs": ["other"]}},
            }
        }
        gate_cfg = get_registry()._extract_gate_config(
            "laziness:sloppy-formatting.py", config
        )
        assert gate_cfg.get("include_dirs") == ["other"]

    def test_non_scope_keys_do_not_leak_down(self) -> None:
        """A category-wide `threshold` would silently redefine unrelated gates."""
        config = {
            "laziness": {
                "enabled": True,
                "threshold": 99,
                "gates": {"sloppy-formatting.py": {}},
            }
        }
        gate_cfg = get_registry()._extract_gate_config(
            "laziness:sloppy-formatting.py", config
        )
        assert "threshold" not in gate_cfg


class TestQuarantineFormattersAreConfigured:
    """The formatting pass built its gates with config={} and rewrote the tree."""

    def test_formatters_receive_the_repo_config(self, scoped_repo: Path) -> None:
        from slopmop.cli._refit_formatting import _collect_applicable_formatters

        formatters = _collect_applicable_formatters(str(scoped_repo))
        assert formatters, "expected at least one applicable formatting gate"
        for check in formatters:
            assert check.config, f"{check.name} was built with empty config"
        scoped = [c for c in formatters if c.config.get("include_dirs")]
        assert scoped, "no formatter saw the repo's include_dirs"

    def test_out_of_scope_files_are_called_out(
        self, scoped_repo: Path, monkeypatch
    ) -> None:
        from slopmop.cli import _refit_formatting as fmt

        lines = fmt._out_of_scope_warning(scoped_repo, ["paperbot/bot.py", "demo.py"])
        assert lines and "1 file(s) fall outside" in lines[0]

    def test_in_scope_pass_is_quiet(self, scoped_repo: Path, monkeypatch) -> None:
        from slopmop.cli import _refit_formatting as fmt

        assert fmt._out_of_scope_warning(scoped_repo, ["paperbot/bot.py"]) == []

    def test_warning_never_breaks_the_commit(self, tmp_path: Path, monkeypatch) -> None:
        """Belt and braces must not become a new failure mode."""
        from slopmop.cli import _refit_formatting as fmt

        assert fmt._out_of_scope_warning(tmp_path, ["anything.py"]) == []  # no config


class TestReviewReusesThePrecheck:
    """Approving a gate is a judgement about output the operator already read.

    ``--approve-gate`` is documented as recording that "a gate's current
    precheck output looks trustworthy". Every invocation rebuilt the precheck
    first — probing every gate with a full single-gate scour — so the approval
    landed on freshly generated output nobody had seen, and working through a
    twenty-gate review cost twenty complete prechecks (#358).
    """

    @staticmethod
    def _args(**overrides: Any):
        import argparse

        base = dict(
            approve_gate=[],
            record_blocker=None,
            blocker_issue=None,
            blocker_reason=None,
            json_output=True,
        )
        base.update(overrides)
        return argparse.Namespace(**base)

    @staticmethod
    def _precheck(gate: str = "laziness:dead-code.py") -> Dict[str, Any]:
        return {
            "schema": "refit-precheck/v1",
            "recorded_at": "2026-01-01T00:00:00+00:00",
            "project_root": ".",
            "gates": [
                {
                    "gate": gate,
                    "display_name": "dead-code.py",
                    "enabled": True,
                    "applicable": True,
                    "probe_status": "runnable",
                    "review_status": "pending",
                    "config_fingerprint": "fp",
                    "missing_tools": [],
                }
            ],
            "status": "blocked_on_gate_fidelity",
        }

    def test_approving_does_not_reprobe(self, tmp_path: Path, monkeypatch) -> None:
        from slopmop.cli import refit as refit_mod

        calls: list[int] = []
        monkeypatch.setattr(refit_mod, "load_precheck", lambda _root: self._precheck())
        monkeypatch.setattr(
            refit_mod,
            "build_precheck",
            lambda *a, **k: calls.append(1) or self._precheck(),
        )
        monkeypatch.setattr(refit_mod, "save_precheck", lambda *a, **k: None)
        monkeypatch.setattr(
            refit_mod, "_precheck_matches_current_config", lambda *a: True
        )

        refit_mod._run_start_precheck_stage(
            self._args(approve_gate=["laziness:dead-code.py"]), tmp_path
        )
        assert calls == [], "approval rebuilt the precheck it was approving"

    def test_recording_a_blocker_does_not_reprobe(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        from slopmop.cli import refit as refit_mod

        calls: list[int] = []
        monkeypatch.setattr(refit_mod, "load_precheck", lambda _root: self._precheck())
        monkeypatch.setattr(
            refit_mod,
            "build_precheck",
            lambda *a, **k: calls.append(1) or self._precheck(),
        )
        monkeypatch.setattr(refit_mod, "save_precheck", lambda *a, **k: None)
        monkeypatch.setattr(
            refit_mod, "_precheck_matches_current_config", lambda *a: True
        )

        refit_mod._run_start_precheck_stage(
            self._args(
                record_blocker="laziness:dead-code.py",
                blocker_issue="#1",
                blocker_reason="tool bug",
            ),
            tmp_path,
        )
        assert calls == []

    def test_a_plain_start_still_probes(self, tmp_path: Path, monkeypatch) -> None:
        """Reuse must not mean a stale precheck is never refreshed."""
        from slopmop.cli import refit as refit_mod

        calls: list[int] = []
        monkeypatch.setattr(refit_mod, "load_precheck", lambda _root: self._precheck())
        monkeypatch.setattr(
            refit_mod,
            "build_precheck",
            lambda *a, **k: calls.append(1) or self._precheck(),
        )
        monkeypatch.setattr(refit_mod, "save_precheck", lambda *a, **k: None)

        refit_mod._run_start_precheck_stage(self._args(), tmp_path)
        assert calls == [1]

    def test_first_run_with_no_precheck_builds_one(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """Approving before any precheck exists must not reuse nothing."""
        from slopmop.cli import refit as refit_mod

        calls: list[int] = []
        monkeypatch.setattr(refit_mod, "load_precheck", lambda _root: None)
        monkeypatch.setattr(
            refit_mod,
            "build_precheck",
            lambda *a, **k: calls.append(1) or self._precheck(),
        )
        monkeypatch.setattr(refit_mod, "save_precheck", lambda *a, **k: None)

        refit_mod._run_start_precheck_stage(
            self._args(approve_gate=["laziness:dead-code.py"]), tmp_path
        )
        assert calls == [1]

    def test_several_gates_approve_in_one_invocation(self) -> None:
        """The flag is documented "Repeatable" — hold the parser to it."""
        from slopmop.sm import create_parser

        gates = [f"laziness:gate{i}.py" for i in range(20)]
        argv = ["refit", "--start"]
        for gate in gates:
            argv += ["--approve-gate", gate]
        parsed = create_parser().parse_args(argv)
        assert parsed.approve_gate == gates


class TestQuarantineCommitIsLegible:
    """The commit lands unasked, so its contents must be readable as it happens.

    It printed a count alone: a pass that rewrote 46 files across excluded
    directories announced "46 file(s) reformatted" and committed, leaving the
    damage to be found later in git log (#357).
    """

    @staticmethod
    def _args():
        import argparse

        return argparse.Namespace(json_output=False)

    @staticmethod
    def _wire(monkeypatch, scoped_repo: Path, changed: list[str]) -> list[list[str]]:
        """Stub the formatters and git; return the list of git argv calls made."""
        from slopmop.cli import _refit_formatting as fmt

        class _Fmt:
            name = "sloppy-formatting.py"
            display_name = "sloppy-formatting.py"
            config: Dict[str, Any] = {}

            def auto_fix(self, _root: str) -> bool:
                return True

        monkeypatch.setattr(
            fmt, "_collect_applicable_formatters", lambda _root: [_Fmt()]
        )
        # Clean before formatting, `changed` afterwards.
        states = iter([[], [f" M {p}" for p in changed]])
        monkeypatch.setattr(
            fmt._refit, "_worktree_status", lambda _root: next(states, [])
        )
        calls: list[list[str]] = []

        def _git_output(_root: Path, *args: str):
            calls.append(list(args))
            return 0, "", ""

        monkeypatch.setattr(fmt._refit, "_git_output", _git_output)
        monkeypatch.setattr(fmt._refit, "_current_head", lambda _root: "abc12345")
        return calls

    def test_files_are_listed_before_the_commit(
        self, scoped_repo: Path, monkeypatch, capsys
    ) -> None:
        from slopmop.cli import _refit_formatting as fmt

        self._wire(monkeypatch, scoped_repo, ["paperbot/bot.py"])
        assert fmt.run_formatting_quarantine_commit(self._args(), scoped_repo) is True

        out = capsys.readouterr().out
        assert "1 file(s) reformatted:" in out
        assert "paperbot/bot.py" in out
        assert "Formatting commit created" in out

    def test_out_of_scope_files_are_flagged_before_committing(
        self, scoped_repo: Path, monkeypatch, capsys
    ) -> None:
        """The thing that would have caught the reported blowup as it happened."""
        from slopmop.cli import _refit_formatting as fmt

        self._wire(monkeypatch, scoped_repo, ["paperbot/bot.py", "demo.py"])
        fmt.run_formatting_quarantine_commit(self._args(), scoped_repo)

        out = capsys.readouterr().out
        warn_index = out.index("fall outside")
        assert (
            out.index("Committing as dedicated") > warn_index
        ), "the warning must appear before the commit line, not after"

    def test_long_lists_are_truncated(
        self, scoped_repo: Path, monkeypatch, capsys
    ) -> None:
        from slopmop.cli import _refit_formatting as fmt

        many = [f"paperbot/mod{i}.py" for i in range(40)]
        self._wire(monkeypatch, scoped_repo, many)
        fmt.run_formatting_quarantine_commit(self._args(), scoped_repo)

        out = capsys.readouterr().out
        assert "40 file(s) reformatted:" in out
        assert f"... and {40 - fmt._FORMATTING_PREVIEW_LIMIT} more" in out

    def test_nothing_to_format_makes_no_commit(
        self, scoped_repo: Path, monkeypatch, capsys
    ) -> None:
        from slopmop.cli import _refit_formatting as fmt

        calls = self._wire(monkeypatch, scoped_repo, [])
        assert fmt.run_formatting_quarantine_commit(self._args(), scoped_repo) is True
        assert calls == []
        assert "already fully formatted" in capsys.readouterr().out


class TestReviewFindings:
    """Cases raised in review on #359, each a way the scope fix could misfire."""

    def test_include_dirs_spellings_all_match(self, scoped_repo: Path) -> None:
        """`./paperbot`, `paperbot/` and a backslash name the same directory.

        Every other path filter is normalized; an unnormalized one turns a
        declared scope into no scope at all, which is the failure this PR is
        about.
        """
        expected = ["paperbot/bot.py"]
        for spelling in ("paperbot", "./paperbot", "paperbot/", "paperbot\\"):
            assert (
                resolve_tool_paths(
                    str(scoped_repo), extensions={".py"}, include_dirs=[spelling]
                )
                == expected
            ), spelling

    def test_include_dirs_declares_no_permissiveness_direction(self) -> None:
        """Both directions of the existing comparison are wrong for this field.

        Dropping an entry narrows what is checked, so "fewer" is more
        permissive rather than stricter, and `[]` means the whole project — so
        the broadest setting looks like the smallest list.
        """
        field = next(
            f
            for f in PythonLintFormatCheck({}).config_schema
            if f.name == "include_dirs"
        )
        assert field.permissiveness is None

    def test_a_disabled_formatter_is_not_run(self, tmp_path: Path) -> None:
        """Reading the config and then ignoring `enabled: false` is the same bug."""
        from slopmop.cli._refit_formatting import _collect_applicable_formatters

        (tmp_path / "pkg").mkdir()
        (tmp_path / "pkg" / "mod.py").write_text("x=1\n")
        (tmp_path / ".sb_config.json").write_text(
            json.dumps(
                {
                    "laziness": {
                        "enabled": True,
                        "gates": {"sloppy-formatting.py": {"enabled": False}},
                    }
                }
            )
        )
        _commit_initial_repo(tmp_path)

        names = {c.name for c in _collect_applicable_formatters(str(tmp_path))}
        assert "sloppy-formatting.py" not in names

    def test_a_disabled_category_is_not_run(self, tmp_path: Path) -> None:
        from slopmop.cli._refit_formatting import _collect_applicable_formatters

        (tmp_path / "pkg").mkdir()
        (tmp_path / "pkg" / "mod.py").write_text("x=1\n")
        (tmp_path / ".sb_config.json").write_text(
            json.dumps({"laziness": {"enabled": False, "gates": {}}})
        )
        _commit_initial_repo(tmp_path)

        names = {c.name for c in _collect_applicable_formatters(str(tmp_path))}
        assert "sloppy-formatting.py" not in names

    def test_an_unmentioned_gate_still_runs(self, scoped_repo: Path) -> None:
        """Absent means on — a repo that never named the gate keeps today's behaviour."""
        from slopmop.cli._refit_formatting import _collect_applicable_formatters

        assert _collect_applicable_formatters(str(scoped_repo))


class TestStalePrecheckIsRejected:
    """Reuse is only safe while the saved run still describes the gates.

    ``build_precheck`` compares config fingerprints and resets an approval
    whose gate was reconfigured. Skipping the rebuild skips that comparison,
    so a config edited after the probe could have its old output approved and
    then be planned against the new config.
    """

    @staticmethod
    def _saved(fingerprint: str = "fp") -> Dict[str, Any]:
        return {
            "gates": [
                {"gate": "laziness:dead-code.py", "config_fingerprint": fingerprint}
            ]
        }

    @staticmethod
    def _records(monkeypatch, fingerprint: str) -> None:
        import slopmop.doctor.gate_preflight as gp
        from slopmop.doctor.gate_preflight import GatePreflightRecord

        monkeypatch.setattr(
            gp,
            "gather_gate_preflight_records",
            lambda _root: [
                GatePreflightRecord(
                    gate="laziness:dead-code.py",
                    display_name="dead-code.py",
                    enabled=True,
                    applicable=True,
                    skip_reason="",
                    config_fingerprint=fingerprint,
                    missing_tools=(),
                )
            ],
        )

    def test_matching_fingerprints_allow_reuse(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        from slopmop.cli.refit import _precheck_matches_current_config

        self._records(monkeypatch, "fp")
        assert _precheck_matches_current_config(tmp_path, self._saved("fp")) is True

    def test_changed_fingerprint_forces_a_rebuild(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        from slopmop.cli.refit import _precheck_matches_current_config

        self._records(monkeypatch, "fp-new")
        assert _precheck_matches_current_config(tmp_path, self._saved("fp")) is False

    def test_a_new_gate_forces_a_rebuild(self, tmp_path: Path, monkeypatch) -> None:
        """A gate that appeared since the probe has no reviewed output at all."""
        from slopmop.cli.refit import _precheck_matches_current_config

        self._records(monkeypatch, "fp")
        saved = {"gates": []}
        assert _precheck_matches_current_config(tmp_path, saved) is False

    def test_corrupt_precheck_forces_a_rebuild(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        from slopmop.cli.refit import _precheck_matches_current_config

        self._records(monkeypatch, "fp")
        assert _precheck_matches_current_config(tmp_path, {}) is False

    def test_stale_precheck_is_rebuilt_before_approval(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """End to end: the approval must not land on output that moved on."""
        from slopmop.cli import refit as refit_mod

        calls: list[int] = []
        monkeypatch.setattr(refit_mod, "load_precheck", lambda _root: self._saved())
        monkeypatch.setattr(
            refit_mod,
            "build_precheck",
            lambda *a, **k: calls.append(1) or self._saved(),
        )
        monkeypatch.setattr(refit_mod, "save_precheck", lambda *a, **k: None)
        monkeypatch.setattr(
            refit_mod, "_precheck_matches_current_config", lambda *a: False
        )

        refit_mod._run_start_precheck_stage(
            argparse.Namespace(
                approve_gate=["laziness:dead-code.py"],
                record_blocker=None,
                blocker_issue=None,
                blocker_reason=None,
                json_output=True,
            ),
            tmp_path,
        )
        assert calls == [1], "a stale precheck was reused for an approval"
