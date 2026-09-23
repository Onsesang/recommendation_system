#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$APP_DIR/.." && pwd)"
LOG_FILE="$APP_DIR/server.log"
AUDIT_HOST="${AUDIT_HOST:-127.0.0.1}"
AUDIT_PORT="${AUDIT_PORT:-8765}"

if systemctl --user cat material-audit.service >/dev/null 2>&1; then
  systemctl --user start material-audit.service material-audit-watch.service
  echo "Started persistent user services at http://$AUDIT_HOST:$AUDIT_PORT"
  exit 0
fi

cd "$PROJECT_DIR"
nohup python -m audit_app.server --host "$AUDIT_HOST" --port "$AUDIT_PORT" >"$LOG_FILE" 2>&1 &
echo "Started fallback audit server (PID $!) at http://$AUDIT_HOST:$AUDIT_PORT"
