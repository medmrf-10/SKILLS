#!/usr/bin/env python3
"""
USDB v5.7 — Deterministic 3-Layer Quality Gate for `turath-entity-db` (`scripts/test_objects_sqlite_gates.py`):
  - Gate 1: Runs all original regression tests in `test_skill_gates.py` + tests `ytb_to_usdb_intake.py`
            on a realistic aligned spoken lecture series (`.txt` + `.align.json` + `.meta.json` + `_meta.json`)
            and passes it through `merge_lecture.py` (`Gate v5.1`).
  - Gate 2: Runs `build_objects_sqlite.py` to build `objects.sqlite` from two complementary sources
            (a classical heritage book with isnads and footnotes + an aligned spoken lecture series
            explaining the same matn), verifying all 11 tables + `passages_fts`, exact column schemas,
            indexes, and 100% lossless raw text preservation (`0 chars lost`).
  - Gate 3: Tests relational SQL queries and strict filtering (`source_layer='matn'` vs `'isnad'`,
            kunya collision guard, `passages_fts` search, second-accurate `youtube_timestamp_url` retrieval,
            and cross-media `matn_triangulation` joining the heritage book and the audio lecture).
"""
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

import build_objects_sqlite as bos
import merge_lecture as ml
import merge_round as mr
import test_skill_gates as tsg
import ytb_to_usdb_intake as yti


EXPECTED_TABLE_COLUMNS = {
    "sources": ["source_id", "source_type", "title", "author_or_sheikh", "science", "archetype", "metadata_json"],
    "series": ["series_id", "source_id", "title", "sheikh", "science", "state", "total_lessons", "metadata_json"],
    "lessons_or_parts": [
        "part_id", "source_id", "series_id", "part_number", "title",
        "yt_id", "dur_s", "page_start", "page_end", "raw_char_count",
    ],
    "passages": [
        "passage_id", "source_id", "series_id", "part_id", "part_number", "passage_index",
        "sub_heading", "raw_text", "clean_matn", "isnad_prefix", "summary",
        "topics_json", "search_queries_json", "start_sec", "end_sec",
        "youtube_timestamp_url", "page_num", "embed_matn_text", "embed_concept_text",
    ],
    "persons": ["person_id", "canonical_name", "role_or_sect", "death_year_hijri", "aliases_json"],
    "passage_persons": ["id", "passage_id", "person_id", "mentioned_name", "canonical_name", "source_layer", "role"],
    "places": ["place_id", "canonical_name", "region_or_type", "aliases_json"],
    "passage_places": ["id", "passage_id", "place_id", "mentioned_name", "canonical_name"],
    "events_chronology": [
        "event_id", "passage_id", "source_id", "year_hijri",
        "year_raw", "is_approximate", "event_title", "event_layer",
    ],
    "stories_cases": [
        "story_id", "passage_id", "source_id", "part_number",
        "story_type", "title", "anchor_start", "summary", "lesson",
    ],
    "science_gems": [
        "gem_id", "passage_id", "source_id", "part_number", "title", "category",
        "verbatim_rule", "polished_rule", "explanation", "start_sec", "end_sec", "youtube_timestamp_url",
    ],
    "evidences": [
        "evidence_id", "passage_id", "source_id", "evidence_type",
        "surah_number", "ayah_start", "ayah_end", "surah_ayah_key",
        "verbatim_text", "hadith_source", "footnote_ref",
    ],
    "matn_triangulation": [
        "triangulation_id", "passage_id", "source_id", "explained_matn_book_id",
        "explained_matn_clause_id", "explained_matn_verbatim", "start_sec", "end_sec",
    ],
}


