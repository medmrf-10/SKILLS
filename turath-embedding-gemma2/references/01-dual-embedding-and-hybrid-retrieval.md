# 01 — المرجع الهندسي للتضمين المزدوج بـ `EmbeddingGemma 2` والاسترجاع الهجين العلائقي

يوثق هذا المرجع المواصفة الهندسية الدقيقة لطبقة التضمين الشعاعي المزدوج (`Dual-Vector Representation`)، وبادئات المهام القياسية في `EmbeddingGemma 2`، وخوارزميات التنظيف المسبق، ومعادلات الدمج الهجين (`Weighted Cosine + BM25 + RRF`)، وجداول الفلترة العلائقية بالكيانات.

---

## 1. بادئات المهام غير المتماثلة في `EmbeddingGemma 2` (`Asymmetric Task Prefixes`)

يعتمد نموذج `EmbeddingGemma 2` (`google/embeddinggemma-2` / `embeddinggemma`) على التضمين غير المتماثل (`Asymmetric Retrieval Embedding`) لتمييز فضاء المستندات المخزنة عن فضاء الاستعلامات البحثية:

| نوع المدخل | القالب القياسي لبادئة المهمة (`Prompt Template`) | مثال تطبيقي |
| :--- | :--- | :--- |
| **تضمين المتن (`vec_matn`)** | `task: search result \| title: {source_title} › {sub_heading} \| text: {clean_matn_hygienic}` | `task: search result \| title: الموافقات (الشاطبي) › قاعدة المشقة تجلب التيسير \| text: المشقة تجلب التيسير، والأصل في الرخص الشرعية رفع الحرج عن المكلفين...` |
| **تضمين المفهوم (`vec_concept`)** | `task: search result \| title: {sub_heading} — {science} \| text: الملخص: {summary} \| الموضوعات: {topics} \| القواعد: {polished_rules} \| أسئلة: {search_queries}` | `task: search result \| title: قاعدة المشقة تجلب التيسير — أصول الفقه \| text: الملخص: تقرير أصل رفع الحرج... \| القواعد: المشقة العارضة في السفر والمرض سبب للرخصة...` |
| **تضمين القاعدة العلمية (`gem`)** | - المتن: `task: search result \| title: {gem_title} \| text: {verbatim_rule}`<br/>- المفهوم: `task: search result \| title: {gem_title} ({category}) \| text: {polished_rule} \| {explanation}` | يتيح البحث المباشر في جدول `gem_embeddings` سواء بلفظ القاعدة التراثي أو بصياغتها المفهومية المحررة. |
| **تضمين الاستعلام (`Query`)** | `task: search query \| query: {user_query}` | `task: search query \| query: ما حكم الرخص الشرعية عند المشقة والسفر؟` |

---

## 2. قواعد التطهير الصارم لحقلَي التضمين (`Dual Text Hygiene Rules`)

تضمن دالتا `prepare_embed_matn_text(passage)` و`prepare_embed_concept_text(passage, gems)` في `scripts/embed_corpus_gemma2.py` تحقيق شروط النظافة النصية الأربعة قبل حساب أي متجه:

### أ. تفكيك محارف الترضية والترحم المدمجة في يونيكود (`Unicode Presentation Ligatures`):
تحوّل جميع المحارف في النطاقين `\ufd40..\ufd4f` و`\ufdfa..\ufdff` إلى مقابلاتها العربية القياسية المفصولة بمسافات حتى لا تتحول إلى رموز مجهولة (`[UNK]`) في النموذج:
- `\ufd40` (`﵀`) $\rightarrow$ `رحمه الله`
- `\ufd41` (`﵁`) $\rightarrow$ `رضي الله عنه`
- `\ufd42` (`﵂`) $\rightarrow$ `رضي الله عنها`
- `\ufd43` (`﵃`) $\rightarrow$ `رضي الله عنهم`
- `\ufd44` (`﵄`) $\rightarrow$ `رضي الله عنهما`
- `\ufd4c` / `\ufdfa` (`ﷺ`) $\rightarrow$ `صلى الله عليه وسلم`
- `\ufdfb` (`ﷻ`) $\rightarrow$ `جل جلاله`
- `\ufdfe` $\rightarrow$ `سبحانه وتعالى`
- `\ufdff` $\rightarrow$ `عز وجل`

### ب. إزالة علامات الصفحات والأوراق والحواشي (`Page & Folio Marker Stripping`):
تُحذف جميع العلامات الطباعية التي لا تحمل دلالة علمية:
1. علامات الصفحات الصريحة والمعقوفة: `[ص: ١٢٣]`, `[ص ١٢٣]`, `صفحة ١٢٣`, `⦗١٢٣⦘`.
2. علامات أوراق المخطوطات: `[١٢ و]`, `[١٢ ظ]`, `(١٣٠ب)`, `/ (٢٥ أ/ د)`.
3. رموز الحواشي المبتورة أو المرقمة: `(¬١)`, `(١)`, والأرقام الهندية الملتصقة بآخر الكلمات.

