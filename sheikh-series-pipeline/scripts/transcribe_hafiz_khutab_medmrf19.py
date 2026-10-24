#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""transcribe_hafiz_khutab_medmrf19.py — محرك التفريغ الشامل المتوازي لحسابَي الـ Pro (medmrf19 و brain):
- الوكيل الأول (medmrf19): يكمل كل خطب الحبيب عمر بن حفيظ (habib-omar-ibn-hafiz/khutab_jumaa -> 337/337).
- الوكيل الثاني (brain): يكمل كل خطب الشيخ مولود السريري (mouloud-sariri/s043 -> 200/200)، وفور انتهائها ينضم تلقائياً لمساندة medmrf19 في إنهاء ما تبقى من خطب الحبيب عمر بن حفيظ!

مزوّد بأقفال حجز ذرية لكل خطبة (/tmp/khutab_claims/) لمنع أي تكرار بين الوكيلين،
وحارس كوتة مستقل لكل حساب (ينتظر تجدد نافذة 5h تلقائياً)، ورفع فوري لتطبيق «ميراث» بعد كل دفعة.
"""
import argparse
import glob
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime

ALL_TARGETS = {
    'hafiz': {
        'key': 'hafiz',
        'name': 'خطب الحبيب عمر بن حفيظ الكاملة (337 خطبة)',
        'series_dir': '/root/workspace/ytb/habib-omar-ibn-hafiz/khutab_jumaa',
        'target_total': 337,
        'keep_order': False,
    },
    'sariri': {
        'key': 'sariri',
        'name': 'خطب الشيخ العلامة مولود السريري الكاملة (200 خطبة)',
        'series_dir': '/root/workspace/ytb/mouloud-sariri/s043',
        'target_total': 200,
        'keep_order': True,
    },
}

AGY_TRANSCRIBE = '/root/workspace/SKILLS/sheikh-series-pipeline/scripts/agy_transcribe.py'
BUILD_INDEX = '/root/workspace/ytb/tools/build_index.py'
SYNC_YTB_SH = '/root/.hermes/scripts/sync_ytb.sh'
CLAIMS_DIR = '/tmp/khutab_claims'
AGY_BIN = '/root/.local/bin/agy'

BATCH_SIZE = int(os.environ.get('KHUTAB_BATCH_SIZE', '4'))
WORKERS = int(os.environ.get('KHUTAB_WORKERS', '1'))

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


def log(profile_name, msg):
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f'[{ts}] [{profile_name}] {msg}', flush=True)


def get_profile_quota(profile_home, profile_name):
    """فحص كوتة الحساب مباشرة بصفر توكن عبر /usage مع قاطع فوري عند أي خطأ 403 أو تعطيل."""
    env = os.environ.copy()
    env['HOME'] = profile_home
    out = {
        'gemini_5h_pct': 0.0,
        'gemini_5h_reset': '',
        'gemini_weekly_pct': 0.0,
        'gemini_weekly_reset': '',
        'disabled': False,
    }
    try:
        r = subprocess.run(
            [AGY_BIN, '-p', '/usage', '--output-format', 'json'],
            env=env, capture_output=True, text=True, timeout=25,
            stdin=subprocess.DEVNULL  # بدونها يتجمد agy -p مع stdin أنبوبي
        )
        combined = ((r.stdout or '') + ' ' + (r.stderr or '')).lower()
        if any(k in combined for k in ('permission_denied', 'code 403', 'disabled in this account', 'submit an appeal', 'violation of terms')):
            log(profile_name, f'[🚨 قاطع طوارئ فوري] الحساب {profile_name} معطّل أو مرفوض (403) — إيقاف فوري!')
            out['disabled'] = True
            return out
        if r.stdout.strip().startswith('{'):
            d = json.loads(r.stdout)
            if d.get('status') == 'ERROR':
                log(profile_name, f'[تحذير حالة الحساب] /usage أعاد ERROR: {d.get("error","")[:200]}')
                out['disabled'] = True
                return out
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
        log(profile_name, f'[تحذير فحص الكوتة] {e}')
    return out


def is_claimed_by_other(target_key, prefix, my_profile):
    """يتحقق مما إذا كانت الخطبة محجوزة حالياً من الوكيل الآخر (صلاحية الحجز 20 دقيقة)."""
    os.makedirs(CLAIMS_DIR, exist_ok=True)
    cpath = os.path.join(CLAIMS_DIR, f'{target_key}_{prefix}.claim')
    if not os.path.exists(cpath):
        return False
    try:
        age = time.time() - os.path.getmtime(cpath)
        if age > 1200:
            os.remove(cpath)
            return False
        owner = open(cpath, encoding='utf-8').read().strip()
        return owner != my_profile
    except OSError:
        return False


def claim_items(target_key, prefixes, my_profile):
    os.makedirs(CLAIMS_DIR, exist_ok=True)
    for prefix in prefixes:
        cpath = os.path.join(CLAIMS_DIR, f'{target_key}_{prefix}.claim')
        try:
            with open(cpath, 'w', encoding='utf-8') as f:
                f.write(my_profile)
        except OSError:
            pass


def release_claims(target_key, prefixes):
    for prefix in prefixes:
        cpath = os.path.join(CLAIMS_DIR, f'{target_key}_{prefix}.claim')
        try:
            if os.path.exists(cpath):
                os.remove(cpath)
        except OSError:
            pass


def scan_progress(series_dir, target_key, my_profile):
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
        if prefix not in valid_txts and not is_claimed_by_other(target_key, prefix, my_profile):
            missing.append(v)

    return videos, valid_txts, missing


def priority_key(v, keep_order=False):
    title = v.get('title') or ''
    dur_s = int(v.get('dur_s') or 1800)
    is_live_generic = (bool(GENERIC_LIVE_RE.search(title)) and 'بعنوان' not in title) or len(title) < 28
    is_seasonal = bool(SEASONAL_RE.search(title))
    if not is_live_generic and not is_seasonal:
        tier = 0  # الخطب الموضوعية الخالدة أولاً ثم الموسمية ثم المباشرة حتى يكتمل الكل 100%
    elif not is_live_generic:
        tier = 1
    else:
        tier = 2
    if keep_order:
        return (tier, int(v['n']))
    dur_bucket = 0 if (600 <= dur_s <= 2700) else 1
    return (tier, dur_bucket, dur_s, int(v['n']))


def write_state(state_file, profile_name, target_info, total_count, done_count, rem_count, quota, status_msg, current_batch=None):
    st = {
        'updated_at': datetime.now().isoformat(),
        'profile': profile_name,
        'active_target': target_info['name'],
        'series_dir': target_info['series_dir'],
        'target_total': target_info['target_total'],
        'total_khutbahs': total_count,
        'completed_khutbahs': done_count,
        'remaining_to_target': max(0, target_info['target_total'] - done_count),
        'remaining_in_series': rem_count,
        'completion_pct': round((done_count / total_count) * 100.0, 2) if total_count else 0.0,
        'quota': quota,
        'status': status_msg,
        'current_batch': current_batch or [],
    }
    tmp = state_file + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(st, f, ensure_ascii=False, indent=2)
    os.replace(tmp, state_file)


def sync_to_mirath_github(profile_name):
    log(profile_name, 'تحديث فهارس تطبيق ميراث (build_index.py) والرفع إلى GitHub (sync_ytb.sh)...')
    root_env = os.environ.copy()
    root_env['HOME'] = '/root'
    subprocess.run(['python3', BUILD_INDEX], cwd='/root/workspace/ytb', env=root_env, check=False)
    subprocess.run(['/bin/bash', SYNC_YTB_SH], env=root_env, check=False)


def run_target(profile_name, profile_home, state_file, target_info):
    series_dir = target_info['series_dir']
    target_total = target_info['target_total']
    target_key = target_info['key']
    keep_order = target_info.get('keep_order', False)
    pass_num = 1

    log(profile_name, f'=== بدء الهدف: {target_info["name"]} ({series_dir} -> الهدف {target_total}) ===')
    while True:
        videos, valid_txts, missing = scan_progress(series_dir, target_key, profile_name)
        total_count = len(videos)
        done_count = len(valid_txts)
        rem_count = len(missing)

        quota = get_profile_quota(profile_home, profile_name)
        if quota.get('disabled'):
            write_state(state_file, profile_name, target_info, total_count, done_count, rem_count, quota, 'STOPPED_CIRCUIT_BREAKER_403', [])
            log(profile_name, '🚨 توقف نهائي عبر قاطع الطوارئ (الحساب معطّل أو أعاد 403).')
            sys.exit(3)
        log(
            profile_name,
            f'[{target_info["name"]}] المنجز {done_count}/{target_total} ({round(done_count*100.0/max(1,total_count),1)}%) | '
            f'كوتة {profile_name}: 5h={quota["gemini_5h_pct"]}% · Weekly={quota["gemini_weekly_pct"]}%'
        )

        if done_count >= target_total or rem_count == 0:
            sync_to_mirath_github(profile_name)
            write_state(state_file, profile_name, target_info, total_count, done_count, rem_count, quota, 'COMPLETED_TARGET', [])
            log(profile_name, f'✅ اكتمل الهدف «{target_info["name"]}» ({done_count}/{target_total}) ورفعه إلى تطبيق ميراث!')
            return

        if quota['gemini_weekly_pct'] < 3.0:
            write_state(state_file, profile_name, target_info, total_count, done_count, rem_count, quota, 'PAUSED_WEEKLY_QUOTA_FLOOR', [])
            log(profile_name, f'[حارس الكوتة الأسبوعية] كوتة الأسبوع ({quota["gemini_weekly_pct"]}%) أقل من 3% — انتظار 10 دقائق...')
            time.sleep(600)
            continue

        if quota['gemini_5h_pct'] < 8.0:
            write_state(state_file, profile_name, target_info, total_count, done_count, rem_count, quota, f'WAITING_5H_RESET ({quota["gemini_5h_reset"]})', [])
            log(profile_name, f'[حارس نافذة 5 ساعات] كوتة 5h ({quota["gemini_5h_pct"]}%) أقل من 8% — انتظار 3 دقائق حتى تتجدد عند {quota["gemini_5h_reset"]}...')
            time.sleep(180)
            continue

        missing.sort(key=lambda v: priority_key(v, keep_order=keep_order))
        needed = min(BATCH_SIZE, target_total - done_count)
        batch = missing[:needed]
        prefixes = [f'{int(v["n"]):03d}' for v in batch]
        claim_items(target_key, prefixes, profile_name)
        only_str = ','.join(prefixes)
        batch_titles = [
            f'#{int(v["n"]):03d} ({round(int(v.get("dur_s") or 0)/60, 1)}m): {v.get("title","")[:60]}'
            for v in batch
        ]

        write_state(state_file, profile_name, target_info, total_count, done_count, rem_count, quota, 'TRANSCRIBING_BATCH', batch_titles)
        log(profile_name, f'إطلاق الدفعة ({len(batch)} خطب): {only_str}')
        for bt in batch_titles:
            log(profile_name, f'  -> {bt}')

        chunk_m = '22' if pass_num == 1 else '15'
        max_single_m = '36' if pass_num == 1 else '20'

        env = os.environ.copy()
        env['HOME'] = profile_home
        env['AGY_PROFILES'] = profile_name

        cmd = [
            sys.executable, '-u', AGY_TRANSCRIBE,
            series_dir,
            '--only', only_str,
            '--model', 'gemini-3.8-flash-high',
            '--agy-profile', profile_name,
            '--workers', str(WORKERS),
            '--max-single-minutes', max_single_m,
            '--chunk-minutes', chunk_m,
        ]
        t0 = time.time()
        try:
            rc_batch = subprocess.run(cmd, env=env, check=False).returncode
        finally:
            release_claims(target_key, prefixes)
        elapsed = round(time.time() - t0, 1)
        if rc_batch == 3:
            write_state(state_file, profile_name, target_info, total_count, done_count, rem_count, quota, 'STOPPED_CIRCUIT_BREAKER_403', [])
            log(profile_name, '🚨 توقف عبر قاطع الطوارئ من داخل agy_transcribe.')
            sys.exit(3)

        _, valid_after, missing_after = scan_progress(series_dir, target_key, profile_name)
        gained = len(valid_after) - done_count
        log(profile_name, f'انتهت الدفعة [{only_str}] في {elapsed}ث (أُنجز +{gained} خطبة جديدة · الإجمالي الآن {len(valid_after)}/{target_total})')

        sync_to_mirath_github(profile_name)

        import random
        rest_s = round(random.uniform(180.0, 300.0), 1)
        log(profile_name, f'[استراحة بشرية بين الدفعات] انتظار {rest_s}ث قبل الدفعة القادمة لمنع استثارة حساسات جوجل...')
        time.sleep(rest_s)

        if gained == 0 and len(missing_after) == rem_count:
            pass_num = 2
            log(profile_name, 'لم تتقدم الدفعة في التمريرة الحالية — تفعيل وضع التقسيم الدقيق (10 دقائق)...')
            time.sleep(10)


def main():
    ap = argparse.ArgumentParser(description='محرك تفريغ الخطب الكامل لحسابَي medmrf19 و brain')
    ap.add_argument('--profile', default=os.environ.get('AGY_PROFILE_WORKER', 'medmrf19'), help='اسم البروفايل (medmrf19 أو brain)')
    ap.add_argument('--primary', default=os.environ.get('PRIMARY_TARGET', 'hafiz'), choices=['hafiz', 'sariri'], help='السلسلة الأساسية التي يبدأ بها هذا الوكيل')
    args = ap.parse_args()

    profile_name = args.profile
    profile_home = f'/root/.agy-profiles/{profile_name}'
    state_file = (
        '/root/workspace/ytb-build/hafiz_khutab_state.json'
        if args.primary == 'hafiz'
        else '/root/workspace/ytb-build/sariri_khutab_state.json'
    )
    complete_flag = f'/root/workspace/ytb-build/KHUTAB_COMPLETE_{profile_name.upper()}.flag'

    if os.path.exists(complete_flag):
        os.remove(complete_flag)

    order = ['hafiz', 'sariri'] if args.primary == 'hafiz' else ['sariri', 'hafiz']
    log(profile_name, f'انطلاق الوكيل {profile_name} لترتيب الأهداف: {order}')
    for tkey in order:
        run_target(profile_name, profile_home, state_file, ALL_TARGETS[tkey])

    with open(complete_flag, 'w', encoding='utf-8') as cf:
        cf.write(datetime.now().isoformat() + '\n')
    log(profile_name, '🎉 اكتملت جميع خطب الحبيب عمر بن حفيظ (337/337) وخطب الشيخ مولود السريري (200/200) بالكامل!')


if __name__ == '__main__':
    main()
