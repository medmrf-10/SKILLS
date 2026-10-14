#!/usr/bin/env python3
"""
Deep 6-Point Quality Scanner for Curated Sheikhs.

Detects:
1. Off-topic / foreign unclassified videos inside structured series (videos not in the raw playlist(s) of the series).
2. Short clips (< 300s or titled 'مقطع'/'برومو'/'تشويقة'/'إعلان'/'فائدة') mixed into long-form series (median >= 900s).
3. Numbering resets, backward jumps, or large gaps in display_no among main lessons.
4. Title-number vs display_no mismatches (where title has explicit الدرس X / الحلقة X / المجلس X != display_no).
5. Inverted parent-child duration anomalies (where Parent < 300s and Child >= 300s).
6. Orphan children or invalid parent_yt_id links.

Usage:
    python3 deep_scanner_all.py [--verbose] [sheikh_id ...]
"""

import json
from pathlib import Path
import re
import statistics
import sys

ROOT = (
    Path.cwd()
    if (Path.cwd() / "data/curated_sheikhs").exists()
    else Path(__file__).resolve().parents[4]
)
CURATED_DIR = ROOT / "data/curated_sheikhs"

AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")


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


def scan_sheikh(sh: str, verbose: bool = False):
    cur_path = CURATED_DIR / f"{sh}.json"
    raw_path = CURATED_DIR / f"{sh}_raw.json"
    cur = json.load(open(cur_path, encoding="utf-8"))
    raw = json.load(open(raw_path, encoding="utf-8")) if raw_path.exists() else {}

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
                if (
                    isinstance(last_parent_dur, (int, float))
                    and 0 < last_parent_dur < 300
                    and isinstance(dur, (int, float))
                    and dur >= 300
                ):
                    flaws.append(
                        f"  [INVERTED_PARENT_CHILD] idx={idx}/{len(lessons)} parent_dur={last_parent_dur}s < child_dur={dur}s | {yt} | {t}"
                    )
            else:
                last_parent_yt = yt
                last_parent_dur = dur

            if not is_c and disp not in {"مقدمة", "برومو", "فهرس", "ختام"}:
                if (
                    not is_general
                    and med_dur >= 900
                    and isinstance(dur, (int, float))
                    and 0 < dur < 300
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


if __name__ == "__main__":
    targets = sys.argv[1:]
    verbose = "--verbose" in targets
    targets = [t for t in targets if t != "--verbose"]
    if not targets:
        targets = [
            "omari",
            "asimi",
            "alihani",
            "hawwa",
            "bardoni",
            "sariri",
            "sayed",
            "bouti",
            "gomaa",
            "kamali",
            "jifri",
            "shaarawy",
            "samarrai",
            "hashemi",
            "dedew",
            "hafiz",
        ]
    for sh in targets:
        scan_sheikh(sh, verbose=verbose)
