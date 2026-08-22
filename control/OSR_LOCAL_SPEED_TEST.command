#!/bin/zsh
set -u

export PATH="$HOME/.local/bin:$HOME/.kimi/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"
cd "$HOME/Open-Source-Research-OSR-" || exit 2

OUT="/tmp/OSR_KIMI_LOOP_RESULT.txt"
: > "$OUT"
exec > >(tee -a "$OUT") 2>&1

echo "OSR_KIMI_LOOP_TEST_START"
echo "cwd=$(pwd)"
echo "PATH=$PATH"
echo "kimi=$(command -v kimi || true)"
echo "rclone=$(command -v rclone || true)"

RC=0
if ! command -v kimi >/dev/null 2>&1; then
  echo "KIMI_NOT_FOUND"
  RC=127
else
  kimi --version || RC=$?
  echo "== Kimi non-interactive round trip =="
  if [[ "$RC" -eq 0 ]]; then
    kimi -p 'This is an OSR remote-control smoke test. Do not modify any file. Reply with exactly two lines: OSR_KIMI_LOOP_OK and /Users/hangwu/Open-Source-Research-OSR-' || RC=$?
  fi
fi

echo "kimi_returncode=$RC"
echo "OSR_KIMI_LOOP_TEST_END"

if command -v rclone >/dev/null 2>&1; then
  rclone copyto "$OUT" 'gdrive:OSR_WORK_SPACE/RemoteControl/OSR_KIMI_LOOP_RESULT.txt' || true
  echo "RESULT_UPLOAD_ATTEMPTED"
else
  echo "RCLONE_NOT_FOUND_FOR_UPLOAD"
fi

exit "$RC"
