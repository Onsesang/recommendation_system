#!/usr/bin/env bash
# Run on the fallback server (A100): pull the backend from the main server (RTX 3060),
# test it, restart the local service and check that it answers. Nothing is ever sent to
# the main server except a read-only DB snapshot request (--db).
#
#   ./shopping_agent/pull_from_main.sh              # code only, core tests, restart, health check
#   ./shopping_agent/pull_from_main.sh --dry-run    # list what would change, touch nothing
#   ./shopping_agent/pull_from_main.sh --data       # also runtime data (configs/backup_data_files.txt)
#   ./shopping_agent/pull_from_main.sh --env        # also shopping_agent/.env (API keys, CORS)
#   ./shopping_agent/pull_from_main.sh --db         # also replace the local user DB with a snapshot
#                                                   # of the main DB (accounts, chats, carts)
#   ./shopping_agent/pull_from_main.sh --no-test    # skip the tests
#   ./shopping_agent/pull_from_main.sh --db-only    # only the DB snapshot, no code, no tests
#                                                   # (what the 10-minute timer runs)
#
# Needs the `onsesang3060` ssh alias (main server through Tailscale). The old
# sync_backup.sh pushes the other way; do not run that one on this server.
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HOST="${MAIN_HOST:-onsesang3060}"
REMOTE_ROOT="${MAIN_REMOTE_ROOT:-onsesang/material_span_grounding}"
REMOTE_PYTHON="${MAIN_REMOTE_PYTHON:-\$HOME/miniconda3/envs/shopping_backend/bin/python}"
PYTHON="${LOCAL_PYTHON:-$HOME/onsesang/miniconda3/envs/shopping_backend/bin/python}"
UNIT="${LOCAL_UNIT:-shopping-agent.service}"
DB_PATH="shopping_agent/data/agent_v1.sqlite3"
REMOTE_SNAPSHOT="shopping_agent/data/.snapshot_for_fallback.sqlite3"
# Content hash of the last snapshot applied here; an identical snapshot is not applied again.
LAST_SNAPSHOT_HASH="shopping_agent/data/.last_snapshot.sha256"

CODE_DIRS=(shopping_agent recommendation_api demo_agent material_span configs notion)
EXCLUDES=(
  --exclude=__pycache__ --exclude='*.pyc' --exclude=.pytest_cache
  --exclude=.env --exclude='shopping_agent/data/*.sqlite3*' --exclude='shopping_agent/data/.snapshot*'
  --exclude=shopping_agent/traces/ --exclude='*.log' --exclude='*.pid'
)
# Suites that need only the runtime data; evaluation-tool tests need data the fallback lacks.
TESTS=(
  shopping_agent.v1.tests.test_agent_api shopping_agent.v1.tests.test_tool_agent
  shopping_agent.v1.tests.test_full_catalog shopping_agent.v1.tests.test_auth_database
  shopping_agent.v1.tests.test_rate_limit shopping_agent.v1.tests.test_routing
  shopping_agent.v1.tests.test_llm shopping_agent.v1.tests.test_tactile_phrases
)

DRY_RUN=0 WITH_CODE=1 WITH_DATA=0 WITH_ENV=0 WITH_DB=0 WITH_TEST=1 DB_CHANGED=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    --data) WITH_DATA=1 ;;
    --env) WITH_ENV=1 ;;
    --db) WITH_DB=1 ;;
    --no-test) WITH_TEST=0 ;;
    --db-only) WITH_CODE=0 WITH_DB=1 WITH_TEST=0 ;;
    -h|--help) sed -n '2,17p' "$0"; exit 0 ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

cd "$PROJECT_ROOT"
if ! ssh -o BatchMode=yes -o ConnectTimeout=15 "$HOST" true 2>/dev/null; then
  # Main unreachable (e.g. it is down and this server is serving): keep everything as it is.
  echo "cannot reach $HOST over ssh; nothing changed" >&2
  exit 1
fi

RSYNC=(rsync -a --checksum --itemize-changes)
(( DRY_RUN )) && RSYNC+=(--dry-run)
changes() { grep -v '/$' | grep -v '^$' || true; }

if (( WITH_CODE )); then
  echo "== code <- $HOST:$REMOTE_ROOT"
  SOURCES=()
  for dir in "${CODE_DIRS[@]}"; do SOURCES+=("$HOST:$REMOTE_ROOT/$dir"); done
  CODE_CHANGES="$("${RSYNC[@]}" "${EXCLUDES[@]}" "${SOURCES[@]}" ./ | changes)"
  echo "${CODE_CHANGES:-(no changes)}"
