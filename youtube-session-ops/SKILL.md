---
name: youtube-session-ops
description: "تشغيل وتشخيص جلسات Google/YouTube في مثيلات Chrome الدائمة على hermes-vps (CDP) التي يعتمد عليها تنزيل الصوت لجسر المحاذاة (vps_align_feeder.py ← mirath-audio ← yt-dlp). استعمل هذه المهارة فوراً عند: فشل تنزيل يوتيوب من الـ VPS (Sign in to confirm you're not a bot / Video unavailable / cookies are no longer valid)، جسر المحاذاة فارغ والماك خامل، خروج Chrome من حساب Google، الحاجة لتدقيق حالة الحسابات المسجَّلة في Chrome الـ VPS، أو قبل أي اقتراح لتنزيل يوتيوب من الماك. تتضمن سكربت تدقيق للقراءة فقط وأدلة جنائية موثّقة وقواعد صارمة."
version: 1.0.0
author: Mohamed Boumaraf
platforms: [linux, macos]
metadata:
  hermes:
    tags: [youtube, yt-dlp, cookies, chrome, cdp, vps, hermes-vps, session, novnc, align-bridge]
    related_skills: [sheikh-series-pipeline, agy-multi-account, agy-lean-cli]
---

# مهارة جلسات يوتيوب على الـ VPS (`youtube-session-ops`)

> **القاعدتان الصارمتان (قرار المالك 2026-10-21):**
> 1. **لا تنزيل ليوتيوب من الماك** ولا أي شيء يعرّض عنوان الماك الـ IP لحظر يوتيوب. (جُرّب مساعد تنزيل على الماك ونجح تقنياً، ثم عُطّل بأمر المالك.)
> 2. **لا تستعمل جلسة Chrome الخاصة بالحساب الرئيسي (`m10` / CDP:9224)** لتنزيل يوتيوب ولا لأي أتمتة: هو الجلسة السليمة الوحيدة وفيه الحسابات الرئيسية.

---

## 1. بنية المسار (من أين تأتي الكوكيز؟)

```
ytb-align-feeder.service (hermes-vps)         ← يحدد الدروس المنتظرة (٩٦٠ درساً بتاريخ 2026-10-21)
  └─ vps_align_feeder.py  → yt-dlp (+ كوكيز)  ← إن فشل: fallback إلى mirath-audio
        └─ /usr/local/bin/mirath-audio → /root/workspace/mirath-tools/youtube_audio.py
              └─ يُصدّر الكوكيز من Chrome الدائم عبر CDP:9222 إلى /root/.config/mirath-cookies/youtube.txt
                 (يعيد التصدير ذاتياً عند خطأ البوت، وينسخ كوكيز google.com إلى نطاق youtube.com)
Chrome الدائم = chrome-agent.service (Xvfb :99، --no-sandbox، يُعاد تلقائياً Restart=always)
noVNC للدخول اليدوي: x11vnc :5900 + websockify :6080 (محلية على الـ VPS)
```

مثيلات Chrome على الـ VPS (CDP على 127.0.0.1 فقط):

| المنفذ | الخدمة / الملف | الغرض | الحالة المرصودة 2026-10-21 |
|---|---|---|---|
| 9222 | `chrome-agent` · `/root/browser-profile` | **مصدر كوكيز التنزيل** (حساب `medmrf19`) | Google حيّ لكن **YouTube غير مسجَّل** (بلا `LOGIN_INFO`) و**جوجل تطلب «Verify it's you»** |
| 9223 | `chrome-agent-bmco` · `…-bmco` | حاوية agents | **خارج الحساب كلياً** (قاعدة كوكيز صغيرة بلا كوكيز Google) |
| 9224 | `chrome-agent-m10` · `…-m10` | الحسابات الرئيسية (medmrf.10/19 export) | **سليم** Google + YouTube منذ 16–17 أكتوبر (لا تلمسه) |
| 9225 | `chrome-agent-student` · `…-student` | حاوية agents | Google حيّ، YouTube غير مسجَّل |

---

## 2. الفحص السريع (كله للقراءة فقط)

