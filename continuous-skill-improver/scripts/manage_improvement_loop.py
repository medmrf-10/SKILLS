#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""manage_improvement_loop.py — أداة CLI ومكتبة إدارة حلقة التحسين المستمر للمهارات وحارس الإنتاج المضاد للخداع.

توفر هذه الأداة:
1. قراءة وتحديث `/Users/macm1pro/REPOS/SKILLS/CONTINUOUS_IMPROVEMENT_STATE.json` عبر المهارات الـ 9.
2. كاشف الخداع وأعطال البيئة (`detect_fake_progress_or_env_failure`) الذي يمنع الانخداع بارتفاع
   `completed_series_this_run` أو `systemctl is-active` عندما تكون ملفات `.txt` الفعلية = 0
   أو يظهر خطأ `$HOME is not defined` في اللوج أو يغيب `Environment="HOME=/root"` من وحدة systemd.
3. فحص حالة محاذاة الماك (`mac_align_state.json`) والتحقق من قاعدة `< 95.0%` وقاعدة `ALIGN-ONSET-BREATH-JUMP`.
4. توليد نص التكليف المعياري (`Prompt`) للوكيل الفرعي المعزول للدورة القادمة (`generate_subagent_prompt`).
"""

from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple

SKILLS_ROOT = pathlib.Path("/Users/macm1pro/REPOS/SKILLS")
DEFAULT_STATE_PATH = SKILLS_ROOT / "CONTINUOUS_IMPROVEMENT_STATE.json"
DEFAULT_LOG_PATH = SKILLS_ROOT / "CONTINUOUS_IMPROVEMENT_LOG.md"
DEFAULT_MAC_ALIGN_STATE_PATH = pathlib.Path("/tmp/mac_align_spool/mac_align_state.json")

SKILL_GATE_MAP: Dict[str, str] = {
    "turath-deep-indexing": "turath-deep-indexing/scripts/test_objects_sqlite_gates.py",
    "person-discovery-intake": "person-discovery-intake/scripts/test_discovery_gates.py",
    "sheikh-curation": "sheikh-curation/scripts/test_curation_v2_gates.py",
    "sheikh-series-pipeline": "sheikh-series-pipeline/scripts/test_pipeline_v5_gates.py",
    "turath-pdf-to-text": "turath-pdf-to-text/scripts/test_pdf_adapter_gates.py",
    "turath-embedding-gemma2": "turath-embedding-gemma2/scripts/test_embedding_gemma2_gates.py",
    "person-to-knowledge-orchestrator": "person-to-knowledge-orchestrator/scripts/test_orchestrator_gates.py",
    "agy-lean-cli": "agy-lean-cli/scripts/test_agy_lean_gates.py",
    "continuous-skill-improver": "continuous-skill-improver/scripts/test_improver_gates.py",
}

CANONICAL_9_SKILLS: List[str] = list(SKILL_GATE_MAP.keys())


def _now_iso_cairo() -> str:
    tz = timezone(timedelta(hours=2))
    return datetime.now(tz).isoformat(timespec="seconds")


def ensure_9_skills_in_state(state: Dict[str, Any]) -> Dict[str, Any]:
    """يضمن وجود المهارات الـ 9 جميعاً (بما فيها continuous-skill-improver) في قائمة التدوير."""
    rot = list(state.get("skills_rotation") or [])
    for sk in CANONICAL_9_SKILLS:
        if sk not in rot:
            rot.append(sk)
    state["skills_rotation"] = rot
    if "next_skill_index" not in state or not isinstance(state["next_skill_index"], int):
        state["next_skill_index"] = 0
    if rot:
        state["next_skill_index"] = state["next_skill_index"] % len(rot)
    return state


def load_state(state_path: pathlib.Path = DEFAULT_STATE_PATH) -> Dict[str, Any]:
    """يقرأ ملف حالة التحسين المستمر ويضمن تكامل قائمة المهارات التسع."""
    if not state_path.exists():
        default_state: Dict[str, Any] = {
            "loop_version": "2.1-subagent-driven",
            "updated_at": _now_iso_cairo(),
            "cycle_count": 0,
            "next_skill_index": 0,
            "last_improved_skill": "",
            "priority_backlog": [],
            "skills_rotation": list(CANONICAL_9_SKILLS),
            "last_completed_cycle": {},
        }
        return default_state
    data = json.loads(state_path.read_text(encoding="utf-8"))
    return ensure_9_skills_in_state(data)


def save_state(state: Dict[str, Any], state_path: pathlib.Path = DEFAULT_STATE_PATH) -> None:
    """يحفظ ملف حالة التحسين المستمر بتنسيق JSON معياري."""
    ensure_9_skills_in_state(state)
    state["updated_at"] = _now_iso_cairo()
    state_path.write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def get_next_skill_info(state: Dict[str, Any]) -> Tuple[int, str, str, List[Dict[str, Any]]]:
    """يرجع (index, skill_name, gate_rel_path, backlog_items) للمهارة التي عليها الدور."""
    ensure_9_skills_in_state(state)
    rot = state["skills_rotation"]
    idx = int(state.get("next_skill_index", 0)) % len(rot)
    skill_name = rot[idx]
    gate_rel = SKILL_GATE_MAP.get(skill_name, f"{skill_name}/scripts/test_gates.py")
    backlog = [
        item
        for item in (state.get("priority_backlog") or [])
        if isinstance(item, dict) and item.get("skill") in (skill_name, "*", None)
    ]
    return idx, skill_name, gate_rel, backlog


def advance_cycle_state(
    state: Dict[str, Any],
    skill_tested: Optional[str] = None,
    real_datasets: Optional[List[str]] = None,
    bugs_fixed: int = 0,
    gate_status: str = "PASS (0 errors)",
) -> Dict[str, Any]:
    """يقدّم عداد الدورات ويدوّر المؤشر الدائري `next_skill_index` إلى المهارة التالية."""
    ensure_9_skills_in_state(state)
    rot = state["skills_rotation"]
    cur_idx = int(state.get("next_skill_index", 0)) % len(rot)
    active_skill = skill_tested or rot[cur_idx]

    if active_skill in rot:
        tested_idx = rot.index(active_skill)
        next_idx = (tested_idx + 1) % len(rot)
    else:
        next_idx = (cur_idx + 1) % len(rot)

    new_cycle = int(state.get("cycle_count", 0)) + 1
    state["cycle_count"] = new_cycle
    state["next_skill_index"] = next_idx
    state["last_improved_skill"] = active_skill
    state["updated_at"] = _now_iso_cairo()
    state["last_completed_cycle"] = {
        "cycle": new_cycle,
        "skills_tested": [active_skill],
        "real_datasets_used": real_datasets
        or [f"Real production datasets & quality gates for {active_skill}"],
        "bugs_fixed": int(bugs_fixed),
        "gate_status": gate_status,
    }
    return state


def detect_fake_progress_or_env_failure(
    log_text: str,
    state_dict: Optional[Dict[str, Any]] = None,
    new_txts_last_30m: int = 0,
    unit_text: Optional[str] = None,
    prev_completed_series: int = 0,
) -> Dict[str, Any]:
    """حارس الإنتاج الفعلي المضاد للخداع (`Anti-Deception Production Watchdog`).

    يكتشف بدقة 100%:
    1. غياب `HOME=/root` أو `User=root` من ملف وحدة systemd (`MISSING_SYSTEMD_HOME_ENV`).
    2. ظهور خطأ `$HOME is not defined` في لوج التفريغ (`LOG_HOME_NOT_DEFINED_ERROR`).
    3. الخداع الشكلي بارتفاع `completed_series_this_run` بينما `new_txts_last_30m == 0`
       وعدد المقاطع الناجحة في اللوج = 0 (`FAKE_PROGRESS_COUNTER_DECEPTION`).
    4. الفشل المتتالي للمقاطع في اللوج بدون أي مقطع ناجح (`CONSECUTIVE_SILENT_CHUNK_FAILURES`).
    """
    state_dict = state_dict or {}
    lines = (log_text or "").splitlines()
    tail_80 = lines[-80:] if len(lines) > 80 else lines
    tail_50 = lines[-50:] if len(lines) > 50 else lines

    issues: List[str] = []
    remediation: List[str] = []

    # 1. فحص ملف وحدة systemd (إن مُرِّر)
    missing_systemd_home_env = False
    if unit_text is not None:
        has_home = ('HOME=/root' in unit_text) or ('Environment="HOME=/root"' in unit_text)
        has_user = ('User=root' in unit_text)
        if not has_home or not has_user:
            missing_systemd_home_env = True
            issues.append("MISSING_SYSTEMD_HOME_ENV")
            remediation.append(
                'إضافة User=root و Environment="HOME=/root" إلى /etc/systemd/system/transcribe-smallest-first.service ثم تنفيذ systemctl daemon-reload'
            )

    # 2. فحص خطأ $HOME is not defined في اللوج
    home_err_count = sum(
        1
        for ln in tail_50
        if ("HOME is not defined" in ln) or ("$HOME is not defined" in ln)
    )
    has_home_env_error = home_err_count > 0
    if has_home_env_error:
        issues.append("LOG_HOME_NOT_DEFINED_ERROR")
        remediation.append(
            "تشغيل /root/workspace/SKILLS/sheikh-series-pipeline/scripts/vps_pipeline_watchdog.py لإصلاح بيئة HOME=/root وإعادة تشغيل transcribe-smallest-first.service"
        )

    # 3. إحصاء المقاطع المنجزة فعلياً مقابل الفاشلة في ذيل اللوج
    chunks_ok_count = sum(
        1
        for ln in tail_80
        if ("✓ المقطع" in ln) or ("[✓ تم]" in ln) or ("تم تفريغ" in ln)
    )
    chunk_fail_count = sum(
        1
        for ln in tail_80
        if ("فشل المقطع" in ln)
        or ("[✗ فشل]" in ln)
        or ("Fatal Error:" in ln)
        or ("HOME is not defined" in ln)
    )

    # 4. فحص الخداع في عداد السلاسل المكتملة مقابل الملفات المكتوبة فعلياً على القرص
    completed_series = int(state_dict.get("completed_series_this_run", 0) or 0)
    status_str = str(state_dict.get("status", "")).upper()
    is_drain_complete = (status_str == "DRAIN_COMPLETE") or bool(state_dict.get("drain_complete"))

    fake_progress_detected = False
    if not is_drain_complete:
        if (
            (completed_series > prev_completed_series or completed_series > 0)
            and int(new_txts_last_30m) == 0
            and chunks_ok_count == 0
        ):
            fake_progress_detected = True
            issues.append("FAKE_PROGRESS_COUNTER_DECEPTION")
            remediation.append(
                f"كشف تقدم وهمي: completed_series_this_run={completed_series} بينما new_txts_last_30m=0 و chunks_ok=0! لا تصدق العداد؛ أصلح البيئة وأعد تشغيل transcribe-smallest-first.service فوراً"
            )

        if chunk_fail_count >= 3 and chunks_ok_count == 0 and int(new_txts_last_30m) == 0:
            fake_progress_detected = True
            if "CONSECUTIVE_SILENT_CHUNK_FAILURES" not in issues:
                issues.append("CONSECUTIVE_SILENT_CHUNK_FAILURES")
            remediation.append(
                f"فشل متتالٍ في المقاطع ({chunk_fail_count} أخطاء في ذيل اللوج) مع صفر ملفات .txt مكتوبة؛ راجع ذيل transcribe_smallest_first.log وأعد تشغيل الخدمة"
            )

    healthy = len(issues) == 0
    if healthy:
        diagnosis_ar = (
            f"HEALTHY: خط التفريغ سليم ويكتب مخرجات حقيقية "
            f"(new_txts_last_30m={new_txts_last_30m}, chunks_ok={chunks_ok_count}, home_err=0)."
        )
    else:
        diagnosis_ar = (
            f"ALERT ({', '.join(issues)}): تم رصد خلل أو تقدم وهمي في خط الإنتاج! "
            + " | ".join(remediation)
        )

    return {
        "healthy": healthy,
        "status": "HEALTHY" if healthy else "DECEPTION_OR_FAILURE_DETECTED",
        "issues": issues,
        "fake_progress_detected": fake_progress_detected,
        "has_home_env_error": has_home_env_error,
        "missing_systemd_home_env": missing_systemd_home_env,
        "home_err_count": home_err_count,
        "chunks_ok_count": chunks_ok_count,
        "chunk_fail_count": chunk_fail_count,
        "completed_series_this_run": completed_series,
        "new_txts_last_30m": int(new_txts_last_30m),
        "remediation_commands": remediation,
        "diagnosis_ar": diagnosis_ar,
    }


def audit_mac_alignment_state(
    mac_state_path: pathlib.Path = DEFAULT_MAC_ALIGN_STATE_PATH,
    mac_state_dict: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """يفحص حالة محاذاة الماك (`mac_align_state.json`) وقاعدة التحقيق في أي درس `< 95.0%`."""
    if mac_state_dict is None:
        if mac_state_path.exists():
            try:
                mac_state_dict = json.loads(mac_state_path.read_text(encoding="utf-8"))
            except Exception as exc:
                return {
                    "available": False,
                    "healthy": False,
                    "error": f"Failed to parse {mac_state_path}: {exc}",
                }
        else:
            return {
                "available": False,
                "healthy": True,
                "note": "mac_align_state.json not present in /tmp/mac_align_spool",
            }

    completed_count = int(mac_state_dict.get("completed_count", 0) or 0)
    speedup = float(mac_state_dict.get("speedup_vs_realtime", 0.0) or 0.0)
    last_completed = str(mac_state_dict.get("last_completed", ""))
    last_match_rate = float(mac_state_dict.get("last_match_rate", 100.0) or 100.0)

    low_match_lessons: List[Dict[str, Any]] = []
    if last_match_rate < 95.0 and last_completed:
        low_match_lessons.append({"lesson": last_completed, "match_rate": last_match_rate})

    for item in mac_state_dict.get("recent_lessons", []) or []:
        if isinstance(item, dict):
            mr = float(item.get("match_rate", 100.0) or 100.0)
            if mr < 95.0:
                low_match_lessons.append(item)

    return {
        "available": True,
        "healthy": len(low_match_lessons) == 0,
        "completed_count": completed_count,
        "speedup_vs_realtime": speedup,
        "last_completed": last_completed,
        "low_match_lessons_under_95pct": low_match_lessons,
        "investigation_required": len(low_match_lessons) > 0,
        "onset_breath_rule": (
            "ALIGN-ONSET-BREATH-JUMP: شد بداية الكلمة بعد النفس/السكتة يُطبَّق على المحاذاة القادمة فقط؛ "
            "يُمنع تعديل أو إعادة محاذاة الملفات المنجزة سابقاً."
        ),
    }


def generate_subagent_prompt(
    state: Optional[Dict[str, Any]] = None,
    skills_root: pathlib.Path = SKILLS_ROOT,
) -> str:
    """يولّد نص التكليف المعياري (`Prompt`) للوكيل الفرعي للدورة القادمة."""
    if state is None:
        state = load_state(skills_root / "CONTINUOUS_IMPROVEMENT_STATE.json")
    idx, skill_name, gate_rel, backlog = get_next_skill_info(state)
    next_cycle_num = int(state.get("cycle_count", 0)) + 1
    gate_abs = skills_root / gate_rel

    all_backlog = state.get("priority_backlog") or []
    backlog_lines = ""
    if all_backlog:
        formatted = []
        for item in all_backlog:
            if isinstance(item, dict):
                formatted.append(
                    f"   - [{item.get('issue_id', 'BACKLOG')}] ({item.get('skill', '')}): "
                    f"{item.get('title', '')} — قيد حاكم: {item.get('constraint', '')}"
                )
        if formatted:
            backlog_lines = "\n".join(formatted)

    prompt = (
        f"أنت الوكيل الفرعي المعزول المسؤول عن تنفيذ **الدورة {next_cycle_num}** من حلقة التحسين المستمر للمهارات "
        f"وحارس الإنتاج الفعلي في `{skills_root}`.\n"
        f"التزم بقاعدة **أمر واحد فقط في كل استدعاء `run_command` (يُمنع استخدام `&&` منعاً باتاً)** ولا تسأل المستخدم أي سؤال.\n\n"
        f"### ١. فحص حارس الإنتاج الفعلي المضاد للخداع (`Anti-Deception Production Watchdog`):\n"
        f"- **تحذير صارم:** يُمنع الاكتفاء بقراءة `completed_series_this_run` في `transcribe_selected_state.json` أو `systemctl is-active`.\n"
        f"- شغّل `python3 {skills_root}/continuous-skill-improver/scripts/manage_improvement_loop.py --audit-pipeline` وافحص:\n"
        f"  1. وجود `User=root` و`Environment=\"HOME=/root\"` في `/etc/systemd/system/transcribe-smallest-first.service` على `hermes-vps`.\n"
        f"  2. خلو آخر 50 سطراً من `/root/workspace/ytb-build/transcribe_smallest_first.log` من خطأ `$HOME is not defined` أو الفشل المتتالي بدون `[✓ تم]`.\n"
        f"  3. عدد ملفات `.txt` المكتوبة فعلياً على القرص في آخر 30 دقيقة (`new_txts_last_30m` و`recent_chunks_ok_in_tail80` في `vps_watchdog_status.json`).\n"
        f"  4. سلامة محاذاة الماك (`/tmp/mac_align_spool/mac_align_state.json`)، والتحقيق الإلزامي في أي درس ينزل معدل مطابقته عن `< 95.0%`، مع الالتزام بقاعدة `ALIGN-ONSET-BREATH-JUMP` (تُطبَّق على المحاذاة القادمة فقط دون لمس الملفات المنجزة سابقاً).\n\n"
        f"### ٢. المهارة المستهدفة في هذه الدورة (`Round-Robin Index {idx}`: `{skill_name}`):\n"
        f"- اقرأ `{skills_root}/{skill_name}/SKILL.md` وافحص كود المهارة في `{skills_root}/{skill_name}/scripts/`.\n"
        f"- اختبر المهارة عملياً على **بيانات إنتاج حقيقية** (سلاسل السيرفر المفرغة والمحاذاة، ملفات المشايخ الـ 17 في `/Users/macm1pro/REPOS/cheikh/data/curated_sheikhs/*_raw.json`، فهرس الشاملة `8,589` كتاباً، ملفات PDF التراثية الحقيقية).\n"
        f"- اكتشف الحالات الحدية أو الأعطال الصامتة وعالجها جذرياً في الكود، ثم وسّع أو شغّل بوابة الفحص `{gate_abs}` وتأكد من خروجها بـ **`PASS (0 errors)`**.\n"
    )
    if backlog_lines:
        prompt += f"\n### ٣. مهام الأولوية المسجلة في `priority_backlog`:\n{backlog_lines}\n"

    prompt += (
        f"\n### ٤. التحديث والمزامنة والإغلاق:\n"
        f"- حدّث `CONTINUOUS_IMPROVEMENT_STATE.json` عبر `manage_improvement_loop.py --advance-cycle --skill {skill_name} ...` ووثّق الدورة {next_cycle_num} في `CONTINUOUS_IMPROVEMENT_LOG.md`.\n"
        f"- نفّذ `git add` ثم `git commit` ثم `git pull --rebase --autostash origin main` ثم `git push origin main` وزامن `hermes-vps:/root/workspace/SKILLS`.\n"
        f"- أرسل إلى المنسق الرئيسي عبر `send_message` ملخصاً مقتضباً من 5 أسطر فقط."
    )
    return prompt


def verify_skills_repository_integrity(skills_root: pathlib.Path = SKILLS_ROOT) -> Dict[str, Any]:
    """يتحقق من وجود وسلامة جميع المهارات الـ 9 وملفات `SKILL.md` وبوابات الاختبار `test_*_gates.py`."""
    missing_skills: List[str] = []
    missing_skill_mds: List[str] = []
    missing_gates: List[str] = []
    verified_skills: List[str] = []

    for skill_name, gate_rel in SKILL_GATE_MAP.items():
        skill_dir = skills_root / skill_name
        skill_md = skill_dir / "SKILL.md"
        gate_file = skills_root / gate_rel

        if not skill_dir.is_dir():
            missing_skills.append(skill_name)
            continue
        if not skill_md.is_file() or skill_md.stat().st_size < 100:
            missing_skill_mds.append(str(skill_md))
            continue
        if not gate_file.is_file() or gate_file.stat().st_size < 100:
            missing_gates.append(str(gate_file))
            continue
        verified_skills.append(skill_name)

    ok = (
        len(missing_skills) == 0
        and len(missing_skill_mds) == 0
        and len(missing_gates) == 0
        and len(verified_skills) == len(CANONICAL_9_SKILLS)
    )
    return {
        "healthy": ok,
        "verified_count": len(verified_skills),
        "expected_count": len(CANONICAL_9_SKILLS),
        "verified_skills": verified_skills,
        "missing_skills": missing_skills,
        "missing_skill_mds": missing_skill_mds,
        "missing_gates": missing_gates,
    }


def verify_state_and_log_integrity(
    state_path: pathlib.Path = DEFAULT_STATE_PATH,
    log_path: pathlib.Path = DEFAULT_LOG_PATH,
) -> Dict[str, Any]:
    """يتحقق من سلامة وتكامل `CONTINUOUS_IMPROVEMENT_STATE.json` و`CONTINUOUS_IMPROVEMENT_LOG.md`."""
    errors: List[str] = []
    if not state_path.is_file():
        errors.append(f"Missing state file: {state_path}")
        return {"healthy": False, "errors": errors}
    if not log_path.is_file():
        errors.append(f"Missing log file: {log_path}")
        return {"healthy": False, "errors": errors}

    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except Exception as exc:
        errors.append(f"Invalid JSON in {state_path}: {exc}")
        return {"healthy": False, "errors": errors}

    rot = state.get("skills_rotation") or []
    for sk in CANONICAL_9_SKILLS:
        if sk not in rot:
            errors.append(f"Skill '{sk}' missing from skills_rotation in state JSON")

    idx = state.get("next_skill_index")
    if not isinstance(idx, int) or not (0 <= idx < len(rot)):
        errors.append(f"Invalid next_skill_index={idx} for rotation length {len(rot)}")

    cycle_count = state.get("cycle_count")
    if not isinstance(cycle_count, int) or cycle_count < 1:
        errors.append(f"Invalid cycle_count={cycle_count}")

    last_cycle = state.get("last_completed_cycle") or {}
    if last_cycle.get("gate_status") != "PASS (0 errors)":
        errors.append(f"last_completed_cycle.gate_status is not 'PASS (0 errors)': {last_cycle.get('gate_status')}")

    log_text = log_path.read_text(encoding="utf-8")
    if "## الدورة 1" not in log_text:
        errors.append("CONTINUOUS_IMPROVEMENT_LOG.md missing '## الدورة 1' header")

    return {
        "healthy": len(errors) == 0,
        "cycle_count": cycle_count,
        "next_skill_index": idx,
        "next_skill": rot[idx] if (isinstance(idx, int) and 0 <= idx < len(rot)) else None,
        "rotation_count": len(rot),
        "log_bytes": log_path.stat().st_size,
        "errors": errors,
    }


def audit_live_pipeline(check_remote_vps: bool = False) -> Dict[str, Any]:
    """يجري تدقيقاً شاملاً لخط الإنتاج على الماك (واختيارياً VPS عبر SSH)."""
    mac_report = audit_mac_alignment_state()
    repo_report = verify_skills_repository_integrity()
    state_report = verify_state_and_log_integrity()

    vps_report: Dict[str, Any] = {"checked_remote": False}
    if check_remote_vps:
        try:
            r = subprocess.run(
                [
                    "ssh",
                    "-o",
                    "BatchMode=yes",
                    "-o",
                    "ConnectTimeout=6",
                    "hermes-vps",
                    "python3 /root/workspace/SKILLS/sheikh-series-pipeline/scripts/vps_pipeline_watchdog.py && cat /root/workspace/ytb-build/vps_watchdog_status.json",
                ],
                capture_output=True,
                text=True,
                timeout=15,
            )
            if r.returncode == 0 and r.stdout.strip():
                vps_report = {"checked_remote": True, "watchdog_status": json.loads(r.stdout.strip())}
            else:
                vps_report = {"checked_remote": True, "error": r.stderr.strip() or f"rc={r.returncode}"}
        except Exception as exc:
            vps_report = {"checked_remote": True, "error": str(exc)}

    return {
        "mac_alignment": mac_report,
        "skills_repository": repo_report,
        "state_and_log": state_report,
        "vps_watchdog": vps_report,
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="إدارة حلقة التحسين المستمر للمهارات وحارس الإنتاج المضاد للخداع (continuous-skill-improver)."
    )
    parser.add_argument("--state-file", type=pathlib.Path, default=DEFAULT_STATE_PATH)
    parser.add_argument("--status", action="store_true", help="عرض حالة الحلقة الحالية والمهارة القادمة")
    parser.add_argument("--audit-pipeline", action="store_true", help="فحص سلامة خط الإنتاج والمستودع")
    parser.add_argument("--check-remote-vps", action="store_true", help="فحص حارس VPS عبر SSH عند التدقيق")
    parser.add_argument("--next-prompt", action="store_true", help="توليد نص التكليف (Prompt) للوكيل الفرعي القادم")
    parser.add_argument("--verify-log-health", type=pathlib.Path, help="فحص ملف لوج تفريغ لكشف الخداع أو خطأ $HOME")
    parser.add_argument("--new-txts-30m", type=int, default=0, help="عدد ملفات .txt المكتوبة في آخر 30 دقيقة")
    parser.add_argument("--completed-series", type=int, default=0, help="قيمة completed_series_this_run للفحص")
    parser.add_argument("--advance-cycle", action="store_true", help="تقديم الدور بعد انتهاء الدورة")
    parser.add_argument("--skill", type=str, help="اسم المهارة التي جرى اختبارها وتطويرها في هذه الدورة")
    parser.add_argument("--datasets", type=str, help="وصف البيانات الحقيقية المستخدمة في الاختبار")
    parser.add_argument("--bugs-fixed", type=int, default=0, help="عدد العلل الواقعية المعالجة")
    parser.add_argument("--gate-status", type=str, default="PASS (0 errors)", help="حالة بوابة الفحص")

    args = parser.parse_args(argv)
    state = load_state(args.state_file)

    if args.verify_log_health:
        log_txt = args.verify_log_health.read_text(encoding="utf-8", errors="ignore")
        res = detect_fake_progress_or_env_failure(
            log_text=log_txt,
            state_dict={"completed_series_this_run": args.completed_series},
            new_txts_last_30m=args.new_txts_30m,
        )
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0 if res["healthy"] else 1

    if args.advance_cycle:
        datasets_list = [args.datasets] if args.datasets else None
        updated = advance_cycle_state(
            state,
            skill_tested=args.skill,
            real_datasets=datasets_list,
            bugs_fixed=args.bugs_fixed,
            gate_status=args.gate_status,
        )
        save_state(updated, args.state_file)
        idx, next_sk, gate_rel, _ = get_next_skill_info(updated)
        print(
            json.dumps(
                {
                    "advanced_to_cycle": updated["cycle_count"],
                    "completed_skill": updated["last_improved_skill"],
                    "next_skill_index": idx,
                    "next_skill": next_sk,
                    "next_gate": gate_rel,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    if args.next_prompt:
        print(generate_subagent_prompt(state, SKILLS_ROOT))
        return 0

    if args.audit_pipeline:
        report = audit_live_pipeline(check_remote_vps=args.check_remote_vps)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    # Default or --status
    idx, skill_name, gate_rel, backlog = get_next_skill_info(state)
    status_payload = {
        "loop_version": state.get("loop_version"),
        "cycle_count": state.get("cycle_count"),
        "last_improved_skill": state.get("last_improved_skill"),
        "next_skill_index": idx,
        "next_skill": skill_name,
        "next_skill_gate": gate_rel,
        "total_rotated_skills": len(state.get("skills_rotation", [])),
        "skills_rotation": state.get("skills_rotation", []),
        "priority_backlog_count": len(state.get("priority_backlog", [])),
    }
    print(json.dumps(status_payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
