"""Tests for LocLockCheck."""

from textwrap import dedent

from slopmop.checks.quality.loc_lock import (
    LocLockCheck,
    _count_code_lines,
    _file_action,
    _find_biggest_python_definition,
)
from slopmop.core.result import CheckStatus


class TestLocLockCheck:
    """Tests for LocLockCheck."""

    def test_name(self):
        """Test check name."""
        check = LocLockCheck({})
        assert check.name == "code-sprawl"

    def test_display_name(self):
        """Test display name."""
        check = LocLockCheck({})
        assert "Sprawl" in check.display_name or "Code" in check.display_name

    def test_category(self):
        """Test check category."""
        check = LocLockCheck({})
        assert check.category.key == "myopia"

    def test_config_schema_has_required_fields(self):
        """Test config schema includes key fields."""
        check = LocLockCheck({})
        schema = check.config_schema
        field_names = [f.name for f in schema]

        assert "max_file_lines" in field_names
        assert "max_function_lines" in field_names
        assert "include_dirs" in field_names
        assert "exclude_dirs" in field_names

    def test_is_applicable_with_python_files(self, tmp_path):
        """Test check is applicable when Python files exist."""
        (tmp_path / "main.py").write_text("print('hello')")
        check = LocLockCheck({})
        assert check.is_applicable(str(tmp_path)) is True

    def test_is_applicable_with_js_files(self, tmp_path):
        """Test check is applicable when JS files exist."""
        (tmp_path / "app.js").write_text("console.log('hello');")
        check = LocLockCheck({})
        assert check.is_applicable(str(tmp_path)) is True

    def test_is_applicable_no_source_files(self, tmp_path):
        """Test check is not applicable without source files."""
        (tmp_path / "data.txt").write_text("just text")
        check = LocLockCheck({})
        assert check.is_applicable(str(tmp_path)) is False


class TestLocLockFileLength:
    """Tests for file length enforcement."""

    def test_passes_short_file(self, tmp_path):
        """Test passes when file is under limit."""
        content = "\n".join([f"line {i}" for i in range(50)])
        (tmp_path / "short.py").write_text(content)

        check = LocLockCheck({"max_file_lines": 100})
        result = check.run(str(tmp_path))

        assert result.status == CheckStatus.PASSED

    def test_fails_long_file(self, tmp_path):
        """Test fails when file exceeds limit."""
        content = "\n".join(f"x{i} = {i}" for i in range(150))
        (tmp_path / "long.py").write_text(content)

        check = LocLockCheck({"max_file_lines": 100})
        result = check.run(str(tmp_path))

        assert result.status == CheckStatus.FAILED
        assert "long.py" in result.output
        assert "150 code lines" in result.output

    def test_respects_default_file_limit(self, tmp_path):
        """Test uses default 1000 line limit."""
        content = "\n".join(f"x{i} = {i}" for i in range(999))
        (tmp_path / "under.py").write_text(content)

        check = LocLockCheck({})
        result = check.run(str(tmp_path))

        assert result.status == CheckStatus.PASSED

    def test_fails_over_default_file_limit(self, tmp_path):
        """Test fails when file exceeds default 1000 line limit."""
        content = "\n".join(f"x{i} = {i}" for i in range(1001))
        (tmp_path / "over.py").write_text(content)

        check = LocLockCheck({})
        result = check.run(str(tmp_path))

        assert result.status == CheckStatus.FAILED


class TestLocLockFunctionLength:
    """Tests for function length enforcement."""

    def test_passes_short_function(self, tmp_path):
        """Test passes when function is under limit."""
        content = '''
def short_function():
    """Short function."""
    x = 1
    y = 2
    return x + y
'''
        (tmp_path / "short.py").write_text(content)

        check = LocLockCheck({"max_function_lines": 10})
        result = check.run(str(tmp_path))

        assert result.status == CheckStatus.PASSED

    def test_fails_long_function(self, tmp_path):
        """Test fails when function exceeds limit."""
        lines = ["def long_function():"]
        lines.append('    """Long function."""')
        for i in range(25):
            lines.append(f"    x{i} = {i}")
        lines.append("    return x0")

        (tmp_path / "long.py").write_text("\n".join(lines))

        check = LocLockCheck({"max_function_lines": 10})
        result = check.run(str(tmp_path))

        assert result.status == CheckStatus.FAILED
        assert "long_function" in result.output

    def test_respects_default_function_limit(self, tmp_path):
        """Test uses default 100 line limit for functions."""
        lines = ["def almost_too_long():"]
        for i in range(98):
            lines.append(f"    x{i} = {i}")
        lines.append("    return x0")

        (tmp_path / "ok.py").write_text("\n".join(lines))

        check = LocLockCheck({})
        result = check.run(str(tmp_path))

        assert result.status == CheckStatus.PASSED

    def test_detects_multiple_long_functions(self, tmp_path):
        """Test detects multiple function violations."""
        lines = []

        # First long function
        lines.append("def func1():")
        for i in range(15):
            lines.append(f"    a{i} = {i}")
        lines.append("")

        # Second long function
        lines.append("def func2():")
        for i in range(15):
            lines.append(f"    b{i} = {i}")

        (tmp_path / "multi.py").write_text("\n".join(lines))

        check = LocLockCheck({"max_function_lines": 10})
        result = check.run(str(tmp_path))

        assert result.status == CheckStatus.FAILED
        assert "func1" in result.output
        assert "func2" in result.output


