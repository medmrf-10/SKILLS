#!/usr/bin/env python3
"""
test_curation_v2_gates.py — 6-Layer Deterministic Quality Gate for sheikh-curation v2.4.

Verifies:
  - Gate 1 (All 9 Defect Repairs):
      Passes a comprehensive adversarial `<person_id>_raw.json` containing all 9 root defects:
        1. Short clips (<300s) inside a long-form series (excerpt clip, standalone dua, general clip).
        2. Promo/teaser at the tail end of a long series (plus a second promo).
        3. Inverted parent-child livestream (Parent=45s, Child=3600s) + same-day Hijri short stream.
        4. Dead livestream (5s <= 15s).
        5. Truncated Hijri date after 100 chars dumped at the tail of a chronological series.
        6. False merge of two long lessons (1800s each) with a generic title and |pos1 - pos2| > 1.
        7. Numbering reset (1..3 -> 1..2) + missing first-lesson offset mismatch (starts at Lesson 2).
        8. Guest speaker lecture + contest closing ceremony + 'خطبة' fiqh keyword collision.
        9. Series with `state=null` (mid-book stopped series needing chapter boundary documentation
           and completed series).
      Asserts deterministically that every single defect is repaired.

  - Gate 2 (Zero-Error Scanner & Global Audit Gate):
      Executes `deep_scanner_all.py` and `global_audit.py` on the curated output (and on a real
      scholar raw dataset `omari_raw.json` in an isolated workspace) and verifies `0 errors`
      (`0 SHORT_IN_LONG`, `0 INVERTED_PARENT`, `0 NUM_RESET`, `0 NUM_MISMATCH`, `0 NULL_STATE`).

  - Gate 3 (Series Directory Export `<person_id>/sXXX/_meta.json`):
      Verifies that `<output_series_dir>/<person_id>/sXXX/_meta.json` directories and metadata files
      are generated for every series and are 100% compatible with `sheikh-series-pipeline v5`.

  - Gate 4 (Real 17-Sheikh Corpus Regression & Semantic Fidelity Gate):
      Verifies Cycle 3 semantic upgrades discovered across all 17 real sheikhs:
        a. Compound Arabic ordinal phrases (21..99, 100..300, المتم الخمسين) & real-world `#N`/`_N_`/`(N)` numbering.
        b. Guest speaker & welcoming ceremony isolation without false positives on co-hosted series or event playlists.
        c. Unclassified matn routing (parenthetical aliases) & automatic clustering of recurring unclassified books/series.
        d. Reverse-ordered (`N..1`) playlist detection and reversal + semantic `state` resolution (`completed`/`stopped`/`ongoing`)
           even when raw dump defaults to `state="completed"` with `"تصنيف: ..."` notes.
        e. Real multi-sheikh raw corpus curation (`sariri`, `alihani`, `bardoni`, `hawwa`, `sayed`) with 0 scanner/audit errors.

  - Gate 5 (Multi-Part Same-Episode Grouping, Scholar-Token Isolation & Category Inference Gate):
      Verifies Cycle 10 (v2.3) upgrades across the 17-sheikh corpus:
        a. `infer_series_category` across `matched_book`, Arabic & foreign-language titles, and lesson-title fallback
           (reducing `"مواعظ ولقاءات عامة"` fallback from 502 series down to 56 series across 17 sheikhs).
        b. Multi-part same-episode grouping & cascade-shift prevention (`- 7 تتمة -`, `| حـ 860 | 2 |` & `| 3 |`,
           out-of-order duplicate lesson numbers merged post-sort without `(م X)` cascade, reverse-playlist unclassified
           `تتمة الدرس` & duplicate recording attachment, multi-part `مقدمة -1-..-3-` grouped under `مقدمة`, and
           unnumbered index-0 intro promoted to `مقدمة` before `الدرس 1`).
        c. `[INVERTED_PARENT_CHILD]` prevention when a `>= 300s` clip-titled video shares a Hijri year/date with a `< 300s`
           video (`jifri` regression) and end-to-end `discover_person` -> `auto_curate_person` verification on `jifri_raw.json`,
           `bouti_raw.json`, and `kamali_raw.json` with 0 scanner/audit errors.
        d. Scholar-name token exclusion in `_score_series_match` preventing false unclassified routing.

  - Gate 6 (Stopped Series Boundary Extraction & Subset Playlist Deduplication Gate):
      Verifies Cycle 19 (v2.4) upgrades across the 17-sheikh corpus:
        a. `_extract_topic_boundary` and `_extract_stopped_boundary_note`: accurate extraction of stopping boundaries
           from the last lesson title of `stopped` series across chapters (`إلى باب شروط الصلاة`), Quranic ayahs/surahs
           (`إلى الآية 45 من سورة البقرة`), poetry/matn verses (`إلى البيت 120`), parenthesized commentary quotes
           (`(قوله ...)`), while stripping scholar names and avoiding false series-title `كتاب ...` matches.
        b. `_deduplicate_identical_or_subset_series`: automatic merging of duplicate or subset playlists (`>= 75%` `yt_id`
           overlap) for the same commentary into a single complete series, eliminating 1-lesson duplicate stubs and
           recovering complementary missing lessons (`ayman`, `dedew`, `gomaa`, `kamali`, `sayed`).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
DISCOVERY_SCRIPT_DIR = SCRIPT_DIR.parent.parent / "person-discovery-intake" / "scripts"
if DISCOVERY_SCRIPT_DIR.exists() and str(DISCOVERY_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(DISCOVERY_SCRIPT_DIR))

from auto_curate_person import (  # noqa: E402
    _build_sheikh_exclude_tokens,
    _deduplicate_identical_or_subset_series,
    _extract_stopped_boundary_note,
    _extract_topic_boundary,
    _score_series_match,
    auto_curate_person,
    extract_lesson_num,
    infer_series_category,
    is_explicit_part_continuation,
    is_guest_or_event_lesson,
)
from discover_person import discover_person  # noqa: E402


def build_adversarial_raw_fixture() -> dict[str, Any]:
    """
    Construct a comprehensive `<person_id>_raw.json` containing all 9 root defects.
    """
    # >100-character truncated title whose trailing Hijri date (19/05/1439) was cut off by YouTube
    truncated_100char_title = (
        "بث مباشر - مجلس شرح كتاب الحكم العطائية للشيخ تاج الدين بن عطاء الله السكندري "
        "رحمه الله تعالى في دار المصطفى بتريم..."
    )
    assert len(truncated_100char_title) >= 100

    raw_series = [
        # Series 1: Long book-explanation series ordered chronologically by Hijri date,
        # containing Defects 1, 2, 3, 4, 5, 8, and 9 (state=null, completed at end).
        {
            "id": "PL_hikam_001",
            "order_no": 1,
            "title": "شرح كتاب الحكم العطائية لابن عطاء الله السكندري",
            "yt_playlist_id": "PL_hikam_001",
            "state": None,
            "expected_count": 10,
            "note": "",
            "lessons": [
                # Lesson 1 (05/05/1439) - Normal full lesson
                {
                    "pos": 1,
                    "yt_id": "vid_hikm_01",
                    "title": "بث مباشر - شرح الحكم العطائية - المقدمة والحكمة الأولى 05/05/1439",
                    "duration": 3600,
                    "is_child": False,
                    "display_no": "1",
                },
                # Defect 4: Dead livestream (5s <= 15s)
                {
                    "pos": 2,
                    "yt_id": "vid_dead_5s",
                    "title": "بث مباشر منقطع - شرح الحكم العطائية 12/05/1439",
                    "duration": 5,
                    "is_child": False,
                    "display_no": "2",
                },
                # Lesson 2 (12/05/1439) - Normal full lesson
                {
                    "pos": 3,
                    "yt_id": "vid_hikm_02",
                    "title": "بث مباشر - شرح الحكم العطائية - الحكمة الثانية والثالثة 12/05/1439",
                    "duration": 3550,
                    "is_child": False,
                    "display_no": "3",
                },
                # Defect 3a: Inverted parent-child livestream (Parent=45s, Child=3600s) on 26/05/1439
                {
                    "pos": 5,
                    "yt_id": "vid_inv_p45",
                    "title": "بث مباشر - شرح الحكم العطائية - الحكمة الخامسة 26/05/1439",
                    "duration": 45,
                    "is_child": False,
                    "display_no": "4",
                },
                {
                    "pos": 6,
                    "yt_id": "vid_inv_c36",
                    "title": "بث مباشر - شرح الحكم العطائية - الحكمة الخامسة 26/05/1439",
                    "duration": 3600,
                    "is_child": True,
                    "parent_yt_id": "vid_inv_p45",
                    "display_no": "ج2",
                },
                # Defect 3b: Standalone short livestream (110s) on the same Hijri date 03/06/1439 as Lesson 5
                {
                    "pos": 7,
                    "yt_id": "vid_same_sh",
                    "title": "#مباشر شرح الحكم العطائية - الحكمة السادسة 03/06/1439",
                    "duration": 110,
                    "is_child": False,
                    "display_no": "5",
                },
                # Lesson 5 (03/06/1439) - Full livestream
                {
                    "pos": 8,
                    "yt_id": "vid_hikm_05",
                    "title": "بث مباشر - شرح الحكم العطائية - الحكمة السادسة 03/06/1439",
                    "duration": 3400,
                    "is_child": False,
                    "display_no": "6",
                },
                # Lesson 6 (10/06/1439) - Final lesson completing the book
                {
                    "pos": 9,
                    "yt_id": "vid_hikm_06",
                    "title": "بث مباشر - شرح الحكم العطائية - المجلس الأخير وخاتمة الكتاب وتمام المتن 10/06/1439",
                    "duration": 3700,
                    "is_child": False,
                    "display_no": "7",
                },
                # Defect 5: Truncated >100-char title missing its Hijri date (19/05/1439),
                # dumped at the tail after 10/06/1439 (while in raw playlist its pos is 4 between pos 3 and pos 5!)
                {
                    "pos": 4,
                    "yt_id": "vid_tr_100c",
                    "title": truncated_100char_title,
                    "duration": 3480,
                    "is_child": False,
                    "display_no": "8",
                },
                # Defect 1a: Excerpt short clip (<300s) from Lesson 2 (12/05/1439)
                {
                    "pos": 10,
                    "yt_id": "vid_clip_ex",
                    "title": "مقطع من الدرس 2 - علامة الاعتماد على العمل 12/05/1439",
                    "duration": 180,
                    "is_child": False,
                    "display_no": "9",
                },
                # Defect 1b: Standalone short dua clip (<300s)
                {
                    "pos": 11,
                    "yt_id": "vid_clip_du",
                    "title": "دعاء ومناجاة وتضرع إلى الله في ختام المجلس",
                    "duration": 95,
                    "is_child": False,
                    "display_no": "10",
                },
                # Defect 1c: Standalone general short clip (<300s) with #الدورة31
                {
                    "pos": 12,
                    "yt_id": "vid_clip_gn",
                    "title": "مقطع: فائدة في الإخلاص وصدق التوجه #الدورة31",
                    "duration": 120,
                    "is_child": False,
                    "display_no": "11",
                },
                # Defect 8a: Guest speaker lecture inside the book series
                {
                    "pos": 13,
                    "yt_id": "vid_guest_1",
                    "title": "محاضرة الدكتور حاتم الأنصاري - كلمة توجيهية لطلاب العلم في المجلس",
                    "duration": 2100,
                    "is_child": False,
                    "display_no": "12",
                },
                # Defect 8b: Contest closing ceremony inside the book series
                {
                    "pos": 14,
                    "yt_id": "vid_event_1",
                    "title": "حفل اختتام المسابقة الرابعة في كتاب الحكم العطائية وتكريم الفائزين",
                    "duration": 1950,
                    "is_child": False,
                    "display_no": "13",
                },
                # Defect 2: Promos at the very tail of the series
                {
                    "pos": 15,
                    "yt_id": "vid_promo_1",
                    "title": "برومو برنامج شرح كتاب الحكم العطائية",
                    "duration": 85,
                    "is_child": False,
                    "display_no": "14",
                },
                {
                    "pos": 16,
                    "yt_id": "vid_promo_2",
                    "title": "تشويقة سلسلة شرح كتاب الحكم العطائية",
                    "duration": 65,
                    "is_child": False,
                    "display_no": "15",
                },
            ],
        },
        # Series 2: Tafsir series containing Defect 6 (False merge of two 1800s lessons with generic title and |pos1-pos2|>1)
        # and Defect 7a (Numbering reset 1..3 -> 1..2)
        {
            "id": "PL_tafsir_002",
            "order_no": 2,
            "title": "مجالس تفسير القرآن الكريم الأسبوعية",
            "yt_playlist_id": "PL_tafsir_002",
            "state": "completed",
            "expected_count": 5,
            "note": "مجالس التفسير.",
            "lessons": [
                {
                    "pos": 10,
                    "yt_id": "vid_tf_mrg1",
                    "title": "بث مباشر - درس التفسير - معاني ودلالات من الآيات البينات",
                    "duration": 1800,
                    "is_child": False,
                    "display_no": "1",
                },
                # Defect 6: Falsely merged 1800s lesson as child 'ج2' with pos=20 (|10 - 20| = 10 > 1) and no explicit part 2
                {
                    "pos": 20,
                    "yt_id": "vid_tf_mrg2",
                    "title": "بث مباشر - درس التفسير - معاني ودلالات من الآيات البينات",
                    "duration": 1800,
                    "is_child": True,
                    "parent_yt_id": "vid_tf_mrg1",
                    "display_no": "ج2",
                },
                {
                    "pos": 30,
                    "yt_id": "vid_tf_ep03",
                    "title": "الدرس 3 - مجالس تفسير القرآن الكريم",
                    "duration": 1900,
                    "is_child": False,
                    "display_no": "3",
                },
                # Defect 7a: Numbering reset (1..3 -> 1..2 in Season 2)
                {
                    "pos": 40,
                    "yt_id": "vid_tf_rst1",
                    "title": "الدرس 1 - مجالس تفسير القرآن الكريم - الموسم الثاني",
                    "duration": 1850,
                    "is_child": False,
                    "display_no": "1",
                },
                {
                    "pos": 50,
                    "yt_id": "vid_tf_rst2",
                    "title": "الدرس 2 - مجالس تفسير القرآن الكريم - الموسم الثاني",
                    "duration": 1920,
                    "is_child": False,
                    "display_no": "2",
                },
            ],
        },
        # Series 3: Stopped mid-book Fiqh series with `state=null` (Defect 9) and Offset numbering starting at Lesson 2 (Defect 7b)
        {
            "id": "PL_fiqh_003",
            "order_no": 3,
            "title": "شرح نظم أسهل المسالك في مذهب الإمام مالك",
            "yt_playlist_id": "PL_fiqh_003",
            "state": None,
            "expected_count": 4,
            "note": "",
            "lessons": [
                {
                    "pos": 1,
                    "yt_id": "vid_fq_ep02",
                    "title": "الدرس 2: المقدمة وباب الطهارة | شرح نظم أسهل المسالك",
                    "duration": 2400,
                    "is_child": False,
                    "display_no": "1",  # Off-by-one mismatch: title is الدرس 2!
                },
                {
                    "pos": 2,
                    "yt_id": "vid_fq_ep03",
                    "title": "الدرس 3: باب فرائض الوضوء وسننه | شرح نظم أسهل المسالك",
                    "duration": 2500,
                    "is_child": False,
                    "display_no": "2",
                },
                {
                    "pos": 3,
                    "yt_id": "vid_fq_ep04",
                    "title": "الدرس 4: باب شروط الصلاة وأركانها | شرح نظم أسهل المسالك",
                    "duration": 2600,
                    "is_child": False,
                    "display_no": "3",
                },
                {
                    "pos": 4,
                    "yt_id": "vid_fq_ep05",
                    "title": "الدرس 5: باب صلاة السفر والجمع بين الصلاتين | شرح نظم أسهل المسالك",
                    "duration": 2550,
                    "is_child": False,
                    "display_no": "4",
                },
            ],
        },
        # Series 4: Friday Khutbah series containing Defect 8c ('خطبة' lexical collision on a Fiqh issue)
        {
            "id": "PL_khutbah_004",
            "order_no": 4,
            "title": "خطب الجمعة والعيدين",
            "yt_playlist_id": "PL_khutbah_004",
            "state": "completed",
            "expected_count": 3,
            "note": "خطب منبرية.",
            "lessons": [
                {
                    "pos": 1,
                    "yt_id": "vid_kh_0001",
                    "title": "خطبة الجمعة: تقوى الله وأثرها في صلاح القلوب",
                    "duration": 1800,
                    "is_child": False,
                    "display_no": "1",
                },
                {
                    "pos": 2,
                    "yt_id": "vid_kh_0002",
                    "title": "خطبة عيد الفطر المبارك: صلة الأرحام والتراحم",
                    "duration": 1650,
                    "is_child": False,
                    "display_no": "2",
                },
                # Defect 8c: Fiqh issue containing the word 'خطبة' wrongly placed in Friday Khutbahs
                {
                    "pos": 3,
                    "yt_id": "vid_kh_fiqh",
                    "title": "مسألة الصلاة أثناء خطبة الإمام وحكم تحية المسجد",
                    "duration": 900,
                    "is_child": False,
                    "display_no": "3",
                },
            ],
        },
        # Series 5: Unclassified bucket containing an unclassified lesson belonging to Series 3 (أسهل المسالك الدرس 6)
        {
            "id": "testsh__unclassified",
            "order_no": 5,
            "title": "غير مصنف",
            "yt_playlist_id": None,
            "is_unclassified": True,
            "state": None,
            "lessons": [
                {
                    "pos": 1,
                    "yt_id": "vid_fq_ep06",
                    "title": "الدرس 6: باب صلاة الجمعة وأحكامها | شرح نظم أسهل المسالك",
                    "duration": 2700,
                    "is_child": False,
                    "display_no": "1",
                }
            ],
        },
    ]

    # Build raw_series in chronological playlist order (so pos=4 is between pos=3 and pos=5 for interpolation)
    raw_playlists = []
    unique_videos = []
    for s in raw_series:
        s_vids = sorted(s["lessons"], key=lambda x: x.get("pos", 1))
        raw_playlists.append(
            {
                "id": s["id"],
                "order_no": s["order_no"],
                "title": s["title"],
                "yt_playlist_id": s["yt_playlist_id"],
                "is_unclassified": bool(s.get("is_unclassified", False)),
                "state": s["state"],
                "expected_count": s.get("expected_count", len(s_vids)),
                "note": s.get("note", ""),
                "videos": [
                    {
                        "pos": v["pos"],
                        "yt_id": v["yt_id"],
                        "title": v["title"],
                        "duration": v["duration"],
                    }
                    for v in s_vids
                ],
            }
        )
        for v in s["lessons"]:
            unique_videos.append(
                {
                    "yt_id": v["yt_id"],
                    "title": v["title"],
                    "duration": v["duration"],
                    "yt_url": f"https://www.youtube.com/watch?v={v['yt_id']}",
                    "appearances": [
                        {
                            "raw_series_id": s["id"],
                            "raw_series_title": s["title"],
                            "pos": v["pos"],
                            "is_unclassified": bool(s.get("is_unclassified", False)),
                        }
                    ],
                }
            )

    return {
        "person_id": "testsh",
        "sheikh_name": "الشيخ عبد الله بن علوي الاختباري",
        "sheikh": {
            "id": "testsh",
            "order_no": 1,
            "name": "الشيخ عبد الله بن علوي الاختباري",
            "short_name": "الاختباري",
            "photo": "",
            "created_at": "2026-10-18 10:00:00",
        },
        "season_hijri_map": {
            "دورة": {"30": 1445, "31": 1447, "32": 1448},
        },
        "series": raw_series,
        "raw_series": raw_playlists,
        "unique_videos": unique_videos,
    }


def run_gate_1_all_9_defects(tmp_path: Path) -> dict[str, Any]:
    """
    Gate 1: Run `auto_curate_person` on the 9-defect adversarial fixture and assert
    deterministic repair of all 9 defects.
    """
    raw_fixture = build_adversarial_raw_fixture()
    raw_file = tmp_path / "testsh_raw.json"
    out_json = tmp_path / "testsh.json"
    out_series_dir = tmp_path / "series_export"
    db_path = tmp_path / "curated.db"

    with open(raw_file, "w", encoding="utf-8") as f:
        json.dump(raw_fixture, f, ensure_ascii=False, indent=2)

    res = auto_curate_person(
        raw_input=raw_file,
        output_json_path=out_json,
        output_series_dir=out_series_dir,
        db_path=db_path,
    )
    curated = res["curated_data"]
    series_by_id = {s["id"]: s for s in curated["series"]}
    series_list = curated["series"]

    # Locate series by title keywords
    hikam_s = next(s for s in series_list if "الحكم العطائية" in s["title"])
    tafsir_s = next(s for s in series_list if "تفسير القرآن" in s["title"])
    fiqh_s = next(s for s in series_list if "أسهل المسالك" in s["title"])
    khutbah_s = next(s for s in series_list if "خطب الجمعة" in s["title"])
    dua_s = next(s for s in series_list if "أدعية وابتهالات" in s["title"])
    clips_s = next(s for s in series_list if "مقتطفات وفوائد قصيرة" in s["title"])
    events_s = next(s for s in series_list if "محاضرات وفعاليات عامة" in s["title"])

    all_yt_ids = {ep["yt_id"] for s in series_list for ep in s["lessons"]}

    # 1. Assert Defect 4 (Dead livestream 5s <= 15s purged completely)
    assert "vid_dead_5s" not in all_yt_ids, "Defect 4 Failed: Dead 5s stream was not removed!"

    # 2. Assert Defect 2 (Promos moved to the very start of Hikam series with 'برومو' and 'برومو 2')
    assert hikam_s["lessons"][0]["yt_id"] == "vid_promo_1", "Defect 2 Failed: Promo 1 not at index 0!"
    assert hikam_s["lessons"][0]["display_no"] == "برومو", "Defect 2 Failed: Promo 1 display_no != 'برومو'!"
    assert not hikam_s["lessons"][0]["is_child"], "Defect 2 Failed: Promo 1 should not be a child!"
    assert hikam_s["lessons"][1]["yt_id"] == "vid_promo_2", "Defect 2 Failed: Promo 2 not at index 1!"
    assert hikam_s["lessons"][1]["is_child"] is True, "Defect 2 Failed: Promo 2 must be a child of Promo 1!"
    assert hikam_s["lessons"][1]["parent_yt_id"] == "vid_promo_1", "Defect 2 Failed: Promo 2 parent_yt_id mismatch!"
    assert hikam_s["lessons"][1]["display_no"] == "برومو 2", "Defect 2 Failed: Promo 2 display_no != 'برومو 2'!"

    # 3. Assert Defect 3 (Inverted parent-child livestream repaired: 3600s is parent, 45s is child 'مقطع';
    #    and same-day 110s short stream attached under 3400s parent)
    hikam_by_yt = {ep["yt_id"]: ep for ep in hikam_s["lessons"]}
    assert hikam_by_yt["vid_inv_c36"]["is_child"] is False, "Defect 3a Failed: 3600s lesson not promoted to parent!"
    assert hikam_by_yt["vid_inv_p45"]["is_child"] is True, "Defect 3a Failed: 45s broken stream not demoted to child!"
    assert hikam_by_yt["vid_inv_p45"]["parent_yt_id"] == "vid_inv_c36", "Defect 3a Failed: 45s parent_yt_id != vid_inv_c36!"
    assert hikam_by_yt["vid_inv_p45"]["display_no"] == "مقطع", "Defect 3a Failed: 45s display_no != 'مقطع'!"

    assert hikam_by_yt["vid_same_sh"]["is_child"] is True, "Defect 3b Failed: Same-day 110s stream not attached as child!"
    assert hikam_by_yt["vid_same_sh"]["parent_yt_id"] == "vid_hikm_05", "Defect 3b Failed: 110s stream not linked to vid_hikm_05!"

    # 4. Assert Defect 1 (Short clips: excerpt attached to Lesson 2, dua moved to Dua series, clip moved to Clips series)
    assert hikam_by_yt["vid_clip_ex"]["is_child"] is True, "Defect 1a Failed: Excerpt clip not attached as child!"
    assert hikam_by_yt["vid_clip_ex"]["parent_yt_id"] == "vid_hikm_02", "Defect 1a Failed: Excerpt not attached to Lesson 2!"
    assert hikam_by_yt["vid_clip_ex"]["display_no"] == "مقطع", "Defect 1a Failed: Excerpt display_no != 'مقطع'!"

    dua_yt_ids = {ep["yt_id"] for ep in dua_s["lessons"]}
    assert "vid_clip_du" in dua_yt_ids, "Defect 1b Failed: Short dua clip not moved to Dua series!"

    clips_yt_ids = {ep["yt_id"] for ep in clips_s["lessons"]}
    assert "vid_clip_gn" in clips_yt_ids, "Defect 1c Failed: General short clip not moved to Clips series!"

    # 5. Assert Defect 5 (Truncated >100-char title interpolated via hijri_interpolator and moved before 26/05/1439)
    hikam_main_ids = [ep["yt_id"] for ep in hikam_s["lessons"] if not ep.get("is_child") and ep["display_no"].isdigit()]
    assert hikam_main_ids == [
        "vid_hikm_01",  # 05/05/1439
        "vid_hikm_02",  # 12/05/1439
        "vid_tr_100c",  # Interpolated ~19/05/1439 (moved from tail to between 12/05 and 26/05!)
        "vid_inv_c36",  # 26/05/1439
        "vid_hikm_05",  # 03/06/1439
        "vid_hikm_06",  # 10/06/1439
    ], f"Defect 5 Failed: Chronological order mismatch: {hikam_main_ids}"

    # 6. Assert Defect 6 (False merge of two 1800s generic-titled lessons ungrouped into independent main lessons)
    tafsir_by_yt = {ep["yt_id"]: ep for ep in tafsir_s["lessons"]}
    assert tafsir_by_yt["vid_tf_mrg1"]["is_child"] is False, "Defect 6 Failed: First 1800s lesson should be main!"
    assert tafsir_by_yt["vid_tf_mrg2"]["is_child"] is False, "Defect 6 Failed: Falsely merged 1800s lesson was not ungrouped!"
    assert tafsir_by_yt["vid_tf_mrg2"]["parent_yt_id"] is None, "Defect 6 Failed: Ungrouped lesson still has parent_yt_id!"

    # 7. Assert Defect 7 (Monotonic display_no in Tafsir 1..5 fixing 1..3->1..2 reset, and Offset 2..6 in Fiqh)
    tafsir_main_disps = [ep["display_no"] for ep in tafsir_s["lessons"] if not ep.get("is_child")]
    assert tafsir_main_disps == ["1", "2", "3", "4", "5"], f"Defect 7a Failed: Tafsir display_no reset not fixed: {tafsir_main_disps}"

    fiqh_main_disps = [ep["display_no"] for ep in fiqh_s["lessons"] if not ep.get("is_child")]
    assert fiqh_main_disps == ["2", "3", "4", "5", "6"], f"Defect 7b Failed: Fiqh offset numbering mismatch: {fiqh_main_disps}"

    # 8. Assert Defect 8 (Guest lecture & Contest ceremony isolated into Events series;
    #    and 'مسألة الصلاة أثناء خطبة الإمام' moved out of Friday Khutbahs into Fiqh)
    events_yt_ids = {ep["yt_id"] for ep in events_s["lessons"]}
    assert "vid_guest_1" in events_yt_ids, "Defect 8a Failed: Guest speaker lecture not isolated into Events series!"
    assert "vid_event_1" in events_yt_ids, "Defect 8b Failed: Contest ceremony not isolated into Events series!"

    khutbah_yt_ids = {ep["yt_id"] for ep in khutbah_s["lessons"]}
    assert "vid_kh_fiqh" not in khutbah_yt_ids, "Defect 8c Failed: Fiqh issue with 'خطبة' still inside Friday Khutbah series!"
    fiqh_all_yt_ids = {
        ep["yt_id"]
        for s in series_list
        if "فقه" in s["title"] or "المسالك" in s["title"]
        for ep in s["lessons"]
    }
    assert "vid_kh_fiqh" in fiqh_all_yt_ids, "Defect 8c Failed: Fiqh issue with 'خطبة' not routed to a Fiqh series!"
    assert "vid_fq_ep06" in {ep["yt_id"] for ep in fiqh_s["lessons"]}, "Defect 8d Failed: Unclassified episode 6 not routed to As'hal al-Masalik!"

    # 9. Assert Defect 9 (Zero null states; Hikam is 'completed', As'hal al-Masalik is 'stopped' with chapter boundaries in title & note)
    for s in series_list:
        assert s.get("state") in ("completed", "stopped", "ongoing"), f"Defect 9 Failed: Invalid state {s.get('state')} on {s['id']}!"
    assert hikam_s["state"] == "completed", f"Defect 9a Failed: Hikam series should be 'completed', got {hikam_s['state']}!"
    assert fiqh_s["state"] == "stopped", f"Defect 9b Failed: Mid-book Fiqh series should be 'stopped', got {fiqh_s['state']}!"
    assert "من " in fiqh_s["title"] and "إلى " in fiqh_s["title"], f"Defect 9c Failed: Stopped series title missing chapter boundaries: {fiqh_s['title']}"
    assert "تغطي الأبواب المشروحة" in fiqh_s["note"], f"Defect 9d Failed: Stopped series note missing chapter boundary details: {fiqh_s['note']}"

    print("  [Gate 1] PASS — All 9 root defects deterministically repaired and verified.")
    return res


def run_gate_2_scanner_and_global_audit(tmp_path: Path, curation_res: dict[str, Any]) -> None:
    """
    Gate 2: Verify `deep_scanner_all.py` and `global_audit.py` report 0 errors on both
    the adversarial fixture output AND a real scholar dataset (`omari_raw.json`).
    """
    s9 = curation_res["report"]["stage9"]
    assert s9["passed"] is True, "Gate 2 Failed: Stage 9 self-audit did not pass!"
    assert s9["scanner_flaws_total"] == 0, f"Gate 2 Failed: Scanner flaws = {s9['scanner_flaws_total']}"
    for tag, cnt in s9["scanner_flaw_breakdown"].items():
        assert cnt == 0, f"Gate 2 Failed: {tag} count = {cnt}"
    assert s9["audit_returncode"] == 0, f"Gate 2 Failed: global_audit returncode = {s9['audit_returncode']}"
    assert "0 errors" in s9["audit_output"], f"Gate 2 Failed: global_audit output missing '0 errors': {s9['audit_output']}"

    # Also test against real scholar dataset `omari_raw.json` (read-only from cheikh repo) if present
    omari_raw_path = Path("/Users/macm1pro/REPOS/cheikh/data/curated_sheikhs/omari_raw.json")
    if omari_raw_path.exists():
        real_dir = tmp_path / "real_omari_test"
        real_dir.mkdir(parents=True, exist_ok=True)
        omari_res = auto_curate_person(
            raw_input=omari_raw_path,
            output_json_path=real_dir / "omari.json",
            output_series_dir=real_dir / "series_export",
            db_path=real_dir / "curated.db",
        )
        assert omari_res["report"]["stage9"]["passed"] is True
        assert omari_res["report"]["stage9"]["scanner_flaws_total"] == 0
        assert omari_res["report"]["stage9"]["audit_returncode"] == 0

    print(
        "  [Gate 2] PASS — deep_scanner_all.py & global_audit.py verified 0 errors "
        "(0 SHORT_IN_LONG, 0 INVERTED_PARENT, 0 NUM_RESET, 0 NUM_MISMATCH, 0 NULL_STATE)."
    )


def run_gate_3_series_meta_export(curation_res: dict[str, Any]) -> None:
    """
    Gate 3: Verify `<output_series_dir>/<person_id>/sXXX/_meta.json` directory tree
    and schema compatibility with `sheikh-series-pipeline v5`.
    """
    person_id = curation_res["person_id"]
    series_dir = Path(curation_res["output_series_dir"])
    curated_series = curation_res["curated_data"]["series"]

    assert series_dir.exists(), "Gate 3 Failed: output_series_dir does not exist!"
    person_series_root = series_dir / person_id
    assert person_series_root.exists(), f"Gate 3 Failed: {person_series_root} does not exist!"

    for s_idx, s in enumerate(curated_series, 1):
        s_slug = f"s{s_idx:03d}"
        meta_path = person_series_root / s_slug / "_meta.json"
        assert meta_path.exists(), f"Gate 3 Failed: Missing {meta_path}!"

        meta = json.load(open(meta_path, encoding="utf-8"))
        assert meta.get("schema_version") == "5.0"
        assert meta.get("pipeline_compat") == "sheikh-series-pipeline-v5"
        assert meta.get("person_id") == person_id
        assert meta.get("sheikh_id") == person_id
        assert meta.get("series_id") == s["id"]
        assert meta.get("series_slug") == s_slug
        assert meta.get("title") == s["title"]
        assert meta.get("state") in ("completed", "stopped", "ongoing")
        assert meta.get("actual_count") == len(s["lessons"])
        assert isinstance(meta.get("lessons"), list) and len(meta["lessons"]) == len(s["lessons"])

        for l_idx, ep in enumerate(meta["lessons"], 1):
            assert ep.get("order_no") == l_idx
            assert ep.get("episode_index") == l_idx
            assert ep.get("file_prefix") == f"{l_idx:03d}"
            assert ep.get("vid") == ep.get("yt_id") and len(str(ep.get("vid", ""))) > 0
            assert isinstance(ep.get("duration"), int) and ep["duration"] > 15
            assert ep.get("dur_s") == ep.get("duration")
            assert isinstance(ep.get("display_no"), str) and len(ep["display_no"]) > 0
            assert isinstance(ep.get("is_child"), bool)
            if ep["is_child"]:
                assert ep.get("parent_yt_id") is not None
            else:
                assert ep.get("parent_yt_id") is None

    # Also verify CLI entrypoint execution end-to-end
    cli_dir = series_dir.parent / "cli_run"
    cli_dir.mkdir(parents=True, exist_ok=True)
    raw_file = series_dir.parent / "testsh_raw.json"
    cli_proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_DIR / "auto_curate_person.py"),
            "--raw-input",
            str(raw_file),
            "--output-json",
            str(cli_dir / "testsh.json"),
            "--output-series-dir",
            str(cli_dir / "series_export"),
            "--db-path",
            str(cli_dir / "curated.db"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert cli_proc.returncode == 0, f"Gate 3 CLI Failed: {cli_proc.stderr or cli_proc.stdout}"
    assert (cli_dir / "series_export" / person_id / "s001" / "_meta.json").exists()

    print(
        f"  [Gate 3] PASS — Exported {len(curated_series)} series directories "
        f"({person_id}/s001..s{len(curated_series):03d}/_meta.json) 100% compatible with sheikh-series-pipeline v5."
    )


def run_gate_4_real_corpus_semantic_fidelity(tmp_path: Path) -> None:
    """
    Gate 4: Verify Cycle 3 semantic upgrades discovered across all 17 real sheikhs:
      1. Compound Arabic ordinal phrase parsing (21..99, 100..300, المتم الخمسين) & `#N`/`_N_`/`(N)` numbering.
      2. Guest speaker & welcoming ceremony isolation without false positives on co-hosted series or event playlists.
      3. Unclassified matn routing (parenthetical aliases) & automatic clustering of recurring unclassified books/series.
      4. Reverse-ordered (`N..1`) playlist reversal + semantic `state` resolution (`completed`/`stopped`/`ongoing`)
         even when raw dump defaults to `state="completed"` with `"تصنيف: ..."` notes.
      5. Real multi-sheikh raw corpus curation (`sariri`, `alihani`, `bardoni`, `hawwa`, `sayed`) with 0 scanner/audit errors.
    """
    # 4a. Compound Arabic ordinal phrases & real-world symbol numbering
    assert extract_lesson_num("المجلس السابع والعشرون من مجالس سماع وقراءة كتاب حلية الأولياء") == 27
    assert extract_lesson_num("شرح صحيح البخاري المجلس الثاني بعد المئة الأولى للشيخ سعيد الكملي") == 102
    assert extract_lesson_num("الدرس المتم الخمسين من شرح ألفية ابن مالك") == 50
    assert extract_lesson_num("الدرس الثالث والستون بعد المئتين من شرح موطأ مالك") == 263
    assert extract_lesson_num("شرح كتاب شذور الذهب #12 | الشيخ صالح العصيمي") == 12
    assert extract_lesson_num("مختصر السيرة النبوية _07_ الشيخ صالح العصيمي") == 7
    assert extract_lesson_num("( 15 ) شرح مقدمة ابن رشد - د. سعيد الكملي") == 15
    assert extract_lesson_num("شرح الحكم العطائية - وقصيدة: فيا سالكاً (8)") is None
    assert extract_lesson_num("تفسير سورة البقرة من الآية (15) إلى (20)") is None

    # 4b. Guest speaker & ceremony discrimination vs co-hosted series & prepositions
    assert is_guest_or_event_lesson(
        "محاضرة الدكتور حاتم الأنصاري في مدرسة شيخ العمود",
        sheikh_info={"name": "أيمن عبد الرحيم", "short_name": "أيمن عبد الرحيم"},
        series_title="دورة تأسيس العلوم",
    ) is True
    assert is_guest_or_event_lesson(
        "كلمة ترحيبية بالشيخ محمد الحسن الددو في افتتاح المركز",
        sheikh_info={"name": "محمد الحسن الددو", "short_name": "الددو"},
        series_title="شرح الورقات",
    ) is True
    assert is_guest_or_event_lesson(
        "مراجعات مع إبراهيم رفيق الطويل - الحلقة 5",
        sheikh_info={"name": "محمد خير الشعال", "short_name": "الهاشمي"},
        series_title="مراجعات مع إبراهيم رفيق الطويل",
    ) is False
    assert is_guest_or_event_lesson(
        "كلمة الشيخ في المؤتمر العالمي لنصرة النبي",
        sheikh_info={"name": "محمد الحسن الددو", "short_name": "الددو"},
        series_title="محاضرات عامة",
    ) is False
    assert is_guest_or_event_lesson(
        "محاضرة الدكتور عمر عبد الكافي في ملتقى رواد الأقصى",
        sheikh_info={"name": "الحبيب عمر بن حفيظ", "short_name": "بن حفيظ"},
        series_title="مشاركات ملتقى رواد الأقصى",
    ) is False

    # 4c & 4d. Synthetic fixture testing parenthetical matn routing, recurring unclassified clustering,
    # reverse playlist (N..1) reversal, and semantic state override of raw default state="completed"
    sem_raw = {
        "person_id": "semsh",
        "sheikh_name": "الشيخ أبو عبد الله المنهجي",
        "sheikh": {
            "id": "semsh",
            "order_no": 1,
            "name": "الشيخ أبو عبد الله المنهجي",
            "short_name": "المنهجي",
        },
        "series": [
            # Series 1: Reverse-ordered playlist (3, 2, 1) with default raw state="completed" and "تصنيف:" note,
            # stopping mid-book at باب صلاة المسافر -> must reverse to 1..3 and resolve state="stopped"
            {
                "id": "PL_rev_fiqh",
                "order_no": 1,
                "title": "شرح متن الورقات في أصول الفقه (الورقات)",
                "yt_playlist_id": "PL_rev_fiqh",
                "state": "completed",
                "note": "تصنيف: الفقه وأصوله",
                "lessons": [
                    {
                        "pos": 1,
                        "yt_id": "vid_wrq_03",
                        "title": "الدرس 3 من شرح الورقات - باب العام والخاص",
                        "duration": 2200,
                        "is_child": False,
                        "display_no": "1",
                    },
                    {
                        "pos": 2,
                        "yt_id": "vid_wrq_02",
                        "title": "الدرس 2 من شرح الورقات - باب الأمر والنهي",
                        "duration": 2150,
                        "is_child": False,
                        "display_no": "2",
                    },
                    {
                        "pos": 3,
                        "yt_id": "vid_wrq_01",
                        "title": "الدرس 1 من شرح الورقات - المقدمة وتعريف أصول الفقه",
                        "duration": 2100,
                        "is_child": False,
                        "display_no": "3",
                    },
                ],
            },
            # Series 2: Unclassified bucket with Lesson 4 of الورقات + 3 recurring lessons of a standalone matn
            {
                "id": "semsh__unclassified",
                "order_no": 2,
                "title": "غير مصنف",
                "yt_playlist_id": None,
                "is_unclassified": True,
                "state": "completed",
                "note": "تصنيف: غير مصنف",
                "lessons": [
                    {
                        "pos": 1,
                        "yt_id": "vid_wrq_04",
                        "title": "الدرس 4 من شرح الورقات - باب المجمل والمبين",
                        "duration": 2300,
                        "is_child": False,
                        "display_no": "1",
                    },
                    {
                        "pos": 2,
                        "yt_id": "vid_srf_01",
                        "title": "شرح متن الصرف الصغير - الدرس 1 - المقدمة والميزان الصرفي",
                        "duration": 1900,
                        "is_child": False,
                        "display_no": "2",
                    },
                    {
                        "pos": 3,
                        "yt_id": "vid_srf_02",
                        "title": "شرح متن الصرف الصغير - الدرس 2 - أبنية الأفعال المجردة",
                        "duration": 1950,
                        "is_child": False,
                        "display_no": "3",
                    },
                    {
                        "pos": 4,
                        "yt_id": "vid_srf_03",
                        "title": "شرح متن الصرف الصغير - الدرس 3 - خاتمة المتن وتمام الكتاب",
                        "duration": 2050,
                        "is_child": False,
                        "display_no": "4",
                    },
                ],
            },
        ],
    }
    sem_dir = tmp_path / "sem_gate4"
    sem_dir.mkdir(parents=True, exist_ok=True)
    sem_raw_file = sem_dir / "semsh_raw.json"
    with open(sem_raw_file, "w", encoding="utf-8") as f:
        json.dump(sem_raw, f, ensure_ascii=False, indent=2)

    sem_res = auto_curate_person(
        raw_input=sem_raw_file,
        output_json_path=sem_dir / "semsh.json",
        output_series_dir=sem_dir / "series_export",
        db_path=sem_dir / "curated.db",
    )
    assert sem_res["report"]["stage9"]["passed"] is True
    sem_series = sem_res["curated_data"]["series"]

    waraqat_s = next(s for s in sem_series if "الورقات" in s["title"])
    sarf_s = next(s for s in sem_series if "الصرف الصغير" in s["title"])

    # Verify reverse-ordered playlist was reversed and unclassified Lesson 4 was routed into it in order 1..4
    assert [ep["yt_id"] for ep in waraqat_s["lessons"]] == [
        "vid_wrq_01",
        "vid_wrq_02",
        "vid_wrq_03",
        "vid_wrq_04",
    ], f"Gate 4 Failed: Reverse playlist + unclassified routing order mismatch: {[ep['yt_id'] for ep in waraqat_s['lessons']]}"
    assert [ep["display_no"] for ep in waraqat_s["lessons"]] == ["1", "2", "3", "4"]
    assert waraqat_s["state"] == "stopped", f"Gate 4 Failed: Mid-book series with raw state='completed' and 'تصنيف:' note should resolve to 'stopped', got {waraqat_s['state']}"
    assert "من " in waraqat_s["title"] and "إلى " in waraqat_s["title"]

    # Verify 3 recurring unclassified matn lessons were clustered into their own completed series
    assert [ep["yt_id"] for ep in sarf_s["lessons"]] == ["vid_srf_01", "vid_srf_02", "vid_srf_03"]
    assert sarf_s["state"] == "completed"

    # 4e. Multi-sheikh real raw corpus verification (if `/Users/macm1pro/REPOS/cheikh/data/curated_sheikhs` exists)
    cheikh_raw_dir = Path("/Users/macm1pro/REPOS/cheikh/data/curated_sheikhs")
    tested_real = []
    if cheikh_raw_dir.exists():
        for pid in ("sariri", "alihani", "bardoni", "hawwa", "sayed"):
            raw_p = cheikh_raw_dir / f"{pid}_raw.json"
            if not raw_p.exists():
                continue
            p_dir = tmp_path / f"real_{pid}"
            p_dir.mkdir(parents=True, exist_ok=True)
            p_res = auto_curate_person(
                raw_input=raw_p,
                output_json_path=p_dir / f"{pid}.json",
                output_series_dir=p_dir / "series_export",
                db_path=p_dir / "curated.db",
            )
            assert p_res["report"]["stage9"]["passed"] is True, f"Gate 4 Real Corpus Failed on {pid}"
            assert p_res["report"]["stage9"]["scanner_flaws_total"] == 0
            assert p_res["report"]["stage9"]["audit_returncode"] == 0
            tested_real.append(pid)

            if pid == "sariri":
                s_titles = [s["title"] for s in p_res["curated_data"]["series"]]
                assert any("الصرف الصغير" in t for t in s_titles), "Gate 4 Failed: sariri missing clustered الصرف الصغير series!"
                stopped_cnt = sum(1 for s in p_res["curated_data"]["series"] if s["state"] == "stopped")
                assert stopped_cnt >= 5, f"Gate 4 Failed: sariri expected >=5 stopped series, got {stopped_cnt}"
            elif pid == "alihani":
                s_titles = [s["title"] for s in p_res["curated_data"]["series"]]
                assert any("مبادئ دروس العربية" in t for t in s_titles), "Gate 4 Failed: alihani missing clustered مبادئ دروس العربية series!"
                assert not any(s.get("is_unclassified") for s in p_res["curated_data"]["series"]), "Gate 4 Failed: alihani still has unclassified bucket!"
            elif pid == "bardoni":
                risala2 = next(s for s in p_res["curated_data"]["series"] if "الشرح الثاني" in s["title"])
                assert extract_lesson_num(risala2["lessons"][0]["title"], risala2["title"]) == 1, (
                    f"Gate 4 Failed: bardoni الشرح الثاني للرسالة not reversed: {risala2['lessons'][0]['title']}"
                )

    print(
        f"  [Gate 4] PASS — Compound ordinals, guest/co-scholar discrimination, unclassified matn clustering, "
        f"reverse playlist reversal, semantic state resolution, and real raw corpus curation ({', '.join(tested_real)}) verified with 0 errors."
    )


def run_gate_5_multipart_same_episode_and_category_inference(tmp_path: Path) -> None:
    """
    Gate 5: Multi-Part Same-Episode Grouping, Scholar-Token Isolation & Category Inference Gate (v2.3).
    Verifies:
      1. `infer_series_category` across Arabic & foreign-language titles, `matched_book`, and lesson-title fallback.
      2. `extract_lesson_num` and `is_explicit_part_continuation` on `- 7 تتمة -`, `| حـ 860 | 2 |`,
         `الجزء الثاني (2)`, `مقدمة -2-`, and leading `80 إعراب ...`.
      3. Scholar-name token exclusion in `_score_series_match` preventing false routing of unclassified lessons.
      4. Multi-part same-episode grouping (pre-sort and post-sort), multi-part `مقدمة -1-..-3-`, unnumbered
         index-0 intro promotion, reverse-playlist `تتمة الدرس` child attachment, and `[INVERTED_PARENT_CHILD]`
         prevention when a `>= 300s` clip-titled video shares a Hijri year with a `< 300s` video.
      5. End-to-end `discover_person` -> `auto_curate_person` on real `jifri_raw.json`, `bouti_raw.json`,
         and `kamali_raw.json` with 0 scanner/audit errors and minimal `(م X)` rewrites.
    """
    # 5a. Category inference tests (matched_book, Arabic titles, multilingual titles, lesson fallback)
    assert infer_series_category("شرح السلم المنورق في علم المنطق") == "المنطق والفلسفة"
    assert infer_series_category("شرح كبرى اليقينيات الكونية") == "العقيدة وعلم الكلام"
    assert infer_series_category("شرح جمع الجوامع") == "أصول الفقه وقواعده"
    assert infer_series_category("إعراب القرآن الكريم") == "التفسير وعلوم القرآن"
    assert infer_series_category("شرح متن الصرف الصغير") == "اللغة العربية وعلومها"
    assert infer_series_category("مجالس صحيح البخاري") == "الحديث وعلومه"
    assert infer_series_category("فقه المعاملات المالية") == "الفقه وأصوله"
    assert infer_series_category("دورة التأهيل الأسري وفقه الأسرة") == "التربية والأسرة وفقه النفس"
    assert infer_series_category("أيها المريد - تزكية النفس") == "التزكية والأخلاق"
    assert infer_series_category("فقه السيرة النبوية") == "السيرة والتراجم والتاريخ"
    assert infer_series_category("برنامج أندلسيات") == "السيرة والتراجم والتاريخ"
    assert infer_series_category("خطب الجمعة المنبرية") == "الخطب والمنبر"
    assert infer_series_category("وعي المسلم المعاصر والغزو الفكري") == "الفكر والوعي الحضاري"
    assert infer_series_category("Bouti - English Subtitle") == "مواد مترجمة للغات أخرى"
    assert infer_series_category("مقتطفات وفوائد قصيرة") == "الفوائد والمقتطفات العلمية"
    # Fallback to lesson titles when series title is generic
    assert (
        infer_series_category(
            "دروس جامع التوبة",
            lessons=[
                {"title": "تفسير سورة البقرة - الدرس 1"},
                {"title": "تفسير سورة البقرة - الدرس 2"},
            ],
        )
        == "التفسير وعلوم القرآن"
    )

    # 5b. Multi-part extraction & continuation detection tests
    assert extract_lesson_num("شرح جمع الجوامع - 7 تتمة -", "شرح جمع الجوامع") == 7
    assert is_explicit_part_continuation("شرح جمع الجوامع - 7 تتمة -") is True
    assert extract_lesson_num("شرح رياض الصالحين | حـ 860 | 2 | باب التوبة", "شرح رياض الصالحين") == 860
    assert is_explicit_part_continuation("شرح رياض الصالحين | حـ 860 | 2 | باب التوبة") is True
    assert extract_lesson_num("شرح البردة - المجلس الأول - الجزء الثاني (2)", "شرح البردة") == 1
    assert extract_lesson_num("شرح البردة - الفصل الأول - الجزء الثاني (2)", "شرح البردة") is None
    assert is_explicit_part_continuation("شرح البردة - الفصل الأول - الجزء الثاني (2)") is True
    assert extract_lesson_num("80 إعراب سورة آل عمران الآية 120", "إعراب القرآن الكريم") == 80
    assert extract_lesson_num("شرح كبرى اليقينيات الكونية - مقدمة -2-", "شرح كبرى اليقينيات الكونية") is None

    # 5c. Scholar-name token exclusion in _score_series_match
    bouti_info = {"name": "محمد سعيد رمضان البوطي", "id": "bouti"}
    bouti_excl = _build_sheikh_exclude_tokens(bouti_info)
    assert "البوطي" in bouti_excl and "سعيد" in bouti_excl
    false_score = _score_series_match(
        "محاضرة عامة عن أزمة الشباب | الدكتور محمد سعيد رمضان البوطي",
        {"title": "ندوات تلفزيونية | الدكتور محمد سعيد رمضان البوطي"},
        sheikh_info=bouti_info,
    )
    assert false_score < 0.70, f"Gate 5 Failed: Scholar-name tokens caused false series match score={false_score}"

    # 5d. End-to-end synthetic fixture for multi-part grouping, intro promotion, and inverted-parent prevention
    gate5_raw: dict[str, Any] = {
        "person_id": "gate5sh",
        "sheikh": {
            "id": "gate5sh",
            "name": "الشيخ الخامس",
            "bio": "اختبار التجميع متعدد الأجزاء ومنع إزاحة الترقيم.",
        },
        "series": [
            # Series 1: Multi-part intro (مقدمة -1-..-2-) + out-of-order multi-part episode (Lesson 2 part 1 & part 2 separated)
            {
                "id": "gate5sh__s001",
                "title": "شرح كبرى اليقينيات الكونية",
                "category": "مواعظ ولقاءات عامة",
                "state": "completed",
                "lessons": [
                    {
                        "pos": 1,
                        "yt_id": "vid_ky_i1",
                        "title": "شرح كبرى اليقينيات الكونية - مقدمة -1- د. الشيخ الخامس",
                        "duration": 2100,
                        "is_child": False,
                        "display_no": "1",
                    },
                    {
                        "pos": 2,
                        "yt_id": "vid_ky_i2",
                        "title": "شرح كبرى اليقينيات الكونية - مقدمة -2- د. الشيخ الخامس",
                        "duration": 2050,
                        "is_child": False,
                        "display_no": "2",
                    },
                    {
                        "pos": 3,
                        "yt_id": "vid_ky_01",
                        "title": "شرح كبرى اليقينيات الكونية - الدرس 1 - وجود الخالق",
                        "duration": 2400,
                        "is_child": False,
                        "display_no": "3",
                    },
                    {
                        "pos": 4,
                        "yt_id": "vid_ky_02a",
                        "title": "شرح كبرى اليقينيات الكونية | حـ 2 | 1 | دليل الاختراع",
                        "duration": 2300,
                        "is_child": False,
                        "display_no": "4",
                    },
                    {
                        "pos": 5,
                        "yt_id": "vid_ky_03",
                        "title": "شرح كبرى اليقينيات الكونية | حـ 3 | حقيقة النبوة",
                        "duration": 2350,
                        "is_child": False,
                        "display_no": "5",
                    },
                    {
                        "pos": 6,
                        "yt_id": "vid_ky_02b",
                        "title": "شرح كبرى اليقينيات الكونية | حـ 2 | 2 | تتمة دليل الاختراع",
                        "duration": 2200,
                        "is_child": False,
                        "display_no": "6",
                    },
                    {
                        "pos": 7,
                        "yt_id": "vid_ky_04",
                        "title": "شرح كبرى اليقينيات الكونية | حـ 4 | خاتمة الكتاب وتمام الشرح",
                        "duration": 2500,
                        "is_child": False,
                        "display_no": "7",
                    },
                ],
            },
            # Series 2: Unnumbered index-0 behind-the-scenes intro before Lesson 1..3 + Hijri clip collision test
            {
                "id": "gate5sh__s002",
                "title": "برنامج أيها المريد",
                "category": "مواعظ ولقاءات عامة",
                "state": "completed",
                "lessons": [
                    {
                        "pos": 1,
                        "yt_id": "vid_mr_intro",
                        "title": "كواليس برنامج أيها المريد",
                        "duration": 900,
                        "is_child": False,
                        "display_no": "1",
                    },
                    {
                        "pos": 2,
                        "yt_id": "vid_mr_01",
                        "title": "أيها المريد - الحلقة 1 - بداية الطريق",
                        "duration": 1800,
                        "is_child": False,
                        "display_no": "2",
                    },
                    {
                        "pos": 3,
                        "yt_id": "vid_mr_02",
                        "title": "أيها المريد - الحلقة 2 - محاسبة النفس",
                        "duration": 1850,
                        "is_child": False,
                        "display_no": "3",
                    },
                    {
                        "pos": 4,
                        "yt_id": "vid_mr_03",
                        "title": "أيها المريد - الحلقة 3 - الحلقة الأخيرة وتمام البرنامج",
                        "duration": 1900,
                        "is_child": False,
                        "display_no": "4",
                    },
                ],
            },
            # Series 3: General chronological series with a <300s video and a >=300s "مقطع من..." sharing Hijri year 1435
            {
                "id": "gate5sh__s003",
                "title": "محاضرات عامة",
                "category": "مواعظ ولقاءات عامة",
                "state": "ongoing",
                "lessons": [
                    {
                        "pos": 1,
                        "yt_id": "vid_gen_short",
                        "title": "كلمة قصيرة في عام 1435 هـ",
                        "duration": 120,
                        "is_child": False,
                        "display_no": "1",
                    },
                    {
                        "pos": 2,
                        "yt_id": "vid_gen_long_clip",
                        "title": "مقطع من محاضرة في عام 1435 هـ عن تزكية القلوب",
                        "duration": 650,
                        "is_child": False,
                        "display_no": "2",
                    },
                    {
                        "pos": 3,
                        "yt_id": "vid_gen_full",
                        "title": "محاضرة كاملة في عام 1436 هـ عن آداب طالب العلم",
                        "duration": 2400,
                        "is_child": False,
                        "display_no": "3",
                    },
                ],
            },
        ],
    }
    g5_dir = tmp_path / "gate5_syn"
    g5_dir.mkdir(parents=True, exist_ok=True)
    g5_raw_file = g5_dir / "gate5sh_raw.json"
    with open(g5_raw_file, "w", encoding="utf-8") as f:
        json.dump(gate5_raw, f, ensure_ascii=False, indent=2)

    g5_res = auto_curate_person(
        raw_input=g5_raw_file,
        output_json_path=g5_dir / "gate5sh.json",
        output_series_dir=g5_dir / "series_export",
        db_path=g5_dir / "curated.db",
    )
    assert g5_res["report"]["stage9"]["passed"] is True, f"Gate 5 Synthetic Failed Stage 9: {g5_res['report']['stage9']}"
    g5_series_list = g5_res["curated_data"]["series"]

    # Verify Series 1: Category inferred as العقيدة وعلم الكلام, intro-2 attached under مقدمة, 2b attached under Lesson 2, 0 `(م X)` rewrites!
    s1 = next(s for s in g5_series_list if "اليقينيات" in s["title"])
    assert s1["category"] == "العقيدة وعلم الكلام", f"Expected العقيدة وعلم الكلام, got {s1['category']}"
    s1_parents = [ep for ep in s1["lessons"] if not ep.get("is_child")]
    assert [ep["display_no"] for ep in s1_parents] == ["مقدمة", "1", "2", "3", "4"], (
        f"Gate 5 Failed: Unexpected parent display_nos in s001: {[ep['display_no'] for ep in s1_parents]}"
    )
    assert not any("(م " in ep["title"] for ep in s1["lessons"]), (
        f"Gate 5 Failed: Unexpected (م X) cascade rewrite in s001: {[ep['title'] for ep in s1['lessons']]}"
    )

    # Verify Series 2: Unnumbered index-0 promoted to مقدمة, lessons 1..3 keep clean numbers without `(م X)`
    s2 = next(s for s in g5_series_list if "المريد" in s["title"])
    assert s2["category"] == "التزكية والأخلاق", f"Expected التزكية والأخلاق, got {s2['category']}"
    assert [ep["display_no"] for ep in s2["lessons"]] == ["مقدمة", "1", "2", "3"], (
        f"Gate 5 Failed: Unexpected display_nos in s002: {[ep['display_no'] for ep in s2['lessons']]}"
    )
    assert not any("(م " in ep["title"] for ep in s2["lessons"])

    # 5e. End-to-end discover_person -> auto_curate_person verification on real jifri, bouti, and kamali corpora
    cheikh_raw_dir = Path("/Users/macm1pro/REPOS/cheikh/data/curated_sheikhs")
    tested_v23 = []
    if cheikh_raw_dir.exists():
        for pid in ("jifri", "bouti", "kamali"):
            raw_p = cheikh_raw_dir / f"{pid}_raw.json"
            if not raw_p.exists():
                continue
            p_dir = tmp_path / f"real_v23_{pid}"
            p_dir.mkdir(parents=True, exist_ok=True)
            disc_path = p_dir / f"{pid}_discovered.json"
            discover_person(name="", person_id=pid, offline_fixture=raw_p, output_path=disc_path)
            p_res = auto_curate_person(
                raw_input=disc_path,
                output_json_path=p_dir / f"{pid}.json",
                output_series_dir=p_dir / "series_export",
                db_path=p_dir / "curated.db",
            )
            assert p_res["report"]["stage9"]["passed"] is True, f"Gate 5 Real Corpus Failed on {pid}: {p_res['report']['stage9']}"
            assert p_res["report"]["stage9"]["scanner_flaws_total"] == 0
            assert p_res["report"]["stage9"]["audit_returncode"] == 0
            tested_v23.append(pid)

    print(
        f"  [Gate 5] PASS — Category inference (15 scholarly domains), multi-part episode grouping, "
        f"intro promotion, scholar-token isolation, and end-to-end discovery->curation ({', '.join(tested_v23)}) verified with 0 errors."
    )


def run_gate_6_stopped_boundary_and_subset_series_dedup(tmp_path: Path) -> None:
    """
    Gate 6: Stopped Series Boundary Extraction & Subset Playlist Deduplication Gate.
    Verifies:
      - `_extract_topic_boundary` and `_extract_stopped_boundary_note` across chapters, Quranic ayahs/surahs,
        poetry/matn verses, parenthesized commentary quotes, scholar-name stripping, and book-title disambiguation.
      - `_deduplicate_identical_or_subset_series` across identical/subset playlists (`>= 75%` `yt_id` overlap)
        with complementary lesson recovery and zero stub series.
      - Real-corpus verification on `ayman_raw.json` and `dedew_raw.json` with 0 errors in Stage 9.
    """
    # 6a. Stopped boundary extraction unit checks
    b_fiqh = _extract_stopped_boundary_note(
        last_lesson_title="شرح عمدة الفقه - الدرس 15 - باب شروط الصلاة | الشيخ محمد الحسن الددو",
        series_title="شرح عمدة الفقه",
        first_lesson_title="شرح عمدة الفقه - الدرس 1 - كتاب الطهارة",
        main_lessons_count=15,
    )
    assert "إلى باب شروط الصلاة" in b_fiqh, f"Gate 6 Failed: Expected 'إلى باب شروط الصلاة' in '{b_fiqh}'"

    b_tafsir = _extract_stopped_boundary_note(
        last_lesson_title="مجلس التفسير - الدرس 12 - الآية 45 من سورة البقرة | د. سعيد الكملي",
        series_title="مجلس التفسير",
        first_lesson_title="مجلس التفسير - الدرس 1 - الفاتحة",
        main_lessons_count=12,
    )
    assert "إلى الآية 45 من سورة البقرة" in b_tafsir, (
        f"Gate 6 Failed: Expected 'إلى الآية 45 من سورة البقرة' in '{b_tafsir}'"
    )

    b_surah_range = _extract_stopped_boundary_note(
        last_lesson_title="تفسير القرآن - سورة البقرة (174-176) - الدرس 22 | الشيخ محمد البردوني",
        series_title="تفسير القرآن",
        first_lesson_title="تفسير القرآن - الدرس 1 - الفاتحة",
        main_lessons_count=22,
    )
    assert "إلى الآية 174-176 من سورة البقرة" in b_surah_range, (
        f"Gate 6 Failed: Expected 'إلى الآية 174-176 من سورة البقرة' in '{b_surah_range}'"
    )

    b_alfiyyah = _extract_stopped_boundary_note(
        last_lesson_title="شرح ألفية ابن مالك - الدرس 30 - البيت 120 | الشيخ مولود السريري",
        series_title="شرح ألفية ابن مالك",
        first_lesson_title="شرح ألفية ابن مالك - الدرس 1 - المقدمة",
        main_lessons_count=30,
    )
    assert "إلى البيت 120" in b_alfiyyah, f"Gate 6 Failed: Expected 'إلى البيت 120' in '{b_alfiyyah}'"

    b_qawl = _extract_stopped_boundary_note(
        last_lesson_title="شرح كفاية الطالب الرباني (315) (قوله ومن حلف لا...) | الشيخ مولود السريري",
        series_title="شرح كفاية الطالب الرباني",
        first_lesson_title="شرح كفاية الطالب الرباني (1) المقدمة",
        main_lessons_count=315,
    )
    assert "إلى قوله ومن حلف لا" in b_qawl and "مولود السريري" not in b_qawl, (
        f"Gate 6 Failed: Expected 'إلى قوله ومن حلف لا' without scholar name in '{b_qawl}'"
    )

    b_ibn_salah = _extract_topic_boundary(
        "49 - أقسام طرق نقل الحديث - كتاب علوم الحديث لابن الصلاح",
        fallback="الدرس 49",
        series_title="شرح كتاب علوم الحديث لابن الصلاح",
    )
    assert b_ibn_salah == "أقسام طرق نقل الحديث", (
        f"Gate 6 Failed: Expected 'أقسام طرق نقل الحديث' (not series book title), got '{b_ibn_salah}'"
    )

    # 6b. Subset playlist deduplication unit & synthetic end-to-end checks
    gate6_raw: dict[str, Any] = {
        "person_id": "gate6sh",
        "sheikh": {
            "id": "gate6sh",
            "name": "المهندس أيمن عبد الرحيم",
            "bio": "اختبار دمج السلاسل الفرعية وتوثيق حدود التوقف.",
        },
        "series": [
            # Primary playlist missing Lesson 1 (has Lessons 2..5)
            {
                "id": "gate6sh__s001",
                "title": "مدخل إلي علوم اللغة",
                "category": "اللغة العربية وعلومها",
                "state": "completed",
                "lessons": [
                    {"pos": 1, "yt_id": "vid_lang_02", "title": "مدخل إلى علوم اللغة - المحاضرة 2 - علم الأصوات", "duration": 3600},
                    {"pos": 2, "yt_id": "vid_lang_03", "title": "مدخل إلى علوم اللغة - المحاضرة 3 - علم الصرف", "duration": 3500},
                    {"pos": 3, "yt_id": "vid_lang_04", "title": "مدخل إلى علوم اللغة - المحاضرة 4 - علم النحو", "duration": 3700},
                    {"pos": 4, "yt_id": "vid_lang_05", "title": "مدخل إلى علوم اللغة - المحاضرة 5 - البلاغة والمعاجم وختام الدورة", "duration": 3800},
                ],
            },
            # Subset duplicate playlist (80% overlap: 4/5 shared + Lesson 1 unique)
            {
                "id": "gate6sh__s002",
                "title": "دورة مدخل إلى علوم اللغة العربية | م. أيمن عبد الرحيم",
                "category": "اللغة العربية وعلومها",
                "state": "completed",
                "lessons": [
                    {"pos": 1, "yt_id": "vid_lang_01", "title": "مدخل إلى علوم اللغة - المحاضرة 1 - مقدمة علوم اللغة", "duration": 3550},
                    {"pos": 2, "yt_id": "vid_lang_02", "title": "مدخل إلى علوم اللغة - المحاضرة 2 - علم الأصوات", "duration": 3600},
                    {"pos": 3, "yt_id": "vid_lang_03", "title": "مدخل إلى علوم اللغة - المحاضرة 3 - علم الصرف", "duration": 3500},
                    {"pos": 4, "yt_id": "vid_lang_04", "title": "مدخل إلى علوم اللغة - المحاضرة 4 - علم النحو", "duration": 3700},
                ],
            },
            # Stopped Fiqh commentary ending at باب شروط الصلاة
            {
                "id": "gate6sh__s003",
                "title": "شرح عمدة الفقه",
                "category": "الفقه وأصوله",
                "state": None,
                "lessons": [
                    {"pos": 1, "yt_id": "vid_fq_01", "title": "شرح عمدة الفقه - الدرس 1 - كتاب الطهارة | م. أيمن عبد الرحيم", "duration": 2800},
                    {"pos": 2, "yt_id": "vid_fq_02", "title": "شرح عمدة الفقه - الدرس 2 - باب شروط الصلاة | م. أيمن عبد الرحيم", "duration": 2900},
                ],
            },
        ],
    }

    g6_dir = tmp_path / "gate6_syn"
    g6_dir.mkdir(parents=True, exist_ok=True)
    g6_raw_file = g6_dir / "gate6sh_raw.json"
    with open(g6_raw_file, "w", encoding="utf-8") as f:
        json.dump(gate6_raw, f, ensure_ascii=False, indent=2)

    g6_res = auto_curate_person(
        raw_input=g6_raw_file,
        output_json_path=g6_dir / "gate6sh.json",
        output_series_dir=g6_dir / "series_export",
        db_path=g6_dir / "curated.db",
    )
    assert g6_res["report"]["stage9"]["passed"] is True, f"Gate 6 Synthetic Failed Stage 9: {g6_res['report']['stage9']}"
    assert g6_res["report"]["stage1"]["subset_series_merged_count"] == 1
    g6_series = g6_res["curated_data"]["series"]
    assert len(g6_series) == 2, f"Gate 6 Failed: Expected 2 series after subset merge, got {len(g6_series)}"

    lang_s = next(s for s in g6_series if "علوم اللغة" in s["title"])
    assert [ep["yt_id"] for ep in lang_s["lessons"]] == [
        "vid_lang_01",
        "vid_lang_02",
        "vid_lang_03",
        "vid_lang_04",
        "vid_lang_05",
    ], f"Gate 6 Failed: Expected merged lessons 1..5 in order, got {[ep['yt_id'] for ep in lang_s['lessons']]}"
    assert [ep["display_no"] for ep in lang_s["lessons"]] == ["1", "2", "3", "4", "5"]

    fiqh_s = next(s for s in g6_series if "عمدة الفقه" in s["title"])
    assert fiqh_s["state"] == "stopped"
    assert "إلى باب شروط الصلاة" in fiqh_s["note"], f"Gate 6 Failed: Missing stopping boundary in note: {fiqh_s['note']}"
    assert "إلى باب شروط الصلاة" in fiqh_s["title"], f"Gate 6 Failed: Missing stopping boundary in title: {fiqh_s['title']}"

    # 6c. Real corpus verification on ayman_raw.json and dedew_raw.json
    cheikh_raw_dir = Path("/Users/macm1pro/REPOS/cheikh/data/curated_sheikhs")
    tested_v24 = []
    if cheikh_raw_dir.exists():
        for pid, min_merges in (("ayman", 3), ("dedew", 1)):
            raw_p = cheikh_raw_dir / f"{pid}_raw.json"
            if not raw_p.exists():
                continue
            p_dir = tmp_path / f"real_v24_{pid}"
            p_dir.mkdir(parents=True, exist_ok=True)
            p_res = auto_curate_person(
                raw_input=raw_p,
                output_json_path=p_dir / f"{pid}.json",
                output_series_dir=p_dir / "series_export",
                db_path=p_dir / "curated.db",
            )
            assert p_res["report"]["stage9"]["passed"] is True, f"Gate 6 Real Corpus Failed on {pid}: {p_res['report']['stage9']}"
            assert p_res["report"]["stage9"]["scanner_flaws_total"] == 0
            assert p_res["report"]["stage9"]["audit_returncode"] == 0
            assert p_res["report"]["stage1"]["subset_series_merged_count"] >= min_merges, (
                f"Gate 6 Failed on {pid}: Expected >= {min_merges} subset series merges, got {p_res['report']['stage1']['subset_series_merged_count']}"
            )
            if pid == "ayman":
                ayman_series = p_res["curated_data"]["series"]
                lang_series = [s for s in ayman_series if "علوم اللغة" in s["title"]]
                assert len(lang_series) == 1 and len(lang_series[0]["lessons"]) == 10, (
                    f"Gate 6 Failed on ayman: Expected single 10-lesson 'مدخل إلى علوم اللغة' series, got {len(lang_series)} series"
                )
            tested_v24.append(pid)

    print(
        f"  [Gate 6] PASS — Stopped series boundary extraction (_extract_stopped_boundary_note) and "
        f"subset playlist deduplication (_deduplicate_identical_or_subset_series on {', '.join(tested_v24)}) verified with 0 errors."
    )


def main() -> None:
    print("=== Running sheikh-curation v2.4 6-Layer Quality Gates ===")
    with tempfile.TemporaryDirectory(prefix="sheikh_curation_v2_gate_") as tmp_dir:
        tmp_path = Path(tmp_dir)
        curation_res = run_gate_1_all_9_defects(tmp_path)
        run_gate_2_scanner_and_global_audit(tmp_path, curation_res)
        run_gate_3_series_meta_export(curation_res)
        run_gate_4_real_corpus_semantic_fidelity(tmp_path)
        run_gate_5_multipart_same_episode_and_category_inference(tmp_path)
        run_gate_6_stopped_boundary_and_subset_series_dedup(tmp_path)
    print("\nPASS (0 errors)")


if __name__ == "__main__":
    main()

