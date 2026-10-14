// Side-show window: shows the creatures the pumpkin summons on a window projector (the Pi's second HDMI
// port, or a smart projector on Wi-Fi opening http://<pi>:8000/window.html?w=<window name>). Plays your video clips from static/creatures/, or draws one of
// the built-in creatures. Black = no light, so only the creature shows on the glass.

import { AlignOverlay, fitElement } from "./warp.js";

const $ = (id) => document.getElementById(id);
const stage = $("stage"), clip = $("clip"), canvas = $("art"), ctx = canvas.getContext("2d");
const TAU = Math.PI * 2;
const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
const ease = (t) => 1 - Math.pow(1 - clamp(t, 0, 1), 3);

let current = null;   // { creature, start, endAt, enter: [dx, dy] | null, exit: { dir, at } | null }
let level = 0;        // creature voice loudness 0..1
let audioCtx = null;

function resize() {
  const dpr = window.devicePixelRatio || 1;
  canvas.width = Math.round((canvas.clientWidth || innerWidth) * dpr);
  canvas.height = Math.round((canvas.clientHeight || innerHeight) * dpr);
}
addEventListener("resize", resize);
resize();

const post = (cmd, body = {}) => fetch(`api/${cmd}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

// Which window this is (a [window.screens.<name>] in config.toml); without ?w= it's the default "door".
const SCREEN = new URLSearchParams(location.search).get("w") || "door";
const status = $("status");
let statusTimer = null;
function showStatus(text, ms, big = false) {
  status.textContent = text;
  status.className = big ? "big" : "";
  status.style.display = big ? "grid" : "block";
  clearTimeout(statusTimer);
  if (ms) statusTimer = setTimeout(() => (status.style.display = "none"), ms);
}

// Check in so the pumpkin knows this projector is on (it only summons into windows that are).
let checkedIn = false;
async function checkIn() {
  try {
    const r = await (await post("window_seen", { screen: SCREEN })).json();
    if (r.error) showStatus(`${SCREEN}: ${r.error}${r.windows ? " (windows: " + r.windows.join(", ") + ")" : ""}`);
    else if (!checkedIn) showStatus(`window "${SCREEN}" connected`, 5000);
    checkedIn = !r.error;
  } catch {
    checkedIn = false;
    showStatus(`window "${SCREEN}": can't reach the pumpkin, retrying`);
  }
}
checkIn();
setInterval(checkIn, 10000);

// ---- events from the brain (only this window's) ----
const es = new EventSource(`events?w=${encodeURIComponent(SCREEN)}`);
es.onmessage = (m) => {
  const ev = JSON.parse(m.data);
  if (ev.t === "creature") start(ev.creature, ev.enter);
  else if (ev.t === "creature_exit") flyOut(ev.dir);
  else if (ev.t === "creature_end") finish();
  else if (ev.t === "creature_mouth") level = ev.level;
  else if (ev.t === "window_calib") applyCalib(ev.calib);
  else if (ev.t === "identify") showStatus(SCREEN, 6000, true);
  else if (ev.t === "align_pattern") ev.on ? overlay.pattern(ev.markers) : overlay.hide();
  else if (ev.t === "align_outline") overlay.outline(ev.quad);
};

const overlay = new AlignOverlay();

function applyCalib(c) {
  if (fitElement(stage, c.warp)) { resize(); return; }   // auto-aligned from a phone photo
  const s = c.scale || 1;
  stage.style.transform = `translate(${(c.x || 0) * 100}vw, ${(c.y || 0) * 100}vh) rotate(${c.rot || 0}rad) scale(${c.mirror ? -s : s}, ${s})`;
}

function start(creature, enter = null) {
  finishNow();
  current = { creature, start: performance.now() / 1000, endAt: null, enter, exit: null };
  if (enter) whoosh();
  lastKnock = -1;
  if (creature.kind === "video") {
    clip.src = creature.src;
    clip.currentTime = 0;
    clip.classList.add("on");
    clip.play().catch((e) => console.warn("video", e));
  }
}

// A flying creature leaves this window towards the next one (dir as the kids see it: [1, 0] = their right).
function flyOut(dir) {
  if (!current || current.exit) return;
  if (current.creature.kind !== "builtin") return finish();
  const leaving = current;
  leaving.exit = { dir, at: performance.now() / 1000 };
  whoosh();
  setTimeout(() => { if (current === leaving) finishNow(); }, 1300);
}

