#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PID_FILE="$PROJECT_ROOT/shopping_agent/server.pid"
UNIT_NAME="material-shopping-agent-v1.service"

if command -v systemctl >/dev/null 2>&1 && systemctl --user is-active --quiet "$UNIT_NAME"; then
  systemctl --user stop "$UNIT_NAME"
  rm -f "$PID_FILE"
  echo "Shopping Agent service stopped."
  exit 0
fi

if [[ ! -f "$PID_FILE" ]]; then
  echo "Shopping Agent is not running."
  exit 0
fi
PID="$(<"$PID_FILE")"
if kill -0 "$PID" 2>/dev/null; then
  kill "$PID"
  wait "$PID" 2>/dev/null || true
fi
rm -f "$PID_FILE"
echo "Shopping Agent stopped."
