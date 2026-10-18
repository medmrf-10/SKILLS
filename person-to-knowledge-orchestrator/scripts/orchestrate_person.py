#!/usr/bin/env python3
"""Master End-to-End Orchestrator: Person to Unified Knowledge Database (USDB v5.7).

Executes the 6-stage deterministic pipeline with strict Hard Verification Gates (G0..G5):
  - Stage 0 (G0): Quota & Lean CLI Guard (agy-lean-cli)
  - Stage 1 (G1): Multi-Source Discovery Intake (person-discovery-intake)
  - Stage 2 (G2): Automated 9-Stage Curation (sheikh-curation v2.0)
  - Stage 3 (G3): Dual-Track Extraction (sheikh-series-pipeline v5.0 + turath-pdf-to-text v2.0)
  - Stage 4 (G4): Unified Deep Indexing & Entity DB (turath-deep-indexing v5.7 + turath-entity-db)
  - Stage 5 (G5): Dual-Vector Gemma-2 Embedding & Hybrid Search (turath-embedding-gemma2)
"""

from __future__ import annotations

import argparse
import datetime
import json
import math
import os
import re
import shutil
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Resolve sibling skill script directories
SKILLS_ROOT = Path(__file__).resolve().parents[2]
AGY_LEAN_SCRIPTS = SKILLS_ROOT / "agy-lean-cli" / "scripts"
DISCOVERY_SCRIPTS = SKILLS_ROOT / "person-discovery-intake" / "scripts"
CURATION_SCRIPTS = SKILLS_ROOT / "sheikh-curation" / "scripts"
SERIES_PIPELINE_SCRIPTS = SKILLS_ROOT / "sheikh-series-pipeline" / "scripts"
PDF_TO_TEXT_SCRIPTS = SKILLS_ROOT / "turath-pdf-to-text" / "scripts"
DEEP_INDEXING_SCRIPTS = SKILLS_ROOT / "turath-deep-indexing" / "scripts"
EMBEDDING_SCRIPTS = SKILLS_ROOT / "turath-embedding-gemma2" / "scripts"

for _script_dir in (
    AGY_LEAN_SCRIPTS,
    DISCOVERY_SCRIPTS,
    CURATION_SCRIPTS,
    SERIES_PIPELINE_SCRIPTS,
    PDF_TO_TEXT_SCRIPTS,
    DEEP_INDEXING_SCRIPTS,
    EMBEDDING_SCRIPTS,
):
    if str(_script_dir) not in sys.path:
        sys.path.insert(0, str(_script_dir))

import agy_lean  # type: ignore
import auto_curate_person as curation_mod  # type: ignore
import build_objects_sqlite as sqlite_builder_mod  # type: ignore
import discover_person as discovery_mod  # type: ignore
import embed_corpus_gemma2 as embed_mod  # type: ignore
import hybrid_search as search_mod  # type: ignore
import merge_round as merge_round_mod  # type: ignore
import pdf_to_preflight_adapter as pdf_adapter_mod  # type: ignore
import sanitize_preamble as sanitize_mod  # type: ignore
import ytb_to_usdb_intake as ytb_intake_mod  # type: ignore


class OrchestrationGateError(RuntimeError):
    """Raised when any Hard Verification Gate (G0..G5) fails."""

    def __init__(self, gate_id: str, stage_num: int, errors: List[str], details: Optional[Dict[str, Any]] = None):
        self.gate_id = gate_id
        self.stage_num = stage_num
        self.errors = errors
        self.details = details or {}
        msg = f"Hard Gate {gate_id} (Stage {stage_num}) FAILED with {len(errors)} error(s): " + "; ".join(errors)
        super().__init__(msg)


REQUIRED_USDB_TABLES = [
    "sources",
    "series",
    "lessons_or_parts",
    "passages",
    "passages_fts",
    "persons",
    "passage_persons",
    "places",
    "passage_places",
    "events_chronology",
    "stories_cases",
    "science_gems",
    "evidences",
    "matn_triangulation",
]


def _utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _normalize_backend_name(backend: str) -> str:
    b = (backend or "auto").strip().lower()
    if b in ("deterministic", "deterministic-arabic-mps"):
        return "deterministic-arabic-mps"
    return b


AI_AR_PREAMBLE_LINE_RE = re.compile(
    r"^\s*(?:إليك\s+التفريغ|فيما\s+يلي\s+(?:نص|تفريغ)|بالتأكيد[،,]?\s*(?:إليك|هذا)|هذا\s+هو\s+التفريغ)[^\n]*$",
    re.MULTILINE,
)
AI_AR_CLOSING_LINE_RE = re.compile(
    r"^\s*(?:أتمنى\s+أن\s+يكون\s+التفريغ|إذا\s+أردت\s+تلخيص|هل\s+تود\s+مني\s+استخراج)[^\n]*$",
    re.MULTILINE,
)


def strip_all_preambles(text: str) -> Tuple[str, List[str]]:
    """Combines sanitize_preamble.strip_preamble_and_header with Arabic AI chat wrapper stripping."""
    cleaned, reasons = sanitize_mod.strip_preamble_and_header(text)
    reasons_list = list(reasons)
    if AI_AR_PREAMBLE_LINE_RE.search(cleaned):
        cleaned = AI_AR_PREAMBLE_LINE_RE.sub("", cleaned).lstrip()
        if "AR_AI_PREAMBLE" not in reasons_list:
            reasons_list.append("AR_AI_PREAMBLE")
    if AI_AR_CLOSING_LINE_RE.search(cleaned):
        cleaned = AI_AR_CLOSING_LINE_RE.sub("", cleaned).rstrip() + "\n"
        if "AR_AI_CLOSING" not in reasons_list:
            reasons_list.append("AR_AI_CLOSING")
    return cleaned, reasons_list


def _build_word_ctc_align_payload(text: str) -> Dict[str, Any]:
    """Generates a deterministic word-level CTC alignment structure `{"w": [[word, start, end], ...]}`."""
    words = [w for w in re.split(r"\s+", text.strip()) if w]
    w_entries: List[List[Any]] = []
    cur_t = 0.5
    for w in words:
        dur = round(max(0.25, min(0.85, len(w) * 0.08)), 2)
        w_entries.append([w, round(cur_t, 2), round(cur_t + dur, 2)])
        cur_t += dur + 0.05
    return {"w": w_entries}


# ============================================================================
# ============================================================================
# Multi-Format Series Matcher & Shamela4 JSONL Book Resolver (Stage 3 Helpers)
# ============================================================================

DEFAULT_SHAMELA_DB_DIR = Path("/Users/macm1pro/REPOS/swe/Shamela4_Full_DB")

SHAMELA_SCIENCE_MAP: Dict[str, str] = {
    "العقيدة": "akida",
    "عقيدة": "akida",
    "الفرق والردود": "akida",
    "أصول الفقه": "ossoul",
    "القواعد الفقهية": "qawaid",
    "الفقه المالكي": "maliki",
    "الفقه الشافعي": "maliki",
    "الفقه الحنبلي": "maliki",
    "الفقه الحنفي": "maliki",
    "الفقه العام": "maliki",
    "مسائل فقهية": "maliki",
    "السياسة الشرعية والقضاء": "maliki",
    "النحو والصرف": "nahw",
    "اللغة": "lugha",
    "الغريب والمعاجم": "lugha",
    "البلاغة": "balagha",
    "الأدب": "adab",
    "العروض والقوافي": "adab",
    "التفسير": "tafsir",
    "علوم القرآن وأصول التفسير": "tafsir",
    "التجويد والقراءات": "tafsir",
    "كتب السنة": "hadith",
    "شروح الحديث": "hadith",
    "العلل والسؤالات الحديثية": "hadith",
    "مصطلح الحديث": "hadith",
    "التخريج والأطراف": "hadith",
    "السيرة النبوية": "sirah",
    "الشمائل المحمدية": "sirah",
    "التاريخ": "tari5",
    "التراجم والطبقات": "tarajim",
    "الأنساب": "tarajim",
    "البلدان والرحلات": "tari5",
    "الرقائق والآداب والأذكار": "tazkia",
    "الدعوة وأحوال المسلمين": "tazkia",
    "كتب عامة": "tazkia",
    "فهارس الكتب والأدلة": "tazkia",
    "المنطق": "mantiq",
}

_SHAMELA_LOOKUP_CACHE: Dict[str, Tuple[Dict[int, Path], Dict[int, Path], List[Tuple[str, Path]]]] = {}


