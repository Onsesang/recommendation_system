#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PID_FILE="$PROJECT_ROOT/shopping_agent/server.pid"
UNIT_NAME="material-shopping-agent-v1.service"

if command -v systemctl >/dev/null 2>&1 && systemctl --user is-active --quiet "$UNIT_NAME"; then
  PID="$(systemctl --user show "$UNIT_NAME" --property=MainPID --value)"
  echo "active ($UNIT_NAME, PID $PID)"
  exit 0
fi

if [[ -f "$PID_FILE" ]] && kill -0 "$(<"$PID_FILE")" 2>/dev/null; then
  echo "active (PID $(<"$PID_FILE"))"
  exit 0
fi
echo "inactive"
exit 1
