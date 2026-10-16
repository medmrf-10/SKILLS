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
from sanitize_preamble import strip_preamble_and_header  # noqa: E402

AR_RE = re.compile(r'[\u0600-\u06FF]')


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
        "(يُمنع منعاً باتاً استخدام run_command أو بايثون أو whisper)."
        f"{chunk_note} "
        "هذا تسجيل صوتي لمحاضرة علمية عربية. اكتب التفريغ النصي الكامل والحرفي بالعربية "
        "مع علامات الترقيم وفواصل الفقرات من أول ثانية إلى آخر ثانية في الملف. "
        "أخرج النص العربي فقط بلا أي تعليق أو مقدمة أو خاتمة. "
        "لا تلخّص، ولا تعيد أي جملة مرتين، ولا تكتب حواراً وهمياً."
    )


def extract_agy_json_response(stdout_text):
    """استخراج حقل response من مخرجات agy JSON سواء كانت في سطر واحد أو متعددة الأسطر."""
    txt = (stdout_text or '').strip()
    if not txt:
        return None
    for line in reversed([l.strip() for l in txt.splitlines() if l.strip().startswith('{')]):
        try:
            payload = json.loads(line)
            if isinstance(payload, dict) and 'response' in payload:
                return (payload.get('response') or '').strip()
        except Exception:
            pass
    idx = txt.find('{')
    ridx = txt.rfind('}')
    if idx != -1 and ridx > idx:
        try:
            payload = json.loads(txt[idx:ridx + 1])
            if isinstance(payload, dict) and 'response' in payload:
                return (payload.get('response') or '').strip()
        except Exception:
            pass
    return None


def transcribe_single_file(audio_path, model, sheikh, series, title, part_idx=None, total_parts=None, min_words=200, timeout_s=240, retries=3, stagger_s=0.0):
    """تشغيل agy داخل مجلد مؤقت معزول (مع حل المسار الحقيقي realpath على macOS) بدون --dangerously-skip-permissions لمنع تشغيل أوامر طرفية خارجية."""
    if stagger_s > 0:
        time.sleep(stagger_s)
    for attempt in range(1, retries + 1):
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
                '--output-format', 'json',
            ]
            if model:
                cmd += ['--model', model]
            t0 = time.time()
            try:
                res = subprocess.run(
                    cmd, cwd=tmpdir, capture_output=True, text=True, timeout=timeout_s
                )
                parsed_resp = extract_agy_json_response(res.stdout)
                raw_out = parsed_resp if parsed_resp is not None else (res.stdout or '').strip()
                cleaned, _ = strip_preamble_and_header(raw_out)
                ar_chars = len(AR_RE.findall(cleaned))
                words = len(cleaned.split())
                if ar_chars >= 300 and words >= min_words:
                    return cleaned.strip(), round(time.time() - t0, 1)
                sample = (cleaned[:180] if cleaned else ((res.stderr or '') + ' ' + (res.stdout or ''))[-240:]).replace('\n', ' ')
                print('  [محاولة %d/%d] مخرجات قصيرة أو غير صالحة (rc=%s, words=%d/%d, ar=%d): %s' % (
                    attempt, retries, res.returncode, words, min_words, ar_chars, sample
                ), flush=True)
            except subprocess.TimeoutExpired:
                print('  [محاولة %d/%d] انتهت مهلة agy (%dث)' % (attempt, retries, timeout_s), flush=True)
            except Exception as e:
                print('  [محاولة %d/%d] خطأ: %s' % (attempt, retries, e), flush=True)
            time.sleep(3)
    return '', 0.0


def detect_silence_midpoints(audio_path):
    """رصد منتصفات فترات الصمت الطبيعي (≥ 0.35 ثانية) عبر ffmpeg silencedetect في أقل من ثانية."""
    try:
        res = subprocess.run(
            [FFMPEG_BIN, '-nostats', '-i', audio_path,
             '-af', 'silencedetect=noise=-32dB:d=0.35', '-f', 'null', '-'],
            capture_output=True, text=True, timeout=30
        )
        mids = []
        for m in re.finditer(r'silence_end:\s*([0-9.]+)\s*\|\s*silence_duration:\s*([0-9.]+)', res.stderr or ''):
            end_s = float(m.group(1))
            dur_sil = float(m.group(2))
            mids.append((round(end_s - dur_sil / 2.0, 2), dur_sil))
        return mids
    except Exception:
        return []


