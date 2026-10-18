---
name: person-discovery-intake
version: 1.0
description: "Use when discovering, harvesting, and unifying all digital heritage (YouTube channels, playlists, livestreams, standalone uploads, Archive.org audio buckets, PDF index link streams such as Jamharat A'mal, and authored/explained books via Turath/Shamela) starting from a scholar or person's name alone into a canonical <person_id>_raw.json file 100% compatible with sheikh-curation."
---

# مهارة `person-discovery-intake`: الاكتشاف الشامل والحصاد الموحد لتراث الأعلام والمشايخ من الاسم فقط

توثق هذه المهارة المعمارية القياسية، والخوارزميات الحتمية، والقواعد الذهبية للانتقال من **«اسم الشخصية فقط»** (أو اسمها مع بعض الروابط الأولية) إلى بناء ملف الجرد الخام الموحد `<person_id>_raw.json` الجاهز تماماً للتنقيح عبر مهارة `sheikh-curation` بمعيار **صفر خطأ (`0 Errors`)**.

تعالج هذه المهارة جذرياً مشكلة تشتت تراث العلماء والمفكرين بين قنوات رسمية وأرشيفية متعددة، وقوائم تشغيل غير مدرجة (`Unlisted Playlists`) مدفونة داخل ملفات `PDF` فهرسية (مثل «جمهرة أعمال م. أيمن عبد الرحيم»)، وحزم صوتية على `Archive.org` ناقصة التوثيق في المواقع الرسمية (مثل موقع العلامة مولود السريري)، وربط السلاسل الصوتية بالمتون العلمية المشروحة ومؤلفات الشخصية عبر فهارس `turathmcp` والشاملة.

---

## 1. المبادئ الحاكمة والقواعد الذهبية (Golden Rules)

1. **الصدق العلمي الصارم ومنع التخمين (`Zero Hallucination`)**:
   - يُمنع منعاً باتاً اختلاق عناوين سلاسل أو أعداد دروس أو مدد زمنية أو معرّفات يوتيوب/أرشيف من الذاكرة اللغوية.
   - كل فيديو أو ملف صوتي في `<person_id>_raw.json` يجب أن يستند إلى معرّف حقيقي (`vid` / `yt_id`) ورابط فعلي ومدة زمنية بالثواني (`dur_s` / `duration`).

2. **الاستيعاب متعدد المصادر (`Multi-Source Exhaustive Intake`)**:
   - لا يقتصر الاكتشاف على تبويب `Playlists` في قناة يوتيوب واحدة؛ بل يشمل وجوباً:
     1. **جميع قنوات يوتيوب المرتبطة بالشخصية**: القناة الرسمية + قنوات المؤسسات أو المدارس العلمية المشتركة (مثل `مدرسة تنكرت العتيقة` أو `مدرسة شيخ العمود`) + القنوات الأرشيفية الموثوقة.
     2. **التبويبات الثلاثة في كل قناة**: قوائم التشغيل (`Playlists`) + الفيديوهات المنفردة (`Videos / Uploads`) + البثوث المباشرة (`Streams / Live`).
     3. **حزم `Archive.org` الصوتية**: عبر واجهة البحث المتقدم (`advancedsearch.php`) وواجهة البيانات الوصفية المباشرة (`archive.org/metadata/<item_id>`) وحسابات الرافعيين (`uploader`).
     4. **تيارات ملفات `PDF` الفهرسية (`PDF FlateDecode Streams`)**: فك ضغط تيارات `zlib` واستخراج الكائنات `/URI` للوصول إلى روابط `bit.ly` وقوائم التشغيل غير المدرجة (`Unlisted Playlists`).
     5. **فهارس الكتب والمتون (`Turath / Shamela / Books Catalog`)**: حصر مؤلفات الشخصية والمتون التراثية التي شرحتها وربط كل سلسلة بمتنها المشروح (`matched_book`).

3. **إلزامية جلب المدد الزمنية (`dur_s` / `duration`) وتواريخ الرفع (`upload_date`)**:
   - لا يُقبل إدراج درس خام بدون مدته بالثواني متى كانت متاحة في البيانات الوصفية ليوتيوب أو `Archive.org`؛ لأن غياب المدة يعطّل كاشف المقاطع القصيرة (`< 300s`) وكاشف انقلاب الأب والابن في البثوث المباشرة المنقطعة داخل `sheikh-curation`.

