#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_transcripts.py — بوابة الجودة المزدوجة للتفريغات (حتمية + فحص دلالي بـ LLM).

تجمع بين طبقتين:
  الطبقة ١ (حتمية سريعة - Deterministic Gate):
    • EMPTY              : خلو الملف من الحروف العربية.
    • SHORT              : أقل من 400 حرف عربي.
    • LATIN_PREAMBLE     : تسرب سرد إنجليزي من جلسة الوكيل في بداية النص.
    • METADATA_HEADER    : وجود ترويسة وصفية غير منطوقة في أول النص (الشيخ:/السلسلة:/الفيديو:) تفسد محاذاة البداية.
    • LOW_WPM_TRUNCATED  : معدل كلمات/دقيقة منخفض جداً مقارنة بمدة الصوت (< 45 ك/د) أو أقل من الحد الأدنى للمحاضرة.
    • ABRUPT_ENDING      : انقطاع النص في آخره وسط جملة دون علامة وقف أو عبارة ختامية أو وجود وسم [ناقص].
    • REPETITION_LOOP    : تكرار هلوسي لعبارات متتالية (8-gram / 12-gram).
    • NUMBERING_MISMATCH : تعارض رقم الملف (NNN) مع رقم الدرس الصريح في العنوان (مثل قائمة مقلوبة).
    • META_MISMATCH      : اختلاف طول النص الفعلي عن المسجل في meta.json.

  الطبقة ٢ (فحص دلالي ذكي بـ LLM — عند تمرير --llm):
    يرسل عينة مهيكلة من كل درس (العنوان + المدة + الإحصاءات + مطلع النص + وسطه + خاتمته) إلى نموذج LLM عبر agy
    لاكتشاف أي عيب دلالي أو خفي لم يخطر على البال في القواعد النصية:
    • ASR_CORRUPTION     : تحريف صوتي/إملائي للمصطلحات الشرعية أو الآيات (من مخلفات Whisper الخام مثل «الجال البسط»، «أئمة السناه»).
    • SEMANTIC_CUTOFF    : انقطاع المعنى في وسط شرح مسألة دون تمام الفكرة.
    • LLM_FILLER_OR_SUM  : تلخيص أو تدخل أسلوبي من النموذج بدل التفريغ الحرفي.
    • TOPIC_MISMATCH     : عدم تطابق مضمون الدرس مع عنوانه المعلن.
    • OTHER_ANOMALY      : أي شذوذ دلالي أو بنيوي آخر يرصدُه النموذج.

الاستعمال:
  python3 check_transcripts.py /path/to/ytb/sheikh/row [--playlist-json playlist.json] [--llm] [--report out.json]
