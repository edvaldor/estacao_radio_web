#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${PROJECT_DIR}/.venv"

if [[ ! -x "${VENV_DIR}/bin/python" ]]; then
  echo "Ambiente Python não encontrado."
  echo "Execute primeiro: sudo ./install.sh"
  exit 1
fi

cd "${PROJECT_DIR}"
exec "${VENV_DIR}/bin/python" app.py
