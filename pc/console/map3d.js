// The live map in 3D (three.js): the floor, what the sensors found, the robot and its trail.
// createMap(container) -> { update(snapshot), setView("behind" | "above") }
// The snapshot comes from /api/map (pc/worldmap.py): centimetres, x ahead, y to the left.
// In the scene, X = x, Z = -y and Y is up, so the robot starts facing +X.
import * as THREE from "./vendor/three/three.module.js";

// leJOS colour IDs -> what the floor looks like
const FLOOR = { 0: 0xd8392b, 1: 0x2f9e57, 2: 0x2d6fd8, 3: 0xf1c40f, 6: 0xf4f5f5, 7: 0x232628, 13: 0x7b4a28 };
const MAX = 8000;

export function createMap(container) {
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.shadowMap.enabled = true;
  container.appendChild(renderer.domElement);
  renderer.domElement.style.display = "block";

  const scene = new THREE.Scene();
  scene.fog = new THREE.Fog(0xe9ecec, 450, 1100);
  const camera = new THREE.PerspectiveCamera(48, 1, 1, 3000);
  scene.add(new THREE.HemisphereLight(0xffffff, 0x9aa3a7, 1.6));
  const sun = new THREE.DirectionalLight(0xffffff, 1.6);
  sun.position.set(-120, 300, 160); sun.castShadow = true;
  sun.shadow.mapSize.set(1024, 1024);
  Object.assign(sun.shadow.camera, { left: -300, right: 300, top: 300, bottom: -300, near: 10, far: 900 });
  scene.add(sun); scene.add(sun.target);

  // floor with a 20 cm grid and a mark where the map started
  const floor = new THREE.Mesh(new THREE.PlaneGeometry(4000, 4000), new THREE.MeshStandardMaterial({ color: 0xe9ecec, roughness: 1 }));
  floor.rotation.x = -Math.PI / 2; floor.receiveShadow = true; scene.add(floor);
  const grid = new THREE.GridHelper(800, 40, 0xc3cacd, 0xd6dbdd); grid.position.y = 0.05; scene.add(grid);
  const start = new THREE.Mesh(new THREE.RingGeometry(5, 6.5, 32), new THREE.MeshBasicMaterial({ color: 0x8a949a }));
  start.rotation.x = -Math.PI / 2; start.position.y = 0.1; scene.add(start);

  // obstacles: one block per grid cell, darker the surer the map is
  const cellGeo = new THREE.BoxGeometry(1, 1, 1); cellGeo.translate(0, 0.5, 0);
  const cells = new THREE.InstancedMesh(cellGeo, new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: 0.7 }), MAX);
  cells.castShadow = true; cells.receiveShadow = true; cells.count = 0; cells.frustumCulled = false; scene.add(cells); // instances move: don't cull by the first bounds
  // floor colours the colour sensor saw
  const tileGeo = new THREE.PlaneGeometry(1, 1); tileGeo.rotateX(-Math.PI / 2);
  const tiles = new THREE.InstancedMesh(tileGeo, new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: 0.9 }), MAX);
  tiles.position.y = 0.2; tiles.count = 0; tiles.frustumCulled = false; scene.add(tiles);

  // the robot: body, wheels, the eye at the front and its beam
  const robot = new THREE.Group(); scene.add(robot);
  const white = new THREE.MeshStandardMaterial({ color: 0xf2f3f3, roughness: 0.6 });
  const grey = new THREE.MeshStandardMaterial({ color: 0x9aa1a4, roughness: 0.6 });
  const black = new THREE.MeshStandardMaterial({ color: 0x1f2224, roughness: 0.85 });
  const body = new THREE.Mesh(new THREE.BoxGeometry(1, 1, 1), white); body.castShadow = true; robot.add(body);
  const brick = new THREE.Mesh(new THREE.BoxGeometry(1, 1, 1), grey); brick.castShadow = true; robot.add(brick);
  const wheels = [0, 1, 2, 3].map(() => { const w = new THREE.Mesh(new THREE.CylinderGeometry(1, 1, 1, 28), black); w.rotation.x = Math.PI / 2; w.castShadow = true; robot.add(w); return w; });
  const eye = new THREE.Mesh(new THREE.BoxGeometry(2.5, 2.5, 5), new THREE.MeshStandardMaterial({ color: 0x23272a })); robot.add(eye);
  const beamMat = new THREE.MeshBasicMaterial({ color: 0xd1242f, transparent: true, opacity: 0.22, depthWrite: false });
  const beamGeo = new THREE.ConeGeometry(1, 1, 24, 1, true); beamGeo.translate(0, -0.5, 0); beamGeo.rotateZ(Math.PI / 2);
  const beam = new THREE.Mesh(beamGeo, beamMat); robot.add(beam);
  const dot = new THREE.Mesh(new THREE.SphereGeometry(1.6, 16, 12), new THREE.MeshBasicMaterial({ color: 0xd1242f })); robot.add(dot);

  // the path driven so far
  const trailPos = new Float32Array(3000 * 3);
  const trailGeo = new THREE.BufferGeometry(); trailGeo.setAttribute("position", new THREE.BufferAttribute(trailPos, 3)); trailGeo.setDrawRange(0, 0);
  const trail = new THREE.Line(trailGeo, new THREE.LineBasicMaterial({ color: 0x2d6fd8 })); trail.frustumCulled = false; scene.add(trail);

  let size = { wheel: 56, track: 120, base: 140, eyeAhead: 60, eyeAngle: 0 }, layout = "tank";
  function shapeRobot() {
    const W = size.track / 10 + 3, wr = size.wheel / 20, L = layout === "car" ? size.base / 10 + 8 : Math.max(12, W * 1.2);
    const cx = layout === "car" ? size.base / 20 : 0; // a car turns around its driven rear axle
    body.scale.set(L, 4, W - 4); body.position.set(cx, wr + 1, 0);
    brick.scale.set(Math.min(12, L * 0.6), 4.5, Math.min(7.6, W - 6)); brick.position.set(cx - 1, wr + 5, 0);
    const axles = layout === "car" ? [0, size.base / 10] : [0, 0];
    wheels.forEach((w, i) => { w.scale.set(wr, 2.8, wr); w.position.set(axles[i >> 1], wr, (i & 1 ? 1 : -1) * (W / 2 - 1.4)); w.visible = layout === "car" || i < 2; });
    eye.position.set(size.eyeAhead / 10, wr + 3, 0); eye.rotation.y = THREE.MathUtils.degToRad(size.eyeAngle);
  }
  shapeRobot();

  // ----- camera: behind the robot (like a car's driver display) or straight above -----
  let view = "behind", zoom = 1, placed = false, snapCamera = false;
  const pose = { x: 0, z: 0, h: 0 }, shown = { x: 0, z: 0, h: 0 };
  const camPos = new THREE.Vector3(-120, 90, 0), camLook = new THREE.Vector3();
  renderer.domElement.addEventListener("wheel", (e) => { e.preventDefault(); zoom = Math.max(0.4, Math.min(3, zoom * (e.deltaY > 0 ? 1.12 : 0.89))); }, { passive: false });
  const fit = () => {
    const w = container.clientWidth || 600, h = container.clientHeight || 400;
    renderer.setSize(w, h, false); renderer.domElement.style.width = "100%"; renderer.domElement.style.height = "100%";
    camera.aspect = w / h; camera.updateProjectionMatrix();
  };
  new ResizeObserver(fit).observe(container); fit();

  const tmp = new THREE.Object3D(), col = new THREE.Color();
  function frame() {
    requestAnimationFrame(frame);
    if (!container.isConnected || container.offsetParent === null) return; // page hidden
    // glide to the latest pose (status arrives 4 times a second)
    shown.x += (pose.x - shown.x) * 0.2; shown.z += (pose.z - shown.z) * 0.2;
    let dh = pose.h - shown.h; dh = Math.atan2(Math.sin(dh), Math.cos(dh)); shown.h += dh * 0.2;
    robot.position.set(shown.x, 0, shown.z); robot.rotation.y = shown.h;
    const fx = Math.cos(shown.h), fz = -Math.sin(shown.h);
    const k = snapCamera ? 1 : 0.08;
    snapCamera = false;
    if (view === "behind") {
      camPos.lerp(new THREE.Vector3(shown.x - fx * 120 * zoom, 85 * zoom, shown.z - fz * 120 * zoom), k);
      camLook.lerp(new THREE.Vector3(shown.x + fx * 70, 0, shown.z + fz * 70), Math.min(1, k * 1.5));
    } else {
      camPos.lerp(new THREE.Vector3(shown.x - 1, 420 * zoom, shown.z), Math.min(1, k * 1.25));
      camLook.lerp(new THREE.Vector3(shown.x, 0, shown.z), Math.min(1, k * 1.9));
    }
    camera.position.copy(camPos); camera.lookAt(camLook);
    sun.position.set(shown.x - 120, 300, shown.z + 160); sun.target.position.set(shown.x, 0, shown.z);
    renderer.render(scene, camera);
  }
  requestAnimationFrame(frame);

  return {
    setView(v) { view = v; },
    update(s) {
      if (!s) return;
      const c = s.cell || 4;
      if (s.robot && (s.robot.wheel !== size.wheel || s.robot.track !== size.track || s.robot.base !== size.base || s.robot.eyeAhead !== size.eyeAhead || s.robot.eyeAngle !== size.eyeAngle || (s.layout || "tank") !== layout)) {
        size = s.robot; layout = s.layout || "tank"; shapeRobot();
      }
      pose.x = s.pose.x; pose.z = -s.pose.y; pose.h = THREE.MathUtils.degToRad(s.pose.heading);
      if (!placed || Math.hypot(pose.x - shown.x, pose.z - shown.z) > 80) { // first view, or the map was cleared: jump there
        Object.assign(shown, pose); placed = true; snapCamera = true;
      }
      // obstacles
      const list = s.cells.slice(0, MAX);
      list.forEach(([i, j, v], n) => {
        const sure = Math.min(1, (v - 0.6) / 2.4);
        tmp.position.set(i * c, 0, -j * c); tmp.scale.set(c, 4 + sure * 6, c); tmp.updateMatrix();
        cells.setMatrixAt(n, tmp.matrix);
        cells.setColorAt(n, col.setRGB(0.55 - sure * 0.33, 0.6 - sure * 0.34, 0.63 - sure * 0.33));
      });
      cells.count = list.length; cells.instanceMatrix.needsUpdate = true; if (cells.instanceColor) cells.instanceColor.needsUpdate = true;
      // floor colours
      const fl = s.floor.slice(0, MAX);
      fl.forEach(([i, j, k], n) => {
        tmp.position.set(i * c, 0, -j * c); tmp.scale.set(c, 1, c); tmp.updateMatrix();
        tiles.setMatrixAt(n, tmp.matrix); tiles.setColorAt(n, col.setHex(FLOOR[k] ?? 0xb0b6b8));
      });
      tiles.count = fl.length; tiles.instanceMatrix.needsUpdate = true; if (tiles.instanceColor) tiles.instanceColor.needsUpdate = true;
      // trail
      const t = s.trail.slice(-3000);
      t.forEach(([x, y], n) => { trailPos[n * 3] = x; trailPos[n * 3 + 1] = 0.4; trailPos[n * 3 + 2] = -y; });
      trailGeo.setDrawRange(0, t.length); trailGeo.attributes.position.needsUpdate = true;
      // the eye's beam: red to what it hit, faint when nothing is in range
      const e = s.eye;
      beam.visible = dot.visible = !!e;
      if (e) {
        const a = THREE.MathUtils.degToRad(size.eyeAngle), wr = size.wheel / 20;
        const spread = e.kind === "us" ? 0.26 : 0.36; // half-angle of the beam, roughly
        beam.position.set(size.eyeAhead / 10, wr + 3, 0); beam.rotation.y = a;
        beam.scale.set(Math.max(1, e.dist), Math.max(1, e.dist * Math.tan(spread)), Math.max(1, e.dist * Math.tan(spread)));
        beamMat.color.setHex(e.hit ? 0xd1242f : 0x2f9e57); beamMat.opacity = e.hit ? 0.2 : 0.06;
        dot.visible = e.hit;
        dot.position.set(size.eyeAhead / 10 + Math.cos(a) * e.dist, wr + 3, -Math.sin(a) * e.dist);
      }
    },
  };
}
