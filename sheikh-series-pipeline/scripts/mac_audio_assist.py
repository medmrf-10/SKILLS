#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mac_audio_assist.py — مساعد التنزيل على الماك لمغذّي المحاذاة (vps_align_feeder.py).

لماذا؟ عنوان hermes-vps (مركز بيانات) يعتبره يوتيوب مشبوهاً ("Sign in to confirm you're not a bot") وكوكيز الـ VPS
تتلف باستمرار، بينما تنزيل الماك (عنوان منزلي) ينجح بلا كوكيز. فعندما يفشل تنزيل الـ VPS (أو يُفتح قاطع يوتيوب)
يكتب المغذّي طلباً <key>.need.json في /root/workspace/align-bridge/need_mac/ وهذا السكربت:

  1) يسرد الطلبات من الـ VPS (ssh)،
  2) ينزّل الصوت محلياً بـ yt-dlp (نفس محدّد الصيغ: يفضّل المسار العربي الأصلي) أو curl للروابط المباشرة،
  3) يحوّله إلى Opus 12kbps VoIP بنفس إعدادات المغذّي،
  4) يتحقق من المدة (ffprobe) كي لا يُرفع ملف مبتور،
  5) يرفع <key>.opus ثم يكتب <key>.job.json ذرّياً ويحذف الطلب،
فيلتقطه mac_align_fleet.py كأي مهمة عادية دون أي تعديل عليه.

