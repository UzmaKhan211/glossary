#!/usr/bin/env python3
"""
Build a unit-organized vocab spreadsheet from data/vocab.json (the output of
extract_data.py), using the official per-unit bilingual glossary PDFs as the
source of truth for which unit each word belongs to.

Why this exists: data/vocab.json is organized by grade only. The word wall
is meant to be printed/posted unit by unit as a class works through the
curriculum, so cards need a unit number, not just a grade. The big feedback
spreadsheet has no unit column at all -- the unit-level glossary PDFs
(named like "KG-Unit3.pdf" / "Grade5-Unit6.pdf") are the only place that
information exists, so we cross-reference each vocab word against every
unit glossary's text to find which unit(s) introduce/reference it.

Input: data/unit_glossary_raw/<grade>/unit<N>.txt -- plain-text dumps of the
unit glossary PDFs (see README.md for how these were produced; there's no
API to regenerate them automatically, they were pasted in from Drive).

Output:
  data/unit_vocab.json   -- grade -> word -> {text, image, primary_unit, all_units}
  data/unit_sheet_qa.md  -- every word with no unit match, and every word that
                            showed up in more than one unit (common: cumulative
                            glossaries repeat earlier terms in later units)
  output/unit_vocab_sheet.xlsx -- the actual spreadsheet, grouped by
                            Grade > Unit > Word, images embedded, with an
                            "Unmapped" tab for words no unit text matched
"""
import json
import re
from pathlib import Path

import openpyxl
from openpyxl.drawing.image import Image as XLImage
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from PIL import Image as PILImage

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
RAW_DIR = DATA_DIR / "unit_glossary_raw"
SPANISH_DIR = DATA_DIR / "spanish_translations"
IMAGES_DIR = REPO_ROOT / "assets" / "images"
OUTPUT_DIR = REPO_ROOT / "output"

UNIT_FILE_RE = re.compile(r"unit(\d+)\.txt$", re.IGNORECASE)

# Word forms in the glossary spreadsheet that don't literally appear in the
# unit PDFs but clearly refer to the same taught term (confirmed by hand
# against the raw unit text -- not a guess): K's "less than" is just labeled
# "less" in the unit glossaries.
WORD_ALIASES = {
    "less than": "less",
    "more than": "more",
}

