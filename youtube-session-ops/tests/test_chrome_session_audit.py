#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""اختبارات المنطق النقي في chrome_session_audit.py (بلا Chrome ولا شبكة)."""
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'scripts'))
import chrome_session_audit as audit  # noqa: E402


class ClassifyTests(unittest.TestCase):
    def test_logged_in_requires_login_info_on_youtube(self):
        self.assertEqual(audit.classify({'youtube.com': {'LOGIN_INFO', 'SID'}, 'google.com': {'SID'}}), 'LOGGED-IN')

    def test_google_only_when_sid_without_youtube_login(self):
        self.assertEqual(audit.classify({'google.com': {'SID', '__Secure-1PSID'}, 'youtube.com': {'YSC'}}), 'GOOGLE-ONLY')
        self.assertEqual(audit.classify({'google.com': {'__Secure-1PSID'}}), 'GOOGLE-ONLY')

    def test_logged_out_when_nothing(self):
        self.assertEqual(audit.classify({}), 'LOGGED-OUT')
        self.assertEqual(audit.classify({'google.com': {'NID'}, 'youtube.com': {'VISITOR_INFO1_LIVE'}}), 'LOGGED-OUT')

    def test_login_info_on_google_domain_does_not_count(self):
        self.assertEqual(audit.classify({'google.com': {'LOGIN_INFO'}}), 'LOGGED-OUT')


class TimeFormatTests(unittest.TestCase):
    def test_webkit_epoch_conversion(self):
        unix = 1792580000  # أي لحظة معروفة
        us = (unix + audit.WEBKIT_EPOCH_OFFSET) * 1_000_000
        self.assertEqual(audit.webkit_to_str(us), time.strftime('%Y-%m-%d %H:%M', time.localtime(unix)))
        self.assertEqual(audit.webkit_to_str(0), '-')


if __name__ == '__main__':
    unittest.main()
