"""Parser-specific CLI tests split out from test_sm_cli.py."""

import pytest

import slopmop.cli.parser_builders as parser_builders
from slopmop.sm import create_parser


class TestCreateParser:
    """Tests for create_parser function."""

    def test_creates_parser(self):
        parser = create_parser()
        assert parser is not None
        assert parser.prog == "./sm"

    def test_swab_subcommand(self):
        parser = create_parser()
        args = parser.parse_args(["swab"])
        assert args.verb == "swab"

    def test_scour_subcommand(self):
        parser = create_parser()
        args = parser.parse_args(["scour"])
        assert args.verb == "scour"

    def test_buff_subcommand(self):
        parser = create_parser()
        args = parser.parse_args(["buff"])
        assert args.verb == "buff"

    def test_buff_with_pr_number(self):
        parser = create_parser()
        args = parser.parse_args(["buff", "84"])
        assert args.verb == "buff"
        assert args.pr_or_action == "84"
        assert args.action_args == []

    def test_buff_inspect_parses(self):
        parser = create_parser()
        args = parser.parse_args(["buff", "inspect", "84"])
        assert args.verb == "buff"
        assert args.pr_or_action == "inspect"
        assert args.action_args == ["84"]

    def test_buff_iterate_parses(self):
        parser = create_parser()
        args = parser.parse_args(["buff", "iterate", "84"])
        assert args.verb == "buff"
        assert args.pr_or_action == "iterate"
        assert args.action_args == ["84"]

    def test_buff_finalize_parses(self):
        parser = create_parser()
        args = parser.parse_args(["buff", "finalize", "84", "--push"])
        assert args.verb == "buff"
        assert args.pr_or_action == "finalize"
        assert args.action_args == ["84"]
        assert args.push is True

    def test_buff_status_parses(self):
        parser = create_parser()
        args = parser.parse_args(["buff", "status", "84"])
        assert args.verb == "buff"
        assert args.pr_or_action == "status"
        assert args.action_args == ["84"]

    def test_buff_watch_parses(self):
        parser = create_parser()
        args = parser.parse_args(["buff", "watch", "84", "--interval", "10"])
        assert args.verb == "buff"
        assert args.pr_or_action == "watch"
        assert args.action_args == ["84"]
        assert args.interval == 10

    def test_buff_fail_fast_parses(self):
        parser = create_parser()
        args = parser.parse_args(["buff", "watch", "84", "--fail-fast"])
        assert args.fail_fast is True

    def test_buff_fail_fast_defaults_false(self):
        parser = create_parser()
        args = parser.parse_args(["buff", "watch", "84"])
        assert args.fail_fast is False

    def test_buff_json_and_output_file_flags(self):
        parser = create_parser()
        args = parser.parse_args(
            ["buff", "84", "--json", "--output-file", "triage.json"]
        )
        assert args.verb == "buff"
        assert args.pr_or_action == "84"
        assert args.action_args == []
        assert args.json_output is True
        assert args.output_file == "triage.json"

    def test_refit_start_parses(self):
        parser = create_parser()
        args = parser.parse_args(["refit", "--start"])
        assert args.verb == "refit"
        assert args.start is True
        assert args.iterate is False

    def test_refit_iterate_parses(self):
        parser = create_parser()
        args = parser.parse_args(["refit", "--iterate"])
        assert args.verb == "refit"
        assert args.start is False
        assert args.iterate is True

    def test_refit_finish_parses(self):
        parser = create_parser()
        args = parser.parse_args(["refit", "--finish"])
        assert args.verb == "refit"
        assert args.finish is True

    def test_refit_skip_parses_without_reason(self):
        parser = create_parser()
        args = parser.parse_args(["refit", "--skip"])
        assert args.verb == "refit"
        assert args.skip == "manual skip"
        assert args.iterate is False

    def test_refit_skip_parses_with_reason(self):
        parser = create_parser()
        args = parser.parse_args(["refit", "--skip", "tool unavailable on CI"])
        assert args.skip == "tool unavailable on CI"

    def test_refit_skip_is_mutually_exclusive_with_iterate(self):
        parser = create_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["refit", "--iterate", "--skip"])

    def test_refit_json_and_output_file_flags(self):
        parser = create_parser()
        args = parser.parse_args(
            ["refit", "--start", "--json", "--output-file", "refit.json"]
        )
        assert args.verb == "refit"
        assert args.start is True
        assert args.json_output is True
        assert args.output_file == "refit.json"

    def test_refit_requires_exactly_one_mode(self):
        parser = create_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["refit"])

    def test_refit_modes_are_mutually_exclusive(self):
        parser = create_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["refit", "--start", "--iterate"])

    def test_swab_with_quality_gates(self):
        parser = create_parser()
        args = parser.parse_args(
            [
                "swab",
                "-g",
                "overconfidence:untested-code.py",
                "overconfidence:coverage-gaps.py",
            ]
        )
        assert args.verb == "swab"
        assert args.quality_gates == [
            "overconfidence:untested-code.py",
            "overconfidence:coverage-gaps.py",
        ]

    def test_swabbing_time_flag(self):
        parser = create_parser()
        args = parser.parse_args(["swab", "--swabbing-time", "30"])
        assert args.verb == "swab"
        assert args.swabbing_time == 30

    def test_swabbing_time_default_none(self):
        parser = create_parser()
        args = parser.parse_args(["scour"])
        assert args.swabbing_time is None

    def test_swabbing_time_zero_disables(self):
        parser = create_parser()
        args = parser.parse_args(["swab", "--swabbing-time", "0"])
        assert args.swabbing_time == 0

    def test_no_cache_flag_default_false(self):
        parser = create_parser()
        args = parser.parse_args(["swab"])
        assert args.no_cache is False

    def test_no_cache_flag_set(self):
        parser = create_parser()
        args = parser.parse_args(["swab", "--no-cache"])
        assert args.no_cache is True

    def test_no_cache_flag_on_scour(self):
        parser = create_parser()
        args = parser.parse_args(["scour", "--no-cache"])
        assert args.no_cache is True

    def test_ignore_baseline_failures_flag_on_swab(self):
        parser = create_parser()
        args = parser.parse_args(["swab", "--ignore-baseline-failures"])
        assert args.ignore_baseline_failures is True

    def test_ignore_baseline_failures_flag_on_scour(self):
        parser = create_parser()
        args = parser.parse_args(["scour", "--ignore-baseline-failures"])
        assert args.ignore_baseline_failures is True

    def test_status_generate_baseline_snapshot_flag(self):
        parser = create_parser()
        args = parser.parse_args(["status", "--generate-baseline-snapshot"])
        assert args.generate_baseline_snapshot is True

    def test_config_subcommand(self):
        parser = create_parser()
        args = parser.parse_args(["config", "--show"])
        assert args.verb == "config"
        assert args.show is True

    def test_config_enable(self):
        parser = create_parser()
        args = parser.parse_args(
            ["config", "--enable", "myopia:vulnerability-blindness.py"]
        )
        assert args.verb == "config"
        assert args.enable == "myopia:vulnerability-blindness.py"

    def test_config_current_pr_number(self):
        parser = create_parser()
        args = parser.parse_args(["config", "--current-pr-number", "85"])
        assert args.verb == "config"
        assert args.current_pr_number == 85

    def test_config_clear_current_pr(self):
        parser = create_parser()
        args = parser.parse_args(["config", "--clear-current-pr"])
        assert args.verb == "config"
        assert args.clear_current_pr is True

    def test_help_subcommand(self):
        parser = create_parser()
        args = parser.parse_args(["help", "laziness:sloppy-formatting.py"])
        assert args.verb == "help"
        assert args.gate == "laziness:sloppy-formatting.py"

    def test_init_subcommand(self):
        parser = create_parser()
        args = parser.parse_args(["init", "--non-interactive"])
        assert args.verb == "init"
        assert args.non_interactive is True

    def test_commit_hooks_status(self):
        parser = create_parser()
        args = parser.parse_args(["commit-hooks", "status"])
        assert args.verb == "commit-hooks"
        assert args.hooks_action == "status"

    def test_commit_hooks_install(self):
        parser = create_parser()
        args = parser.parse_args(["commit-hooks", "install", "swab"])
        assert args.verb == "commit-hooks"
        assert args.hooks_action == "install"
        assert args.hook_verb == "swab"

    def test_commit_hooks_uninstall(self):
        parser = create_parser()
        args = parser.parse_args(["commit-hooks", "uninstall"])
        assert args.verb == "commit-hooks"
        assert args.hooks_action == "uninstall"

    def test_agent_install_parses(self):
        parser = create_parser()
        args = parser.parse_args(
            ["agent", "install", "--target", "cursor", "--project-root", "."]
        )
        assert args.verb == "agent"
        assert args.agent_action == "install"
        assert args.target == "cursor"
        assert args.project_root == "."

    def test_agent_install_parses_copilot_target(self):
        parser = create_parser()
        args = parser.parse_args(["agent", "install", "--target", "copilot"])
        assert args.verb == "agent"
        assert args.agent_action == "install"
        assert args.target == "copilot"

    def test_agent_install_help_shows_preview_install_paths(self, capsys):
        parser = create_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["agent", "install", "--help"])

        out = capsys.readouterr().out
        assert ".slopmop/tmp/.github/copilot-instructions.md" in out
        assert ".slopmop/tmp/.copilot/skills/slopmop/SKILL.md" in out

    def test_agent_install_help_tolerates_missing_template_preview(
        self, monkeypatch, capsys
    ):
        def _preview_paths(target):
            if target == "antigravity":
                raise FileNotFoundError("Template directory not found: antigravity")
            return [f".slopmop/tmp/{target}"]

        monkeypatch.setattr(parser_builders, "preview_install_paths", _preview_paths)

        parser = create_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["agent", "install", "--help"])

        out = capsys.readouterr().out
        assert "antigravity:" in out
        assert "unavailable (Template directory not found: antigravity)" in out

    def test_doctor_subcommand(self):
        parser = create_parser()
        args = parser.parse_args(["doctor"])
        assert args.verb == "doctor"
        assert args.checks == []
        assert args.list_checks is False
        assert args.fix is False
        assert args.yes is False
        assert args.json_output is None  # tri-state: auto-detect

    def test_doctor_with_check_names(self):
        parser = create_parser()
        args = parser.parse_args(["doctor", "state.lock", "sm_env.pip_check"])
        assert args.checks == ["state.lock", "sm_env.pip_check"]

    def test_doctor_with_glob_pattern(self):
        parser = create_parser()
        args = parser.parse_args(["doctor", "state.*"])
        assert args.checks == ["state.*"]

    def test_doctor_list_checks_flag(self):
        parser = create_parser()
        args = parser.parse_args(["doctor", "--list-checks"])
        assert args.list_checks is True

    def test_doctor_fix_flag(self):
        parser = create_parser()
        args = parser.parse_args(["doctor", "--fix"])
        assert args.fix is True

    def test_doctor_fix_with_yes_shorthand(self):
        parser = create_parser()
        args = parser.parse_args(["doctor", "--fix", "-y"])
        assert args.fix is True
        assert args.yes is True

    def test_doctor_json_flag_explicit(self):
        parser = create_parser()
        args = parser.parse_args(["doctor", "--json"])
        assert args.json_output is True

    def test_doctor_no_json_flag_explicit(self):
        parser = create_parser()
        args = parser.parse_args(["doctor", "--no-json"])
        assert args.json_output is False

    def test_doctor_project_root(self):
        parser = create_parser()
        args = parser.parse_args(["doctor", "--project-root", "/tmp/elsewhere"])
        assert args.project_root == "/tmp/elsewhere"

    def test_doctor_fix_with_check_subset(self):
        parser = create_parser()
        args = parser.parse_args(["doctor", "--fix", "--yes", "state.lock"])
        assert args.fix is True
        assert args.yes is True
        assert args.checks == ["state.lock"]
