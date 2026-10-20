#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""agy_multi_pool.py — إدارة وفحص ومزامنة ومعايرة الحسابات المتعددة لـ Antigravity (agy).

السياسة المعتمدة للحسابات:
- medmrf10 (medmrf.10@gmail.com — Ultra): الحساب الرئيسي (Main Account) للجلسات التفاعلية والبحث العميق وإنشاء الخطب والدروس. لا يُستخدم افتراضياً في التفريغ الصوتي.
- medmrf19 (medmrf.19@gmail.com — Pro) + brain (brainthomas555@gmail.com — Pro): الحسابان الافتراضيان للتفريغ الصوتي والمهام الغزيرة دون تفرقة بينهما؛ يُختار دائماً صاحب الكوتة الأسبوعية الأعلى (gemini-weekly) لاستغلال حصتيهما معاً قبل تاريخ التجديد الأسبوعي.

الوظائف الرئيسية:
1. --status                   : فحص جميع البروفايلات في ~/.agy-profiles/* وعرض حالة الكوتة الحية (0 توكن).
2. --best-transcribe-profile  : إرجاع أفضل بروفايل Pro للتفريغ حالياً (الأعلى في الكوتة الأسبوعية بين medmrf19 و brain).
3. --sync-to-vps              : نسخ توكنات البروفايلات من الماك إلى hermes-vps:/root/.agy-profiles/.
4. --calibrate PROFILE        : تفريغ درس واحد بحساب محدد وقياس استهلاك الكوتة (5h & Weekly) قبل وبعد بدقة.
"""
import argparse
import base64
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

PROFILES_ROOT = (
    '/root/.agy-profiles'
    if os.path.isdir('/root/.agy-profiles') and sys.platform != 'darwin'
    else (
        '/Users/macm1pro/.agy-profiles'
        if os.path.isdir('/Users/macm1pro/.agy-profiles')
        else os.path.expanduser('~/.agy-profiles')
    )
)

MAIN_ACCOUNT = 'medmrf10'
DEFAULT_TRANSCRIBE_PRO_POOL = ('medmrf19', 'brain')


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


def extract_email_from_token_file(pdir):
    tok_path = os.path.join(pdir, '.gemini', 'antigravity-cli', 'antigravity-oauth-token')
    try:
        tok = json.load(open(tok_path, encoding='utf-8'))
        idt = tok.get('id_token', '')
        if idt and '.' in idt:
            payload = idt.split('.')[1]
            payload += '=' * (-len(payload) % 4)
            claims = json.loads(base64.urlsafe_b64decode(payload))
            if claims.get('email'):
                return claims['email']
    except Exception:
        pass
    return 'unknown'


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


def inspect_profile(name, pdir, include_models=True):
    env = os.environ.copy()
    env['HOME'] = pdir
    role = 'Main (Ultra)' if name == MAIN_ACCOUNT else ('Default Transcribe (Pro)' if name in DEFAULT_TRANSCRIBE_PRO_POOL else 'Pro')
    info = {
        'profile': name,
        'role': role,
        'home': pdir,
        'email': extract_email_from_token_file(pdir),
        'tier': 'Ultra' if name == MAIN_ACCOUNT else 'Pro',
        'has_argon': name == MAIN_ACCOUNT,
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

    if include_models:
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
            info['tier'] = 'Ultra' if info['has_argon'] else ('Pro' if models else info['tier'])
        except Exception:
            pass

    if info['email'] == 'unknown':
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


def pick_best_pro_for_transcription(min_5h_pct=8.0, min_weekly_pct=2.0):
    """يختار تلقائياً حساب الـ Pro (بين medmrf19 و brain دون تفرقة) صاحب الكوتة الأسبوعية الأعلى حالياً."""
    candidates = []
    for name in DEFAULT_TRANSCRIBE_PRO_POOL:
        pdir = os.path.join(PROFILES_ROOT, name)
        tok = os.path.join(pdir, '.gemini', 'antigravity-cli', 'antigravity-oauth-token')
        if not os.path.exists(tok):
            continue
        info = inspect_profile(name, pdir, include_models=False)
        q = info.get('quota') or {}
        g5 = float(q.get('gemini_5h_pct') if q.get('gemini_5h_pct') is not None else 0.0)
        gw = float(q.get('gemini_weekly_pct') if q.get('gemini_weekly_pct') is not None else 0.0)
        eligible = (g5 >= min_5h_pct) and (gw >= min_weekly_pct)
        candidates.append({
            'profile': name,
            'home': pdir,
            'email': info['email'],
            'gemini_5h_pct': g5,
            'gemini_weekly_pct': gw,
            'gemini_weekly_reset': q.get('gemini_weekly_reset', ''),
            'eligible': eligible,
        })
    # الترتيب: المؤهل أولاً، ثم الأعلى في الكوتة الأسبوعية (gemini_weekly_pct)، ثم الأعلى في كوتة الـ 5 ساعات
    candidates.sort(
        key=lambda c: (1 if c['eligible'] else 0, c['gemini_weekly_pct'], c['gemini_5h_pct']),
        reverse=True
    )
    return candidates


def cmd_status(as_json=False):
    profiles = list_profiles()
    results = [inspect_profile(name, pdir, include_models=False) for name, pdir in profiles]
    if as_json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return results

    for r in results:
        q = r.get('quota') or {}
        g5 = f"{q.get('gemini_5h_pct')}%" if q.get('gemini_5h_pct') is not None else 'N/A'
        gw = f"{q.get('gemini_weekly_pct')}%" if q.get('gemini_weekly_pct') is not None else 'N/A'
        c5 = f"{q.get('claude_5h_pct')}%" if q.get('claude_5h_pct') is not None else 'N/A'
        cw = f"{q.get('claude_weekly_pct')}%" if q.get('claude_weekly_pct') is not None else 'N/A'
        print(
            f"• {r['profile']} ({r['email']}) [{r['role']}] -> "
            f"Gemini Weekly={gw} (5h={g5}) | Claude Weekly={cw} (5h={c5})"
        )
    best = pick_best_pro_for_transcription()
    if best:
        print(f"★ الحساب المختار للتفريغ الآن (الأعلى كوتة أسبوعية بين Pro): {best[0]['profile']} ({best[0]['gemini_weekly_pct']}%)")
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
        for fn in ('antigravity-oauth-token', 'jetski_state.pbtxt', 'settings.json', 'installation_id'):
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
    before = inspect_profile(profile_name, pdir, include_models=False)
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
    after = inspect_profile(profile_name, pdir, include_models=False)
    qa = after.get('quota') or {}
    print(f"  بعد التفريغ ({elapsed}ث): Gemini 5h = {qa.get('gemini_5h_pct')}% | Gemini Weekly = {qa.get('gemini_weekly_pct')}%")
    if qb.get('gemini_5h_pct') is not None and qa.get('gemini_5h_pct') is not None:
        d5 = round(qb['gemini_5h_pct'] - qa['gemini_5h_pct'], 3)
        dw = round((qb.get('gemini_weekly_pct') or 0) - (qa.get('gemini_weekly_pct') or 0), 3)
        print(f'  الاستهلاك الصافي: Δ 5h = -{d5}% | Δ Weekly = -{dw}%')


def main():
    ap = argparse.ArgumentParser(description='إدارة الحسابات المتعددة لـ agy')
    ap.add_argument('--status', action='store_true', help='فحص حالة وكوتة جميع البروفايلات')
    ap.add_argument('--best-transcribe-profile', action='store_true', help='إرجاع حساب الـ Pro صاحب أعلى كوتة أسبوعية للتفريغ')
    ap.add_argument('--json', action='store_true', help='إخراج JSON')
    ap.add_argument('--sync-to-vps', action='store_true', help='مزامنة البروفايلات إلى hermes-vps')
    ap.add_argument('--calibrate', metavar='PROFILE', help='معايرة كوتة بروفايل محدد بتفريغ درس واحد')
    ap.add_argument('--series-dir', help='مسار السلسلة للمعايرة')
    ap.add_argument('--only', help='رقم الدرس للمعايرة (مثل 012)')
    ap.add_argument('--model', default='gemini-3.8-flash-high', help='النموذج المستخدم')
    args = ap.parse_args()

    if args.sync_to_vps:
        cmd_sync_to_vps()
    elif args.best_transcribe_profile:
        cands = pick_best_pro_for_transcription()
        if args.json:
            print(json.dumps(cands, ensure_ascii=False, indent=2))
        elif cands:
            print(cands[0]['profile'])
        else:
            print('medmrf19')
    elif args.calibrate:
        if not args.series_dir or not args.only:
            ap.error('--calibrate يتطلب --series-dir و --only')
        cmd_calibrate(args.calibrate, args.series_dir, args.only, args.model)
    else:
        cmd_status(as_json=args.json)


if __name__ == '__main__':
    main()
