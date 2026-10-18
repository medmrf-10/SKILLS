#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_pdf_adapter_gates.py — بوابة الفحص الحتمية الشاملة للإصدار v2.1 من مهارة `turath-pdf-to-text`.

تختبر أربع بوابات متتابعة:
  - Gate 1: تشغيل بوابات `test_pdf_gates.py` الأصلية (12 اختباراً هندسياً وبصرياً) والتأكد من عدم كسر أي قاعدة.
  - Gate 2: اختبار `pdf_to_preflight_adapter.py` على 5 صفحات واقعية متعددة التخطيطات (`pages/p0001.json` .. `p0005.json`
            تضم متناً وعناوين أبواب وآيات قرآنية وحواشي سفلية مرقمة 1، 2، 3 وحاشية جدول أزهرية `framed_hashiya`
            ذات متن عمودي مدار 90°) والتحقق التشفيري من حفظ 100% من الحروف والحواشي (`100% Zero-Loss Check`).
  - Gate 3: تمرير مخرجات المحول فعلياً إلى `/Users/macm1pro/REPOS/SKILLS/turath-deep-indexing/scripts/manifest_v4.py`
            و`fn_linker_v4.py` والتحقق من توليد الـ Manifest وربط جميع الحواشي الـ 13 بدون أي أخطاء.
  - Gate 4: اختبار الحالات الحدية الواقعية المستخرجة من الكتب التراثية المصورة:
            * صيغ الحواشي غير القياسية (`[١]`, `(*)`, `( * )`, `[*]`, `* -`, الأرقام الفوقية `¹²`, الأرقام الملتصقة بالكلمات `هما1`).
            * الحواشي الأفقية المتعددة في سطر واحد (`(١) ...   (٢) ...   (٣) ...   (٤) ...`) مع عدم شطر الأرقام المرجعية داخل السياق.
            * حواشي الاستمرار العابرة للصفحات (`= ...` و`(=) ...`) وتطابق عداد `fn_continuation_merged_count`.
            * الحواشي المشتركة لأكثر من موضع في الصفحة الواحدة، وتعدد الحواشي بنفس الرقم في الصفحة، وتثبيت الإحالة الساقطة مطبعياً دون انزياح عبر الصفحات.
            * كبح الرؤوس الجارية المتكررة (Running Headers) من تقطيع الأجزاء، ودعم العناوين المركبة متعددة الأسطر والعناوين المدمجة (Run-in Headings).

