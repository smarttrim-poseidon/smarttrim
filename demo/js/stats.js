// Detection statistics for ArUco Detection Review. Every number is counted from the
// prepared detection CSV and frame_times.json of each clip; nothing is hardcoded.
import { parseDetectionCsv } from "./data.js";

const $ = id => document.getElementById(id);

/**
 * Counts for one clip.
 *   rows: Map(frame -> parsed CSV row), pts: presentation time of every video frame,
 *   segments: manifest segments (frames in an "invalid" one are excluded from the valid rate).
 * Detection rate = detected / frames with detection data. Frames outside the video are ignored.
 */
export function computeClipStats(rows, pts, segments = []) {
  const totalFrames = pts.length;
  const invalid = (segments || []).filter(s => s.kind === "invalid");
  const inInvalid = k => invalid.some(s => s.start_frame <= k && k <= s.end_frame);
  let analysed = 0, detected = 0, validFrames = 0, validDetected = 0;
  for (const [k, row] of rows) {
    if (!(k >= 0 && k < totalFrames)) continue;
    analysed++;
    if (row.detected) detected++;
    if (!inInvalid(k)) { validFrames++; if (row.detected) validDetected++; }
  }
  const gaps = pts.slice(1).map((t, i) => t - pts[i]).sort((a, b) => a - b);
  const medianGap = gaps.length ? gaps[Math.floor(gaps.length / 2)] : 0;
  const rate = (n, d) => (d ? (100 * n) / d : null);
  return {
    totalFrames, analysedFrames: analysed, detected, notDetected: analysed - detected,
    noDataFrames: totalFrames - analysed, detectionRate: rate(detected, analysed),
    // End of the last frame: its presentation time plus one typical frame interval.
    durationS: totalFrames ? pts[totalFrames - 1] + medianGap : 0,
    hasInvalidSegment: invalid.length > 0,
    invalidRanges: invalid.map(s => [s.start_frame, s.end_frame]),
    validFrames, validDetected, validRate: rate(validDetected, validFrames),
  };
}

const pct = v => (v === null ? "—" : `${v.toFixed(1)} %`);
const esc = s => String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

export function describeCamera(clip) {
  const camera = clip.camera_description || (clip.camera === "fixed" ? "Fixed camera" : "Moving camera");
  return clip.environment ? `${clip.environment} · ${camera}` : camera;
}

/** Short group name used by the recording steps and the highlights, e.g. "Bench · fixed camera". */
export function recordingGroup(clip) {
  if (!clip) return "";
  const camera = clip.camera === "fixed" ? "fixed camera" : "moving camera";
  if (!clip.environment) return clip.label;
  return clip.environment.toLowerCase() === "bench" ? `Bench · ${camera}` : clip.environment;
}

export class DetectionStats {
  constructor(manifest, onPick) {
    this.clips = manifest?.clips || [];
    this.onPick = onPick;            // clicking a step or chart row selects that clip in the review
    this.stats = new Map();          // clip id -> stats, or { error }
    this.selected = null;
    this.ready = false;
  }

  async init() {
    if (!this.clips.length) { $("det-stats").hidden = true; this.ready = true; return; }
    this._renderSteps();
    // One retry on a failed request (the same file is fetched again; nothing is filled in).
    const get = async (path, read, what) => {
      for (let attempt = 1; ; attempt++) {
        try {
          const r = await fetch("media/" + path, { cache: "no-store" });
          if (!r.ok) throw new Error(`${what} missing (HTTP ${r.status})`);
          return await read(r);
        } catch (err) {
          if (attempt >= 2) throw err;
          await new Promise(res => setTimeout(res, 300));
        }
      }
    };
    await Promise.all(this.clips.map(async clip => {
      try {
        const [times, csv] = await Promise.all([
          get(clip.frame_times, r => r.json(), "frame times"),
          get(clip.detections, r => r.text(), "detection CSV"),
        ]);
        this.stats.set(clip.id, computeClipStats(parseDetectionCsv(csv), times.pts_s, clip.segments));
      } catch (err) {
        this.stats.set(clip.id, { error: String(err.message || err) });
      }
    }));
    this.ready = true;
    this._renderSteps();
    this._renderChart();
    this.select(this.selected || this.clips[0].id);
  }

