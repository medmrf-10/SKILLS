---
name: continuous-skill-improver
description: "Use when running or managing the Subagent-Driven Continuous Skill Improvement loop (*/20 * * * * cron) and Anti-Deception Production Watchdog across all 9 skills in /Users/macm1pro/REPOS/SKILLS/. Enforces zero main-context bloat via isolated subagents, detects fake progress counters ($HOME missing in systemd, 0 real .txt files written despite rising completed_series_this_run), audits Mac MPS alignment (<95% match rate investigation & post-breath onset tightening), rotates skills round-robin on real production data, expands deterministic quality gates, and syncs GitHub + hermes-vps."
version: 1.0.0
author: Mohamed Boumaraf, Antigravity Agent
license: MIT
platforms: [macos, linux]
metadata:
  hermes:
    tags: [continuous-improvement, subagent-loop, watchdog, anti-deception, cron, round-robin, quality-gates, vps, mac-mps]
    related_skills: [sheikh-series-pipeline, person-to-knowledge-orchestrator, person-discovery-intake, sheikh-curation, turath-deep-indexing, turath-pdf-to-text, turath-embedding-gemma2, agy-lean-cli]
---

## القواعد الحاكمة الإلزامية (التدرج الأسي اليدوي والأركان الخمسة لتقارير المشكلات)

1. **قاعدة التدرج الأسي والفحص اليدوي الذاتي (`1 -> 10 -> 100 -> 1000`)**:
   - في العناصر العشرة الأولى (`1, 2, 3... 10`) ينفذ الوكيل عملاً واحداً فقط في كل مرة، ويتفحص المخرج يدوياً بعينه وعقله (لا بالسكريبتات وحدها)، ويصلح الجذور ويطور المهارة ذاتها قبل الانتقال للعمل التالي، ثم يتدرج بالدفعات العشرية (`10, 20, 30... 100`).
2. **الأركان الخمسة الإلزامية لتقرير الفحص التجريبي (`5-Pillar Empirical Audit Report`)**:
   - يلتزم كل وكيل فاحص عند تجربة أي مهارة على بيانات حقيقية بتقديم وتوثيق تقرير مفصل يضم خمسة أركان إلزامية:
     1. **ما الهدف من التجربة**: تحديد المهارة والعينة الحقيقية والمعيار المستهدف.
     2. **ماذا فعل الوكيل خطوة بخطوة**: السرد الدقيق للخطوات والأوامر المنفذة فعلياً.
     3. **ما المشكلات المكتشفة مشفوعة بالأدلة المباشرة**: إثبات الخلل بمقتطفات حقيقية من المخرجات على القرص.
     4. **لماذا حدثت المشكلة جذرياً (`Root Cause`)**: تشريح السبب البرمجي أو المنطقي العميق للخلل.
     5. **كيف يقترح حلها**: الحل الجذري المنفذ أو المقترح لعرضه على محمد أو مستشار الهندسة (`Claude Opus`).
3. **الضوابط العشرة للوكيل المنفذ برمجياً (`10 Engineering Execution Guardrails`)**:
   - يلتزم كل وكيل منفذ أو مطور للمهارات بـ `10` ضوابط صارمة: قراءة الوثائق المرتبطة بالمهمة فقط لتوفير التوكنات وتجنب التشتت، وتنفيذ مهمة ذرية واحدة محددة، وكتابة خطة قصيرة قبل التعديل، وعدم تغيير مخطط البيانات دون توثيق القرار (`Decision Record`)، وكتابة اختبارات ومعايير قبول حتمية، وعدم حذف سجل المراجع والعزو (`provenance`)، والتحقق الفعلي من مخرجات النموذج قبل نشرها، وتحديث الوثائق المتأثرة فقط، وعرض الملفات المعدلة والمخاطر بوضوح، والتوقف للسؤال عند وجود تعارض معماري.

# حلقة التحسين المستمر للمهارات وحارس الإنتاج الفعلي (`continuous-skill-improver v1.0`)

مهارة معيارية دائمة وقابلة لإعادة الاستخدام لإدارة **التحسين المستمر للمهارات بالدور (`Round-Robin Empirical Skill Improvement`)** بالتوازي مع **حارس خط الإنتاج الفعلي المضاد للخداع (`Anti-Deception Production Watchdog`)** عبر منظومة التراث والمعرفة (`/Users/macm1pro/REPOS/SKILLS/`).

> **المرجع الهندسي التفصيلي:** اقرأ [`references/01-subagent-loop-and-watchdog-protocol.md`](./references/01-subagent-loop-and-watchdog-protocol.md) للاطلاع على القوالب الجاهزة لاستدعاء `schedule` و`invoke_subagent`، ومخطط `CONTINUOUS_IMPROVEMENT_STATE.json`، وقائمة فحص حارس الإنتاج الفعلي (`Anti-Deception Checklist`).

