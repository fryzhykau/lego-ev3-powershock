// A DualShock 4 built from three.js shapes (no model files), with parts that move.
// createDS4(container) -> { update(input, lightColor), setColor(hex) }
// input: { lx, ly, rx, ry, l2, r2, btn: { cross, circle, square, triangle, L1, R1, L3, R3,
//          up, down, left, right, share, options, PS, pad } }
import * as THREE from "./vendor/three/three.module.js";

export const COLORS = {
  "Magma Red": 0xc8211f,
  "Jet Black": 0x1d2023,
  "Wave Blue": 0x1f4fb5,
  "Glacier White": 0xe9ecee,
  "Midnight Blue": 0x1b2742,
  "Gold": 0xb8954a,
};

// Same outline as the 2D drawing, in a 440 x 300 box; mapped to centimetres (16 cm wide).
const K = 16 / 440;
const X = (x) => (x - 220) * K;
const Z = (y) => (y - 150) * K;

function outlineShape() {
  const s = new THREE.Shape();
  const P = (x, y) => [X(x), -Z(y)]; // shape is drawn in XY, then laid flat
  s.moveTo(...P(95, 40));
  s.lineTo(...P(345, 40));
  s.bezierCurveTo(...P(382, 40), ...P(402, 58), ...P(410, 92));
  // The shell stops where the wings end; the grips are separate swept handles (see below),
  // so the outline no longer includes the grip lobes.
  s.lineTo(...P(420, 150));
  s.bezierCurveTo(...P(424, 188), ...P(408, 208), ...P(380, 208));
  s.lineTo(...P(60, 208));
  s.bezierCurveTo(...P(32, 208), ...P(16, 188), ...P(20, 150));
  s.lineTo(...P(30, 92));
  s.bezierCurveTo(...P(38, 58), ...P(58, 40), ...P(95, 40));
  return s;
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
    depth, bevelEnabled: true, bevelThickness: bevel, bevelSize: bevel * 0.9, bevelSegments: segs, curveSegments: 48,
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
  const c = document.createElement("canvas"); c.width = 512; c.height = 280;
  const g = c.getContext("2d");
  g.fillStyle = "#16191b"; g.fillRect(0, 0, c.width, c.height);
  g.fillStyle = "#0b0c0d";
  for (let y = 10; y < c.height; y += 14) for (let x = 10 + ((y / 14) % 2) * 7; x < c.width; x += 14) { g.beginPath(); g.arc(x, y, 3.2, 0, 7); g.fill(); }
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; return t;
}

