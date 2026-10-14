// Animated jack-o'-lantern face, drawn on a canvas for projection onto a pumpkin.
// Black pixels = no projector light, so only the glowing eyes, nose and mouth land on the pumpkin.

const TAU = Math.PI * 2;
const lerp = (a, b, t) => a + (b - a) * t;
const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));

export class PumpkinFace {
  constructor(canvas) {
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d");
    // Inputs (set from outside)
    this.gazeTarget = { x: 0, y: 0 }; // -1..1, in the face's screen space
    this.speaking = false;
    this.mouthLevel = null; // 0..1 from the real audio loudness; null = animate procedurally while speaking
    this.awake = false; // eyes half closed while nobody is around
    // Animated state
    this.gaze = { x: 0, y: 0 };
    this.mouth = 0;
    this.mouthKick = 0;
    this.lid = 0.55; // 0 = wide open, 1 = closed
    this.blinkUntil = 0;
    this.nextBlink = performance.now() + 2000;
    this.surpriseUntil = 0;
    this.laughUntil = 0;
    this.visible = true; // false = the pumpkin is dark (hide_when_idle); fades in when it wakes
    this.vis = 1;
    this.squint = 0; // 0..1, cheeks pushing the eyes into happy crescents while laughing
    this.wander = { x: 0, y: 0, next: 0 };
    this.calib = defaultCalibration(); // the brain stores it and sends it, so a phone can adjust the projector view
    this.showGuide = false;
    this.resize();
    window.addEventListener("resize", () => this.resize());
  }

  resize() {
    const dpr = window.devicePixelRatio || 1;
    // the element's own size: full screen, or the auto-aligned box (see warp.js)
    this.canvas.width = Math.round((this.canvas.clientWidth || innerWidth) * dpr);
    this.canvas.height = Math.round((this.canvas.clientHeight || innerHeight) * dpr);
    this.dpr = dpr;
  }

  // Called on each word boundary from speech synthesis.
  kick() { this.mouthKick = 1; }
  surprise(ms = 900) { this.surpriseUntil = performance.now() + ms; }
  laugh(ms = 1500) { this.laughUntil = performance.now() + ms; }
  setVisible(on) { this.visible = on; }

  adjust(key) {
    const c = this.calib;
    const step = 0.01;
    const moves = {
      ArrowLeft: () => (c.x -= step), ArrowRight: () => (c.x += step),
      ArrowUp: () => (c.y -= step), ArrowDown: () => (c.y += step),
      "+": () => (c.scale *= 1.03), "=": () => (c.scale *= 1.03), "-": () => (c.scale /= 1.03),
      "[": () => (c.rot -= 0.02), "]": () => (c.rot += 0.02),
      "{": () => (c.stretch /= 1.03), "}": () => (c.stretch *= 1.03),
      "0": () => Object.assign(c, defaultCalibration()),
    };
    if (!moves[key]) return false;
    moves[key]();
    return true;
  }

  update(now, dt) {
    // Gaze: follow the target when awake, otherwise drift around lazily.
    let tx = this.gazeTarget.x, ty = this.gazeTarget.y;
    if (!this.awake) {
      if (now > this.wander.next) {
        this.wander = { x: (Math.random() * 2 - 1) * 0.7, y: (Math.random() * 2 - 1) * 0.4,
                        next: now + 1500 + Math.random() * 3000 };
      }
      tx = this.wander.x; ty = this.wander.y;
    }
    const g = 1 - Math.exp(-dt * (this.awake ? 9 : 2.5));
    this.gaze.x = lerp(this.gaze.x, clamp(tx, -1, 1), g);
    this.gaze.y = lerp(this.gaze.y, clamp(ty, -1, 1), g);

    // Blinking
    if (now > this.nextBlink) {
      this.blinkUntil = now + 140;
      this.nextBlink = now + 2500 + Math.random() * 4000;
    }
    const surprised = now < this.surpriseUntil;
    let lidTarget = this.awake ? 0.08 : 0.55;
    if (surprised) lidTarget = -0.15;
    const laughing = now < this.laughUntil;
    if (laughing) lidTarget = 0;
    else if (now < this.blinkUntil) lidTarget = 1;
    this.squint = lerp(this.squint, laughing ? 1 : 0, 1 - Math.exp(-dt * 12));
    this.vis = lerp(this.vis, this.visible ? 1 : 0, 1 - Math.exp(-dt * (this.visible ? 3 : 1.5)));
    this.lid = lerp(this.lid, lidTarget, 1 - Math.exp(-dt * (now < this.blinkUntil ? 40 : 8)));

    // Mouth: follows the audio loudness sent by the brain; otherwise syllable-rate flapping while speaking.
    let mTarget = 0;
    if (this.mouthLevel !== null) {
      mTarget = this.mouthLevel;
    } else if (this.speaking) {
      const syll = Math.abs(Math.sin(now / 1000 * 10.5)) * (0.55 + 0.45 * Math.sin(now / 1000 * 3.1 + 1));
      mTarget = 0.15 + 0.65 * syll + 0.4 * this.mouthKick;
    }
    if (now < this.laughUntil) mTarget = Math.max(mTarget, 0.25);   // keep a big open grin while laughing
    this.mouthKick = Math.max(0, this.mouthKick - dt * 5);
    this.mouth = lerp(this.mouth, clamp(mTarget, 0, 1), 1 - Math.exp(-dt * 30));
  }