---

## ١. القواعد الذهبية الثلاث (`The 3 Golden Rules`)

### القاعدة الذهبية ١: التنفيذ الحصري عبر الوكلاء الفرعيين (`Subagent-Only Execution / Zero Main-Context Bloat`)
- **المنسق الرئيسي (`Main Agent`)** لا يقرأ ملفات الكود الكبيرة، ولا يفحص سجلات التفريغ الطويلة، ولا يشغّل الاختبارات الثقيلة في المحادثة الرئيسية أبداً، وذلك لحماية نافذة السياق الرئيسية (`Context Window`) من التضخم على مدار الساعات والأيام.
- يقتصر دور المنسق الرئيسي على:
  1. إنشاء جدول زمني دوري: `schedule(CronExpression="*/20 * * * *", IsDaemon=false, Prompt=...)`.
  2. عند كل تنبيه دوري (`Cron Trigger`):
     - فحص الوكلاء الفرعيين النشطين عبر `manage_subagents(Action="list")`. إذا كان هناك وكيل تحسين يعمل بالفعل (`state == "running"`)، لا يطلق وكيلاً مكرراً.
     - توليد التكليف المعياري للدورة الجديدة (أو قراءته عبر `scripts/manage_improvement_loop.py --next-prompt`) وإطلاق وكيل فرعي معزول عبر `invoke_subagent(TypeName="self", Model="inherit", Role="Continuous Skill Improver & Watchdog", Prompt=...)`.
     - استلام ملخص الوكيل الفرعي المقتضب (`5 أسطر فقط`) بعد انتهاء الدورة.

---

### القاعدة الذهبية ٢: حارس خط الإنتاج الفعلي المضاد للخداع (`Anti-Deception Production Watchdog`)
- **يُمنع منعاً باتاً** الاكتفاء بقراءة العدادات الشكلية مثل `completed_series_this_run` في `/root/workspace/ytb-build/transcribe_selected_state.json` أو نتيجة `systemctl is-active transcribe-smallest-first.service`!
- **لماذا؟ (واقعة الخداع الموثقة):** قد تكون خدمة `systemd` في حالة `active (running)` ويرتفع عداد `completed_series_this_run` (مثلاً إلى `15` أو `71`) بينما تفشل أداة `agy` داخلياً في كل مقطع بسبب غياب متغير البيئة `Environment="HOME=/root"` في وحدة `systemd` (`Fatal Error: $HOME is not defined`)، فتطوي السلسلة تلو الأخرى في ثوانٍ دون كتابة أي ملف `.txt` حقيقي على القرص!
- **الفحوص الأربعة الإلزامية في كل دورة (`Mandatory 4-Point Live Verification`):**
  1. **سلامة بيئة وحدة `systemd` على الخادم (`Systemd Unit Environment`):**
     - التحقق من وجود `User=root` و`Environment="HOME=/root"` و`PATH` الشامل لـ `/root/.local/bin` داخل `/etc/systemd/system/transcribe-smallest-first.service`.
  2. **سلامة اللوج الحي (`Live Log Tail Health`):**
     - فحص آخر `50`–`80` سطراً من `/root/workspace/ytb-build/transcribe_smallest_first.log` والتأكد من خلوها التام من:
       - `HOME is not defined` أو `$HOME` غير معرّف.
       - الفشل المتتالي للمقاطع (`فشل المقطع` / `[✗ فشل]`) دون ظهور علامات النجاح الحقيقية (`✓ المقطع` أو `[✓ تم]`).
  3. **الإنتاج الفعلي على القرص (`Real Disk Output vs Counter Delta`):**
     - فحص مخرجات [`vps_pipeline_watchdog.py`](../sheikh-series-pipeline/scripts/vps_pipeline_watchdog.py) (`/root/workspace/ytb-build/vps_watchdog_status.json`):
       - عدد ملفات `.txt` الحقيقية (`>= 400 bytes`) المكتوبة على القرص في آخر 30 دقيقة (`new_txts_last_30m`).
       - عدد المقاطع المنجزة فعلياً في ذيل اللوج (`recent_chunks_ok_in_tail80`).
     - إذا كان `completed_series_this_run > 0` (أو زاد عن الدورة السابقة) بينما `new_txts_last_30m == 0` و`recent_chunks_ok_in_tail80 == 0` (دون اكتمال التفريغ الكلي `DRAIN_COMPLETE`)، تُعلن فوراً حالة **`FAKE_PROGRESS_DECEPTION`** ويُصلح ملف `.service` ويُعاد تشغيل الخدمة فوراً.
  4. **سلامة خط المحاذاة على الماك (`Mac MPS Alignment Health & Onset Discipline`):**
     - فحص `/tmp/mac_align_spool/mac_align_state.json` للتأكد من تقدم `completed_count` وسرعة المحاذاة (`speedup_vs_realtime`).
     - **قاعدة التحقيق الإلزامي (`< 95.0% Match Rate Rule`):** أي درس ينزل معدل مطابقته (`match_rate`) عن `95.0%` يجب التحقيق في سببه الجذري (هل هو نقص في التفريغ أو ترويسة غير منطوقة أو خطأ محاذاة).
     - **قاعدة شد بداية الكلمة بعد النفس (`ALIGN-ONSET-BREATH-JUMP`):** منع قفز `start_sec` للكلمة التالية إلى بداية نفس الشيخ أو سكتته الطويلة بين الجمل، مع الالتزام الصارم بعدم تعديل أو إعادة محاذاة الملفات المنجزة سابقاً (يُطبَّق على المحاذاة القادمة فقط).

