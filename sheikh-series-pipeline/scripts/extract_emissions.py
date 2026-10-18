#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""extract_emissions.py — المرحلة الصوتية الوحيدة: مصفوفة انبعاثات واحدة لكل درس (بلا فيتربي).

المعمارية:
  مصفوفة انبعاثات درس ٣٠ دقيقة في mms-300m ≈ (90,000 إطار × 32 صنفًا × 4 بايت) ≈ 11MB فقط.
  الفخّ القديم (5.5GB) لم يكن من المصفوفة الصوتية، بل لأن المحاذي بنى **مصفوفة فيتربي ثنائية الأبعاد
  للملف كاملًا مرة واحدة** (90,000 إطار × 40,000 حالة ≈ 4.5GB). لذلك تفصل هذه المرحلة:
    • توليد الانبعاثات بنوافذ متداخلة (٢٠–٣٠ث + سياق ٢ث) ⇒ ذاكرة ثابتة منخفضة.
    • دعم تسريع GPU على الماك (Apple Silicon MPS: RTF ≈ 0.029 بـfp32 و0.021 بـfp16 — أسرع بـ39–53× من CPU)
      ودعم CUDA وCPU (torch fp32 أو ONNX، مع دعم طيّ الصمت واقتطاع الطبقات والتوازي بـfork/COW).
    • حفظ المصفوفة float32 على القرص.
    • **تفريغ النموذج من الذاكرة فورًا** — فمرحلة المحاذاة لا تلمس نموذجًا إطلاقًا.

المخرجات (بادئة --out):
  <out>.em.npy      مصفوفة float32 (T,C) — log-softmax + عمود <star> (كما يتوقعها get_alignments)
  <out>.tokens.json الكلمات المرجعية + مفردات الرمز + blank/pad (بلا أي نموذج)
  <out>.meta.json   fps · T · C · المدة · النموذج · الجهاز · أزمنة · الذروة

الاستعمال:
  extract_emissions.py --audio a.wav --txt t.txt --out work/001 [--device auto|mps|cuda|cpu] [--dtype fp32|fp16]