### ج. عزل السند عن المتن وعن المفهوم (`Strict Isnad & Transmission Isolation`):
1. في **`embed_matn_text`**: يُعتمد حقل `clean_matn` المعزول عن `isnad_prefix`، وإذا مرّ نص خام يحتوي على سلسلة إسناد ابتدائية (`حدثنا ... ثنا ... عن ... قال:`)، يتم تجريد مقدمة الإسناد آلياً ليبقى متن الخبر فقط.
2. في **`embed_concept_text`**:
   - يُشترط في جميع الأعلام المضافين إلى نص المفهوم أن تكون طبقتهم `source_layer == 'matn'`.
   - يُحظر تماماً إدراج أي راوٍ وُسم بـ `source_layer == 'isnad'`، بل ويقوم المحرك بفحص نص المفهوم وتطهيره من أي اسم علم إسنادي خالص لم يرد في المتن.
   - يُشترط في التواريخ المضافة أن تكون `event_layer == 'historical'` (أو غير مساوية لـ `'transmission'`) لاستبعاد تواريخ سماع النسخ الخطية.

---

## 3. أوزان الدمج الهجين ومعادلة `Reciprocal Rank Fusion (RRF)`

يحسب محرك `HybridSearchEngine` في `scripts/hybrid_search.py` ثلاث درجات أولية لكل مقطع مرشح $d$ بعد تطبيق الفلاتر العلائقية:

1. **درجة تشابه المتن (`score_matn`):**
   $$S_{\text{matn}}(q, d) = \max\left(0, \langle \hat{v}_{\text{query}}(q), \hat{v}_{\text{matn}}(d) \rangle\right)$$
2. **درجة تشابه المفهوم (`score_concept`):**
   $$S_{\text{concept}}(q, d) = \max\left(0, \langle \hat{v}_{\text{query}}(q), \hat{v}_{\text{concept}}(d) \rangle\right)$$
3. **درجة المطابقة المعجمية (`score_fts`):**
   تُستخرج من `bm25(passages_fts)` مع التطبيع على المجال $[0, 1]$ عبر:
   $$S_{\text{fts}}(q, d) = \frac{|\text{bm25}(d)|}{\max_{d'} |\text{bm25}(d')| + \epsilon}$$

ثم تُدمج القنوات الثلاث باستخدام مزيج متوازن من **المجموع الموزون للدرجات (`Weighted Score`)** و**دمج الرتب المتبادلة (`Reciprocal Rank Fusion — RRF`)**:

$$\text{RRF}(q, d) = \sum_{c \in \{\text{matn}, \text{concept}, \text{fts}\}} \frac{\alpha_c}{k + \text{rank}_c(d)} \quad (k = 60)$$

$$\text{HybridScore}(q, d) = 0.70 \times \left(\alpha_{\text{matn}} S_{\text{matn}} + \alpha_{\text{concept}} S_{\text{concept}} + \alpha_{\text{fts}} S_{\text{fts}}\right) + 0.30 \times k \times \text{RRF}(q, d)$$

### جدول أوضاع الأوزان القياسية (`Weight Profiles`):

| وضع الاسترجاع (`Search Mode`) | `--alpha-matn` | `--alpha-concept` | `--alpha-fts` | الاستخدام الأمثل |
| :--- | :---: | :---: | :---: | :--- |
| **الوضع الهجين المتوازن (`hybrid` — الافتراضي)** | `0.35` | `0.45` | `0.20` | البحث العام الذي يجمع بين الفهم المفهومي والدقة الحرفية. |
| **وضع المتن الصرف (`matn`)** | `1.00` | `0.00` | `0.00` | البحث بعبارة تراثية، نص حديث، أو اقتباس مباشر من المتن. |
| **وضع المفهوم الصرف (`concept`)** | `0.00` | `1.00` | `0.00` | البحث بسؤال معاصر، مسألة تحليلية، أو مصطلح فقهي/عقدي حديث. |
| **وضع المطابقة النصية الدلالية (`lexical-heavy`)** | `0.40` | `0.20` | `0.40` | التحقق من ورود ألفاظ معينة مع مراعاة السياق الدلالي للمتن. |

---

## 4. جداول الفلترة العلائقية بالكيانات (`Relational Entity Filter Matrix`)

تُنفَّذ الفلاتر العلائقية في `scripts/hybrid_search.py` كشروط `SQL` حتمية تقيد مجموعة المقاطع المرشحة (`Candidate Passages`) قبل حساب الترتيب النهائي:

