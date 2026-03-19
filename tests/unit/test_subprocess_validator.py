"""Tests for subprocess command validator."""

import pytest

from slopmop.subprocess.validator import CommandValidator, SecurityError


class TestCommandValidator:
    """Tests for CommandValidator class."""

    def test_allows_whitelisted_python(self):
        """Test that python executable is allowed."""
        validator = CommandValidator()
        assert validator.validate(["python", "-m", "pytest"]) is True

    def test_allows_versioned_python_executables(self):
        """Test that versioned Python executables (python3.14, etc.) are accepted."""
        validator = CommandValidator()
        assert validator.validate(["python3.14", "-m", "pytest"]) is True
        assert validator.validate(["python3.13", "-m", "mypy"]) is True

    def test_allows_whitelisted_black(self):
        """Test that black is allowed."""
        validator = CommandValidator()
        assert validator.validate(["black", "--check", "."]) is True

    def test_allows_whitelisted_npm(self):
        """Test that npm is allowed."""
        validator = CommandValidator()
        assert validator.validate(["npm", "install"]) is True

    def test_allows_flutter_and_dart_tools(self):
        """Flutter/Dart tooling should be allowed for first-class Dart gates."""
        validator = CommandValidator()
        assert validator.validate(["flutter", "test", "--coverage"]) is True
        assert validator.validate(["dart", "format", "."]) is True

    def test_rejects_unknown_executable(self):
        """Test that unknown executables are rejected."""
        validator = CommandValidator()
        with pytest.raises(SecurityError) as exc_info:
            validator.validate(["rm", "-rf", "/"])
        assert "not in whitelist" in str(exc_info.value)

    def test_rejects_empty_command(self):
        """Test that empty commands are rejected."""
        validator = CommandValidator()
        with pytest.raises(SecurityError) as exc_info:
            validator.validate([])
        assert "Empty command" in str(exc_info.value)

    def test_rejects_shell_injection_semicolon(self):
        """Test that semicolon injection is rejected."""
        validator = CommandValidator()
        with pytest.raises(SecurityError) as exc_info:
            validator.validate(["python", "-c", "print('hello'); import os"])
        assert "Dangerous" in str(exc_info.value)

    def test_rejects_shell_injection_pipe(self):
        """Test that pipe injection is rejected."""
        validator = CommandValidator()
        with pytest.raises(SecurityError) as exc_info:
            validator.validate(["python", "script.py", "| cat /etc/passwd"])
        assert "Dangerous" in str(exc_info.value)

    def test_rejects_shell_operator_at_arg_start_without_space(self):
        """Operator at token start should be rejected (e.g. '|cat')."""
        validator = CommandValidator()
        with pytest.raises(SecurityError) as exc_info:
            validator.validate(["python", "script.py", "|cat"])
        assert "Dangerous" in str(exc_info.value)

    def test_rejects_shell_operator_at_arg_end_without_space(self):
        """Operator at token end should be rejected (e.g. 'cat|')."""
        validator = CommandValidator()
        with pytest.raises(SecurityError) as exc_info:
            validator.validate(["python", "script.py", "cat|"])
        assert "Dangerous" in str(exc_info.value)

    def test_rejects_redirect_without_space(self):
        """Redirection operators without spaces should be rejected."""
        validator = CommandValidator()
        with pytest.raises(SecurityError) as exc_info:
            validator.validate(["python", "script.py", "2>/tmp/err"])
        assert "Dangerous" in str(exc_info.value)

    def test_allows_regex_argument_with_pipe_character(self):
        """Regex alternation in a normal arg is not shell injection."""
        validator = CommandValidator()
        assert (
            validator.validate(
                [
                    "black",
                    "--exclude",
                    r"/(venv|\.venv|build|dist|node_modules)/",
                    ".",
                ]
            )
            is True
        )

    def test_rejects_shell_injection_backtick(self):
        """Test that backtick injection is rejected."""
        validator = CommandValidator()
        with pytest.raises(SecurityError) as exc_info:
            validator.validate(["python", "-c", "`rm -rf /`"])
        assert "Dangerous" in str(exc_info.value)

    def test_rejects_command_substitution(self):
        """Test that $() command substitution is rejected."""
        validator = CommandValidator()
        with pytest.raises(SecurityError) as exc_info:
            validator.validate(["python", "-c", "$(whoami)"])
        assert "Dangerous" in str(exc_info.value)

    def test_allows_full_path_to_whitelisted(self):
        """Test that full paths to whitelisted executables work."""
        validator = CommandValidator()
        assert validator.validate(["/usr/bin/python", "-m", "pytest"]) is True

    def test_add_allowed_executable(self):
        """Test adding custom executable to whitelist."""
        validator = CommandValidator()
        validator.add_allowed("custom-tool")
        assert validator.validate(["custom-tool", "--version"]) is True

    def test_is_allowed(self):
        """Test is_allowed check."""
        validator = CommandValidator()
        assert validator.is_allowed("python") is True
        assert validator.is_allowed("malware") is False

    def test_additional_allowed_in_constructor(self):
        """Test providing additional allowed in constructor."""
        validator = CommandValidator(additional_allowed={"my-tool"})
        assert validator.validate(["my-tool", "--help"]) is True

    def test_rejects_non_string_args(self):
        """Test that non-string arguments are rejected."""
        validator = CommandValidator()
        with pytest.raises(SecurityError) as exc_info:
            validator.validate(["python", 123])  # type: ignore
        assert "not a string" in str(exc_info.value)

    def test_rejects_non_list_command(self):
        """Test that non-list commands are rejected."""
        validator = CommandValidator()
        with pytest.raises(SecurityError) as exc_info:
            validator.validate("python -m pytest")  # type: ignore
        assert "must be a list" in str(exc_info.value)

    def test_allows_find_duplicate_strings(self):
        """Test that find-duplicate-strings is whitelisted."""
        validator = CommandValidator()
        assert validator.validate(["find-duplicate-strings", "--help"]) is True