class TestLocLockExclusions:
    """Tests for directory and file exclusions."""

    # These three exclusion tests use REAL code in the huge file, not
    # comment-only content.  Under code-line counting, a file of 2000
    # comment lines has zero code lines and passes regardless of
    # whether it's excluded — so comment-only content would make these
    # tests pass for the wrong reason.  Real code lines mean the file
    # WOULD trip the limit if scanned, proving the exclusion actually
    # fires.

    def test_excludes_node_modules(self, tmp_path):
        """Test excludes node_modules directory."""
        nm_dir = tmp_path / "node_modules" / "package"
        nm_dir.mkdir(parents=True)
        content = "\n".join(f"const x{i} = {i};" for i in range(2000))
        (nm_dir / "huge.js").write_text(content)
        (tmp_path / "app.js").write_text("const x = 1;")

        check = LocLockCheck({"max_file_lines": 100})
        result = check.run(str(tmp_path))

        assert result.status == CheckStatus.PASSED

    def test_excludes_venv(self, tmp_path):
        """Test excludes venv directory."""
        venv_dir = tmp_path / "venv" / "lib"
        venv_dir.mkdir(parents=True)
        content = "\n".join(f"x{i} = {i}" for i in range(2000))
        (venv_dir / "huge.py").write_text(content)
        (tmp_path / "main.py").write_text("x = 1")

        check = LocLockCheck({"max_file_lines": 100})
        result = check.run(str(tmp_path))

        assert result.status == CheckStatus.PASSED

    def test_respects_custom_exclude_dirs(self, tmp_path):
        """Test respects custom exclude_dirs config."""
        gen_dir = tmp_path / "generated"
        gen_dir.mkdir()
        content = "\n".join(f"x{i} = {i}" for i in range(2000))
        (gen_dir / "huge.py").write_text(content)
        (tmp_path / "main.py").write_text("x = 1")

        check = LocLockCheck({"max_file_lines": 100, "exclude_dirs": ["generated"]})
        result = check.run(str(tmp_path))

        assert result.status == CheckStatus.PASSED


class TestLocLockLanguageSupport:
    """Tests for different language support."""

    def test_detects_js_arrow_functions(self, tmp_path):
        """Test detects long arrow functions in JavaScript."""
        lines = ["const longArrow = () => {"]
        for i in range(15):
            lines.append(f"  const x{i} = {i};")
        lines.append("  return x0;")
        lines.append("};")

        (tmp_path / "arrow.js").write_text("\n".join(lines))

        check = LocLockCheck({"max_function_lines": 10})
        result = check.run(str(tmp_path))

        assert result.status == CheckStatus.FAILED
        assert "longArrow" in result.output

    def test_detects_async_python_functions(self, tmp_path):
        """Test detects long async functions in Python."""
        lines = ["async def long_async():"]
        for i in range(15):
            lines.append(f"    x{i} = {i}")
        lines.append("    return x0")

        (tmp_path / "async.py").write_text("\n".join(lines))

        check = LocLockCheck({"max_function_lines": 10})
        result = check.run(str(tmp_path))

        assert result.status == CheckStatus.FAILED
        assert "long_async" in result.output

    def test_checks_only_specified_extensions(self, tmp_path):
        """Test only checks specified extensions when configured."""
        py_content = "\n".join(f"x{i} = {i}" for i in range(200))
        (tmp_path / "long.py").write_text(py_content)
        js_content = "\n".join(f"const x{i} = {i};" for i in range(200))
        (tmp_path / "long.js").write_text(js_content)

        # Only check .js files
        check = LocLockCheck(
            {
                "max_file_lines": 100,
                "extensions": [".js"],
            }
        )
        result = check.run(str(tmp_path))

        assert result.status == CheckStatus.FAILED
        assert "long.js" in result.output
        assert "long.py" not in result.output


