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

AR_TO_ASCII_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹¹²³⁴⁵⁶⁷⁸⁹⁰", "012345678901234567891234567890")
ASCII_TO_AR_DIGITS = str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩")
SUPERSCRIPT_CHARS = "¹²³⁴⁵⁶⁷⁸⁹"
TASHKEEL_RE = re.compile(r"[\u0617-\u061A\u064B-\u065F\u0670\u0640]")
ZONE_SENTINEL = "\n<<__TURATH_ZONE_SPLIT__>>\n"

STANDALONE_NEXT_WORDS = {
    "في", "من", "عن", "على", "إلى", "الى", "أن", "إن", "ان", "ما", "لا", "أو", "ثم",
    "بل", "قد", "هل", "لم", "لن", "مع", "كل", "غير", "عند", "بين", "بعد", "قبل",
    "فوق", "تحت", "نحو", "مثل", "قال", "قوله", "باب", "فصل", "كتاب", "مسألة",
    "فرع", "تنبيه", "حاشية", "الشرح", "أقول", "وهو", "وهي", "وهم", "وهذا", "وهذه",
}

QURAN_INTRO_CUE_RE = re.compile(
    r"(?:(?:قال|قوله|لقوله|بقوله|كقوله)\s+(?:الله\s+)?(?:تعالى|سبحانه|عز\s+وجل)|"
    r"ذكرهم\s+الله\s+في\s+قوله|في\s+قوله\s*:|لقوله\s*:|قال\s+تعالى|قوله\s+تعالى|"
    r"في\s+التنزيل|في\s+القرآن|سورة\s+[\u0621-\u064A]+|الآية)"
)

SHARH_ZONE_DIVIDER_LINE_RE = re.compile(
    r"^\s*(?:[-─═=_]{3,}\s*(?:الشرح|الشَّرْحُ)?\s*[-─═=_]*|\[\s*(?:الشرح|الشَّرْحُ)\s*\])\s*$"
)

FOLIO_MARKER_RE = re.compile(
    r"(?:/\s*)?\((?=[^()\n]{1,16}\))(?=[^)]*[أابظوزدمه])\s*[٠-٩0-9]{1,4}\s*/?\s*[أابظو]?\u064e?\s*"
    r"(?:/\s*[أابظوزدمه]\u064e?\s*){0,2}\)"
)

COUNT_NOUNS = {
    "عدد", "رقم", "برقم", "الأسطر", "سطر", "سطرا", "ورقة", "ورقات",
    "ص", "صفحة", "ج", "جزء", "سنة", "عام", "مجلد", "حديث", "آية",
    "المسألة", "مسألة", "القاعدة", "قاعدة", "الباب", "باب", "الفصل", "فصل",
    "الفرع", "فرع", "المطلب", "مطلب", "المبحث", "مبحث", "النوع", "نوع", "قسم",
}

HEADING_KEYWORDS_RE = re.compile(
    r"^(?:كتاب|الكتاب|باب|الباب|فصل|الفصل|مسألة|المسألة|مبحث|المبحث|مطلب|المطلب|فرع|الفرع|"
    r"قاعدة|القاعدة|تنبيه|التنبيه|خاتمة|الخاتمة|تتمة|القول في|القسم|حاشية)\b"
)

