# 05 — ما أُنجز في `Gate v4.1` وخارطة الطريق للوكيل القادم (Completed Milestones & Open Roadmap)

يوثق هذا الملف **ما اكتمل فعلياً** حتى ترقية `Gate v4.1 (v4.1_strict_grounded)` مقابل **ما لا يزال بحاجة إلى استكمال** في `/Users/macm1pro/REPOS/books`.

---

## 1. ما أُنجز بالكامل (`Completed Milestones`)

1. **اكتمال البنية النصية والربط الموضعي (`100%` عبر 81 كتاباً):**
   - 81 كتاباً عبر 10 جولات (`1,580` مقطعاً، `868` درة، `526` قصة/حالة، `751` اقتباساً، `1,900` حاشية مربوطة بصفر حواشٍ سائبة، `2.13` مليون حرف متن محفوظ حرفياً 100%).
2. **ترقية `manifest_v4.py` إلى `Pre-Flight v4.1` وإعادة توليد `raw_round{4..10}_books.json`:**
   - منع القطع وسط الجملة (`_has_dangling_tail` + `khabar_boundary`) — عالج قطع حديث الجزء 1 في كتاب `2327` (`24,237 -> 24,545` حرفاً).
   - تمييز الخواتيم (`kind: "colophon"`) عن العناوين اليتيمة (`kind: "section_heading"`) — عالج الجزء الأخير من `2412`.
   - معالجة العناوين الصورية (`is_pseudo_heading`, `effective_heading`, `continues_previous_part`) للبسملة والمقدمات الصماء.
   - حماية كتب `tarajim` من تعبير `EDITOR_V4_RE` (`حياته|شيوخه|تلاميذه|مؤلفاته|وفاته`).
   - إضافة `pg_end` و`edition_footnotes_missing_warning`.
3. **ترقية `merge_round.py` إلى `Gate v4.1 (v4.1_strict_grounded)`:**
   - استعادة `sub_heading` (من `title`/`heading`) و`topics` (من `key_topics`/`key_concepts`/`key_claims`/`key_points`) تلقائياً وفرض `P0` على غيابها.
   - إصلاح `resolve_person_mentioned_as` لمنع مطابقة اسم الجد بعد `بن` (`سالم بن عبد الله بن عمر بن الخطاب` لم يعد يطابق `"الخطاب"`)، مع وسم `source_layer` (`"matn"` مقابل `"isnad"`) واستبعاد رواة السند من `embed_concept_text`.
   - عزل الأسانيد الداخلية المرقمة وغير المرقمة (`extract_interior_isnads` بتمريرتين) وتجريدها من `embed_matn_text`.
   - ترقية محلل التواريخ الهجرية لدعم المئات الملتصقة (`ثمانمئة`, `ثلثمئة`)، و`ألف` (`سنة ثمانية وألف`)، والعطف بـ `وقيل` المشترك في المئات/العقود، وحارس المشترك اللفظي `مقدار سِنِّه`، ووسم `event_layer` (`"transmission"` مقابل `"biography_or_event"`).
   - فصل `text_origin` عن `ref_origin` في الأدلة الشرعية (`evidences`).
   - إضافة الفاحص الدلالي الصارم (`check_semantic_grounding_v41`) الذي يفحص حرفية كل اقتباس داخلي `«...»` (`P0_UNVERIFIED_INLINE_QUOTE`) ويمنع هلوسة الإكمال من ذاكرة النموذج في الملخصات وشروح الدرر والقصص (`P0_HALLUCINATED_ENTITY_IN_SUMMARY`, `P0_GEM_COMMENTARY_UNGROUNDED_SCHOLAR`, `P0_GEM_DANGLING_START`).
4. **شفاء الكتب المعيارية الثلاثة بالكامل (`0` أخطاء `P0` تحت `Gate v4.1`):**
   - الكتاب المعياري 1: `2327` (*الفقهاء والعباد* للفسوي — الجولة 5 `r5_deep_tarajim.json`): `passed: True, p0_error_count: 0`.
   - الكتاب المعياري 2: `2412` (*رسالة المسترشدين* للمحاسبي — الجولة 6 `r6_deep_tazkia.json`): `passed: True, p0_error_count: 0`.
   - الكتاب المعياري 3: `6243` (*أخبار النحويين البصريين* للسيرافي — الجولة 10 `r10_deep_tarajim.json`): `passed: True, p0_error_count: 0`.

---

## 2. المهام المتبقية في خارطة الطريق (`Open Backlog for Next Agent`)

### المهمة 1 (عالية الأولوية): تعميم الشفاء واستكمال الكيانات على بقية كتب الجولات 6–10 (`36 كتاباً`)
- **الوضع الحالي:**
  أصبحت البوابة `Gate v4.1` جاهزة ومختبرة بالكامل، وكشفت عند مسح الجولات 4–10 أن 36 كتاباً في الجولات 6 (الدفعة B) و7 و8 و9 و10 لا تزال تفتقر إلى حقول `persons`, `places`, `chronology`, `evidences`, `search_queries` (التي تركها الوكيلان فارغة `[]` سابقاً)، بالإضافة إلى بضعة اقتباسات أو ملخصات فيها `«...»` غير حرفية في الجولات 4–5.
- **خطوات التنفيذ:**
  1. استكمال `persons`, `places`, `chronology`, `evidences`, `search_queries` (و`title` للدرر و`speaker` للاقتباسات في الجولات 7–10) في ملفات `r{6..10}_deep_<science>.json` باتباع نموذج الكتابين المشفيين `r6_deep_tazkia.json` (`2412`) و`r10_deep_tarajim.json` (`6243`).
  2. تنقية أي عبارة `«...»` ملخصة بالمعنى داخل `summary` أو `topics` في بقية الكتب التي يبلغ عنها `check_semantic_grounding_v41`.
  3. إعادة تشغيل `mr.audit_and_merge_round(r)` للجولات `4..10` حتى تمر جميع الكتب بـ `0` أخطاء `P0` تحت `Gate v4.1`، ثم تشغيل `python3 build_practical_data.py` و`python3 build_showcase_site.py`.

---

### المهمة 2 (المرحلة القادمة): الاختبار العملي للتضمين الشعاعي (`EmbeddingGemma 2`)
- **الوضع الحالي:**
  نصوص `embed_matn_text` و`embed_concept_text` باتت في `v4.1` منقاة من الأسانيد الابتدائية والداخلية ومن رواة الإسناد وتواريخ السماع ومن شوائب الحواشي والـ OCR، لكن **لم يتم تشغيل نموذج `EmbeddingGemma 2` الفعلي عليها بعد ولم يُختبر الاسترجاع الشعاعي (`Vector Search Evaluation`)**.
- **خطة التنفيذ عند البدء بها:**
  1. توليد المتجهات الشعاعية (`Embeddings`) لحقلَي `embed_matn_text` و`embed_concept_text` لكل مقطع من المقاطع الـ `1,580`.
  2. بناء مجموعة اختبار استرجاعي (`Retrieval Benchmark`) تقارن دقة البحث في النص الخام للشاملة مقابل البحث الهجين (`embed_matn_text` + `embed_concept_text` + فلاتر الكيانات المؤصلة في المتن).
  3. ربط البحث الشعاعي الدلالي مباشرة بواجهة المنصة العملية (`app.html`).
