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
    discover_person,
    extract_links_from_pdf,
    match_title_to_book,
    normalize_person_id,
    parse_archive_metadata_payload,
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


def main() -> None:
    errors: list[str] = []
    test_gate1_pdf_flatedecode_extraction(errors)
    raw_data = test_gate2_unification_and_book_matching(errors)
    test_gate3_schema_and_sheikh_curation_compatibility(raw_data, errors)

    if errors:
        print(f"\nFAIL ({len(errors)} errors):")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)

    print("\nPASS (0 errors)")
    sys.exit(0)


if __name__ == "__main__":
    main()
