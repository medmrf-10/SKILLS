"""
Footnote Linker v4 & Token Conservation Classifier (per Claude Opus Blueprint §4.5 & §4.6).
Implements:
- 6 Footnote marker dialects (neg, paren, brack, dash, bare, star) with LCS-maximizing auto-detection
- Cross-page continuation merging ('=' or unmarked head lines)
- Juz-aware & pg=None-safe footnote page keys and IDs
- Monotone LCS alignment across the book/part stream (eliminating greedy cursor deadlocks)
- Window-slice footnote scoping (separating in-window linked footnotes from out-of-window footnotes)
- Closed-world classification of unaligned parenthetical/bracket tokens (including source-stripped footnote markers in hdth/sharh repos)
"""
import re
from collections import Counter

DIG = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
TASHKEEL_RE = re.compile(r"[\u0617-\u061A\u064B-\u065F\u0670\u0640]")

# Stage 4 Normalizer Regexes (Opus §4.6)
FOLIO_MARKER_RE = re.compile(
    r"(?:/\s*)?\((?=[^()\n]{1,16}\))(?=[^)]*[أابظوزدمه])\s*[٠-٩0-9]{1,4}\s*/?\s*[أابظو]?\u064e?\s*"
    r"(?:/\s*[أابظوزدمه]\u064e?\s*){0,2}\)"
)
EDITION_PAGE_RE = re.compile(r"⦗[^⦘\n]{1,20}⦘")

FN_HEAD = {
    "neg":   re.compile(r"^\s*\(¬([٠-٩0-9]+)\)\s*"),
    "paren": re.compile(r"^\s*\(([٠-٩0-9]+)\)\s*"),
    "brack": re.compile(r"^\s*\[([٠-٩0-9]+)\]\s*"),
    "dash":  re.compile(r"^\s*([٠-٩0-9]+)\s*[-–.)]\s*"),
    "bare":  re.compile(r"^\s*([٠-٩0-9]{1,3})\s+(?=[^\s\-–])"),
    "star":  re.compile(r"^\s*\(?(\*+)\)?\s*"),
}

TXT_TOK = {
    "neg":   re.compile(r"\(¬([٠-٩0-9]+)\)"),
    "paren": re.compile(r"\(([٠-٩0-9]+|\*+)\)"),
    "brack": re.compile(r"\[([٠-٩0-9]+)\]"),
    "bare":  re.compile(r"(?<=[\u0621-\u064A\u064B-\u0652﴾»\"'\)\]])\s?([٠-٩]{1,2})(?![٠-٩0-9/\-–])(?=[\s\.,،:؛!?»\"']|$)"),
    "star":  re.compile(r"\((\*+)\)"),
}

COUNT_NOUNS = {
    "عدد", "رقم", "برقم", "الأسطر", "سطر", "سطرا", "ورقة", "ورقات",
    "ص", "صفحة", "ج", "جزء", "سنة", "عام", "مجلد", "حديث", "آية",
    "المسألة", "مسألة", "القاعدة", "قاعدة", "الباب", "باب", "الفصل", "فصل",
    "الفرع", "فرع", "المطلب", "مطلب", "المبحث", "مبحث", "النوع", "نوع", "قسم",
}


def val_of(s: str):
    t = str(s).translate(DIG).strip()
    return int(t) if t.isdigit() else t


def detect_dialect_candidates(parts: list) -> Counter:
    c = Counter()
    for p in parts:
        fn_raw = p.get("fn_raw") if "fn_raw" in p else p.get("fn")
        if isinstance(fn_raw, dict):
            for v in fn_raw.values():
                for ln in re.split(r"[\r\n]+", str(v)):
                    ln = ln.strip()
                    if not ln:
                        continue
                    for name in ("neg", "paren", "brack", "dash", "star", "bare"):
                        if FN_HEAD[name].match(ln):
                            c[name] += 1
                            break
        elif isinstance(fn_raw, list):
            for item in fn_raw:
                ln = (item.get("text") or "").strip()
                for name in ("neg", "paren", "brack", "dash", "star", "bare"):
                    if FN_HEAD[name].match(ln):
                        c[name] += 1
                        break
    return c


