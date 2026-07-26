#!/usr/bin/env bash
set -Eeuo pipefail

SERVICE_NAME="estacao-radio-web"
KIOSK_SERVICE="estacao-radio-kiosk"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Use: sudo ./scripts/uninstall.sh"
  exit 1
fi

systemctl disable --now "${KIOSK_SERVICE}" 2>/dev/null || true
systemctl disable --now "${SERVICE_NAME}" 2>/dev/null || true

rm -f \
  "/etc/systemd/system/${KIOSK_SERVICE}.service" \
  "/etc/systemd/system/${SERVICE_NAME}.service" \
  "/usr/local/bin/estacao-radio-kiosk"

systemctl daemon-reload

echo "Os serviços foram removidos."
echo "A pasta do projeto e suas configurações foram preservadas."
