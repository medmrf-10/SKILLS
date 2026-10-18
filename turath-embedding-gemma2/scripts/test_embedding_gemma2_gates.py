#!/usr/bin/env python3
"""
بوابة الفحص الحتمية ثلاثية الطبقات (3-Layer Quality Gate) لمهارة turath-embedding-gemma2:
- Gate 1 (Dual Text Hygiene & Vector Generation):
  التحقق من خلو embed_matn_text و embed_concept_text من محارف الترضية المدمجة (\ufd40..\ufd4f)،
  وعلامات الصفحات ([ص: N]، صفحة N، ⦗N⦘، (¬N))، ورواة الإسناد (source_layer='isnad')،
  وتوليد متجهات float32 مطبّعة بـ L2-Norm (||v||_2 == 1.0 ± 1e-5) لكل من passage_embeddings و gem_embeddings.
- Gate 2 (Dual Semantic Retrieval — Matn vs Concept):
  التحقق من أن البحث بعبارة تراثية حرفية يتصدر عبر vec_matn (مع تفوق score_matn > score_concept)،
  والبحث بسؤال مفهومي معاصر يتصدر عبر vec_concept (مع تفوق score_concept > score_matn).
- Gate 3 (Hybrid FTS5 + Vector + Entity Filtering & Isnad Isolation):
  التحقق من أن الفلترة بـ --person مع person_layer='matn' تستبعد المقطع الذي ورد فيه العلم في السند فقط (isnad)
  وتسترجع المقطع الذي ورد فيه في المتن (matn)، مع الفلترة بالمكان والتاريخ الهجري والآية القرآنية وفقرة المتن المشروح
  وإرجاع youtube_timestamp_url الصحيح، وإخراج PASS (0 errors).
"""

from __future__ import annotations

import json
import re
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List

import numpy as np

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from embed_corpus_gemma2 import (  # noqa: E402
    HONORIFIC_RANGE_RE,
    blob_to_vector,
    embed_sqlite_corpus,
)
from hybrid_search import HybridSearchEngine  # noqa: E402


SCHEMA_DDL = """
CREATE TABLE sources (
    source_id TEXT PRIMARY KEY,
    source_type TEXT,
    title TEXT,
    author_or_sheikh TEXT,
    science TEXT,
    archetype TEXT,
    metadata_json TEXT
);

CREATE TABLE series (
    series_id TEXT PRIMARY KEY,
    source_id TEXT,
    title TEXT,
    sheikh TEXT,
    science TEXT,
    state TEXT,
    total_lessons INTEGER,
    metadata_json TEXT
);

CREATE TABLE lessons_or_parts (
    part_id TEXT PRIMARY KEY,
    source_id TEXT,
    series_id TEXT,
    part_number INTEGER,
    title TEXT,
    yt_id TEXT,
    dur_s REAL,
    page_start INTEGER,
    page_end INTEGER,
    raw_char_count INTEGER
);

CREATE TABLE passages (
    passage_id TEXT PRIMARY KEY,
    source_id TEXT,
    series_id TEXT,
    part_id TEXT,
    part_number INTEGER,
    passage_index INTEGER,
    sub_heading TEXT,
    raw_text TEXT,
    clean_matn TEXT,
    isnad_prefix TEXT,
    summary TEXT,
    topics_json TEXT,
    search_queries_json TEXT,
    start_sec REAL,
    end_sec REAL,
    youtube_timestamp_url TEXT,
    page_num INTEGER,
    embed_matn_text TEXT,
    embed_concept_text TEXT
);

CREATE VIRTUAL TABLE passages_fts USING fts5 (
    passage_id UNINDEXED,
    sub_heading,
    raw_text,
    clean_matn,
    summary,
    topics_text,
    search_queries_text
);

CREATE TABLE persons (
    person_id TEXT PRIMARY KEY,
    canonical_name TEXT,
    role_or_sect TEXT,
    death_year_hijri INTEGER,
    aliases_json TEXT
);

CREATE TABLE passage_persons (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    passage_id TEXT,
    person_id TEXT,
    mentioned_name TEXT,
    canonical_name TEXT,
    source_layer TEXT,
    role TEXT
);

CREATE TABLE places (
    place_id TEXT PRIMARY KEY,
    canonical_name TEXT,
    region_or_type TEXT,
    aliases_json TEXT
);

CREATE TABLE passage_places (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    passage_id TEXT,
    place_id TEXT,
    mentioned_name TEXT,
    canonical_name TEXT
);

CREATE TABLE events_chronology (
    event_id TEXT PRIMARY KEY,
    passage_id TEXT,
    source_id TEXT,
    year_hijri INTEGER,
    year_raw TEXT,
    is_approximate INTEGER,
    event_title TEXT,
    event_layer TEXT
);

CREATE TABLE stories_cases (
    story_id TEXT PRIMARY KEY,
    passage_id TEXT,
    source_id TEXT,
    part_number INTEGER,
    story_type TEXT,
    title TEXT,
    anchor_start TEXT,
    summary TEXT,
    lesson TEXT
);

CREATE TABLE science_gems (
    gem_id TEXT PRIMARY KEY,
    passage_id TEXT,
    source_id TEXT,
    part_number INTEGER,
    title TEXT,
    category TEXT,
    verbatim_rule TEXT,
    polished_rule TEXT,
    explanation TEXT,
    start_sec REAL,
    end_sec REAL,
    youtube_timestamp_url TEXT
);

CREATE TABLE evidences (
    evidence_id TEXT PRIMARY KEY,
    passage_id TEXT,
    source_id TEXT,
    evidence_type TEXT,
    surah_number INTEGER,
    ayah_start INTEGER,
    ayah_end INTEGER,
    surah_ayah_key TEXT,
    verbatim_text TEXT,
    hadith_source TEXT,
    footnote_ref TEXT
);

CREATE TABLE matn_triangulation (
    triangulation_id TEXT PRIMARY KEY,
    passage_id TEXT,
    source_id TEXT,
    explained_matn_book_id TEXT,
    explained_matn_clause_id TEXT,
    explained_matn_verbatim TEXT,
    start_sec REAL,
    end_sec REAL
);
"""


