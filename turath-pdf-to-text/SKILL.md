---
name: turath-pdf-to-text
description: >-
  v2.0 (Pure Verbatim Text & Footnotes Engine + Pre-Flight v4 Adapter). Use when converting scanned or digital Arabic heritage PDF books, lithographs, Bulaq/Azhari framed Hashiyas, manuscripts, or multi-column indexes into 100% pure verbatim structured text and footnotes (pages/pNNNN.json + .txt, book_matn.txt with [ص: N], footnotes.json, pages_preflight.json, and Pre-Flight v4 source_snapshots for turath-deep-indexing manifest_v4.py & fn_linker_v4.py, plus SQLite + FTS5 archive) via agy CLI (Gemini 3.8 Flash Vision), with adaptive 2-band geometric splitting (2.4x), edge-safe scipy.ndimage despeckling, 90-degree CW vertical margin rotation, view_file 33.5x token lock, 5 deterministic quality gates, 2800px microscopic focal zoom verification, and 100% Zero-Loss Check.
version: 2.0.0
author: Mohamed Boumaraf, Hermes Agent
license: MIT
platforms: [linux, macos]
metadata:
  hermes:
    tags: [pdf, ocr, vision, arabic, turath, gemini, agy, preflight-v4, adapter, zero-loss, sqlite, fts5, toc, hashiya, bulaq, footnotes, diacritics, focal-zoom]
    related_skills: [turath-deep-indexing, sheikh-series-pipeline]
---

# مهارة `turath-pdf-to-text v2.0`: محرك الاستخراج البصري الحرفي الصافي ١٠٠٪ للمتون والحواشي + محول `Pre-Flight v4` المباشر (`Pure Verbatim Text & Footnotes Engine + Pre-Flight v4 Adapter`)

هذه المهارة تمثل **المواصفة الهندسية القياسية والمحرك التنفيذي الموحد (الإصدار `v2.0`)** لتحويل كتب التراث العربي المصورة (`PDF`، سواء كانت طبعات حجرية/أزهرية محاطة بجدول، أو طبعات محققة كثيفة التشكيل والشعر والحواشي، أو مسحاً ثنائياً قديماً `JBIG2Decode`، أو ملفات ذات طبقة OCR مدمجة فاسدة) إلى **نص عربي حرفي صافي مهيكل بدقة ١٠٠٪ للمتون والطرر والحواشي وأرقام الصفحات (`pages/pNNNN.json` + `pages/pNNNN.txt`)**، مع **محول توافقي مباشر (`scripts/pdf_to_preflight_adapter.py`)** يربط المخرجات آلياً وبفحص حفظ حرفي صارم (`100% Zero-Loss Check`) مع `manifest_v4.py` و`fn_linker_v4.py` في مهارة `turath-deep-indexing`، بالإضافة إلى بناء قاعدة البيانات الأرشيفية الشجرية (`<slug>.db` + `toc.json` + `<slug>.md` + `<slug>_pages.md`).

---

## 0. الفصل المعماري الصارم (`TURATH_FACTORY.md` — Layer 1 vs. Layer 2)

وفق معمارية مصنع التراث (`TURATH_FACTORY.md`)، تلتزم هذه المهارة (`v2.0`) بالفصل الهندسي الحاسم بين طبقتين:

| الطبقة في المصنع | المهارة المسؤولة | المهمة الحصرية وحدود المسؤولية | المخرجات القياسية |
| :--- | :--- | :--- | :--- |
| **الطبقة ١ (`Layer 1`)** | **`turath-pdf-to-text v2.0`** | **الاستخراج البصري الحرفي الصافي 100%** للمتون، والطرر/المتون العمودية المدارة `90° CW`، والحواشي السفلية، وأرقام الصفحات دون إقحام أي مهام تلخيص أو فهرسة موضوعية. | `pages/pNNNN.json` + `pages/pNNNN.txt` + أرشيف `<slug>.db` |
| **جسر التحويل (`Adapter`)** | **[`scripts/pdf_to_preflight_adapter.py`](./scripts/pdf_to_preflight_adapter.py)** | تحويل `pages/pNNNN.json` بأمان حرفي `100%` (`Zero-Loss Check`) إلى هيكل المدخلات القياسي لـ `Pre-Flight v4` مع علامات الصفحات `[ص: N]` وفصل المتن عن الحواشي واستدعاء `manifest_v4.py`. | `book_matn.txt` + `footnotes.json` + `pages_preflight.json` + `source_snapshots/<id>/0*.json` + `adapter_manifest.json` |
| **الطبقة ٢ (`Layer 2`)** | **`turath-deep-indexing`** | استقبال مخرجات المحول عبر `manifest_v4.py` و`fn_linker_v4.py` لتنفيذ الفحص الاستباقي، وربط الحواشي بـ `LCS`، والفهرسة الموضوعية العميقة، والتلخيص. | `round_manifest_r4_r10.json` + `raw_round{N}_books.json` + بطاقات الفهرسة العميقة |

