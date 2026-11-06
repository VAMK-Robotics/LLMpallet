// 3D preview. The scene uses the robot workobject coordinates directly (mm, Z up):
// origin = pallet corner on the top deck, +X along 1200 mm, +Y along 800 mm.
import * as THREE from "three";
import { OrbitControls } from "three/addons/OrbitControls.js";
import { CSS2DRenderer, CSS2DObject } from "three/addons/CSS2DRenderer.js";

THREE.Object3D.DEFAULT_UP.set(0, 0, 1);

export const ROTATION_COLORS = { "0": 0xd9a066, "90": 0x7fa7d9, "180": 0x8cc084, "-90": 0xc49bd6 };

export class Preview3D {
  constructor(container, { onSelectLayer, tooltip }) {
    this.container = container;
    this.onSelectLayer = onSelectLayer;
    this.tooltip = tooltip;
    this.activeLayer = 0;
    this.showNumbers = true;
    this.fadeOthers = true;
    this.pallet = { length_x: 1200, width_y: 800, height: 144 };
    this.layout = null;
    this.boxMeshes = [];

    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    this.renderer.setPixelRatio(window.devicePixelRatio);
    container.appendChild(this.renderer.domElement);

    this.labelRenderer = new CSS2DRenderer();
    Object.assign(this.labelRenderer.domElement.style, { position: "absolute", top: "0", left: "0", pointerEvents: "none" });
    container.appendChild(this.labelRenderer.domElement);

    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(40, 1, 10, 100000);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.addEventListener("change", () => this.render());

    this.scene.add(new THREE.HemisphereLight(0xffffff, 0x666666, 1.6));
    const sun = new THREE.DirectionalLight(0xffffff, 1.4);
    sun.position.set(-1500, -2000, 3000);
    this.scene.add(sun);

    this.staticGroup = new THREE.Group();
    this.dynamicGroup = new THREE.Group();
    this.scene.add(this.staticGroup, this.dynamicGroup);

    this.materials = {};
    for (const [rot, color] of Object.entries(ROTATION_COLORS)) {
      this.materials[rot] = {
        active: new THREE.MeshStandardMaterial({ color, roughness: 0.85 }),
        faded: new THREE.MeshStandardMaterial({ color, roughness: 0.85, transparent: true, opacity: 0.22, depthWrite: false }),
        dim: new THREE.MeshStandardMaterial({ color, roughness: 0.85 }),
        ghost: new THREE.MeshStandardMaterial({ color, roughness: 0.85, transparent: true, opacity: 0.07, depthWrite: false }),
      };
      this.materials[rot].dim.color.multiplyScalar(0.75);
    }
    this.edgeMat = new THREE.LineBasicMaterial({ color: 0x333333 });
    this.edgeMatActive = new THREE.LineBasicMaterial({ color: 0x1d4ed8 });
    this.edgeMatFaded = new THREE.LineBasicMaterial({ color: 0x555555, transparent: true, opacity: 0.25 });
    this.markerMat = new THREE.MeshBasicMaterial({ color: 0xdc2626 });
    this.arrowMat = new THREE.MeshBasicMaterial({ color: 0x1f2937, side: THREE.DoubleSide });
    this.interlayerMat = new THREE.MeshStandardMaterial({ color: 0xa0784f, roughness: 1, transparent: true, opacity: 0.45, depthWrite: false });
    this.interlayerGhostMat = new THREE.MeshStandardMaterial({ color: 0xa0784f, roughness: 1, transparent: true, opacity: 0.06, depthWrite: false });

    this.raycaster = new THREE.Raycaster();
    this.pointer = new THREE.Vector2();
    this._bindPointer();

    new ResizeObserver(() => this.resize()).observe(container);
    this.resize();
  }

