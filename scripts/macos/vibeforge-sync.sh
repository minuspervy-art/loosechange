#!/bin/bash
# Keep VibeForge's OpenRouter models current — no typing.
#   vibeforge-sync.sh --restart    icon: quit VibeForge if open (not while agents work),
#                                  update, reopen, show a notification
#   vibeforge-sync.sh --if-closed  schedule: update only if VibeForge is closed;
#                                  notify only when something changed
# The installer copies this file to ~/Library/Application Support/loosechange/ and sets
# LC_BIN / LC_DATA: launchd jobs may not read ~/Documents (macOS privacy protection).
# Log: ~/Library/Logs/loosechange/vibeforge-sync.log
set -u
MODE="${1:---if-closed}"
LOG="$HOME/Library/Logs/loosechange/vibeforge-sync.log"
mkdir -p "$(dirname "$LOG")"
if [ -n "${LC_BIN:-}" ]; then
    CMD=("$LC_BIN")
else  # run from a checkout
    REPO="$(cd "$(dirname "$0")/../.." && pwd)"
    UV="${UV:-$(command -v uv 2>/dev/null || echo /opt/homebrew/bin/uv)}"
    CMD=("$UV" run --quiet --project "$REPO" loosechange)
    LC_DATA="${LC_DATA:-$REPO/data}"
fi

OUT="$("${CMD[@]}" sync --apply "$MODE" --data-dir "${LC_DATA:-data}" 2>&1)"
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
