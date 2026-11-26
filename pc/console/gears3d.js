// LEGO Technic gears in 3D (three.js), built from their real proportions.
// Units are millimetres. LEGO spur gears use module 1: pitch radius = teeth / 2, so two
// meshing gears sit (t1 + t2) / 2 mm apart, which is (t1 + t2) / 16 studs (8 mm per stud).
import * as THREE from "./vendor/three/three.module.js";

const LIGHT = 0xa3a9ad; // LEGO light bluish grey
const DARK = 0x585c5f;  // LEGO dark bluish grey
const RED = 0xc4281c;   // red axle on the motor

// Per gear: colour, double bevel, and the holes punched through it.
const STYLE = {
  8: { color: LIGHT, bevel: false, holes: [] },
  12: { color: DARK, bevel: true, holes: [] },
  16: { color: LIGHT, bevel: false, holes: [["win", 4, 4.4, 1.3]] },
  20: { color: LIGHT, bevel: true, holes: [["pin", 4, 5.6, 0.9]] },
  24: { color: LIGHT, bevel: false, holes: [["pin", 4, 6.6, 2.4]] },
  36: { color: DARK, bevel: true, holes: [["lobe", 4, 0, 0]] },
  40: { color: LIGHT, bevel: false, holes: [["pin", 4, 8, 2.4], ["pin", 8, 14.6, 2.4]] },
};

function crossPath(size, arm, Kind = THREE.Path) {
  const s = size / 2, a = arm / 2, p = new Kind();
  p.moveTo(-a, -s); p.lineTo(a, -s); p.lineTo(a, -a); p.lineTo(s, -a); p.lineTo(s, a); p.lineTo(a, a);
  p.lineTo(a, s); p.lineTo(-a, s); p.lineTo(-a, a); p.lineTo(-s, a); p.lineTo(-s, -a); p.lineTo(-a, -a); p.closePath();
  return p;
}

function gearShape(t) {
  const rp = t / 2, tip = rp + 0.95, root = rp - 1.15, s = new THREE.Shape(), step = (Math.PI * 2) / t;
  // tapered teeth: root, flank, rounded tip, flank, root
  const prof = [[-0.5, root], [-0.3, root], [-0.19, rp], [-0.12, tip], [0.12, tip], [0.19, rp], [0.3, root]];
  for (let i = 0; i < t; i++) {
    const a0 = i * step;
    prof.forEach(([f, r], k) => {
      const a = a0 + f * step, x = Math.cos(a) * r, y = Math.sin(a) * r;
      if (i === 0 && k === 0) s.moveTo(x, y); else s.lineTo(x, y);
    });
  }
  s.closePath();
  const st = STYLE[t];
  s.holes.push(crossPath(4.8, 1.8)); // axle hole
  for (const [kind, n, at, size] of st.holes) {
    for (let k = 0; k < n; k++) {
      const a = (k / n) * Math.PI * 2 + Math.PI / 4, x = Math.cos(a) * at, y = Math.sin(a) * at;
      if (kind === "pin") { const h = new THREE.Path(); h.absarc(x, y, size, 0, Math.PI * 2, true); s.holes.push(h); }
      if (kind === "win") { // small windows on the 16T
        const h = new THREE.Path(), w = size, c = Math.cos(a), sn = Math.sin(a);
        const pt = (u, v) => [x + c * u - sn * v, y + sn * u + c * v];
        h.moveTo(...pt(-w, -w * 0.8)); h.lineTo(...pt(w, -w * 1.1)); h.lineTo(...pt(w, w * 1.1)); h.lineTo(...pt(-w, w * 0.8)); h.closePath();
        s.holes.push(h);
      }
      if (kind === "lobe") { // the 36T's four big cut-outs between spokes
        const r1 = 4.6, r2 = root - 2.6, half = 0.52, a0 = (k / n) * Math.PI * 2 + Math.PI / 4, h = new THREE.Path();
        h.absarc(0, 0, r2, a0 - half, a0 + half, false);
        h.absarc(0, 0, r1, a0 + half * 0.62, a0 - half * 0.62, true);
        h.closePath();
        s.holes.push(h);
      }
    }
  }
  return s;
}

const cache = new Map();
function gearGeometry(t) {
  if (cache.has(t)) return cache.get(t);
  const st = STYLE[t];
  const g = new THREE.ExtrudeGeometry(gearShape(t), {
    depth: st.bevel ? 2.6 : 3.2, curveSegments: 24, bevelEnabled: true,
    bevelThickness: st.bevel ? 0.95 : 0.35, bevelSize: st.bevel ? 0.6 : 0.3, bevelSegments: st.bevel ? 2 : 2,
  });
  g.center();
  cache.set(t, g);
  return g;
}

function axleMesh(color, length) {
  const g = new THREE.ExtrudeGeometry(crossPath(4.6, 1.7, THREE.Shape), { depth: length, bevelEnabled: false });
  g.translate(0, 0, -length / 2);
  const m = new THREE.Mesh(g, new THREE.MeshStandardMaterial({ color, roughness: 0.5 }));
  m.castShadow = true; return m;
}

