"""
DICOM de-identification and metadata extraction module.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import pydicom
from pydicom.dataset import Dataset
from pydicom.errors import InvalidDicomError

from pipeline.hashing import Hasher

logger = logging.getLogger("pipeline.dicom")

REMOVE_FIELDS = [
    "PatientAddress", "PatientTelephoneNumbers", "ReferringPhysicianName",
    "PerformingPhysicianName", "InstitutionName", "InstitutionAddress",
    "OperatorsName", "StationName", "OtherPatientIDs", "OtherPatientNames",
    "AccessionNumber", "StudyID",
]
DATE_FIELDS = ["PatientBirthDate", "StudyDate", "SeriesDate"]
UID_FIELDS = ["StudyInstanceUID", "SeriesInstanceUID", "SOPInstanceUID", "FrameOfReferenceUID"]
BURNED_IN_RISK_MODALITIES = {"US", "OT", "SC"}


@dataclass
class DicomResult:
    status: str  # "processed" | "quarantined" | "failed"
    pseudo_patient_id: str | None = None
    output_filename: str | None = None
    tags_removed: int = 0
    tags_hashed: int = 0
    tags_date_shifted: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)
    reason: str | None = None


def check_burned_in_risk(ds: Dataset) -> tuple[bool, str | None]:
    modality = str(ds.get("Modality", ""))
    burned_in_flag = str(ds.get("BurnedInAnnotation", "")).upper()
    if burned_in_flag == "YES":
        return True, "BurnedInAnnotation tag explicitly set to YES"
    if modality in BURNED_IN_RISK_MODALITIES:
        return True, f"modality '{modality}' has known burned-in-PHI risk, flag unset/unreliable"
    return False, None


class DicomDeidentifier:
    def __init__(self, hasher: Hasher):
        self.hasher = hasher

    def _extract_metadata(self, ds: Dataset) -> dict[str, Any]:
        """Extracts non-PHI technical metadata formatted for database insertion."""
        rows = ds.get("Rows")
        cols = ds.get("Columns")
        pixel_spacing = ds.get("PixelSpacing")

        return {
            "modality": str(ds.get("Modality", "")),
            "manufacturer": str(ds.get("Manufacturer", "")),
            "manufacturer_model": str(ds.get("ManufacturerModelName", "")),
            "body_part_examined": str(ds.get("BodyPartExamined", "")),
            "rows_px": int(rows) if rows is not None else None,
            "columns_px": int(cols) if cols is not None else None,
            "pixel_spacing": str(pixel_spacing) if pixel_spacing is not None else None,
            "patient_sex": str(ds.get("PatientSex", "")) or None,
            "patient_age": str(ds.get("PatientAge", "")) or None,
        }

    def deidentify(self, ds: Dataset) -> tuple[str, dict[str, int]]:
        original_patient_id = str(ds.get("PatientID", "UNKNOWN"))
        counts = {"hashed": 0, "date_shifted": 0, "removed": 0}

        # 1. Pseudonymize Patient ID
        pseudo_patient_id = self.hasher.pseudo_patient_id(original_patient_id)
        ds.PatientID = pseudo_patient_id
        counts["hashed"] += 1

        # 2. Derive UIDs and keep File Meta Header in sync
        for uid_field in UID_FIELDS:
            if uid_field in ds:
                original_uid = str(ds.get(uid_field))
                new_uid = self.hasher.derive_uid(original_uid)
                setattr(ds, uid_field, new_uid)
                counts["hashed"] += 1

                # Sync File Meta header if SOPInstanceUID changed
                if uid_field == "SOPInstanceUID" and hasattr(ds, "file_meta"):
                    if "MediaStorageSOPInstanceUID" in ds.file_meta:
                        ds.file_meta.MediaStorageSOPInstanceUID = new_uid

        # 3. Anonymize names and add compliance flags
        ds.PatientName = "ANONYMOUS"
        ds.PatientIdentityRemoved = "YES"
        ds.DeidentificationMethod = "Salted Hash + Deterministic Date Shift"

        # 4. Deterministic Date Shifting
        offset_days = self.hasher.date_offset_days(original_patient_id)
        for date_field in DATE_FIELDS:
            if date_field in ds:
                raw_date = str(ds.get(date_field, ""))
                if raw_date:
                    try:
                        parsed = datetime.strptime(raw_date, "%Y%m%d")
                        shifted = parsed + timedelta(days=offset_days)
                        setattr(ds, date_field, shifted.strftime("%Y%m%d"))
                        counts["date_shifted"] += 1
                    except ValueError:
                        setattr(ds, date_field, "")

        # 5. Recursive Direct Identifier Removal
        def scrub(dataset: Dataset) -> None:
            for f in REMOVE_FIELDS:
                if f in dataset:
                    del dataset[f]
                    counts["removed"] += 1
            for elem in dataset:
                if elem.VR == "SQ" and elem.value:
                    for item in elem.value:
                        if isinstance(item, Dataset):
                            scrub(item)

        scrub(ds)

        # 6. Strip Private/Vendor-Specific Tags
        before_count = len(ds)
        ds.remove_private_tags()
        counts["removed"] += max(0, before_count - len(ds))

        return pseudo_patient_id, counts

    def process_file(self, path: str) -> tuple[DicomResult, Dataset | None]:
        try:
            ds = pydicom.dcmread(path, force=True)
        except InvalidDicomError as e:
            return DicomResult(status="failed", reason=f"invalid_dicom: {e}"), None
        except Exception as e:
            logger.exception("Failed to read DICOM file: %s", path)
            return DicomResult(status="failed", reason=f"io_error: {str(e)}"), None

        # Burned-in PHI check
        is_risky, reason = check_burned_in_risk(ds)
        if is_risky:
            return DicomResult(status="quarantined", reason=reason), ds

        # Extract demographic/technical metadata before tag stripping
        metadata = self._extract_metadata(ds)

        try:
            pseudo_id, counts = self.deidentify(ds)
        except Exception as e:
            logger.exception("De-identification error for file: %s", path)
            return DicomResult(status="failed", reason=f"deid_error: {str(e)}"), None

        result = DicomResult(
            status="processed",
            pseudo_patient_id=pseudo_id,
            tags_removed=counts["removed"],
            tags_hashed=counts["hashed"],
            tags_date_shifted=counts["date_shifted"],
            metadata=metadata,
        )
        return result, ds