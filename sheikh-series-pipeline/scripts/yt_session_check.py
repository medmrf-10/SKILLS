#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""yt_session_check.py — يفحص هل Chrome الدائم على الـ VPS (CDP :9222) مسجَّل الدخول إلى يوتيوب، دون أي طلب إلى يوتيوب.

الأساس: كوكي LOGIN_INFO لنطاق youtube.com لا يوجد إلا في جلسة مسجَّلة. غيابه يعني أن الكوكيز التي تُصدَّر ستكون
«no longer valid» ويرفضها يوتيوب (Sign in to confirm you're not a bot). (تعلّمنا ذلك 2026-10-21: التنزيل من الـ VPS
فشل ١٩٩٠ مرة لأن Chrome خرج من حساب يوتيوب.)

رموز الخروج: 0 مسجَّل ✓ · 10 غير مسجَّل (يلزم دخول يدوي عبر noVNC) · 2 تعذّر الوصول إلى CDP.
يُشغَّل بمفسّر venv الذي فيه websocket-client:  /root/venvs/asr/bin/python yt_session_check.py [--port 9222]
لا يطبع قيم الكوكيز أبداً، بل الحالة فقط.
"""
import argparse
import json
import sys
import urllib.request


def logged_in_from_cookies(cookies):
    """نقيّة وقابلة للاختبار: True إن وُجد LOGIN_INFO لنطاق youtube.com."""
    return any(c.get('name') == 'LOGIN_INFO' and 'youtube.com' in c.get('domain', '') for c in cookies or [])


def fetch_cookies(port):
    import websocket  # websocket-client
    targets = json.load(urllib.request.urlopen('http://127.0.0.1:%d/json' % port, timeout=8))
    pages = [t for t in targets if t.get('type') == 'page' and t.get('webSocketDebuggerUrl')]
    if not pages:
        raise RuntimeError('no page targets')
    ws = websocket.create_connection(pages[0]['webSocketDebuggerUrl'], timeout=20, suppress_origin=True)
    try:
        ws.send(json.dumps({'id': 1, 'method': 'Network.getAllCookies'}))
        while True:
            m = json.loads(ws.recv())
            if m.get('id') == 1:
                return (m.get('result') or {}).get('cookies') or []
    finally:
        ws.close()


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--port', type=int, default=9222)
    args = ap.parse_args(argv)
    try:
        ok = logged_in_from_cookies(fetch_cookies(args.port))
    except Exception as e:  # noqa: BLE001
        print('CDP-UNREACHABLE: %s' % str(e)[:100])
        return 2
    print('YT-LOGGED-IN' if ok else 'YT-LOGGED-OUT')
    return 0 if ok else 10


if __name__ == '__main__':
    sys.exit(main())
