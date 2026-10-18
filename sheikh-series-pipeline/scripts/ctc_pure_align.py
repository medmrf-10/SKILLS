#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ctc_pure_align.py — محاذاة نقيّة على مصفوفة الانبعاثات (Sliding-Horizon Viterbi v4.2).

بلا Whisper · بلا مراسي ASR · بلا كاش كلمات · بلا معايرة ساعة.
المدخل: مصفوفة انبعاثات <prefix>.em.npy + النص المرجعي + <prefix>.meta.json (اختياري).

المبدأ
  • نافذة إطارات متداخلة (~120ث) مقابل شريحة كلمات مقدَّرة بمعدل الكلام المُرصَد + هامش كلمات،
    ورزم <star> يُدرجها المحاذي لكل كلمة وفي الذيل لامتصاص الاستطرادات والصمت (مع عقوبة لوغاريتمية
    --star-pen -0.9 تمنع عمود <star> من ابتلاع الكلمات القصيرة)، فلا تسحب الاستطرادات أزمنة الكلمات المجاورة.
  • تُثبّت أول `--pin` ثانية موثوقة من كل نافذة، مع تسليم محكوم بمرساة صلبة (`--solid-handoff 1`)
    يرجع للخلف حتى آخر كلمة صلبة قبل الأفق، ثم يزحف المؤشر (frame, word) إلى نهاية الدرس.
  • تخطي علامات الترقيم الصامتة المستقلة (`*`، `ۖ`، `ۚ`) أثناء فيتربي عبر خريطة فهارس صريحة (`active_idx`)
    ثم ربطها بحدّ الكلمة المنطوقة السابقة حتى لا تسرق إطارات صوتية من الكلمات الحقيقية.
  • الاستيفاء: الكلمات التي ثقتها أدنى من `--min-score` تُقدَّر خطيًا بفترات متناسبة `(start, end)`
    بين الجارتين الموثوقتين وتُوسم `i` (المحاذاة الصوتية المباشرة تُوسم `a`).
  • كشف البتر النصي آليًا بحساب `audio_span_pct` (نسبة امتداد النص على مدة الصوت الكلية).

الذاكرة: شريحة انبعاثات (~0.7MB لـ120ث) + فيتربي الشريحة وحدها (≈20–40MB) — لا مصفوفة للملف كاملًا.
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
from shadow_norm import shadow, v1_norm  # noqa: E402


class TokShim:
    """يوفّر ما يطلبه get_alignments (مفردات + blank/pad) بلا تحميل أي نموذج."""

    def __init__(self, vocab, pad):
        self._v = vocab
        self.vocab_size = len(vocab)
        self.pad_token_id = pad

    def get_vocab(self):
        return self._v


def peak_mb():
    """ذروة الذاكرة بالميغابايت (macOS يعيد ru_maxrss بالبايت، ولينكس بالكيلوبايت)."""
    r = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return r / (1024.0 * 1024.0) if sys.platform == 'darwin' else r / 1024.0


def shadow_words_1to1(words, use_dict=True, unify=True):
    """تطبيع ظلّي لكل كلمة أصلية (تفقيط الأرقام مدموجًا، وتخطي الرموز الصامتة المستقلة).

    إذا كانت الكلمة رمز ترقيم صامتًا خالصًا (مثل `*` أو علامة وقف قرآنية منفردة `ۖ`)، تُعاد سلسلة
    فارغة `''` ليتخطاها `align_slice` في فيتربي عبر خريطة فهارس صريحة بدل إجبار فيتربي على مطابقة حرف «ا».
    """
    import re as _re
    out = []
    for w in words:
        s = shadow(w, use_dict, unify).replace(' ', '')            # تفقيط الأرقام مدموجًا بلا فواصل
        if not s and _re.search(r'[0-9\u0660-\u0669]', str(w)):   # أرقام مخلوطة بترقيم ⇒ فقّط كل مجرى رقمي
            runs = _re.findall(r'[0-9\u0660-\u0669]+', str(w))
            s = ''.join(shadow(r, use_dict, unify).replace(' ', '') for r in runs)
        if not s:
            s = v1_norm(w) or ''                                   # فارغ للرموز الصامتة الخالصة
        out.append(s)
    return out


