#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ctc_pure_align.py — محاذاة نقيّة على مصفوفة الانبعاثات (Sliding-Horizon Viterbi).

بلا Whisper · بلا مراسي ASR · بلا كاش كلمات · بلا معايرة ساعة.
المدخل: مصفوفة انبعاثات <prefix>.em.npy + النص المرجعي + <prefix>.meta.json (اختياري).

المبدأ
  • نافذة إطارات متداخلة (~120ث) مقابل شريحة كلمات مقدَّرة بمعدل الكلام المُرصَد + هامش كلمات،
    ورزم <star> يُدرجها المحاذي لكل كلمة وفي الذيل لامتصاص الاستطرادات والصمت (و«الفراغ» يمتص
    ما لا كلام فيه)، فلا تسحب الاستطرادات أزمنة الكلمات المجاورة.
  • تُثبّت أول `--pin` ثانية موثوقة من كل نافذة، ثم يزحف المؤشر (frame, word) من نهاية آخر كلمة
    مثبتة إلى نهاية الدرس، ويُعاد تقدير معدل الكلام من المثبَّت (تحوّل ذاتي بلا أي مرساة خارجية).
  • الاستيفاء: الكلمات التي ثقتها أدنى من `--min-score` تُقدَّر خطيًا بين الجارتين الموثوقتين
    وتُوسم `i` (المحاذاة الحقيقية تُوسم `a`).

الذاكرة: شريحة انبعاثات (~0.7MB لـ120ث) + فيتربي الشريحة وحدها (≈20–40MB) — لا مصفوفة للملف كاملًا.

المخرجات
  align.json  بنية v1 المتوافقة مع الموقع: {cov, start, dur, audio, align_meta, x=[[كلمة,بداية,نهاية,علامة],…]}
  report.json التغطية · الأزمنة · الذروة · قياس التحقق المتقاطع (اختياري مع --v1) وتوزيع الدقائق

الاستعمال
  ctc_pure_align.py --em work/001.em.npy --tokens work/001.tokens.json --out v3out/001.align.json \
      [--slice 120] [--pin 65] [--margin 30] [--star segment] [--min-score -2.0] [--v1 old.align.json] [--tag 001]
      [--pause-cut 1] [--shadow-norm 1]