> **ملاحظة تشغيلية:** جميع السكربتات في `scripts/` مكتفية ذاتياً (`Self-Contained`) وتعمل على كل من **الماك (`macOS`)** و**الخادم (`Linux VPS`)** مع دعم نقاط الحفظ والاستئناف التلقائي لكل صفحة (`pages/pNNNN.json` + `pages/pNNNN.txt`).

---

## 1. الفلسفة الحاكمة: لماذا يفشل الاستدعاء الساذج للرؤية وكيف حسمناه هندسياً؟

أثبتت سلسلة التجارب المعملية الأربع عشرة (`Exp 1–14`) على 8 كتب تراثية حقيقية أن إرسال ملف `.pdf` أو صورة صفحة كاملة مباشرةً إلى النموذج يؤدي حتماً إلى **تصحيف النقاط المزدحمة، وسقوط بعض الحواشي، وتضخم التوكنات بمقدار 33.5 ضعفاً (`545,640` توكن/صفحة)**، وأن الاكتفاء بملف نصي مقسّم بالصفحات يكسر **66%–100%** من الجمل العابرة للصفحات ويثير تضارباً في **64.7%** من أرقام الحواشي عند تجميع الأبواب. لذلك يقوم هذا الخط على **سبع ركائز هندسية وحتمية لا تقبل التنازل**:

1. **منع تمرير `.pdf` مباشرةً والاعتماد على الرندر الرمادي المتكيف مع العرض الأصلي (`1650–1800px`):**
   - تمرير ملف `.pdf` مباشرةً أبطأ بمرتين (`98–115ث` مقابل `44–51ث`)، ويُسقط أرقام الصفحات العلوية، وعند تجميع عدة صفحات في PDF واحد يصحّف الكلمات المشكولة (`ضَمِرَتْ` ← `صَمَرَتْ`، `أَثْبَتُوكَ` ← `أَنْبَتُوكَ`).
   - الأبعاد الاسمية لصفحة PDF (`page.rect`) في كتب `JBIG2Decode` غالباً ما تكون صغيرة (`372×578 pt`) بينما دقة المسح المدمجة داخلها `1622×2480 px` (`314 DPI`) أو `3270×4728 px` (`600 DPI`). استخدام `dpi=150` ثابت يتلف **50%–75%** من البكسلات؛ لذا يحسب المحرك دائماً معامل التكبير من العرض المستهدف: `zoom = target_width / page.rect.width`.
2. **التنظيف الآمن لغبار المسح مع حماية الطرر الجانبية (`Edge-Safe Connected-Component Despeckling`):**
   - **89.7%** من المكونات المتصلة السوداء في صفحات `JBIG2` الممسوحة (`~6,500–7,500` شائبة في الصفحة الواحدة) هي ذرات غبار مسح معزولة (`area <= 5px`).
   - يزيل المحرك عبر `scipy.ndimage.label` في `~75ms` جميع الشوائب `<= 5px` الواقعة خارج هالة حماية مضخمة بـ `3px` حول الحروف (`binary_dilation`)، مما يخفض حجم PNG بنسبة **28%** ويمنع التباس الغبار بالنقاط أو السكون.
   - **حماية الطرر الجانبية:** لا يمسح المحرك من حواف الصفحة إلا خطوط الظل السوداء الطويلة (`comp_h > 120px` يميناً/يساراً أو `comp_w > 180px` أعلى/أسفل)، مما يحمي إشارات أجزاء المخطوطات القريبة من الحافة مثل `[I/8]` و`[٤ ب]` من البتر.
