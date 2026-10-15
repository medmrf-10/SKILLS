#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v1_to_cache.py — اشتقاق كاش كلمات المراسي من محاذاة v1 جاهزة (بلا أي ASR).

الغاية
  الدروس التي لها محاذاة سابقة (align.force.json / align.json) تحمل كلماتٍ بتوقيتاتها.
  فبدل إعادة تسميع ثقيل (RTF≈1.2 ⇒ ~33 دقيقة للدرس)، تُشتقّ منها المراسي في ثوانٍ.
  التوقيتات الموروثة تحمل انزياح v1 المتراكم، وv3 يصحّحه بـ`--calib-seq` (معايرة CTC
  تتابعية داخل النوافذ) — فالنتيجة النهائية أزمنة CTC لا أزمنة v1.

المدخل
  ملف v1: إمّا قائمة [{"w":كلمة,"s":بداية,"e":نهاية,...}, ...]
           أو قاموس فيه "x" = [[كلمة, بداية, نهاية, علامة, انزياح], ...]
المخرج
  كاش بصيغة خطّ v3: [{"t":الكلمة, "n":صيغة مخففة, "s":بداية, "e":نهاية, "seg":رقم المقطع}, ...]

الاستعمال
  python v1_to_cache.py --v1 <align.force.json> --cache <out.json> [--seg-secs 300] [--min-p 0.0]
"""
import argparse, hashlib, json, os, re, sys, unicodedata

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:                       # نفس مخفّف التطبيع المستخدم في المولّد المحلي
    from shadow_norm import light_norm  # type: ignore
except Exception:
    _TASHKEEL = re.compile(r'[\u0617-\u061A\u064B-\u0652\u0670\u0640]')
    def light_norm(w):
        return _TASHKEEL.sub('', unicodedata.normalize('NFKC', w or '')).strip()


def load_v1(path):
    """يُرجع [(كلمة, بداية, نهاية)] من أي من صيغتَي v1."""
    d = json.load(open(path, encoding='utf-8'))
    rows = d.get('x') if isinstance(d, dict) else d
    if not isinstance(rows, list):
        raise SystemExit('صيغة v1 غير معروفة: %s' % path)
    out = []
    for e in rows:
        if isinstance(e, dict):                      # {"w","s","e","p"}
            w, s, t = e.get('w'), e.get('s'), e.get('e')
            if w and isinstance(s, (int, float)) and isinstance(t, (int, float)):
                out.append((str(w), float(s), float(t)))
        elif isinstance(e, (list, tuple)) and len(e) >= 3:   # [كلمة, بداية, نهاية, ...]
            w, s, t = e[0], e[1], e[2]
            if w and isinstance(s, (int, float)) and isinstance(t, (int, float)):
                out.append((str(w), float(s), float(t)))
    return out


def to_cache(rows, seg_secs=300.0):
    words, last_seg, seg0 = [], None, 0.0
    for w, s, t in rows:
        if t < s:                                    # توقيت مقلوب ⇒ يُستبعد
            continue
        seg = int(s // seg_secs)
        if last_seg is not None and seg != last_seg:
            seg0 = s                                    # بداية المقطع الجديد
        words.append({'t': w, 'n': light_norm(w), 's': round(s, 3), 'e': round(t, 3), 'seg': seg})
        last_seg = seg
    return words


def main():
    ap = argparse.ArgumentParser(description='اشتقاق كاش المراسي من محاذاة v1 (بلا ASR)')
    ap.add_argument('--v1', required=True, help='ملف محاذاة v1 (align.force.json / align.json)')
    ap.add_argument('--cache', help='مسار الكاش الناتج (افتراضي: <v1>.asr.json)')
    ap.add_argument('--seg-secs', type=float, default=300.0, help='طول المقطع بالثواني (افتراضي 300)')
    ap.add_argument('--print-key', action='store_true', help='اطبع مفتاح الكاش باسم sha1 ثم اخرج')
    a = ap.parse_args()

    if a.print_key:
        h = hashlib.sha1(('v1|%s' % os.path.abspath(a.v1)).encode()).hexdigest()
        print('%s.v1.json' % h)
        return
    if not os.path.exists(a.v1):
        raise SystemExit('ملف v1 غير موجود: %s' % a.v1)

    rows = load_v1(a.v1)
    if not rows:
        raise SystemExit('لم تُقرأ أي كلمة بتوقيت صالح من %s' % a.v1)
    words = to_cache(rows, a.seg_secs)
    out = a.cache or (os.path.splitext(a.v1)[0] + '.asr.json')
    with open(out, 'w', encoding='utf-8') as fh:
        json.dump(words, fh, ensure_ascii=False)
    span = words[-1]['e'] - words[0]['s']
    print('[v1→كاش] %s ⇒ %s | كلمات=%d | مدى %.0fث | مقاطع=%d' % (
        os.path.basename(a.v1), os.path.basename(out), len(words), span,
        len({w['seg'] for w in words})))


if __name__ == '__main__':
    main()
