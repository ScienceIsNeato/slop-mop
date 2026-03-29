#!/usr/bin/env python3
"""semantic-diff — filter formatting noise from git diffs and render with diff2html.

Parses a unified diff, drops hunks where ALL changes are explained by the
configured IGNORED_SUBSTITUTIONS list, then pipes the cleaned diff to
diff2html for side-by-side browser rendering.

Usage:
    # Compare a branch to main (opens browser):
    python3 scripts/semantic_diff.py --open -- origin/main..HEAD

    # Pipe an existing diff:
    git diff origin/main..HEAD | python3 scripts/semantic_diff.py --stdin --open

    # Just output the cleaned diff (pipe to anything):
    python3 scripts/semantic_diff.py -- origin/main..HEAD | diff2html -i stdin -o preview
"""

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass, field

# ── Substitutions config ─────────────────────────────────────────────────────
# Each entry is (pattern, replacement, is_regex).
# Both sides of every changed hunk are normalised with all substitutions,
# then compared.  Hunks that are identical after normalisation are dropped.
#
# Add/remove entries here to tune what counts as "noise".

IGNORED_SUBSTITUTIONS: list[tuple[str, str, bool]] = [
    # Single → double quotes (deno fmt / prettier)
    ("'", '"', False),
    # Trailing commas added/removed
    (r",\s*$", "", True),
    # Collapse all runs of whitespace (handles line-wrap reformatting)
    (r"\s+", " ", True),
]


# ── Diff parsing ──────────────────────────────────────────────────────────────

@dataclass
class Hunk:
    header: str
    lines: list[str] = field(default_factory=list)  # raw hunk lines incl. context


@dataclass
class FileDiff:
    headers: list[str] = field(default_factory=list)  # "diff --git …", "---", "+++"
    hunks: list[Hunk] = field(default_factory=list)


def parse_diff(raw: str) -> list[FileDiff]:
    files: list[FileDiff] = []
    current_file: FileDiff | None = None
    current_hunk: Hunk | None = None

    for line in raw.splitlines(keepends=True):
        if line.startswith("diff "):
            if current_hunk and current_file:
                current_file.hunks.append(current_hunk)
                current_hunk = None
            current_file = FileDiff()
            files.append(current_file)
            current_file.headers.append(line)
        elif line.startswith(("--- ", "+++ ", "index ", "new file", "deleted file",
                               "old mode", "new mode", "rename ", "similarity ",
                               "Binary ")):
            if current_file:
                if current_hunk:
                    current_file.hunks.append(current_hunk)
                    current_hunk = None
                current_file.headers.append(line)
        elif line.startswith("@@"):
            if current_file:
                if current_hunk:
                    current_file.hunks.append(current_hunk)
                current_hunk = Hunk(header=line)
        elif current_hunk is not None:
            current_hunk.lines.append(line)
        elif current_file is not None:
            current_file.headers.append(line)

    if current_hunk and current_file:
        current_file.hunks.append(current_hunk)

    return files


def normalise(text: str) -> str:
    result = text
    for pattern, replacement, is_regex in IGNORED_SUBSTITUTIONS:
        if is_regex:
            result = re.sub(pattern, replacement, result, flags=re.MULTILINE)
        else:
            result = result.replace(pattern, replacement)
    return result.strip()


def hunk_is_noise(hunk: Hunk) -> bool:
    """Return True if every change in this hunk is explained by IGNORED_SUBSTITUTIONS."""
    removed = "".join(
        line[1:] for line in hunk.lines if line.startswith("-")
    )
    added = "".join(
        line[1:] for line in hunk.lines if line.startswith("+")
    )
    if not removed and not added:
        return True  # context-only, trivially noise-free
    return normalise(removed) == normalise(added)


def filter_diff(files: list[FileDiff]) -> str:
    out_parts: list[str] = []
    dropped_files = 0
    dropped_hunks = 0
    kept_hunks = 0

    for file_diff in files:
        kept = [h for h in file_diff.hunks if not hunk_is_noise(h)]
        dropped_hunks += len(file_diff.hunks) - len(kept)
        kept_hunks += len(kept)

        if not kept:
            dropped_files += 1
            continue

        out_parts.extend(file_diff.headers)
        for hunk in kept:
            out_parts.append(hunk.header)
            out_parts.extend(hunk.lines)

    summary = (
        f"# semantic-diff: dropped {dropped_files} files, "
        f"{dropped_hunks} hunks (formatting noise); "
        f"kept {kept_hunks} hunks with real changes\n"
    )
    print(summary, file=sys.stderr)
    return "".join(out_parts)


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Filter formatting noise from git diffs and render with diff2html.",
        epilog="Anything after -- is passed directly to git diff.",
    )
    parser.add_argument(
        "--stdin", action="store_true",
        help="Read diff from stdin instead of running git diff.",
    )
    parser.add_argument(
        "--open", action="store_true",
        help="Pipe output through diff2html and open in browser.",
    )
    parser.add_argument(
        "--output", "-o", default=None,
        help="Write cleaned diff (or HTML with --open) to this file.",
    )
    parser.add_argument(
        "git_args", nargs=argparse.REMAINDER,
        help="Arguments passed to git diff (after --).",
    )

    args = parser.parse_args()

    # Strip leading "--" separator if present
    git_args = [a for a in args.git_args if a != "--"]

    # Read raw diff
    if args.stdin:
        raw = sys.stdin.read()
    else:
        cmd = ["git", "diff", "-w", "--ignore-blank-lines"] + git_args
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode not in (0, 1):  # 1 = diffs found, that's fine
            print(f"git diff failed: {result.stderr}", file=sys.stderr)
            sys.exit(result.returncode)
        raw = result.stdout

    if not raw.strip():
        print("No diff output — nothing to filter.", file=sys.stderr)
        sys.exit(0)

    files = parse_diff(raw)
    cleaned = filter_diff(files)

    if args.open:
        # Check diff2html is available
        which = subprocess.run(["which", "diff2html"], capture_output=True)
        if which.returncode != 0:
            print(
                "diff2html not found. Install with: npm install -g diff2html-cli",
                file=sys.stderr,
            )
            sys.exit(1)

        if args.output:
            d2h = subprocess.run(
                ["diff2html", "-i", "stdin", "-o", "stdout", "-s", "side", "-f", "html"],
                input=cleaned, capture_output=True, text=True,
            )
            with open(args.output, "w") as f:
                f.write(d2h.stdout)
            subprocess.run(["open", args.output])
            print(f"Wrote {len(d2h.stdout):,} bytes to {args.output}", file=sys.stderr)
        else:
            import tempfile
            with tempfile.NamedTemporaryFile(
                suffix=".html", delete=False, mode="w", prefix="semantic-diff-"
            ) as tmp:
                tmpname = tmp.name
            d2h = subprocess.run(
                ["diff2html", "-i", "stdin", "-o", "stdout", "-s", "side", "-f", "html"],
                input=cleaned, capture_output=True, text=True,
            )
            with open(tmpname, "w") as f:
                f.write(d2h.stdout)
            subprocess.run(["open", tmpname])
            print(
                f"Opened {tmpname} ({len(d2h.stdout):,} bytes)", file=sys.stderr,
            )
    else:
        if args.output:
            with open(args.output, "w") as f:
                f.write(cleaned)
        else:
            sys.stdout.write(cleaned)


if __name__ == "__main__":
    main()
