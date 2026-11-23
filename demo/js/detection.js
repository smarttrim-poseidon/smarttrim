// Tab 1: ArUco Detection Review. Shows only what the detection CSV recorded:
// marker outline and corners on detected frames, a status on every frame, and any
// labelled invalid segments (e.g. marker detached) even where the marker is detected.
import { lastIndexAtOrBefore, parseDetectionCsv } from "./data.js";

const $ = id => document.getElementById(id);
const COLOURS = { detected: "#2ecc71", missed: "#56657a", nodata: "#1c2633", playhead: "#ffffff",
                  invalidDetected: "#e74c3c", invalidMissed: "#6e2c2c" };

function clock(seconds) {
  const m = Math.floor(seconds / 60), s = seconds - 60 * m;
  return `${String(m).padStart(2, "0")}:${s.toFixed(1).padStart(4, "0")}`;
}

export class DetectionReview {
  constructor(manifest) {
    this.manifest = manifest;
    this.video = $("video");
    this.overlay = $("overlay");
    this.state = { ready: false, frame: null, mediaTime: null, overlayDrawn: false, status: "",
                   overlayEnabled: false, error: null, segment: null, range: null };
    this.clip = null;
    this.pts = [];
    this.rows = new Map();
    this.segments = [];
    this.range = { first: 0, last: 0, mode: "full" };
    this.objectUrl = null;
    this._bind();
  }

  _bind() {
    $("det-play").onclick = () => (this.video.paused ? this._play() : this.video.pause());
    $("det-prev").onclick = () => this.step(-1);
    $("det-next").onclick = () => this.step(1);
    $("det-speed").onchange = e => { this.video.playbackRate = Number(e.target.value); };
    $("det-slider").oninput = e => { this.video.pause(); this.seekFrame(Number(e.target.value)); };
    $("det-strip").onclick = e => {
      const box = e.target.getBoundingClientRect();
      const span = this.range.last - this.range.first + 1;
      this.video.pause();
      this.seekFrame(this.range.first + Math.floor(((e.clientX - box.left) / box.width) * span));
    };
    $("clip-select").onchange = e => this.loadClip(e.target.value);
    $("range-select").onchange = e => this.setRange(e.target.value);
    this.video.addEventListener("play", () => { $("det-play").textContent = "❚❚ Pause"; });
    this.video.addEventListener("pause", () => { $("det-play").textContent = "▶ Play"; });
    this.video.addEventListener("seeked", () => this.showTime(this.video.currentTime));
    window.addEventListener("resize", () => this.draw());
  }

  async init() {
    const clips = this.manifest?.clips || [];
    $("clip-select").innerHTML = clips.map(c => `<option value="${c.id}">${c.label}</option>`).join("");
    if (!clips.length) {
      this._empty("No video prepared yet.\nRun demo/prepare_media.py with a video and its ArUco detection CSV\n(see demo/README.md), then reload this page.");
      this.state.ready = true;
      return;
    }
    // ?clip=<id> opens that recording first (e.g. ?present&clip=water_controlled).
    const wanted = new URLSearchParams(location.search).get("clip");
    await this.loadClip((clips.find(c => c.id === wanted) || clips[0]).id);
  }

  _empty(message) {
    const box = $("detection-empty");
    box.hidden = false;
    box.textContent = message;
    this._status("No clip loaded", "nodata");
  }

