---
name: turath-deep-indexing
description: >-
  Use when indexing, extracting, auditing, merging, or repairing Islamic heritage books across 22 sciences, spoken video lectures with CTC forced alignment and Matn-Sharh triangulation, technical/educational courses with User Cognitive DNA, developing the Quality Gate (Gate v4.3 / USDB v5.6), building cross-corpus knowledge graphs, preparing dual-layer embeddings (EmbeddingGemma 2), or running regression tests across multi-genre corpora.
version: 5.6
---

# مهارة `turath-deep-indexing`: الفهرسة العميقة وتحويل المصادر إلى قواعد بيانات معرفية (الإصدار 5.6 — Gate v4.3 & USDB v5.6)

هذه المهارة تمثل **الدستور المعماري والمواصفة الهندسية القياسية** لمنظومة الفهرسة العميقة وتحويل المصادر النصية والمرئية والتعليمية إلى قواعد بيانات معرفية (`Universal Source-to-Database Architecture — USDB v5.6`) في مستودع الكتب (`$TURATH_BOOKS_REPO`) ومستودعات التفريغات والمتون والتفاسير. هدفها تمكين أي وكيل قادم من استكمال العمل أو تدقيق البيانات أو إصلاح العيوب أو استخراج جولات وكتب وسلاسل مرئية ودورات تقنية جديدة وفق أعلى معايير الحرفية والتأصيل المعرفي والدلالي **دون تكرار أي خطأ من الأخطاء الـ 38 الموثقة ودون الحاجة للتخمين في تفاصيل المعمارية أو البوابات الحتمية**.

> **ملاحظة تشغيلية:** جميع السكربتات في `scripts/` مكتفية ذاتياً (`Self-Contained`) وتدعم خيار `--work-dir <dir>` للتشغيل على أي مجلد عمل أو مختبر تجارب معزول على macOS أو VPS.

---

## 1. الفلسفة الحاكمة: ماذا نفعل للمصدر الخام أصلاً؟

نحن لا نلخص الكتب أو المحاضرات أو الدورات تلخيصاً إنشائياً، ولا نقطعها تقطيعاً آلياً أعمى بالسكربتات (`Chunking` بعدد الكلمات)، بل نحول **النص الخام الأصم** عبر **أربعة محولات قياسية (`4 Universal Source Adapters`)** إلى **بنية معرفية مزدوجة الطبقات مع حفظ المتن الأصلي حرفياً 100%**:

1. **الحفظ الحرفي التام للمتن (`100% Lossless Verbatim Partitioning`):**
   - الوكيل لا ينسخ نص الفقرة الطويل ولا يعيد كتابته؛ الوكيل يقرأ الجزء الخام ويحدد فقط **مرساة البداية (`anchor_start`)** لكل مبحث فرعي (`4–8` كلمات متصلة حرفياً).
   - سكربت الدمج الحتمي (`merge_round.py` للكتب، `merge_lecture.py` للدروس المرئية، `merge_course.py` للدورات التقنية) هو الذي يقص النص الخام بين المراسي بحيث يتحقق الشرط الرياضي القاطع في كل جزء:
     `concat(passage.raw_text for passage in part_passages) == raw_part_text` (صفر حروف مفقودة، صفر فجوات، صفر تداخل).
