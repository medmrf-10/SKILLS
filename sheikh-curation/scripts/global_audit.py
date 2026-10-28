#!/usr/bin/env python3
"""
Global Structural & Database Audit for Curated Scholar Archives.

Verifies:
1. Every child lesson (`is_child: true`) is preceded by a valid parent lesson and `parent_yt_id == last_parent_yt`.
2. In every series, main lesson `display_no` values are strictly monotonic (`n > prev_num`) with zero resets.
3. Non-numeric main `display_no` values are restricted to `{"مقدمة", "برومو", "فهرس", "ختام"}`.
4. In `long-form` series (median duration >= 900s, non-clip series), zero parent lessons `< min_duration` have child lessons `>= min_duration`.
5. Optional SQLite `curated.db` series and lesson counts match `<id>.json` 100% when the database is present.

Usage:
    python3 global_audit.py [--data-dir DIR] [--db-path FILE] [--min-duration 300] [--min-series-median 900] [--min-duration-contemplative 120] [target ...]
"""

import argparse
import json
import os
from pathlib import Path
import re
import sqlite3
import sys


def get_default_data_dir() -> Path:
    env_dir = os.environ.get("CURATION_DATA_DIR") or os.environ.get("CURATED_DIR")
    if env_dir:
        return Path(env_dir).expanduser().resolve()
    env_root = os.environ.get("CURATED_ROOT")
    if env_root:
        return (Path(env_root).expanduser() / "data" / "curated_sheikhs").resolve()
    return (Path.cwd() / "data" / "curated_sheikhs").resolve()


def get_default_db_path(data_dir: Path) -> Path:
    env_db = os.environ.get("CURATED_DB")
    if env_db:
        return Path(env_db).expanduser().resolve()
    return (data_dir.parent / "curated.db").resolve()


def resolve_target_paths(targets: list[str], data_dir: Path) -> list[tuple[str, Path]]:
    resolved: list[tuple[str, Path]] = []
    if not targets:
        if not data_dir.is_dir():
            return resolved
        for p in sorted(data_dir.glob("*.json")):
            if p.name.endswith("_raw.json"):
                continue
            resolved.append((p.stem, p))
        return resolved

    for t in targets:
        cand = Path(t)
        if cand.suffix == ".json" and cand.exists():
            resolved.append((cand.stem, cand))
        else:
            stem = t[:-5] if t.endswith(".json") else t
            resolved.append((stem, data_dir / f"{stem}.json"))
    return resolved


