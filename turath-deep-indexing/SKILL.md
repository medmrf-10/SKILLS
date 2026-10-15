---
name: turath-deep-indexing
description: >-
  Use when indexing, extracting, auditing, merging, or repairing Islamic heritage books across traditional sciences, spoken video lectures with CTC forced alignment and Matn-Sharh triangulation, technical/educational courses with User Cognitive DNA, developing the Quality Gate (Gate v4.2 / USDB v5.0), building cross-corpus knowledge graphs, preparing dual-layer embeddings (EmbeddingGemma 2), or maintaining reading and showcase platforms.
version: 5.0
---

# مهارة `turath-deep-indexing`: الفهرسة العميقة وتحويل المصادر إلى قواعد بيانات معرفية (الإصدار 5.0 — USDB v5.0)

هذه المهارة تمثل **الدستور المعماري والمواصفة الهندسية القياسية** لمنظومة الفهرسة العميقة وتحويل المصادر النصية والمرئية والتعليمية إلى قواعد بيانات معرفية (`Universal Source-to-Database Architecture — USDB v5.0`) في مستودع الكتب (`$TURATH_BOOKS_REPO`). هدفها تمكين أي وكيل قادم من استكمال العمل أو تدقيق البيانات أو إصلاح العيوب أو استخراج جولات وكتب وسلاسل مرئية ودورات تقنية جديدة وفق أعلى معايير الحرفية والتأصيل المعرفي والدلالي **دون تكرار أي خطأ سابق ودون الحاجة للتخمين في تفاصيل المعمارية أو البوابات الحتمية**.

> **ملاحظة تشغيلية:** أرقام الجولات وحالة الكتب والمحاضرات والدورات والمهام المفتوحة في `references/05-open-backlog-and-roadmap.md` (تحديثية لا معمارية). تعمل المهارة والسكربتات على بيئة macOS أو VPS أو أي بيئة نظامية دون تعديل في الكود اعتماداً على متغيرات البيئة القياسية (`$TURATH_BOOKS_REPO`, `$SKILLS_DIR`, `$AGY_BIN`).

---

## 1. الفلسفة الحاكمة: ماذا نفعل للمصدر الخام أصلاً؟

نحن لا نلخص الكتب أو المحاضرات أو الدورات تلخيصاً إنشائياً، ولا نقطعها تقطيعاً آلياً أعمى بالسكربتات (`Chunking` بعدد الكلمات)، بل نحول **النص الخام الأصم** عبر **أربعة محولات قياسية (`4 Universal Source Adapters`)** إلى **بنية معرفية مزدوجة الطبقات مع حفظ المتن الأصلي حرفياً 100%**:

1. **الحفظ الحرفي التام للمتن (`100% Lossless Verbatim Partitioning`):**
   - الوكيل لا ينسخ نص الفقرة الطويل ولا يعيد كتابته؛ الوكيل يقرأ الجزء الخام ويحدد فقط **مرساة البداية (`anchor_start`)** لكل مبحث فرعي (`4–8` كلمات متصلة حرفياً).
   - سكربت الدمج الحتمي (`merge_round.py` للكتب، `usdb_v5/merge_lecture.py` للدروس المرئية، `usdb_v5/merge_course.py` للدورات التقنية) هو الذي يقص النص الخام بين المراسي بحيث يتحقق الشرط الرياضي القاطع في كل جزء:
     `concat(passage.raw_text for passage in part_passages) == raw_part_text` (صفر حروف مفقودة، صفر فجوات، صفر تداخل).
2. **الطبقة الأولى — النواة المشتركة (`Shared Core: deep_toc_passages`):**
   - تفكيك الكتل الصماء إلى مباحث موضوعية معنونة (`sub_heading` ≤ 2800 حرف، وفي ملفات التعريف المركزة كالعقيدة ≤ 1800 حرف).
   - عزل سلاسل الإسناد المتصلة في بداية الخبر (`isnad_prefix`) عن متن الحدث (`clean_matn`) عبر `matn_start_anchor` في الكتب التراثية، وإسقاط التوقيت الصوتي بالثانية (`start_sec`, `end_sec`, `youtube_timestamp_url`) عبر ملفات المحاذاة بالكلمة (`.align.json` `CTC Forced Alignment`) في الدروس المرئية، وحماية الكتل البرمجية والجدولية الذرية (`Atomic Code/Table Blocks`) في الدورات التقنية.
   - استخراج الكيانات المهيكلة الموثقة لكل مبحث: الأعلام الذريون الموحدون (`persons`)، الأماكن التاريخية الموحدة (`places`)، التواريخ الهجرية المميزة عن الأعمار والمدد (`chronology`)، الأدلة الشرعية المربوطة بالحواشي (`evidences`)، والأسئلة البحثية الطبيعية (`search_queries`).
   - توليد حقلَي التضمين المزدوج لـ `EmbeddingGemma 2` (`embed_matn_text` و`embed_concept_text`).