4. **الفصل الدقيق في القنوات المشتركة ومنع الخلط بين الأعلام**:
   - في القنوات التي تجمع أكثر من عالم (مثل قناة `مدرسة تنكرت العتيقة` المشتركة بين العلامة مولود السريري والشيخ محمد البردوني الحسيمي)، تُفحص عناوين القوائم والفيديوهات والكتب المشروحة بدقة لعزل مواد كل علم في ملفه الخاص وعدم نسبة سلسلة لعالم آخر.

5. **التوافق المزدوج الكامل (`100% Backward & Forward Schema Compatibility`)**:
   - يتضمن ملف `<person_id>_raw.json` الناتج كلاً من:
     * مفاتيح الجرد الشامل الحديثة (`person_id`, `sheikh_name`, `discovered_at`, `channels`, `playlists`, `videos`, `archive_items`, `pdf_extracted_links`, `books`, `stats`).
     * والمفاتيح القياسية التي تستهلكها سكربتات `sheikh-curation` مباشرة (`sheikh`, `raw_playlists_count`, `unique_videos_count`, `raw_series`, `unique_videos`) دون الحاجة لأي تحويل وسيط.

---

## 2. معمارية خط أنابيب الاكتشاف (Discovery Pipeline Architecture)

```mermaid
flowchart TD
    A["اسم الشخصية (--name) + معرف مقترح (--person-id)"] --> B["تطبيع الاسم وتوليد person_id القياسي"]
    B --> C1["مسار يوتيوب: yt-dlp / InnerTube\n(Channels, Playlists, Uploads, Streams)"]
    B --> C2["مسار PDF الفهرسي: zlib.decompress\n(FlateDecode Streams + /URI + Shortlinks)"]
    B --> C3["مسار Archive.org: AdvancedSearch + Metadata API\n(Audio .mp3/.m4a/.flac/.ogg + Uploader Buckets)"]
    B --> C4["مسار الكتب والمتون: TurathMCP / Books Catalog\n(مؤلفات الشخصية + المتون التراثية المشروحة)"]
    C2 -->|"Unlisted Playlists & Video URLs"| C1
    C2 -->|"Archive Item IDs"| C3
    C1 --> D["محرك إزالة التكرار والتوحيد (Deduplication & Normalization Engine)"]
    C3 --> D
    C4 --> E["محرك مطابقة السلاسل بالمتون والكتب (Series-to-Matn Matcher)"]
    D --> E
    E --> F["تصدير <person_id>_raw.json المعياري"]
    F --> G["بوابة الجودة الثلاثية (test_discovery_gates.py -> PASS 0 errors)"]
```

---

## 3. المصادر الخمسة للاكتشاف وقواعد التعامل مع كل مصدر

### المصدر الأول: يوتيوب (`YouTube Channels, Playlists, Uploads & Streams`)
1. **البحث والاكتشاف من الاسم**:
   - البحث عن القنوات الرسمية والأرشيفية وقوائم التشغيل الكبرى باستخدام `yt-dlp`:
     ```bash
     yt-dlp --flat-playlist -J "ytsearch20:<اسم الشخصية>"
     ```
2. **الحصاد الشامل للقناة (`Playlists` + `Videos` + `Streams`)**:
   - لكل قناة مكتشفة (`UC...` أو `/@handle`):
     * جلب جميع قوائم التشغيل: `https://www.youtube.com/channel/<UC_ID>/playlists`
     * جلب قائمة الرفوعات الكاملة (`Uploads`): تحويل بادئة معرف القناة من `UC` إلى `UU` (`https://www.youtube.com/playlist?list=UU<channel_suffix>`) لضمان التقاط جميع الفيديوهات المنفردة غير المضافة لأي قائمة تشغيل (`unclassified`).
     * جلب تبويب البثوث المباشرة: `https://www.youtube.com/<handle>/streams` مع وسمها بـ `source_type: "youtube_stream"`.
3. **استخراج الحقول الإلزامية لكل فيديو**:
   - `vid` و`yt_id`: معرف الفيديو ذو الـ 11 حرفاً.
   - `title`: العنوان الكامل كما ورد في المصدر.
   - `dur_s` و`duration`: المدة بالثواني (عدد صحيح موجب).
   - `upload_date`: تاريخ الرفع بصيغة `YYYYMMDD` (أو التاريخ الهجري المستخرج عند غياب تاريخ الرفع في الفحص السطحي).
   - `playlist_id` و`playlist_title`: معرف وعنوان القائمة الأم.
   - `source_type`: نوع المصدر (`"youtube_playlist"`, `"youtube_stream"`, `"youtube_upload"`, `"youtube_unlisted_playlist"`).
   - `appearances`: قائمة بجميع القوائم التي ظهر فيها الفيديو مع ترتيبه (`pos`) داخل كل قائمة، مما يمكّن `hijri_interpolator.py` من استيفاء التواريخ المبتورة بدقة.

