// Showcase View: a presentation layout over the same live page. It reuses the same video, overlay,
// timeline and 3D canvas (so the recording and playback position survive a switch), and only adds:
//   - a summary beside the large video, from the same CSV statistics as the Engineering view;
//   - a magnified crop of the current frame around the marker, with the CSV corners drawn on it;
//   - read-only mirrors of the detection status and of the replay's source label and roll/pitch;
//   - a presentation look for the 3D scene (lights, shadows, tone mapping). Geometry, data,
//     axis mapping and timing are untouched, and the original look is restored in Engineering view.
import * as THREE from "three";
import { describeCamera, recordingGroup } from "./stats.js";

const $ = id => document.getElementById(id);
const VIEW_KEY = "smarttrim.view";
const esc = s => String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const fmt = v => (v === null || v === undefined ? "—" : v.toFixed(1));

export class Showcase {
  constructor({ detection, replay, stats, statsReady }) {
    this.detection = detection;
    this.replay = replay;
    this.stats = stats;
    this.statsReady = statsReady;
    this.view = "engineering";
    this.clipId = null;
  }

  init() {
    document.querySelectorAll(".viewswitch .vs").forEach(b => { b.onclick = () => this.setView(b.dataset.view); });
    this._mirrorDetection();
    this._mirrorReplay();
    let initial = new URLSearchParams(location.search).get("view");
    if (!initial) { try { initial = localStorage.getItem(VIEW_KEY); } catch { initial = null; } }
    this.setView(initial === "showcase" ? "showcase" : "engineering", { persist: false });
    this.statsReady.then(() => this.update(this.clipId ?? this.detection.clip?.id ?? this.stats.selected));
    window.addEventListener("resize", () => this.drawZoom());
  }

  setView(view, { persist = true } = {}) {
    const on = view === "showcase";
    this.view = on ? "showcase" : "engineering";
    document.body.classList.toggle("showcase", on);
    document.body.classList.remove("view-enter");
    void document.body.offsetWidth;                      // restart the short fade
    document.body.classList.add("view-enter");
    document.querySelectorAll(".viewswitch .vs").forEach(b => b.setAttribute("aria-pressed", String(b.dataset.view === this.view)));
    if (persist) { try { localStorage.setItem(VIEW_KEY, this.view); } catch { /* storage unavailable: fine */ } }
    this.apply3DLook(on);
    // Same elements, new sizes: let the overlay, the strip and the replay chart redraw.
    requestAnimationFrame(() => { window.dispatchEvent(new Event("resize")); this.drawZoom(); });
  }

  /** Summary for the selected recording (called when the recording changes). */
  update(id) {
    if (id) this.clipId = id;
    if (!this.stats.ready || !this.clipId) return;
    const clip = this.stats.clips.find(c => c.id === this.clipId);
    const s = this.stats.stats.get(this.clipId);
    $("sc-title").textContent = clip ? clip.label : "—";
    $("sc-camera").textContent = clip ? describeCamera(clip) : "";
    const rate = $("sc-rate");
    if (!clip || !s || s.error) {
      rate.innerHTML = `<div class="sc-big">—</div><div class="sc-big-label">statistics unavailable</div>`;
    } else if (s.hasInvalidSegment) {
      const ranges = s.invalidRanges.map(([a, b]) => `${a}–${b}`).join(", ");
      rate.innerHTML = `
        <div class="sc-big"><span data-sc="rate">${fmt(s.validRate)}</span><small>%</small></div>
        <div class="sc-big-label">marker ID ${clip.marker_id} detected in <b data-sc="detected">${s.validDetected}</b> of
          <b data-sc="frames">${s.validFrames}</b> valid frames (frames ${ranges} excluded: marker detached)</div>
        <div class="sc-big-sub">All ${s.analysedFrames} frames: <span data-sc="all-rate">${fmt(s.detectionRate)}</span> %
          (${s.detected} detections, including the detached-marker frames)</div>`;
    } else {
      rate.innerHTML = `
        <div class="sc-big"><span data-sc="rate">${fmt(s.detectionRate)}</span><small>%</small></div>
        <div class="sc-big-label">marker ID ${clip.marker_id} detected in <b data-sc="detected">${s.detected}</b> of
          <b data-sc="frames">${s.analysedFrames}</b> frames analysed · ${s.durationS.toFixed(1)} s of video</div>`;
    }
    this._renderChart();
    this.drawZoom();
  }

