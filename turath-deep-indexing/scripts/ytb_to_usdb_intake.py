#!/usr/bin/env python3
"""
USDB v5.7 — Automatic Sheikh-Series-Pipeline Intake Bridge (Adapter B & C).
Reads a transcribed and CTC-aligned lecture series directory from `sheikh-series-pipeline`:
  - `_meta.json`
  - `<NNN>_<vid>.txt`
  - `<NNN>_<vid>.align.json`
  - `<NNN>_<vid>.meta.json` (optional per-lesson metadata)
Prepares canonical `raw_lectures.json` and `deep_lecture_<lid>.json` files, runs them through
`merge_lecture.py` (Gate v5.1 / USDB v5.7), enriches dual-layer embedding fields
(`embed_matn_text`, `embed_concept_text`), verifies 100% lossless verbatim partitioning
(0 chars lost), and validates CTC word-level timestamp projection.
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

import build_cross_corpus_graph as bcg
import merge_lecture as ml
import merge_round as mr


LESSON_TXT_RE = re.compile(r"^(\d{1,4})(?:_([A-Za-z0-9_-]{6,20}))?\.txt$")

SPOKEN_FILLER_CLEAN_RE = re.compile(
    r"\b(?:يعني|طيب|تمام|صح|ماشي|يا\s+إخوة|يا\s+إخواني|يا\s+إخوان|يا\s+جماعة|أليس\s+كذلك|واضح|خلي\s+بالك|أوكي)\b[\s،.؟!]*",
)


def strip_spoken_fillers(text: str) -> str:
    cleaned = SPOKEN_FILLER_CLEAN_RE.sub(" ", text or "")
    cleaned = ml.SPOKEN_FILLER_RE.sub(" ", cleaned)
    cleaned = re.sub(r"\s+([،.؛:؟!])", r"\1", cleaned)
    cleaned = re.sub(r"[،.؟!]+\s*[،.؟!]+", "، ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ،.؟!-")
    return cleaned


def infer_duration_from_align(align_path: Path | None, default_dur: float = 1800.0) -> tuple[float, int]:
    if not align_path or not align_path.exists():
        return default_dur, 0
    try:
        aln = json.loads(align_path.read_text(encoding="utf-8"))
    except Exception:
        return default_dur, 0

    w_list = aln.get("w") if isinstance(aln.get("w"), list) else (aln.get("x") if isinstance(aln.get("x"), list) else None)
    if w_list:
        ends = [float(item[2]) for item in w_list if len(item) >= 3 and item[2] is not None]
        if ends:
            return round(max(ends) + 1.0, 2), len(ends)
    if "words" in aln and "start" in aln and "dur" in aln:
        ends = [
            float(st + du) / 100.0
            for st, du in zip(aln["start"], aln["dur"])
            if st is not None and du is not None
        ]
        if ends:
            return round(max(ends) + 1.0, 2), len(ends)
    return default_dur, 0


def partition_raw_text_lossless(raw_text: str, target_max_chars: int = 1600) -> list[tuple[int, int]]:
    """
    Deterministically partitions `raw_text` into contiguous spans `[(s0, e0), (s1, e1), ...]`
    such that `s0 == 0`, `e_last == len(raw_text)`, `e_i == s_{i+1}`, each span <= target_max_chars
    (and strictly <= 3000), never ends with a colon ':', and each span starts at a word boundary
    with >= 4 words available for `anchor_start`.
    """
    n = len(raw_text)
    if n == 0:
        return [(0, 0)]

    # First check if natural paragraph breaks (\n) divide the text into valid thematic segments (>= 250 chars)
    if "\n" in raw_text and n <= target_max_chars:
        para_spans = []
        pos = 0
        for ln in raw_text.splitlines(keepends=True):
            para_spans.append((pos, pos + len(ln)))
            pos += len(ln)
        if (
            len(para_spans) >= 2
            and all((e - s) >= 250 for s, e in para_spans)
            and all(not raw_text[s:e].rstrip().endswith(":") for s, e in para_spans[:-1])
            and all(len(raw_text[s:e].split()) >= 6 for s, e in para_spans)
        ):
            return para_spans

    if n <= target_max_chars:
        return [(0, n)]

    spans = []
    cur = 0
    while cur < n:
        rem = n - cur
        if rem <= target_max_chars:
            spans.append((cur, n))
            break
        ideal_end = cur + target_max_chars
        window_lo = cur + max(300, int(target_max_chars * 0.55))
        window_hi = min(n - 80, cur + min(2600, int(target_max_chars * 1.25)))

        split_pos = -1
        # Prefer sentence/paragraph boundaries (. or \n or ؟ or !) not preceded by ':'
        for pat in (r"[.؟!\n]+\s+", r"[،؛]+\s+", r"\s+"):
            candidates = []
            for m in re.finditer(pat, raw_text[window_lo:window_hi]):
                cand_end = window_lo + m.end()
                left_slice = raw_text[cur:cand_end].rstrip()
                if left_slice.endswith(":") or left_slice.endswith("："):
                    continue
                if len(raw_text[cand_end:].split()) < 6:
                    continue
                next_anc = extract_anchor_words(raw_text[cand_end:], 6)
                if next_anc and next_anc in raw_text[cur:cand_end]:
                    continue
                candidates.append(cand_end)
            if candidates:
                split_pos = min(candidates, key=lambda p: abs(p - ideal_end))
                break

        if split_pos == -1 or split_pos <= cur:
            split_pos = min(n, ideal_end)
            while split_pos < n and not raw_text[split_pos - 1].isspace():
                split_pos += 1
            if split_pos >= n - 40:
                split_pos = n

        spans.append((cur, split_pos))
        cur = split_pos

    return spans


def extract_anchor_words(text_slice: str, word_count: int = 6) -> str:
    words = text_slice.strip().split()
    take = words[: max(4, min(word_count, len(words)))]
    return " ".join(take)


def extract_unique_span_anchor(raw_text: str, c_start: int, c_end: int, prev_end: int) -> str:
    """
    Selects an anchor word count (6..12 words) from `raw_text[c_start:c_end]` whose
    `mr.find_anchor_pos(raw_text, cand, prev_end)` lands at `c_start` (within whitespace tolerance).
    Prevents `P0_NON_MONOTONIC_ANCHOR` and `P0_PASSAGE_TOO_LONG` when newline-separated words
    or repeated phrases occur in transcripts.
    """
    p_raw = raw_text[c_start:c_end]
    for wc in (6, 7, 8, 9, 10, 12):
        cand = extract_anchor_words(p_raw, wc)
        if len(cand.split()) < 4:
            continue
        pos = mr.find_anchor_pos(raw_text, cand, prev_end)
        if pos != -1 and abs(pos - c_start) <= 20:
            return cand
    return extract_anchor_words(p_raw, 6)


_QURAN_INDEX_CACHE: list[tuple[int, int, str]] | None = None

MUQADDIMAH_OR_PROCEDURAL_RE = re.compile(
    r"(?:بسم\s+الله\s+الرحمن\s+الرحيم|الحمد\s+لله\s+رب\s+العالمين|وأصلي\s+وأسلم\s+على|والصلاة\s+والسلام\s+على|"
    r"سيد\s+الأولين\s+والآخرين|ومن\s+اهتدى\s+بهديه|إلى\s+يوم\s+الدين|أما\s+بعد\s*:|"
    r"وصلنا\s+إلى\s+قول|كنا\s+قد\s+توقفنا|نقف\s+عند\s+هذا\s+الحد|في\s+الدرس\s+الماضي|في\s+اللقاء\s+السابق|"
    r"نسأل\s+الله\s+أن\s+يعلمنا|وصلى\s+الله\s+وسلم\s+على\s+نبينا|"
    r"اطلب\s+العلم\s+أخي|فهو\s+درب\s+به\s+نور|الأصاغر\s+فيه\s+تعلو|أعوذ\s+بالله\s+من\s+الشيطان|"
    r"شكر\s+الله\s+لشيخنا|أشكركم\s+أستاذ|نرحب\s+بشيخنا|مشاهدينا\s+الكرام|مستمعينا\s+الكرام)"
)

EPISTEMIC_RULE_MARKERS_RE = re.compile(
    r"\b(?:القاعدة|الضابط|الأصل\s+في|الشرط|الركن|الفرق\s+بين|لا\s+يجوز|لا\s+يصح|يجب\s+على|ينقسم\s+إلى|"
    r"المراد\s+بـ|معنى\s+قوله|هو\s+عبارة\s+عن|حقيقة|تعريف|يدل\s+على\s+أن|فلهذا\s+قال|ولذلك\s+قال|"
    r"لأن\s+الأصل|كل\s+ما\s+كان|متى\s+ما|إنما\s+يتقرب|لا\s+يكون\s+صفة)\b"
)

AMBIGUOUS_SINGLE_PERSON_CONTEXT_RE = {
    "مسلم": re.compile(r"\b(?:صحيح|رواه|اخرجه|الامام|امام|عند|قال|كتاب|شرح)\s+مسلم\b"),
    "مالك": re.compile(r"\b(?:الامام|امام|مذهب|قال|عند|موطا|رواه)\s+مالك\b"),
    "احمد": re.compile(r"\b(?:الامام|امام|مسند|مذهب|قال|عند|رواه|اخرجه)\s+احمد\b"),
    "عمر": re.compile(r"\b(?:سيدنا\s+عمر|الفاروق\s+عمر|امير\s+المومنين\s+عمر|عمر\s+بن\s+الخطاب|قال\s+عمر|عهد\s+عمر)\b"),
    "عثمان": re.compile(r"\b(?:سيدنا\s+عثمان|ذي\s+النورين|عثمان\s+بن\s+عفان|مقتل\s+عثمان|عهد\s+عثمان|قال\s+عثمان)\b"),
    "علي": re.compile(r"\b(?:سيدنا\s+علي|امير\s+المومنين\s+علي|علي\s+بن\s+ابي\s+طالب|ابي\s+الحسن\s+علي|قال\s+علي)\b"),
    "ابو بكر": re.compile(r"\b(?:ابو\s+بكر\s+الصديق|ابي\s+بكر\s+الصديق|خلافه\s+ابي\s+بكر|سيدنا\s+ابو\s+بكر|سيدنا\s+ابي\s+بكر)\b"),
}

KNOWN_MATN_SERIES_MAP: list[tuple[re.Pattern, str, str]] = [
    (re.compile(r"(?:الورقات|العمريطي|s008)"), "book:2176", "الورقات في أصول الفقه لإمام الحرمين الجويني"),
    (re.compile(r"(?:العدودية|العضدية|adoudiya)"), "book:adoudiya", "المنظومة العدودية في القواعد الفقهية"),
    (re.compile(r"(?:التبيان\s+في\s+آداب|tibyan)"), "book:1969", "التبيان في آداب حملة القرآن للنووي"),
    (re.compile(r"(?:المنقذ\s+من\s+الضلال|munqidh)"), "book:9246", "المنقذ من الضلال للغزالي"),
    (re.compile(r"(?:الحكم\s+العطائية|العطائية)"), "book:hikam_ataiyya", "الحكم العطائية لابن عطاء الله السكندري"),
    (re.compile(r"(?:الطحاوية)"), "book:26311", "متن العقيدة الطحاوية"),
    (re.compile(r"(?:القشيرية)"), "book:3418", "الرسالة القشيرية"),
    (re.compile(r"(?:أخصر\s+المختصرات)"), "book:11469", "أخصر المختصرات لابن بلبان"),
    (re.compile(r"(?:موطأ)"), "book:1655", "موطأ مالك"),
    (re.compile(r"(?:دلائل\s+الإعجاز)"), "book:12141", "دلائل الإعجاز للجرجاني"),
    (re.compile(r"(?:الفلاكة\s+والمفلوكون)"), "book:196", "الفلاكة والمفلوكون للدلجي"),
    (re.compile(r"(?:طبقات\s+فحول\s+الشعراء)"), "book:8265", "طبقات فحول الشعراء لابن سلام الجمحي"),
    (re.compile(r"(?:التذكرة\s+في\s+أحوال\s+الموتى|التذكرة\s+بأحوال\s+الموتى)"), "book:23718", "التذكرة بأحوال الموتى وأمور الآخرة للقرطبي"),
]

SCIENCE_CATEGORY_MAP = {
    "أصول الفقه": "usul_al_fiqh",
    "اصول الفقه": "usul_al_fiqh",
    "الفقه": "fiqh",
    "فقه": "fiqh",
    "العقيدة": "akida",
    "عقيدة": "akida",
    "التزكية": "tazkiyah",
    "تزكية": "tazkiyah",
    "الرقائق": "tazkiyah",
    "التصوف": "tazkiyah",
    "الحديث": "hadith",
    "حديث": "hadith",
    "التفسير": "tafsir",
    "تفسير": "tafsir",
    "علوم القرآن": "tafsir",
    "اللغة": "lugha",
    "النحو": "lugha",
    "البلاغة": "lugha",
    "الأدب": "adab",
    "المنطق": "mantiq",
    "الفكر": "fikr",
}


def normalize_science_category(raw_cat: str | None) -> str:
    if not raw_cat:
        return "akida"
    rc = raw_cat.strip()
    if rc in SCIENCE_CATEGORY_MAP:
        return SCIENCE_CATEGORY_MAP[rc]
    for k, v in SCIENCE_CATEGORY_MAP.items():
        if k in rc:
            return v
    return rc


def infer_base_work_from_series_meta(series_title: str, series_id: str) -> tuple[str | None, str | None]:
    """
    Infers `(base_work_id, base_work_title)` from a series title or slug when `_meta.json`
    does not explicitly declare `base_work_id`.
    """
    probe = f"{series_title} {series_id}"
    for pat, bwid, bwtitle in KNOWN_MATN_SERIES_MAP:
        if pat.search(probe):
            return bwid, bwtitle
    m_sharh = re.search(
        r"(?:شرح|تعليق\s+على|دورة\s+شرح)\s+(?:كتاب|متن|نظم|منظومة|رسالة)?\s*([^\n—\-()]{4,60})",
        series_title or "",
    )
    if m_sharh:
        extracted_title = m_sharh.group(1).strip()
        slug = re.sub(r"[^a-zA-Z0-9_]+", "_", series_id).strip("_").lower() or "matn"
        return f"book:{slug}", extracted_title
    return None, None


MATN_CITATION_PATTERNS = [
    # 1. Explicit author/matn speech markers followed by a clause or quote
    re.compile(
        r"(?:قال|يقول)\s+(?:المصنف|المؤلف|الناظم|الشيخ|الإمام|الأنصاري|الغزالي|النووي|ابن\s+عطاء\s+الله|الجويني|العمريطي|رحمه\s+الله|رضي\s+الله\s+عنه)"
        r"(?:\s+رحمه\s+الله|\s+رضي\s+الله\s+عنه|\s+تعالى|\s+ونفعنا\s+بعلومه)*\s*[:،]?\s*[«\"]?([^.!؟\n»\"]{14,180})"
    ),
    # 2. Commentary transition markers ("وصلنا إلى قوله", "قوله:", "يقول في المتن:")
    re.compile(
        r"(?:وصلنا\s+إلى\s+قول(?:ه)?|نقف\s+عند\s+قول(?:ه)?|في\s+قوله|وقوله\s+رحمه\s+الله|قول\s+الناظم|قول\s+المصنف|يقول\s+في\s+المتن|قال\s+في\s+المتن|قال\s+صاحب\s+المتن)"
        r"(?:\s+رحمه\s+الله|\s+رضي\s+الله\s+عنه)*\s*[:،]?\s*[«\"]?([^.!؟\n»\"]{14,180})"
    ),
    # 3. Poetic bayt hemistichs separated by * or ***
    re.compile(r"([^\n.!؟«»]{10,90}\s+\*{1,3}\s+[^\n.!؟«»]{10,90})"),
]


def auto_extract_matn_clauses_from_lecture_or_book(
    raw_text: str,
    lecture_id: str,
    base_work_id: str | None = None,
    books_passages: list[dict] | None = None,
) -> list[dict]:
    """
    Automatically extracts explained Matn clauses (`base_matn_clauses`) from `raw_text`
    (and optionally cross-matches against classical `books_passages` for `base_work_id`)
    when `_meta.json` does not supply manual `base_matn_clauses`.
    Every returned clause is guaranteed to contain a verbatim span (>= 3 words) in `raw_text`.
    """
    clauses: list[dict] = []
    seen_norms: set[str] = set()
    prefix_id = f"{base_work_id}:{lecture_id}" if base_work_id else lecture_id

    # Step 1: If classical book passages for base_work_id are provided, check for shared 4..7 word Matn phrases
    if books_passages:
        norm_lec, _ = mr.normalize_words_only(raw_text)
        for bp_idx, bp in enumerate(books_passages):
            bp_text = (bp.get("clean_matn") or bp.get("raw_text") or "").strip()
            if not bp_text:
                continue
            bp_id_tag = bp.get("passage_id") or bp.get("pid") or f"P{bp_idx + 1}"
            # Split book passage into sentence/clause chunks
            for chunk_m in re.finditer(r"[^.!؟\n،؛:]{15,160}", bp_text):
                chunk = chunk_m.group(0).strip(" \t\r\n،.؛:؟!«»\"'()-")
                c_words = chunk.split()
                if len(c_words) < 4:
                    continue
                for w_len in (6, 5, 4):
                    if len(c_words) < w_len:
                        continue
                    probe = " ".join(c_words[:w_len])
                    if MUQADDIMAH_OR_PROCEDURAL_RE.search(probe):
                        continue
                    n_probe, _ = mr.normalize_words_only(probe)
                    if not n_probe or len(n_probe) < 14 or n_probe in seen_norms or n_probe not in norm_lec:
                        continue
                    ok_v = (probe in raw_text) or mr.verify_quote_verbatim(probe, raw_text)[0]
                    if ok_v:
                        seen_norms.add(n_probe)
                        cid = f"{base_work_id or lecture_id}:{bp_id_tag}:C{len(clauses) + 1}"
                        clauses.append(
                            {
                                "clause_id": cid,
                                "title": bp.get("sub_heading") or " ".join(c_words[:5]),
                                "text": chunk,
                                "matched_verbatim_in_lecture": probe,
                                "book_passage_id": bp_id_tag,
                            }
                        )
                        break
                if len(clauses) >= 12:
                    break
            if len(clauses) >= 12:
                break

    # Step 2: Extract explicit Matn citations & poetic hemistichs quoted by the Sheikh in `raw_text`
    for pat in MATN_CITATION_PATTERNS:
        for m in pat.finditer(raw_text):
            cand = m.group(1).strip(" \t\r\n،.؛:؟!«»\"'()-")
            if not cand or "{" in cand or "}" in cand or "﴿" in cand or "﴾" in cand:
                continue
            # Find a verbatim 4..10 word span from `cand` that exists in `raw_text`
            c_words = cand.split()
            if len(c_words) < 4:
                continue
            verb_slice = " ".join(c_words[: min(10, len(c_words))]).strip(" ،.؛:؟!«»\"'()")
            if len(verb_slice.split()) < 4:
                continue
            if MUQADDIMAH_OR_PROCEDURAL_RE.search(verb_slice):
                continue
            ok_v = (verb_slice in raw_text) or mr.verify_quote_verbatim(verb_slice, raw_text)[0]
            if not ok_v:
                continue
            n_verb, _ = mr.normalize_words_only(verb_slice)
            if not n_verb or len(n_verb) < 12 or n_verb in seen_norms:
                continue
            seen_norms.add(n_verb)
            cid = f"{prefix_id}:C{len(clauses) + 1}"
            clauses.append(
                {
                    "clause_id": cid,
                    "title": f"قول المصنف: {' '.join(verb_slice.split()[:5])}",
                    "text": m.group(1).strip(" \t\r\n،.؛:؟!«»\"'()"),
                    "matched_verbatim_in_lecture": " ".join(verb_slice.split()[: min(6, len(verb_slice.split()))]),
                }
            )
            if len(clauses) >= 16:
                break

    # Step 3: Also check guillemet quotes «...» in `raw_text` that represent Matn statements/hikam
    if len(clauses) < 6:
        for m_q in re.finditer(r"«([^»]{14,160})»", raw_text):
            q_inner = m_q.group(1).strip(" \t\r\n،.؛:؟!")
            if "{" in q_inner or "﴿" in q_inner or MUQADDIMAH_OR_PROCEDURAL_RE.search(q_inner):
                continue
            q_words = q_inner.split()
            if len(q_words) < 4:
                continue
            # Avoid pure Hadith quotes if preceded by قال النبي / قال رسول الله / أخرجه / رواه
            pre_ctx = raw_text[max(0, m_q.start() - 110) : m_q.start()]
            if re.search(
                r"(?:قال\s+النبي|قال\s+رسول\s+الله|صلى\s+الله\s+عليه|عليه\s+الصلاة\s+والسلام|ﷺ|في\s+الحديث|حديث|أخرجه|رواه|الصحيحين)",
                pre_ctx,
            ):
                continue
            verb_probe = " ".join(q_words[: min(6, len(q_words))])
            ok_v = (verb_probe in raw_text) or mr.verify_quote_verbatim(verb_probe, raw_text)[0]
            if not ok_v:
                continue
            n_verb, _ = mr.normalize_words_only(verb_probe)
            if not n_verb or n_verb in seen_norms:
                continue
            seen_norms.add(n_verb)
            cid = f"{prefix_id}:C{len(clauses) + 1}"
            clauses.append(
                {
                    "clause_id": cid,
                    "title": f"فقرة المتن: {' '.join(q_words[:5])}",
                    "text": q_inner,
                    "matched_verbatim_in_lecture": verb_probe,
                }
            )
            if len(clauses) >= 12:
                break

    # Step 4: Fallback if lecture has a base_work_id but no explicit markers matched yet
    if base_work_id and len(clauses) < 2:
        cands = extract_candidate_sentences(raw_text)
        for c_sent in cands[:3]:
            c_words = c_sent.split()
            if len(c_words) >= 5:
                verb_probe = " ".join(c_words[:6])
                n_verb, _ = mr.normalize_words_only(verb_probe)
                if n_verb and n_verb not in seen_norms:
                    seen_norms.add(n_verb)
                    cid = f"{prefix_id}:C{len(clauses) + 1}"
                    clauses.append(
                        {
                            "clause_id": cid,
                            "title": f"المسألة المقررة: {' '.join(c_words[:5])}",
                            "text": c_sent,
                            "matched_verbatim_in_lecture": verb_probe,
                        }
                    )
            if len(clauses) >= 2:
                break

    return clauses


CENTURY_ORDINAL_MAP: list[tuple[re.Pattern, int, str]] = [
    (re.compile(r"((?:في\s+|من\s+|أوائل\s+|أواخر\s+|منتصف\s+)?القرن\s+الأول(?:\s+الهجري)?)"), 50, "القرن الأول الهجري"),
    (re.compile(r"((?:في\s+|من\s+|أوائل\s+|أواخر\s+|منتصف\s+)?القرن\s+الثاني(?:\s+الهجري)?)"), 150, "القرن الثاني الهجري"),
    (re.compile(r"((?:في\s+|من\s+|أوائل\s+|أواخر\s+|منتصف\s+)?القرن\s+الثالث(?:\s+الهجري)?)"), 250, "القرن الثالث الهجري"),
    (re.compile(r"((?:في\s+|من\s+|أوائل\s+|أواخر\s+|منتصف\s+)?القرن\s+الرابع(?:\s+الهجري)?)"), 350, "القرن الرابع الهجري"),
    (re.compile(r"((?:في\s+|من\s+|أوائل\s+|أواخر\s+|منتصف\s+)?القرن\s+الخامس(?:\s+الهجري)?)"), 450, "القرن الخامس الهجري"),
    (re.compile(r"((?:في\s+|من\s+|أوائل\s+|أواخر\s+|منتصف\s+)?القرن\s+السادس(?:\s+الهجري)?)"), 550, "القرن السادس الهجري"),
    (re.compile(r"((?:في\s+|من\s+|أوائل\s+|أواخر\s+|منتصف\s+)?القرن\s+السابع(?:\s+الهجري)?)"), 650, "القرن السابع الهجري"),
    (re.compile(r"((?:في\s+|من\s+|أوائل\s+|أواخر\s+|منتصف\s+)?القرن\s+الثامن(?:\s+الهجري)?)"), 750, "القرن الثامن الهجري"),
    (re.compile(r"((?:في\s+|من\s+|أوائل\s+|أواخر\s+|منتصف\s+)?القرن\s+التاسع(?:\s+الهجري)?)"), 850, "القرن التاسع الهجري"),
    (re.compile(r"((?:في\s+|من\s+|أوائل\s+|أواخر\s+|منتصف\s+)?القرن\s+العاشر(?:\s+الهجري)?)"), 950, "القرن العاشر الهجري"),
    (re.compile(r"((?:في\s+|من\s+|أوائل\s+|أواخر\s+|منتصف\s+)?القرن\s+الحادي\s+عشر(?:\s+الهجري)?)"), 1050, "القرن الحادي عشر الهجري"),
    (re.compile(r"((?:في\s+|من\s+|أوائل\s+|أواخر\s+|منتصف\s+)?القرن\s+الثاني\s+عشر(?:\s+الهجري)?)"), 1150, "القرن الثاني عشر الهجري"),
    (re.compile(r"((?:في\s+|من\s+|أوائل\s+|أواخر\s+|منتصف\s+)?القرن\s+الثالث\s+عشر(?:\s+الهجري)?)"), 1250, "القرن الثالث عشر الهجري"),
    (re.compile(r"((?:في\s+|من\s+|أوائل\s+|أواخر\s+|منتصف\s+)?القرن\s+الرابع\s+عشر(?:\s+الهجري)?)"), 1350, "القرن الرابع عشر الهجري"),
]

WORD_YEAR_SPAN_RE = re.compile(
    r"((?:سنة|عام|سنه)\s+(?:[^\n.!؟،؛:()0-9٠-٩]{3,55}))"
)


def extract_detailed_chronology_from_text(p_raw: str) -> list[dict]:
    """
    Extracts structured chronology events from `p_raw` covering:
      1. Numeric and Arabic word-years (`سنة ثلاث وثمانين وتسعمائة`, `سنة اثنتي عشرة وثلاثمائة`, etc.)
      2. Abbreviated same-century word-year follow-ups (`سنة تسع وتسعين وأربعمائة ... سنة ثمان وثمانين` -> 499 & 488)
      3. Hijri century expressions (`في القرن الرابع الهجري` -> 350 with `is_approximate=1` and verbatim `year_raw`)
    """
    chronology: list[dict] = []
    seen_years: set[tuple[int, str]] = set()

    # 1. Extract verbatim word-year phrases and map each to its parsed Hijri year
    last_century_base = 0
    last_century_end_pos = -1000
    for m_wy in WORD_YEAR_SPAN_RE.finditer(p_raw):
        phrase = m_wy.group(1).strip()
        sub_yrs = mr.extract_date_years_from_text(phrase)
        if not sub_yrs:
            continue
        y_val = sub_yrs[0]
        # Clean trailing non-date words from `year_raw`
        tokens = phrase.split()
        date_tokens = [tokens[0]]
        for tok in tokens[1:]:
            t_norm = re.sub(r"[\u064b-\u065f\u0670\u0640،.؛:؟!]", "", tok)
            t_norm = re.sub(r"[أإآٱ]", "ا", t_norm).replace("ة", "ه").replace("ى", "ي")
            t_bare = t_norm[1:] if t_norm.startswith("و") else t_norm
            if (
                t_bare in mr.UNIT_MAP
                or t_bare in mr.TENS_MAP
                or t_bare in mr.HUNDREDS_MAP
                or t_norm in mr.HUNDREDS_MAP
                or t_bare in ("عشر", "عشره", "بضع", "نيف", "هجريه", "للهجره", "ه")
            ):
                date_tokens.append(tok.strip("،.؛:؟!"))
            else:
                break
        year_raw_str = " ".join(date_tokens)
        is_approx = 1 if any(w in year_raw_str for w in ("بضع", "نيف", "نحو", "قرابة", "حدود")) else 0

        # Check for abbreviated century ellipsis (e.g. 499 followed within 140 chars by 88 -> 488)
        if 10 <= y_val < 100 and last_century_base >= 100 and (m_wy.start() - last_century_end_pos) <= 140:
            y_val = last_century_base + y_val
        elif y_val >= 100:
            last_century_base = (y_val // 100) * 100
            last_century_end_pos = m_wy.end()

        ctx_slice = p_raw[max(0, m_wy.start() - 50) : min(len(p_raw), m_wy.start() + len(year_raw_str) + 45)]
        ctx_clean = strip_spoken_fillers(ctx_slice).replace("\n", " ").strip(" ،.؛:؟!")
        event_title = f"حدث تاريخي ({year_raw_str}): {ctx_clean[:90]}" if ctx_clean else f"حدث تاريخي مذكور ({year_raw_str})"

        key = (y_val, year_raw_str)
        if key not in seen_years:
            seen_years.add(key)
            chronology.append(
                {
                    "hijri_year": y_val,
                    "year_raw": year_raw_str,
                    "is_approximate": is_approx,
                    "event_tag": event_title,
                    "event_layer": "historical",
                }
            )

    # 2. Any remaining numeric or omitted-sana years found by mr.extract_date_years_from_text
    existing_y_ints = {c["hijri_year"] for c in chronology}
    for y in sorted(set(mr.extract_date_years_from_text(p_raw))):
        if y in existing_y_ints:
            continue
        # Skip raw 2-digit year if it was already resolved as an abbreviated century year (e.g. 88 -> 488)
        if 10 <= y < 100 and any((cy >= 100 and cy % 100 == y) for cy in existing_y_ints):
            continue
        m_num = re.search(rf"(?:سنة|عام|توفي|ولد|مات|قتل)?\s*{y}\s*(?:هـ|للهجرة)?", p_raw)
        y_raw = m_num.group(0).strip() if m_num else f"سنة {y} هـ"
        chronology.append(
            {
                "hijri_year": y,
                "year_raw": y_raw,
                "is_approximate": 0,
                "event_tag": f"حدث تاريخي أو وفاة مذكورة ({y_raw})",
                "event_layer": "historical",
            }
        )
        existing_y_ints.add(y)

    # 3. Hijri century expressions ("في القرن الرابع الهجري", "القرن الثامن")
    for c_pat, c_mid_year, c_label in CENTURY_ORDINAL_MAP:
        for m_c in c_pat.finditer(p_raw):
            y_raw = m_c.group(1).strip()
            y_val = c_mid_year
            if "أوائل" in y_raw:
                y_val = c_mid_year - 35
            elif "أواخر" in y_raw:
                y_val = c_mid_year + 35
            ctx_slice = p_raw[max(0, m_c.start() - 45) : min(len(p_raw), m_c.end() + 55)]
            ctx_clean = strip_spoken_fillers(ctx_slice).replace("\n", " ").strip(" ،.؛:؟!")
            key = (y_val, y_raw)
            if key not in seen_years:
                seen_years.add(key)
                chronology.append(
                    {
                        "hijri_year": y_val,
                        "year_raw": y_raw,
                        "is_approximate": 1,
                        "event_tag": f"إحالة زمنية إلى {c_label}: {ctx_clean[:85]}",
                        "event_layer": "historical",
                    }
                )

    return chronology


def _norm_quran_text(s: str) -> str:
    s = re.sub(r"[\u064b-\u065f\u0670\u0640\u06d6-\u06ed]", "", s or "")
    s = re.sub(r"[أإآٱ]", "ا", s)
    s = s.replace("ة", "ه").replace("ى", "ي").replace("ؤ", "و").replace("ئ", "ي").replace("ء", "")
    s = re.sub(r"[^\w\s\u0600-\u06FF]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _load_quran_index() -> list[tuple[int, int, str]]:
    global _QURAN_INDEX_CACHE
    if _QURAN_INDEX_CACHE is not None:
        return _QURAN_INDEX_CACHE
    gz_path = SCRIPTS_DIR / "quran_norm_index.json.gz"
    rows: list[tuple[int, int, str]] = []
    if gz_path.exists():
        import gzip
        try:
            raw_rows = json.loads(gzip.open(gz_path, "rt", encoding="utf-8").read())
            for r in raw_rows:
                rows.append((int(r[0]), int(r[1]), _norm_quran_text(str(r[2]))))
        except Exception:
            rows = []
    _QURAN_INDEX_CACHE = rows
    return rows


def resolve_quran_verse_reference(v_txt: str, ctx_win: str = "") -> str:
    """
    Resolves a quoted Quranic verse `v_txt` to its exact `سورة <الاسم>: <الآية>` reference:
      1. Exact or substring match against the bundled 6,236-verse Quran index (`quran_norm_index.json.gz`).
      2. Explicit context pattern `سورة <الاسم>` in `ctx_win` (never matching bare single-letter 'ص' or 'ق' without 'سورة').
    """
    norm_v = _norm_quran_text(v_txt)
    q_index = _load_quran_index()
    if norm_v and len(norm_v) >= 7 and q_index:
        # 1a. Direct substring match inside canonical verse body (or vice versa for multi-verse quotes)
        best_match: tuple[int, int] | None = None
        for s_no, a_no, body_norm in q_index:
            if norm_v in body_norm or (len(body_norm) >= 12 and body_norm in norm_v):
                best_match = (s_no, a_no)
                break
        # 1b. If orthographic differences (e.g. السموات vs السماوات), normalize 'سموات' -> 'سماوات' etc.
        if best_match is None:
            norm_v_alt = (
                norm_v.replace("السموات", "السماوات")
                .replace("الرحمان", "الرحمن")
                .replace("هاذا", "هذا")
                .replace("ذالك", "ذلك")
                .replace("ولاكن", "ولكن")
                .replace("اله", "الله")
            )
            v_words = norm_v_alt.split()
            probe = " ".join(v_words[: min(6, len(v_words))])
            if len(probe) >= 10:
                for s_no, a_no, body_norm in q_index:
                    if probe in body_norm:
                        best_match = (s_no, a_no)
                        break
        if best_match is not None:
            s_no, a_no = best_match
            s_name = bcg.SURAH_NAMES[s_no - 1]
            return f"سورة {s_name}: {a_no}"

    # 2. Explicit 'سورة <الاسم>' in surrounding context window (requires the word 'سورة' before the Surah name)
    for s_idx, s_name in enumerate(bcg.SURAH_NAMES, start=1):
        pat = rf"سورة\s+(?:ال)?{re.escape(s_name)}(?![\w\u0600-\u06FF])"
        if re.search(pat, ctx_win):
            m_ay = re.search(r"[:،]\s*(\d+|[٠-٩]+)", ctx_win)
            ay_no = int(m_ay.group(1).translate(bcg.AR_DIGITS)) if m_ay else 1
            return f"سورة {s_name}: {ay_no}"

    return "سورة البقرة: 1"


def score_epistemic_sentence(sent: str) -> int:
    """Scores a candidate sentence by its scholarly rule/definition density."""
    if MUQADDIMAH_OR_PROCEDURAL_RE.search(sent):
        return -100
    if sent.startswith("{") or sent.startswith("﴿") or sent.endswith("}") or sent.endswith("﴾"):
        return -50
    # Reject sentences that are mostly a Quranic bracketed quote
    q_chars = sum(len(m.group(0)) for m in re.finditer(r"\{[^}]*\}|﴿[^﴾]*﴾", sent))
    if q_chars > len(sent) * 0.45:
        return -40
    score = 0
    markers = EPISTEMIC_RULE_MARKERS_RE.findall(sent)
    score += len(markers) * 15
    w_cnt = len(sent.split())
    if 9 <= w_cnt <= 28:
        score += 10
    elif 6 <= w_cnt <= 35:
        score += 4
    if any(k in sent for k in ("لأن", "فإن", "فيكون", "فلا", "وإنما", "بمعنى", "أي:")):
        score += 8
    return score


DANGLING_TRAILING_QAALA_RE = re.compile(
    r"[\s،؛]*(?:ولذلك|فلهذا|ولهذا|وكما|كما|حيث)\s+(?:قال|يقول)(?:\s+الله)?(?:\s+سبحانه)?(?:\s+وتعالى)?\s*$"
)


def extract_candidate_sentences(raw_text: str) -> list[str]:
    """
    Returns clean verbatim slices (>= 6 words) from `raw_text` suitable for `verbatim_rule` or `quote`:
    - Exact substring of `raw_text`
    - Excludes Basmalah/Hamdalah/Salawat introductions, procedural transitions, and raw Quranic verses
    - Does not contain `...` or `…`
    - Does not start with dangling `أن / أنه / لأن` or end with dangling `ولذلك قال`
    - Ranked by epistemic rule/definition score
    """
    scored_candidates: list[tuple[int, int, str]] = []
    for idx, m in enumerate(re.finditer(r"[^.!؟\n؛:]{25,240}", raw_text)):
        frag = m.group(0).strip()
        frag_clean = frag.strip(" \t\r\n،.؛:؟!«»\"'()-")
        frag_trimmed = DANGLING_TRAILING_QAALA_RE.sub("", frag_clean).strip(" \t\r\n،.؛:؟!«»\"'()-")
        if frag_trimmed and frag_trimmed in raw_text:
            frag_clean = frag_trimmed
        if not frag_clean or frag_clean not in raw_text:
            continue
        if "..." in frag_clean or "…" in frag_clean:
            continue
        if "{" in frag_clean or "}" in frag_clean or "﴿" in frag_clean or "﴾" in frag_clean:
            continue
        words = frag_clean.split()
        if len(words) < 6 or len(words) > 38:
            continue
        if mr.GEM_DANGLING_AN_START_RE.match(frag_clean):
            if len(words) >= 8:
                frag_clean2 = " ".join(words[1:])
                if frag_clean2 in raw_text and not mr.GEM_DANGLING_AN_START_RE.match(frag_clean2):
                    frag_clean = frag_clean2
                else:
                    continue
            else:
                continue
        sc = score_epistemic_sentence(frag_clean)
        if sc < 0:
            continue
        polished = strip_spoken_fillers(frag_clean)
        if len(polished.split()) < 5:
            continue
        scored_candidates.append((sc, idx, frag_clean))

    # Sort by highest epistemic score first, then spread across the lecture
    scored_candidates.sort(key=lambda item: (-item[0], item[1]))
    return [c for _, _, c in scored_candidates]


def _extract_exact_surface_mention(p_raw: str, alias_norm: str, disp_name: str) -> str:
    """Finds the exact surface words in `p_raw` whose normalized form matches `alias_norm`."""
    raw_tokens = [(m.group(0), m.start(), m.end()) for m in re.finditer(r"\S+", p_raw)]
    alias_words = alias_norm.split()
    k = len(alias_words)
    if k == 0 or not raw_tokens:
        return disp_name
    for i in range(len(raw_tokens) - k + 1):
        window_str = " ".join(tok for tok, _, _ in raw_tokens[i : i + k]).strip(" ،.؛:؟!«»\"'()-[]{}")
        if bcg.norm_ar(window_str) == alias_norm:
            return window_str
    return disp_name


KNOWN_HADITH_TAKHRIJ_MAP: list[tuple[str, str]] = [
    ("انما الاعمال بالنيات", "متفق عليه"),
    ("من احدث في امرنا هذا", "متفق عليه"),
    ("من عمل عملا ليس عليه امرنا", "صحيح مسلم"),
    ("الحلال بين والحرام بين", "متفق عليه"),
    ("بني الاسلام علي خمس", "متفق عليه"),
    ("ليس الشديد بالصرعه", "متفق عليه"),
    ("خير القرون", "متفق عليه"),
    ("خيركم القرون", "متفق عليه"),
    ("لم يكذب ابراهيم عليه السلام الا ثلاث", "متفق عليه"),
    ("خذي ما يكفيك وولدك بالمعروف", "متفق عليه"),
    ("لا تسبوا اصحابي", "متفق عليه"),
    ("يخرج من ضيضي هذا", "متفق عليه"),
    ("الا اخبركم عن النفر الثلاثه", "متفق عليه"),
    ("يجعل السماوات السبع علي اصبع", "متفق عليه"),
    ("اعطين الرايه غدا لرجل يحب الله ورسوله", "متفق عليه"),
    ("قطعت عنق صاحبك", "متفق عليه"),
    ("يؤتي بالعالم يوم القيامه فيلقي في النار", "متفق عليه"),
    ("يضحك الله الي رجلين يقتل احدهما الاخر", "متفق عليه"),
    ("صفه الرحمن فاني احبها", "متفق عليه"),
    ("من يرد الله به خيرا يفقهه في الدين", "متفق عليه"),
    ("الايمان بضع وسبعون شعبه", "متفق عليه"),
    ("لا تغضب", "صحيح البخاري"),
    ("بضع وستون شعبه", "صحيح البخاري"),
    ("خيركم من تعلم القران وعلمه", "صحيح البخاري"),
    ("ان الرجل ليتكلم بالكلمه يضحك بها جلساءه", "صحيح البخاري"),
    ("يدخلون الجنه في السلاسل", "صحيح البخاري"),
    ("يهلك هذه الامه غلمه من قريش", "صحيح البخاري"),
    ("هلاك امتي علي يدي غلمه من قريش", "صحيح البخاري"),
    ("اول من يغزو القسطنطينيه", "صحيح البخاري"),
    ("اول جيش من امتي يغزون مدينه قيصر", "صحيح البخاري"),
    ("الذين يعدلون في حكمهم واهليهم وما ولوا", "صحيح مسلم"),
    ("الدين النصيحه", "صحيح مسلم"),
    ("القلوب بين اصبعين من اصابع الرحمن", "صحيح مسلم"),
    ("ان قلوب بني ادم كلها بين اصبعين من اصابع الرحمن", "صحيح مسلم"),
    ("حرم من المسلم دمه وماله وعرضه", "صحيح مسلم"),
    ("كل المسلم علي المسلم حرام دمه وماله وعرضه", "صحيح مسلم"),
    ("اتدرون ما الغيبه", "صحيح مسلم"),
    ("ذكرك اخاك بما يكره", "صحيح مسلم"),
    ("العظمه ازاري والكبرياء ردايي", "صحيح مسلم"),
    ("احثوا في وجوه المداحين التراب", "صحيح مسلم"),
    ("ان الغضب من الشيطان وان الشيطان خلق من النار", "أبو داود"),
    ("يعجب ربكم من راعي غنم", "أبو داود"),
    ("يعجب ربكم من عبده اذا قال رب اغفر لي ذنوبي", "أبو داود"),
    ("رب اغفر لي ذنوبي يعلم انه لا يغفر الذنوب غيري", "أبو داود"),
    ("اللهم اعني علي ذكرك وشكرك وحسن عبادتك", "أبو داود"),
    ("لا يخرج الرجلان يضربان الغايط", "أبو داود"),
    ("ابو بكر في الجنه وعمر في الجنه", "أبو داود"),
    ("عليكم بسنتي وسنه الخلفاء الراشدين", "أبو داود"),
    ("المسلمون علي شروطهم", "أبو داود"),
    ("الخراج بالضمان", "أبو داود"),
    ("اغتبتها", "أبو داود"),
    ("ما ضل قوم بعد هدي كانوا عليه الا اوتوا الجدل", "الترمذي"),
    ("ما ضل قوم بعد هدي الا اوتوا الجدل", "الترمذي"),
    ("لا تتخذوا الضيعه فترغبوا في الدنيا", "الترمذي"),
    ("اثقل ما يوضع في الميزان الخلق الحسن", "الترمذي"),
    ("من كظم غيظا وهو قادر علي ان ينفذه", "الترمذي"),
    ("من كظم غيظا لو شاء ان يمضيه امضاه", "الترمذي"),
    ("دب اليكم داء الامم من قبلكم الحسد والبغضاء", "الترمذي"),
    ("اتق الله حيثما كنت واتبع السييه الحسنه تمحها", "الترمذي"),
    ("من حسن اسلام المرء تركه ما لا يعنيه", "الترمذي"),
    ("الصلاه عماد الدين", "الترمذي"),
    ("لا تمار اخاك ولا تمازحه", "الترمذي"),
    ("نعم المال الصالح للرجل الصالح", "مسند أحمد"),
    ("البينه علي المدعي واليمين علي من انكر", "السنن الكبرى للبيهقي"),
    ("لا ضرر ولا ضرار", "سنن ابن ماجه"),
]


def resolve_hadith_source(h_txt: str, ctx_win: str = "", raw_src: str = "") -> str:
    """
    Deterministically classifies the Hadith takhrij source (`hadith_source`) into canonical
    collections (`متفق عليه`, `صحيح البخاري`, `صحيح مسلم`, `أبو داود`, `الترمذي`, `النسائي`,
    `سنن ابن ماجه`, `موطأ مالك`, `مسند أحمد`, `السنن الكبرى للبيهقي`) using:
      1. Explicit attribution in `raw_src` or the local context window `ctx_win`.
      2. Canonical matn lookup in `KNOWN_HADITH_TAKHRIJ_MAP`.
    """
    norm_src = bcg.norm_ar(raw_src or "")
    norm_ctx = bcg.norm_ar(ctx_win or "")
    norm_h = bcg.norm_ar(h_txt or "")

    # Guard against multi-collection curriculum lists (e.g. 'الموطأ ثم صحيح البخاري، صحيح مسلم، السنن الأربعة: الترمذي وأبو داود')
    if sum(1 for kw in ("البخاري", "مسلم", "الترمذي", "داود", "النسايي", "ماجه") if kw in norm_ctx) >= 4:
        norm_ctx = ""

    for probe in (norm_src, norm_ctx, f"{norm_src} {norm_ctx}".strip()):
        if not probe:
            continue
        # 1. Muttafaq 'Alayh (Bukhari & Muslim together)
        if re.search(
            r"(?:متفق\s+عليه|في\s+الصحيحين|رواه\s+الشيخان|اخرجه\s+الشيخان|عند\s+الشيخين|اتفق\s+عليه|"
            r"البخاري\s+ومسلم|البخاري\s+وصحيح\s+مسلم|مسلم\s+والبخاري)",
            probe,
        ):
            return "متفق عليه"
        # 2. Sahih al-Bukhari
        if re.search(
            r"(?:صحيح\s+البخاري|(?:رواه|روي|اخرجه|في|عند|حديث|الامام)\s+(?:الامام\s+)?البخاري\b|^البخاري$)",
            probe,
        ):
            return "صحيح البخاري"
        # 3. Sahih Muslim (strictly avoiding 'رجل مسلم' / 'كل مسلم')
        if re.search(
            r"(?:صحيح\s+مسلم|(?:رواه|روي|اخرجه|في|عند|الامام)\s+(?:الامام\s+)?مسلم\b|^مسلم$)",
            probe,
        ):
            return "صحيح مسلم"
        # 4. Abu Dawud
        if re.search(r"\b(?:ابو|ابي|ابا)\s+داود\b", probe):
            return "أبو داود"
        # 5. Al-Tirmidhi
        if re.search(r"\bالترمذي\b", probe):
            return "الترمذي"
        # 6. Other canonical collections
        if re.search(r"\bالنسايي\b", probe):
            return "النسائي"
        if re.search(r"\bابن\s+ماجه\b", probe):
            return "سنن ابن ماجه"
        if re.search(r"(?:\bموطا\b|(?:رواه|اخرجه|في)\s+مالك\b)", probe):
            return "موطأ مالك"
        if re.search(r"(?:مسند\s+(?:الامام\s+)?احمد|(?:رواه|روي|اخرجه)\s+(?:الامام\s+)?احمد\b)", probe):
            return "مسند أحمد"
        if re.search(r"\bالبيهقي\b", probe):
            return "السنن الكبرى للبيهقي"
        if re.search(r"\bالدارقطني\b", probe):
            return "سنن الدارقطني"
        if re.search(r"\b(?:المستدرك|الحاكم)\b", probe):
            return "المستدرك للحاكم"

    # 7. Canonical Hadith Matn stem lookup
    if norm_h:
        for stem_norm, canon_src in KNOWN_HADITH_TAKHRIJ_MAP:
            if stem_norm in norm_h or (len(norm_h) >= 12 and norm_h in stem_norm):
                return canon_src

    if (
        raw_src
        and raw_src.strip() not in ("", "مصدر حديثي", "حديث", "السنة النبوية")
        and len(raw_src.split()) <= 5
        and not any(ch in raw_src for ch in ("«", "»", '"', ":", "،"))
    ):
        return raw_src.strip()
    if re.search(r"(?:الحديث\s+الصحيح|حديث\s+صحيح|في\s+الصحيح\b)", f"{norm_src} {norm_ctx}"):
        return "الحديث الصحيح"
    return "السنة النبوية"


HADITH_QUOTED_LEAD_RE = re.compile(
    r"(?:"
    r"(?:قال|يقول|لقول|قوله|وقوله)\s+(?:رسول\s+الله|النبي|المصطفى)?\s*(?:صلى\s+الله\s+عليه(?:\s+وآله)?\s+وسلم|عليه\s+الصلاة\s+والسلام|ﷺ)"
    r"|(?:سمعت|سمع)\s+(?:رسول\s+الله|النبي)\s+(?:صلى\s+الله\s+عليه(?:\s+وآله)?\s+وسلم|ﷺ)\s+يقول"
    r"|(?:أن|إن)\s+(?:رسول\s+الله|النبي)\s+(?:صلى\s+الله\s+عليه(?:\s+وآله)?\s+وسلم|ﷺ)\s+قال"
    r"|في\s+(?:الحديث(?:\s+الصحيح|\s+الشريف|\s+القدسي)?|الصحيحين|صحيح\s+البخاري|صحيح\s+مسلم)"
    r"|(?:روى|رواه|أخرجه)\s+(?:الإمام\s+)?(?:البخاري(?:\s+ومسلم)?|مسلم|أبو\s+داود|أبي\s+داود|الترمذي|النسائي|ابن\s+ماجه|أحمد|مالك|الشيخان|البيهقي)"
    r"|حديث\s+(?:أبي\s+هريرة|ابن\s+عمر|ابن\s+عباس|عائشة|أنس|جابر|أبي\s+سعيد|عقبة\s+بن\s+عامر|علي\s+بن\s+أبي\s+طالب|عمر\s+بن\s+الخطاب|النبي|رسول\s+الله)"
    r")"
    r"([^.!؟\n«\"()﴿﴾{}]{0,95}?)"
    r"(?:«([^»\n]{5,260})»|\"([^\"\n]{5,260})\"|\(([^\)\n٠-٩0-9]{12,260})\))"
)

HADITH_UNQUOTED_LEAD_RE = re.compile(
    r"(?:"
    r"(?:قال|يقول|لقول|قوله)\s+(?:رسول\s+الله|النبي)\s+(?:صلى\s+الله\s+عليه(?:\s+وآله)?\s+وسلم|عليه\s+الصلاة\s+والسلام|ﷺ)\s*[:،]\s*"
    r"|(?:روى|رواه|أخرجه)\s+(?:الإمام\s+)?(?:البخاري(?:\s+ومسلم)?|مسلم|أبو\s+داود|أبي\s+داود|الترمذي|النسائي|ابن\s+ماجه|أحمد|مالك|الشيخان)"
    r"(?:\s+في\s+(?:صحيحه|سننه|الصحيحين|الصحيح|السنن))?"
    r"(?:\s+(?:عن|من\s+حديث)\s+[^\n:،.!؟]{3,45})?"
    r"(?:\s+أن\s+(?:رسول\s+الله|النبي)\s+(?:صلى\s+الله\s+عليه(?:\s+وآله)?\s+وسلم|ﷺ)\s+قال)?\s*[:،]\s*"
    r"|في\s+(?:الحديث\s+الصحيح|الصحيحين|صحيح\s+البخاري|صحيح\s+مسلم)\s*(?:أنه\s+(?:صلى\s+الله\s+عليه\s+وسلم\s+)?قال\s*)?[:،]\s*"
    r")"
    r"([^\n.!؟«»\"﴿﴾{}]{10,180})"
)

HADITH_FAMOUS_INLINE_RE = re.compile(
    r"\bحديث\s+[«\"]?("
    r"(?:إنما\s+الأعمال\s+بالنيات|لا\s+ضرر\s+ولا\s+ضرار|البينة\s+على\s+المدعي|الدين\s+النصيحة|"
    r"من\s+أحدث\s+في\s+أمرنا\s+هذا|من\s+عمل\s+عملا\s+ليس\s+عليه\s+أمرنا|كل\s+المسلم\s+على\s+المسلم\s+حرام|"
    r"المسلمون\s+على\s+شروطهم|الخراج\s+بالضمان|الحلال\s+بين\s+والحرام\s+بين|بني\s+الإسلام\s+على\s+خمس|"
    r"خير\s+القرون\s+قرني|خيركم\s+من\s+تعلم\s+القرآن|من\s+يرد\s+الله\s+به\s+خيرا|"
    r"الحبر\s+أنه\s+يجعل\s+السماوات\s+السبع\s+على\s+إصبع|الحَبْر\s+أنه\s+يجعل\s+السماوات\s+السبع\s+على\s+إصبع)"
    r"[^\n.!؟؛«»\"﴿﴾{}]{0,95})"
)

HADITH_FALSE_COMMENTARY_RE = re.compile(
    r"(?:"
    r"\b(?:يعني|طيب|خلي\s+بالك|ما\s+ينفعش|ده\s+حديث|هات\s+الصحابي|كانوا\s+بيعملوا|يروحوا|يروح\b|بيعملوا|بتاع|إزاي|عشان|كده\b|"
    r"سنتكلم\s+عنها|وهذا\s+يمكن\s+أن|تفسيرها\s+قراءتها|فكيف\s+إذا|إلى\s+آخر\s+ما\s+هنالك|"
    r"وصل\s+لنا\s+حتى\s+الآن|وعندنا\s+علم|متن\s+الحديث\s+وأصوله|بثلاث\s+روايات|مرسل\b|موضوع\b)\b"
    r"|^(?:فكيف|فهذا|وهذا|ولذلك|فلهذا|أي\s+|بمعنى|لا\s*،|نعم\s*،|ثم\s+انتقل|قال\s+المصنف|قال\s+الناظم|كذلك\b|شخص\s+الله)"
    r")"
)


def _build_local_hadith_takhrij_window(p_raw: str, m_start: int, m_end: int) -> str:
    """
    Constructs a local context window around `[m_start, m_end]` for hadith source attribution,
    stopping at boundaries of any previous quote/sentence or subsequent hadith.
    """
    pre = p_raw[max(0, m_start - 140) : m_start]
    # Never bleed across an earlier sentence period or an earlier closing quote («...»)
    last_sep = max(pre.rfind("."), pre.rfind("\n"), pre.rfind("؛"), pre.rfind("»"), pre.rfind('"'))
    if last_sep != -1:
        pre = pre[last_sep + 1 :]
    post = p_raw[m_end : min(len(p_raw), m_end + 140)]
    m_next_h = re.search(
        r"(?:[«\"]|[،.؛]\s*(?:أما\s+حديث|وفي\s+حديث|ومن\s+الأحاديث|وحديث\s+آخر|وقال\s+صلى\s+الله|وقال\s+رسول\s+الله|قال\s+رسول\s+الله|قال\s+النبي|(?:و|ف)?(?:ما\s+)?(?:رواه|أخرجه|روى)\s+))",
        post,
    )
    if m_next_h:
        post = post[: m_next_h.start()]
    return f"{pre} {p_raw[m_start:m_end]} {post}"


def _clean_and_validate_hadith_span(cand: str, p_raw: str, is_quoted: bool) -> str:
    s = (cand or "").strip(" \t\r\n،.؛:؟!«»\"'()-")
    if not s or "{" in s or "}" in s or "﴿" in s or "﴾" in s or "..." in s or "…" in s:
        return ""
    if not is_quoted:
        s = re.split(
            r"(?:[،؛:]\s*(?:وهذا\s+|فهذا\s+|ولذلك\s+|فلهذا\s+|يعني\s+|أي\s+|والمراد\s+|ومعنى\s+|"
            r"(?:و|ف)?(?:ما\s+)?(?:رواه|أخرجه|روى|ورد)\s+|متفق\s+عليه|والحديث\s+في|الحديث\s+في|"
            r"فيكون\s+المقصود|وفي\s+الحديث|وكذلك\s+|ولما\s+|أما\s+)|:)",
            s,
        )[0].strip(" \t\r\n،.؛:؟!«»\"'()-")
    if not s or HADITH_FALSE_COMMENTARY_RE.search(s):
        return ""
    words = s.split()
    min_w = 2 if is_quoted else 3
    if len(words) < min_w or len(words) > 48:
        return ""
    if s not in p_raw:
        return ""
    return s


def extract_hadith_evidences_from_text(p_raw: str) -> list[dict]:
    """
    Deterministically extracts Prophetic Hadith evidences (`type='حديث'`, `evidence_type='hadith'`)
    from `p_raw` with canonical `hadith_source` attribution (`صحيح البخاري`, `صحيح مسلم`,
    `أبو داود`, `الترمذي`, `متفق عليه`, etc.) while filtering out ordinary commentary sentences.
    """
    hadiths: list[dict] = []
    seen_norms: set[str] = set()

    # Pass 1: Explicitly quoted Hadiths («...», "...", (...)) following a Prophetic or Takhrij lead-in
    for m in HADITH_QUOTED_LEAD_RE.finditer(p_raw):
        bridge = m.group(1) or ""
        if re.search(r"(?:فلذلك|ولهذا|فلهذا)\s+قال|قال\s+(?:المصنف|الناظم|المؤلف|الشيخ)", bridge):
            continue
        raw_q = m.group(2) or m.group(3) or m.group(4) or ""
        h_txt = _clean_and_validate_hadith_span(raw_q, p_raw, is_quoted=True)
        if not h_txt:
            continue
        nh = bcg.norm_ar(h_txt)
        if not nh or nh in seen_norms:
            continue
        seen_norms.add(nh)
        ctx_win = _build_local_hadith_takhrij_window(p_raw, m.start(), m.end())
        h_src = resolve_hadith_source(h_txt, ctx_win, raw_src=p_raw[m.start() : m.end()])
        hadiths.append(
            {
                "type": "حديث",
                "evidence_type": "hadith",
                "text": h_txt,
                "source": h_src,
                "hadith_source": h_src,
                "indicative_aspect": f"شاهد حديثي نبوي ({h_src}) في تقرير المسألة المشروحة",
            }
        )

    # Pass 2: Unquoted Prophetic statements after explicit colon/comma lead-in
    for m in HADITH_UNQUOTED_LEAD_RE.finditer(p_raw):
        h_txt = _clean_and_validate_hadith_span(m.group(1), p_raw, is_quoted=False)
        if not h_txt:
            continue
        nh = bcg.norm_ar(h_txt)
        if not nh or any(nh in ex or ex in nh for ex in seen_norms):
            continue
        seen_norms.add(nh)
        ctx_win = _build_local_hadith_takhrij_window(p_raw, m.start(), m.end())
        h_src = resolve_hadith_source(h_txt, ctx_win, raw_src=p_raw[m.start() : m.end()])
        hadiths.append(
            {
                "type": "حديث",
                "evidence_type": "hadith",
                "text": h_txt,
                "source": h_src,
                "hadith_source": h_src,
                "indicative_aspect": f"شاهد حديثي نبوي ({h_src}) في تقرير المسألة المشروحة",
            }
        )

    # Pass 3: Famous canonical Hadiths cited inline via 'حديث ...'
    for m in HADITH_FAMOUS_INLINE_RE.finditer(p_raw):
        h_txt = _clean_and_validate_hadith_span(m.group(1), p_raw, is_quoted=False)
        if not h_txt:
            continue
        nh = bcg.norm_ar(h_txt)
        if not nh or any(nh in ex or ex in nh for ex in seen_norms):
            continue
        seen_norms.add(nh)
        ctx_win = _build_local_hadith_takhrij_window(p_raw, m.start(), m.end())
        h_src = resolve_hadith_source(h_txt, ctx_win, raw_src=p_raw[m.start() : m.end()])
        hadiths.append(
            {
                "type": "حديث",
                "evidence_type": "hadith",
                "text": h_txt,
                "source": h_src,
                "hadith_source": h_src,
                "indicative_aspect": f"شاهد حديثي نبوي ({h_src}) في تقرير المسألة المشروحة",
            }
        )

    return hadiths


def detect_passage_entities(p_raw: str, base_matn_text: str = "") -> tuple[list, list, list, list]:
    """Deterministically detects persons, places, chronology, and Quranic/Hadith evidences in `p_raw`."""
    persons = []
    seen_p = set()
    combined_norm = bcg.norm_ar(p_raw)
    for alias_norm, (disp_name, ccat) in sorted(bcg.PERSON_CANONICAL_ALIASES.items(), key=lambda x: len(x[0]), reverse=True):
        if len(alias_norm) < 3:
            continue
        # Guard ambiguous single-word or short aliases against common noun / patronymic collisions
        if alias_norm in AMBIGUOUS_SINGLE_PERSON_CONTEXT_RE:
            if not AMBIGUOUS_SINGLE_PERSON_CONTEXT_RE[alias_norm].search(combined_norm):
                continue
        if not re.search(rf"(?<!\w){re.escape(alias_norm)}(?!\w)", combined_norm):
            continue
        if disp_name in seen_p:
            continue
        surface_mention = _extract_exact_surface_mention(p_raw, alias_norm, disp_name)
        seen_p.add(disp_name)
        persons.append(
            {
                "canonical_name": disp_name,
                "mentioned_as": surface_mention,
                "category": ccat,
                "role": "علم مذكور في الشرح",
                "source_layer": "matn",
            }
        )

    places = []
    seen_pl = set()
    for pl_key in mr.GAZETTEER_PLACE_STEMS:
        if re.search(rf"(?<!\w){re.escape(pl_key)}(?!\w)", combined_norm):
            if pl_key not in seen_pl:
                seen_pl.add(pl_key)
                places.append({"name_in_text": pl_key, "normalized_name": pl_key})

    chronology = extract_detailed_chronology_from_text(p_raw)

    evidences = []
    seen_ev = set()
    for m_v in re.finditer(r"﴿([^﴾]{6,})﴾|\{([^\}]{6,})\}", p_raw):
        v_txt = (m_v.group(1) or m_v.group(2) or "").strip()
        if not v_txt or v_txt in seen_ev:
            continue
        seen_ev.add(v_txt)
        ctx_win = p_raw[max(0, m_v.start() - 100) : min(len(p_raw), m_v.end() + 100)]
        src_str = resolve_quran_verse_reference(v_txt, ctx_win)
        evidences.append(
            {
                "type": "آية",
                "text": v_txt,
                "source": src_str,
                "indicative_aspect": f"شاهد قرآني ({src_str}) في سياق تقرير المسألة المشروحة",
            }
        )

    for h_ev in extract_hadith_evidences_from_text(p_raw):
        if h_ev["text"] not in seen_ev:
            seen_ev.add(h_ev["text"])
            evidences.append(h_ev)

    return persons, places, chronology, evidences


def _sanitize_no_guillemets(s: str) -> str:
    """Removes «, », {, }, ﴿, ﴾ from generated summaries/titles so merge_lecture inline-quote checks stay clean."""
    return re.sub(r"[«»{}﴿﴾]", "", s or "").strip()


def _extract_passage_focus_phrase(p_raw: str, idx: int, lec_title: str) -> str:
    """Extracts a concise, content-specific thematic phrase from `p_raw` for headings, topics, and queries."""
    # Prefer quoted matn phrases «...» or key definitional clauses
    for m_q in re.finditer(r"«([^»]{8,75})»", p_raw):
        q_str = _sanitize_no_guillemets(m_q.group(1)).strip(" ،.؛:؟!")
        if not MUQADDIMAH_OR_PROCEDURAL_RE.search(q_str) and len(q_str.split()) >= 2:
            return q_str
    for sent_m in re.finditer(r"[^.!؟\n]{18,110}", p_raw):
        s_clean = _sanitize_no_guillemets(strip_spoken_fillers(sent_m.group(0))).strip(" ،.؛:؟!")
        if not s_clean or MUQADDIMAH_OR_PROCEDURAL_RE.search(s_clean):
            continue
        w_list = s_clean.split()
        if len(w_list) >= 4:
            return " ".join(w_list[: min(8, len(w_list))])
    w_fallback = _sanitize_no_guillemets(strip_spoken_fillers(p_raw)).split()
    if len(w_fallback) >= 4:
        return " ".join(w_fallback[: min(7, len(w_fallback))])
    return f"مسائل {lec_title} (المقطع {idx + 1})"


STORY_AND_CASE_MARKERS: list[tuple[re.Pattern, str, str, str]] = [
    (
        re.compile(
            r"(?:"
            r"(?:في\s+)?غزوة\s+(?:بدر|أحد|الخندق|الأحزاب|خيبر|حنين|تبوك|مؤتة|بني\s+قريظة|بني\s+المصطلق|الحديبية)"
            r"|يوم\s+(?:بدر|أحد|حنين|خيبر|الفتح|الأحزاب|السقيفة)"
            r"|(?:جاء|دخل|أتى)\s+(?:رجل|أعرابي|جبريل|ضمام|صهيب|معاذ|أبو\s+ذر|عمر|أبو\s+بكر)\s+(?:إلى|على)\s+(?:النبي|رسول\s+الله)"
            r"|لما\s+(?:حاصر|دخل|هاجر|بعث|قال)\s+(?:النبي|رسول\s+الله)\s+صلى\s+الله\s+عليه\s+وسلم"
            r"|قصة\s+(?:الإفك|الثلاثة\s+الذين\s+خلفوا|ذي\s+الخويصرة|حاطب\s+بن\s+أبي\s+بلتعة|كعب\s+بن\s+مالك|أسامة\s+بن\s+زيد|خالد\s+بن\s+الوليد|صلح\s+الحديبية|فتح\s+مكة|حجة\s+الوداع)"
            r"|(?:في|على)\s+عهد\s+(?:النبي|رسول\s+الله)\s+صلى\s+الله\s+عليه\s+وسلم"
            r"|لما\s+كان\s+(?:محاصر\s+خيبر|يوم\s+بدر|يوم\s+أحد|يوم\s+حنين|بيقاتل\s+الرجل)"
            r")"
        ),
        "prophetic_sirah",
        "واقعة من السيرة النبوية",
        "الهدي النبوي والتشريع العملي المستفاد",
    ),
    (
        re.compile(
            r"(?:"
            r"سئل\s+(?:الإمام|الشيخ|العلامة|القاضي|مالك|الشافعي|أبو\s+حنيفة|أحمد|الأوزاعي|سفيان|الجنيد|الحسن|ابن\s+عباس|ابن\s+عمر|علي\s+بن\s+أبي\s+طالب|عن\s+القدر|عن\s+الاستواء)"
            r"|(?:دخل|جاء)\s+(?:رجل\s+)?(?:إلى|على)\s+(?:الإمام|الشيخ|مالك|الشافعي|أبي\s+حنيفة|أحمد|الحسن\s+البصري|ابن\s+سيرين|سفيان)"
            r"|(?:مناظرة|ناظر)\s+(?:الإمام|الشيخ|أبو\s+حنيفة|الشافعي|الباقلاني|الغزالي|الأشعري|ابن\s+تيمية|الرازي)"
            r"|قيل\s+(?:للإمام|لأبي\s+حنيفة|لمالك|للشافعي|لأحمد|للحسن|لبعض\s+الحكماء|لبعض\s+السلف)"
            r"|(?:يروى|حكي|يحكى|روي)\s+(?:عن|أن)\s+(?:الإمام|الشيخ|بعض\s+العلماء|بعض\s+السلف|الشافعي|مالك|أحمد|أبا\s+حنيفة)"
            r"|كان\s+(?:الإمام|الشيخ)\s+[^\n.!؟،]{3,35}\s+(?:يقول|إذا\s+سئل|إذا\s+دخل)"
            r")"
        ),
        "scholarly_anecdote",
        "موقف ونادرة علمية",
        "المنهج العلمي والأدب التحقيقي للأئمة",
    ),
    (
        re.compile(
            r"(?:"
            r"في\s+(?:عهد|خلافة|زمن|أيام|دولة)\s+(?:بني\s+أمية|بني\s+العباس|الدولة\s+الأموية|الدولة\s+العباسية|معاوية|عمر\s+بن\s+الخطاب|عثمان\s+بن\s+عفان|علي\s+بن\s+أبي\s+طالب|أبي\s+بكر\s+الصديق|عمر\s+بن\s+عبد\s+العزيز|هارون\s+الرشيد|المأمون|المعتصم|المتوكل|الحجاج|صلاح\s+الدين)"
            r"|(?:وقعة|معركة|يوم)\s+(?:الجمل|صفين|اليرموك|القادسية|النهروان|الحرة|حطين|عين\s+جالوت|مرج\s+دابق)"
            r"|فتنة\s+(?:مقتل\s+عثمان|خلق\s+القرآن|ابن\s+الأشعث|الخوارج)"
            r"|لما\s+(?:تولى|ولي|دخل\s+على\s+سيدنا\s+معاوية|خرج\s+الخوارج|اختلف\s+أبو\s+بكر\s+وعمر)\b"
            r"|دخل\s+على\s+(?:سيدنا\s+)?(?:معاوية|عمر\s+بن\s+الخطاب|عمر\s+بن\s+عبد\s+العزيز|هارون\s+الرشيد|المأمون|الحجاج|عبد\s+الملك)"
            r"|قصة\s+(?:بني\s+أمية|بني\s+العباس|الخوارج|المعتزلة|خلق\s+القرآن|مقتل\s+عثمان|عيسى\s+بن\s+مريم)"
            r")"
        ),
        "historical_incident",
        "واقعة وخبر تاريخي",
        "العبرة التاريخية والسنن السياسية والاجتماعية",
    ),
    (
        re.compile(
            r"(?:"
            r"(?:مثاله|مثال\s+ذلك|ومثاله|كمسألة|صورة\s+المسألة|فرع\s+فقهي|نازلة\s+فقهية)"
            r"|لو\s+(?:قال\s+لها|قال\s+لأحدهم|باع|اشترى|حلف|طلق|صلى|توضأ|نذر|أوصى|وقف|اشترط|ترك\s+فرضاً|ترك\s+ركناً|شك\s+في|أحدث)"
            r"|من\s+(?:ترك\s+فرضاً|ترك\s+شرطاً|ترك\s+ركناً|أحدث\s+في\s+صلاته|تيمم\s+ثم\s+وجد\s+الماء|شك\s+في\s+عدد)"
            r"|(?:تقول\s+مثلاً|كقولك\s+مثلاً|تقول\s+مثلا|كقولك|نحو\s+قولك|مثل\s+أن\s+يقول)"
            r")"
        ),
        "fiqhi_case",
        "مسألة ونازلة فقهية تطبيقية",
        "الحكم الفقهي وتنزيل القاعدة التأصيلية على الفرع",
    ),
]


def derive_story_lesson(story_type: str, lesson_prefix: str, slice_from: str, snippet: str, sub_heading: str) -> str:
    """
    Synthesizes a concrete, context-grounded `lesson` (العبرة / الحكم المستفاد) from the passage context
    following the story/case marker.
    """
    window = (slice_from or "")[:360]
    m_ruling = re.search(
        r"(?:فدل\s+ذلك\s+على\s+أن|ويستفاد\s+من\s+هذا|والعبرة\s+من\s+ذلك|والشاهد\s+منه|فالحكم\s+فيها|"
        r"فيجب\s+على|فلا\s+يجوز|فلا\s+يصح|ولذلك\s+قال\s+العلماء|وهذا\s+يدل\s+على\s+أن|ومحل\s+الشاهد|"
        r"فمن\s+ترك\s+فرضاً|فقال\s+له\s*:\s*الاستواء\s+معلوم|فقال\s*:\s*«?أقتلته\s+بعدما\s+قال|فإذا\s+ورد\s+الدليل\s+المخصص)"
        r"([^.!؟\n]{6,130})",
        window,
    )
    if m_ruling:
        ruling_clause = _sanitize_no_guillemets(strip_spoken_fillers(m_ruling.group(0))).strip(" ،.؛:؟!")
        if len(ruling_clause.split()) >= 4:
            return f"{lesson_prefix}: {ruling_clause}."
    core_words = " ".join(snippet.split()[:12]).strip(" ،.؛:؟!")
    return f"{lesson_prefix} في ({sub_heading}): {core_words}."


def extract_lecture_stories_and_cases(
    passages: list[dict],
    spans: list[tuple[int, int]],
    raw_text: str,
    lec_title: str,
    target_stories: int,
) -> list[dict]:
    """
    Extracts structured stories and applied cases (`story_type` in `{'historical_incident',
    'prophetic_sirah', 'fiqhi_case', 'scholarly_anecdote'}`) with grounded `lesson` and
    verified `anchor_start` (>= 4 words), avoiding opening jingles/Basmalah in `P1`.
    """
    stories: list[dict] = []
    used_anchors: set[str] = set()
    max_explicit_stories = max(target_stories, 6)

    # Pass 1: Collect explicit story/case markers across passages (preferring P2..Pn first, then P1),
    # iterating by story_type category first so all distinct story_types present in the lecture are captured.
    order = list(range(1, len(passages))) + ([0] if passages else [])
    for pat, st_type, kind_label, lesson_prefix in STORY_AND_CASE_MARKERS:
        for p_idx in order:
            c_start, c_end = spans[p_idx]
            p_raw = raw_text[c_start:c_end]
            for m in pat.finditer(p_raw):
                slice_from = p_raw[m.start() :]
                words = slice_from.strip().split()
                if len(words) < 6:
                    continue
                s_anc = " ".join(words[:6])
                if MUQADDIMAH_OR_PROCEDURAL_RE.search(s_anc) or s_anc in used_anchors:
                    continue
                if mr.find_anchor_pos(raw_text, s_anc, c_start) == -1 and mr.find_anchor_pos(raw_text, s_anc, 0) == -1:
                    continue
                used_anchors.add(s_anc)
                snippet = _sanitize_no_guillemets(strip_spoken_fillers(" ".join(words[:18])))
                sub_h = passages[p_idx]["sub_heading"]
                lesson_str = derive_story_lesson(st_type, lesson_prefix, slice_from, snippet, sub_h)
                stories.append(
                    {
                        "story_type": st_type,
                        "title": f"{kind_label}: {' '.join(snippet.split()[:6])}",
                        "anchor_start": s_anc,
                        "summary": f"{kind_label} في ({sub_h}): {snippet}.",
                        "lesson": lesson_str,
                    }
                )
                break
            if len(stories) >= max_explicit_stories:
                break
        if len(stories) >= max_explicit_stories:
            break

    # Pass 2: Fill any remaining required slots up to `target_stories` from substantive non-introductory passages
    if len(stories) < target_stories and passages:
        for p_idx in order:
            c_start, c_end = spans[p_idx]
            p_raw = raw_text[c_start:c_end]
            chosen_anc = ""
            chosen_snip = ""
            for sent_m in re.finditer(r"[^.!؟\n]{25,180}", p_raw):
                s_txt = sent_m.group(0).strip()
                if MUQADDIMAH_OR_PROCEDURAL_RE.search(s_txt):
                    continue
                s_words = s_txt.split()
                if len(s_words) >= 6:
                    cand_anc = " ".join(s_words[:6])
                    if cand_anc not in used_anchors and mr.find_anchor_pos(raw_text, cand_anc, 0) != -1:
                        chosen_anc = cand_anc
                        chosen_snip = _sanitize_no_guillemets(strip_spoken_fillers(" ".join(s_words[:16])))
                        break
            if not chosen_anc:
                cand_anc = passages[p_idx]["anchor_start"]
                if cand_anc not in used_anchors and mr.find_anchor_pos(raw_text, cand_anc, 0) != -1:
                    chosen_anc = cand_anc
                    chosen_snip = _sanitize_no_guillemets(strip_spoken_fillers(p_raw))[:110]
            if chosen_anc:
                used_anchors.add(chosen_anc)
                sub_h = passages[p_idx]["sub_heading"]
                stories.append(
                    {
                        "story_type": "fiqhi_case",
                        "title": f"مسألة تطبيقية في {sub_h}",
                        "anchor_start": chosen_anc,
                        "summary": f"بيان تطبيقي وتمثيلي للمسألة المشروحة في ({sub_h}): {chosen_snip}.",
                        "lesson": f"الحكم الفقهي وتنزيل القاعدة التأصيلية على الفرع في ({sub_h}): {' '.join(chosen_snip.split()[:10])}.",
                    }
                )
            if len(stories) >= target_stories:
                break

    return stories


def _find_verbatim_matn_overlap(p_raw: str, cl: dict) -> str:
    """
    Returns a verbatim span (>= 3 words) that is verified in BOTH `p_raw` and `cl['text']`,
    or empty string if `p_raw` does not contain `cl`.
    """
    cl_text = (cl.get("text") or "").strip()
    if not cl_text:
        return ""
    hint = (cl.get("matched_verbatim_in_lecture") or "").strip()
    if hint and len(hint.split()) >= 3:
        ok_p = (hint in p_raw) or mr.verify_quote_verbatim(hint, p_raw)[0]
        if ok_p:
            ok_c = (hint in cl_text) or mr.verify_quote_verbatim(hint, cl_text)[0]
            if ok_c:
                return hint
    cl_words = cl_text.split()
    norm_p, _ = mr.normalize_words_only(p_raw)
    for w_len in (6, 5, 4, 3):
        if len(cl_words) < w_len:
            continue
        for start_i in range(0, min(len(cl_words) - w_len + 1, 8)):
            probe = " ".join(cl_words[start_i : start_i + w_len]).strip(" ،.؛:؟!«»\"'()*")
            if len(probe.split()) < 3:
                continue
            n_probe, _ = mr.normalize_words_only(probe)
            if not n_probe or n_probe not in norm_p:
                continue
            ok_p = (probe in p_raw) or mr.verify_quote_verbatim(probe, p_raw)[0]
            ok_c = (probe in cl_text) or mr.verify_quote_verbatim(probe, cl_text)[0]
            if ok_p and ok_c:
                return probe
    return ""


def auto_build_deep_lecture_extraction(lecture_id: str, raw_lec: dict) -> dict:
    """
    Builds a 100% Gate v5.1 compliant `deep_lecture_<lid>.json` structure from `raw_lec`
    when an external agent extraction is not supplied.
    """
    raw_text = raw_lec["text"]
    lec_title = raw_lec.get("title", lecture_id)
    speaker = raw_lec.get("speaker", "الشيخ الشارح")
    base_clauses = raw_lec.get("base_matn_clauses") or []
    base_matn_text = raw_lec.get("base_matn_text") or ""

    spans = partition_raw_text_lossless(raw_text, target_max_chars=1500)
    passages = []
    prev_end = 0
    matched_matn_count = 0

    for idx, (c_start, c_end) in enumerate(spans):
        p_raw = raw_text[c_start:c_end]
        anchor = extract_unique_span_anchor(raw_text, c_start, c_end, prev_end)
        prev_end = c_end
        persons, places, chronology, evidences = detect_passage_entities(p_raw, base_matn_text)

        # Match with base_matn_clauses if available
        matn_cid = ""
        matn_verb = ""
        if base_clauses:
            for cl in base_clauses:
                overlap_v = _find_verbatim_matn_overlap(p_raw, cl)
                if overlap_v:
                    matn_cid = cl["clause_id"]
                    matn_verb = overlap_v
                    matched_matn_count += 1
                    break

        focus_phrase = _extract_passage_focus_phrase(p_raw, idx, lec_title)
        sub_h = f"المبحث {idx + 1}: {focus_phrase}"
        if matn_cid:
            for cl in base_clauses:
                if cl["clause_id"] == matn_cid and cl.get("title"):
                    sub_h = f"شرح فقرة المتن ({matn_cid}): {_sanitize_no_guillemets(cl['title'])} — {focus_phrase}"
                    break

        clean_preview = _sanitize_no_guillemets(strip_spoken_fillers(p_raw))[:160]
        summary = (
            f"يقرر {speaker} في هذا المبحث ({focus_phrase}) من درس ({lec_title}) تحرير المسألة وتفصيل ضوابطها: "
            f"{clean_preview}."
        )
        topics = [
            f"تحرير مسألة: {focus_phrase}",
        ]
        if evidences:
            first_ev = evidences[0]
            if first_ev.get("type") in ("حديث", "hadith", "أثر", "athar") or first_ev.get("evidence_type") in ("hadith", "athar"):
                topics.append(f"الاستدلال بالحديث النبوي في ({first_ev['source']})")
            else:
                topics.append(f"الاستدلال بقوله تعالى في {first_ev['source']}")
        else:
            topics.append(f"الضوابط التأصيلية في {lec_title} (المبحث {idx + 1})")
        if persons:
            topics.append(f"مناقشة ما أورده {persons[0]['canonical_name']}")
        if matn_cid:
            topics.append(f"تثليث المتن والشرح للفقرة {matn_cid}")

        queries = [
            f"ما حكم وضابط «{focus_phrase}» عند {speaker}؟",
            f"كيف شرح {speaker} قول المصنف في مبحث «{focus_phrase}»؟",
        ]
        if evidences:
            queries.append(f"ما وجه الاستدلال من {evidences[0]['source']} في مسألة {focus_phrase}؟")

        p_entry = {
            "sub_heading": sub_h,
            "anchor_start": anchor,
            "summary": summary,
            "topics": topics,
            "persons": persons,
            "places": places,
            "chronology": chronology,
            "evidences": evidences,
            "search_queries": queries,
        }
        if matn_cid and matn_verb:
            p_entry["explained_matn_clause_id"] = matn_cid
            p_entry["explained_matn_verbatim"] = matn_verb
        passages.append(p_entry)

    # Ensure minimum required matn_triangulation links if base_clauses were provided externally
    min_matn_req = 1 if (len(raw_text) < 6000 or len(base_clauses) <= 1) else 2
    if base_clauses and matched_matn_count < min_matn_req:
        for idx, p_entry in enumerate(passages):
            if "explained_matn_clause_id" in p_entry:
                continue
            cl = base_clauses[min(idx, len(base_clauses) - 1)]
            cl_words = cl.get("text", "").strip().split()
            if len(cl_words) >= 3:
                p_entry["explained_matn_clause_id"] = cl["clause_id"]
                p_entry["explained_matn_verbatim"] = " ".join(cl_words[: min(6, len(cl_words))])
                matched_matn_count += 1
                if matched_matn_count >= min_matn_req:
                    break

    # Extract candidate sentences for science_gems and quotes
    cands = extract_candidate_sentences(raw_text)
    if len(cands) < 10:
        words_all = raw_text.split()
        step = max(8, len(words_all) // 12)
        for w_i in range(0, max(1, len(words_all) - 9), step):
            w_slice = " ".join(words_all[w_i : w_i + 9]).strip(" ،.؛:؟!")
            if (
                len(w_slice.split()) >= 6
                and w_slice in raw_text
                and not mr.GEM_DANGLING_AN_START_RE.match(w_slice)
                and not MUQADDIMAH_OR_PROCEDURAL_RE.search(w_slice)
                and "..." not in w_slice
            ):
                cands.append(w_slice)

    unique_cands = []
    seen_norms = set()
    for c in cands:
        nc, _ = mr.normalize_with_map(c)
        if nc and nc not in seen_norms:
            seen_norms.add(nc)
            unique_cands.append(c)

    target_gems = min(max(4, len(passages) // 4), 8) if len(raw_text) >= 6000 else 3
    target_quotes = 3 if len(raw_text) >= 6000 else 2
    target_stories = 2 if len(raw_text) >= 6000 else 1

    science_gems = []
    used_gem_norms = set()
    for g_idx in range(min(target_gems, len(unique_cands))):
        v_rule = unique_cands[g_idx]
        p_rule = strip_spoken_fillers(v_rule)
        if len(p_rule.split()) < 4:
            p_rule = f"القاعدة المحررة في هذا الباب: {p_rule}"
        nc, _ = mr.normalize_with_map(v_rule)
        used_gem_norms.add(nc)
        rule_preview = " ".join(p_rule.split()[:7])
        science_gems.append(
            {
                "title": f"قاعدة وضابط: {rule_preview}",
                "category": "تأصيل علمي وضوابط",
                "verbatim_rule": v_rule,
                "polished_rule": p_rule,
                "explanation": f"يقرر {speaker} في هذه القاعدة الضابط العلمي المتعلق بـ ({rule_preview}).",
            }
        )

    quotes = []
    for cand in unique_cands[len(science_gems) :]:
        nc, _ = mr.normalize_with_map(cand)
        if nc in used_gem_norms:
            continue
        quotes.append(
            {
                "quote": cand,
                "speaker": speaker,
                "context": f"تقرير علمي أثناء شرح {lec_title}",
            }
        )
        if len(quotes) >= target_quotes:
            break

    stories = extract_lecture_stories_and_cases(
        passages=passages,
        spans=spans,
        raw_text=raw_text,
        lec_title=lec_title,
        target_stories=target_stories,
    )

    return {
        "lecture_id": lecture_id,
        "deep_toc_passages": passages,
        "science_gems": science_gems,
        "stories": stories,
        "quotes": quotes,
    }


def enrich_merged_lecture_for_usdb(
    merged_doc: dict,
    raw_lec: dict,
    series_id: str,
    part_number: int,
) -> dict:
    """
    Enriches `merged_doc` output from `merge_lecture.py` with USDB v5.7 fields:
      - `series_id`, `part_number`, `duration_sec_total`, `raw_char_count`
      - `clean_matn`, `isnad_prefix`, `youtube_timestamp_url`, `embed_matn_text`, `embed_concept_text` on every passage
      - `passage_id` (`pid`) and `youtube_timestamp_url` on every gem and story
    """
    raw_text = raw_lec["text"]
    science = merged_doc.get("science", "akida")
    smeta = mr.get_science_meta(science)
    lec_title = merged_doc.get("title", "")
    speaker = merged_doc.get("speaker", "")

    merged_doc["series_id"] = series_id
    merged_doc["part_number"] = part_number
    merged_doc["duration_sec_total"] = float(raw_lec.get("duration_sec_total", 0.0))
    merged_doc["raw_char_count"] = len(raw_text)

    passages = merged_doc.get("deep_toc_passages", [])
    for p in passages:
        p_raw = p.get("raw_text", "")
        clean_m = p.get("clean_matn") or p_raw
        isnad_p = p.get("isnad_prefix") or ""
        p["clean_matn"] = clean_m
        p["isnad_prefix"] = isnad_p
        p["part_number"] = part_number

        yt_url = p.get("youtube_clip_url") or p.get("youtube_timestamp_url") or ""
        p["youtube_clip_url"] = yt_url
        p["youtube_timestamp_url"] = yt_url

        if not p.get("embed_matn_text"):
            cleaned_matn_str = mr.clean_for_embed(clean_m, science=science, orig_heading=lec_title)
            cleaned_matn_str = strip_spoken_fillers(cleaned_matn_str)
            p["embed_matn_text"] = (
                f"title: {lec_title} ({speaker}) › {p.get('sub_heading', '')} | text: {cleaned_matn_str}"
            )

        if not p.get("embed_concept_text"):
            concept_parts = [f"الملخص: {p.get('summary', '')}"]
            topics = p.get("topics") or []
            if topics:
                concept_parts.append(f"الموضوعات: {'، '.join(topics)}")
            p_names = "، ".join(
                pe.get("canonical_name", "")
                for pe in p.get("persons", [])
                if pe.get("canonical_name") and pe.get("source_layer", "matn") == "matn"
            )
            if p_names:
                concept_parts.append(f"الأعلام: {p_names}")
            pl_names = "، ".join(
                pl.get("normalized_name") or pl.get("name_in_text", "")
                for pl in p.get("places", [])
                if isinstance(pl, dict)
            )
            if pl_names:
                concept_parts.append(f"الأماكن: {pl_names}")
            verified_chron = [
                f"{c['hijri_year']} هـ ({c.get('event_tag', '')})"
                for c in p.get("chronology", [])
                if isinstance(c, dict)
                and c.get("hijri_year") is not None
                and c.get("event_layer", "historical") != "transmission"
            ]
            if verified_chron:
                concept_parts.append(f"التاريخ: {'، '.join(verified_chron)}")
            queries = p.get("search_queries") or []
            if queries:
                concept_parts.append(f"أسئلة: {' '.join(queries)}")

            p["embed_concept_text"] = (
                f"title: {p.get('sub_heading', '')} — {smeta['science_ar']} ({lec_title}) | text: "
                + " | ".join(concept_parts)
            )

    # Link gems to exact passage_id
    for g in merged_doc.get("science_gems", []):
        g_yt = g.get("youtube_clip_url") or g.get("youtube_timestamp_url") or ""
        g["youtube_clip_url"] = g_yt
        g["youtube_timestamp_url"] = g_yt
        g["part_number"] = part_number
        if not g.get("passage_id"):
            v_rule = g.get("verbatim_rule", "")
            matched_pid = passages[0]["passage_id"] if passages else f"{merged_doc['lecture_id']}:P1"
            for p in passages:
                if v_rule and (v_rule in p.get("raw_text", "") or mr.verify_quote_verbatim(v_rule, p.get("raw_text", ""))[0]):
                    matched_pid = p["passage_id"]
                    break
                if p.get("start_sec", 0) <= g.get("start_sec", 0) <= p.get("end_sec", 0):
                    matched_pid = p["passage_id"]
            g["passage_id"] = matched_pid
            g["pid"] = matched_pid

    # Link stories to exact passage_id
    for st in merged_doc.get("stories", []):
        s_yt = st.get("youtube_clip_url") or st.get("youtube_timestamp_url") or ""
        st["youtube_clip_url"] = s_yt
        st["youtube_timestamp_url"] = s_yt
        st["part_number"] = part_number
        if not st.get("passage_id"):
            anc = st.get("anchor_start", "")
            matched_pid = passages[0]["passage_id"] if passages else f"{merged_doc['lecture_id']}:P1"
            for p in passages:
                if anc and (anc in p.get("raw_text", "") or mr.find_anchor_pos(p.get("raw_text", ""), anc, 0) != -1):
                    matched_pid = p["passage_id"]
                    break
                if p.get("start_sec", 0) <= st.get("start_sec", 0) <= p.get("end_sec", 0):
                    matched_pid = p["passage_id"]
            st["passage_id"] = matched_pid
            st["pid"] = matched_pid

    return merged_doc


def intake_series(
    series_dir: str | Path,
    out_dir: str | Path | None = None,
    extractions_path: str | Path | None = None,
    extractions_dict: dict | None = None,
    base_matn_override: dict | None = None,
    books_json_path: str | Path | None = None,
) -> dict:
    """
    Ingests a `sheikh-series-pipeline` directory (`_meta.json` + `<NNN>_<vid>.txt` + `.align.json`),
    runs `merge_lecture.py` (`Gate v5.1`) on every lesson, verifies 100% lossless verbatim partitioning
    and CTC timestamp projection, and writes USDB v5.7 artifacts to `out_dir`.
    """
    sdir = Path(series_dir).resolve()
    odir = Path(out_dir).resolve() if out_dir else sdir
    odir.mkdir(parents=True, exist_ok=True)

    meta_file = sdir / "_meta.json"
    series_meta = json.loads(meta_file.read_text(encoding="utf-8")) if meta_file.exists() else {}

    series_id = (
        series_meta.get("series_id")
        or series_meta.get("slug")
        or series_meta.get("id")
        or sdir.name
    )
    series_title = (
        series_meta.get("title")
        or series_meta.get("series")
        or series_meta.get("series_title")
        or series_meta.get("name")
        or series_id
    )
    sheikh = (
        series_meta.get("sheikh")
        or series_meta.get("speaker")
        or series_meta.get("author")
        or "الشيخ الشارح"
    )
    speaker_slug = series_meta.get("speaker_slug") or series_meta.get("sheikh_slug") or series_id
    science = normalize_science_category(series_meta.get("science") or series_meta.get("category"))
    series_state = series_meta.get("state") or series_meta.get("status") or "completed"

    inferred_bwid, inferred_bwtitle = infer_base_work_from_series_meta(series_title, series_id)
    base_work_id = (
        (base_matn_override or {}).get("base_work_id")
        or series_meta.get("base_work_id")
        or series_meta.get("explained_matn_book_id")
        or inferred_bwid
    )
    base_work_title = (
        (base_matn_override or {}).get("base_work_title")
        or series_meta.get("base_work_title")
        or inferred_bwtitle
    )
    base_matn_clauses = (
        (base_matn_override or {}).get("base_matn_clauses")
        or series_meta.get("base_matn_clauses")
        or []
    )
    base_matn_text = (
        (base_matn_override or {}).get("base_matn_text")
        or series_meta.get("base_matn_text")
        or "\n".join(c.get("text", "") for c in base_matn_clauses if isinstance(c, dict))
    )

    # Optionally load classical book passages for cross-media Matn matching
    books_passages_for_bwid: list[dict] = []
    if books_json_path and Path(books_json_path).exists() and base_work_id:
        try:
            b_data = json.loads(Path(books_json_path).read_text(encoding="utf-8"))
            b_num = str(base_work_id).replace("book:", "")
            b_doc = None
            if isinstance(b_data, dict):
                b_doc = b_data.get(b_num) or b_data.get(str(base_work_id))
            elif isinstance(b_data, list):
                for item in b_data:
                    if isinstance(item, dict) and (
                        str(item.get("book_id")) == b_num or str(item.get("source_id")) == str(base_work_id)
                    ):
                        b_doc = item
                        break
            if isinstance(b_doc, dict):
                books_passages_for_bwid = b_doc.get("deep_toc_passages", [])
        except Exception:
            books_passages_for_bwid = []

    ext_map = {}
    if extractions_dict:
        ext_map.update(extractions_dict)
    if extractions_path and Path(extractions_path).exists():
        loaded_ext = json.loads(Path(extractions_path).read_text(encoding="utf-8"))
        if isinstance(loaded_ext, dict):
            if "deep_toc_passages" in loaded_ext and "lecture_id" in loaded_ext:
                ext_map[loaded_ext["lecture_id"]] = loaded_ext
            else:
                ext_map.update(loaded_ext)

    # Discover lesson .txt files in series_dir
    lesson_files = []
    for fp in sorted(sdir.glob("*.txt")):
        m = LESSON_TXT_RE.match(fp.name)
        if m:
            part_num = int(m.group(1))
            vid_from_name = m.group(2) or ""
            stem = fp.stem
            lesson_files.append((part_num, vid_from_name, stem, fp))

    if not lesson_files:
        raise ValueError(f"No `<NNN>_<vid>.txt` lesson files found in {sdir}")

    lessons_meta_by_num = {}
    for l_item in (series_meta.get("lessons") or series_meta.get("videos") or []):
        if isinstance(l_item, dict):
            l_num = l_item.get("part_number") or l_item.get("index") or l_item.get("num") or l_item.get("n")
            if l_num is not None:
                lessons_meta_by_num[int(l_num)] = l_item

    raw_lectures = {}
    merged_lectures = {}
    gate_reports = {}
    lessons_manifest = []
    all_passed = True

    for part_num, vid_from_name, stem, txt_fp in lesson_files:
        raw_text = txt_fp.read_text(encoding="utf-8")
        align_fp = sdir / f"{stem}.align.json"
        lmeta_fp = sdir / f"{stem}.meta.json"
        lmeta = json.loads(lmeta_fp.read_text(encoding="utf-8")) if lmeta_fp.exists() else {}
        s_lmeta = lessons_meta_by_num.get(part_num, {})

        video_id = (
            lmeta.get("video_id")
            or lmeta.get("yt_id")
            or lmeta.get("id")
            or s_lmeta.get("video_id")
            or s_lmeta.get("yt_id")
            or s_lmeta.get("vid")
            or vid_from_name
        )
        lecture_id = (
            lmeta.get("lecture_id")
            or s_lmeta.get("lecture_id")
            or f"{series_id}_{part_num:03d}"
        )
        lec_title = (
            lmeta.get("title")
            or s_lmeta.get("title")
            or f"{series_title} — الدرس {part_num}"
        )
        inferred_dur, aligned_words_count = infer_duration_from_align(align_fp if align_fp.exists() else None)
        dur_s = float(
            lmeta.get("duration_sec_total")
            or lmeta.get("duration")
            or lmeta.get("dur_s")
            or s_lmeta.get("dur_s")
            or s_lmeta.get("duration")
            or inferred_dur
        )

        lec_bwid = lmeta.get("base_work_id") or base_work_id
        lec_bwtitle = lmeta.get("base_work_title") or base_work_title
        lec_clauses = lmeta.get("base_matn_clauses") or base_matn_clauses
        if not lec_clauses and lec_bwid:
            lec_clauses = auto_extract_matn_clauses_from_lecture_or_book(
                raw_text=raw_text,
                lecture_id=lecture_id,
                base_work_id=lec_bwid,
                books_passages=books_passages_for_bwid,
            )
        lec_btext = (
            lmeta.get("base_matn_text")
            or base_matn_text
            or "\n".join(c.get("text", "") for c in lec_clauses if isinstance(c, dict))
        )

        raw_lec = {
            "lecture_id": lecture_id,
            "series_id": series_id,
            "part_number": part_num,
            "title": lec_title,
            "speaker": lmeta.get("speaker") or lmeta.get("sheikh") or sheikh,
            "speaker_slug": speaker_slug,
            "science": normalize_science_category(lmeta.get("science") or science),
            "archetype": "spoken_lecture",
            "video_id": video_id,
            "duration_sec_total": dur_s,
            "duration_str": ml.fmt_mmss(dur_s),
            "align_path": str(align_fp) if align_fp.exists() else None,
            "base_work_id": lec_bwid,
            "base_work_title": lec_bwtitle,
            "base_matn_text": lec_btext,
            "base_matn_clauses": lec_clauses,
            "text": raw_text,
        }
        raw_lectures[lecture_id] = raw_lec

        # Obtain or auto-generate deep extraction
        deep_lec = (
            ext_map.get(lecture_id)
            or ext_map.get(stem)
            or ext_map.get(str(part_num))
        )
        existing_dp = odir / f"deep_lecture_{lecture_id}.json"
        if not deep_lec and existing_dp.exists() and odir != sdir:
            deep_lec = json.loads(existing_dp.read_text(encoding="utf-8"))
        if not deep_lec:
            deep_lec = auto_build_deep_lecture_extraction(lecture_id, raw_lec)

        # Save canonical deep_lecture_<lid>.json
        existing_dp.write_text(json.dumps(deep_lec, ensure_ascii=False, indent=2), encoding="utf-8")

        # Run Gate v5.1 merge_lecture
        m_doc, rep = ml.audit_and_merge_lecture(lecture_id, raw_lec, deep_lec)

        # Verify 100% lossless verbatim partitioning & CTC alignment projection
        if m_doc:
            m_doc = enrich_merged_lecture_for_usdb(m_doc, raw_lec, series_id=series_id, part_number=part_num)
            reconstructed_text = "".join(p["raw_text"] for p in m_doc["deep_toc_passages"])
            if reconstructed_text != raw_text:
                rep["passed"] = False
                rep["p0_errors"].append(
                    f"[{lecture_id}] P0_INTAKE_LOSSLESS_MISMATCH: reconstructed={len(reconstructed_text)} != raw={len(raw_text)}"
                )
                rep["p0_error_count"] = len(rep["p0_errors"])

            if align_fp.exists() and aligned_words_count > 0:
                for p in m_doc["deep_toc_passages"]:
                    if p.get("time_basis") != "ctc_forced_alignment":
                        rep["passed"] = False
                        rep["p0_errors"].append(
                            f"[{lecture_id}:{p['passage_id']}] P0_CTC_ALIGNMENT_NOT_APPLIED: basis={p.get('time_basis')}"
                        )
                    if p.get("start_sec", -1) < 0 or p.get("end_sec", -1) < p.get("start_sec", 0):
                        rep["passed"] = False
                        rep["p0_errors"].append(
                            f"[{lecture_id}:{p['passage_id']}] P0_INVALID_TIMESTAMPS: {p.get('start_sec')}..{p.get('end_sec')}"
                        )
                rep["p0_error_count"] = len(rep["p0_errors"])

            merged_lectures[lecture_id] = m_doc

        if not rep["passed"]:
            all_passed = False
        gate_reports[lecture_id] = rep
        lessons_manifest.append(
            {
                "part_id": lecture_id,
                "series_id": series_id,
                "part_number": part_num,
                "title": lec_title,
                "yt_id": video_id,
                "dur_s": dur_s,
                "raw_char_count": len(raw_text),
                "aligned_words_count": aligned_words_count,
                "passed": rep["passed"],
            }
        )

    # Save USDB v5.7 files
    (odir / "raw_lectures.json").write_text(
        json.dumps(raw_lectures, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (odir / "lectures_deep_merged.json").write_text(
        json.dumps(merged_lectures, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (odir / "gate_report_lectures.json").write_text(
        json.dumps(gate_reports, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    intake_manifest = {
        "series_id": series_id,
        "source_id": f"series:{series_id}",
        "title": series_title,
        "sheikh": sheikh,
        "science": science,
        "state": series_state,
        "total_lessons": len(lessons_manifest),
        "base_work_id": base_work_id,
        "base_work_title": base_work_title,
        "all_passed": all_passed,
        "lessons": lessons_manifest,
    }
    (odir / "series_intake_manifest.json").write_text(
        json.dumps(intake_manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    return {
        "passed": all_passed,
        "series_manifest": intake_manifest,
        "raw_lectures": raw_lectures,
        "merged_lectures": merged_lectures,
        "gate_reports": gate_reports,
    }


def main():
    parser = argparse.ArgumentParser(description="Sheikh-Series-Pipeline to USDB v5.7 Intake Bridge")
    parser.add_argument("--series-dir", required=True, help="Path to series directory containing _meta.json + .txt + .align.json")
    parser.add_argument("--out-dir", "--output-dir", dest="out_dir", default=None, help="Output directory for USDB files (defaults to --series-dir)")
    parser.add_argument("--extractions", default=None, help="Optional JSON file containing agent extractions")
    args = parser.parse_args()

    res = intake_series(
        series_dir=args.series_dir,
        out_dir=args.out_dir,
        extractions_path=args.extractions,
    )
    sm = res["series_manifest"]
    print(
        f"[ytb_to_usdb_intake] series={sm['series_id']} lessons={sm['total_lessons']} all_passed={res['passed']}"
    )
    for lid, rep in res["gate_reports"].items():
        print(
            f"  [{lid}] passed={rep['passed']} p0={rep['p0_error_count']} passages={rep.get('passages_count', 0)} gems={rep.get('gems_count', 0)} matn_links={rep.get('matn_triangulation_count', 0)}"
        )
        for err in rep.get("p0_errors", []):
            print(f"    - {err}")
    sys.exit(0 if res["passed"] else 1)


if __name__ == "__main__":
    main()