  draw(now) {
    const { ctx, canvas, calib } = this;
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.fillStyle = "#000";
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    const s = Math.min(canvas.width, canvas.height) / 1000 * calib.scale;
    ctx.translate(canvas.width * (0.5 + calib.x), canvas.height * (0.5 + calib.y));
    ctx.rotate(calib.rot);
    ctx.scale(s, s * calib.stretch);

    if (this.showGuide) this.drawGuide();
    if (this.vis < 0.005) return;   // dark until someone arrives
    ctx.globalAlpha = this.vis;

    // Candle flicker
    const t = now / 1000;
    const flicker = 0.88 + 0.07 * Math.sin(t * 7.3) + 0.05 * Math.sin(t * 13.1 + 2) * Math.sin(t * 3.7);
    const brightness = (this.awake ? 1 : 0.7) * flicker;

    // Laughing: the whole face bounces with each "ho!"
    if (this.squint > 0.01) ctx.translate(0, -Math.abs(Math.sin(t * 13)) * 16 * this.squint);

    this.drawEye(-190, -110, 1, brightness);
    this.drawEye(190, -110, -1, brightness);
    this.drawNose(brightness);
    this.drawMouth(brightness);
    ctx.globalAlpha = 1;
  }

  glow(x, y, r, brightness) {
    const grad = this.ctx.createRadialGradient(x, y, r * 0.05, x, y, r);
    const a = clamp(brightness, 0, 1);
    grad.addColorStop(0, `rgba(255, 250, 200, ${a})`);
    grad.addColorStop(0.35, `rgba(255, 196, 40, ${a})`);
    grad.addColorStop(1, `rgba(255, 96, 0, ${a})`);
    return grad;
  }

  // side = 1 for the face's right eye (screen left), -1 for its left eye; shapes mirror.
  drawEye(cx, cy, side, brightness) {
    const ctx = this.ctx;
    const surprised = performance.now() < this.surpriseUntil;
    const k = surprised ? 1.12 : 1;
    // Rounded triangle, apex tilted toward the nose, classic jack-o'-lantern style.
    const pts = [
      [cx - 105 * k, cy + 62 * k],
      [cx + 105 * k, cy + 62 * k],
      [cx + side * 28 * k, cy - 92 * k],
    ];
    ctx.save();
    ctx.beginPath();
    roundedPolygon(ctx, pts, 26);
    ctx.shadowColor = "rgba(255, 120, 0, 0.9)";
    ctx.shadowBlur = 50;
    ctx.fillStyle = this.glow(cx, cy + 10, 150, brightness);
    ctx.fill();
    ctx.shadowBlur = 0;
    ctx.clip();

    // Pupil
    const px = cx + this.gaze.x * 58 + side * 4;
    const py = cy + 18 + this.gaze.y * 26;
    ctx.fillStyle = "#000";
    ctx.beginPath();
    ctx.arc(px, py, surprised ? 26 : 34, 0, TAU);
    ctx.fill();
    // Tiny highlight makes the pupil read as an eye from a distance.
    ctx.fillStyle = `rgba(255, 245, 210, ${0.9 * brightness})`;
    ctx.beginPath();
    ctx.arc(px - 11, py - 12, 7, 0, TAU);
    ctx.fill();

    // Eyelid: black band sliding down from the top.
    const top = cy - 100, bottom = cy + 70;
    const lid = clamp(this.lid, 0, 1);
    ctx.fillStyle = "#000";
    if (lid > 0.01) {
      ctx.fillRect(cx - 140, top - 10, 280, (bottom - top + 10) * lid + 10);
    }
    // Laughing: a dark cheek curve rises from below, leaving a happy upside-down-U eye.
    if (this.squint > 0.01) {
      ctx.beginPath();
      ctx.ellipse(cx, bottom + 40, 150, 40 + 80 * this.squint, 0, 0, TAU);
      ctx.fill();
    }
    ctx.restore();
  }

