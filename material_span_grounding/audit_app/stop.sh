#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if systemctl --user cat material-audit.service >/dev/null 2>&1; then
  systemctl --user stop material-audit-watch.service material-audit.service
  echo "Stopped material audit user services."
  exit 0
fi

echo "Persistent material audit service is not installed."
