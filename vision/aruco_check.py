"""Standalone ArUco detection check on a video (classical computer vision, OpenCV).

Detects one ArUco marker in frames around a chosen time, writes an annotated frame
(corners numbered 0-3 in the marker's own order, plus the ID) and a CSV of the
detections. Optionally scans the whole clip for a detection rate. Frames are first
turned upright using the video's rotation flag, so pixel coordinates match the
video as it is normally viewed.

No pose is estimated: that needs a calibrated camera. Pixel sizes and the
mm-per-pixel scale apply only in the marker plane of that frame.

Usage:
    python vision/aruco_check.py --video katamaran_10.mp4 --time 6.0 \
        [--dictionary DICT_4X4_50] [--marker-id 0] [--marker-mm 40] [--window 1.0] [--scan]
"""
import argparse
import csv
import sys
from pathlib import Path

import cv2
import numpy as np

CORNER_NAMES = ("0 top-left", "1 top-right", "2 bottom-right", "3 bottom-left")  # marker's own order
CSV_FIELDS = ["frame", "time_s", "detected", "marker_id", "other_ids",
              "c0_x", "c0_y", "c1_x", "c1_y", "c2_x", "c2_y", "c3_x", "c3_y",
              "side_01_px", "side_12_px", "side_23_px", "side_30_px", "mean_side_px",
              "px_per_mm_in_marker_plane"]


def make_detector(dictionary_name):
    if not hasattr(cv2.aruco, dictionary_name):
        raise ValueError(f"unknown ArUco dictionary {dictionary_name!r}")
    dictionary = cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, dictionary_name))
    params = cv2.aruco.DetectorParameters()
    params.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
    return cv2.aruco.ArucoDetector(dictionary, params)


def detect(detector, frame, marker_id, marker_mm):
    """Return a dict for the wanted marker in this frame (detected False if absent)."""
    corners, ids, _ = detector.detectMarkers(frame)
    found = [] if ids is None else [int(i) for i in ids.ravel()]
    row = {"detected": False, "marker_id": "", "other_ids": " ".join(
        str(i) for i in found if i != marker_id), "corners": None}
    if marker_id not in found:
        return row
    c = corners[found.index(marker_id)].reshape(4, 2)
    sides = [float(np.linalg.norm(c[(i + 1) % 4] - c[i])) for i in range(4)]
    mean_side = sum(sides) / 4
    row.update(detected=True, marker_id=marker_id, corners=c, sides=sides, mean_side=mean_side,
               px_per_mm=mean_side / marker_mm)
    return row


