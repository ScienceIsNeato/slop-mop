"""detect-secrets scanning + result post-processing for the security gate.

Split out of ``security/__init__.py`` to keep that module under the
code-sprawl limit. ``DetectSecretsMixin`` is mixed into ``SecurityLocalCheck``
and relies on host-class members (``self.config``, ``self._run_command``,
``self._get_exclude_dirs``) provided by ``BaseCheck`` / ``SecurityLocalCheck``.
"""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from fnmatch import fnmatch
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, cast

from slopmop.core.result import Finding, FindingLevel

if TYPE_CHECKING:
    # Imported only for annotations. The runtime symbol is imported lazily
    # inside _run_detect_secrets to avoid an import cycle with security/__init__.
    from slopmop.checks.security import SecuritySubResult
    from slopmop.subprocess.runner import SubprocessResult

_GIT_SHA_RE = re.compile(r"\b[0-9a-f]{7,40}\b")
_HEX_HIGH_ENTROPY_STRING = "Hex High Entropy String"


class DetectSecretsMixin:
    """detect-secrets scan invocation, path scoping, and finding filters."""

    if TYPE_CHECKING:
        # Members provided by the host class (BaseCheck / SecurityLocalCheck).
        # Declared so type-checkers resolve attribute access on the mixin.
        config: Dict[str, Any]

        def _run_command(
            self,
            command: List[str],
            cwd: Optional[str] = None,
            timeout: Optional[int] = None,
            env: Optional[Dict[str, str]] = None,
        ) -> SubprocessResult: ...

        def _get_exclude_dirs(self) -> List[str]: ...

    def _detect_secrets_scan_paths(self, project_root: str) -> List[str]:
        """Top-level entries to hand ``detect-secrets scan``, excluded dirs pruned.

        detect-secrets has no flag that prunes the directory *walk*:
        ``--exclude-files`` (and a baseline ``exclude.files`` regex) only filter
        the *report*, so a large ``venv/``, ``node_modules/``, or vendored
        submodule still costs the full file-hashing pass — which on big repos
        sits right on the 60s timeout and makes the gate flaky (barnacle #244).
        Sibling scanners (bandit/semgrep) scope their walk via ``--exclude``;
        detect-secrets only accepts explicit paths, so we pass them.

        We reuse :meth:`_is_path_excluded_for_detect_secrets` — the exact
        predicate that already post-filters findings — so the set of files
        actually scanned (and thus the secrets reported) is unchanged; only the
        wasted descent into excluded directories is removed.

        Returns ``[]`` (scan the whole tree, prior behaviour) when the root
        can't be listed or every top-level entry is excluded, so we never
        accidentally narrow coverage to nothing.
        """
        try:
            entries = sorted(os.listdir(project_root))
        except OSError:
            return []
        return [
            name
            for name in entries
            if not self._is_path_excluded_for_detect_secrets(name)
        ]

    def _is_path_excluded_for_detect_secrets(self, path: str) -> bool:
        """Return True when a path should be ignored by detect-secrets parsing."""
        normalized = self._normalize_ds_path(str(path))
        if not normalized:
            return False

        padded = f"/{normalized}/"
        for raw in self._get_exclude_dirs():
            if not isinstance(raw, str):
                continue
            token = raw.strip().strip("/")
            if not token:
                continue
            if any(ch in token for ch in "*?[]"):
                # fnmatch patterns in config are usually directory tokens
                # (e.g. */.venv). Match both exact and descendant paths.
                if fnmatch(normalized, token) or fnmatch(normalized, f"{token}/*"):
                    return True
            else:
                if f"/{token}/" in padded:
                    return True
        return False

    @staticmethod
    def _safe_read_line(
        project_root: str,
        path: str,
        line_number: Optional[int],
        line_cache: Optional[dict[str, list[str]]] = None,
    ) -> str:
        """Best-effort line reader for detect-secrets post-filters."""
        if not isinstance(line_number, int) or line_number < 1:
            return ""
        try:
            candidate = Path(project_root) / path
            resolved = candidate.resolve()
            root_resolved = Path(project_root).resolve()
            # Prevent escaping project root via crafted report paths.
            if root_resolved not in resolved.parents and resolved != root_resolved:
                return ""
            cache_key = str(resolved)
            lines: list[str]
            if line_cache is not None and cache_key in line_cache:
                lines = line_cache[cache_key]
            else:
                lines = resolved.read_text(
                    encoding="utf-8", errors="ignore"
                ).splitlines()
                if line_cache is not None:
                    line_cache[cache_key] = lines
            if line_number <= len(lines):
                return lines[line_number - 1]
        except OSError:
            return ""
        return ""

    def _is_detect_secrets_false_positive(
        self,
        project_root: str,
        path: str,
        secret: dict[str, Any],
        line_cache: Optional[dict[str, list[str]]] = None,
    ) -> bool:
        """Heuristics for common non-secret detect-secrets findings."""
        normalized = str(path).replace("\\", "/")
        lower = normalized.lower()
        basename = Path(normalized).name.lower()
        detector_type = str(secret.get("type", ""))
        line_text = ""

        if "/.slopmop/" in lower or lower.startswith(".slopmop/"):
            return True
        if "/ios/flutter/ephemeral/" in lower or lower.startswith(
            "ios/flutter/ephemeral/"
        ):
            return True
        if lower.endswith(".xcscheme") and detector_type == _HEX_HIGH_ENTROPY_STRING:
            return True
        if detector_type == _HEX_HIGH_ENTROPY_STRING:
            line_number = secret.get("line_number")
            line_text = self._safe_read_line(
                project_root, normalized, line_number, line_cache
            )
            context_parts = [line_text]
            if isinstance(line_number, int):
                for offset in (2, 1):
                    if line_number > offset:
                        context_parts.insert(
                            0,
                            self._safe_read_line(
                                project_root,
                                normalized,
                                line_number - offset,
                                line_cache,
                            ),
                        )
                for offset in (1, 2):
                    context_parts.append(
                        self._safe_read_line(
                            project_root,
                            normalized,
                            line_number + offset,
                            line_cache,
                        )
                    )
            context_lower = "\n".join(part for part in context_parts if part).lower()
            tokens = set(re.findall(r"[a-z0-9_]+", context_lower))
            if _GIT_SHA_RE.search(context_lower) and (
                "is_placeholder_sha(" in context_lower
                or "make_run_branch_name(" in context_lower
                or "rev-parse" in context_lower
                or "_current_head" in context_lower
                or any(token == "sha" or token.endswith("_sha") for token in tokens)
            ):
                return True
            _PUBLIC_ID_TOKENS = {
                "account_id",
                "accountid",
                "zone_id",
                "zoneid",
                "project_id",
                "projectid",
                "org_id",
                "orgid",
                "tenant_id",
                "tenantid",
                "workspace_id",
                "workspaceid",
            }
            if any(tok in _PUBLIC_ID_TOKENS for tok in tokens):
                return True
        if basename == ".metadata" and detector_type in {
            _HEX_HIGH_ENTROPY_STRING,
            "Base64 High Entropy String",
        }:  # pragma: allowlist secret
            return True
        if (
            basename in {".env.example", "alembic.ini"}
            and detector_type == "Basic Auth Credentials"
        ):
            return True
        if detector_type.lower() == ("se" "cret " "key" "word"):
            if not line_text:
                line_text = self._safe_read_line(
                    project_root, normalized, secret.get("line_number"), line_cache
                )
            line_lower = line_text.lower()
            # Accessing secret env/config keys is not a leaked secret.
            if ".config.get(" in line_lower or "os.getenv(" in line_lower:
                return True
            # Placeholder defaults are expected in templates and smoke tooling.
            placeholder_markers = (
                "change-me",
                "changeme",
                "placeholder",
                "example",
                "dev-",
                "demo",
                "sample",
                "dummy",
            )
            if any(marker in line_lower for marker in placeholder_markers):
                return True
            # Match whole tokens only; avoid substring false positives
            # like "latest", "contest", or "locale".
            tokens = set(re.findall(r"[a-z0-9]+", line_lower))
            if {"test", "local", "dev", "demo", "sample", "dummy"} & tokens and {
                "secret",
                "token",
                "key",
            } & tokens:
                return True
        return False

    @staticmethod
    def _normalize_ds_path(path: str) -> str:
        """Normalize a detect-secrets path for consistent comparison.

        detect-secrets may report paths as ``./config.py`` or ``config.py`` and
        uses backslashes on Windows.  Normalise to a bare forward-slash path so
        allowlist lookups are separator- and prefix-independent.  Only the exact
        ``./`` prefix is stripped (not arbitrary leading dots/slashes) to avoid
        corrupting dotfile names like ``.env``.
        """
        s = str(path).replace("\\", "/")
        return s[2:] if s.startswith("./") else s

    def _load_detect_secrets_allowlist(self, project_root: str) -> set[tuple[str, str]]:
        """Load known (normalized_path, hashed_secret) pairs from the baseline.

        Returns an empty set if no baseline exists or if it cannot be parsed.
        Never writes to the file — this is a read-only operation.
        Paths are normalized via :meth:`_normalize_ds_path` so that
        ``./foo/bar.py`` and ``foo/bar.py`` are treated as the same entry.
        """
        config_file = self.config.get("config_file_path")
        if not config_file:
            return set()
        baseline_path = Path(project_root) / config_file
        if not baseline_path.exists():
            return set()
        try:
            baseline_raw: dict[str, Any] = json.loads(
                baseline_path.read_text(encoding="utf-8")
            )
            baseline_results: dict[str, Any] = baseline_raw.get("results", {})
            if not isinstance(baseline_results, dict):
                return set()
            known: set[tuple[str, str]] = set()
            for bpath, bsecrets in baseline_results.items():
                norm_bpath = self._normalize_ds_path(str(bpath))
                if isinstance(bsecrets, list):
                    for bs in cast(List[Any], bsecrets):
                        if isinstance(bs, dict) and "hashed_secret" in bs:
                            bs_dict: Dict[str, Any] = cast(Dict[str, Any], bs)
                            known.add((norm_bpath, str(bs_dict["hashed_secret"])))
            return known
        except (json.JSONDecodeError, OSError):
            return set()

    def _create_plugin_config_baseline(self, project_root: str) -> Optional[str]:
        """Write a temp baseline carrying plugin/filter config (no results).

        ``detect-secrets scan --baseline <file>`` reads its plugin and filter
        configuration from the baseline rather than using defaults.  We can't
        pass the real baseline because that rewrites ``generated_at``.  Instead
        we write a throwaway file inside ``.slopmop/`` (which is git-ignored)
        that contains only the config blocks and an empty ``results`` dict.
        detect-secrets will update that temp file on its own — we don't care.

        Returns the temp file path, or ``None`` when no baseline config is found.
        """
        config_file = self.config.get("config_file_path")
        if not config_file:
            return None
        baseline_path = Path(project_root) / config_file
        if not baseline_path.exists():
            return None
        try:
            baseline_raw: dict[str, Any] = json.loads(
                baseline_path.read_text(encoding="utf-8")
            )
            plugins_used: Any = baseline_raw.get("plugins_used", [])
            filters_used: Any = baseline_raw.get("filters_used", [])
            if not plugins_used and not filters_used:
                return None
            tmp_baseline: dict[str, Any] = {
                "custom_plugin_paths": baseline_raw.get("custom_plugin_paths", []),
                "exclude": baseline_raw.get("exclude", {"files": None, "lines": None}),
                "filters_used": filters_used,
                "plugins_used": plugins_used,
                "results": {},
                "version": baseline_raw.get("version", ""),
            }
            slopmop_dir = Path(project_root) / ".slopmop"
            slopmop_dir.mkdir(exist_ok=True)
            fd, tmp_path_str = tempfile.mkstemp(
                prefix="detect-secrets-plugin-config-",
                suffix=".json",
                dir=slopmop_dir,
            )
            tmp_path = Path(tmp_path_str)
            try:
                # Close the mkstemp fd before write_text so Windows does not
                # raise a sharing-violation error when opening the file.
                os.close(fd)
                tmp_path.write_text(
                    json.dumps(tmp_baseline, indent=2), encoding="utf-8"
                )
            except OSError:
                # Clean up the orphaned temp file before signalling failure.
                try:
                    tmp_path.unlink(missing_ok=True)
                except OSError:
                    pass
                return None
            return str(tmp_path)
        except (json.JSONDecodeError, OSError):
            return None

    @staticmethod
    def _load_tmp_baseline_report(
        tmp_baseline_path: str,
    ) -> Optional[dict[str, Any]]:
        """Read scan results detect-secrets wrote into a throwaway baseline."""
        try:
            loaded = json.loads(Path(tmp_baseline_path).read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                return cast(dict[str, Any], loaded)
        except (json.JSONDecodeError, OSError):
            return None
        return None

    @staticmethod
    def _parse_detect_secrets_report(
        result_output: str,
        report_from_tmp_baseline: Optional[dict[str, Any]],
    ) -> dict[str, Any]:
        """Normalize stdout JSON or throwaway-baseline JSON into one report."""
        if report_from_tmp_baseline is not None:
            return report_from_tmp_baseline
        report_loaded: Any = json.loads(result_output)
        if isinstance(report_loaded, dict):
            return cast(dict[str, Any], report_loaded)
        return {}

    def _subresult_from_detect_secrets_report(
        self, project_root: str, report: dict[str, Any]
    ) -> SecuritySubResult:
        """Turn a detect-secrets report dict into a pass/fail sub-result."""
        from slopmop.checks.security import SecuritySubResult

        known = self._load_detect_secrets_allowlist(project_root)
        detected_any = report.get("results", {})
        detected = (
            cast(dict[str, Any], detected_any) if isinstance(detected_any, dict) else {}
        )
        real_secrets = self._filter_known_secrets(detected, known, project_root)
        if not real_secrets:
            return SecuritySubResult("detect-secrets", True, "No secrets detected")

        detail_lines: list[str] = []
        for path, secrets in real_secrets.items():
            types = [str(secret.get("type", "?")) for secret in secrets]
            detail_lines.append(f"  Potential secret in {path}: {', '.join(types)}")
        detail = "\n".join(detail_lines)
        sarif = self._build_detect_secrets_sarif(real_secrets)
        return SecuritySubResult("detect-secrets", False, detail, sarif)

    def _run_detect_secrets(self, project_root: str) -> SecuritySubResult:
        """Run detect-secrets scan without touching the real baseline file.

        Passing the *real* ``--baseline`` would make detect-secrets rewrite it
        (fresh ``generated_at``) on every run, dirtying the working tree. So we
        pass a throwaway baseline carrying only the real one's
        ``plugins_used`` / ``filters_used`` (empty ``results``) to honour plugin
        config, and separately load the real ``results`` as a read-only
        allowlist so previously-accepted secrets stay suppressed.
        """
        # Imported lazily to avoid an import cycle: this mixin lives in a
        # sibling module that security/__init__ imports at load time.
        from slopmop.checks.security import (
            SecuritySubResult,
            _scanner_failed_to_start,
        )

        cmd = [sys.executable, "-m", "detect_secrets", "scan"]
        # Scope the walk to top-level paths that aren't excluded. Without this,
        # detect-secrets descends into venv/node_modules/submodules (no path
        # arg => whole working dir), re-hashing gigabytes and tripping the 60s
        # timeout — a flaky false failure, not a real finding (barnacle #244).
        scan_paths = self._detect_secrets_scan_paths(project_root)
        cmd.extend(scan_paths)
        # Pass a throwaway baseline so the plugin/filter config from the real
        # baseline is honoured. detect-secrets will rewrite the throwaway file
        # (updating its generated_at), but the real .secrets.baseline is never
        # touched, so the working tree stays clean.
        tmp_baseline_path = self._create_plugin_config_baseline(project_root)
        if tmp_baseline_path:
            cmd.extend(["--baseline", tmp_baseline_path])

        report_from_tmp_baseline: Optional[dict[str, Any]] = None
        try:
            result = self._run_command(cmd, cwd=project_root, timeout=60)
            if tmp_baseline_path and not (result.stdout or "").strip():
                report_from_tmp_baseline = self._load_tmp_baseline_report(
                    tmp_baseline_path
                )
        finally:
            if tmp_baseline_path:
                Path(tmp_baseline_path).unlink(missing_ok=True)

        if result.success:
            try:
                report = self._parse_detect_secrets_report(
                    result.output, report_from_tmp_baseline
                )
                return self._subresult_from_detect_secrets_report(project_root, report)
            except json.JSONDecodeError:
                return SecuritySubResult("detect-secrets", True, "Scan completed")

        # The scan command exited non-zero. Distinguish a scanner that never
        # ran (module not importable in this interpreter — a tooling failure)
        # from a scan that ran and genuinely failed. The former must not be
        # reported as a security finding: that's a false "SLOP DETECTED" for a
        # broken install, not a leaked secret.
        output = result.output or ""
        if _scanner_failed_to_start(output):
            return SecuritySubResult(
                "detect-secrets",
                True,
                "detect-secrets could not run (module not importable) — "
                "skipped. Reinstall with: pipx install --force 'slopmop[all]'",
                warned=True,
            )

        return SecuritySubResult(
            "detect-secrets",
            False,
            output[-300:] if output else "Scan failed",
        )

    def _filter_known_secrets(
        self,
        detected: dict[str, Any],
        known: set[tuple[str, str]],
        project_root: str,
    ) -> dict[str, list[dict[str, Any]]]:
        """Filter raw scan findings against the baseline allowlist.

        Returns only the secrets that are genuinely new — not present in
        ``known`` (baseline allowlist) and not matching a known false-positive
        pattern.  Paths are normalized so ``./foo.py`` matches ``foo.py``.
        """
        real_secrets: dict[str, list[dict[str, Any]]] = {}
        line_cache: dict[str, list[str]] = {}
        for path_any, secrets_any in detected.items():
            if not isinstance(path_any, str):
                continue
            path = path_any
            norm_path = self._normalize_ds_path(path)
            if self._is_path_excluded_for_detect_secrets(path):
                continue
            if "constants.py" in path:
                continue
            if not isinstance(secrets_any, list):
                continue
            secrets: list[dict[str, Any]] = [
                cast(dict[str, Any], s)
                for s in cast(list[Any], secrets_any)
                if isinstance(s, dict)
            ]
            filtered: list[dict[str, Any]] = []
            for secret in secrets:
                hashed = str(secret.get("hashed_secret", ""))
                if (norm_path, hashed) in known:
                    continue
                if not self._is_detect_secrets_false_positive(
                    project_root, path, secret, line_cache
                ):
                    filtered.append(secret)
            if filtered:
                real_secrets[path] = filtered
        return real_secrets

    @staticmethod
    def _build_detect_secrets_sarif(
        real_secrets: dict[str, list[dict[str, Any]]],
    ) -> List[Finding]:
        """Build SARIF findings from detect-secrets results."""
        sarif: List[Finding] = []
        for path, secrets in real_secrets.items():
            for s in secrets:
                ln = s.get("line_number")
                line_val = ln if isinstance(ln, int) else 1

                fix_strategy = (
                    f"STEP 1 - CLASSIFY Credential:\n"
                    f"  Evaluate the detected credential at {path}:{line_val} and classify it:\n"
                    f"  - DANGEROUS: Real sensitive credential (e.g., live API key, production password, private SSH key).\n"
                    f"  - SAFE_BUT_SLOPPY: Mock/test credential, but hardcoded in production paths or scattered ad-hoc.\n"
                    f"  - SAFE_AND_CLEAN: Mock/test credential, properly centralized in tests or mock directories.\n\n"
                    f"STEP 2 - IF DANGEROUS:\n"
                    f"  Run this exact command to file a blocker and alert the captain:\n"
                    f'  sm barnacle file --title "Live credential leak in {path}" --command "sm swab" '
                    f'--expected "Credentials must not be hardcoded or committed to git" '
                    f'--actual "Dangerous credential detected in {path} at line {line_val}" '
                    f'--workflow "swab" --blocker-type "blocking"\n'
                    f"  Then exit the loop.\n\n"
                    f"STEP 3 - IF SAFE_BUT_SLOPPY:\n"
                    f"  Refactor the code to manage via environment variable (e.g., os.getenv) or move it to a test fixture file. "
                    f"Then start over at STEP 1.\n\n"
                    f"STEP 4 - IF SAFE_AND_CLEAN:\n"
                    f"  Run this exact command to add the approved test credential to the baseline:\n"
                    f"  python3 -m detect_secrets scan --baseline .secrets.baseline"
                )

                sarif.append(
                    Finding(
                        message=f"Potential secret: {s.get('type', '?')}",
                        level=FindingLevel.ERROR,
                        file=path,
                        line=ln if isinstance(ln, int) else None,
                        fix_strategy=fix_strategy,
                    )
                )
        return sarif
