#!/usr/bin/env python3
"""
Diagnostic health audit script for the 81-book Turath Deep Indexing corpus
in /Users/macm1pro/REPOS/books.

Run with:
    python3 /Users/macm1pro/REPOS/SKILLS/turath-deep-indexing/scripts/audit_corpus_health.py
"""

import glob
import json
from pathlib import Path

BOOKS_DIR = Path("/Users/macm1pro/REPOS/books")


def main():
    print("=" * 95)
    print("TURATH DEEP INDEXING CORPUS HEALTH AUDIT (/Users/macm1pro/REPOS/books)")
    print("=" * 95)

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
    print("-" * 95)

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

    print("-" * 95)
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

    # Gate v4.1 Golden Benchmark Verification (2327, 2412, 6243)
    import sys
    if str(BOOKS_DIR) not in sys.path:
        sys.path.insert(0, str(BOOKS_DIR))
    try:
        import merge_round as mr
        print("\n" + "=" * 95)
        print("GATE v4.1 (v4.1_strict_grounded) GOLDEN BENCHMARK BOOKS CHECK")
        print("=" * 95)
        benchmarks = [
            (5, "tarajim", 2327, "الفقهاء والعباد للفسوي"),
            (6, "tazkia", 2412, "رسالة المسترشدين للمحاسبي"),
            (10, "tarajim", 6243, "أخبار النحويين البصريين للسيرافي"),
        ]
        for r_num, sc, bid, bname in benchmarks:
            raw_r = json.loads((BOOKS_DIR / f"raw_round{r_num}_books.json").read_text(encoding="utf-8"))
            deep_b = json.loads((BOOKS_DIR / f"r{r_num}_deep_{sc}.json").read_text(encoding="utf-8"))
            _, rep = mr.audit_and_merge_round(r_num, raw_override={sc: raw_r[sc]}, deep_overrides={sc: deep_b})
            status = "PASS (0 P0)" if rep["passed"] else f"FAIL ({rep['p0_error_count']} P0)"
            print(f"  - Round {r_num:2d} | {sc:8s} | Book {bid} ({bname}): {status}")
    except Exception as exc:
        print(f"\n[!] Could not run Gate v4.1 benchmark check: {exc}")


if __name__ == "__main__":
    main()
