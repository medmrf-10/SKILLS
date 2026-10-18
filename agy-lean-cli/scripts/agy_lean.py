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
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Any, Dict, List, Optional, Tuple


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
    "/tmp/agy_quota_snapshot.json",
    "/root/workspace/ytb-build/live_quota.json",
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


def fetch_quota_data(refresh_live: bool = False, max_cache_age_s: float = 300.0) -> Optional[Dict[str, Any]]:
    """قراءة بيانات الكوتة من اللقطة المحلية الحديثة أو استدعاء antigravity-usage مباشرة."""
    if not refresh_live:
        for qpath in QUOTA_SNAPSHOT_PATHS:
            if os.path.exists(qpath):
                try:
                    age = time.time() - os.path.getmtime(qpath)
                    if age <= max_cache_age_s:
                        with open(qpath, encoding="utf-8") as f:
                            data = json.load(f)
                        if isinstance(data, dict) and data.get("models"):
                            return data
                except Exception:
                    continue

    if QUOTA_BIN and os.path.exists(QUOTA_BIN) and os.access(QUOTA_BIN, os.X_OK):
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
                    return data
        except Exception:
            pass

    for qpath in QUOTA_SNAPSHOT_PATHS:
        if os.path.exists(qpath):
            try:
                with open(qpath, encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict) and data.get("models"):
                    return data
            except Exception:
                continue
    return None


def _match_model_entry(models: List[Dict[str, Any]], model_hint: str) -> Optional[Dict[str, Any]]:
    hint = (model_hint or "gemini").lower()
    want_claude = any(k in hint for k in ("claude", "opus", "sonnet"))
    want_gpt = "gpt" in hint
    for m in models:
        lbl = (m.get("label") or "").lower()
        if want_claude and any(k in lbl for k in ("claude", "opus", "sonnet")):
            return m
        if want_gpt and "gpt" in lbl:
            return m
        if not want_claude and not want_gpt and ("gemini 3.8 flash" in lbl or "gemini 4 argon" in lbl):
            return m
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
    """تقييم حتمي لمدى أمان استهلاك الكوتة لنموذج محدد وفق قاعدتَي الـ5 ساعات والاحتياطي الأسبوعي."""
    label = target.get("label") or "Unknown Model"
    rem = float(target.get("remainingPercentage") if target.get("remainingPercentage") is not None else 1.0)
    reset_ms = float(target.get("timeUntilResetMs") or 0.0)
    reset_hours = reset_ms / (1000.0 * 3600.0)
    exhausted = bool(target.get("isExhausted", False))
    floor_5h = min_5h_bg if background else min_5h_fg
    is_weekly_window = reset_hours > weekly_window_threshold_h

    if exhausted or rem < floor_5h:
        mode_lbl = "الوكلاء الخلفيين (15%)" if background else "الوكيل الرئيسي (10%)"
        return {
            "safe": False,
            "label": label,
            "remaining_pct": round(rem * 100.0, 2),
            "remaining_ratio": rem,
            "reset_hours": round(reset_hours, 2),
            "window_type": "weekly_or_rolling" if is_weekly_window else "5h",
            "reason": (
                f"حظر الكوتة لـ [{label}]: المتبقي {rem*100:.2f}% أقل من حد الأمان لـ{mode_lbl} "
                f"({floor_5h*100:.0f}%)"
            ),
        }

    if is_weekly_window and reset_hours > weekly_unlock_hours and rem <= min_weekly_reserve:
        return {
            "safe": False,
            "label": label,
            "remaining_pct": round(rem * 100.0, 2),
            "remaining_ratio": rem,
            "reset_hours": round(reset_hours, 2),
            "window_type": "weekly_or_rolling",
            "reason": (
                f"حظر الاحتياطي الأسبوعي لـ [{label}]: المتبقي {rem*100:.2f}% <= {min_weekly_reserve*100:.0f}% "
                f"وباقي {reset_hours:.1f} ساعة (> {weekly_unlock_hours:.0f} ساعة) على التجديد"
            ),
        }

    return {
        "safe": True,
        "label": label,
        "remaining_pct": round(rem * 100.0, 2),
        "remaining_ratio": rem,
        "reset_hours": round(reset_hours, 2),
        "window_type": "weekly_or_rolling" if is_weekly_window else "5h",
        "reason": "OK",
    }


