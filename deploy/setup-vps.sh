#!/usr/bin/env bash
# netcup VPS 최초 1회 설정 (Debian / Ubuntu)
#   사용:  SITE_DOMAIN=sapcesyntax.com sudo -E bash setup-vps.sh
#
# 이미 Caddy가 돌고 있어도 안전하다. 기존 Caddyfile을 덮어쓰지 않고
# conf.d/ 에 이 사이트 블록만 추가한다.
set -euo pipefail

: "${SITE_DOMAIN:?SITE_DOMAIN 이 필요합니다. 예: SITE_DOMAIN=sapcesyntax.com}"
WEBROOT="${WEBROOT:-/var/www/floorplan}"
HERE="$(cd "$(dirname "$0")" && pwd)"
CADDYFILE=/etc/caddy/Caddyfile
CONFD=/etc/caddy/conf.d
SITEFILE="$CONFD/${SITE_DOMAIN}.caddy"

echo "▸ 도메인 $SITE_DOMAIN · 웹루트 $WEBROOT"

if ! command -v caddy >/dev/null; then
  echo "▸ Caddy 설치"
  apt-get update -qq
  apt-get install -y -qq debian-keyring debian-archive-keyring apt-transport-https curl gnupg rsync
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
    | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  echo "deb [signed-by=/usr/share/keyrings/caddy-stable-archive-keyring.gpg] https://dl.cloudsmith.io/public/caddy/stable/deb/debian any-version main" \
    > /etc/apt/sources.list.d/caddy-stable.list
  apt-get update -qq && apt-get install -y -qq caddy
else
  echo "▸ Caddy 이미 설치됨: $(caddy version | head -1)"
  echo "   실행 설정: $(systemctl cat caddy 2>/dev/null | grep -m1 ExecStart= | sed 's/.*--config //;s/ .*//' || echo '(확인 불가)')"
fi
command -v rsync >/dev/null || apt-get install -y -qq rsync

echo "▸ 웹 루트 준비"
mkdir -p "$WEBROOT"
[ -f "$WEBROOT/index.html" ] || echo '<meta charset="utf-8"><p>배포 대기 중…' > "$WEBROOT/index.html"
chown -R caddy:caddy "$WEBROOT" 2>/dev/null || true

echo "▸ 기존 설정 백업"
if [ -f "$CADDYFILE" ]; then
  cp -a "$CADDYFILE" "$CADDYFILE.bak.$(date +%Y%m%d-%H%M%S)"
  echo "   $CADDYFILE → 백업함"
  echo "   현재 정의된 사이트:"
  grep -oE '^[a-zA-Z0-9*.:-]+[[:space:]]*\{' "$CADDYFILE" 2>/dev/null | sed 's/[[:space:]]*{//' | sed 's/^/     · /' || echo "     (없음)"
else
  mkdir -p /etc/caddy; : > "$CADDYFILE"
fi

echo "▸ 사이트 블록 설치: $SITEFILE"
mkdir -p "$CONFD"
sed -e "s|__DOMAIN__|$SITE_DOMAIN|g" -e "s|__WEBROOT__|$WEBROOT|g" \
    "$HERE/site.caddy.tpl" > "$SITEFILE"

if ! grep -qE '^\s*import\s+conf\.d/\*\.caddy' "$CADDYFILE"; then
  printf '\n# 사이트별 설정\nimport conf.d/*.caddy\n' >> "$CADDYFILE"
  echo "   Caddyfile 에 import 추가"
fi

echo "▸ 설정 검증"
caddy validate --config "$CADDYFILE" --adapter caddyfile

echo "▸ 방화벽 (설치되어 있으면)"
if command -v ufw >/dev/null; then
  ufw allow 22/tcp >/dev/null 2>&1 || true
  ufw allow 80/tcp >/dev/null 2>&1 || true
  ufw allow 443/tcp >/dev/null 2>&1 || true
fi

systemctl reload caddy 2>/dev/null || systemctl restart caddy
systemctl enable caddy >/dev/null 2>&1 || true

echo
echo "✓ 서버 준비 완료"
echo "  DNS( A $SITE_DOMAIN → 이 서버 )가 잡혀 있으면 Caddy가 곧 인증서를 받습니다."
echo "  다음: 로컬에서  DEPLOY_HOST=root@<IP> bash deploy/deploy.sh"
