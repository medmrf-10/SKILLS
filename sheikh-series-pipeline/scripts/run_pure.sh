#!/bin/bash
# run_pure.sh [--target auto|mac|vps] [--series <series_dir> [--only <stems>] | <tag>] — المسار النقي (v4.2) الموحد
#
# يتيح اختيار بيئة التنفيذ عند استدعاء المهارة:
#   • --target mac : تشغيل محلي على الماك (Apple Silicon MPS GPU · batch=4 · نافذة 30ث · أسرع بـ 38–53× من CPU)
#   • --target vps : تشغيل على الخادم اللينكس (أو عبر SSH إلى hermes-vps إذا اُستدعي من الماك)
#   • --target auto: يكتشف النظام تلقائيًا (Darwin ⇒ mac ، Linux ⇒ vps)
#   • --series <dir>: معالجة سلسلة كاملة بتحميل النموذج الصوتي مرة واحدة وفك الصوت في الذاكرة بلا ملفات .wav مؤقتة
#
# متغيرات اختيارية:
#   EXEC_TARGET (auto|mac|vps) · VPS_HOST (hermes-vps) · SERIES_WORKSPACE · PURE_WORKDIR · SKILL_DIR
#   PURE_OUT · ALIGN_PY · EM_DEVICE (auto|mps|cuda|cpu) · EM_DTYPE (fp32|fp16) · EM_BATCH · EM_WINDOW
#   SLICE · PIN · MARGIN · STAR · MIN_SCORE · V1 · AUDIO · TXT · FFMPEG · KEEP_WAV (0|1)
set -euo pipefail

TARGET="${EXEC_TARGET:-auto}"
SERIES_DIR=""
ONLY_FILTER=""
while [ $# -gt 0 ]; do
  case "$1" in
    --target)
      TARGET="${2:?حدد الهدف: mac أو vps أو auto}"
      shift 2
      ;;
    --target=*)
      TARGET="${1#*=}"
      shift
      ;;
    --series)
      SERIES_DIR="${2:?حدد مجلد السلسلة بعد --series}"
      shift 2
      ;;
    --series=*)
      SERIES_DIR="${1#*=}"
      shift
      ;;
    --only)
      ONLY_FILTER="${2:?حدد الدروس بعد --only}"
      shift 2
      ;;
    --only=*)
      ONLY_FILTER="${1#*=}"
      shift
      ;;
    *)
      break
      ;;
  esac
done

TAG="${1:-}"
if [ -z "$SERIES_DIR" ] && [ -z "$TAG" ]; then
  echo "الاستخدام: run_pure.sh [--target auto|mac|vps] (--series <series_dir> [--only 001,006] | <tag>)" >&2
  exit 2
fi
OS_NAME="$(uname -s)"

if [ "$TARGET" = "auto" ]; then
  if [ "$OS_NAME" = "Darwin" ]; then
    TARGET="mac"
  else
    TARGET="vps"
  fi
fi

# إذا طُلب --target vps ونحن على الماك، نفّذ عبر SSH على الخادم البعيد إن لم يُطلب التشغيل المحلي
if [ "$TARGET" = "vps" ] && [ "$OS_NAME" = "Darwin" ] && [ "${LOCAL_ONLY:-0}" != "1" ]; then
  VPS_HOST="${VPS_HOST:-hermes-vps}"
  if [ -n "$SERIES_DIR" ]; then
    echo "[سلسلة] توجيه التنفيذ إلى الخادم البعيد ($VPS_HOST)..."
    exec ssh "$VPS_HOST" "SERIES_WORKSPACE=${SERIES_WORKSPACE:-/root/workspace} PURE_WORKDIR=${PURE_WORKDIR:-} PURE_OUT=${PURE_OUT:-} /root/workspace/SKILLS/sheikh-series-pipeline/scripts/run_pure_vps.sh --series $SERIES_DIR ${ONLY_FILTER:+--only $ONLY_FILTER}"
  else
    echo "[$TAG] توجيه التنفيذ إلى الخادم البعيد ($VPS_HOST)..."
    exec ssh "$VPS_HOST" "SERIES_WORKSPACE=${SERIES_WORKSPACE:-/root/workspace} PURE_WORKDIR=${PURE_WORKDIR:-} AUDIO=${AUDIO:-} TXT=${TXT:-} /root/workspace/SKILLS/sheikh-series-pipeline/scripts/run_pure_vps.sh $TAG"
  fi
fi

SKILL_DIR="${SKILL_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"

