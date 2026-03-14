"""Tests for workflow hook integration in CLI commands."""

from __future__ import annotations

import argparse
from pathlib import Path
from unittest.mock import patch

# ---------------------------------------------------------------------------
# validate.py — cmd_swab / cmd_scour / _load_config_for_hook
# ---------------------------------------------------------------------------


class TestCmdSwabHook:
    """on_swab_complete is called after a full (non -g) swab run."""

    def _make_args(self, tmp_path: Path, **overrides) -> argparse.Namespace:
        data = {
            "project_root": str(tmp_path),
            "fix": False,
            "verbose": False,
            "output_format": "console",
            "no_cache": True,
            "gates": None,
            "swabbing_time": None,
            "output_file": None,
        }
        data.update(overrides)
        return argparse.Namespace(**data)

    def test_hook_called_when_swab_passes(self, tmp_path):
        """on_swab_complete is called with passed=True when exit_code==0."""
        args = self._make_args(tmp_path)

        with (
            patch("slopmop.cli.validate._run_validation", return_value=0),
            patch("slopmop.cli.validate.ensure_checks_registered"),
            patch("slopmop.cli.validate.get_registry") as mock_reg,
            patch("slopmop.workflow.hooks.on_swab_complete") as mock_hook,
        ):
            mock_reg.return_value.get_gate_names_for_level.return_value = []

            from slopmop.cli.validate import cmd_swab

            result = cmd_swab(args)

        assert result == 0
        mock_hook.assert_called_once()
        _, kwargs = mock_hook.call_args
        assert kwargs["passed"] is True
        assert args.json_file == str(tmp_path / ".slopmop" / "last_swab.json")

    def test_hook_called_when_swab_fails(self, tmp_path):
        """on_swab_complete is called with passed=False when exit_code!=0."""
        args = self._make_args(tmp_path)

        with (
            patch("slopmop.cli.validate._run_validation", return_value=1),
            patch("slopmop.cli.validate.ensure_checks_registered"),
            patch("slopmop.cli.validate.get_registry") as mock_reg,
            patch("slopmop.workflow.hooks.on_swab_complete") as mock_hook,
        ):
            mock_reg.return_value.get_gate_names_for_level.return_value = []

            from slopmop.cli.validate import cmd_swab

            result = cmd_swab(args)

        assert result == 1
        mock_hook.assert_called_once()
        _, kwargs = mock_hook.call_args
        assert kwargs["passed"] is False

    def test_hook_skipped_for_explicit_gate_run(self, tmp_path):
        """Hook is NOT called when -g flag selects specific gates."""
        args = self._make_args(tmp_path, quality_gates=["myopia:string-duplication.py"])

        with (
            patch("slopmop.cli.validate._run_validation", return_value=0),
            patch("slopmop.cli.validate.ensure_checks_registered"),
            patch("slopmop.workflow.hooks.on_swab_complete") as mock_hook,
        ):
            from slopmop.cli.validate import cmd_swab

            cmd_swab(args)

        mock_hook.assert_not_called()
        assert not hasattr(args, "json_file") or args.json_file is None

    def test_hook_error_is_suppressed(self, tmp_path):
        """A failing hook never propagates to the caller."""
        args = self._make_args(tmp_path)

        with (
            patch("slopmop.cli.validate._run_validation", return_value=0),
            patch("slopmop.cli.validate.ensure_checks_registered"),
            patch("slopmop.cli.validate.get_registry") as mock_reg,
            patch(
                "slopmop.workflow.hooks.on_swab_complete",
                side_effect=RuntimeError("boom"),
            ),
        ):
            mock_reg.return_value.get_gate_names_for_level.return_value = []

            from slopmop.cli.validate import cmd_swab

            result = cmd_swab(args)

        assert result == 0  # error did not propagate


