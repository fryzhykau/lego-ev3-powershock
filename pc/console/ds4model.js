// A DualShock 4 built in code (no model files), with parts that move.
// createDS4(container) -> { update(input, lightColor), setColor(hex) }
// input: { lx, ly, rx, ry, l2, r2, btn: { cross, circle, square, triangle, L1, R1, L3, R3,
//          up, down, left, right, share, options, PS, pad } }
//
// The shell is one smooth surface: a signed-distance shape (the top-view outline traced from
// Wikimedia Commons' "Dualshock 4 Layout.svg", 162 mm wide, rounded, with the grips bent down
// and the stick bosses and button pods blended in), turned into triangles with surface nets.
// Units are centimetres: x to the right, y up, z towards the player; z = 0 is the back edge.
import * as THREE from "./vendor/three/three.module.js";

export const COLORS = {
  "Magma Red": 0xc8211f,
  "Jet Black": 0x1d2023,
  "Wave Blue": 0x1f4fb5,
  "Glacier White": 0xe9ecee,
  "Midnight Blue": 0x1b2742,
  "Gold": 0xb8954a,
};

// ---------- measurements (cm) ----------
const STICK = { x: 2.58, z: 4.44 };   // stick centres
const POD = { x: 5.07, z: 2.36 };     // D-pad and face-button centres
const PAD = { w: 5.3, d: 2.75, z: 1.55 }; // touchpad
const PS_Z = 4.67, SPEAKER_Z = 3.67, SHARE = { x: 3.29, z: 0.85 };

// Right half of the outline, top view (x, z). It runs past the middle (x < 0) so that mirroring
// with |x| leaves no seam.
const OUTLINE = [[-1.5, 0], [2.67, 0], [5.9, 0], [6.35, 0.25], [6.7, 0.95], [7.22, 2.89], [7.67, 4.89], [8.0, 6.67],
  [8.11, 8.0], [7.82, 9.08], [6.67, 9.6], [5.56, 9.44], [4.8, 8.7], [4.44, 7.56], [4.11, 6.67], [3.85, 6.1], [3.3, 5.88],
  [0, 5.88], [-1.5, 5.88]];

const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const smooth = (a, b, v) => { const t = clamp((v - a) / (b - a), 0, 1); return t * t * (3 - 2 * t); };
const smin = (a, b, k) => { const h = clamp(0.5 + 0.5 * (b - a) / k, 0, 1); return b + (a - b) * h - k * h * (1 - h); };
const smax = (a, b, k) => -smin(-a, -b, k);

function outlinePoints() {
  const curve = new THREE.SplineCurve(OUTLINE.map(([x, z]) => new THREE.Vector2(x, z)));
  const pts = curve.getSpacedPoints(110);
  const xs = new Float64Array(pts.length), zs = new Float64Array(pts.length);
  pts.forEach((p, i) => { xs[i] = p.x; zs[i] = p.y; });
  return { xs, zs };
}
const POLY = outlinePoints();

// Signed distance to the outline polygon (negative inside).
function sdOutline(px, pz) {
  const { xs, zs } = POLY, n = xs.length;
  let d = (px - xs[0]) ** 2 + (pz - zs[0]) ** 2, s = 1;
  for (let i = 0, j = n - 1; i < n; j = i, i++) {
    const ex = xs[j] - xs[i], ez = zs[j] - zs[i], wx = px - xs[i], wz = pz - zs[i];
    const t = clamp((wx * ex + wz * ez) / (ex * ex + ez * ez), 0, 1);
    const bx = wx - ex * t, bz = wz - ez * t;
    d = Math.min(d, bx * bx + bz * bz);
    const c1 = pz >= zs[i], c2 = pz < zs[j], c3 = ex * wz > ez * wx;
    if ((c1 && c2 && c3) || (!c1 && !c2 && !c3)) s = -s;
  }
  return s * Math.sqrt(d);
}
function sdCylinder(px, py, pz, r, h, rr) { // vertical, centred at the origin, rounded edges
  const dx = Math.hypot(px, pz) - r + rr, dy = Math.abs(py) - h + rr;
  return Math.min(Math.max(dx, dy), 0) + Math.hypot(Math.max(dx, 0), Math.max(dy, 0)) - rr;
}
function sdEllipsoid(px, py, pz, rx, ry, rz) {
  const k0 = Math.hypot(px / rx, py / ry, pz / rz), k1 = Math.hypot(px / (rx * rx), py / (ry * ry), pz / (rz * rz));
  return k0 * (k0 - 1) / k1;
}
function sdBox(px, py, pz, bx, by, bz) {
  const qx = Math.abs(px) - bx, qy = Math.abs(py) - by, qz = Math.abs(pz) - bz;
  return Math.hypot(Math.max(qx, 0), Math.max(qy, 0), Math.max(qz, 0)) + Math.min(Math.max(qx, qy, qz), 0);
}

