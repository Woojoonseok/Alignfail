#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [ ! -x .venv/bin/python ] || [ ! -f frontend/dist/index.html ]; then
  echo "Run bash scripts/setup-wsl.sh first."
  exit 1
fi
echo "AlignFail Dataset Studio: http://localhost:8000"
echo "Data root example: /mnt/d/Dada"
exec .venv/bin/python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000 --workers 1