3. **الطبقة الثانية — العدسة الإبستمولوجية القابلة للتوسيع (`Extensible Epistemological Lens`):**
   ترتكز العدسة المعرفية على **أربعة قوالب عامة قابلة للتوسيع (Four Extensible Archetypes)**:
   * **القالب السردي/الخبري (`Narrative Profile` — `Adapter A`):** يُستخرج فيه `stories` + `isnad_prefix` (`tarajim`, `sirah`, `tari5`, `tazkia`).
   * **القالب التقعيدي/المعياري (`Normative Profile` — `Adapter A`):** يُستخرج فيه `applied_cases` + `verbatim_rule` (`maliki`, `ossoul`, `9awa3idFi9h`, `akida`, `3olomQuran`).
   * **قالب الدروس المرئية وتثليث المتون (`Spoken Lecture & Matn Triangulation Profile` — `Adapter B & C`):** يجمع بين `verbatim_rule` الحرفي من التفريغ (للتوقيت الصوتي الدقيق بالثانية) و`polished_rule` المصقول من اللوازم الشفهية (`يعني / طيب / يا إخوة / تمام؟`)، ويربط مقاطع الشرح بفقرات المتن الأصلي المشروح (`explained_matn_clause_id` + `explained_matn_verbatim`).
   * **قالب الدورات التقنية والبصمة المعرفية للمستخدم (`Technical Course & Cognitive DNA Profile` — `Adapter D`):** يفرض التدرج الذري وحماية الكود والجداول (`P0_BROKEN_ATOMIC_BLOCK`)، وتصدير السبب الجذري للمشكلة (`problem_root_cause`)، والمقابلة الصريحة بين النمط الخاطئ (`wrong_pattern`) والنمط الصحيح (`canonical_pattern`)، وحظر التشبيهات الطفولية، وحماية اتجاه النص العربي (`P0_BARE_ENGLISH_LINE_START`).

---

## 2. الأدوات التنفيذية المدمجة في المهارة (`$SKILL_DIR/scripts/`)

تضم المهارة داخل مجلدها `scripts/` جميع محركات التجهيز والدمج وبوابات الجودة الصارمة لتعمل مباشرةً على أي مستودع (`$TURATH_BOOKS_REPO` أو `$USDB_WORK_DIR`) على الماك أو الـ VPS:

| السكربت في `$SKILL_DIR/scripts/` | الوظيفة الدقيقة |
| :--- | :--- |
| [`scripts/manifest_v4.py`](./scripts/manifest_v4.py) | التجهيز المسبق الحتمي للكتب (`Pre-Flight v4.1`): يجلب الكتب من مصادرها، يعزل مقدمات المحققين، يسقط الأجزاء المتداخلة (`b=a`)، يدمج العناوين القصيرة (`< 4` كلمات) مع تمييز الخواتيم (`colophon` مقابل `section_heading`)، يعالج العناوين الصورية (`﷽`/`المقدمة` -> `effective_heading` و`continues_previous_part`)، ويمنع القطع وسط الجملة (`_has_dangling_tail` + `khabar_boundary`). |
| [`scripts/merge_round.py`](./scripts/merge_round.py) | بوابة الجودة الصارمة والدمج الحتمي للكتب (`Gate v4.2 — v4.2_strict_grounded`): يحاذي المقاطع 100%، يعالج الحواشي المدمجة والملتصقة وتكرار ترقيم الصفحات، يفحص الحرفية التامة للدرر والاقتباسات والعبارات المحصورة بـ `«...»` داخل الملخصات، يعزل الأسانيد الابتدائية والداخلية، يفصل طبقة السند عن طبقة المتن في الأعلام والتواريخ والأماكن، ويفحص التأسيس الدلالي (`check_semantic_grounding_v41`). |
| [`scripts/check_round_p0.py`](./scripts/check_round_p0.py) | فاحص تشخيصي سريع لأخطاء `P0` عبر جولة واحدة أو جميع الجولات (`2..10`) أو علم محدد. |
| [`scripts/merge_lecture.py`](./scripts/merge_lecture.py) | بوابة الجودة والدمج الحتمي للدروس المرئية وتثليث المتون (`Adapter B & C`): يحاذي المقاطع 100%، يسقط التوقيت الصوتي بالكلمة من `.align.json` (`CTC Forced Alignment`)، يفحص الدرر المزدوجة (`verbatim_rule` + `polished_rule` الخالي من اللوازم الشفهية)، ويتحقق من روابط المتن المشروح (`explained_matn_clause_id`). |
| [`scripts/merge_course.py`](./scripts/merge_course.py) | بوابة الجودة والدمج الحتمي للدورات التقنية (`Adapter D`): يحمي الكتل البرمجية والجداول من الانقسام (`P0_BROKEN_ATOMIC_BLOCK`)، ويفرض البصمة المعرفية للمستخدم (`problem_root_cause`, `wrong_pattern`, `canonical_pattern`, خلو الشرح من التشبيهات الطفولية، وسلامة اتجاه الـ RTL `P0_BARE_ENGLISH_LINE_START`). |
| [`scripts/build_cross_corpus_graph.py`](./scripts/build_cross_corpus_graph.py) | محرك بناء الجسر المعرفي العابر للمدونات: يوحد الشواهد القرآنية (`surah:ayah`) ويربطها بالتفاسير الأربعين (`firdaws`)، ويبني تثليث المتون المتعدد (`Multi-Matn Bridge`)، ويوحد أسماء الأعلام عبر الكتب والمحاضرات (`canonicalize_person`). |
| [`scripts/audit_corpus_health.py`](./scripts/audit_corpus_health.py) | فاحص الصحة الشامل للمدونة وبوابات الجودة عبر جميع الجولات والمسارات. |


