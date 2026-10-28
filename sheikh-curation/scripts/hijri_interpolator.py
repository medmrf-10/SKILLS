#!/usr/bin/env python3
"""
Hijri Date Parser & Playlist-Position Linear Interpolator.

Pure mathematical engine solving YouTube's 100-character title truncation problem
where older lessons lose their trailing Hijri date and get dumped at the end of
chronologically sorted series.

Features:
1. Hijri date extraction supporting `14[234]\\d` (1420-1449 AH), numeric `DD/MM/YYYY` or `DD-MM-YYYY`,
   named Hijri months, and dynamic `season_hijri_map` loaded from the scholar's JSON metadata.
2. Linear interpolation across raw playlists (`raw_series`) between confirmed dated anchors
   (`(i1, d1)` and `(i2, d2)`), choosing the playlist with the tightest bounding span (`|d2 - d1| + (i2 - i1)`).

Usage:
    python3 hijri_interpolator.py --input <curated.json> [--raw-input <raw.json>] [--output <out.json>] [--series N ...]
"""

import argparse
import json
import os
from pathlib import Path
import re
import sys

AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")

MONTHS = {
    "محرم": 1,
    "المحر": 1,
    "صفر": 2,
    "ربيع الأول": 3,
    "ربيع الاول": 3,
    "ربيع أول": 3,
    "ربيع اول": 3,
    "ربيع الآخر": 4,
    "ربيع الاخر": 4,
    "ربيع الثاني": 4,
    "ربيع ثاني": 4,
    "جمادى الأولى": 5,
    "جمادى الاولى": 5,
    "جماد أول": 5,
    "جمادى أول": 5,
    "جمادى الآخرة": 6,
    "جمادى الاخرة": 6,
    "جمادى الثانية": 6,
    "جماد ثاني": 6,
    "رجب": 7,
    "شعبان": 8,
    "رمضان": 9,
    "شوال": 10,
    "ذو القعدة": 11,
    "ذي القعدة": 11,
    "ذو الحجة": 12,
    "ذي الحجة": 12,
}


def get_default_data_dir() -> Path:
    env_dir = os.environ.get("CURATION_DATA_DIR") or os.environ.get("CURATED_DIR")
    if env_dir:
        return Path(env_dir).expanduser().resolve()
    env_root = os.environ.get("CURATED_ROOT")
    if env_root:
        return (Path(env_root).expanduser() / "data" / "curated_sheikhs").resolve()
    return (Path.cwd() / "data" / "curated_sheikhs").resolve()


def norm(s: str) -> str:
    return str(s).translate(AR_DIGITS)


def parse_hijri(title: str, season_hijri_map: dict | None = None):
    """Extract (year, month, day) in Hijri calendar from a video or playlist title."""
    t = norm(title)

    # 1. Numeric DD/MM/14YY or DD-MM-14YY
    m = re.search(r"(\d{1,2})\s*[/\-]\s*(\d{1,2})\s*[/\-]\s*(14[234]\d)", t)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1 <= mo <= 12 and 1 <= d <= 30:
            return (y, mo, d)

    # 2. Explicit 4-digit Hijri year 1420..1449
    ym = re.search(r"(14[234]\d)", t)
    if ym:
        y = int(ym.group(1))
        mo = 6
        for k, v in MONTHS.items():
            if k in t:
                mo = v
                break
        dm = re.search(
            r"(\d{1,2})\s+(?:من\s+)?(?:" + "|".join(MONTHS.keys()) + r")", t
        )
        d = int(dm.group(1)) if dm and 1 <= int(dm.group(1)) <= 30 else 15
        return (y, mo, d)

    # 3. Dynamic season_hijri_map from scholar configuration / metadata
    if season_hijri_map:
        for cat_name, mapping in season_hijri_map.items():
            clean_cat = cat_name.replace("_", " ")
            if clean_cat in t or cat_name in t:
                for num_key, y in mapping.items():
                    if re.search(rf"\b0*{re.escape(str(num_key))}\b", t):
                        mo = 9 if ("ملتقى" in clean_cat or "رمضان" in clean_cat) else 11
                        return (int(y), mo, 15)

    return None


def to_days(dt: tuple[int, int, int]) -> int:
    return dt[0] * 372 + dt[1] * 31 + dt[2]


