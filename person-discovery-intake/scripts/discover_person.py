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
    "سعيد الكملي": "kamali",
    "محمد الحسن الددو": "dedew",
    "علي جمعة": "gomaa",
    "عبد الرحمن ذاكر الهاشمي": "hashemi",
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
    r"\b(?:bit\.ly|goo\.gl|tinyurl\.com|t\.co|youtu\.be)/[A-Za-z0-9_\-]+",
    re.IGNORECASE,
)
BARE_PLAYLIST_ID_RE = re.compile(r"\b(PL[A-Za-z0-9_\-]{16,34})\b")


def _unescape_pdf_string(raw_bytes: bytes) -> str:
    """Unescape PDF literal string escapes such as \\(, \\), \\\\ and octal \\ddd."""
    s = raw_bytes.decode("latin-1", errors="ignore")
    s = s.replace(r"\(", "(").replace(r"\)", ")").replace(r"\\", "\\")
    return s.strip()


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
    target = (resolved_url or url).strip().rstrip(".,;)]}>'\"")
    playlist_id = None
    video_id = None
    archive_id = None
    link_type = "other"

    # 1. Check YouTube Playlist
    m_pl = re.search(r"[?&]list=((?:PL|UU|OLAK5uy_)[A-Za-z0-9_\-]+)", target)
    if m_pl:
        playlist_id = m_pl.group(1)
        link_type = "youtube_playlist"
    else:
        # 2. Check YouTube Video
        m_vid = re.search(
            r"(?:youtube\.com/(?:watch\?.*?v=|live/|shorts/|embed/)|youtu\.be/)([A-Za-z0-9_\-]{11})",
            target,
        )
        if m_vid:
            video_id = m_vid.group(1)
            link_type = "youtube_video"
        else:
            # 3. Check Archive.org Item
            m_arch = re.search(
                r"archive\.org/(?:details|download|metadata)/([A-Za-z0-9_.\-]+)",
                target,
            )
            if m_arch:
                archive_id = m_arch.group(1)
                link_type = "archive_item"
            elif re.search(r"^https?://(?:bit\.ly|goo\.gl|tinyurl\.com|t\.co)/", target, re.I):
                link_type = "shortlink"

    return {
        "url": url.strip().rstrip(".,;)]}>'\""),
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
        resolved = clean_u
        if resolve_redirects and re.search(
            r"^https?://(?:bit\.ly|goo\.gl|tinyurl\.com|t\.co)/", clean_u, re.I
        ):
            resolved = resolve_http_redirect(clean_u)

        info = classify_extracted_url(clean_u, resolved)
        dedup_key = (
            f"pl:{info['playlist_id']}"
            if info["playlist_id"]
            else (
                f"vid:{info['video_id']}"
                if info["video_id"]
                else (
                    f"arch:{info['archive_id']}"
                    if info["archive_id"]
                    else info["resolved_url"]
                )
            )
        )
        if dedup_key in seen_keys:
            continue
        seen_keys.add(dedup_key)
        info["source_pdf"] = pdf_name
        info["extraction_method"] = method
        results.append(info)

    return results


# ---------------------------------------------------------------------------
# 3. Classical & Modern Books Knowledge Base & Matn Matching Engine
# ---------------------------------------------------------------------------

MATN_KNOWLEDGE_BASE: list[dict[str, Any]] = [
    # --- الفقه المالكي ---
    {
        "book_id": "maliki:mukhtasar_khalil",
        "title": "مختصر خليل في الفقه المالكي",
        "author": "خليل بن إسحاق الجندي",
        "science": "الفقه المالكي",
        "keywords": ["مختصر خليل", "المختصر الفقهي لخليل"],
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
        "keywords": ["رسالة ابن أبي زيد", "رساله ابن ابي زيد", "الرسالة الفقهية"],
    },
    {
        "book_id": "maliki:murshid_muin_ibn_ashir",
        "title": "المرشد المعين على الضروري من علوم الدين (متن ابن عاشر)",
        "author": "عبد الواحد بن عاشر",
        "science": "الفقه المالكي",
        "keywords": ["المرشد المعين", "متن ابن عاشر", "نظم ابن عاشر", "ميارة الصغير"],
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
        "keywords": ["المنهج المنتخب", "منهج الزقاق", "قواعد الزقاق"],
    },
    {
        "book_id": "maliki:idah_al_masalik",
        "title": "إيضاح المسالك إلى قواعد الإمام مالك",
        "author": "أحمد بن يحيى الونشريسي",
        "science": "الفقه المالكي",
        "keywords": ["إيضاح المسالك", "ايضاح المسالك"],
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
        "keywords": ["متن الورقات", "شرح الورقات"],
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
        "keywords": ["مقدمات السنوسي", "مقدمات الإمام السنوسي", "المقدمات للسنوسي"],
    },
    {
        "book_id": "akida:umm_al_barahin",
        "title": "أم البراهين (العقيدة الصغرى للسنوسي)",
        "author": "أبو عبد الله محمد بن يوسف السنوسي",
        "science": "العقيدة وعلم الكلام",
        "keywords": ["أم البراهين", "العقيدة الصغرى", "صغرى السنوسي"],
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
        "keywords": ["الحكم العطائية", "الحكم العطائيه"],
    },
    {
        "book_id": "tazkia:qabas_al_nur_al_mubin",
        "title": "قبس النور المبين من إحياء علوم الدين",
        "author": "الحبيب عمر بن حفيظ (مختصر الإحياء للغزالي)",
        "science": "التزكية والسلوك",
        "keywords": ["قبس النور المبين"],
    },
    {
        "book_id": "tazkia:risalat_al_muawanah",
        "title": "رسالة المعاونة والمظاهرة والمؤازرة",
        "author": "الحبيب عبد الله بن علوي الحداد",
        "science": "التزكية والسلوك",
        "keywords": ["رسالة المعاونة", "رساله المعاونه"],
    },
    {
        "book_id": "tazkia:risala_qushayriyya",
        "title": "الرسالة القشيرية",
        "author": "أبو القاسم القشيري",
        "science": "التزكية والسلوك",
        "keywords": ["الرسالة القشيرية", "الرساله القشيريه"],
    },
    # --- الحديث النبوي والسيرة ---
    {
        "book_id": "hadith:sahih_al_bukhari",
        "title": "الجامع المسند الصحيح (صحيح البخاري)",
        "author": "محمد بن إسماعيل البخاري",
        "science": "الحديث النبوي وشروحه",
        "keywords": ["صحيح البخاري", "جامع البخاري", "الكوكب الساري"],
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
        "keywords": ["موطأ الإمام مالك", "موطأ مالك", "شرح الموطأ", "شرح الزرقاني على موطأ"],
    },
    {
        "book_id": "hadith:riyad_al_salihin",
        "title": "رياض الصالحين من كلام سيد المرسلين",
        "author": "محيي الدين يحيى بن شرف النووي",
        "science": "الحديث النبوي والتزكية",
        "keywords": ["رياض الصالحين"],
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
    # --- اللغة العربية والنحو والصرف والبلاغة ---
    {
        "book_id": "nahw:alfiyyat_ibn_malik",
        "title": "ألفية ابن مالك في النحو والصرف",
        "author": "ابن مالك الأندلسي",
        "science": "النحو والصرف",
        "keywords": ["ألفية ابن مالك", "شرح ابن عقيل", "شرح الأشموني", "أوضح المسالك"],
    },
    {
        "book_id": "nahw:qatr_al_nada",
        "title": "قطر الندى وبل الصدى",
        "author": "ابن هشام الأنصاري",
        "science": "النحو والصرف",
        "keywords": ["قطر الندى", "قطر الندي"],
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
        "title": "المقدمة الآجرومية",
        "author": "ابن آجروم الصنهاجي",
        "science": "النحو والصرف",
        "keywords": ["الآجرومية", "الاجروميه", "متن الآجرومية"],
    },
    {
        "book_id": "sarf:lamiyyat_al_afaal",
        "title": "لامية الأفعال في علم الصرف",
        "author": "ابن مالك الأندلسي",
        "science": "النحو والصرف",
        "keywords": ["لامية الأفعال", "لاميه الافعال"],
    },
    {
        "book_id": "balagha:dalail_al_ijaz",
        "title": "دلائل الإعجاز في علم المعاني",
        "author": "عبد القاهر الجرجاني",
        "science": "البلاغة القرآنية",
        "keywords": ["دلائل الإعجاز", "دلائل الاعجاز"],
    },
    # --- المنطق والفكر المعاصر ---
    {
        "book_id": "mantiq:sullam_munawwaraq",
        "title": "السلم المنورق في علم المنطق",
        "author": "عبد الرحمن الأخضري",
        "science": "المنطق وآداب البحث",
        "keywords": ["السلم المنورق"],
    },
    {
        "book_id": "fikr:fi_sittat_ayyam",
        "title": "في ستة أيام",
        "author": "علي محمود العمري",
        "science": "الفكر الإسلامي والعقيدة",
        "keywords": ["في ستة أيام", "في سته ايام"],
    },
]


def _word_boundary_match(needle_norm: str, haystack_norm: str) -> bool:
    """Check if normalized phrase `needle_norm` appears on Arabic word boundaries inside `haystack_norm`."""
    if not needle_norm or not haystack_norm:
        return False
    pattern = rf"(?:^|[\s/:|\-–—(\[\{{«\"'،.]){re.escape(needle_norm)}(?:$|[\s/:|\-–—)\]\}}»\"'،.])"
    return bool(re.search(pattern, haystack_norm))


def match_title_to_book(
    series_title: str,
    video_titles: list[str] | None = None,
    extra_books: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """
    Match a playlist/series title (and sample video titles) against classical matns and books
    using Arabic word-boundary checks and strict science separation.
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

    return best_match


def discover_person_books(
    sheikh_name: str,
    playlists: list[dict[str, Any]],
    archive_items: list[dict[str, Any]],
    extra_books: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """
    Build the unified `books` list for `<person_id>_raw.json`, combining:
    1. Books authored by `sheikh_name` (from knowledge base or `--books-json`).
    2. Classical matns / books explained by `sheikh_name` across playlists and Archive.org items.
    """
    norm_person = normalize_arabic(sheikh_name)
    books_map: dict[str, dict[str, Any]] = {}

    # 1. Check catalog for books authored directly by the person
    all_candidates = list(MATN_KNOWLEDGE_BASE) + list(extra_books or [])
    for b in all_candidates:
        b_id = str(b.get("book_id") or b.get("id") or "")
        b_title = b.get("title") or ""
        b_author = b.get("author") or ""
        if not b_id or not b_title:
            continue
        norm_author = normalize_arabic(b_author)
        is_authored = bool(
            norm_person
            and norm_author
            and (norm_person in norm_author or norm_author in norm_person)
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

    # 2. Match playlists / series to books
    for pl in playlists:
        v_titles = [v.get("title", "") for v in pl.get("videos", [])]
        matched = pl.get("matched_book") or match_title_to_book(
            pl.get("title", ""), v_titles, extra_books=extra_books
        )
        if matched:
            pl["matched_book"] = matched
            b_id = matched["book_id"]
            b_author = matched.get("author") or ""
            norm_author = normalize_arabic(b_author)
            is_authored = bool(
                norm_person
                and norm_author
                and (norm_person in norm_author or norm_author in norm_person)
            )
            if b_id not in books_map:
                books_map[b_id] = {
                    "book_id": b_id,
                    "title": matched["title"],
                    "author": b_author,
                    "science": matched.get("science") or "علوم شرعية",
                    "source": "series_matn_matcher",
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
            item.get("title", ""), f_titles, extra_books=extra_books
        )
        if matched:
            item["matched_book"] = matched
            b_id = matched["book_id"]
            if b_id not in books_map:
                books_map[b_id] = {
                    "book_id": b_id,
                    "title": matched["title"],
                    "author": matched.get("author") or "",
                    "science": matched.get("science") or "علوم شرعية",
                    "source": "archive_matn_matcher",
                    "is_authored_by_person": False,
                    "is_explained_by_person": True,
                    "matched_playlists": [],
                }
            else:
                books_map[b_id]["is_explained_by_person"] = True
            arch_pid = f"archive__{item['item_id']}"
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
    ".ogg": 4,
    ".wav": 5,
}


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


def parse_archive_metadata_payload(
    item_id: str,
    meta_payload: dict[str, Any],
    person_id: str,
    fallback_creator: str = "",
) -> dict[str, Any]:
    """
    Parse an Archive.org `/metadata/<item_id>` JSON payload:
    - Extracts item metadata (`title`, `creator`, `uploader`, `mediatype`, `date`).
    - Filters audio files and deduplicates derivative formats by stem (`.mp3` preferred over `.ogg`).
    - Computes exact `dur_s` / `duration` and `direct_url` for each audio file.
    """
    meta = meta_payload.get("metadata") or {}
    raw_files = meta_payload.get("files") or []
    clean_item_slug = re.sub(r"[^A-Za-z0-9_]+", "_", item_id).strip("_")

    # Group audio candidates by stem so derivative .ogg files don't duplicate original .mp3 files
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
        # Prefer 'original' source slightly over 'derivative' for same priority
        if f.get("source") == "derivative":
            prio += 10
        by_stem.setdefault(stem, []).append((prio, f))

    selected_files: list[dict[str, Any]] = []
    for stem in sorted(by_stem.keys()):
        candidates = sorted(by_stem[stem], key=lambda x: x[0])
        best_f = candidates[0][1]
        selected_files.append(best_f)

    audio_entries: list[dict[str, Any]] = []
    total_dur = 0
    item_title = meta.get("title") or item_id
    upload_date_raw = str(meta.get("date") or meta.get("publicdate") or "")
    upload_date = re.sub(r"[^\d]", "", upload_date_raw)[:8] or None

    for idx, f in enumerate(selected_files, 1):
        fname = f["name"]
        dur_s = parse_archive_duration(f.get("length") or f.get("duration"))
        total_dur += dur_s
        f_title = (f.get("title") or os.path.splitext(os.path.basename(fname))[0]).strip()
        if f_title.isdigit():
            f_title = f"الدرس {int(f_title)} | {item_title}"
        direct_url = f"https://archive.org/download/{item_id}/{urllib.parse.quote(fname)}"
        vid = f"archive__{person_id}__{clean_item_slug}__ep{idx:03d}"
        size_val = int(f["size"]) if str(f.get("size", "")).isdigit() else 0

        audio_entries.append({
            "pos": idx,
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

def ingest_offline_fixture(
    fixture_data: dict[str, Any],
    person_id: str,
    sheikh_name: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """
    Ingest an existing `<sheikh>_raw.json`, `full_channels/<channel>.json`, or composite test fixture
    into normalized `(channels, raw_playlists, archive_items, pdf_links)`.
    """
    channels: list[dict[str, Any]] = []
    playlists: list[dict[str, Any]] = []
    archive_items: list[dict[str, Any]] = []
    pdf_links: list[dict[str, Any]] = []

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

        vids_out: list[dict[str, Any]] = []
        for v_idx, v in enumerate(sp.get("videos") or [], 1):
            vid = v.get("yt_id") or v.get("vid")
            if not vid:
                continue
            ref = v_meta_lookup.get(vid, {})
            dur_raw = (
                v.get("dur_s")
                if v.get("dur_s") is not None
                else (v.get("duration") if v.get("duration") is not None else ref.get("duration"))
            )
            dur_s = int(round(float(dur_raw))) if isinstance(dur_raw, (int, float)) else 0
            up_date = v.get("upload_date") or ref.get("upload_date")
            v_stype = v.get("source_type") or ref.get("source_type") or (
                "youtube_stream" if ("بث مباشر" in (v.get("title") or "") or "#مباشر" in (v.get("title") or "")) else stype
            )
            vids_out.append({
                "pos": v.get("pos") or v.get("order_no") or v_idx,
                "vid": vid,
                "yt_id": vid,
                "title": (v.get("title") or ref.get("title") or f"الدرس {v_idx}").strip(),
                "dur_s": dur_s,
                "duration": dur_s,
                "upload_date": up_date,
                "source_type": v_stype,
                "yt_url": v.get("yt_url") or v.get("url") or ref.get("yt_url") or f"https://www.youtube.com/watch?v={vid}",
            })

        playlists.append({
            "id": pid,
            "playlist_id": pid,
            "order_no": sp.get("order_no") or idx,
            "title": ptitle,
            "yt_playlist_id": yt_pl_id,
            "url": sp.get("url") or (f"https://www.youtube.com/playlist?list={yt_pl_id}" if yt_pl_id else ""),
            "source_type": stype,
            "state": sp.get("state") or "completed",
            "expected_count": sp.get("expected_count") or len(vids_out),
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
            dur_raw = v.get("duration") if v.get("duration") is not None else v.get("dur_s")
            dur_s = int(round(float(dur_raw))) if isinstance(dur_raw, (int, float)) else 0
            vids_out.append({
                "pos": v.get("order_no") or v_idx,
                "vid": vid,
                "yt_id": vid,
                "title": (v.get("title") or f"الدرس {v_idx}").strip(),
                "dur_s": dur_s,
                "duration": dur_s,
                "upload_date": v.get("upload_date"),
                "source_type": "youtube_upload",
                "yt_url": v.get("url") or f"https://www.youtube.com/watch?v={vid}",
            })
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
            apps = uv.get("appearances") or []
            pos = apps[0].get("pos", len(orphan_uncl) + 1) if apps else len(orphan_uncl) + 1
            dur_raw = uv.get("dur_s") if uv.get("dur_s") is not None else uv.get("duration")
            dur_s = int(round(float(dur_raw))) if isinstance(dur_raw, (int, float)) else 0
            orphan_uncl.append({
                "pos": pos,
                "vid": vid,
                "yt_id": vid,
                "title": (uv.get("title") or vid).strip(),
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


def build_canonical_raw_json(
    person_id: str,
    sheikh_name: str,
    channels: list[dict[str, Any]],
    playlists: list[dict[str, Any]],
    archive_items: list[dict[str, Any]],
    pdf_extracted_links: list[dict[str, Any]],
    extra_books: list[dict[str, Any]] | None = None,
    photo_url: str | None = None,
) -> dict[str, Any]:
    """
    Deduplicate playlists and videos across all sources (YouTube + Archive.org + PDF links),
    match series to books/matns, and build the canonical `<person_id>_raw.json` structure.
    """
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    now_sql = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    # 1. Convert Archive.org multi-track audio items into series in `playlists` if not already present
    existing_pids = {pl.get("playlist_id") or pl.get("id") for pl in playlists}
    for arch in archive_items:
        arch_pid = f"archive__{arch['item_id']}"
        if arch_pid not in existing_pids and arch.get("files"):
            existing_pids.add(arch_pid)
            arch_vids = []
            for f in arch["files"]:
                arch_vids.append({
                    "pos": f.get("pos", 1),
                    "vid": f["vid"],
                    "yt_id": f["yt_id"],
                    "title": f["title"],
                    "dur_s": f["dur_s"],
                    "duration": f["duration"],
                    "upload_date": f.get("upload_date") or arch.get("upload_date"),
                    "source_type": "archive_org",
                    "yt_url": f["direct_url"],
                })
            playlists.append({
                "id": arch_pid,
                "playlist_id": arch_pid,
                "order_no": len(playlists) + 1,
                "title": arch["title"],
                "yt_playlist_id": arch_pid,
                "url": arch["details_url"],
                "source_type": "archive_org",
                "state": "completed",
                "expected_count": len(arch_vids),
                "video_count": len(arch_vids),
                "note": f"تصنيف: سلسلة صوتية من أرشيف الإنترنت (Archive.org: {arch['item_id']})",
                "matched_book": arch.get("matched_book"),
                "videos": arch_vids,
            })

    # 2. Discover books & match playlists/archive items to matns
    books = discover_person_books(
        sheikh_name=sheikh_name,
        playlists=playlists,
        archive_items=archive_items,
        extra_books=extra_books,
    )

    # 3. Identify all videos that belong to official/classified playlists
    classified_vids: set[str] = set()
    for pl in playlists:
        is_uncl = pl.get("yt_playlist_id") is None or "__unclassified" in str(pl.get("id", ""))
        if not is_uncl:
            for v in pl.get("videos", []):
                vid = v.get("vid") or v.get("yt_id")
                if vid:
                    classified_vids.add(vid)

    # 4. Clean unclassified playlists (remove videos already in classified playlists) & deduplicate
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
            dedup_vids.append({
                "pos": len(dedup_vids) + 1,
                "vid": vid,
                "yt_id": vid,
                "title": (v.get("title") or f"الدرس {len(dedup_vids) + 1}").strip(),
                "dur_s": dur_s,
                "duration": dur_s,
                "upload_date": v.get("upload_date"),
                "source_type": v.get("source_type") or pl.get("source_type") or "youtube_playlist",
                "yt_url": v.get("yt_url") or f"https://www.youtube.com/watch?v={vid}",
            })

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

    # 5. Build deduplicated `videos` / `unique_videos` with full `appearances`
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
                unique_videos_map[vid] = {
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
            else:
                duplicates_removed += 1
                # Upgrade duration or matched_book if previously missing
                if unique_videos_map[vid]["dur_s"] == 0 and dur_s > 0:
                    unique_videos_map[vid]["dur_s"] = dur_s
                    unique_videos_map[vid]["duration"] = dur_s
                if not unique_videos_map[vid].get("matched_book") and pl_matched_book:
                    unique_videos_map[vid]["matched_book"] = pl_matched_book

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
        "pdf_links_count": len(pdf_extracted_links),
        "pdf_playlists_count": pdf_playlists_count,
        "books_count": len(books),
        "matched_series_to_books_count": matched_series_count,
        "total_duration_s": total_dur_s,
        "total_duration_hours": round(total_dur_s / 3600.0, 2),
        "duplicates_removed": duplicates_removed,
    }

    sheikh_obj = {
        "id": person_id,
        "order_no": 1,
        "name": sheikh_name,
        "short_name": extract_short_name(sheikh_name),
        "photo": photo_url,
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
    offline_fixture: str | Path | dict[str, Any] | None = None,
    resolve_redirects: bool = False,
    fetch_live_unlisted_playlists: bool = False,
    output_path: str | Path | None = None,
) -> dict[str, Any]:
    """
    Main orchestrator for `person-discovery-intake`.
    Combines offline fixtures, PDF link extraction, YouTube URLs, Archive.org items, and books catalog
    into a unified `<person_id>_raw.json` dictionary (and writes to `output_path` if specified).
    """
    pid = normalize_person_id(name, explicit_id=person_id)
    channels: list[dict[str, Any]] = []
    playlists: list[dict[str, Any]] = []
    archive_items: list[dict[str, Any]] = []
    pdf_links: list[dict[str, Any]] = []
    extra_books: list[dict[str, Any]] = []
    photo_url: str | None = None

    # 1. Load offline fixture if provided
    if offline_fixture is not None:
        if isinstance(offline_fixture, dict):
            fix_data = offline_fixture
        else:
            fix_path = Path(offline_fixture)
            fix_data = json.loads(fix_path.read_text(encoding="utf-8"))
        if not name and fix_data.get("sheikh", {}).get("name"):
            name = fix_data["sheikh"]["name"]
        photo_url = fix_data.get("sheikh", {}).get("photo")
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
                pl_id = lnk["playlist_id"]
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
    ap.add_argument("--offline-fixture", default=None, help="Path to offline fixture JSON or existing <id>_raw.json")
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
