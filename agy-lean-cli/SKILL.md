---
name: agy-lean-cli
description: استدعاء أداة Antigravity CLI (agy) في بيئة معزولة خالية تماماً من مخططات MCP والإضافات والمهارات (~0 توكن إضافي بدلاً من ~38,000 توكن)، مع حارس الكوتة الحي الصارم (حماية 10% لنافذة الـ5 ساعات و25% للاحتياطي الأسبوعي) وتنظيف تلقائي لقواعد بيانات الجلسات المؤقتة.
---

# مهارة الاستدعاء الخفيف والمعزول لـ Antigravity (`agy-lean-cli`)

## ١. المشكلة الهندسية والحل المعماري

عند تشغيل `agy -p "..."` في البيئة الافتراضية للمستخدم (`HOME=/Users/macm1pro` أو `/root`)، يقوم `agy` تلقائياً بتحميل:
1. جميع خوادم ومخططات **`MCP`** المعرّفة في `~/.gemini/config/mcp_config.json` و`~/.gemini/antigravity-cli/mcp/` (~38,000 توكن في كل نداء).
2. جميع الإضافات (`plugins`) والمهارات الشاملة (`skills`) والقواعد (`GEMINI.md` و`rules/`).
3. فهرسة ملفات مجلد العمل الحالي إذا لم يُعزل في مجلد مؤقت فارغ.

### الحل في `agy-lean-cli`:
بناء بيئة `HOME` معزولة (`Lean Isolated HOME`) تربط رمزياً (`Symlink`) **ملفات المصادقة والترخيص فقط** (`oauth`, `installation_id`, `jetski_state.pbtxt`, `Library/Keychains` على الماك) مع توليد `config.json` و`settings.json` نظيفين خاليين تماماً من:
- `mcp_config.json` و`mcp/`
- `plugins/` و`skills/` و`rules/` و`GEMINI.md`

وتشغيل `agy` داخل مجلد عمل مؤقت (`Temporary Workspace`) لا يضم إلا الملفات المحددة صراحةً عبر `--file` مع الخيارات:
- `--disable-slash-commands`
- `--mode plan` (أو المرادف `--mode ask` للاستشارات النصية والقراءة فقط دون تعديل)
- `--dangerously-skip-permissions`
- `--output-format json`

---

## ٢. قواعد محمد الصارمة لحماية الكوتة (`Strict Dual-Window Quota Guard`)

تدمج أداة [`scripts/agy_lean.py`](./scripts/agy_lean.py) فاحص الكوتة الحي المتصل بـ:
- `/root/workspace/ytb-build/live_quota.json` (تلقائياً على السيرفر `hermes-vps` حيث لا تتوفر كوكيز سطح المكتب مباشرةً، مع فحص مزدوج لعمر الملف `mtime` وطابع `timestamp` الداخلي `max_stale_age_s=1800s`).
- `/Users/macm1pro/.hermes/node/bin/antigravity-usage quota --json --all-models` (على الماك) أو اللقطة المحلية `/tmp/agy_quota_snapshot.json`.

وتطبّق ثلاث قواعد حتمية قبل السماح بأي استدعاء:

1. **قاعدة نافذة الـ 5 ساعات (`5h Window Floor`):**
   - يُحظر استهلاك آخر **`10%`** من كوتة الـ 5 ساعات (مخصصة حصرياً للوكيل التفاعلي الرئيسي).
   - تتوقف استدعاءات الخلفية (`background=True`) تلقائياً عند نزول الكوتة تحت **`15%`** (لترك هامش أمان `5%` فوق الـ `10%`).
2. **قاعدة الاحتياطي الأسبوعي (`Weekly Reserve Rule`):**
   - عندما يكون وقت التجديد المتبقي `timeUntilResetMs > 5.5 ساعات` (نافذة أسبوعية/متدحرجة)، يُحظر النزول إلى **`<= 25%`** (يُشترط `> 25%`) إلا إذا بقي **`<= 12` ساعة** على موعد التجديد الأسبوعي (مع بقاء سقف الـ`15%`/`10%` محمياً حتى في آخر 12 ساعة).
   - إذا وُجدت نافذتان (`5h` + `Weekly`) لنفس الفئة، يطبّق `check_quota()` و`select_best_model()` الحارس المزدوج ويمنع الاستدعاء إذا اختلّ أيٌّ من الشرطين.