function wormMesh() {
  const group = new THREE.Group();
  const mat = new THREE.MeshStandardMaterial({ color: DARK, roughness: 0.45 });
  const core = new THREE.Mesh(new THREE.CylinderGeometry(3.0, 3.0, 9.6, 32), mat);
  core.rotation.z = Math.PI / 2; core.castShadow = true; group.add(core);
  class Helix extends THREE.Curve {
    getPoint(u, target = new THREE.Vector3()) {
      const turns = 2.9, a = u * turns * Math.PI * 2, len = 9.0;
      return target.set(-len / 2 + u * len, Math.cos(a) * 3.55, Math.sin(a) * 3.55);
    }
  }
  const thread = new THREE.Mesh(new THREE.TubeGeometry(new Helix(), 220, 0.85, 10, false), mat);
  thread.castShadow = true; group.add(thread);
  return group;
}

function makeGear(t) {
  const st = STYLE[t];
  const mat = new THREE.MeshStandardMaterial({ color: st.color, roughness: 0.42, metalness: 0.0 });
  const m = new THREE.Mesh(gearGeometry(t), mat);
  m.castShadow = true; m.receiveShadow = true;
  return m;
}

// ---------- a little scene per view ----------
function makeView(container, { height }) {
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.shadowMap.enabled = true; renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping; renderer.toneMappingExposure = 1.1;
  container.innerHTML = ""; container.appendChild(renderer.domElement);
  const el = renderer.domElement; el.style.display = "block"; el.style.width = "100%"; el.style.height = "100%";
  if (!container.style.height && !getComputedStyle(container).aspectRatio.includes("/")) container.style.height = height + "px";
  el.style.cursor = "grab"; el.style.touchAction = "none";
  const scene = new THREE.Scene();
  scene.add(new THREE.HemisphereLight(0xffffff, 0x7f868b, 1.4));
  const key = new THREE.DirectionalLight(0xffffff, 2.3); key.position.set(-40, 70, 90); key.castShadow = true;
  key.shadow.mapSize.set(1024, 1024); key.shadow.radius = 5;
  Object.assign(key.shadow.camera, { left: -90, right: 90, top: 90, bottom: -90, near: 1, far: 300 });
  scene.add(key);
  const rim = new THREE.DirectionalLight(0xffffff, 0.8); rim.position.set(60, 20, -60); scene.add(rim);
  const floor = new THREE.Mesh(new THREE.PlaneGeometry(600, 600), new THREE.ShadowMaterial({ opacity: 0.16 }));
  floor.rotation.x = -Math.PI / 2; floor.receiveShadow = true; scene.add(floor);
  const camera = new THREE.PerspectiveCamera(28, 1, 1, 2000);
  const world = new THREE.Group(); scene.add(world);
  const view = { renderer, scene, camera, world, floor, el, yaw: -0.38, pitch: 0.32, fitW: 30, fitH: 20, center: new THREE.Vector3(), visible: true, tick: null };
  let drag = null;
  el.addEventListener("pointerdown", (e) => { drag = { x: e.clientX, y: e.clientY, yaw: view.yaw, pitch: view.pitch }; el.setPointerCapture(e.pointerId); el.style.cursor = "grabbing"; });
  el.addEventListener("pointermove", (e) => { if (!drag) return; view.yaw = drag.yaw + (e.clientX - drag.x) * 0.01; view.pitch = Math.max(-0.2, Math.min(1.35, drag.pitch + (e.clientY - drag.y) * 0.008)); });
  el.addEventListener("pointerup", () => { drag = null; el.style.cursor = "grab"; });
  el.addEventListener("dblclick", () => { view.yaw = -0.38; view.pitch = 0.32; });
  const size = () => {
    const w = container.clientWidth || 300, h = container.clientHeight || height;
    renderer.setSize(w, h, false); camera.aspect = w / h; camera.updateProjectionMatrix();
  };
  new ResizeObserver(size).observe(container); size();
  new IntersectionObserver((es) => { view.visible = es.some((e) => e.isIntersecting); }).observe(container);
  views.push(view);
  return view;
}

const views = [];
let last = performance.now();
function loop(now) {
  requestAnimationFrame(loop);
  const dt = Math.min(0.05, (now - last) / 1000); last = now;
  for (const v of views) {
    if (!v.visible || v.el.offsetParent === null) continue;
    if (v.tick) v.tick(dt);
    // camera orbits the train's centre; distance fits its size and the view's shape
    // far enough back to fit both the width and the height of what's shown
    const tan = Math.tan((v.camera.fov * Math.PI) / 360);
    const dist = Math.max(v.fitW / (tan * v.camera.aspect), v.fitH / tan) * 1.12 + 10;
    const c = v.center;
    v.camera.position.set(c.x + Math.sin(v.yaw) * Math.cos(v.pitch) * dist, c.y + Math.sin(v.pitch) * dist, c.z + Math.cos(v.yaw) * Math.cos(v.pitch) * dist);
    v.camera.lookAt(c);
    v.renderer.render(v.scene, v.camera);
  }
}
requestAnimationFrame(loop);

