# 07 — معمارية قاعدة بيانات الكيانات العلائقية (`Entity DB SQLite + FTS5 Schema`)

يوثق هذا المرجع المخطط العلائقي القياسي لقاعدة بيانات الكيانات الموحدة **`objects.sqlite` (`SQLite + FTS5`)** داخل مهارة `turath-deep-indexing`، والتي توحد مخرجات الكتب التراثية (`merge_round.py`) والدروس المرئية (`merge_lecture.py`) والدورات التقنية (`merge_course.py`) والجسر المعرفي (`build_cross_corpus_graph.py`) في `11` جدولاً علائقياً مترابطاً جاهزاً للربط مع محرك المتجهات `turath-embedding-gemma2`.

---

## 1. المخطط العلائقي القياسي لقاعدة بيانات الكيانات (`objects.sqlite` — 11 جدولاً + `FTS5`)

تُبنى قاعدة بيانات `SQLite` العلائقية القياسية بالأسماء والأعمدة الدقيقة التالية لضمان التوافق التام مع `turath-embedding-gemma2`:

### 1. جدول المصادر الكلية (`sources`)
```sql
CREATE TABLE sources (
    source_id TEXT PRIMARY KEY,
    source_type TEXT,
    title TEXT,
    author_or_sheikh TEXT,
    science TEXT,
    archetype TEXT,
    metadata_json TEXT
);
```

### 2. جدول السلاسل الصوتية والمرئية (`series`)
```sql
CREATE TABLE series (
    series_id TEXT PRIMARY KEY,
    source_id TEXT,
    title TEXT,
    sheikh TEXT,
    science TEXT,
    state TEXT,
    total_lessons INTEGER,
    metadata_json TEXT
);
```

### 3. جدول الدروس أو أجزاء الكتب (`lessons_or_parts`)
```sql
CREATE TABLE lessons_or_parts (
    part_id TEXT PRIMARY KEY,
    source_id TEXT,
    series_id TEXT,
    part_number INTEGER,
    title TEXT,
    yt_id TEXT,
    dur_s REAL,
    page_start INTEGER,
    page_end INTEGER,
    raw_char_count INTEGER
);
```

### 4. جدول المقاطع الموضوعية (`passages`) وجدول البحث النصي الفوري (`passages_fts`)
```sql
CREATE TABLE passages (
    passage_id TEXT PRIMARY KEY,
    source_id TEXT,
    series_id TEXT,
    part_id TEXT,
    part_number INTEGER,
    passage_index INTEGER,
    sub_heading TEXT,
    raw_text TEXT,
    clean_matn TEXT,
    isnad_prefix TEXT,
    summary TEXT,
    topics_json TEXT,
    search_queries_json TEXT,
    start_sec REAL,
    end_sec REAL,
    youtube_timestamp_url TEXT,
    page_num INTEGER,
    embed_matn_text TEXT,
    embed_concept_text TEXT
);

CREATE VIRTUAL TABLE passages_fts USING fts5(
    passage_id UNINDEXED,
    sub_heading,
    raw_text,
    clean_matn,
    summary,
    topics_text,
    search_queries_text
);
```

### 5. جدول الأعلام الموحدين (`persons`) وجدول ربط الأعلام بالمقاطع (`passage_persons`)
```sql
CREATE TABLE persons (
    person_id TEXT PRIMARY KEY,
    canonical_name TEXT,
    role_or_sect TEXT,
    death_year_hijri INTEGER,
    aliases_json TEXT
);

CREATE TABLE passage_persons (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    passage_id TEXT,
    person_id TEXT,
    mentioned_name TEXT,
    canonical_name TEXT,
    source_layer TEXT CHECK(source_layer IN ('isnad', 'matn')),
    role TEXT
);
```
- **الفصل الصارم بين السند والمتن:** يحمل كل ظهور لعَلَم في `passage_persons` وسم `source_layer` مقيداً بـ `CHECK(source_layer IN ('isnad', 'matn'))`، مما يتيح استبعاد رواة الأسانيد عند البحث عن أعلام المتن أو العكس.
- **التوحيد القياسي الذكي للأعلام:** يعتمد دالة `canonicalize_person` من `build_cross_corpus_graph.py` مع حماية الكنى المشتركة (`أبو بكر / ابن عمر / عبد الله`) من التصادم الجزئي مع الأعلام المركبة (`أبو بكر البيهقي / أبو بكر بن العربي / أبو عبد الله السنوسي`).

