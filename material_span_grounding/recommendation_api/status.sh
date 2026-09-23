#!/usr/bin/env bash
set -euo pipefail
PORT="${MATERIAL_API_PORT:-8877}"
if systemctl --user is-active material-recommendation.service >/dev/null 2>&1; then
  systemctl --user status material-recommendation.service --no-pager --lines=3
fi
curl --fail --silent "http://127.0.0.1:${PORT}/api/health"
echo
