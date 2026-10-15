# -*- coding: utf-8 -*-
"""ctc_windows.py — محاذاة CTC مُقطَّعة إلى نوافذ (تجاوز سقف الذاكرة).

السبب: `ctc-forced-aligner` يبني شبكة المحاذاة للصوت كله مقابل النص كله ⇒ الذاكرة تنفجر
(قُتل بالـOOM عند ٥٫٥GB لدرس ٢٧ دقيقة). الحل: تقطيع الصوت إلى نوافذ (٥ دقائق افتراضاً)
وتقطيع النص عند نفس الحدود (نستخدم توقيتات v1 كمرجع للحدود) مع تداخل كلمات، ثم خياطة النتائج.

قياس: زمن كل نافذة + ذاكرتها القصوى (RSS) من /usr/bin/time -v.
الاستعمال:
  ctc_windows.py --audio a.wav --text t.txt --v1 v1.json --outdir out/ --chunk 300
"""
import argparse
import json
import os
import subprocess
import sys
import time

ALIGNER = '/root/venvs/ctc/bin/ctc-forced-aligner'
MODEL = 'MahmoudAshraf/mms-300m-1130-forced-aligner'


def sh(cmd):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True)


def peak_mb_from_log(path):
    try:
        for line in open(path, encoding='utf-8', errors='ignore'):
            if 'Maximum resident set size' in line:
                return round(int(line.split(':')[1].strip()) / 1024.0, 1)
    except OSError:
        pass
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--audio', required=True)
    ap.add_argument('--text', required=True)
    ap.add_argument('--v1', required=True, help='ملف v1 المنشور (لتحديد حدود النوافذ)')
    ap.add_argument('--outdir', required=True)
    ap.add_argument('--chunk', type=int, default=300)
    ap.add_argument('--overlap-words', type=int, default=8)
    ap.add_argument('--batch', type=int, default=4)
    ap.add_argument('--tag', default='')
    ap.add_argument('--start-chunk', type=int, default=0)
    a = ap.parse_args()

    os.makedirs(a.outdir, exist_ok=True)
    words = open(a.text, encoding='utf-8').read().split()
    v1 = json.load(open(a.v1, encoding='utf-8'))
    x = v1['x']
    dur = float(v1['x'][-1][2])
    if len(x) != len(words):
        print('تحذير: عدد كلمات v1 (%d) != كلمات النص (%d) — سأستخدم التقسيم النسبي' % (len(x), len(words)))
    starts = [r[1] for r in x] if len(x) == len(words) else \
        [dur * i / max(1, len(words)) for i in range(len(words))]

    n_chunks = int(dur // a.chunk) + (1 if dur % a.chunk else 0)
    results = {}
    summary = []
    for k in range(a.start_chunk, n_chunks):
        t0 = k * a.chunk
        t1 = min(dur, t0 + a.chunk)
        i0 = next((i for i, s in enumerate(starts) if s >= t0), len(words))
        i1 = next((i for i, s in enumerate(starts) if s >= t1), len(words))
        i0 = max(0, i0 - a.overlap_words)
        i1 = min(len(words), i1 + a.overlap_words)
        if i1 - i0 < 5:
            continue
        cw = os.path.join(a.outdir, 'chunk_%s_%03d.wav' % (a.tag or 'x', k))
        ct = os.path.join(a.outdir, 'chunk_%s_%03d.txt' % (a.tag or 'x', k))
        open(ct, 'w', encoding='utf-8').write(' '.join(words[i0:i1]))
        sh('ffmpeg -y -loglevel error -ss %.2f -t %.2f -i %s -ac 1 -ar 16000 -c:a pcm_s16le %s'
           % (t0, t1 - t0, a.audio, cw))
        t_start = time.time()
        log = os.path.join(a.outdir, 'chunk_%s_%03d.time.log' % (a.tag or 'x', k))
        cmd = ('/usr/bin/time -v %s --audio_path %s --text_path %s --language ara --romanize '
               '--alignment_model %s --compute_dtype float32 --batch_size %d --device cpu > %s 2>&1'
               % (ALIGNER, cw, ct, MODEL, a.batch,
                  os.path.join(a.outdir, 'chunk_%s_%03d.log' % (a.tag or 'x', k))))
        r = sh(cmd)
        wall = time.time() - t_start
        oj = cw[:-4] + '.json'
        ok = os.path.exists(oj)
        nseg = 0
        if ok:
            segs = json.load(open(oj, encoding='utf-8'))['segments']
            nseg = len(segs)
            for j, s in enumerate(segs):
                gi = i0 + j
                if gi >= i1:
                    break
                rec = {'w': s['text'], 's': round(s['start'] + t0, 2), 'e': round(s['end'] + t0, 2),
                       'p': s.get('score'), 'chunk': k}
                if gi not in results or (rec['p'] or -9) > (results[gi]['p'] or -9):
                    results[gi] = rec
        summary.append({'chunk': k, 't0': t0, 't1': t1, 'words': len(range(i0, i1)), 'aligned': nseg,
                        'wall_s': round(wall, 1), 'peak_rss_mb': peak_mb_from_log(log), 'ok': ok})
        print(json.dumps(summary[-1], ensure_ascii=False), flush=True)
        for f in (cw, ct):
            try:
                os.remove(f)
            except OSError:
                pass
        json.dump({'v': 2, 'method': 'ctc-mms300m-windows', 'chunk_s': a.chunk,
                   'words_text': len(words), 'words_aligned': len(results),
                   'coverage': round(len(results) / len(words), 4),
                   'x': [[results[i]['w'], results[i]['s'], results[i]['e'], results[i]['chunk'],
                          results[i]['p']] for i in sorted(results)] if len(results) == len(words) else [],
                   'chunks': summary},
                  open(os.path.join(a.outdir, 'result_%s.json' % (a.tag or 'x')), 'w', encoding='utf-8'),
                  ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main()
