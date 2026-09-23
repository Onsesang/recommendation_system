#!/usr/bin/env bash
# 체크포인트 복원 스크립트
#   사용법: ./checkpoints/fetch_checkpoints.sh [실험이름 ...]
#   인자 없으면 전체를 받습니다. 예: ./checkpoints/fetch_checkpoints.sh 24_adaptive_tactile_recommendation
# 요구사항: gh CLI 로그인 (저장소가 private이라 필요)
set -euo pipefail
REPO=Onsesang/recommendation_system
ROOT=$(cd "$(dirname "$0")/.." && pwd)
MAP="$ROOT/checkpoints/manifest.tsv"

want=("$@")
match() {
  [ ${#want[@]} -eq 0 ] && return 0
  for w in "${want[@]}"; do [ "$w" = "$1" ] && return 0; done
  return 1
}

tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
for tag in $(cut -f1 "$MAP" | sort -u); do
  match "$tag" || continue
  echo "==> ckpt-$tag 다운로드"
  gh release download "ckpt-$tag" -R "$REPO" -D "$tmp/$tag" --clobber

  while IFS=$'\t' read -r t size path; do
    [ "$t" = "$tag" ] || continue
    bn=$(basename "$path")
    dest="$ROOT/$path"
    mkdir -p "$(dirname "$dest")"
    if [ "$size" -gt 2000000000 ]; then
      cat "$tmp/$tag/$bn.part"* > "$dest"        # 분할본 병합
    else
      mv "$tmp/$tag/$bn" "$dest"
    fi
    echo "    $path"
  done < "$MAP"
done

echo "==> sha256 검증"
cd "$ROOT" && sha256sum -c --quiet checkpoints/sha256.txt 2>/dev/null | grep -v ': OK$' || true
echo "완료."
