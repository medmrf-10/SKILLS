#!/bin/bash
# run_pure_vps.sh <tag> — المسار النقي (v4) على الـVPS: صوت خام + نص مرجعي ⇒ align.json
#   المرحلة ١ (صوتية): مصفوفة انبعاثات واحدة (نوافذ ٢٠ث + سياق ٢ث · batch 1) ثم **تفريغ النموذج**.
#   المرحلة ٢ (محاذاة): شريحة متحركة على المصفوفة — بلا نموذج، بلا Whisper، بلا مراسي، بلا معايرة.
# لا يستعمل أي كاش كلمات سابق (لا ASR ولا محاذاة v1) — إلا للمقارنة إن مُرِّر V1 صراحةً.
# يُستدعى داخل: systemd-run --scope -p MemoryMax=${MEMORY_GUARD_MB:-2000M} --unit=pure<tag> --collect
# متغيرات: EM_ENGINE · EM_WINDOW · ONNX_WORKERS · ONNX_THREADS · SERIES_WORKSPACE · PURE_WORKDIR · SKILL_DIR · PURE_OUT · ALIGN_PY · THREADS · SLICE · PIN · MARGIN · STAR · V1 · FFMPEG
set -euo pipefail
TAG=${1:?الاستخدام: run_pure_vps.sh <tag>}
ROOT=${SERIES_WORKSPACE:-/root/workspace}
SKILL_DIR=${SKILL_DIR:-$(cd "$(dirname "$0")/.." && pwd)}
WORK=${PURE_WORKDIR:-$ROOT/ytb-build/pure}
PY=${ALIGN_PY:-/root/venvs/ctc/bin/python}
OUT=${PURE_OUT:-$WORK/out}
mkdir -p "$OUT" "$WORK/audio"

AUDIO=${AUDIO:-}
if [ -z "$AUDIO" ]; then
  for ext in wav mp3 m4a; do [ -s "$WORK/audio/$TAG.$ext" ] && AUDIO=$WORK/audio/$TAG.$ext && break; done
fi
TXT=${TXT:-$WORK/txt/$TAG.txt}
[ -s "${AUDIO:-/nonexistent}" ] || { echo "[$TAG] ✗ لا يوجد صوت (ابحث في $WORK/audio)"; exit 2; }
[ -s "$TXT" ] || { echo "[$TAG] ✗ لا يوجد نص مرجعي: $TXT"; exit 2; }

FF=${FFMPEG:-}
if [ -z "$FF" ]; then
  if command -v ffmpeg >/dev/null 2>&1; then FF=ffmpeg
  else FF=$(ls -d /root/.hermes/tools/ffmpeg-*/bin/ffmpeg 2>/dev/null | head -1); fi
fi
if [ "${AUDIO##*.}" != "wav" ]; then
  W="$WORK/audio/$TAG.wav"
  [ -s "$W" ] || "$FF" -y -loglevel error -i "$AUDIO" -ar 16000 -ac 1 "$W"
  AUDIO=$W
fi
PRE="$OUT/$TAG"
T0=$(date +%s)
echo "[$TAG] المرحلة ١: مصفوفة الانبعاثات (بلا Whisper · بلا كاش كلمات)"
# ⚠ سقف الذاكرة (مُقاس 2026-10-15): ONNX UINT8 بـ4 عمال ≈2286MB و**بعامِلين أيضًا يُقتل بـOOM** داخل 2000M؛
#   سببه أن ذاكرة جلسة ORT مجهولة (anonymous) فتُحتسب كاملة، بخلاف torch الذي يستدعي الأوزان بـmmap.
#   ⇒ الافتراضي هنا **torch** (نافذة ٢٠ث: ذروة cgroup 919MB · RTF 1.17–1.33). ONNX يبقى متاحًا بـ EM_ENGINE=onnx خارج السقف.
#   الافتراضي الآمن: نافذة ٢٠ث + عامِلان (جلسة ONNX لكل عامل) ≈1.3–1.5GB.
"$PY" -u "$SKILL_DIR/scripts/extract_emissions.py" --audio "$AUDIO" --txt "$TXT" --out "$PRE" \
    --engine "${EM_ENGINE:-torch}" --window "${EM_WINDOW:-20}" --onnx-workers "${ONNX_WORKERS:-2}" \
    --onnx-threads "${ONNX_THREADS:-2}" --threads "${THREADS:-4}" --par-halves "${PAR_HALVES:-1}" --par-procs "${PAR_PROCS:-1}" \
    --silence-compact "${SILENCE_COMPACT:-0}" --silence-rel "${SILENCE_REL:-5.0}" --layers "${LAYERS:-0}"
T1=$(date +%s)
echo "[$TAG] المرحلة ٢: محاذاة الشريحة المتحركة على المصفوفة (بلا نموذج)"
"$PY" -u "$SKILL_DIR/scripts/ctc_pure_align.py" --em "$PRE.em.npy" --tokens "$PRE.tokens.json" \
    --out "$OUT/$TAG.align.json" --tag "$TAG" --slice "${SLICE:-120}" --pin "${PIN:-65}" \
    --margin "${MARGIN:-30}" --star "${STAR:-segment}" ${V1:+--v1 "$V1"} \
    --star-pen "${STAR_PEN:--0.9}" --solid-handoff "${SOLID_HANDOFF:-1}" --island-guard "${ISLAND_GUARD:-0}"
T2=$(date +%s)
CG=$(awk -F: '/^0::/{print $3}' /proc/self/cgroup 2>/dev/null | head -1)
PEAK=$(cat "/sys/fs/cgroup${CG}/memory.peak" 2>/dev/null | awk '{printf "%.0f",$1/1048576}')
echo "[$TAG] الزمن الكلي (صوت خام → align.json): $((T2-T0))ث = انبعاثات $((T1-T0))ث + محاذاة $((T2-T1))ث | ذروة الـcgroup: ${PEAK:-?}MB"
echo "[$TAG] المخرجات: $OUT/$TAG.align.json ($(ls -la "$OUT/$TAG.align.json" 2>/dev/null | awk '{printf "%.0fKB",$5/1024}'))"
