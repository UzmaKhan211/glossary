"""
Glue between the existing command-line scripts (scripts/extract_data.py,
scripts/pdf_glossary_parser.py, scripts/generate.py) and the Flask app in
app.py. Nothing in here is Flask-specific -- app.py just calls these
functions and renders their results.

Data lives in the same repo-relative paths the CLI scripts already use
(data/vocab.json, data/unit_vocab.json, output/*.pdf) so the web interface
is a front end for the real pipeline, not a separate copy of it. The only
new persistent state is the uploaded PDFs themselves and their parsed
cache, under data/unit_pdfs/ and data/unit_glossary_parsed/.
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import extract_data  # noqa: E402
from pdf_glossary_parser import GlossaryEntry, parse_unit_pdf  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
OUTPUT_DIR = REPO_ROOT / "output"
UNIT_PDFS_DIR = DATA_DIR / "unit_pdfs"
UNIT_PARSED_DIR = DATA_DIR / "unit_glossary_parsed"
VOCAB_PATH = DATA_DIR / "vocab.json"
UNIT_VOCAB_PATH = DATA_DIR / "unit_vocab.json"

# The grades extract_data.py's fixed column layout currently understands.
# This ISN'T a hard cap on what the app can show -- known_grades() below
# also picks up whatever grades actually exist in data/vocab.json, so a
# grades 6-8 spreadsheet (once extract_data.py -- or a variant of it -- can
# read that sheet's own column layout) shows up here automatically without
# any other code change. Uploading that sheet through the *current*
# extractor won't work until its column layout is wired in, since
# extract_data.GRADE_COLS is specific to the K-5 sheet's fixed columns.
GRADES = ["K", "1", "2", "3", "4", "5"]
GRADE_LABELS = {"K": "Kindergarten", "1": "Grade 1", "2": "Grade 2", "3": "Grade 3", "4": "Grade 4", "5": "Grade 5"}


def label_for_grade(grade):
    return GRADE_LABELS.get(grade, "Kindergarten" if grade == "K" else f"Grade {grade}")


def known_grades():
    """Every grade with word data loaded, in a sensible display order (K-5
    first if present, then any other grade -- e.g. 6, 7, 8 -- numerically)."""
    vocab = load_vocab()
    grades = {g for g in (set(vocab) | set(GRADES)) if vocab.get(g)}
    ordered = [g for g in GRADES if g in grades]
    extra = sorted((g for g in grades if g not in GRADES), key=lambda g: (len(g), g))
    return ordered + extra


# Matches the grade+unit out of Amplify's own PDF filenames, e.g.
# "Grade5-Unit7.pdf", "KG-Unit3.pdf", "Grade 2 - Unit 4.pdf", "Grade7-Unit2.pdf".
FILENAME_RE = re.compile(r"(?:grade\s*(\d+)|k\s*g?)\D*unit\s*(\d+)", re.IGNORECASE)


def grade_and_unit_from_filename(filename):
    m = FILENAME_RE.search(filename)
    if not m:
        return None, None
    grade = m.group(1) if m.group(1) else "K"
    return grade, int(m.group(2))


def load_vocab():
    if VOCAB_PATH.exists():
        return json.loads(VOCAB_PATH.read_text())
    return {g: [] for g in GRADES}


def images_status(grade):
    """(expected, present) image-file counts for a grade's cards.

    data/vocab.json is committed to git and travels with a fresh clone, but
    the actual image files under assets/images/ are gitignored (regenerable,
    not source) -- so a fresh clone can show a full word list with an
    "image" path recorded on every card while none of those files actually
    exist on disk yet. That's silent otherwise: cards render fine minus the
    picture, no error. This lets the UI flag it explicitly instead, since
    the fix (re-upload the spreadsheet on this machine to re-extract the
    images) isn't something you'd otherwise think to do if the words
    already looked "loaded"."""
    images_dir = REPO_ROOT / "assets" / "images"
    cards = load_vocab().get(grade, [])
    expected = sum(1 for c in cards if c.get("image"))
    present = sum(1 for c in cards if c.get("image") and (images_dir / c["image"]).exists())
    return expected, present


def load_unit_vocab():
    if UNIT_VOCAB_PATH.exists():
        return json.loads(UNIT_VOCAB_PATH.read_text())
    return {}


def save_unit_vocab(unit_vocab):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    UNIT_VOCAB_PATH.write_text(json.dumps(unit_vocab, indent=2))


def process_master_spreadsheet(xlsx_path):
    """Run extract_data.extract_cards() (the same extraction the CLI uses)
    and merge the result into data/vocab.json. Returns {grade: card_count}.

    This only ever touches the grades extract_data.GRADE_COLS knows how to
    read from this specific spreadsheet's fixed column layout (currently
    K-5) -- any other grade already in data/vocab.json (e.g. 6-8, once a
    matching extractor for that sheet exists) is left untouched rather than
    wiped out, so uploading a second/different spreadsheet is additive."""
    cards_by_grade, _qa_lines = extract_data.extract_cards(xlsx_path)
    cards_by_grade = {g: cards_by_grade.get(g, []) for g in extract_data.GRADE_COLS}

    existing = load_vocab()
    existing.update(cards_by_grade)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    VOCAB_PATH.write_text(json.dumps(existing, indent=2))
    return {g: len(cards) for g, cards in cards_by_grade.items()}


def save_and_parse_unit_pdf(grade, unit, filename, pdf_bytes):
    """Save an uploaded unit PDF and parse it, caching the parsed entries as
    JSON (so re-matching later doesn't need the PDF re-parsed). Returns the
    parsed entry count and any parser warnings."""
    pdf_dir = UNIT_PDFS_DIR / grade
    pdf_dir.mkdir(parents=True, exist_ok=True)
    (pdf_dir / f"unit{unit}.pdf").write_bytes(pdf_bytes)

    parsed = parse_unit_pdf(pdf_bytes)
    parsed_dir = UNIT_PARSED_DIR / grade
    parsed_dir.mkdir(parents=True, exist_ok=True)
    (parsed_dir / f"unit{unit}.json").write_text(json.dumps({
        "source_filename": filename,
        "en": [{"word": e.word, "definition": e.definition} for e in parsed.en],
        "es": [{"word": e.word, "definition": e.definition} for e in parsed.es],
        "warnings": parsed.warnings,
    }, indent=2))
    return len(parsed.en), parsed.warnings


def load_parsed_units(grade):
    """Return {unit_number: {"en": [GlossaryEntry], "es": [GlossaryEntry]}}
    for every unit PDF already uploaded+parsed for a grade."""
    grade_dir = UNIT_PARSED_DIR / grade
    units = {}
    if not grade_dir.is_dir():
        return units
    for path in sorted(grade_dir.glob("unit*.json")):
        m = re.search(r"unit(\d+)\.json$", path.name)
        if not m:
            continue
        data = json.loads(path.read_text())
        units[int(m.group(1))] = {
            "en": [GlossaryEntry(**e) for e in data["en"]],
            "es": [GlossaryEntry(**e) for e in data["es"]],
        }
    return units


def normalize(text):
    text = text.lower().replace("-", " ").replace("(", " ").replace(")", " ")
    return re.sub(r"\s+", " ", text).strip()


def _headword_variants(word):
    base = normalize(word)
    variants = {base}
    if base.endswith("s"):
        variants.add(base[:-1])
    else:
        variants.add(base + "s")
        variants.add(base + "es")
    return variants


def match_grade(grade):
    """Match this grade's cleaned spreadsheet words against every unit PDF
    parsed so far, and write the result into data/unit_vocab.json under
    this grade's key. Returns the list of entries (same shape that gets
    saved) for immediate display."""
    vocab = load_vocab()
    cards = vocab.get(grade, [])
    units = load_parsed_units(grade)

    # unit -> {normalized headword: index into that unit's en/es lists}
    unit_index = {}
    for unit_num, parsed in units.items():
        index = {}
        for i, entry in enumerate(parsed["en"]):
            for variant in _headword_variants(entry.word):
                index.setdefault(variant, i)
        unit_index[unit_num] = index

    def spanish_for_unit(word, unit_num):
        """Look up this word's Spanish word/definition specifically from
        unit_num's own uploaded PDF, rather than assuming every unit a word
        recurs in shares one translation -- units can genuinely phrase the
        same word differently."""
        index = unit_index[unit_num]
        variant_hit = next(iter(_headword_variants(word) & set(index)), None)
        if variant_hit is None:
            return "", ""
        i = index[variant_hit]
        es_entries = units[unit_num]["es"]
        # If this unit's PDF had a mismatched English/Spanish entry count
        # (the parser flags this -- see save_and_parse_unit_pdf's warnings),
        # the position that lines up with the English headword may not
        # exist on the Spanish side at all. Leave the Spanish fields blank
        # rather than crash or grab the wrong word.
        if i >= len(es_entries):
            return "", ""
        return es_entries[i].word, es_entries[i].definition

    entries = []
    for card in cards:
        candidates = sorted(
            unit_num for unit_num, index in unit_index.items()
            if _headword_variants(card["word"]) & set(index)
        )
        primary_unit = candidates[0] if candidates else None
        spanish_word, spanish_text = "", ""
        spanish_by_unit = {}
        if primary_unit is not None:
            spanish_word, spanish_text = spanish_for_unit(card["word"], primary_unit)
            # A word appearing in several units (e.g. "above" reintroduced in
            # a later unit) can have distinct phrasing per unit -- record
            # each unit's own translation, not just the primary one, so
            # per-unit exports show the right words instead of reusing the
            # earliest unit's translation everywhere.
            for u in candidates:
                w, t = spanish_for_unit(card["word"], u)
                if w:
                    spanish_by_unit[str(u)] = {"word": w, "text": t}
        entries.append({
            "word": card["word"],
            "text": card.get("text") or "",
            "image": card.get("image"),
            "primary_unit": primary_unit,
            "all_units": candidates,
            "spanish_word": spanish_word,
            "spanish_text": spanish_text,
            "spanish_by_unit": spanish_by_unit,
        })

    unit_vocab = load_unit_vocab()
    unit_vocab[grade] = entries
    save_unit_vocab(unit_vocab)
    return entries


def uploaded_units_summary(grade):
    """{unit_number: entry_count} for whatever's been uploaded+parsed so far."""
    return {unit: len(parsed["en"]) for unit, parsed in load_parsed_units(grade).items()}


