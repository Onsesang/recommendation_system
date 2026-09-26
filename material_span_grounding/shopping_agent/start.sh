#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PID_FILE="$PROJECT_ROOT/shopping_agent/server.pid"
LOG_FILE="$PROJECT_ROOT/shopping_agent/server.log"
PYTHON_BIN="${SHOPPING_AGENT_PYTHON:-/home/user/onsesang/miniconda3/envs/texture/bin/python}"
UNIT_NAME="material-shopping-agent-v1.service"

# Prefer the user service manager so the demo survives a terminal/Codex session ending.
if command -v systemd-run >/dev/null 2>&1 && systemctl --user is-system-running >/dev/null 2>&1; then
  if systemctl --user is-active --quiet "$UNIT_NAME"; then
    PID="$(systemctl --user show "$UNIT_NAME" --property=MainPID --value)"
    echo "Shopping Agent is already running as $UNIT_NAME (PID $PID)."
    exit 0
  fi
  systemctl --user reset-failed "$UNIT_NAME" 2>/dev/null || true
  rm -f "$PID_FILE"
  systemd-run --user \
    --unit="$UNIT_NAME" \
    --collect \
    --property=Restart=on-failure \
    --property=RestartSec=3s \
    --working-directory="$PROJECT_ROOT" \
    "$PYTHON_BIN" -m shopping_agent.v1.server
  for _ in {1..50}; do
    if systemctl --user is-active --quiet "$UNIT_NAME"; then
      PID="$(systemctl --user show "$UNIT_NAME" --property=MainPID --value)"
      echo "$PID" >"$PID_FILE"
      echo "Shopping Agent started as $UNIT_NAME (PID $PID)."
      exit 0
    fi
    sleep 0.1
  done
  echo "Shopping Agent service failed to become active." >&2
  journalctl --user -u "$UNIT_NAME" -n 30 --no-pager >&2 || true
  exit 1
fi

if [[ -f "$PID_FILE" ]] && kill -0 "$(<"$PID_FILE")" 2>/dev/null; then
  echo "Shopping Agent is already running (PID $(<"$PID_FILE"))."
  exit 0
fi

cd "$PROJECT_ROOT"
nohup "$PYTHON_BIN" -m shopping_agent.v1.server >"$LOG_FILE" 2>&1 &
echo $! >"$PID_FILE"
echo "Shopping Agent started (PID $!, log $LOG_FILE)."
