#!/usr/bin/env python3
"""
Render Word Wall vocab cards (2 per Letter-landscape page) from data/vocab.json
into a print-ready PDF, using Playwright/Chromium so the HTML+CSS template can
match the approved card template exactly: rounded card border, word + definition
+ image side by side, Amplify logo footer, "cut here" divider between the two
cards on a page.

Usage:
  python3 scripts/generate.py --grade 2 --out output/grade2.pdf
  python3 scripts/generate.py --grade K 1 2 3 4 5 --out output/all_grades.pdf
  python3 scripts/generate.py --grade 3 --limit 6 --out output/grade3_sample.pdf
"""
import argparse
import json
import os
import sys
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from playwright.sync_api import sync_playwright

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = REPO_ROOT / "templates"
DATA_DIR = REPO_ROOT / "data"
IMAGES_DIR = REPO_ROOT / "assets" / "images"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from grade_fonts import grade_css  # noqa: E402
from bolding import text_html_for  # noqa: E402

# Minimum an auto-shrunk header/definition is allowed to shrink to, as a
# fraction of its nominal size, before we give up and let it clip. Keeps a
# pathologically long word/definition from becoming illegibly tiny.
MIN_SHRINK_RATIO = 0.62

# Four independent jobs:
#  1. Grow short definitions on no-image cards: a card with no picture and a
#     definition that's only 1-2 lines at the nominal 20pt leaves a big,
#     visually awkward empty gap below the text before the footer (the text
#     column runs the full card width, so "short" here means genuinely
#     short, not just narrow-column wrapping). Enlarging just the definition
#     text on these specific cards fills the card better without touching
#     anything else -- recorded in the report so it's easy to tell exactly
#     which cards changed. Two tiers: a definition that's already only 1
#     line at nominal size has the most room to fill, so it grows more (to
#     GROWN_DEFINITION_1LINE_PT); one that already wraps to 2 lines at
#     nominal size has less spare room and growing it as much would just
#     push it to wrap further, so it only grows to GROWN_DEFINITION_2LINE_PT.
#  1b. The same no-image + short-definition cards also get their header
#     (the word) enlarged from the nominal 52pt, for the same reason -- it
#     was left looking small relative to the extra room the card now has.
#     Only applies to cards that already qualified for job 1, so the set of
#     affected cards is identical between the two.
#  2. The header (word) must never wrap to a second line (CSS already forces
#     white-space: nowrap + overflow: hidden on it) -- if it's too wide for
#     the card at its nominal (or job-1b-enlarged) size, shrink it in 0.5pt
#     steps until it fits on one line, and record exactly which word got
#     shrunk and by how much so it can be reported back and reviewed by hand.
#  3. The existing behavior: if a long definition still makes the card taller
#     than its fixed box, shrink the definition (and, as a last resort, the
#     header again) until it fits -- this also acts as a safety net if
#     growing a short definition/header (jobs 1/1b) ever overflows the card.
GROWN_DEFINITION_1LINE_PT = 30  # nominal is 20pt; for a definition that's <=1 line at nominal size; see job 1
GROWN_DEFINITION_2LINE_PT = 24  # nominal is 20pt; for a definition that's exactly 2 lines at nominal size; see job 1
GROWN_HEADER_PT = 66  # nominal is 52pt; see job 1b above