def build_test_fixture_db(db_path: Path) -> None:
    """يبني قاعدة بيانات اختبارية شاملة تحاكي الجداول المعيارية لـ build_objects_sqlite.py."""
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(SCHEMA_DDL)

        # 1. المصادر (sources)
        conn.executemany(
            "INSERT INTO sources VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                ("book_muwafaqat", "book", "الموافقات في أصول الشريعة", "أبو إسحاق الشاطبي", "ossoul", "normative", "{}"),
                ("book_muwatta", "book", "الموطأ والمدونة الفقهية", "مالك بن أنس", "maliki", "normative", "{}"),
                ("lec_umm_barahin", "lecture", "شرح متن أم البراهين", "الشيخ علي محمود العمري", "akida", "spoken_lecture", "{}"),
            ],
        )

        # 2. السلاسل (series)
        conn.execute(
            "INSERT INTO series VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("ser_barahin", "lec_umm_barahin", "سلسلة شرح أم البراهين", "الشيخ علي محمود العمري", "akida", "complete", 12, "{}"),
        )

        # 3. الأجزاء والدروس (lessons_or_parts)
        conn.executemany(
            "INSERT INTO lessons_or_parts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                ("part_muwafaqat_1", "book_muwafaqat", None, 1, "كتاب المقاصد والرخص", None, None, 140, 155, 4200),
                ("part_muwatta_1", "book_muwatta", None, 1, "باب جامع الطهارة والنية", None, None, 210, 225, 3800),
                ("part_barahin_2", "lec_umm_barahin", "ser_barahin", 2, "الدرس الثاني: أقسام الحكم العقلي", "umm_barahin_02", 1850.0, None, None, 9500),
            ],
        )

        # 4. المقاطع (passages) — تتضمن عمداً محارف \ufd40..\ufd4f وعلامات صفحات وأسانيد لاختبار Gate 1
        passages_data = [
            (
                "P1_TAYSIR_MATN",
                "book_muwafaqat",
                None,
                "part_muwafaqat_1",
                1,
                1,
                "قاعدة المشقة تجلب التيسير وضوابط الرخص الشرعية",
                "حدثنا قتيبة بن سعيد ثنا الليث بن سعد عن مالك بن أنس \ufd41 قال: [ص: ١٤٢] المشقة تجلب التيسير، والأمر إذا ضاق اتسع، وإنما شرعت الرخصة لرفع الحرج القطعي عن المكلفين (¬٣) صفحة ١٤٣ ⦗١٤٣⦘ ﴿يريد الله بكم اليسر ولا يريد بكم العسر﴾.",
                "[ص: ١٤٢] المشقة تجلب التيسير، والأمر إذا ضاق اتسع، وإنما شرعت الرخصة لرفع الحرج القطعي عن المكلفين (¬٣) صفحة ١٤٣ ⦗١٤٣⦘ ﴿يريد الله بكم اليسر ولا يريد بكم العسر﴾ \ufd40.",
                "حدثنا قتيبة بن سعيد ثنا الليث بن سعد عن مالك بن أنس \ufd41 قال:",
                "تقرير أصل التخفيف الشرعي وبيان ضوابط العمل بالرخص الشرعية عند العذر والمرض والسفر لدفع المشقة الفادحة.",
                json.dumps(["الرخص الشرعية", "رفع الحرج", "أحكام المرض والسفر"], ensure_ascii=False),
                json.dumps([
                    "ما هي ضوابط الرخص الشرعية عند العذر والمرض والسفر؟",
                    "متى ينتقل المكلف من العزيمة إلى الرخصة في الفقه؟",
                ], ensure_ascii=False),
                None,
                None,
                None,
                142,
                "",
                "",
            ),
            (
                "P2_MALIK_MATN",
                "book_muwatta",
                None,
                "part_muwatta_1",
                1,
                2,
                "مذهب الإمام مالك بن أنس في الفتوى بالمدينة المنورة ومراعاة العرف",
                "حدثنا يحيى بن يحيى الليثي قال: [ص: ٢١٥] قرأت على الإمام مالك بن أنس \ufd40 في المدينة المنورة سنة تسع وسبعين ومائة أن المفتي لا ينكر تغير الأحكام بتغير الأزمان والعوائد الجارية بين الناس (¬١) صفحة ٢١٦.",
                "[ص: ٢١٥] قرأت على الإمام مالك بن أنس \ufd40 في المدينة المنورة سنة تسع وسبعين ومائة أن المفتي لا ينكر تغير الأحكام بتغير الأزمان والعوائد الجارية بين الناس (¬١) صفحة ٢١٦.",
                "حدثنا يحيى بن يحيى الليثي قال:",
                "بيان منهج الإمام مالك بن أنس في المدينة المنورة في ربط الفتوى الفقهية بتغير العرف والبيئة الاجتماعية.",
                json.dumps(["تغير الفتوى", "العرف والعادة", "فقه المدينة المنورة"], ensure_ascii=False),
                json.dumps([
                    "كيف يؤثر تغير العرف والبيئة المعاصرة على الفتوى الفقهية؟",
                    "ما منهج مالك بن أنس في مراعاة العوائد بالمدينة المنورة؟",
                ], ensure_ascii=False),
                None,
                None,
                None,
                215,
                "",
                "",
            ),
            (
                "P3_BARAHIN_LECTURE",
                "lec_umm_barahin",
                "ser_barahin",
                "part_barahin_2",
                2,
                1,
                "أقسام الحكم العقلي والفرق بين الواجب العقلي والحكم العادي",
                "يعني يا إخوة طيب نبدأ في قول الإمام السنوسي \ufd40: وأقسام الحكم العقلي ثلاثة الوجوب والاستحالة والجواز، فالواجب العقلي ما لا يتصور في العقل عدمه، والمستحيل ما لا يتصور في العقل وجوده، والجائز ما يصح في العقل وجوده وعدمه تمام؟",
                "وأقسام الحكم العقلي ثلاثة الوجوب والاستحالة والجواز، فالواجب العقلي ما لا يتصور في العقل عدمه، والمستحيل ما لا يتصور في العقل وجوده، والجائز ما يصح في العقل وجوده وعدمه.",
                "",
                "تحرير الفرق المنهجي بين الحكم العقلي المبني على الذات والحكم العادي المبني على التلازم التجريبي وتقسيمات الوجوب والاستحالة والجواز.",
                json.dumps(["الحكم العقلي", "الواجب والمستحيل والجائز", "الفرق بين العقلي والعادي"], ensure_ascii=False),
                json.dumps([
                    "كيف نميز بين الحكم العقلي والحكم العادي في علم الكلام؟",
                    "ما هي أقسام الحكم العقلي الثلاثة في متن أم البراهين؟",
                ], ensure_ascii=False),
                412.5,
                489.0,
                "https://www.youtube.com/watch?v=umm_barahin_02&t=412s",
                None,
                "",
                "",
            ),
        ]
        conn.executemany(
            "INSERT INTO passages VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            passages_data,
        )

        # تعبئة جدول passages_fts
        for p in passages_data:
            pid, _, _, _, _, _, sub_h, raw_t, clean_m, _, summ, top_j, sq_j, *_ = p
            top_txt = " ".join(json.loads(top_j))
            sq_txt = " ".join(json.loads(sq_j))
            conn.execute(
                "INSERT INTO passages_fts VALUES (?, ?, ?, ?, ?, ?, ?)",
                (pid, sub_h, raw_t, clean_m, summ, top_txt, sq_txt),
            )

        # 5. الأعلام (persons & passage_persons)
        # لاحظ: مالك بن أنس في P1_TAYSIR_MATN ورد في السند فقط (source_layer='isnad')!
        # بينما في P2_MALIK_MATN ورد في المتن (source_layer='matn')!
        conn.executemany(
            "INSERT INTO persons VALUES (?, ?, ?, ?, ?)",
            [
                ("per_malik", "مالك بن أنس", "إمام دار الهجرة", 179, json.dumps(["الإمام مالك", "مالك"], ensure_ascii=False)),
                ("per_qutaybah", "قتيبة بن سعيد", "محدث", 240, "[]"),
                ("per_layth", "الليث بن سعد", "فقيه ومحدث", 175, "[]"),
                ("per_yahya", "يحيى بن يحيى الليثي", "راوي الموطأ", 234, "[]"),
                ("per_sanusi", "محمد بن يوسف السنوسي", "متكلم وأصولي", 895, json.dumps(["الإمام السنوسي", "السنوسي"], ensure_ascii=False)),
            ],
        )

        conn.executemany(
            "INSERT INTO passage_persons (passage_id, person_id, mentioned_name, canonical_name, source_layer, role) VALUES (?, ?, ?, ?, ?, ?)",
            [
                ("P1_TAYSIR_MATN", "per_qutaybah", "قتيبة بن سعيد", "قتيبة بن سعيد", "isnad", "narrator"),
                ("P1_TAYSIR_MATN", "per_layth", "الليث بن سعد", "الليث بن سعد", "isnad", "narrator"),
                ("P1_TAYSIR_MATN", "per_malik", "مالك بن أنس", "مالك بن أنس", "isnad", "narrator"),
                ("P2_MALIK_MATN", "per_yahya", "يحيى بن يحيى الليثي", "يحيى بن يحيى الليثي", "isnad", "narrator"),
                ("P2_MALIK_MATN", "per_malik", "الإمام مالك بن أنس", "مالك بن أنس", "matn", "scholar"),
                ("P3_BARAHIN_LECTURE", "per_sanusi", "الإمام السنوسي", "محمد بن يوسف السنوسي", "matn", "author"),
            ],
        )

        # 6. الأماكن (places & passage_places)
        conn.execute(
            "INSERT INTO places VALUES (?, ?, ?, ?)",
            ("plc_madinah", "المدينة المنورة", "الحجاز", json.dumps(["المدينة", "طيبة"], ensure_ascii=False)),
        )
        conn.execute(
            "INSERT INTO passage_places (passage_id, place_id, mentioned_name, canonical_name) VALUES (?, ?, ?, ?)",
            ("P2_MALIK_MATN", "plc_madinah", "المدينة المنورة", "المدينة المنورة"),
        )

        # 7. التواريخ (events_chronology) — تاريخ تاريخي (179 هـ) وتاريخ نسخ مخطوط (745 هـ)
        conn.executemany(
            "INSERT INTO events_chronology VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                ("ev_179", "P2_MALIK_MATN", "book_muwatta", 179, "سنة تسع وسبعين ومائة", 0, "قراءة الموطأ على الإمام مالك ووفاته", "historical"),
                ("ev_745_copy", "P1_TAYSIR_MATN", "book_muwafaqat", 745, "سنة خمس وأربعين وسبعمائة", 0, "سماع النسخة الخطية بدمشق", "transmission"),
            ],
        )

        # 8. القصص والحالات (stories_cases)
        conn.execute(
            "INSERT INTO stories_cases VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("st_1", "P2_MALIK_MATN", "book_muwatta", 1, "applied_case", "قراءة يحيى بن يحيى على مالك", "قرأت على الإمام مالك", "عرض مسائل الموطأ بالمدينة", "اعتبار عمل أهل المدينة والعرف"),
        )

        # 9. القواعد والدرر العلمية (science_gems)
        conn.executemany(
            "INSERT INTO science_gems VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    "G1_TAYSIR",
                    "P1_TAYSIR_MATN",
                    "book_muwafaqat",
                    1,
                    "قاعدة المشقة تجلب التيسير",
                    "قاعدة أصولية وفقهية",
                    "المشقة تجلب التيسير، والأمر إذا ضاق اتسع، وإنما شرعت الرخصة لرفع الحرج القطعي عن المكلفين \ufd40 [ص: ١٤٢]",
                    "المشقة العارضة في المرض والسفر والضرورة سبب شرعي للانتقال من العزيمة إلى الرخصة دفعاً للحرج.",
                    "بيان ارتباط الرخص الشرعية برفع الحرج والمشقة غير المعتادة.",
                    None,
                    None,
                    None,
                ),
                (
                    "G2_URF",
                    "P2_MALIK_MATN",
                    "book_muwatta",
                    1,
                    "قاعدة تغير الفتوى بتغير الأزمان والعوائد",
                    "ضابط فقهي",
                    "المفتي لا ينكر تغير الأحكام بتغير الأزمان والعوائد الجارية بين الناس",
                    "الأحكام الفقهية المبنية على العرف والمصلحة تتغير بتغير البيئة والعصر والعادات الاجتماعية.",
                    "تأصيل مراعاة العرف في الفتوى الفقهية عند المالكية.",
                    None,
                    None,
                    None,
                ),
                (
                    "G3_AQLI",
                    "P3_BARAHIN_LECTURE",
                    "lec_umm_barahin",
                    2,
                    "حد الواجب والمستحيل والجائز العقلي",
                    "قاعدة عقدية",
                    "فالواجب العقلي ما لا يتصور في العقل عدمه، والمستحيل ما لا يتصور في العقل وجوده، والجائز ما يصح في العقل وجوده وعدمه",
                    "ينحصر الحكم العقلي في ثلاثة أقسام: الواجب الذي يمتنع عدمه، والمستحيل الذي يمتنع وجوده، والجائز الذي يقبل الوجود والعدم.",
                    "تمييز الأحكام العقلية الذاتية عن الأحكام العادية التجريبية.",
                    420.0,
                    475.0,
                    "https://www.youtube.com/watch?v=umm_barahin_02&t=420s",
                ),
            ],
        )

        # 10. الشواهد القرآنية (evidences)
        conn.execute(
            "INSERT INTO evidences VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "evd_q_2_185",
                "P1_TAYSIR_MATN",
                "book_muwafaqat",
                "quran",
                2,
                185,
                185,
                "2:185",
                "يريد الله بكم اليسر ولا يريد بكم العسر",
                None,
                "(¬٣)",
            ),
        )

        # 11. تثليث المتون (matn_triangulation)
        conn.execute(
            "INSERT INTO matn_triangulation VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "tri_ub_2",
                "P3_BARAHIN_LECTURE",
                "lec_umm_barahin",
                "umm-al-barahin",
                "UB:2",
                "وأقسام الحكم العقلي ثلاثة الوجوب والاستحالة والجواز",
                412.5,
                489.0,
            ),
        )

        conn.commit()
    finally:
        conn.close()


