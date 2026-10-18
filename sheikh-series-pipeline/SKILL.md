---
name: sheikh-series-pipeline
description: "Use when processing an audio series on Mac (Apple Silicon MPS), Linux VPS, or v5.0 Hybrid VPS+Mac Fleet: intake, smallest-first queue, pluggable transcription (YouTube + Archive.org direct_url) with live quota guard and long-lecture chunking, dual-layer quality gate (deterministic + LLM semantic audit), Opus 12kbps VoIP bridge, pure CTC v4.2 / v5.0 fp16 silence-compacted alignment, and publish."
version: 5.0.0
author: Mohamed Boumaraf, Hermes Agent
license: MIT
platforms: [linux, macos]
metadata:
  hermes:
    tags: [sheikhs, series, transcription, pluggable, gemini, llm-qa, alignment, pure-ctc, mps, fp16, opus-bridge, silence-compaction, onnx, ctc, mms, vps, macos, arabic, irth, hawshat, v5]
    related_skills: [agy-transcription, youtube-audio-download, agy-worker-orchestration, antigravity-cli, mirath-content-platform]
---

# خطّ سلاسل المشايخ v5.0 — من التسجيل إلى محاذاة ١٠٠٪ (دعم الماك MPS والخادم VPS والمعمارية الهجينة v5.0)

محرك عام متكامل لاستقبال أي **سلسلة صوتية**، وتسليم: **نصّ مفرَّغ دقيق ومفحوص دلاليًا** عبر طبقة تفريغ تبادلية وبوابة جودة مزدوجة (حتمية + تدقيق LLM) + **محاذاة زمنية لكل كلمة بنسبة تغطية ١٠٠٪** عبر المسار النقي v4.2 / v5.0 (`align.json`) + الطبقات المعرفية (تلخيص/أسئلة) + النشر في المخزن المعتمد.

يدعم الخط **اختيار بيئة التنفيذ (`--target mac | vps | auto` أو الوضع الهجين المستمر `v5.0 Hybrid VPS + Mac MPS`)** عند استدعاء المهارة:
- **الوضع الهجين الموزّع (`v5.0 Hybrid Fleet` · تفريغ `hermes-vps` + جسر `Opus 12kbps VoIP` + محاذاة `Mac M1 Pro MPS fp16`):** السيرفر يفرّغ السلاسل تصاعديًا من الأصغر للأكبر (`transcribe_selected_smallest_first.py` · `333` سلسلة · `7,383` درساً) عبر `agy_transcribe.py` مع دعم `Archive.org` (`direct_url`) وحارس الكوتة الحي (`_is_quota_safe_for_background`)، ويحوّل الصوت فورًا قبل حذف `.mp3` إلى `.opus` (`16kHz mono, 12kbps VoIP, ~3 MB/hour`) في `/root/workspace/align-bridge/ready/`، بينما يسحبه الماك في الخلفية عبر خدمة `LaunchAgent` (`mac_align_fleet.py` مع `caffeinate -i`) ويحاذيه بدقة `fp16` مع طيّ الصمت (`plan_silence` + `compact_wave` + `unpad_emissions`) بسرعة **٣٨× إلى ٤٩× من الوقت الحقيقي** ويعيد `.align.json` للسيرفر مع مزامنة الكوتة الحية كل دقيقتين (`quota_sync_worker`). (انظر `references/11-hybrid-vps-mac-mps-v5.md`).
- **الماك المستقل (`--target mac` · Apple Silicon M1 Pro MPS GPU):** يُسرّع المرحلة الصوتية بـ **٣٩× إلى ٥٣×** مقارنةً بمعالج الخادم (درس ٢٧ دقيقة ينتهي من الصفر في **~٥٠ ثانية** بـ`fp32` أو **~٣٤ ثانية** بـ`fp16`، ودرس ٤٤ دقيقة في **~٩٠ ثانية**).
- **الخادم المستقل (`--target vps` · Linux VPS CPU داخل `MemoryMax=2000M`):** للتشغيل المستمر الخلفي ٢٤/٧ وتنزيل السلاسل عبر `mirath-audio` ومحاذاة النوافذ داخل cgroup آمن (`~٣١ دقيقة` لدرس ٢٧ دقيقة).