def align_slice(em, tok, words, i0, i1, f0, f1, stride_ms, star, nwords=None, star_pen=0.0, star_col=None):
    """يحاذي em[f0:f1] على الكلمات المنطوقة في words[i0:i1] ⇒ {فهرس عام: (بداية, نهاية, ثقة)} بأزمنة مطلقة.

    يتخطى الرموز الصامتة الخالصة (حيث nwords[gi] == '') أثناء حساب فيتربي ثم يربطها بحدّ الكلمة السابقة،
    ويطبّق العقوبة اللوغاريتمية `star_pen` على عمود `<star>` المضاف.
    """
    src = nwords if nwords is not None else words
    active_idx = [gi for gi in range(i0, i1) if src[gi]]
    if not active_idx:
        return {}
    n_sub_frames = max(1, int(f1) - int(f0))
    while len(active_idx) > 1:
        text = ' '.join(src[gi] for gi in active_idx)
        tokens, text_starred = preprocess_text(text, True, 'ara', 'word', star)
        repeats = sum(1 for k in range(1, len(tokens)) if tokens[k] == tokens[k - 1])
        if len(tokens) + repeats + 8 < n_sub_frames:
            break
        new_len = max(1, int(len(active_idx) * 0.72))
        if new_len >= len(active_idx):
            new_len = len(active_idx) - 1
        active_idx = active_idx[:new_len]
    else:
        text = ' '.join(src[gi] for gi in active_idx)
        tokens, text_starred = preprocess_text(text, True, 'ara', 'word', star)
    sub = torch.from_numpy(np.array(em[f0:f1], dtype=np.float32, copy=True))
    if star_pen and star_col is not None and 0 <= star_col < sub.shape[1]:
        sub[:, star_col] = sub[:, star_col] + float(star_pen)
    segments, scores, blank = get_alignments(sub, tokens, tok)
    spans = get_spans(tokens, segments, blank)
    out = postprocess_results(text_starred, spans, stride_ms, scores)
    off = f0 * stride_ms / 1000.0
    got = {}
    for j, s in enumerate(out):
        if j >= len(active_idx):
            break
        gi = active_idx[j]
        got[gi] = (round(s['start'] + off, 2), round(s['end'] + off, 2), s.get('score'))

    # ربط الرموز الصامتة داخل الشريحة بحدّ الكلمة المنطوقة السابقة حتى يتقدم المؤشر بسلاسة
    last_t = None
    for gi in range(i0, min(i1, (active_idx[-1] + 1) if active_idx else i1)):
        if gi in got:
            last_t = got[gi][1]
        elif not src[gi] and last_t is not None:
            got[gi] = (last_t, last_t, None)
    return got


def _norm_len(w):
    """طول الكلمة بعد نزع الترقيم (يقارب ما يراه المحاذي فعلًا)."""
    import re as _re
    return len(_re.sub(r'[^\w\u0600-\u06FF]', '', str(w)))


def solid_cut(new, nwords, rate, a):
    """أعلى فهرس «كلمة صلبة» بين المرشّحين (طول ≥ solid-min-len · ثقة ≥ solid-min-score · اتساق معدل محلي)."""
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
    """حارس الجزر: كلمة قصيرة (≤3 أحرف) أو ضعيفة الثقة تشكّل جزيرة زمنية معزولة بين مرساتين صلبتين."""
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


def interpolate(times, words, min_score, silent_set=None):
    """استيفاء خطي بفترات متناسبة للكلمات ضعيفة الثقة/المفقودة بين جارتين موثوقتين ⇒ (الأزمنة, العلامات)."""
    n = len(words)
    silent_set = silent_set or set()
    flags = ['a' if (i in times and i not in silent_set) else '' for i in range(n)]
    for i in range(n):
        if i in silent_set:
            flags[i] = 'i'
        elif i in times and (times[i][2] is None or times[i][2] < min_score):
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
            t0 = times[nxt][0]
            times[i] = (round(t0, 2), round(t0, 2), None)
        elif nxt is None:
            t0 = times[prev][1]
            times[i] = (round(t0, 2), round(t0, 2), None)
        else:
            s0, e0 = times[prev][1], times[nxt][0]
            if e0 < s0:
                s0 = e0 = times[prev][1]
            k_interp = max(1, nxt - prev - 1)
            idx_in_gap = i - prev - 1
            w_s = s0 + (e0 - s0) * (idx_in_gap / k_interp)
            w_e = w_s if i in silent_set else (s0 + (e0 - s0) * ((idx_in_gap + 1) / k_interp))
            times[i] = (round(w_s, 2), round(max(w_s, w_e), 2), None)
        flags[i] = 'i'
    return times, flags


