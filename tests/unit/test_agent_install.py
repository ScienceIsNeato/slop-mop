"""Tests for ``sm agent install`` command."""

from __future__ import annotations

import argparse

from slopmop.cli.agent import _expand_targets, _templates_for_target, cmd_agent


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
        """all expands to both supported integrations."""
        assert _expand_targets("all") == ["cursor", "claude"]

    def test_templates_for_known_targets(self):
        """Known targets return templates."""
        assert len(_templates_for_target("cursor")) == 1
        assert len(_templates_for_target("claude")) == 1

    def test_templates_for_unknown_target(self):
        """Unknown target returns an empty list."""
        assert _templates_for_target("unknown") == []


class TestCmdAgent:
    """Command-level behavior for installs."""

    def test_install_all_targets(self, tmp_path):
        """Default install writes cursor and claude templates."""
        args = _make_args(tmp_path)

        result = cmd_agent(args)

        assert result == 0
        assert (tmp_path / ".cursor/rules/slopmop-swab.mdc").exists()
        assert (tmp_path / ".claude/commands/sm-swab.md").exists()

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
        assert "Run slop-mop quick validation" in claude_file.read_text(
            encoding="utf-8"
        )

    def test_installed_templates_include_buff_workflow(self, tmp_path):
        """Generated agent templates should mention the post-PR buff rail."""
        args = _make_args(tmp_path)

        result = cmd_agent(args)

        assert result == 0
        cursor_text = (tmp_path / ".cursor/rules/slopmop-swab.mdc").read_text(
            encoding="utf-8"
        )
        claude_text = (tmp_path / ".claude/commands/sm-swab.md").read_text(
            encoding="utf-8"
        )
        assert "sm buff" in cursor_text
        assert "sm buff" in claude_text

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
