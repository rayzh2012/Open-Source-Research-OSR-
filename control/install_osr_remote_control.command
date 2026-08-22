#!/bin/zsh
set -euo pipefail

BRANCH="stage2-direct-miner-v3-1"
RAW="https://raw.githubusercontent.com/rayzh2012/Open-Source-Research-OSR-/$BRANCH"
APP="$HOME/Library/Application Support/OSR Control"
PLIST="$HOME/Library/LaunchAgents/com.rayzh.osr.remote-control.plist"
mkdir -p "$APP" "$HOME/Library/LaunchAgents"

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"

if ! command -v brew >/dev/null 2>&1; then
  echo "Homebrew is required first: https://brew.sh" >&2
  exit 1
fi

brew install python rclone git || true
python3 -m pip install --user -U pyarrow requests

if ! rclone listremotes 2>/dev/null | grep -qx 'gdrive:'; then
  echo
  echo "One-time Google Drive authorization. Create remote name exactly: gdrive"
  rclone config
fi

curl -fL "$RAW/control/osr_command_watcher.py" -o "$APP/osr_command_watcher.py"
chmod +x "$APP/osr_command_watcher.py"

cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.rayzh.osr.remote-control</string>
  <key>ProgramArguments</key>
  <array><string>/usr/bin/env</string><string>python3</string><string>$APP/osr_command_watcher.py</string></array>
  <key>RunAtLoad</key><true/>
  <key>StartInterval</key><integer>30</integer>
  <key>ProcessType</key><string>Background</string>
  <key>StandardOutPath</key><string>$APP/launchd.out.log</string>
  <key>StandardErrorPath</key><string>$APP/launchd.err.log</string>
</dict>
</plist>
PLIST

launchctl bootout "gui/$UID/com.rayzh.osr.remote-control" >/dev/null 2>&1 || true
launchctl bootstrap "gui/$UID" "$PLIST"
launchctl enable "gui/$UID/com.rayzh.osr.remote-control"
launchctl kickstart -k "gui/$UID/com.rayzh.osr.remote-control"

echo
echo "✅ OSR Remote Control installed."
echo "Poll interval: 30 seconds"
echo "Status: gdrive:OSR_WORK_SPACE/RemoteControl/OSR_CONTROL_STATUS.json"
echo "Local log: $APP/osr-control.log"
echo
echo "You can close this window. Future allowlisted runs can be triggered by changing control/osr_command.json in GitHub."
read -k 1 "?Press any key to close..."