def parse_args():
    parser = argparse.ArgumentParser(
        description="Global Structural & Database Audit for Curated Scholar Archives."
    )
    parser.add_argument(
        "targets",
        nargs="*",
        help="Scholar IDs or JSON file paths to audit (default: all *.json in --data-dir)",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help="Directory containing curated <id>.json files (default: $CURATION_DATA_DIR or ./data/curated_sheikhs)",
    )
    parser.add_argument(
        "--db-path",
        type=Path,
        default=None,
        help="Path to SQLite curated.db (default: $CURATED_DB or <data-dir>/../curated.db)",
    )
    parser.add_argument(
        "--min-duration",
        type=int,
        default=300,
        help="Minimum duration (in seconds) for parent/main lessons (default: 300)",
    )
    parser.add_argument(
        "--min-series-median",
        type=int,
        default=900,
        help="Median duration threshold (in seconds) for long-form series (default: 900)",
    )
    parser.add_argument(
        "--min-duration-contemplative",
        type=int,
        default=120,
        help="Minimum duration (in seconds) for contemplative lessons (default: 120)",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    data_dir = args.data_dir.expanduser().resolve() if args.data_dir else get_default_data_dir()
    db_path = args.db_path.expanduser().resolve() if args.db_path else get_default_db_path(data_dir)

    targets = resolve_target_paths(args.targets, data_dir)
    if not targets:
        print(f"No curated JSON files found in {data_dir}. Pass --data-dir or target files.", file=sys.stderr)
        sys.exit(1)

    conn = sqlite3.connect(db_path) if db_path.is_file() else None
    cur = conn.cursor() if conn else None

    total_series = 0
    total_lessons = 0
    all_errors = []

    for sh, p in targets:
        if not p.is_file():
            all_errors.append(f"{sh}: file not found ({p})")
            continue
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        series_list = data.get("series", [])
        sh_lessons = 0
        sh_errs = []

        for _s_idx, s in enumerate(series_list, 1):
            sid = s.get("id")
            st = s.get("state")
            if st not in ("completed", "stopped", "ongoing"):
                sh_errs.append(f"{sid}: invalid series state={st!r}")
            lessons = s.get("lessons", [])
            sh_lessons += len(lessons)
            last_parent_yt = None
            last_parent_dur = None
            prev_num = None

            for l_idx, l in enumerate(lessons, 1):
                yt = l.get("yt_id")
                disp = str(l.get("display_no", ""))
                is_c = bool(l.get("is_child"))
                p_yt = l.get("parent_yt_id")
                dur = l.get("duration")

                if is_c:
                    if not last_parent_yt:
                        sh_errs.append(f"{sid} idx={l_idx}: child at start ({yt})")
                    elif p_yt != last_parent_yt:
                        sh_errs.append(
                            f"{sid} idx={l_idx}: parent_yt_id={p_yt} != {last_parent_yt} ({yt})"
                        )
                    t_child = l.get("title", "")
                    is_explicit_part2 = bool(
                        re.search(r"-\s*2\s*-|الجزء الثاني|\(2\)", t_child)
                    )
                    if (
                        isinstance(last_parent_dur, (int, float))
                        and 0 < last_parent_dur < args.min_duration
                        and isinstance(dur, (int, float))
                        and dur >= args.min_duration
                        and not is_explicit_part2
                    ):
                        sh_errs.append(
                            f"{sid} idx={l_idx}: inverted parent ({last_parent_dur}s) < child ({dur}s) ({yt})"
                        )
                else:
                    last_parent_yt = yt
                    last_parent_dur = dur
                    if disp.isdigit():
                        n = int(disp)
                        if prev_num is not None and n <= prev_num:
                            sh_errs.append(
                                f"{sid} idx={l_idx}: display_no reset {prev_num} -> {n} ({yt})"
                            )
                        prev_num = n
                    elif disp not in ("مقدمة", "برومو", "فهرس", "ختام"):
                        sh_errs.append(
                            f"{sid} idx={l_idx}: invalid main display_no={disp} ({yt})"
                        )

        db_info = ""
        if cur is not None:
            cur.execute("SELECT COUNT(*) FROM series WHERE sheikh_id=?", (sh,))
            db_s_cnt = cur.fetchone()[0]
            cur.execute(
                "SELECT COUNT(*) FROM lessons l JOIN series s ON l.series_id=s.id WHERE s.sheikh_id=?",
                (sh,),
            )
            db_l_cnt = cur.fetchone()[0]

            if db_s_cnt != len(series_list):
                sh_errs.append(f"DB series count {db_s_cnt} != JSON {len(series_list)}")
            if db_l_cnt != sh_lessons:
                sh_errs.append(f"DB lesson count {db_l_cnt} != JSON {sh_lessons}")
            db_info = f" (DB={db_s_cnt:3d}/{db_l_cnt:5d})"

        total_series += len(series_list)
        total_lessons += sh_lessons
        print(
            f"{sh:12s} | series={len(series_list):3d} | lessons={sh_lessons:5d}{db_info} | errors={len(sh_errs)}"
        )
        for e in sh_errs[:10]:
            print("  ERR:", e)
        all_errors.extend(sh_errs)

    if conn is not None:
        conn.close()

    print(
        f"\nTOTAL: {len(targets)} files | {total_series} series | {total_lessons} lessons | {len(all_errors)} errors"
    )
    sys.exit(1 if all_errors else 0)


if __name__ == "__main__":
    main()
