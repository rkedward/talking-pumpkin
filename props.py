"""Physical extras on the Raspberry Pi's GPIO: servo eyebrows, a fog burst and lights when kids arrive.

Everything here is optional: with nothing configured (or off the Pi) every call is a no-op.
"""

import re
import threading
import time

# Brow positions as (left, right) raise amounts, -1..1 (positive = raised).
EXPRESSIONS = {
    "neutral": (0.0, 0.0),
    "surprised": (1.0, 1.0),
    "happy": (0.4, 0.4),
    "quizzical": (0.9, -0.3),
    "sly": (-0.6, 0.6),
    "sleepy": (-0.5, -0.5),
    "laughing": (0.8, 0.8),
}
LAUGH = re.compile(r"\b(?:ha|ho|hee|heh|hah)(?:[\s,!.-]+(?:ha|ho|hee|heh|hah)\b)+|\b(?:ha){2,}|\b(?:ho){2,}|\b(?:hee){2,}", re.I)


class Props:
    def __init__(self, cfg, log):
        self.cfg, self.log = cfg, log
        self.brows = None
        self.fog = self.lights = None
        self.last_fog = 0.0
        self._setup_brows()
        self._setup_relays()

    # ---- eyebrows -------------------------------------------------------------------------------
    def _setup_brows(self):
        kind = self.cfg["eyebrows"]
        try:
            if kind == "pca9685":
                # Adafruit 16-channel PWM/servo HAT or bonnet on I2C: smooth, jitter-free servos.
                from adafruit_servokit import ServoKit
                kit = ServoKit(channels=16)
                left, right = kit.servo[int(self.cfg["brow_left"])], kit.servo[int(self.cfg["brow_right"])]
                self.brows = (lambda a: setattr(left, "angle", a), lambda a: setattr(right, "angle", a))
            elif kind == "gpio":
                # Servos straight on GPIO pins (software PWM: fine for brows, can jitter a little).
                from gpiozero import AngularServo
                left = AngularServo(int(self.cfg["brow_left"]), min_angle=0, max_angle=180)
                right = AngularServo(int(self.cfg["brow_right"]), min_angle=0, max_angle=180)
                self.brows = (lambda a: setattr(left, "angle", a), lambda a: setattr(right, "angle", a))
            if self.brows:
                self.log(f"props: eyebrow servos on {kind}")
                self.expression("neutral")
        except Exception as exc:
            self.log(f"props: eyebrows off ({type(exc).__name__}: {exc})")
            self.brows = None

    def expression(self, name):
        if not self.brows:
            return
        left, right = EXPRESSIONS.get(name, EXPRESSIONS["neutral"])
        neutral, span = float(self.cfg["brow_neutral_deg"]), float(self.cfg["brow_raise_deg"])
        right_sign = -1 if self.cfg["brow_invert_right"] else 1
        try:
            self.brows[0](max(0, min(180, neutral + left * span)))
            self.brows[1](max(0, min(180, neutral + right_sign * right * span)))
        except Exception as exc:
            self.log(f"props: eyebrow error {exc}")

    def expression_for(self, sentence):
        """Pick brows for a spoken sentence."""
        s = sentence.strip()
        if LAUGH.search(s):
            return "laughing"
        if s.endswith("?"):
            return "quizzical"
        if s.endswith("!"):
            return "surprised"
        if any(w in s.lower() for w in ("because", "get it", "boo")):
            return "sly"
        return "happy"

    # ---- fog and lights -------------------------------------------------------------------------
    def _setup_relays(self):
        pins = {"fog": int(self.cfg["fog_pin"]), "lights": int(self.cfg["lights_pin"])}
        if not any(pins.values()):
            return
        try:
            from gpiozero import OutputDevice
        except Exception as exc:
            self.log(f"props: fog/lights off (gpiozero unavailable: {exc})")
            return
        for name, pin in pins.items():
            if pin:
                setattr(self, name, OutputDevice(pin, active_high=bool(self.cfg["active_high"]), initial_value=False))
                self.log(f"props: {name} relay on GPIO{pin}")

    def arrival(self):
        """Kids just walked up: flash the lights and puff some fog (rate-limited)."""
        if self.lights:
            threading.Thread(target=self._flash, daemon=True).start()
        if self.fog and time.time() - self.last_fog > float(self.cfg["fog_cooldown_s"]):
            self.last_fog = time.time()
            threading.Thread(target=self._pulse, args=(self.fog, float(self.cfg["fog_seconds"])), daemon=True).start()

    def visit_over(self):
        if self.lights:
            self.lights.off()

    def _flash(self):
        for _ in range(3):
            self.lights.on(); time.sleep(0.15)
            self.lights.off(); time.sleep(0.12)
        self.lights.on()

    @staticmethod
    def _pulse(dev, seconds):
        dev.on()
        time.sleep(seconds)
        dev.off()
