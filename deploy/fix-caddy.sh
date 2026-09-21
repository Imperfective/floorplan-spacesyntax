#!/usr/bin/env bash
# 기존 Caddyfile 의 기본 :80 placeholder 블록을 제거해 자동 HTTPS 충돌을 푼다.
#   curl -fsSL https://github.com/Imperfective/floorplan-spacesyntax/raw/main/deploy/fix-caddy.sh -o fix.sh
#   sudo bash fix.sh
set -uo pipefail
[ "$(id -u)" -eq 0 ] || { echo "✗ root(sudo)로 실행하세요"; exit 1; }
CF=/etc/caddy/Caddyfile
say(){ printf '\n\033[1;36m▸ %s\033[0m\n' "$*"; }

say "기존 Caddyfile 백업"
cp -a "$CF" "$CF.bak.$(date +%s)" && echo "   $CF.bak.* 저장"

say "기본 placeholder(:80 → /usr/share/caddy) 제거, conf.d import만 유지"
cat > "$CF" <<'CADDY'
# floorplan-spacesyntax: 사이트 설정은 conf.d/ 에 있다.
# (netcup 기본 ':80 → /usr/share/caddy' placeholder 는 자동 HTTPS 를 방해해 제거함)
import conf.d/*.caddy
CADDY

say "설정 검증"
caddy validate --config "$CF" --adapter caddyfile 2>&1 | tail -4 || {
  echo "✗ 검증 실패 — 백업으로 되돌립니다"; cp -a "$(ls -t $CF.bak.* | head -1)" "$CF"; exit 1; }

say "reload + 인증서 발급 대기"
systemctl reload caddy 2>&1 || systemctl restart caddy 2>&1
for i in $(seq 1 10); do
  sleep 7
  code=$(curl -sk -m 6 -o /dev/null -w '%{http_code}' https://sapcesyntax.com/ --resolve sapcesyntax.com:443:127.0.0.1 2>/dev/null || echo 000)
  echo "   [$i] https://sapcesyntax.com (로컬) → $code"
  [ "$code" = "200" ] && { echo; echo "✓ 인증서 발급 완료 · 사이트 LIVE"; break; }
done

say "최근 Caddy 로그"
journalctl -u caddy -n 30 --no-pager 2>/dev/null | grep -iE 'sapcesyntax|acme|obtain|certificate|error|challenge' | tail -8
echo
echo "이제 https://sapcesyntax.com 을 브라우저에서 확인하세요."