function whoosh() {
  try {
    audioCtx = audioCtx || new AudioContext();
    const now = audioCtx.currentTime, len = 1.0;
    const buf = audioCtx.createBuffer(1, Math.floor(audioCtx.sampleRate * len), audioCtx.sampleRate), d = buf.getChannelData(0);
    for (let i = 0; i < d.length; i++) d[i] = Math.random() * 2 - 1;
    const src = audioCtx.createBufferSource(), filt = audioCtx.createBiquadFilter(), gain = audioCtx.createGain();
    src.buffer = buf;
    filt.type = "bandpass"; filt.Q.value = 2.5;
    filt.frequency.setValueAtTime(300, now);
    filt.frequency.exponentialRampToValueAtTime(1800, now + len * 0.5);
    filt.frequency.exponentialRampToValueAtTime(400, now + len);
    gain.gain.setValueAtTime(0.001, now);
    gain.gain.exponentialRampToValueAtTime(0.6, now + len * 0.4);
    gain.gain.exponentialRampToValueAtTime(0.001, now + len);
    src.connect(filt).connect(gain).connect(audioCtx.destination);
    src.start(now);
  } catch { /* no audio */ }
}

function finish() {
  if (!current || current.endAt) return;
  current.endAt = performance.now() / 1000 + 0.8;   // fade out
  clip.classList.remove("on");
  setTimeout(() => { if (current && current.endAt && performance.now() / 1000 >= current.endAt) finishNow(); }, 900);
}

function finishNow() {
  current = null;
  clip.pause();
  clip.classList.remove("on");
  clip.removeAttribute("src");
  level = 0;
}

clip.addEventListener("ended", () => { finish(); post("creature_done", { screen: SCREEN }); });
clip.addEventListener("error", () => { finish(); post("creature_done", { screen: SCREEN }); });

// ---- render loop for the built-in creatures ----
function frame() {
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  if (current && current.creature.kind === "builtin") {
    const now = performance.now() / 1000;
    const t = now - current.start;
    let alpha = current.enter ? 1 : ease(t / 0.8);   // a creature flying in is already solid
    if (current.endAt) alpha = Math.min(alpha, clamp((current.endAt - now) / 0.8, 0, 1));
    const s = Math.min(canvas.width, canvas.height) / 1000;
    ctx.translate(canvas.width / 2, canvas.height / 2);
    ctx.scale(s, s);
    // flying in from one side, or out the other
    let ox = 0, oy = 0, tilt = 0;
    if (current.enter) {
      const k = 1 - ease(t / 1.4);
      ox -= current.enter[0] * 1500 * k; oy -= current.enter[1] * 1100 * k; tilt += current.enter[0] * 0.35 * k;
    }
    if (current.exit) {
      const u = clamp((now - current.exit.at) / 1.1, 0, 1), k = u * u;
      ox += current.exit.dir[0] * 1500 * k; oy += current.exit.dir[1] * 1100 * k;
      tilt += current.exit.dir[0] * 0.35 * Math.min(1, u * 3);
    }
    ctx.translate(ox, oy);
    ctx.rotate(tilt);
    ctx.globalAlpha = alpha;
    const draw = { "ghost": drawGhost, "shadow eyes": drawEyes, "skeleton hand": drawHand }[current.creature.art || current.creature.name];
    if (draw) draw(t, !!current.enter);
    ctx.globalAlpha = 1;
  }
  requestAnimationFrame(frame);
}
requestAnimationFrame(frame);

