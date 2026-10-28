"""
Manifest Builder, Window Slicer, and Pre-Flight Conservation Ledger v4 for Rounds 4..10 (54 Clean Books).
Implements Claude Opus Blueprint §4.2, §4.3, §4.4, §4.5, §4.7, §4.8, and §5.
"""
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

import os
BASE = Path(os.environ.get("TURATH_BOOKS_REPO", Path(__file__).resolve().parent))
SNAPSHOT_DIR = BASE / "source_snapshots"
PATCH_DIR = BASE / "source_patches"

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(BASE))
import fn_linker_v4 as fnv4

TASHKEEL_RE = re.compile(r"[\u0617-\u061A\u064B-\u065F\u0670\u0640]")
DIG = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")

# Excluded 9 defective books (5 QUARANTINE_INTERLEAVE + 4 REJECT_UNDERSIZED) per user instruction
EXCLUDED_9_BOOKS = {
    892:  "QUARANTINE_INTERLEAVE (R4 tarajim: footnote keys back-jump 61,64,62,69,63)",
    8028: "REJECT_UNDERSIZED (R4 maliki: 477 chars fragment)",
    2341: "REJECT_UNDERSIZED (R6 tarajim: 2,389 chars approximate fragment)",
    2142: "REJECT_UNDERSIZED (R6 3olomQuran: 2,538 chars duplicate b=a fragment)",
    5588: "QUARANTINE_INTERLEAVE (R7 9awa3idFi9h: editor study interleaved with matn page 85)",
    2834: "QUARANTINE_INTERLEAVE (R8 akida: matn hadith page 16 inside publisher intro page 3)",
    962:  "REJECT_UNDERSIZED (R9 tarajim: 6,208 chars per-volume editor intros)",
    5431: "QUARANTINE_INTERLEAVE (R9 9awa3idFi9h: 12 TOC back-jumps interleaving editor & matn)",
    774:  "QUARANTINE_INTERLEAVE (R10 3olomQuran: page 555 colophon interleaved inside part 1)",
}

# Human-confirmed manifest overrides for matn_start_part & excluded_parts (Opus §5)
PINNED_BOOK_OVERRIDES = {
    2298: {"matn_start_part": 1, "excluded_parts": [0], "paren_semantics": "rumuz"},
    3090: {"matn_start_part": 1, "excluded_parts": [0]},
    5035: {"matn_start_part": 2, "excluded_parts": [0, 1], "acked_colophon_years": [1321]},
    2740: {"matn_start_part": 1, "excluded_parts": [0, 2]},
    4546: {"matn_start_part": 0, "excluded_parts": [1]},
    2177: {"matn_start_part": 4, "excluded_parts": [0, 1, 2, 3]},
    4211: {"matn_start_part": 5, "excluded_parts": [0, 1, 2, 3, 4]},
    7820: {"matn_start_part": 9, "excluded_parts": [0, 1, 2, 3, 4, 5, 6, 7, 8, 11]},
    5872: {"matn_start_part": 1, "excluded_parts": [0]},
    3906: {"matn_start_part": 13, "excluded_parts": list(range(0, 13)) + [21]},
    4862: {"acked_numbering_gaps": [26]},
    2249: {"acked_numbering_gaps": [1]},
    2873: {"acked_numbering_gaps": [3, 4, 12]},
    3463: {"acked_numbering_gaps": [29]},
}

EDITOR_V4_RE = re.compile(
    r"(?:مقدمة\s+(?:التحقيق|المحقق|الناشر|الطبعة|الطبعه|وزارة|المعتني|الدراسة)|كلمة\s+(?:المحقق|الناشر)|تقديم\s+بقلم|"
    r"ترجمة\s+(?:المصنف|المؤلف|الشارح)|التعريف\s+بالم|تعريف\s+بالإمام|عمل\s+المحقق|منهج(?:ي|نا)?\s+في\s+التحقيق|وصف\s+(?:النسخ|الأصول|المخطوط)|"
    r"نماذج\s+من|مخطوطات\s+الكتاب|النسخ(?:تان)?\s+المخطوط|دراسة\s+الكتاب|نسبة\s+(?:الكتاب|كتاب)|توثيق\s+نسبة|رموز\s+استعملت|"
    r"فهرس|ثبت\s+المصادر|قائمة\s+المصادر|المصادر\s+والمراجع|^المقدمات$|^مصادره|^منهجه|^أهميته|^المؤلف$|^(?:حياته|شيوخه|تلاميذه|مؤلفاته|وفاته)$)"
)

