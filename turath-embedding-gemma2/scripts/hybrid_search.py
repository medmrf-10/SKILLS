#!/usr/bin/env python3
"""
محرك الاسترجاع الهجين العلائقي (Hybrid Search Engine: FTS5 BM25 + Dual EmbeddingGemma 2 + RRF + Entity Filters)
لمنظومة التراث الفقهي والمعرفي (turath-embedding-gemma2).

يدمج بين:
1. البحث النصي الحرفي عبر passages_fts (FTS5 BM25).
2. البحث الدلالي المزدوج في متجه المتن (vec_matn) ومتجه المفهوم (vec_concept) باستخدام ضرب المصفوفات المسرّع (torch MPS/CPU أو numpy).
3. دمج الرتب والدرجات (Weighted Score + Reciprocal Rank Fusion RRF) مع التحكم بالأوزان (--alpha-matn, --alpha-concept, --alpha-fts).
4. الفلترة العلائقية الصارمة بالكيانات:
   - --person مع --person-layer matn|isnad|any (الافتراضي 'matn' لعزل رواة السند)
   - --place
   - --year-min و --year-max (في events_chronology مع event_layer='historical')
   - --surah و --ayah (في evidences)
   - --science و --source-type
   - --matn-clause (في matn_triangulation)
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

import numpy as np

try:
    import torch
    HAS_TORCH = True
except ImportError:
    torch = None  # type: ignore
    HAS_TORCH = False

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from embed_corpus_gemma2 import (  # noqa: E402
    ARABIC_STOPWORDS,
    ARABIC_STOPWORDS_NORM,
    BOILERPLATE_CLEAN_RES,
    CONCEPT_SYNONYM_CLUSTERS,
    DIGITS_MAP,
    QUERY_FRAMING_STOPWORDS_NORM,
    arabic_consonant_skeleton,
    arabic_light_stem,
    blob_to_vector,
    create_embedder,
    normalize_arabic_for_match,
)

PERSON_TITLE_STOPWORDS: Set[str] = {
    "الامام", "امام", "الشيخ", "شيخ", "الاسلام", "الحافظ", "حافظ",
    "القاضي", "قاضي", "العلامه", "علامه", "الصحابي", "صحابي", "الجليل",
    "الخليفه", "خليفه", "امير", "المؤمنين", "المومنين", "نبي", "رسول", "الله",
    "فضيله", "سيدنا", "مولانا", "رضي", "عنه", "عنها", "عنهما", "عنهم", "عنهن",
    "رحمه", "رحمهم", "عليه", "عليهم", "عليهما", "عليها", "السلام", "صلي", "وسلم",
    "تعالي", "سبحانه", "ابو", "ابي", "ابا",
}

PLACE_EPITHET_STOPWORDS: Set[str] = {
    "المكرمه", "مكرمه", "المنوره", "منوره", "الشريف", "شريف",
    "المقدسه", "مقدسه", "المحروسه", "محروسه",
}

_SURAH_NAMES_ORDERED: List[str] = [
    "الفاتحه", "البقره", "ال عمران", "النساء", "المائده", "الانعام", "الاعراف", "الانفال", "التوبه", "يونس",
    "هود", "يوسف", "الرعد", "ابراهيم", "الحجر", "النحل", "الاسراء", "الكهف", "مريم", "طه",
    "الانبياء", "الحج", "المؤمنون", "النور", "الفرقان", "الشعراء", "النمل", "القصص", "العنكبوت", "الروم",
    "لقمان", "السجده", "الاحزاب", "سبا", "فاطر", "يس", "الصافات", "ص", "الزمر", "غافر",
    "فصلت", "الشوري", "الزخرف", "الدخان", "الجاثيه", "الاحقاف", "محمد", "الفتح", "الحجرات", "ق",
    "الذاريات", "الطور", "النجم", "القمر", "الرحمن", "الواقعه", "الحديد", "المجادله", "الحشر", "الممتحنه",
    "الصف", "الجمعه", "المنافقون", "التغابن", "الطلاق", "التحريم", "الملك", "القلم", "الحاقه", "المعارج",
    "نوح", "الجن", "المزمل", "المدثر", "القيامه", "الانسان", "المرسلات", "النبا", "النازعات", "عبس",
    "التكوير", "الانفطار", "المطففين", "الانشقاق", "البروج", "الطارق", "الاعلي", "الغاشيه", "الفجر", "البلد",
    "الشمس", "الليل", "الضحي", "الشرح", "التين", "العلق", "القدر", "البينه", "الزلزله", "العاديات",
    "القارعه", "التكاثر", "العصر", "الهمزه", "الفيل", "قريش", "الماعون", "الكوثر", "الكافرون", "النصر",
    "المسد", "الاخلاص", "الفلق", "الناس",
]
SURAH_NAME_TO_NUMBER: Dict[str, int] = {
    normalize_arabic_for_match(nm): idx + 1 for idx, nm in enumerate(_SURAH_NAMES_ORDERED)
}
SURAH_NAME_TO_NUMBER.update({
    "عمران": 3,
    "بني اسرائيل": 17,
    "المؤمن": 40,
    "الدهر": 76,
    "الانشراح": 94,
    "اقرا": 96,
    "لم يكن": 98,
    "اللهب": 111,
})


def _canonicalize_person_text(text: str) -> str:
    """يطبع اسم العلم ويوحد صيغ الإعراب في الكنى والأنساب (أبو/أبي/أبا -> ابو، ابن/بن -> بن)."""
    s = normalize_arabic_for_match(text)
    s = re.sub(r"\b(?:ابو|ابي|ابا)\b", "ابو", s)
    s = re.sub(r"\b(?:ابن|بن)\b", "بن", s)
    return re.sub(r"\s+", " ", s).strip()


def _extract_person_core_tokens(text: str) -> List[str]:
    """يستخرج الكلمات الجوهرية المميزة لاسم العلم بعد تجريد الألقاب والترضية."""
    canon = _canonicalize_person_text(text)
    raw_toks = [t for t in re.findall(r"[\u0621-\u064A0-9]+", canon) if len(t) >= 2]
    core = [t for t in raw_toks if t not in PERSON_TITLE_STOPWORDS]
    if not core:
        core = [t for t in raw_toks if t not in {"الامام", "الشيخ", "رضي", "الله", "عنه", "رحمه", "عليه", "السلام"}]
    return core or raw_toks


def _fts_orthographic_group(tok: str) -> str:
    """
    يبني مجموعة بدائل إملائية وصرفية آمنة لـ SQLite FTS5 MATCH لمعالجة:
    - اختلاف الهمزات (الاجماع / الإجماع / الأجماع، مساله / مسألة، بالاباء / بآبائكم)
    - التاء المربوطة والهاء (الصدقه / الصدقة / بالصدقة)
    - الألف المقصورة والياء (استوي / استوى، المرضى / مرضاكم)
    - الجذوع مع بادئات العطف والجر وأحرف المضارعة ("حلف"* / "تحلف"* / "صدق"* / "مرض"*)
    """
    clean_t = re.sub(r"[^\u0621-\u064A0-9A-Za-z]", "", tok).strip()
    if not clean_t:
        return ""
    norm_t = normalize_arabic_for_match(clean_t)
    stem_t = arabic_light_stem(norm_t)

    variants: List[str] = []
    for cand in (clean_t, norm_t):
        if cand and cand not in variants:
            variants.append(cand)

    # بدائل التاء المربوطة / الهاء والألف المقصورة / الياء
    for base in list(variants):
        if base.endswith("ه") and len(base) >= 3:
            variants.append(base[:-1] + "ة")
        elif base.endswith("ة") and len(base) >= 3:
            variants.append(base[:-1] + "ه")
        if base.endswith("ي") and len(base) >= 3:
            variants.append(base[:-1] + "ى")
        elif base.endswith("ى") and len(base) >= 3:
            variants.append(base[:-1] + "ي")

    # بدائل همزة القطع بعد (ال) التعريف أو في أول الكلمة أو وسطها (مساله -> مسألة)
    for base in list(variants):
        if base.startswith("الا") and len(base) >= 4:
            variants.append("الإ" + base[3:])
            variants.append("الأ" + base[3:])
            variants.append("الآ" + base[3:])
        elif base.startswith("ا") and not base.startswith("ال") and len(base) >= 3:
            variants.append("إ" + base[1:])
            variants.append("أ" + base[1:])
            variants.append("آ" + base[1:])
        if "سال" in base:
            variants.append(base.replace("سال", "سأل"))
        if "قران" in base:
            variants.append(base.replace("قران", "قرآن"))
        if "ابا" in base:
            variants.append(base.replace("ابا", "آبا"))

    quoted_parts: List[str] = []
    seen_q: Set[str] = set()
    for v in variants:
        q = f'"{v}"'
        if q not in seen_q:
            seen_q.add(q)
            quoted_parts.append(q)

    # إضافة مطابقة البادئة (Prefix Wildcard) للجذع الصرفي في FTS5
    if len(stem_t) >= 3:
        stem_variants = [stem_t]
        if stem_t.startswith("ا"):
            stem_variants.extend(["إ" + stem_t[1:], "أ" + stem_t[1:], "آ" + stem_t[1:]])
        if "سال" in stem_t:
            stem_variants.append(stem_t.replace("سال", "سأل"))
        for sv in stem_variants:
            for pref in ("", "ال", "و", "ب", "بال", "ل", "ت", "ي"):
                cand_p = f'"{pref}{sv}"*'
                if cand_p not in seen_q:
                    seen_q.add(cand_p)
                    quoted_parts.append(cand_p)

    if len(quoted_parts) == 1:
        return quoted_parts[0]
    return "(" + " OR ".join(quoted_parts) + ")"


def _compute_cosine_scores(
    mat: np.ndarray,
    query_vec: np.ndarray,
    use_mps: bool = True,
) -> np.ndarray:
    """
    يحسب تشابه جيب التمام (Cosine Similarity) لمصفوفة متجهات مطبّعة مسبقاً بـ L2-Norm
    عبر ضرب المصفوفات المسرّع (torch MPS/CPU أو numpy Vectorized MatMul).
    """
    if mat.size == 0:
        return np.zeros((0,), dtype=np.float32)
    mat_f32 = np.ascontiguousarray(mat, dtype=np.float32)
    q_f32 = np.ascontiguousarray(query_vec, dtype=np.float32).reshape(-1)

    if use_mps and HAS_TORCH and torch is not None and torch.backends.mps.is_available():
        try:
            t_mat = torch.from_numpy(mat_f32).to("mps", dtype=torch.float32)
            t_q = torch.from_numpy(q_f32).to("mps", dtype=torch.float32)
            sims = torch.mv(t_mat, t_q).to("cpu").numpy().astype(np.float32)
            return sims
        except Exception:
            pass

    if HAS_TORCH and torch is not None:
        try:
            t_mat = torch.from_numpy(mat_f32)
            t_q = torch.from_numpy(q_f32)
            return torch.mv(t_mat, t_q).numpy().astype(np.float32)
        except Exception:
            pass

    return (mat_f32 @ q_f32).astype(np.float32)


class HybridSearchEngine:
    """
    محرك الاسترجاع الهجين العلائقي فوق قاعدة بيانات SQLite الموحدة.
    """

    def __init__(
        self,
        db_path: str | Path,
        backend: str = "auto",
        dim: int = 768,
        model_name: Optional[str] = None,
        use_mps: bool = True,
    ) -> None:
        self.db_path = Path(db_path)
        if not self.db_path.exists():
            raise FileNotFoundError(f"SQLite database not found: {self.db_path}")
        self.use_mps = use_mps
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.create_function("NORM_AR", 1, lambda s: normalize_arabic_for_match(str(s or "")))

        # تحديد البعد الفعلي المخزن في passage_embeddings إن وجد
        stored_dim = dim
        try:
            row = self.conn.execute("SELECT dim FROM passage_embeddings LIMIT 1").fetchone()
            if row and row["dim"]:
                stored_dim = int(row["dim"])
        except sqlite3.OperationalError:
            pass

        self.dim = stored_dim
        self.embedder = create_embedder(
            backend=backend,
            dim=self.dim,
            model_name=model_name,
            use_mps=use_mps,
        )

    def close(self) -> None:
        if self.conn:
            self.conn.close()

    def __enter__(self) -> "HybridSearchEngine":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()

    # -----------------------------------------------------------------------
    # 1. الفلترة العلائقية الصارمة بالكيانات (Strict Relational Entity Filters)
    # -----------------------------------------------------------------------
    def resolve_candidate_passage_ids(
        self,
        person: Optional[str] = None,
        person_layer: str = "matn",
        place: Optional[str] = None,
        year_min: Optional[int] = None,
        year_max: Optional[int] = None,
        event_layer: str = "historical",
        surah: Optional[int] = None,
        ayah: Optional[str] = None,
        science: Optional[str] = None,
        source_type: Optional[str] = None,
        matn_clause: Optional[str] = None,
    ) -> Set[str]:
        """
        يرجع مجموعة معرفات المقاطع (passage_id) التي تحقق جميع الفلاتر العلائقية المحددة.
        """
        all_pids: Set[str] = {
            str(r["passage_id"])
            for r in self.conn.execute("SELECT passage_id FROM passages")
        }
        candidates = set(all_pids)

        # أ. فلتر العلم (مع عزل طبقة الإسناد افتراضياً person_layer='matn' ودعم المطابقة المطبّعة المرنة للألقاب والكنى)
        if person and person.strip():
            q_canon = _canonicalize_person_text(person)
            q_core_toks = _extract_person_core_tokens(person)
            q_core_stems = [arabic_light_stem(t) for t in q_core_toks if len(arabic_light_stem(t)) >= 2]
            layer_mode = (person_layer or "matn").strip().lower()

            sql = """
                SELECT pp.passage_id, pp.canonical_name AS pp_canon, pp.mentioned_name AS pp_ment,
                       pe.canonical_name AS pe_canon, pe.aliases_json AS pe_aliases
                FROM passage_persons pp
                LEFT JOIN persons pe ON pp.person_id = pe.person_id
            """
            params: List[Any] = []
            if layer_mode in ("matn", "isnad"):
                sql += " WHERE LOWER(COALESCE(pp.source_layer, 'matn')) = ?"
                params.append(layer_mode)

            matched_person_pids: Set[str] = set()
            for r in self.conn.execute(sql, params):
                combined_raw = " | ".join(
                    str(r[k] or "") for k in ("pp_canon", "pp_ment", "pe_canon", "pe_aliases")
                )
                rec_canon = _canonicalize_person_text(combined_raw)
                if not rec_canon:
                    continue
                if q_canon and q_canon in rec_canon:
                    matched_person_pids.add(str(r["passage_id"]))
                    continue
                rec_toks = set(re.findall(r"[\u0621-\u064A0-9]+", rec_canon))
                rec_stems = {arabic_light_stem(t) for t in rec_toks}
                if q_core_toks and all(
                    (ct in rec_canon or ct in rec_toks or arabic_light_stem(ct) in rec_stems)
                    for ct in q_core_toks
                ):
                    matched_person_pids.add(str(r["passage_id"]))
                elif q_core_stems and all(cs in rec_stems for cs in q_core_stems):
                    matched_person_pids.add(str(r["passage_id"]))

            candidates &= matched_person_pids

        # ب. فلتر المكان (مع دعم تجريد الألقاب الجغرافية مثل المكرمة/المنورة والمطابقة ثنائية الاتجاه)
        if place and place.strip():
            pl_norm = normalize_arabic_for_match(place)
            pl_toks = [t for t in re.findall(r"[\u0621-\u064A0-9]+", pl_norm) if len(t) >= 2]
            pl_core_toks = [t for t in pl_toks if t not in PLACE_EPITHET_STOPWORDS] or pl_toks
            pl_core_str = " ".join(pl_core_toks)

            sql = """
                SELECT ppl.passage_id, ppl.canonical_name AS ppl_canon, ppl.mentioned_name AS ppl_ment,
                       pl.canonical_name AS pl_canon, pl.aliases_json AS pl_aliases
                FROM passage_places ppl
                LEFT JOIN places pl ON ppl.place_id = pl.place_id
            """
            matched_place_pids: Set[str] = set()
            for r in self.conn.execute(sql):
                fields_norm = [
                    normalize_arabic_for_match(str(r[k] or ""))
                    for k in ("ppl_canon", "ppl_ment", "pl_canon", "pl_aliases")
                ]
                combined_pl = " | ".join(f for f in fields_norm if f)
                if not combined_pl:
                    continue
                if pl_norm in combined_pl or (pl_core_str and pl_core_str in combined_pl):
                    matched_place_pids.add(str(r["passage_id"]))
                    continue
                # مطابقة عكسية عندما يكون الاسم المخزن مختصراً (مثل "مكه" والفلتر "مكة المكرمة")
                rec_canon_pl = fields_norm[0] or fields_norm[2]
                if rec_canon_pl and len(rec_canon_pl) >= 3 and (
                    rec_canon_pl in pl_norm or arabic_light_stem(rec_canon_pl) in {arabic_light_stem(t) for t in pl_core_toks}
                ):
                    matched_place_pids.add(str(r["passage_id"]))

            candidates &= matched_place_pids

        # ج. فلتر التاريخ الهجري (مع اشتراط event_layer='historical' افتراضياً)
        if year_min is not None or year_max is not None:
            sql = "SELECT DISTINCT passage_id FROM events_chronology WHERE year_hijri IS NOT NULL"
            params = []
            if event_layer and event_layer.lower() != "any":
                sql += " AND LOWER(COALESCE(event_layer, 'historical')) = ?"
                params.append(event_layer.strip().lower())
            if year_min is not None:
                sql += " AND year_hijri >= ?"
                params.append(int(year_min))
            if year_max is not None:
                sql += " AND year_hijri <= ?"
                params.append(int(year_max))
            matched = {str(r["passage_id"]) for r in self.conn.execute(sql, params)}
            candidates &= matched

        # د. فلتر الشواهد القرآنية (--surah أو --ayah مثل 2:255 أو البقرة:255 أو ٢:٢٥٥)
        if surah is not None:
            sql = "SELECT DISTINCT passage_id FROM evidences WHERE surah_number = ?"
            matched = {str(r["passage_id"]) for r in self.conn.execute(sql, [int(surah)])}
            candidates &= matched

        if ayah and str(ayah).strip():
            ayah_s = str(ayah).strip().translate(DIGITS_MAP)
            ayah_s_clean = re.sub(r"^\s*(?:سورة|سوره)\s+", "", ayah_s).strip()
            s_num_resolved: Optional[int] = None
            a_start_resolved: Optional[int] = None
            a_end_resolved: Optional[int] = None

            if ":" in ayah_s_clean:
                s_part, a_part = ayah_s_clean.split(":", 1)
                s_part_str = s_part.strip()
                if s_part_str.isdigit():
                    s_num_resolved = int(s_part_str)
                else:
                    s_norm = normalize_arabic_for_match(s_part_str)
                    s_norm = re.sub(r"^(?:سوره|سورة)\s+", "", s_norm).strip()
                    s_num_resolved = SURAH_NAME_TO_NUMBER.get(s_norm)

                a_nums = [int(x) for x in re.findall(r"[0-9]+", a_part)]
                if a_nums:
                    a_start_resolved = a_nums[0]
                    a_end_resolved = a_nums[-1]
            else:
                a_nums = [int(x) for x in re.findall(r"[0-9]+", ayah_s_clean)]
                non_digit_part = normalize_arabic_for_match(re.sub(r"[0-9\-–:]+", " ", ayah_s_clean))
                non_digit_part = re.sub(r"^(?:سوره|سورة|ايه|آية)\s+", "", non_digit_part).strip()
                if non_digit_part and non_digit_part in SURAH_NAME_TO_NUMBER:
                    s_num_resolved = SURAH_NAME_TO_NUMBER[non_digit_part]
                if a_nums:
                    a_start_resolved = a_nums[0]
                    a_end_resolved = a_nums[-1]

            if s_num_resolved is not None and a_start_resolved is not None:
                canonical_key = f"{s_num_resolved}:{a_start_resolved}"
                a_end_val = a_end_resolved if a_end_resolved is not None else a_start_resolved
                sql = """
                    SELECT DISTINCT passage_id
                    FROM evidences
                    WHERE surah_ayah_key = ?
                       OR (
                           surah_number = ?
                           AND ayah_start IS NOT NULL
                           AND ayah_start <= ?
                           AND COALESCE(ayah_end, ayah_start) >= ?
                       )
                """
                matched = {
                    str(r["passage_id"])
                    for r in self.conn.execute(sql, [canonical_key, s_num_resolved, a_end_val, a_start_resolved])
                }
                candidates &= matched
            elif a_start_resolved is not None:
                sql = """
                    SELECT DISTINCT passage_id
                    FROM evidences
                    WHERE (ayah_start <= ? AND COALESCE(ayah_end, ayah_start) >= ?)
                       OR surah_ayah_key LIKE '%:' || ?
                """
                matched = {
                    str(r["passage_id"])
                    for r in self.conn.execute(sql, [a_start_resolved, a_start_resolved, str(a_start_resolved)])
                }
                candidates &= matched
            elif s_num_resolved is not None:
                sql = "SELECT DISTINCT passage_id FROM evidences WHERE surah_number = ?"
                matched = {str(r["passage_id"]) for r in self.conn.execute(sql, [s_num_resolved])}
                candidates &= matched
            else:
                candidates = set()

        # هـ. فلتر العلم الشرعي/المعرفي ونوع المصدر (--science و --source-type)
        if science and science.strip():
            sc_norm = science.strip().lower()
            sql = """
                SELECT DISTINCT p.passage_id
                FROM passages p
                LEFT JOIN sources s ON p.source_id = s.source_id
                LEFT JOIN series sr ON p.series_id = sr.series_id
                WHERE LOWER(COALESCE(s.science, '')) = ?
                   OR LOWER(COALESCE(sr.science, '')) = ?
            """
            matched = {str(r["passage_id"]) for r in self.conn.execute(sql, [sc_norm, sc_norm])}
            candidates &= matched

        if source_type and source_type.strip():
            st_norm = source_type.strip().lower()
            sql = """
                SELECT DISTINCT p.passage_id
                FROM passages p
                JOIN sources s ON p.source_id = s.source_id
                WHERE LOWER(COALESCE(s.source_type, '')) = ?
            """
            matched = {str(r["passage_id"]) for r in self.conn.execute(sql, [st_norm])}
            candidates &= matched

        # و. فلتر فقرة المتن المشروح (--matn-clause)
        if matn_clause and matn_clause.strip():
            mc = matn_clause.strip()
            sql = """
                SELECT DISTINCT passage_id
                FROM matn_triangulation
                WHERE LOWER(explained_matn_clause_id) = LOWER(?)
                UNION
                SELECT DISTINCT p_book.passage_id
                FROM matn_triangulation mt
                JOIN passages p_book ON p_book.source_id = mt.explained_matn_book_id
                WHERE LOWER(mt.explained_matn_clause_id) = LOWER(?)
                  AND mt.explained_matn_verbatim IS NOT NULL
                  AND LENGTH(TRIM(mt.explained_matn_verbatim)) > 0
                  AND NORM_AR(p_book.raw_text) LIKE '%' || NORM_AR(mt.explained_matn_verbatim) || '%'
            """
            matched = {str(r[0]) for r in self.conn.execute(sql, [mc, mc])}
            candidates &= matched

        return candidates

    # -----------------------------------------------------------------------
    # 2. البحث النصي الحرفي عبر FTS5 BM25 (passages_fts)
    # -----------------------------------------------------------------------
    def _score_fts5(self, query: str, candidate_pids: Set[str]) -> Dict[str, float]:
        """
        يستعلم من جدول passages_fts باستخدام BM25 مع:
        1. عزل أدوات الاستفهام والكلمات القالبية العامة (مثل: هل، ما حكم، مسألة، ضابط، يجوز) عن التطابق العشوائي.
        2. توليد مجموعات البدائل الإملائية والصرفية (الهمزات أ/إ/آ/ا، التاء المربوطة ة/ه، الياء ى/ي، وبادئات الجذوع "stem"*).
        3. تعزيز التطابق المعجمي والجذعي المطبّع في العنوان والمتن والملخص المنقى.
        """
        if not query or not query.strip() or not candidate_pids:
            return {}

        all_query_tokens = [
            tok for tok in re.findall(r"[\u0621-\u064A0-9A-Za-z]+", query)
            if len(tok) >= 2 and normalize_arabic_for_match(tok) not in ARABIC_STOPWORDS_NORM
        ]
        if not all_query_tokens:
            all_query_tokens = [
                tok for tok in re.findall(r"[\u0621-\u064A0-9A-Za-z]+", query) if len(tok) >= 2
            ]
        if not all_query_tokens:
            return {}

        core_tokens = [
            tok for tok in all_query_tokens
            if normalize_arabic_for_match(tok) not in QUERY_FRAMING_STOPWORDS_NORM
        ]
        if not core_tokens:
            core_tokens = all_query_tokens

        raw_scores: Dict[str, float] = {}
        fts_groups = [g for g in (_fts_orthographic_group(t) for t in core_tokens) if g]

        if fts_groups:
            and_expr = " AND ".join(fts_groups)
            or_expr = " OR ".join(fts_groups)

            for mult, fts_expr in ((1.60, and_expr), (0.85, or_expr)):
                try:
                    rows = self.conn.execute(
                        """
                        SELECT passage_id, bm25(passages_fts) AS b_score
                        FROM passages_fts
                        WHERE passages_fts MATCH ?
                        """,
                        (fts_expr,),
                    ).fetchall()
                    for r in rows:
                        pid = str(r["passage_id"])
                        if pid in candidate_pids:
                            val = abs(float(r["b_score"])) * mult
                            if val > raw_scores.get(pid, 0.0):
                                raw_scores[pid] = val
                except sqlite3.OperationalError:
                    pass

        # 2. تعزيز التطابق المعجمي والجذعي المطبّع (لمعالجة اختلاف الهمزات والتصريف والمشتقات في العربية)
        q_norm = normalize_arabic_for_match(query)
        norm_core_tokens = [
            normalize_arabic_for_match(t) for t in core_tokens
            if len(normalize_arabic_for_match(t)) >= 2
        ]
        core_stems = [arabic_light_stem(nt) for nt in norm_core_tokens]
        core_skels = [arabic_consonant_skeleton(st) for st in core_stems]

        # تحديد العناقيد الدلالية النشطة في الاستعلام لدعم الترادف المباشر (مثل علاج <-> داووا)
        q_tok_set = set(norm_core_tokens) | set(core_stems)
        active_cluster_kws: Set[str] = set()
        for _, kws in CONCEPT_SYNONYM_CLUSTERS:
            kws_norm = [normalize_arabic_for_match(k) for k in kws]
            if any((kn in q_tok_set or arabic_light_stem(kn) in q_tok_set) for kn in kws_norm if " " not in kn):
                for kn in kws_norm:
                    if " " not in kn:
                        active_cluster_kws.add(arabic_light_stem(kn))

        if norm_core_tokens:
            placeholders = ",".join("?" for _ in candidate_pids)
            rows = self.conn.execute(
                f"""
                SELECT passage_id, sub_heading, clean_matn, raw_text, summary, topics_json, search_queries_json
                FROM passages
                WHERE passage_id IN ({placeholders})
                """,
                list(candidate_pids),
            ).fetchall()

            for r in rows:
                pid = str(r["passage_id"])
                primary_raw = " ".join(str(r[k] or "") for k in ("sub_heading", "clean_matn", "raw_text"))
                secondary_raw = " ".join(str(r[k] or "") for k in ("summary", "topics_json", "search_queries_json"))
                for bp_re in BOILERPLATE_CLEAN_RES:
                    primary_raw = bp_re.sub(" ", primary_raw)
                    secondary_raw = bp_re.sub(" ", secondary_raw)

                prim_norm = normalize_arabic_for_match(primary_raw)
                sec_norm = normalize_arabic_for_match(secondary_raw)
                doc_norm = f"{prim_norm} {sec_norm}".strip()

                prim_words = set(re.findall(r"[\u0621-\u064A0-9]+", prim_norm))
                all_words = prim_words | set(re.findall(r"[\u0621-\u064A0-9]+", sec_norm))
                prim_stems = {arabic_light_stem(w) for w in prim_words}
                all_stems = prim_stems | {arabic_light_stem(w) for w in all_words}
                all_skels = {arabic_consonant_skeleton(st) for st in all_stems if len(st) >= 3}

                matched_weight = 0.0
                matched_tokens_count = 0
                for idx_t, nt in enumerate(norm_core_tokens):
                    st = core_stems[idx_t]
                    sk = core_skels[idx_t]
                    if nt in prim_words or nt in prim_norm:
                        matched_weight += 3.2
                        matched_tokens_count += 1
                    elif len(st) >= 3 and st in prim_stems:
                        matched_weight += 2.7
                        matched_tokens_count += 1
                    elif nt in all_words or nt in doc_norm:
                        matched_weight += 2.0
                        matched_tokens_count += 1
                    elif len(st) >= 3 and st in all_stems:
                        matched_weight += 1.7
                        matched_tokens_count += 1
                    elif len(sk) >= 3 and sk in all_skels:
                        matched_weight += 1.1
                        matched_tokens_count += 1

                if matched_tokens_count > 0:
                    coverage_ratio = matched_tokens_count / len(norm_core_tokens)
                    phrase_bonus = 3.5 if (len(q_norm) >= 6 and q_norm in doc_norm) else 0.0
                    all_match_bonus = 3.0 if matched_tokens_count == len(norm_core_tokens) and len(norm_core_tokens) >= 2 else 0.0
                    syn_bonus = 1.2 if (active_cluster_kws and (prim_stems & active_cluster_kws)) else 0.0
                    lex_score = (matched_weight * (0.6 + 0.8 * coverage_ratio)) + phrase_bonus + all_match_bonus + syn_bonus
                    raw_scores[pid] = raw_scores.get(pid, 0.0) + lex_score
                else:
                    # إذا لم يطابق المقطع أي كلمة موضوعية جوهرية، نصفر درجته المعجمية لمنع تسرب الكلمات العامة
                    raw_scores.pop(pid, None)

        if not raw_scores:
            return {}

        max_s = max(raw_scores.values())
        if max_s <= 1e-12:
            return {k: 0.0 for k in raw_scores}
        return {k: float(v / max_s) for k, v in raw_scores.items()}

    # -----------------------------------------------------------------------
    # 3. البحث الهجين المزدوج + RRF + إثراء النتائج
    # -----------------------------------------------------------------------
    def search(
        self,
        query: str = "",
        top_k: int = 5,
        mode: str = "hybrid",
        alpha_matn: Optional[float] = None,
        alpha_concept: Optional[float] = None,
        alpha_fts: Optional[float] = None,
        rrf_k: int = 60,
        person: Optional[str] = None,
        person_layer: str = "matn",
        place: Optional[str] = None,
        year_min: Optional[int] = None,
        year_max: Optional[int] = None,
        event_layer: str = "historical",
        surah: Optional[int] = None,
        ayah: Optional[str] = None,
        science: Optional[str] = None,
        source_type: Optional[str] = None,
        matn_clause: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        ينفذ الاسترجاع الهجين الكامل ويعيد قائمة النتائج المثرية بجميع البيانات والتوقيتات والكيانات.
        """
        # تحديد أوزان الدمج حسب الوضع أو الخيارات الصريحة
        mode_clean = (mode or "hybrid").strip().lower()
        if mode_clean == "matn":
            w_matn = 1.0 if alpha_matn is None else float(alpha_matn)
            w_concept = 0.0 if alpha_concept is None else float(alpha_concept)
            w_fts = 0.0 if alpha_fts is None else float(alpha_fts)
        elif mode_clean == "concept":
            w_matn = 0.0 if alpha_matn is None else float(alpha_matn)
            w_concept = 1.0 if alpha_concept is None else float(alpha_concept)
            w_fts = 0.0 if alpha_fts is None else float(alpha_fts)
        elif mode_clean == "fts":
            w_matn = 0.0 if alpha_matn is None else float(alpha_matn)
            w_concept = 0.0 if alpha_concept is None else float(alpha_concept)
            w_fts = 1.0 if alpha_fts is None else float(alpha_fts)
        else:
            w_matn = 0.35 if alpha_matn is None else float(alpha_matn)
            w_concept = 0.45 if alpha_concept is None else float(alpha_concept)
            w_fts = 0.20 if alpha_fts is None else float(alpha_fts)

        candidate_pids = self.resolve_candidate_passage_ids(
            person=person,
            person_layer=person_layer,
            place=place,
            year_min=year_min,
            year_max=year_max,
            event_layer=event_layer,
            surah=surah,
            ayah=ayah,
            science=science,
            source_type=source_type,
            matn_clause=matn_clause,
        )
        if not candidate_pids:
            return []

        placeholders = ",".join("?" for _ in candidate_pids)
        emb_rows = self.conn.execute(
            f"""
            SELECT passage_id, dim, vec_matn_blob, vec_concept_blob
            FROM passage_embeddings
            WHERE passage_id IN ({placeholders})
            ORDER BY passage_id
            """,
            list(candidate_pids),
        ).fetchall()

        pid_list = [str(r["passage_id"]) for r in emb_rows]
        if not pid_list:
            return []

        if query and query.strip():
            q_vec = self.embedder.embed_query(query)
            matn_mat = np.stack([blob_to_vector(r["vec_matn_blob"], self.dim) for r in emb_rows], axis=0)
            concept_mat = np.stack([blob_to_vector(r["vec_concept_blob"], self.dim) for r in emb_rows], axis=0)

            raw_sim_matn = _compute_cosine_scores(matn_mat, q_vec, use_mps=self.use_mps)
            raw_sim_concept = _compute_cosine_scores(concept_mat, q_vec, use_mps=self.use_mps)

            scores_matn = {pid: float(max(0.0, raw_sim_matn[i])) for i, pid in enumerate(pid_list)}
            scores_concept = {pid: float(max(0.0, raw_sim_concept[i])) for i, pid in enumerate(pid_list)}
            scores_fts = self._score_fts5(query, candidate_pids)

            # حساب رتب القنوات الثلاث لدمج RRF
            sorted_by_matn = sorted(pid_list, key=lambda p: scores_matn.get(p, 0.0), reverse=True)
            sorted_by_concept = sorted(pid_list, key=lambda p: scores_concept.get(p, 0.0), reverse=True)
            sorted_by_fts = sorted(
                [p for p in pid_list if scores_fts.get(p, 0.0) > 0.0],
                key=lambda p: scores_fts.get(p, 0.0),
                reverse=True,
            )

            rank_matn = {p: idx + 1 for idx, p in enumerate(sorted_by_matn)}
            rank_concept = {p: idx + 1 for idx, p in enumerate(sorted_by_concept)}
            rank_fts = {p: idx + 1 for idx, p in enumerate(sorted_by_fts)}

            scored_items: List[Tuple[str, float, Dict[str, Any]]] = []
            for pid in pid_list:
                s_m = scores_matn.get(pid, 0.0)
                s_c = scores_concept.get(pid, 0.0)
                s_f = scores_fts.get(pid, 0.0)

                r_m = rank_matn[pid]
                r_c = rank_concept[pid]
                r_f = rank_fts.get(pid)

                rrf_m = 1.0 / (rrf_k + r_m) if s_m > 0 else 0.0
                rrf_c = 1.0 / (rrf_k + r_c) if s_c > 0 else 0.0
                rrf_f = (1.0 / (rrf_k + r_f)) if (r_f is not None and s_f > 0) else 0.0

                rrf_total = (w_matn * rrf_m) + (w_concept * rrf_c) + (w_fts * rrf_f)
                weighted_linear = (w_matn * s_m) + (w_concept * s_c) + (w_fts * s_f)
                hybrid_score = (0.70 * weighted_linear) + (0.30 * rrf_k * rrf_total)

                dominant_channel = "matn" if s_m >= s_c else "concept"
                scored_items.append(
                    (
                        pid,
                        float(hybrid_score),
                        {
                            "hybrid_score": round(float(hybrid_score), 6),
                            "score_matn": round(float(s_m), 6),
                            "score_concept": round(float(s_c), 6),
                            "score_fts": round(float(s_f), 6),
                            "rrf_score": round(float(rrf_total), 6),
                            "rank_matn": r_m,
                            "rank_concept": r_c,
                            "rank_fts": r_f,
                            "dominant_channel": dominant_channel,
                        },
                    )
                )

            scored_items.sort(key=lambda x: x[1], reverse=True)
            top_items = scored_items[: max(1, int(top_k))]
        else:
            # استعلام فلاتر علائقية خالص بدون نص بحث
            top_items = [
                (
                    pid,
                    1.0,
                    {
                        "hybrid_score": 1.0,
                        "score_matn": 0.0,
                        "score_concept": 0.0,
                        "score_fts": 0.0,
                        "rrf_score": 0.0,
                        "rank_matn": idx + 1,
                        "rank_concept": idx + 1,
                        "rank_fts": None,
                        "dominant_channel": "entity_filter",
                    },
                )
                for idx, pid in enumerate(pid_list[: max(1, int(top_k))])
            ]

        return [self._hydrate_passage_result(pid, score_meta) for pid, _, score_meta in top_items]

    def search_gems(
        self,
        query: str,
        top_k: int = 5,
        mode: str = "hybrid",
        alpha_matn: float = 0.45,
        alpha_concept: float = 0.55,
    ) -> List[Dict[str, Any]]:
        """يبحث مباشرة في جدول gem_embeddings (متجه لفظ القاعدة التراثي + متجه القاعدة المصقولة)."""
        rows = self.conn.execute(
            """
            SELECT ge.gem_id, ge.passage_id, ge.dim, ge.vec_matn_blob, ge.vec_concept_blob,
                   sg.source_id, sg.part_number, sg.title, sg.category,
                   sg.verbatim_rule, sg.polished_rule, sg.explanation,
                   sg.start_sec, sg.end_sec, sg.youtube_timestamp_url
            FROM gem_embeddings ge
            JOIN science_gems sg ON ge.gem_id = sg.gem_id
            ORDER BY ge.gem_id
            """
        ).fetchall()
        if not rows:
            return []

        q_vec = self.embedder.embed_query(query)
        matn_mat = np.stack([blob_to_vector(r["vec_matn_blob"], self.dim) for r in rows], axis=0)
        concept_mat = np.stack([blob_to_vector(r["vec_concept_blob"], self.dim) for r in rows], axis=0)

        s_matn = _compute_cosine_scores(matn_mat, q_vec, use_mps=self.use_mps)
        s_conc = _compute_cosine_scores(concept_mat, q_vec, use_mps=self.use_mps)

        m_clean = (mode or "hybrid").strip().lower()
        if m_clean == "matn":
            w_m, w_c = 1.0, 0.0
        elif m_clean == "concept":
            w_m, w_c = 0.0, 1.0
        else:
            w_m, w_c = float(alpha_matn), float(alpha_concept)

        results: List[Dict[str, Any]] = []
        for idx, r in enumerate(rows):
            sm = float(max(0.0, s_matn[idx]))
            sc = float(max(0.0, s_conc[idx]))
            comb = w_m * sm + w_c * sc
            item = dict(r)
            item.pop("vec_matn_blob", None)
            item.pop("vec_concept_blob", None)
            item["score_matn"] = round(sm, 6)
            item["score_concept"] = round(sc, 6)
            item["hybrid_score"] = round(comb, 6)
            item["dominant_channel"] = "matn" if sm >= sc else "concept"
            results.append(item)

        results.sort(key=lambda x: x["hybrid_score"], reverse=True)
        return results[: max(1, int(top_k))]

    def _hydrate_passage_result(self, passage_id: str, score_meta: Dict[str, Any]) -> Dict[str, Any]:
        """يجمع كافة بيانات المقطع، المصدر، القواعد، التوقيتات، والكيانات المطابقة."""
        p_row = self.conn.execute(
            """
            SELECT p.*,
                   s.source_type, s.title AS source_title, s.author_or_sheikh, s.science, s.archetype
            FROM passages p
            LEFT JOIN sources s ON p.source_id = s.source_id
            WHERE p.passage_id = ?
            """,
            (passage_id,),
        ).fetchone()
        if not p_row:
            return {"passage_id": passage_id, **score_meta}

        p_dict = dict(p_row)
        for j_col, out_col in (("topics_json", "topics"), ("search_queries_json", "search_queries")):
            raw_v = p_dict.get(j_col)
            try:
                p_dict[out_col] = json.loads(raw_v) if raw_v else []
            except Exception:
                p_dict[out_col] = []

        # القواعد المستخرجة (science_gems)
        gems = [
            dict(r)
            for r in self.conn.execute(
                """
                SELECT gem_id, title, category, verbatim_rule, polished_rule,
                       explanation, start_sec, end_sec, youtube_timestamp_url
                FROM science_gems
                WHERE passage_id = ?
                ORDER BY gem_id
                """,
                (passage_id,),
            )
        ]

        # الأعلام (passage_persons)
        persons = [
            dict(r)
            for r in self.conn.execute(
                """
                SELECT person_id, mentioned_name, canonical_name, source_layer, role
                FROM passage_persons
                WHERE passage_id = ?
                ORDER BY id
                """,
                (passage_id,),
            )
        ]

        # الأماكن (passage_places)
        places = [
            dict(r)
            for r in self.conn.execute(
                """
                SELECT place_id, mentioned_name, canonical_name
                FROM passage_places
                WHERE passage_id = ?
                ORDER BY id
                """,
                (passage_id,),
            )
        ]

        # التواريخ (events_chronology)
        events = [
            dict(r)
            for r in self.conn.execute(
                """
                SELECT event_id, year_hijri, year_raw, is_approximate, event_title, event_layer
                FROM events_chronology
                WHERE passage_id = ?
                ORDER BY year_hijri
                """,
                (passage_id,),
            )
        ]

        # الشواهد القرآنية والحديثية (evidences)
        evidences = [
            dict(r)
            for r in self.conn.execute(
                """
                SELECT evidence_id, evidence_type, surah_number, ayah_start, ayah_end,
                       surah_ayah_key, verbatim_text, hadith_source, footnote_ref
                FROM evidences
                WHERE passage_id = ?
                ORDER BY evidence_id
                """,
                (passage_id,),
            )
        ]

        # تثليث المتون (matn_triangulation)
        triangulations = [
            dict(r)
            for r in self.conn.execute(
                """
                SELECT triangulation_id, explained_matn_book_id, explained_matn_clause_id,
                       explained_matn_verbatim, start_sec, end_sec
                FROM matn_triangulation
                WHERE passage_id = ?
                ORDER BY triangulation_id
                """,
                (passage_id,),
            )
        ]

        return {
            "passage_id": p_dict["passage_id"],
            "source_id": p_dict.get("source_id"),
            "series_id": p_dict.get("series_id"),
            "part_id": p_dict.get("part_id"),
            "part_number": p_dict.get("part_number"),
            "passage_index": p_dict.get("passage_index"),
            "source_type": p_dict.get("source_type"),
            "source_title": p_dict.get("source_title"),
            "author_or_sheikh": p_dict.get("author_or_sheikh"),
            "science": p_dict.get("science"),
            "sub_heading": p_dict.get("sub_heading"),
            "raw_text": p_dict.get("raw_text"),
            "clean_matn": p_dict.get("clean_matn"),
            "isnad_prefix": p_dict.get("isnad_prefix"),
            "summary": p_dict.get("summary"),
            "topics": p_dict.get("topics", []),
            "search_queries": p_dict.get("search_queries", []),
            "start_sec": p_dict.get("start_sec"),
            "end_sec": p_dict.get("end_sec"),
            "youtube_timestamp_url": p_dict.get("youtube_timestamp_url"),
            "page_num": p_dict.get("page_num"),
            "science_gems": gems,
            "persons": persons,
            "places": places,
            "events_chronology": events,
            "evidences": evidences,
            "matn_triangulation": triangulations,
            **score_meta,
        }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="محرك الاسترجاع الهجين العلائقي (FTS5 BM25 + Dual EmbeddingGemma 2 + RRF + Entity Filters)."
    )
    parser.add_argument("--db", "--db-path", dest="db", required=True, help="مسار ملف قاعدة بيانات SQLite")
    parser.add_argument("--query", default="", help="نص البحث (عبارة تراثية أو سؤال مفهومي)")
    parser.add_argument("--top-k", type=int, default=5, help="عدد النتائج المسترجعة")
    parser.add_argument(
        "--mode",
        default="hybrid",
        choices=["hybrid", "matn", "concept", "fts"],
        help="وضع البحث (الافتراضي: hybrid)",
    )
    parser.add_argument("--alpha-matn", type=float, default=None, help="وزن متجه المتن vec_matn")
    parser.add_argument("--alpha-concept", type=float, default=None, help="وزن متجه المفهوم vec_concept")
    parser.add_argument("--alpha-fts", type=float, default=None, help="وزن البحث المعجمي FTS5 BM25")
    parser.add_argument("--person", default=None, help="فلترة باسم العلم")
    parser.add_argument(
        "--person-layer",
        default="matn",
        choices=["matn", "isnad", "any"],
        help="طبقة ورود العلم (الافتراضي: matn لمنع التلوث برواة السند)",
    )
    parser.add_argument("--place", default=None, help="فلترة باسم المكان")
    parser.add_argument("--year-min", type=int, default=None, help="الحد الأدنى للسنة الهجرية")
    parser.add_argument("--year-max", type=int, default=None, help="الحد الأعلى للسنة الهجرية")
    parser.add_argument("--surah", type=int, default=None, help="فلترة برقم السورة القرآنية")
    parser.add_argument("--ayah", default=None, help="فلترة بمفتاح الآية (مثل 2:255)")
    parser.add_argument("--science", default=None, help="فلترة بالعلم (مثل maliki, akida, ossoul)")
    parser.add_argument("--source-type", default=None, help="فلترة بنوع المصدر (book, lecture, course)")
    parser.add_argument("--matn-clause", default=None, help="فلترة بمعرف فقرة المتن المشروح (مثل UB:2)")
    parser.add_argument(
        "--backend",
        default="auto",
        choices=["auto", "ollama", "sentence-transformers", "genai", "deterministic-arabic-mps"],
        help="محرك التضمين المستخدم",
    )

    args = parser.parse_args(argv)
    with HybridSearchEngine(db_path=args.db, backend=args.backend) as engine:
        results = engine.search(
            query=args.query,
            top_k=args.top_k,
            mode=args.mode,
            alpha_matn=args.alpha_matn,
            alpha_concept=args.alpha_concept,
            alpha_fts=args.alpha_fts,
            person=args.person,
            person_layer=args.person_layer,
            place=args.place,
            year_min=args.year_min,
            year_max=args.year_max,
            surah=args.surah,
            ayah=args.ayah,
            science=args.science,
            source_type=args.source_type,
            matn_clause=args.matn_clause,
        )
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
