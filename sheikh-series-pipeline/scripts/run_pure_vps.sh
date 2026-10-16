#!/bin/bash
# run_pure_vps.sh <tag> — المسار النقي (v4) (متوافق مع الاستدعاءات القديمة، ويدعم EXEC_TARGET=vps|mac|auto)
#   المرحلة ١ (صوتية): مصفوفة انبعاثات واحدة ثم **تفريغ النموذج**.
#   المرحلة ٢ (محاذاة): شريحة متحركة على المصفوفة — بلا نموذج، بلا Whisper، بلا مراسي، بلا معايرة.
# يُستدعى على الـVPS داخل: systemd-run --scope -p MemoryMax=${MEMORY_GUARD_MB:-2000M} --unit=pure<tag> --collect
set -euo pipefail
SKILL_DIR=${SKILL_DIR:-$(cd "$(dirname "$0")/.." && pwd)}
exec "$SKILL_DIR/scripts/run_pure.sh" --target "${EXEC_TARGET:-auto}" "$@"