class TestLocLockOutput:
    """Tests for output formatting."""

    def test_includes_fix_suggestion(self, tmp_path):
        """Test failure includes fix suggestion."""
        content = "\n".join(f"x{i} = {i}" for i in range(200))
        (tmp_path / "long.py").write_text(content)

        check = LocLockCheck({"max_file_lines": 100})
        result = check.run(str(tmp_path))

        assert result.fix_suggestion is not None
        # The new fix_suggestion points at the per-violation action
        # lines rather than describing what to do directly — the
        # violations say WHAT, the suggestion says DON'T-SQUEEZE.
        assert "move-this instruction" in result.fix_suggestion

    def test_limits_output_to_top_violations(self, tmp_path):
        """Test output is limited to top violations."""
        # Create 15 files, all too long
        for i in range(15):
            content = "\n".join(f"x{j} = {j}" for j in range(200 + i))
            (tmp_path / f"file{i:02d}.py").write_text(content)

        check = LocLockCheck({"max_file_lines": 100})
        result = check.run(str(tmp_path))

        assert result.status == CheckStatus.FAILED
        # Should show top 10 and mention "... and X more"
        assert "and" in result.output and "more" in result.output


# ---------------------------------------------------------------------------
# Anti-squeeze: code-line counting
# ---------------------------------------------------------------------------
#
# These tests exist because an LLM (specifically, an earlier version of
# the agent maintaining this codebase) squeezed base.py from 1003 to
# exactly 1000 by compressing a docstring from 8 lines to 5.  The gate
# went green.  The file still had two unrelated 200-line classes in it.
# That's the failure mode the new metric prevents — prove it here.


class TestCodeLineCounting:
    """The ``_count_code_lines`` helper — what counts, what doesn't."""

    def test_python_counts_code_not_comments(self) -> None:
        src = dedent("""\
            x = 1
            # a comment
            y = 2
            # another comment
            z = 3
        """)
        assert _count_code_lines(src, ".py") == 3

    def test_python_blanks_dont_count(self) -> None:
        src = "x = 1\n\n\n\n\ny = 2\n"
        assert _count_code_lines(src, ".py") == 2

    def test_python_docstring_is_invisible(self) -> None:
        """The exact squeeze the old metric allowed: docstring prose.

        Under raw-line counting, the 6-line docstring here contributes
        6.  Under code-line counting it contributes 0 — the STRING
        token spans all 6 lines but none of them have a NAME/NUMBER/OP.
        Only the def, the return, and the call count.
        """
        src = dedent('''\
            def f():
                """Summary line.

                This docstring has a blank paragraph break and
                multiple lines of prose.  None of this is code.
                It should be invisible to the metric entirely.
                """
                return 1
            f()
        ''')
        assert _count_code_lines(src, ".py") == 3  # def, return, f()

    def test_python_docstring_compression_is_futile(self) -> None:
        """The headline test: squeeze the docstring, count stays put.

        Same function, docstring compressed from 6 lines to 1.  Under
        the old raw-line metric this would drop the count by 5.  Under
        code-line counting: identical.  There is nothing to squeeze.
        """
        verbose = dedent('''\
            def f():
                """Summary.

                Long
                multi-line
                prose.
                """
                return 1
        ''')
        terse = dedent('''\
            def f():
                """Summary. Long multi-line prose."""
                return 1
        ''')
        assert _count_code_lines(verbose, ".py") == _count_code_lines(terse, ".py")

    def test_python_string_assignment_still_counts(self) -> None:
        """A line with a STRING token AND code tokens still counts.

        The tokenize filter skips lines that are ONLY string (bare
        docstrings).  ``CONST = "value"`` has NAME and OP alongside
        the STRING, so the line is code.  We're not making string
        literals disappear — just docstrings.
        """
        src = 'MESSAGE = "Tests timed out"\nOTHER = "also a string"\n'
        assert _count_code_lines(src, ".py") == 2

    def test_python_syntax_error_falls_back(self) -> None:
        """Broken file → prefix-mode fallback, not a crash.

        The fallback is less precise (docstrings WILL count) but the
        file still gets a number.  Better than the whole gate erroring
        out because one file has a stray paren.
        """
        # Unclosed bracket mid-file — tokenize raises TokenError.
        broken = "x = [1, 2,\ny = 3\n"
        # Fallback sees 2 non-blank non-# lines.
        assert _count_code_lines(broken, ".py") == 2

    def test_js_slash_slash_comments_dont_count(self) -> None:
        src = "const x = 1;\n// comment\n// another\nconst y = 2;\n"
        assert _count_code_lines(src, ".js") == 2

    def test_js_blanks_dont_count(self) -> None:
        src = "const x = 1;\n\n\nconst y = 2;\n"
        assert _count_code_lines(src, ".js") == 2

    def test_unknown_extension_defaults_to_hash(self) -> None:
        """Extensions not in the prefix table fall back to ``#``.

        Arbitrary but safe — over-counting a language we don't
        recognize is better than under-counting.  A ``.xyz`` file
        with ``//`` comments will have those comments counted as
        code, which means it trips the limit EARLY, not late.
        """
        src = "code\n# this IS treated as comment\ncode\n"
        assert _count_code_lines(src, ".xyz") == 2