def compute_v1_metrics(x, v1_path):
    """حساب مؤشرات التحقق المتقاطع مع v1 (الكل + المراسي النظيفة غير المكدّسة بـ50ms)."""
    v1 = json.load(open(v1_path, encoding='utf-8'))
    rows = v1.get('x') if isinstance(v1, dict) else v1
    ref, rtxt, rsrc = [], [], []
    for r in rows:
        if isinstance(r, dict):
            ref.append(r.get('s') if isinstance(r.get('s'), (int, float)) else None)
            rtxt.append(str(r.get('w', '')))
            rsrc.append(str(r.get('src', 'a')))
        else:
            ref.append(r[1] if len(r) >= 3 and isinstance(r[1], (int, float)) else None)
            rtxt.append(str(r[0]))
            flag = r[5] if len(r) >= 6 else (r[3] if len(r) >= 4 else 'a')
            rsrc.append(str(flag))

    # كشف الكلمات التي كدّسها v1 بفارق اصطناعي +0.05s عند فجوات Whisper
    v1_stacked = set()
    for i in range(1, len(ref)):
        if ref[i] is not None and ref[i - 1] is not None:
            if abs((ref[i] - ref[i - 1]) - 0.05) < 0.015:
                v1_stacked.add(i)
                v1_stacked.add(i - 1)

    def summarize(devs, reg, ntxt):
        if not devs:
            return None
        ds = sorted(devs)
        return dict(
            n=len(devs),
            text_match=ntxt,
            text_match_pct=round(ntxt / len(devs) * 100, 1),
            median=round(st.median(devs), 2),
            p90=round(ds[int(len(ds) * 0.9)], 2),
            max=round(max(devs), 2),
            within_0_1=round(sum(1 for d in devs if d <= 0.1) / len(devs) * 100, 1),
            within_0_2=round(sum(1 for d in devs if d <= 0.2) / len(devs) * 100, 1),
            within_0_5=round(sum(1 for d in devs if d <= 0.5) / len(devs) * 100, 1),
            within_1=round(sum(1 for d in devs if d <= 1.0) / len(devs) * 100, 1),
            within_1_5=round(sum(1 for d in devs if d <= 1.5) / len(devs) * 100, 1),
            window_20_25_n=len(reg),
            window_20_25_median=round(st.median(reg), 2) if reg else None,
            window_20_25_p90=round(sorted(reg)[int(len(reg) * 0.9)], 2) if reg else None,
            window_20_25_gt1=round(sum(1 for d in reg if d > 1) / len(reg) * 100, 0) if reg else None,
            window_20_25_gt2=round(sum(1 for d in reg if d > 2) / len(reg) * 100, 0) if reg else None,
        )

    devs_all, reg_all, ntxt_all = [], [], 0
    devs_clean, reg_clean, ntxt_clean = [], [], 0
    for i, r in enumerate(x):
        if i >= len(ref) or ref[i] is None or r[1] is None:
            continue
        match = bool(rtxt[i] and rtxt[i] == r[0])
        d = abs(r[1] - ref[i])
        devs_all.append(d)
        if match:
            ntxt_all += 1
        if 1200 <= r[1] <= 1500:
            reg_all.append(d)

        if rsrc[i] == 'a' and i not in v1_stacked and r[3] == 'a':
            devs_clean.append(d)
            if match:
                ntxt_clean += 1
            if 1200 <= r[1] <= 1500:
                reg_clean.append(d)

    return summarize(devs_all, reg_all, ntxt_all), summarize(devs_clean, reg_clean, ntxt_clean), len(v1_stacked)