# word_in_text() is a plain substring search over each unit's flattened text,
# so it can't distinguish "this word is being defined here" from "this word
# happens to appear inside a *different* word's definition" -- e.g. Grade 5
# Unit 4 never defines "rectangle", it defines "rectangular prism" ("a solid
# figure with 6 faces that are all rectangl[e]s"), and the plural-tolerance
# rule matches that incidental "rectangles" as if it were rectangle's own
# entry. A second, related failure mode showed up in grades 2-4: a word that
# is genuinely just the tail of a *different*, longer compound term ("foot"
# inside "square foot", "denominator" inside "common denominator") gets
# credited with a match that isn't really about it at all.
#
# Every (grade, word) below was hand-verified against the actual unit text in
# data/unit_glossary_raw/ -- read the surrounding sentence, decided whether it
# was that word's own "word <definition>" entry or just incidental use inside
# someone else's definition, and rebuilt the true unit list from scratch. This
# REPLACES word_in_text()'s automatic result for these entries (rather than
# only nudging the primary unit) so the "also referenced in" list is accurate
# too, not just the primary placement. An empty list means the word never has
# a real standalone entry in any of the provided units, despite an incidental
# text match -- it should land on the Unmapped tab, not get a fake unit.
VERIFIED_UNIT_CORRECTIONS = {
    # Grade 1
    ("1", "more"): [2, 4, 6],  # unit 1 only had "...or MORE numbers..." inside sum's definition
    ("1", "one"): [3, 4, 5, 6],  # units 1-2 only had "...subtract ONE number...", "addend ONE OF the..."
    ("1", "side"): [7],  # unit 2 only had "...on each SIDE of the equal sign..." inside equation's definition
    ("1", "subtract"): [2, 6],  # unit 1 only had "...when you SUBTRACT one number..." inside difference's definition
    ("1", "sum"): [1, 2, 6],  # unit 4's only "sum" hit was incidental, inside addend's definition

    # Grade 2
    ("2", "foot"): [3],  # unit 6's only hit was "...12 inches is equal to 1 FOOT" inside inch's definition
    ("2", "meter"): [3],  # unit 6's only hit was "...is equal to 1 METER" inside centimeter's definition
    ("2", "digit"): [7],  # unit 5's hits were both incidental (expanded form's/standard form's definitions)
    ("2", "equal"): [8],  # units 2,3,6,7 only ever use "equal"/"equally" inside other words' definitions
    ("2", "expression"): [7, 8],  # units 5,6 only had "an EXPRESSION that means..." inside half past/quarter past
    ("2", "length"): [],  # no unit has a real "length" entry; all 3 hits were incidental ("unit of length")
    ("2", "number line"): [4],  # unit 3's hit was inside line plot's definition ("above a number line")
    ("2", "one"): [7],  # units 5,8 only had incidental "...100 ONES", "addend ONE OF the numbers..."
    ("2", "point"): [4],  # unit 6's hits were incidental, inside hour hand's/minute hand's definitions
    ("2", "rectangle"): [6],  # unit 1's hits were incidental, inside bar graph's/tape diagram's definitions
    ("2", "sum"): [7, 8],  # unit 2's only hit was inside Commutative Property of Addition's definition
    ("2", "ten"): [7],  # unit 5's only hit was "...group of 10 TENS..." inside hundred's definition

    # Grade 3
    ("3", "foot"): [],  # no real "foot" entry; unit 2 only has "square foot" (different term), unit 6 incidental
    ("3", "inch"): [6],  # unit 2 only has "square inch" (different term), no standalone "inch" entry
    ("3", "equation"): [4],  # unit 2's only hit was inside parentheses' definition ("expressions or equations")
    ("3", "expression"): [4],  # unit 2's only hit was inside parentheses' definition ("used in expressions")
    ("3", "square"): [7],  # units 2,4 only have "square centimeter/foot/inch" (different terms) + "square units"
    ("3", "sum"): [],  # no real "sum" entry; unit 4 incidental (Distributive Property), unit 6 incidental (add)
    ("3", "two-dimensional"): [7],  # units 2,4 only use it as a descriptor inside area's definition

    # Grade 4
    ("4", "denominator"): [3],  # unit 2 only has "common denominator"/"common numerator" (different terms)
    ("4", "factor pair"): [4, 5],  # units 1,3 only had it inside composite number's/prime number's definitions
    ("4", "length"): [6],  # units 5,7 only had "unit of length", "equal-length sides" (descriptive, not the entry)
    ("4", "numerator"): [3],  # unit 2 only has "common numerator" (different term), no standalone "numerator"
    ("4", "point"): [7],  # unit 4 only has "decimal point" (different term), no standalone "point" entry

    # Grade 5 (originally reported, now fixed)
    ("5", "rectangle"): [7],  # unit 4 only defines "rectangular prism"; "rectangles" there is incidental
    ("5", "base"): [6],  # unit 5's only hit was "base-ten place value" inside hundredths'/tenth's definitions
    ("5", "product"): [3, 4, 5, 6],  # units 1,2 only had "product" inside Associative Property's/factor's definitions
    ("5", "sum"): [4, 5, 6],  # units 2,3 only had "sum" inside Distributive Property's definition
    ("5", "equation"): [3, 5],  # unit 4's hit was incidental, inside partial quotients' definition
    ("5", "expression"): [2, 3, 4, 5],  # unit 6's hits were incidental, inside exponent's definition
    ("5", "volume"): [1, 4],  # unit 6's hits were incidental, inside cup's/gallon's "liquid volume unit" phrasing
}


def normalize(text):
    text = text.lower()
    text = text.replace("-", " ").replace("(", " ").replace(")", " ")
    return re.sub(r"\s+", " ", text).strip()


def word_in_text(word, normalized_text):
    candidates = {word, WORD_ALIASES.get(word, word)}
    for candidate in candidates:
        base = normalize(candidate)
        # tolerate a simple plural mismatch either direction (unit glossaries
        # sometimes list "solid shapes" where the spreadsheet says "solid shape")
        for variant in (base, base + "s", base + "es"):
            pattern = r"(?<!\w)" + re.escape(variant) + r"(?!\w)"
            if re.search(pattern, normalized_text):
                return True
        if base.endswith("s") and re.search(r"(?<!\w)" + re.escape(base[:-1]) + r"(?!\w)", normalized_text):
            return True
    return False


def load_unit_texts(grade_dir):
    """Return {unit_number: normalized_text} for one grade's raw-text folder."""
    units = {}
    if not grade_dir.is_dir():
        return units
    for path in grade_dir.glob("unit*.txt"):
        m = UNIT_FILE_RE.search(path.name)
        if not m:
            continue
        units[int(m.group(1))] = normalize(path.read_text())
    return units


