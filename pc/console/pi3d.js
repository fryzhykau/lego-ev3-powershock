// A Raspberry Pi 2/3 Model B in 3D, with what the robot camera needs plugged in: the camera on its
// ribbon, power, the microSD card and (on a Pi 2) a WiFi dongle. Numbered markers follow the parts.
// createPi(container) -> { setModel("pi2" | "pi3"), setStatus({ live, reachable }), highlight(key | null), PARTS }
//
// Sizes in millimetres from the board's mechanical drawing (85 x 56 mm). Board coordinates: x along
// the long edge from the micro-USB end, y from the HDMI edge towards the GPIO header, z up.
// Scene: X = x - 42.5, Y = z, Z = 28 - y (so the HDMI edge faces the viewer).
import * as THREE from "./vendor/three/three.module.js";

export const PARTS = [
  { key: "camera", n: 1, title: "Camera connector", text: "Lift the connector's clip, push the ribbon in with its metal contacts facing the HDMI port, press the clip down. Only with the power off." },
  { key: "module", n: 2, title: "Camera module", text: "The lens points where the robot drives. Mounted upside down? Start the camera with --flip." },
  { key: "power", n: 3, title: "Power (micro-USB)", text: "5 V from a USB power bank on the robot: at least 2 A for a Pi 2, 2.5 A for a Pi 3. No power button: it starts when plugged in." },
  { key: "sd", n: 4, title: "microSD card (underneath)", text: "Raspberry Pi OS Lite, written with Raspberry Pi Imager with your WiFi and SSH set." },
  { key: "wifi", n: 5, title: "WiFi", text: "A Pi 2 needs a USB WiFi dongle in any USB port. A Pi 3 has WiFi built in." },
  { key: "leds", n: 6, title: "Lights", text: "Red: power is fine (flickering means too little power). Green flickering: reading the SD card." },
  { key: "unused", n: 7, title: "Not needed on the robot", text: "HDMI, audio, Ethernet, display connector and the GPIO pins stay empty." },
];

const P = (x, y, z) => new THREE.Vector3(x - 42.5, z, 28 - y); // board coordinates -> scene

function roundedRect(w, h, r) {
  const s = new THREE.Shape(), x = -w / 2, y = -h / 2;
  s.moveTo(x + r, y); s.lineTo(x + w - r, y); s.quadraticCurveTo(x + w, y, x + w, y + r);
  s.lineTo(x + w, y + h - r); s.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
  s.lineTo(x + r, y + h); s.quadraticCurveTo(x, y + h, x, y + h - r);
  s.lineTo(x, y + r); s.quadraticCurveTo(x, y, x + r, y);
  return s;
}

