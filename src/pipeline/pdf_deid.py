"""
PDF de-identification
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass

import pymupdf as fitz  # PyMuPDF - `import fitz` directly is deprecated

from pipeline.hashing import Hasher

logger = logging.getLogger("pipeline.pdf")

KNOWN_LABELS = [
    "Patient ID", "Patient Age", "Patient Name", "GA", "Gender", "BMI",
    "Examination Findings", "Head", "Brain", "Heart", "Spine",
    "Abdominal wall", "Urinary tract", "Extremities", "Conclusion",
]
_LABEL_ALTERNATION = "|".join(re.escape(label) for label in KNOWN_LABELS)


def extract_field(text: str, label: str) -> str | None:
    pattern = rf"{re.escape(label)}\s*:\s*(.+?)(?=\s{{2,}}(?:{_LABEL_ALTERNATION})\s*:|\Z)"
    match = re.search(pattern, text)
    return match.group(1).strip() if match else None


@dataclass
class PdfResult:
    status: str  # "processed" | "quarantined" | "failed"
    pseudo_patient_id: str | None = None
    output_filename: str | None = None
    redaction_verified: bool | None = None
    reason: str | None = None


class PdfDeidentifier:
    def __init__(self, hasher: Hasher):
        self.hasher = hasher

    def process_file(self, path: str, out_path: str) -> PdfResult:
        doc = fitz.open(path)
        text_sorted = doc[0].get_text("text", sort=True)

        patient_id = extract_field(text_sorted, "Patient ID")
        patient_name = extract_field(text_sorted, "Patient Name")

        if not patient_id or not patient_name:
            doc.close()
            return PdfResult(status="quarantined", reason="field_extraction_failed")

        pseudo_patient_id = self.hasher.pseudo_patient_id(patient_id)

        for page in doc:
            for value in (patient_id, patient_name):
                for rect in page.search_for(value):
                    page.add_redact_annot(rect, fill=(0, 0, 0))
            page.apply_redactions()

        doc.save(out_path)
        doc.close()

        verify_doc = fitz.open(out_path)
        verify_text = " ".join(page.get_text("text", sort=True) for page in verify_doc)
        verify_doc.close()
        redaction_verified = (patient_id not in verify_text) and (patient_name not in verify_text)

        return PdfResult(
            status="processed",
            pseudo_patient_id=pseudo_patient_id,
            redaction_verified=redaction_verified,
        )