---

## 3. القواعد الثماني عشرة الحاكمة للوكيل (`Gate v4.2 & USDB v5.0 Golden Rules` — لا تكسرها أبداً)

1. **أمر طرفية واحد في كل خطوة (`One Shell Command at a Time`):**
   - يُمنع ربط الأوامر بـ `&&` أو `;`. نفذ كل أمر منفرداً وتحقق من مخرجه.
   - لا تستخدم `\"` داخل تعبيرات `{...}` في `f-string` عند استدعاء `python3 -c '...'` لتجنب `SyntaxError` في Python < 3.12.
2. **افحص قبل أن تفترض، وحلل الجذر قبل القفز للحل:**
   - شغّل دائماً سكربت الفحص الصحي:
     `python3 "$SKILLS_DIR/turath-deep-indexing/scripts/audit_corpus_health.py"`
     أو عبر الرابط النسبي [`scripts/audit_corpus_health.py`](./scripts/audit_corpus_health.py) لتعرف الحالة الدقيقة للبيانات قبل أي تعديل.
3. **لا تعدل حرفاً واحداً في النص الخام (`raw_text`):**
   - حتى لو كان في مطبوعة الشاملة خطأ ترقيم صريح (مثل النقطتين الخاطئتين قبل مفعول به أو كلام الراوي نحو `يكتب: كل شيء ما أنت إلا الحفظة`)، يبقى `raw_text` مطابقاً للمصدر 100%، لكن **عند استخراج جوهرة أو اقتباس يجب أن يبدأ الاقتباس من بداية الجملة الصحيحة دلالياً (`ما أنت إلا الحفظة تكتب لفظ اللفظة`) لا من بعد النقطتين آلياً!**
4. **ممنوع الاقتباس الآلي لما بعد النقطتين (`No Blind Colon-Splitting`):**
   - كل درة (`verbatim_rule`) وكل اقتباس (`quote`) يجب أن يكون **جملة تامة المعنى نحوياً ودلالياً**، خالية من كلام الراوي المقحم في أولها وخالية من دمج مقولتين لقائلين مختلفين.
5. **ممنوع قطع الدرة من جملة مصدرية معلّقة (`P0_GEM_DANGLING_START`):**
   - لا تبدأ `verbatim_rule` أبداً بـ `أن ...` أو `أنه ...` أو `أنها ...` أو `بأن ...` مقتطعةً بعد فعل محذوف (`روي عنه أن...`, `اعلم أن...`). إما أن تضم الفعل العامل معها أو تبدأ من الجملة التامة بعد `أن`.
6. **ممنوع الحذف بـ `...` في الدرر والاقتباسات (`Zero Ellipsis in Gems & Quotes`):**
   - الدرر والاقتباسات يجب أن تكون شريحة متصلة حرفياً 100% من المتن (`exact` أو `hemistich` لشطري الشعر فقط).
