#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
command -v python3.12 >/dev/null || { echo "Python 3.12 (including venv) is required."; exit 1; }
command -v npm >/dev/null || { echo "Node.js 22.12+ and npm are required inside WSL."; exit 1; }
if [ -d .venv ] && [ ! -x .venv/bin/python ]; then
  echo "An incompatible .venv exists. Transfer source files without the Windows .venv directory."
  exit 1
fi
python3.12 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements.txt
npm --prefix frontend ci
npm --prefix frontend run build
echo "Setup complete. Run: bash scripts/start-wsl.sh"
