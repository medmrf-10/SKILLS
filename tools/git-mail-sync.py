#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tools/git-mail-sync.py — جسر Git ← Gmail: كل المحتوى **نص صريح داخل جسم الرسالة** (بلا أي مرفقات).

يُستدعى آليًا من خطافات git في المستودع، أو يدويًا:
    python3 tools/git-mail-sync.py --trigger commit      # حالة الالتزام HEAD (يُستدعى من post-commit)
    python3 tools/git-mail-sync.py --trigger push        # يُستدعى من pre-push (لفرع main)
    python3 tools/git-mail-sync.py --test                # رسالة اختبار الآن (تتجاوز كتم التكرار)
    python3 tools/git-mail-sync.py --dry-run             # يطبع الرسالة بلا إرسال

البنية الملزمة (مواصفة المالك ٢٠٢٦-١٠-١٥):
    Subject: [GIT-SYNC] skills | <short-sha> | <commit-summary>
    Body :  (أ) شجرة ملفات المستودع الحالية
            (ب) آخر ٣ التزامات مع الإحصاءات      ⇐ git log -n 3 --stat
            (ج) الفروق الدقيقة للتعديل الأخير     ⇐ git show --stat --patch HEAD
            (د) المحتوى الكامل لملفات هذا الالتزام ⇐ ترويسة === FILE: path/to/file ===

