// SmartTrim V5 · Test Replay: tab switching, local manifest, and the shared-timeline gate.
import { DetectionReview } from "./detection.js";
import { Presentation } from "./presentation.js";
import { MotionReplay } from "./replay.js";
import { DetectionStats, recordingGroup } from "./stats.js";
import { Showcase } from "./showcase.js";

const $ = id => document.getElementById(id);

async function loadManifest() {
  try {
    const response = await fetch("media/manifest.json", { cache: "no-store" });
    return response.ok ? await response.json() : null;
  } catch {
    return null;
  }
}

function setupTabs() {
  document.querySelectorAll(".tab").forEach(button => {
    button.onclick = () => {
      document.querySelectorAll(".tab").forEach(b => b.classList.toggle("active", b === button));
      document.querySelectorAll(".panel").forEach(p =>
        p.classList.toggle("active", p.id === `panel-${button.dataset.tab}`));
      if (button.dataset.tab === "detection") window.__demo.replay?.setPlaying(false);
      else window.__demo.detection?.video.pause();
      window.dispatchEvent(new Event("resize"));
    };
  });
}

// The two timelines stay independent. A shared timeline needs a video and a sensor CSV
// from the same run plus a verified time offset, recorded in the manifest. None exist yet.
function describeSharedTimeline(manifest) {
  const links = (manifest?.shared_timeline_links || []).filter(l => l.offset_verified === true);
  return links.length
    ? `Shared timeline: ${links.length} verified video/sensor link(s) recorded, but linking is not built yet; timelines stay independent.`
    : "Shared timeline: off. The two timelines are independent. A shared timeline needs a video and a sensor CSV " +
      "from the same run and a verified time offset; none is recorded yet.";
}

async function main() {
  setupTabs();
  const manifest = await loadManifest();
  const gate = describeSharedTimeline(manifest);
  $("shared-gate-detection").textContent = gate;
  $("shared-gate-replay").textContent = gate;
  window.__demo = { manifest, sharedTimeline: false, errors: [] };
  window.__demo.detection = new DetectionReview(manifest);
  window.__demo.replay = new MotionReplay(manifest);
  // Statistics panel: counts from every clip's CSV; follows the clip shown in the review.
  const stats = new DetectionStats(manifest, id => window.__demo.detection.loadClip(id));
  window.__demo.stats = stats;
  // When the recording changes, the statistics, the highlights and the Showcase summary follow it.
  window.__demo.detection.onClip = clip => {
    stats.select(clip.id);
    window.__demo.presentation?.showFor(clip.id);
    window.__demo.showcase?.update(clip.id);
  };
  const statsReady = stats.init().catch(err => { window.__demo.errors.push(String(err)); });
  // Engineering / Showcase views share the same elements, so switching keeps the recording and position.
  window.__demo.showcase = new Showcase({ detection: window.__demo.detection, replay: window.__demo.replay, stats, statsReady });
  window.__demo.showcase.init();
  await Promise.all([
    statsReady,
    window.__demo.detection.init().catch(err => { window.__demo.errors.push(String(err)); throw err; }),
    window.__demo.replay.init().then(() => window.__demo.showcase.refresh3D())
      .catch(err => { window.__demo.errors.push(String(err)); throw err; }),
  ]);
  // Presentation mode affects the detection tab only; the 3D replay stays independent.
  window.__demo.presentation = new Presentation(window.__demo.detection, manifest, recordingGroup);
  await window.__demo.presentation.init();
  window.__demo.ready = true;
}

main().catch(err => console.error(err));
