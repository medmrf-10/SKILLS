#!/usr/bin/env python3
"""Fast P0 checker for a single round (and optional subset of sciences) under Gate v4.3."""
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import merge_round as mr


def main():
    args = sys.argv[1:]
    work_dir = mr.BASE
    pos_args = []
    i = 0
    while i < len(args):
        if args[i] == "--work-dir" and i + 1 < len(args):
            work_dir = Path(args[i + 1]).resolve()
            mr.BASE = work_dir
            i += 2
        else:
            pos_args.append(args[i])
            i += 1

    rounds = [int(pos_args[0])] if pos_args else list(range(2, 11))
    only_sciences = pos_args[1:] if len(pos_args) > 1 else None

    for r in rounds:
        raw_p = work_dir / f"raw_round{r}_books.json"
        if not raw_p.exists():
            continue
        raw_r = json.loads(raw_p.read_text(encoding="utf-8"))
        if only_sciences:
            raw_r = {sc: raw_r[sc] for sc in only_sciences if sc in raw_r}
        deep_ov = {}
        for sc in raw_r:
            dp = work_dir / f"r{r}_deep_{sc}.json"
            if dp.exists():
                deep_ov[sc] = json.loads(dp.read_text(encoding="utf-8"))
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
            if only_sciences or errs:
                for err_line in errs[:15]:
                    print("    -", err_line)


if __name__ == "__main__":
    main()

