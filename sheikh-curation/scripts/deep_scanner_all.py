#!/usr/bin/env python3
"""
Deep 6-Point Quality Scanner for Curated Scholar Archives.

Detects:
1. Off-topic / foreign unclassified videos inside structured series (videos not in the raw playlist(s) of the series).
2. Short clips (< min_duration or titled 'مقطع'/'برومو'/'تشويقة'/'إعلان'/'فائدة') mixed into long-form series (median >= min_series_median).
3. Numbering resets, backward jumps, or large gaps in display_no among main lessons.
4. Title-number vs display_no mismatches (where title has explicit الدرس X / الحلقة X / المجلس X != display_no).
5. Inverted parent-child duration anomalies (where Parent < min_duration and Child >= min_duration).
6. Orphan children or invalid parent_yt_id links.

Usage:
    python3 deep_scanner_all.py [--data-dir DIR] [--verbose] [--min-duration 300] [--min-series-median 900] [--min-duration-contemplative 120] [target ...]
"""

import argparse
import json
import os
from pathlib import Path
import re
import statistics
import sys

AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")


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


def extract_explicit_num(title: str):
    t = norm(title)
    t = re.sub(r"\d{1,2}\s*[/\-]\s*\d{1,2}\s*[/\-]\s*\d{2,4}", " ", t)
    t = re.sub(r"\b14[234]\d\b|\b20[012]\d\b", " ", t)
    m = re.search(
        r"(?:الدرس|درس|الحلقة|حلقة|حـ|المجلس|مجلس|المحاضرة|محاضرة|لقاء|اللقاء)\s*(?:الـ?\s*)?\(?0*(\d{1,4})\)?",
        t,
    )
    if m:
        return int(m.group(1))
    return None


def resolve_target_paths(targets: list[str], data_dir: Path) -> list[tuple[str, Path, Path]]:
    resolved: list[tuple[str, Path, Path]] = []
    if not targets:
        if not data_dir.is_dir():
            return resolved
        for p in sorted(data_dir.glob("*.json")):
            if p.name.endswith("_raw.json"):
                continue
            stem = p.stem
            resolved.append((stem, p, data_dir / f"{stem}_raw.json"))
        return resolved

    for t in targets:
        cand = Path(t)
        if cand.suffix == ".json" and cand.exists():
            stem = cand.stem[:-4] if cand.stem.endswith("_raw") else cand.stem
            cur_p = cand if not cand.stem.endswith("_raw") else cand.parent / f"{stem}.json"
            raw_p = cand.parent / f"{stem}_raw.json"
            resolved.append((stem, cur_p, raw_p))
        else:
            stem = t[:-5] if t.endswith(".json") else t
            resolved.append((stem, data_dir / f"{stem}.json", data_dir / f"{stem}_raw.json"))
    return resolved


