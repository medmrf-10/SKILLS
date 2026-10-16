#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""new_series.py — تهيئة سلسلة جديدة وبناء _meta.json مع حفظ المدد وكشف الترقيم المعكوس.

المزايا:
  • يجلب بيانات قائمة يوتيوب عبر `yt-dlp --flat-playlist -J` (أو يقرأ ملف JSON جاهز).
  • يحفظ مدة كل درس بالثواني (`dur_s`) ورقم الدرس الصريح في العنوان (`title_ep`) داخل `_meta.json`
    حتى تتمكن بوابة الجودة `check_transcripts.py` من حساب معدل الكلمات في الدقيقة (WPM) آليًا.
  • يكتشف تلقائيًا (`--order auto`) القوائم المعكوسة على يوتيوب (مثل قائمة «مقدمات السنوسي» حيث
    الموضع 1 في القائمة هو «الدرس 09 والأخير» والموضع 9 هو «الدرس 01») ويرتبها تصاعديًا حسب رقم الدرس.
  • يدعم `--fix-existing` لإعادة ترقيم ملفات `.txt` و`.mp3` الموجودة في المجلد إذا كانت مرقمة بترتيب معكوس.

الاستعمال:
  python3 new_series.py --slug bardouni-husaymi --row 1005 \
      --sheikh "محمد البردوني الحسيمي" --series "مقدمات السنوسي" \
      --playlist "PLUAcOYpvESsfJk6driIvfxJHDWq-NRtHz" [--work-root /root/workspace] [--order auto|title|playlist]
