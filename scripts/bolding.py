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
