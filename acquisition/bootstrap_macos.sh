#!/bin/zsh
set -euo pipefail

REPO="$HOME/Open-Source-Research-OSR-"
URL="https://github.com/rayzh2012/Open-Source-Research-OSR-.git"

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"

if [[ -d "$REPO/.git" ]]; then
  git -C "$REPO" fetch origin master
  git -C "$REPO" checkout master
  git -C "$REPO" pull --ff-only origin master
else
  git clone --branch master "$URL" "$REPO"
fi

chmod +x "$REPO/acquisition/install_macos_watcher.sh" "$REPO/acquisition/run_watcher.sh"
exec "$REPO/acquisition/install_macos_watcher.sh"
