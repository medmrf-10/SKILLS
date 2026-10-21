#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""chrome_session_audit.py — تدقيق للقراءة فقط لجلسات Google/YouTube في مثيلات Chrome الدائمة (CDP) على الـ VPS.

لا يطبع قيم الكوكيز أبداً (أسماء وتواريخ فقط)، ولا يفتح أي صفحة ولا يطلب شيئاً من يوتيوب/جوجل.
يعمل على الـ VPS بمفسّر فيه websocket-client:   /root/venvs/asr/bin/python chrome_session_audit.py
أو من الماك:  ssh hermes-vps /root/venvs/asr/bin/python - < chrome_session_audit.py

لكل مثيل Chrome (يُكتشف من /proc: --remote-debugging-port و --user-data-dir) يعرض:
  • من CDP: وجود SID / __Secure-1PSID / LOGIN_INFO ... في نطاقَي google.com و youtube.com وتواريخ انتهائها.
  • من قاعدة Cookies (نسخة مؤقتة للقراءة): وقت إنشاء كوكيز الجلسة (= آخر تسجيل دخول فعلي) وآخر تحديث/تدوير
    لـ __Secure-1PSIDTS و __Secure-1PSIDCC (= هل Chrome ما زال يدوّر الجلسة أم توقف عن ذلك).
  • عناوين تبويبات خدمات جوجل المفتوحة (عنوان ونطاق فقط) وهل Gmail يطلب «تأكيد الهوية».
