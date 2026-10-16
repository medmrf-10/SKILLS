#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_book_db.py — المحرك المهيكل لبناء قاعدة بيانات الكتاب التراثي (SQLite + FTS5)
والفهرس الشجري (TOC) ودمج الأبواب والفصول عبر الصفحات لمهارة turath-pdf-to-text.

يحوّل مخرجات الصفحات (<out_dir>/pages/p*.json أو <slug>.json) إلى حزمة تراثية متكاملة:
  1. <slug>.db       : قاعدة بيانات SQLite متوافقة مع عمليات turathmcp:
                       - جدول book_meta : بيانات الكتاب وإحصائياته
                       - جدول toc       : الفهرس الشجري (part_id, title, level, parent_id, path, start/end pages, word_count)
                       - جدول parts     : نصوص الأبواب والفصول متصلة السياق عبر الصفحات (text_continuous, text_clean, footnotes_scoped, summary)
                       - جدول pages     : الأرشيف الصفحي الكامل (matn, matn_reflowed, footnotes, margin_notes)
                       - جدول footnotes : جدول الحواشي المربوطة بسياقها في المتن (scoped_id, matn_context, status)
                       - فهارس FTS5     : بحث عربي فوري يتجاهل التشكيل ويوحد الهمزات ويوسع اللواصق (و، ف، ب، ك، ل، ال، ت*)
  2. toc.json        : الفهرس الشجري المهيكل بصيغة JSON
  3. <slug>.md       : النسخة المهيكلة بالأبواب والفصول (تبدأ بجدول الفهرس، وتصل الجمل المقطوعة عبر الصفحات مع وسم ⟦ص ...⟧ وتوحد أرقام الحواشي بوسم [ص.../ح...])
  4. <slug>_pages.md : الأرشيف الصفحي المطابق للمطبوع صفحة بصفحة للمراجعة البصرية