AUTOFIT_JS = """
async ([minRatio, grownPt1Line, grownPt2Line, grownHeaderPt]) => {
  // Wait for the custom @font-face fonts (Castledown Pro / Benton Sans) to
  // finish loading before measuring/mutating anything. Forcing a layout
  // read (scrollWidth/scrollHeight) on an element before its own webfont
  // has finished applying can make Chromium lock that element onto the
  // fallback font for the rest of the render -- harmless for the header
  // (which was already the first thing measured, apparently after fonts
  // settle in practice) but the new job-1 measurement below reads
  // .card-text's scrollHeight even earlier in the page lifecycle, which
  // was enough to trigger it and print definitions in a fallback serif.
  await document.fonts.ready;

  const report = [];
  const pxToPt = (px) => px * 72 / 96;
  const ptToPx = (pt) => pt * 96 / 72;
  const HEADER_FIT_MARGIN_PX = 4;

  // .card-header is a flex item stretched (default align-items: stretch) to
  // the card's full content width, so its clientWidth is always that fixed
  // stretched width, and el.scrollWidth clamps to max(content, clientWidth)
  // -- it correctly reveals *overflow* (content wider than the box) but
  // clamps to clientWidth whenever content already fits, so it can't tell
  // us how much slack there is. Measuring the actual text run width via
  // canvas sidesteps that: it reflects the true content width regardless of
  // the stretched box, so a header can be required to land with real margin
  // to spare instead of just barely not overflowing.
  const measureCanvas = document.createElement('canvas');
  const measureCtx = measureCanvas.getContext('2d');
  function headerTextWidthPx(el) {
    const cs = getComputedStyle(el);
    measureCtx.font = `${cs.fontWeight} ${cs.fontSize} ${cs.fontFamily}`;
    return measureCtx.measureText(el.textContent).width;
  }

  // floorBasisPx, if given, anchors the shrink floor to that size instead of
  // the element's current size -- needed for the header, which job 1b may
  // have already grown to grownHeaderPt before this ever runs; without this
  // the floor would be minRatio of the *grown* size (a much narrower shrink
  // range) instead of minRatio of its true nominal size, and a long
  // multi-word header could run out of room to shrink down to a fit and
  // print clipped.
  function shrinkFontUntil(el, fitsFn, floorRatio, floorBasisPx) {
    const cs = getComputedStyle(el);
    const originalSize = parseFloat(cs.fontSize);
    const ratio = parseFloat(cs.lineHeight) / originalSize;
    const floor = (floorBasisPx != null ? floorBasisPx : originalSize) * floorRatio;
    let size = originalSize;
    let guard = 0;
    // Steps by 0.5px each iteration; the guard just bounds a runaway loop,
    // so it needs enough headroom to cross the full grown-size-to-floor
    // range (e.g. grown 66pt header down to its 52pt-nominal floor is ~90
    // steps) without cutting a shrink off early.
    while (!fitsFn() && size > floor && guard < 300) {
      size -= 0.5;
      el.style.fontSize = size + 'px';
      el.style.lineHeight = (size * ratio) + 'px';
      guard++;
    }
    return { originalSize, finalSize: size };
  }

  document.querySelectorAll('.card:not(.empty)').forEach(card => {
    const header = card.querySelector('.card-header');
    const gradeMatch = card.className.match(/grade-(\\S+)/);
    const grade = gradeMatch ? gradeMatch[1] : '?';
    // Captured before jobs 1/1b run, so it's always the true nominal size
    // (52pt) even on cards whose header gets grown below.
    const nominalHeaderPx = header ? parseFloat(getComputedStyle(header).fontSize) : null;

    const textEl0 = card.querySelector('.card-text');
    if (card.classList.contains('no-image') && textEl0 && textEl0.textContent.trim()) {
      const cs0 = getComputedStyle(textEl0);
      const baseSize = parseFloat(cs0.fontSize);
      const baseLineHeight = parseFloat(cs0.lineHeight);
      const lineCount = Math.round(textEl0.scrollHeight / baseLineHeight);
      let targetPt = null;
      if (lineCount <= 1) targetPt = grownPt1Line;
      else if (lineCount === 2) targetPt = grownPt2Line;
      const grownPx = targetPt != null ? ptToPx(targetPt) : null;
      if (grownPx != null && grownPx > baseSize) {
        const ratio = baseLineHeight / baseSize;
        textEl0.style.fontSize = grownPx + 'px';
        textEl0.style.lineHeight = (grownPx * ratio) + 'px';
        report.push({
          word: header ? header.textContent : '?', grade,
          fromPt: Math.round(pxToPt(baseSize) * 10) / 10,
          toPt: Math.round(pxToPt(grownPx) * 10) / 10,
          reason: 'short no-image definition enlarged to reduce empty space',
        });

        // Same qualifying card -- enlarge its header (word) too, for the
        // same reason (job 1b above).
        if (header) {
          const csH = getComputedStyle(header);
          const baseHeaderSize = parseFloat(csH.fontSize);
          const baseHeaderLineHeight = parseFloat(csH.lineHeight);
          const grownHeaderPx = ptToPx(grownHeaderPt);
          if (grownHeaderPx > baseHeaderSize) {
            const headerRatio = baseHeaderLineHeight / baseHeaderSize;
            header.style.fontSize = grownHeaderPx + 'px';
            header.style.lineHeight = (grownHeaderPx * headerRatio) + 'px';
            report.push({
              word: header.textContent, grade,
              fromPt: Math.round(pxToPt(baseHeaderSize) * 10) / 10,
              toPt: Math.round(pxToPt(grownHeaderPx) * 10) / 10,
              reason: 'header enlarged on short no-image card to reduce empty space',
            });
          }
        }
      }
    }

    if (header) {
      // A few px of required slack, not just "not technically overflowing"
      // -- a header that lands exactly flush against the card's inner edge
      // (zero px to spare) reads as cut off even though nothing is clipped.
      const headerFits = () => headerTextWidthPx(header) <= header.clientWidth - HEADER_FIT_MARGIN_PX;
      const { originalSize, finalSize } = shrinkFontUntil(
        header,
        headerFits,
        minRatio,
        nominalHeaderPx,
      );
      let effectiveFinalSize = finalSize;
      if (!headerFits()) {
        // A handful of unusually long compound-word headers still don't fit
        // even at the normal minRatio floor -- a header that spills past
        // the card edge is worse than a smaller one, so keep shrinking past
        // that floor (down to an absolute 12pt backstop) until it actually
        // fits on one line.
        const { finalSize: overriddenFinalSize } = shrinkFontUntil(
          header,
          headerFits,
          1,
          ptToPx(12),
        );
        effectiveFinalSize = overriddenFinalSize;
      }
      if (effectiveFinalSize < originalSize) {
        report.push({
          word: header.textContent, grade,
          fromPt: Math.round(pxToPt(originalSize) * 10) / 10,
          toPt: Math.round(pxToPt(effectiveFinalSize) * 10) / 10,
          reason: 'too wide for one line',
        });
      }
    }

    const textEl = card.querySelector('.card-text');
    if (textEl && card.scrollHeight > card.clientHeight + 1) {
      const { originalSize, finalSize } = shrinkFontUntil(
        textEl,
        () => card.scrollHeight <= card.clientHeight + 1,
        minRatio,
      );
      if (finalSize < originalSize) {
        report.push({
          word: header ? header.textContent : '?', grade,
          fromPt: Math.round(pxToPt(originalSize) * 10) / 10,
          toPt: Math.round(pxToPt(finalSize) * 10) / 10,
          reason: 'definition too tall for the card',
        });
      }
    }

    // Last resort if it's still overflowing: shrink the header further too.
    if (header && card.scrollHeight > card.clientHeight + 1) {
      shrinkFontUntil(header, () => card.scrollHeight <= card.clientHeight + 1, minRatio, nominalHeaderPx);
    }
  });

  return report;
}
"""


