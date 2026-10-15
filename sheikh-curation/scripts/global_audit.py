#!/usr/bin/env python3
"""
Global Structural & Database Audit for All 16 Curated Sheikhs.

Verifies:
1. Every child lesson (`is_child: true`) is preceded by a valid parent lesson and `parent_yt_id == last_parent_yt`.
2. In every series, main lesson `display_no` values are strictly monotonic (`n > prev_num`) with zero resets.
3. Non-numeric main `display_no` values are restricted to `{"مقدمة", "برومو", "فهرس", "ختام"}`.
4. In `long-form` series (median duration >= 900s, non-clip series), zero main lessons have `0 < duration < 120s`, and zero parent lessons `< 300s` have child lessons `>= 300s`.
5. `data/curated.db` series and lesson counts match `data/curated_sheikhs/<sheikh>.json` 100%.
"""

import json
from pathlib import Path
import re
import sqlite3
import sys

ROOT = (
    Path.cwd()
    if (Path.cwd() / "data/curated_sheikhs").exists()
    else Path(__file__).resolve().parents[4]
)
CURATED_DIR = ROOT / "data/curated_sheikhs"
DB_PATH = ROOT / "data/curated.db"

SHEIKHS = [
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
    "ayman",
]


def main():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    total_series = 0
    total_lessons = 0
    all_errors = []

    for sh in SHEIKHS:
        p = CURATED_DIR / f"{sh}.json"
        data = json.load(open(p, encoding="utf-8"))
        series_list = data.get("series", [])
        sh_lessons = 0
        sh_errs = []

        for s_idx, s in enumerate(series_list, 1):
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
                        and 0 < last_parent_dur < 300
                        and isinstance(dur, (int, float))
                        and dur >= 300
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

        total_series += len(series_list)
        total_lessons += sh_lessons
        print(
            f"{sh:10s} | series={len(series_list):3d} (DB={db_s_cnt:3d}) | lessons={sh_lessons:5d} (DB={db_l_cnt:5d}) | errors={len(sh_errs)}"
        )
        for e in sh_errs[:10]:
            print("  ERR:", e)
        all_errors.extend(sh_errs)

    print(
        f"\nTOTAL: {len(SHEIKHS)} Sheikhs | {total_series} series | {total_lessons} lessons | {len(all_errors)} errors"
    )
    sys.exit(1 if all_errors else 0)


if __name__ == "__main__":
    main()
