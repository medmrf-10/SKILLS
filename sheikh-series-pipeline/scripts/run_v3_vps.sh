#!/bin/bash
# run_v3_vps.sh <tag> — درس واحد على الـVPS وحده، داخل سقف ذاكرة واحد.
#   1) مصدر كلمات المراسي، بالترتيب:
#        (أ) محاذاة v1 جاهزة (align.force.json) ⇒ تُشتقّ في ثوانٍ بلا أي ASR  ✅ المسار المفضّل
#        (ب) كاش ASR محلي سابق في $ALIGN_CACHE_DIR
#        (ج) توليد محلي بـfaster-whisper (نمط سريع: base · int8 · beam=1 · vad) مع قيد زمني
#   2) محاذاة v3: مراسي v2 من النص المرجعي ← معايرة تتابعية ← تقطيع محكوم ← تحقق ← إعادة محاذاة.
# يُستدعى عادة داخل: systemd-run --scope -p MemoryMax=${MEMORY_GUARD_MB:-2000M} --unit=v3<tag> --collect
# متغيرات البيئة: SERIES_WORKSPACE · V3_WORKDIR · SKILL_DIR · ALIGN_CACHE_DIR · SERIES_LESSONS_DIR
#                 SERIES_SLUG · AUDIO · TXT · V1 · ASR_MODEL · ASR_BEAM · ASR_VAD · ASR_MAX_SEC
set -euo pipefail
TAG=${1:?الاستخدام: run_v3_vps.sh <tag>}
ROOT=${SERIES_WORKSPACE:-/root/workspace}
WORK=${V3_WORKDIR:-$ROOT/ytb-build/v2}
SKILL_DIR=${SKILL_DIR:-$(cd "$(dirname "$0")/.." && pwd)}
CACHE_DIR=${ALIGN_CACHE_DIR:-$HOME/.cache/hawshat/wwords}
SERIES_SLUG=${SERIES_SLUG:-sharawi-539}
LESSONS_DIR=${SERIES_LESSONS_DIR:-$ROOT/hawshat/playlists/lessons/$SERIES_SLUG}
PY=${ALIGN_PY:-/root/venvs/ctc/bin/python}     # بيئة torch/rapidfuzz
ASR_PY=${ASR_PY:-/root/venvs/asr/bin/python}   # بيئة faster-whisper
LESSON_NO=$(printf '%02d' $((10#$TAG)))        # 006 ⇒ 06 (ترقيم المستودع)
AUDIO=${AUDIO:-}
if [ -z "$AUDIO" ]; then
  for ext in wav mp3 m4a; do
    [ -s "$WORK/audio/kahf539_$TAG.$ext" ] && AUDIO=$WORK/audio/kahf539_$TAG.$ext && break
  done
fi
TXT=${TXT:-$WORK/txt/kahf539_$TAG.txt}
OUTDIR=${V3_OUTDIR:-$WORK/v3out}
LOG=${V3_LOG:-$WORK/logs/v3s_$TAG.log}

[ -s "$AUDIO" ] || { echo "[$TAG] ✗ لا يوجد صوت: $AUDIO"; exit 2; }
[ -s "$TXT" ]   || { echo "[$TAG] ✗ لا يوجد نص مرجعي: $TXT"; exit 2; }
mkdir -p "$CACHE_DIR" "$OUTDIR" "$WORK/logs"

# --- 1) ملف محاذاة v1 (إن وُجد) ---------------------------------------------
V1=${V1:-}
if [ -z "$V1" ]; then
  for c in "$WORK/../../ytb/sharawi/539/${TAG}_"*.force.align.json \
           "$ROOT/ytb/sharawi/539/${TAG}_"*.force.align.json \
           "$ROOT/ytb/sharawi/539/${TAG}_"*.align.json \
           "$LESSONS_DIR/${LESSON_NO}.align.force.json" "$LESSONS_DIR/${LESSON_NO}.align.json"; do
    [ -s "$c" ] && V1=$c && break
  done
fi

ARGS=(--audio "$AUDIO" --txt "$TXT" --outdir "$OUTDIR" --tag "$TAG"
      --calib-seq --target "${V3_TARGET:-70}" --resplit "${V3_RESPLIT:-20}" --batch "${V3_BATCH:-1}"
      --retry-max "${V3_RETRY_MAX:-6}")

# --- 2) مصدر كلمات المراسي ---------------------------------------------------
if [ -n "$V1" ]; then
  CACHE=$("$ASR_PY" "$SKILL_DIR/scripts/v1_to_cache.py" --v1 "$V1" --print-key)
  CACHE="$CACHE_DIR/$CACHE"
  if [ ! -s "$CACHE" ]; then
    echo "[$TAG] مسار سريع: اشتقاق المراسي من محاذاة v1 ⇒ $(basename "$V1") (بلا أي ASR)"
    "$ASR_PY" "$SKILL_DIR/scripts/v1_to_cache.py" --v1 "$V1" --cache "$CACHE"
  else
    echo "[$TAG] كاش v1 مشتقّ سابقًا: $CACHE"
  fi
  ARGS+=(--cache "$CACHE" --v1 "$V1")
else
  ASR_MODEL=${ASR_MODEL:-Systran/faster-whisper-base}     # النمط السريع الافتراضي
  CACHE=$("$ASR_PY" "$SKILL_DIR/scripts/gen_asr_cache.py" --audio "$AUDIO" --prompt-from-txt "$TXT" --print-key)
  CACHE="$CACHE_DIR/$CACHE"
  if [ ! -s "$CACHE" ]; then
    echo "[$TAG] لا محاذاة v1 ⇒ توليد كاش ASR محلي (${ASR_MODEL} · int8 · beam ${ASR_BEAM:-1}${ASR_VAD:+ · vad})"
    MAXSEC=${ASR_MAX_SEC:-900}
    S=$(date +%s)
    timeout "$MAXSEC" "$ASR_PY" "$SKILL_DIR/scripts/gen_asr_cache.py" --audio "$AUDIO" --cache "$CACHE" \
       --prompt-from-txt "$TXT" --model "$ASR_MODEL" --beam "${ASR_BEAM:-1}" --threads "${ASR_THREADS:-0}" \
       ${ASR_VAD:+--vad} 2>&1 | tee -a "$LOG"
    E=$(date +%s); D=$((E-S))
    echo "[$TAG] زمن توليد الكاش: ${D}ث (الحد المسموح ${MAXSEC}ث)"
    [ -s "$CACHE" ] || { echo "[$TAG] ✗ فشل توليد الكاش خلال ${MAXSEC}ث — راجع تعليق المهارة عن نمط سريع بديل"; exit 3; }
  else
    echo "[$TAG] كاش ASR موجود: $CACHE"
  fi
  ARGS+=(--cache "$CACHE")
fi

# --- 3) محاذاة v3 ------------------------------------------------------------
echo "[$TAG] تشغيل v3 (سقف الذاكرة ${MEMORY_GUARD_MB:-2000}M) → $OUTDIR/v3_$TAG.json"
"$PY" -u "$SKILL_DIR/scripts/v3_align.py" "${ARGS[@]}" 2>&1 | tee -a "$LOG"
echo "[$TAG] ✓ انتهى: $(ls -la "$OUTDIR/v3_$TAG.json" 2>/dev/null | awk '{print int($5/1024)"KB"}')"
