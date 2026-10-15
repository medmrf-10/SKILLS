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
    ap.add_argument('--threads', type=int, default=4)
    ap.add_argument('--engine', default='auto', choices=['auto', 'torch', 'onnx'],
                    help='auto: onnx إن وُجد النموذج المكمَّم وإلّا torch')
    ap.add_argument('--onnx-model', default=ONNX_FILE)
    ap.add_argument('--onnx-workers', type=int, default=4, help='نوافذ متوازية (خيط لكل نافذة)')
    ap.add_argument('--onnx-threads', type=int, default=1, help='خيوط ONNX داخل النافذة')
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
        t_load = time.time() - t0
        t0 = time.time()
        with torch.inference_mode():
            em, stride = generate_emissions(model, wave, window_length=a.window,
                                           context_length=a.context, batch_size=1)
        t_em = time.time() - t0
        em = np.ascontiguousarray(em.float().numpy())
        del model
        gc.collect()
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
                window=a.window, context=a.context, batch=1)
    json.dump(meta, open(a.out + '.meta.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)

    print('[انبعاثات] %s | إطارات=%d × صنوف=%d | fps=%.2f | مدة=%.0fث | تحميل=%.1fث · توليد=%.1fث · RTF=%.2f | ذروة=%.0fMB | مصفوفة=%.1fMB' % (
        os.path.basename(a.out), meta['frames'], meta['classes'], fps, dur, t_load, t_em,
        meta['rtf'], meta['peak_rss_mb'], os.path.getsize(a.out + '.em.npy') / 1048576.0))


if __name__ == '__main__':
    main()
