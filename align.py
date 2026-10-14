"""Semi-automatic projector alignment from a phone photo.

The projector shows a white frame with four ArUco markers. You photograph it from where the kids stand
and upload the photo from the debug page. The markers tell us how projector pixels land in the photo
(a homography); then we find the target in the photo (the lit window pane, or the pumpkin) and work out
the four projector points where the picture has to go so it fits the target and looks square to the
kids, keystone and mirroring included. Each try redraws the markers inside the new fit, so a second or
third photo refines it (useful on a round pumpkin). Corners can be dragged on the phone if the
automatic guess is off.

All projector coordinates are fractions of the projector's screen (0..1). A "warp" is
{"quad": [[x, y] x4 (top-left, top-right, bottom-right, bottom-left)], "aspect": width / height of the
content as the kids see it}.
"""

import base64

import cv2
import numpy as np

UNIT = [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]
MARK_UV = [(0.3, 0.3), (0.7, 0.3), (0.7, 0.7), (0.3, 0.7)]   # marker centres (ids 0-3) in content space
MARK_SIZE = 0.17          # marker side, as a fraction of the content height
PROJ_ASPECT = 16 / 9      # projector screens are 16:9 (only affects how square the markers are drawn)
MAX_TRIES = 3
GOOD = 0.015              # off by less than 1.5% of the target's size counts as aligned
FACE_FILL = 0.95          # the face's box as a fraction of the pumpkin's outline


def homography(src, dst):
    return cv2.getPerspectiveTransform(np.float32(src), np.float32(dst))


def transform(H, pts):
    return cv2.perspectiveTransform(np.float32(pts).reshape(-1, 1, 2), H).reshape(-1, 2)


def order_corners(pts):
    """Top-left, top-right, bottom-right, bottom-left."""
    pts = np.float32(pts).reshape(-1, 2)
    s, d = pts.sum(1), pts[:, 0] - pts[:, 1]
    return np.float32([pts[np.argmin(s)], pts[np.argmax(d)], pts[np.argmax(s)], pts[np.argmin(d)]])


def quad_aspect(q):
    q = np.float32(q)
    w = (np.linalg.norm(q[1] - q[0]) + np.linalg.norm(q[2] - q[3])) / 2
    h = (np.linalg.norm(q[3] - q[0]) + np.linalg.norm(q[2] - q[1])) / 2
    return float(w / max(h, 1e-6))


def marker_quads(warp):
    """Where to draw the four markers on the projector (inside the current fit, if there is one)."""
    quad = warp["quad"] if warp else UNIT
    aspect = warp["aspect"] if warp else PROJ_ASPECT
    H = homography(UNIT, quad)
    out = []
    for i, (u, v) in enumerate(MARK_UV):
        hu, hv = MARK_SIZE / aspect / 2, MARK_SIZE / 2
        corners = [[u - hu, v - hv], [u + hu, v - hv], [u + hu, v + hv], [u - hu, v + hv]]
        out.append({"id": i, "corners": transform(H, corners).round(5).tolist()})
    return out


def detect_markers(gray):
    d = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    if hasattr(cv2.aruco, "ArucoDetector"):            # OpenCV 4.7+
        corners, ids, _ = cv2.aruco.ArucoDetector(d, cv2.aruco.DetectorParameters()).detectMarkers(gray)
    else:                                               # OpenCV 4.6 (Raspberry Pi OS)
        corners, ids, _ = cv2.aruco.detectMarkers(gray, d, parameters=cv2.aruco.DetectorParameters_create())
    if ids is None:
        return {}
    return {int(i): c.reshape(4, 2) for c, i in zip(corners, ids.flatten()) if 0 <= int(i) < 4}


