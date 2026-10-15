#!/bin/bash
# run_v3_queue.sh <tag...> — طابور تشغيل دروس متتابعة على الـVPS، بعاملين متوازيين كحد أقصى،
# وكل درس داخل وحدة cgroup مستقلة: MemoryMax=${MEMORY_GUARD_MB:-2000M}.
#   الاستخدام: bash run_v3_queue.sh 006 007 008 ...    (أو: PARALLEL=1 bash run_v3_queue.sh 006 ...)
set -uo pipefail
SKILL_DIR=${SKILL_DIR:-$(cd "$(dirname "$0")/.." && pwd)}
ROOT=${SERIES_WORKSPACE:-/root/workspace}
WORK=${V3_WORKDIR:-$ROOT/ytb-build/v2}
MEM=${MEMORY_GUARD_MB:-2000}
PARALLEL=${PARALLEL:-2}          # سقف هذا الخادم: ٤ أنوية ≈ ٢ مهام متوازية (كل مهمة ~1.3GB)
STAMP=$(date +%F-%H%M)
QLOG=$WORK/logs/queue-$STAMP.log
mkdir -p "$WORK/logs"
echo "=== طابور v3: $* | متوازي=$PARALLEL | سقف=${MEM}M | $STAMP" | tee -a "$QLOG"

run_one() {
  local tag=$1
  echo "[$(date +%H:%M:%S)] ▶ $tag" | tee -a "$QLOG"
  systemd-run --scope -p MemoryMax=${MEM}M --unit=v3$tag --collect \
    env SKILL_DIR="$SKILL_DIR" bash "$SKILL_DIR/scripts/run_v3_vps.sh" "$tag" >> "$WORK/logs/v3s_$tag.log" 2>&1
  echo "[$(date +%H:%M:%S)] ■ $tag (exit $?)" | tee -a "$QLOG"
}
export -f run_one 2>/dev/null || true

if [ "$PARALLEL" -le 1 ]; then
  for tag in "$@"; do run_one "$tag"; done
else
  for tag in "$@"; do
    run_one "$tag" &
    while [ "$(jobs -rp | wc -l)" -ge "$PARALLEL" ]; do sleep 20; done
  done
  wait
fi
echo "=== انتهى الطابور: $(date +%H:%M:%S)" | tee -a "$QLOG"
for tag in "$@"; do
  f="$WORK/v3out/v3_$tag.json"
  printf "%s: %s\n" "$tag" "$([ -s "$f" ] && echo "✓ $(stat -c%s $f) bytes" || echo '✗ لم يكتمل')" | tee -a "$QLOG"
done