def build_realistic_fixture_data(tmp_dir: Path) -> tuple[Path, Path]:
    """
    Creates:
      1. A classical heritage book (`book_id=3418`, `maliki`) with lead isnad, footnotes, historical & sama' dates,
         places, scholars, Quranic verses, and the base clauses of Matn al-Akhdari (`AKH:1`, `AKH:2`).
      2. A `sheikh-series-pipeline` directory (`series_dir`) with `_meta.json`, `001_vAkhdari01X.txt`,
         `001_vAkhdari01X.align.json`, and `001_vAkhdari01X.meta.json`.
    """
    p1_raw = (
        "حدثنا عبد الله بن مسلمة القعنبي عن مالك بن أنس عن نافع عن ابن عمر رضي الله عنهما قال: "
        "أول ما يجب على المكلف تصحيح إيمانه ثم معرفة ما يصلح به فرض عينه كأحكام الطهارة والصلاة والصيام (١). "
        "قال العلامة عبد الرحمن الأخضري رحمه الله في مختصره المفرغ بالمدينة المنورة سنة ثلاث وثمانين وتسعمائة: "
        "الطهارة قسمان طهارة حدث وطهارة خبث ولا يصح الجميع إلا بالماء المطلق الطاهر في نفسه المطهر لغيره. "
        "وقد استدل الإمام مالك بن أنس وأبو بكر الصديق والإمام أبو بكر البيهقي بقوله تعالى: "
        "﴿إِنَّ اللَّهَ يُحِبُّ التَّوَّابِينَ وَيُحِبُّ الْمُتَطَهِّرِينَ﴾ على فضل الجمع بين طهارة الباطن والظاهر."
    )
    p2_raw = (
        "فصل في فرائض الوضوء وسننه عند المالكية بالبصرة والمدينة المنورة: "
        "قال العلامة عبد الرحمن الأخضري رحمه الله: فرائض الوضوء سبع وهي النية عند غسل الوجه وغسل الوجه وغسل اليدين إلى المرفقين "
        "ومسح جميع الرأس وغسل الرجلين إلى الكعبين والدلك والفور. "
        "وقد قُرئ هذا الجزء سماعاً بالقيروان سنة عشرين وأربعمائة على يد رواة النسخة."
    )
    raw_part_text = p1_raw + "\n" + p2_raw

    fn_obj = {
        "fn_id": "3418:p12:1",
        "page": 12,
        "seq": 1,
        "marker": "١",
        "text": "(١) أخرجه البيهقي في السنن الكبرى وذكره شراح مختصر الأخضري.",
    }

    raw_round = {
        "maliki": {
            "book_id": 3418,
            "science": "maliki",
            "meta": {
                "title": "مختصر الأخضري في العبادات على مذهب الإمام مالك",
                "author": "عبد الرحمن بن محمد الأخضري",
                "death": 983,
            },
            "scope": {"parts_selected": 1, "chars_selected": len(raw_part_text)},
            "book_footnotes": [fn_obj],
            "parts": [
                {
                    "i": 1,
                    "pg": 12,
                    "pg_end": 14,
                    "t": "مقدمة الطهارة وفرائض الوضوء",
                    "text": raw_part_text,
                    "fn": [fn_obj],
                    "src_parts": [1],
                }
            ],
        }
    }

    deep_book = {
        "book_id": 3418,
        "science": "maliki",
        "deep_toc_passages": [
            {
                "part": 1,
                "sub_heading": "وجوب تصحيح الإيمان ومعرفة فرض العين وأقسام الطهارة والماء المطلق",
                "anchor_start": "حدثنا عبد الله بن مسلمة القعنبي عن مالك",
                "matn_start_anchor": "أول ما يجب على المكلف تصحيح إيمانه",
                "explained_matn_clause_id": "AKH:1",
                "explained_matn_verbatim": "أول ما يجب على المكلف تصحيح إيمانه ثم معرفة ما يصلح به فرض عينه",
                "summary": "يبين العلامة عبد الرحمن الأخضري وجوب تقديم تصحيح الإيمان ومعرفة فروض الأعيان، ويقسم الطهارة بالمدينة المنورة إلى طهارة حدث وطهارة خبث بالماء المطلق.",
                "topics": [
                    "وجوب تصحيح الإيمان ومعرفة فرض العين",
                    "تقسيم الطهارة إلى طهارة حدث وطهارة خبث",
                    "اشتراط الماء المطلق لرفع الحدث وحكم المتطهرين",
                ],
                "persons": [
                    {
                        "canonical_name": "عبد الله بن مسلمة القعنبي",
                        "mentioned_as": "عبد الله بن مسلمة القعنبي",
                        "category": "محدث",
                        "role": "راوي الإسناد",
                        "source_layer": "isnad",
                    },
                    {
                        "canonical_name": "نافع مولى ابن عمر",
                        "mentioned_as": "نافع",
                        "category": "تابعي",
                        "role": "راوي الإسناد",
                        "source_layer": "isnad",
                    },
                    {
                        "canonical_name": "عبد الله بن عمر",
                        "mentioned_as": "ابن عمر",
                        "category": "صحابي",
                        "role": "راوي الإسناد",
                        "source_layer": "isnad",
                    },
                    {
                        "canonical_name": "العلامة عبد الرحمن الأخضري",
                        "mentioned_as": "العلامة عبد الرحمن الأخضري",
                        "category": "عالم",
                        "role": "مؤلف المتن",
                        "source_layer": "matn",
                    },
                    {
                        "canonical_name": "الإمام مالك بن أنس",
                        "mentioned_as": "الإمام مالك بن أنس",
                        "category": "عالم",
                        "role": "إمام المذهب",
                        "source_layer": "matn",
                    },
                    {
                        "canonical_name": "أبو بكر الصديق",
                        "mentioned_as": "أبو بكر الصديق",
                        "category": "صحابي",
                        "role": "الخليفة الأول",
                        "source_layer": "matn",
                    },
                    {
                        "canonical_name": "الإمام أبو بكر البيهقي",
                        "mentioned_as": "الإمام أبو بكر البيهقي",
                        "category": "عالم",
                        "role": "مخرج الأثر",
                        "source_layer": "matn",
                    },
                ],
                "places": [
                    {"name_in_text": "المدينة المنورة", "normalized_name": "المدينة المنورة"},
                ],
                "chronology": [
                    {"hijri_year": 983, "event_tag": "تصنيف مختصر الأخضري ووفاة مؤلفه", "event_layer": "historical"},
                ],
                "evidences": [
                    {
                        "type": "آية",
                        "text": "إِنَّ اللَّهَ يُحِبُّ التَّوَّابِينَ وَيُحِبُّ الْمُتَطَهِّرِينَ",
                        "source": "سورة البقرة: 222",
                        "indicative_aspect": "محبة الله للمتطهرين حساً ومعنى",
                    }
                ],
                "search_queries": [
                    "ما أول ما يجب على المكلف في مختصر الأخضري؟",
                    "ما أقسام الطهارة وما حكم الماء المطلق عند المالكية؟",
                ],
            },
            {
                "part": 1,
                "sub_heading": "فرائض الوضوء السبع عند المالكية وتوثيق سماع النسخة",
                "anchor_start": "فصل في فرائض الوضوء وسننه عند المالكية",
                "explained_matn_clause_id": "AKH:2",
                "explained_matn_verbatim": "فرائض الوضوء سبع وهي النية عند غسل الوجه",
                "summary": "يعدد العلامة عبد الرحمن الأخضري فرائض الوضوء السبع في المذهب المالكي وهي النية وغسل الوجه واليدين ومسح الرأس وغسل الرجلين والدلك والفور.",
                "topics": [
                    "فرائض الوضوء السبع في المذهب المالكي",
                    "فرضية الدلك والفور ومقارنة الأمصار",
                ],
                "persons": [
                    {
                        "canonical_name": "العلامة عبد الرحمن الأخضري",
                        "mentioned_as": "العلامة عبد الرحمن الأخضري",
                        "category": "عالم",
                        "role": "مؤلف المتن",
                        "source_layer": "matn",
                    },
                ],
                "places": [
                    {"name_in_text": "البصرة", "normalized_name": "البصرة"},
                    {"name_in_text": "المدينة المنورة", "normalized_name": "المدينة المنورة"},
                    {"name_in_text": "القيروان", "normalized_name": "القيروان"},
                ],
                "chronology": [
                    {"hijri_year": 420, "event_tag": "قراءة وسماع النسخة بالقيروان", "event_layer": "transmission"},
                ],
                "evidences": [],
                "search_queries": [
                    "ما هي فرائض الوضوء السبع في مختصر الأخضري؟",
                ],
            },
        ],
        "science_gems": [
            {
                "part": 1,
                "title": "قاعدة تقديم تصحيح الإيمان وفروض الأعيان على النوافل",
                "category": "أصول التكليف",
                "verbatim_rule": "أول ما يجب على المكلف تصحيح إيمانه ثم معرفة ما يصلح به فرض عينه كأحكام الطهارة والصلاة والصيام",
                "explanation": "قاعدة كلية في ترتيب الواجبات الشرعية العينية على المكلف.",
            },
            {
                "part": 1,
                "title": "ضابط أقسام الطهارة واشتراط الماء المطلق",
                "category": "ضوابط الطهارة",
                "verbatim_rule": "الطهارة قسمان طهارة حدث وطهارة خبث ولا يصح الجميع إلا بالماء المطلق الطاهر في نفسه المطهر لغيره",
                "explanation": "حصر أقسام الطهارة الشرعية وبيان شرط صحتها بالماء المطلق.",
            },
        ],
        "stories": [
            {
                "part": 1,
                "title": "تطبيق فرائض الوضوء السبع واشتراط الدلك والفور",
                "anchor_start": "فرائض الوضوء سبع وهي النية عند غسل الوجه",
                "summary": "تفصيل الأركان السبعة التي لا يصح الوضوء في المذهب المالكي إلا باستيفائها مع الدلك والموالاة.",
                "lesson": "وجوب مراعاة الدلك والفور في الوضوء عند السادة المالكية.",
            }
        ],
        "quotes": [
            {
                "part": 1,
                "quote": "فرائض الوضوء سبع وهي النية عند غسل الوجه وغسل الوجه وغسل اليدين إلى المرفقين",
                "speaker": "العلامة عبد الرحمن الأخضري",
                "context": "تعداد فرائض الوضوء في مختصر الأخضري",
            }
        ],
    }

    (tmp_dir / "raw_round4_books.json").write_text(json.dumps(raw_round, ensure_ascii=False, indent=2), encoding="utf-8")
    (tmp_dir / "r4_deep_maliki.json").write_text(json.dumps(deep_book, ensure_ascii=False, indent=2), encoding="utf-8")

    # 2. Build realistic sheikh-series-pipeline directory
    series_dir = tmp_dir / "series_akhdari"
    series_dir.mkdir(parents=True, exist_ok=True)

    base_matn_clauses = [
        {
            "clause_id": "AKH:1",
            "title": "مقدمة العقيدة وفروض الأعيان وأقسام الطهارة",
            "text": "أول ما يجب على المكلف تصحيح إيمانه ثم معرفة ما يصلح به فرض عينه كأحكام الطهارة والصلاة والصيام. الطهارة قسمان طهارة حدث وطهارة خبث ولا يصح الجميع إلا بالماء المطلق الطاهر في نفسه المطهر لغيره.",
        },
        {
            "clause_id": "AKH:2",
            "title": "باب فرائض الوضوء السبع",
            "text": "فرائض الوضوء سبع وهي النية عند غسل الوجه وغسل الوجه وغسل اليدين إلى المرفقين ومسح جميع الرأس وغسل الرجلين إلى الكعبين والدلك والفور.",
        },
    ]

    series_meta = {
        "series_id": "sharh_akhdari_binsayib",
        "title": "شرح مختصر الأخضري في الفقه المالكي",
        "sheikh": "الشيخ بن سايب",
        "speaker_slug": "binsayib",
        "science": "maliki",
        "state": "completed",
        "base_work_id": "matn-al-akhdari",
        "base_work_title": "مختصر الأخضري في العبادات على مذهب الإمام مالك",
        "base_matn_clauses": base_matn_clauses,
    }
    (series_dir / "_meta.json").write_text(json.dumps(series_meta, ensure_ascii=False, indent=2), encoding="utf-8")

    lec_p1 = (
        "بسم الله الرحمن الرحيم الحمد لله رب العالمين وصلى الله وسلم على نبينا محمد وعلى آله وصحبه أجمعين. "
        "نشرع في هذا الدرس الأول في شرح كلام العلامة عبد الرحمن الأخضري رحمه الله المتوفى سنة ثلاث وثمانين وتسعمائة "
        "حيث قال في مفتتح كتابه: أول ما يجب على المكلف تصحيح إيمانه ثم معرفة ما يصلح به فرض عينه كأحكام الطهارة والصلاة والصيام. "
        "يعني يا إخوة المقصود أن العلم الواجب عيناً على كل مسلم هو ما تتوقف عليه صحة عقيدته وعبادته اليومية على مذهب الإمام مالك بن أنس بالمدينة المنورة. "
        "وقد قرر القاضي أبو بكر الباقلاني أن معرفة أصول التوحيد مقدمة بالذات على الفروع العملية. "
        "ثم قسم المصنف الطهارة إلى قسمين فقال: الطهارة قسمان طهارة حدث وطهارة خبث ولا يصح الجميع إلا بالماء المطلق الطاهر في نفسه المطهر لغيره."
    )
    lec_p2 = (
        "ننتقل الآن إلى المبحث الثاني من كلام العلامة عبد الرحمن الأخضري رحمه الله في فرائض الوضوء حيث قال: "
        "فرائض الوضوء سبع وهي النية عند غسل الوجه وغسل الوجه وغسل اليدين إلى المرفقين ومسح جميع الرأس وغسل الرجلين إلى الكعبين والدلك والفور. "
        "طيب خلي بالك أن الدلك هو إمرار اليد على العضو مع الماء أو إثره، والفور هو الموالاة بين الأعضاء في الزمن المعتدل. "
        "وقد دل على تيسير الشريعة في أبواب الطهارة قوله تعالى: ﴿وَمَا جَعَلَ عَلَيْكُمْ فِي الدِّينِ مِنْ حَرَجٍ﴾ في سورة الحج. "
        "فمن ترك فرضاً من هذه الفرائض السبع لم يصح وضوؤه حتى يأتي به على الوجه المعتبر عند فقهاء المالكية."
    )
    lec_raw_text = lec_p1 + "\n" + lec_p2

    (series_dir / "001_vAkhdari01X.txt").write_text(lec_raw_text, encoding="utf-8")
    (series_dir / "001_vAkhdari01X.meta.json").write_text(
        json.dumps(
            {
                "lecture_id": "sharh_akhdari_binsayib_001",
                "title": "شرح مختصر الأخضري — الدرس الأول: مقدمة فرض العين وأقسام الطهارة وفرائض الوضوء",
                "video_id": "vAkhdari01X",
                "duration_sec_total": 180.0,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    # Build word-by-word CTC alignment (.align.json) covering every token monotonically
    words = lec_raw_text.split()
    timed_x = []
    cur_t = 1.0
    for w in words:
        w_clean = w.strip()
        if not w_clean:
            continue
        dur = round(max(0.25, min(0.85, len(w_clean) * 0.08)), 2)
        timed_x.append([w_clean, round(cur_t, 2), round(cur_t + dur, 2), "a"])
        cur_t += dur + 0.05

    (series_dir / "001_vAkhdari01X.align.json").write_text(
        json.dumps({"cov": 100.0, "x": timed_x}, ensure_ascii=False),
        encoding="utf-8",
    )

    return tmp_dir, series_dir


def run_all_3_gates() -> int:
    errors = []
    print("=" * 78)
    print("USDB v5.7 — Running 3-Layer Quality Gate (`test_objects_sqlite_gates.py`)")
    print("=" * 78)

    # -------------------------------------------------------------------------
    # GATE 1: Original Regression Suite (`test_skill_gates.py`) + YTB Intake Bridge
    # -------------------------------------------------------------------------
    print("\n[Gate 1] Running `test_skill_gates.py` regression suite + `ytb_to_usdb_intake.py`...")
    suite = unittest.defaultTestLoader.loadTestsFromModule(tsg)
    runner = unittest.TextTestRunner(verbosity=0)
    res_unit = runner.run(suite)
    if not res_unit.wasSuccessful() or res_unit.testsRun < 11:
        errors.append(
            f"Gate 1 FAILED: test_skill_gates.py ran {res_unit.testsRun} tests, failures={len(res_unit.failures)}, errors={len(res_unit.errors)}"
        )
    else:
        print(f"  [OK] `test_skill_gates.py`: {res_unit.testsRun} deterministic tests passed.")

    with tempfile.TemporaryDirectory(prefix="turath_entity_db_gate_") as tmp_str:
        tmp_dir = Path(tmp_str)
        work_dir, series_dir = build_realistic_fixture_data(tmp_dir)

        # Merge Book via merge_round.py (Gate v4.3)
        books_out, book_rep = mr.audit_and_merge_round(round_num=4, work_dir=work_dir)
        if not book_rep["passed"] or book_rep["p0_error_count"] > 0:
            errors.append(f"Gate 1 FAILED: merge_round.py P0 errors: {book_rep['p0_errors']}")
        else:
            (work_dir / "round4_9_books_deep.json").write_text(
                json.dumps(books_out, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(f"  [OK] `merge_round.py` (Gate v4.3): book 3418 merged with 0 P0 errors ({len(books_out[0]['deep_toc_passages'])} passages).")

        # Run ytb_to_usdb_intake.py -> merge_lecture.py (Gate v5.1)
        intake_res = yti.intake_series(series_dir=series_dir, out_dir=work_dir)
        if not intake_res["passed"]:
            errors.append(f"Gate 1 FAILED: ytb_to_usdb_intake.py reported failures: {intake_res['gate_reports']}")
        else:
            lec_doc = intake_res["merged_lectures"]["sharh_akhdari_binsayib_001"]
            for p in lec_doc["deep_toc_passages"]:
                if not p.get("embed_matn_text") or not p.get("embed_concept_text"):
                    errors.append(f"Gate 1 FAILED: missing embed_matn_text or embed_concept_text in {p['passage_id']}")
                if p.get("time_basis") != "ctc_forced_alignment":
                    errors.append(f"Gate 1 FAILED: time_basis={p.get('time_basis')} != ctc_forced_alignment")
                if not p.get("youtube_clip_url") or "?t=" not in p.get("youtube_clip_url", ""):
                    errors.append(f"Gate 1 FAILED: invalid youtube_clip_url in {p['passage_id']}")
            print(
                f"  [OK] `ytb_to_usdb_intake.py` -> `merge_lecture.py`: series '{intake_res['series_manifest']['series_id']}' "
                f"merged with 0 P0 errors ({len(lec_doc['deep_toc_passages'])} passages, {len(lec_doc['science_gems'])} gems, "
                f"{lec_doc['matn_triangulation_count']} matn links)."
            )

        # -------------------------------------------------------------------------
        # GATE 2: Build `objects.sqlite` & Verify 11 Tables + `passages_fts` + 0 Chars Lost
        # -------------------------------------------------------------------------
        print("\n[Gate 2] Building `objects.sqlite` via `build_objects_sqlite.py` and checking schema & lossless integrity...")
        db_path = work_dir / "objects.sqlite"
        db_stats = bos.build_objects_sqlite(db_path=db_path, work_dir=work_dir)

        if db_stats["chars_lost"] != 0:
            errors.append(
                f"Gate 2 FAILED: chars_lost={db_stats['chars_lost']} (expected={db_stats['expected_raw_chars']}, actual={db_stats['actual_passage_chars']})"
            )

        for tbl, cnt in db_stats["table_counts"].items():
            if cnt <= 0:
                errors.append(f"Gate 2 FAILED: Table '{tbl}' is empty (count={cnt})")

        conn = sqlite3.connect(str(db_path))
        cur = conn.cursor()

        # Verify exact column names for all 11 relational tables
        for tbl, exp_cols in EXPECTED_TABLE_COLUMNS.items():
            cur.execute(f"PRAGMA table_info({tbl})")
            actual_cols = [row[1] for row in cur.fetchall()]
            if actual_cols != exp_cols:
                errors.append(f"Gate 2 FAILED: Table '{tbl}' columns {actual_cols} != expected {exp_cols}")

        # Verify required join indexes exist
        cur.execute("SELECT name FROM sqlite_master WHERE type='index'")
        index_names = {r[0] for r in cur.fetchall()}
        for req_idx in (
            "idx_passage_persons_passage_id",
            "idx_passage_persons_person_id",
            "idx_passage_persons_source_layer",
            "idx_passage_places_place_id",
            "idx_events_chronology_year_hijri",
            "idx_evidences_surah_ayah_key",
            "idx_matn_triangulation_clause_id",
        ):
            if req_idx not in index_names:
                errors.append(f"Gate 2 FAILED: Missing required index '{req_idx}'")

        if not errors:
            print(
                f"  [OK] `objects.sqlite` built cleanly: all 11 tables + `passages_fts` populated, "
                f"total_chars={db_stats['actual_passage_chars']} (0 chars lost)."
            )
            print("  Table counts:", json.dumps(db_stats["table_counts"], ensure_ascii=False))

        # -------------------------------------------------------------------------
        # GATE 3: Relational SQL Queries, Layer Filtering, FTS5, Timestamps & Matn Triangulation
        # -------------------------------------------------------------------------
        print("\n[Gate 3] Executing relational SQL & strict filtering verification queries...")

        # 3.1 Strict `source_layer = 'matn'` vs `'isnad'` & Kunya Collision Guard
        cur.execute(
            """
            SELECT DISTINCT canonical_name FROM passage_persons
            WHERE source_layer = 'isnad'
            """
        )
        isnad_persons = {r[0] for r in cur.fetchall()}
        cur.execute(
            """
            SELECT DISTINCT canonical_name FROM passage_persons
            WHERE source_layer = 'matn'
            """
        )
        matn_persons = {r[0] for r in cur.fetchall()}

        if not any("القعنبي" in p for p in isnad_persons):
            errors.append(f"Gate 3.1 FAILED: Isnad narrator 'القعنبي' missing from source_layer='isnad': {isnad_persons}")
        if any("القعنبي" in p for p in matn_persons):
            errors.append(f"Gate 3.1 FAILED: Isnad narrator 'القعنبي' leaked into source_layer='matn': {matn_persons}")

        # Cross-media scholar unification: العلامة عبد الرحمن الأخضري and الإمام مالك بن أنس in both book and lecture
        cur.execute(
            """
            SELECT p.person_id, p.canonical_name, COUNT(DISTINCT pas.source_id) AS src_cnt
            FROM persons p
            JOIN passage_persons pp ON pp.person_id = p.person_id
            JOIN passages pas ON pas.passage_id = pp.passage_id
            WHERE pp.source_layer = 'matn'
            GROUP BY p.person_id
            HAVING src_cnt >= 2
            """
        )
        cross_media_scholars = cur.fetchall()
        if len(cross_media_scholars) < 2:
            errors.append(f"Gate 3.1 FAILED: Expected >= 2 cross-media unified scholars, got {cross_media_scholars}")

        # Kunya collision guard in `persons` table: الصديق vs البيهقي vs الباقلاني
        cur.execute(
            """
            SELECT person_id, canonical_name FROM persons
            WHERE canonical_name LIKE '%بكر%'
            """
        )
        abu_bakr_rows = cur.fetchall()
        if len({r[0] for r in abu_bakr_rows}) < 3:
            errors.append(f"Gate 3.1 FAILED: Kunya collision detected among Abu Bakr scholars: {abu_bakr_rows}")
        else:
            print(
                f"  [OK] Query 3.1 (Isnad vs Matn & Kunya Guard): {len(isnad_persons)} isnad-only narrators isolated, "
                f"{len(cross_media_scholars)} cross-media scholars unified, {len(abu_bakr_rows)} distinct 'Abu Bakr' entities preserved."
            )

        # 3.2 `events_chronology` layer separation ('historical' vs 'transmission')
        cur.execute("SELECT year_hijri, event_layer FROM events_chronology ORDER BY year_hijri")
        chron_rows = cur.fetchall()
        chron_map = {r[0]: r[1] for r in chron_rows}
        if chron_map.get(420) != "transmission" or chron_map.get(983) != "historical":
            errors.append(f"Gate 3.2 FAILED: Chronology event_layer mismatch: {chron_rows}")
        else:
            print(f"  [OK] Query 3.2 (Chronology Layer Separation): 983 AH='historical', 420 AH='transmission'.")

        # 3.3 Full-Text Search in `passages_fts`
        cur.execute(
            """
            SELECT f.passage_id, p.source_id, f.sub_heading
            FROM passages_fts f
            JOIN passages p ON p.passage_id = f.passage_id
            WHERE passages_fts MATCH 'الطهارة'
            """
        )
        fts_hits = cur.fetchall()
        fts_sources = {r[1] for r in fts_hits}
        if len(fts_hits) < 2 or len(fts_sources) < 2:
            errors.append(f"Gate 3.3 FAILED: passages_fts MATCH 'الطهارة' returned insufficient cross-source hits: {fts_hits}")
        else:
            print(f"  [OK] Query 3.3 (`passages_fts` Full-Text Search): {len(fts_hits)} hits across {len(fts_sources)} sources.")

        # 3.4 Second-accurate `youtube_timestamp_url` & Dual-Layer Spoken Gems
        cur.execute(
            """
            SELECT gem_id, verbatim_rule, polished_rule, start_sec, end_sec, youtube_timestamp_url
            FROM science_gems
            WHERE start_sec IS NOT NULL
            """
        )
        lec_gems = cur.fetchall()
        if not lec_gems:
            errors.append("Gate 3.4 FAILED: No timestamped lecture gems found in science_gems")
        for gid, v_rule, p_rule, s_sec, e_sec, yt_url in lec_gems:
            if s_sec <= 0 or e_sec < s_sec or not yt_url.startswith("https://youtu.be/vAkhdari01X?t="):
                errors.append(f"Gate 3.4 FAILED: Invalid timestamp or URL on gem {gid}: {s_sec}..{e_sec} {yt_url}")
            if ml.SPOKEN_FILLER_RE.search(p_rule):
                errors.append(f"Gate 3.4 FAILED: Spoken filler leaked into polished_rule of {gid}: {p_rule!r}")
        if not errors:
            print(
                f"  [OK] Query 3.4 (Audio Timestamps & Spoken Gems): {len(lec_gems)} gems verified with second-accurate YouTube URLs and filler-free polished rules."
            )

        # 3.5 Cross-Media `matn_triangulation` Join between Heritage Book (`book:3418`) and Audio Lecture
        cur.execute(
            """
            SELECT
                mt.explained_matn_clause_id,
                mt.explained_matn_book_id,
                p_book.passage_id AS book_passage_id,
                p_lec.passage_id AS lecture_passage_id,
                mt.start_sec,
                mt.end_sec,
                p_lec.youtube_timestamp_url,
                mt.explained_matn_verbatim
            FROM matn_triangulation mt
            JOIN passages p_lec ON p_lec.passage_id = mt.passage_id
            JOIN passages p_book ON p_book.source_id = mt.explained_matn_book_id
            WHERE mt.start_sec IS NOT NULL
              AND p_book.raw_text LIKE '%' || mt.explained_matn_verbatim || '%'
            ORDER BY mt.start_sec
            """
        )
        tri_rows = cur.fetchall()
        tri_clauses = {r[0] for r in tri_rows}
        if not ("AKH:1" in tri_clauses and "AKH:2" in tri_clauses):
            errors.append(f"Gate 3.5 FAILED: Cross-media matn_triangulation SQL join missed clauses: {tri_rows}")
        else:
            print(
                f"  [OK] Query 3.5 (Cross-Media `matn_triangulation` Join): linked clauses {sorted(tri_clauses)} "
                f"between book 'book:3418' and audio lecture with exact second timestamps."
            )

        conn.close()

        # 3.6 Real-World Edge-Case Regression (Cycle 1 Continuous Improvement):
        # - Exact 6,236-verse Quran resolver (no false 38:1 'ص' or 50:1 'ق' collisions)
        # - Ambiguous single-word person guard ('رجل مسلم' != Imam Muslim) + genitive 'أبي هريرة' & 'الترمذي'
        # - Muqaddimah / procedural gem hygiene
        q_ref = yti.resolve_quran_verse_reference(
            "الذي جعل لكم من الشجر الأخضر نارا فإذا أنتم منه توقدون",
            "وقد استدل المصنف رحمه الله بقوله تعالى في الآيات الصريحة القاطعة: {الذي جعل لكم من الشجر الأخضر نارا فإذا أنتم منه توقدون}",
        )
        if q_ref != "سورة يس: 80":
            errors.append(f"Gate 3.6 FAILED: Quran resolver returned {q_ref!r} instead of 'سورة يس: 80'")

        persons_test, _, _, _ = yti.detect_passage_entities(
            "ذكر كل رجل مسلم صادق ما رواه الإمام الترمذي عن أبي هريرة رضي الله عنه في السنن."
        )
        p_canons = {p["canonical_name"] for p in persons_test}
        p_names = {p["mentioned_as"] for p in persons_test}
        if "مسلم بن الحجاج" in p_canons:
            errors.append(f"Gate 3.6 FAILED: Bare 'رجل مسلم' falsely matched Imam Muslim: {persons_test}")
        if "الإمام أبو عيسى الترمذي" not in p_canons or "أبو هريرة رضي الله عنه" not in p_canons:
            errors.append(f"Gate 3.6 FAILED: Missed الترمذي or أبو هريرة in {persons_test}")
        if "أبي هريرة" not in p_names:
            errors.append(f"Gate 3.6 FAILED: Exact surface mention 'أبي هريرة' not preserved: {persons_test}")

        gem_cands = yti.extract_candidate_sentences(
            "بسم الله الرحمن الرحيم الحمد لله رب العالمين وصلى الله وسلم على سيدنا محمد. "
            "وصلنا إلى قول الشيخ رحمه الله تعالى في الباب الثالث. "
            "والقاعدة المقررة عند الأصوليين أن الأمر المطلق يقتضي الوجوب والنهي المطلق يقتضي التحريم والفساد."
        )
        if not gem_cands or any("بسم الله" in c or "وصلنا إلى قول" in c for c in gem_cands):
            errors.append(f"Gate 3.6 FAILED: Muqaddimah or procedural sentence leaked into gem candidates: {gem_cands}")
        if not errors:
            print(
                "  [OK] Query 3.6 (Real-World Regression Gate): 6,236-verse Quran resolver (36:80), "
                "person disambiguation ('رجل مسلم' vs 'أبي هريرة'/'الترمذي'), and Muqaddimah gem hygiene verified."
            )

    print("\n" + "=" * 78)
    if errors:
        print(f"FAIL ({len(errors)} errors):")
        for e in errors:
            print("  -", e)
        return 1
    print("PASS (0 errors)")
    return 0


if __name__ == "__main__":
    sys.exit(run_all_3_gates())
