# Global Skills (`medmrf-10/SKILLS`)

مستودع المهارات القياسية لمنظومة التراث والمعرفة (خط الإنتاج الشامل من «اسم الشخصية» إلى قواعد البيانات العلائقية والتضمين الشعاعي المزدوج):

## ١. المهارات العشر المعتمدة (`10 Verified Production Skills`)

1. **[`person-to-knowledge-orchestrator`](./person-to-knowledge-orchestrator/SKILL.md) (`v1.0`)**:
   - **المايسترو الشامل (`End-to-End Orchestrator`):** يستلم «اسم الشخصية» فقط ويدير المراحل الست (`G0..G5`) بالتتابع المحكوم ببوابات الجودة الحتمية ونقاط الحفظ القابلة للاستئناف (`pipeline_state.json`) حتى إخراج المستودع المعرفي الكامل للشخصية (`SQLite + FTS5 + Dual EmbeddingGemma 2`).
   - بوابة الفحص: [`scripts/test_orchestrator_gates.py`](./person-to-knowledge-orchestrator/scripts/test_orchestrator_gates.py) (`PASS (0 errors)`).

2. **[`person-discovery-intake`](./person-discovery-intake/SKILL.md) (`v1.0`)**:
   - **الاكتشاف والجلب الشامل من اسم الشخصية:** يكتشف آلياً قنوات يوتيوب الرسمية والأرشيفية (`Playlists`, `Videos`, `Streams` مع مددها وتواريخها)، ويحصد حزم `Archive.org` وحسابات الرافعيين، ويفك تيارات `FlateDecode` (`zlib`) من ملفات `PDF` الفهرسية (`جمهرة أعمال / فهارس`) لاستخراج روابط `Unlisted Playlists`، ويطابق السلاسل بالمتون والكتب ليخرج `<person_id>_raw.json` المعياري.
   - بوابة الفحص: [`scripts/test_discovery_gates.py`](./person-discovery-intake/scripts/test_discovery_gates.py) (`PASS (0 errors)`).

3. **[`sheikh-curation`](./sheikh-curation/SKILL.md) (`v2.0`)**:
   - **التنقيح الدلالي الآلي للسلاسل والدروس بمعيار صفر خطأ (`0 Errors`):** يضم محرك التنقيح ذا المراحل التسع [`scripts/auto_curate_person.py`](./sheikh-curation/scripts/auto_curate_person.py) لتصنيف غير المصنف دلالياً، وعزل المقاطع القصيرة (`< 300s`) والبروموهات والضيوف، وإصلاح انقلاب الأب والابن في البثوث المباشرة المنقطعة، واستيفاء التواريخ الهجرية المبتورة بعد حرف 100 (`hijri_interpolator.py`)، ومنع تصفير الترقيم، وتوثيق حدود الأبواب المشروحة، مع الإجازة الحتمية عبر [`deep_scanner_all.py`](./sheikh-curation/scripts/deep_scanner_all.py) و[`global_audit.py`](./sheikh-curation/scripts/global_audit.py) وتوليد `<person_id>/sXXX/_meta.json`.
   - بوابة الفحص: [`scripts/test_curation_v2_gates.py`](./sheikh-curation/scripts/test_curation_v2_gates.py) (`PASS (0 errors)`).

4. **[`sheikh-series-pipeline`](./sheikh-series-pipeline/SKILL.md) (`v5.0`)**:
   - **خط الإنتاج الهجين لتفريغ ومحاذاة السلاسل الصوتية (`Hybrid VPS + Opus 12kbps VoIP Bridge + Mac Apple Silicon MPS fp16`):** التفريغ عبر [`agy_transcribe.py`](./sheikh-series-pipeline/scripts/agy_transcribe.py) (`gemini-3.8-flash-high` مع دعم `Archive.org` وحارس الكوتة الحي وسقف `<= 215 WPM` وكاشف حلقات التكرار السداسية)، والتحويل الفوري إلى `Opus 12kbps VoIP` (`~3 MB` للساعة عبر [`vps_align_feeder.py`](./sheikh-series-pipeline/scripts/vps_align_feeder.py))، والمحاذاة الصوتية النقية بالكلمة على شريحة الماك `Apple Silicon MPS fp16` مع طي الصمت (`plan_silence` + `compact_wave` + `unpad_emissions`) عبر [`mac_align_fleet.py`](./sheikh-series-pipeline/scripts/mac_align_fleet.py) بسرعة `~48×` من الوقت الحقيقي. التفاصيل في [`references/11-hybrid-vps-mac-mps-v5.md`](./sheikh-series-pipeline/references/11-hybrid-vps-mac-mps-v5.md) والمراجع `01`–`10`.
   - بوابة الفحص: [`scripts/test_pipeline_v5_gates.py`](./sheikh-series-pipeline/scripts/test_pipeline_v5_gates.py) (`PASS (0 errors)`).

