// CSV parsing and data adapters. No values are invented: blanks stay null.

export const MEASURED_SOURCES = new Set(["arduino_mpu6050"]);  // same rule as sensor_log.py

/** RFC 4180 CSV: quoted fields may contain commas, quotes ("") and newlines. */
export function parseCsv(text) {
  const rows = [];
  let row = [], field = "", quoted = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (quoted) {
      if (c === '"') {
        if (text[i + 1] === '"') { field += '"'; i++; } else { quoted = false; }
      } else { field += c; }
    } else if (c === '"') { quoted = true; }
    else if (c === ",") { row.push(field); field = ""; }
    else if (c === "\n" || c === "\r") {
      if (c === "\r" && text[i + 1] === "\n") i++;
      row.push(field); rows.push(row); row = []; field = "";
    } else { field += c; }
  }
  if (field !== "" || row.length) { row.push(field); rows.push(row); }
  const nonEmpty = rows.filter(r => !(r.length === 1 && r[0] === ""));
  if (!nonEmpty.length) return { header: [], records: [] };
  const header = nonEmpty[0].map(h => h.replace(/^﻿/, "").trim());
  const records = nonEmpty.slice(1).map(r => Object.fromEntries(header.map((h, j) => [h, r[j] ?? ""])));
  return { header, records };
}

/** Number or null (blank, "nan", non-numeric and non-finite values are missing). */
export function toNumber(value) {
  if (value === null || value === undefined) return null;
  const text = String(value).trim();
  if (text === "" || /^nan$/i.test(text)) return null;
  const n = Number(text);
  return Number.isFinite(n) ? n : null;
}

/**
 * SmartTrim sensor CSV -> recordings, following sensor_log.load_recording:
 * roll_deg and pitch_deg columns are required; time comes from timestamp_ms
 * (relative to the first one in the file) when present, otherwise time_s;
 * rows without a time or roll value are dropped; recordings are grouped by
 * run_id and source. Pitch may be blank on a row (shown as missing).
 */
export function parseSensorCsv(text) {
  const { header, records } = parseCsv(text);
  const problems = [];
  for (const col of ["roll_deg", "pitch_deg"]) if (!header.includes(col)) problems.push(`missing column ${col}`);
  const stamps = header.includes("timestamp_ms") ? records.map(r => toNumber(r.timestamp_ms)) : [];
  const firstStamp = stamps.find(s => s !== null);
  if (firstStamp === undefined && !header.includes("time_s")) {
    problems.push("missing column time_s (and no timestamp_ms to derive it)");
  }
  if (problems.length) return { recordings: [], problems };

  const groups = new Map();
  records.forEach((r, i) => {
    const t = firstStamp !== undefined ? (stamps[i] === null ? null : (stamps[i] - firstStamp) / 1000)
                                       : toNumber(r.time_s);
    const roll = toNumber(r.roll_deg);
    if (t === null || roll === null) return;
    const runId = (r.run_id || "").trim() || "unnamed run";
    const source = (r.source || "").trim() || "unknown source";
    const key = `${runId} · ${source}`;
    if (!groups.has(key)) {
      groups.set(key, { key, runId, source, measured: MEASURED_SOURCES.has(source),
                        notes: r.notes || "", axisConvention: r.axis_convention || "", rows: [] });
    }
    groups.get(key).rows.push({ t, roll, pitch: toNumber(r.pitch_deg) });
  });
  const recordings = [...groups.values()].map(g => {
    g.rows.sort((a, b) => a.t - b.t);
    const t0 = g.rows[0].t;
    g.rows.forEach(row => { row.t -= t0; });
    const dts = g.rows.slice(1).map((row, i) => row.t - g.rows[i].t).filter(d => d > 0).sort((a, b) => a - b);
    g.medianDt = dts.length ? dts[Math.floor(dts.length / 2)] : null;
    g.duration = g.rows[g.rows.length - 1].t;
    return g;
  });
  if (!recordings.length) problems.push("no valid rows");
  return { recordings, problems };
}

/** Index of the last sample at or before t, or -1. */
export function lastIndexAtOrBefore(times, t) {
  let lo = 0, hi = times.length - 1, found = -1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (times[mid] <= t + 1e-9) { found = mid; lo = mid + 1; } else { hi = mid - 1; }
  }
  return found;
}

/**
 * Sample shown at time t: the latest sample not older than the gap limit
 * (1.5 x the median sample interval). Otherwise null: the replay shows "no sample"
 * rather than holding or interpolating a value across a gap.
 */
export function sampleAt(recording, t) {
  const times = recording._times || (recording._times = recording.rows.map(r => r.t));
  const i = lastIndexAtOrBefore(times, t);
  if (i < 0) return null;
  const limit = recording.medianDt ? 1.5 * recording.medianDt : 0;
  return t - times[i] <= limit + 1e-9 ? recording.rows[i] : null;
}

/** aruco_check.py detection CSV -> Map(frame -> row). Missing frames stay absent. */
export function parseDetectionCsv(text) {
  const { header, records } = parseCsv(text);
  const needed = ["frame", "detected", "c0_x", "c0_y", "c1_x", "c1_y", "c2_x", "c2_y", "c3_x", "c3_y"];
  const missing = needed.filter(c => !header.includes(c));
  if (missing.length) throw new Error(`detection CSV is missing columns: ${missing.join(", ")}`);
  const byFrame = new Map();
  for (const r of records) {
    const frame = toNumber(r.frame);
    if (frame === null) continue;
    const detected = r.detected === "True";
    let corners = null;
    if (detected) {
      corners = [0, 1, 2, 3].map(i => [toNumber(r[`c${i}_x`]), toNumber(r[`c${i}_y`])]);
      if (corners.some(([x, y]) => x === null || y === null)) corners = null;
    }
    byFrame.set(frame, {
      frame, detected: detected && corners !== null, corners,
      markerId: toNumber(r.marker_id), otherIds: (r.other_ids || "").trim(),
      nominalTime: toNumber(r.time_s), meanSide: toNumber(r.mean_side_px),
    });
  }
  return byFrame;
}
