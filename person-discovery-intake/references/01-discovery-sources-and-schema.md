# المرجع التقني الأول: مصادر الاكتشاف الخمسة ومخطط البيانات القياسي (`<person_id>_raw.json`)

يوثق هذا المرجع البنية الدقيقة لملف المخرجات `<person_id>_raw.json`، وبروتوكولات الجلب البرمجي من يوتيوب و`Archive.org`، وخوارزمية فك تيارات ملفات `PDF` الفهرسية (`FlateDecode` + `/URI`)، وقواعد مطابقة السلاسل بالكتب والمتون العلمية.

---

## 1. مخطط البيانات المعياري لملف `<person_id>_raw.json` (`Canonical Schema`)

صُمم مخطط `<person_id>_raw.json` ليكون **مزدوج التوافق 100%**:
- يوفر الحقول الشاملة لخط أنابيب الاكتشاف (`person_id`, `sheikh_name`, `discovered_at`, `channels`, `playlists`, `videos`, `archive_items`, `pdf_extracted_links`, `books`, `stats`).
- ويوفر في الوقت ذاته الحقول القياسية التي تستهلكها سكربتات `sheikh-curation` مباشرة (`sheikh`, `raw_playlists_count`, `unique_videos_count`, `raw_series`, `unique_videos`).

### مثال هيكلي كامل للمخطط (`JSON Schema Instance`):

