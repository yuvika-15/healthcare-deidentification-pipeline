"""
Stores sanitized files on the local filesystem (a mounted Docker volume) -
no external storage service, no API/network dependency. Two destination
directories (DICOM vs PDF) are already defined separately in Config, so
this maps a key's prefix ("dicom/..." or "pdf/...") to the right one,
without requiring any change to how main.py calls upload().
"""
from __future__ import annotations

import logging
import os
import shutil
import time

from pipeline.config import Config

logger = logging.getLogger("pipeline.storage")


class Storage:
    def __init__(self, cfg: Config):
        self.cfg = cfg

    def ensure_bucket(self) -> None:
        """'Bucket' here just means: make sure the output directories exist."""
        os.makedirs(self.cfg.dicom_output_dir, exist_ok=True)
        os.makedirs(self.cfg.pdf_output_dir, exist_ok=True)
        logger.info("output_dirs_ready", extra={
            "dicom_output_dir": self.cfg.dicom_output_dir,
            "pdf_output_dir": self.cfg.pdf_output_dir,
        })

    def _resolve_dest(self, key: str) -> str:
        prefix, _, filename = key.partition("/")
        if prefix == "dicom":
            return os.path.join(self.cfg.dicom_output_dir, filename)
        elif prefix == "pdf":
            return os.path.join(self.cfg.pdf_output_dir, filename)
        raise ValueError(f"Unrecognized storage key prefix: {key!r}")

    def upload(self, local_path: str, key: str) -> None:
        """A local copy into the correct mounted output volume. Retries on
        transient OS-level errors, since this still runs unattended over
        thousands of files - a momentary disk/IO hiccup shouldn't fail
        the whole file."""
        dest_path = self._resolve_dest(key)
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)

        attempt = 0
        while True:
            attempt += 1
            try:
                shutil.copy2(local_path, dest_path)
                return
            except OSError as e:
                if attempt > self.cfg.upload_max_retries:
                    logger.error("upload_failed_final", extra={"key": key, "error": str(e), "attempts": attempt})
                    raise
                backoff = self.cfg.upload_retry_backoff_seconds * (2 ** (attempt - 1))
                logger.warning("upload_retry", extra={"key": key, "attempt": attempt, "backoff_s": backoff})
                time.sleep(backoff)