def split_audio_chunks(audio_path, dur_s, chunk_minutes, tmpdir, tol_s=25.0):
    """تقسيم الملف الصوتي الطويل إلى مقاطع متتالية عبر ffmpeg عند منتصفات فواصل الصمت الطبيعي."""
    chunk_s = float(chunk_minutes * 60.0)
    n_chunks = max(1, int(math.ceil(dur_s / chunk_s)))
    sil_mids = detect_silence_midpoints(audio_path) if n_chunks > 1 else []

    # تحديد نقاط القطع المثالية بمحاذاة أقرب سكتة طبيعية ضمن ±tol_s
    cut_points = [0.0]
    for idx in range(1, n_chunks):
        target = idx * (dur_s / n_chunks)
        cands = [(m, d) for (m, d) in sil_mids if abs(m - target) <= tol_s and m > cut_points[-1] + 60.0]
        if cands:
            # فضّل السكتة الأطول القريبة من الهدف
            best_m = max(cands, key=lambda x: x[1] - abs(x[0] - target) * 0.01)[0]
            cut_points.append(best_m)
        else:
            cut_points.append(round(target, 2))
    cut_points.append(round(dur_s, 2))

    chunks = []
    ext = os.path.splitext(audio_path)[1] or '.mp3'
    for idx in range(len(cut_points) - 1):
        st_s = cut_points[idx]
        length_s = round(cut_points[idx + 1] - st_s, 2)
        if length_s < 45 and chunks:
            prev_path, prev_st, prev_len = chunks[-1]
            new_len = round(prev_len + length_s, 2)
            subprocess.run(
                [FFMPEG_BIN, '-y', '-loglevel', 'error', '-ss', str(prev_st), '-t', str(new_len),
                 '-i', audio_path, '-acodec', 'copy', prev_path],
                check=True
            )
            chunks[-1] = (prev_path, prev_st, new_len)
            break
        cpath = os.path.join(tmpdir, 'chunk_%02d%s' % (idx + 1, ext))
        subprocess.run(
            [FFMPEG_BIN, '-y', '-loglevel', 'error', '-ss', str(st_s), '-t', str(length_s),
             '-i', audio_path, '-acodec', 'copy', cpath],
            check=True
        )
        chunks.append((cpath, st_s, length_s))
    return chunks