"""
import argparse
import gc
import json
import math
import os
import resource
import sys
import time

import numpy as np
import soundfile as sf
import torch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ctc_forced_aligner import load_alignment_model, generate_emissions  # noqa: E402


def time_to_frame(t, stride=20.0):
    return int(t * 1000.0 / stride)


MODEL = 'MahmoudAshraf/mms-300m-1130-forced-aligner'
SR = 16000
ONNX_DIR = os.environ.get('ONNX_ALIGN_DIR', '/root/models/onnx-mms-aligner')
ONNX_FILE = os.path.join(ONNX_DIR, 'onnx', 'model_int8.onnx')


def select_device(requested):
    """اختيار الجهاز تلقائيًا: MPS (ماك Apple Silicon) ← CUDA ← CPU."""
    if requested and requested != 'auto':
        return requested
    if hasattr(torch.backends, 'mps') and torch.backends.mps.is_available():
        return 'mps'
    if torch.cuda.is_available():
        return 'cuda'
    return 'cpu'


def emissions_torch(model, wave, device, dtype, window, context, batch_size, sr=SR):
    """توليد مصفوفة الانبعاثات عبر PyTorch مع دعم MPS/CUDA/CPU وتفريغ فوري لكل دفعة إلى CPU."""
    stride = 20.0
    context_samples = int(context * sr)
    window_samples = int(window * sr)
    if wave.size(0) < window_samples:
        window_samples = wave.size(0)
    ext = int(math.ceil(wave.size(0) / window_samples) * window_samples - wave.size(0))
    padded = torch.nn.functional.pad(wave, (context_samples, context_samples + ext))
    input_windows = padded.unfold(0, window_samples + 2 * context_samples, window_samples)

    bs = max(1, int(batch_size))
    batched_outs = []
    with torch.inference_mode():
        for step_idx, i in enumerate(range(0, input_windows.size(0), bs)):
            batch = input_windows[i:i + bs].to(device=device, dtype=dtype)
            out = model(batch).logits
            batched_outs.append(out.detach().to(device='cpu', dtype=torch.float32))
            del batch, out
            if device == 'mps' and (step_idx + 1) % 8 == 0 and hasattr(torch, 'mps'):
                torch.mps.empty_cache()
        if device == 'mps' and hasattr(torch, 'mps'):
            torch.mps.empty_cache()

    emissions = torch.cat(batched_outs, dim=0)
    ctx_frames = time_to_frame(context)
    if ctx_frames > 0:
        emissions = emissions[:, ctx_frames:-ctx_frames]
    emissions = emissions.flatten(0, 1)
    ext_frames = time_to_frame(ext / sr)
    if ext_frames > 0:
        emissions = emissions[:-ext_frames]
    emissions = torch.log_softmax(emissions, dim=-1)
    emissions = torch.cat([emissions, torch.zeros(emissions.size(0), 1)], dim=1)
    return np.ascontiguousarray(emissions.float().numpy()), float(stride)


def emissions_onnx(wave_np, model_file, window, context, workers, threads, sr=SR):
    """محرك ONNX Runtime UINT8: نافذة لكل خيط (intra_op=1)."""
    import onnxruntime as ort
    from concurrent.futures import ThreadPoolExecutor
    so = ort.SessionOptions()
    so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    so.intra_op_num_threads = max(1, threads)
    so.inter_op_num_threads = 1
    sess = ort.InferenceSession(model_file, so, providers=['CPUExecutionProvider'])
    ins = [i.name for i in sess.get_inputs()]
    starts = list(range(0, len(wave_np), int(window * sr)))

    def run_one(st):
        cs, ce = max(int(st - context * sr), 0), min(int(st + (window + context) * sr), len(wave_np))
        seg = np.ascontiguousarray(wave_np[cs:ce], dtype=np.float32)[None, :]
        feeds = {n: (np.ones_like(seg, dtype=np.int64) if 'mask' in n else seg) for n in ins}
        out = sess.run(None, feeds)[0]
        lead = int((st - cs) / sr * 50.0)
        return st, out[0, lead:lead + int(round(window * 50))]

    parts = {}
    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        for st, arr in ex.map(run_one, starts):
            parts[st] = arr
    raw = np.concatenate([parts[st] for st in starts], axis=0).astype(np.float32)
    m = raw.max(axis=1, keepdims=True)
    em = (raw - m) - np.log(np.exp(raw - m).sum(axis=1, keepdims=True))     # log-softmax
    if em.shape[1] == 31:                                                   # المحاذي يتوقع <star> كعمود 32
        em = np.concatenate([em, np.zeros((em.shape[0], 1), dtype=np.float32)], axis=1)
    return em


def plan_silence(wave_np, sr, min_sil=0.5, keep=0.15, frame=320, rel_db=5.0, win_s=5.0, abs_db=-55.0):
    """يخطّط طيّ الصمت بعتبة **محلية متدرّجة** مع أرضية صمت مطلقة (`abs_db`): يرجع (keep_mask لكل إطار 20ms، إحصاءات) بلا أي نموذج."""
    n = len(wave_np) // frame
    if n < 8:
        return None, dict(removed_s=0.0, pct=0.0, gaps=0, reason='صوت قصير')
    x = wave_np[:n * frame].reshape(n, frame).astype(np.float64)
    rms = np.sqrt((x ** 2).mean(axis=1) + 1e-12)
    db = 20.0 * np.log10(rms + 1e-9)
    W = max(2, int(round(win_s * sr / frame)))
    pad = np.pad(db, (W, W), mode='edge')
    step = 25                                   # وسيط كل 0.5ث ثم استيفاء (كلفة ~1% ومتانة الوسيط)
    pos = np.arange(0, n, step)
    med = np.array([np.median(pad[p:p + 2 * W + 1]) for p in pos], dtype=np.float64)
    roll = np.interp(np.arange(n), pos, med, left=med[0], right=med[-1])
    sil = (db < (roll - rel_db)) | (db < abs_db)
    d = np.diff(np.concatenate([[0], sil.astype(np.int8), [0]]))
    st, en = np.flatnonzero(d == 1), np.flatnonzero(d == -1)
    kf, kmin = int(round(keep * sr / frame)), int(round(min_sil * sr / frame))
    keep_mask = np.ones(n, dtype=bool)
    removed = gaps = 0
    for s0, e0 in zip(st, en):
        if (e0 - s0) < kmin:
            continue
        a, b = s0 + kf, e0 - kf
        if (b - a) < 1:
            continue
        keep_mask[a:b] = False
        removed += (b - a)
        gaps += 1
    return keep_mask, dict(removed_s=round(removed * 0.02, 1), gaps=gaps, total_s=round(n * 0.02, 1),
                           pct=round(removed / n * 100.0, 1), rel_db=rel_db, win_s=win_s, abs_db=abs_db,
                           thr_db=round(float(np.median(roll) - rel_db), 1),
                           frames_kept=int(keep_mask.sum()), frames_total=n)


def compact_wave(wave_np, keep_mask, frame=320):
    """يبني الصوت المضغوط (مقاطع متصلة بحدود 320 عينة) + خريطة الفهارس الأصلية."""
    d = np.diff(np.concatenate([[0], keep_mask.astype(np.int8), [0]]))
    s, e = np.flatnonzero(d == 1), np.flatnonzero(d == -1)
    parts = [wave_np[i * frame:j * frame] for i, j in zip(s, e)]
    comp = np.concatenate(parts) if parts else wave_np
    return np.ascontiguousarray(comp), np.flatnonzero(keep_mask)


def unpad_emissions(em_compact, idx_map, n_frames, blank_fill=-10.0, star_col=None):
    """إعادة نفخ المصفوفة: كل إطار محذوف يعود في موضعه الأصلي كإطار صمت صريح."""
    C = em_compact.shape[1]
    full = np.full((n_frames, C), float(blank_fill), dtype=np.float32)
    full[:, 0] = 0.0
    if star_col is not None and 0 <= star_col < C:
        full[:, star_col] = 0.0
    k = min(len(idx_map), len(em_compact))
    full[idx_map[:k]] = em_compact[:k]
    deficit = len(idx_map) - k
    if deficit > 0 and k:
        full[idx_map[k:]] = em_compact[k - 1]
    return full, deficit


def emissions_torch_parallel(model, wave, window, context, halves, sr=SR):
    """المسار أ (٤/٤): يقسّم الزمن إلى halves مقطعًا، كل مقطع على خيط مستقل."""
    import threading
    total_s = wave.size(0) / sr
    res = [None] * halves
    err = [None] * halves

    def work(i, s0, s1):
        try:
            a = max(0, int(round((s0 - context) * sr)))
            b = min(wave.size(0), int(round((s1 + context) * sr)))
            with torch.inference_mode():
                e, stride = generate_emissions(model, wave[a:b], window_length=window,
                                               context_length=context, batch_size=1)
            e = np.ascontiguousarray(e.float().numpy())
            f = 1000.0 / float(stride)
            lead = int(round((s0 * sr - a) / sr * f))
            want = int(round((s1 - s0) * f))
            res[i] = (e[lead:lead + want], float(stride))
        except Exception as ex:                       # noqa: BLE001
            err[i] = '%s: %s' % (type(ex).__name__, str(ex)[:120])

    ths = [threading.Thread(target=work, args=(i, i * total_s / halves, (i + 1) * total_s / halves))
           for i in range(halves)]
    for t in ths:
        t.start()
    for t in ths:
        t.join()
    bad = [e for e in err if e]
    if bad or any(r is None for r in res):
        raise RuntimeError('فشل التوازي: %s' % (bad[:2] or 'مقطع بلا مخرجات'))
    em = np.concatenate([r[0] for r in res], axis=0)
    return em, res[0][1]


def emissions_torch_segmented(model, wav_in, window, context, seg_sec, threads=2, rt=320):
    """يولّد الانبعاثات مقطعًا مقطعًا (seg_sec ثانية + هامش سياق) ويهدم ما استُهلك مع malloc_trim على CPU."""
    import ctypes
    if not seg_sec or seg_sec <= 0:
        with torch.inference_mode():
            em, stride = generate_emissions(model, wav_in, window_length=window,
                                            context_length=context, batch_size=1)
        return np.ascontiguousarray(em.float().numpy()), float(stride)
    try:
        torch.set_num_threads(int(threads))
    except Exception:
        pass
    total = int(wav_in.numel())
    seg = int(seg_sec * SR)
    ctx = int(context * SR)
    pieces, pos = [], 0
    libc = None
    try:
        libc = ctypes.CDLL('libc.so.6')
    except Exception:
        libc = None
    stride = 20.0
    while pos < total:
        end = min(pos + seg, total)
        s = max(0, pos - ctx)
        e = min(total, end + ctx)
        chunk = wav_in[s:e].contiguous()
        with torch.inference_mode():
            em, stride = generate_emissions(model, chunk, window_length=window,
                                            context_length=context, batch_size=1)
        f0 = int(round((pos - s) / rt))
        f1 = f0 + int(round((end - pos) / rt))
        pieces.append(em[f0:f1].clone())
        del em
        pos = end
        gc.collect()
        if libc is not None:
            try:
                libc.malloc_trim(0)
            except Exception:
                pass
    out = torch.cat(pieces, dim=0)
    n_expect = int(round(total / rt))
    if out.size(0) != n_expect:
        if out.size(0) > n_expect:
            out = out[:n_expect]
        else:
            pad = torch.full((n_expect - out.size(0), out.size(1)), -10.0)
            if out.size(1) > 31:
                pad[:, -1] = 0.0
            out = torch.cat([out, pad], dim=0)
    print('[تقطيع] %d إطارًا (متوقّع %d) · مقاطع=%d · طول المقطع=%.0fث'
          % (out.size(0), n_expect, len(pieces), seg_sec), flush=True)
    return np.ascontiguousarray(out.float().numpy()), float(stride)


def emissions_torch_procs(model, wave, window, context, procs, sr=SR, threads=2):
    """المسار أ (٤/٤): عمليات مستقلة (fork) تتقاسم أوزان النموذج عبر COW."""
    import multiprocessing as mp
    frame = int(round(sr / 50.0))
    n = wave.size(0)
    total_frames = n // frame
    step = total_frames // procs
    ctx_f = int(round(context * 50.0))
    jobs = []
    for i in range(procs):
        f0 = i * step
        f1 = total_frames if i == procs - 1 else (i + 1) * step
        jobs.append((i, f0, f1, max(0, (f0 - ctx_f) * frame), min(n, (f1 + ctx_f) * frame)))
    ctxm = mp.get_context('fork')
    q = ctxm.SimpleQueue()

    def work(i, f0, f1, a0, a1, q):
        try:
            torch.set_num_threads(threads)
            with torch.inference_mode():
                e, stride = generate_emissions(model, wave[a0:a1], window_length=window,
                                               context_length=context, batch_size=1)
            arr = np.ascontiguousarray(e.float().numpy())
            lead = f0 - a0 // frame
            q.put((i, arr[lead:lead + (f1 - f0)]))
        except Exception as ex:                      # noqa: BLE001
            q.put((i, ('ERR', '%s: %s' % (type(ex).__name__, str(ex)[:140]))))

    ps = [ctxm.Process(target=work, args=j + (q,)) for j in jobs]
    for p in ps:
        p.start()
    got = {}
    for _ in jobs:
        i, arr = q.get()
        got[i] = arr
    for p in ps:
        p.join()
    for i in sorted(got):
        if isinstance(got[i], tuple):
            raise RuntimeError('فشل الجزء %d: %s' % (i, got[i][1]))
    em = np.concatenate([got[i] for i in sorted(got)], axis=0)
    print('[توزيع] %d عمليات × %d خيوط ⇒ إطارات %d' % (procs, threads, em.shape[0]), flush=True)
    return em, 20.0


def peak_mb():
    """ذروة الذاكرة بالميغابايت (macOS يعيد ru_maxrss بالبايت، ولينكس بالكيلوبايت)."""
    r = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return r / (1024.0 * 1024.0) if sys.platform == 'darwin' else r / 1024.0


def find_ffmpeg():
    """إيجاد ثنائي ffmpeg على الماك أو اللينكس."""
    import glob
    import shutil
    ff = os.environ.get('FFMPEG', '')
    if ff and os.path.exists(ff):
        return ff
    w = shutil.which('ffmpeg')
    if w:
        return w
    for pat in ('/opt/homebrew/bin/ffmpeg', '/usr/local/bin/ffmpeg', '/root/.hermes/tools/ffmpeg-*/bin/ffmpeg'):
        m = sorted(glob.glob(pat))
        if m:
            return m[-1]
    return 'ffmpeg'


def read_audio_16k(audio_path, sr=SR):
    """قراءة الصوت بمعدل 16kHz أحادي مباشرة في الذاكرة (sf.read للـwav الجاهز، أو أنبوب ffmpeg f32le لأي صيغة)."""
    import subprocess
    if audio_path.lower().endswith('.wav'):
        try:
            info = sf.info(audio_path)
            if info.samplerate == sr and info.channels == 1:
                data, _ = sf.read(audio_path, dtype='float32', always_2d=False)
                return np.ascontiguousarray(data, dtype=np.float32)
        except Exception:
            pass
    ff = find_ffmpeg()
    cmd = [
        ff, '-nostdin', '-v', 'error', '-i', audio_path,
        '-f', 'f32le', '-acodec', 'pcm_f32le', '-ac', '1', '-ar', str(sr), '-'
    ]
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if res.returncode != 0:
        err = res.stderr.decode('utf-8', errors='replace')[-300:]
        raise SystemExit('فشل فكّ الصوت عبر ffmpeg (%s): %s' % (audio_path, err))
    return np.frombuffer(res.stdout, dtype=np.float32).copy()


def discover_series_lessons(series_dir, only_filter=None):
    """اكتشاف أزواج (صوت، نص) لكل درس في مجلد السلسلة."""
    import re
    only_set = set(x.strip() for x in only_filter.split(',') if x.strip()) if only_filter else None
    lessons = []
    for fn in sorted(os.listdir(series_dir)):
        if not re.match(r'^\d{3}_.+\.txt$', fn):
            continue
        stem = fn[:-4]
        if only_set and stem not in only_set and not any(stem.startswith(o) for o in only_set):
            continue
        txt_path = os.path.join(series_dir, fn)
        audio_path = None
        for ext in ('.mp3', '.m4a', '.wav', '.opus', '.webm', '.ogg', '.flac'):
            cand = os.path.join(series_dir, stem + ext)
            if os.path.exists(cand) and os.path.getsize(cand) > 0:
                audio_path = cand
                break
        if audio_path:
            lessons.append((stem, audio_path, txt_path))
    return lessons


def main():
    ap = argparse.ArgumentParser(description='مصفوفة انبعاثات واحدة للدرس أو للسلسلة كاملة (بلا فيتربي، بلا Whisper)')
    ap.add_argument('--audio', help='ملف الصوت (wav/mp3/m4a/...) — لوضع الدرس المفرد')
    ap.add_argument('--txt', help='النص المرجعي (كلمة لكل فراغ) — لوضع الدرس المفرد')
    ap.add_argument('--out', help='بادئة المخرجات — لوضع الدرس المفرد')
    ap.add_argument('--series-dir', help='مجلد السلسلة (لمعالجة جميع الدروس بتحميل النموذج مرة واحدة)')
    ap.add_argument('--out-dir', help='مجلد المخرجات عند استخدام --series-dir')
    ap.add_argument('--only', help='تصفية الدروس عند استخدام --series-dir (مفصولة بفواصل، مثل 001,006)')
    ap.add_argument('--skip-existing', action='store_true',
                    help='تخطّي استخراج الانبعاثات إذا وُجد ملف .em.npy وتحديث .tokens.json فقط عند تغيّر النص')
    ap.add_argument('--model', default=MODEL)
    ap.add_argument('--window', type=float, default=30.0, help='طول نافذة الانبعاثات بالثواني')
    ap.add_argument('--context', type=float, default=2.0, help='سياق التداخل بين النوافذ')
    ap.add_argument('--threads', type=int, default=4, help='خيوط torch')
    ap.add_argument('--seg-sec', type=float, default=0.0,
                    help='تقطيع الصوت على CPU إلى مقاطع بهذا الطول (ث) مع malloc_trim لتثبيت المخصّص (0 = بلا تقطيع)')
    ap.add_argument('--layers', type=int, default=0,
                    help='(٤/٤ مسار ب) اقتطاع طبقات المحرّك إلى N طبقة (0 = الكل 24)')
    ap.add_argument('--par-procs', type=int, default=1,
                    help='(٤/٤ مسار أ) عمليات مستقلة بـfork تتقاسم الأوزان (COW) × threads خيطًا')
    ap.add_argument('--par-halves', type=int, default=1,
                    help='المسار أ: عدد المقاطع المتوازية على خيوط مستقلة')
    ap.add_argument('--device', default='auto', choices=['auto', 'mps', 'cuda', 'cpu'],
                    help='الجهاز: auto يختار mps على الماك أو cuda أو cpu')
    ap.add_argument('--dtype', default='fp32', choices=['fp32', 'fp16'],
                    help='الدقة العددية: fp32 (الافتراضي المتطابق) أو fp16 على MPS/CUDA')
    ap.add_argument('--batch', type=int, default=0,
                    help='حجم الدفعة (0 = تلقائي: 4 على MPS/CUDA، و1 على CPU)')
    ap.add_argument('--engine', default='torch', choices=['auto', 'torch', 'onnx'],
                    help='المحرك: torch (الافتراضي، يدعم MPS/CUDA/CPU) أو onnx')
    ap.add_argument('--onnx-model', default=ONNX_FILE)
    ap.add_argument('--onnx-workers', type=int, default=2, help='نوافذ متوازية (خيط لكل نافذة)')
    ap.add_argument('--onnx-threads', type=int, default=2, help='خيوط ONNX داخل النافذة')
    ap.add_argument('--compact-silence', dest='silence_compact', type=int, default=0,
                    help='اسم الخطة (٣/٤) — مرادف لـ--silence-compact')
    ap.add_argument('--silence-compact', type=int, default=0,
                    help='طيّ الصمت قبل النموذج ثم إعادة النفخ في المصفوفة')
    ap.add_argument('--silence-min', type=float, default=0.5, help='أدنى مدة صمت قابلة للطيّ (ث)')
    ap.add_argument('--silence-keep', type=float, default=0.15, help='هامش الأمان عند طرفي الصمت (ث)')
    ap.add_argument('--silence-rel', type=float, default=5.0,
                    help='كم dB تحت وسيط الطاقة المحلي يُعتبر الإطار صمتًا (عتبة متدرّجة ±نافذة)')
    ap.add_argument('--silence-win', type=float, default=5.0, help='نصف نافذة العتبة المحلية (ث)')
    ap.add_argument('--silence-dry-run', type=int, default=0,
                    help='قياس جاف: كم ثانية صمت قابلة للطيّ ونسبتها من الدرس (بلا نموذج)')
    a = ap.parse_args()
    torch.set_num_threads(max(1, a.threads))

    if a.series_dir:
        out_dir = a.out_dir or os.path.join(a.series_dir, '_pure_out')
        os.makedirs(out_dir, exist_ok=True)
        lessons = discover_series_lessons(a.series_dir, a.only)
        if not lessons:
            raise SystemExit('لم يُعثر على دروس مكتملة (صوت + نص) في: %s' % a.series_dir)
        tasks = [(stem, aud, txt, os.path.join(out_dir, stem)) for stem, aud, txt in lessons]
    else:
        if not (a.audio and a.txt and a.out):
            raise SystemExit('مرّر إما (--audio و --txt و --out) لدرس مفرد أو (--series-dir و --out-dir) لسلسلة.')
        d = os.path.dirname(os.path.abspath(a.out))
        if d:
            os.makedirs(d, exist_ok=True)
        tasks = [(os.path.basename(a.out), a.audio, a.txt, a.out)]

    device = select_device(a.device)
    engine = a.engine
    if engine == 'auto':
        engine = 'onnx' if (device == 'cpu' and os.path.exists(a.onnx_model)) else 'torch'
    batch_size = a.batch if a.batch > 0 else (4 if device in ('mps', 'cuda') else 1)
    dtype = torch.float16 if (a.dtype == 'fp16' and device in ('mps', 'cuda')) else torch.float32

    model = None
    tokenizer = None
    t_load = 0.0

    def ensure_tokenizer():
        nonlocal tokenizer
        if tokenizer is None:
            from transformers import AutoTokenizer
            tokenizer = AutoTokenizer.from_pretrained(a.model)
        return tokenizer

    def ensure_model():
        nonlocal model, tokenizer, t_load
        if model is not None:
            return model, tokenizer, 0.0
        t0 = time.time()
        model, tokenizer = load_alignment_model(device, model_path=a.model, dtype=dtype)
        if a.layers and a.layers > 0:
            try:
                enc = model.wav2vec2.encoder
                tot = len(enc.layers)
                if a.layers < tot:
                    enc.layers = torch.nn.ModuleList(list(enc.layers)[:a.layers])
                    model.config.num_hidden_layers = a.layers
                    if hasattr(model.wav2vec2.config, 'num_hidden_layers'):
                        model.wav2vec2.config.num_hidden_layers = a.layers
                    print('[طبقات] اقتُطع المحرّك %d ⇒ %d طبقة' % (tot, a.layers), flush=True)
            except Exception as ex:                       # noqa: BLE001
                print('[طبقات] تعذّر القطع: %s' % ex, flush=True)
        t_load = time.time() - t0
        return model, tokenizer, t_load

    for stem, audio_path, txt_path, out_prefix in tasks:
        words = open(txt_path, encoding='utf-8').read().split() if txt_path else []
        if not words:
            print('[تخطٍ] نص مرجعي فارغ: %s' % txt_path, flush=True)
            continue

        em_path = out_prefix + '.em.npy'
        tok_path = out_prefix + '.tokens.json'
        meta_path = out_prefix + '.meta.json'

        if a.skip_existing and os.path.exists(em_path) and os.path.getsize(em_path) > 0:
            need_tok = True
            if os.path.exists(tok_path):
                try:
                    old_tok = json.load(open(tok_path, encoding='utf-8'))
                    if old_tok.get('words') == words:
                        need_tok = False
                except Exception:
                    pass
            if not need_tok:
                print('[انبعاثات] %s | موجود مسبقًا ومطابق للنص (%d كلمة) — تخطٍ' % (stem, len(words)), flush=True)
                continue
            tok = ensure_tokenizer()
            vocab = {k.lower(): v for k, v in tok.get_vocab().items()}
            blank = vocab.get('<blank>', tok.pad_token_id)
            json.dump({'vocab': vocab, 'vocab_size': len(vocab), 'pad': tok.pad_token_id,
                       'blank': blank, 'words': words, 'n_words': len(words)},
                      open(tok_path, 'w', encoding='utf-8'), ensure_ascii=False)
            if os.path.exists(meta_path):
                try:
                    m = json.load(open(meta_path, encoding='utf-8'))
                    m['n_words'] = len(words)
                    json.dump(m, open(meta_path, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
                except Exception:
                    pass
            print('[انبعاثات] %s | أُعيد استخدام .em.npy وتُحدّث .tokens.json (%d كلمة) في 0.0ث' % (
                stem, len(words)), flush=True)
            continue

        t_dec0 = time.time()
        data = read_audio_16k(audio_path, sr=SR)
        t_dec = time.time() - t_dec0
        wave = torch.from_numpy(data)
        dur = wave.size(0) / SR

        sc_stats, keep_mask, idx_map = None, None, None
        if a.silence_compact or a.silence_dry_run:
            keep_mask, sc_stats = plan_silence(np.asarray(data), SR, a.silence_min, a.silence_keep,
                                               rel_db=a.silence_rel, win_s=a.silence_win)
            print('[طيّ الصمت] %s | إطارات %s/%s · صمت قابل للطيّ %.1fث (%.1f%% من الدرس) في %d فاصلة · عتبة %.1f dB' % (
                stem, sc_stats.get('frames_kept'), sc_stats.get('frames_total'), sc_stats.get('removed_s'),
                sc_stats.get('pct'), sc_stats.get('gaps', 0), sc_stats.get('thr_db', 0.0)), flush=True)
            if a.silence_dry_run and not a.silence_compact:
                json.dump(dict(audio=os.path.basename(audio_path), dur=round(dur, 2), **sc_stats),
                          open(out_prefix + '.silence.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
                print('[طيّ الصمت] قياس جاف انتهى ⇒ %s.silence.json' % out_prefix, flush=True)
                continue
            if keep_mask is not None:
                data, idx_map = compact_wave(np.asarray(data), keep_mask)
                dur_comp = len(data) / SR
                print('[طيّ الصمت] الصوت المضغوط %.1fث من %.1fث ⇒ توفير متوقع %.1f%%' % (
                    dur_comp, dur, 100.0 * (1 - dur_comp / dur)), flush=True)

        if engine == 'onnx':
            tok = ensure_tokenizer()
            cur_load, t0 = 0.0, time.time()
            em = emissions_onnx(np.asarray(data), a.onnx_model, a.window, a.context, a.onnx_workers, a.onnx_threads)
            t_em = time.time() - t0
            stride = 1000.0 / 50.0
            cur_device = 'cpu'
        else:
            mdl, tok, cur_load = ensure_model()
            t0 = time.time()
            wav_in = wave if idx_map is None else torch.from_numpy(np.asarray(data).copy())
            if device == 'cpu' and a.seg_sec and a.seg_sec > 0:
                em, stride = emissions_torch_segmented(mdl, wav_in, a.window, a.context,
                                                       a.seg_sec, threads=int(a.threads))
            elif device == 'cpu' and a.par_procs and a.par_procs > 1:
                em, stride = emissions_torch_procs(mdl, wav_in, a.window, a.context, a.par_procs,
                                                   threads=int(a.threads))
            elif device == 'cpu' and a.par_halves and a.par_halves > 1:
                em, stride = emissions_torch_parallel(mdl, wav_in, a.window, a.context, a.par_halves)
            else:
                em, stride = emissions_torch(mdl, wav_in, device=device, dtype=dtype,
                                             window=a.window, context=a.context, batch_size=batch_size)
            t_em = time.time() - t0
            cur_device = device

        deficit = 0
        if idx_map is not None:
            n_frames = int(sc_stats['frames_total'])
            em, deficit = unpad_emissions(em, idx_map, n_frames,
                                          star_col=(em.shape[1] - 1 if em.shape[1] > 31 else None))
            fps = float(n_frames) / dur if dur > 0 else 50.0
            stride = 1000.0 / fps
            print('[طيّ الصمت] أُعيد نفخ المصفوفة إلى %d إطارًا · محذوف=%d · نقص ذيلي=%d' % (
                n_frames, n_frames - len(idx_map), deficit), flush=True)

        fps = float(em.shape[0]) / dur if dur > 0 else 1000.0 / float(stride)

        np.save(em_path, em)
        vocab = {k.lower(): v for k, v in tok.get_vocab().items()}
        blank = vocab.get('<blank>', tok.pad_token_id)
        json.dump({'vocab': vocab, 'vocab_size': len(vocab), 'pad': tok.pad_token_id,
                   'blank': blank, 'words': words, 'n_words': len(words)},
                  open(tok_path, 'w', encoding='utf-8'), ensure_ascii=False)
        meta = dict(model=a.model, engine=engine, device=cur_device, dtype=a.dtype,
                    onnx_model=(a.onnx_model if engine == 'onnx' else ''),
                    onnx_workers=(a.onnx_workers if engine == 'onnx' else 0),
                    fps=round(fps, 4), stride_ms=float(stride), frames=int(em.shape[0]),
                    classes=int(em.shape[1]), dur=round(dur, 2), n_words=len(words),
                    audio=os.path.basename(audio_path), decode_s=round(t_dec, 2),
                    load_s=round(cur_load, 1), em_s=round(t_em, 1),
                    rtf=round(t_em / dur, 4), peak_rss_mb=round(peak_mb(), 1),
                    window=a.window, context=a.context, batch=batch_size,
                    silence_compact=bool(idx_map is not None),
                    silence_stats=(sc_stats if idx_map is not None else None),
                    unpad_deficit=int(deficit), par_halves=int(a.par_halves), par_procs=int(a.par_procs),
                    layers=int(a.layers), threads=int(a.threads))
        json.dump(meta, open(meta_path, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)

        print('[انبعاثات] %s | جهاز=%s (%s, batch=%d) | إطارات=%d × صنوف=%d | fps=%.2f | مدة=%.0fث | فك=%.1fث · تحميل=%.1fث · توليد=%.1fث · RTF=%.4f | ذروة=%.0fMB | مصفوفة=%.1fMB' % (
            stem, cur_device, a.dtype, batch_size, meta['frames'], meta['classes'],
            fps, dur, t_dec, cur_load, t_em, meta['rtf'], meta['peak_rss_mb'],
            os.path.getsize(em_path) / 1048576.0), flush=True)

    if model is not None:
        del model
        gc.collect()
        if device == 'mps' and hasattr(torch, 'mps'):
            torch.mps.empty_cache()
        elif device == 'cuda' and torch.cuda.is_available():
            torch.cuda.empty_cache()


if __name__ == '__main__':
    main()

