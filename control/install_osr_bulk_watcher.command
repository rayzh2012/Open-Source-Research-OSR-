#!/bin/zsh
set -euo pipefail
BRANCH="stage2-direct-miner-v3-1"
REPO="$HOME/Open-Source-Research-OSR-"
if [[ ! -d "$REPO/.git" ]]; then
  git clone -b "$BRANCH" https://github.com/rayzh2012/Open-Source-Research-OSR-.git "$REPO"
else
  git -C "$REPO" fetch origin "$BRANCH"
  git -C "$REPO" checkout "$BRANCH"
  git -C "$REPO" pull --ff-only
fi
chmod +x "$REPO/acquisition/install_macos_watcher.sh"
exec "$REPO/acquisition/install_macos_watcher.sh"