"""
import argparse
import glob
import json
import os
import re
import subprocess
import sys

TITLE_EP_RE = re.compile(r'(?:الدرس|درس|الحلقة|حلقة|المجلس|مجلس)\s*[:\-–—]?\s*0*([0-9]{1,3})\b')


def extract_title_ep(title):
    if not title:
        return None
    m = TITLE_EP_RE.search(title)
    if m:
        return int(m.group(1))
    return None


def fetch_playlist(playlist_arg):
    if os.path.exists(playlist_arg):
        return json.load(open(playlist_arg, encoding='utf-8'))
    url = playlist_arg
    if not url.startswith('http'):
        url = 'https://www.youtube.com/playlist?list=' + playlist_arg
    cmd = ['yt-dlp', '--flat-playlist', '-J', url]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return json.loads(res.stdout)


def rename_existing_files(series_dir, vid_to_new_n):
    """إعادة تسمية ملفات NNN_<vid>.(txt|mp3|wav|m4a|meta.json) بأمان عبر مرحلة وسيطة لمنع التصادم."""
    staged = []
    for path in sorted(glob.glob(os.path.join(series_dir, '[0-9][0-9][0-9]_*.*'))):
        base = os.path.basename(path)
        m = re.match(r'^(\d{3})_([A-Za-z0-9_-]{6,20})\.([a-z0-9.]+)$', base)
        if not m:
            continue
        old_n, vid, ext = int(m.group(1)), m.group(2), m.group(3)
        new_n = vid_to_new_n.get(vid)
        if new_n is not None and new_n != old_n:
            tmp_path = os.path.join(series_dir, '__tmp_%03d_%s.%s' % (new_n, vid, ext))
            final_path = os.path.join(series_dir, '%03d_%s.%s' % (new_n, vid, ext))
            os.rename(path, tmp_path)
            staged.append((tmp_path, final_path, base, os.path.basename(final_path), new_n, ext))
    for tmp_path, final_path, old_b, new_b, new_n, ext in staged:
        os.rename(tmp_path, final_path)
        if ext == 'meta.json':
            try:
                md = json.load(open(final_path, encoding='utf-8'))
                md['n'] = new_n
                json.dump(md, open(final_path, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
            except Exception:
                pass
        print('[إعادة ترقيم] %s ⇒ %s' % (old_b, new_b))


def main():
    ap = argparse.ArgumentParser(description='تهيئة سلسلة شيخ جديدة وبناء _meta.json')
    ap.add_argument('--slug', required=True, help='معرّف الشيخ اللاتيني (مثل bardouni-husaymi)')
    ap.add_argument('--row', required=True, type=int, help='رقم السلسلة (مثل 1005)')
    ap.add_argument('--sheikh', required=True, help='اسم الشيخ بالعربية')
    ap.add_argument('--series', required=True, help='اسم السلسلة بالعربية')
    ap.add_argument('--category', default='تزكية وأخلاق وعقيدة', help='التصنيف')
    ap.add_argument('--playlist', required=True, help='رابط أو معرّف قائمة يوتيوب أو مسار ملف JSON')
    ap.add_argument('--work-root', default=os.environ.get('SERIES_WORKSPACE', '/root/workspace'),
                    help='المجلد الجذري الذي يحوي ytb/')
    ap.add_argument('--series-dir', default='', help='مسار مجلد السلسلة مباشرة (اختياري، يتجاوز --work-root)')
    ap.add_argument('--order', default='auto', choices=['auto', 'title', 'playlist'],
                    help='ترتيب الدروس: auto يرتب حسب رقم الدرس الصريح في العنوان إن وُجد دون تضارب')
    ap.add_argument('--fix-existing', action='store_true',
                    help='إعادة ترقيم ملفات المجلد الحالية لتطابق الترتيب المختار')
    args = ap.parse_args()

    series_dir = args.series_dir or os.path.join(args.work_root, 'ytb', args.slug, str(args.row))
    os.makedirs(series_dir, exist_ok=True)

    data = fetch_playlist(args.playlist)
    entries = [e for e in (data.get('entries') or []) if e and e.get('id')]
    if not entries:
        raise SystemExit('لم يُعثر على دروس في القائمة: %s' % args.playlist)

    raw_videos = []
    for idx, e in enumerate(entries, 1):
        vid = e.get('id')
        title = e.get('title') or ''
        dur = e.get('duration') or e.get('dur_s') or 0
        title_ep = extract_title_ep(title)
        raw_videos.append({
            'playlist_pos': idx,
            'vid': vid,
            'title': title,
            'dur_s': float(dur) if dur else 0.0,
            'title_ep': title_ep,
        })

    # تحديد الترتيب
    use_title_order = False
    eps = [v['title_ep'] for v in raw_videos if v['title_ep'] is not None]
    if args.order == 'title' and len(eps) == len(raw_videos):
        use_title_order = True
    elif args.order == 'auto' and len(eps) == len(raw_videos) and len(set(eps)) == len(raw_videos):
        if eps != [v['playlist_pos'] for v in raw_videos]:
            use_title_order = True
            print('[ترتيب تلقائي] كُشف ترقيم صريح في العناوين يخالف ترتيب القائمة (%s) ⇒ سيتم الترتيب تصاعديًا حسب رقم الدرس.' % (
                ','.join(str(x) for x in eps[:5]) + ('...' if len(eps) > 5 else '')
            ))

    if use_title_order:
        raw_videos.sort(key=lambda v: (v['title_ep'], v['playlist_pos']))

    videos = []
    vid_to_new_n = {}
    for n, v in enumerate(raw_videos, 1):
        vid_to_new_n[v['vid']] = n
        videos.append({
            'n': n,
            'vid': v['vid'],
            'title': v['title'],
            'dur_s': v['dur_s'],
            'title_ep': v['title_ep'],
            'playlist_pos': v['playlist_pos'],
        })

    if args.fix_existing:
        rename_existing_files(series_dir, vid_to_new_n)

    playlist_id = data.get('id') or args.playlist
    meta = {
        'row': args.row,
        'sheikh': args.sheikh,
        'slug': args.slug,
        'series': args.series,
        'category': args.category,
        'playlist_id': playlist_id,
        'count': len(videos),
        'order_mode': 'title_ep' if use_title_order else 'playlist_pos',
        'videos': videos,
    }
    meta_path = os.path.join(series_dir, '_meta.json')
    with open(meta_path, 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    total_dur_h = sum(v['dur_s'] for v in videos) / 3600.0
    print('[تم] كُتب %s (%d درسًا · إجمالي %.2f ساعة · وضع الترتيب=%s)' % (
        meta_path, len(videos), total_dur_h, meta['order_mode']))


if __name__ == '__main__':
    main()
