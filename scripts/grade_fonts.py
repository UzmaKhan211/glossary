"""
Single source of truth for card typography, mapped onto real brand fonts.

Font *family*/*weight* per grade band come from the original Student
Edition type spec (see the font-table screenshot the design team
provided) -- one deliberate deviation from that spec: grades 2-5 header
uses Benton Sans Bold rather than "Amplify Bold", since no Amplify Bold
file was supplied and Benton Sans Bold was given as its replacement.

Size, however, is uniform across every grade: 52pt header / 20pt body,
per the updated card template (2026-07) -- this superseded the font-table
screenshot's per-grade sizes (33/30pt header, 20/18/16/14pt body).

Font files live in templates/fonts/ (see templates/fonts.css for the
@font-face declarations).

Note the "Book" weight below is 350, not 400 -- that's Benton Sans Book's
actual embedded OS/2 weight class, not a typo.
"""

HEADER_SIZE_PT = 52
HEADER_LINE_PT = 62.4  # 1.2x, same ratio the font-table spec used throughout
TEXT_SIZE_PT = 20
TEXT_LINE_PT = 24  # 1.2x

# Font family/weight per grade band ("Header" row in the spec / "Text" row).
GRADE_FONTS = {
    "K": {
        "header": {"family": "Castledown Pro", "weight": 900},
        "text": {"family": "Castledown Pro", "weight": 400},
    },
    "1": {
        "header": {"family": "Castledown Pro", "weight": 900},
        "text": {"family": "Castledown Pro", "weight": 400},
    },
    "2": {
        "header": {"family": "Benton Sans", "weight": 700},
        "text": {"family": "Benton Sans", "weight": 350},
    },
    "3": {
        "header": {"family": "Benton Sans", "weight": 700},
        "text": {"family": "Benton Sans", "weight": 350},
    },
    "4": {
        "header": {"family": "Benton Sans", "weight": 700},
        "text": {"family": "Benton Sans", "weight": 350},
    },
    "5": {
        "header": {"family": "Benton Sans", "weight": 700},
        "text": {"family": "Benton Sans", "weight": 350},
    },
}


def grade_css():
    lines = []
    for grade, roles in GRADE_FONTS.items():
        h, t = roles["header"], roles["text"]
        lines.append(f"""
.card.grade-{grade} .card-header {{
  font-family: '{h["family"]}';
  font-weight: {h["weight"]};
  font-size: {HEADER_SIZE_PT}pt;
  line-height: {HEADER_LINE_PT}pt;
}}
.card.grade-{grade} .card-text {{
  font-family: '{t["family"]}';
  font-weight: {t["weight"]};
  font-size: {TEXT_SIZE_PT}pt;
  line-height: {TEXT_LINE_PT}pt;
}}
.card.grade-{grade} .card-text strong {{
  font-weight: {h["weight"]};
}}""")
    return "\n".join(lines)
