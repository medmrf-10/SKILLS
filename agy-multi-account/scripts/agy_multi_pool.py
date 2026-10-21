#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""agy_multi_pool.py — إدارة وفحص ومزامنة ومعايرة الحسابات المتعددة لـ Antigravity (agy).

السجل المرجعي للحسابات (المصدر الوحيد للحقيقة): ../profiles.json
  (الاسم، البريد، الخطة، الدور main|transcribe|unassigned، الـ aliases). أي بروفايل موجود في
  ~/.agy-profiles ولم يُسجَّل هناك يُعامَل كـ unassigned تلقائياً.

السياسة المعتمدة للحسابات:
- medmrf10 (medmrf.10@gmail.com — Ultra): الحساب الرئيسي (Main Account) للجلسات التفاعلية والبحث العميق وإنشاء الخطب والدروس. لا يُستخدم افتراضياً في التفريغ الصوتي.
- medmrf19 (medmrf.19@gmail.com): مدير عائلة Google، محظور من جوجل (403) — لا يُستعمل.
- brain (brainthomas555@gmail.com — Pro): حساب تفريغ مستقل بحصته الخاصة.
- العائلة (mb10 ← bm10 ← mb19 ← medmrfco، وanimeco خارج التناوب لعدم الأهلية): حصتها مشتركة بين الأعضاء، فتُعامل كخانة تفريغ واحدة:
  يُستعمل mb10 ما دام سليماً، وإن تعثّر (حظر/عدم أهلية/فشل فحص) ننتقل للتالي بحسب failover_order. جوجل تعاقب الحساب المخالف نفسه لا العائلة (إفادة المالك).
- يُختار دائماً بين الخانات المستقلة (brain والعائلة) صاحب الكوتة الأسبوعية الأعلى (gemini-weekly).

