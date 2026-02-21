#!/bin/bash
# Slop-Mop Setup Script
#
# Sets up slop-mop for a project:
#   1. Creates/finds a Python venv
#   2. Installs all required dependencies
#   3. Creates convenience `sm` wrappers in the parent project
#   4. Verifies all packages installed correctly
#
# Usage (from parent project root):
#   ./slop-mop/scripts/setup.sh
#
# Or from within slop-mop:
#   ./scripts/setup.sh

set -euo pipefail

# ─── Resolve paths ────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SLOP_MOP_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PROJECT_ROOT="$(cd "$SLOP_MOP_DIR/.." && pwd)"

echo ""
echo "� Slop-Mop Setup"
echo "============================================================"
echo "📂 Project root:  $PROJECT_ROOT"
echo "📂 Slop-mop dir:  $SLOP_MOP_DIR"
echo ""

# ─── Step 1: Find or create venv ──────────────────────────────────
VENV_DIR=""
if [ -d "$PROJECT_ROOT/venv" ]; then
    VENV_DIR="$PROJECT_ROOT/venv"
    echo "✅ Found existing venv: $VENV_DIR"
elif [ -d "$PROJECT_ROOT/.venv" ]; then
    VENV_DIR="$PROJECT_ROOT/.venv"
    echo "✅ Found existing venv: $VENV_DIR"
else
    VENV_DIR="$PROJECT_ROOT/venv"
    echo "📦 Creating virtual environment: $VENV_DIR"
    python3 -m venv "$VENV_DIR"
    echo "✅ Virtual environment created"
fi

PYTHON="$VENV_DIR/bin/python"
PIP="$VENV_DIR/bin/pip"

# Activate for the rest of this script
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

# ─── Step 2: Upgrade pip ──────────────────────────────────────────
echo ""
echo "📦 Upgrading pip..."
"$PYTHON" -m pip install --upgrade pip --quiet

# ─── Step 3: Install slop-mop dependencies ────────────────────────
echo ""
echo "📦 Installing slop-mop dependencies..."

# Use requirements.txt as the single source of truth for deps
REQUIREMENTS="$SLOP_MOP_DIR/requirements.txt"
if [ ! -f "$REQUIREMENTS" ]; then
    echo "❌ Error: requirements.txt not found at $REQUIREMENTS"
    exit 1
fi

