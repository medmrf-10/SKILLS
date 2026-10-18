# قائمة مهام تطوير مستودع المهارات (`SKILLS Roadmap & Agent TODO List`)

- **تاريخ الاعتماد:** 2026-10-18
- **الهدف النهائي:** تحويل مستودع `SKILLS` إلى خط إنتاج آلي متكامل يستلم **«اسم شخصية / عالم» فقط**، ويتولى من الصفر: البحث والاكتشاف في يوتيوب وأرشيف والكتب $\leftarrow$ التصفية والتنقيح ومعالجة الترتيب والتداخل (`0 errors`) $\leftarrow$ التفريغ النصي والمحاذاة الصوتية بالكلمة (`.align.json`) $\leftarrow$ الفهرسة العميقة الدقيقة $\leftarrow$ التحويل إلى قواعد بيانات علائقية للكيانات (`Objects: الشخصيات، الأحداث، الأماكن، القصص، القواعد، الشواهد`) $\leftarrow$ التضمين الشعاعي المزدوج باستخدام **`EmbeddingGemma 2`**.
- **آلية التنفيذ:** كل مهمة في هذه القائمة مخصصة لـ **وكيل مستقل (`Independent Agent`)** يقوم بالبحث والتجريب العملي والتعلم على بيانات حقيقية، ثم يبني مهارته المستقلة (أو يرقّي المهارة القائمة) مع سكربتاتها واختباراتها الحتمية ويودعها في هذا المستودع.

---

## المهام السبع لوكلاء التطوير المستقلين (`Today's Agent Tasks`)

### [ ] المهمة 1: مهارة الاكتشاف والجلب الشامل من اسم الشخصية (`person-discovery-intake`)
- **المشكلة الحالية:** مهارة [`sheikh-curation`](./sheikh-curation/SKILL.md) تفترض وجود ملف `<sheikh>_raw.json` جاهز مسبقاً، وسكربتات الجلب مبعثرة في مستودع `cheikh/scripts/`.
- **مهمة الوكيل:**
  1. بناء مهارة وسكربتات مكتفية ذاتياً تستلم **اسم الشخصية فقط** (مع خيار تزويد روابط أولية إن وُجدت).
  2. البحث الآلي في **يوتيوب (`YouTube`)**: اكتشاف القنوات الرسمية والأرشيفية، جلب جميع قوائم التشغيل (`Playlists`) وجميع الفيديوهات المنفردة والبثوث المباشرة (`Streams`) مع مددها (`duration`) وتواريخ رفعها الكاملة.
  3. البحث الآلي في **`Archive.org` والمواقع الرسمية**: جلب حزم الصوتيات (`archive.org/metadata/<item_id>`)، فحص حسابات الرافعيين لاستدراك السلاسل غير المربوطة، وفك تيارات ملفات `PDF` الفهرسية (` جمهرة أعمال / فهارس`) لاستخراج روابط `Unlisted Playlists`.
  4. حصر **كتب ومؤلفات الشخصية** (من `turathmcp` / الشاملة / ملفات `PDF`) وربط السلاسل الصوتية بالمتون أو الكتب التي تشرحها.
  5. إخراج ملف `<person_id>_raw.json` معياري وموحد 100%.

---

### [ ] المهمة 2: ترقية التنقيح الدلالي الآلي للسلاسل والدروس (`sheikh-curation v2`)
- **المشكلة الحالية:** [`sheikh-curation`](./sheikh-curation/SKILL.md) تملك أدوات الفحص والتشخيص القوية ([`deep_scanner_all.py`](./sheikh-curation/scripts/deep_scanner_all.py) و[`hijri_interpolator.py`](./sheikh-curation/scripts/hijri_interpolator.py) و[`global_audit.py`](./sheikh-curation/scripts/global_audit.py))، لكن تحويل `<person_id>_raw.json` الجديد إلى سلاسل منقحة يتطلب خطوات يدوية.
- **مهمة الوكيل:**
  1. تطوير خط أنابيب وكيلي معياري داخل `sheikh-curation` يستلم `<person_id>_raw.json` وينفذ آلياً ودلالياً:
     - تصنيف الفيديوهات غير المصنفة (`Unclassified`) إلى سلاسلها الصحيحة.
     - عزل المقاطع القصيرة (`Reels/Shorts < 300s`) والبروموهات ومحاضرات الضيوف.
     - إصلاح انقلاب الأب والابن في البثوث المباشرة المنقطعة (`Parent < 300s` و`Child >= 600s`).
     - استيفاء التواريخ الهجرية وأرقام الدروس المبتورة بعد حرف 100 في يوتيوب.
     - منع تصفير الترقيم (`Numbering Resets`) وفك الدمج الخاطئ للدروس ذات العناوين العامة.
     - تحديد حالة كل سلسلة (`completed / stopped / ongoing`) وتوثيق حدود الأبواب المشروحة.
  2. عدم إجازة المخرج إلا بعد اجتياز `global_audit.py` بنتيجة **`0 errors`** وتوليد هيكل المجلدات الموحد (`<person_id>/sXXX/`).