3. **التوجيه البصري الآلي للتخطيطات والشطر الأفقي عند وادي الفراغ (`CV Layout Router & 2-Band Split`):**
   - الصفحة العمودية الكاملة (`1650×2557`) يصغّرها مشفّر الرؤية الداخلي على ضلعها الأطول (`2557 -> ~1536`)، فيسحق عرض السطر إلى `~990px` ويفقد **62%** من مساحة البكسلات.
   - يصنّف `analyze_and_slice_page()` كل صفحة حتمياً في **`< 15ms`** إلى أربعة مسارات:
     * **`blank_or_sparse` (`ink_ratio < 0.004`):** تخطي استدعاء النموذج كلياً (`0.1s`، `0` توكن).
     * **`standard_single_col`:** شطر الصفحة أفقياً عند أنظف وادي فراغ بين السطور قرب المنتصف (`40%..62%` بعيداً عن خط الحاشية) مع هامش تداخل `18px` إلى شطرين (`@band1_top.png` + `@band2_bot.png`)، مما يضاعف كثافة البكسلات الفعلية **2.4 مرة** ويقضي على تصحيف الشعر المشكول.
     * **`two_column`:** عند رصد خط عمودي فاصل أو فراغ مركزي في الفهارس، تُشطر الصفحة **عمودياً** إلى `@col1_right.png` و`@col2_left.png` لمنع القفز الأفقي بين العمودين.
     * **`framed_hashiya`:** عند رصد جدول بولاقي/أزهري مزدوج الإطار، يقص داخل الجدول إلى `@box_top.png` و`@box_bot.png`، ويقص الهامش الخارجي **ويديره 90° مع عقارب الساعة (`np.rot90(crop, k=3)`)** في `@margin_upright.png` ليقرأ النموذج المتن العمودي أفقياً بدقة 100% وفي `36.7s` بدل انتهاء المهلة!
4. **قفل `view_file` المتوازي في جولة واحدة مع `--json-schema` (خفض التوكنات `33.5x`):**
   - يعمل `agy` داخل مجلد مؤقت معزول (`os.path.realpath(tmpdir)`) مع أمر صريح باستدعاء `view_file` في خطوة متوازية واحدة لجميع شطور الصفحة، وحظر صريح لأدوات `run_command` و`turathmcp` وأدوات البحث، مع تمرير `--json-schema` و`--disable-slash-commands`.
   - يمنع هذا القفل استدعاء `turathmcp` في الخلفية (الذي كان يستهلك `545,640` توكن)، ويقضي على تسرب روابط الملفات والمقدمات الحوارية، ويحسم الاستخراج في جولة واحدة (`num_turns = 1`، `cache_read_tokens = 16k–28k`).
5. **بوابات الجودة الحتمية الخمس + حلقة التكبير البؤري المجهري المدمجة (`Batched 2800px Focal Zoom`):**
   - تمر مخرجات المرحلة الأولى فوراً عبر 5 بوابات فحص حتمية (`< 5ms`): تطبيع الأرقام الفارسية (`U+06F0..U+06F9`)، فحص التغطية السطرية، فحص تطابق خط الحاشية وأرقام الإحالات بين المتن والهوامش (`matn_markers == fn_markers` مع استثناء أرقام الآيات داخل `﴿...﴾`)، فحص توازن أقواس الآيات `﴿...﴾`، وفحص قائمة الكلمات المشتبه بها `uncertain_words`.
   - عند رصد أي كلمة مشتبه بها أو عدم تطابق في الحواشي، يحدد المحرك موقع السطر المقابل في المسقط البصري (`±2 سطر`)، ويقتطع شريحة مجهرية بعرض **`2800px` (`~550 DPI`)** مباشرةً من الـ PDF، ويفحص جميع الشرائح المشتبه بها في الصفحة في **نداء متوازٍ واحد (`Batched Stage 2`)** عبر `gemini-3.8-flash-high` ثم يرقّع السطر المصحح تلقائياً.
