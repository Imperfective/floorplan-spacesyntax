#!/usr/bin/env bash
# docs/ 를 서버 웹 루트로 올린다 — GitHub Actions(.github/workflows/deploy.yml)의 정적 파일 단계를 로컬에서.
#   사용:  SSH_KEY=~/.ssh/sapcesyntax_gha_deploy DEPLOY_HOST=minkyu@152.53.208.67 bash deploy/deploy.sh
#
# 웹 루트는 Docker 컨테이너 deepvoice-caddy 의 /data/floorplan 마운트다. 로그인·기록 API는 워크플로가 배포한다.
# 로컬에 rsync가 없어도 된다(윈도우 Git Bash) — tar로 보내고 서버의 rsync로 바꿔 넣는다.
set -euo pipefail

: "${DEPLOY_HOST:?DEPLOY_HOST 가 필요합니다. 예: DEPLOY_HOST=minkyu@152.53.208.67}"
WEBROOT="${WEBROOT:-/home/minkyu/deepvoice/caddy/data/floorplan}"
SRC="$(cd "$(dirname "$0")/.." && pwd)/docs"
SSH_OPTS=(-o BatchMode=yes)
[ -n "${SSH_KEY:-}" ] && SSH_OPTS+=(-i "$SSH_KEY")

# 캐시 무효화 — 워크플로와 같은 규칙(엔진·통계 js 내용 해시)을 임시 사본에 적용
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
cp -R "$SRC/." "$TMP/"
for f in aihub-engine aihub-stats; do
  v=$(sha256sum "$TMP/$f.js" | cut -c1-12)
  sed -i -E "s#$f\.js\?v=[^\"]*#$f.js?v=$v#" "$TMP/index.html"
done

echo "▸ $SRC  →  $DEPLOY_HOST:$WEBROOT"
tar -C "$TMP" -cf - . | ssh "${SSH_OPTS[@]}" "$DEPLOY_HOST" "set -e
  T=\$(mktemp -d); tar -xf - -C \"\$T\"
  rsync -a --delete --chmod=D755,F644 \"\$T/\" '$WEBROOT/'
  rm -rf \"\$T\""
echo "✓ 배포 완료"
