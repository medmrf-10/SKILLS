# المرجع الهندسي 01 — بروتوكول حلقة الوكلاء الفرعيين وحارس الإنتاج المضاد للخداع (`Subagent Loop & Anti-Deception Watchdog Protocol`)

يوثّق هذا المرجع البنية التشغيلية الكاملة لمهارة [`continuous-skill-improver`](../SKILL.md)، شاملةً القوالب الجاهزة للجدولة الدورية وإطلاق الوكلاء الفرعيين، ومخطط ملف الحالة `CONTINUOUS_IMPROVEMENT_STATE.json`، وقائمة فحص حارس الإنتاج الفعلي (`Anti-Deception Checklist`).

---

## ١. قالب إنشاء الجدولة الدورية في المحادثة الرئيسية (`Main Agent Cron Schedule Template`)

ينشئ المنسق الرئيسي (`Main Agent`) جدولة كرون كل 20 دقيقة عبر أداة `schedule` دون تنفيذ أي قراءة ملفات كبيرة في السياق الرئيسي:

```json
{
  "CronExpression": "*/20 * * * *",
  "IsDaemon": false,
  "Prompt": "حان موعد دورة التحسين المستمر للمهارات وفحص خط الإنتاج الفعلي (Subagent-Driven Continuous Skill Improvement & Anti-Deception Watchdog). افحص manage_subagents(Action='list') أولاً؛ إذا لم يكن هناك وكيل تحسين قيد التشغيل، أطلق وكيلاً فرعياً معزولاً عبر invoke_subagent(TypeName='self', Model='inherit') لتنفيذ دورة الفحص والتحسين الكاملة وإرجاع ملخص من 5 أسطر فقط."
}
```

---

## ٢. قالب استدعاء الوكيل الفرعي المعزول (`invoke_subagent Template`)

عند كل تنبيه دوري، يتحقق المنسق الرئيسي من عدم وجود وكيل فرعي نشط ثم يستدعي `invoke_subagent` بالقالب التالي (أو يولّده تلقائياً عبر `python3 /Users/macm1pro/REPOS/SKILLS/continuous-skill-improver/scripts/manage_improvement_loop.py --next-prompt`):