  // ---------------------------------------------------------------- static scene
  setPallet(pallet) {
    this.pallet = pallet;
    this.staticGroup.clear();
    const { length_x: L, width_y: W, height: H } = pallet;
    const wood = new THREE.MeshStandardMaterial({ color: 0xb08955, roughness: 1 });
    const addBox = (x0, y0, z0, sx, sy, sz) => {
      const m = new THREE.Mesh(new THREE.BoxGeometry(sx, sy, sz), wood);
      m.position.set(x0 + sx / 2, y0 + sy / 2, z0 + sz / 2);
      this.staticGroup.add(m);
      const e = new THREE.LineSegments(new THREE.EdgesGeometry(m.geometry), new THREE.LineBasicMaterial({ color: 0x6b4f2a }));
      e.position.copy(m.position);
      this.staticGroup.add(e);
    };
    // EUR pallet (simplified): top boards along X, cross boards, 9 blocks, bottom boards along X
    const tb = 22, cb = 22, blk = H - 2 * tb - cb, bb = tb;
    const topBoards = [[0, 145], [W * 0.25 - 50 + 22, 100], [W / 2 - 72.5, 145], [W * 0.75 - 50 - 22, 100], [W - 145, 145]];
    for (const [y, w] of topBoards) addBox(0, y, -tb, L, w, tb);
    const xs = [0, L / 2 - 72.5, L - 145];
    for (const x of xs) addBox(x, 0, -tb - cb, 145, W, cb);
    const ys = [[0, 100], [W / 2 - 72.5, 145], [W - 100, 100]];
    for (const x of xs) for (const [y, w] of ys) addBox(x, y, -tb - cb - blk, 145, w, blk);
    for (const [y, w] of ys) addBox(0, y, -H, L, w, bb);

    const grid = new THREE.GridHelper(4000, 40, 0x888888, 0xbbbbbb);
    grid.rotation.x = Math.PI / 2;
    grid.position.set(L / 2, W / 2, -H - 0.5);
    grid.material.transparent = true;
    grid.material.opacity = 0.35;
    this.staticGroup.add(grid);

    // workobject axes at origin
    const axes = [[new THREE.Vector3(1, 0, 0), 0xdc2626, "X"], [new THREE.Vector3(0, 1, 0), 0x16a34a, "Y"], [new THREE.Vector3(0, 0, 1), 0x2563eb, "Z"]];
    for (const [dir, color, name] of axes) {
      const arrow = new THREE.ArrowHelper(dir, new THREE.Vector3(0, 0, 0.5), 300, color, 50, 25);
      // always draw the workobject axes on top, so boxes never hide them
      arrow.traverse(o => { if (o.material) { o.material.depthTest = false; o.renderOrder = 999; } });
      this.staticGroup.add(arrow);
      const div = document.createElement("div");
      div.className = "axis-label";
      div.style.color = "#" + color.toString(16).padStart(6, "0");
      div.textContent = name;
      const label = new CSS2DObject(div);
      label.position.copy(dir.clone().multiplyScalar(340));
      this.staticGroup.add(label);
    }
    this.setView("iso");
  }

