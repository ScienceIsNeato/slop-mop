#!/bin/bash
# release.sh — Bump version, create release branch + PR, leave a paper trail.
#
# Usage:
#   ./scripts/release.sh patch   # 0.3.0 → 0.3.1
#   ./scripts/release.sh minor   # 0.3.0 → 0.4.0
#   ./scripts/release.sh major   # 0.3.0 → 1.0.0
#
# What it does:
#   1. Reads the current version from pyproject.toml
#   2. Computes the bumped version
#   3. Creates a release/<new_version> branch off main
#   4. Updates pyproject.toml with the new version
#   5. Commits, pushes, and opens a PR
#
# The PR merge is still manual — you review the changelog, then merge.
# Once merged, push the tag (or let CI do it) to trigger release.yml.
#
# Can also be called from CI via the prepare-release workflow.

set -euo pipefail

# ── Helpers ──────────────────────────────────────────────

die() { echo "❌ $*" >&2; exit 1; }

usage() {
    echo "Usage: $0 <patch|minor|major>"
    echo ""
    echo "  patch   Bump the patch version (0.3.0 → 0.3.1)"
    echo "  minor   Bump the minor version (0.3.0 → 0.4.0)"
    echo "  major   Bump the major version (0.3.0 → 1.0.0)"
    exit 1
}

# ── Validate input ───────────────────────────────────────

BUMP="${1:-}"
[[ "$BUMP" =~ ^(patch|minor|major)$ ]] || usage

# ── Resolve project root ────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

# ── Preflight checks ────────────────────────────────────

command -v gh &>/dev/null || die "gh CLI not found. Install: https://cli.github.com"
command -v python3 &>/dev/null || die "python3 not found"

# Ensure we're on main and clean
CURRENT_BRANCH=$(git branch --show-current)
if [[ "$CURRENT_BRANCH" != "main" ]]; then
    echo "⚠️  Not on main (on $CURRENT_BRANCH). Switching to main..."
    git checkout main
fi
git pull origin main --ff-only || die "Could not fast-forward main. Resolve manually."

if [[ -n "$(git status --porcelain)" ]]; then
    die "Working tree is dirty. Commit or stash changes first."
fi

# ── Read current version from pyproject.toml ─────────────

CURRENT_VERSION=$(python3 -c "
import tomllib
with open('pyproject.toml', 'rb') as f:
    print(tomllib.load(f)['project']['version'])
")

echo "📦 Current version: $CURRENT_VERSION"

# ── Compute new version ──────────────────────────────────

IFS='.' read -r V_MAJOR V_MINOR V_PATCH <<< "$CURRENT_VERSION"

case "$BUMP" in
    major) V_MAJOR=$((V_MAJOR + 1)); V_MINOR=0; V_PATCH=0 ;;
    minor) V_MINOR=$((V_MINOR + 1)); V_PATCH=0 ;;
    patch) V_PATCH=$((V_PATCH + 1)) ;;
esac

NEW_VERSION="${V_MAJOR}.${V_MINOR}.${V_PATCH}"
BRANCH_NAME="release/v${NEW_VERSION}"
TAG_NAME="v${NEW_VERSION}"

echo "🔼 Bump: $BUMP → $NEW_VERSION"

# ── Ensure no tag or branch collision ────────────────────

if git rev-parse "$TAG_NAME" &>/dev/null 2>&1; then
    die "Tag $TAG_NAME already exists. Delete it first or choose a different bump."
fi

if git rev-parse --verify "$BRANCH_NAME" &>/dev/null 2>&1; then
    die "Branch $BRANCH_NAME already exists. Delete it first."
fi

# ── Create release branch ───────────────────────────────

git checkout -b "$BRANCH_NAME"

# ── Bump version in pyproject.toml ───────────────────────

# Use python to do a precise in-place replacement (no sed portability issues)
python3 -c "
import re, pathlib
p = pathlib.Path('pyproject.toml')
text = p.read_text()
text = re.sub(
    r'^version\s*=\s*\"[^\"]+\"',
    'version = \"${NEW_VERSION}\"',
    text,
    count=1,
    flags=re.MULTILINE,
)
p.write_text(text)
print('✅ pyproject.toml updated')
"

# ── Verify the bump ─────────────────────────────────────

VERIFY_VERSION=$(python3 -c "
import tomllib
with open('pyproject.toml', 'rb') as f:
    print(tomllib.load(f)['project']['version'])
")

if [[ "$VERIFY_VERSION" != "$NEW_VERSION" ]]; then
    die "Version verification failed: expected $NEW_VERSION, got $VERIFY_VERSION"
fi

# ── Generate changelog snippet ───────────────────────────

CHANGELOG=$(git log --oneline "v${CURRENT_VERSION}..HEAD" 2>/dev/null || echo "(no previous tag found)")

# ── Commit + push ────────────────────────────────────────

git add pyproject.toml
git commit -m "chore: bump version to ${NEW_VERSION} for PyPI release"

echo "🚀 Pushing $BRANCH_NAME..."
git push -u origin "$BRANCH_NAME"

# ── Create PR ────────────────────────────────────────────

PR_BODY="## Release v${NEW_VERSION}

**Bump type:** \`${BUMP}\` (${CURRENT_VERSION} → ${NEW_VERSION})

### Changes since v${CURRENT_VERSION}

${CHANGELOG}

### Post-merge steps

After merging this PR, the release is triggered by pushing the tag:

\`\`\`bash
git checkout main && git pull
git tag ${TAG_NAME} && git push origin ${TAG_NAME}
\`\`\`

This will trigger the \`release.yml\` workflow which:
1. Runs quality gates
2. Builds the package
3. Publishes to PyPI
4. Creates a GitHub Release with auto-generated notes"

echo "$PR_BODY" > /tmp/release_pr_body.md

PR_URL=$(gh pr create \
    --title "chore: bump version to ${NEW_VERSION} for PyPI release" \
    --body-file /tmp/release_pr_body.md \
    --base main \
    --head "$BRANCH_NAME")

rm -f /tmp/release_pr_body.md

echo ""
echo "════════════════════════════════════════════════════════════"
echo "✅ Release v${NEW_VERSION} prepared!"
echo ""
echo "   PR:     $PR_URL"
echo "   Branch: $BRANCH_NAME"
echo "   Tag:    $TAG_NAME (push after PR merges)"
echo "════════════════════════════════════════════════════════════"