6. **المحول المباشر لـ `Pre-Flight v4` وفحص عدم الفقد الحرفي (`pdf_to_preflight_adapter.py` & `100% Zero-Loss Check`):**
   - يحوّل `pages/pNNNN.json` إلى ملف المتن الموحد `book_matn.txt` المعلّم بعلامات الصفحات المعيارية `[ص: N]` وعلامات الهوامش الجانبية `[هامش جانبي — ص N]`، مع فصل الحواشي السفلية في `footnotes.json` و`pages_preflight.json`.
   - يبني هيكل `source_snapshots/<book_id>/{toc.json, 0000.json..0NNN.json}` المطابق تماماً لما يستقبله `manifest_v4.py` و`fn_linker_v4.py` في `turath-deep-indexing`، مع التحقق التشفيري (`SHA-256`) من حفظ `100.0%` من حروف المتن والهامش والحواشي (`0 lost chars`).
7. **الهيكلة الشجرية بالأبواب والفصول، وصل الجمل عبر الصفحات، وقاعدة البيانات `SQLite + FTS5` (`build_book_db.py`):**
   - يستخرج الكاشف الهجين (`9E`) الفهرس الشجري للكتاب (`TOC`) بدقة `F1 = 100%` (بما في ذلك العناوين بين معقوفات `[...]`، والعناوين الموضوعية القصيرة، والعناوين المدمجة في أول السطر `Run-in Headings`).
   - يعيد تجميع الأسطر المكسورة إلى فقرات متماسكة، ويلحم الجمل المقطوعة عبر الصفحات مع إدراج وسام موضع الصفحة `⟦ص ١٥٢⟧` في النص المتصل (`text_continuous`) وتجريده في النص الصافي (`text_clean`).
   - يؤطّر إحالات الحواشي بمعرّف الصفحة (`[ص١٥٢/ح١]`) لمنع تضارب الأرقام (`100%` صفر تضارب)، ويربط كل حاشية بنافذة سياقها في المتن وبقسمها الدقيق، ويبني قاعدة بيانات `SQLite + FTS5` تدعم البحث العربي بالهمزات والسوابق المتصلة وتاء الإضافة (`أئمة` ← `أئمتهم`، `رؤوس` ← `رءوس`).

---

## 2. الأدوات التنفيذية المدمجة في المهارة (`$SKILL_DIR/scripts/`)

| السكربت في `$SKILL_DIR/scripts/` | الوظيفة الدقيقة |
| :--- | :--- |
| [`scripts/agy_pdf_to_text.py`](./scripts/agy_pdf_to_text.py) | المحرك الرئيسي الشامل (الطبقة ١): الرندر الرمادي المتكيف، إزالة الغبار الآمنة، التوجيه البصري للتخطيطات الأربعة، استدعاء المرحلة الأولى بعزل `realpath` و`--json-schema`، بوابات الجودة الخمس، التكبير البؤري المدمج `2800px`، والحفظ المرحلي لكل صفحة (`pages/pNNNN.json` + `pages/pNNNN.txt`) مع استدعاء `build_book_db.py` تلقائياً لبناء `<slug>.db` و`toc.json` و`<slug>.md` و`<slug>_pages.md`. |
| [`scripts/pdf_to_preflight_adapter.py`](./scripts/pdf_to_preflight_adapter.py) | **المحول المباشر (`v2.0`):** يحوّل `pages/pNNNN.json` بأمان حرفي `100%` إلى حزمة مدخلات `Pre-Flight v4` (`book_matn.txt` بعلامات `[ص: N]`، `footnotes.json`، `pages_preflight.json`، و`source_snapshots/<book_id>/0*.json`)، وينفّذ بوابة `100% Zero-Loss Check` ويستدعي `manifest_v4.py` و`fn_linker_v4.py` مباشرةً ويخرج `adapter_manifest.json`. |
| [`scripts/build_book_db.py`](./scripts/build_book_db.py) | محرك هيكلة الكتاب وبناء قاعدة البيانات الأرشيفية `SQLite + FTS5` والفهرس الشجري (`toc.json`) والماركداون المهيكل بالأبواب (`<slug>.md`) مع واجهة استعلام سريعة (`--get-toc`، `--get-part`، `--search`). |
| [`scripts/check_pdf_output.py`](./scripts/check_pdf_output.py) | فاحص ومصلح حتمي سريع لمجلد مخرجات أي كتاب: يعيد تشغيل بوابات الجودة الخمس، يطبّع أي أرقام أو حروف فارسية متبقية (`--fix-normalize`)، ويعيد بناء قاعدة البيانات والماركداون (`--rebuild`). |
| [`scripts/test_pdf_gates.py`](./scripts/test_pdf_gates.py) | حزمة الاختبارات الانحدارية البصرية والهيكلية (`12` اختباراً حتمياً في `< 0.04` ثانية) تفحص مصنّف التخطيطات، إزالة الغبار وحماية الطرر، تطبيع اليونيكود، بوابات الحواشي والآيات، كاشف الفهرس الشجري `9E`، وصل الجمل عبر الصفحات، وبحث `SQLite FTS5` العربي. |
| [`scripts/test_pdf_adapter_gates.py`](./scripts/test_pdf_adapter_gates.py) | **بوابة الفحص الشاملة للإصدار `v2.0` (`Gate 1` + `Gate 2` + `Gate 3`):** تشغّل بوابات `test_pdf_gates.py` الـ 12، وتختبر `pdf_to_preflight_adapter.py` على 5 صفحات واقعية (تضم حواشي مرقمة `1, 2, 3` وحاشية جدول أزهرية `framed_hashiya`)، وتمرر المخرجات فعلياً إلى `manifest_v4.py` و`fn_linker_v4.py` وتتحقق من الخروج بـ `PASS (0 errors)`. |

