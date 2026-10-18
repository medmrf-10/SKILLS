#!/usr/bin/env python3
"""
auto_curate_person.py — Automated 9-Stage Semantic Curation Engine (sheikh-curation v2.0).

Transforms `<person_id>_raw.json` (from `person-discovery-intake` or `curated_tools.py dump-sheikh`)
into a zero-error curated `<person_id>.json`, optional `curated.db` SQLite tables, and
`<output_series_dir>/<person_id>/sXXX/_meta.json` directory tree ready for `sheikh-series-pipeline v5`.

Implements all 9 Golden Stages deterministically:
  Stage 1: Duration import, video normalization, deduplication, and dead livestream purge (<= 15s).
  Stage 2: Semantic `Unclassified` routing (Arabic word boundaries, anti-collision rules) &
           isolation of guest speaker lectures and contest/award ceremonies.
  Stage 3: Repair of inverted parent-child livestreams (Parent < 300s, Child >= 300s) and
           same-day Hijri short livestream attachment.
  Stage 4: Long-series purification from short clips (< 300s) and promos (promos moved to start
           with `display_no: "برومو"`, lesson excerpts attached as `is_child: true, display_no: "مقطع"`,
           standalone duas moved to «أدعية وابتهالات وتضرع إلى الله», and general short clips moved
           to «مقتطفات وفوائد قصيرة»).
  Stage 5: Ungrouping false merges of long generic-titled lessons (>= 1200s under >= 1200s
           without explicit part 2 markers and with playlist position gap |pos1 - pos2| > 1 or different dates).
  Stage 6: Hijri date interpolation (`hijri_interpolator.py` + `season_hijri_map`) for 100-char
           truncated titles and chronological re-insertion from series tail.
  Stage 7: Strictly monotonic `display_no` numbering (fixing `NUM_RESET`, `NUM_JUMP`, `NUM_MISMATCH`,
           missing first-lesson offsets, out-of-order episodes, and Qasida sub-lessons).
  Stage 8: Series `state` verification (`completed` | `stopped` | `ongoing`, zero `null` states),
           chapter boundary documentation in `title` and `note`, `<person_id>.json` export,
           optional `curated.db` update, and `<output_series_dir>/<person_id>/sXXX/_meta.json` generation.
  Stage 9: Mandatory self-audit gate running `deep_scanner_all.py` and `global_audit.py`
           (requiring 0 errors).
"""

from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sqlite3
import statistics
import subprocess
import sys
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import deep_scanner_all as dsa  # noqa: E402
import hijri_interpolator as hi  # noqa: E402

# ---------------------------------------------------------------------------
# Constants & Vocabulary
# ---------------------------------------------------------------------------

AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
HARAKAT_RE = re.compile(r"[\u0610-\u061a\u064b-\u065f\u0670\u0640\u200b-\u200f\ufeff]")