"""

import argparse
import glob
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone


# ==============================================================================
# 1. التطبيع الإملائي والبحث العربي المتقدم (Normalized & Clitic-Aware Search)
# ==============================================================================

TASHKEEL_RE = re.compile(r"[\u064B-\u065F\u0670\u0640]")


def normalize_arabic_search(text: str) -> str:
    """تطبيع النص العربي للبحث الفوري (إزالة التشكيل والتطويل، توحيد الهمزات والألف المقصورة والتاء المربوطة)."""
    if not text:
        return ""
    s = TASHKEEL_RE.sub("", text)
    s = re.sub(r"[أإآٱ]", "ا", s)
    s = re.sub(r"[ؤئ]", "ء", s)
    s = s.replace("ى", "ي").replace("ة", "ه")
    return s


def expand_arabic_query_terms(word: str) -> list:
    """
    توسيع الكلمة البحثية لتشمل اللواصق السابقة (و، ف، ب، ك، ل، ال، لل، س)
    وتحول التاء المربوطة إلى تاء مفتوحة عند الإضافة للضمائر (أئمة -> أئمتهم، شريعة -> شريعته).
    """
    w = normalize_arabic_search(word.strip())
    if not w:
        return []
    stems = {w}
    for pref in ["وال", "فال", "بال", "كال", "لل", "ال", "ول", "فل", "و", "ف", "ب", "ك", "ل", "س"]:
        if w.startswith(pref) and len(w) - len(pref) >= 3:
            stems.add(w[len(pref):])
    expanded = set()
    for st in stems:
        expanded.add(st)
        base_no_al = st[2:] if st.startswith("ال") and len(st) >= 5 else st
        expanded.add(base_no_al)
        expanded.add("ال" + base_no_al)
        for p in ["و", "ف", "ب", "ك", "ل", "س", "ول", "فل"]:
            expanded.add(p + base_no_al)
            expanded.add(p + "ال" + base_no_al)
        expanded.add("لل" + base_no_al)
        if base_no_al.endswith("ه") and len(base_no_al) >= 3:
            t_stem = base_no_al[:-1] + "ت*"
            expanded.add(t_stem)
            for p in ["و", "ف", "ب", "ك", "ل"]:
                expanded.add(p + t_stem)
        elif len(base_no_al) >= 4:
            expanded.add(base_no_al + "*")
    return sorted(expanded)


# ==============================================================================
# 2. الكاشف البنيوي للعناوين والشعر والفهرس الشجري (Method 9E+)
# ==============================================================================

HEADING_KEYWORDS_L1 = re.compile(r"^(?:كتاب|الكتاب|رسالة|الرسالة)\b")
HEADING_KEYWORDS_L2 = re.compile(r"^(?:باب|الباب|القول في|القسم|الجملة|المقصد)\b")
HEADING_KEYWORDS_L3 = re.compile(
    r"^(?:فصل|الفصل|مسألة|المسألة|مبحث|المبحث|مطلب|المطلب|فرع|الفرع|تنبيه|التنبيه|قاعدة|القاعدة|خاتمة|الخاتمة|تتمة|فائدة|عنوان الكتاب)\b"
)
RUNIN_HEADING_RE = re.compile(
    r"^((?:القسم|الباب|الفصل|المسألة|المبحث|المطلب|الفرع|التنبيه|المرتبة|النوع|الضرب)\s+"
    r"(?:الأول|الأوّل|الأوَّل|الثاني|الثالث|الرابع|الخامس|السادس|السابع|الثامن|التاسع|العاشر|الحادي|الثاني عشر|[٠-٩0-9]+)"
    r"(?:\s*:\s*[^،.:؛\n]{2,35})?)\s*[،:]\s+(.+)$"
)
NUMBERED_PARA_RE = re.compile(r"^([٠-٩0-9]{1,3})\s*[-–—]\s*(.+)$")

PARAGRAPH_STARTERS = (
    "أما بعد",
    "وذلك :",
    "وذلك أن",
    "ولما ",
    "ولهذا ",
    "وقد ",
    "فإن ",
    "فأعان الله",
    "وفي هؤلاء",
    "فتقدم ",
    "والله هو",
    "والسلام عليكم",
    "والحمد لله",
    "وفي يوم ",
    "قال ",
    "وقال ",
    "ثم ينقسم",
    "ثُمَّ ينقسم",
    "وهم يشبهون",
    "وأيضًا فإنه",
    "خطا الخط",
    "ثم فتح الله",
)


def is_poetry_line(line: str, prev_line: str = "") -> str:
    """
    يكتشف الأبيات الشعرية ذات الشطرين (سواء فُصلت بـ // أو بـ 3+ مسافات بين شطرين متوازنين،
    أو سُبقت بـ «قال الشاعر» / «أنشد») ويعيدها بصيغة موحدة «شطر ١ // شطر ٢»، أو سلسلة فارغة إن لم تكن شعرًا.
    """
    s = line.strip()
    if "//" in s and not s.startswith("http"):
        parts = [p.strip() for p in s.split("//") if p.strip()]
        if len(parts) == 2 and 2 <= len(parts[0].split()) <= 9 and 2 <= len(parts[1].split()) <= 9:
            return f"{parts[0]} // {parts[1]}"
    # فحص وجود فجوة من 3 مسافات فأكثر بين شطرين متوازنين
    m_gap = re.match(r"^(\S+(?:\s+\S+){2,7})\s{3,}(\S+(?:\s+\S+){2,7})$", s)
    if m_gap:
        return f"{m_gap.group(1).strip()} // {m_gap.group(2).strip()}"
    if prev_line and re.search(r"(?:قال الشاعر|قول الشاعر|أنشد|قوله\s*:)\s*$", prev_line.strip()):
        words = s.split()
        if 6 <= len(words) <= 12 and not s.endswith("."):
            mid = len(words) // 2
            return f"{' '.join(words[:mid])} // {' '.join(words[mid:])}"
    return ""


def parse_page_structure(matn: str, is_first_page: bool = False) -> tuple:
    """
    يحلل سطور المتن في الصفحة ليكتشف:
      1) العناوين المعقوفة متعددة الأسطر ويدمجها في عنوان واحد.
      2) العناوين المستقلة (Standalone Headings) بمستوياتها 1..3.
      3) العناوين المدمجة في صدر الفقرة (Run-in Headings).
      4) الأبيات الشعرية ذات الشطرين.
    """
    raw_lines = [ln for ln in (matn or "").splitlines() if ln.strip()]
    merged_lines = []
    i = 0
    while i < len(raw_lines):
        ln = raw_lines[i].strip()
        if ln.startswith("[") and "]" not in ln:
            buf = [ln]
            j = i + 1
            while j < len(raw_lines) and j - i <= 4:
                buf.append(raw_lines[j].strip())
                if "]" in raw_lines[j]:
                    break
                j += 1
            if j < len(raw_lines) and "]" in raw_lines[j] and sum(len(x.split()) for x in buf) <= 18:
                merged_lines.append(" ".join(buf))
                i = j + 1
                continue
        # نحتفظ بالمسافات الداخلية في السطر الأصلي لكشف فجوة شطري الشعر
        merged_lines.append(raw_lines[i].strip())
        i += 1

    structured_lines = []
    headings = []
    grammatical_binders = {
        "من", "في", "على", "إلى", "الى", "عن", "أن", "ان", "لا", "لم", "إلا", "الا", "رب", "بهذه", "دخل", "يمكن"
    }

    for idx, raw_ln in enumerate(merged_lines):
        prev_ln = merged_lines[idx - 1] if idx > 0 else ""
        poetry_norm = is_poetry_line(raw_ln, prev_ln)
        if poetry_norm:
            structured_lines.append({
                "text": f"«{poetry_norm}»",
                "is_heading": False,
                "is_poetry": True,
                "runin_heading": None,
                "runin_level": None,
                "level": None,
            })
            continue

        clean_ln = re.sub(r"^#+\s*", "", raw_ln).strip()
        clean_ln = re.sub(r"\s{2,}", " ", clean_ln)
        core_ln = re.sub(r"[\(\[]([٠-٩0-9]{1,2})[\)\]]", "", clean_ln).strip()
        words = core_ln.split()
        w_count = len(words)

        ends_with_stop = bool(re.search(r"[.:!؟،؛»﴾]\s*(?:[\(\[][٠-٩0-9]+[\)\]])?\s*$", clean_ln))
        is_salutation = any(
            clean_ln.startswith(p)
            for p in ["بسم الله الرحمن الرحيم", "الحمد لله", "والصلاة والسلام", "والسلام عليكم"]
        )

        m_runin = RUNIN_HEADING_RE.match(clean_ln)
        if m_runin and w_count > 6:
            runin_title = m_runin.group(1).strip()
            headings.append({
                "title": runin_title,
                "level": 3,
                "line_idx": idx,
                "kind": "run_in",
            })
            structured_lines.append({
                "text": clean_ln,
                "is_heading": False,
                "is_poetry": False,
                "runin_heading": runin_title,
                "runin_level": 3,
                "level": None,
            })
            continue

        level = None
        if not is_salutation:
            if clean_ln.startswith("[") and re.search(r"\]\s*(?:[\(\[][٠-٩0-9]+[\)\]])?\s*$", clean_ln) and w_count <= 16:
                level = 2
            elif HEADING_KEYWORDS_L1.match(core_ln) and w_count <= 9 and not ends_with_stop and "،" not in core_ln:
                level = 1
            elif HEADING_KEYWORDS_L2.match(core_ln) and w_count <= 9 and not ends_with_stop and "،" not in core_ln:
                level = 2
            elif HEADING_KEYWORDS_L3.match(core_ln) and w_count <= 8 and not ends_with_stop and "،" not in core_ln:
                level = 3
            elif (
                1 <= w_count <= 3
                and not ends_with_stop
                and "،" not in core_ln
                and not clean_ln.startswith("﴿")
                and not re.match(r"^[\(\[٠-٩0-9]", clean_ln)
                and "//" not in clean_ln
                and not prev_ln.rstrip().endswith(("،", "؛", ":"))
            ):
                clause_starters = {
                    "وهم", "وهو", "وهي", "وهذا", "وهذه", "وهؤلاء", "فهو", "فهي", "فهم",
                    "فإن", "وإن", "ولما", "فلما", "ثم", "بل", "لكن", "لأن", "حتى",
                    "إذ", "إذا", "لو", "ولولا", "أو", "إلا", "كما", "قال", "فقال",
                }
                prev_words = prev_ln.split()
                prev_last_word = prev_words[-1] if prev_words else ""
                first_word = words[0] if words else ""
                if prev_last_word not in grammatical_binders and first_word not in clause_starters:
                    level = 1 if (is_first_page and len(headings) == 0 and w_count == 1) else 3

        structured_lines.append({
            "text": clean_ln,
            "is_heading": level is not None,
            "is_poetry": False,
            "runin_heading": None,
            "runin_level": None,
            "level": level,
        })
        if level is not None:
            headings.append({"title": clean_ln, "level": level, "line_idx": idx, "kind": "standalone"})

    return structured_lines, headings


def reflow_page_blocks(structured_lines: list) -> list:
    """يعيد تجميع الأسطر المكسورة في الصفحة إلى فقرات متماسكة مع الحفاظ على العناوين والشعر والآيات."""
    blocks = []
    curr_para = []

    def flush_para():
        if curr_para:
            blocks.append({"type": "paragraph", "level": None, "text": " ".join(curr_para)})
            curr_para.clear()

    for item in structured_lines:
        txt = item["text"]
        if item["is_heading"]:
            flush_para()
            blocks.append({"type": "heading", "level": item["level"], "text": txt, "kind": "standalone"})
            continue

        if item.get("is_poetry"):
            flush_para()
            blocks.append({"type": "paragraph", "level": None, "text": f"شعر: {txt}", "is_poetry": True})
            continue

        if item.get("runin_heading"):
            flush_para()
            blocks.append({
                "type": "heading",
                "level": item["runin_level"],
                "text": item["runin_heading"],
                "kind": "run_in",
            })
            curr_para.append(txt)
            continue

        if not curr_para:
            curr_para.append(txt)
            continue

        prev_txt = curr_para[-1]
        prev_ends_stop = bool(re.search(r"[.:!؟»﴾]\s*(?:[\(\[][٠-٩0-9]+[\)\]])?\s*$", prev_txt))
        starts_new_topic = (
            txt.startswith(PARAGRAPH_STARTERS)
            or bool(NUMBERED_PARA_RE.match(txt))
            or txt.startswith("﴿")
        )

        if prev_ends_stop and starts_new_topic:
            flush_para()
            curr_para.append(txt)
        elif prev_ends_stop and len(" ".join(curr_para).split()) >= 45:
            flush_para()
            curr_para.append(txt)
        else:
            curr_para.append(txt)

    flush_para()
    return blocks


# ==============================================================================
# 3. تأطير الحواشي وربطها بالسياق ومنع تضارب أرقامها عبر الصفحات
# ==============================================================================

def tag_inline_footnotes_with_page_scope(text: str, page_label: str) -> str:
    """
    يحول إحالات الحواشي داخل المتن مثل (١) إلى [ص١٥٢/ح١] لمنع تضارب أرقام الحواشي
    عند دمج صفحات الباب الواحد، مع عدم المساس بأرقام الآيات داخل ﴿...﴾.
    """
    if not text:
        return ""
    out = []
    last_idx = 0
    for m in re.finditer(r"[\(\[]([٠-٩0-9]{1,2})[\)\]]", text):
        pos = m.start()
        before = text[:pos]
        if before.count("﴿") > before.count("﴾"):
            continue
        ar_map = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
        val = int(m.group(1).translate(ar_map))
        if 1 <= val <= 25:
            out.append(text[last_idx:pos])
            out.append(f"[ص{page_label}/ح{m.group(1)}]")
            last_idx = m.end()
    out.append(text[last_idx:])
    return "".join(out)


def strip_annotations_for_clean_text(text: str) -> str:
    """ينتج نصًا عربيًا صافيًا خاليًا من أرقام الحواشي وأوسمة الصفحات لأغراض التلخيص والبحث."""
    if not text:
        return ""
    s = re.sub(r"\[ص[^\]]+/ح[^\]]+\]", "", text)
    s = re.sub(r"⟦[^⟧]+⟧", "", s)
    parts = re.split(r"(﴿[^﴾]*﴾)", s)
    cleaned_parts = []
    for p in parts:
        if p.startswith("﴿") and p.endswith("﴾"):
            cleaned_parts.append(p)
        else:
            cleaned_parts.append(re.sub(r"[\(\[]([٠-٩0-9]{1,2})[\)\]]", "", p))
    s = "".join(cleaned_parts)
    return re.sub(r"[ \t]{2,}", " ", s).strip()


def parse_and_link_page_footnotes(pdf_page: int, printed_page: str, matn: str, footnotes_raw: str) -> list:
    """يحلل حواشي الصفحة ويربط كل حاشية بموضعها في المتن ويكشف الحواشي المشتركة أو اليتيمة."""
    if not footnotes_raw or not footnotes_raw.strip():
        return []
    page_label = str(printed_page or pdf_page)
    ar_map = str.maketrans("٠١٢٣٤٥٦٧٨٩¹²³⁴⁵⁶⁷⁸⁹", "0123456789123456789")
    fn_records = []
    for ln in footnotes_raw.splitlines():
        s = ln.strip()
        if not s:
            continue
        m = re.match(r"^(?:[\(\[]([٠-٩0-9]{1,2})[\)\]]|([٠-٩0-9]{1,2})\s*[-–—)])\s*(.*)$", s)
        if m:
            raw_marker = m.group(1) or m.group(2)
            num_int = int(raw_marker.translate(ar_map))
            body = m.group(3).strip()
            contexts = []
            for match in re.finditer(r"[\(\[]" + re.escape(raw_marker) + r"[\)\]]", matn):
                pos = match.start()
                before = matn[:pos]
                if before.count("﴿") > before.count("﴾"):
                    continue
                start_ctx = max(0, pos - 45)
                end_ctx = min(len(matn), match.end() + 35)
                snippet = re.sub(r"\s+", " ", matn[start_ctx:end_ctx]).strip()
                contexts.append(snippet)
            status = "LINKED" if len(contexts) == 1 else ("SHARED_MARKER" if len(contexts) > 1 else "ORPHAN_IN_MATN")
            fn_records.append({
                "pdf_page": pdf_page,
                "printed_page": str(printed_page or ""),
                "marker_num": num_int,
                "marker_raw": f"({raw_marker})",
                "scoped_id": f"[ص{page_label}/ح{raw_marker}]",
                "text": body,
                "matn_contexts": contexts,
                "status": status,
            })
        elif fn_records:
            fn_records[-1]["text"] += " " + s
        else:
            fn_records.append({
                "pdf_page": pdf_page,
                "printed_page": str(printed_page or ""),
                "marker_num": 0,
                "marker_raw": "(=)",
                "scoped_id": f"[ص{page_label}/ح=]",
                "text": s,
                "matn_contexts": [],
                "status": "CONTINUATION",
            })
    return fn_records


# ==============================================================================
# 4. بناء الفهرس الشجري (TOC) وتجميع الأبواب والفصول عبر الصفحات (Parts Builder)
# ==============================================================================

def build_structured_book(pages_data: list, book_slug: str, book_title: str = "", author: str = "") -> dict:
    """
    يحول قائمة الصفحات المستخرجة إلى هيكل كتاب كامل يضم:
      - toc: الفهرس الشجري السليم (بدون تداخل المستويات المتساوية)
      - parts: الأبواب والفصول متصلة السياق عبر الصفحات مع حواشيها المؤطرة في مواضعها الدقيقة
      - pages_enriched: الصفحات مع الفقرات المعاد تدفقها
      - footnotes_all: جميع الحواشي المربوطة
    """
    parts = []
    pages_enriched = []
    footnotes_all = []

    current_part = None
    preamble_paragraphs = []
    preamble_footnotes = []
    preamble_start_pdf = None
    preamble_start_pg = None

    def start_new_part(title: str, level: int, kind: str, pdf_page: int, printed_page: str, page_label: str):
        nonlocal current_part
        clean_title = re.sub(r"[\(\[]([٠-٩0-9]{1,2})[\)\]]\s*$", "", title).strip()
        tagged_h = tag_inline_footnotes_with_page_scope(title, page_label)
        part_id = len(parts) + 1

        # تحديد الأب (parent_id) والمسار الشجري (path) دون تلويث متغير level الأصلي!
        parent_id = None
        ancestors = []
        search_lvl = level
        for prev_p in reversed(parts):
            if prev_p["orig_level"] < search_lvl:
                if parent_id is None:
                    parent_id = prev_p["part_id"]
                ancestors.append(prev_p["title"])
                search_lvl = prev_p["orig_level"]
                if search_lvl == 1:
                    break
        ancestors.reverse()
        path_str = " > ".join(ancestors + [clean_title])

        current_part = {
            "part_id": part_id,
            "title": clean_title,
            "raw_title": title,
            "raw_title_tagged": tagged_h,
            "level": len(ancestors) + 1,
            "orig_level": level,
            "kind": kind,
            "parent_id": parent_id,
            "path": path_str,
            "start_pdf_page": pdf_page,
            "end_pdf_page": pdf_page,
            "start_printed_page": str(printed_page or pdf_page),
            "end_printed_page": str(printed_page or pdf_page),
            "paragraphs": [],
            "footnotes": [],
            "summary": "",
        }
        if part_id == 1 and preamble_paragraphs:
            current_part["start_pdf_page"] = preamble_start_pdf or pdf_page
            current_part["start_printed_page"] = str(preamble_start_pg or printed_page or pdf_page)
            current_part["paragraphs"].extend(preamble_paragraphs)
            current_part["footnotes"].extend(preamble_footnotes)
            preamble_paragraphs.clear()
            preamble_footnotes.clear()

        parts.append(current_part)
        return current_part

    for p_idx, pdata in enumerate(pages_data):
        pdf_page = pdata.get("pdf_page", p_idx + 1)
        if pdata.get("layout") == "blank_or_sparse":
            pages_enriched.append({
                "pdf_page": pdf_page,
                "printed_page": "",
                "part_id": current_part["part_id"] if current_part else 1,
                "layout": "blank_or_sparse",
                "running_header": "",
                "matn": "",
                "matn_reflowed": "",
                "footnotes": "",
                "margin_notes": "",
                "word_count": 0,
                "warnings": [],
            })
            continue

        ext = pdata.get("extracted") or {}
        printed_page = str(ext.get("printed_page") or "").strip()
        page_label = printed_page or str(pdf_page)
        matn = ext.get("matn") or ""
        fn_raw = ext.get("footnotes") or ""
        margin_raw = (ext.get("margin_notes") or "").strip()
        running_hdr = (ext.get("running_header") or "").strip()

        structured_lines, page_headings = parse_page_structure(matn, is_first_page=(p_idx == 0))
        blocks = reflow_page_blocks(structured_lines)
        fn_records = parse_and_link_page_footnotes(pdf_page, printed_page, matn, fn_raw)

        # تتبع الأقسام التي ظهرت في هذه الصفحة لتوزيع الحواشي عليها بدقة حسب موضع الإحالة
        parts_active_on_page = []
        if current_part:
            parts_active_on_page.append(current_part)

        margin_badge = f"⟦هامش ص {page_label}: {margin_raw}⟧ " if margin_raw else ""
        margin_attached = False

        reflowed_page_paras = []
        for b_idx, blk in enumerate(blocks):
            if blk["type"] == "heading":
                pt_new = start_new_part(blk["text"], blk["level"], blk.get("kind", "standalone"), pdf_page, page_label, page_label)
                if pt_new not in parts_active_on_page:
                    parts_active_on_page.append(pt_new)
            else:
                para_tagged = tag_inline_footnotes_with_page_scope(blk["text"], page_label)
                if not margin_attached and margin_badge:
                    para_tagged = margin_badge + para_tagged
                    margin_attached = True
                reflowed_page_paras.append(blk["text"])

                target_list = current_part["paragraphs"] if current_part else preamble_paragraphs
                if not current_part and preamble_start_pdf is None:
                    preamble_start_pdf = pdf_page
                    preamble_start_pg = page_label

                if current_part:
                    current_part["end_pdf_page"] = pdf_page
                    current_part["end_printed_page"] = page_label

                # فحص ما إذا كانت الفقرة الأولى في هذه الصفحة هي تكملة لجملة مقطوعة في آخر الصفحة السابقة!
                if (
                    b_idx == 0
                    and not blk.get("is_poetry")
                    and target_list
                    and target_list[-1]["pdf_page"] < pdf_page
                ):
                    prev_para = target_list[-1]["text_raw"]
                    ends_with_stop = bool(re.search(r"[.:!؟»﴾]\s*(?:[\(\[][٠-٩0-9]+[\)\]])?\s*$", prev_para.strip()))
                    if not ends_with_stop:
                        target_list[-1]["text_tagged"] += f" ⟦ص {page_label}⟧ " + para_tagged
                        target_list[-1]["text_raw"] += " " + blk["text"]
                        target_list[-1]["end_pdf_page"] = pdf_page
                        target_list[-1]["end_printed_page"] = page_label
                        continue

                prefix_badge = ""
                if target_list and target_list[-1].get("end_pdf_page", target_list[-1]["pdf_page"]) < pdf_page:
                    prefix_badge = f"⟦ص {page_label}⟧ "

                target_list.append({
                    "pdf_page": pdf_page,
                    "end_pdf_page": pdf_page,
                    "printed_page": page_label,
                    "end_printed_page": page_label,
                    "text_tagged": prefix_badge + para_tagged,
                    "text_raw": blk["text"],
                })

        # توزيع حواشي الصفحة على القسم الذي وردت فيه الإحالة فعليًا (وليس مجرد آخر قسم في الصفحة!)
        for fn_rec in fn_records:
            sid = fn_rec["scoped_id"]
            matched_parts = []
            for cand_pt in parts_active_on_page:
                cand_text = cand_pt.get("raw_title_tagged", "") + " " + " ".join(
                    p["text_tagged"] for p in cand_pt["paragraphs"] if p.get("end_pdf_page") == pdf_page or p.get("pdf_page") == pdf_page
                )
                if sid in cand_text:
                    matched_parts.append(cand_pt)
            if not matched_parts and parts_active_on_page:
                matched_parts = [parts_active_on_page[0]]

            if matched_parts:
                fn_rec["part_id"] = matched_parts[0]["part_id"]
                footnotes_all.append(fn_rec)
                for mp in matched_parts:
                    mp["footnotes"].append(dict(fn_rec, part_id=mp["part_id"]))
            else:
                fn_rec["part_id"] = 1
                footnotes_all.append(fn_rec)
                preamble_footnotes.append(fn_rec)

        gr = pdata.get("gate_report") or {}
        pages_enriched.append({
            "pdf_page": pdf_page,
            "printed_page": page_label,
            "part_id": parts_active_on_page[0]["part_id"] if parts_active_on_page else 1,
            "layout": pdata.get("layout", "standard_single_col"),
            "running_header": running_hdr,
            "matn": matn,
            "matn_reflowed": "\n\n".join(reflowed_page_paras),
            "footnotes": fn_raw,
            "margin_notes": margin_raw,
            "word_count": gr.get("total_words", len((matn + " " + fn_raw).split())),
            "warnings": gr.get("warnings", []),
        })

    if not parts and preamble_paragraphs:
        start_new_part(book_title or book_slug, 1, "standalone", preamble_start_pdf or 1, preamble_start_pg or "1", preamble_start_pg or "1")

    # استكمال النصوص المجمعة والإحصائيات لكل قسم (Part)
    toc = []
    for pt in parts:
        # تحديث نطاق الصفحات الفعلي للقسم بناءً على فقراته الفعليّة
        if pt["paragraphs"]:
            pt["start_pdf_page"] = min(pt["start_pdf_page"], pt["paragraphs"][0]["pdf_page"])
            pt["end_pdf_page"] = max(p["end_pdf_page"] for p in pt["paragraphs"])
            pt["end_printed_page"] = pt["paragraphs"][-1]["end_printed_page"]

        paras_tagged = [p["text_tagged"] for p in pt["paragraphs"]]
        paras_raw = [p["text_raw"] for p in pt["paragraphs"]]

        text_continuous = "\n\n".join(paras_tagged).strip()
        text_clean = strip_annotations_for_clean_text("\n\n".join(paras_raw))

        fn_lines_scoped = []
        for fn in pt["footnotes"]:
            orphan_note = " *(سقط رقمها من المتن في المطبوع)*" if fn["status"] == "ORPHAN_IN_MATN" else ""
            fn_lines_scoped.append(f"- **{fn['scoped_id']}**{orphan_note}: {fn['text']}")
        footnotes_scoped_str = "\n".join(fn_lines_scoped)

        word_count = len(pt["title"].split()) + len(text_clean.split()) + sum(len(fn["text"].split()) for fn in pt["footnotes"])
        char_size = len(text_continuous.encode("utf-8"))

        pt["text_continuous"] = text_continuous
        pt["text_clean"] = text_clean
        pt["footnotes_scoped"] = footnotes_scoped_str
        pt["word_count"] = word_count
        pt["char_size"] = char_size

        toc.append({
            "i": pt["part_id"],
            "t": pt["title"],
            "d": pt["level"],
            "orig_level": pt["orig_level"],
            "kind": pt["kind"],
            "parent_id": pt["parent_id"],
            "path": pt["path"],
            "pg": pt["start_printed_page"],
            "end_pg": pt["end_printed_page"],
            "pdf_pg": pt["start_pdf_page"],
            "end_pdf_pg": pt["end_pdf_page"],
            "words": word_count,
            "sz": char_size,
        })

    inferred_title = book_title or (toc[0]["t"] if toc else book_slug)
    return {
        "book_slug": book_slug,
        "book_title": inferred_title,
        "author": author,
        "toc": toc,
        "parts": parts,
        "pages": pages_enriched,
        "footnotes": footnotes_all,
    }


# ==============================================================================
# 5. حفظ قاعدة بيانات SQLite وتوليد ملفات الـ Markdown المهيكلة
# ==============================================================================

def write_sqlite_db(db_path: str, structured_book: dict):
    """ينشئ قاعدة بيانات SQLite كاملة للكتاب مع فهارس البحث العربي FTS5."""
    existing_summaries = {}
    if os.path.exists(db_path):
        try:
            old_conn = sqlite3.connect(db_path)
            for pid, summ in old_conn.execute("SELECT part_id, summary FROM parts WHERE summary != ''"):
                existing_summaries[pid] = summ
            old_conn.close()
        except Exception:
            pass
        os.remove(db_path)

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.executescript(
        """
        PRAGMA journal_mode=WAL;
        CREATE TABLE book_meta (
            book_slug TEXT PRIMARY KEY,
            title TEXT,
            author TEXT,
            total_pages INTEGER,
            total_parts INTEGER,
            total_words INTEGER,
            total_footnotes INTEGER,
            built_at TEXT
        );

        CREATE TABLE toc (
            part_id INTEGER PRIMARY KEY,
            title TEXT,
            level INTEGER,
            kind TEXT,
            parent_id INTEGER,
            path TEXT,
            start_printed_page TEXT,
            end_printed_page TEXT,
            start_pdf_page INTEGER,
            end_pdf_page INTEGER,
            word_count INTEGER,
            char_size INTEGER
        );

        CREATE TABLE parts (
            part_id INTEGER PRIMARY KEY,
            title TEXT,
            level INTEGER,
            path TEXT,
            start_printed_page TEXT,
            end_printed_page TEXT,
            start_pdf_page INTEGER,
            end_pdf_page INTEGER,
            text_continuous TEXT,
            text_clean TEXT,
            text_search_norm TEXT,
            footnotes_scoped TEXT,
            word_count INTEGER,
            summary TEXT
        );

        CREATE TABLE pages (
            pdf_page INTEGER PRIMARY KEY,
            printed_page TEXT,
            part_id INTEGER,
            layout TEXT,
            running_header TEXT,
            matn TEXT,
            matn_reflowed TEXT,
            footnotes TEXT,
            margin_notes TEXT,
            text_search_norm TEXT,
            word_count INTEGER,
            warnings_json TEXT
        );

        CREATE TABLE footnotes (
            fn_id INTEGER PRIMARY KEY AUTOINCREMENT,
            scoped_id TEXT,
            part_id INTEGER,
            pdf_page INTEGER,
            printed_page TEXT,
            marker_num INTEGER,
            marker_raw TEXT,
            fn_text TEXT,
            matn_context TEXT,
            status TEXT
        );

        CREATE VIRTUAL TABLE parts_fts USING fts5(
            title_norm,
            text_search_norm,
            content='parts',
            content_rowid='part_id'
        );

        CREATE VIRTUAL TABLE pages_fts USING fts5(
            text_search_norm,
            content='pages',
            content_rowid='pdf_page'
        );
        """
    )

    total_words = sum(p["word_count"] for p in structured_book["pages"])
    cur.execute(
        "INSERT INTO book_meta VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            structured_book["book_slug"],
            structured_book["book_title"],
            structured_book["author"],
            len(structured_book["pages"]),
            len(structured_book["parts"]),
            total_words,
            len(structured_book["footnotes"]),
            datetime.now(timezone.utc).isoformat(),
        ),
    )

    for t in structured_book["toc"]:
        cur.execute(
            "INSERT INTO toc VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                t["i"],
                t["t"],
                t["d"],
                t["kind"],
                t["parent_id"],
                t["path"],
                t["pg"],
                t["end_pg"],
                t["pdf_pg"],
                t["end_pdf_pg"],
                t["words"],
                t["sz"],
            ),
        )

    for pt in structured_book["parts"]:
        pid = pt["part_id"]
        summ = existing_summaries.get(pid, pt.get("summary", ""))
        pt["summary"] = summ
        fn_plain = " ".join(fn["text"] for fn in pt["footnotes"])
        norm_part = normalize_arabic_search(pt["title"] + "\n" + pt["text_clean"] + "\n" + fn_plain)
        norm_title = normalize_arabic_search(pt["title"])
        cur.execute(
            "INSERT INTO parts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                pid,
                pt["title"],
                pt["level"],
                pt["path"],
                pt["start_printed_page"],
                pt["end_printed_page"],
                pt["start_pdf_page"],
                pt["end_pdf_page"],
                pt["text_continuous"],
                pt["text_clean"],
                norm_part,
                pt["footnotes_scoped"],
                pt["word_count"],
                summ,
            ),
        )
        cur.execute(
            "INSERT INTO parts_fts(rowid, title_norm, text_search_norm) VALUES (?, ?, ?)",
            (pid, norm_title, norm_part),
        )

    for pg in structured_book["pages"]:
        norm_pg = normalize_arabic_search(pg["matn"] + "\n" + pg["footnotes"] + "\n" + pg["margin_notes"])
        cur.execute(
            "INSERT INTO pages VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                pg["pdf_page"],
                pg["printed_page"],
                pg["part_id"],
                pg["layout"],
                pg["running_header"],
                pg["matn"],
                pg["matn_reflowed"],
                pg["footnotes"],
                pg["margin_notes"],
                norm_pg,
                pg["word_count"],
                json.dumps(pg["warnings"], ensure_ascii=False),
            ),
        )
        cur.execute(
            "INSERT INTO pages_fts(rowid, text_search_norm) VALUES (?, ?)",
            (pg["pdf_page"], norm_pg),
        )

    for fn in structured_book["footnotes"]:
        cur.execute(
            "INSERT INTO footnotes (scoped_id, part_id, pdf_page, printed_page, marker_num, marker_raw, fn_text, matn_context, status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                fn["scoped_id"],
                fn["part_id"],
                fn["pdf_page"],
                fn["printed_page"],
                fn["marker_num"],
                fn["marker_raw"],
                fn["text"],
                " | ".join(fn["matn_contexts"]),
                fn["status"],
            ),
        )

    conn.commit()
    conn.close()


def format_structured_chapter_markdown(structured_book: dict) -> str:
    """
    يبني ملف الـ Markdown المهيكل بالأبواب والفصول (<slug>.md):
      - يبدأ بعنوان الكتاب وجدول الفهرس الشامل (TOC).
      - يعرض كل باب/فصل بنصه المتصل عبر الصفحات (مع وسم ⟦ص ...⟧) وملخصه (إن وجد) وحواشيه المؤطرة.
    """
    lines = []
    lines.append(f"# {structured_book['book_title']}")
    if structured_book.get("author"):
        lines.append(f"**المؤلف:** {structured_book['author']}")
    lines.append("")
    lines.append("## فهرس الأبواب والفصول")
    lines.append("")
    lines.append("| # | القسم / العنوان | المسار | ص المطبوع | ص PDF | الكلمات |")
    lines.append("| :--- | :--- | :--- | :--- | :--- | :--- |")
    for t in structured_book["toc"]:
        depth = t["path"].count(" > ")
        indent = "— " * depth
        pg_range = t["pg"] if t["pg"] == t["end_pg"] else f"{t['pg']}–{t['end_pg']}"
        pdf_range = str(t["pdf_pg"]) if t["pdf_pg"] == t["end_pdf_pg"] else f"{t['pdf_pg']}–{t['end_pdf_pg']}"
        lines.append(f"| {t['i']} | {indent}**{t['t']}** | `{t['path']}` | {pg_range} | {pdf_range} | {t['words']} |")
    lines.append("")
    lines.append("---")
    lines.append("")

    for pt in structured_book["parts"]:
        hashes = "#" * min(4, pt["level"] + 1)
        pg_span = (
            f"ص {pt['start_printed_page']}"
            if pt["start_printed_page"] == pt["end_printed_page"]
            else f"ص {pt['start_printed_page']}–{pt['end_printed_page']}"
        )
        title_disp = pt.get("raw_title_tagged") or pt["title"]
        lines.append(f"{hashes} [{pt['part_id']}] {title_disp} ({pg_span})")
        lines.append("")
        if pt.get("summary"):
            lines.append(f"> **ملخص القسم:** {pt['summary']}")
            lines.append("")
        if pt["text_continuous"]:
            lines.append(pt["text_continuous"])
            lines.append("")
        if pt["footnotes_scoped"]:
            lines.append("#### حواشي القسم")
            lines.append(pt["footnotes_scoped"])
            lines.append("")
        lines.append("---")
        lines.append("")

    return "\n".join(lines).strip() + "\n"


# ==============================================================================
# 6. واجهة الاستعلام البرمجي وسطر الأوامر (turathmcp-Compatible Query Engine)
# ==============================================================================

def query_get_toc(db_path: str) -> dict:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    meta = dict(conn.execute("SELECT * FROM book_meta LIMIT 1").fetchone())
    toc_rows = [dict(r) for r in conn.execute("SELECT * FROM toc ORDER BY part_id")]
    conn.close()
    return {
        "book_slug": meta["book_slug"],
        "title": meta["title"],
        "author": meta["author"],
        "total_pages": meta["total_pages"],
        "total_words": meta["total_words"],
        "toc": [
            {
                "i": r["part_id"],
                "t": r["title"],
                "d": r["level"],
                "path": r["path"],
                "pg": r["start_printed_page"],
                "end_pg": r["end_printed_page"],
                "pdf_pg": r["start_pdf_page"],
                "end_pdf_pg": r["end_pdf_page"],
                "words": r["word_count"],
                "sz": r["char_size"],
            }
            for r in toc_rows
        ],
    }


def query_get_part(db_path: str, part_id: int, clean: bool = False) -> dict:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM parts WHERE part_id = ?", (part_id,)).fetchone()
    conn.close()
    if not row:
        return {"error": f"Part {part_id} not found"}
    r = dict(row)
    return {
        "i": r["part_id"],
        "t": r["title"],
        "d": r["level"],
        "path": r["path"],
        "pg": r["start_printed_page"],
        "end_pg": r["end_printed_page"],
        "pdf_pg": r["start_pdf_page"],
        "end_pdf_pg": r["end_pdf_page"],
        "words": r["word_count"],
        "summary": r["summary"],
        "text": r["text_clean"] if clean else r["text_continuous"],
        "fn": r["footnotes_scoped"],
    }


def query_search_book(db_path: str, query_str: str, top: int = 20) -> list:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    words = [w for w in query_str.strip().split() if w]
    if not words:
        return []
    word_clauses = []
    for w in words:
        variants = expand_arabic_query_terms(w)
        if variants:
            clause = "(" + " OR ".join(v if v.endswith("*") else f'"{v}"' for v in variants) + ")"
            word_clauses.append(clause)
    fts_query = " AND ".join(word_clauses)

    sql = """
        SELECT p.pdf_page, p.printed_page, p.part_id, p.matn_reflowed, p.footnotes,
               t.title AS part_title, t.path AS part_path,
               bm25(pages_fts) AS score
        FROM pages_fts
        JOIN pages p ON pages_fts.rowid = p.pdf_page
        LEFT JOIN toc t ON p.part_id = t.part_id
        WHERE pages_fts MATCH ?
        ORDER BY score
        LIMIT ?
    """
    rows = conn.execute(sql, (fts_query, top)).fetchall()
    all_parts = [
        dict(pr)
        for pr in conn.execute(
            "SELECT part_id, title, path, start_pdf_page, end_pdf_page, text_clean, footnotes_scoped FROM parts ORDER BY part_id"
        ).fetchall()
    ]
    conn.close()

    results = []
    for r in rows:
        full_txt = (r["matn_reflowed"] or "") + "\n" + (r["footnotes"] or "")
        snippet = full_txt[:180].replace("\n", " ")
        matched_token = ""
        for w in words:
            stems = [s.rstrip("*") for s in expand_arabic_query_terms(w) if len(s.rstrip("*")) >= 3]
            for token in full_txt.split():
                tok_norm = re.sub(r"[^\u0621-\u064A]", "", normalize_arabic_search(token))
                if any(tok_norm.startswith(st) or st in tok_norm for st in stems):
                    idx = full_txt.find(token)
                    if idx != -1:
                        matched_token = token
                        s0 = max(0, idx - 60)
                        s1 = min(len(full_txt), idx + 120)
                        snippet = re.sub(r"\s+", " ", full_txt[s0:s1]).strip()
                        break

        part_id = r["part_id"]
        part_title = r["part_title"]
        part_path = r["part_path"]
        cand_parts = [
            pt for pt in all_parts
            if pt["start_pdf_page"] <= r["pdf_page"] <= pt["end_pdf_page"]
        ]
        if len(cand_parts) > 1 and matched_token:
            for pt in cand_parts:
                pt_blob = (pt["text_clean"] or "") + " " + (pt["footnotes_scoped"] or "")
                if matched_token in pt_blob:
                    part_id = pt["part_id"]
                    part_title = pt["title"]
                    part_path = pt["path"]
                    break

        results.append({
            "pdf_page": r["pdf_page"],
            "printed_page": r["printed_page"],
            "part_id": part_id,
            "part_title": part_title,
            "path": part_path,
            "snippet": snippet,
        })
    return results


def build_all_for_dir(out_dir: str, title: str = "", author: str = "") -> dict:
    """يبني قاعدة البيانات وملفات الفهرس والأبواب لمجلد مخرجات كتاب."""
    pages_dir = os.path.join(out_dir, "pages")
    pages_data = []
    book_slug = os.path.basename(os.path.abspath(out_dir))

    existing_jsons = [
        f for f in glob.glob(os.path.join(out_dir, "*.json"))
        if not f.endswith(("gate_report.json", "toc.json"))
    ]
    if existing_jsons:
        try:
            with open(existing_jsons[0], "r", encoding="utf-8") as f:
                bdoc_meta = json.load(f)
                if bdoc_meta.get("book_slug"):
                    book_slug = bdoc_meta["book_slug"]
        except Exception:
            book_slug = os.path.splitext(os.path.basename(existing_jsons[0]))[0]

    if os.path.isdir(pages_dir):
        for pf in sorted(glob.glob(os.path.join(pages_dir, "p*.json"))):
            with open(pf, "r", encoding="utf-8") as f:
                pages_data.append(json.load(f))
    elif existing_jsons:
        with open(existing_jsons[0], "r", encoding="utf-8") as f:
            bdoc = json.load(f)
            pages_data = bdoc.get("pages", [])

    if not pages_data:
        raise RuntimeError(f"لا توجد بيانات صفحات في: {out_dir}")

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from agy_pdf_to_text import format_book_markdown, run_quality_gates  # noqa: E402

    for pdata in pages_data:
        if pdata.get("layout") == "blank_or_sparse":
            continue
        meta = pdata.get("meta") or {}
        meta.setdefault("visual_line_count", pdata.get("gate_report", {}).get("visual_line_count", 0))
        meta.setdefault("layout", pdata.get("layout", "standard_single_col"))
        meta.setdefault("height", 2500)
        pdata["gate_report"] = run_quality_gates(pdata["extracted"], meta)

    structured = build_structured_book(pages_data, book_slug=book_slug, book_title=title, author=author)

    db_path = os.path.join(out_dir, f"{book_slug}.db")
    write_sqlite_db(db_path, structured)

    toc_path = os.path.join(out_dir, "toc.json")
    with open(toc_path, "w", encoding="utf-8") as f:
        json.dump(query_get_toc(db_path), f, ensure_ascii=False, indent=2)

    pages_md_path = os.path.join(out_dir, f"{book_slug}_pages.md")
    with open(pages_md_path, "w", encoding="utf-8") as f:
        f.write(format_book_markdown(pages_data))

    master_md_path = os.path.join(out_dir, f"{book_slug}.md")
    with open(master_md_path, "w", encoding="utf-8") as f:
        f.write(format_structured_chapter_markdown(structured))

    return {
        "book_slug": book_slug,
        "db_path": db_path,
        "toc_path": toc_path,
        "master_md_path": master_md_path,
        "pages_md_path": pages_md_path,
        "total_pages": len(structured["pages"]),
        "total_parts": len(structured["parts"]),
        "total_footnotes": len(structured["footnotes"]),
    }


def main():
    parser = argparse.ArgumentParser(description="بناء واستعلام قاعدة بيانات الكتاب التراثي (SQLite + FTS5 + TOC)")
    parser.add_argument("out_dir", help="مجلد مخرجات الكتاب")
    parser.add_argument("--title", default="", help="عنوان الكتاب (اختياري)")
    parser.add_argument("--author", default="", help="اسم المؤلف (اختياري)")
    parser.add_argument("--get-toc", action="store_true", help="عرض الفهرس الشجري للكتاب بصيغة JSON")
    parser.add_argument("--get-part", type=int, default=0, help="جلب نص قسم/باب محدد برقمه في الفهرس")
    parser.add_argument("--clean", action="store_true", help="جلب النص الصافي للقسم بدون أوسمة الصفحات والحواشي")
    parser.add_argument("--search", default="", help="بحث عربي فوري في المتن والحواشي")
    parser.add_argument("--set-summary", nargs=2, metavar=("PART_ID", "SUMMARY"), help="حفظ ملخص لقسم محدد وتحديث الماركداون")
    args = parser.parse_args()

    dbs = glob.glob(os.path.join(args.out_dir, "*.db"))
    db_path = dbs[0] if dbs else ""

    if args.get_toc:
        if not db_path:
            info = build_all_for_dir(args.out_dir, args.title, args.author)
            db_path = info["db_path"]
        print(json.dumps(query_get_toc(db_path), ensure_ascii=False, indent=2))
        return

    if args.get_part > 0:
        if not db_path:
            info = build_all_for_dir(args.out_dir, args.title, args.author)
            db_path = info["db_path"]
        print(json.dumps(query_get_part(db_path, args.get_part, clean=args.clean), ensure_ascii=False, indent=2))
        return

    if args.search:
        if not db_path:
            info = build_all_for_dir(args.out_dir, args.title, args.author)
            db_path = info["db_path"]
        hits = query_search_book(db_path, args.search)
        print(json.dumps({"query": args.search, "hits_count": len(hits), "hits": hits}, ensure_ascii=False, indent=2))
        return

    if args.set_summary:
        if not db_path:
            info = build_all_for_dir(args.out_dir, args.title, args.author)
            db_path = info["db_path"]
        pid = int(args.set_summary[0])
        summ_txt = args.set_summary[1]
        conn = sqlite3.connect(db_path)
        conn.execute("UPDATE parts SET summary = ? WHERE part_id = ?", (summ_txt, pid))
        conn.commit()
        conn.close()
        info = build_all_for_dir(args.out_dir, args.title, args.author)
        print(f"[تم] تحديث ملخص القسم {pid} وإعادة بناء {info['master_md_path']}")
        return

    info = build_all_for_dir(args.out_dir, args.title, args.author)
    print(
        f"[بناء قاعدة البيانات والفهرس] الكتاب={info['book_slug']} | الصفحات={info['total_pages']} | "
        f"الأقسام={info['total_parts']} | الحواشي المربوطة={info['total_footnotes']}\n"
        f"  -> SQLite DB : {info['db_path']}\n"
        f"  -> TOC JSON  : {info['toc_path']}\n"
        f"  -> Master MD : {info['master_md_path']}\n"
        f"  -> Pages MD  : {info['pages_md_path']}"
    )


if __name__ == "__main__":
    main()
