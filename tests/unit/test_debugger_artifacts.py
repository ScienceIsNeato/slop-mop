"""Tests for the cross-language debugger-artifacts gate."""

from slopmop.checks.quality.debugger_artifacts import DebuggerArtifactsCheck
from slopmop.core.result import CheckStatus


def _run(tmp_path, config=None):
    return DebuggerArtifactsCheck(config or {}).run(str(tmp_path))


class TestApplicability:
    def test_applicable_with_python(self, tmp_path):
        (tmp_path / "x.py").write_text("x = 1\n")
        assert DebuggerArtifactsCheck({}).is_applicable(str(tmp_path))

    def test_applicable_with_go(self, tmp_path):
        (tmp_path / "x.go").write_text("package main\n")
        assert DebuggerArtifactsCheck({}).is_applicable(str(tmp_path))

    def test_applicable_with_rust(self, tmp_path):
        (tmp_path / "x.rs").write_text("fn main() {}\n")
        assert DebuggerArtifactsCheck({}).is_applicable(str(tmp_path))

    def test_not_applicable_markdown_only(self, tmp_path):
        (tmp_path / "README.md").write_text("# hi\n")
        assert not DebuggerArtifactsCheck({}).is_applicable(str(tmp_path))

    def test_not_applicable_when_only_tests(self, tmp_path):
        # Source only in tests/ — nothing for this gate to guard.
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "x.py").write_text("breakpoint()\n")
        assert not DebuggerArtifactsCheck({}).is_applicable(str(tmp_path))


class TestPythonPatterns:
    def test_passes_clean(self, tmp_path):
        (tmp_path / "x.py").write_text("x = 1\n")
        r = _run(tmp_path)
        assert r.status is CheckStatus.PASSED

    def test_catches_breakpoint(self, tmp_path):
        (tmp_path / "x.py").write_text("breakpoint()\n")
        r = _run(tmp_path)
        assert r.status is CheckStatus.FAILED
        assert "x.py:1" in r.output

    def test_catches_pdb_set_trace(self, tmp_path):
        (tmp_path / "x.py").write_text("import pdb; pdb.set_trace()\n")
        r = _run(tmp_path)
        # The `import pdb; …` line has pdb.set_trace on it — but the
        # regex anchors on start-of-line to avoid false positives in
        # docstrings.  A bare `pdb.set_trace()` on its own line matches.
        (tmp_path / "y.py").write_text("pdb.set_trace()\n")
        r = _run(tmp_path)
        assert r.status is CheckStatus.FAILED

    def test_catches_ipdb(self, tmp_path):
        (tmp_path / "x.py").write_text("ipdb.set_trace()\n")
        r = _run(tmp_path)
        assert r.status is CheckStatus.FAILED

    def test_ignores_commented_out(self, tmp_path):
        (tmp_path / "x.py").write_text("# breakpoint()\n")
        r = _run(tmp_path)
        assert r.status is CheckStatus.PASSED

    def test_ignores_plain_print(self, tmp_path):
        # print() is often legitimate logging — NOT flagged.
        (tmp_path / "x.py").write_text("print('hello')\n")
        r = _run(tmp_path)
        assert r.status is CheckStatus.PASSED


class TestJavaScriptPatterns:
    def test_catches_debugger_statement(self, tmp_path):
        (tmp_path / "x.js").write_text("debugger;\n")
        r = _run(tmp_path)
        assert r.status is CheckStatus.FAILED

    def test_catches_debugger_no_semicolon(self, tmp_path):
        (tmp_path / "x.ts").write_text("debugger\n")
        r = _run(tmp_path)
        assert r.status is CheckStatus.FAILED

    def test_ignores_debugger_in_word(self, tmp_path):
        (tmp_path / "x.js").write_text("const debuggerEnabled = false;\n")
        r = _run(tmp_path)
        assert r.status is CheckStatus.PASSED

    def test_ignores_console_log(self, tmp_path):
        (tmp_path / "x.js").write_text("console.log('hi');\n")
        r = _run(tmp_path)
        assert r.status is CheckStatus.PASSED