// ---- ghost ----
function drawGhost(t, flying = false) {
  const rise = flying ? 1 : ease(t / 2.5);   // floats up from below, unless it flew in from another window
  const x = Math.sin(t * 0.7) * 90;
  const y = (1 - rise) * 800 + Math.sin(t * 1.6) * 25;
  ctx.save();
  ctx.translate(x, y);
  ctx.rotate(Math.sin(t * 0.7 + 0.5) * 0.06);
  ctx.shadowColor = "rgba(160, 200, 255, 0.9)";
  ctx.shadowBlur = 60;
  const g = ctx.createRadialGradient(0, -120, 20, 0, 0, 330);
  g.addColorStop(0, "rgba(250, 252, 255, 0.95)");
  g.addColorStop(1, "rgba(170, 195, 255, 0.55)");
  ctx.fillStyle = g;
  // sheet body with a wavy hem
  ctx.beginPath();
  ctx.moveTo(-170, -120);
  ctx.arc(0, -120, 170, Math.PI, 0);
  ctx.bezierCurveTo(175, 20, 200, 160, 210, 240);
  const scallops = 5;
  for (let i = 0; i < scallops; i++) {
    const x0 = 210 - (i * 420) / scallops, x1 = 210 - ((i + 1) * 420) / scallops;
    const dip = 60 + 25 * Math.sin(t * 3 + i * 1.3);
    ctx.quadraticCurveTo((x0 + x1) / 2, 240 + dip, x1, 240);
  }
  ctx.bezierCurveTo(-200, 160, -175, 20, -170, -120);
  ctx.fill();
  // waving arm
  ctx.save();
  ctx.translate(165, -10);
  ctx.rotate(-0.6 + Math.sin(t * 5) * 0.45);
  ctx.beginPath();
  ctx.ellipse(55, 0, 70, 32, 0, 0, TAU);
  ctx.fill();
  ctx.restore();
  ctx.beginPath();
  ctx.ellipse(-180, 20, 55, 28, 0.5, 0, TAU);
  ctx.fill();
  // face
  ctx.shadowBlur = 0;
  ctx.fillStyle = "#000";
  const blink = (t % 4.2) > 4.05 ? 0.1 : 1;
  for (const ex of [-60, 60]) {
    ctx.beginPath();
    ctx.ellipse(ex, -150, 26, 40 * blink, 0, 0, TAU);
    ctx.fill();
  }
  ctx.beginPath();
  ctx.ellipse(0, -55, 34 + level * 16, 10 + level * 60, 0, 0, TAU);
  ctx.fill();
  ctx.restore();
}

// ---- shadow eyes ----
let eyes = null;
function makeEyes() {
  let seed = 7;
  const rnd = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
  const colors = [[255, 210, 40], [255, 60, 30], [140, 255, 60], [255, 140, 20]];
  return Array.from({ length: 26 }, (_, i) => ({
    x: (rnd() * 2 - 1) * 440, y: (rnd() * 2 - 1) * 400, size: 9 + rnd() * 16,
    color: colors[Math.floor(rnd() * colors.length)], delay: i * 0.18 + rnd() * 0.3,
    blinkPeriod: 2.5 + rnd() * 4, blinkPhase: rnd() * 10, gap: 2.2 + rnd() * 1.2,
  }));
}
function drawEyes(t) {
  eyes = eyes || makeEyes();
  for (const e of eyes) {
    const appear = clamp((t - e.delay) / 0.6, 0, 1);
    if (!appear) continue;
    const phase = (t + e.blinkPhase) % e.blinkPeriod;
    const open = phase < 0.15 ? Math.abs(phase - 0.075) / 0.075 : 1;
    const glow = (0.6 + 0.4 * Math.sin(t * 2 + e.delay)) * (0.8 + level * 0.6);
    const [r, g, b] = e.color;
    const size = e.size * (1 + level * 0.35);
    const dx = Math.sin(t * 0.4 + e.delay) * 12;
    for (const side of [-1, 1]) {
      const cx = e.x + dx + side * size * e.gap * 0.5, cy = e.y;
      ctx.save();
      ctx.shadowColor = `rgba(${r},${g},${b},${0.9 * appear})`;
      ctx.shadowBlur = 25;
      ctx.fillStyle = `rgba(${r},${g},${b},${clamp(glow, 0, 1) * appear})`;
      ctx.beginPath();
      ctx.ellipse(cx, cy, size, size * 0.55 * open, side * -0.15, 0, TAU);
      ctx.fill();
      ctx.shadowBlur = 0;
      ctx.fillStyle = `rgba(0,0,0,${appear})`;
      ctx.beginPath();
      ctx.ellipse(cx, cy, size * 0.18, size * 0.5 * open, 0, 0, TAU);
      ctx.fill();
      ctx.restore();
    }
  }
}