التشغيل: LaunchAgent com.mohamed.mac-audio-assist (KeepAlive)، أو يدوياً:  python3 mac_audio_assist.py --once --limit 3
"""
import argparse
import base64
import fcntl
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import concurrent.futures
from datetime import datetime

VPS_HOST = os.environ.get('VPS_HOST', 'hermes-vps')
REMOTE_NEED = os.environ.get('ALIGN_NEED_DIR', '/root/workspace/align-bridge/need_mac')
REMOTE_BRIDGE = os.environ.get('ALIGN_BRIDGE_DIR', '/root/workspace/align-bridge/ready')
WORKERS = int(os.environ.get('ASSIST_WORKERS', '2'))
POLL_S = float(os.environ.get('ASSIST_POLL_S', '20'))
GAP_S = float(os.environ.get('ASSIST_GAP_S', '4'))          # فاصل بين تنزيلين متتاليين (لطف مع يوتيوب)
BACKOFF_BASE_S = 600
BACKOFF_MAX_S = 21600
MIN_DURATION_RATIO = 0.80                                  # أقل نسبة مقبولة من المدة المتوقعة

YTDLP = shutil.which('yt-dlp') or '/opt/homebrew/bin/yt-dlp'
FFMPEG = shutil.which('ffmpeg') or '/opt/homebrew/bin/ffmpeg'
FFPROBE = shutil.which('ffprobe') or '/opt/homebrew/bin/ffprobe'
LOG_PATH = os.environ.get('ASSIST_LOG', os.path.expanduser('~/workspace/ytb-build/mac_audio_assist.log'))
LOCK_PATH = '/tmp/mac_audio_assist.lock'

AUDIO_FORMAT = ('worstaudio[language^=ar][abr>=32]/bestaudio[language^=ar]/worstaudio[format_note*=original][abr>=32]/'
                'worstaudio[abr>=32]/worstaudio/bestaudio')
SSH_OPTS = ['-o', 'BatchMode=yes', '-o', 'ConnectTimeout=15', '-o', 'ServerAliveInterval=15', '-o', 'ServerAliveCountMax=2']

_FAILS = {}          # key -> (count, next_try_ts)
_FAILS_LOCK = threading.Lock()


def log(msg):
    line = f'[{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}] [mac-audio-assist] {msg}'
    print(line, flush=True)


# ───────────── دوال نقية (قابلة للاختبار) ─────────────

def backoff_delay(count):
    """تراجع: 10د ثم 20د ثم 40د ... بحد أقصى 6 ساعات."""
    return min(BACKOFF_MAX_S, BACKOFF_BASE_S * (2 ** max(0, count - 1)))


def is_direct_audio_url(url):
    u = (url or '').lower()
    return bool(u.startswith('http') and ('archive.org/' in u or u.endswith(('.mp3', '.m4a', '.wav', '.ogg', '.opus'))))


def youtube_url(item):
    url = item.get('url') or ''
    if url.startswith('http'):
        return url
    return f'https://www.youtube.com/watch?v={item["vid"]}'


def build_job_meta(item, opus_bytes, now=None):
    """نفس بنية job.json التي يكتبها vps_align_feeder.prepare_one_opus (يعتمد عليها mac_align_fleet)."""
    return {
        'key': item['key'],
        'vid': item['vid'],
        'stem': item['stem'],
        'sheikh': item['sheikh'],
        'row': item['row'],
        'txt_path': item['txt_path'],
        'dur_s': item['dur_s'],
        'opus_bytes': int(opus_bytes),
        'created_at': time.time() if now is None else now,
    }


def duration_ok(actual_s, expected_s, ratio=MIN_DURATION_RATIO):
    """يرفض الملف المبتور: المدة الفعلية يجب ألا تقل عن ratio من المتوقعة (إن كانت المتوقعة معروفة)."""
    if not expected_s or expected_s <= 0:
        return actual_s is not None and actual_s > 5
    return actual_s is not None and actual_s >= expected_s * ratio


def in_cooldown(key, now=None):
    now = time.time() if now is None else now
    with _FAILS_LOCK:
        rec = _FAILS.get(key)
    return bool(rec and rec[1] > now)


def note_failure(key, now=None):
    now = time.time() if now is None else now
    with _FAILS_LOCK:
        cnt = _FAILS.get(key, (0, 0.0))[0] + 1
        _FAILS[key] = (cnt, now + backoff_delay(cnt))
    return backoff_delay(cnt)


def note_success(key):
    with _FAILS_LOCK:
        _FAILS.pop(key, None)


# ───────────── اتصال الـ VPS ─────────────

def ssh(cmd, input_text=None, timeout=60):
    return subprocess.run(['ssh', *SSH_OPTS, VPS_HOST, cmd], input=input_text, capture_output=True,
                          text=True, timeout=timeout, stdin=None if input_text is not None else subprocess.DEVNULL)


def list_need(limit=20):
    """يسرد طلبات التنزيل الجاهزة للتنفيذ (الأقدم أولاً) ويحذف ما انتهى منها على الجانب البعيد."""
    remote = (
        'import glob, json, os\n'
        f'nd = {json.dumps(REMOTE_NEED)}\n'
        f'bd = {json.dumps(REMOTE_BRIDGE)}\n'
        'out = []\n'
        'for p in glob.glob(nd + "/*.need.json"):\n'
        '    try:\n'
        '        j = json.load(open(p, encoding="utf-8"))\n'
        '        k = j["key"]; tp = j.get("txt_path", "")\n'
        '        ap = tp[:-4] + ".align.json" if tp.endswith(".txt") else ""\n'
        '        if os.path.exists(os.path.join(bd, k + ".job.json")) or (ap and os.path.exists(ap) and os.path.getsize(ap) > 200) or not os.path.exists(tp):\n'
        '            os.remove(p); continue\n'
        '        out.append(j)\n'
        '    except Exception:\n'
        '        pass\n'
        'out.sort(key=lambda x: x.get("requested_at", 0))\n'
        f'print(json.dumps(out[:{int(limit)}], ensure_ascii=False))\n'
    )
    b64 = base64.b64encode(remote.encode('utf-8')).decode('ascii')
    r = ssh(f"python3 -c \"import base64; exec(base64.b64decode('{b64}'))\"", timeout=45)
    if r.returncode != 0 or not r.stdout.strip():
        if r.returncode != 0:
            log(f'[تحذير list_need] rc={r.returncode} {(r.stderr or "").strip()[:160]}')
        return []
    try:
        return json.loads(r.stdout.strip().splitlines()[-1])
    except ValueError:
        return []


def download_audio(item, tmpd):
    """ينزّل الصوت الخام لملف في tmpd ويعيد مساره أو None."""
    url = youtube_url(item)
    if is_direct_audio_url(item.get('url')):
        raw = os.path.join(tmpd, 'raw.mp3')
        r = subprocess.run(['curl', '-fL', '--retry', '3', '--connect-timeout', '20', '-sS', item['url'], '-o', raw],
                           capture_output=True, text=True, timeout=900, stdin=subprocess.DEVNULL)
        return raw if (r.returncode == 0 and os.path.exists(raw) and os.path.getsize(raw) > 10000) else None
    r = subprocess.run(
        [YTDLP, '--no-warnings', '--no-playlist', '-f', AUDIO_FORMAT, '-o', os.path.join(tmpd, 'raw.%(ext)s'), url],
        capture_output=True, text=True, timeout=900, stdin=subprocess.DEVNULL)
    cands = glob.glob(os.path.join(tmpd, 'raw.*'))
    if r.returncode != 0 or not cands:
        log(f'  yt-dlp فشل: {((r.stderr or r.stdout) or "").strip().splitlines()[-1][:200] if (r.stderr or r.stdout) else "?"}')
        return None
    return cands[0]


def to_opus(raw_audio, out_path):
    r = subprocess.run(
        [FFMPEG, '-nostdin', '-y', '-loglevel', 'error', '-threads', '2', '-i', raw_audio, '-vn', '-ac', '1', '-ar', '16000',
         '-c:a', 'libopus', '-b:a', '12k', '-compression_level', '0', '-application', 'voip', '-map_metadata', '-1', out_path],
        capture_output=True, text=True, timeout=900, stdin=subprocess.DEVNULL)
    return r.returncode == 0 and os.path.exists(out_path) and os.path.getsize(out_path) > 1000


def probe_duration(path):
    r = subprocess.run([FFPROBE, '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=nw=1:nk=1', path],
                       capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return None


def upload(item, opus_path):
    """يرفع Opus ثم يكتب job.json ذرّياً ويحذف طلب need — بهذا الترتيب كي لا يرى المستهلك job بلا opus."""
    key = item['key']
    tmp_remote = f'{REMOTE_BRIDGE}/{key}.opus.tmp'
    r = subprocess.run(['scp', '-q', *SSH_OPTS, opus_path, f'{VPS_HOST}:{tmp_remote}'],
                       capture_output=True, text=True, timeout=600, stdin=subprocess.DEVNULL)
    if r.returncode != 0:
        log(f'  scp فشل: {(r.stderr or "").strip()[:160]}')
        return False
    meta = build_job_meta(item, os.path.getsize(opus_path))
    job_path = f'{REMOTE_BRIDGE}/{key}.job.json'
    cmd = (f"mv {tmp_remote} {REMOTE_BRIDGE}/{key}.opus && cat > {job_path}.tmp && mv {job_path}.tmp {job_path} "
           f"&& rm -f {REMOTE_NEED}/{key}.need.json")
    r = ssh(cmd, input_text=json.dumps(meta, ensure_ascii=False, indent=2), timeout=60)
    if r.returncode != 0:
        log(f'  إنهاء الرفع فشل: {(r.stderr or "").strip()[:160]}')
        return False
    return True


def process_item(item):
    key = item['key']
    if in_cooldown(key):
        return None
    t0 = time.time()
    with tempfile.TemporaryDirectory(prefix='assist_') as tmpd:
        raw = download_audio(item, tmpd)
        if not raw:
            d = note_failure(key)
            log(f'✗ تعذّر تنزيل {key} (تراجع {int(d // 60)}د)')
            return False
        out = os.path.join(tmpd, 'out.opus')
        if not to_opus(raw, out):
            d = note_failure(key)
            log(f'✗ فشل تحويل Opus لـ {key} (تراجع {int(d // 60)}د)')
            return False
        dur = probe_duration(out)
        if not duration_ok(dur, item.get('dur_s')):
            d = note_failure(key)
            log(f'✗ مدة غير منطقية لـ {key}: {dur} من {item.get("dur_s")}ث (تراجع {int(d // 60)}د)')
            return False
        if not upload(item, out):
            note_failure(key)
            return False
        note_success(key)
        mb = os.path.getsize(out) / (1024.0 * 1024.0)
        log(f'✓ جهّز الماك {key}.opus ({mb:.2f} MB · {dur / 60:.1f}د) في {time.time() - t0:.0f}ث')
        return True


def run_batch(limit=None):
    items = [i for i in list_need(limit=max(WORKERS * 4, limit or 0)) if not in_cooldown(i['key'])]
    if limit:
        items = items[:limit]
    if not items:
        return 0
    done = 0

    def _one(it):
        time.sleep(GAP_S)
        return process_item(it)

    with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for ok in ex.map(_one, items):
            done += 1 if ok else 0
    return done


def main(argv=None):
    ap = argparse.ArgumentParser(description='مساعد تنزيل الماك لمغذّي المحاذاة')
    ap.add_argument('--once', action='store_true', help='دورة واحدة ثم خروج')
    ap.add_argument('--limit', type=int, default=0, help='أقصى عدد دروس في الدورة')
    args = ap.parse_args(argv)

    lock_fd = open(LOCK_PATH, 'w')
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        log('نسخة أخرى تعمل — خروج.')
        return 0
    log(f'بدء المساعد (WORKERS={WORKERS} · POLL={POLL_S}s · VPS={VPS_HOST})')
    while True:
        try:
            n = run_batch(limit=args.limit or None)
            if args.once:
                log(f'انتهت الدورة: {n} درس جاهز')
                return 0
            time.sleep(1 if n else POLL_S)
        except KeyboardInterrupt:
            return 0
        except Exception as e:  # noqa: BLE001
            log(f'خطأ في الحلقة: {e}')
            if args.once:
                return 1
            time.sleep(POLL_S)


if __name__ == '__main__':
    sys.exit(main())
