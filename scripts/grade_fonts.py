"""
Single source of truth for the Student Edition type spec (see the font-table
screenshot the design team provided) mapped onto free substitute fonts.

Font names on the right are NOT the real Amplify/Castledown/Benton fonts --
we don't have license to those files. Sizes/line-heights are copied exactly
from the design spec. Swap in the real font files by:
  1. Dropping the .woff2/.ttf files into templates/fonts/
  2. Adding an @font-face block for them in templates/fonts.css
  3. Changing the "family" values below to the real family names
No template/layout code needs to change.
"""

# word header ("Header" row in the spec) / definition text ("Text" row)
GRADE_FONTS = {
    "K": {
        "header": {"family": "Baloo 2", "weight": 800, "size_pt": 33, "line_pt": 39},
        "text": {"family": "Nunito", "weight": 400, "size_pt": 20, "line_pt": 24},
    },
    "1": {
        "header": {"family": "Baloo 2", "weight": 800, "size_pt": 33, "line_pt": 39.6},
        "text": {"family": "Nunito", "weight": 400, "size_pt": 18, "line_pt": 21.6},
    },
    "2": {
        "header": {"family": "Poppins", "weight": 700, "size_pt": 30, "line_pt": 36},
        "text": {"family": "Source Sans 3", "weight": 400, "size_pt": 16, "line_pt": 19.2},
    },
    "3": {
        "header": {"family": "Poppins", "weight": 700, "size_pt": 30, "line_pt": 36},
        "text": {"family": "Source Sans 3", "weight": 400, "size_pt": 16, "line_pt": 19.2},
    },
    "4": {
        "header": {"family": "Poppins", "weight": 700, "size_pt": 30, "line_pt": 36},
        "text": {"family": "Source Sans 3", "weight": 400, "size_pt": 14, "line_pt": 16.8},
    },
    "5": {
        "header": {"family": "Poppins", "weight": 700, "size_pt": 30, "line_pt": 36},
        "text": {"family": "Source Sans 3", "weight": 400, "size_pt": 14, "line_pt": 16.8},
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
