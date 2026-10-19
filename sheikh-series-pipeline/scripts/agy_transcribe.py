#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""agy_transcribe.py — تفريغ الدروس الصوتية عبر agy (Gemini) مع تقطيع تلقائي للمحاضرات الطويلة وتطهير فوري.

المزايا الهندسية:
  1. يعمل على الماك (macOS) والـVPS (Linux) تلقائيًا (يكتشف مسار `agy` و`ffmpeg` و`ffprobe`).
  2. يمنع تلوث المخرجات بالمقدمات اللاتينية (`I have launched...`) أو استدعاء أدوات طرفية (`run_command`)
     عبر تشغيل `agy` داخل مجلد عمل مؤقت معزول يضم رابطًا للملف الصوتي فقط + موجه نظام صارم يقصر الأدوات
     على `view_file` فقط، ثم يمرر النص عبر `strip_preamble_and_header` قبل الحفظ.
  3. يمنع البتر في المحاضرات الطويلة (> 38 دقيقة، مثل دروس 70–90 دقيقة) عبر تقسيم الصوت تلقائيًا إلى مقاطع
     بطول `--chunk-minutes` (الافتراضي 25 دقيقة) وتفريغ كل مقطع كاملًا ثم دمجها والتحقق من معدل الكلمات (WPM).

الاستعمال:
  python3 agy_transcribe.py <series_dir> [--only 001,002] [--model gemini-3-flash-preview] \
      [--max-single-minutes 38] [--chunk-minutes 25] [--force] [--check-usage]
