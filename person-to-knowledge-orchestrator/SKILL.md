---
name: person-to-knowledge-orchestrator
description: Master End-to-End Orchestrator (المايسترو الشامل من اسم الشخصية إلى قاعدة المعرفة الموحّدة). Takes a person's name or raw sources (YouTube channels/playlists, Archive.org collections, PDF books/indexes) and executes the 6-stage deterministic pipeline with strict hard verification gates (G0..G5) between every stage, resumable state checkpointing (pipeline_state.json), 0% character loss enforcement across both books and audio transcripts, and dual-vector 768-dim Gemma-2 hybrid semantic + FTS5 + entity-filtered search verification. Use whenever asked to run a full or partial person-to-knowledge pipeline, orchestrate discovery to curated series to USDB v5.7 SQLite + embeddings, or audit end-to-end pipeline gates.
---

# Master Orchestrator: Person to Unified Knowledge Database (`person-to-knowledge-orchestrator`)

## 1. Mission & Core Architecture

`person-to-knowledge-orchestrator` is the master end-to-end pipeline that transforms a scholar/author's name or raw source inventory into a verified, zero-character-loss Unified Scholarly Database (**USDB v5.7**) equipped with dual-vector 768-dimensional Gemma-2 embeddings, FTS5 trigram/word indices, and chronological/entity/matn-clause graph cross-links.

Every stage is governed by a **Hard Verification Gate (`G0` through `G5`)**. A stage never advances to the next stage unless its gate passes with **0 P0 errors**.

```mermaid
flowchart TD
    S0["Stage 0: Quota & Lean CLI Guard (agy-lean-cli)"] -->|Gate G0: Quota >= 20% & Lean HOME Isolated| S1["Stage 1: Discovery Intake (person-discovery-intake)"]
    S1 -->|Gate G1: Valid <person_id>_raw.json & Non-Empty Sources| S2["Stage 2: 9-Stage Curation (sheikh-curation v2.0)"]
    S2 -->|Gate G2: deep_scanner_all == 0 Flaws & global_audit == 0 Errors| S3["Stage 3: Dual-Track Extraction (sheikh-series-pipeline v5.0 + turath-pdf-to-text v2.0)"]
    S3 -->|Gate G3: 0 AI Preambles & 100.0% PDF Character Retention| S4["Stage 4: Unified Deep Indexing & Entity DB (turath-deep-indexing v5.7 + turath-entity-db)"]
    S4 -->|Gate G4: Gate v4.3 PASS (0 P0 Errors) & SQLite chars_lost == 0| S5["Stage 5: Dual-Vector Gemma-2 Embedding & Hybrid Search (turath-embedding-gemma2)"]
    S5 -->|Gate G5: 100% 3072-Byte BLOB Coverage & Hybrid Search Verification| DONE["05_reports/ORCHESTRATION_REPORT.md (PASS)"]
```

---

## 2. Standard Workspace Layout (`<work_dir>/<person_id>/`)

All pipeline artifacts for `<person_id>` live in a deterministic, self-contained workspace directory:

```text
<work_dir>/<person_id>/
├── pipeline_state.json                         # Resumable stage checkpoint & gate ledger
├── 00_quota/
│   └── quota_guard_report.json                 # Stage 0 model selection & quota verification
├── 01_discovery/
│   └── <person_id>_raw.json                    # Stage 1 unified multi-source inventory
├── 02_curated/
│   ├── <person_id>.json                        # Stage 2 curated schema (series + standalone + excluded)
│   ├── curated.db                              # Stage 2 normalized SQLite curation ledger
│   └── series/<person_id>/sXXX/_meta.json      # Per-series metadata ready for transcript extraction
├── 03_extracted/
│   ├── series/<person_id>/sXXX/                # Stage 3A sanitized transcripts + .align.json + .meta.json
│   └── books/<book_slug>/                      # Stage 3B zero-loss PDF extraction + manifest_v4 preflight
│       ├── book_matn.txt
│       ├── footnotes.json
│       ├── pages_preflight.json
│       ├── adapter_manifest.json
│       ├── round_manifest_r4_r10.json
│       └── raw_round4_books.json
├── 04_knowledge_db/
│   ├── <person_id>_objects.sqlite              # Stage 4 & 5 Unified Scholarly DB (USDB v5.7 + Gemma-2 vectors)
│   ├── round4_9_books_deep.json                # Merged & audited books payload
│   ├── lectures_deep_merged.json               # Merged & audited lectures payload
│   ├── gate_report_books.json                  # Gate v4.3 books verification report
│   └── gate_report_lectures.json               # Gate v4.3 lectures verification report
└── 05_reports/
    ├── orchestration_audit_report.json         # Machine-readable end-to-end gate audit
    └── ORCHESTRATION_REPORT.md                 # Human-readable executive summary & metrics
```

