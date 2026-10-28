# التنسيق الشامل وبوابات التحقق الصارمة (`G0`–`G5`)

يوثق هذا المرجع العقود والمدخلات والمخرجات والشروط الحتمية لبوابات الجودة الست (`G0` إلى `G5`) في مهارة `person-to-knowledge-orchestrator`.

---

## 1. مصفوفة تكامل المهارات عبر المراحل الست

1. **المرحلة 0 (`Stage 0`) — الطبقة الصفرية وحارس الحصة والعزل**:
   1. المهارات المرتبطة: `$SKILLS_DIR/agy-lean-cli` و`$SKILLS_DIR/agy-multi-account`.
   2. المدخلات: بطاقة هوية العلم وفهرسه المعياري المعتمد من محمد، وحالة الحسابات في شلال الأولويات (`العائلة -> brain -> ram`).
   3. المخرجات: `00_quota/quota_guard_report.json`.
   4. البوابة الصارمة `G0`: اعتماد الفهرس المعياري للعلم، وتوفر حصة `>= 20.0%`، وعزل بيئة `HOME` الخفيفة (`mcp_servers == 0` و`plugins == 0`).
2. **المرحلة 1 (`Stage 1`) — الجرد الأولي للمصادر**:
   1. المدخلات: روابط قنوات وقوائم يوتيوب، ومعرفات `Archive.org`، وفهارس الأعمال، وقوائم الكتب المؤلفة أو المشروحة.
   2. المخرجات: `01_discovery/<person_id>_raw.json`.
   3. البوابة الصارمة `G1`: مطابقة مخطط الجرد القياسي، ووجود مصادر صالحة غير فارغة (`total_sources > 0`) بعد المراجعة اليدوية للعينة.
3. **المرحلة 2 (`Stage 2`) — التنقيح الدلالي للسلاسل والدروس**:
   1. المهارة المرتبطة: `$SKILLS_DIR/sheikh-curation`.
   2. المدخلات: `01_discovery/<person_id>_raw.json`.
   3. المخرجات: `02_curated/<person_id>.json`، و`02_curated/curated.db`، وملفات `02_curated/series/<person_id>/sXXX/_meta.json`.
   4. البوابة الصارمة `G2`: `0` عيوب في `deep_scanner_all.py`، و`0` أخطاء في `global_audit.py`، و`0` تكرار لمعرفات `video_id`.
4. **المرحلة 3 (`Stage 3`) — الاستخراج النصي المزدوج والمحاذاة الصوتية الحقيقية**:
   1. المهارات المرتبطة: `$SKILLS_DIR/sheikh-series-pipeline` و`$SKILLS_DIR/turath-pdf-to-text`.
   2. المدخلات: السلاسل المنقحة وتفريغاتها الصوتية وملفات الكتب (`PDF` أو النصوص المهيكلة).
   3. المخرجات: `03_extracted/series/<person_id>/sXXX/*` و`03_extracted/books/<book_slug>/{adapter_manifest.json, raw_round4_books.json, ...}`.
   4. البوابة الصارمة `G3`: `0` مقدمات أو خواتيم آلية في ملفات `.txt`، ومحاذاة `CTC` حقيقية غير مزيفة، وحفظ حرفي بنسبة `100.0%` في الكتب (`body_char_loss == 0` و`footnotes_char_loss == 0`).
5. **المرحلة 4 (`Stage 4`) — الفهرسة العميقة الموحدة وبناء قاعدة الكيانات**:
   1. المهارة المرتبطة: `$SKILLS_DIR/turath-deep-indexing`.
   2. المدخلات: مخرجات `03_extracted/series/...` و`03_extracted/books/...` مع الفهرس العام المعياري للعلم.
   3. المخرجات: `04_knowledge_db/<person_id>_objects.sqlite`، و`round4_9_books_deep.json`، و`lectures_deep_merged.json`، وتقارير البوابات `gate_report_*.json`.
   4. البوابة الصارمة `G4`: نجاح بوابات الفهرسة بـ `0` أخطاء حرجة (`total_p0_errors == 0`)، و`chars_lost == 0` في `SQLite`، و`0` تسرب بين طبقات السند والمتن.
6. **المرحلة 5 (`Stage 5`) — التضمين الشعاعي المزدوج المحلي والبحث الهجين**:
   1. المهارة المرتبطة: `$SKILLS_DIR/turath-embedding-gemma2`.
   2. المدخلات: `04_knowledge_db/<person_id>_objects.sqlite`.
   3. المخرجات: جداول المتجهات `passage_embeddings` و`gem_embeddings` داخل `<person_id>_objects.sqlite`، وتقارير `05_reports/ORCHESTRATION_REPORT.md`.
   4. البوابة الصارمة `G5`: تغطية التضمين بنسبة `100%` (`3072` بايت لكل متجه `float32` ذي بعد `768`)، و`0` رموز ترضية مدمجة في نص المفهوم، ونجاح اختبارات البحث الهجين المفلتر.

---

## 2. المواصفات التفصيلية للبوابات (`G0`–`G5`)

### البوابة `G0`: الطبقة الصفرية وحارس الحصة والعزل
1. التحقق من اعتماد «بطاقة هوية العلم» و«الفهرس العام المعياري للعلم» من محمد قبل تشغيل أي فهرسة.
2. التحقق من أن الحساب المختار ضمن شلال (`العائلة -> brain -> ram`) يملك حصة متبقية `>= 20.0%` مع حظر استخدام حساب `medmrf10` أو أي مفاتيح `API` خارجية.
3. التحقق من أن `isolation_info["isolated"] == True` مع `mcp_servers_count == 0` و`plugins_count == 0`.

