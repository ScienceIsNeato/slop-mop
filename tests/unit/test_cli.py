"""Tests for CLI module."""

from unittest.mock import MagicMock, patch

import pytest  # noqa: F401  # Required for fixtures

from slopbucket.cli import create_parser, list_aliases, list_checks, main, setup_logging


class TestCLI:
    """Tests for CLI functions."""

    def test_create_parser(self):
        """Test parser creation."""
        parser = create_parser()
        assert parser is not None
        assert parser.prog == "slopbucket"

    def test_parser_checks_argument(self):
        """Test parser accepts --checks argument."""
        parser = create_parser()
        args = parser.parse_args(["--checks", "commit"])
        assert args.checks == ["commit"]

    def test_parser_multiple_checks(self):
        """Test parser accepts multiple checks."""
        parser = create_parser()
        args = parser.parse_args(["--checks", "lint", "tests"])
        assert args.checks == ["lint", "tests"]

    def test_parser_project_root(self):
        """Test parser accepts --project-root."""
        parser = create_parser()
        args = parser.parse_args(["--checks", "commit", "--project-root", "/tmp"])
        assert args.project_root == "/tmp"

    def test_parser_no_auto_fix(self):
        """Test parser accepts --no-auto-fix."""
        parser = create_parser()
        args = parser.parse_args(["--checks", "commit", "--no-auto-fix"])
        assert args.no_auto_fix is True

    def test_parser_no_fail_fast(self):
        """Test parser accepts --no-fail-fast."""
        parser = create_parser()
        args = parser.parse_args(["--checks", "commit", "--no-fail-fast"])
        assert args.no_fail_fast is True

    def test_parser_verbose(self):
        """Test parser accepts --verbose."""
        parser = create_parser()
        args = parser.parse_args(["--checks", "commit", "--verbose"])
        assert args.verbose is True

    def test_parser_quiet(self):
        """Test parser accepts --quiet."""
        parser = create_parser()
        args = parser.parse_args(["--checks", "commit", "--quiet"])
        assert args.quiet is True

    def test_parser_list_checks(self):
        """Test parser accepts --list-checks."""
        parser = create_parser()
        args = parser.parse_args(["--list-checks"])
        assert args.list_checks is True

    def test_parser_list_aliases(self):
        """Test parser accepts --list-aliases."""
        parser = create_parser()
        args = parser.parse_args(["--list-aliases"])
        assert args.list_aliases is True

    def test_setup_logging_default(self):
        """Test setup_logging with default level."""
        setup_logging(verbose=False)
        # Just verify it doesn't raise

    def test_setup_logging_verbose(self):
        """Test setup_logging with verbose level."""
        setup_logging(verbose=True)
        # Just verify it doesn't raise

    @patch("slopbucket.cli.get_registry")
    def test_list_checks_output(self, mock_get_registry, capsys):
        """Test list_checks prints checks."""
        mock_registry = MagicMock()
        mock_registry.list_checks.return_value = ["check1", "check2"]
        mock_registry.get_definition.return_value = None
        mock_get_registry.return_value = mock_registry

        list_checks()

        captured = capsys.readouterr()
        assert "Available Checks" in captured.out
        assert "check1" in captured.out
        assert "check2" in captured.out

    @patch("slopbucket.cli.get_registry")
    def test_list_aliases_output(self, mock_get_registry, capsys):
        """Test list_aliases prints aliases."""
        mock_registry = MagicMock()
        mock_registry.list_aliases.return_value = {"commit": ["lint", "tests"]}
        mock_get_registry.return_value = mock_registry

        list_aliases()

        captured = capsys.readouterr()
        assert "Check Aliases" in captured.out
        assert "commit" in captured.out

    def test_main_no_checks_shows_help(self, capsys):
        """Test main with no checks shows help."""
        result = main([])
        assert result == 1
        captured = capsys.readouterr()
        assert "--checks is required" in captured.out

    @patch("slopbucket.cli.run_checks")
    @patch("slopbucket.checks.register_all_checks")
    def test_main_list_checks(self, mock_register, mock_run, capsys):
        """Test main with --list-checks."""
        result = main(["--list-checks"])
        assert result == 0
        mock_register.assert_called_once()

    @patch("slopbucket.cli.run_checks")
    @patch("slopbucket.checks.register_all_checks")
    def test_main_list_aliases(self, mock_register, mock_run, capsys):
        """Test main with --list-aliases."""
        result = main(["--list-aliases"])
        assert result == 0
        mock_register.assert_called_once()

    def test_main_invalid_project_root(self, capsys):
        """Test main with invalid project root."""
        result = main(
            ["--checks", "commit", "--project-root", "/nonexistent/path/xyz123"]
        )
        assert result == 1
        captured = capsys.readouterr()
        assert "not found" in captured.out

    @patch("slopbucket.cli.run_checks")
    def test_main_passes_args_to_run_checks(self, mock_run_checks, tmp_path):
        """Test main passes arguments correctly to run_checks."""
        mock_run_checks.return_value = 0

        result = main(
            [
                "--checks",
                "check1",
                "check2",
                "--project-root",
                str(tmp_path),
                "--no-auto-fix",
                "--no-fail-fast",
                "--verbose",
                "--quiet",
            ]
        )

        assert result == 0
        mock_run_checks.assert_called_once_with(
            check_names=["check1", "check2"],
            project_root=str(tmp_path),
            auto_fix=False,
            fail_fast=False,
            verbose=True,
            quiet=True,
        )

    @patch("slopbucket.cli.get_registry")
    def test_list_checks_empty(self, mock_get_registry, capsys):
        """Test list_checks with empty registry."""
        mock_registry = MagicMock()
        mock_registry.list_checks.return_value = []
        mock_get_registry.return_value = mock_registry

        list_checks()

        captured = capsys.readouterr()
        assert "No checks registered" in captured.out

    @patch("slopbucket.cli.get_registry")
    def test_list_aliases_empty(self, mock_get_registry, capsys):
        """Test list_aliases with empty registry."""
        mock_registry = MagicMock()
        mock_registry.list_aliases.return_value = {}
        mock_get_registry.return_value = mock_registry

        list_aliases()

        captured = capsys.readouterr()
        assert "No aliases registered" in captured.out

    def test_parser_short_verbose(self):
        """Test parser accepts -v for verbose."""
        parser = create_parser()
        args = parser.parse_args(["--checks", "commit", "-v"])
        assert args.verbose is True

    def test_parser_short_quiet(self):
        """Test parser accepts -q for quiet."""
        parser = create_parser()
        args = parser.parse_args(["--checks", "commit", "-q"])
        assert args.quiet is True

    def test_parser_default_project_root(self):
        """Test parser default project root is current directory."""
        parser = create_parser()
        args = parser.parse_args(["--checks", "commit"])
        assert args.project_root == "."