7. **كل نص بين قوسين منقوطين `«...»` (كلمتان فأكثر) في الملخصات والموضوعات والقصص يجب أن يكون حرفياً 100% (`P0_UNVERIFIED_INLINE_QUOTE`):**
   - يُمنع منعاً باتاً وضع `«...»` حول عبارة ملخصة أو مضغوطة بالمعنى. إما أن تنسخ اللفظ الحرفي المتصل من المتن أو تصوغ المعنى سرداً بدون أقواس `«...»`.
8. **حظر الإكمال من ذاكرة النموذج خارج النص (`Zero Memory-Completion Hallucination`):**
   - يُمنع إقحام أسماء أعلام أو ولاة أو كتب أو أماكن أو قرون أو ألقاب من ثقافة النموذج العامة إذا لم ترد في المقطع أو حواشيه (`P0_HALLUCINATED_ENTITY_IN_SUMMARY` / `P0_GEM_COMMENTARY_UNGROUNDED_SCHOLAR` / `P0_STORY_UNGROUNDED_PLACE` / `P0_STORY_UNGROUNDED_CENTURY`).
9. **فصل صارم بين طبقة السند (`isnad`) وطبقة المتن (`matn`) في الكيانات والتواريخ والتضمين:**
   - رواة الإسناد الابتدائي أو الداخلي الذين لم يردوا في المتن يوسمون بـ `source_layer: "isnad"` ويُستبعدون من `embed_concept_text`.
   - تواريخ سماع المخطوط ورواية النسخة توسم بـ `event_layer: "transmission"` وتُستبعد من `embed_concept_text`.
   - الأسانيد الداخلية (`وحدثنا فلان قال حدثنا...`) تُجرد من `embed_matn_text` عبر `extract_interior_isnads` كما يُجرد السند الابتدائي.
10. **ممنوع انتهاء المقطع بنقطتين رأسيتين (`No Trailing Colon at Passage End`):**
    - لا يجوز أن ينتهي أي مقطع (غير المقطع الأخير في الجزء) بـ `:` أو `: (١)` أو `: «` لأن ذلك يقطع القول عن مقوله أو الدليل عن مدلوله.
11. **الالتزام الصارم بأسماء المفاتيح المعيارية المعتمدة (منع تشتت المفاتيح في الجولات الجديدة):**
    - في المقاطع: `sub_heading` · `topics` · `anchor_start` · `matn_start_anchor` · `summary` · `persons` · `places` · `chronology` · `evidences` · `search_queries`.
    - في الدرر: `part` · `title` · `category` (بالعربية حصراً!) · `verbatim_rule` · `explanation`.
    - في الاقتباسات: `part` · `quote` · `speaker` · `context`.
    - في القصص والحالات: `part` · `title` · `anchor_start` · `summary` · `lesson`.
12. **لا تترك حقول الكيانات (`persons`, `places`, `chronology`, `evidences`, `search_queries`) فارغة للتسريع:**
    - تفرض البوابة (`Gate v4.2`) خطأ `P0` على أي مقطع يخلو من `sub_heading`, `summary`, `topics`, `search_queries` وعلى أي كتاب يخلو من `persons` أو `evidences` أو يقل فيه `science_gems` عن 5 أو `stories` عن 3 أو `quotes` عن 5.
13. **في الدروس المرئية والصوتية (`Adapter B`): اجمع بين `verbatim_rule` الحرفي و`polished_rule` المصفى من اللوازم الشفهية:**
    - في `usdb_v5/merge_lecture.py`، يجب أن تطابق `verbatim_rule` نص التفريغ حرفياً 100% (لتوليد التوقيت الصوتي بالثانية من `.align.json`)، بينما تُصاغ `polished_rule` بلغة علمية محررة خالية تماماً من اللوازم الشفهية (`يعني / طيب / يا إخوة / تمام؟ / صح؟`).
14. **في شروح المتون (`Adapter C`): اربط مقاطع الشرح بفقرة المتن المشروحة بدقة (`explained_matn_clause_id` + `explained_matn_verbatim`):**
    - يجب أن يكون `explained_matn_verbatim` شريحة حرفية (`>= 4` كلمات) من نص فقرة المتن المعيارية في `base_matn_clauses`.
15. **في الدورات التقنية والهندسية (`Adapter D`): التزم بالبصمة المعرفية للمستخدم (`User Cognitive DNA`):**
    - لا تضع `anchor_start` أبداً داخل كود برمجي ```` ```...``` ```` أو جدول Markdown (`P0_BROKEN_ATOMIC_BLOCK`).
    - كل درة تقنية يجب أن تحتوي على `problem_root_cause` (المشكلة الهندسية الجذرية)، و`wrong_pattern` (النمط الخاطئ)، و`canonical_pattern` (النمط القياسي الصحيح)، مع حظر التشبيهات الطفولية (`تخيل شجرة / تخيل دفتر`).
