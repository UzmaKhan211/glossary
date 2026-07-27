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
- **Word**: derived from column A (`"a foot/ feet"` -> `"foot"`). Column D
  ("Overall Feedback") is mostly free-form editorial notes ("add in 5th",
  "remove from 2nd"), *not* a reliable word source — it's only used when it
  literally says `entry: X` / `entry word: X`. Two rows needed a manual
  override after auditing the sheet by hand (see `MANUAL_WORD_OVERRIDES` in
  `scripts/extract_data.py`); everything else is programmatic.

Every one of those decisions is logged per-card in `data/qa_report.md` —
check it after any re-extraction, especially if the sheet's column layout
changes.

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

The spreadsheet's font-table spec calls for Castledown (Heavy/Regular/Fun
Bold), Amplify (Bold/Medium), and Benton Book — all proprietary Amplify
fonts we don't have license to redistribute here. `scripts/grade_fonts.py`
maps every grade band to a close free substitute at the *exact* sizes/line
heights from the spec:

| Band | Header substitute | Text substitute |
|---|---|---|
| K, 1 | Baloo 2 (800) | Nunito (400) |
| 2-5 | Poppins (700) | Source Sans 3 (400) |

**To switch to the real fonts**: drop the `.woff2`/`.ttf` files in
`templates/fonts/`, add an `@font-face` block for them in
`templates/fonts.css`, and change the `family` values in
`scripts/grade_fonts.py` — no layout/template code needs to change.

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
