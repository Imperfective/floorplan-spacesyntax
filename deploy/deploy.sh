#!/usr/bin/env bash
# docs/ 를 VPS 웹 루트로 올린다.
#   사용:  DEPLOY_HOST=root@203.0.113.10 bash deploy/deploy.sh
set -euo pipefail

: "${DEPLOY_HOST:?DEPLOY_HOST 가 필요합니다. 예: DEPLOY_HOST=root@203.0.113.10}"
WEBROOT="${WEBROOT:-/var/www/floorplan}"
SRC="$(cd "$(dirname "$0")/.." && pwd)/docs/"

echo "▸ $SRC  →  $DEPLOY_HOST:$WEBROOT"
rsync -az --delete --human-readable --progress \
  --chmod=D755,F644 \
  "$SRC" "$DEPLOY_HOST:$WEBROOT/"

ssh "$DEPLOY_HOST" "chown -R caddy:caddy $WEBROOT 2>/dev/null || true; systemctl reload caddy 2>/dev/null || true"
echo "✓ 배포 완료"
