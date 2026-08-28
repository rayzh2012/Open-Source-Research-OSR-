#!/bin/zsh
set -euo pipefail

BRANCH="stage2-direct-miner-v3-1"
RAW="https://raw.githubusercontent.com/rayzh2012/Open-Source-Research-OSR-/$BRANCH"
APP="$HOME/Library/Application Support/OSR Control"
PLIST="$HOME/Library/LaunchAgents/com.rayzh.osr.remote-control.plist"
REPO="$HOME/Open-Source-Research-OSR-"
LABEL="com.rayzh.osr.remote-control"
mkdir -p "$APP" "$HOME/Library/LaunchAgents"

RUNTIME_PATH="$HOME/.local/bin:$HOME/.kimi/bin:/opt/homebrew/bin:/usr/local/bin:/Library/Frameworks/Python.framework/Versions/3.12/bin:/usr/bin:/bin:/usr/sbin:/sbin"
export PATH="$RUNTIME_PATH:$PATH"

if ! command -v brew >/dev/null 2>&1; then
  echo "Homebrew is required first: https://brew.sh" >&2
  exit 1
fi

brew install rclone git || true
python3 -m pip install --user -U pyarrow requests

PYTHON_BIN="$(command -v python3)"
RCLONE_BIN="$(command -v rclone)"
RCLONE_CONFIG="$HOME/.config/rclone/rclone.conf"

echo "Python: $PYTHON_BIN"
echo "rclone: $RCLONE_BIN"
echo "rclone config: $RCLONE_CONFIG"

if ! "$RCLONE_BIN" listremotes 2>/dev/null | grep -qx 'gdrive:'; then
  echo
  echo "One-time Google Drive authorization. Create remote name exactly: gdrive"
  "$RCLONE_BIN" config
fi

curl -fL -H 'Cache-Control: no-cache' "$RAW/control/osr_command_watcher.py?ts=$(date +%s%N)" -o "$APP/osr_command_watcher.py"
chmod +x "$APP/osr_command_watcher.py"

cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PYTHON_BIN</string>
    <string>$APP/osr_command_watcher.py</string>
  </array>
  <key>WorkingDirectory</key><string>$REPO</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>HOME</key><string>$HOME</string>
    <key>PATH</key><string>$RUNTIME_PATH</string>
    <key>RCLONE_CONFIG</key><string>$RCLONE_CONFIG</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>5</integer>
  <key>ProcessType</key><string>Background</string>
  <key>StandardOutPath</key><string>$APP/launchd.out.log</string>
  <key>StandardErrorPath</key><string>$APP/launchd.err.log</string>
</dict>
</plist>
PLIST

launchctl bootout "gui/$UID/$LABEL" >/dev/null 2>&1 || true
launchctl bootstrap "gui/$UID" "$PLIST"
launchctl enable "gui/$UID/$LABEL"
launchctl kickstart -k "gui/$UID/$LABEL"
sleep 1

echo
echo "=== launchd verification ==="
if launchctl print "gui/$UID/$LABEL" > "$APP/launchd.print.txt" 2>&1; then
  grep -E '^[[:space:]]*(state|pid|last exit code) = ' "$APP/launchd.print.txt" || true
else
  cat "$APP/launchd.print.txt" >&2 || true
  echo "launchd job verification failed" >&2
  tail -n 80 "$APP/launchd.err.log" >&2 2>/dev/null || true
  exit 2
fi

if ! pgrep -f "$APP/osr_command_watcher.py" >/dev/null 2>&1; then
  echo "Watcher process is not running." >&2
  echo "--- launchd stderr ---" >&2
  tail -n 80 "$APP/launchd.err.log" >&2 2>/dev/null || true
  echo "--- watcher log ---" >&2
  tail -n 80 "$APP/osr-control.log" >&2 2>/dev/null || true
  exit 3
fi

echo
echo "✅ OSR Remote Control installed and watcher process verified."
echo "Mode: persistent watcher, internal poll every 5 seconds"
echo "Python: $PYTHON_BIN"
echo "Runtime PATH: $RUNTIME_PATH"
echo "Status: gdrive:OSR_WORK_SPACE/RemoteControl/OSR_CONTROL_STATUS.json"
echo "Local log: $APP/osr-control.log"
echo "Launchd stderr: $APP/launchd.err.log"
echo
echo "Pending GitHub command will be consumed by the live watcher."