def page_key(part: dict, pg) -> tuple:
    j = part.get("j")
    j_str = str(j) if j is not None else "-"
    pg_str = str(pg) if (pg is not None and str(pg) != "None") else f"none@part{part['i']}"
    return (j_str, pg_str)


def parse_fns_v4(bid: int, parts: list, dialect: str, legacy_fn_id: bool = False) -> list:
    """
    Parses raw footnote dicts across `parts` into a single ordered footnote stream,
    deduplicating shared pages by (juz, page) and merging cross-page continuation lines.
    """
    if not dialect or dialect not in FN_HEAD:
        return []
    heads = [FN_HEAD[dialect]]
    if dialect == "star":
        heads.extend([FN_HEAD["paren"], FN_HEAD["neg"]])
    elif dialect == "dash":
        heads.append(FN_HEAD["paren"])

    stream = []
    seen = set()
    for p in parts:
        fn_raw = p.get("fn_raw") if "fn_raw" in p else p.get("fn")
        if not isinstance(fn_raw, dict):
            continue
        for pg, raw in fn_raw.items():
            if not raw:
                continue
            k_pg = page_key(p, pg)
            if k_pg in seen:
                continue
            seen.add(k_pg)
            lines = [ln.strip() for ln in re.split(r"[\r\n]+", str(raw)) if ln.strip()]
            entries = []
            for ln in lines:
                m = None
                for h in heads:
                    m = h.match(ln)
                    if m:
                        break
                if m:
                    entries.append({
                        "val": val_of(m.group(1)),
                        "marker": m.group(1),
                        "text": ln,
                        "page": str(pg) if (pg is not None and str(pg) != "None") else k_pg[1],
                        "j": p.get("j"),
                        "owner_part_hint": p["i"],
                    })
                elif entries:
                    entries[-1]["text"] += " / " + ln
                elif stream:
                    stream[-1]["text"] += " / " + ln
                    stream[-1]["continued"] = True
                else:
                    entries.append({
                        "val": None,
                        "marker": "",
                        "text": ln,
                        "page": str(pg) if (pg is not None and str(pg) != "None") else k_pg[1],
                        "j": p.get("j"),
                        "owner_part_hint": p["i"],
                        "orphan_head": True,
                    })
            for seq, e in enumerate(entries, 1):
                e["seq_in_page"] = seq
                if legacy_fn_id or e["j"] is None:
                    e["fn_id"] = f"{bid}:p{e['page']}:{seq}"
                else:
                    e["fn_id"] = f"{bid}:j{e['j']}:p{e['page']}:{seq}"
                stream.append(e)
    return stream


def extract_text_tokens_v4(parts: list, dialect: str) -> list:
    toks = []
    if dialect == "neg":
        pats = [("neg", TXT_TOK["neg"])]
    elif dialect in ("dash", "paren", "star", None):
        pats = [("neg", TXT_TOK["neg"]), ("paren", TXT_TOK["paren"])]
    elif dialect == "brack":
        pats = [("brack", TXT_TOK["brack"])]
    elif dialect == "bare":
        pats = [("bare", TXT_TOK["bare"])]
    else:
        pats = [("paren", TXT_TOK["paren"])]

    part_order = {p["i"]: idx for idx, p in enumerate(parts)}
    for p in parts:
        txt = p.get("full_text") or p.get("text") or ""
        seen_spans = set()
        for kind, pat in pats:
            for m in pat.finditer(txt):
                sp = (m.start(), m.end())
                if any(s <= sp[0] and sp[1] <= e for s, e in seen_spans):
                    continue
                if kind == "paren" and FOLIO_MARKER_RE.match(txt[max(0, m.start() - 3):min(len(txt), m.end() + 2)]):
                    continue
                seen_spans.add(sp)
                toks.append({
                    "part": p["i"],
                    "start": m.start(),
                    "end": m.end(),
                    "val": val_of(m.group(1)),
                    "raw": m.group(0),
                    "kind": kind,
                    "neg": (kind == "neg") or m.group(0).startswith("(¬"),
                })
    toks.sort(key=lambda t: (part_order.get(t["part"], 0), t["start"]))
    return toks


