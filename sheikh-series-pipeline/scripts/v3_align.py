# -*- coding: utf-8 -*-
"""v3_align.py — محاذاة CTC محكومة بمراسي v2 **مع معايرة ساعة المراسي** (توجيه المالك).

لماذا المعايرة؟ (قياس ٢٠٢٦-١٠-١٥)
  أزمنة كلمات كاش ASR (مصدر مراسي v2) **تتخلف تراكميًا** عن الصوت عند الوقفات الطويلة:
  −١٫٥ث عند الدقيقة ٥ ⇒ −٧ث (001) و−١٠ث (005) عند الدقيقة ٢٥، بينما CTC خط الإنتاج وv1
  متفقان مع الصوت في كل الدقائق (±٠٫٢ث). فلو قُطعت النوافذ بأزمنة المراسي الخام لانجرّت
  كل النوافذ المتأخرة. لذلك: **معايرة أولًا، ثم تقطيع محكوم بالمراسي، ثم تحقّق وإعادة محاذاة**.

المراحل:
  ١) مراسي v2 (Gotoh+rapidfuzz، تشابه ≥ 0.80) — للهوية.
  ٢) تمرير معايرة بنوافذ ≥ ١٢٠ث (محكومة بالمراسي في ساعة ASR) ⇒ وسيط (CTC − مرساة) لكل نافذة
     ⇒ دالة تصحيح متعدّدة القطع تُنقل بها أزمنة المراسي إلى **ساعة الصوت**.
  ٣) تقطيع نهائي عند **حدود مراسي مصحَّحة** كل ٦٠–١٢٠ث + محاذاة.
  ٤) تحقّق متقاطع: أي نافذة انحرافها عن المراسي المصحَّحة > ١٫٥ث (أو وسيطها > ٠٫٧ث) تُعاد
     بنوافذ ٢٠–٣٠ث مقطوعة **بين المراسي السليمة**، مع تجربة `<star>` لامتصاص صوت غير مفرّغ.

الاستعمال:
  v3_align.py --audio a.wav --txt t.txt --cache c.mlx.json --outdir out --tag 001 \
      [--coarse 120] [--target 90] [--resplit 25] [--tol 1.5] [--min-sim 0.80] [--v1 old.json]
"""
import argparse
import json
import os
import statistics as st
import sys
import time

import torch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import shadow_norm as SN  # noqa: E402
from v2_anchor import sim_matrix, gotoh  # المُجرَّبان (وسيط ٨٢٫٩٪ في المرحلة ١)  # noqa: E402
from ctc_forced_aligner import (load_alignment_model, generate_emissions, preprocess_text,  # noqa: E402
                                get_alignments, get_spans, postprocess_results)

MODEL = 'MahmoudAshraf/mms-300m-1130-forced-aligner'


# ───────────────────────── مراسي v2 ─────────────────────────
def anchors_from_asr(ref_words, asr, min_sim=0.80):
    ref_sh = SN.shadow_words(ref_words)
    asr_sh = SN.shadow_words([w.get('t') or w.get('n', '') for w in asr])
    matches, _ = gotoh(sim_matrix(ref_sh, asr_sh))
    out = []
    for i, j, s in matches:
        if s >= min_sim and i < len(ref_words) and asr[j].get('s') is not None:
            out.append({'i': i, 't': float(asr[j]['s']), 's': round(s, 3), 'w': ref_words[i]})
    out.sort(key=lambda a: a['i'])
    return out


# ───────────────────────── معايرة ساعة المراسي ─────────────────────────
def piecewise_offset(pts):
    """pts=[(زمن, وسيط الانحراف)] ⇒ دالة تُرجع الانزياح المتوقّع لأي زمن (تقطيع خطي)."""
    pts = sorted(pts)
    if not pts:
        return lambda t: 0.0
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    if len(pts) == 1:
        return lambda t: ys[0]

    def f(t):
        if t <= xs[0]:
            return ys[0]
        if t >= xs[-1]:
            return ys[-1]
        for k in range(1, len(xs)):
            if t <= xs[k]:
                w = (t - xs[k - 1]) / (xs[k] - xs[k - 1]) if xs[k] > xs[k - 1] else 0.0
                return ys[k - 1] + w * (ys[k] - ys[k - 1])
        return ys[-1]
    return f


