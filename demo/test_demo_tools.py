"""Tests for the Test Replay demo's Python tools (media preparation and sample data)."""
import csv
import hashlib
import json
import struct
from pathlib import Path

import pytest

import prepare_media as pm

DEMO_DIR = Path(__file__).resolve().parent
CSV_FIELDS = ["frame", "time_s", "detected", "marker_id", "other_ids",
              "c0_x", "c0_y", "c1_x", "c1_y", "c2_x", "c2_y", "c3_x", "c3_y", "mean_side_px"]


def write_video(path, frames=12, fps=10.0, size=(64, 48)):
    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, size)
    if not writer.isOpened():
        pytest.skip("OpenCV cannot write MP4 here")
    for i in range(frames):
        writer.write(np.full((size[1], size[0], 3), i * 10, np.uint8))
    writer.release()
    return path


def write_detections(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in CSV_FIELDS})
    return path


def detected_row(frame, corners):
    row = {"frame": frame, "time_s": f"{frame / 10:.3f}", "detected": "True", "marker_id": 0}
    for i, (x, y) in enumerate(corners):
        row[f"c{i}_x"], row[f"c{i}_y"] = x, y
    return row


def test_mp4_frame_times_match_a_constant_rate_video(tmp_path):
    video = write_video(tmp_path / "clip.mp4", frames=12, fps=10.0)
    times, info = pm.mp4_video_frame_times(video)
    assert len(times) == 12
    assert times == pytest.approx([i / 10 for i in range(12)], abs=1e-6)
    assert info["rotation_deg"] == 0 and (info["stored_width"], info["stored_height"]) == (64, 48)


def test_add_clip_writes_timestamps_copies_media_and_updates_manifest(tmp_path):
    video = write_video(tmp_path / "clip.mp4")
    csv_path = write_detections(tmp_path / "det.csv", [
        detected_row(0, [(10, 10), (30, 10), (30, 30), (10, 30)]),
        {"frame": 1, "time_s": "0.100", "detected": "False"},
    ])
    media = tmp_path / "media"
    summary = pm.add_clip(video, csv_path, "c1", "Clip 1", "fixed", media)
    assert summary["frame_count"] == 12 and summary["detected"] == 1 and summary["rows"] == 2
    times = json.loads((media / "c1" / "frame_times.json").read_text())
    assert times["upright_width"] == 64 and times["upright_height"] == 48
    assert len(times["pts_s"]) == 12
    assert (media / "c1" / "video.mp4").read_bytes() == video.read_bytes()
    manifest = json.loads((media / "manifest.json").read_text())
    assert [c["id"] for c in manifest["clips"]] == ["c1"]
    assert manifest["clips"][0]["camera"] == "fixed"
    assert manifest["shared_timeline_links"] == []
    pm.add_clip(video, csv_path, "c1", "Clip 1 again", "fixed", media)      # replaces, no duplicate
    assert len(json.loads((media / "manifest.json").read_text())["clips"]) == 1


@pytest.mark.parametrize("rows, message", [
    ([detected_row(0, [(10, 10), (60, 10), (60, 47), (10, 47)])], None),            # inside 64x48
    ([detected_row(0, [(10, 10), (80, 10), (80, 30), (10, 30)])], "outside the upright"),
    ([detected_row(12, [(1, 1), (2, 1), (2, 2), (1, 2)])], "outside the video"),
    ([detected_row(0, [(1, 1)] * 4), detected_row(0, [(1, 1)] * 4)], "appears twice"),
])
def test_detection_csv_checks(tmp_path, rows, message):
    video = write_video(tmp_path / "clip.mp4")
    csv_path = write_detections(tmp_path / "det.csv", rows)
    if message is None:
        pm.add_clip(video, csv_path, "ok", "ok", "moving", tmp_path / "media")
    else:
        with pytest.raises(pm.MediaError, match=message):
            pm.add_clip(video, csv_path, "bad", "bad", "moving", tmp_path / "media")


