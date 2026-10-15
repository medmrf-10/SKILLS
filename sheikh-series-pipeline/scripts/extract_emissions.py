#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""extract_emissions.py — المرحلة الصوتية الوحيدة: مصفوفة انبعاثات واحدة لكل درس (بلا فيتربي).

المعمارية (توجيه المالك 2026-10-15)
  مصفوفة انبعاثات درس ٣٠ دقيقة في mms-300m ≈ (90,000 إطار × 31 صنفًا × 4 بايت) ≈ 11MB فقط.
  الفخّ القديم (5.5GB) لم يكن من المصفوفة الصوتية، بل لأن المحاذي بنى **مصفوفة فيتربي ثنائية الأبعاد
  للملف كاملًا مرة واحدة** (90,000 إطار × 40,000 حالة ≈ 4.5GB). لذلك تفصل هذه المرحلة:
    • توليد الانبعاثات بنوافذ متداخلة (٣٠ث + سياق ٢ث) و`batch 1` ⇒ ذاكرة ثابتة منخفضة.
    • حفظ المصفوفة float32 على القرص.
    • **تفريغ النموذج من الذاكرة فورًا** — فمرحلة المحاذاة لا تلمس نموذجًا إطلاقًا.

المخرجات (بادئة --out):
  <out>.em.npy      مصفوفة float32 (T,C) — خام logits قبل softmax (كما يتوقعها get_alignments)
  <out>.tokens.json الكلمات المرجعية + مفردات الرمز + blank/pad (بلا أي نموذج)
  <out>.meta.json   fps · T · C · المدة · النموذج · أزمنة · الذروة

الاستعمال:
  extract_emissions.py --audio a.wav --txt t.txt --out work/001 [--threads 4]
