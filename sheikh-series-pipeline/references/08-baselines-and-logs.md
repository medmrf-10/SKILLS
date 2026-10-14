# ٠٨ — خطوط الأساس المقيسة ومن أين تُقاس

> كل رقم هنا **له تاريخ**. لا تنقله إلى تقرير بلا إعادة قياس بالأمر المكتوب بجانبه. الأوامر تفترض `W=/root/workspace`.

## التفريغ (قياس 2026-10-15 00:31)

- `ytb/sharawi`: **١٥٨ صفًا** فيها ملفات · **٦٥٨ تفريغًا صالحًا** من ٦٥٩ خامًا.
- البقرة `515` = **١١١/١١١** ✔ · ص `524` = ١٣/١٣ ✔ · ق `537` = ٦/٦ ✔ · القمر `482` = ٣/٣ ✔.
- قوائم الشعراوي المعلنة: **١٥٧ قائمة · ٥,٤٨٩ درساً**؛ والحدّ الممتحنة ٦٠.
- أمر القياس:

```bash
python3 - <<'PY'
import glob,os
ok=lambda p: os.path.getsize(p)>=1200 and b'blocked by Gemini' not in open(p,'rb').read()
fs=[f for f in glob.glob('/root/workspace/ytb/sharawi/*/*.txt') if ok(f)]
print('صالح:', len(fs), '| صفوف:', len({os.path.dirname(f) for f in fs}))
PY
```

## المخزون العام (COVERAGE.md — 2026-10-13T12:23)

- ٩٩٩ سلسلة · ٨٢٤ مرشّحة للتفريغ · ٢٠ شيخاً موحّداً · ١٦٩ سلسلة موحّدة · تغطية المانيجست ١١٠/٩٩٩.
- لكل شيخ (سلسلة/درس/نسبة): `sharawi` ١٥٧ سلسلة و٥٤٨٩ درساً؛ `bouti` ٨٠/٣٩٧٤/٣٣٪؛ `habib-omar-ibn-hafiz` ١٨٣/١١٧٠٨/٤٪؛
  `ali-gomaa` ١٧٩/١٧٠٣٢/٢٪؛ `mouloud-sariri` ٨٥/٥٢٩٦/٦٪؛ `adham-alasimi` ٥٩/٣٤٠٤/٢٤٪؛ `habib-ali-aljifri` ٦٦/١٤٢٩/٤٣٪.
- أعلى ثمانية بالتفريغات على القرص (registry.md): `bouti` ١١٢٩ · `ibnhafiz` ٥٣٨ · `alasimi` ٤٧٢ · `aljifri` ٤٥١ · `alsayed` ٢٩٦ · `bardouni` ٢٨٠ · `alamri` ٢٣٦ · `ali-gomaa` ٢٢٩.

## المحاذاة (قياس 2026-10-15 00:31)

- `ytb/**/*.align.json` = **١٠** منشورة · مرشّحون في `ytb-build/align-out/` = **٤٩**.
- كاش ASR على الماك: `~/.cache/hawshat/wwords/*` = **٣٦** ملفاً · مخرجات الماك `~/align_sharawi/out/` = **١١٢**.
- كاشات على الخادم: `ytb-build/wwords-cache/` و`wwords-cache-mac/` = ١٢+١٢ (نُسخ للقياس/النقل).
- أرقام جودة الكهف ٥٣٩/٠٠١ (المرجع الدائم): ٕ٧٫٨٪ → مطابقة كلمية ٦٤٫٧٪ → **مطابقة حروف ٨٢٫٤٪** (`cov_strict` ٦٥٫٨٪).
- أوامر القياس: `find $W/ytb -name '*.align.json' | wc -l` · `ls $W/ytb-build/align-out | wc -l` · `ssh mac 'ls ~/.cache/hawshat/wwords | wc -l'`.
- تدقيق جودة صفّ: `python3 $W/ytb-build/align_qa.py sharawi/539` (رتابة + مطابقة المنشور).

## الجهازان (قياس 2026-10-15 00:31)

