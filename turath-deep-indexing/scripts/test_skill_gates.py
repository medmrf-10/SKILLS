#!/usr/bin/env python3
"""
Deterministic Automated Regression & Stress-Test Suite for `turath-deep-indexing` (v5.6).
Tests all 37 quality gate contracts and edge cases across:
  1. merge_round.py (Classical & Modern Books — 22 sciences)
  2. fn_linker_v4.py (Footnote LCS & Source-Stripped Marker Alignment)
  3. merge_lecture.py (Spoken Lectures, CTC Forced Alignment & Matn Triangulation)
  4. merge_course.py (Technical Courses, 5 Atomic Block Types & UAX #9 P2 Cognitive DNA)
  5. build_cross_corpus_graph.py (Cross-Corpus Ayah, Matn & Person Entity Resolution)
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

import build_cross_corpus_graph as bcg
import fn_linker_v4 as fnl
import merge_course as mc
import merge_lecture as ml
import merge_round as mr


class TestBookGatesAndEdgeCases(unittest.TestCase):
    def test_01_expanded_22_sciences_and_dynamic_order(self):
        """Mistake #27: Non-9 sciences ('hadith_sharh', 'tafsir', 'irab_quran', 'manzumat', etc.) must not be silently skipped."""
        for sc in (
            "tarajim", "sirah", "tari5", "tazkia", "akida", "maliki", "ossoul", "3olomQuran", "9awa3idFi9h",
            "hadith", "hadith_sharh", "tafsir", "irab_quran", "manzumat", "kalam_firaq",
            "nahw", "sarf", "balagha", "mantiq", "munazarah", "lugha", "faraid",
        ):
            meta = mr.get_science_meta(sc)
            self.assertIn("science_ar", meta)
            self.assertIn("gem_label", meta)
        # Fallback for unseen future science key
        custom_meta = mr.get_science_meta("astronomy_turath")
        self.assertIn("science_ar", custom_meta)

    def test_02_isnad_tahwil_haa_marker(self):
        """Mistake #28: Hadith [ح] / (ح) tahwil marker inside multi-path isnad chains must be recognized."""
        chunk = (
            "حدثنا عبد الله بن مسلمة عن مالك عن نافع عن ابن عمر [ح] وحدثنا قتيبة بن سعيد حدثنا الليث "
            "عن سعيد المقبري عن أبيه عن أبي هريرة أن رسول الله صلى الله عليه وسلم قال: "
            "المسلم أخو المسلم لا يظلمه ولا يسلمه ومن كان في حاجة أخيه كان الله في حاجته."
        )
        matn_anc = "المسلم أخو المسلم لا يظلمه ولا يسلمه"
        isnad_p, clean_m, chain_ref, _ = mr.validate_and_extract_isnad(chunk, 0, matn_anc)
        self.assertTrue(len(isnad_p) > 20)
        self.assertTrue(clean_m.startswith("المسلم أخو المسلم"))
        self.assertIn("قتيبة", isnad_p)
        self.assertEqual(chain_ref, "independent")

    def test_03_unicode_islamic_honorific_ligatures(self):
        """Mistake #29: Unicode ligatures (\ufd40..\ufd4f, \ufdfa..\ufdff) must expand cleanly in clean_for_embed and match expanded text."""
        raw_part = "قال الإمام الشافعي \ufd40 في الرسالة وروى عنه الربيع بن سليمان وعن ابن عباس \ufd44 أن البيع جائز."
        cleaned = mr.clean_for_embed(raw_part, science="hadith_sharh")
        self.assertIn("رحمه الله", cleaned)
        self.assertIn("رضي الله عنهما", cleaned)
        self.assertNotIn("\ufd40", cleaned)
        # Anchor & span verification when agent expands ligature to words
        off, st = mr.find_anchor_offset(raw_part, "قال الإمام الشافعي رحمه الله في الرسالة", 0)
        self.assertEqual(off, 0)
        self.assertNotEqual(st, "failed")
        mode, s_idx, e_idx = mr.verify_and_locate_span_in_part(
            "قال الإمام الشافعي رحمه الله في الرسالة وروى عنه الربيع", raw_part, allow_elision=False
        )
        self.assertNotEqual(mode, "failed")
        self.assertEqual(s_idx, 0)

    def test_04_inline_safha_page_marker_stripping(self):
        """Mistake #30: Inline 'صفحة ١٣٧' markers in tfsr/digital editions must be stripped from embed_matn_text."""
        raw_tfsr = "المقصد الأول في بيان معنى العبادة صفحة ١٣٧ وتحقيق التوحيد الخالص لله عز وجل."
        cleaned = mr.clean_for_embed(raw_tfsr, science="tafsir")
        self.assertNotIn("صفحة ١٣٧", cleaned)
        self.assertIn("وتحقيق التوحيد", cleaned)

    def test_05_approximate_hijri_decade_years(self):
        """Mistake #31: Approximate Hijri decade expressions ('سنة نيف وثلاثين وثلاثمائة', 'سنة بضع وعشرين ومائتين') must extract decade base and validate any year in [decade..decade+9]."""
        txt = "توفي رحمه الله ببغداد سنة نيف وثلاثين وثلاثمائة بعد أن صنف التصانيف الكثيرة."
        yrs = mr.extract_date_years_from_text(txt)
        self.assertIn(330, yrs)
        chron = mr.tag_chronology_source([{"hijri_year": 334, "event_tag": "وفاة المصنف ببغداد"}], txt, [], 1)
        self.assertEqual(chron[0]["year_source"], "text_explicit")

    def test_06_curly_brace_quran_verses(self):
        """Mistake #32: Curly-brace Quranic verses '{...}' in Shamela/akidsofi must be detected by P0_MISSED_QURAN_VERSES and fn_linker_v4."""
        raw_part = "وقد استدل المصنف بقوله تعالى: {ليس كمثله شيء وهو السميع البصير} على نفي المماثلة وإثبات السمع والبصر لله."
        raw_r = {
            "kalam_firaq": {
                "book_id": 9901,
                "meta": {"title": "الإبانة", "author": "الأشعري", "death": 324},
                "scope": {"parts_selected": 1, "chars_selected": len(raw_part)},
                "book_footnotes": [],
                "parts": [{"i": 1, "t": "باب", "pg": 1, "text": raw_part, "fn": []}],
            }
        }
        deep_missing_ev = {
            "deep_toc_passages": [
                {
                    "part": 1,
                    "sub_heading": "إثبات السمع والبصر ونفي المماثلة",
                    "anchor_start": "وقد استدل المصنف بقوله تعالى",
                    "summary": "يستدل المصنف بالآية الكريمة على إثبات صفتي السمع والبصر لله مع نفي مماثلة الحوادث.",
                    "topics": ["إثبات الصفات", "نفي التمثيل"],
                    "persons": [],
                    "places": [],
                    "chronology": [],
                    "evidences": [],  # Missing curly-brace verse!
                    "search_queries": ["ما دلالة الآية على إثبات السمع والبصر؟"],
                }
            ],
            "science_gems": [],
            "stories": [],
            "quotes": [],
        }
        _, rep = mr.audit_and_merge_round(99, raw_override=raw_r, deep_overrides={"kalam_firaq": deep_missing_ev})
        self.assertFalse(rep["passed"])
        self.assertTrue(any("P0_MISSED_QURAN_VERSES" in e for e in rep["p0_errors"]))

    def test_07_source_stripped_footnote_markers_and_poetic_double_asterisk(self):
        """Mistake #33 & #34: Source-stripped (¬١) markers when fn=[] and poetic '**' hemistichs must pass cleanly."""
        raw_part = (
            "قال الحافظ ابن رجب رحمه الله في شرح الحديث (¬١) وقد أنشد بعض السلف في هذا المعنى:\n"
            "إذا ما اعتقدت الحق فلا تعدلن به ** وإن خالفوا بالجهل ما جاء في الذكر"
        )
        # 1. Verify poetic hemistich split with '/' matching '**' in raw_part
        mode, s_pos, e_pos = mr.verify_and_locate_span_in_part(
            "إذا ما اعتقدت الحق فلا تعدلن به / وإن خالفوا بالجهل ما جاء في الذكر",
            raw_part,
            allow_elision=True,
        )
        self.assertEqual(mode, "hemistich")
        # 2. Verify fn_linker_v4 marks (¬١) as source_stripped_neg_marker when fn=[]
        parts_list = [{"i": 1, "t": "شرح", "text": raw_part, "fn": []}]
        res = fnl.link_book_footnotes_v4(128, "hadith_sharh", parts_list)
        self.assertEqual(res["token_classes"].get("source_stripped_neg_marker"), 1)
        self.assertEqual(res["p0_errors"], [])

    def test_08_multi_part_page_bare_footnote_guard(self):
        """Mistake #35: A part with 0 footnote tokens on a multi-part printed page must NOT steal parenthesized footnotes belonging to the next part."""
        parts_list = [
            {
                "i": 1,
                "t": "الجزء الأول",
                "pg": 362,
                "text": "هذا نص الجزء الأول في أول الصفحة وليس فيه أي إحالة هامشية.",
                "fn": [{"fn_id": "6736:p362:1", "page": "362", "marker": "١", "text": "(¬١) حاشية تتبع الجزء الثاني."}],
            },
            {
                "i": 2,
                "t": "الجزء الثاني",
                "pg": 362,
                "text": "هذا نص الجزء الثاني وفيه الإحالة الهامشية الصريحة (¬١) في آخره.",
                "fn": [{"fn_id": "6736:p362:1", "page": "362", "marker": "١", "text": "(¬١) حاشية تتبع الجزء الثاني."}],
            },
        ]
        passages_by_part = {
            1: [{"start_offset": 0, "end_offset": len(parts_list[0]["text"]), "fn_refs": []}],
            2: [{"start_offset": 0, "end_offset": len(parts_list[1]["text"]), "fn_refs": []}],
        }
        consumed, _, errs = mr.classify_and_link_book_footnotes(6736, "tarajim", parts_list, passages_by_part)
        self.assertEqual(errs, [])
        self.assertEqual(passages_by_part[1][0]["fn_refs"], [])
        self.assertEqual(passages_by_part[2][0]["fn_refs"], ["6736:p362:1"])