def find_pane(gray, centre):
    """The lit window pane: the bright area around the markers (the frame blocks the rest of the light)."""
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    _, th = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    th = cv2.morphologyEx(th, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    contours, _ = cv2.findContours(th, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    inside = [c for c in contours if cv2.pointPolygonTest(c, tuple(map(float, centre)), False) >= 0]
    if not inside:
        return None
    hull = cv2.convexHull(max(inside, key=cv2.contourArea))
    peri = cv2.arcLength(hull, True)
    for eps in np.linspace(0.01, 0.12, 23):
        approx = cv2.approxPolyDP(hull, eps * peri, True)
        if len(approx) == 4:
            return order_corners(approx)
    return order_corners(cv2.boxPoints(cv2.minAreaRect(hull)))


def find_pumpkin(gray, centre, span):
    """The pumpkin's outline: the roundest large shape around the markers. Returns its box corners."""
    h, w = gray.shape
    edges = cv2.Canny(cv2.GaussianBlur(gray, (7, 7), 0), 30, 90)
    edges = cv2.dilate(edges, np.ones((5, 5), np.uint8))
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
    best, best_score = None, 0
    for c in contours:
        if len(c) < 20:
            continue
        (cx, cy), (aw, ah), ang = cv2.fitEllipse(c)
        if not (span * 1.1 < max(aw, ah) < 0.95 * max(h, w)) or not (0.55 < aw / max(ah, 1) < 1.8):
            continue
        if np.hypot(cx - centre[0], cy - centre[1]) > 0.35 * max(aw, ah):
            continue                                     # the markers should be near its middle
        fill = cv2.contourArea(cv2.convexHull(c)) / (np.pi * aw * ah / 4)
        score = aw * ah * min(fill, 1.0)
        if fill > 0.6 and score > best_score:
            best, best_score = ((cx, cy), (aw, ah), ang), score
    if best is None:
        return None
    pts = cv2.ellipse2Poly((int(best[0][0]), int(best[0][1])), (int(best[1][0] / 2), int(best[1][1] / 2)),
                           int(best[2]), 0, 360, 5)
    x, y, bw, bh = cv2.boundingRect(pts)
    return box_corners(x + bw / 2, y + bh / 2, bw * FACE_FILL, bh * FACE_FILL)


def box_corners(cx, cy, w, h):
    return np.float32([[cx - w / 2, cy - h / 2], [cx + w / 2, cy - h / 2], [cx + w / 2, cy + h / 2], [cx - w / 2, cy + h / 2]])


class Aligner:
    """get_warp(target) / set_warp(target, warp) read and store a target's warp ("face" or a window name)."""

    def __init__(self, get_warp, set_warp, hub, log):
        self.get_warp, self.set_warp, self.hub, self.log = get_warp, set_warp, hub, log
        self.sessions = {}

    def _pattern(self, target, on=True):
        ev = {"t": "align_pattern", "screen": target, "on": on}
        if on:
            ev["markers"] = marker_quads(self.get_warp(target))
        self.hub.publish(ev)

    def start(self, target):
        if not hasattr(cv2, "aruco"):
            return {"error": "this OpenCV has no ArUco module (install python3-opencv from apt)"}
        self.sessions[target] = {"try": 0}
        self._pattern(target)
        return {"ok": True, "msg": "Pattern is up. Stand where the kids will stand and take a photo with the whole pattern in it."}

    def done(self, target):
        self.sessions.pop(target, None)
        self._pattern(target, on=False)
        warp = self.get_warp(target)
        if warp:
            self.hub.publish({"t": "align_outline", "screen": target, "quad": warp["quad"]})
        return {"ok": True, "msg": "Saved. The projector shows an orange outline of the fit for a few seconds."}

    def photo(self, target, kind, image_b64):
        s = self.sessions.setdefault(target, {"try": 0})
        data = np.frombuffer(base64.b64decode(image_b64.split(",")[-1]), np.uint8)
        img = cv2.imdecode(data, cv2.IMREAD_COLOR)
        if img is None:
            return {"error": "couldn't read that photo"}
        scale = 1600 / max(img.shape[:2])
        if scale < 1:
            img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        found = detect_markers(gray)
        if len(found) < 3:   # rear projection: the kids see the markers mirrored, so look in a flipped copy
            flipped = detect_markers(cv2.flip(gray, 1))
            if len(flipped) > len(found):
                found = {i: np.float32([[gray.shape[1] - 1 - x, y] for x, y in c]) for i, c in flipped.items()}
        if len(found) < 3:
            return {"error": f"I found {len(found)} of the 4 markers. Get the whole pattern in the photo, hold "
                             "steady, and avoid glare, then try again."}
        drawn = {m["id"]: np.float32(m["corners"]) for m in marker_quads(self.get_warp(target))}
        proj = np.concatenate([drawn[i] for i in sorted(found)])
        photo = np.concatenate([found[i] for i in sorted(found)])
        H, _ = cv2.findHomography(proj, photo, 0)        # projector (0..1) -> photo pixels
        if H is None:
            return {"error": "the markers didn't line up; try a straighter photo"}
        centre = photo.mean(0)
        span = float(np.ptp(photo[:, 0]))
        corners = find_pane(gray, centre) if kind == "window" else find_pumpkin(gray, centre, span)
        guessed = corners is None
        if guessed:   # fall back to a box around the markers; the corners can be dragged on the phone
            x0, y0 = photo.min(0)
            x1, y1 = photo.max(0)
            corners = box_corners((x0 + x1) / 2, (y0 + y1) / 2, (x1 - x0) * 1.6, (y1 - y0) * 1.6)
        s.update(H=H, img=img, kind=kind)
        s["try"] += 1
        return self._solve(target, corners, guessed)

    def corners(self, target, pts):
        """Re-fit using corners dragged on the phone (fractions of the preview image)."""
        s = self.sessions.get(target)
        if not s or "H" not in s:
            return {"error": "take a photo first"}
        h, w = s["img"].shape[:2]
        return self._solve(target, np.float32(pts) * [w, h], False, retry=False)

    def _solve(self, target, corners, guessed, retry=True):
        s = self.sessions[target]
        H, img = s["H"], s["img"]
        h, w = img.shape[:2]
        corners = order_corners(corners)
        old = self.get_warp(target)
        before = transform(H, old["quad"] if old else UNIT)
        diag = float(np.linalg.norm(corners[2] - corners[0]))
        off = float(np.mean(np.linalg.norm(before - corners, axis=1)) / max(diag, 1))
        quad = np.clip(transform(np.linalg.inv(H), corners), -0.5, 1.5)
        self.set_warp(target, {"quad": quad.round(5).tolist(), "aspect": round(quad_aspect(corners), 4)})
        self._pattern(target)                             # markers move inside the new fit for the next try

        preview = img.copy()
        cv2.polylines(preview, [before.astype(np.int32)], True, (255, 160, 60), 2)
        cv2.polylines(preview, [corners.astype(np.int32)], True, (0, 140, 255), 4)
        ok, jpg = cv2.imencode(".jpg", preview, [cv2.IMWRITE_JPEG_QUALITY, 80])
        n = s["try"]
        aligned = off < GOOD and not guessed
        if aligned:
            msg = f"Aligned: it was only off by {off:.1%}. Tap Done."
        elif guessed:
            msg = "I couldn't find the edges by myself. Drag the orange corners onto them and tap Use my corners."
        elif n >= MAX_TRIES:
            msg = f"Try {n} of {MAX_TRIES}: off by {off:.1%} before this fix. Drag the corners if it still looks wrong, or tap Done."
        else:
            msg = f"Try {n} of {MAX_TRIES}: it was off by {off:.1%}, now fixed. Take another photo to check."
        self.log(f"align {target}: try {n}, off {off:.1%}{' (guessed edges)' if guessed else ''}")
        return {"ok": True, "msg": msg, "try": n, "off": round(off, 4), "aligned": aligned,
                "preview": "data:image/jpeg;base64," + base64.b64encode(jpg).decode(),
                "corners": (corners / [w, h]).round(4).tolist()}
