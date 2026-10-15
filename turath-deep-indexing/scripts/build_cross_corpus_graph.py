#!/usr/bin/env python3
"""
Track 4: Cross-Corpus Knowledge Graph Builder (USDB v5.5).
Builds the 4 Deterministic Bridges across:
  1. Classical Heritage Books (81 books across 9 sciences in /Users/macm1pro/REPOS/books)
  2. Spoken Video Lectures + CTC Word Alignments (usdb_v5/lectures_deep_merged.json)
  3. Multi-Matn Clauses (Umm al-Barahin UB:1..UB:6 & Matn al-Akhdari AKH:1..AKH:3 in raw_lectures.json)
  4. Technical & Educational Courses (usdb_v5/courses_deep_merged.json)
  5. Complete Tafsir Corpus (/Users/macm1pro/REPOS/firdaws/docs/tafsir/data/<id>/<surah>.json.gz)
Outputs:
  - /Users/macm1pro/REPOS/books/usdb_v5/cross_corpus_graph.json
  - /Users/macm1pro/REPOS/books/web_data/usdb_v5_bundle.js
"""
import gzip
import json
import os
import re
from pathlib import Path

BOOKS_DIR = Path(os.environ.get("TURATH_BOOKS_REPO", "/Users/macm1pro/REPOS/books"))
USDB_DIR = BOOKS_DIR / "usdb_v5"
FIRDAWS_TAFSIR_DIR = Path("/Users/macm1pro/REPOS/firdaws/docs/tafsir/data")

SURAH_NAMES = [
    "الفاتحة", "البقرة", "آل عمران", "النساء", "المائدة", "الأنعام", "الأعراف", "الأنفال", "التوبة", "يونس",
    "هود", "يوسف", "الرعد", "إبراهيم", "الحجر", "النحل", "الإسراء", "الكهف", "مريم", "طه",
    "الأنبياء", "الحج", "المؤمنون", "النور", "الفرقان", "الشعراء", "النمل", "القصص", "العنكبوت", "الروم",
    "لقمان", "السجدة", "الأحزاب", "سبأ", "فاطر", "يس", "الصافات", "ص", "الزمر", "غافر",
    "فصلت", "الشورى", "الزخرف", "الدخان", "الجاثية", "الأحقاف", "محمد", "الفتح", "الحجرات", "ق",
    "الذاريات", "الطور", "النجم", "القمر", "الرحمن", "الواقعة", "الحديد", "المجادلة", "الحشر", "الممتحنة",
    "الصف", "الجمعة", "المنافقون", "التغابن", "الطلاق", "التحريم", "الملك", "القلم", "الحاقة", "المعارج",
    "نوح", "الجن", "المزمل", "المدثر", "القيامة", "الإنسان", "المرسلات", "النبأ", "النازعات", "عبس",
    "التكوير", "الانفطار", "المطففين", "الانشقاق", "البروج", "الطارق", "الأعلى", "الغاشية", "الفجر", "البلد",
    "الشمس", "الليل", "الضحى", "الشرح", "التين", "العلق", "القدر", "البينة", "الزلزلة", "العاديات",
    "القارعة", "التكاثر", "العصر", "الهمزة", "الفيل", "قريش", "الماعون", "الكوثر", "الكافرون", "النصر",
    "المسد", "الإخلاص", "الفلق", "الناس"
]


def norm_ar(s: str) -> str:
    s = re.sub(r"[\u064b-\u065f\u0670\u0640]", "", s or "")
    s = re.sub(r"[أإآٱ]", "ا", s)
    s = s.replace("ة", "ه").replace("ى", "ي").replace("ؤ", "و").replace("ئ", "ي")
    return re.sub(r"\s+", " ", s).strip()


SURAH_MAP = {norm_ar(name): idx + 1 for idx, name in enumerate(SURAH_NAMES)}
SURAH_MAP[norm_ar("الانشراح")] = 94
SURAH_MAP[norm_ar("براءة")] = 9
SURAH_MAP[norm_ar("غافر")] = 40
SURAH_MAP[norm_ar("المؤمن")] = 40
SURAH_MAP[norm_ar("بني إسرائيل")] = 17

AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")

PERSON_CANONICAL_ALIASES = {
    "السنوسي": ("الإمام محمد بن يوسف السنوسي", "عالم"),
    "محمد بن يوسف السنوسي": ("الإمام محمد بن يوسف السنوسي", "عالم"),
    "ابو عبد الله السنوسي": ("الإمام محمد بن يوسف السنوسي", "عالم"),
    "الاشعري": ("الإمام أبو الحسن الأشعري", "عالم"),
    "ابو الحسن الاشعري": ("الإمام أبو الحسن الأشعري", "عالم"),
    "الباقلاني": ("القاضي أبو بكر الباقلاني", "عالم"),
    "ابو بكر الباقلاني": ("القاضي أبو بكر الباقلاني", "عالم"),
    "الجويني": ("إمام الحرمين أبو المعالي الجويني", "عالم"),
    "امام الحرمين": ("إمام الحرمين أبو المعالي الجويني", "عالم"),
    "امام الحرمين الجويني": ("إمام الحرمين أبو المعالي الجويني", "عالم"),
    "ابو المعالي الجويني": ("إمام الحرمين أبو المعالي الجويني", "عالم"),
    "الغزالي": ("الإمام أبو حامد الغزالي", "عالم"),
    "ابو حامد الغزالي": ("الإمام أبو حامد الغزالي", "عالم"),
    "الرازي": ("الإمام فخر الدين الرازي", "عالم"),
    "فخر الدين الرازي": ("الإمام فخر الدين الرازي", "عالم"),
    "مالك": ("الإمام مالك بن أنس", "عالم"),
    "مالك بن انس": ("الإمام مالك بن أنس", "عالم"),
    "الشافعي": ("الإمام محمد بن إدريس الشافعي", "عالم"),
    "محمد بن ادريس الشافعي": ("الإمام محمد بن إدريس الشافعي", "عالم"),
    "ابو حنيفه": ("الإمام أبو حنيفة النعمان", "عالم"),
    "ابو حنيفه النعمان": ("الإمام أبو حنيفة النعمان", "عالم"),
    "احمد بن حنبل": ("الإمام أحمد بن حنبل", "عالم"),
    "احمد": ("الإمام أحمد بن حنبل", "عالم"),
    "البخاري": ("الإمام محمد بن إسماعيل البخاري", "عالم"),
    "محمد بن اسماعيل البخاري": ("الإمام محمد بن إسماعيل البخاري", "عالم"),
    "مسلم": ("الإمام مسلم بن الحجاج", "عالم"),
    "مسلم بن الحجاج": ("الإمام مسلم بن الحجاج", "عالم"),
    "الاخضري": ("العلامة عبد الرحمن الأخضري", "عالم"),
    "عبد الرحمن الاخضري": ("العلامة عبد الرحمن الأخضري", "عالم"),
    "الشاطبي": ("الإمام أبو إسحاق الشاطبي", "عالم"),
    "ابو اسحاق الشاطبي": ("الإمام أبو إسحاق الشاطبي", "عالم"),
    "ابراهيم بن موسي الشاطبي": ("الإمام أبو إسحاق الشاطبي", "عالم"),
    "ابن تيميه": ("أحمد بن عبد الحليم بن تيمية", "عالم"),
    "احمد بن عبد الحليم بن تيميه": ("أحمد بن عبد الحليم بن تيمية", "عالم"),
    "ابن القيم": ("ابن قيم الجوزية", "عالم"),
    "ابن قيم الجوزيه": ("ابن قيم الجوزية", "عالم"),
    "ابن كثير": ("الحافظ إسماعيل بن كثير", "عالم"),
    "اسماعيل بن كثير": ("الحافظ إسماعيل بن كثير", "عالم"),
    "القرطبي": ("الإمام أبو عبد الله القرطبي", "عالم"),
    "ابو عبد الله القرطبي": ("الإمام أبو عبد الله القرطبي", "عالم"),
    "الطبري": ("الإمام ابن جرير الطبري", "عالم"),
    "ابن جرير الطبري": ("الإمام ابن جرير الطبري", "عالم"),
    "ابن رشد": ("القاضي ابن رشد", "عالم"),
    "ابن خلدون": ("العلامة عبد الرحمن بن خلدون", "عالم"),
    "عمر بن الخطاب": ("عمر بن الخطاب رضي الله عنه", "صحابي"),
    "عمر": ("عمر بن الخطاب رضي الله عنه", "صحابي"),
    "ابو بكر الصديق": ("أبو بكر الصديق رضي الله عنه", "صحابي"),
    "ابو بكر": ("أبو بكر الصديق رضي الله عنه", "صحابي"),
    "عثمان بن عفان": ("عثمان بن عفان رضي الله عنه", "صحابي"),
    "عثمان": ("عثمان بن عفان رضي الله عنه", "صحابي"),
    "علي بن ابي طالب": ("علي بن أبي طالب رضي الله عنه", "صحابي"),
    "علي": ("علي بن أبي طالب رضي الله عنه", "صحابي"),
    "ابن عباس": ("عبد الله بن عباس رضي الله عنهما", "صحابي"),
    "عبد الله بن عباس": ("عبد الله بن عباس رضي الله عنهما", "صحابي"),
    "ابن عمر": ("عبد الله بن عمر رضي الله عنهما", "صحابي"),
    "عبد الله بن عمر": ("عبد الله بن عمر رضي الله عنهما", "صحابي"),
    "عايشه": ("عائشة أم المؤمنين رضي الله عنها", "صحابي"),
    "عايشه بنت ابي بكر": ("عائشة أم المؤمنين رضي الله عنها", "صحابي"),
    "عايشه ام المومنين": ("عائشة أم المؤمنين رضي الله عنها", "صحابي"),
    "ابو هريره": ("أبو هريرة رضي الله عنه", "صحابي"),
    "انس بن مالك": ("أنس بن مالك رضي الله عنه", "صحابي"),
    "موسي": ("نبي الله موسى عليه السلام", "نبي"),
    "ابراهيم": ("نبي الله إبراهيم عليه السلام", "نبي"),
    "عيسي": ("نبي الله عيسى عليه السلام", "نبي"),
    "نوح": ("نبي الله نوح عليه السلام", "نبي"),
    "فرعون": ("فرعون", "حاكم"),
}


