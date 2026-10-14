#!/usr/bin/env python3
"""
Hijri Date Parser & Playlist-Position Linear Interpolator.

Solves YouTube's 100-character title truncation problem where older lessons (1433-1445 AH)
lose their trailing Hijri date and get dumped at the end of chronologically sorted series
after 1447/1448 AH lessons.

Features:
1. Full Hijri date extraction supporting `14[234]\\d` (1420-1449 AH), numeric `DD/MM/YYYY` or `DD-MM-YYYY`,
   named Hijri months, and annual Dawrah / Multaqa ordinal-to-Hijri year mapping.
2. Linear interpolation across all official raw playlists (`raw_series`) in `<sheikh>_raw.json`,
   choosing the playlist with the tightest dated bounding span (`|d2 - d1| + (i2 - i1)`).

Usage:
    python3 hijri_interpolator.py <sheikh_id> [series_number ...]
"""

import json
from pathlib import Path
import re
import sys

ROOT = (
    Path.cwd()
    if (Path.cwd() / "data/curated_sheikhs").exists()
    else Path(__file__).resolve().parents[4]
)
CURATED_DIR = ROOT / "data/curated_sheikhs"

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

# Dar Al-Mustafa Summer Dawrah ordinal -> Hijri year (held in Dhu al-Qi'dah = month 11)
DAWRAH_WORDS = {
    "الثامنة عشرة": 1433,
    "التاسعة عشرة": 1434,
    "العشرين": 1435,
    "الحادية والعشرين": 1436,
    "الثانية والعشرين": 1437,
    "الثالثة والعشرين": 1438,
    "الرابعة والعشرين": 1439,
    "الخامسة والعشرين": 1440,
    "السادسة والعشرين": 1441,
    "السابعة والعشرين": 1442,
    "الثامنة والعشرين": 1443,
    "التاسعة والعشرين": 1444,
    "الثلاثين": 1445,
    "الحادية والثلاثين": 1447,
    "الثانية والثلاثين": 1448,
}

# Annual Du'at Multaqa in Ramadan -> Hijri year (month 9, day 21)
MULTAQA_WORDS = {
    "الخامس عشر": 1443,
    "السادس عشر": 1444,
    "السابع عشر": 1445,
    "الثامن عشر": 1446,
    "التاسع عشر": 1447,
    "العشرين": 1448,
    "العشرون": 1448,
}


def norm(s: str) -> str:
    return str(s).translate(AR_DIGITS)


def parse_hijri(title: str):
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

    # 3. Dawrah number or Arabic ordinal
    for w, y in DAWRAH_WORDS.items():
        if w in t and ("الدورة" in t or "دورة" in t):
            return (y, 11, 15)
    dm_num = re.search(r"(?:الدورة|دورة|#الدورة)\s*(?:الـ?\s*)?\(?(\d{2})\)?", t)
    if dm_num:
        dn = int(dm_num.group(1))
        if 15 <= dn <= 30:
            return (1415 + dn, 11, 15)
        if dn in (31, 32):
            return (1416 + dn, 11, 15)

    # 4. Multaqa Al-Du'at ordinal in Ramadan
    if "ملتقى الدعاة" in t:
        for w, y in MULTAQA_WORDS.items():
            if w in t:
                return (y, 9, 21)

    return None


def to_days(dt):
    return dt[0] * 372 + dt[1] * 31 + dt[2]


def from_days(d):
    y = int(d // 372)
    rem = int(d % 372)
    m = max(1, min(12, rem // 31))
    day = max(1, min(30, rem % 31))
    return (y, m, day)


def build_interpolated_dates(raw_data: dict):
    """Return (explicit_dates, best_interp) dicts keyed by yt_id."""
    explicit_dates = {}
    for uv in raw_data.get("unique_videos", []):
        dt = parse_hijri(uv["title"])
        if dt:
            explicit_dates[uv["yt_id"]] = dt

    best_interp = {}
    for rs in raw_data.get("raw_series", []):
        vids = rs.get("videos", [])
        pl_dt = parse_hijri(rs.get("title", ""))
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


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 hijri_interpolator.py <sheikh_id> [series_index ...]")
        sys.exit(1)

    sh = sys.argv[1]
    s_indices = [int(x) for x in sys.argv[2:]]

    raw = json.load(open(CURATED_DIR / f"{sh}_raw.json", encoding="utf-8"))
    cur = json.load(open(CURATED_DIR / f"{sh}.json", encoding="utf-8"))

    explicit_dates, best_interp = build_interpolated_dates(raw)
    print(
        f"[{sh}] Explicit dates: {len(explicit_dates)} | Interpolated: {len(best_interp)}"
    )

    target_series = (
        [(i, cur["series"][i - 1]) for i in s_indices]
        if s_indices
        else list(enumerate(cur["series"], 1))
    )

    for si, s in target_series:
        undated_in_s = [
            (idx, l)
            for idx, l in enumerate(s["lessons"], 1)
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
