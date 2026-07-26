#!/usr/bin/env bash
set -Eeuo pipefail

KIOSK_SERVICE="estacao-radio-kiosk"
KIOSK_SCRIPT="/usr/local/bin/estacao-radio-kiosk"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Use: sudo ./scripts/install-kiosk.sh"
  exit 1
fi

if [[ -n "${SUDO_USER:-}" && "${SUDO_USER}" != "root" ]]; then
  TARGET_USER="${SUDO_USER}"
elif id pi >/dev/null 2>&1; then
  TARGET_USER="pi"
else
  echo "Não foi possível identificar o usuário da tela."
  echo "Execute novamente usando sudo a partir do seu usuário normal."
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update

if apt-cache show chromium >/dev/null 2>&1; then
  BROWSER_PACKAGE="chromium"
  BROWSER_COMMAND="/usr/bin/chromium"
elif apt-cache show chromium-browser >/dev/null 2>&1; then
  BROWSER_PACKAGE="chromium-browser"
  BROWSER_COMMAND="/usr/bin/chromium-browser"
else
  echo "O navegador Chromium não foi encontrado nos repositórios deste sistema."
  exit 1
fi

apt-get install -y \
  xserver-xorg \
  x11-xserver-utils \
  xinit \
  openbox \
  dbus-x11 \
  unclutter \
  "${BROWSER_PACKAGE}"

cat >"${KIOSK_SCRIPT}" <<EOF
#!/usr/bin/env bash
set -Eeuo pipefail

xset s off
xset -dpms
xset s noblank
unclutter -idle 0.2 -root &
openbox-session &

for attempt in \$(seq 1 30); do
  if python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5000/api/health', timeout=1)" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

exec ${BROWSER_COMMAND} \
  --kiosk \
  --app=http://127.0.0.1:5000 \
  --noerrdialogs \
  --disable-infobars \
  --disable-session-crashed-bubble \
  --disable-translate \
  --disable-dev-shm-usage \
  --overscroll-history-navigation=0
EOF

chmod +x "${KIOSK_SCRIPT}"

cat >"/etc/systemd/system/${KIOSK_SERVICE}.service" <<EOF
[Unit]
Description=Tela da Estação Rádio Web
After=systemd-user-sessions.service estacao-radio-web.service
Requires=estacao-radio-web.service
Conflicts=getty@tty1.service

[Service]
User=${TARGET_USER}
PAMName=login
TTYPath=/dev/tty1
StandardInput=tty
StandardOutput=journal
StandardError=journal
Environment=DISPLAY=:0
ExecStart=/usr/bin/startx ${KIOSK_SCRIPT} -- :0 vt1 -keeptty -nocursor
Restart=on-failure
RestartSec=5

[Install]
WantedBy=graphical.target
EOF

systemctl daemon-reload
systemctl set-default graphical.target
systemctl enable --now "${KIOSK_SERVICE}"

echo
echo "Modo tela cheia instalado."
echo "A interface abrirá automaticamente no próximo início."
echo "Reinicie com: sudo reboot"
