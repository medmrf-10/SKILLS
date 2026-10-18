#!/usr/bin/env python3
"""
USDB v5.7 — Canonical Relational Entity Database Builder (`scripts/build_objects_sqlite.py`).
Transforms `turath-deep-indexing` outputs:
  - Heritage Books merged via `merge_round.py` (`round*_9_books_deep.json` / `all_9_books_deep.json`)
  - Spoken Audio/Video Lectures merged via `merge_lecture.py` / `ytb_to_usdb_intake.py` (`lectures_deep_merged.json`)
  - Technical & Educational Courses merged via `merge_course.py` (`courses_deep_merged.json`)
  - Cross-Corpus Knowledge Graph (`cross_corpus_graph.json`)
into a normalized relational SQLite + FTS5 database (`objects.sqlite`) with 11 core tables,
1 FTS5 virtual table (`passages_fts`), and full join indexes compatible with `turath-embedding-gemma2`.
"""
import argparse
import json
import os
import re
import sqlite3
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

import build_cross_corpus_graph as bcg
import merge_round as mr
import ytb_to_usdb_intake as yti


KNOWN_PERSON_DEATH_HIJRI = {
    "الامام محمد بن يوسف السنوسي": 895,
    "الامام ابو الحسن الاشعري": 324,
    "القاضي ابو بكر الباقلاني": 403,
    "امام الحرمين ابو المعالي الجويني": 478,
    "الامام ابو حامد الغزالي": 505,
    "الامام فخر الدين الرازي": 606,
    "الامام مالك بن انس": 179,
    "الامام محمد بن ادريس الشافعي": 204,
    "الامام ابو حنيفه النعمان": 150,
    "الامام احمد بن حنبل": 241,
    "الامام محمد بن اسماعيل البخاري": 256,
    "الامام مسلم بن الحجاج": 261,
    "العلامه عبد الرحمن الاخضري": 983,
    "الامام ابو اسحاق الشاطبي": 790,
    "احمد بن عبد الحليم بن تيميه": 728,
    "ابن قيم الجوزيه": 751,
    "الحافظ اسماعيل بن كثير": 774,
    "الامام ابو عبد الله القرطبي": 671,
    "الامام ابن جرير الطبري": 310,
    "القاضي ابن رشد": 595,
    "العلامه عبد الرحمن بن خلدون": 808,
    "عمر بن الخطاب رضي الله عنه": 23,
    "ابو بكر الصديق رضي الله عنه": 13,
    "عثمان بن عفان رضي الله عنه": 35,
    "علي بن ابي طالب رضي الله عنه": 40,
    "عبد الله بن عباس رضي الله عنهما": 68,
    "عبد الله بن عمر رضي الله عنهما": 73,
    "عايشه ام المومنين رضي الله عنها": 58,
    "ابو هريره رضي الله عنه": 57,
    "انس بن مالك رضي الله عنه": 93,
}


SCHEMA_DDL = """
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS sources (
    source_id TEXT PRIMARY KEY,
    source_type TEXT,
    title TEXT,
    author_or_sheikh TEXT,
    science TEXT,
    archetype TEXT,
    metadata_json TEXT
);

CREATE TABLE IF NOT EXISTS series (
    series_id TEXT PRIMARY KEY,
    source_id TEXT,
    title TEXT,
    sheikh TEXT,
    science TEXT,
    state TEXT,
    total_lessons INTEGER,
    metadata_json TEXT
);

CREATE TABLE IF NOT EXISTS lessons_or_parts (
    part_id TEXT PRIMARY KEY,
    source_id TEXT,
    series_id TEXT,
    part_number INTEGER,
    title TEXT,
    yt_id TEXT,
    dur_s REAL,
    page_start INTEGER,
    page_end INTEGER,
    raw_char_count INTEGER
);

CREATE TABLE IF NOT EXISTS passages (
    passage_id TEXT PRIMARY KEY,
    source_id TEXT,
    series_id TEXT,
    part_id TEXT,
    part_number INTEGER,
    passage_index INTEGER,
    sub_heading TEXT,
    raw_text TEXT,
    clean_matn TEXT,
    isnad_prefix TEXT,
    summary TEXT,
    topics_json TEXT,
    search_queries_json TEXT,
    start_sec REAL,
    end_sec REAL,
    youtube_timestamp_url TEXT,
    page_num INTEGER,
    embed_matn_text TEXT,
    embed_concept_text TEXT
);

CREATE VIRTUAL TABLE IF NOT EXISTS passages_fts USING fts5(
    passage_id UNINDEXED,
    sub_heading,
    raw_text,
    clean_matn,
    summary,
    topics_text,
    search_queries_text
);

CREATE TABLE IF NOT EXISTS persons (
    person_id TEXT PRIMARY KEY,
    canonical_name TEXT,
    role_or_sect TEXT,
    death_year_hijri INTEGER,
    aliases_json TEXT
);

CREATE TABLE IF NOT EXISTS passage_persons (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    passage_id TEXT,
    person_id TEXT,
    mentioned_name TEXT,
    canonical_name TEXT,
    source_layer TEXT CHECK(source_layer IN ('isnad', 'matn')),
    role TEXT
);

CREATE TABLE IF NOT EXISTS places (
    place_id TEXT PRIMARY KEY,
    canonical_name TEXT,
    region_or_type TEXT,
    aliases_json TEXT
);

CREATE TABLE IF NOT EXISTS passage_places (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    passage_id TEXT,
    place_id TEXT,
    mentioned_name TEXT,
    canonical_name TEXT
);

CREATE TABLE IF NOT EXISTS events_chronology (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    passage_id TEXT,
    source_id TEXT,
    year_hijri INTEGER,
    year_raw TEXT,
    is_approximate INTEGER,
    event_title TEXT,
    event_layer TEXT CHECK(event_layer IN ('historical', 'transmission'))
);

CREATE TABLE IF NOT EXISTS stories_cases (
    story_id INTEGER PRIMARY KEY AUTOINCREMENT,
    passage_id TEXT,
    source_id TEXT,
    part_number INTEGER,
    story_type TEXT,
    title TEXT,
    anchor_start TEXT,
    summary TEXT,
    lesson TEXT
);

CREATE TABLE IF NOT EXISTS science_gems (
    gem_id TEXT PRIMARY KEY,
    passage_id TEXT,
    source_id TEXT,
    part_number INTEGER,
    title TEXT,
    category TEXT,
    verbatim_rule TEXT,
    polished_rule TEXT,
    explanation TEXT,
    start_sec REAL,
    end_sec REAL,
    youtube_timestamp_url TEXT
);

CREATE TABLE IF NOT EXISTS evidences (
    evidence_id INTEGER PRIMARY KEY AUTOINCREMENT,
    passage_id TEXT,
    source_id TEXT,
    evidence_type TEXT,
    surah_number INTEGER,
    ayah_start INTEGER,
    ayah_end INTEGER,
    surah_ayah_key TEXT,
    verbatim_text TEXT,
    hadith_source TEXT,
    footnote_ref TEXT
);

CREATE TABLE IF NOT EXISTS matn_triangulation (
    triangulation_id INTEGER PRIMARY KEY AUTOINCREMENT,
    passage_id TEXT,
    source_id TEXT,
    explained_matn_book_id TEXT,
    explained_matn_clause_id TEXT,
    explained_matn_verbatim TEXT,
    start_sec REAL,
    end_sec REAL
);

CREATE INDEX IF NOT EXISTS idx_passages_source_id ON passages(source_id);
CREATE INDEX IF NOT EXISTS idx_passages_series_id ON passages(series_id);
CREATE INDEX IF NOT EXISTS idx_passages_part_id ON passages(part_id);
CREATE INDEX IF NOT EXISTS idx_passage_persons_passage_id ON passage_persons(passage_id);
CREATE INDEX IF NOT EXISTS idx_passage_persons_person_id ON passage_persons(person_id);
CREATE INDEX IF NOT EXISTS idx_passage_persons_source_layer ON passage_persons(source_layer);
CREATE INDEX IF NOT EXISTS idx_passage_places_passage_id ON passage_places(passage_id);
CREATE INDEX IF NOT EXISTS idx_passage_places_place_id ON passage_places(place_id);
CREATE INDEX IF NOT EXISTS idx_events_chronology_passage_id ON events_chronology(passage_id);
CREATE INDEX IF NOT EXISTS idx_events_chronology_year_hijri ON events_chronology(year_hijri);
CREATE INDEX IF NOT EXISTS idx_stories_cases_passage_id ON stories_cases(passage_id);
CREATE INDEX IF NOT EXISTS idx_science_gems_passage_id ON science_gems(passage_id);
CREATE INDEX IF NOT EXISTS idx_evidences_passage_id ON evidences(passage_id);
CREATE INDEX IF NOT EXISTS idx_evidences_surah_ayah_key ON evidences(surah_ayah_key);
CREATE INDEX IF NOT EXISTS idx_matn_triangulation_passage_id ON matn_triangulation(passage_id);
CREATE INDEX IF NOT EXISTS idx_matn_triangulation_clause_id ON matn_triangulation(explained_matn_clause_id);
CREATE INDEX IF NOT EXISTS idx_matn_triangulation_book_id ON matn_triangulation(explained_matn_book_id);
"""


