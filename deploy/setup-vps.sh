#!/usr/bin/env bash
# netcup VPS 최초 1회 설정 (Debian / Ubuntu 기준)
#   사용:  SITE_DOMAIN=example.com sudo -E bash setup-vps.sh
set -euo pipefail

: "${SITE_DOMAIN:?SITE_DOMAIN 환경변수가 필요합니다. 예: SITE_DOMAIN=example.com}"
WEBROOT=/var/www/floorplan

echo "▸ 패키지 갱신"
apt-get update -qq
apt-get install -y -qq debian-keyring debian-archive-keyring apt-transport-https curl rsync ufw

echo "▸ Caddy 설치"
if ! command -v caddy >/dev/null; then
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
    | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
    > /etc/apt/sources.list.d/caddy-stable.list
  apt-get update -qq
  apt-get install -y -qq caddy
fi

echo "▸ 웹 루트 준비: $WEBROOT"
mkdir -p "$WEBROOT"
chown -R caddy:caddy "$WEBROOT"

echo "▸ 도메인 설정: $SITE_DOMAIN"
mkdir -p /etc/caddy
grep -q '^SITE_DOMAIN=' /etc/default/caddy 2>/dev/null \
  && sed -i "s|^SITE_DOMAIN=.*|SITE_DOMAIN=$SITE_DOMAIN|" /etc/default/caddy \
  || echo "SITE_DOMAIN=$SITE_DOMAIN" >> /etc/default/caddy
# systemd 유닛이 /etc/default/caddy 를 읽도록 보강
mkdir -p /etc/systemd/system/caddy.service.d
cat > /etc/systemd/system/caddy.service.d/override.conf <<UNIT
[Service]
EnvironmentFile=/etc/default/caddy
UNIT
systemctl daemon-reload

echo "▸ 방화벽 (22, 80, 443)"
ufw allow 22/tcp  >/dev/null 2>&1 || true
ufw allow 80/tcp  >/dev/null 2>&1 || true
ufw allow 443/tcp >/dev/null 2>&1 || true
ufw --force enable >/dev/null 2>&1 || true

echo "▸ Caddyfile 배치"
install -m 644 "$(dirname "$0")/Caddyfile" /etc/caddy/Caddyfile
caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile --envfile /etc/default/caddy || true
systemctl enable --now caddy
systemctl reload caddy || systemctl restart caddy

echo
echo "✓ 서버 준비 완료"
echo "  다음: 로컬에서  SITE_DOMAIN=$SITE_DOMAIN DEPLOY_HOST=사용자@서버주소 bash deploy/deploy.sh"