def main():
    ap = argparse.ArgumentParser(description='تفريغ الدروس الصوتية عبر agy مع تقطيع تلقائي للمحاضرات الطويلة')
    ap.add_argument('series_dir', help='مجلد السلسلة الذي يحوي _meta.json والملفات الصوتية')
    ap.add_argument('--only', default='', help='أرقام دروس محددة مفصولة بفاصلة (مثل 001,004)')
    ap.add_argument('--model', default=os.environ.get('TRANSCRIBE_MODEL', ''), help='نموذج Gemini في agy (الافتراضي: النموذج الافتراضي في agy)')
    ap.add_argument('--max-single-minutes', type=float, default=15.0,
                    help='أقصى مدة بالدقائق لتفريغ الدرس في استدعاء واحد قبل تقسيمه تلقائيًا (الافتراضي: 15)')
    ap.add_argument('--chunk-minutes', type=float, default=12.0,
                    help='طول كل مقطع بالدقائق عند تقسيم الدروس الطويلة (الافتراضي: 12)')
    default_workers = 4 if sys.platform == 'darwin' else 2
    ap.add_argument('--workers', type=int, default=default_workers,
                    help='عدد المقاطع التي تُفرّغ بالتوازي للدرس الطويل (الافتراضي: 4 على الماك، 2 على الخادم)')
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

    audio_files = sorted(
        f for ext in ('*.mp3', '*.m4a', '*.wav')
        for f in glob.glob(os.path.join(args.series_dir, ext))
        if not os.path.basename(f).startswith('_')
    )
    if not audio_files:
        raise SystemExit('لا توجد ملفات صوتية في: %s' % args.series_dir)

    for audio_path in audio_files:
        base = os.path.splitext(os.path.basename(audio_path))[0]
        num_prefix = base.split('_')[0]
        if only_set and (num_prefix not in only_set and base not in only_set):
            continue

        vinfo = videos_by_prefix.get(base, {})
        dur_s = float(vinfo.get('dur_s') or 0.0) or get_audio_duration(audio_path)
        dur_m = dur_s / 60.0 if dur_s > 0 else 0.0
        title = vinfo.get('title', base)
        txt_path = os.path.join(args.series_dir, base + '.txt')

        if os.path.exists(txt_path) and not args.force:
            existing_txt = open(txt_path, encoding='utf-8', errors='replace').read()
            cleaned_ex, _ = strip_preamble_and_header(existing_txt)
            w_ex = len(cleaned_ex.split())
            wpm_ex = (w_ex / dur_m) if dur_m > 0 else 999.0
            if w_ex >= 200 and wpm_ex >= args.min_wpm:
                print('[تخطي] %s سليم مسبقًا (%d كلمة · %.1f ك/د)' % (base, w_ex, wpm_ex), flush=True)
                continue

        print('[تفريغ] %s | المدة=%.1fد | العنوان=«%s»' % (base, dur_m, title[:65]), flush=True)
        t_start = time.time()
        if dur_m > args.max_single_minutes:
            with tempfile.TemporaryDirectory(prefix='agy_chunks_') as cdir:
                chunks = split_audio_chunks(audio_path, dur_s, args.chunk_minutes, cdir)
                print('  -> قُسّم الدرس الطويل (%.1fد) إلى %d مقاطع (كل مقطع ~%.0fد · توازي=%d)' % (
                    dur_m, len(chunks), args.chunk_minutes, args.workers
                ), flush=True)

                def _run_chunk(item):
                    idx, (cpath, st_s, len_s) = item
                    req_w = max(200, int((len_s / 60.0) * 35))
                    stg = (idx - 1) * 1.5 if idx <= max(1, args.workers) else 0.0
                    ptxt, elapsed = transcribe_single_file(
                        cpath, args.model, sheikh, series, title,
                        part_idx=idx, total_parts=len(chunks), min_words=req_w, stagger_s=stg
                    )
                    return idx, len_s, ptxt, elapsed

                results = {}
                ok = True
                with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
                    futs = [pool.submit(_run_chunk, (idx, ch)) for idx, ch in enumerate(chunks, 1)]
                    for fut in concurrent.futures.as_completed(futs):
                        idx, len_s, ptxt, elapsed = fut.result()
                        if not ptxt:
                            ok = False
                            print('  [!] فشل تفريغ المقطع %d/%d لـ %s' % (idx, len(chunks), base), flush=True)
                        else:
                            cw = len(ptxt.split())
                            cwpm = cw / (len_s / 60.0) if len_s > 0 else 0.0
                            print('     ✓ المقطع %d/%d (%.1fد): %d كلمة (%.1f ك/د) في %.1fث' % (
                                idx, len(chunks), len_s / 60.0, cw, cwpm, elapsed
                            ), flush=True)
                            results[idx] = ptxt
                parts_txt = [results[i] for i in range(1, len(chunks) + 1) if i in results]
                full_txt = '\n\n'.join(parts_txt) if (ok and len(parts_txt) == len(chunks)) else ''
        else:
            req_w = max(200, int(dur_m * 35)) if dur_m > 0 else 200
            full_txt, _ = transcribe_single_file(audio_path, args.model, sheikh, series, title, min_words=req_w)

        if not full_txt:
            print('[✗ فشل] لم يكتمل تفريغ %s' % base, flush=True)
            continue

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
            'chars': len(cleaned_final),
            'words': total_words,
            'wpm': round(total_wpm, 1),
            'model': args.model,
            'ok': True,
        })
        json.dump(md, open(mp, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
        print('[✓ تم] %s | %d كلمة | %.1f ك/د | الزمن=%.1fث' % (
            os.path.basename(txt_path), total_words, total_wpm, time.time() - t_start
        ), flush=True)


if __name__ == '__main__':
    main()
