# -*- coding: utf-8 -*-
"""shadow_norm.py — المجرى النصي الظلّي المطبّع (ترقية v2، المرحلة ١).

تنفيذ مواصفة المالك في references/09:
  ١) تحويل الألف الخنجرية U+0670 إلى ألف إملائية **قبل** حذف الحركات
     (هذا هو الفرق الجوهري عن v1 الذي كان يحذف U+0670 ⇒ «السماوات» تصير «السموت»).
  ٢) إزالة رموز الوقف والتجويد العثمانية (U+06E1، U+0655، U+06D6–U+06ED، التطويل).
  ٣) الواو والياء الصغيرتان (U+06E5/U+06E6) → و/ي صريحتان.
  ٤) حذف الحركات القصيرة والمدّة.
  ٥) توحيد الألف والهمزات والتاء المربوطة والياء المتطرفة.
  ٦) تفقيط الأرقام (Number Textualization) — في المجرى الظلّي فقط.
  ٧) إزالة الترقيم.

كل دالة تُعيد النصّ المطبّع؛ ولا تُستعمل هذه المخرجات في النشر (النصّ المنشور يبقى الأصل).
"""
import re
import unicodedata

DAGGER_ALEF = '\u0670'

# حركات قصيرة + مدة/ألف فوقية معيارية
TASHKEEL = re.compile(r'[\u064B-\u0652\u0653\u0656\u0657\u0658\u0659\u065A\u065B\u065C\u065D\u065E\u065F]')
# رموز عثمانية: سكون عثماني/همزات صغيرة/أرقام صغيرة/علامات وقف/تطويل
OTTOMAN = re.compile(r'[\u06D6-\u06ED\u0640]')
PUNCT = re.compile(r'([^\w\s]|_)', re.UNICODE)

SMALL_WAW = '\u06E5'
SMALL_YA = '\u06E6'

UNIFY = (
    ('\u0622', '\u0627'),  # آ
    ('\u0623', '\u0627'),  # أ
    ('\u0625', '\u0627'),  # إ
    ('\u0671', '\u0627'),  # ٱ ألف الوصل
    ('\u0649', '\u064A'),  # ى
    ('\u0629', '\u0647'),  # ة
    ('\u0624', '\u0648'),  # ؤ
    ('\u0626', '\u064A'),  # ئ
)

# ── تفقيط الأرقام (عربي فصيح مبسّط يكفي للمطابقة الصوتية) ─────────────────────
_UNITS = ['', 'واحد', 'اثنان', 'ثلاثة', 'أربعة', 'خمسة', 'ستة', 'سبعة', 'ثمانية', 'تسعة']
_TEENS = ['عشرة', 'أحد عشر', 'اثنا عشر', 'ثلاثة عشر', 'أربعة عشر', 'خمسة عشر', 'ستة عشر',
          'سبعة عشر', 'ثمانية عشر', 'تسعة عشر']
_TENS = ['', 'عشرة', 'عشرون', 'ثلاثون', 'أربعون', 'خمسون', 'ستون', 'سبعون', 'ثمانون', 'تسعون']
_HUNDREDS = ['', 'مئة', 'مئتان', 'ثلاثمئة', 'أربعمئة', 'خمسمئة', 'ستمئة', 'سبعمئة', 'ثمانمئة', 'تسعمئة']


def _below_1000(n):
    out = []
    h, r = divmod(n, 100)
    if h:
        out.append(_HUNDREDS[h])
    if 10 <= r < 20:
        out.append(_TEENS[r - 10])
    else:
        t, u = divmod(r, 10)
        if u:
            out.append(_UNITS[u])
        if t:
            out.append(_TENS[t])
    return ' و'.join(out)


def number_to_words(n):
    if n == 0:
        return 'صفر'
    parts = []
    thousands, rest = divmod(n, 1000)
    if thousands == 1:
        parts.append('ألف')
    elif thousands == 2:
        parts.append('ألفان')
    elif thousands:
        parts.append(_below_1000(thousands) + (' آلاف' if thousands <= 10 else ' ألفاً'))
    if rest:
        parts.append(_below_1000(rest))
    return ' و'.join(parts)


_AR_DIGITS = str.maketrans('٠١٢٣٤٥٦٧٨٩', '0123456789')


def texturize_numbers(word):
    """يُعيد كلمات منطوقة للرمز الرقمي الخالص (وإلّا الكلمة كما هي)."""
    w = word.translate(_AR_DIGITS)
    if not w.isdigit():
        return word
    return number_to_words(int(w))


# ── قاموس العثماني ← الإملائي (يُحمّل من ملف إن وُجد، وإلّا تُطبَّق القواعد) ─────
_DICT = None


DEFAULT_DICT = __file__.replace('shadow_norm.py', 'ottoman_dict.json')


def load_dict(path=None):
    """قاموس أزواج (عثماني ← إملائي) بصيغة JSON {عثماني: إملائي} — اختياري."""
    global _DICT
    if _DICT is None:
        _DICT = {}
        path = path or DEFAULT_DICT
        if path:
            try:
                import json
                with open(path, encoding='utf-8') as f:
                    raw = json.load(f)
                _DICT = {str(k): str(v) for k, v in raw.items()}
            except Exception:
                _DICT = {}
    return _DICT


def shadow(word, use_dict=True):
    w = unicodedata.normalize('NFC', str(word))
    w = w.replace(DAGGER_ALEF, '\u0627')      # ١) الألف الخنجرية → ألف صريحة (قبل حذف الحركات)
    w = w.replace(SMALL_WAW, '\u0648').replace(SMALL_YA, '\u064A')
    w = OTTOMAN.sub('', w)                     # ٢) علامات الوقف/التجويد والتطويل
    w = TASHKEEL.sub('', w)                    # ٤) الحركات
    for a, b in UNIFY:                         # ٥) توحيد الأشكال
        w = w.replace(a, b)
    w = texturize_numbers(w)                   # ٦) تفقيط
    w = PUNCT.sub('', w)                       # ٧) الترقيم
    w = w.strip()
    if use_dict and w:
        w = load_dict().get(w, w)
    return w


def shadow_words(words, use_dict=True):
    return [w for w in (shadow(x, use_dict) for x in words) if w]


# ── تطبيع v1 (للمقارنة «قبل») — مطابق لـ align_mlx.norm ────────────────────────
_V1_DIAC = re.compile(r'[\u064B-\u0652\u0670\u0640]')
_V1_PUNCT = re.compile(r'[^\w\s]', re.UNICODE)
_V1_UNIFY = (('أ', 'ا'), ('إ', 'ا'), ('آ', 'ا'), ('ى', 'ي'), ('ة', 'ه'), ('ؤ', 'و'), ('ئ', 'ي'))


def v1_norm(word):
    w = _V1_DIAC.sub('', str(word))
    w = _V1_PUNCT.sub('', w)
    for a, b in _V1_UNIFY:
        w = w.replace(a, b)
    return w.strip()