// ---------- gear trains ----------
// train: [t1, t2, t3, t4] (t3 = 0 for one stage; 1 = worm). Gears stand upright facing the
// viewer; a second stage shares the driven axle, one layer in front.
function buildTrain(view, train) {
  const [t1, t2, t3, t4] = train;
  view.world.clear();
  const rp = (t) => t / 2;
  const parts = [];
  const lift = (t) => (t === 1 ? 0 : rp(t) + 1.5);
  // stage 1
  let x1 = 0, y1, g1;
  const x2 = t1 === 1 ? 0 : rp(t1) + rp(t2);
  const axleY = Math.max(lift(t2), t3 ? lift(t3) : 0, t3 ? lift(t4) : 0, t1 === 1 ? 0 : lift(t1)) + 4;
  const g2 = makeGear(t2); g2.position.set(x2, axleY, 0);
  if (t1 === 1) { g1 = wormMesh(); y1 = axleY + rp(t2) + 3.55; x1 = x2; g1.position.set(x1, y1, 0); }
  else { g1 = makeGear(t1); y1 = axleY; g1.position.set(x1, y1, 0); }
  parts.push(g1, g2);
  // stage 2 on the driven axle, in front
  let g3 = null, g4 = null, x4 = x2;
  if (t3) { // second stage: always spur gears (a worm here would need a crossed axle)
    const zf = 8;
    g3 = makeGear(t3); g3.position.set(x2, axleY, zf);
    g4 = makeGear(t4);
    x4 = x2 + rp(t3) + rp(t4); g4.position.set(x4, axleY, zf);
    parts.push(g3, g4);
  }
  parts.forEach((p) => view.world.add(p));
  // axles: red on the motor, dark elsewhere
  const addAxle = (x, y, z0, z1, color, alongX) => {
    const a = axleMesh(color, alongX ? 18 : Math.abs(z1 - z0) + 10);
    if (alongX) { a.rotation.y = Math.PI / 2; a.position.set(x - 9, y, z0); }
    else a.position.set(x, y, (z0 + z1) / 2);
    view.world.add(a); return a;
  };
  const motorAxle = t1 === 1 ? addAxle(x1, y1, 0, 0, RED, true) : addAxle(x1, y1, -3, 3, RED, false);
  addAxle(x2, axleY, -3, t3 ? 11 : 3, 0x2b3033, false);
  if (t3) addAxle(x4, axleY, 5, 11, 0x2b3033, false);
  // fit the camera
  const box = new THREE.Box3().setFromObject(view.world), size = new THREE.Vector3();
  box.getCenter(view.center); box.getSize(size);
  view.fitW = size.x / 2 + 6; view.fitH = size.y / 2 + 8;
  view.floor.position.y = box.min.y - 0.2;
  // meshing: tooth of the driver faces a gap of the driven gear on the line between them
  const ph = (t) => Math.PI + Math.PI / t;
  let angle = 0;
  view.tick = (dt) => {
    angle += dt * 1.1; // motor turns at a fixed visual speed
    const r12 = t1 === 1 ? 1 / t2 : t1 / t2;
    if (t1 === 1) { g1.rotation.x = angle; } else { g1.rotation.z = angle; }
    motorAxle.rotation[t1 === 1 ? "x" : "z"] = angle;
    const a2 = (t1 === 1 ? 0 : ph(t2)) - angle * r12;
    g2.rotation.z = t1 === 1 ? angle * r12 : a2;
    if (t3) {
      // the second gear on the driven axle turns with it; it was mounted so that one of its
      // teeth faces the output gear at the start, which keeps the two meshing from then on
      const a3 = g2.rotation.z - (t1 === 1 ? 0 : ph(t2));
      g3.rotation.z = a3;
      g4.rotation.z = ph(t4) - a3 * (t3 / t4);
    }
  };
}

export function trainView(container, train, height) {
  const v = makeView(container, { height });
  buildTrain(v, train);
  return { set: (t) => buildTrain(v, t) };
}

// A row of every gear, turning slowly, to compare sizes.
export function partsView(container, list, height) {
  const v = makeView(container, { height });
  let x = 0; const gears = [];
  for (const t of list) {
    const r = t === 1 ? 4.5 : t / 2 + 1;
    x += r;
    const g = t === 1 ? wormMesh() : makeGear(t);
    g.position.set(x, t === 1 ? 4.5 : r + 1, 0);
    v.world.add(g); gears.push([g, t]);
    x += r + 10;
  }
  const box = new THREE.Box3().setFromObject(v.world), size = new THREE.Vector3();
  box.getCenter(v.center); box.getSize(size);
  v.fitW = size.x / 2 + 3; v.fitH = size.y / 2 + 4; v.pitch = 0.16; v.yaw = 0; // face-on, so the labels below line up
  v.floor.position.y = box.min.y - 0.2;
  v.tick = (dt) => gears.forEach(([g, t]) => { if (t === 1) g.rotation.x += dt * 1.2; else g.rotation.z += dt * 0.5 * (8 / t); });
  // labels under each gear are positioned by the caller from these x positions
  return { positions: gears.map(([g, t]) => ({ t, x: g.position.x })), width: x };
}
