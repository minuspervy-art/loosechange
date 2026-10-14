#!/bin/bash
# Runner for the loosechange:// handler app: loosechange-open.sh <check|apply|apply-restart> <url>
# Prints STATUS on the first line and a message after it (see oneclick.py).
# The installer copies it to ~/Library/Application Support/loosechange/ with LC_BIN / LC_DATA
# set (macOS does not let background helpers read ~/Documents). The URL is only ever
# passed as an argument, never evaluated by a shell.
set -u
MODE="${1:-check}"
URL="${2:-}"
LOG="$HOME/Library/Logs/loosechange/links.log"
mkdir -p "$(dirname "$LOG")"
if [ -n "${LC_BIN:-}" ]; then
    CMD=("$LC_BIN")
else
    REPO="$(cd "$(dirname "$0")/../.." && pwd)"
    UV="${UV:-$(command -v uv 2>/dev/null || echo /opt/homebrew/bin/uv)}"
    CMD=("$UV" run --quiet --project "$REPO" loosechange)
    LC_DATA="${LC_DATA:-$REPO/data}"
fi
OUT="$("${CMD[@]}" open-url --mode "$MODE" --data "${LC_DATA:-data}/models.json" -- "$URL" 2>>"$LOG")"
{ echo "--- $(date '+%Y-%m-%d %H:%M:%S') $MODE $URL"; printf '%s\n' "$OUT"; } >> "$LOG"
if [ -z "$OUT" ]; then
    OUT="ERROR
Что-то пошло не так — подробности в ~/Library/Logs/loosechange/links.log"
fi
printf '%s' "$OUT"
exit 0
