"""Strip Python docstrings using the tokenize module.

This is the only reliable way to remove docstrings from Python source.
Regex-based approaches break on docstrings containing internal quotes,
escaped characters, or nested triple-quote patterns.

Uses Python's tokenize module which actually parses the token stream,
correctly handling all edge cases that regex cannot.

Line numbers are preserved: multi-line docstrings are replaced with
``pass`` plus enough blank lines to maintain the original line count.
This ensures downstream tools report correct line numbers.

Usage:
    python strip_docstrings.py file.py
"""

import argparse
import io
import tokenize


def strip_docstrings(source: str) -> str:
    """Remove docstrings from Python source using the tokenize module.

    Based on the pyminifier approach (Dan McDougall, SO #2962727),
    updated for Python 3. Uses token stream analysis to correctly
    identify docstrings vs regular string literals.

    A STRING token is a docstring when preceded by INDENT, NEWLINE,
    or at module level (after ENCODING). Regular string expressions
    like ``'string' >> obj`` are preserved.

    Line numbers are preserved: multi-line docstrings are replaced
    with ``pass`` plus enough blank lines to keep the total line count
    identical to the original.  This means downstream tools (like the
    duplicate-string finder) report correct file positions.

    Args:
        source: Python source code as a string.

    Returns:
        Source with docstrings blanked (line-count preserved) and
        ``pass`` inserted to keep syntax valid.
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
            is_docstring = prev_toktype in (
                tokenize.INDENT,
                tokenize.NEWLINE,
                tokenize.ENCODING,
            ) or (prev_toktype == tokenize.NL and start_col == 0)

            if is_docstring:
                # Replace with pass + enough newlines to preserve line count
                newline_count = token_string.count("\n")
                out += "pass" + "\n" * newline_count
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


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Strip docstrings from Python files using tokenize"
    )
    parser.add_argument("files", nargs="+", help="Python files to process")
    args = parser.parse_args()

    for filepath in args.files:
        print(strip_file(filepath))


if __name__ == "__main__":
    main()
