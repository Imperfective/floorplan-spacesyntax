#!/usr/bin/env bash
# 콘솔에서 한 줄로: SSH 키 접속을 열고 + Caddy 인증서 상태를 진단·복구한다.
#   curl -fsSL https://github.com/Imperfective/floorplan-spacesyntax/raw/main/deploy/fix-access.sh | bash
set -uo pipefail
[ "$(id -u)" -eq 0 ] || { echo "✗ root 로 실행하세요 (sudo -i 후 재실행)"; exit 1; }
say(){ printf '\n\033[1;36m▸ %s\033[0m\n' "$*"; }

DEPLOYKEY='ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIA05WfGeXqeRCixGsvApyWEZtV0p6WQJqszFP5jn1pD2 deploy@sapcesyntax.com'

say "1) SSH 키 접속 열기"
mkdir -p /root/.ssh
# 배포키가 없으면 추가 (있으면 건너뜀)
grep -qF "$DEPLOYKEY" /root/.ssh/authorized_keys 2>/dev/null || echo "$DEPLOYKEY" >> /root/.ssh/authorized_keys
chmod 700 /root/.ssh
chmod 600 /root/.ssh/authorized_keys
chown -R root:root /root/.ssh
echo "   authorized_keys 줄 수: $(wc -l < /root/.ssh/authorized_keys)"

# root 키 로그인 허용 + 공개키 인증 on
SSHD=/etc/ssh/sshd_config
cp -a "$SSHD" "$SSHD.bak.$(date +%s)" 2>/dev/null || true
sed -i 's/^#*[[:space:]]*PermitRootLogin.*/PermitRootLogin prohibit-password/' "$SSHD"
grep -q '^PermitRootLogin' "$SSHD" || echo 'PermitRootLogin prohibit-password' >> "$SSHD"
sed -i 's/^#*[[:space:]]*PubkeyAuthentication.*/PubkeyAuthentication yes/' "$SSHD"
grep -q '^PubkeyAuthentication' "$SSHD" || echo 'PubkeyAuthentication yes' >> "$SSHD"
# drop-in 으로 확실히 덮어쓰기 (일부 배포판이 cloud-init 파일로 막음)
mkdir -p /etc/ssh/sshd_config.d
printf 'PermitRootLogin prohibit-password\nPubkeyAuthentication yes\n' > /etc/ssh/sshd_config.d/00-floorplan.conf
sshd -t 2>&1 && (systemctl restart ssh 2>/dev/null || systemctl restart sshd 2>/dev/null)
echo "   PermitRootLogin: $(sshd -T 2>/dev/null | grep -i '^permitrootlogin' || echo '?')"
echo "   PubkeyAuth     : $(sshd -T 2>/dev/null | grep -i '^pubkeyauthentication' || echo '?')"

say "2) Caddy 진단"
CFG=$(systemctl show -p ExecStart caddy 2>/dev/null | grep -oE -- '--config [^ ]+' | awk '{print $2}')
CFG=${CFG:-/etc/caddy/Caddyfile}
echo "   실행 설정 파일: $CFG"
echo "   웹루트 파일 수: $(find /var/www/floorplan -type f 2>/dev/null | wc -l)"
echo "   conf.d 목록   : $(ls /etc/caddy/conf.d/ 2>/dev/null | tr '\n' ' ')"
if [ -f "$CFG" ]; then
  echo "   설정에 sapcesyntax 포함: $(grep -l sapcesyntax "$CFG" /etc/caddy/conf.d/* 2>/dev/null | tr '\n' ' ' || echo '없음')"
  echo "   import conf.d 있음: $(grep -qE 'import +conf\.d' "$CFG" && echo yes || echo no)"
fi
echo "   --- caddy validate ---"
caddy validate --config "$CFG" --adapter caddyfile 2>&1 | tail -4

say "3) 재적용 + 인증서 재시도"
systemctl reload caddy 2>&1 || systemctl restart caddy 2>&1
sleep 12
code=$(curl -sk -m 8 -o /dev/null -w '%{http_code}' https://127.0.0.1/ -H 'Host: sapcesyntax.com' 2>/dev/null || echo 000)
echo "   로컬 HTTPS(Host: sapcesyntax.com) → $code"
echo "   --- 최근 Caddy 로그 (acme/error) ---"
journalctl -u caddy -n 40 --no-pager 2>/dev/null | grep -iE 'sapcesyntax|acme|obtain|error|certificate|challenge' | tail -8

say "완료"
echo "이제 로컬(Mac)에서 접속 가능해야 합니다. 위 3) 로그에 인증서 실패 사유가 있으면 그대로 보여주세요."