3. **التبديل التلقائي متعدد البدائل (`Multi-Hop Smart Model Routing`):**
   - إذا طُلب نموذج محظور الكوتة (مثل `Claude Opus / Sonnet` عند `4.71%`)، يحوّله `select_best_model()` تلقائياً عبر سلسلة البدائل (`gemini-3.8-flash-high` ثم `gemini-4-argon-high` ثم `gemini-3.8-flash-medium`) إلى أعلى نموذج آمن متاح.
4. **التنظيف الحتمي الشامل بعد كل استدعاء (`Deterministic Session & DB Cleanup`):**
   - ينظف `_cleanup_lean_conv()` تلقائياً داخل `finally` (حتى عند حدوث `TimeoutExpired`): مجلدات `brain/*`، `conversations/*`، `annotations/*`، `presence/*`، ملفات `implicit/<uuid>.pb` ذات المعرفات المستقلة، قواعد البيانات المتضخمة (`conversation_summaries.db*` و`jetbox_summaries_proto.pb*.tmp`)، وأي ملف `.gemini/config/mcp_config.json` فارغ ينشئه `agy` تلقائياً عند الإقلاع على Linux.

---

## ٣. واجهة الاستخدام (`CLI & Python API`)

### أ) الاستخدام من سطر الأوامر (`CLI`)

```bash
# 1. فحص حالة الكوتة الحية وقرار الحارس لكل المجموعات
python3 /Users/macm1pro/REPOS/SKILLS/agy-lean-cli/scripts/agy_lean.py --check-quota

# 2. استدعاء نصي خفيف ومعزول (0 MCP tokens) في وضع القراءة/الاستشارة (--mode ask)
python3 /Users/macm1pro/REPOS/SKILLS/agy-lean-cli/scripts/agy_lean.py \
  -p "استخرج الأعلام المذكورين في هذا النص بصيغة JSON" \
  --mode ask \
  --model gemini-3.8-flash-high

# 3. فحص ملف واحد أو عدة ملفات معزولة في مجلد مؤقت
python3 /Users/macm1pro/REPOS/SKILLS/agy-lean-cli/scripts/agy_lean.py \
  -p "راجع هذا الملف وتحقق من سلامة الحواشي" \
  --file /path/to/page_0001.json \
  --mode ask \
  --json
```

### ب) الاستخدام كمكتبة بايثون (`Python API`)

```python
from agy_lean import check_quota, run_agy_lean

# 1. التحقق من الكوتة
q = check_quota(model_hint="gemini-3.8-flash-high", background=True)
if not q["safe"]:
    raise RuntimeError(q["reason"])

# 2. استدعاء رشيق ومعزول
res = run_agy_lean(
    prompt="لخص القاعدة الأصولية في جملة واحدة.",
    model="gemini-3.8-flash-high",
    mode="ask",
    files=["/path/to/sample.txt"],
    background=True,
)
print(res["response"])
```

---

## ٤. بوابة الفحص الحتمية رباعية الطبقات (`4-Layer Quality Gate`)

للتحقق من:
1. منطق الحارس المزدوج (`5h Floor >= 15%` + `Weekly Reserve > 25%`) والتوجيه الذكي متعدد البدائل.
2. أولوية قراءة `/root/workspace/ytb-build/live_quota.json` وفحص تقادم اللقطة (`Staleness Check`).
3. سلامة عزل `HOME` (`0 MCP files`) والتنظيف الحتمي الشامل لملفات `brain/*` و`implicit/*.pb` و`conversation_summaries.db*`.
4. نجاح الاستدعاء الحي ونظافة القرص بعده (`0` بقايا):

```bash
python3 /Users/macm1pro/REPOS/SKILLS/agy-lean-cli/scripts/test_agy_lean_gates.py
```
