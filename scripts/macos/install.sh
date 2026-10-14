#!/bin/bash
# Install (or remove with --uninstall) loosechange's macOS helpers:
#   ~/Applications/loosechange.app — handler of loosechange:// links (the bot's
#     «⚡ Установить в один клик» button): confirm dialog, then install with backup
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
OPEN_RUNNER="$HOME_DIR/loosechange-open.sh"
APP="$HOME/Applications/Обновить модели VibeForge.app"
HANDLER="$HOME/Applications/loosechange.app"
LSREGISTER=/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister
LABEL="com.loosechange.vibeforge-sync"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
UV="$(command -v uv 2>/dev/null || echo /opt/homebrew/bin/uv)"
HOURS=3

if [ "${1:-}" = "--uninstall" ]; then
    launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
    rm -f "$PLIST"
    [ -d "$HANDLER" ] && "$LSREGISTER" -u "$HANDLER" 2>/dev/null || true
    rm -rf "$APP" "$RUNNER" "$HANDLER" "$OPEN_RUNNER"
    "$UV" tool uninstall loosechange >/dev/null 2>&1 || true
    echo "removed: $HANDLER, $APP, $PLIST, runners, uv tool loosechange (data kept in $DATA)"
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
bake() {  # copy a runner with LC_BIN / LC_DATA baked in
    {
        head -1 "$1"
        printf 'export LC_BIN=%q\nexport LC_DATA=%q\n' "$LC_BIN" "$DATA"
        tail -n +2 "$1"
    } > "$2"
    chmod +x "$2"
}
bake "$REPO/scripts/macos/vibeforge-sync.sh" "$RUNNER"
bake "$REPO/scripts/macos/loosechange-open.sh" "$OPEN_RUNNER"
for f in models.json access.json history/changes.json; do
    [ -f "$REPO/data/$f" ] && cp "$REPO/data/$f" "$DATA/$f"
done
echo "cli: $LC_BIN"
echo "data: $DATA"

# 3) the loosechange:// link handler
SRC="$(mktemp -t loosechange-handler).applescript"
sed "s|__RUNNER__|$OPEN_RUNNER|" "$REPO/scripts/macos/LinkHandler.applescript" > "$SRC"
rm -rf "$HANDLER"
osacompile -o "$HANDLER" "$SRC"
rm -f "$SRC"
PB=/usr/libexec/PlistBuddy
INFO="$HANDLER/Contents/Info.plist"
$PB -c "Set :CFBundleIdentifier dev.loosechange.handler" "$INFO" 2>/dev/null \
    || $PB -c "Add :CFBundleIdentifier string dev.loosechange.handler" "$INFO"
$PB -c "Add :CFBundleURLTypes array" "$INFO"
$PB -c "Add :CFBundleURLTypes:0 dict" "$INFO"
$PB -c "Add :CFBundleURLTypes:0:CFBundleURLName string loosechange link" "$INFO"
$PB -c "Add :CFBundleURLTypes:0:CFBundleURLSchemes array" "$INFO"
$PB -c "Add :CFBundleURLTypes:0:CFBundleURLSchemes:0 string loosechange" "$INFO"
codesign --force --deep --sign - "$HANDLER" >/dev/null 2>&1
"$LSREGISTER" -f "$HANDLER"
echo "link handler: $HANDLER (loosechange://)"

# 4) the icon: an AppleScript applet that runs the sync with --restart
mkdir -p "$HOME/Applications"
rm -rf "$APP"
osacompile -o "$APP" -e "do shell script \"/bin/bash \" & quoted form of \"$RUNNER\" & \" --restart\""
echo "icon: $APP"

# 5) the schedule
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
