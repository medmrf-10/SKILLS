#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""transcribe_selected_smallest_first.py — تفريغ السلاسل المختارة من الأصغر إلى الأكبر بأقصى توازي آمن على السيرفر.

يعتمد مهارة sheikh-series-pipeline:
- SERIES_WORKERS = 4 (4 سلاسل بالتوازي لتداخل التنزيل مع التفريغ دون توقف)
- CHUNK_WORKERS = 4 لكل سلسلة (حتى 16 عملية agy متوازية في الذروة)
- حارس ذاكرة تلقائي (MemAvailable >= 1600 MB) يمنع إطلاق سلسلة جديدة إذا اقتربت الذاكرة من السقف.
"""
import concurrent.futures
import glob
import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime

if not os.environ.get('HOME'):
    os.environ['HOME'] = os.path.expanduser('~') if os.path.expanduser('~') != '~' else '/root'

SELECTIONS_JSON = '/root/workspace/cheikh-exports/cheikh-selected-curated-2026-10-17.json'
YTB_ROOT = '/root/workspace/ytb'
ROW_MAP_JSON = '/root/workspace/ytb/_meta/row_map.json'
AGY_TRANSCRIBE = '/root/workspace/SKILLS/sheikh-series-pipeline/scripts/agy_transcribe.py'
STATE_FILE = '/root/workspace/ytb-build/transcribe_selected_state.json'

SERIES_WORKERS = int(os.environ.get('SERIES_WORKERS', '4'))
CHUNK_WORKERS = int(os.environ.get('CHUNK_WORKERS', '4'))
MIN_AVAIL_MB = int(os.environ.get('MIN_AVAIL_MB', '1600'))

SHEIKH_ID_TO_SLUG = {
    'sayed': 'ahmed-alsayed',
    'asimi': 'adham-alasimi',
    'bardoni': 'bardouni-husaymi',
    'jifri': 'habib-ali-aljifri',
    'hafiz': 'habib-omar-ibn-hafiz',
    'gomaa': 'ali-gomaa',
    'bouti': 'said-bouti',
    'shaarawy': 'sharawi',
    'hawwa': 'maath-hawa',
    'sariri': 'mouloud-sariri',
    'omari': 'ali-mahmoud-alomari',
    'hashemi': 'dhaker-alhashimi',
    'kamali': 'said-kamali',
    'samarrai': 'fadhel-samarrai',
    'ayman': 'ayman-abdelrahim',
    'dedew': 'daddo',
    'alihani': 'ali-hani-aqrabawi',
}

STATE_LOCK = threading.Lock()


def log(msg):
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f'[{ts}] {msg}', flush=True)


def get_mem_available_mb():
    try:
        with open('/proc/meminfo', encoding='utf-8') as f:
            for line in f:
                if line.startswith('MemAvailable:'):
                    return int(line.split()[1]) // 1024
    except Exception:
        pass
    return 4096


def wait_for_safe_ram(sid):
    while True:
        avail = get_mem_available_mb()
        if avail >= MIN_AVAIL_MB:
            return avail
        log(f'[حارس الذاكرة] الذاكرة المتاحة ({avail} MB) أقل من الحد الآمن ({MIN_AVAIL_MB} MB) — انتظار 15ث قبل بدء {sid}...')
        time.sleep(15)


def index_existing_ytb():
    """يرصد كل ملفات .txt الصالحة في /root/workspace/ytb بمعرّف يوتيوب."""
    yt_to_path = {}
    retranscribing_vids = set()
    for root, dirs, files in os.walk(YTB_ROOT):
        if os.path.basename(root) == '_truncated_legacy_backup':
            for f in files:
                if f.endswith('.txt') and '_' in f[:-4]:
                    retranscribing_vids.add(f[:-4].split('_', 1)[1])
            continue
        for skip in ('.git', '_variants', '_raw_preamble_backup'):
            if skip in dirs:
                dirs.remove(skip)
        for f in files:
            if not f.endswith('.txt'):
                continue
            p = os.path.join(root, f)
            try:
                if os.path.getsize(p) < 60:
                    continue
                stem = f[:-4]
                parts = stem.split('_', 1)
                if len(parts) == 2 and (len(parts[1]) == 11 or parts[1].startswith('archive__')):
                    yt_to_path[parts[1]] = p
            except OSError:
                pass
    return yt_to_path, retranscribing_vids


def resolve_series_dir(series_obj, yt_to_path, row_map):
    sh_id = series_obj.get('sheikh_id', 'unattributed')
    sh_slug = SHEIKH_ID_TO_SLUG.get(sh_id, sh_id)
    row_key = series_obj['id'].split('__', 1)[-1] if '__' in series_obj['id'] else series_obj['id']
    return os.path.join(YTB_ROOT, sh_slug, row_key)

def ensure_series_meta(series_dir, series_obj):
    os.makedirs(series_dir, exist_ok=True)
    meta_path = os.path.join(series_dir, '_meta.json')
    videos = []
    for idx, l in enumerate(series_obj.get('lessons') or [], 1):
        vid = l.get('yt_id')
        if not vid:
            continue
        n = int(l.get('order_no') or idx)
        videos.append({
            'n': n,
            'vid': vid,
            'title': l.get('title') or l.get('yt_title') or '',
            'dur_s': int(l.get('duration') or 0),
            'url': l.get('yt_url') or '',
        })
    meta = {
        'series_id': series_obj.get('id'),
        'sheikh_id': series_obj.get('sheikh_id'),
        'sheikh': series_obj.get('sheikh_name', ''),
        'series': series_obj.get('title', ''),
        'yt_playlist_id': series_obj.get('yt_playlist_id'),
        'videos': videos,
    }
    with open(meta_path, 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    return videos


def cleanup_transcribed_mp3s(series_dir):
    """يحذف ملفات الصوت المؤقتة للدروس التي اكتمل تفريغها بنجاح لتوفير مساحة القرص."""
    for mp3 in glob.glob(os.path.join(series_dir, '*.mp3')):
        base = os.path.splitext(mp3)[0]
        txt = base + '.txt'
        meta = base + '.meta.json'
        if os.path.exists(txt) and os.path.getsize(txt) >= 60 and os.path.exists(meta):
            try:
                md = json.load(open(meta, encoding='utf-8'))
                if md.get('ok'):
                    os.remove(mp3)
            except Exception:
                pass


def main():
    log(f'بدء محرك تفريغ الاختيارات المتوازي (SERIES_WORKERS={SERIES_WORKERS} × CHUNK_WORKERS={CHUNK_WORKERS})...')
    data = json.load(open(SELECTIONS_JSON, encoding='utf-8'))
    row_map = json.load(open(ROW_MAP_JSON, encoding='utf-8')) if os.path.exists(ROW_MAP_JSON) else {}
    yt_to_path, retranscribing_vids = index_existing_ytb()
    log(f'إجمالي التفريغات الصالحة المرصودة في ytb حالياً: {len(yt_to_path)}')

    min_completion_pct = float(os.environ.get('MIN_COMPLETION_PCT', '70.0'))
    queue = []
    skipped_under_threshold = 0
    for s in data.get('series', []):
        lessons = [l for l in (s.get('lessons') or []) if l.get('yt_id')]
        if not lessons:
            continue
        missing = []
        for idx, l in enumerate(lessons, 1):
            if l.get('duration') is None and l.get('is_child'):
                continue
            vid = l['yt_id']
            n = int(l.get('order_no') or idx)
            if vid not in yt_to_path:
                missing.append((n, vid, int(l.get('duration') or 0)))
        if not missing:
            continue
        total_count = len(lessons)
        elig_done = sum(1 for l in lessons if (l['yt_id'] in yt_to_path or l['yt_id'] in retranscribing_vids))
        done_pct = (elig_done / total_count) * 100.0
        if done_pct < min_completion_pct:
            skipped_under_threshold += 1
            continue
        rem_dur = sum(x[2] for x in missing)
        queue.append({
            'series_obj': s,
            'missing': missing,
            'rem_count': len(missing),
            'total_count': total_count,
            'done_pct': round(done_pct, 1),
            'rem_dur': rem_dur,
        })

    queue.sort(key=lambda x: (x['rem_count'], x['total_count'], x['rem_dur']))
    total_q = len(queue)
    log(
        f'وضع التصفية (>= {min_completion_pct:.1f}% فقط): تم استبعاد {skipped_under_threshold} سلسلة جديدة أو دون 70% | '
        f'المتبقي لإكماله: {total_q} سلسلة فقط ({sum(x["rem_count"] for x in queue)} درساً)'
    )

    active_map = {}
    completed_series = 0

    def write_state():
        with STATE_LOCK:
            state = {
                'updated_at': datetime.now().isoformat(),
                'series_workers': SERIES_WORKERS,
                'chunk_workers': CHUNK_WORKERS,
                'total_series_in_queue': total_q,
                'completed_series_this_run': completed_series,
                'mem_available_mb': get_mem_available_mb(),
                'active_series': list(active_map.values()),
            }
            with open(STATE_FILE, 'w', encoding='utf-8') as sf:
                json.dump(state, sf, ensure_ascii=False, indent=2)

    def process_one_series(idx, item):
        nonlocal completed_series
        s = item['series_obj']
        sid = s['id']
        avail_mb = wait_for_safe_ram(sid)
        with STATE_LOCK:
            s_dir = resolve_series_dir(s, yt_to_path, row_map)
            ensure_series_meta(s_dir, s)
            active_map[sid] = {
                'queue_index': idx,
                'series_id': sid,
                'sheikh': s.get('sheikh_name'),
                'title': s.get('title'),
                'dir': s_dir,
                'remaining_lessons': item['rem_count'],
                'total_lessons': item['total_count'],
                'remaining_hours': round(item['rem_dur'] / 3600.0, 2),
                'started_at': datetime.now().isoformat(),
            }
        write_state()

        only_nums = ','.join(f'{n:03d}' for n, _, _ in item['missing'])
        log(f'=== [{idx}/{total_q}] بدء: {sid} | الشيخ: {s.get("sheikh_name")} | «{s.get("title")}» ({item["rem_count"]}/{item["total_count"]} درس · {item["rem_dur"]/3600:.2f}س · RAM متاح={avail_mb}MB) ===')

        cmd = [
            sys.executable, AGY_TRANSCRIBE, s_dir,
            '--only', only_nums,
            '--workers', str(CHUNK_WORKERS),
            '--chunk-minutes', '12',
            '--max-single-minutes', '15',
        ]
        res = subprocess.run(cmd)
        cleanup_transcribed_mp3s(s_dir)

        with STATE_LOCK:
            active_map.pop(sid, None)
            completed_series += 1
        write_state()
        log(f'--- [{idx}/{total_q}] انتهت القائمة {sid} (exit={res.returncode} · المنجز في هذه الدفعة={completed_series}) ---')
        return sid, res.returncode

    write_state()
    if not queue:
        flag_path = '/root/workspace/ytb-build/TRANSCRIBE_DRAIN_COMPLETE.flag'
        try:
            with open(flag_path, 'w', encoding='utf-8') as ff:
                ff.write(datetime.now().isoformat() + '\n')
        except Exception:
            pass
        log('لا توجد أي سلاسل متبقية فوق 80% — تم إيقاف التفريغ بالكامل.')
        return

    with concurrent.futures.ThreadPoolExecutor(max_workers=SERIES_WORKERS) as pool:
        futs = [pool.submit(process_one_series, idx, item) for idx, item in enumerate(queue, 1)]
        for fut in concurrent.futures.as_completed(futs):
            try:
                fut.result()
            except Exception as e:
                log(f'[خطأ غير متوقع في عامل السلسلة] {e}')

    yt_after = index_existing_ytb()
    still_missing_series = 0
    for item in queue:
        rem_now = [vid for _, vid, _ in item['missing'] if vid not in yt_after]
        if rem_now:
            still_missing_series += 1
    if still_missing_series > 0:
        log(f'تبقّت {still_missing_series} سلسلة تحتاج إعادة محاولة لبعض الدروس — لن يُكتب علم الإغلاق حتى تكتمل 100%.')
        return

    flag_path = '/root/workspace/ytb-build/TRANSCRIBE_DRAIN_COMPLETE.flag'
    try:
        with open(flag_path, 'w', encoding='utf-8') as ff:
            ff.write(datetime.now().isoformat() + '\n')
    except Exception:
        pass
    log(f'اكتملت جميع القوائم (>= {min_completion_pct:.1f}%) بنسبة 100% في الطابور وتم إغلاق التفريغ!')


if __name__ == '__main__':
    main()