if [ "$TARGET" = "mac" ]; then
  DEFAULT_ROOT="/Users/macm1pro/workspace"
  DEFAULT_PY="/Users/macm1pro/venvs/ctc/bin/python"
  DEFAULT_DEVICE="mps"
  DEFAULT_WINDOW="30"
  DEFAULT_BATCH="4"
  DEFAULT_LAYERS="0"
else
  DEFAULT_ROOT="/root/workspace"
  DEFAULT_PY="/root/venvs/ctc/bin/python"
  DEFAULT_DEVICE="cpu"
  DEFAULT_WINDOW="20"
  DEFAULT_BATCH="1"
  DEFAULT_LAYERS="0"
fi

ROOT="${SERIES_WORKSPACE:-$DEFAULT_ROOT}"
WORK="${PURE_WORKDIR:-$ROOT/ytb-build/pure}"
PY="${ALIGN_PY:-$DEFAULT_PY}"
OUT="${PURE_OUT:-$WORK/out}"
mkdir -p "$OUT" "$WORK/audio"

if [ -n "$SERIES_DIR" ]; then
  T0=$(date +%s)
  echo "[سلسلة] الهدف=$TARGET | المرحلة ١: انبعاثات الدفعة الكاملة بتحميل النموذج مرة واحدة (جهاز=${EM_DEVICE:-$DEFAULT_DEVICE} · نافذة=${EM_WINDOW:-$DEFAULT_WINDOW}ث · دفعة=${EM_BATCH:-$DEFAULT_BATCH} · طبقات=${LAYERS:-$DEFAULT_LAYERS})"
  EM_SERIES_ARGS=(
    --series-dir "$SERIES_DIR" --out-dir "$OUT"
    --skip-existing
    --engine "${EM_ENGINE:-torch}"
    --device "${EM_DEVICE:-$DEFAULT_DEVICE}"
    --dtype "${EM_DTYPE:-fp32}"
    --batch "${EM_BATCH:-$DEFAULT_BATCH}"
    --window "${EM_WINDOW:-$DEFAULT_WINDOW}"
    --onnx-workers "${ONNX_WORKERS:-2}"
    --onnx-threads "${ONNX_THREADS:-2}"
    --threads "${THREADS:-4}"
    --par-procs "${PAR_PROCS:-1}"
    --par-halves "${PAR_HALVES:-1}"
    --silence-compact "${SILENCE_COMPACT:-0}"
    --silence-rel "${SILENCE_REL:-5.0}"
    --layers "${LAYERS:-$DEFAULT_LAYERS}"
    --seg-sec "${SEG_SEC:-0}"
  )
  [ -n "$ONLY_FILTER" ] && EM_SERIES_ARGS+=(--only "$ONLY_FILTER")
  "$PY" -u "$SKILL_DIR/scripts/extract_emissions.py" "${EM_SERIES_ARGS[@]}"

  T1=$(date +%s)
  echo "[سلسلة] المرحلة ٢: محاذاة الشريحة المتحركة لجميع دروس السلسلة (بلا نموذج)"
  AL_SERIES_ARGS=(
    --series-out "$OUT"
    --slice "${SLICE:-120}" --pin "${PIN:-65}"
    --margin "${MARGIN:-30}" --star "${STAR:-segment}"
    --min-score "${MIN_SCORE:--3.0}"
    --star-pen "${STAR_PEN:--0.9}"
    --solid-handoff "${SOLID_HANDOFF:-1}"
    --island-guard "${ISLAND_GUARD:-0}"
  )
  [ -n "$ONLY_FILTER" ] && AL_SERIES_ARGS+=(--only "$ONLY_FILTER")
  "$PY" -u "$SKILL_DIR/scripts/ctc_pure_align.py" "${AL_SERIES_ARGS[@]}"
  T2=$(date +%s)
  echo "[سلسلة] الزمن الكلي على $TARGET: $((T2-T0))ث = انبعاثات $((T1-T0))ث + محاذاة $((T2-T1))ث | التقرير: $OUT/_series_align_report.json"
  exit 0
fi

AUDIO="${AUDIO:-}"
if [ -z "$AUDIO" ]; then
  for ext in wav mp3 m4a opus webm; do
    [ -s "$WORK/audio/$TAG.$ext" ] && AUDIO="$WORK/audio/$TAG.$ext" && break
  done