---

## 3. The 6 Stages & Their Hard Verification Gates

### Stage 0 — Quota & Lean CLI Guard (`agy-lean-cli`)
- **Action**: Calls `check_quota()` and `select_best_model()` from `/Users/macm1pro/REPOS/SKILLS/agy-lean-cli/scripts/agy_lean.py` and prepares/verifies the isolated lean `HOME` directory (`/tmp/agy_lean_home`) so background subagents never load heavy global MCP servers or browser plugins.
- **Hard Gate `G0`**:
  1. Selected model must have remaining quota `>= 20.0%` (or automatic fallback to an available model with `>= 20.0%`).
  2. `verify_lean_home_isolation()` must return `isolated == True` with `0` MCP servers and `0` plugins in the isolated home.

### Stage 1 — Multi-Source Discovery Intake (`person-discovery-intake`)
- **Action**: Calls `discover_person()` from `/Users/macm1pro/REPOS/SKILLS/person-discovery-intake/scripts/discover_person.py` to ingest YouTube channels/playlists, Archive.org items, PDF index files (hyperlinks + text URLs), and PDF/JSON books into `01_discovery/<person_id>_raw.json`.
- **Hard Gate `G1`**:
  1. `01_discovery/<person_id>_raw.json` exists and conforms to the required schema (`person_id`, `sheikh_name`, `playlists`, `videos`, `archive_items`, `books`, `stats`).
  2. Total discovered sources (`unique_videos_count + len(books) + len(archive_items)`) must be `> 0`.

### Stage 2 — Automated 9-Stage Curation (`sheikh-curation v2.0`)
- **Action**: Calls `auto_curate_person()` from `/Users/macm1pro/REPOS/SKILLS/sheikh-curation/scripts/auto_curate_person.py` on `01_discovery/<person_id>_raw.json`, producing `02_curated/<person_id>.json`, `02_curated/curated.db`, and `02_curated/series/<person_id>/sXXX/_meta.json`.
- **Hard Gate `G2`**:
  1. `deep_scanner_all.py` must report `0 flaws` (`scanner_flaws_total == 0`).
  2. `global_audit.py` must return exit code `0` with `"0 errors"` in its output.
  3. Zero duplicate `video_id` across active episodes (`series` + `standalone_lectures`).

### Stage 3 — Dual-Track Extraction (`sheikh-series-pipeline v5.0` + `turath-pdf-to-text v2.0`)
- **Track 3A (Audio/Video Series — Multi-Format Series Matcher)**:
  - Matches external series directories under `--series-transcripts-dir` across all 4 production naming conventions (`yt_id`/`vid` overlap, `series_slug` e.g. `sharh_manzouma_adoudiya`, `playlist_id` e.g. `alasimi-mut-744`, `row_id` e.g. `984`, or safe `sNNN` without cross-series pollution).
  - Stages lesson `.txt`, `.align.json`, and `.meta.json` files into `03_extracted/series/<person_id>/sXXX/` without overwriting curated v5.0 `_meta.json`, runs `sanitize_preamble.process_dir()` to strip Latin/Arabic AI preambles and closings, preserves real word-level CTC `.align.json` files (or generates deterministic word-level alignments when missing), and syncs `transcribed_count`, `aligned_count`, and per-lesson `has_transcript = 1` across `_meta.json`, `<person_id>.json`, and `curated.db`.