"$PIP" install -r "$REQUIREMENTS" --quiet 2>&1 || {
    echo ""
    echo "⚠️  Some packages failed to install. Trying individually..."
    FAILED=()
    while IFS= read -r line; do
        # Skip comments and empty lines
        [[ "$line" =~ ^[[:space:]]*# ]] && continue
        [[ -z "${line// }" ]] && continue
        "$PIP" install "$line" --quiet 2>&1 || FAILED+=("$line")
    done < "$REQUIREMENTS"
    
    if [ ${#FAILED[@]} -gt 0 ]; then
        echo ""
        echo "❌ Failed to install these packages:"
        for pkg in "${FAILED[@]}"; do
            echo "   • $pkg"
        done
        echo ""
        echo "   These checks may not work until the packages are installed."
        echo "   You can try installing them manually or check platform compatibility."
    fi
}

echo "✅ Dependencies installed"

# ─── Step 4: Install vendored Node.js tools ───────────────────────
echo ""
echo "🔧 Installing vendored Node.js tools..."

FDS_DIR="$SLOP_MOP_DIR/tools/find-duplicate-strings"

if [ ! -d "$FDS_DIR" ] || [ ! -f "$FDS_DIR/package.json" ]; then
    echo "ℹ️  Vendored Node.js tools not found — skipping"
elif ! command -v node &>/dev/null; then
    echo "⚠️  Node.js not found — skipping find-duplicate-strings"
    echo "   Install Node.js to enable quality:string-duplication checking"
elif ! command -v npm &>/dev/null; then
    echo "⚠️  npm not found — skipping find-duplicate-strings"
    echo "   Install npm to enable quality:string-duplication checking"
elif [ -f "$FDS_DIR/lib/cli/index.js" ] && [ -d "$FDS_DIR/node_modules" ]; then
    echo "✅ find-duplicate-strings already installed — skipping"
else
    echo "📦 Installing find-duplicate-strings..."
    # npm install triggers the postinstall hook which runs tsc automatically.
    # HUSKY=0 prevents husky from printing ".git can't be found" since
    # this directory is not a standalone git repo.
    (cd "$FDS_DIR" && HUSKY=0 npm install --silent 2>&1) || true
    if [ -f "$FDS_DIR/lib/cli/index.js" ]; then
        echo "✅ find-duplicate-strings installed successfully"
    else
        echo "⚠️  find-duplicate-strings install failed"
        echo "   To fix: cd $FDS_DIR && npm install"
        echo "   quality:string-duplication checks will be skipped until installed"
    fi
fi

# ─── Step 5: Create convenience wrapper ───────────────────────────
echo ""
echo "📄 Creating 'sm' wrapper script..."

# Determine the relative path from project root to slop-mop
RELATIVE_SM_DIR=$(python3 -c "import os.path; print(os.path.relpath('$SLOP_MOP_DIR', '$PROJECT_ROOT'))")

SM_WRAPPER="$PROJECT_ROOT/scripts/sm"
mkdir -p "$(dirname "$SM_WRAPPER")"

cat > "$SM_WRAPPER" << WRAPPER_EOF
#!/bin/bash
# Auto-generated by slop-mop setup — runs sm from the local submodule.
# Do NOT install slop-mop via pip. Each project gets its own copy.

SCRIPT_DIR="\$(cd "\$(dirname "\${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="\$(cd "\$SCRIPT_DIR/.." && pwd)"
SLOP_MOP_DIR="\$PROJECT_ROOT/$RELATIVE_SM_DIR"

if [ ! -d "\$SLOP_MOP_DIR/slopmop" ]; then
    echo "❌ Error: slop-mop submodule not found at \$SLOP_MOP_DIR"
    echo "   Run: git submodule update --init"
    exit 1
fi

# Find Python executable (prefer project venv, fall back to system Python)
PYTHON=""
if [ -f "\$PROJECT_ROOT/venv/bin/python" ]; then
    PYTHON="\$PROJECT_ROOT/venv/bin/python"
elif [ -f "\$PROJECT_ROOT/.venv/bin/python" ]; then
    PYTHON="\$PROJECT_ROOT/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON="python3"
elif command -v python >/dev/null 2>&1; then
    PYTHON="python"
else
    echo "❌ Error: No Python found. Install Python 3 or create a venv."
    exit 1
fi

# Run the module directly from the submodule.
# cd to project root first so --project-root defaults to "." work correctly
# regardless of where the caller's working directory is (e.g. git hooks,
# CI steps, or running the wrapper via an absolute path from a subdir).
export PYTHONPATH="\$SLOP_MOP_DIR:\${PYTHONPATH:-}"
cd "\$PROJECT_ROOT"
exec "\$PYTHON" -m slopmop.sm "\$@"
WRAPPER_EOF

chmod +x "$SM_WRAPPER"
echo "✅ Wrapper created: $SM_WRAPPER"

# Create root-level wrapper so `./sm` works from the project root.
# Same pattern as ./gradlew or ./manage.py — a real executable that
# delegates to the canonical scripts/sm wrapper.
ROOT_SM="$PROJECT_ROOT/sm"
if [ ! -e "$ROOT_SM" ] || [ -L "$ROOT_SM" ]; then
    # Remove stale symlink if present (migrating from earlier setup)
    [ -L "$ROOT_SM" ] && rm -f "$ROOT_SM"
    cat > "$ROOT_SM" << 'ROOT_WRAPPER_EOF'
#!/bin/bash
# Auto-generated by slop-mop setup — root-level convenience wrapper.
# Delegates to scripts/sm. Same pattern as ./gradlew or ./manage.py.
exec "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/scripts/sm" "$@"
ROOT_WRAPPER_EOF
    chmod +x "$ROOT_SM"
    echo "✅ Root wrapper created: $ROOT_SM (delegates to scripts/sm)"
else
    echo "⚠️  $ROOT_SM already exists — skipping (delete it to regenerate)"
fi

# ─── Step 6: Verify installations ─────────────────────────────────
# Derive the tool list from requirements.txt (single source of truth)
# rather than maintaining a separate hardcoded list.
echo ""
echo "🔍 Verifying installed packages..."

PASS=0
FAIL=0
MISSING=()

while IFS= read -r line; do
    # Skip comments and blank lines
    [[ "$line" =~ ^[[:space:]]*# ]] && continue
    [[ -z "${line// }" ]] && continue
    # Strip version specifiers: "black>=23.0.0" -> "black"
    pkg=$(echo "$line" | sed 's/[><=!;].*//' | xargs)
    [ -z "$pkg" ] && continue
    if "$PIP" show "$pkg" &>/dev/null; then
        PASS=$((PASS + 1))
    else
        FAIL=$((FAIL + 1))
        MISSING+=("$pkg")
    fi
done < "$REQUIREMENTS"

echo "   ✅ $PASS/$((PASS + FAIL)) packages verified"
if [ $FAIL -gt 0 ]; then
    echo "   ⚠️  $FAIL packages not found after install:"
    for pkg in "${MISSING[@]}"; do
        echo "      • $pkg"
    done
    echo "   Some quality gates may not work. Try: pip install <package>"
fi

# ─── Step 7: Done ─────────────────────────────────────────────────
echo ""
echo "============================================================"
echo "🚀 Setup Complete!"
echo "============================================================"
echo ""
echo "Next steps (from project root):"
echo "  ./sm init              # Auto-detect project, write config"
echo "  ./sm validate commit   # Run quality gates"
echo "  ./sm config --show     # Review configuration"
echo ""