### البوابة `G1`: سلامة الجرد الأولي للمصادر
1. وجود ملف `01_discovery/<person_id>_raw.json` وصلاحية بنيته بصيغة `JSON`.
2. توفر المفاتيح الأساسية: `person_id`, `sheikh_name`, `playlists`, `videos`, `archive_items`, `books`, `stats`.
3. وجود مصدر واحد صالح على الأقل (`len(videos) + len(books) + len(archive_items) > 0`) مع اكتمال حقلي `video_id` و`title` لكل درس مرئي أو صوتي.

### البوابة `G2`: التحقق من التنقيح الدلالي (`9-Stage Curation`)
1. وجود ملفات `02_curated/<person_id>.json` و`02_curated/curated.db`.
2. إرجاع `deep_scanner_all.py` لعدد `0` عيوب (`scanner_flaws_total == 0`).
3. إرجاع `global_audit.py` لرمز خروج `0` مع نص `"0 errors"`.
4. تفرد جميع معرفات `video_id` النشطة عبر السلاسل والمحاضرات المستقلة (`0` مكررات).
5. وجود ملف `_meta.json` لكل سلسلة منقحة في `02_curated/series/<person_id>/<series_id>/_meta.json`.

### البوابة `G3`: الاستخراج النصي والتطهير والمحاذاة
1. فحوص المسار `3A` (تفريغ السلاسل الصوتية):
   1. وجود `_meta.json` في كل مجلد سلسلة داخل `03_extracted/series/<person_id>/sXXX/`.
   2. عدم فراغ أي ملف `.txt` (`len(text.strip()) > 0`).
   3. إرجاع دالة `strip_preamble_and_header(text)` لقائمة أسباب فارغة `[]` (انعدام المقدمات والخواتيم الآلية).
   4. وجود ملف محاذاة `.align.json` حقيقي ناتج عن محرك `CTC` الفعلي وليس مولداً بمعادلات حسابية صورية.
2. فحوص المسار `3B` (الكتب):
   1. وجود ملفات `adapter_manifest.json` و`round_manifest_r4_r10.json` و`raw_round4_books.json` لكل كتاب في `03_extracted/books/<book_slug>/`.
   2. كون `adapter_manifest["status"] == "PASS"` مع `body_char_loss == 0` و`footnotes_char_loss == 0` و`retention_pct == 100.0`.
   3. نجاح `adapter_manifest["manifest_v4_verification"]["passed"] == True`.

### البوابة `G4`: الفهرسة العميقة وبناء قاعدة `SQLite` بلا فقد حرفي
1. نجاح تقارير البوابات `gate_report_books.json` و`gate_report_lectures.json` بحالة `"PASS"` و`total_p0_errors == 0`.
2. تطابق عدد الأحرف الخام مع مجموع أحرف المقاطع في `build_objects_sqlite.py` (`chars_lost == 0`).
3. التحقق المباشر داخل قاعدة `04_knowledge_db/<person_id>_objects.sqlite`:
   1. وجود الجداول العلائقية وجداول `FTS5` المعتمدة (`sources`, `series`, `lessons_or_parts`, `passages`, `passages_fts`, `persons`, `passage_persons`, `places`, `passage_places`, `events_chronology`, `stories_cases`, `science_gems`, `evidences`, `matn_triangulation`).
   2. تطابق `SELECT SUM(LENGTH(raw_text)) FROM passages` مع إجمالي الأحرف الأصلية.
   3. انعدام ظهور رواة سلاسل الإسناد في طبقة `source_layer = 'matn'`.
   4. انعدام ظهور سنوات وفيات الرواة في طبقة `event_layer = 'historical'`.

### البوابة `G5`: التضمين الشعاعي المزدوج والبحث الهجين
1. تغطية جدول `passage_embeddings` لجميع صفوف `passages` وتغطية جدول `gem_embeddings` لجميع صفوف `science_gems` بنسبة `100%`.
2. مطابقة طول كل متجه ثنائي (`vec_matn_blob`, `vec_concept_blob`) لـ `3072` بايت (`768 * 4`) ومعيار `L2 norm` في نطاق `1.0 ± 1e-3`.
3. خلو جميع نصوص `embed_concept_text` من محارف الترضية المدمجة (`HONORIFIC_RANGE_RE`).
4. نجاح استعلامات `HybridSearchEngine` عبر أوضاع `hybrid` و`matn` و`concept` و`fts` مع التحقق من عزل طبقة `person_layer="matn"`.

---

## 3. مخطط حالة خط الإنتاج القابل للاستئناف (`pipeline_state.json`)

1. يُحفظ ملف `pipeline_state.json` في جذر `$TURATH_ROOT/workspaces/<person_id>/pipeline_state.json` لتوثيق حالة كل مرحلة وبوابتها:

```json
{
  "person_id": "kamali",
  "person_name": "الشيخ سعيد الكملي",
  "work_dir": "$TURATH_ROOT/workspaces/kamali",
  "updated_at": "2026-10-28T10:00:00Z",
  "overall_status": "PASS",
  "stages": {
    "0": {
      "name": "stage0_quota_and_lean_guard",
      "gate": "G0",
      "status": "PASS",
      "completed_at": "2026-10-28T10:00:01Z",
      "metrics": {
        "remaining_pct": 95.0,
        "isolated": true
      },
      "errors": []
    }
  }
}
```
