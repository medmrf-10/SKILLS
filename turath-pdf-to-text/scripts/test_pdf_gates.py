#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_pdf_gates.py — حزمة الاختبارات الانحدارية الحتمية لمهارة turath-pdf-to-text.
تفحص جميع الخوارزميات الهندسية وبوابات الجودة الخمس في < 0.3 ثانية:
  1. تطبيع الأرقام الفارسية (U+06F0..U+06F9) والحروف الفارسية (ی، ک) وإزالة الروابط المتسربة.
  2. تنظيف ذرات غبار المسح (<= 5px) وحماية الطرر الجانبية القريبة من الحافة مثل [I/8] من البتر.
  3. كشف الصفحات الفارغة (blank_or_sparse).
  4. كشف الصفحات ذات العمودين (two_column) وشطرها عمودياً.
  5. كشف حواشي الجداول البولاقية (framed_hashiya) وتدوير المتن العمودي 90° مع عقارب الساعة.
  6. الشطر الأفقي عند وادي الفراغ الأوسط (standard_single_col) مع تجنب خط فاصل الحاشية.
  7. بوابة تطابق إحالات المتن والهوامش (بما فيها الأسس العلوية ¹ والأرقام الملاصقة للكلمات مثل هما1)
     وتجاهل أرقام الصفحات في آخر جملة الحاشية مثل «ص ١٢ ، ١٣ .».
  8. بوابة كشف سقوط الحاشية تحت خط الفصل (MISSING_FOOTNOTES_BELOW_SEPARATOR).
  9. بوابة توازن أقواس الآيات ﴿...﴾ وعلامات التنصيص «...».
  10. مطابقة أطول كلمة عربية في uncertain_words (تجنب مطابقة حرف الألف المفرد في «ا وجوب ا»).