  async loadClip(id) {
    this.state.ready = false;
    this.video.pause();
    this.clip = this.manifest.clips.find(c => c.id === id);
    $("clip-select").value = id;
    this.onClip?.(this.clip);            // e.g. the statistics panel follows the selected clip
    const base = "media/";
    const [timesJson, csvText, videoBlob] = await Promise.all([
      fetch(base + this.clip.frame_times).then(r => { if (!r.ok) throw new Error("frame times missing"); return r.json(); }),
      fetch(base + this.clip.detections).then(r => { if (!r.ok) throw new Error("detection CSV missing"); return r.text(); }),
      fetch(base + this.clip.video).then(r => { if (!r.ok) throw new Error("video missing"); return r.blob(); }),
    ]);
    this.times = timesJson;
    this.pts = timesJson.pts_s;
    this.rows = parseDetectionCsv(csvText);
    this.segments = this.clip.segments || [];
    this.state.error = null;
    if (this.objectUrl) URL.revokeObjectURL(this.objectUrl);
    this.objectUrl = URL.createObjectURL(videoBlob);   // blob URL: reliable seeking without HTTP ranges

    $("clip-marker-badge").textContent =
      `Marker ID ${this.clip.marker_id} · ${this.clip.dictionary} · ${this.clip.marker_mm} mm`;
    const cameraText = this.clip.camera_description || (this.clip.camera === "fixed" ? "fixed camera" : "moving camera");
    $("clip-source-badge").textContent =
      `Real video · ${this.clip.environment ? `${this.clip.environment} · ` : ""}${cameraText}`;
    $("camera-notice").textContent = this.clip.camera === "moving"
      ? `${this.clip.camera_description || "Moving camera"}: this clip shows detection status and marker corners only. No pose, roll or pitch is derived from it.`
      : "Fixed camera: detection status and corners only. Pose and vessel angles need a calibrated camera and are not computed here.";

    const total = this.pts[this.pts.length - 1];
    const options = [];
    if (this.clip.default_range) {
      const d = this.clip.default_range;
      options.push(`<option value="default">${clock(d.start_s)}–${clock(d.end_s)} (default)</option>`);
    }
    options.push(`<option value="full">Full clip ${clock(0)}–${clock(total)}</option>`);
    $("range-select").innerHTML = options.join("");

    await new Promise((resolve, reject) => {
      this.video.onloadeddata = resolve;
      this.video.onerror = () => reject(new Error("the browser could not decode this video"));
      this.video.src = this.objectUrl;
    });
    const w = this.video.videoWidth, h = this.video.videoHeight;
    this.state.overlayEnabled = w === timesJson.upright_width && h === timesJson.upright_height;
    if (!this.state.overlayEnabled) {
      this.state.error = `Video shows as ${w}x${h} but the detection CSV is for ${timesJson.upright_width}x` +
                         `${timesJson.upright_height}; overlay disabled.`;
    }
    if (!this._watching) { this._watchFrames(); this._watching = true; }
    await this.setRange(this.clip.default_range ? "default" : "full");
    this.state.ready = true;
  }

  async setRange(mode) {
    const d = this.clip.default_range;
    this.range = mode === "default" && d
      ? { first: d.first_frame, last: d.last_frame, mode }
      : { first: 0, last: this.pts.length - 1, mode: "full" };
    this.state.range = { ...this.range };
    $("range-select").value = this.range.mode;
    const slider = $("det-slider");
    slider.min = String(this.range.first);
    slider.max = String(this.range.last);
    const inRange = this.range.first <= this.range.last;
    const count = (pred) => { let n = 0; for (let k = this.range.first; k <= this.range.last; k++) if (pred(k)) n++; return n; };
    const detected = count(k => this.rows.get(k)?.detected);
    const noData = count(k => !this.rows.has(k));
    const invalid = count(k => this.segmentAt(k));
    $("detection-summary").textContent = inRange
      ? `In this range: marker ID ${this.clip.marker_id} detected in ${detected} of ${this.range.last - this.range.first + 1} frames` +
        (noData ? `; ${noData} frames have no detection data` : "") +
        (invalid ? `; ${invalid} frames are in an invalid segment` : "") + "."
      : "";
    this._drawStrip();
    this.video.pause();
    await this.seekFrame(this.range.first);
  }

  segmentAt(k) {
    return this.segments.find(s => s.kind === "invalid" && s.start_frame <= k && k <= s.end_frame) || null;
  }

  _play() {
    if ((this.state.frame ?? 0) >= this.range.last) {
      this.seekFrame(this.range.first).then(() => this.video.play());
    } else {
      this.video.play();
    }
  }

  _watchFrames() {
    if (!("requestVideoFrameCallback" in HTMLVideoElement.prototype)) {
      const loop = () => { this.showTime(this.video.currentTime); requestAnimationFrame(loop); };
      requestAnimationFrame(loop);
      return;
    }
    const onFrame = (_now, meta) => {
      this.showTime(meta.mediaTime);
      this.video.requestVideoFrameCallback(onFrame);
    };
    this.video.requestVideoFrameCallback(onFrame);
  }

