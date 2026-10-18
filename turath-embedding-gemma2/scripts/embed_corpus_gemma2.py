#!/usr/bin/env python3
"""
 محرك التضمين الشعاعي المزدوج بـ EmbeddingGemma 2 (Dual-Vector Representation Engine)
لمنظومة التراث الفقهي والمعرفي (turath-embedding-gemma2).

يوفر:
1. دوال التطهير والتجهيز المزدوج:
   - prepare_embed_matn_text(passage, ...)
   - prepare_embed_concept_text(passage, gems, ...)
   مع تفكيك محارف الترضية المدمجة (\ufd40..\ufd4f و \ufdfa..\ufdff)، وإزالة علامات الصفحات
   ([ص: N]، صفحة N، ⦗N⦘، (¬N))، وعزل رواة الإسناد (source_layer='isnad') وتواريخ النسخ.
2. محولات التضمين المتعددة (auto | ollama | sentence-transformers | genai | deterministic-arabic-mps):
   - بما فيها المحرك الحتمي المسرّع على Apple Silicon MPS / NumPy (DeterministicArabicGemma2Embedder)
     ببعد dim=768 وتطبيع L2-Norm صارم (||v||_2 == 1.0 ± 1e-5).
3. بناء وتعبئة جداول المتجهات في SQLite:
   - passage_embeddings
   - gem_embeddings
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

try:
    import torch
    HAS_TORCH = True
except ImportError:
    torch = None  # type: ignore
    HAS_TORCH = False


# ---------------------------------------------------------------------------
# 1. الثوابت والتعابير النمطية لتطهير النصوص (Dual Text Hygiene Constants)
# ---------------------------------------------------------------------------

HONORIFIC_LIGATURE_MAP: Dict[str, str] = {
    "\ufd40": " رحمه الله ",
    "\ufd41": " رضي الله عنه ",
    "\ufd42": " رضي الله عنها ",
    "\ufd43": " رضي الله عنهم ",
    "\ufd44": " رضي الله عنهما ",
    "\ufd45": " رضي الله عنهن ",
    "\ufd46": " صلى الله عليه وآله ",
    "\ufd47": " عليه السلام ",
    "\ufd48": " عليهم السلام ",
    "\ufd49": " عليهما السلام ",
    "\ufd4a": " عليه الصلاة والسلام ",
    "\ufd4b": " قدس سره ",
    "\ufd4c": " صلى الله عليه وآله وسلم ",
    "\ufd4d": " عليها السلام ",
    "\ufd4e": " تبارك وتعالى ",
    "\ufd4f": " رحمهم الله ",
    "\ufdfa": " صلى الله عليه وسلم ",
    "\ufdfb": " جل جلاله ",
    "\ufdfc": " ريال ",
    "\ufdfd": " بسم الله الرحمن الرحيم ",
    "\ufdfe": " سبحانه وتعالى ",
    "\ufdff": " عز وجل ",
}

HONORIFIC_RANGE_RE = re.compile(r"[\ufd40-\ufd4f\ufdfa-\ufdff]")
TASHKEEL_RE = re.compile(r"[\u0617-\u061A\u064B-\u065F\u0670\u06D6-\u06ED]")
DIGITS_MAP = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")

# علامات الصفحات والأوراق والحواشي الطباعية
PAGE_BRACKET_RE = re.compile(
    r"\[\s*(?:ص|صفحة|صـ)\s*:?\s*[٠-٩0-9]{1,5}(?:\s*[-–/]\s*[٠-٩0-9]{1,5})?\s*\]"
    r"|\(\s*(?:ص|صفحة|صـ)\s*:?\s*[٠-٩0-9]{1,5}\s*\)"
    r"|\bصفحة\s+[٠-٩0-9]{1,5}\b"
    r"|\bص\s*:\s*[٠-٩0-9]{1,5}\b"
)
EDITION_PAGE_RE = re.compile(r"⦗[^⦘\n]{1,25}⦘")
FOLIO_MARKER_RE = re.compile(
    r"\[\s*[٠-٩0-9]{1,4}\s*[أابوظو]\s*\]"
    r"|(?:/\s*)?\((?=[^()\n]{1,16}\))(?=[^)]*[أابظوزدمه])\s*[٠-٩0-9]{1,4}\s*/?\s*[أابظو]?\u064e?\s*(?:/\s*[أابظوزدمه]\u064e?\s*){0,2}\)"
)
FOOTNOTE_NEG_RE = re.compile(r"\(\s*¬\s*[٠-٩0-9]+\s*\)")
FOOTNOTE_PAREN_NUM_RE = re.compile(r"\(\s*[٠-٩0-9]{1,3}\s*\)")
GLUED_BARE_FN_RE = re.compile(r"(?<=[\u0621-\u064A﴾»\"'\)\]])[٠-٩0-9]{1,2}(?![٠-٩0-9/\-–])")
SPOKEN_FILLER_RE = re.compile(
    r"\b(?:يعني|طيب|يا إخوة|يا اخوة|تمام\s*؟?|ماشي\s*؟?|صح\s*؟?|خلي بالك|واضح\s*؟?)\b"
)

LEADING_ISNAD_CHAIN_RE = re.compile(
    r"^\s*(?:(?:\[ح\]|\(ح\)|ح)\s+)?(?:و?(?:حدثنا|حدثني|أخبرنا|أخبرني|أنبأنا|أنبأني|ثنا|نا|سمعت|روينا|روي لنا|وبه حدثنا|وبه ثنا)\b[^:。\n]{5,260}?(?:قال|قالت|يقول|أنه قال|أنها قالت)\s*:\s*)+"
)

ARABIC_STOPWORDS = {
    "في", "من", "على", "عن", "إلى", "الى", "مع", "هذا", "هذه", "ذلك", "تلك",
    "الذي", "التي", "الذين", "ما", "هل", "كيف", "ماذا", "متى", "أين", "اين",
    "هو", "هي", "هم", "كان", "كانت", "يكون", "أن", "ان", "إن", "ان", "ثم",
    "أو", "او", "لا", "لم", "لن", "قد", "كل", "بعض", "غير", "بين", "عند",
    "به", "بها", "فيه", "فيها", "منه", "منها", "عنه", "عنها", "له", "لها",
}


# ---------------------------------------------------------------------------
# 2. دوال التطهير والتجهيز المزدوج (prepare_embed_matn_text / prepare_embed_concept_text)
# ---------------------------------------------------------------------------

def expand_honorific_ligatures(text: str) -> str:
    """يفكك جميع محارف الترضية والترحم المدمجة (\ufd40..\ufd4f و \ufdfa..\ufdff) إلى كلمات عربية."""
    if not text:
        return ""
    s = text
    for lig, replacement in HONORIFIC_LIGATURE_MAP.items():
        if lig in s:
            s = s.replace(lig, replacement)
    # ضمان عدم بقاء أي محرف غير مغطى في النطاق
    s = HONORIFIC_RANGE_RE.sub(" ", s)
    return s


def normalize_arabic_for_match(text: str) -> str:
    """تطبيع عربي خفيف للمقارنة والبحث وتجريد السوابق."""
    if not text:
        return ""
    s = expand_honorific_ligatures(text)
    s = TASHKEEL_RE.sub("", s)
    s = s.replace("\u0640", "")
    s = re.sub(r"[أإآٱ]", "ا", s)
    s = s.replace("ة", "ه").replace("ى", "ي").replace("ؤ", "و").replace("ئ", "ي")
    s = s.translate(DIGITS_MAP)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def clean_hygienic_arabic_text(
    text: str,
    strip_leading_isnad: bool = False,
    strip_spoken_fillers: bool = False,
    forbidden_phrases: Optional[Sequence[str]] = None,
) -> str:
    """
    يطبق قواعد النظافة النصية الصارمة (Gate 1 Hygiene):
    1. تفكيك محارف \ufd40..\ufd4f و \ufdfa..\ufdff.
    2. إزالة علامات الصفحات [ص: N]، صفحة N، ⦗N⦘، وأوراق المخطوطات، وحواشي (¬N).
    3. عزل سلاسل الإسناد الابتدائي والعبارات المحظورة (مثل رواة السند في نص المفهوم).
    """
    if not text:
        return ""
    s = expand_honorific_ligatures(text)
    s = TASHKEEL_RE.sub("", s)
    s = s.replace("\u0640", "")
    s = s.replace("﷽", " ")

    # إزالة علامات الصفحات والأوراق والحواشي
    s = PAGE_BRACKET_RE.sub(" ", s)
    s = EDITION_PAGE_RE.sub(" ", s)
    s = FOLIO_MARKER_RE.sub(" ", s)
    s = FOOTNOTE_NEG_RE.sub(" ", s)
    s = FOOTNOTE_PAREN_NUM_RE.sub(" ", s)
    s = GLUED_BARE_FN_RE.sub("", s)
    s = re.sub(r"\[[^\]]*(?:الآية|آية|سورة|ص\s*:|صفحة)[^\]]*\]", " ", s)
    s = s.replace("صفحة فارغة في الأصل", " ")

    if strip_leading_isnad:
        s = LEADING_ISNAD_CHAIN_RE.sub("", s)

    if strip_spoken_fillers:
        s = SPOKEN_FILLER_RE.sub(" ", s)

    if forbidden_phrases:
        for phrase in forbidden_phrases:
            p_clean = expand_honorific_ligatures(phrase).strip()
            p_clean = TASHKEEL_RE.sub("", p_clean)
            if p_clean and len(p_clean) >= 3:
                s = re.sub(re.escape(p_clean), " ", s)

    # تنظيف الأقواس الفارغة والفواصل المكررة
    s = re.sub(r"\[\s*\]|\(\s*\)", " ", s)
    s = re.sub(r"\s+([،.؛:؟!])", r"\1", s)
    s = re.sub(r"[،\s]{2,}", lambda m: "، " if "،" in m.group(0) else " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _parse_json_list(val: Any) -> List[Any]:
    if val is None:
        return []
    if isinstance(val, list):
        return val
    if isinstance(val, str):
        val_s = val.strip()
        if not val_s:
            return []
        try:
            parsed = json.loads(val_s)
            if isinstance(parsed, list):
                return parsed
        except Exception:
            return [x.strip() for x in re.split(r"[،,|]", val_s) if x.strip()]
    return []


def prepare_embed_matn_text(
    passage: Dict[str, Any],
    source_meta: Optional[Dict[str, Any]] = None,
    isnad_persons: Optional[Sequence[Dict[str, Any]]] = None,
) -> str:
    """
    يبني ويطهر حقل embed_matn_text للمقطع:
    - يعتمد على clean_matn (أو raw_text بعد طرح isnad_prefix وسلسلة السند الابتدائية).
    - يضمن خلو النص تماماً من محارف \ufd40..\ufd4f، وعلامات الصفحات [ص: N]، ورواة الإسناد.
    - يصوغ النص ببادئة المهمة القياسية في EmbeddingGemma 2:
      task: search result | title: {source_title} | text: {clean_matn}
    """
    source_meta = source_meta or {}
    clean_matn = (passage.get("clean_matn") or "").strip()
    raw_text = (passage.get("raw_text") or "").strip()
    isnad_prefix = (passage.get("isnad_prefix") or "").strip()

    if not clean_matn and raw_text:
        if isnad_prefix and raw_text.startswith(isnad_prefix):
            clean_matn = raw_text[len(isnad_prefix):].strip()
        else:
            clean_matn = raw_text

    if not clean_matn:
        existing = (passage.get("embed_matn_text") or "").strip()
        if "| text:" in existing:
            clean_matn = existing.split("| text:", 1)[1].strip()
        else:
            clean_matn = existing

    # جمع أسماء رواة السند الخالصين لعزلهم من المتن إن تسربوا
    forbidden_isnad_names: List[str] = []
    if isnad_prefix:
        forbidden_isnad_names.append(isnad_prefix)
    persons_in_passage = list(isnad_persons or []) + _parse_json_list(passage.get("persons"))
    for pe in persons_in_passage:
        if isinstance(pe, dict) and pe.get("source_layer") == "isnad":
            for k in ("mentioned_name", "mentioned_in_text", "canonical_name"):
                nm = (pe.get(k) or "").strip()
                if nm:
                    forbidden_isnad_names.append(nm)

    hygienic_matn = clean_hygienic_arabic_text(
        clean_matn,
        strip_leading_isnad=True,
        strip_spoken_fillers=False,
        forbidden_phrases=forbidden_isnad_names,
    )

    src_title = (
        source_meta.get("title")
        or passage.get("source_title")
        or passage.get("book_title")
        or passage.get("source_id")
        or "مصدر تراثي"
    )
    src_title_clean = clean_hygienic_arabic_text(str(src_title))
    return f"task: search result | title: {src_title_clean} | text: {hygienic_matn}"


def prepare_embed_concept_text(
    passage: Dict[str, Any],
    gems: Optional[Sequence[Dict[str, Any]]] = None,
    persons: Optional[Sequence[Dict[str, Any]]] = None,
    places: Optional[Sequence[Dict[str, Any]]] = None,
    events: Optional[Sequence[Dict[str, Any]]] = None,
    source_meta: Optional[Dict[str, Any]] = None,
) -> str:
    """
    يبني ويطهر حقل embed_concept_text للمقطع:
    - يجمع بين: العنوان الفرعي (sub_heading) + الملخص (summary) + الموضوعات (topics)
      + القواعد المصقولة (polished_rule) + الأسئلة البحثية (search_queries)
      + أعلام المتن فقط (source_layer='matn') + الأماكن + التواريخ التاريخية (event_layer='historical').
    - يستبعد بصرامة جميع رواة الإسناد (source_layer='isnad') وتواريخ النسخ والسماع (event_layer='transmission').
    - يصوغ النص ببادئة المهمة القياسية في EmbeddingGemma 2:
      task: search result | title: {sub_heading} | text: ...
    """
    source_meta = source_meta or {}
    gems = list(gems or [])
    all_persons = list(persons or []) + _parse_json_list(passage.get("persons"))
    all_places = list(places or []) + _parse_json_list(passage.get("places"))
    all_events = list(events or []) + _parse_json_list(passage.get("chronology"))

    # تحديد رواة الإسناد المحظورين من الدخول في نص المفهوم
    isnad_only_names: List[str] = []
    matn_person_names: List[str] = []
    for pe in all_persons:
        if not isinstance(pe, dict):
            continue
        layer = (pe.get("source_layer") or "matn").strip().lower()
        c_name = (pe.get("canonical_name") or "").strip()
        m_name = (pe.get("mentioned_name") or pe.get("mentioned_in_text") or "").strip()
        if layer == "isnad":
            if c_name:
                isnad_only_names.append(c_name)
            if m_name:
                isnad_only_names.append(m_name)
        elif layer == "matn":
            chosen = c_name or m_name
            if chosen and chosen not in matn_person_names:
                matn_person_names.append(chosen)

    # إذا كان العلم مذكوراً في المتن أيضاً فلا نحذفه من المتن، أما إن كان في السند فقط فيُحظر تماماً
    matn_norm_set = {normalize_arabic_for_match(x) for x in matn_person_names}
    strict_forbidden_isnad = [
        nm for nm in isnad_only_names
        if normalize_arabic_for_match(nm) not in matn_norm_set
    ]

    sub_heading = clean_hygienic_arabic_text(
        passage.get("sub_heading") or "",
        strip_spoken_fillers=True,
        forbidden_phrases=strict_forbidden_isnad,
    )
    summary = clean_hygienic_arabic_text(
        passage.get("summary") or "",
        strip_spoken_fillers=True,
        forbidden_phrases=strict_forbidden_isnad,
    )

    raw_topics = _parse_json_list(passage.get("topics_json") or passage.get("topics"))
    topics_clean = [
        clean_hygienic_arabic_text(str(t), strip_spoken_fillers=True, forbidden_phrases=strict_forbidden_isnad)
        for t in raw_topics
        if str(t).strip()
    ]
    topics_clean = [t for t in topics_clean if t]

    polished_rules: List[str] = []
    for g in gems:
        if not isinstance(g, dict):
            continue
        pr = (g.get("polished_rule") or g.get("verbatim_rule") or "").strip()
        if pr:
            pr_clean = clean_hygienic_arabic_text(
                pr,
                strip_spoken_fillers=True,
                forbidden_phrases=strict_forbidden_isnad,
            )
            if pr_clean and pr_clean not in polished_rules:
                polished_rules.append(pr_clean)

    raw_queries = _parse_json_list(passage.get("search_queries_json") or passage.get("search_queries"))
    queries_clean = [
        clean_hygienic_arabic_text(str(q), strip_spoken_fillers=True, forbidden_phrases=strict_forbidden_isnad)
        for q in raw_queries
        if str(q).strip()
    ]
    queries_clean = [q for q in queries_clean if q]

    place_names: List[str] = []
    for pl in all_places:
        if isinstance(pl, dict):
            p_nm = (pl.get("canonical_name") or pl.get("normalized_name") or pl.get("mentioned_name") or "").strip()
            p_nm_clean = clean_hygienic_arabic_text(p_nm, forbidden_phrases=strict_forbidden_isnad)
            if p_nm_clean and p_nm_clean not in place_names:
                place_names.append(p_nm_clean)

    hist_events: List[str] = []
    for ev in all_events:
        if not isinstance(ev, dict):
            continue
        ev_layer = (ev.get("event_layer") or "historical").strip().lower()
        if ev_layer == "transmission":
            continue
        yr = ev.get("year_hijri") if ev.get("year_hijri") is not None else ev.get("hijri_year")
        ev_title = clean_hygienic_arabic_text(
            str(ev.get("event_title") or ev.get("event_tag") or ""),
            forbidden_phrases=strict_forbidden_isnad,
        )
        if yr is not None and ev_title:
            hist_events.append(f"{yr} هـ ({ev_title})")
        elif yr is not None:
            hist_events.append(f"{yr} هـ")
        elif ev_title:
            hist_events.append(ev_title)

    concept_segments: List[str] = []
    if sub_heading:
        concept_segments.append(f"العنوان: {sub_heading}")
    if summary:
        concept_segments.append(f"الملخص: {summary}")
    if topics_clean:
        concept_segments.append(f"الموضوعات: {'، '.join(topics_clean)}")
    if polished_rules:
        concept_segments.append(f"القواعد: {' | '.join(polished_rules)}")
    if queries_clean:
        concept_segments.append(f"أسئلة: {' | '.join(queries_clean)}")
    if matn_person_names:
        matn_persons_clean = [
            clean_hygienic_arabic_text(p, forbidden_phrases=strict_forbidden_isnad)
            for p in matn_person_names
        ]
        matn_persons_clean = [p for p in matn_persons_clean if p]
        if matn_persons_clean:
            concept_segments.append(f"الأعلام: {'، '.join(matn_persons_clean)}")
    if place_names:
        concept_segments.append(f"الأماكن: {'، '.join(place_names)}")
    if hist_events:
        concept_segments.append(f"التاريخ: {'، '.join(hist_events)}")

    if not concept_segments:
        existing = (passage.get("embed_concept_text") or "").strip()
        existing_clean = clean_hygienic_arabic_text(
            existing,
            strip_spoken_fillers=True,
            forbidden_phrases=strict_forbidden_isnad,
        )
        concept_body = existing_clean
    else:
        concept_body = " | ".join(concept_segments)

    title_str = sub_heading or clean_hygienic_arabic_text(str(source_meta.get("title") or "مفهوم علمي"))
    return f"task: search result | title: {title_str} | text: {concept_body}"


def prepare_gem_embed_texts(
    gem: Dict[str, Any],
    passage: Optional[Dict[str, Any]] = None,
    isnad_persons: Optional[Sequence[Dict[str, Any]]] = None,
) -> Tuple[str, str]:
    """يجهز نصي التضمين المزدوج (embed_matn_text و embed_concept_text) للقاعدة العلمية في science_gems."""
    forbidden_isnad: List[str] = []
    for pe in (isnad_persons or []):
        if isinstance(pe, dict) and pe.get("source_layer") == "isnad":
            for k in ("mentioned_name", "canonical_name"):
                if pe.get(k):
                    forbidden_isnad.append(str(pe[k]))

    title = clean_hygienic_arabic_text(str(gem.get("title") or "قاعدة علمية"), forbidden_phrases=forbidden_isnad)
    category = clean_hygienic_arabic_text(str(gem.get("category") or "فائدة"), forbidden_phrases=forbidden_isnad)
    verbatim_rule = clean_hygienic_arabic_text(
        str(gem.get("verbatim_rule") or ""),
        strip_leading_isnad=True,
        forbidden_phrases=forbidden_isnad,
    )
    polished_rule = clean_hygienic_arabic_text(
        str(gem.get("polished_rule") or verbatim_rule),
        strip_spoken_fillers=True,
        forbidden_phrases=forbidden_isnad,
    )
    explanation = clean_hygienic_arabic_text(
        str(gem.get("explanation") or ""),
        strip_spoken_fillers=True,
        forbidden_phrases=forbidden_isnad,
    )

    gem_matn = f"task: search result | title: {title} | text: {verbatim_rule}"
    concept_parts = [f"القاعدة: {polished_rule}"]
    if explanation:
        concept_parts.append(f"الشرح: {explanation}")
    if passage and passage.get("sub_heading"):
        sub_h = clean_hygienic_arabic_text(str(passage["sub_heading"]), forbidden_phrases=forbidden_isnad)
        if sub_h:
            concept_parts.append(f"المبحث: {sub_h}")
    gem_concept = f"task: search result | title: {title} ({category}) | text: {' | '.join(concept_parts)}"
    return gem_matn, gem_concept


def format_query_prompt(query: str) -> str:
    """يصوغ استعلام المستخدم ببادئة المهمة القياسية في EmbeddingGemma 2."""
    q_clean = clean_hygienic_arabic_text(query)
    if q_clean.startswith("task:"):
        return q_clean
    return f"task: search query | query: {q_clean}"


# ---------------------------------------------------------------------------
# 3. العناقيد الدلالية العربية التراثية-المعاصرة والجذور (Arabic Semantic Engine)
# ---------------------------------------------------------------------------

CONCEPT_SYNONYM_CLUSTERS: List[Tuple[str, List[str]]] = [
    ("cluster_taysir_rukhsa", [
        "مشقه", "تجلب", "تيسير", "ضاق", "اتسع", "حرج", "رفع الحرج", "رخصه", "رخص",
        "شرعيه", "عذر", "مرض", "سفر", "ضروره", "محظورات", "تخفيف", "عسر", "يسر",
    ]),
    ("cluster_niyyah_qasd", [
        "اعمال", "بالنيات", "نيه", "قصد", "امور", "بمقاصدها", "اخلاص", "رياء", "سمعه",
        "عباده", "عاده", "تمييز", "قلب", "ثواب", "ابتغاء", "وجه الله",
    ]),
    ("cluster_yaqin_shakk", [
        "يقين", "يزول", "بالشك", "استصحاب", "اصل", "بقاء", "ذمه", "براءه", "طهاره",
        "حدث", "وضوء", "ظن", "غالب", "وهم",
    ]),
    ("cluster_urf_fatwa", [
        "تغير", "احكام", "تبدل", "ازمان", "عرف", "عاده", "محكمه", "فتوي", "قضاء",
        "بيئه", "عصر", "معاصره", "نوازل", "مصلحه", "مقاصد", "عوائد",
    ]),
    ("cluster_darar_izalah", [
        "ضرر", "ضرار", "يزال", "يدفع", "مفسده", "مفاسد", "درء", "جلب", "مصالح",
        "اخف", "الضررين", "تعدي", "ضمان", "اتلاف",
    ]),
    ("cluster_aqli_hukm_kalam", [
        "واجب", "عقلي", "يتصور", "العقل", "عدمه", "مستحيل", "جائز", "ممكن", "وجوده",
        "حكم عقلي", "حكم عادي", "حكم شرعي", "ام البراهين", "سنوسي", "اشعري", "علم الكلام",
        "برهان", "حدوث", "قدم", "بقاء", "مخالفه للحوادث", "غني مطلق", "افتقار",
    ]),
    ("cluster_sifat_maani", [
        "صفات", "المعاني", "معنويه", "نفسيه", "سلبيه", "قدره", "اراده", "علم", "حياه",
        "سمع", "بصر", "كلام", "تعلق", "تنجيزي", "صلوحي",
    ]),
    ("cluster_sababiyyah_adah", [
        "سببيه", "عاده", "تلازم", "اقتران", "تاثير", "طبع", "عله", "نار", "احراق",
        "خلق", "مقارنه", "خرق العاده", "معجزه",
    ]),
    ("cluster_tahara_akhdari", [
        "اخضري", "طهاره", "مياه", "وضوء", "فرائض", "سنن", "نواقض", "غسل", "تيمم",
        "صلاه", "سهو", "سجود", "قبلي", "بعدي", "ترقيع", "عبادات", "مالكي",
    ]),
    ("cluster_zakat_maliki", [
        "زكاه", "نصاب", "حول", "ماشيه", "عين", "حرث", "ثمار", "معادن", "ركاز", "عروض",
        "تجاره", "مدير", "محتكر", "فقراء", "مساكين", "مصارف",
    ]),
    ("cluster_buyu_riba", [
        "بيع", "بيوع", "ربا", "فضل", "نسيئه", "غرر", "جهاله", "سلم", "صرف", "خيار",
        "مجلس", "شرط", "عقد", "عقود", "معاملات", "ثمن", "مثمن",
    ]),
    ("cluster_usool_qiyas", [
        "قياس", "عله", "مناط", "تنقيح", "تحقيق", "تخريج", "نص", "اجماع", "استحسان",
        "مصالح مرسله", "سد الذرائع", "مفهوم", "منطوق", "عام", "خاص", "مطلق", "مقيد",
    ]),
    ("cluster_hadith_mustalah", [
        "صحيح", "حسن", "ضعيف", "مرسل", "منقطع", "معضل", "مدلس", "شاذ", "معلل", "عله",
        "جرح", "تعديل", "ثقه", "ضبط", "عداله", "متواتر", "احاد", "اسناد", "متن",
    ]),
    ("cluster_tafsir_quran", [
        "تفسير", "تاويل", "اسباب النزول", "مكي", "مدني", "ناسخ", "منسوخ", "محكم",
        "متشابه", "قراءات", "اعجاز", "تناسب", "سياق", "ايه", "سوره",
    ]),
    ("cluster_tazkiyah_qalb", [
        "تزكيه", "نفس", "قلب", "توبه", "صبر", "شكر", "توكل", "خوف", "رجاء", "محبه",
        "زهد", "ورع", "مراقبه", "محاسبه", "عجب", "كبر", "حسد", "غفله",
    ]),
    ("cluster_sirah_hijrah", [
        "سيره", "نبويه", "هجره", "مدينه", "مكه", "غزوه", "بدر", "احد", "خندق", "صلح",
        "حديبيه", "فتح", "مؤاخاه", "صحابه", "انصار", "مهاجرين", "وثيقه",
    ]),
    ("cluster_nahw_irab", [
        "نحو", "اعراب", "بناء", "مبتدا", "خبر", "فاعل", "مفعول", "حال", "تمييز",
        "مرفوع", "منصوب", "مجرور", "مجزوم", "عامل", "عمل", "نداء", "اضافه",
    ]),
]

ARABIC_PREFIXES = ("وال", "بال", "كال", "فال", "ولل", "لل", "ال", "و", "ف", "ب", "ك", "ل", "س")
ARABIC_SUFFIXES = ("كموها", "تموها", "ونهم", "ينهم", "اتنا", "يات", "ات", "ون", "ين", "ان", "هم", "هن", "كم", "نا", "ها", "ية", "يه", "ه", "ي", "ك")


def arabic_light_stem(word: str) -> str:
    """تجريد صرفي عربي خفيف لاستخلاص الجذع الدلالي."""
    w = word.strip()
    if len(w) <= 3:
        return w
    for pref in ARABIC_PREFIXES:
        if w.startswith(pref) and len(w) - len(pref) >= 3:
            w = w[len(pref):]
            break
    for suf in ARABIC_SUFFIXES:
        if w.endswith(suf) and len(w) - len(suf) >= 3:
            w = w[:-len(suf)]
            break
    return w


def arabic_consonant_skeleton(stem: str) -> str:
    """استخلاص الجذر/الهيكل الصامت التقريبي بحذف حروف العلة والمد الزائدة."""
    if len(stem) <= 3:
        return stem
    core = stem[0] + re.sub(r"[اوي]", "", stem[1:-1]) + stem[-1]
    if len(core) < 3:
        return stem[:3]
    return core[:4]


def _extract_semantic_payload(text: str) -> str:
    """
    يجرد ديباجة القالب القياسي (task: ... | title: ... | text: ...) وعناوين الحقول
    حتى تتركز الطاقة الشعاعية في الكلمات والمفاهيم الحقيقية للمتن أو المفهوم.
    """
    s = text.strip()
    if "| text:" in s:
        head_part, body_part = s.split("| text:", 1)
        title_val = ""
        if "title:" in head_part:
            title_val = head_part.split("title:", 1)[1].strip()
        # إذا كان النص نص مفهوم (يحتوي على العنوان/الملخص/القواعد) نعطي العنوان وزناً كاملاً،
        # وإذا كان نص متن صرفاً نركز على المتن الحرفي
        if any(lbl in body_part for lbl in ("الملخص:", "الموضوعات:", "القواعد:", "أسئلة:")):
            s = f"{title_val} {body_part}"
        else:
            s = body_part
    elif "| query:" in s:
        s = s.split("| query:", 1)[1].strip()
    elif s.startswith("task:"):
        s = re.sub(r"^task:\s*[^|]+\|\s*", "", s)

    # حذف تسميات الحقول الهيكلية المتكررة
    s = re.sub(r"\b(?:العنوان|الملخص|الموضوعات|القواعد|أسئلة|الأعلام|الأماكن|التاريخ|القاعدة|الشرح|المبحث)\s*:", " ", s)
    return s


class DeterministicArabicGemma2Embedder:
    """
    محرك تضمين محلي حتمي فائق السرعة مسرّع على Apple Silicon MPS / NumPy
    (dim=768، مطبّع L2-Norm بدقة float32).
    يحاكي سلوك EmbeddingGemma 2 عبر الدمج الموزون بين:
    1. المفردات الدقيقة والتراكيب الثنائية (Exact Word Unigrams & Bigrams)
    2. الجذوع الصرفية والجذور الصامتة (Light Stems & Consonantal Roots)
    3. المقاطع الحرفية الثلاثية والرباعية (Char 3/4-grams)
    4. إسقاط العناقيد المفهومية التراثية-المعاصرة (Semantic Concept Projection)
    """

    def __init__(self, dim: int = 768, use_mps: bool = True) -> None:
        self.dim = int(dim)
        self.model_name = f"embeddinggemma-2-deterministic-arabic-{self.dim}d"
        self.use_mps = bool(
            use_mps and HAS_TORCH and torch is not None and torch.backends.mps.is_available()
        )
        self.device = "mps" if self.use_mps else "cpu"

    def _feature_indices_and_signs(self, feature_key: str, k: int = 4) -> Tuple[np.ndarray, np.ndarray]:
        digest = hashlib.sha256(feature_key.encode("utf-8")).digest()
        raw_ints = np.frombuffer(digest[: k * 4], dtype=np.uint32)
        indices = (raw_ints % self.dim).astype(np.int64)
        signs = np.where((raw_ints >> 31) == 0, 1.0, -1.0).astype(np.float32)
        return indices, signs

    def _encode_single_np(self, text: str) -> np.ndarray:
        payload = _extract_semantic_payload(text)
        norm_text = normalize_arabic_for_match(payload)
        vec = np.zeros(self.dim, dtype=np.float32)

        if not norm_text:
            vec[0] = 1.0
            return vec

        tokens = [
            tok for tok in re.findall(r"[\u0621-\u064A0-9]+", norm_text)
            if len(tok) >= 2 and tok not in ARABIC_STOPWORDS
        ]
        if not tokens:
            tokens = re.findall(r"[\u0621-\u064A0-9]+", norm_text)

        stems: List[str] = []
        for tok in tokens:
            st = arabic_light_stem(tok)
            skel = arabic_consonant_skeleton(st)
            stems.append(st)

            # 1. المفردة التامة (Exact word token)
            idx, sgn = self._feature_indices_and_signs(f"w:{tok}", k=4)
            np.add.at(vec, idx, sgn * 2.2)

            # 2. الجذع الصرفي والجذر الصامت (Morphological stem & root)
            idx_s, sgn_s = self._feature_indices_and_signs(f"s:{st}", k=4)
            np.add.at(vec, idx_s, sgn_s * 1.8)

            idx_r, sgn_r = self._feature_indices_and_signs(f"r:{skel}", k=3)
            np.add.at(vec, idx_r, sgn_r * 1.1)

            # 3. المقاطع الحرفية (Char 3-grams & 4-grams)
            padded = f"<{tok}>"
            for n in (3, 4):
                if len(padded) >= n:
                    for i in range(len(padded) - n + 1):
                        ng = padded[i : i + n]
                        idx_c, sgn_c = self._feature_indices_and_signs(f"c{n}:{ng}", k=2)
                        np.add.at(vec, idx_c, sgn_c * 0.35)

        # 4. التراكيب الثنائية (Word & Stem Bigrams — حاسمة لعبارات المتن التراثي)
        for i in range(len(tokens) - 1):
            bg_w = f"bw:{tokens[i]}_{tokens[i + 1]}"
            idx_bw, sgn_bw = self._feature_indices_and_signs(bg_w, k=4)
            np.add.at(vec, idx_bw, sgn_bw * 2.8)

            bg_s = f"bs:{stems[i]}_{stems[i + 1]}"
            idx_bs, sgn_bs = self._feature_indices_and_signs(bg_s, k=3)
            np.add.at(vec, idx_bs, sgn_bs * 2.0)

        # 5. إسقاط العناقيد المفهومية التراثية-المعاصرة (Semantic Concept Projection)
        token_set = set(tokens) | set(stems)
        for cluster_id, keywords in CONCEPT_SYNONYM_CLUSTERS:
            hits = 0
            for kw in keywords:
                if " " in kw:
                    if kw in norm_text:
                        hits += 2
                else:
                    kw_stem = arabic_light_stem(kw)
                    if kw in token_set or kw_stem in token_set:
                        hits += 1
            if hits > 0:
                weight = min(4.5, 1.8 * (1.0 + np.log1p(hits)))
                idx_cl, sgn_cl = self._feature_indices_and_signs(f"concept:{cluster_id}", k=6)
                np.add.at(vec, idx_cl, sgn_cl * float(weight))

        return vec

    def _l2_normalize_batch(self, mat: np.ndarray) -> np.ndarray:
        if mat.ndim == 1:
            mat = mat.reshape(1, -1)
        mat = mat.astype(np.float32, copy=False)
        if self.use_mps and HAS_TORCH and torch is not None:
            try:
                t = torch.from_numpy(mat).to(self.device, dtype=torch.float32)
                norms = torch.linalg.norm(t, dim=1, keepdim=True).clamp(min=1e-12)
                t_norm = (t / norms).to("cpu")
                return t_norm.numpy().astype(np.float32)
            except Exception:
                pass
        norms = np.linalg.norm(mat, axis=1, keepdims=True)
        norms = np.where(norms < 1e-12, 1.0, norms)
        return (mat / norms).astype(np.float32)

    def embed_documents(self, texts: Sequence[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        raw_vecs = np.stack([self._encode_single_np(t) for t in texts], axis=0)
        return self._l2_normalize_batch(raw_vecs)

    def embed_query(self, query: str) -> np.ndarray:
        formatted = format_query_prompt(query)
        mat = self.embed_documents([formatted])
        return mat[0]


# ---------------------------------------------------------------------------
# 4. محولات Ollama و SentenceTransformers و Google GenAI
# ---------------------------------------------------------------------------

class OllamaGemma2Embedder:
    """محول خادم Ollama المحلي لنموذج embeddinggemma."""

    def __init__(
        self,
        model_name: str = "embeddinggemma",
        dim: int = 768,
        base_url: str = "http://127.0.0.1:11434",
    ) -> None:
        self.model_name = model_name
        self.dim = int(dim)
        self.base_url = base_url.rstrip("/")

    def is_available(self, timeout: float = 0.4) -> bool:
        try:
            req = urllib.request.Request(f"{self.base_url}/api/tags", method="GET")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                models = [m.get("name", "") for m in data.get("models", [])]
                return any("embeddinggemma" in m or self.model_name in m for m in models)
        except Exception:
            return False

    def _fit_and_normalize(self, vecs: np.ndarray) -> np.ndarray:
        vecs = vecs.astype(np.float32)
        if vecs.shape[1] > self.dim:
            vecs = vecs[:, : self.dim]
        elif vecs.shape[1] < self.dim:
            pad = np.zeros((vecs.shape[0], self.dim - vecs.shape[1]), dtype=np.float32)
            vecs = np.concatenate([vecs, pad], axis=1)
        norms = np.linalg.norm(vecs, axis=1, keepdims=True)
        norms = np.where(norms < 1e-12, 1.0, norms)
        return (vecs / norms).astype(np.float32)

    def embed_documents(self, texts: Sequence[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        payload = json.dumps({"model": self.model_name, "input": list(texts)}).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/api/embed",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30.0) as resp:
            res = json.loads(resp.read().decode("utf-8"))
            embs = np.array(res["embeddings"], dtype=np.float32)
            return self._fit_and_normalize(embs)

    def embed_query(self, query: str) -> np.ndarray:
        return self.embed_documents([format_query_prompt(query)])[0]


class SentenceTransformersGemma2Embedder:
    """محول مكتبة sentence-transformers لنموذج google/embeddinggemma-2."""

    def __init__(self, model_name: str = "google/embeddinggemma-300m", dim: int = 768) -> None:
        from sentence_transformers import SentenceTransformer  # type: ignore

        device = "mps" if (HAS_TORCH and torch is not None and torch.backends.mps.is_available()) else "cpu"
        self.model_name = model_name
        self.dim = int(dim)
        self.model = SentenceTransformer(model_name, device=device)

    def embed_documents(self, texts: Sequence[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        vecs = self.model.encode(list(texts), convert_to_numpy=True, normalize_embeddings=True).astype(np.float32)
        if vecs.shape[1] != self.dim:
            vecs = vecs[:, : self.dim]
            norms = np.linalg.norm(vecs, axis=1, keepdims=True)
            norms = np.where(norms < 1e-12, 1.0, norms)
            vecs = (vecs / norms).astype(np.float32)
        return vecs

    def embed_query(self, query: str) -> np.ndarray:
        return self.embed_documents([format_query_prompt(query)])[0]


class GenAIGemma2Embedder:
    """محول حزمة google.genai للتضمين السحابي."""

    def __init__(self, model_name: str = "gemini-embedding-001", dim: int = 768) -> None:
        from google import genai  # type: ignore

        self.model_name = model_name
        self.dim = int(dim)
        self.client = genai.Client()

    def embed_documents(self, texts: Sequence[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        resp = self.client.models.embed_content(
            model=self.model_name,
            contents=list(texts),
        )
        vecs = np.array([e.values for e in resp.embeddings], dtype=np.float32)
        if vecs.shape[1] > self.dim:
            vecs = vecs[:, : self.dim]
        norms = np.linalg.norm(vecs, axis=1, keepdims=True)
        norms = np.where(norms < 1e-12, 1.0, norms)
        return (vecs / norms).astype(np.float32)

    def embed_query(self, query: str) -> np.ndarray:
        return self.embed_documents([format_query_prompt(query)])[0]


def create_embedder(
    backend: str = "auto",
    dim: int = 768,
    model_name: Optional[str] = None,
    use_mps: bool = True,
) -> Any:
    """ينشئ محرك التضمين المطلوب مع دعم التبديل التلقائي السلس."""
    backend = (backend or "auto").strip().lower()
    if backend == "deterministic-arabic-mps":
        return DeterministicArabicGemma2Embedder(dim=dim, use_mps=use_mps)
    if backend == "ollama":
        return OllamaGemma2Embedder(model_name=model_name or "embeddinggemma", dim=dim)
    if backend == "sentence-transformers":
        return SentenceTransformersGemma2Embedder(model_name=model_name or "google/embeddinggemma-300m", dim=dim)
    if backend == "genai":
        return GenAIGemma2Embedder(model_name=model_name or "gemini-embedding-001", dim=dim)

    # الوضع التلقائي (auto): يفحص توفر Ollama بنموذج embeddinggemma محلياً، وإلا يستخدم المحرك المحلي الحتمي المسرع
    if os.environ.get("TURATH_FORCE_DETERMINISTIC", "0") != "1":
        ollama_emb = OllamaGemma2Embedder(model_name=model_name or "embeddinggemma", dim=dim)
        if ollama_emb.is_available():
            return ollama_emb
    return DeterministicArabicGemma2Embedder(dim=dim, use_mps=use_mps)


# ---------------------------------------------------------------------------
# 5. بناء وتعبئة جداول المتجهات في SQLite (SQLite Dual-Vector Indexing)
# ---------------------------------------------------------------------------

EMBEDDING_TABLES_DDL = """
CREATE TABLE IF NOT EXISTS passage_embeddings (
    passage_id TEXT PRIMARY KEY,
    model_name TEXT NOT NULL,
    dim INTEGER NOT NULL,
    embed_matn_text TEXT NOT NULL,
    embed_concept_text TEXT NOT NULL,
    vec_matn_blob BLOB NOT NULL,
    vec_concept_blob BLOB NOT NULL,
    matn_norm REAL NOT NULL,
    concept_norm REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS gem_embeddings (
    gem_id TEXT PRIMARY KEY,
    passage_id TEXT NOT NULL,
    model_name TEXT NOT NULL,
    dim INTEGER NOT NULL,
    embed_matn_text TEXT NOT NULL,
    embed_concept_text TEXT NOT NULL,
    vec_matn_blob BLOB NOT NULL,
    vec_concept_blob BLOB NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_gem_embeddings_passage_id ON gem_embeddings(passage_id);
"""


def vector_to_blob(vec: np.ndarray) -> bytes:
    """يحول متجه float32 إلى بايتات BLOB جاهزة للتخزين في SQLite."""
    return np.asarray(vec, dtype=np.float32).tobytes()


def blob_to_vector(blob: bytes, dim: int = 768) -> np.ndarray:
    """يقرأ بايتات BLOB من SQLite كمتجه numpy float32."""
    vec = np.frombuffer(blob, dtype=np.float32)
    if dim and vec.size != dim:
        vec = vec[:dim]
    return vec


def embed_sqlite_corpus(
    db_path: str | Path,
    backend: str = "auto",
    dim: int = 768,
    model_name: Optional[str] = None,
    use_mps: bool = True,
    batch_size: int = 128,
) -> Dict[str, Any]:
    """
    يقوم بتجهيز النصوص المزدوجة (embed_matn_text و embed_concept_text) وتوليد متجهات
    float32 مطبّعة بـ L2-Norm لكل من جدولَي passage_embeddings و gem_embeddings.
    """
    db_path = Path(db_path)
    if not db_path.exists():
        raise FileNotFoundError(f"Database file not found: {db_path}")

    embedder = create_embedder(backend=backend, dim=dim, model_name=model_name, use_mps=use_mps)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    try:
        conn.executescript(EMBEDDING_TABLES_DDL)

        # جلب بيانات المصادر
        sources_map: Dict[str, Dict[str, Any]] = {}
        try:
            for r in conn.execute("SELECT * FROM sources"):
                sources_map[str(r["source_id"])] = dict(r)
        except sqlite3.OperationalError:
            pass

        # جلب الأعلام المرتبطين بالمقاطع
        persons_by_passage: Dict[str, List[Dict[str, Any]]] = {}
        try:
            for r in conn.execute("SELECT * FROM passage_persons"):
                pid = str(r["passage_id"])
                persons_by_passage.setdefault(pid, []).append(dict(r))
        except sqlite3.OperationalError:
            pass

        # جلب الأماكن المرتبطة بالمقاطع
        places_by_passage: Dict[str, List[Dict[str, Any]]] = {}
        try:
            for r in conn.execute("SELECT * FROM passage_places"):
                pid = str(r["passage_id"])
                places_by_passage.setdefault(pid, []).append(dict(r))
        except sqlite3.OperationalError:
            pass

        # جلب التواريخ المرتبطة بالمقاطع
        events_by_passage: Dict[str, List[Dict[str, Any]]] = {}
        try:
            for r in conn.execute("SELECT * FROM events_chronology"):
                pid = str(r["passage_id"])
                events_by_passage.setdefault(pid, []).append(dict(r))
        except sqlite3.OperationalError:
            pass

        # جلب القواعد العلمية (science_gems)
        gems_rows: List[Dict[str, Any]] = []
        gems_by_passage: Dict[str, List[Dict[str, Any]]] = {}
        try:
            for r in conn.execute("SELECT * FROM science_gems ORDER BY gem_id"):
                gd = dict(r)
                gems_rows.append(gd)
                gems_by_passage.setdefault(str(gd["passage_id"]), []).append(gd)
        except sqlite3.OperationalError:
            pass

        # جلب جميع المقاطع
        passages_rows = [dict(r) for r in conn.execute("SELECT * FROM passages ORDER BY passage_id")]
        passages_by_id = {str(p["passage_id"]): p for p in passages_rows}

        # 1. تجهيز نصوص التضمين المزدوجة للمقاطع
        passage_ids: List[str] = []
        matn_texts: List[str] = []
        concept_texts: List[str] = []

        for p in passages_rows:
            pid = str(p["passage_id"])
            src_meta = sources_map.get(str(p.get("source_id") or ""), {})
            p_persons = persons_by_passage.get(pid, [])
            p_places = places_by_passage.get(pid, [])
            p_events = events_by_passage.get(pid, [])
            p_gems = gems_by_passage.get(pid, [])

            matn_t = prepare_embed_matn_text(p, source_meta=src_meta, isnad_persons=p_persons)
            concept_t = prepare_embed_concept_text(
                p,
                gems=p_gems,
                persons=p_persons,
                places=p_places,
                events=p_events,
                source_meta=src_meta,
            )

            passage_ids.append(pid)
            matn_texts.append(matn_t)
            concept_texts.append(concept_t)

            # تحديث الحقلين في جدول passages لضمان النظافة التامة في الجدول الأصلي أيضاً
            conn.execute(
                "UPDATE passages SET embed_matn_text = ?, embed_concept_text = ? WHERE passage_id = ?",
                (matn_t, concept_t, pid),
            )

        # توليد المتجهات على دفعات
        matn_vecs = np.zeros((len(passage_ids), embedder.dim), dtype=np.float32)
        concept_vecs = np.zeros((len(passage_ids), embedder.dim), dtype=np.float32)

        for i in range(0, len(passage_ids), batch_size):
            j = min(i + batch_size, len(passage_ids))
            matn_vecs[i:j] = embedder.embed_documents(matn_texts[i:j])
            concept_vecs[i:j] = embedder.embed_documents(concept_texts[i:j])

        conn.execute("DELETE FROM passage_embeddings")
        for idx, pid in enumerate(passage_ids):
            v_m = matn_vecs[idx]
            v_c = concept_vecs[idx]
            m_norm = float(np.linalg.norm(v_m))
            c_norm = float(np.linalg.norm(v_c))
            conn.execute(
                """
                INSERT OR REPLACE INTO passage_embeddings (
                    passage_id, model_name, dim,
                    embed_matn_text, embed_concept_text,
                    vec_matn_blob, vec_concept_blob,
                    matn_norm, concept_norm
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    pid,
                    embedder.model_name,
                    embedder.dim,
                    matn_texts[idx],
                    concept_texts[idx],
                    vector_to_blob(v_m),
                    vector_to_blob(v_c),
                    m_norm,
                    c_norm,
                ),
            )

        # 2. تجهيز وتوليد المتجهات المزدوجة للقواعد العلمية (gem_embeddings)
        gem_ids: List[str] = []
        gem_pids: List[str] = []
        gem_matn_texts: List[str] = []
        gem_concept_texts: List[str] = []

        for g in gems_rows:
            gid = str(g["gem_id"])
            pid = str(g["passage_id"])
            parent_p = passages_by_id.get(pid)
            p_persons = persons_by_passage.get(pid, [])
            g_matn_t, g_concept_t = prepare_gem_embed_texts(g, passage=parent_p, isnad_persons=p_persons)
            gem_ids.append(gid)
            gem_pids.append(pid)
            gem_matn_texts.append(g_matn_t)
            gem_concept_texts.append(g_concept_t)

        gem_matn_vecs = np.zeros((len(gem_ids), embedder.dim), dtype=np.float32)
        gem_concept_vecs = np.zeros((len(gem_ids), embedder.dim), dtype=np.float32)

        for i in range(0, len(gem_ids), batch_size):
            j = min(i + batch_size, len(gem_ids))
            gem_matn_vecs[i:j] = embedder.embed_documents(gem_matn_texts[i:j])
            gem_concept_vecs[i:j] = embedder.embed_documents(gem_concept_texts[i:j])

        conn.execute("DELETE FROM gem_embeddings")
        for idx, gid in enumerate(gem_ids):
            conn.execute(
                """
                INSERT OR REPLACE INTO gem_embeddings (
                    gem_id, passage_id, model_name, dim,
                    embed_matn_text, embed_concept_text,
                    vec_matn_blob, vec_concept_blob
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    gid,
                    gem_pids[idx],
                    embedder.model_name,
                    embedder.dim,
                    gem_matn_texts[idx],
                    gem_concept_texts[idx],
                    vector_to_blob(gem_matn_vecs[idx]),
                    vector_to_blob(gem_concept_vecs[idx]),
                ),
            )

        conn.commit()
        return {
            "db_path": str(db_path),
            "model_name": embedder.model_name,
            "dim": embedder.dim,
            "device": getattr(embedder, "device", "cpu"),
            "passages_embedded": len(passage_ids),
            "gems_embedded": len(gem_ids),
        }
    finally:
        conn.close()


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="توليد وفهرسة التضمين المزدوج بـ EmbeddingGemma 2 في قاعدة بيانات SQLite."
    )
    parser.add_argument("--db", "--db-path", dest="db", required=True, help="مسار ملف قاعدة بيانات SQLite")
    parser.add_argument(
        "--backend",
        default="auto",
        choices=["auto", "ollama", "sentence-transformers", "genai", "deterministic-arabic-mps"],
        help="محرك التضمين المستخدم (الافتراضي: auto)",
    )
    parser.add_argument("--dim", type=int, default=768, help="أبعاد المتجه (الافتراضي: 768)")
    parser.add_argument("--model-name", default=None, help="اسم النموذج الاختياري")
    parser.add_argument("--no-mps", action="store_true", help="تعطيل تسريع MPS واستخدام CPU فقط")
    parser.add_argument("--batch-size", type=int, default=128, help="حجم الدفعة")

    args = parser.parse_args(argv)
    stats = embed_sqlite_corpus(
        db_path=args.db,
        backend=args.backend,
        dim=args.dim,
        model_name=args.model_name,
        use_mps=not args.no_mps,
        batch_size=args.batch_size,
    )
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
