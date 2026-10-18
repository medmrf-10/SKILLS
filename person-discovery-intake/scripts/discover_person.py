#!/usr/bin/env python3
"""
discover_person.py — Exhaustive Multi-Source Person Discovery & Intake Engine.

Discovers, harvests, deduplicates, and unifies all digital heritage of a scholar/person
starting from their name (and optional seed URLs / PDFs / Archive.org IDs / offline fixtures):
1. YouTube: Official & archival channels, Playlists, Uploads (UU...), Livestreams (Streams),
   and Unlisted Playlists extracted from index PDFs.
2. PDF Index Decompression: Decompresses PDF FlateDecode streams via `zlib.decompress`
   and parses `/URI` annotations to recover hidden playlist/video/Archive.org/shortlink URLs.
3. Archive.org: Queries AdvancedSearch & Metadata API (`archive.org/metadata/<item_id>`),
   deduplicates derivative audio files (.mp3 preferred over .ogg), extracts exact durations
   (`dur_s`) and direct download URLs (`direct_url`).
4. Books & Matn Matching: Discovers authored books and matches audio/video series to
   classical Islamic matns with strict science separation and Arabic word-boundary checks.
5. Canonical Export: Outputs `<person_id>_raw.json` 100% compatible with `sheikh-curation`
   (`deep_scanner_all.py`, `hijri_interpolator.py`, `curated_tools.py`).
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import gzip
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import urllib.parse
import urllib.request
import zlib
from typing import Any

# ---------------------------------------------------------------------------
# 1. Arabic Normalization & Person ID Transliteration
# ---------------------------------------------------------------------------

AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
HARAKAT_RE = re.compile(r"[\u064B-\u065F\u0670\u0640]")

KNOWN_PERSON_SLUGS: dict[str, str] = {
    "مولود السريري": "sariri",
    "محمد البردوني": "bardoni",
    "محمد البردوني الحسيمي": "bardoni",
    "علي هاني": "alihani",
    "علي هاني العقرباوي": "alihani",
    "محمد متولي الشعراوي": "shaarawy",
    "الشعراوي": "shaarawy",
    "محمد سعيد رمضان البوطي": "bouti",
    "محمد سعيد البوطي": "bouti",
    "البوطي": "bouti",
    "فاضل السامرائي": "samarrai",
    "فاضل صالح السامرائي": "samarrai",
    "الحبيب علي الجفري": "jifri",
    "علي الجفري": "jifri",
    "الحبيب عمر بن حفيظ": "hafiz",
    "عمر بن حفيظ": "hafiz",
    "علي محمود العمري": "omari",
    "علي العمري": "omari",
    "أدهم العاسمي": "asimi",
    "معاذ سعيد حوى": "hawwa",
    "معاذ سعيد حوا": "hawwa",
    "سعيد الكملي": "kamali",
    "محمد الحسن الددو": "dedew",
    "محمد الحسن الددو الشنقيطي": "dedew",
    "علي جمعة": "gomaa",
    "عبد الرحمن ذاكر الهاشمي": "hashemi",
    "ذاكر الهاشمي": "hashemi",
    "أحمد السيد": "sayed",
    "أيمن عبد الرحيم": "ayman",
    "المهندس أيمن عبد الرحيم": "ayman",
    "سعيد فودة": "fouda",
    "عبد العزيز بن سايب": "ibnsayeb",
    "مصطفى البحياوي": "bahyaoui",
    "محمد سيد سلطان": "sultan",
    "أحمد طه ريان": "rayyan",
    "محمد نعيم عرقسوسي": "arqsousi",
    "عبد الفتاح أبو غدة": "abughuddah",
    "نور الدين عتر": "itr",
    "محمد محمد أبو موسى": "abumusa",
    "وهبة الزحيلي": "zuhayli",
    "محمد الطاهر بن عاشور": "ibnashur",
    "ابن عاشور": "ibnashur",
    "جلال الدين السيوطي": "suyuti",
    "أبو إسحاق الشاطبي": "shatibi",
    "أبو حامد الغزالي": "ghazali",
    "يحيى بن شرف النووي": "nawawi",
}

SHEIKH_PHOTOS: dict[str, str] = {
    "sayed": "https://medmrf-10.github.io/hawshat/playlists/img/ahmed-alsayed.jpg",
    "asimi": "https://medmrf-10.github.io/hawshat/playlists/img/adham-alasimi.jpg",
    "bardoni": "https://medmrf-10.github.io/hawshat/playlists/img/bardouni-husaymi.jpg",
    "jifri": "https://medmrf-10.github.io/hawshat/playlists/img/habib-ali-aljifri.jpg",
    "hafiz": "https://medmrf-10.github.io/hawshat/playlists/img/habib-omar-ibn-hafiz.jpg",
    "gomaa": "https://medmrf-10.github.io/hawshat/playlists/img/ali-gomaa.jpg",
    "bouti": "https://medmrf-10.github.io/hawshat/playlists/img/said-bouti.jpg",
    "shaarawy": "https://medmrf-10.github.io/hawshat/playlists/img/sharawi.jpg",
    "hawwa": "https://medmrf-10.github.io/hawshat/playlists/img/maath-hawa.jpg",
    "sariri": "https://medmrf-10.github.io/hawshat/playlists/img/mouloud-sariri.jpg",
    "omari": "https://medmrf-10.github.io/hawshat/playlists/img/ali-mahmoud-alomari.jpg",
    "hashemi": "https://medmrf-10.github.io/hawshat/playlists/img/dhaker-alhashimi.jpg",
    "kamali": "https://medmrf-10.github.io/hawshat/playlists/img/said-kamali.jpg",
    "samarrai": "https://medmrf-10.github.io/hawshat/playlists/img/fadhel-samarrai.jpg",
    "ayman": "https://medmrf-10.github.io/hawshat/playlists/img/ayman-abdelrahim.jpg",
    "dedew": "https://medmrf-10.github.io/hawshat/playlists/img/daddo.jpg",
    "alihani": "https://yt3.googleusercontent.com/dNA40wR5QtnNoK1ilEriqsLa16RdGAXBgN-dXxDQzF0CxP5ET9itcRC4gjPRPL99kuHFsO4ApA=s900-c-k-c0x00ffffff-no-rj",
    "khudayr": "https://upload.wikimedia.org/wikipedia/commons/e/e0/%D8%B9%D8%A8%D8%AF_%D8%A7%D9%84%D9%83%D8%B1%D9%8A%D9%85_%D8%A7%D9%84%D8%AE%D8%B6%D9%8A%D8%B1.jpg",
    "fawzan": "https://upload.wikimedia.org/wikipedia/commons/8/8c/Saleh_Al-Fawzan.png",
    "shanqiti": "https://upload.wikimedia.org/wikipedia/commons/a/a2/%D9%85%D8%AD%D9%85%D8%AF_%D8%A7%D9%84%D8%AD%D8%B3%D9%86_%D8%A7%D9%84%D8%AF%D8%AF%D9%88.jpg",
}

AR_TO_LATIN_MAP: dict[str, str] = {
    "ا": "a", "أ": "a", "إ": "i", "آ": "a", "ٱ": "a",
    "ب": "b", "ت": "t", "ث": "th", "ج": "j", "ح": "h",
    "خ": "kh", "د": "d", "ذ": "dh", "ر": "r", "ز": "z",
    "س": "s", "ش": "sh", "ص": "s", "ض": "d", "ط": "t",
    "ظ": "z", "ع": "a", "غ": "gh", "ف": "f", "ق": "q",
    "ك": "k", "ل": "l", "م": "m", "ن": "n", "ه": "h",
    "ة": "a", "و": "w", "ؤ": "u", "ي": "y", "ى": "a",
    "ئ": "i", "ء": "",
}


def normalize_arabic(text: str) -> str:
    """Normalize Arabic string for deterministic matching (strip diacritics, unify hamzas/digits)."""
    if not text:
        return ""
    s = str(text).translate(AR_DIGITS)
    s = HARAKAT_RE.sub("", s)
    s = re.sub(r"[أإآٱ]", "ا", s)
    s = s.replace("ى", "ي").replace("ئ", "ي").replace("ؤ", "و").replace("ة", "ه")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def normalize_person_id(name: str, explicit_id: str | None = None) -> str:
    """Generate or normalize a canonical ASCII slug `person_id` from a person's name."""
    if explicit_id and str(explicit_id).strip():
        slug = re.sub(r"[^a-z0-9_]+", "_", str(explicit_id).strip().lower()).strip("_")
        if slug:
            return slug

    norm_name = normalize_arabic(name)
    # Remove common honorific prefixes
    cleaned = re.sub(
        r"^(?:الشيخ|العلامه|الامام|الدكتور|الاستاذ|المهندس|الحبيب|السيد|فضيله|أ\.?د\.?|د\.?|م\.?)\s+",
        "",
        norm_name,
    ).strip()

    for k, v in KNOWN_PERSON_SLUGS.items():
        nk = normalize_arabic(k)
        if nk == norm_name or nk == cleaned or (nk in norm_name and len(nk) >= 7):
            return v

    # Fallback deterministic transliteration of last significant word or full name
    ascii_chars = []
    for ch in cleaned.lower():
        if ch in AR_TO_LATIN_MAP:
            ascii_chars.append(AR_TO_LATIN_MAP[ch])
        elif "a" <= ch <= "z" or "0" <= ch <= "9":
            ascii_chars.append(ch)
        elif ch in (" ", "-", "_"):
            ascii_chars.append("_")
    slug = re.sub(r"_+", "_", "".join(ascii_chars)).strip("_")
    return slug or "person_unknown"


def extract_short_name(sheikh_name: str) -> str:
    """Derive a clean short name from the scholar's full name."""
    parts = [p for p in re.split(r"\s+", (sheikh_name or "").strip()) if p]
    if not parts:
        return ""
    if len(parts) >= 2 and parts[-2] in ("بن", "أبو", "أبي", "آل", "عبد"):
        return f"{parts[-2]} {parts[-1]}"
    return parts[-1]


# ---------------------------------------------------------------------------
# 2. PDF FlateDecode Stream Decompression & Link Extraction Engine
# ---------------------------------------------------------------------------

STREAM_BLOCK_RE = re.compile(rb"stream(?:\r\n|\n|\r)(.*?)(?:\r\n|\n|\r)?endstream", re.DOTALL)
PDF_URI_PAREN_RE = re.compile(rb"/URI\s*\(([^)]+)\)")
PDF_URI_HEX_RE = re.compile(rb"/URI\s*<([0-9A-Fa-f\s]+)>")
RAW_URL_RE = re.compile(
    r"https?://[A-Za-z0-9\-._~:/?#\[\]@!$&'*+,;=%]+",
    re.IGNORECASE,
)
SHORTLINK_NO_SCHEME_RE = re.compile(
    r"(?<!://)(?<!\.)\b(?:bit\.ly|goo\.gl|tinyurl\.com|t\.co|youtu\.be)/[A-Za-z0-9_\-]+",
    re.IGNORECASE,
)
BARE_PLAYLIST_ID_RE = re.compile(r"\b(PL[A-Za-z0-9_\-]{16,34})\b")

# Filter out embedded TrueType font licenses, PKI certificates, and XMP schema URIs inside PDFs
PDF_NOISE_URL_RE = re.compile(
    r"(?:"
    r"microsoft\.com/(?:pki|typography)"
    r"|crl\.microsoft\.com"
    r"|linotype\.com"
    r"|lucasfonts\.com"
    r"|wikipedia\.org/wiki/MIT_License"
    r"|scripts\.sil\.org/OFL"
    r"|w3\.org/[0-9]{4}/"
    r"|purl\.org/dc/"
    r"|ns\.adobe\.com/"
    r"|iptc\.org/std/"
    r"|^https?://(?:bit|bit\.ly|goo\.gl|tinyurl\.com|t\.co)/?$"
    r")",
    re.IGNORECASE,
)


def _unescape_pdf_string(raw_bytes: bytes) -> str:
    """Unescape PDF literal string escapes such as \\(, \\), \\\\ and octal \\ddd."""
    s = raw_bytes.decode("latin-1", errors="ignore")
    s = s.replace(r"\(", "(").replace(r"\)", ")").replace(r"\\", "\\")
    return s.strip()


def unwrap_redirect_wrapper_url(url: str) -> str:
    """
    Unwrap Google Docs/Sheets (`https://www.google.com/url?q=...`), YouTube (`youtube.com/redirect?q=...`),
    or Facebook (`l.facebook.com/l.php?u=...`) redirect wrapper URLs into their actual target URL.
    """
    s = (url or "").strip()
    if not s:
        return s
    try:
        parsed = urllib.parse.urlsplit(s)
        host = (parsed.netloc or "").lower()
        path = parsed.path or ""
        if (
            ("google." in host and path == "/url")
            or ("youtube.com" in host and path == "/redirect")
            or ("facebook.com" in host and path == "/l.php")
        ):
            qs = urllib.parse.parse_qs(parsed.query)
            for key in ("q", "url", "u"):
                vals = qs.get(key)
                if vals and vals[0]:
                    return urllib.parse.unquote(vals[0]).strip()
    except Exception:
        pass
    return s


def resolve_http_redirect(url: str, timeout: int = 8) -> str:
    """Follow HTTP 301/302 redirects (e.g., bit.ly -> youtube.com/playlist?list=...)."""
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
            },
            method="HEAD",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.geturl() or url
    except Exception:
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
                },
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.geturl() or url
        except Exception:
            return url


def classify_extracted_url(url: str, resolved_url: str | None = None) -> dict[str, Any]:
    """Classify a discovered URL into playlist, video, archive_item, shortlink, or other."""
    clean_orig = url.strip().rstrip(".,;)]}>'\"")
    target = unwrap_redirect_wrapper_url(resolved_url or clean_orig).strip().rstrip(".,;)]}>'\"")
    playlist_id = None
    video_id = None
    archive_id = None
    link_type = "other"

    # Extract both playlist_id and video_id if present (e.g., watch?v=VID&list=PL_ID)
    m_pl = re.search(r"(?:[?&]|%3[Ff]|%26)list(?:=|%3[Dd])((?:PL|UU|OLAK5uy_)[A-Za-z0-9_\-]+)", target)
    if m_pl:
        playlist_id = m_pl.group(1)

    m_vid = re.search(
        r"(?:youtube\.com/(?:watch\?.*?v=|live/|shorts/|embed/)|youtu\.be/)([A-Za-z0-9_\-]{11})",
        target,
    )
    if m_vid:
        video_id = m_vid.group(1)

    if playlist_id:
        link_type = "youtube_playlist"
    elif video_id:
        link_type = "youtube_video"
    else:
        m_arch = re.search(
            r"archive\.org/(?:details|download|metadata)/([A-Za-z0-9_.\-]+)",
            target,
        )
        if m_arch:
            archive_id = m_arch.group(1)
            link_type = "archive_item"
        elif re.search(r"^https?://(?:bit\.ly|goo\.gl|tinyurl\.com|t\.co)/[A-Za-z0-9_\-]+", target, re.I):
            link_type = "shortlink"

    return {
        "url": clean_orig,
        "resolved_url": target,
        "link_type": link_type,
        "playlist_id": playlist_id,
        "video_id": video_id,
        "archive_id": archive_id,
    }


def extract_links_from_pdf(
    pdf_path: str | Path,
    resolve_redirects: bool = False,
) -> list[dict[str, Any]]:
    """
    Extract all embedded links (YouTube playlists, unlisted playlists, videos, Archive.org items,
    and shortlinks) from a PDF file by scanning both uncompressed `/URI` annotations and
    `zlib.decompress`-ed `FlateDecode` streams.
    """
    path = Path(pdf_path)
    if not path.exists():
        raise FileNotFoundError(f"PDF file not found: {path}")

    raw_bytes = path.read_bytes()
    pdf_name = path.name
    candidates: list[tuple[str, str]] = []  # (url_str, extraction_method)

    # Layer 1: Uncompressed /URI (...) and /URI <HEX>
    for m in PDF_URI_PAREN_RE.finditer(raw_bytes):
        u = _unescape_pdf_string(m.group(1))
        if u:
            candidates.append((u, "PDF_URI_Annot"))

    for m in PDF_URI_HEX_RE.finditer(raw_bytes):
        hex_str = re.sub(rb"\s+", b"", m.group(1)).decode("ascii", errors="ignore")
        if len(hex_str) % 2 == 1:
            hex_str += "0"
        try:
            u = bytes.fromhex(hex_str).decode("utf-8", errors="ignore").strip()
            if u:
                candidates.append((u, "PDF_URI_Hex_Annot"))
        except ValueError:
            pass

    # Layer 2: Decompress all `stream ... endstream` blocks with zlib (FlateDecode)
    for m in STREAM_BLOCK_RE.finditer(raw_bytes):
        stream_data = m.group(1)
        decompressed: bytes | None = None
        for wbits in (15, -15, 31):
            try:
                decompressed = zlib.decompress(stream_data, wbits)
                break
            except Exception:
                continue
        if decompressed is None:
            # Try stripping leading/trailing whitespace inside stream
            stripped = stream_data.strip(b"\r\n ")
            for wbits in (15, -15):
                try:
                    decompressed = zlib.decompress(stripped, wbits)
                    break
                except Exception:
                    continue

        if decompressed is not None:
            method = "FlateDecode_stream"
            payloads = [decompressed]
        else:
            method = "Plain_stream"
            payloads = [stream_data]

        for buf in payloads:
            for um in PDF_URI_PAREN_RE.finditer(buf):
                u = _unescape_pdf_string(um.group(1))
                if u:
                    candidates.append((u, method))

            text_latin = buf.decode("latin-1", errors="ignore")
            text_utf8 = buf.decode("utf-8", errors="ignore")
            for text in (text_utf8, text_latin):
                for rm in RAW_URL_RE.finditer(text):
                    candidates.append((rm.group(0), method))
                for sm in SHORTLINK_NO_SCHEME_RE.finditer(text):
                    short_u = sm.group(0)
                    if not short_u.lower().startswith("http"):
                        short_u = "https://" + short_u
                    candidates.append((short_u, method))
                for pm in BARE_PLAYLIST_ID_RE.finditer(text):
                    pl_id = pm.group(1)
                    candidates.append(
                        (f"https://www.youtube.com/playlist?list={pl_id}", method)
                    )

    # Deduplicate and classify
    results: list[dict[str, Any]] = []
    seen_keys: set[str] = set()

    for raw_u, method in candidates:
        clean_u = raw_u.strip().rstrip(".,;)]}>'\"\\")
        if not clean_u or len(clean_u) < 8:
            continue
        if PDF_NOISE_URL_RE.search(clean_u):
            continue
        resolved = unwrap_redirect_wrapper_url(clean_u)
        if PDF_NOISE_URL_RE.search(resolved):
            continue
        if resolve_redirects and re.search(
            r"^https?://(?:bit\.ly|goo\.gl|tinyurl\.com|t\.co)/[A-Za-z0-9_\-]+", resolved, re.I
        ):
            resolved = resolve_http_redirect(resolved)

        info = classify_extracted_url(clean_u, resolved)
        if info["playlist_id"]:
            dedup_key = f"pl:{info['playlist_id']}"
        elif info["video_id"]:
            dedup_key = f"vid:{info['video_id']}"
        elif info["archive_id"]:
            dedup_key = f"arch:{info['archive_id']}"
        elif info["link_type"] == "shortlink":
            dedup_key = "short:" + re.sub(r"^https?://", "", info["resolved_url"], flags=re.I)
        else:
            dedup_key = "url:" + re.sub(r"^https?://", "", info["resolved_url"], flags=re.I)

        if dedup_key in seen_keys:
            continue
        seen_keys.add(dedup_key)
        info["source_pdf"] = pdf_name
        info["extraction_method"] = method
        results.append(info)

    return results


# ---------------------------------------------------------------------------
# 3. Classical & Modern Books Knowledge Base, Shamela4 Index & Matn Matcher
# ---------------------------------------------------------------------------

