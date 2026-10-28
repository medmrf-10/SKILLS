# أدلة معالجة الأعطال والاسترداد (`02-failure-playbooks-and-recovery`)

يوثق هذا المرجع خطوات التشخيص الجذري والاسترداد الآمن عند توقف أي بوابة من البوابات الصارمة (`G0`–`G5`) في مهارة `person-to-knowledge-orchestrator`.

---

## 1. أعطال البوابة `G0` (الحصة وعزل البيئة والطبقة الصفرية)

1. **العطل `G0_QUOTA_BELOW_THRESHOLD` أو نفاد الحساب النشط**:
   1. السبب الجذري: انخفاض الحصة المتبقية في الحساب الحالي دون `20.0%` أو دخوله في حالة تبريد (`429`).
   2. إجراء الإصلاح: الانتقال التلقائي وفق شلال الحسابات الصارم (`العائلة -> brain -> ram`) عبر `$SKILLS_DIR/agy-multi-account` مع حظر استخدام حساب `medmrf10` أو أي مفاتيح `API` خارجية.
2. **العطل `G0_LEAN_HOME_NOT_ISOLATED` أو تسرب خوادم `MCP`**:
   1. السبب الجذري: وجود روابط لملفات `mcp_config.json` أو إضافات المتصفح داخل بيئة `HOME` المعزولة.
   2. إجراء الإصلاح: إعادة تهيئة البيئة المعزولة عبر `$SKILLS_DIR/agy-lean-cli/scripts/agy_lean.py` والتأكد من أن `violations == []`.

---

## 2. أعطال البوابتين `G1` و`G2` (الجرد والتنقيح الدلالي)

1. **العطل `G1_EMPTY_DISCOVERY` أو نقص بيانات الدروس**:
   1. السبب الجذري: فشل جلب قوائم التشغيل أو نقص حقلي `video_id` و`title` في بعض العناصر.
   2. إجراء الإصلاح: فحص المصدر الأصلي يدوياً واستكمال المعرفات الناقصة في `01_discovery/<person_id>_raw.json` قبل إعادة تشغيل المرحلة 1.
2. **العطل `G2_SCANNER_FLAWS` أو `G2_DUPLICATE_ACTIVE_VIDEOS`**:
   1. السبب الجذري: وجود حلقات مكررة بين السلاسل والمحاضرات المستقلة أو خلل في ترتيب الحلقات.
   2. إجراء الإصلاح: مراجعة مخرجات `$SKILLS_DIR/sheikh-curation/scripts/deep_scanner_all.py` و`$SKILLS_DIR/sheikh-curation/scripts/global_audit.py` وإزالة التكرار من `02_curated/<person_id>.json` حتى تصبح النتيجة `0 errors`.

---

## 3. أعطال البوابة `G3` (التفريغ النصي وحفظ أحرف الكتب)

1. **العطل `G3_UNSANITIZED_PREAMBLE` في ملفات الدروس `.txt`**:
   1. السبب الجذري: بقاء عبارات افتتاحية أو ختامية من نموذج التفريغ في بداية أو نهاية الملف النصي.
   2. إجراء الإصلاح: تشغيل `$SKILLS_DIR/sheikh-series-pipeline/scripts/sanitize_preamble.py` وفحص الملف يدوياً للتأكد من سلامة مطلع الدرس وخاتمته.
2. **العطل `G3_BOOK_CHAR_LOSS` أو `orphan_head` في الكتب**:
   1. السبب الجذري: سقوط أحرف أثناء تحويل الحواشي أو وجود أسطر حواشٍ غير مرقمة في `footnotes`.
   2. إجراء الإصلاح: مراجعة `adapter_manifest.json` وتوجيه الحواشي غير المرقمة أو خواتيم الطبع إلى `margin_notes` عبر `$SKILLS_DIR/turath-pdf-to-text/scripts/pdf_to_preflight_adapter.py` لضمان `retention_pct == 100.0`.

---

## 4. أعطال البوابتين `G4` و`G5` (الفهرسة العميقة والتضمين)

1. **العطل `G4_SQLITE_CHAR_LOSS` أو `P0_NON_MONOTONIC_ANCHOR`**:
   1. السبب الجذري: عدم تطابق `anchor_start` مع مواضع التقطيع الحرفي للمقاطع في `merge_round.py` أو `merge_lecture.py`.
   2. إجراء الإصلاح: تصحيح `anchor_start` ليطابق الكلمات الأولى الحرفية للمقطع بالضبط وإعادة بناء `04_knowledge_db/<person_id>_objects.sqlite` حتى يصبح `chars_lost == 0`.
2. **العطل `G4_INVALID_PERSON_LAYER` أو تسرب رواة السند إلى المتن**:
   1. السبب الجذري: تصنيف راوٍ ورد في سلسلة الإسناد (`حدثنا`, `أخبرنا`) ضمن طبقة `matn` بدلاً من `isnad`.
   2. إجراء الإصلاح: ضبط `matn_start_anchor` لفصل مقدمة السند عن نص المتن ووسم رواة السند بـ `source_layer="isnad"` وتواريخ وفياتهم بـ `event_layer="transmission"`.
3. **العطل `G5_HONORIFIC_LEAK_IN_CONCEPT` أو نقص المتجهات**:
   1. السبب الجذري: بقاء رموز الترضية المدمجة (`\ufdfa`–`\ufdff`) في `embed_concept_text` أو انقطاع عملية التضمين المحلي.
   2. إجراء الإصلاح: تفكيك رموز الترضية عبر `expand_honorific_ligatures` في `$SKILLS_DIR/turath-embedding-gemma2/scripts/embed_corpus_gemma2.py` وإعادة التضمين المحلي حتى تكتمل المتجهات بنسبة `100%`.
