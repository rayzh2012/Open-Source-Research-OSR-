#!/bin/zsh
set -euo pipefail

REPO="$HOME/Open-Source-Research-OSR-"
PLIST="$HOME/Library/LaunchAgents/com.rayzh.osr.bulk-acquisition.plist"
APP="$HOME/Library/Application Support/OSR Acquisition"
mkdir -p "$HOME/Library/LaunchAgents" "$APP/logs"

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"

if ! command -v brew >/dev/null 2>&1; then
  echo "Homebrew is required. Install from https://brew.sh then rerun." >&2
  exit 1
fi

brew install python rclone git || true
python3 -m pip install --user -U requests huggingface_hub

if ! rclone listremotes | grep -qx 'gdrive:'; then
  echo
  echo "One-time Google Drive setup. Create a remote named exactly: gdrive"
  echo "Choose Google Drive, authenticate in the browser, and grant Drive access."
  rclone config
fi

if ! security find-generic-password -a "$USER" -s osr-hf-token -w >/dev/null 2>&1; then
  echo
  read -s "HFNEW?Paste a NEW Hugging Face read token (input hidden): "
  echo
  if [[ -n "$HFNEW" ]]; then
    security add-generic-password -a "$USER" -s osr-hf-token -w "$HFNEW" -U >/dev/null
  fi
fi

chmod +x "$REPO/acquisition/run_watcher.sh" "$REPO/acquisition/install_macos_watcher.sh"

cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.rayzh.osr.bulk-acquisition</string>
  <key>ProgramArguments</key>
  <array><string>/bin/zsh</string><string>$REPO/acquisition/run_watcher.sh</string></array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>30</integer>
  <key>ProcessType</key><string>Background</string>
  <key>StandardOutPath</key><string>$APP/logs/watcher.out.log</string>
  <key>StandardErrorPath</key><string>$APP/logs/watcher.err.log</string>
</dict>
</plist>
PLIST

launchctl bootout "gui/$UID/com.rayzh.osr.bulk-acquisition" >/dev/null 2>&1 || true
launchctl bootstrap "gui/$UID" "$PLIST"
launchctl enable "gui/$UID/com.rayzh.osr.bulk-acquisition"
launchctl kickstart -k "gui/$UID/com.rayzh.osr.bulk-acquisition"

echo
echo "OSR bulk watcher installed and running."
echo "stdout: $APP/logs/watcher.out.log"
echo "stderr: $APP/logs/watcher.err.log"
echo "queue:  $REPO/acquisition/targets.json"
echo "Drive status will be written under Dragon Source Corpus/_ACQUISITION_STATUS/."