MATN_KNOWLEDGE_BASE: list[dict[str, Any]] = [
    # --- الفقه المالكي ---
    {
        "book_id": "maliki:mukhtasar_khalil",
        "title": "مختصر خليل في الفقه المالكي",
        "author": "خليل بن إسحاق الجندي",
        "science": "الفقه المالكي",
        "keywords": ["مختصر خليل", "المختصر الفقهي لخليل", "سلسلة شرح المختصر", "سلسة شرح مختصر خليل"],
        "exclude_keywords": ["الشرح الكبير", "مواهب الجليل"],
    },
    {
        "book_id": "maliki:sharh_kabir_dardir",
        "title": "الشرح الكبير على مختصر خليل",
        "author": "أبو البركات أحمد الدردير",
        "science": "الفقه المالكي",
        "keywords": ["الشرح الكبير على مختصر خليل", "الشرح الكبير للدردير"],
    },
    {
        "book_id": "maliki:sharh_saghir_dardir",
        "title": "الشرح الصغير على أقرب المسالك",
        "author": "أبو البركات أحمد الدردير",
        "science": "الفقه المالكي",
        "keywords": ["الشرح الصغير", "أقرب المسالك"],
    },
    {
        "book_id": "maliki:ashal_al_masalik",
        "title": "نظم أسهل المسالك في مذهب الإمام مالك",
        "author": "محمد البشار",
        "science": "الفقه المالكي",
        "keywords": ["أسهل المسالك", "اسهل المسالك"],
    },
    {
        "book_id": "maliki:risalat_ibn_abi_zayd",
        "title": "رسالة ابن أبي زيد القيرواني",
        "author": "ابن أبي زيد القيرواني",
        "science": "الفقه المالكي",
        "keywords": [
            "رسالة ابن أبي زيد",
            "رساله ابن ابي زيد",
            "الرسالة الفقهية",
            "ابواب الصيام لابن ابي زيد القيرواني",
        ],
    },
    {
        "book_id": "maliki:murshid_muin_ibn_ashir",
        "title": "المرشد المعين على الضروري من علوم الدين (متن ابن عاشر)",
        "author": "عبد الواحد بن عاشر",
        "science": "الفقه المالكي",
        "keywords": ["المرشد المعين", "متن ابن عاشر", "نظم ابن عاشر", "ميارة الصغير", "الضروري من علوم الدين"],
    },
    {
        "book_id": "maliki:mukhtasar_akhdari",
        "title": "مختصر الأخضري في العبادات على مذهب الإمام مالك",
        "author": "عبد الرحمن الأخضري",
        "science": "الفقه المالكي",
        "keywords": ["مختصر الأخضري", "متن الأخضري"],
    },
    {
        "book_id": "maliki:manhaj_muntakhab_zaqqaq",
        "title": "المنهج المنتخب إلى قواعد المذهب",
        "author": "علي بن قاسم الزقاق",
        "science": "الفقه المالكي",
        "keywords": ["المنهج المنتخب", "منهج الزقاق", "قواعد الزقاق", "الزقاقية"],
    },
    {
        "book_id": "maliki:idah_al_masalik",
        "title": "إيضاح المسالك إلى قواعد الإمام مالك",
        "author": "أحمد بن يحيى الونشريسي",
        "science": "الفقه المالكي",
        "keywords": ["إيضاح المسالك", "ايضاح المسالك"],
    },
    {
        "book_id": "maliki:tuhfat_al_hukkam",
        "title": "تحفة الحكام في نكت العقود والأحكام (عاصمية ابن عاصم)",
        "author": "أبو بكر بن عاصم الأندلسي",
        "science": "الفقه المالكي",
        "keywords": ["تحفة الحكام", "عاصمية ابن عاصم"],
    },
    {
        "book_id": "maliki:bidayat_al_mujtahid",
        "title": "بداية المجتهد ونهاية المقتصد",
        "author": "ابن رشد الحفيد",
        "science": "الفقه المقارن والمالكي",
        "keywords": ["بداية المجتهد"],
    },
    # --- الفقه الحنفي والشافعي والعام ---
    {
        "book_id": "hanafi:mukhtasar_quduri",
        "title": "مختصر القدوري في الفقه الحنفي",
        "author": "أبو الحسين أحمد بن محمد القدوري",
        "science": "الفقه الحنفي",
        "keywords": ["مختصر القدوري", "متن القدوري"],
    },
    {
        "book_id": "hanafi:al_lubab_sharh_al_kitab",
        "title": "اللباب في شرح الكتاب",
        "author": "عبد الغني الغنيمي الميداني",
        "science": "الفقه الحنفي",
        "keywords": ["اللباب في شرح الكتاب", "كتاب اللباب"],
    },
    {
        "book_id": "hanafi:al_ikhtiyar_li_talil_al_mukhtar",
        "title": "الاختيار لتعليل المختار",
        "author": "عبد الله بن محمود الموصلي",
        "science": "الفقه الحنفي",
        "keywords": ["الاختيار لتعليل المختار", "كتاب الاختيار"],
    },
    {
        "book_id": "hanafi:sharh_al_wiqaya",
        "title": "شرح الوقاية في مسائل الهداية",
        "author": "عبيد الله بن مسعود المحبوبي (صدر الشريعة)",
        "science": "الفقه الحنفي",
        "keywords": ["شرح الوقاية"],
    },
    {
        "book_id": "hanafi:uqud_rasm_al_mufti",
        "title": "عقود رسم المفتي (وإسعاد المفتي)",
        "author": "محمد أمين بن عابدين",
        "science": "الفقه الحنفي وأصول الإفتاء",
        "keywords": ["عقود رسم المفتي", "إسعاد المفتي", "أصول الإفتاء"],
    },
    {
        "book_id": "hanafi:ghurra_munifa",
        "title": "الغرة المنيفة في تحقيق بعض مسائل الإمام أبي حنيفة",
        "author": "سراج الدين الغزنوي",
        "science": "الفقه الحنفي",
        "keywords": ["الغرة المنيفة"],
    },
    {
        "book_id": "shafii:matn_abi_shuja",
        "title": "متن الغاية والتقريب (متن أبي شجاع)",
        "author": "أبو شجاع أحمد بن الحسين الأصفهاني",
        "science": "الفقه الشافعي",
        "keywords": ["متن الغاية والتقريب", "الغاية والتقريب", "متن أبي شجاع"],
    },
    {
        "book_id": "shafii:safwat_al_zubad",
        "title": "صفوة الزبد (متن الزبد في الفقه الشافعي)",
        "author": "أحمد بن رسلان الرملي",
        "science": "الفقه الشافعي",
        "keywords": ["صفوة الزبد", "متن الزبد"],
    },
    {
        "book_id": "shafii:muqaddimat_al_majmu",
        "title": "مقدمة المجموع شرح المهذب",
        "author": "محيي الدين يحيى بن شرف النووي",
        "science": "الفقه الشافعي",
        "keywords": ["مقدمة المجموع"],
    },
    {
        "book_id": "shafii:sullam_al_tawfiq",
        "title": "سلم التوفيق إلى محبة الله على التحقيق",
        "author": "عبد الله بن حسين بن طاهر باعلوي",
        "science": "الفقه الشافعي والتزكية",
        "keywords": ["سلم التوفيق", "سلم التحقيق إلى محبة الله"],
    },
    {
        "book_id": "shafii:al_risala_al_jamia",
        "title": "الرسالة الجامعة والتذكرة النافعة",
        "author": "أحمد بن زين الحبشي",
        "science": "الفقه الشافعي والتزكية",
        "keywords": ["الرسالة الجامعة"],
    },
    {
        "book_id": "shafii:fawaid_thamina",
        "title": "الفوائد الثمينة في فقه الشافعية",
        "author": "أحمد بن عمر الشاطري",
        "science": "الفقه الشافعي",
        "keywords": ["الفوائد الثمينة"],
    },
    {
        "book_id": "fiqh:nubdha_mashhur",
        "title": "النبذة فيما يجب تعلمه وتعليمه",
        "author": "عبد الرحمن بن محمد المشهور",
        "science": "الفقه الشافعي",
        "keywords": ["النبذة فيما يجب تعلمه", "النبذه فيما يجب علي الانسان تعلمه"],
    },
    {
        "book_id": "fiqh:takmilat_zubdat_al_hadith",
        "title": "تكملة زبدة الحديث في فقه المواريث",
        "author": "محمد بن سالم بن حفيظ التريمي",
        "science": "الفرائض والمواريث",
        "keywords": ["تكملة زبدة الحديث", "تفصيل أحكام المواريث"],
    },
    {
        "book_id": "fiqh:siyasa_shariyya_ibn_taymiyya",
        "title": "السياسة الشرعية في إصلاح الراعي والرعية",
        "author": "أحمد بن عبد الحليم بن تيمية",
        "science": "السياسة الشرعية والفقه",
        "keywords": ["السياسة الشرعية لابن تيمية", "كتاب السياسة الشرعية"],
    },
    {
        "book_id": "9awa3idFi9h:ashbah_wa_nazair",
        "title": "الأشباه والنظائر في قواعد وفروع الفقه",
        "author": "جلال الدين السيوطي",
        "science": "القواعد الفقهية",
        "keywords": ["الأشباه والنظائر", "الأشباه و النظائر"],
    },
    # --- أصول الفقه (مفصول بدقة عن مقاصد الشريعة) ---
    {
        "book_id": "ossoul:iysal_al_salik",
        "title": "إيصال السالك في أصول الإمام مالك",
        "author": "محمد يحيى الولاتي",
        "science": "أصول الفقه",
        "keywords": ["إيصال السالك", "ايصال السالك"],
    },
    {
        "book_id": "ossoul:maraqi_al_suud",
        "title": "مراقي السعود إلى مراقي السعود (ونشر البنود)",
        "author": "عبد الله بن الحاج إبراهيم العلوي",
        "science": "أصول الفقه",
        "keywords": ["مراقي السعود", "نشر البنود", "نيل السول على مراقي السعود"],
    },
    {
        "book_id": "ossoul:jam_al_jawami",
        "title": "جمع الجوامع في أصول الفقه",
        "author": "تاج الدين السبكي",
        "science": "أصول الفقه",
        "keywords": ["جمع الجوامع", "الكوكب الساطع"],
    },
    {
        "book_id": "ossoul:miftah_al_wusul",
        "title": "مفتاح الوصول إلى بناء الفروع على الأصول",
        "author": "أبو عبد الله الشريف التلمساني",
        "science": "أصول الفقه",
        "keywords": ["مفتاح الوصول"],
    },
    {
        "book_id": "ossoul:risala_adudiyya",
        "title": "الرسالة العضدية في علم الوضع",
        "author": "عضد الدين الإيجي",
        "science": "أصول الفقه وعلم الوضع",
        "keywords": ["الرسالة العضدية", "الرساله العضديه"],
    },
    {
        "book_id": "ossoul:waraqat_juwayni",
        "title": "الورقات في أصول الفقه",
        "author": "إمام الحرمين الجويني",
        "science": "أصول الفقه",
        "keywords": ["متن الورقات", "شرح الورقات", "نظم الورقات"],
    },
    {
        "book_id": "ossoul:lubb_al_usul",
        "title": "لب الأصول (وغاية الوصول شرح لب الأصول)",
        "author": "زكريا الأنصاري",
        "science": "أصول الفقه",
        "keywords": ["لب الأصول", "غاية الوصول شرح لب الأصول"],
    },
    # --- مقاصد الشريعة (مفصول تماماً عن أصول الفقه) ---
    {
        "book_id": "maqasid:muwafaqat_shatibi",
        "title": "الموافقات في مقاصد الشريعة",
        "author": "أبو إسحاق الشاطبي",
        "science": "مقاصد الشريعة",
        "keywords": ["الموافقات للشاطبي", "كتاب المقاصد من الموافقات", "شرح كتاب المقاصد"],
    },
    # --- العقيدة وعلم الكلام (منع خلط مقدمات السنوسي بالفقه) ---
    {
        "book_id": "akida:muqaddimat_sanusi",
        "title": "شرح مقدمات الإمام السنوسي في التوحيد وأقسام الأحكام",
        "author": "أبو عبد الله محمد بن يوسف السنوسي",
        "science": "العقيدة وعلم الكلام",
        "keywords": ["مقدمات السنوسي", "مقدمات الإمام السنوسي", "المقدمات للسنوسي", "متن المقدمات"],
    },
    {
        "book_id": "akida:umm_al_barahin",
        "title": "أم البراهين (العقيدة الصغرى للسنوسي)",
        "author": "أبو عبد الله محمد بن يوسف السنوسي",
        "science": "العقيدة وعلم الكلام",
        "keywords": ["أم البراهين", "العقيدة الصغرى", "صغرى السنوسي"],
    },
    {
        "book_id": "akida:sughra_al_sughra_sanusi",
        "title": "صغرى الصغرى في علم التوحيد",
        "author": "أبو عبد الله محمد بن يوسف السنوسي",
        "science": "العقيدة وعلم الكلام",
        "keywords": ["صغرى الصغرى"],
    },
    {
        "book_id": "akida:kubra_sanusi",
        "title": "عمدة أهل التوفيق والتسديد (العقيدة الكبرى للسنوسي وحواشي اليوسي)",
        "author": "أبو عبد الله محمد بن يوسف السنوسي",
        "science": "العقيدة وعلم الكلام",
        "keywords": ["كبرى السنوسي", "حواشي اليوسي على كبرى السنوسي", "العقيدة الكبرى للسنوسي"],
    },
    {
        "book_id": "akida:aqaid_nasafiyya",
        "title": "العقائد النسفية وشرحها للتفتازاني",
        "author": "نجم الدين عمر النسفي",
        "science": "العقيدة وعلم الكلام",
        "keywords": ["العقائد النسفية", "شرح العقائد النسفية"],
    },
    {
        "book_id": "akida:aqidat_al_awam",
        "title": "منظومة عقيدة العوام",
        "author": "أحمد المرزوقي المالكي",
        "science": "العقيدة وعلم الكلام",
        "keywords": ["عقيدة العوام"],
    },
    {
        "book_id": "akida:kharida_bahiyya",
        "title": "الخريدة البهية في العقيدة التوحيدية",
        "author": "أبو البركات أحمد الدردير",
        "science": "العقيدة وعلم الكلام",
        "keywords": ["الخريدة البهية"],
    },
    {
        "book_id": "akida:jawharat_al_tawhid",
        "title": "جوهرة التوحيد",
        "author": "إبراهيم اللقاني",
        "science": "العقيدة وعلم الكلام",
        "keywords": ["جوهرة التوحيد"],
    },
    {
        "book_id": "akida:manzuma_adudiyya_dedew",
        "title": "المنظومة العدودية في عقيدة أهل السنة والجماعة",
        "author": "محمد سالم ولد عدود",
        "science": "العقيدة وعلم الكلام",
        "keywords": ["المنظومة العدودية"],
    },
    {
        "book_id": "akida:manzumat_al_ajhuri",
        "title": "منظومة الأجهوري في أصول الدين",
        "author": "علي الأجهوري",
        "science": "العقيدة وعلم الكلام",
        "keywords": ["منظومة الأجهوري"],
    },
    {
        "book_id": "akida:iqbar_al_intisar_bardoni",
        "title": "إقبار الانتصار (مناقشة كتاب الانتصار للتدمرية)",
        "author": "محمد البردوني الحسيمي",
        "science": "العقيدة وعلم الكلام",
        "keywords": ["إقبار الانتصار"],
    },
    {
        "book_id": "akida:kubra_yaqiniyyat",
        "title": "كبرى اليقينيات الكونية",
        "author": "محمد سعيد رمضان البوطي",
        "science": "العقيدة وعلم الكلام",
        "keywords": ["كبرى اليقينيات الكونية", "كبرى اليقينيات"],
    },
    {
        "book_id": "akida:iqtisad_fi_itiqad",
        "title": "الاقتصاد في الاعتقاد",
        "author": "أبو حامد الغزالي",
        "science": "العقيدة وعلم الكلام",
        "keywords": ["الاقتصاد في الاعتقاد"],
    },
    # --- التزكية والسلوك والأخلاق ---
    {
        "book_id": "tazkia:adab_suluk_al_murid",
        "title": "رسالة آداب سلوك المريد",
        "author": "الحبيب عبد الله بن علوي الحداد",
        "science": "التزكية والسلوك",
        "keywords": ["آداب سلوك المريد", "اداب سلوك المريد"],
    },
    {
        "book_id": "tazkia:minhaj_shuab_al_iman",
        "title": "المنهاج في شعب الإيمان",
        "author": "الحليمي",
        "science": "التزكية والسلوك",
        "keywords": ["المنهاج في شعب الإيمان", "المنهاج في شعب الايمان"],
    },
    {
        "book_id": "tazkia:hikam_ataiyya",
        "title": "الحكم العطائية",
        "author": "ابن عطاء الله السكندري",
        "science": "التزكية والسلوك",
        "keywords": ["الحكم العطائية", "الحكم العطائيه", "رسائل الحكم"],
    },
    {
        "book_id": "tazkia:mukatabat_ataiyya",
        "title": "المكاتبات والمناجاة الإلهية",
        "author": "ابن عطاء الله السكندري",
        "science": "التزكية والسلوك",
        "keywords": ["المكاتبات والمناجاة الإلهية"],
    },
    {
        "book_id": "tazkia:taj_al_arus",
        "title": "تاج العروس الحاوي لتهذيب النفوس",
        "author": "ابن عطاء الله السكندري",
        "science": "التزكية والسلوك",
        "keywords": ["تاج العروس الحاوي لتهذيب النفوس", "تاج العروس"],
    },
    {
        "book_id": "tazkia:qabas_al_nur_al_mubin",
        "title": "قبس النور المبين من إحياء علوم الدين",
        "author": "الحبيب عمر بن حفيظ",
        "science": "التزكية والسلوك",
        "keywords": ["قبس النور المبين"],
    },
    {
        "book_id": "tazkia:ihya_ulum_al_din",
        "title": "إحياء علوم الدين (وموعظة المؤمنين)",
        "author": "أبو حامد الغزالي",
        "science": "التزكية والسلوك",
        "keywords": ["إحياء علوم الدين", "موعظة المؤمنين من إحياء علوم الدين"],
        "exclude_keywords": ["قبس النور المبين"],
    },
    {
        "book_id": "tazkia:bidayat_al_hidaya",
        "title": "بداية الهداية",
        "author": "أبو حامد الغزالي",
        "science": "التزكية والسلوك",
        "keywords": ["بداية الهداية"],
    },
    {
        "book_id": "tazkia:ayyuha_al_walad",
        "title": "أيها الولد",
        "author": "أبو حامد الغزالي",
        "science": "التزكية والسلوك",
        "keywords": ["أيها الولد"],
    },
    {
        "book_id": "tazkia:munqidh_min_al_dalal",
        "title": "المنقذ من الضلال",
        "author": "أبو حامد الغزالي",
        "science": "التزكية والفكر الإسلامي",
        "keywords": ["المنقذ من الضلال"],
    },
    {
        "book_id": "tazkia:mizan_al_amal",
        "title": "ميزان العمل",
        "author": "أبو حامد الغزالي",
        "science": "التزكية والسلوك",
        "keywords": ["ميزان العمل"],
    },
    {
        "book_id": "tazkia:arbain_fi_usul_al_din",
        "title": "الأربعين في أصول الدين",
        "author": "أبو حامد الغزالي",
        "science": "التزكية والعقيدة",
        "keywords": ["الأربعين في أصول الدين"],
    },
    {
        "book_id": "tazkia:al_adab_fi_al_din",
        "title": "الأدب في الدين",
        "author": "أبو حامد الغزالي",
        "science": "التزكية والسلوك",
        "keywords": ["الأدب في الدين"],
    },
    {
        "book_id": "tazkia:risalat_al_muawanah",
        "title": "رسالة المعاونة والمظاهرة والمؤازرة",
        "author": "الحبيب عبد الله بن علوي الحداد",
        "science": "التزكية والسلوك",
        "keywords": ["رسالة المعاونة", "رساله المعاونه"],
    },
    {
        "book_id": "tazkia:ithaf_al_sail",
        "title": "إتحاف السائل بجواب المسائل",
        "author": "الحبيب عبد الله بن علوي الحداد",
        "science": "التزكية والسلوك",
        "keywords": ["إتحاف السائل"],
    },
    {
        "book_id": "tazkia:risala_qushayriyya",
        "title": "الرسالة القشيرية",
        "author": "أبو القاسم القشيري",
        "science": "التزكية والسلوك",
        "keywords": ["الرسالة القشيرية", "الرساله القشيريه"],
    },
    {
        "book_id": "tazkia:manazil_al_sairin",
        "title": "منازل السائرين (وسبيل المبتدئين)",
        "author": "أبو إسماعيل عبد الله الأنصاري الهروي",
        "science": "التزكية والسلوك",
        "keywords": ["منازل السائرين", "سبيل المبتدئين في شرح البدايات من منازل السائرين"],
    },
    {
        "book_id": "tazkia:maqasid_al_riaya",
        "title": "مقاصد الرعاية لحقوق الله عز وجل",
        "author": "العز بن عبد السلام (مختصر الرعاية للمحاسبي)",
        "science": "التزكية والسلوك",
        "keywords": ["مقاصد الرعاية لحقوق الله", "مقاصد الرعاية"],
    },
    {
        "book_id": "tazkia:qawaid_al_tasawwuf",
        "title": "قواعد التصوف",
        "author": "أحمد زروق الفاسي",
        "science": "التزكية والسلوك",
        "keywords": ["قواعد التصوف"],
    },
    {
        "book_id": "tazkia:futuh_al_ghayb",
        "title": "فتوح الغيب",
        "author": "عبد القادر الجيلاني",
        "science": "التزكية والسلوك",
        "keywords": ["فتوح الغيب"],
    },
    {
        "book_id": "tazkia:lawaqih_al_anwar",
        "title": "لواقح الأنوار القدسية في بيان العهود المحمدية",
        "author": "عبد الوهاب الشعراني",
        "science": "التزكية والسلوك",
        "keywords": ["لواقح الأنوار القدسية"],
    },
    {
        "book_id": "tazkia:kashf_al_ghumma",
        "title": "كشف الغمة عن جميع الأمة",
        "author": "عبد الوهاب الشعراني",
        "science": "الحديث والتزكية والفقه",
        "keywords": ["كشف الغمة عن جميع الأمة", "كشف الغمة"],
    },
    {
        "book_id": "tazkia:tanwir_al_qulub",
        "title": "تنوير القلوب في معاملة علام الغيوب",
        "author": "محمد أمين الكردي",
        "science": "التزكية والفقه والعقيدة",
        "keywords": ["تنوير القلوب"],
    },
    {
        "book_id": "tazkia:kibrit_al_ahmar",
        "title": "الكبريت الأحمر والإكسير الأكبر",
        "author": "عبد الله بن أبي بكر العيدروس",
        "science": "التزكية والسلوك",
        "keywords": ["الكبريت الأحمر"],
    },
    {
        "book_id": "tazkia:idah_asrar_ulum_al_muqarrabin",
        "title": "إيضاح أسرار علوم المقربين",
        "author": "محمد بن عبد الله العيدروس",
        "science": "التزكية والسلوك",
        "keywords": ["إيضاح أسرار علوم المقربين"],
    },
    {
        "book_id": "tazkia:qamie_al_tughyan",
        "title": "قامع الطغيان على منظومة شعب الإيمان",
        "author": "محمد نووي الجاوي",
        "science": "التزكية والسلوك",
        "keywords": ["قامع الطغيان", "منظومة شعب الإيمان"],
    },
    {
        "book_id": "tazkia:akhlaq_wa_siyar_ibn_hazm",
        "title": "الأخلاق والسير في مداواة النفوس",
        "author": "ابن حزم الأندلسي",
        "science": "الأخلاق والتزكية",
        "keywords": ["الأخلاق والسير", "الأخلاق و السير"],
    },
    {
        "book_id": "tazkia:maharim_al_lisan",
        "title": "نظم محارم اللسان (مطهرة القلوب)",
        "author": "محمد مولود بن أحمد فال اليعقوبي",
        "science": "التزكية والآداب",
        "keywords": ["نظم محارم اللسان", "محارم اللسان"],
    },
    {
        "book_id": "tazkia:jami_fi_adab_shariyya",
        "title": "نظم الجامع في الآداب الشرعية",
        "author": "محمد سالم ولد عدود",
        "science": "التزكية والآداب",
        "keywords": ["الجامع في الآداب الشرعية"],
    },
    {
        "book_id": "tazkia:tadhkirat_al_sami",
        "title": "تذكرة السامع والمتكلم في أدب العالم والمتعلم",
        "author": "بدر الدين بن جماعة",
        "science": "التزكية وآداب الطلب",
        "keywords": ["تذكرة السامع والمتكلم", "آداب المتعلم والمعلم"],
    },
    {
        "book_id": "tazkia:mustakhlas_fi_tazkiyat_al_anfus",
        "title": "المستخلص في تزكية الأنفس",
        "author": "سعيد حوى",
        "science": "التزكية والسلوك",
        "keywords": ["المستخلص في تزكية الأنفس"],
    },
    {
        "book_id": "tazkia:fadhlakat_al_haqiqa",
        "title": "فذلكة الحقيقة في أحكام الطريقة",
        "author": "محمد مهدي الصيادي الرواس",
        "science": "التزكية والسلوك",
        "keywords": ["فذلكة الحقيقة"],
    },
    {
        "book_id": "tazkia:ubudiyya_ibn_taymiyya",
        "title": "كتاب العبودية (والفوائد لابن القيم)",
        "author": "ابن تيمية / ابن القيم",
        "science": "التزكية والعقيدة",
        "keywords": ["كتاب العبودية لابن تيمية", "كتاب الفوائد لابن القيم"],
    },
    {
        "book_id": "tazkia:khuluquna_hafiz",
        "title": "خلقنا",
        "author": "الحبيب عمر بن حفيظ",
        "science": "التزكية والأخلاق",
        "keywords": ["كتاب خلقنا", "ختم كتاب: خلقنا"],
    },
    {
        "book_id": "tazkia:silat_al_aqrabin_hafiz",
        "title": "صلة الأقربين",
        "author": "الحبيب عمر بن حفيظ",
        "science": "التزكية والآداب",
        "keywords": ["صلة الأقربين"],
    },
    # --- التفسير وعلوم القرآن والتجويد ---
    {
        "book_id": "tafsir:madarik_al_tanzil_nasafi",
        "title": "مدارك التنزيل وحقائق التأويل (تفسير النسفي)",
        "author": "أبو البركات عبد الله بن أحمد النسفي",
        "science": "التفسير وعلوم القرآن",
        "keywords": ["تفسير النسفي", "مدارك التنزيل"],
    },
    {
        "book_id": "tafsir:durr_masun_samin_halabi",
        "title": "الدر المصون في علوم الكتاب المكنون",
        "author": "السمين الحلبي",
        "science": "التفسير وإعراب القرآن",
        "keywords": ["الدر المصون"],
    },
    {
        "book_id": "tafsir:iklil_fi_istinbat_tanzil",
        "title": "الإكليل في استنباط التنزيل",
        "author": "جلال الدين السيوطي",
        "science": "التفسير وعلوم القرآن",
        "keywords": ["الإكليل في استنباط التنزيل", "الاكليل في استباط التنزيل"],
    },
    {
        "book_id": "tafsir:khawatir_shaarawy",
        "title": "تفسير وخواطر الشيخ محمد متولي الشعراوي حول القرآن الكريم",
        "author": "محمد متولي الشعراوي",
        "science": "التفسير وعلوم القرآن",
        "keywords": [
            "تفسير الشعراوي",
            "خواطر الشيخ محمد متولي الشعراوي",
            "سلسلة تفسير القرآن الكريم للشيخ محمد متولي الشعراوي",
        ],
    },
    {
        "book_id": "tafsir:lamasat_bayaniyya_samarrai",
        "title": "لمسات بيانية في نصوص من التنزيل",
        "author": "فاضل صالح السامرائي",
        "science": "البلاغة القرآنية والتفسير البياني",
        "keywords": ["لمسات بيانية"],
    },
    {
        "book_id": "3olomQuran:tibyan_nawawi",
        "title": "التبيان في آداب حملة القرآن",
        "author": "محيي الدين يحيى بن شرف النووي",
        "science": "علوم القرآن والآداب",
        "keywords": ["التبيان في آداب حملة القرآن"],
    },
    {
        "book_id": "3olomQuran:ulum_al_quran_itr",
        "title": "علوم القرآن الكريم",
        "author": "نور الدين عتر",
        "science": "علوم القرآن",
        "keywords": ["علوم القرآن لنور الدين عتر", "علوم القرآن (1) لنور الدين عتر"],
    },
    {
        "book_id": "3olomQuran:naba_azim_daraz",
        "title": "النبأ العظيم نظرات جديدة في القرآن",
        "author": "محمد عبد الله دراز",
        "science": "علوم القرآن والإعجاز",
        "keywords": ["النبأ العظيم"],
    },
    {
        "book_id": "tajwid:muqaddima_jazariyya",
        "title": "المقدمة الجزرية في التجويد",
        "author": "محمد بن محمد بن الجزري",
        "science": "التجويد والقراءات",
        "keywords": ["متن الجزرية", "المقدمة الجزرية", "شرح الجزرية"],
    },
    # --- الحديث النبوي وعلومه والسيرة ---
    {
        "book_id": "hadith:sahih_al_bukhari",
        "title": "الجامع المسند الصحيح (صحيح البخاري)",
        "author": "محمد بن إسماعيل البخاري",
        "science": "الحديث النبوي وشروحه",
        "keywords": ["صحيح البخاري", "جامع البخاري", "الكوكب الساري", "مجالس البخاري", "سماع كتب السنة"],
    },
    {
        "book_id": "hadith:sahih_muslim",
        "title": "المسند الصحيح (صحيح مسلم)",
        "author": "مسلم بن الحجاج النيسابوري",
        "science": "الحديث النبوي وشروحه",
        "keywords": ["صحيح مسلم", "مقدمة صحيح مسلم"],
    },
    {
        "book_id": "hadith:muwatta_malik",
        "title": "موطأ الإمام مالك",
        "author": "مالك بن أنس",
        "science": "الحديث النبوي والفقه المالكي",
        "keywords": ["موطأ الإمام مالك", "موطأ مالك", "شرح الموطأ", "مجالس الموطأ", "شرح الزرقاني على موطأ"],
    },
    {
        "book_id": "hadith:musnad_ahmad",
        "title": "مسند الإمام أحمد بن حنبل",
        "author": "أحمد بن حنبل",
        "science": "الحديث النبوي وشروحه",
        "keywords": ["مسند أحمد", "مسند الإمام أحمد", "مسانيد الإمام أحمد"],
    },
    {
        "book_id": "hadith:jam_bayn_al_sahihayn",
        "title": "الجمع بين الصحيحين (أنوار الصحيحين)",
        "author": "الحميدي / عبد الحق الإشبيلي",
        "science": "الحديث النبوي وشروحه",
        "keywords": ["الجمع بين الصحيحين", "أنوار الصحيحين"],
    },
    {
        "book_id": "hadith:riyad_al_salihin",
        "title": "رياض الصالحين من كلام سيد المرسلين",
        "author": "محيي الدين يحيى بن شرف النووي",
        "science": "الحديث النبوي والتزكية",
        "keywords": ["رياض الصالحين"],
    },
    {
        "book_id": "hadith:arbain_nawawiyya",
        "title": "الأربعون النووية في الأحاديث الصحيحة النبوية",
        "author": "محيي الدين يحيى بن شرف النووي",
        "science": "الحديث النبوي وشروحه",
        "keywords": ["الأربعين النووية", "الأربعون النووية"],
    },
    {
        "book_id": "hadith:umdat_al_ahkam",
        "title": "عمدة الأحكام من كلام خير الأنام (وإحكام الأحكام لابن دقيق العيد)",
        "author": "عبد الغني المقدسي / ابن دقيق العيد",
        "science": "أحاديث الأحكام",
        "keywords": ["عمدة الأحكام", "إحكام الأحكام شرح عمدة الأحكام"],
    },
    {
        "book_id": "hadith:bulugh_al_maram",
        "title": "بلوغ المرام من أدلة الأحكام",
        "author": "ابن حجر العسقلاني",
        "science": "أحاديث الأحكام",
        "keywords": ["بلوغ المرام"],
    },
    {
        "book_id": "hadith:adab_al_mufrad",
        "title": "الأدب المفرد",
        "author": "محمد بن إسماعيل البخاري",
        "science": "الحديث النبوي والآداب",
        "keywords": ["الأدب المفرد"],
    },
    {
        "book_id": "hadith:shamail_muhammadiyya",
        "title": "الشمائل المحمدية",
        "author": "أبو عيسى محمد بن عيسى الترمذي",
        "science": "السيرة والشمائل النبوية",
        "keywords": ["الشمائل المحمدية", "شمائل النبي صلى الله عليه وسلم"],
    },
    {
        "book_id": "hadith:muqaddimat_ibn_al_salah",
        "title": "علوم الحديث (مقدمة ابن الصلاح)",
        "author": "أبو عمرو عثمان بن الصلاح",
        "science": "مصطلح الحديث وعلومه",
        "keywords": ["مقدمة ابن الصلاح", "كتاب علوم الحديث"],
    },
    {
        "book_id": "hadith:nuzhat_al_nazar",
        "title": "نزهة النظر في توضيح نخبة الفكر",
        "author": "ابن حجر العسقلاني",
        "science": "مصطلح الحديث وعلومه",
        "keywords": ["نزهة النظر", "نخبة الفكر", "شرح النزهة"],
    },
    {
        "book_id": "hadith:manzuma_bayquniyya",
        "title": "المنظومة البيقونية في مصطلح الحديث",
        "author": "عمر بن محمد البيقوني",
        "science": "مصطلح الحديث وعلومه",
        "keywords": ["المنظومة البيقونية", "شرح البيقونية", "الشرح الجديد على البيقونية"],
    },
    {
        "book_id": "hadith:ilal_al_tirmidhi",
        "title": "علل الترمذي الكبير والصغير",
        "author": "أبو عيسى محمد بن عيسى الترمذي",
        "science": "علل الحديث",
        "keywords": ["علل الترمذي", "مقاصد شرح العلل"],
    },
    {
        "book_id": "hadith:al_tamyiz_muslim",
        "title": "كتاب التمييز للإمام مسلم",
        "author": "مسلم بن الحجاج النيسابوري",
        "science": "علل الحديث ومصطلحه",
        "keywords": ["كتاب التمييز للإمام مسلم", "التمييز للإمام مسلم"],
    },
    {
        "book_id": "hadith:tahrir_ulum_al_hadith",
        "title": "تحرير علوم الحديث",
        "author": "عبد الله بن يوسف الجديع",
        "science": "مصطلح الحديث وعلومه",
        "keywords": ["تحرير علوم الحديث"],
    },
    {
        "book_id": "hadith:nazm_al_muin",
        "title": "نظم المعين في الحديث",
        "author": "أحمد السيد",
        "science": "الحديث النبوي وعلومه",
        "keywords": ["نظم المعين في الحديث", "نظم المعين"],
    },
    {
        "book_id": "hadith:arbain_ghumariyya",
        "title": "الأربعون الغمارية في شكر النعم",
        "author": "عبد الله بن الصديق الغماري",
        "science": "الحديث النبوي وشروحه",
        "keywords": ["الأربعون الغمارية", "الأربعين الغمارية"],
    },
    {
        "book_id": "hadith:maalim_al_sunnah",
        "title": "معالم السنة النبوية",
        "author": "صالح بن أحمد الشامي",
        "science": "الحديث النبوي وشروحه",
        "keywords": ["معالم السنة النبوية"],
    },
    {
        "book_id": "hadith:shifa_qadi_iyad",
        "title": "الشفا بتعريف حقوق المصطفى",
        "author": "القاضي عياض اليحصبي",
        "science": "السيرة والشمائل النبوية",
        "keywords": ["الشفا بتعريف حقوق المصطفى", "الشفا للقاضي عياض", "كرسي القاضي عياض لشرح الشفا"],
    },
    {
        "book_id": "sirah:fiqh_al_sirah_bouti",
        "title": "فقه السيرة النبوية",
        "author": "محمد سعيد رمضان البوطي",
        "science": "السيرة النبوية",
        "keywords": ["فقه السيرة النبوية", "فقه السيرة"],
    },
    {
        "book_id": "sirah:manzumat_ibn_abi_al_izz",
        "title": "الأرجوزة الميئية في ذكر حال أشرف البرية (منظومة ابن أبي العز في السيرة)",
        "author": "ابن أبي العز الحنفي",
        "science": "السيرة النبوية",
        "keywords": ["منظومة ابن أبي العز الحنفي في السيرة", "الأرجوزة الميئية"],
    },
    {
        "book_id": "sirah:bahjat_al_mahafil",
        "title": "بهجة المحافل وبغية الأماثل في تلخيص المعجزات والسير والشمائل",
        "author": "يحيى بن أبي بكر العامري",
        "science": "السيرة والشمائل النبوية",
        "keywords": ["بهجة المحافل"],
    },
    {
        "book_id": "sirah:misk_al_khitam_dedew",
        "title": "مسك الختام في سيرة سيد الأنام",
        "author": "محمد الحسن الددو",
        "science": "السيرة النبوية",
        "keywords": ["مسك الختام في سيرة سيد الأنام"],
    },
    {
        "book_id": "sirah:nur_al_yaqin",
        "title": "نور اليقين في سيرة سيد المرسلين",
        "author": "محمد الخضري بك",
        "science": "السيرة النبوية",
        "keywords": ["نور اليقين في سيرة سيد المرسلين", "نور اليقين"],
    },
    {
        "book_id": "tazkia:al_daa_wal_dawa",
        "title": "الداء والدواء (الجواب الكافي لمن سأل عن الدواء الشافي)",
        "author": "ابن قيم الجوزية",
        "science": "التزكية والأخلاق",
        "keywords": ["الداء والدواء", "الجواب الكافي"],
    },
    # --- اللغة العربية والنحو والصرف والبلاغة والأدب ---
    {
        "book_id": "nahw:alfiyyat_ibn_malik",
        "title": "ألفية ابن مالك في النحو والصرف",
        "author": "ابن مالك الأندلسي",
        "science": "النحو والصرف",
        "keywords": [
            "ألفية ابن مالك",
            "شرح ابن عقيل",
            "شرح الأشموني",
            "أوضح المسالك",
            "شرح السيوطي على الألفية",
            "البهجة المرضية",
        ],
    },
    {
        "book_id": "nahw:tashil_al_fawaid",
        "title": "تسهيل الفوائد وتكميل المقاصد (وشرح المساعد لابن عقيل)",
        "author": "ابن مالك الأندلسي",
        "science": "النحو والصرف",
        "keywords": ["تسهيل الفوائد", "شرح المساعد لابن عقيل"],
    },
    {
        "book_id": "nahw:qatr_al_nada",
        "title": "قطر الندى وبل الصدى",
        "author": "ابن هشام الأنصاري",
        "science": "النحو والصرف",
        "keywords": ["قطر الندى", "قطر الندي", "شرح الفاكهي للقطر"],
    },
    {
        "book_id": "nahw:shudhur_al_dhahab",
        "title": "شذور الذهب في معرفة كلام العرب",
        "author": "ابن هشام الأنصاري",
        "science": "النحو والصرف",
        "keywords": ["شذور الذهب"],
    },
    {
        "book_id": "nahw:ajurrumiyya",
        "title": "المقدمة الآجرومية (والتحفة السنية)",
        "author": "ابن آجروم الصنهاجي",
        "science": "النحو والصرف",
        "keywords": ["الآجرومية", "الاجروميه", "متن الآجرومية", "التحفة السنية"],
    },
    {
        "book_id": "nahw:mulhat_al_irab",
        "title": "ملحة الإعراب",
        "author": "أبو محمد القاسم بن علي الحريري",
        "science": "النحو والصرف",
        "keywords": ["ملحة الإعراب"],
    },
    {
        "book_id": "nahw:muwassil_al_tullab",
        "title": "موصل الطلاب إلى قواعد الإعراب",
        "author": "خالد بن عبد الله الأزهري",
        "science": "النحو والصرف",
        "keywords": ["موصل الطلاب إلى قواعد الإعراب", "موصل الطلاب"],
    },
    {
        "book_id": "sarf:lamiyyat_al_afaal",
        "title": "لامية الأفعال في علم الصرف",
        "author": "ابن مالك الأندلسي",
        "science": "النحو والصرف",
        "keywords": ["لامية الأفعال", "لاميه الافعال"],
    },
    {
        "book_id": "sarf:tasrif_al_izzi",
        "title": "تصريف العزي (ومع شرح التفتازاني)",
        "author": "عز الدين عبد الوهاب الزنجاني",
        "science": "النحو والصرف",
        "keywords": ["تصريف العزي", "شرح العزي"],
    },
    {
        "book_id": "sarf:bina_al_afaal",
        "title": "متن البناء والأساس في علم التصريف (بناء الأفعال)",
        "author": "عبد الله الدنقزي",
        "science": "النحو والصرف",
        "keywords": ["البناء والأساس", "البناء في التصريف", "متن البناء في علم التصريف", "البناء في علم التصريف"],
    },
    {
        "book_id": "sarf:al_maqsud_fi_sarf",
        "title": "المقصود في علم الصرف",
        "author": "منسوب للإمام أبي حنيفة",
        "science": "النحو والصرف",
        "keywords": ["المقصود في الصرف"],
    },
    {
        "book_id": "sarf:amthila_mukhtalifa",
        "title": "الأمثلة المختلفة في علم الصرف",
        "author": "علماء الصرف",
        "science": "النحو والصرف",
        "keywords": ["الأمثلة المختلفة", "الأمثلة المختلة في الصرف"],
    },
    {
        "book_id": "balagha:dalail_al_ijaz",
        "title": "دلائل الإعجاز في علم المعاني",
        "author": "عبد القاهر الجرجاني",
        "science": "البلاغة القرآنية",
        "keywords": ["دلائل الإعجاز", "دلائل الاعجاز"],
    },
    {
        "book_id": "balagha:jawhar_maknun",
        "title": "الجوهر المكنون في صدف الثلاثة فنون",
        "author": "عبد الرحمن الأخضري",
        "science": "البلاغة العربية",
        "keywords": ["الجوهر المكنون"],
    },
    {
        "book_id": "balagha:durus_al_balagha",
        "title": "دروس البلاغة",
        "author": "حفني ناصف ومحمد دياب ومصطفى طموم وسلطان محمد",
        "science": "البلاغة العربية",
        "keywords": ["دروس البلاغة"],
    },
    {
        "book_id": "balagha:minhaj_wadih_balagha",
        "title": "المنهاج الواضح للبلاغة",
        "author": "حامد عوني",
        "science": "البلاغة العربية",
        "keywords": ["المنهاج الواضح"],
    },
    {
        "book_id": "balagha:risala_samarqandiyya",
        "title": "الرسالة السمرقندية في الاستعارات (ونظم الاستعارة)",
        "author": "أبو القاسم بن أبي بكر السمرقندي",
        "science": "البلاغة العربية",
        "keywords": ["الرسالة السمرقندية", "السمرقندية في الاستعارات", "نظم الاستعارة"],
    },
    {
        "book_id": "adab:maqamat_hariri",
        "title": "مقامات الحريري",
        "author": "أبو محمد القاسم بن علي الحريري",
        "science": "الأدب واللغة",
        "keywords": ["مقامات الحريري", "شرح المقامات"],
    },
    {
        "book_id": "adab:lamiyyat_al_arab",
        "title": "لامية العرب",
        "author": "الشنفرى",
        "science": "الأدب والشعر العربي",
        "keywords": ["لامية العرب"],
    },
    {
        "book_id": "adab:lamiyyat_ibn_al_wardi",
        "title": "لامية ابن الوردي (نصيحة الإخوان ومرشدة الخلان)",
        "author": "عمر بن مظفر بن الوردي",
        "science": "الأدب والآداب",
        "keywords": ["لامية ابن الوردي"],
    },
    {
        "book_id": "adab:unwan_al_hikam",
        "title": "قصيدة عنوان الحكم (نونـية البستي)",
        "author": "أبو الفتح البستي",
        "science": "الأدب والحكمة",
        "keywords": ["عنوان الحكم"],
    },
    {
        "book_id": "adab:manzumat_al_ilbiri",
        "title": "تائية الألبيري (منظومة الألبيري في الأدب وطلب العلم)",
        "author": "أبو إسحاق الإلبيري",
        "science": "الأدب وآداب الطلب",
        "keywords": ["منظومة الألبيري", "تائية الألبيري"],
    },
    {
        "book_id": "adab:muallaqat_imru_al_qais",
        "title": "معلقة امرئ القيس",
        "author": "امرؤ القيس",
        "science": "الأدب والشعر العربي",
        "keywords": ["معلقة امرئ القيس"],
    },
    # --- المنطق وآداب البحث والفكر المعاصر ---
    {
        "book_id": "mantiq:sullam_munawwaraq",
        "title": "السلم المنورق في علم المنطق",
        "author": "عبد الرحمن الأخضري",
        "science": "المنطق وآداب البحث",
        "keywords": ["السلم المنورق"],
    },
    {
        "book_id": "mantiq:isaghuji",
        "title": "إيساغوجي في المنطق (ومغني الطلاب وشرح الحسام الكاتي)",
        "author": "أثير الدين الأبهري",
        "science": "المنطق وآداب البحث",
        "keywords": ["إيساغوجي", "ايساغوجي", "مغني الطلاب", "شرح الحسام الكاتي"],
    },
    {
        "book_id": "mantiq:maqulat_sujai",
        "title": "نظم المقولات العشر وشرحها للسجاعي",
        "author": "أحمد بن أحمد السجاعي",
        "science": "المنطق والمقولات",
        "keywords": ["مقولات السجاعي", "شرح المقولات"],
    },
    {
        "book_id": "mantiq:adab_al_bahth_wal_munazara",
        "title": "آداب البحث والمناظرة (وفتح الوهاب بشرح الآداب)",
        "author": "طاشكبري زاده / زكريا الأنصاري",
        "science": "المنطق وآداب البحث",
        "keywords": ["آداب البحث والمناظرة", "آداب البحث و المناظرة", "فتح الوهاب بشرح الآداب"],
    },
    {
        "book_id": "fikr:fi_sittat_ayyam",
        "title": "في ستة أيام",
        "author": "علي محمود العمري",
        "science": "الفكر الإسلامي والعقيدة",
        "keywords": ["في ستة أيام", "في سته ايام"],
    },
    {
        "book_id": "fikr:tasis_way_al_muslim_ayman",
        "title": "دورة تأسيس وعي المسلم المعاصر",
        "author": "أيمن عبد الرحيم",
        "science": "الفكر الإسلامي والوعي المعاصر",
        "keywords": ["تأسيس وعي المسلم المعاصر", "دورة الوعي المعاصر"],
    },
    {
        "book_id": "fikr:al_bayt_al_muslim_ayman",
        "title": "دورة البيت المسلم",
        "author": "أيمن عبد الرحيم",
        "science": "التربية والأسرة",
        "keywords": ["دورة البيت المسلم", "البيت المسلم"],
    },
    {
        "book_id": "fikr:al_way_al_lughawi_ayman",
        "title": "دورة الوعي اللغوي ومدخل إلى علم اللغة",
        "author": "أيمن عبد الرحيم",
        "science": "اللغة العربية والوعي اللغوي",
        "keywords": ["دورة الوعي اللغوي", "مدخل إلي علم اللغة", "مدخل إلى علم اللغة"],
    },
    {
        "book_id": "fikr:mukawinat_al_aql_al_muslim_gomaa",
        "title": "مكونات العقل المسلم",
        "author": "علي جمعة",
        "science": "الفكر الإسلامي وأصول المعرفة",
        "keywords": ["مكونات العقل المسلم"],
    },
    {
        "book_id": "fikr:fiqh_al_nafs_hashemi",
        "title": "مجالس فقه النفس",
        "author": "عبد الرحمن ذاكر الهاشمي",
        "science": "فقه النفس والتربية",
        "keywords": ["مجالس فقه النفس", "فقه النفس في القرآن", "كراسة قراءة النفس"],
    },
    {
        "book_id": "fikr:minhaj_mirath_al_nubuwwa_sayed",
        "title": "المنهاج من ميراث النبوة",
        "author": "أحمد السيد",
        "science": "الحديث والتزكية والبناء المنهجي",
        "keywords": ["المنهاج من ميراث النبوة", "خلاصات أبواب المنهاج"],
    },
    # --- متون وكتب إضافية من سلاسل المشايخ الـ 17 ---
    {
        "book_id": "balagha:tuhfat_al_ikhwan_dardir",
        "title": "تحفة الإخوان في علم البيان",
        "author": "أبو البركات أحمد الدردير",
        "science": "البلاغة العربية",
        "keywords": ["تحفة الإخوان في علم البيان", "تحفة الإخوان للدردير", "تحفة الإخوان لأحمد الدردير"],
    },
    {
        "book_id": "balagha:al_balagha_al_wadiha",
        "title": "البلاغة الواضحة",
        "author": "علي الجارم ومصطفى أمين",
        "science": "البلاغة العربية",
        "keywords": ["البلاغة الواضحة"],
    },
    {
        "book_id": "sarf:taysir_al_ilal_wal_ibdal",
        "title": "تيسير الإعلال والإبدال",
        "author": "عبد العليم إبراهيم",
        "science": "النحو والصرف",
        "keywords": ["تيسير الإعلال والإبدال"],
    },
    {
        "book_id": "nahw:al_nahw_al_wazifi",
        "title": "النحو الوظيفي",
        "author": "عبد العليم إبراهيم",
        "science": "النحو والصرف",
        "keywords": ["النحو الوظيفي"],
    },
    {
        "book_id": "sarf:unwan_al_zarf",
        "title": "عنوان الظرف في فن الصرف",
        "author": "هارون بن عبد الرزاق",
        "science": "النحو والصرف",
        "keywords": ["عنوان الظرف"],
    },
    {
        "book_id": "mantiq:al_miftah_fi_ilm_al_mantiq",
        "title": "المفتاح في علم المنطق",
        "author": "علماء المنطق",
        "science": "المنطق وآداب البحث",
        "keywords": ["المفتاح في علم المنطق"],
    },
    {
        "book_id": "hadith:taysir_mustalah_al_hadith",
        "title": "تيسير مصطلح الحديث (وتيسير علوم الحديث)",
        "author": "محمود الطحان",
        "science": "مصطلح الحديث وعلومه",
        "keywords": ["تيسير مصطلح الحديث", "تيسير علوم الحديث"],
    },
    {
        "book_id": "fiqh:kitab_al_siyam_sirajuddin",
        "title": "حول الصيام (كتاب الصيام)",
        "author": "عبد الله سراج الدين",
        "science": "الفقه والتزكية",
        "keywords": ["كتاب الصيام للشيخ عبدالله سراج الدين", "كتاب الصيام للشيخ عبد الله سراج الدين"],
    },
    {
        "book_id": "tazkia:al_wasaya_al_nafia_haddad",
        "title": "الوصايا النافعة",
        "author": "الحبيب عبد الله بن علوي الحداد",
        "science": "التزكية والسلوك",
        "keywords": ["الوصايا النافعة", "كتاب الوصايا النافعة"],
    },
    {
        "book_id": "tazkia:fath_basair_al_ikhwan_hafiz",
        "title": "فتح بصائر الإخوان",
        "author": "الحبيب عمر بن حفيظ",
        "science": "التزكية والسلوك",
        "keywords": ["فتح بصائر الإخوان"],
    },
    {
        "book_id": "tazkia:fath_al_karim_al_ghafir",
        "title": "فتح الكريم الغافر في شرح جلبة المسافر",
        "author": "الحبيب عمر بن حفيظ",
        "science": "التزكية والآداب",
        "keywords": ["فتح الكريم الغافر", "جلبة المسافر"],
    },
    {
        "book_id": "tazkia:aqd_al_mithaq",
        "title": "عقد الميثاق",
        "author": "الحبيب عمر بن حفيظ",
        "science": "التزكية والسلوك",
        "keywords": ["كتاب: عقد الميثاق", "عقد الميثاق"],
    },
    {
        "book_id": "tazkia:mamlakat_al_qalb",
        "title": "مملكة القلب والأعضاء",
        "author": "الحبيب عمر بن حفيظ",
        "science": "التزكية والسلوك",
        "keywords": ["مملكة القلب والأعضاء"],
    },
    {
        "book_id": "tazkia:raf_al_astar",
        "title": "رفع الأستار",
        "author": "الحبيب عمر بن حفيظ",
        "science": "التزكية والعقيدة",
        "keywords": ["كتاب: رفع الأستار", "رفع الأستار"],
        "exclude_keywords": ["رحلة الهند", "India Tour"],
    },
    {
        "book_id": "tazkia:lidhati_bidhati_bakathir",
        "title": "شرح قصيدة لذاتي بذاتي",
        "author": "عبد الله باكثير",
        "science": "التزكية والأدب",
        "keywords": ["قصيدة: لذاتي بذاتي", "لذاتي بذاتي"],
    },
    {
        "book_id": "tazkia:qasidat_tariqatuna_rawwas",
        "title": "قصيدة طريقتنا للإمام الرواس",
        "author": "محمد مهدي الصيادي الرواس",
        "science": "التزكية والسلوك",
        "keywords": ["قصيدة طريقتنا"],
    },
    {
        "book_id": "fikr:afrah_al_ruh_qutb",
        "title": "أفراح الروح",
        "author": "سيد قطب",
        "science": "الفكر الإسلامي والأدب",
        "keywords": ["أفراح الروح"],
    },
    {
        "book_id": "fiqh:al_durar_al_bahiyya",
        "title": "الدرر البهية في المسائل الفقهية (والروضة الندية)",
        "author": "محمد بن علي الشوكاني",
        "science": "الفقه المقارن",
        "keywords": ["الدرر البهية", "الروضة الندية شرح الدرر البهية"],
    },
    {
        "book_id": "tajweed:al_durar_al_lawami",
        "title": "الدرر اللوامع في أصل مقرأ الإمام نافع",
        "author": "أبو الحسن علي بن محمد ابن بري",
        "science": "القراءات والتجويد",
        "keywords": ["الدرر اللوامع في أصل مقرأ الإمام نافع", "مقرأ الإمام نافع", "متن الدرر اللوامع"],
    },
    {
        "book_id": "nahw:nazm_ubayd_rabbih",
        "title": "نظم الآجرومية لعبيد ربه الشنقيطي",
        "author": "محمد بن آب القلاوي الشنقيطي (عبيد ربه)",
        "science": "النحو والصرف",
        "keywords": ["نظم عبيد ربه", "عبيد ربه", "نظم الآجرومية لعبيد ربه"],
    },
    {
        "book_id": "tafsir:manzumat_al_zamzami",
        "title": "منظومة الزمزمي في علوم القرآن (التفسير)",
        "author": "عبد العزيز بن علي الزمزمي",
        "science": "التفسير وعلوم القرآن",
        "keywords": ["منظومة الزمزمي", "نظم الزمزمي"],
    },
    {
        "book_id": "tafsir:al_tashil_ibn_juzayy",
        "title": "التسهيل لعلوم التنزيل",
        "author": "محمد بن أحمد بن جزي الكلبي",
        "science": "التفسير وعلوم القرآن",
        "keywords": ["التسهيل لعلوم التنزيل", "تفسير ابن جزي"],
    },
]

