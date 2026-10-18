# قائمة مهام تطوير مستودع المهارات (`SKILLS Roadmap & Agent TODO List`)

- **تاريخ الاعتماد:** 2026-10-18
- **الحالة الكلية:** ✅ **مكتملة بالكامل (`8/8` مهام — جميع بوابات الفحص الحتمية `PASS (0 errors)`)**
- **الهدف النهائي:** تحويل مستودع `SKILLS` إلى خط إنتاج آلي متكامل يستلم **«اسم شخصية / عالم» فقط**، ويتولى من الصفر: البحث والاكتشاف في يوتيوب وأرشيف والكتب $\leftarrow$ التصفية والتنقيح ومعالجة الترتيب والتداخل (`0 errors`) $\leftarrow$ التفريغ النصي والمحاذاة الصوتية بالكلمة (`.align.json`) $\leftarrow$ الفهرسة العميقة الدقيقة $\leftarrow$ التحويل إلى قواعد بيانات علائقية للكيانات (`Objects: الشخصيات، الأحداث، الأماكن، القصص، القواعد، الشواهد`) $\leftarrow$ التضمين الشعاعي المزدوج باستخدام **`EmbeddingGemma 2`**.
- **آلية التنفيذ:** كل مهمة في هذه القائمة نُفِّذت عبر **وكيل مستقل (`Independent Agent`)** بالتجريب العملي وبوابات الفحص الحتمية ثلاثية الطبقات (`3-Layer Quality Gates`).

---

## المهام المنجزة والمعتمدة (`Completed & Verified Agent Tasks`)

### [x] المهمة 0 (تأسيسية): مهارة الاستدعاء الخفيف وحارس الكوتة (`agy-lean-cli`)
- **المجلد:** [`./agy-lean-cli/`](./agy-lean-cli/SKILL.md)
- **المنجزات:**
  1. بناء [`scripts/agy_lean.py`](./agy-lean-cli/scripts/agy_lean.py) لعزل بيئة `HOME` تماماً من مخططات `MCP` والإضافات والمهارات (`~0` توكن إضافي بدلاً من `~38,000` توكن) مع ربط رمزي لملفات المصادقة و`Keychain` فقط وتنظيف فوري لقواعد بيانات الجلسات المؤقتة.
  2. دمج حارس الكوتة الحي (`check_quota` و`select_best_model`) لحماية `10%` من نافذة الـ5 ساعات للوكيل الرئيسي (وإيقاف الخلفية عند `15%`) وحماية `25%` من الاحتياطي الأسبوعي حتى آخر `12` ساعة قبل التجديد.
  3. بوابة الفحص الحتمية: [`scripts/test_agy_lean_gates.py`](./agy-lean-cli/scripts/test_agy_lean_gates.py) — **`PASS (0 errors)`**.

---

### [x] المهمة 1: مهارة الاكتشاف والجلب الشامل من اسم الشخصية (`person-discovery-intake`)
- **المجلد:** [`./person-discovery-intake/`](./person-discovery-intake/SKILL.md)
- **المنجزات:**
  1. بناء [`scripts/discover_person.py`](./person-discovery-intake/scripts/discover_person.py) ومرجع [`references/01-discovery-sources-and-schema.md`](./person-discovery-intake/references/01-discovery-sources-and-schema.md) لاستلام **اسم الشخصية فقط** وجلب قنوات يوتيوب الرسمية والأرشيفية (`Playlists`, `Videos`, `Streams` مع `duration` وتواريخ الرفع).
  2. حصاد حزم `Archive.org` (`archive.org/metadata/<item_id>`) وحسابات الرافعيين، وفك تيارات `FlateDecode` (`zlib.decompress`) من ملفات `PDF` الفهرسية (`جمهرة أعمال / فهارس`) لاستخراج روابط `Unlisted Playlists`.
  3. حصر كتب ومؤلفات الشخصية ومطابقة السلاسل الصوتية بالمتون المشروحة وإخراج `<person_id>_raw.json` المعياري المتوافق 100% مع `sheikh-curation`.
  4. بوابة الفحص الحتمية: [`scripts/test_discovery_gates.py`](./person-discovery-intake/scripts/test_discovery_gates.py) — **`PASS (0 errors)`**.

---