```bash
# تدقيق كل مثيلات Chrome: الحكم + أعمار الكوكيز + تبويبات «تأكيد الهوية» (لا يطبع قيماً ولا يفتح صفحات)
ssh hermes-vps /root/venvs/asr/bin/python - < /Users/macm1pro/REPOS/SKILLS/youtube-session-ops/scripts/chrome_session_audit.py

# هل Chrome:9222 مسجَّل في يوتيوب؟ (بلا أي طلب ليوتيوب؛ رمز الخروج 0 نعم · 10 لا · 2 تعذّر CDP)
ssh hermes-vps '/root/venvs/asr/bin/python /root/workspace/ytb-build/yt_session_check.py; echo $?'

# حالة المغذّي: yt_session_ok · yt_blocked_until · need_mac_download · pending_with_txt
ssh hermes-vps cat /root/workspace/ytb-build/align_feeder_state.json
# سجل ساعي: نجاح/فشل التنزيل (انهيار مفاجئ = جلسة ماتت)
ssh hermes-vps "grep -c 'فشل تنزيل الصوت' /root/workspace/ytb-build/vps_align_feeder.log"
```

**الحكم في `chrome_session_audit.py`:** `LOGGED-IN` (يوجد `LOGIN_INFO` لـ youtube.com) · `GOOGLE-ONLY` (جلسة Google حيّة بلا جلسة YouTube) · `LOGGED-OUT`.
اختبارات الوحدة لمنطق الحكم موجودة في `sheikh-series-pipeline/tests/`.

---

## 3. الأعراض ← التشخيص

| العرَض | التشخيص |
|---|---|
| `Sign in to confirm you're not a bot` بلا كوكيز، و`Video unavailable` مع الكوكيز | الكوكيز ميتة + عنوان الـ VPS مشبوه عند يوتيوب (فيديو عام كأغنية مشهورة قد يعمل بينما دروس الشيخ لا). |
| تحذير yt-dlp: `cookies are no longer valid … rotated in the browser` | دُوّرت `__Secure-1PSIDTS` في Chrome فبطلت النسخة المصدَّرة، أو جلسة YouTube لم تكن مسجَّلة أصلاً. |
| `ready_in_bridge=0` والماك خامل 0% CPU | **جوع صامت**: المنتِج (VPS) فاشل والمستهلك (الماك) حيّ. افحص سجل المغذّي لا الماك. |
| سجل المغذّي يكرر الدروس التسعة نفسها آلاف المرات | head-of-line blocking (أُصلح بتراجع زمني لكل درس) . |
| `systemctl stop ytb-align-feeder` ثم يعود وحده | حارس cron `vps_pipeline_watchdog.py` (كل ٣ دقائق) يعيده بالكود المنشور؛ بعد النشر استعمل `systemctl restart` وتحقق من حقل جديد في `align_feeder_state.json`. |
| تبويب Gmail في Chrome يعرض «Verify it's you … sign in again» | جوجل فرضت **إعادة مصادقة** على الحساب (انظر §5). |

---

## 4. الإصلاح (الإجراء اليدوي الوحيد المطلوب)

لا يمكن لوكيل تسجيل الدخول (كلمة سر + غالباً تحقق بخطوتين). يفعلها المالك:

1. `ssh -L 6080:127.0.0.1:6080 hermes-vps` ثم افتح `http://localhost:6080` (شاشة Xvfb :99 فيها Chrome).
2. في Chrome الافتراضي (CDP:9222) سجّل الدخول إلى **youtube.com** بحساب مناسب (انظر القاعدة أدناه)، وتأكد أن صورة الحساب تظهر.
3. تحقق: `yt_session_check.py` يطبع `YT-LOGGED-IN`. المغذّي يستأنف تلقائياً خلال ٥ دقائق (`yt_session_ok: true`).

