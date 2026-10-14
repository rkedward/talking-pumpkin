"""Downloads the models the pumpkin needs (Windows installer; the Pi installer does the same in bash):
the person detector, Piper voices (the assistants' too once the side show is on) and the Whisper model."""

import subprocess
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config  # noqa: E402

DETECTOR_URL = ("https://storage.googleapis.com/download.tensorflow.org/models/tflite/task_library/"
                "object_detection/rpi/lite-model_efficientdet_lite0_detection_metadata_1.tflite")
ASSISTANT_VOICES = ["en_US-amy-medium", "en_US-lessac-medium", "en_GB-alan-medium"]


def main():
    cfg = config.load()
    det = config.resolve(cfg["detector"]["model"])
    det.parent.mkdir(parents=True, exist_ok=True)
    if not det.exists():
        print("downloading the person detector...")
        urllib.request.urlretrieve(DETECTOR_URL, det)

    voices_dir = config.resolve("models/voices")
    voices_dir.mkdir(parents=True, exist_ok=True)
    voices = [Path(cfg["tts"]["piper_voice"]).stem]
    if cfg["window"]["enabled"]:
        voices += ASSISTANT_VOICES
    for v in voices:
        if not (voices_dir / f"{v}.onnx").exists():
            print(f"downloading voice {v}...")
            subprocess.run([sys.executable, "-m", "piper.download_voices", "--download-dir", str(voices_dir), v], check=True)

    from faster_whisper import WhisperModel
    stt = cfg["stt"]
    print(f"getting the speech recognition model ({stt['model']})...")
    WhisperModel(stt["model"], device="cpu", compute_type=stt["compute_type"],
                 download_root=str(config.resolve("models/whisper")))
    print("models ready")


if __name__ == "__main__":
    main()