// Sweeps an oval cross-section along a curve. rx(u) / ry(u) give the half-width and
// half-height at u (0..1); tone(u) is a brightness factor stored as vertex colour.
function sweep(curve, rx, ry, tone, segs = 64, around = 40) {
  const pos = [], col = [], idx = [];
  const up = new THREE.Vector3(0, 1, 0), T = new THREE.Vector3(), B = new THREE.Vector3(), N = new THREE.Vector3(), C = new THREE.Vector3();
  for (let i = 0; i <= segs; i++) {
    const u = i / segs;
    curve.getPointAt(u, C); curve.getTangentAt(u, T);
    B.crossVectors(T, up).normalize(); N.crossVectors(B, T).normalize();
    const a = rx(u), b = ry(u), k = tone(u);
    for (let j = 0; j <= around; j++) {
      const t = (j / around) * Math.PI * 2, c = Math.cos(t), sn = Math.sin(t);
      pos.push(C.x + B.x * a * c + N.x * b * sn, C.y + B.y * a * c + N.y * b * sn, C.z + B.z * a * c + N.z * b * sn);
      // the underside of the lower grip is the darker, textured part
      const under = sn < 0.2 ? 1 : 0;
      const f = 1 - (1 - k) * under;
      col.push(f, f, f);
    }
  }
  for (let i = 0; i < segs; i++) for (let j = 0; j < around; j++) {
    const a = i * (around + 1) + j, b = a + around + 1;
    idx.push(a, b, a + 1, b, b + 1, a + 1);
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
  g.setAttribute("color", new THREE.Float32BufferAttribute(col, 3));
  g.setIndex(idx); g.computeVertexNormals();
  return g;
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
  camera.position.set(0, 10.5, 19.5);
  camera.lookAt(0, -1.4, 0.6);

  // studio lighting
  scene.add(new THREE.HemisphereLight(0xffffff, 0x8a8f94, 1.25));
  const key = new THREE.DirectionalLight(0xffffff, 2.2);
  key.position.set(-6, 14, 9); key.castShadow = true;
  key.shadow.mapSize.set(1024, 1024); key.shadow.radius = 6;
  Object.assign(key.shadow.camera, { left: -12, right: 12, top: 12, bottom: -12, near: 1, far: 40 });
  scene.add(key);
  const rim = new THREE.DirectionalLight(0xffffff, 0.9); rim.position.set(8, 4, -10); scene.add(rim);
  const floor = new THREE.Mesh(new THREE.PlaneGeometry(60, 60), new THREE.ShadowMaterial({ opacity: 0.18 }));
  floor.rotation.x = -Math.PI / 2; floor.position.y = -4.6; floor.receiveShadow = true; scene.add(floor);

  // materials
  const shell = new THREE.MeshPhysicalMaterial({ color: COLORS["Magma Red"], roughness: 0.5, clearcoat: 0.25, clearcoatRoughness: 0.5 });
  const dark = new THREE.MeshStandardMaterial({ color: 0x24282b, roughness: 0.55 });
  const darker = new THREE.MeshStandardMaterial({ color: 0x141618, roughness: 0.7 });
  const rubber = new THREE.MeshStandardMaterial({ color: 0x2a2e31, roughness: 0.85, side: THREE.DoubleSide });
  const capMat = new THREE.MeshStandardMaterial({ color: 0x24282b, roughness: 0.5, side: THREE.DoubleSide });
  const lightMat = new THREE.MeshStandardMaterial({ color: 0x3d7bff, emissive: 0x3d7bff, emissiveIntensity: 1.6 });
  const hiMat = (c) => new THREE.MeshStandardMaterial({ color: c, roughness: 0.4 });

  const model = new THREE.Group();
  scene.add(model);
  const mesh = (geo, mat, parent = model) => { const m = new THREE.Mesh(geo, mat); m.castShadow = true; m.receiveShadow = true; parent.add(m); return m; };

  // ----- body: shell plus two grips -----
  // Real DS4: 16.2 cm wide, 9.8 cm front to back (grips included), 5.2 cm tall (grips included).
  // The shell is about 2.4 cm thick with a fairly tight edge radius; the grips hang below it.
  mesh(slab(outlineShape(), 1.35, 0.5, 8), shell);
  // Grips: start under the wings, splay outwards a little and run back and down towards the
  // player, tapering to a rounded end; oval in section, about 3 cm wide at the root.
  const gripMat = new THREE.MeshPhysicalMaterial({ color: COLORS["Magma Red"], roughness: 0.55, clearcoat: 0.2, clearcoatRoughness: 0.6, vertexColors: true });
  const smooth = (a, b, u) => { const t = Math.min(1, Math.max(0, (u - a) / (b - a))); return t * t * (3 - 2 * t); };
  const endCap = (u) => (u < 0.84 ? 1 : Math.sqrt(Math.max(0, 1 - ((u - 0.84) / 0.16) ** 2)));
  for (const side of [-1, 1]) {
    // starts inside the wing (hidden), comes out under its rounded end and runs down and back
    const spine = new THREE.CatmullRomCurve3([
      new THREE.Vector3(side * 5.25, -1.0, -0.9),
      new THREE.Vector3(side * 5.55, -1.25, 1.0),
      new THREE.Vector3(side * 5.9, -1.95, 2.55),
      new THREE.Vector3(side * 6.15, -2.75, 3.75),
      new THREE.Vector3(side * 6.25, -3.3, 4.55),
    ]);
    const g = sweep(spine,
      (u) => (1.6 - 0.42 * smooth(0.15, 1, u)) * endCap(u),                       // half-width, tapering
      (u) => (1.0 + 0.35 * smooth(0.05, 0.4, u) - 0.3 * smooth(0.5, 1, u)) * endCap(u), // half-height
      (u) => 1 - 0.22 * smooth(0.4, 0.6, u));                                      // darker lower band
    mesh(g, gripMat);
  }
  // raised areas around the D-pad and the face buttons, as on the real shell
  for (const cx of [X(88), X(352)]) {
    const pod = mesh(new THREE.SphereGeometry(1, 48, 24, 0, Math.PI * 2, 0, Math.PI / 2), shell);
    pod.scale.set(1.85, 0.3, 1.8); pod.position.set(cx, -0.06, -1.9);
  }
  // D-pad sits in a round dish
  const dish = mesh(new THREE.CylinderGeometry(1.42, 1.3, 0.2, 48), darker); dish.position.set(X(88), 0.16, -1.93);
  // underside bulge between the grips
  const belly = mesh(new THREE.SphereGeometry(1, 40, 24), shell);
  belly.scale.set(4.4, 1.0, 2.4); belly.position.set(0, -1.85, -1.1);
  // ports: micro-USB at the back, headset jack and extension port at the front
  const usb = mesh(new THREE.BoxGeometry(0.85, 0.28, 0.1), darker); usb.position.set(0, -1.05, Z(40) - 0.52);
  const jack = mesh(new THREE.CylinderGeometry(0.17, 0.17, 0.1, 20), darker); jack.rotation.x = Math.PI / 2; jack.position.set(-0.35, -1.0, Z(208) + 0.5);
  const ext = mesh(new THREE.BoxGeometry(0.75, 0.22, 0.1), darker); ext.position.set(0.55, -1.0, Z(208) + 0.5);

  // ----- top: touchpad, light strip, speaker, PS button -----
  const pad = mesh(slab(roundedRect(5.25, 2.5, 0.35), 0.12, 0.06, 3), new THREE.MeshStandardMaterial({ map: dotsTexture(), roughness: 0.75 }));
  pad.position.set(0, 0.12, Z(85)); pad.rotation.x = 0.09;
  const strip = mesh(new THREE.BoxGeometry(4.9, 0.05, 0.1), lightMat); strip.position.set(0, 0.12, Z(50) - 0.02); strip.castShadow = false;
  const bar = mesh(new THREE.BoxGeometry(4.4, 0.32, 0.06), lightMat); bar.position.set(0, -0.95, Z(40) - 0.72); bar.castShadow = false;
  for (const [row, n] of [[-1, 4], [0, 5], [1, 4]]) for (let i = 0; i < n; i++) {
    const d = mesh(new THREE.CylinderGeometry(0.065, 0.065, 0.05, 12), darker); d.position.set((i - (n - 1) / 2) * 0.2, 0.02, -0.72 + row * 0.15);
  }
  const ps = mesh(new THREE.CylinderGeometry(0.32, 0.32, 0.16, 32), dark); ps.position.set(0, 0.08, 0.5);
  const share = mesh(new THREE.CapsuleGeometry(0.14, 0.42, 6, 12), dark); share.rotation.x = Math.PI / 2; share.rotation.z = 0.25; share.position.set(X(133), 0.08, -3.24);
  const options = mesh(new THREE.CapsuleGeometry(0.14, 0.42, 6, 12), dark); options.rotation.x = Math.PI / 2; options.rotation.z = -0.25; options.position.set(X(307), 0.08, -3.24);

  // ----- d-pad -----
  const arrow = new THREE.Shape();
  arrow.moveTo(-0.3, 0.35); arrow.lineTo(-0.3, 1.0); arrow.quadraticCurveTo(-0.3, 1.08, -0.22, 1.08);
  arrow.lineTo(0.22, 1.08); arrow.quadraticCurveTo(0.3, 1.08, 0.3, 1.0); arrow.lineTo(0.3, 0.35); arrow.lineTo(0, 0.12); arrow.closePath();
  const dpad = {};
  for (const [name, ang] of [["up", 0], ["right", -Math.PI / 2], ["down", Math.PI], ["left", Math.PI / 2]]) {
    const g = slab(arrow, 0.16, 0.06, 3); g.scale(1.05, 1, 1.05); g.rotateY(ang);
    const m = mesh(g, dark); m.position.set(X(88), 0.42, -1.93); dpad[name] = m;
  }

  // ----- face buttons: domed caps with coloured symbols -----
  const capProfile = [[0, 0.3], [0.2, 0.3], [0.33, 0.27], [0.4, 0.2], [0.42, 0]].map(([x, y]) => new THREE.Vector2(x, y));
  const face = {};
  for (const [name, dx, dz, col] of [["triangle", 0, -1, "#3fd0b4"], ["circle", 1, 0, "#ff5b5b"], ["cross", 0, 1, "#7aa8ff"], ["square", -1, 0, "#ff7fd1"]]) {
    const g = new THREE.Group(); model.add(g);
    g.position.set(X(352) + dx * 0.95, 0.22, -1.9 + dz * 0.95); g.scale.setScalar(1.05);
    mesh(new THREE.LatheGeometry(capProfile, 32), capMat, g);
    const symMat = new THREE.MeshStandardMaterial({ map: symbolTexture(name, col), transparent: true, emissive: new THREE.Color(col), emissiveMap: symbolTexture(name, col), emissiveIntensity: 0.25 });
    const sym = new THREE.Mesh(new THREE.CircleGeometry(0.3, 32), symMat); sym.rotation.x = -Math.PI / 2; sym.position.y = 0.305; g.add(sym);
    face[name] = { g, symMat };
  }

  // ----- sticks: wells, shafts that pivot, dished caps -----
  const capLathe = [[0, 0.95], [0.4, 0.98], [0.62, 1.06], [0.74, 1.04], [0.78, 0.94], [0.72, 0.84], [0.32, 0.8], [0.3, 0.2], [0, 0.2]].map(([x, y]) => new THREE.Vector2(x, y));
  const sticks = {};
  for (const [name, sx] of [["L", 152], ["R", 288]]) {
    const SZ = 0.05;
    const mound = mesh(new THREE.SphereGeometry(1, 48, 24, 0, Math.PI * 2, 0, Math.PI / 2), shell);
    mound.scale.set(1.55, 0.36, 1.55); mound.position.set(X(sx), -0.05, SZ);
    const ring = mesh(new THREE.TorusGeometry(1.08, 0.1, 12, 48), shell); ring.rotation.x = Math.PI / 2; ring.position.set(X(sx), 0.3, SZ);
    const hole = mesh(new THREE.CylinderGeometry(1.06, 1.06, 0.3, 40), darker); hole.position.set(X(sx), 0.18, SZ);
    const pivot = new THREE.Group(); pivot.position.set(X(sx), -0.25, SZ); pivot.scale.setScalar(1.18); model.add(pivot);
    mesh(new THREE.LatheGeometry(capLathe, 40), rubber, pivot);
    const grip = mesh(new THREE.TorusGeometry(0.72, 0.06, 8, 40), darker, pivot); grip.rotation.x = Math.PI / 2; grip.position.y = 1.0;
    sticks[name] = pivot;
  }

  // ----- shoulder buttons and hinged triggers at the back -----
  const bumpers = {}, triggers = {};
  for (const [name, side] of [["L", -1], ["R", 1]]) {
    const b = mesh(slab(roundedRect(3.0, 0.75, 0.37), 0.32, 0.18, 5), dark);
    b.position.set(side * 3.8, -0.05, Z(40) - 0.3); bumpers[name] = b;
    const hinge = new THREE.Group(); hinge.position.set(side * 3.8, -0.5, Z(40) - 0.15); model.add(hinge);
    // side profile: x = towards the back, y = up; the front (finger) face curves inwards
    const prof = new THREE.Shape();
    prof.moveTo(0, 0);
    prof.lineTo(0.85, 0.05);
    prof.quadraticCurveTo(1.25, -0.6, 1.12, -1.55);
    prof.quadraticCurveTo(1.02, -2.35, 0.7, -2.62);
    prof.quadraticCurveTo(0.42, -2.7, 0.3, -2.42);
    prof.quadraticCurveTo(0.62, -1.25, 0, 0);
    const tg = new THREE.ExtrudeGeometry(prof, { depth: 2.3, bevelEnabled: true, bevelThickness: 0.24, bevelSize: 0.2, bevelSegments: 6, curveSegments: 24 });
    tg.translate(0, 0, -1.15); tg.rotateY(Math.PI / 2); // profile in the Y/Z plane, pointing back; width along X
    const trigMat = new THREE.MeshStandardMaterial({ color: 0x2a2e31, roughness: 0.45, emissive: 0xe0402c, emissiveIntensity: 0 });
    mesh(tg, trigMat, hinge);
    triggers[name] = { hinge, mat: trigMat };
  }

  // ----- view: drag to turn, sized to the container -----
  const HOME = { yaw: -0.42, pitch: 0.0 };
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
    camera.position.z = w / h < 1.2 ? 23.5 : 19.5; // step back on narrow screens
    camera.updateProjectionMatrix();
  };
  new ResizeObserver(fit).observe(container); fit();

  // ----- live state, eased so presses look physical -----
  const target = { lx: 0, ly: 0, rx: 0, ry: 0, l2: 0, r2: 0, btn: {} };
  const cur = { lx: 0, ly: 0, rx: 0, ry: 0, l2: 0, r2: 0 };
  const press = {};
  const ease = (a, b, k) => a + (b - a) * k;
  function frame() {
    requestAnimationFrame(frame);
    if (!container.isConnected || container.offsetParent === null) return; // hidden page: skip
    model.rotation.y = ease(model.rotation.y, yaw, 0.2);
    model.rotation.x = ease(model.rotation.x, pitch, 0.2);
    for (const k of ["lx", "ly", "rx", "ry", "l2", "r2"]) cur[k] = ease(cur[k], target[k] || 0, 0.35);
    const b = target.btn || {};
    const p = (name) => (press[name] = ease(press[name] || 0, b[name] ? 1 : 0, 0.45));
    // sticks lean the way they're pushed, and sink when clicked
    sticks.L.rotation.set(cur.ly * 0.38, 0, -cur.lx * 0.38); sticks.L.position.y = -0.25 - p("L3") * 0.15;
    sticks.R.rotation.set(cur.ry * 0.38, 0, -cur.rx * 0.38); sticks.R.position.y = -0.25 - p("R3") * 0.15;
    for (const [name, f] of Object.entries(face)) { const v = p(name); f.g.position.y = 0.22 - v * 0.14; f.symMat.emissiveIntensity = 0.25 + v * 2.4; }
    for (const [name, m] of Object.entries(dpad)) m.position.y = 0.42 - p(name) * 0.1;
    ps.position.y = 0.08 - p("PS") * 0.06; share.position.y = 0.08 - p("share") * 0.06; options.position.y = 0.08 - p("options") * 0.06;
    pad.position.y = 0.12 - p("pad") * 0.05;
    bumpers.L.position.y = -0.1 - p("L1") * 0.12; bumpers.R.position.y = -0.1 - p("R1") * 0.12;
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
    setColor(hex) { shell.color.set(hex); gripMat.color.set(hex); },
  };
}