def check_quota(
    model_hint: str = "gemini",
    background: bool = True,
    refresh_live: bool = False,
    qdata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """فحص الكوتة الحية لنموذج محدد (gemini / claude / gpt)."""
    data = qdata if qdata is not None else fetch_quota_data(refresh_live=refresh_live)
    if not data or not data.get("models"):
        return {
            "safe": True,
            "label": model_hint,
            "remaining_pct": 100.0,
            "remaining_ratio": 1.0,
            "reset_hours": 0.0,
            "window_type": "unknown",
            "reason": "تعذر قراءة لقطة الكوتة المحلية؛ السماح الافتراضي",
        }
    target = _match_model_entry(data["models"], model_hint)
    if not target:
        return {
            "safe": True,
            "label": model_hint,
            "remaining_pct": 100.0,
            "remaining_ratio": 1.0,
            "reset_hours": 0.0,
            "window_type": "unknown",
            "reason": "النموذج غير موجود في اللقطة",
        }
    return evaluate_quota_entry(target, background=background)


def select_best_model(
    preferred_model: str = "gemini-3.8-flash-high",
    background: bool = True,
    auto_fallback: bool = True,
    qdata: Optional[Dict[str, Any]] = None,
) -> Tuple[str, Dict[str, Any]]:
    """اختيار النموذج الأنسب مع التحويل التلقائي إلى Gemini إذا كانت كوتة Claude محظورة."""
    q_pref = check_quota(preferred_model, background=background, qdata=qdata)
    if q_pref["safe"]:
        return preferred_model, q_pref
    if auto_fallback:
        fallback = "gemini-3.8-flash-high"
        q_fb = check_quota(fallback, background=background, qdata=qdata)
        if q_fb["safe"]:
            return fallback, q_fb
    return preferred_model, q_pref


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

    for sub in ("conversations", "annotations", "brain", "presence", "implicit", "log", "cache"):
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
    for rel_forbidden in FORBIDDEN_LEAN_PATHS:
        target_p = os.path.join(lean_home_dir, rel_forbidden)
        if os.path.islink(target_p) or os.path.exists(target_p):
            try:
                if os.path.isdir(target_p) and not os.path.islink(target_p):
                    shutil.rmtree(target_p, ignore_errors=True)
                else:
                    os.remove(target_p)
            except OSError:
                pass

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
            cfg = json.load(open(cfg_json, encoding="utf-8"))
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


def _cleanup_lean_conv(lean_home_dir: str, conv_id: Optional[str]) -> None:
    if not conv_id:
        return
    base_dir = os.path.join(lean_home_dir, ".gemini", "antigravity-cli")
    for sub, suffixes in (
        ("conversations", (".pb", ".db", ".db-wal", ".db-shm")),
        ("annotations", (".pbtxt",)),
        ("presence", (".lock",)),
        ("implicit", (".pb",)),
    ):
        sub_dir = os.path.join(base_dir, sub)
        for suffix in suffixes:
            p = os.path.join(sub_dir, conv_id + suffix)
            try:
                if os.path.exists(p):
                    os.remove(p)
            except OSError:
                pass
    brain_dir = os.path.join(base_dir, "brain", conv_id)
    if os.path.isdir(brain_dir):
        shutil.rmtree(brain_dir, ignore_errors=True)


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
) -> Dict[str, Any]:
    """تشغيل agy في بيئة HOME معزولة ومجلد عمل مؤقت بعد التحقق من حارس الكوتة."""
    chosen_model, quota_info = select_best_model(
        preferred_model=model,
        background=background,
        auto_fallback=auto_fallback,
    )
    if not quota_info["safe"]:
        return {
            "ok": False,
            "error": quota_info["reason"],
            "quota": quota_info,
            "model": chosen_model,
            "response": "",
            "usage": {},
        }

    lean_home = prepare_lean_home(lean_home_dir)
    cli_mode = normalize_mode(mode)

    with tempfile.TemporaryDirectory(prefix="agy_lean_ws_") as raw_ws:
        ws_dir = os.path.realpath(raw_ws)
        attached_names = []
        for fpath in (files or []):
            if not fpath or not os.path.exists(fpath):
                raise FileNotFoundError(f"الملف المرفق غير موجود: {fpath}")
            real_f = os.path.realpath(fpath)
            bname = os.path.basename(real_f)
            dst_f = os.path.join(ws_dir, bname)
            try:
                os.link(real_f, dst_f)
            except Exception:
                shutil.copy2(real_f, dst_f)
            attached_names.append(bname)

        final_prompt = prompt
        if attached_names:
            refs = " ".join(f"@{name}" for name in attached_names if f"@{name}" not in final_prompt)
            if refs:
                final_prompt = f"{refs}\n\n{final_prompt}"

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
        if chosen_model:
            cmd += ["--model", chosen_model]
        if effort:
            cmd += ["--effort", effort]
        if json_schema:
            cmd += ["--json-schema", json_schema]

        env = dict(os.environ)
        env["HOME"] = lean_home
        env["PAGER"] = "cat"

        t0 = time.time()
        try:
            res = subprocess.run(
                cmd,
                cwd=ws_dir,
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout_s,
            )
            elapsed_s = round(time.time() - t0, 2)
        except subprocess.TimeoutExpired:
            return {
                "ok": False,
                "error": f"انتهت مهلة الاستدعاء ({timeout_s}ث)",
                "quota": quota_info,
                "model": chosen_model,
                "response": "",
                "usage": {},
            }

        resp_txt, usage, conv_id = _extract_agy_json(res.stdout)
        _cleanup_lean_conv(lean_home, conv_id)

        if resp_txt is None:
            resp_txt = (res.stdout or "").strip()

        ok = res.returncode == 0 and bool(resp_txt)
        return {
            "ok": ok,
            "returncode": res.returncode,
            "model": chosen_model,
            "mode": cli_mode,
            "elapsed_s": elapsed_s,
            "quota": quota_info,
            "lean_home": lean_home,
            "attached_files": attached_names,
            "response": resp_txt,
            "usage": usage,
            "stderr": (res.stderr or "").strip() if not ok else "",
        }


