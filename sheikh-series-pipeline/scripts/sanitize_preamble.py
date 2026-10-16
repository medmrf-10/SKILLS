#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sanitize_preamble.py — تطهير ملفات التفريغ (.txt) من المقدمات اللاتينية وترويسات البيانات الوصفية.

يعالج نوعين من التلوث في مطلع ملفات التفريغ قبل المحاذاة الصوتية (CTC):
  1. المقدمات اللاتينية/الإنگليزية التي قد يطبعها وكيل agy قبل النص (مثل: "I have launched...", "Viewing...").
  2. ترويسات البيانات الوصفية غير المنطوقة (مثل: "الشيخ: ...", "السلسلة: ...", "الفيديو: ...", "الدرس: ...").

يحفظ نسخة احتياطية من كل ملف معيب داخل `<series_dir>/_raw_preamble_backup/` قبل تعديله.

الاستعمال:
  python3 sanitize_preamble.py <series_dir> [<series_dir> ...] [--dry-run]
"""
import argparse
import glob
import os
import re
import shutil
import sys

AR_RE = re.compile(r'[\u0600-\u06FF]')
LATIN_RE = re.compile(r'[A-Za-z]{4,}')
METADATA_LINE_RE = re.compile(
    r'^\s*(الشيخ|السلسلة|الفيديو|الدرس|العنوان|المصدر|القناة|تاريخ)\s*[:：]',
    re.MULTILINE,
)
OPENING_CUE_RE = re.compile(
    r'(بسم\s+الله|الحمد\s+لله|إن\s+الحمد\s+لله|نحمده|أشهد\s+أن|أما\s+بعد|'
    r'السلام\s+عليكم|اللهم\s+صل|وصلى\s+الله|سبحانك\s+لا\s+علم|رب\s+اشرح)'
)


def strip_preamble_and_header(text):
    """إزالة الترويسات الوصفية والمقدمات غير المنطوقة من مطلع النص.

    تُعيد: (cleaned_text, reasons_list)
    """
    reasons = []
    lines = text.splitlines()
    idx = 0

    # 1. إزالة الأسطر الفارغة أو اللاتينية أو ترويسات البيانات الوصفية في أول 15 سطرًا
    while idx < min(len(lines), 15):
        s = lines[idx].strip()
        if not s:
            idx += 1
            continue
        if METADATA_LINE_RE.match(s):
            if 'METADATA_HEADER' not in reasons:
                reasons.append('METADATA_HEADER')
            idx += 1
            continue
        ar_count = len(AR_RE.findall(s))
        lat_count = len(re.findall(r'[A-Za-z]', s))
        if lat_count > ar_count or (LATIN_RE.search(s) and ar_count < 10):
            if 'LATIN_PREAMBLE' not in reasons:
                reasons.append('LATIN_PREAMBLE')
            idx += 1
            continue
        if re.match(r'^[-=_*#]{3,}$', s):
            idx += 1
            continue
        break

    cleaned = '\n'.join(lines[idx:]).lstrip()

    # 2. إذا بقي في أول 250 حرفًا كلام لاتيني متصل يسبق فاتحة الدرس العربية
    head = cleaned[:300]
    if LATIN_RE.search(head):
        m = OPENING_CUE_RE.search(cleaned[:600])
        if m and m.start() > 0 and LATIN_RE.search(cleaned[:m.start()]):
            cleaned = cleaned[m.start():].lstrip()
            if 'LATIN_PREAMBLE' not in reasons:
                reasons.append('LATIN_PREAMBLE')
        else:
            m_ar = AR_RE.search(cleaned)
            if m_ar and m_ar.start() > 0:
                cleaned = cleaned[m_ar.start():].lstrip()
                if 'LATIN_PREAMBLE' not in reasons:
                    reasons.append('LATIN_PREAMBLE')

    return (cleaned + '\n') if cleaned else '', reasons


def process_dir(series_dir, dry_run=False):
    txts = sorted(
        f for f in glob.glob(os.path.join(series_dir, '*.txt'))
        if not os.path.basename(f).startswith('_')
    )
    backup_dir = os.path.join(series_dir, '_raw_preamble_backup')
    modified = 0
    for path in txts:
        raw = open(path, encoding='utf-8', errors='replace').read()
        cleaned, reasons = strip_preamble_and_header(raw)
        if reasons and cleaned and cleaned != raw:
            modified += 1
            fname = os.path.basename(path)
            removed_chars = len(raw) - len(cleaned)
            print('[تطهير] %s | الأسباب=%s | حُذف=%d حرفًا' % (fname, ','.join(reasons), removed_chars))
            if not dry_run:
                os.makedirs(backup_dir, exist_ok=True)
                bpath = os.path.join(backup_dir, fname)
                if not os.path.exists(bpath):
                    shutil.copy2(path, bpath)
                with open(path, 'w', encoding='utf-8') as f:
                    f.write(cleaned)
                mp = path[:-4] + '.meta.json'
                if os.path.exists(mp):
                    import json
                    try:
                        md = json.load(open(mp, encoding='utf-8'))
                        if 'chars' in md:
                            md['chars'] = len(cleaned)
                            json.dump(md, open(mp, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
                    except Exception:
                        pass
    print('[ملخص التطهير] %s: عُولج %d/%d ملف' % (series_dir, modified, len(txts)))
    return modified


def main():
    ap = argparse.ArgumentParser(description='تطهير ملفات التفريغ من المقدمات اللاتينية والترويسات الوصفية')
    ap.add_argument('dirs', nargs='+', help='مجلد (أو مجلدات) السلسلة')
    ap.add_argument('--dry-run', action='store_true', help='عرض ما سيُحذف دون تعديل الملفات')
    args = ap.parse_args()
    total = 0
    for d in args.dirs:
        if not os.path.isdir(d):
            print('تحذير: المسار ليس مجلدًا: %s' % d, file=sys.stderr)
            continue
        total += process_dir(d, dry_run=args.dry_run)
    sys.exit(0)


if __name__ == '__main__':
    main()