الإرسال عبر `gws` (Gmail API، مصادَق على هذا الخادم بمفتاح keyring — بلا كلمة مرور تطبيقات).
"""
import argparse
import base64
import json
import os
import subprocess
import sys
import tempfile
import time
from email.header import Header
from email.message import EmailMessage

REPO_DEFAULT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TO_DEFAULT = 'medmrf.10@gmail.com'
SEP = '─' * 68
SUBSEP = '·' * 68
BODY_LIMIT = 9_000_000          # سقف جسم الرسالة (سقف Gmail 25MB — نبقى بعيدًا)
TRIGGERS = ('commit', 'merge', 'rewrite', 'push', 'test', 'manual')


def sh(cmd, repo):
    p = subprocess.run(cmd, cwd=repo, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return p.stdout.decode('utf-8', 'replace').rstrip('\n')


def render_tree(paths):
    tree = {}
    for p in paths:
        cur = tree
        parts = p.split('/')
        for part in parts[:-1]:
            cur = cur.setdefault(part, {})
        cur.setdefault('\x00files', []).append(parts[-1])
    lines = []

    def walk(node, depth):
        for d in sorted(k for k in node if k != '\x00files'):
            lines.append('  ' * depth + d + '/')
            walk(node[d], depth + 1)
        for f in sorted(node.get('\x00files', [])):
            lines.append('  ' * depth + f)

    walk(tree, 0)
    return lines


def head_info(repo, sha):
    fmt = '%h%x1f%s%x1f%an%x1f%ad%x1f%h %s'
    out = sh(['git', 'show', '-s', '--date=format:%Y-%m-%d %H:%M', '--format=' + fmt, sha], repo).split('\x1f')
    return dict(short=out[0], summary=out[1], author=out[2], date=out[3], full_subject=out[4])


def changed_files(repo, sha):
    rows, codes = [], {}
    out = sh(['git', 'diff-tree', '--no-commit-id', '--name-status', '-r', sha], repo)
    for line in out.split('\n'):
        parts = line.split('\t')
        if len(parts) < 2:
            continue
        code, path = parts[0][:1], parts[-1]
        rows.append(path)
        codes[path] = code
    return rows, codes


def file_body(repo, sha, path, cap):
    txt = sh(['git', 'show', '%s:%s' % (sha, path)], repo)
    if len(txt) > cap:
        txt = txt[:cap] + '\n… [اقتُطع: تجاوز %d حرفًا — راجع git show %s:%s]' % (cap, sha[:7], path)
    return txt


def build(repo, to, sha, trigger, cap):
    hi = head_info(repo, sha)
    tracked = sh(['git', 'ls-files'], repo).split('\n')
    tracked = [t for t in tracked if t]
    files, codes = changed_files(repo, sha)
    branch = sh(['git', 'rev-parse', '--abbrev-ref', 'HEAD'], repo)
    dirty = sh(['git', 'status', '--porcelain'], repo).split('\n')
    dirty = [d for d in dirty if d]

    summary = ' '.join(hi['summary'].split())[:120]
    # الوسم الثابت يبقى ASCII غير مُرمَّز (لتعمل فلاتر Gmail)، والعربي يُرمَّز RFC2047 بلا أي طيّ أسطر
    enc = ' '.join(Header(summary, 'utf-8').encode().split())
    subject = '[GIT-SYNC] skills | %s | %s' % (hi['short'], enc)
    L = []
    L.append('جسر Git ← Gmail لمستودع المهارات — نص صريح في الجسم، بلا أي مرفقات.')
    L.append(SEP)
    L.append('المستودع : %s' % repo)
    L.append('الفرع    : %s   |   الالتزام: %s   |   المُشغِّل: %s' % (branch, hi['full_subject'], trigger))
    L.append('المؤلف    : %s   |   التاريخ: %s' % (hi['author'], hi['date']))
    if dirty:
        L.append('شجرة العمل: %d تغييرًا غير مُلتزم (منها %d غير مُتتبَّع)' % (
            len(dirty), sum(1 for d in dirty if d.startswith('??'))))
        for d in dirty[:12]:
            L.append('            %s' % d)
    L.append('')
    L.append('أ) شجرة ملفات المستودع الحالية (المجموع: %d ملفًا مُتتبَّعًا)' % len(tracked))
    L.append(SUBSEP)
    L.extend(render_tree(tracked))
    L.append('')
    L.append('ب) آخر ٣ التزامات مع الإحصاءات')
    L.append(SUBSEP)
    L.append('$ git log -n 3 --stat')
    L.append(sh(['git', '--no-pager', 'log', '-n', '3', '--stat', '--date=format:%Y-%m-%d %H:%M'], repo))
    L.append('')
    L.append('ج) الفروق الدقيقة للتعديل الأخير')
    L.append(SUBSEP)
    L.append('$ git show --stat --patch HEAD')
    L.append(sh(['git', '--no-pager', 'show', '--stat', '--patch', sha], repo))
    L.append('')
    L.append('د) المحتوى الكامل للملفات المتغيّرة في هذا الالتزام (%d ملفًا)' % len(files))
    L.append(SUBSEP)
    for path in files:
        code = codes.get(path, 'M')
        L.append('=== FILE: %s ===   [%s]' % (path, code))
        if code == 'D':
            L.append('(محذوف في هذا الالتزام)')
        else:
            L.append(file_body(repo, sha, path, cap))
        L.append('=== END FILE: %s ===' % path)
        L.append('')
    L.append(SEP)
    L.append('أُرسلت آليًا من خطاف git على هذا الخادم · المُشغِّل: %s · %s' % (
        trigger, time.strftime('%Y-%m-%d %H:%M:%S')))
    return subject, '\n'.join(L)


def send_via_gws(to, subject, body, repo):
    """يُرسل عبر gws برفع multipart (message/rfc822) — لا يمرّ الجسم في argv إطلاقًا."""
    msg = EmailMessage()
    msg['To'] = to
    msg['From'] = to
    msg['Subject'] = subject
    msg.set_content(body, subtype='plain', charset='utf-8', cte='base64')
    # gws يفرض أن يكون --upload داخل مجلد العمل الحالي ⇒ نكتب الرسالة في .git/ ونُنفّذ من جذر المستودع
    fd, path = tempfile.mkstemp(suffix='.eml', prefix='git-mail-sync-', dir=os.path.join(repo, '.git'))
    with os.fdopen(fd, 'wb') as f:
        f.write(msg.as_bytes())
    try:
        p = subprocess.run(['gws', 'gmail', 'users', 'messages', 'send',
                            '--params', json.dumps({'userId': 'me', 'uploadType': 'multipart'}),
                            '--upload', os.path.relpath(path, repo),
                            '--upload-content-type', 'message/rfc822', '--json', '{}'],
                           cwd=repo, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        out = p.stdout.decode('utf-8', 'replace')
        if p.returncode != 0:
            return None, out[:500]
        i, j = out.find('{'), out.rfind('}')
        if i < 0 or j <= i:
            return None, out[:500]
        try:
            d = json.loads(out[i:j + 1])          # gws يبثّ سطر keyring قبل JSON
        except Exception:
            return None, out[:500]
        mid = d.get('id') or d.get('threadId')
        if not mid or 'error' in d:
            return None, json.dumps(d, ensure_ascii=False)[:400]
        return mid, out[i:j + 1][:200]
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def main():
    ap = argparse.ArgumentParser(description='جسر Git ← Gmail (نص صريح بلا مرفقات)')
    ap.add_argument('--repo', default=REPO_DEFAULT)
    ap.add_argument('--to', default=TO_DEFAULT)
    ap.add_argument('--trigger', default='manual', choices=TRIGGERS)
    ap.add_argument('--sha', default='HEAD')
    ap.add_argument('--test', action='store_true', help='رسالة اختبار (تُلغي كتم التكرار)')
    ap.add_argument('--force', action='store_true', help='أرسل حتى لو سبق إرسال نفس الالتزام')
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()
    repo = os.path.abspath(a.repo)
    if not os.path.isdir(os.path.join(repo, '.git')):
        print('ليس مستودع git: %s' % repo, file=sys.stderr)
        return 2
    trigger = 'test' if a.test else a.trigger
    if not a.sha or set(a.sha.strip()) == {'0'}:
        print('التزام الحذف/الفارغ — لا إرسال.')
        return 0
    sha = sh(['git', 'rev-parse', a.sha], repo) or a.sha
    state_path = os.path.join(repo, '.git', 'git-mail-sync.state.json')
    log_path = os.path.join(repo, '.git', 'git-mail-sync.log')
    state = {}
    if os.path.exists(state_path):
        try:
            state = json.load(open(state_path, encoding='utf-8'))
        except Exception:
            state = {}
    if not (a.force or a.test) and state.get('last_' + trigger) == sha:
        print('مُرسل سابقًا لهذا المُشغِّل (%s · %s) — تخطٍّ.' % (trigger, sha[:7]))
        return 0

    # سقف متكيّف: يضمن بقاء جسم الرسالة داخل سقف Gmail (٢٥MB) مع احتفاظه بالكامل عند الإمكان
    for cap in (400_000, 40_000):
        subject, body = build(repo, a.to, sha, trigger, cap)
        if len(body.encode('utf-8')) <= BODY_LIMIT or cap == 40_000:
            break
    if a.dry_run:
        print('Subject: %s\n%s\n[حجم الجسم: %d حرفًا ≈ %.0fKB]' % (subject, body[:3000], len(body), len(body.encode())/1024))
        return 0
    mid, info = send_via_gws(a.to, subject, body, repo)
    line = '%s | %s | %s | %s | %s | %s' % (
        time.strftime('%Y-%m-%d %H:%M:%S'), trigger, sha[:7],
        'OK' if mid else 'FAIL', mid or '-', subject)
    with open(log_path, 'a', encoding='utf-8') as f:
        f.write(line + '\n')
    if mid:
        state['last_' + trigger] = sha
        state['last'] = dict(sha=sha, trigger=trigger, at=time.strftime('%Y-%m-%d %H:%M:%S'), message_id=mid)
        json.dump(state, open(state_path, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print('أُرسلت ✓ message-id=%s | %s' % (mid, subject))
        print('المستلم: %s · حجم الجسم: %d حرفًا · المُشغِّل: %s' % (a.to, len(body), trigger))
        return 0
    print('فشل الإرسال ✗ %s' % info, file=sys.stderr)
    return 1


if __name__ == '__main__':
    sys.exit(main())