2. **الطبقة الأولى — النواة المشتركة (`Shared Core: deep_toc_passages`):**
   - تفكيك الكتل الصماء إلى مباحث موضوعية معنونة (`sub_heading` ≤ 2800 حرف، وفي ملفات التعريف المركزة كالعقيدة ≤ 1800 حرف).
   - عزل سلاسل الإسناد المتصلة في بداية الخبر (`isnad_prefix` شاملةً رمز التحويل `[ح]`) عن متن الحدث (`clean_matn`) عبر `matn_start_anchor` في الكتب التراثية، وإسقاط التوقيت الصوتي بالثانية (`start_sec`, `end_sec`, `youtube_clip_url`) عبر ملفات المحاذاة بالكلمة (`.align.json` `CTC Forced Alignment`) بنافذة محلية محمية بحدود الكلمات في الدروس المرئية، وحماية الكتل الذرية الخمس (`code_fence`, `markdown_table`, `display_math` `$$...$$`, `callout_blockquote` `> [!IMPORTANT]`, `details_block` `<details>...</details>`) في الدورات التقنية.
   - استخراج الكيانات المهيكلة الموثقة لكل مبحث: الأعلام الذريون الموحدون (`persons`)، الأماكن التاريخية الموحدة (`places`)، التواريخ الهجرية المميزة عن الأعمار والمدد والداعمة للعقود التقريبية (`نيف / بضع`) (`chronology`)، الأدلة الشرعية المربوطة بالحواشي والداعمة لأقواس `﴿...﴾` و`{...}` (`evidences`)، والأسئلة البحثية الطبيعية (`search_queries`).
   - توليد حقلَي التضمين المزدوج لـ `EmbeddingGemma 2` (`embed_matn_text` المصفى من محارف الترضية المدمجة `\ufd40..\ufd4f` وعلامات `صفحة ١٣٧`، و`embed_concept_text`).
3. **الطبقة الثانية — العدسة الإبستمولوجية القابلة للتوسيع عبر 22 علماً (`Extensible Epistemological Lens`):**
   ترتكز العدسة المعرفية على **أربعة قوالب عامة قابلة للتوسيع (Four Extensible Archetypes)**:
   * **القالب السردي/الخبري (`Narrative Profile` — `Adapter A`):** يُستخرج فيه `stories` + `isnad_prefix` (`tarajim`, `sirah`, `tari5`, `tazkia`, `hadith`).
   * **القالب التقعيدي/المعياري (`Normative & Exegetical Profile` — `Adapter A`):** يُستخرج فيه `stories/applied_cases` + `verbatim_rule` (`maliki`, `ossoul`, `9awa3idFi9h`, `akida`, `3olomQuran`, `hadith_sharh`, `tafsir`, `irab_quran`, `manzumat`, `kalam_firaq`, `nahw`, `sarf`, `balagha`, `mantiq`, `munazarah`, `lugha`, `faraid`).
   * **قالب الدروس المرئية وتثليث المتون (`Spoken Lecture & Matn Triangulation Profile` — `Adapter B & C`):** يجمع بين `verbatim_rule` الحرفي من التفريغ (للتوقيت الصوتي الدقيق بالثانية) و`polished_rule` المصقول من اللوازم الشفهية (`يعني / طيب / يا إخوة / تمام؟ / ماشي؟`)، ويربط مقاطع الشرح بفقرات المتن الأصلي المشروح (`explained_matn_clause_id` + `explained_matn_verbatim`)، مع تحجيم تلقائي للحد الأدنى في الدروس القصيرة (`< 6,000` حرف).
   * **قالب الدورات التقنية والبصمة المعرفية للمستخدم (`Technical Course & Cognitive DNA Profile` — `Adapter D`):** يفرض التدرج الذري وحماية الكود والجداول والمعادلات والتنبيهات (`P0_BROKEN_ATOMIC_BLOCK`)، وتصدير السبب الجذري للمشكلة (`problem_root_cause`)، والمقابلة الصريحة بين النمط الخاطئ (`wrong_pattern`) والنمط الصحيح (`canonical_pattern`)، وحظر التشبيهات الطفولية، وحماية اتجاه النص العربي وفق معيار يونيكود `UAX #9 Rule P2` (`P0_BARE_ENGLISH_LINE_START`).

---

## 2. الأدوات التنفيذية المدمجة في المهارة (`$SKILL_DIR/scripts/`)

تضم المهارة داخل مجلدها `scripts/` جميع محركات التجهيز والدمج وبوابات الجودة الصارمة ومجموعة الاختبارات الآلية:

| السكربت في `$SKILL_DIR/scripts/` | الوظيفة الدقيقة |
| :--- | :--- |
| [`scripts/manifest_v4.py`](./scripts/manifest_v4.py) | التجهيز المسبق الحتمي للكتب (`Pre-Flight v4.2`): يطبع مخططات المصادر المختلفة (`hdth`, `tfsr`, `shamela`)، يعزل مقدمات المحققين، يسقط الأجزاء المتداخلة (`b=a`)، يدمج العناوين القصيرة (`< 4` كلمات) مع تمييز الخواتيم (`colophon` مقابل `section_heading`)، ويستدعي `fn_linker_v4.py`. |
| [`scripts/fn_linker_v4.py`](./scripts/fn_linker_v4.py) | محرك ربط الحواشي السداسي اللهجات بـ `Monotone LCS`: يطابق رموز الحواشي، يدعم سياق الآيات بـ `﴿...﴾` و`{...}`، ويصنف رموز `(¬N)` في المصادر منزوعة الهوامش (`hdth`) كـ `source_stripped_neg_marker`. |
| [`scripts/merge_round.py`](./scripts/merge_round.py) | بوابة الجودة الصارمة والدمج الحتمي للكتب (`Gate v4.3 — v4.3_universal_strict_grounded`): يدعم 22 علماً قياسياً + أي علم جديد ديناميكياً، يفك محارف الترضية المدمجة (`\ufd40..\ufd4f`)، يدعم تحويل الإسناد `[ح]`، العقود الهجرية التقريبية (`نيف / بضع`)، الآيات المعقوفة `{...}`، وفواصل الشعر `**`، ويدعم `--work-dir <dir>`. |
| [`scripts/check_round_p0.py`](./scripts/check_round_p0.py) | فاحص تشخيصي سريع لأخطاء `P0` عبر جولة واحدة أو جميع الجولات أو علم محدد (يدعم `--work-dir <dir>`). |
| [`scripts/merge_lecture.py`](./scripts/merge_lecture.py) | بوابة الجودة والدمج الحتمي للدروس المرئية وتثليث المتون (`Gate v5.1`): يحاذي المقاطع 100%، يسقط التوقيت الصوتي بالكلمة من `.align.json` بنافذة محلية وحدود كلمات صارمة تمنع قفز المؤشر، يتحقق من الأعلام القصيرة (`1–3` كلمات)، ويدعم الدروس القصيرة (`< 6,000` حرف) وخيار `--work-dir <dir>`. |
| [`scripts/merge_course.py`](./scripts/merge_course.py) | بوابة الجودة والدمج الحتمي للدورات التقنية (`Gate v5.1`): يحمي الكتل الذرية الخمس (`code_fence`, `markdown_table`, `display_math`, `callout_blockquote`, `details_block`)، ويفرض البصمة المعرفية للمستخدم وقانون `UAX #9 Rule P2` للمحارف المحايدة في بداية السطر العربي، ويدعم `--work-dir <dir>`. |
| [`scripts/build_cross_corpus_graph.py`](./scripts/build_cross_corpus_graph.py) | محرك بناء الجسر المعرفي العابر للمدونات: يوحد الشواهد القرآنية (`surah:ayah`) ويربطها بالتفاسير الأربعين (`firdaws`)، ويبني تثليث المتون المتعدد، ويوحد أسماء الأعلام مع حماية الكنى المشتركة (`أبو بكر / ابن عمر / عبد الله`) من التصادم الجزئي. |
| [`scripts/test_skill_gates.py`](./scripts/test_skill_gates.py) | حزمة الاختبارات الانحدارية الآلية (`11` اختباراً حتمياً في `< 0.02` ثانية) تفحص جميع القواعد والحالات الحدية (`#27–#38`). |
| [`scripts/audit_corpus_health.py`](./scripts/audit_corpus_health.py) | فاحص الصحة الشامل للمدونة وبوابات الجودة عبر جميع الجولات والمسارات. |

