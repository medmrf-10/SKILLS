#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sanitize_preamble.py — تطهير ملفات التفريغ (.txt) من المقدمات اللاتينية وترويسات البيانات الوصفية.

يعالج نوعين من التلوث في مطلع ملفات التفريغ قبل المحاذاة الصوتية (CTC):
  1. المقدمات اللاتينية/الإنگليزية التي قد يطبعها وكيل agy قبل النص (مثل: "I have launched...", "Viewing...").
  2. ترويسات البيانات الوصفية غير المنطوقة (مثل: "الشيخ: ...", "السلسلة: ...", "الفيديو: ...", "الدرس: ...").

يحفظ نسخة احتياطية من كل ملف معيب داخل `<series_dir>/_raw_preamble_backup/` قبل تعديله.

الاستعمال:
  python3 sanitize_preamble.py <series_dir> [<series_dir> ...] [--dry-run]
"""
import argparse
import glob
import os
import re
import shutil
import sys

AR_RE = re.compile(r'[\u0600-\u06FF]')
LATIN_RE = re.compile(r'[A-Za-z]{4,}')
METADATA_LINE_RE = re.compile(
    r'^\s*(الشيخ|السلسلة|الفيديو|الدرس|العنوان|المصدر|القناة|تاريخ)\s*[:：]',
    re.MULTILINE,
)
OPENING_CUE_RE = re.compile(
    r'(بسم\s+الله|الحمد\s+لله|إن\s+الحمد\s+لله|نحمده|أشهد\s+أن|أما\s+بعد|'
    r'السلام\s+عليكم|اللهم\s+صل|وصلى\s+الله|سبحانك\s+لا\s+علم|رب\s+اشرح)'
)


PROMPT_ECHO_RE = re.compile(
    r'(اقرأ الملف الصوتي @[^\n]*|تنبيه صارم:\s*ينتهي هذا المقطع[^\n.!]*[.!]*|'
    r'في منتصف الكلام[؛;،,]\s*توقف فور انتهاء الصوت[^\n.!]*[.!]*|'
    r'(?:أخرج|إخراج)\s+النص(?:\s+العربي)?\s+فقط\s+بلا\s+أي\s+تعليق(?:\s+أو\s+مقدمة\s+أو\s+خاتمة\.?)?|'
    r'لا\s+تلخّ?ص،?\s*ولا\s+تعيد\s+أي\s+جملة\s+مرتين(?:\s*،?\s*ولا\s+تكتب\s+حوار[اً]*\s+وهمي[اً]*\.?)?|'
    r'هذا هو المقطع\s*\(\d+\s*من\s*\d+\)\s*من المحاضرة[^\n.!]*[.!]*|'
    r'النص جاهز ومكتمل[^.\n]*\.|فلنتأكد من دقة\s*:|نستمع بدقة لكلمات الشيخ\s*:|'
    r'لتسمع النص بدقة|دعنا نستمع بدقة|دعنا نتأكد من الكلمات|'
    r'دعنا نتأكد من النص بدقة متناهية[^.\n]*\.?|'
    r'كما سمعت التسجيل بدقة متناهية[^.\n]*\.?|'
    r'دعنا نراجع بداية النص ونهايته\s*:?\s*(?:البداية\s*:)?|'
    r'معلومات إضافية حول الملف[^.\n]*\.|دعنا نتأكد من سماع النص[^:\n]*:|'
    r'وينقطع الصوت تمام[اً]+ هنا[!.]?|'
    r'كل شيء جاهز ومضبوط تمام[اً]+[.،\s]*سأقوم بإخراج النص فقط[.\s]*)'
)

RESIDUAL_PROMPT_LINE_RE = re.compile(
    r'(?:'
    r'^\s*(?:[-*•]|\d+\.)?\s*["\']?\s*(?:أخرج|إخراج|النص\s+العربي\s+فقط|الآن\s+سأقوم\s+بإخراج\s+النص\s+فقط)[^\n]{0,80}أو\s+مقدمة\s+أو\s+خاتمة[."\')]*\s*'
    r'|^\s*(?:[-*•]|\d+\.)?\s*["\']?\s*(?:ولا\s+يوجد\s+تعليق|النص\s+دقيق\s+جد[اً]+\s+وجاهز\s+للإخراج|كل\s+كلمة\s+مطابقة\s+تمام[اً]+\s+للملف\s+الصوتي)[^\n]{0,90}أو\s+مقدمة\s+أو\s+خاتمة(?:،\s*النص\s+العربي\s+فقط)?[."\')]*\s*'
    r'|^\s*(?:[-*•]|\d+\.)?\s*["\']?\s*(?:دعنا\s+نتأكد\s+من\s+النص\s+بدقة\s+متناهية|كما\s+سمعت\s+التسجيل\s+بدقة\s+متناهية|دعنا\s+نراجع\s+بداية\s+النص\s+ونهايته|البداية\s*:)[^\n]*$'
    r'|(?:\bأو\s+مقدمة\s+أو\s+خاتمة[."\')]*\s*)?(?:[-*•]|\d+\.)?\s*["\']?\s*لا\s+تلخّ?ص،?\s*ولا\s+تعيد\s+أي\s+جملة\s+مرتين(?:،?\s*ولا\s+تكتب\s+حوار[اً]*\s+وهمي[اً]*)?[."\')]*\s*(?:->\s*لا\s+نكتب\s+أي\s+كلمة\s+سوى\s+التفريغ\s+النصي\s+العربي\s+للملف\.?)?\s*'
    r'|(?:تنبيه صارم:\s*ينتهي هذا المقطع\s*)?في منتصف الكلام[؛;،,]\s*توقف فور انتهاء الصوت[^\n.!]*[.!]*\s*'
    r'|^\s*(?:[-*•]|\d+\.)?\s*["\']?\s*أو\s+مقدمة\s+أو\s+خاتمة[."\')]+\s*'
    r')'
)


def _norm_anchor(s):
    s = re.sub(r'[\u064B-\u065F\u0670\u0640]', '', s)
    s = re.sub(r'[أإآٱ]', 'ا', s)
    s = re.sub(r'[^\u0600-\u06FF\s]', ' ', s)
    return ' '.join(s.split())


DEVOTIONAL_WORDS = {
    'امين', 'آمين', 'اللهم', 'صل', 'صلي', 'صلى', 'الله', 'عليه', 'عليها', 'عليهم',
    'وسلم', 'وعلي', 'وعلى', 'اله', 'آله', 'وصحبه', 'اجمعين', 'أجمعين', 'تسليما',
    'كثيرا', 'بارك', 'وبارك', 'سبحان', 'وبحمده', 'العظيم', 'الحمد', 'لله', 'رب',
    'العالمين', 'لا', 'اله', 'إله', 'الا', 'إلا', 'والله', 'اكبر', 'أكبر', 'استغفر',
    'أستغفر', 'ولاحول', 'حول', 'ولا', 'قوه', 'قوة', 'بالله', 'العلي', 'تبارك',
    'وتعالي', 'وتعالى', 'عز', 'وجل', 'جل', 'جلاله', 'رضي', 'عنه', 'عنها', 'عنهم',
    'عنهما', 'رحمه', 'رحمهم', 'يا', 'كلا', 'بلي', 'بلى', 'نعم', 'تعالي', 'تعالى',
    'سيدنا', 'نبينا', 'محمد', 'رسول', 'النبي', 'الكريم',
}


SBV_SRT_LINE_RE = re.compile(
    r'(?m)^(?:\s*\d+\s*\n)?\s*\d+[;:]\d{2}:\d{2}(?:[:.,]\d+)?\s*(?:,|-->)\s*\d+[;:]\d{2}:\d{2}(?:[:.,]\d+)?\s*$'
)


def _norm_word_for_dedup(w):
    s = re.sub(r'[\u064B-\u065F\u0670\u0640]', '', str(w))
    s = re.sub(r'[أإآٱ]', 'ا', s)
    s = s.replace('ة', 'ه').replace('ى', 'ي')
    s = re.sub(r'[^\u0621-\u063A\u0641-\u064A0-9a-zA-Z]', '', s)
    return s.lower()


def _is_devotional_span(norm_words):
    """التحقق مما إذا كانت السلسلة النصية عبارة تعبدية أو دعائية مشروعة يكررها الشيخ قصداً."""
    cleaned = [w for w in norm_words if w]
    if not cleaned:
        return True
    if all(w in DEVOTIONAL_WORDS for w in cleaned):
        return True
    return False


def _extract_lexical_tokens(text):
    tokens = []
    for m in re.finditer(r'[\u0621-\u065F\u0670\u06400-9a-zA-Z]+', text):
        nw = _norm_word_for_dedup(m.group(0))
        if nw:
            tokens.append((m.start(), m.end(), nw))
    return tokens


def _consume_trailing_punct(text, pos):
    m = re.match(r'^[\s.،,:؛!؟?\-—–()\[\]«»"\']+', text[pos:])
    return pos + (m.end() if m else 0)


def _dedup_inline_consecutive_spans(block, min_overlap_words=4, max_span_words=45):
    """إزالة الجمل أو العبارات المكررة فوراً على التوالي داخل الفقرة الواحدة مع حفظ التكرارات التعبدية."""
    cur = block
    for _ in range(8):
        lex = _extract_lexical_tokens(cur)
        n = len(lex)
        if n < min_overlap_words * 2:
            break
        norm_list = [x[2] for x in lex]
        found = False
        max_L = min(max_span_words, n // 2)
        for L in range(max_L, min_overlap_words - 1, -1):
            for i in range(0, n - 2 * L + 1):
                if norm_list[i] != norm_list[i + L]:
                    continue
                span1 = norm_list[i:i + L]
                if span1 == norm_list[i + L:i + 2 * L] and not _is_devotional_span(span1):
                    # تأكد من عدم وجود فاصل طويل غير علامات الترقيم بين النسختين
                    between = cur[lex[i + L - 1][1]:lex[i + L][0]]
                    if len(between.strip()) <= 4:
                        cut_start = _consume_trailing_punct(cur, lex[i + L - 1][1])
                        cut_end = _consume_trailing_punct(cur, lex[i + 2 * L - 1][1])
                        cur = cur[:cut_start].rstrip() + ' ' + cur[cut_end:].lstrip()
                        found = True
                        break
            if found:
                break
        if not found:
            break
    return cur.strip()


def _dedup_two_adjacent_chunks(prev_chunk, next_chunk, min_overlap_words=4, max_window_words=55):
    """إزالة تداخل الجمل عند حدود مقطعين متتاليين (نهاية المقطع الأول مع بداية المقطع الثاني)."""
    p_txt = prev_chunk.strip()
    n_txt = next_chunk.strip()
    if not p_txt or not n_txt:
        return p_txt, n_txt

    for _ in range(4):
        p_lex = _extract_lexical_tokens(p_txt)
        n_lex = _extract_lexical_tokens(n_txt)
        if len(p_lex) < min_overlap_words or len(n_lex) < min_overlap_words:
            break
        tail_lex = p_lex[-min(len(p_lex), max_window_words):]
        head_lex = n_lex[:min(len(n_lex), max_window_words)]
        t_words = [x[2] for x in tail_lex]
        h_words = [x[2] for x in head_lex]
        t_len = len(tail_lex)
        h_len = len(head_lex)
        max_L = min(t_len, h_len)

        matched = None
        for L in range(max_L, min_overlap_words - 1, -1):
            # ابحث عن تطابق يقع في آخر 3 كلمات من نهاية المقطع الأول وأول 3 كلمات من بداية المقطع الثاني
            for t_start in range(max(0, t_len - L - 3), t_len - L + 1):
                first_w = t_words[t_start]
                t_slice = None
                for h_start in range(0, min(4, h_len - L + 1)):
                    if h_words[h_start] != first_w:
                        continue
                    if t_slice is None:
                        t_slice = t_words[t_start:t_start + L]
                        if _is_devotional_span(t_slice):
                            break
                    if t_slice == h_words[h_start:h_start + L]:
                        matched = (t_start, h_start, L)
                        break
                if matched:
                    break
            if matched:
                break

        if not matched:
            break

        t_start, h_start, L = matched
        # قص ذيل المقطع الأول إذا كان هناك 1-3 كلمات زائدة بعد التداخل المشترك
        if t_start + L < t_len:
            p_cut = _consume_trailing_punct(p_txt, tail_lex[t_start + L - 1][1])
            p_txt = p_txt[:p_cut].rstrip()
        # قص صدر المقطع الثاني حتى نهاية التداخل المشترك
        n_cut = _consume_trailing_punct(n_txt, head_lex[h_start + L - 1][1])
        n_txt = n_txt[n_cut:].lstrip()

    return p_txt, n_txt


def deduplicate_chunk_boundary_overlap(text_or_chunks, min_overlap_words=4, max_window_words=55):
    """إزالة الجمل المكررة عند حدود تقطيع الصوت (كل 12 دقيقة) مع الحفاظ الكامل على التكرارات التعبدية المشروعة.

    تقبل إما قائمة نصوص مقاطع `list[str]` أو نصاً كاملاً `str` وتعيد النص المدمج المطهّر `str`.
    """
    if isinstance(text_or_chunks, (list, tuple)):
        raw_blocks = [str(c).strip() for c in text_or_chunks if str(c).strip()]
        if not raw_blocks:
            return ''
    elif isinstance(text_or_chunks, str):
        if not text_or_chunks.strip():
            return text_or_chunks
        raw_blocks = [b.strip() for b in re.split(r'\n\s*\n', text_or_chunks) if b.strip()]
    else:
        return ''

    cleaned_blocks = []
    for blk in raw_blocks:
        blk_clean = _dedup_inline_consecutive_spans(
            blk, min_overlap_words=min_overlap_words, max_span_words=max_window_words
        )
        if not blk_clean:
            continue
        if not cleaned_blocks:
            cleaned_blocks.append(blk_clean)
            continue
        prev_b, next_b = _dedup_two_adjacent_chunks(
            cleaned_blocks[-1], blk_clean,
            min_overlap_words=min_overlap_words, max_window_words=max_window_words
        )
        cleaned_blocks[-1] = prev_b
        if next_b:
            cleaned_blocks.append(next_b)

    merged_txt = '\n\n'.join(b for b in cleaned_blocks if b)
    return deduplicate_large_repeated_blocks(merged_txt, min_block_words=24)


def deduplicate_large_repeated_blocks(text, min_block_words=24):
    """إزالة الكتل النصية الكبيرة المكررة (≥24 كلمة متطابقة في موضعين غير متجاورين) الناتجة عن إعادة تفريغ مقطع فرعي، مع دمج الفجوات القصيرة بين الكتل المكررة واستثناء الآيات القرآنية والتكرارات التعبدية."""
    if not text or not text.strip():
        return text
    cur_text = text
    anchor_len = min(10, max(6, min_block_words // 2))
    for _pass in range(6):
        tokens = _extract_lexical_tokens(cur_text)
        n = len(tokens)
        if n < min_block_words * 2:
            break
        seen = {}
        spans = []
        i = 0
        while i <= n - min_block_words:
            key = tuple(tokens[k][2] for k in range(i, i + anchor_len))
            best = None
            for j0 in seen.get(key, ()):
                if i - j0 < min_block_words:
                    continue
                L = anchor_len
                while i + L < n and j0 + L < i and tokens[i + L][2] == tokens[j0 + L][2]:
                    L += 1
                if L >= min_block_words:
                    span_words = [tokens[k][2] for k in range(i, i + L)]
                    if _is_devotional_span(span_words):
                        continue
                    raw_slice = cur_text[tokens[i][0]:tokens[i + L - 1][1]]
                    if L < 55 and ('{' in raw_slice or '}' in raw_slice or '﴿' in raw_slice or '﴾' in raw_slice):
                        continue
                    if best is None or L > best[0]:
                        best = (L, j0)
            if best:
                L, j0 = best
                spans.append([i, i + L, j0, j0 + L])
                for k in range(i, i + L):
                    if k <= n - anchor_len:
                        seen.setdefault(tuple(tokens[m][2] for m in range(k, k + anchor_len)), []).append(k)
                i += L
            else:
                seen.setdefault(key, []).append(i)
                i += 1

        if not spans:
            break

        merged = []
        for sp in spans:
            if merged and (sp[0] - merged[-1][1] <= 35) and (merged[-1][2] <= sp[2] < merged[-1][0]):
                merged[-1][1] = sp[1]
                merged[-1][3] = sp[3]
            else:
                merged.append(sp[:])

        for m_sp in merged:
            if m_sp[1] - m_sp[0] >= 100:
                lookback = max(0, m_sp[0] - 8)
                for k in range(lookback, m_sp[0]):
                    if [tokens[x][2] for x in range(k, min(n, k + 4))] == ['بسم', 'الله', 'الرحمن', 'الرحيم']:
                        m_sp[0] = k
                        break

        # نفّذ الحذف من آخر مقطع مكرر إلى أوله للحفاظ على صحة الفهارس
        for m_sp in reversed(merged):
            c_start = tokens[m_sp[0]][0]
            # إذا سبق بداية القطع علامات ترقيم ملتصقة مثل "..." احذفها أيضاً
            while c_start > 0 and cur_text[c_start - 1] in '.;,،:؛-—–…':
                c_start -= 1
            c_end = _consume_trailing_punct(cur_text, tokens[m_sp[1] - 1][1])
            head_part = cur_text[:c_start].rstrip()
            tail_part = cur_text[c_end:].lstrip()
            if head_part and tail_part:
                sep = '\n\n' if ('\n\n' in cur_text[max(0, c_start - 4):min(len(cur_text), c_end + 4)]) else ' '
                cur_text = head_part + sep + tail_part
            else:
                cur_text = head_part or tail_part
    return cur_text


def _strip_leading_ascii_remnants(s):
    """إزالة بقايا الحروف اللاتينية القصيرة (1-3 أحرف مثل now. أو ed- أو c) أو وسوم _0:/_1: في بداية النص قبل أول حرف عربي بزمن خطي O(N)."""
    m_ar = AR_RE.search(s)
    if not m_ar or m_ar.start() == 0:
        return s
    pos = m_ar.start()
    prefix = s[:pos]
    if LATIN_RE.search(prefix):
        return s
    while pos > 0 and s[pos - 1] in '«"([{﴿':
        pos -= 1
    return s[pos:]


def _is_thinking_or_preamble_leak(s):
    """تمييز ديباجات التفكير اللاتينية وصدى الموجه عن الكلمات الإنجليزية العرضية التي ينطقها الشيخ داخل فقرة عربية طويلة."""
    if PROMPT_ECHO_RE.search(s):
        return True
    lat_m = list(LATIN_RE.finditer(s))
    if not lat_m:
        return False
    end_pos = lat_m[-1].end()
    head_s = s[:end_pos]
    ar_h = len(AR_RE.findall(head_s))
    lat_h = len(re.findall(r'[A-Za-z]', head_s))
    if ar_h > 120 and lat_h < ar_h * 0.12:
        return False
    return True


def _clean_json_thought_and_brace_leaks(text, reasons):
    """إزالة مسودات التفكير المتسربة بصيغة _1:...} وأسطر الأقواس المعقوفة اليتيمة } وبقايا الحروف اللاتينية الملتصقة."""
    lines = text.splitlines()
    out_lines = []
    changed = False
    salutation_cut_re = re.compile(r'^.*?والسلام عليكم ورحم[ةه] الله(?: تعالى)? وبركاته[.}]*\s*')

    for line in lines:
        s = line.strip()
        if not s:
            out_lines.append(line)
            continue

        # (أ) أسطر تتكون فقط من أقواس إغلاق JSON يتيمة مثل } أو }} أو ]} أو ]\}
        if re.match(r'^[\s\]\\}]+$', s):
            changed = True
            continue

        # (ب) أسطر تبدأ بوسم مسودة تفكير أو متحدث مسرب مثل _1: أو _0: أو 突出_0:
        m_tag = re.match(r'^\s*(?:[\u4e00-\u9fff]+)?_[0-9]+:\s*(.*)$', s)
        if m_tag:
            rest = m_tag.group(1).strip()
            changed = True
            if not rest or re.match(r'^(?:\d+\}?|\d{2}:\d{2}:\d{2}\s*-\s*\d{2}:\d{2}:\d{2})\s*$', rest):
                continue
            words_rest = rest.split()
            if len(words_rest) >= 50:
                if rest.endswith('}'):
                    continue
                m_sal = salutation_cut_re.match(rest)
                if m_sal:
                    after_sal = rest[m_sal.end():].strip()
                    if after_sal:
                        out_lines.append(after_sal)
                    continue
            if '{' not in rest and re.search(r'[.؟!…ـ]\}+\s*$', rest):
                rest = re.sub(r'\}+\s*$', '', rest)
            out_lines.append(rest)
            continue

        # (ج) قوس إغلاق JSON يتيم ملتصق بنهاية جملة عادية (مثل "...}" أو ".}" أو "؟}" أو "ـ}") بدون قوس فتح { في نفس السطر
        if s.endswith('}') and '{' not in s and re.search(r'(?:[.؟!…ـ]\}+|\.{2,}\}+|\}\}+)\s*$', s):
            line = re.sub(r'\}+\s*$', '', line)
            changed = True

        # (د) بقايا 1-3 أحرف لاتينية ملتصقة مباشرة بكلمة عربية مثل now.يعني أو nowيعني
        if re.search(r'(?<![A-Za-z])[A-Za-z]{1,3}[.:\-_]*(?=[\u0600-\u06FF])', line):
            line = re.sub(r'(?<![A-Za-z])[A-Za-z]{1,3}[.:\-_]*(?=[\u0600-\u06FF])', '', line)
            changed = True

        # (هـ) بقايا صدى تعليمات موجه النظام العربي (مثل: أو مقدمة أو خاتمة. لا تلخّص، ولا تعيد أي جملة مرتين...)
        if RESIDUAL_PROMPT_LINE_RE.search(line):
            new_line = RESIDUAL_PROMPT_LINE_RE.sub('', line)
            new_line = RESIDUAL_PROMPT_LINE_RE.sub('', new_line).strip()
            if new_line != line.strip():
                changed = True
                if not new_line:
                    continue
                line = new_line

        out_lines.append(line)

    if changed:
        if 'LATIN_PREAMBLE' not in reasons:
            reasons.append('LATIN_PREAMBLE')
        text = '\n'.join(out_lines)
        text = re.sub(r'\n{3,}', '\n\n', text)
    return text


def _strip_single_block_thinking(block):
    """إذا احتوى المقطع على مونولوج تفكير لاتيني أو تكرار لنص الموجه ينتهي بنص عربي صافٍ (≥300 حرف)، اقتطع المونولوج بالكامل."""
    if not _is_thinking_or_preamble_leak(block):
        return block, False
    lat_matches = list(LATIN_RE.finditer(block))
    echo_matches = list(PROMPT_ECHO_RE.finditer(block))
    if not lat_matches and not echo_matches:
        return block, False
    last_end = 0
    if lat_matches:
        last_end = max(last_end, lat_matches[-1].end())
    if echo_matches:
        last_end = max(last_end, echo_matches[-1].end())
    tail = block[last_end:]
    # تخطي أي علامات ترقيم لاتينية أو بقايا 1-3 أحرف إنجليزية أو وسوم _1: بعد آخر كلمة إنجليزية
    tail = _strip_leading_ascii_remnants(tail)
    tail = re.sub(r'^[\s.:\'"`*\-—–()\[\]0-9/\\]+', '', tail)
    if len(AR_RE.findall(tail)) >= 300:
        return tail.lstrip(), True
    return block, False


def strip_preamble_and_header(text):
    """إزالة الترويسات الوصفية والمقدمات غير المنطوقة ومونولوج التفكير المتسرب وتكرارات حدود المقاطع.

    تُعيد: (cleaned_text, reasons_list)
    """
    reasons = []

    # 0. إزالة ترويسات البيانات الوصفية (الشيخ: / السلسلة: / الفيديو:) في أول 15 سطراً قبل فحص الروابط اللاتينية
    init_lines = text.splitlines()
    init_idx = 0
    while init_idx < min(len(init_lines), 15):
        s_init = init_lines[init_idx].strip()
        if not s_init:
            init_idx += 1
            continue
        if METADATA_LINE_RE.match(s_init):
            if 'METADATA_HEADER' not in reasons:
                reasons.append('METADATA_HEADER')
            init_idx += 1
            continue
        if re.match(r'^[-=_*#]{3,}$', s_init):
            init_idx += 1
            continue
        break
    if init_idx > 0:
        text = '\n'.join(init_lines[init_idx:]).lstrip()

    # إذا وجد مونولوج تفكير لاتيني أو صدى لتعليمات الموجه في أي موضع من الملف:
    if LATIN_RE.search(text) or PROMPT_ECHO_RE.search(text):
        paras = re.split(r'\n\s*\n', text)
        out_paras = []
        in_leak = False
        pos_cursor = 0
        for p in paras:
            idx_p = text.find(p, pos_cursor)
            if idx_p != -1:
                pos_cursor = idx_p + len(p)
            near_after = text[pos_cursor: pos_cursor + 2800] if idx_p != -1 else ''
            more_leak_ahead = _is_thinking_or_preamble_leak(near_after)
            has_lat = _is_thinking_or_preamble_leak(p)
            if has_lat:
                in_leak = True
                if 'LATIN_PREAMBLE' not in reasons:
                    reasons.append('LATIN_PREAMBLE')
                if not more_leak_ahead:
                    last_m = list(LATIN_RE.finditer(p)) + list(PROMPT_ECHO_RE.finditer(p))
                    if last_m:
                        end_pos = max(m.end() for m in last_m)
                        tail_p = _strip_leading_ascii_remnants(p[end_pos:])
                        tail_p = re.sub(r'^[\s.:\'"`*\-—–()\[\]0-9/\\]+', '', tail_p)
                        if len(AR_RE.findall(tail_p)) >= 15 and not _is_thinking_or_preamble_leak(tail_p):
                            tail_clean = tail_p.strip()
                            anchor_words = ' '.join(_norm_anchor(tail_clean).split()[:5])
                            if len(anchor_words) >= 10 and out_paras:
                                # إذا وُجدت مسودة سابقة لنفس المقطع تبدأ بنفس الجملة المفتتاحية ضمن آخر الفقرات، احذف المسودة المكررة
                                char_back = 0
                                cut_from = None
                                for back_i in range(len(out_paras) - 1, -1, -1):
                                    char_back += len(out_paras[back_i])
                                    if char_back > 15000:
                                        break
                                    if anchor_words in _norm_anchor(out_paras[back_i]):
                                        cut_from = back_i
                                if cut_from is not None:
                                    out_paras = out_paras[:cut_from]
                            out_paras.append(tail_clean)
                            in_leak = False
                continue
            if in_leak:
                if more_leak_ahead:
                    continue
                in_leak = False
            out_paras.append(p)
        text = '\n\n'.join(out_paras)

    # إزالة مسودات التفكير بصيغة _1:...} وأسطر } اليتيمة وبقايا الحروف اللاتينية الملتصقة
    text = _clean_json_thought_and_brace_leaks(text, reasons)

    # إزالة أسطر التوقيت الزمني لملفات الترجمة (SBV / SRT / VTT مثل 0;00:00.000,0;00:06.880)
    if SBV_SRT_LINE_RE.search(text):
        text = SBV_SRT_LINE_RE.sub('', text)
        text = re.sub(r'\n{3,}', '\n\n', text)
        if 'SUBTITLE_TIMESTAMPS' not in reasons:
            reasons.append('SUBTITLE_TIMESTAMPS')

    # إزالة الوسوم الوصفية غير المنطوقة مثل [شارة إنشادية] أو ترويسات المتحدثين غير المنطوقة مثل **السائل الثالث:**
    if re.search(r'\[شارة[^\]]*\]', text):
        text = re.sub(r'\[شارة[^\]]*\]\s*', '', text)
        if 'METADATA_HEADER' not in reasons:
            reasons.append('METADATA_HEADER')
    if re.search(r'\*\*\s*(?:السائل|السائلة|الشيخ|المقدم|المحاضر|سؤال|الجواب)[^*\n]{0,25}\*\*', text):
        text = re.sub(r'\*\*\s*(?:السائل|السائلة|الشيخ|المقدم|المحاضر|سؤال|الجواب)[^*\n]{0,25}\*\*\s*', '', text)
        if 'METADATA_HEADER' not in reasons:
            reasons.append('METADATA_HEADER')

    lines = text.splitlines()
    idx = 0

    # 1. إزالة الأسطر الفارغة أو اللاتينية أو ترويسات البيانات الوصفية في أول 15 سطرًا
    while idx < min(len(lines), 15):
        s = lines[idx].strip()
        if not s:
            idx += 1
            continue
        if METADATA_LINE_RE.match(s):
            if 'METADATA_HEADER' not in reasons:
                reasons.append('METADATA_HEADER')
            idx += 1
            continue
        ar_count = len(AR_RE.findall(s))
        lat_count = len(re.findall(r'[A-Za-z]', s))
        if lat_count > ar_count or (LATIN_RE.search(s) and ar_count < 10):
            if 'LATIN_PREAMBLE' not in reasons:
                reasons.append('LATIN_PREAMBLE')
            idx += 1
            continue
        if re.match(r'^[-=_*#]{3,}$', s):
            idx += 1
            continue
        break

    cleaned = '\n'.join(lines[idx:]).lstrip()

    # 2. إذا بقي في أول 300 حرف كلام لاتيني متصل أو بقايا 1-3 أحرف لاتينية تسبق فاتحة الدرس العربية
    head = cleaned[:300]
    if LATIN_RE.search(head):
        m = OPENING_CUE_RE.search(cleaned[:600])
        if m and m.start() > 0 and LATIN_RE.search(cleaned[:m.start()]):
            cleaned = cleaned[m.start():].lstrip()
            if 'LATIN_PREAMBLE' not in reasons:
                reasons.append('LATIN_PREAMBLE')
        else:
            m_ar = AR_RE.search(cleaned)
            if m_ar and m_ar.start() > 0:
                cleaned = cleaned[m_ar.start():].lstrip()
                if 'LATIN_PREAMBLE' not in reasons:
                    reasons.append('LATIN_PREAMBLE')
    elif re.match(r'^(?:[\u4e00-\u9fff]+|[A-Za-z]{1,3}(?![A-Za-z]))[\s.:\'"`*\-—–()\[\]0-9/\\]*', cleaned):
        new_cleaned = _strip_leading_ascii_remnants(cleaned).lstrip()
        if new_cleaned != cleaned:
            cleaned = new_cleaned
            if 'LATIN_PREAMBLE' not in reasons:
                reasons.append('LATIN_PREAMBLE')

    # 3. إزالة تداخل الجمل المكررة عند حدود المقاطع الصوتية مع حفظ التكرارات التعبدية
    if cleaned:
        deduped = deduplicate_chunk_boundary_overlap(cleaned)
        if deduped and len(deduped.split()) < len(cleaned.split()):
            cleaned = deduped
            if 'CHUNK_BOUNDARY_OVERLAP' not in reasons:
                reasons.append('CHUNK_BOUNDARY_OVERLAP')

    return (cleaned + '\n') if cleaned else '', reasons


def process_dir(series_dir, dry_run=False):
    txts = sorted(
        f for f in glob.glob(os.path.join(series_dir, '*.txt'))
        if not os.path.basename(f).startswith('_')
    )
    backup_dir = os.path.join(series_dir, '_raw_preamble_backup')
    modified = 0
    for path in txts:
        raw = open(path, encoding='utf-8', errors='replace').read()
        cleaned, reasons = strip_preamble_and_header(raw)
        if reasons and cleaned and cleaned != raw:
            modified += 1
            fname = os.path.basename(path)
            removed_chars = len(raw) - len(cleaned)
            print('[تطهير] %s | الأسباب=%s | حُذف=%d حرفًا' % (fname, ','.join(reasons), removed_chars))
            if not dry_run:
                os.makedirs(backup_dir, exist_ok=True)
                bpath = os.path.join(backup_dir, fname)
                if not os.path.exists(bpath):
                    shutil.copy2(path, bpath)
                with open(path, 'w', encoding='utf-8') as f:
                    f.write(cleaned)
                mp = path[:-4] + '.meta.json'
                if os.path.exists(mp):
                    import json
                    try:
                        md = json.load(open(mp, encoding='utf-8'))
                        if 'chars' in md:
                            md['chars'] = len(cleaned)
                            json.dump(md, open(mp, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
                    except Exception:
                        pass
    print('[ملخص التطهير] %s: عُولج %d/%d ملف' % (series_dir, modified, len(txts)))
    return modified


def main():
    ap = argparse.ArgumentParser(description='تطهير ملفات التفريغ من المقدمات اللاتينية والترويسات الوصفية')
    ap.add_argument('dirs', nargs='+', help='مجلد (أو مجلدات) السلسلة')
    ap.add_argument('--dry-run', action='store_true', help='عرض ما سيُحذف دون تعديل الملفات')
    args = ap.parse_args()
    total = 0
    for d in args.dirs:
        if not os.path.isdir(d):
            print('تحذير: المسار ليس مجلدًا: %s' % d, file=sys.stderr)
            continue
        total += process_dir(d, dry_run=args.dry_run)
    sys.exit(0)


if __name__ == '__main__':
    main()