class TestSqueezeDefeat:
    """End-to-end: the squeeze doesn't work anymore."""

    def test_deleting_comments_does_not_help(self, tmp_path) -> None:
        """Two files with identical code, one stuffed with comments.
        Limit 100.  Both at 105 code lines.  Both fail identically.

        This is the mechanical proof: padded.py IS bare.py after a
        comment-strip, and bare.py still fails.  There is nowhere to
        squeeze to.  The 50 comment lines were never contributing.
        """
        code = [f"x{i} = {i}" for i in range(105)]
        # Same 105 code lines plus a comment after each of the first
        # 50 — adds 50 raw lines, 0 code lines.
        padded = code[:]
        for i in range(50):
            padded.insert(2 * i + 1, f"# explains x{i}")

        (tmp_path / "padded.py").write_text("\n".join(padded))
        (tmp_path / "bare.py").write_text("\n".join(code))

        check = LocLockCheck({"max_file_lines": 100})
        result = check.run(str(tmp_path))

        # Both trip.  Stripping the 50 comments from padded.py would
        # turn it into bare.py — which also trips.  No escape.
        assert result.status == CheckStatus.FAILED
        assert "padded.py" in result.output
        assert "bare.py" in result.output
        # And they trip at the SAME count — the comments were never
        # contributing.  That's the proof.
        assert result.output.count("105 code lines") == 2

    def test_comment_heavy_file_gets_headroom(self, tmp_path) -> None:
        """The flip side: well-documented code gets MORE room, not less.

        A file with 120 raw lines but only 80 code lines passes a
        limit of 100.  The metric rewards documentation instead of
        punishing it.  Under the old raw-line count this would fail.
        """
        # 80 code + 40 comments = 120 raw, 80 code
        lines = []
        for i in range(80):
            lines.append(f"x{i} = {i}")
            if i % 2 == 0:
                lines.append(f"# explains x{i}")
        (tmp_path / "documented.py").write_text("\n".join(lines))

        check = LocLockCheck({"max_file_lines": 100})
        result = check.run(str(tmp_path))

        assert result.status == CheckStatus.PASSED


# ---------------------------------------------------------------------------
# Ultra-specific guidance ('#4')
# ---------------------------------------------------------------------------


class TestMoveTarget:
    """``_find_biggest_python_definition`` — what to point the agent at."""

    def test_finds_biggest_class(self) -> None:
        src = dedent("""\
            class Small:
                x = 1

            class Large:
                a = 1
                b = 2
                c = 3
                d = 4
                e = 5

            def tiny():
                pass
        """)
        hit = _find_biggest_python_definition(src)
        assert hit is not None
        name, line, span = hit
        assert name == "Large"
        assert line == 4
        assert span == 6  # lines 4-9 inclusive

    def test_prefers_class_over_nested_method(self) -> None:
        """A 50-line class with one 45-line method → point at the CLASS.

        We're answering "what to move out of the file", not "what to
        break up inside it".  Moving the class moves the method too.
        Only top-level definitions are candidates.
        """
        body = "\n".join(f"        x{i} = {i}" for i in range(45))
        src = f"class Wrapper:\n    def huge(self):\n{body}\n\ndef small(): pass\n"
        hit = _find_biggest_python_definition(src)
        assert hit is not None
        assert hit[0] == "Wrapper"  # not "huge"

    def test_no_definitions_returns_none(self) -> None:
        """A file of module-level assignments has nothing to 'move'.

        The caller falls back to a generic message.  Rare case — a
        file over 1000 code lines with ZERO classes or functions is
        almost certainly generated code that should be excluded anyway.
        """
        src = "\n".join(f"CONST_{i} = {i}" for i in range(50))
        assert _find_biggest_python_definition(src) is None

    def test_syntax_error_returns_none(self) -> None:
        assert _find_biggest_python_definition("def broken(:\n") is None


