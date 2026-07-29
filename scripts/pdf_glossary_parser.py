"""
Parse an official Amplify per-unit bilingual glossary PDF directly (using
real page coordinates and font weights) into a clean, ordered list of
(English word, English definition, Spanish word, Spanish definition) entries.

Why this exists: earlier work on this project extracted glossary text via a
Google Drive text-dump tool, and that dump's reading order sometimes
interleaved the English and Spanish columns line-by-line on pages with
diagrams, requiring careful hand reconstruction (see README.md's "Spanish
translations" section). Opening the actual PDF with PyMuPDF instead shows the
underlying document never has that problem -- every dictionary entry is its
own text block, with the headword in a distinct bold/heavy font and the
definition in the matching regular weight, and the English and Spanish
columns are simply two side-by-side groups of blocks on the page (English
blocks left of the column midpoint, Spanish blocks right of it). Reading
directly from the PDF's structure sidesteps the interleaving problem
entirely instead of working around it after the fact.

This module has no opinion about grades/units/spreadsheets -- it just turns
PDF bytes into entries. The webapp is responsible for matching those entries
against the master vocabulary list.
"""
import re
from dataclasses import dataclass, field

import fitz

# Running header/footer/column-label text that appears on every page and
# carries no vocabulary content.
BOILERPLATE_RE = re.compile(
    r"©\s*Amplify Education|is based on curricula from Illustrative Mathematics"
    r"|^(English|Español)$|Glossary/.*Glosario",
    re.IGNORECASE,
)
# The recurring page title ("Grade 5 Unit 7 Glossary/...") is set in this
# font family and no other text is, so filtering on it is a reliable
# belt-and-suspenders alongside the text-pattern match above.
TITLE_FONT_RE = re.compile(r"^Amplify-", re.IGNORECASE)
# The "English"/"Español" column-label spans are dropped individually (not
# just as a whole-block check) because on a couple of pages with very few
# entries, PyMuPDF merges the header row into the same block as the first
# real entry below it.
HEADER_LABEL_RE = re.compile(r"^(English|Español)$", re.IGNORECASE)
# Diagram leftovers (coordinate-grid axis numbers, clock/number-line labels):
# only digits, single letters, spaces and light punctuation, no real word.
DIAGRAM_NOISE_RE = re.compile(r"^[\dA-Z°\s.,()/–—-]+$")
BOLD_HINT_RE = re.compile(r"bold|heavy", re.IGNORECASE)
WHITESPACE_RE = re.compile(r"\s+")


@dataclass
class GlossaryEntry:
    word: str
    definition: str = ""


@dataclass
class ParsedGlossary:
    en: list = field(default_factory=list)
    es: list = field(default_factory=list)
    warnings: list = field(default_factory=list)


def _is_bold(font_name):
    return bool(BOLD_HINT_RE.search(font_name))


def _clean(text):
    return WHITESPACE_RE.sub(" ", text).strip()


def _page_column_split(page):
    """The x-coordinate that separates the English column from the Spanish
    one. The "Español" header label's own position isn't a reliable proxy
    for this -- it sits roughly centered over its column, well to the right
    of where that column's actual entry text (headwords, definitions)
    starts flush-left -- so the page's horizontal midpoint is used
    directly instead."""
    return page.rect.width / 2


def _drop_fused_section_letter(spans):
    """K-grade pages sometimes fuse the alphabetical section header ("A",
    "B", ...) onto the same text block as the real headword that follows it
    (e.g. one block containing "A" then "above"). Strip a lone leading
    single-uppercase-letter span so it isn't mistaken for the headword."""
    if len(spans) > 1 and len(spans[0]["text"].strip()) == 1 and spans[0]["text"].strip().isupper():
        return spans[1:]
    return spans


def _content_blocks(blocks, split_x):
    """Yield (y0, lang, spans) for every block side that's real vocabulary
    content -- boilerplate, section-letter headers, and diagram noise are
    dropped here. A block is split into its English-side and Spanish-side
    spans separately (not treated as one unit) because the "English /
    Español" column-label row is a single block with both languages'
    spans in it."""
    for block in blocks:
        if block.get("type") != 0:
            continue  # image, not text
        spans = [
            s
            for line in block.get("lines", [])
            for s in line["spans"]
            if not TITLE_FONT_RE.match(s["font"]) and not HEADER_LABEL_RE.match(s["text"].strip())
        ]
        if not spans:
            continue
        y0 = min(s["bbox"][1] for s in spans)
        for lang, side_spans in (
            ("en", [s for s in spans if s["bbox"][0] < split_x]),
            ("es", [s for s in spans if s["bbox"][0] >= split_x]),
        ):
            if not side_spans:
                continue
            text = _clean("".join(s["text"] for s in side_spans))
            if not text or BOILERPLATE_RE.search(text):
                continue
            if len(text) <= 2:
                continue  # lone section-letter header ("A", "B", ...)
            if DIAGRAM_NOISE_RE.match(text):
                continue
            yield y0, lang, _drop_fused_section_letter(side_spans)


def parse_unit_pdf(pdf_bytes):
    """Return a ParsedGlossary with .en and .es lists of GlossaryEntry, in
    the same reading order on both sides (so zip(result.en, result.es) pairs
    each English headword with its Spanish counterpart)."""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    result = ParsedGlossary()
    for page_index, page in enumerate(doc):
        blocks = page.get_text("dict")["blocks"]
        split_x = _page_column_split(page)
        content = sorted(_content_blocks(blocks, split_x), key=lambda b: b[0])
        for y0, lang, spans in content:
            entries = result.en if lang == "en" else result.es
            first = spans[0]
            if _is_bold(first["font"]):
                # The headword is usually one span, but a few (e.g.
                # "x-coordinate", "coordenada x") italicize the variable
                # letter as its own bold span glued to the rest -- so the
                # word is every *leading* bold span, not just the first.
                i = 0
                while i < len(spans) and _is_bold(spans[i]["font"]):
                    i += 1
                word = _clean("".join(s["text"] for s in spans[:i]))
                definition = _clean("".join(s["text"] for s in spans[i:]))
                entries.append(GlossaryEntry(word=word, definition=definition))
            elif entries:
                # Continuation fragment (a definition wrapped across a page
                # break). Skip it if it's just an echo of the headword
                # itself (K-grade repeats the word in a plain caption under
                # its icon, not part of any real definition) or a bare
                # single-word diagram caption (shape-diagram pages leave
                # stray "square"/"rectangles" picture labels as their own
                # blocks) -- real wrapped continuations in this corpus are
                # always multi-word phrases.
                extra = _clean("".join(s["text"] for s in spans))
                is_bare_word_caption = " " not in extra and extra.isalpha()
                if extra.lower() != entries[-1].word.lower() and not is_bare_word_caption:
                    entries[-1].definition = _clean(entries[-1].definition + " " + extra)
            else:
                result.warnings.append(
                    f"page {page_index + 1}: found a non-bold {lang} fragment before any "
                    f"headword ({spans[0]['text']!r}) -- dropped"
                )
    if len(result.en) != len(result.es):
        result.warnings.append(
            f"English/Spanish entry counts don't match ({len(result.en)} vs {len(result.es)}) "
            "-- pairing by position past this point may be off; review manually"
        )
    return result


def parse_unit_pdf_path(path):
    with open(path, "rb") as f:
        return parse_unit_pdf(f.read())
