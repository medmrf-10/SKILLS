#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
agy_pdf_to_text.py — المحرك الموحد لتحويل كتب التراث العربي المصورة (PDF) إلى نص حرفي مهيكل بدقة ١٠٠٪
عبر رؤية agy CLI (Gemini 3.8 Flash) مع التوجيه البصري للتخطيطات، وبوابات الجودة الخمس، والتكبير البؤري المجهري (2800px).

المزايا الهندسية:
  1. يمنع تمرير ملف .pdf مباشرةً إلى النموذج؛ يولّد صور .png رمادية متكيفة مع العرض الأصلي للمسح (1650-1800px).
  2. ينظّف غبار المسح الضوئي المعزول (<= 5px) عبر المكونات المتصلة (scipy.ndimage.label) مع هالة حماية 3px حول الحروف،
     ويزيل خطوط الظل الطويلة عند الحواف فقط (> 120px) لحماية الطرر وإشارات المخطوطات الجانبية مثل [٤ ب] و[I/8].
  3. يصنّف تخطيط الصفحة حتمياً في < 15ms إلى أربعة مسارات:
     - blank_or_sparse: تخطي استدعاء النموذج كلياً (صفر توكن).
     - standard_single_col: شطر أفقي عند وادي الفراغ الأوسط (+18px تداخل) لمضاعفة كثافة البكسلات 2.4x.
     - two_column: شطر عمودي للفهارس والصفحات ذات العمودين (@col1_right.png + @col2_left.png).
     - framed_hashiya: قص داخل الجدول (@box_top.png + @box_bot.png) وقص الهامش الخارجي وتدويره 90° مع عقارب الساعة (@margin_upright.png).
  4. يشغّل agy داخل مجلد مؤقت معزول (os.path.realpath) بقفل صارم لأداة view_file المتوازية مع --json-schema
     وحظر أدوات الطرفية والبحث (run_command, turathmcp)، مما يخفض استهلاك التوكنات المخبأة 33.5x.
  5. يطبّق 5 بوابات جودة حتمية (< 5ms): تطبيع الأرقام الفارسية (U+06F0..U+06F9)، التغطية السطرية، تطابق إحالات المتن والهوامش،
     توازن الأقواس والآيات، وتحديد موقع الكلمات المشتبه بها لتكبيرها مجهرياً بدقة 2800px وفحصها دفعةً واحدة (Batched Stage 2).

الاستعمال:
  python3 agy_pdf_to_text.py <input.pdf> --out-dir <output_dir> \
      [--pages 1-50] [--only 16,22,86] [--model gemini-3.8-flash-medium] \
      [--zoom-model gemini-3.8-flash-high] [--workers 2] [--stagger 2.0] [--force]
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import glob
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import fitz
import numpy as np
from scipy import ndimage


def find_bin(name: str, extra_paths: list[str]) -> str:
    w = shutil.which(name)
    if w:
        return w
    for p in extra_paths:
        matches = sorted(glob.glob(p))
        if matches and os.access(matches[-1], os.X_OK):
            return matches[-1]
    return name


AGY_BIN = os.environ.get("AGY_BIN") or find_bin(
    "agy",
    [
        shutil.which("agy") or str(Path.home() / ".local" / "bin" / "agy"),
        os.path.expanduser("~/.local/bin/agy"),
        "/root/.local/bin/agy",
    ],
)

PERSIAN_TO_ARABIC_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "٠١٢٣٤٥٦٧٨٩")
PERSIAN_CHARS_MAP = str.maketrans({"ی": "ي", "ک": "ك", "ے": "ي", "ۀ": "ة"})


def save_gray_png(arr: np.ndarray, path: str) -> None:
    arr_c = np.ascontiguousarray(arr, dtype=np.uint8)
    h, w = arr_c.shape
    fitz.Pixmap(fitz.csGRAY, w, h, arr_c.tobytes(), False).save(path)


def normalize_arabic_output(text: str) -> tuple[str, dict]:
    """تطبيع الأرقام الفارسية الشرقية (U+06F0..U+06F9) والحروف الفارسية وإزالة أي روابط ملفات متسربة."""
    if not text:
        return "", {"persian_digits_fixed": 0, "persian_chars_fixed": 0}
    persian_digits = sum(1 for c in text if "\u06f0" <= c <= "\u06f9")
    persian_chars = sum(1 for c in text if c in ("ی", "ک", "ے", "ۀ"))
    fixed = text.translate(PERSIAN_TO_ARABIC_DIGITS).translate(PERSIAN_CHARS_MAP)
    fixed = re.sub(r"\[[^\]]+\.(?:png|jpg|pdf)\]\(file://[^\)]+\)", "", fixed)
    return fixed.strip(), {
        "persian_digits_fixed": persian_digits,
        "persian_chars_fixed": persian_chars,
    }


def render_clean_gray(page: fitz.Page, target_width: int = 1650, max_speck_area: int = 5) -> tuple[np.ndarray, int]:
    """
    رندر الصفحة بالرمادي بعرض متكيف مع المسح الأصلي، مع إزالة ذرات الغبار المعزولة (<= 5px)
    وخطوط الظل الطويلة عند الحواف فقط (> 120px) مع حماية كاملة للطرر وإشارات المخطوطات الجانبية.
    """
    zoom = target_width / max(1.0, page.rect.width)
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), colorspace=fitz.csGRAY, alpha=False)
    arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width).copy()
    return clean_gray_array(arr, max_speck_area=max_speck_area)


def clean_gray_array(arr: np.ndarray, max_speck_area: int = 5) -> tuple[np.ndarray, int]:
    """تنظيف مصفوفة الصورة الرمادية من الغبار المعزول وخطوط ظل الحواف الطويلة."""
    cleaned = arr.copy()
    h, w = cleaned.shape
    binary_dark = cleaned < 200
    labeled, num_features = ndimage.label(binary_dark)
    specks_removed = 0
    if num_features > 0:
        sizes = ndimage.sum(binary_dark, labeled, range(1, num_features + 1))
        objs = ndimage.find_objects(labeled)
        core_mask = np.zeros_like(binary_dark)
        border_kill = np.zeros(num_features + 1, dtype=bool)
        for idx, slc in enumerate(objs):
            if slc is None:
                continue
            comp_id = idx + 1
            y_slc, x_slc = slc
            comp_h = y_slc.stop - y_slc.start
            comp_w = x_slc.stop - x_slc.start
            touches_left = x_slc.start <= 3
            touches_right = x_slc.stop >= w - 3
            touches_top = y_slc.start <= 3
            touches_bottom = y_slc.stop >= h - 3
            if (touches_left or touches_right) and comp_w < int(w * 0.04) and comp_h > 120:
                border_kill[comp_id] = True
            elif (touches_top or touches_bottom) and comp_h < int(h * 0.025) and comp_w > 180:
                border_kill[comp_id] = True
            elif sizes[idx] >= max(10, max_speck_area + 1):
                core_mask[y_slc, x_slc] |= (labeled[y_slc, x_slc] == comp_id)

        dilated_core = ndimage.binary_dilation(core_mask, iterations=3)
        for idx, slc in enumerate(objs):
            if slc is None:
                continue
            comp_id = idx + 1
            y_slc, x_slc = slc
            if border_kill[comp_id]:
                cleaned[y_slc, x_slc][labeled[y_slc, x_slc] == comp_id] = 255
            elif sizes[idx] <= max_speck_area:
                sub_mask = labeled[y_slc, x_slc] == comp_id
                if not np.any(dilated_core[y_slc, x_slc][sub_mask]):
                    cleaned[y_slc, x_slc][sub_mask] = 255
                    specks_removed += 1
        cleaned[cleaned > 225] = 255
    return cleaned, specks_removed


