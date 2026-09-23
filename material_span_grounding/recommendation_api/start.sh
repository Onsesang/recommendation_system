#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PID_FILE="$APP_DIR/recommendation_api/server.pid"
LOG_FILE="$APP_DIR/recommendation_api/server.log"
HOST="${MATERIAL_API_HOST:-127.0.0.1}"
PORT="${MATERIAL_API_PORT:-8877}"

if [[ "$HOST" == "127.0.0.1" && "$PORT" == "8877" ]] \
  && systemctl --user show-environment >/dev/null 2>&1 \
  && [[ -f "$HOME/.config/systemd/user/material-recommendation.service" ]]; then
  rm -f "$PID_FILE"
  systemctl --user daemon-reload
  systemctl --user enable --now material-recommendation.service
  for _ in {1..30}; do
    if curl --silent --fail "http://127.0.0.1:8877/api/health" >/dev/null; then
      echo "Material recommendation API: http://127.0.0.1:8877"
      echo "Docs: http://127.0.0.1:8877/docs"
      echo "Managed by user systemd: material-recommendation.service"
      exit 0
    fi
    sleep 1
  done
  systemctl --user status material-recommendation.service --no-pager >&2 || true
  exit 1
fi

if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  echo "Material recommendation API is already running (PID $(cat "$PID_FILE"))."
  exit 0
fi

cd "$APP_DIR"
nohup conda run --no-capture-output -n texture python -m recommendation_api.server \
  --host "$HOST" --port "$PORT" >"$LOG_FILE" 2>&1 &
echo "$!" >"$PID_FILE"

for _ in {1..30}; do
  if curl --silent --fail "http://127.0.0.1:${PORT}/api/health" >/dev/null; then
    echo "Material recommendation API: http://${HOST}:${PORT}"
    echo "Docs: http://${HOST}:${PORT}/docs"
    exit 0
  fi
  sleep 1
done

echo "Server did not become healthy. Check $LOG_FILE" >&2
exit 1