---

### القاعدة الذهبية ٣: الاختبار التجريبي بالدور على البيانات الحقيقية وتوسيع البوابات (`Round-Robin Real-Data Empirical Testing & Gate Expansion`)
1. **تحديد المهارة المستهدفة:**
   - قراءة `/Users/macm1pro/REPOS/SKILLS/CONTINUOUS_IMPROVEMENT_STATE.json` لتحديد المهارة التي عليها الدور (`skills_rotation[next_skill_index]`) وأي مهام ذات أولوية في `priority_backlog`.
2. **الاختبار على بيانات إنتاج حقيقية (`100% Real Production Data`):**
   - يُمنع الاكتفاء ببيانات اصطناعية صغيرة؛ تُختبر المهارة على:
     - السلاسل الحية المفرغة والمحاذاة من `hermes-vps` و`Mac MPS`.
     - ملفات المشايخ الـ `17` في `/Users/macm1pro/REPOS/cheikh/data/curated_sheikhs/*_raw.json` (`26,881` فيديو خاماً و`1,092` سلسلة).
     - فهرس الشاملة الكامل (`shamela4_books_index.json.gz` — `8,589` كتاباً) وقاعدة `/Users/macm1pro/REPOS/swe/Shamela4_Full_DB`.
     - ملفات `PDF` التراثية والفهرسية الحقيقية (`jamhara.pdf`، صفحات الكتب المصورة والحواشي).
3. **الإصلاح الجذري وتوسيع البوابات (`Root-Cause Fix + Gate N+1`):**
   - اكتشاف الحالات الحدية (`Edge Cases`) أو الأعطال الصامتة في الكود الفعلي ومعالجتها جذرياً.
   - إضافة أو ترقية بوابة فحص حتمية (`Gate N+1`) داخل `scripts/test_*_gates.py` الخاص بالمهارة والتأكد من خروجه بـ **`PASS (0 errors)`**.
4. **التوثيق والرفع والمزامنة (`State + Log + GitHub + VPS Sync`):**
   - تحديث `CONTINUOUS_IMPROVEMENT_STATE.json` (تدوير `next_skill_index = (idx + 1) % len(skills_rotation)` وزيادة `cycle_count`) عبر `scripts/manage_improvement_loop.py --advance-cycle`.
   - توثيق الدورة في `CONTINUOUS_IMPROVEMENT_LOG.md`.
   - رفع التحديثات إلى GitHub (`git add` ← `git commit` ← `git pull --rebase --autostash origin main` ← `git push origin main`) ومزامنتها إلى `hermes-vps:/root/workspace/SKILLS`.

---

## ٢. المهارات التسع المشمولة في حلقة التدوير (`The 9 Rotated Skills`)