// How far the grips bend down and thicken: 0 at the stick line, 1 at the grip ends.
const gripT = (z) => clamp((z - 5.0) / 4.6, 0, 1);

function shell(x, y, z) {
  const ax = Math.abs(x), u = gripT(z);
  const drop = 1.85 * u ** 1.5;
  const half = 1.0 * (1 + 0.38 * smooth(0, 1, u));
  const wing = 0.22 * smooth(5.4, 8.2, ax) * (1 - u); // the wings' tops fall away outwards
  const yc = -1.0 - drop - wing;
  // rounded slab: the outline, rounded with radius r on both faces
  const r = 0.72, qx = sdOutline(ax, z) + r, qy = Math.abs(y - yc) - half + r;
  let d = Math.hypot(Math.max(qx, 0), Math.max(qy, 0)) + Math.min(Math.max(qx, qy), 0) - r;
  // bosses the sticks sit in, and the raised pods under the D-pad and face buttons
  d = smin(d, sdCylinder(ax - STICK.x, y + 0.55, z - STICK.z, 1.62, 0.9, 0.3), 0.45);
  d = smin(d, sdEllipsoid(ax - POD.x, y + 0.18, z - POD.z, 1.95, 0.42, 1.95), 0.5);
  // cut-outs: the stick wells and the touchpad's bed
  d = smax(d, -sdCylinder(ax - STICK.x, y - 0.6, z - STICK.z, 1.18, 0.88, 0.05), 0.08);
  d = smax(d, -sdBox(x, y - 0.55, z - PAD.z, PAD.w / 2 + 0.08, 0.68, PAD.d / 2 + 0.08), 0.06);
  return d;
}