> **اقرأ أولاً:** `references/07-ops-and-guards.md` و`references/11-hybrid-vps-mac-mps-v5.md` — قواعد المالك الحاكمة وضوابط العمليات والمعمارية الهجينة. أنت **لا تبدأ** عملاً بمبادرة ذاتية منك، ولا تنشر، ولا ترفع؛ بل تعرض الترتيب والخيارات وتنتظر «ابدأ بـX».

## القاعدة الصفرية للوكيل: تحديد بيئة التنفيذ (`Mac` أم `VPS` أم `Hybrid v5`؟) وعدم الخلط بينهما

1. **اسأل أو تحقّق قبل البدء:** إذا استدعى المالك المهارة ولم يحدّد صراحةً أين يريد التنفيذ (`الماك` أم `الخادم VPS` أم `الخط الهجين v5`)، **اسأله أولاً سؤالاً مباشراً من سطر واحد:**
   *«هل تريد تنفيذ السلسلة على الماك (سرعة MPS القصوى)، أم على الخادم VPS (تشغيل خلفي معزول)، أم عبر الخط الهجين v5 (تفريغ VPS + محاذاة Mac MPS)؟»*
2. **إيّاك أن تعامل الماك كالـVPS أو تعامل الـVPS كالماك:** بمجرد اختيار البيئة، يتغيّر سلوكك وإعدادات الموارد في **كل المراحل** جذرياً وفق الجدول الملزم أدناه:

| البُعد التشغيلي | بروفايل الماك (`--target mac` · Apple Silicon M1 Pro · 16GB) | بروفايل الخادم (`--target vps` · Linux 4 vCPU · 7.8GB بلا Swap) | البروفايل الهجين (`v5.0 Hybrid` · VPS + Opus Bridge + Mac MPS) |
|---|---|---|---|
| **فلسفة الموارد** | **استغلال كامل للسرعة والتوازي** (GPU موحّد + ذاكرة مريحة؛ بلا تقييد `cgroup` ولا تقليم طبقات) | **حماية صارمة للبوابة من OOM** (عزل إلزامي بسقف `MemoryMax=2800M` ووحدة محاذاة واحدة في اللحظة) | **تخصّص مزدوج ٢٤/٧:** التفريغ على VPS مع حارس الكوتة والذاكرة + المحاذاة على Mac MPS بدقة `fp16` وطيّ الصمت وتخفيف الحمل الحراري |
| **غلاف التشغيل الطويل** | `caffeinate -i <cmd>` (لمنع نوم الماك؛ **ممنوع** استدعاء `systemd-run` لأنه غير موجود على macOS) | `systemd-run --scope -p MemoryMax=2800M --unit=... --collect <cmd>` (**إلزامي** لكل مهمة ثقيلة) | VPS: `transcribe_selected_smallest_first.py` + `vps_align_feeder.py` · Mac: `LaunchAgent` (`com.mohamed.mac-align-fleet.plist` مع `caffeinate -i`) |
| **التفريغ (`agy_transcribe.py`)** | توازي كامل: `--workers 4 --chunk-minutes 12` | توازي محافظ: `--workers 2 --chunk-minutes 12` | على VPS: `SERIES_WORKERS=4 × CHUNK_WORKERS=4` (من الأصغر للأكبر) + دعم `Archive.org` (`direct_url`) + حارس الكوتة الحي (`>=15%` 5h و`>=25%` أسبوعي) |
| **بوابة الجودة (`check_transcripts.py --llm`)** | تدقيق متوازٍ سريع: `--llm --llm-workers 4` | تدقيق محافظ: `--llm --llm-workers 2` | تطهير فوري بـ`strip_preamble_and_header` أثناء التفريغ وقبل المحاذاة + بوابة الجودة الثلاثية |
| **الانبعاثات الصوتية (`extract_emissions.py`)** | `--device mps --dtype fp32 --batch 4 --window 30 --layers 0` (**٢٤ طبقة كاملة** + وضع `--series-dir` بتحميل النموذج مرة واحدة) | `--device cpu --engine torch --batch 1 --window 20 --layers 0` (أو `--seg-sec 300 --silence-compact 1` داخل سقف `2800M`) | جسر `Opus 12kbps VoIP (~3MB/h)` ← الماك `mps · fp16 · batch=3 · cooldown=3.5s` مع طيّ الصمت (`plan_silence` + `compact_wave` + `unpad_emissions`) |
| **السرعة الفعلية المقيسة** | درس ٢٧د في **~٥٠ث** · سلسلة ١٠٫٧ ساعات (٩ دروس) في **~٢٠ دقيقة** (`RTF = 0.031`) | درس ٢٧د في **٢٠٫٨–٣١٫٧ دقيقة** (`RTF = 0.78–1.30`) | نقل الشبكة **~٠٫٥ث/درس** · المحاذاة الكاملة على الماك بسرعة **٣٨×–٤٩× من الوقت الحقيقي** (`RTF ≈ 0.020–0.026`) |
| **مفسر بايثون وجذر العمل** | `/Users/macm1pro/venvs/ctc/bin/python` · `/Users/macm1pro/workspace` | `/root/venvs/ctc/bin/python` · `/root/workspace` | VPS: `/root/workspace/ytb` + `/root/workspace/align-bridge/ready` · Mac: `/tmp/mac_align_spool` |

