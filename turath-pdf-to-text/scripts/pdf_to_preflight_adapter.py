#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pdf_to_preflight_adapter.py — المحول المباشر الحرفي (Layer 1 -> Layer 2 Pre-Flight v4 Adapter)
بين مخرجات `turath-pdf-to-text` (`pages/pNNNN.json` + `.txt`) ومحرك `manifest_v4.py` و`fn_linker_v4.py`
في مهارة `turath-deep-indexing`.

الوظائف الهندسية الحتمية:
  1. يقرأ مخرجات الاستخراج البصري الحرفي (`pages/pNNNN.json` أو ملف الكتاب المجمع `<slug>.json`)
     ويضمن توليد الملفات النصية الرديفة `pages/pNNNN.txt`.
  2. يولّد ملف المتن الموحد الصافي `book_matn.txt` المعلّم بعلامات الصفحات المعيارية `[ص: N]`
     وعلامات الهوامش الجانبية `[هامش جانبي — ص N]` (بما في ذلك المتون العمودية المدارة 90° في حواشي الجداول الأزهرية).
  3. يفصل الحواشي السفلية في ملف مهيكل `footnotes.json`، ويولّد سجل الصفحات الاستباقي `pages_preflight.json`.
  4. يبني هيكل اللقطة المصدرية القياسي الذي يستقبله `manifest_v4.py` و`fn_linker_v4.py` مباشرةً:
     - `<out_dir>/source_snapshots/<book_id>/toc.json`
     - `<out_dir>/source_snapshots/<book_id>/0000.json` .. `0NNN.json`
     - `<out_dir>/preflight_r4_to_r10_report.json`
  5. ينفّذ بوابة التحقق الصارم من عدم ضياع أي حرف (`100% Zero-Loss Check`) عبر مطابقة عدد المحارف
     والبصمة التشفيرية `SHA-256` والاحتواء الحرفي التام للمتن والهامش الجانبي والحواشي السفلية.
  6. يدعم استدعاء `manifest_v4.py` و`fn_linker_v4.py` مباشرةً للتحقق من جاهزية المخرجات لمرحلة `Pre-Flight v4`
     وتوليد تقرير التوافق الشامل `adapter_manifest.json`.
