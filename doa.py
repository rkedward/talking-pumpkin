"""Direction of arrival from a ReSpeaker USB mic array, so the eyes find whoever is talking.

Supports both Seeed arrays; the firmware computes the voice direction itself and we read it over USB
control transfers (needs `pyusb` and permission to the device; the installer adds a udev rule):
  - reSpeaker XVF3800 4-Mic Array (with or without XIAO ESP32S3). Needs its USB firmware: the XIAO
    version ships with I2S firmware, see flash_xvf3800.sh.
  - ReSpeaker USB Mic Array v2.0 (XVF3000).
"""

import struct
import threading
import time

VENDOR_ID = 0x2886
XVF3800_PIDS = (0x001A,)
XVF3000_PIDS = (0x0018,)


class _XVF3800:
    """Seeed's XVF3800 USB control protocol: DOA_VALUE = (resid 20, cmdid 18), two uint16 words
    [angle 0-359, speech detected], preceded by one status byte."""

    name = "reSpeaker XVF3800"

    def __init__(self, dev, usb):
        self.dev, self.usb = dev, usb

    def read(self):
        u = self.usb.util
        resid, cmdid, length = 20, 18, 4
        data = bytes(self.dev.ctrl_transfer(u.CTRL_IN | u.CTRL_TYPE_VENDOR | u.CTRL_RECIPIENT_DEVICE,
                                            0, 0x80 | cmdid, resid, length + 1, 1000))
        angle, speech = struct.unpack("<HH", data[1:5])
        return angle, bool(speech)


class _XVF3000:
    """ReSpeaker USB Mic Array v2.0 (Seeed tuning.py protocol): DOAANGLE (21, 0), VOICEACTIVITY (19, 32)."""

    name = "ReSpeaker USB Mic Array v2.0"

    def __init__(self, dev, usb):
        self.dev, self.usb = dev, usb

    def _int(self, pid, offset):
        u = self.usb.util
        data = self.dev.ctrl_transfer(u.CTRL_IN | u.CTRL_TYPE_VENDOR | u.CTRL_RECIPIENT_DEVICE,
                                      0, 0x80 | 0x40 | offset, pid, 8, 1000)
        return struct.unpack("ii", bytes(data))[0]

    def read(self):
        speech = bool(self._int(19, 32))
        return self._int(21, 0), speech


def _open(usb, log):
    """Find a ReSpeaker array and work out which protocol it speaks."""
    try:   # Windows: libusb comes as a pip package (libusb-package) rather than from the system
        import libusb_package
        backend = libusb_package.get_libusb1_backend()
    except ImportError:
        backend = None
    devices = list(usb.core.find(find_all=True, idVendor=VENDOR_ID, backend=backend))
    for dev in devices:
        order = (_XVF3000, _XVF3800) if dev.idProduct in XVF3000_PIDS else (_XVF3800, _XVF3000)
        for proto in order:
            p = proto(dev, usb)
            try:
                angle, _ = p.read()
                if 0 <= angle < 360:
                    return p
            except Exception:
                continue
    if devices:
        log("mic array: ReSpeaker found but it doesn't report voice direction; is it running its USB "
            "firmware (see flash_xvf3800.sh) and does the udev rule allow access? On Windows its control "
            "interface needs the WinUSB driver (see README).")
    return None


class ReSpeakerDOA:
    def __init__(self, cfg, log):
        self.offset = float(cfg["offset_deg"])
        self.flip = bool(cfg["flip"])
        self.angle = None          # raw 0-359 from the array
        self.voice = False
        self.voice_at = 0.0
        self.proto = None
        try:
            import usb.core
            import usb.util
            self.proto = _open(usb, log)
        except Exception as exc:  # pyusb or libusb missing
            log(f"mic array: direction finding off ({type(exc).__name__}: {exc})")
            return
        if self.proto is None:
            log("mic array: no ReSpeaker voice direction available; eyes follow the closest person")
            return
        log(f"mic array: {self.proto.name} found, eyes will turn toward voices")
        threading.Thread(target=self._loop, daemon=True, name="doa").start()

    def _loop(self):
        errors = 0
        while True:
            try:
                angle, voice = self.proto.read()
                if voice:
                    self.angle = angle
                    self.voice_at = time.time()
                self.voice = voice
                errors = 0
            except Exception:
                errors += 1
                if errors > 50:
                    return
            time.sleep(0.1)

    @property
    def available(self):
        return self.proto is not None

    def bearing(self, max_age=0.6):
        """Voice direction relative to straight ahead, degrees (positive = camera image right), or None."""
        if self.angle is None or time.time() - self.voice_at > max_age:
            return None
        b = (self.angle - self.offset + 180) % 360 - 180
        return -b if self.flip else b

    def raw(self):
        return self.angle
