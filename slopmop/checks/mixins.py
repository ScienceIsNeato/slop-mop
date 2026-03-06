"""Language-specific check mixins — Python and JavaScript project helpers.

Split out of ``base.py`` when that file hit the 1000-line code-sprawl
gate.  These classes are pure mixins: they have no meaningful
``__init__``, expect to be mixed into a ``BaseCheck`` subclass, and
reach for ``self._create_result`` / ``self.config`` which the host
class provides.  They live in their own file because venv detection
and npm-lockfile sniffing have nothing to do with the abstract gate
contract — they were just squatting in ``base.py`` by historical
accident.

``PythonCheckMixin`` handles the venv-resolution dance: figuring out
which ``python`` to invoke when the project has its own ``.venv`` but
slop-mop was installed via pipx and has a DIFFERENT python with the
bundled scanners.

The environment gate is a hard stop, not a warning.  A quality gate
that renders verdicts against a borrowed interpreter is a quality
gate that lies — "13/13 passed" on the wrong python is worse than no
gates at all because it manufactures confidence.  The old behaviour
(warn once, suppress forever, proceed) produced exactly that failure
mode in practice: a session that ran dozens of swabs against a
different project's venv, all green, while eight tests passed only
because the contaminated shell had $VIRTUAL_ENV set — they mocked
the subprocess runner but the venv gate let them through on the
ambient activation before the mock was ever reached.  The one
warning that would have caught it fired on the first run and never
again.

There is no escape hatch.  If you don't have a project venv, the
gates that need one fail and tell you how to create it.  "But CI
doesn't have a .venv" — then CI creates one; it's one line in the
workflow and it makes the env explicit instead of ambient.  The cost
of one ``python -m venv .venv && pip install -e .`` is a lot lower
than the cost of a green build that ran against the wrong
interpreter.

``JavaScriptCheckMixin`` does the pnpm/yarn/npm lockfile detection
plus the ``.npmrc`` parsing for ``legacy-peer-deps`` — the kind of
thing every JS gate needs and nobody wants to write twice.
"""

import logging
import os
import shutil
import sys
from pathlib import Path
from typing import List, Optional

from slopmop.checks.base import count_source_scope
from slopmop.core.result import (
    CheckResult,
    CheckStatus,
    Finding,
    FindingLevel,
    ScopeInfo,
)

logger = logging.getLogger(__name__)


