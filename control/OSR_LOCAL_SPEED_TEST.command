#!/bin/zsh
set -euo pipefail
cd "$HOME/Open-Source-Research-OSR-"

echo "OSR_KIMI_LOOP_TEST_START"
echo "cwd=$(pwd)"
echo "kimi=$(command -v kimi || true)"

if ! command -v kimi >/dev/null 2>&1; then
  echo "KIMI_NOT_FOUND"
  exit 127
fi

kimi --version

echo "== Kimi non-interactive round trip =="
kimi -p 'This is an OSR remote-control smoke test. Do not modify any file. Reply with exactly two lines: OSR_KIMI_LOOP_OK and the current working directory.'

echo "OSR_KIMI_LOOP_TEST_END"