- **Track 3B (Written Books / PDFs & Shamela4 JSONL Auto-Ingestion)**:
  - Automatically resolves books discovered in Stage 1 (`books` from `shamela4_books_index.json.gz` or `matched_book` on curated series, prioritizing `shamela_id` for `shamela:<N>` IDs and ignoring `tafsir:surah_*`) against `/Users/macm1pro/REPOS/swe/Shamela4_Full_DB` (or `--shamela-db-dir`), or accepts explicit `--book-input` pointing to a Shamela4 book folder, `.jsonl`, `pages/` directory, or `.json`.
  - Converts Shamela4 `pages.jsonl` + `book_metadata.json` into `pages/pNNNN.json` (cleaning inline HTML tags and routing unnumbered colophon lines in `footnotes` to `margin_notes` so `orphan_head == 0` with `100.0%` character retention) and runs `convert_pdf_output_to_preflight()` (`round_num=4`).
- **Hard Gate `G3`**:
  1. Every lecture `.txt` file has `0` AI preamble/closing patterns (`strip_preamble_and_header(text)[1] == []`) and non-empty Arabic content.
  2. Every book's `adapter_manifest.json` has `status == "PASS"`, `zero_loss_check.passed == True`, `body_char_loss == 0`, `footnotes_char_loss == 0`, `retention_pct == 100.0`, and `manifest_v4_verification.passed == True`.

### Stage 4 — Unified Deep Indexing & Entity DB (`turath-deep-indexing v5.7` + `turath-entity-db`)
- **Action**:
  1. For each extracted series in `03_extracted/series/<person_id>/sXXX/` containing lecture `.txt` files, runs `intake_series()` from `/Users/macm1pro/REPOS/SKILLS/turath-deep-indexing/scripts/ytb_to_usdb_intake.py` (applying base matn clauses when the series explains a known matn or extracted book).
  2. For each extracted book in `03_extracted/books/<book_slug>/`, builds or loads the deep extraction payload (`r4_deep_<science>.json`) and runs `audit_and_merge_round(round_num=4, ...)` from `/Users/macm1pro/REPOS/SKILLS/turath-deep-indexing/scripts/merge_round.py`.
  3. Builds the Unified Scholarly Database at `04_knowledge_db/<person_id>_objects.sqlite` via `build_objects_sqlite()` from `/Users/macm1pro/REPOS/SKILLS/turath-deep-indexing/scripts/build_objects_sqlite.py`, populating all 20 relational + FTS5 tables (`books`, `passages`, `lectures`, `courses`, `series_manifests`, `matn_clauses`, `sharh_links`, `footnotes`, `persons`, `places`, `dates_events`, `quran_Verse_refs`, `hadith_refs`, `poetry_verses`, `stories`, `science_gems`, `quotes`, `cross_links`, `passages_fts`, `gems_fts`).
- **Hard Gate `G4`**:
  1. `gate_report_books.json` and `gate_report_lectures.json` both have `status == "PASS"` and `total_p0_errors == 0`.
  2. `build_objects_sqlite` reports `chars_lost == 0` (`expected_raw_chars == actual_passage_chars`) — **0% character loss** across all books and lectures combined.
  3. Zero narrator leak in `matn`-layer person queries and zero death-year leak in `historical`-layer date queries.

### Stage 5 — Dual-Vector Gemma-2 Embedding & Hybrid Search Verification (`turath-embedding-gemma2`)
- **Action**:
  1. Runs `embed_sqlite_corpus()` from `/Users/macm1pro/REPOS/SKILLS/turath-embedding-gemma2/scripts/embed_corpus_gemma2.py` on `04_knowledge_db/<person_id>_objects.sqlite`, populating `embedding_matn` (Raw Verbatim Matn View) and `embedding_concept` (Contextualized Concept & Entity View) on `passages` and `embedding` on `science_gems`.
  2. Instantiates `HybridSearchEngine` from `/Users/macm1pro/REPOS/SKILLS/turath-embedding-gemma2/scripts/hybrid_search.py` and runs end-to-end verification queries across `hybrid`, `matn`, `concept`, and `fts` modes plus structured filters (`person_layer="matn"`, `year_min`/`year_max`, `matn_clause`).