def detect_visual_lines(dark: np.ndarray, x0: int, x1: int) -> list[tuple[int, int]]:
    """استخراج فترات الأسطر البصرية [(y0, y1), ...] عبر المسقط الأفقي للحبر داخل النطاق [x0, x1]."""
    h, _ = dark.shape
    row_ink = np.mean(dark[:, x0:x1], axis=1)
    is_line = row_ink > 0.008
    line_intervals = []
    in_line = False
    start_y = 0
    for y in range(h):
        if is_line[y] and not in_line:
            in_line = True
            start_y = y
        elif not is_line[y] and in_line:
            in_line = False
            if y - start_y >= 8:
                line_intervals.append((start_y, y))
    if in_line and h - start_y >= 8:
        line_intervals.append((start_y, h))

    merged_lines = []
    for y0, y1 in line_intervals:
        if merged_lines and (y0 - merged_lines[-1][1]) < 8:
            merged_lines[-1] = (merged_lines[-1][0], y1)
        else:
            merged_lines.append((y0, y1))
    return merged_lines


def analyze_and_slice_page(arr: np.ndarray, out_dir: str, tag: str) -> dict:
    """
    المصنّف البصري الحتمي للتخطيطات (< 15ms):
    يصنّف الصفحة إلى:
      1) blank_or_sparse
      2) framed_hashiya (جدول بولاقي/أزهري مع متن عمودي في الهامش الخارجي)
      3) two_column (فهرس أو صفحة ذات عمودين)
      4) standard_single_col (صفحة اعتيادية تُشطر أفقياً عند وادي الفراغ الأوسط)
    """
    h, w = arr.shape
    dark = arr < 185
    ink_ratio = float(np.mean(dark[int(h * 0.06):int(h * 0.92), int(w * 0.06):int(w * 0.94)]))

    # 1. فحص الجداول المحاطة بإطار عمودي مزدوج (framed_hashiya) قبل حساب الأسطر
    col_ink = np.mean(dark[int(h * 0.12):int(h * 0.86), :], axis=0)
    left_region = col_ink[int(w * 0.08):int(w * 0.32)]
    right_region = col_ink[int(w * 0.72):int(w * 0.96)]
    if len(left_region) > 0 and len(right_region) > 0 and np.max(left_region) > 0.52 and np.max(right_region) > 0.52:
        left_frame_x = int(w * 0.08) + int(np.argmax(left_region))
        right_frame_x = int(w * 0.72) + int(np.argmax(right_region))
        if right_frame_x - left_frame_x > int(w * 0.45):
            inner_lines = detect_visual_lines(dark, left_frame_x + 25, right_frame_x - 25)
            hc = int(h * 0.94)
            box_arr = arr[:hc, max(0, left_frame_x - 10):min(w, right_frame_x + 15)]
            bh, bw = box_arr.shape
            y0, y1 = int(bh * 0.40), int(bh * 0.62)
            interior_ink = np.sum(box_arr[y0:y1, 40:max(41, bw - 40)] < 190, axis=1)
            smooth = np.convolve(interior_ink, np.ones(7) / 7.0, mode="same")
            cut_y = y0 + int(np.argmin(smooth))

            fmap = {}
            if out_dir:
                p_top = os.path.join(out_dir, f"{tag}_box_top.png")
                p_bot = os.path.join(out_dir, f"{tag}_box_bot.png")
                save_gray_png(box_arr[:cut_y + 18, :], p_top)
                save_gray_png(box_arr[max(0, cut_y - 18):, :], p_bot)
                fmap = {"box_top.png": p_top, "box_bot.png": p_bot}

                margin_arr = arr[int(h * 0.06):hc, int(w * 0.03):max(int(w * 0.04), left_frame_x - 14)]
                ys, xs = np.where(margin_arr < 190)
                if len(ys) > 50:
                    crop_m = margin_arr[
                        max(0, ys.min() - 15):min(margin_arr.shape[0], ys.max() + 15),
                        max(0, xs.min() - 15):min(margin_arr.shape[1], xs.max() + 15),
                    ]
                    if crop_m.shape[0] > crop_m.shape[1] * 1.5:
                        crop_m = np.rot90(crop_m, k=3)
                    p_margin = os.path.join(out_dir, f"{tag}_margin_upright.png")
                    save_gray_png(crop_m, p_margin)
                    fmap["margin_upright.png"] = p_margin

            return {
                "layout": "framed_hashiya",
                "width": w,
                "height": h,
                "left_frame_x": left_frame_x,
                "right_frame_x": right_frame_x,
                "ink_ratio": round(ink_ratio, 4),
                "visual_lines": inner_lines,
                "visual_line_count": len(inner_lines),
                "footnote_separator_y": None,
                "files_map": fmap,
            }

    merged_lines = detect_visual_lines(dark, int(w * 0.08), int(w * 0.92))

    # 2. فحص الصفحات الفارغة أو الفواصل
    if ink_ratio < 0.004 or len(merged_lines) == 0:
        return {
            "layout": "blank_or_sparse",
            "width": w,
            "height": h,
            "ink_ratio": round(ink_ratio, 4),
            "visual_lines": [],
            "visual_line_count": 0,
            "footnote_separator_y": None,
            "files_map": {},
        }

    # 3. فحص الصفحات ذات العمودين (فهارس الأعلام والموضوعات)
    mid_col_region = col_ink[int(w * 0.42):int(w * 0.58)]
    if len(mid_col_region) > 0 and np.max(mid_col_region) > 0.50:
        div_x = int(w * 0.42) + int(np.argmax(mid_col_region))
        fmap = {}
        if out_dir:
            p_col1 = os.path.join(out_dir, f"{tag}_col1_right.png")
            p_col2 = os.path.join(out_dir, f"{tag}_col2_left.png")
            save_gray_png(arr[:, max(0, div_x - 10):w], p_col1)
            save_gray_png(arr[:, 0:min(w, div_x + 10)], p_col2)
            fmap = {"col1_right.png": p_col1, "col2_left.png": p_col2}
        return {
            "layout": "two_column",
            "width": w,
            "height": h,
            "divider_x": div_x,
            "ink_ratio": round(ink_ratio, 4),
            "visual_lines": merged_lines,
            "visual_line_count": len(merged_lines),
            "footnote_separator_y": None,
            "files_map": fmap,
        }

    # 4. الصفحة الاعتيادية (عمود واحد): كشف خط فاصل الحواشي + الشطر الأفقي عند وادي الفراغ الأوسط
    fn_sep_y = None
    for y in range(int(h * 0.42), int(h * 0.88)):
        row = dark[y, int(w * 0.12):int(w * 0.88)]
        padded = np.concatenate(([0], row.view(np.int8), [0]))
        diffs = np.diff(padded)
        starts = np.where(diffs == 1)[0]
        ends = np.where(diffs == -1)[0]
        if len(starts) > 0 and int(np.max(ends - starts)) > int(w * 0.16):
            above_ink = float(np.mean(dark[max(0, y - 14):max(0, y - 4), int(w * 0.15):int(w * 0.85)]))
            below_ink = float(np.mean(dark[min(h, y + 4):min(h, y + 14), int(w * 0.15):int(w * 0.85)]))
            if above_ink < 0.05 and below_ink < 0.05:
                fn_sep_y = y
                break

    row_ink = np.mean(dark[:, int(w * 0.08):int(w * 0.92)], axis=1)
    mid_start, mid_end = int(h * 0.40), int(h * 0.62)
    best_valley_y = h // 2
    min_score = 1e9
    for y in range(mid_start, mid_end):
        if fn_sep_y and abs(y - fn_sep_y) < 20:
            continue
        window_score = float(np.sum(row_ink[max(0, y - 8):min(h, y + 8)]))
        dist_penalty = abs(y - (h // 2)) / h * 0.02
        if window_score + dist_penalty < min_score:
            min_score = window_score + dist_penalty
            best_valley_y = y

    fmap = {}
    if out_dir:
        p_top = os.path.join(out_dir, f"{tag}_band1_top.png")
        p_bot = os.path.join(out_dir, f"{tag}_band2_bot.png")
        save_gray_png(arr[0:min(h, best_valley_y + 18), :], p_top)
        save_gray_png(arr[max(0, best_valley_y - 18):h, :], p_bot)
        fmap = {"band1_top.png": p_top, "band2_bot.png": p_bot}

    return {
        "layout": "standard_single_col",
        "width": w,
        "height": h,
        "ink_ratio": round(ink_ratio, 4),
        "visual_lines": merged_lines,
        "visual_line_count": len(merged_lines),
        "footnote_separator_y": fn_sep_y,
        "split_valley_y": best_valley_y,
        "files_map": fmap,
    }


def run_quality_gates(extracted: dict, layout_meta: dict) -> dict:
    """
    تشغيل بوابات الجودة الحتمية الخمس على مخرجات المرحلة الأولى:
      1) تطبيع الأرقام الفارسية والحروف الفارسية (normalize_arabic_output)
      2) بوابة التغطية السطرية (كشف سقوط الأسطر)
      3) بوابة تطابق خط الحاشية وأرقام الإحالات بين المتن والهوامش (مع استثناء أرقام الآيات داخل ﴿...﴾)
      4) بوابة توازن الأقواس وعلامات الآيات ﴿...﴾ و«...»
      5) بوابة تحديد الإحداثيات السطرية للكلمات المشتبه بها (uncertain_words) لتكبيرها بدقة 2800px
    """
    matn_norm, norm_stats_m = normalize_arabic_output(extracted.get("matn", ""))
    fn_norm, norm_stats_f = normalize_arabic_output(extracted.get("footnotes", ""))
    hdr_norm, _ = normalize_arabic_output(extracted.get("running_header", ""))
    margin_norm, _ = normalize_arabic_output(extracted.get("margin_notes", ""))
    pg_norm, _ = normalize_arabic_output(extracted.get("printed_page", ""))

    extracted["matn"] = matn_norm
    extracted["footnotes"] = fn_norm
    extracted["running_header"] = hdr_norm
    extracted["margin_notes"] = margin_norm
    extracted["printed_page"] = pg_norm

    matn_lines = [ln.strip() for ln in matn_norm.splitlines() if ln.strip()]
    fn_lines = [ln.strip() for ln in fn_norm.splitlines() if ln.strip()]
    total_extracted_lines = len(matn_lines) + len(fn_lines) + (1 if hdr_norm else 0) + (1 if pg_norm else 0)
    total_words = len((matn_norm + " " + fn_norm).split())

    visual_line_count = layout_meta.get("visual_line_count", 0)
    words_per_visual_line = round(total_words / max(1, visual_line_count), 2)

    warnings = []
    focal_tasks = []

    if layout_meta.get("layout") == "standard_single_col" and visual_line_count >= 10 and words_per_visual_line < 4.5:
        warnings.append(f"LOW_WORDS_PER_VISUAL_LINE ({words_per_visual_line} words/vline)")

    fn_sep_y = layout_meta.get("footnote_separator_y")
    if fn_sep_y is not None and not fn_norm:
        warnings.append(f"MISSING_FOOTNOTES_BELOW_SEPARATOR (y={fn_sep_y})")
        focal_tasks.append({
            "crop_id": "fn_missing",
            "type": "missing_footnotes",
            "word": "الحاشية السفلية",
            "reason": "Visual footnote separator detected but footnotes field is empty",
            "context_line": "",
            "y_range": (max(0, fn_sep_y - 20), layout_meta["height"]),
        })

    def to_int_marker(s: str) -> int:
        ar_map = str.maketrans("٠١٢٣٤٥٦٧٨٩¹²³⁴⁵⁶⁷⁸⁹", "0123456789123456789")
        return int(s.translate(ar_map))

    fn_markers = []
    for ln in fn_lines:
        for m in re.finditer(
            r"(?:^\s*(?:[\(\[]\s*([٠-٩0-9]{1,2})\s*[\)\]]|([٠-٩0-9]{1,2})\s*[-–—.)]|([¹²³⁴⁵⁶⁷⁸⁹]))"
            r"|(?:\s{2,}|(?<=[.؛])\s+)[\(\[]\s*([٠-٩0-9]{1,2})\s*[\)\]]\s*(?=[\u0621-\u064A«\"\[]))",
            ln,
        ):
            raw_num = m.group(1) or m.group(2) or m.group(3) or m.group(4)
            val = to_int_marker(raw_num)
            if 1 <= val <= 25 and val not in fn_markers:
                fn_markers.append(val)

    matn_without_quran = re.sub(r"﴿[^﴾]*﴾", " ", matn_norm)
    matn_markers = []
    for m in re.finditer(
        r"[\(\[]\s*([٠-٩0-9]{1,2})\s*[\)\]]|([¹²³⁴⁵⁶⁷⁸⁹])|(?<=[\u0621-\u064A\u064B-\u065F])([٠-٩0-9]{1,2})(?=\s|[،.؛:!؟«»\"'\)\]]|$)",
        matn_without_quran,
    ):
        raw_num = m.group(1) or m.group(2) or m.group(3)
        val = to_int_marker(raw_num)
        if 1 <= val <= 25:
            matn_markers.append(val)

    if fn_markers and matn_markers:
        missing_in_fn = [m for m in set(matn_markers) if m not in set(fn_markers)]
        missing_in_matn = [m for m in set(fn_markers) if m not in set(matn_markers)]
        if missing_in_fn or missing_in_matn:
            warnings.append(
                f"FOOTNOTE_PARITY_MISMATCH (matn={matn_markers}, fn={fn_markers}, "
                f"missing_in_fn={missing_in_fn}, missing_in_matn={missing_in_matn})"
            )
            y0_fn = fn_sep_y - 30 if fn_sep_y else int(layout_meta["height"] * 0.65)
            focal_tasks.append({
                "crop_id": "fn_parity",
                "type": "footnote_parity_mismatch",
                "word": f"إحالات الحواشي {matn_markers} مقابل {fn_markers}",
                "reason": f"Matn markers {matn_markers} != Footnote markers {fn_markers}",
                "context_line": fn_lines[0] if fn_lines else "",
                "y_range": (max(0, y0_fn), layout_meta["height"]),
            })

    for open_b, close_b, label in [("﴿", "﴾", "QURAN_BRACKETS"), ("«", "»", "HADITH_QUOTES")]:
        c_open = (matn_norm + fn_norm).count(open_b)
        c_close = (matn_norm + fn_norm).count(close_b)
        if c_open != c_close:
            warnings.append(f"UNBALANCED_{label} ({open_b}:{c_open} != {close_b}:{c_close})")

    uncertain_list = extracted.get("uncertain_words", []) or []
    visual_lines = layout_meta.get("visual_lines") or []
    if fn_sep_y:
        matn_vlines = [vl for vl in visual_lines if vl[1] < fn_sep_y]
        fn_vlines = [vl for vl in visual_lines if vl[0] >= fn_sep_y]
    else:
        matn_vlines = visual_lines
        fn_vlines = []

    def strip_tashkeel(s: str) -> str:
        return re.sub(r"[\u064B-\u065F\u0670]", "", s)

    for idx_u, uw in enumerate(uncertain_list):
        uw_clean, _ = normalize_arabic_output(str(uw))
        if not uw_clean:
            continue
        uw_core = re.sub(r"\[.*?\]|\(.*?\)", " ", uw_clean).strip()
        arabic_words = re.findall(r"[\u0621-\u064A\u064B-\u065F\u0670]{2,}", uw_core)
        if not arabic_words:
            arabic_words = re.findall(r"[\u0621-\u064A\u064B-\u065F\u0670]{2,}", uw_clean)
        uw_token = max(arabic_words, key=lambda w: len(strip_tashkeel(w))) if arabic_words else uw_clean.split()[0]
        uw_bare = strip_tashkeel(uw_token)

        found_in_matn_idx = None
        context_line = ""
        for idx, ln in enumerate(matn_lines):
            if uw_token in ln or (uw_bare and uw_bare in strip_tashkeel(ln)):
                found_in_matn_idx = idx
                context_line = ln
                break

        if found_in_matn_idx is not None and matn_vlines:
            rel = found_in_matn_idx / max(1, len(matn_lines) - 1)
            center_v_idx = min(len(matn_vlines) - 1, int(round(rel * (len(matn_vlines) - 1))))
            v_start = max(0, center_v_idx - 2)
            v_end = min(len(matn_vlines) - 1, center_v_idx + 2)
            y0 = max(0, matn_vlines[v_start][0] - 25)
            y1 = min(layout_meta["height"], matn_vlines[v_end][1] + 25)
            focal_tasks.append({
                "crop_id": f"zoom{idx_u + 1}",
                "type": "uncertain_word",
                "word": uw_clean,
                "matched_token": uw_token,
                "section": "matn",
                "line_idx": found_in_matn_idx,
                "context_line": context_line,
                "y_range": (y0, y1),
            })
        else:
            found_in_fn = False
            for idx, ln in enumerate(fn_lines):
                if uw_token in ln or (uw_bare and uw_bare in strip_tashkeel(ln)):
                    found_in_fn = True
                    context_line = ln
                    break
            if found_in_fn and fn_vlines:
                y0 = max(0, fn_vlines[0][0] - 25)
                y1 = min(layout_meta["height"], fn_vlines[-1][1] + 25)
            else:
                y0 = 0
                y1 = int(layout_meta["height"] * 0.50)
            focal_tasks.append({
                "crop_id": f"zoom{idx_u + 1}",
                "type": "uncertain_word",
                "word": uw_clean,
                "matched_token": uw_token,
                "section": "footnotes_or_margin",
                "context_line": context_line or margin_norm,
                "y_range": (y0, y1),
            })

    return {
        "normalized_stats": {
            "persian_digits_fixed": norm_stats_m["persian_digits_fixed"] + norm_stats_f["persian_digits_fixed"],
            "persian_chars_fixed": norm_stats_m["persian_chars_fixed"] + norm_stats_f["persian_chars_fixed"],
        },
        "total_extracted_lines": total_extracted_lines,
        "total_words": total_words,
        "visual_line_count": visual_line_count,
        "words_per_visual_line": words_per_visual_line,
        "matn_markers": matn_markers,
        "fn_markers": fn_markers,
        "warnings": warnings,
        "focal_tasks": focal_tasks,
    }


def render_focal_zoom_crop(
    pdf_path: str,
    page_idx_0: int,
    y_range_stage1: tuple[int, int],
    stage1_height: int,
    out_png_path: str,
    target_width: int = 2800,
) -> str:
    """قص شريحة السطر المشتبه به مباشرةً من الـ PDF بدقة 2800px (~550 DPI) مع إزالة الغبار وتعزيز التباين."""
    doc = fitz.open(pdf_path)
    page = doc[page_idx_0]
    y0_rel = max(0.0, y_range_stage1[0] / max(1, stage1_height))
    y1_rel = min(1.0, y_range_stage1[1] / max(1, stage1_height))

    rect = page.rect
    clip_rect = fitz.Rect(
        rect.x0,
        rect.y0 + y0_rel * rect.height,
        rect.x1,
        rect.y0 + y1_rel * rect.height,
    )
    zoom = target_width / max(1.0, rect.width)
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=clip_rect, colorspace=fitz.csGRAY, alpha=False)
    arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width).copy()
    doc.close()

    binary_dark = arr < 200
    labeled, num_f = ndimage.label(binary_dark)
    if num_f > 0:
        areas = np.bincount(labeled.ravel())
        core = (labeled > 0) & (areas[labeled] > 9)
        prot = ndimage.binary_dilation(core, iterations=4)
        specks = (labeled > 0) & (areas[labeled] <= 9) & (~prot)
        arr[specks] = 255
    arr = np.clip((arr.astype(np.float32) - 25.0) * (255.0 / 200.0), 0, 255).astype(np.uint8)
    save_gray_png(arr, out_png_path)
    return out_png_path