def map_words_to_units(words, unit_texts):
    """words: list of word strings. unit_texts: {unit_num: normalized_text}.
    Returns {word: sorted_list_of_unit_numbers_it_appears_in}."""
    result = {}
    for word in words:
        matches = sorted(u for u, text in unit_texts.items() if word_in_text(word, text))
        result[word] = matches
    return result


def load_spanish_translations():
    """Return {grade: {(unit_str, word): entry}} from data/spanish_translations/grade_<G>.json.

    Those files were produced by carefully reading data/unit_glossary_original/ (the
    byte-faithful re-fetch of the official bilingual glossary PDFs, NOT the reflowed
    unit_glossary_raw/ cache used for unit-mapping) and copying the Spanish word and
    definition exactly as printed -- see README.md for the extraction method.
    """
    lookup = {}
    for path in SPANISH_DIR.glob("grade_*.json"):
        grade = path.stem.removeprefix("grade_")
        data = json.loads(path.read_text())
        lookup[grade] = {(unit, entry["word"]): entry for unit, entries in data.items() for entry in entries}
    return lookup


def build_unit_vocab():
    vocab = json.loads((DATA_DIR / "vocab.json").read_text())
    spanish_lookup = load_spanish_translations()
    unit_vocab = {}
    qa_lines = ["# Unit-mapping QA report\n"]

    for grade, cards in vocab.items():
        grade_dir_name = "K" if grade == "K" else grade
        unit_texts = load_unit_texts(RAW_DIR / grade_dir_name)
        if not unit_texts:
            qa_lines.append(f"\n## Grade {grade}: no unit glossary PDFs provided yet -- skipped.\n")
            continue

        words = [c["word"] for c in cards]
        word_to_units = map_words_to_units(words, unit_texts)
        grade_spanish = spanish_lookup.get(grade, {})

        qa_lines.append(f"\n## Grade {grade} (units available: {sorted(unit_texts)})\n")
        grade_entries = []
        for card in cards:
            correction_key = (grade, card["word"])
            corrected = correction_key in VERIFIED_UNIT_CORRECTIONS
            units_found = VERIFIED_UNIT_CORRECTIONS[correction_key] if corrected else word_to_units[card["word"]]
            primary_unit = units_found[0] if units_found else None
            spanish = grade_spanish.get((str(primary_unit), card["word"])) if primary_unit else None
            entry = {
                "word": card["word"],
                "text": card.get("text") or "",
                "image": card.get("image"),
                "primary_unit": primary_unit,
                "all_units": units_found,
                "spanish_word": (spanish or {}).get("spanish_word") or "",
                "spanish_text": (spanish or {}).get("spanish_definition") or "",
            }
            grade_entries.append(entry)
            tag = " [hand-corrected -- see VERIFIED_UNIT_CORRECTIONS]" if corrected else ""
            if not units_found:
                qa_lines.append(f"- UNMAPPED: '{card['word']}' -- not found in any provided unit glossary{tag}")
            elif len(units_found) > 1:
                qa_lines.append(
                    f"- '{card['word']}' appears in units {units_found} -- filed under unit {primary_unit} "
                    f"(earliest), also referenced later{tag}"
                )
            if primary_unit and not entry["spanish_word"]:
                qa_lines.append(f"- '{card['word']}' (unit {primary_unit}): no Spanish translation found -- left blank")
            elif spanish and spanish.get("confidence") in ("low", "unmapped"):
                qa_lines.append(
                    f"- '{card['word']}' (unit {primary_unit}): Spanish translation is low-confidence "
                    f"-- {spanish.get('note', 'see data/spanish_translations/')}"
                )
            elif corrected:
                qa_lines.append(f"- '{card['word']}' filed under unit {primary_unit}{tag}")
        unit_vocab[grade] = grade_entries

    (DATA_DIR / "unit_vocab.json").write_text(json.dumps(unit_vocab, indent=2))
    (DATA_DIR / "unit_sheet_qa.md").write_text("\n".join(qa_lines) + "\n")
    return unit_vocab


HEADER_FILL = PatternFill("solid", fgColor="F27221")
HEADER_FONT = Font(color="FFFFFF", bold=True)
UNIT_FILL = PatternFill("solid", fgColor="FDE9DD")
IMG_COL_WIDTH_PX = 110
ROW_HEIGHT_PX = 90


