// Tab 2: 3D Motion Replay of roll and pitch from a SmartTrim sensor CSV.
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { STLLoader } from "three/addons/loaders/STLLoader.js";

import { applyAttitude, orientationCheck } from "./attitude.js";
import { parseSensorCsv, sampleAt } from "./data.js";

const $ = id => document.getElementById(id);
const PIVOT_MM = 40;   // display pivot: midship, 40 mm above the keel (visual only)
const SAMPLE_URL = "samples/simulated_motion_sample.csv";

export class MotionReplay {
  constructor(manifest) {
    this.manifest = manifest;
    this.recordings = [];
    this.recording = null;
    this.t = 0;
    this.playing = false;
    this.state = { ready: false, modelKind: null, sample: null, check: [], recordingKey: null };
    this._buildScene();
    this._bind();
  }

  _buildScene() {
    const stage = $("three-stage");
    this.renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true });
    this.renderer.setPixelRatio(window.devicePixelRatio || 1);
    stage.appendChild(this.renderer.domElement);
    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0x0a1420);
    this.camera = new THREE.PerspectiveCamera(40, 1, 1, 5000);
    this.camera.position.set(230, 170, 260);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.target.set(0, PIVOT_MM, 0);
    this.controls.update();
    this.scene.add(new THREE.HemisphereLight(0xdde8ff, 0x223344, 1.1));
    const sun = new THREE.DirectionalLight(0xffffff, 1.4);
    sun.position.set(200, 400, 250);
    this.scene.add(sun);
    // Fixed reference grid at keel level (not a waterline: no draft is shown here).
    const grid = new THREE.GridHelper(400, 16, 0x35506e, 0x1d2e42);
    this.scene.add(grid);
    // Fixed world axes for orientation (X bow, Y up, Z starboard).
    const origin = new THREE.Vector3(-120, 0, 120);
    [[1, 0, 0, 0xff6b6b], [0, 1, 0, 0x7ee081], [0, 0, 1, 0x6fa8ff]].forEach(([x, y, z, c]) =>
      this.scene.add(new THREE.ArrowHelper(new THREE.Vector3(x, y, z), origin, 60, c, 12, 7)));

    this.boat = new THREE.Group();                 // attitude group, rotates about the pivot
    this.boat.position.set(0, PIVOT_MM, 0);
    this.scene.add(this.boat);
    this.model = new THREE.Group();                // model in boat coordinates, keel at y = 0
    this.model.position.set(0, -PIVOT_MM, 0);
    this.boat.add(this.model);
    // Bow arrow above the deck; it moves with the boat so pitch and roll are easy to read.
    this.bowArrow = new THREE.ArrowHelper(new THREE.Vector3(1, 0, 0),
      new THREE.Vector3(-40, 115 - PIVOT_MM, 0), 150, 0xff9f1a, 26, 14);
    this.boat.add(this.bowArrow);
    this.liveMaterial = new THREE.MeshStandardMaterial({ color: 0x2f7fd6, metalness: 0.1, roughness: 0.55 });
    this.ghostMaterial = new THREE.MeshBasicMaterial({ color: 0x8592a3, wireframe: true, transparent: true, opacity: 0.35 });
    this._resize();
    new ResizeObserver(() => this._resize()).observe(stage);
    const loop = now => { this._tick(now); this.renderer.render(this.scene, this.camera); requestAnimationFrame(loop); };
    requestAnimationFrame(loop);
  }

  _resize() {
    const stage = $("three-stage");
    const w = stage.clientWidth || 800, h = stage.clientHeight || 500;
    this.renderer.setSize(w, h);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
  }

  async _loadModel() {
    const mesh = this.manifest?.cad_mesh;
    if (mesh) {
      try {
        const geometry = await new STLLoader().loadAsync("media/" + mesh.path);
        geometry.rotateX(-Math.PI / 2);            // CAD (x bow, z up) -> display (X bow, Y up)
        geometry.computeVertexNormals();
        this.model.add(new THREE.Mesh(geometry, this.liveMaterial));
        this.state.modelKind = "cad";
        $("model-badge").textContent = mesh.label;
        $("model-badge").className = "badge badge-real";
        return;
      } catch (err) {
        console.warn("CAD mesh could not be loaded; using the schematic", err);
      }
    }
    // Simplified V5 schematic from the nominal dimensions (not CAD geometry).
    const box = (w, h, d, x, y, z) => {
      const m = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), this.liveMaterial);
      m.position.set(x, y, z);
      this.model.add(m);
    };
    for (const z of [-60, 60]) box(200, 65, 48, 0, 32.5, z);          // pontoons 200 x 48 x 65
    for (const x of [-54, 54]) box(18, 12, 156, x, 79.4, 0);          // struts at x = +/-54
    box(130, 3, 66, 0, 86.9, 0);                                       // cargo deck
    box(40, 30, 1, 98, 32.5, -60); box(40, 30, 1, 98, 32.5, 60);       // bow marks (orientation cue)
    this.state.modelKind = "schematic";
    $("model-badge").textContent = "V5 schematic (simplified, not CAD)";
    $("model-badge").className = "badge badge-unknown";
  }

  _bind() {
    $("rep-play").onclick = () => this.setPlaying(!this.playing);
    $("rep-speed").onchange = e => { this.speed = Number(e.target.value); };
    this.speed = 1;
    $("rep-slider").oninput = e => { this.setPlaying(false); this.setTime(Number(e.target.value)); };
    $("rep-chart").onclick = e => {
      if (!this.recording) return;
      const box = e.target.getBoundingClientRect();
      this.setPlaying(false);
      this.setTime(((e.clientX - box.left) / box.width) * this.recording.duration);
    };
    $("rec-select").onchange = e => this.selectRecording(e.target.value);
    $("rec-file").onchange = async e => {
      const file = e.target.files[0];
      if (file) this.loadCsvText(await file.text(), file.name);
    };
    window.addEventListener("resize", () => this._drawChart());
  }

  async init() {
    await this._loadModel();
    this.state.check = orientationCheck(this.boat);
    const list = $("orientation-check").querySelector("ul");
    list.innerHTML = this.state.check.map(c => `<li class="${c.pass ? "pass" : "fail"}">${c.name}</li>`).join("");
    const text = await fetch(SAMPLE_URL).then(r => (r.ok ? r.text() : ""));
    if (text) this.loadCsvText(text, "simulated_motion_sample.csv");
    this.state.ready = true;
  }

  loadCsvText(text, name) {
    const { recordings, problems } = parseSensorCsv(text);
    if (problems.length) {
      this._status(`Could not load ${name}: ${problems.join("; ")}`, "bad");
      return;
    }
    this.recordings = recordings;
    this.fileName = name;
    $("rec-select").innerHTML = recordings.map(r => `<option value="${r.key}">${r.key}</option>`).join("");
    this.selectRecording(recordings[0].key);
  }

  selectRecording(key) {
    this.recording = this.recordings.find(r => r.key === key);
    this.state.recordingKey = key;
    const r = this.recording;
    const badge = $("rec-source-badge");
    if (r.source === "simulated") {
      badge.textContent = "Simulated data";
      badge.className = "badge badge-sim";
    } else if (r.measured) {
      badge.textContent = "Recorded MPU6050 data";      // source arduino_mpu6050 (MEASURED_SOURCES)
      badge.className = "badge badge-measured";
    } else {
      badge.textContent = `Source: ${r.source} — not confirmed as measured`;
      badge.className = "badge badge-unknown";
    }
    $("rec-notes").textContent = [r.notes, `File: ${this.fileName}`].filter(Boolean).join(" · ");
    $("ro-samples").textContent = `${r.rows.length} · ~${r.medianDt ? (1 / r.medianDt).toFixed(0) : "?"} Hz`;
    const slider = $("rep-slider");
    slider.max = String(r.duration);
    this.setPlaying(false);
    this.setTime(0);
  }

  setPlaying(on) {
    this.playing = on && !!this.recording;
    if (this.playing && this.t >= this.recording.duration) this.t = 0;
    this._last = null;
    $("rep-play").textContent = this.playing ? "❚❚ Pause" : "▶ Play";
  }

  _tick(now) {
    if (!this.playing || !this.recording) return;
    if (this._last !== null) {
      const t = this.t + ((now - this._last) / 1000) * this.speed;
      if (t >= this.recording.duration) { this.setTime(this.recording.duration); this.setPlaying(false); }
      else this.setTime(t);
    }
    this._last = now;
  }

  setTime(t) {
    if (!this.recording) return;
    this.t = Math.min(Math.max(0, t), this.recording.duration);
    const sample = sampleAt(this.recording, this.t);
    this.state.sample = sample;
    $("rep-slider").value = String(this.t);
    $("ro-rtime").textContent = `${this.t.toFixed(2)} / ${this.recording.duration.toFixed(2)} s`;
    const live = sample !== null && sample.pitch !== null;
    $("ro-roll").textContent = sample ? `${sample.roll >= 0 ? "+" : ""}${sample.roll.toFixed(2)}°` : "—";
    $("ro-pitch").textContent = sample && sample.pitch !== null
      ? `${sample.pitch >= 0 ? "+" : ""}${sample.pitch.toFixed(2)}°` : "—";
    $("no-sample-banner").hidden = live;
    this.bowArrow.visible = live;
    if (live) {
      applyAttitude(this.boat, sample.roll, sample.pitch);
      this._setMaterial(this.liveMaterial);
      this._status(this.recording.source === "simulated" ? "Simulated sample" : "Sensor sample", "ok");
    } else {
      applyAttitude(this.boat, 0, 0);               // ghost outline only; no attitude is claimed
      this._setMaterial(this.ghostMaterial);
      this._status(sample ? "Pitch missing in this sample" : "No sample (gap in the recording)", "nodata");
    }
    this._drawChart();
  }

  _setMaterial(material) {
    this.model.traverse(o => { if (o.isMesh) o.material = material; });
  }

  _status(text, kind) {
    const chip = $("replay-status");
    chip.textContent = text;
    chip.className = `status-chip ${kind}`;
  }

  _drawChart() {
    const canvas = $("rep-chart");
    const r = this.recording;
    if (!r) return;
    const box = canvas.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    canvas.width = Math.round(box.width * dpr);
    canvas.height = Math.round(box.height * dpr);
    const ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const W = box.width, H = box.height, pad = 6;
    const maxAbs = Math.max(1, ...r.rows.flatMap(s => [Math.abs(s.roll), Math.abs(s.pitch ?? 0)])) * 1.15;
    const x = t => (r.duration ? (t / r.duration) * W : 0);
    const y = v => H / 2 - (v / maxAbs) * (H / 2 - pad);
    ctx.clearRect(0, 0, W, H);
    ctx.strokeStyle = "#22344a"; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(0, H / 2); ctx.lineTo(W, H / 2); ctx.stroke();
    const limit = 1.5 * (r.medianDt || 0);
    // Gaps: shaded, and lines are not joined across them.
    ctx.fillStyle = "rgba(93,109,126,0.25)";
    r.rows.forEach((s, i) => {
      if (i && s.t - r.rows[i - 1].t > limit + 1e-9) ctx.fillRect(x(r.rows[i - 1].t), 0, x(s.t) - x(r.rows[i - 1].t), H);
    });
    for (const [key, colour] of [["roll", "#f39c12"], ["pitch", "#48c9e4"]]) {
      ctx.strokeStyle = colour; ctx.lineWidth = 1.6; ctx.beginPath();
      let pen = false;
      r.rows.forEach((s, i) => {
        const v = s[key];
        const joined = i && s.t - r.rows[i - 1].t <= limit + 1e-9;
        if (v === null) { pen = false; return; }
        if (pen && joined) ctx.lineTo(x(s.t), y(v)); else ctx.moveTo(x(s.t), y(v));
        pen = true;
      });
      ctx.stroke();
    }
    ctx.fillStyle = "#93a7bd"; ctx.font = "11px Segoe UI, sans-serif";
    ctx.fillText(`±${maxAbs.toFixed(1)}°  roll`, 6, 12);
    ctx.fillStyle = "#48c9e4"; ctx.fillText("pitch", 74, 12);
    ctx.strokeStyle = "#ffffff"; ctx.lineWidth = 1.5;
    ctx.beginPath(); ctx.moveTo(x(this.t), 0); ctx.lineTo(x(this.t), H); ctx.stroke();
  }
}