- **Hard Gate `G5`**:
  1. `passages_without_embeddings == 0` and `gems_without_embeddings == 0`.
  2. Every vector BLOB has exact byte length `dim * 4` (`3072` bytes for 768-dim float32) and unit L2 norm (`~1.0`).
  3. All `embed_text_concept` texts contain `0` honorifics (`HONORIFIC_RANGE_RE`) and `0` narrator prefixes.
  4. `HybridSearchEngine` smoke & layer-isolation checks pass (`0` narrator leak in `person_layer="matn"`).

---

## 4. CLI Usage & Resumable Execution

Run the orchestrator via `/Users/macm1pro/REPOS/SKILLS/person-to-knowledge-orchestrator/scripts/orchestrate_person.py`:

```bash
# Full end-to-end run from offline fixture + book inputs
python3 /Users/macm1pro/REPOS/SKILLS/person-to-knowledge-orchestrator/scripts/orchestrate_person.py \
  --name "الشيخ سعيد الكملي" \
  --person-id "kamali" \
  --work-dir "/tmp/orchestrator_workspace" \
  --offline-fixture "/path/to/discovery_fixture.json" \
  --book-input "/path/to/extracted_book_dir_or_json" \
  --embedding-backend "deterministic"

# Resume from a specific stage (or automatically skip already-passed stages)
python3 /Users/macm1pro/REPOS/SKILLS/person-to-knowledge-orchestrator/scripts/orchestrate_person.py \
  --name "الشيخ سعيد الكملي" \
  --person-id "kamali" \
  --work-dir "/tmp/orchestrator_workspace" \
  --from-stage 4 \
  --to-stage 5
```

### Key CLI Flags
- `--name`: Scholar/author Arabic name (required).
- `--person-id`: Explicit ASCII slug (optional; auto-derived via `normalize_person_id` if omitted).
- `--work-dir`: Root directory under which `<person_id>/` workspace is created.
- `--youtube-url` / `--archive-id` / `--index-pdf` / `--books-json` / `--offline-fixture`: Discovery inputs passed to Stage 1.
- `--series-transcripts-dir`: Optional directory containing pre-extracted `.txt` / `.align.json` lecture transcripts (supporting `series_slug`, `playlist_id`, `row_id`, `sNNN`, or flat layouts) to stage into `03_extracted/series/<person_id>/`.
- `--book-input`: Repeatable path(s) to PDF extraction outputs, Shamela4 book directories (`pages.jsonl`), standalone `.jsonl` files, or `.json` payloads to process in Stage 3B.
- `--shamela-db-dir` / `--no-auto-shamela-books` / `--max-auto-books`: Configure automatic resolution and ingestion of discovered Shamela4 books from `/Users/macm1pro/REPOS/swe/Shamela4_Full_DB`.
- `--from-stage` / `--to-stage`: Run a specific slice of stages (`0`..`5`).
- `--resume` / `--force`: `--resume` (default) skips stages already marked `"PASS"` in `pipeline_state.json`; `--force` re-runs all requested stages from scratch.
- `--embedding-backend`: `"auto"`, `"sentence-transformers"`, or `"deterministic"`.

---

## 5. Anti-Patterns & Strict Rules

1. **Never Bypass a Failed Gate**: If any gate `G0`..`G5` fails, `orchestrate_person.py` immediately halts, records `"status": "FAIL"` with exact diagnostics in `pipeline_state.json`, and raises `OrchestrationGateError`.
2. **Zero Character Loss Is Non-Negotiable**: Neither Stage 3B (`pdf_to_preflight_adapter.py`) nor Stage 4 (`merge_round.py` + `build_objects_sqlite.py`) may drop a single character of `raw_matn` or `raw_footnotes`.
3. **Strict Layer Separation (`matn` vs `isnad`, `historical` vs `transmission`)**: Narrators in chains of transmission (`حدثنا`, `أخبرنا`) must always be tagged `source_layer="isnad"`, and narrator death dates (`ت ٣١٠ هـ`) must always be tagged `event_layer="transmission"`.
4. **Never Invoke Heavy Unisolated CLI Subprocesses**: Always verify `agy-lean-cli` isolation in Stage 0 before spawning any LLM workers.

For detailed gate specifications, schemas, and troubleshooting, read [references/01-end-to-end-orchestration-and-gates.md](file:///Users/macm1pro/REPOS/SKILLS/person-to-knowledge-orchestrator/references/01-end-to-end-orchestration-and-gates.md).
