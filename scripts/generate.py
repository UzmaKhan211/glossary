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

# Minimum an auto-shrunk header/definition is allowed to shrink to, as a
# fraction of its nominal size, before we give up and let it clip. Keeps a
# pathologically long word/definition from becoming illegibly tiny.
MIN_SHRINK_RATIO = 0.62

# Two independent jobs:
#  1. The header (word) must never wrap to a second line (CSS already forces
#     white-space: nowrap + overflow: hidden on it) -- if it's too wide for
#     the card at its nominal 52pt, shrink it in 0.5pt steps until it fits on
#     one line, and record exactly which word got shrunk and by how much so
#     it can be reported back and reviewed by hand.
#  2. The existing behavior: if a long definition still makes the card taller
#     than its fixed box, shrink the definition (and, as a last resort, the
#     header again) until it fits.
AUTOFIT_JS = """
(minRatio) => {
  const report = [];
  const pxToPt = (px) => px * 72 / 96;

  function shrinkFontUntil(el, fitsFn, floorRatio) {
    const cs = getComputedStyle(el);
    const originalSize = parseFloat(cs.fontSize);
    const ratio = parseFloat(cs.lineHeight) / originalSize;
    const floor = originalSize * floorRatio;
    let size = originalSize;
    let guard = 0;
    while (!fitsFn() && size > floor && guard < 80) {
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

    if (header) {
      const { originalSize, finalSize } = shrinkFontUntil(
        header,
        () => header.scrollWidth <= header.clientWidth + 1,
        minRatio,
      );
      if (finalSize < originalSize) {
        report.push({
          word: header.textContent, grade,
          fromPt: Math.round(pxToPt(originalSize) * 10) / 10,
          toPt: Math.round(pxToPt(finalSize) * 10) / 10,
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
      shrinkFontUntil(header, () => card.scrollHeight <= card.clientHeight + 1, minRatio);
    }
  });

  return report;
}
"""


def load_cards(grades, limit=None):
    vocab = json.loads((DATA_DIR / "vocab.json").read_text())
    cards = []
    for grade in grades:
        grade_cards = vocab.get(grade, [])
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
                "text_html": c.get("text_html"),
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
            shrink_report = page.evaluate(AUTOFIT_JS, MIN_SHRINK_RATIO)
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
    if shrink_report:
        print(f"\n{len(shrink_report)} card(s) had their font auto-shrunk to fit -- please review:")
        for entry in shrink_report:
            print(f"  - grade {entry['grade']} '{entry['word']}': {entry['fromPt']}pt -> {entry['toPt']}pt "
                  f"({entry['reason']})")


if __name__ == "__main__":
    main()
