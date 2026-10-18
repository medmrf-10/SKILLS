# End-to-End Orchestration & Hard Verification Gates (`G0`–`G5`)

This reference documents the exact contracts, schemas, invariants, and gate assertions enforced by `person-to-knowledge-orchestrator` (`scripts/orchestrate_person.py`).

---

## 1. Upstream Skill Integration Matrix

| Stage | Skill | Primary Script & Entry Point | Input Artifact(s) | Output Artifact(s) | Hard Gate |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Stage 0** | `agy-lean-cli` | `agy_lean.py` (`select_best_model`, `prepare_lean_home`, `verify_lean_home_isolation`) | Optional quota override / live check | `00_quota/quota_guard_report.json` | **Gate G0**: Quota `>= 20.0%` & Lean HOME isolated (`mcp_servers == 0`, `plugins == 0`) |
| **Stage 1** | `person-discovery-intake` | `discover_person.py` (`discover_person`) | YouTube URLs, Archive IDs, PDF indexes, Books JSON, or offline fixture | `01_discovery/<person_id>_raw.json` | **Gate G1**: Valid discovery schema & total discovered sources `> 0` |
| **Stage 2** | `sheikh-curation v2.0` | `auto_curate_person.py` (`auto_curate_person`) | `01_discovery/<person_id>_raw.json` | `02_curated/<person_id>.json`, `02_curated/curated.db`, `02_curated/series/<person_id>/sXXX/_meta.json` | **Gate G2**: `deep_scanner_all == 0` flaws, `global_audit == 0` errors, `0` duplicate `video_id`s |
| **Stage 3** | `sheikh-series-pipeline v5.0` + `turath-pdf-to-text v2.0` | `sanitize_preamble.py` (`process_dir`, `strip_preamble_and_header`) + `pdf_to_preflight_adapter.py` (`convert_pdf_output_to_preflight`) | Curated series + transcript files & PDF book outputs (`book_matn.txt` + `footnotes.json` or JSON) | `03_extracted/series/<person_id>/sXXX/*` & `03_extracted/books/<book_slug>/{adapter_manifest.json, raw_round4_books.json, ...}` | **Gate G3**: `0` AI preambles in `.txt` transcripts & `100.0%` PDF character retention (`body_char_loss == 0`, `footnotes_char_loss == 0`) |
| **Stage 4** | `turath-deep-indexing v5.7` + `turath-entity-db` | `ytb_to_usdb_intake.py` (`intake_series`), `merge_round.py` (`audit_and_merge_round`), `build_objects_sqlite.py` (`build_objects_sqlite`) | `03_extracted/series/...` & `03_extracted/books/...` | `04_knowledge_db/<person_id>_objects.sqlite`, `round4_9_books_deep.json`, `lectures_deep_merged.json`, `gate_report_*.json` | **Gate G4**: Gate v4.3 `PASS` (`0` P0 errors on books & lectures), `chars_lost == 0` in SQLite, `0` narrator/date layer leaks |
| **Stage 5** | `turath-embedding-gemma2` | `embed_corpus_gemma2.py` (`embed_sqlite_corpus`) + `hybrid_search.py` (`HybridSearchEngine`) | `04_knowledge_db/<person_id>_objects.sqlite` | Updated `<person_id>_objects.sqlite` with dual 768-dim float32 BLOBs + `05_reports/ORCHESTRATION_REPORT.md` | **Gate G5**: `100%` embedding coverage (`3072` bytes/vector), `0` honorifics in concept text, verified hybrid + filtered search |

---

## 2. Detailed Gate Specifications

### Gate G0: Quota & Lean CLI Isolation
- **Checks**:
  1. `selected_model_info["allowed"] is True` and `selected_model_info["remaining_pct"] >= 20.0`.
  2. `isolation_info["isolated"] is True`, `isolation_info["mcp_servers_count"] == 0`, and `isolation_info["plugins_count"] == 0`.
- **Failure Trigger**: If all candidate models are `< 20%` quota or if `/tmp/agy_lean_home` contains leaked MCP server definitions or plugins.

### Gate G1: Multi-Source Discovery Integrity
- **Checks**:
  1. `01_discovery/<person_id>_raw.json` exists and parses as a JSON object.
  2. Required keys exist: `person_id`, `sheikh_name`, `playlists`, `videos`, `archive_items`, `books`, `stats`.
  3. At least one valid source exists (`len(videos) + len(books) + len(archive_items) > 0`).
  4. Every entry in `videos` has a non-empty `video_id` and `title`.

### Gate G2: 9-Stage Curation Verification
- **Checks**:
  1. `02_curated/<person_id>.json` and `02_curated/curated.db` exist.
  2. `report["stage9"]["scanner_flaws_total"] == 0` (from `deep_scanner_all.py`).
  3. `report["stage9"]["audit_returncode"] == 0` and `"0 errors"` appears in `report["stage9"]["audit_output"]` (from `global_audit.py`).
  4. Active `video_id`s across all `series[].episodes[]` and `standalone_lectures[]` are 100% unique (`0` duplicates).
  5. Every curated series has a corresponding `02_curated/series/<person_id>/<series_id>/_meta.json`.