def test_default_range_and_invalid_segment_are_recorded(tmp_path):
    video = write_video(tmp_path / "clip.mp4", frames=12, fps=10.0)     # frames at 0.0 .. 1.1 s
    csv_path = write_detections(tmp_path / "det.csv", [
        detected_row(k, [(10, 10), (30, 10), (30, 30), (10, 30)]) for k in range(12)])
    label = "Invalid for vessel tracking — marker detached"
    result = pm.add_clip(video, csv_path, "fixed1", "Fixed", "fixed", tmp_path / "media",
                         default_range_s=(0, 0.5), invalid_segments=[(8, 11, label, "evidence")])
    assert result["default_range"] == {"start_s": 0.0, "end_s": 0.5, "first_frame": 0, "last_frame": 5}
    clip = json.loads((tmp_path / "media" / "manifest.json").read_text(encoding="utf-8"))["clips"][0]
    seg = clip["segments"][0]
    assert (seg["kind"], seg["start_frame"], seg["end_frame"], seg["label"]) == ("invalid", 8, 11, label)
    assert seg["start_s"] == pytest.approx(0.8) and seg["note"] == "evidence"
    assert seg["annotation"] == "manual"
    # Detections inside the invalid segment stay as recorded; the segment only labels them.
    assert result["detected"] == 12
    # No range and no segments by default.
    plain = pm.add_clip(video, csv_path, "plain", "Plain", "moving", tmp_path / "media")
    assert plain["default_range"] is None and plain["segments"] == []


@pytest.mark.parametrize("kwargs, message", [
    ({"default_range_s": (5, 1)}, "START < END"),
    ({"default_range_s": (50, 60)}, "no frames between"),
    ({"invalid_segments": [(10, 20, "x", "")]}, "outside 0-11"),
    ({"invalid_segments": [(5, 3, "x", "")]}, "outside 0-11"),
    ({"invalid_segments": [(1, 2, "  ", "")]}, "needs a label"),
])
def test_bad_range_or_segment_is_rejected(tmp_path, kwargs, message):
    video = write_video(tmp_path / "clip.mp4", frames=12, fps=10.0)
    csv_path = write_detections(tmp_path / "det.csv", [{"frame": 0, "time_s": "0", "detected": "False"}])
    with pytest.raises(pm.MediaError, match=message):
        pm.add_clip(video, csv_path, "c", "c", "fixed", tmp_path / "media", **kwargs)


def test_detection_csv_missing_columns_is_rejected(tmp_path):
    video = write_video(tmp_path / "clip.mp4")
    bad = tmp_path / "bad.csv"
    bad.write_text("frame,detected\n0,False\n", encoding="utf-8")
    with pytest.raises(pm.MediaError, match="missing columns"):
        pm.add_clip(video, bad, "x", "x", "moving", tmp_path / "media")


def _binary_stl(triangles):
    data = bytearray(80) + struct.pack("<I", len(triangles))
    for tri in triangles:
        data += struct.pack("<3f", 0, 0, 0)
        for vertex in tri:
            data += struct.pack("<3f", *vertex)
        data += b"\x00\x00"
    return bytes(data)


def test_cad_mesh_bounds_check(tmp_path):
    good = tmp_path / "good.stl"
    good.write_bytes(_binary_stl([[(-100, -84, 0), (100, 84, 98), (0, 0, 50)]]))
    mesh = pm.add_cad_mesh(tmp_path / "media", stl_path=good)
    assert mesh["bounds_mm"] == [[-100, -84, 0], [100, 84, 98]]
    wrong = tmp_path / "wrong.stl"
    wrong.write_bytes(_binary_stl([[(0, 0, 0), (50, 10, 10), (0, 10, 0)]]))
    with pytest.raises(pm.MediaError, match="do not look like the V5"):
        pm.add_cad_mesh(tmp_path / "media", stl_path=wrong)


