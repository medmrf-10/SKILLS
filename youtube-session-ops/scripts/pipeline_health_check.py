#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pipeline_health_check.py — فحص صحة مسار المحاذاة (الماك + hermes-vps) للقراءة فقط، ولا يُصلح شيئاً.

يقيس: محاذاة الماك في آخر ٦٠ دقيقة وحياة العملية والطابور، وجلسة يوتيوب على الـ VPS، ونجاح/فشل التنزيل في آخر ٦٠ دقيقة،
وحالة الجسر والمتبقي، ووجود yt-dlp/المساعد على الماك (ممنوع). ثم يطبّق قواعد التنبيه في evaluate().

الاستعمال:   python3 pipeline_health_check.py            # نص مقروء
             python3 pipeline_health_check.py --json     # JSON
رموز الخروج: 0 سليم · 1 يوجد تنبيه (أسطر تبدأ بـ ALERT:) · 2 تعذّر الفحص نفسه.
لا يكتب شيئاً ولا يفتح صفحات ولا يلمس Chrome ولا يطلب شيئاً من يوتيوب.
"""
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta

D = os.path.expanduser('~/workspace/ytb-build')
WINDOW_MIN = 60
STALE_MIN = 20          # حالة المغذّي/الماك التي لم تتجدد منذ هذه المدة تُعدّ متجمدة

REMOTE = r'''
import json, re, subprocess
from datetime import datetime, timedelta
now = datetime.now()
cut = now - timedelta(minutes=%(win)d)
ok = bad = 0
for l in open("/root/workspace/ytb-build/vps_align_feeder.log", errors="ignore"):
    m = re.match(r"\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)\]", l)
    if not m or datetime.strptime(m.group(1), "%%Y-%%m-%%d %%H:%%M:%%S") < cut:
        continue
    if "✓ جاهز للمحاذاة" in l:
        ok += 1
    elif "فشل تنزيل الصوت" in l:
        bad += 1
r = subprocess.run(["/root/venvs/asr/bin/python", "/root/workspace/ytb-build/yt_session_check.py"], capture_output=True, text=True)
s = json.load(open("/root/workspace/ytb-build/align_feeder_state.json"))
age = (now - datetime.fromisoformat(s["updated_at"])).total_seconds() / 60.0
print(json.dumps({"session": r.stdout.strip(), "yt_session_ok": s.get("yt_session_ok"), "ready": s.get("ready_in_bridge"),
                  "pending": s.get("pending_with_txt"), "state_age_min": round(age, 1), "ok": ok, "fail": bad}))
''' % {'win': WINDOW_MIN}


def is_forbidden_command(cmdline):
    """هل هذا الأمر yt-dlp أو مساعد تنزيل الماك؟ نفحص المنفّذ ووسيطيه الأولين فقط، فلا يطابق أمراً يذكر الكلمة كنص عادي."""
    tokens = cmdline.split()
    if not tokens:
        return False
    exe = os.path.basename(tokens[0]).lower()
    head = [os.path.basename(t) for t in tokens[1:3]]
    if exe == 'yt-dlp':
        return True
    if exe.startswith('python'):
        return 'yt-dlp' in head or 'mac_audio_assist.py' in head
    return False


def collect_mac(now=None):
    now = now or datetime.now()
    cut = now - timedelta(minutes=WINDOW_MIN)
    aligned = []
    for l in open(os.path.join(D, 'mac_align_fleet.log'), errors='ignore'):
        m = re.match(r'\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)\].*✓ محاذاة #(\d+)', l)
        if m:
            t = datetime.strptime(m.group(1), '%Y-%m-%d %H:%M:%S')
            if t >= cut:
                aligned.append((t, int(m.group(2))))
    st = json.load(open(os.path.join(D, 'mac_align_state.json')))
    ps = subprocess.run(['ps', '-axo', 'pid,command'], capture_output=True, text=True).stdout.splitlines()
    me = str(os.getpid())
    fleet = [x for x in ps if 'mac_align_fleet.py' in x and 'caffeinate' not in x]
    # لا نطابق عمليتنا نفسها ولا نصاً يحوي الكلمة داخل وسيط (نفحص أول كلمة من الأمر فقط)
    bad = []
    for x in ps:
        parts = x.strip().split(None, 1)
        if len(parts) < 2 or parts[0] == me:
            continue
        if is_forbidden_command(parts[1]):
            bad.append(x.strip()[:100])
    updated = datetime.fromisoformat(st['updated_at'])
    return {
        'mac_aligned_60m': len(aligned),
        'mac_last_aligned': aligned[-1][0].strftime('%H:%M:%S') if aligned else None,
        'mac_total': st.get('completed_lessons'),
        'mac_queue': st.get('prefetch_queue_ready'),
        'mac_fleet_alive': bool(fleet),
        'mac_state_age_min': round((now - updated).total_seconds() / 60.0, 1),
        'mac_bad_procs': bad,
    }


def collect_vps():
    r = subprocess.run(['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=15', 'hermes-vps', 'python3 -'],
                       input=REMOTE, capture_output=True, text=True, timeout=75)
    if r.returncode != 0 or not r.stdout.strip():
        return {'vps_error': (r.stderr or 'no output').strip()[:160]}
    d = json.loads(r.stdout.strip().splitlines()[-1])
    return {'vps_session': d['session'], 'vps_session_ok': d['yt_session_ok'], 'vps_ready': d['ready'],
            'vps_pending': d['pending'], 'vps_state_age_min': d['state_age_min'],
            'vps_ok_60m': d['ok'], 'vps_fail_60m': d['fail']}


def evaluate(m):
    """نقيّة وقابلة للاختبار: تعيد قائمة تنبيهات (فارغة = سليم)."""
    alerts = []
    if m.get('vps_error'):
        alerts.append('تعذّر الاتصال بـ hermes-vps: %s' % m['vps_error'])
        return alerts
    if m.get('vps_session') != 'YT-LOGGED-IN' or m.get('vps_session_ok') is False:
        alerts.append('جلسة يوتيوب في Chrome الـ VPS ميتة (%s) ⇒ الدخول يدوياً عبر noVNC (مهارة youtube-session-ops §4)' % m.get('vps_session'))
    ok, fail = m.get('vps_ok_60m', 0), m.get('vps_fail_60m', 0)
    if fail >= 5 and fail > ok:
        alerts.append('إخفاقات التنزيل (%d) تتجاوز النجاحات (%d) في آخر ساعة' % (fail, ok))
    if not m.get('mac_fleet_alive'):
        alerts.append('عملية mac_align_fleet.py غير حيّة (يفترض أن يعيدها launchd؛ افحص launchctl print gui/$(id -u)/com.mohamed.mac-align-fleet)')
    if m.get('mac_bad_procs'):
        alerts.append('عملية ممنوعة على الماك (yt-dlp أو mac_audio_assist): %s ⇒ لا تنزيل يوتيوب من الماك' % m['mac_bad_procs'][:2])
    pending = m.get('vps_pending') or 0
    work_available = (m.get('vps_ready') or 0) > 0 or (m.get('mac_queue') or 0) > 0
    if pending > 0 and m.get('mac_aligned_60m', 0) == 0 and work_available:
        alerts.append('الماك لم يحاذِ شيئاً خلال ساعة رغم وجود عمل جاهز (جسر=%s، طابور=%s)' % (m.get('vps_ready'), m.get('mac_queue')))
    if pending > 0 and (m.get('vps_ready') or 0) == 0 and (m.get('mac_queue') or 0) == 0:
        alerts.append('جوع الجسر: المتبقي %d والجسر والطابور فارغان ⇒ المغذّي لا يُنتج (افحص vps_align_feeder.log)' % pending)
    if (m.get('vps_state_age_min') or 0) > STALE_MIN:
        alerts.append('حالة المغذّي لم تتجدد منذ %.0f دقيقة (متجمد؟)' % m['vps_state_age_min'])
    return alerts


def main(argv=None):
    as_json = '--json' in (argv or sys.argv[1:])
    try:
        m = {}
        m.update(collect_mac())
        m.update(collect_vps())
    except Exception as e:  # noqa: BLE001
        print('تعذّر الفحص نفسه: %s: %s' % (type(e).__name__, str(e)[:160]))
        return 2
    alerts = evaluate(m)
    if as_json:
        print(json.dumps({'metrics': m, 'alerts': alerts}, ensure_ascii=False, indent=2))
    else:
        print('MAC  محاذاة_آخر_ساعة=%s  آخرها=%s  الإجمالي=%s  الطابور=%s  العملية_حيّة=%s' % (
            m.get('mac_aligned_60m'), m.get('mac_last_aligned'), m.get('mac_total'), m.get('mac_queue'), m.get('mac_fleet_alive')))
        if 'vps_error' not in m:
            print('VPS  الجلسة=%s  جسر=%s  المتبقي=%s  جُهّز_آخر_ساعة=%s  فشل=%s' % (
                m['vps_session'], m['vps_ready'], m['vps_pending'], m['vps_ok_60m'], m['vps_fail_60m']))
        for a in alerts:
            print('ALERT:', a)
        if not alerts:
            print('OK: كل شيء سليم')
    return 1 if alerts else 0


if __name__ == '__main__':
    sys.exit(main())