---

### [ ] المهمة 3: ترقية مهارة التفريغ والمحاذاة الهجينة (`sheikh-series-pipeline v5 — Hybrid VPS + Mac MPS`)
- **المشكلة الحالية:** [`sheikh-series-pipeline`](./sheikh-series-pipeline/SKILL.md) موثقة على إصدار `v4.2` (CPU على السيرفر فقط)، بينما ابتكرنا اليوم معمارية هجينة أسرع بـ 10 أضعاف.
- **مهمة الوكيل:**
  1. دمج وتوثيق **المعمارية الهجينة (`VPS Transcription + Opus 12kbps Bridge + Mac MPS fp16 Silence-Compacted Alignment`)** داخل `sheikh-series-pipeline`:
     - دعم التنزيل الصوتي المباشر من `Archive.org` إلى جانب يوتيوب في [`agy_transcribe.py`](./sheikh-series-pipeline/scripts/agy_transcribe.py).
     - تضمين الجسر الصوتي المضغوط (`vps_align_feeder.py` — `Opus 12kbps VoIP` بحجم `~3 MB` للساعة) لحل عنق زجاجة الإنترنت الضعيف.
     - تضمين محرك المحاذاة على `Apple Silicon MPS` (`mac_align_fleet.py`) بدقة `fp16` وطيّ الصمت (`plan_silence` + `compact_wave` + `unpad_emissions`) وتنظيف الديباجة (`strip_preamble_and_header`) بسرعة `38×–49×` من الوقت الحقيقي.

---

### [ ] المهمة 4: تجريد مهارة تفريغ الكتب المصورة (`turath-pdf-to-text v2 — Pure Text & Footnotes`)
- **المشكلة الحالية:** [`turath-pdf-to-text`](./turath-pdf-to-text/SKILL.md) تجمع بين الاستخراج البصري للنص والحواشي وبين مهام فهرسة وتلخيص مكانها الصحيح في `turath-deep-indexing`.
- **مهمة الوكيل:**
  1. تجريد `turath-pdf-to-text` لتكون **محرك استخراج بصري حرفي صافي 100%** للمتون والحواشي (`pages/pNNNN.json` + `.txt`).
  2. بناء محول مباشر (`pdf_to_preflight_adapter.py`) يحول مخرجات `turath-pdf-to-text` تلقائياً إلى الصيغة التي يستقبلها [`manifest_v4.py`](./turath-deep-indexing/scripts/manifest_v4.py) في `turath-deep-indexing`.

---

