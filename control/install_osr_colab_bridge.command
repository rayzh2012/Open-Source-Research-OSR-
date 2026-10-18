#!/bin/zsh
set -euo pipefail

REPO="$HOME/Open-Source-Research-OSR-"
PY312="/Library/Frameworks/Python.framework/Versions/3.12/bin/python3"

if [[ ! -x "$PY312" ]]; then
  if command -v python3.12 >/dev/null 2>&1; then
    PY312="$(command -v python3.12)"
  else
    echo "Python 3.12+ is required by google-colab-cli."
    echo "Current candidates:"
    command -v python3 || true
    python3 --version || true
    exit 2
  fi
fi

echo "Using: $PY312"
"$PY312" --version

echo "Installing/upgrading google-colab-cli for this user..."
"$PY312" -m pip install --user --upgrade google-colab-cli

COLAB="$HOME/Library/Python/3.12/bin/colab"
if [[ ! -x "$COLAB" ]]; then
  COLAB="$(find "$HOME/Library/Python" "$HOME/.local" -type f -name colab -perm -111 2>/dev/null | head -1 || true)"
fi
if [[ -z "${COLAB:-}" || ! -x "$COLAB" ]]; then
  echo "Installed package but could not locate colab executable."
  exit 3
fi

echo "Colab CLI: $COLAB"
"$COLAB" version

echo
echo "ONE-TIME AUTHENTICATION"
echo "A Google URL/code flow may appear. Sign in with the Google account that owns your Colab subscription."
echo "The resulting refresh token is cached locally under ~/.config/colab-cli/."
"$COLAB" --auth=oauth2 sessions

echo
echo "Authentication check passed."

if [[ -d "$REPO/.git" ]]; then
  git -C "$REPO" pull --ff-only || true
fi

echo
echo "Now installing/updating OSR Remote Control watcher..."
if [[ -f "$REPO/control/install_osr_remote_control.command" ]]; then
  chmod +x "$REPO/control/install_osr_remote_control.command"
  /bin/zsh "$REPO/control/install_osr_remote_control.command"
else
  echo "Remote-control installer missing in $REPO"
  exit 4
fi

echo
echo "✅ OSR Colab Bridge ready."
echo "Next remote-safe actions: COLAB_PROBE, COLAB_SMOKE"
echo "COLAB_SMOKE uses a CPU runtime, downloads one ~80 MiB public HF shard, validates Parquet, then exits."