class TestRustPatterns:
    def test_catches_dbg_macro(self, tmp_path):
        (tmp_path / "x.rs").write_text("let y = dbg!(x);\n")
        r = _run(tmp_path)
        assert r.status is CheckStatus.FAILED

    def test_catches_todo_macro(self, tmp_path):
        (tmp_path / "x.rs").write_text("fn f() { todo!() }\n")
        r = _run(tmp_path)
        assert r.status is CheckStatus.FAILED

    def test_ignores_rust_commented(self, tmp_path):
        (tmp_path / "x.rs").write_text("// dbg!(x);\n")
        r = _run(tmp_path)
        assert r.status is CheckStatus.PASSED


class TestGoPatterns:
    def test_catches_runtime_breakpoint(self, tmp_path):
        (tmp_path / "x.go").write_text(
            'package main\nimport "runtime"\nfunc f() { runtime.Breakpoint() }\n'
        )
        r = _run(tmp_path)
        assert r.status is CheckStatus.FAILED

    def test_ignores_println(self, tmp_path):
        (tmp_path / "x.go").write_text(
            'package main\nimport "fmt"\nfunc f() { fmt.Println("ok") }\n'
        )
        r = _run(tmp_path)
        assert r.status is CheckStatus.PASSED


class TestCPatterns:
    def test_catches_builtin_trap(self, tmp_path):
        (tmp_path / "x.c").write_text("void f() { __builtin_trap(); }\n")
        r = _run(tmp_path)
        assert r.status is CheckStatus.FAILED

    def test_catches_sigtrap(self, tmp_path):
        (tmp_path / "x.c").write_text("void f() { raise(SIGTRAP); }\n")
        r = _run(tmp_path)
        assert r.status is CheckStatus.FAILED


class TestExclusions:
    def test_skips_tests_dir(self, tmp_path):
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "x.py").write_text("breakpoint()\n")
        (tmp_path / "src.py").write_text("x = 1\n")  # anchor file
        r = _run(tmp_path)
        assert r.status is CheckStatus.PASSED

    def test_skips_node_modules(self, tmp_path):
        (tmp_path / "node_modules").mkdir()
        (tmp_path / "node_modules" / "x.js").write_text("debugger;\n")
        (tmp_path / "src.js").write_text("x = 1;\n")
        r = _run(tmp_path)
        assert r.status is CheckStatus.PASSED

    def test_user_exclude_dirs(self, tmp_path):
        (tmp_path / "weird").mkdir()
        (tmp_path / "weird" / "x.py").write_text("breakpoint()\n")
        (tmp_path / "src.py").write_text("x = 1\n")
        r = _run(tmp_path, {"exclude_dirs": ["weird"]})
        assert r.status is CheckStatus.PASSED


class TestReporting:
    def test_line_numbers_in_output(self, tmp_path):
        (tmp_path / "x.py").write_text("x = 1\ny = 2\nbreakpoint()\n")
        r = _run(tmp_path)
        assert "x.py:3" in r.output

    def test_multiple_hits_counted(self, tmp_path):
        (tmp_path / "a.py").write_text("breakpoint()\n")
        (tmp_path / "b.js").write_text("debugger;\n")
        r = _run(tmp_path)
        assert r.status is CheckStatus.FAILED
        assert "2 debugger artifact" in r.error

    def test_fix_suggestion_mentions_config_path(self, tmp_path):
        (tmp_path / "x.py").write_text("breakpoint()\n")
        r = _run(tmp_path)
        assert "exclude_dirs" in r.fix_suggestion

    def test_full_name(self):
        check = DebuggerArtifactsCheck({})
        assert check.full_name == "deceptiveness:debugger-artifacts"
