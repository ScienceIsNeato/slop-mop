"""Unit-ish tests for DockerManager internals that don't need Docker.

``test_docker_install.py`` carries a module-level ``skipif(not docker)``
marker so nothing in it runs on CI without a Docker daemon.  That's
correct for the end-to-end container tests but wrong for the pure
string-manipulation logic in ``run_sm``'s extraction path — the marker
splitting and shell-script generation are entirely testable without a
container, and if they break we want to know on EVERY CI run, not just
on machines where Docker happens to be available.

So this file deliberately has NO integration marker and NO skipif.
It runs in the standard unit flow.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from tests.integration.docker_manager import (
    _CONTAINER_BUILD_DIR,
    _CONTAINER_SCENARIO_SUMMARY,
    _EXTRACT_MARKER,
    DockerManager,
    RunResult,
)

# ---------------------------------------------------------------------------
# Shell-script generation
# ---------------------------------------------------------------------------
#
# These tests reach into the bash string that run_sm() builds.  That's
# normally a smell — testing implementation rather than behaviour — but
# here the shell script IS the behaviour: it runs in an opaque container
# and there's no way to observe it except by inspecting the string or
# running Docker.  We inspect the string.


def _capture_shell_script(**run_sm_kwargs: object) -> str:
    """Call run_sm with subprocess mocked, return the generated bash."""
    dm = DockerManager()
    dm._image_built = True  # skip build_image()
    with patch("tests.integration.docker_manager.subprocess.run") as mock_run:
        mock_run.return_value = SimpleNamespace(returncode=0, stdout="", stderr="")
        dm.run_sm(branch="x", **run_sm_kwargs)  # type: ignore[arg-type]
        # Last arg to docker run is the bash -c script
        docker_cmd = mock_run.call_args.args[0]
        return docker_cmd[-1]


def _capture_scenario_shell_script(**run_kwargs: object) -> str:
    """Call run_scripted_scenario with subprocess mocked, return the bash."""
    dm = DockerManager()
    dm._image_built = True
    with patch("tests.integration.docker_manager.subprocess.run") as mock_run:
        mock_run.return_value = SimpleNamespace(returncode=0, stdout="", stderr="")
        dm.run_scripted_scenario(branch="x", scenario_script="echo scenario", **run_kwargs)  # type: ignore[arg-type]
        docker_cmd = mock_run.call_args.args[0]
        return docker_cmd[-1]


def _capture_refit_scenario_shell_script(**run_kwargs: object) -> str:
    """Call run_refit_scenario with subprocess mocked, return the bash."""
    dm = DockerManager()
    dm._image_built = True
    with patch("tests.integration.docker_manager.subprocess.run") as mock_run:
        mock_run.return_value = SimpleNamespace(returncode=0, stdout="", stderr="")
        dm.run_refit_scenario(
            branch="x",
            scenario="happy-path-small",
            run_branch="run/refit/happy-path-small/20260319-abcdef1-run01",
            **run_kwargs,
        )
        docker_cmd = mock_run.call_args.args[0]
        return docker_cmd[-1]


class TestExtractFileShellScript:
    """The bash appendix ``extract_file`` adds to the four-phase script."""

    def test_no_extract_leaves_script_alone(self) -> None:
        script = _capture_shell_script()
        assert _EXTRACT_MARKER not in script
        assert "_SM_RC" not in script

    def test_extract_appends_cat_after_command(self) -> None:
        script = _capture_shell_script(extract_file="/tmp/out.sarif")
        # The cat MUST follow the user's command, not precede it — the
        # file doesn't exist until the command writes it.
        sm_pos = script.find("sm swab")
        cat_pos = script.find('cat "/tmp/out.sarif"')
        assert sm_pos != -1 and cat_pos != -1
        assert cat_pos > sm_pos, (
            f"cat must run AFTER sm command\n"
            f"sm at {sm_pos}, cat at {cat_pos}\n{script}"
        )

    def test_extract_preserves_exit_code(self) -> None:
        """The critical bit: without ``_SM_RC=$?`` the ``cat`` succeeding
        would flip every failing gate run to exit 0.  That would make
        ``assert_prerequisites`` a no-op on the ``all-fail`` branch —
        the one branch where we NEED it to catch real failures.
        """
        script = _capture_shell_script(extract_file="/tmp/x")
        # Must capture $? immediately after the sm command, before
        # anything else runs and overwrites it.
        assert "; _SM_RC=$?" in script
        # Must re-exit with it at the very end.
        assert script.rstrip().endswith("exit $_SM_RC")
        # And the capture must precede the echo/cat (otherwise $?
        # would be echo's exit code, always 0).
        rc_pos = script.find("_SM_RC=$?")
        echo_pos = script.find(f'echo "{_EXTRACT_MARKER}"')
        assert rc_pos < echo_pos, f"$? captured too late:\n{script}"

    def test_extract_swallows_cat_failure(self) -> None:
        """If sm crashes before writing the file, ``cat`` fails.  That
        MUST NOT become the container's exit code — the real failure
        (whatever killed sm) is what we want tests to see.  ``|| true``
        on the cat keeps the stashed ``_SM_RC`` intact.
        """
        script = _capture_shell_script(extract_file="/tmp/x")
        assert "2>/dev/null || true" in script

    def test_marker_echoed_unconditionally(self) -> None:
        """Even when the file doesn't exist, the marker appears.  This
        lets the splitting logic distinguish "container died before
        phase C" (no marker → ``extracted is None``) from "sm wrote an
        empty file" (marker + nothing → ``extracted == ""``).  A test
        for "SARIF output exists" cares about that difference.
        """
        script = _capture_shell_script(extract_file="/tmp/x")
        # echo is NOT guarded by a test -f — it always runs.
        assert f'echo "{_EXTRACT_MARKER}"; cat' in script.replace("\n", "")

    def test_extract_respects_custom_command(self) -> None:
        script = _capture_shell_script(
            command=["sm", "scour", "--sarif"],
            extract_file="/tmp/x",
        )
        assert "sm scour --sarif" in script
        assert "sm swab" not in script  # default not leaked in
        assert "_SM_RC=$?" in script


class TestScenarioShellScript:
    def test_scripted_scenario_runs_after_bootstrap(self) -> None:
        script = _capture_scenario_shell_script()
        init_pos = script.find("sm init --non-interactive")
        scenario_pos = script.find("echo scenario")
        assert init_pos != -1 and scenario_pos != -1
        assert scenario_pos > init_pos, (
            "scenario script must run after clone/install/init bootstrap\n" + script
        )

    def test_scripted_scenario_respects_extract_file(self) -> None:
        script = _capture_scenario_shell_script(extract_file="/tmp/protocol.json")
        assert 'cat "/tmp/protocol.json"' in script
        assert "_SM_RC=$?" in script

    def test_scripted_scenario_uses_custom_ref_for_checkout(self) -> None:
        script = _capture_scenario_shell_script(ref="deadbeef")
        assert "git checkout deadbeef" in script


class TestRefitScenarioShellScript:
    def test_refit_scenario_invokes_driver_script(self) -> None:
        script = _capture_refit_scenario_shell_script()
        assert (
            f"{_CONTAINER_BUILD_DIR}/tests/integration/refit_scenario_driver.py"
            in script
        )
        assert "--scenario happy-path-small" in script
        assert (
            "--run-branch run/refit/happy-path-small/20260319-abcdef1-run01" in script
        )

    def test_refit_scenario_extracts_summary_file(self) -> None:
        script = _capture_refit_scenario_shell_script()
        assert f'cat "{_CONTAINER_SCENARIO_SUMMARY}"' in script

    def test_refit_scenario_respects_custom_checkout_ref(self) -> None:
        script = _capture_refit_scenario_shell_script(ref="deadbeef")
        assert "git checkout deadbeef" in script


# ---------------------------------------------------------------------------
# Output splitting
# ---------------------------------------------------------------------------


def _run_with_stdout(stdout: str, extract_file: str | None = None) -> RunResult:
    """Drive run_sm with canned subprocess output."""
    dm = DockerManager()
    dm._image_built = True
    with patch("tests.integration.docker_manager.subprocess.run") as mock_run:
        mock_run.return_value = SimpleNamespace(returncode=1, stdout=stdout, stderr="")
        return dm.run_sm(branch="x", extract_file=extract_file)


class TestExtractFileSplitting:
    """Parsing the container's stdout back into ``stdout`` + ``extracted``."""

    def test_no_extract_requested(self) -> None:
        result = _run_with_stdout("hello", extract_file=None)
        assert result.extracted is None
        assert result.stdout == "hello"

    def test_splits_on_marker(self) -> None:
        raw = f'git noise\nswab output\n{_EXTRACT_MARKER}\n{{"sarif": true}}'
        result = _run_with_stdout(raw, extract_file="/tmp/x")
        assert result.extracted == '{"sarif": true}'
        assert result.stdout == "git noise\nswab output\n"
        assert _EXTRACT_MARKER not in result.stdout, (
            "marker should be stripped so result.output stays readable "
            "in test failure messages"
        )

    def test_missing_marker_leaves_extracted_none(self) -> None:
        """Container died during phase A/B — no marker because the
        extraction appendix never ran.  ``extracted`` stays ``None``
        (not empty string) and ``stdout`` is untouched so the caller's
        ``assert_prerequisites`` can show the real error.
        """
        raw = "REPO_CLONE_FAILED\nfatal: repository not found\n"
        result = _run_with_stdout(raw, extract_file="/tmp/x")
        assert result.extracted is None
        assert result.stdout == raw

    def test_empty_payload_is_empty_string_not_none(self) -> None:
        """sm wrote the file but it was empty.  That's a different
        failure mode from "file never written" — the feature ran but
        produced nothing.  ``extracted == ""`` lets tests distinguish.
        """
        raw = f"swab ran\n{_EXTRACT_MARKER}\n"
        result = _run_with_stdout(raw, extract_file="/tmp/x")
        assert result.extracted == ""
        assert result.extracted is not None  # redundant but explicit

    def test_preserves_internal_whitespace(self) -> None:
        """SARIF has significant indentation.  Stripping would mangle it.
        Only the ONE leading newline from ``echo`` gets peeled; trailing
        whitespace and the payload's own structure survive untouched.
        """
        payload = '  {\n    "key": "val"\n  }\n\n'
        raw = f"console\n{_EXTRACT_MARKER}\n{payload}"
        result = _run_with_stdout(raw, extract_file="/tmp/x")
        assert result.extracted == payload

    def test_marker_in_payload_splits_once(self) -> None:
        """Paranoia: if the extracted file somehow contains the marker
        string (it won't — see the comment on ``_EXTRACT_MARKER`` — but
        ``maxsplit=1`` means we're safe anyway).  Second occurrence
        stays in the payload.
        """
        payload = f"before {_EXTRACT_MARKER} after"
        raw = f"console\n{_EXTRACT_MARKER}\n{payload}"
        result = _run_with_stdout(raw, extract_file="/tmp/x")
        assert result.extracted == payload


