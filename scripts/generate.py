#!/usr/bin/env python3
"""
Render Word Wall vocab cards (2 per Letter-landscape page) from data/vocab.json
into a print-ready PDF, using Playwright/Chromium so the HTML+CSS template can
match the approved prototype (Letter_79.pdf) exactly: rounded card border,
Amplify footer bar, "cut here" divider between the two cards on a page.

Usage:
  python3 scripts/generate.py --grade 2 --out output/grade2.pdf
  python3 scripts/generate.py --grade K 1 2 3 4 5 --out output/all_grades.pdf
  python3 scripts/generate.py --grade 3 --limit 6 --out output/grade3_sample.pdf
"""
import argparse
import datetime
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

# Minimum an auto-shrunk text/header block is allowed to shrink to, as a
# fraction of its nominal (font-table) size, before we give up and let it
# clip. Keeps very long definitions from becoming illegibly tiny.
MIN_SHRINK_RATIO = 0.62

AUTOFIT_JS = """
(minRatio) => {
  function shrinkToFit(card, selector, floorRatio) {
    const el = card.querySelector(selector);
    if (!el) return;
    const cs = getComputedStyle(el);
    const originalSize = parseFloat(cs.fontSize);
    const ratio = parseFloat(cs.lineHeight) / originalSize;
    const floor = originalSize * floorRatio;
    let size = originalSize;
    let guard = 0;
    while (card.scrollHeight > card.clientHeight + 1 && size > floor && guard < 60) {
      size -= 0.5;
      el.style.fontSize = size + 'px';
      el.style.lineHeight = (size * ratio) + 'px';
      guard++;
    }
  }
  document.querySelectorAll('.card:not(.empty)').forEach(card => {
    shrinkToFit(card, '.card-text', minRatio);
    if (card.scrollHeight > card.clientHeight + 1) {
      shrinkToFit(card, '.card-header', minRatio);
    }
  });
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


def render_html(cards, year, print_code):
    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))
    template = env.get_template("deck.html.j2")
    return template.render(
        pages=paginate(cards),
        grade_css=grade_css(),
        year=year,
        print_code=print_code,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--grade", nargs="+", default=["K", "1", "2", "3", "4", "5"],
                         help="Grade(s) to include, e.g. --grade 2 3")
    parser.add_argument("--limit", type=int, default=None,
                         help="Max cards per grade (useful for quick samples)")
    parser.add_argument("--out", default="output/word_wall_cards.pdf")
    parser.add_argument("--year", default=str(datetime.date.today().year))
    parser.add_argument("--print-code", default="", help="Optional footer print/SKU code")
    args = parser.parse_args()

    cards = load_cards(args.grade, args.limit)
    if not cards:
        print("No cards found for the requested grade(s).", file=sys.stderr)
        sys.exit(1)

    html = render_html(cards, args.year, args.print_code)
    build_html_path = TEMPLATES_DIR / "_build.html"
    build_html_path.write_text(html)

    out_path = REPO_ROOT / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=resolve_chromium_executable())
        page = browser.new_page()
        page.goto(build_html_path.resolve().as_uri())
        page.evaluate(AUTOFIT_JS, MIN_SHRINK_RATIO)
        page.pdf(
            path=str(out_path),
            width="11in",
            height="8.5in",
            print_background=True,
            margin={"top": "0", "bottom": "0", "left": "0", "right": "0"},
        )
        browser.close()

    build_html_path.unlink()
    print(f"Wrote {len(cards)} cards ({len(cards) // 2 + len(cards) % 2} pages) -> {out_path}")


if __name__ == "__main__":
    main()
