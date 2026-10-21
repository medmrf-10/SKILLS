#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""اختبارات وحدة لـ mac_audio_assist.py وللتراجع/القاطع/طلبات الماك في vps_align_feeder.py.
لا شبكة ولا ssh ولا يوتيوب. التشغيل:  python3 -m unittest discover -s sheikh-series-pipeline/tests -v
"""
import json
import os
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'scripts'))
import mac_audio_assist as assist  # noqa: E402
import yt_session_check as ytcheck  # noqa: E402
import vps_align_feeder as feeder  # noqa: E402

ITEM = {'key': 'sh__s1__001_abc', 'vid': 'abcdefghijk', 'url': '', 'stem': '001_abc', 'sheikh': 'sh',
        'row': 's1', 'txt_path': '/root/workspace/ytb/sh/s1/001_abc.txt', 'dur_s': 1800}


class AssistPureTests(unittest.TestCase):
    def test_backoff_doubles_and_caps(self):
        self.assertEqual(assist.backoff_delay(1), 600)
        self.assertEqual(assist.backoff_delay(2), 1200)
        self.assertEqual(assist.backoff_delay(3), 2400)
        self.assertEqual(assist.backoff_delay(50), assist.BACKOFF_MAX_S)

    def test_direct_url_detection(self):
        self.assertTrue(assist.is_direct_audio_url('https://archive.org/download/x/y.mp3'))
        self.assertTrue(assist.is_direct_audio_url('https://example.com/a.M4A'))
        self.assertFalse(assist.is_direct_audio_url('https://www.youtube.com/watch?v=abc'))
        self.assertFalse(assist.is_direct_audio_url(''))
        self.assertFalse(assist.is_direct_audio_url(None))

    def test_youtube_url_fallback_from_vid(self):
        self.assertEqual(assist.youtube_url(ITEM), 'https://www.youtube.com/watch?v=abcdefghijk')
        self.assertEqual(assist.youtube_url(dict(ITEM, url='https://youtu.be/zzz')), 'https://youtu.be/zzz')

    def test_job_meta_matches_feeder_schema(self):
        m = assist.build_job_meta(ITEM, 123456, now=1.5)
        self.assertEqual(sorted(m), sorted(['key', 'vid', 'stem', 'sheikh', 'row', 'txt_path', 'dur_s', 'opus_bytes', 'created_at']))
        self.assertEqual(m['opus_bytes'], 123456)
        self.assertEqual(m['created_at'], 1.5)

    def test_duration_check(self):
        self.assertTrue(assist.duration_ok(1790, 1800))
        self.assertTrue(assist.duration_ok(1500, 1800))        # 83% مقبول
        self.assertFalse(assist.duration_ok(900, 1800))        # مبتور
        self.assertFalse(assist.duration_ok(None, 1800))
        self.assertTrue(assist.duration_ok(60, 0))             # المتوقعة مجهولة: يكفي أن تكون معقولة
        self.assertFalse(assist.duration_ok(2, 0))

    def test_cooldown_cycle(self):
        assist._FAILS.clear()
        self.assertFalse(assist.in_cooldown('k'))
        d = assist.note_failure('k', now=1000.0)
        self.assertEqual(d, 600)
        self.assertTrue(assist.in_cooldown('k', now=1500.0))
        self.assertFalse(assist.in_cooldown('k', now=1700.0))
        assist.note_success('k')
        self.assertFalse(assist.in_cooldown('k', now=1001.0))


class FeederResilienceTests(unittest.TestCase):
    def setUp(self):
        feeder._KEY_FAILS.clear()
        feeder._YT_STATE.update({'streak': 0, 'blocked_until': 0.0})
        self.tmp = tempfile.TemporaryDirectory()
        self.p = [mock.patch.object(feeder, 'NEED_DIR', os.path.join(self.tmp.name, 'need')),
                  mock.patch.object(feeder, 'BRIDGE_DIR', os.path.join(self.tmp.name, 'ready')),
                  mock.patch.object(feeder, 'MAC_ASSIST_ENABLED', True)]
        for x in self.p:
            x.start()
        os.makedirs(feeder.BRIDGE_DIR, exist_ok=True)

    @staticmethod
    def write(path, text):
        with open(path, 'w') as f:
            f.write(text)

    def tearDown(self):
        for x in self.p:
            x.stop()
        self.tmp.cleanup()

    def test_key_backoff_skips_failed_head_so_queue_progresses(self):
        feeder.note_key_failure('a', now=1000.0)
        self.assertTrue(feeder.key_in_cooldown('a', now=1100.0))
        self.assertFalse(feeder.key_in_cooldown('b', now=1100.0))      # غيره يتقدّم
        self.assertFalse(feeder.key_in_cooldown('a', now=1000.0 + 301))
        self.assertEqual(feeder.note_key_failure('a', now=5000.0), 600)  # ثاني إخفاق: ضعف المدة
        feeder.note_key_success('a')
        self.assertFalse(feeder.key_in_cooldown('a', now=5001.0))

    def test_key_backoff_caps(self):
        d = 0
        for _ in range(30):
            d = feeder.note_key_failure('z', now=0.0)
        self.assertEqual(d, feeder.KEY_BACKOFF_MAX_S)

    def test_circuit_breaker_opens_after_streak_and_closes_on_success(self):
        for _ in range(feeder.YT_BLOCK_AFTER - 1):
            feeder.note_yt_result(False, now=100.0)
        self.assertFalse(feeder.yt_blocked(now=100.0))
        feeder.note_yt_result(False, now=100.0)
        self.assertTrue(feeder.yt_blocked(now=101.0))
        self.assertFalse(feeder.yt_blocked(now=100.0 + feeder.YT_BLOCK_SECONDS + 1))
        feeder.note_yt_result(False, now=0.0)
        feeder.note_yt_result(True, now=0.0)
        self.assertEqual(feeder._YT_STATE['streak'], 0)

    def test_request_mac_download_is_idempotent_and_complete(self):
        self.assertTrue(feeder.request_mac_download(ITEM))
        self.assertFalse(feeder.request_mac_download(ITEM))
        with open(feeder.need_path(ITEM['key'])) as f:
            d = json.load(f)
        for k in ('key', 'vid', 'url', 'stem', 'sheikh', 'row', 'txt_path', 'dur_s', 'requested_at'):
            self.assertIn(k, d)

    def test_cleanup_removes_fulfilled_done_and_missing_txt(self):
        txt = os.path.join(self.tmp.name, 'a.txt')
        self.write(txt, 'x' * 100)
        live = dict(ITEM, key='live', txt_path=txt)
        fulfilled = dict(ITEM, key='fulfilled', txt_path=txt)
        gone = dict(ITEM, key='gone', txt_path=os.path.join(self.tmp.name, 'missing.txt'))
        for it in (live, fulfilled, gone):
            feeder.request_mac_download(it)
        self.write(os.path.join(feeder.BRIDGE_DIR, 'fulfilled.job.json'), '{}')
        feeder.cleanup_need_files(allowed_vids=None)
        left = sorted(os.path.basename(p) for p in os.listdir(feeder.NEED_DIR))
        self.assertEqual(left, ['live.need.json'])
        done_txt = os.path.join(self.tmp.name, 'd.txt')
        self.write(done_txt, 'x' * 100)
        self.write(os.path.join(self.tmp.name, 'd.align.json'), 'y' * 300)
        feeder.request_mac_download(dict(ITEM, key='done', txt_path=done_txt))
        feeder.cleanup_need_files()
        self.assertFalse(os.path.exists(feeder.need_path('done')))
        self.assertTrue(os.path.exists(feeder.need_path('live')))


class YouTubeSessionGateTests(unittest.TestCase):
    def setUp(self):
        feeder._KEY_FAILS.clear()
        feeder._YT_SESSION.update({'ok': True, 'checked_at': 0.0, 'warned_at': 0.0})

    def test_cookie_logic_requires_login_info_on_youtube_domain(self):
        self.assertTrue(ytcheck.logged_in_from_cookies([{'name': 'LOGIN_INFO', 'domain': '.youtube.com'}]))
        self.assertFalse(ytcheck.logged_in_from_cookies([{'name': 'SID', 'domain': '.google.com'},
                                                         {'name': 'LOGIN_INFO', 'domain': '.google.com'}]))
        self.assertFalse(ytcheck.logged_in_from_cookies([]))
        self.assertFalse(ytcheck.logged_in_from_cookies(None))

    def test_gate_is_cached_within_ttl(self):
        calls = []
        chk = lambda: calls.append(1) or False
        self.assertFalse(feeder.youtube_session_ok(now=1000.0, check=chk))
        self.assertFalse(feeder.youtube_session_ok(now=1000.0 + feeder.YT_CHECK_TTL_S - 1, check=chk))
        self.assertEqual(len(calls), 1)
        self.assertFalse(feeder.youtube_session_ok(now=1000.0 + feeder.YT_CHECK_TTL_S + 1, check=chk))
        self.assertEqual(len(calls), 2)

    def test_gate_recovers_when_login_restored(self):
        feeder.youtube_session_ok(now=0.0, check=lambda: False)
        self.assertTrue(feeder.youtube_session_ok(now=feeder.YT_CHECK_TTL_S + 1, check=lambda: True))

    def test_unreachable_check_does_not_block(self):
        with mock.patch.object(feeder.subprocess, 'run', side_effect=OSError('x')):
            self.assertTrue(feeder._run_session_check())
        with mock.patch.object(feeder.subprocess, 'run', return_value=mock.Mock(returncode=2)):
            self.assertTrue(feeder._run_session_check())
        with mock.patch.object(feeder.subprocess, 'run', return_value=mock.Mock(returncode=10)):
            self.assertFalse(feeder._run_session_check())

    def test_defer_does_not_escalate_backoff_but_skips_key(self):
        feeder.defer_key('k', seconds=300, now=1000.0)
        self.assertTrue(feeder.key_in_cooldown('k', now=1100.0))
        self.assertFalse(feeder.key_in_cooldown('k', now=1301.0))
        self.assertEqual(feeder._KEY_FAILS['k'][0], 0)                 # العدّاد لم يزدد
        self.assertEqual(feeder.note_key_failure('k', now=2000.0), 300)  # أول إخفاق حقيقي = التراجع الأساسي


class MacAssistDisabledByDefaultTests(unittest.TestCase):
    def test_handoff_off_unless_env_set(self):
        self.assertFalse(feeder.MAC_ASSIST_ENABLED)
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.object(feeder, 'NEED_DIR', os.path.join(d, 'need')):
                self.assertFalse(feeder.request_mac_download(ITEM))
                self.assertFalse(os.path.exists(os.path.join(d, 'need')))


if __name__ == '__main__':
    unittest.main()