- الخادم: **٤ أنوية** · RAM مستخدم ٢٩٥٢MB / حر **٤٨٣MB** · **بلا swap** (لا تشغّل عليه ASR ثقيلاً).
- الماك: macOS 26.6 · arm64 · ١٠ أنوية · ١٦GB · القرص الحر **١٣٫٧GB** (حدّ `safe_run` ≥ ٦٠٠٠MB).
- أوامر: `nproc; free -m` على الخادم · `ssh mac 'df -m / | tail -1; sysctl -n vm.swapusage'`.

## الكوتة (تُقاس دائماً)

```bash
agy -p "/usage" --output-format json   # المفتاح المستعمل: gemini-5h
```

- محاضرة ١٠٦د ≈ ٠٫١٠٦ نقطة من نطاق الخمس ساعات · argon ≈ ٦٫٥× ذلك (سبب رفضه — انظر ٠٢).

## مواقع السجلات والحالة (اذهب إليها قبل أي سؤال)

| ماذا | أين |
|---|---|
| تفريغ الشعراوي (المنسّق/البِركة) | `ytb-build/logs/sharawi-run.log` · `sharawi-pool.log` · `logs/prefetch_audio_range_*.log` |
| حالة التفريغ والمنسّق | `ytb-build/transcribe-state.json` · `sharawi_run_state.json` · `.sharawi-claims.txt` · `/root/workspace/.agy-jobs.jsonl` |
| تثبيت/إيقاف الماك | `ytb-build/logs/mac_cleanup.log` · `logs/transcribe_pause_resume.log` |
| المحاذاة على الماك | `~/align_sharawi/logs/{guard_*.log,safe_run.log,rerun_*.log,cleanup.log}` |
| حارس الفشل | `ytb-build/watchdog_attempts.json` + خرج `failed_watch.py` |
| مهام cron | `/root/.hermes/cron/jobs.json` |

## قاعدة التقارير

إن اختلف رقم في ملف مع القياس الجديد ⇒ **القياس يفوز**، وأصلح الملف أو أشر إلى أنه قديم بدل تكرار الرقم الخاطئ.

## تجارب ترقية v2 — سجل القياسات (يُحدَّث بالنتائج الحقيقية فقط)

**تجربة المرحلة ١ (تطبيع ظلّي + Gotoh + rapidfuzz، جافّة بلا ASR)** — المطلوب: ٠٠٣، ٠٠٤، ٠٠٦، ٠١٤.
العمود «قبل» = نسبة المراسي التامة بطريقة v1 (difflib على النص المطبَّع القديم) من نفس الكاش، «بعد» = v2.

| الدرس | كلمات | مراسي v1 (تامة) | مراسي v2 (تامة) | مراسي v2 (ضبابية ≥٠٫٨) | الكاش المستعمل |
|---|---|---|---|---|---|
| kahf539_003 |  |  |  |  |  |
| kahf539_004 |  |  |  |  |  |
| kahf539_006 |  |  |  |  |  |
| kahf539_014 |  |  |  |  |  |

**تجربة المرحلة ٢ (CTC مقابل Whisper DTW)** — الدرسان ٠٠١ و٠٠٥، على الماك ثم ONNX UINT8 على الـVPS:

| الدرس/المحرّك | زمن (ث) | ذروة الذاكرة | التغطية | انحراف الحدود مقابل `.align.force.json` |
|---|---|---|---|---|
| ٠٠١ — v1 (DTW) |  |  |  | مرجع |
| ٠٠١ — CTC M1 Pro |  |  |  |  |
| ٠٠١ — CTC ONNX UINT8 / VPS |  |  |  |  |
| ٠٠٥ — v1 (DTW) |  |  |  | مرجع |
| ٠٠٥ — CTC M1 Pro |  |  |  |  |
| ٠٠٥ — CTC ONNX UINT8 / VPS |  |  |  |  |

**قاعدة:** أي خلية فارغة = لم تُقس بعد؛ لا تُخمِّن ولا تنسخ رقماً من مرجع آخر.
