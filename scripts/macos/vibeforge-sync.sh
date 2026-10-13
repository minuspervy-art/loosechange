#!/bin/bash
# Keep VibeForge's OpenRouter models current — no typing.
#   vibeforge-sync.sh --restart    icon: quit VibeForge if open (not while agents work),
#                                  update, reopen, show a notification
#   vibeforge-sync.sh --if-closed  schedule: update only if VibeForge is closed;
#                                  notify only when something changed
# Log: ~/Library/Logs/loosechange/vibeforge-sync.log
set -u
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
UV="${UV:-$(command -v uv 2>/dev/null || echo /opt/homebrew/bin/uv)}"
LOG="$HOME/Library/Logs/loosechange/vibeforge-sync.log"
MODE="${1:---if-closed}"
mkdir -p "$(dirname "$LOG")"

OUT="$("$UV" run --quiet --project "$REPO" loosechange sync --apply "$MODE" \
    --data-dir "$REPO/data" 2>&1)"
CODE=$?
{ echo "--- $(date '+%Y-%m-%d %H:%M:%S') $MODE (exit $CODE)"; printf '%s\n' "$OUT"; } >> "$LOG"

SUMMARY="$(printf '%s\n' "$OUT" | sed -n 's/^summary: //p' | tail -1)"
if [ -z "$SUMMARY" ]; then
    SUMMARY="ошибка (код $CODE) — подробности в ~/Library/Logs/loosechange/vibeforge-sync.log"
fi
notify() {
    local text="${1//\"/\'}"
    /usr/bin/osascript -e "display notification \"$text\" with title \"loosechange · VibeForge\"" \
        >/dev/null 2>&1
}
if [ "$MODE" = "--restart" ] || printf '%s' "$SUMMARY" | grep -q -e "добавлено" -e "ошибка"; then
    notify "$SUMMARY"
fi
exit 0