class PythonCheckMixin:
    """Mixin for Python-specific check utilities."""

    # Cache resolved Python path per project_root.  Naturally provides
    # once-per-run log semantics — the fallback-cascade log lines only
    # fire on cache miss, which is once per distinct project_root per
    # process.  The old ``_venv_warning_shown`` set was a redundant
    # second layer of suppression on top of this; it's gone.
    _python_cache: dict[str, str] = {}

    def _find_python_in_venv(self, venv_path: Path) -> Optional[str]:
        """Find Python executable in a venv directory (Unix or Windows)."""
        for subpath in ["bin/python", "Scripts/python.exe"]:
            python_path = venv_path / subpath
            if python_path.exists():
                return str(python_path)
        return None

    def _cache_and_return(self, project_root: str, python_path: str) -> str:
        """Cache and return the Python path."""
        PythonCheckMixin._python_cache[project_root] = python_path
        return python_path

    def has_project_venv(self, project_root: str) -> bool:
        """Check if the project has its own virtual environment.

        Returns True ONLY for ``project_root/venv`` or
        ``project_root/.venv``.  It does NOT consult ``$VIRTUAL_ENV``.
        The old behaviour treated any activated venv anywhere on the
        system as equivalent to a project venv — a shell that had a
        different project's venv activated would sail past this check
        and then run gates against that foreign interpreter.  The
        method name says "project venv"; a venv that lives somewhere
        else is by definition not one.
        """
        root = Path(project_root)
        for venv_dir in ["venv", ".venv"]:
            if (root / venv_dir / "bin" / "python").exists():
                return True
            if (root / venv_dir / "Scripts" / "python.exe").exists():
                return True
        return False

    @staticmethod
    def suggest_venv_command(project_root: str) -> str:
        """Suggest the right venv creation command for this project.

        Detects the project's package manager and returns an actionable
        command string.  The user can copy-paste it directly.
        """
        root = Path(project_root)

        # Poetry
        if (root / "poetry.lock").exists():
            return "poetry install"
        # Pipenv
        if (root / "Pipfile").exists():
            return "pipenv install --dev"
        # PDM
        if (root / "pdm.lock").exists():
            return "pdm install"
        # Standard: pyproject.toml or requirements.txt
        if (root / "pyproject.toml").exists():
            return "python3 -m venv venv && source venv/bin/activate && pip install -e '.[dev]'"
        if (root / "requirements.txt").exists():
            return "python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt"
        # Bare minimum
        return "python3 -m venv venv && source venv/bin/activate"

    def check_project_venv_or_fail(
        self, project_root: str, start_time: float
    ) -> Optional[CheckResult]:
        """Return FAILED when no project venv exists.  No escape hatch.

        PROJECT-context checks call this at the top of ``run()``.
        These are checks that import or execute the project's own code
        — pytest loads conftest.py, coverage instruments modules,
        pip-audit inspects site-packages.  Running them against a
        borrowed interpreter produces results that describe the wrong
        thing.

        The old contract returned WARNED here, which downstream
        rendered as yellow-not-red and didn't block commits.  Worse,
        ``has_project_venv`` used to count any ``$VIRTUAL_ENV`` as a
        project venv — so a stale shell activation from a *different
        project* silently satisfied this gate, and the check then ran
        against that foreign interpreter with full confidence.  That's
        not a degraded result, that's a wrong result wearing a green
        checkmark.

        Returns ``None`` when a real project venv exists so the caller
        can proceed::

            result = self.check_project_venv_or_fail(project_root, start_time)
            if result is not None:
                return result
        """
        import time

        if self.has_project_venv(project_root):
            return None

        msg = "No project venv (./venv or ./.venv) — refusing to run against a borrowed interpreter"
        ambient = os.environ.get("VIRTUAL_ENV")
        ambient_note = (
            f"\n\n$VIRTUAL_ENV is currently {ambient} — that is NOT this project's "
            "venv and slop-mop will not use it.  A stale activation from another "
            "project is exactly the case this gate exists to catch."
            if ambient
            else ""
        )

        return self._create_result(  # type: ignore[attr-defined]
            status=CheckStatus.FAILED,
            duration=time.time() - start_time,
            error=msg,
            fix_suggestion=(
                f"Create a project venv:\n"
                f"  cd {project_root} && {self.suggest_venv_command(project_root)}"
                f"{ambient_note}"
            ),
            findings=[Finding(message=msg, level=FindingLevel.ERROR)],
        )

    # Back-compat alias — 4 call sites in checks/, renamed when the
    # semantics flipped from warn-and-proceed to fail-hard.  External
    # plugins (if any exist) that call the old name get the new
    # behaviour, which is what they should want.
    check_project_venv_or_warn = check_project_venv_or_fail

    def get_project_python(self, project_root: str) -> str:
        """Get the Python executable for the project.

        Resolution order:
        1. ``./venv/bin/python`` or ``./.venv/bin/python`` — the project's
           own env, the only answer that's actually correct for gates
           that inspect project state
        2. ``$VIRTUAL_ENV`` — ambient activation, could be anything
        3. ``sys.executable`` — slop-mop's own python, has bundled tools
           but not project deps
        4. ``python3`` on PATH — last resort

        Levels 2-4 are reachable in two cases: the caller didn't gate
        with ``check_project_venv_or_fail`` first (bundled-tool checks
        that only need *a* python, not the *project's* python), or the
        gate hasn't been wired up yet for a new check.  Either way we
        log INFO — not WARNING — about what we picked.  INFO because
        the gate is where the hard stop lives; this method just
        resolves a path.  The cache naturally makes it once-per-root.
        """
        if project_root in PythonCheckMixin._python_cache:
            return PythonCheckMixin._python_cache[project_root]

        root = Path(project_root)

        # 1. Project venv — the correct answer.
        for venv_dir in ["venv", ".venv"]:
            python_path = self._find_python_in_venv(root / venv_dir)
            if python_path:
                virtual_env = os.environ.get("VIRTUAL_ENV")
                if virtual_env:
                    project_venv_path = (root / venv_dir).resolve()
                    if project_venv_path != Path(virtual_env).resolve():
                        # We're doing the right thing (project venv wins),
                        # but the shell is confused.  FYI, not a problem.
                        logger.info(
                            f"Using project venv {project_venv_path} "
                            f"(ignoring $VIRTUAL_ENV={virtual_env})"
                        )
                return self._cache_and_return(project_root, python_path)

        # 2-4. Fallback cascade.  Log what we landed on once — the
        # _python_cache hit above means this fires once per root per
        # process.  No separate suppression set; the cache IS the
        # suppression.
        virtual_env = os.environ.get("VIRTUAL_ENV")
        if virtual_env:
            python_path = self._find_python_in_venv(Path(virtual_env))
            if python_path:
                logger.info(
                    f"No project venv in {project_root}; using $VIRTUAL_ENV={virtual_env}"
                )
                return self._cache_and_return(project_root, python_path)

        if sys.executable:
            logger.info(
                f"No project venv in {project_root}; using sys.executable={sys.executable}"
            )
            return self._cache_and_return(project_root, sys.executable)

        for python_name in ["python3", "python"]:
            system_python = shutil.which(python_name)
            if system_python:
                logger.info(
                    f"No project venv in {project_root}; using PATH {python_name}={system_python}"
                )
                return self._cache_and_return(project_root, system_python)

        return self._cache_and_return(project_root, "python3")

    def _python_execution_failed_hint(self) -> str:
        """Return helpful hint text for Python execution failures.

        Use this in fix_suggestion when a Python tool fails to run.
        """
        return (
            "If this is a 'python not found' or 'module not found' error, "
            "ensure your project has a venv/ or .venv/ directory with dependencies "
            "installed. slop-mop will auto-detect and use it."
        )

    def has_python_files(self, project_root: str) -> bool:
        """Check if project has Python files."""
        root = Path(project_root)
        return any(root.rglob("*.py"))

    def has_setup_py(self, project_root: str) -> bool:
        """Check if project has setup.py."""
        return (Path(project_root) / "setup.py").exists()

    def has_pyproject_toml(self, project_root: str) -> bool:
        """Check if project has pyproject.toml."""
        return (Path(project_root) / "pyproject.toml").exists()

    def has_requirements_txt(self, project_root: str) -> bool:
        """Check if project has requirements.txt."""
        return (Path(project_root) / "requirements.txt").exists()

    def is_python_project(self, project_root: str) -> bool:
        """Check if this is a Python project."""
        return (
            self.has_python_files(project_root)
            or self.has_setup_py(project_root)
            or self.has_pyproject_toml(project_root)
            or self.has_requirements_txt(project_root)
        )

    def skip_reason(self, project_root: str) -> str:
        """Return reason for skipping Python checks."""
        if not self.has_python_files(project_root):
            return "No Python files found"
        if not (
            self.has_setup_py(project_root)
            or self.has_pyproject_toml(project_root)
            or self.has_requirements_txt(project_root)
        ):
            return "No Python project markers (setup.py, pyproject.toml, or requirements.txt)"
        return "Python check not applicable"

    def measure_scope(self, project_root: str) -> Optional[ScopeInfo]:
        """Measure scope for Python checks — counts .py files and LOC.

        Uses include_dirs from config if available, otherwise scans
        the entire project root.
        """
        config = getattr(self, "config", {})
        include_dirs = config.get("include_dirs") or config.get("src_dirs")
        include_list = list(include_dirs) if include_dirs else None
        return count_source_scope(
            project_root, include_dirs=include_list, extensions={".py"}
        )