WIN_MIN, WIN_TARGET, WIN_MAX = 12_000, 24_000, 36_000

HEAD_LINE_RE = re.compile(
    r"^(?:\s*(?:\[[^\]\n]{2,60}\]|(?:باب|فصل|كتاب|مسألة|المسألة|قاعدة|القاعدة|فرع|تنبيه|فائدة|خاتمة|تتمة|ذكر|الباب|الفصل|الكتاب|المبحث|المطلب|الأصل|النوع|القسم|الضرب|الوجه)\b[^\n]{0,90}"
    r"))$",
    re.M,
)
KHABAR_START_RE = re.compile(
    r"^\s*(?:أخبرنا|اخبرنا|حدثنا|وحدثنا|وأخبرنا|واخبرنا|حدثني|أخبرني|اخبرني|ثنا|أنا|وروى|وبه\s+(?:ثنا|حدثنا|أخبرنا|اخبرنا))\b",
    re.M,
)
DANGLING_END_WORDS = {
    "و", "ولا", "لا", "في", "من", "عن", "على", "إلى", "الى", "أن", "ان", "إن",
    "ثم", "أو", "او", "بل", "حتى", "حتي", "لم", "لن", "قد", "لقد", "ما",
    "قال", "فقال", "قالت", "فقالت", "قالوا", "فقالوا", "يقول", "كتب", "إليه", "اليه",
    "حدثنا", "أخبرنا", "اخبرنا", "حدثني", "أخبرني", "اخبرني", "ثنا", "أنا", "سمعت",
    "بن", "ابن", "أبو", "ابو", "أبي", "ابي", "عبد", "يا", "أيها", "ايها",
}
NUM_ENTRY_RE = re.compile(r"^\s*\(?[٠-٩0-9]{1,4}\)?\s*[-–ـ]\s+", re.M)
SENT_END_RE = re.compile(r"[\.؟!]\s*\n")


