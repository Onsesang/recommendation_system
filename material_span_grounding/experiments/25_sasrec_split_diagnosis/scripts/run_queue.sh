#!/usr/bin/env bash
# Sequential GPU queue: each line of the given file is one train25.py argument list.
set -u
cd "$(dirname "$0")/.."
PY=~/miniconda3/envs/texture/bin/python
while read -r line; do
  [ -z "$line" ] && continue
  tag=$(echo "$line" | sed -n 's/.*--tag \([^ ]*\).*/\1/p')
  if [ -n "$tag" ] && [ -f "results/runs/$tag.json" ]; then echo "skip $tag"; continue; fi
  echo "=== $(date '+%F %T') $line"
  $PY scripts/train25.py $line > "logs/${tag:-run}.log" 2>&1 || echo "FAILED: $line"
  tail -3 "logs/${tag:-run}.log"
done < "$1"
echo "=== queue done $(date '+%F %T')"