def load_cards(grades, limit=None):
    vocab = json.loads((DATA_DIR / "vocab.json").read_text())
    cards = []
    for grade in grades:
        # Alphabetize each grade's cards by word rather than leaving them in
        # master-spreadsheet row order, so a printed deck can be flipped
        # through/found A-Z. Sort before applying --limit so a sample deck
        # is the first N words alphabetically, not just the first N rows.
        grade_cards = sorted(vocab.get(grade, []), key=lambda c: c["word"].lower())
        if limit:
            grade_cards = grade_cards[:limit]
        for c in grade_cards:
            image_uri = None
            if c.get("image"):
                image_path = IMAGES_DIR / c["image"]
                image_uri = image_path.resolve().as_uri()
            cards.append({
                "grade": grade,
                "word": c["word"],
                "text": c.get("text") or "",
                "text_html": text_html_for(grade, c["word"]),
                "image_uri": image_uri,
            })
    return cards


def resolve_chromium_executable():
    """Locate a pre-installed Chromium build if PLAYWRIGHT_BROWSERS_PATH points
    to one (as it does in this sandbox), otherwise let Playwright use its own
    managed browser (the normal case after `playwright install`)."""
    browsers_path = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if browsers_path:
        candidates = sorted(Path(browsers_path).glob("chromium-*/chrome-linux/chrome"))
        if candidates:
            return str(candidates[-1])
    return None


