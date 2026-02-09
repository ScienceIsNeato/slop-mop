"""Strip Python docstrings using the tokenize module.

This is the only reliable way to remove docstrings from Python source.
Regex-based approaches break on docstrings containing internal quotes,
escaped characters, or nested triple-quote patterns.

Uses Python's tokenize module which actually parses the token stream,
correctly handling all edge cases that regex cannot.

Usage:
    # Strip a single file to stdout
    python strip_docstrings.py file.py

    # Batch mode: strip multiple files into a target directory,
    # preserving relative paths from a source root
    python strip_docstrings.py --batch --src-root /project --target-dir /tmp/stripped file1.py file2.py ...
"""

import argparse
import io
import sys
import tokenize
from pathlib import Path


def strip_docstrings(source: str) -> str:
    """Remove docstrings from Python source using the tokenize module.

    Based on the pyminifier approach (Dan McDougall, SO #2962727),
    updated for Python 3. Uses token stream analysis to correctly
    identify docstrings vs regular string literals.

    A STRING token is a docstring when preceded by INDENT, NEWLINE,
    or at module level (after ENCODING). Regular string expressions
    like ``'string' >> obj`` are preserved.

    Args:
        source: Python source code as a string.

    Returns:
        Source with docstrings replaced by ``pass`` statements
        (to preserve valid syntax for functions with only a docstring).
    """
    io_obj = io.StringIO(source)
    out = ""
    prev_toktype = tokenize.INDENT
    last_lineno = -1
    last_col = 0

    for tok in tokenize.generate_tokens(io_obj.readline):
        token_type = tok[0]
        token_string = tok[1]
        start_line, start_col = tok[2]
        end_line, end_col = tok[3]

        # Preserve indentation and whitespace
        if start_line > last_lineno:
            last_col = 0
        if start_col > last_col:
            out += " " * (start_col - last_col)

        if token_type == tokenize.STRING:
            if prev_toktype in (tokenize.INDENT, tokenize.NEWLINE, tokenize.ENCODING):
                # This is a docstring — replace with pass to keep syntax valid
                out += "pass"
            elif prev_toktype == tokenize.NL:
                # Could be module-level docstring
                if start_col == 0:
                    out += "pass"
                else:
                    out += token_string
            else:
                # Regular string literal — preserve it
                out += token_string
        elif token_type == tokenize.COMMENT:
            # Strip comments too — they're not string literals
            pass
        else:
            out += token_string

        prev_toktype = token_type
        last_col = end_col
        last_lineno = end_line

    return out


def strip_file(filepath: str) -> str:
    """Read a Python file and return its content with docstrings stripped."""
    with open(filepath, encoding="utf-8", errors="replace") as f:
        source = f.read()
    try:
        return strip_docstrings(source)
    except tokenize.TokenError:
        # If tokenization fails (syntax error in source), return original
        return source


def batch_strip(
    files: list[str], src_root: str, target_dir: str
) -> dict[str, str]:
    """Strip docstrings from multiple files into a target directory.

    Preserves relative paths from src_root so the Node tool's glob
    patterns still work.

    Args:
        files: Absolute paths to .py files.
        src_root: Project root to compute relative paths from.
        target_dir: Directory to write stripped copies to.

    Returns:
        Mapping of original path -> stripped path.
    """
    path_map: dict[str, str] = {}
    src_root_path = Path(src_root).resolve()
    target_path = Path(target_dir)

    for filepath in files:
        try:
            rel = Path(filepath).resolve().relative_to(src_root_path)
        except ValueError:
            # File outside src_root — use basename
            rel = Path(filepath).name  # type: ignore[assignment]

        out_path = target_path / rel
        out_path.parent.mkdir(parents=True, exist_ok=True)

        stripped = strip_file(filepath)
        out_path.write_text(stripped, encoding="utf-8")
        path_map[filepath] = str(out_path)

    return path_map


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Strip docstrings from Python files using tokenize"
    )
    parser.add_argument("files", nargs="+", help="Python files to process")
    parser.add_argument(
        "--batch",
        action="store_true",
        help="Batch mode: write stripped files to target-dir",
    )
    parser.add_argument(
        "--src-root",
        default=".",
        help="Source root for computing relative paths (batch mode)",
    )
    parser.add_argument(
        "--target-dir",
        help="Target directory for stripped files (batch mode)",
    )

    args = parser.parse_args()

    if args.batch:
        if not args.target_dir:
            print("--target-dir required in batch mode", file=sys.stderr)
            sys.exit(1)
        batch_strip(args.files, args.src_root, args.target_dir)
    else:
        # Single file mode: print to stdout
        for filepath in args.files:
            print(strip_file(filepath))


if __name__ == "__main__":
    main()
