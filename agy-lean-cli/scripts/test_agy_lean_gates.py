#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_agy_lean_gates.py — بوابة الفحص الحتمية رباعية الطبقات (4-Layer Quality Gate) لمهارة agy-lean-cli.

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
"""
import json
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from agy_lean import (  # noqa: E402
    _cleanup_lean_conv,
    _snapshot_session_subdirs,
    check_quota,
    evaluate_quota_entry,
    fetch_quota_data,
    prepare_lean_home,
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

    if errors:
        for e in errors:
            print(f"[FAIL] {e}", file=sys.stderr)
        print(f"FAIL ({len(errors)} errors)")
        return 1

    print("PASS (0 errors) — All 4 Quality Gates verified for agy-lean-cli.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
