#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_pipeline_v5_gates.py — بوابة الفحص الحتمية لمعمارية الإصدار الخامس (v5.0 Hybrid VPS + Mac MPS).

تختبر فعلياً وحتمياً:
  - Gate 1 (Syntax & Component Integrity):
      سلامة شجرة AST ووجود جميع الدوال والثوابت المحورية في:
      agy_transcribe.py, vps_align_feeder.py, mac_align_fleet.py,
      transcribe_selected_smallest_first.py, extract_emissions.py, ctc_pure_align.py,
      ووجود المرجع الهندسي references/11-hybrid-vps-mac-mps-v5.md وترقية SKILL.md.
  - Gate 2 (Silence Compaction & Unpadding Math + Preamble Sanitizer):
      اختبار رياضي فعلي لدوال plan_silence و compact_wave و unpad_emissions على موجة صوتية
      اصطناعية فيها فجوات صمت طويلة والتأكد من تطابق أبعاد الانبعاثات المسترجعة (T_orig)
      وحفظ التوقيت بالملي ثانية، مع اختبار strip_preamble_and_header على نصوص ملوثة.
  - Gate 3 (Quota Guard & Real .align.json Schema Validation):
      اختبار _is_quota_safe_for_background على حالات الكوتة الحرجة (5h < 15%، أسبوعي <= 25% مع >12h)،
      ومحاكاة محاذاة CTC نقية كاملة (align_one_file) والتحقق من مخطط .align.json.
