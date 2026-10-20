---
name: agy-multi-account
description: "إدارة وتشغيل حسابات متعددة من Antigravity CLI (agy) بالتوازي أو بالتناوب على السيرفر (hermes-vps) والماك، وفحص كوتة كل حساب مجاناً (0 توكن)، وتشغيل طابور التفريغ الصوتي وتوزيعه على عدة حسابات (Ultra + Pro). استعمل هذه المهارة فوراً عند السؤال عن حسابات agy المتعددة (medmrf10, medmrf19, ...)، أو إضافة حساب ثالث/رابع، أو معرفة أين وصل طابور التفريغ وكيف يُشغّل بحساب معين."
version: 1.0.0
author: Mohamed Boumaraf
platforms: [linux, macos]
metadata:
  hermes:
    tags: [agy, multi-account, quota, transcription, profiles, medmrf10, medmrf19, hermes-vps]
    related_skills: [sheikh-series-pipeline, agy-lean-cli, agy-transcription, agy-worker-orchestration]
---

# مهارة إدارة الحسابات المتعددة لـ Antigravity (`agy-multi-account`) وطابور التفريغ على السيرفر

هذه المهارة هي المرجع الهندسي الموحّد لأي وكيل (سواء على الماك أو وكيل سلاك `Hermes` على السيرفر `hermes-vps`) للتعامل مع **عدة حسابات `agy` مفصولة** وتشغيل التفريغ الصوتي أو المهام الثقيلة عليها دون تداخل.

---

## 1. كيف يعمل فصل الحسابات (`HOME Isolation`) والفرق الحرج بين الماك ولينكس

يخزّن `agy` بيانات المصادقة والجلسات داخل `$HOME/.gemini/antigravity-cli/`:
- ملف التوكن: `$HOME/.gemini/antigravity-cli/antigravity-oauth-token`
- حالة الإعداد: `$HOME/.gemini/antigravity-cli/jetski_state.pbtxt`
- الإعدادات: `$HOME/.gemini/antigravity-cli/settings.json`

### الفرق الجوهري بين اللينكس (`hermes-vps`) والماك (`macOS`):
1. **على السيرفر `hermes-vps` (Linux) — فصل تام 100%:**
   - لا يوجد Keychain في لينكس، لذلك يعتمد `agy` حصرياً وبنسبة 100% على ملف `antigravity-oauth-token` الموجود داخل `$HOME/.gemini/antigravity-cli/`.
   - تشغيل `HOME=/root/.agy-profiles/medmrf19 /root/.local/bin/agy ...` يعزل الحساب عزلاً مطلقاً عن `HOME=/root/.agy-profiles/medmrf10` وعن `/root/.gemini`.
2. **على الماك (`macOS`) — فخ الـ Keychain وحلّه الجذري بسطر واحد:**
   - عند تسجيل الدخول لأول مرة عبر المتصفح على الماك، يحفظ `agy` التوكن في مكانين معاً:
     1. ملف البروفايل المعزول: `$HOME/.gemini/antigravity-cli/antigravity-oauth-token`
     2. مدخل واحد مشترك في **macOS Keychain** (`service="gemini", account="antigravity"`).
   - مادام هذا المدخل موجوداً في الـ Keychain، فإن أي تشغيل لـ `agy` على الماك سيقرأ من الـ Keychain أولاً ويتجاهل `$HOME`!
   - **الحل الجذري الدائم على الماك:** فور تسجيل الدخول بأي حساب جديد على الماك، احذف مدخل الـ Keychain المشترك بأمر واحد:
     ```bash
     security delete-generic-password -s gemini -a antigravity
     ```
     بمجرد حذف هذا المدخل، يتوقف `agy` عن القراءة من الـ Keychain ويعود للاعتماد 100% على ملف `antigravity-oauth-token` داخل كل `$HOME` (تماماً مثل لينكس)، فيبقى `agy` / `lss` على حساب `medmrf.10@gmail.com` ويبقى `medmrf19` على حساب `medmrf.19@gmail.com` بعزل تام 100% (وهذا ما تفعله أداة `agy_multi_pool.py` تلقائياً في كل استدعاء).

