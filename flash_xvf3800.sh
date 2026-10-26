#!/usr/bin/env bash
# Puts the USB firmware on a reSpeaker XVF3800 mic array, so it works as a USB microphone with voice
# direction. Needed once for the "with XIAO ESP32S3" version, which ships with I2S firmware.
#
# 1. Plug the Pi into the USB-C port on the round mic board (not the one on the small XIAO module).
# 2. Unplug it again, hold the Mute button, plug it back in while holding, release when the red LED blinks
#    (Safe Mode).
# 3. Run:  bash flash_xvf3800.sh            (or: bash flash_xvf3800.sh /path/to/firmware.bin)
#
# Seeed moves and renames the firmware files between releases, so instead of a fixed URL this clones
# their repository and picks the newest standard USB DFU image in it.
set -euo pipefail
cd "$(dirname "$0")"
REPO="https://github.com/respeaker/reSpeaker_XVF3800_USB_4MIC_ARRAY"
SRC="models/firmware/reSpeaker_XVF3800_USB_4MIC_ARRAY"

command -v dfu-util >/dev/null || sudo apt-get install -y dfu-util
command -v git >/dev/null || sudo apt-get install -y git

if [ $# -ge 1 ]; then
  FW="$1"
else
  mkdir -p models/firmware
  if [ -d "$SRC/.git" ]; then
    git -C "$SRC" pull --ff-only -q || true
  else
    git clone --depth 1 -q "$REPO" "$SRC"
  fi
  # Newest standard image: respeaker_xvf3800_usb_dfu_firmware_vX.Y.Z.bin (not the _16k6ch / _48k2ch variants).
  FW=$(find "$SRC" -type f -iname 'respeaker_xvf3800_usb_dfu_firmware_v*.bin' -not -path '*old*' \
         | grep -Ev '_[0-9]+k[0-9]+ch\.bin$' | sort -V | tail -n 1 || true)
  if [ -z "$FW" ]; then
    # Fall back to any USB DFU image if the naming changed.
    FW=$(find "$SRC" -type f -iname '*usb*dfu*.bin' | sort -V | tail -n 1 || true)
  fi
fi
if [ -z "${FW:-}" ] || [ ! -f "$FW" ]; then
  echo "Couldn't find a USB DFU firmware file. Available .bin files:"
  find "$SRC" -type f -name '*.bin' 2>/dev/null || true
  echo "Run again with the right one:  bash flash_xvf3800.sh /path/to/file.bin"
  exit 1
fi
if [ "$(stat -c %s "$FW")" -lt 100000 ]; then
  echo "$FW is too small to be firmware (Git LFS pointer?). Download it from $REPO and pass its path."
  exit 1
fi
echo "Firmware: $FW"

echo "Looking for the mic array in Safe Mode..."
if ! sudo dfu-util -l | grep -q "2886:001a"; then
  echo "Not found. Hold Mute while plugging the mic array in (red LED blinking), then run this again."
  exit 1
fi
sudo dfu-util -R -e -a 1 -D "$FW"
echo
echo "Done. Unplug and replug the mic array. Check it with:  arecord -l   (look for XVF3800)"
