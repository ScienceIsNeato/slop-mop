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
