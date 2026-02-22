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