  /** Frame shown at video time t: the last frame whose presentation time is <= t. */
  frameAt(t) {
    return Math.max(0, lastIndexAtOrBefore(this.pts, t + 1e-4));
  }

  seekFrame(k) {
    k = Math.min(Math.max(this.range.first, Math.round(k)), this.range.last);
    const t = k + 1 < this.pts.length ? (this.pts[k] + this.pts[k + 1]) / 2 : this.pts[k] + 0.01;
    return new Promise(resolve => {
      const done = () => { this.video.removeEventListener("seeked", done); this.showTime(this.video.currentTime); resolve(k); };
      this.video.addEventListener("seeked", done);
      this.video.currentTime = t;
    });
  }

  /** Presentation jump: load the clip and range if needed, show the frame, stay paused. */
  async jumpTo(point) {
    this.video.pause();
    if (!this.clip || this.clip.id !== point.clip) await this.loadClip(point.clip);
    const mode = point.range === "default" && this.clip.default_range ? "default" : "full";
    if (this.range.mode !== mode) await this.setRange(mode);
    await this.seekFrame(point.frame);
    this.video.pause();
    return this.state.frame;
  }

  step(delta) {
    this.video.pause();
    return this.seekFrame((this.state.frame ?? this.range.first) + delta);
  }

  showTime(t) {
    if (!this.pts.length) return;
    this.state.mediaTime = t;
    this.state.frame = this.frameAt(t);
    if (!this.video.paused && this.state.frame > this.range.last) {   // stop at the end of the range
      this.video.pause();
      this.seekFrame(this.range.last);
      return;
    }
    this.draw();
  }

  _status(text, kind) {
    const chip = $("detection-status");
    chip.textContent = text;
    chip.className = `status-chip ${kind}`;
    this.state.status = text;
  }

