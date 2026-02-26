"""Tests for CLI helper functions."""

from slopmop.cli.init import _deep_merge


class TestDeepMerge:
    """Tests for _deep_merge helper function."""

    def test_simple_merge_adds_new_keys(self):
        """New keys from updates are added to base."""
        base = {"a": 1}
        updates = {"b": 2}
        _deep_merge(base, updates)
        assert base == {"a": 1, "b": 2}

    def test_simple_merge_overwrites_existing(self):
        """Existing keys are overwritten by updates."""
        base = {"a": 1}
        updates = {"a": 2}
        _deep_merge(base, updates)
        assert base == {"a": 2}

    def test_nested_dict_merge(self):
        """Nested dicts are merged recursively."""
        base = {"outer": {"a": 1, "b": 2}}
        updates = {"outer": {"b": 3, "c": 4}}
        _deep_merge(base, updates)
        assert base == {"outer": {"a": 1, "b": 3, "c": 4}}

    def test_deeply_nested_merge(self):
        """Works for deeply nested structures."""
        base = {"l1": {"l2": {"l3": {"a": 1}}}}
        updates = {"l1": {"l2": {"l3": {"b": 2}}}}
        _deep_merge(base, updates)
        assert base == {"l1": {"l2": {"l3": {"a": 1, "b": 2}}}}

    def test_non_dict_overwrites_dict(self):
        """Non-dict updates overwrite dict base values."""
        base = {"a": {"nested": 1}}
        updates = {"a": "string"}
        _deep_merge(base, updates)
        assert base == {"a": "string"}

    def test_dict_overwrites_non_dict(self):
        """Dict updates overwrite non-dict base values."""
        base = {"a": "string"}
        updates = {"a": {"nested": 1}}
        _deep_merge(base, updates)
        assert base == {"a": {"nested": 1}}

    def test_empty_updates_leaves_base_unchanged(self):
        """Empty updates dict leaves base unchanged."""
        base = {"a": 1, "b": {"c": 2}}
        _deep_merge(base, {})
        assert base == {"a": 1, "b": {"c": 2}}

    def test_config_like_structure(self):
        """Works with slopmop config-like structures."""
        base = {
            "version": "1.0",
            "overconfidence": {
                "enabled": False,
                "gates": {
                    "py-tests": {"enabled": True},
                    "py-types": {"enabled": True},
                },
            },
        }
        updates = {
            "overconfidence": {
                "enabled": True,
                "gates": {
                    "py-tests": {"test_dirs": ["tests", "spec"]},
                    "py-static-analysis": {"enabled": True, "threshold": 80},
                },
            }
        }
        _deep_merge(base, updates)

        assert base["version"] == "1.0"
        assert base["overconfidence"]["enabled"] is True
        assert base["overconfidence"]["gates"]["py-types"] == {"enabled": True}
        assert base["overconfidence"]["gates"]["py-tests"] == {
            "enabled": True,
            "test_dirs": ["tests", "spec"],
        }
        assert base["overconfidence"]["gates"]["py-static-analysis"] == {
            "enabled": True,
            "threshold": 80,
        }


class TestCmdInitNonInteractiveDetection:
    """Tests for automatic non-interactive terminal detection in sm init."""

    def _make_args(self, tmp_path, non_interactive=False):
        """Create an argparse Namespace mimicking sm init."""
        import argparse

        return argparse.Namespace(
            project_root=str(tmp_path),
            config=None,
            non_interactive=non_interactive,
        )

    def test_falls_back_when_stdin_not_tty(self, tmp_path, capsys):
        """cmd_init auto-detects non-interactive terminal and uses defaults."""
        from unittest.mock import patch

        # Ensure there's a detectable project file
        (tmp_path / "setup.py").write_text("")

        args = self._make_args(tmp_path, non_interactive=False)

        with (
            patch("slopmop.cli.init.sys") as mock_sys,
            patch("slopmop.cli.status.run_status", return_value=0),
        ):
            mock_sys.stdin.isatty.return_value = False
            from slopmop.cli.init import cmd_init

            result = cmd_init(args)

        assert result == 0
        out = capsys.readouterr().out
        assert "Non-interactive terminal detected" in out
        assert "auto-detected defaults" in out

    def test_no_fallback_when_stdin_is_tty(self, tmp_path, capsys, monkeypatch):
        """cmd_init uses interactive mode when stdin is a TTY.

        We pass --non-interactive explicitly to avoid actually blocking on
        input(), but verify the auto-detection message does NOT appear.
        """
        from unittest.mock import patch

        (tmp_path / "setup.py").write_text("")

        # Explicitly pass non_interactive=True to avoid blocking input()
        args = self._make_args(tmp_path, non_interactive=True)

        with patch("slopmop.cli.status.run_status", return_value=0):
            from slopmop.cli.init import cmd_init

            result = cmd_init(args)

        assert result == 0
        out = capsys.readouterr().out
        # When --non-interactive is explicitly set, the auto-detection
        # message should NOT appear (it only shows on auto-fallback)
        assert "Non-interactive terminal detected" not in out

    def test_explicit_non_interactive_flag_skips_tty_check(self, tmp_path, capsys):
        """--non-interactive flag works regardless of TTY status."""
        from unittest.mock import patch

        (tmp_path / "setup.py").write_text("")
        args = self._make_args(tmp_path, non_interactive=True)

        with (
            patch("slopmop.cli.init.sys") as mock_sys,
            patch("slopmop.cli.status.run_status", return_value=0),
        ):
            # Even with a TTY, --non-interactive should skip prompts
            mock_sys.stdin.isatty.return_value = True
            from slopmop.cli.init import cmd_init

            result = cmd_init(args)

        assert result == 0
        out = capsys.readouterr().out
        assert "Non-interactive mode: using detected defaults" in out