  /** Compact bench -> water chart. A recording with an invalid segment shows its valid-frames rate and says so. */
  _renderChart() {
    $("sc-chart").innerHTML = this.stats.clips.map((clip, i) => {
      const s = this.stats.stats.get(clip.id);
      if (!s || s.error) return "";
      const valid = s.hasInvalidSegment;
      const r = valid ? s.validRate : s.detectionRate;
      const n = valid ? s.validDetected : s.detected, d = valid ? s.validFrames : s.analysedFrames;
      return `<button class="sc-bar${clip.id === this.clipId ? " selected" : ""}" data-sc-clip="${esc(clip.id)}"
                data-sc-rate="${fmt(r)}" data-sc-detected="${n}" data-sc-frames="${d}"
                title="${esc(clip.label)}: ${n} of ${d} ${valid ? "valid " : ""}frames${valid ? ` (all frames: ${fmt(s.detectionRate)} %)` : ""}">
          <span class="sc-bar-no">${i + 1}</span>
          <span class="sc-bar-name">${esc(recordingGroup(clip))}${valid ? ' <em>valid frames</em>' : ""}</span>
          <span class="sc-bar-track"><span class="sc-bar-fill" style="width:${(r ?? 0).toFixed(2)}%"></span></span>
          <span class="sc-bar-value">${fmt(r)}<small>%</small></span>
        </button>`;
    }).join("");
    document.querySelectorAll("#sc-chart .sc-bar").forEach(b => { b.onclick = () => this.detection.loadClip(b.dataset.scClip); });
  }

  // --- read-only mirrors -------------------------------------------------------------------
  _observe(el, fn) {
    if (!el) return;
    new MutationObserver(fn).observe(el, { childList: true, characterData: true, subtree: true, attributes: true,
                                           attributeFilter: ["class", "hidden"] });
    fn();
  }

  _mirrorDetection() {
    this._observe($("detection-status"), () => {
      const src = $("detection-status");
      $("sc-indicator-text").textContent = src.textContent;
      $("sc-indicator").className = "sc-indicator " + [...src.classList].filter(c => c !== "status-chip").join(" ");
    });
    this._observe($("segment-status"), () => { $("sc-invalid").hidden = $("segment-status").hidden; });
    this._observe($("frame-line"), () => { $("sc-frame").textContent = $("frame-line").textContent; this.drawZoom(); });
    this._observe($("jump-caption"), () => {
      const src = $("jump-caption");
      $("sc-caption").textContent = src.textContent;
      $("sc-caption").hidden = src.hidden || !src.textContent;
    });
  }

  _mirrorReplay() {
    this._observe($("rec-source-badge"), () => {
      const src = $("rec-source-badge");
      const kind = src.classList.contains("badge-sim") ? "sim" : src.classList.contains("badge-measured") ? "measured" : "unknown";
      $("sc-rep-source").textContent = src.textContent || "—";
      $("sc-rep-source").className = `sc-source sc-source-${kind}`;
    });
    this._observe($("rec-select"), () => { $("sc-rep-rec").textContent = $("rec-select").value || ""; });
    for (const [from, to] of [["ro-roll", "sc-roll"], ["ro-pitch", "sc-pitch"], ["ro-rtime", "sc-rtime"]]) {
      this._observe($(from), () => { $(to).textContent = $(from).textContent; });
    }
  }