| الفهرس | اسم المهارة | بوابة الفحص الحتمية | البيانات الحقيقية المعتمدة للاختبار |
|---|---|---|---|
| `0` | [`turath-deep-indexing`](../turath-deep-indexing/SKILL.md) | `scripts/test_objects_sqlite_gates.py` | دروس مفرغة ومحاذاة حقيقية + كتب الشاملة + فهرس القرآن (`6,236` آية) |
| `1` | [`person-discovery-intake`](../person-discovery-intake/SKILL.md) | `scripts/test_discovery_gates.py` | ملفات `jamhara.pdf` + الـ `17` شيخاً (`*_raw.json`) + `8,589` كتاباً بالشاملة + حزم `Archive.org` |
| `2` | [`sheikh-curation`](../sheikh-curation/SKILL.md) | `scripts/test_curation_v2_gates.py` | كامل مدونة المشايخ الـ `17` (`26,881` فيديو خاماً و`1,092` سلسلة مرجعية) |
| `3` | [`sheikh-series-pipeline`](../sheikh-series-pipeline/SKILL.md) | `scripts/test_pipeline_v5_gates.py` | طابور `hermes-vps` + جسر `Opus 12kbps` + محاذاة `Mac MPS` + `ALIGN-ONSET-BREATH-JUMP` |
| `4` | [`turath-pdf-to-text`](../turath-pdf-to-text/SKILL.md) | `scripts/test_pdf_adapter_gates.py` | صفحات `PDF` التراثية ذات الحواشي والطرر المدارة `90° CW` ومحول `Pre-Flight v4` |
| `5` | [`turath-embedding-gemma2`](../turath-embedding-gemma2/SKILL.md) | `scripts/test_embedding_gemma2_gates.py` | قواعد بيانات `SQLite` العلائقية الحقيقية (`passages` + `science_gems`) والبحث الهجين `RRF` |
| `6` | [`person-to-knowledge-orchestrator`](../person-to-knowledge-orchestrator/SKILL.md) | `scripts/test_orchestrator_gates.py` | التشغيل الشامل من الاسم إلى `SQLite + Embeddings` والفهرسة التزايدية (`Delta Ingestion`) |
| `7` | [`agy-lean-cli`](../agy-lean-cli/SKILL.md) | `scripts/test_agy_lean_gates.py` | عزل `HOME` وحارس الكوتة الحي (`live_quota.json`) ومنع استنزاف التوكنات |
| `8` | [`continuous-skill-improver`](./SKILL.md) | `scripts/test_improver_gates.py` | فحص حارس الخداع (`Anti-Deception Watchdog`) وتدوير الحالة وتكامل المستودع الكامل |

---

## ٣. أدوات التشغيل والفحص (`CLI & Gate Scripts`)

### ١. إدارة حلقة التحسين وحارس الإنتاج (`scripts/manage_improvement_loop.py`)

```bash
# عرض حالة الحلقة الحالية والمهارة التي عليها الدور:
python3 /Users/macm1pro/REPOS/SKILLS/continuous-skill-improver/scripts/manage_improvement_loop.py --status

# فحص صحة اللوج وبيئة systemd وكشف التقدم الوهمي (Anti-Deception Audit):
python3 /Users/macm1pro/REPOS/SKILLS/continuous-skill-improver/scripts/manage_improvement_loop.py --audit-pipeline

# توليد نص التكليف الكامل (Prompt) للوكيل الفرعي للدورة القادمة:
python3 /Users/macm1pro/REPOS/SKILLS/continuous-skill-improver/scripts/manage_improvement_loop.py --next-prompt

# تقديم الدور بعد انتهاء الدورة بنجاح (Advance Cycle):
python3 /Users/macm1pro/REPOS/SKILLS/continuous-skill-improver/scripts/manage_improvement_loop.py \
    --advance-cycle \
    --skill "continuous-skill-improver" \
    --datasets "CONTINUOUS_IMPROVEMENT_STATE.json + real VPS/Mac watchdog telemetry + 9 skills gates" \
    --bugs-fixed 3 \
    --gate-status "PASS (0 errors)"
```

### ٢. بوابة الجودة الرباعية (`scripts/test_improver_gates.py`)

```bash
python3 /Users/macm1pro/REPOS/SKILLS/continuous-skill-improver/scripts/test_improver_gates.py
```

تتحقق البوابة الحتمية من الطبقات الأربع التالية:
- **Gate 1 (`Round-Robin State Rotation & Subagent Prompt Generation`):** صحة تدوير الفهرس عبر المهارات الـ `9` وتوليد تكليف الوكيل الفرعي متضمناً قواعد عدم الخداع وأمر التنفيذ الواحد.
- **Gate 2 (`Anti-Deception Watchdog Gate`):** التحقق بنسبة 100% من كشف:
  1. التقدم الوهمي (`completed_series_this_run=15` مع `new_txts_last_30m=0` و`recent_chunks_ok=0`).
  2. خطأ `$HOME is not defined` في لوج التفريغ.
  3. غياب `Environment="HOME=/root"` من ملف وحدة `systemd`.
  4. حالة الصحة السليمة عند كتابة ملفات `.txt` حقيقية وخلو اللوج من الأخطاء.
- **Gate 3 (`Skills Repository & Gate Scripts Integrity`):** التحقق من وجود جميع المهارات الـ `9` وملفات `SKILL.md` وبوابات الاختبار `test_*_gates.py`.
- **Gate 4 (`State & Log Synchronization Integrity`):** التحقق من سلامة بنية `CONTINUOUS_IMPROVEMENT_STATE.json` وتطابقها مع `CONTINUOUS_IMPROVEMENT_LOG.md`.
