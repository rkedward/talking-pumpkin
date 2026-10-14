"""Prints the settings start.ps1 needs, as JSON: web port, which display gets the face, and the side-show
window plugged into the laptop's HDMI (if any)."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config  # noqa: E402

cfg = config.load()
w = cfg["window"]
hdmi = [n for n, s in config.screens(w).items() if s["hdmi"]] if w["enabled"] else []
print(json.dumps({"port": int(cfg["web"]["port"]), "face_screen": int(cfg["face"].get("screen", 0)),
                  "hdmi_window": hdmi[0] if hdmi else ""}))