  // --- marker close-up -----------------------------------------------------------------------
  /** Magnified crop of the frame on screen around the marker, with the CSV corners. Nothing is drawn without a detection. */
  drawZoom() {
    if (this.view !== "showcase") return;
    const canvas = $("sc-zoom"), d = this.detection, video = d.video;
    const box = canvas.getBoundingClientRect();
    if (!box.width) return;
    const dpr = window.devicePixelRatio || 1;
    canvas.width = Math.round(box.width * dpr);
    canvas.height = Math.round(box.height * dpr);
    const ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const W = box.width, H = box.height;
    ctx.fillStyle = "#060c15";
    ctx.fillRect(0, 0, W, H);
    const k = d.state.frame, row = k === null ? null : d.rows.get(k);
    const label = $("sc-zoom-label");
    if (!d.state.overlayEnabled || !row || !row.detected || !video.videoWidth) {
      ctx.fillStyle = "#62778e";
      ctx.font = "600 14px Segoe UI, sans-serif";
      ctx.textAlign = "center";
      ctx.fillText(row ? "No marker detected in this frame" : "No detection data", W / 2, H / 2);
      ctx.textAlign = "start";
      label.textContent = "Marker close-up";
      this.zoomDrawn = false;
      return;
    }
    const xs = row.corners.map(c => c[0]), ys = row.corners.map(c => c[1]);
    const side = Math.max(Math.max(...xs) - Math.min(...xs), Math.max(...ys) - Math.min(...ys));
    const span = Math.min(Math.max(side * 2.8, 90), video.videoWidth, video.videoHeight);
    const cx = xs.reduce((a, b) => a + b) / 4, cy = ys.reduce((a, b) => a + b) / 4;
    const sx = Math.min(Math.max(cx - span / 2, 0), video.videoWidth - span);
    const sy = Math.min(Math.max(cy - span / 2, 0), video.videoHeight - span);
    ctx.imageSmoothingQuality = "high";
    ctx.drawImage(video, sx, sy, span, span, 0, 0, W, H);
    const s = W / span;
    const pts = row.corners.map(([x, y]) => [(x - sx) * s, (y - sy) * s]);
    const invalid = d.segmentAt(k);
    ctx.lineWidth = 3;
    ctx.strokeStyle = invalid ? "#e74c3c" : "#2ecc71";
    ctx.setLineDash(invalid ? [10, 7] : []);
    ctx.beginPath();
    pts.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)));
    ctx.closePath();
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.font = "bold 15px Segoe UI, sans-serif";
    pts.forEach(([x, y], i) => {
      ctx.fillStyle = "#e74c3c"; ctx.beginPath(); ctx.arc(x, y, 5, 0, 2 * Math.PI); ctx.fill();
      ctx.fillStyle = "#ffffff"; ctx.fillText(String(i), Math.min(Math.max(x + 7, 2), W - 12), Math.min(Math.max(y - 7, 14), H - 4));
    });
    // Magnification relative to the main video on screen.
    const stage = $("video-stage").getBoundingClientRect();
    const mainScale = Math.min(stage.width / video.videoWidth, stage.height / video.videoHeight);
    label.textContent = `Marker close-up · ×${(s / mainScale).toFixed(1)} of the main view · this frame`;
    this.zoomDrawn = true;
  }

  // --- 3D presentation look ------------------------------------------------------------------
  _build3D() {
    const r = this.replay;
    const group = new THREE.Group();
    const key = new THREE.DirectionalLight(0xfff4e6, 2.4);
    key.position.set(-180, 340, 240);
    key.castShadow = true;
    key.shadow.mapSize.set(2048, 2048);
    Object.assign(key.shadow.camera, { left: -260, right: 260, top: 260, bottom: -260, near: 50, far: 1200 });
    key.shadow.bias = -0.0005;
    key.shadow.radius = 4;
    const rim = new THREE.DirectionalLight(0x6fb6ff, 1.8);
    rim.position.set(160, 120, -340);
    const fill = new THREE.DirectionalLight(0xbfd4ff, 0.55);
    fill.position.set(320, 60, 160);
    group.add(key, key.target, rim, fill);
    const ground = new THREE.Mesh(new THREE.PlaneGeometry(1400, 1400), new THREE.ShadowMaterial({ opacity: 0.38 }));
    ground.rotation.x = -Math.PI / 2;
    ground.position.y = 0.2;                       // keel level, under the existing reference grid
    ground.receiveShadow = true;
    group.add(ground);
    const c = document.createElement("canvas");
    c.width = 2; c.height = 256;
    const g = c.getContext("2d"), grad = g.createLinearGradient(0, 0, 0, 256);
    grad.addColorStop(0, "#14273f"); grad.addColorStop(0.55, "#0b1626"); grad.addColorStop(1, "#05090f");
    g.fillStyle = grad; g.fillRect(0, 0, 2, 256);
    const background = new THREE.CanvasTexture(c);
    background.colorSpace = THREE.SRGBColorSpace;
    this._3d = { group, background, fog: new THREE.Fog(0x0b1626, 520, 1500), saved: null };
  }

  _setShadows(on) {
    this.replay.model?.traverse(o => { if (o.isMesh) { o.castShadow = on; o.receiveShadow = false; } });
  }

  apply3DLook(on) {
    const r = this.replay;
    if (!r?.renderer) return;
    if (!this._3d) this._build3D();
    const t = this._3d;
    if (on && !t.saved) {
      t.saved = { background: r.scene.background, fog: r.scene.fog, toneMapping: r.renderer.toneMapping,
                  exposure: r.renderer.toneMappingExposure, metalness: r.liveMaterial.metalness,
                  roughness: r.liveMaterial.roughness, camera: r.camera.position.clone(), target: r.controls.target.clone() };
      r.scene.add(t.group);
      r.scene.background = t.background;
      r.scene.fog = t.fog;
      r.renderer.toneMapping = THREE.ACESFilmicToneMapping;
      r.renderer.toneMappingExposure = 1.05;
      r.renderer.shadowMap.enabled = true;
      r.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
      r.liveMaterial.metalness = 0.28;             // finish only: colour and geometry unchanged
      r.liveMaterial.roughness = 0.42;
      this._setShadows(true);
      r.camera.position.set(245, 135, 290);         // a slightly lower, wider framing for the 16:9 stage
      r.controls.update();
    } else if (!on && t.saved) {
      const s = t.saved;
      r.scene.remove(t.group);
      r.scene.background = s.background;
      r.scene.fog = s.fog;
      r.renderer.toneMapping = s.toneMapping;
      r.renderer.toneMappingExposure = s.exposure;
      r.renderer.shadowMap.enabled = false;
      r.liveMaterial.metalness = s.metalness;
      r.liveMaterial.roughness = s.roughness;
      this._setShadows(false);
      r.camera.position.copy(s.camera);
      r.controls.target.copy(s.target);
      r.controls.update();
      t.saved = null;
    } else {
      return;
    }
    r.scene.traverse(o => { const m = o.material; if (m) (Array.isArray(m) ? m : [m]).forEach(x => { x.needsUpdate = true; }); });
    r.liveMaterial.needsUpdate = true;
    r.ghostMaterial.needsUpdate = true;
  }

  /** Called once the replay has loaded its model, so the model can cast the showcase shadow. */
  refresh3D() {
    if (this.view === "showcase") {
      this._setShadows(true);
      this.replay.liveMaterial.needsUpdate = true;
    }
  }
}