// Surface nets: one vertex per grid cell the surface passes through, one quad per crossing edge.
function surfaceNets(f, [x0, y0, z0], [nx, ny, nz], s) {
  const v = new Float32Array(nx * ny * nz);
  let n = 0;
  for (let k = 0; k < nz; k++) for (let j = 0; j < ny; j++) for (let i = 0; i < nx; i++) v[n++] = f(x0 + i * s, y0 + j * s, z0 + k * s);
  const at = (i, j, k) => i + nx * (j + ny * k);
  const cell = new Int32Array(nx * ny * nz).fill(-1);
  const pos = [];
  const C = [[0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0], [0, 0, 1], [1, 0, 1], [0, 1, 1], [1, 1, 1]];
  const E = [[0, 1], [2, 3], [4, 5], [6, 7], [0, 2], [1, 3], [4, 6], [5, 7], [0, 4], [1, 5], [2, 6], [3, 7]];
  const c = new Float32Array(8);
  for (let k = 0; k < nz - 1; k++) for (let j = 0; j < ny - 1; j++) for (let i = 0; i < nx - 1; i++) {
    let inside = 0;
    for (let q = 0; q < 8; q++) { c[q] = v[at(i + C[q][0], j + C[q][1], k + C[q][2])]; if (c[q] < 0) inside++; }
    if (inside === 0 || inside === 8) continue;
    let sx = 0, sy = 0, sz = 0, m = 0;
    for (const [a, b] of E) {
      if ((c[a] < 0) === (c[b] < 0)) continue;
      const t = c[a] / (c[a] - c[b]);
      sx += C[a][0] + (C[b][0] - C[a][0]) * t; sy += C[a][1] + (C[b][1] - C[a][1]) * t; sz += C[a][2] + (C[b][2] - C[a][2]) * t; m++;
    }
    cell[at(i, j, k)] = pos.length / 3;
    pos.push(x0 + (i + sx / m) * s, y0 + (j + sy / m) * s, z0 + (k + sz / m) * s);
  }
  const idx = [];
  const quad = (a, b, cc, d) => { if (a < 0 || b < 0 || cc < 0 || d < 0) return; idx.push(a, b, cc, a, cc, d); };
  for (let k = 1; k < nz - 1; k++) for (let j = 1; j < ny - 1; j++) for (let i = 1; i < nx - 1; i++) {
    const p = v[at(i, j, k)] < 0;
    if (p !== (v[at(i + 1, j, k)] < 0)) quad(cell[at(i, j - 1, k - 1)], cell[at(i, j, k - 1)], cell[at(i, j, k)], cell[at(i, j - 1, k)]);
    if (p !== (v[at(i, j + 1, k)] < 0)) quad(cell[at(i - 1, j, k - 1)], cell[at(i, j, k - 1)], cell[at(i, j, k)], cell[at(i - 1, j, k)]);
    if (p !== (v[at(i, j, k + 1)] < 0)) quad(cell[at(i - 1, j - 1, k)], cell[at(i, j - 1, k)], cell[at(i, j, k)], cell[at(i - 1, j, k)]);
  }
  // smooth normals from the shape itself; turn each triangle to face outwards
  const nrm = new Float32Array(pos.length), e = s * 0.35;
  for (let q = 0; q < pos.length; q += 3) {
    const [x, y, z] = [pos[q], pos[q + 1], pos[q + 2]];
    const gx = f(x + e, y, z) - f(x - e, y, z), gy = f(x, y + e, z) - f(x, y - e, z), gz = f(x, y, z + e) - f(x, y, z - e);
    const l = Math.hypot(gx, gy, gz) || 1;
    nrm[q] = gx / l; nrm[q + 1] = gy / l; nrm[q + 2] = gz / l;
  }
  for (let t = 0; t < idx.length; t += 3) {
    const [a, b, d] = [idx[t] * 3, idx[t + 1] * 3, idx[t + 2] * 3];
    const ux = pos[b] - pos[a], uy = pos[b + 1] - pos[a + 1], uz = pos[b + 2] - pos[a + 2];
    const wx = pos[d] - pos[a], wy = pos[d + 1] - pos[a + 1], wz = pos[d + 2] - pos[a + 2];
    const fx = uy * wz - uz * wy, fy = uz * wx - ux * wz, fz = ux * wy - uy * wx;
    if (fx * (nrm[a] + nrm[b] + nrm[d]) + fy * (nrm[a + 1] + nrm[b + 1] + nrm[d + 1]) + fz * (nrm[a + 2] + nrm[b + 2] + nrm[d + 2]) < 0) {
      const tmp = idx[t + 1]; idx[t + 1] = idx[t + 2]; idx[t + 2] = tmp;
    }
  }
  return { pos, nrm, idx };
}

