#!/usr/bin/env bash
# نافذة واحدة: توليد انبعاثات 120ث + قياس RTF والذروة داخل السقف
# set -o pipefail إلزامي: بدونه يُخفي `| tail -1` فشل بايثون ويُظهر الوحدة "ناجحة" زورًا
set -o pipefail
WD=$1; W=$2; SK=$3
LOG="$W/w${WD}.log"
/root/venvs/ctc/bin/python -u "$SK/scripts/extract_emissions.py" --audio "$W/a120.wav" --txt "$W/w120.txt" \
  --out "$W/e$WD" --engine torch --window "$WD" --threads 4 >"$LOG" 2>&1
RC=$?
tail -2 "$LOG" | sed "s/^/[نافذة ${WD}ث] /"
echo "[نافذة ${WD}ث] خروج=$RC" >>"$LOG"
exit $RC
