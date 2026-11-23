"""Prepare local media for the SmartTrim V5 Test Replay demo (no internet needed).

Copies a video and its ArUco detection CSV (from vision/aruco_check.py)
into demo/media/, writes the exact per-frame
presentation timestamps read from the MP4 file, and records everything in
demo/media/manifest.json. Optionally extracts the V5 CAD preview mesh.

Raw source videos stay outside the repository; the prepared copies in
demo/media/ are committed so the demo runs from a clone or GitHub Pages.

Usage:
    python demo/prepare_media.py --video VIDEO.mp4 --detections DETECTIONS.csv \
        --clip-id katamaran_10 --label "katamaran_10 (moving camera)" --camera moving
    python demo/prepare_media.py --cad-zip V5_CAD.zip
"""
import argparse
import csv
import hashlib
import json
import math
import shutil
import struct
import sys
import zipfile
from pathlib import Path

DEMO_DIR = Path(__file__).resolve().parent
DEFAULT_MEDIA = DEMO_DIR / "media"
CAD_MEMBER = "smarttrim/V5_SLEEK_CAD/SmartTrim_V5_COMPLETE_Assembly_PREVIEW_ONLY.stl"
REQUIRED_DETECTION_COLUMNS = ["frame", "time_s", "detected", "marker_id",
                              "c0_x", "c0_y", "c1_x", "c1_y", "c2_x", "c2_y", "c3_x", "c3_y"]
CORNER_MARGIN_PX = 5.0


class MediaError(ValueError):
    """Input files are missing, inconsistent, or not in the expected format."""


# ---------------------------------------------------------------------------
# Minimal MP4 reader: per-frame presentation times and rotation of the video track
# ---------------------------------------------------------------------------
_CONTAINERS = {b"moov", b"trak", b"mdia", b"minf", b"stbl", b"edts"}


def _boxes(data, start, end):
    pos = start
    while pos + 8 <= end:
        size, kind = struct.unpack(">I4s", data[pos:pos + 8])
        header = 8
        if size == 1:
            size = struct.unpack(">Q", data[pos + 8:pos + 16])[0]
            header = 16
        elif size == 0:
            size = end - pos
        if size < header or pos + size > end:
            raise MediaError(f"malformed MP4 box {kind!r} at byte {pos}")
        yield kind, pos + header, pos + size
        pos += size


def _find(data, start, end, kind):
    for k, s, e in _boxes(data, start, end):
        if k == kind:
            return s, e
    return None


def _track_info(data, trak):
    s, e = trak
    mdia = _find(data, s, e, b"mdia")
    if mdia is None:
        return None
    hdlr = _find(data, *mdia, b"hdlr")
    if hdlr is None or data[hdlr[0] + 8:hdlr[0] + 12] != b"vide":
        return None
    return {"trak": trak, "mdia": mdia}