QURAN_SURAHS: list[tuple[int, str]] = [
    (1, "الفاتحة"), (2, "البقرة"), (3, "آل عمران"), (4, "النساء"), (5, "المائدة"),
    (6, "الأنعام"), (7, "الأعراف"), (8, "الأنفال"), (9, "التوبة"), (10, "يونس"),
    (11, "هود"), (12, "يوسف"), (13, "الرعد"), (14, "إبراهيم"), (15, "الحجر"),
    (16, "النحل"), (17, "الإسراء"), (18, "الكهف"), (19, "مريم"), (20, "طه"),
    (21, "الأنبياء"), (22, "الحج"), (23, "المؤمنون"), (24, "النور"), (25, "الفرقان"),
    (26, "الشعراء"), (27, "النمل"), (28, "القصص"), (29, "العنكبوت"), (30, "الروم"),
    (31, "لقمان"), (32, "السجدة"), (33, "الأحزاب"), (34, "سبأ"), (35, "فاطر"),
    (36, "يس"), (37, "الصافات"), (38, "ص"), (39, "الزمر"), (40, "غافر"),
    (41, "فصلت"), (42, "الشورى"), (43, "الزخرف"), (44, "الدخان"), (45, "الجاثية"),
    (46, "الأحقاف"), (47, "محمد"), (48, "الفتح"), (49, "الحجرات"), (50, "ق"),
    (51, "الذاريات"), (52, "الطور"), (53, "النجم"), (54, "القمر"), (55, "الرحمن"),
    (56, "الواقعة"), (57, "الحديد"), (58, "المجادلة"), (59, "الحشر"), (60, "الممتحنة"),
    (61, "الصف"), (62, "الجمعة"), (63, "المنافقون"), (64, "التغابن"), (65, "الطلاق"),
    (66, "التحريم"), (67, "الملك"), (68, "القلم"), (69, "الحاقة"), (70, "المعارج"),
    (71, "نوح"), (72, "الجن"), (73, "المزمل"), (74, "المدثر"), (75, "القيامة"),
    (76, "الإنسان"), (77, "المرسلات"), (78, "النبأ"), (79, "النازعات"), (80, "عبس"),
    (81, "التكوير"), (82, "الانفطار"), (83, "المطففين"), (84, "الانشقاق"), (85, "البروج"),
    (86, "الطارق"), (87, "الأعلى"), (88, "الغاشية"), (89, "الفجر"), (90, "البلد"),
    (91, "الشمس"), (92, "الليل"), (93, "الضحى"), (94, "الشرح"), (95, "التين"),
    (96, "العلق"), (97, "القدر"), (98, "البينة"), (99, "الزلزلة"), (100, "العاديات"),
    (101, "القارعة"), (102, "التكاثر"), (103, "العصر"), (104, "الهمزة"), (105, "الفيل"),
    (106, "قريش"), (107, "الماعون"), (108, "الكوثر"), (109, "الكافرون"), (110, "النصر"),
    (111, "المسد"), (112, "الإخلاص"), (113, "الفلق"), (114, "الناس"),
]