class TestWindowsExecutableNormalization:
    """Windows tool resolution hands back .exe/.cmd/.bat paths.

    The validator must normalize those before whitelist comparison, or
    every resolved tool on Windows gets rejected.
    """

    def test_allows_exe_suffix(self):
        validator = CommandValidator()
        assert validator.validate(["black.exe", "--check", "."]) is True

    def test_allows_exe_suffix_with_full_windows_path(self):
        validator = CommandValidator()
        assert (
            validator.validate([r"C:\repo\.venv\Scripts\python.exe", "-m", "pytest"])
            is True
        )

    def test_allows_cmd_suffix(self):
        validator = CommandValidator()
        assert (
            validator.validate([r"C:\repo\node_modules\.bin\eslint.cmd", "src/"])
            is True
        )

    def test_allows_bat_suffix(self):
        validator = CommandValidator()
        assert validator.validate(["npx.bat", "prettier", "--check"]) is True

    def test_suffix_stripping_is_case_insensitive(self):
        validator = CommandValidator()
        assert validator.validate(["Python.EXE", "-V"]) is True
        assert validator.validate(["NPM.CMD", "install"]) is True

    def test_does_not_strip_non_suffix_dot(self):
        """python3.11 must not become python3."""
        validator = CommandValidator()
        assert validator.validate(["python3.11", "-m", "pytest"]) is True

    def test_versioned_python_with_exe_suffix(self):
        """python3.11.exe → python3.11 → allowed."""
        validator = CommandValidator()
        assert validator.validate(["python3.11.exe", "-m", "pytest"]) is True

    def test_rejects_unknown_exe(self):
        validator = CommandValidator()
        with pytest.raises(SecurityError) as exc_info:
            validator.validate(["evil.exe", "--payload"])
        assert "not in whitelist" in str(exc_info.value)

    def test_rejects_unknown_cmd(self):
        validator = CommandValidator()
        with pytest.raises(SecurityError) as exc_info:
            validator.validate([r"C:\temp\malware.cmd"])
        assert "not in whitelist" in str(exc_info.value)

    def test_only_strips_final_suffix(self):
        """black.exe.txt is not black — do not over-strip."""
        validator = CommandValidator()
        with pytest.raises(SecurityError):
            validator.validate(["black.exe.txt", "."])

    def test_is_allowed_normalizes_windows_paths(self):
        validator = CommandValidator()
        assert validator.is_allowed(r"C:\py\Scripts\black.exe") is True
        assert validator.is_allowed("eslint.cmd") is True
        assert validator.is_allowed("unknown.exe") is False

    def test_add_allowed_normalizes_case(self):
        """Lookup lowercases; insert must too, or mixed-case adds fail."""
        validator = CommandValidator()
        validator.add_allowed("MyTool")
        assert validator.validate(["mytool", "--version"]) is True
        assert validator.validate(["MYTOOL", "--version"]) is True
        assert validator.validate(["MyTool", "--version"]) is True

    def test_add_allowed_normalizes_windows_suffix(self):
        """Adding a .exe name should allow the bare name and vice versa."""
        validator = CommandValidator()
        validator.add_allowed("MyScanner.EXE")
        assert validator.is_allowed("myscanner") is True
        assert validator.is_allowed(r"C:\bin\MyScanner.exe") is True

    def test_additional_allowed_normalizes_case(self):
        """Constructor-supplied entries get the same normalization."""
        validator = CommandValidator(additional_allowed={"CamelTool"})
        assert validator.validate(["cameltool", "arg"]) is True
        assert validator.is_allowed("CAMELTOOL") is True
