#!/usr/bin/env bash
# Opens the pumpkin face full screen on the first display and, if a side-show window is set to hdmi, the creature
# window on the second display (the Pi 5's second HDMI port). Started at login by install_pi.sh.
cd "$(dirname "$0")"
PY=.venv/bin/python; [ -x "$PY" ] || PY=python3
# WINDOW = name of the window on the Pi's 2nd HDMI port, or "-" when the side show is off or all windows are on Wi-Fi
read -r PORT WINDOW SCREEN_X < <("$PY" -c "
import config; c = config.load(); w = c['window']
hdmi = [n for n, s in config.screens(w).items() if s['hdmi']] if w['enabled'] else []
print(c['web']['port'], hdmi[0] if hdmi else '-', int(w['screen_x']))" 2>/dev/null || echo "8000 - 0")
URL="http://localhost:${PORT}"
for _ in $(seq 60); do curl -s -o /dev/null "$URL/" && break; sleep 1; done
BROWSER=$(command -v chromium || command -v chromium-browser)
FLAGS=(--kiosk --noerrdialogs --disable-infobars --no-first-run --incognito --disable-session-crashed-bubble
       --check-for-update-interval=31536000 --autoplay-policy=no-user-gesture-required)

if [ "$WINDOW" != "-" ]; then
  # x position of the second monitor, from xrandr (e.g. "1: +HDMI-A-2 1920/530x1080/300+1920+0  HDMI-A-2")
  if [ "$SCREEN_X" = "0" ] && command -v xrandr >/dev/null; then
    SCREEN_X=$(xrandr --listmonitors | awk 'NR>1 {split($3, a, "+"); if (a[2] > 0) {print a[2]; exit}}')
  fi
  "$BROWSER" "${FLAGS[@]}" --user-data-dir=/tmp/pumpkin-window --window-position="${SCREEN_X:-1920},0" "$URL/window.html?w=$WINDOW" &
fi
exec "$BROWSER" "${FLAGS[@]}" --user-data-dir=/tmp/pumpkin-face --window-position=0,0 "$URL/"
