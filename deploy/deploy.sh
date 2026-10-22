#!/usr/bin/env bash
# docs/ 를 VPS 웹 루트로 올린다 — GitHub Actions(.github/workflows/deploy.yml)와 같은 일을 로컬에서.
#   사용:  DEPLOY_HOST=minkyu@152.53.208.67 bash deploy/deploy.sh
#          (키 지정) SSH_KEY=~/.ssh/sapcesyntax_gha_deploy DEPLOY_HOST=... bash deploy/deploy.sh
#
# 기본 WEBROOT는 지금 서버 구성(Docker 컨테이너 deepvoice-caddy 의 /data/floorplan 마운트)이다.
# 호스트 Caddy로 새로 설치한 서버(install.sh)라면 WEBROOT=/var/www/floorplan 을 준다.
# 로컬에 rsync가 없어도 된다(윈도우 Git Bash) — tar로 보내고 서버의 rsync로 바꿔 넣는다.
set -euo pipefail

: "${DEPLOY_HOST:?DEPLOY_HOST 가 필요합니다. 예: DEPLOY_HOST=minkyu@152.53.208.67}"
WEBROOT="${WEBROOT:-/home/minkyu/deepvoice/caddy/data/floorplan}"
SRC="$(cd "$(dirname "$0")/.." && pwd)/docs"
SSH_OPTS=(-o BatchMode=yes)
[ -n "${SSH_KEY:-}" ] && SSH_OPTS+=(-i "$SSH_KEY")

# 엔진 캐시 무효화 — 워크플로와 같은 규칙(엔진 해시)을 임시 사본에 적용
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
cp -R "$SRC/." "$TMP/"
v=$(sha256sum "$TMP/aihub-engine.js" | cut -c1-12)
sed -i -E "s#aihub-engine\.js\?v=[^\"]*#aihub-engine.js?v=$v#" "$TMP/index.html"

echo "▸ $SRC  →  $DEPLOY_HOST:$WEBROOT  (engine v=$v)"
tar -C "$TMP" -cf - . | ssh "${SSH_OPTS[@]}" "$DEPLOY_HOST" "set -e
  T=\$(mktemp -d); tar -xf - -C \"\$T\"
  rsync -a --delete --chmod=D755,F644 \"\$T/\" '$WEBROOT/'
  rm -rf \"\$T\"
  # root로 올린 호스트 Caddy 설치본일 때만 소유자·설정을 손본다
  if [ \"\$(id -u)\" = 0 ] && id caddy >/dev/null 2>&1; then chown -R caddy:caddy '$WEBROOT'; systemctl reload caddy 2>/dev/null || true; fi
  ls -l '$WEBROOT'"
echo "✓ 배포 완료"
