#!/bin/bash
# Simple launcher for testing /discuss command locally.
# No tmux, no frills — channel-server runs in the background with its stdout
# piped to a log file so the terminal stays clean for Claude Code's TUI.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Load proxy and local overrides
[ -f "$SCRIPT_DIR/autoservice.local.sh" ] && source "$SCRIPT_DIR/autoservice.local.sh"
[ -f "$SCRIPT_DIR/.mcp.env" ] && set -a && source "$SCRIPT_DIR/.mcp.env" && set +a

# Bypass corporate proxy for localhost — channel.py → channel-server is local WS.
# Without this, Python websockets routes ws://localhost:9999 through https_proxy
# and gets back an HTTP error instead of a WS upgrade ("InvalidMessage" in logs).
export no_proxy="localhost,127.0.0.1,::1${no_proxy:+,$no_proxy}"
export NO_PROXY="$no_proxy"

LOG_DIR="$SCRIPT_DIR/.autoservice/logs"
mkdir -p "$LOG_DIR"
SERVER_LOG="$LOG_DIR/channel-server.stdout.log"

# Default admin chat ids (private DM + optional group). Override via env if needed.
: "${ADMIN_CHAT_ID:=oc_7b5516c9077db050028a6f9e24d2b3f6}"
export ADMIN_CHAT_ID

echo "=== /discuss Test Launcher ==="
echo "Proxy         : ${https_proxy:-NOT SET}"
echo "Admin chats   : $ADMIN_CHAT_ID"
echo "Server stdout : $SERVER_LOG"
echo "Server logfile: $LOG_DIR/channel-server.log (DEBUG level, rotated)"
echo ""
echo "Tail the server in another terminal if you need to see its logs:"
echo "  tail -f $SERVER_LOG"
echo ""

# Start channel-server in background, redirecting ALL output to a file
uv run python3 feishu/channel_server.py > "$SERVER_LOG" 2>&1 &
SERVER_PID=$!

# Give the server a moment to bind the port
sleep 2

# Check it didn't die immediately
if ! kill -0 "$SERVER_PID" 2>/dev/null; then
  echo "!! channel-server exited during startup. Last lines of log:"
  tail -n 30 "$SERVER_LOG"
  exit 1
fi

echo "Channel-server running (PID $SERVER_PID). Starting Claude Code..."
echo "Go to Feishu and send: /discuss \"测试话题\""
echo "Press Ctrl+C here to stop everything."
echo ""

# Cleanup on exit
trap "echo 'Stopping...'; kill $SERVER_PID 2>/dev/null; wait $SERVER_PID 2>/dev/null; echo 'Done.'" EXIT

# Run Claude Code in foreground — its TUI owns the terminal, undistorted
claude \
  --dangerously-load-development-channels server:autoservice-channel \
  --permission-mode bypassPermissions
