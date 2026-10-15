#!/usr/bin/env bash
# نافذة واحدة: توليد انبعاثات 120ث + قياس RTF والذروة داخل السقف
WD=$1; W=$2; SK=$3
/root/venvs/ctc/bin/python -u "$SK/scripts/extract_emissions.py" --audio "$W/a120.wav" --txt "$W/w120.txt" \
  --out "$W/e$WD" --engine torch --window "$WD" --threads 4 2>&1 | tail -1 | sed "s/^/[نافذة ${WD}ث] /"
