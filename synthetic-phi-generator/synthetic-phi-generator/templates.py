"""
PDF report templates rendered with reportlab.

Each template embeds the same PHI header contract so the existing
pdf_deid.py extractor (KNOWN_LABELS-based regex) can find `Patient ID`
and `Patient Name` regardless of which template produced the file:

    Patient ID : <value>
    Patient Name : <value>
    Gender : <value>
    ...

The `ultrasound` template intentionally uses a two-column layout (label
top-left / demographic block top-right) matching real-world hospital
report layouts, similar to the original assignment's fixtures - this is
the harder, more realistic case for text-extraction-order bugs.
The `radiology` and `lab` templates use a simpler single-column layout,
demonstrating an easier layout your pipeline should also handle cleanly.
"""
from __future__ import annotations

import textwrap

from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas

from fake_data import PatientRecord, random_bool_finding, random_exam_date

PAGE_W, PAGE_H = letter


def _draw_field(c: canvas.Canvas, x: float, y: float, label: str, value: str,
                 font: str = "Helvetica-Bold", size: int = 11) -> None:
 
    c.setFont(font, size)
    c.drawString(x, y, f"{label} : {value}")


def _draw_header_bar(c: canvas.Canvas, hospital_name: str) -> None:
    c.setFillColorRGB(0.85, 0.1, 0.1)
    c.circle(PAGE_W - 1.1 * inch, PAGE_H - 0.85 * inch, 0.28 * inch, fill=1, stroke=0)
    c.setFillColorRGB(1, 1, 1)
    c.setFont("Helvetica-Bold", 14)
    c.drawCentredString(PAGE_W - 1.1 * inch, PAGE_H - 0.9 * inch, "+")
    c.setFillColorRGB(0, 0, 0)
    c.setFont("Helvetica-Bold", 20)
    c.drawCentredString(PAGE_W / 2, PAGE_H - 0.85 * inch, hospital_name)
    c.setLineWidth(1.5)
    c.line(0.6 * inch, PAGE_H - 1.15 * inch, PAGE_W - 0.6 * inch, PAGE_H - 1.15 * inch)


def render_ultrasound_report(c: canvas.Canvas, rec: PatientRecord) -> None:
    """Two-column obstetric ultrasound report, mirroring the original
    Origin Hospital fixture layout (label/value pairs split left/right)."""
    _draw_header_bar(c, rec.hospital_name)

    ga_weeks = rec.extra.get("ga_weeks", 24)
    ga_days = rec.extra.get("ga_days", 0)
    bmi = rec.extra.get("bmi", 24)

    left_x = 0.6 * inch
    y = PAGE_H - 1.55 * inch
    line_h = 0.28 * inch

  
    c.setFont("Helvetica-Bold", 11)
    c.drawString(left_x, y, f"Patient ID : {rec.patient_id}" + " " * 18 +
                 f"Patient Age : {rec.age_years} years")
    y -= line_h
    c.drawString(left_x, y, f"Patient Name : {rec.patient_name}" + " " * 18 +
                 f"GA : {ga_weeks} weeks {ga_days} day(s)")
    y -= line_h
    c.drawString(left_x, y, f"Gender : {rec.gender}" + " " * 18 + f"BMI : {bmi}")

    y -= line_h * 1.8
    c.setFont("Helvetica-Bold", 14)
    c.drawString(left_x, y, "Examination Findings")
    y -= line_h * 1.4

    findings = [
        ("Head", "Normal skull appearance"),
        ("Brain", "No choroid plexus cyst seen"),
        ("Heart", "Normal 4 chamber view"),
        ("Spine", "No spina bifida"),
        ("Abdominal wall", "Normal"),
        ("Urinary tract", "Normal"),
        ("Extremities", "Hands and feet appear normal"),
    ]
    abnormal_flag = random_bool_finding()
    if abnormal_flag:
        idx = 1
        findings[idx] = ("Brain", "Choroid plexus cyst noted, recommend follow-up scan")

    for label, val in findings:
        _draw_field(c, left_x, y, label, val)
        y -= line_h

    y -= line_h
    c.setFont("Helvetica-Bold", 14)
    c.drawString(left_x, y, "Conclusion")
    y -= line_h * 1.2
    c.setFont("Helvetica", 10)
    conclusion = (
        "Findings suggestive of a soft marker; clinical correlation and follow-up advised."
        if abnormal_flag else
        "There is no structural defects and normal flow patterns, no fetal abnormalities detected in this scan."
    )
    c.drawString(left_x, y, conclusion)
    rec.extra["abnormal_flag"] = abnormal_flag


