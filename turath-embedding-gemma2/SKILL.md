---
name: turath-embedding-gemma2
description: >-
  Use when generating Dual-Vector Embeddings (EmbeddingGemma 2: vec_matn + vec_concept) for Islamic heritage books, spoken video lectures, and educational courses in SQLite, enforcing Dual Text Hygiene (stripping U+FD40..U+FD4F ligatures, page markers, and isolating isnad transmitters from concept embeddings), or executing Hybrid Search combining SQLite FTS5 BM25, Dual EmbeddingGemma 2 Cosine Similarity (MPS/NumPy), Reciprocal Rank Fusion (RRF), and strict Relational Entity Filters.
version: 1.0
---

# مهارة `turath-embedding-gemma2`: التضمين الشعاعي المزدوج بـ `EmbeddingGemma 2` والاسترجاع الهجين المعرفي

تمثل هذه المهارة **المواصفة الهندسية والمحرك التنفيذي** لطبقة التضمين الشعاعي المزدوج (`Dual-Vector Representation`) والبحث الهجين العلائقي (`Hybrid Search + Relational Entity Filtering`) فوق قواعد بيانات الكيانات الموحدة (`SQLite`) التي تنتجها منظومة `turath-deep-indexing`.

> **ملاحظة تشغيلية:** جميع السكربتات في `scripts/` مكتفية ذاتياً (`Self-Contained`)، وتعمل على `macOS` (`Apple Silicon MPS` / `NumPy`) وخوادم `Linux`، وتدعم التبديل التلقائي بين المحركات الحية (`Ollama` / `SentenceTransformers` / `Google GenAI`) والمحرك المحلي الحتمي المسرّع (`DeterministicArabicGemma2Embedder`) للعمل دون اتصال بالإنترنت (`Offline / Gate Testing`).

---

## 1. الفلسفة المعمارية: لماذا التضمين الشعاعي المزدوج (`Dual-Vector Representation`)؟

تعاني أنظمة الاسترجاع التقليدية أحادية المتجه (`Single-Vector RAG`) في التراث الإسلامي والدروس العلمية من تناقض بنيوي حاد:
1. **فجوة العبارة التراثية مقابل السؤال المعاصر (`Lexical-Conceptual Chasm`):**
   - المتن التراثي يُصاغ بلغة классиكية مكثفة أو بألفاظ الحديث والمتون (مثل: *«المشقة تجلب التيسير»*، *«الواجب العقلي ما لا يتصور في العقل عدمه»*، *«لا ينكر تغير الأحكام بتغير الأزمان»*).
   - الباحث المعاصر قد يبحث **بنص العبارة التراثية حرفياً**، أو يبحث **بسؤال مفهومي معاصر** (مثل: *«ما ضوابط الرخص الشرعية عند المرض والسفر؟»* أو *«أثر تغير العرف والبيئة في الفتوى الفقهية»*).
   - دمج المتن الأصلي والملخص التحليلي في متجه واحد يُضعف دقة المتجه في الحالتين معاً.
2. **تلوث المتجهات برواة الإسناد ورموز الطباعة (`Isnad & Typographical Pollution`):**
   - في كتب الحديث والتراجم والتاريخ، تتكرر أسماء رواة السند (`حدثنا قتيبة بن سعيد عن مالك...`) في آلاف المقاطع؛ فإذا دخلت في متجه المفهوم أو لم تُعزل عن المتن، طغى تشابه السند على موضوع المقطع.
   - كما أن محارف الترضية المدمجة في يونيكود (`\ufd40..\ufd4f` مثل `﵀` و`﵁`) وعلامات الصفحات (`[ص: ١٢٣]`, `صفحة ١٣٧`, `⦗١١٣⦘`) وحواشي `(¬١)` تشوّه تقطيع الكلمات (`Tokenization`) في نماذج التضمين.

لذلك تعتمد هذه المهارة **معمارية المتجهين المستقلين (`Dual-Vector Architecture`)** لكل مقطع (`passage`) ولكل قاعدة علمية (`science_gem`):

| المتجه | الحقل المصدري | الوظيفة الدلالية ومحتواه الدقيق | متى يتصدر في البحث؟ |
| :--- | :--- | :--- | :--- |
| **متجه المتن (`vec_matn`)** | `embed_matn_text` | يُولَّد من النص الأصلي الصافي (`clean_matn`) بعد تجريد سلسلة الإسناد الابتدائي (`isnad_prefix`) والأسانيد الداخلية، وفك محارف الترضية المدمجة (`\ufd40..\ufd4f` و`\ufdfa..\ufdff`) إلى كلمات عربية قياسية، وحذف علامات الصفحات (`[ص: N]`, `صفحة N`, `⦗N⦘`) ورموز الحواشي `(¬N)`. | عند البحث بعبارة تراثية، نص حديث، شاهد، بيت شعري، أو جملة من متن مشروح. |
| **متجه المفهوم (`vec_concept`)** | `embed_concept_text` | يُولَّد من العنوان الفرعي (`sub_heading`) + الملخص التحليلي (`summary`) + الموضوعات (`topics`) + القواعد المصقولة (`polished_rule`) + الأسئلة البحثية (`search_queries`) + أعلام المتن (`source_layer='matn'`) + الأماكن (`places`) + التواريخ التاريخية (`event_layer='historical'`)، **مع الاستبعاد الصارم لرواة الإسناد (`source_layer='isnad'`) وتواريخ النسخ والسماع (`event_layer='transmission'`)**. | عند البحث بسؤال مفهومي معاصر، مسألة فقهية أو عقدية، أو مصطلح تحليلي. |