الحكم: LOGGED-IN إن وُجد LOGIN_INFO لـ youtube.com؛ GOOGLE-ONLY إن وُجد SID لجوجل دون يوتيوب؛ LOGGED-OUT غير ذلك.
"""
import glob
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import time
import urllib.request

KEY_NAMES = ('SID', '__Secure-1PSID', '__Secure-3PSID', 'SAPISID', 'LOGIN_INFO',
             '__Secure-1PSIDTS', '__Secure-1PSIDCC', '__Secure-3PSIDCC', 'SIDCC', 'YSC', 'VISITOR_INFO1_LIVE')
SESSION_COOKIES = ('SID', '__Secure-1PSID', 'LOGIN_INFO')
ROTATING = ('__Secure-1PSIDTS', '__Secure-1PSIDCC')
WEBKIT_EPOCH_OFFSET = 11644473600


def webkit_to_str(us):
    if not us:
        return '-'
    return time.strftime('%Y-%m-%d %H:%M', time.localtime(us / 1e6 - WEBKIT_EPOCH_OFFSET))


def classify(cookie_names_by_domain):
    """نقيّة: تحكم على الحالة من {نطاق: مجموعة أسماء}."""
    yt = cookie_names_by_domain.get('youtube.com', set())
    g = cookie_names_by_domain.get('google.com', set())
    if 'LOGIN_INFO' in yt:
        return 'LOGGED-IN'
    if 'SID' in g or '__Secure-1PSID' in g:
        return 'GOOGLE-ONLY'
    return 'LOGGED-OUT'


def discover_chromes():
    """يرجع [(port, user_data_dir)] من /proc."""
    out = []
    for p in glob.glob('/proc/[0-9]*/cmdline'):
        try:
            args = open(p, 'rb').read().decode('utf-8', 'ignore').split('\0')
        except OSError:
            continue
        if not args or 'chrome' not in os.path.basename(args[0]) or any(a.startswith('--type=') for a in args):
            continue
        port = udd = None
        for a in args:
            m = re.match(r'--remote-debugging-port=(\d+)', a)
            if m:
                port = int(m.group(1))
            if a.startswith('--user-data-dir='):
                udd = a.split('=', 1)[1]
        if port and udd:
            out.append((port, udd))
    return sorted(set(out))


def cdp_cookies(port):
    import websocket
    targets = json.load(urllib.request.urlopen('http://127.0.0.1:%d/json' % port, timeout=8))
    pages = [t for t in targets if t.get('type') == 'page' and t.get('webSocketDebuggerUrl')]
    ws = websocket.create_connection(pages[0]['webSocketDebuggerUrl'], timeout=20, suppress_origin=True)
    try:
        ws.send(json.dumps({'id': 1, 'method': 'Network.getAllCookies'}))
        while True:
            m = json.loads(ws.recv())
            if m.get('id') == 1:
                return (m.get('result') or {}).get('cookies') or [], targets
    finally:
        ws.close()


def db_rows(udd):
    """ينسخ قاعدة الكوكيز (مع WAL) إلى مجلد مؤقت ويقرأ تواريخ الإنشاء/التحديث للكوكيز المفتاحية فقط."""
    src_dir = None
    for cand in ('Default/Network', 'Default'):
        if os.path.exists(os.path.join(udd, cand, 'Cookies')):
            src_dir = os.path.join(udd, cand)
            break
    if not src_dir:
        return []
    tmp = tempfile.mkdtemp(prefix='cookie_audit_')
    try:
        for suffix in ('', '-wal', '-shm', '-journal'):
            f = os.path.join(src_dir, 'Cookies' + suffix)
            if os.path.exists(f):
                shutil.copy2(f, os.path.join(tmp, 'Cookies' + suffix))
        con = sqlite3.connect(os.path.join(tmp, 'Cookies'))
        cols = {r[1] for r in con.execute('PRAGMA table_info(cookies)')}
        upd = 'last_update_utc' if 'last_update_utc' in cols else 'last_access_utc'
        q = ('SELECT host_key, name, creation_utc, %s, expires_utc FROM cookies '
             'WHERE (host_key LIKE "%%google.com" OR host_key LIKE "%%youtube.com") AND name IN (%s)'
             % (upd, ','.join('?' * len(KEY_NAMES))))
        rows = con.execute(q, KEY_NAMES).fetchall()
        con.close()
        return rows
    except Exception as e:  # noqa: BLE001
        return [('ERR', str(e)[:80], 0, 0, 0)]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def audit_one(port, udd):
    print('=' * 70)
    print('Chrome CDP:%d  profile=%s' % (port, udd))
    try:
        cookies, targets = cdp_cookies(port)
    except Exception as e:  # noqa: BLE001
        print('  CDP error:', type(e).__name__, str(e)[:80])
        return 'UNREACHABLE'
    by_dom = {}
    for c in cookies:
        d = c.get('domain', '')
        for base in ('youtube.com', 'google.com'):
            if d.endswith(base):
                by_dom.setdefault(base, set()).add(c['name'])
    verdict = classify(by_dom)
    print('  الحكم:', verdict)
    for base in ('google.com', 'youtube.com'):
        names = by_dom.get(base, set())
        print('  %-12s الكوكيز المفتاحية: %s' % (base, ', '.join(n for n in KEY_NAMES if n in names) or '(لا شيء)'))
    rows = db_rows(udd)
    print('  — من قاعدة الكوكيز (إنشاء | آخر تحديث):')
    seen = set()
    for host, name, cre, upd, exp in sorted(rows):
        if name in SESSION_COOKIES + ROTATING and (host, name) not in seen:
            seen.add((host, name))
            print('     %-16s %-18s created=%s  updated=%s' % (host, name, webkit_to_str(cre), webkit_to_str(upd)))
    gtabs = []
    for t in targets:
        u = t.get('url', '')
        if t.get('type') == 'page' and re.search(r'(accounts\.google|mail\.google|myaccount\.google|youtube\.com|accounts\.youtube)', u):
            host = re.sub(r'^https?://([^/]+).*$', r'\1', u)
            confirm = 'confirmidentifier' in u or 'signin' in u.lower() or 'ServiceLogin' in u
            gtabs.append('%s | %s%s' % (host, (t.get('title') or '')[:40], '  ⚠ يطلب تسجيل الدخول/تأكيد الهوية' if confirm else ''))
    for g in gtabs[:8]:
        print('  تبويب:', g)
    return verdict


def main():
    chromes = discover_chromes()
    if not chromes:
        print('لا يوجد Chrome بـ --remote-debugging-port على هذا الجهاز.')
        return 2
    verdicts = {port: audit_one(port, udd) for port, udd in chromes}
    print('=' * 70)
    print('الملخص:', ' · '.join('%d=%s' % (p, v) for p, v in verdicts.items()))
    return 0


if __name__ == '__main__':
    sys.exit(main())