  select(id) {
    this.selected = id;
    document.querySelectorAll("#rec-steps .step").forEach(b => {
      const on = b.dataset.step === id;
      b.classList.toggle("active", on);
      b.setAttribute("aria-pressed", String(on));
    });
    if (!this.ready) return;
    const clip = this.clips.find(c => c.id === id);
    const s = this.stats.get(id);
    $("stats-title").textContent = clip ? clip.label : "—";
    $("stats-camera").textContent = clip ? describeCamera(clip) : "";
    const out = $("stats-readout"), hero = $("stats-hero");
    if (!clip || !s || s.error) {
      hero.innerHTML = "";
      out.innerHTML = `<div class="tile"><dt>Statistics</dt><dd>unavailable${s?.error ? ` (${esc(s.error)})` : ""}</dd></div>`;
    } else {
      // Headline rate. With an invalid segment both rates are shown, each clearly named.
      const rate = (key, value, label, cls = "") => `<div class="rate ${cls}"><span class="rate-value"><span data-stat="${key}">${
        value === null ? "—" : value.toFixed(1)}</span><small>%</small></span><span class="rate-label">${esc(label)}</span></div>`;
      const ranges = s.invalidRanges.map(([a, b]) => `${a}–${b}`).join(", ");
      hero.innerHTML = s.hasInvalidSegment
        ? rate("rate", s.detectionRate, "detection rate, all frames") +
          rate("valid-rate", s.validRate, `valid frames only (excl. ${ranges})`, "rate-valid")
        : rate("rate", s.detectionRate, `marker ID ${clip.marker_id} detection rate`);
      const tiles = [
        ["Recording duration", `${s.durationS.toFixed(2)} s`, "duration"],
        ["Frames analysed", String(s.analysedFrames), "analysed"],
        [`ID ${clip.marker_id} detected`, String(s.detected), "detected"],
        [`ID ${clip.marker_id} not detected`, String(s.notDetected), "not-detected"],
      ];
      if (s.noDataFrames) tiles.splice(2, 0, ["Frames without detection data", String(s.noDataFrames), "no-data"]);
      if (s.hasInvalidSegment) {
        tiles.push(["Valid frames", String(s.validFrames), "valid-frames", "tile-valid"],
                   ["Detected in valid frames", String(s.validDetected), "valid-detected", "tile-valid"]);
      }
      out.innerHTML = tiles.map(([k, v, key, cls]) =>
        `<div class="tile ${cls || ""}"><dt>${esc(k)}</dt><dd data-stat="${key}">${esc(v)}</dd></div>`).join("");
    }
    document.querySelectorAll("#stats-chart .bar-row").forEach(r =>
      r.classList.toggle("selected", r.dataset.clip === id));
  }

  /** Recording selector that tells the story: bench (moving), bench (fixed), then the water tank. */
  _renderSteps() {
    const box = $("rec-steps");
    if (!box) return;
    box.innerHTML = this.clips.map((clip, i) => {
      const s = this.stats.get(clip.id);
      const ok = s && !s.error;
      // With an invalid segment the step shows the valid-frames rate (the conservative one) and says so.
      const value = ok ? (s.hasInvalidSegment ? s.validRate : s.detectionRate) : null;
      const which = ok && s.hasInvalidSegment ? " · valid frames" : "";
      return (i ? `<span class="step-arrow" aria-hidden="true">›</span>` : "") +
        `<button class="step" data-step="${esc(clip.id)}" aria-pressed="false" title="${esc(clip.label)}">
          <span class="step-no">${i + 1}</span>
          <span class="step-env">${esc(recordingGroup(clip))}</span>
          <span class="step-id">${esc(clip.id)}${which}</span>
          <span class="step-rate">${value === null ? "" : `${value.toFixed(1)}<small>%</small>`}</span>
        </button>`;
    }).join("");
    box.querySelectorAll(".step").forEach(b => { b.onclick = () => this.onPick?.(b.dataset.step); });
    if (this.selected) this.select(this.selected);
  }

  _renderChart() {
    const rows = [];
    for (const clip of this.clips) {
      const s = this.stats.get(clip.id);
      if (!s || s.error) {
        rows.push(`<div class="bar-row" data-clip="${esc(clip.id)}" title="${esc(s?.error || "statistics unavailable")}"><span class="bar-name">${esc(clip.label)}</span>
          <span class="bar-track"></span><span class="bar-value">unavailable</span></div>`);
        continue;
      }
      const sub = s.hasInvalidSegment;
      const row = (kind, name, what, n, d, r) => `
        <div class="bar-row${sub ? " bar-sub" : ""}" data-clip="${esc(clip.id)}" data-kind="${kind}"
             data-detected="${n}" data-frames="${d}" data-rate="${r === null ? "" : r.toFixed(1)}"
             title="${esc(clip.label)}, ${what}: marker ID ${clip.marker_id} detected in ${n} of ${d} frames (${pct(r)})">
          <span class="bar-name">${esc(name)}</span>
          <span class="bar-track"><span class="bar-fill${kind === "valid" ? " bar-hatched" : ""}" style="width:${r === null ? 0 : r.toFixed(2)}%"></span></span>
          <span class="bar-value">${pct(r)} <small>${n}/${d}</small></span>
        </div>`;
      if (sub) {
        // A clip with an invalid segment gets a heading and two clearly named rates.
        const ranges = s.invalidRanges.map(([a, b]) => `${a}–${b}`).join(", ");
        rows.push(`<div class="bar-row bar-group" data-clip="${esc(clip.id)}"><span class="bar-name">${esc(clip.label)}</span></div>`);
        rows.push(row("all", "All frames", "all frames", s.detected, s.analysedFrames, s.detectionRate));
        rows.push(row("valid", `Valid frames only (excl. ${ranges})`, `valid frames only, excluding invalid frames ${ranges}`,
                      s.validDetected, s.validFrames, s.validRate));
      } else {
        rows.push(row("all", clip.label, "all frames", s.detected, s.analysedFrames, s.detectionRate));
      }
    }
    $("stats-chart").innerHTML = rows.join("") +
      `<div class="bar-axis" aria-hidden="true"><span>0 %</span><span>50 %</span><span>100 %</span></div>`;
    document.querySelectorAll("#stats-chart .bar-row").forEach(r => {
      r.onclick = () => this.onPick?.(r.dataset.clip);
    });
  }
}