5. **[`turath-pdf-to-text`](./turath-pdf-to-text/SKILL.md) (`v2.0`)**:
   - **المحرك البصري الحرفي الصافي لتفريغ الكتب المصورة والحواشي (`100% Pure Verbatim Text & Footnotes + Pre-Flight v4 Adapter`):** يستخرج المتون والطرر المدارة `90° CW` وحواشي الجداول الأزهرية/البولاقية بدقة 100% (`pages/pNNNN.json` + `pages/pNNNN.txt`)، مع المحول المباشر [`scripts/pdf_to_preflight_adapter.py`](./turath-pdf-to-text/scripts/pdf_to_preflight_adapter.py) الذي يجهز المخرجات لمرحلة `Pre-Flight v4` (`manifest_v4.py` و`fn_linker_v4.py`) بصفر ضياع حرفي (`100% Zero-Loss`).
   - بوابة الفحص: [`scripts/test_pdf_adapter_gates.py`](./turath-pdf-to-text/scripts/test_pdf_adapter_gates.py) (`PASS (0 errors)`).

6. **[`turath-deep-indexing`](./turath-deep-indexing/SKILL.md) (`v5.7` + `turath-entity-db`)**:
   - **منظومة الفهرسة العميقة وقواعد بيانات الكيانات العلائقية (`Gate v4.3 / USDB v5.7`):** تشمل القوالب الإبستمولوجية الأربعة عبر 22 علماً، والحفظ الحرفي التام للمتن (`100% Lossless Verbatim Partitioning`)، وجسر إدخال السلاسل الصوتية [`scripts/ytb_to_usdb_intake.py`](./turath-deep-indexing/scripts/ytb_to_usdb_intake.py)، ومحرك بناء قاعدة بيانات الكيانات العلائقية القياسية [`scripts/build_objects_sqlite.py`](./turath-deep-indexing/scripts/build_objects_sqlite.py) (`SQLite + FTS5` بـ 11 جدولاً مترابطاً: `sources`, `series`, `lessons_or_parts`, `passages` + `passages_fts`, `persons` مع الفصل الصارم بين `isnad` و`matn`, `places`, `events_chronology`, `stories_cases`, `science_gems`, `evidences`, و`matn_triangulation`).
   - بوابة الفحص: [`scripts/test_objects_sqlite_gates.py`](./turath-deep-indexing/scripts/test_objects_sqlite_gates.py) (`PASS (0 errors)`).

7. **[`turath-embedding-gemma2`](./turath-embedding-gemma2/SKILL.md) (`v1.0`)**:
   - **التضمين الشعاعي المزدوج بـ `EmbeddingGemma 2` والبحث الهجين العلائقي:** يولد متجه المتن (`vec_matn` من `embed_matn_text`) ومتجه المفهوم (`vec_concept` من `embed_concept_text`) لكل مقطع ولكل قاعدة علمية عبر [`scripts/embed_corpus_gemma2.py`](./turath-embedding-gemma2/scripts/embed_corpus_gemma2.py)، ويوفر محرك الاسترجاع الهجين [`scripts/hybrid_search.py`](./turath-embedding-gemma2/scripts/hybrid_search.py) (`FTS5 BM25` + `Dual EmbeddingGemma 2 RRF` + فلترة علائقية بالأعلام والأماكن والتواريخ الهجرية والآيات وفقرات المتون).
   - بوابة الفحص: [`scripts/test_embedding_gemma2_gates.py`](./turath-embedding-gemma2/scripts/test_embedding_gemma2_gates.py) (`PASS (0 errors)`).

8. **[`agy-lean-cli`](./agy-lean-cli/SKILL.md) (`v1.0`)**:
   - **الاستدعاء المعزول الخفيف لـ `agy` وحارس الكوتة الصارم:** يعزل بيئة `HOME` تماماً من مخططات `MCP` والإضافات والمهارات (`~0` توكن إضافي بدلاً من `~38,000` توكن) عبر [`scripts/agy_lean.py`](./agy-lean-cli/scripts/agy_lean.py)، ويحمي الكوتة الحية (`>= 10%` للوكيل الرئيسي و`>= 15%` لعمال الخلفية في نافذة الـ5 ساعات، و`>= 25%` للاحتياطي الأسبوعي حتى آخر 12 ساعة).
   - بوابة الفحص: [`scripts/test_agy_lean_gates.py`](./agy-lean-cli/scripts/test_agy_lean_gates.py) (`PASS (0 errors)`).

