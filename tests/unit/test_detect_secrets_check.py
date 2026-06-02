"""Tests for SecurityLocalCheck._run_detect_secrets method."""

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from slopmop.checks.security import SecurityLocalCheck


class TestRunDetectSecrets:
    """Tests for _run_detect_secrets method."""

    def test_detect_secrets_uses_post_filter_not_exclude_files_arg(self):
        """Exclude handling should avoid shell-sensitive regex arguments."""
        check = SecurityLocalCheck({})
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.output = json.dumps({"results": {}})

        with patch.object(check, "_run_command", return_value=mock_result) as mock_run:
            check._run_detect_secrets("/tmp/project")

        call_args = mock_run.call_args[0][0]
        assert "--exclude-files" not in call_args

    def test_detect_secrets_path_exclude_filters_tests_dir(self):
        """Configured exclude dirs should be honored during result parsing."""
        check = SecurityLocalCheck({})
        assert check._is_path_excluded_for_detect_secrets("server/tests/test_auth.py")
        assert not check._is_path_excluded_for_detect_secrets("server/app/auth.py")

    def test_scan_paths_prune_excluded_top_level_dirs(self, tmp_path):
        """Helper drops venv/node_modules/dot-dirs but keeps real source.

        Regression for barnacle #244: detect-secrets must not descend into
        large vendored/venv directories — they cause the 60s-timeout flake.
        """
        (tmp_path / "src").mkdir()
        (tmp_path / "venv").mkdir()
        (tmp_path / "node_modules").mkdir()
        (tmp_path / ".git").mkdir()
        (tmp_path / "config.yml").write_text("name: ci\n")

        check = SecurityLocalCheck({})
        paths = check._detect_secrets_scan_paths(str(tmp_path))

        assert "src" in paths
        assert "config.yml" in paths
        assert "venv" not in paths
        assert "node_modules" not in paths
        assert ".git" not in paths

    def test_scan_paths_empty_when_root_unlistable(self):
        """Unlistable root falls back to whole-tree scan (no path args)."""
        check = SecurityLocalCheck({})
        assert check._detect_secrets_scan_paths("/nonexistent/path/xyz") == []

    def test_detect_secrets_scopes_walk_to_unexcluded_paths(self, tmp_path):
        """_run_detect_secrets passes scoped paths so the walk is pruned.

        The big vendored dirs must never reach the scan argv; the real source
        dirs must. This is what takes the scan from ~49s to ~1.7s (#244).
        """
        (tmp_path / "src").mkdir()
        (tmp_path / "venv").mkdir()
        (tmp_path / "node_modules").mkdir()
        (tmp_path / "config.yml").write_text("name: ci\n")

        check = SecurityLocalCheck({})
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.output = json.dumps({"results": {}})

        with patch.object(check, "_run_command", return_value=mock_result) as mock_run:
            check._run_detect_secrets(str(tmp_path))

        argv = mock_run.call_args[0][0]
        assert "scan" in argv
        assert "src" in argv
        assert "config.yml" in argv
        # The expensive vendored dirs must be pruned before the walk.
        assert "venv" not in argv
        assert "node_modules" not in argv

    def test_detect_secrets_no_findings(self, tmp_path):
        """Test _run_detect_secrets with no secrets found."""
        check = SecurityLocalCheck({})
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.output = json.dumps({"results": {}})

        with patch.object(check, "_run_command", return_value=mock_result):
            result = check._run_detect_secrets(str(tmp_path))

        assert result.name == "detect-secrets"
        assert result.passed is True
        assert "No secrets" in result.findings

    def test_detect_secrets_module_missing_is_not_a_finding(self, tmp_path):
        """A scanner that can't import is a tooling failure, not SLOP.

        Regression for the barnacle where ``No module named detect_secrets``
        was reported as a security finding (SLOP DETECTED) instead of a
        graceful skip — telling users they had a leaked secret when they
        actually had a broken install.
        """
        check = SecurityLocalCheck({})
        mock_result = MagicMock()
        mock_result.success = False
        mock_result.output = "/path/to/python: No module named detect_secrets\n"  # pragma: allowlist secret

        with patch.object(check, "_run_command", return_value=mock_result):
            result = check._run_detect_secrets(str(tmp_path))

        assert result.name == "detect-secrets"
        # Not a failure — it never ran, so it cannot be a security finding.
        assert result.passed is True
        assert result.warned is True
        assert "could not run" in result.findings

    def test_detect_secrets_real_scan_failure_still_fails(self, tmp_path):
        """A genuine scan failure (not a startup error) is still reported."""
        check = SecurityLocalCheck({})
        mock_result = MagicMock()
        mock_result.success = False
        mock_result.output = "detect-secrets: error: unrecognized arguments: --bogus"

        with patch.object(check, "_run_command", return_value=mock_result):
            result = check._run_detect_secrets(str(tmp_path))

        assert result.name == "detect-secrets"
        assert result.passed is False

    def test_detect_secrets_with_findings(self, tmp_path):
        """Test _run_detect_secrets with secrets found."""
        check = SecurityLocalCheck({})
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.output = json.dumps(
            {
                "results": {
                    "config.py": [
                        {
                            "type": "Secret Keyword",
                            "line_number": 5,
                        }  # pragma: allowlist secret
                    ]
                }
            }
        )

        with patch.object(check, "_run_command", return_value=mock_result):
            result = check._run_detect_secrets(str(tmp_path))

        assert result.passed is False
        assert "config.py" in result.findings
        assert "Secret Keyword" in result.findings

    def test_detect_secrets_ignores_constants(self, tmp_path):
        """Test _run_detect_secrets ignores constants.py."""
        check = SecurityLocalCheck({})
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.output = json.dumps(
            {"results": {"constants.py": [{"type": "High Entropy String"}]}}
        )

        with patch.object(check, "_run_command", return_value=mock_result):
            result = check._run_detect_secrets(str(tmp_path))

        assert result.passed is True  # constants.py is ignored

    def test_detect_secrets_ignores_known_generated_and_placeholder_noise(
        self, tmp_path
    ):
        """Generated metadata and placeholder defaults should be filtered."""
        check = SecurityLocalCheck({})
        app_dir = tmp_path / "app"
        app_dir.mkdir()
        (app_dir / "__init__.py").write_text(
            'secret_key = app.config.get("SECRET_KEY")\n'  # pragma: allowlist secret
            'if not secret_key or secret_key == "dev-secret-change-me":\n'  # pragma: allowlist secret
            'jwt_secret = "dev-jwt-secret"\n'  # pragma: allowlist secret
        )
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.output = json.dumps(
            {
                "results": {
                    "client/.metadata": [
                        {"type": "Hex High Entropy String", "line_number": 7}
                    ],
                    "server/.env.example": [
                        {"type": "Basic Auth Credentials", "line_number": 3}
                    ],
                    "app/__init__.py": [
                        {
                            "type": "Secret Keyword",
                            "line_number": 1,
                        },  # pragma: allowlist secret
                        {
                            "type": "Secret Keyword",
                            "line_number": 2,
                        },  # pragma: allowlist secret
                        {
                            "type": "Secret Keyword",
                            "line_number": 3,
                        },  # pragma: allowlist secret
                    ],
                    "app/config.py": [
                        {
                            "type": "Secret Keyword",
                            "line_number": 10,
                        }  # pragma: allowlist secret
                    ],
                }
            }
        )

        with patch.object(check, "_run_command", return_value=mock_result):
            result = check._run_detect_secrets(str(tmp_path))

        assert result.passed is False
        assert "app/config.py" in result.findings
        assert "client/.metadata" not in result.findings
        assert "server/.env.example" not in result.findings
        assert "app/__init__.py" not in result.findings

    def test_detect_secrets_ignores_paths_from_exclude_dirs(self, tmp_path):
        """Findings in excluded dirs should not fail the gate."""
        check = SecurityLocalCheck({})
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.output = json.dumps(
            {
                "results": {
                    "server/tests/test_auth.py": [
                        {
                            "type": "Secret Keyword",
                            "line_number": 3,
                        }  # pragma: allowlist secret
                    ]
                }
            }
        )

        with patch.object(check, "_run_command", return_value=mock_result):
            result = check._run_detect_secrets(str(tmp_path))

        assert result.passed is True

    def test_detect_secrets_ignores_root_flutter_ephemeral_paths(self, tmp_path):
        """Root-level Flutter iOS ephemeral artifacts should be filtered."""
        check = SecurityLocalCheck({})
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.output = json.dumps(
            {
                "results": {
                    "ios/Flutter/ephemeral/generated.xcconfig": [
                        {
                            "type": "Secret Keyword",
                            "line_number": 1,
                        }  # pragma: allowlist secret
                    ]
                }
            }
        )

        with patch.object(check, "_run_command", return_value=mock_result):
            result = check._run_detect_secrets(str(tmp_path))

        assert result.passed is True

    def test_detect_secrets_does_not_filter_latest_as_test_marker(self, tmp_path):
        """Substring like 'latest' should not be treated as test placeholder noise."""
        check = SecurityLocalCheck({})
        app_dir = tmp_path / "app"
        app_dir.mkdir()
        (app_dir / "config.py").write_text(
            'SECRET_KEY = "latest_production_key_abc123"\n'  # pragma: allowlist secret
        )
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.output = json.dumps(
            {
                "results": {
                    "app/config.py": [
                        {
                            "type": "Secret Keyword",
                            "line_number": 1,
                        }  # pragma: allowlist secret
                    ]
                }
            }
        )

        with patch.object(check, "_run_command", return_value=mock_result):
            result = check._run_detect_secrets(str(tmp_path))

        assert result.passed is False
        assert "app/config.py" in result.findings

    def test_detect_secrets_ignores_git_sha_fields(self, tmp_path):
        """Manifest-style git SHA references should not be treated as secrets."""
        check = SecurityLocalCheck({})
        scenarios_dir = tmp_path / "scenarios"
        scenarios_dir.mkdir()
        manifest = scenarios_dir / "happy-path-small.json"
        manifest.write_text(
            "\n".join(
                [
                    '{"fixture_base_sha": "f6049f7840ea4be9de6db24a9813c1a8212e38c3"}',
                    '{"from_sha": "cc96da5f7c045a5b8652ce00b6ee074201673012"}',
                    '{"to_sha": "742a795a416749884426cf98dc4c694d1b1fb68e"}',
                ]
            )
            + "\n"
        )
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.output = json.dumps(
            {
                "results": {
                    "scenarios/happy-path-small.json": [
                        {"type": "Hex High Entropy String", "line_number": 1},
                        {"type": "Hex High Entropy String", "line_number": 2},
                        {"type": "Hex High Entropy String", "line_number": 3},
                    ]
                }
            }
        )

        with patch.object(check, "_run_command", return_value=mock_result):
            result = check._run_detect_secrets(str(tmp_path))

        assert result.passed is True

    def test_detect_secrets_ignores_is_placeholder_sha_assertions(self, tmp_path):
        """Helper assertions about SHAs should not trip detect-secrets."""
        check = SecurityLocalCheck({})
        helpers = tmp_path / "helpers.py"
        helpers.write_text(
            'assert not is_placeholder_sha("abcdef1234567890abcdef1234567890abcdef12")\n'
        )
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.output = json.dumps(
            {
                "results": {
                    "helpers.py": [
                        {"type": "Hex High Entropy String", "line_number": 1}
                    ]
                }
            }
        )

        with patch.object(check, "_run_command", return_value=mock_result):
            result = check._run_detect_secrets(str(tmp_path))

        assert result.passed is True

    def test_detect_secrets_ignores_git_sha_context_from_neighbor_lines(self, tmp_path):
        """Git SHA context can come from surrounding lines, not just the hit line."""
        check = SecurityLocalCheck({})
        helpers = tmp_path / "helpers.py"
        helpers.write_text(
            "\n".join(
                [
                    "branch = make_run_branch_name(",
                    '    "happy-path-small",',
                    '    "abcdef1234567890",',
                    '    "run01",',
                    ")",
                    'if args[0] == "rev-parse":',
                    '    return (0, "abc12345def", "")',
                    "head = _current_head(project_root)",
                    'Mock(return_value="deadbeef1234")',
                ]
            )
            + "\n"
        )
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.output = json.dumps(
            {
                "results": {
                    "helpers.py": [
                        {"type": "Hex High Entropy String", "line_number": 3},
                        {"type": "Hex High Entropy String", "line_number": 7},
                        {"type": "Hex High Entropy String", "line_number": 9},
                    ]
                }
            }
        )

        with patch.object(check, "_run_command", return_value=mock_result):
            result = check._run_detect_secrets(str(tmp_path))

        assert result.passed is True

    def test_safe_read_line_uses_cache_for_same_file(self, tmp_path):
        """Line lookup cache should avoid repeated file reads per path."""
        check = SecurityLocalCheck({})
        app_dir = tmp_path / "app"
        app_dir.mkdir()
        (app_dir / "config.py").write_text("line1\nline2\n")

        read_calls = {"count": 0}
        original_read_text = Path.read_text

        def _counting_read_text(self, *args, **kwargs):
            read_calls["count"] += 1
            return original_read_text(self, *args, **kwargs)

        with patch("pathlib.Path.read_text", new=_counting_read_text):
            cache: dict[str, list[str]] = {}
            first = check._safe_read_line(str(tmp_path), "app/config.py", 1, cache)
            second = check._safe_read_line(str(tmp_path), "app/config.py", 2, cache)

        assert first == "line1"
        assert second == "line2"
        assert read_calls["count"] == 1

    def test_detect_secrets_json_error(self, tmp_path):
        """Test _run_detect_secrets handles JSON errors."""
        check = SecurityLocalCheck({})
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.output = "not json"

        with patch.object(check, "_run_command", return_value=mock_result):
            result = check._run_detect_secrets(str(tmp_path))

        assert result.passed is True  # Scan completed

    def test_detect_secrets_failure(self, tmp_path):
        """Test _run_detect_secrets with command failure."""
        check = SecurityLocalCheck({})
        mock_result = MagicMock()
        mock_result.success = False
        mock_result.output = "Error running scan"

        with patch.object(check, "_run_command", return_value=mock_result):
            result = check._run_detect_secrets(str(tmp_path))

        assert result.passed is False

    def test_detect_secrets_never_passes_real_baseline_flag(self, tmp_path):
        """detect-secrets scan must NOT receive the real .secrets.baseline as --baseline.

        Passing the real baseline causes detect-secrets to rewrite the file on
        every run (updated ``generated_at``), turning read-only validation into
        a commit obligation.  When a temp plugin-config file is used, ``--baseline``
        may be present but must point elsewhere.
        """
        baseline = tmp_path / ".secrets.baseline"
        baseline.write_text(
            json.dumps({"generated_at": "2026-01-01T00:00:00Z", "results": {}})
        )
        check = SecurityLocalCheck({"config_file_path": ".secrets.baseline"})
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.output = json.dumps({"results": {}})
        captured_cmd: list[str] = []

        def _capture(cmd: list[str], **kwargs: Any) -> MagicMock:  # type: ignore[misc]
            captured_cmd.extend(cmd)
            return mock_result

        with patch.object(check, "_run_command", side_effect=_capture):
            check._run_detect_secrets(str(tmp_path))

        real_baseline_path = str(tmp_path / ".secrets.baseline")
        assert "--baseline" not in captured_cmd, (
            "No --baseline should be passed when the baseline has no "
            "plugins_used or filters_used — _create_plugin_config_baseline "
            "should have returned None and left the flag out."
        )

    def test_detect_secrets_baseline_file_not_modified(self, tmp_path):
        """Running the security check must NOT modify the .secrets.baseline file."""
        original_content = json.dumps(
            {"generated_at": "2026-01-01T00:00:00Z", "results": {}}, indent=2
        )
        baseline = tmp_path / ".secrets.baseline"
        baseline.write_text(original_content)
        check = SecurityLocalCheck({"config_file_path": ".secrets.baseline"})
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.output = json.dumps({"results": {}})

        with patch.object(check, "_run_command", return_value=mock_result):
            check._run_detect_secrets(str(tmp_path))

        assert (
            baseline.read_text() == original_content
        ), ".secrets.baseline was modified during a read-only security scan"

    def test_detect_secrets_baseline_allowlist_suppresses_known_hashes(self, tmp_path):
        """Secrets already in the baseline allowlist should not be reported."""
        hashed = "abc123def456"  # pragma: allowlist secret
        baseline = tmp_path / ".secrets.baseline"
        baseline.write_text(
            json.dumps(
                {
                    "generated_at": "2026-01-01T00:00:00Z",
                    "results": {
                        "config.py": [
                            {
                                "type": "Secret Keyword",
                                "hashed_secret": hashed,
                                "line_number": 5,
                            }  # pragma: allowlist secret
                        ]
                    },
                }
            )
        )
        check = SecurityLocalCheck({"config_file_path": ".secrets.baseline"})
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.output = json.dumps(
            {
                "results": {
                    "config.py": [
                        {
                            "type": "Secret Keyword",
                            "hashed_secret": hashed,
                            "line_number": 5,
                        }  # pragma: allowlist secret
                    ]
                }
            }
        )

        with patch.object(check, "_run_command", return_value=mock_result):
            result = check._run_detect_secrets(str(tmp_path))

        assert result.passed is True, "Secret already in baseline should be suppressed"

    def test_detect_secrets_new_secret_not_in_baseline_reported(self, tmp_path):
        """A new secret not in the baseline should still be reported."""
        known_hash = "aaaaaaaaaaaa"  # pragma: allowlist secret
        new_hash = "bbbbbbbbbbbb"  # pragma: allowlist secret
        baseline = tmp_path / ".secrets.baseline"
        baseline.write_text(
            json.dumps(
                {
                    "generated_at": "2026-01-01T00:00:00Z",
                    "results": {
                        "config.py": [
                            {
                                "type": "Secret Keyword",
                                "hashed_secret": known_hash,
                                "line_number": 3,
                            }  # pragma: allowlist secret
                        ]
                    },
                }
            )
        )
        check = SecurityLocalCheck({"config_file_path": ".secrets.baseline"})
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.output = json.dumps(
            {
                "results": {
                    "config.py": [
                        {
                            "type": "Secret Keyword",
                            "hashed_secret": new_hash,
                            "line_number": 7,
                        }  # pragma: allowlist secret
                    ]
                }
            }
        )

        with patch.object(check, "_run_command", return_value=mock_result):
            result = check._run_detect_secrets(str(tmp_path))

        assert result.passed is False
        assert "config.py" in result.findings

    def test_detect_secrets_path_dotslash_normalized(self, tmp_path):
        """Baseline key './config.py' must suppress a scan finding of 'config.py'."""
        hashed = "abc123def456"  # pragma: allowlist secret
        baseline = tmp_path / ".secrets.baseline"
        baseline.write_text(
            json.dumps(
                {
                    "generated_at": "2026-01-01T00:00:00Z",
                    "results": {
                        "./config.py": [
                            {
                                "type": "Secret Keyword",
                                "hashed_secret": hashed,
                                "line_number": 5,
                            }  # pragma: allowlist secret
                        ]
                    },
                }
            )
        )
        check = SecurityLocalCheck({"config_file_path": ".secrets.baseline"})
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.output = json.dumps(
            {
                "results": {
                    "config.py": [
                        {
                            "type": "Secret Keyword",
                            "hashed_secret": hashed,
                            "line_number": 5,
                        }  # pragma: allowlist secret
                    ]
                }
            }
        )

        with patch.object(check, "_run_command", return_value=mock_result):
            result = check._run_detect_secrets(str(tmp_path))

        assert result.passed is True, (
            "'./config.py' in baseline should match 'config.py' from scan report "
            "(path normalization strips leading './')"
        )

    def test_detect_secrets_plugin_config_passed_via_temp_baseline(self, tmp_path):
        """When the baseline has plugins_used, --baseline must point to a temp file.

        The real .secrets.baseline must not be passed because detect-secrets
        rewrites it; a throwaway temp file inside .slopmop/ carries the plugin
        config instead.
        """
        baseline_content = {
            "generated_at": "2026-01-01T00:00:00Z",
            "plugins_used": [{"name": "HexHighEntropyString", "hex_limit": 3.0}],
            "filters_used": [],
            "results": {},
        }
        baseline = tmp_path / ".secrets.baseline"
        baseline.write_text(json.dumps(baseline_content))

        check = SecurityLocalCheck({"config_file_path": ".secrets.baseline"})
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.output = json.dumps({"results": {}})
        captured_cmd: list[str] = []

        def _capture(cmd: list[str], **kwargs: Any) -> MagicMock:  # type: ignore[misc]
            captured_cmd.extend(cmd)
            return mock_result

        with patch.object(check, "_run_command", side_effect=_capture):
            check._run_detect_secrets(str(tmp_path))

        assert (
            "--baseline" in captured_cmd
        ), "--baseline should be in cmd when baseline has plugins_used"
        idx = captured_cmd.index("--baseline")
        passed_path = captured_cmd[idx + 1]
        real_baseline = str(tmp_path / ".secrets.baseline")
        assert (
            passed_path != real_baseline
        ), "The real .secrets.baseline must never be the --baseline argument"
        from pathlib import Path as _Path

        assert not _Path(
            passed_path
        ).exists(), "Temp plugin-config baseline must be deleted after the scan"
        assert json.loads(baseline.read_text()) == baseline_content

    def test_detect_secrets_suppresses_cloudflare_account_id(self, tmp_path):
        """Cloudflare accountId (32-char hex) in workflow files should not be flagged."""
        workflow_dir = tmp_path / ".github" / "workflows"
        workflow_dir.mkdir(parents=True)
        workflow = workflow_dir / "deploy-pages.yml"
        workflow.write_text(
            "jobs:\n  deploy:\n    steps:\n"
            "      - name: Deploy\n        with:\n"
            "          accountId: 4c2341810414766ae8cbf672785e82c5\n"  # pragma: allowlist secret
        )
        check = SecurityLocalCheck({})
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.output = json.dumps(
            {
                "results": {
                    ".github/workflows/deploy-pages.yml": [
                        {
                            "type": "Hex High Entropy String",
                            "line_number": 6,
                        }  # pragma: allowlist secret
                    ]
                }
            }
        )
        with patch.object(check, "_run_command", return_value=mock_result):
            result = check._run_detect_secrets(str(tmp_path))

        assert result.passed is True