def align_one_file(em_path, tk_path, out_path, tag, a):
    base = em_path[:-7] if em_path.endswith('.em.npy') else os.path.splitext(em_path)[0]
    tk_path = tk_path or (base + '.tokens.json')
    meta = {}
    if os.path.exists(base + '.meta.json'):
        meta = json.load(open(base + '.meta.json', encoding='utf-8'))
    if not os.path.exists(tk_path):
        raise SystemExit('لا يوجد ملف توكنات: %s' % tk_path)
    tj = json.load(open(tk_path, encoding='utf-8'))
    words, vocab = tj['words'], {k.lower(): v for k, v in tj['vocab'].items()}
    tok = TokShim(vocab, tj.get('pad'))
    em = np.load(em_path, mmap_mode='r')
    T, C = em.shape
    stride_ms = float(meta.get('stride_ms', 20.0))
    fps = float(meta.get('fps') or (1000.0 / stride_ms))
    dur = T / fps
    N = len(words)
    if meta.get('n_words') not in (None, N):
        print('[%s] تنبيه: عدد كلمات النص (%d) ≠ المسجَّل في meta (%s)' % (tag, N, meta.get('n_words')), flush=True)

    nwords = None
    silent_set = set()
    if a.shadow_norm:
        nwords = shadow_words_1to1(words, unify=bool(a.shadow_unify))
        assert len(nwords) == N, 'التطبيع الظلّي كسر التناظر ١:١ ✗'
        silent_set = {i for i, nw in enumerate(nwords) if not nw}
        changed = sum(1 for o, n in zip(words, nwords) if o != n and n != '')
        print('[%s] تطبيع ظلّي ١:١: تغيّرت %d/%d كلمة · رموز صامتة متخطاة=%d · مثال: «%s» ⇒ «%s»' % (
            tag, changed, N, len(silent_set),
            next((o for o, n in zip(words, nwords) if o != n and n), ''),
            next((n for o, n in zip(words, nwords) if o != n and n), '')), flush=True)

    t_start = time.time()
    times, pins, forced = {}, 0, 0
    fc, wc = 0, 0
    B = None                     # إطارات فواصل الصمت الطبيعية (من مصفوفة الانبعاثات، بلا أي ASR)
    blank_id = int(tj.get('blank') if tj.get('blank') is not None else vocab.get('<blank>', 0))
    Cv = int(tj.get('vocab_size') or len(vocab))
    star_col = Cv if C > Cv else None          # عمود <star> المضاف (آخر عمود) إن وُجد
    amv_full = np.asarray(em[:, :Cv]).argmax(1) if C > Cv else np.asarray(em).argmax(1)
    ev_arr = ((amv_full != blank_id) & (amv_full != np.concatenate([[blank_id], amv_full[:-1]]))).astype(np.int32)
    cum_ev = np.cumsum(ev_arr)
    src_for_len = nwords if nwords is not None else words
    w_chars = np.array([max(1, _norm_len(w)) for w in src_for_len], dtype=np.int32)
    cum_wchars = np.cumsum(w_chars)
    if a.pause_cut:
        isb = (amv_full == blank_id).astype(np.int8)
        d = np.diff(np.concatenate([[0], isb, [0]]))
        st_b, en_b = np.flatnonzero(d == 1), np.flatnonzero(d == -1)
        B = en_b[(en_b - st_b) >= a.pause_min_frames]
        print('[%s] فواصل صمت طبيعية: %d (أدنى %d إطارًا · blank=%d)' % (tag, len(B), a.pause_min_frames, blank_id), flush=True)
    rate = N / dur if dur > 0 else 1.0                 # كلمات/ثانية تقديرية أولية
    print('[%s] انبعاثات %d إطارًا × %d صنفًا · %.0fث · %d كلمة · معدل ابتدائي %.2f كلمة/ث · star=%s · star_pen=%.2f' % (
        tag, T, C, dur, N, rate, a.star, a.star_pen), flush=True)

    while wc < N and fc < T:
        tc = fc / fps
        fi1 = min(T, fc + int(a.slice * fps))
        if B is not None and fi1 < T:                    # ① اقترب من فاصل صمت طبيعي (بلا أي ASR)
            lo_b = fc + int(0.4 * a.slice * fps)
            cand = B[(B > lo_b) & (np.abs(B - fi1) <= int(a.pause_tol * fps))]
            if len(cand):
                fi1 = int(cand[np.argmin(np.abs(cand - fi1))])
        slice_dur = max(1.0, (fi1 - fc) / fps)
        avg_rate = N / max(1.0, dur)
        ev_slice = 0
        if fi1 >= T:
            n_est = N - wc
            wi1 = N
            eff_margin = 0
        else:
            ev_before = int(cum_ev[fc - 1]) if fc > 0 else 0
            ev_slice = max(0, int(cum_ev[min(T - 1, fi1 - 1)] - ev_before))
            ev_rem = max(1, int(cum_ev[-1] - ev_before))
            ch_before = int(cum_wchars[wc - 1]) if wc > 0 else 0
            ch_rem = max(1, int(cum_wchars[-1] - ch_before))
            target_ch = ch_before + ch_rem * (max(1, ev_slice) / float(ev_rem))
            wi_ev = int(np.searchsorted(cum_wchars, target_ch, side='left')) + 1
            max_phys_words = max(a.min_words, int(round(max(3.6, avg_rate * 2.4) * slice_dur)))
            n_est = min(max_phys_words, max(a.min_words, wi_ev - wc))
            eff_margin = min(a.margin, max(4, int(round(0.06 * n_est))))
            wi1 = min(N, wc + n_est + eff_margin)
        slice_rate = n_est / slice_dur
        margin = eff_margin
        while True:                                     # تحصين: عند فشل التثبيت تُقلَّص الشريحة
            try:
                got = align_slice(em, tok, words, wc, wi1, fc, fi1, stride_ms, a.star, nwords, a.star_pen, star_col)
            except Exception as e:
                got = {}
                print('[%s]   [!] فشل شريحة %.0f–%.0fث (%s: %s)' % (tag, tc, fi1 / fps, type(e).__name__, str(e)[:80]), flush=True)
            horizon = (fi1 / fps) if fi1 >= T else (tc + a.pin)
            new = {i: v for i, v in got.items() if v[1] <= horizon and v[1] > v[0] - 0.01}
            if new or margin <= 0:
                break
            margin -= 10                                # قلّل الهامش ثم أعد المحاولة على الشريحة نفسها
            wi1 = min(N, wc + n_est + max(0, margin))
        if not new:                                     # لا تثبيت: تقدّم اضطراري لضمان التقدّم
            forced += 1
            step_f = int(a.slice * fps / 2)
            step_dur = max(1.0, step_f / fps)
            if fi1 < T and ev_slice < max(4, int(slice_dur * 0.4)):
                step_w = 0
            else:
                step_w = max(1, min(n_est // 2, int(round(avg_rate * step_dur))))
            print('[%s]   [!] شريحة %.0fث بلا تثبيت ⇒ تقدّم اضطراري %.0fث / %d كلمة' % (
                tag, tc, step_f / fps, step_w), flush=True)
            fc += step_f
            wc += step_w
            continue
        if a.solid_handoff and fi1 < T:
            cut_i = solid_cut(new, nwords if nwords is not None else words, slice_rate, a)
            if cut_i is not None and cut_i < max(new):
                dropped = sum(1 for i in new if i > cut_i)
                new = {i: v for i, v in new.items() if i <= cut_i}
                if dropped:
                    print('[%s]   ↳ تسليم صلب عند الكلمة %d (أُعيد %d كلمة للشريحة التالية)' % (tag, cut_i, dropped), flush=True)
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
            tag, tc, fi1 / fps, len(new), last_end, rate), flush=True)

    # الكلمات المتبقية في الذيل (إن وُجدت) بتوسيع الشريحة إلى أقصى ما تبقّى
    if wc < N:
        got = {}
        try:
            got = align_slice(em, tok, words, wc, N, int(fc), T, stride_ms, a.star, nwords, a.star_pen, star_col)
        except Exception as e:
            print('[%s]   [!] فشل شريحة الذيل: %s' % (tag, type(e).__name__), flush=True)
        for i, v in got.items():
            times.setdefault(i, v)
        print('[%s] ذيل: أُضيف %d كلمة من أصل %d متبقية' % (tag, len(got), N - wc), flush=True)

    wall = time.time() - t_start
    if a.island_guard and times:
        dem = island_demote(times, nwords if nwords is not None else words, rate, a)
        for i in dem:
            s, e, sc = times[i]
            times[i] = (s, e, -999.0)              # ⇒ يوسم i ويُستوفى خطيًا بين المراسي الصلبة
        if dem:
            print('[%s] حارس الجزر: %d كلمة قصيرة/معزولة ⇒ استيفاء خطي' % (tag, len(dem)), flush=True)
    times, flags = interpolate(times, words, a.min_score, silent_set=silent_set)
    x = []
    for i, w in enumerate(words):
        s, e, _ = times.get(i, (None, None, None))
        if s is None:
            x.append([w, None, None, ''])
        else:
            x.append([w, s, e, flags[i] or 'i'])
    aligned = sum(1 for r in x if r[3] == 'a')
    covered = sum(1 for r in x if r[1] is not None)
    spoken_total = max(1, N - len(silent_set))
    spoken_interp = sum(1 for idx, r in enumerate(x) if r[1] is not None and r[3] != 'a' and idx not in silent_set)
    first_s = min((r[1] for r in x if r[1] is not None), default=0.0)
    last_e = max((r[2] for r in x if r[2] is not None), default=0.0)
    audio_span_pct = round((last_e / dur) * 100.0, 2) if dur > 0 else 0.0

    # كشف كتل الكلمات المستوفاة المتصلة (≥10 كلمات منطوقة متتالية بلا محاذاة صوتية ⇒ مؤشر تكرار/حشو نصي عند حدود المقاطع)
    unaligned_clusters = []
    _cur_run = []
    for idx, r in enumerate(x):
        if idx in silent_set:
            continue
        if r[3] != 'a':
            _cur_run.append((idx, r[0], r[1]))
        else:
            if len(_cur_run) >= 10:
                unaligned_clusters.append(dict(
                    start_idx=_cur_run[0][0], end_idx=_cur_run[-1][0], count=len(_cur_run),
                    t=round(_cur_run[0][2] or 0.0, 2),
                    sample=' '.join(w for _, w, _ in _cur_run[:12])
                ))
            _cur_run = []
    if len(_cur_run) >= 10:
        unaligned_clusters.append(dict(
            start_idx=_cur_run[0][0], end_idx=_cur_run[-1][0], count=len(_cur_run),
            t=round(_cur_run[0][2] or 0.0, 2),
            sample=' '.join(w for _, w, _ in _cur_run[:12])
        ))

    report = dict(tag=tag, words=N, spoken_words=spoken_total, silent_tokens=len(silent_set),
                  aligned=aligned, interpolated=spoken_interp,
                  unaligned_clusters_count=len(unaligned_clusters),
                  unaligned_clusters=unaligned_clusters,
                  covered=covered, coverage=round(covered / N * 100, 2),
                  align_coverage=round(aligned / N * 100, 2),
                  spoken_align_coverage=round(aligned / spoken_total * 100, 2),
                  first_aligned_s=round(first_s, 2), last_aligned_s=round(last_e, 2),
                  audio_span_pct=audio_span_pct,
                  pinned=pins, forced=forced,
                  dur=round(dur, 1), frames=int(T), fps=round(fps, 3), slice=a.slice, pin=a.pin,
                  margin=a.margin, star=a.star, min_score=a.min_score, shadow_norm=bool(a.shadow_norm),
                  star_pen=a.star_pen, solid_handoff=bool(a.solid_handoff), solid_min_len=a.solid_min_len,
                  solid_min_score=a.solid_min_score, island_guard=bool(a.island_guard), pause_cut=bool(a.pause_cut),
                  align_wall_s=round(wall, 1), peak_rss_mb=round(peak_mb(), 1),
                  em_meta=meta)

    if a.v1 and os.path.exists(a.v1):
        vs_all, vs_clean, n_stacked = compute_v1_metrics(x, a.v1)
        if vs_all:
            report['vs_v1'] = vs_all
        if vs_clean:
            vs_clean['v1_stacked_excluded'] = n_stacked
            report['vs_v1_clean'] = vs_clean

    out = dict(cov=report['coverage'], start=0.0, dur=round(dur, 2), audio=meta.get('audio'),
               align_meta=dict(engine='ctc-pure', model=meta.get('model'), fps=round(fps, 3),
                               slice=a.slice, pin=a.pin, margin=a.margin, star=a.star, shadow_norm=bool(a.shadow_norm),
                               min_score=a.min_score, star_pen=a.star_pen, solid_handoff=bool(a.solid_handoff),
                               aligned=aligned, interpolated=spoken_interp,
                               silent_tokens=len(silent_set),
                               unaligned_clusters_count=len(unaligned_clusters),
                               first_aligned_s=round(first_s, 2),
                               last_aligned_s=round(last_e, 2), audio_span_pct=audio_span_pct,
                               wall_s=round(wall, 1)),
               x=x)
    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or '.', exist_ok=True)
    json.dump(out, open(out_path, 'w', encoding='utf-8'), ensure_ascii=False)
    rp = (a.report if (a.report and not a.series_out) else '') or (os.path.splitext(out_path)[0] + '.report.json')
    json.dump(report, open(rp, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('[%s] ✓ %s | تغطية %.1f%% (محاذاة مباشرة %.1f%% من المنطوق · استيفاء %d · صامت %d) | امتداد الصوت %.1f%% (%.0f–%.0fث من %.0fث) | %d كلمة مثبتة · %d تقدّم اضطراري | زمن %.1fث · ذروة %.0fMB' % (
        tag, os.path.basename(out_path), report['coverage'], report['spoken_align_coverage'],
        report['interpolated'], len(silent_set), audio_span_pct, first_s, last_e, dur, pins, forced, wall, report['peak_rss_mb']), flush=True)
    if audio_span_pct < 85.0:
        print('[%s] [!] تحذير بتر نصي: النص انتهى عند %.0fث من أصل %.0fث (%.1f%% فقط من الصوت)!' % (
            tag, last_e, dur, audio_span_pct), flush=True)
    if unaligned_clusters:
        print('[%s] [!] تحذير تكرار/حشو نصي محتمل: %d كتلة متصلة (≥6 كلمات مستوفاة بلا أثر صوتي)، أولها عند الكلمة %d (%.1fث): «%s...»' % (
            tag, len(unaligned_clusters), unaligned_clusters[0]['start_idx'], unaligned_clusters[0]['t'], unaligned_clusters[0]['sample']), flush=True)
    try:
        if 'vs_v1' in report:
            v = report['vs_v1']
            print('[%s] تحقق متقاطع مع v1 (الكل، n=%d): وسيط=%.2fث p90=%.2fث ±0.1ث=%.0f%% ±0.2ث=%.0f%% ±0.5ث=%.0f%% ±1ث=%.0f%% | النافذة ٤: وسيط=%sث p90=%sث' % (
                tag, v['n'], v['median'], v['p90'], v['within_0_1'], v['within_0_2'], v['within_0_5'], v['within_1'],
                v['window_20_25_median'], v['window_20_25_p90']), flush=True)
        if 'vs_v1_clean' in report:
            vc = report['vs_v1_clean']
            print('[%s] تحقق متقاطع مع v1 (مراسٍ حقيقية بعد استبعاد %d كلمة مكدّسة بـ50ms، n=%d): وسيط=%.2fث p90=%.2fث ±0.1ث=%.0f%% ±0.2ث=%.0f%% ±0.5ث=%.0f%% ±1ث=%.0f%% | النافذة ٤: وسيط=%sث p90=%sث' % (
                tag, vc['v1_stacked_excluded'], vc['n'], vc['median'], vc['p90'], vc['within_0_1'], vc['within_0_2'],
                vc['within_0_5'], vc['within_1'], vc['window_20_25_median'], vc['window_20_25_p90']), flush=True)
    except Exception as e:
        print('[%s] ⚠ تعذّرت طباعة التحقق المتقاطع (%s: %s) — المخرجات مكتوبة وسليمة' % (
            tag, type(e).__name__, str(e)[:120]), flush=True)
    return report


def main():
    ap = argparse.ArgumentParser(description='محاذاة CTC نقيّة من مصفوفة انبعاثات (بلا Whisper)')
    ap.add_argument('--em', help='ملف الانبعاثات .em.npy (لوضع الدرس المفرد)')
    ap.add_argument('--tokens', help='.tokens.json (افتراضي: بجوار --em)')
    ap.add_argument('--out', help='ملف align.json الناتج (لوضع الدرس المفرد)')
    ap.add_argument('--series-out', help='مجلد يحتوي على ملفات .em.npy و .tokens.json لمحاذاة السلسلة دفعةً واحدة')
    ap.add_argument('--only', help='تصفية الدروس عند استخدام --series-out (مفصولة بفواصل)')
    ap.add_argument('--tag', default='')
    ap.add_argument('--slice', type=float, default=120.0, help='طول شريحة الإطارات (ث)')
    ap.add_argument('--pin', type=float, default=65.0, help='ما يُثبّت من أول كل شريحة (ث)')
    ap.add_argument('--margin', type=int, default=30, help='هامش كلمات إضافي في ذيل الشريحة')
    ap.add_argument('--min-words', type=int, default=12, help='أدنى عدد كلمات في الشريحة')
    ap.add_argument('--star', default='segment', choices=['segment', 'edges'])
    ap.add_argument('--pause-cut', type=int, default=1, help='اقطع الشرائح عند فواصل الصمت الطبيعية')
    ap.add_argument('--pause-min-frames', type=int, default=15, help='أدنى طول صمت (إطارًا) = 0.3ث')
    ap.add_argument('--pause-tol', type=float, default=10.0, help='مدى البحث عن أقرب صمت (ث)')
    ap.add_argument('--min-score', type=float, default=-3.0, help='حدّ الثقة للاستيفاء الخطي (الافتراضي: -3.0)')
    ap.add_argument('--star-pen', type=float, default=-0.9,
                    help='عقوبة لوغاريتمية تُضاف لعمود <star> المضاف قبل الفيتربي (-0.9 = الافتراضي المُقاس)')
    ap.add_argument('--solid-handoff', type=int, default=1,
                    help='تسليم محكوم بمرساة صلبة: يقطع التثبيت عند آخر كلمة صلبة لا عند أي كلمة')
    ap.add_argument('--solid-min-len', type=int, default=4, help='أدنى طول كلمة صلبة (بعد التطبيع)')
    ap.add_argument('--solid-min-score', type=float, default=-1.0, help='أدنى ثقة لكلمة صلبة')
    ap.add_argument('--island-guard', type=int, default=0,
                    help='حارس الجزر (مطفأ افتراضيًا؛ شغّله بـ 1 للاختبار)')
    ap.add_argument('--v1', default='', help='ملف محاذاة مرجعي للتحقق المتقاطع (اختياري)')
    ap.add_argument('--shadow-unify', type=int, default=0,
                    help='توحيد الحروف (ة→ه · ى→ي) — مفيد لمطابقة ASR وضارّ لمحاذي CTC الصوتي')
    ap.add_argument('--shadow-norm', type=int, default=1,
                    help='تطبيع ظلّي ١:١ (عثماني/ألف خنجرية U+0670/تفقيط أرقام) قبل preprocess_text')
    ap.add_argument('--report', default='', help='ملف report.json (افتراضي: بجوار --out)')
    a = ap.parse_args()

    if a.series_out:
        only_set = set(x.strip() for x in a.only.split(',') if x.strip()) if a.only else None
        em_files = sorted(fn for fn in os.listdir(a.series_out) if fn.endswith('.em.npy'))
        reports = []
        for fn in em_files:
            stem = fn[:-7]
            if only_set and stem not in only_set and not any(stem.startswith(o) for o in only_set):
                continue
            em_p = os.path.join(a.series_out, fn)
            tk_p = os.path.join(a.series_out, stem + '.tokens.json')
            out_p = os.path.join(a.series_out, stem + '.align.json')
            if not os.path.exists(tk_p):
                continue
            rep = align_one_file(em_p, tk_p, out_p, stem, a)
            reports.append(rep)
        if not reports:
            raise SystemExit('لم يُعثر على ملفات .em.npy + .tokens.json في: %s' % a.series_out)
        tot_words = sum(r['words'] for r in reports)
        tot_spoken = sum(r['spoken_words'] for r in reports)
        tot_aligned = sum(r['aligned'] for r in reports)
        tot_interp = sum(r['interpolated'] for r in reports)
        tot_silent = sum(r.get('silent_tokens', 0) for r in reports)
        tot_clusters = sum(r.get('unaligned_clusters_count', 0) for r in reports)
        tot_dur = sum(r['dur'] for r in reports)
        tot_wall = sum(r['align_wall_s'] for r in reports)
        min_span = min(r['audio_span_pct'] for r in reports)
        series_rep = dict(
            lessons_count=len(reports),
            total_dur_s=round(tot_dur, 1),
            total_dur_min=round(tot_dur / 60.0, 1),
            total_words=tot_words,
            total_spoken_words=tot_spoken,
            total_silent_tokens=tot_silent,
            total_aligned=tot_aligned,
            total_interpolated=tot_interp,
            total_unaligned_clusters=tot_clusters,
            series_spoken_align_pct=round(tot_aligned / max(1, tot_spoken) * 100.0, 2),
            min_audio_span_pct=min_span,
            total_align_wall_s=round(tot_wall, 1),
            lessons=[dict(tag=r['tag'], dur_min=round(r['dur'] / 60.0, 1), words=r['words'],
                          spoken_words=r['spoken_words'], silent_tokens=r.get('silent_tokens', 0),
                          aligned=r['aligned'], interpolated=r['interpolated'],
                          unaligned_clusters_count=r.get('unaligned_clusters_count', 0),
                          spoken_align_coverage=r['spoken_align_coverage'],
                          audio_span_pct=r['audio_span_pct'], align_wall_s=r['align_wall_s'],
                          em_s=r.get('em_meta', {}).get('em_s')) for r in reports]
        )
        srp = os.path.join(a.series_out, '_series_align_report.json')
        json.dump(series_rep, open(srp, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
        print('[سلسلة] ✓ %d دروس (%.1f دقيقة · %d كلمة · %d منطوقة) | محاذاة مباشرة %.2f%% (%d مستوفى · %d صامت · %d كتلة مشبوهة) | أدنى تغطية صوت %.1f%% | زمن المحاذاة الكلي %.1fث ⇒ %s' % (
            len(reports), series_rep['total_dur_min'], tot_words, tot_spoken, series_rep['series_spoken_align_pct'],
            tot_interp, tot_silent, tot_clusters, min_span, tot_wall, srp), flush=True)
    else:
        if not (a.em and a.out):
            raise SystemExit('مرّر إما (--em و --out) لدرس مفرد أو (--series-out) لسلسلة.')
        align_one_file(a.em, a.tokens, a.out, a.tag or os.path.basename(a.out), a)


if __name__ == '__main__':
    main()