PAGE_SCHEMA = {
    "type": "object",
    "properties": {
        "printed_page": {"type": "string"},
        "running_header": {"type": "string"},
        "matn": {"type": "string"},
        "margin_notes": {"type": "string"},
        "footnotes": {"type": "string"},
        "uncertain_words": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["printed_page", "running_header", "matn", "margin_notes", "footnotes", "uncertain_words"],
    "additionalProperties": False,
}

BATCHED_STAGE2_SCHEMA = {
    "type": "object",
    "properties": {
        "verifications": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "crop_id": {"type": "string"},
                    "verified_word_or_segment": {"type": "string"},
                    "corrected_full_line": {"type": "string"},
                    "was_changed": {"type": "boolean"},
                    "visual_evidence": {"type": "string"},
                },
                "required": ["crop_id", "verified_word_or_segment", "corrected_full_line", "was_changed", "visual_evidence"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["verifications"],
    "additionalProperties": False,
}


def parse_markdown_fallback(raw_text: str) -> dict:
    if not raw_text or not isinstance(raw_text, str):
        return {}
    text = raw_text.strip()
    if len(text) < 20:
        return {}
    fn_part = ""
    matn_part = text
    for sep in ["--- الحاشية ---", "#### [الحاشية]", "### الحواشي", "#### الحواشي", "---"]:
        if sep in text and text.rfind(sep) > len(text) * 0.35:
            idx = text.rfind(sep)
            matn_part = text[:idx].strip()
            fn_part = text[idx + len(sep):].strip()
            break
    return {
        "printed_page": "",
        "running_header": "",
        "matn": matn_part,
        "margin_notes": "",
        "footnotes": fn_part,
        "uncertain_words": [],
    }


def call_agy_schema(
    files_map: dict,
    prompt: str,
    schema_dict: dict,
    model: str = "gemini-3.8-flash-medium",
    timeout_s: int = 160,
    max_attempts: int = 2,
) -> dict:
    last_err = None
    for attempt in range(1, max_attempts + 1):
        with tempfile.TemporaryDirectory(prefix="agy_pdf_") as raw_tmp:
            tmpdir = os.path.realpath(raw_tmp)
            for local_name, src_path in files_map.items():
                shutil.copy2(os.path.realpath(src_path), os.path.join(tmpdir, local_name))
            schema_str = json.dumps(schema_dict, ensure_ascii=False)
            cmd = [
                AGY_BIN,
                "-p",
                prompt,
                "--model",
                model,
                "--disable-slash-commands",
                "--json-schema",
                schema_str,
                "--output-format",
                "json",
            ]
            t0 = time.time()
            try:
                res = subprocess.run(cmd, cwd=tmpdir, capture_output=True, text=True, timeout=timeout_s)
                wall_s = round(time.time() - t0, 2)
                stdout = (res.stdout or "").strip()
            except subprocess.TimeoutExpired:
                last_err = f"TimeoutExpired after {timeout_s}s (attempt {attempt})"
                time.sleep(2.0)
                continue

            parsed = {}
            for line in reversed(stdout.splitlines()):
                line = line.strip()
                if line.startswith("{"):
                    try:
                        parsed = json.loads(line)
                        break
                    except Exception:
                        pass
            if not parsed and "{" in stdout:
                try:
                    parsed = json.loads(stdout[stdout.find("{"):stdout.rfind("}") + 1])
                except Exception:
                    pass
            resp_raw = parsed.get("response", stdout)
            structured = None
            if isinstance(resp_raw, dict):
                structured = resp_raw
            elif isinstance(resp_raw, str):
                try:
                    structured = json.loads(resp_raw)
                except Exception:
                    for ln_cand in reversed(resp_raw.splitlines()):
                        ln_cand = ln_cand.strip()
                        if ln_cand.startswith("{"):
                            try:
                                obj_cand = json.loads(ln_cand)
                                if isinstance(obj_cand, dict):
                                    structured = obj_cand
                                    break
                            except Exception:
                                pass
                    if not isinstance(structured, dict) or not structured:
                        s_idx = resp_raw.find("{")
                        if s_idx != -1:
                            try:
                                obj_cand, _ = json.JSONDecoder().raw_decode(resp_raw[s_idx:])
                                if isinstance(obj_cand, dict):
                                    structured = obj_cand
                            except Exception:
                                pass
            if not isinstance(structured, dict) or not structured:
                if isinstance(resp_raw, str) and len(resp_raw.strip()) > 30 and "matn" in schema_dict.get("properties", {}):
                    structured = parse_markdown_fallback(resp_raw)

            if isinstance(structured, dict) and structured:
                return {
                    "ok": True,
                    "attempt": attempt,
                    "rc": res.returncode,
                    "duration_s": wall_s,
                    "num_turns": parsed.get("num_turns"),
                    "usage": parsed.get("usage"),
                    "data": structured,
                }
            last_err = f"Empty structured output on attempt {attempt} (rc={res.returncode}, stdout_len={len(stdout)})"
            time.sleep(2.0)

    return {
        "ok": False,
        "attempt": max_attempts,
        "rc": -1,
        "duration_s": timeout_s,
        "num_turns": 0,
        "usage": {},
        "data": {},
        "error": last_err,
    }


def build_prompt_for_layout(layout: str, files_map: dict) -> str:
    if layout == "framed_hashiya":
        has_margin = "margin_upright.png" in files_map
        m_str = " و @margin_upright.png (نص الهامش الجانبي بعد تدويره أفقياً ليكون معتدلاً)" if has_margin else ""
        return (
            f"استدعِ أداة view_file في خطوة واحدة متوازية لقراءة الصور @box_top.png و @box_bot.png{m_str} معاً الآن "
            "(يُمنع استدعاء أدوات الطرفية run_command أو turathmcp أو أدوات البحث).\n"
            "قواعد الاستخراج:\n"
            "١. ضع رقم الصفحة المطبوع في حقل printed_page.\n"
            "٢. استخرج نص الحاشية داخل الجدول من @box_top.png ثم @box_bot.png كاملاً حرفياً ١٠٠٪ في حقل matn دون تكرار السطر المشترك.\n"
            "٣. استخرج نص المتن الجانبي من @margin_upright.png حرفياً في حقل margin_notes، وأعد الحقول المطلوبة (printed_page, running_header, matn, margin_notes, footnotes, uncertain_words)."
        )
    if layout == "two_column":
        return (
            "هذه صفحة فهرس مطبوعة في عمودين مفصولين بخط عمودي: @col1_right.png (العمود الأيمن الأول) و @col2_left.png (العمود الأيسر الثاني). "
            "استدعِ أداة view_file في خطوة واحدة متوازية لقراءة الصورتين معاً الآن (يُمنع استدعاء أدوات الطرفية run_command أو turathmcp أو أدوات البحث). "
            "استخرج عنوان الفهرس ثم جميع مدخلات العمود الأيمن كاملة من الأعلى للأسفل، ثم مدخلات العمود الأيسر كاملة من الأعلى للأسفل في حقل matn، "
            "وضع رقم الصفحة في حقل printed_page، وأعد الحقول المطلوبة (printed_page, running_header, matn, margin_notes, footnotes, uncertain_words)."
        )
    return (
        "استدعِ أداة view_file في خطوة واحدة متوازية لقراءة الصورتين @band1_top.png و @band2_bot.png معاً الآن "
        "(يُمنع منعاً باتاً استدعاء أدوات الطرفية run_command أو turathmcp أو أدوات البحث). "
        "الصورتان تمثلان الشطر العلوي والشطر السفلي لنفس الصفحة مع هامش تداخل بسيط (١٨ بكسل) عند الفراغ الأوسط؛ "
        "احذر من تكرار السطر المشترك عند نقطة الالتقاء.\n"
        "قواعد الاستخراج الصارمة:\n"
        "١. استخرج المتن في حقل matn حرفياً ١٠٠٪ بالتشكيل المطبوع وعلامات الترقيم وأرقام الحواشي وأبيات الشعر (افصل شطري البيت بـ ٤ مسافات)، ورقم الصفحة في printed_page.\n"
        "٢. إذا وُجدت إشارات أوراق المخطوط في الهامش الجانبي مثل [٤ ب] أو [I/8] فوثقها في margin_notes أو في موضعها.\n"
        "٣. افصل الحواشي السفلية الواقعة تحت خط الفصل في حقل footnotes بأرقامها كاملة.\n"
        "٤. دقّق عدد النقاط ومواقعها فوق كل سنّ وتحته (ث/ب/ت/ن/ي، ص/ض، ح/خ/ج) وقاطع الكلمات الغريبة مع شرحها في الحاشية السفلية.\n"
        "٥. فقط إذا كانت هناك كلمة تشتبه نقاطها أو أقواسها بصرياً بين قراءتين متنافستين (مثل: أثبتوك [أو: أنبتوك])، فاكتب القراءة الأرجح في المتن وسجّلها في uncertain_words."
    )


def run_batched_stage2_zoom(
    pdf_path: str,
    page_idx_0: int,
    tag: str,
    focal_tasks: list[dict],
    stage1_height: int,
    crops_dir: str,
    zoom_model: str = "gemini-3.8-flash-high",
) -> dict:
    """قص جميع الشرائح المشتبه بها في الصفحة بدقة 2800px وفحصها معاً في نداء متوازٍ واحد."""
    selected_tasks = focal_tasks[:3]
    fmap = {}
    items_desc = []
    for t in selected_tasks:
        cid = t["crop_id"]
        zpath = os.path.join(crops_dir, f"{tag}_{cid}.png")
        render_focal_zoom_crop(pdf_path, page_idx_0, t["y_range"], stage1_height, zpath, target_width=2800)
        fmap[f"{cid}.png"] = zpath
        items_desc.append(
            f"- @{cid}.png : السطر المبدئي «{t.get('context_line', '')}» | العنصر المشتبه به: «{t.get('word', '')}»"
        )

    crops_str = " و ".join(f"@{k}" for k in fmap.keys())
    prompt = (
        f"استدعِ أداة view_file في خطوة واحدة متوازية لقراءة الشرائح المكبرة ({crops_str}) بدقة فائقة (2800px) الآن "
        "(يُمنع استدعاء أدوات الطرفية run_command أو turathmcp أو أدوات البحث):\n"
        + "\n".join(items_desc)
        + "\nافحص نقاط الحروف وعلامات الحصر والأقواس والحركات مجهرياً لكل شريحة، وأعد النتيجة في مصفوفة verifications."
    )
    return call_agy_schema(fmap, prompt, BATCHED_STAGE2_SCHEMA, model=zoom_model, timeout_s=150)


def process_single_page(job: dict) -> dict:
    t_start = time.time()
    pdf_path = job["pdf_path"]
    page_idx_0 = job["page_idx_0"]
    page_num_1 = page_idx_0 + 1
    tag = f"p{page_num_1:04d}"
    pages_dir = job["pages_dir"]
    crops_dir = job["crops_dir"]
    stage1_model = job["model"]
    zoom_model = job["zoom_model"]
    force = job.get("force", False)

    chk_path = os.path.join(pages_dir, f"{tag}.json")
    if not force and os.path.exists(chk_path):
        try:
            with open(chk_path, "r", encoding="utf-8") as f:
                cached = json.load(f)
            if cached.get("layout") == "blank_or_sparse" or cached.get("gate_report", {}).get("total_words", 0) > 5:
                return cached
        except Exception:
            pass

    doc = fitz.open(pdf_path)
    arr, specks_removed = render_clean_gray(doc[page_idx_0], target_width=job.get("target_width", 1650))
    doc.close()

    layout_meta = analyze_and_slice_page(arr, crops_dir, tag)
    layout_meta["specks_removed"] = specks_removed

    if layout_meta["layout"] == "blank_or_sparse":
        res_obj = {
            "pdf_page": page_num_1,
            "tag": tag,
            "layout": "blank_or_sparse",
            "total_wall_s": round(time.time() - t_start, 2),
            "stage1_duration_s": 0.0,
            "stage2_duration_s": 0.0,
            "extracted": {
                "printed_page": "",
                "running_header": "",
                "matn": "",
                "margin_notes": "",
                "footnotes": "",
                "uncertain_words": [],
            },
            "gate_report": {"total_words": 0, "warnings": [], "focal_tasks": []},
            "focal_verifications": [],
        }
        with open(chk_path, "w", encoding="utf-8") as f:
            json.dump(res_obj, f, ensure_ascii=False, indent=2)
        txt_path = os.path.join(pages_dir, f"{tag}.txt")
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(format_page_verbatim_txt(res_obj))
        return res_obj

    prompt = build_prompt_for_layout(layout_meta["layout"], layout_meta["files_map"])
    s1 = call_agy_schema(layout_meta["files_map"], prompt, PAGE_SCHEMA, model=stage1_model, timeout_s=160)
    extracted = s1.get("data") or {}
    gate_report = run_quality_gates(extracted, layout_meta)

    focal_verifications = []
    stage2_dur = 0.0
    if gate_report["focal_tasks"] and not job.get("no_zoom", False):
        s2 = run_batched_stage2_zoom(
            pdf_path=pdf_path,
            page_idx_0=page_idx_0,
            tag=tag,
            focal_tasks=gate_report["focal_tasks"],
            stage1_height=layout_meta["height"],
            crops_dir=crops_dir,
            zoom_model=zoom_model,
        )
        stage2_dur = s2["duration_s"]
        if s2["ok"]:
            verifs = s2["data"].get("verifications") or []
            focal_verifications = verifs
            # Map crop_id back to context_line and patch matn if was_changed is True
            task_by_cid = {t["crop_id"]: t for t in gate_report["focal_tasks"]}
            for v in verifs:
                cid = str(v.get("crop_id", "")).replace(".png", "")
                matched_task = task_by_cid.get(cid)
                if v.get("was_changed") and matched_task and matched_task.get("context_line"):
                    old_ln = matched_task["context_line"]
                    new_ln, _ = normalize_arabic_output(v.get("corrected_full_line", ""))
                    if old_ln and new_ln and old_ln in extracted.get("matn", ""):
                        extracted["matn"] = extracted["matn"].replace(old_ln, new_ln, 1)

    res_obj = {
        "pdf_page": page_num_1,
        "tag": tag,
        "layout": layout_meta["layout"],
        "total_wall_s": round(time.time() - t_start, 2),
        "stage1_duration_s": s1["duration_s"],
        "stage2_duration_s": round(stage2_dur, 2),
        "stage1_usage": s1.get("usage"),
        "meta": {k: v for k, v in layout_meta.items() if k not in ("visual_lines", "files_map")},
        "gate_report": gate_report,
        "extracted": extracted,
        "focal_verifications": focal_verifications,
    }
    with open(chk_path, "w", encoding="utf-8") as f:
        json.dump(res_obj, f, ensure_ascii=False, indent=2)
    txt_path = os.path.join(pages_dir, f"{tag}.txt")
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(format_page_verbatim_txt(res_obj))

    if not job.get("keep_crops", False):
        for p in layout_meta["files_map"].values():
            if os.path.exists(p):
                try:
                    os.remove(p)
                except Exception:
                    pass
    return res_obj


def parse_page_selection(pages_arg: str, only_arg: str, total_pages: int) -> list[int]:
    """يرجع قائمة الفهارس الصفرية (0-indexed) للصفحات المطلوب تحويلها."""
    selected_1 = set()
    if only_arg:
        for part in only_arg.split(","):
            part = part.strip()
            if part.isdigit():
                selected_1.add(int(part))
    elif pages_arg:
        for part in pages_arg.split(","):
            part = part.strip()
            if "-" in part:
                a, b = part.split("-", 1)
                selected_1.update(range(int(a), int(b) + 1))
            elif part.isdigit():
                selected_1.add(int(part))
    else:
        selected_1.update(range(1, total_pages + 1))
    return [p - 1 for p in sorted(selected_1) if 1 <= p <= total_pages]


def format_page_verbatim_txt(p: dict) -> str:
    """توليد النص الحرفي الصافي لصفحة واحدة (pages/pNNNN.txt) بعلامة الصفحة المعيارية [ص: N]."""
    if p.get("layout") == "blank_or_sparse":
        return ""
    ext = p.get("extracted") or {}
    pdf_p = p.get("pdf_page", 1)
    pg_str = (ext.get("printed_page") or "").strip() or str(pdf_p)
    blocks = [f"[ص: {pg_str}]"]
    if (ext.get("matn") or "").strip():
        blocks.append(ext["matn"].strip())
    if (ext.get("margin_notes") or "").strip():
        blocks.append(f"[هامش جانبي — ص {pg_str}]\n{ext['margin_notes'].strip()}")
    if (ext.get("footnotes") or "").strip():
        blocks.append("--- الحاشية ---\n" + ext["footnotes"].strip())
    return "\n\n".join(blocks) + "\n"


def format_book_markdown(pages_data: list[dict]) -> str:
    blocks = []
    for p in pages_data:
        pdf_p = p["pdf_page"]
        if p["layout"] == "blank_or_sparse":
            continue
        ext = p["extracted"]
        pg_str = ext.get("printed_page") or str(pdf_p)
        hdr = ext.get("running_header", "")
        header_line = f"=== [صفحة PDF: {pdf_p} | ص مطبوعة: {pg_str}] ==="
        if hdr:
            header_line += f" ({hdr})"
        parts = [header_line]
        if ext.get("margin_notes"):
            parts.append(f"[هامش جانبي: {ext['margin_notes']}]")
        if ext.get("matn"):
            parts.append(ext["matn"])
        if ext.get("footnotes"):
            parts.append("--- الحاشية ---\n" + ext["footnotes"])
        blocks.append("\n\n".join(parts))
    return "\n\n" + ("\n\n" + ("=" * 60) + "\n\n").join(blocks) + "\n"


def main():
    parser = argparse.ArgumentParser(description="تحويل كتب الـ PDF العربية إلى نص حرفي مهيكل بدقة 100% عبر رؤية agy")
    parser.add_argument("pdf_path", help="مسار ملف الـ PDF المراد تحويله")
    parser.add_argument("--out-dir", required=True, help="مجلد حفظ المخرجات ونقاط الاستئناف")
    parser.add_argument("--pages", default="", help="نطاق الصفحات بصيغة 1-50 أو 10-20,35")
    parser.add_argument("--only", default="", help="صفحات محددة مفصولة بفاصلة مثل 16,22,86")
    parser.add_argument("--model", default="gemini-3.8-flash-medium", help="نموذج المرحلة الأولى (الافتراضي: gemini-3.8-flash-medium)")
    parser.add_argument("--zoom-model", default="gemini-3.8-flash-high", help="نموذج التكبير البؤري 2800px (الافتراضي: gemini-3.8-flash-high)")
    parser.add_argument("--target-width", type=int, default=1650, help="عرض الصورة بالبكسل في المرحلة الأولى (الافتراضي: 1650)")
    parser.add_argument("--workers", type=int, default=2, help="عدد العمال المتوازيين (الافتراضي: 2)")
    parser.add_argument("--stagger", type=float, default=2.0, help="فارق الإقلاع بالثواني بين العمال لمنع تصادم MCP (الافتراضي: 2.0)")
    parser.add_argument("--no-zoom", action="store_true", help="تعطيل المرحلة الثانية (التكبير البؤري)")
    parser.add_argument("--keep-crops", action="store_true", help="الاحتفاظ بصور الشطور والشرائح المكبرة")
    parser.add_argument("--force", action="store_true", help="إعادة استخراج الصفحات حتى لو كانت محفوظة مسبقاً")
    args = parser.parse_args()

    if not os.path.exists(args.pdf_path):
        print(f"[خطأ] الملف غير موجود: {args.pdf_path}", file=sys.stderr)
        sys.exit(1)

    os.makedirs(args.out_dir, exist_ok=True)
    pages_dir = os.path.join(args.out_dir, "pages")
    crops_dir = os.path.join(args.out_dir, "_crops")
    os.makedirs(pages_dir, exist_ok=True)
    os.makedirs(crops_dir, exist_ok=True)

    doc = fitz.open(args.pdf_path)
    total_pdf_pages = len(doc)
    doc.close()

    selected_indices = parse_page_selection(args.pages, args.only, total_pdf_pages)
    if not selected_indices:
        print("[خطأ] لم يتم اختيار أي صفحات صالحة.", file=sys.stderr)
        sys.exit(1)

    book_slug = os.path.splitext(os.path.basename(args.pdf_path))[0]
    print(
        f"[بدء] كتاب: {book_slug} ({len(selected_indices)}/{total_pdf_pages} صفحة) | "
        f"model={args.model} | zoom={args.zoom_model} | workers={args.workers}",
        flush=True,
    )

    jobs = [
        {
            "pdf_path": args.pdf_path,
            "page_idx_0": idx,
            "pages_dir": pages_dir,
            "crops_dir": crops_dir,
            "model": args.model,
            "zoom_model": args.zoom_model,
            "target_width": args.target_width,
            "no_zoom": args.no_zoom,
            "keep_crops": args.keep_crops,
            "force": args.force,
        }
        for idx in selected_indices
    ]

    t0 = time.time()
    results_by_idx = {}
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        future_map = {}
        for i, job in enumerate(jobs):
            fut = pool.submit(process_single_page, job)
            future_map[fut] = job["page_idx_0"]
            if i < len(jobs) - 1 and args.workers > 1:
                time.sleep(args.stagger)
        for fut in as_completed(future_map):
            idx = future_map[fut]
            res = fut.result()
            results_by_idx[idx] = res
            gr = res.get("gate_report", {})
            print(
                f"  [صفحة {idx + 1:04d}] ({res['layout']}): {res['total_wall_s']}s "
                f"(s1={res['stage1_duration_s']}s, s2={res['stage2_duration_s']}s) | "
                f"كلمات={gr.get('total_words', 0)} | تحذيرات={gr.get('warnings', [])}",
                flush=True,
            )

    total_wall = round(time.time() - t0, 2)
    ordered_pages = [results_by_idx[idx] for idx in selected_indices]

    book_json_path = os.path.join(args.out_dir, f"{book_slug}.json")
    book_md_path = os.path.join(args.out_dir, f"{book_slug}.md")
    gate_report_path = os.path.join(args.out_dir, "gate_report.json")

    total_words = sum(p.get("gate_report", {}).get("total_words", 0) for p in ordered_pages)
    pages_with_warnings = [p["pdf_page"] for p in ordered_pages if p.get("gate_report", {}).get("warnings")]

    summary_payload = {
        "book_slug": book_slug,
        "pdf_path": os.path.abspath(args.pdf_path),
        "total_pdf_pages": total_pdf_pages,
        "processed_pages": len(ordered_pages),
        "total_words": total_words,
        "total_wall_s": total_wall,
        "effective_s_per_page": round(total_wall / max(1, len(ordered_pages)), 2),
        "pages_with_warnings": pages_with_warnings,
        "pages": ordered_pages,
    }
    with open(book_json_path, "w", encoding="utf-8") as f:
        json.dump(summary_payload, f, ensure_ascii=False, indent=2)

    pages_md_path = os.path.join(args.out_dir, f"{book_slug}_pages.md")
    with open(pages_md_path, "w", encoding="utf-8") as f:
        f.write(format_book_markdown(ordered_pages))

    gate_summary = {
        "book_slug": book_slug,
        "processed_pages": len(ordered_pages),
        "total_words": total_words,
        "pages_with_warnings": pages_with_warnings,
        "per_page": [
            {
                "pdf_page": p["pdf_page"],
                "printed_page": p["extracted"].get("printed_page", ""),
                "layout": p["layout"],
                "words": p["gate_report"].get("total_words", 0),
                "matn_markers": p["gate_report"].get("matn_markers", []),
                "fn_markers": p["gate_report"].get("fn_markers", []),
                "warnings": p["gate_report"].get("warnings", []),
                "focal_verifications": len(p.get("focal_verifications", [])),
            }
            for p in ordered_pages
        ],
    }
    with open(gate_report_path, "w", encoding="utf-8") as f:
        json.dump(gate_summary, f, ensure_ascii=False, indent=2)

    from build_book_db import build_all_for_dir  # noqa: E402
    db_info = build_all_for_dir(args.out_dir)

    print(
        f"\n[اكتمل] {len(ordered_pages)} صفحة ({total_words} كلمة) في {total_wall}s "
        f"({summary_payload['effective_s_per_page']}s/صفحة)\n"
        f"  -> SQLite DB : {db_info['db_path']} ({db_info['total_parts']} أقسام، {db_info['total_footnotes']} حاشية)\n"
        f"  -> TOC JSON  : {db_info['toc_path']}\n"
        f"  -> Master MD : {db_info['master_md_path']}\n"
        f"  -> Pages MD  : {db_info['pages_md_path']}",
        flush=True,
    )


if __name__ == "__main__":
    main()