### [x] المهمة 2: ترقية التنقيح الدلالي الآلي للسلاسل والدروس (`sheikh-curation v2`)
- **المجلد:** [`./sheikh-curation/`](./sheikh-curation/SKILL.md)
- **المنجزات:**
  1. بناء خط الأنابيب الآلي ذي المراحل التسع [`scripts/auto_curate_person.py`](./sheikh-curation/scripts/auto_curate_person.py) لتصنيف `Unclassified` دلالياً، وعزل المقاطع القصيرة (`< 300s`) والبروموهات ومحاضرات الضيوف، وإصلاح انقلاب الأب والابن في البثوث المباشرة المنقطعة، واستيفاء التواريخ الهجرية المبتورة بعد حرف 100، ومنع تصفير الترقيم وفك الدمج الخاطئ، وتحديد حالة السلسلة (`completed / stopped / ongoing`) وتوثيق حدود الأبواب المشروحة.
  2. عدم إجازة المخرج إلا بعد اجتياز [`deep_scanner_all.py`](./sheikh-curation/scripts/deep_scanner_all.py) و[`global_audit.py`](./sheikh-curation/scripts/global_audit.py) بنتيجة **`0 errors`** وتوليد هيكل المجلدات الموحد (`<person_id>/sXXX/_meta.json`).
  3. بوابة الفحص الحتمية: [`scripts/test_curation_v2_gates.py`](./sheikh-curation/scripts/test_curation_v2_gates.py) — **`PASS (0 errors)`**.

---

### [x] المهمة 3: ترقية مهارة التفريغ والمحاذاة الهجينة (`sheikh-series-pipeline v5 — Hybrid VPS + Mac MPS`)
- **المجلد:** [`./sheikh-series-pipeline/`](./sheikh-series-pipeline/SKILL.md)
- **المنجزات:**
  1. ترقية المهارة إلى `v5.0` وتوثيق المعمارية الهجينة في [`references/11-hybrid-vps-mac-mps-v5.md`](./sheikh-series-pipeline/references/11-hybrid-vps-mac-mps-v5.md): التفريغ على السيرفر عبر [`agy_transcribe.py`](./sheikh-series-pipeline/scripts/agy_transcribe.py) (مع دعم `Archive.org` وحارس الكوتة وسقف `<= 215 WPM` وكاشف حلقات التكرار السداسية) + الجسر الصوتي المضغوط (`Opus 12kbps VoIP` بحجم `~3 MB` للساعة عبر [`vps_align_feeder.py`](./sheikh-series-pipeline/scripts/vps_align_feeder.py)) + المحاذاة الفورية على شريحة الماك `Apple Silicon MPS fp16` مع طي الصمت (`plan_silence` + `compact_wave` + `unpad_emissions`) عبر [`mac_align_fleet.py`](./sheikh-series-pipeline/scripts/mac_align_fleet.py) بسرعة `~48×` من الوقت الحقيقي.
  2. بوابة الفحص الحتمية: [`scripts/test_pipeline_v5_gates.py`](./sheikh-series-pipeline/scripts/test_pipeline_v5_gates.py) — **`PASS (0 errors)`**.

---

### [x] المهمة 4: تجريد مهارة تفريغ الكتب المصورة (`turath-pdf-to-text v2 — Pure Text & Footnotes`)
- **المجلد:** [`./turath-pdf-to-text/`](./turath-pdf-to-text/SKILL.md)
- **المنجزات:**
  1. ترقية [`SKILL.md`](./turath-pdf-to-text/SKILL.md) إلى `v2.0` لتكون محرك استخراج بصري حرفي صافي 100% للمتون والحواشي (`pages/pNNNN.json` + `pages/pNNNN.txt`) مع الحفاظ الكامل على جميع القواعد الهندسية والبصرية الذهبية.
  2. بناء المحول المباشر [`scripts/pdf_to_preflight_adapter.py`](./turath-pdf-to-text/scripts/pdf_to_preflight_adapter.py) لتحويل مخرجات `turath-pdf-to-text` بأمان حرفي 100% (`0 chars lost`) إلى الصيغة القياسية التي يستقبلها [`manifest_v4.py`](./turath-deep-indexing/scripts/manifest_v4.py) و[`fn_linker_v4.py`](./turath-deep-indexing/scripts/fn_linker_v4.py) في `turath-deep-indexing`.
  3. بوابة الفحص الحتمية: [`scripts/test_pdf_adapter_gates.py`](./turath-pdf-to-text/scripts/test_pdf_adapter_gates.py) — **`PASS (0 errors)`**.

---