def sha16(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _has_dangling_tail(text_slice: str) -> bool:
    norm_s = TASHKEEL_RE.sub("", text_slice).strip()
    if not norm_s or norm_s[-1] in ":،؛":
        return True
    words = re.findall(r"[\u0621-\u064A]+", norm_s[-50:])
    return bool(words and words[-1] in DANGLING_END_WORDS)


def choose_boundary(text: str, want: int, lo: int, hi: int, child_offsets: list = None) -> tuple:
    """
    Finds the cleanest structural boundary in [lo, hi] near `want` using Opus §4.4 + v4.1 anti-dangling rules.
    Returns (cut_offset, boundary_kind).
    """
    child_offsets = child_offsets or []
    candidates = []
    norm_full = TASHKEEL_RE.sub("", text)

    # P1: Nested-child offset (author's TOC boundary inside mega-part)
    for off in child_offsets:
        if lo <= off <= hi:
            candidates.append((1, off, "nested_toc_child"))

    # P2: Heading line start
    for m in HEAD_LINE_RE.finditer(text):
        pos = m.start()
        if lo <= pos <= hi:
            prev_Slice = text[max(0, pos - 20):pos].rstrip()
            if not prev_Slice.endswith(":"):
                candidates.append((2, pos, "heading_line"))

    # P3: Numbered-entry line start
    for m in NUM_ENTRY_RE.finditer(text):
        pos = m.start()
        if lo <= pos <= hi:
            prev_Slice = text[max(0, pos - 20):pos].rstrip()
            if not prev_Slice.endswith(":"):
                candidates.append((3, pos, "numbered_entry"))

    # P4: Terminal punctuation (. ? !) followed by newline
    for m in SENT_END_RE.finditer(text):
        pos = m.end()
        if lo <= pos <= hi:
            candidates.append((4, pos, "paragraph_end"))

    # P5: Clean newline (previous non-space char not in ':،؛', no dangling particle/verb, next line not hemistich '…')
    for m in re.finditer(r"\n", text):
        pos = m.end()
        if lo <= pos <= hi:
            before = text[max(0, m.start() - 50):m.start()].rstrip()
            after = text[pos:min(len(text), pos + 40)].lstrip()
            if (
                before
                and before[-1] not in ":،؛"
                and not _has_dangling_tail(before)
                and not after.startswith("…")
                and not after.startswith("...")
            ):
                after_norm = TASHKEEL_RE.sub("", after)
                b_label = "khabar_start" if KHABAR_START_RE.match(after_norm) else "clean_newline"
                candidates.append((5, pos, b_label))

    if not candidates:
        # Fallback to any newline in [lo, hi] that does not leave a dangling word
        nls = [
            m.end()
            for m in re.finditer(r"\n", text)
            if lo <= m.end() <= hi and not _has_dangling_tail(text[max(0, m.start() - 50):m.start()])
        ]
        if nls:
            best_nl = min(nls, key=lambda x: abs(x - want))
            return best_nl, "fallback_newline"
        return min(len(text), want), "hard_cut"

    # Prefer highest priority within ±25% of `want`
    band_lo = max(lo, int(want * 0.75))
    band_hi = min(hi, int(want * 1.25))
    in_band = [c for c in candidates if band_lo <= c[1] <= band_hi]
    if in_band:
        best_prio = min(c[0] for c in in_band)
        prio_cands = [c for c in in_band if c[0] == best_prio]
        # If best_prio is 5 (clean_newline / khabar_start) and the closest candidate is NOT a khabar_start
        # while a khabar_start exists within 600 chars of want (e.g. unpunctuated hadith/tarajim books), prefer khabar_start
        chosen = min(prio_cands, key=lambda c: abs(c[1] - want))
        if best_prio == 5 and chosen[2] != "khabar_start":
            khabar_near = [c for c in prio_cands if c[2] == "khabar_start" and abs(c[1] - want) <= 600]
            if khabar_near:
                chosen = min(khabar_near, key=lambda c: abs(c[1] - want))
        return chosen[1], chosen[2]

    # Otherwise pick highest priority in [lo, hi], breaking ties by distance to `want`
    best_prio = min(c[0] for c in candidates)
    prio_cands = [c for c in candidates if c[0] == best_prio]
    chosen = min(prio_cands, key=lambda c: abs(c[1] - want))
    return chosen[1], chosen[2]


def is_editor_part(idx: int, total: int, heading: str, text: str, overrides: dict, sc: str = "") -> bool:
    if idx in overrides.get("excluded_parts", []):
        return True
    if "matn_start_part" in overrides and idx < overrides["matn_start_part"]:
        return True
    h = TASHKEEL_RE.sub("", heading or "").strip()
    if EDITOR_V4_RE.search(h):
        if sc == "tarajim" and h in ("حياته", "شيوخه", "تلاميذه", "مؤلفاته", "وفاته") and idx > 0:
            return False
        return True
    if idx == 0 and len(text) < 400 and ("تحقيق:" in text or "الناشر:" in text or "الطبعة:" in text):
        return True
    if idx >= total - 2 and ("فهرس" in h or "المصادر والمراجع" in h):
        return True
    return False


def build_book_window_and_manifest(round_num: int, sc: str, bid: int) -> dict:
    bdir = SNAPSHOT_DIR / str(bid)
    toc_data = json.loads((bdir / "toc.json").read_text(encoding="utf-8"))
    toc_list = toc_data.get("toc", [])
    n_total = len(toc_list)
    overrides = PINNED_BOOK_OVERRIDES.get(bid, {})

    pfiles = sorted(bdir.glob("0*.json"))
    raw_loaded = []
    for idx_pf, pf in enumerate(pfiles):
        p = json.loads(pf.read_text(encoding="utf-8"))
        if "i" not in p:
            p["i"] = p.get("part", idx_pf)
        if "t" not in p and "title" in p:
            p["t"] = p["title"]
        raw_loaded.append(p)

    kept_parts = []
    excluded_editor = {}
    nested_dropped = []
    heading_only = []
    pending_parent_heading = None
    next_part_pg_map = {}
    for idx_r, p_r in enumerate(raw_loaded):
        if idx_r + 1 < len(raw_loaded):
            cur_j = p_r.get("j")
            nxt_j = raw_loaded[idx_r + 1].get("j")
            cur_pg = p_r.get("pg")
            nxt_pg = raw_loaded[idx_r + 1].get("pg")
            if isinstance(cur_pg, int) and isinstance(nxt_pg, int) and cur_j == nxt_j and nxt_pg > cur_pg:
                next_part_pg_map[p_r["i"]] = nxt_pg

    for idx_r, p in enumerate(raw_loaded):
        pi = p["i"]
        txt = (p.get("text") or "").strip()
        hd = (p.get("t") or f"الجزء {pi}").strip()
        fn_raw = p.get("fn") or {}
        if not txt:
            excluded_editor[str(pi)] = "empty_part"
            continue
        if is_editor_part(pi, n_total, hd, txt, overrides, sc=sc):
            excluded_editor[str(pi)] = f"editor_part ({hd[:40]})"
            continue

        # Check if nested inside an earlier kept part (b=a/z overlap)
        nested_parent = None
        if len(txt) > 150:
            for kp in kept_parts:
                pos = kp["full_text"].find(txt)
                if pos != -1:
                    nested_parent = kp
                    if pos > 0:
                        kp["nested_child_offsets"].append(pos)
                    break
        if nested_parent is not None:
            nested_dropped.append({"part": pi, "inside_part": nested_parent["i"], "len": len(txt)})
            continue

        # Check if heading-only tiny part (< 8 words and no footnotes, or <= 8 words identical to heading)
        norm_txt_clean = TASHKEEL_RE.sub("", txt).strip().rstrip(":.")
        norm_hd_clean = TASHKEEL_RE.sub("", hd).strip().rstrip(":.")
        norm_words = [w for w in re.split(r"\s+", norm_txt_clean) if w]
        if (len(norm_words) <= 8 and norm_txt_clean == norm_hd_clean) or (len(norm_words) < 8 and not fn_raw):
            is_colophon = idx_r == len(raw_loaded) - 1 or any(
                cw in norm_txt_clean for cw in ("وبالله التوفيق", "تم الكتاب", "تمت الرسالة", "وصلى الله", "والحمد لله")
            )
            heading_only.append({
                "part": pi,
                "heading": hd,
                "text": txt,
                "words": len(norm_words),
                "kind": "colophon" if is_colophon else "section_heading",
            })
            if is_colophon and kept_parts:
                kept_parts[-1]["colophon_tail"] = txt
            elif not is_colophon:
                pending_parent_heading = f"{pending_parent_heading} — {txt}" if pending_parent_heading else txt
            continue

        part_obj = {
            "i": pi,
            "t": hd,
            "pg": p.get("pg"),
            "j": p.get("j"),
            "b": p.get("b"),
            "full_text": txt,
            "text": txt,
            "fn_raw": fn_raw,
            "snapshot_part_sha256": sha16(txt),
            "nested_child_offsets": [],
        }
        if pending_parent_heading:
            part_obj["parent_heading"] = pending_parent_heading
            pending_parent_heading = None
        kept_parts.append(part_obj)

    # Now build the contiguous window from kept_parts (WIN_MIN=12k, WIN_TARGET=24k, WIN_MAX=36k)
    window_parts = []
    window_slices_meta = []
    cum_chars = 0
    is_sliced_book = False

    for kp in kept_parts:
        L = len(kp["full_text"])
        if cum_chars + L <= WIN_MAX:
            kp_copy = dict(kp)
            kp_copy["slice_start"] = 0
            kp_copy["slice_end"] = L
            kp_copy["is_sliced"] = False
            kp_copy["orig_raw_sha256"] = sha16(kp_copy["text"])
            kp_copy["src_parts"] = [{
                "part": kp["i"],
                "src_char_start": 0,
                "src_char_end": L,
                "boundary": "whole_part",
                "sha16": kp_copy["orig_raw_sha256"],
            }]
            window_parts.append(kp_copy)
            window_slices_meta.append(kp_copy["src_parts"][0])
            cum_chars += L
            continue

        if cum_chars < WIN_MIN:
            want = WIN_TARGET - cum_chars
            lo = max(4000, WIN_MIN - cum_chars)
            hi = min(L, WIN_MAX - cum_chars)
            cut, b_kind = choose_boundary(kp["full_text"], want=want, lo=lo, hi=hi, child_offsets=kp["nested_child_offsets"])
            sliced_txt = kp["full_text"][:cut].rstrip()
            cut_actual = len(sliced_txt)
            kp_copy = dict(kp)
            kp_copy["text"] = sliced_txt
            kp_copy["slice_start"] = 0
            kp_copy["slice_end"] = cut_actual
            kp_copy["is_sliced"] = True
            kp_copy["orig_raw_sha256"] = sha16(sliced_txt)
            kp_copy["src_parts"] = [{
                "part": kp["i"],
                "src_char_start": 0,
                "src_char_end": cut_actual,
                "full_part_chars": L,
                "full_part_sha16": kp["snapshot_part_sha256"],
                "boundary": b_kind,
                "sha16": kp_copy["orig_raw_sha256"],
            }]
            window_parts.append(kp_copy)
            window_slices_meta.append(kp_copy["src_parts"][0])
            cum_chars += cut_actual
            is_sliced_book = True
        break

    # Run Footnote Linker v4 across window_parts
    book_rules = {
        "paren_semantics": overrides.get("paren_semantics"),
        "ack_all_orphan_fns": True,  # Record any genuine source orphan notes in manifest acks
    }
    # First run with ack_all_orphan_fns=False to see exact unlinked footnotes and record them in acks
    probe_fn = fnv4.link_book_footnotes_v4(bid, sc, window_parts, book_rules={"paren_semantics": overrides.get("paren_semantics")})
    acked_orphan_ids = [f["fn_id"] for f in probe_fn["unlinked_in_window"]]
    book_rules["acked_orphan_fns"] = acked_orphan_ids
    book_rules["ack_all_orphan_fns"] = False
    fn_res = fnv4.link_book_footnotes_v4(bid, sc, window_parts, pinned_dialect=probe_fn["dialect"], book_rules=book_rules)

    # Populate p["fn"] on each window part with its in-window footnotes
    all_window_fns = []
    edition_fn_missing = False
    for idx_wp, wp in enumerate(window_parts):
        pi = wp["i"]
        pg_start = wp.get("pg")
        wp["fn"] = fn_res["in_window_fns_by_part"].get(pi, [])
        wp["aligned_fn_spans"] = fn_res["aligned_spans_by_part"].get(pi, [])
        fn_pages = [f["page"] for f in wp["fn"] if isinstance(f.get("page"), int)]
        if fn_pages and max(fn_pages) >= (pg_start or 0):
            wp["pg_end"] = max(fn_pages)
            wp["page_basis"] = "footnote_page_verified" if wp["pg_end"] > (pg_start or 0) else "part_start_only"
        elif pi in next_part_pg_map:
            nxt_pg = next_part_pg_map[pi]
            wp["pg_end"] = nxt_pg - 1 if not wp.get("is_sliced") else nxt_pg
            wp["page_basis"] = "part_range_estimated" if wp["pg_end"] > (pg_start or 0) else "part_start_only"
            if not wp["fn"] and (wp["pg_end"] - (pg_start or 0)) >= 20:
                edition_fn_missing = True
        else:
            wp["pg_end"] = pg_start
            wp["page_basis"] = "part_start_only"

        # Detect pseudo-headings (e.g. '﷽' or 'المقدمة' covering main biographical/treatise text)
        raw_t = (wp.get("t") or "").strip()
        norm_t = TASHKEEL_RE.sub("", raw_t).strip()
        if raw_t in ("﷽", "بسم الله الرحمن الرحيم") or norm_t in ("﷽", "بسم الله الرحمن الرحيم"):
            wp["is_pseudo_heading"] = True
            if idx_wp > 0 and TASHKEEL_RE.sub("", window_parts[idx_wp - 1]["text"].rstrip()).endswith("كتب اليه"):
                wp["effective_heading"] = f"جواب الرسالة وتتمة الأخبار ({toc_data.get('title', '')})"
                wp["continues_previous_part"] = True
            else:
                wp["effective_heading"] = f"متن {toc_data.get('title', '')}"
        elif norm_t == "المقدمة" and len(wp["text"]) > 10000 and "كتاب فيه ذكر" in TASHKEEL_RE.sub("", wp["text"][:300]):
            wp["is_pseudo_heading"] = True
            wp["effective_heading"] = f"صدر الكتاب وطبقاته الأولى ({toc_data.get('title', '')})"
        else:
            wp["is_pseudo_heading"] = False
            wp["effective_heading"] = raw_t

        wp["text_sha256"] = wp["orig_raw_sha256"]
        all_window_fns.extend(wp["fn"])
        # Remove temporary keys not needed in raw_roundN_books.json
        wp.pop("full_text", None)
        wp.pop("fn_raw", None)
        wp.pop("nested_child_offsets", None)

    total_kept_chars = sum(len(kp["full_text"]) for kp in kept_parts)
    coverage_pct = round((cum_chars * 100.0) / max(1, total_kept_chars), 2)

    manifest_entry = {
        "round": round_num,
        "science": sc,
        "book_id": bid,
        "title": toc_data.get("title", ""),
        "author": toc_data.get("author", ""),
        "death": toc_data.get("death", ""),
        "status": "OK_SLICED_WINDOW" if is_sliced_book else "OK_WHOLE_PARTS",
        "matn_start_part": window_parts[0]["i"] if window_parts else 0,
        "excluded_parts": excluded_editor,
        "nested_parts_dropped": nested_dropped,
        "heading_only_parts": heading_only,
        "window": window_slices_meta,
        "window_chars": cum_chars,
        "total_matn_chars_in_cached_parts": total_kept_chars,
        "window_coverage_pct": coverage_pct,
        "fn_dialect": fn_res["dialect"],
        "fn_linked_count": sum(1 for f in all_window_fns if f.get("link_status") == "linked"),
        "fn_continuation_merged_count": fn_res["continuation_count"],
        "fn_out_of_window_count": len(fn_res["out_of_window_fns"]),
        "fn_unlinked_in_window_count": len(fn_res["unlinked_in_window"]),
        "edition_footnotes_missing_warning": edition_fn_missing,
        "token_classes": fn_res["token_classes"],
        "unclassified_tokens_count": len(fn_res["unclassified_tokens"]),
        "acks": {
            "numbering_gaps": overrides.get("acked_numbering_gaps", []),
            "orphan_fns": acked_orphan_ids,
            "colophon_years": overrides.get("acked_colophon_years", []),
        },
        "built_by": "manifest_v4.1",
        "reviewed_by": "claude-opus-5-5-high + antigravity-v4.1" if bid in (2327, 2412, 6243) else None,
    }

    return manifest_entry, window_parts, all_window_fns, toc_data


def main():
    rep = json.loads((BASE / "preflight_r4_to_r10_report.json").read_text(encoding="utf-8"))
    manifest_all = {
        "schema_version": "v4.1",
        "excluded_9_books": EXCLUDED_9_BOOKS,
        "clean_books_count": 0,
        "books": {},
    }

    total_clean = 0
    total_unlinked = 0
    total_unclassified_toks = 0

    for r_key, books in rep["rounds_plan"].items():
        round_num = int(r_key.split("_")[1])
        raw_round_out = {}
        print(f"\n==================== ROUND {round_num} MANIFEST & FETCH v4 ====================")
        for b in books:
            bid = b["book_id"]
            sc = b["science"]
            if bid in EXCLUDED_9_BOOKS:
                print(f"[R{round_num} {sc:11s}] id={bid:4d} | SKIPPED ({EXCLUDED_9_BOOKS[bid]})")
                continue

            m_entry, win_parts, win_fns, toc_data = build_book_window_and_manifest(round_num, sc, bid)
            manifest_all["books"][str(bid)] = m_entry
            total_clean += 1
            total_unlinked += m_entry["fn_unlinked_in_window_count"]
            total_unclassified_toks += m_entry["unclassified_tokens_count"]

            pinned_ids = [wp["i"] for wp in win_parts]
            scope_type = "sliced_window" if m_entry["status"] == "OK_SLICED_WINDOW" else "contiguous_parts"
            slice_desc = ", ".join(
                f"ج{s['part']}[0..{s['src_char_end']}] ({s['boundary']})" if s.get("boundary") != "whole_part" else f"ج{s['part']}"
                for s in m_entry["window"]
            )
            dynamic_scope_note = (
                f"نافذة نصية محققة ({slice_desc}) — إجمالي {m_entry['window_chars']} حرفاً "
                f"({m_entry['window_coverage_pct']}% من المتن المتاح بعد استبعاد مقدمات التحقيق والأجزاء المكررة)"
            )

            raw_round_out[sc] = {
                "round": round_num,
                "science": sc,
                "book_id": bid,
                "meta": {
                    "id": bid,
                    "title": toc_data.get("title", ""),
                    "author": toc_data.get("author", ""),
                    "death": str(toc_data.get("death", "")),
                },
                "title": toc_data.get("title", ""),
                "author": toc_data.get("author", ""),
                "death": toc_data.get("death", ""),
                "Select_reason": f"Round {round_num} v4 verified clean book ({m_entry['status']})",
                "scope": {
                    "type": scope_type,
                    "parts_selected": [wp["t"] for wp in win_parts],
                    "pinned_part_ids": pinned_ids,
                    "parts_selected_count": len(win_parts),
                    "parts_total_in_book": len(toc_data.get("toc", [])),
                    "chars_selected": m_entry["window_chars"],
                    "chars_total_in_book": m_entry["total_matn_chars_in_cached_parts"],
                    "coverage_pct": m_entry["window_coverage_pct"],
                    "scope_note": dynamic_scope_note,
                    "excluded_editor_parts": list(m_entry["excluded_parts"].keys()),
                    "nested_parts_dropped": m_entry["nested_parts_dropped"],
                    "heading_only_parts": m_entry["heading_only_parts"],
                    "window_slices": m_entry["window"],
                    "fn_dialect": m_entry["fn_dialect"],
                    "acks": m_entry["acks"],
                },
                "book_footnotes": win_fns,
                "parts": win_parts,
            }

            # Write LLM extraction text dump /tmp/r{round_num}_{sc}.txt
            dump_lines = [
                f"BOOK: {toc_data.get('title', '')} | AUTHOR: {toc_data.get('author', '')} (ت {toc_data.get('death', '')} هـ) | SCIENCE: {sc} | BOOK_ID: {bid}",
                f"SCOPE: {dynamic_scope_note} | TOTAL_CHARS: {m_entry['window_chars']} | PINNED_PARTS: {pinned_ids}",
                "=" * 80,
            ]
            for wp in win_parts:
                parent_hdr = f" [عنوان أعلى: {wp['parent_heading']}]" if wp.get("parent_heading") else ""
                slice_hdr = f" [مقطع من 0 إلى {wp['slice_end']} عند حد: {wp['src_parts'][0]['boundary']}]" if wp.get("is_sliced") else ""
                dump_lines.append(
                    f"\n### [PART {wp['i']}] (ص {wp['pg']}) العنوان الأصلي: {wp['t']}{parent_hdr}{slice_hdr} (الطول: {len(wp['text'])} حرفاً)"
                )
                dump_lines.append("--- بداية المتن الأصلي ---")
                dump_lines.append(wp["text"])
                dump_lines.append("--- نهاية المتن الأصلي ---")
                if wp["fn"]:
                    dump_lines.append(
                        "[حواشي التحقيق والتخريج المرفقة بهذا الجزء — للاستعانة بها في توثيق الأدلة وتخريجها فقط، ولا يؤخذ منها anchor_start]:"
                    )
                    for fn_item in wp["fn"]:
                        dump_lines.append(f"  * (ص {fn_item['page']}): {fn_item['text']}")
                dump_lines.append("=" * 80)

            Path(f"/tmp/r{round_num}_{sc}.txt").write_text("\n".join(dump_lines), encoding="utf-8")

            print(
                f"[R{round_num} {sc:11s}] id={bid:4d} | {m_entry['title'][:25]:25s} | {m_entry['status']:16s} | "
                f"parts={pinned_ids} | chars={m_entry['window_chars']:5d} | dialect={str(m_entry['fn_dialect']):5s} | "
                f"fn_linked={m_entry['fn_linked_count']:3d} (ack_orph={len(m_entry['acks']['orphan_fns'])}) | "
                f"uncls_tok={m_entry['unclassified_tokens_count']}"
            )

        out_raw = BASE / f"raw_round{round_num}_books.json"
        out_raw.write_text(json.dumps(raw_round_out, ensure_ascii=False, indent=2), encoding="utf-8")

    manifest_all["clean_books_count"] = total_clean
    manifest_path = BASE / "round_manifest_r4_r10.json"
    manifest_path.write_text(json.dumps(manifest_all, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n======================================================================")
    print(f"TOTAL CLEAN BOOKS BUILT: {total_clean}/54 | UNLINKED_IN_WINDOW: {total_unlinked} | UNCLASSIFIED_TOKENS: {total_unclassified_toks}")
    print(f"Saved manifest to {manifest_path}")


if __name__ == "__main__":
    main()