"""
import argparse
import ast
import glob
import json
import os
import shutil
import sys
import tempfile
import time

# إذا شُغّل السكربت عبر python3 العام على الماك ولم تكن حزم المحاذاة محمّلة فيه، انتقل تلقائياً لبيئة ctc
_CTC_VENV_PY = '/Users/macm1pro/venvs/ctc/bin/python'
if os.path.exists(_CTC_VENV_PY) and os.environ.get('_V5_GATE_REEXEC') != '1':
    try:
        import numpy  # noqa: F401
        import soundfile  # noqa: F401
        import torch  # noqa: F401
        import ctc_forced_aligner  # noqa: F401
    except ImportError:
        env = dict(os.environ)
        env['_V5_GATE_REEXEC'] = '1'
        os.execve(_CTC_VENV_PY, [_CTC_VENV_PY, __file__] + sys.argv[1:], env)

import numpy as np  # noqa: E402

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_ROOT = os.path.dirname(SCRIPT_DIR)
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)


def _collect_ast_symbols(py_path):
    src = open(py_path, encoding='utf-8').read()
    tree = ast.parse(src, filename=py_path)
    funcs = {}
    assigns = set()
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            funcs[node.name] = [a.arg for a in node.args.args]
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    assigns.add(t.id)
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                imports.add(alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name)
    return src, funcs, assigns, imports


def run_gate_1_syntax_and_integrity(errors):
    print('=== [Gate 1] Syntax & Component Integrity ===')
    required_scripts = [
        'agy_transcribe.py',
        'vps_align_feeder.py',
        'mac_align_fleet.py',
        'transcribe_selected_smallest_first.py',
        'extract_emissions.py',
        'ctc_pure_align.py',
        'sanitize_preamble.py',
    ]
    parsed = {}
    for sname in required_scripts:
        spath = os.path.join(SCRIPT_DIR, sname)
        if not os.path.exists(spath):
            errors.append(f'Gate 1: السكربت مفقود: {spath}')
            continue
        try:
            parsed[sname] = _collect_ast_symbols(spath)
            print(f'  ✓ AST سليم: scripts/{sname}')
        except SyntaxError as e:
            errors.append(f'Gate 1: خطأ بناء AST في {sname}: {e}')

    # 1) فحص agy_transcribe.py
    if 'agy_transcribe.py' in parsed:
        src, funcs, _, _ = parsed['agy_transcribe.py']
        if 'download_lesson_audio' not in funcs:
            errors.append('Gate 1: الدالة download_lesson_audio مفقودة في agy_transcribe.py')
        elif 'direct_url' not in funcs['download_lesson_audio']:
            errors.append('Gate 1: المعامل direct_url مفقود في download_lesson_audio داخل agy_transcribe.py')
        if '_is_quota_safe_for_background' not in funcs:
            errors.append('Gate 1: الدالة _is_quota_safe_for_background مفقودة في agy_transcribe.py')
        if '_is_dead_silent_chunk' not in funcs:
            errors.append('Gate 1: الدالة _is_dead_silent_chunk مفقودة في agy_transcribe.py')
        if 'deduplicate_chunk_boundary_overlap' not in funcs:
            errors.append('Gate 1: الدالة deduplicate_chunk_boundary_overlap مفقودة في agy_transcribe.py')
        for token in ('archive.org/', 'libopus', '12k', 'voip', '.job.json', '[language^=ar]'):
            if token not in src:
                errors.append(f'Gate 1: المكوّن {token} مفقود في agy_transcribe.py')

    # 1b) فحص sanitize_preamble.py
    if 'sanitize_preamble.py' in parsed:
        src, funcs, _, _ = parsed['sanitize_preamble.py']
        for fn in ('strip_preamble_and_header', 'deduplicate_chunk_boundary_overlap'):
            if fn not in funcs:
                errors.append(f'Gate 1: الدالة {fn} مفقودة في sanitize_preamble.py')

    # 2) فحص vps_align_feeder.py
    if 'vps_align_feeder.py' in parsed:
        src, funcs, _, _ = parsed['vps_align_feeder.py']
        for fn in ('index_ytb_txt_and_align', 'build_ordered_lessons', 'cleanup_completed_in_bridge', 'prepare_one_opus'):
            if fn not in funcs:
                errors.append(f'Gate 1: الدالة {fn} مفقودة في vps_align_feeder.py')
        if '[language^=ar]' not in src:
            errors.append('Gate 1: تفضيل المسار العربي [language^=ar] مفقود في vps_align_feeder.py')

    # 3) فحص mac_align_fleet.py
    if 'mac_align_fleet.py' in parsed:
        src, funcs, assigns, imports = parsed['mac_align_fleet.py']
        for fn in ('quota_sync_worker', 'prefetch_worker', 'upload_and_finalize', 'diagnose_low_coverage', '_ensure_ssh_master'):
            if fn not in funcs:
                errors.append(f'Gate 1: الدالة {fn} مفقودة في mac_align_fleet.py')
        for imp in ('plan_silence', 'compact_wave', 'unpad_emissions', 'apply_local_agc'):
            if imp not in imports and imp not in funcs:
                errors.append(f'Gate 1: الدالة {imp} غير مستوردة في mac_align_fleet.py')
        for tok in (
            'MAC_ALIGN_BATCH_SIZE', 'MAC_ALIGN_PREFETCH', 'MAC_ALIGN_COOLDOWN_S',
            'MIN_ACCEPTABLE_ALIGN_PCT', 'retried_without_silence_compact',
            'empty_cache', 'gc.collect', 'ControlMaster=no', 'sys.stdin.buffer.read()',
        ):
            if tok not in src:
                errors.append(f'Gate 1: إعداد الحارس/تخفيف الحمل {tok} مفقود في mac_align_fleet.py')

    # 4) فحص transcribe_selected_smallest_first.py
    if 'transcribe_selected_smallest_first.py' in parsed:
        src, funcs, _, _ = parsed['transcribe_selected_smallest_first.py']
        for fn in ('get_mem_available_mb', 'wait_for_safe_ram', 'index_existing_ytb', 'ensure_series_meta'):
            if fn not in funcs:
                errors.append(f'Gate 1: الدالة {fn} مفقودة في transcribe_selected_smallest_first.py')

    # 4b) فحص ctc_pure_align.py (حارس القفز المبكر على النفس ALIGN-ONSET-BREATH-JUMP)
    if 'ctc_pure_align.py' in parsed:
        src, funcs, _, _ = parsed['ctc_pure_align.py']
        for fn in ('tighten_word_onsets_against_breath_and_blank', 'align_slice', 'interpolate'):
            if fn not in funcs:
                errors.append(f'Gate 1: الدالة {fn} مفقودة في ctc_pure_align.py')

    # 5) فحص المراجع (01 إلى 11) و SKILL.md
    ref11 = os.path.join(SKILL_ROOT, 'references', '11-hybrid-vps-mac-mps-v5.md')
    if not os.path.exists(ref11) or os.path.getsize(ref11) < 1000:
        errors.append('Gate 1: المرجع references/11-hybrid-vps-mac-mps-v5.md مفقود أو غير مكتمل')
    else:
        r11_txt = open(ref11, encoding='utf-8').read()
        for req_tok in ('MIN_ACCEPTABLE_ALIGN_PCT', 'diagnose_low_coverage', 'abs_db'):
            if req_tok not in r11_txt:
                errors.append(f'Gate 1: توثيق {req_tok} مفقود في references/11-hybrid-vps-mac-mps-v5.md')
        print('  ✓ المرجع الهندسي موجود ومكتمل (بما فيه حارس <95%): references/11-hybrid-vps-mac-mps-v5.md')

    skill_md = os.path.join(SKILL_ROOT, 'SKILL.md')
    if not os.path.exists(skill_md):
        errors.append('Gate 1: الملف SKILL.md مفقود')
    else:
        s_txt = open(skill_md, encoding='utf-8').read()
        for req_ref in (
            '01-intake-and-registry.md',
            '02-transcription-pluggable.md',
            '03-alignment-pure-ctc.md',
            '04-publish-and-layers.md',
            '05-hardware-and-execution-profiles.md',
            '06-pitfalls-catalogue.md',
            '07-ops-and-guards.md',
            '08-measured-baselines.md',
            '09-v2-upgrade-spec.md',
            '10-emissions-engine-onnx.md',
            '11-hybrid-vps-mac-mps-v5.md',
        ):
            if req_ref not in s_txt:
                errors.append(f'Gate 1: المرجع {req_ref} غير مذكور في SKILL.md')
        print('  ✓ SKILL.md محدّث للإصدار v5.0 ويحافظ على جميع المراجع (01–11)')


def run_gate_2_silence_math_and_sanitizer(errors):
    print('=== [Gate 2] Silence Compaction & Unpadding Math + Preamble Sanitizer ===')
    from extract_emissions import apply_local_agc, compact_wave, plan_silence, unpad_emissions
    from sanitize_preamble import strip_preamble_and_header

    # 1) إنشاء موجة صوتية اصطناعية بطول 30 ثانية (480,000 عينة عند 16kHz = 1,500 إطار بطول 20ms)
    #    فجوات صمت واقعية بطول 2.0 ثانية ضمن نافذة الوسيط المتحرك (win_s=5.0s):
    #    الصمت في: [4..6s], [11..13s], [18..20s], [25..27s] (4 فجوات × 2ث = 8ث صمت)
    sr = 16000
    frame_samples = 320
    dur_s = 30.0
    total_samples = int(dur_s * sr)
    n_orig_frames = total_samples // frame_samples  # 1500 frames

    t = np.arange(total_samples, dtype=np.float32) / sr
    wave = (0.25 * np.sin(2.0 * np.pi * 220.0 * t) + 0.15 * np.sin(2.0 * np.pi * 440.0 * t)).astype(np.float32)
    silence_Windows = ((4.0, 6.0), (11.0, 13.0), (18.0, 20.0), (25.0, 27.0))
    for s_sec, e_sec in silence_Windows:
        wave[int(s_sec * sr):int(e_sec * sr)] = 1e-5

    keep_mask, sc_stats = plan_silence(wave, sr, min_sil=0.5, keep=0.15, frame=frame_samples, rel_db=5.0, win_s=5.0)
    if keep_mask is None:
        errors.append('Gate 2: أعادت plan_silence قيمة None على موجة تحوي فجوات صمت')
        return
    if sc_stats.get('frames_total') != n_orig_frames:
        errors.append(f'Gate 2: إجمالي الإطارات ({sc_stats.get("frames_total")}) != المتوقع ({n_orig_frames})')
    if sc_stats.get('gaps') != 4:
        errors.append(f'Gate 2: عدد فجوات الصمت المرصودة ({sc_stats.get("gaps")}) != 4')
    if sc_stats.get('pct', 0.0) < 18.0:
        errors.append(f'Gate 2: نسبة الصمت المطوي ({sc_stats.get("pct")}%) أقل من المتوقع (>18%)')

    comp_wave, idx_map = compact_wave(wave, keep_mask, frame=frame_samples)
    if len(comp_wave) != len(idx_map) * frame_samples:
        errors.append(f'Gate 2: طول الموجة المضغوطة ({len(comp_wave)}) لا يطابق idx_map*320 ({len(idx_map)*frame_samples})')

    # إنشاء مصفوفة انبعاثات مضغوطة تحفظ البصمة الزمنية الأصلية لكل إطار بالملي ثانية
    n_kept = len(idx_map)
    n_classes = 32
    em_compact = np.full((n_kept, n_classes), -5.0, dtype=np.float32)
    # نضع في العمود 1 التوقيت الأصلي بالملي ثانية (f_orig * 20.0) للتحقق من عدم حدوث أي إزاحة زمنية بعد إعادة النفخ
    em_compact[:, 1] = idx_map.astype(np.float32) * 20.0

    em_unpadded, deficit = unpad_emissions(em_compact, idx_map, n_orig_frames, blank_fill=-10.0, star_col=31)
    if em_unpadded.shape != (n_orig_frames, n_classes):
        errors.append(f'Gate 2: أبعاد المصفوفة المسترجعة {em_unpadded.shape} != {(n_orig_frames, n_classes)}')
    if deficit != 0:
        errors.append(f'Gate 2: deficit={deficit} != 0')

    # التحقق من أن كل إطار محتفظ به عاد إلى موضعه الزمني الأصلي بالمللي ثانية دون أي انزياح
    restored_ms = em_unpadded[idx_map, 1]
    expected_ms = idx_map.astype(np.float32) * 20.0
    if not np.allclose(restored_ms, expected_ms, atol=1e-4):
        errors.append('Gate 2: انزياح في توقيت الإطارات المسترجعة بعد unpad_emissions!')

    # التحقق من أن إطارات الصمت المحذوفة مُلئت كإطارات صمت صريحة (blank=0.0, star=0.0, other=-10.0)
    removed_mask = ~keep_mask
    if not np.allclose(em_unpadded[removed_mask, 0], 0.0):
        errors.append('Gate 2: عمود <blank> في الإطارات المطوية لا يساوي 0.0')
    if not np.allclose(em_unpadded[removed_mask, 31], 0.0):
        errors.append('Gate 2: عمود <star> في الإطارات المطوية لا يساوي 0.0')
    if not np.allclose(em_unpadded[removed_mask, 2], -10.0):
        errors.append('Gate 2: أعمدة الحروف في الإطارات المطوية لا تساوي blank_fill (-10.0)')

    print(
        f'  ✓ طيّ الصمت وإعادة النفخ سليم رياضياً: T_orig={n_orig_frames} إطاراً (30.0s) '
        f'-> طُوي إلى {n_kept} إطاراً (حُذف {sc_stats["removed_s"]}s = {sc_stats["pct"]}% في {sc_stats["gaps"]} فجوات) '
        f'-> استُرجع إلى {em_unpadded.shape} بانزياح 0.00ms'
    )

    # 1b) اختبار أرضية الصمت المطلقة (abs_db=-55.0) على ذيل صامت طويل (أكبر من نافذة الوسيط win_s)
    tail_wave = np.concatenate([wave[:int(10.0 * sr)], np.full(int(20.0 * sr), 1e-5, dtype=np.float32)])
    tail_mask, tail_stats = plan_silence(tail_wave, sr, min_sil=0.65, keep=0.20, frame=frame_samples, rel_db=9.5, win_s=8.0, abs_db=-55.0)
    tail_silent_kept_pct = float(tail_mask[510:].mean() * 100.0)
    if tail_silent_kept_pct > 2.0:
        errors.append(f'Gate 2: فشل طي الذيل الصامت الطويل (بقيت {tail_silent_kept_pct:.2f}% من الإطارات الصامتة)')
    else:
        print(f'  ✓ أرضية الصمت المطلقة (abs_db=-55.0) تطوي الذيل الصامت الطويل بنجاح (أزالت {100.0 - tail_silent_kept_pct:.1f}% من الصمت الممتد)')

    # 1c) اختبار Two-Way Local AGC لرفع صوت السائل البعيد (-42dB) بجوار صوت الشيخ القريب (-18dB) دون تضخيم الصمت (-80dB)
    agc_test_wave = np.zeros(int(6.0 * sr), dtype=np.float32)
    t_seg = np.arange(int(2.0 * sr), dtype=np.float32) / sr
    agc_test_wave[:int(2.0 * sr)] = 0.18 * np.sin(2.0 * np.pi * 220.0 * t_seg)          # شيخ قريب (-18dB)
    agc_test_wave[int(2.0 * sr):int(4.0 * sr)] = 0.008 * np.sin(2.0 * np.pi * 300.0 * t_seg)  # سائل بعيد (-42dB)
    agc_test_wave[int(4.0 * sr):] = 1e-5                                                 # صمت محض (-100dB)
    agc_out = apply_local_agc(agc_test_wave, sr=sr)
    rms_sheikh = float(np.sqrt(np.mean(agc_out[int(0.3 * sr):int(1.7 * sr)] ** 2)))
    rms_student = float(np.sqrt(np.mean(agc_out[int(2.3 * sr):int(3.7 * sr)] ** 2)))
    rms_silence = float(np.sqrt(np.mean(agc_out[int(4.3 * sr):int(5.7 * sr)] ** 2)))
    ratio_sp = rms_student / max(1e-6, rms_sheikh)
    if not (0.75 <= ratio_sp <= 1.35) or rms_silence > 0.05:
        errors.append(f'Gate 2: فشل apply_local_agc في موازنة السائل البعيد (ratio={ratio_sp:.2f}, silence={rms_silence:.4f})')
    else:
        print(f'  ✓ Two-Way Local AGC سليم: وازن صوت السائل البعيد (-42dB) مع الشيخ (-18dB) بنسبة {ratio_sp:.2f}× وحافظ على الصمت ({rms_silence:.4f})')

    # 2) اختبار تطهير الديباجة اللاتينية والترويسات الوصفية
    contaminated = (
        "I have launched view_file on lesson_audio.mp3 and will now provide the exact Arabic transcript.\n\n"
        "الشيخ: محمد البردوني الحسيمي\n"
        "السلسلة: شرح مقدمات السنوسي\n"
        "الفيديو: الدرس الأول\n"
        "[شارة إنشادية]\n"
        "**الشيخ:** بسم الله الرحمن الرحيم، الحمد لله رب العالمين، والصلاة والسلام على سيدنا محمد وعلى آله وصحبه أجمعين."
    )
    cleaned, reasons = strip_preamble_and_header(contaminated)
    if not cleaned.startswith('بسم الله الرحمن الرحيم'):
        errors.append(f'Gate 2: فشل strip_preamble_and_header في تنظيف المطلع: {cleaned[:80]!r}')
    if 'LATIN_PREAMBLE' not in reasons or 'METADATA_HEADER' not in reasons:
        errors.append(f'Gate 2: لم يرصد strip_preamble_and_header كل أسباب التلوث: {reasons}')
    print(f'  ✓ مطهّر الديباجة والترويسات سليم: رصد {reasons} واستخرج مطلع الدرس الصافي')


def run_gate_3_quota_guard_and_align_schema(errors):
    print('=== [Gate 3] Quota Guard & Real .align.json Schema Validation ===')
    import agy_transcribe
    import ctc_pure_align
    import mac_align_fleet
    from ctc_forced_aligner import preprocess_text

    # 0) اختبار مشخّص < 95.0% (diagnose_low_coverage)
    fake_low_rep = {
        'spoken_align_coverage': 37.9,
        'words': 5550,
        'spoken_words': 5550,
        'interpolated': 3447,
        'forced': 37,
        'audio_span_pct': 14.5,
        'unaligned_clusters': [{'start_idx': 726, 'end_idx': 5549, 'count': 4824, 't': 575.4, 'sample': 'بسم الله الرحمن الرحيم باب البيوع'}],
    }
    diag_msg, diag_dict = mac_align_fleet.diagnose_low_coverage(fake_low_rep, 3971.8)
    causes_joined = ' '.join(diag_dict.get('causes', []))
    if 'TEXT_HALLUCINATION_OR_CHUNK_REPEAT' not in causes_joined or 'DEAD_SILENCE_TAIL_OR_TRUNCATION' not in causes_joined:
        errors.append(f'Gate 3: لم يرصد diagnose_low_coverage أسباب الهلوسة والذيل الصامت: {diag_dict}')
    else:
        print(f'  ✓ حارس ومشخّص <95% (diagnose_low_coverage) سليم: رصد {diag_dict["causes"]}')

    # 1) اختبار حارس الكوتة الحي (_is_quota_safe_for_background) على الحالات الحرجة
    snap_path = '/tmp/agy_quota_snapshot.json'
    vps_qpath = '/root/workspace/ytb-build/live_quota.json'
    backup_snap = None
    if os.path.exists(snap_path):
        backup_snap = open(snap_path, 'rb').read()

    try:
        target_qpath = vps_qpath if os.path.exists(os.path.dirname(vps_qpath)) else snap_path

        def _write_quota(rem_pct, reset_hours, exhausted=False):
            payload = {
                'models': [
                    {
                        'label': 'Gemini 3.8 Flash',
                        'remainingPercentage': rem_pct,
                        'timeUntilResetMs': int(reset_hours * 3600 * 1000),
                        'isExhausted': exhausted,
                    }
                ]
            }
            with open(target_qpath, 'w', encoding='utf-8') as f:
                json.dump(payload, f)

        # الحالة أ: نافذة 5 ساعات والكوتة 12% (< 15%) -> يجب أن يمنع (False) لحماية الـ10% للوكيل الرئيسي
        _write_quota(0.12, 2.5)
        ok_a, _ = agy_transcribe._is_quota_safe_for_background('gemini-3.8-flash-high')
        if ok_a:
            errors.append('Gate 3: سمح حارس الكوتة بالتشغيل رغم أن كوتة الـ5 ساعات = 12% (< 15%)')

        # الحالة ب: كوتة أسبوعية 22% (<= 25%) وباقي 48 ساعة (> 12 ساعة) -> يجب أن يمنع (False)
        _write_quota(0.22, 48.0)
        ok_b, _ = agy_transcribe._is_quota_safe_for_background('gemini-3.8-flash-high')
        if ok_b:
            errors.append('Gate 3: سمح حارس الكوتة بالتشغيل رغم أن الكوتة الأسبوعية = 22% (<= 25%) وباقي 48س (> 12س)')

        # الحالة ج: كوتة أسبوعية 20% (>= 15%) ولكن في آخر 8 ساعات قبل التجديد (<= 12 ساعة) -> يجب أن يسمح (True)
        _write_quota(0.20, 8.0)
        ok_c, _ = agy_transcribe._is_quota_safe_for_background('gemini-3.8-flash-high')
        if not ok_c:
            errors.append('Gate 3: منع حارس الكوتة التشغيل في آخر 8 ساعات (<= 12س) مع توفر 20% (>= 15%)')

        # الحالة د: كوتة مريحة 80% -> يجب أن يسمح (True)
        _write_quota(0.80, 72.0)
        ok_d, _ = agy_transcribe._is_quota_safe_for_background('gemini-3.8-flash-high')
        if not ok_d:
            errors.append('Gate 3: منع حارس الكوتة التشغيل مع توفر 80%')

        print('  ✓ حارس الكوتة الحي (_is_quota_safe_for_background) اجتاز الحالات الأربع الحرجة بنجاح')
    finally:
        if backup_snap is not None:
            with open(snap_path, 'wb') as f:
                f.write(backup_snap)
        elif os.path.exists(snap_path):
            try:
                os.remove(snap_path)
            except OSError:
                pass

    # 2) محاكاة محاذاة CTC نقية كاملة (align_one_file) والتحقق من مخطط .align.json
    with tempfile.TemporaryDirectory(prefix='v5_gate3_align_') as tmpd:
        words = ['بسم', 'الله', '*', 'الحمد', 'لله']
        spoken_words = [w for w in words if w != '*']
        rom_tokens, _ = preprocess_text(' '.join(spoken_words), True, 'ara', 'word', 'segment')
        # مفردات mms-300m القياسية اللاتينية
        chars = sorted({ch for tok in rom_tokens if tok != '<star>' for ch in tok})
        vocab = {'<blank>': 0}
        for idx_c, ch in enumerate(chars, 1):
            vocab[ch] = idx_c
        vocab['<star>'] = len(vocab)

        # نبني مصفوفة انبعاثات اصطناعية واضحة (240 إطار = 4.8 ثوانٍ عند 50fps)
        T = 240
        C = len(vocab)
        em = np.full((T, C), -10.0, dtype=np.float32)
        em[:, 0] = 0.0  # افتراضياً blank
        em[:, vocab['<star>']] = -2.0

        def _paint_rom_word(f_start, rom_w):
            cur = f_start
            for ch in rom_w:
                cid = vocab[ch]
                em[cur:cur + 4, :] = -10.0
                em[cur:cur + 4, cid] = 0.0
                cur += 6  # إطاران blank بين كل حرفين متتاليين

        word_only_roms = [t for t in rom_tokens if t != '<star>']
        starts = [10, 60, 120, 180]
        for st_f, rw in zip(starts, word_only_roms):
            _paint_rom_word(st_f, rw)

        # vocab المحفوظ في tokens.json لا يتضمن <star> لأن get_alignments يضيفه من العمود الأخير
        saved_vocab = {k: v for k, v in vocab.items() if k != '<star>'}
        em_path = os.path.join(tmpd, '001_test.em.npy')
        tok_path = os.path.join(tmpd, '001_test.tokens.json')
        meta_path = os.path.join(tmpd, '001_test.meta.json')
        out_align = os.path.join(tmpd, '001_test.align.json')

        np.save(em_path, em)
        json.dump(
            {'vocab': saved_vocab, 'vocab_size': len(saved_vocab), 'pad': 0, 'blank': 0, 'words': words, 'n_words': len(words)},
            open(tok_path, 'w', encoding='utf-8'), ensure_ascii=False
        )
        json.dump(
            {'model': 'mms-300m-1130-forced-aligner', 'fps': 50.0, 'stride_ms': 20.0, 'frames': T, 'classes': C, 'dur': T / 50.0, 'n_words': len(words), 'audio': '001_test.mp3'},
            open(meta_path, 'w', encoding='utf-8'), ensure_ascii=False
        )

        ns = argparse.Namespace(
            em=em_path, tokens=tok_path, out=out_align, series_out='', only='', tag='gate3_synth',
            slice=120.0, pin=65.0, margin=30, min_words=12, star='segment',
            pause_cut=1, pause_min_frames=15, pause_tol=10.0, min_score=-3.0, star_pen=-0.9,
            solid_handoff=1, solid_min_len=2, solid_min_score=-2.0, island_guard=0,
            v1='', shadow_unify=0, shadow_norm=1, report=''
        )
        rep = ctc_pure_align.align_one_file(em_path, tok_path, out_align, 'gate3_synth', ns)
        if not os.path.exists(out_align):
            errors.append('Gate 3: لم يُنشأ ملف .align.json من align_one_file')
        else:
            al_data = json.load(open(out_align, encoding='utf-8'))
            for req_k in ('cov', 'start', 'dur', 'align_meta', 'x'):
                if req_k not in al_data:
                    errors.append(f'Gate 3: الحقل {req_k} مفقود في .align.json')
            x_rows = al_data.get('x', [])
            if len(x_rows) != len(words):
                errors.append(f'Gate 3: عدد عناصر x ({len(x_rows)}) != عدد الكلمات ({len(words)})')
            if al_data.get('cov') != 100.0:
                errors.append(f'Gate 3: التغطية الكلية ({al_data.get("cov")}%) != 100.0%')
            if rep.get('spoken_align_coverage') != 100.0:
                errors.append(f'Gate 3: تغطية المنطوق ({rep.get("spoken_align_coverage")}%) != 100.0%')
            if x_rows[2][0] != '*' or x_rows[2][3] != 'i':
                errors.append(f'Gate 3: لم يُوسم الرمز الصامت "*" بـ "i": {x_rows[2]}')
            prev_s = -1.0
            for idx_w, row in enumerate(x_rows):
                if len(row) != 4 or row[1] is None or row[2] is None or row[2] < row[1] or row[1] < prev_s:
                    errors.append(f'Gate 3: خلل رتابة زمنية عند الكلمة {idx_w}: {row}')
                prev_s = row[1]
            print(
                f'  ✓ محاكاة المحاذاة النقية ومخطط .align.json سليم 100%: '
                f'cov={al_data["cov"]}%, spoken_align={rep["spoken_align_coverage"]}%, '
                f'silent_tokens={rep["silent_tokens"]}'
            )


def run_gate_4_pre_speech_breath_onset_tightening(errors):
    print('=== [Gate 4] Pre-Speech Breath Onset Tightening Gate (ALIGN-ONSET-BREATH-JUMP) ===')
    import ctc_pure_align
    from ctc_forced_aligner import preprocess_text

    # 1) محاكاة التقاط أول حرف ('ف' في 'فهناك') على صوت الشهيق في أول سكتة طولها 3.1 ثوانٍ قبل النطق الفعلي للكلمة
    with tempfile.TemporaryDirectory(prefix='v5_gate4_breath_') as tmpd:
        words = ['الحمد', 'لله.', 'فهناك', 'شهادات']
        rom_tokens, _ = preprocess_text(' '.join(words), True, 'ara', 'word', 'segment')
        chars = sorted({ch for tok in rom_tokens if tok != '<star>' for ch in tok.split(' ') if ch})
        vocab = {'<blank>': 0}
        for idx_c, ch in enumerate(chars, 1):
            vocab[ch] = idx_c
        vocab['<star>'] = len(vocab)

        # 300 إطار = 6.0 ثوانٍ عند 50fps
        T = 300
        C = len(vocab)
        em = np.full((T, C), -10.0, dtype=np.float32)
        em[:, 0] = 0.0
        em[:, vocab['<star>']] = -2.0

        def _paint_letters(f_start, letters_list):
            cur = f_start
            for ch in letters_list:
                cid = vocab[ch]
                em[cur:cur + 3, :] = -10.0
                em[cur:cur + 3, cid] = 0.0
                cur += 5
            return cur

        word_roms = [t.split(' ') for t in rom_tokens if t != '<star>']
        # الكلمة 0 ('الحمد') عند الإطار 10 (0.20s..0.64s)
        _paint_letters(10, word_roms[0])
        # الكلمة 1 ('لله.') عند الإطار 38 (0.76s..1.02s)
        _paint_letters(38, word_roms[1])
        # نفس/شهيق مبكر عند الإطار 55 (1.10s) يفعّل الحرف الأول من 'فهناك' ('f')، يليه 3.10 ثوانٍ من الصمت (<blank>)!
        first_ch_fahanak = word_roms[2][0]
        em[55:58, :] = -10.0
        em[55:58, vocab[first_ch_fahanak]] = 0.0
        # النطق الفعلي لبقية حروف 'فهناك' عند الإطار 212 (4.24s..4.60s) ثم 'شهادات' عند الإطار 238 (4.76s..5.30s)
        _paint_letters(212, word_roms[2][1:])
        _paint_letters(238, word_roms[3])

        saved_vocab = {k: v for k, v in vocab.items() if k != '<star>'}
        em_path = os.path.join(tmpd, 'breath_test.em.npy')
        tok_path = os.path.join(tmpd, 'breath_test.tokens.json')
        meta_path = os.path.join(tmpd, 'breath_test.meta.json')
        out_align = os.path.join(tmpd, 'breath_test.align.json')

        np.save(em_path, em)
        json.dump(
            {'vocab': saved_vocab, 'vocab_size': len(saved_vocab), 'pad': 0, 'blank': 0, 'words': words, 'n_words': len(words)},
            open(tok_path, 'w', encoding='utf-8'), ensure_ascii=False
        )
        json.dump(
            {'model': 'mms-300m-1130-forced-aligner', 'fps': 50.0, 'stride_ms': 20.0, 'frames': T, 'classes': C, 'dur': T / 50.0, 'n_words': len(words), 'audio': 'breath_test.mp3'},
            open(meta_path, 'w', encoding='utf-8'), ensure_ascii=False
        )

        ns = argparse.Namespace(
            em=em_path, tokens=tok_path, out=out_align, series_out='', only='', tag='gate4_breath',
            slice=120.0, pin=65.0, margin=30, min_words=12, star='segment',
            pause_cut=1, pause_min_frames=15, pause_tol=10.0, min_score=-3.0, star_pen=-0.9,
            solid_handoff=1, solid_min_len=2, solid_min_score=-2.0, island_guard=0,
            v1='', shadow_unify=0, shadow_norm=1, report=''
        )
        ctc_pure_align.align_one_file(em_path, tok_path, out_align, 'gate4_breath', ns)
        al_data = json.load(open(out_align, encoding='utf-8'))
        x = al_data['x']
        w1_end = x[1][2]
        w2_start, w2_end = x[2][1], x[2][2]
        w2_dur = round(w2_end - w2_start, 2)
        if w2_start < 4.05:
            errors.append(f'Gate 4: قفزت بداية الكلمة "فهناك" مبكراً إلى الشهيق ({w2_start}s < 4.05s): {x[2]}')
        if w2_dur > 0.85:
            errors.append(f'Gate 4: امتد طول الكلمة "فهناك" عبر السكتة ({w2_dur}s > 0.85s): {x[2]}')
        if w1_end > 1.20:
            errors.append(f'Gate 4: تمددت نهاية الكلمة السابقة "لله." داخل السكتة ({w1_end}s > 1.20s): {x[1]}')
        print(
            f'  ✓ شدّ بداية الكلمة ضد الشهيق والفراغ (tighten_word_onsets_against_breath_and_blank) سليم: '
            f'"لله."={x[1][1]}..{w1_end}s -> سكتة نظيفة -> "فهناك"={w2_start}..{w2_end}s (طول={w2_dur}s)'
        )

    # 2) اختبار عدم ابتلاع الفجوة الصامتة في interpolate() عندما تكون الفجوة > 0.8s
    raw_times = {
        0: (1.00, 1.50, -0.2),
        1: (1.55, 5.80, -5.5),  # ضعيفة الثقة وسط سكتة 4.5 ثانية
        2: (6.00, 6.55, -0.1),
    }
    interp_words = ['الحمد', 'والصلاة', 'والسلام']
    t_out, fl_out = ctc_pure_align.interpolate(dict(raw_times), interp_words, min_score=-3.0)
    interp_s, interp_e, _ = t_out[1]
    interp_dur = round(interp_e - interp_s, 2)
    if fl_out[1] != 'i':
        errors.append(f'Gate 4: لم تُوسم الكلمة ضعيفة الثقة بـ "i": {fl_out}')
    if interp_s < 5.30 or interp_dur > 0.65 or interp_dur < 0.30:
        errors.append(
            f'Gate 4: ابتلعت interpolate() سكتة النفس بدل وضع الكلمة بجوار الكلام الفعلي: '
            f'start={interp_s}s, end={interp_e}s, dur={interp_dur}s'
        )
    else:
        print(
            f'  ✓ حارس الاستيفاء عبر السكتات (interpolate) سليم: '
            f'وضع "والصلاة" عند {interp_s}..{interp_e}s (طول={interp_dur}s) بجوار الكلمة التالية (6.00s) دون ابتلاع السكتة'
        )


def run_gate_5_chunk_boundary_dedup_and_post_breath_duration(errors):
    print('=== [Gate 5] Chunk-Boundary Overlap Deduplication & Post-Breath Onset Duration Gate ===')
    import agy_transcribe
    import ctc_pure_align
    from ctc_forced_aligner import preprocess_text
    from sanitize_preamble import deduplicate_chunk_boundary_overlap, strip_preamble_and_header

    # 1) فحص إزالة تداخل الجمل عند حدود المقاطع (12 دقيقة) مع الحفاظ على التكرارات التعبدية المشروعة
    chunk_1 = (
        "بسم الله الرحمن الرحيم. الحمد لله رب العالمين، اللهم اغفر لنا وارحمنا، آمين آمين. "
        "وصلى الله على نبينا محمد صلى الله عليه وسلم، صلى الله عليه وسلم. "
        "وهذا هو القول الراجح عند جمهور الفقهاء في مسألة خيار المجلس وأحكامه."
    )
    chunk_2 = (
        "وهذا هو القولُ الراجح عند جمهور الفقهاء في مسألة خيار المجلس وأحكامه، "
        "ثم ننتقل الآن إلى المبحث الثاني في شروط صحة البيع ولزومه عند الأئمة الأربعة. "
        "ويشترط فيه الرضا التام بين المتعاقدين بلا إكراه."
    )
    chunk_3 = (
        "ويشترط فيه الرضا التام بين المتعاقدين بلا إكراه. "
        "نسأل الله القبول والتوفيق، آمين آمين، وصلى الله وسلم على سيدنا محمد."
    )

    merged_from_list = agy_transcribe.deduplicate_chunk_boundary_overlap([chunk_1, chunk_2, chunk_3])
    merged_from_str = deduplicate_chunk_boundary_overlap('\n\n'.join([chunk_1, chunk_2, chunk_3]))
    cleaned_full, clean_reasons = strip_preamble_and_header('\n\n'.join([chunk_1, chunk_2, chunk_3]))

    if merged_from_list.count('جمهور الفقهاء في مسألة خيار المجلس') != 1:
        errors.append(
            f'Gate 5: فشل deduplicate_chunk_boundary_overlap (list) في إزالة تكرار حد المقطع الأول/الثاني: '
            f'count={merged_from_list.count("جمهور الفقهاء في مسألة خيار المجلس")}'
        )
    if merged_from_str.count('الرضا التام بين المتعاقدين بلا إكراه') != 1:
        errors.append(
            f'Gate 5: فشل deduplicate_chunk_boundary_overlap (str) في إزالة تكرار حد المقطع الثاني/الثالث: '
            f'count={merged_from_str.count("الرضا التام بين المتعاقدين بلا إكراه")}'
        )
    if 'CHUNK_BOUNDARY_OVERLAP' not in clean_reasons:
        errors.append(f'Gate 5: لم يسجل strip_preamble_and_header السبب CHUNK_BOUNDARY_OVERLAP: {clean_reasons}')

    # التحقق الصارم من الحفاظ الكامل على التكرارات التعبدية المشروعة («آمين آمين»، «صلى الله عليه وسلم»)
    if merged_from_list.count('آمين آمين') != 2:
        errors.append(
            f'Gate 5: حُذف التكرار التعبدي المشروع "آمين آمين" بالخطأ! '
            f'(المتوقع=2، الفعلي={merged_from_list.count("آمين آمين")})'
        )
    if merged_from_list.count('صلى الله عليه وسلم') != 2:
        errors.append(
            f'Gate 5: حُذف التكرار التعبدي المشروع "صلى الله عليه وسلم" بالخطأ! '
            f'(المتوقع=2، الفعلي={merged_from_list.count("صلى الله عليه وسلم")})'
        )
    print(
        '  ✓ deduplicate_chunk_boundary_overlap سليم: أزال الجمل المكررة عند حدود المقاطع (12د) '
        'وحافظ 100% على التكرارات التعبدية المشروعة («آمين آمين»، «صلى الله عليه وسلم»)'
    )

    sw_phone = ctc_pure_align.shadow_words_1to1(['00971656669999.', '2500000'])
    if len(sw_phone) != 2 or not sw_phone[0].startswith('صفرصفر') or 'مليون' not in sw_phone[1]:
        errors.append(f'Gate 5: فشل shadow_words_1to1 في تفقيط أرقام الهواتف أو الملايين: {sw_phone}')
    else:
        print(f'  ✓ shadow_words_1to1 سليم لأرقام الهواتف الطويلة والملايين: {sw_phone[0][:18]}... / {sw_phone[1]}')

    # 2) فحص سقف مدة الكلمة بعد سكتة النفس (Post-Breath Onset Duration Gate) عبر أطوال كلمات متعددة
    with tempfile.TemporaryDirectory(prefix='v5_gate5_postbreath_') as tmpd:
        words = ['قال', 'المصنف:', 'فالمعاملات', 'المالية', 'مبنية', 'على', 'العدل']
        rom_tokens, _ = preprocess_text(' '.join(words), True, 'ara', 'word', 'segment')
        chars = sorted({ch for tok in rom_tokens if tok != '<star>' for ch in tok.split(' ') if ch})
        vocab = {'<blank>': 0}
        for idx_c, ch in enumerate(chars, 1):
            vocab[ch] = idx_c
        vocab['<star>'] = len(vocab)

        # 400 إطار = 8.0 ثوانٍ عند 50fps
        T = 400
        C = len(vocab)
        em = np.full((T, C), -10.0, dtype=np.float32)
        em[:, 0] = 0.0
        em[:, vocab['<star>']] = -2.0

        def _paint(f_start, letters_list):
            cur = f_start
            for ch in letters_list:
                cid = vocab[ch]
                em[cur:cur + 3, :] = -10.0
                em[cur:cur + 3, cid] = 0.0
                cur += 4
            return cur

        word_roms = [t.split(' ') for t in rom_tokens if t != '<star>']
        # الكلمة 0 ('قال') والكلمة 1 ('المصنف:') قبل سكتة النفس (0.20s..1.10s)
        _paint(10, word_roms[0])
        _paint(30, word_roms[1])
        # شهيق مبكر عند الإطار 62 (1.24s) يلتقط أول حرفين من 'فالمعاملات'، يليه صمت حتى الإطار 210 (4.20s)
        for idx_b, ch_b in enumerate(word_roms[2][:2]):
            f_b = 62 + idx_b * 3
            em[f_b:f_b + 2, :] = -10.0
            em[f_b:f_b + 2, vocab[ch_b]] = 0.0
        # النطق الفعلي لـ 'فالمعاملات' عند الإطار 210 (4.20s) وبقية الجملة بعدها
        cur_f = _paint(210, word_roms[2][2:])
        for w_idx in range(3, len(word_roms)):
            cur_f = _paint(cur_f + 4, word_roms[w_idx])

        saved_vocab = {k: v for k, v in vocab.items() if k != '<star>'}
        em_path = os.path.join(tmpd, 'postbreath.em.npy')
        tok_path = os.path.join(tmpd, 'postbreath.tokens.json')
        meta_path = os.path.join(tmpd, 'postbreath.meta.json')
        out_align = os.path.join(tmpd, 'postbreath.align.json')

        np.save(em_path, em)
        json.dump(
            {'vocab': saved_vocab, 'vocab_size': len(saved_vocab), 'pad': 0, 'blank': 0, 'words': words, 'n_words': len(words)},
            open(tok_path, 'w', encoding='utf-8'), ensure_ascii=False
        )
        json.dump(
            {'model': 'mms-300m-1130-forced-aligner', 'fps': 50.0, 'stride_ms': 20.0, 'frames': T, 'classes': C, 'dur': T / 50.0, 'n_words': len(words), 'audio': 'postbreath.mp3'},
            open(meta_path, 'w', encoding='utf-8'), ensure_ascii=False
        )

        ns = argparse.Namespace(
            em=em_path, tokens=tok_path, out=out_align, series_out='', only='', tag='gate5_postbreath',
            slice=120.0, pin=65.0, margin=30, min_words=12, star='segment',
            pause_cut=1, pause_min_frames=15, pause_tol=10.0, min_score=-3.0, star_pen=-0.9,
            solid_handoff=1, solid_min_len=2, solid_min_score=-2.0, island_guard=0,
            v1='', shadow_unify=0, shadow_norm=1, report=''
        )
        ctc_pure_align.align_one_file(em_path, tk_path=tok_path, out_path=out_align, tag='gate5_postbreath', a=ns)
        al_data = json.load(open(out_align, encoding='utf-8'))
        x = al_data['x']
        prev_end = x[1][2]
        pb_start, pb_end = x[2][1], x[2][2]
        pb_dur = round(pb_end - pb_start, 2)
        max_allowed_dur = round(max(0.85, 0.22 * len(words[2])), 2)
        pause_gap = round(pb_start - prev_end, 2)

        if pb_start < 3.95 or pause_gap < 2.50:
            errors.append(
                f'Gate 5: لم تُشدّ بداية الكلمة الطويلة "فالمعاملات" بعد سكتة النفس '
                f'(start={pb_start}s, gap={pause_gap}s): {x[2]}'
            )
        if pb_dur > max_allowed_dur or pb_dur < 0.20:
            errors.append(
                f'Gate 5: مدة الكلمة بعد النفس خارج النطاق الفيزيائي '
                f'(dur={pb_dur}s, max_allowed={max_allowed_dur}s): {x[2]}'
            )
        print(
            f'  ✓ Post-Breath Onset Duration Gate سليم: '
            f'"المصنف:" ينتهي {prev_end}s -> فجوة نفس نظيفة ({pause_gap}s) -> '
            f'"فالمعاملات"={pb_start}..{pb_end}s (المدة={pb_dur}s <= السقف الفيزيائي {max_allowed_dur}s)'
        )


def main():
    errors = []
    run_gate_1_syntax_and_integrity(errors)
    run_gate_2_silence_math_and_sanitizer(errors)
    run_gate_3_quota_guard_and_align_schema(errors)
    run_gate_4_pre_speech_breath_onset_tightening(errors)
    run_gate_5_chunk_boundary_dedup_and_post_breath_duration(errors)

    if errors:
        print(f'\nFAIL ({len(errors)} errors):')
        for err in errors:
            print(f'  - {err}')
        sys.exit(1)

    print('\nPASS (0 errors)')
    sys.exit(0)


if __name__ == '__main__':
    main()
