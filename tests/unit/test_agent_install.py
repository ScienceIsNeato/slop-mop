"""Tests for ``sm agent install`` command."""

from __future__ import annotations

import argparse

import pytest

from slopmop.agent_install.loader import _load_shared_core, load_assets
from slopmop.agent_install.registry import ALL_KEYS, TARGETS, cli_choices, expand_target
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


# ---------------------------------------------------------------------------
# Registry tests
# ---------------------------------------------------------------------------


class TestRegistry:
    """Target registry and alias behavior."""

    def test_all_keys_matches_targets(self):
        """ALL_KEYS tuple is consistent with TARGETS dict."""
        assert set(ALL_KEYS) == set(TARGETS.keys())

    def test_expand_single_target(self):
        """Single target returns a one-element list."""
        assert expand_target("claude") == ["claude"]

    def test_expand_all_alias(self):
        """'all' alias expands to every target."""
        result = expand_target("all")
        assert set(result) == set(ALL_KEYS)

    def test_expand_unknown_raises(self):
        """Unknown target raises ValueError."""
        with pytest.raises(ValueError, match="Unknown"):
            expand_target("nonexistent")

    def test_cli_choices_includes_all(self):
        """cli_choices includes 'all' plus every target key."""
        choices = cli_choices()
        assert "all" in choices
        for key in ALL_KEYS:
            assert key in choices


# ---------------------------------------------------------------------------
# Loader / template substitution tests
# ---------------------------------------------------------------------------


