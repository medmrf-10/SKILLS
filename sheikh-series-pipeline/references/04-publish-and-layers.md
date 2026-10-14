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
أسماء المدخلات المتوقعة في `ytb-build/align-out/`:

- `sharawi-539-001.align.json` — تمريرة turbo-q4 الأولى.
- `sharawi-539-001.lv3.align.json` — تمريرة large-v3 الثانية، **وتفوز إن وُجدت**.

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
python3 /root/workspace/ytb-build/check_transcripts.py /root/workspace/ytb      # exit 1 = عيب
python3 /root/workspace/ytb-build/sanitize_preamble.py --apply <root>          # قطع سرد إنجليزي + أرشفة
```

- الحاوية تكشف: `LATIN_PREAMBLE` (سرد وكيل إنجليزي في أول ٢٠٠ حرف)، `EMPTY` (لا حروف عربية)،
  `SHORT` (<٤٠٠ حرف عربي)، `META_MISMATCH` (`chars` في meta ≠ الطول الحقيقي).
- التنظيف **لا يحذف**: الأصل يُؤرشف في `<root>/_fix/english-preamble/` ويُحدَّث `chars/sha256/cleaned`.
- حدث فعلاً تسرّب في ١٠٤ ملفات (ytb ٣٢ + hawshat ٤٨ + irth ٢٤) فُنظّفت وأُرشفت ودفعت بعدها.

## المساحة على الماك (شرط السلاسل الطويلة)

- شرط البدء في `safe_run.sh` للماك: `disk_free ≥ 6000MB` (وحدود القدرة في `05-mac-and-vps.md`).
- المنظّف `mac_cleanup_aligned.sh` يُشغّل من الخادم كل ٣٠ دقيقة (cron) مع تثبيت نسخته على الماك:
  يحذف **الصوت فقط** للدروس التي تُوجد لها محاذاة مكتوبة (`out/<tag>_<nn>.small.align.json`)، ويحفظ النصوص والنتائج،
  ولا يلمس تسمية يجري محاذاتها الآن (`aligning_procs`). سجله: `ytb-build/logs/mac_cleanup.log` و`~/align_sharawi/logs/cleanup.log`.
- القياس عند أول تشغيل صحيح: محى ١٠ ملفات صوت ⇒ وفّر ١٢٨MB، والقرص الحر ١٣٫٨GB.
- **عطل مُصلح يجب تذكّره**: المُثبِّت كان يستعمل `ssh -n … 'cat > file'` و`-n` يوجّه stdin إلى `/dev/null`
  ⇒ يُكتب ملف **فارغ** على الماك في كل مرّة، والسجل يقول «installed» كذباً ⇒ التنظيف متوقف بصفة صامتة.
  الإصلاح: أزل `-n` من سطر التثبيت (تحقّق دائماً بـ`wc -c` بعد أي تنصيب عن بعد).

## التجهيز المسبق (توازي خادم↔ماك)

- `prefetch_audio_range.sh <lo> <hi>` ينزّل صوت صفوف الشعراوي في النطاق مقدّماً بترتيب المصحف
  حتى يجد خطّ المحاذاة الملفات جاهزة ولا ينتظر الماك التنزيل؛ سجلّه `logs/prefetch_audio_range_<lo>_<hi>.log`.
- `fetch_row_audio.sh <sheikh/row>` ينزّل صوت صفّ كامل (للكهف: `audio/kahf539-NNN`).
- **خطة المالك المعلّقة (`§20`)**: الخادم يجهّز الصفوف التالية (وتنزيل + نصوص + نقل للماك) في الخلفية أثناء انشغال الماك،
  وحذف صوت الماك المنتهي بعد نشر كل صفّ — لا تنفّذ قبل «ابدأ».
