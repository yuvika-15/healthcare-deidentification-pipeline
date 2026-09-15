"""
Pipeline:

validate config -> connect DB/storage -> process all DICOMs ->
process all PDFs -> write a run summary row for each.
"""
from __future__ import annotations

import logging
import os
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

from pipeline.config import CONFIG
from pipeline.db import Database
from pipeline.dicom_deid import DicomDeidentifier
from pipeline.hashing import Hasher
from pipeline.logging_setup import setup_logging
from pipeline.pdf_deid import PdfDeidentifier
from pipeline.storage import Storage

logger = logging.getLogger("pipeline.main")


def process_one_dicom(
    path: str,
    deidentifier: DicomDeidentifier,
    hasher: Hasher,
    db: Database,
    storage: Storage,
) -> str:
    fhash = hasher.file_hash(path)

    # 1. Idempotency Check
    if db.is_processed("dicom_files", fhash):
        return "skipped"

    # 2. De-identification
    result, ds = deidentifier.process_file(path)

    if result.status == "quarantined":
        dest = os.path.join(CONFIG.quarantine_dir, "dicom", os.path.basename(path))
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copy2(path, dest)
        logger.warning("dicom_quarantined", extra={"file": os.path.basename(path), "reason": result.reason})
        return "quarantined"

    if result.status == "failed" or ds is None or not result.pseudo_patient_id:
        logger.error("dicom_failed", extra={"file": os.path.basename(path), "reason": result.reason})
        return "failed"

    # 3. Local Staging and Storage Upload
    out_filename = hasher.make_output_filename(result.pseudo_patient_id, path)
    local_out = os.path.join("/tmp/dicom_out", out_filename)
    os.makedirs(os.path.dirname(local_out), exist_ok=True)

    try:
        ds.save_as(local_out)
        storage.upload(local_out, f"dicom/{out_filename}")
    finally:
        if os.path.exists(local_out):
            os.remove(local_out)

    # 4. Thread-Safe Database Ingestion
    meta = result.metadata
    db.upsert_patient(
        result.pseudo_patient_id,
        sex=meta.get("patient_sex"),
        age=meta.get("patient_age"),
    )
    db.insert_dicom_record({
        "pseudo_patient_id": result.pseudo_patient_id,
        "source_file_hash": fhash,
        "output_filename": out_filename,
        "modality": meta.get("modality", ""),
        "manufacturer": meta.get("manufacturer", ""),
        "manufacturer_model": meta.get("manufacturer_model", ""),
        "body_part_examined": meta.get("body_part_examined", ""),
        "rows_px": meta.get("rows_px"),
        "columns_px": meta.get("columns_px"),
        "pixel_spacing": meta.get("pixel_spacing", ""),
        "tags_removed": result.tags_removed,
        "tags_hashed": result.tags_hashed,
        "tags_date_shifted": result.tags_date_shifted,
        "quarantined": False,
    })

    logger.info("dicom_processed", extra={"pseudo_patient_id": result.pseudo_patient_id, "output": out_filename})
    return "processed"


def process_one_pdf(
    path: str,
    deidentifier: PdfDeidentifier,
    hasher: Hasher,
    db: Database,
    storage: Storage,
) -> str:
    fhash = hasher.file_hash(path)

    # 1. Idempotency Check
    if db.is_processed("pdf_reports", fhash):
        return "skipped"

    # Stage to temporary placeholder path
    temp_placeholder = os.path.join("/tmp/pdf_out", f"{fhash[:12]}.tmp")
    os.makedirs(os.path.dirname(temp_placeholder), exist_ok=True)

    try:
        result = deidentifier.process_file(path, temp_placeholder)

        if result.status == "quarantined":
            dest = os.path.join(CONFIG.quarantine_dir, "pdf", os.path.basename(path))
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.copy2(path, dest)
            logger.warning("pdf_quarantined", extra={"file": os.path.basename(path), "reason": result.reason})
            return "quarantined"

        if result.status == "failed" or not result.pseudo_patient_id:
            logger.error("pdf_failed", extra={"file": os.path.basename(path), "reason": result.reason})
            return "failed"

        # Rename to deterministic output name and upload
        out_filename = hasher.make_output_filename(result.pseudo_patient_id, path)
        final_local_path = os.path.join("/tmp/pdf_out", out_filename)
        os.replace(temp_placeholder, final_local_path)

        try:
            storage.upload(final_local_path, f"pdf/{out_filename}")
        finally:
            if os.path.exists(final_local_path):
                os.remove(final_local_path)

        # 2. Database Record Insertion
        db.upsert_patient(
            result.pseudo_patient_id,
            sex=result.metadata.get("gender"),
            age=result.metadata.get("patient_age"),
        )
        db.insert_pdf_record({
            "pseudo_patient_id": result.pseudo_patient_id,
            "source_file_hash": fhash,
            "output_filename": out_filename,
            "redaction_verified": result.redaction_verified,
        })

        if not result.redaction_verified:
            logger.warning("pdf_redaction_unverified", extra={"file": os.path.basename(path)})

        logger.info("pdf_processed", extra={"pseudo_patient_id": result.pseudo_patient_id, "output": out_filename})
        return "processed"

    finally:
        if os.path.exists(temp_placeholder):
            os.remove(temp_placeholder)


def run_batch(files: list[str], worker_fn, run_type: str, db: Database) -> dict[str, int]:
    summary = {"processed": 0, "skipped": 0, "quarantined": 0, "failed": 0}
    started_at = datetime.now()

    with ThreadPoolExecutor(max_workers=CONFIG.max_workers) as pool:
        futures = {pool.submit(worker_fn, f): f for f in files}
        for future in as_completed(futures):
            path = futures[future]
            try:
                status = future.result()
                summary[status] = summary.get(status, 0) + 1
            except Exception as e:
                summary["failed"] += 1
                logger.error(
                    "file_processing_exception",
                    extra={"file": os.path.basename(path), "error": str(e)},
                    exc_info=True,
                )

    db.insert_run_summary(run_type, started_at, summary)
    logger.info(f"{run_type}_batch_complete", extra={**summary, "total": len(files)})
    return summary


def main() -> None:
    setup_logging(CONFIG.log_level)
    logger.info(
        "pipeline_starting",
        extra={
            "dicom_input_dir": CONFIG.dicom_input_dir,
            "pdf_input_dir": CONFIG.pdf_input_dir,
            "max_workers": CONFIG.max_workers,
        },
    )

    hasher = Hasher(CONFIG.deid_salt)
    dicom_deidentifier = DicomDeidentifier(hasher)
    pdf_deidentifier = PdfDeidentifier(hasher)

    db = Database(CONFIG)
    db.init_schema()

    storage = Storage(CONFIG)
    storage.ensure_bucket()

    dicom_files = [str(p) for p in Path(CONFIG.dicom_input_dir).glob("*") if p.is_file()]
    pdf_files = [str(p) for p in Path(CONFIG.pdf_input_dir).glob("*") if p.is_file()]

    logger.info("files_discovered", extra={"dicom_count": len(dicom_files), "pdf_count": len(pdf_files)})

    dicom_summary = run_batch(
        dicom_files,
        lambda p: process_one_dicom(p, dicom_deidentifier, hasher, db, storage),
        "dicom",
        db,
    )
    pdf_summary = run_batch(
        pdf_files,
        lambda p: process_one_pdf(p, pdf_deidentifier, hasher, db, storage),
        "pdf",
        db,
    )

    logger.info("pipeline_complete", extra={"dicom": dicom_summary, "pdf": pdf_summary})
    db.close()


if __name__ == "__main__":
    main()