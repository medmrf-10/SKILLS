#!/usr/bin/env python3
"""Fast P0 checker for a single round (and optional subset of sciences) under Gate v4.2."""
import json
import os
import re
import sys
import merge_round as mr


def main():
    rounds = [int(sys.argv[1])] if len(sys.argv) > 1 else list(range(2, 11))
    only_sciences = sys.argv[2:] if len(sys.argv) > 2 else None

    for r in rounds:
        raw_p = f"/Users/macm1pro/REPOS/books/raw_round{r}_books.json"
        if not os.path.exists(raw_p):
            continue
        raw_r = json.loads(open(raw_p, encoding="utf-8").read())
        if only_sciences:
            raw_r = {sc: raw_r[sc] for sc in only_sciences if sc in raw_r}
        deep_ov = {}
        for sc in raw_r:
            dp = f"/Users/macm1pro/REPOS/books/r{r}_deep_{sc}.json"
            if os.path.exists(dp):
                deep_ov[sc] = json.loads(open(dp, encoding="utf-8").read())
        _, rep = mr.audit_and_merge_round(r, raw_override=raw_r, deep_overrides=deep_ov)
        print(f"=== ROUND {r} (passed={rep['passed']}, total_p0={rep['p0_error_count']}) ===")
        by_sc = {}
        for e in rep["p0_errors"]:
            m = re.match(r"^\[([^:\]]+)", str(e))
            sc = m.group(1) if m else "?"
            by_sc.setdefault(sc, []).append(str(e))
        for sc in raw_r:
            errs = by_sc.get(sc, [])
            types = sorted(set(re.findall(r"P0_[A-Z0-9_]+", " ".join(errs))))
            print(f"  [{sc}] id={raw_r[sc]['book_id']} parts={len(raw_r[sc]['parts'])} p0={len(errs)} types={types}")
            if only_sciences:
                for err_line in errs:
                    print("    -", err_line)


if __name__ == "__main__":
    main()