# أنماط العناوين التراثية لتقطيع الأجزاء مع الحفاظ الحرفي 100% على سطر العنوان داخل المتن
CHAPTER_HEADING_RE = re.compile(
    r"^(?:\[[^\]]{2,110}\](?:\s*[\(\[]\s*[٠-٩0-9\*]{1,3}\s*[\)\]])?|"
    r"(?:كتاب|الكتاب|باب|الباب|فصل|الفصل|مسألة|المسألة|مبحث|المبحث|مطلب|المطلب|فرع|الفرع|"
    r"قاعدة|القاعدة|تنبيه|التنبيه|خاتمة|الخاتمة|تتمة|القول في|القسم|حاشية)\b[^\n]{0,95})$"
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


def to_ar_digits(val: int | str) -> str:
    return str(val).translate(AR_TO_ASCII_DIGITS).translate(ASCII_TO_AR_DIGITS)


def parse_marker_val(raw_m: str) -> int | str | None:
    s = (raw_m or "").strip()
    if not s:
        return None
    if "*" in s:
        return "*"
    ascii_s = s.translate(AR_TO_ASCII_DIGITS)
    if ascii_s.isdigit():
        return int(ascii_s)
    return None


def repair_line_breaks_and_mixed_digits(text: str, is_page_number: bool = False) -> tuple[str, dict]:
    """
    ينظف النص العربي ويصلح:
      1. الأرقام الفارسية (U+06F0..U+06F9) والحروف الفارسية (ی، ک).
      2. الكلمات المقطوعة عبر نهاية السطر بالشرطة أو الكشيدة (`المسـ\\nـألة` -> `المسألة`, `باجـ-\\nـتهاد` -> `باجتهاد`, `الاست-\\nحسان` -> `الاستحسان`).
      3. الأرقام الهندية/العربية المختلطة في أرقام الصفحات (`١5` -> `١٥`) أو داخل الأرقام المركبة (`١25` -> `١٢٥`).
    """
    norm_text, base_stats = normalize_arabic_output(str(text or ""))
    line_break_splits_repaired = 0
    mixed_digits_normalized = 0

    if norm_text and not is_page_number:
        # 1) كشيدة في نهاية السطر الأول وكشيدة في مطلع السطر الثاني: المسـ\nـألة أو باجـ-\nـتهاد
        def _fix_double_kashida(m: re.Match) -> str:
            nonlocal line_break_splits_repaired
            line_break_splits_repaired += 1
            return m.group(1) + m.group(2)

        norm_text = re.sub(
            r"([\u0621-\u063A\u0641-\u064A][\u064B-\u065F\u0670]*)ـ+[-‐‑]?\s*\n\s*ـ+([\u0621-\u063A\u0641-\u064A])",
            _fix_double_kashida,
            norm_text,
        )

        # 2) كشيدة في نهاية السطر الأول يليها تكملة الكلمة في السطر الثاني: المسـ\nألة
        def _fix_trailing_kashida(m: re.Match) -> str:
            nonlocal line_break_splits_repaired
            frag2 = m.group(2)
            frag2_bare = TASHKEEL_RE.sub("", frag2)
            if frag2_bare.startswith("ال") or frag2_bare in STANDALONE_NEXT_WORDS:
                return m.group(0)
            line_break_splits_repaired += 1
            return m.group(1) + frag2

        norm_text = re.sub(
            r"([\u0621-\u063A\u0641-\u064A][\u064B-\u065F\u0670]*)ـ+\s*\n\s*([\u0621-\u063A\u0641-\u064A][\u0621-\u063A\u0641-\u064A\u064B-\u065F\u0670]{0,7})(?=\s|[،.؛:!؟\)\]]|$)",
            _fix_trailing_kashida,
            norm_text,
        )

        # 3) شرطة ملتصقة بنهاية الشطر الأول للكلمة المقطوعة عبر السطر: الاست-\nحسان
        def _fix_hyphen_split(m: re.Match) -> str:
            nonlocal line_break_splits_repaired
            frag2 = m.group(2)
            frag2_bare = TASHKEEL_RE.sub("", frag2)
            if frag2_bare.startswith("ال") or frag2_bare in STANDALONE_NEXT_WORDS:
                return m.group(0)
            line_break_splits_repaired += 1
            return m.group(1) + frag2

        norm_text = re.sub(
            r"([\u0621-\u063A\u0641-\u064A][\u064B-\u065F\u0670]*)[-‐‑]\s*\n\s*ـ*([\u0621-\u063A\u0641-\u064A][\u0621-\u063A\u0641-\u064A\u064B-\u065F\u0670]{0,7})(?=\s|[،.؛:!؟\)\]]|$)",
            _fix_hyphen_split,
            norm_text,
        )

    if norm_text:
        if is_page_number:
            ascii_cnt = sum(1 for c in norm_text if "0" <= c <= "9")
            if ascii_cnt > 0:
                norm_text = norm_text.translate(ASCII_TO_AR_DIGITS)
                mixed_digits_normalized += ascii_cnt
        else:
            def _fix_mixed_digits_token(m: re.Match) -> str:
                nonlocal mixed_digits_normalized
                tok = m.group(0)
                has_ar = any("\u0660" <= c <= "\u0669" for c in tok)
                has_ascii = any("0" <= c <= "9" for c in tok)
                if has_ar and has_ascii:
                    mixed_digits_normalized += 1
                    return tok.translate(ASCII_TO_AR_DIGITS)
                return tok

            norm_text = re.sub(r"[٠-٩0-9]{2,}", _fix_mixed_digits_token, norm_text)

    return norm_text, {
        "persian_digits_fixed": base_stats.get("persian_digits_fixed", 0),
        "persian_chars_fixed": base_stats.get("persian_chars_fixed", 0),
        "line_break_splits_repaired": line_break_splits_repaired,
        "mixed_digits_normalized": mixed_digits_normalized,
    }


def coerce_footnotes_to_raw_str(footnotes_val) -> tuple[str, str, int]:
    """
    يوحّد عقد بيانات الحواشي بين `validate_json.py` و`pdf_to_preflight_adapter.py`:
    يقبل:
      - نصاً (`str`) متعدد الأسطر أو أفقياً
      - قائمة نصوص (`list[str]`، مثل `["= تكملة...", "(١) حاشية أولى"]`)
      - قائمة قواميس (`list[dict]`، مثل `[{"id": "1", "text": "..."}, {"id": "=", "text": "..."}]`)
      - قاموساً (`dict`، مثل `{"1": "حاشية أولى", "2": "حاشية ثانية"}`)
    ويرجع `(raw_footnotes_str, input_format, structured_items_count)`.
    """
    if footnotes_val is None:
        return "", "str", 0
    if isinstance(footnotes_val, str):
        return footnotes_val, "str", 0

    lines = []
    structured_count = 0

    if isinstance(footnotes_val, dict):
        items_iter = [{"id": k, "text": v} for k, v in footnotes_val.items()]
        input_fmt = "dict"
    elif isinstance(footnotes_val, list):
        items_iter = footnotes_val
        input_fmt = "list_dict" if any(isinstance(x, dict) for x in footnotes_val) else "list_str"
    else:
        return str(footnotes_val), "other", 0

    for item in items_iter:
        if isinstance(item, str):
            s = item.strip()
            if s:
                lines.append(s)
                structured_count += 1
        elif isinstance(item, dict):
            raw_id = ""
            for k_id in ("id", "marker", "num", "number", "val"):
                if item.get(k_id) is not None and str(item.get(k_id)).strip() != "":
                    raw_id = str(item.get(k_id)).strip()
                    break
            txt = ""
            for k_tx in ("text", "body", "content", "footnote"):
                if item.get(k_tx) is not None and str(item.get(k_tx)).strip() != "":
                    txt = str(item.get(k_tx)).strip()
                    break
            is_cont = bool(item.get("continued")) or raw_id in ("=", "(=)", "[=]") or bool(re.match(r"^\s*(?:=|[\(\[]\s*=\s*[\)\]])", txt))
            if is_cont:
                body_c = re.sub(r"^\s*(?:=|[\(\[]\s*=\s*[\)\]])\s*", "", txt).strip()
                lines.append(f"= {body_c}" if body_c else "=")
                structured_count += 1
            elif raw_id:
                m_existing = FN_LINE_HEAD_RE.match(txt)
                existing_marker = next((g for g in m_existing.groups()[:7] if g is not None), "") if m_existing else ""
                if m_existing and parse_marker_val(existing_marker) == parse_marker_val(raw_id):
                    lines.append(txt)
                else:
                    v = parse_marker_val(raw_id)
                    if v == "*":
                        head = "(*)"
                    elif isinstance(v, int):
                        head = f"({to_ar_digits(v)})"
                    elif raw_id.startswith(("(", "[")):
                        head = raw_id
                    else:
                        head = f"({raw_id})"
                    lines.append(f"{head} {txt}".strip())
                structured_count += 1
            elif txt:
                lines.append(txt)
                structured_count += 1

    return "\n".join(lines), input_fmt, structured_count


def arabic_skeleton(word: str) -> str:
    """يبني جذعاً مبسطاً للكلمة العربية لمطابقة الكلمات المحققة في الحواشي مع المتن."""
    w = TASHKEEL_RE.sub("", word or "")
    w = re.sub(r"[^\u0621-\u064A]", "", w)
    w = re.sub(r"^[وفبكل]+", "", w)
    if w.startswith("ال") and len(w) > 4:
        w = w[2:]
    for suf in ("ون", "ين", "ات", "ان", "هم", "هن", "كم", "نا", "ها", "ه"):
        if w.endswith(suf) and len(w) - len(suf) >= 3:
            w = w[: -len(suf)]
            break
    w = re.sub(r"[اأإآىءؤئ]", "", w)
    return w


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


FN_LINE_HEAD_RE = re.compile(
    r"^\s*(?:"
    r"\(¬\s*([٠-٩0-9]{1,3})\s*\)"
    r"|\(\s*([٠-٩0-9]{1,3}|\*+)\s*\)"
    r"|\[\s*([٠-٩0-9]{1,3}|\*+)\s*\]"
    r"|([٠-٩0-9]{1,3})\s*[-–—.)]"
    r"|([¹²³⁴⁵⁶⁷⁸⁹])"
    r"|(\*+)\s*[-–—.]?(?=\s+\S)"
    r"|([٠-٩0-9]{1,3})\s+(?=[^\s\-–])"
    r")\s*(.*)$"
)

INLINE_HORIZ_FN_CAND_RE = re.compile(
    r"(?:(?<=\s{2})|(?<=[.؛]\s)|(?<=[.؛]\s{2}))"
    r"(?:\(\s*([٠-٩0-9]{1,2}|\*+)\s*\)|\[\s*([٠-٩0-9]{1,2}|\*+)\s*\]|([٠-٩0-9]{1,2})\s*[-–—.)]\s+|([¹²³⁴⁵⁶⁷⁸⁹])\s+)"
    r"\s*(?=[\u0621-\u064A«\"\[\(])"
)


def is_quranic_floral_span(
    text: str,
    start: int,
    end: int,
    fn_entries_meta: list[tuple[int | str, str]],
    fn_vals_set: set,
) -> bool:
    """
    يميز بين الآية القرآنية `﴿...﴾` وبين المتن المشروح الموضوع بين قوسين زهريين `﴿...﴾` في كتب الشروح والحواشي:
      - الآية القرآنية: تسبقها قرائن قرآنية (`قال تعالى`، `قوله تعالى`، `لقوله:`، `ذكرهم الله في قوله:`، `سورة`، `الآية`)،
        أو يتبعها مباشرةً رقم حاشية خارج القوس `﴾(١)` بدون إحالات معقوفة/فوقية بالداخل،
        أو تحوي أرقام آيات `(٤٣)` غير موجودة في حواشي الصفحة.
      - المتن المشروح `﴿...﴾`: يقع في `matn_top` أو في صدر الفقرة دون قرائن قرآنية ويحوي إحالات حواشٍ حقيقية `[١]`، `²`، `(٣)`
        تقابلها حواشٍ في ذيل الصفحة.
    """
    before = TASHKEEL_RE.sub("", text[max(0, start - 120):start])
    after = text[end:min(len(text), end + 25)]
    inner = text[start + 1:max(start + 1, end - 1)]

    if QURAN_INTRO_CUE_RE.search(before):
        return True

    has_non_paren_fn_markers_inside = bool(re.search(r"\[\s*[٠-٩0-9\*]{1,2}\s*\]|[¹²³⁴⁵⁶⁷⁸⁹]", inner))
    m_after = re.match(r"^\s*[\(\[]\s*([٠-٩0-9]{1,3}|\*+)\s*[\)\]]", after)
    if m_after and not has_non_paren_fn_markers_inside:
        return True

    inner_paren_vals = [parse_marker_val(m.group(1)) for m in re.finditer(r"\(([٠-٩0-9]{1,3})\)", inner)]
    if inner_paren_vals and not has_non_paren_fn_markers_inside:
        if any(v not in fn_vals_set for v in inner_paren_vals):
            return True
        fn_bodies_for_vals = " ".join(b for v, b in fn_entries_meta if v in inner_paren_vals)
        if re.search(r"\b(?:سورة|آية|الآية)\b", TASHKEEL_RE.sub("", fn_bodies_for_vals)) and not re.search(
            r"(?:في\s+الأصل|في\s+النسخ|في\s+المطبوع|قوله)", TASHKEEL_RE.sub("", fn_bodies_for_vals)
        ):
            return True

    return False


def find_true_quran_spans(
    text: str,
    fn_entries_meta: list[tuple[int | str, str]] | None = None,
    fn_vals_set: set | None = None,
) -> list[tuple[int, int]]:
    entries = fn_entries_meta or []
    vals = fn_vals_set or set()
    spans = []
    for m in re.finditer(r"﴿[^﴾]*﴾", text):
        if is_quranic_floral_span(text, m.start(), m.end(), entries, vals):
            spans.append((m.start(), m.end()))
    return spans


def split_horizontal_footnote_lines(footnotes_raw: str) -> tuple[list[str], int]:
    """
    يفصل الحواشي الأفقية المتعددة المطبوعة في سطر واحد (مثل: `(١) تحت .   (٢) منتظر .   (٣) ينظروا .`)
    بشرط التتابع الرقمي الصارم (`next_val == cur_val + 1` أو `1` بعد `*`) ووجود فاصل فراغي أو ترقيمي،
    مع عدم المساس بأي أرقام مرجعية داخل سياق الحاشية (مثل `طبعة دار الكتب (٢) ١٣٣٠`).
    """
    if not footnotes_raw or not footnotes_raw.strip():
        return [], 0

    out_lines = []
    horiz_splits = 0

    for raw_ln in footnotes_raw.splitlines():
        ln = raw_ln.strip()
        if not ln:
            continue

        # تطبيع بادئة حاشية الاستمرار عبر الصفحات (=) أو [=] إلى =
        if re.match(r"^\s*(?:[\(\[]\s*=\s*[\)\]]|=)\s*", ln):
            ln_body = re.sub(r"^\s*(?:[\(\[]\s*=\s*[\)\]]|=)\s*", "", ln).strip()
            out_lines.append(f"= {ln_body}" if ln_body else "=")
            continue

        m_head = FN_LINE_HEAD_RE.match(ln)
        if not m_head:
            out_lines.append(ln)
            continue

        raw_marker = next((g for g in m_head.groups()[:7] if g is not None), "")
        cur_val = parse_marker_val(raw_marker)
        if cur_val is None:
            out_lines.append(ln)
            continue

        split_positions = [0]
        for m_cand in INLINE_HORIZ_FN_CAND_RE.finditer(ln):
            if m_cand.start() == 0:
                continue
            cand_raw = m_cand.group(1) or m_cand.group(2) or m_cand.group(3) or m_cand.group(4)
            cand_val = parse_marker_val(cand_raw)
            if cand_val is None:
                continue
            prefix_slice = ln[split_positions[-1]:m_cand.start()].rstrip()
            if not prefix_slice:
                continue
            # تجنب الفصل بعد نقطتين رأسيتين أو كلمات الإحالة العددية
            last_words = [TASHKEEL_RE.sub("", w) for w in re.findall(r"[\u0621-\u064A]+", prefix_slice[-25:])]
            if prefix_slice.endswith(":") or (last_words and last_words[-1] in COUNT_NOUNS):
                continue

            is_sequential = (
                (isinstance(cur_val, int) and isinstance(cand_val, int) and cand_val == cur_val + 1)
                or (cur_val == "*" and cand_val == 1)
                or (isinstance(cur_val, int) and cand_val == "*")
            )
            if is_sequential:
                split_positions.append(m_cand.start())
                cur_val = cand_val
                horiz_splits += 1

        if len(split_positions) == 1:
            out_lines.append(ln)
        else:
            for idx_sp, pos in enumerate(split_positions):
                end_pos = split_positions[idx_sp + 1] if idx_sp + 1 < len(split_positions) else len(ln)
                chunk = ln[pos:end_pos].strip()
                if chunk:
                    out_lines.append(chunk)

    return out_lines, horiz_splits


def is_likely_non_fn_token_in_page(matn_no_quran: str, start: int, end: int, raw_tok: str) -> bool:
    """يفحص ما إذا كان الرقم بين قوسين في المتن يمثل رقم قائمة أو قيمة عددية وليس إحالة حاشية."""
    if FOLIO_MARKER_RE.match(matn_no_quran[max(0, start - 3):min(len(matn_no_quran), end + 2)]):
        return True
    before = matn_no_quran[max(0, start - 120):start]
    after = matn_no_quran[end:min(len(matn_no_quran), end + 40)]
    if "قوله تعالى" in before[-90:] or "قال تعالى" in before[-90:] or "سورة" in before[-60:] or "الآية" in before[-50:]:
        return True
    line_start = matn_no_quran.rfind("\n", 0, start) + 1
    prefix_on_line = matn_no_quran[line_start:start].strip()
    if not prefix_on_line:
        return True
    prev_words = [TASHKEEL_RE.sub("", w) for w in re.findall(r"[\u0621-\u064A]+", before[-45:])]
    if any(w in COUNT_NOUNS or w.lstrip("والفب") in COUNT_NOUNS for w in prev_words[-2:]):
        return True
    if re.match(r"^\s*(?:هـ|م|سنة|عام|ورقة|سطر|حديث|آية|[٠-٩0-9]{3,4})\b", after):
        return True
    return False


def anchor_missing_fn_marker_in_matn(
    matn: str,
    marker_val: int | str,
    fn_body: str,
    min_pos: int,
    max_pos: int,
    quran_spans: list[tuple[int, int]] | None = None,
) -> tuple[str, int]:
    """
    يدرج إحالة الحاشية الساقطة مطبعياً في المتن داخل النطاق الرتيب [min_pos, max_pos] للصفحة نفسها،
    باستخدام مطابقة الكلمة المحققة في نص الحاشية (مثل `وفي المطبوع : ويتظاهرون` -> `يظهرون(١)`)
    أو عند نهاية الجملة السابقة، لمنع انزياح ربط الحواشي عبر الصفحات في `lcs_align`.
    """
    marker_str = "(*)" if marker_val == "*" else f"({to_ar_digits(marker_val)})"
    lo = max(0, min(len(matn), min_pos))
    hi = max(lo, min(len(matn), max_pos))
    window = matn[lo:hi]
    if not window.strip():
        window = matn
        lo, hi = 0, len(matn)

    # استخراج الكلمات المرشحة من نص الحاشية (بعد ':' أو داخل «...» أو الكلمات المميزة)
    cand_words = []
    for m_q in re.finditer(r"(?:في\s+(?:الأصل|المطبوع|النسخ\w*|بعض\s+النسخ|[«\"][^»\"]+[»\"])\s*:\s*|«([^»]+)»)([^\s.،؛:«»\(\)\[\]]+)", fn_body):
        w_c = m_q.group(1) or m_q.group(2) or ""
        for sub_w in w_c.split():
            sk = arabic_skeleton(sub_w)
            if len(sk) >= 3:
                cand_words.append((sub_w, sk))
    if not cand_words:
        stop_words = {"كذا", "الأصل", "المطبوع", "النسخة", "النسخ", "سورة", "آية", "الآية", "حديث", "انظر", "راجع", "قوله", "بدلا", "زيادة"}
        for w_raw in re.findall(r"[\u0621-\u064A\u064B-\u065F]+", fn_body):
            w_clean = TASHKEEL_RE.sub("", w_raw)
            if w_clean not in stop_words:
                sk = arabic_skeleton(w_clean)
                if len(sk) >= 3:
                    cand_words.append((w_clean, sk))

    def is_inside_quran(pos_in_matn: int) -> bool:
        if quran_spans is not None:
            return any(qs <= pos_in_matn <= qe for qs, qe in quran_spans)
        b = matn[:pos_in_matn]
        return b.rfind("﴿") > b.rfind("﴾")

    best_insert_pos = None
    for _, cand_sk in cand_words:
        for m_w in re.finditer(r"[\u0621-\u064A\u064B-\u065F]+", window):
            abs_end = lo + m_w.end()
            if is_inside_quran(abs_end):
                continue
            w_sk = arabic_skeleton(m_w.group(0))
            if w_sk and (w_sk == cand_sk or (len(w_sk) >= 3 and len(cand_sk) >= 3 and (w_sk in cand_sk or cand_sk in w_sk))):
                best_insert_pos = abs_end
                break
        if best_insert_pos is not None:
            break

    if best_insert_pos is None:
        # إدراج آمن قبل علامة الترقيم في نهاية الفقرة/السطر ضمن النطاق [lo, hi] خارج الآيات القرآنية
        for m_p in reversed(list(re.finditer(r"[\u0621-\u064A\u064B-\u065F\]»]+(?=\s*[.،؛\n]|$)", window))):
            abs_end = lo + m_p.end()
            if not is_inside_quran(abs_end):
                best_insert_pos = abs_end
                break
    if best_insert_pos is None:
        best_insert_pos = hi

    new_matn = matn[:best_insert_pos] + marker_str + matn[best_insert_pos:]
    return new_matn, best_insert_pos + len(marker_str)


def normalize_page_footnotes_and_markers(matn: str, footnotes_raw: str) -> tuple[str, str, dict]:
    """
    يطبع صيغ الحواشي السفلية وإحالاتها في المتن على مستوى الصفحة الواحدة لضمان التوافق التام 100%
    مع `fn_linker_v4.py`:
      1. شطر الحواشي الأفقية المشتركة في سطر واحد إلى أسطر مستقلة.
      2. توحيد رؤوس الحواشي غير القياسية (`[١]`, `١ -`, `١.`, `¹`, `(*)`, `( * )`, `[*]`, `*`) إلى `(١)` أو `(*)`.
      3. تطبيع إحالات المتن غير القياسية خارج الآيات القرآنية وبما يشمل المتن المشروح بين `﴿...﴾` (`[١]`, `¹`, `(1)`, `هما1`، والنجمة `*`).
      4. موازنة إحالات الصفحة الواحدة (منع الحواشي المشتركة المكررة من سرقة حواشي الصفحة التالية، وتثبيت الإحالات الساقطة).
    """
    stats = {
        "horizontal_splits": 0,
        "non_standard_fn_heads_normalized": 0,
        "non_standard_matn_markers_normalized": 0,
        "shared_markers_spaced": 0,
        "missing_matn_markers_anchored": 0,
    }

    split_lines, horiz_splits = split_horizontal_footnote_lines(footnotes_raw)
    stats["horizontal_splits"] = horiz_splits

    canonical_fn_lines = []
    fn_entries_meta = []  # [(val, body)]

    for ln in split_lines:
        if ln.startswith("="):
            canonical_fn_lines.append(ln)
            continue
        m_head = FN_LINE_HEAD_RE.match(ln)
        if m_head:
            raw_marker = next((g for g in m_head.groups()[:7] if g is not None), "")
            body = (m_head.group(8) or "").strip()
            val = parse_marker_val(raw_marker)
            if val == "*":
                canon_head = "(*)"
            elif isinstance(val, int):
                canon_head = f"({to_ar_digits(val)})"
            else:
                canonical_fn_lines.append(ln)
                continue

            if not ln.startswith(canon_head):
                stats["non_standard_fn_heads_normalized"] += 1
            canon_ln = f"{canon_head} {body}".strip()
            canonical_fn_lines.append(canon_ln)
            fn_entries_meta.append((val, body))
        else:
            canonical_fn_lines.append(ln)

    norm_footnotes_raw = "\n".join(canonical_fn_lines)
    fn_val_counts = {}
    for v, _ in fn_entries_meta:
        fn_val_counts[v] = fn_val_counts.get(v, 0) + 1
    fn_vals_set = set(fn_val_counts.keys())

    if not matn:
        return matn, norm_footnotes_raw, stats

    def _normalize_matn_segment(seg: str) -> str:
        if not seg:
            return seg
        # 1. معالجة علامة النجمة (*) في المتن
        if "*" in fn_vals_set:
            seg, n1 = re.subn(r"\(\s*\*+\s*\)|\[\s*\*+\s*\]", "(*)", seg)
            stats["non_standard_matn_markers_normalized"] += n1
        else:
            seg = re.sub(r"\(\*+\)", "( * )", seg)

        if fn_vals_set:
            # 2. الأقواس الهلالية المتباعدة: ( ١ ) -> (١)
            def _fix_spaced_paren(m: re.Match) -> str:
                v = parse_marker_val(m.group(1))
                if v in fn_vals_set:
                    stats["non_standard_matn_markers_normalized"] += 1
                    return f"({to_ar_digits(v)})"
                return m.group(0)

            seg = re.sub(
                r"\(\s+([٠-٩0-9]{1,2})\s*\)|\(\s*([٠-٩0-9]{1,2})\s+\)",
                lambda m: _fix_spaced_paren(m if m.group(1) else re.match(r"\(\s*([٠-٩0-9]{1,2})\s*\)", m.group(0))),
                seg,
            )

            # 2-ب. الأرقام اللاتينية أو المختلطة داخل أقواس هلالية: (1) -> (١)
            def _fix_ascii_paren(m: re.Match) -> str:
                raw_in = m.group(1)
                v = parse_marker_val(raw_in)
                if v in fn_vals_set:
                    canon_in = to_ar_digits(v)
                    if raw_in != canon_in:
                        stats["non_standard_matn_markers_normalized"] += 1
                        return f"({canon_in})"
                return m.group(0)

            seg = re.sub(r"\(([٠-٩0-9]{1,3})\)", _fix_ascii_paren, seg)

            # 3. الأقواس المعقوفة الرقمية: [١] -> (١) إذا كان الرقم ضمن حواشي الصفحة
            def _fix_brack_marker(m: re.Match) -> str:
                v = parse_marker_val(m.group(1))
                if v in fn_vals_set:
                    stats["non_standard_matn_markers_normalized"] += 1
                    return f"({to_ar_digits(v)})"
                return m.group(0)

            seg = re.sub(r"\[\s*([٠-٩0-9]{1,2})\s*\]", _fix_brack_marker, seg)

            # 4. الأرقام الفوقية Superscript: ¹ -> (١)
            def _fix_sup_marker(m: re.Match) -> str:
                v = parse_marker_val(m.group(1))
                if v in fn_vals_set:
                    stats["non_standard_matn_markers_normalized"] += 1
                    return f"({to_ar_digits(v)})"
                return m.group(0)

            seg = re.sub(r"([¹²³⁴⁵⁶⁷⁸⁹])", _fix_sup_marker, seg)

            # 5. الأرقام الملتصقة بنهاية الكلمة العربية بدون أقواس: هما1 -> هما(١)
            def _fix_attached_bare_digit(m: re.Match) -> str:
                v = parse_marker_val(m.group(1))
                if v in fn_vals_set:
                    stats["non_standard_matn_markers_normalized"] += 1
                    return f"({to_ar_digits(v)})"
                return m.group(0)

            seg = re.sub(
                r"(?<=[\u0621-\u064A\u064B-\u065F])([٠-٩0-9]{1,2})(?=\s|[،.؛:!؟«»\"'\)\]]|$)",
                _fix_attached_bare_digit,
                seg,
            )
        return seg

    # تطبيع إحالات المتن خارج الآيات القرآنية ﴿...﴾ مع دعم المتن المشروح بين ﴿...﴾
    segments = re.split(r"(﴿[^﴾]*﴾)", matn)
    cur_off = 0
    for idx_s, seg in enumerate(segments):
        seg_start = cur_off
        seg_end = cur_off + len(seg)
        cur_off = seg_end
        if not seg:
            continue
        if idx_s % 2 == 1 and seg.startswith("﴿") and seg.endswith("﴾"):
            if is_quranic_floral_span(matn, seg_start, seg_end, fn_entries_meta, fn_vals_set):
                continue
            inner_norm = _normalize_matn_segment(seg[1:-1])
            segments[idx_s] = f"﴿{inner_norm}﴾"
        else:
            segments[idx_s] = _normalize_matn_segment(seg)

    norm_matn = "".join(segments)

    # إذا كانت الصفحة تحتوي حاشية نجمية (*) ولم يُعثر بعد على (*) في المتن، نحول النجمة المنفردة * إلى (*)
    if "*" in fn_vals_set and "(*)" not in norm_matn:
        for idx_s in range(0, len(segments), 2):
            seg = segments[idx_s]
            if "*" in seg:
                seg_new, n_star = re.subn(r"(?<!\*)\*(?!\*)", "(*)", seg, count=fn_val_counts["*"])
                if n_star:
                    segments[idx_s] = seg_new
                    stats["non_standard_matn_markers_normalized"] += n_star
                    break
        norm_matn = "".join(segments)

    # موازنة الإحالات داخل الصفحة الواحدة لضمان عدم سرقة حواشي الصفحات المجاورة في lcs_align
    if fn_vals_set:
        quran_spans = find_true_quran_spans(norm_matn, fn_entries_meta, fn_vals_set)

        def _in_quran(pos: int) -> bool:
            return any(qs <= pos < qe for qs, qe in quran_spans)

        tok_matches_by_val: dict[int | str, list[re.Match]] = {}
        for m_tok in re.finditer(r"\(([٠-٩0-9]+|\*+)\)", norm_matn):
            if _in_quran(m_tok.start()):
                continue
            if FOLIO_MARKER_RE.match(norm_matn[max(0, m_tok.start() - 3):min(len(norm_matn), m_tok.end() + 2)]):
                continue
            v = parse_marker_val(m_tok.group(1))
            if v is not None:
                tok_matches_by_val.setdefault(v, []).append(m_tok)

        spans_to_space = []
        for v, target_k in fn_val_counts.items():
            m_list = tok_matches_by_val.get(v, [])
            if len(m_list) > target_k >= 1:
                primary = [m for m in m_list if not is_likely_non_fn_token_in_page(norm_matn, m.start(), m.end(), m.group(0))]
                secondary = [m for m in m_list if is_likely_non_fn_token_in_page(norm_matn, m.start(), m.end(), m.group(0))]
                ordered_keep = (primary + secondary)[:target_k]
                keep_starts = {m.start() for m in ordered_keep}
                for m in m_list:
                    if m.start() not in keep_starts:
                        spans_to_space.append((m.start(), m.end(), m.group(1), True))

        for v, m_list in tok_matches_by_val.items():
            if v not in fn_val_counts:
                for m in m_list:
                    if norm_matn[:m.start()].rstrip().endswith("﴾") or is_likely_non_fn_token_in_page(
                        norm_matn, m.start(), m.end(), m.group(0)
                    ):
                        spans_to_space.append((m.start(), m.end(), m.group(1), False))

        if spans_to_space:
            spans_to_space.sort(key=lambda x: x[0], reverse=True)
            for sp_s, sp_e, inner_m, is_shared_fn in spans_to_space:
                norm_matn = norm_matn[:sp_s] + f"( {inner_m} )" + norm_matn[sp_e:]
                if is_shared_fn:
                    stats["shared_markers_spaced"] += 1

        quran_spans = find_true_quran_spans(norm_matn, fn_entries_meta, fn_vals_set)
        tok_positions_by_val: dict[int | str, list[tuple[int, int]]] = {}
        for m_tok in re.finditer(r"\(([٠-٩0-9]+|\*+)\)", norm_matn):
            if any(qs <= m_tok.start() < qe for qs, qe in quran_spans):
                continue
            v = parse_marker_val(m_tok.group(1))
            if v is not None:
                tok_positions_by_val.setdefault(v, []).append((m_tok.start(), m_tok.end()))

        for idx_fn, (v, fn_body) in enumerate(fn_entries_meta):
            target_k = fn_val_counts.get(v, 0)
            cur_k = len(tok_positions_by_val.get(v, []))
            if cur_k >= target_k:
                continue
            min_pos = 0
            max_pos = len(norm_matn)
            if isinstance(v, int):
                for prev_v, pos_list in tok_positions_by_val.items():
                    if isinstance(prev_v, int) and prev_v < v and pos_list:
                        min_pos = max(min_pos, pos_list[-1][1])
                for next_v, pos_list in tok_positions_by_val.items():
                    if isinstance(next_v, int) and next_v > v and pos_list:
                        max_pos = min(max_pos, pos_list[0][0])

            norm_matn, ins_end = anchor_missing_fn_marker_in_matn(
                norm_matn, v, fn_body, min_pos, max_pos, quran_spans=quran_spans
            )
            stats["missing_matn_markers_anchored"] += 1
            quran_spans = find_true_quran_spans(norm_matn, fn_entries_meta, fn_vals_set)
            tok_positions_by_val = {}
            for m_tok in re.finditer(r"\(([٠-٩0-9]+|\*+)\)", norm_matn):
                if any(qs <= m_tok.start() < qe for qs, qe in quran_spans):
                    continue
                v_re = parse_marker_val(m_tok.group(1))
                if v_re is not None:
                    tok_positions_by_val.setdefault(v_re, []).append((m_tok.start(), m_tok.end()))

    return norm_matn, norm_footnotes_raw, stats


def _get_page_field(p: dict, ext_in: dict, *keys: str, default=""):
    for k in keys:
        if k in ext_in and ext_in[k] not in (None, ""):
            return ext_in[k]
        if k in p and p[k] not in (None, ""):
            return p[k]
    return default


def check_delimiters_balanced_and_preserved(matn_top: str, full_matn: str) -> bool:
    """يتحقق من توازن علامات بداية ونهاية المتن المشروح (`﴿...﴾`, `(...)`, `[...]`, `«...»`) وحفظها الحرفي 100%."""
    if not matn_top:
        return True
    if matn_top not in full_matn:
        return False
    for op, cl in (("﴿", "﴾"), ("(", ")"), ("[", "]"), ("«", "»")):
        if matn_top.count(op) != matn_top.count(cl):
            return False
    return True


def extract_and_normalize_page_zones(p: dict, update_in_place: bool = True) -> dict:
    """
    يستخلص ويطبع جميع مناطق الصفحة (المتن الأعلى `matn_top`، الشرح الأسفل `sharh_body`، المتن الموحد `matn`/`text`،
    الهامش الجانبي `margin_notes`، والحواشي السفلية `footnotes` بجميع صيغها النصية والمهيكلة) مع الحفاظ الحرفي 100%.
    """
    ext_in = p.get("extracted") if isinstance(p.get("extracted"), dict) else {}

    raw_printed_page = _get_page_field(p, ext_in, "printed_page", "page_number", default="")
    raw_running_header = _get_page_field(p, ext_in, "running_header", "header", default="")
    raw_matn_top = _get_page_field(p, ext_in, "matn_top", "top_matn", default="")
    raw_sharh_body = _get_page_field(p, ext_in, "sharh_body", "sharh", default="")
    raw_matn = _get_page_field(p, ext_in, "matn", default="")
    raw_text = _get_page_field(p, ext_in, "text", "body", default="")
    raw_margin_notes = _get_page_field(p, ext_in, "margin_notes", "hashiya_margin", "margin", default="")
    raw_footnotes_val = _get_page_field(p, ext_in, "footnotes", "footnotes_raw", "fn", default="")

    printed_page, st_pg = repair_line_breaks_and_mixed_digits(str(raw_printed_page), is_page_number=True)
    running_header, st_rh = repair_line_breaks_and_mixed_digits(str(raw_running_header))
    matn_top, st_mt = repair_line_breaks_and_mixed_digits(str(raw_matn_top))
    sharh_body, st_sh = repair_line_breaks_and_mixed_digits(str(raw_sharh_body))
    matn_base, st_mb = repair_line_breaks_and_mixed_digits(str(raw_matn))
    text_base, st_tb = repair_line_breaks_and_mixed_digits(str(raw_text))
    margin_notes, st_mn = repair_line_breaks_and_mixed_digits(str(raw_margin_notes))

    fn_coerced_str, fn_input_format, fn_struct_count = coerce_footnotes_to_raw_str(raw_footnotes_val)
    footnotes_pre, st_fn = repair_line_breaks_and_mixed_digits(fn_coerced_str)

    if matn_base and text_base:
        if text_base in matn_base:
            extra_body = matn_base
        elif matn_base in text_base:
            extra_body = text_base
        else:
            extra_body = f"{matn_base}\n{text_base}"
    else:
        extra_body = matn_base or text_base

    # إذا لم يُفصل matn_top وsharh_body في حقلين مستقلين ولكن نص المتن يحوي خط فصل صريح بين المتن الأعلى والشرح الأسفل
    if not matn_top and not sharh_body and extra_body:
        eb_lines = extra_body.splitlines()
        div_idx = None
        for idx_l, ln_eb in enumerate(eb_lines):
            if 0 < idx_l < len(eb_lines) - 1 and SHARH_ZONE_DIVIDER_LINE_RE.match(ln_eb):
                div_idx = idx_l
                break
        if div_idx is not None:
            matn_top = "\n".join(eb_lines[:div_idx]).strip()
            sharh_body = "\n".join(eb_lines[div_idx:]).strip()
            extra_body = ""
        else:
            # كشف المتن الأعلى المحصور بين ﴿...﴾ أو (...) في صدر الصفحة متبوعاً بسطر يبدأ بـ «الشرح:» أو «قال الشارح:»
            for idx_l in range(1, min(6, len(eb_lines))):
                ln_norm = TASHKEEL_RE.sub("", eb_lines[idx_l].strip())
                if re.match(r"^(?:الشرح|قال\s+الشارح)\s*:", ln_norm):
                    top_cand = "\n".join(eb_lines[:idx_l]).strip()
                    if (top_cand.startswith("﴿") and "﴾" in top_cand) or (top_cand.startswith("(") and ")" in top_cand):
                        matn_top = top_cand
                        sharh_body = "\n".join(eb_lines[idx_l:]).strip()
                        extra_body = ""
                    break

    if matn_top or sharh_body:
        if matn_top and sharh_body and extra_body == f"{matn_top}\n{sharh_body}":
            extra_body = ""
        elif matn_top and extra_body == matn_top:
            extra_body = ""
        elif sharh_body and extra_body == sharh_body:
            extra_body = ""
        elif extra_body:
            rem = extra_body
            if matn_top and matn_top in rem:
                rem = rem.replace(matn_top, "", 1).strip()
            if sharh_body and sharh_body in rem:
                rem = rem.replace(sharh_body, "", 1).strip()
            extra_body = rem

    zone_keys = []
    zone_texts = []
    for zk, zt in (("matn_top", matn_top), ("sharh_body", sharh_body), ("extra_body", extra_body)):
        if zt:
            zone_keys.append(zk)
            zone_texts.append(zt)

    combined_for_norm = ZONE_SENTINEL.join(zone_texts)
    norm_combined, footnotes_raw, fn_norm_stats = normalize_page_footnotes_and_markers(combined_for_norm, footnotes_pre)

    if zone_keys:
        split_Back = norm_combined.split(ZONE_SENTINEL)
        zone_map = {zk: (split_Back[i] if i < len(split_Back) else "") for i, zk in enumerate(zone_keys)}
        matn_top = zone_map.get("matn_top", "")
        sharh_body = zone_map.get("sharh_body", "")
        extra_body = zone_map.get("extra_body", "")
        matn = "\n".join(part for part in (matn_top, sharh_body, extra_body) if part)
    else:
        matn = norm_combined

    all_repair_dicts = (st_pg, st_rh, st_mt, st_sh, st_mb, st_tb, st_mn, st_fn)
    merged_stats = dict(fn_norm_stats)
    merged_stats["persian_digits_fixed"] = sum(d["persian_digits_fixed"] for d in all_repair_dicts)
    merged_stats["persian_chars_fixed"] = sum(d["persian_chars_fixed"] for d in all_repair_dicts)
    merged_stats["line_break_splits_repaired"] = sum(d["line_break_splits_repaired"] for d in all_repair_dicts)
    merged_stats["mixed_digits_normalized"] = sum(d["mixed_digits_normalized"] for d in all_repair_dicts)
    merged_stats["structured_footnote_items_coerced"] = fn_struct_count

    has_multi_zone = bool(matn_top or sharh_body)
    delims_ok = check_delimiters_balanced_and_preserved(matn_top, matn)
    has_continuation_fn = any(ln.strip().startswith("=") for ln in footnotes_raw.splitlines() if ln.strip())

    if update_in_place:
        ext_out = dict(ext_in)
        ext_out["printed_page"] = printed_page
        ext_out["running_header"] = running_header
        ext_out["matn"] = matn
        if matn_top:
            ext_out["matn_top"] = matn_top
        if sharh_body:
            ext_out["sharh_body"] = sharh_body
        ext_out["margin_notes"] = margin_notes
        ext_out["footnotes"] = footnotes_raw
        if fn_input_format != "str":
            ext_out["footnotes_structured"] = raw_footnotes_val
        ext_out.setdefault("uncertain_words", p.get("uncertain_words", []))
        p["extracted"] = ext_out

    return {
        "printed_page": printed_page,
        "running_header": running_header,
        "matn_top": matn_top,
        "sharh_body": sharh_body,
        "extra_body": extra_body,
        "matn": matn,
        "margin_notes": margin_notes,
        "footnotes_raw": footnotes_raw,
        "footnotes_input_format": fn_input_format,
        "has_multi_zone": has_multi_zone,
        "has_continuation_fn": has_continuation_fn,
        "matn_top_delimiters_preserved": delims_ok,
        "normalization_stats": merged_stats,
    }


def parse_footnote_lines_verbatim(
    footnotes_raw: str,
    pdf_page: int,
    printed_page: str,
    pg_int: int,
    book_id: int,
    juz: int = 1,
    prev_stream: list[dict] | None = None,
) -> list[dict]:
    """
    يحلل أسطر الحاشية السفلية إلى سجلات مهيكلة مع الحفاظ الكامل على النص الحرفي لكل حاشية.
    يدعم الصيغ: (١) ، [١] ، ١ - ، ١. ، (*) ، والأسطر المكملة عبر الصفحات (`= ...` أو الأسطر غير المرقمة في مطلع الحاشية).
    """
    if not footnotes_raw or not footnotes_raw.strip():
        return []
    entries = []
    for raw_ln in footnotes_raw.splitlines():
        ln = raw_ln.strip()
        if not ln:
            continue
        if ln.startswith("="):
            if entries:
                entries[-1]["text"] += " / " + ln
                entries[-1]["body"] += " / " + ln
                entries[-1]["continued"] = True
            elif prev_stream:
                prev_stream[-1]["text"] += " / " + ln
                prev_stream[-1]["body"] += " / " + ln
                prev_stream[-1]["continued"] = True
                prev_stream[-1].setdefault("continued_on_pages", []).append(pg_int)
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
            continue

        m = FN_LINE_HEAD_RE.match(ln)
        if m:
            marker_str = next((g for g in m.groups()[:7] if g is not None), "")
            body = (m.group(8) or "").strip()
            val = parse_marker_val(marker_str)
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
        elif prev_stream:
            prev_stream[-1]["text"] += " / " + ln
            prev_stream[-1]["body"] += " / " + ln
            prev_stream[-1]["continued"] = True
            prev_stream[-1].setdefault("continued_on_pages", []).append(pg_int)
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


def normalize_heading_key(text: str) -> str:
    """تطبيع نص العنوان أو رأس الصفحة الجاري للمقارنة ومنع تكرار تقطيع الرؤوس الجارية."""
    s = TASHKEEL_RE.sub("", text or "")
    s = re.sub(r"\s*[\(\[]\s*[٠-٩0-9\*]{1,3}\s*[\)\]]\s*", " ", s)
    s = re.sub(r"[^\u0621-\u064A\s]", " ", s)
    return " ".join(s.split())


def is_candidate_heading_line(line: str, running_header: str = "", seen_heading_keys: set[str] | None = None) -> tuple[bool, int, str]:
    """
    يفحص ما إذا كان السطر عنوان باب/فصل يصلح كبداية جزء هيكلي دون حذف السطر من المتن.
    يدعم العناوين المستقلة، وعناوين المتون المحصورة بين قوسين زهريين `﴿باب ...﴾`،
    والعناوين المدمجة في مطلع الفقرة (Run-in Headings مثل: `القسم الأول: المفتي المستقل، وشرطه: ...`)
    ويمنع الرؤوس الجارية المتكررة (Running Headers) من تقطيع الأجزاء خطأً.
    يرجع (is_heading, level, clean_heading_title).
    """
    s = line.strip()
    if not s:
        return False, 0, ""
    if s.startswith(("[ص:", "[هامش جانبي", "«", "---", "───", "===")):
        return False, 0, ""

    # إزالة أرقام الحواشي الطرفية من نهاية العنوان عند الفحص
    core = re.sub(r"\s*[\(\[]\s*[٠-٩0-9\*]{1,3}\s*[\)\]]\s*$", "", s).strip()

    # دعم عناوين الأبواب والفصول الموضوعة بين قوسين زهريين في أعلى صفحات الشروح مثل: ﴿فصل في شروط الصلاة﴾
    if core.startswith("﴿"):
        if core.endswith("﴾") and not re.search(r"\([٠-٩0-9]+\)", core):
            inner_floral = core[1:-1].strip()
            inner_norm = TASHKEEL_RE.sub("", inner_floral).strip()
            if HEADING_KEYWORDS_RE.match(inner_norm) and 1 <= len(inner_floral.split()) <= 12:
                core = inner_floral
            else:
                return False, 0, ""
        else:
            return False, 0, ""

    # دعم العناوين المدمجة في أول السطر (Run-in Headings) مثل: `القسم الأوَّل: المفتي المستقل، وشَرْطُهُ: أنْ يكونَ...`
    norm_s = TASHKEEL_RE.sub("", core).strip()
    if HEADING_KEYWORDS_RE.match(norm_s):
        m_runin = re.match(
            r"^((?:كتاب|الكتاب|باب|الباب|فصل|الفصل|مسألة|المسألة|مبحث|المبحث|مطلب|المطلب|فرع|الفرع|"
            r"قاعدة|القاعدة|تنبيه|التنبيه|خاتمة|الخاتمة|تتمة|القول في|القسم|حاشية)\b[^،؛.!\n]{2,65}?)"
            r"\s*(?:،\s+و|،\s+(?:شَرْط|شرط|حُكْم|حكم|معن|فإن|وفيه|اعلم|قال)|-\s+|\s+وشَرْط|\s+وشرط)",
            core,
        )
        if m_runin:
            cand_prefix = m_runin.group(1).strip().rstrip(":،-")
            prefix_words = cand_prefix.split()
            if 2 <= len(prefix_words) <= 10:
                core = cand_prefix

    if len(core) > 110:
        return False, 0, ""
    words = core.split()
    if not (1 <= len(words) <= 14):
        return False, 0, ""
    if re.search(r"[.؟!؛،]\s*$", core):
        return False, 0, ""
    if not CHAPTER_HEADING_RE.match(core):
        return False, 0, ""
    norm_core = TASHKEEL_RE.sub("", core).strip()
    if EDITOR_HEADING_GUARD_RE.search(norm_core):
        return False, 0, ""

    h_key = normalize_heading_key(core)
    if running_header:
        rh_key = normalize_heading_key(running_header)
        if rh_key and (h_key == rh_key or f"كتاب {rh_key}" == h_key) and seen_heading_keys and h_key in seen_heading_keys:
            return False, 0, ""
    if seen_heading_keys is not None and h_key in seen_heading_keys and len(words) >= 2:
        return False, 0, ""

    if re.match(r"^(?:كتاب|الكتاب)\b", norm_core):
        return True, 1, core
    if re.match(r"^(?:باب|الباب|القسم|القول في|حاشية)\b", norm_core) or (core.startswith("[") and core.endswith("]")):
        return True, 2, core.strip("[]").strip() or core
    return True, 3, core


def detect_multiline_heading(matn_lines: list[str], idx: int, running_header: str = "", seen_heading_keys: set[str] | None = None) -> tuple[bool, int, str, int]:
    """
    يكتشف العناوين المركبة أو الممتدة عبر عدة أسطر متتالية في المتن:
      1. عنوان معقوف متعدد الأسطر: `[موقف من مواقف الشيخ / في / إبطال حيل أهل الطرق الدجالين](١)`
      2. عنوان تراثي مركب من سطرين: `الباب الأول` متبوعاً بـ `في شروط المفتي وأحكامه`
    يرجع (is_heading, level, clean_title, lines_consumed).
    """
    ln0 = matn_lines[idx].strip()
    # 1. عنوان معقوف متعدد الأسطر يبدأ بـ '[' ولا يغلق في نفس السطر
    if ln0.startswith("[") and "]" not in ln0 and idx + 1 < len(matn_lines):
        acc = [ln0]
        for k in range(1, min(4, len(matn_lines) - idx)):
            nxt = matn_lines[idx + k].strip()
            if nxt.startswith(("[ص:", "[هامش جانبي", "﴿")):
                break
            acc.append(nxt)
            if "]" in nxt:
                joined = " ".join(acc)
                joined_clean = re.sub(r"\s*[\(\[]\s*[٠-٩0-9\*]{1,3}\s*[\)\]]\s*$", "", joined).strip()
                if joined_clean.startswith("[") and joined_clean.endswith("]"):
                    inner = joined_clean[1:-1].strip()
                    if 2 <= len(inner.split()) <= 18 and not EDITOR_HEADING_GUARD_RE.search(TASHKEEL_RE.sub("", inner)):
                        h_key = normalize_heading_key(inner)
                        if seen_heading_keys is not None and h_key in seen_heading_keys:
                            return False, 0, "", 1
                        return True, 2, inner, k + 1
                break

    # 2. فحص السطر الحالي كعنوان مفرد أو مركب مع السطر التابع له
    is_h, h_lvl, h_clean = is_candidate_heading_line(ln0, running_header=running_header, seen_heading_keys=seen_heading_keys)
    if not is_h:
        return False, 0, "", 1

    # إذا كان العنوان قصيراً (مثل: `الباب الأول` أو `فصل`) ويتبعه مباشرةً سطر عنوان فرعي قصير يبدأ بـ `في ` أو عنوان ثانٍ
    if idx + 1 < len(matn_lines) and len(h_clean.split()) <= 4 and not ln0.startswith("["):
        ln1 = matn_lines[idx + 1].strip()
        ln1_core = re.sub(r"\s*[\(\[]\s*[٠-٩0-9\*]{1,3}\s*[\)\]]\s*$", "", ln1).strip()
        ln1_norm = TASHKEEL_RE.sub("", ln1_core).strip()
        if (
            1 <= len(ln1_core.split()) <= 10
            and not re.search(r"[.؟!؛،:]\s*$", ln1_core)
            and re.match(r"^(?:في|فيما|بيان|ذكر|حكم|شروط|آداب)\b", ln1_norm)
        ):
            combined = f"{h_clean} {ln1_core}".strip()
            return True, h_lvl, combined, 2

    return True, h_lvl, h_clean, 1


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
    normalization_totals = {
        "horizontal_splits": 0,
        "non_standard_fn_heads_normalized": 0,
        "non_standard_matn_markers_normalized": 0,
        "shared_markers_spaced": 0,
        "missing_matn_markers_anchored": 0,
        "cross_page_continuations_merged": 0,
        "line_break_splits_repaired": 0,
        "mixed_digits_normalized": 0,
        "structured_footnote_items_coerced": 0,
        "persian_digits_fixed": 0,
        "persian_chars_fixed": 0,
    }

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
                "matn_top": "",
                "sharh_body": "",
                "has_multi_zone": False,
                "matn_top_delimiters_preserved": True,
                "matn": "",
                "margin_notes": "",
                "footnotes_raw": "",
                "footnotes_input_format": "str",
                "footnotes_parsed": [],
                "char_counts": {"matn": 0, "matn_top": 0, "sharh_body": 0, "margin_notes": 0, "footnotes": 0},
            })
            continue

        zone_info = extract_and_normalize_page_zones(p, update_in_place=True)
        printed_page = zone_info["printed_page"]
        running_header = zone_info["running_header"]
        matn_top = zone_info["matn_top"]
        sharh_body = zone_info["sharh_body"]
        matn = zone_info["matn"]
        margin_notes = zone_info["margin_notes"]
        footnotes_raw = zone_info["footnotes_raw"]
        page_norm_stats = zone_info["normalization_stats"]

        for k_st, v_st in page_norm_stats.items():
            normalization_totals[k_st] = normalization_totals.get(k_st, 0) + v_st

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

        matn_lines_page = [ln.strip() for ln in matn.splitlines() if ln.strip()]
        for ln_i, ln in enumerate(matn_lines_page):
            source_matn_lines_all.append(ln)
            if not inferred_first_heading:
                is_h, _, h_title, _ = detect_multiline_heading(matn_lines_page, ln_i, running_header=running_header)
                if is_h:
                    inferred_first_heading = h_title

        for ln in margin_notes.splitlines():
            if ln.strip():
                source_margin_lines_all.append(ln.strip())

        if margin_notes:
            margin_notes_by_page[str(pg_int)] = margin_notes

        fn_parsed = parse_footnote_lines_verbatim(
            footnotes_raw,
            pdf_page,
            pg_label,
            pg_int,
            book_id,
            juz=juz,
            prev_stream=parsed_footnotes_all,
        )
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
            "matn_top": matn_top,
            "sharh_body": sharh_body,
            "has_multi_zone": zone_info["has_multi_zone"],
            "matn_top_delimiters_preserved": zone_info["matn_top_delimiters_preserved"],
            "matn": matn,
            "margin_notes": margin_notes,
            "footnotes_raw": footnotes_raw,
            "footnotes_input_format": zone_info["footnotes_input_format"],
            "footnotes_parsed": fn_parsed,
            "normalization_stats": page_norm_stats,
            "char_counts": {
                "matn": len(matn),
                "matn_top": len(matn_top),
                "sharh_body": len(sharh_body),
                "margin_notes": len(margin_notes),
                "footnotes": len(footnotes_raw),
            },
        })

    normalization_totals["cross_page_continuations_merged"] = sum(
        1 for fn_e in parsed_footnotes_all if fn_e.get("continued")
    )

    effective_title = title.strip() or inferred_first_heading or f"كتاب {book_slug}"
    if EDITOR_HEADING_GUARD_RE.search(TASHKEEL_RE.sub("", effective_title)):
        effective_title = f"متن {effective_title}"

    # 2. تقطيع الصفحات إلى أجزاء هيكلية (0000.json .. 0NNN.json) بدون ضياع أي حرف
    # ملاحظة حاسمة: نحافظ على سطر العنوان داخل حقل text أيضاً لضمان بقاء أي إحالة حاشية (١) في العنوان قابلة للربط في fn_linker_v4
    raw_segments = []
    seen_heading_keys: set[str] = set()
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
        running_header = pg_rec.get("running_header", "")
        matn_lines = [ln.strip() for ln in pg_rec["matn"].splitlines() if ln.strip()]

        if cur_seg["pg_start"] is None:
            cur_seg["pg_start"] = pg_int

        page_marker_emitted = False
        idx_ln = 0
        while idx_ln < len(matn_lines):
            is_h, h_lvl, h_clean, consumed = detect_multiline_heading(
                matn_lines,
                idx_ln,
                running_header=running_header,
                seen_heading_keys=seen_heading_keys,
            )
            if is_h:
                h_key = normalize_heading_key(h_clean)
                if h_key:
                    seen_heading_keys.add(h_key)
                cur_words = count_arabic_words("\n".join(cur_seg["lines"]))
                if cur_words >= 18:
                    raw_segments.append(cur_seg)
                    new_lines = []
                    if not page_marker_emitted:
                        new_lines.append(pg_rec["page_marker"])
                        page_marker_emitted = True
                    for c_i in range(consumed):
                        new_lines.append(matn_lines[idx_ln + c_i])
                    cur_seg = {
                        "title": h_clean,
                        "level": h_lvl,
                        "pg_start": pg_int,
                        "lines": new_lines,
                        "pages_touched": [pg_int],
                    }
                    idx_ln += consumed
                    continue
                elif cur_seg["title"].startswith("صدر الكتاب"):
                    cur_seg["title"] = h_clean
                    cur_seg["level"] = h_lvl
                else:
                    cur_seg["title"] = f"{cur_seg['title']} — {h_clean}"

            if not page_marker_emitted:
                cur_seg["lines"].append(pg_rec["page_marker"])
                page_marker_emitted = True
            for c_i in range(consumed):
                cur_seg["lines"].append(matn_lines[idx_ln + c_i])
            if pg_int not in cur_seg["pages_touched"]:
                cur_seg["pages_touched"].append(pg_int)
            idx_ln += consumed

        if not page_marker_emitted:
            cur_seg["lines"].append(pg_rec["page_marker"])
            page_marker_emitted = True
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
        "cross_page_continuations_merged": normalization_totals["cross_page_continuations_merged"],
        "normalization_totals": normalization_totals,
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
        "normalization_totals": normalization_totals,
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
        "schema": "turath_pdf_to_preflight_adapter_v2.2",
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
        "multi_zone_pages": sum(1 for p in pages_preflight if p.get("has_multi_zone")),
        "total_parts_built": len(snapshot_parts),
        "total_footnotes_count": len(parsed_footnotes_all),
        "cross_page_continuations_merged": normalization_totals["cross_page_continuations_merged"],
        "normalization_totals": normalization_totals,
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
    من المتن الأصلي (بما يشمل المتن الأعلى `matn_top` وعلامات بدايته ونهايته، والشرح الأسفل `sharh_body`)
    أو الهوامش الجانبية أو الحواشي السفلية عبر جميع ملفات المخرجات.
    """
    errors = []
    src_body_lines = []
    src_matn_chars = 0
    src_matn_top_chars = 0
    src_sharh_body_chars = 0
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
        matn_top = pg.get("matn_top", "")
        sharh_body = pg.get("sharh_body", "")
        margin = pg["margin_notes"]
        fn_raw = pg["footnotes_raw"]

        src_matn_chars += len(matn)
        src_matn_top_chars += len(matn_top)
        src_sharh_body_chars += len(sharh_body)
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
        if matn_top:
            if matn_top not in book_matn_txt:
                errors.append(f"Page {p_num}: verbatim matn_top missing in book_matn.txt")
            if not pg.get("matn_top_delimiters_preserved", True):
                errors.append(f"Page {p_num}: matn_top opening/closing delimiters unbalanced or lost")
        if sharh_body and sharh_body not in book_matn_txt:
            errors.append(f"Page {p_num}: verbatim sharh_body missing in book_matn.txt")
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
        "source_matn_top_chars": src_matn_top_chars,
        "source_sharh_body_chars": src_sharh_body_chars,
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