---

### المصدر الثاني: فك تيارات ملفات `PDF` الفهرسية (`PDF FlateDecode Stream Link Extraction`)
كثيراً ما تُجمع أعمال العالم أو المفكر في كتاب فهرسي بصيغة `PDF` (مثل «جمهرة أعمال م. أيمن عبد الرحيم»)، وتكون الروابط التشعبية فيه مضغوطة داخل تيارات `FlateDecode` أو مخفية خلف روابط مختصرة (`bit.ly`) تشير إلى قوائم تشغيل غير مدرجة (`Unlisted Playlists`) لا تظهر في بحث يوتيوب إطلاقاً.

* **الخوارزمية المعتمدة في `extract_links_from_pdf(pdf_path)`**:
  1. قراءة الملف الثنائي (`rb`) والبحث في طبقتين:
     - **الطبقة الأولى (الكائنات غير المضغوطة)**: التقاط جميع وسوم `/URI (...)` و`/URI <HEX>` وفك تهريب محارف PDF (`\(`, `\)`, `\\`).
     - **الطبقة الثانية (تيارات `stream ... endstream` المضغوطة)**: تمرير كل تيار ثنائي عبر `zlib.decompress(data)` (مع تجربة `wbits=-15` للـ Raw Deflate عند الحاجة)، ثم مسح النص المفكوك لاستخراج:
       * روابط قوائم يوتيوب: `youtube.com/playlist?list=PL...` ومعرفات `PL[A-Za-z0-9_-]{16,34}`.
       * روابط الفيديوهات المباشرة والمختصرة: `youtube.com/watch?v=...` و`youtu.be/...`.
       * روابط أرشيف الإنترنت: `archive.org/details/...` و`archive.org/download/...`.
       * الروابط المختصرة: `bit.ly/...`، `goo.gl/...`، `tinyurl.com/...` مع دعم تتبع التحويلات (`HTTP 301/302 Redirects`) لكشف رابط قائمة التشغيل الهدف.

---

### المصدر الثالث: أرشيف الإنترنت (`Archive.org AdvancedSearch & Metadata API`)
تُحفظ عشرات السلاسل الصوتية الكاملة للمشايخ على `Archive.org`، وكثيراً ما تسقط بعض حلقاتها من جداول المواقع الرسمية (كما سقط الدرس الأخير `024.mp3` من جدول «إيصال السالك» والدرس `090.mp3` من «نشر البنود» في موقع الشيخ السريري بينما هما موجودان داخل حزمة الأرشيف نفسها).

* **الخوارزمية المعتمدة**:
  1. **البحث عن الحزم وحسابات الرافعيين**:
     - عبر `https://archive.org/advancedsearch.php?q=creator:("<الاسم>") OR title:("<الاسم>")&output=json`.
     - وعند معرفة حساب رافع رسمي (`uploader`)، يُجرد الحساب كاملاً لاكتشاف الحزم غير المربوطة في الموقع (مثل اكتشاف حزمة `Kitab.Alma9asid` الكاملة).
  2. **فحص البيانات الوصفية المباشرة (`https://archive.org/metadata/<item_id>`)**:
     - قراءة المصفوفة `files` واستخراج جميع الملفات الصوتية (`.mp3`, `.m4a`, `.flac`, `.ogg`).
     - **إزالة تكرار المشتقات الصوتية (`Derivative Deduplication`)**: ينشئ `Archive.org` تلقائياً نسخة `.ogg` مشتقة لكل ملف `.mp3`؛ يختار السكربت النسخة الأصلية الأعلى جودة لنفس الاسم الأساسي (`stem`) بترتيب الأولوية: `.mp3` ثم `.m4a` ثم `.flac` ثم `.ogg`.
     - **حساب المدة (`dur_s`)**: تحويل حقل `length` في بيانات الأرشيف (سواء كان بالثواني الكسرية `"7298.42"` أو بصيغة `"02:01:38"`) إلى عدد صحيح بالثواني (`7298`).
     - **توليد الرابط المباشر والمعرف القياسي**:
       * `direct_url`: `https://archive.org/download/<item_id>/<filename>`
       * `vid` / `yt_id`: `archive__<person_id>__<clean_item_id>__ep<NNN>` (متوافق 100% مع معيار `sheikh-curation` كما في `sariri.json`).

---

