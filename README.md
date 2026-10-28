# مستودع المهارات القياسية لمنظومة التراث والمعرفة (`medmrf-10/SKILLS`)

يضم هذا المستودع المهارات المعتمدة لمصنع المعرفة التراثية، المرتبة وفق معمارية الطبقات من الاكتشاف والجلب والتنقيح، إلى التفريغ النصي الصافي والمحاذاة الصوتية، ثم الفهرسة العميقة وقواعد البيانات العلائقية والتضمين الشعاعي، إلى جانب مهارات البنية التحتية وإدارة الحسابات وضوابط التدقيق التجريبي.

---

## 1. مهارات الاكتشاف والتنقيح والإنتاج النصي والصوتي

1. **[`person-discovery-intake`](./person-discovery-intake/SKILL.md)**:
   - المهارة المسؤولة عن الاكتشاف والجلب الشامل لمواد الشخصية العلمية (قنوات وقوائم يوتيوب، حزم `Archive.org`، الفهارس، والكتب) وإخراج ملف الجرد الخام المعياري المتوافق مع مرحلة التنقيح.

2. **[`sheikh-curation`](./sheikh-curation/SKILL.md)**:
   - المهارة المسؤولة عن التنقيح الدلالي للسلاسل والدروس بمعيار صفر خطأ (`0 Errors`): تصنيف المواد غير المصنفة، عزل المقاطع القصيرة والضيوف، إصلاح انقلاب الأب والابن في البثوث المنقطعة، استيفاء التواريخ الهجرية، وضبط الترقيم وحالة السلسلة (`completed / stopped / ongoing`) مع التدقيق الشامل عبر [`scripts/deep_scanner_all.py`](./sheikh-curation/scripts/deep_scanner_all.py) و[`scripts/global_audit.py`](./sheikh-curation/scripts/global_audit.py).

3. **[`sheikh-series-pipeline`](./sheikh-series-pipeline/SKILL.md)**:
   - خط الإنتاج الهجين لتفريغ السلاسل الصوتية ومحاذاة الكلمات بالثانية (`.txt` + `.align.json`): يدير التفريغ الصوتي المحكوم بحارس الكوتة وسقف سرعة النطق وكاشف التكرار عبر [`scripts/agy_transcribe.py`](./sheikh-series-pipeline/scripts/agy_transcribe.py)، والجسر الصوتي المضغوط (`Opus 12kbps VoIP`) عبر [`scripts/vps_align_feeder.py`](./sheikh-series-pipeline/scripts/vps_align_feeder.py)، والمحاذاة الصوتية بالكلمة على شريحة `Apple Silicon MPS fp16` عبر [`scripts/mac_align_fleet.py`](./sheikh-series-pipeline/scripts/mac_align_fleet.py) و[`scripts/ctc_pure_align.py`](./sheikh-series-pipeline/scripts/ctc_pure_align.py).

4. **[`turath-pdf-to-text`](./turath-pdf-to-text/SKILL.md)**:
   - المحرك البصري الحرفي الصافي لتفريغ الكتب المصورة والحواشي (`100% Pure Verbatim Text & Footnotes`): يستخرج المتون والطرر المدارة وحواشي الطبعات الأزهرية والحجرية بدقة حرفية كاملة (`pages/pNNNN.json` + `pages/pNNNN.txt`)، مع محول التجهيز المباشر [`scripts/pdf_to_preflight_adapter.py`](./turath-pdf-to-text/scripts/pdf_to_preflight_adapter.py) لمرحلة الفهرسة العميقة بصفر ضياع حرفي.

---

## 2. مهارات الفهرسة العميقة وقواعد البيانات والتضمين والربط

5. **[`turath-deep-indexing`](./turath-deep-indexing/SKILL.md)**:
   - منظومة الفهرسة العميقة وقواعد بيانات الكيانات العلائقية: تطبق القوالب الإبستمولوجية عبر العلوم التراثية مع الحفظ الحرفي التام للمتن (`100% Lossless Verbatim Partitioning`)، وتضم جسر إدخال السلاسل الصوتية [`scripts/ytb_to_usdb_intake.py`](./turath-deep-indexing/scripts/ytb_to_usdb_intake.py) ومحرك بناء قاعدة البيانات العلائقية القياسية [`scripts/build_objects_sqlite.py`](./turath-deep-indexing/scripts/build_objects_sqlite.py) (`SQLite + FTS5` للمصادر، السلاسل، الدروس، المقاطع، الأعلام مع فصل الإسناد عن المتن، الأماكن، الأحداث، القصص، القواعد العلمية، الشواهد، وتثليث المتون).