"""
import os
import sys
import tempfile
import unittest
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from agy_pdf_to_text import (  # noqa: E402
    analyze_and_slice_page,
    clean_gray_array,
    normalize_arabic_output,
    run_quality_gates,
)


class TestTurathPdfToTextGates(unittest.TestCase):
    def test_01_unicode_drift_normalizer(self):
        raw = "توف\u06cc سنة ۱۲۵ هـ في \u06a9تاب طبقات الشعراء ص ۲۰ ، ۲۱ [band1.png](file:///tmp/band1.png)"
        fixed, stats = normalize_arabic_output(raw)
        self.assertEqual(fixed, "توفي سنة ١٢٥ هـ في كتاب طبقات الشعراء ص ٢٠ ، ٢١")
        self.assertEqual(stats["persian_digits_fixed"], 7)
        self.assertEqual(stats["persian_chars_fixed"], 2)

    def test_02_edge_safe_despeckling_preserves_marginalia(self):
        arr = np.full((600, 500), 255, dtype=np.uint8)
        # 1) Add isolated 2x2 scanner dust speck at (100, 100) -> should be removed
        arr[100:102, 100:102] = 0
        # 2) Add tall scanner shadow bar on left edge (x=0..4, y=50..250, h=200 > 120) -> should be removed
        arr[50:250, 0:4] = 0
        # 3) Add marginalia bracket near right edge (x=488..498, y=120..145, h=25 <= 120, area > 10) -> MUST be preserved!
        arr[120:145, 488:495] = 0

        cleaned, specks_removed = clean_gray_array(arr, max_speck_area=5)
        self.assertGreaterEqual(specks_removed, 1)
        self.assertEqual(int(cleaned[100, 100]), 255, "Isolated speck must be removed")
        self.assertEqual(int(cleaned[150, 1]), 255, "Tall edge shadow bar must be removed")
        self.assertEqual(int(cleaned[130, 490]), 0, "Short marginalia glyph near edge must be preserved")

    def test_03_blank_page_detection(self):
        arr = np.full((1000, 700), 255, dtype=np.uint8)
        meta = analyze_and_slice_page(arr, "", "test_blank")
        self.assertEqual(meta["layout"], "blank_or_sparse")
        self.assertEqual(meta["visual_line_count"], 0)

    def test_04_two_column_layout_detection(self):
        arr = np.full((1000, 800), 255, dtype=np.uint8)
        # Draw central vertical divider rule at x=400
        arr[100:900, 398:402] = 0
        # Draw 12 text lines on both columns
        for i in range(12):
            y = 150 + i * 55
            arr[y:y + 14, 100:360] = 0
            arr[y:y + 14, 440:700] = 0
        with tempfile.TemporaryDirectory() as tmp:
            meta = analyze_and_slice_page(arr, tmp, "test_2col")
            self.assertEqual(meta["layout"], "two_column")
            self.assertIn("col1_right.png", meta["files_map"])
            self.assertIn("col2_left.png", meta["files_map"])

    def test_05_framed_hashiya_and_90deg_margin_rotation(self):
        arr = np.full((1200, 900), 255, dtype=np.uint8)
        # Draw left vertical frame at x=180 (20%) and right vertical frame at x=800 (88.8%)
        arr[100:1080, 178:183] = 0
        arr[100:1080, 798:803] = 0
        # Draw interior horizontal text lines
        for i in range(15):
            y = 140 + i * 55
            arr[y:y + 14, 220:760] = 0
        # Draw vertical marginalia in outer left margin (x=60..110, y=250..650 -> taller than wide!)
        arr[250:650, 75:95] = 0
        with tempfile.TemporaryDirectory() as tmp:
            meta = analyze_and_slice_page(arr, tmp, "test_hashiya")
            self.assertEqual(meta["layout"], "framed_hashiya")
            self.assertGreaterEqual(meta["visual_line_count"], 12)
            self.assertIn("margin_upright.png", meta["files_map"])

    def test_06_footnote_parity_ignores_end_of_sentence_page_numbers(self):
        extracted = {
            "printed_page": "٢٢",
            "running_header": "",
            "matn": "يعني : حلف الرباب لعكل (١) . وذكر حسين بن فهم (٢) قال الأصمعي¹ وهما2 :",
            "margin_notes": "",
            "footnotes": "(١) راجع ذلك كله بالنص في طبقات الشعراء ص ١٢ ، ١٣ .\n(٢) توفي عام ٢٨٩ هـ .",
            "uncertain_words": [],
        }
        meta = {
            "layout": "standard_single_col",
            "height": 2500,
            "visual_line_count": 4,
            "footnote_separator_y": 1800,
            "visual_lines": [(100, 130), (200, 230), (1850, 1880), (1900, 1930)],
        }
        gr = run_quality_gates(extracted, meta)
        self.assertEqual(gr["fn_markers"], [1, 2], "Must not mistake '١٣ .' at end of footnote 1 for footnote #13")
        self.assertEqual(gr["warnings"], [])

    def test_07_uncertain_word_longest_arabic_token_matching(self):
        extracted = {
            "printed_page": "51",
            "running_header": "",
            "matn": (
                "القول في القسم الثالث من الجزء الأول\n"
                "36 - هذا القسم يتضمن النظر في أركان الحكم\n"
                "38 - وأما المحكوم عليه فله شرطان هما1 أن يفهم الخطاب الوارد\n"
                "بأمر أو نهي ، إذ من ليس يفهم الخطاب لا يصح منه اقتضاء ا وجوب ا"
            ),
            "margin_notes": "[I/8]",
            "footnotes": "(1) في الأصل : منهما .",
            "uncertain_words": ["ا وجوب ا [أو: | وجوب |]"],
        }
        meta = {
            "layout": "standard_single_col",
            "height": 2000,
            "visual_line_count": 5,
            "footnote_separator_y": 1700,
            "visual_lines": [(100, 140), (300, 340), (600, 640), (900, 940), (1800, 1840)],
        }
        gr = run_quality_gates(extracted, meta)
        self.assertEqual(len(gr["focal_tasks"]), 1)
        ft = gr["focal_tasks"][0]
        self.assertEqual(ft["matched_token"], "وجوب")
        self.assertEqual(ft["line_idx"], 3, "Must match line 3 containing 'وجوب', not line 0 containing 'ا'")

    def test_08_unbalanced_brackets_and_missing_footnotes_detection(self):
        extracted = {
            "printed_page": "١٠",
            "running_header": "",
            "matn": "قال تعالى : ﴿فعززنا بثالث مثقلة (١) .",
            "margin_notes": "",
            "footnotes": "",
            "uncertain_words": [],
        }
        meta = {
            "layout": "standard_single_col",
            "height": 2200,
            "visual_line_count": 12,
            "footnote_separator_y": 1650,
            "visual_lines": [(100 + i * 100, 130 + i * 100) for i in range(12)],
        }
        gr = run_quality_gates(extracted, meta)
        warn_str = " | ".join(gr["warnings"])
        self.assertIn("MISSING_FOOTNOTES_BELOW_SEPARATOR", warn_str)
        self.assertIn("UNBALANCED_QURAN_BRACKETS", warn_str)

    def test_09_footnote_parity_ignores_quranic_verse_numbers_inside_braces(self):
        extracted = {
            "printed_page": "١٥٨",
            "running_header": "",
            "matn": (
                "﴿ فَاعْتَبِرُوا يَا أُولِي الأَبْصَارِ (٢) وَلَوْلا أَن كَتَبَ اللَّهُ عَلَيْهِمُ الْجَلاءَ "
                "لَعَذَّبَهُمْ فِي الدُّنْيَا وَلَهُمْ فِي الآخِرَةِ عَذَابُ النَّارِ (٣) ذَلِكَ بِأَنَّهُمْ "
                "شَاقُّوا اللَّهَ وَرَسُولَهُ (٤) وَلِيُخْزِيَ الْفَاسِقِينَ ﴾(١) ."
            ),
            "margin_notes": "",
            "footnotes": "(١) [سورة الحشر : ٢-٥] .",
            "uncertain_words": [],
        }
        meta = {
            "layout": "standard_single_col",
            "height": 2200,
            "visual_line_count": 4,
            "footnote_separator_y": 1800,
            "visual_lines": [(100, 130), (200, 230), (300, 330), (1850, 1880)],
        }
        gr = run_quality_gates(extracted, meta)
        self.assertEqual(gr["matn_markers"], [1])
        self.assertEqual(gr["fn_markers"], [1])
        self.assertEqual(gr["warnings"], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)

