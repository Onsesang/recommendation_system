#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AUDIT_HOST="${AUDIT_HOST:-100.96.162.32}"
AUDIT_PORT="${AUDIT_PORT:-8765}"

if systemctl --user cat material-audit.service >/dev/null 2>&1; then
  echo "web=$(systemctl --user is-active material-audit.service)"
  echo "watcher=$(systemctl --user is-active material-audit-watch.service)"
  echo "web_b=$(systemctl --user is-active material-audit-b.service 2>/dev/null || true)"
  echo "watcher_b=$(systemctl --user is-active material-audit-watch-b.service 2>/dev/null || true)"
else
  echo "Persistent material audit service is not installed."
fi
curl -fsS "http://$AUDIT_HOST:$AUDIT_PORT/api/health"
echo
curl -fsS "http://$AUDIT_HOST:8766/api/health"
echo
