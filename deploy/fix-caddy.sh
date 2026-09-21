#!/usr/bin/env bash
# 자동 HTTPS 복구:
#  (1) netcup 기본 :80 placeholder 제거  (2) 포트를 잡고 있는 stray caddy 정리
#  (3) systemd 로 깨끗하게 재시작  (4) 인증서 발급 확인
#   curl -fsSL https://github.com/Imperfective/floorplan-spacesyntax/raw/main/deploy/fix-caddy.sh -o fix.sh
#   sudo bash fix.sh
set -uo pipefail
[ "$(id -u)" -eq 0 ] || { echo "✗ root(sudo)로 실행하세요"; exit 1; }
CF=/etc/caddy/Caddyfile
say(){ printf '\n\033[1;36m▸ %s\033[0m\n' "$*"; }

say "Caddyfile 정리 (기본 placeholder 제거, conf.d import 유지)"
cp -a "$CF" "$CF.bak.$(date +%s)" 2>/dev/null || true
if grep -q '/usr/share/caddy' "$CF" 2>/dev/null || ! grep -qE 'import +conf\.d' "$CF" 2>/dev/null; then
  printf '# floorplan-spacesyntax\nimport conf.d/*.caddy\n' > "$CF"
fi
caddy validate --config "$CF" --adapter caddyfile 2>&1 | tail -3

say "포트를 잡고 있는 stray caddy 정리"
ss -tlnp 2>/dev/null | grep -E ':(80|443) ' | sed 's/^/   /' || true
systemctl stop caddy 2>/dev/null || true
# systemd 밖에서 도는 caddy 프로세스까지 모두 종료
if pgrep -x caddy >/dev/null; then
  echo "   caddy 프로세스 종료: $(pgrep -x caddy | tr '\n' ' ')"
  pkill -x caddy 2>/dev/null || true
  sleep 2
  pgrep -x caddy >/dev/null && { echo "   강제 종료"; pkill -9 -x caddy 2>/dev/null || true; sleep 2; }
fi
echo "   남은 caddy: $(pgrep -x caddy | tr '\n' ' ' || echo '없음')"

say "systemd 로 깨끗하게 시작"
systemctl reset-failed caddy 2>/dev/null || true
systemctl start caddy
sleep 2
echo "   상태: $(systemctl is-active caddy)"
systemctl is-active caddy | grep -q active || { echo "   ✗ 시작 실패:"; journalctl -u caddy -n 8 --no-pager | tail -8; exit 1; }

say "인증서 발급 대기 (최대 ~80초)"
ok=0
for i in $(seq 1 10); do
  sleep 8
  code=$(curl -sk -m 6 -o /dev/null -w '%{http_code}' --resolve sapcesyntax.com:443:127.0.0.1 https://sapcesyntax.com/ 2>/dev/null || echo 000)
  echo "   [$i] https(로컬) → $code"
  [ "$code" = "200" ] && { ok=1; break; }
done

say "최근 로그"
journalctl -u caddy -n 40 --no-pager 2>/dev/null | grep -iE 'sapcesyntax|acme|obtain|certificate|error|challenge' | tail -8

echo
[ "$ok" = 1 ] && echo "✓ 인증서 발급 완료 · https://sapcesyntax.com LIVE" \
             || echo "⚠ 아직 미발급 — 위 로그의 acme/error 줄을 확인하세요."