def make_person_id(norm_key: str) -> str:
    slug = re.sub(r"\s+", "_", norm_key.strip())
    return f"person:{slug}"


def make_place_id(canonical_name: str) -> str:
    norm_p = bcg.norm_ar(canonical_name)
    slug = re.sub(r"\s+", "_", norm_p.strip())
    return f"place:{slug}"


def extract_death_year(cname: str, per_dict: dict) -> int | None:
    if isinstance(per_dict.get("death_year_hijri"), int):
        return per_dict["death_year_hijri"]
    if isinstance(per_dict.get("death"), int):
        return per_dict["death"]
    m = re.search(r"\(\s*ت\s*([٠-٩0-9]+)\s*هـ?\s*\)", cname or "")
    if m:
        return int(m.group(1).translate(bcg.AR_DIGITS))
    norm_k = bcg.norm_ar(re.sub(r"\([^\)]*\)", "", cname or "").strip())
    if norm_k in KNOWN_PERSON_DEATH_HIJRI:
        return KNOWN_PERSON_DEATH_HIJRI[norm_k]
    return None


def derive_clean_matn_from_book_passage(p: dict) -> str:
    if p.get("clean_matn"):
        return p["clean_matn"]
    raw_text = p.get("raw_text", "")
    isnad_prefix = (p.get("isnad_prefix") or "").strip()
    matn_anc = (p.get("matn_start_anchor") or "").strip()
    if isnad_prefix and matn_anc:
        _, clean_m, _, _ = mr.validate_and_extract_isnad(raw_text, 0, matn_anc)
        if clean_m and clean_m != raw_text:
            return clean_m
    if isnad_prefix and isnad_prefix in raw_text:
        idx = raw_text.find(isnad_prefix)
        tail = raw_text[idx + len(isnad_prefix) :].strip()
        if tail:
            return tail
    return raw_text


VALID_CANONICAL_STORY_TYPES = {
    "historical_incident",
    "prophetic_sirah",
    "fiqhi_case",
    "scholarly_anecdote",
}


def classify_story_type(
    raw_type: str | None,
    title: str = "",
    anchor: str = "",
    summary: str = "",
    science: str = "",
) -> str:
    rt = (raw_type or "").strip()
    if rt in VALID_CANONICAL_STORY_TYPES:
        return rt
    probe = f"{title} {anchor} {summary}"
    for pat, st_type, _, _ in yti.STORY_AND_CASE_MARKERS:
        if pat.search(probe):
            return st_type
    if re.search(r"(?:غزوة|النبي|رسول\s+الله|سيرة|صحابي|يوم\s+بدر|يوم\s+أحد|خيبر)", probe):
        return "prophetic_sirah"
    if re.search(r"(?:سئل\s+الإمام|سئل\s+مالك|سئل\s+الشيخ|مناظرة|ناظر|قيل\s+للإمام|نادرة|موقف\s+علمي)", probe):
        return "scholarly_anecdote"
    if re.search(r"(?:خلافة|عهد|الدولة\s+الأموية|الدولة\s+العباسية|معاوية|وقعة|معركة|فتنة|تاريخية)", probe):
        return "historical_incident"
    if re.search(r"(?:فرائض|وضوء|صلاة|طهارة|بيع|طلاق|نكاح|لو\s+قال|لو\s+باع|مثاله|مسألة|تطبيق|فرع|نازلة)", probe):
        return "fiqhi_case"
    if science == "sirah":
        return "prophetic_sirah"
    if science in ("tari5",):
        return "historical_incident"
    if science in ("tarajim", "tazkia", "tazkiyah"):
        return "scholarly_anecdote"
    return "fiqhi_case"