---

## 3. القواعد الثماني عشرة الحاكمة للوكيل (`Gate v4.3 & USDB v5.6 Golden Rules` — لا تكسرها أبداً)

1. **أمر طرفية واحد في كل خطوة (`One Shell Command at a Time`):**
   - يُمنع ربط الأوامر بـ `&&` أو `;`. نفذ كل أمر منفرداً وتحقق من مخرجه.
   - لا تستخدم `\"` داخل تعبيرات `{...}` في `f-string` عند استدعاء `python3 -c '...'`.
2. **افحص قبل أن تفترض، وشغّل حزمة اختبارات البوابات بعد أي تعديل في السكربتات:**
   - شغّل `python3 "$SKILLS_DIR/turath-deep-indexing/scripts/test_skill_gates.py"` للتأكد من سلامة جميع البوابات الحتمية، و`audit_corpus_health.py` لفحص حالة المدونة.
3. **لا تعدل حرفاً واحداً في النص الخام (`raw_text`):**
   - يبقى `raw_text` مطابقاً للمصدر 100%، وعند استخراج جوهرة أو اقتباس يجب أن يبدأ الاقتباس من بداية الجملة الصحيحة دلالياً لا من بعد النقطتين آلياً.
4. **ممنوع الاقتباس الآلي لما بعد النقطتين (`No Blind Colon-Splitting`):**
   - كل درة (`verbatim_rule`) وكل اقتباس (`quote`) يجب أن يكون **جملة تامة المعنى نحوياً ودلالياً**، خالية من كلام الراوي المقحم في أولها وخالية من دمج مقولتين لقائلين مختلفين.
5. **ممنوع قطع الدرة من جملة مصدرية معلّقة (`P0_GEM_DANGLING_START`):**
   - لا تبدأ `verbatim_rule` أبداً بـ `أن ...` أو `أنه ...` أو `أنها ...` أو `بأن ...` مقتطعةً بعد فعل محذوف (`روي عنه أن...`, `اعلم أن...`).
6. **ممنوع الحذف بـ `...` في الدرر والاقتباسات (`Zero Ellipsis in Gems & Quotes`):**
   - الدرر والاقتباسات يجب أن تكون شريحة متصلة حرفياً 100% من المتن (`exact` أو `hemistich` لشطري الشعر المفصولين بـ `...` أو `**` في الأصل).
7. **كل نص بين قوسين منقوطين `«...»` (كلمتان فأكثر) في الملخصات والموضوعات والقصص يجب أن يكون حرفياً 100% (`P0_UNVERIFIED_INLINE_QUOTE`).**
8. **حظر الإكمال من ذاكرة النموذج خارج النص (`Zero Memory-Completion Hallucination`):**
   - يُمنع إقحام أسماء أعلام أو ولاة أو كتب أو أماكن أو قرون أو ألقاب من ثقافة النموذج العامة إذا لم ترد في المقطع أو حواشيه.
9. **فصل صارم بين طبقة السند (`isnad`) وطبقة المتن (`matn`) في الكيانات والتواريخ والتضمين:**
   - رواة الإسناد الابتدائي أو الداخلي الذين لم يردوا في المتن يوسمون بـ `source_layer: "isnad"` ويُستبعدون من `embed_concept_text`.
   - تواريخ سماع المخطوط ورواية النسخة توسم بـ `event_layer: "transmission"` وتُستبعد من `embed_concept_text`.
10. **ممنوع انتهاء المقطع بنقطتين رأسيتين (`No Trailing Colon at Passage End`).**
11. **الالتزام الصارم بأسماء المفاتيح المعيارية المعتمدة:**
    - في المقاطع: `sub_heading` · `topics` · `anchor_start` · `matn_start_anchor` · `summary` · `persons` · `places` · `chronology` · `evidences` · `search_queries`.
    - في الدرر: `part` · `title` · `category` (بالعربية حصراً!) · `verbatim_rule` · `explanation`.
    - في الاقتباسات: `part` · `quote` · `speaker` · `context`.
    - في القصص والحالات: `part` · `title` · `anchor_start` · `summary` · `lesson`.
