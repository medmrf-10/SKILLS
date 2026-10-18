#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_agy_lean_gates.py — بوابة الفحص الحتمية خماسية الطبقات (5-Layer Quality Gate) لمهارة agy-lean-cli.

تتحقق من:
  1. [Gate 1: Dual-Window Quota Guard & Multi-Model Smart Routing]:
     - قاعدة الـ5 ساعات (حظر الخلفية عند <15%، السماح عند >=15%، وحظر الأمامي عند <10%).
     - قاعدة الاحتياطي الأسبوعي (حظر <=25% عند بقاء >12 ساعة على التجديد، والسماح في آخر 12 ساعة مع بقاء سقف الـ15%/10%).
     - الحارس المزدوج عند وجود قيدَي 5h وWeekly معاً لنفس الفئة.
     - التوجيه الذكي متعدد البدائل (Claude -> Gemini Flash -> Gemini Argon).
  2. [Gate 2: Server live_quota.json Priority & Staleness Verification]:
     - اختيار اللقطة الأحدث بين /root/workspace/ytb-build/live_quota.json و/tmp/agy_quota_snapshot.json.
     - كشف تقادم اللقطة (Staleness Check) عبر كلٍّ من mtime وحقل timestamp الداخلي، وحظر التنفيذ عند fail_on_stale=True.
  3. [Gate 3: Zero-MCP Isolated HOME & Deterministic Session/Brain/DB Cleanup]:
     - خلو بيئة HOME المعزولة من mcp_config.json وplugins وskills وrules.
     - التنظيف الحتمي الكامل لمجلدات brain/* وimplicit/<random_uuid>.pb وconversation_summaries.db*
       وjetbox_summaries_proto.pb*.tmp وملف mcp_config.json الفارغ الذي قد ينشئه agy على Linux.
  4. [Gate 4: Live End-to-End Lean Execution & Post-Call Disk Audit]:
     - نجاح استدعاء فعلي لـ agy في البيئة المعزولة مع ملفات مرفقة والتحقق من نظافة HOME المعزول بعد الاستدعاء (0 بقايا).
  5. [Gate 5: Adaptive Concurrency Throttling & Rate-Limit 429 Backoff Gate]:
     - حساب معدل استهلاك الكوتة (Burn-Rate Prediction) وتقليص العمال المتوازيين تدريجياً (مثلاً من 16 إلى 8 ثم 4 تحت 25% ثم 0 تحت 15%).
     - كشف أخطاء 429 / ResourceExhausted / QuotaExceeded وتمييزها بـ error_type="rate_limit" مع انتظار Exponential Backoff + Jitter وإعادة المحاولة الذكية.
"""
import json
import os
import sys
import tempfile
import time
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from agy_lean import (  # noqa: E402
    _cleanup_lean_conv,
    _snapshot_session_subdirs,
    check_quota,
    classify_agy_error,
    compute_quota_burn_rate_and_recommended_workers,
    compute_rate_limit_backoff,
    evaluate_quota_entry,
    fetch_quota_data,
    prepare_lean_home,
    recommend_concurrency_from_quota,
    run_agy_lean,
    select_best_model,
    verify_lean_home_isolation,
)


def main() -> int:
    errors = []

    # =========================================================================
    # Gate 1: فحص منطق حارس الكوتة المزدوج والتوجيه الذكي متعدد البدائل
    # =========================================================================
    # 1.1: نافذة 5 ساعات عند 12% -> محظور للخلفية (<15%)، مسموح للأمامي (>=10%)
    entry_5h_12pct = {
        "label": "Gemini 3.8 Flash (High)",
        "remainingPercentage": 0.12,
        "timeUntilResetMs": 2 * 3600 * 1000,
        "isExhausted": False,
    }
    if evaluate_quota_entry(entry_5h_12pct, background=True)["safe"]:
        errors.append("Gate 1.1 Failed: 12% in 5h window must be blocked for background workers (<15%)")
    if not evaluate_quota_entry(entry_5h_12pct, background=False)["safe"]:
        errors.append("Gate 1.1 Failed: 12% in 5h window must be allowed for foreground main agent (>=10%)")

    # 1.2: حد الـ15% بالضبط في نافذة الـ5 ساعات -> مسموح للخلفية (>=15%)، و9% محظور للأمامي (<10%)
    entry_5h_15pct = {
        "label": "Gemini 3.8 Flash (High)",
        "remainingPercentage": 0.15,
        "timeUntilResetMs": 2 * 3600 * 1000,
        "isExhausted": False,
    }
    if not evaluate_quota_entry(entry_5h_15pct, background=True)["safe"]:
        errors.append("Gate 1.2a Failed: exact 15% in 5h window must be allowed for background (>=15%)")

    entry_5h_9pct = {
        "label": "Gemini 4 Argon (High)",
        "remainingPercentage": 0.09,
        "timeUntilResetMs": 1 * 3600 * 1000,
        "isExhausted": False,
    }
    if evaluate_quota_entry(entry_5h_9pct, background=False)["safe"]:
        errors.append("Gate 1.2b Failed: 9% in 5h window must be blocked for foreground (<10%)")

    # 1.3: نافذة أسبوعية عند 25% بالضبط وباقي 20 ساعة (>12h) -> محظور (يشترط > 25%)، وعند 26% -> مسموح
    entry_weekly_25pct = {
        "label": "Claude Opus 5.5 (High)",
        "remainingPercentage": 0.25,
        "timeUntilResetMs": 20 * 3600 * 1000,
        "isExhausted": False,
    }
    if evaluate_quota_entry(entry_weekly_25pct, background=True)["safe"]:
        errors.append("Gate 1.3a Failed: 25% weekly reserve with 20h remaining must be blocked (requires >25%)")

    entry_weekly_26pct = {
        "label": "Claude Opus 5.5 (High)",
        "remainingPercentage": 0.26,
        "timeUntilResetMs": 20 * 3600 * 1000,
        "isExhausted": False,
    }
    if not evaluate_quota_entry(entry_weekly_26pct, background=True)["safe"]:
        errors.append("Gate 1.3b Failed: 26% weekly reserve with 20h remaining must be allowed (>25%)")

    # 1.4: نافذة أسبوعية في آخر 8 ساعات (<12h): عند 20% مسموح، وعند 12% محظور للخلفية بحارس الـ15%
    entry_weekly_unlocked_20 = {
        "label": "Claude Opus 5.5 (High)",
        "remainingPercentage": 0.20,
        "timeUntilResetMs": 8 * 3600 * 1000,
        "isExhausted": False,
    }
    if not evaluate_quota_entry(entry_weekly_unlocked_20, background=True)["safe"]:
        errors.append("Gate 1.4a Failed: 20% weekly reserve in last 8h (<12h) must be unlocked")

    entry_weekly_unlocked_12 = {
        "label": "Claude Opus 5.5 (High)",
        "remainingPercentage": 0.12,
        "timeUntilResetMs": 8 * 3600 * 1000,
        "isExhausted": False,
    }
    if evaluate_quota_entry(entry_weekly_unlocked_12, background=True)["safe"]:
        errors.append("Gate 1.4b Failed: 12% in last 8h must still be blocked for background (<15% floor)")

    # 1.5: الحارس المزدوج عند وجود قيدَي 5h وWeekly معاً لنفس النموذج
    dual_window_qdata = {
        "models": [
            {
                "label": "Gemini 3.8 Flash (High)",
                "remainingPercentage": 0.80,
                "timeUntilResetMs": 2 * 3600 * 1000,  # 5h window safe (80%)
                "isExhausted": False,
            },
            {
                "label": "Gemini 3.8 Flash (High)",
                "remainingPercentage": 0.22,
                "timeUntilResetMs": 48 * 3600 * 1000,  # Weekly window locked (22% <= 25%, 48h > 12h)
                "isExhausted": False,
            },
        ]
    }
    dual_res = check_quota("gemini-3.8-flash-high", background=True, qdata=dual_window_qdata)
    if dual_res["safe"]:
        errors.append("Gate 1.5 Failed: dual-window check must block when weekly entry violates <=25% reserve")

    # 1.6: التوجيه الذكي متعدد البدائل (Claude محظور + Flash محظور -> التحويل إلى Argon المتاح)
    multi_fallback_qdata = {
        "models": [
            {
                "label": "Claude Opus 5.5 (High)",
                "remainingPercentage": 0.047,
                "timeUntilResetMs": 13 * 3600 * 1000,
                "isExhausted": False,
            },
            {
                "label": "Gemini 3.8 Flash (High)",
                "remainingPercentage": 0.11,  # Blocked for background (<15%)
                "timeUntilResetMs": 2 * 3600 * 1000,
                "isExhausted": False,
            },
            {
                "label": "Gemini 4 Argon (High)",
                "remainingPercentage": 0.78,  # Safe (78%)
                "timeUntilResetMs": 2 * 3600 * 1000,
                "isExhausted": False,
            },
        ]
    }
    chosen_m, q_info = select_best_model(
        "claude-opus-5.5", background=True, auto_fallback=True, qdata=multi_fallback_qdata
    )
    if chosen_m != "gemini-4-argon-high" or not q_info["safe"]:
        errors.append(f"Gate 1.6 Failed: expected multi-hop fallback to gemini-4-argon-high, got {chosen_m} ({q_info})")

    # =========================================================================
    # Gate 2: فحص أولوية ملف السيرفر live_quota.json والتحقق من العمر (Staleness)
    # =========================================================================
    with tempfile.TemporaryDirectory(prefix="test_quota_snap_") as snap_dir:
        server_snap = os.path.join(snap_dir, "live_quota.json")
        local_snap = os.path.join(snap_dir, "agy_quota_snapshot.json")
        now_ts = time.time()

        # لقطة محلية قديمة (عمرها 45 دقيقة = 2700 ثانية > 1800 ثانية)
        stale_payload = {
            "timestamp": "2020-01-01T00:00:00Z",
            "models": [
                {
                    "label": "Gemini 3.8 Flash (High)",
                    "remainingPercentage": 0.55,
                    "timeUntilResetMs": 3600 * 1000,
                    "isExhausted": False,
                }
            ],
        }
        with open(local_snap, "w", encoding="utf-8") as f:
            json.dump(stale_payload, f)
        os.utime(local_snap, (now_ts - 2700, now_ts - 2700))

        # فحص كشف التقادم وحظر fail_on_stale=True عندما لا توجد إلا اللقطة القديمة (محاكاة السيرفر بدون QUOTA_BIN)
        stale_fetched = fetch_quota_data(
            refresh_live=False,
            max_cache_age_s=300.0,
            max_stale_age_s=1800.0,
            snapshot_paths=(local_snap,),
            now_ts=now_ts,
            allow_live_bin=False,
        )
        if not stale_fetched or not stale_fetched.get("_is_stale"):
            errors.append(f"Gate 2.1 Failed: expected stale snapshot to be marked _is_stale=True, got {stale_fetched}")

        stale_q = check_quota(
            "gemini-3.8-flash-high",
            background=True,
            qdata=stale_fetched,
            max_stale_age_s=1800.0,
            fail_on_stale=True,
        )
        if stale_q["safe"] or not stale_q.get("is_stale"):
            errors.append(f"Gate 2.2 Failed: fail_on_stale=True must block stale quota snapshot, got {stale_q}")

        # الآن نكتب لقطة سيرفر حديثة في live_quota.json ونتحقق من اختيارها تلقائياً
        from datetime import datetime, timezone
        fresh_iso = datetime.fromtimestamp(now_ts - 20, tz=timezone.utc).isoformat().replace("+00:00", "Z")
        fresh_payload = {
            "timestamp": fresh_iso,
            "models": [
                {
                    "label": "Gemini 3.8 Flash (High)",
                    "remainingPercentage": 0.72,
                    "timeUntilResetMs": 6900 * 1000,
                    "isExhausted": False,
                }
            ],
        }
        with open(server_snap, "w", encoding="utf-8") as f:
            json.dump(fresh_payload, f)
        os.utime(server_snap, (now_ts - 20, now_ts - 20))

        best_fetched = fetch_quota_data(
            refresh_live=False,
            max_cache_age_s=300.0,
            max_stale_age_s=1800.0,
            snapshot_paths=(server_snap, local_snap),
            now_ts=now_ts,
            allow_live_bin=False,
        )
        if (
            not best_fetched
            or best_fetched.get("_is_stale")
            or best_fetched.get("_source_path") != server_snap
        ):
            errors.append(f"Gate 2.3 Failed: expected fresh server live_quota.json to be chosen, got {best_fetched}")

    # =========================================================================
    # Gate 3: فحص عزل HOME والتنظيف الحتمي الشامل لقواعد بيانات الجلسات المؤقتة
    # =========================================================================
    with tempfile.TemporaryDirectory(prefix="test_lean_home_") as tmp_home:
        lh = prepare_lean_home(tmp_home)
        iso_before = verify_lean_home_isolation(lh)
        if not iso_before["isolated"]:
            errors.append(f"Gate 3.1 Failed: lean HOME not isolated properly before run: {iso_before}")

        pre_snap = _snapshot_session_subdirs(lh)
        cli_base = os.path.join(lh, ".gemini", "antigravity-cli")

        # محاكاة كافة مخلفات agy الواقعية على الماك ولينكس (بما فيها implicit UUID المختلف وmcp_config.json الفارغ)
        fake_conv = "11111111-2222-3333-4444-555555555555"
        fake_implicit = "99999999-aaaa-bbbb-cccc-dddddddddddd"
        os.makedirs(os.path.join(cli_base, "brain", fake_conv), exist_ok=True)
        with open(os.path.join(cli_base, "brain", fake_conv, "transcript.jsonl"), "w", encoding="utf-8") as f:
            f.write("{}\n")
        for ext in (".pb", ".db", ".db-wal", ".db-shm"):
            with open(os.path.join(cli_base, "conversations", fake_conv + ext), "w", encoding="utf-8") as f:
                f.write("x")
        with open(os.path.join(cli_base, "implicit", fake_implicit + ".pb"), "w", encoding="utf-8") as f:
            f.write("x")
        with open(os.path.join(cli_base, "log", "cli-20261018_170000.log"), "w", encoding="utf-8") as f:
            f.write("log")
        for bloat_f in (
            "conversation_summaries.db",
            "conversation_summaries.db-wal",
            "conversation_summaries.db-shm",
            "jetbox_summaries_proto.pb",
            "jetbox_summaries_proto.pb.tmp123.tmp",
            "cli.log",
            "cache/last_conversations.json",
        ):
            with open(os.path.join(cli_base, bloat_f), "w", encoding="utf-8") as f:
                f.write("bloat")
        # محاكاة إنشاء agy على Linux لملف .gemini/config/mcp_config.json فارغ
        with open(os.path.join(lh, ".gemini", "config", "mcp_config.json"), "w", encoding="utf-8") as f:
            f.write("")

        cln = _cleanup_lean_conv(lh, conv_id=fake_conv, pre_snapshot=pre_snap, sweep_all_idle=True)
        if cln["remaining_brain_count"] != 0 or cln["remaining_session_files"] != 0:
            errors.append(f"Gate 3.2 Failed: session cleanup left files behind: {cln}")

        iso_after = verify_lean_home_isolation(lh)
        if not iso_after["isolated"]:
            errors.append(f"Gate 3.3 Failed: lean HOME isolation violated after cleanup: {iso_after}")

    # =========================================================================
    # Gate 4: اختبار استدعاء فعلي خفيف ومعزول وفحص نظافة القرص بعده
    # =========================================================================
    live_q = check_quota("gemini-3.8-flash-high", background=True)
    if "safe" not in live_q:
        errors.append("Gate 4.0 Failed: live check_quota did not return expected schema")
    elif live_q.get("safe", False):
        with tempfile.TemporaryDirectory(prefix="test_lean_call_") as tmp_dir:
            sub1 = os.path.join(tmp_dir, "d1")
            sub2 = os.path.join(tmp_dir, "d2")
            os.makedirs(sub1, exist_ok=True)
            os.makedirs(sub2, exist_ok=True)
            # ملفان بنفس الاسم للتحقق من عدم التصادم + قراءة المحتوى
            f1 = os.path.join(sub1, "sample_ayah.txt")
            f2 = os.path.join(sub2, "sample_ayah.txt")
            with open(f1, "w", encoding="utf-8") as f:
                f.write("العلم نور والجهل ظلام.")
            with open(f2, "w", encoding="utf-8") as f:
                f.write("الحلم سيد الأخلاق.")

            res = run_agy_lean(
                prompt="اقرأ الملف المرفق الأول (@sample_ayah.txt) وأخرج الكلمة الأولى منه فقط بدون أي شرح.",
                model="gemini-3.8-flash-high",
                mode="ask",
                files=[f1, f2],
                background=True,
                timeout_s=90,
            )
            if not res.get("ok"):
                errors.append(f"Gate 4.1 Failed: live run_agy_lean failed: {res}")
            elif "العلم" not in res.get("response", ""):
                errors.append(f"Gate 4.2 Failed: expected 'العلم' in response, got: {res.get('response')!r}")

            cln_live = res.get("cleanup") or {}
            if cln_live.get("remaining_brain_count", -1) != 0 or cln_live.get("remaining_session_files", -1) != 0:
                errors.append(f"Gate 4.3 Failed: live run left session files in lean_home: {cln_live}")

            iso_live = verify_lean_home_isolation(res["lean_home"])
            if not iso_live.get("isolated"):
                errors.append(f"Gate 4.4 Failed: lean_home not isolated after live run: {iso_live}")

    # =========================================================================
    # Gate 5: Adaptive Concurrency Throttling & Rate-Limit 429 Backoff Gate
    # =========================================================================
    # 5.1: حساب معدل الاستهلاك (Burn-Rate) وتقليص العمال التكيفي (16 -> 8 -> 4 -> 0)
    qdata_abundant = {
        "models": [
            {
                "label": "Gemini 3.8 Flash (High)",
                "remainingPercentage": 0.75,
                "timeUntilResetMs": int(3.5 * 3600 * 1000),
                "isExhausted": False,
            }
        ]
    }
    rec_full = recommend_concurrency_from_quota(
        model_hint="gemini-3.8-flash-high", max_workers=16, background=True, qdata=qdata_abundant
    )
    if rec_full["recommended_workers"] != 16 or rec_full["throttle_level"] != "full" or not rec_full["safe"]:
        errors.append(f"Gate 5.1a Failed: expected 16 workers at 75% quota, got {rec_full}")

    qdata_moderate = {
        "models": [
            {
                "label": "Gemini 3.8 Flash (High)",
                "remainingPercentage": 0.32,
                "timeUntilResetMs": int(2.5 * 3600 * 1000),
                "isExhausted": False,
            }
        ]
    }
    rec_mod = recommend_concurrency_from_quota(
        model_hint="gemini-3.8-flash-high", max_workers=16, background=True, qdata=qdata_moderate
    )
    if rec_mod["recommended_workers"] != 8 or rec_mod["throttle_level"] != "moderate":
        errors.append(f"Gate 5.1b Failed: expected 8 workers (moderate throttle) at 32% quota, got {rec_mod}")

    # هبوط الكوتة تحت 25% (مثلاً 21%) قبل الوصول إلى جدار الـ 15% -> تقليص العمال من 16 إلى 4
    qdata_critical = {
        "models": [
            {
                "label": "Gemini 3.8 Flash (High)",
                "remainingPercentage": 0.21,
                "timeUntilResetMs": int(2.0 * 3600 * 1000),
                "isExhausted": False,
            }
        ]
    }
    rec_crit = compute_quota_burn_rate_and_recommended_workers(
        model_hint="gemini-3.8-flash-high", max_workers=16, background=True, qdata=qdata_critical
    )
    if rec_crit["recommended_workers"] != 4 or rec_crit["throttle_level"] != "critical" or not rec_crit["safe"]:
        errors.append(f"Gate 5.1c Failed: expected 4 workers when <25% (21%), got {rec_crit}")

    # هبوط الكوتة تحت 15% (مثلاً 13%) -> إيقاف العمال بالكامل (0)
    qdata_blocked = {
        "models": [
            {
                "label": "Gemini 3.8 Flash (High)",
                "remainingPercentage": 0.13,
                "timeUntilResetMs": int(1.5 * 3600 * 1000),
                "isExhausted": False,
            }
        ]
    }
    rec_blk = recommend_concurrency_from_quota(
        model_hint="gemini-3.8-flash-high", max_workers=16, background=True, qdata=qdata_blocked
    )
    if rec_blk["recommended_workers"] != 0 or rec_blk["throttle_level"] != "blocked" or rec_blk["safe"]:
        errors.append(f"Gate 5.1d Failed: expected 0 workers when <15% (13%), got {rec_blk}")

    # 5.2: تصنيف أخطاء 429 / ResourceExhausted / QuotaExceeded وعدم الخلط مع النصوص العادية
    err_429 = classify_agy_error(
        stdout_text="",
        stderr_text="Error: HTTP 429 Too Many Requests: RESOURCE_EXHAUSTED (QuotaExceeded). Retry-After: 5s",
        returncode=1,
    )
    if err_429["error_type"] != "rate_limit" or not err_429["is_rate_limit"] or err_429["retry_after_s"] != 5.0:
        errors.append(f"Gate 5.2a Failed: expected rate_limit classification with retry_after_s=5.0, got {err_429}")

    normal_ok = classify_agy_error(
        stdout_text='{"response": "الحديث رقم 429 في صحيح مسلم باب الإيمان"}',
        stderr_text="",
        returncode=0,
        resp_txt="الحديث رقم 429 في صحيح مسلم باب الإيمان",
    )
    if normal_ok["is_error"] or normal_ok["error_type"] is not None:
        errors.append(f"Gate 5.2b Failed: normal Arabic response containing number 429 must not be flagged as error: {normal_ok}")

    # 5.3: فحص Exponential Backoff + Jitter وإعادة المحاولة الذكية داخل run_agy_lean
    b1 = compute_rate_limit_backoff(1, base_delay_s=2.0, max_delay_s=30.0, jitter_ratio=0.25)
    b2 = compute_rate_limit_backoff(2, base_delay_s=2.0, max_delay_s=30.0, jitter_ratio=0.25)
    b3 = compute_rate_limit_backoff(3, base_delay_s=2.0, max_delay_s=30.0, jitter_ratio=0.25)
    if not (2.0 < b1 < b2 < b3 <= 30.0):
        errors.append(f"Gate 5.3a Failed: backoff delays not strictly increasing with jitter: b1={b1}, b2={b2}, b3={b3}")

    # محاكاة تعافي run_agy_lean بعد خطأَي 429 متتاليين ثم نجاح في المحاولة الثالثة
    recorded_sleeps = []
    call_counter = {"n": 0}

    def fake_runner_recover(cmd, **kwargs):
        call_counter["n"] += 1
        if call_counter["n"] == 1:
            return SimpleNamespace(
                returncode=1,
                stdout="",
                stderr="google.api_core.exceptions.ResourceExhausted: 429 QuotaExceeded",
            )
        if call_counter["n"] == 2:
            return SimpleNamespace(
                returncode=1,
                stdout="",
                stderr="Error 429: RESOURCE_EXHAUSTED — rateLimitExceeded",
            )
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"response": "نجاح بعد التراجع الأسي", "conversation_id": "fake-conv-1"}),
            stderr="",
        )

    res_recover = run_agy_lean(
        prompt="اختبار التعافي من 429",
        model="gemini-3.8-flash-high",
        background=True,
        qdata=qdata_abundant,
        max_retries=3,
        backoff_base_s=1.5,
        backoff_max_s=20.0,
        sleep_fn=lambda s: recorded_sleeps.append(s),
        runner_fn=fake_runner_recover,
    )
    if (
        not res_recover.get("ok")
        or res_recover.get("attempts") != 3
        or not res_recover.get("retried_rate_limit")
        or len(recorded_sleeps) != 2
        or not (recorded_sleeps[0] < recorded_sleeps[1])
        or res_recover.get("error_type") is not None
    ):
        errors.append(f"Gate 5.3b Failed: expected recovery on attempt 3 with 2 backoff sleeps, got {res_recover}, sleeps={recorded_sleeps}")

    # محاكاة فشل مستمر بـ 429 حتى استنفاد المحاولات والتأكد من إرجاع error_type="rate_limit"
    exhaust_sleeps = []

    def fake_runner_always_429(cmd, **kwargs):
        return SimpleNamespace(
            returncode=1,
            stdout="",
            stderr="HTTP 429 Too Many Requests: RESOURCE_EXHAUSTED",
        )

    res_exhaust = run_agy_lean(
        prompt="اختبار استنفاد محاولات 429",
        model="gemini-3.8-flash-high",
        background=True,
        qdata=qdata_abundant,
        max_retries=2,
        backoff_base_s=1.0,
        backoff_max_s=10.0,
        sleep_fn=lambda s: exhaust_sleeps.append(s),
        runner_fn=fake_runner_always_429,
    )
    if (
        res_exhaust.get("ok")
        or res_exhaust.get("error_type") != "rate_limit"
        or res_exhaust.get("attempts") != 3
        or len(exhaust_sleeps) != 2
    ):
        errors.append(f"Gate 5.3c Failed: expected error_type='rate_limit' after 3 attempts, got {res_exhaust}")

    if errors:
        for e in errors:
            print(f"[FAIL] {e}", file=sys.stderr)
        print(f"FAIL ({len(errors)} errors)")
        return 1

    print("PASS (0 errors) — All 5 Quality Gates verified for agy-lean-cli.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