class TestCmdScourHook:
    """on_scour_complete is called after a full (non -g) scour run."""

    def _make_args(self, tmp_path: Path, **overrides) -> argparse.Namespace:
        data = {
            "project_root": str(tmp_path),
            "fix": False,
            "verbose": False,
            "output_format": "console",
            "no_cache": True,
            "gates": None,
            "output_file": None,
        }
        data.update(overrides)
        return argparse.Namespace(**data)

    def test_hook_called_when_scour_passes(self, tmp_path):
        """on_scour_complete is called with passed=True when exit_code==0."""
        args = self._make_args(tmp_path)

        with (
            patch("slopmop.cli.validate._run_validation", return_value=0),
            patch("slopmop.cli.validate.ensure_checks_registered"),
            patch("slopmop.cli.validate.get_registry") as mock_reg,
            patch("slopmop.workflow.hooks.on_scour_complete") as mock_hook,
        ):
            mock_reg.return_value.get_gate_names_for_level.return_value = []

            from slopmop.cli.validate import cmd_scour

            result = cmd_scour(args)

        assert result == 0
        mock_hook.assert_called_once()
        _, kwargs = mock_hook.call_args
        assert kwargs["passed"] is True
        assert args.json_file == str(tmp_path / ".slopmop" / "last_scour.json")

    def test_hook_called_when_scour_fails(self, tmp_path):
        """on_scour_complete is called with passed=False when exit_code!=0."""
        args = self._make_args(tmp_path)

        with (
            patch("slopmop.cli.validate._run_validation", return_value=1),
            patch("slopmop.cli.validate.ensure_checks_registered"),
            patch("slopmop.cli.validate.get_registry") as mock_reg,
            patch("slopmop.workflow.hooks.on_scour_complete") as mock_hook,
        ):
            mock_reg.return_value.get_gate_names_for_level.return_value = []

            from slopmop.cli.validate import cmd_scour

            result = cmd_scour(args)

        assert result == 1
        mock_hook.assert_called_once()
        _, kwargs = mock_hook.call_args
        assert kwargs["passed"] is False

    def test_hook_all_gates_enabled_when_no_disabled_config(self, tmp_path):
        """all_gates_enabled=True when config has no disabled_gates."""
        args = self._make_args(tmp_path)

        with (
            patch("slopmop.cli.validate._run_validation", return_value=0),
            patch("slopmop.cli.validate.ensure_checks_registered"),
            patch("slopmop.cli.validate.get_registry") as mock_reg,
            patch("slopmop.cli.validate._load_config_for_hook", return_value={}),
            patch("slopmop.workflow.hooks.on_scour_complete") as mock_hook,
        ):
            mock_reg.return_value.get_gate_names_for_level.return_value = []

            from slopmop.cli.validate import cmd_scour

            cmd_scour(args)

        _, kwargs = mock_hook.call_args
        assert kwargs["all_gates_enabled"] is True

    def test_hook_all_gates_disabled_when_config_has_disabled_gates(self, tmp_path):
        """all_gates_enabled=False when config disables some gates."""
        args = self._make_args(tmp_path)

        with (
            patch("slopmop.cli.validate._run_validation", return_value=0),
            patch("slopmop.cli.validate.ensure_checks_registered"),
            patch("slopmop.cli.validate.get_registry") as mock_reg,
            patch(
                "slopmop.cli.validate._load_config_for_hook",
                return_value={"disabled_gates": ["myopia:string-duplication.py"]},
            ),
            patch("slopmop.workflow.hooks.on_scour_complete") as mock_hook,
        ):
            mock_reg.return_value.get_gate_names_for_level.return_value = []

            from slopmop.cli.validate import cmd_scour

            cmd_scour(args)

        _, kwargs = mock_hook.call_args
        assert kwargs["all_gates_enabled"] is False

    def test_hook_skipped_for_explicit_gate_run(self, tmp_path):
        """Hook is NOT called when -g flag selects specific gates."""
        args = self._make_args(tmp_path, quality_gates=["myopia:string-duplication.py"])

        with (
            patch("slopmop.cli.validate._run_validation", return_value=0),
            patch("slopmop.cli.validate.ensure_checks_registered"),
            patch("slopmop.workflow.hooks.on_scour_complete") as mock_hook,
        ):
            from slopmop.cli.validate import cmd_scour

            cmd_scour(args)

        mock_hook.assert_not_called()


class TestLoadConfigForHook:
    """_load_config_for_hook returns config dict or empty dict on failure."""

    def test_returns_config_when_load_config_succeeds(self, tmp_path):
        """Returns parsed config from load_config."""
        from slopmop.cli.validate import _load_config_for_hook

        with patch(
            "slopmop.sm.load_config",
            return_value={"disabled_gates": ["foo"]},
        ):
            result = _load_config_for_hook(tmp_path)

        assert result == {"disabled_gates": ["foo"]}

    def test_returns_empty_dict_on_exception(self, tmp_path):
        """Returns {} when load_config raises."""
        from slopmop.cli.validate import _load_config_for_hook

        with patch("slopmop.sm.load_config", side_effect=RuntimeError("no config")):
            result = _load_config_for_hook(tmp_path)

        assert result == {}


# ---------------------------------------------------------------------------
# buff.py — _fire_buff_hook and on_iteration_started
# ---------------------------------------------------------------------------