// A flat cable (ribbon) along a curve; its width runs along the scene's Z axis.
function ribbonGeometry(curve, width, segs = 120) {
  const pos = [], idx = [];
  for (let i = 0; i <= segs; i++) {
    const p = curve.getPoint(i / segs);
    pos.push(p.x, p.y, p.z - width / 2, p.x, p.y, p.z + width / 2);
    if (i < segs) { const a = i * 2; idx.push(a, a + 1, a + 2, a + 1, a + 3, a + 2); }
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
  g.setIndex(idx); g.computeVertexNormals();
  return g;
}

export function createPi(container) {
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  container.appendChild(renderer.domElement);
  renderer.domElement.style.display = "block";

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(32, 1, 1, 2000);
  camera.position.set(-6, 142, 166);
  camera.lookAt(0, 16, 4);
  scene.add(new THREE.HemisphereLight(0xffffff, 0x8a8f94, 1.3));
  const key = new THREE.DirectionalLight(0xffffff, 2.1);
  key.position.set(-80, 220, 140); key.castShadow = true; key.shadow.mapSize.set(1024, 1024);
  Object.assign(key.shadow.camera, { left: -150, right: 150, top: 150, bottom: -150, near: 10, far: 600 });
  scene.add(key);
  const floor = new THREE.Mesh(new THREE.PlaneGeometry(1200, 1200), new THREE.ShadowMaterial({ opacity: 0.16 }));
  floor.rotation.x = -Math.PI / 2; floor.position.y = -6; floor.receiveShadow = true; scene.add(floor);

  const model = new THREE.Group(); scene.add(model);
  const parts = {}; // key -> meshes to light up
  const add = (key, geo, mat, at, parent = model) => {
    const m = new THREE.Mesh(geo, mat); m.position.copy(at); m.castShadow = true; m.receiveShadow = true;
    parent.add(m); if (key) (parts[key] = parts[key] || []).push(m); return m;
  };
  const box = (w, d, h) => new THREE.BoxGeometry(w, h, d); // w along x, d along y, h up
  const mat = (color, o = {}) => new THREE.MeshStandardMaterial(Object.assign({ color, roughness: 0.55 }, o));
  const metal = mat(0xc9ced2, { metalness: 0.75, roughness: 0.35 });
  const black = mat(0x1d2023), dark = mat(0x0f1112), gold = mat(0xd6a531, { metalness: 0.8, roughness: 0.3 });
  const beige = mat(0xe8dfc8), white = mat(0xf2f3f3);

  // ----- the board -----
  const pcb = new THREE.ExtrudeGeometry(roundedRect(85, 56, 3), { depth: 1.4, bevelEnabled: false });
  pcb.rotateX(-Math.PI / 2);
  add(null, pcb, mat(0x1d7a3c, { roughness: 0.7 }), new THREE.Vector3(0, 0, 0));
  for (const [x, y] of [[3.5, 3.5], [61.5, 3.5], [3.5, 52.5], [61.5, 52.5]]) { // mounting holes
    const ring = add(null, new THREE.CylinderGeometry(3, 3, 0.2, 24), gold, P(x, y, 1.45));
    add(null, new THREE.CylinderGeometry(1.4, 1.4, 0.25, 20), mat(0xf2f3f3), P(x, y, 1.5));
    ring.castShadow = false;
  }
  const soc = add(null, box(14, 14, 1.2), black, P(29, 32, 2.0));
  add(null, box(8, 8, 1), black, P(59, 31, 1.9)); // USB/Ethernet chip

  // ----- GPIO header (not used) -----
  add("unused", box(51, 5, 2.5), black, P(32.1, 52.5, 2.65));
  const pinGeo = box(0.64, 0.64, 8.5);
  for (let i = 0; i < 20; i++) for (const y of [51.27, 53.81]) add(null, pinGeo, gold, P(8 + i * 2.54, y, 5.6)).castShadow = false;

  // ----- connectors along the HDMI edge -----
  add("power", box(8, 5.6, 3), metal, P(10.6, 2.4, 2.9));
  add("unused", box(15, 11.5, 6.5), metal, P(32, 4.8, 4.65));
  add("unused", box(7, 12, 6), black, P(53.5, 5.6, 4.4));
  const jack = add("unused", new THREE.CylinderGeometry(3, 3, 3, 20), black, P(53.5, -1.2, 4.4)); jack.rotation.x = Math.PI / 2;
  // camera (CSI) connector between HDMI and audio, display (DSI) connector at the SD end
  add("camera", box(3.6, 22, 5.5), beige, P(45, 11.5, 4.15));
  add("camera", box(4.2, 22.4, 1.2), dark, P(45, 11.5, 7.4));
  add("unused", box(3.6, 22, 5.5), beige, P(4.2, 28, 4.15));
  add("unused", box(4.2, 22.4, 1.2), dark, P(4.2, 28, 7.4));

  // ----- USB and Ethernet on the far short edge -----
  const usbSlots = [];
  for (const y of [9, 27]) {
    add("unused", box(17.5, 13.2, 15.6), metal, P(77.6, y, 9.2));
    for (const z of [5.5, 12.5]) usbSlots.push(add(null, box(0.3, 11, 4.4), dark, P(86.4, y, z + 1.4)));
  }
  add("unused", box(21, 16, 13.5), metal, P(76.6, 45.75, 8.15));
  add(null, box(0.3, 12, 9), dark, P(87.15, 45.75, 7.6));

  // ----- lights -----
  const red = mat(0x701010, { emissive: 0xff2a2a, emissiveIntensity: 1.2 });
  const green = mat(0x0f5a24, { emissive: 0x31e26c, emissiveIntensity: 0.2 });
  add("leds", box(1.6, 3, 0.9), red, P(1.6, 8, 1.85));
  add("leds", box(1.6, 3, 0.9), green, P(1.6, 11.6, 1.85));

  // ----- microSD card underneath, sticking out at the short edge -----
  add("sd", box(12, 14, 1.6), metal, P(7, 28, -0.9));
  add("sd", box(15, 11, 0.8), mat(0x2b3a8f), P(4.5, 28, -1.9));

  // ----- power plug and cable -----
  const plug = new THREE.Group(); model.add(plug);
  add("power", box(10.5, 9, 6.5), black, P(10.6, -7, 2.9), plug);
  add("power", box(6.6, 4, 1.8), metal, P(10.6, -1.5, 2.9), plug);
  const powerCurve = new THREE.CatmullRomCurve3([P(10.6, -11, 2.9), P(10.6, -28, 1), P(-4, -48, -3), P(-30, -55, -4.5)]);
  add("power", new THREE.TubeGeometry(powerCurve, 48, 1.9, 12), black, new THREE.Vector3());

  // ----- WiFi dongle (Pi 2) in the lower USB port -----
  const dongle = new THREE.Group(); model.add(dongle);
  add("wifi", box(4, 11.6, 4.4), metal, P(88.3, 9, 6.9), dongle);
  add("wifi", box(15, 14, 6.5), black, P(97.5, 9, 6.9), dongle);
  add("wifi", box(0.4, 3, 1.2), mat(0x1b3fb3, { emissive: 0x3d7bff, emissiveIntensity: 0.9 }), P(105.2, 7, 7.5), dongle);
  const wifiChip = add("wifi", box(5, 5, 1), black, P(5, 46, 1.9)); // the Pi 3's own WiFi chip and antenna

  // ----- camera ribbon and the camera module -----
  // the ribbon leaves the connector upwards and curls over to the module, which stands above the
  // HDMI end facing left (the way the robot drives); its contacts face the HDMI port
  const ribbonCurve = new THREE.CatmullRomCurve3([
    P(45, 11.5, 6), P(45, 11.5, 22), P(41, 11.5, 36), P(30, 11.5, 42), P(16, 11.5, 36), P(9, 11.5, 30), P(4, 11.5, 34), P(2, 11.5, 44),
  ].map((v, i, a) => v), false, "catmullrom", 0.5);
  const ribbon = add("camera", ribbonGeometry(ribbonCurve, 16), new THREE.MeshStandardMaterial({ color: 0xeef0f0, roughness: 0.6, side: THREE.DoubleSide }), new THREE.Vector3());
  ribbon.castShadow = true;
  add("camera", box(0.5, 16, 8), mat(0x2f6fd8), P(46.1, 11.5, 12)); // blue stiffener on the far side from the contacts
  const cam = new THREE.Group(); cam.position.copy(P(2, 11.5, 57)); model.add(cam);
  add("module", box(1.2, 25, 24), mat(0x1c1f22), new THREE.Vector3(0, 0, 0), cam);
  add("module", box(8, 12, 9), black, new THREE.Vector3(-3.6, 1, 0), cam); // lens holder
  const lens = add("module", new THREE.CylinderGeometry(5.2, 5.2, 9, 32), black, new THREE.Vector3(-11, 1, 0), cam); lens.rotation.z = Math.PI / 2;
  const glass = add("module", new THREE.CylinderGeometry(3.4, 3.4, 0.6, 32), mat(0x223a55, { metalness: 0.6, roughness: 0.1 }), new THREE.Vector3(-15.6, 1, 0), cam); glass.rotation.z = Math.PI / 2;
  add("module", box(1.6, 17, 3), beige, new THREE.Vector3(0.6, -10.5, 0), cam);

  // ----- numbered markers that follow the parts -----
  const anchors = {
    camera: P(45, 11.5, 9), module: P(2, 11.5, 70), power: P(10.6, -9, 7), sd: P(-1, 28, -1),
    wifi: P(98, 9, 11), leds: P(1.6, 9.8, 3), unused: P(32, 0, 8.5),
  };
  const layer = document.createElement("div");
  layer.className = "pimarks";
  container.appendChild(layer);
  const marks = {};
  for (const p of PARTS) {
    const el = document.createElement("span");
    el.className = "pimark"; el.textContent = p.n; el.title = p.title; el.dataset.key = p.key;
    layer.appendChild(el); marks[p.key] = el;
  }

  // ----- view: drag to turn -----
  const HOME = { yaw: 0.5, pitch: 0.12 };
  let yaw = HOME.yaw, pitch = HOME.pitch, drag = null;
  const el = renderer.domElement;
  el.style.touchAction = "none"; el.style.cursor = "grab";
  el.addEventListener("pointerdown", (e) => { drag = { x: e.clientX, y: e.clientY, yaw, pitch }; try { el.setPointerCapture(e.pointerId); } catch (err) { /* pointer gone */ } el.style.cursor = "grabbing"; });
  el.addEventListener("pointermove", (e) => { if (!drag) return; yaw = drag.yaw + (e.clientX - drag.x) * 0.01; pitch = Math.max(-0.5, Math.min(0.9, drag.pitch + (e.clientY - drag.y) * 0.008)); });
  el.addEventListener("pointerup", () => { drag = null; el.style.cursor = "grab"; });
  el.addEventListener("dblclick", () => { yaw = HOME.yaw; pitch = HOME.pitch; });
  const fit = () => {
    const w = container.clientWidth || 400, h = container.clientHeight || 300;
    renderer.setSize(w, h, false); el.style.width = "100%"; el.style.height = "100%";
    camera.aspect = w / h; camera.updateProjectionMatrix();
  };
  new ResizeObserver(fit).observe(container); fit();

  // ----- state -----
  let lit = null, status = {};
  const glow = new Map(); // mesh -> its own emissive, to restore
  function light(key) {
    for (const [m, e] of glow) { m.material.emissive.setHex(e[0]); m.material.emissiveIntensity = e[1]; }
    glow.clear();
    lit = key;
    if (!key) return;
    for (const m of parts[key] || []) {
      if (!m.material.emissive) continue;
      if (!glow.has(m)) { m.material = m.material.clone(); glow.set(m, [m.material.emissive.getHex(), m.material.emissiveIntensity]); }
      m.material.emissive.setHex(0xffb020); m.material.emissiveIntensity = 0.55;
    }
  }
  const v = new THREE.Vector3();
  let t = 0;
  function frame() {
    requestAnimationFrame(frame);
    if (!container.isConnected || container.offsetParent === null) return;
    t += 1;
    model.rotation.y += (yaw - model.rotation.y) * 0.2;
    model.rotation.x += (pitch - model.rotation.x) * 0.2;
    green.emissiveIntensity = status.reachable ? (Math.sin(t / 5) > 0.3 ? 1.4 : 0.2) : 0.15; // ACT light flickers when the Pi is up
    renderer.render(scene, camera);
    const w = container.clientWidth, h = container.clientHeight;
    model.updateMatrixWorld();
    for (const p of PARTS) {
      const m = marks[p.key];
      if (p.key === "wifi" && !dongle.visible) { v.copy(wifiChip.position).add(new THREE.Vector3(0, 4, 0)); } else v.copy(anchors[p.key]);
      v.applyMatrix4(model.matrixWorld).project(camera);
      m.style.transform = `translate(${((v.x + 1) / 2 * w).toFixed(1)}px, ${((1 - v.y) / 2 * h).toFixed(1)}px) translate(-50%, -50%)`;
    }
  }
  requestAnimationFrame(frame);

  return {
    PARTS,
    setModel(m) {
      const pi2 = m !== "pi3";
      dongle.visible = pi2; wifiChip.visible = !pi2;
      soc.material = pi2 ? black : metal; // the Pi 3's processor has a silver lid
    },
    setStatus(s) {
      status = s || {};
      marks.camera.classList.toggle("ok", !!status.live); marks.module.classList.toggle("ok", !!status.live);
      marks.power.classList.toggle("ok", !!status.reachable); marks.wifi.classList.toggle("ok", !!status.reachable);
      marks.sd.classList.toggle("ok", !!status.reachable);
    },
    highlight(key) {
      if (key === lit) return;
      light(key);
      for (const [k, m] of Object.entries(marks)) m.classList.toggle("on", k === key);
    },
  };
}
