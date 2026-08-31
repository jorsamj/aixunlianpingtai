#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="${MC_REMOTE_PYTHON:-python3}"
DATA_DIR="${MC_REMOTE_DATA_DIR:-${SCRIPT_DIR}/remote_data}"
HOST="${MC_REMOTE_HOST:-0.0.0.0}"
PORT="${MC_REMOTE_PORT:-8020}"

mkdir -p -- "${DATA_DIR}"

"${PYTHON}" "${SCRIPT_DIR}/task_worker.py" --data-dir "${DATA_DIR}" --roles training &
WORKER_PID=$!
MC_REMOTE_DATA_DIR="${DATA_DIR}" "${PYTHON}" -m uvicorn remote_train_server:app --host "${HOST}" --port "${PORT}" &
API_PID=$!

cleanup() {
  kill "${API_PID}" "${WORKER_PID}" 2>/dev/null || true
  wait "${API_PID}" "${WORKER_PID}" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

wait -n "${API_PID}" "${WORKER_PID}"
