---
name: agy-multi-account
description: "إدارة وتشغيل حسابات متعددة من Antigravity CLI (agy) على السيرفر (hermes-vps) والماك، وفحص كوتة كل حساب مجاناً (0 توكن)، واختيار حساب الـ Pro الأعلى كوتة أسبوعية للتفريغ تلقائياً. استعمل هذه المهارة فوراً عند التعامل مع حسابات agy الثلاثة (medmrf10 الرئيسي، وحسابَي الـ Pro للتفريغ: medmrf19 و brain)."
version: 1.1.0
author: Mohamed Boumaraf
platforms: [linux, macos]
metadata:
  hermes:
    tags: [agy, multi-account, quota, transcription, profiles, medmrf10, medmrf19, brain, hermes-vps]
    related_skills: [sheikh-series-pipeline, agy-lean-cli, agy-transcription, agy-worker-orchestration]
---

# مهارة إدارة الحسابات المتعددة لـ Antigravity (`agy-multi-account`) وسياسة التفريغ الصوتي

هذه المهارة هي المرجع الهندسي الموحّد لأي وكيل (سواء على الماك أو على السيرفر `hermes-vps`) للتعامل مع حسابات `agy` الثلاثة المعزولة وتطبيق السياسة الصارمة لتوزيع المهام والكوتة بينها.

---

## 1. سجل الحسابات المعتمدة والسياسة التشغيلية الصارمة

تُخزَّن جميع الحسابات المعزولة في المسار الموحد:
- **على السيرفر (`hermes-vps`):** `/root/.agy-profiles/<profile_name>/.gemini/antigravity-cli/`
- **على الماك (`macOS`):** `/Users/macm1pro/.agy-profiles/<profile_name>/.gemini/antigravity-cli/`

### الحسابات الثلاثة المسجّلة:

1. **`medmrf10` (`medmrf.10@gmail.com` — Google AI Ultra) — الحساب الرئيسي (`Main Account`):**
   - **الدور:** الحساب الرئيسي للمستخدم والوكيل التفاعلي، مخصّص للجلسات الحوارية، التخطيط، البحث العلمي العميق، وإنشاء الخطب والدروس العلمية المركّبة (`Claude Opus 4.6` / `Gemini 3.1 Pro High`).
   - **قاعدة الحماية الصارمة:** **يُمنع استخدام `medmrf10` افتراضياً في التفريغ الصوتي (`agy_transcribe.py`) أو المهام الخلفية الغزيرة** حفاظاً على حصته للمهام العلمية التفاعلية.

2. **`medmrf19` (`medmrf.19@gmail.com` — Google AI Pro) — حساب التفريغ الافتراضي (أ):**
   - **الدور:** حساب عمل ثقيل (`Workhorse Pro`) للتفريغ الصوتي (`gemini-3.8-flash-high`) والفهرسة والمهام الآلية.
   - **الاختصار في الطرفية:** `medmrf19`

3. **`brain` (`brainthomas555@gmail.com` — Google AI Pro) — حساب التفريغ الافتراضي (ب):**
   - **الدور:** حساب عمل ثقيل (`Workhorse Pro`) للتفريغ الصوتي (`gemini-3.8-flash-high`) والفهرسة والمهام الآلية.
   - **الاختصار في الطرفية:** `brain`

---

## 2. القاعدة الافتراضية للتفريغ الصوتي (`Default Transcription Policy`)

