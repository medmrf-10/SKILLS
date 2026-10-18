#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""vps_pipeline_watchdog.py — حارس الإنتاج الفعلي للتفريغ والجسر الصوتي على hermes-vps.

لا يكتفي بفحص systemctl is-active، بل يفحص:
1. وجود HOME=/root في وحدة systemd وفي بيئة العملية.
2. خلو آخر 25 سطراً في transcribe_smallest_first.log من أخطاء البيئة القاتلة ($HOME is not defined).
3. عدد المقاطع المنجزة فعلياً (✓ المقطع / [✓ تم]) وعدد ملفات .txt المكتوبة في آخر 30 دقيقة.
4. عمل vps_align_feeder.py.
"""
import json
import os
import pathlib
import subprocess
import time
from datetime import datetime

LOG_PATH = pathlib.Path('/root/workspace/ytb-build/transcribe_smallest_first.log')
FLAG_PATH = pathlib.Path('/root/workspace/ytb-build/TRANSCRIBE_DRAIN_COMPLETE.flag')
UNIT_PATH = pathlib.Path('/etc/systemd/system/transcribe-smallest-first.service')
STATUS_PATH = pathlib.Path('/root/workspace/ytb-build/vps_watchdog_status.json')
YTB_ROOT = pathlib.Path('/root/workspace/ytb')


def ensure_unit_env() -> bool:
    if not UNIT_PATH.exists():
        return False
    txt = UNIT_PATH.read_text(encoding='utf-8')
    if 'HOME=/root' not in txt:
        replacement = (
            '[Service]\n'
            'User=root\n'
            'Environment="HOME=/root"\n'
            'Environment="PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/root/.local/bin"\n'
        )
        txt = txt.replace('[Service]\n', replacement, 1)
        UNIT_PATH.write_text(txt, encoding='utf-8')
        subprocess.run(['systemctl', 'daemon-reload'], check=False)
        return True
    return False


def check_feeder() -> str:
    r = subprocess.run(['pgrep', '-f', 'vps_align_feeder.py'], capture_output=True)
    if r.returncode != 0:
        log_f = open('/root/workspace/ytb-build/vps_align_feeder.log', 'a', encoding='utf-8')
        subprocess.Popen(
            ['python3', '-u', '/root/workspace/ytb-build/vps_align_feeder.py'],
            stdout=log_f,
            stderr=subprocess.STDOUT,
            env={**os.environ, 'HOME': '/root'},
        )
        return 'restarted'
    return 'running'


def main() -> None:
    feeder_state = check_feeder()
    now = time.time()
    new_txts_30m = sum(
        1
        for p in YTB_ROOT.glob('*/*/*.txt')
        if not p.name.startswith('_') and p.stat().st_size >= 400 and (now - p.stat().st_mtime) <= 1800
    )
    if FLAG_PATH.exists():
        STATUS_PATH.write_text(
            json.dumps(
                {
                    'updated_at': datetime.now().isoformat(),
                    'status': 'DRAIN_COMPLETE',
                    'feeder': feeder_state,
                    'new_txts_last_30m': new_txts_30m,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding='utf-8',
        )
        return

    unit_fixed = ensure_unit_env()
    active = (
        subprocess.run(['systemctl', 'is-active', '--quiet', 'transcribe-smallest-first.service']).returncode
        == 0
    )
    tail_lines = LOG_PATH.read_text(encoding='utf-8', errors='ignore').splitlines()[-80:] if LOG_PATH.exists() else []
    home_err = sum(1 for l in tail_lines[-25:] if 'HOME is not defined' in l)
    chunks_ok = sum(1 for l in tail_lines if '✓ المقطع' in l or '[✓ تم]' in l)

    action = 'none'
    if unit_fixed or not active or home_err > 0:
        subprocess.run(['systemctl', 'restart', 'transcribe-smallest-first.service'], check=False)
        action = f'restarted_service (unit_fixed={unit_fixed}, active={active}, home_err={home_err})'

    STATUS_PATH.write_text(
        json.dumps(
            {
                'updated_at': datetime.now().isoformat(),
                'status': 'HEALTHY' if (active and home_err == 0) else 'RECOVERED',
                'action': action,
                'feeder': feeder_state,
                'recent_chunks_ok_in_tail80': chunks_ok,
                'new_txts_last_30m': new_txts_30m,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding='utf-8',
    )


if __name__ == '__main__':
    main()