**ما نجح فعلاً (2026-10-21) وما أربك:**
- افتح النفق كـ **عملية خلفية يملكها الوكيل** (`ssh -N -L 127.0.0.1:6080:127.0.0.1:6080 hermes-vps` بـ`IsDaemon`)؛ طلب «شغّل هذا الأمر في طرفية» فشل مع المالك (`ERR_CONNECTION_REFUSED` لأن لا نفق كان يعمل). تحقق قبل أن تطلب منه شيئاً: `lsof -iTCP:6080 -sTCP:LISTEN` ثم `curl localhost:6080/vnc.html` (=200).
- **لا تقل «سجّل الدخول» فقط**: افتح أنت صفحة الدخول في Chrome:9222 عبر CDP (`PUT /json/new?<url>` ثم `/json/activate/<id>`، والرابط `https://accounts.google.com/ServiceLogin?service=youtube&continue=https%3A%2F%2Fwww.youtube.com%2F`) والتقط لقطة `Page.captureScreenshot` لتتأكد ما الذي سيراه. ظهرت «Verify it's you — حساب → Next»، فصارت الخطوات: Next ← كلمة السر ← تم.
- المالك اختار الاستمرار بحساب `medmrf19` (مدير العائلة) **بعد تحذيره** من أن تعطيله قد يؤثر على خطة الأعضاء.
- بعد النجاح: `yt_session_check.py` ⇒ `YT-LOGGED-IN`؛ تنزيل تجريبي لدرس واحد عبر `mirath-audio` (المحاولة الأولى بالكوكيز القديمة تفشل ثم تعيد الأداة تصدير الكوكيز ذاتياً وتنجح)؛ **أغلق التبويب الذي فتحته** (تبويب يوتيوب المفتوح يدوّر الكوكيز) و**أغلق النفق**؛ ثم استأنف المغذّي تلقائياً خلال ~٥ دقائق (٦ دروس في دقيقتين) والماك عاد يحاذي.

**أي حساب؟** الأفضل **حساب مخصّص للتنزيل فقط**، ليس الرئيسي. حساب `medmrf19` (الذي تطلب جوجل منه الآن التحقق وهو محظور في Antigravity) خيار سيئ لأنه تحت مراقبة جوجل.

**وصفة أمتن (لم تُنفَّذ، تحتاج تسجيل دخول واحداً):** تصدير الكوكيز من **نافذة خاصة (Incognito)** تُغلق بعد التصدير، فلا يدوّرها Chrome بعد ذلك (توصية yt-dlp الرسمية) وتبقى النسخة صالحة أسابيع. أي: `Target.createBrowserContext` ← تسجيل دخول ← زيارة `youtube.com/robots.txt` ← تصدير ← إغلاق السياق.

---

## 5. لماذا يخرج Chrome من الحساب؟ (أدلة 2026-10-21)

### مثبت بالقياس
- **9222:** جلسة Google أُنشئت من جديد في **2026-10-20 22:12** (أي أن السابقة ماتت قبلها)، وتدوَّر كوكيزها حتى الآن (`__Secure-1PSIDCC` 12:35، `__Secure-1PSIDTS` 10:00)، لكن **لا `LOGIN_INFO` لنطاق youtube.com**؛ وفتح يوتيوب فيه أظهر «Sign in». كوكيز youtube.com الوحيدة القديمة من 17 أكتوبر 20:25.
- **تبويب Gmail في 9222:** «Verify it's you — `medmrf.19`@… Google needs to verify it's you. Please sign in again» ⇒ **جوجل تفرض إعادة مصادقة** (إبطال جلسة بحسب المخاطر) على هذا الحساب.
- **9224** بقي مسجَّلاً ~٥ أيام (`LOGIN_INFO` من 16 أكتوبر 18:30، Google SID من 17 أكتوبر 10:27). فالجلسات قادرة على البقاء أياماً على هذا الخادم.
- **لا شيفرة تمسح الكوكيز:** بحث `clearBrowserCookies/deleteCookies/logout/signout` في `/root/workspace` لم يجد إلا ملفات واجهات غير ذات صلة؛ **ولا إعادة تشغيل لـ Chrome** منذ 18 أكتوبر 15:44 (الخدمة تعمل ~٣ أيام بلا انقطاع)؛ أخطاء GPU (`ContextResult::kFatalFailure`) ضجيج Xvfb لا علاقة له.
- **انهيار التنزيل بين ليلة وضحاها:** نجاح ثابت ~٤٠–١٣٠ درساً/ساعة لمدة يومين بصفر إخفاق، ثم **10:00 → 10:09** أول إخفاق ثم ٩٨٨ إخفاقاً في ساعة. وفي **10:00 بالضبط** دُوّرت `__Secure-1PSIDTS` في Chrome (9222).

