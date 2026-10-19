#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""agy_lean.py — استدعاء Antigravity CLI (agy) في بيئة HOME معزولة خالية من MCP مع حارس الكوتة الصارم.

المزايا الهندسية:
  1. عزل كامل لبيئة HOME (Zero-MCP / Zero-Plugins / Zero-Skills):
     يوفر ~38,000 توكن في كل استدعاء عبر ربط ملفات المصادقة فقط (OAuth + Keychain)
     دون نسخ أو ربط mcp_config.json أو مجلدات mcp/ وplugins/ وskills/ وrules/.
  2. حارس الكوتة الحي (Strict Quota Guard):
     - يحمي 10% من نافذة الـ5 ساعات للوكيل التفاعلي الرئيسي (ويوقف عمال الخلفية عند 15%).
     - يحمي 25% من الكوتة الأسبوعية (عندما يكون timeUntilResetMs > 5.5 ساعات) ولا يفتحها إلا في آخر 12 ساعة قبل التجديد.
  3. تنظيف فوري لملفات الجلسات المؤقتة (conversations / annotations / brain) لمنع تضخم القرص.
"""
import argparse
import glob
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Any, Callable, Dict, List, Optional, Tuple


def _find_bin(name: str, extra_paths: List[str]) -> str:
    w = shutil.which(name)
    if w:
        return w
    for p in extra_paths:
        matches = sorted(glob.glob(p))
        if matches and os.access(matches[-1], os.X_OK):
            return matches[-1]
    return name


REAL_HOME = os.environ.get("AGY_REAL_HOME") or os.path.expanduser("~")

AGY_BIN = os.environ.get("AGY_BIN") or _find_bin("agy", [
    os.path.join(REAL_HOME, ".local/bin/agy"),
    "/Users/macm1pro/.local/bin/agy",
    "/root/.local/bin/agy",
])

QUOTA_BIN = os.environ.get("AGY_QUOTA_BIN") or _find_bin("antigravity-usage", [
    os.path.join(REAL_HOME, ".hermes/node/bin/antigravity-usage"),
    "/Users/macm1pro/.hermes/node/bin/antigravity-usage",
    "/root/.hermes/node/bin/antigravity-usage",
])

QUOTA_SNAPSHOT_PATHS = (
    "/root/workspace/ytb-build/live_quota.json",
    "/tmp/agy_quota_snapshot.json",
)

DEFAULT_FALLBACK_CHAIN = (
    "gemini-3.8-flash-high",
    "gemini-4-argon-high",
    "gemini-3.8-flash-medium",
    "gemini-4-argon-medium",
    "gemini-3.8-flash-low",
)

FORBIDDEN_LEAN_PATHS = (
    ".gemini/config/mcp_config.json",
    ".gemini/antigravity/mcp_config.json",
    ".gemini/antigravity-cli/mcp",
    ".gemini/antigravity/mcp",
    ".gemini/config/plugins",
    ".gemini/antigravity-cli/skills",
    ".gemini/antigravity/skills",
    ".gemini/skills",
    ".gemini/rules",
    ".gemini/antigravity-cli/rules",
    ".gemini/GEMINI.md",
)

SESSION_SUBDIRS = (
    "brain",
    "conversations",
    "annotations",
    "presence",
    "implicit",
    "log",
    "crashes",
)

BLOAT_DB_PATTERNS = (
    "conversation_summaries.db",
    "conversation_summaries.db-wal",
    "conversation_summaries.db-shm",
    "jetbox_summaries_proto.pb",
    "jetbox_summaries_proto.pb.*.tmp",
    "cli.log",
    "history.jsonl",
    "agy_run_sessions.jsonl",
    "cache/last_conversations.json",
)


def _parse_iso_ts(ts_str: str) -> Optional[float]:
    if not ts_str or not isinstance(ts_str, str):
        return None
    try:
        from datetime import datetime, timezone
        s = ts_str.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except Exception:
        return None


def _compute_snapshot_age(qpath: str, data: Dict[str, Any], now_ts: Optional[float] = None) -> float:
    now = now_ts if now_ts is not None else time.time()
    ages: List[float] = []
    try:
        mtime = os.path.getmtime(qpath)
        ages.append(max(0.0, now - mtime))
    except OSError:
        pass
    payload_ts = _parse_iso_ts(str(data.get("timestamp") or ""))
    if payload_ts is not None:
        ages.append(max(0.0, now - payload_ts))
    return round(max(ages) if ages else 0.0, 2)


def _load_best_snapshot(
    paths: Tuple[str, ...] = QUOTA_SNAPSHOT_PATHS,
    now_ts: Optional[float] = None,
) -> Optional[Tuple[Dict[str, Any], str, float]]:
    candidates: List[Tuple[float, int, Dict[str, Any], str]] = []
    for priority_idx, qpath in enumerate(paths):
        if not qpath or not os.path.exists(qpath):
            continue
        try:
            with open(qpath, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and isinstance(data.get("models"), list) and data["models"]:
                age_s = _compute_snapshot_age(qpath, data, now_ts=now_ts)
                candidates.append((age_s, priority_idx, data, qpath))
        except Exception:
            continue
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1]))
    best_age, _, best_data, best_path = candidates[0]
    best_copy = dict(best_data)
    best_copy["_source_path"] = best_path
    best_copy["_age_seconds"] = best_age
    return best_copy, best_path, best_age


def _has_usable_quota_bin() -> bool:
    return bool(QUOTA_BIN and os.path.exists(QUOTA_BIN) and os.access(QUOTA_BIN, os.X_OK))


def fetch_quota_data(
    refresh_live: bool = False,
    max_cache_age_s: float = 300.0,
    max_stale_age_s: float = 1800.0,
    snapshot_paths: Tuple[str, ...] = QUOTA_SNAPSHOT_PATHS,
    now_ts: Optional[float] = None,
    allow_live_bin: Optional[bool] = None,
) -> Optional[Dict[str, Any]]:
    """قراءة بيانات الكوتة من اللقطة المزامَنة (/root/workspace/ytb-build/live_quota.json) أو المحلية أو استدعاء antigravity-usage مع فحص عمر الملف."""
    best_snap = _load_best_snapshot(paths=snapshot_paths, now_ts=now_ts)
    has_bin = _has_usable_quota_bin() if allow_live_bin is None else bool(allow_live_bin)

    # 1. إذا لم يُطلب تحديث حي قسري، أو كنا على سيرفر hermes-vps حيث لا تتوفر أداة سطح المكتب محلياً،
    # نستخدم اللقطة الأحدث فوراً إذا كانت ضمن العمر المسموح
    if best_snap is not None:
        snap_data, _, snap_age = best_snap
        effective_fresh_limit = max_stale_age_s if not has_bin else max_cache_age_s
        if (not refresh_live or not has_bin) and snap_age <= effective_fresh_limit:
            snap_data["_is_stale"] = False
            return snap_data

    # 2. محاولة الجلب المباشر عبر antigravity-usage إن كانت متوفرة (بيئة الماك)
    if has_bin:
        try:
            env = dict(os.environ)
            env["HOME"] = REAL_HOME
            res = subprocess.run(
                [QUOTA_BIN, "quota", "--json", "--all-models"],
                capture_output=True, text=True, timeout=15, env=env
            )
            if res.returncode == 0 and res.stdout.strip():
                data = json.loads(res.stdout.strip())
                if isinstance(data, dict) and data.get("models"):
                    try:
                        with open("/tmp/agy_quota_snapshot.json", "w", encoding="utf-8") as f:
                            json.dump(data, f, ensure_ascii=False, indent=2)
                    except Exception:
                        pass
                    data["_source_path"] = "live_cli"
                    data["_age_seconds"] = 0.0
                    data["_is_stale"] = False
                    return data
        except Exception:
            pass

    # 3. الرجوع إلى اللقطة المحلية/المزامَنة مع وسم حالتها العمرية (staleness check)
    if best_snap is not None:
        snap_data, _, snap_age = best_snap
        snap_data["_is_stale"] = bool(snap_age > max_stale_age_s)
        return snap_data
    return None


def _classify_family(text: str) -> str:
    t = (text or "").lower()
    if any(k in t for k in ("claude", "opus", "sonnet", "haiku")):
        return "claude"
    if "gpt" in t or "openai" in t:
        return "gpt"
    if any(k in t for k in ("gemini", "flash", "argon", "pro")):
        return "gemini"
    return "other"


def _score_model_candidate(entry: Dict[str, Any], model_hint: str) -> int:
    if entry.get("isAutocompleteOnly"):
        return -1
    lbl = (entry.get("label") or "").lower()
    mid = (entry.get("modelId") or "").lower()
    hint = (model_hint or "gemini-3.8-flash-high").lower().replace("_", "-")
    want_fam = _classify_family(hint)
    entry_fam = _classify_family(lbl + " " + mid)

    if want_fam != "other" and entry_fam != want_fam:
        return -1

    score = 100
    # مطابقة الفئة الفرعية
    for sub_tok in ("flash", "argon", "opus", "sonnet", "3.8", "4", "5.5", "120b"):
        if sub_tok in hint:
            if sub_tok in lbl:
                score += 30
            else:
                score -= 10
    # مطابقة مستوى الجهد/الطبقة (high / medium / low)
    if "high" in hint:
        score += 15 if "(high)" in lbl or "high" in lbl else -5
    elif "medium" in hint:
        score += 15 if "(medium)" in lbl or "medium" in lbl else -5
    elif "low" in hint:
        score += 15 if "(low)" in lbl or "low" in lbl else -5
    else:
        # تفضيل High افتراضياً ثم Medium عند تمرير اسم العائلة فقط مثل "gemini" أو "claude"
        if "(high)" in lbl:
            score += 10
        elif "(medium)" in lbl:
            score += 5
    return score


def _match_model_entries(models: List[Dict[str, Any]], model_hint: str) -> List[Dict[str, Any]]:
    scored: List[Tuple[int, int, Dict[str, Any]]] = []
    for idx, m in enumerate(models or []):
        if not isinstance(m, dict):
            continue
        sc = _score_model_candidate(m, model_hint)
        if sc >= 0:
            scored.append((sc, -idx, m))
    if not scored:
        return []
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return [item[2] for item in scored]


def _match_model_entry(models: List[Dict[str, Any]], model_hint: str) -> Optional[Dict[str, Any]]:
    matches = _match_model_entries(models, model_hint)
    if matches:
        return matches[0]
    return models[0] if models else None


def evaluate_quota_entry(
    target: Dict[str, Any],
    background: bool = True,
    min_5h_bg: float = 0.15,
    min_5h_fg: float = 0.10,
    min_weekly_reserve: float = 0.25,
    weekly_window_threshold_h: float = 5.5,
    weekly_unlock_hours: float = 12.0,
) -> Dict[str, Any]:
    """تقييم حتمي لمدى أمان استهلاك الكوتة لنموذج محدد وفق قاعدتَي الـ5 ساعات (>=15% للخلفية / >=10% للأمامي) والاحتياطي الأسبوعي (>25% إلا في آخر 12 ساعة)."""
    label = target.get("label") or "Unknown Model"
    rem = float(target.get("remainingPercentage") if target.get("remainingPercentage") is not None else 1.0)
    reset_ms = float(target.get("timeUntilResetMs") or 0.0)
    reset_hours = max(0.0, reset_ms / (1000.0 * 3600.0))
    exhausted = bool(target.get("isExhausted", False))
    floor_5h = min_5h_bg if background else min_5h_fg
    is_weekly_window = reset_hours > weekly_window_threshold_h
    weekly_locked = bool(is_weekly_window and reset_hours > weekly_unlock_hours)

    base_info = {
        "label": label,
        "remaining_pct": round(rem * 100.0, 2),
        "remaining_ratio": rem,
        "reset_hours": round(reset_hours, 2),
        "window_type": "weekly_or_rolling" if is_weekly_window else "5h",
        "floor_5h_pct": round(floor_5h * 100.0, 2),
        "weekly_reserve_pct": round(min_weekly_reserve * 100.0, 2),
        "weekly_locked": weekly_locked,
    }

    if exhausted or rem < floor_5h:
        mode_lbl = "الوكلاء الخلفيين (15%)" if background else "الوكيل الرئيسي (10%)"
        return {
            **base_info,
            "safe": False,
            "reason": (
                f"حظر الكوتة لـ [{label}]: المتبقي {rem*100:.2f}% أقل من حد الأمان لـ{mode_lbl} "
                f"({floor_5h*100:.0f}%)"
            ),
        }

    if weekly_locked and rem <= min_weekly_reserve:
        return {
            **base_info,
            "safe": False,
            "reason": (
                f"حظر الاحتياطي الأسبوعي لـ [{label}]: المتبقي {rem*100:.2f}% <= {min_weekly_reserve*100:.0f}% "
                f"وباقي {reset_hours:.1f} ساعة (> {weekly_unlock_hours:.0f} ساعة) على التجديد"
            ),
        }

    return {
        **base_info,
        "safe": True,
        "reason": "OK",
    }


def check_quota(
    model_hint: str = "gemini",
    background: bool = True,
    refresh_live: bool = False,
    qdata: Optional[Dict[str, Any]] = None,
    max_stale_age_s: float = 1800.0,
    fail_on_stale: bool = False,
) -> Dict[str, Any]:
    """فحص الكوتة الحية لنموذج محدد مع تطبيق الحارس المزدوج (5h + Weekly) والتحقق من عمر ملف الكوتة."""
    data = (
        qdata
        if qdata is not None
        else fetch_quota_data(refresh_live=refresh_live, max_stale_age_s=max_stale_age_s)
    )
    if not data or not data.get("models"):
        return {
            "safe": not fail_on_stale,
            "label": model_hint,
            "remaining_pct": 100.0 if not fail_on_stale else 0.0,
            "remaining_ratio": 1.0 if not fail_on_stale else 0.0,
            "reset_hours": 0.0,
            "window_type": "unknown",
            "is_stale": True,
            "snapshot_age_s": None,
            "source_path": None,
            "reason": (
                "حظر الكوتة: تعذر العثور على لقطة كوتة صالحة"
                if fail_on_stale
                else "تعذر قراءة لقطة الكوتة المحلية؛ السماح الافتراضي"
            ),
        }

    source_path = data.get("_source_path")
    age_s = data.get("_age_seconds")
    if age_s is None and source_path and os.path.exists(str(source_path)):
        age_s = _compute_snapshot_age(str(source_path), data)
    elif age_s is None and data.get("timestamp"):
        parsed_ts = _parse_iso_ts(str(data.get("timestamp")))
        if parsed_ts is not None:
            age_s = round(max(0.0, time.time() - parsed_ts), 2)

    is_stale = bool(
        data.get("_is_stale")
        if "_is_stale" in data
        else (age_s is not None and age_s > max_stale_age_s)
    )

    matches = _match_model_entries(data["models"], model_hint)
    if not matches:
        return {
            "safe": True,
            "label": model_hint,
            "remaining_pct": 100.0,
            "remaining_ratio": 1.0,
            "reset_hours": 0.0,
            "window_type": "unknown",
            "is_stale": is_stale,
            "snapshot_age_s": age_s,
            "source_path": source_path,
            "reason": "النموذج غير موجود في اللقطة",
        }

    primary_eval = evaluate_quota_entry(matches[0], background=background)

    # فحص الحارس المزدوج عبر نافذتَي الـ5 ساعات والأسبوعية إن وُجد قيدان لنفس العائلة
    blocking_eval = None
    if not primary_eval["safe"]:
        blocking_eval = primary_eval
    else:
        top_score = _score_model_candidate(matches[0], model_hint)
        for m in matches[1:]:
            # فحص النماذج المطابقة لنفس الفئة أو التي تمثل نافذة زمنية ثانية لنفس النموذج
            if _score_model_candidate(m, model_hint) >= top_score - 15 or (
                (m.get("label") or "").split("(")[0].strip().lower()
                == (matches[0].get("label") or "").split("(")[0].strip().lower()
            ):
                ev = evaluate_quota_entry(m, background=background)
                if not ev["safe"]:
                    blocking_eval = ev
                    break

    chosen_eval = dict(blocking_eval if blocking_eval is not None else primary_eval)
    chosen_eval["is_stale"] = is_stale
    chosen_eval["snapshot_age_s"] = age_s
    chosen_eval["source_path"] = source_path

    if is_stale and fail_on_stale and chosen_eval["safe"]:
        chosen_eval["safe"] = False
        chosen_eval["reason"] = (
            f"حظر الكوتة لـ [{chosen_eval['label']}]: لقطة الكوتة قديمة جداً "
            f"(عمرها {age_s:.0f}ث > الحد المسموح {max_stale_age_s:.0f}ث)"
        )

    return chosen_eval


def select_best_model(
    preferred_model: str = "gemini-3.8-flash-high",
    background: bool = True,
    auto_fallback: bool = True,
    qdata: Optional[Dict[str, Any]] = None,
    fallback_chain: Tuple[str, ...] = DEFAULT_FALLBACK_CHAIN,
    max_stale_age_s: float = 1800.0,
    fail_on_stale: bool = False,
) -> Tuple[str, Dict[str, Any]]:
    """اختيار النموذج الأنسب وفق سياسة الحارس المزدوج (5h + Weekly) مع التحويل التلقائي عبر سلسلة البدائل الآمنة."""
    data = (
        qdata
        if qdata is not None
        else fetch_quota_data(refresh_live=False, max_stale_age_s=max_stale_age_s)
    )
    q_pref = check_quota(
        preferred_model,
        background=background,
        qdata=data,
        max_stale_age_s=max_stale_age_s,
        fail_on_stale=fail_on_stale,
    )
    if q_pref["safe"]:
        return preferred_model, q_pref

    if auto_fallback:
        safe_candidates: List[Tuple[float, int, str, Dict[str, Any]]] = []
        for idx, fb_model in enumerate(fallback_chain):
            if fb_model.lower() == (preferred_model or "").lower():
                continue
            # إذا لم يكن النموذج البديل موجوداً أصلاً في قائمة النماذج، نتخطاه إلا إذا كانت القائمة فارغة
            if data and data.get("models"):
                fb_matches = _match_model_entries(data["models"], fb_model)
                if not fb_matches:
                    continue
                # تأكد من أن البديل يطابق الفئة الفرعية المطلوبة (مثلاً argon مقابل flash) إن وُجدت في اللقطة
                top_lbl = (fb_matches[0].get("label") or "").lower()
                if "argon" in fb_model.lower() and "argon" not in top_lbl and any(
                    "argon" in (m.get("label") or "").lower() for m in data["models"]
                ):
                    continue
                if "flash" in fb_model.lower() and "flash" not in top_lbl and any(
                    "flash" in (m.get("label") or "").lower() for m in data["models"]
                ):
                    continue
            q_fb = check_quota(
                fb_model,
                background=background,
                qdata=data,
                max_stale_age_s=max_stale_age_s,
                fail_on_stale=fail_on_stale,
            )
            if q_fb["safe"]:
                q_fb = dict(q_fb)
                q_fb["fallback_from"] = preferred_model
                q_fb["fallback_reason"] = q_pref["reason"]
                safe_candidates.append((float(q_fb.get("remaining_ratio", 0.0)), -idx, fb_model, q_fb))
        if safe_candidates:
            safe_candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
            _, _, best_fb_model, best_q_fb = safe_candidates[0]
            return best_fb_model, best_q_fb

    return preferred_model, q_pref


def recommend_concurrency_from_quota(
    model_hint: str = "gemini-3.8-flash-high",
    max_workers: int = 16,
    min_workers: int = 1,
    background: bool = True,
    qdata: Optional[Dict[str, Any]] = None,
    prev_qdata: Optional[Dict[str, Any]] = None,
    window_hours: float = 5.0,
    soft_throttle_pct: float = 25.0,
    medium_throttle_pct: float = 40.0,
    max_stale_age_s: float = 1800.0,
    fail_on_stale: bool = False,
) -> Dict[str, Any]:
    """تقدير معدل استهلاك الكوتة (Burn-Rate Prediction) وتحديد عدد العمال المتوازيين الآمن (Adaptive Concurrency Throttling).

    بدلاً من العمل بأقصى سرعة (مثلاً 16 عاملاً) حتى الاصطدام المفاجئ بجدار الـ15%:
      - عند هبوط الكوتة تحت حد الأمان (<15% للخلفية أو <10% للأمامي أو كسر الاحتياطي الأسبوعي): recommended_workers = 0.
      - في المنطقة الحرجة (15% <= remaining_pct < 25%، أو قرب جدار الاحتياطي الأسبوعي بـ <=7%):
        تقليص العمال إلى الربع max(min_workers, max_workers // 4) (مثلاً من 16 إلى 4).
      - في المنطقة المتوسطة (25% <= remaining_pct < 40% أو عندما يتوقع معدل الحرق استنفاد الهامش قبل التجديد):
        تقليص العمال إلى النصف max(min_workers, max_workers // 2) (مثلاً من 16 إلى 8).
      - في المنطقة الآمنة (>= 40% مع معدل حرق آمن): السماح بكامل العمال (max_workers).
    """
    max_w = max(1, int(max_workers))
    min_w = max(1, min(int(min_workers), max_w))

    q_info = check_quota(
        model_hint=model_hint,
        background=background,
        qdata=qdata,
        max_stale_age_s=max_stale_age_s,
        fail_on_stale=fail_on_stale,
    )
    rem_pct = float(q_info.get("remaining_pct", 100.0))
    reset_h = float(q_info.get("reset_hours", 0.0))
    floor_5h_pct = float(q_info.get("floor_5h_pct", 15.0 if background else 10.0))
    weekly_locked = bool(q_info.get("weekly_locked", False))
    weekly_res_pct = float(q_info.get("weekly_reserve_pct", 25.0))
    effective_floor_pct = max(floor_5h_pct, weekly_res_pct) if weekly_locked else floor_5h_pct
    usable_headroom_pct = round(max(0.0, rem_pct - effective_floor_pct), 2)

    # حساب معدل الاستهلاك (Burn Rate %/hour)
    if q_info.get("window_type") == "5h" or reset_h <= 5.5:
        elapsed_h = max(0.25, window_hours - min(window_hours, reset_h))
        consumed_pct = max(0.0, 100.0 - rem_pct)
        burn_rate_pct_per_h = round(consumed_pct / elapsed_h, 2) if reset_h > 0 else 0.0
    else:
        # نافذة أسبوعية (168 ساعة)
        weekly_total_h = 168.0
        elapsed_h = max(1.0, weekly_total_h - min(weekly_total_h, reset_h))
        consumed_pct = max(0.0, 100.0 - rem_pct)
        burn_rate_pct_per_h = round(consumed_pct / elapsed_h, 2)

    # إذا توفرت لقطة سابقة للمقارنة اللحظية، نأخذ الأعلى بين المعدل اللحظي ومعدل النافذة
    if prev_qdata is not None:
        prev_q = check_quota(model_hint=model_hint, background=background, qdata=prev_qdata)
        prev_rem = float(prev_q.get("remaining_pct", rem_pct))
        prev_ts = _parse_iso_ts(str((prev_qdata or {}).get("timestamp") or ""))
        curr_ts = _parse_iso_ts(str((qdata or {}).get("timestamp") or ""))
        if prev_ts is not None and curr_ts is not None and curr_ts > prev_ts:
            dt_h = max(1.0 / 60.0, (curr_ts - prev_ts) / 3600.0)
        else:
            prev_reset_h = float(prev_q.get("reset_hours", reset_h))
            dt_h = max(1.0 / 60.0, prev_reset_h - reset_h) if prev_reset_h > reset_h else 0.25
        if prev_rem > rem_pct:
            instant_burn = round((prev_rem - rem_pct) / dt_h, 2)
            burn_rate_pct_per_h = max(burn_rate_pct_per_h, instant_burn)

    projected_hours_to_floor = (
        round(usable_headroom_pct / burn_rate_pct_per_h, 2)
        if burn_rate_pct_per_h > 0.0
        else 999.0
    )
    will_exhaust_before_reset = bool(
        reset_h > 0.0 and burn_rate_pct_per_h > 0.0 and projected_hours_to_floor < reset_h
    )

    if not q_info.get("safe", False) or rem_pct < floor_5h_pct or (weekly_locked and rem_pct <= weekly_res_pct):
        rec_workers = 0
        throttle_level = "blocked"
        reason = q_info.get("reason") or "الكوتة دون حد الأمان؛ إيقاف التوازي (0 عمال)"
    elif rem_pct < soft_throttle_pct or usable_headroom_pct < 10.0:
        rec_workers = max(min_w, max_w // 4)
        throttle_level = "critical"
        reason = (
            f"تقليص حرج للعمال ({max_w} -> {rec_workers}): المتبقي {rem_pct:.1f}% تحت عتبة التهدئة "
            f"({soft_throttle_pct:.0f}%) قبل جدار الإيقاف ({effective_floor_pct:.0f}%)"
        )
    elif rem_pct < medium_throttle_pct or (will_exhaust_before_reset and rem_pct < 65.0):
        rec_workers = max(min_w, max_w // 2)
        throttle_level = "moderate"
        reason = (
            f"تقليص وقائي للعمال ({max_w} -> {rec_workers}): المتبقي {rem_pct:.1f}% "
            f"(معدل الحرق {burn_rate_pct_per_h:.1f}%/ساعة، يكفي {projected_hours_to_floor:.1f}س مقابل {reset_h:.1f}س للتجديد)"
        )
    else:
        rec_workers = max_w
        throttle_level = "full"
        reason = f"كوتة وفيرة ({rem_pct:.1f}%)؛ تشغيل كامل التوازي ({rec_workers} عمال)"

    return {
        "safe": bool(q_info.get("safe", False) and rec_workers > 0),
        "model": q_info.get("label") or model_hint,
        "recommended_workers": rec_workers,
        "max_workers": max_w,
        "min_workers": min_w,
        "throttle_level": throttle_level,
        "throttle_ratio": round(rec_workers / float(max_w), 4) if max_w > 0 else 0.0,
        "remaining_pct": rem_pct,
        "effective_floor_pct": effective_floor_pct,
        "usable_headroom_pct": usable_headroom_pct,
        "reset_hours": reset_h,
        "burn_rate_pct_per_hour": burn_rate_pct_per_h,
        "projected_hours_to_floor": projected_hours_to_floor,
        "will_exhaust_before_reset": will_exhaust_before_reset,
        "reason": reason,
        "quota": q_info,
    }


compute_quota_burn_rate_and_recommended_workers = recommend_concurrency_from_quota


def _safe_symlink(src: str, dst: str) -> None:
    if not os.path.exists(src):
        return
    if os.path.islink(dst) or os.path.exists(dst):
        try:
            if os.path.islink(dst) and os.readlink(dst) == src:
                return
            if os.path.isdir(dst) and not os.path.islink(dst):
                shutil.rmtree(dst, ignore_errors=True)
            else:
                os.remove(dst)
        except OSError:
            pass
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    os.symlink(src, dst)


def _remove_forbidden_lean_paths(lean_home_dir: str) -> int:
    removed = 0
    for rel_forbidden in FORBIDDEN_LEAN_PATHS:
        target_p = os.path.join(lean_home_dir, rel_forbidden)
        if os.path.islink(target_p) or os.path.exists(target_p):
            try:
                if os.path.isdir(target_p) and not os.path.islink(target_p):
                    shutil.rmtree(target_p, ignore_errors=True)
                else:
                    os.remove(target_p)
                removed += 1
            except OSError:
                pass
    return removed


def prepare_lean_home(lean_home_dir: Optional[str] = None) -> str:
    """بناء بيئة HOME معزولة تحتوي على روابط المصادقة فقط وبدون أي MCP أو إضافات أو مهارات."""
    if not lean_home_dir:
        uid = getattr(os, "getuid", lambda: 0)()
        lean_home_dir = f"/tmp/agy_lean_home_{uid}"

    os.makedirs(lean_home_dir, exist_ok=True)

    # على macOS: ربط ~/Library لتمكين الوصول إلى Keychain وشهادات النظام دون طلب تسجيل دخول
    if sys.platform == "darwin":
        real_lib = os.path.join(REAL_HOME, "Library")
        if os.path.isdir(real_lib):
            _safe_symlink(real_lib, os.path.join(lean_home_dir, "Library"))

    real_gemini = os.path.join(REAL_HOME, ".gemini")
    lean_gemini = os.path.join(lean_home_dir, ".gemini")
    os.makedirs(lean_gemini, exist_ok=True)

    # 1. روابط المصادقة الأساسية في ~/.gemini/
    for fname in (
        "jetski-standalone-oauth-token",
        "oauth_creds.json",
        "google_accounts.json",
        "installation_id",
        "state.json",
    ):
        _safe_symlink(os.path.join(real_gemini, fname), os.path.join(lean_gemini, fname))

    # 2. روابط ~/.gemini/antigravity/ الأساسية (بدون mcp_config.json أو skills أو rules)
    real_ag = os.path.join(real_gemini, "antigravity")
    lean_ag = os.path.join(lean_gemini, "antigravity")
    os.makedirs(lean_ag, exist_ok=True)
    for fname in ("antigravity_state.pbtxt", "installation_id", "bin", "lib"):
        _safe_symlink(os.path.join(real_ag, fname), os.path.join(lean_ag, fname))

    # 3. روابط ~/.gemini/antigravity-cli/ الأساسية (بدون mcp أو skills أو rules)
    real_cli = os.path.join(real_gemini, "antigravity-cli")
    lean_cli = os.path.join(lean_gemini, "antigravity-cli")
    os.makedirs(lean_cli, exist_ok=True)
    for fname in ("antigravity-oauth-token", "installation_id", "jetski_state.pbtxt", "bin"):
        _safe_symlink(os.path.join(real_cli, fname), os.path.join(lean_cli, fname))

    for sub in ("conversations", "annotations", "brain", "presence", "implicit", "log", "cache", "crashes"):
        os.makedirs(os.path.join(lean_cli, sub), exist_ok=True)

    # 4. إعدادات antigravity-cli/settings.json النظيفة
    lean_cli_settings = {
        "allowNonWorkspaceAccess": True,
        "model": "Gemini 3.8 Flash (High)",
        "notifications": False,
        "permissions": {"allow": []},
        "runningLightSpeed": "fast",
        "showFeedbackSurvey": False,
        "toolPermission": "always-proceed",
        "trustedWorkspaces": [
            "/tmp",
            "/private/tmp",
            "/var/folders",
            "/private/var/folders",
            REAL_HOME,
        ],
        "verbosity": "low",
    }
    with open(os.path.join(lean_cli, "settings.json"), "w", encoding="utf-8") as f:
        json.dump(lean_cli_settings, f, indent=2)

    # 5. إعدادات ~/.gemini/config/config.json النظيفة (بدون mcp_config.json وبدون plugins)
    lean_cfg_dir = os.path.join(lean_gemini, "config")
    os.makedirs(lean_cfg_dir, exist_ok=True)
    with open(os.path.join(lean_cfg_dir, ".migrated"), "w", encoding="utf-8") as f:
        f.write("")
    lean_cfg = {
        "plugins": {},
        "userSettings": {
            "autoExecutionPolicy": "CASCADE_COMMANDS_AUTO_EXECUTION_EAGER",
            "enableTerminalSandbox": False,
            "globalPermissionGrants": {"allow": []},
            "nonWorkspaceFileAccessPolicy": "AGENT_SETTING_POLICY_ALLOW",
            "permissionGrantsV2Migrated": True,
            "useAiCredits": False,
        },
    }
    with open(os.path.join(lean_cfg_dir, "config.json"), "w", encoding="utf-8") as f:
        json.dump(lean_cfg, f, indent=2)

    # 6. التأكد من حذف أي مسار محظور لو كان موجوداً مسبقاً
    _remove_forbidden_lean_paths(lean_home_dir)

    return lean_home_dir


def verify_lean_home_isolation(lean_home_dir: str) -> Dict[str, Any]:
    """التحقق الحتمي من خلو بيئة HOME المعزولة من أي ملفات MCP أو إضافات ووجود روابط المصادقة."""
    violations = []
    for rel_forbidden in FORBIDDEN_LEAN_PATHS:
        p = os.path.join(lean_home_dir, rel_forbidden)
        if os.path.exists(p) or os.path.islink(p):
            violations.append(rel_forbidden)

    auth_token = os.path.join(lean_home_dir, ".gemini/antigravity-cli/antigravity-oauth-token")
    cfg_json = os.path.join(lean_home_dir, ".gemini/config/config.json")
    has_auth = os.path.exists(auth_token)
    has_clean_cfg = False
    if os.path.exists(cfg_json):
        try:
            with open(cfg_json, encoding="utf-8") as f:
                cfg = json.load(f)
            has_clean_cfg = cfg.get("plugins") == {}
        except Exception:
            has_clean_cfg = False

    return {
        "isolated": len(violations) == 0 and has_auth and has_clean_cfg,
        "violations": violations,
        "has_auth": has_auth,
        "has_clean_cfg": has_clean_cfg,
        "lean_home": lean_home_dir,
    }


def _snapshot_session_subdirs(lean_home_dir: str) -> Dict[str, set]:
    base_dir = os.path.join(lean_home_dir, ".gemini", "antigravity-cli")
    snap: Dict[str, set] = {}
    for sub in SESSION_SUBDIRS:
        sub_dir = os.path.join(base_dir, sub)
        if os.path.isdir(sub_dir):
            try:
                snap[sub] = set(os.listdir(sub_dir))
            except OSError:
                snap[sub] = set()
        else:
            snap[sub] = set()
    return snap


def _cleanup_lean_conv(
    lean_home_dir: str,
    conv_id: Optional[str] = None,
    pre_snapshot: Optional[Dict[str, set]] = None,
    sweep_all_idle: bool = True,
) -> Dict[str, Any]:
    """تنظيف شامل وحتمي لبيئة HOME المعزولة بعد كل استدعاء (brain / conversations / implicit / summaries DB / log / MCP)."""
    base_dir = os.path.join(lean_home_dir, ".gemini", "antigravity-cli")
    removed_items = 0

    def _rm_path(p: str) -> bool:
        try:
            if os.path.islink(p) or os.path.isfile(p):
                os.remove(p)
                return True
            if os.path.isdir(p):
                shutil.rmtree(p, ignore_errors=True)
                return True
        except OSError:
            pass
        return False

    # 1. حذف ملفات ومجلد conv_id المحدد إن وُجد
    if conv_id:
        for sub, suffixes in (
            ("conversations", (".pb", ".db", ".db-wal", ".db-shm")),
            ("annotations", (".pbtxt",)),
            ("presence", (".lock",)),
            ("implicit", (".pb",)),
        ):
            sub_dir = os.path.join(base_dir, sub)
            for suffix in suffixes:
                if _rm_path(os.path.join(sub_dir, conv_id + suffix)):
                    removed_items += 1
        if _rm_path(os.path.join(base_dir, "brain", conv_id)):
            removed_items += 1

    # 2. حذف كل العناصر التي أُنشئت خلال هذا الاستدعاء أو المتراكمة في مجلدات الجلسات المؤقتة
    for sub in SESSION_SUBDIRS:
        sub_dir = os.path.join(base_dir, sub)
        if not os.path.isdir(sub_dir):
            continue
        before_set = (pre_snapshot or {}).get(sub, set())
        try:
            entries = list(os.listdir(sub_dir))
        except OSError:
            continue
        for name in entries:
            if sweep_all_idle or (pre_snapshot is not None and name not in before_set):
                if _rm_path(os.path.join(sub_dir, name)):
                    removed_items += 1

    # 3. حذف قواعد بيانات الملخصات والسجلات المؤقتة المتضخمة
    for pat in BLOAT_DB_PATTERNS:
        for matched_p in glob.glob(os.path.join(base_dir, pat)):
            if _rm_path(matched_p):
                removed_items += 1

    # 4. حذف أي ملف محظور قد ينشئه agy تلقائياً عند الإقلاع (مثل .gemini/config/mcp_config.json الفارغ على Linux)
    removed_items += _remove_forbidden_lean_paths(lean_home_dir)

    # 5. إحصاء أي بقايا للتحقق الحتمي في بوابات الجودة
    remaining_brain = []
    brain_root = os.path.join(base_dir, "brain")
    if os.path.isdir(brain_root):
        try:
            remaining_brain = os.listdir(brain_root)
        except OSError:
            pass

    remaining_session_files = 0
    for sub in SESSION_SUBDIRS:
        sub_dir = os.path.join(base_dir, sub)
        if os.path.isdir(sub_dir):
            try:
                remaining_session_files += len(os.listdir(sub_dir))
            except OSError:
                pass

    return {
        "removed_items": removed_items,
        "remaining_brain_count": len(remaining_brain),
        "remaining_session_files": remaining_session_files,
    }


def _extract_agy_json(stdout_text: str) -> Tuple[Optional[str], Dict[str, Any], Optional[str]]:
    txt = (stdout_text or "").strip()
    if not txt:
        return None, {}, None
    for line in reversed([l.strip() for l in txt.splitlines() if l.strip().startswith("{")]):
        try:
            payload = json.loads(line)
            if isinstance(payload, dict) and "response" in payload:
                return (
                    (payload.get("response") or "").strip(),
                    (payload.get("usage") or {}),
                    payload.get("conversation_id"),
                )
        except Exception:
            pass
    idx = txt.find("{")
    ridx = txt.rfind("}")
    if idx != -1 and ridx > idx:
        try:
            payload = json.loads(txt[idx : ridx + 1])
            if isinstance(payload, dict) and "response" in payload:
                return (
                    (payload.get("response") or "").strip(),
                    (payload.get("usage") or {}),
                    payload.get("conversation_id"),
                )
        except Exception:
            pass
    return None, {}, None


def normalize_mode(mode: str) -> str:
    """تحويل أوضاع الاستشارة (ask / plan / read) إلى الوضع المدعوم رسمياً في agy CLI."""
    m = (mode or "ask").strip().lower()
    if m in ("ask", "plan", "read", "readonly"):
        return "plan"
    if m in ("accept-edits", "auto"):
        return m
    return "plan"


_RATE_LIMIT_REGEX = re.compile(
    r"("
    r"\b429\b"
    r"|resource[_\s-]*exhausted"
    r"|quota[_\s-]*exceeded"
    r"|rate[_\s-]*limit(?:ed|[_\s-]*exceeded)?"
    r"|too\s+many\s+requests"
    r"|exhausted\s+your\s+capacity"
    r"|capacity\s+exhausted"
    r")",
    re.IGNORECASE,
)

_EXPLICIT_RATE_LIMIT_IN_OK_STDOUT_REGEX = re.compile(
    r"("
    r"resource[_\s-]*exhausted"
    r"|quota[_\s-]*exceeded"
    r"|429\s+too\s+many\s+requests"
    r"|status[_\s-]*code[\s:=]+429"
    r"|\"code\"\s*:\s*429"
    r"|rate\s+limit\s+exceeded"
    r")",
    re.IGNORECASE,
)

_RETRY_AFTER_REGEX = re.compile(
    r"(?:retry[-_\s]*after|retrydelay)[\"'=:\s]+(\d+(?:\.\d+)?)\s*s?",
    re.IGNORECASE,
)


def classify_agy_error(
    stdout_text: str = "",
    stderr_text: str = "",
    returncode: int = 0,
    resp_txt: Optional[str] = None,
) -> Dict[str, Any]:
    """تصنيف مخرجات وأخطاء agy لكشف أخطاء 429 / ResourceExhausted / QuotaExceeded بدقة."""
    out = stdout_text or ""
    err = stderr_text or ""
    resp = (resp_txt if resp_txt is not None else out).strip()
    combined = f"{err}\n{out}\n{resp}"

    retry_after_s: Optional[float] = None
    m_retry = _RETRY_AFTER_REGEX.search(combined)
    if m_retry:
        try:
            retry_after_s = float(m_retry.group(1))
        except ValueError:
            retry_after_s = None

    # فحص أخطاء تجاوز المعدل (429 / ResourceExhausted / QuotaExceeded)
    is_rate_limit = False
    matched_token = None
    if returncode != 0 or not resp:
        m_rl = _RATE_LIMIT_REGEX.search(combined)
        if m_rl:
            is_rate_limit = True
            matched_token = m_rl.group(1)
    else:
        m_rl_explicit = _EXPLICIT_RATE_LIMIT_IN_OK_STDOUT_REGEX.search(combined)
        if m_rl_explicit:
            is_rate_limit = True
            matched_token = m_rl_explicit.group(1)

    if is_rate_limit:
        return {
            "is_error": True,
            "error_type": "rate_limit",
            "is_rate_limit": True,
            "matched_pattern": matched_token,
            "retry_after_s": retry_after_s,
            "reason": f"تجاوز معدل الطلبات (429 / ResourceExhausted: {matched_token})",
        }

    if returncode != 0 or not resp:
        low_comb = combined.lower()
        if any(k in low_comb for k in ("unauthenticated", "invalid_grant", "oauth", "401 unauthorized")):
            err_type = "auth_error"
        else:
            err_type = "cli_error"
        return {
            "is_error": True,
            "error_type": err_type,
            "is_rate_limit": False,
            "matched_pattern": None,
            "retry_after_s": None,
            "reason": (err.strip() or out.strip() or f"فشل تنفيذ agy (رمز الخروج {returncode})"),
        }

    return {
        "is_error": False,
        "error_type": None,
        "is_rate_limit": False,
        "matched_pattern": None,
        "retry_after_s": None,
        "reason": "OK",
    }


def compute_rate_limit_backoff(
    attempt: int,
    base_delay_s: float = 2.0,
    max_delay_s: float = 30.0,
    jitter_ratio: float = 0.25,
    retry_after_s: Optional[float] = None,
    rng: Optional[random.Random] = None,
) -> float:
    """حساب زمن الانتظار التصاعدي مع التشتيت العشوائي (Exponential Backoff + Jitter) عند حدوث 429."""
    att = max(1, int(attempt))
    base = max(0.05, float(base_delay_s))
    cap = max(base, float(max_delay_s))
    exp_delay = min(cap, base * (2 ** (att - 1)))

    rand_src = rng if rng is not None else random
    j_ratio = max(0.0, min(0.5, float(jitter_ratio)))
    if j_ratio > 0.0:
        min_j = exp_delay * min(0.05, j_ratio * 0.25)
        max_j = exp_delay * j_ratio
        jitter = rand_src.uniform(min_j, max_j)
    else:
        jitter = 0.0

    delay = min(cap, exp_delay + jitter)
    if retry_after_s is not None and retry_after_s > 0:
        delay = min(cap, max(delay, float(retry_after_s)))
    return round(delay, 3)


def run_agy_lean(
    prompt: str,
    model: str = "gemini-3.8-flash-high",
    mode: str = "ask",
    files: Optional[List[str]] = None,
    background: bool = True,
    auto_fallback: bool = True,
    timeout_s: int = 180,
    effort: str = "",
    json_schema: str = "",
    lean_home_dir: Optional[str] = None,
    qdata: Optional[Dict[str, Any]] = None,
    max_stale_age_s: float = 1800.0,
    fail_on_stale: bool = False,
    max_retries: int = 2,
    backoff_base_s: float = 2.0,
    backoff_max_s: float = 30.0,
    sleep_fn: Optional[Callable[[float], None]] = None,
    runner_fn: Optional[Callable[..., Any]] = None,
) -> Dict[str, Any]:
    """تشغيل agy في بيئة HOME معزولة ومجلد عمل مؤقت بعد التحقق من حارس الكوتة المزدوج ودعم التراجع الأسي عند 429 وتنظيف الجلسة."""
    chosen_model, quota_info = select_best_model(
        preferred_model=model,
        background=background,
        auto_fallback=auto_fallback,
        qdata=qdata,
        max_stale_age_s=max_stale_age_s,
        fail_on_stale=fail_on_stale,
    )
    if not quota_info["safe"]:
        return {
            "ok": False,
            "error": quota_info["reason"],
            "error_type": "quota_guard",
            "quota": quota_info,
            "model": chosen_model,
            "attempts": 0,
            "retried_rate_limit": False,
            "backoff_delays_s": [],
            "response": "",
            "usage": {},
        }

    lean_home = prepare_lean_home(lean_home_dir)
    cli_mode = normalize_mode(mode)
    effective_sleep = sleep_fn if sleep_fn is not None else time.sleep
    effective_runner = runner_fn if runner_fn is not None else subprocess.run

    with tempfile.TemporaryDirectory(prefix="agy_lean_ws_") as raw_ws:
        ws_dir = os.path.realpath(raw_ws)
        attached_names: List[str] = []
        used_names: set = set()
        inline_blocks: List[str] = []
        total_inline_bytes = 0
        is_ask_mode = (mode or "ask").strip().lower() == "ask"
        for idx, fpath in enumerate(files or [], 1):
            if not fpath or not os.path.exists(fpath):
                raise FileNotFoundError(f"الملف المرفق غير موجود: {fpath}")
            real_f = os.path.realpath(fpath)
            bname = os.path.basename(real_f)
            if bname in used_names:
                stem, ext = os.path.splitext(bname)
                bname = f"{stem}_{idx}{ext}"
            used_names.add(bname)
            dst_f = os.path.join(ws_dir, bname)
            try:
                os.link(real_f, dst_f)
            except Exception:
                shutil.copy2(real_f, dst_f)
            fsize = os.path.getsize(real_f)
            ext_low = os.path.splitext(bname)[1].lower()
            if is_ask_mode and fsize <= 65536 and total_inline_bytes + fsize <= 90000 and ext_low in (".txt", ".md", ".json", ".py", ".kt", ".ts", ".js", ".html", ".css", ".sql", ".sh", ".yaml", ".yml", ".xml"):
                try:
                    txt_c = open(real_f, encoding="utf-8").read()
                    inline_blocks.append(f"=== FILE: {bname} ===\n{txt_c}")
                    total_inline_bytes += fsize
                    continue
                except Exception:
                    pass
            attached_names.append(bname)

        final_prompt = prompt
        if inline_blocks:
            joined_inline = "\n\n".join(inline_blocks)
            final_prompt = f"[محتوى الملفات المرفقة مدمج أدناه — أجب مباشرة في جولة واحدة دون استدعاء أداة view_file]\n\n{joined_inline}\n\n{final_prompt}"
        if attached_names:
            refs = " ".join(f"@{name}" for name in attached_names if f"@{name}" not in final_prompt)
            if refs:
                final_prompt = f"{refs}\n\n{final_prompt}"

        env = dict(os.environ)
        env["HOME"] = lean_home
        env["PAGER"] = "cat"

        total_allowed_attempts = max(1, 1 + int(max_retries))
        backoff_delays_s: List[float] = []
        active_model = chosen_model
        last_cleanup_info: Dict[str, Any] = {}
        last_res: Any = None
        last_resp_txt: str = ""
        last_usage: Dict[str, Any] = {}
        last_err_info: Dict[str, Any] = {}
        t0_total = time.time()

        for attempt_idx in range(1, total_allowed_attempts + 1):
            cmd = [
                AGY_BIN,
                "-p",
                final_prompt,
                "--mode",
                cli_mode,
                "--dangerously-skip-permissions",
                "--disable-slash-commands",
                "--output-format",
                "json",
            ]
            if active_model:
                cmd += ["--model", active_model]
            # لا تمرر --effort إذا كان اسم النموذج يتضمن الطبقة سلفاً مثل (High) أو كان من عائلة Claude التي ترفض --effort
            model_low = (active_model or "").lower()
            supports_effort = not (
                any(t in model_low for t in ("(high)", "(medium)", "(low)", "claude", "opus", "sonnet", "haiku"))
            )
            if effort and supports_effort:
                cmd += ["--effort", effort]
            if json_schema:
                cmd += ["--json-schema", json_schema]

            pre_snapshot = _snapshot_session_subdirs(lean_home)
            conv_id: Optional[str] = None
            try:
                try:
                    res = effective_runner(
                        cmd,
                        cwd=ws_dir,
                        env=env,
                        capture_output=True,
                        text=True,
                        timeout=timeout_s,
                    )
                except subprocess.TimeoutExpired:
                    last_cleanup_info = _cleanup_lean_conv(
                        lean_home, conv_id=None, pre_snapshot=pre_snapshot, sweep_all_idle=True
                    )
                    return {
                        "ok": False,
                        "error": f"انتهت مهلة الاستدعاء ({timeout_s}ث)",
                        "error_type": "timeout",
                        "quota": quota_info,
                        "model": active_model,
                        "lean_home": lean_home,
                        "cleanup": last_cleanup_info,
                        "attempts": attempt_idx,
                        "retried_rate_limit": len(backoff_delays_s) > 0,
                        "backoff_delays_s": backoff_delays_s,
                        "response": "",
                        "usage": {},
                    }

                resp_txt, usage, conv_id = _extract_agy_json(res.stdout)
            finally:
                last_cleanup_info = _cleanup_lean_conv(
                    lean_home, conv_id=conv_id, pre_snapshot=pre_snapshot, sweep_all_idle=True
                )

            if resp_txt is None:
                resp_txt = (res.stdout or "").strip()

            err_info = classify_agy_error(
                stdout_text=res.stdout or "",
                stderr_text=res.stderr or "",
                returncode=res.returncode,
                resp_txt=resp_txt,
            )
            last_res = res
            last_resp_txt = resp_txt
            last_usage = usage
            last_err_info = err_info

            if not err_info["is_error"]:
                elapsed_s = round(time.time() - t0_total, 2)
                return {
                    "ok": True,
                    "returncode": res.returncode,
                    "error_type": None,
                    "model": active_model,
                    "mode": cli_mode,
                    "elapsed_s": elapsed_s,
                    "quota": quota_info,
                    "lean_home": lean_home,
                    "cleanup": last_cleanup_info,
                    "attached_files": attached_names,
                    "attempts": attempt_idx,
                    "retried_rate_limit": len(backoff_delays_s) > 0,
                    "backoff_delays_s": backoff_delays_s,
                    "response": resp_txt,
                    "usage": usage,
                    "stderr": "",
                }

            # إذا كان الخطأ تجاوز معدل الطلبات (429 / ResourceExhausted) ولم نستنفد المحاولات، ننتظر بـ Exponential Backoff + Jitter
            if err_info["error_type"] == "rate_limit" and attempt_idx < total_allowed_attempts:
                delay_s = compute_rate_limit_backoff(
                    attempt=attempt_idx,
                    base_delay_s=backoff_base_s,
                    max_delay_s=backoff_max_s,
                    retry_after_s=err_info.get("retry_after_s"),
                )
                backoff_delays_s.append(delay_s)
                effective_sleep(delay_s)
                continue

            # أي خطأ آخر غير 429 أو بعد استنفاد محاولات 429 نتوقف فوراً
            break

        elapsed_s = round(time.time() - t0_total, 2)
        stderr_str = (last_res.stderr or "").strip() if last_res is not None else ""
        error_msg = last_err_info.get("reason") or stderr_str or "فشل استدعاء agy"
        return {
            "ok": False,
            "returncode": last_res.returncode if last_res is not None else 1,
            "error": error_msg,
            "error_type": last_err_info.get("error_type") or "cli_error",
            "model": active_model,
            "mode": cli_mode,
            "elapsed_s": elapsed_s,
            "quota": quota_info,
            "lean_home": lean_home,
            "cleanup": last_cleanup_info,
            "attached_files": attached_names,
            "attempts": len(backoff_delays_s) + 1,
            "retried_rate_limit": len(backoff_delays_s) > 0,
            "backoff_delays_s": backoff_delays_s,
            "response": last_resp_txt,
            "usage": last_usage,
            "stderr": stderr_str,
        }


def main() -> int:
    ap = argparse.ArgumentParser(description="استدعاء agy في بيئة معزولة خالية من MCP مع حارس الكوتة الحي")
    ap.add_argument("-p", "--prompt", default="", help="نص الموجه المراد إرساله إلى agy")
    ap.add_argument("--file", "-f", action="append", default=[], help="إرفاق ملف محدد في مجلد العمل المعزول (قابل للتكرار)")
    ap.add_argument("--model", default="gemini-3.8-flash-high", help="اسم النموذج (الافتراضي: gemini-3.8-flash-high)")
    ap.add_argument("--mode", default="ask", help="وضع التشغيل: ask/plan (افتراضي للقراءة فقط) أو auto")
    ap.add_argument("--effort", default="", help="مستوى التفكير: low|medium|high")
    ap.add_argument("--timeout", type=int, default=180, help="المهلة بالثواني")
    ap.add_argument("--max-retries", type=int, default=2, help="عدد محاولات الإعادة عند أخطاء 429 / ResourceExhausted")
    ap.add_argument("--max-workers", type=int, default=16, help="الحد الأقصى للعمال عند حساب التوازي الآمن")
    ap.add_argument("--foreground", action="store_true", help="استخدام حد الوكيل الرئيسي (10%%) بدلاً من حد الخلفية (15%%)")
    ap.add_argument("--no-fallback", action="store_true", help="عدم التبديل التلقائي إلى Gemini عند حظر كوتة Claude")
    ap.add_argument("--check-quota", action="store_true", help="فحص الكوتة الحية وعرض حالة المجموعات فقط")
    ap.add_argument("--recommend-workers", action="store_true", help="حساب معدل استهلاك الكوتة وعدد العمال المتوازيين الموصى به")
    ap.add_argument("--verify-isolation", action="store_true", help="بناء وفحص بيئة HOME المعزولة فقط")
    ap.add_argument("--json", action="store_true", help="إخراج النتيجة الكاملة بصيغة JSON")
    args = ap.parse_args()

    if args.recommend_workers:
        qdata = fetch_quota_data(refresh_live=True)
        rec = recommend_concurrency_from_quota(
            model_hint=args.model,
            max_workers=args.max_workers,
            background=not args.foreground,
            qdata=qdata,
        )
        print(json.dumps(rec, ensure_ascii=False, indent=2))
        return 0 if rec["safe"] else 1

    if args.check_quota:
        qdata = fetch_quota_data(refresh_live=True)
        report = {
            "gemini_flash": check_quota("gemini-3.8-flash-high", background=not args.foreground, qdata=qdata),
            "gemini_argon": check_quota("gemini-4-argon-high", background=not args.foreground, qdata=qdata),
            "claude": check_quota("claude-opus-5.5-high", background=not args.foreground, qdata=qdata),
            "gpt": check_quota("gpt-oss-120b", background=not args.foreground, qdata=qdata),
            "concurrency_recommendation": recommend_concurrency_from_quota(
                model_hint=args.model,
                max_workers=args.max_workers,
                background=not args.foreground,
                qdata=qdata,
            ),
        }
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    if args.verify_isolation:
        lh = prepare_lean_home()
        iso = verify_lean_home_isolation(lh)
        print(json.dumps(iso, ensure_ascii=False, indent=2))
        return 0 if iso["isolated"] else 1

    if not args.prompt:
        ap.error("يرجى تمرير --prompt أو --check-quota أو --recommend-workers أو --verify-isolation")

    result = run_agy_lean(
        prompt=args.prompt,
        model=args.model,
        mode=args.mode,
        files=args.file,
        background=not args.foreground,
        auto_fallback=not args.no_fallback,
        timeout_s=args.timeout,
        effort=args.effort,
        max_retries=args.max_retries,
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        if result["ok"]:
            print(result["response"])
        else:
            print(f"[خطأ agy_lean] {result.get('error') or result.get('stderr')}", file=sys.stderr)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