# ───────────────────────── أدوات CTC ─────────────────────────
def align_text(model, tokenizer, seg, text, batch, star='segment'):
    emissions, stride = generate_emissions(model, seg, 30, 2, batch)
    tokens, text_starred = preprocess_text(text, True, 'ara', 'word', star)
    segments, scores, blank = get_alignments(emissions, tokens, tokenizer)
    spans = get_spans(tokens, segments, blank)
    return postprocess_results(text_starred, spans, stride, scores)


def dev_stats(d):
    if not d:
        return {}
    a = sorted(abs(x) for x in d)
    return {'n': len(a), 'median_abs': round(st.median(a), 2), 'max_abs': round(a[-1], 2),
            'p90_abs': round(a[int(0.9 * (len(a) - 1))], 2),
            'within_0.5': round(sum(1 for x in a if x <= 0.5) / len(a), 3),
            'within_1.0': round(sum(1 for x in a if x <= 1.0) / len(a), 3),
            'within_1.5': round(sum(1 for x in a if x <= 1.5) / len(a), 3)}


def align_window(model, tokenizer, wave, t0, t1, words, i0, i1, batch, anchors, star='segment'):
    """محاذاة نافذة (تحصين: نصّ أطول من الصوت ⇒ اقتطاع وسطي) ⇒ (نتائج، انحرافات)."""
    seg = wave[..., int(max(0.0, t0) * 16000):int(t1 * 16000)]
    if i0 >= i1:
        return {}, []

    def run(ii0, ii1, mode):
        out = align_text(model, tokenizer, seg, ' '.join(words[ii0:ii1]), batch, mode)
        got = {}
        for j, s in enumerate(out):
            gi = ii0 + j
            if gi >= ii1:
                break
            got[gi] = (round(s['start'] + t0, 2), round(s['end'] + t0, 2), s.get('score'))
        return got

    try:
        got = run(i0, i1, star)
    except Exception:
        mid, half = (i0 + i1) // 2, max(25, (i1 - i0) // 4)
        got = run(max(i0, mid - half), min(i1, mid + half), star)
    devs = [got[a['i']][0] - a['t'] for a in anchors if i0 <= a['i'] < i1 and a['i'] in got]
    return got, devs