  // ---------------------------------------------------------------- dynamic scene
  setLayout(layout, params) {
    this.layout = layout;
    this.params = params;
    for (const obj of this.dynamicGroup.children) {
      if (obj.geometry) obj.geometry.dispose();
    }
    this.dynamicGroup.clear();
    this.boxMeshes = [];
    const H = params.box_height;
    const geoCache = new Map();
    const getGeo = (sx, sy) => {
      const k = `${sx}x${sy}`;
      if (!geoCache.has(k)) {
        const g = new THREE.BoxGeometry(Math.max(sx - 0.6, 0.1), Math.max(sy - 0.6, 0.1), Math.max(H - 0.6, 0.1));
        geoCache.set(k, { box: g, edges: new THREE.EdgesGeometry(g) });
      }
      return geoCache.get(k);
    };
    const markerGeo = new THREE.SphereGeometry(6, 12, 8);

    for (const p of layout.placements) {
      const g = getGeo(p.size_x, p.size_y);
      const mesh = new THREE.Mesh(g.box, this.materials[String(p.rotation)].active);
      mesh.position.set(p.x, p.y, p.z - H / 2);
      mesh.userData = p;
      const edges = new THREE.LineSegments(g.edges, this.edgeMat);
      edges.position.copy(mesh.position);
      const marker = new THREE.Mesh(markerGeo, this.markerMat);
      marker.position.set(p.x, p.y, p.z + 1);
      // arrow on the top face showing the direction of the box +X axis (rotation)
      const len = Math.min(p.size_x, p.size_y) * 0.35;
      const shape = new THREE.Shape();
      shape.moveTo(len, 0); shape.lineTo(len * 0.35, len * 0.3); shape.lineTo(len * 0.35, -len * 0.3); shape.closePath();
      const arrow = new THREE.Mesh(new THREE.ShapeGeometry(shape), this.arrowMat);
      arrow.position.set(p.x, p.y, p.z + 0.8);
      arrow.rotation.z = THREE.MathUtils.degToRad(p.rotation);

      const div = document.createElement("div");
      div.className = "box-label";
      div.textContent = p.index;
      const label = new CSS2DObject(div);
      label.position.set(p.x, p.y, p.z + 15);

      this.dynamicGroup.add(mesh, edges, marker, arrow, label);
      this.boxMeshes.push({ mesh, edges, marker, arrow, label, p });
    }

    const t = params.interlayer_thickness;
    this.interlayerMeshes = [];
    if (t > 0) {
      const g = new THREE.BoxGeometry(this.pallet.length_x, this.pallet.width_y, t);
      for (const z of layout.interlayers) {
        const m = new THREE.Mesh(g, this.interlayerMat);
        m.position.set(this.pallet.length_x / 2, this.pallet.width_y / 2, z + t / 2);
        m.userData = { interlayer: true, z };
        this.dynamicGroup.add(m);
        this.interlayerMeshes.push(m);
      }
    }

    // usable area outline
    const u = layout.usable_area;
    if (u && u.x_max > u.x_min) {
      const pts = [[u.x_min, u.y_min], [u.x_max, u.y_min], [u.x_max, u.y_max], [u.x_min, u.y_max], [u.x_min, u.y_min]]
        .map(([x, y]) => new THREE.Vector3(x, y, 0.5));
      const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts),
        new THREE.LineDashedMaterial({ color: 0xdc2626, dashSize: 20, gapSize: 12 }));
      line.computeLineDistances();
      this.dynamicGroup.add(line);
    }
    this.setActiveLayer(this.activeLayer);
  }

  setActiveLayer(layer) {
    this.activeLayer = layer;
    for (const b of this.boxMeshes) {
      const mats = this.materials[String(b.p.rotation)];
      const isActive = b.p.layer === layer;
      const above = b.p.layer > layer;
      // layers above the active one are ghosted so the active layer stays visible from the top
      let mat = isActive ? mats.active : above ? mats.ghost : (this.fadeOthers ? mats.faded : mats.dim);
      if (!this.fadeOthers && above) mat = mats.faded;
      b.mesh.material = mat;
      b.edges.material = isActive ? this.edgeMatActive : (mat.transparent ? this.edgeMatFaded : this.edgeMat);
      b.edges.visible = !(mat === mats.ghost);
      b.marker.visible = isActive || !mat.transparent;
      b.arrow.visible = isActive;
      b.label.visible = isActive && this.showNumbers;
    }
    const activeInfo = this.layout && this.layout.layers[layer];
    for (const m of this.interlayerMeshes || []) {
      m.material = activeInfo && m.userData.z >= activeInfo.z_top - 1e-6 ? this.interlayerGhostMat : this.interlayerMat;
    }
    this.render();
  }

  setOptions({ showNumbers, fadeOthers }) {
    if (showNumbers !== undefined) this.showNumbers = showNumbers;
    if (fadeOthers !== undefined) this.fadeOthers = fadeOthers;
    this.setActiveLayer(this.activeLayer);
  }

  setView(name) {
    const { length_x: L, width_y: W } = this.pallet;
    const h = this.layout ? this.layout.stack_height : 0;
    const target = new THREE.Vector3(L / 2, W / 2, h / 2);
    const d = Math.max(L, W, h) * 1.9 + 600;
    if (name === "top") {
      // X up on the screen, Y to the left -> origin in the bottom-right corner
      this.camera.position.set(target.x - 0.01 * d, target.y, target.z + d * 1.1);
    } else if (name === "front") {
      this.camera.position.set(target.x, target.y - d * 1.2, target.z);
    } else {
      // isometric view from the robot side (origin corner)
      this.camera.position.set(target.x - d * 0.8, target.y - d * 0.75, target.z + d * 0.65);
    }
    this.controls.target.copy(target);
    this.camera.lookAt(target);
    this.controls.update();
    this.render();
  }

  // ---------------------------------------------------------------- interaction
  _bindPointer() {
    const el = this.renderer.domElement;
    let down = null;
    el.addEventListener("pointerdown", e => { down = { x: e.clientX, y: e.clientY, button: e.button }; });
    el.addEventListener("pointerup", e => {
      if (down && down.button === 0 && Math.hypot(e.clientX - down.x, e.clientY - down.y) < 5) {
        const hit = this._pick(e);
        if (hit) this.onSelectLayer(hit.layer);
      }
      down = null;
    });
    el.addEventListener("pointermove", e => {
      if (e.buttons) { this.tooltip.hidden = true; return; }
      const hit = this._pick(e);
      if (!hit) { this.tooltip.hidden = true; return; }
      const rect = this.container.getBoundingClientRect();
      this.tooltip.hidden = false;
      this.tooltip.textContent =
        `Box #${hit.index}  (layer ${hit.layer + 1})\nX ${hit.x.toFixed(1)}  Y ${hit.y.toFixed(1)}  Z ${hit.z.toFixed(1)}\nR ${hit.rotation}°`;
      this.tooltip.style.left = `${e.clientX - rect.left + 14}px`;
      this.tooltip.style.top = `${e.clientY - rect.top + 14}px`;
    });
    el.addEventListener("pointerleave", () => { this.tooltip.hidden = true; });
  }

  _pick(e) {
    const rect = this.renderer.domElement.getBoundingClientRect();
    this.pointer.set(((e.clientX - rect.left) / rect.width) * 2 - 1, -((e.clientY - rect.top) / rect.height) * 2 + 1);
    this.raycaster.setFromCamera(this.pointer, this.camera);
    const meshes = this.boxMeshes.map(b => b.mesh);
    const hits = this.raycaster.intersectObjects(meshes, false);
    if (!hits.length) return null;
    // prefer the first opaque box, so faded boxes don't steal clicks from the active layer
    const opaque = hits.find(h => !h.object.material.transparent);
    return (opaque || hits[0]).object.userData;
  }

  resize() {
    const w = this.container.clientWidth || 1, h = this.container.clientHeight || 1;
    this.renderer.setSize(w, h);
    this.labelRenderer.setSize(w, h);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
    this.render();
  }

  render() {
    this.renderer.render(this.scene, this.camera);
    this.labelRenderer.render(this.scene, this.camera);
  }
}
