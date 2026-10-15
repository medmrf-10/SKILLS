# -*- coding: utf-8 -*-
"""ctc_win2.py — محاذاة CTC بنافذة، بتحميل النموذج مرّة واحدة (يتجاوز OOM وبطء إعادة التحميل).

يحمّل النموذج مرّة، يقرأ الصوت كاملاً في الذاكرة (١٠٠MB لـ٢٧ دقيقة)، ثم يمرّ على نوافذ
(~٣٠٠ ثانية) ويحاذي كلمات كل نافذة (مع كلمات تداخل من المشروع المرجعي v1)، ثم يخيط النتائج.

الاستعمال:
  ctc_win2.py --audio A.wav --text T.txt --v1 V.json --tag 001 --outdir wout [--chunk 300]
"""
import argparse
import json
import os
import time

import torch

from ctc_forced_aligner import (generate_emissions, get_alignments, get_spans,  # noqa: E402
                                load_alignment_model, load_audio, postprocess_results,
                                preprocess_text)

MODEL = 'MahmoudAshraf/mms-300m-1130-forced-aligner'


def run_one(model, tokenizer, wave, dur, words, starts, chunk, overlap, outdir, tag, batch=4):
    n_chunks = int(dur // chunk) + (1 if dur % chunk else 0)
    res, log = {}, []
    for k in range(n_chunks):
        t0, t1 = k * chunk, min(dur, (k + 1) * chunk)
        i0 = next((i for i, s in enumerate(starts) if s >= t0), len(words))
        i1 = next((i for i, s in enumerate(starts) if s >= t1), len(words))
        i0, i1 = max(0, i0 - overlap), min(len(words), i1 + overlap)
        if i1 - i0 < 5:
            continue
        text = ' '.join(words[i0:i1])
        seg = wave[..., int(t0 * 16000):int(t1 * 16000)]
        t_start = time.time()
        emissions, stride = generate_emissions(model, seg, 30, 2, batch)
        t_em = time.time() - t_start
        tokens_starred, text_starred = preprocess_text(text, True, 'ara', 'word', 'segment')
        t2 = time.time()
        segments, scores, blank = get_alignments(emissions, tokens_starred, tokenizer)
        spans = get_spans(tokens_starred, segments, blank)
        out = postprocess_results(text_starred, spans, stride, scores)
        t_dec = time.time() - t2
        for j, s in enumerate(out):
            gi = i0 + j
            if gi >= i1:
                break
            rec = {'w': s['text'], 's': round(s['start'] + t0, 2), 'e': round(s['end'] + t0, 2),
                   'p': s.get('score'), 'c': k}
            if gi not in res or (rec['p'] or -9) > (res[gi]['p'] or -9):
                res[gi] = rec
        log.append({'chunk': k, 't0': t0, 'words': i1 - i0, 'aligned': len(out),
                    't_emissions': round(t_em, 1), 't_decode': round(t_dec, 1),
                    'peak_rss_mb': round(torch.cuda.max_memory_allocated() / 1e6, 1) if False else None})
        print(json.dumps(log[-1], ensure_ascii=False), flush=True)
        torch.cuda.empty_cache() if torch.cuda.is_available() else None
    os.makedirs(outdir, exist_ok=True)
    json.dump({'v': 2, 'method': 'ctc-mms300m-windows', 'chunk_s': chunk, 'words_text': len(words),
               'words_aligned': len(res), 'coverage': round(len(res) / len(words), 4),
               'x': [[res[i]['w'], res[i]['s'], res[i]['e'], res[i]['c'], res[i]['p']] for i in sorted(res)],
               'chunks': log}, open(os.path.join(outdir, 'result_%s.json' % tag), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    return res, log


def load_wave_fallback(path, dtype=torch.float32):
    """قراءة WAV مباشرة (16k mono) بلا ffmpeg — الماك بلا ffmpeg."""
    import soundfile as sf
    data, sr = sf.read(path, dtype='float32', always_2d=False)
    if data.ndim > 1:
        data = data.mean(axis=1)
    if sr != 16000:
        raise SystemExit('معدل العينات %d ليس 16000 — حوّل الملف أولاً' % sr)
    return torch.from_numpy(data.copy()).to(dtype)  # أحادي البعد كما يفعل load_audio (flatten)


def load_wave(path, dtype=torch.float32):
    try:
        return load_audio(path, dtype, 'cpu')
    except ImportError:                     # ffmpeg غير موجود (الماك)
        print('ffmpeg غير متاح ⇒ قراءة WAV مباشرة بـsoundfile', flush=True)
        return load_wave_fallback(path, dtype)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--cases', required=True, help='JSON: [{tag,audio,text,v1}]')
    ap.add_argument('--outdir', default='wout')
    ap.add_argument('--chunk', type=int, default=300)
    ap.add_argument('--overlap-words', type=int, default=8)
    ap.add_argument('--batch', type=int, default=4)
    a = ap.parse_args()

    t0 = time.time()
    model, tokenizer = load_alignment_model('cpu', MODEL, None, torch.float32)
    print('النموذج جاهز بعد %.1fث' % (time.time() - t0), flush=True)
    import resource
    print('RSS بعد التحميل: %.0fMB' % (resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024), flush=True)

    for c in json.load(open(a.cases, encoding='utf-8')):
        words = open(c['text'], encoding='utf-8').read().split()
        v1 = json.load(open(c['v1'], encoding='utf-8'))
        starts = [r[1] for r in v1['x']]
        dur = float(v1['x'][-1][2])
        if len(starts) != len(words):
            print('تحذير %s: كلمات v1=%d != النص=%d' % (c['tag'], len(starts), len(words)), flush=True)
        t1 = time.time()
        wave = load_wave(c['audio'], torch.float32)
        tt = time.time()
        res, log = run_one(model, tokenizer, wave, dur, words, starts, a.chunk, a.overlap_words,
                           a.outdir, c['tag'], a.batch)
        print('[%s] انتهى: كلمات %d/%d (%.1f%%) | زمن %.1fث | RSS %.0fMB' % (
            c['tag'], len(res), len(words), len(res) / len(words) * 100, time.time() - tt,
            resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024), flush=True)


if __name__ == '__main__':
    main()