---

## 2. مخطط تخزين المتجهات في SQLite (`Vector Storage Schema`)

يتكامل محرك `embed_corpus_gemma2.py` مع الجداول الإحدى عشرة القياسية التي يبنيها `build_objects_sqlite.py` في `turath-deep-indexing`، ويضيف إليها جدولَي متجهات مدمجين بصيغة `float32 BLOB` مطبّعة مسبقاً بـ `L2-Norm` (`||v||_2 = 1.0`):

### أ. جدول متجهات المقاطع (`passage_embeddings`):
```sql
CREATE TABLE IF NOT EXISTS passage_embeddings (
    passage_id TEXT PRIMARY KEY,
    model_name TEXT NOT NULL,
    dim INTEGER NOT NULL,
    embed_matn_text TEXT NOT NULL,
    embed_concept_text TEXT NOT NULL,
    vec_matn_blob BLOB NOT NULL,
    vec_concept_blob BLOB NOT NULL,
    matn_norm REAL NOT NULL,
    concept_norm REAL NOT NULL,
    FOREIGN KEY (passage_id) REFERENCES passages(passage_id)
);
```

### ب. جدول متجهات القواعد والدرر العلمية (`gem_embeddings`):
```sql
CREATE TABLE IF NOT EXISTS gem_embeddings (
    gem_id TEXT PRIMARY KEY,
    passage_id TEXT NOT NULL,
    model_name TEXT NOT NULL,
    dim INTEGER NOT NULL,
    embed_matn_text TEXT NOT NULL,
    embed_concept_text TEXT NOT NULL,
    vec_matn_blob BLOB NOT NULL,
    vec_concept_blob BLOB NOT NULL,
    FOREIGN KEY (gem_id) REFERENCES science_gems(gem_id),
    FOREIGN KEY (passage_id) REFERENCES passages(passage_id)
);
```

### ج. تسريع تشابه جيب التمام (`Accelerated Cosine Similarity`):
- بما أن كل متجه مخزن في `vec_matn_blob` و`vec_concept_blob` مطبّع مسبقاً على كرة الوحدة (`||v||_2 == 1.0 ± 1e-5`) بصيغة `float32`، فإن حساب تشابه جيب التمام (`Cosine Similarity`) يختزل إلى عملية ضرب قياسي مباشر (`Dot Product / Matrix-Vector Multiplication`):
  $$\text{cos\_sim}(q, d) = \langle \hat{q}, \hat{d} \rangle = \mathbf{D} \cdot \hat{q}$$
- ينفذ المحرك هذه العملية دفعةً واحدة (`Vectorized MatMul`) عبر `torch` على شريحة `Apple Silicon MPS` أو `CPU`، أو عبر `numpy.matmul` في أقل من ملي ثانية لآلاف المقاطع.

---

## 3. معمارية البحث الهجين (`Hybrid Search + RRF + Entity Filters`)

يدمج محرك `scripts/hybrid_search.py` أربع طبقات استرجاع في خط أنابيب واحد:

```mermaid
flowchart TD
    Q["استعلام الباحث + فلاتر الكيانات الاختيارية"] --> EF["1. الفلترة العلائقية المسبقة (SQL Entity Filters)<br/>person (matn/isnad) | place | year_min..max | surah/ayah | science | source_type | matn_clause"]
    EF --> FTS["2. البحث المعجمي الحرفي<br/>SQLite FTS5 BM25 (passages_fts)"]
    EF --> VMATN["3. البحث الدلالي في المتن<br/>Cosine(q_vec, vec_matn)"]
    EF --> VCONC["4. البحث الدلالي في المفهوم<br/>Cosine(q_vec, vec_concept)"]
    FTS --> FUSE["5. دمج الرتب والدرجات الهجين<br/>Weighted Score + Reciprocal Rank Fusion (RRF)<br/>(alpha_matn, alpha_concept, alpha_fts)"]
    VMATN --> FUSE
    VCONC --> FUSE
    FUSE --> OUT["6. إثراء النتائج الكاملة<br/>المتن + الملخص + القواعد + التوقيت الصوتي ورابط يوتيوب / رقم الصفحة + الكيانات"]
```