def paginate(cards):
    pages = []
    for i in range(0, len(cards), 2):
        pair = (cards[i], cards[i + 1] if i + 1 < len(cards) else None)
        pages.append(pair)
    return pages


def render_html(cards, lang="en"):
    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))
    template = env.get_template("deck.html.j2")
    return template.render(
        pages=paginate(cards),
        grade_css=grade_css(),
        lang=lang,
    )


def render_pdf(cards, out_path, lang="en"):
    """Render `cards` to a print-ready PDF at out_path. Returns the list of
    autofit shrink-report entries (see AUTOFIT_JS) so callers can surface
    exactly which words got shrunk and why."""
    html = render_html(cards, lang)
    build_html_path = TEMPLATES_DIR / f"_build_{lang}.html"
    build_html_path.write_text(html)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=resolve_chromium_executable())
            page = browser.new_page()
            page.goto(build_html_path.resolve().as_uri())
            shrink_report = page.evaluate(
                AUTOFIT_JS,
                [MIN_SHRINK_RATIO, GROWN_DEFINITION_1LINE_PT, GROWN_DEFINITION_2LINE_PT, GROWN_HEADER_PT],
            )
            page.pdf(
                path=str(out_path),
                width="11in",
                height="8.5in",
                print_background=True,
                margin={"top": "0", "bottom": "0", "left": "0", "right": "0"},
            )
            browser.close()
    finally:
        build_html_path.unlink(missing_ok=True)

    return shrink_report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--grade", nargs="+", default=["K", "1", "2", "3", "4", "5"],
                         help="Grade(s) to include, e.g. --grade 2 3")
    parser.add_argument("--limit", type=int, default=None,
                         help="Max cards per grade (useful for quick samples)")
    parser.add_argument("--out", default="output/word_wall_cards.pdf")
    args = parser.parse_args()

    cards = load_cards(args.grade, args.limit)
    if not cards:
        print("No cards found for the requested grade(s).", file=sys.stderr)
        sys.exit(1)

    out_path = REPO_ROOT / args.out
    shrink_report = render_pdf(cards, out_path)

    print(f"Wrote {len(cards)} cards ({len(cards) // 2 + len(cards) % 2} pages) -> {out_path}")
    grown = [e for e in shrink_report if e["toPt"] > e["fromPt"]]
    shrunk = [e for e in shrink_report if e["toPt"] < e["fromPt"]]
    if grown:
        print(f"\n{len(grown)} font(s) enlarged on short no-image cards to reduce empty space:")
        for entry in grown:
            print(f"  - grade {entry['grade']} '{entry['word']}': {entry['fromPt']}pt -> {entry['toPt']}pt "
                  f"({entry['reason']})")
    if shrunk:
        print(f"\n{len(shrunk)} card(s) had their font auto-shrunk to fit -- please review:")
        for entry in shrunk:
            print(f"  - grade {entry['grade']} '{entry['word']}': {entry['fromPt']}pt -> {entry['toPt']}pt "
                  f"({entry['reason']})")


if __name__ == "__main__":
    main()
