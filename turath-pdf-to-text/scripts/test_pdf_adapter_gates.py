#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_pdf_adapter_gates.py — بوابة الفحص الحتمية الشاملة للإصدار v2.0 من مهارة `turath-pdf-to-text`.

تختبر ثلاث بوابات متتابعة:
  - Gate 1: تشغيل بوابات `test_pdf_gates.py` الأصلية (12 اختباراً هندسياً وبصرياً) والتأكد من عدم كسر أي قاعدة.
  - Gate 2: اختبار `pdf_to_preflight_adapter.py` على 5 صفحات واقعية متعددة التخطيطات (`pages/p0001.json` .. `p0005.json`
            تضم متناً وعناوين أبواب وآيات قرآنية وحواشي سفلية مرقمة 1، 2، 3 وحاشية جدول أزهرية `framed_hashiya`
            ذات متن عمودي مدار 90°) والتحقق التشفيري من حفظ 100% من الحروف والحواشي (`100% Zero-Loss Check`).
  - Gate 3: تمرير مخرجات المحول فعلياً إلى `/Users/macm1pro/REPOS/SKILLS/turath-deep-indexing/scripts/manifest_v4.py`
            و`fn_linker_v4.py` والتحقق من توليد الـ Manifest وربط جميع الحواشي الـ 13 بدون أي أخطاء.

