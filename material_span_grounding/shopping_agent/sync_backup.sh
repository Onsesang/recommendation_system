#!/usr/bin/env bash
# Mirror the backend code (and optionally data / .env) to the backup server, then
# restart its service and check that it answers.
#
#   ./shopping_agent/sync_backup.sh              # code only, restart, health check
#   ./shopping_agent/sync_backup.sh --dry-run    # list what would change, touch nothing
#   ./shopping_agent/sync_backup.sh --data       # also runtime data (configs/backup_data_files.txt)
#   ./shopping_agent/sync_backup.sh --env        # also shopping_agent/.env (API key; overwrites the
#                                                  # backup's own values such as its CORS origin)
#   ./shopping_agent/sync_backup.sh --test       # also run the unit tests on the backup server
#
# The user database (shopping_agent/data/*.sqlite3) is never copied here.
# Needs the `onsesang3060` ssh alias, which reaches the server through Tailscale.
set -euo pipefail

# Since 2026-09-26 the RTX 3060 is the main server and the A100 the fallback, and the A100
# still has the `onsesang3060` alias: run there, this script would overwrite the main
# server's code and restart it. The fallback pulls with pull_from_main.sh instead.
if [[ "${ALLOW_LEGACY_PUSH:-0}" != 1 ]]; then
  echo "sync_backup.sh is retired: on the fallback server run ./shopping_agent/pull_from_main.sh" >&2
  echo "(set ALLOW_LEGACY_PUSH=1 only if you really mean to push this machine's code to \$SYNC_HOST)" >&2
  exit 1
fi

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HOST="${SYNC_HOST:-onsesang3060}"
REMOTE_ROOT="${SYNC_REMOTE_ROOT:-onsesang/material_span_grounding}"
REMOTE_PYTHON="${SYNC_REMOTE_PYTHON:-\$HOME/miniconda3/envs/shopping_backend/bin/python}"
REMOTE_UNIT="${SYNC_REMOTE_UNIT:-shopping-agent.service}"
DATA_LIST="$PROJECT_ROOT/shopping_agent/configs/backup_data_files.txt"
TAILSCALE_SOCKET="$HOME/.local/share/tailscale/tailscaled.sock"

CODE_DIRS=(shopping_agent recommendation_api demo_agent material_span configs notion)
EXCLUDES=(
  --exclude=__pycache__ --exclude='*.pyc' --exclude=.pytest_cache
  --exclude=.env --exclude='shopping_agent/data/*.sqlite3*'
  --exclude=shopping_agent/traces/ --exclude='*.log' --exclude='*.pid'
)

DRY_RUN=0 WITH_DATA=0 WITH_ENV=0 WITH_TEST=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    --data) WITH_DATA=1 ;;
    --env) WITH_ENV=1 ;;
    --test) WITH_TEST=1 ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

cd "$PROJECT_ROOT"

# This server joins the tailnet in userspace mode through a transient unit, which does
# not survive a reboot. Start it again when the daemon is not answering.
TAILSCALE="$HOME/.local/bin/tailscale"
if [[ -x "$TAILSCALE" ]] && ! "$TAILSCALE" --socket="$TAILSCALE_SOCKET" status >/dev/null 2>&1; then
  echo "starting tailscaled (userspace)"
  systemctl --user reset-failed tailscaled-userspace.service 2>/dev/null || true
  systemd-run --user --unit=tailscaled-userspace --property=Restart=on-failure \
    "$HOME/.local/bin/tailscaled" --tun=userspace-networking --socks5-server=localhost:1055 \
    --state="$HOME/.local/share/tailscale/tailscaled.state" --socket="$TAILSCALE_SOCKET" >/dev/null
  for _ in {1..20}; do
    "$TAILSCALE" --socket="$TAILSCALE_SOCKET" status >/dev/null 2>&1 && break
    sleep 1
  done
fi
if ! ssh -o BatchMode=yes -o ConnectTimeout=15 "$HOST" true 2>/dev/null; then
  echo "cannot reach $HOST over ssh (check Tailscale and ~/.ssh/config)" >&2
  exit 1
fi

RSYNC=(rsync -a --checksum --itemize-changes)
(( DRY_RUN )) && RSYNC+=(--dry-run)

changes() { grep -v '/$' | grep -v '^$' || true; }

echo "== code -> $HOST:$REMOTE_ROOT"
CODE_CHANGES="$("${RSYNC[@]}" "${EXCLUDES[@]}" "${CODE_DIRS[@]}" "$HOST:$REMOTE_ROOT/" | changes)"
echo "${CODE_CHANGES:-(no changes)}"

if (( WITH_DATA )); then
  echo "== data"
  DATA_CHANGES="$(grep -v '^#' "$DATA_LIST" | grep . \
    | "${RSYNC[@]}" --partial --relative --files-from=- --recursive . "$HOST:$REMOTE_ROOT/" | changes)"
  echo "${DATA_CHANGES:-(no changes)}"
fi

if (( WITH_ENV )); then
  echo "== .env"
  "${RSYNC[@]}" --chmod=F600 shopping_agent/.env "$HOST:$REMOTE_ROOT/shopping_agent/.env" | changes
fi

if (( DRY_RUN )); then
  echo "dry run: nothing copied, service not restarted"
  exit 0
fi

if (( WITH_TEST )); then
  echo "== tests on $HOST"
  for suite in shopping_agent/v1/tests recommendation_api/tests; do
    # Keep the running service untouched when the synced code fails its tests there.
    if ! ssh -o BatchMode=yes "$HOST" "cd $REMOTE_ROOT && ONSESANG_ROOT=\$HOME/onsesang \
        $REMOTE_PYTHON -m unittest discover -s $suite -t . > /tmp/sync_backup_test.log 2>&1"; then
      echo "$suite: FAILED — service not restarted" >&2
      ssh -o BatchMode=yes "$HOST" "grep -E '^(ERROR|FAIL):' /tmp/sync_backup_test.log | head -10" >&2 || true
      exit 1
    fi
    echo "$suite: OK"
  done
fi

echo "== restart $REMOTE_UNIT"
ssh -o BatchMode=yes "$HOST" "systemctl --user restart $REMOTE_UNIT"
for _ in {1..30}; do
  HEALTH="$(ssh -o BatchMode=yes "$HOST" \
    "curl -fsS --max-time 3 http://127.0.0.1:8878/agent/v1/health" 2>/dev/null || true)"
  [[ -n "$HEALTH" ]] && break
  sleep 1
done
if [[ -z "$HEALTH" ]]; then
  echo "backup service did not answer /agent/v1/health" >&2
  ssh -o BatchMode=yes "$HOST" "journalctl --user -u $REMOTE_UNIT -n 20 --no-pager" >&2 || true
  exit 1
fi
python3 -c 'import json,sys; h=json.loads(sys.argv[1]); print("health:", h["status"], "| products", h.get("catalog_products"), "| llm", h["llm"]["provider"], h["llm"]["model"], "| agent", h["features"].get("agent_mode"))' "$HEALTH"

REMAINING="$(rsync -a --checksum --itemize-changes --dry-run "${EXCLUDES[@]}" "${CODE_DIRS[@]}" "$HOST:$REMOTE_ROOT/" | changes | wc -l)"
echo "code files still different: $REMAINING"
[[ "$REMAINING" == 0 ]]
