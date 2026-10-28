#!/usr/bin/env python3
"""
discover_person.py — Brick 1: Clean, Zero-Hardcoded Live Person Discovery Engine.
Discovers YouTube videos/channels (via yt-dlp) and Archive.org audio/video/book items
starting strictly from a person's name (`--name`) and era (`--era`).
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import unicodedata
from typing import Any
import urllib.parse
import urllib.request

BIDI_AND_INVISIBLE_RE = re.compile(r"[\u200e\u200f\u061c\ufeff\u202a-\u202e\u2066-\u2069]")
HARAKAT_RE = re.compile(r"[\u064B-\u065F\u0670\u0640]")
AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
HONORIFICS = {
    "الشيخ", "شيخ", "الدكتور", "دكتور", "الاستاذ", "استاذ", "العلامه", "علامه",
    "المحدث", "محدث", "الامام", "امام", "فضيله", "سماحه", "المهندس", "الحبيب", "د", "أ",
}
MEDIA_PRIORITY = {".mp4": 1, ".mp3": 2, ".m4a": 3, ".opus": 4, ".flac": 5, ".wav": 6, ".ogg": 7, ".avi": 8}


def clean_text(text: str | None) -> str:
    """Normalize text with NFC and strip hidden directional characters."""
    if not text:
        return ""
    cleaned = BIDI_AND_INVISIBLE_RE.sub("", str(text))
    cleaned = unicodedata.normalize("NFC", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def normalize_ar(text: str | None) -> str:
    """Normalize Arabic text for deterministic token comparison."""
    s = clean_text(text).translate(AR_DIGITS)
    s = HARAKAT_RE.sub("", s)
    s = re.sub(r"[أإآٱ]", "ا", s)
    s = s.replace("ى", "ي").replace("ؤ", "و").replace("ئ", "ي").replace("ة", "ه")
    return re.sub(r"\s+", " ", s).strip()


def extract_core_name_tokens(name: str) -> list[str]:
    """Extract core given and family/nisba tokens after stripping honorifics."""
    tokens = [t for t in re.split(r"[^\w\u0600-\u06FF]+", normalize_ar(name)) if t]
    while len(tokens) > 1 and tokens[0] in HONORIFICS:
        tokens.pop(0)
    return [t for t in tokens if t not in ("بن", "ابن")]


def matches_compound_person_name(text: str, core_tokens: list[str], era: str = "contemporary") -> bool:
    """
    Guard against partial first-name collisions, father/son name inversions,
    and conflicting kunyas/given names sharing the same nisba.
    """
    if not text or not core_tokens:
        return False
    norm = normalize_ar(text)
    words = [w for w in re.split(r"[^\w\u0600-\u06FF]+", norm) if w]
    if not words:
        return False
    if len(core_tokens) == 1:
        return core_tokens[0] in words

    first_tok, last_tok = core_tokens[0], core_tokens[-1]
    if first_tok not in words or last_tok not in words:
        return False

    for i, w in enumerate(words):
        if w != first_tok:
            continue
        # Reject if preceded by 'ابو'/'ابي' (e.g. 'أبو صالح الشامي') or another personal name (e.g. 'أحمد صالح الشامي')
        if i > 0 and words[i - 1] in ("ابو", "ابي", "احمد", "محمد", "زيد", "عبد", "عبدالرقيب"):
            continue
        # Allow direct adjacency ('صالح الشامي') or 1-2 patronymic tokens ('صالح أحمد الشامي', 'صالح بن أحمد الشامي')
        window = words[i + 1 : i + 5]
        if last_tok in window:
            rel_idx = window.index(last_tok)
            middle = window[:rel_idx]
            if all(m not in ("حيدر", "ابو", "بدر") for m in middle):
                if era == "contemporary" and any(k in norm for k in ("جنازه الشيخ", "المرحوم", "الفن اليافعي")):
                    return False
                return True
    return False


def classify_content_role(title: str, channel: str, core_tokens: list[str]) -> str:
    """Distinguish direct appearances/majalis of the person from audiobooks or third-party explanations."""
    norm_t = normalize_ar(title)
    norm_c = normalize_ar(channel)
    combined = f"{norm_t} {norm_c}"
    if any(k in combined for k in ("بصوت", "كتاب صوتي", "الكتاب الصوتي", "مسموع", "قراءه صوتيه")):
        return "audiobook_of_person_work"
    if any(k in norm_t for k in ("علي مصنفه", "علي مؤلفه", "علي جامعه", "بحضور مؤلف", "مع صالح", "غرفه الشيخ")):
        return "direct_appearance_or_sama"
    if any(k in norm_t for k in ("شرح كتاب", "شرح معالم", "شرح زوائد", "مع الشيخ", "تقديم الشيخ")):
        return "third_party_explanation_of_work"
    if matches_compound_person_name(channel, core_tokens, era="any"):
        return "person_channel_upload"
    return "related_or_biographical"


def discover_youtube(name: str, core_tokens: list[str], era: str, extra_urls: list[str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Run live yt-dlp discovery from `--name` and optional `--youtube-urls`."""
    queries = [f"ytsearch25:{name}"] + list(extra_urls or [])
    channels_map: dict[str, dict[str, Any]] = {}
    playlists_map: dict[str, dict[str, Any]] = {}
    videos_map: dict[str, dict[str, Any]] = {}

    for q in queries:
        cmd = ["yt-dlp", "--flat-playlist", "--dump-json", q]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        except Exception as exc:
            sys.stderr.write(f"[WARN] yt-dlp failed on {q}: {exc}\n")
            continue
        if proc.returncode != 0 or not proc.stdout.strip():
            continue

        for line in proc.stdout.splitlines():
            if not line.strip():
                continue
            try:
                ent = json.loads(line)
            except ValueError:
                continue
            vid = clean_text(ent.get("id"))
            title = clean_text(ent.get("title"))
            channel = clean_text(ent.get("channel") or ent.get("uploader"))
            channel_id = clean_text(ent.get("channel_id") or ent.get("uploader_id"))
            pl_id = clean_text(ent.get("playlist_id"))
            pl_title = clean_text(ent.get("playlist_title") or ent.get("playlist"))
            if not vid or not title or title in ("[Deleted video]", "[Private video]"):
                continue

            context_str = f"{title} {channel} {pl_title}"
            if not matches_compound_person_name(context_str, core_tokens, era=era):
                continue

            dur_raw = ent.get("duration")
            dur_s = int(round(float(dur_raw))) if isinstance(dur_raw, (int, float)) else 0
            role = classify_content_role(title, channel, core_tokens)
            url = clean_text(ent.get("url") or ent.get("webpage_url")) or f"https://www.youtube.com/watch?v={vid}"

            if channel_id and channel_id not in channels_map:
                channels_map[channel_id] = {
                    "channel_id": channel_id,
                    "title": channel or channel_id,
                    "url": f"https://www.youtube.com/channel/{channel_id}",
                }
            if pl_id and pl_id.startswith("PL") and pl_id not in playlists_map:
                playlists_map[pl_id] = {
                    "playlist_id": pl_id,
                    "title": pl_title or pl_id,
                    "url": f"https://www.youtube.com/playlist?list={pl_id}",
                }
            if vid not in videos_map:
                videos_map[vid] = {
                    "vid": vid,
                    "title": title,
                    "dur_s": dur_s,
                    "channel_id": channel_id or None,
                    "channel_title": channel or None,
                    "playlist_id": pl_id if pl_id.startswith("PL") else None,
                    "content_role": role,
                    "url": url,
                }

    return list(channels_map.values()), list(playlists_map.values()), list(videos_map.values())


