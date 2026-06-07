"""Tests for scripts/sync_version.py (version propagation + drift detection)."""

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load():
    path = REPO_ROOT / "scripts" / "sync_version.py"
    spec = importlib.util.spec_from_file_location("sync_version_under_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


sync = _load()


def _make_repo(tmp_path: Path, version: str) -> Path:
    (tmp_path / "slopmop").mkdir()
    (tmp_path / "slopmop" / "_version.py").write_text(
        f'__version__ = "{version}"\n', encoding="utf-8"
    )
    return tmp_path


def _doc_target():
    return sync.Target("doc.md", r"version (\d+\.\d+\.\d+)", "doc line")


# ── pure helpers ──────────────────────────────────────────────────────────


def test_sub_version_replaces_only_the_captured_group():
    text = 'see version 1.0.0 here, and a glob "src/**"'
    out = sync._sub_version(text, r"version (\d+\.\d+\.\d+)", "2.5.9")
    assert "version 2.5.9" in out
    assert "src/**" in out  # untouched


def test_source_version_reads_the_file(tmp_path):
    _make_repo(tmp_path, "3.4.5")
    assert sync.source_version(tmp_path) == "3.4.5"


def test_source_version_raises_when_missing(tmp_path):
    (tmp_path / "slopmop").mkdir()
    (tmp_path / "slopmop" / "_version.py").write_text("# no version here\n")
    with pytest.raises(SystemExit):
        sync.source_version(tmp_path)


# ── check / apply with injected root + targets ────────────────────────────


def test_check_clean_when_in_sync(tmp_path):
    _make_repo(tmp_path, "1.2.3")
    (tmp_path / "doc.md").write_text("the doc says version 1.2.3\n")
    version, problems = sync.check(tmp_path, [_doc_target()])
    assert version == "1.2.3"
    assert problems == []


def test_check_reports_drift(tmp_path):
    _make_repo(tmp_path, "1.2.3")
    (tmp_path / "doc.md").write_text("the doc says version 9.9.9\n")
    _version, problems = sync.check(tmp_path, [_doc_target()])
    assert problems and "9.9.9" in problems[0]


def test_check_reports_missing_pattern(tmp_path):
    _make_repo(tmp_path, "1.2.3")
    (tmp_path / "doc.md").write_text("the prose was reworded; no version token\n")
    _version, problems = sync.check(tmp_path, [_doc_target()])
    assert problems and "matched nothing" in problems[0]


def test_check_tolerates_missing_target_file(tmp_path):
    _make_repo(tmp_path, "1.2.3")
    # doc.md does not exist -> skipped, no problem
    _version, problems = sync.check(tmp_path, [_doc_target()])
    assert problems == []


def test_apply_rewrites_then_check_is_clean(tmp_path):
    _make_repo(tmp_path, "4.0.0")
    doc = tmp_path / "doc.md"
    doc.write_text("the doc says version 1.0.0\n")
    version, changed = sync.apply(tmp_path, [_doc_target()])
    assert version == "4.0.0"
    assert changed == ["doc.md"]
    assert "version 4.0.0" in doc.read_text()
    # Idempotent: second apply changes nothing.
    _v, changed_again = sync.apply(tmp_path, [_doc_target()])
    assert changed_again == []


# ── main() CLI surface (monkeypatch the module's REPO_ROOT) ────────────────


def test_main_check_passes_on_real_repo(capsys):
    assert sync.main(["--check"]) == 0
    assert "in sync" in capsys.readouterr().out


def test_main_check_fails_on_drift(tmp_path, monkeypatch, capsys):
    _make_repo(tmp_path, "1.2.3")
    (tmp_path / "README.md").write_text("slop-mop is at version 9.9.9\n")
    monkeypatch.setattr(sync, "REPO_ROOT", tmp_path)
    assert sync.main(["--check"]) == 1
    assert "drift" in capsys.readouterr().err.lower()


def test_main_apply_syncs_then_reports_already_in_sync(tmp_path, monkeypatch, capsys):
    _make_repo(tmp_path, "2.2.2")
    readme = tmp_path / "README.md"
    readme.write_text("slop-mop is at version 1.1.1\n")
    monkeypatch.setattr(sync, "REPO_ROOT", tmp_path)

    assert sync.main([]) == 0
    assert "Synced" in capsys.readouterr().out
    assert "version 2.2.2" in readme.read_text()

    assert sync.main([]) == 0
    assert "Already in sync" in capsys.readouterr().out