def build_gate4_real_lecture_db(db_path: Path) -> None:
    """
    يبني قاعدة بيانات Gate 4 من نصوص دروس حقيقية مفرغة (شرح المنظومة العضدية / الوضع،
    شرح نظم الورقات للسريري، وشرح المنظومة العدودية للددو) لاختبار:
    - التوسيع الدلالي والجذور الصرفية لمصطلحات الوضع والاستعمال والحمل والحقيقة والمجاز والمشترك والمتواطئ والكلي والجزئي.
    - صمود FTS5 أمام اختلاف الهمزات والتاء المربوطة والياء وأدوات الاستفهام القالبية.
    - مرونة الفلترة العلائقية بالأعلام (--person بألقاب أو كنى معربة) والأماكن والآيات.
    """
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(SCHEMA_DDL)
        conn.executemany(
            "INSERT INTO sources VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                ("lec_dedew_adud", "lecture", "شرح المنظومة العضدية في الوضع والدلالة", "محمد الحسن الددو", "ossoul", "spoken_lecture", "{}"),
                ("lec_sariri_waraqat", "lecture", "شرح نظم الورقات في أصول الفقه", "مولود السريري", "ossoul", "spoken_lecture", "{}"),
                ("lec_dedew_aqidah", "lecture", "شرح المنظومة العدودية في اعتقاد أهل السنة", "محمد الحسن الددو", "akida", "spoken_lecture", "{}"),
            ],
        )

        passages_rows = [
            (
                "D1_ADUDIYYA_WAD",
                "lec_dedew_adud",
                None,
                "part_adud_1",
                1,
                1,
                "المبحث 1: تحرير مراتب الوضع والاستعمال والحمل والحقيقة والمجاز",
                "إن الوضع عند الأصوليين واللغويين هو تعيين اللفظ بإزاء المعنى، ويتفرع عنه الاستعمال وهو إطلاق اللفظ وإرادة المعنى، ثم الحمل وهو اعتقاد السامع مراد المتكلم من لفظه، فإن استعمل اللفظ فيما وضع له أولاً فهو الحقيقة، وإن استعمل في غير ما وضع له لعلاقة وقرينة مانعة من إرادة المعنى الأصلي فهو المجاز كما قرره العلامة محمد الأمين الشنقيطي.",
                "إن الوضع عند الأصوليين واللغويين هو تعيين اللفظ بإزاء المعنى، ويتفرع عنه الاستعمال وهو إطلاق اللفظ وإرادة المعنى، ثم الحمل وهو اعتقاد السامع مراد المتكلم من لفظه، فإن استعمل اللفظ فيما وضع له أولاً فهو الحقيقة، وإن استعمل في غير ما وضع له لعلاقة وقرينة مانعة من إرادة المعنى الأصلي فهو المجاز.",
                "",
                "يقرر محمد الحسن الددو في هذا المبحث (تحرير مراتب الوضع والاستعمال والحمل) من درس (شرح المنظومة العضدية) تحرير المسألة وتفصيل ضوابطها: الفرق بين الوضع والاستعمال والحمل وأقسام الدلالة الوضعية بين الحقيقة والمجاز.",
                json.dumps(["الوضع والاستعمال والحمل", "الحقيقة والمجاز", "الضوابط التأصيلية في الدرس الأول"], ensure_ascii=False),
                json.dumps(["ما حكم وضابط «الوضع والاستعمال والحمل» عند محمد الحسن الددو؟"], ensure_ascii=False),
                120.0,
                260.0,
                "https://www.youtube.com/watch?v=adud_01&t=120s",
                None,
                "",
                "",
            ),
            (
                "D2_SARIRI_MUSHTARAK",
                "lec_sariri_waraqat",
                None,
                "part_war_1",
                1,
                2,
                "المبحث 2: اللفظ المشترك والمتواطئ والكلي والجزئي وحجية الإجماع",
                "الأصل في الألفاظ عدم الاشتراك، واللفظ المشترك إذا أطلق يتوقف فيه حتى ترد القرينة التي تبينه بناء على أن المشترك يفيد الإجمال، بخلاف المتواطئ الذي يصدق معناه الكلي على أفراده الجزئية بالتساوي، وعلم المنطق تكفل بالكليات الخمس والحدود، كما أن الإجماع حجة قطعية في أصول الفقه.",
                "الأصل في الألفاظ عدم الاشتراك، واللفظ المشترك إذا أطلق يتوقف فيه حتى ترد القرينة التي تبينه بناء على أن المشترك يفيد الإجمال، بخلاف المتواطئ الذي يصدق معناه الكلي على أفراده الجزئية بالتساوي، وعلم المنطق تكفل بالكليات الخمس والحدود، كما أن الإجماع حجة قطعية في أصول الفقه.",
                "",
                "بيان حكم اللفظ المشترك والفرق بينه وبين المتواطئ وتقسيم المعاني إلى الكلي والجزئي وتقرير حجية الإجماع.",
                json.dumps(["المشترك والمتواطئ", "الكلي والجزئي", "الإجماع"], ensure_ascii=False),
                json.dumps(["ما الفرق بين اللفظ المشترك والمتواطئ والكلي والجزئي؟"], ensure_ascii=False),
                310.0,
                450.0,
                "https://www.youtube.com/watch?v=MwmXm6poras&t=310s",
                None,
                "",
                "",
            ),
            (
                "D3_DEDEW_KALAM",
                "lec_dedew_aqidah",
                None,
                "part_dedew_5",
                5,
                6,
                "المبحث 6: خلاف المنتسبين للسنة في الكلام النفسي ومسألة القرآن",
                "إن القرآن كلام الله حقيقة لا مجازاً بالحروف والمعاني، وذكر أحمد بن عبد الحليم بن تيمية أن من قصر الكلام على المعنى والكلام النفسي فقط فقد خالف السلف، واستدل بآية الكرسي {اللَّهُ لَا إِلَهَ إِلَّا هُوَ الْحَيُّ الْقَيُّومُ}.",
                "إن القرآن كلام الله حقيقة لا مجازاً بالحروف والمعاني، وذكر أحمد بن عبد الحليم بن تيمية أن من قصر الكلام على المعنى والكلام النفسي فقط فقد خالف السلف.",
                "",
                "يقرر محمد الحسن الددو في هذا المبحث (خلاف أهل السنة في الكلام) من درس (شرح المنظومة العدودية) تحرير المسألة وتفصيل ضوابطها: مسألة خلق القرآن والكلام النفسي ومذهب السلف.",
                json.dumps(["كلام الله والقرآن", "الكلام النفسي"], ensure_ascii=False),
                json.dumps(["ما حكم وضابط «القرآن كلام الله» عند محمد الحسن الددو؟"], ensure_ascii=False),
                510.0,
                640.0,
                "https://www.youtube.com/watch?v=wJd0T9BkymQ&t=510s",
                None,
                "",
                "",
            ),
            (
                "D4_DEDEW_HALF_ABAA",
                "lec_dedew_aqidah",
                None,
                "part_dedew_6",
                6,
                6,
                "المبحث 6: لا تحلفوا بآبائكم والنهي عن الشرك الأصغر",
                "في حديث أبي هريرة رضي الله عنه أن النبي صلى الله عليه وسلم قال في مكة: لا تحلفوا بآبائكم، فمن كان حالفاً فليحلف بالله أو ليصمت، لأن الحلف بغير الله من أفراد الشرك الأصغر.",
                "لا تحلفوا بآبائكم، فمن كان حالفاً فليحلف بالله أو ليصمت، لأن الحلف بغير الله من أفراد الشرك الأصغر.",
                "",
                "يقرر محمد الحسن الددو في هذا المبحث (لا تحلفوا بآبائكم) من درس (شرح المنظومة العدودية) تحرير المسألة وتفصيل ضوابطها: النهي عن الحلف بالآباء وبيان الشرك الأصغر.",
                json.dumps(["تحرير مسألة: لا تحلفوا بآبائكم", "الشرك الأصغر"], ensure_ascii=False),
                json.dumps(["ما حكم وضابط «لا تحلفوا بآبائكم» عند محمد الحسن الددو؟"], ensure_ascii=False),
                720.0,
                830.0,
                "https://www.youtube.com/watch?v=_ghw18kXujk&t=720s",
                None,
                "",
                "",
            ),
            (
                "D5_DEDEW_SADAQAH",
                "lec_dedew_aqidah",
                None,
                "part_dedew_6",
                6,
                8,
                "المبحث 8: داووا مرضاكم بالصدقة ورفع البلاء بالتوبة",
                "وفيما أورده الإمام أبو عيسى الترمذي في الحديث: داووا مرضاكم بالصدقة، فإنه لم ينزل بلاء إلا بذنب ولم يكشف إلا بتوبة، كما قال نوح لقومه {فَقُلْتُ اسْتَغْفِرُوا رَبَّكُمْ إِنَّهُ كَانَ غَفَّارًا}.",
                "داووا مرضاكم بالصدقة، فإنه لم ينزل بلاء إلا بذنب ولم يكشف إلا بتوبة.",
                "",
                "يقرر محمد الحسن الددو في هذا المبحث (داووا مرضاكم بالصدقة) من درس (شرح المنظومة العدودية) تحرير المسألة وتفصيل ضوابطها: مشروعية التداوي بالصدقة والاستغفار لشفاء المرضى.",
                json.dumps(["تحرير مسألة: داووا مرضاكم بالصدقة", "التداوي بالصدقة"], ensure_ascii=False),
                json.dumps(["ما حكم وضابط «داووا مرضاكم بالصدقة» عند محمد الحسن الددو؟"], ensure_ascii=False),
                910.0,
                1020.0,
                "https://www.youtube.com/watch?v=_ghw18kXujk&t=910s",
                None,
                "",
                "",
            ),
            (
                "D6_DEDEW_NADHR",
                "lec_dedew_aqidah",
                None,
                "part_dedew_6",
                6,
                17,
                "المبحث 17: والنذر غير ذلك كالنذر المعلق؛ كمن ينذر لله",
                "والنذر غير ذلك كالنذر المعلق؛ كمن ينذر لله إن شفاه من مرض، أو إن قدم غائب، أو إن رزق ولداً؛ فهذا مكروه ولكنه ينعقد ويجب الوفاء به إذا تحقق الشرط الذي علق عليه، فيجب الوفاء بالنذر.",
                "والنذر غير ذلك كالنذر المعلق؛ كمن ينذر لله إن شفاه من مرض، أو إن قدم غائب؛ فهذا مكروه ولكنه ينعقد ويجب الوفاء به إذا تحقق الشرط الذي علق عليه.",
                "",
                "يقرر محمد الحسن الددو في هذا المبحث (والنذر غير ذلك كالنذر المعلق) من درس (شرح المنظومة العدودية) تحرير المسألة وتفصيل ضوابطها: حكم النذر المعلق على شرط ووجوب الوفاء به مع الكراهة.",
                json.dumps(["تحرير مسألة: والنذر المعلق", "أحكام النذر"], ensure_ascii=False),
                json.dumps(["ما حكم وضابط «والنذر غير ذلك كالنذر المعلق» عند محمد الحسن الددو؟"], ensure_ascii=False),
                1340.0,
                1450.0,
                "https://www.youtube.com/watch?v=_ghw18kXujk&t=1340s",
                None,
                "",
                "",
            ),
        ]
        conn.executemany(
            "INSERT INTO passages VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            passages_rows,
        )

        for p in passages_rows:
            pid, _, _, _, _, _, sub_h, raw_t, clean_m, _, summ, top_j, sq_j, *_ = p
            conn.execute(
                "INSERT INTO passages_fts VALUES (?, ?, ?, ?, ?, ?, ?)",
                (pid, sub_h, raw_t, clean_m, summ, " ".join(json.loads(top_j)), " ".join(json.loads(sq_j))),
            )

        conn.executemany(
            "INSERT INTO persons VALUES (?, ?, ?, ?, ?)",
            [
                ("per_tirmidhi", "الإمام أبو عيسى الترمذي", "محدث", 279, json.dumps(["الإمام أبو عيسى الترمذي", "الترمذي"], ensure_ascii=False)),
                ("per_abu_hurayrah", "أبو هريرة رضي الله عنه", "صحابي", 57, json.dumps(["أبو هريرة رضي الله عنه", "أبي هريرة"], ensure_ascii=False)),
                ("per_ibn_taymiyyah", "أحمد بن عبد الحليم بن تيمية", "عالم", 728, json.dumps(["أحمد بن عبد الحليم بن تيمية", "ابن تيمية"], ensure_ascii=False)),
                ("per_shanqiti", "العلامة محمد الأمين الشنقيطي رحمه الله", "أصولي ومفسر", 1393, json.dumps(["العلامة محمد الأمين الشنقيطي"], ensure_ascii=False)),
            ],
        )
        conn.executemany(
            "INSERT INTO passage_persons (passage_id, person_id, mentioned_name, canonical_name, source_layer, role) VALUES (?, ?, ?, ?, ?, ?)",
            [
                ("D5_DEDEW_SADAQAH", "per_tirmidhi", "الإمام أبو عيسى الترمذي", "الإمام أبو عيسى الترمذي", "matn", "scholar"),
                ("D4_DEDEW_HALF_ABAA", "per_abu_hurayrah", "أبي هريرة رضي الله عنه", "أبو هريرة رضي الله عنه", "matn", "companion"),
                ("D3_DEDEW_KALAM", "per_ibn_taymiyyah", "أحمد بن عبد الحليم بن تيمية", "أحمد بن عبد الحليم بن تيمية", "matn", "scholar"),
                ("D1_ADUDIYYA_WAD", "per_shanqiti", "العلامة محمد الأمين الشنقيطي", "العلامة محمد الأمين الشنقيطي رحمه الله", "matn", "scholar"),
            ],
        )

        conn.execute(
            "INSERT INTO places VALUES (?, ?, ?, ?)",
            ("plc_makkah", "مكه", "حاضرة / إقليم تاريخي", json.dumps(["مكه"], ensure_ascii=False)),
        )
        conn.execute(
            "INSERT INTO passage_places (passage_id, place_id, mentioned_name, canonical_name) VALUES (?, ?, ?, ?)",
            ("D4_DEDEW_HALF_ABAA", "plc_makkah", "مكه", "مكه"),
        )

        conn.executemany(
            "INSERT INTO evidences VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                ("ev_g4_2_255", "D3_DEDEW_KALAM", "lec_dedew_aqidah", "quran", 2, 255, 255, "2:255", "اللَّهُ لَا إِلَهَ إِلَّا هُوَ الْحَيُّ الْقَيُّومُ", None, None),
                ("ev_g4_71_10", "D5_DEDEW_SADAQAH", "lec_dedew_aqidah", "quran", 71, 10, 10, "71:10", "فَقُلْتُ اسْتَغْفِرُوا رَبَّكُمْ إِنَّهُ كَانَ غَفَّارًا", None, None),
            ],
        )
        conn.commit()
    finally:
        conn.close()


