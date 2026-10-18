#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_improver_gates.py — بوابة الفحص الحتمية الرباعية (4-Layer Quality Gate) لمهارة continuous-skill-improver v1.0.

تتحقق من:
- Gate 1: سلامة تدوير الدور (Round-Robin State Rotation) عبر المهارات الـ 9 وتوليد تكليف الوكيل الفرعي (generate_subagent_prompt).
- Gate 2 (Anti-Deception Watchdog Gate): كشف حالة الخداع الواقعية بنسبة 100% (completed_series_this_run=15 مع new_txts_last_30m=0، أو خطأ $HOME is not defined في اللوج، أو غياب HOME=/root من ملف .service، أو درس محاذاة < 95.0%).
- Gate 3: وجود وسلامة جميع المهارات الـ 9 وملفات SKILL.md وبوابات الاختبار test_*_gates.py في /Users/macm1pro/REPOS/SKILLS/.
- Gate 4: تكامل CONTINUOUS_IMPROVEMENT_STATE.json و CONTINUOUS_IMPROVEMENT_LOG.md.
"""

from __future__ import annotations

import copy
import sys
import pathlib

SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
SKILL_ROOT = SCRIPT_DIR.parent
SKILLS_REPO_ROOT = SKILL_ROOT.parent

sys.path.insert(0, str(SCRIPT_DIR))

from manage_improvement_loop import (  # noqa: E402
    CANONICAL_9_SKILLS,
    SKILL_GATE_MAP,
    advance_cycle_state,
    audit_mac_alignment_state,
    detect_fake_progress_or_env_failure,
    ensure_9_skills_in_state,
    generate_subagent_prompt,
    get_next_skill_info,
    verify_skills_repository_integrity,
    verify_state_and_log_integrity,
)


def gate1_round_robin_and_prompt() -> list[str]:
    errors: list[str] = []
    if len(CANONICAL_9_SKILLS) != 9:
        errors.append(f"Expected 9 canonical skills, found {len(CANONICAL_9_SKILLS)}")

    if "continuous-skill-improver" not in CANONICAL_9_SKILLS:
        errors.append("continuous-skill-improver missing from CANONICAL_9_SKILLS")

    # فحص ترقية حالة قديمة من 8 مهارات إلى 9 مهارات وتدويرها دورة كاملة
    mock_state = {
        "loop_version": "2.0-subagent-driven",
        "cycle_count": 14,
        "next_skill_index": 7,
        "last_improved_skill": "person-to-knowledge-orchestrator",
        "priority_backlog": [
            {
                "skill": "sheikh-series-pipeline",
                "issue_id": "ALIGN-ONSET-BREATH-JUMP",
                "title": "القفز المبكر لبداية الكلمة التالية أثناء أخذ الشيخ نفساً عميقاً",
                "constraint": "يُطبَّق الحل على المحاذاة القادمة فقط؛ يُمنع تعديل أو إعادة محاذاة الملفات المنجزة سابقاً.",
            }
        ],
        "skills_rotation": CANONICAL_9_SKILLS[:8],
    }
    ensure_9_skills_in_state(mock_state)
    if len(mock_state["skills_rotation"]) != 9:
        errors.append("ensure_9_skills_in_state failed to append 9th skill")

    idx, sk_name, gate_rel, _ = get_next_skill_info(mock_state)
    if idx != 7 or sk_name != "agy-lean-cli":
        errors.append(f"Expected index 7 (agy-lean-cli), got index={idx} ({sk_name})")

    # اختبار توليد Prompt للوكيل الفرعي
    prompt = generate_subagent_prompt(mock_state, SKILLS_REPO_ROOT)
    required_phrases = [
        "الدورة 15",
        "agy-lean-cli",
        "أمر واحد فقط",
        "&&",
        "completed_series_this_run",
        'Environment="HOME=/root"',
        "$HOME is not defined",
        "new_txts_last_30m",
        "95.0%",
        "ALIGN-ONSET-BREATH-JUMP",
        "PASS (0 errors)",
    ]
    for phrase in required_phrases:
        if phrase not in prompt:
            errors.append(f"Subagent prompt missing required directive phrase: {phrase!r}")

    # اختبار التدوير الكامل عبر 9 خطوات متتالية
    rot_state = copy.deepcopy(mock_state)
    rot_state["next_skill_index"] = 0
    visited: list[str] = []
    for step in range(9):
        _, cur_sk, _, _ = get_next_skill_info(rot_state)
        visited.append(cur_sk)
        advance_cycle_state(rot_state, skill_tested=cur_sk, bugs_fixed=1)

    if visited != CANONICAL_9_SKILLS:
        errors.append(f"9-step rotation order mismatch: {visited} != {CANONICAL_9_SKILLS}")
    if rot_state["next_skill_index"] != 0:
        errors.append(f"Expected wrap-around to index 0 after 9 cycles, got {rot_state['next_skill_index']}")

    return errors


def gate2_anti_deception_watchdog() -> list[str]:
    errors: list[str] = []

    # الحالة 1: واقعة الخداع الفعلية (completed_series_this_run=15 مع new_txts_last_30m=0 و chunks_ok=0)
    deception_res = detect_fake_progress_or_env_failure(
        log_text="[2026-10-18] Starting series ayman__s004...\n[2026-10-18] Finished series loop.\n",
        state_dict={"completed_series_this_run": 15, "total_series": 71},
        new_txts_last_30m=0,
    )
    if deception_res["healthy"] or not deception_res["fake_progress_detected"]:
        errors.append("Failed to detect fake progress when completed_series_this_run=15 and new_txts_last_30m=0")
    if "FAKE_PROGRESS_COUNTER_DECEPTION" not in deception_res["issues"]:
        errors.append("FAKE_PROGRESS_COUNTER_DECEPTION missing from issues list")

    # الحالة 2: خطأ $HOME is not defined في اللوج الحي
    home_err_log = (
        "[19:10:01] Running agy worker on chunk 001...\n"
        "Fatal Error: $HOME is not defined\n"
        "[✗ فشل] فشل المقطع 1/4\n"
    )
    home_res = detect_fake_progress_or_env_failure(
        log_text=home_err_log,
        state_dict={"completed_series_this_run": 3},
        new_txts_last_30m=0,
    )
    if home_res["healthy"] or not home_res["has_home_env_error"]:
        errors.append("Failed to detect Fatal Error: $HOME is not defined in log")
    if "LOG_HOME_NOT_DEFINED_ERROR" not in home_res["issues"]:
        errors.append("LOG_HOME_NOT_DEFINED_ERROR missing from issues list")
    if not home_res["remediation_commands"]:
        errors.append("No remediation commands returned for $HOME error")

    # الحالة 3: غياب HOME=/root من ملف وحدة systemd
    bad_unit = "[Unit]\nDescription=Smallest First Transcriber\n[Service]\nExecStart=/usr/bin/python3 /root/run.py\n"
    unit_res = detect_fake_progress_or_env_failure(
        log_text="[✓ تم] 001_abc.txt\n",
        state_dict={"completed_series_this_run": 1},
        new_txts_last_30m=2,
        unit_text=bad_unit,
    )
    if unit_res["healthy"] or not unit_res["missing_systemd_home_env"]:
        errors.append("Failed to detect missing Environment=\"HOME=/root\" in systemd unit text")
    if "MISSING_SYSTEMD_HOME_ENV" not in unit_res["issues"]:
        errors.append("MISSING_SYSTEMD_HOME_ENV missing from issues list")

    # الحالة 4: حالة الإنتاج السليمة الحقيقية
    good_unit = (
        "[Unit]\nDescription=Smallest First Transcriber\n[Service]\n"
        'User=root\nEnvironment="HOME=/root"\nExecStart=/usr/bin/python3 /root/run.py\n'
    )
    good_log = (
        "[20:15:00] ✓ المقطع 1/2 (1240 كلمة)\n"
        "[20:16:10] ✓ المقطع 2/2 (1180 كلمة)\n"
        "[20:16:12] [✓ تم] 002_mD2uoA578qo.txt (2420 words, 118 WPM)\n"
    )
    good_res = detect_fake_progress_or_env_failure(
        log_text=good_log,
        state_dict={"completed_series_this_run": 15},
        new_txts_last_30m=4,
        unit_text=good_unit,
    )
    if not good_res["healthy"] or good_res["issues"]:
        errors.append(f"False positive in healthy production state: {good_res}")

    # الحالة 5: فحص محاذاة الماك وكشف الدروس ذات المطابقة < 95.0%
    mac_low = audit_mac_alignment_state(
        mac_state_dict={
            "completed_count": 660,
            "speedup_vs_realtime": 44.8,
            "last_completed": "test_sheikh__s001__001_xyz",
            "last_match_rate": 91.4,
        }
    )
    if mac_low["healthy"] or not mac_low["investigation_required"]:
        errors.append("audit_mac_alignment_state failed to flag lesson with match_rate=91.4% (< 95.0%)")
    if "ALIGN-ONSET-BREATH-JUMP" not in mac_low.get("onset_breath_rule", ""):
        errors.append("audit_mac_alignment_state missing ALIGN-ONSET-BREATH-JUMP rule")

    return errors


def gate3_skills_repository_integrity() -> list[str]:
    errors: list[str] = []
    rep = verify_skills_repository_integrity(SKILLS_REPO_ROOT)
    if not rep["healthy"]:
        errors.append(
            f"Repository integrity check failed: missing_skills={rep['missing_skills']}, "
            f"missing_mds={rep['missing_skill_mds']}, missing_gates={rep['missing_gates']}"
        )

    ref_doc = SKILL_ROOT / "references" / "01-subagent-loop-and-watchdog-protocol.md"
    if not ref_doc.is_file() or ref_doc.stat().st_size < 500:
        errors.append(f"Reference protocol doc missing or too small: {ref_doc}")

    for sk, gate_rel in SKILL_GATE_MAP.items():
        gate_path = SKILLS_REPO_ROOT / gate_rel
        if not gate_path.is_file():
            errors.append(f"Missing gate script for {sk}: {gate_path}")

    return errors


def gate4_state_and_log_sync() -> list[str]:
    errors: list[str] = []
    res = verify_state_and_log_integrity(
        SKILLS_REPO_ROOT / "CONTINUOUS_IMPROVEMENT_STATE.json",
        SKILLS_REPO_ROOT / "CONTINUOUS_IMPROVEMENT_LOG.md",
    )
    if not res["healthy"]:
        errors.extend(res["errors"])
    if res.get("rotation_count", 0) < 9:
        errors.append(f"Expected at least 9 skills in CONTINUOUS_IMPROVEMENT_STATE.json, got {res.get('rotation_count')}")
    return errors


def main() -> int:
    gates = [
        ("Gate 1: Round-Robin State Rotation & Subagent Prompt Generation", gate1_round_robin_and_prompt),
        ("Gate 2: Anti-Deception Watchdog (Fake Counter, $HOME Error & <95% Align)", gate2_anti_deception_watchdog),
        ("Gate 3: All 9 Skills & Gate Scripts Integrity", gate3_skills_repository_integrity),
        ("Gate 4: CONTINUOUS_IMPROVEMENT_STATE.json & LOG Synchronization", gate4_state_and_log_sync),
    ]

    total_errors: list[str] = []
    print("=" * 78)
    print("RUNNING continuous-skill-improver v1.0 DETERMINISTIC 4-LAYER QUALITY GATES")
    print("=" * 78)

    for title, fn in gates:
        errs = fn()
        status = "PASS" if not errs else f"FAIL ({len(errs)} errors)"
        print(f"[{status}] {title}")
        for e in errs:
            print(f"   - ERROR: {e}")
        total_errors.extend(errs)

    print("-" * 78)
    if total_errors:
        print(f"FINAL RESULT: FAIL ({len(total_errors)} errors)")
        return 1

    print("FINAL RESULT: PASS (0 errors)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
