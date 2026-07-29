#!/usr/bin/env python3
"""
Word Wall pipeline -- a small local web app so mapping a new grade's
vocabulary to its units, adding Spanish translations, and exporting the
printable card decks doesn't require re-running scripts by hand (or asking
an engineer to do it).

Run with:
    python3 webapp/app.py
then open http://127.0.0.1:5050

There's no login and no multi-user isolation -- this is meant to be run
locally by one person at a time, the same way the CLI scripts it wraps
always were. All data is read from/written to the same data/ and output/
paths those scripts use, so this is a front end for the real pipeline,
not a separate copy of it.
"""
import sys
from pathlib import Path

from flask import Flask, flash, redirect, render_template, request, send_file, url_for

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pipeline  # noqa: E402

app = Flask(__name__)
app.secret_key = "word-wall-pipeline-local-tool"  # local single-user tool -- no real session security needed


@app.context_processor
def inject_current_year():
    import datetime
    return {"current_year": datetime.date.today().year}


def grade_status():
    vocab = pipeline.load_vocab()
    unit_vocab = pipeline.load_unit_vocab()
    status = {}
    for grade in pipeline.GRADES:
        cards = vocab.get(grade, [])
        entries = unit_vocab.get(grade, [])
        mapped = sum(1 for e in entries if e.get("primary_unit") is not None)
        spanish = sum(1 for e in entries if e.get("primary_unit") is not None and e.get("spanish_word"))
        status[grade] = {
            "label": pipeline.GRADE_LABELS[grade],
            "words": len(cards),
            "mapped": mapped,
            "spanish": spanish,
            "units_uploaded": sorted(pipeline.uploaded_units_summary(grade)),
            "has_data": bool(entries),
        }
    return status


@app.route("/")
def home():
    return render_template("home.html", grades=grade_status(), vocab_loaded=pipeline.VOCAB_PATH.exists())


@app.route("/upload-spreadsheet", methods=["GET", "POST"])
def upload_spreadsheet():
    if request.method == "POST":
        file = request.files.get("spreadsheet")
        if not file or not file.filename:
            flash("Choose the master glossary spreadsheet (.xlsx) first.", "error")
            return redirect(url_for("upload_spreadsheet"))
        tmp_path = pipeline.DATA_DIR / "_uploaded_master.xlsx"
        pipeline.DATA_DIR.mkdir(parents=True, exist_ok=True)
        file.save(tmp_path)
        try:
            counts = pipeline.process_master_spreadsheet(tmp_path)
        except Exception as exc:  # surface a friendly error instead of a stack trace
            flash(f"Couldn't read that spreadsheet: {exc}", "error")
            return redirect(url_for("upload_spreadsheet"))
        flash(
            "Spreadsheet processed: " + ", ".join(f"{pipeline.GRADE_LABELS[g]} {n}" for g, n in counts.items()),
            "success",
        )
        return redirect(url_for("home"))
    return render_template("upload_spreadsheet.html")


@app.route("/map/<grade>", methods=["GET", "POST"])
def map_grade(grade):
    if grade not in pipeline.GRADES:
        return "Unknown grade", 404

    if request.method == "POST":
        files = request.files.getlist("unit_pdfs")
        if not files or not any(f.filename for f in files):
            flash("Choose one or more unit PDF files first.", "error")
            return redirect(url_for("map_grade", grade=grade))

        uploaded, errors = [], []
        for file in files:
            if not file.filename:
                continue
            detected_grade, unit = pipeline.grade_and_unit_from_filename(file.filename)
            if unit is None:
                errors.append(
                    f"{file.filename}: couldn't tell which unit this is from the filename "
                    "(expected something like \"Grade5-Unit7.pdf\" or \"KG-Unit3.pdf\")."
                )
                continue
            if detected_grade != grade:
                errors.append(
                    f"{file.filename}: filename looks like {pipeline.GRADE_LABELS.get(detected_grade, detected_grade)}, "
                    f"but you're uploading to {pipeline.GRADE_LABELS[grade]} -- double-check this is the right file."
                )
            pdf_bytes = file.read()
            count, warnings = pipeline.save_and_parse_unit_pdf(grade, unit, file.filename, pdf_bytes)
            uploaded.append(f"Unit {unit}: {count} words")
            for w in warnings:
                errors.append(f"{file.filename} (unit {unit}): {w}")

        if uploaded:
            pipeline.match_grade(grade)
            flash(f"Uploaded {', '.join(uploaded)}. Data mapped -- review it below.", "success")
        for e in errors:
            flash(e, "warning")
        return redirect(url_for("review_grade", grade=grade))

    return render_template(
        "map_grade.html",
        grade=grade,
        grade_label=pipeline.GRADE_LABELS[grade],
        units_uploaded=pipeline.uploaded_units_summary(grade),
        word_count=len(pipeline.load_vocab().get(grade, [])),
    )


@app.route("/review/<grade>", methods=["GET", "POST"])
def review_grade(grade):
    if grade not in pipeline.GRADES:
        return "Unknown grade", 404

    unit_vocab = pipeline.load_unit_vocab()
    entries = unit_vocab.get(grade, [])

    if request.method == "POST":
        for i, entry in enumerate(entries):
            prefix = f"row{i}_"
            unit_raw = request.form.get(prefix + "primary_unit", "").strip()
            entry["primary_unit"] = int(unit_raw) if unit_raw.isdigit() else None
            entry["word"] = request.form.get(prefix + "word", entry["word"]).strip()
            entry["text"] = request.form.get(prefix + "text", entry["text"]).strip()
            entry["spanish_word"] = request.form.get(prefix + "spanish_word", entry["spanish_word"]).strip()
            entry["spanish_text"] = request.form.get(prefix + "spanish_text", entry["spanish_text"]).strip()
        unit_vocab[grade] = entries
        pipeline.save_unit_vocab(unit_vocab)
        flash("Changes saved.", "success")
        return redirect(url_for("review_grade", grade=grade))

    rows = sorted(
        enumerate(entries),
        key=lambda pair: (pair[1]["primary_unit"] is None, pair[1]["primary_unit"] or 0, pair[1]["word"].lower()),
    )
    return render_template(
        "review_grade.html",
        grade=grade,
        grade_label=pipeline.GRADE_LABELS[grade],
        rows=rows,
    )


@app.route("/images/<path:rel_path>")
def serve_image(rel_path):
    images_dir = (pipeline.REPO_ROOT / "assets" / "images").resolve()
    target = (images_dir / rel_path).resolve()
    if images_dir not in target.parents or not target.exists():
        return "Not found", 404
    return send_file(target)


@app.route("/generate", methods=["GET", "POST"])
def generate():
    status = grade_status()
    if request.method == "POST":
        grades = request.form.getlist("grades")
        language = request.form.get("language")
        if not grades:
            flash("Pick at least one grade first.", "error")
            return redirect(url_for("generate"))
        if language not in ("en", "es"):
            flash("Pick a language.", "error")
            return redirect(url_for("generate"))

        import datetime
        out_name = f"word_wall_{'spanish' if language == 'es' else 'english'}_{'-'.join(grades)}.pdf"
        out_path = pipeline.OUTPUT_DIR / out_name
        count = pipeline.render_card_pdf(grades, language, out_path, str(datetime.date.today().year))
        if count == 0:
            flash("No cards to export for that selection -- map some words to units first.", "error")
            return redirect(url_for("generate"))
        return send_file(out_path, as_attachment=True, download_name=out_name)

    return render_template("generate.html", grades=status)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5050, debug=True)
