#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PID_FILE="$APP_DIR/recommendation_api/server.pid"
if systemctl --user is-active material-recommendation.service >/dev/null 2>&1; then
  systemctl --user stop material-recommendation.service
  echo "Material recommendation API stopped."
  exit 0
fi
if [[ ! -f "$PID_FILE" ]]; then
  echo "Material recommendation API is not running."
  exit 0
fi
PID="$(cat "$PID_FILE")"
if kill -0 "$PID" 2>/dev/null; then
  kill "$PID"
  for _ in {1..20}; do
    kill -0 "$PID" 2>/dev/null || break
    sleep 0.25
  done
fi
rm -f "$PID_FILE"
echo "Material recommendation API stopped."
