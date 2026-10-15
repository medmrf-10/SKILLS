# -*- coding: utf-8 -*-
"""build_ottoman_dict.py — بناء قاموس العثماني ← الإملائي (أزواج الكلمات) من نصّي تنزيل.

المصدر: api.alquran.cloud  →  quran-uthmani (الرسم العثماني) و quran-simple (الإملائي القياسي).
المخرَج: ottoman_dict.json  {كلمة عثمانية مطبّعة بالمجرى الظلّي : كلمة إملائية مطبّعة}
"""
import difflib
import json
import sys
from rapidfuzz import fuzz

sys.path.insert(0, '/root/workspace/ytb-build/v2')
import shadow_norm as SN  # noqa: E402

def SIM(a, b):
    return fuzz.ratio(a, b) / 100.0


U = json.load(open('/tmp/uthmani.json', encoding='utf-8'))['data']['surahs']
S = json.load(open('/tmp/simple_clean.json', encoding='utf-8'))['data']['surahs']  # الإملائي بدون تشكيل (الهدف)

by_key_u = {}
for su in U:
    for a in su['ayahs']:
        by_key_u[(a['surah']['number'] if isinstance(a.get('surah'), dict) else su['number'], a['numberInSurah'])] = a['text']
by_key_s = {}
for su in S:
    for a in su['ayahs']:
        by_key_s[(su['number'], a['numberInSurah'])] = a['text']

print('آيات عثماني', len(by_key_u), '| إملائي', len(by_key_s))

cnt = {}
pairs_raw = {}
n_ayah_diff = 0
for k in sorted(set(by_key_u) & set(by_key_s)):
    uw = by_key_u[k].split()
    sw = by_key_s[k].split()
    if uw == sw:
        continue
    nu = [SN.shadow(w, use_dict=False) for w in uw]
    ns = [SN.shadow(w, use_dict=False) for w in sw]
    if nu == ns:
        continue
    n_ayah_diff += 1
    if len(nu) != len(ns):
        continue          # عدد كلمات مختلف ⇒ الاقتران غير موثوق
    sm = difflib.SequenceMatcher(a=nu, b=ns, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag != 'replace':
            continue
        for a1, b1 in zip(range(i1, i2), range(j1, j2)):
            ku, ks = nu[a1], ns[b1]
            if ku and ks and ku != ks and len(ku) > 1 and len(ks) > 1 and SIM(ku, ks) >= 0.62:
                cnt[(ku, ks)] = cnt.get((ku, ks), 0) + 1
                pairs_raw.setdefault(ku, ks)

# احتفظ بالمعنى الأكثر تكراراً لكل مفتاح (مفتاح واحد ← قيمة واحدة)
best = {}
for (ku, ks), c in cnt.items():
    if ku not in best or c > best[ku][1]:
        best[ku] = (ks, c)
out = {k: v for k, (v, c) in best.items()}
json.dump(out, open('/root/workspace/ytb-build/v2/ottoman_dict.json', 'w', encoding='utf-8'),
          ensure_ascii=False, indent=0, sort_keys=True)

print('آيات اختلفت بعد التطبيع:', n_ayah_diff)
print('أزواج خام (متضمّنة التكرار):', len(cnt), '| مفاتيح نهائية:', len(out))
top = sorted(cnt.items(), key=lambda kv: -kv[1])[:15]
print('الأكثر تكراراً:', json.dumps({f'{k[0]}→{k[1]}': v for k, v in top}, ensure_ascii=False))
ex = ['الرحمان', 'هاذا', 'ذالك', 'الاه', 'السماوات', 'ابراهيم', 'ياايها', 'الذين', 'عم', 'يس']
for e in ex:
    print(f'  {e:>10} → {out.get(e, "—")}')
print('عيّنة:', json.dumps(dict(list(sorted(out.items()))[:6]), ensure_ascii=False))
