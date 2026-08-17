"""
Cryptographic hashing, pseudonymization, and deterministic shifting utilities.
"""
from __future__ import annotations

import hashlib
import hmac
import os
from pathlib import Path


class Hasher:
    def __init__(self, salt: str | bytes):
        if isinstance(salt, str):
            self.salt = salt.encode("utf-8")
        else:
            self.salt = salt

        if not self.salt:
            raise ValueError("Hasher requires a non-empty salt string or byte sequence.")

    def hmac_hex(self, value: str) -> str:
        """Compute HMAC-SHA256 hex digest for a string using the pipeline salt."""
        return hmac.new(self.salt, str(value).encode("utf-8"), hashlib.sha256).hexdigest()

    def pseudo_patient_id(self, original_patient_id: str) -> str:
        """Generate a consistent 20-character pseudonymous ID (e.g., ANON0CBAE706C89F5103)."""
        digest = self.hmac_hex(original_patient_id)
        return f"ANON{digest[:16].upper()}"

    def date_offset_days(self, patient_id: str) -> int:
        """Derive a deterministic integer date offset in the range [-364, 364] days[cite: 1]."""
        digest = self.hmac_hex(patient_id)
        raw_int = int(digest[:8], 16)
        return (raw_int % 729) - 364

    def derive_uid(self, original_uid: str | None) -> str:
        """
        Derive a deterministic, valid DICOM UID under standard root prefix 2.25 (UUID-derived)[cite: 1].
        Truncated to the DICOM maximum length of 64 characters[cite: 1].
        """
        if not original_uid:
            return ""
        digest = self.hmac_hex(original_uid)
        return f"2.25.{int(digest, 16)}"[:64]

    @staticmethod
    def file_hash(path: str | Path, chunk_size: int = 65536) -> str:
        """Compute SHA-256 hash of raw file contents for deduplication and integrity tracking[cite: 1]."""
        sha = hashlib.sha256()
        with open(path, "rb") as f:
            while chunk := f.read(chunk_size):
                sha.update(chunk)
        return sha.hexdigest()

    @staticmethod
    def make_output_filename(pseudo_patient_id: str, original_path: str | Path) -> str:
        """Generate a deterministic sanitized filename preserving the original extension[cite: 1]."""
        orig_str = str(original_path)
        path_hash = hashlib.sha256(orig_str.encode("utf-8")).hexdigest()[:10]
        ext = os.path.splitext(orig_str)[1]
        return f"{pseudo_patient_id}_{path_hash}{ext}"