def canonicalize_person(cname: str, cat: str = "") -> tuple[str, str, str]:
    raw = re.sub(r"\([^\)]*\)", "", cname or "").strip()
    n = norm_ar(raw)
    # Strip honorific prefixes and suffixes
    prefixes = [
        "الامام ", "الشيخ ", "العلامه ", "الحافظ ", "القاضي ", "الدكتور ",
        "سيدنا ", "امير المومنين ", "الصحابي الجليل ", "الصحابي ", "نبي الله ",
        "النبي ", "الرسول ", "حجه الاسلام ", "شيخ الاسلام "
    ]
    changed = True
    while changed:
        changed = False
        for pf in prefixes:
            if n.startswith(pf):
                n = n[len(pf):].strip()
                changed = True
    suffixes = [
        " رضي الله عنهما", " رضي الله عنها", " رضي الله عنهم", " رضي الله عنه",
        " رحمه الله", " عليه الصلاه والسلام", " عليه السلام", " صلي الله عليه وسلم"
    ]
    for sf in suffixes:
        if n.endswith(sf):
            n = n[:-len(sf)].strip()

    if n in PERSON_CANONICAL_ALIASES:
        disp, ccat = PERSON_CANONICAL_ALIASES[n]
        return norm_ar(disp), disp, (cat or ccat)
    for k, (disp, ccat) in PERSON_CANONICAL_ALIASES.items():
        if len(k) >= 6 and (k in n or n in k):
            return norm_ar(disp), disp, (cat or ccat)
    return n, raw, cat