def _fetch_archive_item_detail(item_id: str, core_tokens: list[str], era: str) -> dict[str, Any] | None:
    """Fetch `/metadata/{item_id}` and separate modern media files from PDF/text books."""
    url = f"https://archive.org/metadata/{urllib.parse.quote(item_id)}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (PersonDiscoveryBrick1/2.0)"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            payload = json.loads(resp.read().decode("utf-8", errors="ignore"))
    except Exception:
        return None

    meta = payload.get("metadata") or {}
    title = clean_text(meta.get("title") or item_id)
    creator_raw = meta.get("creator")
    creator = clean_text(", ".join(creator_raw) if isinstance(creator_raw, list) else str(creator_raw or ""))
    mediatype = clean_text(meta.get("mediatype") or "").lower()

    if not matches_compound_person_name(f"{title} {creator}", core_tokens, era=era):
        return None

    raw_files = payload.get("files") or []
    by_stem: dict[str, list[tuple[int, dict[str, Any]]]] = {}
    pdf_files: list[str] = []

    for f in raw_files:
        fname = clean_text(f.get("name"))
        if not fname or fname.startswith("__") or fname.startswith("_HOUR_"):
            continue
        ext = os.path.splitext(fname)[1].lower()
        if ext == ".pdf":
            pdf_files.append(f"https://archive.org/download/{item_id}/{urllib.parse.quote(fname)}")
        elif ext in MEDIA_PRIORITY:
            stem = os.path.splitext(fname)[0]
            # Prefer modern formats (.mp4, .mp3, .m4a, .opus) over legacy .avi/.ogg regardless of derivative flag
            by_stem.setdefault(stem, []).append((MEDIA_PRIORITY[ext], f))

    media_tracks: list[dict[str, Any]] = []
    for stem, cands in sorted(by_stem.items()):
        best_f = sorted(cands, key=lambda x: x[0])[0][1]
        fname = clean_text(best_f["name"])
        len_raw = best_f.get("length")
        dur_s = 0
        if len_raw is not None:
            try:
                dur_s = int(round(float(len_raw)))
            except ValueError:
                pass
        media_tracks.append({
            "name": fname,
            "title": clean_text(best_f.get("title")) or os.path.basename(stem),
            "ext": os.path.splitext(fname)[1].lower(),
            "dur_s": dur_s,
            "direct_url": f"https://archive.org/download/{item_id}/{urllib.parse.quote(fname)}",
        })

    return {
        "item_id": item_id,
        "title": title,
        "creator": creator,
        "mediatype": mediatype,
        "details_url": f"https://archive.org/details/{item_id}",
        "media_tracks": media_tracks,
        "pdf_urls": pdf_files,
        "content_role": classify_content_role(title, creator, core_tokens),
    }


