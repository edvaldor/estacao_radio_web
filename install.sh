#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${PROJECT_DIR}/.venv"
SERVICE_NAME="estacao-radio-web"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
ENV_FILE="/etc/default/${SERVICE_NAME}"
BLACKLIST_FILE="/etc/modprobe.d/estacao-radio-rtl-sdr.conf"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Este instalador precisa de permissão administrativa."
  echo "Use: sudo ./install.sh"
  exit 1
fi

if [[ -n "${SUDO_USER:-}" && "${SUDO_USER}" != "root" ]]; then
  TARGET_USER="${SUDO_USER}"
elif id pi >/dev/null 2>&1; then
  TARGET_USER="pi"
else
  TARGET_USER="root"
fi

TARGET_GROUP="$(id -gn "${TARGET_USER}")"

echo
echo "========================================"
echo "  Instalação da Estação Rádio Web"
echo "========================================"
echo "Pasta: ${PROJECT_DIR}"
echo "Usuário do serviço: ${TARGET_USER}"
echo

export DEBIAN_FRONTEND=noninteractive
if [[ "${SKIP_APT:-0}" != "1" ]]; then
  apt-get update
  apt-get install -y \
    python3 \
    python3-venv \
    python3-pip \
    rtl-sdr \
    alsa-utils \
    git
fi

echo "Preparando o ambiente Python..."
if [[ ! -d "${VENV_DIR}" ]]; then
  python3 -m venv "${VENV_DIR}"
fi
"${VENV_DIR}/bin/python" -m pip install --upgrade pip wheel
"${VENV_DIR}/bin/pip" install -r "${PROJECT_DIR}/requirements.txt"

echo "Liberando o RTL-SDR para uso como receptor..."
cat >"${BLACKLIST_FILE}" <<'EOF'
# O dongle RTL2832U será usado pelo rtl_fm, não como receptor de TV.
blacklist dvb_usb_rtl28xxu
blacklist rtl2832
blacklist rtl2830
EOF

if command -v update-initramfs >/dev/null 2>&1; then
  update-initramfs -u
fi

usermod -a -G audio,plugdev "${TARGET_USER}" || true

if [[ ! -f "${ENV_FILE}" ]]; then
  AUDIO_DEVICE="default"
  AUDIO_CARD=""
  if aplay -l 2>/dev/null | grep -q "Headphones"; then
    AUDIO_DEVICE="plughw:CARD=Headphones,DEV=0"
    AUDIO_CARD="1"
  fi
  cat >"${ENV_FILE}" <<'EOF'
# auto: usa o RTL-SDR quando encontrado e simulação quando ele não está conectado.
RADIO_DRIVER=auto
RADIO_HOST=0.0.0.0
RADIO_PORT=5000
EOF
  {
    echo "RADIO_AUDIO_DEVICE=${AUDIO_DEVICE}"
    echo "RADIO_AUDIO_MIXER=PCM"
    if [[ -n "${AUDIO_CARD}" ]]; then
      echo "RADIO_AUDIO_CARD=${AUDIO_CARD}"
    fi
  } >>"${ENV_FILE}"
else
  if ! grep -q '^RADIO_AUDIO_DEVICE=' "${ENV_FILE}"; then
    if aplay -l 2>/dev/null | grep -q "Headphones"; then
      echo "RADIO_AUDIO_DEVICE=plughw:CARD=Headphones,DEV=0" >>"${ENV_FILE}"
      echo "RADIO_AUDIO_CARD=1" >>"${ENV_FILE}"
    else
      echo "RADIO_AUDIO_DEVICE=default" >>"${ENV_FILE}"
    fi
  fi
  if ! grep -q '^RADIO_AUDIO_MIXER=' "${ENV_FILE}"; then
    echo "RADIO_AUDIO_MIXER=PCM" >>"${ENV_FILE}"
  fi
fi

cat >"${SERVICE_FILE}" <<EOF
[Unit]
Description=Estação Rádio Web
After=network.target sound.target

[Service]
Type=simple
User=${TARGET_USER}
Group=${TARGET_GROUP}
SupplementaryGroups=audio plugdev
WorkingDirectory=${PROJECT_DIR}
EnvironmentFile=-${ENV_FILE}
Environment=PYTHONUNBUFFERED=1
ExecStart=${VENV_DIR}/bin/python ${PROJECT_DIR}/app.py
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

chown -R "${TARGET_USER}:${TARGET_GROUP}" "${PROJECT_DIR}"
chmod +x \
  "${PROJECT_DIR}/install.sh" \
  "${PROJECT_DIR}/run.sh" \
  "${PROJECT_DIR}/scripts/update.sh" \
  "${PROJECT_DIR}/scripts/install-kiosk.sh" \
  "${PROJECT_DIR}/scripts/uninstall.sh"

systemctl daemon-reload
systemctl enable --now "${SERVICE_NAME}"

echo
echo "Instalação concluída."
echo
echo "Abra em outro computador ou celular:"
echo "  http://IP_DO_RASPBERRY:5000"
echo
echo "Para descobrir o IP:"
echo "  hostname -I"
echo
echo "Para instalar a abertura automática na tela de 3,2 polegadas:"
echo "  sudo ./scripts/install-kiosk.sh"
echo
echo "IMPORTANTE: reinicie o Raspberry Pi para liberar o RTL-SDR:"
echo "  sudo reboot"
echo
echo "O scanner usa rtl_power e já foi instalado junto com rtl-sdr."
