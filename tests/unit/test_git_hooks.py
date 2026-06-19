"""Git-hook generation tests (split out of test_sm_cli.py for size).

Covers pre-commit/pre-push hook script generation, the merged/deleted-branch
guard's detection logic, and hook-info parsing.
"""

import argparse
import subprocess
from pathlib import Path

from slopmop.cli.hooks import (
    _GLOBAL_PASSTHROUGH_HOOKS,
    _generate_hook_script,
    _generate_merged_branch_guard,
    _generate_passthrough_hook,
    _generate_pre_push_hook_script,
    _get_git_hooks_dir,
    _global_hooks_dir,
    _parse_hook_info,
    cmd_commit_hooks,
)


def _is_posix_sh(script: str) -> bool:
    import tempfile

    with tempfile.NamedTemporaryFile(mode="w", suffix=".sh", delete=False) as tmp:
        tmp.write(script)
        p = Path(tmp.name)
    try:
        return (
            subprocess.run(
                ["sh", "-n", str(p)], capture_output=True, check=False
            ).returncode
            == 0
        )
    finally:
        p.unlink(missing_ok=True)


class TestGitHooksFunctions:
    """Tests for git hooks helper functions."""

    def test_get_git_hooks_dir(self, tmp_path):
        """Returns hooks dir for git repo."""
        (tmp_path / ".git").mkdir()
        result = _get_git_hooks_dir(tmp_path)
        assert result == tmp_path / ".git" / "hooks"

    def test_get_git_hooks_dir_not_git(self, tmp_path):
        """Returns None for non-git directory."""
        result = _get_git_hooks_dir(tmp_path)
        assert result is None

    def test_generate_hook_script(self):
        """Generates valid hook script with swab verb."""
        script = _generate_hook_script("swab")
        assert "sm swab" in script
        assert "MANAGED BY SLOP-MOP" in script
        # Should use PATH-based sm lookup
        assert "command -v sm" in script
        # Should write structured output for LLM consumption
        assert "--swabbing-timeout 0" in script
        assert "--json-file .slopmop/last_swab.json" in script
        assert "--json --output-file" not in script
        assert "Structured results:" in script
        assert "mkdir -p .slopmop" in script

    def test_generate_hook_script_direct_verb(self):
        """Generates hook script when given a verb directly."""
        script = _generate_hook_script("scour")
        assert "sm scour" in script
        assert "# Command: sm scour" in script
        assert "--swabbing-timeout 0" in script
        assert "--json-file .slopmop/last_scour.json" in script

    def test_generate_pre_push_hook_script(self):
        """Generates pre-push merged-branch guard hook script."""
        script = _generate_pre_push_hook_script()
        assert "# Command: merged-branch-guard + sm scour" in script
        assert "gh pr list" in script
        assert "--state merged" in script
        assert "You're missing some context." in script
        assert "sync against main, checkout a new branch, and open a new PR." in script
        # Guard must inspect the refs Git passes on stdin, not just HEAD, so a
        # push that names a branch other than the current checkout is covered.
        assert "while read -r local_ref local_sha remote_ref remote_sha" in script
        assert "refs/heads/*) branch=${local_ref#refs/heads/}" in script
        # Deletions (all-zero local sha) write nothing and must be skipped.
        assert "0000000000000000000000000000000000000000" in script
        assert "git symbolic-ref" not in script

    def test_pre_push_hook_runs_scour_after_guard(self):
        """The pre-push hook runs a cached scour, after the merged-branch guard."""
        script = _generate_pre_push_hook_script()
        # scour runs, and reuses the swab cache (no --no-cache).
        assert "sm scour --porcelain --json-file .slopmop/last_scour.json" in script
        assert "--no-cache" not in script
        # The guard's stdin loop must finish before scour starts, so the merged
        # check happens first and scour doesn't consume the pushed refs.
        assert script.index("\ndone\n") < script.index("sm scour --porcelain")
        # A failing scour blocks the push, with the standard bypass.
        assert "Push blocked by slop-mop scour" in script
        assert "git push --no-verify" in script

    def test_precommit_hook_embeds_merged_branch_guard(self):
        """The pre-commit hook guards a merged/deleted branch before swab runs."""
        script = _generate_hook_script("swab")
        assert "merged/deleted-branch guard" in script
        # Guard must run BEFORE the swab invocation, or work piles onto a dead
        # branch before the gate even checks. Anchor on the real invocation
        # (with --swabbing-timeout), not the "# Command:" comment.
        assert script.index("\n_sm_merged_branch_guard\n") < script.index(
            "sm swab --porcelain --swabbing-timeout"
        )
        # The three detection strategies, strongest first.
        assert "gh pr list --head" in script and "--state merged" in script
        assert "git ls-remote --heads" in script
        assert "git merge-base --is-ancestor HEAD" in script
        # Allow-lists: integration branches and never-pushed (no upstream).
        assert "main|master|develop" in script
        assert "@{upstream}" in script
        # Escape hatch surfaced to the user.
        assert "git commit --no-verify" in script

    def test_precommit_hook_is_valid_posix_sh(self):
        """The generated hook (guard + swab) must parse as POSIX sh."""

        for verb in ("swab", "scour"):
            script = _generate_hook_script(verb)
            result = subprocess.run(
                ["sh", "-n", "/dev/stdin"],
                input=script,
                text=True,
                capture_output=True,
            )
            assert result.returncode == 0, f"{verb}: {result.stderr}"

    def _run_guard(self, cwd, fake_gh_json: "str | None" = None) -> int:
        """Run the guard in cwd; return exit code.

        When ``fake_gh_json`` is given, a fake ``gh`` is placed first on PATH
        that *applies the --jq filter* (like real gh) to that JSON array — so
        the merged-PR check path is exercised faithfully, including the
        ``.[0].number // empty`` handling of an empty result.
        """
        import os
        import stat as _stat

        guard = "#!/bin/sh\n" + _generate_merged_branch_guard() + "\nexit 0\n"
        script = cwd / ".guard.sh"
        script.write_text(guard)
        env = dict(os.environ)
        if fake_gh_json is not None:
            bindir = cwd / ".fakebin"
            bindir.mkdir(exist_ok=True)
            gh = bindir / "gh"
            gh.write_text(
                "#!/bin/sh\n"
                'f=""; p=""\n'
                'for a in "$@"; do [ "$p" = "--jq" ] && f="$a"; p="$a"; done\n'
                f"printf '%s' '{fake_gh_json}' | jq -r \"$f\"\n"
            )
            gh.chmod(gh.stat().st_mode | _stat.S_IXUSR | _stat.S_IXGRP | _stat.S_IXOTH)
            env["PATH"] = f"{bindir}{os.pathsep}{env.get('PATH', '')}"
        return subprocess.run(["sh", str(script)], cwd=str(cwd), env=env).returncode

    def _git(self, cwd, *args) -> None:

        subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True)

    def test_guard_blocks_branch_merged_into_default(self, tmp_path):
        """A branch fully contained in a moved-on origin/main is blocked."""

        remote = tmp_path / "remote.git"
        subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
        work = tmp_path / "work"
        subprocess.run(["git", "clone", "-q", str(remote), str(work)], check=True)
        self._git(work, "config", "user.email", "t@t.t")
        self._git(work, "config", "user.name", "t")
        self._git(work, "commit", "-q", "--allow-empty", "-m", "init")
        self._git(work, "branch", "-M", "main")
        self._git(work, "push", "-q", "-u", "origin", "main")
        self._git(work, "remote", "set-head", "origin", "main")
        # feature branch, pushed (own tracking ref), then merged into main
        self._git(work, "checkout", "-q", "-b", "feat/x")
        self._git(work, "commit", "-q", "--allow-empty", "-m", "w")
        self._git(work, "push", "-q", "-u", "origin", "feat/x")
        self._git(work, "checkout", "-q", "main")
        self._git(work, "merge", "-q", "--no-ff", "feat/x", "-m", "merge")
        self._git(work, "push", "-q", "origin", "main")
        self._git(work, "checkout", "-q", "feat/x")
        assert self._run_guard(work) == 1  # blocked

    def test_guard_allows_fresh_open_branch(self, tmp_path):
        """An open branch not yet merged is allowed through."""

        remote = tmp_path / "remote.git"
        subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
        work = tmp_path / "work"
        subprocess.run(["git", "clone", "-q", str(remote), str(work)], check=True)
        self._git(work, "config", "user.email", "t@t.t")
        self._git(work, "config", "user.name", "t")
        self._git(work, "commit", "-q", "--allow-empty", "-m", "init")
        self._git(work, "branch", "-M", "main")
        self._git(work, "push", "-q", "-u", "origin", "main")
        self._git(work, "remote", "set-head", "origin", "main")
        self._git(work, "checkout", "-q", "-b", "feat/open")
        self._git(work, "commit", "-q", "--allow-empty", "-m", "w")
        self._git(work, "push", "-q", "-u", "origin", "feat/open")
        assert self._run_guard(work) == 0  # allowed

    def test_guard_allows_integration_branch(self, tmp_path):
        """Committing directly on main is never blocked by the guard."""

        subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
        self._git(tmp_path, "config", "user.email", "t@t.t")
        self._git(tmp_path, "config", "user.name", "t")
        self._git(tmp_path, "commit", "-q", "--allow-empty", "-m", "init")
        self._git(tmp_path, "branch", "-M", "main")
        assert self._run_guard(tmp_path) == 0

    def _setup_pushed_branch(self, tmp_path, branch: str, base: str = "") -> "Path":
        """Init a repo with origin/main and a `branch` (optionally base-tracking)."""

        remote = tmp_path / "remote.git"
        subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
        work = tmp_path / "work"
        subprocess.run(["git", "clone", "-q", str(remote), str(work)], check=True)
        self._git(work, "config", "user.email", "t@t.t")
        self._git(work, "config", "user.name", "t")
        self._git(work, "commit", "-q", "--allow-empty", "-m", "init")
        self._git(work, "branch", "-M", "main")
        self._git(work, "push", "-q", "-u", "origin", "main")
        self._git(work, "remote", "set-head", "origin", "main")
        if base:  # base-tracking branch (tracks origin/main, not its own remote)
            self._git(work, "checkout", "-q", "-b", branch, base)
        else:  # own-tracking branch
            self._git(work, "checkout", "-q", "-b", branch)
            self._git(work, "commit", "-q", "--allow-empty", "-m", "w")
            self._git(work, "push", "-q", "-u", "origin", branch)
        self._git(work, "commit", "-q", "--allow-empty", "-m", "more")
        return work

    def test_guard_allows_open_branch_when_gh_reports_no_merged_pr(self, tmp_path):
        """jq null fix: an empty merged-PR list must NOT block (was 'PR #null')."""
        work = self._setup_pushed_branch(tmp_path, "feat/open")
        # gh installed, returns [] for a still-open branch — must be allowed.
        assert self._run_guard(work, fake_gh_json="[]") == 0

    def test_guard_blocks_when_gh_reports_a_merged_pr(self, tmp_path):
        """An own-tracking branch with a real merged PR is blocked."""
        work = self._setup_pushed_branch(tmp_path, "feat/done")
        assert self._run_guard(work, fake_gh_json='[{"number": 7}]') == 1

    def test_guard_allows_base_tracking_branch_despite_stale_merged_pr(self, tmp_path):
        """Reorder fix: base-tracking branch skips the gh check, so a stale
        merged PR reusing the branch name doesn't false-block it."""
        work = self._setup_pushed_branch(tmp_path, "feat/reused", base="origin/main")
        assert self._run_guard(work, fake_gh_json='[{"number": 99}]') == 0

    def test_guard_uses_jq_empty_fallback(self):
        """The guard must use `// empty` so an absent number isn't the literal 'null'."""
        assert ".[0].number // empty" in _generate_merged_branch_guard()

    def test_guard_blocks_deleted_remote_head(self, tmp_path):
        """Strategy #2: remote branch head deleted (merge cleanup) is blocked.

        Delete the ref directly in the bare remote so the local remote-tracking
        ref persists (no prune) — the realistic state after a GitHub merge+delete.
        """
        work = self._setup_pushed_branch(tmp_path, "feat/gone")
        self._git(tmp_path / "remote.git", "branch", "-D", "feat/gone")
        # fake gh returns [] so the merged-PR check doesn't interfere; the
        # ls-remote check must see the head is gone and block.
        assert self._run_guard(work, fake_gh_json="[]") == 1

    def test_guard_checks_renamed_tracking_branch(self, tmp_path):
        """A branch tracking a NON-default remote ref (renamed) is NOT base-
        tracking — it has its own remote branch and must still be checked.

        Before the fix, any upstream-name != local-name branch was skipped, so
        a merged renamed branch would wrongly accept commits.
        """
        remote = tmp_path / "remote.git"
        subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
        work = tmp_path / "work"
        subprocess.run(["git", "clone", "-q", str(remote), str(work)], check=True)
        self._git(work, "config", "user.email", "t@t.t")
        self._git(work, "config", "user.name", "t")
        self._git(work, "commit", "-q", "--allow-empty", "-m", "init")
        self._git(work, "branch", "-M", "main")
        self._git(work, "push", "-q", "-u", "origin", "main")
        self._git(work, "remote", "set-head", "origin", "main")
        # local 'feat/local' pushed to a DIFFERENT remote name 'feat/remote'
        self._git(work, "checkout", "-q", "-b", "feat/local")
        self._git(work, "commit", "-q", "--allow-empty", "-m", "w")
        self._git(work, "push", "-q", "origin", "feat/local:feat/remote")
        self._git(work, "branch", "--set-upstream-to=origin/feat/remote")
        self._git(work, "commit", "-q", "--allow-empty", "-m", "more")
        # remote_branch=feat/remote != default(main): checked, not skipped.
        # gh reports a merged PR for the head -> blocked (would allow if skipped).
        assert self._run_guard(work, fake_gh_json='[{"number": 12}]') == 1

    def test_parse_hook_info_new_format(self):
        """Parses new-format hook info (Command: sm verb)."""
        content = """# MANAGED BY SLOP-MOP
#!/bin/sh
# Command: sm swab
sm swab
"""
        result = _parse_hook_info(content)
        assert result is not None
        assert result["verb"] == "swab"
        assert result["managed"] is True

    def test_parse_hook_info_not_managed(self):
        """Returns None for non-managed hook."""
        content = "#!/bin/sh\necho hello"
        result = _parse_hook_info(content)
        assert result is None