def lcs_align(toks: list, fns: list):
    n, m = len(toks), len(fns)
    if n == 0 or m == 0:
        return []
    if n * m > 6_000_000:
        pairs = []
        toks_by_part = {}
        for idx, t in enumerate(toks):
            toks_by_part.setdefault(t["part"], []).append((idx, t))
        fns_by_part = {}
        for jdx, f in enumerate(fns):
            fns_by_part.setdefault(f.get("owner_part_hint"), []).append((jdx, f))
        for pi, p_toks in sorted(toks_by_part.items()):
            p_fns = fns_by_part.get(pi, [])
            sub_pairs = lcs_align([t for _, t in p_toks], [f for _, f in p_fns])
            for ti, fj in sub_pairs:
                pairs.append((p_toks[ti][0], p_fns[fj][0]))
        return pairs

    prev = [0] * (m + 1)
    back = []
    for i in range(1, n + 1):
        cur = [0] * (m + 1)
        tv = toks[i - 1]["val"]
        row = bytearray(m + 1)
        for j in range(1, m + 1):
            if tv is not None and tv == fns[j - 1]["val"] and prev[j - 1] + 1 >= max(prev[j], cur[j - 1]):
                cur[j] = prev[j - 1] + 1
                row[j] = 1
            elif prev[j] >= cur[j - 1]:
                cur[j] = prev[j]
                row[j] = 2
            else:
                cur[j] = cur[j - 1]
                row[j] = 3
        back.append(row)
        prev = cur

    pairs = []
    i, j = n, m
    while i > 0 and j > 0:
        d = back[i - 1][j]
        if d == 1:
            pairs.append((i - 1, j - 1))
            i -= 1
            j -= 1
        elif d == 2:
            i -= 1
        else:
            j -= 1
    return pairs[::-1]


def classify_unaligned_token(
    tok: dict,
    text: str,
    science: str = "",
    book_rules: dict = None,
    known_folios: set = None,
    fn_stripped_by_source: bool = False,
) -> str:
    book_rules = book_rules or {}
    known_folios = known_folios or set()
    if tok.get("neg"):
        if fn_stripped_by_source or book_rules.get("fn_stripped_by_source"):
            return "source_stripped_neg_marker"
        return "UNLINKED_NEG_MARKER"
    if tok.get("kind") == "bare":
        return "bare_number_in_matn"

    s, e = tok["start"], tok["end"]
    val = tok["val"]
    if val in known_folios or str(val) in known_folios:
        return "folio"
    if val in book_rules.get("acked_tokens", []) or tok["raw"] in book_rules.get("acked_tokens", []):
        return "acked"
    if book_rules.get("paren_semantics") == "rumuz":
        return "rumuz"

    # 1. Inside Quranic brackets ﴿ ... ﴾ or { ... } or immediately after Quranic text
    before = text[max(0, s - 250):s]
    after = text[e:min(len(text), e + 60)]
    last_open_q = max(before.rfind("﴿"), before.rfind("{"))
    last_close_q = max(before.rfind("﴾"), before.rfind("}"))
    if last_open_q != -1 and last_open_q > last_close_q:
        return "verse_no"
    if last_close_q != -1 and (s - (max(0, s - 250) + last_close_q)) <= 12:
        return "verse_no"
    if re.match(r"^\s*\([٠-٩0-9]+\)", after) or re.match(r"^\s*\([٠-٩0-9]+\)\s*$", before[-12:]):
        return "verse_no"
    if (
        "قوله تعالى" in before[-120:]
        or "قال تعالى" in before[-120:]
        or "سورة" in before[-80:]
        or "الآية" in before[-60:]
    ):
        return "verse_no"

    # 2. Line-initial or clause-initial list/item number
    line_start = text.rfind("\n", 0, s) + 1
    prefix_on_line = text[line_start:s].strip()
    if not prefix_on_line or re.match(r"^(?:[-–*•]|(?:\b(?:أولا|ثانيا|ثالثا|رابعا|خامسا|أ|ب|ج|د)\b))\s*:?$", prefix_on_line):
        return "list_no"
    if re.search(r"[:؛،.\-–]\s*$", before) or re.search(r"\([٠-٩0-9]+\)", text[max(0, s - 180):min(len(text), e + 180)].replace(tok["raw"], "", 1)):
        return "list_no"

    # 3. Preceded by counting/reference nouns or inside (N x M)
    prev_words = [TASHKEEL_RE.sub("", w) for w in re.findall(r"[\u0621-\u064A]+", before[-50:])]
    if any(w in COUNT_NOUNS or w.lstrip("والفب") in COUNT_NOUNS for w in prev_words[-3:]):
        return "numeric_value"
    if re.search(r"[×x/\-–]", tok["raw"]) or re.match(r"^\s*(?:هـ|م|سنة|عام|ورقة|سطر|حديث|آية)\b", after):
        return "numeric_value"

    return "numeric_value"