## When to Use

- استقبال سلسلة صوتية جديدة (قائمة تشغيل يوتيوب / أرشيف الإنترنت `Archive.org` / صف مانيجست) وتفريغها وفحصها ومحاذاتها بالكامل على الماك أو الخادم أو عبر الأسطول الهجين `v5.0`.
- تشغيل طابور التفريغ الشامل مرتّباً من السلاسل الأصغر إلى الأكبر (`transcribe_selected_smallest_first.py` — `333` سلسلة، `7,383` درساً) مع حماية الكوتة الحية والذاكرة.
- فحص جودة التفريغات القائمة ببوابة الجودة الثلاثية (`check_transcripts.py --llm --align-dir ...`) لكشف البتر الصامت (انخفاض معدل الكلمات في الدقيقة `WPM`)، أو التحريفات الصوتية للمصطلحات، أو القوائم المعكوسة، أو ترويسات البيانات الوصفية غير المنطوقة.
- إكمال سلسلة ناقصة أو إعادة تفريغ المحاضرات الطويلة (`> 15 دقيقة`) مع التقطيع التلقائي عند السكتات والدمج عبر `agy_transcribe.py`.
- محاذاة سلسلة قائمة بالمسار النقي (Pure CTC v4.2 / v5.0): انبعاثات مرة واحدة (`extract_emissions.py` أو `mac_align_fleet.py` مع طيّ الصمت `fp16`) ثم فيتربي بنافذة أفق متحركة (`ctc_pure_align.py`) ⇒ تغطية ١٠٠٪ بلا Whisper ولا كاش كلمات.

## القاعدة الذهبية في سطر

**حدّد البيئة أولاً (`mac` أو `vps` أو `hybrid v5`) ← التفريغ = `agy_transcribe.py` ← الفحص = `check_transcripts.py --sync-meta --llm` ← المحاذاة = `run_pure.sh --target mac|vps --series <dir>` (أو تلقائياً عبر جسر `Opus 12kbps` إلى `mac_align_fleet.py`).**

## الخريطة العامة (٥ مراحل)

