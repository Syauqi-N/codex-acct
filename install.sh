#!/usr/bin/env bash
# Install codex-acct by symlinking it into ~/.local/bin (or $BIN_DIR).
set -euo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="${BIN_DIR:-$HOME/.local/bin}"

mkdir -p "$BIN_DIR"

for f in codex-acct codex-acct-ws.js; do
  if [ ! -f "$SRC_DIR/$f" ]; then
    echo "error: $SRC_DIR/$f not found" >&2
    exit 1
  fi
  chmod +x "$SRC_DIR/$f"
  ln -sfn "$SRC_DIR/$f" "$BIN_DIR/$f"
  echo "linked $BIN_DIR/$f -> $SRC_DIR/$f"
done

# dependency checks
command -v python3 >/dev/null || echo "WARNING: python3 not found (required)"
command -v codex >/dev/null || echo "WARNING: codex not found (npm i -g @openai/codex)"
if command -v node >/dev/null; then
  major="$(node -p 'process.versions.node.split(".")[0]')"
  [ "$major" -ge 22 ] || echo "WARNING: node $major found, hot-switch needs Node 22+"
else
  echo "WARNING: node not found (only needed for serve/tui/switch/status)"
fi

case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) echo "WARNING: $BIN_DIR is not in \$PATH"
     echo "  add this to your shell rc: export PATH=\"$BIN_DIR:\$PATH\"" ;;
esac

echo
echo "done. try: codex-acct help"
