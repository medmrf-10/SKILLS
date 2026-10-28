#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
النواة الهندسية المطهرة لتنظيف النصوص التراثية وفهرستها في SQLite FTS5 مع التضمين المحلي الصريح
(Turath Text Hygiene, Isnad/Matn Splitter, SQLite FTS5 + float32 BLOB, RRF, and Strict LocalModelEmbedder).
"""

from __future__ import annotations

import argparse
import re
import sqlite3
import sys
import unicodedata
from pathlib import Path
from typing import Dict, Optional, Sequence, Tuple

import numpy as np

# 1. خريطة تفكيك الرموز التراثية المدمجة ومحارف الاتجاه الخفية
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
    "\ufdfd": " بسم الله الرحمن الرحيم ",
    "\ufdfe": " سبحانه وتعالى ",
    "\ufdff": " عز وجل ",
}

HONORIFIC_RANGE_RE = re.compile(r"[\ufd40-\ufd4f\ufdfa-\ufdff]")
INVISIBLE_DIRECTIONAL_RE = re.compile(r"[\u200e\u200f\u061c\ufeff\u202a-\u202e\u2066-\u2069]")
TASHKEEL_RE = re.compile(r"[\u0617-\u061a\u064b-\u065f\u0670\u06d6-\u06ed]")
EASTERN_DIGITS_MAP = str.maketrans("\u0660\u0661\u0662\u0663\u0664\u0665\u0666\u0667\u0668\u0669", "0123456789")

PAGE_AND_FOOTNOTE_RE = re.compile(
    r"\[\s*(?:ص|صفحة|صـ)\s*:?\s*[\u0660-\u06690-9]{1,5}(?:\s*[-–/]\s*[\u0660-\u06690-9]{1,5})?\s*\]"
    r"|⦗[^⦘\n]{1,25}⦘"
    r"|\(\s*¬\s*[\u0660-\u06690-9]+\s*\)"
)

LEADING_ISNAD_CHAIN_RE = re.compile(
    r"^\s*(?:(?:\[ح\]|\(ح\)|ح)\s+)?"
    r"(?:و?(?:حدثنا|حدثني|أخبرنا|أخبرني|أنبأنا|أنبأني|ثنا|نا|سمعت|روينا|روي لنا|وبه حدثنا|وبه ثنا)\b"
    r"[^:。\n]{5,320}?(?:قال|قالت|يقول|أنه قال|أنها قالت)\s*:\s*)+"
)


def expand_honorific_ligatures(text: str) -> str:
    """توسيع الرموز التراثية المدمجة في يونيكود إلى عباراتها العربية الصريحة."""
    if not text:
        return ""
    out = text
    for lig, phrase in HONORIFIC_LIGATURE_MAP.items():
        if lig in out:
            out = out.replace(lig, phrase)
    return HONORIFIC_RANGE_RE.sub(" ", out)


def clean_hygienic_arabic_text(
    text: str,
    unicode_form: str = "NFKC",
    strip_tashkeel: bool = False,
    strip_page_markers: bool = True,
) -> str:
    """تطهير النص التراثي من محارف الاتجاه الخفية وتوسيع الرموز المدمجة وتطبيع NFC/NFKC."""
    if not text:
        return ""
    if unicode_form not in ("NFC", "NFKC"):
        raise ValueError(f"Unsupported unicode_form: {unicode_form}")

    s = INVISIBLE_DIRECTIONAL_RE.sub("", text)
    s = expand_honorific_ligatures(s)
    s = unicodedata.normalize(unicode_form, s)
    s = s.replace("\u0640", "").translate(EASTERN_DIGITS_MAP)

    if strip_page_markers:
        s = PAGE_AND_FOOTNOTE_RE.sub(" ", s)
    if strip_tashkeel:
        s = TASHKEEL_RE.sub("", s)

    s = re.sub(r"\s+([،.؛:؟!])", r"\1", s)
    return re.sub(r"\s+", " ", s).strip()


def split_isnad_and_matn(text: str) -> Tuple[str, str]:
    """فصل سلسلة الإسناد الابتدائية عن متن الخبر لمنع تشويش أسماء الرواة على البحث الدلالي."""
    cleaned = clean_hygienic_arabic_text(text, unicode_form="NFKC", strip_tashkeel=False)
    if not cleaned:
        return ("", "")
    match = LEADING_ISNAD_CHAIN_RE.match(cleaned)
    if not match:
        return ("", cleaned)
    isnad_prefix = match.group(0).strip()
    clean_matn = cleaned[match.end():].strip()
    return (isnad_prefix, clean_matn) if clean_matn else ("", cleaned)


# 2. ترميز المتجهات بصيغة float32 BLOB وفحص سلامتها رياضياً
def vector_to_f32_blob(vec: Sequence[float] | np.ndarray, normalize_l2: bool = True) -> bytes:
    """تحويل المتجه إلى float32 BLOB مع فحص الخلو من NaN/Inf والتطبيع الرياضي L2."""
    arr = np.asarray(vec, dtype=np.float32).reshape(-1)
    if arr.size == 0:
        raise ValueError("Empty embedding vector is not allowed.")
    if not np.all(np.isfinite(arr)):
        raise ValueError("Embedding vector contains NaN or Inf values.")
    if normalize_l2:
        norm = float(np.linalg.norm(arr))
        if norm <= 1e-12:
            raise ValueError("Zero-norm embedding vector cannot be L2-normalized.")
        arr = (arr / norm).astype(np.float32)
    return arr.tobytes()


def f32_blob_to_vector(blob: bytes) -> np.ndarray:
    """استرجاع متجه float32 من حقل BLOB في SQLite."""
    arr = np.frombuffer(blob, dtype=np.float32)
    if not np.all(np.isfinite(arr)):
        raise ValueError("Stored BLOB vector contains NaN or Inf values.")
    return arr


# 3. بناء جداول SQLite مع فهرس FTS5 النصي ودالة Reciprocal Rank Fusion (RRF)
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS passages (
    passage_id TEXT PRIMARY KEY,
    book_title TEXT NOT NULL DEFAULT '',
    author_info TEXT NOT NULL DEFAULT '',
    chapter_path TEXT NOT NULL DEFAULT '',
    source_text TEXT NOT NULL,
    content TEXT NOT NULL,
    isnad_prefix TEXT NOT NULL DEFAULT '',
    clean_matn TEXT NOT NULL,
    embedding_input TEXT NOT NULL,
    model_name TEXT,
    dim INTEGER,
    vec_matn_blob BLOB
);

CREATE VIRTUAL TABLE IF NOT EXISTS passages_fts USING fts5(
    passage_id UNINDEXED,
    clean_matn,
    content,
    tokenize='unicode61'
);
"""


