#!/bin/bash
# Install (or remove with --uninstall) the no-typing VibeForge model sync:
#   ~/Applications/Обновить модели VibeForge.app   — double-click (or put in the Dock)
#   ~/Library/LaunchAgents/com.loosechange.vibeforge-sync.plist — every N hours,
#     only while VibeForge is closed (default 3 h; --interval-hours N)
set -eu
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
SYNC="$REPO/scripts/macos/vibeforge-sync.sh"
APP="$HOME/Applications/Обновить модели VibeForge.app"
LABEL="com.loosechange.vibeforge-sync"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
UV="$(command -v uv 2>/dev/null || echo /opt/homebrew/bin/uv)"
HOURS=3

if [ "${1:-}" = "--uninstall" ]; then
    launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
    rm -f "$PLIST"
    rm -rf "$APP"
    echo "removed: $APP, $PLIST"
    exit 0
fi
if [ "${1:-}" = "--interval-hours" ]; then HOURS="${2:?hours}"; fi
[ -x "$UV" ] || { echo "uv not found (brew install uv)"; exit 1; }
chmod +x "$SYNC"

# 1) the icon: an AppleScript applet that runs the sync with --restart
mkdir -p "$HOME/Applications"
rm -rf "$APP"
osacompile -o "$APP" -e "do shell script \"UV=\" & quoted form of \"$UV\" & \" /bin/bash \" & quoted form of \"$SYNC\" & \" --restart\""
echo "icon: $APP"

# 2) the schedule
mkdir -p "$HOME/Library/LaunchAgents" "$HOME/Library/Logs/loosechange"
cat > "$PLIST" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array><string>/bin/bash</string><string>$SYNC</string><string>--if-closed</string></array>
  <key>EnvironmentVariables</key><dict><key>UV</key><string>$UV</string></dict>
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