  draw() {
    const k = this.state.frame;
    if (k === null || !this.pts.length) return;
    const row = this.rows.get(k);
    const segment = this.segmentAt(k);
    this.state.segment = segment ? segment.label : null;
    $("det-slider").value = String(k);
    $("ro-frame").textContent = `${k} / ${this.pts.length - 1}`;
    $("ro-time").textContent = `${this.pts[k].toFixed(3)} s`;
    $("ro-csv-time").textContent = row && row.nominalTime !== null ? `${row.nominalTime.toFixed(3)} s` : "—";
    $("ro-side").textContent = row && row.detected && row.meanSide !== null ? `${row.meanSide.toFixed(1)} px` : "—";
    $("ro-other").textContent = row && row.otherIds ? row.otherIds : "—";
    $("ro-segment").textContent = segment ? "Invalid" : "—";
    $("frame-line").textContent = `Frame ${k} · ${this.pts[k].toFixed(3)} s`;
    const manual = segment && segment.annotation === "manual";
    const banner = $("segment-banner");
    banner.hidden = !segment;
    banner.textContent = segment ? segment.label + (manual ? " · manually annotated" : "") : "";
    banner.title = segment ? segment.note : "";
    // Second status, separate from the detector's result: a person's annotation of this frame.
    const segChip = $("segment-status"), reason = $("segment-reason");
    segChip.hidden = !segment;
    reason.hidden = !segment;
    segChip.textContent = segment
      ? `Invalid for vessel tracking${manual ? " — manually annotated" : ""}` : "";
    reason.textContent = segment
      ? `${segment.label} (frames ${segment.start_frame}–${segment.end_frame}). ${segment.note || ""}`.trim() : "";
    this.state.segmentStatus = segment ? segChip.textContent : null;
    const tbody = $("corner-table").querySelector("tbody");
    tbody.innerHTML = row && row.detected
      ? row.corners.map(([x, y], i) => `<tr><td>${i}</td><td>${x.toFixed(1)}</td><td>${y.toFixed(1)}</td></tr>`).join("")
      : `<tr><td colspan="3">—</td></tr>`;

    if (this.state.error) this._status(this.state.error, "bad");
    else if (!row) this._status("No detection data for this frame", "nodata");
    else if (row.detected) this._status(`Marker ID ${this.clip.marker_id} detected`, "ok");
    else this._status("Marker not detected", "miss");

    // Overlay: only on frames with a recorded detection, and only if the video size matches.
    const canvas = this.overlay;
    const box = canvas.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    canvas.width = Math.round(box.width * dpr);
    canvas.height = Math.round(box.height * dpr);
    const ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, box.width, box.height);
    this.state.overlayDrawn = false;
    if (!this.state.overlayEnabled || !row || !row.detected) { this._drawPlayhead(k); return; }
    const vw = this.video.videoWidth, vh = this.video.videoHeight;
    const scale = Math.min(box.width / vw, box.height / vh);       // object-fit: contain
    const ox = (box.width - vw * scale) / 2, oy = (box.height - vh * scale) / 2;
    const pts = row.corners.map(([x, y]) => [ox + x * scale, oy + y * scale]);
    ctx.lineWidth = 3;
    ctx.strokeStyle = segment ? "#e74c3c" : "#2ecc71";
    ctx.setLineDash(segment ? [8, 6] : []);              // dashed red: detected, but not valid for tracking
    ctx.beginPath();
    pts.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)));
    ctx.closePath();
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.font = "bold 16px Segoe UI, sans-serif";
    // Text labels are kept inside the visible video area; the outline and corner dots stay exactly
    // at the CSV coordinates. clampX/clampY only move where a label is written.
    const left = ox, right = ox + vw * scale, top = oy, bottom = oy + vh * scale;
    const clampX = (x, w) => Math.min(Math.max(x, left + 2), right - w - 2);
    const clampY = (y, h) => Math.min(Math.max(y, top + h + 2), bottom - 4);
    pts.forEach(([x, y], i) => {
      ctx.fillStyle = "#e74c3c";
      ctx.beginPath(); ctx.arc(x, y, 6, 0, 2 * Math.PI); ctx.fill();
      ctx.fillStyle = "#ffffff";
      ctx.fillText(String(i), clampX(x + 8, 10), clampY(y - 8, 14));
    });
    const cx = pts.reduce((s, p) => s + p[0], 0) / 4, cy = pts.reduce((s, p) => s + p[1], 0) / 4;
    const labelW = 68, labelH = 24;
    const lx = clampX(cx - labelW / 2, labelW), ly = Math.min(Math.max(cy - 14, top + 2), bottom - labelH - 2);
    ctx.fillStyle = "rgba(0,0,0,0.6)";
    ctx.fillRect(lx, ly, labelW, labelH);
    ctx.fillStyle = "#ff79f2";
    ctx.fillText(`ID ${this.clip.marker_id}`, lx + 8, ly + 18);
    this.state.idLabelBox = [lx, ly, labelW, labelH, left, right];   // for the layout check
    this.state.overlayDrawn = true;
    this._drawPlayhead(k);
  }

  _drawStrip() {
    const canvas = $("det-strip");
    const { first, last } = this.range;
    const n = Math.max(1, last - first + 1);
    canvas.width = n;
    canvas.height = 1;
    const ctx = canvas.getContext("2d");
    for (let k = first; k <= last; k++) {
      const row = this.rows.get(k);
      const invalid = this.segmentAt(k);
      ctx.fillStyle = !row ? COLOURS.nodata
        : row.detected ? (invalid ? COLOURS.invalidDetected : COLOURS.detected)
        : (invalid ? COLOURS.invalidMissed : COLOURS.missed);
      ctx.fillRect(k - first, 0, 1, 1);
    }
    this._stripImage = ctx.getImageData(0, 0, n, 1);
  }

  _drawPlayhead(k) {
    const canvas = $("det-strip");
    if (!this._stripImage) return;
    const ctx = canvas.getContext("2d");
    ctx.putImageData(this._stripImage, 0, 0);
    ctx.fillStyle = COLOURS.playhead;
    const span = this.range.last - this.range.first + 1;
    ctx.fillRect(k - this.range.first, 0, Math.max(1, Math.round(span / 300)), 1);
  }

  /** Test helper: the current video frame as a PNG data URL at its native size. */
  grabFrame() {
    const c = document.createElement("canvas");
    c.width = this.video.videoWidth;
    c.height = this.video.videoHeight;
    c.getContext("2d").drawImage(this.video, 0, 0);
    return c.toDataURL("image/png");
  }
}