def parse_evidence_fields(ev: dict, passage_fn_refs: list, raw_text: str = "") -> dict:
    ev_type_raw = (ev.get("type") or ev.get("evidence_type") or "").strip()
    ev_src = (ev.get("source") or ev.get("hadith_source") or ev.get("reference") or "").strip()
    v_txt = (ev.get("text") or ev.get("verbatim_text") or "").strip()
    fn_ref = ev.get("footnote_ref") or (",".join(str(x) for x in passage_fn_refs) if passage_fn_refs else None)

    is_quran = (
        "آية" in ev_type_raw
        or "قرآن" in ev_type_raw
        or "quran" in ev_type_raw.lower()
        or "سورة" in ev_src
    )
    if is_quran:
        akey, snum, anum, _ = bcg.parse_ayah_key(ev_src)
        ay_end = anum
        if ev_src:
            s_ascii = ev_src.translate(bcg.AR_DIGITS)
            m_rng = re.search(r":\s*(?:الآية\s*|آية\s*)?(\d+)\s*[-–]\s*(\d+)", s_ascii)
            if m_rng:
                anum = int(m_rng.group(1))
                ay_end = int(m_rng.group(2))
                if snum:
                    akey = f"{snum}:{anum}"
        return {
            "evidence_type": "quran",
            "surah_number": snum,
            "ayah_start": anum,
            "ayah_end": ay_end,
            "surah_ayah_key": akey,
            "verbatim_text": v_txt,
            "hadith_source": None,
            "footnote_ref": fn_ref,
        }
    norm_ev_type = "athar" if ev_type_raw in ("athar", "أثر") else "hadith"
    resolved_h_src = yti.resolve_hadith_source(v_txt, raw_text, ev_src)
    return {
        "evidence_type": norm_ev_type,
        "surah_number": None,
        "ayah_start": None,
        "ayah_end": None,
        "surah_ayah_key": None,
        "verbatim_text": v_txt,
        "hadith_source": resolved_h_src,
        "footnote_ref": fn_ref,
    }