| مرحلة | على الماك (`--target mac`) | على الخادم (`--target vps`) | في المعمارية الهجينة (`v5.0 Hybrid`) | الأداة الجوهرية | المرجع |
|---|---|---|---|---|---|
| ٠ الاستقبال والترتيب | محلي سريع | عبر `mirath-audio` / محلي | فهرسة وترتيب تصاعدي من الأصغر للأكبر (`333` سلسلة) | `new_series.py` · `transcribe_selected_smallest_first.py` | `01-intake-and-registry.md` · `11-…` |
| ١ التفريغ التبادلي | `--workers 4` (متوازٍ) | `--workers 2` (محافظ) | على VPS (`gemini-3.8-flash-high` + `direct_url` + حارس الكوتة الحي + تحويل `.opus` فوري) | `agy_transcribe.py` | `02-transcription-pluggable.md` · `11-…` |
| ٢ بوابة الجودة الثلاثية | `--llm-workers 4` | `--llm-workers 2` | تطهير مزدوج في `agy_transcribe.py` و`mac_align_fleet.py` + فحص حتمي ودلالي | `check_transcripts.py --sync-meta --llm` · `sanitize_preamble.py` | `02-…` §بوابة الجودة |
| ٣ المحاذاة الأساسية (v4.2 / v5.0) | `mps · batch=4 · layers=0` (~٢٠د للسلسلة) | `cpu cgroup 2800M · batch=1 · layers=0` | جسر `Opus 12kbps VoIP` ← `mac_align_fleet.py` (`mps fp16` + طي الصمت `38x–49x`) | `run_pure.sh` · `vps_align_feeder.py` · `mac_align_fleet.py` | `03-alignment-pure-ctc.md` · `11-…` |
| ٤ النشر والطبقات | بأمر المالك | بأمر المالك | رفع تلقائي لـ`.align.json` وتحديث `.meta.json` على VPS؛ والنشر الخارجي بأمر المالك | `attach_align.py` · `copy_layers.py` · `test_pipeline_v5_gates.py` | `04-publish-and-layers.md` · `11-…` |

> البنية الكاملة للعتاد وأنماط التشغيل على الماك والخادم والخط الهجين في `05-hardware-and-execution-profiles.md` و `07-ops-and-guards.md` و `11-hybrid-vps-mac-mps-v5.md`.

---

## المرحلة ٠ — الاستقبال وضبط السلسلة (`new_series.py` و `transcribe_selected_smallest_first.py`)

```bash
python3 "$SKILL_DIR/scripts/new_series.py" \
    --slug bardouni-husaymi --row 1005 \
    --sheikh "محمد البردوني الحسيمي" --series "مقدمات السنوسي" \
    --playlist "PLUAcOYpvESsfJk6driIvfxJHDWq-NRtHz" \
    [--work-root "$SERIES_WORKSPACE"] [--order auto|title|playlist] [--fix-existing]
```

1. **حفظ المدد والأرقام الصريحة:** يكتب `<series_dir>/_meta.json` شاملاً `dur_s` (مدة كل فيديو بالثواني) و`title_ep` (رقم الدرس الصريح في العنوان) و`url` (الرابط المباشر لـ`Archive.org` أو يوتيوب) لتمكين بوابة الجودة من حساب معدل الكلمات في الدقيقة (`WPM`) آليًا.
2. **كشف القوائم المعكوسة تلقائيًا (`--order auto`):** إذا كانت القائمة مرفوعة بترتيب معكوس على يوتيوب (مثل قائمة «مقدمات السنوسي» حيث الموضع 1 هو «الدرس 09 والأخير» والموضع 9 هو «الدرس 01»)، يرتبها تصاعديًا حسب رقم الدرس الصريح، ومع `--fix-existing` يعيد ترقيم ملفات `.txt` و`.meta.json` القائمة بأمان.
3. **طابور السلاسل المرتّب من الأصغر إلى الأكبر (`transcribe_selected_smallest_first.py`):** على السيرفر، يرتب الـ`333` سلسلة (`7,383` درساً) تصاعدياً حسب `(rem_count, total_count, rem_dur)` مع حارس ذاكرة (`MemAvailable >= 1600 MB`) لتخريج السلاسل القصيرة فوراً إلى جسر المحاذاة.

