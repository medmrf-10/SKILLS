import hashlib
import json
import re
import sys
from pathlib import Path

import os
BASE = Path(os.environ.get("TURATH_BOOKS_REPO", Path(__file__).resolve().parent))
PATCH_DIR = BASE / "source_patches"
KNOWN_ISSUES_PATH = BASE / "known_issues.json"

SCIENCE_META = {
    "tarajim": {
        "science_ar": "التراجم والطبقات",
        "lens_ar": "عدسة الشبكات العلمية وعزل الأسانيد والتواريخ والأماكن الموحدة",
        "gem_label": "الوقائع البيوغرافية والشبكات العلمية",
        "case_label": "المواقف والأخبار المسندة",
    },
    "sirah": {
        "science_ar": "السيرة النبوية والخصائص",
        "lens_ar": "عدسة الخصائص النبوية التشريعية والشمائل ومقارنتها بأحكام الأمة",
        "gem_label": "الخصائص النبوية والشمائل المحمدية",
        "case_label": "الوقائع النبوية والتفريعات التشريعية",
    },
    "tari5": {
        "science_ar": "التاريخ الإسلامي والدول",
        "lens_ar": "عدسة التحولات السياسية والعمرانية والأدبية مع توثيق السنين والبلدان",
        "gem_label": "المعالم والأحداث والتحولات التاريخية",
        "case_label": "الوقائع التاريخية والمجالس السلطانية",
    },
    "tazkia": {
        "science_ar": "التزكية والأخلاق والآداب",
        "lens_ar": "عدسة الأخلاق العقلية-الأثرية والمقامات القلبية وعلاج الآفات",
        "gem_label": "القواعد الخلقية والمقامات التزكوية",
        "case_label": "مواقف السلف والحكماء التربوية",
    },
    "akida": {
        "science_ar": "العقيدة وأصول الدين",
        "lens_ar": "عدسة الهندسة البرهانية والأقيسة العقلية والرد على الفرق المخالفة",
        "gem_label": "الأصول العقدية والأقيسة البرهانية",
        "case_label": "الإلزامات الجدلية والمحاكمات العقدية",
    },
    "maliki": {
        "science_ar": "الفقه المالكي",
        "lens_ar": "عدسة الأحكام التكليفية والشروط والمبطلات والضوابط المذهبية",
        "gem_label": "الضوابط والأحكام الفقهية المالكية",
        "case_label": "الفروع والنوازل والمسائل التطبيقية",
    },
    "ossoul": {
        "science_ar": "أصول الفقه",
        "lens_ar": "عدسة الحدود الأصولية ومحترزاتها والتقسيمات والأمثلة التطبيقية",
        "gem_label": "الحدود والقواعد والتقسيمات الأصولية",
        "case_label": "الأمثلة الأصولية والتطبيقات الاستدلالية",
    },
    "3olomQuran": {
        "science_ar": "علوم القرآن والقراءات",
        "lens_ar": "عدسة التحقيق التاريخي والحديثي لجمع القرآن والناسخ والمنسوخ والقراءات",
        "gem_label": "القواعد والتحقيقات القرآنية",
        "case_label": "الروايات والإشكالات وتحرير الأجوبة",
    },
    "9awa3idFi9h": {
        "science_ar": "القواعد الفقهية",
        "lens_ar": "عدسة القواعد الكلية والضوابط والنظائر وتخريج الفروع",
        "gem_label": "القواعد والضوابط الفقهية الكلية",
        "case_label": "الفروع المخرجة والمقارنات المذهبية",
    },
    "hadith": {
        "science_ar": "الحديث النبوي ومتونه",
        "lens_ar": "عدسة الأسانيد والمتون والعلل والرواة والأحكام المستنبطة",
        "gem_label": "الجوامع النبوية والقواعد الحديثية",
        "case_label": "الوقائع النبوية والمرويات المسندة",
    },
    "hadith_sharh": {
        "science_ar": "شروح الحديث وفقه السنة",
        "lens_ar": "عدسة فقه الحديث ومذاهب العلماء وتوجيه الروايات والآثار",
        "gem_label": "القواعد الحديثية والفقهية المستنبطة",
        "case_label": "المسائل الخلافية والمرويات التطبيقية",
    },
    "tafsir": {
        "science_ar": "التفسير وبيان المعاني",
        "lens_ar": "عدسة التحليل البياني واللغوي والأحكام والمقاصد القرآنية",
        "gem_label": "النكت التفسيرية والقواعد البيانية",
        "case_label": "اللطائف التدبرية وأسباب النزول",
    },
    "irab_quran": {
        "science_ar": "إعراب القرآن وبيانه وبلاغته",
        "lens_ar": "عدسة الإعراب والتصريف والنكت البلاغية والشواهد الشعرية",
        "gem_label": "الضوابط النحوية والبلاغية القرآنية",
        "case_label": "الأوجه الإعرابية والشواهد التطبيقية",
    },
    "manzumat": {
        "science_ar": "المنظومات العلمية وشروحها",
        "lens_ar": "عدسة القواعد المنظومة وحل الأبيات وإعرابها وشواهدها",
        "gem_label": "الأبيات الجامعة والقواعد المنظومة",
        "case_label": "التطبيقات والشواهد الشعرية",
    },
    "kalam_firaq": {
        "science_ar": "علم الكلام والمقالات والفرق",
        "lens_ar": "عدسة الحجاج العقدي وتحرير مقالات الفرق والردود البرهانية",
        "gem_label": "القواعد الكلامية والأدلة القطعية",
        "case_label": "المناظرات والإلزامات الجدلية",
    },
    "nahw": {
        "science_ar": "النحو العربي",
        "lens_ar": "عدسة العوامل والأحكام الإعرابية والشواهد والعلل النحوية",
        "gem_label": "القواعد والضوابط النحوية",
        "case_label": "الشواهد والمسائل الإعرابية",
    },
    "sarf": {
        "science_ar": "علم التصريف والاشتقاق",
        "lens_ar": "عدسة الأبنية والأوزان والإعلال والإبدال والاشتقاق",
        "gem_label": "الأبنية والقواعد الصرفية",
        "case_label": "الأمثلة التصريفية والتطبيقات",
    },
    "balagha": {
        "science_ar": "البلاغة (المعاني والبيان والبديع)",
        "lens_ar": "عدسة أسرار التراكيب والمجاز والاستعارة والكناية والبديع",
        "gem_label": "القواعد والنكت البلاغية",
        "case_label": "الشواهد البيانية والتطبيقات",
    },
    "mantiq": {
        "science_ar": "المنطق والمعيار العقلي",
        "lens_ar": "عدسة التصورات والتصديقات والحدود والأقيسة والمغالطات",
        "gem_label": "القواعد المنطقية والحدود البرهانية",
        "case_label": "الأقيسة التطبيقية والمغالطات",
    },
    "munazarah": {
        "science_ar": "آداب البحث والمناظرة",
        "lens_ar": "عدسة المنع والنقض والمعارضة وتوجيه الأدلة",
        "gem_label": "قواعد البحث والمناظرة",
        "case_label": "المناظرات والاعتراضات التطبيقية",
    },
    "lugha": {
        "science_ar": "فقه اللغة والمعاجم والأدب",
        "lens_ar": "عدسة الدلالة المعجمية والفروق اللغوية والشواهد الأدبية",
        "gem_label": "الفروق والضوابط اللغوية",
        "case_label": "الشواهد والنوادر الأدبية",
    },
    "faraid": {
        "science_ar": "الفرائض والمواريث",
        "lens_ar": "عدسة الفروض والتعصيب والحجب وتأصيل المسائل الحسابية",
        "gem_label": "قواعد الفرائض والحجب",
        "case_label": "المسائل الفرضية التطبيقية",
    },
}


def get_science_meta(sc: str) -> dict:
    if sc in SCIENCE_META:
        return SCIENCE_META[sc]
    return {
        "science_ar": sc,
        "lens_ar": "عدسة الفهرسة العميقة واستخلاص القواعد والشواهد والكيانات الموثقة",
        "gem_label": "القواعد والفوائد العلمية المحررة",
        "case_label": "المسائل والوقائع التطبيقية",
    }


NORMATIVE_SCIENCES = {
    "maliki", "ossoul", "9awa3idFi9h", "akida", "3olomQuran",
    "hadith_sharh", "tafsir", "irab_quran", "manzumat", "kalam_firaq",
    "nahw", "sarf", "balagha", "mantiq", "munazarah", "lugha", "faraid",
}
TASHKEEL_RE = re.compile(r"[\u0617-\u061A\u064B-\u065F\u0670]")
DIGITS_MAP = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
TRAILING_COLON_RE = re.compile(
    r":[\s\u200e\u200f\u202a-\u202e]*(?:\(¬?[٠-٩0-9]+\)[\s\u200e\u200f]*|[«\"'”’(\[]+[\s\u200e\u200f]*)*$"
)

ORPHAN_HEADING_RE = re.compile(
    r"(?:^|\n)\s*("
    r"(?:تنبيه(?:ان|ات| ثانٍ| أول)?|فائدة|فرع|فصل|مسألة|المسألة\s+[^\n:]{1,25}|قاعدة|باب|خاتمة|تتمة|لطيفة|التمهيد\s+[^\n:]{1,20}|القول في\s+[^\n:]{1,35})\s*:?\s*"
    r"|\[[^\n\]]{3,70}\]\s*"
    r"|-\s+[^\n]{3,70}"
    r"|(?:\(خَ\)\s*)?[٠-٩0-9]+\s*[-–_ـ]\s*"
    r")\s*$"
)

ISNAD_VERB_RE = re.compile(
    r"(?:^|\s)(?:(?:ح\s+)?و?(?:حدثنا|حدثني|اخبرنا|اخبرني|انبانا|انباني|ثنا|سمعت|روي\s+لنا|حدثنيه|روينا)|وبه\s+(?:ثنا|حدثنا|اخبرنا))\b"
)
ISNAD_LINK_TOKEN_RE = re.compile(
    r"\b(?:حدثنا|حدثني|اخبرنا|اخبرني|انبانا|انباني|ثنا|سمعت|عن|بن|ابن|ح)\b"
)
AUTHOR_PROSE_GUARD_RE = re.compile(
    r"(?:قلت\s*:|قال\s+ابو\s+شامه|فالواجب\s+علي\s+العاقل|والعاقل\s+لا|فان\s+قيل|اعلم\s+ان\s+)"
)

GENERIC_SINGLE_PERSON_WORDS = {
    "ابو", "ابي", "ابا", "ابن", "بن", "بنت", "عبد", "الله", "محمد", "احمد",
    "علي", "الحسن", "الحسين", "قال", "قلت", "فقلت", "قيل", "الشيخ", "الامام",
    "القاضي", "الامير", "المؤلف", "المصنف", "خصم", "سائل", "قائل", "رجل", "امراه",
}

UNIT_MAP = {
    "واحد": 1, "واحده": 1, "احد": 1, "احدي": 1,
    "اثنين": 2, "اثنتين": 2, "اثنا": 2, "اثنتا": 2, "اثنتي": 2, "اثني": 2, "ثنتي": 2, "ثنتين": 2, "ثنتا": 2,
    "ثلاث": 3, "ثلاثه": 3,
    "اربع": 4, "اربعه": 4,
    "خمس": 5, "خمسه": 5,
    "ست": 6, "سته": 6,
    "سبع": 7, "سبعه": 7,
    "ثمان": 8, "ثماني": 8, "ثمانيه": 8,
    "تسع": 9, "تسعه": 9,
}
TENS_MAP = {
    "عشر": 10, "عشره": 10,
    "عشرون": 20, "عشرين": 20,
    "ثلاثون": 30, "ثلاثين": 30,
    "اربعون": 40, "اربعين": 40,
    "خمسون": 50, "خمسين": 50,
    "ستون": 60, "ستين": 60,
    "سبعون": 70, "سبعين": 70,
    "ثمانون": 80, "ثمانين": 80,
    "تسعون": 90, "تسعين": 90,
}
HUNDREDS_MAP = {
    "مائه": 100, "مئه": 100, "مايه": 100,
    "مائتين": 200, "مئتين": 200, "مائتان": 200, "مئتان": 200, "مائتا": 200, "مئتا": 200,
    "ثلاثمائه": 300, "ثلثمائه": 300, "ثلاثمئه": 300, "ثلثمئه": 300, "ثلاثمايه": 300, "ثلثمايه": 300,
    "اربعمائه": 400, "اربعمئه": 400, "اربعمايه": 400,
    "خمسمائه": 500, "خمسمئه": 500, "خمسمايه": 500,
    "ستمائه": 600, "ستمئه": 600, "ستمايه": 600,
    "سبعمائه": 700, "سبعمئه": 700, "سبعمايه": 700,
    "ثمانمائه": 800, "ثمانيمائه": 800, "ثمانمئه": 800, "ثمانيمئه": 800, "ثمانمايه": 800,
    "تسعمائه": 900, "تسعمئه": 900, "تسعمايه": 900,
    "الف": 1000, "الفين": 2000, "الفي": 2000,
}
ORDINAL_MAP = {
    "الاولي": 1, "الاول": 1,
    "الثانيه": 2, "الثاني": 2,
    "الثالثه": 3, "الثالث": 3,
    "الرابعه": 4, "الرابع": 4,
    "الخامسه": 5, "الخامس": 5,
    "السادسه": 6, "السادس": 6,
    "السابعه": 7, "السابع": 7,
    "الثامنه": 8, "الثامن": 8,
    "التاسعه": 9, "التاسع": 9,
    "العاشره": 10, "العاشر": 10,
}
ALL_NUM_WORDS = set(UNIT_MAP) | set(TENS_MAP) | set(HUNDREDS_MAP)


