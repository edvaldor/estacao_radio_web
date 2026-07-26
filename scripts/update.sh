#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Use: sudo ./scripts/update.sh"
  exit 1
fi

if [[ ! -d "${PROJECT_DIR}/.git" ]]; then
  echo "Esta pasta não foi obtida com git clone."
  echo "Para receber atualizações automáticas, instale usando:"
  echo "  git clone https://github.com/edvaldor/estacao_radio_web.git"
  exit 1
fi

if [[ -n "${SUDO_USER:-}" && "${SUDO_USER}" != "root" ]]; then
  TARGET_USER="${SUDO_USER}"
elif id pi >/dev/null 2>&1; then
  TARGET_USER="pi"
else
  TARGET_USER="root"
fi

echo "Baixando a versão mais recente..."
sudo -u "${TARGET_USER}" git -C "${PROJECT_DIR}" pull --ff-only

echo "Atualizando dependências e o serviço..."
SKIP_APT=1 bash "${PROJECT_DIR}/install.sh"

echo
echo "Atualização concluída. Versão: $(cat "${PROJECT_DIR}/VERSION" 2>/dev/null || echo atual)"
