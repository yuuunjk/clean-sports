#!/usr/bin/env bash
# data/ 변경분을 커밋해 main에 올린다. (워크플로에서 호출)
set -euo pipefail

git config user.name "sports-bot"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"

git add data

if git diff --cached --quiet; then
  echo "변경 없음"
  exit 0
fi

git commit -m "data: $(TZ=Asia/Seoul date '+%Y-%m-%d %H:%M') KST 자동 갱신"
# 다른 커밋이 먼저 올라와 있으면 붙여서 다시 올린다
git pull --rebase --autostash --quiet || true
git push