---

## المرحلة ١ — التفريغ التبادلي المحصَّن (`agy_transcribe.py`)

```bash
python3 "$SKILL_DIR/scripts/agy_transcribe.py" <series_dir> \
    [--only 001,008] [--model gemini-3.8-flash-high] \
    [--max-single-minutes 15] [--chunk-minutes 12] [--workers 4] [--force] [--check-usage]
```

- **دعم التنزيل المزدوج (YouTube + `Archive.org` `direct_url`):** تفحص `download_lesson_audio()` حقل `direct_url`؛ فإذا كان رابطاً مباشراً من `archive.org/` أو ملفاً صوتياً مباشراً، تنزّله عبر `curl -fL` وتتحقق من سلامة مدته عبر `is_valid_audio_file()`، وإلا تنزّله عبر `mirath-audio` أو `yt-dlp`.
- **حارس الكوتة الحي (`_is_quota_safe_for_background`):** يقرأ `/root/workspace/ytb-build/live_quota.json` (المزامَن من الماك كل دقيقتين) ويوقف عمال الخلفية مؤقتاً إذا هبطت كوتة الـ5 ساعات دون **`15%`** (حمايةً لـ`10%` للوكيل الرئيسي) أو إذا هبطت الكوتة الأسبوعية إلى **`<= 25%`** وكان المتبقي على التجديد أكثر من **`12` ساعة**.
- **عزل بيئة `agy` وحصر القراءة في `view_file` (منع السقوط الصامت إلى Whisper):** يعمل كل نداء `agy` داخل مجلد مؤقت معزول (مع حل المسار الحقيقي `realpath` على macOS)، مع تعليمة تقرأ `@lesson_audio.mp3` عبر `view_file` فقط وتمنع `run_command` و`whisper` والمقدمات اللاتينية، ثم يطهّر المخرج بـ`strip_preamble_and_header()` وينظّف قاعدة بيانات جلسة `agy` المؤقتة (`_cleanup_agy_conv_db`) قبل الحفظ.
- **التقطيع الصامت الذكي والتفريغ المتوازي (`--chunk-minutes 12 --workers 4`):** تُقسَّم المحاضرات (`> 15 دقيقة`) تلقائيًا وتُفرَّغ بالتوازي ثم تُدمج، مع إنقاذ تلقائي بتقسيم أي مقطع متعثر إلى نصفين.
- **التحويل الفوري إلى جسر المحاذاة (`Opus 12kbps VoIP Bridge`):** على السيرفر، وفور كتابة `.txt` وقبل حذف `.mp3` المؤقت، يحوّل `agy_transcribe.py` الصوت إلى `/root/workspace/align-bridge/ready/<sheikh>__<series>__<stem>.opus` (`16kHz mono, 12kbps VoIP, ~3 MB/hour`) + `.job.json` ليُلتقط فوراً من الماك.

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

## المرحلة ٣ — المحاذاة الأساسية: المسار النقي الموحد v4.2 (`run_pure.sh`) والأسطول الهجين v5.0 (`mac_align_fleet.py`)