---

## 3. التشغيل القياسي والأوامر المعتمدة

### أ) تحويل كتاب كامل أو نطاق صفحات (الطبقة ١ — الاستخراج البصري الحرفي الصافي):
يستخدم `gemini-3.8-flash-medium` في المرحلة الأولى (سرعة عالية `~30–50s`/صفحة) ويصعّد تلقائياً إلى `gemini-3.8-flash-high` بدقة `2800px` لأي سطر يحتوي كلمة مشتبهة أو خلل حاشية، ويحفظ `pages/pNNNN.json` + `pages/pNNNN.txt`:

```bash
python3 "$SKILL_DIR/scripts/agy_pdf_to_text.py" /path/to/book.pdf \
    --out-dir /path/to/output_book \
    [--pages 1-50] [--only 16,22,86] \
    --model gemini-3.8-flash-medium \
    --zoom-model gemini-3.8-flash-high \
    --workers 2 --stagger 2.0
```

### ب) تحويل المخرجات إلى هيكل `Pre-Flight v4` لتسليمها إلى `turath-deep-indexing` (`pdf_to_preflight_adapter.py`):

```bash
python3 "$SKILL_DIR/scripts/pdf_to_preflight_adapter.py" /path/to/output_book \
    --out-dir /path/to/output_book/preflight_v4 \
    --book-id 9001 \
    --science fiqh \
    --round 1 \
    --title "عنوان الكتاب" \
    --author "اسم المؤلف" \
    --death "643"
```

### ج) استعراض الفهرس الشجري، جلب الأبواب، والبحث في الأرشيف (`build_book_db.py`):

```bash
# عرض الفهرس الشجري (TOC) بصيغة JSON مطابقة لـ turathmcp
python3 "$SKILL_DIR/scripts/build_book_db.py" /path/to/output_book --get-toc

# جلب نص باب/فصل محدد (مع الحواشي، أو نصاً صافياً عبر --clean)
python3 "$SKILL_DIR/scripts/build_book_db.py" /path/to/output_book --get-part 1 --clean

# بحث عربي فوري في المتن والحواشي (يدعم الهمزات والسوابق وتاء الإضافة)
python3 "$SKILL_DIR/scripts/build_book_db.py" /path/to/output_book --search "رؤوس"
```

### د) فحص وتطبيع مخرجات كتاب محوّل وإعادة بناء قاعدة البيانات والماركداون:

```bash
python3 "$SKILL_DIR/scripts/check_pdf_output.py" /path/to/output_book --fix-normalize --rebuild
```

### هـ) تشغيل بوابات الاختبارات الحتمية الشاملة (`Gate 1–4`):

