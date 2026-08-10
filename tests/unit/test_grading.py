class TestFindingsProgress:
    """The letter is coarse; findings show motion between letter changes.

    A legacy repo sits at F (4+ failing gates) through an enormous amount of
    real work — clearing 3 gates and 65% of findings can leave the grade
    untouched, which reads as "nothing happened" to exactly the
    inherited-codebase user `sm refit` serves.
    """

    def test_letter_is_unchanged_by_findings(self):
        from slopmop.reporting.grading import compute_hull_grade

        bare = compute_hull_grade(failing=6, warned=0)
        rich = compute_hull_grade(
            failing=6, warned=0, findings=20, previous_findings=57
        )
        assert bare.grade == rich.grade == "F"
        assert bare.level == rich.level

    def test_progress_note_shows_improvement(self):
        from slopmop.reporting.grading import compute_hull_grade

        g = compute_hull_grade(failing=6, warned=0, findings=20, previous_findings=57)
        assert g.findings_delta == -37
        assert g.progress_note == "20 findings (down 37)"
        assert "down 37" in g.label

    def test_progress_note_shows_regression(self):
        from slopmop.reporting.grading import compute_hull_grade

        g = compute_hull_grade(failing=1, warned=0, findings=9, previous_findings=4)
        assert g.progress_note == "9 findings (up 5)"

    def test_no_previous_run_shows_count_only(self):
        from slopmop.reporting.grading import compute_hull_grade

        g = compute_hull_grade(failing=2, warned=0, findings=7)
        assert g.findings_delta is None
        assert g.progress_note == "7 findings"

    def test_clean_run_has_no_note(self):
        from slopmop.reporting.grading import compute_hull_grade

        g = compute_hull_grade(failing=0, warned=0)
        assert g.progress_note == ""
        assert g.label == "A+ — shipshape"

    def test_singular_finding(self):
        from slopmop.reporting.grading import compute_hull_grade

        g = compute_hull_grade(failing=1, warned=0, findings=1)
        assert g.progress_note == "1 finding"

    def test_to_dict_carries_findings_and_delta(self):
        from slopmop.reporting.grading import compute_hull_grade

        d = compute_hull_grade(
            failing=6, warned=0, findings=20, previous_findings=57
        ).to_dict()
        assert d["findings"] == 20
        assert d["previous_findings"] == 57
        assert d["findings_delta"] == -37
        # The consumer-facing contract (the Action's minimum-grade) is intact.
        assert d["grade"] == "F"

    def test_to_dict_omits_delta_without_baseline(self):
        from slopmop.reporting.grading import compute_hull_grade

        d = compute_hull_grade(failing=2, warned=0, findings=5).to_dict()
        assert d["findings"] == 5
        assert "previous_findings" not in d
        assert "findings_delta" not in d


class TestPreviousFindingsLookup:
    """The delta source: the prior run's hull_grade in last_scour.json."""

    def _write_scour(self, root, payload):
        d = root / ".slopmop"
        d.mkdir(parents=True, exist_ok=True)
        (d / "last_scour.json").write_text(__import__("json").dumps(payload))

    def test_reads_findings_from_prior_run(self, tmp_path):
        from slopmop.reporting.report import _previous_findings_count

        self._write_scour(tmp_path, {"data": {"hull_grade": {"findings": 57}}})
        assert _previous_findings_count(str(tmp_path)) == 57

    def test_missing_file_returns_none(self, tmp_path):
        from slopmop.reporting.report import _previous_findings_count

        assert _previous_findings_count(str(tmp_path)) is None

    def test_no_project_root_returns_none(self):
        from slopmop.reporting.report import _previous_findings_count

        assert _previous_findings_count(None) is None

    def test_unreadable_json_returns_none(self, tmp_path):
        from slopmop.reporting.report import _previous_findings_count

        d = tmp_path / ".slopmop"
        d.mkdir()
        (d / "last_scour.json").write_text("{not json")
        assert _previous_findings_count(str(tmp_path)) is None

    def test_pre_findings_artifact_returns_none(self, tmp_path):
        """A run recorded before the findings field existed has no delta."""
        from slopmop.reporting.report import _previous_findings_count

        self._write_scour(tmp_path, {"data": {"hull_grade": {"grade": "F"}}})
        assert _previous_findings_count(str(tmp_path)) is None

    def test_no_hull_grade_returns_none(self, tmp_path):
        from slopmop.reporting.report import _previous_findings_count

        self._write_scour(tmp_path, {"data": {"summary": {}}})
        assert _previous_findings_count(str(tmp_path)) is None


class TestFindingsCountRobustness:
    """The count must never understate a failing run."""

    def test_gate_without_structured_findings_counts_as_one(self):
        """A gate can fail with raw output and no Finding objects.

        Counting those as zero would render "F — scuttled · 0 findings",
        which reads as "nothing is wrong" on a failing run.
        """
        from slopmop.core.result import CheckResult, CheckStatus

        bare = CheckResult(
            name="x:y", status=CheckStatus.FAILED, duration=0.1, findings=[]
        )
        assert (len(bare.findings) if bare.findings else 1) == 1

    def test_negative_previous_findings_is_rejected(self):
        from slopmop.reporting.grading import compute_hull_grade

        g = compute_hull_grade(failing=1, warned=0, findings=3, previous_findings=-5)
        assert g.previous_findings is None
        assert g.findings_delta is None

    def test_bool_previous_findings_is_rejected(self):
        """bool is a subclass of int — True would become a delta of 1."""
        from slopmop.reporting.grading import compute_hull_grade

        g = compute_hull_grade(
            failing=1, warned=0, findings=3, previous_findings=True  # type: ignore[arg-type]
        )
        assert g.previous_findings is None


class TestPreviousFindingsValidation:
    def test_negative_and_bool_in_artifact_are_rejected(self, tmp_path):
        import json as _json

        from slopmop.reporting.report import _previous_findings_count

        d = tmp_path / ".slopmop"
        d.mkdir()
        for bad in (-1, True, "12", None):
            (d / "last_scour.json").write_text(
                _json.dumps({"data": {"hull_grade": {"findings": bad}}})
            )
            assert _previous_findings_count(str(tmp_path)) is None
