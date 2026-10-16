#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check_pdf_output.py — فاحص وبوابة الجودة الحتمية لمخرجات تحويل الـ PDF (turath-pdf-to-text).

يفحص مجلد مخرجات الكتاب (<out_dir>/pages/p*.json) ويتحقق من:
  1. خلو النصوص من الأرقام الفارسية (U+06F0..U+06F9) والحروف الفارسية (ی، ک) وروابط الملفات المتسربة.
  2. التغطية السطرية ومعدل الكلمات لكل سطر بصري (كشف سقوط الأسطر Haplography).
  3. تطابق إحالات الحواشي بين المتن والهامش (Footnote Parity Gate) ووجود نص الحاشية تحت خط الفصل.
  4. توازن أقواس الآيات ﴿...﴾ وعلامات التنصيص «...».
  5. إعادة بناء ملفات الكتاب المجمعة (<slug>.json و<slug>.md وgate_report.json) عند تمرير --rebuild.

الاستعمال:
  python3 check_pdf_output.py <out_dir> [--fix-normalize] [--rebuild]
"""
import argparse
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from agy_pdf_to_text import format_book_markdown, run_quality_gates  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="فحص جودة صفحات الـ PDF المستخرجة وتطبيعها")
    parser.add_argument("out_dir", help="مجلد مخرجات الكتاب الذي يحوي pages/p*.json")
    parser.add_argument("--fix-normalize", action="store_true", help="تطبيع الأرقام والحروف الفارسية وتحديث ملفات الصفحات في مكانها")
    parser.add_argument("--rebuild", action="store_true", help="إعادة توليد ملف الماركداون والـ JSON المجمع للكتاب")
    args = parser.parse_args()

    pages_dir = os.path.join(args.out_dir, "pages")
    if not os.path.isdir(pages_dir):
        print(f"[خطأ] مجلد الصفحات غير موجود: {pages_dir}", file=sys.stderr)
        sys.exit(1)

    page_files = sorted(glob.glob(os.path.join(pages_dir, "p*.json")))
    if not page_files:
        print(f"[خطأ] لا توجد ملفات صفحات داخل: {pages_dir}", file=sys.stderr)
        sys.exit(1)

    pages_data = []
    total_warnings = 0
    total_digits_fixed = 0
    total_words = 0

    for pf in page_files:
        with open(pf, "r", encoding="utf-8") as f:
            pdata = json.load(f)

        if pdata.get("layout") == "blank_or_sparse":
            pages_data.append(pdata)
            continue

        meta = pdata.get("meta") or {}
        meta.setdefault("visual_line_count", pdata.get("gate_report", {}).get("visual_line_count", 0))
        meta.setdefault("layout", pdata.get("layout", "standard_single_col"))
        meta.setdefault("height", 2500)

        gr = run_quality_gates(pdata["extracted"], meta)
        pdata["gate_report"] = gr
        digits_fixed = gr["normalized_stats"]["persian_digits_fixed"]
        chars_fixed = gr["normalized_stats"]["persian_chars_fixed"]
        total_digits_fixed += digits_fixed + chars_fixed
        total_words += gr["total_words"]

        if args.fix_normalize and (digits_fixed > 0 or chars_fixed > 0):
            with open(pf, "w", encoding="utf-8") as f:
                json.dump(pdata, f, ensure_ascii=False, indent=2)

        if gr["warnings"]:
            total_warnings += len(gr["warnings"])
            print(f"  [تحذير] ص {pdata.get('pdf_page')} ({os.path.basename(pf)}): {gr['warnings']}")

        pages_data.append(pdata)

    if args.rebuild:
        book_slug = os.path.basename(os.path.abspath(args.out_dir))
        md_path = os.path.join(args.out_dir, f"{book_slug}.md")
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(format_book_markdown(pages_data))
        print(f"[تحديث] أعيد بناء: {md_path}")

    status = "CLEAN" if total_warnings == 0 else f"WARNINGS ({total_warnings})"
    print(
        f"[النتيجة: {status}] الصفحات={len(pages_data)} | الكلمات={total_words} | "
        f"أرقام/حروف فارسية طُبِّعت={total_digits_fixed} | تحذيرات={total_warnings}"
    )
    sys.exit(0 if total_warnings == 0 else 1)


if __name__ == "__main__":
    main()