PERSON_AUTHOR_ALIASES: dict[str, list[str]] = {
    "shaarawy": ["الشعراوي", "محمد متولي الشعراوي"],
    "bouti": ["محمد سعيد البوطي", "محمد سعيد رمضان البوطي"],
    "samarrai": ["فاضل صالح السامرائي", "فاضل السامرائي"],
    "dedew": ["محمد الحسن الددو الشنقيطي", "محمد الحسن الددو"],
    "itr": ["نور الدين عتر"],
    "abughuddah": ["عبد الفتاح أبو غدة"],
    "zuhayli": ["وهبة الزحيلي"],
    "ibnashur": ["ابن عاشور", "محمد الطاهر بن عاشور"],
    "suyuti": ["الجلال السيوطي", "جلال الدين السيوطي"],
    "shatibi": ["الشاطبي الأصولي النحوي", "أبو إسحاق الشاطبي"],
    "ghazali": ["أبو حامد الغزالي"],
    "nawawi": ["النووي", "محيي الدين يحيى بن شرف النووي"],
    "omari": ["علي محمود العمري"],
    "bardoni": ["محمد البردوني الحسيمي", "محمد البردوني"],
    "sariri": ["مولود السريري"],
    "sayed": ["أحمد السيد"],
    "hashemi": ["عبد الرحمن ذاكر الهاشمي", "ذاكر الهاشمي"],
    "ayman": ["أيمن عبد الرحيم"],
}

_SHAMELA_BOOKS_CACHE: list[dict[str, Any]] | None = None
_SHAMELA_PHRASE_INDEX_CACHE: dict[str, tuple[tuple[int, int, int], dict[str, Any], str]] | None = None

# Generic Islamic topic names that must NOT auto-match standalone Shamela pamphlets without explicit author/matn context
SHAMELA_GENERIC_TOPIC_STOPLIST: set[str] = {
    normalize_arabic(w)
    for w in [
        "الايمان", "التوحيد", "العقيده", "العقيده الاسلاميه", "الفقه", "الفقه الاسلامي",
        "قواعد الفقه", "قواعد الفقه الاسلامي", "التفسير", "الحديث", "السنه", "السنه النبويه",
        "شرح السنه النبويه", "السيره", "السيره النبويه", "الهجره النبويه", "الفتاوي", "المحاضرات",
        "الخطب", "خطبه الجمعه", "خطب الجمعه", "الدعاء", "الذكر", "الاداب", "الاخلاق", "الزهد",
        "الرقائق", "العلم", "فضل العلم", "ادب الطلب", "اداب طالب العلم", "النحو", "الصرف",
        "البلاغه", "المنطق", "الاصول", "اصول الفقه", "في اصول الفقه", "القواعد", "القواعد الفقهيه",
        "الوصايا", "الرساله", "المقدمه", "الامالي", "الفوائد", "المجالس", "الفتن", "الملاحم",
        "الجهاد", "الصلاه", "صلاه التراويح", "صلاه القيام", "صلاه الجماعه", "الصيام", "احكام الصيام",
        "الزكاه", "الحج", "احكام الحج والعمره", "النكاح", "البيوع", "المعاملات", "فقه المعاملات",
        "المواريث", "الفرائض", "علم الفرائض", "القضاء", "الشهادات", "الحدود", "الاعتصام", "البدع",
        "التوبه", "الصبر", "الشكر", "اليقين", "التوكل", "المحبه", "الخوف", "الرجاء", "الورع",
        "الاخلاص", "النيه", "الارشاد", "التبصره", "التذكره", "النصيحه", "الموعظه", "البيان",
        "علم البيان", "علم المعاني", "علم البديع", "علم الصرف", "علم النحو", "علم المنطق",
        "علم الكلام", "علم الاصول", "البرهان", "الايضاح", "التمهيد", "التقريب", "التحرير",
        "التنقيح", "التلخيص", "المنتخب", "المختصر", "الجامع", "الكافي", "الشافي", "الوافي",
        "المغني", "المجموع", "الحاوي", "المبسوط", "المحيط", "الذخيره", "المعونه", "المدخل",
        "الاشراف", "الانصاف", "الانتصار", "الرد", "المسائل", "الاجوبه", "الاسئله والاجوبه",
        "النوازل", "الاحكام", "تفسير القران", "تفسير القران العظيم", "تفسير القران الكريم",
        "علوم القران", "علوم القران الكريم", "علوم الحديث", "مصطلح الحديث", "مقاصد الشريعه",
        "تاريخ الاسلام", "تاريخ التشريع الاسلامي", "قصص الانبياء", "القصص القراني", "فضائل الصحابه",
        "سير الصحابه", "حقوق الانسان", "حقوق الانسان في الاسلام", "الجنه والنار", "المدائح النبويه",
        "شرح المدائح النبويه", "اسماء الله الحسني", "شرح اسماء الله الحسني", "علو الهمه",
        "بدر الكبري", "غزوه بدر الكبري", "الايات البينات", "السراج المنير", "الامام مالك",
        "الفكر العربي", "منهج الدعوه", "السياسه الشرعيه", "فقه عمل اليوم والليله", "عمل اليوم والليله",
        "اعجاز القران", "اعجاز القران الكريم", "احباب الله", "اولياء الله", "محبه الرسول",
        "محمد صلي الله عليه وسلم", "رسول الله صلي الله عليه وسلم", "حقيقه التوحيد", "شعب الايمان",
        "منازل الاخره", "اهوال القبور", "اشراط الساعه", "علامات الساعه", "احاديث الفتن",
        "الفتن والملاحم", "الاسراء والمعراج", "المولد النبوي", "اصول الدين", "فلسفه الدين",
        "اعلام النبلاء", "الدرر السنيه", "الفتاوي الكبري", "السنن الكبري", "السنن الصغري",
    ]
}

SHAMELA_BOOK_CONTEXT_MARKERS = (
    "شرح", "كتاب", "متن", "منظومه", "نظم", "رساله", "قراءه", "مدارسه",
    "حاشيه", "تعليق", "مختصر", "تهذيب", "مقاصد", "دوره", "مباحث",
    "صرف", "نحو", "بلاغه", "منطق", "اصول",
)