def annotate(frame, row, label):
    out = frame.copy()
    if row["detected"]:
        c = row["corners"]
        cv2.polylines(out, [np.round(c).astype(np.int32)], True, (0, 220, 0), 2, cv2.LINE_AA)
        for i, (x, y) in enumerate(c):
            p = (int(round(x)), int(round(y)))
            cv2.circle(out, p, 6, (0, 0, 255), 2, cv2.LINE_AA)
            cv2.putText(out, str(i), (p[0] + 8, p[1] - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.8,
                        (0, 0, 255), 2, cv2.LINE_AA)
        centre = c.mean(axis=0)
        cv2.putText(out, f"ID {row['marker_id']}", (int(centre[0]) - 30, int(centre[1])),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 0, 255), 2, cv2.LINE_AA)
        detail = (f"ID {row['marker_id']} | mean side {row['mean_side']:.1f} px | "
                  f"{row['px_per_mm']:.2f} px/mm (marker plane)")
    else:
        detail = "marker not detected"
    cv2.rectangle(out, (0, 0), (out.shape[1], 52), (0, 0, 0), -1)
    for y, text in ((20, label), (44, detail)):
        cv2.putText(out, text, (8, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1,
                    cv2.LINE_AA)
    return out


def csv_row(index, fps, row):
    out = {"frame": index, "time_s": f"{index / fps:.3f}", "detected": row["detected"],
           "marker_id": row["marker_id"], "other_ids": row["other_ids"]}
    if row["detected"]:
        for i, (x, y) in enumerate(row["corners"]):
            out[f"c{i}_x"], out[f"c{i}_y"] = f"{x:.2f}", f"{y:.2f}"
        for name, value in zip(("side_01_px", "side_12_px", "side_23_px", "side_30_px"),
                               row["sides"]):
            out[name] = f"{value:.2f}"
        out["mean_side_px"] = f"{row['mean_side']:.2f}"
        out["px_per_mm_in_marker_plane"] = f"{row['px_per_mm']:.3f}"
    return out


def rotation_code(cap):
    """cv2.rotate code that shows the frame as the phone recorded it (None if upright)."""
    angle = int(round(cap.get(cv2.CAP_PROP_ORIENTATION_META) or 0)) % 360
    if cap.get(cv2.CAP_PROP_ORIENTATION_AUTO):
        return None                       # OpenCV already rotated the frames
    return {90: cv2.ROTATE_90_CLOCKWISE, 180: cv2.ROTATE_180,
            270: cv2.ROTATE_90_COUNTERCLOCKWISE}.get(angle)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--video", required=True)
    parser.add_argument("--time", type=float, default=6.0, help="seconds; frame to annotate")
    parser.add_argument("--window", type=float, default=1.0,
                        help="also log detections within +/- this many seconds")
    parser.add_argument("--dictionary", default="DICT_4X4_50")
    parser.add_argument("--marker-id", type=int, default=0)
    parser.add_argument("--marker-mm", type=float, default=40.0,
                        help="measured outer black square side in mm")
    parser.add_argument("--scan", action="store_true", help="scan the whole clip too")
    parser.add_argument("--out", help="output folder (default vision/output/aruco)")
    args = parser.parse_args(argv)

    cap = cv2.VideoCapture(args.video)
    if not cap.isOpened():
        print(f"error: could not open video {args.video}", file=sys.stderr)
        return 2
    fps = cap.get(cv2.CAP_PROP_FPS)
    frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    rotate = rotation_code(cap)
    detector = make_detector(args.dictionary)
    out_dir = Path(args.out) if args.out else Path(__file__).resolve().parent / "output" / "aruco"
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(args.video).stem

    target = min(frames - 1, max(0, round(args.time * fps)))
    half = round(args.window * fps)
    first, last = (0, frames - 1) if args.scan else (max(0, target - half),
                                                     min(frames - 1, target + half))
    cap.set(cv2.CAP_PROP_POS_FRAMES, first)
    rows, target_frame, target_row = [], None, None
    for index in range(first, last + 1):
        ok, frame = cap.read()
        if not ok:
            break
        if rotate is not None:
            frame = cv2.rotate(frame, rotate)        # upright, as the phone recorded it
        row = detect(detector, frame, args.marker_id, args.marker_mm)
        rows.append(csv_row(index, fps, row))
        if index == target:
            target_frame, target_row = frame, row
    cap.release()
    if target_frame is None:
        print(f"error: could not read frame {target}", file=sys.stderr)
        return 2

    label = f"{stem} frame {target} ({target / fps:.2f} s) | {args.dictionary}"
    annotated = annotate(target_frame, target_row, label)
    files = {"annotated": out_dir / f"{stem}_f{target:04d}_aruco.png"}
    cv2.imwrite(str(files["annotated"]), annotated)
    scope_tag = "all" if args.scan else f"f{target:04d}_pm{args.window:g}s"
    files["detections"] = out_dir / f"{stem}_aruco_detections_{scope_tag}.csv"
    with open(files["detections"], "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    print(f"video: {frames} frames at {fps:.3f} fps; frame size {target_frame.shape[1]}x"
          f"{target_frame.shape[0]}; turned upright using rotation flag: {rotate is not None}")
    if target_row["detected"]:
        c = target_row["corners"]
        print(f"frame {target} ({target / fps:.2f} s): ID {args.marker_id} detected; mean side "
              f"{target_row['mean_side']:.1f} px = {target_row['px_per_mm']:.2f} px/mm "
              f"in the marker plane")
        for name, (x, y) in zip(CORNER_NAMES, c):
            print(f"  corner {name}: ({x:.1f}, {y:.1f}) px")
    else:
        print(f"frame {target} ({target / fps:.2f} s): ID {args.marker_id} not detected")
    hits = sum(1 for r in rows if r["detected"])
    scope = "whole clip" if args.scan else f"{rows[0]['time_s']}-{rows[-1]['time_s']} s"
    print(f"detected in {hits}/{len(rows)} frames ({scope})")
    other = [r for r in rows if r["other_ids"]]
    if other:
        ids = sorted({i for r in other for i in r["other_ids"].split()})
        print(f"other marker IDs seen in {len(other)} frames: {', '.join(ids)}")
    for name, path in files.items():
        print(f"wrote {name}: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