الوظائف الرئيسية:
1. --status                   : فحص جميع البروفايلات في ~/.agy-profiles/* وعرض حالة الكوتة الحية (0 توكن).
2. --best-transcribe-profile  : إرجاع أفضل بروفايل Pro للتفريغ حالياً (الأعلى في الكوتة الأسبوعية بين حسابات التفريغ).
3. --sync-to-vps              : نسخ توكنات البروفايلات من الماك إلى hermes-vps:/root/.agy-profiles/.
4. --calibrate PROFILE        : تفريغ درس واحد بحساب محدد وقياس استهلاك الكوتة (5h & Weekly) قبل وبعد بدقة.
5. --doctor                   : فحص صحة كل بروفايل (التوكن، الصلاحيات، تطابق البريد مع السجل، Keychain) دون أي تعديل.
6. --reconcile-keychain       : نقل توكن Keychain إلى البروفايل صاحبه بحسب البريد (لا يحذف شيئاً إلا مع --delete).
7. --run PROFILE [-- ARGS]    : تشغيل agy بحساب معزول (بديل مستقل عن ~/.zshrc يعمل من أي وكيل أو سكربت).
8. --print-aliases            : توليد دوال/aliases الـ zsh من السجل (للـ source في ~/.zshrc).
9. --backup / --restore P     : نسخ احتياطي لتوكنات كل البروفايلات / استعادة توكن بروفايل من أحدث نسخة.

ملاحظة هندسية مهمة: agy -p يتجمد عندما يكون stdin أنبوباً مفتوحاً (كما في استدعاء الوكلاء/الـ cron)،
لذلك تُستدعى كل أوامر الفحص هنا مع stdin=DEVNULL.
"""
import argparse
import base64
import concurrent.futures
import glob
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone

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

REGISTRY_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'profiles.json')

# قيم احتياطية عند غياب profiles.json
MAIN_ACCOUNT = 'medmrf10'
DEFAULT_TRANSCRIBE_PRO_POOL = ('mb10', 'brain')

KEYCHAIN_SERVICE = 'gemini'
KEYCHAIN_ACCOUNT = 'antigravity'
KEYRING_PREFIX = 'go-keyring-base64:'
USAGE_TIMEOUT = 40


# ───────────────────────── السجل (profiles.json) ─────────────────────────

def load_registry(path=None):
    """يقرأ profiles.json؛ يعيد قاموساً بالمفاتيح main و profiles و العتبات، مع قيم احتياطية إن غاب الملف."""
    path = path or REGISTRY_PATH
    reg = {
        'main': MAIN_ACCOUNT,
        'transcribe_pool_min_5h_pct': 8.0,
        'transcribe_pool_min_weekly_pct': 2.0,
        'groups': {},
        'profiles': {
            MAIN_ACCOUNT: {'email': None, 'tier': 'Ultra', 'role': 'main', 'aliases': [MAIN_ACCOUNT]},
            **{n: {'email': None, 'tier': 'Pro', 'role': 'transcribe', 'aliases': [n]} for n in DEFAULT_TRANSCRIBE_PRO_POOL},
        },
    }
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
        reg['main'] = data.get('main', reg['main'])
        for k in ('transcribe_pool_min_5h_pct', 'transcribe_pool_min_weekly_pct'):
            if k in data:
                reg[k] = float(data[k])
        if isinstance(data.get('profiles'), dict) and data['profiles']:
            reg['profiles'] = data['profiles']
        if isinstance(data.get('groups'), dict):
            reg['groups'] = data['groups']
    except (OSError, ValueError):
        pass
    return reg


def main_account():
    return load_registry()['main']


def group_chain(group):
    """أعضاء مجموعة (مثل family) القابلون للتناوب بترتيب failover_order (الحالة active فقط)."""
    profs = load_registry()['profiles']
    members = [
        (m.get('failover_order', 999), n) for n, m in profs.items()
        if m.get('group') == group and m.get('role') == 'family-member' and m.get('status', 'active') == 'active'
    ]
    return [n for _, n in sorted(members)]


def transcribe_slots():
    """«خانات» التفريغ: كل خانة سلسلة مرشحين (الأول هو المفضّل، والبقية احتياط عند تعثّره).
    حساب role=transcribe مستقل = خانة بمرشح واحد؛ ومجموعة use_for=transcribe (العائلة) = خانة واحدة بسلسلة،
    لأن حصة أعضائها مشتركة فلا يُفاضَل بينهم بالكوتة بل بالترتيب والسلامة."""
    reg = load_registry()
    profs = reg['profiles']
    slots = [[n] for n, p in profs.items() if p.get('role') == 'transcribe' and p.get('status', 'active') == 'active']
    for g, meta in (reg.get('groups') or {}).items():
        if meta.get('use_for') == 'transcribe':
            chain = group_chain(g)
            if chain:
                slots.append(chain)
    return slots or [[n] for n in DEFAULT_TRANSCRIBE_PRO_POOL]


def transcribe_pool():
    """أسماء المرشحين المفضّلين (رأس كل خانة)."""
    return tuple(s[0] for s in transcribe_slots())


def profile_meta(name):
    return load_registry()['profiles'].get(name, {'email': None, 'tier': None, 'role': 'unassigned', 'aliases': [name]})


def role_label(name):
    meta = profile_meta(name)
    role, status = meta.get('role'), meta.get('status', 'active')
    if role == 'main':
        label = 'Main (Ultra)'
    elif role == 'transcribe':
        label = 'Default Transcribe (Pro)'
    elif role == 'family-manager':
        label = 'Family Manager'
    elif role == 'family-member':
        label = 'Family Member #%s' % meta.get('failover_order', '?')
    else:
        label = 'Unassigned'
    if status != 'active':
        label += ' — ' + status.upper()
    return label


# ───────────────────────── التوكنات و Keychain ─────────────────────────

def token_path(pdir):
    return os.path.join(pdir, '.gemini', 'antigravity-cli', 'antigravity-oauth-token')


def read_token_file(pdir):
    """يقرأ ملف التوكن كقاموس، أو None إن غاب/تلف."""
    try:
        with open(token_path(pdir), encoding='utf-8') as f:
            d = json.load(f)
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


def email_from_token_dict(tok):
    try:
        idt = tok.get('id_token', '')
        if idt and '.' in idt:
            payload = idt.split('.')[1]
            payload += '=' * (-len(payload) % 4)
            claims = json.loads(base64.urlsafe_b64decode(payload))
            return claims.get('email') or None
    except Exception:
        pass
    return None


def token_expiry(tok):
    """يعيد datetime (UTC-aware) لانتهاء access_token، أو None."""
    try:
        s = tok['token']['expiry']
        # Go يكتب كسر الثانية بأطوال متغيرة (5 أو 9 خانات) بينما fromisoformat في بايثون 3.9 يقبل 3 أو 6 فقط
        s = re.sub(r'\.(\d+)', lambda m: '.' + m.group(1)[:6].ljust(6, '0'), s)
        dt = datetime.fromisoformat(s.replace('Z', '+00:00'))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def decode_keyring_value(raw):
    """يفك قيمة Keychain بتنسيق go-keyring-base64:<base64(json)> (أو JSON خام) إلى قاموس، أو None."""
    raw = (raw or '').strip()
    if not raw:
        return None
    try:
        if raw.startswith(KEYRING_PREFIX):
            raw = base64.b64decode(raw[len(KEYRING_PREFIX):]).decode('utf-8')
        d = json.loads(raw)
        return d if isinstance(d, dict) else None
    except Exception:
        return None


def keychain_exists():
    if sys.platform != 'darwin':
        return False
    r = subprocess.run(
        ['security', 'find-generic-password', '-s', KEYCHAIN_SERVICE, '-a', KEYCHAIN_ACCOUNT],
        capture_output=True, stdin=subprocess.DEVNULL
    )
    return r.returncode == 0


def read_keychain_token():
    """يقرأ توكن Keychain المشترك (إن وُجد) كقاموس. لا يطبع شيئاً من محتواه."""
    if sys.platform != 'darwin':
        return None
    r = subprocess.run(
        ['security', 'find-generic-password', '-s', KEYCHAIN_SERVICE, '-a', KEYCHAIN_ACCOUNT, '-w'],
        capture_output=True, text=True, stdin=subprocess.DEVNULL
    )
    if r.returncode != 0:
        return None
    return decode_keyring_value(r.stdout)


def delete_keychain_entry():
    if sys.platform == 'darwin':
        subprocess.run(
            ['security', 'delete-generic-password', '-s', KEYCHAIN_SERVICE, '-a', KEYCHAIN_ACCOUNT],
            capture_output=True, stdin=subprocess.DEVNULL
        )


def _write_token_atomic(pdir, tok):
    """يكتب التوكن JSON بصلاحيات 600 مع نسخة احتياطية من القديم."""
    dest = token_path(pdir)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    if os.path.exists(dest):
        shutil.copy2(dest, dest + '.bak.' + time.strftime('%Y%m%d-%H%M%S'))
    tmp = dest + '.tmp'
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        json.dump(tok, f)
    os.replace(tmp, dest)
    os.chmod(dest, 0o600)


def email_hash(email):
    """بصمة SHA-256 للبريد (بحروف صغيرة) — تسمح بتسجيل الحساب في مستودع عام دون كشف بريده."""
    return hashlib.sha256((email or '').strip().lower().encode('utf-8')).hexdigest()


def meta_has_email(meta):
    return bool(meta.get('email') or meta.get('email_sha256'))


def meta_email_matches(meta, email):
    """يطابق بريداً بما في السجل: email صريح، أو email_sha256 (للحسابات غير المعلنة)."""
    if not email:
        return False
    if meta.get('email'):
        return meta['email'].lower() == email.lower()
    if meta.get('email_sha256'):
        return meta['email_sha256'].lower() == email_hash(email)
    return False


def find_owner_profile(email, profiles):
    """يجد البروفايل صاحب البريد: أولاً من السجل، ثم من ملفات التوكن الفعلية."""
    if not email:
        return None
    reg = load_registry()['profiles']
    for name, meta in reg.items():
        if meta_email_matches(meta, email):
            return name
    for name, pdir in profiles:
        tok = read_token_file(pdir)
        if tok and (email_from_token_dict(tok) or '').lower() == email.lower():
            return name
    return None


def reconcile_keychain(delete=False, dry_run=False, keychain_tok=None):
    """ينسب توكن Keychain المشترك إلى البروفايل صاحبه بحسب البريد (لا بحسب من شُغّل آخراً).

    - يكتب الملف فقط إذا كان توكن البروفايل مفقوداً/تالفاً أو كان توكن Keychain أحدث (انتهاء أبعد).
    - لا يحذف إدخال Keychain إلا مع delete=True وبعد التأكد أن نسخة البروفايل محدَّثة وبنفس البريد.
    يعيد قاموساً بالنتيجة: status ∈ none|unowned|unchanged|updated|would-update، و profile و email.
    """
    kc = keychain_tok if keychain_tok is not None else read_keychain_token()
    if not kc:
        return {'status': 'none'}
    email = email_from_token_dict(kc)
    profiles = list_profiles(register_default=False)
    owner = find_owner_profile(email, profiles)
    if not owner:
        return {'status': 'unowned', 'email': email}
    pdir = os.path.join(PROFILES_ROOT, owner)
    cur = read_token_file(pdir)
    kc_exp, cur_exp = token_expiry(kc), token_expiry(cur or {})
    need = (cur is None) or (email_from_token_dict(cur) != email) or (
        kc_exp is not None and (cur_exp is None or kc_exp > cur_exp)
    )
    result = {'status': 'unchanged', 'profile': owner, 'email': email}
    if need:
        result['status'] = 'would-update' if dry_run else 'updated'
        if not dry_run:
            _write_token_atomic(pdir, kc)
    if delete and not dry_run:
        fresh = read_token_file(pdir)
        if fresh and email_from_token_dict(fresh) == email:
            delete_keychain_entry()
            result['deleted'] = True
    return result


def ensure_default_profile_registered():
    """يتأكد من نسخ الحساب الأساسي ~/.gemini إلى ~/.agy-profiles/<main> إن لم يكن موجوداً. لا يلمس Keychain."""
    default_cli = os.path.expanduser('~/.gemini/antigravity-cli')
    main_cli = os.path.join(PROFILES_ROOT, main_account(), '.gemini', 'antigravity-cli')
    if os.path.exists(os.path.join(default_cli, 'antigravity-oauth-token')) and not os.path.exists(
        os.path.join(main_cli, 'antigravity-oauth-token')
    ):
        os.makedirs(main_cli, exist_ok=True)
        for fname in ('antigravity-oauth-token', 'jetski_state.pbtxt', 'settings.json'):
            src = os.path.join(default_cli, fname)
            if os.path.exists(src):
                shutil.copy2(src, os.path.join(main_cli, fname))


def list_profiles(register_default=True):
    if register_default:
        ensure_default_profile_registered()
    if not os.path.isdir(PROFILES_ROOT):
        return []
    out = []
    for name in sorted(os.listdir(PROFILES_ROOT)):
        pdir = os.path.join(PROFILES_ROOT, name)
        if name.startswith('.'):
            continue
        if os.path.isdir(pdir) and os.path.exists(token_path(pdir)):
            out.append((name, pdir))
    return out


def extract_email_from_token_file(pdir):
    tok = read_token_file(pdir)
    return (email_from_token_dict(tok) if tok else None) or 'unknown'


# ───────────────────────── فحص الكوتة (/usage) ─────────────────────────

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


def run_agy(pdir, args, timeout=USAGE_TIMEOUT):
    """يشغّل agy ببروفايل معزول وstdin=DEVNULL (وإلا يتجمد مع الأنابيب). يعيد (stdout, stderr, returncode|None عند المهلة)."""
    env = os.environ.copy()
    env['HOME'] = pdir
    try:
        r = subprocess.run(
            [AGY_BIN] + list(args), env=env, capture_output=True, text=True,
            timeout=timeout, stdin=subprocess.DEVNULL
        )
        return r.stdout or '', r.stderr or '', r.returncode
    except subprocess.TimeoutExpired as e:
        out = e.stdout.decode('utf-8', 'ignore') if isinstance(e.stdout, bytes) else (e.stdout or '')
        err = e.stderr.decode('utf-8', 'ignore') if isinstance(e.stderr, bytes) else (e.stderr or '')
        return out, err, None


DISABLED_MARKERS = ('permission_denied', 'code 403', 'disabled in this account', 'submit an appeal',
                    'violation of terms', 'not eligible for antigravity')


def is_disabled_text(text):
    """يكشف رسالة تعطيل الحساب من جوجل (403 / مخالفة الشروط)."""
    low = (text or '').lower()
    return any(m in low for m in DISABLED_MARKERS)


def fetch_usage(pdir, retries=1):
    """يجلب الكوتة الحية (0 توكن) مع إعادة محاولة واحدة. يعيد (quota_dict, error|None).
    الخطأ 'disabled' يعني أن الحساب معطّل من جوجل (لا إعادة محاولة)."""
    last_err = None
    for _ in range(retries + 1):
        out, err, rc = run_agy(pdir, ['-p', '/usage', '--output-format', 'json'])
        if is_disabled_text(out + ' ' + err):
            return {}, 'disabled'
        if out.strip().startswith('{'):
            try:
                d = json.loads(out)
                q = parse_usage_response(d.get('response', ''))
                if q['gemini_weekly_pct'] is not None or q['gemini_5h_pct'] is not None:
                    return q, None
                last_err = 'usage-response-empty'
                continue
            except ValueError:
                last_err = 'usage-json-invalid'
                continue
        last_err = 'timeout' if rc is None else ('rc=%s %s' % (rc, (err or out).strip()[:120]))
    return {}, last_err


def inspect_profile(name, pdir, include_models=True):
    meta = profile_meta(name)
    tok = read_token_file(pdir)
    token_email = (email_from_token_dict(tok) if tok else None) or 'unknown'
    exp = token_expiry(tok or {})
    info = {
        'profile': name,
        'role': role_label(name),
        'home': pdir,
        'email': token_email,
        'tier': meta.get('tier') or ('Ultra' if name == main_account() else 'Pro'),
        'has_argon': name == main_account(),
        'models': [],
        'quota': {},
        'token_expiry': exp.isoformat() if exp else None,
    }
    if meta_has_email(meta) and token_email != 'unknown' and not meta_email_matches(meta, token_email):
        info['email_mismatch'] = {'registry': meta.get('email') or '(sha256)', 'token': token_email}

    quota, err = fetch_usage(pdir)
    info['quota'] = quota
    if err:
        info['error'] = err

    if include_models:
        try:
            out, _, _ = run_agy(pdir, ['models'], timeout=30)
            models = []
            for line in out.splitlines():
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


def inspect_many(profiles, include_models=False, max_workers=4):
    """يفحص عدة بروفايلات بالتوازي مع الحفاظ على ترتيب الإدخال."""
    if not profiles:
        return []
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(max_workers, len(profiles))) as ex:
        futs = [ex.submit(inspect_profile, n, p, include_models) for n, p in profiles]
        return [f.result() for f in futs]


def _probe_slot(chain, min_5h_pct, min_weekly_pct):
    """يفحص خانة تفريغ: يجرّب مرشحيها بالترتيب ويأخذ أول سليم (بلا خطأ فحص). الأعضاء المتخطَّون يُسجَّلون
    في failover_from. التعثّر (حظر/عدم أهلية/مهلة) هو وحده ما يسبّب القفز للتالي، أما انخفاض الكوتة فلا يسبّبه
    لأن حصة أعضاء العائلة مشتركة (القفز لا يزيد السعة)."""
    skipped, last = [], None
    for name in chain:
        pdir = os.path.join(PROFILES_ROOT, name)
        if not os.path.exists(token_path(pdir)):
            skipped.append(name)
            continue
        info = inspect_profile(name, pdir, include_models=False)
        q = info.get('quota') or {}
        g5 = float(q.get('gemini_5h_pct') if q.get('gemini_5h_pct') is not None else 0.0)
        gw = float(q.get('gemini_weekly_pct') if q.get('gemini_weekly_pct') is not None else 0.0)
        entry = {
            'profile': name,
            'home': pdir,
            'email': info['email'],
            'gemini_5h_pct': g5,
            'gemini_weekly_pct': gw,
            'gemini_weekly_reset': q.get('gemini_weekly_reset', ''),
            'eligible': (g5 >= min_5h_pct) and (gw >= min_weekly_pct) and not info.get('error'),
            'error': info.get('error'),
            'failover_from': list(skipped),
        }
        last = entry
        if not info.get('error'):
            return entry
        skipped.append(name)
    return last


def pick_best_pro_for_transcription(min_5h_pct=None, min_weekly_pct=None):
    """يختار تلقائياً حساب التفريغ صاحب الكوتة الأسبوعية الأعلى بين «الخانات» المستقلة
    (حسابات role=transcribe + مجموعة العائلة كخانة واحدة بتناوب failover_order عند تعثّر الحساب)."""
    reg = load_registry()
    min_5h_pct = reg['transcribe_pool_min_5h_pct'] if min_5h_pct is None else min_5h_pct
    min_weekly_pct = reg['transcribe_pool_min_weekly_pct'] if min_weekly_pct is None else min_weekly_pct
    slots = transcribe_slots()
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(4, len(slots))) as ex:
        probed = list(ex.map(lambda c: _probe_slot(c, min_5h_pct, min_weekly_pct), slots))
    candidates = [c for c in probed if c]
    # الترتيب: المؤهل أولاً، ثم الأعلى في الكوتة الأسبوعية (gemini_weekly_pct)، ثم الأعلى في كوتة الـ 5 ساعات
    candidates.sort(
        key=lambda c: (1 if c['eligible'] else 0, c['gemini_weekly_pct'], c['gemini_5h_pct']),
        reverse=True
    )
    return candidates


# ───────────────────────── الأوامر ─────────────────────────

def find_shared_quota_groups(results, pct_tol=1.0):
    """يكتشف الحسابات التي تقرأ من حصة واحدة مشتركة: نفس لحظة تجديد الأسبوعي (Gemini و Claude) بالثانية
    ونسبة أسبوعية متقاربة. حسابان مستقلان لا يتطابقان بالثانية عادةً. يعيد قائمة مجموعات (قوائم أسماء) حجمها ≥ 2."""
    buckets = {}
    for r in results:
        q = r.get('quota') or {}
        gr, cr, gw = q.get('gemini_weekly_reset'), q.get('claude_weekly_reset'), q.get('gemini_weekly_pct')
        if not gr or not cr or gw is None:
            continue
        buckets.setdefault((gr, cr), []).append((r['profile'], gw))
    groups = []
    for members in buckets.values():
        if len(members) < 2:
            continue
        lo, hi = min(m[1] for m in members), max(m[1] for m in members)
        if hi - lo <= pct_tol:
            groups.append(sorted(m[0] for m in members))
    return groups


def mark_shared_quota(results):
    """يضيف حقل shared_quota_with لكل نتيجة تنتمي لمجموعة حصة مشتركة."""
    for grp in find_shared_quota_groups(results):
        for r in results:
            if r['profile'] in grp:
                r['shared_quota_with'] = [n for n in grp if n != r['profile']]
    return results


def cmd_status(as_json=False):
    profiles = list_profiles()
    results = mark_shared_quota(inspect_many(profiles, include_models=False))
    if as_json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return results

    for r in results:
        q = r.get('quota') or {}
        g5 = f"{q.get('gemini_5h_pct')}%" if q.get('gemini_5h_pct') is not None else 'N/A'
        gw = f"{q.get('gemini_weekly_pct')}%" if q.get('gemini_weekly_pct') is not None else 'N/A'
        c5 = f"{q.get('claude_5h_pct')}%" if q.get('claude_5h_pct') is not None else 'N/A'
        cw = f"{q.get('claude_weekly_pct')}%" if q.get('claude_weekly_pct') is not None else 'N/A'
        flag = ''
        if r.get('shared_quota_with'):
            flag += ' ⛓ حصة مشتركة مع: ' + ','.join(r['shared_quota_with'])
        if r.get('email_mismatch'):
            flag += f" ⚠ البريد لا يطابق السجل ({r['email_mismatch']['registry']})"
        if r.get('error') == 'disabled':
            flag += ' 🚨 الحساب معطّل أو غير مؤهل من جوجل (403 / Verify your account) — لا تستخدمه'
        elif r.get('error'):
            flag += f" ⚠ فشل فحص الكوتة: {r['error']}"
        print(
            f"• {r['profile']} ({r['email']}) [{r['role']}] -> "
            f"Gemini Weekly={gw} (5h={g5}) | Claude Weekly={cw} (5h={c5}){flag}"
        )
    best = pick_best_pro_for_transcription()
    if best:
        fo = best[0].get('failover_from')
        extra = f" (قُفز عن: {','.join(fo)})" if fo else ''
        print(f"★ الحساب المختار للتفريغ الآن (الأعلى كوتة أسبوعية بين الخانات المستقلة): {best[0]['profile']} ({best[0]['gemini_weekly_pct']}%){extra}")
    return results


def cmd_doctor(as_json=False):
    """فحص صحة بدون أي تعديل. يعيد (قائمة_النتائج، عدد_المشاكل)."""
    reg = load_registry()
    findings = []

    def add(level, profile, msg):
        findings.append({'level': level, 'profile': profile, 'message': msg})

    on_disk = {n: p for n, p in list_profiles(register_default=False)}
    for name, meta in reg['profiles'].items():
        pdir = os.path.join(PROFILES_ROOT, name)
        if name not in on_disk:
            add('error', name, 'مسجّل في profiles.json لكن لا يوجد له ملف توكن (سجّل الدخول بـ /login).')
            continue
        tok = read_token_file(pdir)
        if tok is None:
            add('error', name, 'ملف التوكن تالف أو ليس JSON (قد يكون كُتب بتنسيق Keychain الخام). استعده بـ: --restore %s' % name)
            continue
        mode = oct(os.stat(token_path(pdir)).st_mode & 0o777)
        if mode != '0o600':
            add('warn', name, f'صلاحيات ملف التوكن {mode} والمطلوب 0o600.')
        email = email_from_token_dict(tok)
        if meta_has_email(meta) and email and not meta_email_matches(meta, email):
            add('error', name, f'التوكن لحساب {email} بينما السجل يقول {meta.get("email") or "(بصمة sha256)"} (توكن في بروفايل خطأ؟).')
        if not meta_has_email(meta):
            add('warn', name, f'لا بريد مسجّل في profiles.json (التوكن: {email}).')
        if meta.get('role', 'unassigned') == 'unassigned':
            add('info', name, 'دور غير محدّد (unassigned) في profiles.json.')
        if meta.get('status', 'active') != 'active':
            add('info', name, f'الحالة {meta["status"]} — خارج التناوب ({meta.get("note", "")}).')
    for name in on_disk:
        if name not in reg['profiles']:
            add('warn', name, 'بروفايل على القرص غير مسجّل في profiles.json.')

    # تكرار البريد بين بروفايلين = توكن منسوخ بالخطأ
    seen = {}
    for name, pdir in on_disk.items():
        e = (email_from_token_dict(read_token_file(pdir) or {}) or '').lower()
        if e:
            seen.setdefault(e, []).append(name)
    for e, names in seen.items():
        if len(names) > 1:
            add('error', ','.join(names), f'نفس البريد {e} في أكثر من بروفايل.')

    kc = read_keychain_token() if keychain_exists() else None
    if kc is not None:
        e = email_from_token_dict(kc)
        owner = find_owner_profile(e, list(on_disk.items()))
        add('info', owner or '-', f'يوجد إدخال في Keychain المشترك لحساب {e} (صاحبه: {owner or "غير معروف"}). '
                                  'هذا طبيعي إن كانت جلسة agy الافتراضية (بدون alias) مفتوحة.')
    elif keychain_exists():
        add('warn', '-', 'يوجد إدخال Keychain لكن تنسيقه غير مفهوم.')

    problems = sum(1 for f in findings if f['level'] in ('error', 'warn'))
    if as_json:
        print(json.dumps(findings, ensure_ascii=False, indent=2))
    else:
        icon = {'error': '✗', 'warn': '!', 'info': 'i'}
        for f in findings:
            print(f"[{icon[f['level']]}] {f['profile']}: {f['message']}")
        print(f'— {len(on_disk)} بروفايل على القرص، {problems} مشكلة/تحذير.')
    return findings, problems


def cmd_reconcile(delete=False, dry_run=False, quiet=False):
    res = reconcile_keychain(delete=delete, dry_run=dry_run)
    if not quiet:
        print(json.dumps(res, ensure_ascii=False))
    return res


def backups_root():
    return os.path.join(PROFILES_ROOT, '.backups')


def cmd_backup():
    """ينسخ توكنات كل البروفايلات إلى ~/.agy-profiles/.backups/<الوقت>/<profile>.token بصلاحيات 600. يعيد المسار."""
    dest = os.path.join(backups_root(), time.strftime('%Y%m%d-%H%M%S'))
    os.makedirs(dest, mode=0o700, exist_ok=True)
    n = 0
    for name, pdir in list_profiles(register_default=False):
        out = os.path.join(dest, name + '.token')
        shutil.copy2(token_path(pdir), out)
        os.chmod(out, 0o600)
        n += 1
    print(f'[✓ نسخ احتياطي] {n} توكن -> {dest}')
    return dest


def cmd_restore(profile, from_dir=None):
    """يستعيد توكن بروفايل من أحدث نسخة احتياطية (أو من --from)، بعد حفظ الحالي بجانبه."""
    root = backups_root()
    if from_dir is None:
        dirs = sorted(d for d in (os.listdir(root) if os.path.isdir(root) else []) if os.path.exists(os.path.join(root, d, profile + '.token')))
        if not dirs:
            raise SystemExit(f'لا توجد نسخة احتياطية للبروفايل {profile} في {root}')
        from_dir = os.path.join(root, dirs[-1])
    src = os.path.join(from_dir, profile + '.token')
    try:
        with open(src, encoding='utf-8') as f:
            tok = json.load(f)
    except (OSError, ValueError):
        raise SystemExit(f'نسخة احتياطية غير صالحة: {src}')
    _write_token_atomic(os.path.join(PROFILES_ROOT, profile), tok)
    print(f'[✓ استعادة] {profile} من {src} (بريد: {email_from_token_dict(tok)})')


def cmd_run(profile, args):
    """تشغيل agy ببروفايل معزول (stdin/stdout موروثان للجلسات التفاعلية) ثم مصالحة Keychain بحسب البريد."""
    pdir = os.path.join(PROFILES_ROOT, profile)
    os.makedirs(os.path.join(pdir, '.gemini', 'antigravity-cli'), exist_ok=True)
    env = os.environ.copy()
    env['HOME'] = pdir
    rc = subprocess.call([AGY_BIN] + list(args), env=env)
    try:
        reconcile_keychain(delete=False)
    except Exception as e:
        print(f'[تحذير] تعذرت مصالحة Keychain: {e}', file=sys.stderr)
    return rc


def render_aliases():
    """يولّد كود zsh: دالة _agy_profile_run + aliases من profiles.json."""
    script = os.path.abspath(__file__)
    lines = [
        '# مولَّد تلقائياً من agy-multi-account/profiles.json — لا تعدّله يدوياً.',
        '# أعد توليده بـ: python3 %s --print-aliases > ~/.agy-aliases.zsh' % shlex.quote(script),
        '_agy_profile_run() {',
        '  local prof="$1"; shift',
        '  local pdir="%s/${prof}"' % PROFILES_ROOT,
        '  mkdir -p "${pdir}/.gemini/antigravity-cli"',
        '  HOME="${pdir}" agy "$@"',
        '  local rc=$?',
        '  # مصالحة Keychain بحسب البريد (تنسب التوكن لصاحبه ولا تحذف شيئاً)',
        '  python3 %s --reconcile-keychain --quiet >/dev/null 2>&1 || true' % shlex.quote(script),
        '  return $rc',
        '}',
    ]
    for name, meta in load_registry()['profiles'].items():
        for a in meta.get('aliases') or [name]:
            lines.append("alias %s='_agy_profile_run %s'" % (a, name))
    return '\n'.join(lines) + '\n'


def cmd_sync_to_vps(vps_host='hermes-vps'):
    profiles = list_profiles()
    if not profiles:
        print('لا توجد بروفايلات في ~/.agy-profiles للمزامنة.')
        return
    for name, pdir in profiles:
        remote_dir = f'/root/.agy-profiles/{name}/.gemini/antigravity-cli'
        subprocess.run(['ssh', vps_host, 'mkdir -p %s && chmod 700 %s' % (shlex.quote(remote_dir), shlex.quote(remote_dir))], check=True)
        files_to_copy = []
        for fn in ('antigravity-oauth-token', 'jetski_state.pbtxt', 'settings.json', 'installation_id'):
            fp = os.path.join(pdir, '.gemini', 'antigravity-cli', fn)
            if os.path.exists(fp):
                files_to_copy.append(fp)
        if files_to_copy:
            subprocess.run(['scp', '-q'] + files_to_copy + [f'{vps_host}:{remote_dir}/'], check=True)
            subprocess.run(['ssh', vps_host, 'chmod 600 %s/antigravity-oauth-token' % shlex.quote(remote_dir)], check=False)
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


def main(argv=None):
    ap = argparse.ArgumentParser(description='إدارة الحسابات المتعددة لـ agy')
    ap.add_argument('--status', action='store_true', help='فحص حالة وكوتة جميع البروفايلات')
    ap.add_argument('--best-transcribe-profile', action='store_true', help='إرجاع حساب الـ Pro صاحب أعلى كوتة أسبوعية للتفريغ')
    ap.add_argument('--json', action='store_true', help='إخراج JSON')
    ap.add_argument('--sync-to-vps', action='store_true', help='مزامنة البروفايلات إلى hermes-vps')
    ap.add_argument('--calibrate', metavar='PROFILE', help='معايرة كوتة بروفايل محدد بتفريغ درس واحد')
    ap.add_argument('--series-dir', help='مسار السلسلة للمعايرة')
    ap.add_argument('--only', help='رقم الدرس للمعايرة (مثل 012)')
    ap.add_argument('--model', default='gemini-3.8-flash-high', help='النموذج المستخدم')
    ap.add_argument('--doctor', action='store_true', help='فحص صحة البروفايلات والسجل و Keychain (بدون تعديل)')
    ap.add_argument('--reconcile-keychain', action='store_true', help='نسب توكن Keychain إلى صاحبه بحسب البريد')
    ap.add_argument('--delete', action='store_true', help='مع --reconcile-keychain: احذف إدخال Keychain بعد التأكد من حفظه')
    ap.add_argument('--dry-run', action='store_true', help='مع --reconcile-keychain: اعرض ما سيحدث فقط')
    ap.add_argument('--quiet', action='store_true', help='بدون مخرجات (للاستدعاء من الـ alias)')
    ap.add_argument('--run', metavar='PROFILE', help='تشغيل agy ببروفايل معزول؛ مرّر وسائط agy بعد --')
    ap.add_argument('--backup', action='store_true', help='نسخ احتياطي لتوكنات كل البروفايلات إلى ~/.agy-profiles/.backups/')
    ap.add_argument('--restore', metavar='PROFILE', help='استعادة توكن بروفايل من أحدث نسخة احتياطية')
    ap.add_argument('--from', dest='from_dir', help='مع --restore: مجلد نسخة محددة')
    ap.add_argument('--print-aliases', action='store_true', help='طباعة دوال/aliases الـ zsh المولّدة من profiles.json')
    args, rest = ap.parse_known_args(argv)
    if rest and rest[0] == '--':
        rest = rest[1:]

    if args.run:
        return cmd_run(args.run, rest)
    if rest:
        ap.error('وسائط غير معروفة: ' + ' '.join(rest))

    if args.print_aliases:
        sys.stdout.write(render_aliases())
    elif args.backup:
        cmd_backup()
    elif args.restore:
        cmd_restore(args.restore, args.from_dir)
    elif args.doctor:
        _, problems = cmd_doctor(as_json=args.json)
        return 1 if problems else 0
    elif args.reconcile_keychain:
        cmd_reconcile(delete=args.delete, dry_run=args.dry_run, quiet=args.quiet)
    elif args.sync_to_vps:
        cmd_sync_to_vps()
    elif args.best_transcribe_profile:
        cands = pick_best_pro_for_transcription()
        if args.json:
            print(json.dumps(cands, ensure_ascii=False, indent=2))
        elif cands:
            if not cands[0]['eligible']:
                print('[تحذير] لا يوجد حساب مؤهل (الكوتة منخفضة أو فشل الفحص)؛ أُعيد الأعلى نسبةً فقط.', file=sys.stderr)
            print(cands[0]['profile'])
        else:
            print(DEFAULT_TRANSCRIBE_PRO_POOL[0])
    elif args.calibrate:
        if not args.series_dir or not args.only:
            ap.error('--calibrate يتطلب --series-dir و --only')
        cmd_calibrate(args.calibrate, args.series_dir, args.only, args.model)
    else:
        cmd_status(as_json=args.json)
    return 0


if __name__ == '__main__':
    sys.exit(main())
