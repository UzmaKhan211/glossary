# Word Wall vocab card generator

Turns the NA K-5 Math Glossary spreadsheet into print-ready Word Wall vocab
cards (2 per Letter-landscape page, "cut here" divider between them),
matching the approved prototype design in `Letter_79.pdf`: rounded card
border, word header, optional definition + image, Amplify footer bar.

## Pipeline

```
glossary.xlsx  --extract_data.py-->  data/vocab.json + assets/images/  --generate.py-->  output/*.pdf
```

1. **`scripts/extract_data.py`** reads the raw spreadsheet (an editorial
   proofing sheet, not a clean table) and produces a clean, per-grade
   `data/vocab.json` plus `data/qa_report.md`, a line-by-line log of exactly
   which column supplied the word/definition/image for every card, so the
   judgment calls below can be spot-checked.
2. **`scripts/generate.py`** renders `data/vocab.json` through the HTML/CSS
   template in `templates/` using headless Chromium (Playwright) and prints
   to PDF.

## Setup

```
pip install -r requirements.txt
python3 scripts/fetch_fonts.py
```

Chromium must be available to Playwright. If `playwright install` isn't an
option in your environment, `generate.py` will auto-detect a Chromium build
under `$PLAYWRIGHT_BROWSERS_PATH` if that env var is set; otherwise it uses
Playwright's normal managed browser.

`assets/images/`, `templates/fonts/`, and `templates/fonts.css` are
gitignored on purpose -- they're regenerable build artifacts (extracted from
the sheet / downloaded from Google Fonts), not source, so they don't bloat
the repo or any handoff of it. `fetch_fonts.py` recreates the font files;
`extract_data.py` (next section) recreates the images.

## Regenerating the data from the spreadsheet