```bash
python3 "$SKILL_DIR/scripts/test_pdf_adapter_gates.py"
```

---

## 4. القواعد الذهبية الأربع عشرة للوكيل (لا تكسرها أبداً)

1. **إياك وتمرير ملف `.pdf` مباشرةً إلى `view_file`:** حوّل الصفحات دائماً إلى صور `.png` رمادية مقطعة عبر `agy_pdf_to_text.py`.
2. **إياك واستخدام `--effort` مع `--model gemini-3.8-flash-high` أو `medium` في `agy`:** مستوى الجهد مدمج في اسم النموذج نفسه؛ تمرير `--effort` معه يُسقط النداء فوراً (`0 tokens`, `rc != 0`).
3. **إياك وتمرير صورة صفحة عمودية كاملة دون شطر:** الشطر الأفقي عند وادي الفراغ الأوسط (`@band1_top.png` + `@band2_bot.png`) إلزامي للصفحات العمودية لمضاعفة كثافة البكسلات `2.4x`.
4. **احظر `run_command` و`turathmcp` وأدوات البحث صراحةً داخل المحث، لكن لا تكتب «ولا غيرها» بإطلاق مع `--json-schema`:** لأن `--json-schema` يعمل عبر أداة تسليم داخلية، فالمنع المطلق قد يجعل النموذج يعيد نصاً حراً بدل استدعاء أداة الـ JSON.
5. **شغّل `agy` دائماً داخل `os.path.realpath(tmpdir)` يحتوي صور الصفحة الحالية فقط:** لمنع فشل حل المسارات الرمزية `/var/folders` على macOS ولمنع قراءة ملفات أخرى.
6. **التزم بفارق إقلاع متدرج (`--stagger 2.0`) عند تشغيل عمال متوازيين (`--workers 2..3`):** لمنع تصادم تهيئة خوادم MCP المحلية عند بدء العمليات في نفس اللحظة.
7. **لا تمسح حواف الصفحة بعرض ثابت أعمى:** مسح كل مكون يلامس `6%` من الحافة يبتر إشارات المخطوطات الجانبية مثل `[I/8]`؛ لا تمسح إلا خطوط الظل الطويلة (`comp_h > 120px`).
8. **اقلب المتن العمودي في حواشي الجداول بزاوية 90° مع عقارب الساعة (`k=3`) قبل إرساله للنموذج:** لكي يقرأه أفقياً في `~36 ثانية` بدقة 100%.
9. **طبّع الأرقام الفارسية الشرقية (`U+06F0..U+06F9` ← `U+0660..U+0669`) والحروف الفارسية (`ی/ک` ← `ي/ك`) حتمياً بعد كل استدعاء:** لأن محرك الرؤية يخلط بينها بصمت، مما يفسد فهارس الأرقام والربط اللاحق.
10. **احذف نص الآيات القرآنية `﴿[^﴾]*﴾` مؤقتاً قبل فحص إحالات الحواشي في المتن:** حتى لا تُحسب أرقام الآيات `(٢) (٣) (٤)` داخل الآية كإحالات حواشٍ مفقودة.
11. **عند البحث عن موقع الكلمة المشتبه بها (`uncertain_words`) لقص شريحة التكبير البؤري `2800px`، طابق أطول كلمة عربية (`>= 2` حرف) بعد استبعاد الشروح بين المعقوفات:** لتجنب مطابقة حرف مفرد مثل الألف في `"ا وجوب ا"` مع السطر الأول من الصفحة.
12. **اعتمد دائماً المعمارية المزدوجة (`<slug>.db` + `toc.json` + `<slug>.md` المهيكل بالأبواب + `<slug>_pages.md`):** مع تأطير إحالات الحواشي برقم الصفحة `[ص.../ح...]` ووصل الجمل المقطوعة عبر الصفحات عبر `build_book_db.py`.
13. **افصل صارماً بين الاستخراج الحرفي (الطبقة ١) والفهرسة الموضوعية والتلخيص (الطبقة ٢):** سلّم مخرجات الصفحات إلى `turath-deep-indexing` حصراً عبر `scripts/pdf_to_preflight_adapter.py` بعد اجتياز `100% Zero-Loss Check` وبوابة `manifest_v4.py`.
14. **اعتمد التطبيع المقيّد بالصفحة (`normalize_page_footnotes_and_markers`) قبل الربط الرتيب (`lcs_align`):** لفصل الحواشي الأفقية المتعددة في السطر الواحد، وتوحيد صيغ الإحالات غير القياسية (`[١]`, `(*)`, `¹`, `هما1`)، ودمج حواشي الاستمرار (`= ...` / `(=) ...`)، وموازنة الحواشي المشتركة داخل الصفحة لمنع انزياح الإحالات عبر الصفحات.
15. **ادعم التخطيط متعدد المناطق (`Matn / Sharh / Footnotes`) وميّز بين الآيات القرآنية `﴿...﴾` والمتن المشروح المحصور بين `﴿...﴾`:** عبر `extract_and_normalize_page_zones` و`is_quranic_floral_span` لحفظ محددات `matn_top` (`﴿...﴾`, `(...)`) بنسبة `100% Zero-Loss` وتطبيع إحالات الحواشي داخل المتن المشروح (`[١]` ← `(١)`) دون المساس بأرقام الآيات القرآنية الحقيقية (`(٤٣)`).
16. **أصلح الكلمات المقطوعة عبر نهاية السطر بالشرطة أو الكشيدة وطبّع الأرقام المختلطة (`repair_line_breaks_and_mixed_digits`):** لوصل شطري الكلمة الواحدة (`المسـ\nـألة` ← `المسألة`، `باجـ-\nـتهاد` ← `باجتهاد`، `الاست-\nحسان` ← `الاستحسان`) وتوحيد الأرقام الهندية/اللاتينية المختلطة في `printed_page` (`"١5"` ← `"١٥"`) وداخل النصوص والحواشي (`١25` ← `١٢٥`).
17. **وحّد عقد بيانات الحواشي بين `scripts/validate_json.py` و`scripts/pdf_to_preflight_adapter.py` (`coerce_footnotes_to_raw_str`):** ليقبل الحواشي بصيغة نص (`str`)، أو قائمة نصوص (`list[str]`)، أو قائمة قواميس (`[{"id": "1", "text": "..."}]`)، أو قاموس (`dict`)، مع دعم حواشي الاستمرار العابرة للصفحات (`= ...`, `(=) ...`) والتحقق منها عبر البوابات الخمس في `scripts/test_pdf_adapter_gates.py`.