  drawNose(brightness) {
    const ctx = this.ctx;
    ctx.save();
    ctx.beginPath();
    roundedPolygon(ctx, [[-42, 40], [42, 40], [0, -22]], 10);
    ctx.shadowColor = "rgba(255, 120, 0, 0.8)";
    ctx.shadowBlur = 30;
    ctx.fillStyle = this.glow(0, 25, 70, brightness * 0.9);
    ctx.fill();
    ctx.restore();
  }

  drawMouth(brightness) {
    const ctx = this.ctx;
    const open = this.mouth;
    const W = 290, cornerY = 110;
    const upperC = 215 - open * 25;            // control point y of the upper lip curve
    const lowerC = 255 + open * 190;           // control point y of the lower lip curve
    const curveY = (x, c) => {                 // quadratic with symmetric endpoints: x is linear in t
      const t = (x + W) / (2 * W);
      return (1 - t) ** 2 * cornerY + 2 * t * (1 - t) * c + t * t * cornerY;
    };
    ctx.save();
    ctx.beginPath();
    ctx.moveTo(-W, cornerY);
    ctx.quadraticCurveTo(0, upperC, W, cornerY);
    ctx.quadraticCurveTo(0, lowerC, -W, cornerY);
    ctx.closePath();
    ctx.shadowColor = "rgba(255, 120, 0, 0.9)";
    ctx.shadowBlur = 50;
    ctx.fillStyle = this.glow(0, 200, 330, brightness);
    ctx.fill();
    ctx.shadowBlur = 0;
    ctx.clip();

    // Teeth are uncarved pumpkin, so they're black blocks inside the glowing mouth.
    ctx.fillStyle = "#000";
    for (const [x0, x1] of [[-150, -95], [70, 125]]) {     // upper teeth hang down
      const y = Math.min(curveY(x0, upperC), curveY(x1, upperC));
      ctx.fillRect(x0, y - 20, x1 - x0, 20 + 46);
    }
    for (const [x0, x1] of [[-40, 15]]) {                   // lower tooth sticks up
      const y = Math.max(curveY(x0, lowerC), curveY(x1, lowerC));
      ctx.fillRect(x0, y - 48, x1 - x0, 48 + 20);
    }
    ctx.restore();
  }

  drawGuide() {
    const ctx = this.ctx;
    ctx.save();
    ctx.strokeStyle = "rgba(80, 160, 255, 0.8)";
    ctx.lineWidth = 4;
    ctx.beginPath();
    ctx.ellipse(0, 40, 470, 420, 0, 0, TAU);
    ctx.moveTo(-500, 0); ctx.lineTo(500, 0);
    ctx.moveTo(0, -460); ctx.lineTo(0, 500);
    ctx.stroke();
    ctx.restore();
  }
}

function roundedPolygon(ctx, pts, r) {
  const n = pts.length;
  const mid = (a, b) => [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
  const start = mid(pts[n - 1], pts[0]);
  ctx.moveTo(start[0], start[1]);
  for (let i = 0; i < n; i++) {
    const p = pts[i], next = pts[(i + 1) % n];
    const m = mid(p, next);
    ctx.arcTo(p[0], p[1], m[0], m[1], r);
  }
  ctx.closePath();
}

function defaultCalibration() {
  return { x: 0, y: 0, scale: 0.9, rot: 0, stretch: 1 };
}
