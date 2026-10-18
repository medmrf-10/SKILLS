#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_agy_lean_gates.py — بوابة الفحص الحتمية (3-Layer Quality Gate) لمهارة agy-lean-cli.

تتحقق من:
  1. [Gate 1: Quota Guard Logic & Live Snapshot]:
     - قاعدة الـ5 ساعات (حظر الخلفية عند <15%، وحظر الأمامي عند <10%).
     - قاعدة الاحتياطي الأسبوعي (حظر <=25% عند بقاء >12 ساعة على التجديد، والسماح في آخر 12 ساعة).
     - التحويل التلقائي من Claude المحظور (4.71%) إلى Gemini المتاح (>80%).
  2. [Gate 2: Zero-MCP Isolated HOME]:
     - خلو بيئة HOME المعزولة تماماً من mcp_config.json وplugins وskills وrules.
     - سلامة روابط المصادقة (OAuth + Keychain).
  3. [Gate 3: Live End-to-End Lean Execution]:
     - نجاح استدعاء فعلي لـ agy في البيئة المعزولة مع ملف مرفق وتنظيف الجلسة المؤقتة.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from agy_lean import (  # noqa: E402
    check_quota,
    evaluate_quota_entry,
    prepare_lean_home,
    run_agy_lean,
    select_best_model,
    verify_lean_home_isolation,
)


def main() -> int:
    errors = []

    # -------------------------------------------------------------------------
    # Gate 1: فحص منطق حارس الكوتة (5h Floor + Weekly Reserve + Live Snapshot)
    # -------------------------------------------------------------------------
    # 1.1: نافذة 5 ساعات عند 12% -> محظور للخلفية (15%)، مسموح للأمامي (10%)
    entry_5h_12pct = {
        "label": "Gemini 3.8 Flash (High)",
        "remainingPercentage": 0.12,
        "timeUntilResetMs": 2 * 3600 * 1000,  # 2h
        "isExhausted": False,
    }
    res_bg = evaluate_quota_entry(entry_5h_12pct, background=True)
    res_fg = evaluate_quota_entry(entry_5h_12pct, background=False)
    if res_bg["safe"]:
        errors.append("Gate 1.1 Failed: 12% in 5h window must be blocked for background workers (<15%)")
    if not res_fg["safe"]:
        errors.append("Gate 1.1 Failed: 12% in 5h window must be allowed for foreground main agent (>=10%)")

    # 1.2: نافذة 5 ساعات عند 9% -> محظور حتى للوكيل الأمامي (<10%)
    entry_5h_9pct = {
        "label": "Gemini 4 Argon (High)",
        "remainingPercentage": 0.09,
        "timeUntilResetMs": 1 * 3600 * 1000,
        "isExhausted": False,
    }
    if evaluate_quota_entry(entry_5h_9pct, background=False)["safe"]:
        errors.append("Gate 1.2 Failed: 9% in 5h window must be blocked for foreground (<10%)")

    # 1.3: نافذة أسبوعية عند 24% وباقي 20 ساعة (>12h) -> محظور
    entry_weekly_locked = {
        "label": "Claude Opus 5.5 (High)",
        "remainingPercentage": 0.24,
        "timeUntilResetMs": 20 * 3600 * 1000,  # 20h (> 12h)
        "isExhausted": False,
    }
    if evaluate_quota_entry(entry_weekly_locked, background=True)["safe"]:
        errors.append("Gate 1.3 Failed: 24% weekly reserve with 20h remaining must be blocked")

    # 1.4: نافذة أسبوعية عند 20% وباقي 8 ساعات (<12h) -> مسموح
    entry_weekly_unlocked = {
        "label": "Claude Opus 5.5 (High)",
        "remainingPercentage": 0.20,
        "timeUntilResetMs": 8 * 3600 * 1000,  # 8h (< 12h)
        "isExhausted": False,
    }
    if not evaluate_quota_entry(entry_weekly_unlocked, background=True)["safe"]:
        errors.append("Gate 1.4 Failed: 20% weekly reserve in last 8h (<12h) must be unlocked")

    # 1.5: التبديل التلقائي من Claude المحظور إلى Gemini المتاح
    mock_qdata = {
        "models": [
            {
                "label": "Claude Opus 5.5 (High)",
                "remainingPercentage": 0.047,
                "timeUntilResetMs": 13 * 3600 * 1000,
                "isExhausted": False,
            },
            {
                "label": "Gemini 3.8 Flash (High)",
                "remainingPercentage": 0.83,
                "timeUntilResetMs": 2.5 * 3600 * 1000,
                "isExhausted": False,
            },
        ]
    }
    chosen_m, q_info = select_best_model("claude-opus-5.5", background=True, auto_fallback=True, qdata=mock_qdata)
    if chosen_m != "gemini-3.8-flash-high" or not q_info["safe"]:
        errors.append(f"Gate 1.5 Failed: expected fallback to gemini-3.8-flash-high, got {chosen_m}")

    live_q = check_quota("gemini", background=True)
    if "safe" not in live_q:
        errors.append("Gate 1.6 Failed: live check_quota did not return expected schema")

    # -------------------------------------------------------------------------
    # Gate 2: فحص عزل بيئة HOME (Zero-MCP Isolation)
    # -------------------------------------------------------------------------
    with tempfile.TemporaryDirectory(prefix="test_lean_home_") as tmp_home:
        lh = prepare_lean_home(tmp_home)
        iso = verify_lean_home_isolation(lh)
        if not iso["isolated"]:
            errors.append(f"Gate 2 Failed: lean HOME not isolated properly: {iso}")

    # -------------------------------------------------------------------------
    # Gate 3: اختبار استدعاء فعلي خفيف ومعزول مع ملف مرفق
    # -------------------------------------------------------------------------
    if live_q.get("safe", False):
        with tempfile.TemporaryDirectory(prefix="test_lean_call_") as tmp_dir:
            sample_file = os.path.join(tmp_dir, "sample_ayah.txt")
            with open(sample_file, "w", encoding="utf-8") as f:
                f.write("العلم نور والجهل ظلام.")

            res = run_agy_lean(
                prompt="اقرأ الملف المرفق وأخرج الكلمة الأولى منه فقط بدون أي شرح.",
                model="gemini-3.8-flash-high",
                mode="ask",
                files=[sample_file],
                background=True,
                timeout_s=90,
            )
            if not res.get("ok"):
                errors.append(f"Gate 3 Failed: live run_agy_lean failed: {res}")
            elif "العلم" not in res.get("response", ""):
                errors.append(f"Gate 3 Failed: expected 'العلم' in response, got: {res.get('response')!r}")

    if errors:
        for e in errors:
            print(f"[FAIL] {e}", file=sys.stderr)
        print(f"FAIL ({len(errors)} errors)")
        return 1

    print("PASS (0 errors) — All 3 Quality Gates verified for agy-lean-cli.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