def parse_ayah_key(source_str: str) -> tuple[str | None, int | None, int | None, str | None]:
    if not source_str:
        return None, None, None, None
    s = source_str.translate(AR_DIGITS)
    m = re.search(r"(?:سورة\s+)?([^\d:،\-\(\)\[\]]+?)\s*[:،\-/\(\[]\s*(?:الآية\s*|آية\s*)?(\d+)", s)
    if not m:
        return None, None, None, None
    raw_sname = m.group(1).replace("سورة", "").strip()
    ayah_num = int(m.group(2))
    ns = norm_ar(raw_sname)
    snum = SURAH_MAP.get(ns)
    if not snum:
        for k_norm, k_num in SURAH_MAP.items():
            if len(k_norm) >= 3 and (k_norm == ns or k_norm in ns):
                snum = k_num
                break
    if not snum or ayah_num <= 0:
        return None, None, None, None
    return f"{snum}:{ayah_num}", snum, ayah_num, SURAH_NAMES[snum - 1]


def fetch_firdaws_tafsir(surah_num: int, ayah_num: int) -> list[dict]:
    if not FIRDAWS_TAFSIR_DIR.exists():
        return []
    books_meta_p = FIRDAWS_TAFSIR_DIR / "books.json"
    if not books_meta_p.exists():
        return []
    bmeta = json.loads(books_meta_p.read_text(encoding="utf-8")).get("books", [])
    preferred_ids = [22, 525, 506, 250, 251, 490]  # ابن كثير، الشنقيطي، درويش، إلخ
    id_to_name = {b["id"]: b["name"] for b in bmeta}
    ordered_ids = [bid for bid in preferred_ids if bid in id_to_name] + [
        b["id"] for b in bmeta if b["id"] not in preferred_ids
    ]
    key = f"{surah_num}:{ayah_num}"
    results = []
    for bid in ordered_ids:
        gz_p = FIRDAWS_TAFSIR_DIR / str(bid) / f"{surah_num}.json.gz"
        if not gz_p.exists():
            continue
        try:
            data = json.loads(gzip.open(gz_p, "rt", encoding="utf-8").read())
            entry = data.get(key)
            if entry:
                txt = entry.get("text", "") if isinstance(entry, dict) else str(entry)
                clean_txt = re.sub(r"<[^>]+>", " ", txt)
                clean_txt = re.sub(r"\(p-[^\)]+\)", "", clean_txt)
                clean_txt = re.sub(r"\s+", " ", clean_txt).strip()
                if len(clean_txt) > 40:
                    results.append(
                        {
                            "tafsir_id": bid,
                            "tafsir_name": id_to_name.get(bid, f"تفسير #{bid}"),
                            "excerpt": clean_txt[:460] + ("..." if len(clean_txt) > 460 else ""),
                        }
                    )
            if len(results) >= 4:
                break
        except Exception:
            continue
    return results