### [ ] المهمة 5: بناء محول قواعد بيانات الكيانات المهيكلة (`turath-entity-db` ضمن `turath-deep-indexing`)
- **المشكلة الحالية:** [`turath-deep-indexing`](./turath-deep-indexing/SKILL.md) تستخرج الكيانات بدقة عالية في ملفات JSON (`Gate v4.3 / USDB v5.6`)، لكنها تحتاج خطاً آلياً يحول تفريغات `ytb` (`.txt` + `.align.json`) والكتب المفرغة مباشرةً إلى **قاعدة بيانات علائقية (`SQLite + FTS5`) للكائنات (`Objects`)**.
- **مهمة الوكيل:**
  1. بناء جسر الإدخال التلقائي (`ytb_to_usdb_intake.py`) الذي يقرأ أي سلسلة من `ytb` (`.txt` + `.align.json`) ويدخلها في [`merge_lecture.py`](./turath-deep-indexing/scripts/merge_lecture.py).
  2. بناء محرك التصدير العلائقي الكامل (`build_objects_sqlite.py`) الذي يحول مخرجات `turath-deep-indexing` و[`build_cross_corpus_graph.py`](./turath-deep-indexing/scripts/build_cross_corpus_graph.py) إلى قاعدة بيانات `SQLite` قياسية تضم الجداول المترابطة التالية:
     - `sources` و`series` و`lessons_or_parts`
     - `passages` (النص الحرفي 100% + التوقيت الصوتي `start_sec / end_sec` + رابط يوتيوب بالثانية `youtube_timestamp_url` أو رقم الصفحة)
     - `persons` (جدول الأعلام والشخصيات والفرق الموحدة قياسياً مع الفصل الصارم بين طبقة الإسناد `isnad` وطبقة المتن `matn`)
     - `places` (جدول الأماكن والبلدان والمعالم الجغرافية والتاريخية)
     - `events_chronology` (جدول الأحداث والتواريخ الهجرية والوقائع والغزوات)
     - `stories_cases` (جدول القصص التراثية والحالات التطبيقية الفقهية والعقدية)
     - `science_gems` (جدول القواعد والضوابط العلمية بصيغتَي `verbatim_rule` و`polished_rule`)
     - `evidences` (جدول الشواهد من الآيات القرآنية `surah:ayah` والأحاديث النبوية والحواشي)
     - `matn_triangulation` (جدول ربط مقاطع الشروح الصوتية والمكتوبة بفقرات المتن الأصلي `explained_matn_clause_id`).

---

### [ ] المهمة 6: مهارة التضمين الشعاعي المزدوج بـ `EmbeddingGemma 2` (`turath-embedding-gemma2`)
- **المشكلة الحالية:** `turath-deep-indexing` تولّد حقلَي `embed_matn_text` و`embed_concept_text`، لكن لا توجد بعد مهارة تنفيذية لتوليد المتجهات (`Vectors`) وفهرستها بـ **`EmbeddingGemma 2`**.
- **مهمة الوكيل:**
  1. بناء مهارة مستقلة `turath-embedding-gemma2` في المستودع مع سكربتات التنفيذ والاختبار.
  2. تشغيل نموذج **`EmbeddingGemma 2`** لتوليد التضمين المزدوج لكل مقطع (`passage`) ولكل قاعدة (`science_gem`):
     - **متجه المتن (`vec_matn`)**: من حقل `embed_matn_text` (النص الأصلي المصفى من الترضيات وعلامات الصفحات).
     - **متجه المفهوم (`vec_concept`)**: من حقل `embed_concept_text` (العنوان الفرعي + الملخص + الموضوعات + القواعد المصقولة + الأسئلة البحثية `search_queries`).
  3. تخزين المتجهات في قاعدة بيانات شعاعية مدمجة عالية الأداء (`SQLite-vec` أو `LanceDB`) مربوطة بـ `passage_id` وبجداول الكيانات (`persons`, `places`, `events_chronology`, `evidences`).
  4. بناء محرك استرجاع هجين (`Hybrid Retriever CLI & API`): يجمع بين البحث النصي الحرفي (`FTS5`)، والبحث الدلالي المزدوج (`EmbeddingGemma 2` على المتن والمفهوم)، والفلترة بالكيانات (مثلاً: *ابحث دلالياً عن كذا بشرط وجود العَلَم فلان أو المكان فلان أو في السورة الفلانية*).

---

### [ ] المهمة 7: مهارة المايسترو الشامل (`person-to-knowledge-orchestrator`)
- **المشكلة الحالية:** الحاجة إلى نقطة دخول واحدة تدير المهارات الست السابقة بتناغم.
- **مهمة الوكيل:**
  1. بناء مهارة المايسترو التي تستلم: `اسم الشخصية` (ومسار العمل).
  2. تشغّل بالتتابع المحكوم ببوابات الجودة (`Quality Gates`):
     `[1. person-discovery-intake] ➔ [2. sheikh-curation v2 (0 errors)] ➔ [3. sheikh-series-pipeline v5 + turath-pdf-to-text v2] ➔ [4. turath-deep-indexing + turath-entity-db] ➔ [5. turath-embedding-gemma2]`.
  3. تخرج في النهاية مستودع الشخصية كاملاً: النصوص المفرغة والمحاذاة بالثانية + قاعدة بيانات الكيانات (`SQLite`) + الفهرس الشعاعي (`EmbeddingGemma 2`) مع تقرير تدقيق شامل.
