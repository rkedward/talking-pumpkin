#!/usr/bin/env python3
"""Talking pumpkin: the brain. Watches for trick-or-treaters, greets them with Claude, listens and answers,
moves the eyes, mouth and props. The face itself is drawn by static/index.html in a (kiosk) browser.

Run:  python3 main.py      then open http://localhost:8000 (the Pi installer does both at boot)
"""

import json
import math
import queue
import random
import socket
import sys
import threading
import time

import brain
import config
from audio import Listener, Microphone, Speaker, WhisperSTT, make_tts
from align import Aligner
from doa import ReSpeakerDOA
from home import Home
from props import Props
from sideshow import SideShow
from vision import Vision
from web import Hub, serve

FILLERS = [
    "Ooh! Who goes there?", "Well, well, well, what have we here?", "Hey! Come closer, let me see you!",
    "Ooh, visitors! Let me get a good look at you.", "Halloo there! Hold still, let me see that costume.",
]
WRAPUPS = [
    "I'd love to chat all night, but more trick-or-treaters are coming. Grab some candy and have a spook-tacular Halloween! Ho ho ho!",
    "Okay, my candle's flickering! Take some candy, and happy Halloween! Hee hee!",
]
GOODBYES = ["Bye bye! Happy Halloween! Ho ho ho!", "See you later, alligator! Happy haunting!", "Bye bye! Hee hee, that was fun!"]
BUTLER_LINES = [
    "Ding dong! Visitors, sir! Allow me to get the lights.",
    "Someone's at the door! I'll put the lights on and wake up the master pumpkin.",
    "Ah, guests! One moment while I fetch the lights. Master Jack, you have visitors!",
]
STATE_FILE = config.ROOT / "state.json"
NO_CALIB = {"x": 0.0, "y": 0.0, "scale": 1.0, "rot": 0.0, "mirror": False}


