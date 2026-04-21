#!/usr/bin/env bash
# install.sh — install pymanager and add it to your PATH
#
# Usage:
#   ./install.sh          # install and add to PATH
#   ./install.sh --dry-run  # show what would be done without changing anything

set -euo pipefail

DRY_RUN=0
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=1

# ── Colors ───────────────────────────────────────────────────────────────────
if [[ -t 1 ]]; then
  GREEN='\033[32m'; YELLOW='\033[33m'; RED='\033[31m'; BOLD='\033[1m'; RESET='\033[0m'
else
  GREEN=''; YELLOW=''; RED=''; BOLD=''; RESET=''
fi

ok()   { echo -e "  ${GREEN}✅${RESET}  $*"; }
warn() { echo -e "  ${YELLOW}⚠${RESET}   $*"; }
err()  { echo -e "  ${RED}❌${RESET}  $*" >&2; }
info() { echo -e "  ${BOLD}→${RESET}  $*"; }

echo -e "\n${BOLD}🔧 pymanager installer${RESET}\n"

# ── Step 1: Check Python ─────────────────────────────────────────────────────
PYTHON=""
for candidate in python3 python; do
  if command -v "$candidate" &>/dev/null; then
    PYTHON="$candidate"
    PYTHON_VER=$("$candidate" --version 2>&1 | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1)
    break
  fi
done

if [[ -z "$PYTHON" ]]; then
  err "Python not found. Install Python 3.9+ from https://python.org and re-run."
  exit 1
fi
ok "Found $PYTHON ($PYTHON_VER)"

# ── Step 2: pip install ───────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
info "Installing pymanager from $SCRIPT_DIR..."

if [[ $DRY_RUN -eq 0 ]]; then
  "$PYTHON" -m pip install --user -e "$SCRIPT_DIR" --quiet --no-warn-script-location
  ok "pymanager installed"
else
  info "[dry-run] Would run: $PYTHON -m pip install --user -e $SCRIPT_DIR"
fi

# ── Step 3: Detect scripts directory ─────────────────────────────────────────
SCRIPTS_DIR=$("$PYTHON" - <<'EOF'
import sysconfig, sys

# Try --user scheme first (matches what pip --user does)
try:
    d = sysconfig.get_path("scripts", f"{os.name}_user" if hasattr(sysconfig, 'get_scheme_names') else "posix_user")
except Exception:
    d = None

# Fallback: ask pip directly
if not d or not d.strip():
    import subprocess, re
    r = subprocess.run(
        [sys.executable, "-m", "pip", "show", "pymanager"],
        capture_output=True, text=True
    )
    m = re.search(r"Location:\s*(.+)", r.stdout)
    if m:
        import pathlib
        loc = pathlib.Path(m.group(1).strip())
        # Typical layout: lib/pythonX.Y/site-packages → go up to get prefix
        # Then scripts is at the same level as lib
        d = str(loc.parent.parent.parent / "bin")

# Last resort: sysconfig posix_user
if not d:
    import os
    d = sysconfig.get_path("scripts", "posix_user")

print(d or "")
EOF
)

# Python snippet above may fail on older Pythons without 'os' imported — redo cleanly
SCRIPTS_DIR=$("$PYTHON" - <<'PYEOF'
import sysconfig, sys, os

schemes = sysconfig.get_scheme_names() if hasattr(sysconfig, "get_scheme_names") else []
user_scheme = next(
    (s for s in schemes if "user" in s and "home" not in s),
    "posix_user"
)

try:
    d = sysconfig.get_path("scripts", user_scheme)
except KeyError:
    d = sysconfig.get_path("scripts", "posix_user")

print(d or "")
PYEOF
)

if [[ -z "$SCRIPTS_DIR" ]]; then
  warn "Could not detect scripts directory. You may need to add pip's bin folder to PATH manually."
  warn "Run: pymanager setup-path   (once you can run pymanager)"
  exit 0
fi

ok "Scripts directory: $SCRIPTS_DIR"

# ── Step 4: Check if already on PATH ─────────────────────────────────────────
if echo "$PATH" | tr ':' '\n' | grep -qxF "$SCRIPTS_DIR"; then
  ok "$SCRIPTS_DIR is already on PATH — nothing to do."
  echo ""
  echo -e "  Run ${BOLD}pymanager --version${RESET} to verify.\n"
  exit 0
fi

# ── Step 5: Detect shell config file ─────────────────────────────────────────
SHELL_NAME=$(basename "${SHELL:-/bin/zsh}")
case "$SHELL_NAME" in
  zsh)   RC_FILE="$HOME/.zshrc" ;;
  bash)  RC_FILE="$HOME/.bash_profile" ;;
  fish)  RC_FILE="$HOME/.config/fish/config.fish" ;;
  *)     RC_FILE="$HOME/.profile" ;;
esac

info "Shell: $SHELL_NAME  →  config: $RC_FILE"

# ── Step 6: Add to PATH ───────────────────────────────────────────────────────
PATH_LINE='export PATH="'"$SCRIPTS_DIR"':$PATH"'

# fish uses a different syntax
if [[ "$SHELL_NAME" == "fish" ]]; then
  PATH_LINE="fish_add_path \"$SCRIPTS_DIR\""
fi

MARKER="# added by pymanager installer"

if grep -qF "$SCRIPTS_DIR" "$RC_FILE" 2>/dev/null; then
  ok "$SCRIPTS_DIR already present in $RC_FILE"
else
  if [[ $DRY_RUN -eq 0 ]]; then
    echo "" >> "$RC_FILE"
    echo "$MARKER" >> "$RC_FILE"
    echo "$PATH_LINE" >> "$RC_FILE"
    ok "Added to $RC_FILE:"
    echo -e "      ${BOLD}$PATH_LINE${RESET}"
  else
    info "[dry-run] Would append to $RC_FILE:"
    echo -e "      $MARKER"
    echo -e "      $PATH_LINE"
  fi
fi

# ── Step 7: Apply to current session ─────────────────────────────────────────
export PATH="$SCRIPTS_DIR:$PATH"

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}✅ pymanager is ready!${RESET}"
echo ""

if [[ $DRY_RUN -eq 0 ]]; then
  echo -e "  Reload your shell to pick up PATH changes:"
  echo -e "    ${BOLD}source $RC_FILE${RESET}"
  echo ""
  echo -e "  Or open a new terminal tab — then try:"
  echo -e "    ${BOLD}pymanager --version${RESET}"
  echo -e "    ${BOLD}pymanager pip install requests${RESET}"
fi
echo ""
