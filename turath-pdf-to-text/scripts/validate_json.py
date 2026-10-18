#!/usr/bin/env python3
"""
Unified JSON Schema & Quality Contract Validator for `turath-pdf-to-text` (v2.2)
================================================================================
Shares the exact data contract with `pdf_to_preflight_adapter.py` so that:
1. Multi-Zone Layouts (`matn_top`, `sharh_body`, `text`, `matn`, `margin_notes`, `footnotes`)
   are natively validated in both nested (`{"extracted": {...}}`) and flat page dicts,
   as well as implicit `--- الشرح ---` or top `﴿...﴾`/`(...)` Matn blocks.
2. Footnotes of ANY representation (`str`, `list[str]`, `list[dict]` like
   `[{"id": "1", "text": "..."}]`, `dict` like `{"1": "..."}`, and cross-page
   continuations `= ...`, `(=) ...`, `{"id": "=", "text": "..."}`) are accepted
   and coerced cleanly into the canonical footnote string format.
3. Hyphen/Kashida line-break word splits (`المسـ\\nـألة` -> `المسألة`) and mixed
   Arabic/Hindi/ASCII digits (`"١5"` -> `"١٥"`, `١25` -> `١٢٥`) are repaired and
   verified.
4. `matn_top` start/end delimiters (`﴿...﴾`, `(...)`) are verified for 100% Zero-Loss
   preservation and balance, while distinguishing commented-upon Matn `﴿...﴾`
   (which may contain footnote markers `(١)`) from true Quranic verses `﴿...﴾`.
"""

import argparse
import copy
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from pdf_to_preflight_adapter import (
    FN_LINE_HEAD_RE,
    check_delimiters_balanced_and_preserved,
    coerce_footnotes_to_raw_str,
    extract_and_normalize_page_zones,
    find_true_quran_spans,
    parse_marker_val,
    repair_line_breaks_and_mixed_digits,
    to_ar_digits,
)

# Forbidden LLM chatter / meta-phrases in Arabic extraction output
FORBIDDEN_LLM_PATTERNS = [
    re.compile(r"(?:إليك|هذا هو|فيما يلي)\s+(?:النص|الاستخراج|تفريغ)", re.UNICODE),
    re.compile(r"```(?:json|text|markdown)?", re.IGNORECASE),
    re.compile(r"(?:Here is the extracted|I have transcribed)", re.IGNORECASE),
]