def add_sheet_header(ws):
    headers = ["Grade", "Unit", "Word", "Definition", "Spanish Word", "Spanish Definition", "Image"]
    for col, title in enumerate(headers, start=1):
        cell = ws.cell(row=1, column=col, value=title)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
    ws.column_dimensions["A"].width = 8
    ws.column_dimensions["B"].width = 8
    ws.column_dimensions["C"].width = 28
    ws.column_dimensions["D"].width = 70
    ws.column_dimensions["E"].width = 28
    ws.column_dimensions["F"].width = 70
    ws.column_dimensions["G"].width = IMG_COL_WIDTH_PX / 7


def write_image(ws, row, col, image_rel_path):
    if not image_rel_path:
        return
    img_path = IMAGES_DIR / image_rel_path
    if not img_path.exists():
        return
    with PILImage.open(img_path) as im:
        w, h = im.size
    scale = min(IMG_COL_WIDTH_PX / w, ROW_HEIGHT_PX / h, 1.0)
    xl_img = XLImage(str(img_path))
    xl_img.width, xl_img.height = w * scale, h * scale
    ws.add_image(xl_img, f"{get_column_letter(col)}{row}")


def build_workbook(unit_vocab):
    wb = openpyxl.Workbook()
    wb.remove(wb.active)

    unmapped_rows = []

    for grade in ["K", "1", "2", "3", "4", "5"]:
        entries = unit_vocab.get(grade)
        if not entries:
            continue
        ws = wb.create_sheet(title=f"Grade {grade}")
        add_sheet_header(ws)

        mapped = [e for e in entries if e["primary_unit"] is not None]
        mapped.sort(key=lambda e: (e["primary_unit"], e["word"].lower()))

        row = 2
        current_unit = None
        for entry in mapped:
            if entry["primary_unit"] != current_unit:
                current_unit = entry["primary_unit"]
            ws.row_dimensions[row].height = ROW_HEIGHT_PX * 0.75
            ws.cell(row=row, column=1, value=grade)
            unit_cell = ws.cell(row=row, column=2, value=current_unit)
            unit_cell.fill = UNIT_FILL
            ws.cell(row=row, column=3, value=entry["word"]).alignment = Alignment(vertical="top", wrap_text=True)
            ws.cell(row=row, column=4, value=entry["text"]).alignment = Alignment(vertical="top", wrap_text=True)
            ws.cell(row=row, column=5, value=entry["spanish_word"]).alignment = Alignment(vertical="top", wrap_text=True)
            ws.cell(row=row, column=6, value=entry["spanish_text"]).alignment = Alignment(vertical="top", wrap_text=True)
            write_image(ws, row, 7, entry["image"])
            row += 1

        for entry in entries:
            if entry["primary_unit"] is None:
                unmapped_rows.append((grade, entry))

    if unmapped_rows:
        ws = wb.create_sheet(title="Unmapped")
        headers = ["Grade", "Word", "Definition", "Image"]
        for col, title in enumerate(headers, start=1):
            cell = ws.cell(row=1, column=col, value=title)
            cell.fill = HEADER_FILL
            cell.font = HEADER_FONT
        ws.column_dimensions["A"].width = 8
        ws.column_dimensions["B"].width = 28
        ws.column_dimensions["C"].width = 70
        ws.column_dimensions["D"].width = IMG_COL_WIDTH_PX / 7
        row = 2
        for grade, entry in unmapped_rows:
            ws.row_dimensions[row].height = ROW_HEIGHT_PX * 0.75
            ws.cell(row=row, column=1, value=grade)
            ws.cell(row=row, column=2, value=entry["word"]).alignment = Alignment(vertical="top", wrap_text=True)
            ws.cell(row=row, column=3, value=entry["text"]).alignment = Alignment(vertical="top", wrap_text=True)
            write_image(ws, row, 4, entry["image"])
            row += 1

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / "unit_vocab_sheet.xlsx"
    wb.save(out_path)
    return out_path


def main():
    unit_vocab = build_unit_vocab()
    out_path = build_workbook(unit_vocab)
    for grade, entries in unit_vocab.items():
        mapped = sum(1 for e in entries if e["primary_unit"] is not None)
        spanish = sum(1 for e in entries if e["primary_unit"] is not None and e["spanish_word"])
        print(f"grade {grade}: {mapped}/{len(entries)} words mapped to a unit, {spanish}/{mapped} have a Spanish translation")
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