---

## 2. سجل الحسابات الحالية (`Registered Profiles`)

جميع الحسابات تُخزن بصيغة موحدة في:
- **السيرفر (`hermes-vps`):** `/root/.agy-profiles/<profile_name>/.gemini/antigravity-cli/`
- **الماك (`macOS`):** `/Users/macm1pro/.agy-profiles/<profile_name>/.gemini/antigravity-cli/`

| اسم البروفايل (`Profile`) | الإيميل | نوع الاشتراك (`Tier`) | النماذج المتاحة للتفريغ والعمل | ملاحظات |
|---|---|---|---|---|
| **`medmrf10`** | `medmrf.10@gmail.com` | **Google AI Ultra** | `gemini-3.8-flash-high`, `gemini-4-argon-high`, `gemini-3.8-flash-medium`, `claude-sonnet-4-6`, `claude-opus-4-6-thinking` | الحساب الأساسي (موجود أيضاً في `/root/.gemini`) |
| **`medmrf19`** | `medmrf.19@gmail.com` | **Google AI Pro** | `gemini-3.8-flash-high`, `gemini-3.8-flash-medium`, `gemini-3.8-flash-low`, `claude-sonnet-4-6`, `claude-opus-4-6-thinking` | **لا يتوفر فيه Argon** (`gemini-4-argon-*` خاص بـ Ultra فقط)؛ يُستخدم مع `gemini-3.8-flash-high` |

---

## 3. طريقة إضافة حساب ثالث أو رابع (`medmrfXX`) في دقيقة واحدة

1. **على الماك** (حيث يتوفر المتصفح للمصادقة):
   ```bash
   mkdir -p ~/.agy-profiles/medmrf3
   HOME=$HOME/.agy-profiles/medmrf3 agy
   ```
   سجّل الدخول في المتصفح بالحساب الثالث، ثم اخرج (`Ctrl+C`).
2. **مزامنة الحساب الجديد فوراً إلى السيرفر `hermes-vps`:**
   ```bash
   python3 /Users/macm1pro/REPOS/SKILLS/agy-multi-account/scripts/agy_multi_pool.py --sync-to-vps
   ```
3. **التحقق من عمل جميع الحسابات وكوتتها على السيرفر (بصفر توكن):**
   ```bash
   python3 /root/workspace/SKILLS/agy-multi-account/scripts/agy_multi_pool.py --status
   ```

---

## 4. فحص الكوتة الحية لكل حساب مجاناً (`0 Tokens`)

لا تطلق أبداً محادثة LLM لفحص الكوتة! استخدم أمر السلاش المدمج `/usage` في وضع الطباعة:
```bash
HOME=/root/.agy-profiles/medmrf19 /root/.local/bin/agy -p '/usage' --output-format json
```
أو عبر أداة المجمع الموحدة التي تفحص كل الحسابات في `/root/.agy-profiles/*` وتطبع جدولاً كاملاً:
```bash
python3 /root/workspace/SKILLS/agy-multi-account/scripts/agy_multi_pool.py --status
```

---

## 5. أين وصل طابور التفريغ الصوتي على `hermes-vps` وكيف يُدار؟

### أ. الخريطة الكاملة لملفات طابور التفريغ على `hermes-vps`:
- **ملف السلاسل المختارة المرجعي (`17` شيخاً):**
  `/root/workspace/cheikh-exports/cheikh-selected-curated-2026-10-17.json`
- **مجلد المخرجات النصية والصوتية:**
  `/root/workspace/ytb/<sheikh_slug>/<series_key>/` (يضم حالياً **`6,579+` ملف `.txt`** صالحاً).
- **سكربت التفريغ المفرد (يدعم تعدد الحسابات):**
  `/root/workspace/SKILLS/sheikh-series-pipeline/scripts/agy_transcribe.py`
- **سكربت طابور السلاسل (من الأصغر إلى الأكبر):**
  `/root/workspace/SKILLS/sheikh-series-pipeline/scripts/transcribe_selected_smallest_first.py`
- **ملف حالة الطابور الحي:**
  `/root/workspace/ytb-build/transcribe_selected_state.json`