def discover_archive(name: str, core_tokens: list[str], era: str, extra_queries: list[str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Query Archive.org AdvancedSearch and inspect item metadata."""
    queries = [name] + [q for q in (extra_queries or []) if q != name]
    candidate_ids: list[str] = []
    seen_ids: set[str] = set()

    for q_name in queries:
        q_expr = f'creator:("{q_name}") OR title:("{q_name}")'
        params = urllib.parse.urlencode({
            "q": q_expr,
            "fl[]": ["identifier", "title", "creator", "mediatype"],
            "rows": "60",
            "page": "1",
            "output": "json",
        }, doseq=True)
        url = f"https://archive.org/advancedsearch.php?{params}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (PersonDiscoveryBrick1/2.0)"})
            with urllib.request.urlopen(req, timeout=20) as resp:
                docs = json.loads(resp.read().decode("utf-8", errors="ignore")).get("response", {}).get("docs", [])
        except Exception as exc:
            sys.stderr.write(f"[WARN] Archive.org search failed for {q_name}: {exc}\n")
            continue

        for d in docs:
            ident = clean_text(d.get("identifier"))
            t_str = clean_text(d.get("title"))
            c_raw = d.get("creator")
            c_str = clean_text(", ".join(c_raw) if isinstance(c_raw, list) else str(c_raw or ""))
            if ident and ident not in seen_ids and matches_compound_person_name(f"{t_str} {c_str}", core_tokens, era=era):
                seen_ids.add(ident)
                candidate_ids.append(ident)

    media_items: list[dict[str, Any]] = []
    books: list[dict[str, Any]] = []
    seen_book_titles: set[str] = set()

    with ThreadPoolExecutor(max_workers=6) as ex:
        futures = {ex.submit(_fetch_archive_item_detail, iid, core_tokens, era): iid for iid in candidate_ids[:40]}
        for fut in as_completed(futures):
            detail = fut.result()
            if not detail:
                continue
            if detail["media_tracks"] and detail["mediatype"] in ("audio", "movies", "video"):
                media_items.append(detail)
            elif detail["mediatype"] == "texts" or detail["pdf_urls"]:
                # Preserve full book title without truncating on prepositions ('في', 'على')
                clean_btitle = re.sub(r"^(?:\d+[\s\-_]+|كتاب\s+\d+\s+Pdf\s+)", "", detail["title"], flags=re.I).strip()
                norm_bt = normalize_ar(clean_btitle)
                if norm_bt and len(norm_bt) >= 5 and norm_bt not in seen_book_titles:
                    seen_book_titles.add(norm_bt)
                    books.append({
                        "item_id": detail["item_id"],
                        "title": clean_btitle,
                        "creator": detail["creator"] or name,
                        "details_url": detail["details_url"],
                        "pdf_urls": detail["pdf_urls"],
                    })

    return media_items, books


def main() -> None:
    ap = argparse.ArgumentParser(description="Brick 1: Live Person Discovery Engine (YouTube + Archive.org).")
    ap.add_argument("--name", required=True, help="Scholar/person Arabic name")
    ap.add_argument("--era", choices=["contemporary", "classical", "any"], default="contemporary")
    ap.add_argument("--youtube-urls", nargs="*", default=[], help="Optional extra YouTube URLs")
    ap.add_argument("--archive-queries", nargs="*", default=[], help="Optional extra Archive.org queries")
    ap.add_argument("--output", "-o", required=True, help="Output JSON file path")
    args = ap.parse_args()

    name = clean_text(args.name)
    core_tokens = extract_core_name_tokens(name)
    channels, playlists, videos = discover_youtube(name, core_tokens, args.era, args.youtube_urls)
    archive_media, books = discover_archive(name, core_tokens, args.era, args.archive_queries)

    yt_direct = sum(1 for v in videos if v["content_role"] == "direct_appearance_or_sama")
    yt_audiobooks = sum(1 for v in videos if v["content_role"] == "audiobook_of_person_work")
    yt_third_party = sum(1 for v in videos if v["content_role"] == "third_party_explanation_of_work")
    arch_tracks = sum(len(m["media_tracks"]) for m in archive_media)
    total_dur_s = sum(v["dur_s"] for v in videos) + sum(t["dur_s"] for m in archive_media for t in m["media_tracks"])

    payload = {
        "person_name": name,
        "era": args.era,
        "core_name_tokens": core_tokens,
        "discovered_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "channels": channels,
        "playlists": playlists,
        "videos": videos,
        "archive_media_items": archive_media,
        "books": books,
        "stats": {
            "channels_count": len(channels),
            "playlists_count": len(playlists),
            "youtube_videos_count": len(videos),
            "youtube_direct_appearances_count": yt_direct,
            "youtube_audiobooks_count": yt_audiobooks,
            "youtube_third_party_explanations_count": yt_third_party,
            "archive_media_items_count": len(archive_media),
            "archive_media_tracks_count": arch_tracks,
            "books_count": len(books),
            "total_duration_s": total_dur_s,
            "total_duration_hours": round(total_dur_s / 3600.0, 2),
        },
    }

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] Brick 1 discovery saved to {out_path}: {json.dumps(payload['stats'], ensure_ascii=False)}")


if __name__ == "__main__":
    main()
