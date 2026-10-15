# جسر Git ← Gmail (git-mail-sync) + مزامنة المهارات إلى شجرة Hermes

يُرسل تلقائيًا رسالة **نص صريح داخل جسم الرسالة** (بلا أي مرفقات) عند كل تغيير في هذا المستودع،
و**ينسخ مهارات المستودع إلى شجرة مهارات Hermes المثبَّتة** لتبقى متطابقة تمامًا.

## المواصفة الملزمة
- **Subject:** `[GIT-SYNC] skills | <short-sha> | <commit-summary>`
  الوسم الثابت يبقى ASCII غير مُرمَّز (لتعمل فلاتر Gmail: `subject:[GIT-SYNC]`) والملخص العربي فقط يُرمَّز RFC2047.
- **Body بالترتيب:** (أ) شجرة ملفات المستودع (ب) `git log -n 3 --stat` (ج) `git show --stat --patch HEAD`
  (د) المحتوى الكامل لكل ملف تغيّر في الالتزام بترويسة `=== FILE: path ===` … `=== END FILE: path ===`.

## الإرسال
`gws gmail users messages send` (Gmail API، مصادَق بمفتاح keyring على هذا الخادم — **بلا كلمة مرور تطبيقات**).
الجسم يُرفع كـ multipart (`message/rfc822`) من ملف مؤقت داخل `.git/` لأن gws يرفض `--json` الطويل (حدّ 128KB لكل وسيط)
ويفرض أن يكون `--upload` داخل مجلد العمل الحالي.

## الخطافات: المصدر هو المستودع لا `.git/hooks`
الخطافات المعيارية تُحفظ في `tools/githooks/` (متتبَّعة في git)، والملفات في `.git/hooks/` نسخ مثبَّتة منها.
**لا تُحرِّر `.git/hooks/*` مباشرة أبدًا** — التحرير هناك يضيع، ويسبب تكرار الكتل عند الإضافة بـ`>>`.

```bash
bash tools/install-githooks.sh     # بعد الاستنساخ، وبعد أي تغيير في tools/githooks/
```

| الخطاف | المُشغِّل | ملاحظة |
|---|---|---|
| `post-commit` | كل التزام | مزامنة المهارات + إشعار التزام (كتم تكرار: لا يُرسل نفس الالتزام مرتين) + حارس انزياح الخطافات |
| `post-merge` | بعد دمج/سحب | يغطي الالتزامات القادمة من origin |
| `post-rewrite` | rebase/amend | يغطي إعادة الكتابة |
| `pre-push` | رفع إلى `main`/`master` | إشعار رفع (منفصل عن إشعار الالتزام) |

## مزامنة المهارات (repo → شجرة Hermes)
`tools/sync-skills.sh` ينسخ **كل مجلد في الجذر يحوي `SKILL.md`** إلى وجهته:
1) ما ينصّ عليه `tools/skills-sync.map` (سطر بالشكل `<name>=<target>`)، وإلا
2) `$HERMES_SKILLS_DIR/<name>` (الافتراضي `/root/.hermes/skills/<name>`).

- `rsync -a --delete --exclude __pycache__ --exclude .git <skill>/ <target>/` — الوجهة **داخل مجلد المهارة نفسه** (لا في أبيه).
- قفل `.git/skills-sync.lock` يمنع تزاحم خطافين، و**تحقق صريح** بعد النسخ: لا يُعلن النجاح إلا بوجود `SKILL.md` في الوجهة.
- تغيير الوجهة يحتاج سطرًا في `tools/skills-sync.map` — لا تعديل في الخطافات.

## تشغيل يدوي
```bash
python3 tools/git-mail-sync.py --test        # رسالة اختبار الآن (تتجاوز كتم التكرار)
python3 tools/git-mail-sync.py --dry-run     # طباعة بلا إرسال
python3 tools/git-mail-sync.py --trigger commit --sha HEAD
bash tools/sync-skills.sh                    # مزامنة المهارات الآن (يفشل بسبب صريح عند السقوط)
```

## السجلات والحالة
- `.git/git-mail-sync.log` — سطر لكل إرسال (وقت · مُشغِّر · sha · OK/FAIL · message-id).
- `.git/git-mail-sync.err` — أخطاء الخطافات وانزياح الخطافات (لا تُكتم أبدًا).
- `.git/git-mail-sync.state.json` — آخر sha أُرسل لكل مُشغِّر (كتم التكرار).
- `.git/skills-sync.log` — سطر لكل نسخة مهارة + سطر إحصاء ختامي (نسخت/فشلت).
- `.git/skills-sync.err` — أخطاء المزامنة فقط.

## سقف الحجم
محتوى الملف الواحد 400KB، وعند تجاوز جسم الرسالة 9MB يُضغط السقف إلى 40KB مع سطر اقتطاع واضح (سقف Gmail 25MB).