def load_shamela_books_index(shamela_db_dir: str | Path | None = None) -> list[dict[str, Any]]:
    """
    Load the 8,589-book Shamela4 index from `shamela4_books_index.json.gz` (or scan `shamela_db_dir`
    if an explicit directory is provided).
    """
    global _SHAMELA_BOOKS_CACHE
    if shamela_db_dir is None and _SHAMELA_BOOKS_CACHE is not None:
        return _SHAMELA_BOOKS_CACHE

    gz_path = Path(__file__).resolve().parent / "shamela4_books_index.json.gz"
    if shamela_db_dir is None and gz_path.exists():
        try:
            with gzip.open(gz_path, "rt", encoding="utf-8") as f:
                _SHAMELA_BOOKS_CACHE = json.load(f)
            return _SHAMELA_BOOKS_CACHE
        except Exception:
            pass

    db_root = Path(shamela_db_dir) if shamela_db_dir else Path("/Users/macm1pro/REPOS/swe/Shamela4_Full_DB")
    if db_root.exists():
        entries: list[dict[str, Any]] = []
        for mf in sorted(db_root.glob("*/*/book_metadata.json")):
            try:
                d = json.loads(mf.read_text(encoding="utf-8"))
                bid = d.get("shamela_id") or d.get("book_id")
                title = (d.get("title_ar") or "").strip()
                if bid and title:
                    entries.append({
                        "id": int(bid),
                        "t": title,
                        "a": (d.get("main_author_name_ar") or "").strip(),
                        "c": (d.get("category_name_ar") or "").strip(),
                        "d": d.get("main_author_death_hijri"),
                    })
            except Exception:
                continue
        if shamela_db_dir is None:
            _SHAMELA_BOOKS_CACHE = entries
        return entries

    return []


def _build_shamela_phrase_index(
    shamela_db_dir: str | Path | None = None,
) -> dict[str, tuple[tuple[int, int, int], dict[str, Any], str]]:
    """
    Build and cache a fast O(1) phrase lookup index over the 8,589 books in Shamela4,
    mapping normalized book title phrases (full titles, matn stems before `في`/`شرح`/`على`,
    and classical author-paired titles like `تمهيد الإسنوي`) to `(rank, book_entry, clean_title)`.
    """
    global _SHAMELA_PHRASE_INDEX_CACHE
    if shamela_db_dir is None and _SHAMELA_PHRASE_INDEX_CACHE is not None:
        return _SHAMELA_PHRASE_INDEX_CACHE

    shamela = load_shamela_books_index(shamela_db_dir)
    phrase_map: dict[str, tuple[tuple[int, int, int], dict[str, Any], str]] = {}

    for b in shamela:
        raw_t = b.get("t") or ""
        author = b.get("a") or ""
        death = b.get("d") or 99999
        cat = b.get("c") or "علوم شرعية"
        if cat == "كتب عامة" and death == 99999:
            continue

        parts = re.split(
            r"\s*=\s*|\s*-\s*(?=(?:ط|ت|جـ|ضمن|دراسة|تحقيق|بإشراف|كتاب|محاضرات)\b)|\s+-\s+",
            raw_t,
        )
        base_t = re.sub(r"\s*[\(\[«].*?[\)\]»]", "", parts[0]).strip()
        if not base_t:
            continue

        cands: list[tuple[str, bool]] = [(base_t, True)]
        stripped = re.sub(r"^(?:كتاب|متن|منظومة|نظم|رسالة|شرح|حاشية|مختصر)\s+", "", base_t).strip()
        if stripped != base_t:
            cands.append((stripped, True))

        if death <= 1445:
            for delim in (" في ", " على ", " عن ", " إلى ", " بين ", " شرح ", " لشرح ", " بشرح "):
                if delim in base_t:
                    bf = base_t.split(delim)[0].strip()
                    cands.append((bf, False))
                    sbf = re.sub(r"^(?:كتاب|متن|منظومة|نظم|رسالة|شرح|حاشية|مختصر)\s+", "", bf).strip()
                    if sbf != bf:
                        cands.append((sbf, False))
                    bf_words = bf.split()
                    if len(bf_words) == 4 and bf_words[2].startswith("و"):
                        cands.append((f"{bf_words[0]} {bf_words[1]}", False))
            bt_words = base_t.split()
            if len(bt_words) == 4 and bt_words[2].startswith("و"):
                cands.append((f"{bt_words[0]} {bt_words[1]}", False))

        if death <= 1390 and author:
            norm_a = normalize_arabic(author)
            a_words = norm_a.split()
            short_a = a_words[-1] if a_words else ""
            head_w = base_t.split(" في ")[0].strip()
            if len(head_w.split()) == 1 and head_w.startswith("ال") and len(short_a) >= 4:
                cands.append((f"{head_w[2:]} {author}", True))
                cands.append((f"{head_w} ل{author}", True))

        for c_str, is_full in cands:
            nc = normalize_arabic(c_str)
            if not nc or nc in SHAMELA_GENERIC_TOPIC_STOPLIST:
                continue
            words = nc.split()
            if len(words) < 2 or len(nc) < 9:
                continue
            if words[0] in (
                "دروس", "محاضرات", "سلسله", "برنامج", "مقتطفات", "لقاء", "ندوه",
                "مؤتمر", "ملتقي", "حوار", "فتاوي", "اسئله", "تاريخ", "قصه",
                "موقف", "منهج", "اثر", "مكانه", "رحله", "موسم", "مجلس", "مجالس",
            ):
                continue
            if death == 99999 and (len(words) < 3 or len(nc) < 14):
                continue
            rank = (1 if is_full else 0, -death, len(nc))
            prev = phrase_map.get(nc)
            if prev is None or rank > prev[0]:
                phrase_map[nc] = (rank, b, base_t)

    if shamela_db_dir is None:
        _SHAMELA_PHRASE_INDEX_CACHE = phrase_map
    return phrase_map


def _word_boundary_match(needle_norm: str, haystack_norm: str) -> bool:
    """
    Check if normalized phrase `needle_norm` appears on Arabic word boundaries inside `haystack_norm`,
    allowing standard attached Arabic proclitics (`و`, `ف`, `ب`, `ك`, `ل`, `لل`) for multi-letter phrases
    (e.g., `لقطر الندى`, `للقطر`, `بشرح`, `للألفية`).
    """
    if not needle_norm or not haystack_norm:
        return False
    b_left = r"(?:^|[\s/:|\-–—_(\[\{«\"'،؛,.؟!])"
    b_right = r"(?:$|[\s/:|\-–—_)\]\}\»\"'،؛,.؟!])"
    if len(needle_norm) >= 5:
        variants = [re.escape(needle_norm)]
        if needle_norm.startswith("ال") and len(needle_norm) >= 6:
            # Handle Arabic orthography where لـ + الـ becomes للـ (e.g. القطر -> للقطر)
            variants.append("لل" + re.escape(needle_norm[2:]))
        alt_pat = "|".join(variants)
        pattern = rf"{b_left}(?:و|ف|ب|ك|ل|وب|ول|فل|فب)?(?:{alt_pat}){b_right}"
    else:
        pattern = rf"{b_left}{re.escape(needle_norm)}{b_right}"
    return bool(re.search(pattern, haystack_norm))


def _is_author_match(sheikh_name: str, author_name: str, person_id: str | None = None) -> bool:
    """Check if `author_name` matches the scholar `sheikh_name` / `person_id`."""
    norm_person = normalize_arabic(sheikh_name)
    norm_author = normalize_arabic(author_name)
    if not norm_person or not norm_author:
        return False
    if norm_person == norm_author:
        return True
    if len(norm_author) >= 7 and (
        _word_boundary_match(norm_author, norm_person) or _word_boundary_match(norm_person, norm_author)
    ):
        return True

    pid = person_id or normalize_person_id(sheikh_name)
    for alias in PERSON_AUTHOR_ALIASES.get(pid, []):
        nalias = normalize_arabic(alias)
        if nalias and (nalias == norm_author or (len(nalias) >= 7 and _word_boundary_match(nalias, norm_author))):
            return True
    return False


def find_shamela_authored_books(
    sheikh_name: str,
    person_id: str | None = None,
    shamela_db_dir: str | Path | None = None,
    max_books: int = 25,
) -> list[dict[str, Any]]:
    """Discover books authored by `sheikh_name` from the Shamela4 database index."""
    shamela_books = load_shamela_books_index(shamela_db_dir)
    if not shamela_books:
        return []

    pid = person_id or normalize_person_id(sheikh_name)
    matched_books: list[dict[str, Any]] = []
    seen_base_titles: set[str] = set()

    for b in shamela_books:
        author = b.get("a") or ""
        if not _is_author_match(sheikh_name, author, person_id=pid):
            continue
        raw_title = (b.get("t") or "").strip()
        if not raw_title:
            continue
        # Clean edition suffix like ' - كتاب' or ' - محاضرات' or ' - ت فلان' for deduplication
        base_title = re.sub(r"\s+-\s+(?:كتاب|محاضرات|محاضرة|ت\s+.*)$", "", raw_title).strip()
        norm_base = normalize_arabic(base_title)
        if norm_base in seen_base_titles:
            continue
        seen_base_titles.add(norm_base)
        matched_books.append({
            "book_id": f"shamela:{b['id']}",
            "title": base_title,
            "author": author,
            "science": b.get("c") or "علوم شرعية",
            "source": "shamela4_db",
            "is_authored_by_person": True,
            "is_explained_by_person": False,
            "matched_playlists": [],
        })
        if len(matched_books) >= max_books:
            break

    return matched_books


def match_series_to_shamela_index(
    series_title: str,
    video_titles: list[str] | None = None,
    shamela_db_dir: str | Path | None = None,
) -> dict[str, Any] | None:
    """
    Automatic Layer-2 Series-to-Book Matcher against the 8,589 books in `shamela4_books_index.json.gz`.
    Uses O(1) n-gram + proclitic hash-table lookup with strict generic-topic filtering so classical and
    established books not listed in `MATN_KNOWLEDGE_BASE` (e.g. `شذا العرف في فن الصرف`, `جواهر البلاغة`,
    `أصول الشاشي`, `تمهيد الإسنوي`, `معيار العلم`, `مدارج السالكين`, `روضة الناظر`, `منهاج الطالبين`,
    `نيل الأوطار`, `سبل السلام`, `كشاف القناع`, `أضواء البيان`, `مفتاح العلوم`) are matched automatically.
    """
    phrase_map = _build_shamela_phrase_index(shamela_db_dir)
    if not phrase_map:
        return None

    def _find_best_in_text(norm_text: str, require_book_marker: bool = False) -> tuple[str, dict[str, Any], str] | None:
        if not norm_text:
            return None
        if require_book_marker and not any(m in norm_text for m in SHAMELA_BOOK_CONTEXT_MARKERS):
            return None
        tokens = [
            t for t in re.split(r"[\s/:|\-–—_(\[\{«\"'،؛,.؟!)\]\}\»]+", norm_text) if t
        ]
        n_tok = len(tokens)
        best: tuple[str, dict[str, Any], str] | None = None
        for i in range(n_tok):
            first_tok = tokens[i]
            first_variants = [first_tok]
            if len(first_tok) >= 4:
                if first_tok.startswith("لل") and len(first_tok) >= 5:
                    first_variants.append("ال" + first_tok[2:])
                for pfx in ("وب", "ول", "فل", "فب", "و", "ف", "ب", "ك", "ل"):
                    if first_tok.startswith(pfx) and len(first_tok) - len(pfx) >= 3:
                        rem = first_tok[len(pfx):]
                        first_variants.append(rem)
                        if rem.startswith("لل") and len(rem) >= 5:
                            first_variants.append("ال" + rem[2:])
            for j in range(i + 2, min(n_tok + 1, i + 9)):
                tail_str = " ".join(tokens[i + 1 : j])
                for fv in first_variants:
                    cand = f"{fv} {tail_str}"
                    hit = phrase_map.get(cand)
                    if hit is not None:
                        _, b_entry, clean_t = hit
                        if (b_entry.get("d") or 99999) == 99999 and not any(
                            m in norm_text for m in SHAMELA_BOOK_CONTEXT_MARKERS
                        ):
                            continue
                        if best is None or len(cand) > len(best[0]):
                            best = (cand, b_entry, clean_t)
        return best

    norm_series = normalize_arabic(series_title)
    series_hit = _find_best_in_text(norm_series, require_book_marker=False)
    if series_hit is not None:
        cand_key, b_entry, clean_t = series_hit
        return {
            "book_id": f"shamela:{b_entry['id']}",
            "title": clean_t,
            "author": b_entry.get("a") or "",
            "science": b_entry.get("c") or "علوم شرعية",
            "confidence": round(0.91 + min(0.04, len(cand_key) / 1000.0), 2),
        }

    # Check sample video titles only when they explicitly state `شرح كتاب ...` / `قراءة كتاب ...`
    # and the series title is not a general tour/conference bucket
    if video_titles and not any(w in norm_series for w in ("رحله", "مؤتمر", "ملتقي", "مقتطفات", "مقاطع")):
        v_norm = normalize_arabic(video_titles[0] or "")
        if re.search(r"(?:شرح|قراءه|مدارسه|درس في)\s+كتاب", v_norm):
            v_hit = _find_best_in_text(v_norm, require_book_marker=True)
            if v_hit is not None:
                cand_key, b_entry, clean_t = v_hit
                return {
                    "book_id": f"shamela:{b_entry['id']}",
                    "title": clean_t,
                    "author": b_entry.get("a") or "",
                    "science": b_entry.get("c") or "علوم شرعية",
                    "confidence": 0.87,
                }

    return None


