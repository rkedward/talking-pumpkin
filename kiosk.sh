#!/usr/bin/env bash
# Opens the pumpkin face full screen on the first display and, if a side-show window is set to hdmi, the creature
# window on the second display (the Pi 5's second HDMI port). If a small DSI touchscreen is connected, the camera
# debug view (camera picture with boxes, voice direction, log) opens on it. Started at login by install_pi.sh.
cd "$(dirname "$0")"
PY=.venv/bin/python; [ -x "$PY" ] || PY=python3
# WINDOW = name of the window on the Pi's 2nd HDMI port, or "-" when the side show is off or all windows are on Wi-Fi
read -r PORT WINDOW SCREEN_X DEBUG_SCREEN < <("$PY" -c "
import config; c = config.load(); w = c['window']
hdmi = [n for n, s in config.screens(w).items() if s['hdmi']] if w['enabled'] else []
print(c['web']['port'], hdmi[0] if hdmi else '-', int(w['screen_x']), c['web'].get('debug_screen') or 'off')" 2>/dev/null || echo "8000 - 0 auto")
URL="http://localhost:${PORT}"
for _ in $(seq 60); do curl -s -o /dev/null "$URL/" && break; sleep 1; done
BROWSER=$(command -v chromium || command -v chromium-browser)
FLAGS=(--kiosk --noerrdialogs --disable-infobars --no-first-run --incognito --disable-session-crashed-bubble
       --check-for-update-interval=31536000 --autoplay-policy=no-user-gesture-required)

# Small DSI screen for the camera debug view: keep the HDMI projector(s) at the top left (the face opens at 0,0)
# and put the DSI screen below the first one (beside it can push the desktop past the Pi's 4096-pixel limit
# with a wide monitor). debug_screen under [web]: "auto" (any DSI screen), an output name
# such as "DSI-1", or "off".
DSI=""
if [ "$DEBUG_SCREEN" != "off" ] && command -v xrandr >/dev/null; then
  CONNECTED=$(xrandr | awk '$2 == "connected" {print $1}')
  if [ "$DEBUG_SCREEN" = "auto" ]; then DSI=$(echo "$CONNECTED" | grep '^DSI' | head -n 1)
  else DSI=$(echo "$CONNECTED" | grep -x "$DEBUG_SCREEN" || true); fi
  HDMIS=$(echo "$CONNECTED" | grep -v '^DSI' || true)
  if [ -n "$DSI" ] && [ -n "$HDMIS" ]; then
    FIRST=$(echo "$HDMIS" | head -n 1)
    # 1080p is plenty for the face (and the projector's native size). Ultra-wide monitors' preferred modes can fail
    # once the DSI screen shares the display, so use 1920x1080 when the output offers it.
    MODE=(--auto)
    if xrandr | awk -v o="$FIRST" '$1 == o {on = 1; next} /^[^ ]/ {on = 0} on && $1 == "1920x1080" {f = 1} END {exit !f}'; then
      MODE=(--mode 1920x1080 --rate 60)
    fi
    xrandr --output "$FIRST" "${MODE[@]}" --primary --pos 0x0 --output "$DSI" --auto --below "$FIRST" || true
    sleep 1
  fi
fi

if [ "$WINDOW" != "-" ]; then
  # x position of the second monitor, from xrandr (e.g. "1: +HDMI-A-2 1920/530x1080/300+1920+0  HDMI-A-2")
  if [ "$SCREEN_X" = "0" ] && command -v xrandr >/dev/null; then
    SCREEN_X=$(xrandr --listmonitors | awk 'NR>1 && $4 !~ /^DSI/ {split($3, a, "+"); if (a[2] > 0) {print a[2]; exit}}')
  fi
  "$BROWSER" "${FLAGS[@]}" --user-data-dir=/tmp/pumpkin-window --window-position="${SCREEN_X:-1920},0" "$URL/window.html?w=$WINDOW" &
fi
if [ -n "$DSI" ]; then
  read -r DSI_X DSI_Y < <(xrandr --listmonitors | awk -v o="$DSI" '$4 == o {split($3, a, "+"); print a[2], a[3]; exit}')
  "$BROWSER" "${FLAGS[@]}" --user-data-dir=/tmp/pumpkin-debug --window-position="${DSI_X:-0},${DSI_Y:-0}" "$URL/?debug" &
fi
exec "$BROWSER" "${FLAGS[@]}" --user-data-dir=/tmp/pumpkin-face --window-position=0,0 "$URL/"
