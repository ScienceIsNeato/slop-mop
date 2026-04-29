"""Shared helpers for upgrade regression scenario fixtures."""

from __future__ import annotations

import json
from pathlib import Path

_SCENARIO_ROOT = Path(__file__).resolve().parent / "fixtures" / "upgrade_scenarios"


def load_upgrade_scenario(name: str) -> tuple[dict, dict, dict[str, str], dict]:
    scenario_root = _SCENARIO_ROOT / name
    meta = json.loads((scenario_root / "meta.json").read_text(encoding="utf-8"))
    before = json.loads((scenario_root / "before.json").read_text(encoding="utf-8"))
    expected = json.loads((scenario_root / "expected.json").read_text(encoding="utf-8"))
    repo_files = json.loads(
        (scenario_root / "repo_files.json").read_text(encoding="utf-8")
    )
    return before, expected, repo_files, meta


def materialize_upgrade_scenario(tmp_path: Path, name: str) -> tuple[dict, dict, dict]:
    before, expected, repo_files, meta = load_upgrade_scenario(name)
    for relative_path, content in repo_files.items():
        target = tmp_path / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    (tmp_path / ".sb_config.json").write_text(
        json.dumps(before, indent=2) + "\n", encoding="utf-8"
    )
    return before, expected, meta