```json
{
  "Subagents": [
    {
      "TypeName": "self",
      "Model": "inherit",
      "Role": "Continuous Skill Improver & Production Watchdog",
      "Prompt": "أنت الوكيل الفرعي المسؤول عن تنفيذ دورة التحسين المستمر للمهارات وحارس الإنتاج الفعلي في `/Users/macm1pro/REPOS/SKILLS/`. التزم بقاعدة أمر واحد فقط في كل استدعاء `run_command` (يُمنع استخدام `&&` منعاً باتاً) ولا تسأل المستخدم أي سؤال.\n\n1. **حارس الإنتاج الفعلي المضاد للخداع (`Anti-Deception Watchdog`):**\n   - افحص `/Users/macm1pro/REPOS/SKILLS/continuous-skill-improver/scripts/manage_improvement_loop.py --audit-pipeline`.\n   - لا تكتفِ بقراءة `completed_series_this_run` أو `systemctl is-active`؛ تحقق من وجود `Environment=\"HOME=/root\"` في `/etc/systemd/system/transcribe-smallest-first.service`، وخلو آخر 50 سطراً من `transcribe_smallest_first.log` من `$HOME is not defined`، وعدد ملفات `.txt` المكتوبة فعلياً في آخر 30 دقيقة (`new_txts_last_30m`)، وسلامة محاذاة الماك (`mac_align_state.json` والتحقيق في أي درس `< 95.0%`).\n\n2. **تحسين المهارة التي عليها الدور (`Round-Robin Skill Improvement`):**\n   - اقرأ `/Users/macm1pro/REPOS/SKILLS/CONTINUOUS_IMPROVEMENT_STATE.json` لتحديد المهارة المستهدفة (`skills_rotation[next_skill_index]`).\n   - اختبر المهارة على بيانات إنتاج حقيقية (سلاسل السيرفر، المشايخ الـ 17، فهرس الشاملة 8,589 كتاباً، ملفات PDF الحقيقية)، واكتشف الحالات الحدية وعالجها برمجياً.\n   - أضف أو شغّل بوابة الفحص الحتمية في `scripts/test_*_gates.py` وتأكد من خروجها بـ `PASS (0 errors)`.\n\n3. **التوثيق والمزامنة:**\n   - حدّث `CONTINUOUS_IMPROVEMENT_STATE.json` و`CONTINUOUS_IMPROVEMENT_LOG.md`.\n   - نفذ `git add` ثم `git commit` ثم `git pull --rebase --autostash origin main` ثم `git push origin main` وزامن `hermes-vps:/root/workspace/SKILLS`.\n   - أرسل عبر `send_message` ملخصاً مقتضباً من 5 أسطر فقط."
    }
  ]
}
```

---

## ٣. مخطط `CONTINUOUS_IMPROVEMENT_STATE.json` (`State Schema`)

يحفظ الملف `/Users/macm1pro/REPOS/SKILLS/CONTINUOUS_IMPROVEMENT_STATE.json` حالة التدوير الدوري عبر المهارات التسع وسجل الأولويات:

```json
{
  "loop_version": "2.1-subagent-driven",
  "updated_at": "2026-10-18T21:20:00+02:00",
  "cycle_count": 15,
  "next_skill_index": 0,
  "last_improved_skill": "continuous-skill-improver",
  "priority_backlog": [
    {
      "skill": "sheikh-series-pipeline",
      "issue_id": "ALIGN-ONSET-BREATH-JUMP",
      "title": "القفز المبكر لبداية الكلمة التالية أثناء أخذ الشيخ نفساً عميقاً أو سكتة بين الجمل",
      "description": "عندما يأخذ الشيخ نفساً عميقاً أو يسكت لثوانٍ بين كلمتين، تقفز بداية الكلمة التالية (start_sec) إلى أول النفس/السكتة وتنتظر عدة ثواني حتى ينطقها الشيخ فعلياً.",
      "constraint": "يُطبَّق الحل على المحاذاة القادمة فقط؛ يُمنع تعديل أو إعادة محاذاة الملفات المنجزة سابقاً."
    }
  ],
  "skills_rotation": [
    "turath-deep-indexing",
    "person-discovery-intake",
    "sheikh-curation",
    "sheikh-series-pipeline",
    "turath-pdf-to-text",
    "turath-embedding-gemma2",
    "person-to-knowledge-orchestrator",
    "agy-lean-cli",
    "continuous-skill-improver"
  ],
  "last_completed_cycle": {
    "cycle": 15,
    "skills_tested": [
      "continuous-skill-improver"
    ],
    "real_datasets_used": [
      "CONTINUOUS_IMPROVEMENT_STATE.json + real VPS/Mac watchdog telemetry + all 9 skills gates"
    ],
    "bugs_fixed": 3,
    "gate_status": "PASS (0 errors)"
  }
}
```

---

## ٤. قائمة فحص حارس الإنتاج الفعلي (`Anti-Deception Watchdog Checklist`)

| البند | الخطأ الشائع (الخداع الشكلي) | الفحص الفعلي الصحيح (المانع للخداع) | إجراء الإصلاح الفوري عند الخلل |
|---|---|---|---|
| **١. بيئة خدمة `systemd` على الخادم** | الاكتفاء بـ `systemctl is-active transcribe-smallest-first.service` | التحقق من وجود `User=root` و`Environment="HOME=/root"` و`PATH` في `/etc/systemd/system/transcribe-smallest-first.service` | حقن `Environment="HOME=/root"` ثم `systemctl daemon-reload` ثم `systemctl restart transcribe-smallest-first.service` |
| **٢. لوج التفريغ الحي (`transcribe_smallest_first.log`)** | عدم قراءة ذيل اللوج والاكتفاء بعداد السلاسل | فحص آخر 50–80 سطراً والتأكد من `home_err == 0` (`$HOME is not defined`) ووجود `[✓ تم]` أو `✓ المقطع` | إعادة تشغيل الخدمة بعد إصلاح البيئة ومراجعة Скрипт `vps_pipeline_watchdog.py` |
| **٣. الملفات المكتوبة فعلياً (`Disk Output`)** | تصديق ارتفاع `completed_series_this_run` في `transcribe_selected_state.json` | فحص `new_txts_last_30m` (`>= 400 bytes`) و`recent_chunks_ok_in_tail80` في `vps_watchdog_status.json` | إذا كان `completed_series_this_run > 0` و`new_txts_last_30m == 0` و`recent_chunks_ok == 0`، أعلن `FAKE_PROGRESS_DECEPTION` وأعد ضبط حالة السلاسل المتخطاة وأصلح الخدمة |
| **٤. محاذاة الصوت والنص على الماك (`Mac MPS Alignment`)** | الاكتفاء بعداد الدروس دون مراقبة جودة المطابقة وبدايات الكلمات | فحص `/tmp/mac_align_spool/mac_align_state.json`، والتحقيق في أي درس `match_rate < 95.0%`، وتطبيق قاعدة شد بداية الكلمة بعد النفس (`ALIGN-ONSET-BREATH-JUMP`) على المحاذاة القادمة فقط | فحص النص والتوقيت للدرس `< 95.0%` وتحديث منطق `ctc_pure_align.py` للدروس الجديدة دون لمس المحاذايات السابقة |