class TestFireBuffHook:
    """_fire_buff_hook calls on_buff_complete with correct has_issues flag."""

    def test_fire_buff_hook_with_issues(self, tmp_path):
        from slopmop.cli.buff import _fire_buff_hook

        with (
            patch("slopmop.cli.buff._project_root_from_cwd", return_value=tmp_path),
            patch("slopmop.workflow.hooks.on_buff_complete") as mock_hook,
        ):
            _fire_buff_hook(has_issues=True)

        mock_hook.assert_called_once_with(tmp_path, has_issues=True)

    def test_fire_buff_hook_all_green(self, tmp_path):
        from slopmop.cli.buff import _fire_buff_hook

        with (
            patch("slopmop.cli.buff._project_root_from_cwd", return_value=tmp_path),
            patch("slopmop.workflow.hooks.on_buff_complete") as mock_hook,
        ):
            _fire_buff_hook(has_issues=False)

        mock_hook.assert_called_once_with(tmp_path, has_issues=False)

    def test_fire_buff_hook_error_is_suppressed(self, tmp_path):
        from slopmop.cli.buff import _fire_buff_hook

        with (
            patch("slopmop.cli.buff._project_root_from_cwd", return_value=tmp_path),
            patch(
                "slopmop.workflow.hooks.on_buff_complete",
                side_effect=RuntimeError("boom"),
            ),
        ):
            _fire_buff_hook(has_issues=True)  # must not raise


class TestBuffIterateHook:
    """on_iteration_started is called when buff iterate exits 0."""

    def test_iteration_started_called_on_success(self, tmp_path):
        from slopmop.cli.buff import cmd_buff

        args = argparse.Namespace(
            pr_or_action="iterate",
            action_args=[],
            interval=30,
            no_resolve=False,
            message=None,
            thread_id=None,
            push=False,
            project_root=str(tmp_path),
        )

        with (
            patch("slopmop.cli.buff._cmd_buff_iterate", return_value=0),
            patch("slopmop.cli.buff._project_root_from_cwd", return_value=tmp_path),
            patch("slopmop.workflow.hooks.on_iteration_started") as mock_hook,
        ):
            result = cmd_buff(args)

        assert result == 0
        mock_hook.assert_called_once()

    def test_iteration_started_not_called_on_failure(self, tmp_path):
        from slopmop.cli.buff import cmd_buff

        args = argparse.Namespace(
            pr_or_action="iterate",
            action_args=[],
            interval=30,
            no_resolve=False,
            message=None,
            thread_id=None,
            push=False,
            project_root=str(tmp_path),
        )

        with (
            patch("slopmop.cli.buff._cmd_buff_iterate", return_value=1),
            patch("slopmop.workflow.hooks.on_iteration_started") as mock_hook,
        ):
            result = cmd_buff(args)

        assert result == 1
        mock_hook.assert_not_called()


# ---------------------------------------------------------------------------
# executor.py — terminal check auto-dependency
# ---------------------------------------------------------------------------


class TestTerminalCheckDependency:
    """Terminal checks auto-depend on all non-terminal checks."""

    def test_terminal_check_depends_on_all_non_terminal(self, tmp_path):
        """A terminal=True check gets every other check as a dependency."""
        from slopmop.core.executor import CheckExecutor
        from slopmop.core.registry import CheckRegistry
        from tests.unit.test_executor import make_mock_check_class

        NormalCheckCls = make_mock_check_class("normal")
        NormalCheckCls.terminal = False

        TermCheckCls = make_mock_check_class("terminal")
        TermCheckCls.terminal = True

        registry = CheckRegistry()
        registry.register(NormalCheckCls)
        registry.register(TermCheckCls)

        normal = registry.get_check("overconfidence:normal", {})
        term = registry.get_check("overconfidence:terminal", {})

        executor = CheckExecutor(registry=registry)
        graph = executor._build_dependency_graph([normal, term])

        assert "overconfidence:normal" in graph["overconfidence:terminal"]
        assert graph["overconfidence:normal"] == set()

    def test_non_terminal_checks_keep_explicit_deps(self, tmp_path):
        """Non-terminal checks still use their declared depends_on."""
        from slopmop.core.executor import CheckExecutor
        from slopmop.core.registry import CheckRegistry
        from tests.unit.test_executor import make_mock_check_class

        CheckACls = make_mock_check_class("check-a")
        CheckBCls = make_mock_check_class(
            "check-b", depends_on=["overconfidence:check-a"]
        )

        registry = CheckRegistry()
        registry.register(CheckACls)
        registry.register(CheckBCls)

        check_a = registry.get_check("overconfidence:check-a", {})
        check_b = registry.get_check("overconfidence:check-b", {})

        executor = CheckExecutor(registry=registry)
        graph = executor._build_dependency_graph([check_a, check_b])

        assert graph["overconfidence:check-b"] == {"overconfidence:check-a"}
