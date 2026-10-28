---
name: agy-lean-cli
description: استدعاء أداة Antigravity CLI (agy) في بيئة HOME معزولة خالية تماماً من مخططات MCP والإضافات والمهارات لتوفير نحو 38,000 توكن في كل نداء، مع تنظيف آمن ومعزول لكل عملية.
---

# مهارة الاستدعاء الخفيف والمعزول لـ Antigravity (`agy-lean-cli`)

## 1. المشكلة الهندسية والحل المعماري

1. عند تشغيل `agy -p` في البيئة الافتراضية للمستخدم، تقوم الأداة تلقائياً بتحميل جميع خوادم ومخططات `MCP` المعرّفة في إعدادات المستخدم (نحو `38,000` توكن في كل نداء)، بالإضافة إلى جميع الإضافات (`plugins`) والمهارات (`skills`) والقواعد (`GEMINI.md` و`rules/`)، مع فهرسة ملفات مجلد العمل الحالي.
2. يعالج السكربت `scripts/agy_lean.py` هذا الهدر عبر بناء بيئة `HOME` مؤقتة ومعزولة (`prepare_lean_home`) لكل عملية على حدة، تربط رمزياً (`Symlink`) ملفات المصادقة والترخيص فقط (`oauth`, `installation_id`, `jetski_state.pbtxt`, ومجلد `Library` على نظام `macOS` للوصول إلى `Keychain`).
3. يولّد السكربت ملفَي `config.json` و`settings.json` نظيفين خاليين تماماً من `mcp_config.json` و`plugins` و`skills` و`rules`، ويشغّل `agy` داخل مجلد عمل مؤقت خاص بالعملية (`Temporary Workspace`) مع الخيارات `--disable-slash-commands` و`--dangerously-skip-permissions` و`--output-format json`.
4. في كتلة `finally`، تنظف كل عملية ملفات جلستها ومجلدها المؤقت الخاص بها فقط (`_cleanup_lean_conv`)، مما يمنع تضخم القرص ويحمي العمليات المتوازية من أي تداخل أو سباق بيانات (`Race Condition`).

## 2. الضوابط الهندسية المدمجة

1. الاعتماد حصرياً على `Path.home()` و`shutil.which("agy")` لاكتشاف المسارات تلقائياً دون أي مسارات محلية صلبة.
2. عزل كل استدعاء في مجلد `HOME` مؤقت ومجلد عمل مؤقت مستقلين افتراضياً، مع دعم تمرير مجلد عمل محدد عبر `--workspace` أو ملفات مرفقة عبر `--file`.
3. استخلاص الاستجابة النصية وإحصاءات الاستهلاك ومعرف الجلسة بدقة عبر `_extract_agy_json`.
4. إسقاط خيار `--effort` تلقائياً إذا كان النموذج المحدد من عائلة `Claude` أو يتضمن مستوى الجهد في اسمه.

## 3. واجهة الاستخدام (`CLI & Python API`)

### 1. الاستخدام من سطر الأوامر (`CLI`)

```bash
# 1. استدعاء نصي خفيف ومعزول (0 MCP tokens) في وضع الاستشارة الافتراضي (--mode ask)
python3 scripts/agy_lean.py -p "اشرح الفرق بين العام والمطلق باختصار"

# 2. تحديد نموذج ومجلد عمل ومهلة زمنية مع إخراج JSON
python3 scripts/agy_lean.py \
  -p "راجع بنية المشروع باختصار" \
  --model gemini-3.8-flash-high \
  --workspace /tmp/my_workspace \
  --timeout 120 \
  --json

# 3. إرفاق ملف أو أكثر داخل مجلد العمل المؤقت المعزول
python3 scripts/agy_lean.py \
  -p "تحقق من سلامة الحواشي في الملف المرفق" \
  --file /path/to/sample.json \
  --mode ask
```

### 2. الاستخدام كمكتبة بايثون (`Python API`)

```python
from agy_lean import run_agy_lean

res = run_agy_lean(
    prompt="لخص القاعدة الأصولية في جملة واحدة.",
    model="gemini-3.8-flash-high",
    mode="ask",
    files=["/path/to/sample.txt"],
    timeout_s=120,
)
if res["ok"]:
    print(res["response"])
```