| خيار الفلتر (`CLI / API`) | الجدول العلائقي المستهدف | الشرط العلائقي الدقيق (`SQL Predicate`) | الغاية المعرفية |
| :--- | :--- | :--- | :--- |
| `--person "<الاسم>"`<br/>`--person-layer matn` *(الافتراضي)* | `passage_persons` + `persons` | `pp.source_layer = 'matn' AND (pp.canonical_name LIKE ? OR pp.mentioned_name LIKE ? OR p.aliases_json LIKE ?)` | استرجاع المقاطع التي يكون فيها العَلَم موضوعاً أو متكلماً في المتن، **واستبعاد المقاطع التي ورد فيها في سلسلة السند فقط**. |
| `--person "<الاسم>"`<br/>`--person-layer isnad` | `passage_persons` | `pp.source_layer = 'isnad' AND (...)` | البحث المتخصص في سلاسل الرواية والأسانيد. |
| `--place "<المكان>"` | `passage_places` + `places` | `ppl.canonical_name LIKE ? OR ppl.mentioned_name LIKE ? OR pl.aliases_json LIKE ?` | حصر البحث في أحداث أو تراجم مرتبطة ببلد أو إقليم محدد. |
| `--year-min <H>`<br/>`--year-max <H>` | `events_chronology` | `ec.event_layer = 'historical' AND ec.year_hijri >= ? AND ec.year_hijri <= ?` | الفلترة الزمنية الدقيقة بالقرون والسنوات الهجرية مع عزل تواريخ نسخ المخطوطات (`transmission`). |
| `--surah <N>`<br/>`--ayah <S:A>` | `evidences` | `ev.surah_number = ?` أو `(ev.surah_ayah_key = ? OR (ev.surah_number = ? AND ev.ayah_start <= ? AND ev.ayah_end >= ?))` | استرجاع جميع المقاطع والشروح التي تستدل بآية قرآنية محددة. |
| `--science <science>`<br/>`--source-type <type>` | `sources` | `s.science = ? AND s.source_type = ?` | حصر البحث في علم محدد (`maliki`, `akida`, `ossoul`...) أو نوع مصدر (`book`, `lecture`, `course`). |
| `--matn-clause <id>` | `matn_triangulation` | `mt.explained_matn_clause_id = ?` | استرجاع جميع شروح فقرة متن معينة (مثل `"UB:2"` في أم البراهين أو `"AKH:1"` في الأخضري) عبر الكتب والدروس الصوتية. |

---

## 5. المحرك المحلي الحتمي المسرّع (`DeterministicArabicGemma2Embedder`)

لضمان عمل المنظومة وبوابات الفحص (`Quality Gates`) بسرعة فائقة (`< 0.1` ثانية) وبصفر اعتماد على الاتصال الخارجي عند عدم توفر خادم `Ollama` أو `GenAI`، يوفر `scripts/embed_corpus_gemma2.py` فئة `DeterministicArabicGemma2Embedder` المبنية على أربع طبقات تمثيل دلالي عربي في فضاء `dim=768`:

1. **طبقة الجذور والتجريد الصرفي العربي (`Arabic Light Stemmer & Consonantal Root Projection`):**
   - تجرد السوابق (`ال`, `وال`, `بال`, `كال`, `فال`, `لل`, `س`) واللواحق (`ون`, `ين`, `ات`, `ان`, `هم`, `ها`, `كم`, `ية`, `ه`, `ي`) وتستخلص الهيكل الصامت للكلمتين والجذر الثلاثي/الرباعي.
2. **طبقة المفردات الدقيقة والتراكيب الثنائية (`Exact Word Unigrams & Phrase Bigrams`):**
   - تمثّل الألفاظ التراثية الدقيقة والتراكيب الثنائية المتتالية (`Word 2-grams`) بأوزان عالية لحسم المطابقات الحرفية في `vec_matn`.
3. **طبقة المقاطع الحرفية (`Character 3-grams & 4-grams`):**
   - تمنح المتجه مناعةً ضد اختلافات التصريف والجموع المكسرّة والهمزات.
4. **طبقة إسقاط العناقيد المفهومية التراثية-المعاصرة (`Semantic Concept Cluster Projection`):**
   - تربط المصطلحات التراثية بمكافئاتها المفهومية المعاصرة في أبعاد دلالية مشتركة (مثل ربط `المشقة / التيسير / الحرج` بـ `الرخص الشرعية / المرض / السفر / العذر`، وربط `الواجب العقلي / المستحيل / الجائز` بـ `الأحكام العقلية / علم الكلام / البرهان`، وربط `تغير الأحكام / الأزمان / العوائد` بـ `تغير الفتوى / العرف / البيئة المعاصرة`).
5. **التطبيع الشعاعي المسرّع (`MPS / NumPy L2 Normalization`):**
   - تُسقط جميع السمات في متجه كثيف `float32` بطول `768` وتُطبّع عبر `torch` (`MPS`/`CPU`) أو `numpy` بحيث يتحقق الشرط الصارم $\|\mathbf{v}\|_2 = 1.0 \pm 10^{-5}$.
