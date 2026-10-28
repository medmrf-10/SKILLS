#!/usr/bin/env python3
"""
Diagnostic health audit script for the Turath Deep Indexing & USDB v5.0 corpus.
Reads repo paths from environment variables ($TURATH_BOOKS_REPO, $SKILLS_DIR)
with safe fallbacks to default macOS paths. Works seamlessly on macOS, VPS, or any environment.

Run with:
    python3 "$SKILLS_DIR/turath-deep-indexing/scripts/audit_corpus_health.py"
    # or simply:
    python3 scripts/audit_corpus_health.py
"""

import json
import os
import sys
from pathlib import Path

BOOKS_DIR = Path(os.environ.get("TURATH_BOOKS_REPO", Path(__file__).resolve().parent))
SKILLS_DIR = Path(os.environ.get("SKILLS_DIR", Path(__file__).resolve().parent.parent.parent))


def main():
    print("=" * 98)
    print(f"USDB v5.0 & TURATH DEEP INDEXING CORPUS HEALTH AUDIT ({BOOKS_DIR})")
    print("=" * 98)

    round_files = [("Round 1", BOOKS_DIR / "all_9_books_deep.json")]
    for r in range(2, 11):
        round_files.append((f"Round {r}", BOOKS_DIR / f"round{r}_9_books_deep.json"))

    total_books = 0
    total_passages = 0
    missing_subheading_books = []
    missing_entities_books = []
    suspicious_quotes = []

    print(
        f"{'Round':8s} | {'Books':5s} | {'Passages':8s} | {'SubHead':7s} | {'Topics':6s} | "
        f"{'Persons':7s} | {'Places':6s} | {'Chron':5s} | {'Evid':5s} | {'Queries':7s} | {'Gems(T)':8s} | {'Quotes(S)':9s}"
    )
    print("-" * 98)

    for label, fpath in round_files:
        if not fpath.exists():
            print(f"{label:8s} | MISSING FILE: {fpath}")
            continue
        data = json.loads(fpath.read_text(encoding="utf-8"))
        books = data["books"] if isinstance(data, dict) else data
        if isinstance(books, dict):
            books = list(books.values())

        b_cnt = len(books)
        total_books += b_cnt
        p_tot = p_sh = p_tp = p_per = p_plc = p_chr = p_ev = p_sq = 0
        g_tot = g_tit = q_tot = q_spk = 0

        for b in books:
            sc = b.get("science", "?")
            bid = b.get("book_id", "?")
            btitle = b.get("title", "")
            ps = b.get("deep_toc_passages", [])
            b_sh = sum(1 for p in ps if (p.get("sub_heading") or "").strip())
            b_per = sum(1 for p in ps if p.get("persons"))
            b_sq = sum(1 for p in ps if p.get("search_queries"))

            if b_sh < len(ps):
                missing_subheading_books.append((label, sc, bid, btitle, f"{b_sh}/{len(ps)}"))
            if b_per == 0 or b_sq == 0:
                missing_entities_books.append((label, sc, bid, btitle, f"persons={b_per}, queries={b_sq}"))

            for p in ps:
                p_tot += 1
                total_passages += 1
                if (p.get("sub_heading") or "").strip():
                    p_sh += 1
                if p.get("topics"):
                    p_tp += 1
                if p.get("persons"):
                    p_per += 1
                if p.get("places"):
                    p_plc += 1
                if p.get("chronology"):
                    p_chr += 1
                if p.get("evidences"):
                    p_ev += 1
                if p.get("search_queries"):
                    p_sq += 1

            for g in b.get("science_gems", []):
                g_tot += 1
                if (g.get("title") or "").strip():
                    g_tit += 1

            for idx, q in enumerate(b.get("quotes", [])):
                q_tot += 1
                if (q.get("speaker") or "").strip():
                    q_spk += 1
                qt = q.get("quote", "")
                if "وقال له آخر:" in qt or qt.startswith("كل شيء "):
                    suspicious_quotes.append((label, sc, bid, idx + 1, qt))

        print(
            f"{label:8s} | {b_cnt:5d} | {p_tot:8d} | {p_sh:7d} | {p_tp:6d} | "
            f"{p_per:7d} | {p_plc:6d} | {p_chr:5d} | {p_ev:5d} | {p_sq:7d} | "
            f"{g_tot:3d}({g_tit:3d}) | {q_tot:3d}({q_spk:3d})"
        )

    print("-" * 98)
    print(f"Total Merged Books: {total_books} | Total Passages: {total_passages}")

    if missing_subheading_books:
        print(f"\n[!] BOOKS WITH EMPTY sub_heading IN MERGED JSON ({len(missing_subheading_books)} books):")
        for item in missing_subheading_books:
            print("   -", item)

    if missing_entities_books:
        print(f"\n[!] BOOKS WITH MISSING persons OR search_queries ({len(missing_entities_books)} books):")
        for item in missing_entities_books[:15]:
            print("   -", item)
        if len(missing_entities_books) > 15:
            print(f"   ... and {len(missing_entities_books) - 15} more books.")

    if suspicious_quotes:
        print(f"\n[!] SUSPICIOUS QUOTES DETECTED ({len(suspicious_quotes)}):")
        for item in suspicious_quotes:
            print("   -", item)

    # Gate v4.2 Verification Across Rounds 2..10
    print("\n" + "=" * 98)
    print("TRACK 2: GATE v4.2 (v4.1_strict_grounded) ROUNDS 2..10 REPORT STATUS (72 BOOKS)")
    print("=" * 98)
    for r_num in range(2, 11):
        rep_path = BOOKS_DIR / f"gate_report_r{r_num}.json"
        if rep_path.exists():
            rep = json.loads(rep_path.read_text(encoding="utf-8"))
            status = "PASS (0 P0)" if rep.get("passed") else f"FAIL ({rep.get('p0_error_count')} P0)"
            print(f"  - Round {r_num:2d} | gate={rep.get('gate_version', '?'):20s} | status={status}")
        else:
            print(f"  - Round {r_num:2d} | MISSING gate_report_r{r_num}.json")

    # Track 1: Spoken Video Lectures + Matn Triangulation
    print("\n" + "=" * 98)
    print("TRACK 1: SPOKEN VIDEO LECTURES + CTC WORD ALIGNMENT + MATN TRIANGULATION (ADAPTER B & C)")
    print("=" * 98)
    lec_rep_path = BOOKS_DIR / "usdb_v5" / "gate_report_lectures.json"
    lec_merged_path = BOOKS_DIR / "usdb_v5" / "lectures_deep_merged.json"
    if lec_rep_path.exists() and lec_merged_path.exists():
        lrep = json.loads(lec_rep_path.read_text(encoding="utf-8"))
        ldata = json.loads(lec_merged_path.read_text(encoding="utf-8"))
        lmap = {item["lecture_id"]: item for item in ldata} if isinstance(ldata, list) else ldata
        for lid, st in lrep.items():
            lobj = lmap.get(lid, {})
            passages = lobj.get("deep_toc_passages", [])
            basis = passages[0].get("time_basis", "?") if passages else "?"
            print(
                f"  - [{lid:20s}] passed={st['passed']} p0={st['p0_error_count']} "
                f"passages={st['passages_count']:2d} gems={st['gems_count']} "
                f"matn_links={st['matn_triangulation_count']} basis={basis}"
            )
    else:
        print("  [!] Missing lecture gate report or merged file.")

    # Track 3: Technical Courses + User Cognitive DNA
    print("\n" + "=" * 98)
    print("TRACK 3: TECHNICAL & EDUCATIONAL COURSES + USER COGNITIVE DNA (ADAPTER D)")
    print("=" * 98)
    crs_rep_path = BOOKS_DIR / "usdb_v5" / "gate_report_courses.json"
    if crs_rep_path.exists():
        crep = json.loads(crs_rep_path.read_text(encoding="utf-8"))
        for cid, st in crep.items():
            print(
                f"  - [{cid:24s}] passed={st['passed']} p0={st['p0_error_count']} "
                f"passages={st['passages_count']:2d} gems={st['gems_count']} "
                f"atomic_blocks_protected={st['atomic_blocks_protected']}"
            )
    else:
        print("  [!] Missing course gate report.")

    # Track 4: Cross-Corpus Knowledge Graph
    print("\n" + "=" * 98)
    print("TRACK 4: CROSS-CORPUS KNOWLEDGE GRAPH (BOOKS + LECTURES + MATN + COURSES + TAFSIR 40)")
    print("=" * 98)
    cc_path = BOOKS_DIR / "usdb_v5" / "cross_corpus_graph.json"
    if cc_path.exists():
        cc = json.loads(cc_path.read_text(encoding="utf-8"))
        s = cc.get("stats", {})
        print(
            f"  - Classical Books: {s.get('books_indexed')} books ({s.get('book_passages')} passages)\n"
            f"  - Spoken Lectures: {s.get('lectures_indexed')} lectures ({s.get('lecture_passages')} passages, {s.get('lecture_gems')} dual-layer gems, {s.get('matn_triangulated_passages')} Matn triangulations)\n"
            f"  - Technical Courses: {s.get('courses_indexed')} courses ({s.get('course_passages')} passages, {s.get('course_gems')} root-cause gems, {s.get('course_atomic_blocks_protected')} atomic blocks)\n"
            f"  - Cross-Corpus Bridges: {s.get('ayah_bridge_total_unique_verses')} Quranic verses linked to Tafsir 40 | {s.get('cross_media_persons_count')} cross-media persons"
        )
    else:
        print("  [!] Missing cross_corpus_graph.json.")


if __name__ == "__main__":
    main()
