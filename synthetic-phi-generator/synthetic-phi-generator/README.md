# Synthetic PHI PDF Report Generator

A companion to your `healthcare-deidentification-pipeline` project: generates
clinical-report-style PDFs with **known, fabricated PHI** embedded in them,
plus a ground-truth CSV, so you can measure your de-id pipeline's redaction
accuracy the same way TCIA's `Pseudo-PHI-DICOM-Data` lets you measure it for
DICOMs — objectively, against an answer key, not by eyeballing outputs.

No real patient, physician, or hospital data is used anywhere. No `faker`
dependency either — just `reportlab`, so it runs offline in any container.

## Why this exists

There's no public dataset of "realistic clinical PDFs with fake-but-present
PHI, freely downloadable" — de-identified corpora (OpenI, MIMIC-CXR) have
had the PHI already stripped, and the datasets that *do* have PHI
(n2c2/i2b2) are plain text, not PDFs, and sit behind a Data Use Agreement.
So: generate your own, with the one property that actually matters for
testing a de-id pipeline — you know exactly what PHI is in each file.

## What's included

| File | Purpose |
|---|---|
| `fake_data.py` | Name/ID/address/date pools and generators (no network, no faker) |
| `templates.py` | 3 reportlab templates: `ultrasound`, `radiology`, `lab` |
| `generate_dataset.py` | CLI: generates N PDFs + `answer_key.csv` |
| `validate_deid_output.py` | Scores your pipeline's actual output against the answer key |

## Quickstart

```bash
pip install reportlab

# Generate 60 synthetic reports (20 of each template), reproducible via --seed
python generate_dataset.py --count 60 --seed 42 --output-dir ./data/input/pdf
```

This writes:
- `./data/input/pdf/ultrasound_60530.pdf`, `radiology_38156.pdf`, `lab_14714.pdf`, ...
- `./data/answer_key.csv` — one row per file, with every injected PHI value
  (`patient_id`, `patient_name`, `gender`, `age_years`, `dob`, `physician_name`,
  `hospital_name`, `address`, `phone`, `abnormal_flag`)



## The three templates, and why there are three

Real clinical PDFs don't share one layout. To actually stress-test your
pipeline (not just replay files that happen to fit its assumptions), the
three templates deliberately differ:

- **`ultrasound`** — two-column header (label top-left, matching demographic
  field top-right on the same row), mirroring your original `patient_10785.pdf`
  fixture almost exactly.
- **`radiology`** and **`lab`** — single-column, one field per line, plus a
  small results table for `lab`. This is a *more common* real-world layout
  and, as it turns out, a harder one for your current extractor (see below).



## Validating your actual pipeline's output

```bash
pip install pymupdf   

python validate_deid_output.py \
    --answer-key ./data/answer_key.csv \
    --input-dir ./data/input/pdf \
    --deid-dir ./data/output/pdf
```


1. **Extraction check** — re-runs both the current and fixed regex against
   the original PDFs, reporting exactly how many records each version
   correctly extracts (this is what produced the 10/30 vs 30/30 numbers above).
2. **Leak check** — opens every de-identified PDF your pipeline produced and
   searches its extractable text for each known `patient_id`/`patient_name`
   from the answer key. Any hit is a genuine PHI leak in the sanitized
   output, named and quoted.