---

## 5. فهرس المراجع التفصيلية في هذه المهارة

1. **[`references/01-vision-geometry-and-layout-routing.md`](./references/01-vision-geometry-and-layout-routing.md)** — الهندسة البصرية، الرندر الرمادي المتكيف، إزالة الغبار الآمنة، ومصنّف التخطيطات الرباعي (`2-Band Split`, `Two-Column`, `Framed Hashiya 90° Rotation`).
2. **[`references/02-agy-cli-mechanics-and-json-schema.md`](./references/02-agy-cli-mechanics-and-json-schema.md)** — ميكانيكا `agy CLI`، قفل `view_file` المتوازي، أسرار `--json-schema`، وخفض التوكنات `33.5x`.
3. **[`references/03-quality-gates-and-focal-zoom.md`](./references/03-quality-gates-and-focal-zoom.md)** — المواصفة الخوارزمية لبوابات الجودة الخمس وحلقة التكبير البؤري المجهري `2800px`.
4. **[`references/04-pitfalls-and-empirical-benchmarks.md`](./references/04-pitfalls-and-empirical-benchmarks.md)** — كتالوج الأخطاء الـ 15 (العَرَض ← السبب الجذري ← الإصلاح) ونتائج التجارب المعيارية على الكتب الستة.
5. **[`references/05-sqlite-fts5-and-chapter-structuring.md`](./references/05-sqlite-fts5-and-chapter-structuring.md)** — هيكلة الكتاب بالأبواب والفصول، الفهرس الشجري (`TOC 9E`)، وصل الجمل عبر الصفحات، تأطير الحواشي `[ص.../ح...]`، وقاعدة البيانات `SQLite + FTS5` المتوافقة مع `turathmcp`.
