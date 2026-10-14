"""Speech in (mic + voice activity detection + local Whisper) and speech out (Piper neural TTS, ElevenLabs
or espeak) with mouth movement driven by the actual loudness of the audio being played."""

import io
import json
import queue
import re
import shutil
import subprocess
import threading
import time
import urllib.request
import wave
from pathlib import Path

import numpy as np

from config import resolve

try:
    import sounddevice as sd
except Exception:  # PortAudio missing: run without sound (typed questions, silent speech)
    sd = None


def _find_device(name, kind):
    if not sd or not name:
        return None
    for i, d in enumerate(sd.query_devices()):
        if name.lower() in d["name"].lower() and d[f"max_{kind}_channels"] > 0:
            return i
    return None


# --------------------------------------------------------------------------------------------- mic

class Microphone:
    """Continuously reads 30 ms frames into a queue. Frames are dropped while the pumpkin is talking."""

    FRAME_S = 0.03

    def __init__(self, cfg, log):
        self.cfg, self.log = cfg, log
        self.rate = int(cfg["rate"])
        self.frames = queue.Queue(maxsize=400)
        self.muted_until = 0.0
        self.user_muted = False
        self.ok = False
        if not sd:
            log("mic: sounddevice/PortAudio not available; type questions in the debug panel")
            return
        dev = _find_device(cfg["device"], "input")
        if dev is None:
            dev = _find_device("xvf", "input")   # XMOS arrays sometimes enumerate without "ReSpeaker"
        try:
            info = sd.query_devices(dev, "input")
            want = cfg["channel"]
            if want == "auto":
                # XVF3800 USB firmware: channel 1 is tuned for speech recognition (channel 0 is the
                # "conference" mix). ReSpeaker v2.0 and plain mics: channel 0.
                want = 1 if "xvf3800" in info["name"].lower() else 0
            channels = max(1, min(int(info["max_input_channels"]), int(want) + 1))
            self.channel = min(int(want), channels - 1)
            self.stream = sd.InputStream(device=dev, samplerate=self.rate, channels=channels, dtype="int16",
                                         blocksize=int(self.rate * self.FRAME_S), callback=self._callback)
            self.stream.start()
            self.ok = True
            log(f"mic: {info['name']} (channel {self.channel})")
        except Exception as exc:
            log(f"mic: could not open ({exc}); type questions in the debug panel")

    def _callback(self, indata, frames, t, status):
        if self.user_muted or time.time() < self.muted_until:
            return
        try:
            self.frames.put_nowait(indata[:, self.channel].copy())
        except queue.Full:
            pass

    def mute_for(self, seconds):
        self.muted_until = max(self.muted_until, time.time() + seconds)

    def flush(self):
        while not self.frames.empty():
            self.frames.get_nowait()


class Listener:
    """Waits for one utterance using an adaptive energy threshold, then transcribes it."""

    def __init__(self, mic, cfg, stt):
        self.mic, self.cfg, self.stt = mic, cfg, stt
        self.noise = 150.0

    def listen(self, timeout_s, typed, should_stop, on_speech=None):
        """Returns heard text, a typed question, or None after timeout_s of nobody speaking."""
        self.mic.flush()
        deadline = time.time() + timeout_s
        pre_roll, voiced, silent, speech = [], [], 0, False
        frame_s = Microphone.FRAME_S
        while True:
            if should_stop():
                return None
            try:
                return typed.get_nowait()
            except queue.Empty:
                pass
            if not speech and time.time() > deadline:
                return None
            if not self.mic.ok or self.stt is None:
                time.sleep(0.05)
                continue
            try:
                frame = self.mic.frames.get(timeout=0.1)
            except queue.Empty:
                continue
            rms = float(np.sqrt(np.mean(frame.astype(np.float32) ** 2)))
            loud = rms > max(self.noise * float(self.cfg["start_ratio"]), float(self.cfg["min_rms"]))
            if not speech:
                pre_roll = (pre_roll + [frame])[-10:]          # keep 300 ms before speech starts
                voiced = voiced + [frame] if loud else []
                if not loud:
                    self.noise = 0.95 * self.noise + 0.05 * rms  # track background noise
                if len(voiced) >= 3:
                    speech, silent = True, 0
                    chunks = pre_roll
                    if on_speech:
                        on_speech()
            else:
                chunks.append(frame)
                silent = 0 if loud else silent + 1
                too_long = len(chunks) * frame_s > float(self.cfg["max_utterance_s"])
                if silent * frame_s >= float(self.cfg["silence_end_s"]) or too_long:
                    audio = np.concatenate(chunks).astype(np.float32) / 32768.0
                    text = self.stt.transcribe(audio, self.mic.rate)
                    if text:
                        return text
                    # Nothing intelligible: keep listening until the deadline.
                    speech, pre_roll, voiced = False, [], []
                    deadline = max(deadline, time.time() + 2)


# --------------------------------------------------------------------------------------------- STT