fi
TXT="${TXT:-$WORK/txt/$TAG.txt}"
[ -s "${AUDIO:-/nonexistent}" ] || { echo "[$TAG] ✗ لا يوجد صوت (ابحث في $WORK/audio أو مرر AUDIO=...)"; exit 2; }
[ -s "$TXT" ] || { echo "[$TAG] ✗ لا يوجد نص مرجعي: $TXT"; exit 2; }

if [ "${KEEP_WAV:-0}" = "1" ] && [ "${AUDIO##*.}" != "wav" ]; then
  FF="${FFMPEG:-ffmpeg}"
  W="$WORK/audio/$TAG.wav"
  [ -s "$W" ] || "$FF" -y -loglevel error -i "$AUDIO" -ar 16000 -ac 1 "$W"
  AUDIO="$W"
fi

PRE="$OUT/$TAG"
T0=$(date +%s)
echo "[$TAG] الهدف=$TARGET | المرحلة ١: مصفوفة الانبعاثات (جهاز=${EM_DEVICE:-$DEFAULT_DEVICE} · نافذة=${EM_WINDOW:-$DEFAULT_WINDOW}ث · دفعة=${EM_BATCH:-$DEFAULT_BATCH} · طبقات=${LAYERS:-$DEFAULT_LAYERS})"
EM_ARGS=(
  --audio "$AUDIO" --txt "$TXT" --out "$PRE"
  --engine "${EM_ENGINE:-torch}"
  --device "${EM_DEVICE:-$DEFAULT_DEVICE}"
  --dtype "${EM_DTYPE:-fp32}"
  --batch "${EM_BATCH:-$DEFAULT_BATCH}"
  --window "${EM_WINDOW:-$DEFAULT_WINDOW}"
  --onnx-workers "${ONNX_WORKERS:-2}"
  --onnx-threads "${ONNX_THREADS:-2}"
  --threads "${THREADS:-4}"
  --par-procs "${PAR_PROCS:-1}"
  --par-halves "${PAR_HALVES:-1}"
  --silence-compact "${SILENCE_COMPACT:-0}"
  --silence-rel "${SILENCE_REL:-5.0}"
  --layers "${LAYERS:-$DEFAULT_LAYERS}"
  --seg-sec "${SEG_SEC:-0}"
)
"$PY" -u "$SKILL_DIR/scripts/extract_emissions.py" "${EM_ARGS[@]}"
[ -s "$PRE.em.npy" ] || { echo "[$TAG] ✗ المرحلة ١ لم تنتج $PRE.em.npy"; exit 3; }

T1=$(date +%s)
echo "[$TAG] المرحلة ٢: محاذاة الشريحة المتحركة على المصفوفة (بلا نموذج)"
AL_ARGS=(
  --em "$PRE.em.npy" --tokens "$PRE.tokens.json"
  --out "$OUT/$TAG.align.json" --tag "$TAG"
  --slice "${SLICE:-120}" --pin "${PIN:-65}"
  --margin "${MARGIN:-30}" --star "${STAR:-segment}"
  --min-score "${MIN_SCORE:--3.0}"
  --star-pen "${STAR_PEN:--0.9}"
  --solid-handoff "${SOLID_HANDOFF:-1}"
  --island-guard "${ISLAND_GUARD:-0}"
  --compact-silence "$PRE.silence.json"
)
[ -n "${V1:-}" ] && AL_ARGS+=(--v1 "$V1")
"$PY" -u "$SKILL_DIR/scripts/ctc_pure_align.py" "${AL_ARGS[@]}"
[ -s "$OUT/$TAG.align.json" ] || { echo "[$TAG] ✗ المرحلة ٢ لم تنتج $OUT/$TAG.align.json"; exit 4; }

T2=$(date +%s)
PEAK="?"
if [ -f /proc/self/cgroup ]; then
  CG=$(awk -F: '/^0::/{print $3}' /proc/self/cgroup 2>/dev/null | head -1)
  PEAK=$(cat "/sys/fs/cgroup${CG}/memory.peak" 2>/dev/null | awk '{printf "%.0f",$1/1048576}' || echo "?")
fi
echo "[$TAG] الزمن الكلي (صوت خام → align.json على $TARGET): $((T2-T0))ث = انبعاثات $((T1-T0))ث + محاذاة $((T2-T1))ث | ذروة الـcgroup: ${PEAK:-?}MB"
echo "[$TAG] المخرجات: $OUT/$TAG.align.json ($(ls -la "$OUT/$TAG.align.json" 2>/dev/null | awk '{printf "%.0fKB",$5/1048576*1024}'))"

