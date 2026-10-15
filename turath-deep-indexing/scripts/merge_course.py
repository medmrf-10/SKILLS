#!/usr/bin/env python3
"""
Gate v5.1 — Technical & Educational Course Engine (Adapter D: Technical Course Profile).
Enforces 100% lossless verbatim partitioning, Atomic Code/Table/Math/Callout/Details Block Protection,
and the User's Cognitive DNA (Root-Cause First, Wrong-vs-Canonical Contrast, Zero Childish Analogies,
and UAX #9 Bidi P2 RTL-Safe English Term Prefixing).
"""
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import merge_round as mr

if not hasattr(mr, "find_anchor_pos"):
    mr.find_anchor_pos = lambda text, anchor, start=0: mr.find_anchor_offset(text, anchor, start)[0]
if not hasattr(mr, "verify_quote_verbatim"):
    def _verify_quote_verbatim(snippet: str, raw_text: str):
        mode, _s, _e = mr.verify_and_locate_span_in_part(snippet, raw_text, allow_elision=False)
        return (mode != "failed"), mode
    mr.verify_quote_verbatim = _verify_quote_verbatim

USDB_DIR = Path(os.environ.get("USDB_WORK_DIR", "/Users/macm1pro/REPOS/books/usdb_v5"))

BANNED_FLUFF_OR_ANALOGY_RE = re.compile(
    r"(?:تخيل\s+شجرة|تخيل\s+دفتر|تخيل\s+عامل|تخيل\s+صندوق|يا\s+صديقي|سؤال\s+ممتاز|أهلاً\s+بك|مرحباً\s+بك|هل\s+ننتقل|هل\s+نبدأ)"
)
# UAX #9 Rule P2: First strong directional character determines paragraph base direction,
# skipping all leading neutral/weak characters (backticks, quotes, parens, dashes, bullets).
BARE_ENGLISH_LINE_START_RE = re.compile(
    r"^\s*(?:[-*+•]\s+|\d+[.)]\s+)?[`\"'«(\[{—–\-]*[A-Za-z][A-Za-z0-9_.+-]*[`\"'»)\]}]*\s+.*[\u0600-\u06FF]",
    re.M,
)


def find_atomic_blocks(raw_text: str):
    """
    Return list of `(char_start, char_end, kind)` for:
    1. Fenced code/diagram blocks (```...```, including ```mermaid)
    2. Contiguous Markdown tables (`|...|`)
    3. Multi-line or block LaTeX display math (`$$...$$`)
    4. GitHub Callout / Alert blockquotes (`> [!NOTE]` ... contiguous `>` lines)
    5. Collapsible HTML `<details>...</details>` blocks
    None of these may EVER be split across passage boundaries.
    """
    blocks = []
    # 1. Fenced code & mermaid blocks
    for m in re.finditer(r"^```[^\n]*\n.*?^```[ \t]*$", raw_text, flags=re.M | re.S):
        blocks.append((m.start(), m.end(), "code_fence"))
    # 2. Contiguous Markdown tables (at least 2 lines starting/ending with |)
    for m in re.finditer(r"(?:^[ \t]*\|[^\n]+\|[ \t]*\n?){2,}", raw_text, flags=re.M):
        blocks.append((m.start(), m.end(), "markdown_table"))
    # 3. Display LaTeX math blocks $$...$$
    for m in re.finditer(r"\$\$.*?\$\$", raw_text, flags=re.S):
        blocks.append((m.start(), m.end(), "display_math"))
    # 4. Contiguous callout / alert blockquotes (> [!...] followed by > lines)
    for m in re.finditer(r"(?:^[ \t]*>[^\n]*\n?){2,}", raw_text, flags=re.M):
        blocks.append((m.start(), m.end(), "callout_blockquote"))
    # 5. HTML <details>...</details> blocks
    for m in re.finditer(r"<details\b[^>]*>.*?</details>", raw_text, flags=re.I | re.S):
        blocks.append((m.start(), m.end(), "details_block"))
    return blocks