class JavaScriptCheckMixin:
    """Mixin for JavaScript-specific check utilities."""

    def has_package_json(self, project_root: str) -> bool:
        """Check if project has package.json."""
        return (Path(project_root) / "package.json").exists()

    def has_js_files(self, project_root: str) -> bool:
        """Check if project has JavaScript files."""
        root = Path(project_root)
        return any(root.rglob("*.js")) or any(root.rglob("*.ts"))

    def is_javascript_project(self, project_root: str) -> bool:
        """Check if this is a JavaScript project.

        Requires package.json at project root — scattered .js files
        (e.g., vendored tools) don't constitute a JS project we can lint.
        """
        return self.has_package_json(project_root)

    def has_node_modules(self, project_root: str) -> bool:
        """Check if node_modules exists."""
        return (Path(project_root) / "node_modules").is_dir()

    def skip_reason(self, project_root: str) -> str:
        """Return reason for skipping JavaScript checks."""
        if not self.has_package_json(project_root):
            return "No package.json found (not a JavaScript/TypeScript project)"
        if not self.has_js_files(project_root):
            return "No JavaScript/TypeScript files found"
        return "JavaScript check not applicable"

    def _detect_package_manager(self, project_root: str) -> str:
        """Detect which package manager the project uses.

        Resolution order: pnpm-lock.yaml → yarn.lock → package-lock.json → npm
        """
        root = Path(project_root)
        if (root / "pnpm-lock.yaml").exists():
            return "pnpm"
        if (root / "yarn.lock").exists():
            return "yarn"
        return "npm"

    def _get_npm_install_command(self, project_root: str) -> List[str]:
        """Build install command with the correct package manager.

        Detects pnpm/yarn/npm from lockfiles and uses the appropriate
        install command. Falls back to npm if no lockfile found.
        Available to all JavaScript checks via the mixin.
        """
        pm = self._detect_package_manager(project_root)

        if pm == "pnpm":
            return ["pnpm", "install", "--no-frozen-lockfile"]
        if pm == "yarn":
            return ["yarn", "install", "--ignore-engines"]

        # npm path
        cmd = ["npm", "install"]

        # Add flags from config (handle string or list)
        # Uses self.config from BaseCheck
        config_flags = getattr(self, "config", {}).get("npm_install_flags", [])
        if isinstance(config_flags, str):
            config_flags = [config_flags]
        cmd.extend(config_flags)

        # Check .npmrc for legacy-peer-deps
        npmrc_path = Path(project_root) / ".npmrc"
        if npmrc_path.exists():
            try:
                content = npmrc_path.read_text()
                # Parse line by line, ignoring comments (# and ;)
                for line in content.splitlines():
                    line = line.strip()
                    # Skip comment lines
                    if line.startswith("#") or line.startswith(";"):
                        continue
                    # Check for active legacy-peer-deps setting
                    if (
                        "legacy-peer-deps=true" in line
                        and "--legacy-peer-deps" not in cmd
                    ):
                        cmd.append("--legacy-peer-deps")
                        break
            except Exception:
                pass  # Ignore .npmrc read errors

        return cmd

    def measure_scope(self, project_root: str) -> Optional[ScopeInfo]:
        """Measure scope for JavaScript checks — counts JS/TS files and LOC.

        Uses include_dirs from config if available, otherwise scans
        the entire project root.
        """
        config = getattr(self, "config", {})
        include_dirs = config.get("include_dirs") or config.get("src_dirs")
        include_list = list(include_dirs) if include_dirs else None
        return count_source_scope(
            project_root,
            include_dirs=include_list,
            extensions={".js", ".ts", ".jsx", ".tsx"},
        )
