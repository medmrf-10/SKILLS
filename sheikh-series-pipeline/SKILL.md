---
name: sheikh-series-pipeline
description: "Use when processing an audio series on Mac (Apple Silicon MPS) or Linux VPS: intake, pluggable transcription with long-lecture chunking, dual-layer quality gate (deterministic + LLM semantic audit), pure CTC v4 alignment, and publish."
version: 2.0.0
author: Mohamed Boumaraf, Hermes Agent
license: MIT
platforms: [linux, macos]
metadata:
  hermes:
    tags: [sheikhs, series, transcription, pluggable, gemini, llm-qa, alignment, pure-ctc, mps, onnx, ctc, mms, vps, macos, arabic, irth, hawshat]
    related_skills: [agy-transcription, youtube-audio-download, agy-worker-orchestration, antigravity-cli, mirath-content-platform]
---

# خطّ سلاسل المشايخ — من التسجيل إلى محاذاة ١٠٠٪ (دعم الماك MPS والخادم VPS)

محرك عام متكامل لاستقبال أي **سلسلة صوتية**، وتسليم: **نصّ مفرَّغ دقيق ومفحوص دلاليًا** عبر طبقة تفريغ تبادلية وبوابة جودة مزدوجة (حتمية + تدقيق LLM) + **محاذاة زمنية لكل كلمة بنسبة تغطية ١٠٠٪** عبر المسار النقي v4 (`align.json`) + الطبقات المعرفية (تلخيص/أسئلة) + النشر في المخزن المعتمد.

يدعم الخط **اختيار بيئة التنفيذ (`--target mac | vps | auto`)** عند استدعاء المهارة:
- **الماك (`--target mac` · Apple Silicon M1 Pro MPS GPU):** يُسرّع المرحلة الصوتية بـ **٣٩× إلى ٥٣×** مقارنةً بمعالج الخادم (درس ٢٧ دقيقة ينتهي من الصفر في **~٥٠ ثانية**، ودرس ٤٤ دقيقة في **~٩٠ ثانية**).
- **الخادم (`--target vps` · Linux VPS CPU داخل `MemoryMax=2000M`):** للتشغيل المستمر الخلفي ٢٤/٧ وتنزيل السلاسل عبر `mirath-audio` ومحاذاة النوافذ داخل cgroup آمن (`~٣١ دقيقة` لدرس ٢٧ دقيقة).

> **اقرأ أولاً:** `references/07-ops-and-guards.md` — قواعد المالك الحاكمة وضوابط العمليات. أنت **لا تبدأ** عملاً بمبادرة ذاتية منك، ولا تنشر، ولا ترفع؛ بل تعرض الترتيب والخيارات وتنتظر «ابدأ بـX».

## القاعدة الصفرية للوكيل: تحديد بيئة التنفيذ (`Mac` أم `VPS`؟) وعدم الخلط بينهما

1. **اسأل أو تحقّق قبل البدء:** إذا استدعى المالك المهارة ولم يحدّد صراحةً أين يريد التنفيذ (`الماك` أم `الخادم VPS`)، **اسأله أولاً سؤالاً مباشراً من سطر واحد:**
   *«هل تريد تنفيذ السلسلة على الماك (سرعة MPS القصوى) أم على الخادم VPS (تشغيل خلفي معزول)؟»*
2. **إيّاك أن تعامل الماك كالـVPS أو تعامل الـVPS كالماك:** بمجرد اختيار البيئة، يتغيّر سلوكك وإعدادات الموارد في **كل المراحل** جذرياً وفق الجدول الملزم أدناه:

| البُعد التشغيلي | بروفايل الماك (`--target mac` · Apple Silicon M1 Pro · 16GB) | بروفايل الخادم (`--target vps` · Linux 4 vCPU · 7.8GB بلا Swap) |
|---|---|---|
| **فلسفة الموارد** | **استغلال كامل للسرعة والتوازي** (GPU موحّد + ذاكرة مريحة؛ بلا تقييد `cgroup` ولا تقليم طبقات) | **حماية صارمة للبوابة من OOM** (عزل إلزامي بسقف `MemoryMax=2800M` ووحدة محاذاة واحدة في اللحظة) |
| **غلاف التشغيل الطويل** | `caffeinate -i <cmd>` (لمنع نوم الماك؛ **ممنوع** استدعاء `systemd-run` لأنه غير موجود على macOS) | `systemd-run --scope -p MemoryMax=2800M --unit=... --collect <cmd>` (**إلزامي** لكل مهمة ثقيلة) |
| **التفريغ (`agy_transcribe.py`)** | توازي كامل: `--workers 4 --chunk-minutes 12` | توازي محافظ: `--workers 2 --chunk-minutes 12` |
| **بوابة الجودة (`check_transcripts.py --llm`)** | تدقيق متوازٍ سريع: `--llm --llm-workers 4` | تدقيق محافظ: `--llm --llm-workers 2` |
| **الانبعاثات الصوتية (`extract_emissions.py`)** | `--device mps --dtype fp32 --batch 4 --window 30 --layers 0` (**٢٤ طبقة كاملة** + وضع `--series-dir` بتحميل النموذج مرة واحدة) | `--device cpu --engine torch --batch 1 --window 20 --layers 0` (أو `--seg-sec 300 --silence-compact 1` داخل سقف `2800M`) |
| **السرعة الفعلية المقيسة** | درس ٢٧د في **~٥٠ث** · سلسلة ١٠٫٧ ساعات (٩ دروس) في **~٢٠ دقيقة** (`RTF = 0.031`) | درس ٢٧د في **٢٠٫٨–٣١٫٧ دقيقة** (`RTF = 0.78–1.30`) |
| **مفسر بايثون وجذر العمل** | `/Users/macm1pro/venvs/ctc/bin/python` · `/Users/macm1pro/workspace` | `/root/venvs/ctc/bin/python` · `/root/workspace` |

## When to Use

- استقبال سلسلة صوتية جديدة (قائمة تشغيل يوتيوب / صف مانيجست) وتفريغها وفحصها ومحاذاتها بالكامل على الماك أو الخادم.
- فحص جودة التفريغات القائمة ببوابة الجودة الثلاثية (`check_transcripts.py --llm --align-dir ...`) لكشف البتر الصامت (انخفاض معدل الكلمات في الدقيقة `WPM`)، أو التحريفات الصوتية للمصطلحات، أو القوائم المعكوسة، أو ترويسات البيانات الوصفية غير المنطوقة.
- إكمال سلسلة ناقصة أو إعادة تفريغ المحاضرات الطويلة (`> 15 دقيقة`) مع التقطيع التلقائي عند السكتات والدمج عبر `agy_transcribe.py`.
- محاذاة سلسلة قائمة بالمسار النقي (Pure CTC v4.2): انبعاثات مرة واحدة (`extract_emissions.py`) ثم فيتربي بنافذة أفق متحركة (`ctc_pure_align.py`) ⇒ تغطية ١٠٠٪ بلا Whisper ولا كاش كلمات.

## القاعدة الذهبية في سطر

**حدّد البيئة أولاً (`mac` أو `vps`) ← التفريغ = `agy_transcribe.py` ← الفحص = `check_transcripts.py --sync-meta --llm` ← المحاذاة = `run_pure.sh --target mac|vps --series <dir>`.**

## الخريطة العامة (٥ مراحل)

