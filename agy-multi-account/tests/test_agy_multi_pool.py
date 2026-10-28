#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""اختبارات وحدة لـ agy_multi_pool.py — لا تلمس الحسابات الحقيقية ولا Keychain ولا الشبكة.

التشغيل:  python3 -m unittest discover -s agy-multi-account/tests -v
"""
import base64
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'scripts'))
import agy_multi_pool as pool  # noqa: E402


def make_id_token(email):
    seg = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip('=')
    return '%s.%s.sig' % (seg({'alg': 'none'}), seg({'email': email}))


def make_token(email, expiry='2026-10-21T08:26:41.955406+02:00'):
    return {
        'token': {'access_token': 'a', 'refresh_token': 'r', 'expiry': expiry},
        'auth_method': 'consumer',
        'id_token': make_id_token(email),
    }


class ParseUsageTests(unittest.TestCase):
    def test_parses_all_four_buckets(self):
        txt = (
            'Gemini Models\tWeekly Limit Remaining\t86%\t2026-10-27T12:41:36Z\n'
            'Gemini Models\tFive Hour Limit Remaining\t92%\t2026-10-21T10:05:49Z\n'
            'Claude and GPT models\tWeekly Limit Remaining\t86.5%\t2026-10-27T13:42:40Z\n'
            'Claude and GPT models\tFive Hour Limit Remaining\t100%\t2026-10-21T10:43:16Z\n'
        )
        q = pool.parse_usage_response(txt)
        self.assertEqual(q['gemini_weekly_pct'], 86.0)
        self.assertEqual(q['gemini_5h_pct'], 92.0)
        self.assertEqual(q['claude_weekly_pct'], 86.5)
        self.assertEqual(q['claude_5h_pct'], 100.0)
        self.assertEqual(q['gemini_weekly_reset'], '2026-10-27T12:41:36Z')

    def test_empty_and_garbage(self):
        self.assertIsNone(pool.parse_usage_response('')['gemini_weekly_pct'])
        self.assertIsNone(pool.parse_usage_response('hello\nworld')['gemini_5h_pct'])
        self.assertIsNone(pool.parse_usage_response(None)['gemini_5h_pct'])


class SharedQuotaTests(unittest.TestCase):
    def _r(self, name, gw, greset, creset='C1'):
        return {'profile': name, 'quota': {'gemini_weekly_pct': gw, 'gemini_weekly_reset': greset, 'claude_weekly_reset': creset}}

    def test_detects_group_with_identical_resets(self):
        rs = [self._r('a', 85.0, 'G1'), self._r('b', 85.0, 'G1'), self._r('c', 84.6, 'G1'),
              self._r('solo', 93.0, 'G2', 'C2')]
        self.assertEqual(pool.find_shared_quota_groups(rs), [['a', 'b', 'c']])
        pool.mark_shared_quota(rs)
        self.assertEqual(rs[0]['shared_quota_with'], ['b', 'c'])
        self.assertNotIn('shared_quota_with', rs[3])

    def test_same_reset_but_far_percentages_is_not_shared(self):
        rs = [self._r('a', 85.0, 'G1'), self._r('b', 20.0, 'G1')]
        self.assertEqual(pool.find_shared_quota_groups(rs), [])

    def test_missing_or_empty_quota_ignored(self):
        rs = [{'profile': 'x', 'quota': {}}, {'profile': 'y'}, self._r('z', 50.0, 'G1')]
        self.assertEqual(pool.find_shared_quota_groups(rs), [])


class FamilyFailoverTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = self.tmp.name
        self.reg_path = os.path.join(root, 'profiles.json')
        fam = lambda n, order, status='active': {'email': n + '@x.com', 'role': 'family-member', 'group': 'family',
                                                'failover_order': order, 'status': status}
        with open(self.reg_path, 'w') as f:
            json.dump({'main': 'm10', 'groups': {'family': {'shared_quota': True, 'use_for': 'transcribe'}},
                       'profiles': {
                           'm10': {'email': 'm10@x.com', 'role': 'main'},
                           'solo': {'email': 'solo@x.com', 'role': 'transcribe'},
                           'mgr': {'email': 'mgr@x.com', 'role': 'family-manager', 'group': 'family', 'status': 'banned'},
                           'f3': fam('f3', 3), 'f1': fam('f1', 1), 'f2': fam('f2', 2),
                           'f4': fam('f4', 4, 'ineligible'),
                       }}, f)
        self.patches = [
            mock.patch.object(pool, 'PROFILES_ROOT', os.path.join(root, 'profiles')),
            mock.patch.object(pool, 'REGISTRY_PATH', self.reg_path),
        ]
        for p in self.patches:
            p.start()
        for n in ('solo', 'mgr', 'f1', 'f2', 'f3', 'f4'):
            pdir = os.path.join(pool.PROFILES_ROOT, n)
            os.makedirs(os.path.dirname(pool.token_path(pdir)), exist_ok=True)
            with open(pool.token_path(pdir), 'w') as fh:
                json.dump(make_token(n + '@x.com'), fh)

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def test_chain_is_ordered_and_excludes_banned_manager_and_ineligible(self):
        self.assertEqual(pool.group_chain('family'), ['f1', 'f2', 'f3'])

    def test_slots_are_solo_plus_one_family_slot(self):
        self.assertEqual(pool.transcribe_slots(), [['f1', 'f2', 'f3'], ['solo']])
        self.assertEqual(pool.transcribe_pool(), ('f1', 'solo'))

    def test_role_labels(self):
        self.assertEqual(pool.role_label('f2'), 'Family Member #2')
        self.assertEqual(pool.role_label('mgr'), 'Family Manager — BANNED')
        self.assertEqual(pool.role_label('f4'), 'Family Member #4 — INELIGIBLE')

    def _usage(self, table):
        return lambda pdir, retries=1: table[os.path.basename(pdir)]

    def test_failover_to_next_when_head_is_disabled(self):
        ok = ({'gemini_5h_pct': 90.0, 'gemini_weekly_pct': 80.0, 'gemini_weekly_reset': ''}, None)
        table = {'solo': ({'gemini_5h_pct': 50.0, 'gemini_weekly_pct': 10.0, 'gemini_weekly_reset': ''}, None),
                 'f1': ({}, 'disabled'), 'f2': ok, 'f3': ok}
        with mock.patch.object(pool, 'fetch_usage', side_effect=self._usage(table)):
            c = pool.pick_best_pro_for_transcription()
        self.assertEqual(c[0]['profile'], 'f2')
        self.assertEqual(c[0]['failover_from'], ['f1'])
        self.assertEqual(c[1]['profile'], 'solo')

    def test_low_quota_does_not_trigger_failover(self):
        low = ({'gemini_5h_pct': 1.0, 'gemini_weekly_pct': 1.0, 'gemini_weekly_reset': ''}, None)
        table = {'solo': ({'gemini_5h_pct': 50.0, 'gemini_weekly_pct': 40.0, 'gemini_weekly_reset': ''}, None),
                 'f1': low, 'f2': low, 'f3': low}
        with mock.patch.object(pool, 'fetch_usage', side_effect=self._usage(table)):
            c = pool.pick_best_pro_for_transcription()
        fam = [x for x in c if x['profile'].startswith('f')][0]
        self.assertEqual(fam['profile'], 'f1')  # بقي على الأول رغم ضعف الكوتة (المشتركة)
        self.assertFalse(fam['eligible'])
        self.assertEqual(c[0]['profile'], 'solo')

    def test_all_family_failed_returns_last_with_error(self):
        table = {'solo': ({'gemini_5h_pct': 50.0, 'gemini_weekly_pct': 40.0, 'gemini_weekly_reset': ''}, None),
                 'f1': ({}, 'disabled'), 'f2': ({}, 'disabled'), 'f3': ({}, 'timeout')}
        with mock.patch.object(pool, 'fetch_usage', side_effect=self._usage(table)):
            c = pool.pick_best_pro_for_transcription()
        self.assertEqual(c[0]['profile'], 'solo')
        fam = c[1]
        self.assertEqual(fam['profile'], 'f3')
        self.assertFalse(fam['eligible'])
        self.assertEqual(fam['failover_from'], ['f1', 'f2'])

    def test_strict_priority_waterfall_family_then_brain_then_ram(self):
        """يختبر شلال الأولويات التتابعي الصارم (العائلة -> brain -> ram) بغض النظر عن تفوق كوتة الطبقة الأدنى."""
        fam = lambda n, order: {'email': n + '@x.com', 'role': 'family-member', 'group': 'family',
                                'failover_order': order, 'status': 'active'}
        with open(self.reg_path, 'w') as f:
            json.dump({
                'main': 'medmrf10',
                'groups': {'family': {'shared_quota': True, 'use_for': 'transcribe', 'priority_tier': 1}},
                'profiles': {
                    'medmrf10': {'email': 'm10@x.com', 'role': 'main'},
                    'brain': {'email': 'brain@x.com', 'role': 'transcribe', 'priority_tier': 2, 'status': 'active'},
                    'ram': {'email': 'ram@x.com', 'role': 'transcribe', 'priority_tier': 3, 'status': 'active'},
                    'mb10': fam('mb10', 1),
                    'bm10': fam('bm10', 2),
                },
            }, f)
        for n in ('brain', 'ram', 'mb10', 'bm10'):
            pdir = os.path.join(pool.PROFILES_ROOT, n)
            os.makedirs(os.path.dirname(pool.token_path(pdir)), exist_ok=True)
            with open(pool.token_path(pdir), 'w') as fh:
                json.dump(make_token(n + '@x.com'), fh)

        self.assertEqual(pool.transcribe_slots(), [['mb10', 'bm10'], ['brain'], ['ram']])

        # 1) العائلة فوق حد الأمان (20% فقط) بينما brain (90%) وram (100%) أعلى -> يختار العائلة (mb10)
        table_tier1 = {
            'mb10': ({'gemini_5h_pct': 25.0, 'gemini_weekly_pct': 20.0, 'gemini_weekly_reset': ''}, None),
            'bm10': ({'gemini_5h_pct': 25.0, 'gemini_weekly_pct': 20.0, 'gemini_weekly_reset': ''}, None),
            'brain': ({'gemini_5h_pct': 95.0, 'gemini_weekly_pct': 90.0, 'gemini_weekly_reset': ''}, None),
            'ram': ({'gemini_5h_pct': 100.0, 'gemini_weekly_pct': 100.0, 'gemini_weekly_reset': ''}, None),
        }
        with mock.patch.object(pool, 'fetch_usage', side_effect=self._usage(table_tier1)):
            c1 = pool.pick_best_pro_for_transcription()
        self.assertEqual([x['profile'] for x in c1], ['mb10', 'brain', 'ram'])

        # 2) العائلة مستنفدة (< حد الأمان) بينما brain (30%) وram (100%) مؤهلان -> ينتقل إلى brain فقط ولا يلمس ram
        table_tier2 = {
            'mb10': ({'gemini_5h_pct': 2.0, 'gemini_weekly_pct': 1.0, 'gemini_weekly_reset': ''}, None),
            'bm10': ({'gemini_5h_pct': 2.0, 'gemini_weekly_pct': 1.0, 'gemini_weekly_reset': ''}, None),
            'brain': ({'gemini_5h_pct': 40.0, 'gemini_weekly_pct': 30.0, 'gemini_weekly_reset': ''}, None),
            'ram': ({'gemini_5h_pct': 100.0, 'gemini_weekly_pct': 100.0, 'gemini_weekly_reset': ''}, None),
        }
        with mock.patch.object(pool, 'fetch_usage', side_effect=self._usage(table_tier2)):
            c2 = pool.pick_best_pro_for_transcription()
        self.assertEqual(c2[0]['profile'], 'brain')
        self.assertEqual(c2[1]['profile'], 'ram')
        self.assertFalse(c2[2]['eligible'])

        # 3) العائلة وbrain مستنفدان معاً -> ينتقل إلى الطبقة الثالثة ram
        table_tier3 = {
            'mb10': ({}, 'disabled'),
            'bm10': ({'gemini_5h_pct': 0.0, 'gemini_weekly_pct': 0.0, 'gemini_weekly_reset': ''}, None),
            'brain': ({'gemini_5h_pct': 1.0, 'gemini_weekly_pct': 1.0, 'gemini_weekly_reset': ''}, None),
            'ram': ({'gemini_5h_pct': 60.0, 'gemini_weekly_pct': 50.0, 'gemini_weekly_reset': ''}, None),
        }
        with mock.patch.object(pool, 'fetch_usage', side_effect=self._usage(table_tier3)):
            c3 = pool.pick_best_pro_for_transcription()
        self.assertEqual(c3[0]['profile'], 'ram')
        self.assertTrue(c3[0]['eligible'])


class TokenHelpersTests(unittest.TestCase):
    def test_email_from_token(self):
        self.assertEqual(pool.email_from_token_dict(make_token('a@b.com')), 'a@b.com')
        self.assertIsNone(pool.email_from_token_dict({'id_token': 'garbage'}))
        self.assertIsNone(pool.email_from_token_dict({}))

    def test_expiry_handles_nanoseconds_and_z(self):
        t = make_token('a@b.com', expiry='2026-10-21T08:26:41.955406123+02:00')
        self.assertIsNotNone(pool.token_expiry(t))
        t2 = make_token('a@b.com', expiry='2026-10-21T06:26:41Z')
        self.assertEqual(pool.token_expiry(t), pool.token_expiry(t2).replace(microsecond=955406))
        self.assertIsNone(pool.token_expiry({}))

    def test_expiry_handles_five_digit_fraction_seen_in_real_tokens(self):
        t = make_token('a@b.com', expiry='2026-10-21T08:46:13.21271+02:00')
        dt = pool.token_expiry(t)
        self.assertIsNotNone(dt)
        self.assertEqual(dt.microsecond, 212710)

    def test_disabled_detection(self):
        self.assertTrue(pool.is_disabled_text('Eligibility check failed: PERMISSION_DENIED (code 403): disabled in this account'))
        self.assertFalse(pool.is_disabled_text('Gemini Models\tWeekly Limit Remaining\t86%'))
        self.assertFalse(pool.is_disabled_text(''))

    def test_decode_keyring_value(self):
        tok = make_token('a@b.com')
        raw = pool.KEYRING_PREFIX + base64.b64encode(json.dumps(tok).encode()).decode()
        self.assertEqual(pool.decode_keyring_value(raw), tok)
        self.assertEqual(pool.decode_keyring_value(json.dumps(tok)), tok)
        self.assertIsNone(pool.decode_keyring_value('nonsense'))
        self.assertIsNone(pool.decode_keyring_value(''))


class ReconcileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.reg_path = os.path.join(self.root, 'profiles.json')
        with open(self.reg_path, 'w') as f:
            json.dump({'main': 'm10', 'profiles': {
                'm10': {'email': 'main@x.com', 'role': 'main'},
                'p19': {'email': 'p19@x.com', 'role': 'transcribe'},
                'p20': {'email': 'p20@x.com', 'role': 'transcribe'},
                'misc': {'email': 'misc@x.com', 'role': 'unassigned'},
            }}, f)
        self.patches = [
            mock.patch.object(pool, 'PROFILES_ROOT', os.path.join(self.root, 'profiles')),
            mock.patch.object(pool, 'REGISTRY_PATH', self.reg_path),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def raw(self, pdir):
        with open(pool.token_path(pdir)) as f:
            return f.read()

    def put(self, name, tok):
        pdir = os.path.join(pool.PROFILES_ROOT, name)
        os.makedirs(os.path.dirname(pool.token_path(pdir)), exist_ok=True)
        with open(pool.token_path(pdir), 'w') as f:
            json.dump(tok, f)
        return pdir

    def test_registry_roles_and_pool(self):
        self.assertEqual(pool.main_account(), 'm10')
        self.assertEqual(pool.transcribe_pool(), ('p19', 'p20'))
        self.assertEqual(pool.profile_meta('ghost')['role'], 'unassigned')
        self.assertEqual(pool.role_label('m10'), 'Main (Ultra)')

    def test_registry_fallback_when_missing(self):
        with mock.patch.object(pool, 'REGISTRY_PATH', os.path.join(self.root, 'nope.json')):
            self.assertEqual(pool.main_account(), pool.MAIN_ACCOUNT)
            self.assertEqual(pool.transcribe_pool(), pool.DEFAULT_TRANSCRIBE_PRO_POOL)

    def test_keychain_token_goes_to_owner_by_email_not_to_last_run(self):
        """الحالة التي كانت تتلف توكن البروفايل: Keychain يحمل حساب main بينما شُغّل بروفايل آخر."""
        main_dir = self.put('m10', make_token('main@x.com', '2026-10-21T06:00:00+02:00'))
        other_dir = self.put('p19', make_token('p19@x.com'))
        before_other = self.raw(other_dir)
        kc = make_token('main@x.com', '2026-10-21T09:00:00+02:00')
        res = pool.reconcile_keychain(keychain_tok=kc)
        self.assertEqual(res['status'], 'updated')
        self.assertEqual(res['profile'], 'm10')
        self.assertEqual(pool.read_token_file(main_dir), kc)
        self.assertEqual(self.raw(other_dir), before_other)  # الآخر لم يُمسّ
        self.assertEqual(oct(os.stat(pool.token_path(main_dir)).st_mode & 0o777), '0o600')
        baks = [f for f in os.listdir(os.path.dirname(pool.token_path(main_dir))) if '.bak.' in f]
        self.assertEqual(len(baks), 1)

    def test_older_keychain_token_does_not_overwrite(self):
        d = self.put('p19', make_token('p19@x.com', '2026-10-21T10:00:00+02:00'))
        cur = pool.read_token_file(d)
        res = pool.reconcile_keychain(keychain_tok=make_token('p19@x.com', '2026-10-21T08:00:00+02:00'))
        self.assertEqual(res['status'], 'unchanged')
        self.assertEqual(pool.read_token_file(d), cur)

    def test_missing_profile_file_gets_created(self):
        os.makedirs(os.path.join(pool.PROFILES_ROOT, 'p20'), exist_ok=True)
        # بروفايل بلا توكن لا يظهر في list_profiles → يُحل المالك من السجل ثم يُكتب الملف
        kc = make_token('p20@x.com')
        res = pool.reconcile_keychain(keychain_tok=kc)
        self.assertEqual(res['status'], 'updated')
        self.assertEqual(pool.read_token_file(os.path.join(pool.PROFILES_ROOT, 'p20')), kc)

    def test_unowned_email_is_left_alone(self):
        self.put('p19', make_token('p19@x.com'))
        res = pool.reconcile_keychain(keychain_tok=make_token('stranger@x.com'))
        self.assertEqual(res['status'], 'unowned')

    def test_dry_run_changes_nothing(self):
        d = self.put('m10', make_token('main@x.com', '2026-10-21T06:00:00+02:00'))
        before = self.raw(d)
        res = pool.reconcile_keychain(dry_run=True, keychain_tok=make_token('main@x.com', '2026-10-21T09:00:00+02:00'))
        self.assertEqual(res['status'], 'would-update')
        self.assertEqual(self.raw(d), before)

    def test_delete_only_after_safe_copy(self):
        self.put('m10', make_token('main@x.com', '2026-10-21T06:00:00+02:00'))
        with mock.patch.object(pool, 'delete_keychain_entry') as d:
            pool.reconcile_keychain(delete=True, keychain_tok=make_token('main@x.com', '2026-10-21T09:00:00+02:00'))
            d.assert_called_once()
        with mock.patch.object(pool, 'delete_keychain_entry') as d:
            pool.reconcile_keychain(delete=False, keychain_tok=make_token('main@x.com', '2026-10-21T10:00:00+02:00'))
            d.assert_not_called()

    def test_list_profiles_ignores_hidden_backup_dir(self):
        self.put('p19', make_token('p19@x.com'))
        self.put('.backups', make_token('x@x.com'))
        names = [n for n, _ in pool.list_profiles(register_default=False)]
        self.assertEqual(names, ['p19'])

    def test_aliases_rendered_from_registry(self):
        out = pool.render_aliases()
        self.assertIn("alias m10='_agy_profile_run m10'", out)
        self.assertIn("alias p20='_agy_profile_run p20'", out)
        self.assertIn('_agy_profile_run()', out)
        self.assertNotIn('delete-generic-password', out)

    def test_best_profile_picks_highest_weekly_eligible(self):
        self.put('p19', make_token('p19@x.com'))
        self.put('p20', make_token('p20@x.com'))
        usage = {
            'p19': ({'gemini_5h_pct': 50.0, 'gemini_weekly_pct': 40.0, 'gemini_weekly_reset': ''}, None),
            'p20': ({'gemini_5h_pct': 20.0, 'gemini_weekly_pct': 80.0, 'gemini_weekly_reset': ''}, None),
        }
        fake = lambda pdir, retries=1: usage[os.path.basename(pdir)]
        with mock.patch.object(pool, 'fetch_usage', side_effect=fake):
            c = pool.pick_best_pro_for_transcription()
        self.assertEqual([x['profile'] for x in c], ['p20', 'p19'])
        self.assertTrue(all(x['eligible'] for x in c))

    def test_failed_usage_is_not_eligible(self):
        self.put('p19', make_token('p19@x.com'))
        self.put('p20', make_token('p20@x.com'))
        usage = {
            'p19': ({}, 'timeout'),
            'p20': ({'gemini_5h_pct': 20.0, 'gemini_weekly_pct': 10.0, 'gemini_weekly_reset': ''}, None),
        }
        fake = lambda pdir, retries=1: usage[os.path.basename(pdir)]
        with mock.patch.object(pool, 'fetch_usage', side_effect=fake):
            c = pool.pick_best_pro_for_transcription()
        self.assertEqual(c[0]['profile'], 'p20')
        self.assertFalse(c[1]['eligible'])

    def test_backup_and_restore_roundtrip(self):
        good = make_token('p19@x.com')
        d = self.put('p19', good)
        self.put('p20', make_token('p20@x.com'))
        dest = pool.cmd_backup()
        self.assertTrue(os.path.exists(os.path.join(dest, 'p19.token')))
        self.assertEqual(oct(os.stat(os.path.join(dest, 'p19.token')).st_mode & 0o777), '0o600')
        with open(pool.token_path(d), 'w') as f:  # تلف: تنسيق Keychain الخام بدل JSON
            f.write('go-keyring-base64:AAAA')
        self.assertIsNone(pool.read_token_file(d))
        pool.cmd_restore('p19')
        self.assertEqual(pool.read_token_file(d), good)

    def test_restore_without_backup_exits(self):
        self.put('p19', make_token('p19@x.com'))
        with self.assertRaises(SystemExit):
            pool.cmd_restore('p19')

    def test_run_agy_uses_devnull_stdin(self):
        import subprocess
        with mock.patch.object(pool.subprocess, 'run') as r:
            r.return_value = mock.Mock(stdout='x', stderr='', returncode=0)
            pool.run_agy('/tmp/h', ['-p', '/usage'])
            self.assertIs(r.call_args.kwargs['stdin'], subprocess.DEVNULL)
            self.assertEqual(r.call_args.kwargs['env']['HOME'], '/tmp/h')

    def test_isolated_keychain_reconciled_to_profile_token_file(self):
        pdir = os.path.join(pool.PROFILES_ROOT, 'p20')
        os.makedirs(pdir, exist_ok=True)
        kc = make_token('p20@x.com')
        with mock.patch.object(pool, 'read_profile_keychain_token', side_effect=lambda d: kc if d == pdir else None), \
             mock.patch.object(pool, 'read_keychain_token', return_value=None):
            res = pool.reconcile_keychain()
        self.assertEqual(res['status'], 'updated')
        self.assertEqual(res['profile'], 'p20')
        self.assertEqual(pool.read_token_file(pdir), kc)

    def test_sync_to_vps_skips_profiles_with_sync_false(self):
        with open(self.reg_path, 'w') as f:
            json.dump({'main': 'm10', 'profiles': {
                'm10': {'email': 'main@x.com', 'role': 'main'},
                'ram': {'email': 'ram@x.com', 'role': 'main', 'sync_to_vps': False},
            }}, f)
        self.put('m10', make_token('main@x.com'))
        self.put('ram', make_token('ram@x.com'))
        with mock.patch.object(pool.subprocess, 'run') as r:
            pool.cmd_sync_to_vps('hermes-vps')
            called_cmds = [' '.join(c.args[0]) for c in r.call_args_list]
            self.assertTrue(any('/root/.agy-profiles/m10/' in c for c in called_cmds))
            self.assertFalse(any('/root/.agy-profiles/ram/' in c for c in called_cmds))


class EmailHashTests(unittest.TestCase):
    def test_hash_is_case_and_space_insensitive(self):
        self.assertEqual(pool.email_hash(' Foo@Bar.COM '), pool.email_hash('foo@bar.com'))
        self.assertEqual(len(pool.email_hash('a@b.com')), 64)

    def test_match_plain_hash_and_missing(self):
        self.assertTrue(pool.meta_email_matches({'email': 'A@B.com'}, 'a@b.com'))
        self.assertTrue(pool.meta_email_matches({'email_sha256': pool.email_hash('a@b.com')}, 'A@B.com'))
        self.assertFalse(pool.meta_email_matches({'email_sha256': pool.email_hash('x@y.com')}, 'a@b.com'))
        self.assertFalse(pool.meta_email_matches({}, 'a@b.com'))
        self.assertFalse(pool.meta_email_matches({'email': 'a@b.com'}, None))
        self.assertTrue(pool.meta_has_email({'email_sha256': 'x'}))
        self.assertFalse(pool.meta_has_email({'role': 'main'}))

    def test_owner_found_by_hash(self):
        with tempfile.TemporaryDirectory() as d:
            reg = os.path.join(d, 'profiles.json')
            with open(reg, 'w') as f:
                json.dump({'profiles': {'hid': {'email_sha256': pool.email_hash('secret@x.com'), 'role': 'family-member'}}}, f)
            with mock.patch.object(pool, 'REGISTRY_PATH', reg):
                self.assertEqual(pool.find_owner_profile('Secret@X.com', []), 'hid')
                self.assertIsNone(pool.find_owner_profile('other@x.com', []))


if __name__ == '__main__':
    unittest.main()