def plan_windows(anchors, dur, target=90.0, min_span=45.0):
    """نوافذ محكومة بالمراسي: تُفتح عند مرساة وتُغلق قبل المرساة التالية التي تبعد ≥ target."""
    wins, k, n = [], 0, len(anchors)
    while k < n:
        t0 = max(0.0, anchors[k]['t'] - 0.4)
        e = k
        while e + 1 < n and anchors[e + 1]['t'] - t0 < target:
            e += 1
        while e == k and e + 1 < n and anchors[e + 1]['t'] - t0 < min_span:
            e += 1
        nxt = e + 1
        if nxt < n:
            t1 = min(dur, max(anchors[e]['t'] + 1.0, anchors[nxt]['t'] - 0.4))
            i1 = anchors[nxt]['i'] + 2
        else:
            t1, i1 = dur, 10 ** 9
        wins.append({'t0': t0, 't1': t1, 'i0': max(0, anchors[k]['i'] - 2), 'i1': i1,
                     'span': round(t1 - t0, 1)})
        k = nxt
    return wins


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--audio', required=True)
    ap.add_argument('--txt', required=True)
    ap.add_argument('--cache', required=True)
    ap.add_argument('--outdir', default='v3out')
    ap.add_argument('--tag', required=True)
    ap.add_argument('--v1', default='')
    ap.add_argument('--coarse', type=float, default=120.0)
    ap.add_argument('--target', type=float, default=90.0)
    ap.add_argument('--resplit', type=float, default=25.0)
    ap.add_argument('--tol', type=float, default=1.5)
    ap.add_argument('--min-sim', type=float, default=0.80)
    ap.add_argument('--batch', type=int, default=1)
    ap.add_argument('--calib-from', default='', help='ملفات CTC سابقة تُستخرج منها إشارة انزياح ساعة المراسي')
    ap.add_argument('--calib-bucket', type=float, default=300.0)
    a = ap.parse_args()

    T0 = time.time()
    words = open(a.txt, encoding='utf-8').read().split()
    asr = [w for w in json.load(open(a.cache, encoding='utf-8')) if w.get('s') is not None]
    anchors = anchors_from_asr(words, asr, a.min_sim)
    print('[%s] مراسي v2: %d/%d (%.1f%%) في %.2fث' % (
        a.tag, len(anchors), len(words), len(anchors) / len(words) * 100, time.time() - T0), flush=True)

    import soundfile as sf
    data, sr = sf.read(a.audio, dtype='float32', always_2d=False)
    assert sr == 16000, 'معدل العينات %d' % sr
    wave = torch.from_numpy(data.copy())
    dur = len(data) / 16000.0
    model, tokenizer = load_alignment_model('cpu', MODEL, None, torch.float32)
    print('[%s] النموذج جاهز (%.1fث)' % (a.tag, time.time() - T0), flush=True)

    # ── (٢) تمرير المعايرة: نوافذ عريضة في ساعة ASR ⇒ وسيط الانحراف لكل نافذة
    asr_end = max(x['t'] for x in anchors)
    coarse_w = [] if a.calib_from else plan_windows(anchors, min(dur, asr_end + 1.0), a.coarse, min_span=60.0)
    cal = []
    if a.calib_from:   # معايرة بلا حساب: وسيط (CTC سابق − مرساة) لكل شريحة ⇒ انزياح ساعة المراسي
        buckets = {}
        for fp in a.calib_from.split(','):
            prev = json.load(open(fp.strip(), encoding='utf-8'))['x']
            for an in anchors:
                if an['i'] < len(prev):
                    buckets.setdefault(int(an['t'] // a.calib_bucket), []).append(prev[an['i']][1] - an['t'])
        cal = [(b * a.calib_bucket + a.calib_bucket / 2.0, round(st.median(v), 2))
               for b, v in sorted(buckets.items()) if len(v) >= 15]
        print('[%s] معايرة من تشغيل سابق: %s' % (a.tag, cal), flush=True)
    for w in coarse_w:
        w['got'], w['dev'] = align_window(model, tokenizer, wave, w['t0'], w['t1'], words,
                                          w['i0'], min(w['i1'], len(words)), a.batch, anchors)
        if w['dev']:
            cal.append(((w['t0'] + w['t1']) / 2.0, st.median(w['dev'])))
        print('[%s] معايرة %.0f–%.0fث: مراسي %d وسيط Δ %s' % (
            a.tag, w['t0'], w['t1'], len(w['dev']),
            round(st.median(w['dev']), 2) if w['dev'] else '—'), flush=True)
    cfn = piecewise_offset(cal)
    anchors2 = [dict(x, t_raw=x['t'], t=x['t'] + cfn(x['t'])) for x in anchors]
    print('[%s] تصحيح ساعة المراسي: %s' % (
        a.tag, [(round(t, 0), round(o, 2)) for t, o in sorted(cal)]), flush=True)

    # ── (٣) التقطيع النهائي عند مراسي مصحَّحة + محاذاة
    wins = plan_windows(anchors2, dur, a.target)
    print('[%s] نوافذ نهائية: %d (مدى %.0f–%.0fث)' % (
        a.tag, len(wins), min(w['span'] for w in wins), max(w['span'] for w in wins)), flush=True)
    t1 = time.time()
    for w in wins:
        w['got'], w['dev'] = align_window(model, tokenizer, wave, w['t0'], w['t1'], words,
                                          w['i0'], min(w['i1'], len(words)), a.batch, anchors2)
        w['stats_first'] = dev_stats(w['dev'])
    print('[%s] المحاذاة النهائية: %.1fث' % (a.tag, time.time() - t1), flush=True)

    # ── (٤) إعادة محاذاة النوافذ المنحرفة بنوافذ ٢٠–٣٠ث بين المراسي، مع <star>
    retried = 0
    for w in wins:
        w['retried'] = False
        w['stats_final'] = w['stats_first']
        if not w['dev']:
            continue
        if not (w['stats_first'].get('max_abs', 0) > a.tol or w['stats_first'].get('median_abs', 0) > 0.7):
            continue
        inner = [x for x in anchors2 if w['i0'] <= x['i'] < min(w['i1'], len(words))
                 and w['t0'] <= x['t'] <= w['t1']]
        best = None
        for star in ('segment', 'word'):
            new, new_dev = {}, []
            s = int(w['t0'])
            while s < int(w['t1']):
                t_s0, t_s1 = s, min(w['t1'], s + a.resplit + 5)
                ins = [x for x in inner if t_s0 - 0.5 <= x['t'] <= t_s1]
                if ins:
                    got, devs = align_window(model, tokenizer, wave, t_s0, t_s1, words,
                                             max(w['i0'], ins[0]['i'] - 2), ins[-1]['i'] + 3,
                                             a.batch, anchors2, star)
                    new.update(got)
                    new_dev += devs
                s += int(a.resplit)
            sn = dev_stats(new_dev)
            if new and (best is None or sn.get('max_abs', 99) < best[1].get('max_abs', 99)):
                best = (new, sn, star)
        if best and best[1].get('max_abs', 99) < w['stats_first'].get('max_abs', 99):
            w['got'], w['stats_final'], w['retried'] = best[0], best[1], True
            retried += 1
            print('[%s] نافذة %.0f–%.0fث أُعيدت (%s) أقصى انحراف %.2fث ← %.2fث' % (
                a.tag, w['t0'], w['t1'], best[2], w['stats_first'].get('max_abs'),
                best[1].get('max_abs')), flush=True)
        else:
            print('[%s] نافذة %.0f–%.0fث: الإعادة لم تُحسّن (%s) — أُبقي الأصل' % (
                a.tag, w['t0'], w['t1'], w['stats_first'].get('max_abs')), flush=True)

    # ── تجميع
    time_map = {}
    for w in wins:
        time_map.update(w['got'])
    anchor_idx = {x['i'] for x in anchors2}
    x = [[words[gi], time_map[gi][0], time_map[gi][1],
          'a' if gi in anchor_idx else 'c', time_map[gi][2]] for gi in sorted(time_map)]
    dev_final = [time_map[a_['i']][0] - a_['t'] for a_ in anchors2 if a_['i'] in time_map]
    stats = dev_stats(dev_final)
    res = {'tag': a.tag, 'audio': a.audio, 'dur': round(dur, 1), 'words': len(words),
           'anchors_v2': len(anchors), 'anchor_ratio': round(len(anchors) / len(words), 4),
           'calibration': [[round(t, 1), round(o, 2)] for t, o in sorted(cal)],
           'windows': len(wins), 'retried': retried, 'stats_vs_v2': stats,
           'wall_s': round(time.time() - T0, 1), 'x': x,
           'windows_log': [{k: v for k, v in w.items() if k != 'got'} for w in wins]}
    os.makedirs(a.outdir, exist_ok=True)
    out_p = os.path.join(a.outdir, 'v3_%s.json' % a.tag)
    json.dump(res, open(out_p, 'w', encoding='utf-8'), ensure_ascii=False)
    print('[%s] انتهى: كلمات %d/%d (%.1f%%) | نوافذ %d (أُعيدت %d) | زمن %.1fث' % (
        a.tag, len(x), len(words), len(x) / len(words) * 100, len(wins), retried, res['wall_s']))
    print('[%s] مقابل مراسي v2 المصحَّحة: وسيط |Δ| %.2fث · ±٠٫٥ث %.0f%% · ±١ث %.0f%% · أقصى %.2fث' % (
        a.tag, stats.get('median_abs', -1), stats.get('within_0.5', 0) * 100,
        stats.get('within_1.0', 0) * 100, stats.get('max_abs', -1)), flush=True)

    # ── تقرير منطقة ٢٠–٢٥ دقيقة
    if a.v1:
        xv = json.load(open(a.v1, encoding='utf-8'))['x']
        pairs = [(x_['i'], time_map[x_['i']], x_['t_raw'], xv[x_['i']][1]) for x_ in anchors2
                 if x_['i'] in time_map and x_['i'] < len(xv) and 1200 <= xv[x_['i']][1] <= 1500]
        dv1 = [p[1] - p[3] for p in pairs]
        raw = [p[2] - p[3] for p in pairs]
        if pairs:
            print('[%s] ٢٠–٢٥د (n=%d): v3−v1 وسيط %.2fث أقصى %.2fث | مرساة خام−v1 وسيط %.2fث أقصى %.2fث' % (
                a.tag, len(pairs), st.median(dv1), max(map(abs, dv1)), st.median(raw), max(map(abs, raw))), flush=True)
        json.dump({'n': len(pairs), 'v1_dev': [round(z, 2) for z in dv1],
                   'raw_anchor_dev': [round(z, 2) for z in raw]},
                  open(os.path.join(a.outdir, 'v3_%s_region.json' % a.tag), 'w'), ensure_ascii=False)
    print('كتبت', out_p)


if __name__ == '__main__':
    main()