def lan_ip():
    """This Pi's address on the home network (what the window projectors open)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
    except OSError:
        return "this-pi's-address"


class Pumpkin:
    def __init__(self, cfg):
        self.cfg = cfg
        self.hub = Hub()
        self.state = "starting"
        self.awake = False
        self.speaking = False
        self.mouth = 0.0
        self.abort_visit = False
        self.force_greet = False
        self.typed = queue.Queue()
        saved = json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}
        self.gaze_flip = saved.get("gaze_flip", cfg["face"]["gaze_flip"])
        self.calib = saved.get("calib")
        self.face_warp = saved.get("face_warp")   # auto-alignment of the face projector (align.py)
        self.screens = config.screens(cfg["window"])
        wc = saved.get("window_calib") or {}
        if "x" in wc:                       # older single-window state.json
            wc = {next(iter(self.screens)): wc}
        self.window_calib = {n: wc.get(n) or dict(NO_CALIB) for n in self.screens}
        self.guide = False
        self.doorbell_pending = False
        self.hide_idle = bool(cfg["face"]["hide_when_idle"])
        self.look_window_until = 0.0
        self.look_gaze = [0.0, 0.0]
        self.summons = 0
        self.test_index = 0

        if self.calib:
            self.hub.publish({"t": "calib", "calib": self.calib})
        self.hub.publish({"t": "face_warp", "warp": self.face_warp})
        self.aligner = Aligner(self._get_warp, self._set_warp, self.hub, self.log)
        for n, c in self.window_calib.items():
            self.hub.publish({"t": "window_calib", "screen": n, "calib": c})
        port = cfg["web"]["port"]
        wifi_windows = [n for n, sc in self.screens.items() if not sc["hdmi"]] if cfg["window"]["enabled"] else []
        if (wifi_windows or cfg["home"]["enabled"]) and cfg["web"]["host"] in ("127.0.0.1", "localhost"):
            cfg["web"]["host"] = "0.0.0.0"   # the Wi-Fi projectors / smart home have to reach this Pi
        self.home = Home(cfg["home"], self.log)
        self.hub.publish({"t": "show", "on": not self.hide_idle})
        serve(cfg["web"], self.hub, self)
        self.log(f"face page on http://localhost:{port}")
        for n in wifi_windows:
            self.log(f"window '{n}': open http://{lan_ip()}:{port}/window.html?w={n} on its projector")
        self.log("claude: fake mode (canned replies)" if cfg["claude"]["fake"] else f"claude: {cfg['claude']['model']}")
        self.show = None   # set below; the web panel can ask for status while the rest is still loading
        self.props = Props(cfg["props"], self.log)
        self.vision = Vision(cfg["camera"], cfg["detector"], self.log)
        self.doa = ReSpeakerDOA(cfg["doa"], self.log) if cfg["doa"]["enabled"] else None
        self.mic = Microphone(cfg["mic"], self.log)
        stt = None
        if cfg["stt"]["engine"] == "whisper":
            try:
                stt = WhisperSTT(cfg["stt"], self.log)
            except Exception as exc:
                self.log(f"speech recognition off ({type(exc).__name__}: {exc}); type questions in the debug panel")
        self.listener = Listener(self.mic, cfg["mic"], stt)
        self.speaker = Speaker(make_tts(cfg["tts"], self.log), cfg["tts"], self.mic, self.log)
        Speaker.volume = float(saved.get("volume", 1.0))
        self.show = None
        if cfg["window"]["enabled"]:
            self.show = SideShow(cfg["window"], cfg["tts"], self.mic, self.hub, self.log)
            brain.configure(cfg["claude"], self.show.creatures,
                            {n: sc["where"] for n, sc in self.screens.items()}, self.show.online)
        else:
            brain.configure(cfg["claude"])
        threading.Thread(target=self._face_loop, daemon=True, name="face").start()

    # ---- helpers -------------------------------------------------------------------------------
    def log(self, text, cls="info"):
        print(f"[{cls}] {text}", flush=True)
        self.hub.publish({"t": "log", "cls": cls, "text": text})

    def set_state(self, s):
        self.state = s
        self.hub.publish({"t": "state", "state": s})

    def say(self, text):
        if not text:
            return
        self.log(f"🎃 {text}", "said")
        self.speaking = True
        self.speaker.speak(text, on_level=self._set_mouth,
                           on_sentence=self._on_sentence,
                           should_stop=lambda: self.abort_visit)
        self.speaking = False
        self.mouth = 0.0
        self.props.expression("happy" if self.awake else "neutral")

    def _on_sentence(self, sentence):
        expr = self.props.expression_for(sentence)
        self.props.expression(expr)
        if expr == "laughing":   # the face squints and bounces while he laughs at his own joke
            self.hub.publish({"t": "laugh", "ms": int(400 + 280 * len(sentence.split()))})

    def sideshow(self, result):
        """Act on Claude's side-show choices: summon a creature, let it talk."""
        if not self.show:
            return
        name = result.get("summon")
        if name and self.summons < int(self.cfg["window"]["max_summons"]) and self.show.summon(name, result.get("window", "")):
            self.summons += 1
            self.look_gaze = self.screens[self.show.screen]["gaze"]
            self.look_window_until = time.time() + 3
            self.home.send("summon", creature=name, window=self.show.screen)
            self.props.expression("sly")
            time.sleep(1.2)                       # let the creature appear before it speaks
        if result.get("creature_says") and self.show.active():
            self.look_window_until = time.time() + 2
            self.show.speak(result["creature_says"], should_stop=lambda: self.abort_visit)
        if result.get("fly_to") and self.show.active() and not self.abort_visit:
            self.show.fly_to(result["fly_to"], on_leave=self._follow)

    def _follow(self, screen):
        """The pumpkin's eyes follow a creature flying to another window."""
        self.look_gaze = self.screens[screen]["gaze"]
        self.look_window_until = time.time() + 1.1 + self.show.fly_gap + 2.5

    def _set_mouth(self, level):
        self.mouth = level

    def present(self):
        _, _, _, last = self.vision.state()
        return last and time.time() - last < float(self.cfg["visit"]["gone_s"])

    def arrived(self):
        people, _, first, _ = self.vision.state()
        return bool(people) and time.time() - first >= float(self.cfg["visit"]["arrive_s"])

    # ---- eyes ----------------------------------------------------------------------------------
    def _face_loop(self):
        hfov = self.vision.hfov
        while True:
            people, target, _, _ = self.vision.state()
            if self.show:
                self.show.active()   # sends the creature away once its time is up
            gaze, look_at = None, None
            voice = self.doa.bearing() if self.doa and self.doa.available and not self.speaking else None
            if voice is not None:
                near = min(people, key=lambda p: abs(self.vision.bearing(p) - voice), default=None)
                if near and abs(self.vision.bearing(near) - voice) <= float(self.cfg["doa"]["match_deg"]):
                    self.vision.prefer_bearing(voice)
                    look_at = near
                else:
                    gaze = (voice, 0.1)   # a voice from someone the camera can't see: look that way
            elif target:
                look_at = target
            if look_at:
                gaze = (self.vision.bearing(look_at), ((look_at["y"] + look_at["h"] * 0.12) - 0.35) * 2.2)
            ev = {"t": "face", "awake": self.awake, "speaking": self.speaking, "mouth": round(self.mouth, 3)}
            if time.time() < self.look_window_until:
                ev["gaze"] = list(self.look_gaze)   # glance at the creature's window
            elif gaze:
                # The camera faces the same way as the pumpkin: someone on the image's right is on the
                # pumpkin's right, which is the left side of the projected face. Hence the minus sign.
                gx = -gaze[0] / (hfov / 2) * 1.3 * (-1 if self.gaze_flip else 1)
                ev["gaze"] = [round(max(-1, min(1, gx)), 3), round(max(-1, min(1, gaze[1])), 3)]
            self.hub.publish(ev)
            time.sleep(1 / 30)

    # ---- visits --------------------------------------------------------------------------------
    def reveal(self, on):
        """Light the pumpkin up (or let it go dark) when hide_when_idle is set."""
        if self.hide_idle:
            self.hub.publish({"t": "show", "on": on})

    def butler_intro(self):
        """The doorbell rang: the butler appears, the smart home turns on a light, then the pumpkin lights up."""
        h = self.cfg["home"]
        self.home.send("doorbell", butler=h["butler"])
        if self.show and self.show.find(h["butler"]) and self.show.summon(h["butler"], h["butler_window"]):
            self.summons += 1
            self.look_gaze = self.screens[self.show.screen]["gaze"]
            self.look_window_until = time.time() + 4
            time.sleep(1.2)
            self.show.speak(random.choice(BUTLER_LINES), should_stop=lambda: self.abort_visit)
        time.sleep(float(h["reveal_delay_s"]))

    def visit(self, forced):
        v = self.cfg["visit"]
        self.abort_visit = False
        self.summons = 0
        doorbell, self.doorbell_pending = self.doorbell_pending, False
        if doorbell:
            self.set_state("doorbell")
            self.butler_intro()
        self.reveal(True)
        self.home.send("visit_start", doorbell=doorbell)
        self.awake = True
        self.hub.publish({"t": "surprise"})
        self.props.expression("surprised")
        self.props.arrival()
        self.set_state("greeting")
        people, _, _, _ = self.vision.state()
        result = {}

        def ask_claude():
            try:
                on_stage = self.show.active() if self.show else None
                note = (f"They rang the doorbell, and your butler {on_stage['name']} answered it and is still visible."
                        if doorbell and on_stage else "They rang the doorbell." if doorbell else "")
                result.update(brain.greet(self.vision.snapshot_b64(), max(1, len(people)), note))
            except Exception as exc:
                self.log(f"claude error: {type(exc).__name__}: {exc}")
                result.update({"session": "", "costumes": [], "say": brain.FALLBACK_SAY})

        worker = threading.Thread(target=ask_claude, daemon=True)
        worker.start()
        self.say(random.choice(FILLERS))      # covers the time Claude takes to look
        worker.join()
        if result.get("costumes"):
            self.log(f"costumes: {'; '.join(result['costumes'])}")
        session = result.get("session", "")
        self.say(result.get("say"))
        self.sideshow(result)

        started, turns = time.time(), 0
        while not self.abort_visit:
            if not forced and not self.present():
                self.say(random.choice(GOODBYES))
                break
            if turns >= int(v["max_turns"]) or time.time() - started > float(v["max_visit_s"]):
                self.say(random.choice(WRAPUPS))
                break
            self.set_state("listening")
            heard = self.listener.listen(float(v["listen_s"]), self.typed, lambda: self.abort_visit,
                                         on_speech=lambda: self.set_state("hearing"))
            if self.abort_visit:
                break
            if not heard:
                if forced and not self.present():
                    forced = False
                continue
            self.log(f"👂 {heard}", "heard")
            self.set_state("thinking")
            on_stage = self.show.active() if self.show else None
            try:
                reply = brain.chat(session, heard, f"{on_stage['name']} (in {self.show.screen})" if on_stage else None)
            except Exception as exc:
                self.log(f"claude error: {type(exc).__name__}: {exc}")
                reply = {"say": "Ooh, my pumpkin brain went fuzzy. Happy Halloween!"}
            self.say(reply["say"])
            self.sideshow(reply)
            turns += 1
        self.props.visit_over()
        if self.show:
            self.show.dismiss()
        self.home.send("visit_end")
        self.reveal(False)
        self.awake = False
        self.props.expression("neutral")

    def run(self):
        last_visit_end = -1e9
        while True:
            self.awake = False
            self.set_state("idle")
            # After a visit, don't re-greet the same kids until they step away (or regreet_s passes,
            # for when the next group steps up as the last one leaves).
            left = False
            while True:
                _, _, _, last = self.vision.state()
                people, _, _, _ = self.vision.state()
                if not people and time.time() - last > 1.5:
                    left = True
                if self.force_greet:
                    break
                ready = left or time.time() - last_visit_end > float(self.cfg["visit"]["regreet_s"])
                if ready and self.arrived():
                    break
                time.sleep(0.1)
            forced, self.force_greet = self.force_greet, False
            self.visit(forced)
            last_visit_end = time.time()
            self.set_state("cooldown")
            time.sleep(2.5)

    # ---- web interface -------------------------------------------------------------------------
    def command(self, name, data):
        if name == "greet":
            self.force_greet = True
            self.log("manual greet")
        elif name == "end":
            self.abort_visit = True
            self.log("visit ended")
        elif name == "flip":
            self.gaze_flip = not self.gaze_flip
            self._save()
            self.log(f"eye direction {'flipped' if self.gaze_flip else 'normal'}")
        elif name == "calib":
            calib = data.get("calib")
            if isinstance(calib, dict):
                self.calib = {k: float(v) for k, v in calib.items() if k in ("x", "y", "scale", "rot", "stretch")}
                self.hub.publish({"t": "calib", "calib": self.calib})
                self._save()
        elif name == "creature_done":
            if self.show:
                self.show.clip_finished(data.get("screen"))
        elif name == "window_seen":
            if not self.show:
                return {"error": "side show is off; set enabled = true under [window]"}
            if not self.show.checked_in(str(data.get("screen", ""))):
                return {"error": f"no window called '{data.get('screen')}' in config.toml",
                        "windows": list(self.screens)}
        elif name == "ghost_tour":
            if not self.show:
                return {"error": "side show is off; set enabled = true under [window]"}
            route = self.show.tour_order()
            ghost = next((c for c in self.show.creatures if c.get("flies")), None)
            if not ghost or len(route) < 2:
                return {"error": "a ghost tour needs the built-in ghost and at least two windows switched on"}
            threading.Thread(target=self._tour, args=(ghost["name"], route), daemon=True).start()
        elif name == "doorbell":
            if not self.home.allowed(data):
                return {"error": "home automation is off, or the key is wrong"}
            if self.state not in ("idle", "cooldown", "starting"):
                self.log("🔔 doorbell (already greeting someone)")
                return {"ok": True, "note": "busy"}
            self.log("🔔 doorbell")
            self.doorbell_pending = True
            self.force_greet = True
        elif name.startswith("align_"):
            return self.align_command(name, data)
        elif name == "window_identify":
            self.hub.publish({"t": "identify"})
        elif name == "summon":
            if not self.show or not self.show.creatures:
                return {"error": "side show is off; set enabled = true under [window]"}
            screen = str(data.get("screen", ""))
            fits = [c for c in self.show.creatures if self.show.place(c, screen) == screen] or self.show.creatures
            c = fits[self.test_index % len(fits)]
            self.test_index += 1
            if not self.show.summon(c["name"], screen):
                return {"error": "no window is switched on (open window.html on a projector)"}
            self.look_gaze = self.screens[self.show.screen]["gaze"]
            self.look_window_until = time.time() + 3
            threading.Thread(target=lambda: (time.sleep(1.2), self.show.speak("Hee hee! Hello there! Happy Halloween!", lambda: False)),
                             daemon=True).start()
        elif name == "window_adjust":
            screen = str(data.get("screen", ""))
            if screen not in self.window_calib:
                return {"error": "unknown window"}
            self.adjust_window(screen, str(data.get("key", "")))
        elif name == "guide":
            self.guide = not self.guide
            self.hub.publish({"t": "guide", "on": self.guide})
        elif name == "volume":
            try:
                Speaker.volume = min(1.5, max(0.0, float(data.get("percent", 100)) / 100))
            except (TypeError, ValueError):
                return {"error": "percent must be a number"}
            self._save()
            self.log(f"volume {round(Speaker.volume * 100)}%")
        elif name == "mute":
            self.mic.user_muted = not self.mic.user_muted
            self.log(f"mic {'muted' if self.mic.user_muted else 'on'}")
        elif name == "ask":
            text = str(data.get("text", ""))[:300].strip()
            if text:
                self.typed.put(text)
        else:
            return {"error": "unknown command"}
        return {"ok": True}

    def _tour(self, name, route):
        if not self.show.summon(name, route[0]):
            return
        self.look_gaze = self.screens[route[0]]["gaze"]
        self.look_window_until = time.time() + 3
        time.sleep(2.5)
        for nxt in route[1:]:
            if not self.show.fly_to(nxt, on_leave=self._follow):
                return
            time.sleep(2.2)
        self.show.speak("Wheee! Boo!", lambda: False)

    # ---- auto-alignment from a phone photo ----------------------------------------------------
    def _align_target(self, data):
        t = str(data.get("target", ""))
        return t if t == "face" or t in self.window_calib else None

    def _get_warp(self, target):
        return self.face_warp if target == "face" else self.window_calib[target].get("warp")

    def _set_warp(self, target, warp):
        if target == "face":
            self.face_warp = warp
            self.calib = {"x": 0.0, "y": 0.0, "scale": 0.9, "rot": 0.0, "stretch": 1.0}   # the fit replaces manual nudges
            self.hub.publish({"t": "calib", "calib": self.calib})
            self.hub.publish({"t": "face_warp", "warp": warp})
        else:
            w = self.window_calib[target]
            w.update(NO_CALIB)
            if warp:
                w["warp"] = warp
            else:
                w.pop("warp", None)
            self.hub.publish({"t": "window_calib", "screen": target, "calib": w})
        self._save()

    def align_command(self, name, data):
        target = self._align_target(data)
        if not target:
            return {"error": "pick the face or a window to align"}
        if name == "align_start":
            return self.aligner.start(target)
        if name == "align_photo":
            return self.aligner.photo(target, "face" if target == "face" else "window", str(data.get("image", "")))
        if name == "align_corners":
            return self.aligner.corners(target, data.get("corners") or [])
        if name == "align_done":
            return self.aligner.done(target)
        if name == "align_undo":
            self.aligner.done(target)
            self._set_warp(target, None)
            return {"ok": True, "msg": "Auto-alignment removed."}
        return {"error": "unknown command"}

    def adjust_window(self, screen, key):
        w = self.window_calib[screen]
        if w.get("warp"):
            return self._nudge_warp(screen, key)
        moves = {"left": ("x", -0.01), "right": ("x", 0.01), "up": ("y", -0.01), "down": ("y", 0.01),
                 "rotl": ("rot", -0.02), "rotr": ("rot", 0.02)}
        if key in moves:
            k, d = moves[key]
            w[k] = round(w[k] + d, 4)
        elif key == "bigger":
            w["scale"] = round(w["scale"] * 1.05, 4)
        elif key == "smaller":
            w["scale"] = round(w["scale"] / 1.05, 4)
        elif key == "mirror":
            w["mirror"] = not w["mirror"]
        elif key == "reset":
            w.update(x=0.0, y=0.0, scale=1.0, rot=0.0, mirror=False)
        self.hub.publish({"t": "window_calib", "screen": screen, "calib": w})
        self._save()

    def _nudge_warp(self, screen, key):
        """The W buttons move, resize, turn or mirror an auto-aligned window."""
        w = self.window_calib[screen]
        q = [list(p) for p in w["warp"]["quad"]]
        cx, cy = sum(p[0] for p in q) / 4, sum(p[1] for p in q) / 4
        moves = {"left": (-0.01, 0), "right": (0.01, 0), "up": (0, -0.01), "down": (0, 0.01)}
        if key in moves:
            q = [[x + moves[key][0], y + moves[key][1]] for x, y in q]
        elif key in ("bigger", "smaller"):
            f = 1.05 if key == "bigger" else 1 / 1.05
            q = [[cx + (x - cx) * f, cy + (y - cy) * f] for x, y in q]
        elif key in ("rotl", "rotr"):
            a = -0.02 if key == "rotl" else 0.02
            q = [[cx + (x - cx) * math.cos(a) - (y - cy) * math.sin(a),
                  cy + (x - cx) * math.sin(a) + (y - cy) * math.cos(a)] for x, y in q]
        elif key == "mirror":
            q = [q[1], q[0], q[3], q[2]]
        elif key == "reset":
            return self._set_warp(screen, None)
        w["warp"]["quad"] = [[round(x, 5), round(y, 5)] for x, y in q]
        self.hub.publish({"t": "window_calib", "screen": screen, "calib": w})
        self._save()

    def _save(self):
        STATE_FILE.write_text(json.dumps({"gaze_flip": self.gaze_flip, "calib": self.calib, "face_warp": self.face_warp,
                                          "window_calib": self.window_calib,
                                          "volume": Speaker.volume}))

    def status(self):
        if not hasattr(self, "listener"):   # the debug panel can ask while the camera and mic are still starting
            return {"state": "starting", "people": 0, "volume": round(Speaker.volume * 100)}
        people, _, _, _ = self.vision.state()
        st = {"state": self.state, "people": len(people), "detect_ms": round(self.vision.detect_ms),
              "fake": self.cfg["claude"]["fake"], "model": self.cfg["claude"]["model"],
              "mic_muted": self.mic.user_muted,
              "volume": round(Speaker.volume * 100),
              "creature": (self.show.on_stage or {}).get("name") if self.show else None,
              "creature_window": self.show.screen if self.show else None,
              "windows": list(self.screens) if self.show else [],
              "windows_on": self.show.online() if self.show else []}
        if self.doa and self.doa.available:
            st["doa_raw"] = self.doa.raw()
            st["doa_bearing"] = self.doa.bearing(max_age=3)
        return st

    def debug_jpeg(self):
        if not hasattr(self, "listener"):
            return None
        return self.vision.debug_jpeg(self.doa.bearing(max_age=1.5) if self.doa and self.doa.available else None)


def main():
    for stream in (sys.stdout, sys.stderr):   # the log has emoji; Windows consoles and log files default to cp1252
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    cfg = config.load()
    Pumpkin(cfg).run()


if __name__ == "__main__":
    main()
