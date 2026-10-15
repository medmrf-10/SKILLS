# ٠٤ — الطبقات والنشر والمساحة

## مخطط `align.json` الموحّد (نفس مخطط مخزن irth)

```json
{"v": 1, "cov": 0.824, "words": ["…"], "start": [ms…], "dur": [ms…]}
```

ويُسجّل ملخّص بجانب النص في `<NNN>_<VID>.meta.json` تحت `align`:
`{"cov":…, "cov_strict":…, "model":"…", "words":2784, "at":"…"}`.
**قاعدة التعديل**: مفاتيح `meta.json` تُضاف ولا تُحذف أبداً.

## `attach_align.py <sheikh/row> [--align-dir DIR] [--dry]`

ينشر نتائج المحاذاة بجانب نصوصها في ytb: `<NNN>_<VID>.align.json`، ويحدّث `meta.json` بالملخّص.
صيغ أسماء المدخلات المتوقعة في `ytb-build/align-out/`:

- `<slug>-<row>-<NNN>.align.json` — مخرج المحاذاة الأولية.
- `<slug>-<row>-<NNN>.v3.align.json` — مخرج بنية v3 المعتمدة (وتفوز تلقائياً).
- `<slug>-<row>-<NNN>.lv3.align.json` — مخرج الجيل الأول بنموذج large-v3.

## `copy_layers.py` — نسخ الطبقات بالهوية فقط

لكل درس محلول في `ytb/_meta/plan.jsonl` يبحث عن طبقاته (align/sum/questions) في مخازن المصدر وينسخها
بجانب النص: `<stem>.align.json`, `<stem>.sum.json`, `<stem>.questions.json`.
- **المطابقة بالهوية فقط**: youtube id، وإلا (row-key + رقم الدرس) — **أبداً برقم ملف في des/durus**.
- يُخرج `ytb/_meta/layers.json` (درس ← طبقات وُجدت) و`ytb/_meta/layers-report.json` (مصادر بلا مقابل).
- قرار المالك (١٣ أكتوبر): طبقة المحاذاة **غير اختيارية** — أسبوع عمل، لا تُسقط أبداً.

## أوراق الروابط والصفوف

- `make_series_sheet.py` / `make_links_sheet.py` / `publish_links_sheet*.py` + `links-sheet/` + `series-sheet.json`.
- `publish_row.py` · `publish_cls.py` · `copy_to_ytb.py` · `copy_tree.py` — أدوات النشر والنسخ بين المخازن.
- **لا تشغّل أداة نشر بلا أمر صريح، ولا تدفع شيئاً إلى GitHub بلا أمر صريح**، ولا تعدّل `SelectedLessons` ولا أي مخزن مصدر.

## بوابة الجودة قبل النشر

```bash
python3 ${SERIES_WORKSPACE}/ytb-build/check_transcripts.py ${SERIES_WORKSPACE}/ytb      # exit 1 = عيب
python3 ${SERIES_WORKSPACE}/ytb-build/sanitize_preamble.py --apply <root>          # قطع سرد إنجليزي + أرشفة
```

- الحاوية تكشف: `LATIN_PREAMBLE` (سرد وكيل إنجليزي في أول ٢٠٠ حرف)، `EMPTY` (لا حروف عربية)،
  `SHORT` (<٤٠٠ حرف عربي)، `META_MISMATCH` (`chars` في meta ≠ الطول الحقيقي).
- التنظيف **لا يحذف**: الأصل يُؤرشف في `<root>/_fix/english-preamble/` ويُحدَّث `chars/sha256/cleaned`.
- حدث فعلاً تسرّب في ١٠٤ ملفات فُنظّفت وأُرشفت قبل النشر (التفاصيل في `08-measured-baselines.md`).

## المساحة على المسرّع (شرط السلاسل الطويلة)

- شرط البدء في `safe_run.sh` للمسرّع: `disk_free ≥ $FREE_SPACE_MIN_MB` (افتراضياً ٦,٠٠٠MB — التفاصيل في `05-hardware-and-execution-profiles.md`).
- سكربت تنظيف المسرّع يُشغّل من الخادم دورياً (cron) مع تثبيت نسخته على جهاز التسريع:
  يحذف **الصوت فقط** للدروس التي كُتبت محاذاتها بنجاح، ويحفظ النصوص والنتائج، ولا يلمس تسمية يجري محاذاتها في لحظة التنظيف.
- **عطل مُصلح يجب تذكّره**: المُثبِّت كان يستعمل `ssh -n … 'cat > file'` و`-n` يوجّه stdin إلى `/dev/null`
  ⇒ يُكتب ملف **فارغ** على المسرّع في كل مرّة، والسجل يقول «installed» كذباً ⇒ التنظيف متوقف بصفة صامتة.
  الإصلاح: أزل `-n` من سطر التثبيت (تحقّق دائماً بـ`wc -c` بعد أي تنصيب عن بعد).

## التجهيز المسبق (توازي خادم ↔ مسرّع)

- `prefetch_audio_range.sh <lo> <hi>` ينزّل صوت صفوف السلسلة في النطاق مقدّماً وفق ترتيبها المقرر
  حتى يجد خطّ المحاذاة الملفات جاهزة ولا ينتظر المسرّع التنزيل.
- `fetch_row_audio.sh <sheikh/row>` ينزّل صوت صفّ كامل بالمعاملات.
- الخادم يجهّز الصفوف التالية (تنزيل + نصوص + نقل للمسرّع) في الخلفية أثناء انشغال المسرّع، وحذف صوت المسرّع المنتهي بعد نشر كل صفّ.
