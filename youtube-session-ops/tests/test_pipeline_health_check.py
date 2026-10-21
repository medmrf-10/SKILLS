#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""اختبارات evaluate() و is_forbidden_command() في pipeline_health_check.py (بلا ssh ولا ملفات)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'scripts'))
import pipeline_health_check as hc  # noqa: E402

HEALTHY = dict(mac_aligned_60m=55, mac_fleet_alive=True, mac_queue=6, mac_bad_procs=[], mac_state_age_min=1.0,
               vps_session='YT-LOGGED-IN', vps_session_ok=True, vps_ready=40, vps_pending=800,
               vps_state_age_min=2.0, vps_ok_60m=100, vps_fail_60m=0)


def m(**kw):
    d = dict(HEALTHY)
    d.update(kw)
    return d


class EvaluateTests(unittest.TestCase):
    def test_healthy_has_no_alerts(self):
        self.assertEqual(hc.evaluate(HEALTHY), [])

    def test_vps_unreachable_short_circuits(self):
        a = hc.evaluate({'vps_error': 'timeout'})
        self.assertEqual(len(a), 1)
        self.assertIn('hermes-vps', a[0])

    def test_dead_youtube_session(self):
        self.assertTrue(any('جلسة يوتيوب' in x for x in hc.evaluate(m(vps_session='YT-LOGGED-OUT', vps_session_ok=False))))
        self.assertTrue(any('جلسة يوتيوب' in x for x in hc.evaluate(m(vps_session_ok=False))))

    def test_failures_exceed_successes_needs_minimum_and_majority(self):
        self.assertTrue(any('إخفاقات' in x for x in hc.evaluate(m(vps_ok_60m=2, vps_fail_60m=9))))
        self.assertFalse(any('إخفاقات' in x for x in hc.evaluate(m(vps_ok_60m=0, vps_fail_60m=3))))   # قليلة
        self.assertFalse(any('إخفاقات' in x for x in hc.evaluate(m(vps_ok_60m=50, vps_fail_60m=9))))  # النجاح أكثر

    def test_fleet_dead_and_forbidden_process(self):
        self.assertTrue(any('mac_align_fleet' in x for x in hc.evaluate(m(mac_fleet_alive=False))))
        self.assertTrue(any('ممنوعة' in x for x in hc.evaluate(m(mac_bad_procs=['/opt/homebrew/bin/yt-dlp -f ba']))))

    def test_mac_idle_despite_work(self):
        self.assertTrue(any('لم يحاذِ' in x for x in hc.evaluate(m(mac_aligned_60m=0))))
        # لا عمل جاهز ⇒ لا تنبيه خمول (قد يكون جوعاً وهو تنبيه آخر)
        a = hc.evaluate(m(mac_aligned_60m=0, vps_ready=0, mac_queue=0))
        self.assertFalse(any('لم يحاذِ' in x for x in a))
        self.assertTrue(any('جوع' in x for x in a))

    def test_nothing_pending_is_fine_even_if_idle(self):
        self.assertEqual(hc.evaluate(m(vps_pending=0, mac_aligned_60m=0, vps_ready=0, mac_queue=0)), [])

    def test_stale_feeder_state(self):
        self.assertTrue(any('متجمد' in x for x in hc.evaluate(m(vps_state_age_min=45.0))))


class ForbiddenCommandTests(unittest.TestCase):
    def test_detects_real_ytdlp_forms(self):
        self.assertTrue(hc.is_forbidden_command('/opt/homebrew/bin/yt-dlp -f ba https://x'))
        self.assertTrue(hc.is_forbidden_command('/opt/homebrew/Cellar/python@3.14/x/Python /opt/homebrew/bin/yt-dlp -f ba'))
        self.assertTrue(hc.is_forbidden_command('/opt/homebrew/bin/python3 -u /x/scripts/mac_audio_assist.py'))

    def test_ignores_text_mentions_and_other_commands(self):
        self.assertFalse(hc.is_forbidden_command('/bin/bash -c ps | grep yt-dlp'))
        self.assertFalse(hc.is_forbidden_command('ssh hermes-vps ls /tmp/yt-dlp-cache'))
        self.assertFalse(hc.is_forbidden_command('/usr/bin/python3 /x/pipeline_health_check.py'))
        self.assertFalse(hc.is_forbidden_command(''))


if __name__ == '__main__':
    unittest.main()
