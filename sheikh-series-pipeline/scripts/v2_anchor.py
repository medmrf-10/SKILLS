# -*- coding: utf-8 -*-
"""v2_anchor.py — تجربة المرحلة الأولى (جافّة، بلا ASR): المجرى الظلّي + Gotoh + rapidfuzz.

يقيس على **كاش ASR موجود** نسبة المراسي بثلاث طرق:
  v1   : difflib على تطبيع v1 (الطريقة الحالية)                                    ← «قبل»
  v2a  : Gotoh (فجوة تآلفية) + تشابه ضبابي على **تطبيع v1** (لعزل أثر الخوارزمية)
  v2b  : Gotoh + تشابه ضبابي على **المجرى الظلّي v2** (التطبيع + الخوارزمية معاً)   ← «بعد»

المراسي تُقاس على كلمات النص المرجعي: مرساة «تامة» = تشابه ١٫٠، «جيدة» = ≥ ٠٫٨.

الاستعمال:
  /root/venvs/ctc/bin/python v2_anchor.py --manifest manifest.json --out result.json
"""
import argparse
import difflib
import json
import sys
import time

import numpy as np
from rapidfuzz import fuzz, process

sys.path.insert(0, '/root/workspace/ytb-build/v2')
import shadow_norm as SN  # noqa: E402

NEG = np.float32(-1e9)


def sim_matrix(ref, asr, workers=-1):
    """تشابه Levenshtein مُطبّع (0..1) بين كل كلمة مرجعية وكل كلمة ASR."""
    if not ref or not asr:
        return np.zeros((len(ref), len(asr)), dtype=np.float32)
    S = process.cdist(ref, asr, scorer=fuzz.ratio, workers=workers, dtype=np.float32)
    return S / np.float32(100.0)


def gotoh(S, gate=0.72, open_pen=1.2, ext_pen=0.15, mismatch=-0.7):
    """محاذاة Gotoh بعقوبة فجوة تآلفية (O للفتح، E للتمديد بشرط |E| ≪ |O|).

    يُعيد (matches, score) حيث matches = [(i, j, sim)] لكلمات المطابقة.
    """
    n, m = S.shape
    M = np.full((n + 1, m + 1), NEG, dtype=np.float32)
    Ix = np.full((n + 1, m + 1), NEG, dtype=np.float32)   # فجوة في المرجع (كلمة ASR بلا مقابل)
    Iy = np.full((n + 1, m + 1), NEG, dtype=np.float32)   # فجوة في ASR (كلمة مرجعية غير منطوقة)
    bm = np.zeros((n + 1, m + 1), dtype=np.int8)
    bx = np.zeros((n + 1, m + 1), dtype=np.int32)
    by = np.zeros((n + 1, m + 1), dtype=np.int8)
    K = np.arange(m + 1, dtype=np.float32)

    M[0, 0] = 0.0
    if m:
        Ix[0, 1:] = -open_pen - K[:-1] * ext_pen
        bx[0, 1:] = 0
    if n:
        Iy[1:, 0] = -open_pen - np.arange(n, dtype=np.float32) * ext_pen
        by[1:, 0] = 1

    for i in range(1, n + 1):
        prevM, prevIx, prevIy = M[i - 1], Ix[i - 1], Iy[i - 1]
        stack = np.stack([prevM[:-1], prevIx[:-1], prevIy[:-1]])
        bm[i, 1:] = np.argmax(stack, axis=0).astype(np.int8)
        best = np.max(stack, axis=0)
        s = S[i - 1]
        M[i, 1:] = best + np.where(s >= gate, s, np.float32(mismatch))

        op = prevM[1:] - np.float32(open_pen)
        cont = prevIy[1:] - np.float32(ext_pen)
        cond = op >= cont
        Iy[i, 1:] = np.where(cond, op, cont)
        by[i, 1:] = cond.astype(np.int8)

        A = M[i].astype(np.float64) + K * float(ext_pen)
        run = np.maximum.accumulate(A)
        argk = np.maximum.accumulate(np.where(A >= run, np.arange(m + 1), -1))
        Ix[i, 1:] = (run[:-1] - K[:-1] * float(ext_pen) - float(open_pen)).astype(np.float32)
        bx[i, 1:] = argk[:-1]

    end_states = (M[n, m], Ix[n, m], Iy[n, m])
    state = int(np.argmax(end_states))
    score = float(end_states[state])
    i, j, matches = n, m, []
    guard = 0
    while (i > 0 or j > 0) and guard < 4 * (n + m + 2):
        guard += 1
        if state == 0:                      # M
            if i and j:
                matches.append((i - 1, j - 1, float(S[i - 1, j - 1])))
            state = int(bm[i, j])
            i, j = i - 1, j - 1
            if i < 0 or j < 0:
                break
        elif state == 1:                    # Ix: كلمات ASR بلا مقابل حتى العمود k
            k = int(bx[i, j])
            j = k
            state = 0
        else:                               # Iy: كلمة مرجعية غير منطوقة
            if by[i, j] == 1:
                i -= 1
                state = 0
            else:
                i -= 1
                # يبقى في Iy
        if i == 0 and j == 0:
            break
    matches.reverse()
    return matches, score


