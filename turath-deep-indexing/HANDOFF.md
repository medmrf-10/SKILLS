# وثيقة التسليم الشاملة (HANDOFF) — ترقية `turath-deep-indexing` v5.6 (`Gate v4.3 / USDB v5.6`)

- **تاريخ التسليم:** `2026-10-16 07:50 +02:00`
- **أحدث التزام موحّد (`main` / `origin/main`):** يتضمن التزام ترقية المهارة `796ca83` (`feat(turath-deep-indexing): upgrade to USDB v5.6 & Gate v4.3 after multi-repo stress tests (Mistakes #27-#38)`) فوق `39c88af`، مدمجاً مع تحديثات `sheikh-series-pipeline` (`c38178c`).
- **المسارات الحية:**
  - مجلد المهارة: `/Users/macm1pro/REPOS/SKILLS/turath-deep-indexing/`
  - المستودع البعيد: `https://github.com/medmrf-10/SKILLS.git` (`branch: main`)
  - مستودع الكتب المرجعي: `/Users/macm1pro/REPOS/books/`

---

## ١. ملخص تنفيذي سريع للوكيل القادم

1. **ما هي مهارة `turath-deep-indexing` وكيف تتكامل مع `sheikh-series-pipeline`؟**
   - بينما تتولى `sheikh-series-pipeline` تحويل الصوت إلى نص مفرّغ + ملف محاذاة صوتية بالكلمة (`.align.json`)، تتولى **`turath-deep-indexing`** المرحلة التالية: **تحويل أي مصدر نصي خام (كتاب تراثي، تفريغ سلسلة دروس مع `.align.json`، متن مشروح، أو مقرر تقني/رياضي) إلى قاعدة بيانات معرفية مهيكلة بالكامل** مع **حفظ النص الأصلي حرفياً بنسبة 100% (`Zero-Loss Verbatim Partitioning`)** وبوابة جودة حتمية صارمة (`0 P0 Errors`).
2. **أهم ما أُنجز في ترقية الإصدار `v5.6` (`Gate v4.3 / USDB v5.6`):**
   - **استقلالية المهارة بالكامل (`Self-Contained Skill`):** جُمعت جميع السكربتات التنفيذية الحتمية داخل `turath-deep-indexing/scripts/` مع دعم معامل `--work-dir <dir>` للتشغيل المعزول في أي مجلد عمل.
   - **تعميم المحولات الأربعة (`Adapters A–D`):**
     - **`Adapter A` (الكتب التراثية — `manifest_v4.py` + `fn_linker_v4.py` + `merge_round.py`):** توسعة العلوم المسجلة في `SCIENCE_META` من 9 إلى **22 علماً تراثياً** + دالة `get_science_meta` لأي علم مستقبلي، مع دعم أسانيد التحويل `[ح]`، تفكيك محارف الترضية المدمجة في يونيكود (`﵀` / `﵁`)، الآيات المعقوفة `{...}`، العقود الهجرية التقريبية (`سنة نيف/بضع`)، الحواشي المبتورة `(¬١)` في مستودع `hdth`، وفواصل الأشطار الشعرية `**`.
     - **`Adapter B & C` (تفريغات الدروس المرئية وتثليث المتون — `merge_lecture.py`):** إسقاط التوقيت الصوتي بالثانية (`start_sec`, `end_sec`, `youtube_clip_url`) من ملفات `.align.json` (بصيغتَي `v3` و`v4`) مع إصلاح قفزة المؤشر في الكلمات القصيرة (`(?<!\w)...(?!\w)` داخل نافذة موضعية `40` حرفاً)، وفصل النص المنطوق الحرفي (`verbatim_rule`) عن القاعدة العلمية المحررة (`polished_rule`)، وربط مقاطع الشرح بفقرات المتن الأصلي (`explained_matn_clause_id`).
     - **`Adapter D` (الدورات التقنية والرياضية — `merge_course.py`):** حماية **5 كتل ذرية** (`code_fence`, `markdown_table`, `display_math $$...$$`, `callout_blockquote`, `details_block`) من الانقسام، وفحص `UAX #9 Rule P2` لمنع كسر اتجاه الـ RTL، وإلزام كل قاعدة بالسبب الجذري (`problem_root_cause`) والمقابلة (`wrong_pattern` مقابل `canonical_pattern`).
     - **الجسر المعرفي العابر للمدونات (`build_cross_corpus_graph.py`):** اكتشاف ديناميكي لأي جولة كتب وأي منظومة متون مشروحة في `raw_lectures.json`، ومنع تصادم الكنى المشتركة (`أبو بكر`، `ابن عمر`، `عبد الله`) عند توحيد الأعلام بين الكتب والدروس.
   - **إضافة اختبار وحدوي وتراجعي دائم (`scripts/test_skill_gates.py`):** يختبر جميع الحالات الحدية الـ 12 (`Mistakes #27–#38`) في `0.01` ثانية (`11/11 OK`).

