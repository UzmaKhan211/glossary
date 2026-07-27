"""
Single source of truth for the Student Edition type spec (see the font-table
screenshot the design team provided) mapped onto real brand fonts.
Sizes/line-heights are copied exactly from the design spec.

Font files live in templates/fonts/ (see templates/fonts.css for the
@font-face declarations). One deliberate deviation from the font-table
screenshot: grades 2-5 header uses Benton Sans Bold rather than "Amplify
Bold" -- no Amplify Bold file was supplied, and Benton Sans Bold was given
as its replacement.

Note the "Book" weight below is 350, not 400 -- that's Benton Sans Book's
actual embedded OS/2 weight class, not a typo.
"""

# word header ("Header" row in the spec) / definition text ("Text" row)
GRADE_FONTS = {
    "K": {
        "header": {"family": "Castledown Pro", "weight": 900, "size_pt": 33, "line_pt": 39},
        "text": {"family": "Castledown Pro", "weight": 400, "size_pt": 20, "line_pt": 24},
    },
    "1": {
        "header": {"family": "Castledown Pro", "weight": 900, "size_pt": 33, "line_pt": 39.6},
        "text": {"family": "Castledown Pro", "weight": 400, "size_pt": 18, "line_pt": 21.6},
    },
    "2": {
        "header": {"family": "Benton Sans", "weight": 700, "size_pt": 30, "line_pt": 36},
        "text": {"family": "Benton Sans", "weight": 350, "size_pt": 16, "line_pt": 19.2},
    },
    "3": {
        "header": {"family": "Benton Sans", "weight": 700, "size_pt": 30, "line_pt": 36},
        "text": {"family": "Benton Sans", "weight": 350, "size_pt": 16, "line_pt": 19.2},
    },
    "4": {
        "header": {"family": "Benton Sans", "weight": 700, "size_pt": 30, "line_pt": 36},
        "text": {"family": "Benton Sans", "weight": 350, "size_pt": 14, "line_pt": 16.8},
    },
    "5": {
        "header": {"family": "Benton Sans", "weight": 700, "size_pt": 30, "line_pt": 36},
        "text": {"family": "Benton Sans", "weight": 350, "size_pt": 14, "line_pt": 16.8},
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
  font-size: {h["size_pt"]}pt;
  line-height: {h["line_pt"]}pt;
}}
.card.grade-{grade} .card-text {{
  font-family: '{t["family"]}';
  font-weight: {t["weight"]};
  font-size: {t["size_pt"]}pt;
  line-height: {t["line_pt"]}pt;
}}""")
    return "\n".join(lines)