function shellGeometry() {
  const s = 0.15;
  const min = [-8.6, -4.6, -0.7], max = [8.6, 0.9, 10.2];
  const dims = min.map((m, i) => Math.ceil((max[i] - m) / s) + 1);
  const { pos, nrm, idx } = surfaceNets(shell, min, dims, s);
  // the ends of the grips are a separate, slightly darker part on the real pad
  const col = new Float32Array(pos.length);
  for (let q = 0; q < pos.length; q += 3) {
    const ax = Math.abs(pos[q]), z = pos[q + 2];
    const band = 1 - 0.2 * smooth(-0.12, 0.12, z - (7.15 + (8.1 - ax) * 0.42));
    col[q] = col[q + 1] = col[q + 2] = band;
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
  g.setAttribute("normal", new THREE.Float32BufferAttribute(nrm, 3));
  g.setAttribute("color", new THREE.Float32BufferAttribute(col, 3));
  g.setIndex(idx);
  return g;
}

function roundedRect(w, h, r) {
  const s = new THREE.Shape(), x = -w / 2, y = -h / 2;
  s.moveTo(x + r, y); s.lineTo(x + w - r, y); s.quadraticCurveTo(x + w, y, x + w, y + r);
  s.lineTo(x + w, y + h - r); s.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
  s.lineTo(x + r, y + h); s.quadraticCurveTo(x, y + h, x, y + h - r);
  s.lineTo(x, y + r); s.quadraticCurveTo(x, y, x + r, y);
  return s;
}

// Extrudes a flat shape upwards (Y) with rounded edges; top ends at y = 0.
function slab(shape, depth, bevel, segs = 6) {
  const g = new THREE.ExtrudeGeometry(shape, {
    depth, bevelEnabled: true, bevelThickness: bevel, bevelSize: bevel * 0.9, bevelSegments: segs, curveSegments: 32,
  });
  g.rotateX(-Math.PI / 2);
  g.translate(0, -(depth + bevel), 0);
  return g;
}

function symbolTexture(kind, color) {
  const c = document.createElement("canvas"); c.width = c.height = 128;
  const g = c.getContext("2d");
  g.strokeStyle = color; g.lineWidth = 9; g.lineCap = "round"; g.lineJoin = "round";
  g.beginPath();
  if (kind === "triangle") { g.moveTo(64, 30); g.lineTo(98, 90); g.lineTo(30, 90); g.closePath(); }
  if (kind === "circle") g.arc(64, 64, 30, 0, Math.PI * 2);
  if (kind === "cross") { g.moveTo(38, 38); g.lineTo(90, 90); g.moveTo(90, 38); g.lineTo(38, 90); }
  if (kind === "square") g.rect(36, 36, 56, 56);
  g.stroke();
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; return t;
}

function dotsTexture() {
  const c = document.createElement("canvas"); c.width = 512; c.height = 270;
  const g = c.getContext("2d");
  g.fillStyle = "#1b1e20"; g.fillRect(0, 0, c.width, c.height);
  g.fillStyle = "#101213";
  for (let y = 9; y < c.height; y += 11) for (let x = 9 + ((y / 11) % 2) * 5.5; x < c.width; x += 11) { g.beginPath(); g.arc(x, y, 2.4, 0, 7); g.fill(); }
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; return t;
}

export function createDS4(container) {
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.05;
  container.appendChild(renderer.domElement);
  renderer.domElement.style.display = "block";

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(30, 1, 0.1, 100);
  camera.position.set(0, 12.5, 22.5);
  camera.lookAt(0, -0.9, 0.6);

  // studio lighting
  scene.add(new THREE.HemisphereLight(0xffffff, 0x8a8f94, 1.25));
  const key = new THREE.DirectionalLight(0xffffff, 2.2);
  key.position.set(-6, 14, 9); key.castShadow = true;
  key.shadow.mapSize.set(1024, 1024); key.shadow.radius = 6;
  Object.assign(key.shadow.camera, { left: -12, right: 12, top: 12, bottom: -12, near: 1, far: 40 });
  scene.add(key);
  const rim = new THREE.DirectionalLight(0xffffff, 0.9); rim.position.set(8, 4, -10); scene.add(rim);
  const floor = new THREE.Mesh(new THREE.PlaneGeometry(60, 60), new THREE.ShadowMaterial({ opacity: 0.18 }));
  floor.rotation.x = -Math.PI / 2; floor.position.y = -3.4; floor.receiveShadow = true; scene.add(floor);

  // materials
  const shellMat = new THREE.MeshPhysicalMaterial({ color: COLORS["Magma Red"], roughness: 0.5, clearcoat: 0.25, clearcoatRoughness: 0.5, vertexColors: true });
  const dark = new THREE.MeshStandardMaterial({ color: 0x24282b, roughness: 0.5 });
  const darker = new THREE.MeshStandardMaterial({ color: 0x141618, roughness: 0.7 });
  const rubber = new THREE.MeshStandardMaterial({ color: 0x2a2e31, roughness: 0.85, side: THREE.DoubleSide });
  const capMat = new THREE.MeshStandardMaterial({ color: 0x202326, roughness: 0.45, side: THREE.DoubleSide });
  const lightMat = new THREE.MeshStandardMaterial({ color: 0x3d7bff, emissive: 0x3d7bff, emissiveIntensity: 1.6 });

  // model = turned by the user; rig = the controller in its own coordinates, centred in model
  const model = new THREE.Group(); scene.add(model);
  const rig = new THREE.Group(); rig.position.set(0, 1.3, -4.6); model.add(rig);
  const mesh = (geo, mat, parent = rig) => { const m = new THREE.Mesh(geo, mat); m.castShadow = true; m.receiveShadow = true; parent.add(m); return m; };

  // ----- the shell -----
  mesh(shellGeometry(), shellMat);

  // ----- top: touchpad, light strip, speaker, PS, Share and Options -----
  const pad = mesh(slab(roundedRect(PAD.w, PAD.d, 0.28), 0.1, 0.05, 3), new THREE.MeshStandardMaterial({ map: dotsTexture(), roughness: 0.75 }));
  pad.position.set(0, -0.05, PAD.z);
  const strip = mesh(new THREE.BoxGeometry(PAD.w - 0.6, 0.04, 0.07), lightMat); strip.position.set(0, -0.06, PAD.z - PAD.d / 2 - 0.06); strip.castShadow = false;
  for (const [row, n] of [[-1, 5], [0, 4], [1, 5]]) for (let i = 0; i < n; i++) {
    const d = mesh(new THREE.CylinderGeometry(0.055, 0.055, 0.04, 12), darker);
    d.position.set((i - (n - 1) / 2) * 0.19, 0.0, SPEAKER_Z + row * 0.16);
  }
  const ps = mesh(new THREE.CylinderGeometry(0.38, 0.38, 0.14, 32), new THREE.MeshStandardMaterial({ color: 0x26292c, roughness: 0.35 }));
  ps.position.set(0, 0.03, PS_Z);
  const share = mesh(new THREE.CapsuleGeometry(0.15, 0.45, 6, 12), dark); share.rotation.x = Math.PI / 2; share.position.set(-SHARE.x, 0.06, SHARE.z);
  const options = mesh(new THREE.CapsuleGeometry(0.15, 0.45, 6, 12), dark); options.rotation.x = Math.PI / 2; options.position.set(SHARE.x, 0.06, SHARE.z);

  // ----- back: light bar and USB; front: headset jack and extension port -----
  const bar = mesh(new THREE.BoxGeometry(4.6, 0.34, 0.06), lightMat); bar.position.set(0, -0.95, -0.03); bar.castShadow = false;
  const usb = mesh(new THREE.BoxGeometry(0.8, 0.26, 0.08), darker); usb.position.set(0, -1.5, -0.02);
  const jack = mesh(new THREE.CylinderGeometry(0.16, 0.16, 0.1, 20), darker); jack.rotation.x = Math.PI / 2; jack.position.set(-0.35, -1.15, 5.9);
  const ext = mesh(new THREE.BoxGeometry(0.75, 0.2, 0.1), darker); ext.position.set(0.5, -1.15, 5.9);

  // ----- D-pad: four separate arrows with pointed inner ends -----
  const arrow = new THREE.Shape();
  arrow.moveTo(-0.36, 0.62); arrow.lineTo(-0.36, 1.36); arrow.quadraticCurveTo(-0.36, 1.48, -0.24, 1.48);
  arrow.lineTo(0.24, 1.48); arrow.quadraticCurveTo(0.36, 1.48, 0.36, 1.36); arrow.lineTo(0.36, 0.62); arrow.lineTo(0, 0.36); arrow.closePath();
  const dpad = {};
  for (const [name, ang] of [["up", 0], ["right", -Math.PI / 2], ["down", Math.PI], ["left", Math.PI / 2]]) {
    const g = slab(arrow, 0.14, 0.06, 3); g.rotateY(ang);
    const m = mesh(g, dark); m.position.set(-POD.x, 0.36, POD.z); dpad[name] = m;
  }

  // ----- face buttons: domed caps with coloured symbols -----
  const capProfile = [[0, 0.3], [0.2, 0.3], [0.36, 0.27], [0.45, 0.2], [0.48, 0]].map(([x, y]) => new THREE.Vector2(x, y));
  const face = {};
  for (const [name, dx, dz, col] of [["triangle", 0, -1, "#3fd0b4"], ["circle", 1, 0, "#ff5b5b"], ["cross", 0, 1, "#7aa8ff"], ["square", -1, 0, "#ff7fd1"]]) {
    const g = new THREE.Group(); rig.add(g);
    g.position.set(POD.x + dx * 1.22, 0.14, POD.z + dz * 1.22);
    mesh(new THREE.LatheGeometry(capProfile, 32), capMat, g);
    const symMat = new THREE.MeshStandardMaterial({ map: symbolTexture(name, col), transparent: true, emissive: new THREE.Color(col), emissiveMap: symbolTexture(name, col), emissiveIntensity: 0.25 });
    const sym = new THREE.Mesh(new THREE.CircleGeometry(0.34, 32), symMat); sym.rotation.x = -Math.PI / 2; sym.position.y = 0.305; g.add(sym);
    face[name] = { g, symMat };
  }

  // ----- sticks: shafts that pivot in the wells, dished caps with a grip ring -----
  const capLathe = [[0, 0.95], [0.4, 0.98], [0.62, 1.06], [0.74, 1.04], [0.78, 0.94], [0.72, 0.84], [0.3, 0.8], [0.26, 0.0], [0, 0.0]].map(([x, y]) => new THREE.Vector2(x, y));
  const sticks = {};
  for (const [name, side] of [["L", -1], ["R", 1]]) {
    const pivot = new THREE.Group(); pivot.position.set(side * STICK.x, -0.62, STICK.z); pivot.scale.setScalar(1.3); rig.add(pivot);
    mesh(new THREE.LatheGeometry(capLathe, 40), rubber, pivot);
    const grip = mesh(new THREE.TorusGeometry(0.72, 0.055, 8, 40), darker, pivot); grip.rotation.x = Math.PI / 2; grip.position.y = 1.0;
    sticks[name] = pivot;
  }

  // ----- shoulder buttons and hinged triggers at the back -----
  const bumpers = {}, triggers = {};
  for (const [name, side] of [["L", -1], ["R", 1]]) {
    const b = mesh(slab(roundedRect(2.1, 0.7, 0.33), 0.2, 0.12, 5), dark);
    b.position.set(side * 4.95, -0.14, -0.18); bumpers[name] = b;
    const hinge = new THREE.Group(); hinge.position.set(side * 4.95, -0.55, -0.25); rig.add(hinge);
    // side profile: x = towards the back, y = up; the finger face curves inwards
    const prof = new THREE.Shape();
    prof.moveTo(0, 0);
    prof.lineTo(0.8, 0.05);
    prof.quadraticCurveTo(1.15, -0.55, 1.05, -1.45);
    prof.quadraticCurveTo(0.95, -2.2, 0.65, -2.45);
    prof.quadraticCurveTo(0.4, -2.52, 0.28, -2.26);
    prof.quadraticCurveTo(0.58, -1.15, 0, 0);
    const tg = new THREE.ExtrudeGeometry(prof, { depth: 1.9, bevelEnabled: true, bevelThickness: 0.2, bevelSize: 0.17, bevelSegments: 6, curveSegments: 24 });
    tg.translate(0, 0, -0.95); tg.rotateY(Math.PI / 2); // profile in the Y/Z plane, pointing back (-z); width along X
    const trigMat = new THREE.MeshStandardMaterial({ color: 0x2a2e31, roughness: 0.45, emissive: 0xe0402c, emissiveIntensity: 0 });
    mesh(tg, trigMat, hinge);
    triggers[name] = { hinge, mat: trigMat };
  }

  // ----- view: drag to turn, sized to the container -----
  const HOME = { yaw: -0.38, pitch: 0.32 };
  let yaw = HOME.yaw, pitch = HOME.pitch, drag = null;
  const el = renderer.domElement;
  el.style.touchAction = "none"; el.style.cursor = "grab";
  el.addEventListener("pointerdown", (e) => { drag = { x: e.clientX, y: e.clientY, yaw, pitch }; try { el.setPointerCapture(e.pointerId); } catch (err) { /* pointer already gone */ } el.style.cursor = "grabbing"; });
  el.addEventListener("pointermove", (e) => { if (!drag) return; yaw = drag.yaw + (e.clientX - drag.x) * 0.01; pitch = Math.max(-0.6, Math.min(1.1, drag.pitch + (e.clientY - drag.y) * 0.008)); });
  el.addEventListener("pointerup", () => { drag = null; el.style.cursor = "grab"; });
  el.addEventListener("dblclick", () => { yaw = HOME.yaw; pitch = HOME.pitch; });
  const fit = () => {
    const w = container.clientWidth || 400, h = container.clientHeight || 300;
    renderer.setSize(w, h, false); el.style.width = "100%"; el.style.height = "100%";
    camera.aspect = w / h;
    camera.position.z = w / h < 1.2 ? 27 : 22.5; // step back on narrow screens
    camera.updateProjectionMatrix();
  };
  new ResizeObserver(fit).observe(container); fit();

  // ----- live state, eased so presses look physical -----
  const target = { lx: 0, ly: 0, rx: 0, ry: 0, l2: 0, r2: 0, btn: {} };
  const cur = { lx: 0, ly: 0, rx: 0, ry: 0, l2: 0, r2: 0 };
  const press = {};
  const ease = (a, b, k) => a + (b - a) * k;
  const baseY = new Map();
  const sink = (m, name, depth) => { if (!baseY.has(m)) baseY.set(m, m.position.y); m.position.y = baseY.get(m) - p(name) * depth; };
  let p;
  function frame() {
    requestAnimationFrame(frame);
    if (!container.isConnected || container.offsetParent === null) return; // hidden page: skip
    model.rotation.y = ease(model.rotation.y, yaw, 0.2);
    model.rotation.x = ease(model.rotation.x, pitch, 0.2);
    for (const k of ["lx", "ly", "rx", "ry", "l2", "r2"]) cur[k] = ease(cur[k], target[k] || 0, 0.35);
    const b = target.btn || {};
    p = (name) => (press[name] = ease(press[name] || 0, b[name] ? 1 : 0, 0.45));
    // sticks lean the way they're pushed, and sink when clicked
    sticks.L.rotation.set(cur.ly * 0.38, 0, -cur.lx * 0.38); sink(sticks.L, "L3", 0.15);
    sticks.R.rotation.set(cur.ry * 0.38, 0, -cur.rx * 0.38); sink(sticks.R, "R3", 0.15);
    for (const [name, f] of Object.entries(face)) { sink(f.g, name, 0.12); f.symMat.emissiveIntensity = 0.25 + (press[name] || 0) * 2.4; }
    for (const [name, m] of Object.entries(dpad)) sink(m, name, 0.1);
    sink(ps, "PS", 0.06); sink(share, "share", 0.06); sink(options, "options", 0.06); sink(pad, "pad", 0.05);
    sink(bumpers.L, "L1", 0.12); sink(bumpers.R, "R1", 0.12);
    triggers.L.hinge.rotation.x = -cur.l2 * 0.42; triggers.L.mat.emissiveIntensity = cur.l2 * 0.45;
    triggers.R.hinge.rotation.x = -cur.r2 * 0.42; triggers.R.mat.emissiveIntensity = cur.r2 * 0.45;
    renderer.render(scene, camera);
  }
  requestAnimationFrame(frame);

  return {
    update(q, light) {
      Object.assign(target, { lx: q.lx || 0, ly: q.ly || 0, rx: q.rx || 0, ry: q.ry || 0, l2: q.l2 || 0, r2: q.r2 || 0, btn: q.btn || {} });
      if (light) { lightMat.color.set(light); lightMat.emissive.set(light); lightMat.emissiveIntensity = light === "#5b6266" ? 0.15 : 1.8; }
    },
    setColor(hex) { shellMat.color.set(hex); },
  };
}
