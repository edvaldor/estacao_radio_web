#!/usr/bin/env bash
set -Eeuo pipefail

KIOSK_SERVICE="estacao-radio-kiosk"
KIOSK_SCRIPT="/usr/local/bin/estacao-radio-kiosk"
XORG_CONFIG="/etc/X11/xorg.conf.d/99-estacao-radio-fbdev.conf"
XWRAPPER_CONFIG="/etc/X11/Xwrapper.config"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Use: sudo bash scripts/install-kiosk.sh"
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

TARGET_UID="$(id -u "${TARGET_USER}")"
TARGET_HOME="$(getent passwd "${TARGET_USER}" | cut -d: -f6)"

export DEBIAN_FRONTEND=noninteractive
if [[ "${SKIP_APT:-0}" != "1" ]]; then
  apt-get update
fi

if apt-cache show chromium >/dev/null 2>&1; then
  BROWSER_PACKAGE="chromium"
elif apt-cache show chromium-browser >/dev/null 2>&1; then
  BROWSER_PACKAGE="chromium-browser"
else
  echo "O navegador Chromium não foi encontrado nos repositórios deste sistema."
  exit 1
fi

REQUIRED_PACKAGES=(
  xserver-xorg
  xserver-xorg-legacy
  xserver-xorg-video-fbdev
  x11-xserver-utils
  xinit
  openbox
  dbus-x11
  unclutter
  "${BROWSER_PACKAGE}"
)
MISSING_PACKAGES=()
for package in "${REQUIRED_PACKAGES[@]}"; do
  if ! dpkg-query -W -f='${Status}' "${package}" 2>/dev/null \
      | grep -q 'install ok installed'; then
    MISSING_PACKAGES+=("${package}")
  fi
done
if [[ "${#MISSING_PACKAGES[@]}" -gt 0 ]]; then
  echo "Instalando componentes ausentes do quiosque..."
  apt-get install -y "${MISSING_PACKAGES[@]}"
fi

if command -v chromium >/dev/null 2>&1; then
  BROWSER_COMMAND="$(command -v chromium)"
elif command -v chromium-browser >/dev/null 2>&1; then
  BROWSER_COMMAND="$(command -v chromium-browser)"
else
  echo "Chromium não instalado. Rode sem SKIP_APT ou instale o pacote chromium."
  exit 1
fi

if [[ -e /dev/fb1 ]]; then
  FRAMEBUFFER_DEVICE="/dev/fb1"
elif [[ -e /dev/fb0 ]]; then
  FRAMEBUFFER_DEVICE="/dev/fb0"
else
  echo "Nenhum framebuffer foi encontrado (/dev/fb0 ou /dev/fb1)."
  echo "Confira o overlay da tela no config.txt e reinicie o Raspberry Pi."
  exit 1
fi

for group in video input render; do
  if getent group "${group}" >/dev/null 2>&1; then
    usermod -a -G "${group}" "${TARGET_USER}"
  fi
done

mkdir -p /etc/X11/xorg.conf.d
cat >"${XWRAPPER_CONFIG}" <<'EOF'
# A tela SPI usa fbdev legado e precisa que o Xorg mantenha privilégios.
allowed_users=console
needs_root_rights=yes
EOF

cat >"${XORG_CONFIG}" <<EOF
Section "ServerFlags"
    Option "AutoAddGPU" "false"
EndSection

Section "ServerLayout"
    Identifier "EstacaoRadioLayout"
    Screen 0 "EstacaoRadioScreen"
EndSection

Section "Device"
    Identifier "WaveshareFramebuffer"
    Driver "fbdev"
    Option "fbdev" "${FRAMEBUFFER_DEVICE}"
    Option "ShadowFB" "true"
EndSection

Section "Screen"
    Identifier "EstacaoRadioScreen"
    Device "WaveshareFramebuffer"
EndSection
EOF

install -d -o "${TARGET_USER}" -g "$(id -gn "${TARGET_USER}")" \
  "${TARGET_HOME}/.config/estacao-radio-kiosk"