---

## ٢. الجرد الكامل لملفات وسكربتات المهارة (`turath-deep-indexing/`)

### أ) السكربتات الحتمية (`turath-deep-indexing/scripts/`)

| السكربت | الوظيفة | طريقة التشغيل القياسية |
|---|---|---|
| [`manifest_v4.py`](file:///Users/macm1pro/REPOS/SKILLS/turath-deep-indexing/scripts/manifest_v4.py) | الفحص الاستباقي (`Pre-Flight v4.1`) وتجهيز `raw_round{N}_books.json` من ملفات الكتب الخام مع تطبيع مفاتيح الأجزاء (`i`, `t`, `pg`, `fn`) | `python3 scripts/manifest_v4.py` |
| [`fn_linker_v4.py`](file:///Users/macm1pro/REPOS/SKILLS/turath-deep-indexing/scripts/fn_linker_v4.py) | ربط الحواشي بالمتن، كشف الآيات (`﴿...﴾` و`{...}`)، وتصنيف الحواشي المبتورة من المصدر (`(¬١)` عندما `fn=[]`) | يُستورد تلقائياً داخل `manifest_v4.py` و`merge_round.py` |
| [`merge_round.py`](file:///Users/macm1pro/REPOS/SKILLS/turath-deep-indexing/scripts/merge_round.py) | القص الحتمي للمقاطع وبوابة الجودة الصارمة (`Gate v4.3`) للكتب التراثية (22 علماً مسجلاً) | `python3 scripts/merge_round.py [--work-dir <dir>] <round_num>` |
| [`check_round_p0.py`](file:///Users/macm1pro/REPOS/SKILLS/turath-deep-indexing/scripts/check_round_p0.py) | الفحص السريع لأخطاء `P0` لكل علم في الجولة دون كتابة ملف الدمج النهائي | `python3 scripts/check_round_p0.py [--work-dir <dir>] <round_num> [science]` |
| [`merge_lecture.py`](file:///Users/macm1pro/REPOS/SKILLS/turath-deep-indexing/scripts/merge_lecture.py) | القص الحتمي وبوابة الجودة (`Gate v5.1`) لتفريغات الدروس الصوتية/المرئية + إسقاط التوقيت من `.align.json` + تثليث المتون | `python3 scripts/merge_lecture.py [--work-dir <dir>] [lecture_id ...]` |
| [`merge_course.py`](file:///Users/macm1pro/REPOS/SKILLS/turath-deep-indexing/scripts/merge_course.py) | القص الحتمي وبوابة الجودة (`Gate v5.1`) للدورات التقنية والرياضية + حماية الكتل الذرية الخمس | `python3 scripts/merge_course.py [--work-dir <dir>] [course_id ...]` |
| [`build_cross_corpus_graph.py`](file:///Users/macm1pro/REPOS/SKILLS/turath-deep-indexing/scripts/build_cross_corpus_graph.py) | بناء الرسم البياني العابر للمدونات (جسر الآيات مع تفاسير `firdaws`، جسر المتون المشروحة، وجسر الأعلام المشتركين) | `python3 scripts/build_cross_corpus_graph.py [--work-dir <dir>]` |
| [`test_skill_gates.py`](file:///Users/macm1pro/REPOS/SKILLS/turath-deep-indexing/scripts/test_skill_gates.py) | حزمة الاختبارات الوحدوية والتراجعية للحالات الحدية (`Mistakes #27–#38`) | `python3 scripts/test_skill_gates.py` |

### ب) ملفات التوثيق المرجعية (`turath-deep-indexing/references/`)
- [`SKILL.md`](file:///Users/macm1pro/REPOS/SKILLS/turath-deep-indexing/SKILL.md): الدليل التنفيذي الشامل للإصدار `v5.6`.
- [`01-architecture-and-schema-v4.md`](file:///Users/macm1pro/REPOS/SKILLS/turath-deep-indexing/references/01-architecture-and-schema-v4.md): المعمارية ذات الطبقتين وجدول الـ 22 علماً المسجلة.
- [`02-pre-flight-and-footnotes.md`](file:///Users/macm1pro/REPOS/SKILLS/turath-deep-indexing/references/02-pre-flight-and-footnotes.md): معالجة الحواشي والترقيم في طبعات الشاملة وتراث.
- [`03-extraction-rules-and-gate-v4.md`](file:///Users/macm1pro/REPOS/SKILLS/turath-deep-indexing/references/03-extraction-rules-and-gate-v4.md): قواعد الاستخراج الوكيلي وبوابة `0 P0`.
- [`04-all-mistakes-and-postmortems.md`](file:///Users/macm1pro/REPOS/SKILLS/turath-deep-indexing/references/04-all-mistakes-and-postmortems.md): سجل الأخطاء الـ 38 (`Mistakes #1–#38` في 6 مجموعات) وأسبابها الجذرية وحلولها البرمجية.
- [`05-rounds-1-to-3-status-and-roadmap.md`](file:///Users/macm1pro/REPOS/SKILLS/turath-deep-indexing/references/05-rounds-1-to-3-status-and-roadmap.md): سجل الجولات `Round 1..10` (`81` كتاباً تراثياً مفهرساً بمعيار `0 P0`).
- [`06-usdb-v5-universal-adapters.md`](file:///Users/macm1pro/REPOS/SKILLS/turath-deep-indexing/references/06-usdb-v5-universal-adapters.md): توثيق المحولات الأربعة (`Adapters A–D`) وترقيات `USDB v5.6`.

---

## ٣. كيف تعمل المهارة على أي سلسلة دروس أو كتاب؟ (دورة العمل من ٣ خطوات)

1. **الخطوة ١ (تجهيز ملف الإدخال الخام):**
   - لسلسلة دروس مفرغة ومحاذاة صوتياً (مثلاً من `/Users/macm1pro/REPOS/hawshat/playlists/lessons/<series>/` أو من مخرجات `sheikh-series-pipeline` مثل `/tmp/bardouni_1005_after/`): يُبنى ملف `raw_lectures.json` يضم نص كل حلقة (`text`) ومسار ملف محاذاتها (`align_path`: `.align.json`) ورمز الفيديو (`video_id`) وفقرات المتن المشروح (`base_matn_clauses`) إن كانت السلسلة شرحاً لمتن.
2. **الخطوة ٢ (الاستخراج الوكيلي بالمراسي فقط — `deep_lecture_<id>.json`):**
   - يقرأ الوكيل نص الحلقة، ولا ينسخ المتن الطويل، بل يقسمه موضوعياً بوضع **مرساة نصية قصيرة (`anchor_start` من 4–8 كلمات حرفية)** لكل مقطع (`<= 2800` حرف)، ويستخرج:
     - `sub_heading`, `summary`, `topics`, `persons`, `places`, `chronology`, `evidences`, `search_queries`
     - `explained_matn_clause_id` + `explained_matn_verbatim` (إن كان يشرح فقرة متن)
     - `science_gems` (`verbatim_rule` حرفياً من التفريغ + `polished_rule` مصفاة من اللوازم الشفهية `يعني / طيب / تمام؟`)
     - `stories` (الأمثلة والوقائع المسردة) و`quotes` (الاقتباسات).
3. **الخطوة ٣ (الدمج الحتمي وبوابة `0 P0`):**
   - تشغيل:
     ```bash
     python3 /Users/macm1pro/REPOS/SKILLS/turath-deep-indexing/scripts/merge_lecture.py --work-dir <dir>
     ```
   - يقوم السكربت بقص النص الأصلي حرفياً بين المراسي (`100% Zero Loss`)، وإسقاط ثواني البداية والنهاية (`start_sec`, `end_sec`, `youtube_clip_url`) لكل مقطع ودرة وقصة واقتباس من `.align.json`، والتحقق من خلو الاستخراج من أي خطأ `P0`.

---

## ٤. القواعد الحاكمة للوكيل القادم (تذكير سريع)

1. **العمليات الطرفية:** أمر واحد في كل مرة (يُمنع منعاً باتاً ربط الأوامر بـ `&&` أو `;`).
2. **التواصل والشرح:** خطوة صغيرة واحدة في كل مرة، المستخدم يقرر والوكيل يقترح وينفذ، جمل قصيرة ومفيدة بلا حشو، وعدم استخدام وسوم `RTL` (`<div dir="rtl">`).
3. **عدم توليد واجهات أو نتائج غير مطلوبة:** التزم بدقة بما يطلبه المستخدم في خطوته الحالية.

---

## ٥. المهمة المباشرة الجاهزة للبدء في المحادثة الجديدة

طلب المستخدم قبل الانتقال للمحادثة الجديدة:
> **«أريد نجرب المهارة ، نجرب على سلسلة معينة ؟»**

**الخيارات الخفيفة الجاهزة فوراً للتجربة في المحادثة الجديدة (ليختار المستخدم إحداها):**
1. **سلسلة قصيرة جاهزة في `hawshat/playlists/lessons/` (مفرغة ومحاذاة بالكلمة `.txt` + `.align.json`):**
   - `alamri-mayar-ilm` (معيار العلم للشيخ علي العمري — **درسان فقط**، `107 KB`).
   - `alamri-qawaid-tasawwuf` (قواعد التصوف للشيخ علي العمري — **درسان فقط**، `119 KB`).
   - `bouti-387` (الدكتور محمد سعيد رمضان البوطي — **3 دروس قصيرة**، `68 KB`).
2. **أو تجربة التكامل المباشر مع مخرجات `sheikh-series-pipeline` v4.2 الجاهزة على الماك:**
   - فهرسة درس أو درسين (أو السلسلة) من **«مقدمات السنوسي» للشيخ محمد البردوني (`bardouni-husaymi/1005`)** التي فُرّغت وحُوذيت للتو بدقة `99.72%` في `/tmp/bardouni_1005_after/ytb/bardouni-husaymi/1005/` + `/tmp/bardouni_1005_pure/out/` مع ربطها بفقرات متن *المقدمات* للإمام السنوسي.

---

## ٦. تنفيذ التجربة العملية الكاملة على سلسلة «شرح المقدمات للسنوسي — الشيخ محمد البردوني الحسيمي» (`9/9 PASSED, 0 P0`)

تم تنفيذ الفهرسة العميقة الكاملة (`Track 2: Spoken Video Lectures` + `Track 4: Cross-Corpus Knowledge Graph`) على كامل السلسلة (**9 دروس، 10 ساعات و23 دقيقة، 308,201 حرف، 55,481 كلمة**) في `/tmp/bardouni_muqaddimat_usdb/`:

1. **إصلاحان برمجيان للتكامل المباشر مع `sheikh-series-pipeline` v4.2:**
   - في [`merge_lecture.py`](file:///Users/macm1pro/REPOS/SKILLS/turath-deep-indexing/scripts/merge_lecture.py): دعم المفتاح `"x"` الذي يولده `ctc_pure_align.py` v4.2 في ملفات `.align.json` إلى جانب المفتاح `"w"`، مع إضافة اختبار انحداري `test_12_ctc_pure_v4_x_key_support` في [`test_skill_gates.py`](file:///Users/macm1pro/REPOS/SKILLS/turath-deep-indexing/scripts/test_skill_gates.py) (`12/12 OK`).
   - في [`build_cross_corpus_graph.py`](file:///Users/macm1pro/REPOS/SKILLS/turath-deep-indexing/scripts/build_cross_corpus_graph.py): تجميع كل فقرات المتن (`base_matn_clauses`) عبر جميع دروس السلسلة المشتركة في `base_work_id` (`27` فقرة من `MUQ:01_1` إلى `MUQ:09_3`)، مع الرجوع التلقائي إلى مستودع الكتب التراثية (`81` كتاباً) عند تشغيل `--work-dir` في مجلد معزول.
2. **حصيلة التحقق الصارم (`Gate v5.1` — `0 P0` في جميع الدروس التسعة):**
   - **الدروس المفهرسة:** `9 / 9` (`bardouni_muqaddimat_01` .. `bardouni_muqaddimat_09`) — كلها `passed=True, p0=0`، استرجاع نصي `100% Zero Loss` (`308,201 / 308,201` حرف)، ومحاذاة زمنية `ctc_forced_alignment` من `.align.json`.
   - **إجمالي المقاطع الموضوعية (`deep_toc_passages`):** `153` مقطعاً مفصلاً مع روابط يوتيوب بالثانية (`youtube_clip_url`).
   - **درر القواعد والضوابط (`science_gems`):** `54` قاعدة عقدية ومنطقية وأصولية بطبقتين (`verbatim_rule` حرفية + `polished_rule` مصقولة خالية من الحشو الشفهي).
   - **الربط الثلاثي بالمتن (`matn_triangulation`):** `54` موضع شرح مربوطاً بـ `27` فقرة من متن وشرح *المقدمات* للإمام السنوسي (`MUQ:01_1` .. `MUQ:09_3`) وبـ `81` كتاباً تراثياً مكتوباً.
   - **المناظرات والأمثلة التطبيقية (`stories`) والاقتباسات (`quotes`):** `33` مناظرة ومثالاً تطبيقياً + `41` اقتباساً موثقاً بالثانية.