"""
import argparse
import glob
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from agy_pdf_to_text import format_page_verbatim_txt, normalize_arabic_output  # noqa: E402

DEFAULT_DEEP_INDEXING_SCRIPTS = "/Users/macm1pro/REPOS/SKILLS/turath-deep-indexing/scripts"

AR_TO_ASCII_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
TASHKEEL_RE = re.compile(r"[\u0617-\u061A\u064B-\u065F\u0670\u0640]")

# أنماط العناوين التراثية لتقطيع الأجزاء مع الحفاظ الحرفي 100% على سطر العنوان داخل المتن
CHAPTER_HEADING_RE = re.compile(
    r"^(?:\[[^\]]{2,80}\](?:\s*[\(\[][٠-٩0-9]{1,2}[\)\]])?|"
    r"(?:كتاب|الكتاب|باب|الباب|فصل|الفصل|مسألة|المسألة|مبحث|المبحث|مطلب|المطلب|فرع|الفرع|"
    r"قاعدة|القاعدة|تنبيه|التنبيه|خاتمة|الخاتمة|تتمة|القول في|القسم|حاشية)\b[^\n]{0,90})$"
)

# الكلمات التي قد يصنفها manifest_v4.py كمقدمة محقق إذا وُضعت عنواناً مستقلاً للجزء
EDITOR_HEADING_GUARD_RE = re.compile(
    r"(?:مقدمة\s+(?:التحقيق|المحقق|الناشر|الطبعة|الطبعه|وزارة|المعتني|الدراسة)|كلمة\s+(?:المحقق|الناشر)|تقديم\s+بقلم|"
    r"ترجمة\s+(?:المصنف|المؤلف|الشارح)|التعريف\s+بالم|تعريف\s+بالإمام|عمل\s+المحقق|منهج(?:ي|نا)?\s+في\s+التحقيق|"
    r"وصف\s+(?:النسخ|الأصول|المخطوط)|نماذج\s+من|مخطوطات\s+الكتاب|دراسة\s+الكتاب|فهرس|ثبت\s+المصادر|قائمة\s+المصادر|"
    r"المصادر\s+والمراجع|^المقدمات$|^مصادره$|^منهجه$|^أهميته$|^المؤلف$)"
)

PAGE_MARKER_LINE_RE = re.compile(r"^\[ص:\s*[^\]]+\]\s*$", re.M)
MARGIN_MARKER_LINE_RE = re.compile(r"^\[هامش جانبي — ص\s*[^\]]+\]\s*$", re.M)


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha16(text: str) -> str:
    return sha256_hex(text)[:16]


def parse_printed_page_int(printed_page: str, fallback_int: int, prev_pg_int: int) -> int:
    """
    يحول رقم الصفحة المطبوع إلى عدد صحيح رتيب التزايد (Strictly Increasing Integer)
    لضمان عدم تصادم مفاتيح الصفحات في `fn_linker_v4.py` ولضمان عمل `next_part_pg_map` في `manifest_v4.py`.
    """
    s = (printed_page or "").translate(AR_TO_ASCII_DIGITS)
    m = re.search(r"(\d+)", s)
    cand = int(m.group(1)) if m else fallback_int
    if cand <= prev_pg_int:
        cand = prev_pg_int + 1
    return max(1, cand)


def parse_footnote_lines_verbatim(footnotes_raw: str, pdf_page: int, printed_page: str, pg_int: int, book_id: int, juz: int = 1) -> list[dict]:
    """
    يحلل أسطر الحاشية السفلية إلى سجلات مهيكلة مع الحفاظ الكامل على النص الحرفي لكل حاشية.
    يدعم الصيغ: (١) ، [١] ، ١ - ، ١. ، (*) ، والأسطر المكملة.
    """
    if not footnotes_raw or not footnotes_raw.strip():
        return []
    head_re = re.compile(
        r"^\s*(?:\(¬([٠-٩0-9]+)\)|\(([٠-٩0-9]+|\*+)\)|\[([٠-٩0-9]+)\]|([٠-٩0-9]+)\s*[-–—.)]|([٠-٩0-9]{1,3})\s+(?=[^\s\-–]))\s*(.*)$"
    )
    entries = []
    for raw_ln in footnotes_raw.splitlines():
        ln = raw_ln.strip()
        if not ln:
            continue
        m = head_re.match(ln)
        if m:
            marker_str = m.group(1) or m.group(2) or m.group(3) or m.group(4) or m.group(5)
            body = m.group(6).strip()
            ascii_m = marker_str.translate(AR_TO_ASCII_DIGITS)
            val = int(ascii_m) if ascii_m.isdigit() else marker_str
            entries.append({
                "val": val,
                "marker": marker_str,
                "text": ln,
                "body": body,
                "pdf_page": pdf_page,
                "printed_page": printed_page,
                "page": pg_int,
                "j": juz,
            })
        elif entries:
            entries[-1]["text"] += " / " + ln
            entries[-1]["body"] += " / " + ln
        else:
            entries.append({
                "val": None,
                "marker": "",
                "text": ln,
                "body": ln,
                "pdf_page": pdf_page,
                "printed_page": printed_page,
                "page": pg_int,
                "j": juz,
                "orphan_head": True,
            })
    for seq, e in enumerate(entries, 1):
        e["seq_in_page"] = seq
        e["fn_id"] = f"{book_id}:j{juz}:p{pg_int}:{seq}"
    return entries


def is_candidate_heading_line(line: str) -> tuple[bool, int, str]:
    """
    يفحص ما إذا كان السطر عنوان باب/فصل يصلح كبداية جزء هيكلي دون حذف السطر من المتن.
    يرجع (is_heading, level, clean_heading_title).
    """
    s = line.strip()
    if not s or len(s) > 110:
        return False, 0, ""
    if s.startswith(("[ص:", "[هامش جانبي", "﴿", "«", "---")):
        return False, 0, ""
    core = re.sub(r"\s*[\(\[][٠-٩0-9]{1,2}[\)\]]\s*$", "", s).strip()
    words = core.split()
    if not (1 <= len(words) <= 14):
        return False, 0, ""
    if re.search(r"[.؟!؛،]\s*$", core):
        return False, 0, ""
    if not CHAPTER_HEADING_RE.match(s):
        return False, 0, ""
    norm_core = TASHKEEL_RE.sub("", core).strip()
    if EDITOR_HEADING_GUARD_RE.search(norm_core):
        return False, 0, ""
    if re.match(r"^(?:كتاب|الكتاب)\b", norm_core):
        return True, 1, core
    if re.match(r"^(?:باب|الباب|القسم|القول في|حاشية)\b", norm_core) or (core.startswith("[") and core.endswith("]")):
        return True, 2, core.strip("[]").strip() or core
    return True, 3, core


def count_arabic_words(text: str) -> int:
    stripped = PAGE_MARKER_LINE_RE.sub("", text)
    stripped = MARGIN_MARKER_LINE_RE.sub("", stripped)
    return len(re.findall(r"[\u0621-\u064A]+", stripped))


def strip_adapter_structural_markers(text: str) -> str:
    """
    يزيل فقط أسطر علامات الصفحات [ص: ...] وأسطر رؤوس الهوامش الجانبية [هامش جانبي — ص ...]
    التي أضافها المحول، ليُفحص تطابق المتن والهامش الحرفي 100% مع الأصل.
    """
    lines = []
    for ln in text.splitlines():
        s = ln.strip()
        if not s:
            continue
        if PAGE_MARKER_LINE_RE.match(s) or MARGIN_MARKER_LINE_RE.match(s):
            continue
        lines.append(s)
    return "\n".join(lines)


def load_pages_from_input(input_path: str) -> tuple[list[dict], str, str | None]:
    """
    يحمّل صفحات الكتاب المستخرجة من مجلد يحتوي `pages/p*.json` أو من ملف `<slug>.json` مباشر.
    يرجع (pages_list, book_slug, pages_dir_or_none).
    """
    abs_in = os.path.abspath(input_path)
    if os.path.isfile(abs_in) and abs_in.endswith(".json"):
        with open(abs_in, "r", encoding="utf-8") as f:
            doc = json.load(f)
        if "pages" in doc and isinstance(doc["pages"], list):
            slug = doc.get("book_slug") or os.path.splitext(os.path.basename(abs_in))[0]
            return doc["pages"], slug, None
        raise ValueError(f"ملف JSON لا يحتوي مصفوفة pages: {abs_in}")

    pages_dir = os.path.join(abs_in, "pages") if os.path.isdir(os.path.join(abs_in, "pages")) else abs_in
    pfiles = sorted(glob.glob(os.path.join(pages_dir, "p*.json")))
    if pfiles:
        pages = []
        for pf in pfiles:
            with open(pf, "r", encoding="utf-8") as f:
                pages.append(json.load(f))
        pages.sort(key=lambda x: x.get("pdf_page", 0))
        slug = os.path.basename(abs_in.rstrip("/"))
        if slug == "pages":
            slug = os.path.basename(os.path.dirname(abs_in.rstrip("/")))
        return pages, slug, pages_dir

    cand_jsons = [
        p for p in glob.glob(os.path.join(abs_in, "*.json"))
        if not p.endswith(("gate_report.json", "toc.json", "adapter_manifest.json", "footnotes.json", "pages_preflight.json"))
    ]
    for cj in cand_jsons:
        with open(cj, "r", encoding="utf-8") as f:
            doc = json.load(f)
        if isinstance(doc, dict) and isinstance(doc.get("pages"), list):
            slug = doc.get("book_slug") or os.path.splitext(os.path.basename(cj))[0]
            return doc["pages"], slug, None

    raise FileNotFoundError(f"لم يُعثر على ملفات pages/p*.json في المسار: {abs_in}")


def convert_pdf_output_to_preflight(
    input_path: str,
    out_dir: str,
    book_id: int = 9001,
    science: str = "fiqh",
    round_num: int = 1,
    title: str = "",
    author: str = "مؤلف تراثي",
    death: str = "750",
    juz: int = 1,
    run_manifest_v4: bool = True,
    deep_indexing_scripts_dir: str = DEFAULT_DEEP_INDEXING_SCRIPTS,
) -> dict:
    """
    الدالة المركزية لتحويل مخرجات `turath-pdf-to-text` إلى حزمة مدخلات `Pre-Flight v4`
    مع بوابة `100% Zero-Loss Check` واستدعاء `manifest_v4.py` و`fn_linker_v4.py`.
    """
    raw_pages, book_slug, src_pages_dir = load_pages_from_input(input_path)
    out_dir_abs = os.path.abspath(out_dir)
    os.makedirs(out_dir_abs, exist_ok=True)
    pages_txt_dir = os.path.join(out_dir_abs, "pages_txt")
    os.makedirs(pages_txt_dir, exist_ok=True)

    pages_preflight = []
    source_matn_lines_all = []
    source_margin_lines_all = []
    source_fn_blocks_by_page = {}
    margin_notes_by_page = {}
    parsed_footnotes_all = []
    book_matn_page_blocks = []

    prev_pg_int = 0
    inferred_first_heading = ""

    # 1. استخلاص وتطبيع الصفحات وبناء book_matn.txt وpages_preflight.json وfootnotes.json
    for idx, p in enumerate(raw_pages):
        pdf_page = int(p.get("pdf_page", idx + 1))
        tag = p.get("tag") or f"p{pdf_page:04d}"
        layout = p.get("layout", "standard_single_col")

        if layout == "blank_or_sparse":
            pages_preflight.append({
                "pdf_page": pdf_page,
                "tag": tag,
                "layout": "blank_or_sparse",
                "printed_page": "",
                "page_int": None,
                "page_marker": "",
                "running_header": "",
                "matn": "",
                "margin_notes": "",
                "footnotes_raw": "",
                "footnotes_parsed": [],
                "char_counts": {"matn": 0, "margin_notes": 0, "footnotes": 0},
            })
            continue

        ext = p.get("extracted") or {}
        printed_page, _ = normalize_arabic_output(ext.get("printed_page", ""))
        running_header, _ = normalize_arabic_output(ext.get("running_header", ""))
        matn, _ = normalize_arabic_output(ext.get("matn", ""))
        margin_notes, _ = normalize_arabic_output(ext.get("margin_notes", ""))
        footnotes_raw, _ = normalize_arabic_output(ext.get("footnotes", ""))

        ext["printed_page"] = printed_page
        ext["running_header"] = running_header
        ext["matn"] = matn
        ext["margin_notes"] = margin_notes
        ext["footnotes"] = footnotes_raw

        pg_int = parse_printed_page_int(printed_page, pdf_page, prev_pg_int)
        prev_pg_int = pg_int
        pg_label = printed_page or str(pg_int)
        page_marker = f"[ص: {pg_label}]"

        # حفظ النسخة النصية الصافية للصفحة (pNNNN.txt)
        page_txt_content = format_page_verbatim_txt(p)
        with open(os.path.join(pages_txt_dir, f"{tag}.txt"), "w", encoding="utf-8") as f:
            f.write(page_txt_content)
        if src_pages_dir and os.path.isdir(src_pages_dir):
            try:
                with open(os.path.join(src_pages_dir, f"{tag}.txt"), "w", encoding="utf-8") as f:
                    f.write(page_txt_content)
            except OSError:
                pass

        for ln in matn.splitlines():
            if ln.strip():
                source_matn_lines_all.append(ln.strip())
                if not inferred_first_heading:
                    is_h, _, h_title = is_candidate_heading_line(ln.strip())
                    if is_h:
                        inferred_first_heading = h_title

        for ln in margin_notes.splitlines():
            if ln.strip():
                source_margin_lines_all.append(ln.strip())

        if margin_notes:
            margin_notes_by_page[str(pg_int)] = margin_notes

        fn_parsed = parse_footnote_lines_verbatim(footnotes_raw, pdf_page, pg_label, pg_int, book_id, juz=juz)
        if footnotes_raw:
            source_fn_blocks_by_page[str(pg_int)] = footnotes_raw
            parsed_footnotes_all.extend(fn_parsed)

        # بناء كتلة الصفحة في book_matn.txt
        p_blocks = [page_marker]
        if matn:
            p_blocks.append(matn)
        if margin_notes:
            p_blocks.append(f"[هامش جانبي — ص {pg_label}]\n{margin_notes}")
        book_matn_page_blocks.append("\n".join(p_blocks))

        pages_preflight.append({
            "pdf_page": pdf_page,
            "tag": tag,
            "layout": layout,
            "printed_page": pg_label,
            "page_int": pg_int,
            "page_marker": page_marker,
            "running_header": running_header,
            "matn": matn,
            "margin_notes": margin_notes,
            "footnotes_raw": footnotes_raw,
            "footnotes_parsed": fn_parsed,
            "char_counts": {
                "matn": len(matn),
                "margin_notes": len(margin_notes),
                "footnotes": len(footnotes_raw),
            },
        })

    effective_title = title.strip() or inferred_first_heading or f"كتاب {book_slug}"
    if EDITOR_HEADING_GUARD_RE.search(TASHKEEL_RE.sub("", effective_title)):
        effective_title = f"متن {effective_title}"

    # 2. تقطيع الصفحات إلى أجزاء هيكلية (0000.json .. 0NNN.json) بدون ضياع أي حرف
    # ملاحظة حاسمة: نحافظ على سطر العنوان داخل حقل text أيضاً لضمان بقاء أي إحالة حاشية (١) في العنوان قابلة للربط في fn_linker_v4
    raw_segments = []
    cur_seg = {
        "title": f"صدر الكتاب — {effective_title}",
        "level": 1,
        "pg_start": pages_preflight[0]["page_int"] if pages_preflight else 1,
        "lines": [],
        "pages_touched": [],
    }

    for pg_rec in pages_preflight:
        if pg_rec["layout"] == "blank_or_sparse":
            continue
        pg_int = pg_rec["page_int"]
        pg_label = pg_rec["printed_page"]
        matn_lines = [ln.strip() for ln in pg_rec["matn"].splitlines() if ln.strip()]

        # وضع علامة الصفحة [ص: N] في مطلع الصفحة
        if cur_seg["pg_start"] is None:
            cur_seg["pg_start"] = pg_int
        cur_seg["lines"].append(pg_rec["page_marker"])
        if pg_int not in cur_seg["pages_touched"]:
            cur_seg["pages_touched"].append(pg_int)

        for ln in matn_lines:
            is_h, h_lvl, h_clean = is_candidate_heading_line(ln)
            if is_h:
                cur_words = count_arabic_words("\n".join(cur_seg["lines"]))
                if cur_words >= 18:
                    raw_segments.append(cur_seg)
                    cur_seg = {
                        "title": h_clean,
                        "level": h_lvl,
                        "pg_start": pg_int,
                        "lines": [ln],
                        "pages_touched": [pg_int],
                    }
                    continue
                elif cur_seg["title"].startswith("صدر الكتاب"):
                    cur_seg["title"] = h_clean
                    cur_seg["level"] = h_lvl
                else:
                    cur_seg["title"] = f"{cur_seg['title']} — {h_clean}"
            cur_seg["lines"].append(ln)
            if pg_int not in cur_seg["pages_touched"]:
                cur_seg["pages_touched"].append(pg_int)

        if pg_rec["margin_notes"]:
            cur_seg["lines"].append(f"[هامش جانبي — ص {pg_label}]")
            for mln in pg_rec["margin_notes"].splitlines():
                if mln.strip():
                    cur_seg["lines"].append(mln.strip())
            if pg_int not in cur_seg["pages_touched"]:
                cur_seg["pages_touched"].append(pg_int)

    if cur_seg["lines"]:
        raw_segments.append(cur_seg)

    # دمج أي جزء أخير قصير جداً (< 12 كلمة) في الجزء السابق له لمنع تصنيفه كـ heading_only في manifest_v4.py
    if len(raw_segments) > 1 and count_arabic_words("\n".join(raw_segments[-1]["lines"])) < 12:
        tail_seg = raw_segments.pop()
        raw_segments[-1]["lines"].extend(tail_seg["lines"])
        for pt_pg in tail_seg["pages_touched"]:
            if pt_pg not in raw_segments[-1]["pages_touched"]:
                raw_segments[-1]["pages_touched"].append(pt_pg)

    # 3. كتابة الملفات الموحدة (book_matn.txt, footnotes.json, pages_preflight.json, toc.json)
    book_matn_txt = "\n\n".join(book_matn_page_blocks) + ("\n" if book_matn_page_blocks else "")
    book_matn_path = os.path.join(out_dir_abs, "book_matn.txt")
    with open(book_matn_path, "w", encoding="utf-8") as f:
        f.write(book_matn_txt)

    footnotes_payload = {
        "book_id": book_id,
        "book_slug": book_slug,
        "title": effective_title,
        "total_pages_with_footnotes": len(source_fn_blocks_by_page),
        "total_pages_with_margin_notes": len(margin_notes_by_page),
        "total_footnotes_count": len(parsed_footnotes_all),
        "raw_by_page": source_fn_blocks_by_page,
        "margin_notes_by_page": margin_notes_by_page,
        "footnotes": parsed_footnotes_all,
    }
    footnotes_json_path = os.path.join(out_dir_abs, "footnotes.json")
    with open(footnotes_json_path, "w", encoding="utf-8") as f:
        json.dump(footnotes_payload, f, ensure_ascii=False, indent=2)

    pages_preflight_payload = {
        "book_id": book_id,
        "book_slug": book_slug,
        "title": effective_title,
        "author": author,
        "death": str(death),
        "total_pages": len(pages_preflight),
        "pages": pages_preflight,
    }
    pages_preflight_path = os.path.join(out_dir_abs, "pages_preflight.json")
    with open(pages_preflight_path, "w", encoding="utf-8") as f:
        json.dump(pages_preflight_payload, f, ensure_ascii=False, indent=2)

    # 4. بناء source_snapshots/<book_id>/toc.json و 0000.json .. 0NNN.json لـ manifest_v4.py و fn_linker_v4.py
    snapshot_book_dir = os.path.join(out_dir_abs, "source_snapshots", str(book_id))
    os.makedirs(snapshot_book_dir, exist_ok=True)
    for old_f in glob.glob(os.path.join(snapshot_book_dir, "*.json")):
        os.remove(old_f)

    toc_entries = []
    snapshot_parts = []
    for idx_seg, seg in enumerate(raw_segments):
        part_text = "\n".join(seg["lines"]).strip()
        part_fn = {}
        part_margins = {}
        for pg_int in seg["pages_touched"]:
            pg_key = str(pg_int)
            if pg_key in source_fn_blocks_by_page:
                part_fn[pg_key] = source_fn_blocks_by_page[pg_key]
            if pg_key in margin_notes_by_page:
                part_margins[pg_key] = margin_notes_by_page[pg_key]

        part_obj = {
            "i": idx_seg,
            "t": seg["title"],
            "d": seg["level"],
            "pg": seg["pg_start"] or 1,
            "j": juz,
            "b": 1,
            "text": part_text,
            "fn": part_fn,
            "margin_notes": part_margins,
        }
        snapshot_parts.append(part_obj)
        part_filename = os.path.join(snapshot_book_dir, f"{idx_seg:04d}.json")
        with open(part_filename, "w", encoding="utf-8") as f:
            json.dump(part_obj, f, ensure_ascii=False, indent=2)

        toc_entries.append({
            "i": idx_seg,
            "t": seg["title"],
            "d": seg["level"],
            "pg": seg["pg_start"] or 1,
            "j": juz,
        })

    toc_payload = {
        "id": book_id,
        "title": effective_title,
        "author": author,
        "death": str(death),
        "toc": toc_entries,
    }
    snap_toc_path = os.path.join(snapshot_book_dir, "toc.json")
    with open(snap_toc_path, "w", encoding="utf-8") as f:
        json.dump(toc_payload, f, ensure_ascii=False, indent=2)
    root_toc_path = os.path.join(out_dir_abs, "toc.json")
    with open(root_toc_path, "w", encoding="utf-8") as f:
        json.dump(toc_payload, f, ensure_ascii=False, indent=2)

    preflight_report_payload = {
        "schema_version": "v4.1",
        "generated_by": "turath-pdf-to-text/scripts/pdf_to_preflight_adapter.py",
        "rounds_plan": {
            f"round_{round_num}": [
                {
                    "book_id": book_id,
                    "science": science,
                    "title": effective_title,
                    "author": author,
                }
            ]
        },
    }
    preflight_report_path = os.path.join(out_dir_abs, "preflight_r4_to_r10_report.json")
    with open(preflight_report_path, "w", encoding="utf-8") as f:
        json.dump(preflight_report_payload, f, ensure_ascii=False, indent=2)

    # 5. فحص الحفاظ الحرفي التام (100% Zero-Loss Check)
    zero_loss_report = verify_zero_loss(
        pages_preflight=pages_preflight,
        book_matn_txt=book_matn_txt,
        footnotes_payload=footnotes_payload,
        snapshot_parts=snapshot_parts,
    )

    # 6. استدعاء manifest_v4.py و fn_linker_v4.py للتحقق من الجاهزية الكاملة لمرحلة Pre-Flight v4
    manifest_v4_verification = {
        "executed": False,
        "passed": True,
        "errors": [],
    }
    manifest_script = os.path.join(deep_indexing_scripts_dir, "manifest_v4.py")
    if run_manifest_v4 and os.path.isfile(manifest_script):
        manifest_v4_verification = run_manifest_v4_check(
            out_dir_abs=out_dir_abs,
            deep_indexing_scripts_dir=deep_indexing_scripts_dir,
            round_num=round_num,
            science=science,
            book_id=book_id,
            expected_footnotes_count=len(parsed_footnotes_all),
        )

    all_passed = bool(zero_loss_report["passed"] and manifest_v4_verification["passed"])
    adapter_manifest = {
        "schema": "turath_pdf_to_preflight_adapter_v2.0",
        "status": "PASS" if all_passed else "FAIL",
        "book_id": book_id,
        "book_slug": book_slug,
        "science": science,
        "round": round_num,
        "title": effective_title,
        "author": author,
        "death": str(death),
        "total_pages": len(pages_preflight),
        "non_blank_pages": sum(1 for p in pages_preflight if p["layout"] != "blank_or_sparse"),
        "framed_hashiya_pages": sum(1 for p in pages_preflight if p["layout"] == "framed_hashiya"),
        "total_parts_built": len(snapshot_parts),
        "total_footnotes_count": len(parsed_footnotes_all),
        "files_generated": {
            "book_matn_txt": book_matn_path,
            "footnotes_json": footnotes_json_path,
            "pages_preflight_json": pages_preflight_path,
            "toc_json": root_toc_path,
            "snapshot_dir": snapshot_book_dir,
            "preflight_report_json": preflight_report_path,
        },
        "zero_loss_check": zero_loss_report,
        "manifest_v4_verification": manifest_v4_verification,
    }
    adapter_manifest_path = os.path.join(out_dir_abs, "adapter_manifest.json")
    with open(adapter_manifest_path, "w", encoding="utf-8") as f:
        json.dump(adapter_manifest, f, ensure_ascii=False, indent=2)

    return adapter_manifest


def verify_zero_loss(
    pages_preflight: list[dict],
    book_matn_txt: str,
    footnotes_payload: dict,
    snapshot_parts: list[dict],
) -> dict:
    """
    يتحقق حسابياً وتشفيرياً (SHA-256 + Substring + Char Counts) من عدم ضياع أي حرف (0 Loss)
    من المتن الأصلي أو الهوامش الجانبية أو الحواشي السفلية عبر جميع ملفات المخرجات.
    """
    errors = []
    src_body_lines = []
    src_matn_chars = 0
    src_margin_chars = 0
    src_fn_chars = 0

    concat_parts_text = "\n\n".join(p["text"] for p in snapshot_parts)
    merged_parts_fn_by_page = {}
    for p in snapshot_parts:
        for pg_k, fn_v in (p.get("fn") or {}).items():
            if pg_k not in merged_parts_fn_by_page:
                merged_parts_fn_by_page[pg_k] = fn_v

    for pg in pages_preflight:
        if pg["layout"] == "blank_or_sparse":
            continue
        p_num = pg["pdf_page"]
        pg_key = str(pg["page_int"])
        matn = pg["matn"]
        margin = pg["margin_notes"]
        fn_raw = pg["footnotes_raw"]

        src_matn_chars += len(matn)
        src_margin_chars += len(margin)
        src_fn_chars += len(fn_raw)

        for ln in matn.splitlines():
            if ln.strip():
                src_body_lines.append(ln.strip())
        for ln in margin.splitlines():
            if ln.strip():
                src_body_lines.append(ln.strip())

        if matn and matn not in book_matn_txt:
            errors.append(f"Page {p_num}: verbatim matn missing in book_matn.txt")
        if margin and margin not in book_matn_txt:
            errors.append(f"Page {p_num}: verbatim margin_notes missing in book_matn.txt")
        if fn_raw:
            if footnotes_payload["raw_by_page"].get(pg_key) != fn_raw:
                errors.append(f"Page {p_num}: footnotes mismatch in footnotes.json['raw_by_page']['{pg_key}']")
            if merged_parts_fn_by_page.get(pg_key) != fn_raw:
                errors.append(f"Page {p_num}: footnotes mismatch in snapshot_parts fn['{pg_key}']")

    expected_body_stream = "\n".join(src_body_lines)
    book_matn_body_stream = strip_adapter_structural_markers(book_matn_txt)
    parts_body_stream = strip_adapter_structural_markers(concat_parts_text)

    if book_matn_body_stream != expected_body_stream:
        errors.append(
            f"book_matn.txt body stream mismatch (expected {len(expected_body_stream)} chars, got {len(book_matn_body_stream)} chars)"
        )
    if parts_body_stream != expected_body_stream:
        errors.append(
            f"snapshot_parts text stream mismatch (expected {len(expected_body_stream)} chars, got {len(parts_body_stream)} chars)"
        )

    expected_fn_stream = "\n".join(
        pg["footnotes_raw"] for pg in pages_preflight if pg["layout"] != "blank_or_sparse" and pg["footnotes_raw"]
    )
    actual_fn_stream = "\n".join(
        footnotes_payload["raw_by_page"][str(pg["page_int"])]
        for pg in pages_preflight
        if pg["layout"] != "blank_or_sparse" and pg["footnotes_raw"] and str(pg["page_int"]) in footnotes_payload["raw_by_page"]
    )
    if actual_fn_stream != expected_fn_stream:
        errors.append(
            f"footnotes stream mismatch (expected {len(expected_fn_stream)} chars, got {len(actual_fn_stream)} chars)"
        )

    body_char_loss = abs(len(expected_body_stream) - len(parts_body_stream))
    fn_char_loss = abs(len(expected_fn_stream) - len(actual_fn_stream))

    return {
        "passed": len(errors) == 0 and body_char_loss == 0 and fn_char_loss == 0,
        "source_matn_chars": src_matn_chars,
        "source_margin_notes_chars": src_margin_chars,
        "source_footnotes_chars": src_fn_chars,
        "body_stream_chars": len(expected_body_stream),
        "book_matn_stripped_chars": len(book_matn_body_stream),
        "snapshot_parts_stripped_chars": len(parts_body_stream),
        "footnotes_stream_chars": len(actual_fn_stream),
        "body_char_loss": body_char_loss,
        "footnotes_char_loss": fn_char_loss,
        "retention_pct": 100.0 if (body_char_loss == 0 and fn_char_loss == 0) else 0.0,
        "source_body_sha256": sha16(expected_body_stream),
        "book_matn_body_sha256": sha16(book_matn_body_stream),
        "snapshot_parts_body_sha256": sha16(parts_body_stream),
        "source_footnotes_sha256": sha16(expected_fn_stream),
        "actual_footnotes_sha256": sha16(actual_fn_stream),
        "errors": errors,
    }


def run_manifest_v4_check(
    out_dir_abs: str,
    deep_indexing_scripts_dir: str,
    round_num: int,
    science: str,
    book_id: int,
    expected_footnotes_count: int,
) -> dict:
    """
    يشغّل `manifest_v4.py` فعلياً مع توجيه `TURATH_BOOKS_REPO` إلى مجلد مخرجات المحول،
    ويتحقق من نجاح بناء الـ Manifest وربط الحواشي عبر `fn_linker_v4.py` بصفر أخطاء.
    """
    manifest_script = os.path.join(deep_indexing_scripts_dir, "manifest_v4.py")
    env = dict(os.environ)
    env["TURATH_BOOKS_REPO"] = out_dir_abs

    res = subprocess.run(
        [sys.executable, manifest_script],
        cwd=out_dir_abs,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    errors = []
    if res.returncode != 0:
        errors.append(f"manifest_v4.py exited with code {res.returncode}: {res.stderr.strip()}")
        return {
            "executed": True,
            "passed": False,
            "rc": res.returncode,
            "errors": errors,
            "stdout": res.stdout,
            "stderr": res.stderr,
        }

    manifest_path = os.path.join(out_dir_abs, "round_manifest_r4_r10.json")
    raw_round_path = os.path.join(out_dir_abs, f"raw_round{round_num}_books.json")

    if not os.path.isfile(manifest_path):
        errors.append(f"Missing generated manifest file: {manifest_path}")
    if not os.path.isfile(raw_round_path):
        errors.append(f"Missing generated raw round file: {raw_round_path}")

    book_manifest = {}
    if not errors:
        with open(manifest_path, "r", encoding="utf-8") as f:
            m_all = json.load(f)
        book_manifest = m_all.get("books", {}).get(str(book_id), {})
        if not book_manifest:
            errors.append(f"Book {book_id} missing from round_manifest_r4_r10.json")
        else:
            if book_manifest.get("fn_unlinked_in_window_count", 0) != 0:
                errors.append(
                    f"Unlinked footnotes in window: {book_manifest.get('fn_unlinked_in_window_count')}"
                )
            if book_manifest.get("unclassified_tokens_count", 0) != 0:
                errors.append(
                    f"Unclassified tokens in window: {book_manifest.get('unclassified_tokens_count')}"
                )
            if book_manifest.get("acks", {}).get("orphan_fns"):
                errors.append(
                    f"Unexpected orphan footnotes in window: {book_manifest['acks']['orphan_fns']}"
                )
            if book_manifest.get("fn_linked_count", 0) != expected_footnotes_count:
                errors.append(
                    f"Expected {expected_footnotes_count} linked footnotes, got {book_manifest.get('fn_linked_count', 0)}"
                )

    return {
        "executed": True,
        "passed": len(errors) == 0,
        "rc": res.returncode,
        "manifest_path": manifest_path,
        "raw_round_path": raw_round_path,
        "book_manifest": book_manifest,
        "errors": errors,
    }


def main():
    parser = argparse.ArgumentParser(
        description="تحويل مخرجات turath-pdf-to-text (pages/pNNNN.json) إلى هيكل Pre-Flight v4 لـ manifest_v4.py و fn_linker_v4.py"
    )
    parser.add_argument("input_path", help="مجلد مخرجات الكتاب الذي يحوي pages/p*.json أو مسار ملف JSON مجمع")
    parser.add_argument("--out-dir", default="", help="مجلد حفظ مخرجات المحول (الافتراضي: <input_path>/preflight_v4)")
    parser.add_argument("--book-id", type=int, default=9001, help="معرف الكتاب الرقمي لـ manifest_v4.py (الافتراضي: 9001)")
    parser.add_argument("--science", default="fiqh", help="اسم العلم الشرعي (الافتراضي: fiqh)")
    parser.add_argument("--round", type=int, default=1, help="رقم الجولة في خطة Pre-Flight (الافتراضي: 1)")
    parser.add_argument("--title", default="", help="عنوان الكتاب التراثي")
    parser.add_argument("--author", default="مؤلف تراثي", help="اسم المؤلف")
    parser.add_argument("--death", default="750", help="سنة وفاة المؤلف بالهجري")
    parser.add_argument("--juz", type=int, default=1, help="رقم الجزء/المجلد (الافتراضي: 1)")
    parser.add_argument("--no-manifest-v4", action="store_true", help="تخطي استدعاء manifest_v4.py التلقائي")
    args = parser.parse_args()

    out_dir = args.out_dir or os.path.join(os.path.abspath(args.input_path), "preflight_v4")
    rep = convert_pdf_output_to_preflight(
        input_path=args.input_path,
        out_dir=out_dir,
        book_id=args.book_id,
        science=args.science,
        round_num=args.round,
        title=args.title,
        author=args.author,
        death=args.death,
        juz=args.juz,
        run_manifest_v4=not args.no_manifest_v4,
    )

    zl = rep["zero_loss_check"]
    mv4 = rep["manifest_v4_verification"]
    print(
        f"[{rep['status']}] كتاب={rep['title']} (id={rep['book_id']}) | صفحات={rep['non_blank_pages']} | "
        f"أجزاء={rep['total_parts_built']} | حواشٍ={rep['total_footnotes_count']}\n"
        f"  -> Zero-Loss Check : passed={zl['passed']} | retention={zl['retention_pct']}% "
        f"(body_loss={zl['body_char_loss']}, fn_loss={zl['footnotes_char_loss']})\n"
        f"  -> Manifest v4     : executed={mv4['executed']} | passed={mv4['passed']} | "
        f"linked_fns={mv4.get('book_manifest', {}).get('fn_linked_count', 0)}\n"
        f"  -> Adapter Manifest: {os.path.join(os.path.abspath(out_dir), 'adapter_manifest.json')}"
    )
    sys.exit(0 if rep["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()