def from_days(d: float) -> tuple[int, int, int]:
    y = int(d // 372)
    rem = int(d % 372)
    m = max(1, min(12, rem // 31))
    day = max(1, min(30, rem % 31))
    return (y, m, day)


def build_interpolated_dates(raw_data: dict, season_hijri_map: dict | None = None):
    """Return (explicit_dates, best_interp) dicts keyed by yt_id using linear interpolation."""
    explicit_dates = {}
    for uv in raw_data.get("unique_videos", []):
        dt = parse_hijri(uv["title"], season_hijri_map=season_hijri_map)
        if dt:
            explicit_dates[uv["yt_id"]] = dt

    best_interp = {}
    for rs in raw_data.get("raw_series", []):
        vids = rs.get("videos", [])
        pl_dt = parse_hijri(rs.get("title", ""), season_hijri_map=season_hijri_map)
        dated_pts = []
        for idx, v in enumerate(vids):
            dt = explicit_dates.get(v["yt_id"])
            if dt:
                dated_pts.append((idx, to_days(dt), dt))

        for idx, v in enumerate(vids):
            vid = v["yt_id"]
            if vid in explicit_dates:
                continue
            if dated_pts:
                prevs = [p for p in dated_pts if p[0] < idx]
                nexts = [p for p in dated_pts if p[0] > idx]
                if prevs and nexts:
                    i1, d1, _ = prevs[-1]
                    i2, d2, _ = nexts[0]
                    frac = (idx - i1) / (i2 - i1)
                    interp_d = d1 + frac * (d2 - d1)
                    span = abs(d2 - d1) + (i2 - i1)
                elif prevs:
                    i1, d1, _ = prevs[-1]
                    interp_d = d1 - 0.1 * (idx - i1)
                    span = 500 + (idx - i1)
                else:
                    i2, d2, _ = nexts[0]
                    interp_d = d2 + 0.1 * (i2 - idx)
                    span = 500 + (i2 - idx)
                if vid not in best_interp or span < best_interp[vid][0]:
                    best_interp[vid] = (
                        span,
                        interp_d,
                        from_days(interp_d),
                        rs.get("title", ""),
                    )
            elif pl_dt:
                d = to_days(pl_dt)
                if vid not in best_interp:
                    best_interp[vid] = (1000, d, pl_dt, rs.get("title", ""))

    return explicit_dates, best_interp


def parse_args():
    parser = argparse.ArgumentParser(
        description="Hijri Date Parser & Playlist-Position Linear Interpolator."
    )
    parser.add_argument(
        "target",
        nargs="?",
        help="Optional scholar ID or curated JSON path",
    )
    parser.add_argument(
        "--input",
        "-i",
        type=Path,
        default=None,
        help="Path to curated <id>.json file",
    )
    parser.add_argument(
        "--raw-input",
        "-r",
        type=Path,
        default=None,
        help="Path to raw <id>_raw.json file containing raw_series playlists",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=None,
        help="Optional path to write JSON interpolation results",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help="Directory containing <id>.json and <id>_raw.json (default: $CURATION_DATA_DIR or ./data/curated_sheikhs)",
    )
    parser.add_argument(
        "--series",
        "-s",
        type=int,
        nargs="*",
        default=[],
        help="1-based series indices to inspect",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    data_dir = args.data_dir.expanduser().resolve() if args.data_dir else get_default_data_dir()

    cur_path = args.input
    raw_path = args.raw_input
    if not cur_path and args.target:
        cand = Path(args.target)
        if cand.suffix == ".json" and cand.exists():
            cur_path = cand
        else:
            stem = args.target[:-5] if args.target.endswith(".json") else args.target
            cur_path = data_dir / f"{stem}.json"
            if not raw_path:
                raw_path = data_dir / f"{stem}_raw.json"

    if not cur_path or not cur_path.is_file():
        print("Error: valid --input <curated.json> or target ID is required.", file=sys.stderr)
        sys.exit(1)

    if not raw_path:
        raw_path = cur_path.parent / f"{cur_path.stem}_raw.json"

    with open(cur_path, encoding="utf-8") as f:
        cur = json.load(f)
    raw = {}
    if raw_path and raw_path.is_file():
        with open(raw_path, encoding="utf-8") as f:
            raw = json.load(f)

    season_map = cur.get("season_hijri_map")
    explicit_dates, best_interp = build_interpolated_dates(
        raw, season_hijri_map=season_map
    )
    print(
        f"[{cur_path.stem}] Explicit dates: {len(explicit_dates)} | Interpolated: {len(best_interp)}"
    )

    if args.output:
        out_payload = {
            "explicit_dates": {k: list(v) for k, v in explicit_dates.items()},
            "interpolated_dates": {
                k: {
                    "span": v[0],
                    "days": v[1],
                    "hijri_ymd": list(v[2]),
                    "source_playlist": v[3],
                }
                for k, v in best_interp.items()
            },
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(out_payload, f, ensure_ascii=False, indent=2)
        print(f"Saved interpolation output to {args.output}")

    target_series = (
        [(i, cur["series"][i - 1]) for i in args.series]
        if args.series
        else list(enumerate(cur.get("series", []), 1))
    )

    for si, s in target_series:
        undated_in_s = [
            (idx, l)
            for idx, l in enumerate(s.get("lessons", []), 1)
            if l["yt_id"] not in explicit_dates and not l.get("is_child")
        ]
        if not undated_in_s:
            continue
        print(
            f"\n=== [{si:02d}] {s.get('id')} — {s.get('title') or s.get('name')} ({len(undated_in_s)} undated main lessons) ==="
        )
        for idx, l in undated_in_s[:25]:
            vid = l["yt_id"]
            bi = best_interp.get(vid)
            print(
                f"  idx={idx:03d} | dur={l.get('duration')}s | {vid} | {l['title'][:55]} -> {bi[2] if bi else None} (via {bi[3][:28] if bi else None})"
            )


if __name__ == "__main__":
    main()