### 6. جدول الأماكن والبلدان (`places`) وجدول ربطها بالمقاطع (`passage_places`)
```sql
CREATE TABLE places (
    place_id TEXT PRIMARY KEY,
    canonical_name TEXT,
    region_or_type TEXT,
    aliases_json TEXT
);

CREATE TABLE passage_places (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    passage_id TEXT,
    place_id TEXT,
    mentioned_name TEXT,
    canonical_name TEXT
);
```

### 7. جدول الحوليات والتواريخ الهجرية (`events_chronology`)
```sql
CREATE TABLE events_chronology (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    passage_id TEXT,
    source_id TEXT,
    year_hijri INTEGER,
    year_raw TEXT,
    is_approximate INTEGER,
    event_title TEXT,
    event_layer TEXT CHECK(event_layer IN ('historical', 'transmission'))
);
```
- يميز حقل `event_layer` بصرامة بين التواريخ التاريخية/البيوغرافية (`'historical'`) وتواريخ سماع المخطوطات والرواية (`'transmission'`).

### 8. جدول القصص والمسائل التطبيقية (`stories_cases`)
```sql
CREATE TABLE stories_cases (
    story_id INTEGER PRIMARY KEY AUTOINCREMENT,
    passage_id TEXT,
    source_id TEXT,
    part_number INTEGER,
    story_type TEXT,
    title TEXT,
    anchor_start TEXT,
    summary TEXT,
    lesson TEXT
);
```

### 9. جدول الدرر والقواعد التأصيلية (`science_gems`)
```sql
CREATE TABLE science_gems (
    gem_id TEXT PRIMARY KEY,
    passage_id TEXT,
    source_id TEXT,
    part_number INTEGER,
    title TEXT,
    category TEXT,
    verbatim_rule TEXT,
    polished_rule TEXT,
    explanation TEXT,
    start_sec REAL,
    end_sec REAL,
    youtube_timestamp_url TEXT
);
```

### 10. جدول الأدلة والشواهد القرآنية والحديثية (`evidences`)
```sql
CREATE TABLE evidences (
    evidence_id INTEGER PRIMARY KEY AUTOINCREMENT,
    passage_id TEXT,
    source_id TEXT,
    evidence_type TEXT,
    surah_number INTEGER,
    ayah_start INTEGER,
    ayah_end INTEGER,
    surah_ayah_key TEXT,
    verbatim_text TEXT,
    hadith_source TEXT,
    footnote_ref TEXT
);
```

### 11. جدول تثليث المتون والشروح (`matn_triangulation`)
```sql
CREATE TABLE matn_triangulation (
    triangulation_id INTEGER PRIMARY KEY AUTOINCREMENT,
    passage_id TEXT,
    source_id TEXT,
    explained_matn_book_id TEXT,
    explained_matn_clause_id TEXT,
    explained_matn_verbatim TEXT,
    start_sec REAL,
    end_sec REAL
);
```

### 12. الفهارس العلائقية الإلزامية (`Indexes`)
تُنشأ فهارس تسريع البحث والربط على جميع المفاتيح الأساسية:
1. الفهرس `passage_id` في جميع الجداول الفرعية (`passage_persons`, `passage_places`, `events_chronology`, `stories_cases`, `science_gems`, `evidences`, `matn_triangulation`).
2. الفهرس `person_id` و`source_layer` في `passage_persons`.
3. الفهرس `place_id` في `passage_places`.
4. الفهرس `year_hijri` في `events_chronology`.
5. الفهرس `surah_ayah_key` في `evidences`.
6. الفهرس `explained_matn_clause_id` و`explained_matn_book_id` في `matn_triangulation`.
