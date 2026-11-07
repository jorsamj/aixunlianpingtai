#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Install the ChangLian Cloud Rockchip board Agent as a systemd service.

Usage:
  sudo bash tools/install_rockchip_agent.sh \
    --control-plane https://control.example.com \
    --node-id rockchip-board-01 \
    --app-root /opt/aixunlianpingtai \
    --rknn-lite-python /opt/rknn/bin/python

The Agent token is read from MC_NODE_AGENT_TOKEN when set; otherwise the
installer prompts for it without echoing. The token is stored only in a
root-owned 0600 EnvironmentFile and is not embedded in ExecStart.
EOF
}

CONTROL_PLANE="$(printenv MC_CONTROL_PLANE_URL 2>/dev/null || true)"
NODE_ID="$(printenv MC_NODE_ID 2>/dev/null || true)"
TOKEN="$(printenv MC_NODE_AGENT_TOKEN 2>/dev/null || true)"
APP_ROOT="$(printenv MC_AGENT_APP_ROOT 2>/dev/null || true)"
if [[ -z "$APP_ROOT" ]]; then APP_ROOT="$(pwd)"; fi
AGENT_PYTHON="$(printenv MC_AGENT_PYTHON 2>/dev/null || true)"
if [[ -z "$AGENT_PYTHON" ]]; then AGENT_PYTHON="$(command -v python3 || true)"; fi
RKNN_LITE_PYTHON="$(printenv MC_AGENT_RKNN_LITE_PYTHON 2>/dev/null || true)"
STATE_DIR="$(printenv MC_NODE_STATE_DIR 2>/dev/null || true)"
if [[ -z "$STATE_DIR" ]]; then STATE_DIR="/var/lib/changlian-node-agent"; fi
SERVICE_NAME="$(printenv MC_AGENT_SERVICE_NAME 2>/dev/null || true)"
if [[ -z "$SERVICE_NAME" ]]; then SERVICE_NAME="changlian-rockchip-agent"; fi
SERVICE_USER="$(printenv MC_AGENT_SERVICE_USER 2>/dev/null || true)"
if [[ -z "$SERVICE_USER" ]]; then SERVICE_USER="$(printenv SUDO_USER 2>/dev/null || true)"; fi
if [[ -z "$SERVICE_USER" ]]; then SERVICE_USER="$(id -un)"; fi
CAPABILITIES="$(printenv MC_NODE_CAPABILITIES 2>/dev/null || true)"
if [[ -z "$CAPABILITIES" ]]; then CAPABILITIES="deployment-test.rknn"; fi

