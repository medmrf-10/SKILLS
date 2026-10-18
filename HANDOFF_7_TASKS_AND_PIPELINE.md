# ملف التسليم الشامل (Handoff 2): إنجاز المهام السبع في `SKILLS` + `agy-lean-cli` + إدارة الكوتة وخط الإنتاج الهجين

- **تاريخ التسليم:** `2026-10-18 11:17 AM`
- **مستودع المهارات:** [`/Users/macm1pro/REPOS/SKILLS/`](file:///Users/macm1pro/REPOS/SKILLS/) (`https://github.com/medmrf-10/SKILLS.git`)
- **قائمة المهام التفصيلية:** [`/Users/macm1pro/REPOS/SKILLS/TODO.md`](file:///Users/macm1pro/REPOS/SKILLS/TODO.md)

---

## 1. حالة خط الإنتاج الحي (التفريغ على السيرفر + المحاذاة على الماك) — مؤمَّن بالكامل على مستوى نظام التشغيل

تم تأمين خطَّي الإنتاج ليعمل كلٌّ منهما كخدمة نظام مستقلة (`OS-level Daemon`) **لا تتأثر إطلاقاً بإغلاق أي محادثة في Antigravity**:

### أ) خط التفريغ الصوتي والجسر المضغوط على السيرفر (`hermes-vps`)
1. **خدمة التفريغ (`systemd`):**
   - `ytb-transcribe-fleet.service` تشغّل `/root/workspace/ytb-build/transcribe_selected_smallest_first.py` (`SERIES_WORKERS=4` × `CHUNK_WORKERS=4`).
   - القائمة المعتمدة: `/root/workspace/cheikh-exports/cheikh-selected-curated-2026-10-17.json` (`333` سلسلة مختارة لـ `17` شيخاً، `7,383` درساً، شاملةً سلاسل الشيخ علي جمعة الـ 11 كاملةً).
   - السكربت المحدَّث `/root/workspace/SKILLS/sheikh-series-pipeline/scripts/agy_transcribe.py` يحتوي الآن على:
     - **تحويل فوري إلى `Opus 12kbps VoIP`** (`~3 MB` للساعة) في `/root/workspace/align-bridge/ready/` فور نجاح التفريغ وقبل حذف `.mp3` المؤقت (تم إصلاح خطأ `audio_path` ونشره).
     - **حارس الكوتة الحي (`_is_quota_safe_for_background`)** الذي يقرأ `/root/workspace/ytb-build/live_quota.json` ويوقف عمال الخلفية مؤقتاً إذا نزلت كوتة الـ 5 ساعات تحت `15%` (لحماية `10%` للوكيل الرئيسي) أو إذا وصلت الكوتة الأسبوعية إلى `25%` وباقي أكثر من `12` ساعة على التجديد.
2. **خدمة الجسر الصوتي (`systemd`):**
   - `ytb-align-feeder.service` تشغّل `/root/workspace/ytb-build/vps_align_feeder.py` لاستكمال أي ملفات قديمة غير محولة في الجسر.
3. **الرفع التلقائي إلى GitHub (`OS Crontab`):**
   - تم تثبيت مهمة `crontab` على نظام تشغيل `hermes-vps`:
     `*/30 * * * * /root/.hermes/scripts/sync_ytb.sh >> /root/workspace/ytb-build/sync_ytb.log 2>&1`
   - ترفع التفريغات (`.txt`) وملفات المحاذاة (`.align.json`) تلقائياً كل 30 دقيقة إلى `https://github.com/medmrf-10/ytb.git`.
4. **أمر الفحص السريع من الماك:**
   - `ssh hermes-vps "python3 /root/workspace/ytb-build/status_snapshot.py"`

### ب) خط المحاذاة الصوتية على شريحة الماك (`Apple Silicon M1 Pro MPS`)
1. **خدمة النظام المستقلة (`macOS LaunchAgent`):**
   - ملف الخدمة: [`/Users/macm1pro/Library/LaunchAgents/com.mohamed.mac-align-fleet.plist`](file:///Users/macm1pro/Library/LaunchAgents/com.mohamed.mac-align-fleet.plist) (`RunAtLoad=true`, `KeepAlive=true`).
   - يعمل تحت `launchd` مباشرةً (`PID` مستقل مع `caffeinate -i`) ولا يتوقف بإغلاق المحادثة.
2. **تخفيف الحمل ومزامنة الكوتة في [`/Users/macm1pro/workspace/ytb-build/mac_align_fleet.py`](file:///Users/macm1pro/workspace/ytb-build/mac_align_fleet.py):**
   - يعمل بدقة `fp16` مع طي الصمت (`plan_silence` + `compact_wave` + `unpad_emissions`) بسرعة **`~46×` من الوقت الحقيقي**.
   - تم تخفيف الحمل ليبقى الماك بارداً وسريعاً أثناء عمل الوكلاء الفرعيين: `MAC_ALIGN_BATCH_SIZE=3`، `MAC_ALIGN_PREFETCH=6`، وتفريغ ذاكرة GPU (`torch.mps.empty_cache()` + `gc.collect()`) مع استراحة **`3.5` ثوانٍ** بين كل درس ودرس.
   - يتضمن خيط `quota_sync_worker()` الذي يفحص الكوتة الحية كل دقيقتين عبر `/Users/macm1pro/.hermes/node/bin/antigravity-usage quota --json --all-models`، ويحفظها في `/tmp/agy_quota_snapshot.json` على الماك ويرفعها إلى `hermes-vps:/root/workspace/ytb-build/live_quota.json`.
3. **ملفات المراقبة على الماك:**
   - الحالة الحية: [`/Users/macm1pro/workspace/ytb-build/mac_align_state.json`](file:///Users/macm1pro/workspace/ytb-build/mac_align_state.json)
   - السجل الحي: `/Users/macm1pro/workspace/ytb-build/mac_align_fleet.log`

---

## 2. اكتشاف نظام الكوتة في `Antigravity` وقواعد محمد الصارمة

### أ) أداة فحص الكوتة الحية والدقيقة 100%
- **الأمر المباشر (جدول مرئي):**
  `/Users/macm1pro/.hermes/node/bin/antigravity-usage quota`
- **الأمر البرمجي (JSON كامل لكل النماذج):**
  `/Users/macm1pro/.hermes/node/bin/antigravity-usage quota --json --all-models`
- **كيف تعمل الأداة داخلياً؟**
  تتصل بعملية `language_server` المحلية الخاصة بـ Antigravity على الماك عبر نقطة النهاية `/exa.language_server_pb.LanguageServerService/GetUserStatus` مع التوكن `X-Codeium-Csrf-Token`، وتعيد النسبة المئوية المتبقية (`remainingPercentage`) ووقت التجديد القادم بالمللي ثانية (`timeUntilResetMs`) لكل نموذج في حساب `medmrf.10@gmail.com`.

### ب) مجموعتا الكوتة (`Quota Pools`) وحالتهما عند التسليم (`11:16 AM`)
1. **مجموعة Gemini (`Gemini 4 Argon High/Medium/Low` + `Gemini 3.8 Flash High/Medium/Low`):**
   - تشمل نموذج الوكيل الرئيسي الحالي (`MODEL_PLACEHOLDER_M417` = `Gemini 4 Argon (High)`) ونموذج التفريغ الصوتي (`gemini-3.8-flash-high`).
   - **المتبقي حالياً:** **`🟢 84.9%`** | **يتجدد بعد:** **`2h 40m`** (`2026-10-18T11:56:02Z`).
2. **مجموعة Claude / GPT-OSS (`Claude Opus 5.5 High/Medium/Low` + `Claude Sonnet 5.5` + `GPT-OSS 120B`):**
   - **المتبقي حالياً:** **`🔴 4.71% (~5%)`** | **يتجدد بعد:** **`13h 06m`** (`2026-10-18T22:22:37Z` أي الساعة `12:22` منتصف الليل بتوقيت القاهرة).
   - **تحذير حرج:** بما أن كوتة `Claude Opus 5.5` عند **`4.71%`** حالياً، **يُمنع استدعاء `Claude Opus 5.5` عبر `agy` حتى تتجدد الكوتة الليلة الساعة `12:22 AM`!**

### ج) قواعد محمد الصارمة لإدارة الكوتة
1. **قاعدة نافذة الـ 5 ساعات (`5h Window Floor`):**
   - أبقِ دائماً **`>= 10%`** من كوتة الـ 5 ساعات حرة حتى لا يتوقف الوكيل الرئيسي أبداً.
   - عمال الخلفية (`agy_transcribe.py` و`agy_lean.py`) يتوقفون تلقائياً عند **`15%`** لترك هامش أمان `5%` فوق الـ `10%`.
2. **قاعدة الاحتياطي الأسبوعي (`Weekly Reserve Rule`):**
   - أبقِ **`>= 25%`** من الكوتة الأسبوعية لآخر 48 ساعة قبل التجديد الأسبوعي، **ولا تبدأ في استهلاك هذه الـ `25%` إلا إذا بقي أقل من `12` ساعة (`< 12h`) على التجديد الأسبوعي**.
   - *(ملاحظة تقنية)*: عندما يكون `timeUntilResetMs > 5.5 ساعات` في مخرجات `antigravity-usage quota --json`، فهذا يعني أن النافذة الحاكمة هي النافذة الأسبوعية/المتدحرجة وليست نافذة الـ 5 ساعات.

---

## 3. خطة تنفيذ المهام السبع + `agy-lean-cli` في المحادثة الجديدة

### القواعد الحاكمة للتنفيذ:
1. **البناء التراكمي على المهارات الحالية (لا تهدم ولا تعِد الاختراع من الصفر):**
   - المهارات الأربع الموجودة في [`/Users/macm1pro/REPOS/SKILLS/`](file:///Users/macm1pro/REPOS/SKILLS/) (`sheikh-curation`, `sheikh-series-pipeline`, `turath-pdf-to-text`, `turath-deep-indexing`) بُنيت بجهد كبير وتحتوي على قواعد ذهبية وسكربتات دقيقة.
   - المطلوب هو **ترقيتها وإضافة الجسور والمهارات المكملة فوقها** مع الحفاظ الكامل على كل قواعدها ومراجعها.
2. **التنفيذ على موجات (`Waves` من 2–3 وكلاء فرعيين `invoke_subagent` في كل موجة مع `Model="inherit"`):**
   - يعمل كل وكيل فرعي داخل مجلد مهارته المعزول فقط.
   - **يُمنع أي وكيل فرعي من تشغيل `git commit` أو `git push`** لمنع أي تعارض؛ الوكيل الرئيسي وحده يراجع ويشغّل اختبارات البوابات (`test_*_gates.py`) ثم يرفع إلى GitHub.
3. **بوابات الفحص الحتمية (`3-Layer Quality Gate`):**
   - لا تُقبل أي مهمة بتقرير إنشائي من الـ LLM؛ يجب وجود سكربت اختبار حتمي (`scripts/test_<skill>_gates.py`) يُشغَّل على عينة بيانات حقيقية ويُخرج `PASS (0 errors)`.
4. **قاعدة أوامر الطرفية (`Shell`):**
   - أمر واحد فقط في كل استدعاء (لا تستخدم `&&` أبداً).

---

### تفصيل المهام المطلوب تنفيذها بالترتيب:

#### [x] المهمة 0 (تأسيسية): مهارة `agy-lean-cli` (`/Users/macm1pro/REPOS/SKILLS/agy-lean-cli/`)
- **الهدف:** التخلص من عبء تحميل مخططات `MCP` (~38,000 توكن) في الاستدعاءات النصية أو استشارات الهندسة أو فحص ملف واحد عبر `agy`، مع دمج حارس الكوتة الحي.
- **المطلوب بناؤه:**
  1. `SKILL.md`: توثيق معمارية العزل (`Isolated HOME` بدون `mcp_config.json` + `--mode ask` + `--disable-slash-commands`) وقواعد اختيار النموذج وحماية الكوتة (`10%` لـ 5h / `25%` للأسبوعي حتى آخر 12 ساعة).
  2. `scripts/agy_lean.py`: أداة سطر أوامر ومكتبة بايثون توفر:
     - `check_quota(model_hint)` عبر `/Users/macm1pro/.hermes/node/bin/antigravity-usage quota --json --all-models` (أو `/tmp/agy_quota_snapshot.json`).
     - تشغيل `agy` في بيئة `HOME` معزولة خالية من `MCP` (مع ربط رمزي لمجلد المصادقة فقط حتى لا يطلب تسجيل دخول)، ودعم إرفاق ملفات محددة فقط في مجلد عمل مؤقت.
  3. `scripts/test_agy_lean_gates.py`: اختبار حتمي يتحقق من فحص الكوتة وعزل `MCP` ونجاح الاستدعاء الخفيف.

#### [x] الموجة الأولى (`Wave 1` — 3 وكلاء فرعيين بالتوازي):
1. **المهمة 1 (`person-discovery-intake` + ربطها بـ `sheikh-curation`):**
   - بناء مهارة `/Users/macm1pro/REPOS/SKILLS/person-discovery-intake/` (وربطها بـ `sheikh-curation`) تستلم **اسم الشخصية فقط** وتجلب آلياً:
     - قنوات يوتيوب الرسمية والأرشيفية، قوائم التشغيل (`Playlists`)، الفيديوهات المنفردة، والبثوث المباشرة (`Streams`) مع مددها (`duration`) وتواريخ رفعها.
     - صوتيات `Archive.org` (`archive.org/metadata/<item_id>`) وحسابات الرافعيين، وفك تيارات ملفات `PDF` الفهرسية (`جمهرة أعمال / فهارس`) لاستخراج روابط `Unlisted Playlists`.
     - كتب ومؤلفات الشخصية من `turathmcp` / الشاملة / `PDF` وربط السلاسل بالمتون المشروحة.
     - إخراج ملف `<person_id>_raw.json` معياري وموحد + `scripts/test_discovery_gates.py`.
2. **المهمة 3 (`sheikh-series-pipeline v5 — Hybrid VPS + Mac MPS`):**
   - ترقية [`/Users/macm1pro/REPOS/SKILLS/sheikh-series-pipeline/`](file:///Users/macm1pro/REPOS/SKILLS/sheikh-series-pipeline/SKILL.md) إلى الإصدار `v5.0`:
     - السكربتات الجديدة موجودة بالفعل في `sheikh-series-pipeline/scripts/` (`agy_transcribe.py` مع دعم `Archive.org` والجسر الفوري وحارس الكوتة، `vps_align_feeder.py`، `mac_align_fleet.py`، و`transcribe_selected_smallest_first.py`).
     - المطلوب: كتابة المرجع الهندسي `references/11-hybrid-vps-mac-mps-v5.md`، تحديث `SKILL.md` لتوثيق المعمارية الهجينة (`Opus 12kbps VoIP` + `Mac MPS fp16` + `plan_silence/compact_wave` + `LaunchAgent` + حارس الكوتة)، وبناء `scripts/test_pipeline_v5_gates.py` للتحقق الحتمي من جميع المكونات.
3. **المهمة 4 (`turath-pdf-to-text v2 — Pure Text & Footnotes + Adapter`):**
   - ترقية [`/Users/macm1pro/REPOS/SKILLS/turath-pdf-to-text/`](file:///Users/macm1pro/REPOS/SKILLS/turath-pdf-to-text/SKILL.md):
     - تجريد `SKILL.md` ليكون محرك استخراج بصري حرفي صافي 100% للمتون والحواشي (`pages/pNNNN.json` + `.txt`) ونقل أي مهام فهرسة/تلخيص إلى `turath-deep-indexing`.
     - بناء المحول `scripts/pdf_to_preflight_adapter.py` الذي يحول مخرجات `turath-pdf-to-text` (`pages/pNNNN.json`) تلقائياً إلى الصيغة التي يستقبلها `manifest_v4.py` في `turath-deep-indexing`، مع `scripts/test_pdf_adapter_gates.py`.

#### [x] الموجة الثانية (`Wave 2` — 3 وكلاء فرعيين بالتوازي بعد اعتماد الموجة الأولى):
4. **المهمة 2 (`sheikh-curation v2 — Automated Semantic Curation`):**
   - تطوير خط أنابيب آلي (`scripts/auto_curate_person.py`) داخل [`/Users/macm1pro/REPOS/SKILLS/sheikh-curation/`](file:///Users/macm1pro/REPOS/SKILLS/sheikh-curation/SKILL.md) يستلم `<person_id>_raw.json` وينفذ آلياً:
     - تصنيف `Unclassified`، عزل المقاطع القصيرة (`<300s`) والبروموهات والضيوف، إصلاح انقلاب الأب والابن في البثوث المنقطعة، استيفاء التواريخ الهجرية والعناوين المبتورة بعد حرف 100، منع تصفير الترقيم، وتحديد حالة السلسلة (`completed / stopped / ongoing`).
     - لا يجيز المخرج إلا بعد اجتياز `global_audit.py` بـ **`0 errors`** + `scripts/test_curation_v2_gates.py`.
5. **المهمة 5 (`turath-entity-db` داخل `turath-deep-indexing`):**
   - داخل [`/Users/macm1pro/REPOS/SKILLS/turath-deep-indexing/`](file:///Users/macm1pro/REPOS/SKILLS/turath-deep-indexing/SKILL.md):
     - بناء `scripts/ytb_to_usdb_intake.py` لإدخال سلاسل `ytb` (`.txt` + `.align.json`) في `merge_lecture.py`.
     - بناء `scripts/build_objects_sqlite.py` لتوليد قاعدة بيانات علائقية قياسية (`SQLite + FTS5`) للكائنات (`Objects`) تضم الجداول الـ 9: `sources`, `series`, `lessons_or_parts`, `passages` (مع `start_sec`, `end_sec`, `youtube_timestamp_url`), `persons` (مع الفصل الصارم بين `isnad` و`matn`), `places`, `events_chronology`, `stories_cases`, `science_gems`, `evidences`, و`matn_triangulation`.
     - بناء `scripts/test_objects_sqlite_gates.py` وتجريبه على بيانات حقيقية.
6. **المهمة 6 (`turath-embedding-gemma2`):**
   - بناء مهارة جديدة [`/Users/macm1pro/REPOS/SKILLS/turath-embedding-gemma2/`](file:///Users/macm1pro/REPOS/SKILLS/turath-embedding-gemma2/):
     - `SKILL.md` + `scripts/embed_corpus_gemma2.py` لتوليد التضمين الشعاعي المزدوج بـ **`EmbeddingGemma 2`**: متجه المتن (`vec_matn` من `embed_matn_text`) ومتجه المفهوم (`vec_concept` من `embed_concept_text`) لكل مقطع ولكل قاعدة علمية.
     - ربط المتجهات بقاعدة بيانات الكيانات (`SQLite`) وبناء محرك البحث الهجين `scripts/hybrid_search.py` (`FTS5` حرفي + `EmbeddingGemma 2` دلالي مزدوج + فلترة بالكيانات: الأعلام، الأماكن، الأحداث، الآيات/الأحاديث) + `scripts/test_embedding_gemma2_gates.py`.

#### [x] الموجة الثالثة (`Wave 3` — المايسترو الشامل والاعتماد النهائي):
7. **المهمة 7 (`person-to-knowledge-orchestrator`):**
   - بناء مهارة المايسترو [`/Users/macm1pro/REPOS/SKILLS/person-to-knowledge-orchestrator/`](file:///Users/macm1pro/REPOS/SKILLS/person-to-knowledge-orchestrator/) (`SKILL.md` + `scripts/orchestrate_person.py` + `scripts/test_orchestrator_gates.py`) التي تستلم `اسم الشخصية` وتشغّل المراحل الخمس بالتتابع المحكوم ببوابات الجودة حتى إخراج المستودع الكامل (النصوص + المحاذاة بالثانية + قاعدة بيانات الكيانات `SQLite` + الفهرس الشعاعي `EmbeddingGemma 2`).
   - تحديث [`TODO.md`](file:///Users/macm1pro/REPOS/SKILLS/TODO.md) و[`README.md`](file:///Users/macm1pro/REPOS/SKILLS/README.md) في مستودع `SKILLS` ورفع كل شيء إلى GitHub.