| مرحلة | على الماك (`--target mac`) | على الخادم (`--target vps`) | الأداة الجوهرية | المرجع |
|---|---|---|---|---|
| ٠ الاستقبال والترتيب | محلي سريع | عبر `mirath-audio` / محلي | `new_series.py` (يحفظ `dur_s` ويكشف الترقيم المعكوس) | `01-intake-and-registry.md` |
| ١ التفريغ التبادلي | `--workers 4` (متوازٍ) | `--workers 2` (محافظ) | `agy_transcribe.py` (عزل الأدوات + تقطيع صامت `> 15د`) | `02-transcription-pluggable.md` |
| ٢ بوابة الجودة الثلاثية | `--llm-workers 4` | `--llm-workers 2` | `check_transcripts.py --sync-meta --llm` · `sanitize_preamble.py` | `02-…` §بوابة الجودة |
| ٣ المحاذاة الأساسية (v4.2) | `mps · batch=4 · layers=0` (~٢٠د للسلسلة) | `cpu cgroup 2800M · batch=1 · layers=0` | `run_pure.sh --target mac\|vps` (`extract_emissions.py` → `ctc_pure_align.py`) | `03-alignment-pure-ctc.md` |
| ٤ النشر والطبقات | بأمر المالك | بأمر المالك | `attach_align.py` · `copy_layers.py` · أوراق الروابط | `04-publish-and-layers.md` |

> البنية الكاملة للعتاد وأنماط التشغيل على الماك والخادم في `05-hardware-and-execution-profiles.md` و `07-ops-and-guards.md`.

---

## المرحلة ٠ — الاستقبال وضبط السلسلة (`new_series.py`)

```bash
python3 "$SKILL_DIR/scripts/new_series.py" \
    --slug bardouni-husaymi --row 1005 \
    --sheikh "محمد البردوني الحسيمي" --series "مقدمات السنوسي" \
    --playlist "PLUAcOYpvESsfJk6driIvfxJHDWq-NRtHz" \
    [--work-root "$SERIES_WORKSPACE"] [--order auto|title|playlist] [--fix-existing]
```

1. **حفظ المدد والأرقام الصريحة:** يكتب `<series_dir>/_meta.json` شاملاً `dur_s` (مدة كل فيديو بالثواني) و`title_ep` (رقم الدرس الصريح في العنوان) لتمكين بوابة الجودة من حساب معدل الكلمات في الدقيقة (`WPM`) آليًا.
2. **كشف القوائم المعكوسة تلقائيًا (`--order auto`):** إذا كانت القائمة مرفوعة بترتيب معكوس على يوتيوب (مثل قائمة «مقدمات السنوسي» حيث الموضع 1 هو «الدرس 09 والأخير» والموضع 9 هو «الدرس 01»)، يرتبها تصاعديًا حسب رقم الدرس الصريح، ومع `--fix-existing` يعيد ترقيم ملفات `.txt` و`.meta.json` القائمة بأمان.

---

## المرحلة ١ — التفريغ التبادلي المحصَّن (`agy_transcribe.py`)

```bash
python3 "$SKILL_DIR/scripts/agy_transcribe.py" <series_dir> \
    [--only 001,008] [--model gemini-3.8-flash-high] \
    [--max-single-minutes 15] [--chunk-minutes 12] [--workers 4] [--force] [--check-usage]
```

- **عزل بيئة `agy` وحصر القراءة في `view_file` (منع السقوط الصامت إلى Whisper):** يعمل كل نداء `agy` داخل مجلد مؤقت معزول (مع حل المسار الحقيقي `realpath` على macOS) **بدون** `--dangerously-skip-permissions`، مع تعليمة تقرأ `@lesson_audio.mp3` عبر `view_file` فقط وتمنع `run_command` و`whisper` والمقدمات اللاتينية، ثم يطهّر المخرج بـ`strip_preamble_and_header()` قبل الحفظ.
- **التقطيع الصامت الذكي والتفريغ المتوازي (`--chunk-minutes 12 --workers 4`):** تُقسَّم المحاضرات (`> 15 دقيقة`) تلقائيًا عند منتصف أقرب سكتة طبيعية (`ffmpeg silencedetect=noise=-32dB:d=0.35` ضمن `±25ث` في `<1ث`) لمنع بتر الكلمات عند حدود القطع، وتُفرَّغ بالتوازي مع إزاحة بدء متدرجة (`1.5ث` بين العمال) ثم تُدمج.

---

## المرحلة ٢ — بوابة الجودة المزدوجة والتنظيف (`check_transcripts.py --llm`)

