#!/usr/bin/env python3
"""
Gate v5.0 — Spoken Lecture & Matn-Sharh Triangulation Engine (Adapter B & Adapter C).
Unifies spoken transcripts + CTC word-level forced alignments (.align.json) + classical Matn clauses
with 100% lossless verbatim partitioning and deterministic timestamp extraction.
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
if not hasattr(mr, "GEM_DANGLING_AN_START_RE"):
    mr.GEM_DANGLING_AN_START_RE = re.compile(r"^\s*(?:أن|أنه|أنها|أنهم|بأن|بأنه|لأن|لأنه)\s+")

USDB_DIR = Path(os.environ.get("USDB_WORK_DIR", "/Users/macm1pro/REPOS/books/usdb_v5"))

SPOKEN_FILLER_RE = re.compile(
    r"(?:^|\s)(?:يعني|طيب|تمام\s*؟|صح\s*؟|ماشي\s*؟|يا\s+إخوة|يا\s+إخواني|يا\s+إخوان|يا\s+جماعة|أليس\s+كذلك\s*؟|واضح\s*؟|خلي\s+بالك|أوكي)(?:\s|$|[،.؟!])"
)


def fmt_mmss(sec: float) -> str:
    s = max(0, int(round(sec)))
    m, rem = divmod(s, 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h:d}:{m:02d}:{rem:02d}"
    return f"{m:02d}:{rem:02d}"


def build_char_to_time_mapper(raw_text: str, align_path: str | None, duration_sec_total: float):
    """
    Build a deterministic mapping function `span_to_time(char_start, char_end)`
    returning `(start_sec, end_sec, time_basis)`.
    When `align_path` is provided, monotonically aligns CTC words against `raw_text` character offsets
    using word-bounded local windows so short particles ('من', 'في', 'لا') never jump the cursor ahead.
    """
    n_chars = max(1, len(raw_text))
    if not align_path or not os.path.exists(align_path):
        def prop_mapper(c_start: int, c_end: int):
            s = round((max(0, c_start) / n_chars) * duration_sec_total, 2)
            e = round((min(n_chars, max(c_start + 1, c_end)) / n_chars) * duration_sec_total, 2)
            return s, max(s, e), "char_proportional_estimate"
        return prop_mapper

    aln = json.loads(Path(align_path).read_text(encoding="utf-8"))
    words_timed = []
    w_list = aln.get("w") if isinstance(aln.get("w"), list) else (aln.get("x") if isinstance(aln.get("x"), list) else None)
    if w_list is not None:
        # Format v3 ('w') & ctc-pure v4.2 ('x'): [['بسم', 0.46, 0.61, 'a'|0], ...]
        for item in w_list:
            if len(item) >= 3 and item[1] is not None and item[2] is not None:
                words_timed.append((str(item[0]), float(item[1]), float(item[2])))
    elif "words" in aln and "start" in aln and "dur" in aln:
        # Format v4: centiseconds (10ms)
        for w, st, du in zip(aln["words"], aln["start"], aln["dur"]):
            if st is not None and du is not None:
                s_sec = float(st) / 100.0
                e_sec = float(st + du) / 100.0
                words_timed.append((str(w), s_sec, e_sec))

    if not words_timed:
        def prop_mapper(c_start: int, c_end: int):
            s = round((max(0, c_start) / n_chars) * duration_sec_total, 2)
            e = round((min(n_chars, max(c_start + 1, c_end)) / n_chars) * duration_sec_total, 2)
            return s, max(s, e), "char_proportional_estimate"
        return prop_mapper

    # Monotonically anchor each word in raw_text with strict word boundaries and local windowing
    anchors = []  # (char_start, char_end, start_sec, end_sec)
    cursor = 0
    for w_str, s_sec, e_sec in words_timed:
        w_clean = w_str.strip()
        if not w_clean:
            continue
        # Tight window prevents short particles ('من', 'في') from matching inside words 150 chars ahead
        max_lookahead = 40 if len(w_clean) <= 3 else 100
        local_win = raw_text[cursor : cursor + max_lookahead]
        m_exact = re.search(rf"(?<!\w){re.escape(w_clean)}(?!\w)", local_win)
        if m_exact:
            orig_s = cursor + m_exact.start()
            orig_e = cursor + m_exact.end()
            anchors.append((orig_s, orig_e, s_sec, e_sec))
            cursor = orig_e
            continue

        # Fallback: normalized token match within tight window
        norm_w, _ = mr.normalize_with_map(w_clean)
        if norm_w:
            norm_win, win_map = mr.normalize_with_map(local_win)
            m_norm = re.search(rf"(?<!\w){re.escape(norm_w)}(?!\w)", norm_win)
            if m_norm and m_norm.start() < len(win_map):
                orig_s = cursor + win_map[m_norm.start()]
                end_idx = min(len(win_map) - 1, m_norm.end() - 1)
                orig_e = cursor + win_map[end_idx] + 1
                anchors.append((orig_s, orig_e, s_sec, e_sec))
                cursor = orig_e
                continue
        # If neither matched locally, do NOT jump cursor far ahead; keep cursor steady for next word

    if not anchors:
        def prop_mapper(c_start: int, c_end: int):
            s = round((max(0, c_start) / n_chars) * duration_sec_total, 2)
            e = round((min(n_chars, max(c_start + 1, c_end)) / n_chars) * duration_sec_total, 2)
            return s, max(s, e), "char_proportional_estimate"
        return prop_mapper

    def ctc_mapper(c_start: int, c_end: int):
        # Find first anchor >= c_start (or closest preceding)
        s_sec = anchors[0][2]
        for a_cs, a_ce, a_ss, a_es in anchors:
            if a_ce >= c_start:
                s_sec = a_ss
                break
            s_sec = a_ss
        e_sec = s_sec
        for a_cs, a_ce, a_ss, a_es in anchors:
            if a_cs <= c_end:
                e_sec = max(e_sec, a_es)
            else:
                break
        return round(s_sec, 2), round(max(s_sec, e_sec), 2), "ctc_forced_alignment"

    return ctc_mapper


def audit_and_merge_lecture(lecture_id: str, raw_lec: dict, deep_lec: dict):
    p0_errors = []
    warnings = []
    raw_text = raw_lec["text"]
    video_id = raw_lec.get("video_id", "")
    dur_total = float(raw_lec.get("duration_sec_total", 3600))
    time_mapper = build_char_to_time_mapper(raw_text, raw_lec.get("align_path"), dur_total)
    base_matn_text = raw_lec.get("base_matn_text") or ""
    base_clauses = {c["clause_id"]: c["text"] for c in raw_lec.get("base_matn_clauses", [])}

    passages_in = deep_lec.get("deep_toc_passages", [])
    if not passages_in:
        p0_errors.append(f"[{lecture_id}] P0_NO_PASSAGES: deep_toc_passages is empty")
        return None, {"passed": False, "p0_error_count": len(p0_errors), "p0_errors": p0_errors}

    # Locate anchors monotonically
    spans = []
    search_from = 0
    for idx, p in enumerate(passages_in):
        anchor = (p.get("anchor_start") or "").strip()
        if len(anchor.split()) < 4:
            p0_errors.append(f"[{lecture_id}:P{idx+1}] P0_SHORT_ANCHOR: anchor_start must be >= 4 words: {anchor!r}")
        pos = mr.find_anchor_pos(raw_text, anchor, search_from) if anchor else -1
        if pos == -1 and anchor:
            pos = mr.find_anchor_pos(raw_text, anchor, 0)
        if pos == -1:
            p0_errors.append(f"[{lecture_id}:P{idx+1}] P0_ANCHOR_NOT_FOUND: {anchor!r}")
            pos = search_from
        if idx == 0 and pos > 140:
            p0_errors.append(f"[{lecture_id}:P1] P0_FIRST_ANCHOR_NOT_AT_START: pos={pos} (>140)")
            pos = 0
        elif idx == 0:
            pos = 0
        if idx > 0 and pos <= spans[-1]:
            p0_errors.append(f"[{lecture_id}:P{idx+1}] P0_NON_MONOTONIC_ANCHOR: pos={pos} <= prev={spans[-1]}")
        spans.append(pos)
        search_from = pos + max(1, len(anchor))

    merged_passages = []
    reconstructed = []
    matn_links_count = 0

    for idx, p in enumerate(passages_in):
        c_start = spans[idx]
        c_end = spans[idx + 1] if idx + 1 < len(spans) else len(raw_text)
        p_raw = raw_text[c_start:c_end]
        reconstructed.append(p_raw)

        if len(p_raw) > 3200:
            p0_errors.append(
                f"[{lecture_id}:P{idx+1}] P0_PASSAGE_TOO_LONG: len={len(p_raw)} > 3200 chars (split into smaller thematic passages)"
            )
        if idx + 1 < len(passages_in) and p_raw.rstrip().endswith(":"):
            p0_errors.append(f"[{lecture_id}:P{idx+1}] P0_DANGLING_COLON_SPLIT: passage ends with colon ':'")

        s_sec, e_sec, t_basis = time_mapper(c_start, c_end)
        yt_url = f"https://youtu.be/{video_id}?t={int(s_sec)}" if video_id else ""

        sub_heading = (p.get("sub_heading") or "").strip()
        summary = (p.get("summary") or "").strip()
        topics = p.get("topics") or []
        queries = p.get("search_queries") or []
        if not sub_heading:
            p0_errors.append(f"[{lecture_id}:P{idx+1}] P0_EMPTY_SUB_HEADING")
        if not summary or len(summary) < 30:
            p0_errors.append(f"[{lecture_id}:P{idx+1}] P0_EMPTY_OR_SHORT_SUMMARY")
        if not topics:
            p0_errors.append(f"[{lecture_id}:P{idx+1}] P0_EMPTY_TOPICS")
        if not queries:
            p0_errors.append(f"[{lecture_id}:P{idx+1}] P0_EMPTY_SEARCH_QUERIES")

        # Check inline quotes «...» in summary and topics
        for q_match in re.findall(r"«([^»]+)»", summary + " " + " ".join(topics)):
            if len(q_match.split()) >= 2:
                ok_raw, _ = mr.verify_quote_verbatim(q_match, raw_text)
                ok_matn, _ = mr.verify_quote_verbatim(q_match, base_matn_text) if base_matn_text else (False, "none")
                if not (ok_raw or ok_matn):
                    p0_errors.append(
                        f"[{lecture_id}:P{idx+1}] P0_UNVERIFIED_INLINE_QUOTE: «{q_match}» not verbatim in lecture or base matn"
                    )

        # Check Matn-Sharh triangulation if provided
        matn_clause_id = (p.get("explained_matn_clause_id") or "").strip()
        matn_verbatim = (p.get("explained_matn_verbatim") or "").strip()
        matn_link_obj = None
        if matn_clause_id or matn_verbatim:
            if matn_clause_id not in base_clauses:
                p0_errors.append(
                    f"[{lecture_id}:P{idx+1}] P0_INVALID_MATN_CLAUSE_ID: {matn_clause_id!r} not in {list(base_clauses.keys())}"
                )
            else:
                target_clause_text = base_clauses[matn_clause_id]
                ok_m, m_mode = mr.verify_quote_verbatim(matn_verbatim, target_clause_text)
                if not ok_m or len(matn_verbatim.split()) < 3:
                    p0_errors.append(
                        f"[{lecture_id}:P{idx+1}] P0_UNVERIFIED_MATN_CLAUSE: {matn_verbatim!r} not verbatim in {matn_clause_id}"
                    )
                else:
                    matn_links_count += 1
                    matn_link_obj = {
                        "base_work_id": raw_lec.get("base_work_id"),
                        "clause_id": matn_clause_id,
                        "explained_matn_verbatim": matn_verbatim,
                        "clause_full_text": target_clause_text,
                        "verified": True,
                    }

        # Verify persons (including 1-3 word names via resolve_person_mentioned_as)
        verified_persons = []
        for per in p.get("persons", []):
            per_dict = dict(per) if isinstance(per, dict) else {"canonical_name": str(per), "mentioned_as": str(per)}
            resolved_p = mr.resolve_person_mentioned_as(per_dict, p_raw + " " + base_matn_text)
            v_in_text = bool(resolved_p.get("mentioned_in_text"))
            verified_persons.append({**per_dict, "verified_in_text": v_in_text})

        merged_passages.append(
            {
                "passage_id": f"{lecture_id}:P{idx+1}",
                "passage_index": idx + 1,
                "sub_heading": sub_heading,
                "anchor_start": p.get("anchor_start"),
                "char_start": c_start,
                "char_end": c_end,
                "char_length": len(p_raw),
                "start_sec": s_sec,
                "end_sec": e_sec,
                "duration_sec": round(e_sec - s_sec, 2),
                "time_range_fmt": f"{fmt_mmss(s_sec)} – {fmt_mmss(e_sec)}",
                "time_basis": t_basis,
                "youtube_clip_url": yt_url,
                "matn_triangulation": matn_link_obj,
                "summary": summary,
                "topics": topics,
                "persons": verified_persons,
                "places": p.get("places", []),
                "chronology": p.get("chronology", []),
                "evidences": p.get("evidences", []),
                "search_queries": queries,
                "raw_text": p_raw,
            }
        )

    # Check 100% lossless reconstruction
    if "".join(reconstructed) != raw_text:
        p0_errors.append(
            f"[{lecture_id}] P0_RECONSTRUCTION_MISMATCH: reconstructed len={len(''.join(reconstructed))} != raw len={len(raw_text)}"
        )

    min_matn_links = 1 if len(raw_text) < 6000 else 2
    if raw_lec.get("base_work_id") and matn_links_count < min_matn_links:
        p0_errors.append(
            f"[{lecture_id}] P0_MISSING_MATN_TRIANGULATION: lecture has base_work_id={raw_lec['base_work_id']} but < {min_matn_links} passages linked via explained_matn_clause_id"
        )

    # Verify science_gems (Dual-Layer Spoken Gem Contract: verbatim_rule + polished_rule)
    min_gems = 3 if len(raw_text) < 6000 else 4
    gems_in = deep_lec.get("science_gems", [])
    if len(gems_in) < min_gems:
        p0_errors.append(f"[{lecture_id}] P0_TOO_FEW_GEMS: {len(gems_in)} < {min_gems}")
    merged_gems = []
    gem_norms = set()
    for g_idx, g in enumerate(gems_in):
        v_rule = (g.get("verbatim_rule") or "").strip()
        p_rule = (g.get("polished_rule") or "").strip()
        expl = (g.get("explanation") or "").strip()
        title = (g.get("title") or "").strip()
        cat = (g.get("category") or "").strip()
        if not title or not cat or not expl:
            p0_errors.append(f"[{lecture_id}:gem#{g_idx+1}] P0_GEM_MISSING_FIELDS: title/category/explanation required")
        if "..." in v_rule or "…" in v_rule:
            p0_errors.append(f"[{lecture_id}:gem#{g_idx+1}] P0_ELLIPSIS_IN_GEM: {v_rule[:60]!r}")
        if mr.GEM_DANGLING_AN_START_RE.match(v_rule):
            p0_errors.append(f"[{lecture_id}:gem#{g_idx+1}] P0_GEM_DANGLING_START: {v_rule[:50]!r}")
        ok_v, v_mode = mr.verify_quote_verbatim(v_rule, raw_text)
        if not ok_v or len(v_rule.split()) < 5:
            p0_errors.append(f"[{lecture_id}:gem#{g_idx+1}] P0_UNVERIFIED_GEM_VERBATIM: {v_rule[:80]!r}")
        if not p_rule or len(p_rule.split()) < 4:
            p0_errors.append(
                f"[{lecture_id}:gem#{g_idx+1}] P0_MISSING_POLISHED_RULE: spoken lectures require polished_rule alongside verbatim_rule"
            )
        elif SPOKEN_FILLER_RE.search(p_rule):
            p0_errors.append(
                f"[{lecture_id}:gem#{g_idx+1}] P0_SPOKEN_FILLER_IN_POLISHED_RULE: {p_rule!r}"
            )
        _, g_pos, _ = mr.verify_and_locate_span_in_part(v_rule, raw_text, allow_elision=False)
        if g_pos == -1:
            g_pos = 0
        gs_sec, ge_sec, gt_basis = time_mapper(g_pos, g_pos + len(v_rule))
        norm_vr, _ = mr.normalize_with_map(v_rule)
        gem_norms.add(norm_vr)
        merged_gems.append(
            {
                "gem_id": f"{lecture_id}:G{g_idx+1}",
                "title": title,
                "category": cat,
                "verbatim_rule": v_rule,
                "polished_rule": p_rule,
                "explanation": expl,
                "start_sec": gs_sec,
                "end_sec": ge_sec,
                "time_range_fmt": f"{fmt_mmss(gs_sec)} – {fmt_mmss(ge_sec)}",
                "youtube_clip_url": f"https://youtu.be/{video_id}?t={int(gs_sec)}" if video_id else "",
                "verbatim_verified": ok_v,
            }
        )

    # Verify stories / applied_cases
    min_stories = 1 if len(raw_text) < 6000 else 2
    stories_in = deep_lec.get("stories") or deep_lec.get("applied_cases") or []
    if len(stories_in) < min_stories:
        p0_errors.append(f"[{lecture_id}] P0_TOO_FEW_STORIES_OR_CASES: {len(stories_in)} < {min_stories}")
    merged_stories = []
    for s_idx, st in enumerate(stories_in):
        s_anc = (st.get("anchor_start") or "").strip()
        s_pos = mr.find_anchor_pos(raw_text, s_anc, 0) if s_anc else -1
        if s_pos == -1 or len(s_anc.split()) < 4:
            p0_errors.append(f"[{lecture_id}:story#{s_idx+1}] P0_STORY_ANCHOR_NOT_FOUND: {s_anc!r}")
            s_pos = 0
        ss_sec, se_sec, _ = time_mapper(s_pos, min(len(raw_text), s_pos + 600))
        merged_stories.append(
            {
                "case_id": f"{lecture_id}:S{s_idx+1}",
                "title": st.get("title", ""),
                "anchor_start": s_anc,
                "summary": st.get("summary", ""),
                "lesson": st.get("lesson", ""),
                "start_sec": ss_sec,
                "end_sec": se_sec,
                "time_range_fmt": f"{fmt_mmss(ss_sec)} – {fmt_mmss(se_sec)}",
                "youtube_clip_url": f"https://youtu.be/{video_id}?t={int(ss_sec)}" if video_id else "",
            }
        )

    # Verify quotes
    min_quotes = 2 if len(raw_text) < 6000 else 3
    quotes_in = deep_lec.get("quotes", [])
    if len(quotes_in) < min_quotes:
        p0_errors.append(f"[{lecture_id}] P0_TOO_FEW_QUOTES: {len(quotes_in)} < {min_quotes}")
    merged_quotes = []
    for q_idx, q in enumerate(quotes_in):
        q_txt = (q.get("quote") or "").strip()
        ok_q, _ = mr.verify_quote_verbatim(q_txt, raw_text)
        if not ok_q and base_matn_text:
            ok_q, _ = mr.verify_quote_verbatim(q_txt, base_matn_text)
        if not ok_q or len(q_txt.split()) < 4:
            p0_errors.append(f"[{lecture_id}:quote#{q_idx+1}] P0_UNVERIFIED_QUOTE: {q_txt!r}")
        norm_q, _ = mr.normalize_with_map(q_txt)
        if norm_q in gem_norms:
            p0_errors.append(f"[{lecture_id}:quote#{q_idx+1}] P0_QUOTE_DUPLICATES_GEM: {q_txt[:60]!r}")
        _, q_pos, _ = mr.verify_and_locate_span_in_part(q_txt, raw_text, allow_elision=False)
        if q_pos == -1:
            q_pos = 0
        qs_sec, qe_sec, _ = time_mapper(q_pos, q_pos + len(q_txt))
        merged_quotes.append(
            {
                "quote_id": f"{lecture_id}:Q{q_idx+1}",
                "quote": q_txt,
                "speaker": q.get("speaker", raw_lec.get("speaker", "")),
                "context": q.get("context", ""),
                "start_sec": qs_sec,
                "end_sec": qe_sec,
                "time_range_fmt": f"{fmt_mmss(qs_sec)} – {fmt_mmss(qe_sec)}",
                "youtube_clip_url": f"https://youtu.be/{video_id}?t={int(qs_sec)}" if video_id else "",
                "verbatim_verified": ok_q,
            }
        )

    merged_doc = {
        "lecture_id": lecture_id,
        "title": raw_lec["title"],
        "speaker": raw_lec["speaker"],
        "speaker_slug": raw_lec.get("speaker_slug", ""),
        "science": raw_lec["science"],
        "archetype": raw_lec.get("archetype", "spoken_lecture"),
        "video_id": video_id,
        "duration_str": raw_lec.get("duration_str", fmt_mmss(dur_total)),
        "base_work_id": raw_lec.get("base_work_id"),
        "base_work_title": raw_lec.get("base_work_title"),
        "gate_version": "v5.1_lecture_matn_grounded",
        "reconstruction_verified": "".join(reconstructed) == raw_text,
        "matn_triangulation_count": matn_links_count,
        "deep_toc_passages": merged_passages,
        "science_gems": merged_gems,
        "stories": merged_stories,
        "quotes": merged_quotes,
    }
    report = {
        "lecture_id": lecture_id,
        "passed": len(p0_errors) == 0,
        "p0_error_count": len(p0_errors),
        "p0_errors": p0_errors,
        "warnings": warnings,
        "passages_count": len(merged_passages),
        "gems_count": len(merged_gems),
        "stories_count": len(merged_stories),
        "quotes_count": len(merged_quotes),
        "matn_triangulation_count": matn_links_count,
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

    raw_all = json.loads((USDB_DIR / "raw_lectures.json").read_text(encoding="utf-8"))
    targets = pos_args if pos_args else list(raw_all.keys())
    merged_all = {}
    reports_all = {}
    all_passed = True
    for lid in targets:
        dp = USDB_DIR / f"deep_lecture_{lid}.json"
        if not dp.exists():
            print(f"[{lid}] MISSING {dp}")
            all_passed = False
            continue
        deep_lec = json.loads(dp.read_text(encoding="utf-8"))
        m_doc, rep = audit_and_merge_lecture(lid, raw_all[lid], deep_lec)
        reports_all[lid] = rep
        if m_doc:
            merged_all[lid] = m_doc
        print(
            f"[{lid}] passed={rep['passed']} p0={rep['p0_error_count']} passages={rep.get('passages_count',0)} gems={rep.get('gems_count',0)} matn_links={rep.get('matn_triangulation_count',0)}"
        )
        for err in rep["p0_errors"]:
            print("  -", err)
        if not rep["passed"]:
            all_passed = False

    if len(targets) == len(raw_all) and merged_all:
        (USDB_DIR / "lectures_deep_merged.json").write_text(
            json.dumps(merged_all, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (USDB_DIR / "gate_report_lectures.json").write_text(
            json.dumps(reports_all, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()

