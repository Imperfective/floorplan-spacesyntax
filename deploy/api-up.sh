#!/usr/bin/env bash
# floorplan-api(로그인·활동 기록) 컨테이너를 띄운다 — 서버에서 실행. .github/workflows/deploy.yml 이 부른다.
#
#   API_DIR/app         server/floorplan-api 사본(워크플로가 rsync)
#   API_DIR/data        SQLite(허용 계정·세션·활동 기록) — 배포해도 지우지 않는다
#   API_DIR/google.env  GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET (워크플로가 GitHub 시크릿으로 씀, 600)
#
# 코드·설정이 그대로이고 컨테이너가 돌고 있으면 다시 띄우지 않는다.
set -euo pipefail
API_DIR=${API_DIR:-$HOME/deepvoice/floorplan-api}
ADMIN_EMAILS=${ADMIN_EMAILS:?ADMIN_EMAILS 필요}
PUBLIC_ORIGIN=${PUBLIC_ORIGIN:-https://sapcesyntax.com}
NETWORK=${NETWORK:-deepvoice-net}
IMAGE=${IMAGE:-node:22-slim}

mkdir -p "$API_DIR/data" "$API_DIR/app"
[ -f "$API_DIR/google.env" ] || : > "$API_DIR/google.env"
chmod 600 "$API_DIR/google.env"

want=$(cat "$API_DIR/app/server.mjs" "$API_DIR/google.env" <(echo "$ADMIN_EMAILS $PUBLIC_ORIGIN $IMAGE") | sha256sum | cut -c1-16)
have=$(cat "$API_DIR/.deployed" 2>/dev/null || true)
running=$(docker inspect -f '{{.State.Running}}' floorplan-api 2>/dev/null || echo false)
if [ "$want" = "$have" ] && [ "$running" = true ]; then
  echo "floorplan-api 그대로 ($want)"
else
  docker rm -f floorplan-api >/dev/null 2>&1 || true
  docker run -d --name floorplan-api --restart unless-stopped --network "$NETWORK" \
    --user "$(id -u):$(id -g)" --read-only --tmpfs /tmp --cap-drop ALL --security-opt no-new-privileges --memory 256m \
    --env-file "$API_DIR/google.env" -e ADMIN_EMAILS="$ADMIN_EMAILS" -e PUBLIC_ORIGIN="$PUBLIC_ORIGIN" -e DB_PATH=/data/floorplan-api.db \
    -v "$API_DIR/app:/app:ro" -v "$API_DIR/data:/data" -w /app "$IMAGE" node server.mjs >/dev/null
  echo "$want" > "$API_DIR/.deployed"
  echo "floorplan-api 다시 띄움 ($want)"
fi

for i in 1 2 3 4 5 6 7 8 9 10; do
  if out=$(docker exec floorplan-api node -e "fetch('http://127.0.0.1:8790/api/auth/config').then(r=>r.text()).then(t=>{console.log(t)})" 2>/dev/null) && [ -n "$out" ]; then
    echo "✓ /api/auth/config $out"; exit 0
  fi
  sleep 1
done
echo "floorplan-api 응답 없음" >&2; docker logs --tail 30 floorplan-api >&2 || true; exit 1
