#!/bin/zsh
set -euo pipefail

REPO="$HOME/Open-Source-Research-OSR-"
APP="$HOME/Library/Application Support/OSR Acquisition"
mkdir -p "$APP/logs"

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"

if [[ -d "$REPO/.git" ]]; then
  git -C "$REPO" pull --ff-only || true
fi

if [[ -z "${HF_TOKEN:-}" ]]; then
  HF_TOKEN="$(security find-generic-password -a "$USER" -s osr-hf-token -w 2>/dev/null || true)"
  export HF_TOKEN
fi

python3 "$REPO/acquisition/bulk_watcher.py"