def _cards_for_grade(grade, language, unit=None):
    """Build the card dicts for a single grade (see render_card_pdf's
    docstring for the shape), optionally restricted to entries that belong
    to the given unit. A word appearing in several units (e.g. "above" is
    introduced in unit 3 and comes back in unit 7) matches every one of them
    -- entry["all_units"] is the hand-verified list of units the word really
    belongs in, not just the first one, so a card for it is produced for
    each of those units rather than only its earliest appearance. Shared by
    render_card_pdf (whole-grade decks, unit=None -- one card per word) and
    render_unit_pdfs (one PDF per unit)."""
    from bolding import spanish_text_html_for, text_html_for

    images_dir = REPO_ROOT / "assets" / "images"
    images_es_dir = REPO_ROOT / "assets" / "images_es"
    unit_vocab = load_unit_vocab()

    cards = []
    for entry in unit_vocab.get(grade, []):
        if unit is not None and unit not in (entry.get("all_units") or []):
            continue
        if language == "es":
            # A word placed in several units can have a genuinely different
            # official Spanish phrasing per unit (see spanish_by_unit's note
            # in build_unit_sheet.py's build_unit_vocab()) -- when rendering
            # a specific unit's PDF, prefer that unit's own translation over
            # the word's primary-unit one, falling back if this unit doesn't
            # have one on record.
            per_unit_es = (entry.get("spanish_by_unit") or {}).get(str(unit)) if unit is not None else None
            word = (per_unit_es or {}).get("word") or entry.get("spanish_word") or ""
            text = (per_unit_es or {}).get("text") or entry.get("spanish_text") or ""
            if not word:
                continue  # no Spanish translation available for this word -- skip rather than print blank
            text_html = spanish_text_html_for(grade, text)
            # Most images are wordless diagrams/shapes/numbers and are reused
            # as-is; only words whose image actually had English labels get a
            # Spanish-relabeled version under assets/images_es/, so check
            # there first and fall back to the plain English image.
            image_rel = entry.get("spanish_image") or entry.get("image")
            image_path = None
            if image_rel:
                candidate = images_es_dir / image_rel
                image_path = candidate if candidate.exists() else images_dir / image_rel
        else:
            word, text = entry["word"], entry.get("text") or ""
            text_html = text_html_for(grade, entry["word"])
            image_path = images_dir / entry["image"] if entry.get("image") else None
        image_uri = None
        if image_path and image_path.exists():
            image_uri = image_path.resolve().as_uri()
        cards.append({"grade": grade, "word": word, "text": text, "text_html": text_html,
                      "image_uri": image_uri, "_sort_word": entry["word"]})
    # Alphabetize by the ENGLISH word always, even in the Spanish deck --
    # Spanish cards follow the same order as their English counterparts
    # (e.g. if "data" sorts before "meter" in English, the Spanish deck
    # shows data's translation before meter's translation too, regardless of
    # what the Spanish words themselves start with) rather than being
    # re-sorted A-Z in Spanish. Not spreadsheet row order either -- so a
    # printed deck can be flipped through/found by this shared order rather
    # than whatever order the master spreadsheet happened to list words in.
    cards.sort(key=lambda c: c["_sort_word"].lower())
    for c in cards:
        del c["_sort_word"]
    return cards


