#!/usr/bin/env bash
# data/ 변경분을 커밋해 main에 올린다. (워크플로에서 호출)
#
# 예전에는 커밋 후 `git pull --rebase`로 붙여 올렸는데, 데이터 갱신 런과 사람이 올린
# 커밋이 겹치면 data/_diag.json 같은 파일에서 리베이스 충돌이 나고 detached HEAD로
# 남아 push가 실패했다(2026-11-20 23:14 KST 런). data/는 5분마다 통째로 다시 만드는
# 파일이라 병합할 이유가 없으므로, 방금 만든 데이터를 따로 보관했다가 최신 main 위에
# 그대로 얹고 올린다. 올리기가 실패하면 최신 main을 다시 받아 몇 번 더 시도한다.
set -uo pipefail

git config user.name "sports-bot"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"

MSG="data: $(TZ=Asia/Seoul date '+%Y-%m-%d %H:%M') KST 자동 갱신"

KEEP="$(mktemp -d)"
cp -a data/. "$KEEP"/

for try in 1 2 3 4 5; do
  git fetch --quiet origin main || { sleep 3; continue; }
  git reset --hard --quiet origin/main || exit 1

  rm -rf data
  mkdir -p data
  cp -a "$KEEP"/. data/

  git add -A data
  if git diff --cached --quiet; then
    echo "변경 없음"
    exit 0
  fi

  git commit --quiet -m "$MSG" || exit 1
  if git push --quiet origin HEAD:main; then
    echo "푸시 완료 (시도 $try)"
    exit 0
  fi
  echo "푸시 실패 — 최신 main을 다시 받아 재시도 ($try/5)"
  sleep 3
done

echo "data/ 푸시 실패: 여러 런이 겹쳤습니다. 다음 런에서 다시 시도합니다."
exit 1