def mp4_video_frame_times(path):
    """Presentation time (s) of every frame of the first video track, in display order.

    Applies the composition offsets (ctts) and the edit list (elst), as players do.
    Returns (times, info) where info has timescale, rotation_deg, width and height
    as stored (before rotation).
    """
    data = Path(path).read_bytes()
    moov = _find(data, 0, len(data), b"moov")
    if moov is None:
        raise MediaError("no 'moov' box: not an MP4/MOV file, or the file is incomplete")
    mvhd = _find(data, *moov, b"mvhd")
    movie_timescale = None
    if mvhd is not None:
        version = data[mvhd[0]]
        offset = mvhd[0] + (20 if version == 1 else 12)
        movie_timescale = struct.unpack(">I", data[offset:offset + 4])[0]
    track = None
    for kind, s, e in _boxes(data, *moov):
        if kind == b"trak":
            track = _track_info(data, (s, e))
            if track:
                break
    if track is None:
        raise MediaError("no video track found")

    mdhd = _find(data, *track["mdia"], b"mdhd")
    version = data[mdhd[0]]
    offset = mdhd[0] + (20 if version == 1 else 12)
    timescale = struct.unpack(">I", data[offset:offset + 4])[0]

    tkhd = _find(data, *track["trak"], b"tkhd")
    version = data[tkhd[0]]
    matrix_at = tkhd[0] + (4 + 8 + 8 + 4 + 4 + 8 if version == 1 else 4 + 4 + 4 + 4 + 4 + 4) + 16
    a, b = struct.unpack(">ii", data[matrix_at:matrix_at + 8])
    rotation = int(round(math.degrees(math.atan2(b / 65536.0, a / 65536.0)))) % 360
    width, height = struct.unpack(">II", data[matrix_at + 36:matrix_at + 44])
    width, height = width >> 16, height >> 16

    minf = _find(data, *track["mdia"], b"minf")
    stbl = _find(data, *minf, b"stbl")
    stts = _find(data, *stbl, b"stts")
    if stts is None:
        raise MediaError("video track has no sample timing table (stts)")
    count = struct.unpack(">I", data[stts[0] + 4:stts[0] + 8])[0]
    decode, t = [], 0
    for i in range(count):
        n, delta = struct.unpack(">II", data[stts[0] + 8 + 8 * i:stts[0] + 16 + 8 * i])
        for _ in range(n):
            decode.append(t)
            t += delta
    offsets = [0] * len(decode)
    ctts = _find(data, *stbl, b"ctts")
    if ctts is not None:
        signed = data[ctts[0]] == 1
        count = struct.unpack(">I", data[ctts[0] + 4:ctts[0] + 8])[0]
        k = 0
        for i in range(count):
            n, value = struct.unpack(">I" + ("i" if signed else "I"),
                                     data[ctts[0] + 8 + 8 * i:ctts[0] + 16 + 8 * i])
            for _ in range(n):
                if k < len(offsets):
                    offsets[k] = value
                k += 1

    # Edit list: an initial empty edit delays the track; media_time shifts it.
    delay_s, media_start = 0.0, 0
    edts = _find(data, *track["trak"], b"edts")
    elst = _find(data, *edts, b"elst") if edts is not None else None
    if elst is not None:
        version = data[elst[0]]
        count = struct.unpack(">I", data[elst[0] + 4:elst[0] + 8])[0]
        pos = elst[0] + 8
        for _ in range(count):
            if version == 1:
                duration, media_time = struct.unpack(">Qq", data[pos:pos + 16])
                pos += 20
            else:
                duration, media_time = struct.unpack(">Ii", data[pos:pos + 8])
                pos += 12
            if media_time == -1:
                delay_s += duration / (movie_timescale or timescale)
            else:
                media_start = media_time
                break
    times = sorted((d + o - media_start) / timescale + delay_s for d, o in zip(decode, offsets))
    return times, {"timescale": timescale, "rotation_deg": rotation,
                   "stored_width": width, "stored_height": height}