def render_card_pdf(grades, language, out_path):
    """Render a standalone card deck PDF for the given grades, in English
    (language="en") or Spanish (language="es"). Reuses scripts/generate.py's
    render_pdf() (same template/CSS/autofit logic as the CLI generator) so
    there's exactly one place that knows how to turn cards into a PDF.
    Returns (card_count, shrink_report) -- see generate.AUTOFIT_JS for what
    a shrink-report entry looks like."""
    import generate

    cards = []
    for grade in grades:
        cards.extend(_cards_for_grade(grade, language))

    if not cards:
        return 0, []

    shrink_report = generate.render_pdf(cards, out_path, lang=language)
    return len(cards), shrink_report


def units_for_grade(grade):
    """Sorted list of unit numbers that have at least one word mapped to them
    for this grade (i.e. what render_unit_pdfs would produce a file for)."""
    unit_vocab = load_unit_vocab()
    units = set()
    for e in unit_vocab.get(grade, []):
        units.update(e.get("all_units") or [])
    return sorted(units)


def render_unit_pdfs(grades, language, out_dir):
    """Render one standalone PDF per (grade, unit) into out_dir, instead of a
    single combined deck -- for printing/posting a Word Wall unit by unit as
    a class works through the curriculum. Returns a list of
    {"grade", "unit", "path", "count", "shrink_report"}, one per unit that
    actually produced at least one card for this language (a unit with no
    Spanish translations yet simply doesn't appear, the same way it's
    skipped from the combined Spanish deck)."""
    import generate

    out_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for grade in grades:
        for unit in units_for_grade(grade):
            cards = _cards_for_grade(grade, language, unit=unit)
            if not cards:
                continue
            grade_slug = grade if grade == "K" else f"grade{grade}"
            out_path = out_dir / f"{grade_slug}_unit{unit}_{language}.pdf"
            shrink_report = generate.render_pdf(cards, out_path, lang=language)
            results.append({
                "grade": grade, "unit": unit, "path": out_path,
                "count": len(cards), "shrink_report": shrink_report,
            })
    return results
