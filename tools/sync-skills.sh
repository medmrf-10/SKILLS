#!/bin/sh
# نسخ مهارات هذا المستودع إلى شجرة مهارات Hermes المثبَّتة (تبقى متطابقة تمامًا).
# المصدر الوحيد للحقيقة هو المستودع؛ الشجرة المثبَّتة نسخة مطابقة له.
# يُستدعى من خطافات git تلقائيًا، ويمكن تشغيله يدويًا:  bash tools/sync-skills.sh
#
# الوجهة لكل مهارة:
#   1) ما ينصّ عليه tools/skills-sync.map (سطر بالشكل: <name>=<target>)، وإلا
#   2) $HERMES_SKILLS_DIR/<name>   (الافتراضي: /root/.hermes/skills/<name>)
set -u

R=$(git rev-parse --show-toplevel 2>/dev/null) || R=$(cd "$(dirname "$0")/.." && pwd)
DEST_ROOT=${HERMES_SKILLS_DIR:-/root/.hermes/skills}
LOG="$R/.git/skills-sync.log"
ERR="$R/.git/skills-sync.err"
LOCK="$R/.git/skills-sync.lock"
MAP="$R/tools/skills-sync.map"

# قفل: خطافان في وقت واحد يتزاحمان على rsync --delete
if ! mkdir "$LOCK" 2>/dev/null; then
  exit 0
fi
trap 'rmdir "$LOCK" 2>/dev/null' EXIT INT TERM

stamp() { date '+%Y-%m-%d %H:%M:%S'; }

target_for() { # $1 = skill name
  if [ -f "$MAP" ]; then
    t=$(awk -F= -v n="$1" '$1==n { sub(/^[^=]*=/, ""); print; exit }' "$MAP")
    [ -n "$t" ] && { echo "$t"; return; }
  fi
  echo "$DEST_ROOT/$1"
}

synced=0
failed=0
for d in "$R"/*/; do
  name=$(basename "$d")
  [ -f "$d/SKILL.md" ] || continue          # مجلدات ليست مهارة تُتجاهل
  target=$(target_for "$name")
  case "$target" in "~"*) target="$HOME${target#\~}" ;; esac

  if ! mkdir -p "$target" 2>>"$ERR"; then
    echo "$(stamp) فشل تهيئة $name ← $target" >>"$ERR"; failed=$((failed + 1)); continue
  fi

  if ! rsync -a --delete --exclude '__pycache__' --exclude '.git' "$d/" "$target/" 2>>"$ERR"; then
    echo "$(stamp) فشل نسخ $name ← $target" >>"$ERR"; failed=$((failed + 1)); continue
  fi

  # تحقق صريح: لا يُعلن النجاح إلا بوجود SKILL.md في الوجهة
  if [ -f "$target/SKILL.md" ]; then
    files=$(find "$target" -type f ! -path '*__pycache__*' | wc -l | tr -d ' ')
    echo "$(stamp) نسخ $name ← $target (ملفات=$files)" >>"$LOG"
    synced=$((synced + 1))
  else
    echo "$(stamp) سقوط SKILL.md بعد النسخ: $name ← $target" >>"$ERR"; failed=$((failed + 1))
  fi
done

echo "$(stamp) انتهى: نسخت=$synced فشلت=$failed" >>"$LOG"
[ "$failed" -eq 0 ] || exit 1
exit 0
