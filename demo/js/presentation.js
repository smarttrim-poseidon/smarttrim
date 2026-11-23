// Presentation mode for ArUco Detection Review: a compact layout and verified jump points.
// Each jump point is checked against the prepared media before it can be used.
import { parseDetectionCsv } from "./data.js";

const $ = id => document.getElementById(id);
const TIME_TOLERANCE_S = 1.0;

async function loadClipData(clip, cache) {
  if (!cache.has(clip.id)) {
    cache.set(clip.id, Promise.all([
      fetch("media/" + clip.frame_times).then(r => (r.ok ? r.json() : Promise.reject(new Error("frame times missing")))),
      fetch("media/" + clip.detections).then(r => (r.ok ? r.text() : Promise.reject(new Error("detection CSV missing")))),
    ]).then(([times, csv]) => ({ pts: times.pts_s, rows: parseDetectionCsv(csv) })));
  }
  return cache.get(clip.id);
}

/** Check one jump point: the clip exists, the frame is in range, and what it shows matches. */
export async function verifyPoint(point, manifest, cache = new Map()) {
  const clip = (manifest?.clips || []).find(c => c.id === point.clip);
  if (!clip) return { ok: false, reason: `clip ${point.clip} is not prepared` };
  let data;
  try { data = await loadClipData(clip, cache); } catch (err) { return { ok: false, reason: String(err.message || err) }; }
  const k = point.frame;
  if (!(k >= 0 && k < data.pts.length)) return { ok: false, reason: `frame ${k} is outside the clip` };
  if (point.range === "default") {
    if (!clip.default_range) return { ok: false, reason: "clip has no default range" };
    if (k < clip.default_range.first_frame || k > clip.default_range.last_frame)
      return { ok: false, reason: `frame ${k} is outside the default range` };
  }
  const t = data.pts[k];
  if (Math.abs(t - point.approx_s) > TIME_TOLERANCE_S)
    return { ok: false, reason: `frame ${k} is at ${t.toFixed(2)} s, not ~${point.approx_s} s` };
  const row = data.rows.get(k);
  if (!row) return { ok: false, reason: `no detection data for frame ${k}` };
  if (row.detected !== point.expect.detected)
    return { ok: false, reason: `frame ${k} is ${row.detected ? "detected" : "not detected"} in the CSV` };
  const invalid = (clip.segments || []).some(s => s.kind === "invalid" && s.start_frame <= k && k <= s.end_frame);
  if (invalid !== point.expect.invalid)
    return { ok: false, reason: `frame ${k} is ${invalid ? "" : "not "}in an invalid segment` };
  return { ok: true, time_s: t, detected: row.detected, invalid };
}

const esc = s => String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const mmss = t => `${String(Math.floor(t / 60)).padStart(2, "0")}:${String(Math.floor(t % 60)).padStart(2, "0")}`;

/**
 * Presentation highlights (verified jump points), grouped by recording. The highlight bar shows
 * only the selected recording's highlights; in normal mode "All highlights" lists every group.
 */
export class Presentation {
  constructor(detection, manifest, groupName = clip => clip.label) {
    this.detection = detection;
    this.manifest = manifest;
    this.groupName = groupName;
    this.points = [];
    this.results = [];
    this.active = null;
    this.on = false;
    this.clipId = null;
    this.ready = false;
    $("present-toggle").onclick = () => this.setOn(!this.on);
  }

  async init() {
    let config = null;
    try {
      const response = await fetch("presentation.json", { cache: "no-store" });
      config = response.ok ? await response.json() : null;
    } catch { config = null; }
    this.points = config?.jump_points || [];
    const cache = new Map();
    this.results = await Promise.all(this.points.map(p => verifyPoint(p, this.manifest, cache)));
    this.ready = true;
    this._renderAll();
    this.showFor(this.clipId ?? this.detection.clip?.id ?? null);
    if (new URLSearchParams(location.search).has("present")) this.setOn(true);
  }

  _button(i) {
    const p = this.points[i], r = this.results[i];
    return `<button class="btn jump${this.active === i ? " active" : ""}" data-index="${i}" ${r.ok ? "" : "disabled"}
              title="${esc(r.ok ? `${p.clip} · frame ${p.frame} · ${r.time_s.toFixed(3)} s` : r.reason)}">
              <span>${esc(p.title)}</span><span class="t">${r.ok ? mmss(r.time_s) : "unavailable"}</span></button>`;
  }

  _bindButtons(root) {
    root.querySelectorAll(".jump").forEach(b => {
      b.onclick = () => { $("jump-all").open = false; this.jump(Number(b.dataset.index)); };
    });
  }

  /** Every highlight, grouped by recording in manifest order (normal mode, "All highlights"). */
  _renderAll() {
    const clips = this.manifest?.clips || [];
    const groups = clips.map(clip => ({ clip, idx: this.points.map((p, i) => (p.clip === clip.id ? i : -1)).filter(i => i >= 0) }))
      .filter(g => g.idx.length);
    const orphans = this.points.map((p, i) => (clips.some(c => c.id === p.clip) ? -1 : i)).filter(i => i >= 0);
    const list = $("jump-all-list");
    list.innerHTML = groups.map(g => `<div class="jump-group" data-clip="${esc(g.clip.id)}">
        <div class="jump-group-label">${esc(this.groupName(g.clip))}</div>
        <div class="jump-buttons">${g.idx.map(i => this._button(i)).join("")}</div></div>`).join("") +
      (orphans.length ? `<div class="jump-group"><div class="jump-group-label">Not prepared</div>
        <div class="jump-buttons">${orphans.map(i => this._button(i)).join("")}</div></div>` : "");
    $("jump-all").querySelector("summary").textContent = `All highlights (${this.points.length})`;
    this._bindButtons(list);
  }

  /** Show the selected recording's highlights; called whenever the recording changes. */
  showFor(clipId) {
    this.clipId = clipId;
    if (!this.ready) return;
    if (this.active !== null && this.points[this.active]?.clip !== clipId) {
      this.active = null;                                   // caption belonged to another recording
      $("jump-caption").hidden = true;
    }
    const idx = this.points.map((p, i) => (p.clip === clipId ? i : -1)).filter(i => i >= 0);
    const bar = $("jump-buttons");
    bar.innerHTML = idx.length ? idx.map(i => this._button(i)).join("")
                               : `<span class="jump-empty">No highlights for this recording</span>`;
    this._bindButtons(bar);
    this._markActive();
  }

  _markActive() {
    document.querySelectorAll(".jump").forEach(b => b.classList.toggle("active", Number(b.dataset.index) === this.active));
  }

  setOn(on) {
    this.on = on;
    document.body.classList.toggle("presenting", on);
    $("present-toggle").setAttribute("aria-pressed", String(on));
    $("present-toggle").textContent = on ? "Exit presentation" : "Presentation mode";
    $("jump-all").open = false;
    $("frame-details").open = !on;          // coordinates collapse under "Frame details"
    window.dispatchEvent(new Event("resize"));
  }

  async jump(index) {
    const point = this.points[index];
    if (!this.results[index]?.ok) return null;
    this.active = index;                     // set first: loading another clip re-renders the bar
    this._markActive();
    const frame = await this.detection.jumpTo(point);
    this.active = index;
    this._markActive();
    const caption = $("jump-caption");
    caption.textContent = point.caption;
    caption.hidden = false;
    return frame;
  }
}
