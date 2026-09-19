#!/usr/bin/env bash
# 한 줄 설치 · 업데이트
#   curl -fsSL https://raw.githubusercontent.com/Imperfective/floorplan-spacesyntax/main/deploy/install.sh | SITE_DOMAIN=sapcesyntax.com bash
#
# 두 번째부터는 같은 명령이 곧 업데이트다 (저장소를 당겨 다시 배포).
set -euo pipefail

SITE_DOMAIN="${SITE_DOMAIN:-sapcesyntax.com}"
WEBROOT="${WEBROOT:-/var/www/floorplan}"
REPO="${REPO:-https://github.com/Imperfective/floorplan-spacesyntax}"
SRC="${SRC:-/opt/floorplan-spacesyntax}"

[ "$(id -u)" -eq 0 ] || { echo "✗ root 로 실행하세요."; exit 1; }

say() { printf '\n\033[1;36m▸ %s\033[0m\n' "$*"; }

say "필요 패키지"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq git rsync curl ca-certificates >/dev/null

say "소스 받기 → $SRC"
if [ -d "$SRC/.git" ]; then
  git -C "$SRC" fetch -q --depth 1 origin main
  git -C "$SRC" reset -q --hard origin/main
  echo "   갱신: $(git -C "$SRC" log -1 --format='%h %s')"
else
  git clone -q --depth 1 "$REPO" "$SRC"
  echo "   복제: $(git -C "$SRC" log -1 --format='%h %s')"
fi

say "서버 설정"
SITE_DOMAIN="$SITE_DOMAIN" WEBROOT="$WEBROOT" bash "$SRC/deploy/setup-vps.sh"

say "사이트 파일 배포"
rsync -a --delete --chmod=D755,F644 "$SRC/docs/" "$WEBROOT/"
chown -R caddy:caddy "$WEBROOT" 2>/dev/null || true
echo "   $(find "$WEBROOT" -type f | wc -l)개 파일 · $(du -sh "$WEBROOT" | cut -f1)"
systemctl reload caddy 2>/dev/null || systemctl restart caddy

say "확인"
sleep 2
code=$(curl -s -o /dev/null -w '%{http_code}' -H "Host: $SITE_DOMAIN" http://127.0.0.1/ || echo 000)
echo "   로컬 HTTP(Host: $SITE_DOMAIN) → $code"
if command -v dig >/dev/null; then
  ip=$(dig +short A "$SITE_DOMAIN" | head -1)
  echo "   DNS A 레코드 → ${ip:-(없음)}"
else
  ip=$(getent hosts "$SITE_DOMAIN" | awk '{print $1}' | head -1)
  echo "   DNS → ${ip:-(없음)}"
fi

echo
if [ -z "${ip:-}" ]; then
  echo "⚠ DNS A 레코드가 아직 없습니다."
  echo "  Cloudflare에  A  @  $(curl -s -m 5 https://api.ipify.org || echo '<이 서버 IP>')  · Proxy: DNS only(회색 구름)"
  echo "  로 추가하면 Caddy가 1~2분 안에 인증서를 받습니다."
else
  echo "✓ https://$SITE_DOMAIN 을 열어 확인하세요."
  echo "  인증서가 아직이면 1~2분 뒤 다시, 그래도 안 되면:  journalctl -u caddy -n 40 --no-pager"
fi
echo
echo "다음부터 업데이트는 이 명령 한 줄:"
echo "  curl -fsSL $REPO/raw/main/deploy/install.sh | SITE_DOMAIN=$SITE_DOMAIN bash"