"""
import argparse
import concurrent.futures
import glob
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sanitize_preamble import (  # noqa: E402
    deduplicate_chunk_boundary_overlap as _sanitize_dedup_chunk_boundary_overlap,
    strip_preamble_and_header,
)

AR_RE = re.compile(r'[\u0600-\u06FF]')


def deduplicate_chunk_boundary_overlap(text_or_chunks, min_overlap_words=4, max_window_words=55):
    """إزالة الجمل المكررة عند حدود تقطيع الصوت (chunk boundaries كل 12 دقيقة) مع الحفاظ الكامل على التكرارات التعبدية المشروعة."""
    return _sanitize_dedup_chunk_boundary_overlap(
        text_or_chunks, min_overlap_words=min_overlap_words, max_window_words=max_window_words
    )


def find_bin(name, extra_paths):
    w = shutil.which(name)
    if w:
        return w
    for p in extra_paths:
        matches = sorted(glob.glob(p))
        if matches and os.access(matches[-1], os.X_OK):
            return matches[-1]
    return name


AGY_BIN = os.environ.get('AGY_BIN') or find_bin('agy', [
    os.path.expanduser('~/.local/bin/agy'),
    '/Users/macm1pro/.local/bin/agy',
    '/root/.local/bin/agy',
])

FFMPEG_BIN = os.environ.get('FFMPEG') or find_bin('ffmpeg', [
    '/opt/homebrew/bin/ffmpeg',
    '/usr/local/bin/ffmpeg',
    '/root/.hermes/tools/ffmpeg-*/bin/ffmpeg',
])

FFPROBE_BIN = os.environ.get('FFPROBE') or find_bin('ffprobe', [
    '/opt/homebrew/bin/ffprobe',
    '/usr/local/bin/ffprobe',
    '/root/.hermes/tools/ffmpeg-*/bin/ffprobe',
])

YTDLP_BIN = os.environ.get('YTDLP_BIN') or find_bin('yt-dlp', [
    '/opt/homebrew/bin/yt-dlp',
    '/usr/local/bin/yt-dlp',
    os.path.expanduser('~/.local/bin/yt-dlp'),
    '/root/.local/bin/yt-dlp',
    '/root/.hermes/tools/python-*/bin/yt-dlp',
    '/root/venvs/*/bin/yt-dlp',
])


def get_audio_duration(audio_path):
    try:
        res = subprocess.run(
            [FFPROBE_BIN, '-v', 'error', '-show_entries', 'format=duration',
             '-of', 'default=noprint_wrappers=1:nokey=1', audio_path],
            capture_output=True, text=True, timeout=30
        )
        return float(res.stdout.strip())
    except Exception:
        return 0.0


def is_valid_audio_file(audio_path, expected_dur_s=0.0):
    if not os.path.exists(audio_path):
        return False
    try:
        if os.path.getsize(audio_path) <= 10000:
            return False
    except OSError:
        return False
    actual_dur = get_audio_duration(audio_path)
    if actual_dur <= 1.0:
        return False
    if expected_dur_s > 60.0 and actual_dur < (expected_dur_s * 0.88):
        return False
    return True


def download_lesson_audio(series_dir, n, vid, expected_dur_s=0.0, retries=3, direct_url=''):
    """تنزيل صوت الدرس من يوتيوب أو أرشيف الإنترنت وتحويله ذرياً إلى MP3 أحادي (16kHz · 64kbps) مع فحص اكتمال المدة."""
    base = '%03d_%s' % (int(n), vid)
    out_mp3 = os.path.join(series_dir, base + '.mp3')
    for ext in ('.mp3', '.m4a', '.wav'):
        cand = os.path.join(series_dir, base + ext)
        if os.path.exists(cand):
            if is_valid_audio_file(cand, expected_dur_s):
                return cand, 0.0
            try:
                os.remove(cand)
            except OSError:
                pass

    t0 = time.time()
    # إذا كان الرابط مباشراً (مثل archive.org/download/*.mp3)، نزّله مباشرة عبر curl
    if direct_url and ('archive.org/' in direct_url or direct_url.lower().endswith(('.mp3', '.m4a', '.wav', '.ogg', '.opus'))):
        tmp_dl = out_mp3 + '.part.mp3'
        try:
            subprocess.run(['curl', '-fL', '--retry', '3', '--connect-timeout', '20', '-sS', direct_url, '-o', tmp_dl], check=True, timeout=600)
            if is_valid_audio_file(tmp_dl, expected_dur_s):
                os.replace(tmp_dl, out_mp3)
                dt = round(time.time() - t0, 1)
                mb = os.path.getsize(out_mp3) / (1024.0 * 1024.0)
                print('[تنزيل مباشر archive] ✓ %s.mp3 (%.1f MB في %.1fث)' % (base, mb, dt), flush=True)
                return out_mp3, dt
        except Exception as e:
            try:
                if os.path.exists(tmp_dl):
                    os.remove(tmp_dl)
            except OSError:
                pass
            raise RuntimeError('فشل تنزيل الرابط المباشر لـ %s (%s): %s' % (base, direct_url, e))

    # إذا وُجد ملف .webm مكتمل من محاولة سابقة قُطعت أثناء تحويل ffmpeg، حوّله فوراً دون إعادة التنزيل
    webm_cand = os.path.join(series_dir, base + '.webm')
    if os.path.exists(webm_cand) and is_valid_audio_file(webm_cand, expected_dur_s):
        tmp_mp3 = out_mp3 + '.part.mp3'
        try:
            subprocess.run(
                [FFMPEG_BIN, '-y', '-loglevel', 'error', '-i', webm_cand,
                 '-vn', '-ar', '16000', '-ac', '1', '-b:a', '64k', tmp_mp3],
                check=True, timeout=300
            )
            if is_valid_audio_file(tmp_mp3, expected_dur_s):
                os.replace(tmp_mp3, out_mp3)
                try:
                    os.remove(webm_cand)
                except OSError:
                    pass
                dt = round(time.time() - t0, 1)
                mb = os.path.getsize(out_mp3) / (1024.0 * 1024.0)
                print('[استكمال تحويل webm] ✓ %s.mp3 (%.1f MB في %.1fث)' % (base, mb, dt), flush=True)
                return out_mp3, dt
        except Exception:
            pass

    url = direct_url if (direct_url and direct_url.startswith('http')) else ('https://www.youtube.com/watch?v=%s' % vid)
    last_err = ''
    if os.path.exists('/usr/local/bin/mirath-audio'):
        import signal
        with tempfile.TemporaryDirectory(prefix='mirath_%s_' % base) as mtmp:
            p = subprocess.Popen(
                ['/usr/local/bin/mirath-audio', url, '--outdir', mtmp, '--name', base],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True
            )
            try:
                out_s, err_s = p.communicate(timeout=1200)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(p.pid, signal.SIGKILL)
                except OSError:
                    p.kill()
                p.wait()
                raise RuntimeError('mirath-audio timed out after 1200s for %s' % base)
            tmp_out = os.path.join(mtmp, base + '.mp3')
            if is_valid_audio_file(tmp_out, expected_dur_s):
                os.replace(tmp_out, out_mp3)
                try:
                    if os.path.exists(webm_cand):
                        os.remove(webm_cand)
                except OSError:
                    pass
                dt = round(time.time() - t0, 1)
                mb = os.path.getsize(out_mp3) / (1024.0 * 1024.0)
                print('[تنزيل صوت mirath-audio] ✓ %s.mp3 (%.1f MB في %.1fث)' % (base, mb, dt), flush=True)
                return out_mp3, dt
            last_err = ((err_s or '') + ' ' + (out_s or ''))[-300:].strip()

    for att in range(1, retries + 1):
        with tempfile.TemporaryDirectory(prefix='ytdl_%s_' % base) as tmpd:
            tmp_tpl = os.path.join(tmpd, 'raw.%(ext)s')
            fmt = (
                'bestaudio[language^=ar][ext=m4a]/bestaudio[language^=ar]/bestaudio[format_note*=original]/bestaudio[ext=m4a]/bestaudio/best'
                if att == 1 else
                'bestaudio[language^=ar]/bestaudio[format_note*=original]/bestaudio/best'
            )
            cmd = [
                YTDLP_BIN, '--no-playlist', '--retries', '5', '--fragment-retries', '5',
                '-f', fmt, '-o', tmp_tpl, url
            ]
            if os.path.exists('/root/.config/mirath-cookies/youtube.txt'):
                cmd[1:1] = ['--cookies', '/root/.config/mirath-cookies/youtube.txt']
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            raw_files = glob.glob(os.path.join(tmpd, 'raw.*'))
            if res.returncode != 0 or not raw_files:
                last_err = ((res.stderr or '') + ' ' + (res.stdout or ''))[-300:].strip()
                time.sleep(2 * att)
                continue
            raw_path = raw_files[0]
            tmp_mp3 = out_mp3 + '.part.mp3'
            ff_cmd = [
                FFMPEG_BIN, '-y', '-loglevel', 'error', '-i', raw_path,
                '-vn', '-ar', '16000', '-ac', '1', '-b:a', '64k', tmp_mp3
            ]
            subprocess.run(ff_cmd, check=True, timeout=300)
            if is_valid_audio_file(tmp_mp3, expected_dur_s):
                os.replace(tmp_mp3, out_mp3)
                break
    if not is_valid_audio_file(out_mp3, expected_dur_s):
        raise RuntimeError('فشل yt-dlp لـ %s: %s' % (base, last_err))
    dt = round(time.time() - t0, 1)
    mb = os.path.getsize(out_mp3) / (1024.0 * 1024.0)
    print('[تنزيل صوت] ✓ %s.mp3 (%.1f MB في %.1fث)' % (base, mb, dt), flush=True)
    return out_mp3, dt



def check_agy_usage():
    try:
        res = subprocess.run([AGY_BIN, '--usage'], capture_output=True, text=True, timeout=20)
        out = (res.stdout or '') + (res.stderr or '')
        print('[حصة agy]\n' + out.strip())
        return True
    except Exception as e:
        print('[تحذير] تعذر فحص agy --usage: %s' % e, file=sys.stderr)
        return False


def build_prompt(audio_filename, sheikh='', series='', title='', part_idx=None, total_parts=None):
    chunk_note = ''
    if part_idx is not None and total_parts is not None and total_parts > 1:
        chunk_note = f" هذا هو المقطع ({part_idx} من {total_parts}) من المحاضرة."
        if part_idx < total_parts:
            chunk_note += (
                " تنبيه صارم: ينتهي هذا المقطع في منتصف الكلام؛ توقّف فور انتهاء الصوت حرفيًا، "
                "ويُمنع منعًا باتًا إضافة أي دعاء ختامي (مثل: نسأل الله... أو وصلى الله على سيدنا محمد...) "
                "أو تلخيص في نهاية المقطع إذا لم يُسمع نصًا في آخر ثواني الصوت."
            )
    return (
        f"اقرأ الملف الصوتي @{audio_filename} مباشرة عبر أداة view_file فقط "
        "(يُمنع منعاً باتاً استخدام run_command أو read_url أو search_web أو بايثون أو whisper)."
        f"{chunk_note} "
        "سياق أكاديمي بحثي: هذا تسجيل صوتي لمحاضرة علمية/تاريخية/تراثية عربية لأغراض الأرشفة والفهرسة النصية الحرفية فقط. "
        "اكتب التفريغ النصي الكامل والحرفي بالعربية "
        "مع علامات الترقيم وفواصل الفقرات من أول ثانية إلى آخر ثانية في الملف. "
        "أخرج النص العربي فقط بلا أي تعليق أو مقدمة أو خاتمة. "
        "لا تلخّص، ولا تعيد أي جملة مرتين، ولا تكتب حواراً وهمياً."
    )


def _cleanup_agy_conv_db(conv_id):
    if not conv_id or not sys.platform.startswith('linux'):
        return
    base_dir = os.path.expanduser('~/.gemini/antigravity-cli')
    for sub, suffixes in (
        ('conversations', ('.pb', '.db', '.db-wal', '.db-shm')),
        ('annotations', ('.pbtxt',)),
        ('presence', ('.lock',)),
        ('implicit', ('.pb',)),
    ):
        sub_dir = os.path.join(base_dir, sub)
        for suffix in suffixes:
            p = os.path.join(sub_dir, conv_id + suffix)
            try:
                if os.path.exists(p):
                    os.remove(p)
            except OSError:
                pass
    brain_dir = os.path.join(base_dir, 'brain', conv_id)
    if os.path.isdir(brain_dir):
        shutil.rmtree(brain_dir, ignore_errors=True)



def extract_agy_json_response(stdout_text):
    """استخراج حقل response وبيانات usage من مخرجات agy JSON مع تنظيف قاعدة بيانات الجلسة المؤقتة."""
    txt = (stdout_text or '').strip()
    if not txt:
        return None, {}
    for line in reversed([l.strip() for l in txt.splitlines() if l.strip().startswith('{')]):
        try:
            payload = json.loads(line)
            if isinstance(payload, dict) and 'response' in payload:
                _cleanup_agy_conv_db(payload.get('conversation_id'))
                return (payload.get('response') or '').strip(), (payload.get('usage') or {})
        except Exception:
            pass
    idx = txt.find('{')
    ridx = txt.rfind('}')
    if idx != -1 and ridx > idx:
        try:
            payload = json.loads(txt[idx:ridx + 1])
            if isinstance(payload, dict) and 'response' in payload:
                _cleanup_agy_conv_db(payload.get('conversation_id'))
                return (payload.get('response') or '').strip(), (payload.get('usage') or {})
        except Exception:
            pass
    return None, {}


def _log_agy_usage(audio_path, dur_s, words, ar_chars, model, rc, elapsed_s, usage):
    ledger = os.environ.get('AGY_USAGE_LEDGER', '/tmp/agy_usage_ledger.jsonl')
    try:
        rec = {
            'ts': round(time.time(), 3),
            'audio': os.path.basename(audio_path),
            'dur_s': round(float(dur_s or 0.0), 2),
            'words': int(words),
            'ar_chars': int(ar_chars),
            'model': model,
            'rc': rc,
            'elapsed_s': round(float(elapsed_s), 2),
            'usage': usage or {},
        }
        with open(ledger, 'a', encoding='utf-8') as f:
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')
    except Exception:
        pass


from contextlib import contextmanager


def _is_quota_safe_for_background(model_hint='gemini'):
    """فحص الكوتة الحية: إبقاء >=15% في نافذة الـ5 ساعات (حماية 10% للوكيل الرئيسي) وإبقاء >=25% من الأسبوعية إلا في آخر 12 ساعة."""
    for qpath in ('/root/workspace/ytb-build/live_quota.json', '/tmp/agy_quota_snapshot.json'):
        if not os.path.exists(qpath):
            continue
        try:
            if time.time() - os.path.getmtime(qpath) > 1800:
                continue
            qdata = json.load(open(qpath, encoding='utf-8'))
            want_claude = any(k in (model_hint or '').lower() for k in ('claude', 'opus', 'sonnet'))
            for m in qdata.get('models', []):
                lbl = (m.get('label') or '').lower()
                if want_claude and ('claude' in lbl or 'opus' in lbl or 'sonnet' in lbl):
                    target = m
                    break
                if not want_claude and ('gemini 3.8 flash' in lbl or 'gemini 4 argon' in lbl):
                    target = m
                    break
            else:
                continue
            rem = float(target.get('remainingPercentage') if target.get('remainingPercentage') is not None else 1.0)
            reset_ms = float(target.get('timeUntilResetMs') or 0.0)
            reset_hours = reset_ms / (1000.0 * 3600.0)
            if target.get('isExhausted') or rem < 0.15:
                return False, f'الكوتة المتبقية ({rem*100:.1f}%) أقل من حد الأمان للخلفية (15% لحماية الـ10% للوكيل الرئيسي)'
            if reset_hours > 5.5 and reset_hours > 12.0 and rem <= 0.25:
                return False, f'الكوتة الأسبوعية ({rem*100:.1f}%) وصلت احتياطي الـ25% وباقي {reset_hours:.1f}س (> 12س) على التجديد'
            return True, ''
        except Exception:
            continue
    return True, ''


@contextmanager
def _global_agy_slot(min_avail_mb=1350, model_hint='gemini'):
    while True:
        ok_q, reason_q = _is_quota_safe_for_background(model_hint)
        if ok_q:
            break
        print(f'[حارس الكوتة] إيقاف مؤقت لعمال الخلفية لمدة 60ث: {reason_q}', flush=True)
        time.sleep(60.0)

    if not sys.platform.startswith('linux'):
        yield
        return
    import fcntl
    max_slots = int(os.environ.get('MAX_GLOBAL_AGY', '20'))
    ramp_lock_path = '/tmp/agy_ramp.lock'
    slot_fd = None
    try:
        while slot_fd is None:
            # 1) فحص الذاكرة المتاحة قبل محاولة حجز خانة
            avail = 4096
            try:
                with open('/proc/meminfo', encoding='utf-8') as f:
                    for line in f:
                        if line.startswith('MemAvailable:'):
                            avail = int(line.split()[1]) // 1024
                            break
            except Exception:
                pass
            if avail >= min_avail_mb:
                for idx in range(max_slots):
                    spath = f'/tmp/agy_slot_{idx:02d}.lock'
                    fd = os.open(spath, os.O_CREAT | os.O_RDWR, 0o666)
                    try:
                        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        slot_fd = fd
                        break
                    except OSError:
                        os.close(fd)
            if slot_fd is None:
                time.sleep(2.0)

        # 2) مباعدة إطلاق العمليات بمقدار 1.0 ثانية حتى تستقر قراءة الذاكرة لكل عملية جديدة
        try:
            with open(ramp_lock_path, 'w') as rlf:
                fcntl.flock(rlf, fcntl.LOCK_EX)
                time.sleep(1.0)
        except Exception:
            pass

        yield
    finally:
        if slot_fd is not None:
            try:
                os.close(slot_fd)
            except OSError:
                pass


def transcribe_single_file(audio_path, model, sheikh, series, title, part_idx=None, total_parts=None, min_words=200, timeout_s=240, retries=3, stagger_s=0.0, sem=None, dur_s=0.0):
    """تشغيل agy داخل مجلد مؤقت معزول مع حجز خانة عالمية محمية بقفل النواة طوال مدة عمل العملية."""
    if stagger_s > 0:
        time.sleep(stagger_s)
    cur_model = model or 'gemini-3.8-flash-high'
    audio_fallbacks = [
        'gemini-3.8-flash-high',
        'gemini-4-argon-high',
        'gemini-3.8-flash-medium',
        'gemini-4-argon-medium',
        'gemini-3.8-flash-low',
    ]
    tried_models = {cur_model}
    for attempt in range(1, retries + 1):
        if sem is not None:
            sem.acquire()
        try:
            with tempfile.TemporaryDirectory(prefix='agy_tr_') as raw_tmpdir:
                tmpdir = os.path.realpath(raw_tmpdir)
                ext = os.path.splitext(audio_path)[1] or '.mp3'
                local_name = 'lesson_audio' + ext
                local_audio = os.path.join(tmpdir, local_name)
                try:
                    os.link(os.path.realpath(audio_path), local_audio)
                except Exception:
                    shutil.copy2(os.path.realpath(audio_path), local_audio)

                prompt = build_prompt(local_name, sheikh, series, title, part_idx, total_parts)
                cmd = [
                    AGY_BIN, '-p', prompt,
                    '--dangerously-skip-permissions',
                    '--disable-slash-commands',
                    '--output-format', 'json',
                ]
                if cur_model:
                    cmd += ['--model', cur_model]
                try:
                    with _global_agy_slot(int(os.environ.get('MIN_CHUNK_AVAIL_MB', '1350'))):
                        t0 = time.time()
                        res = subprocess.run(
                            cmd, cwd=tmpdir, capture_output=True, text=True, timeout=timeout_s
                        )
                        elapsed = round(time.time() - t0, 1)
                    parsed_resp, usage = extract_agy_json_response(res.stdout)
                    raw_out = parsed_resp if parsed_resp is not None else (res.stdout or '').strip()
                    cleaned, _ = strip_preamble_and_header(raw_out)
                    ar_chars = len(AR_RE.findall(cleaned))
                    words = len(cleaned.split())
                    _log_agy_usage(audio_path, dur_s, words, ar_chars, cur_model, res.returncode, elapsed, usage)
                    min_ar = min(300, max(40, min_words * 3))
                    max_words_cap = int((dur_s / 60.0) * 215.0) if dur_s >= 60.0 else 999999
                    w_list = cleaned.split()
                    has_rep_loop = False
                    if len(re.findall(r'[ٹڈڑںےگچپژ]', cleaned)) >= 3:
                        has_rep_loop = True
                    if len(w_list) >= 60:
                        from collections import Counter
                        ngrams = Counter(tuple(w_list[i:i + 6]) for i in range(len(w_list) - 5))
                        if ngrams and ngrams.most_common(1)[0][1] >= 10:
                            has_rep_loop = True
                    retry_min_words = max(45, int(min_words * 0.55)) if dur_s >= 180.0 else 15
                    if not has_rep_loop and 'use-policy' not in raw_out.lower() and words <= max_words_cap and (
                        (ar_chars >= min_ar and words >= min_words)
                        or (attempt >= 2 and res.returncode == 0 and ar_chars >= 60 and words >= retry_min_words)
                        or (dur_s > 0 and dur_s < 60.0 and res.returncode == 0 and ar_chars >= 20 and words >= 5)
                    ):
                        return cleaned.strip(), elapsed
                    sample = (cleaned[:180] if cleaned else ((res.stderr or '') + ' ' + (res.stdout or ''))[-240:]).replace('\n', ' ')
                    print('  [محاولة %d/%d · %s] مخرجات قصيرة أو غير صالحة/هلوسة (rc=%s, words=%d/%d..%d, loop=%s, ar=%d): %s' % (
                        attempt, retries, cur_model, res.returncode, words, min_words, max_words_cap, has_rep_loop, ar_chars, sample
                    ), flush=True)
                    err_low = (raw_out + ' ' + (res.stderr or '') + ' ' + (res.stdout or '')).lower()
                    if any(k in err_low for k in ('unsupported mime type', 'use-policy', 'policies.google.com', 'cannot fulfill', 'invalid model')) or (res.returncode == 0 and words == 0):
                        for fb in audio_fallbacks:
                            if fb not in tried_models:
                                print('  [تبديل تلقائي للنموذج] تعثر/رفض سياسة في %s ⇒ التحويل إلى %s' % (cur_model, fb), flush=True)
                                cur_model = fb
                                tried_models.add(fb)
                                break
                except subprocess.TimeoutExpired:
                    print('  [محاولة %d/%d] انتهت مهلة agy (%dث)' % (attempt, retries, timeout_s), flush=True)
                except Exception as e:
                    print('  [محاولة %d/%d] خطأ: %s' % (attempt, retries, e), flush=True)
        finally:
            if sem is not None:
                sem.release()
        time.sleep(2)

    if dur_s > 240:
        mid_s = round(dur_s / 2.0, 2)
        print('  [إنقاذ تلقائي] تقسيم المقطع المتعثر (%.1fد) إلى نصفين (%.1fد + %.1fد) وإعادة تفريغهما...' % (
            dur_s / 60.0, mid_s / 60.0, (dur_s - mid_s) / 60.0
        ), flush=True)
        with tempfile.TemporaryDirectory(prefix='agy_subsplit_') as sub_dir:
            p1 = os.path.join(sub_dir, 'sub_0.mp3')
            p2 = os.path.join(sub_dir, 'sub_1.mp3')
            try:
                subprocess.run(
                    [FFMPEG_BIN, '-y', '-loglevel', 'error', '-i', audio_path, '-t', str(mid_s), '-c:a', 'copy', p1],
                    check=True, timeout=60
                )
                subprocess.run(
                    [FFMPEG_BIN, '-y', '-loglevel', 'error', '-ss', str(mid_s), '-i', audio_path, '-c:a', 'copy', p2],
                    check=True, timeout=60
                )
                sub_min = max(15, min_words // 3)
                t1, e1 = transcribe_single_file(
                    p1, model, sheikh, series, title, part_idx=part_idx, total_parts=total_parts,
                    min_words=sub_min, timeout_s=timeout_s, retries=2, sem=sem, dur_s=mid_s
                )
                if t1:
                    t2, e2 = transcribe_single_file(
                        p2, model, sheikh, series, title, part_idx=part_idx, total_parts=total_parts,
                        min_words=sub_min, timeout_s=timeout_s, retries=2, sem=sem, dur_s=(dur_s - mid_s)
                    )
                    if t2:
                        return deduplicate_chunk_boundary_overlap([t1.strip(), t2.strip()]), round(e1 + e2, 1)
            except Exception as e:
                print('  [تحذير إنقاذ] تعذر تقسيم المقطع المتعثر: %s' % e, flush=True)
    return '', 0.0


def detect_silence_near_target(audio_path, target_s, tol_s=25.0):
    """رصد أقرب سكتة طبيعية حول نقطة القطع المستهدفة فقط (±tol_s) عبر القفز الفوري -ss قبل -i لتجنب فك ضغط المحاضرة كاملة."""
    win_start = max(0.0, round(target_s - tol_s, 2))
    win_dur = round(tol_s * 2.0, 2)
    try:
        res = subprocess.run(
            [FFMPEG_BIN, '-nostats', '-ss', str(win_start), '-t', str(win_dur),
             '-i', audio_path, '-af', 'silencedetect=noise=-32dB:d=0.35', '-f', 'null', '-'],
            capture_output=True, text=True, timeout=10
        )
        cands = []
        for m in re.finditer(r'silence_end:\s*([0-9.]+)\s*\|\s*silence_duration:\s*([0-9.]+)', res.stderr or ''):
            rel_end = float(m.group(1))
            dur_sil = float(m.group(2))
            abs_mid = round(win_start + rel_end - dur_sil / 2.0, 2)
            cands.append((abs_mid, dur_sil))
        if cands:
            return max(cands, key=lambda x: x[1] - abs(x[0] - target_s) * 0.01)[0]
    except Exception:
        pass
    return round(target_s, 2)


def split_audio_chunks(audio_path, dur_s, chunk_minutes, tmpdir, tol_s=25.0):
    """تقسيم الملف الصوتي الطويل إلى مقاطع متتالية بتمريرة واحدة (-f segment -c:a copy) بلا استهلاك للمعالج."""
    actual_dur = get_audio_duration(audio_path)
    if actual_dur > 1.0:
        dur_s = actual_dur
    chunk_s = float(chunk_minutes * 60.0)
    n_chunks = max(1, int(math.ceil(dur_s / chunk_s)))

    use_fast_copy = os.environ.get('FAST_SEGMENT_COPY', '1') == '1'
    cut_points = [0.0]
    for idx in range(1, n_chunks):
        target = round(idx * (dur_s / n_chunks), 2)
        if use_fast_copy:
            cut_points.append(target)
        else:
            best_m = detect_silence_near_target(audio_path, target, tol_s=tol_s)
            if best_m <= cut_points[-1] + 60.0 or best_m >= dur_s - 45.0:
                best_m = target
            cut_points.append(best_m)
    cut_points.append(round(dur_s, 2))

    if len(cut_points) >= 3 and (cut_points[-1] - cut_points[-2]) < 45.0:
        cut_points.pop(-2)

    ext = os.path.splitext(audio_path)[1] or '.mp3'
    if len(cut_points) <= 2:
        cpath = os.path.join(tmpdir, 'chunk_00' + ext)
        shutil.copy2(audio_path, cpath)
        return [(cpath, 0.0, round(dur_s, 2))]

    seg_times = ','.join('%.2f' % pt for pt in cut_points[1:-1])
    out_pattern = os.path.join(tmpdir, 'chunk_%02d' + ext)
    codec_args = ['-c:a', 'copy'] if ext.lower() == '.mp3' else ['-ar', '16000', '-ac', '1', '-b:a', '64k']
    subprocess.run(
        [FFMPEG_BIN, '-y', '-loglevel', 'error', '-i', audio_path,
         '-vn'] + codec_args + [
         '-f', 'segment', '-segment_times', seg_times,
         '-reset_timestamps', '1', out_pattern],
        check=True
    )

    specs = []
    for idx in range(len(cut_points) - 1):
        st_s = cut_points[idx]
        length_s = round(cut_points[idx + 1] - st_s, 2)
        cpath = os.path.join(tmpdir, 'chunk_%02d%s' % (idx, ext))
        if os.path.exists(cpath) and os.path.getsize(cpath) > 4096:
            specs.append((cpath, st_s, length_s))
    return specs


def main():
    import threading
    ap = argparse.ArgumentParser(description='تفريغ الدروس الصوتية عبر agy مع تقطيع تلقائي للمحاضرات الطويلة')
    ap.add_argument('series_dir', help='مجلد السلسلة الذي يحوي _meta.json والملفات الصوتية')
    ap.add_argument('--only', default='', help='أرقام دروس محددة مفصولة بفاصلة (مثل 001,004)')
    ap.add_argument('--model', default=os.environ.get('TRANSCRIBE_MODEL', 'gemini-3.8-flash-high'),
                    help='نموذج Gemini الصوتي في agy (الافتراضي: gemini-3.8-flash-high)')
    ap.add_argument('--max-single-minutes', type=float, default=15.0,
                    help='أقصى مدة بالدقائق لتفريغ الدرس في استدعاء واحد قبل تقسيمه تلقائيًا (الافتراضي: 15)')
    ap.add_argument('--chunk-minutes', type=float, default=12.0,
                    help='طول كل مقطع بالدقائق عند تقسيم الدروس الطويلة (الافتراضي: 12)')
    default_workers = 4 if sys.platform == 'darwin' else 2
    ap.add_argument('--workers', type=int, default=default_workers,
                    help='عدد المقاطع/الدروس التي تُفرّغ بالتوازي (الافتراضي: 4 على الماك، 2 على الخادم)')
    ap.add_argument('--min-wpm', type=float, default=45.0,
                    help='أدنى معدل كلمات/دقيقة لاعتبار التفريغ مكتملًا')
    ap.add_argument('--force', action='store_true', help='إعادة التفريغ حتى لو وُجد ملف .txt سليم')
    ap.add_argument('--check-usage', action='store_true', help='عرض حصة agy قبل البدء')
    args = ap.parse_args()

    if args.check_usage:
        check_agy_usage()

    meta_path = os.path.join(args.series_dir, '_meta.json')
    meta = json.load(open(meta_path, encoding='utf-8')) if os.path.exists(meta_path) else {}
    sheikh = meta.get('sheikh', '')
    series = meta.get('series', '')
    videos_by_prefix = {}
    for v in meta.get('videos', []):
        if v.get('n') is not None and v.get('vid'):
            videos_by_prefix['%03d_%s' % (int(v['n']), v['vid'])] = v

    only_set = set()
    if args.only:
        for item in args.only.split(','):
            item = item.strip()
            if item.isdigit():
                only_set.add('%03d' % int(item))
            elif item:
                only_set.add(item)

    worker_limit = max(1, args.workers)
    agy_sem = threading.Semaphore(worker_limit)
    split_lock = threading.Lock()
    long_lesson_sem = threading.Semaphore(2)

    def process_audio_file(audio_path):
        base = os.path.splitext(os.path.basename(audio_path))[0]
        num_prefix = base.split('_')[0]
        if only_set and (num_prefix not in only_set and base not in only_set):
            return True

        vinfo = videos_by_prefix.get(base, {})
        actual_dur = get_audio_duration(audio_path)
        dur_s = actual_dur if actual_dur > 1.0 else float(vinfo.get('dur_s') or 0.0)
        dur_m = dur_s / 60.0 if dur_s > 0 else 0.0
        title = vinfo.get('title', base)
        txt_path = os.path.join(args.series_dir, base + '.txt')

        if os.path.exists(txt_path) and not args.force:
            existing_txt = open(txt_path, encoding='utf-8', errors='replace').read()
            cleaned_ex, _ = strip_preamble_and_header(existing_txt)
            w_ex = len(cleaned_ex.split())
            wpm_ex = (w_ex / dur_m) if dur_m > 0 else 999.0
            if w_ex >= max(12, int(dur_m * 24)) and wpm_ex >= min(args.min_wpm, 24.0) and (dur_m < 1.0 or wpm_ex <= 215.0):
                print('[تخطي] %s سليم مسبقًا (%d كلمة · %.1f ك/د)' % (base, w_ex, wpm_ex), flush=True)
                return True

        t_start = time.time()
        if dur_m > args.max_single_minutes:
            with long_lesson_sem:
                print('[تفريغ] %s | المدة=%.1fد | العنوان=«%s»' % (base, dur_m, title[:65]), flush=True)
                with tempfile.TemporaryDirectory(prefix='agy_chunks_') as cdir:
                    with split_lock:
                        chunks = split_audio_chunks(audio_path, dur_s, args.chunk_minutes, cdir)
                    print('  -> قُسّم الدرس الطويل (%.1fد) إلى %d مقاطع (كل مقطع ~%.0fد · توازي=%d)' % (
                        dur_m, len(chunks), args.chunk_minutes, worker_limit
                    ), flush=True)

                    chunk_cache_path = os.path.join(args.series_dir, f'.chunk_cache_{base}.json')
                    cached_chunks = {}
                    if os.path.exists(chunk_cache_path) and not args.force:
                        try:
                            cd = json.load(open(chunk_cache_path, encoding='utf-8'))
                            if cd.get('n_chunks') == len(chunks) and isinstance(cd.get('parts'), dict):
                                cached_chunks = cd['parts']
                        except Exception:
                            cached_chunks = {}
                    cache_lock = threading.Lock()

                    def _is_dead_silent_chunk(cpath, max_vol_floor_db=-48.0):
                        try:
                            vr = subprocess.run(
                                [FFMPEG_BIN, '-nostdin', '-ss', '0', '-t', '900', '-i', cpath, '-af', 'volumedetect', '-f', 'null', '-'],
                                capture_output=True, text=True, timeout=20
                            )
                            m_max = re.search(r'max_volume:\s*([-0-9.]+)\s*dB', vr.stderr or '')
                            if m_max and float(m_max.group(1)) <= max_vol_floor_db:
                                return True, float(m_max.group(1))
                        except Exception:
                            pass
                        return False, 0.0

                    def _run_chunk(item):
                        idx, (cpath, st_s, len_s) = item
                        if str(idx) in cached_chunks and cached_chunks[str(idx)]:
                            c_txt = cached_chunks[str(idx)]
                            print('     [استرجاع كاش ✓] المقطع %d/%d (%.1fد): %d كلمة محفوظة مسبقاً' % (
                                idx, len(chunks), len_s / 60.0, len(c_txt.split())
                            ), flush=True)
                            return idx, len_s, c_txt, 0.0
                        is_sil, max_v = _is_dead_silent_chunk(cpath)
                        if is_sil:
                            print('     [تخطي مقطع صامت] المقطع %d/%d (%.1fد) صمت رقمي خالص (max_volume=%.1f dB) — تخطي تفريغه لمنع الهلوسة' % (
                                idx, len(chunks), len_s / 60.0, max_v
                            ), flush=True)
                            return idx, len_s, '__SILENT_CHUNK__', 0.0
                        req_w = max(50, int((len_s / 60.0) * 24))
                        stg = (idx - 1) * 0.8 if idx <= worker_limit else 0.0
                        ptxt, elapsed = transcribe_single_file(
                            cpath, args.model, sheikh, series, title,
                            part_idx=idx, total_parts=len(chunks), min_words=req_w,
                            stagger_s=stg, sem=agy_sem, dur_s=len_s
                        )
                        if ptxt and ptxt != '__SILENT_CHUNK__':
                            with cache_lock:
                                cached_chunks[str(idx)] = ptxt
                                try:
                                    with open(chunk_cache_path + '.tmp', 'w', encoding='utf-8') as cf:
                                        json.dump({'n_chunks': len(chunks), 'parts': cached_chunks}, cf, ensure_ascii=False)
                                    os.replace(chunk_cache_path + '.tmp', chunk_cache_path)
                                except Exception:
                                    pass
                        return idx, len_s, ptxt, elapsed

                    results = {}
                    ok = True
                    with concurrent.futures.ThreadPoolExecutor(max_workers=min(worker_limit, len(chunks))) as pool:
                        futs = [pool.submit(_run_chunk, (idx, ch)) for idx, ch in enumerate(chunks, 1)]
                        for fut in concurrent.futures.as_completed(futs):
                            idx, len_s, ptxt, elapsed = fut.result()
                            if ptxt == '__SILENT_CHUNK__':
                                results[idx] = ''
                            elif not ptxt:
                                ok = False
                                print('  [!] فشل تفريغ المقطع %d/%d لـ %s' % (idx, len(chunks), base), flush=True)
                            else:
                                cw = len(ptxt.split())
                                cwpm = cw / (len_s / 60.0) if len_s > 0 else 0.0
                                if elapsed > 0:
                                    print('     ✓ المقطع %d/%d (%.1fد): %d كلمة (%.1f ك/د) في %.1fث' % (
                                        idx, len(chunks), len_s / 60.0, cw, cwpm, elapsed
                                    ), flush=True)
                                results[idx] = ptxt
                    parts_txt = [results[i] for i in range(1, len(chunks) + 1) if results.get(i)]
                    full_txt = deduplicate_chunk_boundary_overlap(parts_txt) if (ok and len(results) == len(chunks) and parts_txt) else ''
                    if full_txt and os.path.exists(chunk_cache_path):
                        try:
                            os.remove(chunk_cache_path)
                        except OSError:
                            pass
        else:
            print('[تفريغ] %s | المدة=%.1fد | العنوان=«%s»' % (base, dur_m, title[:65]), flush=True)
            req_w = (max(6, int(dur_m * 10)) if dur_m < 1.0 else max(12, int(dur_m * 24))) if dur_m > 0 else 40
            full_txt, _ = transcribe_single_file(
                audio_path, args.model, sheikh, series, title,
                min_words=req_w, sem=agy_sem, dur_s=dur_s
            )

        if not full_txt:
            print('[✗ فشل] لم يكتمل تفريغ %s' % base, flush=True)
            return False

        cleaned_final, _ = strip_preamble_and_header(full_txt)
        total_words = len(cleaned_final.split())
        total_wpm = (total_words / dur_m) if dur_m > 0 else 0.0
        with open(txt_path, 'w', encoding='utf-8') as f:
            f.write(cleaned_final)
        mp = txt_path[:-4] + '.meta.json'
        md = {}
        if os.path.exists(mp):
            try:
                md = json.load(open(mp, encoding='utf-8'))
            except Exception:
                md = {}
        md.update({
            'dur_s': round(dur_s, 1),
            'chars': len(cleaned_final),
            'words': total_words,
            'wpm': round(total_wpm, 1),
            'model': args.model,
            'ok': True,
        })
        json.dump(md, open(mp, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
        if sys.platform.startswith('linux') and os.path.exists(txt_path) and os.path.getsize(txt_path) > 50:
            bridge_ready = '/root/workspace/align-bridge/ready'
            align_json_path = os.path.join(args.series_dir, base + '.align.json')
            if os.path.isdir(bridge_ready) and not os.path.exists(align_json_path) and audio_path and os.path.exists(audio_path):
                try:
                    import hashlib
                    existing_opus = [x for x in os.listdir(bridge_ready) if x.endswith('.opus')]
                    if len(existing_opus) < 120:
                        s_parts = os.path.normpath(args.series_dir).split(os.sep)
                        sch_slug, ser_slug = s_parts[-2], s_parts[-1]
                        h_key = f'{sch_slug}__{ser_slug}__{base}'
                        opus_dst = os.path.join(bridge_ready, h_key + '.opus')
                        job_dst = os.path.join(bridge_ready, h_key + '.job.json')
                        if not os.path.exists(opus_dst):
                            tmp_opus = opus_dst + '.part.opus'
                            subprocess.run(
                                ['ffmpeg', '-nostdin', '-y', '-loglevel', 'error', '-i', audio_path,
                                 '-vn', '-ac', '1', '-ar', '16000', '-c:a', 'libopus', '-b:a', '12k',
                                 '-vbr', 'on', '-compression_level', '0', '-threads', '1',
                                 '-application', 'voip', tmp_opus],
                                timeout=180, check=False
                            )
                            if os.path.exists(tmp_opus) and os.path.getsize(tmp_opus) > 1000:
                                os.replace(tmp_opus, opus_dst)
                                with open(job_dst, 'w', encoding='utf-8') as jf:
                                    json.dump({
                                        'key': h_key,
                                        'vid': base.split('_', 1)[1] if '_' in base else base,
                                        'stem': base,
                                        'sheikh': sch_slug,
                                        'row': ser_slug,
                                        'txt_path': txt_path,
                                        'dur_s': round(dur_s, 1),
                                        'opus_bytes': os.path.getsize(opus_dst),
                                        'created_at': time.time(),
                                    }, jf, ensure_ascii=False, indent=2)
                except Exception:
                    pass
            for ext_del in ('.mp3', '.webm', '.m4a', '.wav'):
                cand_del = os.path.join(args.series_dir, base + ext_del)
                if os.path.exists(cand_del):
                    try:
                        os.remove(cand_del)
                    except OSError:
                        pass
        print('[✓ تم] %s | %d كلمة | %.1f ك/د | الزمن=%.1fث' % (
            os.path.basename(txt_path), total_words, total_wpm, time.time() - t_start
        ), flush=True)
        return True

    # 1) فحص الملفات الصوتية الموجودة حالياً على القرص والتأكد من اكتمال مدتها قبل البدء بتفريغها
    raw_existing = sorted(
        f for ext in ('*.mp3', '*.m4a', '*.wav')
        for f in glob.glob(os.path.join(args.series_dir, ext))
        if not os.path.basename(f).startswith('_') and not f.endswith('.part.mp3')
    )
    existing_audio = []
    for apath in raw_existing:
        b = os.path.splitext(os.path.basename(apath))[0]
        exp_dur = float(videos_by_prefix.get(b, {}).get('dur_s') or 0.0)
        if is_valid_audio_file(apath, exp_dur):
            existing_audio.append(apath)
        else:
            print('[تنبيه] حذف ملف صوتي غير مكتمل: %s (سيُعاد تحويله/تنزيله)' % os.path.basename(apath), flush=True)
            try:
                os.remove(apath)
            except OSError:
                pass

    valid_bases = {os.path.splitext(os.path.basename(p))[0] for p in existing_audio}
    submitted_bases = set()
    to_dl = []
    for v in meta.get('videos', []):
        if v.get('n') is None or not v.get('vid'):
            continue
        n_int = int(v['n'])
        vid = v['vid']
        num_prefix = '%03d' % n_int
        base = '%03d_%s' % (n_int, vid)
        if only_set and (num_prefix not in only_set and base not in only_set and vid not in only_set):
            continue
        exp_dur = float(v.get('dur_s') or 0.0)
        direct_url = v.get('url') or ''
        if base not in valid_bases:
            to_dl.append((n_int, vid, exp_dur, direct_url))

    with concurrent.futures.ThreadPoolExecutor(max_workers=worker_limit) as tr_pool:
        tr_futs = []
        for apath in existing_audio:
            b = os.path.splitext(os.path.basename(apath))[0]
            num_prefix = b.split('_')[0]
            if only_set and (num_prefix not in only_set and b not in only_set):
                continue
            submitted_bases.add(b)
            tr_futs.append(tr_pool.submit(process_audio_file, apath))

        if to_dl:
            dl_w = min(3, worker_limit, len(to_dl))
            print('[تنزيل متوازي مع التفريغ] جارٍ تنزيل/استكمال %d ملفًا صوتيًا ناقصًا (توازي=%d)...' % (len(to_dl), dl_w), flush=True)
            with concurrent.futures.ThreadPoolExecutor(max_workers=dl_w) as dl_pool:
                dl_futs = {
                    dl_pool.submit(download_lesson_audio, args.series_dir, n_int, vid, exp_dur, 3, d_url): (n_int, vid)
                    for n_int, vid, exp_dur, d_url in to_dl
                }
                for dfut in concurrent.futures.as_completed(dl_futs):
                    try:
                        dl_path, _ = dfut.result()
                        if dl_path and os.path.exists(dl_path):
                            b = os.path.splitext(os.path.basename(dl_path))[0]
                            if b not in submitted_bases:
                                submitted_bases.add(b)
                                tr_futs.append(tr_pool.submit(process_audio_file, dl_path))
                    except Exception as e:
                        print('[تحذير تنزيل] %s' % e, file=sys.stderr, flush=True)

        if not tr_futs and not to_dl:
            raise SystemExit('لا توجد ملفات صوتية في: %s' % args.series_dir)

        for tfut in concurrent.futures.as_completed(tr_futs):
            try:
                tfut.result()
            except Exception as e:
                print('[تحذير تفريغ] %s' % e, file=sys.stderr, flush=True)



if __name__ == '__main__':
    main()