// ---- skeleton hand ----
let lastKnock = -1;
function knockSound() {
  try {
    audioCtx = audioCtx || new AudioContext();
    const now = audioCtx.currentTime;
    const osc = audioCtx.createOscillator(), gain = audioCtx.createGain();
    osc.frequency.setValueAtTime(140, now);
    osc.frequency.exponentialRampToValueAtTime(55, now + 0.12);
    gain.gain.setValueAtTime(0.9, now);
    gain.gain.exponentialRampToValueAtTime(0.001, now + 0.18);
    osc.connect(gain).connect(audioCtx.destination);
    osc.start(now); osc.stop(now + 0.2);
    const noise = audioCtx.createBufferSource(), nb = audioCtx.createBuffer(1, 2205, 22050), d = nb.getChannelData(0);
    for (let i = 0; i < d.length; i++) d[i] = (Math.random() * 2 - 1) * Math.exp(-i / 300);
    const ng = audioCtx.createGain();
    ng.gain.value = 0.5;
    noise.buffer = nb;
    noise.connect(ng).connect(audioCtx.destination);
    noise.start(now);
  } catch { /* no audio: knocks are silent */ }
}

function bone(x0, y0, x1, y1, w) {
  ctx.lineWidth = w;
  ctx.beginPath(); ctx.moveTo(x0, y0); ctx.lineTo(x1, y1); ctx.stroke();
  ctx.beginPath(); ctx.arc(x0, y0, w * 0.62, 0, TAU); ctx.arc(x1, y1, w * 0.62, 0, TAU); ctx.fill();
}

function drawHand(t) {
  // Approach the glass, then knock three times every few seconds.
  let scale = 0.55 + 0.45 * ease(t / 1.5);
  const cycle = (t - 1.8) % 3.2;
  let knock = 0;
  if (t > 1.8) {
    const n = Math.floor((t - 1.8) / 3.2);
    [0, 0.35, 0.7].forEach((k, i) => {
      const d = cycle - k;
      if (d >= 0 && d < 0.25) knock = Math.max(knock, Math.sin((d / 0.25) * Math.PI));
      const id = n * 3 + i;
      if (d >= 0.12 && d < 0.5 && id > lastKnock) { lastKnock = id; knockSound(); }  // sound on impact
    });
  }
  scale += knock * 0.08;
  const curl = clamp(0.15 + level * 0.6 + knock * 0.5, 0, 1);
  ctx.save();
  ctx.scale(scale, scale);
  ctx.translate(Math.sin(t * 0.8) * 15, 40);
  ctx.strokeStyle = ctx.fillStyle = "rgba(236, 230, 210, 0.95)";
  ctx.shadowColor = "rgba(200, 220, 255, 0.6)";
  ctx.shadowBlur = 30;
  ctx.lineCap = "round";
  // forearm and wrist
  bone(-38, 130, -50, 470, 34);
  bone(36, 130, 48, 470, 30);
  for (const [cx, cy] of [[-50, 85], [-15, 95], [20, 92], [52, 82], [-35, 55], [0, 60], [35, 55]]) {
    ctx.beginPath(); ctx.arc(cx, cy, 17, 0, TAU); ctx.fill();
  }
  // fingers: metacarpal + 3 phalanges (the curl shortens them as they bend toward the glass)
  const fingers = [[-78, -0.2, 0.85], [-27, -0.07, 1], [25, 0.06, 0.95], [74, 0.2, 0.78]];
  for (const [bx, ang, len] of fingers) {
    let x = bx * 0.6, y = 40, a = ang - Math.PI / 2;
    const segs = [110, 70 * len, 46 * len, 34 * len];
    segs.forEach((L, i) => {
      const l = i === 0 ? L : L * (1 - curl * 0.45 * i / 3);
      const nx = x + Math.cos(a) * l, ny = y + Math.sin(a) * l;
      bone(x, y, nx, ny, i === 0 ? 20 : 17 - i * 2);
      x = nx; y = ny; a += ang * 0.15;
    });
  }
  // thumb
  let x = -60, y = 70, a = -Math.PI / 2 - 0.85;
  for (const [L, w] of [[80, 20], [55, 17], [40, 15]]) {
    const nx = x + Math.cos(a) * L * (1 - curl * 0.2), ny = y + Math.sin(a) * L * (1 - curl * 0.2);
    bone(x, y, nx, ny, w);
    x = nx; y = ny; a += 0.25;
  }
  ctx.restore();
}