cat >"${KIOSK_SCRIPT}" <<EOF
#!/usr/bin/env bash
set -Eeuo pipefail

export DISPLAY=:0
export HOME=${TARGET_HOME}
export XDG_RUNTIME_DIR=/run/user/${TARGET_UID}

xsetroot -solid black
xset s off
xset -dpms
xset s noblank
unclutter -idle 0.2 -root &

if command -v dbus-launch >/dev/null 2>&1; then
  eval "\$(dbus-launch --sh-syntax)"
fi
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
  --ozone-platform=x11 \
  --disable-gpu \
  --noerrdialogs \
  --no-first-run \
  --no-default-browser-check \
  --disable-infobars \
  --disable-session-crashed-bubble \
  --disable-translate \
  --disable-dev-shm-usage \
  --disable-pinch \
  --password-store=basic \
  --user-data-dir=${TARGET_HOME}/.config/estacao-radio-kiosk \
  --overscroll-history-navigation=0
EOF

chmod +x "${KIOSK_SCRIPT}"

cat >"/etc/systemd/system/${KIOSK_SERVICE}.service" <<EOF
[Unit]
Description=Tela da Estação Rádio Web
After=systemd-user-sessions.service estacao-radio-web.service network.target
Requires=estacao-radio-web.service
Conflicts=getty@tty1.service display-manager.service
StartLimitIntervalSec=60
StartLimitBurst=5

[Service]
User=${TARGET_USER}
PAMName=login
TTYPath=/dev/tty1
TTYReset=yes
TTYVHangup=yes
TTYVTDisallocate=yes
StandardInput=tty
StandardOutput=journal
StandardError=journal
Environment=HOME=${TARGET_HOME}
Environment=DISPLAY=:0
Environment=FRAMEBUFFER=${FRAMEBUFFER_DEVICE}
ExecStart=/usr/bin/xinit ${KIOSK_SCRIPT} -- /usr/bin/Xorg :0 vt1 -keeptty -nocursor -nolisten tcp -config 99-estacao-radio-fbdev.conf
Restart=on-failure
RestartSec=5
TimeoutStopSec=15

[Install]
WantedBy=multi-user.target
EOF

# O quiosque cria sua própria sessão Xorg. Evita a disputa com o desktop.
systemctl disable --now display-manager.service 2>/dev/null || true
systemctl disable --now lightdm.service 2>/dev/null || true
systemctl stop "${KIOSK_SERVICE}.service" 2>/dev/null || true

if ! pgrep -x Xorg >/dev/null 2>&1; then
  rm -f /tmp/.X0-lock /tmp/.X11-unix/X0
fi

systemctl set-default multi-user.target
systemctl daemon-reload
systemctl reset-failed "${KIOSK_SERVICE}.service" 2>/dev/null || true
systemctl enable --now "${KIOSK_SERVICE}.service"

for attempt in $(seq 1 12); do
  if systemctl is-active --quiet "${KIOSK_SERVICE}.service"; then
    sleep 2
    if systemctl is-active --quiet "${KIOSK_SERVICE}.service"; then
      echo
      echo "Modo quiosque instalado e em execução em ${FRAMEBUFFER_DEVICE}."
      echo "A interface abrirá automaticamente nos próximos inícios."
      exit 0
    fi
  fi
  sleep 1
done

echo
echo "O serviço do quiosque não permaneceu ativo."
echo "Diagnóstico mais recente:"
journalctl -u "${KIOSK_SERVICE}.service" -n 30 --no-pager || true
if [[ -f "${TARGET_HOME}/.local/share/xorg/Xorg.0.log" ]]; then
  echo
  echo "Erros do Xorg:"
  grep -E '^\[[^]]+\] \((EE|WW)\)' \
    "${TARGET_HOME}/.local/share/xorg/Xorg.0.log" | tail -n 30 || true
fi
echo
echo "Depois de corrigir o erro, tente:"
echo "  sudo systemctl restart ${KIOSK_SERVICE}"
exit 1
