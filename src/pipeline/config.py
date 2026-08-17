import os
from dataclasses import dataclass


def _int(name: str, default: int) -> int:
    val = os.getenv(name)
    return int(val) if val and val.strip() else default


def _float(name: str, default: float) -> float:
    val = os.getenv(name)
    return float(val) if val and val.strip() else default


@dataclass(frozen=True)
class Config:
    # --- Input / Output Paths ---
    dicom_input_dir: str = os.getenv("DICOM_INPUT_DIR", "/data/input/dicom")
    pdf_input_dir: str = os.getenv("PDF_INPUT_DIR", "/data/input/pdf")
    dicom_output_dir: str = os.getenv("DICOM_OUTPUT_DIR", "/data/output/dicom")
    pdf_output_dir: str = os.getenv("PDF_OUTPUT_DIR", "/data/output/pdf")
    quarantine_dir: str = os.getenv("QUARANTINE_DIR", "/data/quarantine")

    # --- Secrets ---
    deid_salt: str = os.getenv("DEID_SALT", "")

    # --- Database ---
    db_host: str = os.getenv("DB_HOST", "postgres")
    db_port: int = _int("DB_PORT", 5432)
    db_name: str = os.getenv("DB_NAME", "deid_pipeline")
    db_user: str = os.getenv("DB_USER", "postgres")
    db_password: str = os.getenv("DB_PASSWORD", "")

    # --- Operational Tuning ---
    max_workers: int = _int("MAX_WORKERS", 8)
    upload_max_retries: int = _int("UPLOAD_MAX_RETRIES", 3)
    upload_retry_backoff_seconds: float = _float("UPLOAD_RETRY_BACKOFF", 2.0)
    log_level: str = os.getenv("LOG_LEVEL", "INFO").upper()

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        missing = []
        if not self.deid_salt:
            missing.append("DEID_SALT")
        if not self.db_password:
            missing.append("DB_PASSWORD")
            
        if missing:
            raise RuntimeError(
                f"Missing required secrets: {', '.join(missing)}. "
                f"Set them as environment variables (e.g., via .env or docker-compose) - "
                f"never hardcode secrets in source."
            )


CONFIG = Config()