#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""agy_lean.py — استدعاء Antigravity CLI (agy) في بيئة HOME معزولة خالية من MCP والإضافات."""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REAL_HOME = Path(os.environ.get("AGY_REAL_HOME") or Path.home())
AGY_BIN = os.environ.get("AGY_BIN") or shutil.which("agy") or str(REAL_HOME / ".local" / "bin" / "agy")


def _safe_symlink(src: Path, dst: Path) -> None:
    if not src.exists():
        return
    if dst.is_symlink() or dst.exists():
        if dst.is_symlink() and os.readlink(dst) == str(src):
            return
        shutil.rmtree(dst, ignore_errors=True) if (dst.is_dir() and not dst.is_symlink()) else dst.unlink(missing_ok=True)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.symlink_to(src)


def prepare_lean_home(lean_home_dir: Optional[str] = None) -> str:
    """بناء بيئة HOME معزولة تربط ملفات المصادقة فقط بدون أي MCP أو إضافات أو مهارات."""
    home_path = Path(lean_home_dir) if lean_home_dir else Path(tempfile.mkdtemp(prefix="agy_lean_home_"))
    home_path.mkdir(parents=True, exist_ok=True)

    if sys.platform == "darwin" and (REAL_HOME / "Library").is_dir():
        _safe_symlink(REAL_HOME / "Library", home_path / "Library")

    real_gemini, lean_gemini = REAL_HOME / ".gemini", home_path / ".gemini"
    lean_gemini.mkdir(parents=True, exist_ok=True)
    for fname in ("jetski-standalone-oauth-token", "oauth_creds.json", "google_accounts.json", "installation_id", "state.json"):
        _safe_symlink(real_gemini / fname, lean_gemini / fname)

    for sub_dir, files in (
        ("antigravity", ("antigravity_state.pbtxt", "installation_id", "bin", "lib")),
        ("antigravity-cli", ("antigravity-oauth-token", "installation_id", "jetski_state.pbtxt", "bin")),
    ):
        (lean_gemini / sub_dir).mkdir(parents=True, exist_ok=True)
        for fname in files:
            _safe_symlink(real_gemini / sub_dir / fname, lean_gemini / sub_dir / fname)

    lean_cli = lean_gemini / "antigravity-cli"
    for sub in ("conversations", "annotations", "brain", "presence", "implicit", "log", "cache"):
        (lean_cli / sub).mkdir(parents=True, exist_ok=True)

    lean_cli_settings = {"allowNonWorkspaceAccess": True, "notifications": False, "permissions": {"allow": []}, "runningLightSpeed": "fast", "showFeedbackSurvey": False, "toolPermission": "always-proceed", "trustedWorkspaces": ["/tmp", "/private/tmp", "/var/folders", "/private/var/folders", str(REAL_HOME)], "verbosity": "low"}
    (lean_cli / "settings.json").write_text(json.dumps(lean_cli_settings, indent=2), encoding="utf-8")

    lean_cfg_dir = lean_gemini / "config"
    lean_cfg_dir.mkdir(parents=True, exist_ok=True)
    (lean_cfg_dir / ".migrated").write_text("", encoding="utf-8")
    lean_cfg = {"plugins": {}, "userSettings": {"autoExecutionPolicy": "CASCADE_COMMANDS_AUTO_EXECUTION_EAGER", "enableTerminalSandbox": False, "globalPermissionGrants": {"allow": []}, "nonWorkspaceFileAccessPolicy": "AGENT_SETTING_POLICY_ALLOW", "permissionGrantsV2Migrated": True, "useAiCredits": False}}
    (lean_cfg_dir / "config.json").write_text(json.dumps(lean_cfg, indent=2), encoding="utf-8")
    return str(home_path)


def _cleanup_lean_conv(lean_home_dir: str, conv_id: Optional[str]) -> None:
    """حذف ملفات الجلسة الخاصة بمعرف المحادثة الحالي فقط دون المساس بأي عمليات متوازية."""
    if not conv_id:
        return
    base_dir = Path(lean_home_dir) / ".gemini" / "antigravity-cli"
    for sub, suffixes in (("conversations", (".pb", ".db", ".db-wal", ".db-shm")), ("annotations", (".pbtxt",)), ("presence", (".lock",)), ("implicit", (".pb",))):
        for suffix in suffixes:
            (base_dir / sub / f"{conv_id}{suffix}").unlink(missing_ok=True)
    shutil.rmtree(base_dir / "brain" / conv_id, ignore_errors=True)


def _extract_agy_json(stdout_text: str) -> Tuple[Optional[str], Dict[str, Any], Optional[str]]:
    txt = (stdout_text or "").strip()
    if not txt:
        return None, {}, None
    candidates = [ln.strip() for ln in reversed(txt.splitlines()) if ln.strip().startswith("{")]
    idx, ridx = txt.find("{"), txt.rfind("}")
    if idx != -1 and ridx > idx:
        candidates.append(txt[idx : ridx + 1])
    for cand in candidates:
        try:
            payload = json.loads(cand)
            if isinstance(payload, dict) and "response" in payload:
                return (payload.get("response") or "").strip(), (payload.get("usage") or {}), payload.get("conversation_id")
        except Exception:
            pass
    return None, {}, None


