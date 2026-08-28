#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
PYTHON_BIN="${PYTHON_BIN:-python3}"
PORT="${DEPLOY_SERVER_PORT:-8030}"
echo "[deploy] using python: $PYTHON_BIN"
echo "[deploy] install/check minimal web dependencies in CURRENT vendor environment"
"$PYTHON_BIN" -m pip install fastapi 'uvicorn[standard]' python-multipart requests pyyaml pillow >/dev/null
exec "$PYTHON_BIN" -m uvicorn remote_deploy_server:app --host 0.0.0.0 --port "$PORT"
