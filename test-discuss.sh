#!/bin/bash
# Simple launcher for testing /discuss command locally.
# No tmux, no frills — just proxy + channel-server + Claude Code.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Load proxy and local overrides
[ -f "$SCRIPT_DIR/autoservice.local.sh" ] && source "$SCRIPT_DIR/autoservice.local.sh"
[ -f "$SCRIPT_DIR/.mcp.env" ] && set -a && source "$SCRIPT_DIR/.mcp.env" && set +a

echo "=== /discuss Test Launcher ==="
echo "Proxy: ${https_proxy:-NOT SET}"
echo ""

# Start channel-server in background
echo "Starting channel-server..."
ADMIN_CHAT_ID="${ADMIN_CHAT_ID:-oc_7b5516c9077db050028a6f9e24d2b3f6}" \
  uv run python3 feishu/channel_server.py &
SERVER_PID=$!
sleep 2

echo "Channel-server PID: $SERVER_PID"
echo ""
echo "Starting Claude Code with MCP channel..."
echo "Go to Feishu and send: /discuss \"测试话题\""
echo "Press Ctrl+C to stop everything."
echo ""

# Cleanup on exit
trap "echo 'Stopping...'; kill $SERVER_PID 2>/dev/null; wait $SERVER_PID 2>/dev/null; echo 'Done.'" EXIT

# Run Claude Code in foreground
claude \
  --dangerously-load-development-channels server:autoservice-channel \
  --permission-mode bypassPermissions
