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

## ٢. قواعد محمد الصارمة لحماية الكوتة (`Strict Quota Guard`)

تدمج أداة [`scripts/agy_lean.py`](./scripts/agy_lean.py) فاحص الكوتة الحي المتصل بـ:
- `/Users/macm1pro/.hermes/node/bin/antigravity-usage quota --json --all-models`
- أو اللقطة المحدثة في `/tmp/agy_quota_snapshot.json` و`/root/workspace/ytb-build/live_quota.json`.

وتطبّق قاعدتين حتميتين قبل السماح بأي استدعاء:

1. **قاعدة نافذة الـ 5 ساعات (`5h Window Floor`):**
   - يُحظر استهلاك آخر **`10%`** من كوتة الـ 5 ساعات (مخصصة حصرياً للوكيل التفاعلي الرئيسي).
   - تتوقف استدعاءات الخلفية (`background=True`) تلقائياً عند نزول الكوتة تحت **`15%`** (لترك هامش أمان `5%` فوق الـ `10%`).
2. **قاعدة الاحتياطي الأسبوعي (`Weekly Reserve Rule`):**
   - عندما يكون وقت التجديد المتبقي `timeUntilResetMs > 5.5 ساعات` (نافذة أسبوعية/متدحرجة)، يُحظر النزول تحت **`25%`** إلا إذا بقي أقل من **`12` ساعة (`< 12h`)** على موعد التجديد الأسبوعي.
3. **التبديل التلقائي للنموذج (`Smart Model Routing`):**
   - إذا طُلب نموذج من مجموعة `Claude Opus / Sonnet` وكانت كوتته تحت حد الأمان (مثل `4.71%` الحالية)، يرفض الحارس استدعاء `Claude` أو يحوله تلقائياً (عند تفعيل `--auto-fallback`) إلى `gemini-3.8-flash-high` أو `gemini-4-argon-high` (المتوفرة بنسبة `>80%`).

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
q = check_quota(model_hint="gemini", background=True)
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

## ٤. بوابة الفحص الحتمية (`Quality Gate`)

للتحقق من سلامة العزل (`0 MCP files`) ودقة حارس الكوتة (`5h Floor` + `Weekly Reserve`) ونجاح الاستدعاء الحي:

```bash
python3 /Users/macm1pro/REPOS/SKILLS/agy-lean-cli/scripts/test_agy_lean_gates.py
```