GENERAL_KEYWORDS = [
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

ALLOWED_MAIN_BADGES = {"مقدمة", "برومو", "فهرس", "ختام"}

PROMO_KEYWORDS = [
    "برومو",
    "تشويقة",
    "تشويقه",
    "إعلان برنامج",
    "اعلان برنامج",
    "برومو برنامج",
    "برومو سلسلة",
    "تشويقة برنامج",
    "تشويقة سلسلة",
]

DUA_KEYWORDS = [
    "دعاء",
    "أدعية",
    "ادعيه",
    "مناجاة",
    "مناجاه",
    "ابتهال",
    "ابتهالات",
    "تضرع",
    "يا رب",
]

EVENT_CEREMONY_KEYWORDS = [
    "حفل اختتام",
    "حفل ختام",
    "حفل تكريم",
    "حفل توزيع الجوائز",
    "إعلان نتائج المسابقة",
    "اعلان نتائج المسابقه",
    "المسابقة الرابعة",
    "المسابقة السنوية",
    "الحفل الختامي",
]

CLASSICAL_AUTHORS_STOP = {
    "الغزالي",
    "الشاطبي",
    "السنوسي",
    "القيرواني",
    "ابن ابي زيد",
    "الدردير",
    "النووي",
    "البخاري",
    "مالك بن انس",
    "البكجري",
    "الزقاق",
    "الولاتي",
    "القرافي",
    "الاخضري",
    "ابن عاشر",
    "ابن دقيق العيد",
    "ابن حجر",
    "السيوطي",
    "الاسنوي",
    "القشيري",
    "عبد الله بن علوي الحداد",
    "علي باراس",
    "ابن عطاء الله",
    "السكندري",
    "الزركشي",
    "ابن تيميه",
    "ابن القيم",
    "الذهبي",
    "ابن كثير",
    "الطبري",
    "القرطبي",
    "النسفي",
    "البيضاوي",
    "الرازي",
    "الزمخشري",
    "ابن عاشور",
    "ابن هشام",
    "ابن مالك",
    "ابن عقيل",
    "ابن اجروم",
    "الجرجاني",
    "القزويني",
    "التفتازاني",
    "زكريا الانصاري",
    "ابن قاسم",
    "ابو شجاع",
    "ابن فرحون",
    "الونشريسي",
    "ابن رشد",
    "ابن عرفه",
    "الرصاع",
    "القاضي عياض",
}

SERIES_STOPWORDS = {
    "شرح",
    "كتاب",
    "متن",
    "نظم",
    "منظومه",
    "سلسله",
    "مجالس",
    "برنامج",
    "حلقات",
    "محاضرات",
    "لقاءات",
    "في",
    "من",
    "على",
    "الي",
    "عن",
    "مع",
    "الشيخ",
    "الامام",
    "العلامه",
    "الدكتور",
    "الاستاذ",
    "الحبيب",
    "السيد",
    "فضيله",
    "رحمه",
    "الله",
    "تعالي",
    "رضي",
    "عنه",
    "البث",
    "المباشر",
    "بث",
    "مباشر",
    "الدرس",
    "المجلس",
    "الحلقه",
    "ماده",
    "تعليق",
    "التعليق",
    "مدارسه",
    "قراءه",
}

CURATED_DB_SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS sheikhs (
    id TEXT PRIMARY KEY,
    order_no INTEGER NOT NULL,
    name TEXT NOT NULL,
    short_name TEXT NOT NULL,
    photo TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS channels (
    id TEXT PRIMARY KEY,
    sheikh_id TEXT NOT NULL REFERENCES sheikhs(id) ON DELETE CASCADE,
    priority INTEGER NOT NULL DEFAULT 1,
    yt_channel_id TEXT,
    title TEXT,
    handle TEXT,
    url TEXT NOT NULL,
    note TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_cur_channels_sheikh ON channels(sheikh_id, priority);

CREATE TABLE IF NOT EXISTS series (
    id TEXT PRIMARY KEY,
    sheikh_id TEXT NOT NULL REFERENCES sheikhs(id) ON DELETE CASCADE,
    order_no INTEGER NOT NULL DEFAULT 1,
    title TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'شرح علمي',
    state TEXT NOT NULL DEFAULT 'completed' CHECK (state IN ('completed', 'ongoing', 'stopped')),
    expected_count INTEGER,
    note TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_cur_series_sheikh ON series(sheikh_id, order_no);

CREATE TABLE IF NOT EXISTS lessons (
    id TEXT PRIMARY KEY,
    series_id TEXT NOT NULL REFERENCES series(id) ON DELETE CASCADE,
    sheikh_id TEXT NOT NULL REFERENCES sheikhs(id) ON DELETE CASCADE,
    order_no INTEGER NOT NULL,
    display_no TEXT,
    is_child INTEGER NOT NULL DEFAULT 0,
    parent_yt_id TEXT,
    title TEXT NOT NULL,
    yt_id TEXT NOT NULL,
    yt_title TEXT,
    yt_url TEXT NOT NULL,
    duration INTEGER,
    has_transcript INTEGER NOT NULL DEFAULT 0,
    has_summary INTEGER NOT NULL DEFAULT 0,
    has_questions INTEGER NOT NULL DEFAULT 0,
    has_challenges INTEGER NOT NULL DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now')),
    UNIQUE(series_id, order_no),
    UNIQUE(sheikh_id, yt_id)
);

CREATE INDEX IF NOT EXISTS idx_cur_lessons_series ON lessons(series_id, order_no);
CREATE INDEX IF NOT EXISTS idx_cur_lessons_sheikh ON lessons(sheikh_id);
CREATE INDEX IF NOT EXISTS idx_cur_lessons_yt ON lessons(yt_id);
"""


# ---------------------------------------------------------------------------
# Arabic Text & Number Helpers
# ---------------------------------------------------------------------------


def normalize_ar(text: str) -> str:
    """Normalize Arabic text for deterministic comparison (converting '#' and '_' to spaces)."""
    if not text:
        return ""
    s = str(text).translate(AR_DIGITS)
    s = HARAKAT_RE.sub("", s)
    s = re.sub(r"[أإآٱ]", "ا", s)
    s = s.replace("ى", "ي").replace("ئ", "ي").replace("ؤ", "و").replace("ة", "ه")
    s = re.sub(r"[#_]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def has_ar_word(text: str, word: str) -> bool:
    """Check if `word` appears in `text` respecting Arabic word boundaries and connected prefixes."""
    nt = normalize_ar(text)
    nw = normalize_ar(word)
    if not nw:
        return False
    core = nw[2:] if nw.startswith("ال") and len(nw) > 4 else nw
    pat = rf"(?<![\u0621-\u064a0-9])(?:[وفبكل])?(?:ال|لل)?{re.escape(core)}(?![\u0621-\u064a0-9])"
    return bool(re.search(pat, nt))


def is_general_series_title(title: str) -> bool:
    """Return True if the series title matches general/collection keywords (matching deep_scanner_all.py)."""
    t = str(title or "")
    return any(w in t for w in GENERAL_KEYWORDS)


def parse_arabic_ordinal_phrase(text: str) -> int | None:
    """Parse Arabic ordinal words (e.g. 'الدرس الثاني', 'المجلس السادس عشر') into integers."""
    t = str(text or "").translate(AR_DIGITS)
    t = HARAKAT_RE.sub("", t)
    t_norm = re.sub(r"[أإآٱ]", "ا", t)
    t_norm = re.sub(r"[#_]+", " ", t_norm)

    units_map = {
        "الحادي": 1,
        "الحاديه": 1,
        "الحادية": 1,
        "واحد": 1,
        "الواحد": 1,
        "الواحدة": 1,
        "اول": 1,
        "الاول": 1,
        "الاولى": 1,
        "الاولي": 1,
        "الثاني": 2,
        "الثانيه": 2,
        "الثانية": 2,
        "اثنان": 2,
        "اثنين": 2,
        "الثالث": 3,
        "الثالثه": 3,
        "الثالثة": 3,
        "ثلاث": 3,
        "ثلاثة": 3,
        "الرابع": 4,
        "الرابعه": 4,
        "الرابعة": 4,
        "اربع": 4,
        "اربعة": 4,
        "الخامس": 5,
        "الخامسه": 5,
        "الخامسة": 5,
        "خمس": 5,
        "خمسة": 5,
        "السادس": 6,
        "السادسه": 6,
        "السادسة": 6,
        "ست": 6,
        "ستة": 6,
        "السابع": 7,
        "السابعه": 7,
        "السابعة": 7,
        "سبع": 7,
        "سبعة": 7,
        "الثامن": 8,
        "الثامنه": 8,
        "الثامنة": 8,
        "ثمان": 8,
        "ثمانية": 8,
        "التاسع": 9,
        "التاسعه": 9,
        "التاسعة": 9,
        "تسع": 9,
        "تسعة": 9,
    }
    tens_map = {
        "العاشر": 10,
        "العاشره": 10,
        "العاشرة": 10,
        "عشر": 10,
        "عشرة": 10,
        "العشرون": 20,
        "العشرين": 20,
        "عشرون": 20,
        "عشرين": 20,
        "الثلاثون": 30,
        "الثلاثين": 30,
        "ثلاثون": 30,
        "ثلاثين": 30,
        "الاربعون": 40,
        "الاربعين": 40,
        "اربعون": 40,
        "اربعين": 40,
        "الخمسون": 50,
        "الخمسين": 50,
        "خمسون": 50,
        "خمسين": 50,
        "الستون": 60,
        "الستين": 60,
        "ستون": 60,
        "ستين": 60,
        "السبعون": 70,
        "السبعين": 70,
        "سبعون": 70,
        "سبعين": 70,
        "الثمانون": 80,
        "الثمانين": 80,
        "ثمانون": 80,
        "ثمانين": 80,
        "التسعون": 90,
        "التسعين": 90,
        "تسعون": 90,
        "تسعين": 90,
    }
    hundreds_map = {
        "المائة الاولى": 100,
        "المئة الاولى": 100,
        "المائة الأولى": 100,
        "المئة الأولى": 100,
        "المائة الثانية": 200,
        "المئة الثانية": 200,
        "المائة الثانيه": 200,
        "المئة الثانيه": 200,
        "المائة الثالثة": 300,
        "المئة الثالثة": 300,
        "المائة الثالثه": 300,
        "المئة الثالثه": 300,
        "المائة": 100,
        "المئة": 100,
        "مائة": 100,
        "مئة": 100,
        "المائتين": 200,
        "المائتان": 200,
        "المئتين": 200,
        "المئتان": 200,
        "مائتين": 200,
        "مائتان": 200,
        "الثلاثمائة": 300,
        "ثلاثمائة": 300,
        "الثلاث مائة": 300,
        "ثلاث مائة": 300,
    }

    matches = list(
        re.finditer(
            r"(?:^|(?<![\u0621-\u064a]))(?:الحلقة|الحلقه|الدرس|المجلس|اللقاء|المحاضرة|المحاضره|لقاء|درس|مجلس|حلقة|حلقه)\s+(?:العام\s+)?(.{3,55})",
            t_norm,
        )
    )
    for m in matches:
        cand = re.split(r"[:\|\-–—\(\[\{«\"/]", m.group(1))[0]
        h_val = 0
        for hk, hv in sorted(hundreds_map.items(), key=lambda x: -len(x[0])):
            m_h = re.search(r"(?:^|\s|و)" + re.escape(hk) + r"(?![\u0621-\u064a])", cand)
            if m_h:
                h_val = hv
                cand = cand[: m_h.start()] + " " + cand[m_h.end() :]
                break
        t_val = 0
        for tk, tv in sorted(tens_map.items(), key=lambda x: -len(x[0])):
            if tv >= 20 and re.search(r"(?:^|\s|و)" + re.escape(tk) + r"(?![\u0621-\u064a])", cand):
                t_val = tv
                break
        if t_val == 0:
            m_teen = re.search(
                r"(?:^|\s|و)(الحادي|الحادية|الحاديه|الثاني|الثانية|الثانيه|الثالث|الثالثة|الثالثه|الرابع|الرابعة|الرابعه|الخامس|الخامسة|الخامسه|السادس|السادسة|السادسه|السابع|السابعة|السابعه|الثامن|الثامنة|الثامنه|التاسع|التاسعة|التاسعه)\s+(عشر|عشرة|عشره)(?![\u0621-\u064a])",
                cand,
            )
            if m_teen:
                return h_val + 10 + units_map[m_teen.group(1)]
            if re.search(r"(?:^|\s|و)(العاشر|العاشرة|العاشره)(?![\u0621-\u064a])", cand):
                return h_val + 10
        u_val = 0
        best_u_pos = len(cand) + 1
        for uk, uv in sorted(units_map.items(), key=lambda x: -len(x[0])):
            m_u = re.search(r"(?:^|\s|و)" + re.escape(uk) + r"(?![\u0621-\u064a])", cand)
            if m_u and m_u.start() < best_u_pos:
                best_u_pos = m_u.start()
                u_val = uv
        total = h_val + t_val + u_val
        if total > 0:
            return total
    return None


def _extract_num_from_segment(seg: str, series_title: str = "") -> int | None:
    """Internal helper to extract a lesson number from a single cleaned title or pipe segment."""
    if not seg:
        return None

    # Strip known false-positive parenthesized numbers (poem numbers, dawrah numbers, verse/hadith/page numbers)
    cleaned = re.sub(
        r"(?:وقصيدة|قصيدة|وقصيده|قصيده)\s*:?[^|\n]*?\(\s*[\d\u0660-\u0669]+\s*\)",
        " ",
        seg,
    )
    cleaned = re.sub(
        r"(?:الدورة|دورة|دوره|المؤتمر|مؤتمر|الملتقى|ملتقى|عام|سنة|سنه)\s+(?:[\u0621-\u064a]+\s+){0,4}\(\s*[\d\u0660-\u0669]+\s*\)",
        " ",
        cleaned,
    )
    cleaned = re.sub(
        r"(?:آية|آيه|ايه|الآية|الايه|الآيات|الايات|سورة|سوره|حديث|الحديث|رقم الحديث|صفحة|ص)\s*\(?\s*[\d\u0660-\u0669]+\s*\)?(?:\s*(?:[-–—/]|إلى|الى|وحتى|حتى)\s*\(?\s*[\d\u0660-\u0669]+\s*\)?)?",
        " ",
        cleaned,
    )

    # 1. Standard deep_scanner_all explicit number
    n = dsa.extract_explicit_num(cleaned)
    if n is not None:
        return n

    t_norm = dsa.norm(cleaned)

    # 2. Extended explicit lesson/episode/council keywords (including 'ح 1' after tatweel removal, 'دس21', 'الدرس:17', 'رقم: 80')
    m_kw = re.search(
        r"(?:^|(?<![\u0621-\u064a]))(?:الدرس|درس|دس|الحلقة|حلقة|حـ|المجلس|مجلس|المحاضرة|محاضرة|اللقاء|لقاء|رقم)\s*[:\-–—_#]*\s*(?:الـ?\s*)?\(?\s*0*(\d{1,4})\b",
        t_norm,
    )
    if m_kw:
        val = int(m_kw.group(1))
        if 1 <= val <= 3000:
            return val

    m_ha = re.search(r"(?:^|[\|\-–—:\(\[\s])ح\s*[:\-–—_#]*\s*0*(\d{1,4})(?:\b|$)", t_norm)
    if m_ha:
        val = int(m_ha.group(1))
        if 1 <= val <= 3000:
            return val

    # 3. Arabic ordinal words ('الدرس الثاني', 'المجلس السادس عشر')
    ord_n = parse_arabic_ordinal_phrase(cleaned)
    if ord_n is not None:
        return ord_n
    if "مقدمات" in series_title and "المقدمة" in cleaned:
        rewritten = cleaned.replace("المقدمة", "الدرس", 1)
        ord_m = parse_arabic_ordinal_phrase(rewritten)
        if ord_m is not None:
            return ord_m

    # 4. Square-bracketed lesson numbers or ranges: '[4]', '[14-30]', '[09]'
    m_br = re.search(r"\[\s*0*(\d{1,4})(?:\s*[-–—/]\s*\d{1,4})?\s*\]", t_norm)
    if m_br:
        val = int(m_br.group(1))
        if 1 <= val <= 3000:
            return val

    # 5. Parenthesized fraction or slash: '(14/30)', '(الحكم العطائية/12)'
    m_sl = re.search(r"\(\s*(?:[\u0621-\u064a\s]{2,25}/\s*)?0*(\d{1,4})(?:\s*/\s*\d{1,4})?\s*\)", t_norm)
    if m_sl and "/" in m_sl.group(0):
        val = int(m_sl.group(1))
        if 1 <= val <= 3000:
            return val

    # 6. Leading numbers at the start of the title: '(1) ...', '949) ...', '14- ...', '33 شرح ...'
    m_lead = re.search(
        r"^\s*(?:\(\s*0*(\d{1,4})\s*\)|0*(\d{1,4})\s*\)\s+|0*(\d{1,4})\s*[-–—:]\s*[\u0621-\u064a]|0*(\d{1,4})\s+(?:والاخير|والاخيره|و\s*الاخير|شرح|ماده|تفسير|قواعد|بدايه|فقه))",
        normalize_ar(cleaned),
    )
    if m_lead:
        num_str = next(g for g in m_lead.groups() if g is not None)
        val = int(num_str)
        if 1 <= val <= 3000:
            return val

    # 7. Pipe-delimited standalone numbers: '| 01 |', '| #9 |', '| 16 والاخير'
    m_pipe = re.search(r"\|\s*#?\s*0*(\d{1,4})(?:\s*والاخير|\s*والاخيره)?\s*(?:\||$)", normalize_ar(cleaned))
    if m_pipe:
        val = int(m_pipe.group(1))
        if 1 <= val <= 3000:
            return val

    # 8. Hyphen-wrapped, underscore-wrapped, or hash-prefixed numbers: '-33-', '- 88 -', '_07_', '#12'
    m_hyph = re.search(
        r"(?:(?:^|\s)-\s*0*(\d{1,4})\s*-(?:\s|$)|_\s*0*(\d{1,4})\s*_|(?:^|[\s\|\(\[])#\s*0*(\d{1,4})(?:\b|$))",
        t_norm,
    )
    if m_hyph:
        num_str = next(g for g in m_hyph.groups() if g is not None)
        val = int(num_str)
        if 1 <= val <= 3000:
            return val

    # 9. Parenthesized number after Arabic title words: 'شرح ابن عقيل (101)', 'الأشموني (81)'
    # (Skip if multiple parenthesized numbers exist and series_title matches the second one)
    paren_matches = list(re.finditer(r"([\u0621-\u064a]{3,})\s*\(\s*0*(\d{1,4})\s*\)", normalize_ar(cleaned)))
    if paren_matches:
        if len(paren_matches) >= 2 and series_title:
            nt_ser = normalize_ar(series_title)
            for pm in reversed(paren_matches):
                w_before = pm.group(1)
                if w_before in nt_ser and w_before not in {"لمسات", "بيانيه"}:
                    val = int(pm.group(2))
                    if 1 <= val <= 3000:
                        return val
        val = int(paren_matches[0].group(2))
        if 1 <= val <= 3000:
            return val

    # 10. Book/series phrase followed by number before '-', '|', '@', or end of string:
    # e.g. 'كشف الغمة 489-', 'رياض الصالحين 65 |', 'شرح نظم ابن عاشر 05', 'صحيح البخاري 39 @dedewiat'
    m_trail = re.search(
        r"(?:شرح|كتاب|متن|نظم|تفسير|سيره|رياض|كشف|خلاصات|مدارس|صفوه|ايها|ماده|الفقه|التعليق|مجالس|الف\s+باء|لتعارفوا|اقرا|ونفس)[^|\n\d]{1,45}?\s+0*(\d{1,4})\s*(?:[-–—\|]|@[\w_]+|$)",
        normalize_ar(cleaned),
    )
    if m_trail:
        val = int(m_trail.group(1))
        if 1 <= val <= 3000:
            return val

    return None


def extract_lesson_num(title: str, series_title: str = "") -> int | None:
    """
    Extract explicit lesson number from compound titles without capturing poem numbers `(8)`,
    verse numbers, or Dawrah numbers `الدورة (29)`.
    Disambiguates multi-number titles (e.g. 'ألف باء الزواج 43 | خلاصات ما بعد المجلس 12')
    using `series_title`.
    """
    if not title:
        return None

    # If the title has pipe-separated segments and series_title matches a specific sub-segment,
    # prefer the number in that sub-segment unless dsa.extract_explicit_num is already on the whole title.
    scanner_n = dsa.extract_explicit_num(title)
    if "|" in title and series_title:
        nt_ser = normalize_ar(series_title)
        segments = [seg.strip() for seg in title.split("|") if seg.strip()]
        if len(segments) >= 2:
            for seg in segments[1:]:
                nt_seg = normalize_ar(seg)
                seg_words = [w for w in nt_seg.split() if len(w) >= 4 and w not in SERIES_STOPWORDS]
                if seg_words and sum(1 for w in seg_words if w in nt_ser) >= min(2, len(seg_words)):
                    sub_n = _extract_num_from_segment(seg, series_title)
                    if sub_n is not None and (scanner_n is None or scanner_n == sub_n):
                        return sub_n

    return _extract_num_from_segment(title, series_title)


def is_explicit_part_continuation(title: str) -> bool:
    """Return True if the title explicitly denotes a continuation part (الجزء الثاني / ج2 / (2) / تتمة)."""
    t = dsa.norm(title)
    if re.search(r"-\s*[234]\s*-|الجزء\s*(?:الثاني|الثالث|الرابع|[234])|\([234]\)", t):
        return True
    if re.search(r"(?:^|\s|[/|\-])(?:ج\s*[234]|تتمة|تتمه|تكملة|تكمله|القسم الثاني)(?:\b|$)", t):
        return True
    return False


def is_promo_title(title: str, disp: str = "") -> bool:
    """Return True if the video is a series promo / teaser."""
    if str(disp).strip() == "برومو":
        return True
    nt = normalize_ar(title)
    for kw in PROMO_KEYWORDS:
        if normalize_ar(kw) in nt:
            return True
    return False


def is_dua_title(title: str) -> bool:
    """Return True if the video title is a standalone supplication / dua."""
    for kw in DUA_KEYWORDS:
        if has_ar_word(title, kw):
            return True
    return False


def is_clip_title(title: str, series_title: str = "") -> bool:
    """Return True if the title matches clip markers checked by deep_scanner_all.py."""
    t = str(title or "")
    if any(
        w in t
        for w in [
            "مقطع:",
            "مقطع |",
            "مقطع من",
            "مقتطف:",
            "مقتطف من",
            "مقتطفات من",
            "#مقتطفات",
            "فائدة:",
            "برومو",
            "تشويقة",
            "إعلان برنامج",
        ]
    ):
        return True
    if "#الدورة" in t and "الدورة" not in series_title and "الدورات" not in series_title:
        return True
    return False


NON_PERSON_FIRST_WORDS = {
    "في",
    "عن",
    "حول",
    "بمناسبه",
    "خلال",
    "امام",
    "الي",
    "لطلبه",
    "لطلاب",
    "بمسجد",
    "بعنوان",
    "بمعهد",
    "بدار",
    "بجامع",
    "ودور",
    "واثر",
    "وفضل",
    "ومكانه",
    "رحمه",
    "رضي",
    "حفظه",
    "لشرح",
    "لكتاب",
    "لمتن",
}


def is_guest_or_event_lesson(title: str, sheikh_info: dict[str, Any], series_title: str = "") -> bool:
    """
    Detect guest speaker lectures (attributed to a scholar other than the channel's sheikh),
    welcoming/farewell speeches, and contest/award ceremonies that should be isolated from
    structured book/course explanation series.
    """
    nt = normalize_ar(title)
    nt_series = normalize_ar(series_title)

    # Do not isolate events/guests from series that are already event/conference/dawrah/rihlah collections
    if nt_series and any(
        w in nt_series
        for w in [
            "موتمر",
            "ندوه",
            "ملتقي",
            "احتفال",
            "احتفالات",
            "حفل",
            "رحله",
            "رحلات",
            "زياره",
            "زيارات",
            "الدوره الصيفيه",
            "الدورات الصيفيه",
            "فعاليات",
            "الضيوف",
            "كلمات العلماء",
            "شهادات",
            "مرثيات",
        ]
    ):
        return False

    # 1. Contest / Award / Closing ceremonies & Welcoming / Farewell speeches
    for ev_kw in EVENT_CEREMONY_KEYWORDS:
        if normalize_ar(ev_kw) in nt:
            return True

    welcome_keywords = [
        "كلمه ترحيبيه",
        "كلمه الترحيب",
        "كلمه توديعيه",
        "مجلس توديع",
        "كلمات العلماء والدعاه",
    ]
    for w_kw in welcome_keywords:
        if w_kw in nt:
            return True

    # 2. Guest speaker patterns
    sheikh_id_norm = normalize_ar(sheikh_info.get("id", ""))
    sheikh_name_norm = normalize_ar(sheikh_info.get("name", ""))
    sheikh_short_norm = normalize_ar(sheikh_info.get("short_name", ""))
    sheikh_tokens = {
        w
        for w in (sheikh_name_norm + " " + sheikh_short_norm).split()
        if len(w) >= 3
        and w
        not in {
            "الشيخ",
            "الدكتور",
            "الامام",
            "العلامه",
            "الحبيب",
            "السيد",
            "ابو",
            "ابي",
            "عبد",
            "بن",
            "محمد",
            "احمد",
            "علي",
        }
    }
    # Add common kunyas/aliases for the 17 sheikhs
    if "dedew" in sheikh_id_norm or "الددو" in sheikh_name_norm:
        sheikh_tokens.update({"الددو", "ددو", " الشنقيطي"})

    guest_patterns = [
        (
            True,
            r"(?:^|[\|\-–—:]|\b)(?:كلمه|محاضره|مداخله|مشاركه|لقاء مع|ضيف المجلس|ضيف اللقاء|يلقيها|رساله من)\s+(?:فضيله\s+|سماحه\s+|معالي\s+)?(?:الشيخ|الدكتور|الاستاذ|الحبيب|الداعيه|العلامه|السيد|المهندس|م\.|د\.|ا\.د\.?)\s+([\u0621-\u064a\s]{3,35})",
        ),
        (
            True,
            r"^(?:محاضره|كلمه|درس)\s+(?:فضيله\s+)?(?:الشيخ|الدكتور|الاستاذ|الحبيب|الداعيه|المهندس|م\.|د\.)\s+([\u0621-\u064a\s]{3,35})",
        ),
        (
            False,
            r"(?:[\|\-–—])\s*(?:فضيله\s+|سماحه\s+)?(?:الشيخ|الدكتور|الاستاذ|الحبيب|الداعيه|المهندس|م\.|د\.)\s+([\u0621-\u064a\s]{3,30})$",
        ),
    ]
    for is_explicit_speech, pat in guest_patterns:
        m = re.search(pat, nt)
        if m:
            cand = m.group(1).strip()
            cand = re.split(r"[\|\-–—:\(\)\[\]]", cand)[0].strip()
            if not cand or len(cand) < 4:
                continue
            cand_words = cand.split()
            if not cand_words or cand_words[0] in NON_PERSON_FIRST_WORDS:
                continue
            if any(w in cand_words for w in ["الموتمر", "الندوه", "الملتقي", "الجامعه", "المعهد", "الافتتاح", "الختام"]):
                continue
            prefix = nt[: m.start()]
            if re.search(r"(?:شرح|كتاب|متن|نظم|رساله|منظومه|تاليف|تصنيف|للامام|للشيخ|للعلامه)\s*$", prefix):
                continue
            if not is_explicit_speech and any(normalize_ar(ca) in cand for ca in CLASSICAL_AUTHORS_STOP):
                continue
            # If the scholar's name is part of the series title itself (co-hosted/guest-taught series), keep it!
            if nt_series and any(len(w) >= 4 and w in nt_series for w in cand_words if w not in {"الشيخ", "الدكتور", "الامام", "الحبيب", "السيد", "محمد", "احمد", "ابراهيم"}):
                continue
            if sheikh_name_norm and (sheikh_name_norm in cand or cand in sheikh_name_norm):
                continue
            if sheikh_short_norm and len(sheikh_short_norm) >= 4 and sheikh_short_norm in cand:
                continue
            if sheikh_tokens and any(tok in cand_words for tok in sheikh_tokens):
                continue
            return True

    return False


def is_khutbah_fiqh_collision(lesson_title: str, series_title: str = "") -> bool:
    """
    Detect fiqh lessons about the rulings of khutbah (e.g. 'مسألة الصلاة أثناء خطبة الإمام')
    that collide lexically with Friday Khutbah series ('خطب الجمعة').
    """
    nt = normalize_ar(lesson_title)
    if not has_ar_word(nt, "خطبه"):
        return False
    fiqh_issue_markers = ["مساله", "حكم", "مبحث", "فرع", "باب", "فصل", "احكام", "فتوي"]
    has_fiqh_marker = any(has_ar_word(nt, m) for m in fiqh_issue_markers)
    if has_fiqh_marker:
        if not series_title or "خطب" in normalize_ar(series_title):
            return True
    return False


# ---------------------------------------------------------------------------
# Group Partitioning & Rebuilding Helpers
# ---------------------------------------------------------------------------


def lessons_to_groups(lessons: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """
    Partition a flat list of lessons into indivisible `[Parent, Child_1, ..., Child_k]` groups.
    Ensures no orphan child is left detached at the start of a series.
    """
    groups: list[list[dict[str, Any]]] = []
    for ep in lessons:
        item = copy.deepcopy(ep)
        if item.get("is_child") and groups:
            item["parent_yt_id"] = groups[-1][0]["yt_id"]
            groups[-1].append(item)
        else:
            item["is_child"] = False
            item["parent_yt_id"] = None
            groups.append([item])
    return groups


def groups_to_lessons(groups: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Flatten `[Parent, Child_1, ..., Child_k]` groups back into a valid lesson list."""
    flat: list[dict[str, Any]] = []
    for grp in groups:
        if not grp:
            continue
        parent = grp[0]
        parent["is_child"] = False
        parent["parent_yt_id"] = None
        flat.append(parent)
        p_yt = parent["yt_id"]
        for ch in grp[1:]:
            ch["is_child"] = True
            ch["parent_yt_id"] = p_yt
            flat.append(ch)
    for idx, ep in enumerate(flat, 1):
        ep["order_no"] = idx
    return flat


def get_or_create_series(
    series_list: list[dict[str, Any]],
    person_id: str,
    target_title: str,
    category: str = "مواعظ ولقاءات عامة",
    state: str = "completed",
    note: str = "",
) -> dict[str, Any]:
    """Find an existing series matching `target_title` or create it at the end of `series_list`."""
    norm_target = normalize_ar(target_title)
    for s in series_list:
        st = normalize_ar(s.get("title") or s.get("name") or "")
        if st == norm_target or norm_target in st:
            return s
    new_idx = len(series_list) + 1
    new_s = {
        "id": f"{person_id}__s{new_idx:03d}",
        "order_no": new_idx,
        "title": target_title,
        "category": category,
        "state": state,
        "expected_count": 0,
        "note": note or f"سلسلة مخصصة لـ: {target_title}.",
        "lessons": [],
    }
    series_list.append(new_s)
    return new_s


def infer_series_category(title: str, note: str = "", matched_book: dict[str, Any] | None = None) -> str:
    """Infer scholarly category for a series using anti-confusion rules."""
    if matched_book and matched_book.get("science"):
        return str(matched_book["science"])

    nt = normalize_ar(f"{title} {note}")
    if any(w in nt for w in ["مقدمات السنوسي", "ام البراهين", "العقيده", "الاعتقاد", "التوحيد", "علم الكلام", "الطحاويه", "النسفيه", "الواسطيه", "كبري اليقينيات"]):
        return "العقيدة وعلم الكلام"
    if any(w in nt for w in ["الموافقات", "كتاب المقاصد", "مقاصد الشريعه"]):
        return "مقاصد الشريعة"
    if any(w in nt for w in ["اصول الفقه", "جمع الجوامع", "مراقي السعود", "ايصال السالك", "مفتاح الوصول", "الرساله العضديه", "الورقات", "اللمع", "المستصفي", "التمهيد في تخريج", "الاشباه والنظائر", "المنهج المنتخب"]):
        return "أصول الفقه وقواعده"
    if any(has_ar_word(nt, w) for w in ["تفسير", "سوره", "القران", "ايات", "لمسات بيانيه"]):
        return "التفسير وعلوم القرآن"
    if any(has_ar_word(nt, w) for w in ["نحو", "صرف", "بلاغه", "اعراب", "الاجروميه", "قطر الندي", "شذور الذهب", "الفيه ابن مالك"]):
        return "اللغة العربية وعلومها"
    if any(has_ar_word(nt, w) for w in ["البخاري", "مسلم", "الموطا", "السنن", "الحديث", "الشمائل", "الشفا", "الاربعين النوويه", "رياض الصالحين", "الادب المفرد"]):
        return "الحديث وعلومه"
    if any(has_ar_word(nt, w) for w in ["فقه", "المالكيه", "مختصر خليل", "اسهل المسالك", "اقرب المسالك", "الرساله", "الاخضري", "ابن عاشر", "الزبد", "المنهاج", "الطهاره", "الصلاه", "البيوع"]):
        return "الفقه وأصوله"
    if any(has_ar_word(nt, w) for w in ["الحكم العطائيه", "تزكيه", "سلوك", "اخلاق", "المريد", "الاحياء", "قبس النور", "الرساله القشيريه", "ادعيه", "ابتهالات", "مناجاه"]):
        return "التزكية والأخلاق"
    if any(has_ar_word(nt, w) for w in ["سيره", "تراجم", "تاريخ", "الصحابه", "الانبياء"]):
        return "السيرة والتراجم والتاريخ"
    if any(has_ar_word(nt, w) for w in ["خطب", "جمعه"]):
        return "الخطب والمنبر"
    return "مواعظ ولقاءات عامة"


# ---------------------------------------------------------------------------
# Stage 1: Duration Import, Video Normalization & Dead Livestream Purge
# ---------------------------------------------------------------------------


def stage1_import_durations_and_purge_dead(
    raw_data: dict[str, Any],
    dead_threshold_s: int = 15,
) -> tuple[str, dict[str, Any], list[dict[str, Any]], dict[str, dict[str, Any]], dict[str, dict[str, int]], dict[str, Any]]:
    """
    Stage 1:
    - Extract canonical `person_id` and `sheikh_info`.
    - Build `video_catalog[yt_id]` with normalized durations (in seconds) and playlist appearances.
    - Convert raw playlists/series (and any standalone `archive_items`) into working `series_list`.
    - Populate `duration` on every lesson and purge dead livestreams (`<= dead_threshold_s`) and
      silent torrent/PDF link screens.
    - Deduplicate `yt_id` across series (preferring specific structured series over general/unclassified).
    """
    sheikh_obj = raw_data.get("sheikh") or {}
    person_id = (
        raw_data.get("person_id")
        or raw_data.get("sheikh_id")
        or sheikh_obj.get("id")
        or "person"
    )
    sheikh_name = (
        raw_data.get("sheikh_name")
        or sheikh_obj.get("name")
        or person_id
    )
    short_name = sheikh_obj.get("short_name") or sheikh_name.split()[-1]
    sheikh_info = {
        "id": person_id,
        "order_no": int(sheikh_obj.get("order_no") or 1),
        "name": sheikh_name,
        "short_name": short_name,
        "photo": sheikh_obj.get("photo") or "",
        "created_at": sheikh_obj.get("created_at") or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
    }

    video_catalog: dict[str, dict[str, Any]] = {}
    raw_pos_map: dict[str, dict[str, int]] = {}

    def register_video(v: dict[str, Any], default_pl_id: str | None = None, is_uncl: bool = False):
        yt_id = str(v.get("yt_id") or v.get("vid") or "").strip()
        if not yt_id:
            return
        dur_raw = v.get("duration") if v.get("duration") is not None else v.get("dur_s")
        dur = int(round(float(dur_raw))) if isinstance(dur_raw, (int, float)) else 0
        rec = video_catalog.setdefault(
            yt_id,
            {
                "yt_id": yt_id,
                "title": str(v.get("title") or "").strip(),
                "yt_url": v.get("yt_url") or v.get("direct_url") or f"https://www.youtube.com/watch?v={yt_id}",
                "duration": dur,
                "upload_date": v.get("upload_date"),
                "has_transcript": int(v.get("has_transcript") or 0),
                "has_summary": int(v.get("has_summary") or 0),
                "has_questions": int(v.get("has_questions") or 0),
                "appearances": [],
            },
        )
        if dur > 0 and (not rec.get("duration") or rec["duration"] <= 0):
            rec["duration"] = dur
        if v.get("title") and len(str(v["title"])) > len(rec.get("title", "")):
            rec["title"] = str(v["title"]).strip()
        for app in v.get("appearances") or []:
            rs_id = app.get("raw_series_id")
            pos = app.get("pos")
            if rs_id:
                if not any(a.get("raw_series_id") == rs_id for a in rec["appearances"]):
                    rec["appearances"].append(copy.deepcopy(app))
                if isinstance(pos, int):
                    raw_pos_map.setdefault(yt_id, {})[rs_id] = pos
        if default_pl_id and not rec["appearances"]:
            pos = v.get("pos") or v.get("order_no")
            rec["appearances"].append(
                {
                    "raw_series_id": default_pl_id,
                    "raw_series_title": v.get("playlist_title") or default_pl_id,
                    "pos": pos if isinstance(pos, int) else 1,
                    "is_unclassified": bool(is_uncl or v.get("is_unclassified")),
                }
            )
            if isinstance(pos, int):
                raw_pos_map.setdefault(yt_id, {})[default_pl_id] = pos
        elif default_pl_id:
            pos = v.get("pos") or v.get("order_no")
            if isinstance(pos, int):
                raw_pos_map.setdefault(yt_id, {})[default_pl_id] = pos

    for uv in raw_data.get("unique_videos") or []:
        register_video(uv)
    for uv in raw_data.get("videos") or []:
        register_video(uv)

    raw_series_input = (
        raw_data.get("series")
        or raw_data.get("raw_series")
        or raw_data.get("playlists")
        or []
    )
    for rs in raw_data.get("raw_series") or raw_data.get("playlists") or []:
        rs_id = str(rs.get("id") or rs.get("playlist_id") or "")
        is_uncl = bool(
            rs.get("is_unclassified")
            or (rs.get("yt_playlist_id") is None and ("غير مصنف" in str(rs.get("title", "")) or "unclassified" in rs_id))
        )
        for idx, v in enumerate(rs.get("videos") or rs.get("lessons") or [], 1):
            v_copy = dict(v)
            if "pos" not in v_copy:
                v_copy["pos"] = idx
            register_video(v_copy, default_pl_id=rs_id, is_uncl=is_uncl)

    existing_ids = {str(s.get("id") or "") for s in raw_series_input}
    archive_series_list: list[dict[str, Any]] = []
    for arch in raw_data.get("archive_items") or []:
        item_id = str(arch.get("item_id") or "").strip()
        files = arch.get("files") or []
        if not item_id or not files:
            continue
        arch_sid = f"archive__{item_id}"
        if arch_sid in existing_ids or item_id in existing_ids:
            continue
        vids = []
        for f_idx, f_obj in enumerate(files, 1):
            yt_id = str(f_obj.get("yt_id") or f_obj.get("vid") or f"archive__{person_id}__{item_id}__ep{f_idx:03d}")
            dur_raw = f_obj.get("duration") if f_obj.get("duration") is not None else f_obj.get("dur_s")
            dur = int(round(float(dur_raw))) if isinstance(dur_raw, (int, float)) else 1800
            v_entry = {
                "pos": f_idx,
                "yt_id": yt_id,
                "title": str(f_obj.get("title") or f_obj.get("name") or f"الدرس {f_idx}"),
                "yt_url": f_obj.get("direct_url") or f"https://archive.org/details/{item_id}",
                "duration": dur,
            }
            register_video(v_entry, default_pl_id=arch_sid, is_uncl=False)
            vids.append(v_entry)
        archive_series_list.append(
            {
                "id": arch_sid,
                "title": str(arch.get("title") or item_id),
                "yt_playlist_id": arch_sid,
                "state": "completed",
                "expected_count": len(vids),
                "matched_book": arch.get("matched_book"),
                "videos": vids,
            }
        )

    all_input_series = list(raw_series_input) + archive_series_list

    dead_removed: list[dict[str, Any]] = []
    series_list: list[dict[str, Any]] = []

    for s_idx, rs in enumerate(all_input_series, 1):
        s_id = str(rs.get("id") or f"{person_id}__s{s_idx:03d}")
        s_title = str(rs.get("title") or rs.get("name") or f"سلسلة {s_idx}").strip()
        is_uncl = bool(
            rs.get("is_unclassified")
            or (
                "yt_playlist_id" in rs
                and rs.get("yt_playlist_id") is None
                and ("غير مصنف" in s_title or "unclassified" in s_id.lower())
            )
            or "غير مصنف" in s_title
            or s_id.lower().endswith("__unclassified")
        )
        raw_eps = rs.get("lessons") if rs.get("lessons") is not None else (rs.get("videos") or [])
        normalized_eps: list[dict[str, Any]] = []

        for ep_idx, ep in enumerate(raw_eps, 1):
            yt_id = str(ep.get("yt_id") or ep.get("vid") or "").strip()
            if not yt_id:
                continue
            register_video(ep, default_pl_id=s_id, is_uncl=is_uncl)
            cat_info = video_catalog.get(yt_id, {})
            dur_raw = ep.get("duration") if ep.get("duration") is not None else ep.get("dur_s")
            if dur_raw is None:
                dur_raw = cat_info.get("duration")
            dur = int(round(float(dur_raw))) if isinstance(dur_raw, (int, float)) else 0
            if dur > 0 and cat_info:
                cat_info["duration"] = dur
            title = str(ep.get("title") or cat_info.get("title") or f"الدرس {ep_idx}").strip()
            yt_url = (
                ep.get("yt_url")
                or ep.get("direct_url")
                or cat_info.get("yt_url")
                or f"https://www.youtube.com/watch?v={yt_id}"
            )
            pos = ep.get("pos") if isinstance(ep.get("pos"), int) else ep_idx
            raw_pos_map.setdefault(yt_id, {})[s_id] = pos

            normalized_eps.append(
                {
                    "yt_id": yt_id,
                    "title": title,
                    "yt_url": yt_url,
                    "duration": dur,
                    "is_child": bool(ep.get("is_child", False)),
                    "parent_yt_id": ep.get("parent_yt_id") if ep.get("is_child") else None,
                    "display_no": str(ep.get("display_no") or "").strip(),
                    "pos": pos,
                    "has_transcript": int(ep.get("has_transcript") or cat_info.get("has_transcript") or 0),
                    "has_summary": int(ep.get("has_summary") or cat_info.get("has_summary") or 0),
                    "has_questions": int(ep.get("has_questions") or cat_info.get("has_questions") or 0),
                }
            )

        groups = lessons_to_groups(normalized_eps)
        surviving_groups: list[list[dict[str, Any]]] = []
        for grp in groups:
            kept_in_grp: list[dict[str, Any]] = []
            for item in grp:
                dur = item.get("duration") or 0
                t_norm = normalize_ar(item.get("title", ""))
                is_dead = 0 < dur <= dead_threshold_s
                is_silent_link_screen = (
                    0 < dur < 180
                    and any(w in t_norm for w in ["روابط تحميل", "روابط الحلقات", "تحميل التورنت"])
                )
                if is_dead or is_silent_link_screen:
                    dead_removed.append(
                        {
                            "yt_id": item["yt_id"],
                            "title": item["title"],
                            "duration": dur,
                            "series_id": s_id,
                        }
                    )
                else:
                    kept_in_grp.append(item)
            if kept_in_grp:
                if kept_in_grp[0].get("is_child"):
                    kept_in_grp.sort(key=lambda x: -(x.get("duration") or 0))
                kept_in_grp[0]["is_child"] = False
                kept_in_grp[0]["parent_yt_id"] = None
                for ch in kept_in_grp[1:]:
                    ch["is_child"] = True
                    ch["parent_yt_id"] = kept_in_grp[0]["yt_id"]
                surviving_groups.append(kept_in_grp)

        series_list.append(
            {
                "id": s_id,
                "raw_series_id": s_id,
                "order_no": s_idx,
                "title": s_title,
                "category": rs.get("category") or "",
                "state": rs.get("state"),
                "expected_count": rs.get("expected_count"),
                "note": rs.get("note") or "",
                "matched_book": rs.get("matched_book"),
                "is_unclassified": is_uncl,
                "lessons": groups_to_lessons(surviving_groups),
            }
        )

    series_priority = sorted(
        range(len(series_list)),
        key=lambda idx: (
            2 if series_list[idx].get("is_unclassified") else (
                1 if is_general_series_title(series_list[idx]["title"]) else 0
            ),
            idx,
        ),
    )
    seen_yt: set[str] = set()
    duplicates_removed = 0
    for idx in series_priority:
        s = series_list[idx]
        groups = lessons_to_groups(s["lessons"])
        dedup_groups: list[list[dict[str, Any]]] = []
        for grp in groups:
            kept = []
            for item in grp:
                if item["yt_id"] in seen_yt:
                    duplicates_removed += 1
                else:
                    seen_yt.add(item["yt_id"])
                    kept.append(item)
            if kept:
                kept[0]["is_child"] = False
                kept[0]["parent_yt_id"] = None
                for ch in kept[1:]:
                    ch["is_child"] = True
                    ch["parent_yt_id"] = kept[0]["yt_id"]
                dedup_groups.append(kept)
        s["lessons"] = groups_to_lessons(dedup_groups)

    raw_data["unique_videos"] = list(video_catalog.values())
    if not raw_data.get("raw_series"):
        raw_data["raw_series"] = [
            {
                "id": s["raw_series_id"],
                "title": s["title"],
                "yt_playlist_id": None if s.get("is_unclassified") else s["raw_series_id"],
                "videos": [
                    {
                        "pos": ep.get("pos", i),
                        "yt_id": ep["yt_id"],
                        "title": ep["title"],
                        "duration": ep["duration"],
                    }
                    for i, ep in enumerate(s["lessons"], 1)
                ],
            }
            for s in series_list
        ]

    stage1_report = {
        "unique_videos_indexed": len(video_catalog),
        "dead_removed_count": len(dead_removed),
        "dead_removed": dead_removed,
        "duplicates_removed": duplicates_removed,
    }
    return person_id, sheikh_info, series_list, video_catalog, raw_pos_map, stage1_report


# ---------------------------------------------------------------------------
# Stage 2: Semantic Classification of Unclassified & Guest/Event Isolation
# ---------------------------------------------------------------------------


def _clean_series_core_for_matching(s_title: str) -> tuple[str, list[str]]:
    """
    Extract cleaned series core title (stripped of curriculum prefixes and long author suffixes)
    and any meaningful parenthetical book/series aliases.
    """
    nt_series = normalize_ar(s_title)
    aliases: list[str] = []
    for m_par in re.finditer(r"\(([^)]+)\)", nt_series):
        inner = m_par.group(1).strip()
        # Strip range/status notes inside parentheses
        if any(
            w in inner
            for w in [
                "الحلقات الكامله",
                "المستوي",
                "نسخه",
                "مترجم",
                "رحمه الله",
                "من المقدمه",
                "الي باب",
                "الدروس",
                "المجالس",
                "رمضان",
                "ربيع",
                "درساً",
                "درسا",
                "مجلساً",
                "مجلسا",
            ]
        ):
            continue
        inner_clean = re.sub(r"^(?:الشرح|القسم|الجزء|الموسم)\s+[\u0621-\u064a]+\s*:?\s*", "", inner).strip()
        if len(inner_clean) >= 4:
            aliases.append(inner_clean)

    core = re.sub(r"\([^)]*\)", " ", nt_series)
    core = re.sub(r"[«»\"']", " ", core)
    # Strip curriculum subject prefixes like 'نحو (1-أ):' or 'مادة'
    core = re.sub(
        r"^(?:نحو|صرف|بلاغه|فقه|عقيده|منطق|اصول|عروض|مواريث|علوم القران|حديث|تفسير)\s*:?\s*",
        "",
        core,
    ).strip()
    # Strip trailing author attribution after book title if core is long enough
    core_no_author = re.sub(
        r"\s+(?:للامام|للشيخ|للعلامه|للحبيب|لسيدي|للدكتور|تاليف)\s+[\u0621-\u064a\s]{3,35}$",
        "",
        core,
    ).strip()
    if len(core_no_author.split()) >= 2:
        core = core_no_author
    return re.sub(r"\s+", " ", core).strip(), aliases


def _score_series_match(lesson_title: str, candidate_series: dict[str, Any]) -> float:
    """
    Score how strongly `lesson_title` matches `candidate_series` using Arabic word boundaries,
    parenthetical aliases, multi-position n-grams, and anti-collision rules.
    """
    s_title = candidate_series.get("title") or ""
    if candidate_series.get("is_unclassified"):
        return 0.0

    if is_khutbah_fiqh_collision(lesson_title, s_title):
        return 0.0
    if is_khutbah_fiqh_collision(lesson_title, "") and (
        "فقه" in normalize_ar(s_title) or "مباحث" in normalize_ar(s_title)
    ):
        return 0.95

    nt_lesson = normalize_ar(lesson_title)
    nt_series = normalize_ar(s_title)
    nt_series_core, aliases = _clean_series_core_for_matching(s_title)

    mb = candidate_series.get("matched_book") or {}
    mb_title = normalize_ar(mb.get("title") or "")
    if mb_title and len(mb_title) >= 5 and mb_title in nt_lesson:
        return 0.98

    # Check parenthetical book/program aliases (e.g. '(لحظات 2)', '(أم البراهين)', '(نظم الدرر السنية)')
    for alias in aliases:
        alias_tokens = [w for w in alias.split() if len(w) >= 3 and w not in SERIES_STOPWORDS]
        if len(alias_tokens) >= 2:
            if f"{alias_tokens[0]} {alias_tokens[1]}" in nt_lesson:
                return 0.94
            matched_alias_toks = [w for w in alias_tokens if has_ar_word(nt_lesson, w)]
            if len(matched_alias_toks) >= 2:
                return 0.91
        elif len(alias_tokens) == 1 and len(alias_tokens[0]) >= 4 and has_ar_word(nt_lesson, alias_tokens[0]):
            # Check if accompanied by a number if the alias had a number
            if re.search(r"\d", alias):
                if alias in nt_lesson:
                    return 0.94
            else:
                return 0.88

    if "سوره" in nt_series:
        m_surah = re.search(r"سوره\s+([\u0621-\u064a]+)", nt_series)
        if m_surah:
            surah_name = m_surah.group(1)
            if not has_ar_word(nt_lesson, surah_name):
                return 0.0
            if has_ar_word(nt_lesson, "سوره") or has_ar_word(nt_lesson, "تفسير"):
                return 0.93

    tokens = [
        w
        for w in re.split(r"[^\u0621-\u064a0-9]+", nt_series_core)
        if len(w) >= 3 and w not in SERIES_STOPWORDS
    ]
    if not tokens:
        return 0.0

    matched_tokens = [w for w in tokens if has_ar_word(nt_lesson, w)]
    if not matched_tokens:
        return 0.0

    # Check any adjacent 3-token or 2-token phrase from tokens in nt_lesson
    for i in range(len(tokens) - 2):
        phrase3 = f"{tokens[i]} {tokens[i + 1]} {tokens[i + 2]}"
        if phrase3 in nt_lesson:
            return 0.96
    for i in range(len(tokens) - 1):
        phrase2 = f"{tokens[i]} {tokens[i + 1]}"
        if phrase2 in nt_lesson:
            return 0.92

    # Check if two matched tokens appear adjacent in nt_lesson
    if len(matched_tokens) >= 2:
        for i in range(len(matched_tokens) - 1):
            if f"{matched_tokens[i]} {matched_tokens[i + 1]}" in nt_lesson:
                return 0.90

    ratio = len(matched_tokens) / len(tokens)
    if len(matched_tokens) >= 2 and ratio >= 0.5:
        return 0.85 * ratio
    if len(tokens) == 1 and len(matched_tokens) == 1 and len(tokens[0]) >= 5:
        return 0.80
    return 0.0


def _extract_unclassified_series_signature(title: str) -> str | None:
    """
    Extract a clean recurring book/series title from an unclassified lesson title
    (e.g. 'الدرس 1: ... | شرح متن الصرف الصغير' -> 'شرح متن الصرف الصغير')
    so repeated unclassified lessons of the same book can be clustered into a dedicated series.
    """
    t = str(title or "").strip()
    if "|" in t or " - " in t:
        parts = [p.strip() for p in re.split(r"\||\s+[-–—]\s+", t) if p.strip()]
        for seg in reversed(parts):
            seg_clean = re.sub(r"\s*[\[\(]?\s*\d+\s*[\]\)]?\s*$", "", seg).strip()
            if re.match(
                r"^(?:شرح|مدارسة|التعليق على|تعليق على|سلسلة|برنامج|دورة)\s+(?:كتاب\s+|متن\s+|نظم\s+|منظومة\s+|رسالة\s+)?[\u0621-\u064a\s]{4,40}$",
                seg_clean,
            ):
                return seg_clean

    # Match 'شرح (مبادئ دروس العربية (27) لمحمد محيي الدين)'
    m_par_book = re.match(r"^شرح\s*\(\s*([\u0621-\u064a\s]{5,35}?)\s*\(\s*[\d\u0660-\u0669]+\s*\)", t)
    if m_par_book:
        return f"شرح كتاب {m_par_book.group(1).strip()}"

    # Match 'نفائس السيرة : ...'
    if re.match(r"^نفائس السيرة\b", t):
        return "برنامج نفائس السيرة النبوية"

    # Match 'أشهر التساؤلات في رمضان (1) ...'
    if re.match(r"^أشهر التساؤلات في رمضان\b", t):
        return "أشهر التساؤلات في رمضان"

    # Match generic untitled livestreams 'بدأت قناة "..." بثًا مباشرًا'
    if re.match(r"^بدأت قناة\s+.*بث[اًًا]*\s+مباشر", t):
        return "بثوث مباشرة غير معنونة"

    return None


def stage2_semantic_classify_and_isolate_guests(
    series_list: list[dict[str, Any]],
    person_id: str,
    sheikh_info: dict[str, Any],
    video_catalog: dict[str, dict[str, Any]],
    raw_data: dict[str, Any],
) -> dict[str, Any]:
    """
    Stage 2:
    1. Isolate guest lectures (`كلمة الشيخ فلان` / `محاضرة الدكتور فلان` != channel owner)
       and contest/award ceremonies (`حفل اختتام المسابقة`) from book/structured series
       into `محاضرات وفعاليات عامة` (while protecting dedicated co-hosted/guest-taught series).
    2. Fix semantic keyword collisions (e.g. `مسألة الصلاة أثناء خطبة الإمام` moved out of
       `خطب الجمعة` into Fiqh series `دروس ومباحث في الفقه المالكي`).
    3. Route `Unclassified` videos semantically to their proper series (updating `appearances`
       in `video_catalog`/`raw_data`), cluster repeated unclassified matn series, or route
       remaining general items to general series.
    """
    guests_isolated: list[dict[str, Any]] = []
    collisions_fixed: list[dict[str, Any]] = []
    unclassified_routed: list[dict[str, Any]] = []

    guest_Groups_to_add: list[list[dict[str, Any]]] = []
    fiqh_collision_groups: list[list[dict[str, Any]]] = []
    uncl_groups_pool: list[list[dict[str, Any]]] = []

    kept_series: list[dict[str, Any]] = []
    for s in series_list:
        s_title = s.get("title") or ""
        if s.get("is_unclassified"):
            uncl_groups_pool.extend(lessons_to_groups(s.get("lessons") or []))
            continue

        is_guest_series = any(w in s_title for w in ["فعاليات", "الضيوف", "كلمات العلماء"])
        is_gen_series = is_general_series_title(s_title)
        groups = lessons_to_groups(s.get("lessons") or [])

        # Protect dedicated co-hosted or guest-taught series where >= 40% of lessons carry the scholar's name
        if not is_guest_series and len(groups) >= 4:
            flagged_cnt = sum(
                1 for g in groups if is_guest_or_event_lesson(g[0].get("title", ""), sheikh_info, s_title)
            )
            if flagged_cnt >= len(groups) * 0.4:
                is_guest_series = True

        remaining_groups: list[list[dict[str, Any]]] = []

        for grp in groups:
            parent = grp[0]
            p_title = parent.get("title", "")

            if not is_guest_series and is_guest_or_event_lesson(p_title, sheikh_info, s_title):
                guest_Groups_to_add.append(grp)
                guests_isolated.append(
                    {
                        "yt_id": parent["yt_id"],
                        "title": p_title,
                        "from_series": s_title,
                    }
                )
                continue

            if is_khutbah_fiqh_collision(p_title, s_title):
                fiqh_collision_groups.append(grp)
                collisions_fixed.append(
                    {
                        "yt_id": parent["yt_id"],
                        "title": p_title,
                        "from_series": s_title,
                    }
                )
                continue

            v_rec = video_catalog.get(parent["yt_id"], {})
            non_uncl_apps = [a for a in v_rec.get("appearances", []) if not a.get("is_unclassified")]
            if not is_gen_series and not non_uncl_apps:
                if _score_series_match(p_title, s) >= 0.62:
                    target_raw_id = s.get("raw_series_id") or s["id"]
                    for ep in grp:
                        er = video_catalog.get(ep["yt_id"])
                        if er is not None:
                            er["appearances"] = [
                                a for a in er.get("appearances", []) if not a.get("is_unclassified")
                            ]
                            er["appearances"].append(
                                {
                                    "raw_series_id": target_raw_id,
                                    "raw_series_title": s_title,
                                    "pos": ep.get("pos", 1),
                                    "is_unclassified": False,
                                }
                            )
                else:
                    uncl_groups_pool.append(grp)
                    continue

            remaining_groups.append(grp)

        s["lessons"] = groups_to_lessons(remaining_groups)
        kept_series.append(s)

    series_list[:] = kept_series

    unrouted_uncl_groups: list[list[dict[str, Any]]] = []

    for grp in uncl_groups_pool:
        parent = grp[0]
        p_title = parent.get("title", "")

        if is_guest_or_event_lesson(p_title, sheikh_info, ""):
            guest_Groups_to_add.append(grp)
            guests_isolated.append(
                {
                    "yt_id": parent["yt_id"],
                    "title": p_title,
                    "from_series": "غير مصنف",
                }
            )
            continue

        if is_khutbah_fiqh_collision(p_title, ""):
            fiqh_collision_groups.append(grp)
            collisions_fixed.append(
                {
                    "yt_id": parent["yt_id"],
                    "title": p_title,
                    "from_series": "غير مصنف",
                }
            )
            continue

        best_s = None
        best_score = 0.0
        for cand_s in series_list:
            sc = _score_series_match(p_title, cand_s)
            if sc > best_score:
                best_score = sc
                best_s = cand_s

        if best_s is not None and best_score >= 0.68:
            best_groups = lessons_to_groups(best_s["lessons"])
            exp_n = extract_lesson_num(p_title, best_s["title"])
            inserted = False
            if exp_n is not None and not is_general_series_title(best_s["title"]):
                for idx_g, ex_grp in enumerate(best_groups):
                    ex_n = extract_lesson_num(ex_grp[0].get("title", ""), best_s["title"])
                    if ex_n == exp_n:
                        # Attach as child of existing same-numbered lesson so we don't shift subsequent numbers
                        for item in grp:
                            item["is_child"] = True
                            item["parent_yt_id"] = ex_grp[0]["yt_id"]
                            ex_grp.append(item)
                        inserted = True
                        break
                    if ex_n is not None and ex_n > exp_n:
                        best_groups.insert(idx_g, grp)
                        inserted = True
                        break
            if not inserted:
                # Avoid leaving an unnumbered unclassified lesson at the very tail of a structured series
                nt_p = normalize_ar(p_title)
                is_closing_ep = any(w in nt_p for w in ["الاخير", "الاخيره", "خاتمه", "ختم", "اختتام"])
                if (
                    not is_general_series_title(best_s["title"])
                    and len(best_groups) >= 2
                    and exp_n is None
                    and not is_closing_ep
                ):
                    best_groups.insert(len(best_groups) - 1, grp)
                else:
                    best_groups.append(grp)
            best_s["lessons"] = groups_to_lessons(best_groups)
            target_raw_id = best_s.get("raw_series_id") or best_s["id"]
            for ep in grp:
                v_rec = video_catalog.get(ep["yt_id"])
                if v_rec is not None:
                    v_rec["appearances"] = [
                        a for a in v_rec.get("appearances", []) if not a.get("is_unclassified")
                    ]
                    if not any(a.get("raw_series_id") == target_raw_id for a in v_rec["appearances"]):
                        v_rec["appearances"].append(
                            {
                                "raw_series_id": target_raw_id,
                                "raw_series_title": best_s["title"],
                                "pos": len(best_s["lessons"]),
                                "is_unclassified": False,
                            }
                        )
            unclassified_routed.append(
                {
                    "yt_id": parent["yt_id"],
                    "title": p_title,
                    "to_series": best_s["title"],
                    "score": round(best_score, 3),
                }
            )
        else:
            unrouted_uncl_groups.append(grp)

    # Cluster repeated unrouted unclassified groups that share an explicit book/matn series signature (>= 3 lessons)
    sig_buckets: dict[str, list[list[dict[str, Any]]]] = {}
    sig_display_title: dict[str, str] = {}
    still_unrouted: list[list[dict[str, Any]]] = []
    for grp in unrouted_uncl_groups:
        sig_raw = _extract_unclassified_series_signature(grp[0].get("title", ""))
        if sig_raw:
            sig_norm = normalize_ar(sig_raw)
            sig_buckets.setdefault(sig_norm, []).append(grp)
            sig_display_title.setdefault(sig_norm, sig_raw)
        else:
            still_unrouted.append(grp)

    for sig_norm, bucket_grps in sig_buckets.items():
        if len(bucket_grps) >= 3:
            new_title = sig_display_title[sig_norm]
            clustered_s = get_or_create_series(
                series_list,
                person_id,
                new_title,
                category=infer_series_category(new_title),
                state="completed",
                note=f"سلسلة علمية مجمعة من الدروس غير المصنفة لـ: {new_title}.",
            )
            c_groups = lessons_to_groups(clustered_s["lessons"])
            c_groups.extend(bucket_grps)
            clustered_s["lessons"] = groups_to_lessons(c_groups)
            target_raw_id = clustered_s.get("raw_series_id") or clustered_s["id"]
            for grp in bucket_grps:
                parent = grp[0]
                for ep in grp:
                    v_rec = video_catalog.get(ep["yt_id"])
                    if v_rec is not None:
                        v_rec["appearances"] = [
                            a for a in v_rec.get("appearances", []) if not a.get("is_unclassified")
                        ]
                        v_rec["appearances"].append(
                            {
                                "raw_series_id": target_raw_id,
                                "raw_series_title": clustered_s["title"],
                                "pos": len(clustered_s["lessons"]),
                                "is_unclassified": False,
                            }
                        )
                unclassified_routed.append(
                    {
                        "yt_id": parent["yt_id"],
                        "title": parent.get("title", ""),
                        "to_series": clustered_s["title"],
                        "score": 0.90,
                    }
                )
        else:
            still_unrouted.extend(bucket_grps)

    for grp in still_unrouted:
        parent = grp[0]
        guest_Groups_to_add.append(grp)
        unclassified_routed.append(
            {
                "yt_id": parent["yt_id"],
                "title": parent.get("title", ""),
                "to_series": "محاضرات وفعاليات عامة",
                "score": 0.0,
            }
        )

    if fiqh_collision_groups:
        fiqh_s = None
        for s in series_list:
            nt = normalize_ar(s.get("title", ""))
            if ("فقه" in nt or "مباحث" in nt) and "خطب" not in nt and "اصول" not in nt and "نظم" not in nt:
                fiqh_s = s
                break
        if fiqh_s is None:
            fiqh_s = get_or_create_series(
                series_list,
                person_id,
                "دروس ومباحث في الفقه المالكي",
                category="الفقه وأصوله",
                state="completed",
                note="مباحث ومسائل فقهية محررة (مفصولة دلالياً عن خطب الجمعة).",
            )
        f_groups = lessons_to_groups(fiqh_s["lessons"])
        f_groups.extend(fiqh_collision_groups)
        fiqh_s["lessons"] = groups_to_lessons(f_groups)
        target_raw_id = fiqh_s.get("raw_series_id") or fiqh_s["id"]
        for grp in fiqh_collision_groups:
            for ep in grp:
                v_rec = video_catalog.get(ep["yt_id"])
                if v_rec is not None:
                    v_rec["appearances"] = [
                        a for a in v_rec.get("appearances", []) if not a.get("is_unclassified")
                    ]
                    v_rec["appearances"].append(
                        {
                            "raw_series_id": target_raw_id,
                            "raw_series_title": fiqh_s["title"],
                            "pos": len(fiqh_s["lessons"]),
                            "is_unclassified": False,
                        }
                    )

    if guest_Groups_to_add:
        guest_s = get_or_create_series(
            series_list,
            person_id,
            "محاضرات وفعاليات عامة",
            category="مواعظ ولقاءات عامة",
            state="completed",
            note="محاضرات عامة، وكلمات العلماء الضيوف، وحفلات الجوائز والمسابقات المعزولة عن شروح الكتب.",
        )
        g_groups = lessons_to_groups(guest_s["lessons"])
        g_groups.extend(guest_Groups_to_add)
        guest_s["lessons"] = groups_to_lessons(g_groups)

    raw_data["unique_videos"] = list(video_catalog.values())

    return {
        "guests_events_isolated_count": len(guests_isolated),
        "guests_events_isolated": guests_isolated,
        "anti_collision_moves_count": len(collisions_fixed),
        "anti_collision_moves": collisions_fixed,
        "unclassified_routed_count": len(unclassified_routed),
        "unclassified_routed": unclassified_routed,
    }


# ---------------------------------------------------------------------------
# Stage 3: Repair Inverted Parent-Child Livestreams
# ---------------------------------------------------------------------------


def stage3_fix_inverted_livestreams(
    series_list: list[dict[str, Any]],
    season_hijri_map: dict[str, Any] | None = None,
    min_duration: int = 300,
) -> dict[str, Any]:
    """
    Stage 3:
    1. In every `[Parent, Child_1, ...]` group where `0 < Parent.duration < min_duration`
       and at least one `Child.duration >= min_duration`:
       Promote the longest child (`>= 600s` or max duration `>= min_duration`) to be the main
       parent (`is_child: False`, `parent_yt_id: None`) and demote the interrupted short parent
       to a child (`is_child: True`, `parent_yt_id = new_parent.yt_id`, `display_no: "مقطع"`).
    2. Link standalone short livestreams (`< min_duration`) that share the exact same Hijri date
       with a full lesson (`>= 600s`) in the same series as a child (`display_no: "مقطع"`) under it.
    """
    inverted_fixed: list[dict[str, Any]] = []
    same_day_linked: list[dict[str, Any]] = []

    for s in series_list:
        groups = lessons_to_groups(s.get("lessons") or [])
        repaired_groups: list[list[dict[str, Any]]] = []

        for grp in groups:
            parent = grp[0]
            p_dur = parent.get("duration") or 0
            children = grp[1:]
            long_children = [
                ch
                for ch in children
                if isinstance(ch.get("duration"), (int, float))
                and ch["duration"] >= min_duration
                and not is_explicit_part_continuation(ch.get("title", ""))
            ]
            if 0 < p_dur < min_duration and long_children:
                new_parent = max(long_children, key=lambda c: c.get("duration") or 0)
                old_parent = parent
                orig_disp = old_parent.get("display_no", "")

                new_parent["is_child"] = False
                new_parent["parent_yt_id"] = None
                if orig_disp and (orig_disp.isdigit() or orig_disp in ALLOWED_MAIN_BADGES):
                    new_parent["display_no"] = orig_disp
                elif not str(new_parent.get("display_no", "")).isdigit():
                    new_parent["display_no"] = ""

                old_parent["is_child"] = True
                old_parent["parent_yt_id"] = new_parent["yt_id"]
                old_parent["display_no"] = "مقطع"

                new_grp = [new_parent, old_parent]
                for ch in children:
                    if ch is new_parent:
                        continue
                    ch["is_child"] = True
                    ch["parent_yt_id"] = new_parent["yt_id"]
                    if not ch.get("display_no"):
                        ch["display_no"] = "تتمة"
                    new_grp.append(ch)

                repaired_groups.append(new_grp)
                inverted_fixed.append(
                    {
                        "series_id": s["id"],
                        "old_parent_yt_id": old_parent["yt_id"],
                        "old_parent_dur": p_dur,
                        "new_parent_yt_id": new_parent["yt_id"],
                        "new_parent_dur": new_parent.get("duration"),
                    }
                )
            else:
                repaired_groups.append(grp)

        full_by_date: dict[tuple[int, int, int], list[dict[str, Any]]] = {}
        for grp in repaired_groups:
            p = grp[0]
            p_dur = p.get("duration") or 0
            if p_dur >= max(600, min_duration):
                dt = hi.parse_hijri(p.get("title", ""), season_hijri_map=season_hijri_map)
                if dt:
                    full_by_date.setdefault(dt, grp)

        final_groups: list[list[dict[str, Any]]] = []
        for grp in repaired_groups:
            p = grp[0]
            p_dur = p.get("duration") or 0
            p_disp = str(p.get("display_no") or "")
            if (
                len(grp) == 1
                and 0 < p_dur < min_duration
                and p_disp not in ALLOWED_MAIN_BADGES
                and not is_promo_title(p.get("title", ""), p_disp)
            ):
                dt = hi.parse_hijri(p.get("title", ""), season_hijri_map=season_hijri_map)
                if dt and dt in full_by_date and full_by_date[dt] is not grp:
                    target_grp = full_by_date[dt]
                    p["is_child"] = True
                    p["parent_yt_id"] = target_grp[0]["yt_id"]
                    p["display_no"] = "مقطع"
                    target_grp.append(p)
                    same_day_linked.append(
                        {
                            "series_id": s["id"],
                            "short_yt_id": p["yt_id"],
                            "short_dur": p_dur,
                            "parent_yt_id": target_grp[0]["yt_id"],
                            "hijri_date": dt,
                        }
                    )
                    continue
            final_groups.append(grp)

        s["lessons"] = groups_to_lessons(final_groups)

    return {
        "inverted_fixed_count": len(inverted_fixed),
        "inverted_fixed": inverted_fixed,
        "same_day_linked_count": len(same_day_linked),
        "same_day_linked": same_day_linked,
    }


# ---------------------------------------------------------------------------
# Stage 4: Long Series Purification from Short Clips & Promos
# ---------------------------------------------------------------------------


def stage4_purge_short_clips_and_promos(
    series_list: list[dict[str, Any]],
    person_id: str,
    season_hijri_map: dict[str, Any] | None = None,
    min_duration: int = 300,
    min_series_median: int = 900,
    min_duration_contemplative: int = 120,
) -> dict[str, Any]:
    """
    Stage 4:
    In any long-form structured series (`not is_general` and `median >= min_series_median` or >= 600):
    1. Move series promos/teasers to the very start of the series with `display_no: "برومو"`
       (and second promo as child `display_no: "برومو 2"`).
    2. Attach short excerpts taken from a specific lesson in the same series (matching lesson number
       or Hijri date) as child (`is_child: True, display_no: "مقطع"`) under that parent lesson.
    3. Move standalone short supplications/duas (`< min_duration`) with their children to
       «أدعية وابتهالات وتضرع إلى الله».
    4. Move remaining standalone short clips (`< min_duration` or clip-titled) with their children
       to «مقتطفات وفوائد قصيرة».
    """
    promos_positioned: list[dict[str, Any]] = []
    excerpts_attached: list[dict[str, Any]] = []
    duas_moved: list[dict[str, Any]] = []
    clips_moved: list[dict[str, Any]] = []

    dua_groups_to_move: list[list[dict[str, Any]]] = []
    clip_groups_to_move: list[list[dict[str, Any]]] = []

    for s in list(series_list):
        s_title = s.get("title") or ""
        if is_general_series_title(s_title):
            continue

        groups = lessons_to_groups(s.get("lessons") or [])
        if not groups:
            continue

        is_contemplative = any(cw in s_title for cw in ["تأمل", "ختم القرآن"])
        effective_min_dur = min_duration_contemplative if is_contemplative else min_duration

        all_durs = [
            grp[0].get("duration") or 0
            for grp in groups
            if (grp[0].get("duration") or 0) > 0
        ]
        long_durs = [d for d in all_durs if d >= effective_min_dur]
        med_all = statistics.median(all_durs) if len(all_durs) >= 4 else (statistics.median(all_durs) if all_durs else 0)
        med_long = statistics.median(long_durs) if long_durs else 0
        is_long_series = (med_all >= min_series_median) or (med_long >= min_series_median)

        promo_groups: list[list[dict[str, Any]]] = []
        full_groups: list[list[dict[str, Any]]] = []
        short_candidates: list[list[dict[str, Any]]] = []

        for grp in groups:
            p = grp[0]
            p_title = p.get("title", "")
            p_disp = str(p.get("display_no") or "").strip()
            p_dur = p.get("duration") or 0

            if is_promo_title(p_title, p_disp):
                promo_groups.append(grp)
                continue

            if p_disp in {"مقدمة", "فهرس", "ختام"} and not is_clip_title(p_title, s_title):
                full_groups.append(grp)
                continue

            is_short = is_long_series and (0 < p_dur < effective_min_dur)
            is_clip_named = (med_all >= 600 or med_long >= 600) and is_clip_title(p_title, s_title)
            is_bad_disp = p_disp in {"مقطع", "فائدة"}

            if is_short or is_clip_named or is_bad_disp:
                short_candidates.append(grp)
            else:
                full_groups.append(grp)

        full_by_num: dict[int, list[dict[str, Any]]] = {}
        full_by_date: dict[tuple[int, int, int], list[dict[str, Any]]] = {}
        for f_grp in full_groups:
            fp = f_grp[0]
            fn = extract_lesson_num(fp.get("title", ""), s_title)
            if fn is not None and fn not in full_by_num:
                full_by_num[fn] = f_grp
            elif str(fp.get("display_no", "")).isdigit():
                dn = int(fp["display_no"])
                if dn not in full_by_num:
                    full_by_num[dn] = f_grp
            fdt = hi.parse_hijri(fp.get("title", ""), season_hijri_map=season_hijri_map)
            if fdt and fdt not in full_by_date:
                full_by_date[fdt] = f_grp

        for sc_grp in short_candidates:
            sp = sc_grp[0]
            sp_title = sp.get("title", "")
            sp_dur = sp.get("duration") or 0

            ref_num = extract_lesson_num(sp_title, s_title)
            ref_dt = hi.parse_hijri(sp_title, season_hijri_map=season_hijri_map)
            target_full_grp = None
            if (
                ref_num is not None
                and ref_num in full_by_num
                and any(w in sp_title for w in ["مقطع", "مقتطف", "فائدة", "خلاصة", "ملخص"])
            ):
                target_full_grp = full_by_num[ref_num]
            elif ref_dt is not None and ref_dt in full_by_date:
                target_full_grp = full_by_date[ref_dt]

            if target_full_grp is not None:
                for item in sc_grp:
                    item["is_child"] = True
                    item["parent_yt_id"] = target_full_grp[0]["yt_id"]
                    item["display_no"] = "مقطع"
                    target_full_grp.append(item)
                excerpts_attached.append(
                    {
                        "series_id": s["id"],
                        "clip_yt_id": sp["yt_id"],
                        "parent_yt_id": target_full_grp[0]["yt_id"],
                        "title": sp_title,
                    }
                )
            elif is_dua_title(sp_title):
                dua_groups_to_move.append(sc_grp)
                duas_moved.append(
                    {
                        "from_series_id": s["id"],
                        "yt_id": sp["yt_id"],
                        "duration": sp_dur,
                        "title": sp_title,
                    }
                )
            else:
                clip_groups_to_move.append(sc_grp)
                clips_moved.append(
                    {
                        "from_series_id": s["id"],
                        "yt_id": sp["yt_id"],
                        "duration": sp_dur,
                        "title": sp_title,
                    }
                )

        assembled_groups: list[list[dict[str, Any]]] = []
        if promo_groups:
            flat_promos: list[dict[str, Any]] = [item for pg in promo_groups for item in pg]
            first_promo = flat_promos[0]
            first_promo["is_child"] = False
            first_promo["parent_yt_id"] = None
            first_promo["display_no"] = "برومو"
            promo_master_grp = [first_promo]
            for p_idx, extra_p in enumerate(flat_promos[1:], 2):
                extra_p["is_child"] = True
                extra_p["parent_yt_id"] = first_promo["yt_id"]
                extra_p["display_no"] = f"برومو {p_idx}"
                promo_master_grp.append(extra_p)
            assembled_groups.append(promo_master_grp)
            promos_positioned.append(
                {
                    "series_id": s["id"],
                    "promo_yt_id": first_promo["yt_id"],
                    "total_promos": len(flat_promos),
                }
            )

        assembled_groups.extend(full_groups)
        s["lessons"] = groups_to_lessons(assembled_groups)

    if dua_groups_to_move:
        dua_s = get_or_create_series(
            series_list,
            person_id,
            "أدعية وابتهالات وتضرع إلى الله",
            category="التزكية والأخلاق",
            state="completed",
            note="الأدعية والابتهالات والمناجاة المستقلة المنتقاة من مجالس الشيخ.",
        )
        d_groups = lessons_to_groups(dua_s["lessons"])
        d_groups.extend(dua_groups_to_move)
        dua_s["lessons"] = groups_to_lessons(d_groups)

    if clip_groups_to_move:
        clip_s = get_or_create_series(
            series_list,
            person_id,
            "مقتطفات وفوائد قصيرة",
            category="مواعظ ولقاءات عامة",
            state="completed",
            note="المقاطع القصيرة والفوائد المنتقاة المفصولة عن السلاسل المنهجية الطويلة.",
        )
        c_groups = lessons_to_groups(clip_s["lessons"])
        c_groups.extend(clip_groups_to_move)
        clip_s["lessons"] = groups_to_lessons(c_groups)

    return {
        "promos_positioned_count": len(promos_positioned),
        "promos_positioned": promos_positioned,
        "excerpts_attached_count": len(excerpts_attached),
        "excerpts_attached": excerpts_attached,
        "duas_moved_count": len(duas_moved),
        "duas_moved": duas_moved,
        "clips_moved_count": len(clips_moved),
        "clips_moved": clips_moved,
    }


# ---------------------------------------------------------------------------
# Stage 5: Ungrouping False Merges of Long Generic-Titled Lessons
# ---------------------------------------------------------------------------


def _min_playlist_pos_diff(
    ep1: dict[str, Any],
    ep2: dict[str, Any],
    raw_pos_map: dict[str, dict[str, int]],
) -> int | None:
    """Return minimum `|pos1 - pos2|` across shared raw playlists, or from lesson `pos` fields."""
    m1 = raw_pos_map.get(ep1["yt_id"], {})
    m2 = raw_pos_map.get(ep2["yt_id"], {})
    shared = set(m1.keys()) & set(m2.keys())
    diffs = [abs(m1[k] - m2[k]) for k in shared if isinstance(m1[k], int) and isinstance(m2[k], int)]
    if diffs:
        return min(diffs)
    p1 = ep1.get("pos")
    p2 = ep2.get("pos")
    if isinstance(p1, int) and isinstance(p2, int):
        return abs(p1 - p2)
    return None


def stage5_ungroup_false_merges(
    series_list: list[dict[str, Any]],
    raw_pos_map: dict[str, dict[str, int]],
    season_hijri_map: dict[str, Any] | None = None,
    long_lesson_threshold: int = 1200,
) -> dict[str, Any]:
    """
    Stage 5:
    If a long child (`>= 1200s`) is attached under a long parent (`>= 1200s`) without an explicit
    continuation marker (`الجزء الثاني / ج2 / (2) / تتمة`) in its title, and either:
      - their playlist position difference `|pos1 - pos2| > 1`, OR
      - they carry different explicit dates,
    ungroup the child so it becomes an independent main lesson (`is_child: False`).
    """
    ungrouped: list[dict[str, Any]] = []

    for s in series_list:
        groups = lessons_to_groups(s.get("lessons") or [])
        new_groups: list[list[dict[str, Any]]] = []

        for grp in groups:
            parent = grp[0]
            p_dur = parent.get("duration") or 0
            if p_dur < long_lesson_threshold or len(grp) <= 1:
                new_groups.append(grp)
                continue

            p_dt = hi.parse_hijri(parent.get("title", ""), season_hijri_map=season_hijri_map)
            kept_children: list[dict[str, Any]] = []
            promoted_independents: list[list[dict[str, Any]]] = []

            for ch in grp[1:]:
                ch_dur = ch.get("duration") or 0
                ch_title = ch.get("title", "")
                ch_disp = str(ch.get("display_no") or "").strip()

                if (
                    ch_dur >= long_lesson_threshold
                    and not is_explicit_part_continuation(ch_title)
                    and ch_disp not in {"نسخة", "نسخة 2", "قسم القصيدة", "برومو 2"}
                ):
                    ch_dt = hi.parse_hijri(ch_title, season_hijri_map=season_hijri_map)
                    pos_diff = _min_playlist_pos_diff(parent, ch, raw_pos_map)
                    dates_differ = (p_dt is not None and ch_dt is not None and p_dt != ch_dt)
                    pos_separated = (pos_diff is not None and pos_diff > 1)

                    if dates_differ or pos_separated:
                        ch["is_child"] = False
                        ch["parent_yt_id"] = None
                        ch["display_no"] = ""
                        promoted_independents.append([ch])
                        ungrouped.append(
                            {
                                "series_id": s["id"],
                                "parent_yt_id": parent["yt_id"],
                                "ungrouped_yt_id": ch["yt_id"],
                                "duration": ch_dur,
                                "pos_diff": pos_diff,
                                "title": ch_title,
                            }
                        )
                        continue

                kept_children.append(ch)

            new_groups.append([parent] + kept_children)
            new_groups.extend(promoted_independents)

        s["lessons"] = groups_to_lessons(new_groups)

    return {
        "false_merges_ungrouped_count": len(ungrouped),
        "false_merges_ungrouped": ungrouped,
    }


# ---------------------------------------------------------------------------
# Stage 6: Hijri Date Interpolation & Chronological Re-Ordering of Truncated Titles
# ---------------------------------------------------------------------------


def stage6_interpolate_hijri_and_reorder(
    series_list: list[dict[str, Any]],
    raw_data: dict[str, Any],
    season_hijri_map: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Stage 6:
    Uses `hijri_interpolator.py` and `season_hijri_map` to recover Hijri dates for lessons
    whose titles were truncated at 100 chars (or lacked trailing dates) and were dumped at
    the tail of chronological series, re-inserting them into their true chronological position.
    """
    explicit_dates, best_interp = hi.build_interpolated_dates(
        raw_data, season_hijri_map=season_hijri_map
    )

    for s in series_list:
        for ep in s.get("lessons") or []:
            vid = ep["yt_id"]
            if vid not in explicit_dates:
                dt = hi.parse_hijri(ep.get("title", ""), season_hijri_map=season_hijri_map)
                if dt:
                    explicit_dates[vid] = dt

        pos_sorted = sorted(
            [ep for ep in (s.get("lessons") or []) if not ep.get("is_child")],
            key=lambda x: x.get("pos", 999999),
        )
        dated_pts = [
            (idx, hi.to_days(explicit_dates[ep["yt_id"]]), explicit_dates[ep["yt_id"]])
            for idx, ep in enumerate(pos_sorted)
            if ep["yt_id"] in explicit_dates
        ]
        if dated_pts:
            for idx, ep in enumerate(pos_sorted):
                vid = ep["yt_id"]
                if vid in explicit_dates or vid in best_interp:
                    continue
                prevs = [p for p in dated_pts if p[0] < idx]
                nexts = [p for p in dated_pts if p[0] > idx]
                if prevs and nexts:
                    i1, d1, _ = prevs[-1]
                    i2, d2, _ = nexts[0]
                    frac = (idx - i1) / (i2 - i1)
                    interp_d = d1 + frac * (d2 - d1)
                    span = abs(d2 - d1) + (i2 - i1)
                    best_interp[vid] = (span, interp_d, hi.from_days(interp_d), s.get("title", ""))

    reordered_lessons: list[dict[str, Any]] = []

    for s in series_list:
        groups = lessons_to_groups(s.get("lessons") or [])
        if len(groups) < 3:
            continue

        lead_groups: list[list[dict[str, Any]]] = []
        main_groups: list[list[dict[str, Any]]] = []
        tail_groups: list[list[dict[str, Any]]] = []

        for grp in groups:
            disp = str(grp[0].get("display_no") or "").strip()
            if disp in {"برومو", "مقدمة", "فهرس"} and not main_groups:
                lead_groups.append(grp)
            elif disp == "ختام":
                tail_groups.append(grp)
            else:
                main_groups.append(grp)

        if len(main_groups) < 3:
            continue

        group_days: list[float | None] = []
        has_tail_inversion = False
        max_seen_days = -1.0

        for grp in main_groups:
            p = grp[0]
            vid = p["yt_id"]
            if vid in explicit_dates:
                dt = explicit_dates[vid]
                d_val = float(hi.to_days(dt))
                p["hijri_date"] = f"{dt[0]:04d}-{dt[1]:02d}-{dt[2]:02d}"
                group_days.append(d_val)
            elif vid in best_interp:
                _, interp_d, dt_tuple, _ = best_interp[vid]
                d_val = float(interp_d)
                p["interpolated_hijri"] = f"{dt_tuple[0]:04d}-{dt_tuple[1]:02d}-{dt_tuple[2]:02d}"
                group_days.append(d_val)
            else:
                d_val = None
                group_days.append(None)

            if d_val is not None:
                if max_seen_days > 0 and d_val < max_seen_days - 2:
                    has_tail_inversion = True
                if d_val > max_seen_days:
                    max_seen_days = d_val

        dated_vals = [d for d in group_days if d is not None]
        dated_count = len(dated_vals)
        dec_date_pairs = sum(1 for a, b in zip(dated_vals, dated_vals[1:]) if a > b + 1)
        inc_date_pairs = sum(1 for a, b in zip(dated_vals, dated_vals[1:]) if a < b - 1)
        is_reverse_dated = dec_date_pairs > inc_date_pairs * 2

        if (
            dated_count >= max(3, int(len(main_groups) * 0.65))
            and has_tail_inversion
            and not is_reverse_dated
        ):
            indexed_groups = []
            for idx, (grp, d_val) in enumerate(zip(main_groups, group_days)):
                sort_d = d_val if d_val is not None else (max_seen_days + idx + 1)
                indexed_groups.append((sort_d, idx, grp))

            sorted_indexed = sorted(indexed_groups, key=lambda x: (x[0], x[1]))
            new_main_groups = [item[2] for item in sorted_indexed]

            for new_pos, (_, old_pos, grp) in enumerate(sorted_indexed):
                if new_pos != old_pos:
                    reordered_lessons.append(
                        {
                            "series_id": s["id"],
                            "yt_id": grp[0]["yt_id"],
                            "old_group_idx": old_pos + 1,
                            "new_group_idx": new_pos + 1,
                            "hijri": grp[0].get("interpolated_hijri") or grp[0].get("hijri_date"),
                            "title": grp[0].get("title", ""),
                        }
                    )

            s["lessons"] = groups_to_lessons(lead_groups + new_main_groups + tail_groups)

    return {
        "explicit_dates_count": len(explicit_dates),
        "interpolated_dates_count": len(best_interp),
        "reordered_lessons_count": len(reordered_lessons),
        "reordered_lessons": reordered_lessons,
    }


# ---------------------------------------------------------------------------
# Stage 7: Strictly Monotonic display_no & Sub-Number Disambiguation
# ---------------------------------------------------------------------------


def _rewrite_conflicting_title_number(title: str, new_num: int, old_num: int) -> str:
    """
    When merging multi-season series (`1..3 -> 1..2`) or fixing a rogue sub-number in a title,
    ensure `deep_scanner_all.extract_explicit_num(title)` matches `new_num` while preserving
    the original season/sub-council number in parentheses `(م <old_num>)` per SKILL.md §2.5.
    """
    t = str(title)
    pat = re.compile(
        r"((?:الدرس|درس|الحلقة|حلقة|حـ|المجلس|مجلس|المحاضرة|محاضرة|لقاء|اللقاء)\s*(?:الـ?\s*)?\(?0*)"
        + str(old_num)
        + r"(\)?)"
    )
    m = pat.search(dsa.norm(t))
    if m:
        start, end = m.span()
        updated = t[:start] + f"الدرس {new_num} (م {old_num})" + t[end:]
        if dsa.extract_explicit_num(updated) == new_num:
            return updated
    return f"الدرس {new_num} (م {old_num}) | {t}"


def stage7_strict_monotonic_numbering(
    series_list: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Stage 7:
    Enforces strictly monotonic `display_no` across all series with zero `NUM_RESET`,
    zero `NUM_JUMP`, and zero `NUM_MISMATCH`.
    """
    resets_fixed: list[dict[str, Any]] = []
    mismatches_fixed: list[dict[str, Any]] = []
    qasida_attached: list[dict[str, Any]] = []

    for s in series_list:
        s_title = s.get("title") or ""
        is_gen = is_general_series_title(s_title)
        groups = lessons_to_groups(s.get("lessons") or [])
        if not groups:
            continue

        is_qasida_series = any(w in s_title for w in ["قصائد", "قصيدة", "ديوان"])
        filtered_groups: list[list[dict[str, Any]]] = []
        for grp in groups:
            p = grp[0]
            p_title = p.get("title", "")
            if (
                not is_gen
                and not is_qasida_series
                and filtered_groups
                and re.search(r"(?:^|\s)وقصيدة\s*:|شرح قصيدة", p_title)
                and dsa.extract_explicit_num(p_title) is None
            ):
                prev_grp = filtered_groups[-1]
                for item in grp:
                    item["is_child"] = True
                    item["parent_yt_id"] = prev_grp[0]["yt_id"]
                    item["display_no"] = "قسم القصيدة"
                    prev_grp.append(item)
                qasida_attached.append({"series_id": s["id"], "yt_id": p["yt_id"], "title": p_title})
            else:
                filtered_groups.append(grp)

        lead_groups: list[list[dict[str, Any]]] = []
        main_groups: list[list[dict[str, Any]]] = []
        tail_groups: list[list[dict[str, Any]]] = []

        for grp in filtered_groups:
            p = grp[0]
            disp = str(p.get("display_no") or "").strip()
            if disp in {"برومو", "مقدمة", "فهرس"} and not main_groups:
                if disp == "مقدمة" and "مقدمات" in s_title and "المقدمة" in p.get("title", ""):
                    main_groups.append(grp)
                else:
                    lead_groups.append(grp)
            elif disp == "ختام":
                tail_groups.append(grp)
            else:
                main_groups.append(grp)

        if not is_gen and len(main_groups) >= 3:
            raw_exp = [extract_lesson_num(grp[0].get("title", ""), s_title) for grp in main_groups]
            pres = [n for n in raw_exp if n is not None]
            if len(pres) >= 3:
                dec_pairs = sum(1 for a, b in zip(pres, pres[1:]) if a > b)
                inc_pairs = sum(1 for a, b in zip(pres, pres[1:]) if a < b)
                if dec_pairs > inc_pairs * 2 and pres[0] > pres[-1]:
                    main_groups.reverse()
                    raw_exp = [extract_lesson_num(grp[0].get("title", ""), s_title) for grp in main_groups]
                    pres = [n for n in raw_exp if n is not None]

            is_heavily_numbered = len(pres) >= len(main_groups) * 0.65
            # Merge consecutive groups that share the exact same lesson number where one is a continuation or duplicate recording
            merged_main: list[list[dict[str, Any]]] = []
            for idx_m, grp in enumerate(main_groups):
                g_num = extract_lesson_num(grp[0].get("title", ""), s_title)
                if (
                    merged_main
                    and g_num is not None
                    and g_num == extract_lesson_num(merged_main[-1][0].get("title", ""), s_title)
                ):
                    prev_grp = merged_main[-1]
                    prev_is_cont = is_explicit_part_continuation(prev_grp[0].get("title", ""))
                    curr_is_cont = is_explicit_part_continuation(grp[0].get("title", ""))
                    next_num = (
                        extract_lesson_num(main_groups[idx_m + 1][0].get("title", ""), s_title)
                        if idx_m + 1 < len(main_groups)
                        else None
                    )
                    if curr_is_cont or prev_is_cont or (is_heavily_numbered and next_num == g_num + 1):
                        if prev_is_cont and not curr_is_cont:
                            # Swap so the non-continuation is the parent
                            new_parent_grp = list(grp)
                            for item in prev_grp:
                                item["is_child"] = True
                                item["parent_yt_id"] = new_parent_grp[0]["yt_id"]
                                new_parent_grp.append(item)
                            merged_main[-1] = new_parent_grp
                        else:
                            for item in grp:
                                item["is_child"] = True
                                item["parent_yt_id"] = prev_grp[0]["yt_id"]
                                prev_grp.append(item)
                        continue
                merged_main.append(grp)
            main_groups = merged_main

        exp_nums = [extract_lesson_num(grp[0].get("title", ""), s_title) for grp in main_groups]
        present_nums = [n for n in exp_nums if n is not None]
        numbered_ratio = len(present_nums) / max(1, len(main_groups))

        if (
            not is_gen
            and len(present_nums) >= 3
            and numbered_ratio >= 0.60
            and present_nums != sorted(present_nums)
            and max(present_nums) - min(present_nums) <= len(main_groups) * 2 + 15
        ):
            # Interpolate sort keys for unnumbered items so they stay in their relative slot
            sort_keys: list[float] = []
            for idx_g, n_val in enumerate(exp_nums):
                if n_val is not None:
                    sort_keys.append(float(n_val))
                else:
                    prev_known = next(
                        ((j, exp_nums[j]) for j in range(idx_g - 1, -1, -1) if exp_nums[j] is not None),
                        None,
                    )
                    if prev_known is not None:
                        sort_keys.append(float(prev_known[1]) + (idx_g - prev_known[0]) * 0.1)
                    else:
                        sort_keys.append(float(min(present_nums)) - (len(main_groups) - idx_g) * 0.1)
            paired = list(zip(sort_keys, range(len(main_groups)), main_groups))
            paired.sort(key=lambda x: (x[0], x[1]))
            main_groups = [x[2] for x in paired]
            exp_nums = [extract_lesson_num(grp[0].get("title", ""), s_title) for grp in main_groups]
            present_nums = [n for n in exp_nums if n is not None]

        start_num = 1
        if not is_gen and numbered_ratio >= 0.65:
            known_pairs = [(i, n) for i, n in enumerate(exp_nums) if n is not None]
            if known_pairs:
                first_idx, first_val = known_pairs[0]
                inferred_start = first_val - first_idx
                if 1 <= inferred_start <= 50:
                    if len(known_pairs) == 1 or abs((known_pairs[1][1] - known_pairs[1][0]) - inferred_start) <= 3:
                        start_num = inferred_start
                elif 50 < inferred_start <= 1000 and len(known_pairs) >= 2 and numbered_ratio >= 0.80:
                    if abs((known_pairs[1][1] - known_pairs[1][0]) - inferred_start) <= 2:
                        start_num = inferred_start

        prev_n = start_num - 1
        for idx_g, grp in enumerate(main_groups):
            p = grp[0]
            old_disp = str(p.get("display_no") or "").strip()
            exp_n = exp_nums[idx_g]
            scanner_exp_n = dsa.extract_explicit_num(p.get("title", ""))

            if is_gen:
                target_n = prev_n + 1
            elif exp_n is not None and exp_n == prev_n + 1:
                target_n = exp_n
            elif (
                exp_n is not None
                and exp_n > prev_n + 1
                and (exp_n - prev_n <= 15 or prev_n == start_num - 1)
                and numbered_ratio >= 0.65
            ):
                # Lookahead verification: confirm subsequent numbered lesson also advances from exp_n
                next_known = next(
                    ((j, exp_nums[j]) for j in range(idx_g + 1, len(main_groups)) if exp_nums[j] is not None),
                    None,
                )
                if next_known is None or next_known[1] >= exp_n + (next_known[0] - idx_g):
                    target_n = exp_n
                else:
                    target_n = prev_n + 1
            else:
                target_n = prev_n + 1

            if (
                scanner_exp_n is not None
                and scanner_exp_n != target_n
                and abs(scanner_exp_n - target_n) <= 50
                and not is_gen
            ):
                p["title"] = _rewrite_conflicting_title_number(p["title"], target_n, scanner_exp_n)
                resets_fixed.append(
                    {
                        "series_id": s["id"],
                        "yt_id": p["yt_id"],
                        "old_disp": old_disp,
                        "old_title_num": scanner_exp_n,
                        "new_disp": str(target_n),
                    }
                )
            elif old_disp != str(target_n):
                if old_disp.isdigit() and int(old_disp) <= prev_n:
                    resets_fixed.append(
                        {
                            "series_id": s["id"],
                            "yt_id": p["yt_id"],
                            "old_disp": old_disp,
                            "new_disp": str(target_n),
                        }
                    )
                else:
                    mismatches_fixed.append(
                        {
                            "series_id": s["id"],
                            "yt_id": p["yt_id"],
                            "old_disp": old_disp,
                            "new_disp": str(target_n),
                        }
                    )

            p["display_no"] = str(target_n)
            p["is_child"] = False
            p["parent_yt_id"] = None
            prev_n = target_n

        all_groups = lead_groups + main_groups + tail_groups
        for grp in all_groups:
            parent = grp[0]
            parent["is_child"] = False
            parent["parent_yt_id"] = None
            p_yt = parent["yt_id"]
            part_counter = 2
            for ch in grp[1:]:
                ch["is_child"] = True
                ch["parent_yt_id"] = p_yt
                c_disp = str(ch.get("display_no") or "").strip()
                if not c_disp or c_disp.isdigit() or c_disp in ALLOWED_MAIN_BADGES:
                    c_dur = ch.get("duration") or 0
                    if c_dur < 300:
                        ch["display_no"] = "مقطع"
                    else:
                        ch["display_no"] = f"ج{part_counter}"
                        part_counter += 1

        s["lessons"] = groups_to_lessons(all_groups)

    return {
        "resets_fixed_count": len(resets_fixed),
        "resets_fixed": resets_fixed,
        "mismatches_fixed_count": len(mismatches_fixed),
        "mismatches_fixed": mismatches_fixed,
        "qasida_attached_count": len(qasida_attached),
        "qasida_attached": qasida_attached,
    }


# ---------------------------------------------------------------------------
# Stage 8: Series State, Chapter Boundaries, JSON/DB & _meta.json Export
# ---------------------------------------------------------------------------


def _extract_topic_boundary(lesson_title: str, fallback: str) -> str:
    """Extract a clean chapter/topic phrase from a lesson title for boundary documentation."""
    t = str(lesson_title or "").strip()
    m = re.search(
        r"((?:كتاب|باب|فصل|مبحث|قاعدة|القطب|المقدمة|خاتمة)[^|\-–—\(\)\n]{3,55})",
        t,
    )
    if m:
        return m.group(1).strip()
    cleaned = re.sub(
        r"^(?:بث مباشر\s*[\-–—:|]*\s*|#مباشر\s*[\-–—:|]*\s*)?(?:الدرس|درس|المجلس|مجلس|الحلقة|حلقة)\s*(?:[\d\u0660-\u0669]+|الأول|الثاني|الثالث|الرابع|الخامس|السادس|السابع|الثامن|التاسع|العاشر|الأخير)\s*[\-–—:|_]*\s*",
        "",
        t,
    ).strip()
    parts = [p.strip() for p in re.split(r"[\|\-–—_:]", cleaned) if len(p.strip()) >= 4]
    if parts:
        return parts[-1][:55]
    return fallback


def _resolve_series_state(
    s_title: str,
    s_note: str,
    raw_state: str | None,
    main_lessons: list[dict[str, Any]],
) -> str:
    """
    Resolve series `state` (`completed` | `stopped` | `ongoing`) deterministically.
    Does not blindly trust `raw_state == 'completed'` when `s_note` is empty or raw `'تصنيف:'`.
    """
    if raw_state in ("stopped", "ongoing"):
        return raw_state

    is_curated_note = bool(
        s_note
        and not s_note.startswith("تصنيف:")
        and not s_note.startswith("سلسلة مخصصة لـ:")
        and not s_note.startswith("سلسلة علمية مجمعة")
    )

    nt_title = normalize_ar(re.sub(r"[\|\-–—_/:]", " ", s_title))
    nt_note = normalize_ar(re.sub(r"[\|\-–—_/:]", " ", s_note)) if is_curated_note else ""
    n_eps = len(main_lessons)
    last_ep_title = main_lessons[-1].get("title", "") if main_lessons else ""
    tail_titles = " ".join(ep.get("title", "") for ep in main_lessons[-3:])
    nt_last = normalize_ar(re.sub(r"[\|\-–—_/:]", " ", last_ep_title))
    nt_tail = normalize_ar(re.sub(r"[\|\-–—_/:]", " ", tail_titles))
    nt_all = f"{nt_title} {nt_note} {nt_tail}"

    # 1. Explicit markers in title, curated note, or tail lessons
    if any(
        normalize_ar(w) in f"{nt_title} {nt_note}"
        for w in ["توقف", "متوقف", "لم يكتمل", "غير مكتمل", "إلى باب", "من المقدمة إلى"]
    ):
        return "stopped"
    if any(normalize_ar(w) in f"{nt_title} {nt_note}" for w in ["مستمر", "مستمرة", "جاري", "جارية"]):
        return "ongoing"
    if any(normalize_ar(w) in nt_tail for w in ["استشهد فيه", "قبل استشهاده"]):
        return "stopped"
    if "سوره الكهف" in nt_title and "فانطلقا حتي اذا ركبا" in nt_tail:
        return "stopped"

    # If the input already had an explicit human-curated note and state='completed', preserve it
    if raw_state == "completed" and is_curated_note:
        return "completed"

    # 2. Explicit completion markers in title, note, or tail lessons
    completion_markers = [
        "تمام الكتاب",
        "ختام الكتاب",
        "خاتمة الكتاب",
        "نهاية الكتاب",
        "نهاية المتن",
        "الدرس الأخير",
        "المجلس الأخير",
        "الحلقة الأخيرة",
        "المحاضرة الأخيرة",
        "اللقاء الأخير",
        "شرح كامل",
        "مكتمل",
        "مكتملة",
        "ختام السلسلة",
        "تمام المتن",
        "مجلس الختم",
        "ختم الكتاب",
        "ختم كتاب",
        "ختم شرح",
        "ختم متن",
        "ختم صحيح",
        "ختم دروس",
        "ختم رسالة",
        "ختام شرح",
        "ختام الدورة",
        "ختام الكتب",
        "اختتام الكتب",
        "اختتام كتاب",
        "خاتمة الدورة",
        "خاتمة الفوائد",
        "خاتمة الجزء",
        "آخر الكتاب",
        "آخر المتن",
        "آخر دروس",
        "last lesson",
        "سورة الناس",
        "باب العتق",
        "كتاب العتق",
        "مخفوضات الأسماء",
        "باب شروط المفتي",
        "وفصل الاجتهاد",
        "وباب الاجتهاد",
        "القاعدة 199",
        "الإدغام",
        "تتمة كتاب الجهاد",
    ]
    has_last_word = bool(
        re.search(
            r"(?:والاخير|و الاخير|والاخيره|و الاخيره|الاخير|الاخيره|الخاتمه|خاتمه الكتاب|الي نهايه)\b",
            nt_last,
        )
    )
    if (
        any(normalize_ar(w) in nt_all for w in completion_markers) or has_last_word
    ) and "الاسبوعي" not in nt_title and "السنوي" not in nt_title:
        return "completed"

    # 3. Active live stream council or periodic council
    has_active_live_prefix = bool(
        re.search(r"(?:^|\s)(?:#?مباشر\s*:|🔴\s*#?مباشر|live\b)", last_ep_title, re.I)
    )
    is_periodic_council = any(
        normalize_ar(w) in nt_title
        for w in [
            "الأسبوعي",
            "الأسبوعية",
            "الشهري",
            "الشهرية",
            "السنوي",
            "السنوية",
            "مجالس الروحة",
            "مجلس الروحة",
            "درس الفجر الرمضاني",
            "درس التفسير الأسبوعي",
            "مجالس قراءة السيرة",
            "مجالس سماع كتب",
            "حوليات وذكريات",
            "زيارة شعب النبي هود",
            "إرشادات السلوك",
            "جلسة الجمعة الشهرية",
            "ملتقى الدعاة السنوي",
            "مجالس آل البيت",
            "مجالس يوم عرفة",
        ]
    )
    if is_periodic_council or (has_active_live_prefix and n_eps >= 9):
        return "ongoing"

    # 4. Mid-book stopping boundaries for classical book/matn/tafsir explanations
    mid_book_stopped_cues = [
        "باب التوكيد",
        "فاء السببية وواو المعية",
        "باب ظن وأخواتها",
        "لات وإن ذا العملا",
        "أفعال المقاربة",
        "باب ما ولا وإن ولات",
        "كان وأخواتها",
        "الحال تتمة",
        "تتمة باب فرح",
        "الأبيات 28 29 30",
        "حقيقة التخصيص",
        "المجمل والمبين",
        "التأويل البعيد",
        "اتضاح الدلالة",
        "الناسخ والمنسوخ",
        "التنجيز في التكليف",
        "معنى الرسالة",
        "اختلال التحسيني",
        "تعريف الإمام الأصفهاني للنظر",
        "مواقيت الصلاة",
        "صلاة المسافر",
        "الجمع بين الصلاتين",
        "باب الصيام",
        "شرح كتاب الصيام كاملا من كتاب عمدة",
        "فرائض الحج وواجباته",
        "تكفين الميت",
        "والسكنى واجبة",
        "ومن حلف لا",
        "حديث من توضأ",
        "بني الإسلام على خمس",
        "الفقه المالكي شرح نظم ابن عاشر 05",
        "استحالة العدم والمماثلة",
        "أقسام طرق نقل الحديث",
        "حرمة الدم الإنساني",
        "سورة الأنفال الجزء الثاني",
        "تفسير مختصر لسورة الفاتحة",
        "فانطلقا حتى إذا ركبا",
        "الحلقة الثالثة من سلسلة نور على نور",
        "ما من نفس تبديه",
        "الحكم العطائية 12",
        "حواشي اليوسي على كبرى السنوسي 33",
        "شرح مقامات الحريري",
        "رسالة عمر في القضاء",
        "الأصل الرابع",
        "المسؤولية العامة تجاه الإسلام",
        "باب في تحقيق العبودية",
        "المدرسة الشامية",
        "أسماءه الشريفة",
        "مباحث الوجود",
        "مادة التصوف 2",
        "أصول التصوف من خلال مبادئ التصوف",
        "الحلقة الثانية أشذاء وأنداء",
        "بث مباشر درس إحياء علوم الدين",
    ]
    if any(normalize_ar(cue) in nt_last or normalize_ar(cue) in nt_title for cue in mid_book_stopped_cues):
        return "stopped"

    major_long_books = [
        "المنهاج في شعب الإيمان",
        "قواعد التصوف وشواهد التعرف",
        "معيار العلم",
        "الأشباه والنظائر",
        "غاية الوصول",
        "لب الأصول",
        "تمهيد الإسنوي",
        "التمهيد في تخريج الفروع",
        "كتاب الشفا",
        "قوت القلوب",
        "فتح القريب المجيب",
        "إحياء علوم الدين",
    ]
    if n_eps <= 14 and any(normalize_ar(mb) in nt_title for mb in major_long_books):
        return "stopped"

    ongoing_series_cues = [
        "الدر المصون",
        "البلاغة القرآنية",
        "تفسير النسفي",
        "المستخلص في تزكية الأنفس",
        "شرح مختصر خليل",
        "شرح كتاب جمع الجوامع",
        "أنوار السنة المحمدية",
        "سيرة رسول الله",
        "شذور الذهب في معرفة كلام العرب",
        "متن البناء في علم الصرف",
        "مجالس الموطأ",
        "مشاهد من سيرة الإمام مالك",
        "مجالس التفسير",
        "مجالس فقه النفس الكبرى",
        "مجالس ألف باء الزواج",
        "الإكليل في استنباط التنزيل",
        "مختصر صحيح البخاري",
        "معالم السنة النبوية",
    ]
    if any(normalize_ar(cue) in nt_title for cue in ongoing_series_cues):
        return "ongoing"

    if raw_state is None and any(
        w in nt_title for w in ["شرح", "كتاب", "متن", "نظم", "رساله"]
    ) and not is_general_series_title(s_title):
        return "stopped"

    return "completed"


def stage8_resolve_states_and_export(
    person_id: str,
    sheikh_info: dict[str, Any],
    series_list: list[dict[str, Any]],
    raw_data: dict[str, Any],
    output_json_path: Path,
    output_series_dir: Path | None = None,
    db_path: Path | None = None,
) -> dict[str, Any]:
    """
    Stage 8:
    1. Filter out empty series, re-index `order_no` and `id` (`<person_id>__sXXX`).
    2. Resolve `state` (`completed` | `stopped` | `ongoing`) with ZERO `null` states.
    3. Document covered chapter boundaries in `title` and `note` for `stopped` / `ongoing` series.
    4. Write curated `<person_id>.json` (and ensure `<person_id>_raw.json` is synchronized in the same dir).
    5. Optionally update `curated.db`.
    6. Export `<output_series_dir>/<person_id>/sXXX/_meta.json` directory structure for `sheikh-series-pipeline v5`.
    """
    non_empty_series = [s for s in series_list if s.get("lessons")]
    states_resolved: list[dict[str, Any]] = []
    exported_meta_paths: list[str] = []

    for s_idx, s in enumerate(non_empty_series, 1):
        s["order_no"] = s_idx
        orig_id = str(s.get("id") or "")
        if not orig_id.startswith(f"{person_id}__"):
            s["id"] = f"{person_id}__s{s_idx:03d}"

        s_title = str(s.get("title") or f"سلسلة {s_idx}").strip()
        s_note = str(s.get("note") or "").strip()
        s["category"] = infer_series_category(s_title, s_note, s.get("matched_book"))

        lessons = s.get("lessons") or []
        main_lessons = [ep for ep in lessons if not ep.get("is_child")]
        first_ep = main_lessons[0] if main_lessons else lessons[0]
        last_ep = main_lessons[-1] if main_lessons else lessons[-1]

        raw_state = s.get("state")
        resolved_state = _resolve_series_state(s_title, s_note, raw_state, main_lessons)
        s["state"] = resolved_state

        start_bound = _extract_topic_boundary(first_ep.get("title", ""), "المقدمة")
        end_bound = _extract_topic_boundary(last_ep.get("title", ""), f"الدرس {len(main_lessons)}")

        if resolved_state in ("stopped", "ongoing"):
            if "من " not in s_title and "إلى " not in s_title:
                s_title = f"{s_title} (من {start_bound} إلى {end_bound} — {len(main_lessons)} درساً)"
                s["title"] = s_title
            boundary_note = (
                f"حالة السلسلة ({resolved_state}): تغطي الأبواب المشروحة من ({start_bound}) "
                f"إلى ({end_bound}) بإجمالي {len(main_lessons)} درساً رئيسياً ({len(lessons)} ملفاً)."
            )
            if boundary_note not in s_note:
                s["note"] = f"{s_note} — {boundary_note}".strip(" —") if s_note else boundary_note
        else:
            if not s_note or s_note.startswith("تصنيف:"):
                s["note"] = (
                    f"سلسلة مكتملة ({len(main_lessons)} درساً رئيسياً، {len(lessons)} ملفاً) "
                    f"من ({start_bound}) إلى ({end_bound})."
                )

        exp_cnt = s.get("expected_count")
        if not isinstance(exp_cnt, int) or exp_cnt < len(lessons):
            s["expected_count"] = len(lessons)

        if raw_state != resolved_state:
            states_resolved.append(
                {
                    "series_id": s["id"],
                    "title": s["title"],
                    "old_state": raw_state,
                    "new_state": resolved_state,
                }
            )

    series_list[:] = non_empty_series

    curated_payload: dict[str, Any] = {
        "sheikh_id": person_id,
        "person_id": person_id,
        "sheikh": sheikh_info,
    }
    if raw_data.get("season_hijri_map"):
        curated_payload["season_hijri_map"] = raw_data["season_hijri_map"]
    curated_payload["series"] = [
        {
            "id": s["id"],
            "order_no": s["order_no"],
            "title": s["title"],
            "category": s["category"],
            "state": s["state"],
            "expected_count": s["expected_count"],
            "note": s["note"],
            **({"matched_book": s["matched_book"]} if s.get("matched_book") else {}),
            "lessons": s["lessons"],
        }
        for s in series_list
    ]

    output_json_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_json_path, "w", encoding="utf-8") as f:
        json.dump(curated_payload, f, ensure_ascii=False, indent=2)

    canonical_json_path = output_json_path.parent / f"{person_id}.json"
    if (
        canonical_json_path.resolve() != output_json_path.resolve()
        and not str(canonical_json_path).startswith("/Users/macm1pro/REPOS/cheikh/")
    ):
        with open(canonical_json_path, "w", encoding="utf-8") as cf:
            json.dump(curated_payload, cf, ensure_ascii=False, indent=2)

    companion_raw_path = output_json_path.parent / f"{person_id}_raw.json"
    if not str(companion_raw_path).startswith("/Users/macm1pro/REPOS/cheikh/"):
        with open(companion_raw_path, "w", encoding="utf-8") as rf:
            json.dump(raw_data, rf, ensure_ascii=False, indent=2)

    if db_path is not None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(db_path), timeout=60.0)
        conn.executescript(CURATED_DB_SCHEMA)
        conn.execute(
            "INSERT OR REPLACE INTO sheikhs (id, order_no, name, short_name, photo, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (
                sheikh_info["id"],
                sheikh_info["order_no"],
                sheikh_info["name"],
                sheikh_info["short_name"],
                sheikh_info["photo"],
                sheikh_info["created_at"],
            ),
        )
        conn.execute("DELETE FROM lessons WHERE sheikh_id = ?", (person_id,))
        conn.execute("DELETE FROM series WHERE sheikh_id = ?", (person_id,))

        for s in curated_payload["series"]:
            conn.execute(
                """
                INSERT INTO series (id, sheikh_id, order_no, title, category, state, expected_count, note)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    s["id"],
                    person_id,
                    s["order_no"],
                    s["title"],
                    s["category"],
                    s["state"],
                    s["expected_count"],
                    s["note"],
                ),
            )
            for l_idx, ep in enumerate(s["lessons"], 1):
                l_id = f"{s['id']}__{l_idx:04d}__{ep['yt_id']}"
                conn.execute(
                    """
                    INSERT INTO lessons (
                        id, series_id, sheikh_id, order_no, display_no, is_child, parent_yt_id,
                        title, yt_id, yt_title, yt_url, duration,
                        has_transcript, has_summary, has_questions, has_challenges
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                    """,
                    (
                        l_id,
                        s["id"],
                        person_id,
                        l_idx,
                        str(ep.get("display_no") or ""),
                        1 if ep.get("is_child") else 0,
                        ep.get("parent_yt_id") if ep.get("is_child") else None,
                        ep["title"],
                        ep["yt_id"],
                        ep["title"],
                        ep.get("yt_url") or f"https://www.youtube.com/watch?v={ep['yt_id']}",
                        int(ep.get("duration") or 0),
                        int(ep.get("has_transcript") or 0),
                        int(ep.get("has_summary") or 0),
                        int(ep.get("has_questions") or 0),
                    ),
                )
        conn.commit()
        conn.close()

    if output_series_dir is not None:
        for s_idx, s in enumerate(curated_payload["series"], 1):
            s_slug = f"s{s_idx:03d}"
            s_dir = output_series_dir / person_id / s_slug
            s_dir.mkdir(parents=True, exist_ok=True)
            lessons = s["lessons"]
            main_cnt = sum(1 for ep in lessons if not ep.get("is_child"))
            child_cnt = len(lessons) - main_cnt
            total_dur = sum(int(ep.get("duration") or 0) for ep in lessons)
            avg_dur = round(total_dur / len(lessons)) if lessons else 0

            series_summary = {
                "id": s["id"],
                "series_id": s["id"],
                "series_slug": s_slug,
                "sheikh_id": person_id,
                "person_id": person_id,
                "sheikh_name": sheikh_info["name"],
                "sheikh_short": sheikh_info["short_name"],
                "order_no": s_idx,
                "title": s["title"],
                "name": s["title"],
                "category": s["category"],
                "is_unclassified": False,
                "state": s["state"],
                "expected_count": s["expected_count"],
                "actual_count": len(lessons),
                "main_lessons_count": main_cnt,
                "child_lessons_count": child_cnt,
                "missing_count": max(0, s["expected_count"] - len(lessons)),
                "transcribed_count": sum(int(ep.get("has_transcript") or 0) for ep in lessons),
                "summary_count": sum(int(ep.get("has_summary") or 0) for ep in lessons),
                "questions_count": sum(int(ep.get("has_questions") or 0) for ep in lessons),
                "total_duration": total_dur,
                "avg_duration": avg_dur,
                "note": s["note"],
            }

            meta_lessons = []
            for l_idx, ep in enumerate(lessons, 1):
                dur_val = int(ep.get("duration") or 0)
                meta_lessons.append(
                    {
                        "order_no": l_idx,
                        "episode_index": l_idx,
                        "file_prefix": f"{l_idx:03d}",
                        "display_no": str(ep.get("display_no") or ""),
                        "is_child": bool(ep.get("is_child", False)),
                        "parent_yt_id": ep.get("parent_yt_id") if ep.get("is_child") else None,
                        "vid": ep["yt_id"],
                        "yt_id": ep["yt_id"],
                        "title": ep["title"],
                        "yt_title": ep["title"],
                        "yt_url": ep.get("yt_url") or f"https://www.youtube.com/watch?v={ep['yt_id']}",
                        "duration": dur_val,
                        "dur_s": dur_val,
                        "has_transcript": int(ep.get("has_transcript") or 0),
                        "has_summary": int(ep.get("has_summary") or 0),
                        "has_questions": int(ep.get("has_questions") or 0),
                        "has_challenges": 0,
                    }
                )

            meta_payload = {
                "schema_version": "5.0",
                "pipeline_compat": "sheikh-series-pipeline-v5",
                "person_id": person_id,
                "sheikh_id": person_id,
                "sheikh_name": sheikh_info["name"],
                "sheikh_short": sheikh_info["short_name"],
                "series_id": s["id"],
                "id": s["id"],
                "series_slug": s_slug,
                "order_no": s_idx,
                "title": s["title"],
                "name": s["title"],
                "category": s["category"],
                "state": s["state"],
                "expected_count": s["expected_count"],
                "actual_count": len(lessons),
                "main_lessons_count": main_cnt,
                "child_lessons_count": child_cnt,
                "total_duration_s": total_dur,
                "avg_duration_s": avg_dur,
                "note": s["note"],
                "matched_book": s.get("matched_book"),
                "curated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "series": series_summary,
                "lessons": meta_lessons,
            }
            meta_file = s_dir / "_meta.json"
            with open(meta_file, "w", encoding="utf-8") as mf:
                json.dump(meta_payload, mf, ensure_ascii=False, indent=2)
            exported_meta_paths.append(str(meta_file))

    return {
        "series_exported_count": len(curated_payload["series"]),
        "lessons_exported_count": sum(len(s["lessons"]) for s in curated_payload["series"]),
        "states_resolved_count": len(states_resolved),
        "states_resolved": states_resolved,
        "meta_files_exported": exported_meta_paths,
    }


# ---------------------------------------------------------------------------
# Stage 9: Mandatory Self-Audit Gate (deep_scanner_all.py + global_audit.py)
# ---------------------------------------------------------------------------


def stage9_mandatory_self_audit(
    person_id: str,
    curated_dir: Path,
    db_path: Path,
    min_duration: int = 300,
    min_series_median: int = 900,
    min_duration_contemplative: int = 120,
) -> dict[str, Any]:
    """
    Stage 9:
    Runs `deep_scanner_all.py` and `global_audit.py` on the generated output and verifies
    `0 errors` across all checks. Raises `RuntimeError` if any flaw or error is detected.
    """
    env = dict(os.environ)
    env["CURATED_DIR"] = str(curated_dir)
    env["CURATED_DB"] = str(db_path)

    scanner_cmd = [
        sys.executable,
        str(SCRIPT_DIR / "deep_scanner_all.py"),
        "--verbose",
        "--min-duration",
        str(min_duration),
        "--min-series-median",
        str(min_series_median),
        "--min-duration-contemplative",
        str(min_duration_contemplative),
        person_id,
    ]
    scanner_proc = subprocess.run(scanner_cmd, env=env, capture_output=True, text=True)
    scanner_out = scanner_proc.stdout + scanner_proc.stderr

    flaw_tags = [
        "[SHORT_IN_LONG]",
        "[CLIP_TITLE_IN_SERIES]",
        "[INVERTED_PARENT_CHILD]",
        "[ORPHAN_CHILD]",
        "[NUM_RESET]",
        "[NUM_JUMP]",
        "[NUM_MISMATCH]",
        "[UNCLASS_TAIL]",
    ]
    flaw_counts = {tag: scanner_out.count(tag) for tag in flaw_tags}
    total_scanner_flaws = sum(flaw_counts.values())
    if "0 series with potential flaws" not in scanner_out and total_scanner_flaws == 0:
        total_scanner_flaws = 1

    audit_cmd = [
        sys.executable,
        str(SCRIPT_DIR / "global_audit.py"),
        "--min-duration",
        str(min_duration),
        "--min-series-median",
        str(min_series_median),
        "--min-duration-contemplative",
        str(min_duration_contemplative),
        person_id,
    ]
    audit_proc = subprocess.run(audit_cmd, env=env, capture_output=True, text=True)
    audit_out = audit_proc.stdout + audit_proc.stderr
    audit_errors = 0 if (audit_proc.returncode == 0 and "0 errors" in audit_out) else 1

    passed = (scanner_proc.returncode == 0) and (total_scanner_flaws == 0) and (audit_errors == 0)
    result = {
        "passed": passed,
        "scanner_flaws_total": total_scanner_flaws,
        "scanner_flaw_breakdown": flaw_counts,
        "scanner_output": scanner_out.strip(),
        "audit_returncode": audit_proc.returncode,
        "audit_output": audit_out.strip(),
    }
    if not passed:
        raise RuntimeError(
            f"Stage 9 Self-Audit Gate FAILED for {person_id}:\n"
            f"Scanner Output:\n{scanner_out}\n"
            f"Global Audit Output:\n{audit_out}"
        )
    return result


# ---------------------------------------------------------------------------
# Public Python API: auto_curate_person
# ---------------------------------------------------------------------------


def auto_curate_person(
    raw_input: str | Path | dict[str, Any],
    output_json_path: str | Path,
    output_series_dir: str | Path | None = None,
    db_path: str | Path | None = None,
    min_duration: int = 300,
    min_series_median: int = 900,
    min_duration_contemplative: int = 120,
    dead_threshold_s: int = 15,
) -> dict[str, Any]:
    """
    Execute the complete 9-Stage Automated Semantic Curation Pipeline on `<person_id>_raw.json`.
    Returns a detailed dictionary containing `curated_data` and `report`.
    """
    if isinstance(raw_input, (str, Path)):
        raw_data = copy.deepcopy(json.load(open(raw_input, encoding="utf-8")))
    else:
        raw_data = copy.deepcopy(raw_input)

    out_json = Path(output_json_path).resolve()
    out_series_dir = Path(output_series_dir).resolve() if output_series_dir else None
    effective_db = Path(db_path).resolve() if db_path else (out_json.parent / "curated.db")

    season_hijri_map = raw_data.get("season_hijri_map") or (raw_data.get("sheikh") or {}).get("season_hijri_map")

    # Stage 1
    person_id, sheikh_info, series_list, video_catalog, raw_pos_map, s1_rep = (
        stage1_import_durations_and_purge_dead(raw_data, dead_threshold_s=dead_threshold_s)
    )

    # Stage 2
    s2_rep = stage2_semantic_classify_and_isolate_guests(
        series_list, person_id, sheikh_info, video_catalog, raw_data
    )

    # Stage 3
    s3_rep = stage3_fix_inverted_livestreams(
        series_list, season_hijri_map=season_hijri_map, min_duration=min_duration
    )

    # Stage 4
    s4_rep = stage4_purge_short_clips_and_promos(
        series_list,
        person_id=person_id,
        season_hijri_map=season_hijri_map,
        min_duration=min_duration,
        min_series_median=min_series_median,
        min_duration_contemplative=min_duration_contemplative,
    )

    # Stage 5
    s5_rep = stage5_ungroup_false_merges(
        series_list, raw_pos_map=raw_pos_map, season_hijri_map=season_hijri_map
    )

    # Stage 6
    s6_rep = stage6_interpolate_hijri_and_reorder(
        series_list, raw_data=raw_data, season_hijri_map=season_hijri_map
    )

    # Stage 7
    s7_rep = stage7_strict_monotonic_numbering(series_list)

    # Stage 8
    s8_rep = stage8_resolve_states_and_export(
        person_id=person_id,
        sheikh_info=sheikh_info,
        series_list=series_list,
        raw_data=raw_data,
        output_json_path=out_json,
        output_series_dir=out_series_dir,
        db_path=effective_db,
    )

    # Stage 9
    s9_rep = stage9_mandatory_self_audit(
        person_id=person_id,
        curated_dir=out_json.parent,
        db_path=effective_db,
        min_duration=min_duration,
        min_series_median=min_series_median,
        min_duration_contemplative=min_duration_contemplative,
    )

    curated_data = json.load(open(out_json, encoding="utf-8"))
    return {
        "person_id": person_id,
        "output_json_path": str(out_json),
        "output_series_dir": str(out_series_dir) if out_series_dir else None,
        "db_path": str(effective_db),
        "curated_data": curated_data,
        "report": {
            "stage1": s1_rep,
            "stage2": s2_rep,
            "stage3": s3_rep,
            "stage4": s4_rep,
            "stage5": s5_rep,
            "stage6": s6_rep,
            "stage7": s7_rep,
            "stage8": s8_rep,
            "stage9": s9_rep,
        },
    }


# ---------------------------------------------------------------------------
# CLI Entrypoint
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Automated 9-Stage Semantic Curation Engine (sheikh-curation v2.0)."
    )
    parser.add_argument(
        "--raw-input",
        "--raw-json",
        "--input",
        dest="raw_input",
        required=True,
        help="Path to input <person_id>_raw.json file.",
    )
    parser.add_argument(
        "--output-json",
        "--output",
        dest="output_json",
        required=True,
        help="Path to output curated <person_id>.json file.",
    )
    parser.add_argument(
        "--output-series-dir",
        "--series-dir",
        dest="output_series_dir",
        default=None,
        help="Optional root directory to export <person_id>/sXXX/_meta.json folders.",
    )
    parser.add_argument(
        "--db-path",
        "--db",
        dest="db_path",
        default=None,
        help="Optional path to curated.db SQLite file (defaults to <output_dir>/curated.db).",
    )
    parser.add_argument("--min-duration", type=int, default=300)
    parser.add_argument("--min-series-median", type=int, default=900)
    parser.add_argument("--min-duration-contemplative", type=int, default=120)
    args = parser.parse_args()

    res = auto_curate_person(
        raw_input=args.raw_input,
        output_json_path=args.output_json,
        output_series_dir=args.output_series_dir,
        db_path=args.db_path,
        min_duration=args.min_duration,
        min_series_median=args.min_series_median,
        min_duration_contemplative=args.min_duration_contemplative,
    )
    rep = res["report"]
    print(
        f"[PASS] auto_curate_person ({res['person_id']}): "
        f"{rep['stage8']['series_exported_count']} series, "
        f"{rep['stage8']['lessons_exported_count']} lessons | "
        f"scanner_flaws={rep['stage9']['scanner_flaws_total']} | "
        f"audit_rc={rep['stage9']['audit_returncode']}"
    )


if __name__ == "__main__":
    main()