def run_agy_lean(
    prompt: str,
    model: str = "",
    mode: str = "ask",
    workspace: Optional[str] = None,
    files: Optional[List[str]] = None,
    timeout_s: int = 180,
    effort: str = "",
    json_schema: str = "",
    lean_home_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """تشغيل agy في بيئة HOME معزولة ومجلد عمل خاص بالعملية مع تنظيف آمن في finally."""
    owns_home, owns_ws = lean_home_dir is None, workspace is None
    lean_home = prepare_lean_home(lean_home_dir)
    ws_dir = os.path.realpath(workspace) if workspace else os.path.realpath(tempfile.mkdtemp(prefix="agy_lean_ws_"))
    os.makedirs(ws_dir, exist_ok=True)
    cli_mode = mode.strip().lower() if (mode or "").strip().lower() in ("accept-edits", "auto") else "plan"
    conv_id: Optional[str] = None

    try:
        attached_names: List[str] = []
        for idx, fpath in enumerate(files or [], 1):
            real_f = Path(fpath).resolve()
            if not real_f.exists():
                raise FileNotFoundError(f"الملف المرفق غير موجود: {fpath}")
            bname = real_f.name if real_f.name not in attached_names else f"{real_f.stem}_{idx}{real_f.suffix}"
            dst_f = Path(ws_dir) / bname
            if not dst_f.exists():
                try:
                    os.link(real_f, dst_f)
                except OSError:
                    shutil.copy2(real_f, dst_f)
            attached_names.append(bname)

        refs = " ".join(f"@{n}" for n in attached_names if f"@{n}" not in prompt)
        final_prompt = f"{refs}\n\n{prompt}" if refs else prompt
        cmd = [AGY_BIN, "-p", final_prompt, "--mode", cli_mode, "--dangerously-skip-permissions", "--disable-slash-commands", "--output-format", "json"]
        if model:
            cmd += ["--model", model]
        if effort and not any(t in (model or "").lower() for t in ("(high)", "(medium)", "(low)", "claude", "opus", "sonnet", "haiku")):
            cmd += ["--effort", effort]
        if json_schema:
            cmd += ["--json-schema", json_schema]

        t0 = time.time()
        try:
            res = subprocess.run(cmd, cwd=ws_dir, env={**os.environ, "HOME": lean_home, "PAGER": "cat"}, capture_output=True, text=True, timeout=timeout_s)
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": f"انتهت مهلة الاستدعاء ({timeout_s}ث)", "model": model, "response": "", "usage": {}}

        resp_txt, usage, conv_id = _extract_agy_json(res.stdout)
        resp_txt = (res.stdout or "").strip() if resp_txt is None else resp_txt
        ok = res.returncode == 0 and bool(resp_txt)
        return {"ok": ok, "returncode": res.returncode, "model": model, "mode": cli_mode, "elapsed_s": round(time.time() - t0, 2), "response": resp_txt, "usage": usage, "stderr": (res.stderr or "").strip() if not ok else ""}
    finally:
        _cleanup_lean_conv(lean_home, conv_id)
        if owns_ws:
            shutil.rmtree(ws_dir, ignore_errors=True)
        if owns_home:
            shutil.rmtree(lean_home, ignore_errors=True)


def main() -> int:
    ap = argparse.ArgumentParser(description="استدعاء agy في بيئة HOME معزولة خالية من MCP والإضافات")
    ap.add_argument("-p", "--prompt", required=True, help="نص الموجه المراد إرساله إلى agy")
    ap.add_argument("--model", default="", help="اسم النموذج الاختياري")
    ap.add_argument("-w", "--workspace", default=None, help="مجلد العمل الاختياري (ينشئ مجلداً مؤقتاً معزولاً افتراضياً)")
    ap.add_argument("-f", "--file", action="append", default=[], help="إرفاق ملف في مجلد العمل المعزول (قابل للتكرار)")
    ap.add_argument("--mode", default="ask", help="وضع التشغيل: ask/plan أو auto")
    ap.add_argument("--effort", default="", help="مستوى التفكير: low|medium|high")
    ap.add_argument("--timeout", type=int, default=180, help="المهلة بالثواني")
    ap.add_argument("--json", action="store_true", help="إخراج النتيجة الكاملة بصيغة JSON")
    args = ap.parse_args()

    result = run_agy_lean(prompt=args.prompt, model=args.model, mode=args.mode, workspace=args.workspace, files=args.file, timeout_s=args.timeout, effort=args.effort)
    print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else (result["response"] if result["ok"] else ""), end="\n" if (args.json or result["ok"]) else "")
    if not args.json and not result["ok"]:
        print(f"[خطأ agy_lean] {result.get('error') or result.get('stderr')}", file=sys.stderr)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
