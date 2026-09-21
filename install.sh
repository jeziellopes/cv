#!/usr/bin/env bash
# cv install script
#   ./install.sh           install the package and Playwright chromium
#   ./install.sh --check   verify the install without changing anything
set -euo pipefail
cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3}"
BROWSERS="${PLAYWRIGHT_BROWSERS_PATH:-}"
DEFAULT_BROWSERS="$HOME/.cache/ms-playwright"

modules_ok() {
  "$PYTHON" -c "import generate, ats, search" 2>/dev/null
}

chromium_ok() {
  local dir="${BROWSERS:-$DEFAULT_BROWSERS}"
  [ -d "$dir" ] && [ -n "$(ls -d "$dir"/chromium-* 2>/dev/null | head -1)" ]
}

check() {
  local ok=1
  if modules_ok; then
    echo "ok  python modules import (generate, ats, search)"
  else
    echo "fail python modules missing (generate, ats, search): run ./install.sh" >&2
    ok=0
  fi
  if command -v cv >/dev/null 2>&1; then
    echo "ok  cv command on PATH ($(command -v cv))"
  else
    echo "fail cv command not found: run ./install.sh" >&2
    ok=0
  fi
  if chromium_ok; then
    echo "ok  chromium present (${BROWSERS:-$DEFAULT_BROWSERS})"
  else
    echo "fail chromium missing at (${BROWSERS:-$DEFAULT_BROWSERS}): run ./install.sh" >&2
    ok=0
  fi
  [ "$ok" -eq 1 ] || return 1
}

case "${1:-}" in
  --check)
    check
    ;;
  -h|--help)
    echo "usage: ./install.sh [--check]"
    echo "  (no args)  install the cv package and Playwright chromium"
    echo "  --check    verify the install without changing anything"
    ;;
  "")
    echo "== cv install =="
    if modules_ok; then
      echo "package already installed; reinstalling to register new modules (ats, search)"
    fi
    "$PYTHON" -m pip install -e . || "$PYTHON" -m pip install --user -e .
    echo "== playwright chromium =="
    "$PYTHON" -m playwright install chromium
    echo "== smoke test =="
    if modules_ok && command -v cv >/dev/null 2>&1; then
      echo "ok  cv is importable and on PATH"
    else
      echo "fail smoke test: cv not usable" >&2
      exit 1
    fi
    if [ -n "$BROWSERS" ]; then
      echo "note: PLAYWRIGHT_BROWSERS_PATH=$BROWSERS must stay exported when running 'cv generate --pdf'"
    fi
    echo "done. Next: cv generate --pdf"
    ;;
  *)
    echo "unknown option: $1" >&2
    echo "usage: ./install.sh [--check]" >&2
    exit 2
    ;;
esac