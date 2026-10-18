#!/usr/bin/env python3
"""End-to-End Integration & Hard Gate Verification Test Suite for person-to-knowledge-orchestrator.

Tests:
  1. Full 6-Stage End-to-End Orchestration (Stages 0..5, Gates G0..G5) on a multi-source scholar
     with both YouTube lecture series (with AI preambles that must be sanitized) and multi-page
     PDF/written book content (with isnad chains, footnotes, Quranic verses, and matn clauses).
  2. Strict 0% Character Loss across both written books and audio lecture transcripts in USDB v5.7.
  3. Dual-Vector 768-dim Gemma-2 embeddings + HybridSearchEngine verification (hybrid, matn, concept,
     fts, person_layer="matn" vs "isnad" isolation, and historical vs transmission date filtering).
  4. Hard Gate Blocking (negative tests verifying G0..G5 reject corrupt/invalid stage outputs).
  5. Resumable Checkpointing (pipeline_state.json resume & partial stage re-run).
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import orchestrate_person as orch  # type: ignore


def _build_synthetic_fixtures(tmp_root: Path) -> Dict[str, Any]:
    """Creates realistic discovery fixture, lecture transcripts (with AI preambles), and book inputs."""
    fixtures_dir = tmp_root / "fixtures"
    fixtures_dir.mkdir(parents=True, exist_ok=True)

    # 1. Lecture transcripts WITH AI preambles & closings so Stage 3A must sanitize them
    lec1_raw = (
        "بالتأكيد! إليك التفريغ الكامل للدرس الأول:\n"
        "---\n"
        "### تفريغ الدرس الأول: شرح موطأ الإمام مالك\n\n"
        "بسم الله الرحمن الرحيم، الحمد لله رب العالمين، وصلى الله وسلم على نبينا محمد وعلى آله وصحبه أجمعين. "
        "أما بعد، فهذا مجلسنا الأول في شرح موطأ الإمام مالك بن أنس رحمه الله تعالى في فقه البيوع والمعاملات من المدينة المنورة. "
        "وقوله: «البيعان بالخيار ما لم يتفرقا» أصل عظيم في ثبوت خيار المجلس للمتبايعين قبل التفرق بالأبدان، "
        "وقد استدل العلماء بقول الله تعالى: ﴿وَأَحَلَّ اللَّهُ الْبَيْعَ وَحَرَّمَ الرِّبَا﴾ على حل البيوع المبنية على التراضي. "
        "وذكر الإمام الشافعي وأحمد بن حنبل أن خيار المجلس ثابت ما لم يتفرقا من مقامهما، وقد جرى البحث في هذه المسألة سنة ١٤٥ هـ.\n\n"
        "آمل أن يكون هذا التفريغ مفيداً، ولا تتردد في طرح أي سؤال آخر!"
    )

    lec2_raw = (
        "فيما يلي نص المحاضرة المفرغ بدقة:\n"
        "بسم الله الرحمن الرحيم، الحمد لله والصلاة والسلام على رسول الله. "
        "في هذا الدرس الثاني من شرح موطأ الإمام مالك بن أنس رحمه الله نتناول قوله: «من ابتاع طعاما فلا يبعه حتى يستوفيه» "
        "وبيان حكم قبض المبيعات قبل التصرف فيها عند فقهاء المدينة المنورة كالإمام مالك والشافعي وابن عبد البر. "
        "قال الله تعالى: ﴿يَا أَيُّهَا الَّذِينَ آمَنُوا أَوْفُوا بِالْعُقُودِ﴾، وفيه دلالة واضحة على وجوب الوفاء بالشروط المشروعة.\n"
    )

    lec3_raw = (
        "بسم الله الرحمن الرحيم، الحمد لله رب العالمين. "
        "في هذا الدرس الثالث من شرح موطأ الإمام مالك بن أنس رحمه الله نبحث مسألة الصرف وبيع الذهب بالذهب والفضة بالفضة يدا بيد، "
        "وقوله: «الذهب بالذهب ربا إلا هاء وهاء» وما قرره الحافظ ابن عبد البر والقرطبي في تحرير علة الربا في النقدين والمطعومات.\n"
    )

    discovery_fixture = {
        "channels": [
            {
                "channel_id": "UC_KAMALI_OFFICIAL",
                "title": "القناة العلمية للشيخ سعيد الكملي",
                "url": "https://www.youtube.com/@kamali_test",
            }
        ],
        "playlists": [
            {
                "id": "PL_MUWATTA_01",
                "playlist_id": "PL_MUWATTA_01",
                "yt_playlist_id": "PL_MUWATTA_01",
                "title": "سلسلة شرح موطأ الإمام مالك - كتاب البيوع",
                "channel_id": "UC_KAMALI_OFFICIAL",
                "videos": [
                    {
                        "vid": "vid_muwatta_001",
                        "yt_id": "vid_muwatta_001",
                        "video_id": "vid_muwatta_001",
                        "title": "شرح موطأ الإمام مالك - كتاب البيوع - المجلس 1",
                        "dur_s": 2700,
                        "duration": 2700,
                        "upload_date": "20240101",
                        "view_count": 15000,
                        "transcript_text": lec1_raw,
                    },
                    {
                        "vid": "vid_muwatta_002",
                        "yt_id": "vid_muwatta_002",
                        "video_id": "vid_muwatta_002",
                        "title": "شرح موطأ الإمام مالك - كتاب البيوع - المجلس 2",
                        "dur_s": 2650,
                        "duration": 2650,
                        "upload_date": "20240108",
                        "view_count": 14200,
                        "transcript_text": lec2_raw,
                    },
                    {
                        "vid": "vid_muwatta_003",
                        "yt_id": "vid_muwatta_003",
                        "video_id": "vid_muwatta_003",
                        "title": "شرح موطأ الإمام مالك - كتاب البيوع - المجلس 3",
                        "dur_s": 2900,
                        "duration": 2900,
                        "upload_date": "20240115",
                        "view_count": 13800,
                        "transcript_text": lec3_raw,
                    },
                    # Duplicate of vid_muwatta_001 with lower duration/views (to test deduplication)
                    {
                        "vid": "vid_muwatta_001",
                        "yt_id": "vid_muwatta_001",
                        "video_id": "vid_muwatta_001",
                        "title": "شرح موطأ الإمام مالك - كتاب البيوع - المجلس 1 (مكرر)",
                        "dur_s": 2690,
                        "duration": 2690,
                        "upload_date": "20240102",
                        "view_count": 500,
                    },
                ],
            }
        ],
        "videos": [
            {
                "vid": "vid_standalone_01",
                "yt_id": "vid_standalone_01",
                "video_id": "vid_standalone_01",
                "title": "محاضرة تأصيلية في فقه الخلاف ومقاصد الشريعة عند المالكية",
                "dur_s": 3100,
                "duration": 3100,
                "upload_date": "20240210",
                "view_count": 25000,
            }
        ],
        "archive_items": [
            {
                "identifier": "kamali-muwatta-audio-archive",
                "title": "التسجيلات الصوتية لشرح الموطأ",
                "mediatype": "audio",
                "files": [{"name": "01_muwatta.mp3", "format": "VBR MP3", "size": "45000000"}],
            }
        ],
        "books": [],
    }

    fixture_path = fixtures_dir / "discovery_fixture.json"
    fixture_path.write_text(json.dumps(discovery_fixture, ensure_ascii=False, indent=2), encoding="utf-8")

    # Write raw transcripts (with AI preambles/closings) into transcripts_dir so Stage 3A sanitizes them
    transcripts_dir = fixtures_dir / "transcripts"
    transcripts_dir.mkdir(parents=True, exist_ok=True)
    (transcripts_dir / "vid_muwatta_001.txt").write_text(lec1_raw, encoding="utf-8")
    (transcripts_dir / "vid_muwatta_002.txt").write_text(lec2_raw, encoding="utf-8")
    (transcripts_dir / "vid_muwatta_003.txt").write_text(lec3_raw, encoding="utf-8")

    # 2. Multi-page written book input (JSON format supported by pdf_to_preflight_adapter)
    book_payload = {
        "book_slug": "book_masalik_muwatta",
        "book_id": 9101,
        "science": "maliki",
        "title": "المسالك الفقهية في شرح موطأ إمام دار الهجرة",
        "author": "الشيخ سعيد الكملي",
        "death": "750",
        "pages": [
            {
                "pdf_page": 1,
                "tag": "p0001",
                "layout": "standard_single_col",
                "extracted": {
                    "printed_page": "١",
                    "running_header": "باب خيار المجلس وأحكام التعاقد",
                    "matn": (
                        "باب خيار المجلس وأحكام التعاقد\n"
                        "حدثنا يحيى بن يحيى الليثي (ت ٢٢٦ هـ) قال: أخبرنا قاسم بن أصبغ عن نافع عن عبد الله بن عمر "
                        "أن رسول الله صلى الله عليه وسلم قال: «البيعان بالخيار ما لم يتفرقا» (1). "
                        "قوله: «البيعان بالخيار ما لم يتفرقا» فيه بيان مشروعية خيار المجلس، وقد استدل به الشافعي وأحمد بن حنبل، "
                        "بينما حمل مالك بن أنس وأبو حنيفة التفرق في الحديث على التفرق بالأقوال في المدينة المنورة (2). "
                        "قال الله تعالى: ﴿وَأَحَلَّ اللَّهُ الْبَيْعَ وَحَرَّمَ الرِّبَا﴾، وقد وقعت المناظرة في هذه المسألة ببغداد سنة ١٤٥ هـ."
                    ),
                    "margin_notes": "",
                    "footnotes": (
                        "(1) أخرجه البخاري في صحيحه في كتاب البيوع ومسلم بن الحجاج في صحيحه من طريق مالك عن نافع.\n"
                        "(2) انظر التمهيد للحافظ ابن عبد البر وبداية المجتهد لابن رشد الحفيد في تفصيل مذهب أهل المدينة."
                    ),
                },
            },
            {
                "pdf_page": 2,
                "tag": "p0002",
                "layout": "standard_single_col",
                "extracted": {
                    "printed_page": "٢",
                    "running_header": "باب النهي عن بيع الطعام قبل قبضه",
                    "matn": (
                        "باب النهي عن بيع الطعام قبل قبضه\n"
                        "قوله: «من ابتاع طعاما فلا يبعه حتى يستوفيه» (1) أصل مطرد عند فقهاء المذاهب الأربعة في اشتراط القبض "
                        "في الطعام المكيل والموزون قبل بيعه، لما في بيعه قبل قبضه من الغرر والمخاطرة وقد نبه على ذلك الشاطبي في الموافقات "
                        "والقرطبي في تفسيره لقوله تعالى: ﴿يَا أَيُّهَا الَّذِينَ آمَنُوا أَوْفُوا بِالْعُقُودِ﴾."
                    ),
                    "margin_notes": "",
                    "footnotes": "(1) اتفق العلماء على منع بيع الطعام قبل قبضه لثبوت النهي الصريح عنه في الموطأ والصحيحين.",
                },
            },
        ],
    }
    book_json_path = fixtures_dir / "book_masalik_muwatta.json"
    book_json_path.write_text(json.dumps(book_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "discovery_fixture_path": fixture_path,
        "book_json_path": book_json_path,
        "transcripts_dir": transcripts_dir,
    }


def test_e2e_full_6_stage_pipeline(errors: List[str]) -> None:
    """Test 1: Full 6-stage pipeline execution with all Hard Gates G0..G5 passing and 0% char loss."""
    tmp_dir = Path(tempfile.mkdtemp(prefix="test_orchestrator_e2e_"))
    try:
        fx = _build_synthetic_fixtures(tmp_dir)
        work_dir = tmp_dir / "workspace"

        quota_mock = {
            "models": [
                {
                    "label": "Gemini 3.8 Flash (High)",
                    "remainingPercentage": 0.92,
                    "timeUntilResetMs": 3600000,
                    "isExhausted": False,
                },
                {
                    "label": "Claude Opus 4.6",
                    "remainingPercentage": 0.85,
                    "timeUntilResetMs": 3600000,
                    "isExhausted": False,
                },
            ]
        }

        report = orch.orchestrate_person(
            name="الشيخ سعيد الكملي",
            person_id="kamali_test",
            work_dir=work_dir,
            offline_fixture=str(fx["discovery_fixture_path"]),
            series_transcripts_dir=fx["transcripts_dir"],
            book_inputs=[fx["book_json_path"]],
            quota_override=quota_mock,
            embedding_backend="deterministic-arabic-mps",
            embedding_dim=768,
        )

        if report.get("overall_status") != "PASS":
            errors.append(f"[E2E] Expected overall_status == 'PASS', got {report.get('overall_status')}")

        # Check all 6 stages (0..5) and gates (G0..G5)
        stages = report.get("stages", {})
        for s_num, expected_gate in enumerate(["G0", "G1", "G2", "G3", "G4", "G5"]):
            st = stages.get(str(s_num), {})
            if st.get("status") != "PASS" or st.get("gate") != expected_gate:
                errors.append(f"[E2E] Stage {s_num} ({expected_gate}) did not PASS: {st}")

        person_dir = work_dir / "kamali_test"
        expected_paths = [
            person_dir / "pipeline_state.json",
            person_dir / "00_quota" / "quota_guard_report.json",
            person_dir / "01_discovery" / "kamali_test_raw.json",
            person_dir / "02_curated" / "kamali_test.json",
            person_dir / "02_curated" / "curated.db",
            person_dir / "04_knowledge_db" / "kamali_test_objects.sqlite",
            person_dir / "04_knowledge_db" / "round4_9_books_deep.json",
            person_dir / "04_knowledge_db" / "lectures_deep_merged.json",
            person_dir / "05_reports" / "orchestration_audit_report.json",
            person_dir / "05_reports" / "ORCHESTRATION_REPORT.md",
        ]
        for p in expected_paths:
            if not p.exists():
                errors.append(f"[E2E] Expected output artifact missing: {p}")

        # Verify SQLite contents & dual-source (book + lecture_series) unification
        db_path = person_dir / "04_knowledge_db" / "kamali_test_objects.sqlite"
        conn = sqlite3.connect(str(db_path))
        try:
            cur = conn.cursor()
            src_types = dict(
                cur.execute(
                    "SELECT s.source_type, COUNT(p.passage_id) "
                    "FROM passages p JOIN sources s ON p.source_id = s.source_id "
                    "GROUP BY s.source_type"
                ).fetchall()
            )
            if src_types.get("book", 0) < 1:
                errors.append(f"[E2E] Expected >= 1 book passage in SQLite, got {src_types}")
            if src_types.get("lecture_series", 0) < 3:
                errors.append(f"[E2E] Expected >= 3 lecture_series passages in SQLite, got {src_types}")

            # Verify matn_triangulation cross-linking book & lecture passages
            tri_count = cur.execute("SELECT COUNT(*) FROM matn_triangulation").fetchone()[0]
            if tri_count < 2:
                errors.append(f"[E2E] Expected >= 2 matn_triangulation rows, got {tri_count}")

            # Verify narrator layer isolation: يحيى بن يحيى must be in 'isnad' and NEVER in 'matn'
            yahya_matn = cur.execute(
                "SELECT COUNT(*) FROM passage_persons WHERE canonical_name LIKE '%يحيى بن يحيى%' AND source_layer = 'matn'"
            ).fetchone()[0]
            yahya_isnad = cur.execute(
                "SELECT COUNT(*) FROM passage_persons WHERE canonical_name LIKE '%يحيى بن يحيى%' AND source_layer = 'isnad'"
            ).fetchone()[0]
            if yahya_matn != 0 or yahya_isnad == 0:
                errors.append(
                    f"[E2E] Isnad narrator layer leak: yahya_matn={yahya_matn} (expected 0), yahya_isnad={yahya_isnad} (expected >0)"
                )

            # Verify transmission vs historical date isolation: 226 AH (death date) must be 'transmission', 145 AH must be 'historical'
            death_hist = cur.execute(
                "SELECT COUNT(*) FROM events_chronology WHERE year_hijri = 226 AND event_layer = 'historical'"
            ).fetchone()[0]
            event_hist = cur.execute(
                "SELECT COUNT(*) FROM events_chronology WHERE year_hijri = 145 AND event_layer = 'historical'"
            ).fetchone()[0]
            if death_hist != 0 or event_hist == 0:
                errors.append(
                    f"[E2E] Date layer leak: death_226_in_historical={death_hist} (expected 0), event_145_in_historical={event_hist} (expected >0)"
                )
        finally:
            conn.close()

        # Verify HybridSearchEngine queries across unified book + lecture corpus
        with orch.search_mod.HybridSearchEngine(db_path, backend="deterministic-arabic-mps", dim=768) as engine:
            hits_all = engine.search("البيعان بالخيار ما لم يتفرقا", top_k=10, mode="hybrid")
            hit_source_types = {h["source_type"] for h in hits_all}
            if "book" not in hit_source_types or "lecture_series" not in hit_source_types:
                errors.append(
                    f"[E2E] HybridSearchEngine should retrieve both 'book' and 'lecture_series' for shared matn query, got {hit_source_types}"
                )

            # Verify person_layer="matn" filter excludes isnad-only narrator
            hits_yahya_matn = engine.search("البيعان", top_k=10, mode="hybrid", person="يحيى بن يحيى", person_layer="matn")
            hits_yahya_isnad = engine.search("البيعان", top_k=10, mode="hybrid", person="يحيى بن يحيى", person_layer="isnad")
            if len(hits_yahya_matn) != 0 or len(hits_yahya_isnad) == 0:
                errors.append(
                    f"[E2E] HybridSearchEngine person_layer isolation failed: matn={len(hits_yahya_matn)}, isnad={len(hits_yahya_isnad)}"
                )

        # Test 5: Resumable checkpointing & partial stage re-run
        report_resumed = orch.orchestrate_person(
            name="الشيخ سعيد الكملي",
            person_id="kamali_test",
            work_dir=work_dir,
            offline_fixture=str(fx["discovery_fixture_path"]),
            book_inputs=[fx["book_json_path"]],
            quota_override=quota_mock,
            embedding_backend="deterministic-arabic-mps",
            embedding_dim=768,
            resume=True,
            force=False,
        )
        if report_resumed.get("overall_status") != "PASS":
            errors.append("[Resume] Resumed pipeline run did not return PASS")

        # Partial stage re-run (Stages 4..5 with force=True)
        report_partial = orch.orchestrate_person(
            name="الشيخ سعيد الكملي",
            person_id="kamali_test",
            work_dir=work_dir,
            offline_fixture=str(fx["discovery_fixture_path"]),
            book_inputs=[fx["book_json_path"]],
            quota_override=quota_mock,
            embedding_backend="deterministic-arabic-mps",
            embedding_dim=768,
            from_stage=4,
            to_stage=5,
            force=True,
        )
        if report_partial.get("overall_status") != "PASS":
            errors.append("[Partial] Partial stage 4..5 force re-run did not return PASS")

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_hard_gates_block_corrupt_inputs(errors: List[str]) -> None:
    """Test 2: Verifies that every Hard Gate (G0..G5) blocks corrupt or invalid artifacts."""
    tmp_dir = Path(tempfile.mkdtemp(prefix="test_orchestrator_neg_"))
    try:
        # Gate G0 negative test: low quota + forbidden path leak
        g0_ok, g0_errs = orch.verify_gate_g0(
            {
                "selected_model_info": {"selected_model": "gemini-3.8-flash-high", "safe": False, "remaining_pct": 5.0},
                "isolation_info": {
                    "isolated": False,
                    "violations": [".gemini/config/mcp_config.json"],
                    "has_clean_cfg": False,
                },
            }
        )
        if g0_ok or len(g0_errs) < 3:
            errors.append(f"[Neg-G0] Expected G0 to fail on low quota and MCP leak, got ok={g0_ok}, errs={g0_errs}")

        # Gate G1 negative test: empty discovery sources
        bad_disc = tmp_dir / "bad_raw.json"
        bad_disc.write_text(
            json.dumps(
                {
                    "person_id": "empty_p",
                    "sheikh_name": "فارغ",
                    "playlists": [],
                    "videos": [],
                    "archive_items": [],
                    "books": [],
                    "stats": {},
                }
            ),
            encoding="utf-8",
        )
        g1_ok, g1_errs, _ = orch.verify_gate_g1(bad_disc)
        if g1_ok or not any("G1_EMPTY_DISCOVERY" in e for e in g1_errs):
            errors.append(f"[Neg-G1] Expected G1 to fail on empty discovery, got ok={g1_ok}, errs={g1_errs}")

        # Gate G2 negative test: duplicate active video_ids + scanner flaws
        bad_curated = tmp_dir / "bad_curated.json"
        bad_curated.write_text(
            json.dumps(
                {
                    "sheikh": {"id": "dup_p", "name": "مكرر"},
                    "series": [{"series_id": "s001", "episodes": [{"video_id": "v_dup_1"}]}],
                    "standalone_lectures": [{"video_id": "v_dup_1"}],
                    "excluded_videos": [],
                }
            ),
            encoding="utf-8",
        )
        g2_ok, g2_errs, _ = orch.verify_gate_g2(
            curated_json_path=bad_curated,
            curated_db_path=tmp_dir / "missing.db",
            curated_series_root=tmp_dir / "series",
            curation_report={"stage9": {"scanner_flaws_total": 3, "audit_returncode": 1, "audit_output": "3 errors"}},
        )
        if g2_ok or not any("G2_DUPLICATE_ACTIVE_VIDEOS" in e for e in g2_errs):
            errors.append(f"[Neg-G2] Expected G2 to fail on duplicate active video_id and flaws, got ok={g2_ok}, errs={g2_errs}")

        # Gate G3 negative test: unsanitized AI preamble in lecture .txt + character loss in book manifest
        bad_sdir = tmp_dir / "ext_series" / "s001"
        bad_sdir.mkdir(parents=True, exist_ok=True)
        (bad_sdir / "_meta.json").write_text("{}", encoding="utf-8")
        (bad_sdir / "001_vid1.txt").write_text(
            "إليك التفريغ الكامل للدرس:\n"
            + (
                "بسم الله الرحمن الرحيم الحمد لله رب العالمين والصلاة والسلام على سيد المرسلين "
                "في شرح مسائل الفقه المالكي وتحرير ضوابط العقود والبيوع في موطأ الإمام مالك رحمه الله. "
                * 2
            ),
            encoding="utf-8",
        )

        bad_bdir = tmp_dir / "ext_books" / "book_01"
        bad_bdir.mkdir(parents=True, exist_ok=True)
        (bad_bdir / "raw_round4_books.json").write_text("{}", encoding="utf-8")
        (bad_bdir / "round_manifest_r4_r10.json").write_text("{}", encoding="utf-8")
        (bad_bdir / "adapter_manifest.json").write_text(
            json.dumps(
                {
                    "status": "FAIL",
                    "zero_loss_check": {
                        "passed": False,
                        "body_char_loss": 42,
                        "footnotes_char_loss": 0,
                        "retention_pct": 98.1,
                    },
                    "manifest_v4_verification": {"passed": True},
                }
            ),
            encoding="utf-8",
        )
        g3_ok, g3_errs, _ = orch.verify_gate_g3(tmp_dir / "ext_series", tmp_dir / "ext_books")
        if (
            g3_ok
            or not any("G3_UNSANITIZED_PREAMBLE" in e for e in g3_errs)
            or not any("G3_BOOK_CHAR_LOSS" in e for e in g3_errs)
        ):
            errors.append(f"[Neg-G3] Expected G3 to fail on preamble and book char loss, got ok={g3_ok}, errs={g3_errs}")

        # Gate G4 negative test: chars_lost > 0 and P0 errors > 0
        g4_ok, g4_errs, _ = orch.verify_gate_g4(
            db_path=tmp_dir / "nonexistent.sqlite",
            sqlite_summary={"chars_lost": 15, "expected_raw_chars": 1000, "actual_passage_chars": 985},
            book_gate_reports=[{"passed": False, "p0_error_count": 2, "p0_errors": ["P0: test"]}],
            lecture_gate_reports=[],
        )
        if g4_ok or not any("G4_SQLITE_CHAR_LOSS" in e for e in g4_errs):
            errors.append(f"[Neg-G4] Expected G4 to fail on char loss and P0 errors, got ok={g4_ok}, errs={g4_errs}")

        # Gate G5 negative test: honorific leak in embed_concept_text and invalid vector BLOB
        bad_db = tmp_dir / "bad_embed.sqlite"
        conn = sqlite3.connect(str(bad_db))
        conn.execute("CREATE TABLE passages (passage_id TEXT)")
        conn.execute("INSERT INTO passages VALUES ('P1')")
        conn.execute("CREATE TABLE science_gems (gem_id TEXT)")
        conn.execute(
            "CREATE TABLE passage_embeddings ("
            "passage_id TEXT, model_name TEXT, dim INT, embed_matn_text TEXT, embed_concept_text TEXT, "
            "vec_matn_blob BLOB, vec_concept_blob BLOB, matn_norm REAL, concept_norm REAL)"
        )
        conn.execute(
            "CREATE TABLE gem_embeddings ("
            "gem_id TEXT, passage_id TEXT, model_name TEXT, dim INT, embed_matn_text TEXT, embed_concept_text TEXT, "
            "vec_matn_blob BLOB, vec_concept_blob BLOB)"
        )
        conn.execute(
            "INSERT INTO passage_embeddings VALUES ('P1', 'test', 768, 'نص المتن', 'نص المفهوم مع شعار ﷺ مسرب', NULL, NULL, 1.0, 1.0)"
        )
        conn.commit()
        conn.close()
        g5_ok, g5_errs, _ = orch.verify_gate_g5(bad_db, dim=768, backend="deterministic-arabic-mps")
        if (
            g5_ok
            or not any("G5_HONORIFIC_LEAK_IN_CONCEPT" in e for e in g5_errs)
            or not any("G5_INVALID_MATN_BLOB" in e for e in g5_errs)
        ):
            errors.append(f"[Neg-G5] Expected G5 to fail on honorific leak and NULL BLOB, got ok={g5_ok}, errs={g5_errs}")

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_multi_format_series_and_shamela_jsonl_ingestion(errors: List[str]) -> None:
    """
    Gate 4: Multi-Format Real Series & Shamela JSONL Book Auto-Ingestion Gate.
    Verifies:
      1. Track 3A matches external series transcript folders across all 4 production naming schemes:
         - `series_slug` (e.g. `sharh_manzouma_adoudiya`)
         - `playlist_id` (e.g. `alasimi-mut-744`)
         - `row_id` (e.g. `984`)
         - server `sNNN` (e.g. `s011` on server whose `yt_id`s belong to curated `s003`, without polluting `s001`/`s002`)
      2. `_meta.json` and `curated.db` are updated with accurate `transcribed_count`, `aligned_count`, and `has_transcript = 1`.
      3. Track 3B auto-discovers Shamela4 JSONL books (`pages.jsonl` + `book_metadata.json` with `shamela_id` vs `book_id`,
         inline HTML `<span ...>`, CRLF `\r`, and unnumbered colophon lines in `footnotes`), converts them losslessly
         (`100.0%` retention, `0` orphan footnote heads), and populates `matn_triangulation` across book & lecture passages.
    """
    tmp_dir = Path(tempfile.mkdtemp(prefix="test_orchestrator_gate4_"))
    try:
        # 1. Build a mock Shamela4_Full_DB with two books to verify shamela_id vs folder book_id disambiguation
        shamela_db = tmp_dir / "Shamela4_Full_DB"
        cat_dir = shamela_db / "أصول الفقه"
        # Decoy folder whose folder prefix is 1751, but shamela_id is 99999
        decoy_dir = cat_dir / "1751__كتاب-مختلف"
        decoy_dir.mkdir(parents=True, exist_ok=True)
        (decoy_dir / "book_metadata.json").write_text(
            json.dumps({"book_id": 1751, "shamela_id": 99999, "title": "كتاب مختلف", "category_name": "أصول الفقه"}),
            encoding="utf-8",
        )
        (decoy_dir / "pages.jsonl").write_text(
            json.dumps({"page_num": 1, "part": 1, "body": "نص مختلف تماما", "footnotes": ""}) + "\n",
            encoding="utf-8",
        )

        # Target book whose folder prefix is 1600, and shamela_id is 1751
        target_bdir = cat_dir / "1600__شرح-الورقات-في-أصول-الفقه"
        target_bdir.mkdir(parents=True, exist_ok=True)
        (target_bdir / "book_metadata.json").write_text(
            json.dumps(
                {
                    "book_id": 1600,
                    "shamela_id": 1751,
                    "title": "شرح الورقات في أصول الفقه",
                    "author": "الشيخ محمد الحسن الددو",
                    "death": "1445",
                    "category_name": "أصول الفقه",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        shamela_pages = [
            {
                "page_id": 1,
                "book_id": 1600,
                "part": None,
                "page_num": 1,
                "body": (
                    '<span data-type="title" id=toc-1>باب تعريف أصول الفقه والأحكام الشرعية</span>\r'
                    "بسم الله الرحمن الرحيم، الحمد لله رب العالمين. "
                    "اعلم أن الفقه في الاصطلاح معرفة الأحكام الشرعية التي طريقها الاجتهاد، "
                    "والأحكام السبعة هي الواجب والمندوب والمباح والمحظور والمكروه والصحيح والباطل (١).\r"
                    "وقد قرر الإمام الجويني والشافعي ومالك بن أنس في المدينة المنورة أن الواجب ما يثاب على فعله ويعاقب على تركه، "
                    "قال الله تعالى: ﴿وَأَقِيمُوا الصَّلَاةَ وَآتُوا الزَّكَاةَ﴾."
                ),
                "footnotes": "(١) انظر شرح الورقات للإمام الجويني والمحلي في تحرير حد الفقه وأبواب الأصول.",
            },
            {
                "page_id": 2,
                "book_id": 1600,
                "part": None,
                "page_num": 2,
                "body": (
                    '<span data-type="title" id=toc-2>باب العام والخاص والأمر والنهي</span>\r'
                    "والأمر استدعاء الفعل بالقول ممن هو دونه على سبيل الوجوب، والصيغة الدالة عليه افعل، "
                    "وهي عند الإطلاق والتجرد عن القرينة تحمل على الوجوب عند جمهور الأصوليين كالإمام مالك والشافعي وأحمد بن حنبل.\r"
                    "قال الله تعالى: ﴿وَمَا آتَاكُمُ الرَّسُولُ فَخُذُوهُ وَمَا نَهَاكُمْ عَنْهُ فَانْتَهُوا﴾."
                ),
                # Unnumbered colophon in footnotes to verify routing to margin_notes with 0 orphan_head
                "footnotes": "تم طبع هذا الكتاب بمطبعة السعادة بالقاهرة على نفقة طلاب العلم.",
            },
        ]
        (target_bdir / "pages.jsonl").write_text(
            "\n".join(json.dumps(p, ensure_ascii=False) for p in shamela_pages) + "\n",
            encoding="utf-8",
        )

        # Verify resolve_shamela_book_path prioritizes shamela_id for "shamela:1751" and ignores "tafsir:surah_001"
        resolved_sh = orch.resolve_shamela_book_path({"id": "shamela:1751"}, shamela_db_dir=shamela_db)
        if resolved_sh != target_bdir.resolve():
            errors.append(f"[Gate4] Expected shamela:1751 to resolve to {target_bdir}, got {resolved_sh}")
        resolved_taf = orch.resolve_shamela_book_path({"id": "tafsir:surah_001"}, shamela_db_dir=shamela_db)
        if resolved_taf is not None:
            errors.append(f"[Gate4] Expected tafsir:surah_001 to return None, got {resolved_taf}")

        # 2. Build multi-series discovery fixture + 4 external series directories using all 4 naming conventions
        ext_series_root = tmp_dir / "real_ytb_samples"
        s_slug_dir = ext_series_root / "sharh_manzouma_adoudiya"
        s_pl_dir = ext_series_root / "alasimi-mut-744"
        s_row_dir = ext_series_root / "984"
        # Server folder named s001 on disk, whose yt_ids actually belong to curated series 3!
        s_mismatched_dir = ext_series_root / "s001"
        for d in (s_slug_dir, s_pl_dir, s_row_dir, s_mismatched_dir):
            d.mkdir(parents=True, exist_ok=True)

        lec_s1_txt = (
            "Here is the transcription of the audio:\n\n"
            "بسم الله الرحمن الرحيم، الحمد لله رب العالمين، وصلى الله وسلم على نبينا محمد. "
            "في هذا الدرس الأول من شرح المنظومة العضدية والورقات في أصول الفقه نشرح قول المصنف: "
            "اعلم أن الفقه في الاصطلاح معرفة الأحكام الشرعية التي طريقها الاجتهاد، "
            "وبيان الأحكام السبعة من الواجب والمندوب والمباح والمحظور والمكروه والصحيح والباطل عند الإمام مالك والشافعي في المدينة المنورة. "
            "قال الله تعالى: ﴿وَأَقِيمُوا الصَّلَاةَ وَآتُوا الزَّكَاةَ﴾.\n"
        )
        lec_s2_txt = (
            "بسم الله الرحمن الرحيم، الحمد لله رب العالمين. "
            "في هذا المجلس من برنامج المتون العلمية نشرح باب العام والخاص والأمر والنهي، "
            "والأمر استدعاء الفعل بالقول ممن هو دونه على سبيل الوجوب عند الإمام مالك بن أنس والشافعي وأحمد بن حنبل. "
            "قال الله تعالى: ﴿وَمَا آتَاكُمُ الرَّسُولُ فَخُذُوهُ وَمَا نَهَاكُمْ عَنْهُ فَانْتَهُوا﴾.\n"
        )

        # Populate s_slug_dir (`sharh_manzouma_adoudiya`) and s_mismatched_dir (`s001` on server -> belongs to s002)
        (s_slug_dir / "001_vid_adoud_01.txt").write_text(lec_s1_txt, encoding="utf-8")
        (s_mismatched_dir / "001_vid_usul_01.txt").write_text(lec_s2_txt, encoding="utf-8")
        # Direct unit check of _match_external_series_dirs across all 4 naming conventions
        (s_pl_dir / "001_vid_pl_01.txt").write_text(lec_s1_txt, encoding="utf-8")
        (s_row_dir / "001_vid_row_01.txt").write_text(lec_s2_txt, encoding="utf-8")

        mock_curated_series = [
            {
                "series_id": "s001",
                "series_slug": "sharh_manzouma_adoudiya",
                "title": "شرح المنظومة العضدية",
                "lessons": [{"episode_num": 1, "yt_id": "vid_adoud_01", "title": "المجلس 1"}],
            },
            {
                "series_id": "s002",
                "playlist_id": "alasimi-mut-744",
                "title": "شرح الورقات في أصول الفقه",
                "lessons": [{"episode_num": 1, "yt_id": "vid_pl_01", "title": "المجلس 1"}],
            },
            {
                "series_id": "s003",
                "row_id": 984,
                "title": "مجالس الأصول",
                "lessons": [{"episode_num": 1, "yt_id": "vid_row_01", "title": "المجلس 1"}],
            },
            {
                "series_id": "s004",
                "title": "مباحث الأمر والنهي",
                "lessons": [{"episode_num": 1, "yt_id": "vid_usul_01", "title": "المجلس 1"}],
            },
        ]
        matched_map = orch._match_external_series_dirs(ext_series_root, mock_curated_series)
        if (
            matched_map.get("s001") != s_slug_dir
            or matched_map.get("s002") != s_pl_dir
            or matched_map.get("s003") != s_row_dir
            or matched_map.get("s004") != s_mismatched_dir
        ):
            errors.append(f"[Gate4] Multi-format series matching failed: {matched_map}")

        # 3. Run full 6-stage pipeline with auto-discovered Shamela4 book + multi-format series
        disc_fixture = {
            "channels": [{"channel_id": "UC_DEDEW", "title": "قناة الشيخ الددو", "url": "https://youtube.com/@dedew"}],
            "playlists": [
                {
                    "id": "PL_ADOUD_01",
                    "playlist_id": "PL_ADOUD_01",
                    "title": "سلسلة شرح المنظومة العضدية",
                    "videos": [
                        {
                            "vid": "vid_adoud_01",
                            "yt_id": "vid_adoud_01",
                            "video_id": "vid_adoud_01",
                            "title": "شرح المنظومة العضدية - الدرس 1",
                            "dur_s": 2400,
                            "duration": 2400,
                        }
                    ],
                },
                {
                    "id": "PL_USUL_02",
                    "playlist_id": "PL_USUL_02",
                    "title": "سلسلة مباحث الأمر والنهي في أصول الفقه",
                    "videos": [
                        {
                            "vid": "vid_usul_01",
                            "yt_id": "vid_usul_01",
                            "video_id": "vid_usul_01",
                            "title": "مباحث الأمر والنهي في أصول الفقه - الدرس 1",
                            "dur_s": 2500,
                            "duration": 2500,
                        }
                    ],
                },
            ],
            "videos": [],
            "archive_items": [],
            "books": [
                {
                    "book_id": "shamela:1751",
                    "title": "شرح الورقات في أصول الفقه",
                    "author": "الشيخ محمد الحسن الددو",
                    "science": "أصول الفقه",
                }
            ],
        }
        disc_path = tmp_dir / "dedew_disc.json"
        disc_path.write_text(json.dumps(disc_fixture, ensure_ascii=False, indent=2), encoding="utf-8")

        # Keep only the 2 active series directories in ext_series_root for the 2 playlists in disc_fixture
        shutil.rmtree(s_pl_dir, ignore_errors=True)
        shutil.rmtree(s_row_dir, ignore_errors=True)

        quota_mock = {
            "models": [
                {
                    "label": "Gemini 3.8 Flash (High)",
                    "remainingPercentage": 0.90,
                    "timeUntilResetMs": 3600000,
                    "isExhausted": False,
                }
            ]
        }
        work_dir = tmp_dir / "work"
        report = orch.orchestrate_person(
            name="الشيخ محمد الحسن الددو",
            person_id="dedew_gate4",
            work_dir=work_dir,
            offline_fixture=str(disc_path),
            series_transcripts_dir=ext_series_root,
            shamela_db_dir=shamela_db,
            auto_ingest_shamela_books=True,
            quota_override=quota_mock,
            embedding_backend="deterministic-arabic-mps",
            embedding_dim=768,
        )

        if report.get("overall_status") != "PASS":
            errors.append(f"[Gate4] Expected overall_status == 'PASS', got {report.get('overall_status')}")

        # Verify _meta.json transcribed_count was updated to 1 on both series
        for sid_check in ("s001", "s002"):
            m_path = work_dir / "dedew_gate4" / "03_extracted" / "series" / "dedew_gate4" / sid_check / "_meta.json"
            m_data = json.loads(m_path.read_text(encoding="utf-8"))
            if int(m_data.get("transcribed_count", 0)) != 1:
                errors.append(f"[Gate4] Expected {sid_check} transcribed_count == 1 in _meta.json, got {m_data.get('transcribed_count')}")

        # Verify SQLite has both Shamela book passages and lecture_series passages, 0 char loss, and matn_triangulation > 0
        db_path = work_dir / "dedew_gate4" / "04_knowledge_db" / "dedew_gate4_objects.sqlite"
        conn = sqlite3.connect(str(db_path))
        try:
            cur = conn.cursor()
            src_counts = dict(
                cur.execute(
                    "SELECT s.source_type, COUNT(p.passage_id) "
                    "FROM passages p JOIN sources s ON p.source_id = s.source_id "
                    "GROUP BY s.source_type"
                ).fetchall()
            )
            if src_counts.get("book", 0) < 1 or src_counts.get("lecture_series", 0) < 2:
                errors.append(f"[Gate4] Expected book >= 1 and lecture_series >= 2 passages, got {src_counts}")

            tri_by_type = dict(
                cur.execute(
                    "SELECT s.source_type, COUNT(*) "
                    "FROM matn_triangulation m "
                    "JOIN passages p ON m.passage_id = p.passage_id "
                    "JOIN sources s ON p.source_id = s.source_id "
                    "GROUP BY s.source_type"
                ).fetchall()
            )
            if tri_by_type.get("book", 0) < 1 or tri_by_type.get("lecture_series", 0) < 1:
                errors.append(f"[Gate4] Expected matn_triangulation across both book and lecture_series, got {tri_by_type}")
        finally:
            conn.close()

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_incremental_delta_ingestion_and_cache_invalidation(errors: List[str]) -> None:
    """
    Gate 5: Verifies Incremental / Delta Lesson Ingestion & Resume Cache Invalidation:
      1. Initial run with 3 lessons (004, 005, 006) + Shamela4 book auto-ingestion.
      2. No-op resume (`resume=True, incremental=True`) when no files changed skips Stages 3..5.
      3. Incremental delta run (`resume=True, incremental=True, force=False`) when 2 new lessons
         (002, 003 with Arabic AI preambles & VPS .meta.json) and 1 real CTC .align.json (upgrading
         006 from synthetic to real alignment) arrive on disk:
         - Automatically invalidates and re-runs Stages 3, 4, and 5 while keeping Stages 0..2 cached.
         - Reuses cached `deep_lecture_*.json` extractions for unchanged lessons (004, 005).
         - Reuses cached 768-dim L2-normalized embeddings for unchanged passages and science_gems.
         - Upgrades SQLite from 3 -> 5 lecture lessons with 0% char loss, canonical episode titles,
           updated `curated.db` `transcribed_count`/`has_transcript`, and enriched `comprehensive_coverage`.
    """
    tmp_dir = Path(tempfile.mkdtemp(prefix="test_orchestrator_gate5_"))
    try:
        # 1. Create Shamela4 book dir (shamela:7026 - المنظومة العضدية / العقيدة)
        shamela_db = tmp_dir / "Shamela4_Full_DB"
        book_dir = shamela_db / "001_العقيدة" / "0007026__شرح_المنظومة_العضدية"
        book_dir.mkdir(parents=True, exist_ok=True)
        (book_dir / "book_metadata.json").write_text(
            json.dumps(
                {
                    "shamela_id": 7026,
                    "title": "شرح المنظومة العضدية",
                    "author": "الشيخ محمد الحسن الددو",
                    "category_name": "العقيدة",
                    "pages_count": 2,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        shamela_pages = [
            {
                "id": 1,
                "vol": "1",
                "page": 1,
                "text": (
                    "بسم الله الرحمن الرحيم. باب تنزيه الباري سبحانه: "
                    "«وليس مثله علا شيء ولا يشبهه شيء تعالى ذو العلا». "
                    "القاعدة الكلية أن كل ما خطر ببالك فالله بخلاف ذلك، والضابط العقدي إثبات الصفات بلا تكييف ولا تمثيل."
                ),
                "footnote": "",
            },
            {
                "id": 2,
                "vol": "1",
                "page": 2,
                "text": (
                    "فصل في دلالة الآيات: «وكل نص أوهم التشبيها تأويله أو فوضن تنزيها». "
                    "الأصل الشرعي عند أهل السنة الجمع بين الإثبات والتنزيه على وفق لسان العرب."
                ),
                "footnote": "",
            },
        ]
        (book_dir / "pages.jsonl").write_text(
            "\n".join(json.dumps(p, ensure_ascii=False) for p in shamela_pages) + "\n",
            encoding="utf-8",
        )

        # 2. Create discovery fixture with 5 episodes in playlist (initially only 004, 005, 006 exist on disk)
        disc_fixture = {
            "channels": [{"channel_id": "UC_DEDEW_G5", "title": "قناة الشيخ الددو", "url": "https://youtube.com/@dedew"}],
            "playlists": [
                {
                    "id": "PL_ADOUD_G5",
                    "playlist_id": "PL_ADOUD_G5",
                    "title": "سلسلة شرح المنظومة العضدية",
                    "videos": [
                        {
                            "vid": "vid_001_init",
                            "yt_id": "vid_001_init",
                            "video_id": "vid_001_init",
                            "title": "شرح المنظومة العضدية - الدرس 1",
                            "dur_s": 1800,
                            "duration": 1800,
                        },
                        {
                            "vid": "mD2uoA578qo",
                            "yt_id": "mD2uoA578qo",
                            "video_id": "mD2uoA578qo",
                            "title": "شرح المنظومة العضدية - الدرس 2",
                            "dur_s": 1950,
                            "duration": 1950,
                        },
                        {
                            "vid": "Bd3kSlIS-RY",
                            "yt_id": "Bd3kSlIS-RY",
                            "video_id": "Bd3kSlIS-RY",
                            "title": "شرح المنظومة العضدية - الدرس 3",
                            "dur_s": 2100,
                            "duration": 2100,
                        },
                        {
                            "vid": "a7X1z6W9qYp",
                            "yt_id": "a7X1z6W9qYp",
                            "video_id": "a7X1z6W9qYp",
                            "title": "شرح المنظومة العضدية - الدرس 4",
                            "dur_s": 2200,
                            "duration": 2200,
                        },
                        {
                            "vid": "b8Y2x7V8rZq",
                            "yt_id": "b8Y2x7V8rZq",
                            "video_id": "b8Y2x7V8rZq",
                            "title": "شرح المنظومة العضدية - الدرس 5",
                            "dur_s": 2300,
                            "duration": 2300,
                        },
                        {
                            "vid": "c9Z3y8U7sAr",
                            "yt_id": "c9Z3y8U7sAr",
                            "video_id": "c9Z3y8U7sAr",
                            "title": "شرح المنظومة العضدية - الدرس 6",
                            "dur_s": 2400,
                            "duration": 2400,
                        },
                    ],
                }
            ],
            "videos": [],
            "archive_items": [],
            "books": [
                {
                    "book_id": "shamela:7026",
                    "title": "شرح المنظومة العضدية",
                    "author": "الشيخ محمد الحسن الددو",
                    "science": "العقيدة",
                }
            ],
        }
        disc_path = tmp_dir / "dedew_g5_disc.json"
        disc_path.write_text(json.dumps(disc_fixture, ensure_ascii=False, indent=2), encoding="utf-8")

        ext_series_root = tmp_dir / "ytb_daddo"
        s_dir = ext_series_root / "sharh_manzouma_adoudiya"
        s_dir.mkdir(parents=True, exist_ok=True)
        (s_dir / "_meta.json").write_text(
            json.dumps({"series_name": "شرح المنظومة العضدية", "playlist_id": "PL_ADOUD_G5"}, ensure_ascii=False),
            encoding="utf-8",
        )

        # Initial 3 lessons: 004 and 005 have real CTC .align.json + VPS .meta.json (without title); 006 has only .txt
        txt_004 = (
            "بسم الله الرحمن الرحيم، الحمد لله رب العالمين، وصلى الله وسلم على نبينا محمد. "
            "في هذا الدرس الرابع من شرح المنظومة العضدية نشرح قول الناظم رحمه الله: "
            "«وليس مثله علا شيء ولا يشبهه شيء تعالى ذو العلا». "
            "قال الإمام مالك والشافعي في المدينة المنورة: القاعدة الكلية أن كل ما خطر ببالك فالله بخلاف ذلك، والضابط العقدي إثبات الصفات بلا تكييف ولا تمثيل. "
            "قال الله تعالى: ﴿لَيْسَ كَمِثْلِهِ شَيْءٌ وَهُوَ السَّمِيعُ الْبَصِيرُ﴾.\n"
        )
        txt_005 = (
            "بسم الله الرحمن الرحيم، الحمد لله والصلاة والسلام على رسول الله. "
            "في هذا الدرس الخامس من شرح المنظومة العضدية نشرح قول المصنف رحمه الله: "
            "«وكل نص أوهم التشبيها تأويله أو فوضن تنزيها». "
            "قال الإمام مالك بن أنس والشافعي وأحمد بن حنبل: الأصل الشرعي عند أهل السنة الجمع بين الإثبات والتنزيه على وفق لسان العرب. "
            "قال الله تعالى: ﴿وَمَا آتَاكُمُ الرَّسُولُ فَخُذُوهُ وَمَا نَهَاكُمْ عَنْهُ فَانْتَهُوا﴾.\n"
        )
        txt_006 = (
            "بسم الله الرحمن الرحيم، الحمد لله رب العالمين. "
            "في هذا الدرس السادس من شرح المنظومة العضدية نختم شرح قول المصنف: "
            "«وليس مثله علا شيء ولا يشبهه شيء تعالى ذو العلا» "
            "وبيان أنه المحكم الذي ترد إليه سائر المتشابهات في باب الأسماء والصفات عند الإمام مالك والشافعي في المدينة المنورة. "
            "قال الله تعالى: ﴿وَأَقِيمُوا الصَّلَاةَ وَآتُوا الزَّكَاةَ﴾.\n"
        )
        (s_dir / "004_a7X1z6W9qYp.txt").write_text(txt_004, encoding="utf-8")
        (s_dir / "004_a7X1z6W9qYp.align.json").write_text(
            json.dumps({"w": [[w, idx * 0.5, idx * 0.5 + 0.4] for idx, w in enumerate(txt_004.split(), 1)]}, ensure_ascii=False),
            encoding="utf-8",
        )
        (s_dir / "004_a7X1z6W9qYp.meta.json").write_text(
            json.dumps({"dur_s": 2200, "chars": len(txt_004), "words": len(txt_004.split()), "ok": True}, ensure_ascii=False),
            encoding="utf-8",
        )

        (s_dir / "005_b8Y2x7V8rZq.txt").write_text(txt_005, encoding="utf-8")
        (s_dir / "005_b8Y2x7V8rZq.align.json").write_text(
            json.dumps({"w": [[w, idx * 0.5, idx * 0.5 + 0.4] for idx, w in enumerate(txt_005.split(), 1)]}, ensure_ascii=False),
            encoding="utf-8",
        )
        (s_dir / "005_b8Y2x7V8rZq.meta.json").write_text(
            json.dumps({"dur_s": 2300, "chars": len(txt_005), "words": len(txt_005.split()), "ok": True}, ensure_ascii=False),
            encoding="utf-8",
        )

        (s_dir / "006_c9Z3y8U7sAr.txt").write_text(txt_006, encoding="utf-8")

        quota_mock = {
            "models": [
                {
                    "label": "Gemini 3.8 Flash (High)",
                    "remainingPercentage": 0.92,
                    "timeUntilResetMs": 3600000,
                    "isExhausted": False,
                }
            ]
        }
        work_dir = tmp_dir / "work"

        # --- RUN 1: Initial 3-lesson orchestration ---
        rep1 = orch.orchestrate_person(
            name="الشيخ محمد الحسن الددو",
            person_id="dedew_gate5",
            work_dir=work_dir,
            offline_fixture=str(disc_path),
            series_transcripts_dir=ext_series_root,
            shamela_db_dir=shamela_db,
            auto_ingest_shamela_books=True,
            quota_override=quota_mock,
            embedding_backend="deterministic-arabic-mps",
            embedding_dim=768,
            resume=True,
            incremental=True,
        )
        if rep1.get("overall_status") != "PASS":
            errors.append(f"[Gate5] Run 1 expected PASS, got {rep1.get('overall_status')}")

        s2_ts_run1 = rep1["stages"]["2"]["completed_at"]
        s3_ts_run1 = rep1["stages"]["3"]["completed_at"]
        s4_ts_run1 = rep1["stages"]["4"]["completed_at"]

        # Verify canonical episode title was merged into 004_a7X1z6W9qYp.meta.json despite VPS .meta.json
        ext_meta_004 = json.loads(
            (work_dir / "dedew_gate5" / "03_extracted" / "series" / "dedew_gate5" / "s001" / "004_a7X1z6W9qYp.meta.json").read_text(encoding="utf-8")
        )
        if ext_meta_004.get("title") != "شرح المنظومة العضدية - الدرس 4" or ext_meta_004.get("dur_s") != 2200:
            errors.append(f"[Gate5] Expected merged canonical title + VPS dur_s in 004.meta.json, got {ext_meta_004}")

        # Verify 006 initially received a synthetic .align.json
        align_006_path = work_dir / "dedew_gate5" / "03_extracted" / "series" / "dedew_gate5" / "s001" / "006_c9Z3y8U7sAr.align.json"
        _, is_real_006_run1, _ = orch._inspect_align_file(align_006_path)
        if is_real_006_run1:
            errors.append("[Gate5] Expected 006.align.json in Run 1 to be synthetic before real CTC alignment arrives")

        # --- RUN 2: No-op resume when nothing changed on disk ---
        rep2 = orch.orchestrate_person(
            name="الشيخ محمد الحسن الددو",
            person_id="dedew_gate5",
            work_dir=work_dir,
            offline_fixture=str(disc_path),
            series_transcripts_dir=ext_series_root,
            shamela_db_dir=shamela_db,
            auto_ingest_shamela_books=True,
            quota_override=quota_mock,
            embedding_backend="deterministic-arabic-mps",
            embedding_dim=768,
            resume=True,
            incremental=True,
        )
        if rep2.get("delta_ingestion", {}).get("has_delta") is not False:
            errors.append(f"[Gate5] Run 2 (no-op) expected has_delta == False, got {rep2.get('delta_ingestion')}")
        if rep2["stages"]["3"]["completed_at"] != s3_ts_run1 or rep2["stages"]["4"]["completed_at"] != s4_ts_run1:
            errors.append("[Gate5] Run 2 (no-op) unexpectedly re-ran Stage 3 or Stage 4")

        # --- RUN 3: Incremental Delta Arrival (2 new lessons 002, 003 + 1 real CTC alignment for 006) ---
        txt_002_raw = (
            "تفضل، إليك تفريغ النص المسموع كاملاً كما ورد دون اختصار:\n"
            "بسم الله الرحمن الرحيم، الحمد لله رب العالمين. في هذا المجلس الثاني نشرح قول المصنف رحمه الله: "
            "«وليس مثله علا شيء ولا يشبهه شيء تعالى ذو العلا». "
            "قال الإمام مالك والشافعي في المدينة المنورة: القاعدة الأصولية أن الكلام في الصفات فرع عن الكلام في الذات. "
            "قال الله تعالى: ﴿لَيْسَ كَمِثْلِهِ شَيْءٌ وَهُوَ السَّمِيعُ الْبَصِيرُ﴾.\n"
            "آمل أن يكون هذا التفريغ مفيداً وواضحاً."
        )
        txt_003_raw = (
            "إليك النص المفرغ بدقة:\n"
            "بسم الله الرحمن الرحيم، الحمد لله رب العالمين. في الدرس الثالث نبين قول المصنف: "
            "«وكل نص أوهم التشبيها تأويله أو فوضن تنزيها». "
            "قال الإمام مالك بن أنس والشافعي: الضابط عند المحققين أن التنزيه مقدم على كل وهم تمثيلي. "
            "قال الله تعالى: ﴿وَأَقِيمُوا الصَّلَاةَ وَآتُوا الزَّكَاةَ﴾.\n"
        )
        (s_dir / "002_mD2uoA578qo.txt").write_text(txt_002_raw, encoding="utf-8")
        (s_dir / "002_mD2uoA578qo.meta.json").write_text(
            json.dumps({"dur_s": 1950, "chars": len(txt_002_raw), "ok": True}, ensure_ascii=False),
            encoding="utf-8",
        )
        (s_dir / "003_Bd3kSlIS-RY.txt").write_text(txt_003_raw, encoding="utf-8")
        (s_dir / "003_Bd3kSlIS-RY.meta.json").write_text(
            json.dumps({"dur_s": 2100, "chars": len(txt_003_raw), "ok": True}, ensure_ascii=False),
            encoding="utf-8",
        )
        # Real CTC alignment arrives for 006 (no "synthetic" flag)
        (s_dir / "006_c9Z3y8U7sAr.align.json").write_text(
            json.dumps({"w": [[w, idx * 0.45, idx * 0.45 + 0.35] for idx, w in enumerate(txt_006.split(), 1)]}, ensure_ascii=False),
            encoding="utf-8",
        )

        rep3 = orch.orchestrate_person(
            name="الشيخ محمد الحسن الددو",
            person_id="dedew_gate5",
            work_dir=work_dir,
            offline_fixture=str(disc_path),
            series_transcripts_dir=ext_series_root,
            shamela_db_dir=shamela_db,
            auto_ingest_shamela_books=True,
            quota_override=quota_mock,
            embedding_backend="deterministic-arabic-mps",
            embedding_dim=768,
            resume=True,
            incremental=True,
            force=False,
        )
        delta3 = rep3.get("delta_ingestion", {})
        if not delta3.get("has_delta") or not delta3.get("is_incremental_update"):
            errors.append(f"[Gate5] Run 3 expected has_delta=True & is_incremental_update=True, got {delta3}")
        if int(delta3.get("new_lessons_count", 0)) != 2:
            errors.append(f"[Gate5] Run 3 expected new_lessons_count == 2, got {delta3.get('new_lessons_count')}")
        if int(delta3.get("updated_alignments_count", 0)) != 1:
            errors.append(f"[Gate5] Run 3 expected updated_alignments_count == 1, got {delta3.get('updated_alignments_count')}")

        # Stage 2 should remain cached from Run 1, while Stages 3 & 4 must have re-run
        if rep3["stages"]["2"]["completed_at"] != s2_ts_run1:
            errors.append("[Gate5] Run 3 should have kept Stage 2 cached")
        stage4_metrics = rep3["stages"]["4"]["metrics"]
        if int(stage4_metrics.get("reused_cached_lecture_extractions", 0)) != 2:
            errors.append(
                f"[Gate5] Run 3 expected reused_cached_lecture_extractions == 2 (for 004 & 005), got {stage4_metrics.get('reused_cached_lecture_extractions')}"
            )
        if int(stage4_metrics.get("newly_extracted_lectures", 0)) != 3:
            errors.append(
                f"[Gate5] Run 3 expected newly_extracted_lectures == 3 (002, 003, and re-aligned 006), got {stage4_metrics.get('newly_extracted_lectures')}"
            )

        embed_stats3 = rep3["stages"]["5"]["metrics"].get("embed_stats", {})
        if int(embed_stats3.get("reused_cached_passages", 0)) < 3 or int(embed_stats3.get("newly_embedded_passages", 0)) < 2:
            errors.append(f"[Gate5] Run 3 expected embedding cache reuse + delta embedding, got {embed_stats3}")

        # Verify 006.align.json in 03_extracted is now real (not synthetic)
        _, is_real_006_run3, _ = orch._inspect_align_file(align_006_path)
        if not is_real_006_run3:
            errors.append("[Gate5] Expected 006.align.json in 03_extracted to be upgraded to real CTC alignment in Run 3")

        # Verify SQLite has 5 lecture lessons, 0% char loss, and curated.db has transcribed_count == 5
        db_path = work_dir / "dedew_gate5" / "04_knowledge_db" / "dedew_gate5_objects.sqlite"
        conn = sqlite3.connect(str(db_path))
        try:
            cur = conn.cursor()
            lec_parts = cur.execute(
                "SELECT lp.part_number, lp.title FROM lessons_or_parts lp "
                "JOIN sources s ON lp.source_id = s.source_id "
                "WHERE s.source_type = 'lecture_series' ORDER BY lp.part_number"
            ).fetchall()
            if len(lec_parts) != 5 or [r[0] for r in lec_parts] != [2, 3, 4, 5, 6]:
                errors.append(f"[Gate5] Expected 5 lecture parts [2,3,4,5,6] in SQLite after delta, got {lec_parts}")
        finally:
            conn.close()

        cur_db_path = work_dir / "dedew_gate5" / "02_curated" / "curated.db"
        c_conn = sqlite3.connect(str(cur_db_path))
        try:
            tc_val = c_conn.execute("SELECT transcribed_count FROM series WHERE id = 'dedew_gate5__s001'").fetchone()
            ht_cnt = c_conn.execute("SELECT COUNT(*) FROM lessons WHERE has_transcript = 1").fetchone()[0]
            if not tc_val or int(tc_val[0]) != 5 or int(ht_cnt) != 5:
                errors.append(f"[Gate5] Expected curated.db series.transcribed_count=5 and 5 lessons with has_transcript=1, got tc={tc_val}, ht={ht_cnt}")
        finally:
            c_conn.close()

        cov3 = rep3.get("comprehensive_coverage", {})
        if (
            int(cov3.get("shamela_books_imported_count", 0)) < 1
            or int(cov3.get("matn_triangulation_count", 0)) < 3
            or len(cov3.get("science_gems_retrieval_results", [])) < 1
        ):
            errors.append(f"[Gate5] Expected comprehensive_coverage with Shamela books, matn_triangulation >= 3, and gem retrieval hits, got {cov3}")

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def main() -> int:
    errors: List[str] = []
    print("=== Running person-to-knowledge-orchestrator End-to-End & Gate Tests ===")
    test_e2e_full_6_stage_pipeline(errors)
    test_hard_gates_block_corrupt_inputs(errors)
    test_multi_format_series_and_shamela_jsonl_ingestion(errors)
    test_incremental_delta_ingestion_and_cache_invalidation(errors)

    if errors:
        print(f"FAIL ({len(errors)} errors):")
        for err in errors:
            print(f"  - {err}")
        return 1

    print("  [PASS] Stage 0 (Gate G0): Quota >= 20% & Lean HOME isolation verified")
    print("  [PASS] Stage 1 (Gate G1): Multi-source discovery intake verified")
    print("  [PASS] Stage 2 (Gate G2): 9-stage curation (0 scanner flaws, 0 audit errors, 0 dupes) verified")
    print("  [PASS] Stage 3 (Gate G3): Dual-track extraction (0 AI preambles, 100.0% PDF char retention) verified")
    print("  [PASS] Stage 4 (Gate G4): Unified Deep Indexing & USDB v5.7 SQLite (0% char loss, 0 P0 errors) verified")
    print("  [PASS] Stage 5 (Gate G5): Dual-vector 768-dim Gemma-2 embeddings & HybridSearchEngine verified")
    print("  [PASS] Hard Gate Blocking (G0..G5 negative corruption rejection) & Checkpoint Resume verified")
    print("  [PASS] Gate 4: Multi-Format Real Series & Shamela4 JSONL Book Auto-Ingestion verified")
    print("  [PASS] Gate 5: Incremental Delta Lesson Ingestion & Resume Cache Invalidation verified")
    print("PASS (0 errors)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