الخروج القياسي عند النجاح: `PASS (0 errors)`
"""
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

import test_pdf_gates  # noqa: E402
from pdf_to_preflight_adapter import (  # noqa: E402
    DEFAULT_DEEP_INDEXING_SCRIPTS,
    convert_pdf_output_to_preflight,
)


def build_realistic_5_pages_fixture(pages_dir: str) -> list[dict]:
    """
    يبني 5 صفحات واقعية (p0001.json .. p0005.json) تغطي:
      - صفحات اعتيادية (standard_single_col) مع عناوين كتب وأبواب وفصول
      - آيات قرآنية بأرقامها ﴿... (٤٣)﴾ للتأكد من عدم التباسها بأرقام الحواشي
      - حواشٍ سفلية مرقمة (١)، (٢)، (٣)
      - طرر مخطوطات جانبية [ق/ ١٢ أ]
      - صفحة جدول أزهري (framed_hashiya) مع نص داخل الجدول ومتن عمودي مدار 90° في الهامش الخارجي
      - أرقام وحروف فارسية (۱۲۵، ی، ک) لاختبار التطبيع الحتمي قبل التصدير
    """
    os.makedirs(pages_dir, exist_ok=True)
    pages = [
        {
            "pdf_page": 1,
            "tag": "p0001",
            "layout": "standard_single_col",
            "extracted": {
                "printed_page": "١٥",
                "running_header": "أدب المفتي والمستفتي",
                "matn": (
                    "كتاب أدب المفتي والمستفتي\n"
                    "باب شروط المفتي وأحكامه\n"
                    "الحمد لله الذي شرف أهل العلم بحمل شريعته (١)، وجعلهم قدوة الأمة في بيان أحكامه "
                    "لقوله تعالى: ﴿فَاسْأَلُوا أَهْلَ الذِّكْرِ إِنْ كُنْتُمْ لَا تَعْلَمُونَ (٤٣)﴾ (٢)، "
                    "فوجب على المتصدي للفتوى أن يكون عالماً بمدارك الأحكام الشرعية وأقوال الأئمة (٣)."
                ),
                "margin_notes": "[ق/ ١٢ أ]",
                "footnotes": (
                    "(١) في النسخة الأزهرية: بحفظ شريعته المطهرة.\n"
                    "(٢) سورة النحل: الآية ٤٣، واستدل بها الأصوليون على وجوب سؤال العلماء.\n"
                    "(٣) راجع المجموع شرح المهذب للإمام النووي ص ٢٤."
                ),
                "uncertain_words": [],
            },
            "gate_report": {"total_words": 62, "warnings": []},
        },
        {
            "pdf_page": 2,
            "tag": "p0002",
            "layout": "standard_single_col",
            "extracted": {
                "printed_page": "١٦",
                "running_header": "أدب المفتي والمستفتي",
                "matn": (
                    "ولا يجوز له أن يفتي بالتشهي أو الهوى، بل يتحرى الدليل الراجح عنده (١).\n"
                    "فصل في المفتي المستقل وغير المستقل\n"
                    "المفتي ينقسم إلى قسمين: الأول المفتي المستقل الذي يستقل بإدراك الأحكام من الأدلة الشرعية (٢)، "
                    "والثاني المفتي المنتسب الذي يخرج الوجوه على أصول إمامه ويناظر في الأدلة (٣)."
                ),
                "margin_notes": "",
                "footnotes": (
                    "١ - نقل الإجماع على ذلك ابن عبد البر في جامع بيان العلم وفضله.\n"
                    "٢ - شرطه أن يكون قيماً بمعرفة الكتاب والسنة والإجماع والقياس.\n"
                    "٣ - وهو الذي يحفظ مذهب إمامه ويتمكن من تخريج المسائل المسكوت عنها."
                ),
                "uncertain_words": [],
            },
            "gate_report": {"total_words": 78, "warnings": []},
        },
        {
            "pdf_page": 3,
            "tag": "p0003",
            "layout": "framed_hashiya",
            "extracted": {
                "printed_page": "١٧",
                "running_header": "حاشية الباجوري على ابن قاسم",
                "matn": (
                    "حاشية الجدول في شروط التكليف والاجتهاد\n"
                    "قوله: (وشرائط وجوب الصلاة ثلاثة أشياء) أي الشرائط التي يتوقف عليها أصل الوجوب (١)، "
                    "فلا يخاطب الصبي ولا المجنون خطاب تكليف إجماعاً، وإنما يؤمر الصبي المميز بها لسبع سنين "
                    "تمريناً له على العبادة ليعتادها بعد البلوغ (٢)."
                ),
                "margin_notes": (
                    "متن الغاية والتقريب بالهامش العمودي المدار تسعين درجة: "
                    "وشرائط وجوب الصلاة ثلاثة أشياء: الإسلام والبلوغ والعقل وهو حد التكليف."
                ),
                "footnotes": (
                    "(١) فرق الأصوليون بين شروط الوجوب وشروط الصحة التي يتوقف عليها الاعتداد بالفعل.\n"
                    "(٢) لحديث: مروا أولادكم بالصلاة وهم أبناء سبع سنين، أخرجه أبو داود."
                ),
                "uncertain_words": [],
            },
            "gate_report": {"total_words": 88, "warnings": []},
        },
        {
            "pdf_page": 4,
            "tag": "p0004",
            "layout": "standard_single_col",
            "extracted": {
                "printed_page": "١٨",
                "running_header": "أدب المفتي والمستفتي",
                "matn": (
                    "باب آداب المستفتي وصفته\n"
                    "يلزم العامي ومن لم يبلغ رتبة الاجتهاد أن يستفتي أوثق العلماء في بلده دينا وعلما (1)، "
                    "فقد نص الأئمة سنة ۱۲۵ هـ في \u06a9تاب الفتوى على أنه يبحث عن الأعلم والأورع (2)، "
                    "ولا يتتبع الرخص الشاذة التي تخرق الإجماع لما في ذلك من انحلال ربقة التكليف (3)."
                ),
                "margin_notes": "[ق/ ١٣ ب]",
                "footnotes": (
                    "(1) قال الخطيب البغدادي في الفقيه والمتفقه: يجب عليه السؤال عمن يوثق بدينه وعلمه.\n"
                    "(2) توف\u06cc جماعة من التابعين على هذا القول وبه جزم ابن الصلاح.\n"
                    "(3) قال سليمان التيمي: لو أخذت برخصة كل عالم اجتمع فيك الشر كله."
                ),
                "uncertain_words": [],
            },
            "gate_report": {"total_words": 82, "warnings": []},
        },
        {
            "pdf_page": 5,
            "tag": "p0005",
            "layout": "standard_single_col",
            "extracted": {
                "printed_page": "١٩",
                "running_header": "أدب المفتي والمستفتي",
                "matn": (
                    "فصل في كتابة الفتوى وتوقيعها\n"
                    "ينبغي للمفتي أن يكتب الجواب بخط واضح مبين لا يحتمل اللبس ولا الإجمال المخل (١)، "
                    "وأن يختم فتواه بذكر الله تعالى والتفويض إليه فيقول: والله سبحانه وتعالى أعلم بالصواب (٢)، "
                    "والحمد لله رب العالمين وصلى الله على سيدنا محمد وعلى آله وصحبه وسلم."
                ),
                "margin_notes": "",
                "footnotes": (
                    "(١) وكان السلف يكرهون الإفتاء في رقعة ضيقة خشية أن يلحق بها ما ليس منها.\n"
                    "(٢) ثبت ذلك عن الصحابة والتابعين وأئمة المذاهب الأربعة رضي الله عنهم."
                ),
                "uncertain_words": [],
            },
            "gate_report": {"total_words": 72, "warnings": []},
        },
    ]

    for p in pages:
        p_path = os.path.join(pages_dir, f"{p['tag']}.json")
        with open(p_path, "w", encoding="utf-8") as f:
            json.dump(p, f, ensure_ascii=False, indent=2)

    return pages


def run_gate_1_original_visual_gates() -> list[str]:
    """Gate 1: تشغيل بوابات test_pdf_gates.py الأصلية (12 اختباراً) والتأكد من عدم كسر أي قاعدة بصرية."""
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromModule(test_pdf_gates)
    buf = io.StringIO()
    runner = unittest.TextTestRunner(stream=buf, verbosity=2)
    result = runner.run(suite)
    errors = []
    if result.TestsRun != 12 if hasattr(result, "TestsRun") else result.testsRun < 12:
        errors.append(f"Gate 1 expected >= 12 unit tests in test_pdf_gates.py, ran {result.testsRun}")
    for test_case, tb in result.failures + result.errors:
        errors.append(f"Gate 1 failure in {test_case}: {tb.strip()}")
    return errors


def run_gate_2_and_gate_3_adapter_and_manifest_v4() -> tuple[list[str], list[str], dict]:
    """
    Gate 2: اختبار pdf_to_preflight_adapter.py على 5 صفحات واقعية والتحقق من حفظ 100% من الحروف والحواشي.
    Gate 3: تمرير مخرجات المحول فعلياً إلى manifest_v4.py و fn_linker_v4.py والتحقق من نجاح توليد الـ Manifest بصفر أخطاء.
    """
    gate2_errors = []
    gate3_errors = []
    summary_stats = {}

    with tempfile.TemporaryDirectory(prefix="turath_pdf_adapter_test_") as tmp_root:
        book_in_dir = os.path.join(tmp_root, "adab_almufti_pdf_out")
        pages_dir = os.path.join(book_in_dir, "pages")
        preflight_out_dir = os.path.join(tmp_root, "preflight_v4_out")

        build_realistic_5_pages_fixture(pages_dir)

        adapter_rep = convert_pdf_output_to_preflight(
            input_path=book_in_dir,
            out_dir=preflight_out_dir,
            book_id=9001,
            science="fiqh",
            round_num=99,
            title="أدب المفتي والمستفتي",
            author="ابن الصلاح الشهرزوري",
            death="643",
            juz=1,
            run_manifest_v4=True,
            deep_indexing_scripts_dir=DEFAULT_DEEP_INDEXING_SCRIPTS,
        )

        # ---- فحوص Gate 2 (الحفاظ الحرفي 100% وتوليد الملفات المعيارية) ----
        zl = adapter_rep.get("zero_loss_check", {})
        if not zl.get("passed"):
            gate2_errors.append(f"Zero-Loss check failed: {zl.get('errors')}")
        if zl.get("body_char_loss", -1) != 0:
            gate2_errors.append(f"Non-zero body char loss: {zl.get('body_char_loss')}")
        if zl.get("footnotes_char_loss", -1) != 0:
            gate2_errors.append(f"Non-zero footnotes char loss: {zl.get('footnotes_char_loss')}")
        if zl.get("retention_pct") != 100.0:
            gate2_errors.append(f"Expected 100.0% retention, got {zl.get('retention_pct')}")
        if zl.get("source_body_sha256") != zl.get("book_matn_body_sha256"):
            gate2_errors.append("SHA-256 mismatch between source body and book_matn.txt")
        if zl.get("source_body_sha256") != zl.get("snapshot_parts_body_sha256"):
            gate2_errors.append("SHA-256 mismatch between source body and snapshot 0*.json parts")
        if zl.get("source_footnotes_sha256") != zl.get("actual_footnotes_sha256"):
            gate2_errors.append("SHA-256 mismatch between source footnotes and footnotes.json")

        if adapter_rep.get("non_blank_pages") != 5:
            gate2_errors.append(f"Expected 5 non-blank pages, got {adapter_rep.get('non_blank_pages')}")
        if adapter_rep.get("framed_hashiya_pages") != 1:
            gate2_errors.append(f"Expected 1 framed_hashiya page, got {adapter_rep.get('framed_hashiya_pages')}")
        if adapter_rep.get("total_footnotes_count") != 13:
            gate2_errors.append(f"Expected 13 total footnotes across 5 pages, got {adapter_rep.get('total_footnotes_count')}")

        # فحص توليد ملفات p0001.txt .. p0005.txt وعلامات الصفحات [ص: N]
        for i, expected_pg in enumerate(["١٥", "١٦", "١٧", "١٨", "١٩"], 1):
            tag = f"p{i:04d}"
            sidecar_txt = os.path.join(pages_dir, f"{tag}.txt")
            out_txt = os.path.join(preflight_out_dir, "pages_txt", f"{tag}.txt")
            if not os.path.isfile(sidecar_txt) or not os.path.isfile(out_txt):
                gate2_errors.append(f"Missing page .txt sidecar for {tag}")
            else:
                txt_c = Path(sidecar_txt).read_text(encoding="utf-8")
                if f"[ص: {expected_pg}]" not in txt_c:
                    gate2_errors.append(f"Page marker [ص: {expected_pg}] missing in {sidecar_txt}")

        book_matn_txt = Path(adapter_rep["files_generated"]["book_matn_txt"]).read_text(encoding="utf-8")
        for expected_pg in ["١٥", "١٦", "١٧", "١٨", "١٩"]:
            if f"[ص: {expected_pg}]" not in book_matn_txt:
                gate2_errors.append(f"Standard page marker [ص: {expected_pg}] missing in book_matn.txt")
        if "متن الغاية والتقريب بالهامش العمودي المدار تسعين درجة" not in book_matn_txt:
            gate2_errors.append("Azhari framed_hashiya 90° rotated outer margin text missing in book_matn.txt")
        if "سنة ١٢٥ هـ في كتاب الفتوى" not in book_matn_txt:
            gate2_errors.append("Persian digits/chars on page 4 were not normalized to Arabic standard in book_matn.txt")

        # ---- فحوص Gate 3 (التكامل الفعلي مع manifest_v4.py و fn_linker_v4.py) ----
        mv4 = adapter_rep.get("manifest_v4_verification", {})
        if not mv4.get("executed"):
            gate3_errors.append("manifest_v4.py was not executed by adapter")
        if not mv4.get("passed"):
            gate3_errors.extend(mv4.get("errors") or ["manifest_v4_verification reported passed=False"])

        # فحص استدعاء build_book_window_and_manifest و link_book_footnotes_v4 برمجياً أيضاً
        sys.path.insert(0, DEFAULT_DEEP_INDEXING_SCRIPTS)
        import fn_linker_v4 as fnv4  # noqa: E402
        import manifest_v4 as man_v4  # noqa: E402

        orig_base = man_v4.BASE
        orig_snap = man_v4.SNAPSHOT_DIR
        try:
            man_v4.BASE = Path(preflight_out_dir)
            man_v4.SNAPSHOT_DIR = man_v4.BASE / "source_snapshots"
            m_entry, win_parts, win_fns, toc_data = man_v4.build_book_window_and_manifest(99, "fiqh", 9001)
            fn_direct = fnv4.link_book_footnotes_v4(9001, "fiqh", win_parts)

            if m_entry.get("status") not in ("OK_WHOLE_PARTS", "OK_SLICED_WINDOW"):
                gate3_errors.append(f"Unexpected manifest status: {m_entry.get('status')}")
            if m_entry.get("window_coverage_pct") != 100.0:
                gate3_errors.append(f"Expected 100.0% window coverage, got {m_entry.get('window_coverage_pct')}")
            if m_entry.get("fn_linked_count") != 13:
                gate3_errors.append(f"Expected 13 linked footnotes in manifest_v4, got {m_entry.get('fn_linked_count')}")
            if m_entry.get("fn_unlinked_in_window_count") != 0:
                gate3_errors.append(f"Expected 0 unlinked footnotes, got {m_entry.get('fn_unlinked_in_window_count')}")
            if m_entry.get("unclassified_tokens_count") != 0:
                gate3_errors.append(f"Expected 0 unclassified tokens, got {m_entry.get('unclassified_tokens_count')}")
            if m_entry.get("token_classes", {}).get("verse_no") != 1:
                gate3_errors.append(
                    f"Expected Quranic verse number (٤٣) to be classified as verse_no=1, got {m_entry.get('token_classes')}"
                )
            if fn_direct.get("p0_errors"):
                gate3_errors.extend(fn_direct["p0_errors"])
        finally:
            man_v4.BASE = orig_base
            man_v4.SNAPSHOT_DIR = orig_snap

        # تنظيف الملف المؤقت الذي يكتبه manifest_v4 في /tmp/r99_fiqh.txt
        tmp_dump = "/tmp/r99_fiqh.txt"
        if os.path.exists(tmp_dump):
            try:
                os.remove(tmp_dump)
            except OSError:
                pass

        summary_stats = {
            "pages_tested": adapter_rep.get("non_blank_pages"),
            "parts_built": adapter_rep.get("total_parts_built"),
            "footnotes_linked": mv4.get("book_manifest", {}).get("fn_linked_count", 0),
            "retention_pct": zl.get("retention_pct"),
            "body_chars": zl.get("body_stream_chars"),
            "fn_chars": zl.get("footnotes_stream_chars"),
        }

    return gate2_errors, gate3_errors, summary_stats


def main():
    print("======================================================================")
    print("  turath-pdf-to-text v2.0 — Deterministic Quality & Pre-Flight Gates")
    print("======================================================================")

    g1_errors = run_gate_1_original_visual_gates()
    print(f"[Gate 1] Original Visual & DB Gates (12 tests)      : {'PASS' if not g1_errors else 'FAIL'} ({len(g1_errors)} errors)")

    g2_errors, g3_errors, stats = run_gate_2_and_gate_3_adapter_and_manifest_v4()
    print(
        f"[Gate 2] Adapter 100% Zero-Loss (5 pages + Hashiya) : {'PASS' if not g2_errors else 'FAIL'} ({len(g2_errors)} errors) "
        f"[retention={stats.get('retention_pct')}%, body_chars={stats.get('body_chars')}, fn_chars={stats.get('fn_chars')}]"
    )
    print(
        f"[Gate 3] Pre-Flight manifest_v4 & fn_linker_v4      : {'PASS' if not g3_errors else 'FAIL'} ({len(g3_errors)} errors) "
        f"[parts={stats.get('parts_built')}, fn_linked={stats.get('footnotes_linked')}/13]"
    )

    all_errors = g1_errors + g2_errors + g3_errors
    if all_errors:
        print("\n[ERRORS DETECTED]:")
        for err in all_errors:
            print(f"  - {err}")
        print(f"\nFAIL ({len(all_errors)} errors)")
        sys.exit(1)

    print("----------------------------------------------------------------------")
    print("PASS (0 errors)")
    sys.exit(0)


if __name__ == "__main__":
    main()
