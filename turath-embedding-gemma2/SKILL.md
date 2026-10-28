---
name: turath-embedding-gemma2
description: >-
  Use when cleaning Islamic heritage texts (expanding Unicode honorific ligatures U+FD40..U+FDFF, NFC/NFKC normalization, stripping invisible directional markers), isolating isnad narrator chains from matn text, indexing passages in SQLite with FTS5 and float32 BLOB vectors, fusing ranks via Reciprocal Rank Fusion (RRF), or running strictly verified local embedding models (sentence-transformers or mlx) with zero fake hashing and zero external API keys.
version: 2.0
---

# مهارة `turath-embedding-gemma2`: تطهير النصوص التراثية والفهرسة الهجينة (`SQLite FTS5 + RRF`) والتضمين المحلي الصادق

توفر هذه المهارة النواة الهندسية المطهرة والصادقة لتجهيز النصوص التراثية والدروس العلمية، وفصل سلاسل الإسناد عن المتون، وبناء الفهارس الهجينة في `SQLite` (`FTS5` مع أعمدة متجهات `float32 BLOB`)، ودمج الترتيب التبادلي (`Reciprocal Rank Fusion — RRF`)، مع واجهة تضمين محلي صريحة ترفض أي تضمين وهمي أو اتصال سحابي خارجي.

## 1. الضوابط الهندسية الصارمة والصدق المعماري

1. **منع التضمين الوهمي والمفاتيح الخارجية (`Zero Fake Hashing & Zero Cloud APIs`)**:
   1. يُحظر منعاً باتاً استخدام أي دوال تجزئة وهمية (`SHA-256` أو `DeterministicArabicGemma2Embedder`) لتوليد متجهات شكلية لا تحمل دلالة حقيقية.
   2. يُحظر منعاً باتاً حشر قواميس مرادفات يدوية صلبة (`CONCEPT_SYNONYM_CLUSTERS`) لإيهام الفاحص بنجاح الاسترجاع الدلالي.
   3. يُحظر منعاً باتاً استخدام أي مفاتيح سحابية خارجية (`Gemini API` أو غيرها) لتوليد المتجهات؛ التضمين يتم محلياً بالكامل عبر نموذج محلي حقيقي موجود على القرص (`sentence-transformers` أو `mlx`).
   4. إذا لم يتوفر مسار النموذج المحلي الحقيقي على القرص، ترفع فئة `LocalModelEmbedder` استثناءً صريحاً (`RuntimeError`) ولا تلجأ لأي بديل وهمي صامت.
2. **الفصل الثلاثي للتخزين والترويسة السياقية (`3-Layer Storage & Contextual Header`)**:
   1. الحفاظ على `source_text` (النص الأصلي الخام كما ورد في المصدر) دون مساس.
   2. توليد `content` و`clean_matn` بعد تطهير النص وفصل الإسناد للعرض والفهرسة المعجمية في `FTS5`.
   3. بناء `embedding_input` بإرفاق الترويسة السياقية المحايدة (`الكتاب | المصنف | الباب`) قبل المتن الصافي لمنع اختلاط الأقوال المحكية بقول المصنف.

## 2. المكونات الهندسية في `scripts/turath_text_hygiene_and_fts.py`

1. **تطهير النص التراثي وتوسيع الرموز المدمجة (`expand_honorific_ligatures` و`clean_hygienic_arabic_text`)**:
   1. تفكيك جميع محارف الترضية والتصلية والترحم المدمجة في يونيكود (`U+FD40..U+FD4F` و`U+FDFA..U+FDFF` عبر `HONORIFIC_LIGATURE_MAP` مثل `ﷺ` إلى `صلى الله عليه وسلم`، و`ﷻ` إلى `جل جلاله`، و`﵁` إلى `رضي الله عنه`) حتى لا تتحول إلى رموز مجهولة في النموذج أو تفشل في البحث النصي.
   2. إزالة محارف الاتجاه الخفية (`U+200F`, `U+061C`, `U+FEFF`, `U+200E`) والكشيدة (`U+0640`).
   3. تطبيع النص قياسياً بـ `NFKC` أو `NFC` وتوحيد الأرقام إلى الأرقام العربية المشرقية (`0, 1, 2... 9`) وإزالة أختام الصفحات والحواشي الطباعية (`[ص: 12]`, `⦗12⦘`, `(¬1)`).
2. **فصل سلسلة الإسناد عن المتن (`split_isnad_and_matn`)**:
   1. عزل سلسلة الرواية الابتدائية (`حدثنا... أخبرنا... ثنا... عن... قال:`) في حقل مستقل (`isnad_prefix`).
   2. الاحتفاظ بمتن الخبر الصافي في `clean_matn` لمنع طغيان أسماء الرواة المتكررة على التمثيل الدلالي لموضوع المتن.
3. **مخطط `SQLite FTS5` وتخزين المتجهات (`init_sqlite_fts_and_vectors`)**:
   1. إنشاء جدول `passages` الذي يضم الحقول النصية المفصولة (`source_text`, `content`, `isnad_prefix`, `clean_matn`, `embedding_input`) مع عمود المتجهات `vec_matn_blob` بصيغة `float32 BLOB`.
   2. إنشاء جدول البحث النصي الافتراضي `passages_fts` بمحرك `FTS5` ومقطع `unicode61`.
   3. توفير دالتي `vector_to_f32_blob` و`f32_blob_to_vector` مع التحقق الصارم من خلو المتجهات من قيم `NaN` أو `Inf` والتطبيع الرياضي `L2`.
4. **دمج الترتيب التبادلي (`compute_rrf_scores`)**:
   1. دمج قوائم النتائج المرتبة من البحث المعجمي (`FTS5 BM25`) والبحث الشعاعي المحلي عبر معادلة `Reciprocal Rank Fusion` القياسية بثابت `k = 60` وأوزان قنوات قابلة للضبط.
5. **واجهة التضمين المحلي الصريحة (`LocalModelEmbedder`)**:
   1. تشترط تمرير مسار محلي موجود فعلياً على القرص (`model_path`) ومحرك محلي (`sentence-transformers` أو `mlx`).
   2. تتحقق من وجود الملفات محلياً (`local_files_only=True`) وترفع `RuntimeError` واضحاً عند غياب النموذج أو المكتبة.

## 3. طريقة التشغيل والتحقق (`CLI Usage`)

1. **عرض تعليمات الأداة والخيارات المتاحة**:
   ```bash
   python3 scripts/turath_text_hygiene_and_fts.py --help
   ```
2. **تهيئة قاعدة بيانات `SQLite` بجدول المقاطع وفهرس `FTS5`**:
   ```bash
   python3 scripts/turath_text_hygiene_and_fts.py --init-db /path/to/turath.sqlite
   ```
3. **اختبار تطهير نص تراثي وفصل الإسناد عن المتن**:
   ```bash
   python3 scripts/turath_text_hygiene_and_fts.py --sample-text "حدثنا قتيبة بن سعيد قال: قال رسول الله ﷺ: إنما الأعمال بالنيات [ص: 12]"
   ```

## 4. المراجع الهندسية

1. **مرجع التطهير النصي والدمج الهجين**: `references/01-dual-embedding-and-hybrid-retrieval.md` — يوثق خريطة الرموز التراثية المدمجة، وقواعد عزل الإسناد، ومخطط `SQLite FTS5`، ومعادلة `RRF`.
