# 배포 키 등록

`deploy/authorized_key.pub` 는 이 저장소에서 서버로 배포할 때 쓰는 **공개키**입니다.
공개키는 공개되어도 안전합니다 — 짝이 되는 개인키를 가진 쪽만 접속할 수 있습니다.

## 서버에 등록하기

netcup SCP → **VNC 콘솔**로 root 로그인한 뒤 한 줄만 실행하세요.

```bash
mkdir -p /root/.ssh && chmod 700 /root/.ssh && \
curl -fsSL https://raw.githubusercontent.com/Imperfective/floorplan-spacesyntax/main/deploy/authorized_key.pub \
  >> /root/.ssh/authorized_keys && chmod 600 /root/.ssh/authorized_keys && echo OK
```

## 해지하기

```bash
sed -i '/deploy@sapcesyntax.com/d' /root/.ssh/authorized_keys
```

## 직접 배포하려면

키를 등록하지 않고 서버에서 바로 받아 배포해도 됩니다.

```bash
apt-get install -y git rsync
git clone https://github.com/Imperfective/floorplan-spacesyntax /tmp/fps
SITE_DOMAIN=sapcesyntax.com bash /tmp/fps/deploy/setup-vps.sh
rsync -a --delete /tmp/fps/docs/ /var/www/floorplan/
chown -R caddy:caddy /var/www/floorplan && systemctl reload caddy
```