def render_radiology_report(c: canvas.Canvas, rec: PatientRecord) -> None:
    """Single-column chest X-ray style radiology report."""
    _draw_header_bar(c, rec.hospital_name)

    exam_date = rec.extra.get("exam_date") or random_exam_date()
    body_part = rec.extra.get("body_part", "Chest (PA and Lateral)")

    x = 0.6 * inch
    y = PAGE_H - 1.55 * inch
    line_h = 0.26 * inch

    rows = [
        ("Patient ID", rec.patient_id),
        ("Patient Name", rec.patient_name),
        ("Gender", rec.gender),
        ("Patient Age", f"{rec.age_years} years"),
        ("Date of Birth", rec.dob.strftime("%d %b %Y")),
        ("Exam Date", exam_date.strftime("%d %b %Y")),
        ("Referring Physician", rec.physician_name),
        ("Body Part Examined", body_part),
    ]
    for label, val in rows:
        _draw_field(c, x, y, label, str(val))
        y -= line_h

    y -= line_h * 0.6
    c.setLineWidth(0.75)
    c.line(x, y, PAGE_W - x, y)
    y -= line_h * 1.2

    c.setFont("Helvetica-Bold", 13)
    c.drawString(x, y, "Findings")
    y -= line_h * 1.2

    abnormal_flag = random_bool_finding(0.2)
    findings_text = (
        "Patchy opacity noted in the right lower lobe, correlate clinically for infection."
        if abnormal_flag else
        "Lungs are clear bilaterally. No focal consolidation, effusion, or pneumothorax. "
        "Cardiomediastinal silhouette within normal limits."
    )
    c.setFont("Helvetica", 10.5)
    for line in textwrap.wrap(findings_text, width=88):
        c.drawString(x, y, line)
        y -= line_h

    y -= line_h * 0.6
    c.setFont("Helvetica-Bold", 13)
    c.drawString(x, y, "Impression")
    y -= line_h * 1.2
    c.setFont("Helvetica", 10.5)
    impression = (
        "Findings concerning for early focal pneumonia; clinical correlation recommended."
        if abnormal_flag else
        "No acute cardiopulmonary abnormality."
    )
    c.drawString(x, y, impression)
    rec.extra["abnormal_flag"] = abnormal_flag
    rec.extra["exam_date"] = exam_date
    rec.extra["body_part"] = body_part


def render_lab_report(c: canvas.Canvas, rec: PatientRecord) -> None:
    """Single-column lab results report with a simple text-based table."""
    _draw_header_bar(c, rec.hospital_name)

    exam_date = rec.extra.get("exam_date") or random_exam_date()

    x = 0.6 * inch
    y = PAGE_H - 1.55 * inch
    line_h = 0.26 * inch

    rows = [
        ("Patient ID", rec.patient_id),
        ("Patient Name", rec.patient_name),
        ("Gender", rec.gender),
        ("Patient Age", f"{rec.age_years} years"),
        ("Collection Date", exam_date.strftime("%d %b %Y")),
        ("Ordering Physician", rec.physician_name),
        ("Contact", rec.phone),
    ]
    for label, val in rows:
        _draw_field(c, x, y, label, str(val))
        y -= line_h

    y -= line_h * 0.6
    c.setFont("Helvetica-Bold", 13)
    c.drawString(x, y, "Complete Blood Count")
    y -= line_h * 1.3

    col_x = [x, x + 2.2 * inch, x + 3.6 * inch, x + 5.0 * inch]
    headers = ["Test", "Result", "Units", "Reference Range"]
    c.setFont("Helvetica-Bold", 10)
    for cx, h in zip(col_x, headers):
        c.drawString(cx, y, h)
    y -= line_h * 0.9
    c.line(x, y, PAGE_W - x, y)
    y -= line_h

    abnormal_flag = random_bool_finding(0.25)
    tests = [
        ("Hemoglobin", "13.8", "g/dL", "13.0 - 17.0"),
        ("WBC Count", "7.2", "x10^3/uL", "4.0 - 11.0"),
        ("Platelet Count", "250", "x10^3/uL", "150 - 400"),
        ("Hematocrit", "41", "%", "38 - 50"),
    ]
    if abnormal_flag:
        tests[1] = ("WBC Count", "14.6", "x10^3/uL", "4.0 - 11.0")

    c.setFont("Helvetica", 10)
    for row in tests:
        for cx, val in zip(col_x, row):
            c.drawString(cx, y, val)
        y -= line_h

    y -= line_h * 0.6
    c.setFont("Helvetica-Bold", 13)
    c.drawString(x, y, "Interpretation")
    y -= line_h * 1.2
    c.setFont("Helvetica", 10.5)
    interp = (
        "Mild leukocytosis noted; clinical correlation for possible infection recommended."
        if abnormal_flag else
        "All values within normal reference ranges."
    )
    c.drawString(x, y, interp)
    rec.extra["abnormal_flag"] = abnormal_flag
    rec.extra["exam_date"] = exam_date


TEMPLATE_RENDERERS = {
    "ultrasound": render_ultrasound_report,
    "radiology": render_radiology_report,
    "lab": render_lab_report,
}
