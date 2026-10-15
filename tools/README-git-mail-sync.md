# جسر Git ← Gmail (git-mail-sync)

يُرسل تلقائيًا رسالة **نص صريح داخل جسم الرسالة** (بلا أي مرفقات) عند كل تغيير في هذا المستودع.

## المواصفة الملزمة
- **Subject:** `[GIT-SYNC] skills | <short-sha> | <commit-summary>`
  الوسم الثابت يبقى ASCII غير مُرمَّز (لتعمل فلاتر Gmail: `subject:[GIT-SYNC]`) والملخص العربي فقط يُرمَّز RFC2047.
- **Body بالترتيب:** (أ) شجرة ملفات المستودع (ب) `git log -n 3 --stat` (ج) `git show --stat --patch HEAD`
  (د) المحتوى الكامل لكل ملف تغيّر في الالتزام بترويسة `=== FILE: path ===` … `=== END FILE: path ===`.

## الإرسال
`gws gmail users messages send` (Gmail API، مصادَق بمفتاح keyring على هذا الخادم — **بلا كلمة مرور تطبيقات**).
الجسم يُرفع كـ multipart (`message/rfc822`) من ملف مؤقت داخل `.git/` لأن gws يرفض `--json` الطويل (حدّ 128KB لكل وسيط)
ويفرض أن يكون `--upload` داخل مجلد العمل الحالي.

## الخطافات المثبَّتة (`.git/hooks/`)
| الخطاف | المُشغِّل | ملاحظة |
|---|---|---|
| `post-commit` | كل التزام | كتم تكرار: لا يُرسل نفس الالتزام مرتين |
| `post-merge` | بعد دمج/سحب | يغطي الالتزامات القادمة من origin |
| `post-rewrite` | rebase/amend | يغطي إعادة الكتابة |
| `pre-push` | رفع إلى `main`/`master` | إشعار رفع (منفصل عن إشعار الالتزام) |

## تشغيل يدوي
```bash
python3 tools/git-mail-sync.py --test        # رسالة اختبار الآن (تتجاوز كتم التكرار)
python3 tools/git-mail-sync.py --dry-run     # طباعة بلا إرسال
python3 tools/git-mail-sync.py --trigger commit --sha HEAD
```
## السجلات والحالة
- `.git/git-mail-sync.log` — سطر لكل إرسال (وقت · مُشغِّل · sha · OK/FAIL · message-id).
- `.git/git-mail-sync.err` — أخطاء الخطافات (لا تُكتم أبدًا).
- `.git/git-mail-sync.state.json` — آخر sha أُرسل لكل مُشغِّل (كتم التكرار).

## سقف الحجم
محتوى الملف الواحد 400KB، وعند تجاوز جسم الرسالة 9MB يُضغط السقف إلى 40KB مع سطر اقتطاع واضح (سقف Gmail 25MB).