### مرجَّح (لم يثبت)
- **التدوير:** نسخة الكوكيز المصدَّرة (مخزَّنة) بطلت حين دوّر Chrome `__Secure-1PSIDTS` عند 10:00 (التوقيت يتطابق مع أول إخفاق 10:09)، وإعادة التصدير بعدها لم تنفع لأن جلسة **YouTube** نفسها غير مسجَّلة. هذا وصف yt-dlp الحرفي («rotated in the browser as a security measure»).
- **الاستهلاك الآلي الثقيل** لحساب واحد (مئات التنزيلات/ساعة بكوكيز مُعاد تصديرها من جلسة حية) قد يستدعي إبطال جوجل للجلسة. مؤيِّد ضعيف: 9224 (غير مستعمل في التنزيل) بقي سليماً بينما 9222 (المستعمل) فقد جلسته، لكن العينة واحدة مقابل واحدة.
- **ملف خطر الحساب:** `medmrf19` معطّل من جوجل في Antigravity (403) وجوجل تطلب منه الآن التحقق؛ قد يكون ذلك جزءاً من نمط واحد (حساب تحت المراقبة).

### غير معروف
- **ما الذي أنهى جلسة 9222 السابقة قبل 20 أكتوبر 22:12** (خروج يدوي؟ إبطال من جوجل؟ تبديل حساب عبر تسجيل Antigravity OAuth في هذا المتصفح؟). في 9222 تبويب «Google Antigravity Authentication» مفتوح، فتسجيلات `agy` قد تجري في هذا المتصفح.
- **لماذا لم تنتقل جلسة Google إلى YouTube** في 9222/9225 رغم وجود SID في google.com (تفعيل CheckConnection/كوكيز الطرف الثالث؟).

---

## 6. دروس تشغيلية عامة (من هذه الحادثة)

- **الجوع الصامت أخطر من الانهيار:** مستهلك حيّ ومنتِج فاشل يبدوان «تعمل» (عملية حيّة، 0% CPU). افحص دائماً **الطرف الذي يُنتِج** وحقل `updated_at` ومقياس الطابور، لا وجود العملية فقط.
- **head-of-line blocking:** حلقة تأخذ «أول N عنصر» ثم تعيد فشلها بلا نهاية تُجوِّع البقية. الحل: تراجع زمني **لكل عنصر** مع تخطّيه، وقاطع دائرة للخدمة الخارجية.
- **لا تضرب خدمة خارجية بشيء تعرف أنه ميت:** افحص سلامة الجلسة محلياً (CDP + `LOGIN_INFO`) قبل أي طلب شبكي.
- **انشر ثم تحقق بالمحتوى لا بالأمر:** `systemctl start` لا يعيد تحميل الكود (حارس cron أعاد القديم). استعمل `restart` وتأكد من حقل جديد في الحالة أو سطر سجل جديد؛ ووازن `md5sum` بين النسخة المحلية والبعيدة؛ واحتفظ بنسخة `.bak` قبل النشر.
- **`agy -p` وأي CLI يقرأ stdin يتجمد مع stdin أنبوبي:** مرّر `stdin=DEVNULL` (انظر `agy-multi-account`).
- **المستودع عام:** لا تضع بريداً/توكناً لحساب غير معلن؛ سجّل `email_sha256` (انظر `agy-multi-account/profiles.json`). قبل أي دفع افحص `git diff origin/main..HEAD` بحثاً عن بريد/مفاتيح.
- **اقرأ الأرقام الخام لا النسب المقرّبة** (اكتشاف الحصة المشتركة بين حسابات العائلة جاء من كسور مطابقة حتى ١٥ خانة).
- **قيِّم قبل أن تعمل عند المساس بحساب:** أي إجراء قد يعرّض حساباً/IP لخطر (تنزيل من الماك، استعمال جلسة الحساب الرئيسي) يحتاج إذناً صريحاً.

---

## 7. ملفات ذات صلة

- `scripts/chrome_session_audit.py` (هذه المهارة): تدقيق Chrome للقراءة فقط.
- `sheikh-series-pipeline/scripts/yt_session_check.py` + `vps_align_feeder.py`: بوابة الجلسة والتراجع والقاطع.
- `sheikh-series-pipeline/scripts/mac_audio_assist.py` + `launchd/…assist.plist.disabled`: مساعد تنزيل الماك (**معطّل بقرار المالك**؛ يُفعَّل فقط بـ`ALIGN_MAC_ASSIST=1` وبإذن صريح).
- `sheikh-series-pipeline/references/06-pitfalls-catalogue.md` الفخ ٦٤.
- `agy-multi-account/`: حسابات agy والعائلة والحصة المشتركة.