_HALLUCINATIONS = {"", "you", "thank you.", "thanks for watching!", "thank you for watching.", ".", "bye."}


class WhisperSTT:
    """Local speech recognition with faster-whisper; no audio leaves the device."""

    def __init__(self, cfg, log):
        from faster_whisper import WhisperModel
        self.log = log
        started = time.time()
        self.model = WhisperModel(cfg["model"], device="cpu", compute_type=cfg["compute_type"],
                                  cpu_threads=int(cfg["threads"]), download_root=str(resolve("models/whisper")))
        log(f"speech recognition: whisper {cfg['model']} loaded in {time.time() - started:.1f}s")

    def transcribe(self, audio, rate):
        if rate != 16000:
            n = int(len(audio) * 16000 / rate)
            audio = np.interp(np.linspace(0, len(audio), n, endpoint=False), np.arange(len(audio)), audio).astype(np.float32)
        started = time.time()
        segments, _ = self.model.transcribe(
            audio, language="en", beam_size=1, condition_on_previous_text=False,
            initial_prompt="Kids trick-or-treating on Halloween talking to a jack-o'-lantern.")
        parts = [s.text for s in segments if s.no_speech_prob < 0.6 and s.avg_logprob > -1.2]
        text = " ".join(p.strip() for p in parts).strip()
        if text.lower() in _HALLUCINATIONS or re.fullmatch(r"[\W_]*", text):
            text = ""
        self.log(f"(heard in {time.time() - started:.1f}s: {text!r})")
        return text


# --------------------------------------------------------------------------------------------- TTS

def _shift_pitch(samples, semitones):
    """Lower/raise pitch by resampling. The caller pre-compensates speed so the duration stays natural."""
    if not semitones:
        return samples
    ratio = 2 ** (semitones / 12)
    n = int(len(samples) / ratio)
    return np.interp(np.linspace(0, len(samples) - 1, n), np.arange(len(samples)), samples.astype(np.float32)).astype(np.int16)


_PIPER_MODELS = {}   # voice file -> loaded model, shared by the pumpkin and its assistants


def piper_voice_path(name):
    """A Piper voice by name ("en_GB-alan-medium") or path; names live in models/voices/."""
    return resolve(name if ("/" in name or "\\" in name or name.endswith(".onnx")) else f"models/voices/{name}.onnx")


class PiperTTS:
    def __init__(self, cfg, log):
        from piper import PiperVoice, SynthesisConfig
        self.SynthesisConfig = SynthesisConfig
        path = str(piper_voice_path(cfg["piper_voice"]))
        if path not in _PIPER_MODELS:
            _PIPER_MODELS[path] = PiperVoice.load(path)
        self.voice = _PIPER_MODELS[path]
        self.length_scale = float(cfg["piper_length_scale"])
        self.semitones = float(cfg["pitch_semitones"])
        # chorus: extra copies of the voice at these pitch offsets, mixed in (a crowd speaking together)
        self.chorus = [float(v) for v in cfg.get("chorus", [])]
        log(f"voice: piper {Path(path).stem}, pitch {self.semitones:+g}" + (" (chorus)" if self.chorus else ""))

    def _one(self, text, semitones):
        ratio = 2 ** (semitones / 12)
        # Speak faster by `ratio`, then resample down: lower pitch at the original pace.
        syn = self.SynthesisConfig(length_scale=self.length_scale * ratio)
        chunks = list(self.voice.synthesize(text, syn))
        if not chunks:
            return np.zeros(0, np.int16), 22050
        audio = np.concatenate([np.frombuffer(c.audio_int16_bytes, np.int16) for c in chunks])
        return _shift_pitch(audio, semitones), chunks[0].sample_rate

    def synth(self, text):
        audio, rate = self._one(text, self.semitones)
        if not self.chorus or not len(audio):
            return audio, rate
        mix = audio.astype(np.float32)
        for i, offset in enumerate(self.chorus):
            extra, _ = self._one(text, self.semitones + offset)
            start = int(rate * 0.035 * (i + 1))          # slightly out of step, like several voices
            extra = extra[:max(0, len(mix) - start)].astype(np.float32)
            mix[start:start + len(extra)] += extra * 0.7
        mix *= min(1.0, 32000 / max(np.abs(mix).max(), 1))
        return mix.astype(np.int16), rate


