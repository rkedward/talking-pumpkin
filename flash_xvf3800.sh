#!/usr/bin/env bash
# Puts the USB firmware on a reSpeaker XVF3800 mic array, so it works as a USB microphone with voice
# direction. Needed once for the "with XIAO ESP32S3" version, which ships with I2S firmware.
#
# 1. Plug the Pi into the USB-C port on the round mic board (not the one on the small XIAO module).
# 2. Unplug it again, hold the Mute button, plug it back in while holding, release when the red LED blinks
#    (Safe Mode).
# 3. Run:  bash flash_xvf3800.sh
set -euo pipefail
cd "$(dirname "$0")"
VERSION="${1:-v2.0.10}"
FILE="respeaker_xvf3800_usb_dfu_firmware_${VERSION}.bin"
URL="https://raw.githubusercontent.com/respeaker/reSpeaker_XVF3800_USB_4MIC_ARRAY/master/xmos_firmwares/usb/${FILE}"

command -v dfu-util >/dev/null || sudo apt-get install -y dfu-util
mkdir -p models/firmware
[ -f "models/firmware/$FILE" ] || curl -fL -o "models/firmware/$FILE" "$URL"

echo "Looking for the mic array in Safe Mode..."
if ! sudo dfu-util -l | grep -q "2886:001a"; then
  echo "Not found. Hold Mute while plugging the mic array in (red LED blinking), then run this again."
  exit 1
fi
sudo dfu-util -R -e -a 1 -D "models/firmware/$FILE"
echo
echo "Done. Unplug and replug the mic array. Check it with:  arecord -l   (look for XVF3800)"
