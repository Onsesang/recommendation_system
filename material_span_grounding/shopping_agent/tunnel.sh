#!/usr/bin/env bash
# Expose the Shopping Agent demo through a Cloudflare Quick Tunnel.
#
# Quick Tunnels need no Cloudflare account, but the hostname is random and
# changes on every restart. After `start` or `restart`, read the new URL from
# `url` and add it to SHOPPING_AGENT_CORS_ORIGINS in shopping_agent/.env, then
# restart the agent so the Secure cookie keeps matching the public origin.
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
UNIT_NAME="material-agent-tunnel.service"
CLOUDFLARED="${CLOUDFLARED_BIN:-$HOME/.local/bin/cloudflared}"
TARGET="${TUNNEL_TARGET:-http://127.0.0.1:8878}"

usage() { echo "usage: $0 {start|stop|restart|status|url|logs}" >&2; exit 2; }

tunnel_url() {
  journalctl --user -u "$UNIT_NAME" --no-pager 2>/dev/null \
    | grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' | tail -1
}

case "${1:-status}" in
  start)
    if systemctl --user is-active --quiet "$UNIT_NAME"; then
      echo "Tunnel is already running: $(tunnel_url)"
      exit 0
    fi
    [[ -x "$CLOUDFLARED" ]] || { echo "cloudflared not found at $CLOUDFLARED" >&2; exit 1; }
    systemctl --user reset-failed "$UNIT_NAME" 2>/dev/null || true
    systemd-run --user \
      --unit="$UNIT_NAME" \
      --collect \
      --property=Restart=on-failure \
      --property=RestartSec=5s \
      --working-directory="$PROJECT_ROOT" \
      "$CLOUDFLARED" tunnel --no-autoupdate --url "$TARGET" >/dev/null
    for _ in {1..60}; do
      URL="$(tunnel_url)"
      if [[ -n "$URL" ]] && curl --silent --fail --max-time 10 "$URL/agent/v1/health" >/dev/null; then
        echo "Tunnel is live: $URL/agent-demo"
        exit 0
      fi
      sleep 2
    done
    echo "Tunnel did not become reachable. See: $0 logs" >&2
    exit 1
    ;;
  stop)
    systemctl --user stop "$UNIT_NAME" 2>/dev/null || true
    echo "Tunnel stopped."
    ;;
  restart) "$0" stop; sleep 2; "$0" start ;;
  status)
    if systemctl --user is-active --quiet "$UNIT_NAME"; then
      echo "active — $(tunnel_url)"
    else
      echo "inactive"
      exit 1
    fi
    ;;
  url) tunnel_url ;;
  logs) journalctl --user -u "$UNIT_NAME" -n 50 --no-pager ;;
  *) usage ;;
esac