class ElevenLabsTTS:
    """Cloud character voices. Needs ELEVENLABS_API_KEY and a voice id from your ElevenLabs voice library."""

    RATE = 22050

    def __init__(self, cfg, log):
        import os
        self.key = os.environ.get("ELEVENLABS_API_KEY", "")
        self.voice_id = cfg["elevenlabs_voice_id"]
        self.model = cfg["elevenlabs_model"]
        if not self.key or not self.voice_id:
            raise RuntimeError("set ELEVENLABS_API_KEY and tts.elevenlabs_voice_id")
        log(f"voice: ElevenLabs {self.voice_id}")

    def synth(self, text):
        req = urllib.request.Request(
            f"https://api.elevenlabs.io/v1/text-to-speech/{self.voice_id}?output_format=pcm_{self.RATE}",
            data=json.dumps({"text": text, "model_id": self.model}).encode(),
            headers={"xi-api-key": self.key, "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=20) as r:
            return np.frombuffer(r.read(), np.int16), self.RATE


class EspeakTTS:
    """Robotic but zero-setup fallback (sudo apt install espeak-ng)."""

    def __init__(self, cfg, log):
        self.exe = shutil.which("espeak-ng") or shutil.which("espeak")
        if not self.exe:
            raise RuntimeError("espeak-ng not installed")
        self.voice = cfg["espeak_voice"]
        self.pitch = int(np.clip(50 + float(cfg["pitch_semitones"]) * 4, 0, 99))
        log(f"voice: espeak {self.voice}")

    def synth(self, text):
        wav = subprocess.run([self.exe, "-v", self.voice, "-p", str(self.pitch), "-s", "155", "--stdout", text],
                             capture_output=True, check=True).stdout
        with wave.open(io.BytesIO(wav)) as w:
            return np.frombuffer(w.readframes(w.getnframes()), np.int16), w.getframerate()


def make_tts(cfg, log):
    engines = {"piper": PiperTTS, "elevenlabs": ElevenLabsTTS, "espeak": EspeakTTS}
    order = [cfg["engine"]] + [e for e in ("piper", "espeak") if e != cfg["engine"]]
    if cfg["engine"] == "none" or not sd:
        log("voice: no audio output; the face will mouth the words silently")
        return None
    for name in order:
        try:
            return engines[name](cfg, log)
        except Exception as exc:
            log(f"voice: {name} unavailable ({exc})")
    log("voice: no TTS engine available; the face will mouth the words silently")
    return None


# --------------------------------------------------------------------------------------------- speaker

def _sentences(text):
    return [s.strip() for s in re.findall(r"[^.!?]+[.!?]*", text) if s.strip()] or [text]


class Speaker:
    """Plays speech sentence by sentence (the next sentence is synthesized while the current one plays) and
    reports a 0..1 mouth-opening level from the loudness of the audio as it is heard."""

    BLOCK_S = 1 / 60

    def __init__(self, tts, cfg, mic, log):
        self.tts, self.mic, self.log = tts, mic, log
        self.device = _find_device(cfg["output_device"], "output")

    def speak(self, text, on_level, on_sentence=None, should_stop=lambda: False):
        sentences = _sentences(text)
        ready = queue.Queue()

        def producer():
            for s in sentences:
                if should_stop():
                    break
                try:
                    audio, rate = self.tts.synth(s) if self.tts else (None, None)
                except Exception as exc:
                    self.log(f"voice error: {exc}")
                    audio, rate = None, None
                ready.put((s, audio, rate))
            ready.put(None)

        threading.Thread(target=producer, daemon=True).start()
        while True:
            item = ready.get()
            if item is None or should_stop():
                break
            sentence, audio, rate = item
            if on_sentence:
                on_sentence(sentence)
            if audio is None or len(audio) == 0:
                self._mime(sentence, on_level, should_stop)
            else:
                self._play(audio, rate, on_level, should_stop)
        on_level(0.0)

    def _play(self, audio, rate, on_level, should_stop):
        block = max(1, int(rate * self.BLOCK_S))
        n_blocks = int(np.ceil(len(audio) / block))
        padded = np.zeros(n_blocks * block, np.int16)
        padded[:len(audio)] = audio
        blocks = padded.reshape(n_blocks, block)
        rms = np.sqrt(np.mean(blocks.astype(np.float32) ** 2, axis=1))
        ref = max(np.percentile(rms, 90), 1.0)
        levels = np.clip(rms / ref, 0, 1) ** 0.6
        self.mic.mute_for(len(audio) / rate + 0.4)   # don't listen to ourselves
        with sd.OutputStream(samplerate=rate, channels=1, dtype="int16", device=self.device,
                             blocksize=block, latency="low") as stream:
            delay = int(round((stream.latency or 0) / self.BLOCK_S))  # blocks written but not yet heard
            for i in range(n_blocks):
                if should_stop():
                    break
                stream.write(blocks[i])
                on_level(float(levels[i - delay]) if i >= delay else 0.0)
            for i in range(max(0, n_blocks - delay), n_blocks):
                on_level(float(levels[i]))
                time.sleep(self.BLOCK_S)
        on_level(0.0)

    def _mime(self, sentence, on_level, should_stop):
        """No audio available: move the mouth at a speaking pace so the face still 'talks'."""
        end = time.time() + 0.33 * len(sentence.split()) + 0.2
        while time.time() < end and not should_stop():
            t = time.time()
            on_level(abs(np.sin(t * 10.5)) * (0.6 + 0.4 * np.sin(t * 3.1)))
            time.sleep(self.BLOCK_S)
        on_level(0.0)
