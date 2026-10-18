#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""vps_align_feeder.py — يجهز ملفات صوتية مضغوطة (Opus 12kbps VoIP ≈ 5.2MB/ساعة) على السيرفر لطابور المحاذاة على الماك.

- يرتب السلاسل بنفس ترتيب transcribe_selected_smallest_first.py تماماً (الأصغر فالأكبر).
- يستهدف فقط الدروس التي اكتمل تفريغها النصي (.txt موجود وصالح) ولم تُحاذَ بعد (.align.json غير موجود).
- يحافظ على نافذة جاهزة (MAX_BUFFER = 40 درساً) في /root/workspace/align-bridge/ready/ حتى لا يمتلئ القرص ولا ينتظر الماك.
"""
import concurrent.futures
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime

SELECTIONS_JSON = '/root/workspace/cheikh-exports/cheikh-selected-curated-2026-10-17.json'
YTB_ROOT = '/root/workspace/ytb'
BRIDGE_DIR = '/root/workspace/align-bridge/ready'
STATE_FILE = '/root/workspace/ytb-build/align_feeder_state.json'
MAX_BUFFER = int(os.environ.get('ALIGN_MAX_BUFFER', '40'))
FEEDER_WORKERS = int(os.environ.get('ALIGN_FEEDER_WORKERS', '2'))

YTDLP = '/root/venvs/asr/bin/yt-dlp'
COOKIES = '/root/.config/mirath-cookies/youtube.txt'
FLAGS = [
    '--js-runtimes', 'node',
    '--remote-components', 'ejs:github',
    '--extractor-args', 'youtube:player_client=web,default',
]

LOCK = threading.Lock()


def log(msg):
    print(f'[{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}] [align-feeder] {msg}', flush=True)


def index_ytb_txt_and_align():
    """يرصد كل ملفات .txt الصالحة في /root/workspace/ytb والتي ليس لها .align.json بعد."""
    yt_to_txt = {}
    aligned_vids = set()
    for root, dirs, files in os.walk(YTB_ROOT):
        for skip in ('.git', '_variants', '_raw_preamble_backup'):
            if skip in dirs:
                dirs.remove(skip)
        files_set = set(files)
        for f in files:
            if not f.endswith('.txt'):
                continue
            stem = f[:-4]
            parts = stem.split('_', 1)
            if len(parts) != 2 or (len(parts[1]) != 11 and not parts[1].startswith('archive__')):
                continue
            vid = parts[1]
            p = os.path.join(root, f)
            try:
                if os.path.getsize(p) < 600:
                    continue
                al_name = stem + '.align.json'
                if al_name in files_set and os.path.getsize(os.path.join(root, al_name)) > 200:
                    aligned_vids.add(vid)
                else:
                    yt_to_txt[vid] = p
            except OSError:
                pass
    return yt_to_txt, aligned_vids


def build_ordered_lessons():
    """يرتب السلاسل بنفس ترتيب طابور التفريغ الأصلي (الأصغر فالأكبر) ويستخرج الدروس المفرغة التي تنتظر المحاذاة."""
    data = json.load(open(SELECTIONS_JSON, encoding='utf-8'))
    yt_to_txt, aligned_vids = index_existing_and_aligned = index_ytb_txt_and_align()

    series_list = []
    cutoff_ts = 1792180000  # Oct 17, 2026 00:00
    for s in data.get('series', []):
        lessons = [l for l in (s.get('lessons') or []) if l.get('yt_id')]
        if not lessons:
            continue
        tot_dur = sum(int(l.get('duration') or 0) for l in lessons)
        # Check if this series has newly transcribed lessons from the current queue run
        has_new_txt = any(
            (l['yt_id'] in yt_to_txt and os.path.getmtime(yt_to_txt[l['yt_id']]) >= cutoff_ts)
            for l in lessons
        )
        priority_tier = 0 if has_new_txt else 1
        series_list.append((priority_tier, len(lessons), tot_dur, s, lessons))

    # ترتيب تصاعدي: الطابور الجديد أولاً، ومن السلاسل الأصغر إلى الأكبر
    series_list.sort(key=lambda x: (x[0], x[1], x[2]))

    pending = []
    for tier, _, _, s, lessons in series_list:
        if tier > 0:
            continue  # الطابور الجديد فقط كما طلب محمد
        for idx, l in enumerate(lessons, 1):
            vid = l['yt_id']
            if vid in aligned_vids:
                continue
            txt_path = yt_to_txt.get(vid)
            if not txt_path:
                continue
            rel_txt = os.path.relpath(txt_path, YTB_ROOT)
            sheikh_slug, row_key, fn = rel_txt.split(os.sep, 2)
            stem = fn[:-4]
            key = f'{sheikh_slug}__{row_key}__{stem}'
            pending.append({
                'key': key,
                'vid': vid,
                'url': l.get('yt_url') or '',
                'stem': stem,
                'sheikh': sheikh_slug,
                'row': row_key,
                'txt_path': txt_path,
                'series_dir': os.path.dirname(txt_path),
                'dur_s': int(l.get('duration') or 0),
            })
    return pending, len(aligned_vids)


def cleanup_completed_in_bridge():
    os.makedirs(BRIDGE_DIR, exist_ok=True)
    for jpath in glob.glob(os.path.join(BRIDGE_DIR, '*.job.json')):
        try:
            job = json.load(open(jpath, encoding='utf-8'))
            txt_p = job.get('txt_path', '')
            al_p = txt_p[:-4] + '.align.json'
            if os.path.exists(al_p) and os.path.getsize(al_p) > 200:
                opus_p = jpath[:-9] + '.opus'
                for p in (jpath, opus_p):
                    if os.path.exists(p):
                        os.remove(p)
        except Exception:
            pass


def prepare_one_opus(item):
    key = item['key']
    opus_out = os.path.join(BRIDGE_DIR, key + '.opus')
    job_out = os.path.join(BRIDGE_DIR, key + '.job.json')
    al_path = item['txt_path'][:-4] + '.align.json'

    if os.path.exists(al_path) and os.path.getsize(al_path) > 200:
        return True
    if os.path.exists(opus_out) and os.path.exists(job_out) and os.path.getsize(opus_out) > 1000:
        return True

    # 1) إذا كان ملف الصوت موجوداً أصلاً في مجلد السلسلة، حوّله مباشرة إلى Opus 12k بدون إعادة تنزيل
    src_existing = None
    for ext in ('.mp3', '.m4a', '.webm', '.wav', '.opus'):
        cand = os.path.join(item['series_dir'], item['stem'] + ext)
        if os.path.exists(cand) and os.path.getsize(cand) > 10000:
            src_existing = cand
            break

    with tempfile.TemporaryDirectory(prefix='opus_feed_') as tmpd:
        raw_audio = src_existing
        if not raw_audio:
            direct_url = item.get('url') or ''
            if direct_url and ('archive.org/' in direct_url or direct_url.lower().endswith(('.mp3', '.m4a', '.wav', '.ogg', '.opus'))):
                raw_dl = os.path.join(tmpd, 'raw.mp3')
                cr = subprocess.run(['curl', '-fL', '--retry', '3', '--connect-timeout', '20', '-sS', direct_url, '-o', raw_dl], timeout=600)
                if cr.returncode == 0 and os.path.exists(raw_dl) and os.path.getsize(raw_dl) > 10000:
                    raw_audio = raw_dl
            if not raw_audio:
                url = direct_url if (direct_url and direct_url.startswith('http')) else f'https://www.youtube.com/watch?v={item["vid"]}'
                tmpl = os.path.join(tmpd, 'raw.%(ext)s')
                cmd = [
                    YTDLP, '--no-warnings', '--no-playlist',
                    *FLAGS,
                    '-f', 'worstaudio[abr>=32]/worstaudio/bestaudio',
                    '-o', tmpl, url,
                ]
                if os.path.exists(COOKIES):
                    cmd[3:3] = ['--cookies', COOKIES]
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
                cands = glob.glob(os.path.join(tmpd, 'raw.*'))
                if res.returncode != 0 or not cands:
                    # Fallback to mirath-audio if cookies needed refresh
                    if os.path.exists('/usr/local/bin/mirath-audio'):
                        subprocess.run(
                            ['/usr/local/bin/mirath-audio', url, '--outdir', tmpd, '--name', 'raw'],
                            capture_output=True, text=True, timeout=900
                        )
                        cands = glob.glob(os.path.join(tmpd, 'raw.*'))
                if not cands:
                    log(f'✗ فشل تنزيل الصوت لـ {key}')
                    return False
                raw_audio = cands[0]

        tmp_opus = os.path.join(tmpd, 'out.opus')
        ff_cmd = [
            'ffmpeg', '-nostdin', '-y', '-loglevel', 'error',
            '-threads', '1',
            '-i', raw_audio,
            '-vn', '-ac', '1', '-ar', '16000',
            '-c:a', 'libopus', '-b:a', '12k', '-compression_level', '0', '-application', 'voip',
            '-map_metadata', '-1', tmp_opus,
        ]
        ff = subprocess.run(ff_cmd, capture_output=True, text=True, timeout=300)
        if ff.returncode != 0 or not os.path.exists(tmp_opus) or os.path.getsize(tmp_opus) < 1000:
            log(f'✗ فشل تحويل Opus لـ {key}: {(ff.stderr or "")[-200:]}')
            return False

        shutil.move(tmp_opus, opus_out)
        job_meta = {
            'key': key,
            'vid': item['vid'],
            'stem': item['stem'],
            'sheikh': item['sheikh'],
            'row': item['row'],
            'txt_path': item['txt_path'],
            'dur_s': item['dur_s'],
            'opus_bytes': os.path.getsize(opus_out),
            'created_at': time.time(),
        }
        with open(job_out + '.tmp', 'w', encoding='utf-8') as jf:
            json.dump(job_meta, jf, ensure_ascii=False, indent=2)
        os.replace(job_out + '.tmp', job_out)
        mb = job_meta['opus_bytes'] / (1024.0 * 1024.0)
        log(f'✓ جاهز للمحاذاة: {key}.opus ({mb:.2f} MB)')
        return True


def main():
    os.makedirs(BRIDGE_DIR, exist_ok=True)
    log(f'بدء مغذي المحاذاة المضغوط (Opus 12k VoIP · WORKERS={FEEDER_WORKERS} · MAX_BUFFER={MAX_BUFFER})...')
    while True:
        try:
            cleanup_completed_in_bridge()
            pending, aligned_cnt = build_ordered_lessons()
            ready_jobs = glob.glob(os.path.join(BRIDGE_DIR, '*.job.json'))
            state = {
                'updated_at': datetime.now().isoformat(),
                'aligned_in_curated': aligned_cnt,
                'pending_with_txt': len(pending),
                'ready_in_bridge': len(ready_jobs),
            }
            with open(STATE_FILE, 'w', encoding='utf-8') as sf:
                json.dump(state, sf, ensure_ascii=False, indent=2)

            if len(ready_jobs) >= MAX_BUFFER or not pending:
                time.sleep(10)
                continue

            to_prepare = []
            for item in pending:
                jpath = os.path.join(BRIDGE_DIR, item['key'] + '.job.json')
                if not os.path.exists(jpath):
                    to_prepare.append(item)
                if len(ready_jobs) + len(to_prepare) >= MAX_BUFFER:
                    break

            if not to_prepare:
                time.sleep(10)
                continue

            with concurrent.futures.ThreadPoolExecutor(max_workers=FEEDER_WORKERS) as pool:
                list(pool.map(prepare_one_opus, to_prepare[:FEEDER_WORKERS * 3]))
        except Exception as e:
            log(f'خطأ في حلقة المغذي: {e}')
            time.sleep(10)


if __name__ == '__main__':
    main()
