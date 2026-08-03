"""
Bold key terms within a card's definition text, e.g. "a type of rectangle
with **4 equal sides** and **4 square corners**" -> the two phrases render
in bold on the printed card, matching the updated card template.

Curated separately from data/vocab.json (data/bolded_definitions/grade_<G>.json,
one flat {word: "...**bolded**..." markdown} dict per grade) rather than
stored inline on the vocab cards, for the same reason Spanish translations
live apart from unit_vocab.json: data/vocab.json gets fully rebuilt every
time the master spreadsheet is (re-)processed, so anything stored directly
on its cards would be silently wiped out the next upload. Looking bolding
up by grade+word at render time means re-uploading the spreadsheet doesn't
lose it.
"""
import json
import re
from functools import lru_cache
from html import escape
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BOLDED_DIR = REPO_ROOT / "data" / "bolded_definitions"
BOLDED_ES_DIR = REPO_ROOT / "data" / "bolded_definitions_es"

BOLD_MARKDOWN_RE = re.compile(r"\*\*(.+?)\*\*")


def markdown_bold_to_html(text):
    """Convert **bold** markdown into <strong> tags. Escapes everything
    else, so the result is always safe to render directly as HTML."""
    parts = []
    last = 0
    for m in BOLD_MARKDOWN_RE.finditer(text):
        parts.append(escape(text[last:m.start()]))
        parts.append(f"<strong>{escape(m.group(1))}</strong>")
        last = m.end()
    parts.append(escape(text[last:]))
    return "".join(parts)


@lru_cache(maxsize=None)
def _load_grade(grade):
    path = BOLDED_DIR / f"grade_{grade}.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def text_html_for(grade, word):
    """HTML (with <strong> tags) for this grade+word's curated bolded
    definition, or None if nothing's been curated for it yet -- callers
    should fall back to the plain definition text in that case."""
    bolded_markdown = _load_grade(grade).get(word)
    if not bolded_markdown:
        return None
    return markdown_bold_to_html(bolded_markdown)


@lru_cache(maxsize=None)
def _load_grade_es(grade):
    path = BOLDED_ES_DIR / f"grade_{grade}.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def spanish_text_html_for(grade, spanish_text):
    """HTML (with <strong> tags) for this grade's curated Spanish bolded
    definition matching spanish_text verbatim, or None if nothing's been
    curated for it (or it doesn't match any curated entry, e.g. a not-yet-
    reviewed unit-specific phrasing variant) -- callers should fall back to
    the plain Spanish text in that case.

    Keyed by the literal Spanish sentence rather than by word, unlike
    text_html_for(): a word placed in several units can have a genuinely
    different official Spanish phrasing per unit (see spanish_by_unit's
    note in build_unit_sheet.py), so each distinct sentence needs its own
    bolding rather than one markup per word."""
    if not spanish_text:
        return None
    bolded_markdown = _load_grade_es(grade).get(spanish_text)
    if not bolded_markdown:
        return None
    return markdown_bold_to_html(bolded_markdown)