class TestFileAction:
    """The instruction string — what the agent actually reads."""

    def test_target_clears_limit(self) -> None:
        """Biggest def is bigger than the overage → one move fixes it.

        The message quantifies the headroom you'll have AFTER — makes
        the instruction feel like a complete plan, not a first step.
        """
        msg = _file_action(target=("PythonCheckMixin", 619, 273), over=50)
        assert "PythonCheckMixin" in msg
        assert "273 lines" in msg
        assert "line 619" in msg
        assert "clears the limit by 223" in msg  # 273 - 50

    def test_target_too_small_says_so(self) -> None:
        """Honesty when one move isn't enough.

        Still points at the biggest thing (right first move) but warns
        the gate will fire again.  Better than lying, better than
        trying to chain instructions.  The agent does the move,
        re-runs, gets a new target.  Iterative, each step real.
        """
        msg = _file_action(target=("Helper", 100, 30), over=80)
        assert "Helper" in msg
        assert "re-run after" in msg
        assert "clears the limit" not in msg

    def test_no_target_still_says_dont_trim(self) -> None:
        """The degraded case still carries the anti-squeeze payload.

        When we can't name a target (non-Python file with no functions,
        or a parse error) the instruction is vaguer but STILL says
        "don't trim comments".  The one thing we never drop.
        """
        msg = _file_action(target=None, over=42)
        assert "at least 42 lines" in msg
        assert "trimming them won't help" in msg


class TestFindingGuidance:
    """The Finding.message — what lands in the GitHub annotation."""

    def test_file_finding_names_the_target(self, tmp_path) -> None:
        """The annotation on an oversized file tells you WHAT to move.

        This is the end-to-end check: run the gate on a real file,
        pull the Finding, confirm it names the biggest class by name
        and line.  An agent reading the annotation on a PR has zero
        interpretive work.
        """
        # Biggest class is "Mover" at line 6, spanning 10 lines.
        # Total code lines: 2 (Tiny body) + 10 (Mover body) + enough
        # padding to push over a limit of 15.
        src = dedent("""\
            class Tiny:
                a = 1
                b = 2


            class Mover:
                a = 1
                b = 2
                c = 3
                d = 4
                e = 5
                f = 6
                g = 7
                h = 8
                i = 9
        """)
        (tmp_path / "fat.py").write_text(src + "\n".join(f"p{i}=0" for i in range(10)))

        check = LocLockCheck({"max_file_lines": 15})
        result = check.run(str(tmp_path))

        assert result.status == CheckStatus.FAILED
        finding = result.findings[0]
        assert "Mover" in finding.message
        assert "line 6" in finding.message
        # The annotation anchors ON the class header, not line 1 —
        # the agent sees the instruction right next to the class.
        assert finding.line == 6

    def test_function_finding_says_how_much_to_break_off(self, tmp_path) -> None:
        """The annotation on a long function quantifies the split.

        "Break at least N lines off" where N is the overage.  Not
        "make it shorter" — a specific number.  The agent knows when
        it's done.
        """
        # 25-line function, limit 10 → over by 15.
        body = "\n".join(f"    x{i} = {i}" for i in range(24))
        (tmp_path / "func.py").write_text(f"def bloated():\n{body}\n")

        check = LocLockCheck({"max_function_lines": 10})
        result = check.run(str(tmp_path))

        assert result.status == CheckStatus.FAILED
        finding = result.findings[0]
        assert "bloated()" in finding.message
        assert "Break at least 15 lines off" in finding.message

    def test_fix_suggestion_has_anti_squeeze_warning(self, tmp_path) -> None:
        """The '#3' payload — explicit, in the fix_suggestion, always.

        Checks the specific phrases that matter: naming the squeeze
        ("trim comments", "compress docstrings", "join lines") and
        explaining why it won't work ("already don't count").  An
        agent reading this at the decision point won't reach for the
        squeeze because the message PRE-EMPTS the thought.
        """
        (tmp_path / "fat.py").write_text("\n".join(f"x{i}={i}" for i in range(150)))
        check = LocLockCheck({"max_file_lines": 100})
        result = check.run(str(tmp_path))

        suggestion = result.fix_suggestion
        assert suggestion is not None
        # Names all three squeeze flavours.
        assert "trim comments" in suggestion
        assert "compress docstrings" in suggestion
        assert "join lines" in suggestion
        # Explains WHY they won't work — the pre-emption.
        assert "already don't count" in suggestion