while [[ $# -gt 0 ]]; do
  case "$1" in
    --control-plane) [[ $# -ge 2 ]] || { echo 'missing value for --control-plane' >&2; exit 2; }; CONTROL_PLANE="$2"; shift 2 ;;
    --node-id) [[ $# -ge 2 ]] || { echo 'missing value for --node-id' >&2; exit 2; }; NODE_ID="$2"; shift 2 ;;
    --app-root) [[ $# -ge 2 ]] || { echo 'missing value for --app-root' >&2; exit 2; }; APP_ROOT="$2"; shift 2 ;;
    --python) [[ $# -ge 2 ]] || { echo 'missing value for --python' >&2; exit 2; }; AGENT_PYTHON="$2"; shift 2 ;;
    --rknn-lite-python) [[ $# -ge 2 ]] || { echo 'missing value for --rknn-lite-python' >&2; exit 2; }; RKNN_LITE_PYTHON="$2"; shift 2 ;;
    --state-dir) [[ $# -ge 2 ]] || { echo 'missing value for --state-dir' >&2; exit 2; }; STATE_DIR="$2"; shift 2 ;;
    --service-name) [[ $# -ge 2 ]] || { echo 'missing value for --service-name' >&2; exit 2; }; SERVICE_NAME="$2"; shift 2 ;;
    --service-user) [[ $# -ge 2 ]] || { echo 'missing value for --service-user' >&2; exit 2; }; SERVICE_USER="$2"; shift 2 ;;
    --capabilities) [[ $# -ge 2 ]] || { echo 'missing value for --capabilities' >&2; exit 2; }; CAPABILITIES="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

fail() { echo "ERROR: $*" >&2; exit 2; }
[[ "$(uname -s)" == "Linux" ]] || fail "Rockchip Agent systemd installer supports Linux only"
[[ "$EUID" -eq 0 ]] || fail "run this installer as root (for example: sudo bash ...)"
[[ -n "$CONTROL_PLANE" ]] || fail "--control-plane is required"
[[ -n "$NODE_ID" ]] || fail "--node-id is required"
[[ -n "$AGENT_PYTHON" && -x "$AGENT_PYTHON" ]] || fail "Agent Python is not executable: $AGENT_PYTHON"
APP_ROOT="$(cd "$APP_ROOT" && pwd)"
[[ -f "$APP_ROOT/node_agent.py" ]] || fail "node_agent.py not found under --app-root: $APP_ROOT"
if [[ -z "$RKNN_LITE_PYTHON" ]]; then RKNN_LITE_PYTHON="$AGENT_PYTHON"; fi
[[ -x "$RKNN_LITE_PYTHON" ]] || fail "RKNNLite Python is not executable: $RKNN_LITE_PYTHON"
command -v systemctl >/dev/null 2>&1 || fail "systemctl is required"
command -v runuser >/dev/null 2>&1 || fail "runuser is required"
id "$SERVICE_USER" >/dev/null 2>&1 || fail "service user does not exist: $SERVICE_USER"
for path_value in "$APP_ROOT" "$AGENT_PYTHON" "$RKNN_LITE_PYTHON" "$STATE_DIR"; do
  [[ "$path_value" != *" "* && "$path_value" != *$'\t'* ]] || fail "paths containing whitespace are not supported by this installer: $path_value"
done

GROUP_NAME="$(id -gn "$SERVICE_USER")"
install -d -m 0750 -o "$SERVICE_USER" -g "$GROUP_NAME" "$STATE_DIR"

echo "Running strict Rockchip board doctor before installation..."
if ! runuser -u "$SERVICE_USER" -- env \
  MC_NODE_CAPABILITIES="$CAPABILITIES" \
  MC_NODE_STATE_DIR="$STATE_DIR" \
  MC_AGENT_RKNN_LITE_PYTHON="$RKNN_LITE_PYTHON" \
  "$AGENT_PYTHON" "$APP_ROOT/node_agent.py" \
  --doctor \
  --state-dir "$STATE_DIR" \
  --rknn-lite-python "$RKNN_LITE_PYTHON"; then
  fail "Rockchip board doctor failed; service was not installed"
fi

if [[ -z "$TOKEN" ]]; then
  read -r -s -p "Agent Token: " TOKEN
  echo
fi
[[ -n "$TOKEN" ]] || fail "Agent Token is required"
for value in "$CONTROL_PLANE" "$NODE_ID" "$TOKEN" "$APP_ROOT" "$AGENT_PYTHON" "$RKNN_LITE_PYTHON" "$STATE_DIR" "$CAPABILITIES"; do
  [[ "$value" != *$'\n'* && "$value" != *$'\r'* ]] || fail "configuration values must not contain newlines"
done

CONFIG_DIR="/etc/changlian-cloud"
ENV_FILE="$CONFIG_DIR/$SERVICE_NAME.env"
UNIT_FILE="/etc/systemd/system/$SERVICE_NAME.service"
install -d -m 0750 "$CONFIG_DIR"
umask 077
cat >"$ENV_FILE" <<EOF
MC_CONTROL_PLANE_URL=$CONTROL_PLANE
MC_NODE_ID=$NODE_ID
MC_NODE_AGENT_TOKEN=$TOKEN
MC_NODE_CAPABILITIES=$CAPABILITIES
MC_NODE_STATE_DIR=$STATE_DIR
MC_AGENT_RKNN_LITE_PYTHON=$RKNN_LITE_PYTHON
EOF
chmod 0600 "$ENV_FILE"
chown root:root "$ENV_FILE"

cat >"$UNIT_FILE" <<EOF
[Unit]
Description=ChangLian Cloud Rockchip Node Agent
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$SERVICE_USER
WorkingDirectory=$APP_ROOT
EnvironmentFile=$ENV_FILE
ExecStartPre=$AGENT_PYTHON $APP_ROOT/node_agent.py --doctor
ExecStart=$AGENT_PYTHON $APP_ROOT/node_agent.py
Restart=always
RestartSec=5
TimeoutStopSec=30
KillSignal=SIGTERM

[Install]
WantedBy=multi-user.target
EOF
chmod 0644 "$UNIT_FILE"

systemctl daemon-reload
systemctl enable --now "$SERVICE_NAME"
echo "Installed and started $SERVICE_NAME"
echo "Check status with: systemctl status $SERVICE_NAME --no-pager"
echo "Follow logs with: journalctl -u $SERVICE_NAME -f"