class TestLoader:
    """Template loading and {{CORE}} substitution."""

    def test_shared_core_loads(self):
        """_shared/core.md loads and contains the key phrases."""
        core = _load_shared_core()
        text = core.decode("utf-8")
        assert "speed multiplier" in text
        assert "sm swab" in text
        assert "sm scour" in text
        assert "sm buff" in text

    def test_shared_core_has_no_placeholder(self):
        """core.md itself should not contain {{CORE}}."""
        core = _load_shared_core()
        assert b"{{CORE}}" not in core

    def test_no_leftover_placeholders_in_any_target(self):
        """After loading, no template content should contain {{CORE}}."""
        for key, target in TARGETS.items():
            assets = load_assets(target.template_dir)
            for asset in assets:
                assert b"{{CORE}}" not in asset.content, (
                    f"{key}/{asset.destination_relpath} has unsubstituted "
                    "{{CORE}} placeholder"
                )

    def test_core_content_present_in_wrapper_targets(self):
        """Targets that use {{CORE}} should contain the shared body."""
        core_text = _load_shared_core().decode("utf-8").strip()
        # These targets use {{CORE}} wrappers
        wrapper_targets = ["cursor", "copilot", "windsurf", "cline", "roo", "aider"]
        for key in wrapper_targets:
            assets = load_assets(TARGETS[key].template_dir)
            # At least one asset in each target should contain the core body
            texts = [a.content.decode("utf-8") for a in assets]
            combined = "\n".join(texts)
            assert "speed multiplier" in combined, f"{key} missing shared core content"

    def test_claude_templates_are_independent(self):
        """Claude templates don't use {{CORE}} — they have custom content."""
        assets = load_assets(TARGETS["claude"].template_dir)
        for asset in assets:
            text = asset.content.decode("utf-8")
            if asset.destination_relpath.endswith("SKILL.md"):
                assert "speed multiplier" in text.lower()
            else:
                assert "sm" in text.lower()

    def test_load_nonexistent_template_dir(self):
        """Loading a nonexistent template dir raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            load_assets("does_not_exist")

    def test_cursor_preserves_frontmatter(self):
        """Cursor templates retain their YAML frontmatter after substitution."""
        assets = load_assets(TARGETS["cursor"].template_dir)
        assert len(assets) == 3
        for asset in assets:
            text = asset.content.decode("utf-8")
            assert text.startswith("---\n")
            assert "alwaysApply: true" in text

    def test_windsurf_preserves_frontmatter(self):
        """Windsurf template retains its trigger frontmatter."""
        assets = load_assets(TARGETS["windsurf"].template_dir)
        assert len(assets) == 1
        text = assets[0].content.decode("utf-8")
        assert "trigger: always_on" in text


# ---------------------------------------------------------------------------
# Claude SKILL.md structure tests
# ---------------------------------------------------------------------------


class TestClaudeSkill:
    """Claude SKILL.md has the structure Claude Code expects."""

    def test_skill_md_has_yaml_frontmatter(self):
        """SKILL.md must have YAML frontmatter with name and description."""
        assets = load_assets(TARGETS["claude"].template_dir)
        skill_assets = [a for a in assets if a.destination_relpath.endswith("SKILL.md")]
        assert len(skill_assets) == 1
        text = skill_assets[0].content.decode("utf-8")
        assert text.startswith("---\n")
        assert "name: slop-mop" in text
        assert "description:" in text

    def test_skill_md_description_is_accurate(self):
        """SKILL.md description should mention speed multiplier, not quality gates."""
        assets = load_assets(TARGETS["claude"].template_dir)
        skill = next(a for a in assets if a.destination_relpath.endswith("SKILL.md"))
        text = skill.content.decode("utf-8")
        assert "speed multiplier" in text.lower() or "Speed multiplier" in text
        assert "quality" not in text.lower()

    def test_skill_md_path(self):
        """SKILL.md installs to .claude/skills/slopmop/SKILL.md."""
        assets = load_assets(TARGETS["claude"].template_dir)
        paths = [a.destination_relpath for a in assets]
        assert ".claude/skills/slopmop/SKILL.md" in paths

    def test_claude_command_files_reference_verbs(self):
        """Each Claude command file references its respective sm verb."""
        assets = load_assets(TARGETS["claude"].template_dir)
        commands = {
            a.destination_relpath: a.content.decode("utf-8")
            for a in assets
            if "/commands/" in a.destination_relpath
        }
        assert len(commands) == 3
        for path, text in commands.items():
            if "swab" in path:
                assert "sm swab" in text
            elif "scour" in path:
                assert "sm scour" in text
            elif "buff" in path:
                assert "sm buff" in text


# ---------------------------------------------------------------------------
# CLI helper tests
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# End-to-end install tests
# ---------------------------------------------------------------------------


class TestCmdAgent:
    """Command-level behavior for installs."""

    def test_install_all_targets(self, tmp_path):
        """Default install writes all supported templates."""
        args = _make_args(tmp_path)

        result = cmd_agent(args)

        assert result == 0
        assert (tmp_path / ".cursor/rules/slopmop-swab.mdc").exists()
        assert (tmp_path / ".cursor/rules/slopmop-scour.mdc").exists()
        assert (tmp_path / ".cursor/rules/slopmop-buff.mdc").exists()
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

    def test_installed_templates_include_buff(self, tmp_path):
        """Every target mentions sm buff somewhere in its templates."""
        args = _make_args(tmp_path)

        result = cmd_agent(args)

        assert result == 0

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

    def test_installed_content_has_correct_framing(self, tmp_path):
        """Installed files describe sm as a speed multiplier, not quality gates."""
        args = _make_args(tmp_path)
        cmd_agent(args)

        # Check a wrapper target
        cursor_text = (tmp_path / ".cursor/rules/slopmop-swab.mdc").read_text(
            encoding="utf-8"
        )
        assert "speed multiplier" in cursor_text
        assert "{{CORE}}" not in cursor_text

        # Check Claude SKILL.md
        skill_text = (tmp_path / ".claude/skills/slopmop/SKILL.md").read_text(
            encoding="utf-8"
        )
        assert "quality" not in skill_text.lower()

    def test_core_substitution_produces_identical_body(self, tmp_path):
        """All targets using {{CORE}} get identical shared content."""
        args = _make_args(tmp_path)
        cmd_agent(args)

        # Cline has no wrapper — it IS the pure core content
        cline = (tmp_path / ".clinerules/slopmop.md").read_text(encoding="utf-8")
        # Copilot has a header
        copilot = (tmp_path / ".github/copilot-instructions.md").read_text(
            encoding="utf-8"
        )
        # The core table should be in both
        assert "| `sm swab`" in copilot
        assert "| `sm swab`" in cline
        # The core body of cline should appear verbatim inside copilot
        # (copilot = header + core)
        core_body = cline.strip()
        assert core_body in copilot

    def test_install_single_target(self, tmp_path):
        """Installing a single target only writes that target's files."""
        args = _make_args(tmp_path, target="copilot")
        result = cmd_agent(args)

        assert result == 0
        assert (tmp_path / ".github/copilot-instructions.md").exists()
        # Other targets should not be present
        assert not (tmp_path / ".cursor/rules/slopmop-swab.mdc").exists()
        assert not (tmp_path / ".claude/commands/sm-swab.md").exists()

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
