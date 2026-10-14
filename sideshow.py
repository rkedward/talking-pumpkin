"""The side show: the pumpkin's assistants. Window projectors (e.g. behind the frosted front-door glass, or smart
projectors in other rooms' windows that open window.html over Wi-Fi) where the pumpkin can summon creatures. Creatures are your own video clips (dropped in static/creatures/) plus a few
built-in animated ones, and they can talk with their own voice."""

import copy
import threading
import time
import tomllib

from audio import Speaker, make_tts, piper_voice_path
from config import ROOT, screens

CREATURE_DIR = ROOT / "static" / "creatures"
VIDEO_EXT = {".mp4", ".webm", ".mov", ".m4v"}

# Each assistant has its own voice: a Piper voice (downloaded by install_pi.sh), pitch in semitones, speed
# (Piper length scale, >1 is slower), optional chorus (extra copies at these pitch offsets, for a crowd),
# and an espeak variant used if Piper isn't available.
BUILTINS = [
    {"name": "Boo", "art": "ghost", "kind": "builtin", "flies": True,
     "voice": "en_US-amy-medium", "pitch": 4.0, "speed": 0.95, "espeak_voice": "en-us+f4",
     "description": "Boo the ghost, Jack's shy, giggly assistant who floats up to the glass and waves, "
                    "and can fly from window to window"},
    {"name": "the Peepers", "art": "shadow eyes", "kind": "builtin",
     "voice": "en_US-lessac-medium", "pitch": -1.0, "speed": 1.15, "chorus": [-5.0, 4.0], "espeak_voice": "en-us+whisper",
     "description": "the Peepers, Jack's lookout crew: dozens of glowing eyes blinking in the dark that watch for "
                    "trick-or-treaters and always talk all at once"},
    {"name": "Knuckles", "art": "skeleton hand", "kind": "builtin",
     "voice": "en_GB-alan-medium", "pitch": -6.0, "speed": 1.3, "espeak_voice": "en-gb+m7",
     "description": "Knuckles, Jack's very proper skeleton butler, who knocks on the glass from inside and is in "
                    "charge of the candy"},
]
VOICE_KEYS = ("voice", "pitch", "speed", "chorus", "espeak_voice", "elevenlabs_voice_id")


def load_creatures(cfg):
    """Video clips in static/creatures/ (name = file name) plus the built-ins. Descriptions for clips come
    from static/creatures/creatures.toml, e.g.  [skeleton-knocking] description = "a skeleton knocking"."""
    notes = {}
    toml_path = CREATURE_DIR / "creatures.toml"
    if toml_path.exists():
        with open(toml_path, "rb") as f:
            notes = tomllib.load(f)
    creatures = []
    if CREATURE_DIR.exists():
        for f in sorted(CREATURE_DIR.iterdir()):
            if f.suffix.lower() in VIDEO_EXT:
                meta = notes.get(f.stem, {})
                name = meta.get("name", f.stem.replace("-", " ").replace("_", " "))
                creatures.append({"name": name, "kind": "video", "src": f"creatures/{f.name}",
                                  "description": meta.get("description", name),
                                  **{k: meta[k] for k in VOICE_KEYS if k in meta},
                                  "has_audio": bool(meta.get("has_audio", True)),
                                  "windows": [str(w) for w in meta.get("windows", [])]})
    if cfg["builtins"]:
        creatures += [c for c in BUILTINS if c["name"] not in {x["name"] for x in creatures}]
    return creatures


ONLINE_S = 35   # a window page that hasn't checked in for this long is treated as switched off