class TestPrintNextSteps:
    """Tests for _print_next_steps output."""

    def test_uses_sm_not_scripts_sm(self, capsys):
        """Next steps should reference 'sm', not './scripts/sm'."""
        from slopmop.cli.init import _print_next_steps

        _print_next_steps({})
        out = capsys.readouterr().out
        assert "./scripts/sm" not in out
        assert "sm validate commit" in out
        assert "sm config --disable" in out
        assert "sm status" in out
        assert "sm config --show" in out


class TestCmdValidateSelf:
    """Tests for --self validation behavior."""

    def test_self_validate_creates_temp_config(self):
        """Test that --self validation uses a temp config, not the real one."""
        import argparse
        import os
        from unittest.mock import MagicMock, patch

        # We can't easily test the full cmd_validate, but we can verify
        # the logic by checking that SB_CONFIG_FILE env var is set during --self
        # Create args simulating --self
        args = argparse.Namespace(
            self_validate=True,
            project_root=".",
            profile=None,
            quality_gates=None,
            no_fail_fast=False,
            no_auto_fix=False,
            verbose=False,
            quiet=True,
        )

        # Mock the executor to avoid actually running checks
        with patch("slopmop.cli.validate.CheckExecutor") as mock_executor_class:
            mock_executor = MagicMock()
            mock_summary = MagicMock()
            mock_summary.all_passed = True
            mock_executor.run_checks.return_value = mock_summary
            mock_executor_class.return_value = mock_executor

            with patch("slopmop.cli.validate.ConsoleReporter"):
                from slopmop.cli.validate import cmd_validate

                # Store original env
                original_env = os.environ.get("SB_CONFIG_FILE")

                try:
                    result = cmd_validate(args)

                    # After cmd_validate completes, env var should be cleaned up
                    assert os.environ.get("SB_CONFIG_FILE") is None
                    assert result == 0
                finally:
                    # Restore original env
                    if original_env:
                        os.environ["SB_CONFIG_FILE"] = original_env
                    elif "SB_CONFIG_FILE" in os.environ:
                        del os.environ["SB_CONFIG_FILE"]

    def test_self_validate_cleans_up_temp_dir(self):
        """Test that temp config dir is cleaned up after --self validation."""
        import argparse
        from pathlib import Path
        from unittest.mock import MagicMock, patch

        args = argparse.Namespace(
            self_validate=True,
            project_root=".",
            profile=None,
            quality_gates=None,
            no_fail_fast=False,
            no_auto_fix=False,
            verbose=False,
            quiet=True,
        )

        captured_temp_dir = []

        original_mkdtemp = __import__("tempfile").mkdtemp

        def capture_mkdtemp(*args, **kwargs):
            result = original_mkdtemp(*args, **kwargs)
            if "sb_self_validate_" in kwargs.get("prefix", ""):
                captured_temp_dir.append(result)
            return result

        with patch("slopmop.cli.validate.CheckExecutor") as mock_executor_class:
            mock_executor = MagicMock()
            mock_summary = MagicMock()
            mock_summary.all_passed = True
            mock_executor.run_checks.return_value = mock_summary
            mock_executor_class.return_value = mock_executor

            with patch("slopmop.cli.validate.ConsoleReporter"):
                with patch("tempfile.mkdtemp", capture_mkdtemp):
                    from slopmop.cli.validate import cmd_validate

                    cmd_validate(args)

                    # Temp dir should have been created
                    assert len(captured_temp_dir) == 1
                    # And should be cleaned up (not exist)
                    assert not Path(captured_temp_dir[0]).exists()