class TestLectureCourseAndGraphGates(unittest.TestCase):
    def test_09_ctc_word_alignment_no_cursor_jump_on_short_particles(self):
        """Mistake #36: Short particles ('من', 'في') after an unaligned word must NOT jump cursor 150 chars ahead into 'المؤمنين'."""
        raw_text = (
            "بسم الله الرحمن الرحيم الحمد لله رب العالمين والصلوات الزاكيات على نبينا محمد "
            "وعلى آله وصحبه أجمعين أما بعد فإن أصدق الحديث كتاب الله وخير الهدي هدي محمد "
            "صلى الله عليه وسلم وإن المؤمنين في خير عظيم."
        )
        with tempfile.NamedTemporaryFile("w", suffix=".align.json", delete=False, encoding="utf-8") as tf:
            # Word 'والصلاة' differs slightly from 'والصلوات', followed by short particle 'من' (hallucinated by ASR)
            # Old bug: 'من' matched inside 'المؤمنين' 140 chars later, skipping the entire middle of the lecture!
            json.dump(
                {
                    "w": [
                        ["بسم", 0.0, 0.5, 0],
                        ["الله", 0.5, 1.0, 0],
                        ["الرحمن", 1.0, 1.5, 0],
                        ["الرحيم", 1.5, 2.0, 0],
                        ["من", 2.1, 2.3, 0],  # ASR noise particle that does NOT occur locally
                        ["الحمد", 2.5, 3.0, 0],
                        ["لله", 3.0, 3.5, 0],
                        ["رب", 3.5, 4.0, 0],
                        ["العالمين", 4.0, 4.8, 0],
                    ]
                },
                tf,
                ensure_ascii=False,
            )
            aln_path = tf.name

        mapper = ml.build_char_to_time_mapper(raw_text, aln_path, 60.0)
        alhamd_pos = raw_text.find("الحمد لله رب العالمين")
        s_sec, e_sec, basis = mapper(alhamd_pos, alhamd_pos + len("الحمد لله رب العالمين"))
        self.assertEqual(basis, "ctc_forced_alignment")
        self.assertAlmostEqual(s_sec, 2.5, places=1)
        self.assertAlmostEqual(e_sec, 4.8, places=1)
        Path(aln_path).unlink(missing_ok=True)

    def test_10_course_atomic_blocks_and_uax9_bidi_neutral_prefix(self):
        """Mistake #37: find_atomic_blocks must protect display_math ($$...$$), callouts (> [!IMPORTANT]), and <details>, and UAX #9 P2 must catch backticked English at line start."""
        sample_md = (
            "مقدمة الفقرة الأولى حول حساب التدرجات.\n\n"
            "$$\n\\nabla_W L = \\delta a^T\n$$\n\n"
            "> [!IMPORTANT]\n> هذا تنبيه هندسي متصل لا يجوز شطره.\n\n"
            "<details>\n<summary>تفاصيل</summary>\nمحتوى مطوي\n</details>"
        )
        blocks = mc.find_atomic_blocks(sample_md)
        kinds = {b[2] for b in blocks}
        self.assertIn("display_math", kinds)
        self.assertIn("callout_blockquote", kinds)
        self.assertIn("details_block", kinds)

        # UAX #9 Rule P2: backticked or parenthesized English at line start before Arabic flips paragraph to LTR
        self.assertIsNotNone(mc.BARE_ENGLISH_LINE_START_RE.search("`Promise.all` يفشل فور رفض أي وعد برمجي."))
        self.assertIsNotNone(mc.BARE_ENGLISH_LINE_START_RE.search("- `iptables` يفحص القواعد خطياً."))
        self.assertIsNone(mc.BARE_ENGLISH_LINE_START_RE.search("إن دالة `Promise.all` تفشل فور رفض أي وعد برمجي."))

    def test_11_canonicalize_person_kunya_collision_guard(self):
        """Mistake #38: Generic kunyas ('أبو بكر', 'ابن عمر', 'عبد الله') must NEVER collide with 'أبو بكر البيهقي', 'أبو بكر بن العربي', or 'أبو عبد الله السنوسي'."""
        k_siddiq, _, _ = bcg.canonicalize_person("أبو بكر الصديق")
        k_bayhaqi, disp_bayhaqi, _ = bcg.canonicalize_person("الإمام أبو بكر البيهقي")
        k_ibn_arabi, disp_ibn_arabi, _ = bcg.canonicalize_person("القاضي أبو بكر بن العربي")
        k_abdullah, _, _ = bcg.canonicalize_person("عبد الله بن المبارك")
        k_sanusi, _, _ = bcg.canonicalize_person("الإمام أبو عبد الله السنوسي")

        self.assertNotEqual(k_bayhaqi, k_siddiq)
        self.assertNotEqual(k_ibn_arabi, k_siddiq)
        self.assertNotEqual(k_abdullah, k_sanusi)
        self.assertIn("البيهقي", disp_bayhaqi)
        self.assertIn("العربي", disp_ibn_arabi)

    def test_12_ctc_pure_v4_x_key_support(self):
        """ctc_pure_align.py v4.2 outputs timed words under 'x': [['بسم', 0.2, 0.54, 'a'], ...]. Must map as ctc_forced_alignment."""
        raw_text = "بسم الله الرحمن الرحيم قال المصنف رحمه الله والموجودات بالنسبة إلى المحل والمخصص أربعة أقسام."
        with tempfile.NamedTemporaryFile("w", suffix=".align.json", delete=False, encoding="utf-8") as tf:
            json.dump(
                {
                    "cov": 100.0,
                    "x": [
                        ["بسم", 0.2, 0.54, "a"],
                        ["الله", 0.56, 1.06, "a"],
                        ["الرحمن", 1.08, 1.42, "a"],
                        ["الرحيم", 1.44, 2.08, "a"],
                        ["قال", 8.22, 8.82, "a"],
                        ["المصنف", 8.84, 9.28, "a"],
                        ["رحمه", 9.3, 9.58, "a"],
                        ["الله", 9.62, 10.16, "a"],
                        ["والموجودات", 10.6, 11.86, "a"],
                    ],
                },
                tf,
                ensure_ascii=False,
            )
            aln_path = tf.name

        mapper = ml.build_char_to_time_mapper(raw_text, aln_path, 2650.0)
        qal_pos = raw_text.find("قال المصنف رحمه الله")
        s_sec, e_sec, basis = mapper(qal_pos, qal_pos + len("قال المصنف رحمه الله"))
        self.assertEqual(basis, "ctc_forced_alignment")
        self.assertAlmostEqual(s_sec, 8.22, places=2)
        self.assertAlmostEqual(e_sec, 10.16, places=2)
        Path(aln_path).unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)

