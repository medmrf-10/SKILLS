#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sanitize_preamble.py — تطهير ملفات التفريغ (.txt) من ديباجة النموذج اللغوي وترويسات البيانات الوصفية.

يزيل فقط ديباجات النموذج اللغوي الإنجليزية أو العربية ("Here is the transcription...", "إليك التفريغ...")
وترويسات البيانات الوصفية غير المنطوقة ("الشيخ: ...", "السلسلة: ...") التي تسبق بداية كلام الشيخ
("بسم الله" / "الحمد لله" / "إن الحمد لله" / "السلام عليكم")، مع الحفاظ 100% على خطبة الحاجة وكلام الشيخ.
"""
import argparse
import glob
import json
import os
import re
import shutil
import sys

AR_RE = re.compile(r'[\u0600-\u06FF]')
LATIN_RE = re.compile(r'[A-Za-z]{4,}')
METADATA_LINE_RE = re.compile(r'^\s*(?:الشيخ|السلسلة|الفيديو|الدرس|العنوان|المصدر|القناة|تاريخ)\s*[:：]')
LLM_PREAMBLE_LINE_RE = re.compile(
    r'^\s*(?:'
    r'(?:here\s+is|below\s+is|i\s+have\s+launched|viewing|the\s+user\s+wants)[^\n]*'
    r'|(?:إليك|اليك|هذا\s+هو|فيما\s+يلي)\s+(?:التفريغ|النص)(?:\s+النصي|\s+الكامل|\s+الحرفي)?[^\n]*'
    r'|اقرأ\s+الملف\s+الصوتي\s+@[^\n]*'
    r'|(?:أخرج|إخراج)\s+النص(?:\s+العربي)?\s+فقط\s+بلا\s+أي\s+تعليق[^\n]*'
    r')\s*$',
    re.IGNORECASE,
)
OPENING_CUE_RE = re.compile(
    r'(بسم\s+الله|الحمد\s+لله|إن\s+الحمد\s+لله|نحمده|أشهد\s+أن|أما\s+بعد|'
    r'السلام\s+عليكم|اللهم\s+صل|وصلى\s+الله|سبحانك\s+لا\s+علم|رب\s+اشرح)'
)


def strip_preamble_and_header(text):
    """إزالة ديباجة النموذج اللغوي والترويسات الوصفية غير المنطوقة قبل بداية كلام الشيخ."""
    if not text or not text.strip():
        return '', []

    reasons = []
    lines = text.splitlines()
    idx = 0

    while idx < min(len(lines), 15):
        s = lines[idx].strip()
        if not s or re.match(r'^[-=_*#]{3,}$', s):
            idx += 1
            continue
        if METADATA_LINE_RE.match(s):
            if 'METADATA_HEADER' not in reasons:
                reasons.append('METADATA_HEADER')
            idx += 1
            continue
        ar_count = len(AR_RE.findall(s))
        lat_count = len(re.findall(r'[A-Za-z]', s))
        if LLM_PREAMBLE_LINE_RE.match(s) or lat_count > ar_count or (LATIN_RE.search(s) and ar_count < 10):
            if 'LATIN_PREAMBLE' not in reasons:
                reasons.append('LATIN_PREAMBLE')
            idx += 1
            continue
        break

    cleaned = '\n'.join(lines[idx:]).lstrip()
    m_cue = OPENING_CUE_RE.search(cleaned[:400])
    if m_cue and m_cue.start() > 0:
        prefix = cleaned[:m_cue.start()]
        if LATIN_RE.search(prefix) or LLM_PREAMBLE_LINE_RE.search(prefix.strip()):
            cleaned = cleaned[m_cue.start():].lstrip()
            if 'LATIN_PREAMBLE' not in reasons:
                reasons.append('LATIN_PREAMBLE')
    elif LATIN_RE.search(cleaned[:250]):
        m_ar = AR_RE.search(cleaned)
        if m_ar and m_ar.start() > 0 and LATIN_RE.search(cleaned[:m_ar.start()]):
            cleaned = cleaned[m_ar.start():].lstrip()
            if 'LATIN_PREAMBLE' not in reasons:
                reasons.append('LATIN_PREAMBLE')

    return (cleaned + '\n') if cleaned else '', reasons


def process_dir(series_dir, dry_run=False):
    txts = sorted(f for f in glob.glob(os.path.join(series_dir, '*.txt')) if not os.path.basename(f).startswith('_'))
    backup_dir = os.path.join(series_dir, '_raw_preamble_backup')
    modified = 0
    for path in txts:
        raw = open(path, encoding='utf-8', errors='replace').read()
        cleaned, reasons = strip_preamble_and_header(raw)
        if reasons and cleaned and cleaned != raw:
            modified += 1
            fname = os.path.basename(path)
            print('[تطهير] %s | الأسباب=%s | حُذف=%d حرفًا' % (fname, ','.join(reasons), len(raw) - len(cleaned)))
            if not dry_run:
                os.makedirs(backup_dir, exist_ok=True)
                bpath = os.path.join(backup_dir, fname)
                if not os.path.exists(bpath):
                    shutil.copy2(path, bpath)
                with open(path, 'w', encoding='utf-8') as f:
                    f.write(cleaned)
                mp = path[:-4] + '.meta.json'
                if os.path.exists(mp):
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
    ap = argparse.ArgumentParser(description='تطهير ملفات التفريغ من ديباجة النموذج والترويسات الوصفية')
    ap.add_argument('dirs', nargs='+', help='مجلد (أو مجلدات) السلسلة')
    ap.add_argument('--dry-run', action='store_true', help='عرض ما سيُحذف دون تعديل الملفات')
    args = ap.parse_args()
    for d in args.dirs:
        if os.path.isdir(d):
            process_dir(d, dry_run=args.dry_run)
        else:
            print('تحذير: المسار ليس مجلدًا: %s' % d, file=sys.stderr)


if __name__ == '__main__':
    main()