```json
{
  "person_id": "sariri",
  "sheikh_name": "مولود السريري",
  "discovered_at": "2026-10-18T09:30:00Z",
  "sheikh": {
    "id": "sariri",
    "order_no": 1,
    "name": "مولود السريري",
    "short_name": "السريري",
    "photo": "https://medmrf-10.github.io/hawshat/playlists/img/mouloud-sariri.jpg",
    "created_at": "2026-10-18 09:30:00"
  },
  "channels": [
    {
      "channel_id": "UC_example_channel_id_01",
      "channel_key": "sariri-personal",
      "title": "القناة الرسمية للشيخ مولود السريري",
      "url": "https://www.youtube.com/channel/UC_example_channel_id_01",
      "source_type": "youtube_channel",
      "playlists_count": 60,
      "uploads_count": 4513
    }
  ],
  "playlists": [
    {
      "id": "PL4Tn64l1hKwl-OYjCv7Oo0sRcRF7pnZN1",
      "playlist_id": "PL4Tn64l1hKwl-OYjCv7Oo0sRcRF7pnZN1",
      "order_no": 1,
      "title": "شرح كتاب إيصال السالك في أصول الإمام مالك",
      "yt_playlist_id": "PL4Tn64l1hKwl-OYjCv7Oo0sRcRF7pnZN1",
      "url": "https://www.youtube.com/playlist?list=PL4Tn64l1hKwl-OYjCv7Oo0sRcRF7pnZN1",
      "source_type": "youtube_playlist",
      "state": "completed",
      "expected_count": 24,
      "video_count": 24,
      "note": "تصنيف: شرح / سلسلة علمية",
      "matched_book": {
        "book_id": "ossoul:iysal_al_salik",
        "title": "إيصال السالك في أصول الإمام مالك",
        "author": "محمد يحيى الولاتي",
        "science": "أصول الفقه",
        "confidence": 0.96
      },
      "videos": [
        {
          "pos": 1,
          "vid": "pXUZMVKJqtg",
          "yt_id": "pXUZMVKJqtg",
          "title": "الدرس 1: مقدمة كتاب إيصال السالك",
          "dur_s": 4089,
          "duration": 4089,
          "upload_date": "20210301"
        }
      ]
    }
  ],
  "videos": [
    {
      "vid": "pXUZMVKJqtg",
      "yt_id": "pXUZMVKJqtg",
      "title": "الدرس 1: مقدمة كتاب إيصال السالك",
      "yt_url": "https://www.youtube.com/watch?v=pXUZMVKJqtg",
      "dur_s": 4089,
      "duration": 4089,
      "upload_date": "20210301",
      "playlist_id": "PL4Tn64l1hKwl-OYjCv7Oo0sRcRF7pnZN1",
      "playlist_title": "شرح كتاب إيصال السالك في أصول الإمام مالك",
      "source_type": "youtube_playlist",
      "has_transcript": 0,
      "has_summary": 0,
      "has_questions": 0,
      "matched_book": {
        "book_id": "ossoul:iysal_al_salik",
        "title": "إيصال السالك في أصول الإمام مالك",
        "author": "محمد يحيى الولاتي",
        "science": "أصول الفقه",
        "confidence": 0.96
      },
      "appearances": [
        {
          "raw_series_id": "PL4Tn64l1hKwl-OYjCv7Oo0sRcRF7pnZN1",
          "raw_series_title": "شرح كتاب إيصال السالك في أصول الإمام مالك",
          "pos": 1,
          "is_unclassified": false
        }
      ]
    }
  ],
  "archive_items": [
    {
      "item_id": "iysalo-salik_202103",
      "title": "شرح كتاب إيصال السالك في أصول الإمام مالك",
      "creator": "مولود السريري",
      "uploader": "admin@assariry.com",
      "mediatype": "audio",
      "metadata_url": "https://archive.org/metadata/iysalo-salik_202103",
      "details_url": "https://archive.org/details/iysalo-salik_202103",
      "audio_files_count": 24,
      "total_duration_s": 74200,
      "matched_book": {
        "book_id": "ossoul:iysal_al_salik",
        "title": "إيصال السالك في أصول الإمام مالك",
        "author": "محمد يحيى الولاتي",
        "science": "أصول الفقه",
        "confidence": 0.96
      },
      "files": [
        {
          "name": "001.mp3",
          "title": "الدرس 1: مقدمة الكتاب",
          "format": "VBR MP3",
          "dur_s": 3120,
          "duration": 3120,
          "size": 24960000,
          "direct_url": "https://archive.org/download/iysalo-salik_202103/001.mp3",
          "vid": "archive__sariri__iysalo_salik_202103__ep001",
          "yt_id": "archive__sariri__iysalo_salik_202103__ep001"
        }
      ]
    }
  ],
  "pdf_extracted_links": [
    {
      "url": "https://www.youtube.com/playlist?list=PL9saDKf7tQ7uPlqhlafX3tRbnr4oKrvQG",
      "resolved_url": "https://www.youtube.com/playlist?list=PL9saDKf7tQ7uPlqhlafX3tRbnr4oKrvQG",
      "link_type": "youtube_playlist",
      "playlist_id": "PL9saDKf7tQ7uPlqhlafX3tRbnr4oKrvQG",
      "video_id": null,
      "archive_id": null,
      "source_pdf": "jamharat_ayman.pdf",
      "extraction_method": "FlateDecode_stream"
    }
  ],
  "books": [
    {
      "book_id": "ossoul:iysal_al_salik",
      "title": "إيصال السالك في أصول الإمام مالك",
      "author": "محمد يحيى الولاتي",
      "science": "أصول الفقه",
      "source": "matn_knowledge_base",
      "is_authored_by_person": false,
      "is_explained_by_person": true,
      "matched_playlists": ["PL4Tn64l1hKwl-OYjCv7Oo0sRcRF7pnZN1"]
    }
  ],
  "stats": {
    "channels_count": 1,
    "playlists_count": 1,
    "videos_count": 2,
    "streams_count": 0,
    "unclassified_videos_count": 0,
    "archive_items_count": 1,
    "archive_audio_files_count": 1,
    "pdf_links_count": 1,
    "pdf_playlists_count": 1,
    "books_count": 1,
    "matched_series_to_books_count": 1,
    "total_duration_s": 7209,
    "total_duration_hours": 2.0,
    "duplicates_removed": 0
  },
  "raw_playlists_count": 1,
  "unique_videos_count": 2,
  "raw_series": ["... مطابق لـ playlists ..."],
  "unique_videos": ["... مطابق لـ videos ..."]
}
```

---

## 2. بروتوكول التعامل مع `yt-dlp --flat-playlist -J` و`InnerTube`

