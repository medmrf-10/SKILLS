#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gen_asr_cache.py — توليد كاش كلمات ASR **محليًا** على هذا الخادم وحده
(faster-whisper على المعالج، `int8`) دون أي مضيف خارجي ولا MLX ولا SSH.

يُنتج نفس بنية كاش MLX المعتمدة في الخط:
    [{"t": الكلمة كما نُطقت, "n": صيغة مخففة التطبيع, "s": بداية, "e": نهاية, "seg": رقم المقطع}, ...]

الاستخدام:
    python3 gen_asr_cache.py --audio lesson.wav --cache out.mlx.json --prompt-from-txt lesson.txt
    python3 gen_asr_cache.py --audio lesson.wav --print-key          # طباعة الاسم القياسي للكاش

متغيرات البيئة: ASR_MODEL · ASR_COMPUTE_TYPE · ASR_DEVICE · ASR_INITIAL_PROMPT · ALIGN_CACHE_DIR
"""
import argparse
import hashlib
import json
import os
import re
import sys
import time

DEFAULT_PROMPT_HEAD = 80  # عدد كلمات المقدّمة التي تُستخدم كبرومبت (مطابق لسلوك الكاش الأصلي)

PUNCT = re.compile(r'[\u060C\u061B\u061F.,!?()\[\]{}«»"\'`:;…\-–—_0-9\u0660-\u0669]')


def light_norm(t: str) -> str:
    """التطبيع المخفف المستخدم في كاش المرجع: حذف الترقيم + توحيد الهمزات والتاء/الياء."""
    s = PUNCT.sub('', t.strip())
    s = re.sub(r'[أإآٱ]', 'ا', s)
    s = s.replace('ة', 'ه').replace('ى', 'ي').replace('ؤ', 'و').replace('ئ', 'ي')
    return s


def prompt_from_txt(path: str, head: int = DEFAULT_PROMPT_HEAD) -> str:
    try:
        txt = open(path, encoding='utf-8', errors='replace').read()
    except OSError:
        return ''
    words = txt.split()
    return ' '.join(words[:head])


def cache_key(audio: str, model: str, prompt: str) -> str:
    """الاسم القياسي للكاش: sha1(الصوت|النموذج|رأس البرومبت) — نفس اصطلاح prob_caches."""
    return hashlib.sha1((audio + '|' + model + '|' + prompt).encode()).hexdigest() + '.mlx.json'


def peak_mem_mb() -> int:
    try:
        for line in open('/proc/self/status', encoding='utf-8'):
            if line.startswith('VmHWM:'):
                return int(line.split()[1]) // 1024
    except OSError:
        pass
    return -1


def main() -> int:
    ap = argparse.ArgumentParser(description='توليد كاش ASR محلي (faster-whisper int8 على المعالج)')
    ap.add_argument('--audio', required=True)
    ap.add_argument('--cache', default='', help='مسار ملف الكاش؛ إن غاب يُشتق بالاسم القياسي في ALIGN_CACHE_DIR')
    ap.add_argument('--prompt-from-txt', default='', help='ملف نص الدرس: تُؤخذ أول 80 كلمة كبرومبت (يحسّن تمييز صيغ القرآن)')
    ap.add_argument('--print-key', action='store_true', help='اطبع الاسم القياسي للكاش واخرج')
    ap.add_argument('--model', default=os.environ.get('ASR_MODEL', 'Systran/faster-whisper-small'))
    ap.add_argument('--compute-type', default=os.environ.get('ASR_COMPUTE_TYPE', 'int8'))
    ap.add_argument('--device', default=os.environ.get('ASR_DEVICE', 'cpu'))
    ap.add_argument('--language', default=os.environ.get('ASR_LANG', 'ar'))
    ap.add_argument('--initial-prompt', default=os.environ.get('ASR_INITIAL_PROMPT',
                     'تلاوة قرآنية مرتلة وتعليق الشيخ عليها بالعربية.'))
    ap.add_argument('--beam', type=int, default=int(os.environ.get('ASR_BEAM', '5')))
    ap.add_argument('--threads', type=int, default=int(os.environ.get('ASR_THREADS', '0')))
    ap.add_argument('--vad', action='store_true', help='تشغيل مرشّح VAD (افتراضيًا مُطفأ كي لا تُفقد كلمات هادئة)')
    ap.add_argument('--offset', type=float, default=0.0, help='إزاحة تُضاف إلى كل الأزمنة (لاختبار مقاطع)')
    ap.add_argument('--meta', default='', help='ملف meta؛ افتراضيًا بجوار الكاش بـ.meta.json')
    a = ap.parse_args()

    prompt = a.initial_prompt
    if a.prompt_from_txt:
        head = prompt_from_txt(a.prompt_from_txt)
        if head:
            prompt = head

    out = a.cache
    if not out:
        cdir = os.environ.get('ALIGN_CACHE_DIR', os.path.expanduser('~/.cache/hawshat/wwords'))
        out = os.path.join(cdir, cache_key(os.path.basename(a.audio), a.model, prompt))
    if a.print_key:
        print(out)
        return 0

    os.makedirs(os.path.dirname(os.path.abspath(out)) or '.', exist_ok=True)
    from faster_whisper import WhisperModel  # يُستورد هنا ليعمل --print-key بلا مكتبات ثقيلة

    t0 = time.time()
    kw = {}
    if a.threads:
        kw['cpu_threads'] = a.threads
    model = WhisperModel(a.model, device=a.device, compute_type=a.compute_type, **kw)
    t_load = time.time() - t0

    t1 = time.time()
    segments, info = model.transcribe(
        a.audio, language=a.language, task='transcribe', beam_size=a.beam,
        word_timestamps=True, initial_prompt=prompt or None,
        condition_on_previous_text=False, vad_filter=a.vad,
    )
    words = []
    for si, seg in enumerate(segments):
        for w in (seg.words or []):
            tok = (w.word or '').strip()
            if not tok:
                continue
            words.append({
                't': tok,
                'n': light_norm(tok),
                's': round(float(w.start) + a.offset, 2),
                'e': round(float(w.end) + a.offset, 2),
                'seg': si,
            })
    t_tr = time.time() - t1

    dur = float(getattr(info, 'duration', 0.0) or 0.0)
    tmp = out + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(words, fh, ensure_ascii=False)
    os.replace(tmp, out)

    meta = {'model': a.model, 'compute_type': a.compute_type, 'device': a.device,
            'prompt_words': len(prompt.split()), 'audio': a.audio, 'words': len(words),
            'duration': round(dur, 1), 'rtf': round(t_tr / dur, 3) if dur else None,
            'engine': 'faster-whisper (محلي على المعالج)'}
    with open(a.meta or (out + '.meta.json'), 'w', encoding='utf-8') as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=1)

    print(f'✓ كاش ASR: {out}')
    print(f'  كلمات: {len(words)} · مدة الصوت: {dur:.1f}ث · تحميل النموذج: {t_load:.1f}ث · تسميع: {t_tr:.1f}ث · RTF: {meta["rtf"]}')
    print(f'  ذروة الذاكرة: {peak_mem_mb()}MB · النموذج: {a.model} ({a.compute_type}/{a.device})')
    return 0


if __name__ == '__main__':
    sys.exit(main())


# ⚠ مهجور (2026-10-15): لا تستعمله في المسار الأساسي.
# تفريغ Whisper ASR الكامل لكاش الكلمات مرفوض (40–45 دقيقة للدرس على معالج الـVPS).
# البديل المعتمد: المسار النقي (extract_emissions.py + ctc_pure_align.py) بلا أي ASR ولا كاش كلمات.
# البديل الاحتياطي الموثّق (إن احتجت مراسي نصية لدروس جديدة): «إرساء صوتي متناثر» = silero-vad على الدرس كله (~8ث)
#   ثم اقتطاع 4ث قبل كل فاصل صمت كل ~65ث (≈6% من الصوت) ودمج كل 6 نوافذ في شريحة ~26ث، وتفريغها بـfaster-whisper
#   (base/small · int8 · beam_size=1 · cpu_threads=4) في 10–22ث، ثم محاذاة Gotoh/edlib (mode="HW") — تفاصيل في references/03.
