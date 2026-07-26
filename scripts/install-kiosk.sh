#!/usr/bin/env bash
set -Eeuo pipefail

KIOSK_SERVICE="estacao-radio-kiosk"
KIOSK_SCRIPT="/usr/local/bin/estacao-radio-kiosk"
XORG_CONFIG="/etc/X11/xorg.conf.d/99-estacao-radio-fbdev.conf"

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
  xserver-xorg-video-fbdev \
  x11-xserver-utils \
  xinit \
  openbox \
  dbus-x11 \
  unclutter \
  "${BROWSER_PACKAGE}"

if [[ -e /dev/fb1 ]]; then
  FRAMEBUFFER_DEVICE="/dev/fb1"
else
  FRAMEBUFFER_DEVICE="/dev/fb0"
fi

mkdir -p /etc/X11/xorg.conf.d
cat >"${XORG_CONFIG}" <<EOF
Section "ServerLayout"
    Identifier "EstacaoRadioLayout"
    Screen 0 "EstacaoRadioScreen"
EndSection

Section "Device"
    Identifier "WaveshareFramebuffer"
    Driver "fbdev"
    Option "fbdev" "${FRAMEBUFFER_DEVICE}"
EndSection

Section "Screen"
    Identifier "EstacaoRadioScreen"
    Device "WaveshareFramebuffer"
EndSection
EOF

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
After=systemd-user-sessions.service estacao-radio-web.service network.target
Requires=estacao-radio-web.service
Conflicts=getty@tty1.service display-manager.service

[Service]
User=${TARGET_USER}
PAMName=login
TTYPath=/dev/tty1
StandardInput=tty
StandardOutput=journal
StandardError=journal
Environment=DISPLAY=:0
Environment=FRAMEBUFFER=${FRAMEBUFFER_DEVICE}
ExecStart=/usr/bin/startx ${KIOSK_SCRIPT} -- :0 vt1 -keeptty -nocursor
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload

# O quiosque inicia o próprio Xorg. Desliga o Raspberry Pi Desktop/LightDM
# para evitar que dois servidores gráficos disputem a tela :0.
systemctl disable --now display-manager.service 2>/dev/null || true
systemctl disable --now lightdm.service 2>/dev/null || true
systemctl set-default multi-user.target
systemctl enable --now "${KIOSK_SERVICE}"

echo
echo "Modo tela cheia instalado."
echo "A interface abrirá automaticamente no próximo início."
echo "Reinicie com: sudo reboot"
