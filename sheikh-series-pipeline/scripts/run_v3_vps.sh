#!/bin/bash
# run_v3_vps.sh <tag> — تشغيل درس واحد على الـVPS وحده، داخل سقف ذاكرة واحد:
#   1) كاش ASR: إن غاب يُولَّد محليًا (faster-whisper int8 على المعالج) — بلا MLX ولا مضيف خارجي.
#   2) محاذاة v3: مراسي v2 من النص المرجعي + كاش ASR ← معايرة تتابعية ← تقطيع محكوم ← تحقق متقاطع ← إعادة محاذاة.
# يُستدعى عادة داخل: systemd-run --scope -p MemoryMax=${MEMORY_GUARD_MB:-2000M} --unit=v3<tag> --collect
set -euo pipefail
TAG=${1:?الاستخدام: run_v3_vps.sh <tag>}
ROOT=${SERIES_WORKSPACE:-/root/workspace}
WORK=${V3_WORKDIR:-$ROOT/ytb-build/v2}
SKILL_DIR=${SKILL_DIR:-$(cd "$(dirname "$0")/.." && pwd)}
CACHE_DIR=${ALIGN_CACHE_DIR:-$HOME/.cache/hawshat/wwords}
PY=${ALIGN_PY:-/root/venvs/ctc/bin/python}     # بيئة torch/rapidfuzz
ASR_PY=${ASR_PY:-/root/venvs/asr/bin/python}   # بيئة faster-whisper
AUDIO=${AUDIO:-}
if [ -z "$AUDIO" ]; then
  for ext in wav mp3 m4a; do
    [ -s "$WORK/audio/kahf539_$TAG.$ext" ] && AUDIO=$WORK/audio/kahf539_$TAG.$ext && break
  done
fi
TXT=${TXT:-$WORK/txt/kahf539_$TAG.txt}
OUTDIR=${V3_OUTDIR:-$WORK/v3out}
V1=${V1:-$(ls $ROOT/ytb/sharawi/539/${TAG}_*.force.align.json 2>/dev/null | head -1 || true)}
LOG=${V3_LOG:-$WORK/logs/v3s_$TAG.log}

[ -s "$AUDIO" ] || { echo "[$TAG] ✗ لا يوجد صوت: $AUDIO"; exit 2; }
[ -s "$TXT" ]   || { echo "[$TAG] ✗ لا يوجد نص مرجعي: $TXT"; exit 2; }
mkdir -p "$CACHE_DIR" "$OUTDIR" "$WORK/logs"

# --- 1) كاش ASR محلي ---------------------------------------------------------
CACHE=$("$ASR_PY" "$SKILL_DIR/scripts/gen_asr_cache.py" --audio "$AUDIO" --prompt-from-txt "$TXT" --print-key)
if [ ! -s "$CACHE" ]; then
  echo "[$TAG] كاش ASR غائب ⇒ يُولَّد محليًا (نموذج ${ASR_MODEL:-Systran/faster-whisper-small} · ${ASR_COMPUTE_TYPE:-int8} · ${ASR_DEVICE:-cpu})"
  "$ASR_PY" "$SKILL_DIR/scripts/gen_asr_cache.py" --audio "$AUDIO" --cache "$CACHE" \
     --prompt-from-txt "$TXT" ${ASR_BEAM:+--beam "$ASR_BEAM"} 2>&1 | tee -a "$LOG"
else
  echo "[$TAG] كاش ASR موجود: $CACHE"
fi

# --- 2) محاذاة v3 -----------------------------------------------------------
ARGS=(--audio "$AUDIO" --txt "$TXT" --cache "$CACHE" --outdir "$OUTDIR" --tag "$TAG"
      --calib-seq --target "${V3_TARGET:-70}" --resplit "${V3_RESPLIT:-20}" --batch "${V3_BATCH:-1}")
[ -n "$V1" ] && ARGS+=(--v1 "$V1")
echo "[$TAG] تشغيل v3 (سقف الذاكرة ${MEMORY_GUARD_MB:-2000}M) → $OUTDIR/v3_$TAG.json"
"$PY" -u "$SKILL_DIR/scripts/v3_align.py" "${ARGS[@]}" 2>&1 | tee -a "$LOG"
echo "[$TAG] ✓ انتهى: $(ls -la "$OUTDIR/v3_$TAG.json" 2>/dev/null | awk '{print int($5/1024)"KB"}')"