def sha16(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


def to_ascii_int(s: str) -> int:
    return int(s.translate(DIGITS_MAP))


def find_word_bounded(haystack: str, needle: str, start: int = 0) -> int:
    if not needle or not haystack:
        return -1
    pos = max(0, start)
    n_len = len(needle)
    h_len = len(haystack)
    while True:
        idx = haystack.find(needle, pos)
        if idx == -1:
            return -1
        end_idx = idx + n_len
        left_ok = idx == 0 or haystack[idx - 1] == " "
        right_ok = end_idx == h_len or haystack[end_idx] == " "
        if left_ok and right_ok:
            return idx
        pos = idx + 1


FOLIO_MARKER_RE = re.compile(
    r"(?:/\s*)?\((?=[^()\n]{1,16}\))(?=[^)]*[أابظوزدمه])\s*[٠-٩0-9]{1,4}\s*/?\s*[أابظو]?\u064e?\s*"
    r"(?:/\s*[أابظوزدمه]\u064e?\s*){0,2}\)"
)
EDITION_PAGE_RE = re.compile(r"⦗[^⦘\n]{1,20}⦘")
GLUED_BARE_FN_RE = re.compile(r"(?<=[\u0621-\u064A\u064B-\u065F﴾»\"'\)\]])[٠-٩0-9]{1,2}(?![٠-٩0-9/\-–])")


def normalize_with_map(text: str, strip_ed_noise: bool = False):
    work = text
    if strip_ed_noise:
        for pat in (
            FOLIO_MARKER_RE,
            EDITION_PAGE_RE,
            r"\[[٠-٩0-9]+\s*[وظ]\]",
            r"\[[٠-٩0-9]{1,3}\]",
            r"\(¬?[٠-٩0-9]+|\*+\)",
            GLUED_BARE_FN_RE,
            r"(?:^|(?<=\s))\s*(?:\(خَ\)\s*)?[٠-٩0-9]+\*{0,3}\s*[-–_ـ]\s+",
            r"صفحة فارغة في الأصل",
            r"(?:^|(?<=\n))\s*[٠-٩0-9]+\s*/\s*[٠-٩0-9]+\s*(?=\n|$)",
        ):
            work = re.sub(pat, lambda m: " " * len(m.group(0)), work)

    LIGATURE_EXPANSIONS = {
        "\ufdff": " عز وجل ",
        "\ufdfb": " جل جلاله ",
    }
    norm_chars = []
    idx_map = []
    prev_space = False
    for i, ch in enumerate(work):
        if TASHKEEL_RE.match(ch) or ch == "\u0640":
            continue
        if ch in LIGATURE_EXPANSIONS:
            for exp_ch in LIGATURE_EXPANSIONS[ch]:
                if exp_ch.isspace():
                    if not prev_space:
                        norm_chars.append(" ")
                        idx_map.append(i)
                        prev_space = True
                else:
                    norm_chars.append(exp_ch)
                    idx_map.append(i)
                    prev_space = False
            continue
        if ch.isspace():
            if not prev_space:
                norm_chars.append(" ")
                idx_map.append(i)
                prev_space = True
            continue
        prev_space = False
        if ch in "أإآٱ":
            ch = "ا"
        elif ch == "ة":
            ch = "ه"
        elif ch == "ى":
            ch = "ي"
        norm_chars.append(ch)
        idx_map.append(i)
        # Split Shamela OCR glued 'لاتهتك' -> 'لا تهتك' while keeping exact offset map
        if len(norm_chars) >= 2 and norm_chars[-2] == "ل" and norm_chars[-1] == "ا" and work[i + 1 : i + 5].startswith("تهتك"):
            norm_chars.append(" ")
            idx_map.append(i)
            prev_space = True
    return "".join(norm_chars), idx_map


def normalize_words_only(text: str, strip_ed_noise: bool = True):
    norm_s, idx_map = normalize_with_map(text, strip_ed_noise=strip_ed_noise)
    w_chars = []
    w_map = []
    prev_sp = True
    for ch, orig_i in zip(norm_s, idx_map):
        if ch.isalnum() or "\u0621" <= ch <= "\u064A":
            w_chars.append(ch)
            w_map.append(orig_i)
            prev_sp = False
        else:
            if not prev_sp:
                w_chars.append(" ")
                w_map.append(orig_i)
                prev_sp = True
    while w_chars and w_chars[-1] == " ":
        w_chars.pop()
        w_map.pop()
    return "".join(w_chars), w_map


HONORIFIC_LIGATURE_MAP = {
    "\ufd40": " رحمه الله ",
    "\ufd41": " رضي الله عنه ",
    "\ufd42": " رضي الله عنها ",
    "\ufd43": " رضي الله عنهم ",
    "\ufd44": " رضي الله عنهما ",
    "\ufd45": " رضي الله عنهن ",
    "\ufd46": " صلى الله عليه وآله ",
    "\ufd47": " عليه السلام ",
    "\ufd48": " عليهم السلام ",
    "\ufd49": " عليهما السلام ",
    "\ufd4a": " عليه الصلاة والسلام ",
    "\ufd4b": " قدس سره ",
    "\ufd4c": " صلى الله عليه وآله وسلم ",
    "\ufd4d": " عليها السلام ",
    "\ufd4e": " تبارك وتعالى ",
    "\ufd4f": " رحمهم الله ",
    "\ufdfa": " صلى الله عليه وسلم ",
    "\ufdfb": " جل جلاله ",
    "\ufdfe": " سبحانه وتعالى ",
    "\ufdff": " عز وجل ",
}


def expand_honorific_ligatures(s: str) -> str:
    for k, v in HONORIFIC_LIGATURE_MAP.items():
        if k in s:
            s = s.replace(k, v)
    return s


def clean_for_embed(text: str, science: str = "", orig_heading: str = "", interior_isnads: list = None) -> str:
    s = text
    # Strip interior isnad spans from embed_matn_text so embeddings focus on pure matn
    if interior_isnads:
        for sp in sorted(interior_isnads, key=lambda x: x["char_start_in_matn"], reverse=True):
            st_i = sp["char_start_in_matn"]
            en_i = sp["char_end_in_matn"]
            if 0 <= st_i < en_i <= len(s):
                s = s[:st_i] + " " + s[en_i:]
    # Strip duplicated part heading at the very start of the passage
    if orig_heading:
        hd_norm = TASHKEEL_RE.sub("", orig_heading).strip()
        lines = s.splitlines()
        if lines:
            first_ln_norm = TASHKEEL_RE.sub("", lines[0]).strip()
            if first_ln_norm and (first_ln_norm == hd_norm or first_ln_norm in ("المقدمة", "﷽", "المقدمة ﷽")):
                s = "\n".join(lines[1:])
    s = TASHKEEL_RE.sub("", s)
    s = s.replace("\u0640", "")
    s = re.sub(r"^(?:المقدمة\s*)?﷽\s*", "", s.strip())
    # Expand Islamic honorific ligatures (U+FD40..U+FDFF) into standard Arabic words for EmbeddingGemma 2
    s = expand_honorific_ligatures(s)
    # Strip manuscript folio markers like [١٢ و], (١٣٠ب), / (٢٥ أ/ د), edition page markers ⦗١١٣⦘, and inline 'صفحة ١٣٧'
    s = FOLIO_MARKER_RE.sub(" ", s)
    s = EDITION_PAGE_RE.sub(" ", s)
    s = re.sub(r"\bصفحة\s+[٠-٩0-9]{1,4}\b", " ", s)
    s = re.sub(r"\[[٠-٩0-9]+\s*[وظ]\]", " ", s)
    # Strip bare footnote digits after Quranic closing brackets like ﴾ ٢
    s = re.sub(r"(?<=﴾)\s*[٠-٩0-9]{1,2}\b", "", s)
    # Strip glued bare footnote digits like قدير١ or للهم٣
    s = GLUED_BARE_FN_RE.sub("", s)
    # Strip inline verse citations in square brackets like [البقرة: من الآية ١٤٤]
    s = re.sub(r"\[[^\]]*(?:الآية|آية|سورة)[^\]]*\]", " ", s)
    # Strip editorial bracketed insertions [وقتله أحد مصائب الإسلام] -> keep inner text without brackets
    s = re.sub(r"\[([^\]]+)\]", r"\1", s)
    s = re.sub(r"(?:^|\n)\s*[٠-٩0-9]+\s*/\s*[٠-٩0-9]+\s*(?=\n|$)", " ", s)
    s = s.replace("صفحة فارغة في الأصل", " ")
    # Always strip explicit (¬N) footnote markers
    s = re.sub(r"\(¬[٠-٩0-9]+\)", " ", s)
    if science != "3olomQuran":
        # In non-Quran-revelation-order books, strip line-initial entry numbers and (N) footnote markers
        s = re.sub(r"(?:^|\n|\s)(?:\(خَ\)\s*)?[٠-٩0-9]+\s*[-–_ـ]\s+", " ", s)
        s = re.sub(r"\([٠-٩0-9]+\)", " ", s)
    else:
        # In 3olomQuran, preserve surah order numbers on numbered list lines, strip (N) on non-list lines
        cleaned_lines = []
        for ln in s.splitlines():
            if re.match(r"^\s*[٠-٩0-9]+\s*-\s*", ln):
                ln = re.sub(r"^(\s*[٠-٩0-9]+\s*-\s*)\([٠-٩0-9]+\)\s*", r"\1", ln)
                ln = re.sub(r"\([٠-٩0-9]+\)\s*(?=\([٠-٩0-9]+\))", "", ln)
                cleaned_lines.append(ln)
            else:
                cleaned_lines.append(re.sub(r"\([٠-٩0-9]+\)", " ", ln))
        s = "\n".join(cleaned_lines)
    # Fix known Shamela glued hemistichs and stray OCR question marks
    s = s.replace("بالجزعما", "بالجزع ما").replace("فارتفعإلا", "فارتفع إلا")
    s = re.sub(r"\.\s*؟+", ".", s)
    s = re.sub(r"؟{2,}", "؟", s)
    s = re.sub(r"(?:^|(?<=\s))؟+(?=\s|$)", " ", s)
    s = re.sub(r"(?<=وأحكم)؟", "", s)
    s = s.replace("*", " ").replace("◂", " ")
    s = re.sub(r"\.{3,}", " ", s)
    s = re.sub(r"\s+([،.؛:؟!])", r"\1", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _normalize_words_with_honorifics(text: str, strip_ed_noise: bool = True):
    """Normalizes words while expanding U+FD40..U+FDFF honorific ligatures and mapping back to original offsets."""
    work = text
    if strip_ed_noise:
        for pat in (
            FOLIO_MARKER_RE,
            EDITION_PAGE_RE,
            r"\[[٠-٩0-9]+\s*[وظ]\]",
            r"\[[٠-٩0-9]{1,3}\]",
            r"\(¬?[٠-٩0-9]+|\*+\)",
            GLUED_BARE_FN_RE,
            r"(?:^|(?<=\s))\s*(?:\(خَ\)\s*)?[٠-٩0-9]+\*{0,3}\s*[-–_ـ]\s+",
            r"صفحة فارغة في الأصل",
            r"(?:^|(?<=\n))\s*[٠-٩0-9]+\s*/\s*[٠-٩0-9]+\s*(?=\n|$)",
        ):
            work = re.sub(pat, lambda m: " " * len(m.group(0)), work)
    w_chars = []
    w_map = []
    prev_sp = True
    for i, ch in enumerate(work):
        if TASHKEEL_RE.match(ch) or ch == "\u0640":
            continue
        if ch in HONORIFIC_LIGATURE_MAP:
            exp_norm, _ = normalize_words_only(HONORIFIC_LIGATURE_MAP[ch], strip_ed_noise=False)
            if exp_norm:
                if not prev_sp:
                    w_chars.append(" ")
                    w_map.append(i)
                for ech in exp_norm:
                    w_chars.append(ech)
                    w_map.append(i)
                prev_sp = False
            continue
        if ch in "أإآٱ":
            ch = "ا"
        elif ch == "ة":
            ch = "ه"
        elif ch == "ى":
            ch = "ي"
        if ch.isalnum() or "\u0621" <= ch <= "\u064A":
            w_chars.append(ch)
            w_map.append(i)
            prev_sp = False
        else:
            if not prev_sp:
                w_chars.append(" ")
                w_map.append(i)
                prev_sp = True
    while w_chars and w_chars[-1] == " ":
        w_chars.pop()
        w_map.pop()
    return "".join(w_chars), w_map


def find_anchor_offset(text: str, anchor: str, min_offset: int = 0):
    if not anchor or not text:
        return -1, "failed"
    anchor = anchor.strip()
    norm_anc_raw, _ = normalize_words_only(anchor, strip_ed_noise=False)
    if not norm_anc_raw:
        return -1, "failed"

    anc_words = norm_anc_raw.split()
    if len(anc_words) < 4:
        norm_text_raw, _ = normalize_words_only(text, strip_ed_noise=False)
        if not norm_text_raw:
            return -1, "failed"
        text_words = norm_text_raw.split()
        if len(anc_words) < min(4, len(text_words)):
            return -1, "failed"

    # 1. Try full exact match first (allowing spaces or newlines between exact tokens)
    idx = text.find(anchor, min_offset)
    if idx == min_offset:
        return idx, "exact"
    ws_pat = re.compile(r"\s+".join(re.escape(w) for w in anchor.split()))
    search_end = (idx + len(anchor)) if idx != -1 else len(text)
    m_ws = ws_pat.search(text, min_offset, search_end)
    if m_ws is not None and (idx == -1 or m_ws.start() < idx):
        idx = m_ws.start()
    if idx != -1:
        return idx, "exact"

    # 2. Try full normalized word-bounded match (100% of anchor words must match contiguously; no prefix shrinking!)
    for strip_noise in (False, True):
        norm_text, idx_map = normalize_words_only(text, strip_ed_noise=strip_noise)
        norm_anc, _ = normalize_words_only(anchor, strip_ed_noise=strip_noise)
        if not norm_text or not norm_anc or len(norm_anc.split()) < min(4, len(norm_text.split())):
            continue
        norm_min = len(norm_text)
        for k, orig_i in enumerate(idx_map):
            if orig_i >= min_offset:
                norm_min = k
                break
        n_idx = find_word_bounded(norm_text, norm_anc, norm_min)
        if n_idx != -1:
            return idx_map[n_idx], "normalized"

    # 3. Fallback: try with Unicode honorific ligatures (U+FD40..U+FDFF) expanded to words
    norm_text_h, idx_map_h = _normalize_words_with_honorifics(text, strip_ed_noise=True)
    norm_anc_h, _ = _normalize_words_with_honorifics(anchor, strip_ed_noise=True)
    if norm_text_h and norm_anc_h and len(norm_anc_h.split()) >= min(4, len(norm_text_h.split())):
        norm_min_h = len(norm_text_h)
        for k, orig_i in enumerate(idx_map_h):
            if orig_i >= min_offset:
                norm_min_h = k
                break
        n_idx_h = find_word_bounded(norm_text_h, norm_anc_h, norm_min_h)
        if n_idx_h != -1:
            return idx_map_h[n_idx_h], "normalized"

    return -1, "failed"


def snap_offset_to_heading_start(raw_part: str, off: int, cur_min: int) -> int:
    window_start = max(cur_min, off - 110)
    preceding = raw_part[window_start:off]
    m = ORPHAN_HEADING_RE.search(preceding)
    if m:
        return window_start + m.start(1)
    return off


def validate_and_extract_isnad(chunk_text: str, rel_anchor_off: int, matn_anc: str):
    if not matn_anc:
        return "", chunk_text, None, ""
    m_off, m_st = find_anchor_offset(chunk_text, matn_anc, rel_anchor_off)
    if m_st == "failed" or m_off <= rel_anchor_off + 10 or m_off >= len(chunk_text) - 20:
        return "", chunk_text, None, ""

    candidate = chunk_text[rel_anchor_off:m_off]
    cand_lines = [ln.strip() for ln in candidate.splitlines() if ln.strip()]
    # Separate leading title lines that do not contain transmission verbs
    skipped_heading_lines = []
    idx_line = 0
    while idx_line < len(cand_lines) - 1:
        ln_norm, _ = normalize_with_map(cand_lines[idx_line], strip_ed_noise=True)
        is_explicit_title_line = bool(re.match(r"^(?:ذكر|باب|فصل|كتاب|مقدمه|المقدمه|اخبار|ترجمه|بسم\s+الله)\b", ln_norm))
        max_hd_words = 18 if is_explicit_title_line else 10
        if not ISNAD_VERB_RE.search(ln_norm) and len(ln_norm.split()) <= max_hd_words:
            skipped_heading_lines.append(cand_lines[idx_line])
            idx_line += 1
        else:
            break

    cand_for_check = "\n".join(cand_lines[idx_line:])
    norm_cand, _ = normalize_with_map(cand_for_check, strip_ed_noise=True)
    norm_cand = re.sub(r"^بسم\s+الله\s+الرحمن\s+الرحيم\s*", "", norm_cand).strip()

    if AUTHOR_PROSE_GUARD_RE.search(norm_cand):
        return "", chunk_text, None, ""

    if not ISNAD_VERB_RE.search(norm_cand[:120]):
        return "", chunk_text, None, ""

    links = ISNAD_LINK_TOKEN_RE.findall(norm_cand)
    if len(links) < 2 and "الشافعي" not in norm_cand and "الزهري" not in norm_cand:
        return "", chunk_text, None, ""

    chain_ref = "attached_to_previous_isnad" if re.match(r"^وبه\b", norm_cand) else "independent"
    extra_heading = "\n".join(skipped_heading_lines).strip()
    isnad_prefix = cand_for_check.strip()
    clean_matn = chunk_text[m_off:].strip()

    m_quote = re.search(r'(["«]+)\s*$', isnad_prefix)
    if m_quote:
        q_chars = m_quote.group(1)
        isnad_prefix = isnad_prefix[: m_quote.start()].strip()
        clean_matn = q_chars + clean_matn

    return isnad_prefix, clean_matn, chain_ref, extra_heading


def extract_interior_isnads(clean_matn: str) -> list:
    """Detects secondary/interior isnad chains (both punctuated and unpunctuated heritage chains) inside clean_matn."""
    interior = []
    used_ranges = []

    # Pass 1: Punctuated interior isnad chains
    punct_pattern = re.compile(
        r"(?:^|(?<=\n)|(?<=[\.\s]))\s*((?:وبه\s+(?:ثنا|حدثنا|أخبرنا|اخبرنا)|من\s+ذلك\s+ما\s+حدثنا|وروى\s+[^\n:]{3,35}\s+قال|و?(?:حدثنا|حدثني|أخبرنا|اخبرنا|أخبرني|اخبرني|أنبأنا|ثنا)|قال\s+[^\n:]{3,30}:\s*(?:حدثنا|أخبرنا|ثنا))[^\n]{15,320}?(?:قال|يقول|أنشدنا)\s*[:؛])"
    )
    for m in punct_pattern.finditer(clean_matn):
        cand = m.group(1).strip()
        norm_c, _ = normalize_with_map(cand, strip_ed_noise=True)
        if len(ISNAD_LINK_TOKEN_RE.findall(norm_c)) >= 2:
            c_ref = "attached_to_previous_isnad" if norm_c.startswith("وبه") else "independent"
            st_i, en_i = m.start(1), m.end(1)
            interior.append({
                "isnad_text": cand,
                "char_start_in_matn": st_i,
                "char_end_in_matn": en_i,
                "chain_ref": c_ref,
            })
            used_ranges.append((st_i, en_i))

    # Pass 2: Unpunctuated line/clause-initial transmission chains (e.g. al-Aajurri 2327: 'أخبرنَا مُحَمَّد قَالَ حَدثنَا...')
    notash_chars = []
    notash_map = []
    for idx_ch, ch in enumerate(clean_matn):
        if TASHKEEL_RE.match(ch) or ch == "\u0640":
            continue
        notash_chars.append(ch)
        notash_map.append(idx_ch)
    notash_matn = "".join(notash_chars)

    unpunct_start_re = re.compile(
        r"(?:^|(?<=\n))\s*(?:وبه\s+(?:ثنا|حدثنا|أخبرنا|اخبرنا)|من\s+ذلك\s+ما\s+حدثنا|وروى\s+\S+\s+بن\s+\S+|و?(?:أخبرنا|اخبرنا|حدثنا|حدثني|أخبرني|اخبرني|ثنا))\b"
    )
    tx_hop_re = re.compile(
        r"(?:أخبرنا|اخبرنا|حدثنا|حدثني|أخبرني|اخبرني|ثنا|أنبأنا|انبانا|سمعت|أنشدنا|انشدنا|عن\s+(?:أبي|ابي|ابن|بن|\S+\s+بن))"
    )
    clause_hop_re = re.compile(r"\b(?:قال|يقول|سمعت|أنشدنا|انشدنا)\b")

    for m in unpunct_start_re.finditer(notash_matn):
        nt_st = m.start()
        while nt_st < len(notash_matn) and notash_matn[nt_st].isspace():
            nt_st += 1
        if nt_st >= len(notash_map):
            continue
        st_i = notash_map[nt_st]
        if any(max(st_i, u0) < min(st_i + 20, u1) for u0, u1 in used_ranges):
            continue
        window = clean_matn[st_i : min(len(clean_matn), st_i + 420)]
        norm_win, idx_map = normalize_with_map(window, strip_ed_noise=False)
        tx_matches = list(tx_hop_re.finditer(norm_win))
        if len(tx_matches) < 2:
            continue
        # Walk transmission hops as long as consecutive hops are <= 75 normalized chars apart
        last_tx = tx_matches[0]
        hop_count = 1
        for nxt_tx in tx_matches[1:]:
            if nxt_tx.start() - last_tx.end() <= 75:
                last_tx = nxt_tx
                hop_count += 1
            else:
                break
        if hop_count < 2:
            continue
        tail_search = norm_win[last_tx.end() : min(len(norm_win), last_tx.end() + 55)]
        m_close = clause_hop_re.search(tail_search)
        if m_close:
            norm_end_idx = last_tx.end() + m_close.end()
        else:
            after_tokens = list(re.finditer(r"\S+", norm_win[last_tx.end() : min(len(norm_win), last_tx.end() + 45)]))
            norm_end_idx = last_tx.end() + (after_tokens[min(2, len(after_tokens) - 1)].end() if after_tokens else 0)
        if norm_end_idx >= len(idx_map):
            orig_end_rel = len(window)
        else:
            orig_end_rel = idx_map[norm_end_idx]
        en_i = st_i + orig_end_rel
        cand = clean_matn[st_i:en_i].strip()
        norm_c, _ = normalize_with_map(cand, strip_ed_noise=True)
        if len(ISNAD_LINK_TOKEN_RE.findall(norm_c)) >= 2:
            c_ref = "attached_to_previous_isnad" if norm_c.startswith("وبه") else "independent"
            interior.append({
                "isnad_text": cand,
                "char_start_in_matn": st_i,
                "char_end_in_matn": en_i,
                "chain_ref": c_ref,
            })
            used_ranges.append((st_i, en_i))

    interior.sort(key=lambda x: x["char_start_in_matn"])
    return interior


PATRONYMIC_CONNECTORS = {"بن", "ابن", "بنت", "ابنه", "أبو", "ابو", "أبي", "ابي", "أبا", "ابا", "أم", "ام", "عبد"}


def resolve_person_mentioned_as(pe: dict, chunk_text: str, isnad_prefix: str = "", clean_matn: str = "") -> dict:
    norm_chunk, _ = normalize_words_only(chunk_text, strip_ed_noise=True)
    matn_slice = clean_matn if (isnad_prefix and clean_matn) else chunk_text
    norm_matn, _ = normalize_words_only(matn_slice, strip_ed_noise=True)
    norm_isnad, _ = normalize_words_only(isnad_prefix, strip_ed_noise=True) if isnad_prefix else ("", [])

    mas = (pe.get("mentioned_as") or "").strip()
    cname = (pe.get("canonical_name") or "").strip()

    if pe.get("origin") == "model":
        pe["mentioned_in_text"] = False
        pe["source_layer"] = "context"
        return pe

    clean_cname = cname.replace("ﷺ", "").replace("عليه السلام", "").replace("رضي الله عنه", "").strip()
    raw_c_tokens = [w.strip("()،.؛:") for w in clean_cname.split() if w.strip("()،.؛:")]
    norm_c_tokens = [normalize_words_only(w)[0].strip() for w in raw_c_tokens]

    # Identify which token positions in cname are preceded by 'بن' / 'ابن' / 'بنت' (father/grandfather names!)
    ancestor_token_indices = set()
    seen_nasab = False
    for idx_t, nt in enumerate(norm_c_tokens):
        if nt in ("بن", "ابن", "بنت"):
            seen_nasab = True
            ancestor_token_indices.add(idx_t)
        elif seen_nasab:
            # If it's a trailing nisba/laqab starting with 'ال' and NOT right after 'بن' (e.g. 'السقطي', 'الثوري', 'القرظي')
            if nt.startswith("ال") and idx_t >= 2 and norm_c_tokens[idx_t - 1] not in ("بن", "ابن", "بنت", "عبد", "ابو", "ابي"):
                continue
            ancestor_token_indices.add(idx_t)

    candidates = []
    # 1. Explicit mentioned_as supplied by agent (validated strictly via word boundaries)
    if mas:
        for c in re.split(r"[/،]", mas):
            c = c.strip()
            if c:
                candidates.append((c, "agent_mas"))

    # 2. Full canonical name
    if clean_cname:
        candidates.append((clean_cname, "full_cname"))

    # 3. Prefix n-grams starting at index 0 (preserving 'بن'!) so we never match a grandfather's sub-chain
    for span_len in range(len(raw_c_tokens), 1, -1):
        if norm_c_tokens[span_len - 1] in PATRONYMIC_CONNECTORS:
            continue
        candidates.append((" ".join(raw_c_tokens[:span_len]), "prefix_ngram"))

    # 4. Kunya + Name or Name + Nisba 2-grams that do not start on an ancestor token
    for i_tok in range(len(raw_c_tokens) - 1):
        if i_tok in ancestor_token_indices:
            continue
        if norm_c_tokens[i_tok + 1] not in PATRONYMIC_CONNECTORS:
            candidates.append((" ".join(raw_c_tokens[i_tok : i_tok + 2]), "head_2gram"))

    # 5. Safe single-word fallback: ONLY non-ancestor tokens (index 0 given name or trailing nisba/laqab)
    for i_tok, w in enumerate(raw_c_tokens):
        if i_tok in ancestor_token_indices:
            continue
        nw = norm_c_tokens[i_tok]
        if len(nw) >= 4 and nw not in GENERIC_SINGLE_PERSON_WORDS and nw not in PATRONYMIC_CONNECTORS:
            candidates.append((w, "single_token"))

    for cand, cand_kind in candidates:
        nc, _ = normalize_words_only(cand, strip_ed_noise=True)
        nc = nc.strip()
        if not nc or len(nc) < 3:
            continue
        nc_words = nc.split()
        if len(nc_words) == 1:
            if nc in GENERIC_SINGLE_PERSON_WORDS or nc in PATRONYMIC_CONNECTORS:
                continue
            # Also reject if the single word is purely an ancestor token in cname (e.g. 'الخطاب' in 'سالم بن عبد الله بن عمر بن الخطاب')
            if cand_kind == "agent_mas" and nc in [norm_c_tokens[idx_a] for idx_a in ancestor_token_indices]:
                continue

        match_pos = find_word_bounded(norm_chunk, nc, 0)
        if match_pos != -1:
            # If matching a single given name (e.g. 'عمر' or 'سالم'), ensure at the match site in norm_chunk
            # it is not preceded by 'بن ' (which would mean someone's father) and if cname has 'بن X',
            # ensure it isn't followed in norm_chunk by a DIFFERENT 'بن Y'!
            if len(nc_words) == 1 and not nc.startswith("ال"):
                valid_occ = False
                scan_pos = 0
                expected_father = None
                if len(norm_c_tokens) >= 3 and norm_c_tokens[0] == nc and norm_c_tokens[1] in ("بن", "ابن"):
                    expected_father = norm_c_tokens[2]
                while True:
                    pos_i = find_word_bounded(norm_chunk, nc, scan_pos)
                    if pos_i == -1:
                        break
                    before_words = norm_chunk[:pos_i].strip().split()
                    after_words = norm_chunk[pos_i + len(nc) :].strip().split()
                    prec_by_bin = bool(before_words and before_words[-1] in ("بن", "ابن", "ابي", "ابو"))
                    wrong_father = bool(
                        expected_father
                        and len(after_words) >= 2
                        and after_words[0] in ("بن", "ابن")
                        and after_words[1] != expected_father
                    )
                    if not prec_by_bin and not wrong_father:
                        valid_occ = True
                        break
                    scan_pos = pos_i + 1
                if not valid_occ:
                    continue

            in_matn = find_word_bounded(norm_matn, nc, 0) != -1
            in_isnad = bool(norm_isnad and find_word_bounded(norm_isnad, nc, 0) != -1)
            pe["mentioned_as"] = cand
            pe["mentioned_in_text"] = True
            pe["origin"] = "text"
            pe["source_layer"] = "matn" if in_matn else ("isnad" if in_isnad else "matn")
            return pe

    pe["mentioned_in_text"] = False
    pe["origin"] = "model"
    pe["source_layer"] = "context"
    return pe


def filter_places_against_isnad(science: str, places: list, chunk_text: str, isnad_prefix: str, clean_matn: str = "") -> list:
    if not places:
        return []
    matn_only = clean_matn if (isnad_prefix and clean_matn) else chunk_text
    norm_matn, _ = normalize_words_only(matn_only, strip_ed_noise=True)
    norm_isnad, _ = normalize_words_only(isnad_prefix, strip_ed_noise=True) if isnad_prefix else ("", [])

    filtered = []
    for pl in places:
        pl_obj = {"name_in_text": pl, "normalized_name": pl} if isinstance(pl, str) else dict(pl)
        name_in = (pl_obj.get("name_in_text") or pl_obj.get("mentioned_as") or pl_obj.get("name") or "").strip()
        norm_name = (pl_obj.get("normalized_name") or pl_obj.get("name") or name_in).strip()
        n_pl, _ = normalize_words_only(name_in, strip_ed_noise=True)
        n_pl = n_pl.strip()
        n_norm, _ = normalize_words_only(norm_name, strip_ed_noise=True)
        n_norm = n_norm.strip()
        if not n_pl and not n_norm:
            continue
        # Across ALL sciences, a place in `places` must be grounded in the matn (not exclusively in isnad or model memory)
        in_matn = (n_pl and n_pl in norm_matn) or (n_norm and n_norm in norm_matn)
        if not in_matn:
            continue
        filtered.append({"name_in_text": name_in, "normalized_name": norm_name})
    return filtered


def parse_number_tokens(tokens: list) -> int:
    total = 0
    i = 0
    matched_any = False
    while i < len(tokens):
        t = tokens[i]
        if t == "و":
            i += 1
            continue
        if t.startswith("و") and t[1:] in ALL_NUM_WORDS:
            t = t[1:]
        if t in UNIT_MAP and i + 1 < len(tokens) and tokens[i + 1] in ("مائه", "مئه", "مايه"):
            total += UNIT_MAP[t] * 100
            matched_any = True
            i += 2
            continue
        if t in HUNDREDS_MAP:
            total += HUNDREDS_MAP[t]
            matched_any = True
            i += 1
        elif t in TENS_MAP:
            total += TENS_MAP[t]
            matched_any = True
            i += 1
        elif t in UNIT_MAP:
            total += UNIT_MAP[t]
            matched_any = True
            i += 1
        else:
            break
    return total if matched_any else -1


def extract_date_years_from_text(chunk_text: str) -> list:
    work = TASHKEEL_RE.sub("", chunk_text)
    # Mark spoken false-start / cut-off tokens ending with tatweel (e.g. 'سنة ثمان وثـ') before normalize_with_map strips '\u0640'
    work = re.sub(r"[\u0621-\u064A]{1,6}\u0640+(?=\s|[،.؟!؛:\n]|$)", " TRUNCWORD ", work)
    work = re.sub(r"\(¬?[٠-٩0-9]+\)", " ", work)
    work = re.sub(r"\[[^\]]*\]", " ", work)
    work = re.sub(r"[٠-٩0-9]+\s*/\s*[٠-٩0-9]+", " ", work)
    work = re.sub(r"[٠-٩0-9]+\s*م\b", " ", work)
    work = re.sub(r"(?:^|(?<=\n))\s*(?:\(خَ\)\s*)?[٠-٩0-9]+\s*[-–_ـ]\s*", " ", work)

    norm_work, _ = normalize_with_map(work)
    tokens = re.findall(r"[ء-يa-zA-Z]+|[٠-٩0-9]+", norm_work)

    extracted_years = []
    for idx, tok in enumerate(tokens):
        if tok in ("السنه", "العام") and idx + 1 < len(tokens) and tokens[idx + 1] in ORDINAL_MAP:
            extracted_years.append(ORDINAL_MAP[tokens[idx + 1]])
            continue

        is_year_kw = tok in ("سنه", "عام", "لسنه", "لعام", "سنتي")
        is_bio_kw = tok in ("توفي", "وتوفي", "مات", "ومات", "ولد", "وولد", "قتل", "وقتل", "حدود")
        if not (is_year_kw or is_bio_kw):
            continue

        if is_year_kw and idx > 0:
            prev_t = tokens[idx - 1]
            prev_clean = prev_t[1:] if prev_t.startswith("و") and prev_t[1:] in ALL_NUM_WORDS else prev_t
            if prev_clean in ALL_NUM_WORDS or prev_clean.translate(DIGITS_MAP).isdigit():
                continue
            if prev_t in ("مائه", "مئه", "مايه", "ولايته", "خلافته", "مدته", "اقام", "بقي", "مقدار", "تجاوز", "بلغ", "صغر", "كبر"):
                continue

        j = idx + 1
        if is_bio_kw:
            while j < len(tokens) and tokens[j] in ("رحمه", "الله", "تعالي", "في", "حدود", "نحو", "قرابه"):
                j += 1
            if j < len(tokens) and tokens[j] in ("سنه", "عام", "لسنه", "لعام", "سنتي"):
                continue
        if j >= len(tokens):
            continue

        nxt = tokens[j]
        # 'سنة واحدة' is always a 1-year duration, never Year 1 AH
        if nxt in ("واحده", "واحد"):
            continue
        if nxt.translate(DIGITS_MAP).isdigit():
            val = int(nxt.translate(DIGITS_MAP))
            if (100 if is_bio_kw else 1) <= val <= 1500:
                extracted_years.append(val)
            continue

        num_toks = []
        approx_prefix = False
        if j < len(tokens) and tokens[j] in ("نيف", "نيفا", "بضع", "بضعه", "نحو", "حدود", "قرابه"):
            approx_prefix = True
            j += 1
        while j < len(tokens):
            tj = tokens[j]
            tj_clean = tj[1:] if tj.startswith("و") and tj[1:] in ALL_NUM_WORDS else tj
            if tj == "و" or tj_clean in ALL_NUM_WORDS:
                num_toks.append(tj)
                j += 1
            else:
                break
        # Skip spoken false-start / cut-off number phrases (e.g. 'سنة ثمان وثـ')
        if j < len(tokens) and tokens[j] == "TRUNCWORD":
            continue
        # Skip age/duration expressions like 'مقدار سنه عشر سنين'
        if j < len(tokens) and tokens[j] in ("سنين", "اعوام", "اشهر", "شهرا", "يوما"):
            continue
        if num_toks:
            val = parse_number_tokens(num_toks)
            # Handle shared tens/hundreds across 'وقيل' / 'أو' (e.g. 'سنة سبعين وقيل ستين ومائتين' or 'سنة ثلاث وقيل سبع وتسعين')
            if 1 <= val < 100 and j < len(tokens) and tokens[j] in ("وقيل", "او"):
                alt_groups = [[num_toks]]
                k_scan = j
                while k_scan < len(tokens) and tokens[k_scan] in ("وقيل", "او"):
                    k_scan += 1
                    grp = []
                    while k_scan < len(tokens):
                        tk = tokens[k_scan]
                        tk_c = tk[1:] if tk.startswith("و") and tk[1:] in ALL_NUM_WORDS else tk
                        if tk == "و" or tk_c in ALL_NUM_WORDS:
                            grp.append(tk)
                            k_scan += 1
                        else:
                            break
                    if grp:
                        alt_groups.append(grp)
                    else:
                        break
                if len(alt_groups) > 1:
                    last_grp = alt_groups[-1]
                    last_val = parse_number_tokens(last_grp)
                    shared_base = (last_val // 100) * 100 if last_val >= 100 else ((last_val // 10) * 10 if last_val >= 20 and val < 10 else 0)
                    if shared_base > 0:
                        extracted_years.append(val + shared_base)
                        extracted_years.append(last_val)
                        continue
            min_valid_yr = 100 if is_bio_kw else 1
            if min_valid_yr <= val <= 1500:
                extracted_years.append(val)
    return extracted_years


def tag_chronology_source(
    chronology: list, chunk_text: str, part_explicit_years: list, pt: int, isnad_prefix: str = "", clean_matn: str = ""
) -> list:
    passage_years = extract_date_years_from_text(chunk_text)
    matn_years = extract_date_years_from_text(clean_matn) if (isnad_prefix and clean_matn) else passage_years
    isnad_years = extract_date_years_from_text(isnad_prefix) if isnad_prefix else []
    has_approx_decade = bool(re.search(r"\b(?:نيف|نيفا|بضع|بضعة)\b", TASHKEEL_RE.sub("", chunk_text)))
    out = []
    for ch in chronology:
        if not isinstance(ch, dict):
            continue
        hy = ch.get("hijri_year")
        etag = (ch.get("event_tag") or ch.get("event") or "").strip()
        if hy is None and not etag:
            continue
        century_basis = None
        if isinstance(hy, int):
            if hy in passage_years or (has_approx_decade and any(py % 10 == 0 and py <= hy <= py + 9 for py in passage_years)):
                y_src = "text_explicit"
            elif hy >= 100 and (hy % 100) in passage_years:
                matching_basis = [y for y in part_explicit_years if y >= 100 and (y // 100) == (hy // 100)]
                if matching_basis:
                    y_src = "text_expanded"
                    century_basis = f"explicit_year_{matching_basis[-1]}_in_part_{pt}"
                else:
                    y_src = "metadata_inferred"
            else:
                y_src = "metadata_inferred"
        else:
            y_src = "metadata_inferred"

        is_transmission_date = bool(
            isinstance(hy, int)
            and hy in isnad_years
            and hy not in matn_years
        ) or any(w in etag for w in ("سماع", "رواية", "إملاء", "قراءة على"))

        entry = {
            "hijri_year": hy,
            "event_tag": etag,
            "year_source": y_src,
            "event_layer": ch.get("event_layer") or ("transmission" if is_transmission_date else "biography_or_event"),
        }
        if century_basis:
            entry["century_basis"] = century_basis
        out.append(entry)

    for y in matn_years:
        if y >= 100:
            part_explicit_years.append(y)
    return out


def tag_evidence_source_origin(evidences: list, chunk_text: str, linked_fn_texts: list) -> list:
    norm_chunk, _ = normalize_words_only(chunk_text, strip_ed_noise=True)
    norm_fns, _ = normalize_words_only(" ".join(linked_fn_texts), strip_ed_noise=True)
    out = []
    for ev in evidences:
        if not isinstance(ev, dict):
            continue
        ev_copy = dict(ev)
        src = (ev_copy.get("source") or "").strip()
        ev_txt = (ev_copy.get("text") or "").strip()
        norm_src, _ = normalize_words_only(src, strip_ed_noise=True)
        norm_ev_txt, _ = normalize_words_only(ev_txt, strip_ed_noise=True)
        src_words = [
            w for w in norm_src.split()
            if len(w) >= 4 and w not in ("سوره", "الايه", "رواه", "اخرجه", "كتاب", "قوله", "تعالي", "حديث")
        ]

        # Check where the evidence text itself lives
        ev_words = [w for w in norm_ev_txt.split() if len(w) >= 3]
        probe_span = " ".join(ev_words[:min(5, len(ev_words))]) if len(ev_words) >= 2 else norm_ev_txt
        if probe_span and probe_span in norm_chunk:
            text_origin = "matn_verified"
        elif probe_span and norm_fns and probe_span in norm_fns:
            text_origin = "footnote_verified"
        else:
            text_origin = "paraphrased"

        # Check where the citation reference (surah/book name) lives
        if any(w in norm_chunk for w in src_words):
            ref_origin = "matn"
        elif norm_fns and any(w in norm_fns for w in src_words):
            ref_origin = "footnote"
        else:
            ref_origin = "model_takhrij"

        ev_copy["text_origin"] = text_origin
        ev_copy["ref_origin"] = ref_origin
        ev_copy["source_origin"] = "matn" if text_origin == "matn_verified" or ref_origin == "matn" else (
            "footnote" if text_origin == "footnote_verified" or ref_origin == "footnote" else "model_takhrij"
        )
        out.append(ev_copy)
    return out


def load_known_folio_markers(book_id: int) -> dict:
    if not KNOWN_ISSUES_PATH.exists():
        return {}
    data = json.loads(KNOWN_ISSUES_PATH.read_text(encoding="utf-8"))
    for entry in data.get("folio_markers", []):
        if entry.get("book_id") == book_id:
            return {int(k): list(v) for k, v in entry.get("part_folios", {}).items()}
    return {}


def classify_and_link_book_footnotes(book_id: int, science: str, parts_list: list, passages_by_part: dict):
    consumed_fn_ids = set()
    fn_owner_part = {}
    part_classifications = {}
    gate_errors = []

    # Check if parts_list uses v4 LCS pre-aligned footnote spans (Rounds 4..10)
    if parts_list and any("aligned_fn_spans" in p for p in parts_list):
        for p in parts_list:
            pt = p["i"]
            raw_text = p["text"]
            p_passages = passages_by_part.get(pt, [])
            for pas in p_passages:
                pas["fn_refs"] = []

            aligned_starts = {sp[0] for sp in p.get("aligned_fn_spans", [])}
            for m_neg in re.finditer(r"\(¬([٠-٩0-9]+)\)", raw_text):
                if m_neg.start() not in aligned_starts:
                    gate_errors.append(
                        f"UNMATCHED_FN_MARKER in book {book_id} part {pt}: unaligned (¬N) marker {m_neg.group(0)} at {m_neg.start()}"
                    )

            matched_fn_positions = []
            for cand_fn in p.get("fn", []):
                fn_id = cand_fn["fn_id"]
                if fn_id in fn_owner_part and fn_owner_part[fn_id] != pt:
                    gate_errors.append(f"FN_COLLISION: {fn_id} claimed by part {fn_owner_part[fn_id]} and {pt}")
                fn_owner_part[fn_id] = pt
                l_status = cand_fn.get("link_status", "linked")
                if l_status == "linked" and "linked_char_start" in cand_fn:
                    consumed_fn_ids.add(fn_id)
                    tok_start = cand_fn["linked_char_start"]
                    pg_int = int(cand_fn["page"]) if str(cand_fn["page"]).isdigit() else p.get("pg")
                    matched_fn_positions.append((tok_start, pg_int, fn_id))
                    for pas in p_passages:
                        if pas["start_offset"] <= tok_start < pas["end_offset"]:
                            if fn_id not in pas["fn_refs"]:
                                pas["fn_refs"].append(fn_id)
                            break
                elif l_status == "orphan_note_acked":
                    consumed_fn_ids.add(fn_id)
                    if p_passages and fn_id not in p_passages[0]["fn_refs"]:
                        p_passages[0]["fn_refs"].append(fn_id)
                else:
                    gate_errors.append(f"UNLINKED_FN_IN_WINDOW in book {book_id} part {pt}: {fn_id}")

            part_start_pg = p.get("pg")
            valid_fn_positions = [(pos_i, pg_i, fid) for pos_i, pg_i, fid in matched_fn_positions if isinstance(pg_i, int)]
            if valid_fn_positions:
                first_fn_pg = valid_fn_positions[0][1]
                last_fn_pg = valid_fn_positions[-1][1]
                p["pg"] = min(part_start_pg, first_fn_pg) if isinstance(part_start_pg, int) else first_fn_pg
                p["pg_end"] = max(part_start_pg, last_fn_pg) if isinstance(part_start_pg, int) else last_fn_pg
                p["page_basis"] = "inferred_from_fn"
                for pas in p_passages:
                    pas_pgs = [pg_i for pos_i, pg_i, _ in valid_fn_positions if pas["start_offset"] <= pos_i < pas["end_offset"]]
                    if pas_pgs:
                        pas["pg_start"] = min(pas_pgs)
                        pas["pg_end"] = max(pas_pgs)
                        pas["pg"] = pas["pg_start"]
                        pas["page_basis"] = "inferred_from_fn"
                    else:
                        before_pgs = [pg_i for pos_i, pg_i, _ in valid_fn_positions if pos_i < pas["start_offset"]]
                        after_pgs = [pg_i for pos_i, pg_i, _ in valid_fn_positions if pos_i >= pas["end_offset"]]
                        inferred_pg = before_pgs[-1] if before_pgs else (after_pgs[0] if after_pgs else part_start_pg)
                        pas["pg_start"] = inferred_pg
                        pas["pg_end"] = inferred_pg
                        pas["pg"] = inferred_pg
                        pas["page_basis"] = "inferred_from_fn"
            else:
                part_end_pg = p.get("pg_end") if isinstance(p.get("pg_end"), int) else part_start_pg
                part_len = max(1, len(raw_text))
                if isinstance(part_start_pg, int) and isinstance(part_end_pg, int) and part_end_pg > part_start_pg:
                    pg_span = part_end_pg - part_start_pg
                    for pas in p_passages:
                        r0 = pas["start_offset"] / part_len
                        r1 = pas["end_offset"] / part_len
                        pas["pg_start"] = part_start_pg + int(round(r0 * pg_span))
                        pas["pg_end"] = max(pas["pg_start"], part_start_pg + int(round(r1 * pg_span)))
                        pas["pg"] = pas["pg_start"]
                        pas["page_basis"] = "part_range_interpolated"
                else:
                    for pas in p_passages:
                        pas["pg_start"] = part_start_pg
                        pas["pg_end"] = part_start_pg
                        pas["pg"] = part_start_pg
                        pas["page_basis"] = "part_start_only"

            part_classifications[pt] = p.get("aligned_fn_spans", [])
        return consumed_fn_ids, part_classifications, gate_errors

    known_part_folios = load_known_folio_markers(book_id)

    paren_re = re.compile(r"\((¬?)([٠-٩0-9]+|[*]+)\)")

    def parse_marker_val(s: str):
        tr = s.translate(DIGITS_MAP)
        return int(tr) if tr.isdigit() else s

    for p in parts_list:
        pt = p["i"]
        raw_text = p["text"]
        p_passages = passages_by_part.get(pt, [])
        for pas in p_passages:
            pas["fn_refs"] = []

        avail_fns = [f for f in p.get("fn", []) if f["fn_id"] not in consumed_fn_ids]
        remaining_known_folios = list(known_part_folios.get(int(pt), []))

        surah_paren_spans = set()
        folio_paren_spans = set()

        if science == "3olomQuran":
            pos = 0
            for ln in raw_text.splitlines(keepends=True):
                ln_clean = TASHKEEL_RE.sub("", ln).strip()
                if re.match(r"^\s*[٠-٩0-9]+\s*-\s*", ln_clean):
                    sub_items = [m for m in re.finditer(r"[٠-٩0-9]+\s*-\s*.*?(?=(?:\s+[٠-٩0-9]+\s*-\s*)|$)", ln)]
                    for sm in sub_items:
                        sub_txt = sm.group(0)
                        sub_off = pos + sm.start()
                        p_ms = list(paren_re.finditer(sub_txt))
                        if not p_ms:
                            continue
                        last_m = p_ms[-1]
                        surah_paren_spans.add((sub_off + last_m.start(), sub_off + last_m.end()))
                        if len(p_ms) > 1:
                            first_m = p_ms[0]
                            prefix_before_first = TASHKEEL_RE.sub("", sub_txt[: first_m.start()]).strip()
                            if re.match(r"^[٠-٩0-9]+\s*-\s*$", prefix_before_first):
                                folio_paren_spans.add((sub_off + first_m.start(), sub_off + first_m.end()))
                pos += len(ln)

        tokens = []
        for m in paren_re.finditer(raw_text):
            s_off, e_off = m.start(), m.end()
            has_neg = bool(m.group(1))
            val = parse_marker_val(m.group(2))
            if (s_off, e_off) in surah_paren_spans:
                cls = "surah_number"
            elif (s_off, e_off) in folio_paren_spans:
                cls = "folio_number"
                if val in remaining_known_folios:
                    remaining_known_folios.remove(val)
            elif not has_neg and val in remaining_known_folios:
                cls = "folio_number"
                remaining_known_folios.remove(val)
            else:
                cls = "footnote_marker"
            tokens.append({
                "start": s_off,
                "end": e_off,
                "raw": m.group(0),
                "val": val,
                "has_neg": has_neg,
                "class": cls,
            })

        fn_tokens = [t for t in tokens if t["class"] == "footnote_marker"]
        fn_cursor = 0
        matched_fn_positions = []
        book_uses_bare_markers = not any(paren_re.search(p_item.get("text", "")) for p_item in parts_list)

        if not fn_tokens and avail_fns and book_uses_bare_markers:
            # Fallback for editions with bare attached footnote markers (e.g. 'لبعضِي٣', '* ترجمته') without parentheses
            pos_scan = 0
            for cand_fn in avail_fns:
                fn_id = cand_fn["fn_id"]
                mk = str(cand_fn.get("marker", "")).strip()
                pat = re.escape(mk) + r"(?![٠-٩0-9*])"
                m_bare = re.search(pat, raw_text[pos_scan:]) if mk else None
                if m_bare:
                    tok_start = pos_scan + m_bare.start()
                    pos_scan += m_bare.end()
                else:
                    tok_start = pos_scan
                consumed_fn_ids.add(fn_id)
                fn_owner_part[fn_id] = pt
                pg_int = int(cand_fn["page"]) if str(cand_fn["page"]).isdigit() else p.get("pg")
                matched_fn_positions.append((tok_start, pg_int, fn_id))
                for pas in p_passages:
                    if pas["start_offset"] <= tok_start < pas["end_offset"]:
                        if fn_id not in pas["fn_refs"]:
                            pas["fn_refs"].append(fn_id)
                        break

        for tok in fn_tokens:
            matched = False
            while fn_cursor < len(avail_fns):
                cand_fn = avail_fns[fn_cursor]
                cand_val = parse_marker_val(cand_fn["marker"])
                if cand_val == tok["val"]:
                    fn_id = cand_fn["fn_id"]
                    tok["fn_id"] = fn_id
                    consumed_fn_ids.add(fn_id)
                    if fn_id in fn_owner_part and fn_owner_part[fn_id] != pt:
                        gate_errors.append(f"FN_COLLISION: {fn_id} claimed by part {fn_owner_part[fn_id]} and {pt}")
                    fn_owner_part[fn_id] = pt
                    pg_int = int(cand_fn["page"]) if str(cand_fn["page"]).isdigit() else p.get("pg")
                    matched_fn_positions.append((tok["start"], pg_int, fn_id))
                    for pas in p_passages:
                        if pas["start_offset"] <= tok["start"] < pas["end_offset"]:
                            if fn_id not in pas["fn_refs"]:
                                pas["fn_refs"].append(fn_id)
                            break
                    fn_cursor += 1
                    matched = True
                    break
                elif fn_cursor > 0 and tok["raw"] in (avail_fns[fn_cursor - 1].get("text") or "")[:25]:
                    # Combined footnote entry in printed margin, e.g. '(٥) و (٦) سبأ: ٢٣.'
                    prev_fn = avail_fns[fn_cursor - 1]
                    fn_id = prev_fn["fn_id"]
                    tok["fn_id"] = fn_id
                    pg_int = int(prev_fn["page"]) if str(prev_fn["page"]).isdigit() else p.get("pg")
                    matched_fn_positions.append((tok["start"], pg_int, fn_id))
                    for pas in p_passages:
                        if pas["start_offset"] <= tok["start"] < pas["end_offset"]:
                            if fn_id not in pas["fn_refs"]:
                                pas["fn_refs"].append(fn_id)
                            break
                    matched = True
                    break
                else:
                    break
            if not matched:
                if not any(p_item.get("fn") for p_item in parts_list):
                    tok["class"] = "source_stripped_footnote_marker"
                else:
                    gate_errors.append(f"UNMATCHED_FN_MARKER in book {book_id} part {pt}: {tok}")

        part_start_pg = p.get("pg")
        valid_fn_positions = [(pos_i, pg_i, fid) for pos_i, pg_i, fid in matched_fn_positions if isinstance(pg_i, int)]
        if valid_fn_positions:
            first_fn_pg = valid_fn_positions[0][1]
            last_fn_pg = valid_fn_positions[-1][1]
            p["pg"] = min(part_start_pg, first_fn_pg) if isinstance(part_start_pg, int) else first_fn_pg
            p["pg_end"] = max(part_start_pg, last_fn_pg) if isinstance(part_start_pg, int) else last_fn_pg
            p["page_basis"] = "inferred_from_fn"
            for pas in p_passages:
                pas_pgs = [pg_i for pos_i, pg_i, _ in valid_fn_positions if pas["start_offset"] <= pos_i < pas["end_offset"]]
                if pas_pgs:
                    pas["pg_start"] = min(pas_pgs)
                    pas["pg_end"] = max(pas_pgs)
                    pas["pg"] = pas["pg_start"]
                    pas["page_basis"] = "inferred_from_fn"
                else:
                    before_pgs = [pg_i for pos_i, pg_i, _ in valid_fn_positions if pos_i < pas["start_offset"]]
                    after_pgs = [pg_i for pos_i, pg_i, _ in valid_fn_positions if pos_i >= pas["end_offset"]]
                    inferred_pg = before_pgs[-1] if before_pgs else (after_pgs[0] if after_pgs else part_start_pg)
                    pas["pg_start"] = inferred_pg
                    pas["pg_end"] = inferred_pg
                    pas["pg"] = inferred_pg
                    pas["page_basis"] = "inferred_from_fn"
        else:
            part_end_pg = p.get("pg_end") if isinstance(p.get("pg_end"), int) else part_start_pg
            part_len = max(1, len(raw_text))
            if isinstance(part_start_pg, int) and isinstance(part_end_pg, int) and part_end_pg > part_start_pg:
                pg_span = part_end_pg - part_start_pg
                for pas in p_passages:
                    r0 = pas["start_offset"] / part_len
                    r1 = pas["end_offset"] / part_len
                    pas["pg_start"] = part_start_pg + int(round(r0 * pg_span))
                    pas["pg_end"] = max(pas["pg_start"], part_start_pg + int(round(r1 * pg_span)))
                    pas["pg"] = pas["pg_start"]
                    pas["page_basis"] = "part_range_interpolated"
            else:
                for pas in p_passages:
                    pas["pg_start"] = part_start_pg
                    pas["pg_end"] = part_start_pg
                    pas["pg"] = part_start_pg
                    pas["page_basis"] = "part_start_only"

        part_classifications[pt] = tokens

    return consumed_fn_ids, part_classifications, gate_errors


def verify_and_locate_span_in_part(snippet: str, raw_part: str, allow_elision: bool = True):
    """
    Strictly verifies 100% of snippet from first word to last word against raw_part
    with strict word-boundary matching. NO 8-word fallback and NO silent auto-healing.
    """
    if not snippet or not raw_part:
        return "failed", -1, -1

    exact_pos = raw_part.find(snippet)
    if exact_pos != -1:
        return "exact", exact_pos, exact_pos + len(snippet)

    has_ellipsis = bool(re.search(r"\.{2,}|…+", snippet))
    raw_has_hemistich_sep = (".." in raw_part) or ("**" in raw_part) or ("* *" in raw_part)
    if has_ellipsis and not allow_elision and not raw_has_hemistich_sep:
        return "failed", -1, -1

    for norm_fn in (normalize_words_only, _normalize_words_with_honorifics):
        norm_part, part_map = norm_fn(raw_part, strip_ed_noise=True)
        if not norm_part:
            continue

        # Pre-strip FOLIO_MARKER_RE and EDITION_PAGE_RE from snippet before splitting on '/' or poetic '**'
        snippet_clean = FOLIO_MARKER_RE.sub(" ", snippet)
        snippet_clean = EDITION_PAGE_RE.sub(" ", snippet_clean)
        raw_segs = [s.strip() for s in re.split(r"\.{2,}|…+|/|\*(?:\s*\*)+", snippet_clean) if s.strip()]
        if not raw_segs:
            continue

        seg_spans = []
        search_from = 0
        failed_seg = False
        for seg in raw_segs:
            norm_seg, _ = norm_fn(seg, strip_ed_noise=True)
            if not norm_seg:
                failed_seg = True
                break
            pos = find_word_bounded(norm_part, norm_seg, search_from)
            if pos == -1:
                failed_seg = True
                break
            orig_s = part_map[pos]
            orig_e = part_map[min(len(part_map) - 1, pos + len(norm_seg) - 1)] + 1
            while orig_e < len(raw_part) and (TASHKEEL_RE.match(raw_part[orig_e]) or raw_part[orig_e] == "\u0640"):
                orig_e += 1
            seg_spans.append((pos, pos + len(norm_seg), orig_s, orig_e, len(norm_seg.split())))
            search_from = pos + len(norm_seg)

        if failed_seg or not seg_spans:
            continue

        span_start = seg_spans[0][2]
        span_end = seg_spans[-1][3]

        if len(seg_spans) == 1:
            if has_ellipsis and not raw_has_hemistich_sep:
                continue
            return "exact", span_start, span_end

        max_word_gap = 0
        for i in range(len(seg_spans) - 1):
            between = norm_part[seg_spans[i][1] : seg_spans[i + 1][0]].strip()
            gap_words = len(between.split()) if between else 0
            if gap_words > max_word_gap:
                max_word_gap = gap_words

        if max_word_gap == 0 and (not has_ellipsis or raw_has_hemistich_sep):
            return "hemistich", span_start, span_end

        if allow_elision and len(seg_spans) <= 2 and max_word_gap <= 25 and all(s[4] >= 4 for s in seg_spans):
            return "elided_exact", span_start, span_end

    return "failed", -1, -1


def check_semantic_grounding_v41(
    science: str,
    pid_str: str,
    sub_h: str,
    summary: str,
    topics: list,
    raw_window_context: str,
    raw_part: str,
    meta: dict,
    p0_errors: list,
):
    norm_ctx, _ = normalize_words_only(raw_window_context, strip_ed_noise=True)
    norm_part, _ = normalize_words_only(raw_part, strip_ed_noise=True)
    author_norm, _ = normalize_words_only(meta.get("author", ""), strip_ed_noise=True)
    title_norm, _ = normalize_words_only(meta.get("title", ""), strip_ed_noise=True)

    combined_sem = f"{sub_h} | {summary} | {' | '.join(topics or [])}"

    # 1. Check inline quotes «...» inside summary/sub_heading/topics
    for m_q in re.finditer(r"«([^»]{4,140})»", combined_sem):
        q_in = m_q.group(1).strip()
        norm_q, _ = normalize_words_only(q_in, strip_ed_noise=True)
        q_words = norm_q.split()
        # Check if it's a book title or author name
        if norm_q and (norm_q in title_norm or norm_q in author_norm):
            continue
        if len(q_words) >= 3:
            v_mode, _, _ = verify_and_locate_span_in_part(q_in, raw_part, allow_elision=True)
            if v_mode == "failed" and norm_q not in norm_part:
                p0_errors.append(
                    f"[{science}] P0_UNGROUNDED_INLINE_QUOTE in {pid_str}: «{q_in}» does not exist in source text"
                )
        elif len(q_words) == 2:
            # 2-word quoted nicknames like «قرآن النحو» or «أم عاصم»
            if norm_q not in norm_part:
                p0_errors.append(
                    f"[{science}] P0_UNGROUNDED_INLINE_QUOTE in {pid_str}: «{q_in}» does not exist in source text"
                )

    # 2. Check explicit 'X بن Y' person names in summary/sub_heading/topics against part text
    norm_sem, _ = normalize_words_only(combined_sem, strip_ed_noise=True)
    for m_p in re.finditer(r"\b([ء-ي]{3,})\s+بن\s+([ء-ي]{3,}(?:\s+ال[ء-ي]{3,})?)\b", norm_sem):
        x_raw = m_p.group(1)
        x_name = x_raw[1:] if len(x_raw) >= 4 and x_raw[0] in "وفبلك" else x_raw
        y_name = m_p.group(2).split()[0]
        full_pat = f"{x_name} بن {y_name}"
        if full_pat in author_norm or full_pat in title_norm or f"{x_raw} بن {y_name}" in norm_part:
            continue
        if x_name in ("رسول", "نبي", "كتاب", "قول", "حديث", "امير", "خليفه", "شيخ", "علماء", "اهل") or x_raw in ("رسول", "نبي", "كتاب", "قول", "حديث", "امير", "خليفه", "شيخ", "علماء", "اهل"):
            continue
        # Check if full_pat or both x_name and y_name exist in the part (or if it's a well-known full name of someone whose kunya/first name is in norm_ctx)
        if full_pat not in norm_part:
            # Allow if x_name or y_name is in norm_ctx AND the other isn't contradicted, EXCEPT when y_name is completely absent from the entire part!
            if y_name not in norm_part and x_name not in norm_ctx and x_raw not in norm_ctx:
                p0_errors.append(
                    f"[{science}] P0_UNGROUNDED_PERSON_IN_SUMMARY in {pid_str}: '{m_p.group(0)}' not found in part text"
                )
            elif full_pat == "عمر بن هبيره" and "عمر بن هبيره" not in norm_part:
                p0_errors.append(
                    f"[{science}] P0_UNGROUNDED_PERSON_IN_SUMMARY in {pid_str}: 'عمر بن هبيرة' fabricated (source says 'يوسف بن عمر')"
                )

    # Check known ungrounded maternal/kunya fabrications
    if "ام عاصم" in norm_sem and "ام عاصم" not in norm_part:
        p0_errors.append(
            f"[{science}] P0_UNGROUNDED_PERSON_IN_SUMMARY in {pid_str}: 'أم عاصم' not in source text"
        )


def resolve_item_to_passages(item: dict, cands: list, raw_part: str, is_verbatim_item: bool = True, allow_elision: bool = True):
    field_name = "verbatim_rule" if "verbatim_rule" in item else ("quote" if "quote" in item else "")
    text_probe = (item.get(field_name) or "").strip() if field_name else ""

    if is_verbatim_item:
        if not text_probe:
            return None, [], "failed", "empty_verbatim", -1, -1
        v_mode, s_start, s_end = verify_and_locate_span_in_part(text_probe, raw_part, allow_elision=allow_elision)
        if v_mode == "failed":
            return None, [], "failed", "failed_verbatim", -1, -1

        overlapping = [
            p["pid"]
            for p in cands
            if max(p["start_offset"], s_start) < min(p["end_offset"], s_end)
        ]
        if v_mode == "elided_exact" and len(overlapping) > 1:
            return None, [], "failed", "elided_cross_passage", s_start, s_end
        if overlapping:
            return overlapping[0], overlapping, v_mode, "exact_span", s_start, s_end
        return None, [], "failed", "failed_passage_overlap", s_start, s_end

    anc = (item.get("anchor_start") or "").strip()
    if anc:
        off, st = find_anchor_offset(raw_part, anc, 0)
        if st != "failed" and off != -1:
            for p in cands:
                if p["start_offset"] <= off < p["end_offset"]:
                    anc_end = (item.get("anchor_end") or "").strip()
                    s_end = p["end_offset"]
                    if anc_end:
                        off_e, st_e = find_anchor_offset(raw_part, anc_end, off)
                        if st_e != "failed" and off_e >= off:
                            s_end = min(len(raw_part), off_e + len(anc_end))
                    return p["pid"], [p["pid"]], "anchor_verified", "normalized_anchor", off, s_end

    return None, [], "failed", "failed_anchor", -1, -1


def align_book_passages(
    book_id: int,
    science: str,
    meta: dict,
    parts_list: list,
    passages: list,
    book_fn_map: dict,
    p0_errors: list,
    p1_warnings: list,
    round_num: int = 4,
):
    parts_by_id = {p["i"]: p["text"] for p in parts_list}
    parts_obj_by_id = {p["i"]: p for p in parts_list}
    orig_headings = {p["i"]: p.get("t", "") for p in parts_list}
    eff_headings = {p["i"]: (p.get("effective_heading") or p.get("t", "")) for p in parts_list}
    part_src_parts = {p["i"]: p.get("src_parts", []) for p in parts_list}

    by_part = {}
    for p in passages:
        pt = int(p["part"])
        if pt not in parts_by_id:
            p0_errors.append(f"[{science}] Passage references non-selected part {pt}")
            continue
        by_part.setdefault(pt, []).append(p)

    for pt in sorted(parts_by_id.keys()):
        if pt not in by_part or not by_part[pt]:
            p0_errors.append(f"[{science}] Part {pt} has 0 passages (missing coverage)")

    # Check if all passages in the book lazily copied title == sub_heading
    if passages and all(
        "title" in p and "sub_heading" in p and p.get("title") and p.get("title") == p.get("sub_heading")
        for p in passages
    ):
        p0_errors.append(f"[{science}] P0_SCHEMA_LAZY_DUPLICATE_KEYS: all {len(passages)} passages have identical 'title' and 'sub_heading'")

    aligned = []
    passages_by_part = {}
    seq = 1

    for pt in sorted(parts_by_id.keys()):
        raw_part = parts_by_id[pt]
        p_meta_obj = parts_obj_by_id[pt]
        p_list = by_part.get(pt, [])
        if not p_list:
            continue

        resolved_items = []
        cur_min = 0
        for idx, item in enumerate(p_list):
            anc = item.get("anchor_start", "")
            if idx == 0:
                actual_off, st = find_anchor_offset(raw_part, anc, 0)
                if st == "failed" or actual_off > 140:
                    p0_errors.append(
                        f"[{science}] First passage anchor failed or too far in part {pt}: off={actual_off}, st={st}, anchor={anc!r}"
                    )
                off = 0
                status = st
            else:
                actual_off, st = find_anchor_offset(raw_part, anc, cur_min)
                if st == "failed":
                    p0_errors.append(
                        f"[{science}] Interior passage {idx+1} anchor failed in part {pt}: cur_min={cur_min}, anchor={anc!r}"
                    )
                    continue
                off = snap_offset_to_heading_start(raw_part, actual_off, cur_min)
                status = st

            resolved_items.append((item, off, actual_off, status))
            cur_min = max(off, actual_off) + 12

        part_aligned = []
        part_explicit_years = extract_date_years_from_text(orig_headings.get(pt, ""))

        for idx, (item, start_off, actual_anc_off, status) in enumerate(resolved_items):
            end_off = resolved_items[idx + 1][1] if idx + 1 < len(resolved_items) else len(raw_part)
            if end_off <= start_off:
                p0_errors.append(f"[{science}] Invalid span in part {pt} passage {idx+1}: {start_off}..{end_off}")
                continue

            chunk_text = raw_part[start_off:end_off]
            pid_str = f"{book_id}:{pt}:{idx+1}"

            # Check trailing colon rule (including trailing footnote markers, quotes, or bidi marks)
            if TRAILING_COLON_RE.search(chunk_text) and end_off < len(raw_part):
                p0_errors.append(f"[{science}] Passage {pid_str} ends mid-argument with colon ':'")

            # Check dangling word at sliced part boundary
            norm_tail_words = re.findall(r"[\u0621-\u064A]+", TASHKEEL_RE.sub("", chunk_text[-60:]))
            if end_off == len(raw_part) and p_meta_obj.get("is_sliced") and norm_tail_words and norm_tail_words[-1] in ("ولا", "لا", "في", "من", "عن", "على", "إلى", "الى", "أن", "ان", "و"):
                p0_errors.append(f"[{science}] P0_DANGLING_WINDOW_BOUNDARY in {pid_str}: ends with dangling word '{norm_tail_words[-1]}'")

            # Check max length rule across ALL passages (including single-passage parts!)
            max_allowed_len = 1800 if science == "akida" else 2800
            if len(chunk_text) > max_allowed_len:
                p0_errors.append(f"[{science}] Passage {pid_str} exceeds max char length ({len(chunk_text)} > {max_allowed_len})")

            # Gate v4.1 Schema Drift & Field Completeness Check
            if "title" in item and not item.get("sub_heading"):
                p0_errors.append(f"[{science}] P0_SCHEMA_DRIFT in {pid_str}: uses 'title' without 'sub_heading'")
            if any(k in item for k in ("key_claims", "key_topics", "key_concepts")) and not item.get("topics"):
                p0_errors.append(f"[{science}] P0_SCHEMA_DRIFT in {pid_str}: uses legacy topic key without 'topics'")

            rel_anc_off = max(0, actual_anc_off - start_off)
            heading_prefix = chunk_text[:rel_anc_off].strip() if rel_anc_off > 0 else ""

            matn_anc = (item.get("matn_start_anchor") or "").strip()
            isnad_prefix, clean_matn, chain_ref, extra_hd = validate_and_extract_isnad(chunk_text, rel_anc_off, matn_anc)
            if extra_hd:
                heading_prefix = (heading_prefix + "\n" + extra_hd).strip() if heading_prefix else extra_hd
            interior_isnads = extract_interior_isnads(clean_matn)

            clean_persons = []
            for pe in item.get("persons", []):
                pe_copy = dict(pe) if isinstance(pe, dict) else {"canonical_name": str(pe), "mentioned_as": str(pe), "category": "شخصية تاريخية", "role": ""}
                if not pe_copy.get("canonical_name"):
                    pe_copy["canonical_name"] = pe_copy.get("mentioned_as", "")
                pe_copy = resolve_person_mentioned_as(pe_copy, chunk_text, isnad_prefix=isnad_prefix, clean_matn=clean_matn)
                clean_persons.append(pe_copy)

            places = filter_places_against_isnad(science, item.get("places", []), chunk_text, isnad_prefix, clean_matn=clean_matn)
            chronology = tag_chronology_source(
                item.get("chronology", []), chunk_text, part_explicit_years, pt, isnad_prefix=isnad_prefix, clean_matn=clean_matn
            )

            search_queries = [q.strip().rstrip("؟?") + "؟" for q in item.get("search_queries", []) if q.strip()]
            topics = (
                item.get("topics")
                or item.get("key_topics")
                or item.get("key_concepts")
                or item.get("key_claims")
                or item.get("key_points")
                or []
            )
            sub_h = (item.get("sub_heading") or item.get("title") or item.get("heading") or "").strip()
            orig_h_clean = orig_headings.get(pt, "").replace(" ◂ ", " - ").replace("*", "").strip()
            eff_h_clean = eff_headings.get(pt, orig_h_clean).replace(" ◂ ", " - ").replace("*", "").strip()
            par_h = item.get("parent_heading") or eff_h_clean
            if par_h in ("﷽", "بسم الله الرحمن الرحيم"):
                par_h = eff_h_clean
            summary = (item.get("summary") or "").strip()

            if round_num >= 4:
                if not sub_h:
                    p0_errors.append(f"[{science}] P0_EMPTY_SUB_HEADING in {pid_str}")
                if not summary:
                    p0_errors.append(f"[{science}] P0_EMPTY_SUMMARY in {pid_str}")
                if not topics:
                    p0_errors.append(f"[{science}] P0_EMPTY_TOPICS in {pid_str}")
                if not search_queries:
                    p0_errors.append(f"[{science}] P0_EMPTY_SEARCH_QUERIES in {pid_str}")

                # Candidate Density Checks (Explicit Years, Quranic Verses, Persons)
                matn_years_explicit = extract_date_years_from_text(clean_matn)
                has_approx_dec = bool(re.search(r"\b(?:نيف|نيفا|بضع|بضعة)\b", TASHKEEL_RE.sub("", clean_matn)))
                acked_colophon_yrs = set()
                if matn_years_explicit and not any(
                    isinstance(c.get("hijri_year"), int)
                    and (
                        c.get("hijri_year") in matn_years_explicit
                        or (has_approx_dec and any(py % 10 == 0 and py <= c["hijri_year"] <= py + 9 for py in matn_years_explicit))
                    )
                    for c in chronology
                ):
                    p0_errors.append(
                        f"[{science}] P0_MISSED_EXPLICIT_YEARS in {pid_str}: text has years {matn_years_explicit} but chronology={chronology}"
                    )
                explicit_verses = re.findall(r"﴿([^﴾]{8,})﴾", clean_matn)
                if not explicit_verses and re.search(r"(?:قال\s+(?:الله\s+)?تعالى|قوله\s+(?:تعالى|عز\s+وجل)|قال\s+الله\s+عز\s+وجل)", TASHKEEL_RE.sub("", clean_matn)):
                    explicit_verses = re.findall(r"\{([^\}]{8,})\}", clean_matn)
                if explicit_verses and not any(
                    "آية" in (ev.get("type") or "")
                    or "قرآن" in (ev.get("type") or "")
                    or "quran" in (ev.get("type") or "").lower()
                    or "آية" in (ev.get("category") or "")
                    for ev in item.get("evidences", [])
                ):
                    p0_errors.append(
                        f"[{science}] P0_MISSED_QURAN_VERSES in {pid_str}: {len(explicit_verses)} verse(s) ﴿...﴾/{'{...}'} in text but 0 in evidences"
                    )
                norm_matn_no_tash = TASHKEEL_RE.sub("", clean_matn)
                explicit_nasab = [
                    m_n.group(0)
                    for m_n in re.finditer(r"\b(?:أبو|أبي|ابن)?\s*[\u0621-\u064A]{3,}\s+بن\s+[\u0621-\u064A]{3,}", norm_matn_no_tash)
                    if not any(w in m_n.group(0) for w in ("رسول", "نبي", "رب", "سبيل", "بنت", "ابنة"))
                ]
                if explicit_nasab and not clean_persons and science in ("tarajim", "sirah", "tari5", "tazkia", "hadith", "hadith_sharh"):
                    p0_errors.append(
                        f"[{science}] P0_MISSED_PERSONS in {pid_str}: explicit names {explicit_nasab[:3]} in matn but persons=[]"
                    )

                # Semantic Grounding Check (with 1-passage left/right window for context continuity)
                ctx_lo = resolved_items[idx - 1][1] if idx > 0 else start_off
                ctx_hi = resolved_items[idx + 1][1] + 600 if idx + 1 < len(resolved_items) else end_off
                raw_window_context = raw_part[max(0, ctx_lo) : min(len(raw_part), ctx_hi)]
                check_semantic_grounding_v41(
                    science, pid_str, sub_h, summary, topics, raw_window_context, raw_part, meta, p0_errors
                )

            cleaned_matn_str = clean_for_embed(clean_matn, science=science, orig_heading=orig_h_clean, interior_isnads=interior_isnads)
            if re.search(r"\(¬[٠-٩0-9]+\)", cleaned_matn_str):
                p0_errors.append(f"[{science}] Footnote marker (¬N) leaked into embed_matn_text in {pid_str}")

            embed_matn = cleaned_matn_str

            concept_parts = [f"الملخص: {summary}"]
            if topics:
                concept_parts.append(f"الموضوعات: {'، '.join(topics)}")
            # Only include matn persons (not manuscript isnad-only transmitters) in embed_concept_text
            p_names = "، ".join(
                pe["canonical_name"]
                for pe in clean_persons
                if pe.get("canonical_name") and pe.get("mentioned_in_text") and pe.get("source_layer", "matn") == "matn"
            )
            if p_names:
                concept_parts.append(f"الأعلام: {p_names}")
            pl_names = "، ".join(pl.get("normalized_name", pl.get("name_in_text", "")) for pl in places)
            if pl_names:
                concept_parts.append(f"الأماكن: {pl_names}")
            # Only include historical/biographical dates (not manuscript sama'/transmission dates) in embed_concept_text
            verified_chron = [
                f"{c['hijri_year']} هـ ({c['event_tag']})" if c.get("hijri_year") is not None else c["event_tag"]
                for c in chronology
                if c.get("year_source") in ("text_explicit", "text_expanded")
                and c.get("event_layer", "biography_or_event") != "transmission"
                and (c.get("hijri_year") is not None or c.get("event_tag"))
            ]
            if verified_chron:
                concept_parts.append(f"التاريخ: {'، '.join(verified_chron)}")
            if search_queries:
                concept_parts.append(f"أسئلة: {' '.join(search_queries)}")

            smeta = get_science_meta(science)
            embed_concept = (
                f"title: {sub_h} — {smeta['science_ar']} ({meta.get('title', '')}) | text: "
                + " | ".join(concept_parts)
            )

            p_obj = {
                "passage_id": seq,
                "pid": pid_str,
                "part": pt,
                "pg_start": None,
                "pg_end": None,
                "pg": None,
                "page_basis": "part_start_only",
                "src_parts": part_src_parts.get(pt, []),
                "source_layer": item.get("source_layer", "matn"),
                "unit_type": item.get("unit_type", "full_passage"),
                "orig_part_heading": orig_h_clean,
                "parent_heading": par_h,
                "sub_heading": sub_h,
                "heading_prefix": heading_prefix,
                "anchor_start": item.get("anchor_start", ""),
                "matn_start_anchor": matn_anc,
                "align_status": status,
                "start_offset": start_off,
                "end_offset": end_off,
                "char_len": len(chunk_text),
                "embed_matn_char_len": len(cleaned_matn_str),
                "isnad_prefix": isnad_prefix,
                "isnad_chain_ref": chain_ref,
                "interior_isnads": interior_isnads,
                "raw_text": chunk_text,
                "summary": summary,
                "topics": topics,
                "persons": clean_persons,
                "evidences": item.get("evidences", []),
                "places": places,
                "chronology": chronology,
                "search_queries": search_queries,
                "textual_notes": item.get("textual_notes", []),
                "continues_from_pid": item.get("continues_from_pid"),
                "narrative_unit_id": item.get("narrative_unit_id"),
                "fn_refs": [],
                "embed_matn_text": embed_matn,
                "embed_concept_text": embed_concept,
            }
            part_aligned.append(p_obj)
            aligned.append(p_obj)
            seq += 1

        # Verify contiguous partition of part [0..len(raw_part)] without gaps or overlaps
        if part_aligned:
            if part_aligned[0]["start_offset"] != 0 or part_aligned[-1]["end_offset"] != len(raw_part):
                p0_errors.append(f"[{science}] Part {pt} passages do not span [0..{len(raw_part)}]")
            for k in range(len(part_aligned) - 1):
                if part_aligned[k]["end_offset"] != part_aligned[k + 1]["start_offset"]:
                    p0_errors.append(f"[{science}] Gap/overlap in part {pt} between {part_aligned[k]['pid']} and {part_aligned[k+1]['pid']}")

        passages_by_part[pt] = part_aligned

    consumed_fns, fn_cls_map, fn_errs = classify_and_link_book_footnotes(book_id, science, parts_list, passages_by_part)
    for e in fn_errs:
        p0_errors.append(f"[{science}] {e}")

    all_book_fn_ids = set(book_fn_map.keys())
    unlinked_fns = sorted(all_book_fn_ids - consumed_fns)
    if unlinked_fns:
        p0_errors.append(f"[{science}] Unlinked book footnotes: {unlinked_fns}")

    # Now tag and verify evidence source_origin against passage text and linked footnotes
    for pas in aligned:
        linked_fn_texts = [book_fn_map[fid]["text"] for fid in pas["fn_refs"] if fid in book_fn_map]
        pas["evidences"] = tag_evidence_source_origin(pas.get("evidences", []), pas["raw_text"], linked_fn_texts)

    return aligned, unlinked_fns


def audit_and_merge_round(round_num: int = 3, raw_override: dict = None, deep_overrides: dict = None, work_dir: Path = None):
    wdir = Path(work_dir) if work_dir is not None else BASE
    raw_path = wdir / f"raw_round{round_num}_books.json"
    raw_r = raw_override if raw_override is not None else json.loads(raw_path.read_text(encoding="utf-8"))
    base_order = ["tarajim", "sirah", "tari5", "tazkia", "akida", "maliki", "ossoul", "3olomQuran", "9awa3idFi9h"]
    order = [sc for sc in base_order if sc in raw_r] + [sc for sc in raw_r.keys() if sc not in base_order]
    books_out = []
    p0_errors = []
    p1_warnings = []

    if not order:
        p0_errors.append("P0_NO_BOOKS_IN_ROUND: raw_r contains no science entries")

    total_passages_all = 0
    total_gems_all = 0
    total_quotes_all = 0

    for sc in order:
        raw_b = raw_r[sc]
        if deep_overrides and sc in deep_overrides:
            deep_b = deep_overrides[sc]
        else:
            f_path = wdir / f"r{round_num}_deep_{sc}.json"
            deep_b = json.loads(f_path.read_text(encoding="utf-8"))

        parts_list = []
        for idx_p, p_in in enumerate(raw_b["parts"]):
            p_copy = dict(p_in)
            if "i" not in p_copy:
                p_copy["i"] = p_copy.get("part", idx_p)
            if "t" not in p_copy:
                p_copy["t"] = p_copy.get("title", f"الجزء {p_copy['i']}")
            if "text_sha256" not in p_copy and "text" in p_copy:
                p_copy["text_sha256"] = sha16(p_copy["text"])
            parts_list.append(p_copy)
        parts_by_id = {p["i"]: p["text"] for p in parts_list}
        seen_bf_ids = {}
        for idx_f, f in enumerate(raw_b.get("book_footnotes", [])):
            if "fn_id" not in f:
                base_fid = f"{raw_b['book_id']}:p{f.get('page', 0)}:{f.get('seq_in_page', f.get('seq', idx_f + 1))}"
                cnt = seen_bf_ids.get(base_fid, 0) + 1
                seen_bf_ids[base_fid] = cnt
                f["fn_id"] = base_fid if cnt == 1 else f"{base_fid}#{cnt}"
        seen_pf_ids = {}
        for p in parts_list:
            if isinstance(p.get("fn"), list):
                for idx_f, f in enumerate(p["fn"]):
                    if isinstance(f, dict) and "fn_id" not in f:
                        base_fid = f"{raw_b['book_id']}:p{f.get('page', p.get('pg', 0))}:{f.get('seq_in_page', f.get('seq', idx_f + 1))}"
                        cnt = seen_pf_ids.get(base_fid, 0) + 1
                        seen_pf_ids[base_fid] = cnt
                        f["fn_id"] = base_fid if cnt == 1 else f"{base_fid}#{cnt}"
        book_fn_map = {f["fn_id"]: f for f in raw_b.get("book_footnotes", [])}

        # Verify part text SHA256 integrity against text_sha256 and source_patches / orig_raw_sha256
        patch_file = PATCH_DIR / f"{raw_b['book_id']}.json"
        patch_recon = {}
        if patch_file.exists():
            patch_recon = json.loads(patch_file.read_text(encoding="utf-8")).get("reconstructed_parts", {})
        for p in parts_list:
            pi_str = str(p["i"])
            actual_sha = sha16(p["text"])
            if actual_sha != p.get("text_sha256"):
                p0_errors.append(
                    f"[{sc}] Part {p['i']} text tampered! sha16(text)={actual_sha} != text_sha256={p.get('text_sha256')}"
                )
            if pi_str in patch_recon:
                exp_patch_sha = patch_recon[pi_str].get("text_sha256")
                if actual_sha != exp_patch_sha:
                    p0_errors.append(
                        f"[{sc}] Patched part {p['i']} sha16(text)={actual_sha} != patch expected={exp_patch_sha}"
                    )
            else:
                if p.get("orig_raw_sha256") and actual_sha != p.get("orig_raw_sha256"):
                    p0_errors.append(
                        f"[{sc}] Unpatched part {p['i']} sha16(text)={actual_sha} != orig_raw_sha256={p.get('orig_raw_sha256')}"
                    )

        # Generalized numbered-entry sequence integrity check
        if round_num <= 3 and sc in ("tarajim", "sirah"):
            entry_re = re.compile(r"(?:^|\n)\s*(?:\(خَ\)\s*)?([٠-٩]+)\s*-\s*")
            seen_entries = []
            for p in parts_list:
                if p["i"] == 0 and raw_b["book_id"] == 2295:
                    continue
                for m in entry_re.finditer(p["text"]):
                    seen_entries.append(to_ascii_int(m.group(1)))
            if len(seen_entries) >= 10:
                expected_seq = list(range(1, len(seen_entries) + 1))
                if seen_entries != expected_seq:
                    p0_errors.append(
                        f"[{sc} {raw_b['book_id']}] Entry sequence is not 1..{len(expected_seq)}! len={len(seen_entries)}"
                    )
        elif round_num >= 4 and sc != "tari5":
            # Stage 5 LIS-based sequence check v4 (Opus §4.7)
            entry_v4_re = re.compile(r"(?:^|\n)\s*(?:\(خَ\)\s*)?([٠-٩0-9]+)\*{0,3}\s*[-–]\s*(?:([٠-٩0-9]+)\s*[-–]?\s*)?")
            nums = []
            for p in parts_list:
                for m in entry_v4_re.finditer(p["text"]):
                    n1 = to_ascii_int(m.group(1))
                    if n1 >= 600:
                        continue
                    nums.append(n1)
                    if m.group(2):
                        n2 = to_ascii_int(m.group(2))
                        if n1 < n2 <= n1 + 5:
                            for r_val in range(n1 + 1, n2 + 1):
                                nums.append(r_val)
            if len(nums) >= 10:
                n_len = len(nums)
                best_dp = [1] * n_len
                prev_dp = [-1] * n_len
                for i_dp in range(n_len):
                    for j_dp in range(max(0, i_dp - 60), i_dp):
                        if 1 <= nums[i_dp] - nums[j_dp] <= 4 and best_dp[j_dp] + 1 > best_dp[i_dp]:
                            best_dp[i_dp] = best_dp[j_dp] + 1
                            prev_dp[i_dp] = j_dp
                k_dp = max(range(n_len), key=lambda x: best_dp[x])
                chain = []
                while k_dp != -1:
                    chain.append(nums[k_dp])
                    k_dp = prev_dp[k_dp]
                chain.reverse()
                all_txt = "\n".join(p["text"] for p in parts_list)
                acked_gaps = set(raw_b.get("scope", {}).get("acks", {}).get("numbering_gaps", []))
                for a_val, b_val in zip(chain, chain[1:]):
                    for miss in range(a_val + 1, b_val):
                        if miss in acked_gaps or miss in nums:
                            continue
                        ar_miss = str(miss).translate(str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩"))
                        if re.search(r"(?<![٠-٩0-9/])(?:" + re.escape(ar_miss) + r"|" + str(miss) + r")\*{0,3}\s*[-–.)]", all_txt):
                            p1_warnings.append(f"[{sc} {raw_b['book_id']}] NUMBERING_FORMAT_VARIANT for #{miss}")
                        else:
                            p1_warnings.append(f"[{sc} {raw_b['book_id']}] Edition numbering skip #{miss} between {a_val} and {b_val}")

        aligned_passages, unlinked_fns = align_book_passages(
            raw_b["book_id"],
            sc,
            raw_b["meta"],
            parts_list,
            deep_b.get("deep_toc_passages", []),
            book_fn_map,
            p0_errors,
            p1_warnings,
            round_num=round_num,
        )
        passages_by_part = {}
        for p in aligned_passages:
            passages_by_part.setdefault(p["part"], []).append(p)

        # Verify science_gems strictly (no auto-heal, no '...' elision allowed!)
        gems = []
        gem_norm_set = set()
        for idx_g, g in enumerate(deep_b.get("science_gems", [])):
            g = dict(g)
            g.pop("content", None)
            g.pop("detail", None)
            pt = int(g.get("part", -1))
            if pt not in parts_by_id:
                p0_errors.append(f"[{sc}] Gem #{idx_g+1} references invalid part {pt}")
                continue
            if round_num >= 4:
                g_title = (g.get("title") or "").strip()
                g_cat = (g.get("category") or "").strip()
                g_vrule = (g.get("verbatim_rule") or "").strip()
                if not g_title:
                    p0_errors.append(f"[{sc}] P0_GEM_MISSING_TITLE: Gem #{idx_g+1} in part {pt} has empty title")
                if g_cat and re.match(r"^[a-zA-Z0-9_-]+$", g_cat):
                    p0_errors.append(f"[{sc}] P0_GEM_ENGLISH_CATEGORY: Gem #{idx_g+1} has ASCII category {g_cat!r} instead of Arabic")
                if re.match(r"^أن\s+", TASHKEEL_RE.sub("", g_vrule)):
                    p0_errors.append(f"[{sc}] P0_GEM_DANGLING_START: Gem #{idx_g+1} starts with dangling clause 'أن ...': {g_vrule[:50]!r}")
                if g.get("explanation") and g.get("analytical_sharh") and g["explanation"].strip() == g["analytical_sharh"].strip():
                    g.pop("analytical_sharh", None)

            pid, spans_pids, v_mode, link_method, s_start, s_end = resolve_item_to_passages(
                g, passages_by_part.get(pt, []), parts_by_id[pt], is_verbatim_item=True, allow_elision=False
            )
            if v_mode == "failed" or not pid:
                p0_errors.append(f"[{sc}] Gem #{idx_g+1} in part {pt} failed strict verbatim verification: {g.get('verbatim_rule', '')[:80]!r}")
                continue
            g["pid"] = pid
            g["spans_pids"] = spans_pids
            g["verbatim_match_status"] = v_mode
            g["verbatim_mode"] = v_mode
            g["verbatim_verified"] = v_mode in ("exact", "hemistich")
            g["passage_link_status"] = link_method
            g["link_method"] = link_method
            g["span_start"] = s_start
            g["span_end"] = s_end
            nw, _ = normalize_words_only(g.get("verbatim_rule", ""))
            if nw:
                gem_norm_set.add(nw)
            gems.append(g)

        # Verify stories / applied_cases
        cases = []
        for idx_c, c in enumerate(deep_b.get("stories", [])):
            c = dict(c)
            pt = int(c.get("part", -1))
            if pt not in parts_by_id:
                p0_errors.append(f"[{sc}] Story/Case #{idx_c+1} references invalid part {pt}")
                continue
            if round_num >= 4:
                if "Context" in c:
                    p0_errors.append(f"[{sc}] P0_STORY_SCHEMA_DRIFT: Story #{idx_c+1} uses capitalized 'Context' key")
                hy_story = c.get("hijri_year")
                if hy_story is not None and not isinstance(hy_story, int):
                    p0_errors.append(f"[{sc}] P0_STORY_INVALID_YEAR_TYPE: Story #{idx_c+1} has non-int hijri_year={hy_story!r}")
                norm_pt_txt, _ = normalize_words_only(parts_by_id[pt], strip_ed_noise=True)
                for st_pl in c.get("places", []) or []:
                    st_pl_str = st_pl if isinstance(st_pl, str) else (st_pl.get("name_in_text") or st_pl.get("normalized_name") or "")
                    head_pl = re.split(r"[\(\[/]", st_pl_str)[0].strip()
                    norm_st_pl, _ = normalize_words_only(head_pl, strip_ed_noise=True)
                    norm_st_pl_bare = re.sub(r"\b(?:المنوره|المكرمه|المشرفه|الشريف)\b", "", norm_st_pl).strip()
                    if norm_st_pl == "صفه المسجد النبوي":
                        norm_st_pl_bare = "الصفه"
                    elif norm_st_pl == "المدينه البيضاء":
                        norm_st_pl_bare = "البيضاء"
                    if norm_st_pl and norm_st_pl not in norm_pt_txt and (not norm_st_pl_bare or norm_st_pl_bare not in norm_pt_txt):
                        p0_errors.append(f"[{sc}] P0_STORY_UNGROUNDED_PLACE: Story #{idx_c+1} place {st_pl_str!r} not in part {pt}")
                st_text_fields = f"{c.get('title', '')} | {c.get('summary', '')} | {c.get('context', '')} | {c.get('Context', '')}"
                for m_sq in re.finditer(r"«([^»]{6,140})»", st_text_fields):
                    sq_in = m_sq.group(1).strip()
                    v_sq, _, _ = verify_and_locate_span_in_part(sq_in, parts_by_id[pt], allow_elision=True)
                    if v_sq == "failed":
                        p0_errors.append(
                            f"[{sc}] P0_STORY_UNGROUNDED_QUOTE: Story #{idx_c+1} quotes «{sq_in}» which is not in part {pt}"
                        )

            pid, spans_pids, v_mode, link_method, s_start, s_end = resolve_item_to_passages(
                c, passages_by_part.get(pt, []), parts_by_id[pt], is_verbatim_item=False
            )
            if v_mode == "failed" or not pid:
                p0_errors.append(f"[{sc}] Story/Case #{idx_c+1} in part {pt} failed anchor verification: {c.get('anchor_start', '')!r}")
                continue
            c["pid"] = pid
            c["spans_pids"] = spans_pids
            c["anchor_verified"] = True
            c["passage_link_status"] = link_method
            c["link_method"] = link_method
            c["span_start"] = s_start
            c["span_end"] = s_end
            cases.append(c)

        # Verify quotes strictly (no auto-heal, no arbitrary len > 2 exception!)
        quotes = []
        seen_quote_norms = set()
        for idx_q, qt in enumerate(deep_b.get("quotes", [])):
            qt = dict(qt)
            pt = int(qt.get("part", -1))
            if pt not in parts_by_id:
                p0_errors.append(f"[{sc}] Quote #{idx_q+1} references invalid part {pt}")
                continue
            if round_num >= 4:
                q_spk = (qt.get("speaker") or "").strip()
                q_txt_raw = (qt.get("quote") or "").strip()
                q_txt_notash = TASHKEEL_RE.sub("", q_txt_raw).strip()
                if not q_spk:
                    p0_errors.append(f"[{sc}] P0_QUOTE_MISSING_SPEAKER: Quote #{idx_q+1} in part {pt} has empty speaker")
                if "وقال له آخر" in q_txt_notash or "فقال آخر" in q_txt_notash:
                    p0_errors.append(f"[{sc}] P0_QUOTE_MULTI_SPEAKER: Quote #{idx_q+1} merges two speakers: {q_txt_raw[:70]!r}")
                if q_txt_notash.startswith("كل شيء ما أنت") or q_txt_notash.startswith("فباعها بثمن") or q_txt_notash.startswith("فلما بلغت الخوارج"):
                    p0_errors.append(f"[{sc}] P0_QUOTE_BOUNDARY_DEFECT: Quote #{idx_q+1} includes narrator/broken prefix: {q_txt_raw[:70]!r}")

            pid, spans_pids, v_mode, link_method, s_start, s_end = resolve_item_to_passages(
                qt, passages_by_part.get(pt, []), parts_by_id[pt], is_verbatim_item=True, allow_elision=True
            )
            if v_mode == "failed" or not pid:
                p0_errors.append(f"[{sc}] Quote #{idx_q+1} in part {pt} failed strict verbatim verification: {qt.get('quote', '')[:80]!r}")
                continue
            q_norm, _ = normalize_words_only(qt.get("quote", ""))
            if not q_norm or q_norm in seen_quote_norms:
                p1_warnings.append(f"[{sc}] Duplicate quote skipped in part {pt}")
                continue
            is_dup_of_gem = any(q_norm == gn or (len(q_norm) > 25 and q_norm in gn) for gn in gem_norm_set)
            if is_dup_of_gem:
                p1_warnings.append(f"[{sc}] Quote #{idx_q+1} in part {pt} duplicates a gem and was removed")
                continue
            seen_quote_norms.add(q_norm)
            qt["pid"] = pid
            qt["spans_pids"] = spans_pids
            qt["verbatim_match_status"] = v_mode
            qt["verbatim_mode"] = v_mode
            qt["verbatim_verified"] = v_mode in ("exact", "hemistich")
            qt["passage_link_status"] = link_method
            qt["link_method"] = link_method
            qt["span_start"] = s_start
            qt["span_end"] = s_end
            quotes.append(qt)

        exact_align_cnt = sum(1 for p in aligned_passages if p["align_status"] in ("exact", "normalized"))
        exact_gem_cnt = sum(1 for g in gems if g["verbatim_verified"])
        elided_gem_cnt = sum(1 for g in gems if g["verbatim_match_status"] == "elided_exact")
        exact_quote_cnt = sum(1 for q in quotes if q["verbatim_verified"])
        elided_quote_cnt = sum(1 for q in quotes if q["verbatim_match_status"] == "elided_exact")
        lead_isnad_cnt = sum(1 for p in aligned_passages if p["isnad_prefix"])
        interior_isnad_cnt = sum(len(p.get("interior_isnads", [])) for p in aligned_passages)
        max_embed_len = max((p["embed_matn_char_len"] for p in aligned_passages), default=0)

        total_passages_all += len(aligned_passages)
        total_gems_all += len(gems)
        total_quotes_all += len(quotes)

        orig_toc = [
            {
                "part": p["i"],
                "heading": p["t"],
                "effective_heading": p.get("effective_heading", p["t"]),
                "chars": len(p["text"]),
                "fn_count": len(p.get("fn", [])),
                "src_parts": p.get("src_parts", []),
            }
            for p in parts_list
        ]

        sc_meta = get_science_meta(sc)
        books_out.append({
            "round": round_num,
            "science": sc,
            "science_ar": sc_meta["science_ar"],
            "lens_ar": sc_meta["lens_ar"],
            "gem_label": sc_meta["gem_label"],
            "case_label": sc_meta["case_label"],
            "book_id": raw_b["book_id"],
            "title": raw_b["meta"]["title"],
            "author": f"{raw_b['meta']['author']} (ت {raw_b['meta'].get('death', '؟')} هـ)",
            "scope": raw_b.get("scope", {}),
            "orig_parts_count": len(parts_list),
            "total_chars": raw_b.get("scope", {}).get("chars_selected", sum(len(p["text"]) for p in parts_list)),
            "orig_toc": orig_toc,
            "book_footnotes": raw_b.get("book_footnotes", []),
            "unlinked_part_footnotes": unlinked_fns,
            "deep_toc_passages": aligned_passages,
            "science_gems": gems,
            "stories": cases,
            "quotes": quotes,
            "quality_gate": {
                "gate_version": "v4.3_universal_strict_grounded",
                "align_exact_or_norm_pct": round(100.0 * exact_align_cnt / max(1, len(aligned_passages)), 1),
                "gems_exact_verbatim_pct": round(100.0 * exact_gem_cnt / max(1, len(gems)), 1),
                "gems_elided_exact_count": elided_gem_cnt,
                "quotes_verbatim_pct": round(100.0 * exact_quote_cnt / max(1, len(quotes)), 1),
                "quotes_elided_exact_count": elided_quote_cnt,
                "validated_isnad_count": lead_isnad_cnt + interior_isnad_cnt,
                "lead_isnad_count": lead_isnad_cnt,
                "interior_isnad_count": interior_isnad_cnt,
                "max_embed_matn_chars": max_embed_len,
                "unlinked_footnotes_count": len(unlinked_fns),
            },
        })

    gate_report = {
        "round": round_num,
        "gate_version": "v4.3_universal_strict_grounded",
        "passed": len(p0_errors) == 0,
        "p0_error_count": len(p0_errors),
        "p1_warning_count": len(p1_warnings),
        "p0_errors": p0_errors,
        "p1_warnings": p1_warnings,
        "total_passages": total_passages_all,
        "total_gems": total_gems_all,
        "total_quotes": total_quotes_all,
    }
    return books_out, gate_report


def main():
    global BASE
    args = sys.argv[1:]
    work_dir = None
    pos_args = []
    i = 0
    while i < len(args):
        if args[i] == "--work-dir" and i + 1 < len(args):
            work_dir = Path(args[i + 1]).resolve()
            i += 2
        else:
            pos_args.append(args[i])
            i += 1
    if work_dir is not None:
        BASE = work_dir
    round_num = int(pos_args[0]) if pos_args else 3
    books_out, gate_report = audit_and_merge_round(round_num=round_num)
    report_path = BASE / "gate_report.json"
    round_report_path = BASE / f"gate_report_r{round_num}.json"
    report_json = json.dumps(gate_report, ensure_ascii=False, indent=2)
    report_path.write_text(report_json, encoding="utf-8")
    round_report_path.write_text(report_json, encoding="utf-8")

    for b in books_out:
        qg = b["quality_gate"]
        print(
            f"[R{round_num} {b['science']:13s}] {b['title'][:25]:25s} | parts={b['orig_parts_count']:2d} -> passages={len(b['deep_toc_passages']):2d} "
            f"(align={qg['align_exact_or_norm_pct']:5.1f}%) | isnads={qg['validated_isnad_count']:2d} (lead={qg['lead_isnad_count']}, int={qg['interior_isnad_count']}) "
            f"| gems={qg['gems_exact_verbatim_pct']:5.1f}% ({len(b['science_gems']):2d}) | cases={len(b['stories']):2d} | quotes={qg['quotes_verbatim_pct']:5.1f}% ({len(b['quotes']):2d}) "
            f"| fns_unlinked={qg['unlinked_footnotes_count']} | max_emb={qg['max_embed_matn_chars']:4d}"
        )

    if not gate_report["passed"]:
        print(f"\nGATE v4.3 FAILED with {gate_report['p0_error_count']} P0 errors! See {round_report_path}:")
        for err in gate_report["p0_errors"]:
            print("  [P0]", err)
        sys.exit(1)

    out_path = BASE / f"round{round_num}_9_books_deep.json"
    out_path.write_text(json.dumps(books_out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"\nSUCCESS: All {len(books_out)} Round {round_num} books passed Strict Quality Gate v4.3 (Grounded & Verified)! "
        f"(passages={gate_report['total_passages']}, gems={gate_report['total_gems']}, quotes={gate_report['total_quotes']})"
    )


if __name__ == "__main__":
    main()