def audit_and_merge_course(course_id: str, raw_crs: dict, deep_crs: dict):
    p0_errors = []
    raw_text = raw_crs["text"]
    atomic_blocks = find_atomic_blocks(raw_text)

    passages_in = deep_crs.get("deep_toc_passages", [])
    if not passages_in:
        p0_errors.append(f"[{course_id}] P0_NO_PASSAGES: deep_toc_passages is empty")
        return None, {"passed": False, "p0_error_count": len(p0_errors), "p0_errors": p0_errors}

    spans = []
    search_from = 0
    for idx, p in enumerate(passages_in):
        anchor = (p.get("anchor_start") or "").strip()
        if len(anchor.split()) < 3:
            p0_errors.append(f"[{course_id}:P{idx+1}] P0_SHORT_ANCHOR: anchor_start must be >= 3 words: {anchor!r}")
        pos = raw_text.find(anchor, search_from) if anchor else -1
        if pos == -1 and anchor:
            pos = mr.find_anchor_pos(raw_text, anchor, search_from)
        if pos == -1 and anchor:
            pos = raw_text.find(anchor, 0)
        if pos == -1:
            p0_errors.append(f"[{course_id}:P{idx+1}] P0_ANCHOR_NOT_FOUND: {anchor!r}")
            pos = search_from
        if idx == 0 and pos > 120:
            p0_errors.append(f"[{course_id}:P1] P0_FIRST_ANCHOR_NOT_AT_START: pos={pos}")
            pos = 0
        elif idx == 0:
            pos = 0
        if idx > 0 and pos <= spans[-1]:
            p0_errors.append(f"[{course_id}:P{idx+1}] P0_NON_MONOTONIC_ANCHOR: pos={pos} <= prev={spans[-1]}")
        # Check if `pos` cuts inside an atomic block!
        for b_start, b_end, b_kind in atomic_blocks:
            if b_start < pos < b_end:
                p0_errors.append(
                    f"[{course_id}:P{idx+1}] P0_BROKEN_ATOMIC_BLOCK: boundary pos={pos} splits {b_kind} [{b_start}..{b_end}]"
                )
        spans.append(pos)
        search_from = pos + max(1, len(anchor))

    merged_passages = []
    reconstructed = []
    for idx, p in enumerate(passages_in):
        c_start = spans[idx]
        c_end = spans[idx + 1] if idx + 1 < len(spans) else len(raw_text)
        p_raw = raw_text[c_start:c_end]
        reconstructed.append(p_raw)

        if len(p_raw) > 3600:
            p0_errors.append(f"[{course_id}:P{idx+1}] P0_PASSAGE_TOO_LONG: len={len(p_raw)} > 3600")

        sub_heading = (p.get("sub_heading") or "").strip()
        summary = (p.get("summary") or "").strip()
        topics = p.get("topics") or []
        queries = p.get("search_queries") or []
        tech_concepts = p.get("technical_concepts") or []
        code_artifacts = p.get("code_artifacts") or []

        if not sub_heading:
            p0_errors.append(f"[{course_id}:P{idx+1}] P0_EMPTY_SUB_HEADING")
        if not summary or len(summary) < 30:
            p0_errors.append(f"[{course_id}:P{idx+1}] P0_EMPTY_OR_SHORT_SUMMARY")
        if not topics:
            p0_errors.append(f"[{course_id}:P{idx+1}] P0_EMPTY_TOPICS")
        if not queries:
            p0_errors.append(f"[{course_id}:P{idx+1}] P0_EMPTY_SEARCH_QUERIES")
        if not tech_concepts:
            p0_errors.append(f"[{course_id}:P{idx+1}] P0_EMPTY_TECHNICAL_CONCEPTS")

        # Cognitive DNA checks on summary
        if BANNED_FLUFF_OR_ANALOGY_RE.search(summary):
            p0_errors.append(f"[{course_id}:P{idx+1}] P0_CHILDISH_ANALOGY_OR_FLUFF in summary")
        if BARE_ENGLISH_LINE_START_RE.search(summary):
            p0_errors.append(
                f"[{course_id}:P{idx+1}] P0_BARE_ENGLISH_LINE_START in summary (UAX #9 P2: prefix English/backticked terms with an Arabic word): {summary[:80]!r}"
            )

        # Verify code_artifacts verbatim in passage
        for ca_idx, ca in enumerate(code_artifacts):
            snip = (ca.get("verbatim_code_or_syntax") or "").strip()
            if not snip or snip not in raw_text:
                p0_errors.append(
                    f"[{course_id}:P{idx+1}:artifact#{ca_idx+1}] P0_UNVERIFIED_CODE_ARTIFACT: {snip!r} not exact substring of raw_text"
                )

        merged_passages.append(
            {
                "passage_id": f"{course_id}:P{idx+1}",
                "passage_index": idx + 1,
                "sub_heading": sub_heading,
                "anchor_start": p.get("anchor_start"),
                "char_start": c_start,
                "char_end": c_end,
                "char_length": len(p_raw),
                "has_code_block": "```" in p_raw,
                "has_table": bool(re.search(r"^\s*\|.*\|\s*$", p_raw, re.M)),
                "has_display_math": "$$" in p_raw,
                "summary": summary,
                "topics": topics,
                "technical_concepts": tech_concepts,
                "code_artifacts": code_artifacts,
                "search_queries": queries,
                "raw_text": p_raw,
            }
        )

    if "".join(reconstructed) != raw_text:
        p0_errors.append(
            f"[{course_id}] P0_RECONSTRUCTION_MISMATCH: reconstructed len={len(''.join(reconstructed))} != raw len={len(raw_text)}"
        )

    # Verify science_gems (Cognitive DNA: Root-Cause First + Wrong-vs-Canonical Contrast + Verbatim Rule)
    gems_in = deep_crs.get("science_gems", [])
    if len(gems_in) < 3:
        p0_errors.append(f"[{course_id}] P0_TOO_FEW_GEMS: {len(gems_in)} < 3")
    merged_gems = []
    for g_idx, g in enumerate(gems_in):
        title = (g.get("title") or "").strip()
        cat = (g.get("category") or "").strip()
        v_rule = (g.get("verbatim_rule") or "").strip()
        root_cause = (g.get("problem_root_cause") or "").strip()
        wrong_pat = (g.get("wrong_pattern") or "").strip()
        canon_pat = (g.get("canonical_pattern") or "").strip()
        expl = (g.get("explanation") or "").strip()

        if not title or not cat or not expl:
            p0_errors.append(f"[{course_id}:gem#{g_idx+1}] P0_GEM_MISSING_FIELDS")
        if not v_rule or (v_rule not in raw_text and not mr.verify_quote_verbatim(v_rule, raw_text)[0]):
            p0_errors.append(f"[{course_id}:gem#{g_idx+1}] P0_UNVERIFIED_GEM_VERBATIM: {v_rule!r}")
        if not root_cause or len(root_cause) < 20:
            p0_errors.append(f"[{course_id}:gem#{g_idx+1}] P0_MISSING_ROOT_CAUSE: problem_root_cause required by Cognitive DNA")
        if not wrong_pat or not canon_pat:
            p0_errors.append(
                f"[{course_id}:gem#{g_idx+1}] P0_MISSING_CONTRAST_PATTERNS: both wrong_pattern and canonical_pattern required"
            )
        for fld_name, fld_val in [
            ("explanation", expl),
            ("problem_root_cause", root_cause),
            ("wrong_pattern", wrong_pat),
            ("canonical_pattern", canon_pat),
        ]:
            if BANNED_FLUFF_OR_ANALOGY_RE.search(fld_val):
                p0_errors.append(f"[{course_id}:gem#{g_idx+1}] P0_CHILDISH_ANALOGY_OR_FLUFF in {fld_name}")
            if BARE_ENGLISH_LINE_START_RE.search(fld_val):
                p0_errors.append(f"[{course_id}:gem#{g_idx+1}] P0_BARE_ENGLISH_LINE_START in {fld_name}: {fld_val[:60]!r}")

        merged_gems.append(
            {
                "gem_id": f"{course_id}:G{g_idx+1}",
                "title": title,
                "category": cat,
                "verbatim_rule": v_rule,
                "problem_root_cause": root_cause,
                "wrong_pattern": wrong_pat,
                "canonical_pattern": canon_pat,
                "explanation": expl,
                "verbatim_verified": True,
            }
        )

    # Verify applied_cases (pitfalls, patterns, solved exercises)
    cases_in = deep_crs.get("applied_cases") or deep_crs.get("stories") or []
    if len(cases_in) < 2:
        p0_errors.append(f"[{course_id}] P0_TOO_FEW_APPLIED_CASES: {len(cases_in)} < 2")
    merged_cases = []
    for c_idx, cs in enumerate(cases_in):
        c_anc = (cs.get("anchor_start") or "").strip()
        if not c_anc or (c_anc not in raw_text and mr.find_anchor_pos(raw_text, c_anc, 0) == -1):
            p0_errors.append(f"[{course_id}:case#{c_idx+1}] P0_CASE_ANCHOR_NOT_FOUND: {c_anc!r}")
        merged_cases.append(
            {
                "case_id": f"{course_id}:C{c_idx+1}",
                "kind": cs.get("kind", "engineering_case"),
                "title": cs.get("title", ""),
                "anchor_start": c_anc,
                "summary": cs.get("summary", ""),
                "lesson": cs.get("lesson", ""),
            }
        )

    merged_doc = {
        "course_id": course_id,
        "track": raw_crs.get("track", "engineering"),
        "title": raw_crs["title"],
        "instructor": raw_crs.get("instructor", ""),
        "language": raw_crs.get("language", "ar-en"),
        "science": raw_crs["science"],
        "archetype": raw_crs.get("archetype", "technical_course"),
        "gate_version": "v5.1_technical_course_cognitive_dna",
        "reconstruction_verified": "".join(reconstructed) == raw_text,
        "atomic_blocks_protected": len(atomic_blocks),
        "deep_toc_passages": merged_passages,
        "science_gems": merged_gems,
        "applied_cases": merged_cases,
    }
    report = {
        "course_id": course_id,
        "passed": len(p0_errors) == 0,
        "p0_error_count": len(p0_errors),
        "p0_errors": p0_errors,
        "passages_count": len(merged_passages),
        "gems_count": len(merged_gems),
        "cases_count": len(merged_cases),
        "atomic_blocks_protected": len(atomic_blocks),
    }
    return merged_doc, report