def build_objects_sqlite(
    db_path: str | Path,
    work_dir: str | Path | None = None,
    books_list: list[dict] | None = None,
    lectures_map: dict | None = None,
    courses_map: dict | None = None,
    series_manifests: list[dict] | None = None,
) -> dict:
    db_file = Path(db_path).resolve()
    db_file.parent.mkdir(parents=True, exist_ok=True)
    if db_file.exists():
        db_file.unlink()

    wdir = Path(work_dir).resolve() if work_dir else db_file.parent

    # 1. Discover books if not explicitly provided
    if books_list is None:
        books_list = []
        cand_files = []
        if (wdir / "all_9_books_deep.json").exists():
            cand_files.append(wdir / "all_9_books_deep.json")
        for fp in sorted(wdir.glob("round*_9_books_deep.json")):
            cand_files.append(fp)
        for fp in cand_files:
            data = json.loads(fp.read_text(encoding="utf-8"))
            if isinstance(data, list):
                books_list.extend(b for b in data if isinstance(b, dict))
            elif isinstance(data, dict):
                books_list.extend(b for b in data.values() if isinstance(b, dict))

    # 2. Discover lectures if not explicitly provided
    if lectures_map is None:
        lec_fp = wdir / "lectures_deep_merged.json"
        if not lec_fp.exists() and (wdir / "usdb_v5" / "lectures_deep_merged.json").exists():
            lec_fp = wdir / "usdb_v5" / "lectures_deep_merged.json"
        lectures_map = json.loads(lec_fp.read_text(encoding="utf-8")) if lec_fp.exists() else {}

    # 3. Discover courses if not explicitly provided
    if courses_map is None:
        crs_fp = wdir / "courses_deep_merged.json"
        if not crs_fp.exists() and (wdir / "usdb_v5" / "courses_deep_merged.json").exists():
            crs_fp = wdir / "usdb_v5" / "courses_deep_merged.json"
        courses_map = json.loads(crs_fp.read_text(encoding="utf-8")) if crs_fp.exists() else {}

    # 4. Discover series manifests if not explicitly provided
    if series_manifests is None:
        series_manifests = []
        sm_fp = wdir / "series_intake_manifest.json"
        if sm_fp.exists():
            series_manifests.append(json.loads(sm_fp.read_text(encoding="utf-8")))

    conn = sqlite3.connect(str(db_file))
    cur = conn.cursor()
    cur.executescript(SCHEMA_DDL)

    persons_registry = {}  # person_id -> {canonical_name, role_or_sect, death_year_hijri, aliases: set()}
    places_registry = {}   # place_id -> {canonical_name, region_or_type, aliases: set()}
    book_alias_to_source_id = {}
    book_passages_by_source: dict[str, list[tuple[str, str]]] = {}  # source_id -> [(pid, raw_text), ...]
    book_clauses_inserted: set[tuple[str, str]] = set()             # (source_id, clause_id)

    def resolve_verbatim_year_raw(ch: dict, raw_text: str, hy: int | None) -> str:
        if ch.get("year_raw"):
            return str(ch["year_raw"])
        if hy is None:
            return ""
        # Check if raw_text contains an Arabic word-year phrase that evaluates to `hy`
        for m_wy in re.finditer(r"((?:سنة|عام|سنه)\s+[^\n.!؟،؛:()0-9٠-٩]{3,50})", raw_text or ""):
            phrase = m_wy.group(1).strip()
            if hy in mr.extract_date_years_from_text(phrase):
                return phrase
        return f"سنة {hy} هـ"

    def register_person(per: dict, raw_text: str, isnad_prefix: str, clean_matn: str) -> tuple[str, str, str, str, str] | None:
        cname_raw = (per.get("canonical_name") or per.get("mentioned_as") or "").strip()
        if not cname_raw:
            return None
        mentioned_name = (per.get("mentioned_as") or cname_raw).strip()
        cat = (per.get("category") or per.get("role_or_sect") or "").strip()
        role = (per.get("role") or cat or "علم").strip()

        norm_key, disp_name, ccat = bcg.canonicalize_person(cname_raw, cat)
        if not norm_key or len(norm_key) < 2:
            return None
        person_id = make_person_id(norm_key)

        # Determine strict source_layer ('isnad' vs 'matn')
        sl = (per.get("source_layer") or "").strip().lower()
        if sl not in ("isnad", "matn"):
            if isnad_prefix:
                resolved = mr.resolve_person_mentioned_as(
                    {"canonical_name": disp_name, "mentioned_as": mentioned_name},
                    raw_text,
                    isnad_prefix=isnad_prefix,
                    clean_matn=clean_matn,
                )
                sl = "isnad" if resolved.get("source_layer") == "isnad" else "matn"
            else:
                sl = "matn"

        death_yr = extract_death_year(cname_raw, per) or extract_death_year(disp_name, per)
        entry = persons_registry.setdefault(
            person_id,
            {
                "canonical_name": disp_name,
                "role_or_sect": ccat or cat or "علم",
                "death_year_hijri": death_yr,
                "aliases": set(),
            },
        )
        if not entry["death_year_hijri"] and death_yr:
            entry["death_year_hijri"] = death_yr
        if ccat and entry["role_or_sect"] in ("", "علم"):
            entry["role_or_sect"] = ccat
        entry["aliases"].add(cname_raw)
        entry["aliases"].add(mentioned_name)
        entry["aliases"].add(disp_name)

        return person_id, mentioned_name, disp_name, sl, role

    def register_place(pl: dict | str) -> tuple[str, str, str] | None:
        pl_obj = {"name_in_text": pl, "normalized_name": pl} if isinstance(pl, str) else dict(pl)
        mentioned = (pl_obj.get("name_in_text") or pl_obj.get("mentioned_as") or pl_obj.get("normalized_name") or "").strip()
        canonical = (pl_obj.get("normalized_name") or pl_obj.get("canonical_name") or mentioned).strip()
        if not canonical:
            return None
        place_id = make_place_id(canonical)
        region = (pl_obj.get("region_or_type") or pl_obj.get("category") or "حاضرة / إقليم تاريخي").strip()
        entry = places_registry.setdefault(
            place_id,
            {
                "canonical_name": canonical,
                "region_or_type": region,
                "aliases": set(),
            },
        )
        entry["aliases"].add(mentioned)
        entry["aliases"].add(canonical)
        return place_id, mentioned, canonical

    # --- A. Insert Books ---
    for bk in books_list:
        raw_bid = bk.get("book_id")
        source_id = str(bk.get("source_id") or f"book:{raw_bid}")
        science = bk.get("science", "tarajim")
        archetype = "normative_book" if science in mr.NORMATIVE_SCIENCES else "narrative_book"
        title = bk.get("title", "")
        author = bk.get("author", "")

        book_alias_to_source_id[str(raw_bid)] = source_id
        book_alias_to_source_id[source_id] = source_id
        if bk.get("base_work_id"):
            book_alias_to_source_id[str(bk["base_work_id"])] = source_id
        if bk.get("slug"):
            book_alias_to_source_id[str(bk["slug"])] = source_id
        if raw_bid == 3418 or "الأخضري" in title:
            book_alias_to_source_id["matn-al-akhdari"] = source_id
        if "الورقات" in title:
            book_alias_to_source_id["matn-al-waraqat"] = source_id
            book_alias_to_source_id["book:2176"] = source_id
        if "السنوسي" in title or "أم البراهين" in title:
            book_alias_to_source_id["umm-al-barahin"] = source_id
        if "التبيان" in title:
            book_alias_to_source_id["book:1969"] = source_id
        if "المنقذ" in title:
            book_alias_to_source_id["book:9246"] = source_id

        meta_json = json.dumps(
            {
                "book_id": raw_bid,
                "round": bk.get("round"),
                "science_ar": bk.get("science_ar"),
                "orig_parts_count": bk.get("orig_parts_count"),
                "total_chars": bk.get("total_chars"),
                "quality_gate": bk.get("quality_gate", {}),
            },
            ensure_ascii=False,
        )
        cur.execute(
            """
            INSERT OR REPLACE INTO sources (source_id, source_type, title, author_or_sheikh, science, archetype, metadata_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (source_id, "book", title, author, science, archetype, meta_json),
        )

        # Group book passages by part
        passages = bk.get("deep_toc_passages", [])
        by_part = {}
        for p in passages:
            pt = int(p.get("part", 1))
            by_part.setdefault(pt, []).append(p)

        toc_by_part = {int(t["part"]): t for t in bk.get("orig_toc", []) if "part" in t}
        for pt, p_list in sorted(by_part.items()):
            part_id = f"{source_id}:part:{pt}"
            t_info = toc_by_part.get(pt, {})
            part_title = t_info.get("effective_heading") or t_info.get("heading") or (p_list[0].get("parent_heading") if p_list else f"الجزء {pt}")
            pg_starts = [p["pg_start"] for p in p_list if isinstance(p.get("pg_start"), int)]
            pg_ends = [p["pg_end"] for p in p_list if isinstance(p.get("pg_end"), int)]
            pg_s = min(pg_starts) if pg_starts else (p_list[0].get("pg") if p_list else 1)
            pg_e = max(pg_ends) if pg_ends else pg_s
            raw_char_cnt = sum(len(p.get("raw_text", "")) for p in p_list)

            cur.execute(
                """
                INSERT OR REPLACE INTO lessons_or_parts
                (part_id, source_id, series_id, part_number, title, yt_id, dur_s, page_start, page_end, raw_char_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (part_id, source_id, None, pt, part_title, None, None, pg_s, pg_e, raw_char_cnt),
            )

            for p_idx, p in enumerate(p_list, start=1):
                pid = str(p.get("pid") or f"{raw_bid}:{pt}:{p_idx}")
                raw_text = p.get("raw_text", "")
                isnad_prefix = p.get("isnad_prefix") or ""
                clean_matn = derive_clean_matn_from_book_passage(p)
                sub_h = p.get("sub_heading", "")
                summary = p.get("summary", "")
                topics = p.get("topics") or []
                queries = p.get("search_queries") or []
                pg_num = p.get("pg") or p.get("pg_start") or pg_s
                emb_matn = p.get("embed_matn_text") or mr.clean_for_embed(clean_matn, science=science)
                emb_concept = p.get("embed_concept_text") or summary
                book_passages_by_source.setdefault(source_id, []).append(
                    (pid, f"{sub_h} {' '.join(topics)} {raw_text}")
                )

                cur.execute(
                    """
                    INSERT OR REPLACE INTO passages
                    (passage_id, source_id, series_id, part_id, part_number, passage_index, sub_heading,
                     raw_text, clean_matn, isnad_prefix, summary, topics_json, search_queries_json,
                     start_sec, end_sec, youtube_timestamp_url, page_num, embed_matn_text, embed_concept_text)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        pid,
                        source_id,
                        None,
                        part_id,
                        pt,
                        p_idx,
                        sub_h,
                        raw_text,
                        clean_matn,
                        isnad_prefix,
                        summary,
                        json.dumps(topics, ensure_ascii=False),
                        json.dumps(queries, ensure_ascii=False),
                        None,
                        None,
                        None,
                        pg_num,
                        emb_matn,
                        emb_concept,
                    ),
                )

                cur.execute(
                    """
                    INSERT INTO passages_fts
                    (passage_id, sub_heading, raw_text, clean_matn, summary, topics_text, search_queries_text)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        pid,
                        sub_h,
                        raw_text,
                        clean_matn,
                        summary,
                        " ، ".join(topics),
                        " ".join(queries),
                    ),
                )

                for per in p.get("persons", []):
                    reg = register_person(per, raw_text, isnad_prefix, clean_matn)
                    if reg:
                        per_id, ment_name, disp_name, s_layer, r_str = reg
                        cur.execute(
                            """
                            INSERT INTO passage_persons
                            (passage_id, person_id, mentioned_name, canonical_name, source_layer, role)
                            VALUES (?, ?, ?, ?, ?, ?)
                            """,
                            (pid, per_id, ment_name, disp_name, s_layer, r_str),
                        )

                for pl in p.get("places", []):
                    reg_pl = register_place(pl)
                    if reg_pl:
                        pl_id, ment_pl, can_pl = reg_pl
                        cur.execute(
                            """
                            INSERT INTO passage_places
                            (passage_id, place_id, mentioned_name, canonical_name)
                            VALUES (?, ?, ?, ?)
                            """,
                            (pid, pl_id, ment_pl, can_pl),
                        )

                for ch in p.get("chronology", []):
                    if not isinstance(ch, dict):
                        continue
                    hy = ch.get("hijri_year")
                    etag = (ch.get("event_tag") or ch.get("event_title") or ch.get("event") or "").strip()
                    raw_layer = (ch.get("event_layer") or "").strip()
                    ev_layer = "transmission" if raw_layer == "transmission" else "historical"
                    y_raw = resolve_verbatim_year_raw(ch, raw_text, hy if isinstance(hy, int) else None)
                    is_approx = 1 if (
                        ch.get("is_approximate")
                        or ch.get("year_source") in ("text_expanded", "metadata_inferred")
                        or any(w in (y_raw + " " + etag) for w in ("نيف", "بضع", "نحو", "قرابة"))
                    ) else 0
                    cur.execute(
                        """
                        INSERT INTO events_chronology
                        (passage_id, source_id, year_hijri, year_raw, is_approximate, event_title, event_layer)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (pid, source_id, hy if isinstance(hy, int) else None, y_raw, is_approx, etag, ev_layer),
                    )

                ev_list_book = list(p.get("evidences", []))
                seen_ev_norms_b = {
                    bcg.norm_ar(e.get("text") or e.get("verbatim_text") or "")
                    for e in ev_list_book
                    if isinstance(e, dict)
                }
                for auto_hev in yti.extract_hadith_evidences_from_text(clean_matn):
                    nh = bcg.norm_ar(auto_hev["text"])
                    if nh and not any(nh in ex or ex in nh for ex in seen_ev_norms_b if ex):
                        seen_ev_norms_b.add(nh)
                        ev_list_book.append(auto_hev)

                for ev in ev_list_book:
                    if not isinstance(ev, dict):
                        continue
                    ev_parsed = parse_evidence_fields(ev, p.get("fn_refs", []), raw_text=raw_text)
                    cur.execute(
                        """
                        INSERT INTO evidences
                        (passage_id, source_id, evidence_type, surah_number, ayah_start, ayah_end,
                         surah_ayah_key, verbatim_text, hadith_source, footnote_ref)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            pid,
                            source_id,
                            ev_parsed["evidence_type"],
                            ev_parsed["surah_number"],
                            ev_parsed["ayah_start"],
                            ev_parsed["ayah_end"],
                            ev_parsed["surah_ayah_key"],
                            ev_parsed["verbatim_text"],
                            ev_parsed["hadith_source"],
                            ev_parsed["footnote_ref"],
                        ),
                    )

                # Optional matn_triangulation on book passage if explicitly tagged
                if p.get("explained_matn_clause_id"):
                    book_clauses_inserted.add((source_id, str(p["explained_matn_clause_id"])))
                    cur.execute(
                        """
                        INSERT INTO matn_triangulation
                        (passage_id, source_id, explained_matn_book_id, explained_matn_clause_id, explained_matn_verbatim, start_sec, end_sec)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            pid,
                            source_id,
                            source_id,
                            p["explained_matn_clause_id"],
                            p.get("explained_matn_verbatim", ""),
                            None,
                            None,
                        ),
                    )

        # Book stories / applied_cases
        default_book_pid = f"{raw_bid}:1:1"
        if passages:
            default_book_pid = str(passages[0].get("pid") or default_book_pid)
        for st_idx, st in enumerate(bk.get("stories", []), start=1):
            st_pid = str(st.get("pid") or st.get("passage_id") or default_book_pid)
            st_part = int(st.get("part", 1))
            st_type = classify_story_type(
                st.get("story_type"),
                st.get("title", ""),
                st.get("anchor_start", ""),
                st.get("summary", ""),
                science,
            )
            cur.execute(
                """
                INSERT INTO stories_cases
                (passage_id, source_id, part_number, story_type, title, anchor_start, summary, lesson)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    st_pid,
                    source_id,
                    st_part,
                    st_type,
                    st.get("title", ""),
                    st.get("anchor_start", ""),
                    st.get("summary", ""),
                    st.get("lesson", ""),
                ),
            )

        # Book science_gems
        for g_idx, g in enumerate(bk.get("science_gems", []), start=1):
            gem_id = str(g.get("gem_id") or f"{source_id}:G{g_idx}")
            g_pid = str(g.get("pid") or g.get("passage_id") or default_book_pid)
            g_part = int(g.get("part", 1))
            v_rule = g.get("verbatim_rule", "")
            p_rule = g.get("polished_rule") or v_rule
            cur.execute(
                """
                INSERT OR REPLACE INTO science_gems
                (gem_id, passage_id, source_id, part_number, title, category,
                 verbatim_rule, polished_rule, explanation, start_sec, end_sec, youtube_timestamp_url)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    gem_id,
                    g_pid,
                    source_id,
                    g_part,
                    g.get("title", ""),
                    g.get("category", ""),
                    v_rule,
                    p_rule,
                    g.get("explanation", ""),
                    None,
                    None,
                    None,
                ),
            )

    # --- B. Insert Series & Spoken Lectures ---
    inserted_series = set()
    for sm in series_manifests:
        s_id = sm["series_id"]
        src_id = sm.get("source_id") or f"series:{s_id}"
        inserted_series.add(s_id)
        cur.execute(
            """
            INSERT OR REPLACE INTO sources
            (source_id, source_type, title, author_or_sheikh, science, archetype, metadata_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                src_id,
                "lecture_series",
                sm.get("title", s_id),
                sm.get("sheikh", ""),
                sm.get("science", "akida"),
                "spoken_lecture",
                json.dumps(sm, ensure_ascii=False),
            ),
        )
        cur.execute(
            """
            INSERT OR REPLACE INTO series
            (series_id, source_id, title, sheikh, science, state, total_lessons, metadata_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                s_id,
                src_id,
                sm.get("title", s_id),
                sm.get("sheikh", ""),
                sm.get("science", "akida"),
                sm.get("state", "completed"),
                int(sm.get("total_lessons", len(sm.get("lessons", [])))),
                json.dumps(sm, ensure_ascii=False),
            ),
        )

    # Group lectures by series_id to ensure every lecture belongs to a registered series & source
    lectures_by_series = {}
    for lid, lec in lectures_map.items():
        s_id = lec.get("series_id") or lec.get("speaker_slug") or f"series_{lid}"
        lectures_by_series.setdefault(s_id, []).append((lid, lec))

    for s_id, lec_items in lectures_by_series.items():
        src_id = f"series:{s_id}"
        if s_id not in inserted_series:
            first_lec = lec_items[0][1]
            s_title = first_lec.get("series_title") or first_lec.get("base_work_title") or first_lec.get("title", s_id)
            sheikh = first_lec.get("speaker", "")
            science = first_lec.get("science", "akida")
            s_meta_json = json.dumps({"series_id": s_id, "lectures": [x[0] for x in lec_items]}, ensure_ascii=False)
            cur.execute(
                """
                INSERT OR REPLACE INTO sources
                (source_id, source_type, title, author_or_sheikh, science, archetype, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (src_id, "lecture_series", s_title, sheikh, science, "spoken_lecture", s_meta_json),
            )
            cur.execute(
                """
                INSERT OR REPLACE INTO series
                (series_id, source_id, title, sheikh, science, state, total_lessons, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (s_id, src_id, s_title, sheikh, science, "completed", len(lec_items), s_meta_json),
            )
            inserted_series.add(s_id)

        for idx_l, (lid, lec) in enumerate(lec_items, start=1):
            part_num = int(lec.get("part_number") or idx_l)
            passages = lec.get("deep_toc_passages", [])
            raw_char_cnt = sum(len(p.get("raw_text", "")) for p in passages)
            dur_s = float(lec.get("duration_sec_total") or ( max((p.get("end_sec", 0.0) for p in passages), default=0.0) ))
            yt_id = lec.get("video_id") or lec.get("youtube_id") or ""
            lec_science = lec.get("science", "akida")
            smeta = mr.get_science_meta(lec_science)

            cur.execute(
                """
                INSERT OR REPLACE INTO lessons_or_parts
                (part_id, source_id, series_id, part_number, title, yt_id, dur_s, page_start, page_end, raw_char_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (lid, src_id, s_id, part_num, lec.get("title", lid), yt_id, dur_s, None, None, raw_char_cnt),
            )

            # Resolve explained_matn_book_id against loaded books
            raw_bwid = lec.get("base_work_id") or ""
            resolved_matn_book_id = book_alias_to_source_id.get(str(raw_bwid), "")
            if not resolved_matn_book_id and raw_bwid:
                # If a book in the same science is loaded, link to it; otherwise use raw_bwid
                same_sc_books = [b for b in books_list if b.get("science") == lec_science]
                if len(same_sc_books) == 1:
                    resolved_matn_book_id = str(same_sc_books[0].get("source_id") or f"book:{same_sc_books[0]['book_id']}")
                else:
                    resolved_matn_book_id = str(raw_bwid)

            for p_idx, p in enumerate(passages, start=1):
                pid = str(p.get("passage_id") or f"{lid}:P{p_idx}")
                raw_text = p.get("raw_text", "")
                clean_matn = p.get("clean_matn") or raw_text
                isnad_prefix = p.get("isnad_prefix") or ""
                sub_h = p.get("sub_heading", "")
                summary = p.get("summary", "")
                topics = p.get("topics") or []
                queries = p.get("search_queries") or []
                s_sec = float(p.get("start_sec", 0.0))
                e_sec = float(p.get("end_sec", 0.0))
                yt_url = p.get("youtube_timestamp_url") or p.get("youtube_clip_url") or (
                    f"https://youtu.be/{yt_id}?t={int(s_sec)}" if yt_id else ""
                )

                emb_matn = p.get("embed_matn_text")
                if not emb_matn:
                    cleaned_str = mr.clean_for_embed(clean_matn, science=lec_science, orig_heading=lec.get("title", ""))
                    emb_matn = f"title: {lec.get('title', '')} ({lec.get('speaker', '')}) › {sub_h} | text: {cleaned_str}"

                emb_concept = p.get("embed_concept_text")
                if not emb_concept:
                    emb_concept = (
                        f"title: {sub_h} — {smeta['science_ar']} ({lec.get('title', '')}) | text: الملخص: {summary} | الموضوعات: {'، '.join(topics)}"
                    )

                cur.execute(
                    """
                    INSERT OR REPLACE INTO passages
                    (passage_id, source_id, series_id, part_id, part_number, passage_index, sub_heading,
                     raw_text, clean_matn, isnad_prefix, summary, topics_json, search_queries_json,
                     start_sec, end_sec, youtube_timestamp_url, page_num, embed_matn_text, embed_concept_text)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        pid,
                        src_id,
                        s_id,
                        lid,
                        part_num,
                        p_idx,
                        sub_h,
                        raw_text,
                        clean_matn,
                        isnad_prefix,
                        summary,
                        json.dumps(topics, ensure_ascii=False),
                        json.dumps(queries, ensure_ascii=False),
                        s_sec,
                        e_sec,
                        yt_url,
                        None,
                        emb_matn,
                        emb_concept,
                    ),
                )

                cur.execute(
                    """
                    INSERT INTO passages_fts
                    (passage_id, sub_heading, raw_text, clean_matn, summary, topics_text, search_queries_text)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        pid,
                        sub_h,
                        raw_text,
                        clean_matn,
                        summary,
                        " ، ".join(topics),
                        " ".join(queries),
                    ),
                )

                for per in p.get("persons", []):
                    reg = register_person(per, raw_text, isnad_prefix, clean_matn)
                    if reg:
                        per_id, ment_name, disp_name, s_layer, r_str = reg
                        cur.execute(
                            """
                            INSERT INTO passage_persons
                            (passage_id, person_id, mentioned_name, canonical_name, source_layer, role)
                            VALUES (?, ?, ?, ?, ?, ?)
                            """,
                            (pid, per_id, ment_name, disp_name, s_layer, r_str),
                        )

                for pl in p.get("places", []):
                    reg_pl = register_place(pl)
                    if reg_pl:
                        pl_id, ment_pl, can_pl = reg_pl
                        cur.execute(
                            """
                            INSERT INTO passage_places
                            (passage_id, place_id, mentioned_name, canonical_name)
                            VALUES (?, ?, ?, ?)
                            """,
                            (pid, pl_id, ment_pl, can_pl),
                        )

                for ch in p.get("chronology", []):
                    if not isinstance(ch, dict):
                        continue
                    hy = ch.get("hijri_year")
                    etag = (ch.get("event_tag") or ch.get("event_title") or ch.get("event") or "").strip()
                    raw_layer = (ch.get("event_layer") or "").strip()
                    ev_layer = "transmission" if raw_layer == "transmission" else "historical"
                    y_raw = resolve_verbatim_year_raw(ch, raw_text, hy if isinstance(hy, int) else None)
                    is_approx = 1 if (
                        ch.get("is_approximate")
                        or any(w in (y_raw + " " + etag) for w in ("نيف", "بضع", "نحو", "قرابة", "القرن"))
                    ) else 0
                    cur.execute(
                        """
                        INSERT INTO events_chronology
                        (passage_id, source_id, year_hijri, year_raw, is_approximate, event_title, event_layer)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (pid, src_id, hy if isinstance(hy, int) else None, y_raw, is_approx, etag, ev_layer),
                    )

                ev_list_lec = list(p.get("evidences", []))
                seen_ev_norms_l = {
                    bcg.norm_ar(e.get("text") or e.get("verbatim_text") or "")
                    for e in ev_list_lec
                    if isinstance(e, dict)
                }
                for auto_hev in yti.extract_hadith_evidences_from_text(clean_matn):
                    nh = bcg.norm_ar(auto_hev["text"])
                    if nh and not any(nh in ex or ex in nh for ex in seen_ev_norms_l if ex):
                        seen_ev_norms_l.add(nh)
                        ev_list_lec.append(auto_hev)

                for ev in ev_list_lec:
                    if not isinstance(ev, dict):
                        continue
                    ev_parsed = parse_evidence_fields(ev, [], raw_text=raw_text)
                    cur.execute(
                        """
                        INSERT INTO evidences
                        (passage_id, source_id, evidence_type, surah_number, ayah_start, ayah_end,
                         surah_ayah_key, verbatim_text, hadith_source, footnote_ref)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            pid,
                            src_id,
                            ev_parsed["evidence_type"],
                            ev_parsed["surah_number"],
                            ev_parsed["ayah_start"],
                            ev_parsed["ayah_end"],
                            ev_parsed["surah_ayah_key"],
                            ev_parsed["verbatim_text"],
                            ev_parsed["hadith_source"],
                            ev_parsed["footnote_ref"],
                        ),
                    )

                mt = p.get("matn_triangulation")
                if mt and isinstance(mt, dict) and mt.get("clause_id"):
                    mt_bwid = mt.get("base_work_id") or raw_bwid
                    target_book_id = book_alias_to_source_id.get(str(mt_bwid), resolved_matn_book_id or str(mt_bwid))
                    mt_s_sec = float(mt.get("start_sec", s_sec)) if mt.get("start_sec") is not None else s_sec
                    mt_e_sec = float(mt.get("end_sec", e_sec)) if mt.get("end_sec") is not None else e_sec
                    mt_verb = mt.get("explained_matn_verbatim", "")
                    cur.execute(
                        """
                        INSERT INTO matn_triangulation
                        (passage_id, source_id, explained_matn_book_id, explained_matn_clause_id, explained_matn_verbatim, start_sec, end_sec)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            pid,
                            src_id,
                            target_book_id,
                            mt["clause_id"],
                            mt_verb,
                            mt_s_sec,
                            mt_e_sec,
                        ),
                    )
                    # If target_book_id is loaded in `passages` and doesn't yet have a book-side row for `mt["clause_id"]`, link the best matching book passage
                    if (
                        target_book_id in book_passages_by_source
                        and (target_book_id, str(mt["clause_id"])) not in book_clauses_inserted
                    ):
                        bp_list = book_passages_by_source[target_book_id]
                        matched_bp_id = None
                        for bp_id, bp_raw in bp_list:
                            if mt_verb and (
                                mt_verb in bp_raw
                                or mr.verify_and_locate_span_in_part(mt_verb, bp_raw, allow_elision=False)[0] != "failed"
                            ):
                                matched_bp_id = bp_id
                                break
                        if not matched_bp_id:
                            q_norm, _ = mr.normalize_words_only(
                                f"{mt_verb} {mt.get('clause_full_text', '')} {sub_h}"
                            )
                            q_tokens = {w for w in q_norm.split() if len(w) >= 4}
                            best_score = -1
                            for bp_id, bp_raw in bp_list:
                                bp_norm, _ = mr.normalize_words_only(bp_raw)
                                bp_tokens = {w for w in bp_norm.split() if len(w) >= 4}
                                sc = len(q_tokens & bp_tokens)
                                if sc > best_score:
                                    best_score = sc
                                    matched_bp_id = bp_id
                            if not matched_bp_id:
                                matched_bp_id = bp_list[0][0]
                        book_clauses_inserted.add((target_book_id, str(mt["clause_id"])))
                        cur.execute(
                            """
                            INSERT INTO matn_triangulation
                            (passage_id, source_id, explained_matn_book_id, explained_matn_clause_id, explained_matn_verbatim, start_sec, end_sec)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                matched_bp_id,
                                target_book_id,
                                target_book_id,
                                mt["clause_id"],
                                mt_verb,
                                None,
                                None,
                            ),
                        )

            default_lec_pid = passages[0]["passage_id"] if passages else f"{lid}:P1"
            for st_idx, st in enumerate(lec.get("stories", []), start=1):
                st_pid = st.get("passage_id") or st.get("pid")
                if not st_pid:
                    anc = st.get("anchor_start", "")
                    st_pid = default_lec_pid
                    for p in passages:
                        if anc and (anc in p.get("raw_text", "") or mr.find_anchor_offset(p.get("raw_text", ""), anc, 0)[0] != -1):
                            st_pid = p["passage_id"]
                            break
                st_type_lec = classify_story_type(
                    st.get("story_type"),
                    st.get("title", ""),
                    st.get("anchor_start", ""),
                    st.get("summary", ""),
                    lec_science,
                )
                cur.execute(
                    """
                    INSERT INTO stories_cases
                    (passage_id, source_id, part_number, story_type, title, anchor_start, summary, lesson)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        st_pid,
                        src_id,
                        part_num,
                        st_type_lec,
                        st.get("title", ""),
                        st.get("anchor_start", ""),
                        st.get("summary", ""),
                        st.get("lesson", ""),
                    ),
                )

            for g_idx, g in enumerate(lec.get("science_gems", []), start=1):
                gem_id = str(g.get("gem_id") or f"{lid}:G{g_idx}")
                g_pid = g.get("passage_id") or g.get("pid")
                if not g_pid:
                    v_rule = g.get("verbatim_rule", "")
                    g_pid = default_lec_pid
                    for p in passages:
                        if v_rule and v_rule in p.get("raw_text", ""):
                            g_pid = p["passage_id"]
                            break
                g_yt = g.get("youtube_timestamp_url") or g.get("youtube_clip_url") or (
                    f"https://youtu.be/{yt_id}?t={int(g.get('start_sec', 0))}" if yt_id else ""
                )
                cur.execute(
                    """
                    INSERT OR REPLACE INTO science_gems
                    (gem_id, passage_id, source_id, part_number, title, category,
                     verbatim_rule, polished_rule, explanation, start_sec, end_sec, youtube_timestamp_url)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        gem_id,
                        g_pid,
                        src_id,
                        part_num,
                        g.get("title", ""),
                        g.get("category", ""),
                        g.get("verbatim_rule", ""),
                        g.get("polished_rule", ""),
                        g.get("explanation", ""),
                        float(g.get("start_sec", 0.0)),
                        float(g.get("end_sec", 0.0)),
                        g_yt,
                    ),
                )

    # --- C. Insert Technical Courses (if any) ---
    for cid, crs in (courses_map or {}).items():
        src_id = f"course:{cid}"
        passages = crs.get("deep_toc_passages", [])
        raw_char_cnt = sum(len(p.get("raw_text", "")) for p in passages)
        cur.execute(
            """
            INSERT OR REPLACE INTO sources
            (source_id, source_type, title, author_or_sheikh, science, archetype, metadata_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                src_id,
                "technical_course",
                crs.get("title", cid),
                crs.get("instructor", ""),
                crs.get("science", "cs"),
                crs.get("archetype", "technical_course"),
                json.dumps({"course_id": cid, "track": crs.get("track")}, ensure_ascii=False),
            ),
        )
        cur.execute(
            """
            INSERT OR REPLACE INTO lessons_or_parts
            (part_id, source_id, series_id, part_number, title, yt_id, dur_s, page_start, page_end, raw_char_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (cid, src_id, None, 1, crs.get("title", cid), None, None, None, None, raw_char_cnt),
        )
        for p_idx, p in enumerate(passages, start=1):
            pid = str(p.get("passage_id") or f"{cid}:P{p_idx}")
            raw_text = p.get("raw_text", "")
            sub_h = p.get("sub_heading", "")
            summary = p.get("summary", "")
            topics = p.get("topics") or []
            queries = p.get("search_queries") or []
            cur.execute(
                """
                INSERT OR REPLACE INTO passages
                (passage_id, source_id, series_id, part_id, part_number, passage_index, sub_heading,
                 raw_text, clean_matn, isnad_prefix, summary, topics_json, search_queries_json,
                 start_sec, end_sec, youtube_timestamp_url, page_num, embed_matn_text, embed_concept_text)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    pid,
                    src_id,
                    None,
                    cid,
                    1,
                    p_idx,
                    sub_h,
                    raw_text,
                    raw_text,
                    "",
                    summary,
                    json.dumps(topics, ensure_ascii=False),
                    json.dumps(queries, ensure_ascii=False),
                    None,
                    None,
                    None,
                    None,
                    f"title: {crs.get('title', '')} › {sub_h} | text: {raw_text}",
                    f"title: {sub_h} | text: الملخص: {summary}",
                ),
            )
            cur.execute(
                """
                INSERT INTO passages_fts
                (passage_id, sub_heading, raw_text, clean_matn, summary, topics_text, search_queries_text)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (pid, sub_h, raw_text, raw_text, summary, " ، ".join(topics), " ".join(queries)),
            )

    # --- D. Flush Deduplicated Persons & Places Registries ---
    for per_id, pdata in persons_registry.items():
        cur.execute(
            """
            INSERT OR REPLACE INTO persons
            (person_id, canonical_name, role_or_sect, death_year_hijri, aliases_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                per_id,
                pdata["canonical_name"],
                pdata["role_or_sect"],
                pdata["death_year_hijri"],
                json.dumps(sorted(pdata["aliases"]), ensure_ascii=False),
            ),
        )

    for pl_id, pldata in places_registry.items():
        cur.execute(
            """
            INSERT OR REPLACE INTO places
            (place_id, canonical_name, region_or_type, aliases_json)
            VALUES (?, ?, ?, ?)
            """,
            (
                pl_id,
                pldata["canonical_name"],
                pldata["region_or_type"],
                json.dumps(sorted(pldata["aliases"]), ensure_ascii=False),
            ),
        )

    conn.commit()

    # Collect table row counts & lossless verification stats
    tables = [
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
    counts = {}
    for t in tables:
        cur.execute(f"SELECT COUNT(*) FROM {t}")
        counts[t] = cur.fetchone()[0]

    cur.execute("SELECT COALESCE(SUM(raw_char_count), 0) FROM lessons_or_parts")
    expected_chars = cur.fetchone()[0]
    cur.execute("SELECT COALESCE(SUM(LENGTH(raw_text)), 0) FROM passages")
    actual_chars = cur.fetchone()[0]

    conn.close()

    return {
        "db_path": str(db_file),
        "table_counts": counts,
        "expected_raw_chars": expected_chars,
        "actual_passage_chars": actual_chars,
        "chars_lost": expected_chars - actual_chars,
    }


def main():
    parser = argparse.ArgumentParser(description="Build canonical SQLite + FTS5 entity database (objects.sqlite)")
    parser.add_argument("--work-dir", "--inputs", "--input-dir", dest="work_dir", default=None, help="Directory containing merged USDB JSON outputs")
    parser.add_argument("--db-path", "--db", dest="db_path", default=None, help="Output SQLite database path (default: <work-dir>/objects.sqlite)")
    args = parser.parse_args()

    wdir = Path(args.work_dir).resolve() if args.work_dir else Path.cwd()
    db_p = Path(args.db_path).resolve() if args.db_path else (wdir / "objects.sqlite")

    stats = build_objects_sqlite(db_path=db_p, work_dir=wdir)
    print(f"[build_objects_sqlite] Built {stats['db_path']} (chars_lost={stats['chars_lost']})")
    print(json.dumps(stats["table_counts"], ensure_ascii=False, indent=2))
    sys.exit(0 if stats["chars_lost"] == 0 else 1)


if __name__ == "__main__":
    main()