def match_quran_tafsir_series(
    series_title: str,
    video_titles: list[str] | None = None,
) -> dict[str, Any] | None:
    """
    Match Quran Surah Tafsir / Tadabbur / Bayan playlists (e.g. `تفسير سورة البقرة`,
    `فسيرسورة السجدة`, `سورة البقرة` with videos `تفسير سورة البقرة`)
    with strict word-boundary checks so `الحج` never confuses with `الحجر` and single-letter
    surahs (`ص`, `ق`) require explicit `سورة ص` / `سورة ق`.
    """
    norm_series = re.sub(r"(?:تفسير|فسير)سوره\b", "تفسير سوره", normalize_arabic(series_title))
    norm_vids = [
        re.sub(r"(?:تفسير|فسير)سوره\b", "تفسير سوره", normalize_arabic(t))
        for t in (video_titles or [])[:6]
        if t
    ]
    sample_videos = " | ".join(norm_vids)
    combined = f"{norm_series} | {sample_videos}"

    # Require explicit tafsir/tadabbur/bayan/surah indicator in either series title or video titles
    has_tafsir_context = any(
        w in combined
        for w in ("تفسير", "تدبر", "لمسات بيانيه", "خواطر", "سوره ", "مقاصد السور")
    )
    if not has_tafsir_context:
        return None

    for s_num, s_name in QURAN_SURAHS:
        ns_name = normalize_arabic(s_name)
        explicit_phrase = f"سوره {ns_name}"
        if _word_boundary_match(explicit_phrase, norm_series):
            return {
                "book_id": f"tafsir:surah_{s_num:03d}",
                "title": f"تفسير سورة {s_name}",
                "author": "تفسير القرآن الكريم",
                "science": "التفسير وعلوم القرآن",
                "confidence": 0.96,
            }
        if _word_boundary_match(explicit_phrase, sample_videos) and (
            _word_boundary_match(explicit_phrase, norm_series)
            or (len(ns_name) >= 3 and _word_boundary_match(ns_name, norm_series))
        ):
            return {
                "book_id": f"tafsir:surah_{s_num:03d}",
                "title": f"تفسير سورة {s_name}",
                "author": "تفسير القرآن الكريم",
                "science": "التفسير وعلوم القرآن",
                "confidence": 0.92,
            }

    # Check if majority of sampled videos explicitly explain the same surah inside a dedicated tafsir/fajr lesson series
    if norm_vids and any(w in norm_series for w in ("تفسير", "درس الفجر", "مجالس قرانيه")):
        surah_counts: dict[tuple[int, str], int] = {}
        for nv in norm_vids:
            if "تفسير" not in nv and "تدبر" not in nv:
                continue
            for s_num, s_name in QURAN_SURAHS:
                ns_name = normalize_arabic(s_name)
                if _word_boundary_match(f"سوره {ns_name}", nv):
                    surah_counts[(s_num, s_name)] = surah_counts.get((s_num, s_name), 0) + 1
        if len(surah_counts) == 1:
            (s_num, s_name), cnt = next(iter(surah_counts.items()))
            if cnt >= max(1, (len(norm_vids) + 1) // 2):
                return {
                    "book_id": f"tafsir:surah_{s_num:03d}",
                    "title": f"تفسير سورة {s_name}",
                    "author": "تفسير القرآن الكريم",
                    "science": "التفسير وعلوم القرآن",
                    "confidence": 0.90,
                }

    for juz_id, juz_title, juz_kw in [
        ("tafsir:juz_amma", "تفسير جزء عم", "جزء عم"),
        ("tafsir:juz_tabarak", "تفسير جزء تبارك", "جزء تبارك"),
        ("tafsir:juz_qad_samia", "تفسير جزء قد سمع", "جزء قد سمع"),
    ]:
        if _word_boundary_match(normalize_arabic(juz_kw), norm_series):
            return {
                "book_id": juz_id,
                "title": juz_title,
                "author": "تفسير القرآن الكريم",
                "science": "التفسير وعلوم القرآن",
                "confidence": 0.95,
            }

    if any(
        _word_boundary_match(normalize_arabic(p), norm_series)
        for p in (
            "تفسير القرآن الكريم",
            "تفسير قصار السور",
            "تفسير سريع للقرآن الكريم",
            "مجالس التفسير",
            "درس التفسير",
            "تفسير وتدبر للقرآن الكريم",
            "الطريقة المثلى لتفسير القرآن",
            "مقاصد السور",
        )
    ):
        return {
            "book_id": "tafsir:quran_karim",
            "title": "تفسير القرآن الكريم",
            "author": "تفسير القرآن الكريم",
            "science": "التفسير وعلوم القرآن",
            "confidence": 0.94,
        }

    return None


def match_title_to_book(
    series_title: str,
    video_titles: list[str] | None = None,
    extra_books: list[dict[str, Any]] | None = None,
    shamela_db_dir: str | Path | None = None,
) -> dict[str, Any] | None:
    """
    Match a playlist/series title (and sample video titles) across 3 deterministic layers:
      Layer 1: Curated `MATN_KNOWLEDGE_BASE` (+ optional `extra_books`) with science anti-confusion rules.
      Layer 2: `match_quran_tafsir_series` (114 Quran Surahs & Juzs with strict word boundaries).
      Layer 3: `match_series_to_shamela_index` (8,589 books in `shamela4_books_index.json.gz`).
    """
    norm_series = normalize_arabic(series_title)
    sample_videos = " | ".join(normalize_arabic(t) for t in (video_titles or [])[:8])
    combined = f"{norm_series} | {sample_videos}"

    catalog = list(MATN_KNOWLEDGE_BASE)
    if extra_books:
        for eb in extra_books:
            b_title = eb.get("title") or ""
            if b_title:
                catalog.append({
                    "book_id": str(eb.get("book_id") or eb.get("id") or f"custom:{normalize_person_id(b_title)}"),
                    "title": b_title,
                    "author": eb.get("author") or "",
                    "science": eb.get("science") or "علوم شرعية",
                    "keywords": eb.get("keywords") or [b_title],
                    "exclude_keywords": eb.get("exclude_keywords") or [],
                })

    best_match: dict[str, Any] | None = None
    best_score = 0.0

    for entry in catalog:
        excl = entry.get("exclude_keywords") or []
        if any(_word_boundary_match(normalize_arabic(ex), combined) for ex in excl):
            continue

        for kw in entry.get("keywords", []):
            nkw = normalize_arabic(kw)
            if not nkw:
                continue
            if _word_boundary_match(nkw, norm_series):
                score = 0.96 + min(0.03, len(nkw) / 1000.0)
                if score > best_score:
                    best_score = score
                    best_match = {
                        "book_id": entry["book_id"],
                        "title": entry["title"],
                        "author": entry["author"],
                        "science": entry["science"],
                        "confidence": round(score, 2),
                    }
            elif _word_boundary_match(nkw, sample_videos):
                score = 0.88 + min(0.03, len(nkw) / 1000.0)
                if score > best_score:
                    best_score = score
                    best_match = {
                        "book_id": entry["book_id"],
                        "title": entry["title"],
                        "author": entry["author"],
                        "science": entry["science"],
                        "confidence": round(score, 2),
                    }

    if best_match is not None:
        return best_match

    tafsir_match = match_quran_tafsir_series(series_title, video_titles)
    if tafsir_match is not None:
        return tafsir_match

    return match_series_to_shamela_index(series_title, video_titles, shamela_db_dir=shamela_db_dir)


def discover_person_books(
    sheikh_name: str,
    playlists: list[dict[str, Any]],
    archive_items: list[dict[str, Any]],
    extra_books: list[dict[str, Any]] | None = None,
    person_id: str | None = None,
    shamela_db_dir: str | Path | None = None,
) -> list[dict[str, Any]]:
    """
    Build the unified `books` list for `<person_id>_raw.json`, combining:
    1. Books authored by `sheikh_name` (from `MATN_KNOWLEDGE_BASE`, Shamela4 DB index, or `--books-json`).
    2. Classical matns / books explained by `sheikh_name` across playlists and Archive.org items.
    """
    pid_slug = person_id or normalize_person_id(sheikh_name)
    books_map: dict[str, dict[str, Any]] = {}

    # 1. Check catalog and Shamela4 index for books authored directly by the person
    shamela_authored = find_shamela_authored_books(
        sheikh_name=sheikh_name, person_id=pid_slug, shamela_db_dir=shamela_db_dir
    )
    all_candidates = list(MATN_KNOWLEDGE_BASE) + list(extra_books or []) + shamela_authored
    for b in all_candidates:
        b_id = str(b.get("book_id") or b.get("id") or "")
        b_title = b.get("title") or ""
        b_author = b.get("author") or ""
        if not b_id or not b_title:
            continue
        is_authored = bool(
            b.get("is_authored_by_person")
            or _is_author_match(sheikh_name, b_author, person_id=pid_slug)
        )
        if is_authored:
            books_map[b_id] = {
                "book_id": b_id,
                "title": b_title,
                "author": b_author,
                "science": b.get("science") or "علوم شرعية",
                "source": b.get("source") or "books_catalog",
                "is_authored_by_person": True,
                "is_explained_by_person": False,
                "matched_playlists": [],
            }

    # 2. Match playlists / series to books (excluding unclassified catch-all buckets)
    for pl in playlists:
        pid = pl.get("playlist_id") or pl.get("id") or ""
        is_uncl = pl.get("yt_playlist_id") is None or "__unclassified" in str(pid)
        if is_uncl:
            pl["matched_book"] = None
            continue
        v_titles = [v.get("title", "") for v in pl.get("videos", [])]
        matched = pl.get("matched_book") or match_title_to_book(
            pl.get("title", ""), v_titles, extra_books=extra_books, shamela_db_dir=shamela_db_dir
        )
        if matched:
            pl["matched_book"] = matched
            b_id = matched["book_id"]
            b_author = matched.get("author") or ""
            is_authored = _is_author_match(sheikh_name, b_author, person_id=pid_slug)
            if b_id not in books_map:
                books_map[b_id] = {
                    "book_id": b_id,
                    "title": matched["title"],
                    "author": b_author,
                    "science": matched.get("science") or "علوم شرعية",
                    "source": "shamela4_db" if b_id.startswith("shamela:") else "series_matn_matcher",
                    "is_authored_by_person": is_authored,
                    "is_explained_by_person": True,
                    "matched_playlists": [],
                }
            else:
                books_map[b_id]["is_explained_by_person"] = True
            pid = pl.get("playlist_id") or pl.get("id")
            if pid and pid not in books_map[b_id]["matched_playlists"]:
                books_map[b_id]["matched_playlists"].append(pid)

    # 3. Match Archive.org items to books
    for item in archive_items:
        f_titles = [f.get("title", "") for f in item.get("files", [])]
        matched = item.get("matched_book") or match_title_to_book(
            item.get("title", ""), f_titles, extra_books=extra_books, shamela_db_dir=shamela_db_dir
        )
        if matched:
            item["matched_book"] = matched
            b_id = matched["book_id"]
            b_author = matched.get("author") or ""
            is_authored = _is_author_match(sheikh_name, b_author, person_id=pid_slug)
            if b_id not in books_map:
                books_map[b_id] = {
                    "book_id": b_id,
                    "title": matched["title"],
                    "author": b_author,
                    "science": matched.get("science") or "علوم شرعية",
                    "source": "shamela4_db" if b_id.startswith("shamela:") else "archive_matn_matcher",
                    "is_authored_by_person": is_authored,
                    "is_explained_by_person": True,
                    "matched_playlists": [],
                }
            else:
                books_map[b_id]["is_explained_by_person"] = True
            arch_pid = item.get("linked_playlist_id") or f"archive__{item['item_id']}"
            if arch_pid not in books_map[b_id]["matched_playlists"]:
                books_map[b_id]["matched_playlists"].append(arch_pid)

    return list(books_map.values())


# ---------------------------------------------------------------------------
# 4. Archive.org AdvancedSearch & Metadata Harvesting Engine
# ---------------------------------------------------------------------------

AUDIO_EXT_PRIORITY: dict[str, int] = {
    ".mp3": 1,
    ".m4a": 2,
    ".flac": 3,
    ".opus": 4,
    ".aac": 5,
    ".ogg": 6,
    ".wav": 7,
    ".wma": 8,
    ".mp4": 9,
    ".m4v": 10,
    ".mkv": 11,
    ".webm": 12,
    ".avi": 13,
}


def _build_arabic_ordinals_list() -> list[tuple[str, int]]:
    """Build Arabic ordinal phrases (1..59) sorted by descending length so compound ordinals match first."""
    base_pairs: list[tuple[str, int]] = [
        ("الأول", 1), ("الاول", 1), ("الأولى", 1), ("الاولى", 1),
        ("الثاني", 2), ("الثانية", 2),
        ("الثالث", 3), ("الثالثة", 3),
        ("الرابع", 4), ("الرابعة", 4),
        ("الخامس", 5), ("الخامسة", 5),
        ("السادس", 6), ("السادسة", 6),
        ("السابع", 7), ("السابعة", 7),
        ("الثامن", 8), ("الثامنة", 8),
        ("التاسع", 9), ("التاسعة", 9),
        ("العاشر", 10), ("العاشرة", 10),
        ("الحادي عشر", 11), ("الحادية عشرة", 11),
        ("الثاني عشر", 12), ("الثانية عشرة", 12),
        ("الثالث عشر", 13), ("الثالثة عشرة", 13),
        ("الرابع عشر", 14), ("الرابعة عشرة", 14),
        ("الخامس عشر", 15), ("الخامسة عشرة", 15),
        ("السادس عشر", 16), ("السادسة عشرة", 16),
        ("السابع عشر", 17), ("السابعة عشرة", 17),
        ("الثامن عشر", 18), ("الثامنة عشرة", 18),
        ("التاسع عشر", 19), ("التاسعة عشرة", 19),
    ]
    units_for_compounds: list[tuple[list[str], int]] = [
        (["الحادي", "الواحد", "الحادية", "الواحدة"], 1),
        (["الثاني", "الثانية"], 2),
        (["الثالث", "الثالثة"], 3),
        (["الرابع", "الرابعة"], 4),
        (["الخامس", "الخامسة"], 5),
        (["السادس", "السادسة"], 6),
        (["السابع", "السابعة"], 7),
        (["الثامن", "الثامنة"], 8),
        (["التاسع", "التاسعة"], 9),
    ]
    tens_list: list[tuple[list[str], int]] = [
        (["العشرون", "العشرين"], 20),
        (["الثلاثون", "الثلاثين"], 30),
        (["الأربعون", "الاربعون", "الأربعين", "الاربعين"], 40),
        (["الخمسون", "الخمسين"], 50),
    ]
    for ten_forms, ten_val in tens_list:
        for tf in ten_forms:
            base_pairs.append((tf, ten_val))
            for unit_forms, unit_val in units_for_compounds:
                for uf in unit_forms:
                    base_pairs.append((f"{uf} و{tf}", ten_val + unit_val))
                    base_pairs.append((f"{uf} و {tf}", ten_val + unit_val))

    normalized_map: dict[str, int] = {}
    for phrase, num in base_pairs:
        np = normalize_arabic(phrase)
        if np:
            normalized_map[np] = num
    return sorted(normalized_map.items(), key=lambda kv: len(kv[0]), reverse=True)


ARABIC_ORDINAL_TO_EP_NUM: list[tuple[str, int]] = _build_arabic_ordinals_list()


def parse_archive_duration(length_val: Any) -> int:
    """Convert Archive.org `length` field ('7298.42' or '02:01:38' or '45:12') to integer seconds."""
    if length_val is None:
        return 0
    if isinstance(length_val, (int, float)):
        return max(0, int(round(float(length_val))))
    s = str(length_val).strip()
    if not s:
        return 0
    if ":" in s:
        parts = s.split(":")
        try:
            nums = [float(p) for p in parts]
            if len(nums) == 3:
                return max(0, int(round(nums[0] * 3600 + nums[1] * 60 + nums[2])))
            if len(nums) == 2:
                return max(0, int(round(nums[0] * 60 + nums[1])))
        except ValueError:
            return 0
    try:
        return max(0, int(round(float(s))))
    except ValueError:
        return 0


def extract_episode_num_from_text(text: str, item_title: str = "") -> int | None:
    """
    Extract an explicit episode/lesson number (`episode_num`) from an Archive.org filename stem
    or lesson title. Handles:
      - Pure numeric stems: `001` -> 1, `024` -> 24
      - Parenthesized episode numbers: `aqeeda (10)` -> 10, `aqeeda (2)` -> 2
      - Leading numbered prefixes: `01 - الدرس الأول` -> 1, `005_sharh` -> 5
      - Explicit Arabic lesson/session markers: `الدرس 14`, `المجلس (7)`, `الحلقة 03` -> 14, 7, 3
      - Trailing separated episode numbers: `Nafs-19` -> 19, `Nafs-001` -> 1, `sharh_waraqat_01` -> 1,
        `leqa2_eliman_16` -> 16 (ignores Arabizi digits embedded inside words like `leqa2` or `char7`)
      - Arabic ordinals (1..59): `المجلس الرابع والعشرون` -> 24, `المجلس الثاني عشر` -> 12, `المجلس الأول` -> 1
    """
    s = (text or "").strip()
    if not s:
        return None

    # 1. Pure digits (`001`, `24`)
    if s.isdigit():
        val = int(s)
        return val if 1 <= val <= 9999 else None

    # 2. Parenthesized or bracketed number (`aqeeda (10)`, `درس [05]`)
    m_paren = re.search(r"[\(\[\{]\s*(\d{1,4})\s*[\)\]\}]", s)
    if m_paren:
        val = int(m_paren.group(1))
        if 1 <= val <= 9999:
            return val

    # 3. Leading number followed by separator (`01 - ...`, `003_...`, `12. ...`)
    m_lead = re.match(r"^\s*(\d{1,4})\s*[-_\.\:\|\s]", s)
    if m_lead:
        val = int(m_lead.group(1))
        if 1 <= val <= 9999:
            return val

    # 4. Explicit Arabic lesson word + digits (`الدرس 12`, `المجلس 4`, `الحلقة 09`, `لقاء 16`)
    m_ar_ep = re.search(r"(?:الدرس|درس|المجلس|مجلس|الحلقة|حلقة|اللقاء|لقاء|الشريط|شريط)\s*[:\-_#\(]*\s*(\d{1,4})\b", s)
    if m_ar_ep:
        val = int(m_ar_ep.group(1))
        if 1 <= val <= 9999:
            return val

    # 5. Trailing number after separator (`Nafs-19`, `Nafs-001`, `sharh_waraqat_01`, `leqa2_eliman_16`)
    m_trail = re.search(r"[-_\s](\d{1,4})\s*$", s)
    if m_trail:
        val = int(m_trail.group(1))
        # Avoid mistaking Hijri/Gregorian years (e.g. 1444, 2021) for episode numbers
        if 1 <= val <= 999 and not (1400 <= val <= 1460 or 1970 <= val <= 2035):
            return val

    # 6. Arabic ordinals (`المجلس الأول`, `الدرس الثاني عشر`, `اللقاء الرابع والعشرون`)
    norm_s = normalize_arabic(s)
    for ord_phrase, ord_val in ARABIC_ORDINAL_TO_EP_NUM:
        if re.search(rf"(?:^|\s){re.escape(ord_phrase)}(?:\s|$)", norm_s):
            return ord_val

    return None


def extract_archive_episode_num(file_obj: dict[str, Any], stem: str, item_title: str = "") -> int | None:
    """
    Determine the canonical episode number for an Archive.org file object:
      1. From the filename stem (`003.mp3` -> 3, `aqeeda (10).mp3` -> 10, `Nafs-019.mp4` -> 19)
      2. From the file's `track` metadata (`track: "03"` or `"5/28"`)
      3. From the file's `title` metadata (`الدرس 24: ...`, `المجلس الأول ...`)
    Filename stem is checked BEFORE `title` so that sub-topic numbers inside ID3 titles
    (such as `003.mp3` having ID3 title `تتمة أوقات الصلاة 02`) never override the file's actual lesson number.
    """
    ep = extract_episode_num_from_text(stem, item_title=item_title)
    if ep is not None:
        return ep

    track_raw = str(file_obj.get("track") or "").strip()
    if track_raw:
        m_tr = re.match(r"^(\d{1,4})(?:/\d+)?$", track_raw)
        if m_tr:
            val = int(m_tr.group(1))
            if 1 <= val <= 9999:
                return val

    f_title = str(file_obj.get("title") or "").strip()
    if f_title:
        ep = extract_episode_num_from_text(f_title, item_title=item_title)
        if ep is not None:
            return ep

    return None


def normalize_archive_file_title(
    raw_title: str | None,
    stem: str,
    ep_num: int | None,
    pos: int,
    item_title: str,
) -> str:
    """
    Produce a clean, human-readable Arabic lesson title for an Archive.org file:
    - Filters out website/URL spam in ID3 `title` tags (e.g. `www.naseemalsham.com`, `http://...`).
    - Normalizes pure-numeric or Latin-transliterated stems (`001`, `aqeeda (10)`, `sharh_waraqat_01`, `Nafs-019`)
      into `الدرس <ep_num> | <item_title>`.
    - Preserves genuine descriptive Arabic titles (`الدرس 24: قاعدة الأمور تتبع مقاصدها`, `المجلس الأول من كتاب المقاصد`),
      and prepends `الدرس <ep_num>: ` when a descriptive Arabic title lacks the lesson number (`تتمة أوقات الصلاة 02`).
    """
    candidate = (raw_title or "").strip()
    # Reject URL/domain spam in ID3 tags
    if candidate and re.search(r"(?:https?://|www\.|\.(?:com|net|org|info|me)\b)", candidate, re.IGNORECASE):
        candidate = ""

    # Check if candidate has meaningful Arabic letters
    has_arabic = bool(re.search(r"[\u0600-\u06FF]", candidate))
    if not candidate or not has_arabic:
        stem_clean = stem.strip()
        if re.search(r"[\u0600-\u06FF]", stem_clean) and not stem_clean.isdigit():
            candidate = stem_clean
            has_arabic = True

    effective_ep = ep_num if ep_num is not None else pos
    if not has_arabic or candidate.isdigit():
        return f"الدرس {effective_ep} | {item_title}"

    # If the descriptive Arabic title doesn't already mention الدرس/المجلس/الحلقة/اللقاء and we know ep_num
    if ep_num is not None and not re.search(r"(?:الدرس|درس|المجلس|مجلس|الحلقة|حلقة|اللقاء|لقاء)", candidate):
        # Also check if candidate is identical to item_title
        if normalize_arabic(candidate) == normalize_arabic(item_title):
            return f"الدرس {ep_num} | {item_title}"
        return f"الدرس {ep_num}: {candidate}"

    return candidate


def parse_archive_metadata_payload(
    item_id: str,
    meta_payload: dict[str, Any],
    person_id: str,
    fallback_creator: str = "",
) -> dict[str, Any]:
    """
    Parse an Archive.org `/metadata/<item_id>` JSON payload:
    - Extracts item metadata (`title`, `creator`, `uploader`, `mediatype`, `date`).
    - Filters audio/video lecture files and deduplicates derivative formats by stem
      (`.mp3` preferred over `.ogg`, `.mp4` preferred over `.ogv`).
    - Extracts `episode_num` from filenames/tracks/titles and sorts lessons in natural numerical order
      (so `aqeeda (2).mp3` comes before `aqeeda (10).mp3`).
    - Cleans ID3 URL/website spam and normalizes raw numeric/Latin stems into clean Arabic titles.
    - Computes exact `dur_s` / `duration` and `direct_url` for each file.
    """
    meta = meta_payload.get("metadata") or {}
    raw_files = meta_payload.get("files") or []
    clean_item_slug = re.sub(r"[^A-Za-z0-9_]+", "_", item_id).strip("_")
    item_title = (meta.get("title") or item_id).strip()

    # Group audio/video candidates by stem so derivative .ogg/.ogv files don't duplicate original files
    by_stem: dict[str, list[tuple[int, dict[str, Any]]]] = {}
    for f in raw_files:
        fname = f.get("name") or ""
        if not fname or fname.startswith("__"):
            continue
        ext = os.path.splitext(fname)[1].lower()
        if ext not in AUDIO_EXT_PRIORITY:
            continue
        stem = os.path.splitext(fname)[0]
        prio = AUDIO_EXT_PRIORITY[ext]
        # Prefer 'original' source over 'derivative' for same or lower priority
        if f.get("source") == "derivative":
            prio += 20
        by_stem.setdefault(stem, []).append((prio, f))

    selected_with_ep: list[tuple[int, int, str, int | None, str, dict[str, Any]]] = []
    for stem, candidates in by_stem.items():
        best_f = sorted(candidates, key=lambda x: x[0])[0][1]
        base_stem = os.path.basename(stem)
        ep_num = extract_archive_episode_num(best_f, base_stem, item_title=item_title)
        selected_with_ep.append((
            0 if ep_num is not None else 1,
            ep_num if ep_num is not None else 0,
            stem.lower(),
            ep_num,
            base_stem,
            best_f,
        ))

    # Sort in natural episode order first, then stem lexicographically
    selected_with_ep.sort(key=lambda x: (x[0], x[1], x[2]))

    audio_entries: list[dict[str, Any]] = []
    total_dur = 0
    upload_date_raw = str(meta.get("date") or meta.get("publicdate") or "")
    upload_date = re.sub(r"[^\d]", "", upload_date_raw)[:8] or None

    for idx, (_, _, _, ep_num, base_stem, f) in enumerate(selected_with_ep, 1):
        fname = f["name"]
        dur_s = parse_archive_duration(f.get("length") or f.get("duration"))
        total_dur += dur_s
        f_title = normalize_archive_file_title(
            raw_title=f.get("title"),
            stem=base_stem,
            ep_num=ep_num,
            pos=idx,
            item_title=item_title,
        )
        direct_url = f"https://archive.org/download/{item_id}/{urllib.parse.quote(fname)}"
        ep_tag = ep_num if ep_num is not None else idx
        vid = f"archive__{person_id}__{clean_item_slug}__ep{ep_tag:03d}"
        size_val = int(f["size"]) if str(f.get("size", "")).isdigit() else 0

        audio_entries.append({
            "pos": idx,
            "episode_num": ep_num if ep_num is not None else idx,
            "name": fname,
            "title": f_title,
            "format": f.get("format") or os.path.splitext(fname)[1].lstrip(".").upper(),
            "dur_s": dur_s,
            "duration": dur_s,
            "size": size_val,
            "direct_url": direct_url,
            "vid": vid,
            "yt_id": vid,
            "upload_date": upload_date,
        })

    return {
        "item_id": item_id,
        "title": item_title,
        "creator": meta.get("creator") or fallback_creator,
        "uploader": meta.get("uploader") or "",
        "mediatype": meta.get("mediatype") or "audio",
        "upload_date": upload_date,
        "metadata_url": f"https://archive.org/metadata/{item_id}",
        "details_url": f"https://archive.org/details/{item_id}",
        "audio_files_count": len(audio_entries),
        "total_duration_s": total_dur,
        "matched_book": None,
        "files": audio_entries,
    }


def fetch_archive_item_metadata(item_id: str, timeout: int = 20) -> dict[str, Any] | None:
    """Fetch `https://archive.org/metadata/<item_id>` over HTTPS."""
    url = f"https://archive.org/metadata/{urllib.parse.quote(item_id)}"
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; PersonDiscoveryIntake/1.0)"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", errors="ignore"))
    except Exception as exc:
        sys.stderr.write(f"[WARN] Failed to fetch Archive.org metadata for {item_id}: {exc}\n")
        return None


def search_archive_org(
    sheikh_name: str,
    uploader: str | None = None,
    rows: int = 50,
    timeout: int = 20,
) -> list[str]:
    """Query Archive.org AdvancedSearch API for audio items matching the scholar's name or uploader."""
    queries = [f'(creator:("{sheikh_name}") OR title:("{sheikh_name}")) AND mediatype:(audio)']
    if uploader:
        queries.append(f'uploader:("{uploader}")')

    found_ids: list[str] = []
    seen: set[str] = set()
    for q in queries:
        params = urllib.parse.urlencode({
            "q": q,
            "fl[]": "identifier",
            "rows": str(rows),
            "page": "1",
            "output": "json",
        })
        url = f"https://archive.org/advancedsearch.php?{params}"
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 (compatible; PersonDiscoveryIntake/1.0)"},
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="ignore"))
            docs = data.get("response", {}).get("docs", [])
            for d in docs:
                ident = d.get("identifier")
                if ident and ident not in seen:
                    seen.add(ident)
                    found_ids.append(ident)
        except Exception as exc:
            sys.stderr.write(f"[WARN] Archive.org search failed for query {q}: {exc}\n")
    return found_ids