6. **[`turath-embedding-gemma2`](./turath-embedding-gemma2/SKILL.md)**:
   - مهارة التضمين الشعاعي المزدوج والبحث الهجين العلائقي: تولد متجه المتن (`vec_matn`) ومتجه المفهوم (`vec_concept`) لكل مقطع ولكل قاعدة علمية عبر [`scripts/embed_corpus_gemma2.py`](./turath-embedding-gemma2/scripts/embed_corpus_gemma2.py)، وتوفر محرك الاسترجاع الهجين [`scripts/hybrid_search.py`](./turath-embedding-gemma2/scripts/hybrid_search.py) الجامع بين البحث الحرفي (`FTS5 BM25`) والبحث الدلالي والفلترة العلائقية بالكيانات.

7. **[`person-to-knowledge-orchestrator`](./person-to-knowledge-orchestrator/SKILL.md)**:
   - منسق خط الأنابيب المتكامل من مخرجات الشخصية العلمية إلى قواعد البيانات العلائقية (`SQLite + FTS5`) والفهارس الشعاعية عبر [`scripts/orchestrate_person.py`](./person-to-knowledge-orchestrator/scripts/orchestrate_person.py) وفق بوابات التحقق المتتابعة.

---

## 3. مهارات البنية التحتية والحسابات وضوابط الجودة الهندسية

8. **[`agy-multi-account`](./agy-multi-account/SKILL.md)**:
   - منظومة إدارة وعزل الحسابات المتعددة لـ `agy` وفحص الكوتة الحية: تضم السجل المرجعي [`profiles.json`](./agy-multi-account/profiles.json) وأداة [`scripts/agy_multi_pool.py`](./agy-multi-account/scripts/agy_multi_pool.py) لعزل كل حساب في مسار مستقل وسلسلة مفاتيح (`Keychain`) مستقلة، وفحص صحة وكوتة جميع الحسابات بالتوازي بصفر توكن، وتوجيه المهام حسب تخصص كل نموذج وحصته المتاحة.

9. **[`agy-lean-cli`](./agy-lean-cli/SKILL.md)**:
   - مهارة الاستدعاء المعزول الخفيف لـ `agy` وحارس الكوتة عبر [`scripts/agy_lean.py`](./agy-lean-cli/scripts/agy_lean.py): تعزل بيئة التشغيل عن مخططات `MCP` والإضافات لتوفير استهلاك التوكنات في المهام النصية والاستشارية، وتحمي سقف الكوتة للوكيل الرئيسي وعمال الخلفية.

10. **[`youtube-session-ops`](./youtube-session-ops/SKILL.md)**:
    - مهارة تشغيل وتشخيص جلسات `Google / YouTube` على الخادم عبر `CDP`: تضم أداة التدقيق [`scripts/chrome_session_audit.py`](./youtube-session-ops/scripts/chrome_session_audit.py) وفحص صحة خط الإنتاج [`scripts/pipeline_health_check.py`](./youtube-session-ops/scripts/pipeline_health_check.py) مع قواعد حماية الجلسات ومنع الحظر.

11. **[`continuous-skill-improver`](./continuous-skill-improver/SKILL.md)**:
    - بروتوكول التطوير والتدقيق التجريبي اليدوي المتدرج للمهارات (`1 -> 10 -> 100`): يرسخ قاعدة الفحص اليدوي الذاتي قبل التوسع، وتقرير الأركان الخمسة الإلزامي للتشخيص الجذري (`5-Pillar Empirical Audit Report`)، والضوابط الهندسية العشرة المانعة للقواميس الصلبة والاختبارات الصورية، وفحص القرص الفعلي المانع للخداع الشكلي بالعدادات.

---

## 4. الوثيقة المعمارية للمصنع

1. **[`TURATH_FACTORY.md`](./TURATH_FACTORY.md)**:
   - الوثيقة المعمارية الشاملة لمصنع المعرفة التراثية والموسوعة الديناميكية ذات الطبقات الست (الوعي بالعلم وفهرسه المعياري، التفريغ النصي الصافي، التجهيز والفهرسة والإسقاط، تقييم القيمة المضافة `Delta`، الموسوعة الديناميكية متعددة المستويات، ومسارات التعلّم والإنتاج العلمي).