### [x] المهمة 5: بناء محول قواعد بيانات الكيانات المهيكلة (`turath-entity-db` ضمن `turath-deep-indexing v5.7`)
- **المجلد:** [`./turath-deep-indexing/`](./turath-deep-indexing/SKILL.md)
- **المنجزات:**
  1. بناء جسر الإدخال التلقائي [`scripts/ytb_to_usdb_intake.py`](./turath-deep-indexing/scripts/ytb_to_usdb_intake.py) لإدخال سلاسل `ytb` (`.txt` + `.align.json` + `_meta.json`) في [`merge_lecture.py`](./turath-deep-indexing/scripts/merge_lecture.py).
  2. بناء محرك التصدير العلائقي الكامل [`scripts/build_objects_sqlite.py`](./turath-deep-indexing/scripts/build_objects_sqlite.py) ومرجع [`references/07-entity-db-sqlite-schema.md`](./turath-deep-indexing/references/07-entity-db-sqlite-schema.md) لتوليد قاعدة بيانات `SQLite + FTS5` تضم الجداول المترابطة: `sources`, `series`, `lessons_or_parts`, `passages` + `passages_fts`, `persons` + `passage_persons` (مع الفصل الصارم بين `isnad` و`matn`), `places` + `passage_places`, `events_chronology` (`historical` مقابل `transmission`), `stories_cases`, `science_gems` (`verbatim_rule` + `polished_rule`), `evidences` (`surah:ayah`), و`matn_triangulation`.
  3. بوابة الفحص الحتمية: [`scripts/test_objects_sqlite_gates.py`](./turath-deep-indexing/scripts/test_objects_sqlite_gates.py) — **`PASS (0 errors)`**.

---

### [x] المهمة 6: مهارة التضمين الشعاعي المزدوج بـ `EmbeddingGemma 2` (`turath-embedding-gemma2`)
- **المجلد:** [`./turath-embedding-gemma2/`](./turath-embedding-gemma2/SKILL.md)
- **المنجزات:**
  1. بناء [`scripts/embed_corpus_gemma2.py`](./turath-embedding-gemma2/scripts/embed_corpus_gemma2.py) ومرجع [`references/01-dual-embedding-and-hybrid-retrieval.md`](./turath-embedding-gemma2/references/01-dual-embedding-and-hybrid-retrieval.md) لتوليد التضمين الشعاعي المزدوج (`vec_matn` من `embed_matn_text` و`vec_concept` من `embed_concept_text`) لكل مقطع (`passage_embeddings`) ولكل قاعدة علمية (`gem_embeddings`) بدقة `float32` مطبّعة بـ `L2-Norm`.
  2. بناء محرك الاسترجاع الهجين العلائقي [`scripts/hybrid_search.py`](./turath-embedding-gemma2/scripts/hybrid_search.py) الذي يدمج البحث الحرفي (`FTS5 BM25`) والبحث الدلالي المزدوج (`EmbeddingGemma 2` عبر `RRF`) مع الفلترة العلائقية الصارمة بالكيانات (`--person` مع عزل `isnad` عن `matn`، `--place`، `--year-min/max`، `--surah/ayah`، `--matn-clause`).
  3. بوابة الفحص الحتمية: [`scripts/test_embedding_gemma2_gates.py`](./turath-embedding-gemma2/scripts/test_embedding_gemma2_gates.py) — **`PASS (0 errors)`**.

---

### [x] المهمة 7: مهارة المايسترو الشامل (`person-to-knowledge-orchestrator`)
- **المجلد:** [`./person-to-knowledge-orchestrator/`](./person-to-knowledge-orchestrator/SKILL.md)
- **المنجزات:**
  1. بناء محرك التنسيق الشامل [`scripts/orchestrate_person.py`](./person-to-knowledge-orchestrator/scripts/orchestrate_person.py) ومرجع [`references/01-end-to-end-orchestration-and-gates.md`](./person-to-knowledge-orchestrator/references/01-end-to-end-orchestration-and-gates.md) لتشغيل المراحل الست (`Stage 0: Quota Guard` $\rightarrow$ `Stage 1: Discovery Intake` $\rightarrow$ `Stage 2: Semantic Curation v2` $\rightarrow$ `Stage 3: Pure Text & Alignment + PDF Adapter` $\rightarrow$ `Stage 4: Deep Indexing & Objects SQLite DB` $\rightarrow$ `Stage 5: Dual EmbeddingGemma 2 & Hybrid Search`) محكومةً ببوابات الجودة (`G0..G5`) ونقاط الاستئناف (`pipeline_state.json`).
  2. بوابة الفحص الحتمية الشاملة: [`scripts/test_orchestrator_gates.py`](./person-to-knowledge-orchestrator/scripts/test_orchestrator_gates.py) — **`PASS (0 errors)`**.
