# ٠٥ — الجهازان: الخادم (VPS) والماك — الوصول والحدود وما لا يُلمَس

## الخادم (VPS) — هنا تعيش كل البيانات والأدوات

- `/root/workspace/{hawshat, ytb, irth, des, ytb-build, mirath-tools}` + المشتقات (`chr3`, `books`, `cheikh`, `store`…).
- مواصفاته: **٤ أنوية · ~٧٫٨ غ رام · بلا swap** — أعِد القياس بـ`nproc; free -m` قبل أي توسّع، لا تثق بالرقم في هذا الملف.
- تسريعه: لا GPU ⇒ كل ASR ثقيل على الماك. الموديلات الكبيرة تُحمّل على الخادم بحذر وقد تُقتل (`exit 137`).
- `mirath-audio` = `/usr/local/bin/mirath-audio` → `youtube_audio.py` بإنتاجه في `/root/venvs/asr` (فيه yt-dlp يومي،
  faster-whisper، av، websocket-client). الكوكيز: `/root/.config/mirath-cookies/youtube.txt` (٠٦٠٠) — لا تطبع قيمتها،
  ولا تُثبّت المسار في سكربت (المُغلّف يجرّب مسارين).
- كل شيء يعمل هنا يُشرف عليه cron: المنسّق والبِركة (`supervise_sharawi.sh`)، حارس الفشل (`failed_watch.py` كل ١٥د)،
  تقرير التقدّم (١٨٠د)، المنظّف على الماك (٣٠د). سجلاتها في `ytb-build/logs/`.

## الماك (عياد Metal) — للمحاذاة فقط

- الوصول: `ssh mac` (مختصر في `/root/.ssh/config`؛ داخل Tailscale فقط: `100.72.220.19` · `macm1pro.local` · مستخدم `macm1pro`).
  المفتاح `/root/.ssh/id_ed25519` بصفة `SHA256:lIbh2GDy7EPGnm3Po+zxFqb5p8+R51UK61IBcaG4ysE` — الوصول بالمفتاح لا بكلمة سر.
- مواصفاته: macOS 26.6 · arm64 · **١٠ أنوية · ١٦ غ** · القرص الحر ≈ **١٣٫٨ غ** (يراقب).
- مثبّتاته: `/opt/homebrew/bin/python3.14` وفيه `mlx 0.31.2` + `mlx-metal` + `mlx-whisper 0.4.3` + `torch` + `faster-whisper`؛
  أدوات النظام المستعملة: `taskpolicy`, `caffeinate`, `memory_pressure`, `vm_stat`, `sysctl`, `df`.
- النماذج في `~/align_sharawi/models/`: `large-v3-8bit` (الكبير، افتراضي `align_force`) · `small` · `parts`.
- المخرج `~/align_sharawi/out/` يُحمل تقريباً فئة لكل درس وقد صار له ١١٤+ مدخلة — لا تحذفه، هو مصدر النشر.
- على الماك وكلاء بدء تشغيل لا تلمسها (`ai.devin.*`, `ai.openclaw.*`, `ai.orc.*`).

### التقييد الموصى به ولم يُطبّق بعد

سطر `authorized_keys` لحماية مفتاح الخادم عند التسريب:
`from="100.89.239.100",no-port-forwarding,no-agent-forwarding,no-X11-forwarding` —
وهو **يُراد تطبيقه من الماك نفسه** مع نسخة احتياطية، تشغيلياً بأمر المالك.

### ما لا يُلمَس أبداً

1. **لا تُعدّل إعدادات الماك عن بُعد** (قاعدة المالك): خطأ في إعدادات macOS لا يُصلَح من الخادم — أعرض التغيير واتركه للمالك.
2. لا تقتل مهمة محاذاة تعمل (إعادة البدء تهدر دقائق) ولا تحذف ملفاً صوتياً محاذاته لم تُكتب.
3. لا تُشغّل مهمتين ثقيلتين معاً: كل تشغيل عبر `safe_run.sh` (يحجز ويراقب).
4. لا تُنصّب شيئاً (node/docker/برامج) على الماك بلا سؤال: لا Xcode (لا بناء iOS) والقرص محدود.

## `safe_run.sh` (الماك) — الحارس الذي يجعل السلاسل الطويلة تعيش

`safe_run.sh [--wait s] -- CMD…` — يرفض البدء بلا هامش، يشغّل بـ`taskpolicy -b caffeinate -i` (أولوية خلفية
فلا يتجمد النظام)، ويراقب كل ١٥ث ويقتل المهمة إن هبط المورد (**exit 14**).

| المقياس | عند البدء | في المراقبة |
|---|---|---|
| swapout p/s | ≤ ١٥٠٠ | ≤ ٢٥٠٠ |
| swapfiles | ≤ ٦١٤٤MB | ≤ ٨١٩٢MB |
| disk_free | **≥ ٦٠٠٠MB** | ≥ ٤٠٠٠MB |
| compressor | ≤ ٧٠٠٠MB | ≤ ٩٥٠٠MB |
| free% (memory_pressure) | ≥ ٢٠٪ | ≥ ١٢٪ |
| load | ≤ ٢×العأنوية | ≤ ٢×العأنوية |

أكواد الخروج: 0 نجاح · 11 ضغط رام · 12 compressor · 13 load · 14 **قُتلت تحت الضغط** · 15 swapout · 16 free% · 18 swapfiles · 19 disk.
**الدرس العملي**: «free%» من `memory_pressure` يتذبذب ويتضلّل؛ المعايير الصحيحة = **القرص الحر + حجم ملفات swap + معدل swapout**.

## التنزيل إلى الماك (نقل الصوت/النصوص/الكود)

- الكود على الخادم هو الأصل. انسخه بـ`scp`/`ssh cat >` ثم **تحقّق بـ`wc -c` أو `md5`**. تحذير مرير:
  `ssh -n 'cat > file'` يُنتج ملفاً **فارغاً** (‏`-n` يوجّه stdin إلى /dev/null) — وقعت فعلاً في منظّف الماك.
- لا تنسخ الكاشات بين الجهازين: مفتاح الكاش يحوي **مسار الصوت المطلق** ⇒ انسخ الصوت بنفس المسار أو أعِد ASR على الماك.
- تنزيل الموديلات: استعمل حلقات `curl -C -` مع `--speed-limit/--speed-time` وإعادة؛ الربط متقلّب (من ٢٫٥MB/s إلى ٤KB/s)
  و`snapshot_download` وحده لا يكفي. التوازي لا يزيد الصبيب (٦ مسارات = مسار واحد).

## أوامر التعافي السريعة

```bash
ssh mac 'pgrep -fl align_force.py; df -m / | tail -1; tail -2 ~/align_sharawi/logs/cleanup.log'
ssh mac 'bash ~/align_sharawi/stopall.sh'      # إيقاف كل خطّ المحاكاة عند الطارئ (بأمر المالك)
ssh mac 'uptime; sysctl -n vm.swapusage; memory_pressure | tail -1'
```