# ---------------------------------------------------------------------------
# RunResult.extracted field defaults
# ---------------------------------------------------------------------------


class TestRunResultExtracted:
    """The dataclass side — mostly that the default doesn't break existing
    three-positional-arg construction in conftest fixtures."""

    def test_defaults_to_none(self) -> None:
        r = RunResult(exit_code=0, stdout="", stderr="", branch="main", command=["sm"])
        assert r.extracted is None

    def test_existing_callers_unchanged(self) -> None:
        """The three branch fixtures in conftest construct RunResult
        without ``extracted``.  This test is the canary for those —
        if it fails, they fail too, but with a less helpful traceback
        buried inside a session-scoped fixture.
        """
        # Matches the RunResult(...) call in docker_manager.run_sm when
        # extract_file is None — five positional-equivalent kwargs.
        r = RunResult(
            exit_code=1,
            stdout="output",
            stderr="errors",
            branch="all-fail",
            command=["sm", "swab"],
        )
        assert r.extracted is None
        assert r.output == "outputerrors"  # .output property still works


class TestBuildImageTimeout:
    def test_build_image_uses_build_timeout_not_run_timeout(self) -> None:
        dm = DockerManager(timeout=123, build_timeout=789)

        with patch("tests.integration.docker_manager.subprocess.run") as mock_run:
            mock_run.return_value = SimpleNamespace(
                returncode=0,
                stdout="built",
                stderr="",
            )
            dm.build_image(force=True)

        assert mock_run.call_args.kwargs["timeout"] == 789