- **خدمة systemd:**
  `transcribe-smallest-first.service` (تتوقف تلقائياً عند وجود `/root/workspace/ytb-build/TRANSCRIBE_DRAIN_COMPLETE.flag`).

### ب. الإحصائية الدقيقة لطابور التفريغ (حتى 20 أكتوبر 2026):
1. **السلاسل المكتملة `100%`:** **`231` سلسلة** (اكتملت جميع السلاسل التي كانت نسبتها `>= 70%` بالكامل!).
2. **السلاسل المفرغة جزئياً (`1% .. 69.2%`):** **`52` سلسلة** (فيها `2,401` درس متبقٍّ / `2,360` ساعة)، منها **`26` سلسلة في الشريحة `50.0% .. 69.2%`** على وشك الاكتمال، وأقربها:
   - `sayed__s015` (أحمد السيد — مقاصد مدارج السالكين): منجز `69.2%` — متبقٍّ **`8` دروس فقط** (`7.47` ساعة).
   - `samarrai__s026` (فاضل السامرائي — اللمسات البيانية في سورة الإسراء): منجز `68.8%` — متبقٍّ **`5` دروس فقط** (`0.71` ساعة = `42` دقيقة!).
   - `alihani__s012` (علي هاني العقرباوي — شرح الفاكهي على قطر الندى): منجز `68.2%` — متبقٍّ **`7` دروس** (`7.45` ساعة).
   - `asimi__s040` (أدهم العاسمي — أولئك الذين هدى الله): منجز `68.0%` — متبقٍّ **`8` دروس** (`2.02` ساعة).
   - `asimi__s042` (أدهم العاسمي — شرح تاج العروس): منجز `68.0%` — متبقٍّ **`8` دروس** (`2.28` ساعة).
3. **السلاسل الجديدة غير الملموسة (`0%`):** **`135` سلسلة** (`15,737` درساً)، تبدأ أصغرها من `6` دروس فقط (`sariri__s016`: دورة الدلالات اللفظية لمولود السريري — `6` دروس).

### ج. كيف تفرّغ درساً أو سلسلة بحساب معين (`medmrf19`) أو بمجمع الحسابات (`Multi-Account Pool`)؟

1. **لتفريغ درس أو سلسلة بحساب واحد محدد (مثلاً `medmrf19` لمعايرة الكوتة):**
   مرر `--agy-profile medmrf19` أو المتغير البيئي `AGY_PROFILE=medmrf19`:
   ```bash
   AGY_PROFILE=medmrf19 python3 /root/workspace/SKILLS/sheikh-series-pipeline/scripts/agy_transcribe.py \
     /root/workspace/ytb/fadhel-samarrai/s026 \
     --only 012 \
     --model gemini-3.8-flash-high
   ```
2. **لمعايرة استهلاك كوتة حساب (`--calibrate`) على درس واحد وقياس الفرق قبل/بعد تلقائياً:**
   ```bash
   python3 /root/workspace/SKILLS/agy-multi-account/scripts/agy_multi_pool.py \
     --calibrate medmrf19 \
     --series-dir /root/workspace/ytb/fadhel-samarrai/s026 \
     --only 012 \
     --model gemini-3.8-flash-high
   ```
3. **لتشغيل التفريغ الموزّع على عدة حسابات بالتناوب (`Round-Robin Multi-Account Pool`):**
   مرر قائمة الحسابات في `AGY_PROFILES=medmrf10,medmrf19`:
   ```bash
   AGY_PROFILES=medmrf10,medmrf19 MIN_COMPLETION_PCT=50.0 \
     python3 /root/workspace/SKILLS/sheikh-series-pipeline/scripts/transcribe_selected_smallest_first.py
   ```
   سيقوم `agy_transcribe.py` بتوزيع المقاطع (`chunks`) بالتناوب بين الحسابات النشطة التي تتجاوز كوتتها الحد الآمن، مع عزل مجلدات الأقفال (`/tmp/agy_global_slots_<profile>`) ومجلدات الجلسات لكل حساب بشكل مستقل تماماً.
