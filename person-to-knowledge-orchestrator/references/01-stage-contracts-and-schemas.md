# عقود المراحل والمخططات القياسية (`01-stage-contracts-and-schemas`)

يحدد هذا المرجع العقود الصارمة للمدخلات والمخرجات والمخططات القياسية بين مراحل `person-to-knowledge-orchestrator` الست.

---

## 1. عقد الطبقة الصفرية والمرحلة 0 (`Quota & Lean Isolation Contract`)

1. **مدخلات المرحلة 0**:
   1. وثيقة «بطاقة هوية العلم» و«الفهرس العام المعياري للعلم» المعتمدة من محمد.
   2. حالة الحسابات في `$SKILLS_DIR/agy-multi-account` وفق شلال (`العائلة -> brain -> ram`).
2. **مخرجات المرحلة 0 (`00_quota/quota_guard_report.json`)**:
   1. الحقل `checked_at`: الطابع الزمني للفحص بصيغة `UTC ISO-8601`.
   2. الحقل `selected_model_info`: يضم نسبة الحصة المتبقية `remaining_pct >= 20.0` وحالة الأمان `safe == true`.
   3. الحقل `isolation_info`: يضم `isolated == true` و`violations == []` و`has_clean_cfg == true`.

---

## 2. عقد المرحلة 1 (`Discovery Intake Schema`)

1. **ملف المخرج القياسي (`01_discovery/<person_id>_raw.json`)**:
   1. الحقل `person_id`: معرف نصي ASCII موحد للشخصية.
   2. الحقل `sheikh_name`: الاسم العربي الكامل للشخصية أو المصنف.
   3. الحقل `playlists`: قائمة قوائم التشغيل المكتشفة وعناصرها.
   4. الحقل `videos`: قائمة الدروس والمحاضرات المفردة مع `video_id` و`title` و`duration`.
   5. الحقل `archive_items`: قائمة حزم `Archive.org` الصوتية أو المرئية.
   6. الحقل `books`: قائمة الكتب المؤلفة أو المتون المشروحة المرتبطة بالشخصية.
   7. الحقل `stats`: إحصائيات الجرد الإجمالية بعد إزالة المعرفات المكررة.

---

## 3. عقد المرحلة 2 (`Curation v2 Schema`)

1. **ملفات المخرجات القياسية في `02_curated/`**:
   1. الملف `<person_id>.json`: يضم قوائم `series` و`standalone_lectures` و`excluded_videos` بعد التصنيف الدلالي.
   2. قاعدة البيانات `curated.db`: تحتوي على جدولي `series` و`lessons` بحالة الترقيم والتتبع.
   3. ملفات السلاسل `series/<person_id>/sXXX/_meta.json`: تضم بيانات السلسلة والكتاب المشروح (`matched_book`) وقائمة الدروس المرتبة.

---

## 4. عقد المرحلة 3 (`Dual-Track Extraction Schema`)

1. **مخرجات المسار الصوتي (`03_extracted/series/<person_id>/sXXX/`)**:
   1. الملف `<NNN>_<video_id>.txt`: النص العربي الصافي للدرس بعد إزالة أي مقدمات أو خواتيم آلية.
   2. الملف `<NNN>_<video_id>.align.json`: مصفوفة المحاذاة الصوتية الحقيقية بالكلمة `{"w": [[word, start_sec, end_sec], ...]}` الناتجة عن محرك `CTC`.
   3. الملف `<NNN>_<video_id>.meta.json`: البيانات الوصفية للدرس (`video_id`, `title`, `part_number`, `series_id`, `dur_s`).
2. **مخرجات مسار الكتب (`03_extracted/books/<book_slug>/`)**:
   1. الملف `adapter_manifest.json`: يثبت `status == "PASS"` و`body_char_loss == 0` و`footnotes_char_loss == 0` و`retention_pct == 100.0`.
   2. الملف `raw_round4_books.json`: النص الكامل لأجزاء الكتاب مع حواشيه المربوطة.

---

## 5. عقد المرحلة 4 والمرحلة 5 (`USDB v5.7 & Dual Embeddings Schema`)

1. **الجداول الإلزامية في `04_knowledge_db/<person_id>_objects.sqlite`**:
   1. جداول الأصول والفقرات: `sources`, `series`, `lessons_or_parts`, `passages`, `passages_fts`.
   2. جداول الكيانات المعزولة بالطبقات: `persons`, `passage_persons` (`source_layer` في `matn` أو `isnad`), `places`, `passage_places`, `events_chronology` (`event_layer` في `historical` أو `transmission`).
   3. جداول المعرفة المستخلصة: `stories_cases`, `science_gems`, `evidences`, `matn_triangulation`.
   4. جداول التضمين الشعاعي المزدوج: `passage_embeddings` و`gem_embeddings` بأبعاد `768` (`3072` بايت لكل متجه `float32`).
