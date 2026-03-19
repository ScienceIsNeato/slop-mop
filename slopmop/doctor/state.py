"""``.slopmop/`` state health and repair.

These are the only checks that implement ``--fix``, because
``.slopmop/`` is unambiguously slop-mop's own turf.  Even so, fixes
stay conservative: we delete a lock only when the existing
stale-detection logic says it's stale; we only chmod a directory we
own; we never overwrite a broken config without first moving it aside.

``state.lock`` — stale ``sm.lock`` detection.  Reuses
``_is_stale()``/``_pid_alive()`` so the verdict matches what
``sm swab`` would compute when it hits the same lock.  ``--fix``
deletes stale locks, never live ones.

``state.dir_permissions`` — can we write under ``.slopmop/``?  A
read-only state dir turns caching, timing persistence, and lock
acquisition into silent no-ops that degrade behaviour.  ``--fix``
creates the directory if absent, chmods back to writable if owned by
the current user; otherwise prints a sudo hint.

``state.config_readable`` — is ``.sb_config.json`` parseable JSON?  A
broken config makes every gate skip with opaque messages.  ``--fix``
looks for the most recent backup under ``.slopmop/backups/*/`` (left
by ``sm upgrade``) and restores it, moving the broken file aside
first.  If no backup exists, nothing is touched.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, cast

from slopmop.core.config import config_file_path, state_dir_path
from slopmop.core.lock import (
    _is_stale,
    _lock_path,
    _pid_alive,
    _read_lock_meta,
)
from slopmop.doctor.base import DoctorCheck, DoctorContext, DoctorResult


def _format_age(seconds: float) -> str:
    seconds = max(0.0, seconds)
    if seconds < 120:
        return f"{seconds:.0f}s"
    minutes = seconds / 60
    if minutes < 120:
        return f"{minutes:.0f}m"
    hours = minutes / 60
    return f"{hours:.1f}h"


class StateLockCheck(DoctorCheck):
    name = "state.lock"
    description = "Stale or live sm.lock under .slopmop/"
    can_fix = True

    def _inspect(self, ctx: DoctorContext) -> tuple[str, dict[str, object]]:
        """Return ``(state, data)`` where state ∈ {"none","live","stale","unreadable"}."""
        lock_file = _lock_path(ctx.project_root)
        data: dict[str, object] = {"lock_file": str(lock_file)}

        if not lock_file.exists():
            return "none", data

        meta = _read_lock_meta(lock_file)
        if meta is None:
            return "unreadable", data

        pid = meta.get("pid")
        verb = meta.get("verb", "?")
        started = meta.get("started_at", 0)
        age = time.time() - started if started else 0.0

        data.update(
            pid=pid,
            verb=verb,
            started_at=started,
            age_seconds=round(age, 1),
            pid_alive=bool(isinstance(pid, int) and _pid_alive(pid)),
        )

        if _is_stale(meta, ctx.project_root):
            return "stale", data
        return "live", data

    def run(self, ctx: DoctorContext) -> DoctorResult:
        state, data = self._inspect(ctx)
        lock_file = str(data["lock_file"])

        if state == "none":
            return self._ok("no lock held", data=data)

        def _header(*extra: str) -> str:
            return "\n".join((f"Lock file: {lock_file}", *extra))

        fix_hint = f"sm doctor --fix state.lock\n(or: rm {lock_file})"

        if state == "unreadable":
            return self._fail(
                "lock sidecar present but unparseable",
                detail=_header(
                    "Sidecar JSON could not be read — likely a crashed run."
                ),
                fix_hint=fix_hint,
                data=data,
            )

        pid = data.get("pid", "?")
        verb = data.get("verb", "?")
        age = _format_age(cast(float, data.get("age_seconds", 0.0)))
        holder = f"Holder:    pid={pid} verb={verb} (age {age})"

        if state == "stale":
            alive = data.get("pid_alive")
            reason = "PID not running" if not alive else "age exceeds threshold"
            return self._fail(
                f"stale lock held by PID {pid}",
                detail=_header(holder, f"Reason:    {reason}"),
                fix_hint=fix_hint,
                data=data,
            )

        # live — another sm is genuinely running.  Not an error, just
        # something the user should know.
        return self._warn(
            f"live lock: sm {verb} running (pid {pid}, {age})",
            detail=_header(
                holder,
                "",
                "Another ``sm`` process is active.  Wait for it to "
                "finish, or kill it if it has hung.",
            ),
            data=data,
        )

    def fix(self, ctx: DoctorContext) -> DoctorResult:
        state, data = self._inspect(ctx)
        lock_file = Path(str(data["lock_file"]))

        if state == "none":
            return self._ok("no lock to remove", data=data)

        if state == "live":
            # Deliberately refuse.  The lock is real.
            return self._warn(
                "refusing to remove live lock",
                detail=(
                    f"PID {data.get('pid')} is still running ``sm {data.get('verb')}``.\n"
                    "``--fix`` will not delete a live lock.  Kill the process "
                    "first if you are certain it has hung."
                ),
                data=data,
            )

        # stale or unreadable — safe to delete.
        try:
            lock_file.unlink(missing_ok=True)
        except OSError as exc:
            return self._fail(
                "could not remove stale lock",
                detail=f"{lock_file}: {exc}",
                data=data,
            )
        return self._ok(f"removed stale lock {lock_file}", data=data)


class StateDirCheck(DoctorCheck):
    name = "state.dir_permissions"
    description = "`.slopmop/` exists and is writable"
    can_fix = True

    def run(self, ctx: DoctorContext) -> DoctorResult:
        state_dir = state_dir_path(ctx.project_root)
        data: dict[str, object] = {"state_dir": str(state_dir)}

        if not state_dir.exists():
            # Absent is fine until first run creates it — but check
            # whether it *can* be created.
            parent = state_dir.parent
            if not os.access(parent, os.W_OK):
                return self._fail(
                    ".slopmop/ absent and parent not writable",
                    detail=(
                        f"State dir: {state_dir}\n"
                        f"Parent {parent} is not writable by this user."
                    ),
                    fix_hint=(
                        f"Check directory permissions:\n"
                        f"  ls -ld {parent}\n"
                        f"  # then chmod/chown as appropriate"
                    ),
                    data=data,
                )
            return self._ok(".slopmop/ not yet created (OK)", data=data)

        data["exists"] = True

        # Probe write access.  ``os.access`` lies under some ACL
        # setups; a real write/delete is the reliable test.
        try:
            with tempfile.NamedTemporaryFile(dir=state_dir, delete=True):
                pass
        except OSError as exc:
            data["error"] = str(exc)
            return self._fail(
                ".slopmop/ exists but is not writable",
                detail=(
                    f"State dir: {state_dir}\n"
                    f"Write probe failed: {exc}\n"
                    f"Mode: {stat.filemode(state_dir.stat().st_mode)}"
                ),
                fix_hint=(
                    f"sm doctor --fix state.dir_permissions\n"
                    f"(or: chmod u+rwx {state_dir})"
                ),
                data=data,
            )

        return self._ok(".slopmop/ writable", data=data)

    def fix(self, ctx: DoctorContext) -> DoctorResult:
        state_dir = state_dir_path(ctx.project_root)

        if not state_dir.exists():
            try:
                state_dir.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                return self._fail(
                    "could not create .slopmop/",
                    detail=f"{state_dir}: {exc}",
                )
            return self._ok(f"created {state_dir}")

        # Exists but not writable.  Only chmod if we own it — chmod on
        # a directory owned by someone else requires elevation and we
        # don't do that silently.
        try:
            st = state_dir.stat()
            if hasattr(os, "getuid") and st.st_uid != os.getuid():
                return self._fail(
                    ".slopmop/ not owned by current user",
                    detail=(
                        f"{state_dir} is owned by uid {st.st_uid}, "
                        f"current uid is {os.getuid()}."
                    ),
                    fix_hint=f"sudo chown -R $(id -un) {state_dir}",
                )
            mode = st.st_mode | stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR
            os.chmod(state_dir, mode)
        except OSError as exc:
            return self._fail(
                "chmod failed",
                detail=f"{state_dir}: {exc}",
            )

        # Re-verify.
        return self.run(ctx)


def _find_newest_config_backup(project_root: Path) -> Optional[Path]:
    """Return the newest ``*.sb_config.json`` under ``.slopmop/backups/``."""
    backups_root = state_dir_path(project_root) / "backups"
    if not backups_root.exists():
        return None
    candidates = list(backups_root.rglob(config_file_path(project_root).name))
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


class StateConfigCheck(DoctorCheck):
    name = "state.config_readable"
    description = "`.sb_config.json` parseable as JSON"
    can_fix = True

    def run(self, ctx: DoctorContext) -> DoctorResult:
        path = config_file_path(ctx.project_root)
        data: dict[str, object] = {"config_file": str(path)}

        if not path.exists():
            return self._ok(
                "no config yet (run `sm init`)",
                data=data,
            )

        try:
            raw = path.read_text(encoding="utf-8")
            json.loads(raw)
        except (OSError, json.JSONDecodeError) as exc:
            backup = _find_newest_config_backup(ctx.project_root)
            data["error"] = str(exc)
            data["backup_available"] = str(backup) if backup else None
            fix_lines: list[str] = []
            if backup:
                fix_lines.append("sm doctor --fix state.config_readable")
                fix_lines.append(f"(will restore from: {backup})")
            else:
                fix_lines.append("# no backup found — re-run init:")
                fix_lines.append("sm init")
            return self._fail(
                "config JSON is unreadable",
                detail=(
                    f"Config:  {path}\n"
                    f"Error:   {type(exc).__name__}: {exc}\n"
                    f"Backup:  {backup or 'none found'}"
                ),
                fix_hint="\n".join(fix_lines),
                data=data,
            )

        return self._ok(f"config parses: {path}", data=data)

    def fix(self, ctx: DoctorContext) -> DoctorResult:
        path = config_file_path(ctx.project_root)

        if not path.exists():
            return self._ok("no config to repair")

        # Still broken?  re-check — another process may have fixed it.
        try:
            json.loads(path.read_text(encoding="utf-8"))
            return self._ok("config already parses — no fix needed")
        except Exception:
            pass

        backup = _find_newest_config_backup(ctx.project_root)
        if backup is None:
            return self._fail(
                "no backup available to restore from",
                detail=(
                    f"{path} is unparseable and no backup found under "
                    f"{state_dir_path(ctx.project_root) / 'backups'}."
                ),
                fix_hint="sm init  # recreate config from scratch",
            )

        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        aside = path.with_suffix(f".broken.{stamp}.json")
        try:
            shutil.move(str(path), str(aside))
            shutil.copy2(str(backup), str(path))
        except OSError as exc:
            return self._fail(
                "restore failed",
                detail=f"Backup: {backup}\nTarget: {path}\nError:  {exc}",
            )

        return self._ok(
            f"restored config from {backup}",
            detail=f"Broken file moved to: {aside}",
            data={"restored_from": str(backup), "moved_aside": str(aside)},
        )