16. **حماية اتجاه النص العربي (`RTL-Safe Line Start — P0_BARE_ENGLISH_LINE_START`):**
    - لا تبدأ أي سطر أو جملة عربية في الملخصات أو الشروح التقنية بكلمة إنجليزية عارية (`[A-Za-z]`)؛ بل صدّرها دائماً بكلمة عربية رابطة (`الـ`, `وسم`, `عنصر`, `خوارزمية`, `جملة`, `دالة`).
17. **استشارة `Claude Opus` عبر `agy` CLI عند المراجعة المعمارية:**
    - عندما يطلب المستخدم استشارة Opus، استخدم حصراً `agy` CLI عبر المتغير القياسي `"$AGY_BIN"`.
18. **لا ترفع إلى GitHub (`git push`) إلا بأمر صريح من المستخدم.**

---

## 4. فهرس المراجع التفصيلية في هذه المهارة (اقرأها حسب مهمتك)

للحفاظ على نافذة السياق، فُصّلت الخبرة الهندسية في 6 مراجع متخصصة داخل `references/` وسكربت تشخيصي في `scripts/`:

1. **[`references/01-architecture-and-schema-v4.md`](./references/01-architecture-and-schema-v4.md)**
   - الهيكل الكامل لملفات `raw_round{N}_books.json` و`r{N}_deep_<science>.json` و`round{N}_9_books_deep.json` (`v4.2_strict_grounded`).
   - الحقول المعيارية وطبقات السند والمتن: `source_layer` للأعلام، `event_layer` للتواريخ، `text_origin` مقابل `ref_origin` للأدلة، وحقول الملاحة للأجزاء.
   - القوالب الإبستمولوجية وجدول ملفات التعريف المسجلة (`Registered Science Profiles`) للعلوم والمفاتيح المعيارية الصارمة للاستخراج.
2. **[`references/02-preflight-and-cleaning-rules.md`](./references/02-preflight-and-cleaning-rules.md)**
   - قواعد اختيار الكتب وتنظيفها قبل الوكلاء (`manifest_v4.py` `v4.1`).
   - محرك ربط الحواشي السداسي اللهجات (`fn_linker_v4.py`)، ونظام الترقيع المصدري الموثق (`source_patches/{book_id}.json`).
3. **[`references/03-quality-gate-and-algorithms.md`](./references/03-quality-gate-and-algorithms.md)**
   - خوارزميات `merge_round.py` (`Gate v4.2`) بالتفصيل، ومحلل التواريخ الهجرية المطور، وخوارزمية الفحص الدلالي الصارم (`check_semantic_grounding_v41`).
4. **[`references/04-all-mistakes-and-postmortems.md`](./references/04-all-mistakes-and-postmortems.md)**
   - السجل التاريخي الكامل لكل خطأ ودراسة الأسباب الجذرية عبر الجولات 1–10.
5. **[`references/05-open-backlog-and-roadmap.md`](./references/05-open-backlog-and-roadmap.md)**
   - سجل الإنجازات الشامل عبر المسارات الأربعة (الكتب الـ 81، الدروس المرئية وتثليث المتون، الدورات التقنية، والجسر المعرفي العابر للمدونات) وخارطة الطريق القادمة.
6. **[`references/06-usdb-v5-universal-adapters.md`](./references/06-usdb-v5-universal-adapters.md)**
   - المواصفة الهندسية الكاملة للمحولات الأربعة (`USDB v5.0`): الدروس المرئية مع المحاذاة الصوتية بالكلمة (`CTC Forced Alignment`) وتثليث المتون (`usdb_v5/merge_lecture.py`)، الدورات التقنية والبصمة المعرفية للمستخدم (`usdb_v5/merge_course.py`)، والجسر المعرفي العابر للمدونات (`usdb_v5/build_cross_corpus_graph.py`).
7. **[`scripts/audit_corpus_health.py`](./scripts/audit_corpus_health.py)**
   - سكربت فحص فوري يشغله الوكيل بأمر واحد:
     `python3 "$SKILLS_DIR/turath-deep-indexing/scripts/audit_corpus_health.py"`
     ليعطيه تقريراً رقمياً شاملاً عن صحة الكتب الـ 81 وتدقيق بوابة الجودة `Gate v4.2`، والدروس المرئية، والدورات التقنية، والجسر المعرفي العابر للمدونات.