def scan_sheikh(
    sh: str,
    cur_path: Path,
    raw_path: Path,
    verbose: bool = False,
    min_duration: int = 300,
    min_series_median: int = 900,
    min_duration_contemplative: int = 120,
) -> int:
    if not cur_path.is_file():
        print(f"[SKIP] File not found: {cur_path}", file=sys.stderr)
        return 0

    with open(cur_path, encoding="utf-8") as f:
        cur = json.load(f)
    raw = {}
    if raw_path.is_file():
        with open(raw_path, encoding="utf-8") as f:
            raw = json.load(f)

    v_apps = {}
    v_durs = {}
    for v in raw.get("unique_videos", []):
        pls = [
            a["raw_series_id"]
            for a in v.get("appearances", [])
            if not a.get("is_unclassified")
        ]
        v_apps[v["yt_id"]] = pls
        if v.get("duration"):
            v_durs[v["yt_id"]] = v.get("duration")

    general_keywords = [
        "متفرقة",
        "متنوعة",
        "عامة",
        "فوائد",
        "مقاطع",
        "مقتطفات",
        "خطب",
        "محاضرات",
        "ندوات",
        "فتاوى",
        "لقاءات",
        "حوارات",
        "أدعية",
        "ابتهالات",
        "قصائد",
        "تلاوات",
        "مناجاة",
        "شهادات",
        "مرثيات",
        "كلمات",
        "رحلات",
        "زيارات",
        "فعاليات",
        "الدورات",
    ]

    series_reports = []
    for s_idx, s in enumerate(cur.get("series", []), 1):
        sid = s.get("id")
        sname = s.get("name") or s.get("title", "")
        lessons = s.get("lessons", [])
        is_general = any(w in sname for w in general_keywords)

        main_eps = [ep for ep in lessons if not ep.get("is_child")]
        durs = [
            (ep.get("duration") or v_durs.get(ep["yt_id"]))
            for ep in main_eps
            if isinstance(
                ep.get("duration") or v_durs.get(ep["yt_id"]), (int, float)
            )
            and (ep.get("duration") or v_durs.get(ep["yt_id"])) > 0
        ]
        med_dur = statistics.median(durs) if len(durs) >= 4 else 0

        pl_counts = {}
        for ep in lessons:
            for pid in v_apps.get(ep["yt_id"], []):
                pl_counts[pid] = pl_counts.get(pid, 0) + 1

        flaws = []
        last_parent_yt = None
        last_parent_dur = None

        for idx, ep in enumerate(lessons, 1):
            yt = ep["yt_id"]
            t = ep["title"]
            disp = str(ep.get("display_no", ""))
            dur = ep.get("duration") or v_durs.get(yt)
            is_c = bool(ep.get("is_child"))
            pls = v_apps.get(yt, [])
            is_unclass = yt in v_apps and len(pls) == 0

            if is_c:
                p_yt = ep.get("parent_yt_id")
                if not last_parent_yt or p_yt != last_parent_yt:
                    flaws.append(
                        f"  [ORPHAN_CHILD] idx={idx}/{len(lessons)} parent_yt_id={p_yt} != {last_parent_yt} | {yt} | {t}"
                    )
                is_explicit_part2 = bool(
                    re.search(r"-\s*2\s*-|الجزء الثاني|\(2\)", t)
                )
                if (
                    isinstance(last_parent_dur, (int, float))
                    and 0 < last_parent_dur < min_duration
                    and isinstance(dur, (int, float))
                    and dur >= min_duration
                    and not is_explicit_part2
                ):
                    flaws.append(
                        f"  [INVERTED_PARENT_CHILD] idx={idx}/{len(lessons)} parent_dur={last_parent_dur}s < child_dur={dur}s | {yt} | {t}"
                    )
            else:
                last_parent_yt = yt
                last_parent_dur = dur

            if not is_c and disp not in {"مقدمة", "برومو", "فهرس", "ختام"}:
                is_contemplative = any(
                    cw in sname for cw in ["تأمل", "ختم القرآن"]
                )
                effective_min_dur = (
                    min_duration_contemplative if is_contemplative else min_duration
                )
                if (
                    not is_general
                    and med_dur >= min_series_median
                    and isinstance(dur, (int, float))
                    and 0 < dur < effective_min_dur
                ):
                    flaws.append(
                        f"  [SHORT_IN_LONG] idx={idx}/{len(lessons)} disp={disp} dur={dur}s unclass={is_unclass} | {yt} | {t}"
                    )
                elif not is_general and (
                    any(
                        w in t
                        for w in [
                            "مقطع:",
                            "مقطع |",
                            "مقطع من",
                            "برومو",
                            "تشويقة",
                            "إعلان برنامج",
                        ]
                    )
                    or (
                        "#الدورة" in t
                        and "الدورة" not in sname
                        and "الدورات" not in sname
                    )
                ):
                    if med_dur >= 600:
                        flaws.append(
                            f"  [CLIP_TITLE_IN_SERIES] idx={idx}/{len(lessons)} disp={disp} dur={dur}s unclass={is_unclass} | {yt} | {t}"
                        )

                exp_n = extract_explicit_num(t)
                if exp_n is not None and disp.isdigit():
                    d_n = int(disp)
                    if (
                        exp_n != d_n
                        and abs(exp_n - d_n) <= 50
                        and not is_general
                    ):
                        flaws.append(
                            f"  [NUM_MISMATCH] idx={idx}/{len(lessons)} disp={disp} != title_num={exp_n} | {yt} | {t}"
                        )

        prev_n = None
        for idx, ep in enumerate(lessons, 1):
            if ep.get("is_child"):
                continue
            disp = str(ep.get("display_no", ""))
            if disp.isdigit():
                n = int(disp)
                if prev_n is not None:
                    if n <= prev_n:
                        flaws.append(
                            f"  [NUM_RESET] idx={idx}/{len(lessons)} disp={n} after {prev_n} | {ep['yt_id']} | {ep['title']}"
                        )
                    elif n - prev_n > 15:
                        flaws.append(
                            f"  [NUM_JUMP] idx={idx}/{len(lessons)} disp={n} after {prev_n} (+{n - prev_n}) | {ep['yt_id']} | {ep['title']}"
                        )
                prev_n = n

        if not is_general and pl_counts and len(lessons) >= 5:
            in_pl_flags = [len(v_apps.get(ep["yt_id"], [])) > 0 for ep in lessons]
            if sum(in_pl_flags) >= len(lessons) * 0.6:
                for idx in range(len(lessons) - 1, -1, -1):
                    ep = lessons[idx]
                    if len(v_apps.get(ep["yt_id"], [])) == 0:
                        flaws.append(
                            f"  [UNCLASS_TAIL] idx={idx+1}/{len(lessons)} disp={ep.get('display_no')} dur={ep.get('duration')}s | {ep['yt_id']} | {ep['title']}"
                        )
                    else:
                        break

        if flaws:
            series_reports.append((s_idx, sid, sname, len(lessons), flaws))

    print(
        f"=== {sh.upper()}: {len(cur.get('series', []))} series, {len(series_reports)} series with potential flaws ==="
    )
    for s_idx, sid, sname, lcnt, flaws in series_reports:
        print(
            f"\n[{s_idx:02d}] {sid} — {sname} ({lcnt} lessons): {len(flaws)} flags"
        )
        for fl in flaws[: (50 if verbose else 8)]:
            print(fl)
        if not verbose and len(flaws) > 8:
            print(f"  ... and {len(flaws) - 8} more flags")

    return len(series_reports)