def build_matn_system_clauses(
    base_work_id: str,
    base_work_title: str,
    base_work_author: str,
    science_target: str,
    clauses_raw: list[dict],
    lectures_map: dict,
    books_records: list,
    keywords_pool: list[str],
) -> dict:
    clauses_out = []
    for cl in clauses_raw:
        cid = cl["clause_id"]
        video_explanations = []
        for lid, lec in lectures_map.items():
            for p in lec.get("deep_toc_passages", []):
                mt = p.get("matn_triangulation")
                if mt and mt.get("clause_id") == cid:
                    video_explanations.append(
                        {
                            "lecture_id": lid,
                            "speaker": lec.get("speaker"),
                            "lecture_title": lec.get("title"),
                            "youtube_id": lec.get("youtube_id"),
                            "passage_id": p.get("passage_id"),
                            "sub_heading": p.get("sub_heading"),
                            "summary": p.get("summary"),
                            "explained_matn_verbatim": mt.get("explained_matn_verbatim"),
                            "start_sec": p.get("start_sec", 0),
                            "end_sec": p.get("end_sec", 0),
                            "time_range_fmt": p.get("time_range_fmt"),
                            "time_basis": p.get("time_basis"),
                            "youtube_clip_url": p.get("youtube_clip_url"),
                        }
                    )
        written_parallels = []
        cl_kws = [kw for kw in keywords_pool if kw in cl["text"] or kw in cl["title"]]
        if not cl_kws:
            cl_kws = keywords_pool[:3]
        for r, sc, bk in books_records:
            if sc != science_target:
                continue
            for p in bk.get("deep_toc_passages", []):
                hay = (p.get("sub_heading") or "") + " " + (p.get("summary") or "") + " " + (p.get("text") or "")[:500]
                if any(kw in hay for kw in cl_kws):
                    written_parallels.append(
                        {
                            "round": r,
                            "book_id": bk.get("book_id"),
                            "book_title": bk.get("title"),
                            "author": bk.get("author"),
                            "passage_id": p.get("passage_id"),
                            "sub_heading": p.get("sub_heading"),
                            "summary": (p.get("summary") or "")[:240] + "...",
                        }
                    )
                    if len(written_parallels) >= 4:
                        break
            if len(written_parallels) >= 4:
                break

        clauses_out.append(
            {
                "clause_id": cid,
                "title": cl["title"],
                "matn_text": cl["text"],
                "video_explanations": video_explanations,
                "written_book_parallels": written_parallels,
            }
        )
    return {
        "base_work_id": base_work_id,
        "base_work_title": base_work_title,
        "base_work_author": base_work_author,
        "science": science_target,
        "clauses": clauses_out,
    }


