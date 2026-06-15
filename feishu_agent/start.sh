#!/usr/bin/env bash
set -euo pipefail

# Start script for feishu_agent ws_agent
# Exports environment variables used by the service and runs the python module

HERE="$(cd "$(dirname "$0")" && pwd)"
VEVN_DIR="$HERE/../.venv"

# Defaults (override via systemd Environment or EnvironmentFile if desired)
export COPILOTCLI_COMMAND=${COPILOTCLI_COMMAND:-/home/robot/.vscode-server/data/User/globalStorage/github.copilot-chat/copilotCli/copilot}
export COPILOTCLI_TIMEOUT=${COPILOTCLI_TIMEOUT:-600}
export FEISHU_ENABLE_PROVIDER_REVIEW=${FEISHU_ENABLE_PROVIDER_REVIEW:-1}
# Load environment from system-wide file or local .env before validating credentials
if [ -f /etc/default/feishu_agent ]; then
  set -a
  # shellcheck disable=SC1091
  source /etc/default/feishu_agent
  set +a
elif [ -f "$HERE/../.env.local" ]; then
  set -a
  # shellcheck disable=SC1091
  source "$HERE/../.env.local"
  set +a
fi

if [ -z "${COPILOTCLI_ADDITIONAL_MCP:-}" ]; then
  if [ -f /etc/copilot/mcp-config.json ]; then
    export COPILOTCLI_ADDITIONAL_MCP=@/etc/copilot/mcp-config.json
  elif [ -f /home/robot/.copilot/mcp-config.json ]; then
    export COPILOTCLI_ADDITIONAL_MCP=@/home/robot/.copilot/mcp-config.json
  fi
fi

# Ensure required Feishu credentials are present; provide actionable message if missing
if [ -z "${FEISHU_APP_ID:-}" ] || [ -z "${FEISHU_APP_SECRET:-}" ]; then
  cat >&2 <<'EOM'
错误：未设置 FEISHU_APP_ID 或 FEISHU_APP_SECRET。

解决方法（任选其一）：
 1) 在当前 shell 导出并以当前用户运行：
   export FEISHU_APP_ID="<你的_app_id>"
   export FEISHU_APP_SECRET="<你的_app_secret>"
   ./feishu_agent/start.sh

 2) 使用 sudo 并保留环境：
   export FEISHU_APP_ID=...; export FEISHU_APP_SECRET=...; sudo -E ./feishu_agent/start.sh

 3) 推荐：把凭据写入系统环境文件并由 systemd 加载：
   sudo cp feishu_agent/system/feishu_agent.env.example /etc/default/feishu_agent
   sudo edit /etc/default/feishu_agent  # 填入真实值
   sudo systemctl daemon-reload && sudo systemctl restart feishu_agent.service

更多信息请参阅 feishu_agent/system/feishu_agent.env.example
EOM
  exit 1
fi

if [ -d "$VEVN_DIR" ]; then
  # Use virtualenv python if available
  PYBIN="$VEVN_DIR/bin/python"
else
  PYBIN="python3"
fi

exec "$PYBIN" -m feishu_agent.main