def main():
    global USDB_DIR
    args = sys.argv[1:]
    pos_args = []
    i = 0
    while i < len(args):
        if args[i] == "--work-dir" and i + 1 < len(args):
            USDB_DIR = Path(args[i + 1]).resolve()
            i += 2
        else:
            pos_args.append(args[i])
            i += 1

    raw_all = json.loads((USDB_DIR / "raw_courses.json").read_text(encoding="utf-8"))
    targets = pos_args if pos_args else list(raw_all.keys())
    merged_all = {}
    reports_all = {}
    all_passed = True
    for cid in targets:
        dp = USDB_DIR / f"deep_course_{cid}.json"
        if not dp.exists():
            print(f"[{cid}] MISSING {dp}")
            all_passed = False
            continue
        deep_crs = json.loads(dp.read_text(encoding="utf-8"))
        m_doc, rep = audit_and_merge_course(cid, raw_all[cid], deep_crs)
        reports_all[cid] = rep
        if m_doc:
            merged_all[cid] = m_doc
        print(
            f"[{cid}] passed={rep['passed']} p0={rep['p0_error_count']} passages={rep.get('passages_count',0)} gems={rep.get('gems_count',0)} atomic_blocks={rep.get('atomic_blocks_protected',0)}"
        )
        for err in rep["p0_errors"]:
            print("  -", err)
        if not rep["passed"]:
            all_passed = False

    if len(targets) == len(raw_all) and merged_all:
        (USDB_DIR / "courses_deep_merged.json").write_text(
            json.dumps(merged_all, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (USDB_DIR / "gate_report_courses.json").write_text(
            json.dumps(reports_all, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()

