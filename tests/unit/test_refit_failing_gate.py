"""Tests for identifying which gate actually failed in a targeted scour."""

import json

from slopmop.cli._refit_iteration import (
    _artifact_failing_gate,
    _summarise_failure_artifact,
)


def _write_artifact(tmp_path, payload):
    p = tmp_path / "artifact.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


class TestArtifactFailingGate:
    def test_reads_first_to_fix(self, tmp_path):
        p = _write_artifact(
            tmp_path,
            {
                "data": {
                    "first_to_fix": {
                        "gate": "laziness:sloppy-formatting.py",
                        "log_file": ".slopmop/logs/laziness_sloppy-formatting.py.log",
                    }
                }
            },
        )
        assert _artifact_failing_gate(p) == (
            "laziness:sloppy-formatting.py",
            ".slopmop/logs/laziness_sloppy-formatting.py.log",
        )

    def test_missing_first_to_fix(self, tmp_path):
        assert _artifact_failing_gate(_write_artifact(tmp_path, {"data": {}})) == (
            None,
            None,
        )

    def test_unreadable_artifact(self, tmp_path):
        assert _artifact_failing_gate(tmp_path / "nope.json") == (None, None)

    def test_malformed_json(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text("{not json", encoding="utf-8")
        assert _artifact_failing_gate(p) == (None, None)


class TestSummariseFailureArtifact:
    def test_summarises_the_failed_result_not_the_first(self, tmp_path):
        # A targeted scour lists dependencies too; a passing one may sort first.
        p = _write_artifact(
            tmp_path,
            {
                "data": {
                    "results": [
                        {
                            "name": "a:passing",
                            "status": "passed",
                            "findings": [
                                {
                                    "file": "x.py",
                                    "line": 1,
                                    "message": "should not be shown",
                                }
                            ],
                        },
                        {
                            "name": "b:failing",
                            "status": "failed",
                            "findings": [
                                {
                                    "file": "real.py",
                                    "line": 42,
                                    "message": "the actual problem",
                                }
                            ],
                            "fix_suggestion": "do the thing",
                        },
                    ]
                }
            },
        )
        out = "\n".join(_summarise_failure_artifact(p))
        assert "real.py:42" in out
        assert "the actual problem" in out
        assert "should not be shown" not in out
        assert "do the thing" in out

    def test_falls_back_to_first_when_none_failed(self, tmp_path):
        p = _write_artifact(
            tmp_path,
            {
                "data": {
                    "results": [
                        {
                            "name": "a",
                            "status": "warned",
                            "findings": [{"file": "w.py", "message": "warned finding"}],
                        },
                    ]
                }
            },
        )
        assert "warned finding" in "\n".join(_summarise_failure_artifact(p))