الخروج القياسي عند النجاح: `PASS (0 errors)`
"""
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

import test_pdf_gates  # noqa: E402
from pdf_to_preflight_adapter import (  # noqa: E402
    DEFAULT_DEEP_INDEXING_SCRIPTS,
    convert_pdf_output_to_preflight,
)


def build_realistic_5_pages_fixture(pages_dir: str) -> list[dict]:
    """
    يبني 5 صفحات واقعية (p0001.json .. p0005.json) تغطي:
      - صفحات اعتيادية (standard_single_col) مع عناوين كتب وأبواب وفصول
      - آيات قرآنية بأرقامها ﴿... (٤٣)﴾ للتأكد من عدم التباسها بأرقام الحواشي
      - حواشٍ سفلية مرقمة (١)، (٢)، (٣)
      - طرر مخطوطات جانبية [ق/ ١٢ أ]
      - صفحة جدول أزهري (framed_hashiya) مع نص داخل الجدول ومتن عمودي مدار 90° في الهامش الخارجي
      - أرقام وحروف فارسية (۱۲۵، ی، ک) لاختبار التطبيع الحتمي قبل التصدير
    """
    os.makedirs(pages_dir, exist_ok=True)
    pages = [
        {
            "pdf_page": 1,
            "tag": "p0001",
            "layout": "standard_single_col",
            "extracted": {
                "printed_page": "١٥",
                "running_header": "أدب المفتي والمستفتي",
                "matn": (
                    "كتاب أدب المفتي والمستفتي\n"
                    "باب شروط المفتي وأحكامه\n"
                    "الحمد لله الذي شرف أهل العلم بحمل شريعته (١)، وجعلهم قدوة الأمة في بيان أحكامه "
                    "لقوله تعالى: ﴿فَاسْأَلُوا أَهْلَ الذِّكْرِ إِنْ كُنْتُمْ لَا تَعْلَمُونَ (٤٣)﴾ (٢)، "
                    "فوجب على المتصدي للفتوى أن يكون عالماً بمدارك الأحكام الشرعية وأقوال الأئمة (٣)."
                ),
                "margin_notes": "[ق/ ١٢ أ]",
                "footnotes": (
                    "(١) في النسخة الأزهرية: بحفظ شريعته المطهرة.\n"
                    "(٢) سورة النحل: الآية ٤٣، واستدل بها الأصوليون على وجوب سؤال العلماء.\n"
                    "(٣) راجع المجموع شرح المهذب للإمام النووي ص ٢٤."
                ),
                "uncertain_words": [],
            },
            "gate_report": {"total_words": 62, "warnings": []},
        },
        {
            "pdf_page": 2,
            "tag": "p0002",
            "layout": "standard_single_col",
            "extracted": {
                "printed_page": "١٦",
                "running_header": "أدب المفتي والمستفتي",
                "matn": (
                    "ولا يجوز له أن يفتي بالتشهي أو الهوى، بل يتحرى الدليل الراجح عنده (١).\n"
                    "فصل في المفتي المستقل وغير المستقل\n"
                    "المفتي ينقسم إلى قسمين: الأول المفتي المستقل الذي يستقل بإدراك الأحكام من الأدلة الشرعية (٢)، "
                    "والثاني المفتي المنتسب الذي يخرج الوجوه على أصول إمامه ويناظر في الأدلة (٣)."
                ),
                "margin_notes": "",
                "footnotes": (
                    "١ - نقل الإجماع على ذلك ابن عبد البر في جامع بيان العلم وفضله.\n"
                    "٢ - شرطه أن يكون قيماً بمعرفة الكتاب والسنة والإجماع والقياس.\n"
                    "٣ - وهو الذي يحفظ مذهب إمامه ويتمكن من تخريج المسائل المسكوت عنها."
                ),
                "uncertain_words": [],
            },
            "gate_report": {"total_words": 78, "warnings": []},
        },
        {
            "pdf_page": 3,
            "tag": "p0003",
            "layout": "framed_hashiya",
            "extracted": {
                "printed_page": "١٧",
                "running_header": "حاشية الباجوري على ابن قاسم",
                "matn": (
                    "حاشية الجدول في شروط التكليف والاجتهاد\n"
                    "قوله: (وشرائط وجوب الصلاة ثلاثة أشياء) أي الشرائط التي يتوقف عليها أصل الوجوب (١)، "
                    "فلا يخاطب الصبي ولا المجنون خطاب تكليف إجماعاً، وإنما يؤمر الصبي المميز بها لسبع سنين "
                    "تمريناً له على العبادة ليعتادها بعد البلوغ (٢)."
                ),
                "margin_notes": (
                    "متن الغاية والتقريب بالهامش العمودي المدار تسعين درجة: "
                    "وشرائط وجوب الصلاة ثلاثة أشياء: الإسلام والبلوغ والعقل وهو حد التكليف."
                ),
                "footnotes": (
                    "(١) فرق الأصوليون بين شروط الوجوب وشروط الصحة التي يتوقف عليها الاعتداد بالفعل.\n"
                    "(٢) لحديث: مروا أولادكم بالصلاة وهم أبناء سبع سنين، أخرجه أبو داود."
                ),
                "uncertain_words": [],
            },
            "gate_report": {"total_words": 88, "warnings": []},
        },
        {
            "pdf_page": 4,
            "tag": "p0004",
            "layout": "standard_single_col",
            "extracted": {
                "printed_page": "١٨",
                "running_header": "أدب المفتي والمستفتي",
                "matn": (
                    "باب آداب المستفتي وصفته\n"
                    "يلزم العامي ومن لم يبلغ رتبة الاجتهاد أن يستفتي أوثق العلماء في بلده دينا وعلما (1)، "
                    "فقد نص الأئمة سنة ۱۲۵ هـ في \u06a9تاب الفتوى على أنه يبحث عن الأعلم والأورع (2)، "
                    "ولا يتتبع الرخص الشاذة التي تخرق الإجماع لما في ذلك من انحلال ربقة التكليف (3)."
                ),
                "margin_notes": "[ق/ ١٣ ب]",
                "footnotes": (
                    "(1) قال الخطيب البغدادي في الفقيه والمتفقه: يجب عليه السؤال عمن يوثق بدينه وعلمه.\n"
                    "(2) توف\u06cc جماعة من التابعين على هذا القول وبه جزم ابن الصلاح.\n"
                    "(3) قال سليمان التيمي: لو أخذت برخصة كل عالم اجتمع فيك الشر كله."
                ),
                "uncertain_words": [],
            },
            "gate_report": {"total_words": 82, "warnings": []},
        },
        {
            "pdf_page": 5,
            "tag": "p0005",
            "layout": "standard_single_col",
            "extracted": {
                "printed_page": "١٩",
                "running_header": "أدب المفتي والمستفتي",
                "matn": (
                    "فصل في كتابة الفتوى وتوقيعها\n"
                    "ينبغي للمفتي أن يكتب الجواب بخط واضح مبين لا يحتمل اللبس ولا الإجمال المخل (١)، "
                    "وأن يختم فتواه بذكر الله تعالى والتفويض إليه فيقول: والله سبحانه وتعالى أعلم بالصواب (٢)، "
                    "والحمد لله رب العالمين وصلى الله على سيدنا محمد وعلى آله وصحبه وسلم."
                ),
                "margin_notes": "",
                "footnotes": (
                    "(١) وكان السلف يكرهون الإفتاء في رقعة ضيقة خشية أن يلحق بها ما ليس منها.\n"
                    "(٢) ثبت ذلك عن الصحابة والتابعين وأئمة المذاهب الأربعة رضي الله عنهم."
                ),
                "uncertain_words": [],
            },
            "gate_report": {"total_words": 72, "warnings": []},
        },
    ]

    for p in pages:
        p_path = os.path.join(pages_dir, f"{p['tag']}.json")
        with open(p_path, "w", encoding="utf-8") as f:
            json.dump(p, f, ensure_ascii=False, indent=2)

    return pages


def build_real_world_edge_cases_fixture(pages_dir: str) -> list[dict]:
    """
    يبني 6 صفحات واقعية مستمدة من الحالات الحدية الفعلية في الكتب التراثية المصورة:
      - ص 1 (كالمتوهم للمحاسبي ص 9): 4 حواشٍ أفقية في سطر واحد `(١) تحت .    (٢) ...    (٣) ...    (٤) ...`
        وإشارة مخطوطة نجمية `( * )` في المتن بدون حاشية نجمية.
      - ص 2 (كالضروري لابن رشد ص 51 + السيرافي): إحالة رقم ملتصق بالكلمة `هما1`، وإحالة معقوفة `[٢]`،
        وإحالة فوقية `³`، وحاشية نجمية `( * )`، مع بداية حاشية مستمرة عبر الصفحات.
      - ص 3 (كأدب المفتي ص 86): تكملة الحاشية السابقة بعلامة `(=) ...`، وعنوان مدمج في السطر (Run-in Heading)
        `القسم الأوَّل: المفتي المستقل، وشَرْطُهُ: ...`، ورقم مرجعي داخلي في الحاشية `طبعة دار الكتب العلمية (٢) ١٣٣٠`
        لا يجوز شطره كحاشية جديدة، مع تكرار الرأس الجاري في مطلع الصفحة.
      - ص 4 (كرسالة ابن تيمية ص 152 و154): تكملة حاشية بعلامة `= ...`، وعنوان مركب من سطرين (`الباب الثاني / في آداب الفتوى`)،
        وحاشية مشتركة لموضعين `[الأنام](١)` و`[الباقي](١)`، وحاشية ثانية `(٢)`.
      - ص 5 (كرسالة ابن تيمية ص 154 و158): سقوط مطبعي لإحالة `(١)` في المتن مع وجود الكلمة المحققة `يظهرون`
        وقبل `البرطيل(٢)`، وآية قرآنية متعددة الأرقام `﴿... (٢) ... (٣) ...﴾(٣)`.
      - ص 6 (كرسالة ابن تيمية ص 160): عنوان معقوف ممتد على 3 أسطر `[موقف من مواقف الشيخ / في / إبطال حيل أهل الطرق الدجالين](١)`
        مع 3 إحالات مشتركة لنفس الحاشية `(١) من المطبوع .`، وحاشيتين مستقلتين بنفس الرقم `(٢)` في نفس الصفحة.
    """
    os.makedirs(pages_dir, exist_ok=True)
    pages = [
        {
            "pdf_page": 1,
            "tag": "p0001",
            "layout": "standard_single_col",
            "extracted": {
                "printed_page": "- ٩ -",
                "running_header": "كتاب التوهم وأصول الفتوى",
                "matn": (
                    "كتاب التوهم وأصول الفتوى\n"
                    "والملائكة ينظرون إليهم قد نكسوا الرؤوس (١) لما دهشهم من ذلك الهول العظيم، "
                    "وقاموا على أقدامهم شاخصة أبصارهم ينتظرون النداء (٢) من رب العالمين لفصل القضاء ( * ) إلى دار السعادة "
                    "أو إلى دار الشقاء فلا ينظرون (٣) إلا إلى هول المطلع لقوله: ﴿يَوْمَ يَقُومُ النَّاسُ لِرَبِّ الْعَالَمِينَ﴾ (٤)."
                ),
                "margin_notes": "",
                "footnotes": "(١) تحت .    (٢) منتظر باليد الأولى .    (٣) ينظروا .    (٤) سورة ٨٣: ٦",
                "uncertain_words": [],
            },
        },
        {
            "pdf_page": 2,
            "tag": "p0002",
            "layout": "standard_single_col",
            "extracted": {
                "printed_page": "١٠",
                "running_header": "كتاب التوهم وأصول الفتوى",
                "matn": (
                    "القول في القسم الثالث من الجزء الأول ( * )\n"
                    "والمعاني التي تشتمل عليها الألفاظ في دلالتها على الأحكام الشرعية شرطان هما1 أن يفهم المعنى "
                    "الأصلي من السياق العربي الفصيح [٢]، وأن يعرف وجه الاستدلال به عند أئمة الأصول والفقهاء³ "
                    "من غير تعسف ولا خروج عن قانون اللغة."
                ),
                "margin_notes": "",
                "footnotes": (
                    "[*] ترجمة هذا الفصل مستفادة من النسخة الخطية المحفوظة في خزانة القرويين.\n"
                    "( 1 ) في الأصل : منهما ، والتصويب من النسخة المغربية.\n"
                    "[٢] راجع المستصفى للغزالي والبرهان لإمام الحرمين الجويني.\n"
                    "³ قال الشافعي في الرسالة: اللسان العربي أوسع الألسنة مذهباً وأكثرها ألفاظاً، وتتمة كلامه في الصفحة التالية"
                ),
                "uncertain_words": [],
            },
        },
        {
            "pdf_page": 3,
            "tag": "p0003",
            "layout": "standard_single_col",
            "extracted": {
                "printed_page": "١١",
                "running_header": "كتاب التوهم وأصول الفتوى",
                "matn": (
                    "كتاب التوهم وأصول الفتوى\n"
                    "القسم الأوَّل: المفتي المستقل، وشَرْطُهُ: أنْ يكونَ قيِّماً بمعرفة أدلَّة الأحكام الشَّرعيَّة من الكتاب والسُّنَّة (١) "
                    "والإجماع والقياس وما التحق بها على التفصيل المبين في كتب الفقه وتيسرت له الملكة الفقهية التامة (٢)."
                ),
                "margin_notes": "",
                "footnotes": (
                    "(=) ولا يحيط بجميع لسان العرب إلا نبي، ولكن لا يذهب منه شيء على عامتها.\n"
                    "١. أصل هذا التقسيم ذكره أبو الحسين البصري في المعتمد وتبعه ابن الصلاح.\n"
                    "(٢) كذا في «ش» ، وكذا في «الأشباه والنظائر» للسيوطي - طبعة دار الكتب العلمية (٢) ١٣٣٠ - ١٣٣١ وقد سقط من بقية النسخ"
                ),
                "uncertain_words": [],
            },
        },
        {
            "pdf_page": 4,
            "tag": "p0004",
            "layout": "standard_single_col",
            "extracted": {
                "printed_page": "١٢",
                "running_header": "كتاب التوهم وأصول الفتوى",
                "matn": (
                    "الباب الثاني\n"
                    "في آداب الفتوى وسياسة الأنام\n"
                    "وهؤلاء هم الخارجون عن شرائع الإسلام وإن تمسكوا ببعض سياسة [الأنام](١)، "
                    "والصنف [الباقي](١) أهل البدع والأهواء المفارقون للسنة والجماعة الذين حذر العلماء من فتنتهم (٢)."
                ),
                "margin_notes": "",
                "footnotes": (
                    "= لوروده في حاشية النسخة الدمشقية المعتمدة في المقابلة.\n"
                    "(١) كذا في الأصل ، وفي المطبوع : الإسلام ، و«الصنف الثاني» بدلاً من «الباقي».\n"
                    "(٢) انظر مجموع الفتاوى لشيخ الإسلام ابن تيمية ج ٢٨ ص ٤١٠."
                ),
                "uncertain_words": [],
            },
        },
        {
            "pdf_page": 5,
            "tag": "p0005",
            "layout": "standard_single_col",
            "extracted": {
                "printed_page": "١٣",
                "running_header": "كتاب التوهم وأصول الفتوى",
                "matn": (
                    "وقد حصل بأيدي المسلمين طائفة من كتبهم، وهم مع هذا يظهرون التقية والنفاق، "
                    "ويتقربون ببذل الأموال إلى من يقبلها منهم ويبذلونه من البرطيل(٢) لمن يقصدهم، "
                    "وهم يشبهون من ذكرهم الله في قوله: ﴿يُخْرِبُونَ بُيُوتَهُمْ بِأَيْدِيهِمْ وَأَيْدِي الْمُؤْمِنِينَ فَاعْتَبِرُوا يَا أُولِي الْأَبْصَارِ (٢) "
                    "وَلَوْلَا أَنْ كَتَبَ اللَّهُ عَلَيْهِمُ الْجَلَاءَ لَعَذَّبَهُمْ فِي الدُّنْيَا وَلَهُمْ فِي الْآخِرَةِ عَذَابُ النَّارِ (٣)﴾(٣)."
                ),
                "margin_notes": "[ق/ ٥٥ أ]",
                "footnotes": (
                    "(١) كذا في الأصل ، وفي المطبوع : ويتظاهرون .\n"
                    "(٢) الرشوة .\n"
                    "(٣) [سورة الحشر : ٢-٣] ."
                ),
                "uncertain_words": [],
            },
        },
        {
            "pdf_page": 6,
            "tag": "p0006",
            "layout": "standard_single_col",
            "extracted": {
                "printed_page": "١٤",
                "running_header": "كتاب التوهم وأصول الفتوى",
                "matn": (
                    "الحمد [لله](١) الذي بنعمته تتم الصالحات وتدوم البركات.\n"
                    "[موقف من مواقف الشيخ\n"
                    "في\n"
                    "إبطال حيل أهل الطرق الدجالين](١)\n"
                    "حضر جماعة من المشايخ سنة خمس [وسبعمائة](١) في مجلس القضاء بدمشق المحروسة (٢)، "
                    "فأبطل الشيخ شبهاتهم بالحجة والبرهان الساطع (٢) والحمد لله رب العالمين."
                ),
                "margin_notes": "",
                "footnotes": (
                    "(١) من المطبوع .\n"
                    "(٢) في النسخة التيمورية: بدمشق الشام.\n"
                    "(٢) حاشية ثانية مكررة الرقم في ذيل الصفحة نفسها لبيان تمام الواقعة."
                ),
                "uncertain_words": [],
            },
        },
    ]

    for p in pages:
        p_path = os.path.join(pages_dir, f"{p['tag']}.json")
        with open(p_path, "w", encoding="utf-8") as f:
            json.dump(p, f, ensure_ascii=False, indent=2)

    return pages


def run_gate_1_original_visual_gates() -> list[str]:
    """Gate 1: تشغيل بوابات test_pdf_gates.py الأصلية (12 اختباراً) والتأكد من عدم كسر أي قاعدة بصرية."""
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromModule(test_pdf_gates)
    buf = io.StringIO()
    runner = unittest.TextTestRunner(stream=buf, verbosity=2)
    result = runner.run(suite)
    errors = []
    if result.TestsRun != 12 if hasattr(result, "TestsRun") else result.testsRun < 12:
        errors.append(f"Gate 1 expected >= 12 unit tests in test_pdf_gates.py, ran {result.testsRun}")
    for test_case, tb in result.failures + result.errors:
        errors.append(f"Gate 1 failure in {test_case}: {tb.strip()}")
    return errors


def run_gate_2_and_gate_3_adapter_and_manifest_v4() -> tuple[list[str], list[str], dict]:
    """
    Gate 2: اختبار pdf_to_preflight_adapter.py على 5 صفحات واقعية والتحقق من حفظ 100% من الحروف والحواشي.
    Gate 3: تمرير مخرجات المحول فعلياً إلى manifest_v4.py و fn_linker_v4.py والتحقق من نجاح توليد الـ Manifest بصفر أخطاء.
    """
    gate2_errors = []
    gate3_errors = []
    summary_stats = {}

    with tempfile.TemporaryDirectory(prefix="turath_pdf_adapter_test_") as tmp_root:
        book_in_dir = os.path.join(tmp_root, "adab_almufti_pdf_out")
        pages_dir = os.path.join(book_in_dir, "pages")
        preflight_out_dir = os.path.join(tmp_root, "preflight_v4_out")

        build_realistic_5_pages_fixture(pages_dir)

        adapter_rep = convert_pdf_output_to_preflight(
            input_path=book_in_dir,
            out_dir=preflight_out_dir,
            book_id=9001,
            science="fiqh",
            round_num=99,
            title="أدب المفتي والمستفتي",
            author="ابن الصلاح الشهرزوري",
            death="643",
            juz=1,
            run_manifest_v4=True,
            deep_indexing_scripts_dir=DEFAULT_DEEP_INDEXING_SCRIPTS,
        )

        # ---- فحوص Gate 2 (الحفاظ الحرفي 100% وتوليد الملفات المعيارية) ----
        zl = adapter_rep.get("zero_loss_check", {})
        if not zl.get("passed"):
            gate2_errors.append(f"Zero-Loss check failed: {zl.get('errors')}")
        if zl.get("body_char_loss", -1) != 0:
            gate2_errors.append(f"Non-zero body char loss: {zl.get('body_char_loss')}")
        if zl.get("footnotes_char_loss", -1) != 0:
            gate2_errors.append(f"Non-zero footnotes char loss: {zl.get('footnotes_char_loss')}")
        if zl.get("retention_pct") != 100.0:
            gate2_errors.append(f"Expected 100.0% retention, got {zl.get('retention_pct')}")
        if zl.get("source_body_sha256") != zl.get("book_matn_body_sha256"):
            gate2_errors.append("SHA-256 mismatch between source body and book_matn.txt")
        if zl.get("source_body_sha256") != zl.get("snapshot_parts_body_sha256"):
            gate2_errors.append("SHA-256 mismatch between source body and snapshot 0*.json parts")
        if zl.get("source_footnotes_sha256") != zl.get("actual_footnotes_sha256"):
            gate2_errors.append("SHA-256 mismatch between source footnotes and footnotes.json")

        if adapter_rep.get("non_blank_pages") != 5:
            gate2_errors.append(f"Expected 5 non-blank pages, got {adapter_rep.get('non_blank_pages')}")
        if adapter_rep.get("framed_hashiya_pages") != 1:
            gate2_errors.append(f"Expected 1 framed_hashiya page, got {adapter_rep.get('framed_hashiya_pages')}")
        if adapter_rep.get("total_footnotes_count") != 13:
            gate2_errors.append(f"Expected 13 total footnotes across 5 pages, got {adapter_rep.get('total_footnotes_count')}")

        # فحص توليد ملفات p0001.txt .. p0005.txt وعلامات الصفحات [ص: N]
        for i, expected_pg in enumerate(["١٥", "١٦", "١٧", "١٨", "١٩"], 1):
            tag = f"p{i:04d}"
            sidecar_txt = os.path.join(pages_dir, f"{tag}.txt")
            out_txt = os.path.join(preflight_out_dir, "pages_txt", f"{tag}.txt")
            if not os.path.isfile(sidecar_txt) or not os.path.isfile(out_txt):
                gate2_errors.append(f"Missing page .txt sidecar for {tag}")
            else:
                txt_c = Path(sidecar_txt).read_text(encoding="utf-8")
                if f"[ص: {expected_pg}]" not in txt_c:
                    gate2_errors.append(f"Page marker [ص: {expected_pg}] missing in {sidecar_txt}")

        book_matn_txt = Path(adapter_rep["files_generated"]["book_matn_txt"]).read_text(encoding="utf-8")
        for expected_pg in ["١٥", "١٦", "١٧", "١٨", "١٩"]:
            if f"[ص: {expected_pg}]" not in book_matn_txt:
                gate2_errors.append(f"Standard page marker [ص: {expected_pg}] missing in book_matn.txt")
        if "متن الغاية والتقريب بالهامش العمودي المدار تسعين درجة" not in book_matn_txt:
            gate2_errors.append("Azhari framed_hashiya 90° rotated outer margin text missing in book_matn.txt")
        if "سنة ١٢٥ هـ في كتاب الفتوى" not in book_matn_txt:
            gate2_errors.append("Persian digits/chars on page 4 were not normalized to Arabic standard in book_matn.txt")

        # ---- فحوص Gate 3 (التكامل الفعلي مع manifest_v4.py و fn_linker_v4.py) ----
        mv4 = adapter_rep.get("manifest_v4_verification", {})
        if not mv4.get("executed"):
            gate3_errors.append("manifest_v4.py was not executed by adapter")
        if not mv4.get("passed"):
            gate3_errors.extend(mv4.get("errors") or ["manifest_v4_verification reported passed=False"])

        # فحص استدعاء build_book_window_and_manifest و link_book_footnotes_v4 برمجياً أيضاً
        sys.path.insert(0, DEFAULT_DEEP_INDEXING_SCRIPTS)
        import fn_linker_v4 as fnv4  # noqa: E402
        import manifest_v4 as man_v4  # noqa: E402

        orig_base = man_v4.BASE
        orig_snap = man_v4.SNAPSHOT_DIR
        try:
            man_v4.BASE = Path(preflight_out_dir)
            man_v4.SNAPSHOT_DIR = man_v4.BASE / "source_snapshots"
            m_entry, win_parts, win_fns, toc_data = man_v4.build_book_window_and_manifest(99, "fiqh", 9001)
            fn_direct = fnv4.link_book_footnotes_v4(9001, "fiqh", win_parts)

            if m_entry.get("status") not in ("OK_WHOLE_PARTS", "OK_SLICED_WINDOW"):
                gate3_errors.append(f"Unexpected manifest status: {m_entry.get('status')}")
            if m_entry.get("window_coverage_pct") != 100.0:
                gate3_errors.append(f"Expected 100.0% window coverage, got {m_entry.get('window_coverage_pct')}")
            if m_entry.get("fn_linked_count") != 13:
                gate3_errors.append(f"Expected 13 linked footnotes in manifest_v4, got {m_entry.get('fn_linked_count')}")
            if m_entry.get("fn_unlinked_in_window_count") != 0:
                gate3_errors.append(f"Expected 0 unlinked footnotes, got {m_entry.get('fn_unlinked_in_window_count')}")
            if m_entry.get("unclassified_tokens_count") != 0:
                gate3_errors.append(f"Expected 0 unclassified tokens, got {m_entry.get('unclassified_tokens_count')}")
            if m_entry.get("token_classes", {}).get("verse_no") != 1:
                gate3_errors.append(
                    f"Expected Quranic verse number (٤٣) to be classified as verse_no=1, got {m_entry.get('token_classes')}"
                )
            if fn_direct.get("p0_errors"):
                gate3_errors.extend(fn_direct["p0_errors"])
        finally:
            man_v4.BASE = orig_base
            man_v4.SNAPSHOT_DIR = orig_snap

        # تنظيف الملف المؤقت الذي يكتبه manifest_v4 في /tmp/r99_fiqh.txt
        tmp_dump = "/tmp/r99_fiqh.txt"
        if os.path.exists(tmp_dump):
            try:
                os.remove(tmp_dump)
            except OSError:
                pass

        summary_stats = {
            "pages_tested": adapter_rep.get("non_blank_pages"),
            "parts_built": adapter_rep.get("total_parts_built"),
            "footnotes_linked": mv4.get("book_manifest", {}).get("fn_linked_count", 0),
            "retention_pct": zl.get("retention_pct"),
            "body_chars": zl.get("body_stream_chars"),
            "fn_chars": zl.get("footnotes_stream_chars"),
        }

    return gate2_errors, gate3_errors, summary_stats


def run_gate_4_real_world_edge_cases() -> tuple[list[str], dict]:
    """
    Gate 4: اختبار الحالات الحدية الواقعية المستخرجة من الكتب التراثية:
      - صيغ الحواشي غير القياسية (`[١]`, `(*)`, `( * )`, `[*]`, `¹²³`, `هما1`, `١.`)
      - الحواشي الأفقية المتعددة في سطر واحد (`(١) ...   (٢) ...   (٣) ...   (٤) ...`)
      - حواشي الاستمرار العابرة للصفحات (`= ...` و`(=) ...`)
      - الحواشي المشتركة لأكثر من موضع في الصفحة، وتعدد الحواشي بنفس الرقم في الصفحة، وتثبيت الإحالة الساقطة
      - كبح الرؤوس الجارية المتكررة، والعناوين المركبة متعددة الأسطر والعناوين المدمجة (Run-in Headings)
    """
    gate4_errors = []
    g4_stats = {}

    with tempfile.TemporaryDirectory(prefix="turath_pdf_gate4_test_") as tmp_root:
        book_in_dir = os.path.join(tmp_root, "real_world_edge_book")
        pages_dir = os.path.join(book_in_dir, "pages")
        preflight_out_dir = os.path.join(tmp_root, "preflight_v4_out")

        build_real_world_edge_cases_fixture(pages_dir)

        adapter_rep = convert_pdf_output_to_preflight(
            input_path=book_in_dir,
            out_dir=preflight_out_dir,
            book_id=9002,
            science="fiqh",
            round_num=98,
            title="كتاب التوهم وأصول الفتوى",
            author="الحارث المحاسبي وابن تيمية",
            death="728",
            juz=1,
            run_manifest_v4=True,
            deep_indexing_scripts_dir=DEFAULT_DEEP_INDEXING_SCRIPTS,
        )

        zl = adapter_rep.get("zero_loss_check", {})
        if not zl.get("passed") or zl.get("retention_pct") != 100.0:
            gate4_errors.append(f"Gate 4 Zero-Loss check failed: {zl.get('errors')}")

        mv4 = adapter_rep.get("manifest_v4_verification", {})
        if not mv4.get("passed"):
            gate4_errors.extend(mv4.get("errors") or ["Gate 4 manifest_v4_verification failed"])

        norm_totals = adapter_rep.get("normalization_totals", {})
        if norm_totals.get("horizontal_splits", 0) < 3:
            gate4_errors.append(f"Expected >= 3 horizontal footnote splits on page 1, got {norm_totals.get('horizontal_splits')}")
        if norm_totals.get("cross_page_continuations_merged", 0) != 2:
            gate4_errors.append(
                f"Expected 2 cross-page continuation footnotes merged, got {norm_totals.get('cross_page_continuations_merged')}"
            )
        if norm_totals.get("shared_markers_spaced", 0) < 3:
            gate4_errors.append(
                f"Expected >= 3 shared excess footnote markers spaced, got {norm_totals.get('shared_markers_spaced')}"
            )
        if norm_totals.get("missing_matn_markers_anchored", 0) != 1:
            gate4_errors.append(
                f"Expected 1 missing matn marker anchored on page 5, got {norm_totals.get('missing_matn_markers_anchored')}"
            )

        # إجمالي الحواشي الفعلية عبر الصفحات الست:
        # ص1: 4 حواشٍ أفقية | ص2: 4 حواشٍ (*، 1، 2، 3) | ص3: تكملة + حاشيتان (1، 2) | ص4: تكملة + حاشيتان (1، 2)
        # ص5: 3 حواشٍ (1، 2، 3) | ص6: 3 حواشٍ (1، 2، 2) => المجموع = 18 حاشية
        if adapter_rep.get("total_footnotes_count") != 18:
            gate4_errors.append(f"Expected 18 total footnotes in Gate 4, got {adapter_rep.get('total_footnotes_count')}")

        bm = mv4.get("book_manifest", {})
        if bm.get("fn_linked_count") != 18:
            gate4_errors.append(f"Expected 18 linked footnotes in manifest_v4, got {bm.get('fn_linked_count')}")
        if bm.get("fn_continuation_merged_count") != 2:
            gate4_errors.append(
                f"Expected fn_continuation_merged_count=2 in manifest_v4, got {bm.get('fn_continuation_merged_count')}"
            )
        if bm.get("fn_unlinked_in_window_count") != 0:
            gate4_errors.append(f"Expected 0 unlinked footnotes in Gate 4, got {bm.get('fn_unlinked_in_window_count')}")
        if bm.get("unclassified_tokens_count") != 0:
            gate4_errors.append(f"Expected 0 unclassified tokens in Gate 4, got {bm.get('unclassified_tokens_count')}")

        # التحقق من الفهرس الهيكلي (toc.json):
        # 1. عدم تقطيع الرأس الجاري المتكرر "كتاب التوهم وأصول الفتوى" في ص 3
        # 2. استخلاص العنوان المدمج "القسم الأوَّل: المفتي المستقل"
        # 3. استخلاص العنوان المركب من سطرين "الباب الثاني في آداب الفتوى وسياسة الأنام"
        # 4. استخلاص العنوان المعقوف الممتد على 3 أسطر "موقف من مواقف الشيخ في إبطال حيل أهل الطرق الدجالين"
        toc_data = json.loads(Path(adapter_rep["files_generated"]["toc_json"]).read_text(encoding="utf-8"))
        toc_titles = [e["t"] for e in toc_data.get("toc", [])]

        if "القسم الأوَّل: المفتي المستقل" not in toc_titles:
            gate4_errors.append(f"Run-in heading 'القسم الأوَّل: المفتي المستقل' missing from TOC: {toc_titles}")
        if "الباب الثاني في آداب الفتوى وسياسة الأنام" not in toc_titles:
            gate4_errors.append(
                f"Two-line compound heading 'الباب الثاني في آداب الفتوى وسياسة الأنام' missing from TOC: {toc_titles}"
            )
        if "موقف من مواقف الشيخ في إبطال حيل أهل الطرق الدجالين" not in toc_titles:
            gate4_errors.append(
                f"Multi-line bracketed heading 'موقف من مواقف الشيخ في إبطال حيل أهل الطرق الدجالين' missing from TOC: {toc_titles}"
            )
        if toc_titles.count("كتاب التوهم وأصول الفتوى") > 1:
            gate4_errors.append(f"Repeated running header triggered duplicate TOC parts: {toc_titles}")

        # تنظيف الملف المؤقت الذي يكتبه manifest_v4 في /tmp/r98_fiqh.txt
        tmp_dump = "/tmp/r98_fiqh.txt"
        if os.path.exists(tmp_dump):
            try:
                os.remove(tmp_dump)
            except OSError:
                pass

        g4_stats = {
            "pages": adapter_rep.get("non_blank_pages"),
            "parts": adapter_rep.get("total_parts_built"),
            "fn_linked": bm.get("fn_linked_count", 0),
            "continuations": bm.get("fn_continuation_merged_count", 0),
            "horiz_splits": norm_totals.get("horizontal_splits", 0),
        }

    return gate4_errors, g4_stats


def build_multi_zone_commentary_fixture(pages_dir: str) -> list[dict]:
    """
    يبني صفحتين من كتاب شرح وأصول متعدد المناطق (`Matn / Sharh / Footnotes`):
      - ص 1: تحتوي `matn_top` محصوراً بين `﴿...﴾` مع عنوان زهري `﴿فصل في القياس وشروطه﴾` وإحالة معقوفة `[١]`،
        و`sharh_body` يحوي كلمتين مقطوعتين عبر السطر بالكشيدة والشرطة (`المسـ\\nـألة`، `باجـ-\\nـتهاد`)،
        وإحالتي حاشية `(٢)` و`(3)`، وآية قرآنية حقيقية `﴿وَأَقِيمُوا الصَّلَاةَ﴾ (٤٣)`،
        و`footnotes` مهيكلة كقائمة قواميس `list[dict]` فيها رقم مختلط `١25`، ورقم صفحة مختلط `"١5"`.
      - ص 2: تحتوي متناً وشرحاً مفصولين بفاصل `--- الشرح ---`، وحاشية نصية متعددة الأسطر تبدأ بتكملة
        `= تكملة الحاشية السابقة...` وتليها حاشية `(١)` فيها كلمة مقطوعة `الاست-\\nحسان` ورقم مختلط `٢40`.
    """
    os.makedirs(pages_dir, exist_ok=True)
    pages = [
        {
            "pdf_page": 1,
            "tag": "p0001",
            "layout": "standard_single_col",
            "extracted": {
                "printed_page": "١5",
                "running_header": "شرح مختصر المنتهى الأصولي",
                "matn_top": (
                    "﴿فصل في القياس وشروطه﴾\n"
                    "﴿قال المصنف رحمه الله: القياس حمل معلوم على معلوم في إثبات حكم لهما [١] أو نفيه عنهما بأمر جامع بينهما﴾"
                ),
                "sharh_body": (
                    "أقول: اعلم أن هذه المسـ\n"
                    "ـألة من أمهات مسائل الأصول التي يدرك حكمها باجـ-\n"
                    "ـتهاد النظر الصحيح (٢)، وقد دل على حجية القياس قوله تعالى: ﴿وَأَقِيمُوا الصَّلَاةَ﴾ (٤٣) "
                    "في سياق الاعتبار والقياس الجلي (3)."
                ),
                "margin_notes": "[ق/ ٢١ أ]",
                "footnotes": [
                    {"id": "1", "text": "في النسخة الأزهرية زيادة بعد قوله لهما."},
                    {"id": "2", "text": "انظر المستصفى للغزالي ص ١25."},
                    {"id": "3", "text": "وهو القياس القطعي الذي لا يحتمل النقيض عند الأصوليين"},
                ],
                "uncertain_words": [],
            },
        },
        {
            "pdf_page": 2,
            "tag": "p0002",
            "layout": "standard_single_col",
            "extracted": {
                "printed_page": "١6",
                "running_header": "شرح مختصر المنتهى الأصولي",
                "text": (
                    "﴿باب شروط العلة في القياس الشرعي﴾\n"
                    "﴿ومن شرط علة الحكم أن تكون وصفا ظاهرا منضبطا مطردا (١)﴾\n"
                    "--- الشرح ---\n"
                    "الشرح: يعني أن الوصف الجامع بين الأصل والفرع لا يصح التعليل به إلا إذا كان ظاهرا جليا منضبطا "
                    "بنفسه لا يختلف باختلاف الأشخاص والأحوال."
                ),
                "margin_notes": "",
                "footnotes": (
                    "= تكملة الحاشية السابقة من الصفحة الماضية في بيان القياس القطعي.\n"
                    "(١) أخرجه أصحاب السنن وذكره الأصوليون في مبحث الاست-\nحسان القياسي ص ٢40."
                ),
                "uncertain_words": [],
            },
        },
    ]

    for p in pages:
        p_path = os.path.join(pages_dir, f"{p['tag']}.json")
        with open(p_path, "w", encoding="utf-8") as f:
            json.dump(p, f, ensure_ascii=False, indent=2)

    return pages


def run_gate_5_multi_zone_and_validator_contract() -> tuple[list[str], dict]:
    """
    Gate 5: Multi-Zone Matn/Sharh/Footnote Page Layout & Validator Contract Gate:
      - التحقق من توافق `validate_json.py` و`pdf_to_preflight_adapter.py` على صفحات `matn_top` + `sharh_body` + `footnotes`
        بصيغتي القواميس المهيكلة `list[dict]` والنص متعدد الأسطر مع حواشي الاستمرار `= ...`.
      - التحقق من إصلاح الكلمات المقطوعة بالكشيدة/الشرطة (`المسألة`، `باجتهاد`، `الاستحسان`) وتطبيع الأرقام المختلطة (`١٥`، `١٢٥`، `٢٤٠`).
      - التحقق من حفظ محددات `matn_top` (`﴿...﴾`) بنسبة 100% وتطبيع إحالة `[١]` داخل المتن المشروح دون كسر الآية القرآنية `﴿وَأَقِيمُوا الصَّلَاةَ﴾ (٤٣)`.
      - التحقق من نجاح `manifest_v4.py` و`fn_linker_v4.py` بصفر حواشٍ غير مربوطة وصفر رموز غير مصنفة.
    """
    from validate_json import validate_pages_payload

    gate5_errors = []
    g5_stats = {}

    with tempfile.TemporaryDirectory(prefix="turath_pdf_gate5_test_") as tmp_root:
        book_in_dir = os.path.join(tmp_root, "multi_zone_sharh_book")
        pages_dir = os.path.join(book_in_dir, "pages")
        preflight_out_dir = os.path.join(tmp_root, "preflight_v4_out")

        raw_pages = build_multi_zone_commentary_fixture(pages_dir)

        # 1. اختبار validate_json.py على الصفحات الخام قبل التحويل
        val_report = validate_pages_payload({"pages": json.loads(json.dumps(raw_pages))}, normalize_in_place=True)
        if not val_report.get("valid"):
            gate5_errors.append(f"validate_json.py failed on multi-zone fixture: {val_report.get('errors')}")

        p1_rep = val_report["page_reports"][0]
        if p1_rep.get("printed_page") != "١٥":
            gate5_errors.append(f"Expected normalized printed_page '١٥', got {p1_rep.get('printed_page')!r}")

        p1_zones = p1_rep.get("zones", {})
        if "(١)" not in p1_zones.get("matn_top", ""):
            gate5_errors.append(f"Expected '[١]' inside matn_top ﴿...﴾ to normalize to '(١)', got: {p1_zones.get('matn_top')}")
        if not p1_zones.get("matn_top_delimiters_preserved"):
            gate5_errors.append("Expected matn_top_delimiters_preserved=True in Gate 5 page 1")

        # 2. اختبار pdf_to_preflight_adapter.py + manifest_v4.py + fn_linker_v4.py
        adapter_rep = convert_pdf_output_to_preflight(
            input_path=book_in_dir,
            out_dir=preflight_out_dir,
            book_id=9003,
            science="usul",
            round_num=97,
            title="شرح مختصر المنتهى الأصولي",
            author="العضد الإيجي",
            death="756",
            juz=1,
            run_manifest_v4=True,
            deep_indexing_scripts_dir=DEFAULT_DEEP_INDEXING_SCRIPTS,
        )

        zl = adapter_rep.get("zero_loss_check", {})
        if not zl.get("passed") or zl.get("retention_pct") != 100.0:
            gate5_errors.append(f"Gate 5 Zero-Loss check failed: {zl.get('errors')}")

        mv4 = adapter_rep.get("manifest_v4_verification", {})
        if not mv4.get("passed"):
            gate5_errors.extend(mv4.get("errors") or ["Gate 5 manifest_v4_verification failed"])

        bm = mv4.get("book_manifest", {})
        if bm.get("fn_linked_count") != 4:
            gate5_errors.append(f"Expected 4 linked footnotes in Gate 5, got {bm.get('fn_linked_count')}")
        if bm.get("fn_continuation_merged_count") != 1:
            gate5_errors.append(f"Expected 1 continuation merged in Gate 5, got {bm.get('fn_continuation_merged_count')}")
        if bm.get("fn_unlinked_in_window_count") != 0:
            gate5_errors.append(f"Expected 0 unlinked footnotes in Gate 5, got {bm.get('fn_unlinked_in_window_count')}")
        if bm.get("unclassified_tokens_count") != 0:
            gate5_errors.append(f"Expected 0 unclassified tokens in Gate 5, got {bm.get('unclassified_tokens_count')}")

        book_matn_txt = Path(adapter_rep["files_generated"]["book_matn_txt"]).read_text(encoding="utf-8")
        fn_json_txt = Path(adapter_rep["files_generated"]["footnotes_json"]).read_text(encoding="utf-8")

        for expected_word in ("المسألة", "باجتهاد"):
            if expected_word not in book_matn_txt:
                gate5_errors.append(f"Repaired word {expected_word!r} missing from book_matn.txt")
        if "الاستحسان" not in fn_json_txt:
            gate5_errors.append("Repaired word 'الاستحسان' missing from footnotes.json")
        for expected_num in ("١٢٥", "٢٤٠"):
            if expected_num not in fn_json_txt:
                gate5_errors.append(f"Normalized mixed number {expected_num!r} missing from footnotes.json")

        toc_data = json.loads(Path(adapter_rep["files_generated"]["toc_json"]).read_text(encoding="utf-8"))
        toc_titles = [e["t"] for e in toc_data.get("toc", [])]
        if not any("فصل في القياس وشروطه" in t for t in toc_titles):
            gate5_errors.append(f"Floral-bracketed heading 'فصل في القياس وشروطه' missing from TOC: {toc_titles}")
        if not any("باب شروط العلة في القياس الشرعي" in t for t in toc_titles):
            gate5_errors.append(f"Floral-bracketed heading 'باب شروط العلة في القياس الشرعي' missing from TOC: {toc_titles}")

        tmp_dump = "/tmp/r97_usul.txt"
        if os.path.exists(tmp_dump):
            try:
                os.remove(tmp_dump)
            except OSError:
                pass

        norm_totals = adapter_rep.get("normalization_totals", {})
        g5_stats = {
            "pages": adapter_rep.get("non_blank_pages"),
            "parts": adapter_rep.get("total_parts_built"),
            "fn_linked": bm.get("fn_linked_count", 0),
            "continuations": bm.get("fn_continuation_merged_count", 0),
            "splits_repaired": norm_totals.get("line_break_splits_repaired", 0),
            "struct_fn_coerced": norm_totals.get("structured_footnote_items_coerced", 0),
        }

    return gate5_errors, g5_stats


def main():
    print("======================================================================")
    print("  turath-pdf-to-text v2.2 — Deterministic Quality & Pre-Flight Gates")
    print("======================================================================")

    g1_errors = run_gate_1_original_visual_gates()
    print(f"[Gate 1] Original Visual & DB Gates (12 tests)      : {'PASS' if not g1_errors else 'FAIL'} ({len(g1_errors)} errors)")

    g2_errors, g3_errors, stats = run_gate_2_and_gate_3_adapter_and_manifest_v4()
    print(
        f"[Gate 2] Adapter 100% Zero-Loss (5 pages + Hashiya) : {'PASS' if not g2_errors else 'FAIL'} ({len(g2_errors)} errors) "
        f"[retention={stats.get('retention_pct')}%, body_chars={stats.get('body_chars')}, fn_chars={stats.get('fn_chars')}]"
    )
    print(
        f"[Gate 3] Pre-Flight manifest_v4 & fn_linker_v4      : {'PASS' if not g3_errors else 'FAIL'} ({len(g3_errors)} errors) "
        f"[parts={stats.get('parts_built')}, fn_linked={stats.get('footnotes_linked')}/13]"
    )

    g4_errors, g4_stats = run_gate_4_real_world_edge_cases()
    print(
        f"[Gate 4] Real-World Multi-Format, Headers & Cont.   : {'PASS' if not g4_errors else 'FAIL'} ({len(g4_errors)} errors) "
        f"[parts={g4_stats.get('parts')}, fn_linked={g4_stats.get('fn_linked')}/18, "
        f"cont={g4_stats.get('continuations')}, horiz={g4_stats.get('horiz_splits')}]"
    )

    g5_errors, g5_stats = run_gate_5_multi_zone_and_validator_contract()
    print(
        f"[Gate 5] Multi-Zone Matn/Sharh & Validator Contract : {'PASS' if not g5_errors else 'FAIL'} ({len(g5_errors)} errors) "
        f"[parts={g5_stats.get('parts')}, fn_linked={g5_stats.get('fn_linked')}/4, "
        f"splits_fixed={g5_stats.get('splits_repaired')}, struct_fn={g5_stats.get('struct_fn_coerced')}]"
    )

    all_errors = g1_errors + g2_errors + g3_errors + g4_errors + g5_errors
    if all_errors:
        print("\n[ERRORS DETECTED]:")
        for err in all_errors:
            print(f"  - {err}")
        print(f"\nFAIL ({len(all_errors)} errors)")
        sys.exit(1)

    print("----------------------------------------------------------------------")
    print("PASS (0 errors)")
    sys.exit(0)


if __name__ == "__main__":
    main()