def init_sqlite_fts_and_vectors(conn: sqlite3.Connection) -> None:
    """إنشاء جدول المقاطع مع عمود متجهات float32 BLOB وفهرس FTS5 النصي."""
    conn.executescript(SCHEMA_SQL)
    conn.commit()


def compute_rrf_scores(
    ranked_lists: Dict[str, Sequence[str]],
    weights: Optional[Dict[str, float]] = None,
    k: int = 60,
) -> Dict[str, float]:
    """حساب درجات دمج الترتيب التبادلي Reciprocal Rank Fusion (RRF)."""
    if k <= 0:
        raise ValueError("RRF constant k must be positive.")
    scores: Dict[str, float] = {}
    for channel, doc_ids in ranked_lists.items():
        w = 1.0 if weights is None else float(weights.get(channel, 1.0))
        if w <= 0.0:
            continue
        for idx, doc_id in enumerate(doc_ids, start=1):
            scores[doc_id] = scores.get(doc_id, 0.0) + (w / float(k + idx))
    return dict(sorted(scores.items(), key=lambda kv: kv[1], reverse=True))


# 4. واجهة التضمين المحلي الصريحة (LocalModelEmbedder) بدون أي بدائل وهمية أو سحابية
class LocalModelEmbedder:
    """
    واجهة تضمين محلي صريحة تشترط مسار نموذج محلي حقيقي (sentence-transformers أو mlx)
    وترفع RuntimeError صريحاً عند عدم توفر النموذج المحلي أو المكتبة.
    """

    def __init__(self, model_path: str | Path, backend: str = "sentence-transformers") -> None:
        self.model_path = Path(model_path).expanduser().resolve()
        self.backend = backend.strip().lower()
        if self.backend not in ("sentence-transformers", "mlx"):
            raise RuntimeError(
                f"Unsupported local backend '{self.backend}'. Only 'sentence-transformers' or 'mlx' are permitted."
            )
        if not self.model_path.exists():
            raise RuntimeError(
                f"Local embedding model path does not exist on disk: {self.model_path}. "
                "Fake SHA-256 fallback and external API keys are strictly prohibited."
            )
        self._model = self._load_local_model()

    def _load_local_model(self) -> object:
        if self.backend == "sentence-transformers":
            try:
                from sentence_transformers import SentenceTransformer  # type: ignore
            except ImportError as exc:
                raise RuntimeError("Local library 'sentence-transformers' is not installed.") from exc
            return SentenceTransformer(str(self.model_path), local_files_only=True)
        try:
            import mlx.core as _mx  # type: ignore  # noqa: F401
        except ImportError as exc:
            raise RuntimeError("Local library 'mlx' is not installed on this Apple Silicon system.") from exc
        return {"mlx_model_path": str(self.model_path)}

    def encode(self, texts: Sequence[str], batch_size: int = 32) -> np.ndarray:
        if not texts:
            return np.zeros((0, 0), dtype=np.float32)
        if self.backend == "sentence-transformers":
            vecs = self._model.encode(  # type: ignore[attr-defined]
                list(texts),
                batch_size=batch_size,
                normalize_embeddings=True,
                convert_to_numpy=True,
                show_progress_bar=False,
            )
            arr = np.asarray(vecs, dtype=np.float32)
            if not np.all(np.isfinite(arr)):
                raise RuntimeError("Local model produced NaN or Inf values.")
            return arr
        raise RuntimeError(f"MLX model verified at {self.model_path}, custom encoder forward required.")


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="النواة المطهرة لتنظيف النصوص التراثية وفصل الإسناد وفهرسة SQLite FTS5 ودمج RRF والتضمين المحلي الصريح."
    )
    parser.add_argument("--init-db", type=Path, help="إنشاء جداول passages و passages_fts في ملف SQLite محدد.")
    parser.add_argument("--sample-text", type=str, help="تطهير نص تراثي وفصل الإسناد عن المتن وعرض النتيجة.")
    parser.add_argument("--model-path", type=Path, help="مسار النموذج المحلي الصريح عند طلب التحقق من LocalModelEmbedder.")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    if args.init_db:
        with sqlite3.connect(str(args.init_db)) as conn:
            init_sqlite_fts_and_vectors(conn)
        print(f"Initialized SQLite FTS5 + float32 BLOB schema at: {args.init_db}")
    if args.sample_text:
        isnad, matn = split_isnad_and_matn(args.sample_text)
        print(f"ISNAD: {isnad}\nMATN : {matn}")
    if args.model_path:
        embedder = LocalModelEmbedder(args.model_path)
        print(f"Verified LocalModelEmbedder at: {embedder.model_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
