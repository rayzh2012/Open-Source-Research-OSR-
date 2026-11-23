#!/bin/zsh
# Download three Tianlong editions to this Mac; never uploads copyrighted text.
set -euo pipefail
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"
REPO="${OSR_REPO:-$HOME/Open-Source-Research-OSR-}"
ROOT="${1:-$HOME/Documents/金庸研究/天龙八部_三版本}"
SOURCE="$ROOT/JY_upstream"
OUT="$ROOT/研究产出"

for cmd in git python3; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "Missing $cmd. Install Apple Command Line Tools / Python 3 first." >&2
    exit 2
  fi
done

if [[ ! -f "$REPO/tools/tianlong_scene_diff.py" || ! -f "$REPO/tools/tianlong_drive_pipeline.py" ]]; then
  echo "OSR repo not found at: $REPO" >&2
  echo 'First clone: git clone https://github.com/rayzh2012/Open-Source-Research-OSR-.git "$HOME/Open-Source-Research-OSR-"' >&2
  exit 3
fi

mkdir -p "$ROOT"
if [[ ! -d "$SOURCE/.git" ]]; then
  git clone --depth 1 --filter=blob:none --sparse \
    https://github.com/OliverCWY/JY.git "$SOURCE"
else
  # Update only by fast-forward, never reset locally changed contents.
  git -C "$SOURCE" pull --ff-only
fi

git -C "$SOURCE" sparse-checkout set --cone \
  'Markdown/旧版/天龙八部' \
  'Markdown/三联版/天龙八部' \
  'Markdown/新修版/天龙八部'

for edition in '旧版' '三联版' '新修版'; do
  test -s "$SOURCE/Markdown/$edition/天龙八部/index.md" || {
    echo "Missing edition: $edition" >&2; exit 4;
  }
done

python3 "$REPO/tools/tianlong_drive_pipeline.py" \
  --source "$SOURCE" --output "$OUT"
python3 "$REPO/tools/tianlong_scene_diff.py" \
  --corpus "$SOURCE" --output "$OUT/ANALYSIS" --max-candidates 3000

printf '\n[OK] 三版本下载及算法索引已保存在这台 Mac：\n%s\n' "$ROOT"
printf 'Source commit: %s\n' "$(git -C "$SOURCE" rev-parse HEAD)"
printf 'Full text: %s\nZIP archives: %s\nAnalysis: %s\n' \
  "$OUT/Markdown" "$OUT/ZIP" "$OUT/ANALYSIS"
echo 'No credentials used. No books uploaded to GitHub or Google Drive.'