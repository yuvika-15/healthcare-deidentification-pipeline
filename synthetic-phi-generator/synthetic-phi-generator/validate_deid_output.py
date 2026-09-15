#!/usr/bin/env python3
"""
Score a de-identification pipeline's PDF output against the ground-truth
answer key produced by generate_dataset.py.


Two independent checks are run for every record in the answer key:

  1. Extraction check (uses pymupdf, same library as pdf_deid.py):
     re-implements the pipeline's exact extract_field() regex against
     the ORIGINAL input PDF and confirms it recovers the same
     patient_id / patient_name that's in the answer key. If this
     fails, your pipeline would have quarantined (or mis-parsed) that
     file rather than a redaction actually failing - worth knowing
     separately from a true PHI leak.

  2. Leak check: opens every de-identified PDF in the pipeline's PDF
     output directory and searches its extractable text for the
     original patient_id and patient_name from the answer key. Any
     hit is a genuine PHI leak - the string that should have been
     redacted is still present in the sanitized output.

Usage:
    python validate_deid_output.py \\
        --answer-key ./data/answer_key.csv \\
        --input-dir ./data/input/pdf \\
        --deid-dir ./data/output/pdf


"""
from __future__ import annotations

import argparse
import csv
import glob
import os
import re
import sys

KNOWN_LABELS = [
    "Patient ID", "Patient Age", "Patient Name", "GA", "Gender", "BMI",
    "Examination Findings", "Head", "Brain", "Heart", "Spine",
    "Abdominal wall", "Urinary tract", "Extremities", "Conclusion",
    "Date of Birth", "Exam Date", "Referring Physician", "Body Part Examined",
    "Collection Date", "Ordering Physician", "Contact",
]
_LABEL_ALTERNATION = "|".join(re.escape(label) for label in KNOWN_LABELS)


def extract_field(text: str, label: str, dotall: bool) -> str | None:
    """Same shape as pdf_deid.py's extract_field(). Pass dotall=False to
    reproduce the CURRENT pipeline behavior exactly (bug included); pass
    dotall=True to test the suggested fix (re.DOTALL + \\s+ boundary)."""
    if dotall:
        pattern = rf"{re.escape(label)}\s*:\s*(.+?)(?=\s+(?:{_LABEL_ALTERNATION})\s*:|\Z)"
        flags = re.DOTALL
    else:
        pattern = rf"{re.escape(label)}\s*:\s*(.+?)(?=\s{{2,}}(?:{_LABEL_ALTERNATION})\s*:|\Z)"
        flags = 0
    match = re.search(pattern, text, flags)
    return match.group(1).strip() if match else None


def load_answer_key(path: str) -> list[dict]:
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def check_extraction(input_dir: str, answer_key: list[dict], fitz) -> dict:
    results = {"current_regex_ok": 0, "fixed_regex_ok": 0, "total": 0, "failures": []}
    for row in answer_key:
        path = os.path.join(input_dir, row["filename"])
        if not os.path.isfile(path):
            results["failures"].append((row["filename"], "input file not found"))
            continue
        doc = fitz.open(path)
        text = doc[0].get_text("text", sort=True)
        doc.close()

        results["total"] += 1
        for dotall, key in ((False, "current_regex_ok"), (True, "fixed_regex_ok")):
            pid = extract_field(text, "Patient ID", dotall)
            pname = extract_field(text, "Patient Name", dotall)
            if pid == row["patient_id"] and pname == row["patient_name"]:
                results[key] += 1
            elif dotall is False:
                results["failures"].append(
                    (row["filename"], f"current regex: got id={pid!r} name={pname!r}")
                )
    return results


def check_leaks(deid_dir: str, answer_key: list[dict], fitz) -> dict:
    deid_files = glob.glob(os.path.join(deid_dir, "*.pdf"))
    corpus = []
    for path in deid_files:
        doc = fitz.open(path)
        text = " ".join(page.get_text("text") for page in doc)
        doc.close()
        corpus.append((path, text))

    leaks = []
    for row in answer_key:
        pid, pname = row["patient_id"], row["patient_name"]
        for path, text in corpus:
            if pid and pid in text:
                leaks.append((os.path.basename(path), "patient_id", pid))
            if pname and pname in text:
                leaks.append((os.path.basename(path), "patient_name", pname))

    return {
        "deid_files_scanned": len(deid_files),
        "patients_checked": len(answer_key),
        "leaks_found": leaks,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                      formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--answer-key", required=True)
    parser.add_argument("--input-dir", required=True,
                         help="Directory of ORIGINAL (pre-deid) synthetic PDFs")
    parser.add_argument("--deid-dir", default=None,
                         help="Directory of the pipeline's DE-IDENTIFIED PDF output "
                              "(omit to skip the leak check and only test extraction)")
    args = parser.parse_args()

    try:
        import pymupdf as fitz
    except ImportError:
        print("This validator needs pymupdf: pip install pymupdf", file=sys.stderr)
        return 1

    answer_key = load_answer_key(args.answer_key)
    print(f"Loaded {len(answer_key)} records from {args.answer_key}\n")

    print("=== Extraction check (against ORIGINAL input PDFs) ===")
    extraction = check_extraction(args.input_dir, answer_key, fitz)
    print(f"Current pdf_deid.py regex: {extraction['current_regex_ok']}/{extraction['total']} "
          f"files extracted correctly")
    print(f"Fixed regex (re.DOTALL + \\s+ boundary): "
          f"{extraction['fixed_regex_ok']}/{extraction['total']} files extracted correctly")
    if extraction["failures"]:
        print(f"\n{len(extraction['failures'])} extraction failures (current regex), first 10:")
        for fname, reason in extraction["failures"][:10]:
            print(f"  - {fname}: {reason}")

    if args.deid_dir:
        print("\n=== Leak check (against DE-IDENTIFIED output PDFs) ===")
        leaks = check_leaks(args.deid_dir, answer_key, fitz)
        print(f"Scanned {leaks['deid_files_scanned']} de-identified files "
              f"against {leaks['patients_checked']} known patient records")
        if leaks["leaks_found"]:
            print(f"\n*** {len(leaks['leaks_found'])} PHI LEAKS FOUND ***")
            for fname, field, value in leaks["leaks_found"][:20]:
                print(f"  - {fname}: {field}={value!r} still present in output")
        else:
            print("No leaks found: none of the known patient_id/patient_name "
                  "values from the answer key were found in any de-identified output file.")
    else:
        print("\n(--deid-dir not provided, skipping leak check)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