"""
import argparse
import gc
import json
import os
import resource
import sys
import time

import numpy as np
import soundfile as sf
import torch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ctc_forced_aligner import load_alignment_model, generate_emissions  # noqa: E402

MODEL = 'MahmoudAshraf/mms-300m-1130-forced-aligner'
SR = 16000
ONNX_DIR = os.environ.get('ONNX_ALIGN_DIR', '/root/models/onnx-mms-aligner')
ONNX_FILE = os.path.join(ONNX_DIR, 'onnx', 'model_int8.onnx')


def emissions_onnx(wave_np, model_file, window, context, workers, threads, sr=SR):
    """محرك ONNX Runtime UINT8: نافذة لكل خيط (intra_op=1) — أعلى استغلال مقيس على 4 أنوية.

    مقياس 2026-10-15 على هذا الخادم (AMD EPYC · AVX2 فقط بلا AVX-512/VNNI · 4 vCPU):
      torch fp32 (4 خيوط):      RTF 1.17–1.33 · ذروة ~2500MB
      ORT int8 intra_op=4:      RTF 2.12 ✗     · ذروة 1630MB
      ORT int8 4 نوافذ متوازية: RTF 1.10 ✓     · ذروة 2286MB
    ⇒ int8 لا يتفوّق هنا لأن نوى int8 تحتاج VNNI؛ الأفضل هو التوازي على مستوى النافذة.
    """
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
        em = np.concatenate([em, em[:, [0]]], axis=1)
    return em



def plan_silence(wave_np, sr, min_sil=0.5, keep=0.15, frame=320, rel_db=5.0, win_s=5.0):
    """يخطّط طيّ الصمت بعتبة **محلية متدرّجة**: يرجع (keep_mask لكل إطار 20ms، إحصاءات) بلا أي نموذج.

    في تسجيلات المشايخ المضغوطة/المُطبَّعة لا تنفع عتبة مطلقة: المدى الكلي قد لا يبلغ ٢٠ dB
    (001: وسيط −3.3 dBFS · أدنى كتلة ثانية −22 dB) ⇒ العتبة المطلقة ترى «صمتًا = 0.0%» كذبًا.
    لذلك نقارن كل إطار بوسيط طاقته في نافذة ±win_s (≈5ث) ونعتبره صمتًا إن هبط rel_db تحته.
    لكل فترة صمت > min_sil نحتفظ بهامش keep عند الطرفين (حماية أطراف الحروف والسياق) ونستبعد القلب.
    """
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
    sil = db < (roll - rel_db)
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
                           pct=round(removed / n * 100.0, 1), rel_db=rel_db, win_s=win_s,
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
    """إعادة نفخ المصفوفة: كل إطار محذوف يعود في موضعه الأصلي كإطار صمت صريح.

    عمود <blank> = 0.0 (أعلى احتمال) · بقية الأعمدة = blank_fill (-10.0) · عمود <star> = 0.0 كما في المصفوفة الأصلية.
    النتيجة: نفس عدد الإطارات ونفس التوقيت الفيزيائي تمامًا، ومعها فواصل صمت نظيفة 100%.
    """
    C = em_compact.shape[1]
    full = np.full((n_frames, C), float(blank_fill), dtype=np.float32)
    full[:, 0] = 0.0
    if star_col is not None and 0 <= star_col < C:
        full[:, star_col] = 0.0
    k = min(len(idx_map), len(em_compact))
    full[idx_map[:k]] = em_compact[:k]
    deficit = len(idx_map) - k
    if deficit > 0 and k:
        full[idx_map[k:]] = em_compact[k - 1]              # نقص إطار أو إطاران في الذيل
    return full, deficit



def emissions_torch_parallel(model, wave, window, context, halves, sr=SR):
    """المسار أ (٤/٤): يقسّم الزمن إلى halves مقطعًا، كل مقطع على خيط مستقل.

    لماذا: نافذة واحدة بـ4 خيوط داخلية لا تجاوز 216% من 400% (تنازع تزامن)، بينما خيطان
    × خيطان داخليان يشغلان الأنوية الأربع. kython/torch يُطلق GIL داخل النواة ⇒ التوازي حقيقي.
    ولا يُضاعف النموذج في الذاكرة: نفس الكائن ونفس العملية (بلا نسخ ولا share_memory_).
    ولا أثر لدرزات التقسيم: كل مقطع يُحسب على نطاق موسّع بالسياق ثم تُقتطع إطارات السياق،
    فيكون كل إطار مُحتفَظ به على مسافة ≥ context من حافة مقطعه.
    """
    import threading
    fps = 50.0
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
    return torch.from_numpy(em), res[0][1]



def emissions_torch_segmented(model, wav_in, window, context, seg_sec, threads=2, rt=320):
    """يولّد الانبعاثات **مقطعًا مقطعًا** (seg_sec ثانية + هامش سياق) ويهدم ما استُهلك.
    السبب المقيس 2026-10-15: ذروة الذاكرة تنمو خطيًا مع طول الملف (982MB@120ث ⇒ 1929MB@300ث)
    فتصل سقف cgroup 2000M على الدرس الكامل ⇒ ضغط ذاكرة يهدر المعالج. التقطيع يُثبّت الذروة منخفضة.
    """
    import ctypes
    if not seg_sec or seg_sec <= 0:
        with torch.inference_mode():
            return generate_emissions(model, wav_in, window_length=window,
                                      context_length=context, batch_size=1)
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
    if out.size(0) != n_expect:        # ضبط صريح: إطار واحد زائد يُقتطع من الذيل
        if out.size(0) > n_expect:
            out = out[:n_expect]
        else:
            pad = torch.full((n_expect - out.size(0), out.size(1)), -10.0)
            if out.size(1) > 31:
                pad[:, -1] = 0.0
            out = torch.cat([out, pad], dim=0)
    print('[تقطيع] %d إطارًا (متوقّع %d) · مقاطع=%d · طول المقطع=%.0fث'
          % (out.size(0), n_expect, len(pieces), seg_sec), flush=True)
    return out, stride

def emissions_torch_procs(model, wave, window, context, procs, sr=SR, threads=2):
    """المسار أ (٤/٤): عمليات مستقلة (fork) تتقاسم أوزان النموذج عبر COW.

    لماذا لا الخيوط: قياس 2026-10-15 ⇒ تقاسم الزمن على خيوط كسَب 167% من 400% (GIL يمسك
    حلقة النوافذ)، وبقيت عملية واحدة بـ4 خيوط أفضل (178%). العمليات ترفع السقف إلى procs×threads.
    الحدود مضبوطة على شبكة الإطارات (320 عينة) ⇒ مجموع الإطارات = إطارات الملف كاملًا بالضبط،
    وكل جزء يُحسب على نطاق موسّع بالسياق ثم تُقتطع إطارات السياق ⇒ بلا أثر درزات.
    """
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
    return torch.from_numpy(em), 20.0


def peak_mb():
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0


def main():
    ap = argparse.ArgumentParser(description='مصفوفة انبعاثات واحدة للدرس (بلا فيتربي، بلا Whisper)')
    ap.add_argument('--audio', required=True, help='wav أحادي 16kHz')
    ap.add_argument('--txt', required=True, help='النص المرجعي (كلمة لكل فراغ)')
    ap.add_argument('--out', required=True, help='بادئة المخرجات')
    ap.add_argument('--model', default=MODEL)
    ap.add_argument('--window', type=float, default=30.0, help='طول نافذة الانبعاثات بالثواني')
    ap.add_argument('--context', type=float, default=2.0, help='سياق التداخل بين النوافذ')
    ap.add_argument('--threads', type=int, default=4, help='خيوط torch (تُوزَّع على المقاطع في --par-halves)')
    ap.add_argument('--seg-sec', type=float, default=180.0,
                    help='تقطيع الصوت إلى مقاطع بهذا الطول (ث) لتثبيت الذروة — 0 = بلا تقطيع')
    ap.add_argument('--layers', type=int, default=0,
                    help='(٤/٤ مسار ب) اقتطاع طبقات المحرّك إلى N طبقة (0 = الكل 24) — يقلّل الزمن والذاكرة')
    ap.add_argument('--par-procs', type=int, default=1,
                    help='(٤/٤ مسار أ) عمليات مستقلة بـfork تتقاسم الأوزان (COW) × threads خيطًا')
    ap.add_argument('--par-halves', type=int, default=1,
                    help='المسار أ: عدد المقاطع المتوازية (1 = معطّل · 2 = خيطان × خيطين داخليين)')
    ap.add_argument('--engine', default='auto', choices=['auto', 'torch', 'onnx'],
                    help='auto: onnx إن وُجد النموذج المكمَّم وإلّا torch')
    ap.add_argument('--onnx-model', default=ONNX_FILE)
    ap.add_argument('--onnx-workers', type=int, default=4, help='نوافذ متوازية (خيط لكل نافذة)')
    ap.add_argument('--onnx-threads', type=int, default=1, help='خيوط ONNX داخل النافذة')
    ap.add_argument('--compact-silence', dest='silence_compact', type=int, default=0,
                    help='اسم الخطة (٣/٤) — مرادف لـ--silence-compact')
    ap.add_argument('--silence-compact', type=int, default=0,
                    help='طيّ الصمت قبل النموذج ثم إعادة النفخ في المصفوفة (نفس عدد الإطارات والتوقيت)')
    ap.add_argument('--silence-min', type=float, default=0.5, help='أدنى مدة صمت قابلة للطيّ (ث)')
    ap.add_argument('--silence-keep', type=float, default=0.15, help='هامش الأمان عند طرفي الصمت (ث)')
    ap.add_argument('--silence-rel', type=float, default=5.0,
                    help='كم dB تحت وسيط الطاقة المحلي يُعتبر الإطار صمتًا (عتبة متدرّجة ±نافذة)')
    ap.add_argument('--silence-win', type=float, default=5.0, help='نصف نافذة العتبة المحلية (ث)')
    ap.add_argument('--silence-dry-run', type=int, default=0,
                    help='قياس جاف: كم ثانية صمت قابلة للطيّ ونسبتها من الدرس (بلا نموذج)')
    a = ap.parse_args()
    torch.set_num_threads(max(1, a.threads))
    d = os.path.dirname(os.path.abspath(a.out))
    if d:
        os.makedirs(d, exist_ok=True)

    data, sr = sf.read(a.audio, dtype='float32', always_2d=False)
    if sr != SR:
        raise SystemExit('معدل العينات %d ≠ %d — حوّل الصوت أولًا (ffmpeg -ar 16000 -ac 1)' % (sr, SR))
    if data.ndim > 1:
        data = data.mean(axis=1)
    wave = torch.from_numpy(data.copy())
    dur = wave.size(0) / SR
    words = open(a.txt, encoding='utf-8').read().split() if a.txt else []
    if not words:
        raise SystemExit('نص مرجعي فارغ: %s' % a.txt)

    # ── طيّ الصمت (٣/٤): كشف الطاقة ثم استبعاد قلب الصمت الطويل قبل النموذج، وإعادة نفخ المصفوفة بعده
    sc_stats, keep_mask, idx_map = None, None, None
    if a.silence_compact or a.silence_dry_run:
        keep_mask, sc_stats = plan_silence(np.asarray(data), SR, a.silence_min, a.silence_keep,
                                           rel_db=a.silence_rel, win_s=a.silence_win)
        print('[طيّ الصمت] إطارات %s/%s · صمت قابل للطيّ %.1fث (%.1f%% من الدرس) في %d فاصلة · عتبة %.1f dB' % (
            sc_stats.get('frames_kept'), sc_stats.get('frames_total'), sc_stats.get('removed_s'),
            sc_stats.get('pct'), sc_stats.get('gaps', 0), sc_stats.get('thr_db', 0.0)), flush=True)
        if a.silence_dry_run and not a.silence_compact:
            json.dump(dict(audio=os.path.basename(a.audio), dur=round(dur, 2), **sc_stats),
                      open(a.out + '.silence.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
            print('[طيّ الصمت] قياس جاف انتهى ⇒ %s.silence.json' % a.out, flush=True)
            return
        if keep_mask is not None:
            data, idx_map = compact_wave(np.asarray(data), keep_mask)
            dur_comp = len(data) / SR
            print('[طيّ الصمت] الصوت المضغوط %.1fث من %.1fث ⇒ توفير متوقع %.1f%%' % (
                dur_comp, dur, 100.0 * (1 - dur_comp / dur)), flush=True)

    engine = a.engine
    if engine == 'auto':
        engine = 'onnx' if os.path.exists(a.onnx_model) else 'torch'
    if engine == 'onnx':
        from transformers import AutoTokenizer          # المفردات وحدها (بلا أوزان — 1.2GB أقل)
        tokenizer = AutoTokenizer.from_pretrained(a.model)
        t_load, t0 = 0.0, time.time()
        em = emissions_onnx(np.asarray(data), a.onnx_model, a.window, a.context, a.onnx_workers, a.onnx_threads)
        t_em = time.time() - t0
        stride = 1000.0 / 50.0
    else:
        t0 = time.time()
        model, tokenizer = load_alignment_model('cpu', model_path=a.model, dtype=torch.float32)
        if a.layers and a.layers > 0:                     # اقتطاع الطبقات: الرأس يقرأ مخرج الطبقة الأخيرة المتبقية
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
        t0 = time.time()
        wav_in = wave if idx_map is None else torch.from_numpy(np.asarray(data).copy())
        if getattr(a, 'seg_sec', 0) and a.seg_sec > 0:
            em, stride = emissions_torch_segmented(model, wav_in, a.window, a.context,
                                                   a.seg_sec, threads=int(a.threads))
        elif a.par_procs and a.par_procs > 1:
            em, stride = emissions_torch_procs(model, wav_in, a.window, a.context, a.par_procs,
                                               threads=int(a.threads))
        elif a.par_halves and a.par_halves > 1:
            em, stride = emissions_torch_parallel(model, wav_in, a.window, a.context, a.par_halves)
        else:
            with torch.inference_mode():
                em, stride = generate_emissions(model, wav_in, window_length=a.window,
                                               context_length=a.context, batch_size=1)
        t_em = time.time() - t0
        em = np.ascontiguousarray(em.float().numpy())
        del model
        gc.collect()
    deficit = 0
    if idx_map is not None:                       # إعادة النفخ: نفس عدد الإطارات والتوقيت الفيزيائي تمامًا
        n_frames = int(sc_stats['frames_total'])
        em, deficit = unpad_emissions(em, idx_map, n_frames,
                                      star_col=(em.shape[1] - 1 if em.shape[1] > 31 else None))
        fps = float(n_frames) / dur if dur > 0 else 50.0
        stride = 1000.0 / fps
        print('[طيّ الصمت] أُعيد نفخ المصفوفة إلى %d إطارًا · محذوف=%d · نقص ذيلي=%d' % (
            n_frames, n_frames - len(idx_map), deficit), flush=True)
    fps = float(em.shape[0]) / dur if dur > 0 else 1000.0 / float(stride)   # إطارات/ثانية (stride بالملي ثانية)

    np.save(a.out + '.em.npy', em)
    vocab = {k.lower(): v for k, v in tokenizer.get_vocab().items()}
    blank = vocab.get('<blank>', tokenizer.pad_token_id)
    json.dump({'vocab': vocab, 'vocab_size': len(vocab), 'pad': tokenizer.pad_token_id,
               'blank': blank, 'words': words, 'n_words': len(words)},
              open(a.out + '.tokens.json', 'w', encoding='utf-8'), ensure_ascii=False)
    meta = dict(model=a.model, engine=engine, onnx_model=(a.onnx_model if engine == 'onnx' else ''),
                onnx_workers=(a.onnx_workers if engine == 'onnx' else 0), fps=round(fps, 4), stride_ms=float(stride), frames=int(em.shape[0]),
                classes=int(em.shape[1]), dur=round(dur, 2), n_words=len(words),
                audio=os.path.basename(a.audio), load_s=round(t_load, 1), em_s=round(t_em, 1),
                rtf=round(t_em / dur, 4), peak_rss_mb=round(peak_mb(), 1),
                window=a.window, context=a.context, batch=1,
                silence_compact=bool(idx_map is not None),
                silence_stats=(sc_stats if idx_map is not None else None),
                unpad_deficit=int(deficit), par_halves=int(a.par_halves), par_procs=int(a.par_procs),
                layers=int(a.layers), threads=int(a.threads))
    json.dump(meta, open(a.out + '.meta.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)

    print('[انبعاثات] %s | إطارات=%d × صنوف=%d | fps=%.2f | مدة=%.0fث | تحميل=%.1fث · توليد=%.1fث · RTF=%.2f | ذروة=%.0fMB | مصفوفة=%.1fMB' % (
        os.path.basename(a.out), meta['frames'], meta['classes'], fps, dur, t_load, t_em,
        meta['rtf'], meta['peak_rss_mb'], os.path.getsize(a.out + '.em.npy') / 1048576.0))


if __name__ == '__main__':
    main()
