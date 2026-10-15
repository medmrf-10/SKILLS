# -*- coding: utf-8 -*-
"""cmp_v2_quality.py — قياس جودة محاذاة CTC (v2) مقابل خط الإنتاج (v1) بدقة الكلمة.

المجرَيان من نفس النص وبنفس الترتيب ⇒ المقارنة بالفهرس مباشرة (لا حاجة لمزاوجة ضبابية).
يقيس: التغطية، فرق البداية (وسيط/IQR/نِسَب داخل ±0.5ث و±1ث و±2ث)، وعلى مراسي v1 الحقيقية فقط،
وعدد الكلمات التي تخلّف فيها v1 عن CTC بأكثر من ثانيتين (أخطاء زمنية في v1).

الاستعمال: cmp_v2_quality.py <v1.json> <v2result.json>
"""
import json
import statistics as st
import sys

v1 = json.load(open(sys.argv[1], encoding='utf-8'))
v2 = json.load(open(sys.argv[2], encoding='utf-8'))
x = v1['x']
w = v2['x']
n = min(len(x), len(w))
tot = len(w)
print('كلمات: v1=%d | v2=%d | مفعّلة=%d' % (len(x), tot, n))
print('تغطية v1 المعلنة cov=%s | مراسي v1 الحقيقية=%d (%.1f%%)' % (
    v1.get('cov'), sum(1 for r in x if r[5] == 'a'), sum(1 for r in x if r[5] == 'a') / len(x) * 100))


def stats(d, label):
    if not d:
        print(label, 'لا بيانات')
        return
    d = sorted(d)
    print('%s: n=%d | وسيط %+.2fث | IQR [%+.2f, %+.2f] | ±0.5ث %.0f%% | ±1ث %.0f%% | ±2ث %.0f%% | أقصى %.1fث' % (
        label, len(d), st.median(d), d[len(d) // 4], d[3 * len(d) // 4],
        sum(1 for z in d if abs(z) <= 0.5) / len(d) * 100,
        sum(1 for z in d if abs(z) <= 1) / len(d) * 100,
        sum(1 for z in d if abs(z) <= 2) / len(d) * 100, max(abs(z) for z in d)))


d_all = [w[i][1] - x[i][1] for i in range(n)]
d_anc = [w[i][1] - x[i][1] for i in range(n) if x[i][5] == 'a']
stats(d_all, 'Δ على كل الكلمات')
stats(d_anc, 'Δ على مراسي v1 الحقيقية')

# انحراف مقارن بالنص: هل t2 المتوقع = الفرق بين زمن CTC وزمن v1 في *الإجماع*؟
big = sum(1 for z in d_all if abs(z) > 2)
print('كلمات يتجاوز فرقها ٢ث: %d (%.1f%%)' % (big, big / n * 100))
# فحص التسلسل: هل التوقيتات تصاعدية؟
bad = sum(1 for i in range(1, tot) if w[i][1] < w[i - 1][1] - 0.001)
print('انتهاكات الرتابة في CTC: %d' % bad)
covv2 = sum(1 for r in w if r[1] is not None) / tot * 100
print('تغطية CTC: %.1f%% (%d/%d)' % (covv2, sum(1 for r in w if r[1] is not None), tot))
print('آخر كلمة: v1 %.1fث | CTC %.1fث' % (x[min(len(x) - 1, n - 1)][2], w[-1][2]))
