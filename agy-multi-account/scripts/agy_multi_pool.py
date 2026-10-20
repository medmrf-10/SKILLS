#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""agy_multi_pool.py — إدارة وفحص ومزامنة ومعايرة الحسابات المتعددة لـ Antigravity (agy).

الوظائف الرئيسية:
1. --status            : فحص جميع البروفايلات في ~/.agy-profiles/* وعرض جدول الكوتة الحي (0 توكن).
2. --sync-to-vps       : نسخ توكنات البروفايلات من الماك إلى hermes-vps:/root/.agy-profiles/.
3. --queue-status      : عرض حالة طابور التفريغ الصوتي الدقيقة على hermes-vps.
4. --calibrate PROFILE : تفريغ درس واحد بحساب محدد وقياس استهلاك الكوتة (5h & Weekly) قبل وبعد بدقة.
"""
import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import time

AGY_BIN = (
    '/root/.local/bin/agy'
    if os.path.exists('/root/.local/bin/agy')
    else (shutil.which('agy') or '/Users/macm1pro/.local/bin/agy')
)

PROFILES_ROOT = os.path.expanduser('~/.agy-profiles')


def ensure_macos_keychain_cleared():
    """على الماك: يحذف مدخل Keychain المشترك (-s gemini -a antigravity) حتى يعتمد كل بروفايل 100% على ملف antigravity-oauth-token الخاص به."""
    if sys.platform == 'darwin':
        subprocess.run(
            ['security', 'delete-generic-password', '-s', 'gemini', '-a', 'antigravity'],
            capture_output=True
        )


def ensure_default_profile_registered():
    """يتأكد من نسخ الحساب الأساسي ~/.gemini إلى ~/.agy-profiles/medmrf10 إن لم يكن موجوداً، وتنظيف Keychain الماك."""
    ensure_macos_keychain_cleared()
    default_cli = os.path.expanduser('~/.gemini/antigravity-cli')
    med10_cli = os.path.join(PROFILES_ROOT, 'medmrf10', '.gemini', 'antigravity-cli')
    if os.path.exists(os.path.join(default_cli, 'antigravity-oauth-token')) and not os.path.exists(
        os.path.join(med10_cli, 'antigravity-oauth-token')
    ):
        os.makedirs(med10_cli, exist_ok=True)
        for fname in ('antigravity-oauth-token', 'jetski_state.pbtxt', 'settings.json'):
            src = os.path.join(default_cli, fname)
            if os.path.exists(src):
                shutil.copy2(src, os.path.join(med10_cli, fname))


def list_profiles():
    ensure_default_profile_registered()
    if not os.path.isdir(PROFILES_ROOT):
        return []
    out = []
    for name in sorted(os.listdir(PROFILES_ROOT)):
        pdir = os.path.join(PROFILES_ROOT, name)
        tok = os.path.join(pdir, '.gemini', 'antigravity-cli', 'antigravity-oauth-token')
        if os.path.isdir(pdir) and os.path.exists(tok):
            out.append((name, pdir))
    return out


def parse_usage_response(resp_text):
    """يحلل مخرجات agy -p /usage إلى قاموس كوتة مهيكل."""
    res = {
        'gemini_weekly_pct': None,
        'gemini_weekly_reset': '',
        'gemini_5h_pct': None,
        'gemini_5h_reset': '',
        'claude_weekly_pct': None,
        'claude_weekly_reset': '',
        'claude_5h_pct': None,
        'claude_5h_reset': '',
    }
    for line in (resp_text or '').splitlines():
        parts = [p.strip() for p in line.split('\t')]
        if len(parts) < 3:
            continue
        group, bucket, pct_str = parts[0], parts[1], parts[2]
        reset_ts = parts[3] if len(parts) >= 4 else ''
        m = re.search(r'([0-9.]+)%', pct_str)
        val = float(m.group(1)) if m else None
        if 'Gemini' in group and 'Weekly' in bucket:
            res['gemini_weekly_pct'] = val
            res['gemini_weekly_reset'] = reset_ts
        elif 'Gemini' in group and 'Five Hour' in bucket:
            res['gemini_5h_pct'] = val
            res['gemini_5h_reset'] = reset_ts
        elif 'Claude' in group and 'Weekly' in bucket:
            res['claude_weekly_pct'] = val
            res['claude_weekly_reset'] = reset_ts
        elif 'Claude' in group and 'Five Hour' in bucket:
            res['claude_5h_pct'] = val
            res['claude_5h_reset'] = reset_ts
    return res


def inspect_profile(name, pdir):
    env = os.environ.copy()
    env['HOME'] = pdir
    info = {
        'profile': name,
        'home': pdir,
        'email': 'unknown',
        'tier': 'unknown',
        'has_argon': False,
        'models': [],
        'quota': {},
    }
    try:
        r_u = subprocess.run(
            [AGY_BIN, '-p', '/usage', '--output-format', 'json'],
            env=env, capture_output=True, text=True, timeout=25
        )
        if r_u.stdout.strip().startswith('{'):
            d = json.loads(r_u.stdout)
            info['quota'] = parse_usage_response(d.get('response', ''))
    except Exception as e:
        info['error'] = str(e)

    try:
        r_m = subprocess.run(
            [AGY_BIN, 'models'],
            env=env, capture_output=True, text=True, timeout=20
        )
        models = []
        for line in (r_m.stdout or '').splitlines():
            if '\t' in line:
                mid = line.split('\t', 1)[0].strip()
                if mid:
                    models.append(mid)
        info['models'] = models
        info['has_argon'] = any('argon' in m for m in models)
        info['tier'] = 'Ultra' if info['has_argon'] else ('Pro' if models else 'unknown')
    except Exception:
        pass

    log_dir = os.path.join(pdir, '.gemini', 'antigravity-cli', 'log')
    for lp in sorted(glob.glob(os.path.join(log_dir, '*.log')), key=os.path.getmtime, reverse=True)[:3]:
        try:
            for l in open(lp, errors='ignore'):
                if 'applyAuthResult:' in l and 'email=' in l:
                    m = re.search(r'email=([^\s,]+)', l)
                    if m:
                        info['email'] = m.group(1)
        except OSError:
            pass
    return info


def cmd_status(as_json=False):
    profiles = list_profiles()
    results = [inspect_profile(name, pdir) for name, pdir in profiles]
    if as_json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return results

    print('====================================================================================================')
    print(f'{"Profile":<12} | {"Email":<24} | {"Tier":<6} | {"Gem 5h":<7} | {"Gem Wk":<7} | {"Cld 5h":<7} | {"Cld Wk":<7} | {"Argon?"}')
    print('----------------------------------------------------------------------------------------------------')
    for r in results:
        q = r.get('quota') or {}
        g5 = f"{q.get('gemini_5h_pct')}%" if q.get('gemini_5h_pct') is not None else 'N/A'
        gw = f"{q.get('gemini_weekly_pct')}%" if q.get('gemini_weekly_pct') is not None else 'N/A'
        c5 = f"{q.get('claude_5h_pct')}%" if q.get('claude_5h_pct') is not None else 'N/A'
        cw = f"{q.get('claude_weekly_pct')}%" if q.get('claude_weekly_pct') is not None else 'N/A'
        print(
            f"{r['profile']:<12} | {r['email']:<24} | {r['tier']:<6} | {g5:<7} | {gw:<7} | {c5:<7} | {cw:<7} | {'YES' if r['has_argon'] else 'NO (Flash)'}"
        )
    print('====================================================================================================')
    return results


def cmd_sync_to_vps(vps_host='hermes-vps'):
    profiles = list_profiles()
    if not profiles:
        print('لا توجد بروفايلات في ~/.agy-profiles للمزامنة.')
        return
    for name, pdir in profiles:
        remote_dir = f'/root/.agy-profiles/{name}/.gemini/antigravity-cli'
        subprocess.run(['ssh', vps_host, f'mkdir -p {remote_dir}'], check=True)
        files_to_copy = []
        for fn in ('antigravity-oauth-token', 'jetski_state.pbtxt', 'settings.json'):
            fp = os.path.join(pdir, '.gemini', 'antigravity-cli', fn)
            if os.path.exists(fp):
                files_to_copy.append(fp)
        if files_to_copy:
            subprocess.run(['scp', '-q'] + files_to_copy + [f'{vps_host}:{remote_dir}/'], check=True)
            print(f'[✓ مزامنة] {name} -> {vps_host}:{remote_dir}/ ({len(files_to_copy)} ملفات)')


def cmd_calibrate(profile_name, series_dir, only_lesson, model='gemini-3.8-flash-high'):
    pdir = os.path.join(PROFILES_ROOT, profile_name)
    if not os.path.isdir(pdir):
        raise SystemExit(f'البروفايل غير موجود: {pdir}')

    print(f'[1/3] قياس الكوتة القبلية للبروفايل {profile_name}...')
    before = inspect_profile(profile_name, pdir)
    qb = before.get('quota') or {}
    print(f"  قبل التفريغ: Gemini 5h = {qb.get('gemini_5h_pct')}% | Gemini Weekly = {qb.get('gemini_weekly_pct')}%")

    agy_tr = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        'sheikh-series-pipeline', 'scripts', 'agy_transcribe.py'
    )
    cmd = [
        sys.executable, agy_tr, series_dir,
        '--only', str(only_lesson),
        '--model', model,
        '--agy-profile', profile_name,
    ]
    print(f'[2/3] تشغيل التفريغ عبر {profile_name} ({model})...')
    t0 = time.time()
    subprocess.run(cmd, check=True)
    elapsed = round(time.time() - t0, 1)

    print(f'[3/3] قياس الكوتة البعدية للبروفايل {profile_name}...')
    after = inspect_profile(profile_name, pdir)
    qa = after.get('quota') or {}
    print(f"  بعد التفريغ ({elapsed}ث): Gemini 5h = {qa.get('gemini_5h_pct')}% | Gemini Weekly = {qa.get('gemini_weekly_pct')}%")
    if qb.get('gemini_5h_pct') is not None and qa.get('gemini_5h_pct') is not None:
        d5 = round(qb['gemini_5h_pct'] - qa['gemini_5h_pct'], 2)
        dw = round((qb.get('gemini_weekly_pct') or 0) - (qa.get('gemini_weekly_pct') or 0), 2)
        print(f'  الاستهلاك الصافي: Δ 5h = -{d5}% | Δ Weekly = -{dw}%')


def main():
    ap = argparse.ArgumentParser(description='إدارة الحسابات المتعددة لـ agy')
    ap.add_argument('--status', action='store_true', help='فحص حالة وكوتة جميع البروفايلات')
    ap.add_argument('--json', action='store_true', help='إخراج JSON')
    ap.add_argument('--sync-to-vps', action='store_true', help='مزامنة البروفايلات إلى hermes-vps')
    ap.add_argument('--calibrate', metavar='PROFILE', help='معايرة كوتة بروفايل محدد بتفريغ درس واحد')
    ap.add_argument('--series-dir', help='مسار السلسلة للمعايرة')
    ap.add_argument('--only', help='رقم الدرس للمعايرة (مثل 012)')
    ap.add_argument('--model', default='gemini-3.8-flash-high', help='النموذج المستخدم')
    args = ap.parse_args()

    if args.sync_to_vps:
        cmd_sync_to_vps()
    elif args.calibrate:
        if not args.series_dir or not args.only:
            ap.error('--calibrate يتطلب --series-dir و --only')
        cmd_calibrate(args.calibrate, args.series_dir, args.only, args.model)
    else:
        cmd_status(as_json=args.json)


if __name__ == '__main__':
    main()