def test_simulated_sample_is_labelled_and_loads_with_sensor_log():
    from sensor_log import load_recording
    frame, problems = load_recording((DEMO_DIR / "samples" / "simulated_motion_sample.csv").read_bytes())
    assert problems == []
    assert set(frame["source"]) == {"simulated"}
    runs = {run: group for run, group in frame.groupby("run_id")}
    assert set(runs) == {"SIM_PITCH_ONLY", "SIM_ROLL_ONLY", "SIM_COMBINED_GAP"}
    assert (runs["SIM_PITCH_ONLY"]["roll_deg"] == 0).all()
    assert runs["SIM_PITCH_ONLY"]["pitch_deg"].abs().max() == pytest.approx(5.0)
    assert (runs["SIM_ROLL_ONLY"]["pitch_deg"] == 0).all()
    assert runs["SIM_ROLL_ONLY"]["roll_deg"].abs().max() == pytest.approx(8.0)
    gap_times = runs["SIM_COMBINED_GAP"]["time_s"]
    assert not ((gap_times >= 4.0) & (gap_times < 5.0)).any()       # the deliberate 1 s gap
    assert all("Not measured" in note for note in frame["notes"])


def test_environment_and_camera_description_are_optional(tmp_path):
    video = write_video(tmp_path / "clip.mp4")
    csv_path = write_detections(tmp_path / "det.csv", [{"frame": 0, "time_s": "0", "detected": "False"}])
    media = tmp_path / "media"
    pm.add_clip(video, csv_path, "plain", "Plain", "fixed", media)
    pm.add_clip(video, csv_path, "water", "Water", "moving", media, environment="Water tank",
                camera_description="Handheld, approximately stationary camera")
    clips = {c["id"]: c for c in json.loads((media / "manifest.json").read_text())["clips"]}
    assert "environment" not in clips["plain"] and "camera_description" not in clips["plain"]
    assert clips["water"]["environment"] == "Water tank"
    assert clips["water"]["camera_description"] == "Handheld, approximately stationary camera"


# ---------------------------------------------------------------------------
# Prepared media (committed in demo/media): skipped if it has been removed.
# ---------------------------------------------------------------------------
MEDIA = DEMO_DIR / "media"
needs_media = pytest.mark.skipif(not (MEDIA / "manifest.json").exists(), reason="demo/media not prepared")

# Verified results. Bench files must stay byte-identical to the final submission package.
EXPECTED = {
    "katamaran_10": {"frames": 1007, "detected": 492, "environment": "Bench", "camera": "moving"},
    "camera_stable": {"frames": 910, "detected": 255, "environment": "Bench", "camera": "fixed"},
    "water_controlled": {"frames": 1767, "detected": 1532, "environment": "Water tank", "camera": "moving"},
}
BENCH_SHA256 = {
    "katamaran_10/video.mp4": "3f5f4feca69ffb2dc0dfd42142520a99329b51189c8fbfcd7b079b5f08c16c1b",
    "katamaran_10/detections.csv": "3a44a568c5b72e97f13be7d5dbd1620bbf833f2325afbc9c93be077b2b46fc05",
    "katamaran_10/frame_times.json": "2a075eedf6ce1289a2965de3362b7da1b00c88ae53b0bd20e16c10a7a6f5e9f7",
    "camera_stable/video.mp4": "8d6740993a06db63203603b1891162e026683039e72a549e69442a85f69a18cf",
    "camera_stable/detections.csv": "aba4960dc35f84acaabf230095590fc79cf17619cef141a536c1865cf06fd3c3",
    "camera_stable/frame_times.json": "37e18c332d498831c58296f958143e873fd331d2a34baaedd0d7a919d414a0a2",
}
WATER_VIDEO_SHA256 = "d0dc1da501ba50aa36e18f3294205cbee0fc6a39cf9fe90c2694687a9c311f6e"


def _manifest():
    return json.loads((MEDIA / "manifest.json").read_text(encoding="utf-8"))


def _clip_data(clip):
    """(rows by frame, pts) straight from the clip's prepared files."""
    with open(MEDIA / clip["detections"], newline="", encoding="utf-8-sig") as handle:
        rows = {int(r["frame"]): r["detected"] == "True" for r in csv.DictReader(handle)}
    pts = json.loads((MEDIA / clip["frame_times"]).read_text(encoding="utf-8"))["pts_s"]
    return rows, pts