### 2.1. استخراج القوائم والفيديوهات والبثوث عبر `yt-dlp`
عند استدعاء `yt-dlp --flat-playlist -J <URL>`:
- يعيد كائن JSON يحتوي على المصفوفة `entries`.
- إذا كان الرابط لتبويب `/playlists` في القناة، فإن كل عنصر في `entries` يمثل قائمة تشغيل (`id` يبدأ بـ `PL`).
- إذا كان الرابط لقائمة تشغيل (`playlist?list=PL...` أو `playlist?list=UU...`) أو تبويب `/videos` أو `/streams`، فإن كل عنصر في `entries` يمثل فيديو مفرداً يحتوي على:
  * `id`: معرف الفيديو (11 حرفاً).
  * `title`: عنوان الفيديو.
  * `duration`: المدة بالثواني (قد تكون `float` أو `int`، وتُحوّل دائماً إلى `int(round(duration))`).
  * `upload_date` أو `release_timestamp`: تاريخ الرفع بصيغة `YYYYMMDD`.
  * `live_status`: إذا كانت `"was_live"` أو `"is_live"` أو من تبويب `/streams`، يُوسم الفيديو بـ `source_type = "youtube_stream"`.

### 2.2. حيلة قائمة الرفوعات الكاملة (`UC -> UU Trick`)
- كل قناة يوتيوب معرفها `UCxxxxxxxxxxxxxxxxxxxxxx` تمتلك قائمة تشغيل خفية تضم جميع الفيديوهات المرفوعة على القناة بمعرف `UUxxxxxxxxxxxxxxxxxxxxxx`.
- بجلب القائمة `UU...` ومقارنتها بمجموع الفيديوهات الموجودة داخل القوائم الرسمية `PL...`:
  $$\text{Unclassified} = \text{Uploads}(UU) \setminus \bigcup_{i} \text{Playlist}(PL_i)$$
- يُوضع الفارق فقط في قائمة `غير مصنف` (`<channel_key>__unclassified` مع `yt_playlist_id: null` و`is_unclassified: true`)، مما يمنع تكرار الفيديوهات المصنفة داخل قسم غير المصنف.

---

## 3. بروتوكول `Archive.org AdvancedSearch & Metadata API`

### 3.1. البحث المتقدم (`AdvancedSearch API`)
- نقطة النهاية:
  `https://archive.org/advancedsearch.php?q=creator:("<اسم الشيخ>") OR title:("<اسم الشيخ>")&fl[]=identifier,title,creator,uploader,mediatype,date&rows=500&page=1&output=json`
- إذا عُرف حساب الرافع الرسمي (`uploader` مثل `admin@assariry.com`)، يُنفذ استعلام إضافي بـ `uploader:("<uploader>")` لحصر جميع الحزم الصوتية في الحساب حتى لو لم يُذكر اسم الشيخ في عنوان الحزمة.

### 3.2. جلب البيانات الوصفية للحزمة (`Metadata API`)
- نقطة النهاية:
  `https://archive.org/metadata/<item_id>`
- بنية الاستجابة:
  * `metadata`: يحتوي على `identifier`, `title`, `creator`, `uploader`, `mediatype`, `date`.
  * `files`: مصفوفة بجميع ملفات الحزمة (الأصلية `source: "original"` والمشتقة `source: "derivative"`).
- **قواعد تصفية الملفات الصوتية**:
  1. قبول الامتدادات الصوتية فقط: `.mp3`, `.m4a`, `.flac`, `.ogg`, `.wav`.
  2. استبعاد ملفات الصور والبيانات الوصفية (`.jpg`, `.png`, `_meta.xml`, `_files.xml`, `.torrent`, `.afpk`, `.Scandata`).
  3. **إزالة تكرار المشتقات (`Stem Deduplication`)**: إذا وُجد في نفس الحزمة `001.mp3` (`source: "original"`) و`001.ogg` (`source: "derivative"`), يتم الاحتفاظ بـ `001.mp3` فقط وفق سلم الأولوية: `.mp3 > .m4a > .flac > .ogg > .wav`.
  4. **تحويل حقل المدة `length`**:
     - إذا كان نصاً عشرياً مثل `"4530.72"` -> `int(float("4530.72")) = 4530`.
     - إذا كان بصيغة `HH:MM:SS` أو `MM:SS` مثل `"01:15:30"` -> `1*3600 + 15*60 + 30 = 4530`.