### المصدر الرابع: الكتب والمؤلفات ومطابقة المتون (`Turath / Books Catalog & Matn Matching`)
1. **حصر كتب الشخصية ومتون الشروح**:
   - يستعلم السكربت في فهرس `turath_mcp.py` (العبر علومه الـ 11: التفسير، الحديث، الفقه المالكي، التراجم، التاريخ، السيرة، أصول الفقه، علوم القرآن، قواعد الفقه، العقيدة، التزكية) أو ملف الكتب المحلي (`--books-json`)، بالإضافة إلى قاعدة المعرفة المدمجة للمتون العلمية القياسية (`MATN_KNOWLEDGE_BASE`).
   - يميز بدقة بين:
     * **مؤلفات الشخصية نفسها** (`is_authored_by_person: true`).
     * **المتون التراثية التي شرحتها الشخصية صوتياً أو مرئياً** (`is_explained_by_person: true`).
2. **قواعد المطابقة الدلالية الصارمة (`Anti-Confusion Matn Matching Rules`)**:
   - **منع خلط الفنون**:
     * `مقدمات السنوسي` / `أم البراهين` / `العقيدة الصغرى` -> تصنف في **العقيدة وعلم الكلام** ولا تصنف أبداً في الفقه.
     * الفصل الصارم بين **أصول الفقه** (`جمع الجوامع`، `مراقي السعود`، `إيصال السالك`، `مفتاح الوصول`، `الرسالة العضدية`، `الورقات`) وبين **مقاصد الشريعة** (`الموافقات للشاطبي`، `كتاب المقاصد`).
   - **حدود الكلمات العربية (`Arabic Word Boundaries`)**:
     * منع التطابق الجزئي الخاطئ للكلمات القصيرة (مثل عدم تطابق سورة `الحج` مع `الحجر`، وعدم تطابق كلمة `خطبة` في `مسألة الصلاة أثناء خطبة الإمام` مع سلاسل خطب الجمعة).

---

## 4. دليل التشغيل السريع (CLI & Python API Usage)

### أولاً: تشغيل الاكتشاف والتوحيد عبر سطر الأوامر (`discover_person.py`)

```bash
# 1. اكتشاف وتوحيد بيانات شيخ من ملفات خام أو قنوات وأرشيف وPDF وكتب:
python3 /Users/macm1pro/REPOS/SKILLS/person-discovery-intake/scripts/discover_person.py \
  --name "علي محمود العمري" \
  --person-id "omari" \
  --offline-fixture "/Users/macm1pro/REPOS/cheikh/data/curated_sheikhs/omari_raw.json" \
  --output "/tmp/omari_discovered_raw.json"

# 2. اكتشاف شامل مع تمرير روابط يوتيوب وحزم Archive.org وملفات PDF فهرسية:
python3 /Users/macm1pro/REPOS/SKILLS/person-discovery-intake/scripts/discover_person.py \
  --name "المهندس أيمن عبد الرحيم" \
  --person-id "ayman" \
  --youtube-urls "https://www.youtube.com/@sheikhelamoud" \
  --archive-ids "ayman-abdelrahim-audio" \
  --index-pdfs "/path/to/jamharat_ayman.pdf" \
  --output "/path/to/ayman_raw.json"
```

### ثانياً: التشغيل كبوابة جودة حتمية (`test_discovery_gates.py`)

```bash
python3 /Users/macm1pro/REPOS/SKILLS/person-discovery-intake/scripts/test_discovery_gates.py
```

يفحص هذا الاختبار ثلاث طبقات حتمية:
1. **`[Gate 1] PDF FlateDecode Stream & URI Extraction`**: بناء وفحص ملف PDF ثنائي مضغوط بـ `zlib/FlateDecode` واستخراج روابط `Unlisted Playlists` و`Archive.org` والفيديوهات والروابط المختصرة.
2. **`[Gate 2] Multi-Source Unification & Book/Matn Matching`**: دمج بيانات يوتيوب + `Archive.org` (مع تصفية مشتقات `.ogg` وحساب المدد) + الكتب والمتون، والتحقق من صحة ربط السلاسل بمتونها المشروحة ومنع خلط الفنون.
3. **`[Gate 3] Canonical Schema & sheikh-curation Compatibility`**: التحقق الصارم من جميع الحقول والأنواع في `<person_id>_raw.json` وتوافقه التام مع `sheikh-curation` (`hijri_interpolator.py` و`deep_scanner_all.py`)، وإخراج `PASS (0 errors)`.

---

## 5. المراجع التفصيلية
- راجع توثيق مخطط البيانات الكامل (`JSON Schema`) وتفاصيل البروتوكولات البرمجية في: [references/01-discovery-sources-and-schema.md](./references/01-discovery-sources-and-schema.md).