class TestGlobalHooks:
    """Machine-wide (core.hooksPath) hook generation."""

    def test_global_dir_is_under_slopmop_home(self):
        assert _global_hooks_dir() == Path.home() / ".slopmop" / "git-hooks"

    def test_per_repo_hooks_have_no_global_preamble(self):
        # Per-repo hooks run in their own repo — no delegation/onboarding guard.
        assert "core.hooksPath" not in _generate_hook_script("swab")
        assert "git rev-parse --show-toplevel" not in _generate_hook_script("swab")
        assert "git rev-parse --show-toplevel" not in _generate_pre_push_hook_script()

    def test_global_pre_commit_delegates_then_guards_onboarding(self):
        script = _generate_hook_script("swab", global_install=True)
        # Delegates to the repo-local hook so other tools keep working...
        assert '"$_sm_local" "$@" || exit $?' in script
        assert (
            '_sm_local="$(git rev-parse --git-dir 2>/dev/null)/hooks/pre-commit"'
            in script
        )
        # ...and only runs slop-mop in onboarded repos (else exit 0).
        assert ".sb_config.json" in script and "tool.slopmop" in script
        assert _is_posix_sh(script)

    def test_global_pre_push_captures_stdin_and_feeds_guard(self):
        script = _generate_pre_push_hook_script(global_install=True)
        # stdin is slurped once, then fed to the delegated hook AND the guard.
        assert "_sm_stdin=$(cat)" in script
        assert 'printf \'%s\\n\' "$_sm_stdin" | "$_sm_local"' in script
        # The merged-branch guard loop reads the refs back from a here-doc.
        assert "done <<SLOPMOP_REFS" in script
        # scour still runs, and the whole thing is valid POSIX sh.
        assert "sm scour --porcelain" in script
        assert _is_posix_sh(script)

    def test_global_hook_marker_lets_delegation_skip_our_own_hooks(self):
        # The delegation guard skips a local hook that is itself slop-mop's, so
        # a per-repo install under a global install won't double-run.
        script = _generate_hook_script("swab", global_install=True)
        assert '! grep -q "# MANAGED BY SLOP-MOP" "$_sm_local"' in script

    def test_global_worktree_delegation_uses_git_dir(self):
        # The local hook path must use `git rev-parse --git-dir` so linked
        # worktrees (where .git is a file, not a dir) resolve correctly.
        script = _generate_hook_script("swab", global_install=True)
        assert "$(git rev-parse --git-dir 2>/dev/null)/hooks/pre-commit" in script

    def test_passthrough_hook_delegates_and_is_valid_posix_sh(self):
        # Each passthrough hook should forward to the local hook and be POSIX sh.
        for hook_name in _GLOBAL_PASSTHROUGH_HOOKS:
            script = _generate_passthrough_hook(hook_name)
            assert "# MANAGED BY SLOP-MOP" in script
            assert f"/hooks/{hook_name}" in script
            assert 'exec "$_sm_local" "$@"' in script
            assert _is_posix_sh(script), f"sh -n failed for passthrough {hook_name}"

    def test_global_install_writes_hooks_and_sets_hooksPath(
        self, tmp_path, monkeypatch, capsys
    ):
        """cmd_commit_hooks --global writes hooks and sets core.hooksPath."""
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        monkeypatch.setenv("HOME", str(fake_home))

        args = argparse.Namespace(
            project_root=str(tmp_path),
            hooks_action="install",
            hook_verb="swab",
            global_install=True,
        )
        result = cmd_commit_hooks(args)

        assert result == 0
        global_dir = fake_home / ".slopmop" / "git-hooks"
        assert (global_dir / "pre-commit").exists()
        assert (global_dir / "pre-push").exists()
        # Passthrough hooks for other types should also be present.
        assert (global_dir / "commit-msg").exists()
        assert (global_dir / "prepare-commit-msg").exists()
        out = capsys.readouterr().out
        assert "Machine-wide hooks installed" in out
        assert "core.hooksPath" in out
        # Verify git actually recorded the path.
        cfg = subprocess.run(
            ["git", "config", "--global", "--get", "core.hooksPath"],
            capture_output=True,
            text=True,
            check=False,
        )
        assert cfg.returncode == 0
        assert cfg.stdout.strip() == str(global_dir)

    def test_global_uninstall_removes_hooks_and_unsets_hooksPath(
        self, tmp_path, monkeypatch, capsys
    ):
        """cmd_commit_hooks --global uninstall removes hooks and unsets core.hooksPath."""
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        monkeypatch.setenv("HOME", str(fake_home))

        # Install first so there's something to uninstall.
        install_args = argparse.Namespace(
            project_root=str(tmp_path),
            hooks_action="install",
            hook_verb="swab",
            global_install=True,
        )
        assert cmd_commit_hooks(install_args) == 0
        capsys.readouterr()  # discard install output

        # Now uninstall.
        uninstall_args = argparse.Namespace(
            project_root=str(tmp_path),
            hooks_action="uninstall",
            global_install=True,
        )
        result = cmd_commit_hooks(uninstall_args)

        assert result == 0
        out = capsys.readouterr().out
        assert "global core.hooksPath" in out
        # core.hooksPath should be gone.
        cfg = subprocess.run(
            ["git", "config", "--global", "--get", "core.hooksPath"],
            capture_output=True,
            text=True,
            check=False,
        )
        assert cfg.returncode != 0  # key not found → exit 1
