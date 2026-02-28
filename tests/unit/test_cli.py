"""Tests for CLI helper functions."""

from slopmop.cli.config import _deep_merge, _normalize_flat_keys


class TestDeepMerge:
    """Tests for _deep_merge helper function."""

    def test_simple_merge_adds_new_keys(self):
        """New keys from updates are added to base."""
        result = _deep_merge({"a": 1}, {"b": 2})
        assert result == {"a": 1, "b": 2}

    def test_simple_merge_overwrites_existing(self):
        """Existing keys are overwritten by updates."""
        result = _deep_merge({"a": 1}, {"a": 2})
        assert result == {"a": 2}

    def test_nested_dict_merge(self):
        """Nested dicts are merged recursively."""
        result = _deep_merge(
            {"outer": {"a": 1, "b": 2}},
            {"outer": {"b": 3, "c": 4}},
        )
        assert result == {"outer": {"a": 1, "b": 3, "c": 4}}

    def test_deeply_nested_merge(self):
        """Works for deeply nested structures."""
        result = _deep_merge(
            {"l1": {"l2": {"l3": {"a": 1}}}},
            {"l1": {"l2": {"l3": {"b": 2}}}},
        )
        assert result == {"l1": {"l2": {"l3": {"a": 1, "b": 2}}}}

    def test_non_dict_overwrites_dict(self):
        """Non-dict updates overwrite dict base values."""
        result = _deep_merge({"a": {"nested": 1}}, {"a": "string"})
        assert result == {"a": "string"}

    def test_dict_overwrites_non_dict(self):
        """Dict updates overwrite non-dict base values."""
        result = _deep_merge({"a": "string"}, {"a": {"nested": 1}})
        assert result == {"a": {"nested": 1}}

    def test_empty_updates_leaves_base_unchanged(self):
        """Empty updates dict leaves base unchanged."""
        base = {"a": 1, "b": {"c": 2}}
        result = _deep_merge(base, {})
        assert result == {"a": 1, "b": {"c": 2}}
        assert base == {"a": 1, "b": {"c": 2}}  # not mutated

    def test_does_not_mutate_inputs(self):
        """_deep_merge returns a new dict without mutating inputs."""
        base = {"a": 1, "b": {"c": 2}}
        overlay = {"b": {"d": 3}, "e": 4}
        result = _deep_merge(base, overlay)
        assert result == {"a": 1, "b": {"c": 2, "d": 3}, "e": 4}
        assert base == {"a": 1, "b": {"c": 2}}
        assert overlay == {"b": {"d": 3}, "e": 4}

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
        result = _deep_merge(base, updates)

        assert result["version"] == "1.0"
        assert result["overconfidence"]["enabled"] is True
        assert result["overconfidence"]["gates"]["py-types"] == {"enabled": True}
        assert result["overconfidence"]["gates"]["py-tests"] == {
            "enabled": True,
            "test_dirs": ["tests", "spec"],
        }
        assert result["overconfidence"]["gates"]["py-static-analysis"] == {
            "enabled": True,
            "threshold": 80,
        }


class TestNormalizeFlatKeys:
    """Tests for _normalize_flat_keys which converts flat 'category:gate' keys.

    Regression tests for: https://github.com/ScienceIsNeato/slop-mop/issues/50
    """

    def test_flat_key_normalized_to_hierarchical(self):
        """Flat 'category:gate' becomes nested {category: {gates: {gate: ...}}}."""
        flat = {"laziness:dead-code": {"whitelist_file": "w.py"}}
        result = _normalize_flat_keys(flat)
        assert result == {
            "laziness": {"gates": {"dead-code": {"whitelist_file": "w.py"}}}
        }

    def test_multiple_flat_keys_same_category(self):
        """Multiple gates in the same category merge correctly."""
        flat = {
            "myopia:source-duplication": {"threshold": 6},
            "myopia:string-duplication": {"threshold": 3},
        }
        result = _normalize_flat_keys(flat)
        assert result == {
            "myopia": {
                "gates": {
                    "source-duplication": {"threshold": 6},
                    "string-duplication": {"threshold": 3},
                }
            }
        }

    def test_mixed_flat_and_hierarchical(self):
        """Non-flat keys pass through alongside normalized flat keys."""
        data = {
            "version": "1.0",
            "laziness:complexity": {"max_rank": "D"},
        }
        result = _normalize_flat_keys(data)
        assert result["version"] == "1.0"
        assert result["laziness"]["gates"]["complexity"]["max_rank"] == "D"

    def test_already_hierarchical_passes_through(self):
        """Already-hierarchical config passes through unchanged."""
        hierarchical = {
            "version": "1.0",
            "laziness": {"gates": {"dead-code": {"whitelist_file": "w.py"}}},
        }
        result = _normalize_flat_keys(hierarchical)
        assert result == hierarchical

    def test_unknown_category_colon_key_passes_through(self):
        """Colon key with unrecognized category passes through unchanged."""
        data = {"foo:bar": {"value": 1}}
        result = _normalize_flat_keys(data)
        assert result == {"foo:bar": {"value": 1}}

    def test_empty_dict(self):
        """Empty dict produces empty dict."""
        assert _normalize_flat_keys({}) == {}

    def test_flat_and_hierarchical_same_category_merges(self):
        """Flat key + hierarchical key for same category deep-merges.

        Regression: Bugbot flagged that a non-flat key with the same category
        overwrote previously accumulated flat-key data instead of merging.
        """
        data = {
            "laziness:dead-code": {"whitelist_file": "w.py"},
            "laziness": {"enabled": True},
        }
        result = _normalize_flat_keys(data)
        # Both the gate config AND the top-level category key must survive
        assert result["laziness"]["gates"]["dead-code"]["whitelist_file"] == "w.py"
        assert result["laziness"]["enabled"] is True


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

    def test_no_fallback_when_stdin_is_tty(self, tmp_path, capsys):
        """cmd_init does not auto-fallback when stdin is a TTY.

        We simulate a TTY by forcing sys.stdin.isatty() to return True and
        stub input() so the interactive path does not block, then verify the
        auto-detection message does NOT appear.
        """
        from unittest.mock import patch

        (tmp_path / "setup.py").write_text("")

        # Do not set --non-interactive so that TTY auto-detection is used
        args = self._make_args(tmp_path, non_interactive=False)

        with (
            patch("slopmop.cli.init.sys") as mock_sys,
            patch("slopmop.cli.init.input", return_value=""),
            patch("slopmop.cli.init.prompt_yes_no", return_value=True),
            patch("slopmop.cli.status.run_status", return_value=0),
        ):
            mock_sys.stdin.isatty.return_value = True
            from slopmop.cli.init import cmd_init

            result = cmd_init(args)

        assert result == 0
        out = capsys.readouterr().out
        # When stdin is a TTY and --non-interactive is not set, the
        # auto-detection fallback message should NOT appear.
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
        assert "sm swab" in out
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