---

## 4. خوارزمية فك تيارات `PDF` الفهرسية (`FlateDecode` + `/URI`)

تُخزن ملفات `PDF` الروابط التشعبية والنصوص بطريقتين:
1. **كائنات التعليقات التوضيحية (`/Subtype /Link /A << /S /URI /URI (...) >>`)**: قد تكون صريحة في الملف أو مضغوطة داخل كائنات تيارات (`Object Streams`).
2. **تيارات المحتوى المضغوطة (`/Filter /FlateDecode stream ... endstream`)**: تحتوي على النص المرسوم في الجداول والروابط المضمنة مضغوطةً بخوارزمية `zlib` (`RFC 1950` أو `RFC 1951`).

### خطوات الخوارزمية في `extract_links_from_pdf`:
1. قراءة الملف بصيغة ثنائية (`bytes`).
2. مسح الكائنات غير المضغوطة عن أنماط `/URI\s*\(([^)]+)\)` و`/URI\s*<([0-9A-Fa-f]+)>`.
3. البحث عن جميع مقاطع `stream[\r\n]+(.*?)[\r\n]+endstream` (باستخدام `re.DOTALL`):
   - محاولة فك الضغط عبر `zlib.decompress(chunk)`، وفي حال فشل الترويسة تُجرّب `zlib.decompress(chunk, -15)` (Raw Deflate).
   - فك ترميز البيانات المفكوكة بـ `latin-1` و`utf-8 (ignore)` واستخراج جميع الروابط ومعرفات `PL...` و`youtu.be/...` و`archive.org/...` و`bit.ly/...`.
4. تصنيف كل رابط مستخرج (`link_type`) واستخلاص المعرف المقابل (`playlist_id`, `video_id`, `archive_id`).

---

## 5. خوارزمية مطابقة الكتب والمتون (`Series-to-Book & Matn Matching`)

1. **تطبيع النص العربي (`normalize_arabic`)**:
   - إزالة التشكيل والتطويل (`[\u064B-\u065F\u0670\u0640]`).
   - توحيد الهمزات (`أ، إ، آ، ٱ -> ا`)، والألف المقصورة (`ى -> ي`)، والتاء المربوطة (`ة -> ه`).
2. **المطابقة بحدود الكلمات العربية (`Word-Boundary Matching`)**:
   - التحقق من ظهور الكلمات المفتاحية المميزة للمتن ككلمات كاملة محاطة ببداية/نهاية النص أو مسافات أو علامات ترقيم (مع مراعاة اللواصق العربية الشائعة مثل `بـ`، `لـ`، `والـ`).
3. **قواعد الفصل المنهجي بين الفنون (`Strict Science Separation`)**:
   - `مقدمات السنوسي` / `أم البراهين` / `العقيدة الصغرى` / `كبرى اليقينيات` / `الاقتصاد في الاعتقاد` -> `العقيدة وعلم الكلام`.
   - `جمع الجوامع` / `نشر البنود` / `مراقي السعود` / `إيصال السالك` / `مفتاح الوصول` / `الرسالة العضدية` / `الورقات` / `روضة الناظر` -> `أصول الفقه`.
   - `الموافقات` / `كتاب المقاصد` -> `مقاصد الشريعة`.
   - `مختصر خليل` / `الشرح الكبير للدردير` / `الشرح الصغير` / `أقرب المسالك` / `أسهل المسالك` / `رسالة ابن أبي زيد القيرواني` / `المرشد المعين` / `ابن عاشر` / `مختصر الأخضري` / `المنهج المنتخب` -> `الفقه المالكي`.
   - `الحكم العطائية` / `آداب سلوك المريد` / `الرسالة القشيرية` / `إحياء علوم الدين` / `منهاج العابدين` / `المنهاج في شعب الإيمان` / `أيها الولد` -> `التزكية والسلوك`.
