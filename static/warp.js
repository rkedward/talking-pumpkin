// Projector alignment helpers shared by the face page and the window page: fit an element onto four
// projector points (keystone, skew and mirroring in one CSS transform), and draw the ArUco pattern that
// the phone photographs for auto-alignment (see align.py).

// ArUco DICT_4X4_50 markers 0-3, with their black border: "0" = black cell, "1" = white cell.
const MARKERS = {
  0: ["000000", "010110", "001010", "000110", "000100", "000000"],
  1: ["000000", "000000", "011110", "010010", "010100", "000000"],
  2: ["000000", "000110", "000110", "000100", "011010", "000000"],
  3: ["000000", "010010", "010010", "001000", "001100", "000000"],
};

// 3x3 homography (row-major) mapping 4 source points to 4 destination points.
export function homography(src, dst) {
  const A = [], b = [];
  for (let i = 0; i < 4; i++) {
    const [x, y] = src[i], [u, v] = dst[i];
    A.push([x, y, 1, 0, 0, 0, -u * x, -u * y]); b.push(u);
    A.push([0, 0, 0, x, y, 1, -v * x, -v * y]); b.push(v);
  }
  for (let c = 0; c < 8; c++) {                       // Gaussian elimination with partial pivoting
    let p = c;
    for (let r = c + 1; r < 8; r++) if (Math.abs(A[r][c]) > Math.abs(A[p][c])) p = r;
    [A[c], A[p]] = [A[p], A[c]]; [b[c], b[p]] = [b[p], b[c]];
    for (let r = c + 1; r < 8; r++) {
      const f = A[r][c] / A[c][c];
      for (let k = c; k < 8; k++) A[r][k] -= f * A[c][k];
      b[r] -= f * b[c];
    }
  }
  const h = new Array(8);
  for (let r = 7; r >= 0; r--) {
    let s = b[r];
    for (let k = r + 1; k < 8; k++) s -= A[r][k] * h[k];
    h[r] = s / A[r][r];
  }
  return [...h, 1];
}

export function apply(H, [x, y]) {
  const w = H[6] * x + H[7] * y + H[8];
  return [(H[0] * x + H[1] * y + H[2]) / w, (H[3] * x + H[4] * y + H[5]) / w];
}

function matrix3d(H) {
  const [a, b, c, d, e, f, g, h, i] = H;
  return `matrix3d(${a},${d},0,${g},${b},${e},0,${h},0,0,1,0,${c},${f},0,${i})`;
}

// Size `el` to the content's aspect and map its corners onto warp.quad (fractions of the screen).
// Returns false (and clears the fit) when there is no warp.
export function fitElement(el, warp) {
  if (!warp || !warp.quad) {
    Object.assign(el.style, { width: "", height: "", transform: "", transformOrigin: "", left: "", top: "", right: "", bottom: "" });
    return false;
  }
  const h = innerHeight, w = Math.round(h * (warp.aspect || 16 / 9));
  const quad = warp.quad.map(([x, y]) => [x * innerWidth, y * innerHeight]);
  Object.assign(el.style, { position: "fixed", left: "0px", top: "0px", right: "auto", bottom: "auto",
                            width: `${w}px`, height: `${h}px`, transformOrigin: "0 0" });
  el.style.transform = matrix3d(homography([[0, 0], [w, 0], [w, h], [0, h]], quad));
  return true;
}

// A full-screen overlay canvas that shows the alignment pattern or, afterwards, the fitted outline.
export class AlignOverlay {
  constructor() {
    this.canvas = document.createElement("canvas");
    Object.assign(this.canvas.style, { position: "fixed", inset: "0", width: "100vw", height: "100vh", zIndex: "3", display: "none", pointerEvents: "none" });
    document.body.appendChild(this.canvas);
    this.timer = null;
    addEventListener("resize", () => this.redraw && this.redraw());
  }

  _ctx() {
    const dpr = window.devicePixelRatio || 1, c = this.canvas;
    c.width = Math.round(innerWidth * dpr); c.height = Math.round(innerHeight * dpr);
    c.style.display = "block";
    return [c.getContext("2d"), c.width, c.height];
  }

  pattern(markers) {
    clearTimeout(this.timer);
    this.redraw = () => {
      const [ctx, W, H] = this._ctx();
      ctx.fillStyle = "#fff";                           // white everywhere lights up the glass or pumpkin
      ctx.fillRect(0, 0, W, H);
      ctx.fillStyle = "#000";
      for (const m of markers) {
        const Hm = homography([[0, 0], [1, 0], [1, 1], [0, 1]], m.corners.map(([x, y]) => [x * W, y * H]));
        MARKERS[m.id].forEach((row, r) => [...row].forEach((bit, c) => {
          if (bit !== "0") return;
          const pts = [[c, r], [c + 1, r], [c + 1, r + 1], [c, r + 1]].map(([u, v]) => apply(Hm, [u / 6, v / 6]));
          ctx.beginPath();
          pts.forEach(([x, y], k) => (k ? ctx.lineTo(x, y) : ctx.moveTo(x, y)));
          ctx.closePath();
          ctx.fill();
          ctx.stroke();   // hairline overlap so neighbouring cells leave no seams
        }));
      }
    };
    this.redraw();
  }

  outline(quad, ms = 6000) {
    clearTimeout(this.timer);
    this.redraw = () => {
      const [ctx, W, H] = this._ctx();
      ctx.clearRect(0, 0, W, H);
      ctx.strokeStyle = "#ff8c1a";
      ctx.lineWidth = Math.max(4, W / 200);
      ctx.beginPath();
      quad.forEach(([x, y], k) => (k ? ctx.lineTo(x * W, y * H) : ctx.moveTo(x * W, y * H)));
      ctx.closePath();
      ctx.stroke();
    };
    this.redraw();
    this.timer = setTimeout(() => this.hide(), ms);
  }

  hide() {
    clearTimeout(this.timer);
    this.redraw = null;
    this.canvas.style.display = "none";
  }
}
