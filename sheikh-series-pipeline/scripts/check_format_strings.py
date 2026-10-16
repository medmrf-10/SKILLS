#!/usr/bin/env python3
"""check_format_strings.py — حارس آلي: يكشف نصوص تنسيق `%` بعدد محدِّدات ≠ عدد وسائط.

لماذا كُتب (2026-10-15): نص تنسيق في `ctc_pure_align.py` (11 محدِّدًا مقابل 13 وسيطًا) رفع
`TypeError: not all arguments converted` **بعد** كتابة كل مخرجات درس كامل ⇒ صارت الوحدة
`exit-code` بعد ٣٦ دقيقة عمل، ورفضها مدقّق قسم ٨.٧. خطأ طباعة واحد أباد قياسًا سليمًا.

الاستعمال:  python3 check_format_strings.py <dir-or-file> [...]     (rc=1 عند وجود خلل)
يفحص نصوص `'...' % (...)` الثابتة فقط عبر AST — لا يلمس `{}`/f-strings ولا `%` داخل regex.
"""
import ast
import glob
import os
import re
import sys

SPEC = re.compile(r'%(?:\([^)]*\))?[-+ #0]*\d*(?:\.\d+)?[sdfxXrge]')


def check(path):
    bad = []
    src = open(path, encoding='utf-8').read()
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        return [f'{path}:{e.lineno} خطأ نحوي: {e.msg}']
    for node in ast.walk(tree):
        if not (isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod)):
            continue
        left, right = node.left, node.right
        if not (isinstance(left, ast.Constant) and isinstance(left.value, str)):
            continue
        nph = len(SPEC.findall(left.value.replace('%%', '')))
        nargs = len(right.elts) if isinstance(right, ast.Tuple) else 1
        if nph != nargs:
            bad.append(f'{path}:{node.lineno} محددات={nph} وسائط={nargs} ⇒ TypeError عند التشغيل')
    return bad


def main():
    targets = sys.argv[1:] or ['.']
    files = []
    for t in targets:
        if os.path.isdir(t):
            files += sorted(glob.glob(os.path.join(t, '*.py')))
        else:
            files.append(t)
    problems = [p for f in files for p in check(f)]
    for p in problems:
        print('✗ ' + p)
    print(f'فُحص {len(files)} ملفًا · خلل {len(problems)}')
    return 1 if problems else 0


if __name__ == '__main__':
    sys.exit(main())