"""
import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import time

from pathlib import Path

AR_RE = re.compile(r'[\u0600-\u06FF]')
LAT_RE = re.compile(r'[A-Za-z]{4,}')
HEADER_RE = re.compile(r'^\s*(?:الشيخ|السلسلة|الفيديو|المصدر|الرابط)\s*:', re.MULTILINE)
AR_DIGITS = '٠١٢٣٤٥٦٧٨٩'
EP_NUM_RE = re.compile(
    r'(?:الدرس|الحلقة|حلقة|المجلس|مجلس|اللقاء|لقاء|الشريط)\s*[:\-]?\s*([0-9' + AR_DIGITS + r']{1,3})'
)
CLOSING_CUES = (
    'الحمد لله', 'صلى الله', 'والسلام عليكم', 'ورحمة الله', 'إلى لقاء', 'والله أعلم',
    'آمين', 'نكتفي بهذا', 'سبحانك اللهم', 'أستغفرك وأتوب إليك', 'وصلى الله', 'بارك الله فيكم'
)
TERM_PUNCT = ('.', '؟', '!', '﴾', '}', '»', ')', '…')


def ar2en(s: str) -> str:
    return ''.join(str(AR_DIGITS.index(c)) if c in AR_DIGITS else c for c in s)


def extract_title_ep(title: str):
    if not title:
        return None
    m = EP_NUM_RE.search(title)
    if not m:
        return None
    try:
        return int(ar2en(m.group(1)))
    except Exception:
        return None


def find_agy_bin() -> str:
    for cand in (
        os.environ.get('AGY_BIN', ''),
        shutil.which('agy') or '',
        str(Path.home() / '.local/bin/agy'),
        '/root/.local/bin/agy',
    ):
        if cand and os.path.exists(cand):
            return cand
    return 'agy'


def strip_header_lines(txt: str):
    lines = txt.splitlines()
    idx = 0
    while idx < min(len(lines), 6):
        ln = lines[idx].strip()
        if not ln or HEADER_RE.match(ln) or ln.startswith('http://') or ln.startswith('https://'):
            idx += 1
        else:
            break
    return '\n'.join(lines[idx:]).strip()


def duplicate_ngram_runs(words, n=10) -> int:
    if len(words) < n * 2:
        return 0
    seen = {}
    for i in range(len(words) - n + 1):
        g = ' '.join(words[i:i + n])
        seen[g] = seen.get(g, 0) + 1
    return sum(c - 1 for c in seen.values() if c > 2)


def load_durations_map(playlist_json: str) -> dict:
    """يرجع خريطة {vid: duration_sec} من ملف قائمة يوتيوب إن وُجد."""
    out = {}
    if not playlist_json or not os.path.exists(playlist_json):
        return out
    try:
        data = json.load(open(playlist_json, encoding='utf-8'))
        entries = data.get('entries', data) if isinstance(data, dict) else data
        if isinstance(entries, list):
            for e in entries:
                if isinstance(e, dict):
                    vid = e.get('id') or e.get('vid')
                    dur = e.get('duration') or e.get('dur')
                    if vid and dur:
                        out[str(vid)] = float(dur)
    except Exception:
        pass
    return out


def check_deterministic(txt_path: str, root: str, dur_map: dict, min_wpm: float, min_words_default: int):
    rel = os.path.relpath(txt_path, root) if os.path.isdir(root) else os.path.basename(txt_path)
    raw = open(txt_path, encoding='utf-8', errors='replace').read()
    mp = txt_path[:-4] + '.meta.json'
    meta = {}
    if os.path.exists(mp):
        try:
            meta = json.load(open(mp, encoding='utf-8'))
        except Exception as e:
            meta = {'_err': str(e)}

    stem = os.path.basename(txt_path)[:-4]
    parts = stem.split('_', 1)
    file_n = int(parts[0]) if parts[0].isdigit() else meta.get('n')
    vid = parts[1] if len(parts) > 1 else (meta.get('vid') or meta.get('yt') or '')
    series_meta_path = os.path.join(os.path.dirname(txt_path), '_meta.json')
    s_vid_info = {}
    if os.path.exists(series_meta_path):
        try:
            sm = json.load(open(series_meta_path, encoding='utf-8'))
            for v in sm.get('videos', []):
                if v.get('vid') == vid:
                    s_vid_info = v
                    break
        except Exception:
            pass
    title = meta.get('title') or s_vid_info.get('title') or ''
    dur_s = meta.get('duration') or meta.get('dur') or meta.get('dur_s') or s_vid_info.get('dur_s') or dur_map.get(vid)

    issues = []
    ar_chars = len(AR_RE.findall(raw))
    if ar_chars == 0:
        issues.append(('EMPTY', 'لا توجد حروف عربية في الملف'))
        return rel, issues, {'words': 0, 'ar_chars': 0, 'dur_s': dur_s, 'wpm': 0, 'title': title, 'vid': vid}

    if ar_chars < 400:
        issues.append(('SHORT', f'عدد الحروف العربية قليل جداً ({ar_chars} < 400)'))

    # فحص الترويسة غير المنطوقة
    first_lines = '\n'.join(raw.splitlines()[:5])
    if HEADER_RE.search(first_lines):
        issues.append(('METADATA_HEADER', 'يحتوي مطلع الملف على ترويسة بيانات وصفية غير منطوقة (الشيخ/السلسلة/الفيديو)'))

    body = strip_header_lines(raw)
    if LAT_RE.search(body[:250]):
        sample = body[:90].replace('\n', ' ').strip()
        issues.append(('LATIN_PREAMBLE', f'تسرب سرد لاتيني في مطلع النص: «{sample}»'))

    words = body.split()
    n_words = len(words)
    wpm = round(n_words / (dur_s / 60.0), 1) if dur_s and dur_s > 0 else None

    if dur_s and dur_s >= 180:
        if wpm < min_wpm:
            est_pct = round((wpm / 100.0) * 100, 1)
            issues.append((
                'LOW_WPM_TRUNCATED',
                f'تفريغ مبتور بشدة: {n_words} كلمة لدرس مدته {dur_s/60:.1f} دقيقة (المعدل {wpm} ك/د < {min_wpm}؛ يغطي ~{est_pct}% فقط من الدرس)'
            ))
    elif n_words < min_words_default:
        issues.append((
            'LOW_WPM_TRUNCATED',
            f'عدد كلمات منخفض بشكل مريب لمحاضرة كاملة ({n_words} كلمة < {min_words_default})'
        ))

    # فحص الخاتمة والانقطاع المفاجئ
    tail_str = body[-280:].strip() if body else ''
    if '[ناقص]' in tail_str:
        issues.append(('ABRUPT_ENDING', 'ينتهي الملف بوسم [ناقص] الصريح'))
    elif tail_str:
        ends_punct = tail_str.endswith(TERM_PUNCT)
        has_closing = any(c in tail_str for c in CLOSING_CUES)
        if not ends_punct and not has_closing:
            last_words = ' '.join(tail_str.split()[-10:])
            issues.append(('ABRUPT_ENDING', f'انقطاع مفاجئ في نهاية النص بلا علامة ترقيم أو عبارة ختام: «...{last_words}»'))

    # فحص تكرار الهلوسة
    dup10 = duplicate_ngram_runs(words, 10)
    if dup10 > max(15, n_words // 80):
        issues.append(('REPETITION_LOOP', f'تكرارات نصية متطابقة مرتفعة (10-gram repeats = {dup10})'))

    # فحص تطابق رقم الدرس مع العنوان
    ep_title = extract_title_ep(title)
    if ep_title is not None and file_n is not None and ep_title != file_n:
        issues.append((
            'NUMBERING_MISMATCH',
            f'رقم الملف ({file_n:03d}) يخالف الرقم الصريح في العنوان (الدرس {ep_title:02d}: «{title}»)'
        ))

    # فحص meta.json
    if '_err' in meta:
        issues.append(('META_MISMATCH', f'خطأ قراءة meta.json: {meta["_err"]}'))
    elif meta.get('chars') is not None and abs(int(meta['chars']) - len(raw)) > 0:
        issues.append(('META_MISMATCH', f'chars في meta ({meta["chars"]}) ≠ الطول الفعلي ({len(raw)})'))

    info = {
        'file': rel,
        'vid': vid,
        'file_n': file_n,
        'title_ep': ep_title,
        'title': title,
        'dur_s': dur_s,
        'words': n_words,
        'ar_chars': ar_chars,
        'wpm': wpm,
        'head': ' '.join(body.split()[:85]),
        'mid': ' '.join(body.split()[max(0, n_words // 2 - 40):min(n_words, n_words // 2 + 45)]),
        'tail': ' '.join(body.split()[-85:]),
    }
    return rel, issues, info


def run_llm_audit(infos: list, model: str, timeout: int = 300) -> dict:
    """يفحص الدروس دلالياً عبر LLM (باستخدام agy) لاكتشاف أخطاء ASR، البتر الدلالي، التلخيص، أو أي شذوذ خفي."""
    agy = find_agy_bin()
    items_payload = []
    for x in infos:
        item = {
            'file': x['file'],
            'title': x['title'],
            'duration_min': round(x['dur_s'] / 60.0, 1) if x['dur_s'] else None,
            'words': x['words'],
            'wpm': x['wpm'],
            'head_sample': x['head'],
            'mid_sample': x['mid'],
            'tail_sample': x['tail'],
        }
        if x.get('audio_span_pct') is not None:
            item['audio_span_pct'] = x['audio_span_pct']
        if x.get('spoken_align_pct') is not None:
            item['spoken_align_pct'] = x['spoken_align_pct']
        items_payload.append(item)

    prompt = (
        "أنت مدقق جودة صارم لتفريغات المحاضرات الشرعية والعلمية العربية. "
        "لا تستخدم أي أداة طرفية أو بحث؛ اعتمد فقط على البيانات المرفقة في هذا البرومبت. "
        "افحص كل درس في القائمة التالية واكتشف العيوب الحقيقية فقط، مع مراعاة قواعد التفريغ الحرفي لشروح المتون:\n"
        "- قاعدة ١ (اتصال المجالس في شروح المتون): في سلاسل شرح المتون (مثل مقدمات السنوسي)، من الطبيعي جداً أن يفرغ الشيخ من شرح مبحث العنوان في أثناء المجلس ثم يشرع في قراءة أو تمهيد المبحث التالي في آخر الدرس ويقف عنده بقوله «نكتفي بهذا القدر» أو «والله أعلم»، أو يستهل الدرس بقوله «توقفنا عند قوله...». هذا تسلسل علمي طبيعي وليس عيباً (لا تصنفه NUMBERING_OR_TOPIC_MISMATCH ولا SEMANTIC_TRUNCATION).\n"
        "- قاعدة ٢ (خصائص التفريغ الحرفي الشفهي): التكرار الشفهي العفوي من الشيخ لاستدراك لفظة (مثل «بجاه نبينا بجاه نبيه» أو «لصفات، لصفات المعاني») أو نقاط الوقف القصيرة «...» في أثناء الجملة المتصلة هي سمات أصيلة للتفريغ الحرفي الأمين وليست فساد ASR ولا بتراً.\n"
        "- قاعدة ٣ (البرهان الصوتي القاطع): إذا كان معدل الكلمات طبيعياً (wpm >= 70) أو كانت تغطية المحاذاة الصوتية (audio_span_pct >= 98% و spoken_align_pct >= 98%) وكان الذيل ينتهي بخاتمة درس أو دعاء ختامي تام، فالنص مكتمل يقيناً من أول ثانية إلى آخر ثانية.\n\n"
        "العيوب التي يجب رصدها بـ FAIL إن وُجدت فعلاً:\n"
        "1. ASR_CORRUPTION: تحريفات سمعية فاحشة ومفسدة للمعنى ناتجة عن نماذج Whisper قديمة (مثل: «الجال البسط» بدل «الجهل البسيط»، «أئمة السناه» بدل «أئمة السنة»، «إثبات الروط» بدل «إثبات الربط»، «صوم يوم عاشرة» بدل «عاشوراء»، «الحمد لله وبرب العالمين»).\n"
        "2. SEMANTIC_TRUNCATION: انقطاع الملف فعلياً في آخره (tail_sample) وسط جملة غير تامة وبلا أي خاتمة ولا دعاء، مع انخفاض واضح في wpm (< 45) أو audio_span_pct (< 85%).\n"
        "3. NUMBERING_OR_TOPIC_MISMATCH: تعارض صريح بين رقم الملف (مثلاً 001) ورقم الدرس في العنوان (مثلاً الدرس 09)، أو كون النص لكتاب آخر مختلف تماماً.\n"
        "4. LLM_SUMMARY_OR_NOISE: تحول النص إلى تلخيص غير حرفي بصيغة الغائب عن المحاضرة أو تسرب فقرات إنجليزية/برمجية.\n\n"
        "أخرج النتيجة بصيغة JSON فقط (بلا أي نص خارجه ولا markdown fences إن أمكن) كمصفوفة كائنات بهذا الشكل الدقيق:\n"
        "[{\"file\": \"...\", \"verdict\": \"PASS\" أو \"FAIL\", \"defects\": [], \"evidence\": \"\", \"note\": \"تشخيص مختصر\"}]\n\n"
        "بيانات الدروس للفحص:\n"
        + json.dumps(items_payload, ensure_ascii=False, indent=1)
    )

    cmd = [agy, '-p', prompt, '--output-format', 'json']
    if model:
        cmd += ['--model', model]

    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    resp_text = ''
    txt_out = (proc.stdout or '').strip()
    for line in reversed([l.strip() for l in txt_out.splitlines() if l.strip().startswith('{')]):
        try:
            payload = json.loads(line)
            resp_text = (payload.get('response') or '').strip()
            if resp_text:
                break
        except Exception:
            continue
    if not resp_text and txt_out:
        i_brace, j_brace = txt_out.find('{'), txt_out.rfind('}')
        if i_brace != -1 and j_brace > i_brace:
            try:
                payload = json.loads(txt_out[i_brace:j_brace + 1])
                resp_text = (payload.get('response') or '').strip()
            except Exception:
                pass

    if not resp_text:
        return {'_error': f'لم يرجع LLM استجابة صالحة: {proc.stdout[-300:]} {proc.stderr[-300:]}'}

    # استخراج مصفوفة JSON من رد النموذج
    m = re.search(r'\[.*\]', resp_text, re.S)
    if not m:
        return {'_error': f'تعذر استخراج JSON من رد LLM: {resp_text[:400]}'}
    try:
        arr = json.loads(m.group(0))
        return {item['file']: item for item in arr if isinstance(item, dict) and 'file' in item}
    except Exception as e:
        return {'_error': f'فشل تحليل JSON من LLM ({e}): {m.group(0)[:300]}'}


def discover_txt_files(target: str) -> list:
    if os.path.isfile(target) and target.endswith('.txt'):
        return [target]
    files = sorted(glob.glob(os.path.join(target, '*.txt')))
    if not files:
        files = sorted(glob.glob(os.path.join(target, '*', '*', '*.txt')))
    if not files:
        files = sorted(glob.glob(os.path.join(target, '**', '*.txt'), recursive=True))
    return [f for f in files if not os.path.basename(f).startswith('_')]


def sync_meta_counts(files: list) -> int:
    """مزامنة حقلي chars و words في كل من <stem>.meta.json و _meta.json مع الملفات النصية الفعلية."""
    by_dir = {}
    for f in files:
        by_dir.setdefault(os.path.dirname(f), []).append(f)
    updated = 0
    for f in files:
        mp_file = f[:-4] + '.meta.json'
        if os.path.exists(mp_file):
            try:
                raw = open(f, encoding='utf-8', errors='replace').read()
                mdata = json.load(open(mp_file, encoding='utf-8'))
                if mdata.get('chars') != len(raw):
                    mdata['chars'] = len(raw)
                    json.dump(mdata, open(mp_file, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
                    updated += 1
            except Exception:
                pass
    for d, flist in by_dir.items():
        mp = os.path.join(d, '_meta.json')
        if not os.path.exists(mp):
            continue
        try:
            meta = json.load(open(mp, encoding='utf-8'))
            changed = False
            for f in flist:
                base = os.path.splitext(os.path.basename(f))[0]
                parts = base.split('_', 1)
                n_val = int(parts[0]) if parts[0].isdigit() else None
                vid_val = parts[1] if len(parts) > 1 else ''
                raw = open(f, encoding='utf-8', errors='replace').read()
                w_cnt = len(raw.split())
                c_cnt = len(raw)
                for v in meta.get('videos', []):
                    if (vid_val and v.get('vid') == vid_val) or (n_val is not None and v.get('n') == n_val):
                        if v.get('chars') != c_cnt or v.get('words') != w_cnt:
                            v['chars'] = c_cnt
                            v['words'] = w_cnt
                            changed = True
                            updated += 1
            if changed:
                json.dump(meta, open(mp, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
        except Exception:
            pass
    return updated


def main():
    ap = argparse.ArgumentParser(description='بوابة الجودة المزدوجة (حتمية + LLM + محاذاة صوتية) لتفريغات السلاسل')
    ap.add_argument('target', nargs='?', default='/root/workspace/ytb', help='مجلد السلسلة أو المخزن أو ملف نصي')
    ap.add_argument('--playlist-json', default='', help='ملف JSON لقائمة يوتيوب لاستخراج مدد الفيديوهات الحقيقية')
    ap.add_argument('--min-wpm', type=float, default=45.0, help='الحد الأدنى لمعدل الكلمات في الدقيقة (الافتراضي: 45)')
    ap.add_argument('--min-words', type=int, default=1200, help='الحد الأدنى لكلمات المحاضرة عند غياب المدة')
    ap.add_argument('--sync-meta', action='store_true', help='مزامنة chars/words في _meta.json تلقائياً قبل الفحص')
    ap.add_argument('--align-dir', default='', help='مجلد ملفات .align.json للتحقق الصوتي المتقاطع (اختياري)')
    default_llm_workers = 4 if sys.platform == 'darwin' else 2
    ap.add_argument('--llm', action='store_true', help='تفعيل الفحص الدلالي العميق بـ LLM عبر agy')
    ap.add_argument('--llm-model', default=os.environ.get('TRANSCRIBE_MODEL', ''))
    ap.add_argument('--llm-workers', type=int, default=default_llm_workers,
                    help='توازي دفعات الفحص الدلالي (الافتراضي: 4 على الماك، 2 على الخادم)')
    ap.add_argument('--report', default='', help='حفظ تقرير JSON مفصل في هذا المسار')
    a = ap.parse_args()

    files = discover_txt_files(a.target)
    if not files:
        print(f'لم يُعثر على ملفات نصية في: {a.target}')
        return 2

    if a.sync_meta:
        n_up = sync_meta_counts(files)
        if n_up:
            print(f'تمت مزامنة إحصاءات _meta.json لـ {n_up} درساً.', flush=True)

    dur_map = load_durations_map(a.playlist_json)
    all_issues = {}
    infos = []
    by_code = {}

    for f in files:
        rel, issues, info = check_deterministic(f, a.target, dur_map, a.min_wpm, a.min_words)
        if a.align_dir:
            stem = os.path.splitext(os.path.basename(f))[0]
            ap_json = os.path.join(a.align_dir, stem + '.align.json')
            if os.path.exists(ap_json):
                try:
                    ad = json.load(open(ap_json, encoding='utf-8'))
                    am = ad.get('align_meta', {})
                    span_pct = float(am.get('audio_span_pct', 100.0))
                    n_clust = int(am.get('unaligned_clusters_count', 0))
                    info['audio_span_pct'] = span_pct
                    info['spoken_align_pct'] = round(
                        100.0 * int(am.get('aligned', 0)) / max(1, int(am.get('aligned', 0)) + int(am.get('interpolated', 0))), 2
                    )
                    if span_pct < 85.0:
                        issues.append(('ACOUSTIC_TRUNCATION', f'امتداد النص على الصوت {span_pct:.1f}% فقط (< 85%)'))
                    if n_clust > 0:
                        issues.append(('ACOUSTIC_CLUSTER_HALLUCINATION', f'كُشفت {n_clust} كتلة كلمات متصلة مستوفاة بلا أثر صوتي (حشو أو تكرار محتمل)'))
                except Exception:
                    pass
        infos.append(info)
        if issues:
            all_issues[rel] = issues
            for code, msg in issues:
                by_code.setdefault(code, []).append(f'{rel} :: {msg}')

    llm_results = {}
    if a.llm and infos:
        print(f'تشغيل الفحص الدلالي بـ LLM ({a.llm_model}) على {len(infos)} ملفاً (توازي={a.llm_workers})...', flush=True)
        t0 = time.time()
        batches = [infos[i:i + 9] for i in range(0, len(infos), 9)]
        if len(batches) == 1 or a.llm_workers <= 1:
            batch_outputs = [run_llm_audit(b, a.llm_model) for b in batches]
        else:
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=min(a.llm_workers, len(batches))) as ex:
                batch_outputs = list(ex.map(lambda b: run_llm_audit(b, a.llm_model), batches))
        for batch_res in batch_outputs:
            if '_error' in batch_res:
                print('  [!] تنبيه LLM:', batch_res['_error'], flush=True)
            else:
                llm_results.update(batch_res)
        print(f'اكتمل الفحص الدلالي بـ LLM في {time.time() - t0:.1f}ث', flush=True)
        for rel, res in llm_results.items():
            if str(res.get('verdict', '')).upper() == 'FAIL':
                defects = res.get('defects') or ['LLM_FLAGGED']
                ev = res.get('evidence') or ''
                note = res.get('note') or ''
                for d in defects:
                    code = f'LLM_{d}' if not str(d).startswith('LLM_') else str(d)
                    msg = f'{note} (الشاهد: «{ev}»)' if ev else note
                    all_issues.setdefault(rel, []).append((code, msg))
                    by_code.setdefault(code, []).append(f'{rel} :: {msg}')

    print(f'تم فحص {len(files)} ملفاً تحت {a.target}')
    for code, items in sorted(by_code.items()):
        print(f'  [{code}]: {len(items)}')
        for it in items[:10]:
            print(f'     - {it}')
        if len(items) > 10:
            print(f'     ... +{len(items) - 10} أخرى')

    failed_files = len(all_issues)
    passed_files = len(files) - failed_files
    print(f'النتيجة: {"CLEAN (صفر أخطاء)" if failed_files == 0 else f"FAILED ({failed_files}/{len(files)} ملفات معيبة، {passed_files} سليمة)"}')

    if a.report:
        rep = {
            'target': a.target,
            'total_files': len(files),
            'passed_files': passed_files,
            'failed_files': failed_files,
            'issues_by_file': {k: [{'code': c, 'message': m} for c, m in v] for k, v in all_issues.items()},
            'llm_audit': llm_results,
            'file_stats': [{k: v for k, v in x.items() if k not in ('head', 'mid', 'tail')} for x in infos],
        }
        os.makedirs(os.path.dirname(os.path.abspath(a.report)) or '.', exist_ok=True)
        json.dump(rep, open(a.report, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
        print(f'كُتب التقرير المفصل في: {a.report}')

    return 1 if failed_files > 0 else 0


if __name__ == '__main__':
    sys.exit(main())
