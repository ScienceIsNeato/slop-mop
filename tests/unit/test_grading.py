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
