#!/usr/bin/env python3
"""
test_discovery_gates.py — Deterministic 3-Layer Quality Gate for `person-discovery-intake`.

Verifies:
  [Layer 1] PDF FlateDecode Stream & URI Annotation Extraction:
            Builds a real binary PDF with `zlib.compress` FlateDecode streams and `/URI` objects
            containing Unlisted YouTube Playlists, Video links, Archive.org items, and shortlinks,
            and verifies 100% extraction accuracy.
  [Layer 2] Multi-Source Unification, Deduplication & Book/Matn Matching:
            Transforms and unifies real YouTube data (from `/Users/macm1pro/REPOS/cheikh/` when
            available) + Archive.org metadata payloads (including `.mp3`/`.ogg` stem deduplication
            and duration parsing) + Books catalog, and verifies series-to-matn matching and
            anti-confusion science rules.
  [Layer 3] Canonical `<person_id>_raw.json` Schema & `sheikh-curation` Compatibility:
            Validates all required top-level and nested fields, types, durations, appearances,
            uniqueness invariants, and direct runtime compatibility with `sheikh-curation`.

Outputs `PASS (0 errors)` on success.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import zlib
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from discover_person import (  # noqa: E402
    attribute_shared_channel_owner,
    discover_author_books_in_shamela,
    discover_person,
    extract_links_from_pdf,
    find_shamela_authored_books,
    is_shared_channel_fixture,
    match_quran_tafsir_series,
    match_title_to_book,
    normalize_person_id,
    parse_archive_metadata_payload,
    unwrap_redirect_wrapper_url,
)


def build_sample_flatedecode_pdf(target_path: Path) -> None:
    """
    Create a genuine multi-object binary PDF containing both:
    - An uncompressed `/Annot` link object (`/URI (...)`)
    - A `FlateDecode` compressed stream (`zlib.compress`) containing embedded table rows,
      `/URI` links, unlisted YouTube playlists, YouTube videos, Archive.org buckets, and shortlinks.
    """
    stream_content = (
        "BT /F1 12 Tf 72 720 Td "
        "(Jamharat A'mal Index - Unlisted Playlists & Archive Buckets) Tj ET\n"
        "% Embedded URI annotations and raw links inside FlateDecode stream:\n"
        "<< /Type /Action /S /URI /URI (https://www.youtube.com/playlist?list=PL9saDKf7tQ7uPlqhlafX3tRbnr4oKrvQG) >>\n"
        "<< /Type /Action /S /URI /URI (https://www.youtube.com/playlist?list=PLUnlistedSheikhAmoud00123456789) >>\n"
        "Video 1: https://youtu.be/XCO-dOUGVxU\n"
        "Video 2: https://www.youtube.com/watch?v=buIV_WBVY2U\n"
        "Archive Bucket 1: https://archive.org/details/iysalo-salik_202103\n"
        "Archive Bucket 2: https://archive.org/download/Kitab.Alma9asid/001.mp3\n"
        "Shortlink: https://bit.ly/3xYzAmoud1\n"
    ).encode("utf-8")

    compressed_stream = zlib.compress(stream_content, level=9)

    pdf_chunks = [
        b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n",
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n",
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Annots [5 0 R] >>\nendobj\n",
        (
            f"4 0 obj\n<< /Length {len(compressed_stream)} /Filter /FlateDecode >>\nstream\r\n".encode("ascii")
            + compressed_stream
            + b"\r\nendstream\nendobj\n"
        ),
        (
            b"5 0 obj\n<< /Type /Annot /Subtype /Link /Rect [72 680 400 700] "
            b"/A << /Type /Action /S /URI /URI (https://www.youtube.com/playlist?list=PLAnnotUnlistedPlaylist11223344) >> >>\nendobj\n"
        ),
        b"trailer\n<< /Root 1 0 R /Size 6 >>\n%%EOF\n",
    ]
    target_path.write_bytes(b"".join(pdf_chunks))


def test_gate1_pdf_flatedecode_extraction(errors: list[str]) -> list[dict[str, Any]]:
    """Layer 1: Test binary PDF FlateDecode decompression and link extraction."""
    with tempfile.TemporaryDirectory() as tmpdir:
        pdf_path = Path(tmpdir) / "jamharat_test_index.pdf"
        build_sample_flatedecode_pdf(pdf_path)
        links = extract_links_from_pdf(pdf_path, resolve_redirects=False)

    by_pl = {lnk["playlist_id"]: lnk for lnk in links if lnk.get("playlist_id")}
    by_vid = {lnk["video_id"]: lnk for lnk in links if lnk.get("video_id")}
    by_arch = {lnk["archive_id"]: lnk for lnk in links if lnk.get("archive_id")}
    shortlinks = [lnk for lnk in links if lnk.get("link_type") == "shortlink"]

    expected_pls = {
        "PL9saDKf7tQ7uPlqhlafX3tRbnr4oKrvQG",
        "PLUnlistedSheikhAmoud00123456789",
        "PLAnnotUnlistedPlaylist11223344",
    }
    for ep in expected_pls:
        if ep not in by_pl:
            errors.append(f"[Gate 1] Missing expected playlist_id from PDF: {ep}")

    if "PL9saDKf7tQ7uPlqhlafX3tRbnr4oKrvQG" in by_pl:
        method = by_pl["PL9saDKf7tQ7uPlqhlafX3tRbnr4oKrvQG"].get("extraction_method")
        if method != "FlateDecode_stream":
            errors.append(f"[Gate 1] Expected extraction_method='FlateDecode_stream', got {method!r}")

    for ev in ("XCO-dOUGVxU", "buIV_WBVY2U"):
        if ev not in by_vid:
            errors.append(f"[Gate 1] Missing expected video_id from PDF FlateDecode stream: {ev}")

    for ea in ("iysalo-salik_202103", "Kitab.Alma9asid"):
        if ea not in by_arch:
            errors.append(f"[Gate 1] Missing expected archive_id from PDF FlateDecode stream: {ea}")

    if not any("bit.ly/3xYzAmoud1" in lnk["url"] for lnk in shortlinks):
        errors.append("[Gate 1] Missing expected shortlink https://bit.ly/3xYzAmoud1 from PDF stream")

    print(
        f"[Gate 1] PDF FlateDecode & URI Extraction: extracted {len(links)} links "
        f"({len(by_pl)} playlists, {len(by_vid)} videos, {len(by_arch)} archive items, {len(shortlinks)} shortlinks)."
    )
    return links


def test_gate2_unification_and_book_matching(errors: list[str]) -> dict[str, Any]:
    """Layer 2: Test YouTube + Archive.org + Books unification, deduplication, and matn matching."""
    real_omari_path = Path("/Users/macm1pro/REPOS/cheikh/data/curated_sheikhs/omari_raw.json")
    if real_omari_path.exists():
        base_fixture = json.loads(real_omari_path.read_text(encoding="utf-8"))
    else:
        # Fallback realistic fixture if run outside local repo environment
        base_fixture = {
            "sheikh": {
                "id": "omari",
                "order_no": 11,
                "name": "علي محمود العمري",
                "short_name": "العمري",
                "photo": None,
            },
            "raw_playlists_count": 2,
            "unique_videos_count": 3,
            "raw_series": [
                {
                    "id": "PLa3XSU7qw_Yl2R_ovnnJN5EdsU6T8v35r",
                    "order_no": 1,
                    "title": "آداب سلوك المريد",
                    "yt_playlist_id": "PLa3XSU7qw_Yl2R_ovnnJN5EdsU6T8v35r",
                    "state": "completed",
                    "expected_count": 2,
                    "videos": [
                        {
                            "pos": 1,
                            "yt_id": "pBvfBNnfEFU",
                            "title": "رسالة آداب سلوك المريد_ المجلس الأول _ للإمام الحبيب عبد الله بن علوي الحداد",
                            "duration": 3979,
                        },
                        {
                            "pos": 2,
                            "yt_id": "G5n5sONJDio",
                            "title": "رسالة آداب سلوك المريد_ المجلس الثاني _ للإمام الحبيب عبد الله بن علوي الحداد",
                            "duration": 2295,
                        },
                    ],
                },
                {
                    "id": "PLa3XSU7qw_Ymxru2Q5gP8WfdMovgl18ie",
                    "order_no": 2,
                    "title": "المنهاج في شعب الإيمان",
                    "yt_playlist_id": "PLa3XSU7qw_Ymxru2Q5gP8WfdMovgl18ie",
                    "state": "completed",
                    "expected_count": 1,
                    "videos": [
                        {
                            "pos": 1,
                            "yt_id": "N3aD3QWzlfI",
                            "title": "شرح المنهاج في شعب الإيمان/ المجلس الرابع — 15 رمضان 1444",
                            "duration": 4035,
                        }
                    ],
                },
            ],
            "unique_videos": [
                {
                    "yt_id": "pBvfBNnfEFU",
                    "title": "رسالة آداب سلوك المريد_ المجلس الأول _ للإمام الحبيب عبد الله بن علوي الحداد",
                    "yt_url": "https://www.youtube.com/watch?v=pBvfBNnfEFU",
                    "duration": 3979,
                    "appearances": [],
                },
                {
                    "yt_id": "G5n5sONJDio",
                    "title": "رسالة آداب سلوك المريد_ المجلس الثاني _ للإمام الحبيب عبد الله بن علوي الحداد",
                    "yt_url": "https://www.youtube.com/watch?v=G5n5sONJDio",
                    "duration": 2295,
                    "appearances": [],
                },
                {
                    "yt_id": "N3aD3QWzlfI",
                    "title": "شرح المنهاج في شعب الإيمان/ المجلس الرابع — 15 رمضان 1444",
                    "yt_url": "https://www.youtube.com/watch?v=N3aD3QWzlfI",
                    "duration": 4035,
                    "appearances": [],
                },
            ],
        }

    # Inject realistic Archive.org metadata payloads (testing .mp3 vs .ogg derivative deduplication
    # and missing website episode 024.mp3 recovery)
    base_fixture["archive_payloads"] = [
        {
            "item_id": "iysalo-salik_202103",
            "metadata": {
                "identifier": "iysalo-salik_202103",
                "title": "شرح كتاب إيصال السالك في أصول الإمام مالك",
                "creator": "علي محمود العمري",
                "uploader": "archive_uploader@example.org",
                "mediatype": "audio",
                "date": "2021-03-15",
            },
            "files": [
                {
                    "name": "001.mp3",
                    "source": "original",
                    "format": "VBR MP3",
                    "length": "3120.4",
                    "size": "24960000",
                    "title": "الدرس 1: مقدمة إيصال السالك",
                },
                {
                    "name": "001.ogg",
                    "source": "derivative",
                    "format": "Ogg Vorbis",
                    "length": "3120.4",
                    "size": "12000000",
                },
                {
                    "name": "024.mp3",
                    "source": "original",
                    "format": "VBR MP3",
                    "length": "01:15:30",
                    "size": "36240000",
                    "title": "الدرس 24: قاعدة الأمور تتبع مقاصدها — تمام الكتاب",
                },
                {
                    "name": "iysalo-salik_202103_meta.xml",
                    "source": "metadata",
                    "format": "Metadata",
                },
            ],
        },
        {
            "item_id": "Kitab.Alma9asid",
            "metadata": {
                "identifier": "Kitab.Alma9asid",
                "title": "شرح كتاب المقاصد من الموافقات للشاطبي",
                "creator": "علي محمود العمري",
                "uploader": "archive_uploader@example.org",
                "mediatype": "audio",
                "date": "2022-06-10",
            },
            "files": [
                {
                    "name": "001.m4a",
                    "source": "original",
                    "format": "MPEG-4 Audio",
                    "length": "2845",
                    "size": "18500000",
                    "title": "المجلس الأول من كتاب المقاصد",
                }
            ],
        },
    ]

    with tempfile.TemporaryDirectory() as tmpdir:
        pdf_path = Path(tmpdir) / "index_jamhara.pdf"
        build_sample_flatedecode_pdf(pdf_path)
        out_json_path = Path(tmpdir) / "omari_raw.json"

        raw_result = discover_person(
            name="الدكتور علي محمود العمري",
            person_id=None,  # Test automatic person_id normalization -> "omari"
            index_pdfs=[pdf_path],
            offline_fixture=base_fixture,
            output_path=out_json_path,
        )

    # 1. Verify person_id normalization
    if raw_result["person_id"] != "omari":
        errors.append(f"[Gate 2] Expected normalized person_id='omari', got {raw_result['person_id']!r}")

    # 2. Verify Archive.org parsing & derivative deduplication (.ogg filtered out)
    arch_items = {a["item_id"]: a for a in raw_result["archive_items"]}
    if "iysalo-salik_202103" not in arch_items:
        errors.append("[Gate 2] Missing Archive.org item 'iysalo-salik_202103'")
    else:
        iysal = arch_items["iysalo-salik_202103"]
        if iysal["audio_files_count"] != 2:
            errors.append(
                f"[Gate 2] Expected 2 deduplicated audio files in iysalo-salik_202103 (.ogg excluded), got {iysal['audio_files_count']}"
            )
        durs = [f["dur_s"] for f in iysal["files"]]
        if durs != [3120, 4530]:
            errors.append(f"[Gate 2] Expected parsed durations [3120, 4530], got {durs}")
        if not iysal["files"][1]["direct_url"].endswith("/iysalo-salik_202103/024.mp3"):
            errors.append(f"[Gate 2] Unexpected direct_url: {iysal['files'][1]['direct_url']}")

    # 3. Verify Series-to-Book / Matn Matching & Science Anti-Confusion Rules
    pls_by_title = {pl["title"]: pl for pl in raw_result["playlists"]}
    if "آداب سلوك المريد" in pls_by_title:
        mb = pls_by_title["آداب سلوك المريد"].get("matched_book")
        if not mb or mb["book_id"] != "tazkia:adab_suluk_al_murid":
            errors.append(f"[Gate 2] Failed to match 'آداب سلوك المريد' to Haddad's book: {mb}")

    # Test anti-confusion rules directly on matn matcher
    sanusi_match = match_title_to_book("شرح مقدمات الإمام السنوسي")
    if not sanusi_match or sanusi_match["science"] != "العقيدة وعلم الكلام":
        errors.append(
            f"[Gate 2] Science anti-confusion violation: 'مقدمات السنوسي' must map to 'العقيدة وعلم الكلام', got {sanusi_match}"
        )

    usul_match = match_title_to_book("شرح كتاب إيصال السالك في أصول الإمام مالك")
    maqasid_match = match_title_to_book("شرح كتاب المقاصد من الموافقات للشاطبي")
    if not usul_match or usul_match["science"] != "أصول الفقه":
        errors.append(f"[Gate 2] Expected 'أصول الفقه' for إيصال السالك, got {usul_match}")
    if not maqasid_match or maqasid_match["science"] != "مقاصد الشريعة":
        errors.append(f"[Gate 2] Expected 'مقاصد الشريعة' for الموافقات, got {maqasid_match}")

    # Verify authored book detection ('في ستة أيام' by علي محمود العمري)
    books_by_id = {b["book_id"]: b for b in raw_result["books"]}
    if "fikr:fi_sittat_ayyam" not in books_by_id:
        errors.append("[Gate 2] Missing authored book 'fikr:fi_sittat_ayyam' for علي محمود العمري")
    elif not books_by_id["fikr:fi_sittat_ayyam"].get("is_authored_by_person"):
        errors.append("[Gate 2] Expected is_authored_by_person=True for 'في ستة أيام'")

    print(
        f"[Gate 2] Unification & Matn Matching: {len(raw_result['playlists'])} series, "
        f"{len(raw_result['videos'])} unique videos/tracks, {len(raw_result['books'])} books matched."
    )
    return raw_result


def test_gate3_schema_and_sheikh_curation_compatibility(
    raw_data: dict[str, Any],
    errors: list[str],
) -> None:
    """Layer 3: Strict Schema Validation & `sheikh-curation` Runtime Compatibility."""
    required_top_keys = [
        "person_id",
        "sheikh_name",
        "discovered_at",
        "sheikh",
        "channels",
        "playlists",
        "videos",
        "archive_items",
        "pdf_extracted_links",
        "books",
        "stats",
        "raw_playlists_count",
        "unique_videos_count",
        "raw_series",
        "unique_videos",
    ]
    for k in required_top_keys:
        if k not in raw_data:
            errors.append(f"[Gate 3] Missing required top-level key in <person_id>_raw.json: {k!r}")

    if raw_data.get("unique_videos_count") != len(raw_data.get("videos", [])):
        errors.append("[Gate 3] unique_videos_count != len(videos)")

    if len(raw_data.get("raw_series", [])) != len(raw_data.get("playlists", [])):
        errors.append("[Gate 3] len(raw_series) != len(playlists)")

    seen_vids: set[str] = set()
    for idx, v in enumerate(raw_data.get("videos", []), 1):
        vid = v.get("vid")
        yt_id = v.get("yt_id")
        if not vid or vid != yt_id:
            errors.append(f"[Gate 3] Video #{idx} has invalid or mismatched vid={vid!r} / yt_id={yt_id!r}")
        if vid in seen_vids:
            errors.append(f"[Gate 3] Duplicate vid={vid!r} found in unique videos list")
        seen_vids.add(vid)

        for req_v_key in ("title", "dur_s", "duration", "upload_date", "playlist_id", "playlist_title", "source_type", "yt_url", "appearances"):
            if req_v_key not in v:
                errors.append(f"[Gate 3] Video {vid} missing required field {req_v_key!r}")

        if not isinstance(v.get("dur_s"), int) or v.get("dur_s") != v.get("duration"):
            errors.append(f"[Gate 3] Video {vid} has invalid dur_s={v.get('dur_s')!r} / duration={v.get('duration')!r}")

        apps = v.get("appearances")
        if not isinstance(apps, list) or len(apps) == 0:
            errors.append(f"[Gate 3] Video {vid} must have non-empty appearances list")
        else:
            for a in apps:
                for ak in ("raw_series_id", "raw_series_title", "pos", "is_unclassified"):
                    if ak not in a:
                        errors.append(f"[Gate 3] Appearance in {vid} missing {ak!r}")

    # Test direct runtime compatibility with `sheikh-curation`'s `hijri_interpolator.py`
    interp_script = Path("/Users/macm1pro/REPOS/SKILLS/sheikh-curation/scripts/hijri_interpolator.py")
    if interp_script.exists():
        try:
            spec = importlib.util.spec_from_file_location("hijri_interpolator", interp_script)
            if spec and spec.loader:
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                explicit_dates, best_interp = mod.build_interpolated_dates(raw_data)
                if not isinstance(explicit_dates, dict) or not isinstance(best_interp, dict):
                    errors.append("[Gate 3] hijri_interpolator.build_interpolated_dates returned non-dict")
        except Exception as exc:
            errors.append(f"[Gate 3] Runtime incompatibility with hijri_interpolator.py: {exc}")

    print(
        f"[Gate 3] Canonical Schema & sheikh-curation Compatibility: verified "
        f"{len(seen_vids)} unique videos and {len(raw_data.get('playlists', []))} playlists."
    )


def test_gate4_cycle2_real_data_regressions(errors: list[str]) -> None:
    """
    Layer 4 (Cycle 2 Real-Data Regressions):
      1. Google Docs redirect-wrapped URLs (`%3D` encoded `list=`), dual `v=` + `list=` extraction,
         font/PKI/license noise URL filtering, and scheme-insensitive `bit.ly` deduplication (plus
         live verification on `jamhara.pdf` when present).
      2. Arabic proclitic boundary matching (`لقطر الندى`, `للقطر`, `بجمع الجوامع`) & Quran Surah Tafsir matching.
      3. Shamela4 8,589-book index author lookup (`الشعراوي`, `البوطي`, `الددو`, `الخضير`, `الفوزان`).
      4. Shared-channel scholar attribution (`tankert-shared` -> `sariri` vs `bardoni`),
         playlist-summary `expected_count` preservation, and unclassified bucket non-matching.
    """
    # 1. Google redirect unwrapping & PDF noise filtering
    wrapped_url = (
        "https://www.google.com/url?q=https://www.youtube.com/playlist?list%3DPL2-FkZlJhxqUG3274-L28g29_61_B9L3B"
        "&sa=D&ust=1549982491243000&usg=AFQjCNG123"
    )
    unwrapped = unwrap_redirect_wrapper_url(wrapped_url)
    if unwrapped != "https://www.youtube.com/playlist?list=PL2-FkZlJhxqUG3274-L28g29_61_B9L3B":
        errors.append(f"[Gate 4] Failed to unwrap Google redirect URL: got {unwrapped!r}")

    with tempfile.TemporaryDirectory() as tmpdir:
        pdf_path = Path(tmpdir) / "jamhara_regression.pdf"
        stream_bytes = (
            f"<< /Type /Action /S /URI /URI ({wrapped_url}) >>\n"
            "<< /Type /Action /S /URI /URI (https://www.youtube.com/watch?v=9x2F3hA5JIs&list=PL2-FkZlJhxqV402759482759) >>\n"
            "<< /Type /Action /S /URI /URI (http://bit.ly/2I92M2s) >>\n"
            "<< /Type /Action /S /URI /URI (http://bit.ly) >>\n"
            "<< /Type /Action /S /URI /URI (http://www.microsoft.com/pki/certs/MicRooCerAut_2010-06-23.crt) >>\n"
            "<< /Type /Action /S /URI /URI (http://en.wikipedia.org/wiki/MIT_License) >>\n"
            "<< /Type /Action /S /URI /URI (http://www.linotype.com) >>\n"
        ).encode("utf-8")
        comp = zlib.compress(stream_bytes, level=9)
        pdf_bytes = (
            b"%PDF-1.7\n1 0 obj\n<< /Length "
            + str(len(comp)).encode("ascii")
            + b" /Filter /FlateDecode >>\nstream\r\n"
            + comp
            + b"\r\nendstream\nendobj\n%%EOF\n"
        )
        pdf_path.write_bytes(pdf_bytes)
        reg_links = extract_links_from_pdf(pdf_path, resolve_redirects=False)

    reg_pls = {l["playlist_id"]: l for l in reg_links if l.get("playlist_id")}
    if "PL2-FkZlJhxqUG3274-L28g29_61_B9L3B" not in reg_pls:
        errors.append("[Gate 4] Failed to extract percent-encoded playlist_id from Google redirect URL in PDF")
    if "PL2-FkZlJhxqV402759482759" not in reg_pls:
        errors.append("[Gate 4] Failed to extract playlist_id from watch?v=...&list=... URL in PDF")
    elif reg_pls["PL2-FkZlJhxqV402759482759"].get("video_id") != "9x2F3hA5JIs":
        errors.append("[Gate 4] Lost video_id on watch?v=...&list=... URL in PDF")

    short_urls = [l["url"] for l in reg_links if l["link_type"] == "shortlink"]
    if len(short_urls) != 1 or short_urls[0] != "http://bit.ly/2I92M2s":
        errors.append(f"[Gate 4] Expected exactly 1 deduplicated shortlink ['http://bit.ly/2I92M2s'], got {short_urls}")

    noise_found = [l["url"] for l in reg_links if any(k in l["url"] for k in ("microsoft.com", "wikipedia.org", "linotype.com"))]
    if noise_found:
        errors.append(f"[Gate 4] Embedded font/PKI/license noise URLs leaked into PDF links: {noise_found}")

    real_jamhara = Path("/Users/macm1pro/.gemini/antigravity/brain/a66db81b-9ed5-46c9-a1da-c3de34a35d9c/scratch/jamhara.pdf")
    if real_jamhara.exists():
        j_links = extract_links_from_pdf(real_jamhara, resolve_redirects=False)
        j_pls = [l for l in j_links if l["link_type"] == "youtube_playlist"]
        j_short = [l for l in j_links if l["link_type"] == "shortlink"]
        if len(j_pls) < 14:
            errors.append(f"[Gate 4] Expected >=14 YouTube playlists from real jamhara.pdf, got {len(j_pls)}")
        if len(j_short) != 17:
            errors.append(f"[Gate 4] Expected 17 unique shortlinks from real jamhara.pdf, got {len(j_short)}")

    # 2. Proclitic-aware matn matching & Quran Surah Tafsir matching
    proclitic_cases = [
        ("شرح الفاكهي لقطر الندى", "nahw:qatr_al_nada"),
        ("شرح الفاكهي للقطر", "nahw:qatr_al_nada"),
        ("التعريف بجمع الجوامع", "ossoul:jam_al_jawami"),
        ("شرح التحفة السنية", "nahw:ajurrumiyya"),
        ("شرح البناء والأساس", "sarf:bina_al_afaal"),
        ("مدارسة كتاب الداء والدواء", "tazkia:al_daa_wal_dawa"),
        ("قراءة كتاب نور اليقين في سيرة سيد المرسلين", "sirah:nur_al_yaqin"),
    ]
    for title_in, expected_book_id in proclitic_cases:
        m = match_title_to_book(title_in)
        if not m or m["book_id"] != expected_book_id:
            errors.append(f"[Gate 4] Proclitic/Matn match failed for {title_in!r}: expected {expected_book_id!r}, got {m}")

    tafsir_cases = [
        ("تفسير سورة البقرة", "tafsir:surah_002"),
        ("خواطر الشيخ الشعراوي حول سورة آل عمران", "tafsir:surah_003"),
        ("اللمسات البيانية في سورة الكهف", "tafsir:surah_018"),
        ("تفسير جزء عم", "tafsir:juz_amma"),
    ]
    for title_in, expected_book_id in tafsir_cases:
        m = match_title_to_book(title_in)
        if not m or m["book_id"] != expected_book_id:
            errors.append(f"[Gate 4] Quran Tafsir match failed for {title_in!r}: expected {expected_book_id!r}, got {m}")

    # 3. Shamela4 Full DB Index (8,589 books) author discovery
    for sh_name, pid, min_expected in [
        ("محمد متولي الشعراوي", "shaarawy", 2),
        ("محمد سعيد رمضان البوطي", "bouti", 3),
        ("محمد الحسن الددو الشنقيطي", "dedew", 3),
        ("عبد الكريم الخضير", "khudayr", 15),
        ("صالح الفوزان", "fawzan", 15),
    ]:
        sh_books = find_shamela_authored_books(sh_name, person_id=pid)
        if len(sh_books) < min_expected:
            errors.append(
                f"[Gate 4] Shamela4 author lookup for {sh_name} ({pid}) returned {len(sh_books)} books, expected >={min_expected}"
            )

    # 4. Shared-channel attribution (`tankert-shared`), playlist summary `expected_count`, and unclassified non-matching
    shared_fixture = {
        "channel_key": "tankert-shared",
        "sheikh_id": "shared",
        "sheikh_name": "مشترك (السريري والبردوني)",
        "channel_id": "UC_tankert_shared",
        "playlists": [
            {
                "playlist_id": "PL_sariri_1",
                "title": "شرح جمع الجوامع - الشيخ أحمد السريري",
                "video_count": 15,
                "videos": [{"vid": "v_sar_1", "title": "الدرس الأول - الشيخ أحمد السريري", "duration": 1800}],
            },
            {
                "playlist_id": "PL_bardoni_1",
                "title": "شرح قطر الندى للشيخ إبراهيم البردوني",
                "video_count": 12,
                "videos": [{"vid": "v_bar_1", "title": "الدرس الأول - الشيخ إبراهيم البردوني", "duration": 1500}],
            },
            {
                "playlist_id": "PL_summary_only",
                "title": "شرح مختصر خليل - الشيخ أحمد السريري",
                "video_count": 42,
                "videos": [],
            },
        ],
        "unclassified_playlist": {
            "playlist_id": "tankert-shared__unclassified",
            "title": "غير مصنف",
            "videos": [
                {"vid": "v_uncl_sar", "title": "تفسير سورة البقرة - الشيخ أحمد السريري", "duration": 1200},
                {"vid": "v_uncl_bar", "title": "درس للشيخ إبراهيم البردوني", "duration": 900},
            ],
        },
    }
    if not is_shared_channel_fixture(shared_fixture):
        errors.append("[Gate 4] is_shared_channel_fixture returned False for tankert-shared fixture")

    res_sar = discover_person("الشيخ أحمد السريري", person_id="sariri", offline_fixture=shared_fixture)
    res_bar = discover_person("الشيخ إبراهيم البردوني", person_id="bardoni", offline_fixture=shared_fixture)

    sar_pids = {p["id"] for p in res_sar["playlists"]}
    bar_pids = {p["id"] for p in res_bar["playlists"]}
    if "PL_bardoni_1" in sar_pids or "PL_sariri_1" not in sar_pids:
        errors.append(f"[Gate 4] Shared channel attribution failed for sariri: got playlists {sar_pids}")
    if "PL_sariri_1" in bar_pids or "PL_bardoni_1" not in bar_pids:
        errors.append(f"[Gate 4] Shared channel attribution failed for bardoni: got playlists {bar_pids}")

    # Verify expected_count preserved on summary-only playlist (42 even though videos=[])
    pl_sum = next((p for p in res_sar["playlists"] if p["id"] == "PL_summary_only"), None)
    if not pl_sum or pl_sum.get("expected_count") != 42:
        errors.append(f"[Gate 4] Failed to preserve expected_count=42 on summary playlist: {pl_sum}")

    # Verify unclassified playlist is never matched to a book (even when its video mentions 'تفسير سورة البقرة')
    uncl_sar = next((p for p in res_sar["playlists"] if "__unclassified" in p["id"]), None)
    if not uncl_sar:
        errors.append("[Gate 4] Missing unclassified playlist for sariri in shared channel")
    elif uncl_sar.get("matched_book") is not None:
        errors.append(f"[Gate 4] Unclassified playlist must have matched_book=None, got {uncl_sar.get('matched_book')}")

    print(
        "[Gate 4] Cycle 2 Real-Data Regressions: verified Google redirect unwrapping, PDF noise filter, "
        "proclitic & Surah Tafsir matchers, Shamela4 8,589-book author index, and shared-channel attribution."
    )


def test_gate5_shamela_series_matcher_and_cross_source_linking(
    raw_data: dict[str, Any],
    errors: list[str],
) -> None:
    """
    Layer 5 (Cycle 9 — Shamela 8,589-Book Auto-Series Matcher, Archive.org Episode Sorting/Spam Cleanup,
    and Cross-Source Archive.org + YouTube Series Linking & Gap Recovery):
      1. Shamela 8,589-book index series matcher + expanded Matn KB + glued/video-level Quran Surah Tafsir,
         plus strict generic-topic stoplist anti-false-positive verification.
      2. Archive.org multi-format (`.mp4`/`.mp3`) parsing, natural episode sorting (`aqeeda (2)` before `aqeeda (10)`),
         Arabizi stem handling (`leqa2_eliman_16`), stem-first episode extraction (`003.mp3` with `تتمة أوقات الصلاة 02`),
         and ID3 URL spam (`www.naseemalsham.com`) cleanup.
      3. Cross-source YouTube + Archive.org series linking (`linked_archive_item`), episode-level `archive_direct_url`
         attachment, missing episode gap recovery (`024.mp3` in `إيصال السالك`), and duplicate Archive item unification
         (`we-Nafs` MP4 + `we-Nafs_A` MP3).
    """
    # 1. Shamela 8,589-Book Auto-Series Matcher & Expanded Matn KB
    series_match_cases = [
        ("شرح كتاب الشفا بتعريف حقوق المصطفى", "hadith:shifa_qadi_iyad"),
        ("شرح الدرر البهية للشوكاني", "fiqh:al_durar_al_bahiyya"),
        ("شرح متن الدرر اللوامع في أصل مقرأ الإمام نافع", "tajweed:al_durar_al_lawami"),
        ("شرح نظم عبيد ربه", "nahw:nazm_ubayd_rabbih"),
        ("شرح كتاب التسهيل لعلوم التنزيل", "tafsir:al_tashil_ibn_juzayy"),
        ("شرح منظومة الزمزمي في علوم القرآن", "tafsir:manzumat_al_zamzami"),
        ("تفسيرسورة الأعراف", "tafsir:surah_007"),
        ("فسيرسورة الأنعام", "tafsir:surah_006"),
    ]
    for title_in, expected_id in series_match_cases:
        m = match_title_to_book(title_in)
        if not m or m["book_id"] != expected_id:
            errors.append(f"[Gate 5] Series book match failed for {title_in!r}: expected {expected_id!r}, got {m}")

    # Video-level Surah Tafsir fallback when playlist title is generic
    v_tafsir = match_title_to_book(
        "سلسلة دروس التفسير",
        video_titles=[
            "الدرس 1 - تفسير سورة الفرقان الآية 1-10",
            "الدرس 2 - تفسير سورة الفرقان الآية 11-20",
            "الدرس 3 - تفسير سورة الفرقان الآية 21-30",
        ],
    )
    if not v_tafsir or v_tafsir["book_id"] != "tafsir:surah_025":
        errors.append(f"[Gate 5] Video-level Surah Tafsir fallback failed: got {v_tafsir}")

    # Direct Shamela 8,589-book index series matching for books outside static MATN_KNOWLEDGE_BASE
    shamela_series_cases = [
        "شرح روضة الناظر وجنة المناظر",
        "التعليق على زاد المعاد في هدي خير العباد",
        "شرح كتاب المحرر في الحديث",
    ]
    for stitle in shamela_series_cases:
        sm = match_title_to_book(stitle)
        if not sm or not str(sm.get("book_id", "")).startswith("shamela:"):
            errors.append(f"[Gate 5] Expected Shamela 8,589-book index match for {stitle!r}, got {sm}")

    # Anti-false-positive stoplist check on generic topic titles
    for generic_title in ("دروس العقيدة", "فتاوى الصيام", "خطب الجمعة", "مجالس رمضان", "دروس الفقه"):
        gm = match_title_to_book(generic_title)
        if gm is not None:
            errors.append(f"[Gate 5] False-positive book match on generic topic title {generic_title!r}: {gm}")

    # Verify live series matching across all 17 curated sheikhs if available on disk
    curated_dir = Path("/Users/macm1pro/REPOS/cheikh/data/curated_sheikhs")
    if curated_dir.exists():
        total_matched = 0
        for p in sorted(curated_dir.glob("*_raw.json")):
            d = json.loads(p.read_text(encoding="utf-8"))
            for s in d.get("raw_series", []):
                sid = str(s.get("id") or "")
                if s.get("yt_playlist_id") is None or "__unclassified" in sid:
                    continue
                v_titles = [v.get("title", "") for v in s.get("videos", [])[:8]]
                if match_title_to_book(s.get("title", ""), v_titles):
                    total_matched += 1
        if total_matched < 285:
            errors.append(
                f"[Gate 5] Expected >=285 matched series across 17 curated sheikhs, got {total_matched}"
            )

    # 2. Archive.org natural episode sorting, spam ID3 cleanup, and multi-format (.mp4) support
    aqeeda_payload = {
        "metadata": {
            "identifier": "Aqeeda28_test",
            "title": "شرح العقيدة الطحاوية",
            "creator": "محمد سعيد رمضان البوطي",
            "mediatype": "audio",
            "date": "2019-05-01",
        },
        "files": [
            {
                "name": "aqeeda (10).mp3",
                "source": "original",
                "length": "2500",
                "size": "20000000",
                "title": "www.naseemalsham.com",
            },
            {
                "name": "aqeeda (2).mp3",
                "source": "original",
                "length": "2400",
                "size": "19000000",
                "title": "http://www.naseemalsham.com",
            },
            {
                "name": "aqeeda (1).mp3",
                "source": "original",
                "length": "2300",
                "size": "18000000",
                "title": "www.naseemalsham.com",
            },
            {
                "name": "003.mp3",
                "source": "original",
                "track": "03",
                "length": "2600",
                "size": "21000000",
                "title": "تتمة أوقات الصلاة 02",
            },
            {
                "name": "leqa2_eliman_16.mp4",
                "source": "original",
                "length": "1800",
                "size": "45000000",
            },
            {
                "name": "leqa2_eliman_16.ogv",
                "source": "derivative",
                "length": "1800",
                "size": "15000000",
            },
        ],
    }
    parsed_aq = parse_archive_metadata_payload("Aqeeda28_test", aqeeda_payload, "bouti")
    ep_nums = [f["episode_num"] for f in parsed_aq["files"]]
    if ep_nums != [1, 2, 3, 10, 16]:
        errors.append(f"[Gate 5] Expected natural episode_num sort [1, 2, 3, 10, 16], got {ep_nums}")
    titles_out = [f["title"] for f in parsed_aq["files"]]
    if any("naseemalsham" in t for t in titles_out):
        errors.append(f"[Gate 5] ID3 URL spam leaked into normalized titles: {titles_out}")
    if titles_out[0] != "الدرس 1 | شرح العقيدة الطحاوية":
        errors.append(f"[Gate 5] Expected clean Arabic title for aqeeda (1).mp3, got {titles_out[0]!r}")
    if titles_out[2] != "الدرس 3: تتمة أوقات الصلاة 02":
        errors.append(f"[Gate 5] Expected 'الدرس 3: تتمة أوقات الصلاة 02' for 003.mp3, got {titles_out[2]!r}")

    # 3. Cross-Source YouTube + Archive.org series linking & missing episode recovery
    cross_source_fixture = {
        "sheikh": {"id": "sariri", "name": "الشيخ أحمد السريري"},
        "raw_series": [
            {
                "id": "PL_sariri_iysal",
                "title": "شرح كتاب إيصال السالك في أصول الإمام مالك",
                "yt_playlist_id": "PL_sariri_iysal",
                "expected_count": 24,
                "videos": [
                    {
                        "pos": 1,
                        "yt_id": "yt_iysal_01",
                        "title": "الدرس الأول: مقدمة إيصال السالك",
                        "duration": 3120,
                    },
                    {
                        "pos": 2,
                        "yt_id": "yt_iysal_23",
                        "title": "الدرس الثالث والعشرون: المباحث الأصولية",
                        "duration": 2950,
                    },
                ],
            }
        ],
        "unique_videos": [],
        "archive_payloads": [
            {
                "item_id": "iysalo-salik_202103",
                "metadata": {
                    "identifier": "iysalo-salik_202103",
                    "title": "شرح كتاب إيصال السالك في أصول الإمام مالك",
                    "creator": "الشيخ أحمد السريري",
                    "mediatype": "audio",
                    "date": "2021-03-15",
                },
                "files": [
                    {
                        "name": "001.mp3",
                        "source": "original",
                        "length": "3120.4",
                        "size": "24960000",
                        "title": "الدرس 1: مقدمة إيصال السالك",
                    },
                    {
                        "name": "024.mp3",
                        "source": "original",
                        "length": "01:15:30",
                        "size": "36240000",
                        "title": "الدرس 24: قاعدة الأمور تتبع مقاصدها — تمام الكتاب",
                    },
                ],
            }
        ],
    }
    res_cross = discover_person("الشيخ أحمد السريري", person_id="sariri", offline_fixture=cross_source_fixture)
    if len(res_cross["playlists"]) != 1:
        errors.append(
            f"[Gate 5] Expected YouTube playlist and Archive.org item for إيصال السالك to unify into 1 series, got {len(res_cross['playlists'])}"
        )
    else:
        iysal_pl = res_cross["playlists"][0]
        if iysal_pl.get("linked_archive_item") != "iysalo-salik_202103":
            errors.append(
                f"[Gate 5] Expected iysal playlist to link Archive item 'iysalo-salik_202103', got {iysal_pl.get('linked_archive_item')!r}"
            )
        ep1 = next((v for v in iysal_pl.get("videos", []) if v.get("episode_num") == 1), None)
        if not ep1 or not str(ep1.get("archive_direct_url", "")).endswith("/iysalo-salik_202103/001.mp3"):
            errors.append(f"[Gate 5] Missing archive_direct_url on Episode 1 of إيصال السالك: {ep1}")
        recovered_ep24 = next(
            (v for v in iysal_pl.get("videos", []) if v.get("recovered_from_archive") == "iysalo-salik_202103"),
            None,
        )
        if not recovered_ep24 or recovered_ep24.get("episode_num") != 24 or recovered_ep24.get("pos") != 3:
            errors.append(
                f"[Gate 5] Failed to recover missing episode 24 from Archive.org into إيصال السالك: {recovered_ep24}"
            )

    # Also test duplicate Archive.org items unification (we-Nafs MP4 + we-Nafs_A MP3)
    nafs_fixture = {
        "sheikh": {"id": "roushdy", "name": "علاء حامد"},
        "raw_series": [],
        "unique_videos": [],
        "archive_payloads": [
            {
                "item_id": "we-Nafs",
                "metadata": {"identifier": "we-Nafs", "title": "سلسلة و نفس و ما سواها - د. محمد بن ابراهيم الحمد"},
                "files": [
                    {"name": "Nafs-001.mp4", "source": "original", "length": "1500", "size": "30000000"},
                    {"name": "Nafs-002.mp4", "source": "original", "length": "1600", "size": "32000000"},
                ],
            },
            {
                "item_id": "we-Nafs_A",
                "metadata": {"identifier": "we-Nafs_A", "title": "سلسلة و نفس و ما سواها - د. محمد بن ابراهيم الحمد"},
                "files": [
                    {"name": "Nafs-01.mp3", "source": "original", "length": "1500", "size": "10000000"},
                    {"name": "Nafs-02.mp3", "source": "original", "length": "1600", "size": "11000000"},
                    {"name": "Nafs-03.mp3", "source": "original", "length": "1700", "size": "12000000"},
                ],
            },
        ],
    }
    res_nafs = discover_person("علاء حامد", person_id="roushdy", offline_fixture=nafs_fixture)
    if len(res_nafs["playlists"]) != 1:
        errors.append(
            f"[Gate 5] Expected we-Nafs (MP4) and we-Nafs_A (MP3) to unify into 1 series, got {len(res_nafs['playlists'])}"
        )
    else:
        unified_nafs = res_nafs["playlists"][0]
        if unified_nafs["video_count"] != 3:
            errors.append(f"[Gate 5] Expected 3 unified episodes in we-Nafs series, got {unified_nafs['video_count']}")
        if not str(unified_nafs["videos"][0].get("archive_direct_url", "")).endswith("/we-Nafs_A/Nafs-01.mp3"):
            errors.append(
                f"[Gate 5] Expected Episode 1 of we-Nafs to link MP3 archive_direct_url, got {unified_nafs['videos'][0]}"
            )

    print(
        "[Gate 5] Shamela 8,589-Book Series Matcher, Archive.org Episode Sorting & Cross-Source Linking: "
        "verified Shamela series matching, anti-false-positive stoplist, natural episode order, and gap recovery."
    )


def test_gate6_author_books_and_multiplatform_pdf_links(errors: list[str]) -> None:
    """
    [Gate 6] Author Books Discovery in Shamela & Multi-Platform PDF Link Extraction Gate:
      1. High-precision scholar book & tahqiq discovery in `shamela4_books_index.json.gz`
         for البوطي, الشعراوي, علي جمعة, وهبة الزحيلي, ابن عثيمين, صالح الفوزان, الشنقيطي,
         with strict anti-collision against partial-name false positives (e.g., عماد علي جمعة,
         محمد مصطفى الزحيلي, عبد الله بن صالح العثيمين, عبد الله بن صالح الفوزان, and 13 other
         Shenqiti authors) and support for `a`, `author`, and `auth` keys + `role` (`author`/`muhaqqiq`).
      2. Multi-platform PDF link extraction (`extract_links_from_pdf`) classifying Telegram
         (`t.me/...`), Google Drive (`drive.google.com/...`), and SoundCloud (`soundcloud.com/...`)
         into structured fields (`telegram_links`, `gdrive_links`, `soundcloud_links`) inside
         `pdf_extracted_links` alongside `youtube_playlists`, `youtube_videos`, `archive_items`,
         and `shortlinks`.
    """
    # 1a. Verify real Shamela 8,589-book index author & muhaqqiq discovery without false positives
    bouti_books = discover_author_books_in_shamela("الشيخ الدكتور محمد سعيد رمضان البوطي", person_id="bouti")
    if len(bouti_books) < 4:
        errors.append(f"[Gate 6] Expected >= 4 Shamela books for البوطي, got {len(bouti_books)}")

    shaarawy_books = discover_author_books_in_shamela("فضيلة الشيخ محمد متولي الشعراوي", person_id="shaarawy")
    if len(shaarawy_books) < 2:
        errors.append(f"[Gate 6] Expected >= 2 Shamela books for الشعراوي, got {len(shaarawy_books)}")

    gomaa_books = discover_author_books_in_shamela("أ.د. علي جمعة", person_id="ali_gomaa")
    if len(gomaa_books) != 2 or any(b.get("author") != "علي جمعة" for b in gomaa_books):
        errors.append(f"[Gate 6] Expected exact match for علي جمعة (2 books, no عماد علي جمعة collision), got {gomaa_books}")

    zuhayli_books = discover_author_books_in_shamela("الدكتور وهبة بن مصطفى الزحيلي", person_id="zuhayli")
    if len(zuhayli_books) < 4 or any("محمد مصطفى الزحيلي" in str(b.get("author", "")) for b in zuhayli_books):
        errors.append(f"[Gate 6] Expected >= 4 books for وهبة الزحيلي without محمد مصطفى الزحيلي collision, got {len(zuhayli_books)}")

    uthaymeen_books = discover_author_books_in_shamela("فضيلة الشيخ محمد بن صالح العثيمين", person_id="uthaymeen")
    if len(uthaymeen_books) < 100:
        errors.append(f"[Gate 6] Expected >= 100 Shamela books for ابن عثيمين via patronymic resolution, got {len(uthaymeen_books)}")
    if any("عبد الله بن صالح العثيمين" in str(b.get("author", "")) for b in uthaymeen_books):
        errors.append("[Gate 6] Collision: عبد الله بن صالح العثيمين leaked into محمد بن صالح العثيمين books")
    if any(b.get("role") == "muhaqqiq" for b in uthaymeen_books):
        errors.append("[Gate 6] Collision: historian '- ت العثيمين' tahqiq leaked into Sheikh Ibn Uthaymeen books")

    fawzan_books = discover_author_books_in_shamela("الشيخ صالح بن فوزان الفوزان", person_id="fawzan")
    if len(fawzan_books) < 19 or any("عبد الله بن صالح الفوزان" in str(b.get("author", "")) for b in fawzan_books):
        errors.append(f"[Gate 6] Expected >= 19 books for صالح الفوزان without عبد الله بن صالح الفوزان collision, got {len(fawzan_books)}")

    shanqiti_books = discover_author_books_in_shamela("الشيخ محمد الأمين الشنقيطي", person_id="shanqiti")
    if len(shanqiti_books) < 20:
        errors.append(f"[Gate 6] Expected >= 20 books for محمد الأمين الشنقيطي, got {len(shanqiti_books)}")
    if any(b.get("author") != "محمد الأمين الشنقيطي" for b in shanqiti_books):
        errors.append("[Gate 6] Collision: other الشنقيطي authors leaked into محمد الأمين الشنقيطي books")

    # 1b. Verify custom index_entries supporting `a`, `author`, `auth` keys and `author` vs `muhaqqiq` roles
    synthetic_shamela_entries = [
        {"id": 90001, "n": "فقه السيرة النبوية - ط الفكر", "a": "محمد سعيد رمضان البوطي", "c": 24, "h": 1434},
        {"id": 90002, "name": "ضوابط المصلحة في الشريعة الإسلامية", "author": "سعيد رمضان البوطي", "c": 13, "h": 1434},
        {"id": 90003, "title": "الحكم العطائية - ت البوطي", "auth": "ابن عطاء الله السكندري", "c": 30, "h": 709},
        {"id": 90004, "n": "المكتبات في الحضارة الإسلامية", "a": "عماد علي جمعة", "c": 27, "h": 99999},
    ]
    synth_bouti = discover_author_books_in_shamela(
        "محمد سعيد رمضان البوطي",
        person_id="bouti",
        index_entries=synthetic_shamela_entries,
    )
    roles_by_id = {b["shamela_id"]: b["role"] for b in synth_bouti}
    if roles_by_id != {90001: "author", 90002: "author", 90003: "muhaqqiq"}:
        errors.append(
            f"[Gate 6] Expected synthetic Shamela lookup to return 2 authored + 1 muhaqqiq for البوطي, got {roles_by_id}"
        )
    if synth_bouti[0]["title"] != "فقه السيرة النبوية":
        errors.append(
            f"[Gate 6] Expected edition suffix '- ط الفكر' to be cleaned into 'فقه السيرة النبوية', got {synth_bouti[0]['title']!r}"
        )

    # 2a. Verify Multi-Platform PDF Link Extraction on synthetic FlateDecode PDF
    multiplatform_stream = (
        "BT /F1 12 Tf 72 720 Td (Multi-Platform Scholar Index PDF) Tj ET\n"
        "<< /Type /Action /S /URI /URI (https://www.youtube.com/playlist?list=PL_GATE6_PLAYLIST_01) >>\n"
        "<< /Type /Action /S /URI /URI (https://youtu.be/dQw4w9WgXcQ) >>\n"
        "<< /Type /Action /S /URI /URI (https://archive.org/details/gate6_archive_collection) >>\n"
        "<< /Type /Action /S /URI /URI (https://t.me/saeed_albouty/1245) >>\n"
        "<< /Type /Action /S /URI /URI (https://telegram.me/turath_channel) >>\n"
        "<< /Type /Action /S /URI /URI (https://drive.google.com/drive/folders/1AbCdEfGhIjKlMnOpQrStUvWxYz012345?usp=sharing) >>\n"
        "<< /Type /Action /S /URI /URI (https://drive.google.com/file/d/1ZyXwVuTsRqPoNmLkJiHgFeDcBa987654/view) >>\n"
        "<< /Type /Action /S /URI /URI (https://soundcloud.com/alarabiya/sets/sharh-al-hikam) >>\n"
        "<< /Type /Action /S /URI /URI (https://on.soundcloud.com/AbCdEf123) >>\n"
        "<< /Type /Action /S /URI /URI (https://bit.ly/3xYzAbC) >>\n"
    ).encode("latin1")
    compressed_mp = zlib.compress(multiplatform_stream)
    pdf_bytes = (
        b"%PDF-1.4\n"
        b"1 0 obj\n<< /Length " + str(len(compressed_mp)).encode("ascii") + b" /Filter /FlateDecode >>\nstream\n"
        + compressed_mp
        + b"\nendstream\nendobj\n%%EOF\n"
    )
    with tempfile.TemporaryDirectory() as tmpdir:
        mp_pdf = Path(tmpdir) / "multiplatform_index.pdf"
        mp_pdf.write_bytes(pdf_bytes)
        extracted_mp = extract_links_from_pdf(mp_pdf)

        required_structured_keys = (
            "youtube_playlists",
            "youtube_videos",
            "archive_items",
            "telegram_links",
            "gdrive_links",
            "soundcloud_links",
            "shortlinks",
        )
        for key in required_structured_keys:
            if key not in extracted_mp:
                errors.append(f"[Gate 6] Missing structured field '{key}' in pdf_extracted_links")

        if len(extracted_mp["youtube_playlists"]) != 1:
            errors.append(f"[Gate 6] Expected 1 youtube_playlist in multiplatform PDF, got {len(extracted_mp['youtube_playlists'])}")
        if len(extracted_mp["youtube_videos"]) != 1:
            errors.append(f"[Gate 6] Expected 1 youtube_video in multiplatform PDF, got {len(extracted_mp['youtube_videos'])}")
        if len(extracted_mp["archive_items"]) != 1:
            errors.append(f"[Gate 6] Expected 1 archive_item in multiplatform PDF, got {len(extracted_mp['archive_items'])}")
        if len(extracted_mp["telegram_links"]) != 2:
            errors.append(f"[Gate 6] Expected 2 telegram_links in multiplatform PDF, got {len(extracted_mp['telegram_links'])}")
        if len(extracted_mp["gdrive_links"]) != 2:
            errors.append(f"[Gate 6] Expected 2 gdrive_links in multiplatform PDF, got {len(extracted_mp['gdrive_links'])}")
        else:
            gd_ids = {g.get("extracted_id") for g in extracted_mp["gdrive_links"]}
            if gd_ids != {"1AbCdEfGhIjKlMnOpQrStUvWxYz012345", "1ZyXwVuTsRqPoNmLkJiHgFeDcBa987654"}:
                errors.append(f"[Gate 6] Unexpected Google Drive extracted IDs: {gd_ids}")
        if len(extracted_mp["soundcloud_links"]) != 2:
            errors.append(f"[Gate 6] Expected 2 soundcloud_links in multiplatform PDF, got {len(extracted_mp['soundcloud_links'])}")
        if len(extracted_mp["shortlinks"]) != 1:
            errors.append(f"[Gate 6] Expected 1 shortlink in multiplatform PDF, got {len(extracted_mp['shortlinks'])}")

        # Verify end-to-end discover_person preserves structured fields on pdf_extracted_links
        res_mp = discover_person(
            "الشيخ محمد سعيد رمضان البوطي",
            person_id="bouti",
            pdf_paths=[mp_pdf],
            offline_fixture={"sheikh": {"id": "bouti", "name": "الشيخ محمد سعيد رمضان البوطي"}, "raw_series": [], "unique_videos": []},
        )
        raw_pdf_links = res_mp["pdf_extracted_links"]
        if len(raw_pdf_links["telegram_links"]) != 2 or len(raw_pdf_links["gdrive_links"]) != 2 or len(raw_pdf_links["soundcloud_links"]) != 2:
            errors.append("[Gate 6] discover_person output pdf_extracted_links did not preserve structured platform lists")
        if res_mp["stats"].get("pdf_telegram_links_count") != 2 or res_mp["stats"].get("pdf_gdrive_links_count") != 2 or res_mp["stats"].get("pdf_soundcloud_links_count") != 2:
            errors.append(f"[Gate 6] discover_person stats missing multi-platform PDF counts: {res_mp['stats']}")

    # 2b. Verify on real Jamhara PDF when present on disk
    real_jamhara = Path("/Users/macm1pro/.gemini/antigravity/brain/a66db81b-9ed5-46c9-a1da-c3de34a35d9c/scratch/jamhara.pdf")
    if real_jamhara.exists():
        jamhara_links = extract_links_from_pdf(real_jamhara)
        if len(jamhara_links["gdrive_links"]) < 30 or len(jamhara_links["soundcloud_links"]) < 35:
            errors.append(
                f"[Gate 6] Expected >= 30 gdrive_links and >= 35 soundcloud_links in real jamhara.pdf, "
                f"got gdrive={len(jamhara_links['gdrive_links'])}, soundcloud={len(jamhara_links['soundcloud_links'])}"
            )

    print(
        f"[Gate 6] Author Books Discovery in Shamela & Multi-Platform PDF Link Extraction: "
        f"verified البوطي ({len(bouti_books)}), الشعراوي ({len(shaarawy_books)}), علي جمعة ({len(gomaa_books)}), "
        f"وهبة الزحيلي ({len(zuhayli_books)}), ابن عثيمين ({len(uthaymeen_books)}), الفوزان ({len(fawzan_books)}), "
        f"الشنقيطي ({len(shanqiti_books)}) with 0 collisions, and Telegram/GDrive/SoundCloud PDF extraction."
    )


def main() -> None:
    errors: list[str] = []
    test_gate1_pdf_flatedecode_extraction(errors)
    raw_data = test_gate2_unification_and_book_matching(errors)
    test_gate3_schema_and_sheikh_curation_compatibility(raw_data, errors)
    test_gate4_cycle2_real_data_regressions(errors)
    test_gate5_shamela_series_matcher_and_cross_source_linking(raw_data, errors)
    test_gate6_author_books_and_multiplatform_pdf_links(errors)

    if errors:
        print(f"\nFAIL ({len(errors)} errors):")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)

    print("\nPASS (0 errors)")
    sys.exit(0)


if __name__ == "__main__":
    main()
