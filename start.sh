#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv
fi
if [ ! -f .venv/.ais-dependencies-installed ] || [ requirements.txt -nt .venv/.ais-dependencies-installed ]; then
  .venv/bin/python -m pip install -r requirements.txt
  touch .venv/.ais-dependencies-installed
fi
if [ ! -f node_modules/.ais-dependencies-installed ] || [ package-lock.json -nt node_modules/.ais-dependencies-installed ]; then
  npm ci --no-audit --no-fund
  touch node_modules/.ais-dependencies-installed
fi
npm run build
printf '\nAIS Demo: http://127.0.0.1:%s\nUDP: 127.0.0.1:%s\n按 Ctrl+C 结束。\n\n' "${AIS_HTTP_PORT:-8765}" "${AIS_UDP_PORT:-10110}"
exec .venv/bin/python -m uvicorn backend.app:app --host 127.0.0.1 --port "${AIS_HTTP_PORT:-8765}"
