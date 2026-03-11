"""Tests for ``sm agent install`` command."""

from __future__ import annotations

import argparse

from slopmop.cli.agent import (
    ALL_TARGETS,
    _expand_targets,
    _templates_for_target,
    cmd_agent,
)


def _make_args(tmp_path, **overrides) -> argparse.Namespace:
    """Build argparse args namespace for cmd_agent."""
    data = {
        "agent_action": "install",
        "target": "all",
        "project_root": str(tmp_path),
        "force": False,
    }
    data.update(overrides)
    return argparse.Namespace(**data)


class TestAgentHelpers:
    """Low-level helper behavior."""

    def test_expand_targets_all(self):
        """all expands to every supported integration."""
        assert _expand_targets("all") == ALL_TARGETS

    def test_templates_for_known_targets(self):
        """Known targets return at least one template each."""
        for target in ALL_TARGETS:
            templates = _templates_for_target(target)
            assert len(templates) >= 1, f"{target} returned no templates"

    def test_claude_produces_commands_and_skill(self):
        """Claude target installs swab, scour, buff commands and SKILL.md."""
        templates = _templates_for_target("claude")
        paths = [t.relative_path for t in templates]
        assert ".claude/commands/sm-swab.md" in paths
        assert ".claude/commands/sm-scour.md" in paths
        assert ".claude/commands/sm-buff.md" in paths
        assert ".claude/skills/slopmop/SKILL.md" in paths

    def test_aider_produces_two_files(self):
        """Aider target installs .aider.conf.yml and CONVENTIONS.md."""
        templates = _templates_for_target("aider")
        paths = [t.relative_path for t in templates]
        assert ".aider.conf.yml" in paths
        assert "CONVENTIONS.md" in paths

    def test_templates_for_unknown_target(self):
        """Unknown target returns an empty list."""
        assert _templates_for_target("unknown") == []


class TestCmdAgent:
    """Command-level behavior for installs."""

    def test_install_all_targets(self, tmp_path):
        """Default install writes all supported templates."""
        args = _make_args(tmp_path)

        result = cmd_agent(args)

        assert result == 0
        assert (tmp_path / ".cursor/rules/slopmop-swab.mdc").exists()
        assert (tmp_path / ".claude/commands/sm-swab.md").exists()
        assert (tmp_path / ".claude/commands/sm-scour.md").exists()
        assert (tmp_path / ".claude/commands/sm-buff.md").exists()
        assert (tmp_path / ".claude/skills/slopmop/SKILL.md").exists()
        assert (tmp_path / ".github/copilot-instructions.md").exists()
        assert (tmp_path / ".windsurf/rules/slopmop.md").exists()
        assert (tmp_path / ".clinerules/slopmop.md").exists()
        assert (tmp_path / ".roo/rules/01-slopmop.md").exists()
        assert (tmp_path / ".aider.conf.yml").exists()
        assert (tmp_path / "CONVENTIONS.md").exists()

    def test_install_skip_existing_without_force(self, tmp_path, capsys):
        """Existing files are skipped when --force is not set."""
        cursor_file = tmp_path / ".cursor/rules/slopmop-swab.mdc"
        cursor_file.parent.mkdir(parents=True, exist_ok=True)
        cursor_file.write_text("custom-content\n", encoding="utf-8")

        args = _make_args(tmp_path, target="cursor", force=False)
        result = cmd_agent(args)

        assert result == 0
        assert cursor_file.read_text(encoding="utf-8") == "custom-content\n"
        out = capsys.readouterr().out
        assert "Skipped (already exists" in out

    def test_install_overwrites_with_force(self, tmp_path):
        """--force overwrites files managed by install command."""
        claude_file = tmp_path / ".claude/commands/sm-swab.md"
        claude_file.parent.mkdir(parents=True, exist_ok=True)
        claude_file.write_text("old\n", encoding="utf-8")

        args = _make_args(tmp_path, target="claude", force=True)
        result = cmd_agent(args)

        assert result == 0
        assert "iterative development loop" in claude_file.read_text(encoding="utf-8")

    def test_installed_templates_include_skill_description(self, tmp_path):
        """Generated templates should include the skill description with buff workflow."""
        args = _make_args(tmp_path)

        result = cmd_agent(args)

        assert result == 0

        # Every target should mention sm buff somewhere in its templates
        targets_with_buff = {
            "cursor": ".cursor/rules/slopmop-swab.mdc",
            "claude-buff": ".claude/commands/sm-buff.md",
            "copilot": ".github/copilot-instructions.md",
            "windsurf": ".windsurf/rules/slopmop.md",
            "cline": ".clinerules/slopmop.md",
            "roo": ".roo/rules/01-slopmop.md",
            "aider": "CONVENTIONS.md",
        }
        for label, path in targets_with_buff.items():
            text = (tmp_path / path).read_text(encoding="utf-8")
            assert "sm buff" in text, f"{label} ({path}) missing 'sm buff'"

    def test_skill_description_in_templates(self, tmp_path):
        """Templates describe sm as a gradient descent development protocol."""
        args = _make_args(tmp_path)
        cmd_agent(args)

        cursor_text = (tmp_path / ".cursor/rules/slopmop-swab.mdc").read_text(
            encoding="utf-8"
        )
        assert "development protocol" in cursor_text
        assert "gradient descent" in cursor_text
        assert "sm swab" in cursor_text
        assert "sm scour" in cursor_text

    def test_project_root_missing(self, tmp_path):
        """Returns usage error when project root does not exist."""
        missing = tmp_path / "missing"
        args = _make_args(tmp_path, project_root=str(missing))

        result = cmd_agent(args)

        assert result == 2

    def test_unknown_action_prints_usage(self, tmp_path, capsys):
        """Unknown action returns usage error."""
        args = _make_args(tmp_path, agent_action="status")

        result = cmd_agent(args)

        assert result == 2
        out = capsys.readouterr().out
        assert "Usage: sm agent install" in out