def _strip_all_whitespace(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


def extract_footnote_def_numbers_and_continuations(
    fn_str: str,
) -> Tuple[List[int | str], List[Tuple[int | str, str]], int]:
    """
    Extract footnote definition numbers/markers at line starts in normalized
    `footnotes_raw` string, plus `(val, body)` metadata and count of cross-page
    continuation lines starting with `=`.
    """
    if not fn_str or not fn_str.strip():
        return [], [], 0
    nums: List[int | str] = []
    meta: List[Tuple[int | str, str]] = []
    cont_count = 0
    for line in fn_str.split("\n"):
        s = line.strip()
        if not s:
            continue
        if s.startswith("=") or re.match(r"^(?:[\(\[]\s*=\s*[\)\]])", s):
            cont_count += 1
            continue
        m_head = FN_LINE_HEAD_RE.match(s)
        if m_head:
            raw_marker = next((g for g in m_head.groups()[:7] if g is not None), "")
            body = (m_head.group(8) or "").strip()
            val = parse_marker_val(raw_marker)
            if val is not None:
                nums.append(val)
                meta.append((val, body))
    return nums, meta, cont_count


def extract_matn_fn_numbers(
    matn: str,
    fn_entries_meta: List[Tuple[int | str, str]],
    fn_vals_set: set,
) -> List[int | str]:
    """
    Extract footnote marker values `(N)` or `(*)` from normalized Matn (excluding
    true Quranic `﴿...﴾` spans and spaced non-footnote parens `( ٤٣ )`, while keeping
    commented-upon Matn `﴿...﴾` spans).
    """
    if not matn:
        return []
    q_spans = find_true_quran_spans(matn, fn_entries_meta, fn_vals_set)

    def in_true_quran(pos: int) -> bool:
        return any(qs <= pos < qe for qs, qe in q_spans)

    nums: List[int | str] = []
    for m in re.finditer(r"(?<!\()\(([٠-٩0-9]{1,3}|\*+)\)(?!\))", matn):
        if not in_true_quran(m.start()):
            val = parse_marker_val(m.group(1))
            if val is not None:
                nums.append(val)
    return nums


def validate_page_dict(
    page: Dict[str, Any],
    normalize_in_place: bool = True,
    strict_footnote_alignment: bool = True,
) -> Dict[str, Any]:
    """
    Validate (and optionally normalize in place) a single page dictionary.
    Supports both nested `{"page_num": ..., "extracted": {...}}` and flat page dicts,
    multi-zone layouts (`matn_top`, `sharh_body`, `text`, `matn`, `footnotes`),
    and all footnote types (`str`, `list[str]`, `list[dict]`, `dict`).
    """
    errors: List[str] = []
    warnings: List[str] = []

    if not isinstance(page, dict):
        return {
            "valid": False,
            "page_num": -1,
            "printed_page": None,
            "errors": ["page_entry_not_a_dict"],
            "warnings": [],
            "zones": {},
        }

    p_num = page.get("page_num", page.get("pdf_page", page.get("page", 0)))
    try:
        p_num_int = int(p_num)
    except (ValueError, TypeError):
        p_num_int = 0
        errors.append(f"invalid_page_num:{p_num!r}")

    target_page = page if normalize_in_place else copy.deepcopy(page)
    ext = target_page.get("extracted") if isinstance(target_page.get("extracted"), dict) else target_page
    raw_fn_val = ext.get("footnotes", target_page.get("footnotes", ""))
    if raw_fn_val is not None and not isinstance(raw_fn_val, (str, list, dict)):
        errors.append(f"unsupported_footnotes_type:{type(raw_fn_val).__name__}")

    # Run unified multi-zone extraction & normalization
    zones = extract_and_normalize_page_zones(target_page, update_in_place=True)

    # 1. Check for forbidden LLM chatter in any zone
    for zone_name in ("matn_top", "sharh_body", "matn", "footnotes_raw"):
        z_txt = zones.get(zone_name, "")
        for pat in FORBIDDEN_LLM_PATTERNS:
            if pat.search(z_txt):
                errors.append(f"llm_chatter_detected_in_{zone_name}:{pat.pattern}")

    # 2. Check delimiter balance & preservation in matn_top and sharh_body
    if not zones.get("matn_top_delimiters_preserved", True):
        errors.append("matn_top_delimiters_unbalanced_or_not_preserved")

    for zone_name in ("matn_top", "sharh_body", "matn"):
        z_txt = zones.get(zone_name, "")
        if z_txt:
            for op, cl in (("﴿", "﴾"), ("(", ")"), ("[", "]"), ("«", "»")):
                if z_txt.count(op) != z_txt.count(cl):
                    errors.append(f"unbalanced_delimiters_in_{zone_name}:{op}{cl}")

    # 3. Verify 100% Zero-Loss containment of matn_top and sharh_body inside combined matn
    matn_nospace = _strip_all_whitespace(zones.get("matn", ""))
    if zones.get("matn_top"):
        mt_nospace = _strip_all_whitespace(zones["matn_top"])
        if mt_nospace not in matn_nospace:
            errors.append("zero_loss_violation:matn_top_not_in_matn")
    if zones.get("sharh_body"):
        sb_nospace = _strip_all_whitespace(zones["sharh_body"])
        if sb_nospace not in matn_nospace:
            errors.append("zero_loss_violation:sharh_body_not_in_matn")

    # 4. Check Footnote Marker <-> Footnote Definition Alignment
    fn_def_nums, fn_meta, cont_count = extract_footnote_def_numbers_and_continuations(zones["footnotes_raw"])
    fn_vals_set = set(fn_def_nums)
    matn_fn_nums = extract_matn_fn_numbers(zones["matn"], fn_meta, fn_vals_set)

    if matn_fn_nums != fn_def_nums:
        if set(matn_fn_nums) != set(fn_def_nums):
            msg = f"footnote_count_or_id_mismatch:matn={matn_fn_nums}_vs_fn={fn_def_nums}"
            if strict_footnote_alignment:
                errors.append(msg)
            else:
                warnings.append(msg)
        else:
            warnings.append(f"footnote_order_or_duplicate_diff:matn={matn_fn_nums}_vs_fn={fn_def_nums}")

    # 5. Check that printed_page has no mixed Hindi/ASCII digits remaining
    printed_page = zones.get("printed_page", "")
    if printed_page:
        has_hindi = bool(re.search(r"[٠-٩]", printed_page))
        has_ascii = bool(re.search(r"[0-9]", printed_page))
        if has_hindi and has_ascii:
            errors.append(f"mixed_digits_in_printed_page:{printed_page}")

    return {
        "valid": len(errors) == 0,
        "page_num": p_num_int,
        "printed_page": printed_page,
        "errors": errors,
        "warnings": warnings,
        "zones": zones,
        "footnote_alignment": {
            "matn_markers": matn_fn_nums,
            "footnote_defs": fn_def_nums,
            "continuation_lines": cont_count,
        },
    }


def validate_pages_payload(
    payload: Any,
    normalize_in_place: bool = True,
    strict_footnote_alignment: bool = True,
) -> Dict[str, Any]:
    """
    Validate a full JSON payload (either `{"pages": [...]}` or `[...]`).
    """
    if isinstance(payload, dict) and "pages" in payload:
        pages = payload["pages"]
    elif isinstance(payload, list):
        pages = payload
    elif isinstance(payload, dict):
        pages = [payload]
    else:
        return {
            "valid": False,
            "total_pages": 0,
            "valid_pages": 0,
            "invalid_pages": 1,
            "errors": [{"page_num": -1, "errors": ["invalid_top_level_json_structure"]}],
            "page_reports": [],
        }

    page_reports: List[Dict[str, Any]] = []
    all_errors: List[Dict[str, Any]] = []

    for idx, p in enumerate(pages):
        rep = validate_page_dict(
            p,
            normalize_in_place=normalize_in_place,
            strict_footnote_alignment=strict_footnote_alignment,
        )
        if rep["page_num"] == 0:
            rep["page_num"] = idx + 1
        page_reports.append(rep)
        if not rep["valid"]:
            all_errors.append({"page_num": rep["page_num"], "errors": rep["errors"]})

    return {
        "valid": len(all_errors) == 0,
        "total_pages": len(page_reports),
        "valid_pages": sum(1 for r in page_reports if r["valid"]),
        "invalid_pages": len(all_errors),
        "errors": all_errors,
        "page_reports": page_reports,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate and normalize turath-pdf-to-text extracted JSON against the unified contract."
    )
    parser.add_argument("input_json", help="Path to extracted JSON file")
    parser.add_argument(
        "-o",
        "--output",
        help="Optional path to write normalized JSON file (or --in-place to update input_json)",
    )
    parser.add_argument(
        "--in-place",
        action="store_true",
        help="Normalize and write back to input_json in-place",
    )
    parser.add_argument(
        "--non-strict-fn",
        action="store_true",
        help="Treat footnote marker/body count mismatches as warnings instead of errors",
    )
    args = parser.parse_args()

    in_path = Path(args.input_json)
    if not in_path.exists():
        print(f"ERROR: File not found: {in_path}", file=sys.stderr)
        return 1

    with open(in_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    report = validate_pages_payload(
        data,
        normalize_in_place=True,
        strict_footnote_alignment=not args.non_strict_fn,
    )

    out_path = in_path if args.in_place else (Path(args.output) if args.output else None)
    if out_path:
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    summary = {
        "valid": report["valid"],
        "total_pages": report["total_pages"],
        "valid_pages": report["valid_pages"],
        "invalid_pages": report["invalid_pages"],
        "errors": report["errors"],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