fi

if (( WITH_DATA )); then
  echo "== data"
  DATA_CHANGES="$(grep -v '^#' shopping_agent/configs/backup_data_files.txt | grep . \
    | "${RSYNC[@]}" --partial --relative --recursive --files-from=- "$HOST:$REMOTE_ROOT/" ./ | changes)"
  echo "${DATA_CHANGES:-(no changes)}"
fi

if (( WITH_ENV )); then
  echo "== .env"
  "${RSYNC[@]}" --chmod=F600 "$HOST:$REMOTE_ROOT/shopping_agent/.env" shopping_agent/.env | changes
fi

if (( DRY_RUN )); then
  echo "dry run: nothing copied, service not restarted"
  exit 0
fi

if (( WITH_TEST )); then
  echo "== tests"
  if ! ONSESANG_ROOT="$HOME/onsesang" "$PYTHON" -m unittest "${TESTS[@]}" > /tmp/pull_from_main_test.log 2>&1; then
    echo "tests FAILED; service not restarted (log: /tmp/pull_from_main_test.log)" >&2
    grep -E '^(ERROR|FAIL):' /tmp/pull_from_main_test.log | head -10 >&2 || true
    exit 1
  fi
  tail -1 /tmp/pull_from_main_test.log
fi

if (( WITH_DB )); then
  echo "== db snapshot <- $HOST ($(date '+%F %T'))"
  # sqlite's backup API gives a consistent copy while the main service keeps writing.
  ssh -o BatchMode=yes "$HOST" "cd $REMOTE_ROOT && $REMOTE_PYTHON -c \"
import sqlite3
src = sqlite3.connect('file:$DB_PATH?mode=ro', uri=True)
dst = sqlite3.connect('$REMOTE_SNAPSHOT')
src.backup(dst); dst.close(); src.close()\""
  rsync -a "$HOST:$REMOTE_ROOT/$REMOTE_SNAPSHOT" "$DB_PATH.incoming"
  ssh -o BatchMode=yes "$HOST" "rm -f ${REMOTE_ROOT:?}/${REMOTE_SNAPSHOT:?}"
  # Hash the SQL dump rather than the file: the same rows can be laid out in different pages.
  INCOMING_HASH="$("$PYTHON" -c "
import hashlib, sqlite3, sys
c = sqlite3.connect(sys.argv[1])
assert c.execute('pragma integrity_check').fetchone()[0] == 'ok', 'snapshot failed integrity_check'
h = hashlib.sha256()
for line in c.iterdump():
    h.update(line.encode()); h.update(b'\\n')
print(h.hexdigest())" "$DB_PATH.incoming")"
  if [[ -f "$DB_PATH" && -f "$LAST_SNAPSHOT_HASH" && "$(cat "$LAST_SNAPSHOT_HASH")" == "$INCOMING_HASH" ]]; then
    rm -f "$DB_PATH.incoming"
    echo "db unchanged since the last copy; kept as is"
  else
    DB_CHANGED=1
    systemctl --user stop "$UNIT"
    trap 'systemctl --user start "$UNIT"' EXIT  # never leave the service stopped on an error
    [[ -f "$DB_PATH" ]] && cp -p "$DB_PATH" "$DB_PATH.before-pull"
    rm -f "$DB_PATH-wal" "$DB_PATH-shm"
    mv "$DB_PATH.incoming" "$DB_PATH"
    echo "$INCOMING_HASH" > "$LAST_SNAPSHOT_HASH"
    echo "db replaced (previous copy: $DB_PATH.before-pull)"
  fi
fi

if (( ! WITH_CODE && ! WITH_DATA && ! WITH_ENV && ! DB_CHANGED )); then
  echo "nothing changed; $UNIT not restarted"
  exit 0
fi

echo "== restart $UNIT"
systemctl --user restart "$UNIT"
HEALTH=""
for _ in {1..60}; do
  HEALTH="$(curl -fsS --max-time 3 http://127.0.0.1:8878/agent/v1/health 2>/dev/null || true)"
  [[ -n "$HEALTH" ]] && break
  sleep 1
done
if [[ -z "$HEALTH" ]]; then
  echo "service did not answer /agent/v1/health" >&2
  journalctl --user -u "$UNIT" -n 20 --no-pager >&2 || true
  exit 1
fi
"$PYTHON" -c 'import json,sys; h=json.loads(sys.argv[1]); print("health:", h["status"], "| products", h.get("catalog_products"), "| llm", h["llm"]["model"], "| agent", h["features"].get("agent_mode"))' "$HEALTH"