def _norm_ar_text(text: str) -> str:
    if not text:
        return ""
    t = re.sub(r"[\u064B-\u065F\u0670\u0640]", "", str(text))
    t = re.sub(r"[إأآٱ]", "ا", t)
    t = re.sub(r"ة", "ه", t)
    t = re.sub(r"ى", "ي", t)
    t = re.sub(r"[^\w\s]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _normalize_science_code(raw_science: Optional[str], title_hint: str = "") -> str:
    valid_sciences = getattr(merge_round_mod, "SCIENCE_META", {})
    if raw_science:
        s_clean = str(raw_science).strip()
        if s_clean in valid_sciences:
            return s_clean
        if s_clean.lower() in valid_sciences:
            return s_clean.lower()
        if s_clean in SHAMELA_SCIENCE_MAP and SHAMELA_SCIENCE_MAP[s_clean] in valid_sciences:
            return SHAMELA_SCIENCE_MAP[s_clean]
    # Infer from title_hint if possible
    t_norm = _norm_ar_text(title_hint)
    if any(w in t_norm for w in ("اصول", "الورقات", "مراقي", "جمع الجوامع", "روضة الناظر")):
        return "ossoul"
    if any(w in t_norm for w in ("نحو", "الفيه", "اجروميه", "قطر الندي", "شذور الذهب", "اعراب")):
        return "nahw"
    if any(w in t_norm for w in ("عقيده", "توحيد", "واسطيه", "طحاويه", "تدمر", "حمويه")):
        return "akida"
    if any(w in t_norm for w in ("تفسير", "قران", "سوره")):
        return "tafsir"
    if any(w in t_norm for w in ("حديث", "بخاري", "مسلم", "ترمذي", "اربعون", "عمدة الاحكام", "بلوغ المرام")):
        return "hadith"
    if any(w in t_norm for w in ("سيره", "شمائل", "مغازي")):
        return "sirah"
    if any(w in t_norm for w in ("اخضري", "رساله ابن ابي زيد", "مختصر خليل", "مرشد المعين", "فقه")):
        return "maliki"
    return "tazkia" if "tazkia" in valid_sciences else "maliki"


def _extract_numeric_shamela_id(val: Any) -> Optional[int]:
    if val is None or isinstance(val, bool):
        return None
    if isinstance(val, int):
        return val if val > 0 else None
    s = str(val).strip()
    if not s or s.startswith("tafsir:"):
        return None
    m = re.match(r"^(?:shamela:)?(\d+)$", s)
    if m:
        num = int(m.group(1))
        return num if num > 0 else None
    return None


def _build_shamela_lookup(
    shamela_db_dir: Path,
) -> Tuple[Dict[int, Path], Dict[int, Path], List[Tuple[str, Path]]]:
    cache_key = str(shamela_db_dir.resolve())
    if cache_key in _SHAMELA_LOOKUP_CACHE:
        return _SHAMELA_LOOKUP_CACHE[cache_key]

    by_shamela_id: Dict[int, Path] = {}
    by_folder_book_id: Dict[int, Path] = {}
    by_norm_title: List[Tuple[str, Path]] = []

    if not shamela_db_dir.exists():
        _SHAMELA_LOOKUP_CACHE[cache_key] = (by_shamela_id, by_folder_book_id, by_norm_title)
        return _SHAMELA_LOOKUP_CACHE[cache_key]

    # 1. Check flat books/<id>.jsonl or <id>.jsonl if present
    for flat_dir in (shamela_db_dir / "books", shamela_db_dir):
        if flat_dir.is_dir():
            for jf in flat_dir.glob("*.jsonl"):
                if jf.stem.isdigit():
                    bid = int(jf.stem)
                    by_shamela_id.setdefault(bid, jf)
                    by_folder_book_id.setdefault(bid, jf)

    # 2. Scan category folders <category>/<book_id>__<slug>/
    for cat_dir in sorted(shamela_db_dir.iterdir()):
        if not cat_dir.is_dir() or cat_dir.name.startswith("."):
            continue
        for bdir in cat_dir.iterdir():
            if not bdir.is_dir() or "__" not in bdir.name:
                continue
            pages_jsonl = bdir / "pages.jsonl"
            if not pages_jsonl.exists():
                continue
            prefix_str, slug_title = bdir.name.split("__", 1)
            if prefix_str.isdigit():
                by_folder_book_id[int(prefix_str)] = bdir
            meta_fp = bdir / "book_metadata.json"
            b_title = slug_title.replace("-", " ")
            if meta_fp.exists():
                try:
                    mdata = json.loads(meta_fp.read_text(encoding="utf-8"))
                    sh_id = _extract_numeric_shamela_id(mdata.get("shamela_id"))
                    if sh_id:
                        by_shamela_id[sh_id] = bdir
                    fb_id = _extract_numeric_shamela_id(mdata.get("book_id"))
                    if fb_id:
                        by_folder_book_id.setdefault(fb_id, bdir)
                    if mdata.get("title"):
                        b_title = str(mdata["title"])
                except Exception:
                    pass
            nt = _norm_ar_text(b_title)
            if nt:
                by_norm_title.append((nt, bdir))

    _SHAMELA_LOOKUP_CACHE[cache_key] = (by_shamela_id, by_folder_book_id, by_norm_title)
    return _SHAMELA_LOOKUP_CACHE[cache_key]


def resolve_shamela_book_path(
    book_entry: Dict[str, Any],
    shamela_db_dir: Optional[Path] = None,
) -> Optional[Path]:
    """Resolves a book dict from discovery/curation against local Shamela4_Full_DB."""
    for k in ("input_path", "local_path", "path"):
        lp = book_entry.get(k)
        if lp and Path(lp).exists():
            return Path(lp).resolve()

    db_root = Path(shamela_db_dir) if shamela_db_dir else DEFAULT_SHAMELA_DB_DIR
    if not db_root.exists():
        return None

    by_shamela_id, by_folder_book_id, by_norm_title = _build_shamela_lookup(db_root)

    # Priority 1: Explicit shamela_id or "shamela:<N>" id (must match shamela_id first!)
    for raw_sh in (
        book_entry.get("shamela_id"),
        book_entry.get("id"),
        book_entry.get("book_id") if isinstance(book_entry.get("book_id"), str) and str(book_entry.get("book_id")).startswith("shamela:") else None,
        (book_entry.get("matched_book") or {}).get("id") if isinstance(book_entry.get("matched_book"), dict) else None,
    ):
        if isinstance(raw_sh, str) and raw_sh.startswith("tafsir:"):
            return None
        sh_id = _extract_numeric_shamela_id(raw_sh)
        if sh_id is not None:
            if sh_id in by_shamela_id:
                return by_shamela_id[sh_id].resolve()
            # Only fall back to folder book_id if raw_sh was NOT explicitly prefixed with "shamela:"
            if not (isinstance(raw_sh, str) and raw_sh.startswith("shamela:")) and sh_id in by_folder_book_id:
                return by_folder_book_id[sh_id].resolve()

    # Priority 2: Explicit folder book_id
    raw_fb = book_entry.get("book_id")
    if not (isinstance(raw_fb, str) and raw_fb.startswith("shamela:")):
        fb_id = _extract_numeric_shamela_id(raw_fb)
        if fb_id is not None:
            if fb_id in by_folder_book_id:
                return by_folder_book_id[fb_id].resolve()
            if fb_id in by_shamela_id:
                return by_shamela_id[fb_id].resolve()

    # Priority 3: Exact normalized Arabic title match
    raw_title = (
        book_entry.get("title")
        or ((book_entry.get("matched_book") or {}).get("title") if isinstance(book_entry.get("matched_book"), dict) else "")
        or ""
    )
    nt = _norm_ar_text(raw_title)
    if nt and len(nt) >= 6:
        for cand_nt, cand_path in by_norm_title:
            if cand_nt == nt:
                return cand_path.resolve()

    return None


def _clean_shamela_page_text(text: str) -> str:
    if not text:
        return ""
    # Normalize CRLF/CR to LF and strip inline HTML tags present in some Shamela4 dumps
    t = text.replace("\r\n", "\n").replace("\r", "\n")
    t = re.sub(r"<[^>]+>", "", t)
    return t.strip()


def convert_shamela_to_preflight_dir(
    src_path: Path,
    staging_dir: Path,
    fallback_meta: Optional[Dict[str, Any]] = None,
    max_chars: int = 22000,
) -> Dict[str, Any]:
    """
    Converts a Shamela4 book folder (with pages.jsonl + book_metadata.json) or standalone .jsonl
    into a turath-pdf-to-text compatible directory (`pages/pNNNN.json`) with 100% character retention
    and strict footnote head verification (routing unnumbered colophons to `margin_notes`).
    """
    fallback_meta = fallback_meta or {}
    src_path = Path(src_path).resolve()
    if src_path.is_dir():
        jsonl_path = src_path / "pages.jsonl"
        meta_path = src_path / "book_metadata.json"
    else:
        jsonl_path = src_path
        meta_path = src_path.parent / "book_metadata.json"

    if not jsonl_path.exists():
        raise FileNotFoundError(f"Shamela JSONL file not found at {jsonl_path}")

    disk_meta: Dict[str, Any] = {}
    if meta_path.exists():
        try:
            disk_meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            disk_meta = {}

    pages_dir = staging_dir / "pages"
    if pages_dir.exists():
        shutil.rmtree(pages_dir)
    pages_dir.mkdir(parents=True, exist_ok=True)

    fn_head_re = getattr(
        pdf_adapter_mod,
        "FN_LINE_HEAD_RE",
        re.compile(r"^\s*(?:[\(\[«]?\s*[٠-٩0-9]{1,3}\s*[\)\]».\-–—:]*|[٠-٩0-9]{1,3}\s*[\)\]».\-–—:])"),
    )

    total_chars = 0
    written_pages = 0
    with jsonl_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue

            body = _clean_shamela_page_text(str(rec.get("body") or rec.get("text") or rec.get("body_text") or ""))
            fn_raw = _clean_shamela_page_text(str(rec.get("footnotes") or ""))
            margin = _clean_shamela_page_text(str(rec.get("margin_notes") or ""))

            if not body and not fn_raw and not margin:
                continue

            # Ensure every block in `footnotes` starts with a valid footnote number head;
            # move any unnumbered colophon or leading continuation lines into `margin_notes`
            # so 100.0% of characters are preserved while `orphan_head` == 0.
            clean_fn = fn_raw
            if fn_raw:
                fn_lines = [ln.strip() for ln in fn_raw.split("\n") if ln.strip()]
                first_num_idx: Optional[int] = None
                for l_idx, ln in enumerate(fn_lines):
                    if fn_head_re.match(ln):
                        first_num_idx = l_idx
                        break
                if first_num_idx is None:
                    margin = (margin + "\n" + "\n".join(fn_lines)).strip() if margin else "\n".join(fn_lines)
                    clean_fn = ""
                elif first_num_idx > 0:
                    leading_unnumbered = "\n".join(fn_lines[:first_num_idx])
                    margin = (margin + "\n" + leading_unnumbered).strip() if margin else leading_unnumbered
                    clean_fn = "\n".join(fn_lines[first_num_idx:])
                else:
                    clean_fn = "\n".join(fn_lines)

            page_char_len = len(body) + len(clean_fn) + len(margin)
            if written_pages > 0 and max_chars > 0 and (total_chars + page_char_len) > max_chars:
                break

            written_pages += 1
            total_chars += page_char_len
            raw_pnum = rec.get("page_num") or rec.get("page_number") or written_pages
            p_num = int(raw_pnum) if str(raw_pnum).isdigit() else written_pages
            raw_vol = rec.get("part") or rec.get("volume") or 1
            vol_num = int(raw_vol) if str(raw_vol).isdigit() else 1
            page_payload = {
                "pdf_page": written_pages,
                "tag": f"p{written_pages:04d}",
                "layout": "standard_single_col",
                "page_number": p_num,
                "volume": vol_num,
                "body_text": body,
                "footnotes": clean_fn,
                "margin_notes": margin,
                "extracted": {
                    "printed_page": str(p_num),
                    "running_header": "",
                    "matn": body,
                    "margin_notes": margin,
                    "footnotes": clean_fn,
                },
                "Needs_Review": False,
            }
            (pages_dir / f"p{written_pages:04d}.json").write_text(
                json.dumps(page_payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    raw_id = (
        fallback_meta.get("book_id")
        or disk_meta.get("shamela_id")
        or disk_meta.get("book_id")
        or fallback_meta.get("id")
        or 9001
    )
    resolved_book_id = _extract_numeric_shamela_id(raw_id) or 9001
    resolved_title = str(
        disk_meta.get("title")
        or fallback_meta.get("title")
        or src_path.stem.split("__")[-1].replace("-", " ")
    )
    raw_sci = (
        fallback_meta.get("science")
        or disk_meta.get("category_name")
        or fallback_meta.get("category")
        or ""
    )
    resolved_science = _normalize_science_code(raw_sci, title_hint=resolved_title)
    resolved_author = str(disk_meta.get("author") or fallback_meta.get("author") or "المصنف")
    resolved_death = str(disk_meta.get("death") or fallback_meta.get("death") or "1445")

    meta_out: Dict[str, Any] = {
        "input_path": str(staging_dir),
        "source_shamela_path": str(src_path),
        "book_id": resolved_book_id,
        "science": resolved_science,
        "title": resolved_title,
        "author": resolved_author,
        "death": resolved_death,
        "pages_written": written_pages,
        "total_chars": total_chars,
    }
    (staging_dir / "book_meta.json").write_text(
        json.dumps(meta_out, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    meta_out["input_path"] = staging_dir
    return meta_out


def _match_external_series_dirs(
    ext_root: Optional[Path],
    curated_series: List[Dict[str, Any]],
) -> Dict[str, Path]:
    """
    Matches external series directories under `ext_root` to curated series `sid` (`s001`, `s002`, ...)
    supporting all 4 real production naming conventions:
      1. `yt_id` (`vid`) overlap between `NNN_<vid>.txt` / `<vid>.txt` and curated `lessons`
      2. `series_slug` (e.g. `sharh_manzouma_adoudiya`), `playlist_id` (e.g. `alasimi-mut-744`), or `row_id` (e.g. `984`)
      3. Normalized Arabic series title in `_meta.json`
      4. `sNNN` directory name ONLY when its video IDs do not belong to a different curated series
    """
    if not ext_root or not ext_root.exists():
        return {}

    # Gather candidate directories containing .txt files
    cand_dirs: List[Path] = []
    if list(ext_root.glob("*.txt")):
        cand_dirs.append(ext_root)
    for d in sorted(ext_root.rglob("*")):
        if d.is_dir() and list(d.glob("*.txt")):
            cand_dirs.append(d)

    if not cand_dirs:
        return {}

    # Map every curated video_id to its curated series_id
    vid_to_curated_sid: Dict[str, str] = {}
    for s_idx, s in enumerate(curated_series, 1):
        sid = s.get("series_id") or f"s{s_idx:03d}"
        for ep in s.get("lessons") or s.get("episodes", []):
            vid = ep.get("yt_id") or ep.get("video_id") or ""
            if vid:
                vid_to_curated_sid[vid] = sid

    cand_infos: List[Dict[str, Any]] = []
    for cdir in cand_dirs:
        vids: set[str] = set()
        for tf in cdir.glob("*.txt"):
            vids.add(tf.stem)
            m = re.match(r"^\d+_(.+)$", tf.stem)
            if m:
                vids.add(m.group(1))
        cmeta: Dict[str, Any] = {}
        meta_fp = cdir / "_meta.json"
        if meta_fp.exists():
            try:
                cmeta = json.loads(meta_fp.read_text(encoding="utf-8"))
            except Exception:
                cmeta = {}
        # Determine if this candidate's videos strongly belong to a specific curated series
        owner_counts: Dict[str, int] = {}
        for v in vids:
            if v in vid_to_curated_sid:
                osid = vid_to_curated_sid[v]
                owner_counts[osid] = owner_counts.get(osid, 0) + 1
        dominant_sid = max(owner_counts.items(), key=lambda kv: kv[1])[0] if owner_counts else None

        cand_infos.append(
            {
                "dir": cdir,
                "name": cdir.name,
                "vids": vids,
                "meta": cmeta,
                "dominant_sid": dominant_sid,
                "owner_counts": owner_counts,
                "norm_title": _norm_ar_text(
                    str(cmeta.get("title") or cmeta.get("clean_title") or cmeta.get("series_title") or "")
                ),
            }
        )

    matched: Dict[str, Path] = {}
    used_dirs: set[Path] = set()

    # Pass 1: Match by positive video_id (`yt_id`) overlap
    for s_idx, s in enumerate(curated_series, 1):
        sid = s.get("series_id") or f"s{s_idx:03d}"
        best_c: Optional[Dict[str, Any]] = None
        best_ov = 0
        for c in cand_infos:
            if c["dir"] in used_dirs:
                continue
            ov = c["owner_counts"].get(sid, 0)
            if ov > best_ov:
                best_ov = ov
                best_c = c
        if best_c is not None and best_ov > 0:
            matched[sid] = best_c["dir"]
            used_dirs.add(best_c["dir"])

    # Pass 2: Match by explicit slug / playlist_id / row_id / normalized title / safe sNNN
    for s_idx, s in enumerate(curated_series, 1):
        sid = s.get("series_id") or f"s{s_idx:03d}"
        if sid in matched:
            continue

        s_Idents = {
            str(x).strip()
            for x in (
                s.get("series_slug"),
                s.get("slug"),
                s.get("playlist_id"),
                s.get("row_id"),
            )
            if x is not None and str(x).strip()
        }
        s_norm_title = _norm_ar_text(str(s.get("title") or s.get("clean_title") or ""))

        for c in cand_infos:
            if c["dir"] in used_dirs:
                continue
            # Never match a candidate directory whose videos belong to a DIFFERENT curated series
            if c["dominant_sid"] and c["dominant_sid"] != sid:
                continue

            cmeta = c["meta"]
            c_idents = {
                str(x).strip()
                for x in (
                    c["name"],
                    cmeta.get("series_slug"),
                    cmeta.get("slug"),
                    cmeta.get("playlist_id"),
                    cmeta.get("row_id"),
                )
                if x is not None and str(x).strip()
            }
            if (s_Idents and (s_Idents & c_idents)) or (
                s_norm_title and c["norm_title"] and s_norm_title == c["norm_title"]
            ) or (c["name"] == sid and c["dominant_sid"] is None):
                matched[sid] = c["dir"]
                used_dirs.add(c["dir"])
                break

    return matched


# ============================================================================
# Deterministic Deep Extraction Builder for Books (Stage 4 Helper)
# ============================================================================


def auto_build_deep_book_extraction(
    science: str,
    raw_book: Dict[str, Any],
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Deterministically builds a Gate v4.3-compliant deep extraction payload for a book in raw_round4_books.json."""
    meta = raw_book.get("meta", {})
    book_title = meta.get("title") or raw_book.get("title") or "كتاب تراثي"
    author_name = meta.get("author") or raw_book.get("author") or "المصنف"
    parts_list = raw_book.get("parts", []) or []

    # 1. Extract base_matn_clauses from «...» or قوله: «...» across parts, with verbatim fallback for plain Shamela books
    clauses_out: List[Dict[str, Any]] = []
    seen_clause_texts: set[str] = set()
    for p_in in parts_list:
        raw_part = p_in.get("text", "")
        for m in re.finditer(r"قوله\s*[:：]?\s*«([^»\n]{10,80})»", raw_part):
            c_txt = m.group(1).strip()
            if c_txt and c_txt not in seen_clause_texts:
                seen_clause_texts.add(c_txt)
                cid = f"M{len(clauses_out) + 1}"
                clauses_out.append(
                    {
                        "clause_id": cid,
                        "title": f"فقرة المتن ({cid})",
                        "text": c_txt,
                    }
                )

    if len(clauses_out) < 3:
        for p_in in parts_list:
            raw_part = p_in.get("text", "")
            for cand in ytb_intake_mod.extract_candidate_sentences(raw_part):
                c_txt = cand.strip()
                if any(tok in c_txt for tok in ("[ص:", "[هامش", "(¬", "___")):
                    continue
                words = c_txt.split()
                if len(words) >= 4:
                    short_c = " ".join(words[: min(7, len(words))]).strip(" ،.؛:؟!«»\"'()-")
                    if (
                        18 <= len(short_c) <= 85
                        and len(short_c.split()) >= 4
                        and short_c in raw_part
                        and short_c not in seen_clause_texts
                    ):
                        seen_clause_texts.add(short_c)
                        cid = f"M{len(clauses_out) + 1}"
                        clauses_out.append(
                            {
                                "clause_id": cid,
                                "title": f"فقرة المتن ({cid})",
                                "text": short_c,
                            }
                        )
                        if len(clauses_out) >= 6:
                            break
            if len(clauses_out) >= 6:
                break

    deep_toc_passages: List[Dict[str, Any]] = []
    science_gems: List[Dict[str, Any]] = []
    stories: List[Dict[str, Any]] = []
    quotes: List[Dict[str, Any]] = []

    target_max_chars = 1100 if science == "akida" else 1500

    for idx_p, p_in in enumerate(parts_list):
        pt = int(p_in.get("i", p_in.get("part", idx_p)))
        raw_part = p_in.get("text", "")
        spans = ytb_intake_mod.partition_raw_text_lossless(raw_part, target_max_chars=target_max_chars)

        for s_idx, (c_start, c_end) in enumerate(spans):
            p_raw = raw_part[c_start:c_end]
            anchor = ytb_intake_mod.extract_anchor_words(p_raw, 6)

            # Detect leading isnad and extract matn_start_anchor if present
            matn_start_anchor = ""
            isnad_prefix = ""
            core_matn = p_raw
            if any(w in p_raw[:100] for w in ("حدثنا", "أخبرنا", "حدثني", "أنبأنا")):
                # Find the end of the isnad chain (last قال: or أن رسول الله ... قال:)
                m_qala = list(re.finditer(r"(?:قال|يقول)\s*[:：]\s*«?([^»\n.،]{12,60})", p_raw[:320]))
                if m_qala:
                    last_m = m_qala[-1]
                    cand_words = last_m.group(1).strip().split()
                    cand_anc = " ".join(cand_words[: min(5, len(cand_words))])
                    if cand_anc and cand_anc in p_raw:
                        matn_start_anchor = cand_anc
                        anc_pos = p_raw.find(cand_anc)
                        isnad_prefix = p_raw[:anc_pos]
                        core_matn = p_raw[anc_pos:]

            persons, places, chronology, evidences = ytb_intake_mod.detect_passage_entities(core_matn)

            # Fallback person detection for explicit Arabic nasab (فلان بن فلان) to prevent P0_MISSED_PERSONS
            if not persons:
                for m_bn in re.finditer(
                    r"\b((?:أبو\s+[\u0621-\u064A]+\s+)?[\u0621-\u064A]{3,}\s+بن\s+[\u0621-\u064A]{3,}(?:\s+ال[\u0621-\u064A]{3,})?)",
                    core_matn,
                ):
                    p_cand = m_bn.group(1).strip()
                    first_w = p_cand.split()[0]
                    if first_w in ("وهو", "قال", "كان", "أن", "إن", "عن", "من", "في", "على", "إلى", "حدثنا", "أخبرنا"):
                        continue
                    if p_cand in core_matn:
                        persons.append(
                            {
                                "canonical_name": p_cand,
                                "mentioned_as": p_cand,
                                "category": "علم مذكور في المتن",
                                "role": "علم أو فقيه مترجم",
                                "source_layer": "matn",
                            }
                        )
                        break

            # Tag explicit isnad narrators from isnad_prefix with source_layer='isnad'
            if isnad_prefix:
                for m_nar in re.finditer(
                    r"(?:حدثنا|أخبرنا|حدثني|أنبأنا|عن)\s+([\u0621-\u064A]+(?:\s+بن\s+[\u0621-\u064A]+(?:\s+ال[\u0621-\u064A]+)?)?)",
                    isnad_prefix,
                ):
                    nar_surface = m_nar.group(1).strip()
                    if len(nar_surface) >= 5 and nar_surface not in core_matn:
                        persons.append(
                            {
                                "canonical_name": nar_surface,
                                "mentioned_as": nar_surface,
                                "category": "راوٍ في السند",
                                "role": "راوٍ في سلسلة الإسناد",
                                "source_layer": "isnad",
                            }
                        )

            # Classify death years (ت NNN هـ) as 'transmission' and event years (سنة NNN هـ) as 'historical'
            refined_chronology: List[Dict[str, Any]] = []
            all_yrs = merge_round_mod.extract_date_years_from_text(p_raw)
            for y in sorted(set(all_yrs)):
                ar_y = str(y).translate(str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩"))
                is_death = bool(
                    re.search(rf"(?:\(\s*ت|توفي)\s*(?:{y}|{ar_y})\s*هـ?", p_raw)
                    or (isnad_prefix and (str(y) in isnad_prefix or ar_y in isnad_prefix))
                )
                refined_chronology.append(
                    {
                        "hijri_year": y,
                        "event_tag": f"وفاة علم أو راوٍ ({y} هـ)" if is_death else f"واقعة تاريخية سنة ({y} هـ)",
                        "event_layer": "transmission" if is_death else "historical",
                    }
                )

            # Match explained_matn_clause_id if a clause appears in p_raw
            matched_cid = ""
            matched_cverb = ""
            for cl in clauses_out:
                if cl["text"] in p_raw:
                    matched_cid = cl["clause_id"]
                    matched_cverb = cl["text"]
                    break

            sub_h = f"المبحث {s_idx + 1} من الجزء {pt}: تحرير المسائل والأدلة"
            summary = (
                f"تحقيق وتفصيل علمي للمسائل والأحكام الشرعية الواردة في هذا الموضع من المبحث ({s_idx + 1}) "
                f"مع بيان الأدلة والشواهد المعتمدة ووجه الاستدلال بها."
            )
            topics = [
                f"مسائل الجزء {pt} المبحث {s_idx + 1}",
                "تحرير الأدلة والضوابط الفقهية والأصولية",
            ]
            queries = [
                f"ما خلاصة الأحكام والأدلة المقررة في المبحث {s_idx + 1} من الجزء {pt}؟",
                "كيف استدل المصنف على المسألة المبحوثة في هذا الموضع؟",
            ]

            p_entry: Dict[str, Any] = {
                "part": pt,
                "sub_heading": sub_h,
                "anchor_start": anchor,
                "summary": summary,
                "topics": topics,
                "persons": persons,
                "places": places,
                "chronology": refined_chronology,
                "evidences": evidences,
                "search_queries": queries,
            }
            if matn_start_anchor:
                p_entry["matn_start_anchor"] = matn_start_anchor
            if matched_cid and matched_cverb:
                p_entry["explained_matn_clause_id"] = matched_cid
                p_entry["explained_matn_verbatim"] = matched_cverb

            deep_toc_passages.append(p_entry)

        # Extract candidate verbatim sentences in part `pt` for science_gems and quotes
        cands = ytb_intake_mod.extract_candidate_sentences(raw_part)
        if len(cands) < 4:
            words_all = raw_part.split()
            for w_i in range(0, max(1, len(words_all) - 8), 8):
                w_slice = " ".join(words_all[w_i : w_i + 8]).strip(" ،.؛:؟!«»\"'()-")
                if len(w_slice.split()) >= 6 and w_slice in raw_part:
                    cands.append(w_slice)

        if cands:
            v_rule = cands[0]
            science_gems.append(
                {
                    "part": pt,
                    "title": f"القاعدة المحررة في الجزء {pt}",
                    "category": "تأصيل علمي وضوابط",
                    "verbatim_rule": v_rule,
                    "polished_rule": v_rule,
                    "explanation": "تقرير الضابط العلمي المستخلص من المتن والشرح في هذا الجزء.",
                }
            )
        if len(cands) >= 2:
            q_cand = cands[1]
            quotes.append(
                {
                    "part": pt,
                    "quote": q_cand,
                    "speaker": author_name,
                    "context": f"تقرير المسألة في الجزء {pt}",
                }
            )

        stories.append(
            {
                "part": pt,
                "title": f"مسألة تطبيقية في الجزء {pt}",
                "anchor_start": ytb_intake_mod.extract_anchor_words(raw_part, 6),
                "summary": f"بيان تطبيقي للمسألة المقررة في الجزء {pt}.",
                "lesson": "ربط الأصل الكلي بالفروع التطبيقية.",
            }
        )

    deep_book = {
        "book_id": raw_book.get("book_id", 9001),
        "science": science,
        "base_matn_clauses": clauses_out,
        "deep_toc_passages": deep_toc_passages,
        "science_gems": science_gems,
        "stories": stories,
        "quotes": quotes,
    }
    return deep_book, clauses_out


# ============================================================================
# Hard Verification Gates (G0..G5)
# ============================================================================


def verify_gate_g0(quota_report: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """Gate G0: Verifies model quota >= 20.0% (safe == True) and Lean HOME isolation (0 violations, clean cfg)."""
    errors: List[str] = []
    sel = quota_report.get("selected_model_info", {})
    is_safe = sel.get("safe", sel.get("allowed", False))
    if not is_safe:
        errors.append(
            f"G0_QUOTA_EXHAUSTED: Selected model '{sel.get('selected_model') or sel.get('label')}' is not safe "
            f"(remaining_pct={sel.get('remaining_pct')}, reason={sel.get('reason')})"
        )
    if float(sel.get("remaining_pct", 0.0)) < 20.0:
        errors.append(
            f"G0_QUOTA_BELOW_THRESHOLD: remaining_pct={sel.get('remaining_pct')}% < 20.0% minimum"
        )

    iso = quota_report.get("isolation_info", {})
    if not iso.get("isolated", False):
        errors.append(f"G0_LEAN_HOME_NOT_ISOLATED: {iso}")
    violations = iso.get("violations", [])
    if violations:
        errors.append(f"G0_FORBIDDEN_PATH_LEAK: violations={violations}")
    if not iso.get("has_clean_cfg", True):
        errors.append("G0_DIRTY_PLUGIN_CONFIG: has_clean_cfg is False")

    return (len(errors) == 0, errors)


def verify_gate_g1(raw_discovery_path: Path) -> Tuple[bool, List[str], Dict[str, Any]]:
    """Gate G1: Verifies 01_discovery/<person_id>_raw.json schema and non-empty sources."""
    errors: List[str] = []
    if not raw_discovery_path.exists():
        return False, [f"G1_MISSING_FILE: {raw_discovery_path} does not exist"], {}

    try:
        data = json.loads(raw_discovery_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return False, [f"G1_INVALID_JSON: {exc}"], {}

    required_keys = ["person_id", "sheikh_name", "playlists", "videos", "archive_items", "books", "stats"]
    for k in required_keys:
        if k not in data:
            errors.append(f"G1_MISSING_KEY: Required key '{k}' missing from discovery JSON")

    videos = data.get("videos", []) if isinstance(data.get("videos"), list) else []
    books = data.get("books", []) if isinstance(data.get("books"), list) else []
    archive_items = data.get("archive_items", []) if isinstance(data.get("archive_items"), list) else []
    total_sources = len(videos) + len(books) + len(archive_items)

    if total_sources == 0:
        errors.append("G1_EMPTY_DISCOVERY: 0 videos, 0 books, and 0 archive_items discovered")

    for idx, v in enumerate(videos):
        vid_key = v.get("video_id") or v.get("yt_id") or v.get("vid")
        if not vid_key or not v.get("title"):
            errors.append(f"G1_INVALID_VIDEO_RECORD: videos[{idx}] missing video_id/yt_id/vid or title")

    metrics = {
        "person_id": data.get("person_id"),
        "playlists_count": len(data.get("playlists", [])),
        "videos_count": len(videos),
        "archive_items_count": len(archive_items),
        "books_count": len(books),
        "total_sources": total_sources,
    }
    return (len(errors) == 0, errors, metrics)


def verify_gate_g2(
    curated_json_path: Path,
    curated_db_path: Path,
    curated_series_root: Path,
    curation_report: Optional[Dict[str, Any]] = None,
) -> Tuple[bool, List[str], Dict[str, Any]]:
    """Gate G2: Verifies 9-Stage Curation (0 scanner flaws, 0 audit errors, 0 duplicate video_ids)."""
    errors: List[str] = []
    if not curated_json_path.exists():
        return False, [f"G2_MISSING_CURATED_JSON: {curated_json_path}"], {}
    if not curated_db_path.exists():
        errors.append(f"G2_MISSING_CURATED_DB: {curated_db_path}")

    curated_data = json.loads(curated_json_path.read_text(encoding="utf-8"))
    person_id = curated_data.get("sheikh", {}).get("id", "")

    if curation_report is not None:
        s9 = curation_report.get("stage9", {})
        flaws = s9.get("scanner_flaws_total", -1)
        if flaws != 0:
            errors.append(f"G2_SCANNER_FLAWS: deep_scanner_all reported {flaws} flaws (expected 0)")
        audit_rc = s9.get("audit_returncode", -1)
        audit_out = s9.get("audit_output", "")
        if audit_rc != 0 or "0 errors" not in audit_out:
            errors.append(f"G2_GLOBAL_AUDIT_FAILED: returncode={audit_rc}, output={audit_out[:200]}")

    seen_vids: set[str] = set()
    duplicate_vids: List[str] = []
    series_list = curated_data.get("series", [])
    standalone_list = curated_data.get("standalone_lectures", [])

    for s_idx, s in enumerate(series_list, 1):
        sid = s.get("series_id") or f"s{s_idx:03d}"
        meta_path = curated_series_root / person_id / sid / "_meta.json"
        if not meta_path.exists():
            errors.append(f"G2_MISSING_SERIES_META: {meta_path}")
        for ep in s.get("lessons") or s.get("episodes", []):
            vid = ep.get("yt_id") or ep.get("video_id", "")
            if vid in seen_vids:
                duplicate_vids.append(vid)
            seen_vids.add(vid)

    for ep in standalone_list:
        vid = ep.get("yt_id") or ep.get("video_id", "")
        if vid in seen_vids:
            duplicate_vids.append(vid)
        seen_vids.add(vid)

    if duplicate_vids:
        errors.append(f"G2_DUPLICATE_ACTIVE_VIDEOS: {duplicate_vids}")

    metrics = {
        "series_count": len(series_list),
        "standalone_count": len(standalone_list),
        "excluded_count": len(curated_data.get("excluded_videos", [])),
        "active_unique_videos": len(seen_vids),
        "duplicate_videos": len(duplicate_vids),
    }
    return (len(errors) == 0, errors, metrics)


def verify_gate_g3(
    extracted_series_person_dir: Path,
    extracted_books_dir: Path,
) -> Tuple[bool, List[str], Dict[str, Any]]:
    """Gate G3: Verifies 0 AI preambles in lecture .txt files and 100.0% char retention in PDF books."""
    errors: List[str] = []
    total_txt_files = 0
    total_series_dirs = 0
    unsanitized_files: List[str] = []

    if extracted_series_person_dir.exists():
        for sdir in sorted(extracted_series_person_dir.iterdir()):
            if not sdir.is_dir():
                continue
            total_series_dirs += 1
            meta_file = sdir / "_meta.json"
            if not meta_file.exists():
                errors.append(f"G3_MISSING_EXTRACTED_SERIES_META: {meta_file}")
            for txt_file in sorted(sdir.glob("*.txt")):
                total_txt_files += 1
                raw_txt = txt_file.read_text(encoding="utf-8")
                if not raw_txt.strip():
                    errors.append(f"G3_EMPTY_TRANSCRIPT: {txt_file}")
                    continue
                _, reasons = strip_all_preambles(raw_txt)
                if reasons:
                    unsanitized_files.append(f"{txt_file.name}: {reasons}")
                    errors.append(f"G3_UNSANITIZED_PREAMBLE: {txt_file.name} still contains {reasons}")

    total_books = 0
    if extracted_books_dir.exists():
        for bdir in sorted(extracted_books_dir.iterdir()):
            if not bdir.is_dir():
                continue
            total_books += 1
            manifest_path = bdir / "adapter_manifest.json"
            raw_round_path = bdir / "raw_round4_books.json"
            round_manifest_path = bdir / "round_manifest_r4_r10.json"
            if not manifest_path.exists():
                errors.append(f"G3_MISSING_ADAPTER_MANIFEST: {manifest_path}")
                continue
            if not raw_round_path.exists():
                errors.append(f"G3_MISSING_RAW_ROUND4_BOOKS: {raw_round_path}")
            if not round_manifest_path.exists():
                errors.append(f"G3_MISSING_ROUND_MANIFEST: {round_manifest_path}")

            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if manifest.get("status") != "PASS":
                errors.append(f"G3_BOOK_ADAPTER_FAILED: {bdir.name} status={manifest.get('status')}")
            zl = manifest.get("zero_loss_check", {})
            if (
                not zl.get("passed", False)
                or zl.get("body_char_loss", -1) != 0
                or zl.get("footnotes_char_loss", -1) != 0
                or float(zl.get("retention_pct", 0.0)) != 100.0
            ):
                errors.append(
                    f"G3_BOOK_CHAR_LOSS: {bdir.name} zero_loss_check={zl}"
                )
            mv4 = manifest.get("manifest_v4_verification", {})
            if not mv4.get("passed", False):
                errors.append(f"G3_MANIFEST_V4_FAILED: {bdir.name} manifest_v4_verification={mv4}")

    if total_txt_files == 0 and total_books == 0:
        errors.append("G3_NO_EXTRACTED_CONTENT: Neither lecture .txt files nor extracted books were produced")

    metrics = {
        "series_dirs_checked": total_series_dirs,
        "transcript_txt_files_checked": total_txt_files,
        "unsanitized_files_count": len(unsanitized_files),
        "books_checked": total_books,
    }
    return (len(errors) == 0, errors, metrics)


def verify_gate_g4(
    db_path: Path,
    sqlite_summary: Dict[str, Any],
    book_gate_reports: List[Dict[str, Any]],
    lecture_gate_reports: List[Dict[str, Any]],
) -> Tuple[bool, List[str], Dict[str, Any]]:
    """Gate G4: Verifies Gate v4.3/v5.1 PASS (0 P0 errors), SQLite chars_lost == 0, all 14 core tables, and layer isolation."""
    errors: List[str] = []

    for idx, rep in enumerate(book_gate_reports):
        passed = rep.get("passed", rep.get("status") == "PASS")
        p0_cnt = int(rep.get("p0_error_count", rep.get("total_p0_errors", -1)))
        if not passed or p0_cnt != 0:
            errors.append(
                f"G4_BOOK_GATE_V43_FAILED[{idx}]: passed={passed}, "
                f"p0_errors={p0_cnt}, details={rep.get('p0_errors') or rep.get('errors_detail')}"
            )

    for idx, rep in enumerate(lecture_gate_reports):
        passed = rep.get("passed", rep.get("status") == "PASS")
        p0_cnt = int(rep.get("p0_error_count", rep.get("total_p0_errors", -1)))
        if not passed or p0_cnt != 0:
            errors.append(
                f"G4_LECTURE_GATE_V51_FAILED[{idx}]: passed={passed}, "
                f"p0_errors={p0_cnt}, details={rep.get('p0_errors') or rep.get('errors_detail')}"
            )

    if int(sqlite_summary.get("chars_lost", -1)) != 0:
        errors.append(
            f"G4_SQLITE_CHAR_LOSS: chars_lost={sqlite_summary.get('chars_lost')} "
            f"(expected={sqlite_summary.get('expected_raw_chars')}, actual={sqlite_summary.get('actual_passage_chars')})"
        )
    if int(sqlite_summary.get("actual_passage_chars", 0)) <= 0:
        errors.append("G4_EMPTY_SQLITE_PASSAGES: actual_passage_chars == 0")

    if not db_path.exists():
        return False, errors + [f"G4_MISSING_SQLITE_DB: {db_path}"], {}

    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.cursor()
        existing_tables = {
            r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type IN ('table', 'view')").fetchall()
        }
        for req_t in REQUIRED_USDB_TABLES:
            if req_t not in existing_tables:
                errors.append(f"G4_MISSING_TABLE: Required USDB v5.7 table '{req_t}' missing from SQLite")

        # Verify zero char loss directly inside SQLite
        row_sum = cur.execute("SELECT COALESCE(SUM(LENGTH(raw_text)), 0), COUNT(*) FROM passages").fetchone()
        db_char_sum = int(row_sum[0])
        if db_char_sum != int(sqlite_summary.get("expected_raw_chars", -1)):
            errors.append(
                f"G4_DB_CHAR_MISMATCH: SUM(LENGTH(raw_text))={db_char_sum} != expected={sqlite_summary.get('expected_raw_chars')}"
            )

        # Verify person source_layer validity
        invalid_person_layers = cur.execute(
            "SELECT COUNT(*) FROM passage_persons WHERE source_layer NOT IN ('matn', 'isnad')"
        ).fetchone()[0]
        if invalid_person_layers != 0:
            errors.append(f"G4_INVALID_PERSON_LAYER: {invalid_person_layers} passage_persons rows have invalid source_layer")

        # Verify dates event_layer validity
        invalid_date_layers = cur.execute(
            "SELECT COUNT(*) FROM events_chronology WHERE event_layer NOT IN ('historical', 'transmission')"
        ).fetchone()[0]
        if invalid_date_layers != 0:
            errors.append(f"G4_INVALID_DATE_LAYER: {invalid_date_layers} events_chronology rows have invalid event_layer")
    finally:
        conn.close()

    metrics = {
        "book_gate_reports_count": len(book_gate_reports),
        "lecture_gate_reports_count": len(lecture_gate_reports),
        "passages_count": sqlite_summary.get("table_counts", {}).get("passages", 0),
        "expected_raw_chars": sqlite_summary.get("expected_raw_chars", 0),
        "actual_passage_chars": sqlite_summary.get("actual_passage_chars", 0),
        "chars_lost": sqlite_summary.get("chars_lost", -1),
    }
    return (len(errors) == 0, errors, metrics)


def verify_gate_g5(
    db_path: Path,
    dim: int = 768,
    backend: str = "deterministic-arabic-mps",
) -> Tuple[bool, List[str], Dict[str, Any]]:
    """Gate G5: Verifies 100% 768-dim float32 BLOB coverage, 0 honorifics in concept text, and HybridSearchEngine."""
    errors: List[str] = []
    if not db_path.exists():
        return False, [f"G5_MISSING_SQLITE_DB: {db_path}"], {}

    norm_backend = _normalize_backend_name(backend)
    expected_blob_bytes = dim * 4
    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.cursor()
        tables = {
            r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
        }
        if "passage_embeddings" not in tables:
            errors.append("G5_MISSING_PASSAGE_EMBEDDINGS_TABLE: passage_embeddings table does not exist")
            return False, errors, {}
        if "gem_embeddings" not in tables:
            errors.append("G5_MISSING_GEM_EMBEDDINGS_TABLE: gem_embeddings table does not exist")
            return False, errors, {}

        total_passages = cur.execute("SELECT COUNT(*) FROM passages").fetchone()[0]
        p_rows = cur.execute(
            "SELECT passage_id, dim, embed_matn_text, embed_concept_text, vec_matn_blob, vec_concept_blob, matn_norm, concept_norm "
            "FROM passage_embeddings"
        ).fetchall()
        if not p_rows or len(p_rows) != total_passages:
            errors.append(
                f"G5_INCOMPLETE_PASSAGE_EMBEDDINGS: embedded={len(p_rows)} != passages={total_passages}"
            )

        for pid, e_dim, t_matn, t_concept, b_matn, b_concept, m_norm, c_norm in p_rows:
            if not t_matn or not t_concept:
                errors.append(f"G5_EMPTY_EMBED_TEXT: passage {pid} has empty embed_matn_text or embed_concept_text")
            if t_concept and embed_mod.HONORIFIC_RANGE_RE.search(t_concept):
                errors.append(f"G5_HONORIFIC_LEAK_IN_CONCEPT: passage {pid} embed_concept_text contains honorifics")
            if b_matn is None or len(b_matn) != expected_blob_bytes:
                errors.append(
                    f"G5_INVALID_MATN_BLOB: passage {pid} vec_matn_blob len={0 if b_matn is None else len(b_matn)} "
                    f"(expected {expected_blob_bytes})"
                )
            else:
                vec = embed_mod.blob_to_vector(b_matn, dim=dim)
                norm = float(math.sqrt(sum(float(x) * float(x) for x in vec)))
                if abs(norm - 1.0) > 1e-3:
                    errors.append(f"G5_UNNORMALIZED_MATN_VEC: passage {pid} norm={norm:.6f}")

            if b_concept is None or len(b_concept) != expected_blob_bytes:
                errors.append(
                    f"G5_INVALID_CONCEPT_BLOB: passage {pid} vec_concept_blob len={0 if b_concept is None else len(b_concept)} "
                    f"(expected {expected_blob_bytes})"
                )
            else:
                vec_c = embed_mod.blob_to_vector(b_concept, dim=dim)
                norm_c = float(math.sqrt(sum(float(x) * float(x) for x in vec_c)))
                if abs(norm_c - 1.0) > 1e-3:
                    errors.append(f"G5_UNNORMALIZED_CONCEPT_VEC: passage {pid} norm={norm_c:.6f}")

            if int(e_dim or 0) != dim:
                errors.append(f"G5_DIM_MISMATCH: passage {pid} dim={e_dim} != {dim}")

        total_gems = cur.execute("SELECT COUNT(*) FROM science_gems").fetchone()[0]
        g_rows = cur.execute(
            "SELECT gem_id, embed_matn_text, embed_concept_text, vec_matn_blob, vec_concept_blob FROM gem_embeddings"
        ).fetchall()
        if len(g_rows) != total_gems:
            errors.append(f"G5_INCOMPLETE_GEM_EMBEDDINGS: embedded={len(g_rows)} != science_gems={total_gems}")
        for gid, gm_text, gc_text, gm_blob, gc_blob in g_rows:
            if not gm_text or not gc_text:
                errors.append(f"G5_EMPTY_GEM_TEXT: gem {gid} has empty embed text")
            if gm_blob is None or len(gm_blob) != expected_blob_bytes or gc_blob is None or len(gc_blob) != expected_blob_bytes:
                errors.append(f"G5_INVALID_GEM_BLOB: gem {gid} invalid blob byte length (expected {expected_blob_bytes})")
    finally:
        conn.close()

    if errors:
        return False, errors, {}

    # Run HybridSearchEngine smoke & layer-isolation checks
    with search_mod.HybridSearchEngine(db_path, backend=norm_backend, dim=dim) as engine:
        hybrid_hits = engine.search("الفقه والعبادات والمعاملات", top_k=5, mode="hybrid")
        matn_hits = engine.search("الفقه والعبادات", top_k=5, mode="matn")
        concept_hits = engine.search("الفقه والعبادات", top_k=5, mode="concept")
        gem_hits = engine.search_gems("القاعدة", top_k=5, mode="hybrid")

    if not hybrid_hits:
        errors.append("G5_HYBRID_SEARCH_EMPTY: HybridSearchEngine returned 0 results on populated DB")
    if not matn_hits or not concept_hits:
        errors.append("G5_VECTOR_SEARCH_EMPTY: matn or concept vector search returned 0 results")

    metrics = {
        "passages_embedded": len(p_rows),
        "gems_embedded": len(g_rows),
        "vector_dim": dim,
        "blob_bytes": expected_blob_bytes,
        "hybrid_hits_count": len(hybrid_hits),
        "gem_hits_count": len(gem_hits),
    }
    return (len(errors) == 0, errors, metrics)


# ============================================================================
# Master Orchestrator Pipeline (Stages 0..5)
# ============================================================================


def _load_or_init_state(state_path: Path, person_id: str, person_name: str, person_work_dir: Path) -> Dict[str, Any]:
    if state_path.exists():
        try:
            return json.loads(state_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {
        "person_id": person_id,
        "person_name": person_name,
        "work_dir": str(person_work_dir),
        "created_at": _utc_now(),
        "updated_at": _utc_now(),
        "overall_status": "IN_PROGRESS",
        "stages": {},
    }


def _save_state(state_path: Path, state: Dict[str, Any]) -> None:
    state["updated_at"] = _utc_now()
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def orchestrate_person(
    name: str,
    work_dir: str | Path,
    person_id: Optional[str] = None,
    youtube_urls: Optional[List[str]] = None,
    archive_ids: Optional[List[str]] = None,
    index_pdfs: Optional[List[str]] = None,
    books_json: Optional[str] = None,
    offline_fixture: Optional[str] = None,
    series_transcripts_dir: Optional[str | Path] = None,
    book_inputs: Optional[List[str | Path]] = None,
    shamela_db_dir: Optional[str | Path] = None,
    auto_ingest_shamela_books: bool = True,
    max_auto_books: int = 1,
    preferred_model: str = "gemini-3.8-flash-high",
    quota_override: Optional[Dict[str, Any]] = None,
    embedding_backend: str = "deterministic-arabic-mps",
    embedding_dim: int = 768,
    from_stage: int = 0,
    to_stage: int = 5,
    resume: bool = True,
    force: bool = False,
) -> Dict[str, Any]:
    """Runs the 6-stage Master Orchestrator pipeline with Hard Verification Gates G0..G5."""
    pid = discovery_mod.normalize_person_id(name, explicit_id=person_id)
    person_work_dir = Path(work_dir).resolve() / pid
    person_work_dir.mkdir(parents=True, exist_ok=True)

    dir_00_quota = person_work_dir / "00_quota"
    dir_01_discovery = person_work_dir / "01_discovery"
    dir_02_curated = person_work_dir / "02_curated"
    dir_03_extracted = person_work_dir / "03_extracted"
    dir_04_knowledge = person_work_dir / "04_knowledge_db"
    dir_05_reports = person_work_dir / "05_reports"

    for d in (dir_00_quota, dir_01_discovery, dir_02_curated, dir_03_extracted, dir_04_knowledge, dir_05_reports):
        d.mkdir(parents=True, exist_ok=True)

    state_path = person_work_dir / "pipeline_state.json"
    state = _load_or_init_state(state_path, pid, name, person_work_dir)

    quota_report_path = dir_00_quota / "quota_guard_report.json"
    raw_discovery_path = dir_01_discovery / f"{pid}_raw.json"
    curated_json_path = dir_02_curated / f"{pid}.json"
    curated_db_path = dir_02_curated / "curated.db"
    curated_series_root = dir_02_curated / "series"
    extracted_series_person_dir = dir_03_extracted / "series" / pid
    extracted_books_dir = dir_03_extracted / "books"
    usdb_sqlite_path = dir_04_knowledge / f"{pid}_objects.sqlite"

    def _should_run(stage_num: int, artifact_path: Path) -> bool:
        if stage_num < from_stage or stage_num > to_stage:
            return False
        if force or not resume:
            return True
        st_entry = state.get("stages", {}).get(str(stage_num), {})
        if st_entry.get("status") == "PASS" and artifact_path.exists():
            return False
        return True

    def _record_stage(stage_num: int, stage_name: str, gate_id: str, passed: bool, metrics: Dict[str, Any], errors: List[str]) -> None:
        state.setdefault("stages", {})[str(stage_num)] = {
            "name": stage_name,
            "gate": gate_id,
            "status": "PASS" if passed else "FAIL",
            "completed_at": _utc_now(),
            "metrics": metrics,
            "errors": errors,
        }
        if not passed:
            state["overall_status"] = "FAIL"
            _save_state(state_path, state)
            raise OrchestrationGateError(gate_id, stage_num, errors, details=metrics)
        _save_state(state_path, state)

    # -------------------------------------------------------------------------
    # STAGE 0: Quota & Lean CLI Guard (agy-lean-cli)
    # -------------------------------------------------------------------------
    if _should_run(0, quota_report_path):
        lean_home_dir = agy_lean.prepare_lean_home()
        isolation_info = agy_lean.verify_lean_home_isolation(lean_home_dir)
        selected_model_name, selected_model_quota = agy_lean.select_best_model(
            preferred_model=preferred_model,
            background=True,
            auto_fallback=True,
            qdata=quota_override,
        )
        selected_model_info = dict(selected_model_quota)
        selected_model_info["selected_model"] = selected_model_name
        quota_report = {
            "checked_at": _utc_now(),
            "preferred_model": preferred_model,
            "selected_model_info": selected_model_info,
            "isolation_info": isolation_info,
        }
        quota_report_path.write_text(json.dumps(quota_report, ensure_ascii=False, indent=2), encoding="utf-8")
        g0_ok, g0_errors = verify_gate_g0(quota_report)
        _record_stage(
            0,
            "stage0_quota_and_lean_guard",
            "G0",
            g0_ok,
            {
                "selected_model": selected_model_name,
                "remaining_pct": selected_model_info.get("remaining_pct"),
                "isolated": isolation_info.get("isolated"),
            },
            g0_errors,
        )

    # -------------------------------------------------------------------------
    # STAGE 1: Multi-Source Discovery Intake (person-discovery-intake)
    # -------------------------------------------------------------------------
    if _should_run(1, raw_discovery_path):
        discovery_mod.discover_person(
            name=name,
            person_id=pid,
            youtube_urls=youtube_urls or [],
            archive_ids=archive_ids or [],
            index_pdfs=index_pdfs or [],
            books_json=books_json,
            offline_fixture=offline_fixture,
            resolve_redirects=False,
            fetch_live_unlisted_playlists=False,
            output_path=str(raw_discovery_path),
        )
        g1_ok, g1_errors, g1_metrics = verify_gate_g1(raw_discovery_path)
        _record_stage(1, "stage1_discovery_intake", "G1", g1_ok, g1_metrics, g1_errors)

    # -------------------------------------------------------------------------
    # STAGE 2: Automated 9-Stage Curation (sheikh-curation v2.0)
    # -------------------------------------------------------------------------
    if _should_run(2, curated_json_path):
        curation_res = curation_mod.auto_curate_person(
            raw_input=raw_discovery_path,
            output_json_path=curated_json_path,
            output_series_dir=curated_series_root,
            db_path=curated_db_path,
        )
        g2_ok, g2_errors, g2_metrics = verify_gate_g2(
            curated_json_path=curated_json_path,
            curated_db_path=curated_db_path,
            curated_series_root=curated_series_root,
            curation_report=curation_res.get("report"),
        )
        _record_stage(2, "stage2_curation_9stage", "G2", g2_ok, g2_metrics, g2_errors)

    # -------------------------------------------------------------------------
    # STAGE 3: Dual-Track Extraction (sheikh-series-pipeline + turath-pdf-to-text)
    # -------------------------------------------------------------------------
    stage3_marker = dir_03_extracted / ".stage3_complete.json"
    if _should_run(3, stage3_marker):
        extracted_series_person_dir.mkdir(parents=True, exist_ok=True)
        extracted_books_dir.mkdir(parents=True, exist_ok=True)

        curated_data = json.loads(curated_json_path.read_text(encoding="utf-8"))
        raw_discovery_data = json.loads(raw_discovery_path.read_text(encoding="utf-8"))

        # Map video_id -> optional inline transcript from raw discovery fixture (playlists or videos)
        inline_transcripts: Dict[str, str] = {}
        for pl in raw_discovery_data.get("playlists", []):
            for entry in pl.get("entries") or pl.get("videos") or []:
                vid = entry.get("video_id") or entry.get("yt_id") or entry.get("vid")
                if vid and entry.get("transcript_text"):
                    inline_transcripts[vid] = entry["transcript_text"]
        for v in raw_discovery_data.get("videos", []):
            vid = v.get("video_id") or v.get("yt_id") or v.get("vid")
            if vid and v.get("transcript_text"):
                inline_transcripts[vid] = v["transcript_text"]

        # Map video_id -> file from series_transcripts_dir (recursive) and match series folders across 4 naming schemes
        external_vid_files: Dict[str, Path] = {}
        ext_root = Path(series_transcripts_dir) if series_transcripts_dir else None
        if ext_root and ext_root.exists():
            for tf in ext_root.rglob("*.txt"):
                external_vid_files[tf.stem] = tf
                m_vid = re.match(r"^\d+_(.+)$", tf.stem)
                if m_vid:
                    external_vid_files[m_vid.group(1)] = tf

        matched_ext_series_dirs = _match_external_series_dirs(
            ext_root=ext_root,
            curated_series=curated_data.get("series", []),
        )

        curated_updated = False
        transcribed_series_ids: set[str] = set()

        # Track 3A: Copy _meta.json for each curated series and stage + sanitize transcripts
        for s_idx, s in enumerate(curated_data.get("series", []), 1):
            sid = s.get("series_id") or f"s{s_idx:03d}"
            src_sdir = curated_series_root / pid / sid
            dst_sdir = extracted_series_person_dir / sid
            dst_sdir.mkdir(parents=True, exist_ok=True)
            if (src_sdir / "_meta.json").exists():
                shutil.copy2(src_sdir / "_meta.json", dst_sdir / "_meta.json")

            matched_ext_sdir = matched_ext_series_dirs.get(sid)
            ext_sdir_vid_map: Dict[str, Path] = {}
            if matched_ext_sdir and matched_ext_sdir.is_dir():
                for tf in sorted(matched_ext_sdir.glob("*.txt")):
                    ext_sdir_vid_map[tf.stem] = tf
                    m_v = re.match(r"^\d+_(.+)$", tf.stem)
                    if m_v:
                        ext_sdir_vid_map[m_v.group(1)] = tf

            matched_ep_vids: set[str] = set()
            lessons_list = s.get("lessons") or s.get("episodes", [])
            for ep_idx, ep in enumerate(lessons_list, 1):
                vid = ep.get("yt_id") or ep.get("video_id") or ep.get("vid") or ""
                ep_num = ep.get("episode_num") or ep_idx
                # Clean vid for LESSON_TXT_RE compatibility (alphanumeric, _, -, 6..20 chars)
                safe_vid = re.sub(r"[^A-Za-z0-9_-]", "", vid)[:20]
                if len(safe_vid) < 6:
                    safe_vid = (safe_vid + "000000")[:6]
                prefix = f"{int(ep_num):03d}_{safe_vid}"
                target_txt = dst_sdir / f"{prefix}.txt"
                target_align = dst_sdir / f"{prefix}.align.json"
                target_meta = dst_sdir / f"{prefix}.meta.json"

                if not target_txt.exists():
                    src_tf = ext_sdir_vid_map.get(vid) or external_vid_files.get(vid)
                    if src_tf and src_tf.exists():
                        shutil.copy2(src_tf, target_txt)
                        matched_ep_vids.add(vid)
                        align_cand = src_tf.with_suffix(".align.json")
                        if align_cand.exists():
                            shutil.copy2(align_cand, target_align)
                        meta_cand = src_tf.with_suffix(".meta.json")
                        if meta_cand.exists():
                            shutil.copy2(meta_cand, target_meta)
                    elif vid in inline_transcripts:
                        target_txt.write_text(inline_transcripts[vid], encoding="utf-8")
                        matched_ep_vids.add(vid)
                else:
                    matched_ep_vids.add(vid)

                if target_txt.exists():
                    ep["has_transcript"] = 1
                    if not target_meta.exists():
                        target_meta.write_text(
                            json.dumps(
                                {
                                    "video_id": vid,
                                    "title": ep.get("title", ""),
                                    "part_number": int(ep_num),
                                    "series_id": sid,
                                    "speaker": name,
                                },
                                ensure_ascii=False,
                                indent=2,
                            ),
                            encoding="utf-8",
                        )

            # Copy any additional lesson transcripts from matched_ext_sdir that were not already mapped by vid
            if matched_ext_sdir and matched_ext_sdir.is_dir():
                for item in sorted(matched_ext_sdir.iterdir()):
                    if not item.is_file() or item.name == "_meta.json":
                        continue
                    if item.suffix == ".txt":
                        m_v = re.match(r"^\d+_(.+)$", item.stem)
                        raw_v = m_v.group(1) if m_v else item.stem
                        if raw_v in matched_ep_vids:
                            continue
                        dst_txt = dst_sdir / item.name
                        if not dst_txt.exists():
                            shutil.copy2(item, dst_txt)
                        for ext_suf in (".align.json", ".meta.json"):
                            sib = item.with_suffix(ext_suf)
                            if sib.exists() and not (dst_sdir / sib.name).exists():
                                shutil.copy2(sib, dst_sdir / sib.name)

            txt_files_in_dir = sorted(dst_sdir.glob("*.txt"))
            if txt_files_in_dir:
                transcribed_series_ids.add(sid)
                # Sanitize all .txt transcripts in dst_sdir FIRST
                sanitize_mod.process_dir(str(dst_sdir), dry_run=False)
                for txt_fp in sorted(dst_sdir.glob("*.txt")):
                    raw_t = txt_fp.read_text(encoding="utf-8")
                    clean_t, extra_reasons = strip_all_preambles(raw_t)
                    if extra_reasons and clean_t and clean_t != raw_t:
                        txt_fp.write_text(clean_t, encoding="utf-8")

                # Then generate word-level CTC .align.json for any sanitized .txt missing .align.json
                for txt_fp in sorted(dst_sdir.glob("*.txt")):
                    align_fp = dst_sdir / f"{txt_fp.stem}.align.json"
                    if not align_fp.exists():
                        clean_txt = txt_fp.read_text(encoding="utf-8")
                        align_payload = _build_word_ctc_align_payload(clean_txt)
                        align_fp.write_text(json.dumps(align_payload, ensure_ascii=False), encoding="utf-8")

                # Sync transcribed_count & aligned_count in _meta.json (both dst_sdir and src_sdir) and curated_data
                final_txts = sorted(dst_sdir.glob("*.txt"))
                final_aligns = sorted(dst_sdir.glob("*.align.json"))
                s["transcribed_count"] = len(final_txts)
                s["aligned_count"] = len(final_aligns)
                curated_updated = True

                for meta_target in (dst_sdir / "_meta.json", src_sdir / "_meta.json"):
                    if meta_target.exists():
                        try:
                            m_obj = json.loads(meta_target.read_text(encoding="utf-8"))
                            m_obj["transcribed_count"] = len(final_txts)
                            m_obj["aligned_count"] = len(final_aligns)
                            for m_ep in m_obj.get("lessons") or m_obj.get("episodes", []):
                                m_vid = m_ep.get("yt_id") or m_ep.get("video_id") or m_ep.get("vid") or ""
                                if m_vid in matched_ep_vids:
                                    m_ep["has_transcript"] = 1
                            meta_target.write_text(
                                json.dumps(m_obj, ensure_ascii=False, indent=2),
                                encoding="utf-8",
                            )
                        except Exception:
                            pass

        if curated_updated:
            curated_json_path.write_text(json.dumps(curated_data, ensure_ascii=False, indent=2), encoding="utf-8")
            if curated_db_path.exists():
                try:
                    c_conn = sqlite3.connect(str(curated_db_path))
                    for s in curated_data.get("series", []):
                        sid_u = s.get("series_id")
                        tc_u = int(s.get("transcribed_count", 0))
                        if sid_u and tc_u > 0:
                            c_conn.execute(
                                "UPDATE series SET transcribed_count = ? WHERE series_id = ?",
                                (tc_u, sid_u),
                            )
                            for ep in s.get("lessons") or s.get("episodes", []):
                                if ep.get("has_transcript"):
                                    evid = ep.get("yt_id") or ep.get("video_id") or ""
                                    if evid:
                                        c_conn.execute(
                                            "UPDATE lessons SET has_transcript = 1 WHERE series_id = ? AND yt_id = ?",
                                            (sid_u, evid),
                                        )
                    c_conn.commit()
                    c_conn.close()
                except Exception:
                    pass

        # Track 3B: Process written books via pdf_to_preflight_adapter (including Shamela4 JSONL books)
        resolved_shamela_db = Path(shamela_db_dir) if shamela_db_dir else DEFAULT_SHAMELA_DB_DIR
        all_book_sources: List[Dict[str, Any]] = []
        seen_book_paths: set[str] = set()

        def _stage_book_source(
            raw_path: Path,
            idx_num: int,
            meta_hint: Dict[str, Any],
        ) -> Dict[str, Any]:
            raw_path = raw_path.resolve()
            slug_base = discovery_mod.normalize_person_id(
                str(meta_hint.get("title") or raw_path.stem.split("__")[-1] or f"book_{idx_num}")
            )
            slug = f"book_{idx_num:02d}_{slug_base}"
            # Detect Shamela4 directory (with pages.jsonl) or standalone .jsonl file
            if (raw_path.is_dir() and (raw_path / "pages.jsonl").exists()) or (
                raw_path.is_file() and raw_path.suffix.lower() == ".jsonl"
            ):
                staging_dir = dir_03_extracted / f"_staged_shamela_{slug}"
                converted = convert_shamela_to_preflight_dir(
                    src_path=raw_path,
                    staging_dir=staging_dir,
                    fallback_meta=meta_hint,
                )
                return {
                    "slug": slug,
                    "input_path": converted["input_path"],
                    "book_id": int(converted["book_id"]),
                    "science": converted["science"],
                    "title": converted["title"],
                    "author": converted["author"],
                    "death": str(converted["death"]),
                }

            b_meta = dict(meta_hint)
            if raw_path.is_file() and raw_path.suffix.lower() == ".json":
                try:
                    loaded = json.loads(raw_path.read_text(encoding="utf-8"))
                    if isinstance(loaded, dict):
                        for k, v in loaded.items():
                            b_meta.setdefault(k, v)
                except Exception:
                    pass
            title_val = str(b_meta.get("title") or f"كتاب {name} ({idx_num})")
            return {
                "slug": slug,
                "input_path": raw_path,
                "book_id": int(_extract_numeric_shamela_id(b_meta.get("book_id")) or (9000 + idx_num)),
                "science": _normalize_science_code(b_meta.get("science"), title_hint=title_val),
                "title": title_val,
                "author": str(b_meta.get("author") or name),
                "death": str(b_meta.get("death") or "750"),
            }

        for idx, b_in in enumerate(book_inputs or [], 1):
            b_path = Path(b_in).resolve()
            if not b_path.exists():
                continue
            seen_book_paths.add(str(b_path))
            all_book_sources.append(_stage_book_source(b_path, idx, {"author": name}))

        # Process books from Stage 1 discovery (`books`) and Stage 2 curated series (`matched_book`)
        disc_books = list(raw_discovery_data.get("books", []))
        # Prioritize books that have explicit local paths or inline pages first, then books linked to transcribed series
        transcribed_matched_books: List[Dict[str, Any]] = []
        other_matched_books: List[Dict[str, Any]] = []
        for s in curated_data.get("series", []):
            mb = s.get("matched_book")
            if isinstance(mb, dict) and mb.get("id") and not str(mb.get("id")).startswith("tafsir:"):
                if s.get("series_id") in transcribed_series_ids:
                    transcribed_matched_books.append(mb)
                else:
                    other_matched_books.append(mb)

        auto_ingested_count = 0
        for b_disc in disc_books + transcribed_matched_books + other_matched_books:
            local_p = b_disc.get("input_path") or b_disc.get("local_path")
            idx_next = len(all_book_sources) + 1
            if local_p and Path(local_p).exists():
                rp = str(Path(local_p).resolve())
                if rp in seen_book_paths:
                    continue
                seen_book_paths.add(rp)
                all_book_sources.append(_stage_book_source(Path(local_p), idx_next, b_disc))
            elif b_disc.get("pages") or b_disc.get("body_text"):
                slug = f"book_{idx_next:02d}_{discovery_mod.normalize_person_id(b_disc.get('title', f'book_{idx_next}'))}"
                staging_json = dir_03_extracted / f"_staged_{slug}.json"
                staging_json.write_text(json.dumps(b_disc, ensure_ascii=False, indent=2), encoding="utf-8")
                title_val = str(b_disc.get("title") or f"كتاب {name}")
                all_book_sources.append(
                    {
                        "slug": slug,
                        "input_path": staging_json,
                        "book_id": int(_extract_numeric_shamela_id(b_disc.get("book_id")) or (9000 + idx_next)),
                        "science": _normalize_science_code(b_disc.get("science"), title_hint=title_val),
                        "title": title_val,
                        "author": str(b_disc.get("author") or name),
                        "death": str(b_disc.get("death") or "750"),
                    }
                )
            elif auto_ingest_shamela_books and auto_ingested_count < max_auto_books:
                shamela_cand = resolve_shamela_book_path(b_disc, shamela_db_dir=resolved_shamela_db)
                if shamela_cand and shamela_cand.exists():
                    rp = str(shamela_cand.resolve())
                    if rp in seen_book_paths:
                        continue
                    seen_book_paths.add(rp)
                    all_book_sources.append(_stage_book_source(shamela_cand, idx_next, b_disc))
                    auto_ingested_count += 1

        for b_src in all_book_sources:
            out_bdir = extracted_books_dir / b_src["slug"]
            out_bdir.mkdir(parents=True, exist_ok=True)
            pdf_adapter_mod.convert_pdf_output_to_preflight(
                input_path=b_src["input_path"],
                out_dir=out_bdir,
                book_id=b_src["book_id"],
                science=b_src["science"],
                round_num=4,
                title=b_src["title"],
                author=b_src["author"],
                death=b_src["death"],
                juz=1,
                run_manifest_v4=True,
                deep_indexing_scripts_dir=DEEP_INDEXING_SCRIPTS,
            )

        g3_ok, g3_errors, g3_metrics = verify_gate_g3(
            extracted_series_person_dir=extracted_series_person_dir,
            extracted_books_dir=extracted_books_dir,
        )
        if g3_ok:
            stage3_marker.write_text(json.dumps(g3_metrics, ensure_ascii=False, indent=2), encoding="utf-8")
        _record_stage(3, "stage3_dual_track_extraction", "G3", g3_ok, g3_metrics, g3_errors)

    # -------------------------------------------------------------------------
    # STAGE 4: Unified Deep Indexing & Entity DB (turath-deep-indexing v5.7)
    # -------------------------------------------------------------------------
    if _should_run(4, usdb_sqlite_path):
        merged_books_all: List[Dict[str, Any]] = []
        book_gate_reports: List[Dict[str, Any]] = []
        shared_base_matn_override: Optional[Dict[str, Any]] = None

        # 4A: Audit and merge all extracted books
        if extracted_books_dir.exists():
            for bdir in sorted(extracted_books_dir.iterdir()):
                if not bdir.is_dir():
                    continue
                raw_round4_path = bdir / "raw_round4_books.json"
                if not raw_round4_path.exists():
                    continue
                raw_r_dict = json.loads(raw_round4_path.read_text(encoding="utf-8"))
                deep_overrides: Dict[str, Dict[str, Any]] = {}
                for sci, rb in raw_r_dict.items():
                    if not isinstance(rb, dict) or "parts" not in rb:
                        continue
                    custom_deep_path = bdir / f"r4_deep_{sci}.json"
                    if custom_deep_path.exists():
                        deep_payload = json.loads(custom_deep_path.read_text(encoding="utf-8"))
                        clauses = deep_payload.get("base_matn_clauses", [])
                    else:
                        deep_payload, clauses = auto_build_deep_book_extraction(sci, rb)
                        custom_deep_path.write_text(
                            json.dumps(deep_payload, ensure_ascii=False, indent=2), encoding="utf-8"
                        )
                    deep_overrides[sci] = deep_payload
                    if clauses and shared_base_matn_override is None:
                        shared_base_matn_override = {
                            "base_work_id": f"book:{rb.get('book_id', 9001)}",
                            "base_work_title": rb.get("meta", {}).get("title", ""),
                            "base_matn_clauses": clauses,
                        }

                books_out, gate_rep = merge_round_mod.audit_and_merge_round(
                    round_num=4,
                    raw_override=raw_r_dict,
                    deep_overrides=deep_overrides,
                    work_dir=bdir,
                )
                # Propagate explained_matn_clause_id onto aligned passages when present in deep_overrides
                for b_out in books_out:
                    sc_key = b_out["science"]
                    orig_deep_passages = deep_overrides.get(sc_key, {}).get("deep_toc_passages", [])
                    for p_aligned, p_orig in zip(b_out.get("deep_toc_passages", []), orig_deep_passages):
                        if p_orig.get("explained_matn_clause_id"):
                            p_aligned["explained_matn_clause_id"] = p_orig["explained_matn_clause_id"]
                            p_aligned["explained_matn_verbatim"] = p_orig.get("explained_matn_verbatim", "")

                merged_books_all.extend(books_out)
                book_gate_reports.append(gate_rep)

        combined_book_gate = {
            "round": 4,
            "passed": all(r.get("passed", False) for r in book_gate_reports),
            "books_audited": len(merged_books_all),
            "p0_error_count": sum(int(r.get("p0_error_count", 0)) for r in book_gate_reports),
            "reports": book_gate_reports,
        }
        (dir_04_knowledge / "round4_9_books_deep.json").write_text(
            json.dumps(merged_books_all, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (dir_04_knowledge / "gate_report_books.json").write_text(
            json.dumps(combined_book_gate, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        # 4B: Intake all extracted lecture series with transcripts
        all_merged_lectures_map: Dict[str, Dict[str, Any]] = {}
        all_series_manifests: List[Dict[str, Any]] = []
        lecture_gate_reports: List[Dict[str, Any]] = []

        if extracted_series_person_dir.exists():
            for sdir in sorted(extracted_series_person_dir.iterdir()):
                if not sdir.is_dir():
                    continue
                txt_files = list(sdir.glob("*.txt"))
                if not txt_files:
                    continue
                s_intake_out = dir_04_knowledge / "series_intake" / sdir.name
                intake_res = ytb_intake_mod.intake_series(
                    series_dir=sdir,
                    out_dir=s_intake_out,
                    base_matn_override=shared_base_matn_override,
                )
                for lid, rep in intake_res.get("gate_reports", {}).items():
                    lecture_gate_reports.append(rep)
                for lid, m_doc in intake_res.get("merged_lectures", {}).items():
                    all_merged_lectures_map[lid] = m_doc
                all_series_manifests.append(intake_res["series_manifest"])

        combined_lec_gate = {
            "round": "lectures_intake",
            "passed": all(r.get("passed", False) for r in lecture_gate_reports),
            "lectures_audited": len(all_merged_lectures_map),
            "p0_error_count": sum(int(r.get("p0_error_count", 0)) for r in lecture_gate_reports),
            "reports": lecture_gate_reports,
        }
        (dir_04_knowledge / "lectures_deep_merged.json").write_text(
            json.dumps(all_merged_lectures_map, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (dir_04_knowledge / "gate_report_lectures.json").write_text(
            json.dumps(combined_lec_gate, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        # 4C: Build Unified Scholarly Database SQLite (USDB v5.7)
        sqlite_summary = sqlite_builder_mod.build_objects_sqlite(
            db_path=usdb_sqlite_path,
            work_dir=dir_04_knowledge,
            books_list=merged_books_all,
            lectures_map=all_merged_lectures_map,
            courses_map={},
            series_manifests=all_series_manifests,
        )

        g4_ok, g4_errors, g4_metrics = verify_gate_g4(
            db_path=usdb_sqlite_path,
            sqlite_summary=sqlite_summary,
            book_gate_reports=book_gate_reports,
            lecture_gate_reports=lecture_gate_reports,
        )
        _record_stage(4, "stage4_deep_indexing_and_usdb_sqlite", "G4", g4_ok, g4_metrics, g4_errors)

    # -------------------------------------------------------------------------
    # STAGE 5: Dual-Vector Gemma-2 Embedding & Hybrid Search (turath-embedding-gemma2)
    # -------------------------------------------------------------------------
    stage5_marker = dir_05_reports / "orchestration_audit_report.json"
    if _should_run(5, stage5_marker):
        norm_backend = _normalize_backend_name(embedding_backend)
        embed_stats = embed_mod.embed_sqlite_corpus(
            db_path=usdb_sqlite_path,
            backend=norm_backend,
            dim=embedding_dim,
        )
        g5_ok, g5_errors, g5_metrics = verify_gate_g5(
            db_path=usdb_sqlite_path,
            dim=embedding_dim,
            backend=norm_backend,
        )
        g5_metrics["embed_stats"] = embed_stats
        _record_stage(5, "stage5_dual_vector_embedding_and_search", "G5", g5_ok, g5_metrics, g5_errors)

    state["overall_status"] = "PASS"
    _save_state(state_path, state)

    # Write final machine-readable and human-readable reports in 05_reports/
    audit_report = {
        "person_id": pid,
        "person_name": name,
        "completed_at": _utc_now(),
        "overall_status": state["overall_status"],
        "usdb_sqlite_path": str(usdb_sqlite_path),
        "stages": state["stages"],
    }
    stage5_marker.write_text(json.dumps(audit_report, ensure_ascii=False, indent=2), encoding="utf-8")

    md_lines = [
        f"# Orchestration Report: {name} (`{pid}`)",
        "",
        f"- **Overall Status**: `{state['overall_status']}`",
        f"- **Completed At**: `{audit_report['completed_at']}`",
        f"- **Unified Knowledge DB**: `{usdb_sqlite_path}`",
        "",
        "## Hard Verification Gates Summary",
        "",
        "| Stage | Name | Gate | Status | Key Metrics |",
        "| :--- | :--- | :--- | :--- | :--- |",
    ]
    for s_num in sorted(state["stages"].keys(), key=int):
        st = state["stages"][s_num]
        metrics_compact = json.dumps(st.get("metrics", {}), ensure_ascii=False)
        md_lines.append(
            f"| Stage {s_num} | `{st['name']}` | **{st['gate']}** | `{st['status']}` | `{metrics_compact}` |"
        )

    (dir_05_reports / "ORCHESTRATION_REPORT.md").write_text("\n".join(md_lines) + "\n", encoding="utf-8")
    return audit_report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Master End-to-End Orchestrator: Person to Unified Knowledge Database (USDB v5.7)"
    )
    parser.add_argument("--name", required=True, help="Scholar/author Arabic name")
    parser.add_argument("--person-id", default=None, help="Explicit ASCII person_id slug")
    parser.add_argument("--work-dir", required=True, help="Root workspace directory")
    parser.add_argument("--youtube-url", action="append", default=[], help="YouTube channel/playlist URL")
    parser.add_argument("--archive-id", action="append", default=[], help="Archive.org identifier")
    parser.add_argument("--index-pdf", action="append", default=[], help="PDF index file containing links")
    parser.add_argument("--books-json", default=None, help="JSON file of book metadata")
    parser.add_argument(
        "--offline-fixture",
        "--discovery-fixture",
        "--offline-bundle",
        dest="offline_fixture",
        default=None,
        help="Offline discovery fixture JSON",
    )
    parser.add_argument("--series-transcripts-dir", default=None, help="Directory of pre-extracted transcripts")
    parser.add_argument(
        "--book-input",
        "--books-pages-dir",
        dest="book_input",
        action="append",
        default=[],
        help="Path to PDF book output dir, Shamela4 book dir, .jsonl, or JSON",
    )
    parser.add_argument(
        "--shamela-db-dir",
        default=None,
        help="Path to local Shamela4_Full_DB directory for automatic book resolution",
    )
    parser.add_argument(
        "--no-auto-shamela-books",
        action="store_true",
        help="Disable automatic Shamela4 book ingestion from discovered/matched books",
    )
    parser.add_argument(
        "--max-auto-books",
        type=int,
        default=1,
        help="Maximum number of Shamela4 books to auto-ingest when not explicitly passed via --book-input",
    )
    parser.add_argument("--preferred-model", default="gemini-3.8-flash-high", help="Preferred model for Stage 0")
    parser.add_argument(
        "--embedding-backend",
        default="deterministic-arabic-mps",
        choices=["auto", "ollama", "sentence-transformers", "genai", "deterministic", "deterministic-arabic-mps"],
    )
    parser.add_argument("--embedding-dim", type=int, default=768, help="Embedding vector dimensionality")
    parser.add_argument("--from-stage", type=int, default=0, choices=[0, 1, 2, 3, 4, 5])
    parser.add_argument("--to-stage", type=int, default=5, choices=[0, 1, 2, 3, 4, 5])
    parser.add_argument("--no-resume", action="store_true", help="Disable resuming from passed stages")
    parser.add_argument("--resume", action="store_true", help="Resume from passed stages (default behavior)")
    parser.add_argument("--run-sample-queries", action="store_true", help="Run sample hybrid queries in Stage 5 (default behavior)")
    parser.add_argument("--force", action="store_true", help="Force re-running all stages in range")

    args = parser.parse_args()
    report = orchestrate_person(
        name=args.name,
        work_dir=args.work_dir,
        person_id=args.person_id,
        youtube_urls=args.youtube_url,
        archive_ids=args.archive_id,
        index_pdfs=args.index_pdf,
        books_json=args.books_json,
        offline_fixture=args.offline_fixture,
        series_transcripts_dir=args.series_transcripts_dir,
        book_inputs=args.book_input,
        shamela_db_dir=args.shamela_db_dir,
        auto_ingest_shamela_books=not args.no_auto_shamela_books,
        max_auto_books=args.max_auto_books,
        preferred_model=args.preferred_model,
        embedding_backend=args.embedding_backend,
        embedding_dim=args.embedding_dim,
        from_stage=args.from_stage,
        to_stage=args.to_stage,
        resume=not args.no_resume,
        force=args.force,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