def run_quality_gates() -> int:
    errors: List[str] = []

    with tempfile.TemporaryDirectory(prefix="turath_gemma2_gate_") as tmpdir:
        db_path = Path(tmpdir) / "test_turath_objects.sqlite"
        build_test_fixture_db(db_path)

        # تشغيل محرك التضمين المزدوج
        stats = embed_sqlite_corpus(
            db_path=db_path,
            backend="deterministic-arabic-mps",
            dim=768,
            use_mps=True,
        )
        if stats["passages_embedded"] != 3 or stats["gems_embedded"] != 3:
            errors.append(f"[Gate 1] Unexpected embedded counts: {stats}")

        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row

        # ===================================================================
        # Gate 1: Dual Text Hygiene & Vector Generation
        # ===================================================================
        p_emb_rows = conn.execute("SELECT * FROM passage_embeddings ORDER BY passage_id").fetchall()
        g_emb_rows = conn.execute("SELECT * FROM gem_embeddings ORDER BY gem_id").fetchall()

        if len(p_emb_rows) != 3:
            errors.append(f"[Gate 1] Expected 3 rows in passage_embeddings, got {len(p_emb_rows)}")
        if len(g_emb_rows) != 3:
            errors.append(f"[Gate 1] Expected 3 rows in gem_embeddings, got {len(g_emb_rows)}")

        page_noise_re = re.compile(r"\[\s*ص\s*:|\bصفحة\s+[٠-٩0-9]+|⦗|⦘|\(\s*¬")

        for r in p_emb_rows:
            pid = r["passage_id"]
            for field_name in ("embed_matn_text", "embed_concept_text"):
                txt = r[field_name]
                if HONORIFIC_RANGE_RE.search(txt):
                    errors.append(f"[Gate 1] Honorific ligature \\ufd40..\\ufd4f leaked into {field_name} of {pid}")
                if page_noise_re.search(txt):
                    errors.append(f"[Gate 1] Page/footnote marker leaked into {field_name} of {pid}: {txt}")

            # فحص عزل رواة السند (قتيبة بن سعيد، الليث بن سعد، يحيى بن يحيى، ومالك في P1)
            if "قتيبة" in r["embed_concept_text"] or "الليث بن سعد" in r["embed_concept_text"]:
                errors.append(f"[Gate 1] Isnad narrator leaked into embed_concept_text of {pid}")
            if "قتيبة" in r["embed_matn_text"] or "الليث بن سعد" in r["embed_matn_text"]:
                errors.append(f"[Gate 1] Isnad narrator leaked into embed_matn_text of {pid}")
            if pid == "P1_TAYSIR_MATN" and "مالك بن أنس" in r["embed_concept_text"]:
                errors.append("[Gate 1] Isnad-only Malik leaked into P1_TAYSIR_MATN embed_concept_text")
            if pid == "P1_TAYSIR_MATN" and "745" in r["embed_concept_text"]:
                errors.append("[Gate 1] Manuscript transmission year 745 leaked into P1_TAYSIR_MATN embed_concept_text")

            # فحص متجهات float32 وتطبيع L2-Norm (||v||_2 == 1.0 ± 1e-5)
            v_matn = blob_to_vector(r["vec_matn_blob"], r["dim"])
            v_conc = blob_to_vector(r["vec_concept_blob"], r["dim"])
            if v_matn.dtype != np.float32 or v_conc.dtype != np.float32:
                errors.append(f"[Gate 1] Vector dtype is not float32 for {pid}")
            if v_matn.shape != (768,) or v_conc.shape != (768,):
                errors.append(f"[Gate 1] Vector shape is not (768,) for {pid}")

            norm_m = float(np.linalg.norm(v_matn))
            norm_c = float(np.linalg.norm(v_conc))
            if abs(norm_m - 1.0) > 1e-5:
                errors.append(f"[Gate 1] vec_matn L2 norm for {pid} is {norm_m}, expected 1.0 ± 1e-5")
            if abs(norm_c - 1.0) > 1e-5:
                errors.append(f"[Gate 1] vec_concept L2 norm for {pid} is {norm_c}, expected 1.0 ± 1e-5")

        for r in g_emb_rows:
            gid = r["gem_id"]
            for field_name in ("embed_matn_text", "embed_concept_text"):
                txt = r[field_name]
                if HONORIFIC_RANGE_RE.search(txt):
                    errors.append(f"[Gate 1] Honorific ligature leaked into gem {gid} {field_name}")
                if page_noise_re.search(txt):
                    errors.append(f"[Gate 1] Page marker leaked into gem {gid} {field_name}")
            v_gm = blob_to_vector(r["vec_matn_blob"], r["dim"])
            v_gc = blob_to_vector(r["vec_concept_blob"], r["dim"])
            if abs(float(np.linalg.norm(v_gm)) - 1.0) > 1e-5 or abs(float(np.linalg.norm(v_gc)) - 1.0) > 1e-5:
                errors.append(f"[Gate 1] Gem vector L2 norm out of tolerance for {gid}")

        conn.close()

        # ===================================================================
        # Gate 2: Dual Semantic Retrieval — Matn vs Concept
        # ===================================================================
        with HybridSearchEngine(db_path=db_path, backend="deterministic-arabic-mps") as engine:
            # 2.A: بحث بعبارة تراثية حرفية من المتن -> يتصدر عبر vec_matn وتتفوق score_matn على score_concept
            res_matn_1 = engine.search(
                query="المشقة تجلب التيسير والأمر إذا ضاق اتسع",
                mode="matn",
                top_k=3,
            )
            if not res_matn_1 or res_matn_1[0]["passage_id"] != "P1_TAYSIR_MATN":
                errors.append(f"[Gate 2] Classical phrase query failed to rank P1_TAYSIR_MATN #1: {res_matn_1}")
            elif res_matn_1[0]["score_matn"] <= res_matn_1[0]["score_concept"]:
                errors.append(
                    f"[Gate 2] Expected score_matn > score_concept for verbatim phrase query, got "
                    f"matn={res_matn_1[0]['score_matn']} vs concept={res_matn_1[0]['score_concept']}"
                )

            res_matn_2 = engine.search(
                query="الواجب العقلي ما لا يتصور في العقل عدمه والمستحيل ما لا يتصور في العقل وجوده",
                mode="matn",
                top_k=3,
            )
            if not res_matn_2 or res_matn_2[0]["passage_id"] != "P3_BARAHIN_LECTURE":
                errors.append("[Gate 2] Classical kalam matn query failed to rank P3_BARAHIN_LECTURE #1")
            elif res_matn_2[0]["score_matn"] <= res_matn_2[0]["score_concept"]:
                errors.append(
                    f"[Gate 2] Expected score_matn > score_concept for kalam verbatim query, got "
                    f"matn={res_matn_2[0]['score_matn']} vs concept={res_matn_2[0]['score_concept']}"
                )

            # 2.B: بحث بسؤال مفهومي معاصر -> يتصدر عبر vec_concept وتتفوق score_concept على score_matn
            res_conc_1 = engine.search(
                query="ما هي ضوابط الرخص الشرعية عند العذر والمرض والسفر؟",
                mode="concept",
                top_k=3,
            )
            if not res_conc_1 or res_conc_1[0]["passage_id"] != "P1_TAYSIR_MATN":
                errors.append("[Gate 2] Modern conceptual query failed to rank P1_TAYSIR_MATN #1")
            elif res_conc_1[0]["score_concept"] <= res_conc_1[0]["score_matn"]:
                errors.append(
                    f"[Gate 2] Expected score_concept > score_matn for modern conceptual query, got "
                    f"concept={res_conc_1[0]['score_concept']} vs matn={res_conc_1[0]['score_matn']}"
                )

            res_conc_2 = engine.search(
                query="كيف يؤثر تغير العرف والبيئة المعاصرة على الفتوى الفقهية؟",
                mode="concept",
                top_k=3,
            )
            if not res_conc_2 or res_conc_2[0]["passage_id"] != "P2_MALIK_MATN":
                errors.append("[Gate 2] Modern fatwa/urf conceptual query failed to rank P2_MALIK_MATN #1")
            elif res_conc_2[0]["score_concept"] <= res_conc_2[0]["score_matn"]:
                errors.append(
                    f"[Gate 2] Expected score_concept > score_matn for fatwa/urf query, got "
                    f"concept={res_conc_2[0]['score_concept']} vs matn={res_conc_2[0]['score_matn']}"
                )

            # 2.C: فحص البحث المباشر في القواعد العلمية (gem_embeddings)
            gem_hits = engine.search_gems("الانتقال من العزيمة إلى الرخصة في المرض والسفر", mode="concept", top_k=2)
            if not gem_hits or gem_hits[0]["gem_id"] != "G1_TAYSIR":
                errors.append(f"[Gate 2] Gem search failed to rank G1_TAYSIR #1: {gem_hits}")

            # ===================================================================
            # Gate 3: Hybrid FTS5 + Vector + Entity Filtering & Isnad Isolation
            # ===================================================================
            # 3.A: الفلترة بـ --person "مالك بن أنس" مع person_layer='matn' (الافتراضي)
            # يجب أن تستبعد P1_TAYSIR_MATN (حيث ورد مالك في السند فقط) وتسترجع P2_MALIK_MATN فقط!
            malik_matn_hits = engine.search(
                query="الأحكام والفتوى",
                person="مالك بن أنس",
                person_layer="matn",
                top_k=5,
            )
            malik_matn_pids = [h["passage_id"] for h in malik_matn_hits]
            if malik_matn_pids != ["P2_MALIK_MATN"]:
                errors.append(
                    f"[Gate 3] Isnad Isolation failed: person='مالك بن أنس' (person_layer='matn') "
                    f"returned {malik_matn_pids}, expected ['P2_MALIK_MATN'] only!"
                )

            # التحقق من أن person_layer='isnad' يسترجع المقطع الإسنادي عند طلبه صراحة
            malik_isnad_hits = engine.search(
                query="المشقة",
                person="مالك بن أنس",
                person_layer="isnad",
                top_k=5,
            )
            if [h["passage_id"] for h in malik_isnad_hits] != ["P1_TAYSIR_MATN"]:
                errors.append("[Gate 3] Explicit person_layer='isnad' filter failed to retrieve P1_TAYSIR_MATN")

            # 3.B: الفلترة بالمكان (--place) والتاريخ الهجري التاريخي (--year-min / --year-max)
            place_year_hits = engine.search(
                query="تغير الأحكام والعوائد",
                place="المدينة المنورة",
                year_min=150,
                year_max=200,
                top_k=5,
            )
            if len(place_year_hits) != 1 or place_year_hits[0]["passage_id"] != "P2_MALIK_MATN":
                errors.append(f"[Gate 3] Place + Historical Year filter failed: {place_year_hits}")
            elif place_year_hits[0]["page_num"] != 215:
                errors.append(f"[Gate 3] Expected page_num=215 for P2_MALIK_MATN, got {place_year_hits[0]['page_num']}")

            # التأكد من أن سنة نسخ المخطوط (745 هـ، event_layer='transmission') معزولة عن فلتر التاريخ التاريخي
            transmission_year_hits = engine.search(
                query="المشقة",
                year_min=700,
                year_max=800,
                top_k=5,
            )
            if transmission_year_hits:
                errors.append(
                    f"[Gate 3] Transmission year 745 leaked into historical year filter: {transmission_year_hits}"
                )

            # 3.C: الفلترة بالشاهد القرآني (--ayah 2:185 و --surah 2)
            ayah_hits = engine.search(
                query="يريد الله بكم اليسر",
                ayah="2:185",
                surah=2,
                top_k=5,
            )
            if len(ayah_hits) != 1 or ayah_hits[0]["passage_id"] != "P1_TAYSIR_MATN":
                errors.append(f"[Gate 3] Quranic ayah filter (2:185) failed: {ayah_hits}")

            # 3.D: الفلترة بفقرة المتن المشروح (--matn-clause UB:2) ونوع المصدر والعلم والتحقق من youtube_timestamp_url
            lecture_hits = engine.search(
                query="أقسام الحكم العقلي والفرق بين الواجب والمستحيل",
                science="akida",
                source_type="lecture",
                matn_clause="UB:2",
                top_k=5,
            )
            if len(lecture_hits) != 1 or lecture_hits[0]["passage_id"] != "P3_BARAHIN_LECTURE":
                errors.append(f"[Gate 3] Lecture + matn_clause='UB:2' filter failed: {lecture_hits}")
            else:
                lh = lecture_hits[0]
                if lh["youtube_timestamp_url"] != "https://www.youtube.com/watch?v=umm_barahin_02&t=412s":
                    errors.append(f"[Gate 3] Invalid youtube_timestamp_url: {lh['youtube_timestamp_url']}")
                if lh["start_sec"] != 412.5 or lh["end_sec"] != 489.0:
                    errors.append(f"[Gate 3] Invalid start_sec/end_sec: {lh['start_sec']}..{lh['end_sec']}")
                if not lh["science_gems"] or lh["science_gems"][0]["gem_id"] != "G3_AQLI":
                    errors.append(f"[Gate 3] Missing science_gems in hydrated lecture result: {lh['science_gems']}")

        # ===================================================================
        # Gate 4: Real Lecture Corpus & Orthographic/Stopword-Resilient Hybrid Search Gate
        # ===================================================================
        gate4_db = Path(tmpdir) / "gate4_real_lectures.sqlite"
        build_gate4_real_lecture_db(gate4_db)
        g4_stats = embed_sqlite_corpus(db_path=gate4_db, backend="deterministic-arabic-mps", dim=768, use_mps=True)
        if g4_stats["passages_embedded"] < 6:
            errors.append(f"[Gate 4] Unexpected embedded passage count in gate4_db: {g4_stats}")

        with HybridSearchEngine(db_path=gate4_db, backend="deterministic-arabic-mps") as g4_eng:
            # 4.A: مصطلحات الوضع والاستعمال والحمل والحقيقة والمجاز والمشترك والمتواطئ والكلي والجزئي
            q_wad_conc = g4_eng.search(
                query="ما الفرق بين الوضع والاستعمال والحمل في دلالة الالفاظ عند الاصوليين؟",
                mode="concept",
                top_k=3,
            )
            if not q_wad_conc or q_wad_conc[0]["passage_id"] != "D1_ADUDIYYA_WAD":
                errors.append(f"[Gate 4] Conceptual query on الوضع/الاستعمال/الحمل failed: {q_wad_conc[:1]}")

            q_mushtarak = g4_eng.search(
                query="كيف نفرق بين المشترك اللفظي والمتواطئ والكلي والجزئي ومتى يتوقف في المجمل؟",
                mode="hybrid",
                top_k=3,
            )
            if not q_mushtarak or q_mushtarak[0]["passage_id"] != "D2_SARIRI_MUSHTARAK":
                errors.append(f"[Gate 4] Query on المشترك/المتواطئ/الكلي/الجزئي failed: {q_mushtarak[:1]}")

            # 4.B: صمود FTS5 أمام اختلاف الهمزات والتاء المربوطة والياء وأدوات الاستفهام القالبية
            fts_resilience_cases = [
                ("هل يجوز الحلف بالاباء وما حكمه؟", "D4_DEDEW_HALF_ABAA"),
                ("ما حكم الصدقه في علاج المرضى؟", "D5_DEDEW_SADAQAH"),
                ("مساله خلق القران والكلام النفسي", "D3_DEDEW_KALAM"),
                ("حجيه الاجماع في اصول الفقه", "D2_SARIRI_MUSHTARAK"),
                ("ما حكم النذر المعلق علي شرط وهل يجب الوفاء به؟", "D6_DEDEW_NADHR"),
            ]
            for fts_q, expected_pid in fts_resilience_cases:
                fts_hits = g4_eng.search(query=fts_q, mode="fts", top_k=3)
                if not fts_hits or fts_hits[0]["passage_id"] != expected_pid or fts_hits[0]["score_fts"] <= 0.0:
                    errors.append(
                        f"[Gate 4] Orthographic/Stopword FTS5 failed for '{fts_q}': "
                        f"expected {expected_pid}, got {[h['passage_id'] for h in fts_hits]}"
                    )

            # 4.C: مرونة الفلترة العلائقية بالأعلام (--person بألقاب أو بدونها وبصيغ إعراب الكنى) والأماكن والآيات
            flex_entity_cases = [
                ("person=الترمذي", dict(person="الترمذي"), {"D5_DEDEW_SADAQAH"}),
                ("person=الإمام الترمذي", dict(person="الإمام الترمذي"), {"D5_DEDEW_SADAQAH"}),
                ("person=أبو هريرة", dict(person="أبو هريرة"), {"D4_DEDEW_HALF_ABAA"}),
                ("person=أبا هريرة", dict(person="أبا هريرة"), {"D4_DEDEW_HALF_ABAA"}),
                ("person=أبي هريرة رضي الله عنه", dict(person="أبي هريرة رضي الله عنه"), {"D4_DEDEW_HALF_ABAA"}),
                ("person=شيخ الإسلام ابن تيمية", dict(person="شيخ الإسلام ابن تيمية"), {"D3_DEDEW_KALAM"}),
                ("person=الشنقيطي", dict(person="الشنقيطي"), {"D1_ADUDIYYA_WAD"}),
                ("place=مكة المكرمة", dict(place="مكة المكرمة"), {"D4_DEDEW_HALF_ABAA"}),
                ("ayah=نوح:10", dict(ayah="نوح:10"), {"D5_DEDEW_SADAQAH"}),
                ("ayah=٧١:١٠", dict(ayah="٧١:١٠"), {"D5_DEDEW_SADAQAH"}),
                ("ayah=البقرة:255", dict(ayah="البقرة:255"), {"D3_DEDEW_KALAM"}),
            ]
            for label, flt_kwargs, expected_set in flex_entity_cases:
                got_pids = g4_eng.resolve_candidate_passage_ids(**flt_kwargs)
                if not expected_set.issubset(got_pids):
                    errors.append(f"[Gate 4] Flexible entity filter ({label}) failed: expected {expected_set}, got {got_pids}")

        # 4.D: فحص مباشر على قاعدة البيانات الإنتاجية الحقيقية (/tmp/real_e2e_test/orch_dedew_v2/...) إن وجدت
        real_prod_db = Path("/tmp/real_e2e_test/orch_dedew_v2/dedew/04_knowledge_db/dedew_objects.sqlite")
        if real_prod_db.exists():
            with HybridSearchEngine(db_path=real_prod_db, backend="deterministic-arabic-mps") as prod_eng:
                prod_checks = [
                    ("هل يجوز الحلف بالاباء وما حكمه؟", "fts", {"dedew__s029_006:P6", "dedew__s029_006:P10"}),
                    ("ما حكم الصدقه في علاج المرضى؟", "fts", {"dedew__s029_006:P8", "dedew__s029_006:P12"}),
                    ("ما حكم النذر المعلق على شرط وهل يجب الوفاء به مع الكراهة؟", "concept", {"dedew__s029_006:P17"}),
                    ("حكم التبرك بآثار الصالحين وذرية النبي", "concept", {"dedew__s029_006:P19"}),
                    ("حكم التوسل بجاه النبي أو بغيره من الصالحين", "concept", {"dedew__s029_006:P29"}),
                    ("استوي علي العرش", "fts", {"dedew__s029_004:P11"}),
                ]
                for pq, pmode, exp_pids in prod_checks:
                    pres = prod_eng.search(query=pq, mode=pmode, top_k=3)
                    if not pres or pres[0]["passage_id"] not in exp_pids:
                        errors.append(
                            f"[Gate 4 Live DB] Query '{pq}' ({pmode}) returned "
                            f"{[x['passage_id'] for x in pres[:2]]}, expected top-1 in {exp_pids}"
                        )
                if not prod_eng.resolve_candidate_passage_ids(person="الإمام الترمذي"):
                    errors.append("[Gate 4 Live DB] person='الإمام الترمذي' returned 0 on dedew_objects.sqlite")
                if not prod_eng.resolve_candidate_passage_ids(place="مكة المكرمة"):
                    errors.append("[Gate 4 Live DB] place='مكة المكرمة' returned 0 on dedew_objects.sqlite")
                if not prod_eng.resolve_candidate_passage_ids(ayah="البقرة:255"):
                    errors.append("[Gate 4 Live DB] ayah='البقرة:255' returned 0 on dedew_objects.sqlite")

        # ===================================================================
        # تكامل عابر للمهارات مع build_objects_sqlite.py في turath-deep-indexing
        # ===================================================================
        deep_idx_scripts = SCRIPT_DIR.parent.parent / "turath-deep-indexing" / "scripts"
        if (deep_idx_scripts / "build_objects_sqlite.py").exists() and (deep_idx_scripts / "test_objects_sqlite_gates.py").exists():
            if str(deep_idx_scripts) not in sys.path:
                sys.path.insert(0, str(deep_idx_scripts))
            import build_objects_sqlite as bos  # type: ignore
            import merge_round as mr  # type: ignore
            import test_objects_sqlite_gates as tosg  # type: ignore
            import ytb_to_usdb_intake as yti  # type: ignore

            integ_dir = Path(tmpdir) / "integ_usdb"
            integ_dir.mkdir(parents=True, exist_ok=True)
            work_dir, series_dir = tosg.build_realistic_fixture_data(integ_dir)
            books_out, _ = mr.audit_and_merge_round(round_num=4, work_dir=work_dir)
            (work_dir / "round4_9_books_deep.json").write_text(
                json.dumps(books_out, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            yti.intake_series(series_dir=series_dir, out_dir=work_dir)
            real_db = work_dir / "objects.sqlite"
            bos.build_objects_sqlite(db_path=real_db, work_dir=work_dir)

            integ_stats = embed_sqlite_corpus(db_path=real_db, backend="deterministic-arabic-mps", dim=768)
            if integ_stats["passages_embedded"] < 4 or integ_stats["gems_embedded"] < 4:
                errors.append(f"[Cross-Skill Gate] Unexpected counts on real objects.sqlite: {integ_stats}")

            with HybridSearchEngine(db_path=real_db, backend="deterministic-arabic-mps") as real_eng:
                # القعنبي راوٍ في السند فقط -> يجب أن يعيد 0 في طبقة المتن
                qaanabi_matn = real_eng.search(query="الطهارة", person="القعنبي", person_layer="matn")
                if qaanabi_matn:
                    errors.append(f"[Cross-Skill Gate] Isnad narrator القعنبي leaked into matn search: {qaanabi_matn}")
                # استرجاع شروح فقرة المتن AKH:1 عبر الكتب والدروس الصوتية معاً
                akh1_hits = real_eng.search(query="تصحيح إيمانه ومعرفة فرض عينه", matn_clause="AKH:1", top_k=5)
                if len(akh1_hits) < 2:
                    errors.append(f"[Cross-Skill Gate] Expected >=2 passages for matn_clause='AKH:1', got {len(akh1_hits)}")

    if errors:
        print(f"FAIL ({len(errors)} errors):")
        for err in errors:
            print(f"  - {err}")
        return 1

    print(
        "Gate 1 (Dual Text Hygiene & L2-Normalized float32 Vectors): OK\n"
        "Gate 2 (Dual Semantic Retrieval — Matn vs Concept): OK\n"
        "Gate 3 (Hybrid FTS5 + Vector + Entity Filtering & Isnad Isolation): OK\n"
        "Gate 4 (Real Lecture Corpus & Orthographic/Stopword-Resilient Hybrid Search): OK\n"
        "PASS (0 errors)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(run_quality_gates())