# ---------------------------------------------------------------------------
# 5. YouTube Discovery & Flat-Playlist Harvesting (`yt-dlp --flat-playlist -J`)
# ---------------------------------------------------------------------------

def run_yt_dlp_flat_json(url: str, timeout: int = 180) -> dict[str, Any] | None:
    """Execute `yt-dlp --flat-playlist -J <url>` and return parsed JSON object."""
    cmd = ["yt-dlp", "--flat-playlist", "-J", url]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if proc.returncode != 0 or not proc.stdout.strip():
            return None
        return json.loads(proc.stdout)
    except Exception as exc:
        sys.stderr.write(f"[WARN] yt-dlp failed on {url}: {exc}\n")
        return None


def parse_yt_dlp_playlist_dump(
    dump: dict[str, Any],
    default_source_type: str = "youtube_playlist",
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """
    Convert a `yt-dlp --flat-playlist -J` dump into a canonical playlist object and video entries.
    """
    pid = dump.get("id") or "unknown_playlist"
    ptitle = (dump.get("title") or pid).strip()
    purl = dump.get("webpage_url") or f"https://www.youtube.com/playlist?list={pid}"
    entries = dump.get("entries") or []

    videos: list[dict[str, Any]] = []
    for idx, ent in enumerate(entries, 1):
        if not isinstance(ent, dict):
            continue
        vid = ent.get("id") or ent.get("yt_id")
        if not vid:
            continue
        dur_raw = ent.get("duration") if ent.get("duration") is not None else ent.get("dur_s")
        dur_s = int(round(float(dur_raw))) if isinstance(dur_raw, (int, float)) else 0
        up_date = ent.get("upload_date")
        live_status = ent.get("live_status") or ""
        stype = (
            "youtube_stream"
            if live_status in ("was_live", "is_live") or default_source_type == "youtube_stream"
            else default_source_type
        )
        videos.append({
            "pos": idx,
            "vid": vid,
            "yt_id": vid,
            "title": (ent.get("title") or f"الدرس {idx}").strip(),
            "dur_s": dur_s,
            "duration": dur_s,
            "upload_date": up_date,
            "playlist_id": pid,
            "playlist_title": ptitle,
            "source_type": stype,
            "yt_url": ent.get("url") or f"https://www.youtube.com/watch?v={vid}",
        })

    playlist_obj = {
        "id": pid,
        "playlist_id": pid,
        "order_no": 1,
        "title": ptitle,
        "yt_playlist_id": None if pid.endswith("__unclassified") else pid,
        "url": purl,
        "source_type": default_source_type,
        "state": "completed",
        "expected_count": len(videos),
        "video_count": len(videos),
        "note": "تصنيف: شرح / سلسلة علمية",
        "matched_book": None,
        "videos": videos,
    }
    return playlist_obj, videos


# ---------------------------------------------------------------------------
# 6. Deduplication, Unification & `<person_id>_raw.json` Builder
# ---------------------------------------------------------------------------

SHARED_CHANNEL_PERSON_MARKERS: list[tuple[str, list[str]]] = [
    ("bardoni", ["البردوني", "إبراهيم البردوني", "ابراهيم البردوني"]),
    ("sariri", ["السريري", "أحمد السريري", "احمد السريري"]),
    ("kamali", ["الكملي", "سعيد الكملي"]),
    ("khudayr", ["الخضير", "عبد الكريم الخضير", "عبدالكريم الخضير"]),
    ("fawzan", ["الفوزان", "صالح الفوزان"]),
    ("shanqiti", ["المختار الشنقيطي", "محمد المختار الشنقيطي"]),
    ("dedew", ["الددو", "محمد الحسن الددو"]),
    ("bouti", ["البوطي", "رمضان البوطي"]),
    ("shaarawy", ["الشعراوي", "متولي الشعراوي"]),
    ("hussary", ["الحصري", "محمود خليل الحصري"]),
    ("samarrai", ["السامرائي", "فاضل السامرائي"]),
    ("roushdy", ["علاء حامد"]),
    ("khalil", ["خليل محمود"]),
    ("laban", ["أحمد لبن", "احمد لبن"]),
    ("said", ["محمد سيد حاج"]),
    ("ayman", ["أيمن عبد الرحيم", "ايمن عبد الرحيم", "أيمن عبدالرحيم"]),
    ("sayed", ["أحمد السيد", "احمد السيد"]),
]


def is_shared_channel_fixture(fixture_data: dict[str, Any]) -> bool:
    """Return True if the fixture represents a multi-scholar shared channel (e.g. tankert-shared)."""
    sh_id = str(fixture_data.get("sheikh_id") or "").strip().lower()
    ch_key = str(fixture_data.get("channel_key") or "").strip().lower()
    sh_name = str(fixture_data.get("sheikh_name") or "")
    if sh_id == "shared" or "shared" in ch_key:
        return True
    if "مشترك" in sh_name or ("السريري" in sh_name and "البردوني" in sh_name):
        return True
    return False


def attribute_shared_channel_owner(
    title: str,
    video_titles: list[str] | None = None,
    channel_key: str = "",
    default_owner: str | None = "sariri",
) -> str | None:
    """
    Determine which `person_id` owns a playlist or video inside a shared channel
    (such as `tankert-shared` / مدرسة تنكرت العتيقة shared between `sariri` and `bardoni`).
    """
    combined_title = normalize_arabic(title or "")
    for pid, markers in SHARED_CHANNEL_PERSON_MARKERS:
        for m in markers:
            if normalize_arabic(m) in combined_title:
                return pid

    if video_titles:
        counts: dict[str, int] = {}
        for vt in video_titles:
            vt_norm = normalize_arabic(vt or "")
            for pid, markers in SHARED_CHANNEL_PERSON_MARKERS:
                if any(normalize_arabic(m) in vt_norm for m in markers):
                    counts[pid] = counts.get(pid, 0) + 1
        if counts:
            return max(counts.items(), key=lambda kv: kv[1])[0]

    if "tankert" in channel_key.lower() or default_owner:
        return default_owner
    return None


def ingest_offline_fixture(
    fixture_data: dict[str, Any],
    person_id: str,
    sheikh_name: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """
    Ingest an existing `<sheikh>_raw.json`, `full_channels/<channel>.json`, `raw_playlists/<id>.json`,
    or composite test fixture into normalized `(channels, raw_playlists, archive_items, pdf_links)`.
    Automatically filters shared channels (e.g. `tankert-shared.json`) by scholar attribution.
    """
    channels: list[dict[str, Any]] = []
    playlists: list[dict[str, Any]] = []
    archive_items: list[dict[str, Any]] = []
    pdf_links: list[dict[str, Any]] = []

    shared_mode = is_shared_channel_fixture(fixture_data)
    ch_key_raw = str(fixture_data.get("channel_key") or "")

    # Build lookup of video durations/dates from `unique_videos` or `videos` if present
    v_meta_lookup: dict[str, dict[str, Any]] = {}
    for uv in fixture_data.get("unique_videos") or fixture_data.get("videos") or []:
        vid = uv.get("yt_id") or uv.get("vid")
        if vid:
            v_meta_lookup[vid] = uv

    # 1. Channels
    if "channels" in fixture_data and isinstance(fixture_data["channels"], list):
        channels.extend(fixture_data["channels"])
    elif "channel_id" in fixture_data:
        channels.append({
            "channel_id": fixture_data.get("channel_id"),
            "channel_key": fixture_data.get("channel_key") or f"{person_id}-main",
            "title": fixture_data.get("channel_title") or sheikh_name,
            "url": fixture_data.get("source_url") or f"https://www.youtube.com/channel/{fixture_data['channel_id']}",
            "source_type": "youtube_channel",
            "playlists_count": fixture_data.get("total_playlists", 0),
            "uploads_count": fixture_data.get("total_channel_uploads_scanned", 0),
        })
    else:
        channels.append({
            "channel_id": f"UC_{person_id}_official",
            "channel_key": f"{person_id}-main",
            "title": f"القناة الرسمية — {sheikh_name}",
            "url": f"https://www.youtube.com/@{person_id}",
            "source_type": "youtube_channel",
            "playlists_count": fixture_data.get("raw_playlists_count", 0),
            "uploads_count": fixture_data.get("unique_videos_count", 0),
        })

    # 2. Playlists / raw_series
    source_pls = fixture_data.get("raw_series") or fixture_data.get("playlists") or []
    for idx, sp in enumerate(source_pls, 1):
        pid = sp.get("id") or sp.get("playlist_id") or f"{person_id}__pl_{idx:03d}"
        yt_pl_id = sp.get("yt_playlist_id") if "yt_playlist_id" in sp else (
            None if "__unclassified" in str(pid) else pid
        )
        is_uncl = yt_pl_id is None or "__unclassified" in str(pid)
        ptitle = (sp.get("title") or pid).strip()
        stype = sp.get("source_type") or ("youtube_upload" if is_uncl else "youtube_playlist")

        raw_vids = sp.get("videos") or []
        if shared_mode and not is_uncl:
            v_titles = [v.get("title") or "" for v in raw_vids if isinstance(v, dict)]
            owner = attribute_shared_channel_owner(ptitle, v_titles, channel_key=ch_key_raw)
            if owner and owner != person_id:
                continue

        vids_out: list[dict[str, Any]] = []
        for v_idx, v in enumerate(raw_vids, 1):
            vid = v.get("yt_id") or v.get("vid")
            if not vid:
                continue
            ref = v_meta_lookup.get(vid, {})
            v_title_str = (v.get("title") or ref.get("title") or f"الدرس {v_idx}").strip()
            if shared_mode and is_uncl:
                v_owner = attribute_shared_channel_owner(v_title_str, None, channel_key=ch_key_raw)
                if v_owner and v_owner != person_id:
                    continue
            dur_raw = (
                v.get("dur_s")
                if v.get("dur_s") is not None
                else (v.get("duration") if v.get("duration") is not None else ref.get("duration"))
            )
            dur_s = int(round(float(dur_raw))) if isinstance(dur_raw, (int, float)) else 0
            up_date = v.get("upload_date") or ref.get("upload_date")
            v_stype = v.get("source_type") or ref.get("source_type") or (
                "youtube_stream" if ("بث مباشر" in v_title_str or "#مباشر" in v_title_str) else stype
            )
            vids_out.append({
                "pos": v.get("pos") or v.get("order_no") or len(vids_out) + 1,
                "vid": vid,
                "yt_id": vid,
                "title": v_title_str,
                "dur_s": dur_s,
                "duration": dur_s,
                "upload_date": up_date,
                "source_type": v_stype,
                "yt_url": v.get("yt_url") or v.get("url") or ref.get("yt_url") or f"https://www.youtube.com/watch?v={vid}",
            })

        declared_expected = sp.get("expected_count") or sp.get("video_count") or len(vids_out)
        playlists.append({
            "id": pid,
            "playlist_id": pid,
            "order_no": sp.get("order_no") or len(playlists) + 1,
            "title": ptitle,
            "yt_playlist_id": yt_pl_id,
            "url": sp.get("url") or (f"https://www.youtube.com/playlist?list={yt_pl_id}" if yt_pl_id else ""),
            "source_type": stype,
            "state": sp.get("state") or "completed",
            "expected_count": int(declared_expected),
            "video_count": len(vids_out),
            "note": sp.get("note") or ("تصنيف: غير مصنف" if is_uncl else "تصنيف: شرح / سلسلة علمية"),
            "matched_book": sp.get("matched_book"),
            "videos": vids_out,
        })

    # Also check if `unclassified_playlist` exists (from `fetch_channel_full.py` format)
    uncl_pl = fixture_data.get("unclassified_playlist")
    if isinstance(uncl_pl, dict) and uncl_pl.get("videos"):
        pid = uncl_pl.get("playlist_id") or f"{person_id}__unclassified"
        vids_out = []
        for v_idx, v in enumerate(uncl_pl["videos"], 1):
            vid = v.get("yt_id") or v.get("vid")
            if not vid:
                continue
            v_title_str = (v.get("title") or f"الدرس {v_idx}").strip()
            if shared_mode:
                v_owner = attribute_shared_channel_owner(v_title_str, None, channel_key=ch_key_raw)
                if v_owner and v_owner != person_id:
                    continue
            dur_raw = v.get("duration") if v.get("duration") is not None else v.get("dur_s")
            dur_s = int(round(float(dur_raw))) if isinstance(dur_raw, (int, float)) else 0
            vids_out.append({
                "pos": len(vids_out) + 1,
                "vid": vid,
                "yt_id": vid,
                "title": v_title_str,
                "dur_s": dur_s,
                "duration": dur_s,
                "upload_date": v.get("upload_date"),
                "source_type": "youtube_upload",
                "yt_url": v.get("url") or f"https://www.youtube.com/watch?v={vid}",
            })
        if vids_out:
            playlists.append({
                "id": pid,
                "playlist_id": pid,
                "order_no": len(playlists) + 1,
                "title": uncl_pl.get("title") or "غير مصنف",
                "yt_playlist_id": None,
                "url": "",
                "source_type": "youtube_upload",
                "state": "completed",
                "expected_count": len(vids_out),
                "video_count": len(vids_out),
                "note": "تصنيف: غير مصنف",
                "matched_book": None,
                "videos": vids_out,
            })

    # Also check if any videos in `unique_videos` were only in `unclassified` and not in `raw_series`
    seen_in_pls = {v["vid"] for pl in playlists for v in pl.get("videos", [])}
    orphan_uncl: list[dict[str, Any]] = []
    for vid, uv in v_meta_lookup.items():
        if vid not in seen_in_pls:
            v_title_str = (uv.get("title") or vid).strip()
            if shared_mode:
                v_owner = attribute_shared_channel_owner(v_title_str, None, channel_key=ch_key_raw)
                if v_owner and v_owner != person_id:
                    continue
            apps = uv.get("appearances") or []
            pos = apps[0].get("pos", len(orphan_uncl) + 1) if apps else len(orphan_uncl) + 1
            dur_raw = uv.get("dur_s") if uv.get("dur_s") is not None else uv.get("duration")
            dur_s = int(round(float(dur_raw))) if isinstance(dur_raw, (int, float)) else 0
            orphan_uncl.append({
                "pos": pos,
                "vid": vid,
                "yt_id": vid,
                "title": v_title_str,
                "dur_s": dur_s,
                "duration": dur_s,
                "upload_date": uv.get("upload_date"),
                "source_type": uv.get("source_type") or "youtube_upload",
                "yt_url": uv.get("yt_url") or f"https://www.youtube.com/watch?v={vid}",
            })
    if orphan_uncl:
        uncl_pid = f"{person_id}-main__unclassified"
        playlists.append({
            "id": uncl_pid,
            "playlist_id": uncl_pid,
            "order_no": len(playlists) + 1,
            "title": "غير مصنف",
            "yt_playlist_id": None,
            "url": "",
            "source_type": "youtube_upload",
            "state": "completed",
            "expected_count": len(orphan_uncl),
            "video_count": len(orphan_uncl),
            "note": "تصنيف: غير مصنف",
            "matched_book": None,
            "videos": orphan_uncl,
        })

    # 3. Archive.org payloads or items in fixture
    for raw_arch in fixture_data.get("archive_payloads") or []:
        item_id = raw_arch.get("item_id") or raw_arch.get("metadata", {}).get("identifier")
        if item_id:
            archive_items.append(
                parse_archive_metadata_payload(item_id, raw_arch, person_id, fallback_creator=sheikh_name)
            )
    for parsed_arch in fixture_data.get("archive_items") or []:
        if "files" in parsed_arch and "item_id" in parsed_arch:
            archive_items.append(parsed_arch)

    # 4. PDF links in fixture
    if "pdf_extracted_links" in fixture_data:
        pdf_links.extend(fixture_data["pdf_extracted_links"])

    return channels, playlists, archive_items, pdf_links


def _normalize_series_comparison_title(title: str, sheikh_name: str = "") -> str:
    """
    Normalize a YouTube playlist or Archive.org item title for cross-source series identity comparison:
    - Strips scholar names, honorifics (`الشيخ`, `الدكتور`, `فضيلة`, `الأستاذ`, `العلامة`),
      and generic series wrappers (`سلسلة`, `شرح`, `دروس`, `كتاب`, `متن`, `منظومة`, `برنامج`, `دورة`).
    - Normalizes glued `و` (`و نفس و ما سواها` -> `ونفس وما سواها`).
    """
    t = normalize_arabic(title or "")
    if not t:
        return ""
    # Normalize spaced 'و ' conjunction before words (`و نفس و ما` -> `ونفس وما`)
    t = re.sub(r"\bو\s+", "و", t)
    if sheikh_name:
        sh_norm = normalize_arabic(sheikh_name)
        for part in [sh_norm] + [w for w in sh_norm.split() if len(w) >= 4]:
            if part:
                t = t.replace(part, " ")
    for _, markers in SHARED_CHANNEL_PERSON_MARKERS:
        for m in markers:
            mn = normalize_arabic(m)
            if mn:
                t = t.replace(mn, " ")
    strip_words = {
        "سلسله", "دروس", "محاضرات", "برنامج", "دوره", "شرح", "التعليق", "تعليق",
        "علي", "على", "كتاب", "متن", "منظومه", "الشيخ", "للشيخ", "الدكتور", "للدكتور",
        "فضيله", "الاستاذ", "العلامه", "الامام", "للامام", "ابي", "ابو", "ابن", "بن",
        "رحمه", "الله", "حفظه", "تعالي", "بصوت", "كامل", "كامله", "جوده", "عاليه",
        "د", "أ", "شيخ",
    }
    tokens = [w for w in t.split() if w not in strip_words and not w.isdigit()]
    return " ".join(tokens).strip()


def _has_conflicting_edition_markers(title_a: str, title_b: str) -> bool:
    """
    Return True if two series titles have explicitly conflicting edition/level markers
    (e.g. `الأول` vs `الثاني`, `المختصر` vs `المطول`, `قديم` vs `جديد`).
    """
    na = f" {normalize_arabic(title_a)} "
    nb = f" {normalize_arabic(title_b)} "
    conflict_pairs = [
        (" الاول ", " الثاني "),
        (" الاولي ", " الثانيه "),
        (" المختصر ", " المطول "),
        (" القديم ", " الجديد "),
        (" قديم ", " جديد "),
    ]
    for m1, m2 in conflict_pairs:
        if (m1 in na and m2 in nb) or (m2 in na and m1 in nb):
            return True
    return False


def link_and_deduplicate_cross_source_series(
    playlists: list[dict[str, Any]],
    archive_items: list[dict[str, Any]],
    sheikh_name: str = "",
) -> dict[str, int]:
    """
    Unify and deduplicate Archive.org items against YouTube playlists (and earlier Archive.org items):
    - When an Archive.org item matches an existing series by `matched_book["book_id"]` (with same
      `surah_number` for `quran-karim`) or normalized series title similarity:
      1. Links `linked_archive_item` / `linked_archive_items` and `archive_details_url` on the target series.
      2. Attaches `archive_direct_url` and `archive_vid` to matching episodes (by `episode_num`),
         and upgrades missing (`0`) episode durations from Archive.org.
      3. Recovers missing gap episodes present on Archive.org (e.g. episode 24 of `إيصال السالك` or
         episode 28 of `العقيدة الطحاوية`) into the series in natural numerical order.
    - When an Archive.org item does NOT match any existing series, appends it as a standalone
      `archive__<item_id>` series in `playlists`.
    """
    stats = {
        "linked_archive_items_count": 0,
        "cross_source_matched_episodes_count": 0,
        "archive_recovered_missing_episodes_count": 0,
        "standalone_archive_series_count": 0,
    }
    existing_pids = {pl.get("playlist_id") or pl.get("id") for pl in playlists}

    for arch in archive_items:
        arch_files = arch.get("files") or []
        if not arch_files:
            continue
        item_id = arch["item_id"]
        arch_pid = f"archive__{item_id}"
        if arch_pid in existing_pids:
            continue

        arch_title = arch.get("title") or item_id
        arch_norm_title = _normalize_series_comparison_title(arch_title, sheikh_name)
        arch_mb = arch.get("matched_book")
        arch_book_id = arch_mb.get("book_id") if isinstance(arch_mb, dict) else None
        arch_surah = arch_mb.get("surah_number") if isinstance(arch_mb, dict) else None

        candidates: list[tuple[int, int, dict[str, Any]]] = []
        for pl in playlists:
            pid = str(pl.get("playlist_id") or pl.get("id") or "")
            is_uncl = pl.get("yt_playlist_id") is None or "__unclassified" in pid
            if is_uncl or pid == arch_pid:
                continue
            pl_title = pl.get("title") or ""
            if _has_conflicting_edition_markers(arch_title, pl_title):
                continue

            matched = False
            pl_mb = pl.get("matched_book")
            pl_book_id = pl_mb.get("book_id") if isinstance(pl_mb, dict) else None
            pl_surah = pl_mb.get("surah_number") if isinstance(pl_mb, dict) else None

            if arch_book_id and pl_book_id and arch_book_id == pl_book_id:
                if arch_book_id == "quran-karim":
                    if arch_surah and pl_surah and arch_surah == pl_surah:
                        matched = True
                else:
                    matched = True

            if not matched and len(arch_norm_title) >= 5:
                pl_norm_title = _normalize_series_comparison_title(pl_title, sheikh_name)
                if len(pl_norm_title) >= 5:
                    if arch_norm_title == pl_norm_title:
                        matched = True
                    else:
                        shorter = min(arch_norm_title, pl_norm_title, key=len)
                        longer = max(arch_norm_title, pl_norm_title, key=len)
                        if len(shorter) >= 8 and len(shorter.split()) >= 2 and shorter in longer:
                            matched = True

            if matched:
                is_yt_prio = 0 if pl.get("source_type") != "archive_org" else 1
                v_count = len(pl.get("videos") or [])
                candidates.append((is_yt_prio, -v_count, pl))

        if candidates:
            candidates.sort(key=lambda x: (x[0], x[1]))
            target_pl = candidates[0][2]
            stats["linked_archive_items_count"] += 1
            target_pl["linked_archive_item"] = item_id
            linked_list = target_pl.setdefault("linked_archive_items", [])
            if item_id not in linked_list:
                linked_list.append(item_id)
            target_pl["archive_details_url"] = arch.get("details_url")
            arch["linked_playlist_id"] = target_pl.get("playlist_id") or target_pl.get("id")

            pl_vids = target_pl.setdefault("videos", [])
            ep_map: dict[int, dict[str, Any]] = {}
            pl_title_str = target_pl.get("title") or ""
            for v in pl_vids:
                ep_n = v.get("episode_num")
                if ep_n is None:
                    ep_n = extract_episode_num_from_text(v.get("title") or "", item_title=pl_title_str)
                if isinstance(ep_n, int) and ep_n >= 1:
                    v["episode_num"] = ep_n
                    ep_map.setdefault(ep_n, v)
            for v in pl_vids:
                if v.get("episode_num") is None:
                    pos_n = v.get("pos")
                    if isinstance(pos_n, int) and pos_n >= 1 and pos_n not in ep_map:
                        v["episode_num"] = pos_n
                        ep_map[pos_n] = v

            recovered_here = 0
            for f in arch_files:
                f_ep = f.get("episode_num") or f.get("pos")
                if isinstance(f_ep, int) and f_ep in ep_map:
                    ev = ep_map[f_ep]
                    ev["archive_direct_url"] = f["direct_url"]
                    ev["archive_vid"] = f["vid"]
                    if (ev.get("dur_s") or 0) == 0 and (f.get("dur_s") or 0) > 0:
                        ev["dur_s"] = f["dur_s"]
                        ev["duration"] = f["duration"]
                    stats["cross_source_matched_episodes_count"] += 1
                else:
                    new_v = {
                        "pos": f_ep if isinstance(f_ep, int) and f_ep >= 1 else len(pl_vids) + 1,
                        "episode_num": f_ep,
                        "vid": f["vid"],
                        "yt_id": f["yt_id"],
                        "title": f["title"],
                        "dur_s": f["dur_s"],
                        "duration": f["duration"],
                        "upload_date": f.get("upload_date") or arch.get("upload_date"),
                        "source_type": "archive_org",
                        "yt_url": f["direct_url"],
                        "archive_direct_url": f["direct_url"],
                        "recovered_from_archive": item_id,
                    }
                    pl_vids.append(new_v)
                    if isinstance(f_ep, int) and f_ep >= 1:
                        ep_map[f_ep] = new_v
                    recovered_here += 1
                    stats["archive_recovered_missing_episodes_count"] += 1

            if recovered_here > 0:
                pl_vids.sort(
                    key=lambda v: (
                        0 if v.get("episode_num") is not None else 1,
                        v.get("episode_num") if v.get("episode_num") is not None else (v.get("pos") or 0),
                        v.get("pos") or 0,
                    )
                )
                for new_pos, v in enumerate(pl_vids, 1):
                    v["pos"] = new_pos
                target_pl["video_count"] = len(pl_vids)
                target_pl["expected_count"] = max(int(target_pl.get("expected_count") or 0), len(pl_vids))
        else:
            existing_pids.add(arch_pid)
            stats["standalone_archive_series_count"] += 1
            arch_vids = []
            for f in arch_files:
                arch_vids.append({
                    "pos": f.get("pos", 1),
                    "episode_num": f.get("episode_num") or f.get("pos", 1),
                    "vid": f["vid"],
                    "yt_id": f["yt_id"],
                    "title": f["title"],
                    "dur_s": f["dur_s"],
                    "duration": f["duration"],
                    "upload_date": f.get("upload_date") or arch.get("upload_date"),
                    "source_type": "archive_org",
                    "yt_url": f["direct_url"],
                    "archive_direct_url": f["direct_url"],
                })
            playlists.append({
                "id": arch_pid,
                "playlist_id": arch_pid,
                "order_no": len(playlists) + 1,
                "title": arch_title,
                "yt_playlist_id": arch_pid,
                "url": arch["details_url"],
                "source_type": "archive_org",
                "state": "completed",
                "expected_count": len(arch_vids),
                "video_count": len(arch_vids),
                "note": f"تصنيف: سلسلة صوتية من أرشيف الإنترنت (Archive.org: {item_id})",
                "matched_book": arch.get("matched_book"),
                "videos": arch_vids,
            })

    return stats


def build_canonical_raw_json(
    person_id: str,
    sheikh_name: str,
    channels: list[dict[str, Any]],
    playlists: list[dict[str, Any]],
    archive_items: list[dict[str, Any]],
    pdf_extracted_links: list[dict[str, Any]],
    extra_books: list[dict[str, Any]] | None = None,
    photo_url: str | None = None,
    shamela_db_dir: str | Path | None = None,
) -> dict[str, Any]:
    """
    Deduplicate playlists and videos across all sources (YouTube + Archive.org + PDF links),
    match series to books/matns (including the 8,589-book Shamela index), link cross-source
    Archive.org + YouTube series and recover missing episodes, and build `<person_id>_raw.json`.
    """
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    now_sql = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    # 1. Pre-match playlists and archive_items to books/matns so cross-source linking can use book_id
    discover_person_books(
        sheikh_name=sheikh_name,
        playlists=playlists,
        archive_items=archive_items,
        extra_books=extra_books,
        person_id=person_id,
        shamela_db_dir=shamela_db_dir,
    )

    # 2. Link & deduplicate Archive.org items against YouTube playlists (recovering missing gap episodes)
    cross_source_stats = link_and_deduplicate_cross_source_series(
        playlists=playlists,
        archive_items=archive_items,
        sheikh_name=sheikh_name,
    )

    # 3. Finalize books catalog with updated source_series_ids across all playlists and archive items
    books = discover_person_books(
        sheikh_name=sheikh_name,
        playlists=playlists,
        archive_items=archive_items,
        extra_books=extra_books,
        person_id=person_id,
        shamela_db_dir=shamela_db_dir,
    )

    # 4. Identify all videos that belong to official/classified playlists
    classified_vids: set[str] = set()
    for pl in playlists:
        is_uncl = pl.get("yt_playlist_id") is None or "__unclassified" in str(pl.get("id", ""))
        if not is_uncl:
            for v in pl.get("videos", []):
                vid = v.get("vid") or v.get("yt_id")
                if vid:
                    classified_vids.add(vid)

    # 5. Clean unclassified playlists (remove videos already in classified playlists) & deduplicate
    duplicates_removed = 0
    cleaned_playlists: list[dict[str, Any]] = []
    seen_pl_ids: set[str] = set()

    for pl in playlists:
        pid = pl.get("playlist_id") or pl.get("id")
        if not pid or pid in seen_pl_ids:
            duplicates_removed += 1
            continue
        seen_pl_ids.add(pid)

        is_uncl = pl.get("yt_playlist_id") is None or "__unclassified" in str(pid)
        seen_in_this_pl: set[str] = set()
        dedup_vids: list[dict[str, Any]] = []

        for v in pl.get("videos", []):
            vid = v.get("vid") or v.get("yt_id")
            if not vid:
                continue
            if vid in seen_in_this_pl:
                duplicates_removed += 1
                continue
            if is_uncl and vid in classified_vids:
                duplicates_removed += 1
                continue
            seen_in_this_pl.add(vid)
            dur_s = int(v.get("dur_s") if v.get("dur_s") is not None else (v.get("duration") or 0))
            v_entry: dict[str, Any] = {
                "pos": len(dedup_vids) + 1,
                "vid": vid,
                "yt_id": vid,
                "title": (v.get("title") or f"الدرس {len(dedup_vids) + 1}").strip(),
                "dur_s": dur_s,
                "duration": dur_s,
                "upload_date": v.get("upload_date"),
                "source_type": v.get("source_type") or pl.get("source_type") or "youtube_playlist",
                "yt_url": v.get("yt_url") or f"https://www.youtube.com/watch?v={vid}",
            }
            for opt_key in ("episode_num", "archive_direct_url", "archive_vid", "recovered_from_archive"):
                if v.get(opt_key) is not None:
                    v_entry[opt_key] = v[opt_key]
            dedup_vids.append(v_entry)

        if is_uncl and not dedup_vids:
            continue

        pl_copy = dict(pl)
        pl_copy["id"] = pid
        pl_copy["playlist_id"] = pid
        pl_copy["order_no"] = len(cleaned_playlists) + 1
        pl_copy["video_count"] = len(dedup_vids)
        pl_copy["expected_count"] = max(int(pl.get("expected_count") or 0), len(dedup_vids))
        pl_copy["videos"] = dedup_vids
        cleaned_playlists.append(pl_copy)

    # 6. Build deduplicated `videos` / `unique_videos` with full `appearances`
    unique_videos_map: dict[str, dict[str, Any]] = {}
    for pl in cleaned_playlists:
        pid = pl["id"]
        ptitle = pl["title"]
        is_uncl = pl.get("yt_playlist_id") is None or "__unclassified" in str(pid)
        pl_matched_book = pl.get("matched_book")

        for v in pl["videos"]:
            vid = v["vid"]
            dur_s = v["dur_s"]
            if vid not in unique_videos_map:
                uv_entry: dict[str, Any] = {
                    "vid": vid,
                    "yt_id": vid,
                    "title": v["title"],
                    "yt_url": v["yt_url"],
                    "dur_s": dur_s,
                    "duration": dur_s,
                    "upload_date": v.get("upload_date") or "unknown",
                    "playlist_id": None if is_uncl else pid,
                    "playlist_title": "غير مصنف" if is_uncl else ptitle,
                    "source_type": v.get("source_type") or pl.get("source_type") or "youtube_playlist",
                    "has_transcript": 0,
                    "has_summary": 0,
                    "has_questions": 0,
                    "matched_book": pl_matched_book,
                    "appearances": [],
                }
                for opt_key in ("episode_num", "archive_direct_url", "archive_vid", "recovered_from_archive"):
                    if v.get(opt_key) is not None:
                        uv_entry[opt_key] = v[opt_key]
                unique_videos_map[vid] = uv_entry
            else:
                duplicates_removed += 1
                # Upgrade duration, matched_book, or archive_direct_url if previously missing
                if unique_videos_map[vid]["dur_s"] == 0 and dur_s > 0:
                    unique_videos_map[vid]["dur_s"] = dur_s
                    unique_videos_map[vid]["duration"] = dur_s
                if not unique_videos_map[vid].get("matched_book") and pl_matched_book:
                    unique_videos_map[vid]["matched_book"] = pl_matched_book
                if not unique_videos_map[vid].get("archive_direct_url") and v.get("archive_direct_url"):
                    unique_videos_map[vid]["archive_direct_url"] = v["archive_direct_url"]

            unique_videos_map[vid]["appearances"].append({
                "raw_series_id": pid,
                "raw_series_title": ptitle,
                "pos": v["pos"],
                "is_unclassified": is_uncl,
            })

    videos_list = list(unique_videos_map.values())
    official_playlists_count = sum(
        1
        for pl in cleaned_playlists
        if pl.get("yt_playlist_id") is not None and "__unclassified" not in str(pl.get("id", ""))
    )
    streams_count = sum(1 for v in videos_list if v.get("source_type") == "youtube_stream")
    unclassified_videos_count = sum(
        1
        for v in videos_list
        if all(a.get("is_unclassified") for a in v.get("appearances", []))
    )
    total_dur_s = sum(v.get("dur_s") or 0 for v in videos_list)
    matched_series_count = sum(1 for pl in cleaned_playlists if pl.get("matched_book") is not None)
    pdf_playlists_count = sum(
        1 for lnk in pdf_extracted_links if lnk.get("link_type") == "youtube_playlist"
    )
    archive_audio_count = sum(item.get("audio_files_count", 0) for item in archive_items)

    stats = {
        "channels_count": len(channels),
        "playlists_count": official_playlists_count,
        "total_series_including_unclassified": len(cleaned_playlists),
        "videos_count": len(videos_list),
        "streams_count": streams_count,
        "unclassified_videos_count": unclassified_videos_count,
        "archive_items_count": len(archive_items),
        "archive_audio_files_count": archive_audio_count,
        "linked_archive_items_count": cross_source_stats["linked_archive_items_count"],
        "cross_source_matched_episodes_count": cross_source_stats["cross_source_matched_episodes_count"],
        "archive_recovered_missing_episodes_count": cross_source_stats["archive_recovered_missing_episodes_count"],
        "pdf_links_count": len(pdf_extracted_links),
        "pdf_playlists_count": pdf_playlists_count,
        "books_count": len(books),
        "matched_series_to_books_count": matched_series_count,
        "total_duration_s": total_dur_s,
        "total_duration_hours": round(total_dur_s / 3600.0, 2),
        "duplicates_removed": duplicates_removed,
    }

    resolved_photo = photo_url if photo_url is not None else SHEIKH_PHOTOS.get(person_id)
    sheikh_obj = {
        "id": person_id,
        "order_no": 1,
        "name": sheikh_name,
        "short_name": extract_short_name(sheikh_name),
        "photo": resolved_photo,
        "created_at": now_sql,
    }

    return {
        "person_id": person_id,
        "sheikh_name": sheikh_name,
        "discovered_at": now_iso,
        "sheikh": sheikh_obj,
        "channels": channels,
        "playlists": cleaned_playlists,
        "videos": videos_list,
        "archive_items": archive_items,
        "pdf_extracted_links": pdf_extracted_links,
        "books": books,
        "stats": stats,
        "raw_playlists_count": official_playlists_count,
        "unique_videos_count": len(videos_list),
        "raw_series": cleaned_playlists,
        "unique_videos": videos_list,
    }


# ---------------------------------------------------------------------------
# 7. High-Level Orchestrator (`discover_person`) & CLI Entrypoint
# ---------------------------------------------------------------------------

def discover_person(
    name: str,
    person_id: str | None = None,
    youtube_urls: list[str] | None = None,
    archive_ids: list[str] | None = None,
    index_pdfs: list[str | Path] | None = None,
    books_json: str | Path | None = None,
    offline_fixture: str | Path | dict[str, Any] | list[str | Path | dict[str, Any]] | None = None,
    shamela_db_dir: str | Path | None = None,
    resolve_redirects: bool = False,
    fetch_live_unlisted_playlists: bool = False,
    output_path: str | Path | None = None,
) -> dict[str, Any]:
    """
    Main orchestrator for `person-discovery-intake`.
    Combines offline fixtures (single or multi-channel list), PDF link extraction, YouTube URLs,
    Archive.org items, and books catalog (including Shamela4 index) into a unified `<person_id>_raw.json`.
    """
    pid = normalize_person_id(name, explicit_id=person_id)
    channels: list[dict[str, Any]] = []
    playlists: list[dict[str, Any]] = []
    archive_items: list[dict[str, Any]] = []
    pdf_links: list[dict[str, Any]] = []
    extra_books: list[dict[str, Any]] = []
    photo_url: str | None = None

    # 1. Load offline fixture(s) if provided
    if offline_fixture is not None:
        fixture_items = offline_fixture if isinstance(offline_fixture, list) else [offline_fixture]
        for fix_item in fixture_items:
            if isinstance(fix_item, dict):
                fix_data = fix_item
            else:
                fix_path = Path(fix_item)
                fix_data = json.loads(fix_path.read_text(encoding="utf-8"))
            if not name and fix_data.get("sheikh", {}).get("name"):
                name = fix_data["sheikh"]["name"]
            if photo_url is None and fix_data.get("sheikh", {}).get("photo"):
                photo_url = fix_data["sheikh"]["photo"]
            f_ch, f_pl, f_arch, f_pdf = ingest_offline_fixture(fix_data, pid, name)
            channels.extend(f_ch)
            playlists.extend(f_pl)
            archive_items.extend(f_arch)
            pdf_links.extend(f_pdf)
            if "books" in fix_data and isinstance(fix_data["books"], list):
                extra_books.extend(fix_data["books"])

    # 2. Load external books catalog JSON if provided
    if books_json:
        b_path = Path(books_json)
        if b_path.exists():
            b_data = json.loads(b_path.read_text(encoding="utf-8"))
            if isinstance(b_data, list):
                extra_books.extend(b_data)
            elif isinstance(b_data, dict) and "books" in b_data:
                extra_books.extend(b_data["books"])

    # 3. Extract links from index PDFs (e.g. Jamharat A'mal)
    for pdf_file in index_pdfs or []:
        extracted = extract_links_from_pdf(pdf_file, resolve_redirects=resolve_redirects)
        pdf_links.extend(extracted)
        for lnk in extracted:
            if lnk["link_type"] == "youtube_playlist" and lnk.get("playlist_id"):
                if fetch_live_unlisted_playlists:
                    dump = run_yt_dlp_flat_json(lnk["resolved_url"])
                    if dump:
                        pl_obj, _ = parse_yt_dlp_playlist_dump(
                            dump, default_source_type="youtube_unlisted_playlist"
                        )
                        playlists.append(pl_obj)
            elif lnk["link_type"] == "archive_item" and lnk.get("archive_id"):
                if archive_ids is None:
                    archive_ids = []
                if lnk["archive_id"] not in archive_ids:
                    archive_ids.append(lnk["archive_id"])

    # 4. Fetch explicit YouTube URLs if provided
    for yt_url in youtube_urls or []:
        dump = run_yt_dlp_flat_json(yt_url)
        if dump:
            stype = "youtube_stream" if "/streams" in yt_url else "youtube_playlist"
            pl_obj, _ = parse_yt_dlp_playlist_dump(dump, default_source_type=stype)
            playlists.append(pl_obj)

    # 5. Fetch explicit Archive.org IDs if provided (and not already loaded via offline fixture)
    loaded_arch_ids = {a["item_id"] for a in archive_items}
    for arch_id in archive_ids or []:
        if arch_id in loaded_arch_ids:
            continue
        meta_payload = fetch_archive_item_metadata(arch_id)
        if meta_payload:
            archive_items.append(
                parse_archive_metadata_payload(arch_id, meta_payload, pid, fallback_creator=name)
            )
            loaded_arch_ids.add(arch_id)

    # 6. Build canonical `<person_id>_raw.json`
    result = build_canonical_raw_json(
        person_id=pid,
        sheikh_name=name,
        channels=channels,
        playlists=playlists,
        archive_items=archive_items,
        pdf_extracted_links=pdf_links,
        extra_books=extra_books,
        photo_url=photo_url,
        shamela_db_dir=shamela_db_dir,
    )

    if output_path:
        out_p = Path(output_path)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    return result


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Exhaustive Multi-Source Person Discovery & Intake Engine (<person_id>_raw.json)."
    )
    ap.add_argument("--name", required=True, help="Full Arabic name of the scholar/person")
    ap.add_argument("--person-id", default=None, help="Canonical ASCII slug (auto-generated if omitted)")
    ap.add_argument("--youtube-urls", nargs="*", default=[], help="YouTube channel/playlist/stream URLs")
    ap.add_argument("--archive-ids", nargs="*", default=[], help="Archive.org item identifiers")
    ap.add_argument("--index-pdfs", nargs="*", default=[], help="Paths to index PDF files (e.g. Jamharat A'mal)")
    ap.add_argument("--books-json", default=None, help="Path to local books catalog JSON")
    ap.add_argument("--shamela-db-dir", default=None, help="Path to Shamela4_Full_DB directory or index")
    ap.add_argument("--offline-fixture", nargs="*", default=None, help="Path(s) to offline fixture JSON or existing <id>_raw.json")
    ap.add_argument("--resolve-redirects", action="store_true", help="Follow HTTP 301/302 redirects for shortlinks")
    ap.add_argument("--output", "-o", default=None, help="Output file path for <person_id>_raw.json")
    return ap


def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()

    res = discover_person(
        name=args.name,
        person_id=args.person_id,
        youtube_urls=args.youtube_urls,
        archive_ids=args.archive_ids,
        index_pdfs=args.index_pdfs,
        books_json=args.books_json,
        offline_fixture=args.offline_fixture,
        shamela_db_dir=args.shamela_db_dir,
        resolve_redirects=args.resolve_redirects,
        output_path=args.output,
    )
    st = res["stats"]
    print(
        f"[OK] person_id={res['person_id']} ({res['sheikh_name']}): "
        f"{st['playlists_count']} playlists, {st['videos_count']} unique videos/tracks "
        f"({st['total_duration_hours']}h), {st['archive_items_count']} archive items, "
        f"{st['pdf_links_count']} PDF links, {st['books_count']} books."
    )


if __name__ == "__main__":
    main()