def ratios(matches, n_ref, exact=0.999, good=0.8):
    ex = sum(1 for _, _, s in matches if s >= exact)
    gd = sum(1 for _, _, s in matches if s >= good)
    return (ex / n_ref if n_ref else 0.0, gd / n_ref if n_ref else 0.0, len(matches))


def v1_ratio(ref_v1, asr_v1):
    """نسبة المراسي بطريقة v1: مربعات difflib المتطابقة تماماً على تطبيع v1."""
    sm = difflib.SequenceMatcher(a=ref_v1, b=asr_v1, autojunk=False)
    hit = sum(bl.size for bl in sm.get_matching_blocks())
    return (hit / len(ref_v1) if ref_v1 else 0.0), hit


def run_case(case):
    from pathlib import Path
    txt = Path(case['txt']).read_text(encoding='utf-8')
    ref_raw = txt.split()
    cache = json.load(open(case['cache'], encoding='utf-8'))
    asr_raw = [w.get('t', w.get('n', '')) for w in cache]
    asr_n = [w.get('n', '') for w in cache]

    ref_v1 = SN.shadow_words([SN.v1_norm(w) for w in ref_raw], use_dict=False)
    asr_v1 = [w for w in asr_n if w]
    r1, hit1 = v1_ratio(ref_v1, asr_v1)

    ref_sh = SN.shadow_words(ref_raw)
    asr_sh = SN.shadow_words(asr_raw)

    t0 = time.time()
    S1 = sim_matrix(ref_v1, asr_v1)
    m1, _ = gotoh(S1)
    t_v2a = time.time() - t0
    e1, g1, tot1 = ratios(m1, len(ref_v1))

    ref_shd = SN.shadow_words(ref_raw)
    asr_shd = SN.shadow_words(asr_raw)

    t0 = time.time()
    S2 = sim_matrix(ref_sh, asr_sh)
    m2, score2 = gotoh(S2)
    t_v2b = time.time() - t0
    e2, g2, tot2 = ratios(m2, len(ref_sh))

    t0 = time.time()
    S3 = sim_matrix(ref_shd, asr_shd)
    m3, _ = gotoh(S3)
    t_v2c = time.time() - t0
    e3, g3, tot3 = ratios(m3, len(ref_shd))

    return {
        'lesson': case['lesson'], 'model': case.get('model', ''), 'prompt_words': case.get('prompt'),
        'ref_words': len(ref_raw), 'ref_v1': len(ref_v1), 'ref_shadow': len(ref_sh),
        'asr_words': len(asr_raw), 'asr_v1': len(asr_v1), 'asr_shadow': len(asr_sh),
        'v1_exact': round(r1, 4), 'v1_hits': hit1,
        'v2a_exact_on_v1norm': round(e1, 4), 'v2a_good': round(g1, 4), 'v2a_matched': tot1, 'v2a_sec': round(t_v2a, 2),
        'v2b_exact': round(e2, 4), 'v2b_good': round(g2, 4), 'v2b_matched': tot2, 'v2b_sec': round(t_v2b, 2),
        'v2c_exact': round(e3, 4), 'v2c_good': round(g3, 4), 'v2c_matched': tot3, 'v2c_sec': round(t_v2c, 2),
        'gain_exact': round(e3 - r1, 4), 'gain_good': round(g3 - r1, 4),
        'cache': case['cache'],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--manifest', required=True)
    ap.add_argument('--out', default='')
    a = ap.parse_args()
    cases = json.load(open(a.manifest, encoding='utf-8'))
    out = []
    for c in cases:
        try:
            r = run_case(c)
        except Exception as e:
            r = {'lesson': c['lesson'], 'error': f'{type(e).__name__}: {e}'}
        out.append(r)
        print(json.dumps(r, ensure_ascii=False), flush=True)
    if a.out:
        json.dump(out, open(a.out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main()