# ---------------------------------------------------------------------------
# Detection CSV checks
# ---------------------------------------------------------------------------
def load_detections(path, frame_count, width, height):
    """Read and validate an aruco_check.py CSV against the upright video size."""
    with open(path, newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        missing = [c for c in REQUIRED_DETECTION_COLUMNS if c not in (reader.fieldnames or [])]
        if missing:
            raise MediaError(f"detection CSV is missing columns: {', '.join(missing)}")
        rows = list(reader)
    frames, detected = set(), 0
    for row in rows:
        try:
            frame = int(row["frame"])
        except ValueError:
            raise MediaError(f"bad frame index {row['frame']!r}") from None
        if not 0 <= frame < frame_count:
            raise MediaError(f"frame {frame} is outside the video's {frame_count} frames")
        if frame in frames:
            raise MediaError(f"frame {frame} appears twice")
        frames.add(frame)
        if row["detected"] == "True":
            detected += 1
            for i in range(4):
                x, y = float(row[f"c{i}_x"]), float(row[f"c{i}_y"])
                if not (-CORNER_MARGIN_PX <= x <= width + CORNER_MARGIN_PX
                        and -CORNER_MARGIN_PX <= y <= height + CORNER_MARGIN_PX):
                    raise MediaError(
                        f"frame {frame} corner {i} ({x:.1f}, {y:.1f}) lies outside the upright "
                        f"{width}x{height} frame; was the CSV made from unrotated frames?")
    return {"rows": len(rows), "detected": detected, "frames_covered": len(frames)}


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_manifest(media):
    path = media / "manifest.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"clips": [], "cad_mesh": None, "shared_timeline_links": []}


def _save_manifest(media, manifest):
    (media / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def _range_frames(times, start_s, end_s):
    """First and last frame shown within [start_s, end_s] seconds of video time."""
    inside = [i for i, t in enumerate(times) if start_s - 1e-9 <= t <= end_s + 1e-9]
    if not inside:
        raise MediaError(f"no frames between {start_s} s and {end_s} s")
    return inside[0], inside[-1]


def build_segments(times, invalid_segments):
    """[(start_frame, end_frame, label, note)] -> manifest segments, with times."""
    segments = []
    for start, end, label, note in invalid_segments or []:
        start, end = int(start), int(end)
        if not 0 <= start <= end < len(times):
            raise MediaError(f"invalid segment frames {start}-{end} are outside 0-{len(times) - 1}")
        if not str(label).strip():
            raise MediaError("an invalid segment needs a label")
        # Segments come from a person's frame-by-frame review, not from the detector.
        segments.append({"kind": "invalid", "annotation": "manual",
                         "start_frame": start, "end_frame": end,
                         "start_s": round(times[start], 6), "end_s": round(times[end], 6),
                         "label": str(label).strip(), "note": note or ""})
    return segments


def add_clip(video, detections, clip_id, label, camera, media=DEFAULT_MEDIA,
             dictionary="DICT_4X4_50", marker_id=0, marker_mm=40.0,
             default_range_s=None, invalid_segments=None,
             environment=None, camera_description=None):
    video, detections = Path(video), Path(detections)
    if not video.is_file():
        raise MediaError(f"video not found: {video}")
    if not detections.is_file():
        raise MediaError(f"detection CSV not found: {detections}")
    times, info = mp4_video_frame_times(video)
    rotated = info["rotation_deg"] in (90, 270)
    width = info["stored_height"] if rotated else info["stored_width"]
    height = info["stored_width"] if rotated else info["stored_height"]
    summary = load_detections(detections, len(times), width, height)
    default_range = None
    if default_range_s is not None:
        start_s, end_s = map(float, default_range_s)
        if not 0 <= start_s < end_s:
            raise MediaError("--default-range needs 0 <= START < END seconds")
        first, last = _range_frames(times, start_s, end_s)
        default_range = {"start_s": start_s, "end_s": end_s,
                         "first_frame": first, "last_frame": last}
    segments = build_segments(times, invalid_segments)

    target = media / clip_id
    target.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(video, target / "video.mp4")
    shutil.copyfile(detections, target / "detections.csv")
    nominal_fps = (len(times) - 1) / (times[-1] - times[0]) if len(times) > 1 else None
    durations = [b - a for a, b in zip(times, times[1:])]
    frame_times = {
        "source_video": video.name, "video_sha256": _sha256(video),
        "frame_count": len(times), "upright_width": width, "upright_height": height,
        "rotation_deg": info["rotation_deg"], "timescale": info["timescale"],
        "pts_s": [round(t, 6) for t in times],
        "min_frame_interval_s": round(min(durations), 6) if durations else None,
        "max_frame_interval_s": round(max(durations), 6) if durations else None,
        "note": ("pts_s are the presentation times stored in the MP4. The detection CSV's "
                 "time_s column is nominal (frame / fps); the demo maps video time to "
                 "frames with pts_s."),
    }
    (target / "frame_times.json").write_text(json.dumps(frame_times), encoding="utf-8")

    manifest = _load_manifest(media)
    manifest["clips"] = [c for c in manifest["clips"] if c["id"] != clip_id]
    # Optional descriptive metadata (where it was filmed, how the camera was held):
    # stored only when given, so clips prepared without them are unchanged.
    extra = {}
    if environment and str(environment).strip():
        extra["environment"] = str(environment).strip()
    if camera_description and str(camera_description).strip():
        extra["camera_description"] = str(camera_description).strip()
    manifest["clips"].append({
        "id": clip_id, "label": label, "camera": camera, **extra,
        "video": f"{clip_id}/video.mp4", "detections": f"{clip_id}/detections.csv",
        "frame_times": f"{clip_id}/frame_times.json",
        "dictionary": dictionary, "marker_id": marker_id, "marker_mm": marker_mm,
        "detection_rows": summary["rows"], "detected_frames": summary["detected"],
        "frame_count": len(times),
        "default_range": default_range,
        "segments": segments,
    })
    _save_manifest(media, manifest)
    return {**summary, "frame_count": len(times), "width": width, "height": height,
            "rotation_deg": info["rotation_deg"], "nominal_fps": nominal_fps,
            "min_interval_s": frame_times["min_frame_interval_s"],
            "max_interval_s": frame_times["max_frame_interval_s"],
            "default_range": default_range, "segments": segments}


# ---------------------------------------------------------------------------
# CAD preview mesh
# ---------------------------------------------------------------------------
def stl_bounds(data):
    """Bounds of a binary STL as ((xmin, ymin, zmin), (xmax, ymax, zmax))."""
    if len(data) < 84:
        raise MediaError("STL file is too short")
    count = struct.unpack("<I", data[80:84])[0]
    if 84 + 50 * count != len(data):
        raise MediaError("not a binary STL (size does not match the triangle count)")
    lo, hi = [math.inf] * 3, [-math.inf] * 3
    for i in range(count):
        base = 84 + 50 * i + 12
        for v in range(3):
            xyz = struct.unpack("<3f", data[base + 12 * v:base + 12 * v + 12])
            for axis in range(3):
                lo[axis] = min(lo[axis], xyz[axis])
                hi[axis] = max(hi[axis], xyz[axis])
    return tuple(lo), tuple(hi)


def add_cad_mesh(media=DEFAULT_MEDIA, zip_path=None, stl_path=None):
    if zip_path:
        with zipfile.ZipFile(zip_path) as archive:
            try:
                data = archive.read(CAD_MEMBER)
            except KeyError:
                raise MediaError(f"{CAD_MEMBER} not found in {zip_path}") from None
        source = f"{Path(zip_path).name}:{CAD_MEMBER}"
    elif stl_path:
        data = Path(stl_path).read_bytes()
        source = Path(stl_path).name
    else:
        raise MediaError("give --cad-zip or --cad-stl")
    lo, hi = stl_bounds(data)
    length = hi[0] - lo[0]
    if not (190 <= length <= 210 and lo[2] > -1 and abs(lo[0] + hi[0]) < 2):
        raise MediaError(f"mesh bounds {lo} .. {hi} do not look like the V5 assembly "
                         "(x -100..+100 mm, keel at z = 0)")
    (media / "cad").mkdir(parents=True, exist_ok=True)
    (media / "cad" / "v5_preview.stl").write_bytes(data)
    manifest = _load_manifest(media)
    manifest["cad_mesh"] = {
        "path": "cad/v5_preview.stl", "source": source,
        "label": "V5 CAD preview mesh (visual only, nominal geometry)",
        "bounds_mm": [list(map(lambda v: round(v, 2), lo)), list(map(lambda v: round(v, 2), hi))],
        "axes": "CAD: x bow +, z up from keel; shown with three.js X bow, Y up, Z starboard",
    }
    _save_manifest(media, manifest)
    return manifest["cad_mesh"]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--video")
    parser.add_argument("--detections")
    parser.add_argument("--clip-id")
    parser.add_argument("--label")
    parser.add_argument("--camera", choices=("moving", "fixed"), default="moving")
    parser.add_argument("--environment", help='where the clip was filmed, e.g. "Bench" or "Water tank"')
    parser.add_argument("--camera-description",
                        help='how the camera was held, e.g. "Handheld, approximately stationary camera"')
    parser.add_argument("--dictionary", default="DICT_4X4_50")
    parser.add_argument("--marker-id", type=int, default=0)
    parser.add_argument("--marker-mm", type=float, default=40.0)
    parser.add_argument("--default-range", nargs=2, type=float, metavar=("START_S", "END_S"),
                        help="review range the clip opens with, e.g. 0 30 (default: whole clip)")
    parser.add_argument("--invalid-segment", nargs=3, action="append", default=[],
                        metavar=("START_FRAME", "END_FRAME", "LABEL"),
                        help="label frames START..END (inclusive) as invalid; repeatable")
    parser.add_argument("--segment-note", default="",
                        help="evidence for the invalid segment(s), shown in the demo")
    parser.add_argument("--cad-zip")
    parser.add_argument("--cad-stl")
    parser.add_argument("--media-dir", default=str(DEFAULT_MEDIA))
    args = parser.parse_args(argv)
    media = Path(args.media_dir)
    media.mkdir(parents=True, exist_ok=True)
    did_something = False
    try:
        if args.video or args.detections:
            if not (args.video and args.detections and args.clip_id):
                raise MediaError("--video, --detections and --clip-id are needed together")
            r = add_clip(args.video, args.detections, args.clip_id,
                         args.label or args.clip_id, args.camera, media,
                         args.dictionary, args.marker_id, args.marker_mm,
                         default_range_s=args.default_range,
                         invalid_segments=[(a, b, label, args.segment_note)
                                           for a, b, label in args.invalid_segment],
                         environment=args.environment,
                         camera_description=args.camera_description)
            print(f"clip {args.clip_id}: {r['frame_count']} frames, upright {r['width']}x"
                  f"{r['height']} (rotation {r['rotation_deg']} deg); frame interval "
                  f"{r['min_interval_s'] * 1000:.1f}-{r['max_interval_s'] * 1000:.1f} ms; "
                  f"detection rows {r['rows']}, marker detected in {r['detected']}")
            if r["default_range"]:
                d = r["default_range"]
                print(f"  default range {d['start_s']:g}-{d['end_s']:g} s = frames "
                      f"{d['first_frame']}-{d['last_frame']}")
            for seg in r["segments"]:
                print(f"  {seg['kind']} frames {seg['start_frame']}-{seg['end_frame']} "
                      f"({seg['start_s']:.3f}-{seg['end_s']:.3f} s): {seg['label']}")
            did_something = True
        if args.cad_zip or args.cad_stl:
            mesh = add_cad_mesh(media, args.cad_zip, args.cad_stl)
            print(f"CAD mesh: {mesh['path']} from {mesh['source']}, bounds {mesh['bounds_mm']}")
            did_something = True
    except (MediaError, OSError, zipfile.BadZipFile) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if not did_something:
        parser.print_help()
        return 2
    print(f"manifest: {media / 'manifest.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
