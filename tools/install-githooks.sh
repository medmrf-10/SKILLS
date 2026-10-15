#!/bin/sh
# تثبيت الخطافات المعيارية من tools/githooks/ إلى .git/hooks/
# المصدر الوحيد للحقيقة هو المستودع (الخطافات في .git غير مُتتبَّعة ولا تُنسخ مع الاستنساخ).
# يُشغَّل مرة بعد الاستنساخ، وكلما تغيّر خطاف في المستودع:  bash tools/install-githooks.sh
set -eu
R=$(git rev-parse --show-toplevel)
mkdir -p "$R/.git/hooks"
for h in post-commit post-merge post-rewrite pre-push; do
  src="$R/tools/githooks/$h"
  [ -f "$src" ] || { echo "مفقود: tools/githooks/$h" >&2; exit 1; }
  sh -n "$src" || { echo "خطأ صياغة في tools/githooks/$h" >&2; exit 1; }
  install -m 755 "$src" "$R/.git/hooks/$h"
  echo "ثُبِّت: $h"
done
echo "تم. الخطافات مثبَّتة من المستودع."
