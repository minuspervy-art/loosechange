#!/bin/bash
# Install (or remove with --uninstall) the no-typing VibeForge model sync:
#   ~/Applications/Обновить модели VibeForge.app   — double-click (or put in the Dock)
#   ~/Library/LaunchAgents/com.loosechange.vibeforge-sync.plist — every N hours,
#     only while VibeForge is closed (default 3 h; --interval-hours N)
# Background jobs may not read ~/Documents (macOS privacy), so everything they need
# lives outside the checkout: the CLI via `uv tool install` (~/.local/bin/loosechange),
# the runner and data in ~/Library/Application Support/loosechange/. Re-run this script
# after `git pull` or a new `loosechange probe` to refresh them.
set -eu
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
HOME_DIR="$HOME/Library/Application Support/loosechange"
DATA="$HOME_DIR/data"
RUNNER="$HOME_DIR/vibeforge-sync.sh"
APP="$HOME/Applications/Обновить модели VibeForge.app"
LABEL="com.loosechange.vibeforge-sync"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
UV="$(command -v uv 2>/dev/null || echo /opt/homebrew/bin/uv)"
HOURS=3

if [ "${1:-}" = "--uninstall" ]; then
    launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
    rm -f "$PLIST"
    rm -rf "$APP" "$RUNNER"
    "$UV" tool uninstall loosechange >/dev/null 2>&1 || true
    echo "removed: $APP, $PLIST, $RUNNER, uv tool loosechange (data kept in $DATA)"
    exit 0
fi
if [ "${1:-}" = "--interval-hours" ]; then HOURS="${2:?hours}"; fi
[ -x "$UV" ] || { echo "uv not found (brew install uv)"; exit 1; }

# 1) the CLI, outside ~/Documents
"$UV" tool install --force --reinstall --quiet "$REPO"
LC_BIN="$("$UV" tool dir --bin)/loosechange"
[ -x "$LC_BIN" ] || { echo "install failed: $LC_BIN"; exit 1; }

# 2) runner + data (the probe verdicts in access.json come from the checkout)
mkdir -p "$DATA/history" "$HOME/Library/Logs/loosechange"
{
    head -1 "$REPO/scripts/macos/vibeforge-sync.sh"
    printf 'export LC_BIN=%q\nexport LC_DATA=%q\n' "$LC_BIN" "$DATA"
    tail -n +2 "$REPO/scripts/macos/vibeforge-sync.sh"
} > "$RUNNER"
chmod +x "$RUNNER"
for f in models.json access.json history/changes.json; do
    [ -f "$REPO/data/$f" ] && cp "$REPO/data/$f" "$DATA/$f"
done
echo "cli: $LC_BIN"
echo "data: $DATA"

# 3) the icon: an AppleScript applet that runs the sync with --restart
mkdir -p "$HOME/Applications"
rm -rf "$APP"
osacompile -o "$APP" -e "do shell script \"/bin/bash \" & quoted form of \"$RUNNER\" & \" --restart\""
echo "icon: $APP"

# 4) the schedule
mkdir -p "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array><string>/bin/bash</string><string>$RUNNER</string><string>--if-closed</string></array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>LC_BIN</key><string>$LC_BIN</string>
    <key>LC_DATA</key><string>$DATA</string>
  </dict>
  <key>StartInterval</key><integer>$((HOURS * 3600))</integer>
  <key>RunAtLoad</key><false/>
  <key>StandardOutPath</key><string>$HOME/Library/Logs/loosechange/launchd.log</string>
  <key>StandardErrorPath</key><string>$HOME/Library/Logs/loosechange/launchd.log</string>
</dict>
</plist>
PL
plutil -lint "$PLIST" >/dev/null
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "schedule: every $HOURS h while VibeForge is closed ($PLIST)"
echo "log: ~/Library/Logs/loosechange/vibeforge-sync.log"