def build_graph():
    # 1. Load all 81 classical books
    books_records = []
    for r in range(1, 11):
        fp = BOOKS_DIR / ("all_9_books_deep.json" if r == 1 else f"round{r}_9_books_deep.json")
        if not fp.exists():
            continue
        rd = json.loads(fp.read_text(encoding="utf-8"))
        items = rd.items() if isinstance(rd, dict) else [(b.get("science", ""), b) for b in rd if isinstance(b, dict)]
        for sc, bk in items:
            if not isinstance(bk, dict) or not bk.get("deep_toc_passages"):
                continue
            books_records.append((r, sc, bk))

    # 2. Load spoken lectures
    lec_path = USDB_DIR / "lectures_deep_merged.json"
    lectures_map = json.loads(lec_path.read_text(encoding="utf-8")) if lec_path.exists() else {}

    # 3. Load technical courses
    crs_path = USDB_DIR / "courses_deep_merged.json"
    courses_map = json.loads(crs_path.read_text(encoding="utf-8")) if crs_path.exists() else {}

    # 4. Build Bridge 1: Cross-Corpus Ayah Graph (Books <-> Video Lectures <-> Firdaws Tafsirs)
    ayah_nodes = {}
    for r, sc, bk in books_records:
        b_id = bk.get("book_id")
        b_title = bk.get("title", "")
        b_author = bk.get("author", "")
        for p in bk.get("deep_toc_passages", []):
            for ev in p.get("evidences", []):
                if ev.get("type") == "آية" or "سورة" in (ev.get("source") or ""):
                    akey, snum, anum, sname = parse_ayah_key(ev.get("source", ""))
                    if not akey:
                        continue
                    node = ayah_nodes.setdefault(
                        akey,
                        {
                            "ayah_key": akey,
                            "surah_num": snum,
                            "ayah_num": anum,
                            "surah_name": sname,
                            "verse_text": ev.get("text", ""),
                            "book_citations": [],
                            "lecture_citations": [],
                            "firdaws_tafsirs": [],
                        },
                    )
                    if not node["verse_text"] and ev.get("text"):
                        node["verse_text"] = ev.get("text")
                    node["book_citations"].append(
                        {
                            "round": r,
                            "science": sc,
                            "book_id": b_id,
                            "book_title": b_title,
                            "author": b_author,
                            "passage_id": p.get("passage_id"),
                            "sub_heading": p.get("sub_heading"),
                            "indicative_aspect": ev.get("indicative_aspect", ""),
                        }
                    )

    for lid, lec in lectures_map.items():
        for p in lec.get("deep_toc_passages", []):
            for ev in p.get("evidences", []):
                if ev.get("type") == "آية" or "سورة" in (ev.get("source") or ""):
                    akey, snum, anum, sname = parse_ayah_key(ev.get("source", ""))
                    if not akey:
                        continue
                    node = ayah_nodes.setdefault(
                        akey,
                        {
                            "ayah_key": akey,
                            "surah_num": snum,
                            "ayah_num": anum,
                            "surah_name": sname,
                            "verse_text": ev.get("text", ""),
                            "book_citations": [],
                            "lecture_citations": [],
                            "firdaws_tafsirs": [],
                        },
                    )
                    if not node["verse_text"] and ev.get("text"):
                        node["verse_text"] = ev.get("text")
                    node["lecture_citations"].append(
                        {
                            "lecture_id": lid,
                            "lecture_title": lec.get("title"),
                            "speaker": lec.get("speaker"),
                            "youtube_id": lec.get("youtube_id"),
                            "science": lec.get("science"),
                            "passage_id": p.get("passage_id"),
                            "sub_heading": p.get("sub_heading"),
                            "start_sec": p.get("start_sec", 0),
                            "time_range_fmt": p.get("time_range_fmt"),
                            "youtube_clip_url": p.get("youtube_clip_url"),
                            "indicative_aspect": ev.get("indicative_aspect", ""),
                        }
                    )

    sorted_ayahs = sorted(
        ayah_nodes.values(),
        key=lambda x: (
            1 if (x["book_citations"] and x["lecture_citations"]) else 0,
            len(x["lecture_citations"]),
            len({c["science"] for c in x["book_citations"]}),
            len(x["book_citations"]),
        ),
        reverse=True,
    )
    top_ayahs = sorted_ayahs[:35]
    for node in top_ayahs:
        node["firdaws_tafsirs"] = fetch_firdaws_tafsir(node["surah_num"], node["ayah_num"])

    # 5. Build Bridge 2: Multi-Matn Triangulation Graph (Umm al-Barahin + Matn al-Akhdari)
    raw_lecs = json.loads((USDB_DIR / "raw_lectures.json").read_text(encoding="utf-8"))
    ub_system = build_matn_system_clauses(
        base_work_id="umm-al-barahin",
        base_work_title="متن أم البراهين (العقيدة السنوسية الصغرى)",
        base_work_author="الإمام أبو عبد الله محمد بن يوسف السنوسي (ت 895هـ)",
        science_target="akida",
        clauses_raw=raw_lecs["alamri_barahin_12"]["base_matn_clauses"],
        lectures_map=lectures_map,
        books_records=books_records,
        keywords_pool=["الحكم العقلي", "الواجب", "حدوث العالم", "القدم", "الدور", "التسلسل", "البقاء", "الحوادث", "قيامه بنفسه"],
    )
    akh_clauses_raw = raw_lecs.get("binsayib_akhdari_01", {}).get("base_matn_clauses", [])
    akh_system = build_matn_system_clauses(
        base_work_id="matn-al-akhdari",
        base_work_title="متن الأخضري في العبادات على مذهب الإمام مالك (الكتاب 3418)",
        base_work_author="العلامة عبد الرحمن بن محمد الصغير الأخضري (ت 983هـ)",
        science_target="maliki",
        clauses_raw=akh_clauses_raw,
        lectures_map=lectures_map,
        books_records=books_records,
        keywords_pool=["الطهارة", "طهارة الحدث", "طهارة الخبث", "الماء المطلق", "فرائض الوضوء", "النية", "غسل الوجه"],
    )
    matn_systems_bridge = [ub_system, akh_system] if akh_clauses_raw else [ub_system]

    # 6. Build Bridge 3: Unified Scholar & Person Graph across Books and Spoken Lectures
    person_index = {}
    for r, sc, bk in books_records:
        for p in bk.get("deep_toc_passages", []):
            for per in p.get("persons", []):
                if per.get("source_layer") == "isnad":
                    continue
                cname = (per.get("canonical_name") or "").strip()
                if not cname:
                    continue
                key, disp_name, ccat = canonicalize_person(cname, per.get("category", ""))
                if len(key) < 3:
                    continue
                entry = person_index.setdefault(
                    key,
                    {
                        "canonical_name": disp_name,
                        "category": ccat,
                        "book_mentions": [],
                        "lecture_mentions": [],
                    },
                )
                if len(entry["book_mentions"]) < 10:
                    entry["book_mentions"].append(
                        {
                            "book_title": bk.get("title"),
                            "science": sc,
                            "passage_id": p.get("passage_id"),
                            "sub_heading": p.get("sub_heading", ""),
                            "role": per.get("role", ""),
                        }
                    )

    for lid, lec in lectures_map.items():
        for p in lec.get("deep_toc_passages", []):
            for per in p.get("persons", []):
                cname = (per.get("canonical_name") or "").strip()
                if not cname:
                    continue
                key, disp_name, ccat = canonicalize_person(cname, per.get("category", ""))
                if len(key) < 3:
                    continue
                entry = person_index.setdefault(
                    key,
                    {
                        "canonical_name": disp_name,
                        "category": ccat,
                        "book_mentions": [],
                        "lecture_mentions": [],
                    },
                )
                entry["lecture_mentions"].append(
                    {
                        "lecture_id": lid,
                        "lecture_title": lec.get("title"),
                        "speaker": lec.get("speaker"),
                        "youtube_id": lec.get("youtube_id"),
                        "passage_id": p.get("passage_id"),
                        "sub_heading": p.get("sub_heading", ""),
                        "start_sec": p.get("start_sec", 0),
                        "time_range_fmt": p.get("time_range_fmt"),
                        "youtube_clip_url": p.get("youtube_clip_url"),
                        "role": per.get("role", ""),
                    }
                )

    cross_media_persons = sorted(
        [v for v in person_index.values() if v["book_mentions"] and v["lecture_mentions"]],
        key=lambda x: (len(x["lecture_mentions"]), len(x["book_mentions"])),
        reverse=True,
    )[:25]

    graph_out = {
        "engine_version": "USDB v5.5 — Universal Source-to-Database Flagship Engine",
        "stats": {
            "books_indexed": len(books_records),
            "book_passages": sum(len(b.get("deep_toc_passages", [])) for _, _, b in books_records),
            "lectures_indexed": len(lectures_map),
            "lecture_passages": sum(len(l.get("deep_toc_passages", [])) for l in lectures_map.values()),
            "lecture_gems": sum(len(l.get("science_gems", [])) for l in lectures_map.values()),
            "matn_systems_count": len(matn_systems_bridge),
            "matn_triangulated_passages": sum(l.get("matn_triangulation_count", 0) for l in lectures_map.values()),
            "courses_indexed": len(courses_map),
            "course_passages": sum(len(c.get("deep_toc_passages", [])) for c in courses_map.values()),
            "course_gems": sum(len(c.get("science_gems", [])) for c in courses_map.values()),
            "course_atomic_blocks_protected": sum(c.get("atomic_blocks_protected", 0) for c in courses_map.values()),
            "ayah_bridge_total_unique_verses": len(ayah_nodes),
            "cross_media_persons_count": len(cross_media_persons),
        },
        "matn_systems_bridge": matn_systems_bridge,
        "matn_triangulation_bridge": ub_system["clauses"],
        "ayah_bridge_top": top_ayahs,
        "cross_media_persons_bridge": cross_media_persons,
        "lectures": lectures_map,
        "courses": courses_map,
    }

    out_json = USDB_DIR / "cross_corpus_graph.json"
    out_json.write_text(json.dumps(graph_out, ensure_ascii=False, indent=2), encoding="utf-8")

    bundle_js = BOOKS_DIR / "web_data" / "usdb_v5_bundle.js"
    bundle_js.parent.mkdir(parents=True, exist_ok=True)
    bundle_js.write_text(
        "window.USDB_V5_DATA = " + json.dumps(graph_out, ensure_ascii=False) + ";\n",
        encoding="utf-8",
    )
    print(f"Built {out_json} and {bundle_js}:")
    print(json.dumps(graph_out["stats"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    build_graph()
