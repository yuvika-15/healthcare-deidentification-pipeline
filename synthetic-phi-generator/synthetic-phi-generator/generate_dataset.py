#!/usr/bin/env python3
"""
Generate a synthetic PHI-bearing PDF report dataset for testing a
de-identification pipeline, together with a ground-truth answer-key CSV.

This mirrors the idea behind TCIA's Pseudo-PHI-DICOM-Data: don't just
generate plausible-looking documents, generate documents where you KNOW
exactly which strings are the injected PHI - so you can objectively
score a de-id pipeline's output ("did every one of these strings
actually disappear?") instead of eyeballing a handful of PDFs.

Usage:
    python generate_dataset.py --count 60 --output-dir ./data/input/pdf --seed 42

Output:
    <output-dir>/*.pdf                     the synthetic reports
    <output-dir>/../answer_key.csv         ground truth PHI per file
"""
from __future__ import annotations

import argparse
import csv
import os
import random
import sys

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

from fake_data import PatientRecord, generate_patient_record
from templates import TEMPLATE_RENDERERS

ANSWER_KEY_FIELDS = [
    "filename",
    "template",
    "patient_id",
    "patient_name",
    "gender",
    "age_years",
    "dob",
    "physician_name",
    "hospital_name",
    "address",
    "phone",
    "abnormal_flag",
]


def build_record(template: str) -> PatientRecord:
    rec = generate_patient_record(template)
    if template == "ultrasound":
        rec.extra["ga_weeks"] = random.randint(12, 40)
        rec.extra["ga_days"] = random.randint(0, 6)
        rec.extra["bmi"] = round(random.uniform(18.5, 34.0), 1)
    return rec


def render_pdf(rec: PatientRecord, out_path: str) -> None:
    c = canvas.Canvas(out_path, pagesize=letter)
    renderer = TEMPLATE_RENDERERS[rec.template]
    renderer(c, rec)
    c.showPage()
    c.save()


def answer_key_row(filename: str, rec: PatientRecord) -> dict:
    return {
        "filename": filename,
        "template": rec.template,
        "patient_id": rec.patient_id,
        "patient_name": rec.patient_name,
        "gender": rec.gender,
        "age_years": rec.age_years,
        "dob": rec.dob.isoformat(),
        "physician_name": rec.physician_name,
        "hospital_name": rec.hospital_name,
        "address": rec.address,
        "phone": rec.phone,
        "abnormal_flag": rec.extra.get("abnormal_flag", False),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=60,
                         help="Total number of PDF reports to generate (default: 60)")
    parser.add_argument("--output-dir", type=str, default="./output/pdf",
                         help="Directory to write generated PDFs into")
    parser.add_argument("--answer-key", type=str, default=None,
                         help="Path to write the answer-key CSV "
                              "(default: <output-dir>/../answer_key.csv)")
    parser.add_argument("--seed", type=int, default=None,
                         help="Random seed, for reproducible datasets")
    parser.add_argument("--templates", type=str, default="ultrasound,radiology,lab",
                         help="Comma-separated subset of templates to use")
    args = parser.parse_args()

    if args.seed is not None:
        random.seed(args.seed)

    templates = [t.strip() for t in args.templates.split(",") if t.strip()]
    for t in templates:
        if t not in TEMPLATE_RENDERERS:
            print(f"Unknown template '{t}'. Available: {list(TEMPLATE_RENDERERS)}", file=sys.stderr)
            return 1

    os.makedirs(args.output_dir, exist_ok=True)
    answer_key_path = args.answer_key or os.path.join(args.output_dir, os.pardir, "answer_key.csv")
    os.makedirs(os.path.dirname(os.path.abspath(answer_key_path)), exist_ok=True)

    rows = []
    used_ids = set()

    for i in range(args.count):
        template = templates[i % len(templates)]
        rec = build_record(template)
        # Ensure patient IDs are unique across the generated dataset -
        # duplicate IDs would make later per-patient validation ambiguous.
        while rec.patient_id in used_ids:
            rec.patient_id = rec.patient_id[:-1] + str(random.randint(0, 9))
        used_ids.add(rec.patient_id)

        filename = f"{template}_{rec.patient_id}.pdf"
        out_path = os.path.join(args.output_dir, filename)
        render_pdf(rec, out_path)
        rows.append(answer_key_row(filename, rec))

    with open(answer_key_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=ANSWER_KEY_FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Generated {len(rows)} PDF reports in: {os.path.abspath(args.output_dir)}")
    print(f"Answer key written to: {os.path.abspath(answer_key_path)}")
    by_template = {}
    for r in rows:
        by_template[r["template"]] = by_template.get(r["template"], 0) + 1
    for t, n in by_template.items():
        print(f"  - {t}: {n} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