```bash
# أ) الوضع الهجين المستمر v5.0 (تغذية الجسر على VPS + أسطول المحاذاة على الماك بـ fp16 وطي الصمت):
#    على السيرفر (لتغذية الدروس القديمة غير المحاذاة إلى جانب التحويل الفوري في agy_transcribe.py):
python3 "$SKILL_DIR/scripts/vps_align_feeder.py"
#    على الماك (يعمل تلقائياً كـ LaunchAgent تحت com.mohamed.mac-align-fleet.plist مع caffeinate -i):
/usr/bin/caffeinate -i /Users/macm1pro/venvs/ctc/bin/python "$SKILL_DIR/scripts/mac_align_fleet.py"

# ب) معالجة سلسلة كاملة محلياً دفعةً واحدة (تحميل النموذج مرة واحدة + فك الصوت في الذاكرة بلا ملفات .wav):
PURE_OUT=/path/to/out bash "$SKILL_DIR/scripts/run_pure.sh" --target mac --series /path/to/series_dir

# ج) معالجة درس مفرد على الماك (Apple Silicon MPS GPU — ~50 ثانية لدرس 27 دقيقة):
PURE_WORKDIR=/path/to/work AUDIO=/path/to/001.mp3 TXT=/path/to/001.txt \
    bash "$SKILL_DIR/scripts/run_pure.sh" --target mac 001

# د) معالجة على الخادم (Linux VPS CPU داخل سقف ذاكرة 2000M):
systemd-run --scope -p MemoryMax=${MEMORY_GUARD_MB:-2000M} --unit=pure001 --collect \
    bash "$SKILL_DIR/scripts/run_pure.sh" --target vps 001
```

### المزايا الهندسية للمسار النقي الموحد v4.2 والأسطول الهجين v5.0:
1. **فكّ الصوت المباشر في الذاكرة (`read_audio_16k`) + وضع السلسلة الدفعي (`--series-dir`):** يقرأ `extract_emissions.py` ملفات `.mp3`/`.m4a`/`.opus` مباشرةً في الذاكرة عبر أنبوب `ffmpeg -f f32le` في `<1 ثانية` (توفير ١٠٠٪ من ملفات `.wav` المؤقتة التي كانت تستهلك `~2GB` للسلسلة)، ويحمّل نموذج `mms-300m-1130-forced-aligner` **مرة واحدة فقط** للسلسلة كاملة مع إعادة استخدام `.em.npy` تلقائيًا (`--skip-existing`) عند تحديث النصوص.
2. **طيّ الصمت وإعادة النفخ بدقة `fp16` على الماك (`plan_silence` + `compact_wave` + `unpad_emissions`):** في `mac_align_fleet.py` (وعند تفعيل `--silence-compact 1` في `extract_emissions.py`)، تُطوى فجوات الصمت (`>= 0.5s` مع إبقاء هامش `0.15s`) قبل تمرير الموجة إلى `mps` بدقة `fp16` (`MAC_ALIGN_BATCH_SIZE=3`)، ثم تُعاد المصفوفة إلى طولها الأصلي الكامل `T_orig` عبر `unpad_emissions()` بدقة `20ms`، مما يرفع السرعة إلى **٣٨×–٤٩× من الوقت الحقيقي** مع تخفيف الحمل الحراري (`torch.mps.empty_cache()`, `gc.collect()`, واستراحة `3.5s` بين الدروس).
3. **شريحة فيتربي متحركة مع تسليم المراسي الصلبة وعقوبة `<star>` (`ctc_pure_align.py` v4.2):** نافذة `120ث` مقطوعة عند أقرب فاصل صمت طبيعي (`argmax == blank` لمدة `≥ 0.3ث`) مع عقوبة لوغاريتمية `--star-pen -0.9` لعمود `<star>` وتسليم محكوم بمرساة صلبة (`--solid-handoff 1`: طول مُطبّع `≥ 4` حروف وثقة `≥ -1.0` وتقدّم زمني معقول).
4. **تخطي الرموز الصامتة الخالصة في فيتربي:** الرموز الصامتة المنفردة (`*`، `ۖ`، `ۚ`) تُتخطى أثناء حساب فيتربي عبر خريطة فهارس صريحة بدل تحويلها إلى حرف `'ا'` يسرق إطارات صوتية، ثم تُربط بحدّ الكلمة المنطوقة السابقة.
5. **استيفاء بفترات متناسبة وعتبة `--min-score -3.0` وكشف البتر الصوتي (`audio_span_pct`):** تمنح الكلمات المستوفاة فترات `(start, end)` متناسبة غير صفرية، وترفع المحاذاة الصوتية المباشرة للمنطوق إلى **٩٧٫٩٪–٩٩٫٩٪** مع وسيط تطابق **٠٫١٢–٠٫١٤ ثانية** مقابل مراسي `v1` النظيفة (`vs_v1_clean`).
6. **بوابة التحقيق والإصلاح الجذري الإلزامية عند هبوط المحاذاة دون ٩٥٪ (`< 95.0% Alignment Investigation & Root-Cause Auto-Fix Rule` — قاعدة حاكمة صارمة):**
   - **معيار القبول الصارم:** يجب أن تحقق المحاذاة المباشرة للمنطوق (`spoken_align_coverage`) نسبة **`>= 95.0%`** (والوسيط الطبيعي على الماك هو **`98.0% – 99.8%`**).
   - **فتح تحقيق فوري تلقائي:** أي درس تهبط فيه نسبة المحاذاة المباشرة (`spoken_align_coverage` / `تغطية`) عن **`95.0%`** يُعَدّ حادثة جودة حرجة تستوجب فتح تحقيق فوري في السبب الجذري وعدم الاكتفاء بقبول النتيجة أو تبريرها:
     1. فحص ما إذا كان الهبوط ناتجاً عن **طيّ الصمت العدواني (`plan_silence` / `rel_db`)** الذي يمسح المقاطع الصوتية الخافتة ويحولها إلى `blank`، وإعادة استخراج انبعاثات الدرس **بدون طيّ صمت (`silence_compact=0`) أو بعتبة محافظة** ثم إعادة محاذاته.
     2. فحص ما إذا كان الهبوط ناتجاً عن **انحراف تقدير الكلمات (`cum_ev` / `forced progression`)** في بداية أو وسط التسجيل (مثل ضجيج ميكروفون أو مقدمة صامتة قبل كلام الشيخ)، وتصحيح منطق الشريحة في `ctc_pure_align.py` بحيث لا يقفز مؤشر الكلمات `wc` فوق نص لم يُنطق بعد.
     3. فحص ما إذا كان الهبوط ناتجاً عن **علة في النص المفرغ (`.txt`)** (تكرار مقاطع، ديباجة غير منطوقة، أو نقص/زيادة في الدمج بين المقاطع `chunks`)، وإصلاح النص ثم إعادة المحاذاة حتى تتجاوز التغطية **`95.0%`**.