class SideShow:
    def __init__(self, cfg, tts_cfg, mic, hub, log):
        self.cfg, self.mic, self.hub, self.log = cfg, mic, hub, log
        self.creatures = load_creatures(cfg)
        self.screens = screens(cfg)
        self.seen = {}                # screen name -> last check-in time from its window page
        self.on_stage = None          # creature dict currently showing
        self.screen = None            # window it is showing in
        self.stage_until = 0.0
        self.done = threading.Event()
        self.mouth = 0.0
        self.fly_gap = float(cfg.get("fly_gap_s", 0.8))
        self.speakers = {c["name"]: self._speaker(c, tts_cfg) for c in self.creatures}
        names = ", ".join(c["name"] for c in self.creatures) or "none"
        log(f"side show: {len(self.creatures)} creatures ({names}); windows: {', '.join(self.screens)}")

    def _speaker(self, c, tts_cfg):
        """A Speaker with this creature's own voice (falls back to the shared creature voice settings)."""
        voice = copy.deepcopy(tts_cfg)
        voice["pitch_semitones"] = float(c.get("pitch", self.cfg["creature_pitch"]))
        voice["piper_length_scale"] = float(c.get("speed", self.cfg["creature_length_scale"]))
        voice["chorus"] = c.get("chorus", [])
        for name in (c.get("voice"), self.cfg["creature_voice"], tts_cfg["piper_voice"]):
            if name and piper_voice_path(name).exists():
                voice["piper_voice"] = name
                break
        if c.get("espeak_voice"):
            voice["espeak_voice"] = c["espeak_voice"]
        if c.get("elevenlabs_voice_id"):
            voice["elevenlabs_voice_id"] = c["elevenlabs_voice_id"]
        tts = make_tts(voice, lambda m: self.log(m.replace("voice:", f"{c['name']}'s voice:")))
        return Speaker(tts, voice, self.mic, self.log)

    # ---- windows ----
    def checked_in(self, screen):
        if screen not in self.screens:
            return False
        if screen not in self.online():
            self.log(f"🪟 window '{screen}' connected")
        self.seen[screen] = time.time()
        return True

    def online(self):
        now = time.time()
        return [n for n in self.screens if now - self.seen.get(n, 0) < ONLINE_S]

    def place(self, creature, screen=""):
        """The window to use: the one asked for if it's on and allowed for this creature, else another one."""
        allowed = [s for s in self.online() if not creature.get("windows") or s in creature["windows"]]
        if screen in allowed:
            return screen
        return allowed[0] if allowed else None

    def direction(self, a, b):
        """Which way to fly from window a to window b, as the kids see the house: [dx, dy] with one of them +-1.
        Uses each window's gaze, which points from the pumpkin's face towards that window."""
        (ax, ay), (bx, by) = self.screens[a]["gaze"], self.screens[b]["gaze"]
        if abs(bx - ax) >= 0.2:
            return [1 if bx > ax else -1, 0]
        return [0, 1 if by > ay else -1]

    def tour_order(self):
        """Online windows from the kids' left to right (the order a ghost tour visits them)."""
        return sorted(self.online(), key=lambda n: (self.screens[n]["gaze"][0], self.screens[n]["gaze"][1]))

    def fly_to(self, screen, on_leave=None):
        """The creature on stage (if it can fly) leaves its window and flies into another one."""
        c, a = self.on_stage, self.screen
        if not c or not c.get("flies") or screen == a or screen not in self.online():
            return False
        d = self.direction(a, screen)
        self.hub.publish({"t": "creature_exit", "screen": a, "dir": d})
        if on_leave:
            on_leave(screen)
        time.sleep(1.1 + self.fly_gap)       # out of one window, through the house, into the next
        if self.on_stage is not c:
            return False                      # dismissed meanwhile
        self.screen = screen
        self.stage_until = time.time() + float(self.cfg["stay_s"])
        self.hub.publish({"t": "creature", "screen": screen, "creature": c, "enter": d,
                          "stay_s": float(self.cfg["stay_s"])})
        self.log(f"👻 {c['name']} flew from {a} to {screen}")
        return True

    def find(self, name):
        return next((c for c in self.creatures if c["name"] == name), None)

    def summon(self, name, screen=""):
        c = self.find(name)
        where = self.place(c, screen) if c else None
        if not where:
            if c:
                self.log(f"👻 {name}: no window is switched on for it")
            return False
        self.dismiss()
        self.on_stage, self.screen = c, where
        self.done.clear()
        self.stage_until = time.time() + float(self.cfg["stay_s"])
        if c["kind"] == "video" and c.get("has_audio", True):
            self.mic.mute_for(float(self.cfg["stay_s"]))   # don't transcribe the clip's soundtrack
        self.hub.publish({"t": "creature", "screen": where, "creature": c, "stay_s": float(self.cfg["stay_s"])})
        self.log(f"👻 summoned {c['name']} in {where}")
        return True

    def clip_finished(self, screen=None):
        """Called when a window page reports that its video ended."""
        if screen in (None, self.screen):
            self.done.set()

    def active(self):
        if self.on_stage and (time.time() > self.stage_until or self.done.is_set()):
            self.dismiss()
        return self.on_stage

    def dismiss(self):
        if self.on_stage:
            self.hub.publish({"t": "creature_end", "screen": self.screen})
            self.mic.muted_until = min(self.mic.muted_until, time.time() + 0.3)
            self.on_stage = self.screen = None

    def speak(self, text, should_stop):
        """The creature talks (in the window; the pumpkin's mouth stays still)."""
        if not text or not self.on_stage:
            return
        self.log(f"👻 {self.on_stage['name']}: {text}", "said")
        screen = self.screen
        self.stage_until = max(self.stage_until, time.time() + 3)

        def level(v):
            self.mouth = v
            self.hub.publish({"t": "creature_mouth", "screen": screen, "level": round(v, 3)})

        self.speakers[self.on_stage["name"]].speak(text, on_level=level, should_stop=should_stop)
        self.stage_until = max(self.stage_until, time.time() + 4)   # linger a moment after speaking