```bash
# ١. تطهير أي ترويسات وصفية أو مقدمات لاتينية (مع أرشفة الأصل في _raw_preamble_backup/):
python3 "$SKILL_DIR/scripts/sanitize_preamble.py" <series_dir>

# ٢. تشغيل بوابة الجودة المزدوجة (الحتمية + التدقيق الدلالي عبر LLM):
python3 "$SKILL_DIR/scripts/check_transcripts.py" <series_dir> \
    --llm [--playlist-json playlist.json] [--report gate_report.json]
```

1. **الفحوص الحتمية (Deterministic):**
   - `LOW_WPM_TRUNCATED`: يكشف التفريغات المبتورة بمقارنة عدد الكلمات بمدة الصوت (`WPM < 45 ك/د`؛ أو `< 1200 كلمة` عند غياب المدة).
   - `METADATA_HEADER`: يكشف ترويسات `الشيخ: / السلسلة: / الفيديو:` غير المنطوقة في أول الملف (التي كانت تُفسد محاذاة أول ٦٠ ثانية).
   - `LATIN_PREAMBLE`: يكشف أي تسرب إنجليزي/لاتيني في المطلع.
   - `ABRUPT_ENDING`: يكشف انقطاع النص وسط جملة بلا ترقيم ختامي أو عبارة ختام.
   - `NUMBERING_MISMATCH`: يكشف تعارض رقم الملف `NNN` مع الرقم الصريح في العنوان (`الدرس NN`).
   - `REPETITION_LOOP` و `META_MISMATCH` و `EMPTY`/`SHORT`.
2. **الفحص الدلالي بالذكاء الاصطناعي (`--llm`):**
   - يراجع مقتطفات البداية والوسط والنهاية ومعدل الكلمات وعنوان الدرس عبر `agy` ليكتشف التحريفات الصوتية للمصطلحات العلمية والعقدية (`LLM_ASR_CORRUPTION` مثل `الجال البسط` بدل `الجهل البسيط`، `أئمة السُّنَّاه` بدل `أئمة السنة`)، والبتر الدلالي (`LLM_SEMANTIC_TRUNCATION`)، والتلخيص (`LLM_HALLUCINATION_OR_SUMMARY`).

---

## المرحلة ٣ — المحاذاة الأساسية: المسار النقي الموحد v4.2 (`run_pure.sh`)

```bash
# أ) معالجة سلسلة كاملة دفعةً واحدة (تحميل النموذج مرة واحدة + فك الصوت في الذاكرة بلا ملفات .wav):
PURE_OUT=/path/to/out bash "$SKILL_DIR/scripts/run_pure.sh" --target mac --series /path/to/series_dir

# ب) معالجة درس مفرد على الماك (Apple Silicon MPS GPU — ~50 ثانية لدرس 27 دقيقة):
PURE_WORKDIR=/path/to/work AUDIO=/path/to/001.mp3 TXT=/path/to/001.txt \
    bash "$SKILL_DIR/scripts/run_pure.sh" --target mac 001

# ج) معالجة على الخادم (Linux VPS CPU داخل سقف ذاكرة 2000M):
systemd-run --scope -p MemoryMax=${MEMORY_GUARD_MB:-2000M} --unit=pure001 --collect \
    bash "$SKILL_DIR/scripts/run_pure.sh" --target vps 001
```