1. **الطبقة الأولى — الفلترة العلائقية الصارمة بالكيانات (`Relational Entity Filters`):**
   - `--person "<اسم العلم>"` مع `--person-layer matn|isnad|any` (**الافتراضي `'matn'`** لمنع تلوث نتائج البحث بالمقاطع التي ورد فيها العلم راوياً في السند فقط!).
   - `--place "<اسم المكان>"` عبر جدولَي `passage_places` و`places`.
   - `--year-min <H>` و`--year-max <H>` عبر جدول `events_chronology` مع اشتراط `event_layer = 'historical'` لاستبعاد تواريخ نسخ المخطوطات.
   - `--surah <N>` أو `--ayah <surah:ayah>` عبر جدول `evidences`.
   - `--science <science>` و`--source-type <book|lecture|course>` عبر جدول `sources`.
   - `--matn-clause <clause_id>` عبر جدول `matn_triangulation` لاسترجاع جميع الشروح الصوتية والمكتوبة لفقرة متن محددة.
2. **الطبقة الثانية — البحث النصي الحرفي (`FTS5 BM25`):**
   - يستعلم من جدول `passages_fts` مع تطهير آلي لعلامات الترقيم والاستفهام وبناء استعلام هجين (`Phrase / AND / OR`) وحساب درجات `BM25` المطبّعة.
3. **الطبقة الثالثة — البحث الدلالي المزدوج (`Dual EmbeddingGemma 2`):**
   - يولّد متجه الاستعلام ببادئة المهمة القياسية: `task: search query | query: {query}`، ثم يحسب `sim_matn` و`sim_concept` عبر ضرب المصفوفات المسرّع.
4. **الطبقة الرابعة — الدمج الهجين (`Weighted Score + Reciprocal Rank Fusion RRF`):**
   - يجمع بين الدرجات المطبّعة ورتب `RRF` ($\sum_{c \in \{\text{matn}, \text{concept}, \text{fts}\}} \frac{\alpha_c}{k + \text{rank}_c(d)}$) مع قابلية التحكم الكامل بالأوزان (`--alpha-matn`, `--alpha-concept`, `--alpha-fts`).

---

## 4. الأدوات التنفيذية في المهارة (`scripts/`)

| السكربت | الوظيفة الدقيقة |
| :--- | :--- |
| [`scripts/embed_corpus_gemma2.py`](./scripts/embed_corpus_gemma2.py) | محرك تجهيز النصوص (`prepare_embed_matn_text`, `prepare_embed_concept_text`) وتوليد المتجهات المزدوجة (`passage_embeddings`, `gem_embeddings`) بدعم `--backend auto\|ollama\|sentence-transformers\|genai\|deterministic-arabic-mps`. |
| [`scripts/hybrid_search.py`](./scripts/hybrid_search.py) | محرك البحث الهجين (`HybridSearchEngine` + `CLI`) الذي يدمج `FTS5 BM25` + `vec_matn` + `vec_concept` + `RRF` + فلاتر الكيانات العلائقية ويعيد التوقيت الصوتي بالثانية وروابط يوتيوب وأرقام الصفحات. |
| [`scripts/test_embedding_gemma2_gates.py`](./scripts/test_embedding_gemma2_gates.py) | بوابة الفحص الحتمية ثلاثية الطبقات (`Gate 1: Hygiene & L2 Norm`, `Gate 2: Matn vs Concept Retrieval`, `Gate 3: Hybrid + Entity Filters & Isnad Isolation`). |

---

## 5. أوامر التشغيل السريع (`Quick Start CLI`)

### أ. توليد وفهرسة التضمين المزدوج لقاعدة بيانات SQLite:
```bash
python3 /Users/macm1pro/REPOS/SKILLS/turath-embedding-gemma2/scripts/embed_corpus_gemma2.py \
  --db /path/to/turath_objects.sqlite \
  --backend auto \
  --dim 768
```

### ب. تشغيل البحث الهجين مع الفلترة العلائقية وعزل السند:
```bash
python3 /Users/macm1pro/REPOS/SKILLS/turath-embedding-gemma2/scripts/hybrid_search.py \
  --db /path/to/turath_objects.sqlite \
  --query "حكم الرخص الشرعية وتغير الفتوى" \
  --person "مالك بن أنس" \
  --person-layer matn \
  --top-k 5
```

### ج. تشغيل بوابة الفحص الحتمية (`3-Layer Quality Gate`):
```bash
python3 /Users/macm1pro/REPOS/SKILLS/turath-embedding-gemma2/scripts/test_embedding_gemma2_gates.py
```

---

## 6. المراجع الهندسية التفصيلية

- **[`references/01-dual-embedding-and-hybrid-retrieval.md`](./references/01-dual-embedding-and-hybrid-retrieval.md)** — المرجع الهندسي الكامل لبادئات المهام في `EmbeddingGemma 2`، خوارزميات التنظيف المزدوج، معادلات الدمج الهجين (`Weighted + RRF`)، وجداول الفلترة العلائقية.
