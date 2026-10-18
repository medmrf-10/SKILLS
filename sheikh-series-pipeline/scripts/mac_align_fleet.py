#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mac_align_fleet.py — محرك المحاذاة النقية (Pure CTC v4.2) على الماك (Apple Silicon M1 Pro MPS GPU) مع سحب مسبق في الخلفية.

- يحمّل نموذج MahmoudAshraf/mms-300m-1130-forced-aligner على شريحة MPS GPU مرة واحدة فقط طوال فترة العمل.
- يسحب في الخلفية (Prefetch Thread) ملفات الصوت المضغوطة (Opus 12kbps VoIP ≈ 5MB/ساعة) والنصوص من hermes-vps
  إلى /tmp/mac_align_spool حتى لا تنتظر شريحة M1 Pro الشبكة أبداً.
- يرفع ملف <stem>.align.json الناتج فوراً إلى السيرفر بجانب النص ويحدّث <stem>.meta.json ويحذف الملفات المؤقتة.
"""
import argparse
import concurrent.futures
import gc
import glob
import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime

# استخدام النسخة المخزنة محلياً من النموذج فوراً إذا كانت مكتملة على القرص
_hf_snap = '/Users/macm1pro/.cache/huggingface/hub/models--MahmoudAshraf--mms-300m-1130-forced-aligner/snapshots/49402e9577b1158620820667c218cd494cc44486'
if os.path.exists(os.path.join(_hf_snap, 'pytorch_model.bin')) or os.path.exists(os.path.join(_hf_snap, 'model.safetensors')):
    os.environ.setdefault('HF_HUB_OFFLINE', '1')
    os.environ.setdefault('TRANSFORMERS_OFFLINE', '1')

import numpy as np
import torch

SKILL_SCRIPTS = '/Users/macm1pro/REPOS/SKILLS/sheikh-series-pipeline/scripts'
sys.path.insert(0, SKILL_SCRIPTS)

from ctc_forced_aligner import load_alignment_model  # noqa: E402
from extract_emissions import (  # noqa: E402
    MODEL, SR, apply_local_agc, compact_wave, emissions_torch, peak_mb,
    plan_silence, read_audio_16k, unpad_emissions,
)
import ctc_pure_align  # noqa: E402

VPS_HOST = os.environ.get('VPS_HOST', 'hermes-vps')
REMOTE_BRIDGE = '/root/workspace/align-bridge/ready'
LOCAL_SPOOL = '/tmp/mac_align_spool'
STATE_FILE = '/Users/macm1pro/workspace/ytb-build/mac_align_state.json'
MAX_PREFETCH = int(os.environ.get('MAC_ALIGN_PREFETCH', '6'))
PREFETCH_THREADS = int(os.environ.get('MAC_ALIGN_PREFETCH_THREADS', '2'))
BATCH_SIZE = int(os.environ.get('MAC_ALIGN_BATCH_SIZE', '3'))
COOLDOWN_S = float(os.environ.get('MAC_ALIGN_COOLDOWN_S', '3.5'))
MIN_ACCEPTABLE_ALIGN_PCT = float(os.environ.get('MAC_ALIGN_MIN_PCT', '95.0'))
LOCAL_QUOTA_JSON = '/tmp/agy_quota_snapshot.json'
REMOTE_QUOTA_JSON = '/root/workspace/ytb-build/live_quota.json'
AGY_USAGE_BIN = '/Users/macm1pro/.hermes/node/bin/antigravity-usage'


def _ssh_control_path(slot='main'):
    return f'/tmp/ssh-mux-align-{slot}-%h'


def _ssh_mux_opts(slot='main'):
    return [
        '-o', 'ControlMaster=no',
        '-o', f'ControlPath={_ssh_control_path(slot)}',
        '-o', 'ServerAliveInterval=20',
        '-o', 'ServerAliveCountMax=2',
        '-o', 'ConnectTimeout=15',
    ]


def _ensure_ssh_master(slot='main'):
    cpath = _ssh_control_path(slot)
    chk = subprocess.run(
        ['ssh', '-O', 'check', '-o', f'ControlPath={cpath}', VPS_HOST],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        timeout=5, check=False
    )
    if chk.returncode == 0:
        return True
    _reset_stale_ssh_mux(slot)
    res = subprocess.run(
        [
            'ssh', '-MNf',
            '-o', 'ControlMaster=yes',
            '-o', f'ControlPath={cpath}',
            '-o', 'ControlPersist=600',
            '-o', 'ServerAliveInterval=20',
            '-o', 'ServerAliveCountMax=2',
            '-o', 'ConnectTimeout=15',
            VPS_HOST,
        ],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        timeout=20, check=False
    )
    return res.returncode == 0


PREFETCH_QUEUE = queue.Queue(maxsize=MAX_PREFETCH)
IN_FLIGHT_KEYS = set()
COMPLETED_KEYS = set()
LOCK = threading.Lock()
LIST_LOCK = threading.Lock()
UPLOAD_LOCK = threading.Lock()
UPLOAD_POOL = concurrent.futures.ThreadPoolExecutor(max_workers=1)


def log(msg):
    print(f'[{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}] [mac-align] {msg}', flush=True)


def diagnose_low_coverage(rep, dur):
    """تشخيص السبب الجذري لأي درس تهبط تغطية محاذاته المنطوقة تحت 95.0%."""
    cov = float(rep.get('spoken_align_coverage', 0.0))
    words = int(rep.get('words', 0))
    spoken = int(rep.get('spoken_words', max(1, words)))
    interp = int(rep.get('interpolated', 0))
    forced = int(rep.get('forced', 0))
    span_pct = float(rep.get('audio_span_pct', 0.0))
    clusters = rep.get('unaligned_clusters') or []
    n_clusters = len(clusters)
    max_cluster = max((c.get('count', 0) for c in clusters), default=0)
    first_cluster_sample = clusters[0].get('sample', '') if clusters else ''
    first_cluster_t = clusters[0].get('t', 0.0) if clusters else 0.0
    wpm = round(spoken / max(0.1, dur / 60.0), 1)

    causes = []
    if max_cluster >= 40 or (n_clusters >= 1 and interp >= 60):
        causes.append(f'TEXT_HALLUCINATION_OR_CHUNK_REPEAT(clusters={n_clusters}, max_run={max_cluster}w @ {first_cluster_t}s: «{first_cluster_sample[:60]}»)')
    if span_pct < 80.0:
        causes.append(f'DEAD_SILENCE_TAIL_OR_TRUNCATION(audio_span={span_pct:.1f}%)')
    if wpm > 195.0:
        causes.append(f'EXCESS_WPM_HALLUCINATION(wpm={wpm})')
    if forced >= 3 or (cov < 85.0 and not causes):
        causes.append(f'ACOUSTIC_MISMATCH_OR_DUBBED_TRACK(forced={forced}, cov={cov:.1f}%)')
    if not causes:
        causes.append(f'LOCAL_LOW_SNR_OR_OVERLAP(interp={interp}/{spoken}, clusters={n_clusters}, wpm={wpm})')

    diag = {
        'spoken_align_pct': cov,
        'interpolated_words': interp,
        'unaligned_clusters_count': n_clusters,
        'max_cluster_words': max_cluster,
        'wpm': wpm,
        'audio_span_pct': span_pct,
        'forced_steps': forced,
        'causes': causes,
    }
    msg = (
        f'cov={cov:.2f}% (< {MIN_ACCEPTABLE_ALIGN_PCT:.1f}%) | مستوفى={interp}/{spoken} كلمة | '
        f'كتل_غير_محاذاة={n_clusters} (أكبرها={max_cluster} كلمة) | WPM={wpm} | امتداد={span_pct:.1f}% | '
        f'تقدم_اضطراري={forced} => السبب: {" + ".join(causes)}'
    )
    return msg, diag


def _reset_stale_ssh_mux(slot=None):
    pattern = f'/tmp/ssh-mux-align-{slot}-*' if slot else '/tmp/ssh-mux-align-*'
    for p in glob.glob(pattern):
        try:
            subprocess.run(
                ['ssh', '-O', 'exit', '-o', f'ControlPath={p}', VPS_HOST],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=3
            )
        except Exception:
            pass
        try:
            os.remove(p)
        except OSError:
            pass


def quota_sync_worker():
    """فحص الكوتة الحية من سيرفر Antigravity المحلي كل دقيقتين ومزامنتها مع الماك و hermes-vps."""
    mux_opts = _ssh_mux_opts('quota')
    while True:
        try:
            if os.path.exists(AGY_USAGE_BIN):
                res = subprocess.run(
                    [AGY_USAGE_BIN, 'quota', '--json', '--all-models'],
                    capture_output=True, text=True, timeout=15
                )
                if res.returncode == 0 and res.stdout.strip().startswith('{'):
                    tmp_q = LOCAL_QUOTA_JSON + '.tmp'
                    with open(tmp_q, 'w', encoding='utf-8') as qf:
                        qf.write(res.stdout.strip())
                    os.replace(tmp_q, LOCAL_QUOTA_JSON)
                    _ensure_ssh_master('quota')
                    sq = subprocess.run(
                        ['scp', '-q', *mux_opts, LOCAL_QUOTA_JSON, f'{VPS_HOST}:{REMOTE_QUOTA_JSON}'],
                        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        timeout=30, check=False
                    )
                    if sq.returncode != 0:
                        _reset_stale_ssh_mux('quota')
        except Exception as e:
            _reset_stale_ssh_mux('quota')
            log(f'[تحذير مزامنة كوتة] {e}')
        time.sleep(120)


def list_remote_jobs(slot='list'):
    import base64
    with LIST_LOCK:
        _ensure_ssh_master(slot)
        mux_opts = _ssh_mux_opts(slot)
        remote_script = (
            'import glob, json, os\n'
            f'bdir = {json.dumps(REMOTE_BRIDGE)}\n'
            'jobs = []\n'
            'for p in glob.glob(bdir + "/*.job.json"):\n'
            '    op = p[:-9] + ".opus"\n'
            '    if not os.path.exists(op):\n'
            '        continue\n'
            '    try:\n'
            '        j = json.load(open(p, encoding="utf-8"))\n'
            '        tp = j.get("txt_path", "")\n'
            '        vid = j.get("vid", "")\n'
            '        sh = j.get("sheikh", "")\n'
            '        if not os.path.exists(tp) and sh and vid:\n'
            '            cs = glob.glob(f"/root/workspace/ytb/{sh}/*/*_{vid}.txt")\n'
            '            if cs:\n'
            '                tp = cs[0]\n'
            '                j["txt_path"] = tp\n'
            '        ap = tp[:-4] + ".align.json" if tp.endswith(".txt") else ""\n'
            '        if ap and os.path.exists(ap) and os.path.getsize(ap) > 200:\n'
            '            for fp in (p, op):\n'
            '                try: os.remove(fp)\n'
            '                except OSError: pass\n'
            '            continue\n'
            '        if os.path.exists(tp):\n'
            '            j["txt_content"] = open(tp, encoding="utf-8", errors="replace").read()\n'
            '            jobs.append(j)\n'
            '    except Exception:\n'
            '        pass\n'
            'jobs.sort(key=lambda x: x.get("created_at", 0))\n'
            'print(json.dumps(jobs[:12], ensure_ascii=False))\n'
        )
        b64 = base64.b64encode(remote_script.encode('utf-8')).decode('ascii')
        cmd = ['ssh', *mux_opts, VPS_HOST, f'python3 -c "import base64; exec(base64.b64decode(\'{b64}\'))"']
        res = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=35)
        if res.returncode != 0 or not res.stdout.strip():
            if res.returncode != 0:
                log(f'[تحذير list_remote_jobs] rc={res.returncode} err={(res.stderr or "").strip()[:200]}')
                _reset_stale_ssh_mux(slot)
            return []
        try:
            return json.loads(res.stdout.strip().splitlines()[-1])
        except Exception as e:
            log(f'[تحذير فك JSON في list_remote_jobs] {e}')
            return []


def prefetch_worker(worker_id=0):
    os.makedirs(LOCAL_SPOOL, exist_ok=True)
    slot = f'pf{worker_id}'
    mux_opts = _ssh_mux_opts(slot)
    while True:
        try:
            if PREFETCH_QUEUE.qsize() >= MAX_PREFETCH:
                time.sleep(1.5)
                continue
            jobs = list_remote_jobs(slot=slot)
            if not jobs:
                time.sleep(4)
                continue
            fetched_any = False
            for job in jobs:
                if PREFETCH_QUEUE.qsize() >= MAX_PREFETCH:
                    break
                key = job['key']
                with LOCK:
                    if key in IN_FLIGHT_KEYS or key in COMPLETED_KEYS:
                        continue
                    IN_FLIGHT_KEYS.add(key)

                local_opus = os.path.join(LOCAL_SPOOL, key + '.opus')
                local_txt = os.path.join(LOCAL_SPOOL, key + '.txt')
                remote_opus = f'{REMOTE_BRIDGE}/{key}.opus'
                remote_txt = job['txt_path']

                t0 = time.time()
                _ensure_ssh_master(slot)
                r1 = subprocess.run(
                    ['scp', '-q', *mux_opts, f'{VPS_HOST}:{remote_opus}', local_opus],
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    timeout=120
                )
                txt_content = job.get('txt_content')
                if txt_content:
                    with open(local_txt, 'w', encoding='utf-8') as tf:
                        tf.write(txt_content)
                    r2_ok = True
                else:
                    r2 = subprocess.run(
                        ['scp', '-q', *mux_opts, f'{VPS_HOST}:{remote_txt}', local_txt],
                        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        timeout=45
                    )
                    r2_ok = (r2.returncode == 0)

                if r1.returncode == 0 and r2_ok and os.path.exists(local_opus) and os.path.exists(local_txt):
                    dl_s = round(time.time() - t0, 1)
                    mb = os.path.getsize(local_opus) / (1024.0 * 1024.0)
                    job.pop('txt_content', None)
                    job['local_opus'] = local_opus
                    job['local_txt'] = local_txt
                    job['dl_s'] = dl_s
                    log(f'[سحب مسبق ✓] {key}.opus ({mb:.2f} MB في {dl_s}ث · طابور الماك={PREFETCH_QUEUE.qsize() + 1})')
                    PREFETCH_QUEUE.put(job)
                    fetched_any = True
                else:
                    _reset_stale_ssh_mux(slot)
                    for p in (local_opus, local_txt):
                        if os.path.exists(p):
                            os.remove(p)
                    with LOCK:
                        IN_FLIGHT_KEYS.discard(key)
            if not fetched_any:
                time.sleep(2.5)
        except Exception as e:
            _reset_stale_ssh_mux(slot)
            log(f'[تحذير سحب مسبق] {e}')
            time.sleep(3)


def make_align_args():
    ns = argparse.Namespace()
    ns.em = ''
    ns.tokens = ''
    ns.out = ''
    ns.series_out = ''
    ns.only = ''
    ns.tag = ''
    ns.slice = 120.0
    ns.pin = 65.0
    ns.margin = 30
    ns.min_words = 12
    ns.star = 'segment'
    ns.pause_cut = 1
    ns.pause_min_frames = 15
    ns.pause_tol = 10.0
    ns.min_score = -3.0
    ns.star_pen = -0.9
    ns.solid_handoff = 1
    ns.solid_min_len = 4
    ns.solid_min_score = -1.0
    ns.island_guard = 0
    ns.v1 = ''
    ns.shadow_unify = 0
    ns.shadow_norm = 1
    ns.report = ''
    return ns


def upload_and_finalize(job, local_align_path, rep):
    import base64
    key = job['key']
    vid = job.get('vid', '')
    sheikh = job.get('sheikh', '')
    remote_txt = job['txt_path']
    slot = 'up'
    mux_opts = _ssh_mux_opts(slot)
    align_summary = {
        'engine': 'ctc-pure-mac-mps',
        'model': MODEL,
        'cov': round(rep['spoken_align_coverage'] / 100.0, 4),
        'spoken_align_pct': rep['spoken_align_coverage'],
        'audio_span_pct': rep['audio_span_pct'],
        'words': rep['words'],
        'aligned': rep['aligned'],
        'interpolated': rep['interpolated'],
        'retried_without_silence_compact': bool(rep.get('retried_without_silence_compact', False)),
        'local_agc_applied': bool(rep.get('local_agc_applied', False)),
        'at': datetime.now().strftime('%Y-%m-%d %H:%M'),
    }
    if rep.get('low_coverage_diagnosis'):
        align_summary['low_coverage_diagnosis'] = rep['low_coverage_diagnosis']
    if job.get('stripped_reasons'):
        align_summary['stripped_reasons'] = job['stripped_reasons']

    cleaned_txt_b64 = job.get('cleaned_txt_b64', '')
    align_raw_bytes = open(local_align_path, 'rb').read()
    stdin_payload = json.dumps({
        'align_b64': base64.b64encode(align_raw_bytes).decode('ascii'),
        'cleaned_txt_b64': cleaned_txt_b64,
    }).encode('utf-8')

    py_code = (
        f'import base64, glob, json, os, sys\n'
        f'env_in = json.loads(sys.stdin.buffer.read().decode("utf-8"))\n'
        f'data = base64.b64decode(env_in["align_b64"])\n'
        f'if len(data) < 200:\n'
        f'    raise RuntimeError(f"short align payload: {{len(data)}} bytes")\n'
        f'rt = {json.dumps(remote_txt)}\n'
        f'vid = {json.dumps(vid)}\n'
        f'sh = {json.dumps(sheikh)}\n'
        f'if not os.path.exists(rt) and sh and vid:\n'
        f'    cands = glob.glob(f"/root/workspace/ytb/{{sh}}/*/*_{{vid}}.txt")\n'
        f'    if cands:\n'
        f'        rt = cands[0]\n'
        f'ap = rt[:-4] + ".align.json"\n'
        f'mp = rt[:-4] + ".meta.json"\n'
        f'os.makedirs(os.path.dirname(ap), exist_ok=True)\n'
        f'ct_b64 = env_in.get("cleaned_txt_b64", "")\n'
        f'if ct_b64 and rt.endswith(".txt"):\n'
        f'    ct_bytes = base64.b64decode(ct_b64)\n'
        f'    if len(ct_bytes) > 50:\n'
        f'        with open(rt + ".tmp", "wb") as tf:\n'
        f'            tf.write(ct_bytes)\n'
        f'        os.replace(rt + ".tmp", rt)\n'
        f'with open(ap + ".tmp", "wb") as f:\n'
        f'    f.write(data)\n'
        f'os.replace(ap + ".tmp", ap)\n'
        f'md = json.load(open(mp, encoding="utf-8")) if os.path.exists(mp) else {{}}\n'
        f'md["align"] = {repr(align_summary)}\n'
        f'with open(mp + ".tmp", "w", encoding="utf-8") as mf:\n'
        f'    json.dump(md, mf, ensure_ascii=False, indent=2)\n'
        f'os.replace(mp + ".tmp", mp)\n'
        f'bdir = {json.dumps(REMOTE_BRIDGE)}\n'
        f'k = {json.dumps(key)}\n'
        f'targets = set([os.path.join(bdir, k + ".job.json"), os.path.join(bdir, k + ".opus")] + (glob.glob(bdir + f"/*_{{vid}}.*") if vid else []))\n'
        f'for p in targets:\n'
        f'    if os.path.exists(p):\n'
        f'        try: os.remove(p)\n'
        f'        except OSError: pass\n'
    )
    b64_up = base64.b64encode(py_code.encode('utf-8')).decode('ascii')

    try:
        with UPLOAD_LOCK:
            for attempt in range(1, 5):
                try:
                    _ensure_ssh_master(slot)
                    subprocess.run(
                        ['ssh', *mux_opts, VPS_HOST, f'python3 -c "import base64; exec(base64.b64decode(\'{b64_up}\'))"'],
                        input=stdin_payload, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                        timeout=60, check=True
                    )
                    with LOCK:
                        COMPLETED_KEYS.add(key)
                    break
                except Exception as e:
                    _reset_stale_ssh_mux(slot)
                    if attempt == 4:
                        raise
                    log(f'[↻ إعادة محاولة رفع {attempt}/4] {key}: {e}')
                    time.sleep(3 * attempt)
    except Exception as e:
        log(f'[✗ خطأ رفع الخلفية] {key}: {e}')
    finally:
        try:
            if os.path.exists(local_align_path):
                os.remove(local_align_path)
        except OSError:
            pass
        with LOCK:
            IN_FLIGHT_KEYS.discard(key)


def main():
    from agy_transcribe import strip_preamble_and_header
    os.makedirs(LOCAL_SPOOL, exist_ok=True)
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    _reset_stale_ssh_mux()

    device = 'mps' if (hasattr(torch.backends, 'mps') and torch.backends.mps.is_available()) else 'cpu'
    dtype = torch.float16 if device == 'mps' else torch.float32
    dtype_label = 'fp16' if dtype == torch.float16 else 'fp32'
    log(f'تحميل نموذج المحاذاة {MODEL} من الكاش المحلي على شريحة الماك ({device} · {dtype_label} + طي الصمت المحافظ + حارس <{MIN_ACCEPTABLE_ALIGN_PCT:.0f}% + AGC)...')
    t_load0 = time.time()
    model, tokenizer = load_alignment_model(device, model_path=MODEL, dtype=dtype)
    vocab = {k.lower(): v for k, v in tokenizer.get_vocab().items()}
    blank = vocab.get('<blank>', tokenizer.pad_token_id)
    log(f'✓ اكتمل تحميل النموذج في {time.time() - t_load0:.1f}ث — بدء {PREFETCH_THREADS} خيوط سحب مسبق ومزامنة الكوتة وحلقة المحاذاة (batch={BATCH_SIZE}, cooldown={COOLDOWN_S}s)...')

    t_qs = threading.Thread(target=quota_sync_worker, daemon=True)
    t_qs.start()

    for wid in range(PREFETCH_THREADS):
        t_pf = threading.Thread(target=prefetch_worker, args=(wid,), daemon=True)
        t_pf.start()

    completed_lessons = 0
    total_audio_s = 0.0
    total_gpu_s = 0.0
    total_words_aligned = 0
    if os.path.exists(STATE_FILE):
        try:
            prev_st = json.load(open(STATE_FILE, encoding='utf-8'))
            completed_lessons = int(prev_st.get('completed_lessons', 0))
            total_audio_s = float(prev_st.get('total_audio_hours', 0.0)) * 3600.0
            total_words_aligned = int(prev_st.get('total_words_aligned', 0))
            total_gpu_s = total_audio_s * float(prev_st.get('avg_rtf', 0.0285))
        except Exception:
            pass
    align_args = make_align_args()

    while True:
        job = PREFETCH_QUEUE.get()
        key = job['key']
        local_opus = job['local_opus']
        local_txt = job['local_txt']
        em_path = os.path.join(LOCAL_SPOOL, key + '.em.npy')
        tok_path = os.path.join(LOCAL_SPOOL, key + '.tokens.json')
        meta_path = os.path.join(LOCAL_SPOOL, key + '.meta.json')
        out_align = os.path.join(LOCAL_SPOOL, key + '.align.json')
        rep_path = os.path.join(LOCAL_SPOOL, key + '.report.json')
        submitted_upload = False

        try:
            import base64 as _b64
            raw_txt = open(local_txt, encoding='utf-8', errors='replace').read()
            cleaned_txt, stripped_reasons = strip_preamble_and_header(raw_txt)
            if stripped_reasons and cleaned_txt and cleaned_txt != raw_txt:
                with open(local_txt, 'w', encoding='utf-8') as tf:
                    tf.write(cleaned_txt)
                job['cleaned_txt_b64'] = _b64.b64encode(cleaned_txt.encode('utf-8')).decode('ascii')
                job['stripped_reasons'] = stripped_reasons
                raw_txt = cleaned_txt
            words = raw_txt.split()
            if not words:
                log(f'[تخطي] نص فارغ: {key}')
                continue

            t0 = time.time()
            data = read_audio_16k(local_opus, sr=SR)
            t_dec = time.time() - t0
            dur = len(data) / SR

            # عتبة طيّ صمت محافظة (rel_db=9.5, win_s=8.0, min_sil=0.65, keep=0.20) تحمي الحروف المهموسة وأصوات السائلين
            t_em0 = time.time()
            keep_mask, sc_stats = plan_silence(np.asarray(data), SR, 0.65, 0.20, rel_db=9.5, win_s=8.0)
            idx_map = None
            if keep_mask is not None and sc_stats.get('pct', 0.0) >= 1.5:
                comp_data, idx_map = compact_wave(np.asarray(data), keep_mask)
                wav_in = torch.from_numpy(comp_data)
            else:
                wav_in = torch.from_numpy(data)

            em, stride = emissions_torch(
                model, wav_in, device=device, dtype=dtype,
                window=30.0, context=2.0, batch_size=BATCH_SIZE
            )
            if idx_map is not None:
                n_frames = int(sc_stats['frames_total'])
                em, _ = unpad_emissions(
                    em, idx_map, n_frames,
                    star_col=(em.shape[1] - 1 if em.shape[1] > 31 else None)
                )
            t_em = time.time() - t_em0
            fps = float(em.shape[0]) / dur if dur > 0 else 1000.0 / float(stride)

            np.save(em_path, em)
            json.dump(
                {'vocab': vocab, 'vocab_size': len(vocab), 'pad': tokenizer.pad_token_id,
                 'blank': blank, 'words': words, 'n_words': len(words)},
                open(tok_path, 'w', encoding='utf-8'), ensure_ascii=False
            )
            em_meta = {
                'model': MODEL, 'engine': 'torch', 'device': device, 'dtype': dtype_label,
                'fps': round(fps, 4), 'stride_ms': float(stride),
                'frames': int(em.shape[0]), 'classes': int(em.shape[1]),
                'dur': round(dur, 2), 'n_words': len(words),
                'audio': job['stem'] + '.mp3', 'decode_s': round(t_dec, 2),
                'load_s': 0.0, 'em_s': round(t_em, 1),
                'rtf': round(t_em / max(1.0, dur), 4),
            }
            json.dump(em_meta, open(meta_path, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)

            rep = ctc_pure_align.align_one_file(em_path, tok_path, out_align, key, align_args)

            # حارس < 95.0% الإلزامي: إعادة المحاولة تلقائياً على الموجة الكاملة بدون طي الصمت + تطبيع الكسب المحلي ثنائي الاتجاه (Two-Way AGC) لرفع مداخلات السائلين (-40dB..-52dB)
            if rep['spoken_align_coverage'] < MIN_ACCEPTABLE_ALIGN_PCT:
                cov_before = rep['spoken_align_coverage']
                log(
                    f'[⚠ حارس <{MIN_ACCEPTABLE_ALIGN_PCT:.0f}%] {key}: التغطية {cov_before:.2f}% '
                    f'(طي الصمت={sc_stats.get("pct", 0.0) if sc_stats else 0.0:.1f}%) — إعادة المحاذاة على الموجة الكاملة مع Two-Way Local AGC (window=15s)...'
                )
                t_ret0 = time.time()
                data_agc = apply_local_agc(np.asarray(data), sr=SR)
                em_full, stride_full = emissions_torch(
                    model, torch.from_numpy(data_agc), device=device, dtype=dtype,
                    window=15.0, context=2.0, batch_size=max(BATCH_SIZE, 4)
                )
                t_em_ret = time.time() - t_ret0
                t_em += t_em_ret
                fps_full = float(em_full.shape[0]) / dur if dur > 0 else 1000.0 / float(stride_full)
                np.save(em_path, em_full)
                em_meta['fps'] = round(fps_full, 4)
                em_meta['frames'] = int(em_full.shape[0])
                em_meta['em_s'] = round(t_em, 1)
                em_meta['silence_compact'] = False
                em_meta['local_agc'] = True
                json.dump(em_meta, open(meta_path, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
                retry_align = out_align + '.retry'
                rep_retry = ctc_pure_align.align_one_file(em_path, tok_path, retry_align, key + ':full_wave_agc', align_args)
                if rep_retry['spoken_align_coverage'] >= cov_before:
                    os.replace(retry_align, out_align)
                    rep = rep_retry
                    rep['retried_without_silence_compact'] = True
                    rep['local_agc_applied'] = True
                else:
                    if os.path.exists(retry_align):
                        os.remove(retry_align)
                log(
                    f'[↺ نتيجة إعادة المحاولة مع Local AGC] {key}: '
                    f'{cov_before:.2f}% -> {rep["spoken_align_coverage"]:.2f}% (الاعتماد={rep["spoken_align_coverage"]:.2f}%)'
                )
                if rep['spoken_align_coverage'] < MIN_ACCEPTABLE_ALIGN_PCT:
                    diag_msg, diag_dict = diagnose_low_coverage(rep, dur)
                    rep['low_coverage_diagnosis'] = diag_dict
                    log(f'[🔍 تشخيص جذري <{MIN_ACCEPTABLE_ALIGN_PCT:.0f}%] {key}: {diag_msg}')

            UPLOAD_POOL.submit(upload_and_finalize, job, out_align, rep)
            submitted_upload = True

            completed_lessons += 1
            total_audio_s += dur
            total_gpu_s += (t_em + rep['align_wall_s'])
            total_words_aligned += rep['words']
            rtf_avg = total_gpu_s / max(1.0, total_audio_s)

            state = {
                'updated_at': datetime.now().isoformat(),
                'device': device,
                'completed_lessons': completed_lessons,
                'total_audio_hours': round(total_audio_s / 3600.0, 2),
                'total_words_aligned': total_words_aligned,
                'avg_rtf': round(rtf_avg, 4),
                'speed_x_realtime': round(1.0 / max(0.0001, rtf_avg), 1),
                'prefetch_queue_ready': PREFETCH_QUEUE.qsize(),
                'last_lesson': {
                    'key': key,
                    'dur_min': round(dur / 60.0, 1),
                    'words': rep['words'],
                    'spoken_align_pct': rep['spoken_align_coverage'],
                    'audio_span_pct': rep['audio_span_pct'],
                    'em_s': round(t_em, 1),
                    'viterbi_s': rep['align_wall_s'],
                    'dl_s': job.get('dl_s', 0.0),
                },
            }
            with open(STATE_FILE, 'w', encoding='utf-8') as sf:
                json.dump(state, sf, ensure_ascii=False, indent=2)

            log(
                f'[✓ محاذاة #{completed_lessons}] {key} ({dur/60:.1f}د · {rep["words"]} كلمة) '
                f'في {t_em + rep["align_wall_s"]:.1f}ث (GPU={t_em:.1f}ث + فيتربي={rep["align_wall_s"]:.1f}ث · تغطية={rep["spoken_align_coverage"]:.1f}%) '
                f'| الإجمالي={total_audio_s/3600:.2f}س صوتية بسرعة {state["speed_x_realtime"]}×'
            )
        except Exception as e:
            log(f'[✗ خطأ محاذاة] {key}: {e}')
        finally:
            cleanup_paths = [local_opus, local_txt, em_path, tok_path, meta_path, rep_path]
            if not submitted_upload:
                cleanup_paths.append(out_align)
            for p in cleanup_paths:
                try:
                    if os.path.exists(p):
                        os.remove(p)
                except OSError:
                    pass
            if not submitted_upload:
                with LOCK:
                    IN_FLIGHT_KEYS.discard(key)
            PREFETCH_QUEUE.task_done()
            try:
                if device == 'mps' and hasattr(torch, 'mps') and hasattr(torch.mps, 'empty_cache'):
                    torch.mps.empty_cache()
                gc.collect()
            except Exception:
                pass
            if COOLDOWN_S > 0:
                time.sleep(COOLDOWN_S)


if __name__ == '__main__':
    main()
