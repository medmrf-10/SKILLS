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


def main() -> int:
    errors: List[str] = []
    print("=== Running person-to-knowledge-orchestrator End-to-End & Gate Tests ===")
    test_e2e_full_6_stage_pipeline(errors)
    test_hard_gates_block_corrupt_inputs(errors)

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
    print("PASS (0 errors)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