9. **[`continuous-skill-improver`](./continuous-skill-improver/SKILL.md) (`v1.0`)**:
   - **حلقة التحسين المستمر للمهارات عبر الوكلاء الفرعيين وحارس الإنتاج الفعلي المضاد للخداع (`Subagent-Driven Continuous Skill Improvement & Anti-Deception Production Watchdog`):** تدير التدوير الدوري (`Round-Robin`) للمهارات التسع كل 20 دقيقة داخل وكلاء فرعيين معزولين (`Zero Main-Context Bloat`) عبر [`scripts/manage_improvement_loop.py`](./continuous-skill-improver/scripts/manage_improvement_loop.py)، وتكشف التقدم الوهمي (`completed_series_this_run` مقابل `new_txts_last_30m` وأخطاء `$HOME is not defined` في `systemd`)، وتراقب دقة محاذاة الماك (`< 95.0%` وقاعدة `ALIGN-ONSET-BREATH-JUMP`).
   - بوابة الفحص: [`scripts/test_improver_gates.py`](./continuous-skill-improver/scripts/test_improver_gates.py) (`PASS (0 errors)`).

10. **[`agy-multi-account`](./agy-multi-account/SKILL.md) (`v1.3`)**:
    - **إدارة وتشغيل الحسابات المتعددة لـ `agy` (`Multi-Account Isolation, Quota Inspection & Transcription Pool`):** سجل مرجعي واحد [`profiles.json`](./agy-multi-account/profiles.json) لكل الحسابات (الاسم، البريد، الدور، الحالة) بنموذج: `medmrf10` رئيسي مستقل، `brain` مستقل، وعائلة Google (المدير `medmrf19` محظور + 5 أعضاء بحصة مشتركة يتصدرها `mb10` مع تناوب `bm10 ← mb19 ← medmrfco` عند التعثّر)، وعزل عبر `HOME=~/.agy-profiles/<name>` مع إصلاح فخ `macOS Keychain` (نسب التوكن لصاحبه بحسب البريد بدل الكتابة فوق البروفايل)، وفحص صحة (`--doctor`) وكوتة كل حساب مجاناً (`0` توكن، بالتوازي، مع كشف الحسابات المعطّلة 403) عبر [`scripts/agy_multi_pool.py`](./agy-multi-account/scripts/agy_multi_pool.py)، وتشغيل `agy` بحساب معزول من أي وكيل (`--run`) دون `~/.zshrc`، ونسخ احتياطي/استعادة للتوكنات، وتفريغ الصوت بحساب محدد (`--agy-profile brain`) أو باختيار تلقائي للأعلى كوتة. اختبارات وحدة في [`tests/`](./agy-multi-account/tests/test_agy_multi_pool.py).

11. **[`youtube-session-ops`](./youtube-session-ops/SKILL.md) (`v1.0`)**:
    - **تشغيل وتشخيص جلسات Google/YouTube في Chrome الدائم على `hermes-vps` (CDP):** بنية مسار التنزيل (`vps_align_feeder.py` ← `mirath-audio` ← كوكيز Chrome)، وسكربت تدقيق للقراءة فقط [`chrome_session_audit.py`](./youtube-session-ops/scripts/chrome_session_audit.py) (الحكم `LOGGED-IN`/`GOOGLE-ONLY`/`LOGGED-OUT` وأعمار الكوكيز وتبويبات «تأكيد الهوية»)، وجدول الأعراض ← التشخيص، وإجراء الإصلاح عبر noVNC، وأدلة جنائية موثّقة (مثبت/مرجّح/مجهول) لسبب خروج Chrome من الحساب، وقواعد صارمة: لا تنزيل يوتيوب من الماك ولا استعمال جلسة الحساب الرئيسي، ودروس تشغيلية عامة (الجوع الصامت، head-of-line، نشر `restart` لا `start`).

---

## ٢. الوثائق المعمارية وخارطة الطريق (`Architecture & Trackers`)
- **[`TODO.md`](./TODO.md)**: سجل المهام الثماني المكتملة وبوابات فحصها الحتمية.
- **[`HANDOFF_7_TASKS_AND_PIPELINE.md`](./HANDOFF_7_TASKS_AND_PIPELINE.md)**: وثيقة التسليم الشامل وإدارة الكوتة وخط الإنتاج الهجين الحي.
- **[`TURATH_FACTORY.md`](./TURATH_FACTORY.md)** و**[`TURATH_FACTORY_TRACKER.md`](./TURATH_FACTORY_TRACKER.md)**: وثيقة المعمارية السداسية لمصنع المعرفة التراثية والموسوعة الديناميكية.
