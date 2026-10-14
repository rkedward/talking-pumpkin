#!/usr/bin/env bash
# Talking pumpkin installer for Raspberry Pi 5 (Raspberry Pi OS 64-bit with desktop, Bookworm or newer).
# Run from the pumpkin folder:   bash install_pi.sh
# Safe to run again; it skips what's already done.
set -euo pipefail
cd "$(dirname "$0")"
DIR="$(pwd)"

echo "== System packages"
sudo apt-get update
sudo apt-get install -y python3-venv python3-pip python3-numpy python3-opencv python3-picamera2 \
  python3-lgpio python3-gpiozero libportaudio2 libusb-1.0-0 espeak-ng i2c-tools dfu-util x11-xserver-utils
if ! command -v chromium >/dev/null && ! command -v chromium-browser >/dev/null; then
  sudo apt-get install -y chromium || sudo apt-get install -y chromium-browser
fi

echo "== Enable I2C (for the PCA9685 servo board)"
sudo raspi-config nonint do_i2c 0 || true

echo "== Python environment"
# System site packages give the venv apt's picamera2, numpy, OpenCV and lgpio (pip builds of those
# conflict with picamera2).
[ -d .venv ] || python3 -m venv --system-site-packages .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

echo "== Models (person detector, voice, speech recognition)"
mkdir -p models/voices models/whisper
[ -f models/efficientdet_lite0.tflite ] || curl -L -o models/efficientdet_lite0.tflite \
  https://storage.googleapis.com/download.tensorflow.org/models/tflite/task_library/object_detection/rpi/lite-model_efficientdet_lite0_detection_metadata_1.tflite
VOICE=$(.venv/bin/python -c "import config; from pathlib import Path; print(Path(config.load()['tts']['piper_voice']).stem)")
# the pumpkin's voice, plus the assistants' voices (Boo, the Peepers, Knuckles) once the side show is on
VOICES="$VOICE"
if .venv/bin/python -c "import config, sys; sys.exit(0 if config.load()['window']['enabled'] else 1)"; then
  VOICES="$VOICES en_US-amy-medium en_US-lessac-medium en_GB-alan-medium"
fi
for V in $VOICES; do
  [ -f "models/voices/$V.onnx" ] || .venv/bin/python -m piper.download_voices --download-dir models/voices "$V"
done
.venv/bin/python - <<'EOF'
import config
from faster_whisper import WhisperModel
cfg = config.load()["stt"]
WhisperModel(cfg["model"], device="cpu", compute_type=cfg["compute_type"], download_root=str(config.resolve("models/whisper")))
print("whisper model ready:", cfg["model"])
EOF

echo "== ReSpeaker USB mic array access without sudo (XVF3800 and v2.0, including firmware update mode)"
echo 'SUBSYSTEM=="usb", ATTRS{idVendor}=="2886", MODE="0666"' \
  | sudo tee /etc/udev/rules.d/60-respeaker.rules >/dev/null
sudo udevadm control --reload-rules && sudo udevadm trigger || true

echo "== Settings file"
[ -f config.toml ] || cp config.example.toml config.toml
if ! grep -q '^ANTHROPIC_API_KEY=.\+' .env 2>/dev/null; then
  read -r -p "Claude API key (leave blank to run in fake mode for now): " KEY || KEY=""
  echo "ANTHROPIC_API_KEY=$KEY" > .env
  if [ -z "$KEY" ]; then echo "PUMPKIN_FAKE=1" >> .env; fi
  chmod 600 .env
fi

echo "== Start the brain at login (systemd user service)"
mkdir -p ~/.config/systemd/user
cat > ~/.config/systemd/user/pumpkin.service <<EOF
[Unit]
Description=Talking pumpkin brain
After=pipewire.service

[Service]
WorkingDirectory=$DIR
EnvironmentFile=$DIR/.env
ExecStart=$DIR/.venv/bin/python -u main.py
Restart=always
RestartSec=3

[Install]
WantedBy=default.target
EOF
systemctl --user daemon-reload
systemctl --user enable pumpkin.service

echo "== Show the face full screen on the projector at login"
chmod +x kiosk.sh
mkdir -p ~/.config/autostart
cat > ~/.config/autostart/pumpkin-kiosk.desktop <<EOF
[Desktop Entry]
Type=Application
Name=Talking Pumpkin face
Exec=$DIR/kiosk.sh
EOF
# Use the X11 desktop: it lets the face and the side-show window each open full screen on their own
# projector (Wayland ignores window positions).
sudo raspi-config nonint do_wayland W1 || true

echo
echo "Done. Reboot (sudo reboot) and the pumpkin starts by itself."
echo "To start now:   systemctl --user start pumpkin && ./kiosk.sh"
echo "Logs:           journalctl --user -u pumpkin -f"