Download the sheet (File > Download > Microsoft Excel) to
`data/source/glossary.xlsx` (gitignored — the sheet itself isn't checked in),
then:

```
python3 scripts/extract_data.py data/source/glossary.xlsx
```

This overwrites `data/vocab.json`, `data/qa_report.md`, and `assets/images/`.

### Extraction rules (why a card looks the way it does)

The spreadsheet has a 4-column block per grade (`Current`, `Image`,
`Feedback`, `New Entry`) plus feedback/notes columns, and go-by images are
floating drawings anchored near a cell, not cell values — so "the definition"
and "the image" both take a little judgment:

- **Definition text**: prefer `New Entry` (the proofread revision); fall back
  to `Current` when a grade has no New Entry yet. Leading "word: " restatements
  and reviewer asides (`**...**`, `***...***`) are stripped, and the first
  letter is lowercased / trailing period dropped to match the prototype's
  fragment style ("a type of rectangle with 4 equal sides...").
- **Image**: a row can have a go-by image anchored in any of the 4 columns,
  not just `Image` — editors sometimes stage a replacement in `Feedback`, or
  (for image-only entries: all of K, plus shape/comparative words in grades
  1-2 like *cone*, *taller*, *fewer*) paste the image directly into
  `Current`/`New Entry` since those rows don't need text. Priority, newest
  first: `Feedback` > `Image` > `New Entry` > `Current`.
- **Word**: derived from column A (`"a foot/ feet"` -> `"foot"`), then column D
  ("Overall Feedback") is applied on top when it's an actual word edit rather
  than an editorial note. Every one of the 34 non-empty D values in the sheet
  was hand-classified into one of three buckets (`apply_word_feedback` in
  `scripts/extract_data.py`): (1) states the replacement word/phrase directly —
  a bare word ("centimeter"), an `entry: X` / `entry word: X` / `change entry
  to X` prefix — used verbatim; (2) a sentence instructing an edit to make
  ("remove parentheses around sides") — parsed and applied to column A's word;
  (3) a grade-placement note ("add in 5th", "adding this in to 2nd", "remove
  from 2nd") — not a word edit at all, ignored. No manual per-row overrides
  remain; the whole 34-row set is handled by these three general rules.

Every one of those decisions is logged per-card in `data/qa_report.md` —
check it after any re-extraction, especially if the sheet's column layout
changes.

## Unit-wise vocab spreadsheet

`data/vocab.json` is organized by grade only — the big feedback spreadsheet
has no unit column. But word walls get printed/posted unit by unit as a
class works through the curriculum, so `scripts/build_unit_sheet.py` cross-
references every vocab word against the official per-unit bilingual glossary
PDFs (named like `KG-Unit3.pdf` / `Grade5-Unit6.pdf`) to figure out which
unit each word belongs to, and produces a clean spreadsheet grouped by
Grade > Unit > Word with images embedded:

```
python3 scripts/build_unit_sheet.py
```

writes `output/unit_vocab_sheet.xlsx` (one tab per grade, plus an
"Unmapped" tab), `data/unit_vocab.json` (same data as JSON), and
`data/unit_sheet_qa.md`.

All 6 grades are now covered (K, 1, 2, 3, 4: 7 units each except Grade 2,
which has 8; Grade 5: 7 units) — `data/unit_glossary_raw/<grade>/unit<N>.txt`
holds the plain-text dump of each unit's PDF (there's no API to re-fetch
these automatically; they were pulled from the provided Drive folders and
pasted in). To add a grade that gets new/updated unit PDFs later, replace
its `unitN.txt` files and rerun the script — nothing else changes. Current
mapping rate: K 61/61, Grade 1 48/50, Grade 2 74/82, Grade 3 75/89,
Grade 4 62/67, Grade 5 61/69 — the rest are on the "Unmapped" tab.

A word can legitimately show up in more than one unit (curriculum glossaries
are cumulative — a term introduced in an early unit gets repeated in later
units' glossaries). The script assigns each word to the **earliest** unit it
appears in and notes every later reappearance in `unit_sheet_qa.md`. Words
that never turn up in any provided unit glossary at all land on the
"Unmapped" tab rather than being silently dropped, most likely because they
belong to a unit past what was provided. Matching tolerates simple plural
(`shape`/`shapes`) and hyphen/parenthesis (`x-coordinate`/`x coordinate`,
`parallel (lines)`/`parallel lines`) differences between how a word is
written in the spreadsheet versus the unit PDF; two forms that were genuine
rewordings rather than formatting differences (K's "less than"/"more than"
-> "less"/"more") are handled with a small, documented alias table
(`WORD_ALIASES` in the script) rather than a fuzzier heuristic.

**Fixed: false-positive unit placements.** The matcher is a plain substring
search across each unit's flattened text, so on its own it can't tell "this
word is being defined here" apart from "this word happens to appear inside
a *different* word's definition" -- e.g. Grade 5 Unit 4 never defines
"rectangle," it defines *rectangular prism* ("a solid figure with 6 faces
that are all rectangl**es**"), and the plural-tolerance rule matched that
incidental "rectangles" as if it were rectangle's own entry. A related
failure mode showed up in grades 2-4: a word that's genuinely just the tail
of a longer, different compound term ("foot" inside "square foot",
"denominator" inside "common denominator") gets credited with a match that
isn't really about it at all.

Every word flagged as appearing in 2+ units (plus every word that could
plausibly hit this bug) was hand-checked against the actual unit text --
36 corrected (grade, word) pairs across all 6 grades are in
`VERIFIED_UNIT_CORRECTIONS` in `scripts/build_unit_sheet.py`, each with a
comment citing exactly what the false match was. Three words came out with
**no** genuine standalone entry in any provided unit at all (Grade 2
`length`, Grade 3 `foot`, Grade 3 `sum` -- all previously mis-filed under a
unit that only used the word incidentally) and now correctly land on the
Unmapped tab instead. `unit_sheet_qa.md` tags every corrected entry with
`[hand-corrected -- see VERIFIED_UNIT_CORRECTIONS]` so the fix is traceable
back to its reasoning, not just a silent number change.

This spreadsheet is a standalone deliverable for review right now — the
card generator (`generate.py`) still reads `data/vocab.json` directly and
doesn't yet group/paginate by unit. Wiring unit-ordered generation into
`generate.py` would be a small follow-up once the unit data itself looks
right.

## Generating cards

```
python3 scripts/generate.py --grade 2 --out output/grade2.pdf
python3 scripts/generate.py --grade K 1 2 3 4 5 --out output/all_grades.pdf
python3 scripts/generate.py --grade 5 --limit 6 --out output/grade5_sample.pdf
```

Each grade's cards render with the font-table sizes from the Student Edition
spec, auto-fit for length (see below), and skip whichever of definition/image
a given word doesn't have — K is always word + image (no text row); grades
1-5 can be word+text, word+image, or word+text+image, decided per-card by
what `vocab.json` has.

### Handling variable text length

Definitions range from a few words to multi-sentence. The template gives the
image area first claim on leftover space (`flex: 1`, shrinks to 0 before
anything else moves) so short definitions just leave more room for the image.
If a definition is long enough that the *word + text + footer* alone would
overflow the fixed card height, a small script (`AUTOFIT_JS` in
`generate.py`) runs in the browser after layout and shrinks the definition
font-size in 0.5pt steps (down to 62% of its nominal size before giving up)
until it fits — so a card is never taller than its neighbor, and text never
shrinks unless it actually needs to.

## Fonts

`scripts/grade_fonts.py` maps every grade band to a real brand font at the
*exact* sizes/line heights from the spreadsheet's font-table spec:

| Band | Header | Text |
|---|---|---|
| K, 1 | Castledown Pro Heavy (900) | Castledown Pro Regular (400) |
| 2-5 | Benton Sans Bold (700) | Benton Sans Book (350) |

One deliberate deviation from the font-table screenshot: grades 2-5 use
**Benton Sans Bold** for the header, not "Amplify Bold" — no Amplify Bold
file was supplied, and Benton Sans Bold was given as its replacement. The
footer/cut-here chrome (not part of the font-table spec) also uses Benton
Sans, just to avoid pulling in a fifth font family for a few lines of print.

Benton Sans Book's `font-weight: 350` isn't a typo — that's its actual
embedded OS/2 weight class, not the standard 400.

**These are licensed Amplify fonts, not redistributable ones.** They're
committed here (`templates/fonts/*.otf`, `templates/fonts.css`) only because
this repo is **private** — if it's ever made public again, remove those two
paths from git first (re-add them to `.gitignore`; see the note there) rather
than relying on someone remembering to strip them by hand.
`scripts/fetch_fonts.py` remains as a fallback that downloads close free
substitutes (Poppins/Source Sans 3/Baloo 2/Nunito) for anyone working from a
clone who doesn't have rights to the licensed files.

## Design fidelity notes

Card size, margins, border radius/color, footer bar, and the cut-here divider
were measured directly off `Letter_79.pdf` (rendered at 200dpi and sampled
pixel-by-pixel) rather than guessed, so a generated page should overlay the
prototype almost exactly. One open call: the prototype's card border is a
sampled green (`#7cb342`); every grade currently uses that same color. If you
want borders color-coded by grade band instead (matching the K/1/2-3/4-5
chips in the font-table screenshot), that's a one-line change in
`templates/style.css`.

The footer's trailing print/SKU code (`2544700` in the prototype) is exposed
as `--print-code` and left blank by default since it's specific to that one
proof; pass `--print-code XXXXXXX` if you have a real one to print.