def main() -> int:
    ap = argparse.ArgumentParser(description="استدعاء agy في بيئة معزولة خالية من MCP مع حارس الكوتة الحي")
    ap.add_argument("-p", "--prompt", default="", help="نص الموجه المراد إرساله إلى agy")
    ap.add_argument("--file", "-f", action="append", default=[], help="إرفاق ملف محدد في مجلد العمل المعزول (قابل للتكرار)")
    ap.add_argument("--model", default="gemini-3.8-flash-high", help="اسم النموذج (الافتراضي: gemini-3.8-flash-high)")
    ap.add_argument("--mode", default="ask", help="وضع التشغيل: ask/plan (افتراضي للقراءة فقط) أو auto")
    ap.add_argument("--effort", default="", help="مستوى التفكير: low|medium|high")
    ap.add_argument("--timeout", type=int, default=180, help="المهلة بالثواني")
    ap.add_argument("--foreground", action="store_true", help="استخدام حد الوكيل الرئيسي (10%) بدلاً من حد الخلفية (15%)")
    ap.add_argument("--no-fallback", action="store_true", help="عدم التبديل التلقائي إلى Gemini عند حظر كوتة Claude")
    ap.add_argument("--check-quota", action="store_true", help="فحص الكوتة الحية وعرض حالة المجموعات فقط")
    ap.add_argument("--verify-isolation", action="store_true", help="بناء وفحص بيئة HOME المعزولة فقط")
    ap.add_argument("--json", action="store_true", help="إخراج النتيجة الكاملة بصيغة JSON")
    args = ap.parse_args()

    if args.check_quota:
        qdata = fetch_quota_data(refresh_live=True)
        report = {
            "gemini": check_quota("gemini", background=not args.foreground, qdata=qdata),
            "claude": check_quota("claude", background=not args.foreground, qdata=qdata),
            "gpt": check_quota("gpt", background=not args.foreground, qdata=qdata),
        }
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    if args.verify_isolation:
        lh = prepare_lean_home()
        iso = verify_lean_home_isolation(lh)
        print(json.dumps(iso, ensure_ascii=False, indent=2))
        return 0 if iso["isolated"] else 1

    if not args.prompt:
        ap.error("يرجى تمرير --prompt أو --check-quota أو --verify-isolation")

    result = run_agy_lean(
        prompt=args.prompt,
        model=args.model,
        mode=args.mode,
        files=args.file,
        background=not args.foreground,
        auto_fallback=not args.no_fallback,
        timeout_s=args.timeout,
        effort=args.effort,
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
