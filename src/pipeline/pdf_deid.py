"""
PDF de-identification module.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

import pymupdf as fitz  # PyMuPDF - `import fitz` directly is deprecated

from pipeline.hashing import Hasher

logger = logging.getLogger("pipeline.pdf")

KNOWN_LABELS = [
    "Patient ID", "Patient Age", "Patient Name", "GA", "Gender", "BMI",
    "Examination Findings", "Head", "Brain", "Heart", "Spine",
    "Abdominal wall", "Urinary tract", "Extremities", "Conclusion",
    "Collection Date", "Ordering Physician", "Contact",
]
_LABEL_ALTERNATION = "|".join(re.escape(label) for label in KNOWN_LABELS)


def extract_field(text: str, label: str) -> str | None:
    """Extract the value following `label:`, stopping at end-of-line, the next
    known label, or end of text (matches notebook behavior - no DOTALL)."""
    pattern = rf"{re.escape(label)}\s*:\s*([^\n]+?)(?=\s+(?:{_LABEL_ALTERNATION})\s*:|\n|\Z)"
    match = re.search(pattern, text)
    return match.group(1).strip() if match else None


def extract_header_institution(text: str) -> str | None:
    
    first_label_pos = len(text)
    for label in KNOWN_LABELS:
        idx = text.find(label)
        if idx != -1:
            first_label_pos = min(first_label_pos, idx)
    header_text = text[:first_label_pos]
    cleaned = re.sub(r"[^A-Za-z\s]", " ", header_text).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned if cleaned else None


@dataclass
class PdfResult:
    status: str  # "processed" | "quarantined" | "failed"
    pseudo_patient_id: str | None = None
    output_filename: str | None = None
    redaction_verified: bool | None = None
    reason: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class PdfDeidentifier:
    def __init__(self, hasher: Hasher):
        self.hasher = hasher

    def process_file(self, path: str, out_path: str) -> PdfResult:
        doc = fitz.open(path)
        try:
            text_sorted = doc[0].get_text("text", sort=True)

            patient_id = extract_field(text_sorted, "Patient ID")
            patient_name = extract_field(text_sorted, "Patient Name")

            if not patient_id or not patient_name:
                return PdfResult(status="quarantined", reason="field_extraction_failed")

            # Additional direct identifiers - matches the notebook's final
            # deidentify_pdf(), which redacts more than just ID/name.
            physician_name = extract_field(text_sorted, "Ordering Physician")
            contact = extract_field(text_sorted, "Contact")
            collection_date = extract_field(text_sorted, "Collection Date")
            institution_name = extract_header_institution(text_sorted)
            gender = extract_field(text_sorted, "Gender")
            age = extract_field(text_sorted, "Patient Age")

            pseudo_patient_id = self.hasher.pseudo_patient_id(patient_id)

            values_to_redact = [
                v for v in (
                    patient_id, patient_name, physician_name,
                    contact, collection_date, institution_name,
                )
                if v
            ]

            for page in doc:
                for value in values_to_redact:
                    for rect in page.search_for(value):
                        page.add_redact_annot(rect, fill=(0, 0, 0))
                page.apply_redactions()

            doc.save(out_path)
        finally:
            doc.close()

        # Verify ALL redacted values are gone, not just patient_id/name.
        verify_doc = fitz.open(out_path)
        try:
            verify_text = " ".join(page.get_text("text", sort=True) for page in verify_doc)
        finally:
            verify_doc.close()

        redaction_verified = all(value not in verify_text for value in values_to_redact)
        if not redaction_verified:
            logger.warning("pdf_redaction_incomplete", extra={"file": path})

        return PdfResult(
            status="processed",
            pseudo_patient_id=pseudo_patient_id,
            redaction_verified=redaction_verified,
            metadata={"gender": gender, "patient_age": age},
        )
