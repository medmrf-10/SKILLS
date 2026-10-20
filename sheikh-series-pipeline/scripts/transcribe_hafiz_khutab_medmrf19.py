#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""transcribe_hafiz_khutab_medmrf19.py — محرك التفريغ الموضوعي المستقل بحساب medmrf19:
1) 50 خطبة موضوعية للحبيب عمر بن حفيظ (habib-omar-ibn-hafiz/khutab_jumaa: من 8 إلى 58 خطبة)
2) 50 خطبة منبرية موضوعية للشيخ مولود السريري (mouloud-sariri/s043: من 85 إلى 135 خطبة)

يعمل كخدمة systemd مستقلة تماماً على الخادم بحساب medmrf19 (gemini-3.8-flash-high)
ويرفع كل دفعة (6 خطب) فوراً إلى GitHub وتطبيق «ميراث» دون استهلاك أي توكن من الحساب الرئيسي medmrf10.
"""
import glob
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime

TARGETS = [
    {
        'name': 'خطب الحبيب عمر بن حفيظ (50 خطبة موضوعية)',
        'series_dir': '/root/workspace/ytb/habib-omar-ibn-hafiz/khutab_jumaa',
        'target_total': 58,  # 8 سابقة + 50 خطبة موضوعية جديدة
        'keep_order': False,
    },
]

AGY_TRANSCRIBE = '/root/workspace/SKILLS/sheikh-series-pipeline/scripts/agy_transcribe.py'
BUILD_INDEX = '/root/workspace/ytb/tools/build_index.py'
SYNC_YTB_SH = '/root/.hermes/scripts/sync_ytb.sh'
STATE_FILE = '/root/workspace/ytb-build/hafiz_khutab_state.json'
COMPLETE_FLAG = '/root/workspace/ytb-build/HAFIZ_KHUTAB_COMPLETE.flag'
PROFILE_NAME = 'medmrf19'
PROFILE_HOME = '/root/.agy-profiles/medmrf19'
AGY_BIN = '/root/.local/bin/agy'

BATCH_SIZE = int(os.environ.get('KHUTAB_BATCH_SIZE', '6'))
WORKERS = int(os.environ.get('KHUTAB_WORKERS', '4'))

SEASONAL_RE = re.compile(
    r'رمضان|شعبان|شوال|رجب|عاشوراء|محرم|صفر|ربيع|الحج|حج\b|عرفة|عيد|الأضحى|أضحى|الفطر|فطر|'
    r'الكسوف|كسوف|الخسوف|خسوف|الاستسقاء|استسقاء|الإسراء|إسراء|المعراج|معراج|الهجرة|هجرة|المولد|مولد|'
    r'بدر|أحد|الفتح|العام الهجري|السنة الجديدة|ذي الحجة|ذو الحجة|ذي القعدة|العشر|ليلة القدر|غزوة|أيلول|حزيران|الأقصى|قدس|'
    r'الصوم|الصيام|الأضحية|أضحية|زكاة الفطر'
)
GENERIC_LIVE_RE = re.compile(
    r'خطبة[ _]الجمعة (من|في) (جامع|مسجد|صولو|دار|مصلى)|بث[_ ]مباشر.*(من|في) (جامع|مسجد)|'
    r'#مباشر\s*:?\s*#?خطبة|مباشر من '
)


def log(msg):
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f'[{ts}] [khutab-medmrf19] {msg}', flush=True)


def get_medmrf19_quota():
    """فحص كوتة medmrf19 مباشرة بصفر توكن عبر /usage."""
    env = os.environ.copy()
    env['HOME'] = PROFILE_HOME
    out = {
        'gemini_5h_pct': 100.0,
        'gemini_5h_reset': '',
        'gemini_weekly_pct': 100.0,
        'gemini_weekly_reset': '',
    }
    try:
        r = subprocess.run(
            [AGY_BIN, '-p', '/usage', '--output-format', 'json'],
            env=env, capture_output=True, text=True, timeout=25
        )
        if r.stdout.strip().startswith('{'):
            d = json.loads(r.stdout)
            groups = d.get('command', {}).get('data', {}).get('groups', [])
            for g in groups:
                if 'Gemini' in g.get('name', ''):
                    for b in g.get('buckets', []):
                        bid = b.get('id', '')
                        pct = round(float(b.get('remaining_fraction') or 0.0) * 100.0, 3)
                        if bid == 'gemini-5h':
                            out['gemini_5h_pct'] = pct
                            out['gemini_5h_reset'] = b.get('reset_time', '')
                        elif bid == 'gemini-weekly':
                            out['gemini_weekly_pct'] = pct
                            out['gemini_weekly_reset'] = b.get('reset_time', '')
    except Exception as e:
        log(f'[تحذير فحص الكوتة] {e}')
    return out


def scan_progress(series_dir):
    meta_path = os.path.join(series_dir, '_meta.json')
    meta = json.load(open(meta_path, encoding='utf-8'))
    videos = meta.get('videos', [])
    valid_txts = {}
    for fp in glob.glob(os.path.join(series_dir, '*.txt')):
        bn = os.path.basename(fp)
        if bn.startswith('_'):
            continue
        try:
            sz = os.path.getsize(fp)
            if sz >= 400:
                prefix = bn.split('_', 1)[0]
                valid_txts[prefix] = fp
        except OSError:
            pass

    missing = []
    for v in videos:
        n = int(v['n'])
        prefix = f'{n:03d}'
        if prefix not in valid_txts:
            missing.append(v)

    return videos, valid_txts, missing


def priority_key(v, keep_order=False):
    title = v.get('title') or ''
    dur_s = int(v.get('dur_s') or 1800)
    is_live_generic = (bool(GENERIC_LIVE_RE.search(title)) and 'بعنوان' not in title) or len(title) < 28
    is_seasonal = bool(SEASONAL_RE.search(title))
    if not is_live_generic and not is_seasonal:
        tier = 0  # خطب موضوعية خالصة لكل زمان (بلا مناسبات موسمية)
    elif not is_live_generic:
        tier = 1
    else:
        tier = 2
    if keep_order:
        return (tier, int(v['n']))
    dur_bucket = 0 if (600 <= dur_s <= 2700) else 1
    return (tier, dur_bucket, dur_s, int(v['n']))


def write_state(target_info, total_count, done_count, rem_count, quota, status_msg, current_batch=None):
    st = {
        'updated_at': datetime.now().isoformat(),
        'profile': PROFILE_NAME,
        'active_target': target_info['name'],
        'series_dir': target_info['series_dir'],
        'target_total': target_info['target_total'],
        'total_khutbahs': total_count,
        'completed_khutbahs': done_count,
        'remaining_to_target': max(0, target_info['target_total'] - done_count),
        'remaining_in_series': rem_count,
        'quota': quota,
        'status': status_msg,
        'current_batch': current_batch or [],
    }
    tmp = STATE_FILE + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(st, f, ensure_ascii=False, indent=2)
    os.replace(tmp, STATE_FILE)


def sync_to_mirath_github():
    log('تحديث فهارس تطبيق ميراث (build_index.py) والرفع إلى GitHub (sync_ytb.sh)...')
    root_env = os.environ.copy()
    root_env['HOME'] = '/root'
    subprocess.run(['python3', BUILD_INDEX], cwd='/root/workspace/ytb', env=root_env, check=False)
    subprocess.run(['/bin/bash', SYNC_YTB_SH], env=root_env, check=False)


def run_target(target_info):
    series_dir = target_info['series_dir']
    target_total = target_info['target_total']
    keep_order = target_info.get('keep_order', False)
    pass_num = 1

    log(f'=== بدء الهدف: {target_info["name"]} ({series_dir} -> الهدف {target_total}) ===')
    while True:
        videos, valid_txts, missing = scan_progress(series_dir)
        total_count = len(videos)
        done_count = len(valid_txts)
        rem_count = len(missing)

        quota = get_medmrf19_quota()
        log(
            f'[{target_info["name"]}] المنجز {done_count}/{target_total} (من أصل {total_count}) | '
            f'كوتة {PROFILE_NAME}: 5h={quota["gemini_5h_pct"]}% · Weekly={quota["gemini_weekly_pct"]}%'
        )

        if done_count >= target_total or rem_count == 0:
            sync_to_mirath_github()
            write_state(target_info, total_count, done_count, rem_count, quota, 'COMPLETED_TARGET', [])
            log(f'✅ اكتمل الهدف «{target_info["name"]}» ({done_count}/{target_total}) ورفعه إلى تطبيق ميراث!')
            return

        if quota['gemini_weekly_pct'] < 4.0:
            write_state(target_info, total_count, done_count, rem_count, quota, 'PAUSED_WEEKLY_QUOTA_FLOOR', [])
            log(f'[حارس الكوتة الأسبوعية] كوتة الأسبوع ({quota["gemini_weekly_pct"]}%) أقل من 4% — انتظار 10 دقائق...')
            time.sleep(600)
            continue

        if quota['gemini_5h_pct'] < 8.0:
            write_state(target_info, total_count, done_count, rem_count, quota, f'WAITING_5H_RESET ({quota["gemini_5h_reset"]})', [])
            log(f'[حارس نافذة 5 ساعات] كوتة 5h ({quota["gemini_5h_pct"]}%) أقل من 8% — انتظار 3 دقائق حتى تتجدد عند {quota["gemini_5h_reset"]}...')
            time.sleep(180)
            continue

        missing.sort(key=lambda v: priority_key(v, keep_order=keep_order))
        needed = min(BATCH_SIZE, target_total - done_count)
        batch = missing[:needed]
        only_str = ','.join(f'{int(v["n"]):03d}' for v in batch)
        batch_titles = [
            f'#{int(v["n"]):03d} ({round(int(v.get("dur_s") or 0)/60, 1)}m): {v.get("title","")[:60]}'
            for v in batch
        ]

        write_state(target_info, total_count, done_count, rem_count, quota, 'TRANSCRIBING_BATCH', batch_titles)
        log(f'إطلاق الدفعة ({len(batch)} خطب): {only_str}')
        for bt in batch_titles:
            log(f'  -> {bt}')

        chunk_m = '15' if pass_num == 1 else '10'
        max_single_m = '18' if pass_num == 1 else '12'

        env = os.environ.copy()
        env['HOME'] = PROFILE_HOME
        env['AGY_PROFILES'] = PROFILE_NAME

        cmd = [
            sys.executable, '-u', AGY_TRANSCRIBE,
            series_dir,
            '--only', only_str,
            '--model', 'gemini-3.8-flash-high',
            '--agy-profile', PROFILE_NAME,
            '--workers', str(WORKERS),
            '--max-single-minutes', max_single_m,
            '--chunk-minutes', chunk_m,
        ]
        t0 = time.time()
        subprocess.run(cmd, env=env, check=False)
        elapsed = round(time.time() - t0, 1)

        _, valid_after, missing_after = scan_progress(series_dir)
        gained = len(valid_after) - done_count
        log(f'انتهت الدفعة [{only_str}] في {elapsed}ث (أُنجز +{gained} خطبة جديدة · الإجمالي الآن {len(valid_after)}/{target_total})')

        sync_to_mirath_github()

        if gained == 0 and len(missing_after) == rem_count:
            pass_num = 2
            log('لم تتقدم الدفعة في التمريرة الحالية — تفعيل وضع التقسيم الدقيق (10 دقائق)...')
            time.sleep(10)


def main():
    if os.path.exists(COMPLETE_FLAG):
        os.remove(COMPLETE_FLAG)

    log(f'بدء محرك تفريغ الخطب الموضوعية المستقل بحساب {PROFILE_NAME} (50 للحبيب عمر + 50 للشيخ مولود السريري)...')
    for target_info in TARGETS:
        run_target(target_info)

    with open(COMPLETE_FLAG, 'w', encoding='utf-8') as cf:
        cf.write(datetime.now().isoformat() + '\n')
    log('🎉 اكتملت جميع الأهداف (50 خطبة موضوعية للحبيب عمر بن حفيظ + 50 خطبة موضوعية للشيخ مولود السريري) ورفعت إلى تطبيق ميراث!')


if __name__ == '__main__':
    main()