12. **استيعاب الآيات المحاطة بـ `﴿...﴾` أو `{...}` والتواريخ التقريبية بـ `نيف / بضع`:**
    - تفرض البوابة (`Gate v4.3`) استخراج كل آية قرآنية صريحة سواء أحاطت بها `﴿...﴾` أو `{...}` (`P0_MISSED_QURAN_VERSES`)، وكل سنة هجرية صريحة أو عقد تقريبي (`سنة نيف وثلاثين وثلاثمائة`) (`P0_MISSED_EXPLICIT_YEARS`).
13. **في الدروس المرئية والصوتية (`Adapter B`): اجمع بين `verbatim_rule` الحرفي و`polished_rule` المصفى من اللوازم الشفهية.**
14. **في شروح المتون (`Adapter C`): اربط مقاطع الشرح بفقرة المتن المشروحة بدقة (`explained_matn_clause_id` + `explained_matn_verbatim`).**
15. **في الدورات التقنية والهندسية (`Adapter D`): التزم بالبصمة المعرفية للمستخدم (`User Cognitive DNA`) وحماية الكتل الذرية الخمس (`code_fence`, `markdown_table`, `display_math`, `callout_blockquote`, `details_block`).**
16. **حماية اتجاه النص العربي وفق `UAX #9 Rule P2` (`P0_BARE_ENGLISH_LINE_START`):**
    - لا تبدأ أي سطر أو جملة عربية في الملخصات أو الشروح التقنية بكلمة إنجليزية عارية أو مسبوقة بمحارف محايدة فقط (مثل `` `Promise.all` `` أو `- `iptables``)؛ بل صدّرها دائماً بكلمة عربية رابطة (`إن دالة`, `أداة`, `وسم`, `خوارزمية`).
17. **استشارة `Claude Opus` عبر `agy` CLI عند المراجعة المعمارية.**
18. **لا ترفع إلى GitHub (`git push`) إلا بأمر صريح من المستخدم.**

---

## 4. فهرس المراجع التفصيلية في هذه المهارة (اقرأها حسب مهمتك)

1. **[`references/01-architecture-and-schema-v4.md`](./references/01-architecture-and-schema-v4.md)** — الهيكل الكامل لملفات الكتب والعلوم الـ 22 المسجلة (`Gate v4.3`).
2. **[`references/02-preflight-and-cleaning-rules.md`](./references/02-preflight-and-cleaning-rules.md)** — قواعد التجهيز المسبق (`manifest_v4.py`) ومحرك ربط الحواشي (`fn_linker_v4.py`).
3. **[`references/03-quality-gate-and-algorithms.md`](./references/03-quality-gate-and-algorithms.md)** — خوارزميات `merge_round.py` (`Gate v4.3`) ومحلل التواريخ الهجرية والفحص الدلالي الصارم.
4. **[`references/04-all-mistakes-and-postmortems.md`](./references/04-all-mistakes-and-postmortems.md)** — السجل التاريخي الكامل للأخطاء الـ **38** ودراسة أسبابها الجذرية وعلاجاتها الحتمية.
5. **[`references/05-open-backlog-and-roadmap.md`](./references/05-open-backlog-and-roadmap.md)** — سجل الإنجازات الشامل وخارطة الطريق.
6. **[`references/06-usdb-v5-universal-adapters.md`](./references/06-usdb-v5-universal-adapters.md)** — المواصفة الهندسية الكاملة للمحولات الأربعة (`USDB v5.6`) وحزمة الاختبارات الانحدارية `scripts/test_skill_gates.py`.