def link_book_footnotes_v4(
    bid: int,
    science: str,
    parts: list,
    pinned_dialect: str = None,
    book_rules: dict = None,
    known_folios_by_part: dict = None,
    legacy_fn_id: bool = False,
) -> dict:
    """
    Runs v4 dialect detection, stream construction, and monotone LCS alignment on `parts`.
    Supports sliced parts and upstream repos where footnote blocks were stripped (e.g. hdth/api/sharh).
    """
    book_rules = book_rules or {}
    known_folios_by_part = known_folios_by_part or {}
    dc = detect_dialect_candidates(parts)
    has_any_raw_fn = any(bool(p.get("fn_raw") or p.get("fn")) for p in parts)

    if not dc:
        toks = extract_text_tokens_v4(parts, "paren")
        part_texts = {p["i"]: (p.get("text") or "") for p in parts}
        tok_classes = Counter()
        unclassified_toks = []
        p0_errors = []
        fn_stripped = (not has_any_raw_fn) or bool(book_rules.get("fn_stripped_by_source"))
        for t in toks:
            tx = part_texts[t["part"]]
            if t["start"] >= len(tx):
                continue
            cls = classify_unaligned_token(
                t,
                tx,
                science,
                book_rules,
                known_folios_by_part.get(str(t["part"]), set()),
                fn_stripped_by_source=fn_stripped,
            )
            tok_classes[cls] += 1
            if cls == "UNLINKED_NEG_MARKER":
                p0_errors.append(f"Book {bid} ({science}) Part {t['part']}: Unmatched Shamela footnote marker '{t['raw']}' at char {t['start']}")
            elif cls == "UNCLASSIFIED_TOKEN":
                unclassified_toks.append(t)
        return {
            "dialect": None,
            "dialect_counts": {},
            "fn_stream": [],
            "linked_pairs": [],
            "in_window_fns_by_part": {p["i"]: [] for p in parts},
            "aligned_spans_by_part": {p["i"]: [] for p in parts},
            "unlinked_in_window": [],
            "out_of_window_fns": [],
            "continuation_count": 0,
            "token_classes": dict(tok_classes),
            "unclassified_tokens": unclassified_toks,
            "p0_errors": p0_errors,
        }

    dialects_to_try = [pinned_dialect] if pinned_dialect else list(dc.keys())
    best = None
    for d_cand in dialects_to_try:
        fns_c = parse_fns_v4(bid, parts, d_cand, legacy_fn_id=legacy_fn_id)
        toks_c = extract_text_tokens_v4(parts, d_cand)
        pairs_c = lcs_align(toks_c, fns_c)
        score = len(pairs_c) - 0.001 * (len(fns_c) - len(pairs_c))
        if best is None or score > best[0]:
            best = (score, d_cand, fns_c, toks_c, pairs_c)

    _, dialect, fns, toks, pairs = best
    matched_tok_idxs = {ti: fj for ti, fj in pairs}
    matched_fn_idxs = {fj: ti for ti, fj in pairs}

    slice_limits = {}
    part_texts = {}
    for p in parts:
        tx = p.get("text") or ""
        part_texts[p["i"]] = tx
        slice_limits[p["i"]] = p.get("slice_end", len(tx))

    max_in_win_fn_idx_per_part = {}
    for ti, fj in pairs:
        tok = toks[ti]
        pi = tok["part"]
        if tok["start"] < slice_limits[pi]:
            max_in_win_fn_idx_per_part[pi] = max(max_in_win_fn_idx_per_part.get(pi, -1), fj)

    sliced_part_ids = {p["i"] for p in parts if p.get("is_sliced") or ("full_text" in p and len(p["full_text"]) > len(p["text"]))}

    in_window_fns_by_part = {p["i"]: [] for p in parts}
    aligned_spans_by_part = {p["i"]: [] for p in parts}
    unlinked_in_window = []
    out_of_window_fns = []

    acked_orphan_fns = set(book_rules.get("acked_orphan_fns", []))

    for fj, fn_entry in enumerate(fns):
        if fj in matched_fn_idxs:
            ti = matched_fn_idxs[fj]
            tok = toks[ti]
            pi = tok["part"]
            if tok["start"] < slice_limits[pi]:
                fn_copy = dict(fn_entry)
                fn_copy["link_status"] = "linked"
                fn_copy["linked_part"] = pi
                fn_copy["linked_char_start"] = tok["start"]
                fn_copy["linked_char_end"] = tok["end"]
                fn_copy["linked_raw_token"] = tok["raw"]
                in_window_fns_by_part[pi].append(fn_copy)
                aligned_spans_by_part[pi].append((tok["start"], tok["end"], fn_copy["fn_id"], fn_copy["page"]))
            else:
                fn_copy = dict(fn_entry)
                fn_copy["link_status"] = "out_of_window"
                out_of_window_fns.append(fn_copy)
        else:
            owner_pi = fn_entry.get("owner_part_hint")
            if owner_pi in sliced_part_ids and fj > max_in_win_fn_idx_per_part.get(owner_pi, -1):
                fn_copy = dict(fn_entry)
                fn_copy["link_status"] = "out_of_window"
                out_of_window_fns.append(fn_copy)
            elif fn_entry["fn_id"] in acked_orphan_fns or fn_entry.get("orphan_head") or book_rules.get("ack_all_orphan_fns"):
                fn_copy = dict(fn_entry)
                fn_copy["link_status"] = "orphan_note_acked"
                in_window_fns_by_part.setdefault(owner_pi, []).append(fn_copy)
            else:
                fn_copy = dict(fn_entry)
                fn_copy["link_status"] = "unlinked"
                unlinked_in_window.append(fn_copy)

    tok_classes = Counter()
    unclassified_toks = []
    p0_errors = []
    for ti, tok in enumerate(toks):
        pi = tok["part"]
        if tok["start"] >= slice_limits[pi]:
            continue
        if ti in matched_tok_idxs:
            tok_classes["fn_marker"] += 1
            continue
        tx = part_texts[pi]
        cls = classify_unaligned_token(
            tok, tx, science, book_rules, known_folios_by_part.get(str(pi), set())
        )
        tok_classes[cls] += 1
        if cls == "UNLINKED_NEG_MARKER":
            p0_errors.append(
                f"Book {bid} ({science}) Part {pi}: Unmatched Shamela footnote marker '{tok['raw']}' at char {tok['start']}"
            )
        elif cls == "UNCLASSIFIED_TOKEN":
            unclassified_toks.append(tok)

    return {
        "dialect": dialect,
        "dialect_counts": dict(dc),
        "fn_stream": fns,
        "linked_pairs": pairs,
        "in_window_fns_by_part": in_window_fns_by_part,
        "aligned_spans_by_part": aligned_spans_by_part,
        "unlinked_in_window": unlinked_in_window,
        "out_of_window_fns": out_of_window_fns,
        "continuation_count": sum(1 for f in fns if f.get("continued")),
        "token_classes": dict(tok_classes),
        "unclassified_tokens": unclassified_toks,
        "p0_errors": p0_errors,
    }