### المزايا الهندسية للمسار النقي الموحد v4.2:
1. **فكّ الصوت المباشر في الذاكرة (`read_audio_16k`) + وضع السلسلة الدفعي (`--series-dir`):** يقرأ `extract_emissions.py` ملفات `.mp3`/`.m4a` مباشرةً في الذاكرة عبر أنبوب `ffmpeg -f f32le` في `<1 ثانية` (توفير ١٠٠٪ من ملفات `.wav` المؤقتة التي كانت تستهلك `~2GB` للسلسلة)، ويحمّل نموذج `mms-300m-1130-forced-aligner` **مرة واحدة فقط** للسلسلة كاملة مع إعادة استخدام `.em.npy` تلقائيًا (`--skip-existing`) عند تحديث النصوص.
2. **شريحة فيتربي متحركة مع تسليم المراسي الصلبة وعقوبة `<star>` (`ctc_pure_align.py` v4.2):** نافذة `120ث` مقطوعة عند أقرب فاصل صمت طبيعي (`argmax == blank` لمدة `≥ 0.3ث`) مع عقوبة لوغاريتمية `--star-pen -0.9` لعمود `<star>` وتسليم محكوم بمرساة صلبة (`--solid-handoff 1`: طول مُطبّع `≥ 4` حروف وثقة `≥ -1.0` وتقدّم زمني معقول).
3. **تخطي الرموز الصامتة الخالصة في فيتربي:** الرموز الصامتة المنفردة (`*`، `ۖ`، `ۚ`) تُتخطى أثناء حساب فيتربي عبر خريطة فهارس صريحة بدل تحويلها إلى حرف `'ا'` يسرق إطارات صوتية، ثم تُربط بحدّ الكلمة المنطوقة السابقة.
4. **استيفاء بفترات متناسبة وعتبة `--min-score -3.0` وكشف البتر الصوتي (`audio_span_pct`):** تمنح الكلمات المستوفاة فترات `(start, end)` متناسبة غير صفرية، وترفع المحاذاة الصوتية المباشرة للمنطوق إلى **٩٧٫٩٪–٩٩٫٩٪** مع وسيط تطابق **٠٫١٢–٠٫١٤ ثانية** مقابل مراسي `v1` النظيفة (`vs_v1_clean`).

---

## المرحلة ٤ — النشر والطبقات (بأمر المالك فقط)

- `attach_align.py <sheikh/row> [--align-dir DIR]` ينشر `<NNN>_<VID>.align.json` بجانب النص ويحدّث `meta.align`.
- `copy_layers.py` ينسخ طبقات التلخيص والأسئلة والمحاذاة **بالمطابقة القاطعة للهوية فقط** (YouTube ID أو `row-key` + رقم الدرس).
- **حظر النشر الذاتي:** لا نشر تلقائي ولا دفع إلى مستودعات خارجية بلا أمر صريح من المالك.

---

## فهرس المراجع التفصيلية

- `01-intake-and-registry.md` — المخازن، مخطط `SERIES_CONFIG`، `new_series.py`، وكشف القوائم المعكوسة.
- `02-transcription-pluggable.md` — طبقة التفريغ التبادلية (`agy_transcribe.py`) وبوابة الجودة المزدوجة (`check_transcripts.py --llm`).
- `03-alignment-pure-ctc.md` — المسار النقي v4.2 (`extract_emissions.py` + `ctc_pure_align.py`) على الماك (`mps`) والخادم (`cpu`).
- `03-alignment-primary-v3.md` — المسار التاريخي v3 بالمراسي والمعايرة (للتحقق المتقاطع فقط).
- `03-alignment-legacy-whisper.md` — المسار التاريخي الأول (Whisper DTW).
- `04-publish-and-layers.md` — طبقات المعرفة، مخطط `align.json`، وأوراق الروابط.
- `05-hardware-and-execution-profiles.md` — بروفايلات التشغيل على الماك (`--target mac`) والخادم (`--target vps`).
- `06-pitfalls-catalogue.md` — كتالوج الأخطاء الميدانية (١ إلى ٥٥: العَرَض ← السبب الجذري ← الإصلاح).
- `07-ops-and-guards.md` — قواعد المالك الحاكمة ومنظومة الحرّاس.
- `08-measured-baselines.md` — خطوط الأساس المقيسة ونتائج التجارب قبل/بعد التحسين.
- `09-v2-upgrade-spec.md` — المواصفة المعمارية التاريخية لترقية المحرك.
- `10-emissions-engine-onnx.md` — مقاييس محرك الانبعاثات (`MPS GPU` مقابل `CPU FP32` مقابل `ONNX UINT8`).