def main():
    parser = argparse.ArgumentParser(
        description="Deep 6-Point Quality Scanner for Curated Scholar Archives."
    )
    parser.add_argument(
        "targets",
        nargs="*",
        help="Scholar IDs or JSON file paths to scan (default: all *.json in --data-dir)",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help="Directory containing curated <id>.json files (default: $CURATION_DATA_DIR or ./data/curated_sheikhs)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show verbose output (up to 50 flags per series)",
    )
    parser.add_argument(
        "--min-duration",
        type=int,
        default=300,
        help="Minimum duration (in seconds) for main lessons in standard long series (default: 300)",
    )
    parser.add_argument(
        "--min-series-median",
        type=int,
        default=900,
        help="Median duration threshold (in seconds) defining a long-form series (default: 900)",
    )
    parser.add_argument(
        "--min-duration-contemplative",
        type=int,
        default=120,
        help="Minimum duration (in seconds) for contemplative / reflection series (default: 120)",
    )
    args = parser.parse_args()

    data_dir = args.data_dir.expanduser().resolve() if args.data_dir else get_default_data_dir()
    resolved = resolve_target_paths(args.targets, data_dir)
    if not resolved:
        print(f"No curated JSON files found in {data_dir}. Pass --data-dir or target files.", file=sys.stderr)
        sys.exit(1)

    for sh, cur_path, raw_path in resolved:
        scan_sheikh(
            sh,
            cur_path=cur_path,
            raw_path=raw_path,
            verbose=args.verbose,
            min_duration=args.min_duration,
            min_series_median=args.min_series_median,
            min_duration_contemplative=args.min_duration_contemplative,
        )


if __name__ == "__main__":
    main()