---

## المرحلة ٤ — النشر والطبقات وبوابة الفحص الحتمية (بأمر المالك فقط)

- `attach_align.py <sheikh/row> [--align-dir DIR]` ينشر `<NNN>_<VID>.align.json` بجانب النص ويحدّث `meta.align` (وفي الوضع الهجين `v5.0` يتولى `upload_and_finalize()` في `mac_align_fleet.py` رفع `.align.json` وتحديث `.meta.json` وتنظيف الجسر تلقائياً على `hermes-vps`).
- `copy_layers.py` ينسخ طبقات التلخيص والأسئلة والمحاذاة **بالمطابقة القاطعة للهوية فقط** (YouTube ID أو `row-key` + رقم الدرس).
- `test_pipeline_v5_gates.py` يفحص حتمياً سلامة مكونات `v5.0` (شجرة AST، رياضيات طيّ الصمت وإعادة النفخ `T_orig`، تطهير المقدمات اللاتينية، حارس الكوتة الحي، ومخطط `.align.json`).
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
- `11-hybrid-vps-mac-mps-v5.md` — المعمارية الهجينة `v5.0` (تفريغ `hermes-vps` + دعم `Archive.org` + حارس الكوتة الحي + جسر `Opus 12kbps VoIP` + محاذاة `Mac Apple Silicon MPS fp16` مع طيّ الصمت وتخفيف الحمل الحراري).