"""
import argparse
import json
import os
import resource
import statistics as st
import sys
import time

import numpy as np
import torch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ctc_forced_aligner import get_alignments, get_spans, postprocess_results, preprocess_text  # noqa: E402
from shadow_norm import shadow, v1_norm  # noqa: E402  — التطبيع الظلّي (عثماني/ألف خنجرية/تفقيط الأرقام)


class TokShim:
    """يوفّر ما يطلبه get_alignments (مفردات + blank/pad) بلا تحميل أي نموذج."""

    def __init__(self, vocab, pad):
        self._v = vocab
        self.vocab_size = len(vocab)
        self.pad_token_id = pad

    def get_vocab(self):
        return self._v


def shadow_words_1to1(words, use_dict=True, unify=True):
    """تطبيع ظلّي بكلمة ظلّية **واحدة متصلة غير فارغة** لكل كلمة أصلية (يمنع انزياح الفهارس).

    الشرط الهندسي: preprocess_text يقطّع على المسافات ويربط المخرجات بـ gi = i0 + j، فأي كلمة
    تُنتج أكثر من كلمة أو تُنتج فراغًا تزيح فهارس كل ما بعدها. لذلك: ندمج تفقيط الأرقام بلا مسافات،
    ونعوّض علامات الترقيم الصافية بحرف صوتي بديل (ألف) بدل حذفها.
    """
    import re as _re
    out = []
    for w in words:
        s = shadow(w, use_dict, unify).replace(' ', '')            # تفقيط الأرقام مدموجًا بلا فواصل
        if not s and _re.search(r'[0-9\u0660-\u0669]', str(w)):   # أرقام مخلوطة بترقيم ⇒ فقّط كل مجرى رقمي
            runs = _re.findall(r'[0-9\u0660-\u0669]+', str(w))
            s = ''.join(shadow(r, use_dict, unify).replace(' ', '') for r in runs)
        if not s:
            s = v1_norm(w) or 'ا'                           # بديل صوتي مضمون غير فارغ
        out.append(s)
    return out


def align_slice(em, tok, words, i0, i1, f0, f1, stride_ms, star, nwords=None, star_pen=0.0, star_col=None):
    """يحاذي em[f0:f1] على الكلمات words[i0:i1] ⇒ {فهرس عام: (بداية, نهاية, ثقة)} بأزمنة مطلقة.

    nwords = الكلمات الظلّية المطبَّعة (١:١ مع words) — تُمرَّر للفيتربي، والمخرجات تبقى بـwords الأصلية.
    """
    src = nwords if nwords is not None else words
    text = ' '.join(src[i0:i1])
    tokens, text_starred = preprocess_text(text, True, 'ara', 'word', star)
    sub = torch.from_numpy(np.array(em[f0:f1], dtype=np.float32, copy=True))
    if star_pen and star_col is not None and 0 <= star_col < sub.shape[1]:
        sub[:, star_col] = sub[:, star_col] + float(star_pen)   # عقوبة على عمود <star> المضاف
    segments, scores, blank = get_alignments(sub, tokens, tok)
    spans = get_spans(tokens, segments, blank)
    out = postprocess_results(text_starred, spans, stride_ms, scores)
    off = f0 * stride_ms / 1000.0
    got = {}
    for j, s in enumerate(out):
        gi = i0 + j
        if gi >= i1:
            break
        got[gi] = (round(s['start'] + off, 2), round(s['end'] + off, 2), s.get('score'))
    return got


def interpolate(times, words, min_score):
    """استيفاء خطي للكلمات ضعيفة الثقة/المفقودة بين جارتين موثوقتين ⇒ (الأزمنة, العلامات)."""
    n = len(words)
    flags = ['a' if i in times else '' for i in range(n)]
    for i in range(n):
        if i in times and times[i][2] is not None and times[i][2] < min_score:
            flags[i] = 'i'
    known = [i for i in range(n) if flags[i] == 'a']
    if not known:                                     # لا ثقة إطلاقًا ⇒ توزيع خطي على المدة
        return times, flags
    for i in range(n):
        if flags[i] == 'a':
            continue
        prev = max([k for k in known if k < i], default=None)
        nxt = min([k for k in known if k > i], default=None)
        if prev is None and nxt is None:
            continue
        if prev is None:
            s, e = times[nxt][0], times[nxt][0]
        elif nxt is None:
            s, e = times[prev][1], times[prev][1]
        else:
            s, e = times[prev][1], times[nxt][0]
            if e < s:
                s = e = times[prev][1]
        k = (i - prev) if prev is not None and nxt is not None else 1
        m = (nxt - prev) if prev is not None and nxt is not None else 1
        s = s + (e - s) * ((i - prev) / m if m else 0)
        times[i] = (round(s, 2), round(s, 2), None)
    return times, flags



def _norm_len(w):
    """طول الكلمة بعد نزع الترقيم (يقارب ما يراه المحاذي فعلًا)."""
    import re as _re
    return len(_re.sub(r'[^\w\u0600-\u06FF]', '', str(w)))


def solid_cut(new, nwords, rate, a):
    """أعلى فهرس «كلمة صلبة» بين المرشّحين (طول ≥ solid-min-len · ثقة ≥ solid-min-score · اتساق معدل محلي).

    الغرض الهندسي: بدل التسليم الأعمى عند آخر كلمة تحت الأفق (وقد تكون كلمة منجرفة داخل استطراد
    فتورّث إزاحتها للشريحة التالية)، نرجع للخلف حتى آخر كلمة تحقّق الشروط الثلاثة ونقطع التثبيت عندها.
    يرجع None إن لم توجد كلمة صلبة (فيُبقى السلوك السابق لضمان التقدّم).
    """
    if not new:
        return None
    idx = sorted(new)
    i_first = idx[0]
    t_first = new[i_first][0]
    for relax in (0, 1, 2):
        for i in reversed(idx):
            s, e, sc = new[i]
            if relax < 1 and _norm_len(nwords[i]) < a.solid_min_len:
                continue
            if relax < 2 and (sc is None or sc < a.solid_min_score):
                continue
            if i > i_first:
                span = max(1e-6, e - t_first)
                local = (i - i_first + 1) / span
                if rate > 0 and (local < 0.35 * rate or local > 2.5 * rate):
                    continue
            return i
    return None


def island_demote(times, nwords, rate, a):
    """حارس الجزر: كلمة قصيرة (≤3 أحرف) أو ضعيفة الثقة تشكّل جزيرة زمنية معزولة بين مرساتين صلبتين
    (معدل محلي خارج 0.3–3.0 × معدل الكلام) ⇒ تُعاد علامتها إلى i لتُستوفى خطيًا.
    """
    solid = sorted(i for i, v in times.items()
                   if _norm_len(nwords[i]) >= a.solid_min_len and (v[2] is None or v[2] >= a.solid_min_score))
    dem = []
    for i, (s, e, sc) in list(times.items()):
        short = _norm_len(nwords[i]) <= 3
        weak = sc is not None and sc < -0.8
        if not (short or weak):
            continue
        prev = max([k for k in solid if k < i], default=None)
        nxt = min([k for k in solid if k > i], default=None)
        if prev is None or nxt is None:
            continue
        gap = times[nxt][0] - times[prev][1]
        if gap <= 0:
            continue
        local = (nxt - prev + 1) / gap
        if rate > 0 and (local < 0.3 * rate or local > 3.0 * rate):
            dem.append(i)
    return dem


def main():
    ap = argparse.ArgumentParser(description='محاذاة CTC نقيّة من مصفوفة انبعاثات (بلا Whisper)')
    ap.add_argument('--em', required=True, help='ملف الانبعاثات .em.npy')
    ap.add_argument('--tokens', help='.tokens.json (افتراضي: بجوار --em)')
    ap.add_argument('--out', required=True, help='ملف align.json الناتج')
    ap.add_argument('--tag', default='')
    ap.add_argument('--slice', type=float, default=120.0, help='طول شريحة الإطارات (ث)')
    ap.add_argument('--pin', type=float, default=65.0, help='ما يُثبّت من أول كل شريحة (ث)')
    ap.add_argument('--margin', type=int, default=30, help='هامش كلمات إضافي في ذيل الشريحة')
    ap.add_argument('--min-words', type=int, default=12, help='أدنى عدد كلمات في الشريحة')
    ap.add_argument('--star', default='segment', choices=['segment', 'edges'])
    ap.add_argument('--pause-cut', type=int, default=1, help='اقطع الشرائح عند فواصل الصمت الطبيعية')
    ap.add_argument('--pause-min-frames', type=int, default=15, help='أدنى طول صمت (إطارًا) = 0.3ث')
    ap.add_argument('--pause-tol', type=float, default=10.0, help='مدى البحث عن أقرب صمت (ث)')
    ap.add_argument('--min-score', type=float, default=-2.0, help='حدّ الثقة للاستيفاء الخطي')
    ap.add_argument('--star-pen', type=float, default=-0.9,
                    help='عقوبة لوغاريتمية تُضاف لعمود <star> المضاف قبل الفيتربي (-0.9 = الافتراضي المُقاس)')
    ap.add_argument('--solid-handoff', type=int, default=1,
                    help='تسليم محكوم بمرساة صلبة: يقطع التثبيت عند آخر كلمة صلبة لا عند أي كلمة')
    ap.add_argument('--solid-min-len', type=int, default=4, help='أدنى طول كلمة صلبة (بعد التطبيع)')
    ap.add_argument('--solid-min-score', type=float, default=-1.0, help='أدنى ثقة لكلمة صلبة')
    ap.add_argument('--island-guard', type=int, default=0,
                    help='حارس الجزر (مُقاس 2026-10-15: يخفض دقة 001 بـ3.9 نقطة ⇒ مطفأ افتراضيًا؛ شغّله للتحقق)')
    ap.add_argument('--v1', default='', help='ملف محاذاة مرجعي للتحقق المتقاطع (اختياري)')
    ap.add_argument('--shadow-unify', type=int, default=0,
                    help='توحيد الحروف (ة→ه · ى→ي) — مفيد لمطابقة ASR وضارّ لمحاذي CTC الصوتي')
    ap.add_argument('--shadow-norm', type=int, default=1,
                    help='تطبيع ظلّي ١:١ (عثماني/ألف خنجرية U+0670/تفقيط أرقام) قبل preprocess_text')
    ap.add_argument('--report', default='', help='ملف report.json (افتراضي: بجوار --out)')
    a = ap.parse_args()

    base = a.em[:-7] if a.em.endswith('.em.npy') else os.path.splitext(a.em)[0]
    tk_path = a.tokens or (base + '.tokens.json')
    meta = {}
    if os.path.exists(base + '.meta.json'):
        meta = json.load(open(base + '.meta.json', encoding='utf-8'))
    if not os.path.exists(tk_path):
        raise SystemExit('لا يوجد ملف توكنات: %s' % tk_path)
    tj = json.load(open(tk_path, encoding='utf-8'))
    words, vocab = tj['words'], {k.lower(): v for k, v in tj['vocab'].items()}
    tok = TokShim(vocab, tj.get('pad'))
    em = np.load(a.em, mmap_mode='r')
    T, C = em.shape
    stride_ms = float(meta.get('stride_ms', 20.0))
    fps = float(meta.get('fps') or (1000.0 / stride_ms))
    dur = T / fps
    N = len(words)
    if meta.get('n_words') not in (None, N):
        print('[%s] تنبيه: عدد كلمات النص (%d) ≠ المسجَّل في meta (%s)' % (a.tag, N, meta.get('n_words')), flush=True)

    nwords = None
    if a.shadow_norm:
        nwords = shadow_words_1to1(words, unify=bool(a.shadow_unify))
        assert len(nwords) == N, 'التطبيع الظلّي كسر التناظر ١:١ ✗'
        changed = sum(1 for o, n in zip(words, nwords) if o != n)
        fal = sum(1 for n in nwords if n == 'ا' and n not in words)
        print('[%s] تطبيع ظلّي ١:١: تغيّرت %d/%d كلمة · بديل صوتي لعلامات %d كلمة · مثال: «%s» ⇒ «%s»' % (
            a.tag, changed, N, fal, next((o for o, n in zip(words, nwords) if o != n), ''), next((n for o, n in zip(words, nwords) if o != n), '')), flush=True)

    t_start = time.time()
    times, pins, forced = {}, 0, 0
    fc, wc = 0, 0
    B = None                     # إطارات فواصل الصمت الطبيعية (من مصفوفة الانبعاثات، بلا أي ASR)
    blank_id = int(tj.get('blank') if tj.get('blank') is not None else vocab.get('<blank>', 0))
    Cv = int(tj.get('vocab_size') or len(vocab))
    star_col = Cv if C > Cv else None          # عمود <star> المضاف (آخر عمود) إن وُجد
    if a.pause_cut:
        Cv = int(tj.get('vocab_size') or len(vocab))          # عدد أصناف النموذج بلا عمود <star> المضاف
        amv = np.asarray(em[:, :Cv]).argmax(1) if C > Cv else np.asarray(em).argmax(1)
        isb = (amv == blank_id).astype(np.int8)
        d = np.diff(np.concatenate([[0], isb, [0]]))
        st_b, en_b = np.flatnonzero(d == 1), np.flatnonzero(d == -1)
        B = en_b[(en_b - st_b) >= a.pause_min_frames]
        print('[%s] فواصل صمت طبيعية: %d (أدنى %d إطارًا · blank=%d)' % (a.tag, len(B), a.pause_min_frames, blank_id), flush=True)
    rate = N / dur if dur > 0 else 1.0                 # كلمات/ثانية تقديرية أولية
    print('[%s] انبعاثات %d إطارًا × %d صنفًا · %.0fث · %d كلمة · معدل ابتدائي %.2f كلمة/ث · star=%s' % (
        a.tag, T, C, dur, N, rate, a.star), flush=True)

    while wc < N and fc < T:
        tc = fc / fps
        n_est = max(a.min_words, int(round(rate * min(a.slice, max(5.0, dur - tc)))))
        wi1 = min(N, wc + n_est + a.margin)
        fi1 = min(T, fc + int(a.slice * fps))
        if B is not None and fi1 < T:                    # ① اقترب من فاصل صمت طبيعي (بلا أي ASR)
            lo_b = fc + int(0.4 * a.slice * fps)
            cand = B[(B > lo_b) & (np.abs(B - fi1) <= int(a.pause_tol * fps))]
            if len(cand):
                fi1 = int(cand[np.argmin(np.abs(cand - fi1))])
        margin = a.margin
        while True:                                     # تحصين: عند فشل التثبيت تُقلَّص الشريحة
            try:
                got = align_slice(em, tok, words, wc, wi1, fc, fi1, stride_ms, a.star, nwords, a.star_pen, star_col)
            except Exception as e:
                got = {}
                print('[%s]   [!] فشل شريحة %.0f–%.0fث (%s: %s)' % (a.tag, tc, fi1 / fps, type(e).__name__, str(e)[:80]), flush=True)
            horizon = tc + a.pin
            new = {i: v for i, v in got.items() if v[1] <= horizon and v[1] > v[0] - 0.01}
            if new or margin <= 0:
                break
            margin -= 10                                # قلّل الهامش ثم أعد المحاولة على الشريحة نفسها
            wi1 = min(N, wc + n_est + margin)
        if not new:                                     # لا تثبيت: تقدّم اضطراري لضمان التقدّم
            forced += 1
            step_f = int(a.slice * fps / 2)
            step_w = max(1, n_est // 2)
            print('[%s]   [!] شريحة %.0fث بلا تثبيت ⇒ تقدّم اضطراري %.0fث / %d كلمة' % (
                a.tag, tc, step_f / fps, step_w), flush=True)
            fc += step_f
            wc += step_w
            continue
        if a.solid_handoff:
            cut_i = solid_cut(new, nwords if nwords is not None else words, rate, a)
            if cut_i is not None and cut_i < max(new):
                dropped = sum(1 for i in new if i > cut_i)
                new = {i: v for i, v in new.items() if i <= cut_i}
                if dropped:
                    print('[%s]   ↳ تسليم صلب عند الكلمة %d (أُعيد %d كلمة للشريحة التالية)' % (a.tag, cut_i, dropped), flush=True)
        times.update(new)
        pins += len(new)
        last_end = max(v[1] for v in new.values())
        first_i = min(new)
        wc0, tc0 = wc, tc
        wc = max(new) + 1
        fc = max(fc + 1, int(last_end * fps) - int(0.4 * fps))     # تداخل صغير يضمن عدم فقدان كلمة
        span_t = max(1e-6, last_end - tc0)
        rate = (wc - wc0) / span_t
        if first_i != wc0:
            wc = max(wc, first_i + 1)
        print('[%s]   شريحة %.0f–%.0fث ⇒ ثُبّت %d كلمة حتى %.0fث (معدل %.2f كلمة/ث)' % (
            a.tag, tc, fi1 / fps, len(new), last_end, rate), flush=True)

    # الكلمات المتبقية في الذيل (إن وُجدت) بتوسيع الشريحة إلى أقصى ما تبقّى
    if wc < N:
        got = {}
        try:
            got = align_slice(em, tok, words, wc, N, int(fc), T, stride_ms, a.star, nwords, a.star_pen, star_col)
        except Exception as e:
            print('[%s]   [!] فشل شريحة الذيل: %s' % (a.tag, type(e).__name__), flush=True)
        for i, v in got.items():
            times.setdefault(i, v)
        print('[%s] ذيل: أُضيف %d كلمة من أصل %d متبقية' % (a.tag, len(got), N - wc), flush=True)

    wall = time.time() - t_start
    if a.island_guard and times:
        dem = island_demote(times, nwords if nwords is not None else words, rate, a)
        for i in dem:
            s, e, sc = times[i]
            times[i] = (s, e, -999.0)              # ⇒ يوسم i ويُستوفى خطيًا بين المراسي الصلبة
        if dem:
            print('[%s] حارس الجزر: %d كلمة قصيرة/معزولة ⇒ استيفاء خطي' % (a.tag, len(dem)), flush=True)
    times, flags = interpolate(times, words, a.min_score)
    x = []
    for i, w in enumerate(words):
        s, e, _ = times.get(i, (None, None, None))
        if s is None:
            x.append([w, None, None, ''])
        else:
            x.append([w, s, e, flags[i] or 'i'])
    aligned = sum(1 for r in x if r[3] == 'a')
    covered = sum(1 for r in x if r[1] is not None)
    report = dict(tag=a.tag, words=N, aligned=aligned, interpolated=covered - aligned,
                  covered=covered, coverage=round(covered / N * 100, 2),
                  align_coverage=round(aligned / N * 100, 2), pinned=pins, forced=forced,
                  dur=round(dur, 1), frames=int(T), fps=round(fps, 3), slice=a.slice, pin=a.pin,
                  margin=a.margin, star=a.star, min_score=a.min_score, shadow_norm=bool(a.shadow_norm),
                  star_pen=a.star_pen, solid_handoff=bool(a.solid_handoff), solid_min_len=a.solid_min_len,
                  solid_min_score=a.solid_min_score, island_guard=bool(a.island_guard), pause_cut=bool(a.pause_cut),
                  align_wall_s=round(wall, 1), peak_rss_mb=round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0, 1),
                  em_meta=meta)

    if a.v1 and os.path.exists(a.v1):
        v1 = json.load(open(a.v1, encoding='utf-8'))
        rows = v1.get('x') if isinstance(v1, dict) else v1
        ref, rtxt = [], []
        for r in rows:
            if isinstance(r, dict):
                ref.append(r.get('s') if isinstance(r.get('s'), (int, float)) else None)
                rtxt.append(str(r.get('w', '')))
            else:
                ref.append(r[1] if len(r) >= 3 and isinstance(r[1], (int, float)) else None)
                rtxt.append(str(r[0]))
        # المطابقة بالفهرس لا بالنص: الكلمات المكرّرة في الدرس تُفسد أي مطابقة نصية.
        devs, reg, ntxt = [], [], 0
        for i, r in enumerate(x):
            if i >= len(ref) or ref[i] is None or r[1] is None:
                continue
            if rtxt[i] and rtxt[i] == r[0]:
                ntxt += 1
            d = abs(r[1] - ref[i])
            devs.append(d)
            if 1200 <= r[1] <= 1500:
                reg.append(d)
        if devs:
            ds = sorted(devs)
            report['vs_v1'] = dict(n=len(devs), text_match=ntxt, text_match_pct=round(ntxt / len(devs) * 100, 1),
                                   median=round(st.median(devs), 2), p90=round(ds[int(len(ds) * 0.9)], 2),
                                   max=round(max(devs), 2), within_0_1=round(sum(1 for d in devs if d <= 0.1) / len(devs) * 100, 1),
                                   within_0_2=round(sum(1 for d in devs if d <= 0.2) / len(devs) * 100, 1),
                                   within_0_5=round(sum(1 for d in devs if d <= 0.5) / len(devs) * 100, 1),
                                   within_1=round(sum(1 for d in devs if d <= 1.0) / len(devs) * 100, 1),
                                   within_1_5=round(sum(1 for d in devs if d <= 1.5) / len(devs) * 100, 1),
                                   window_20_25_n=len(reg),
                                   window_20_25_median=round(st.median(reg), 2) if reg else None,
                                   window_20_25_p90=round(sorted(reg)[int(len(reg) * 0.9)], 2) if reg else None,
                                   window_20_25_gt1=round(sum(1 for d in reg if d > 1) / len(reg) * 100, 0) if reg else None,
                                   window_20_25_gt2=round(sum(1 for d in reg if d > 2) / len(reg) * 100, 0) if reg else None)
    out = dict(cov=report['coverage'], start=0.0, dur=round(dur, 2), audio=meta.get('audio'),
               align_meta=dict(engine='ctc-pure', model=meta.get('model'), fps=round(fps, 3),
                               slice=a.slice, pin=a.pin, margin=a.margin, star=a.star, shadow_norm=bool(a.shadow_norm),
                               aligned=aligned, interpolated=covered - aligned, wall_s=round(wall, 1)),
               x=x)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)) or '.', exist_ok=True)
    json.dump(out, open(a.out, 'w', encoding='utf-8'), ensure_ascii=False)
    rp = a.report or (os.path.splitext(a.out)[0] + '.report.json')
    json.dump(report, open(rp, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('[%s] ✓ %s | تغطية %.1f%% (محاذاة %.1f%% · استيفاء %d) | %d كلمة مثبتة · %d تقدّم اضطراري | زمن %.1fث · ذروة %.0fMB' % (
        a.tag, os.path.basename(a.out), report['coverage'], report['align_coverage'],
        report['interpolated'], pins, forced, wall, report['peak_rss_mb']))
    if 'vs_v1' in report:
        v = report['vs_v1']
        print('[%s] تحقق متقاطع مع v1 (بالفهرس): n=%d · تطابق نصي %.0f%% · وسيط=%.2fث ±0.5ث=%.0f%% ±1ث=%.0f%% | النافذة ٤ (20–25د): n=%d وسيط=%sث p90=%sث >1ث=%s%% >2ث=%s%%' % (
            a.tag, v['n'], v['text_match_pct'], v['median'], v['within_0_1'], v['within_0_2'], v['within_0_5'], v['within_1'], v['window_20_25_n'],
            v['window_20_25_median'], v['window_20_25_p90'], v['window_20_25_gt1'], v['window_20_25_gt2']))


if __name__ == '__main__':
    main()