def reference_stats(clip):
    """Independent Python version of js/stats.js computeClipStats."""
    rows, pts = _clip_data(clip)
    invalid = [s for s in clip.get("segments", []) if s["kind"] == "invalid"]
    in_invalid = lambda k: any(s["start_frame"] <= k <= s["end_frame"] for s in invalid)
    analysed = {k: d for k, d in rows.items() if 0 <= k < len(pts)}
    valid = {k: d for k, d in analysed.items() if not in_invalid(k)}
    gaps = sorted(b - a for a, b in zip(pts, pts[1:]))
    detected, valid_detected = sum(analysed.values()), sum(valid.values())
    return {"analysed": len(analysed), "detected": detected, "not_detected": len(analysed) - detected,
            "rate": round(100 * detected / len(analysed), 1),
            "duration_s": round(pts[-1] + gaps[len(gaps) // 2], 2), "has_invalid": bool(invalid),
            "valid_frames": len(valid), "valid_detected": valid_detected,
            "valid_rate": round(100 * valid_detected / len(valid), 1) if valid else None}


@needs_media
def test_bench_media_is_byte_identical_to_the_submission():
    for rel, digest in BENCH_SHA256.items():
        assert hashlib.sha256((MEDIA / rel).read_bytes()).hexdigest() == digest, rel


@needs_media
def test_manifest_lists_three_labelled_recordings_with_verified_counts():
    clips = {c["id"]: c for c in _manifest()["clips"]}
    assert set(clips) == set(EXPECTED)
    for cid, want in EXPECTED.items():
        clip = clips[cid]
        rows, pts = _clip_data(clip)
        assert len(pts) == clip["frame_count"] == want["frames"], cid
        assert len(rows) == clip["detection_rows"] == want["frames"], cid
        assert sum(rows.values()) == clip["detected_frames"] == want["detected"], cid
        assert (clip["dictionary"], clip["marker_id"]) == ("DICT_4X4_50", 0)
        assert clip["environment"] == want["environment"] and clip["camera"] == want["camera"]
    assert clips["katamaran_10"]["label"].startswith("Bench")
    assert clips["camera_stable"]["label"].startswith("Bench")
    water = clips["water_controlled"]
    assert water["label"] == "Water Tank — Controlled Motion"
    assert water["camera_description"] == "Handheld, approximately stationary camera"
    assert "tripod" not in json.dumps(water).lower()
    assert water["segments"] == [] and water["default_range"] is None
    times = json.loads((MEDIA / water["frame_times"]).read_text(encoding="utf-8"))
    assert times["video_sha256"] == WATER_VIDEO_SHA256
    assert hashlib.sha256((MEDIA / water["video"]).read_bytes()).hexdigest() == WATER_VIDEO_SHA256


@needs_media
def test_camera_stable_keeps_its_range_and_invalid_segment():
    clip = {c["id"]: c for c in _manifest()["clips"]}["camera_stable"]
    assert clip["default_range"] == {"start_s": 0.0, "end_s": 30.0, "first_frame": 0, "last_frame": 719}
    [seg] = clip["segments"]
    assert (seg["kind"], seg["annotation"], seg["start_frame"], seg["end_frame"]) == ("invalid", "manual", 769, 909)
    assert seg["label"] == "Invalid for vessel tracking — marker detached"


@needs_media
def test_reference_statistics_match_verified_values():
    clips = {c["id"]: c for c in _manifest()["clips"]}
    k10, cs, water = (reference_stats(clips[i]) for i in ("katamaran_10", "camera_stable", "water_controlled"))
    assert (k10["analysed"], k10["detected"], k10["rate"], k10["has_invalid"]) == (1007, 492, 48.9, False)
    assert (cs["analysed"], cs["detected"], cs["rate"]) == (910, 255, 28.0)
    assert (cs["valid_frames"], cs["valid_detected"], cs["valid_rate"]) == (769, 125, 16.3)
    assert (water["analysed"], water["detected"], water["not_detected"], water["rate"]) == (1767, 1532, 235, 86.7)
    assert (k10["duration_s"], cs["duration_s"], water["duration_s"]) == (42.0, 37.96, 73.64)


@needs_media
def test_presentation_jump_points_match_the_prepared_media():
    """Python version of js/presentation.js verifyPoint, run on every jump point."""
    clips = {c["id"]: c for c in _manifest()["clips"]}
    points = json.loads((DEMO_DIR / "presentation.json").read_text(encoding="utf-8"))["jump_points"]
    for p in points:
        clip = clips[p["clip"]]
        rows, pts = _clip_data(clip)
        k = p["frame"]
        assert 0 <= k < len(pts), p["id"]
        if p["range"] == "default":
            assert clip["default_range"]["first_frame"] <= k <= clip["default_range"]["last_frame"]
        assert abs(pts[k] - p["approx_s"]) <= 1.0, p["id"]
        assert rows[k] == p["expect"]["detected"], p["id"]
        invalid = any(s["start_frame"] <= k <= s["end_frame"] for s in clip["segments"] if s["kind"] == "invalid")
        assert invalid == p["expect"]["invalid"], p["id"]
    water = {p["frame"]: (p["title"], round(pts_s, 2)) for p in points if p["clip"] == "water_controlled"
             for pts_s in [_clip_data(clips["water_controlled"])[1][p["frame"]]]}
    assert water == {144: ("Floating vessel, marker detected", 6.04),
                     800: ("Hand-guided movement, marker detected", 33.36),
                     1100: ("Marker visible, detection lost", 45.84),
                     1370: ("Tilted marker, intermittent detection", 57.12)}
    assert [p["id"] for p in points[:4]] == ["closeup", "lost", "roll", "detached"]   # originals kept


def _find_browser():
    import shutil
    for path in (r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                 r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                 shutil.which("chromium"), shutil.which("google-chrome"), shutil.which("chrome")):
        if path and Path(path).exists():
            return path
    return None


def _rendered_page(tmp_path, query):
    """The detection tab's DOM after the page has loaded, from a headless browser."""
    import subprocess
    import threading
    import serve
    browser = _find_browser()
    if not browser:
        pytest.skip("no Chrome/Edge for the rendered-page check")
    server = serve.make_server(port=0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}/{query}"
        result = subprocess.run([browser, "--headless=new", "--disable-gpu", "--no-first-run",
                                 f"--user-data-dir={tmp_path / 'profile'}", "--mute-audio",
                                 "--virtual-time-budget=20000", "--dump-dom", url],
                                capture_output=True, text=True, encoding="utf-8", timeout=120)
    finally:
        server.shutdown()
        server.server_close()
    return result.stdout


@needs_media
@pytest.mark.parametrize("clip_id", list(EXPECTED))
def test_displayed_statistics_match_the_detection_csvs(tmp_path, clip_id):
    import re
    html = _rendered_page(tmp_path, f"?clip={clip_id}")
    clips = {c["id"]: c for c in _manifest()["clips"]}

    # Comparison chart: one row per recording (plus a valid-frames row where a segment is invalid).
    bars = {(m["clip"], m["kind"]): (int(m["det"]), int(m["frames"]), float(m["rate"])) for m in re.finditer(
        r'data-clip="(?P<clip>[^"]+)" data-kind="(?P<kind>\w+)"\s+data-detected="(?P<det>\d+)" '
        r'data-frames="(?P<frames>\d+)" data-rate="(?P<rate>[\d.]+)"', html)}
    expected_bars = {}
    for cid, clip in clips.items():
        ref = reference_stats(clip)
        expected_bars[(cid, "all")] = (ref["detected"], ref["analysed"], ref["rate"])
        if ref["has_invalid"]:
            expected_bars[(cid, "valid")] = (ref["valid_detected"], ref["valid_frames"], ref["valid_rate"])
    # On failure, show any loader error the page recorded for a recording ("unavailable" rows).
    assert bars == expected_bars, re.findall(r'data-clip="([^"]+)" title="([^"]*)"><span class="bar-name">', html)

    # Selected-recording panel: headline rate(s) and tiles.
    shown = dict(re.findall(r'data-stat="([\w-]+)">([^<]*)<', html))
    ref = reference_stats(clips[clip_id])
    assert shown["analysed"] == str(ref["analysed"])
    assert shown["detected"] == str(ref["detected"])
    assert shown["not-detected"] == str(ref["not_detected"])
    assert shown["rate"] == f"{ref['rate']:.1f}"
    assert shown["duration"] == f"{ref['duration_s']:.2f} s"
    if ref["has_invalid"]:
        assert shown["valid-frames"] == str(ref["valid_frames"])
        assert shown["valid-detected"] == str(ref["valid_detected"])
        assert shown["valid-rate"] == f"{ref['valid_rate']:.1f}"
        assert "detection rate, all frames" in html and "valid frames only (excl. 769–909)" in html
    else:
        assert "valid-rate" not in shown

    # Recording steps (bench -> water): a clip with an invalid segment shows its valid-frames rate, labelled.
    steps = re.findall(r'data-step="([^"]+)".*?<span class="step-id">([^<]*)</span>\s*'
                       r'<span class="step-rate">([\d.]+)<small>%</small></span>', html, re.S)
    expected_steps = []
    for cid, clip in clips.items():
        r = reference_stats(clip)
        expected_steps.append((cid, cid + (" · valid frames" if r["has_invalid"] else ""),
                               f"{r['valid_rate'] if r['has_invalid'] else r['rate']:.1f}"))
    assert steps == expected_steps
    assert f'id="stats-title">{clips[clip_id]["label"]}<' in html
    assert "they are not direct measures of vessel stability" in html


@needs_media
@pytest.mark.parametrize("clip_id", list(EXPECTED))
def test_showcase_view_statistics_match_the_detection_csvs(tmp_path, clip_id):
    """Showcase View: headline rate and compact chart come from the same CSVs; invalid frames stay excluded and labelled."""
    import re
    html = _rendered_page(tmp_path, f"?view=showcase&clip={clip_id}")
    clips = {c["id"]: c for c in _manifest()["clips"]}
    assert re.search(r'<body[^>]*class="[^"]*\bshowcase\b', html), "showcase view not applied"
    assert 'id="view-showcase" aria-pressed="true"' in html

    ref = reference_stats(clips[clip_id])
    shown = dict(re.findall(r'data-sc="([\w-]+)">([^<]*)<', html))
    if ref["has_invalid"]:
        assert (shown["rate"], shown["detected"], shown["frames"]) == (
            f"{ref['valid_rate']:.1f}", str(ref["valid_detected"]), str(ref["valid_frames"]))
        assert shown["all-rate"] == f"{ref['rate']:.1f}"
        assert "excluded: marker detached" in html
    else:
        assert (shown["rate"], shown["detected"], shown["frames"]) == (
            f"{ref['rate']:.1f}", str(ref["detected"]), str(ref["analysed"]))
        assert "all-rate" not in shown

    bars = re.findall(r'data-sc-clip="([^"]+)"\s+data-sc-rate="([\d.]+)" data-sc-detected="(\d+)" data-sc-frames="(\d+)"', html)
    expected = []
    for cid, clip in clips.items():
        r = reference_stats(clip)
        expected.append((cid, f"{r['valid_rate'] if r['has_invalid'] else r['rate']:.1f}",
                         str(r["valid_detected"] if r["has_invalid"] else r["detected"]),
                         str(r["valid_frames"] if r["has_invalid"] else r["analysed"])))
    assert bars == expected
    assert html.count("they are not direct measures of vessel stability") >= 2      # both views keep the note
    assert "not a hydrodynamic simulation" in html


def test_vendored_three_js_matches_recorded_checksums():
    vendor = DEMO_DIR / "vendor" / "three"
    lines = [line.split() for line in (vendor / "VERSION.txt").read_text().splitlines()
             if len(line.split()) >= 2 and len(line.split()[0]) == 64]
    assert len(lines) == 4
    for digest, name, *_ in lines:
        assert hashlib.sha256((vendor / name).read_bytes()).hexdigest() == digest, name
