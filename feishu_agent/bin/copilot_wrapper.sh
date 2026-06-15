#!/usr/bin/env bash
set -euo pipefail

BIN="${COPILOTCLI_BIN:-/home/robot/.vscode-server/data/User/globalStorage/github.copilot-chat/copilotCli/copilot}"
if [[ ! -x "$BIN" ]]; then
  echo "copilot binary not found or not executable: $BIN" >&2
  exit 2
fi

# Read entire stdin as the prompt
INPUT=$(cat)

# Run copilot in non-interactive prompt mode and forward stdout/stderr
exec "$BIN" -p "$INPUT" --output-format json --silent