- **الحسابان الافتراضيان للتفريغ هما حسابا الـ Pro (`medmrf19` و `brain`) دون أي تفرقة أو تفضيل مسبق بينهما.**
- **معيار الاختيار التلقائي:** قبل كل مهمة أو دفعة تفريغ، يتم فحص الكوتة الحية (`/usage` بصفر توكن) لكلٍّ من `medmrf19` و `brain`، و**يُختار تلقائياً الحساب الذي يملك أعلى كوتة أسبوعية متبقية (`gemini-weekly`)** (بشرط أن تكون نافذة الـ 5 ساعات `gemini-5h >= 8%`).
- **الهدف الهندسي من هذه القاعدة:** ضمان استغلال الحصة الأسبوعية لكلا حسابَي الـ Pro (`medmrf19` و `brain`) بالتوازن الكامل قبل حلول تاريخ التجديد الأسبوعي لكل منهما، دون ترك أحدهما خاملاً بينما يُستنزف الآخر.
- **التنفيذ الآلي في الكود:**
  - داخل `agy_transcribe.py`: عند عدم تمرير `--agy-profile` (أو تمرير `--agy-profile auto` أو `--agy-profile pro`)، يقوم `_pick_highest_weekly_pro_profile()` تلقائياً بفحص `medmrf19` و `brain` واختيار صاحب أعلى `gemini-weekly` (مع تحديث الكاش كل 180 ثانية ليبدّل تلقائياً بينهما أثناء العمل الطويل).
  - عبر أداة `agy_multi_pool.py`:
    ```bash
    python3 /Users/macm1pro/REPOS/SKILLS/agy-multi-account/scripts/agy_multi_pool.py --best-transcribe-profile
    ```

---

## 3. كيف يعمل عزل الحسابات (`HOME Isolation`) وحلّ Keychain الماك

يعتمد `agy` على الملف `$HOME/.gemini/antigravity-cli/antigravity-oauth-token`.
- **على لينكس (`hermes-vps`):** مجرّد تمرير `HOME=/root/.agy-profiles/<profile>` يعزل الحساب عزلاً مطلقاً بنسبة 100%.
- **على الماك (`macOS`):** عند تسجيل الدخول عبر `/login`، يكتب `agy` التوكن في `macOS Keychain` المشترك (`service="gemini", account="antigravity"`). لذلك:
  1. دالة `_agy_profile_run` المدمجة في `~/.zshrc` (للأوامر `medmrf10`، `medmrf19`، `brain`) تسحب التوكن تلقائياً من الـ Keychain إلى ملف البروفايل المعزول وتحذف مدخل الـ Keychain المشترك فور الخروج.
  2. كما يقوم `agy_multi_pool.py` تلقائياً بتشغيل `security delete-generic-password -s gemini -a antigravity` لضمان عدم طغيان أي حساب على الآخر.

---

## 4. الأوامر السريعة لفحص الكوتة والمزامنة بين الماك والـ VPS

1. **فحص كوتة جميع الحسابات الثلاثة (`medmrf10`, `medmrf19`, `brain`) ومعرفة المرشح الأعلى للتفريغ (بصفر توكن):**
   ```bash
   # على الماك:
   python3 /Users/macm1pro/REPOS/SKILLS/agy-multi-account/scripts/agy_multi_pool.py --status

   # على السيرفر hermes-vps:
   python3 /root/workspace/SKILLS/agy-multi-account/scripts/agy_multi_pool.py --status
   ```

2. **الحصول على اسم حساب الـ Pro الأعلى كوتة أسبوعية للتفريغ برمجياً:**
   ```bash
   python3 /root/workspace/SKILLS/agy-multi-account/scripts/agy_multi_pool.py --best-transcribe-profile
   ```

3. **مزامنة جميع البروفايلات (`medmrf10`, `medmrf19`, `brain`) من الماك إلى السيرفر `hermes-vps`:**
   ```bash
   python3 /Users/macm1pro/REPOS/SKILLS/agy-multi-account/scripts/agy_multi_pool.py --sync-to-vps
   ```

4. **تشغيل التفريغ الصوتي (`agy_transcribe.py`) بالوضع الافتراضي الذكي (يختار تلقائياً الأعلى أسبوعياً بين `medmrf19` و `brain`):**
   ```bash
   python3 /root/workspace/SKILLS/sheikh-series-pipeline/scripts/agy_transcribe.py \
     /root/workspace/ytb/<sheikh>/<series> \
     --model gemini-3.8-flash-high
   ```