### Gate G3: Dual-Track Extraction & Sanitization
- **Track 3A Checks (Series Transcripts)**:
  1. Every series directory in `03_extracted/series/<person_id>/sXXX/` has `_meta.json`.
  2. Every lecture `.txt` transcript in `03_extracted/series/<person_id>/sXXX/` is non-empty (`len(text.strip()) > 0`).
  3. Running `strip_preamble_and_header(text)` on every `.txt` file returns `reasons == []` (zero remaining AI preambles, decorative markdown headers, or closing pleasantries).
- **Track 3B Checks (Books / PDFs)**:
  1. Every book directory in `03_extracted/books/<book_slug>/` contains `adapter_manifest.json`, `round_manifest_r4_r10.json`, and `raw_round4_books.json`.
  2. `adapter_manifest["status"] == "PASS"`.
  3. `adapter_manifest["zero_loss_check"]["passed"] is True`, `body_char_loss == 0`, `footnotes_char_loss == 0`, and `retention_pct == 100.0`.
  4. `adapter_manifest["manifest_v4_verification"]["passed"] is True`.

### Gate G4: Unified Deep Indexing & Zero-Loss SQLite Verification
- **Checks**:
  1. If books are present: `gate_report_books["status"] == "PASS"` and `gate_report_books["total_p0_errors"] == 0`.
  2. If lecture transcripts are present: every series `gate_report_lectures["status"] == "PASS"` and `total_p0_errors == 0`.
  3. `build_objects_sqlite` summary has `chars_lost == 0` and `expected_raw_chars == actual_passage_chars`.
  4. Direct SQLite verification on `04_knowledge_db/<person_id>_objects.sqlite`:
     - All 20 required tables (`books`, `passages`, `lectures`, `courses`, `series_manifests`, `matn_clauses`, `sharh_links`, `footnotes`, `persons`, `places`, `dates_events`, `quran_Verse_refs`, `hadith_refs`, `poetry_verses`, `stories`, `science_gems`, `quotes`, `cross_links`, `passages_fts`, `gems_fts`) exist.
     - `SELECT SUM(raw_char_len) FROM passages` equals `expected_raw_chars`.
     - Zero narrator names (`حدثنا`, `أخبرنا` chain narrators) appear in `SELECT full_name FROM persons WHERE source_layer = 'matn'`.
     - Zero narrator death years (`ت ... هـ`) appear in `SELECT year_hijri FROM dates_events WHERE event_layer = 'historical'`.

### Gate G5: Dual-Vector Gemma-2 Embedding & Hybrid Search Gate
- **Checks**:
  1. `SELECT COUNT(*) FROM passages WHERE embedding_matn IS NULL OR embedding_concept IS NULL` == `0`.
  2. `SELECT COUNT(*) FROM science_gems WHERE embedding IS NULL` == `0`.
  3. Every `embedding_matn`, `embedding_concept`, and `science_gems.embedding` BLOB has exact byte length `dim * 4` (`3072` bytes for `dim = 768`) and L2 norm within `1.0 ± 1e-3`.
  4. Every `embed_text_concept` row in `passages` has `0` honorific characters matching `HONORIFIC_RANGE_RE` (`[\uFDFA-\uFDFF\u0610-\u061A]`).
  5. `HybridSearchEngine` executes test queries in `"hybrid"`, `"matn"`, `"concept"`, and `"fts"` modes and returns valid ranked results with `score > 0`, and `person_layer="matn"` filtering returns `0` isnad-only passages.

---

## 3. Resumable State Schema (`pipeline_state.json`)

`orchestrate_person.py` persists `pipeline_state.json` at the root of `<work_dir>/<person_id>/pipeline_state.json` after every stage transition:

```json
{
  "person_id": "kamali",
  "person_name": "الشيخ سعيد الكملي",
  "work_dir": "/tmp/orchestrator_workspace/kamali",
  "updated_at": "2026-10-18T12:00:00Z",
  "overall_status": "PASS",
  "stages": {
    "0": {
      "name": "stage0_quota_and_lean_guard",
      "gate": "G0",
      "status": "PASS",
      "completed_at": "2026-10-18T12:00:01Z",
      "metrics": {
        "selected_model": "gemini-3.8-flash-high",
        "remaining_pct": 95.0,
        "isolated": true
      },
      "errors": []
    }
  }
}
```

When `--resume` is enabled (default), any stage whose `stages[str(stage_num)]["status"] == "PASS"` and whose primary output artifacts still exist on disk is skipped automatically, allowing rapid recovery after fixing an upstream data issue.
