from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Any, Generator

import psycopg2
from psycopg2 import pool, sql
from psycopg2.extensions import connection as PgConnection

from pipeline.config import Config

logger = logging.getLogger("pipeline.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS patients (
    pseudo_patient_id   TEXT PRIMARY KEY,
    sex                 TEXT,
    age                 TEXT,
    first_seen_at       TIMESTAMP DEFAULT NOW(),
    last_seen_at        TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS dicom_files (
    file_id             SERIAL PRIMARY KEY,
    pseudo_patient_id   TEXT REFERENCES patients(pseudo_patient_id),
    source_file_hash    TEXT UNIQUE NOT NULL,
    output_filename     TEXT NOT NULL,
    modality            TEXT,
    manufacturer        TEXT,
    manufacturer_model  TEXT,
    body_part_examined  TEXT,
    rows_px             INTEGER,
    columns_px          INTEGER,
    pixel_spacing       TEXT,
    tags_removed        INTEGER,
    tags_hashed         INTEGER,
    tags_date_shifted   INTEGER,
    quarantined         BOOLEAN DEFAULT FALSE,
    processed_at        TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS pdf_reports (
    file_id             SERIAL PRIMARY KEY,
    pseudo_patient_id   TEXT REFERENCES patients(pseudo_patient_id),
    source_file_hash    TEXT UNIQUE NOT NULL,
    output_filename     TEXT NOT NULL,
    redaction_verified  BOOLEAN,
    processed_at        TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS pipeline_runs (
    run_id              SERIAL PRIMARY KEY,
    run_type            TEXT NOT NULL,
    started_at          TIMESTAMP,
    completed_at        TIMESTAMP,
    files_processed     INTEGER DEFAULT 0,
    files_skipped       INTEGER DEFAULT 0,
    files_quarantined   INTEGER DEFAULT 0,
    files_failed        INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_dicom_patient ON dicom_files(pseudo_patient_id);
CREATE INDEX IF NOT EXISTS idx_pdf_patient ON pdf_reports(pseudo_patient_id);
"""


class Database:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        # Initialize thread-safe pool based on worker capacity
        self._pool = pool.ThreadedConnectionPool(
            minconn=1,
            maxconn=max(cfg.max_workers + 2, 4),
            host=cfg.db_host,
            port=cfg.db_port,
            dbname=cfg.db_name,
            user=cfg.db_user,
            password=cfg.db_password,
        )

    @contextmanager
    def get_connection(self) -> Generator[PgConnection, None, None]:
        """Lease a connection from the pool and return it on exit."""
        conn = self._pool.getconn()
        conn.autocommit = True
        try:
            yield conn
        finally:
            self._pool.putconn(conn)

    def init_schema(self) -> None:
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(SCHEMA)
        logger.info("Database schema and indexes initialized successfully.")

    def is_processed(self, table: str, file_hash: str) -> bool:
        if table not in ("dicom_files", "pdf_reports"):
            raise ValueError(f"Invalid table queried for processing status: {table}")

        query = sql.SQL("SELECT 1 FROM {table} WHERE source_file_hash = %s LIMIT 1").format(
            table=sql.Identifier(table)
        )
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (file_hash,))
                return cur.fetchone() is not None

    def upsert_patient(
        self, pseudo_patient_id: str, sex: str | None = None, age: str | None = None
    ) -> None:
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO patients (pseudo_patient_id, sex, age, first_seen_at, last_seen_at)
                    VALUES (%s, %s, %s, NOW(), NOW())
                    ON CONFLICT (pseudo_patient_id) DO UPDATE 
                    SET last_seen_at = NOW(),
                        sex = COALESCE(EXCLUDED.sex, patients.sex),
                        age = COALESCE(EXCLUDED.age, patients.age);
                    """,
                    (pseudo_patient_id, sex, age),
                )

    def insert_dicom_record(self, record: dict[str, Any]) -> None:
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO dicom_files (
                        pseudo_patient_id, source_file_hash, output_filename,
                        modality, manufacturer, manufacturer_model, body_part_examined,
                        rows_px, columns_px, pixel_spacing,
                        tags_removed, tags_hashed, tags_date_shifted, quarantined
                    ) VALUES (
                        %(pseudo_patient_id)s, %(source_file_hash)s, %(output_filename)s,
                        %(modality)s, %(manufacturer)s, %(manufacturer_model)s, %(body_part_examined)s,
                        %(rows_px)s, %(columns_px)s, %(pixel_spacing)s,
                        %(tags_removed)s, %(tags_hashed)s, %(tags_date_shifted)s, %(quarantined)s
                    )
                    ON CONFLICT (source_file_hash) DO NOTHING;
                    """,
                    record,
                )

    def insert_pdf_record(self, record: dict[str, Any]) -> None:
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO pdf_reports (
                        pseudo_patient_id, source_file_hash, output_filename, redaction_verified
                    ) VALUES (
                        %(pseudo_patient_id)s, %(source_file_hash)s, %(output_filename)s, %(redaction_verified)s
                    )
                    ON CONFLICT (source_file_hash) DO NOTHING;
                    """,
                    record,
                )

    def insert_run_summary(self, run_type: str, started_at: Any, summary: dict[str, int]) -> None:
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO pipeline_runs (
                        run_type, started_at, completed_at,
                        files_processed, files_skipped, files_quarantined, files_failed
                    ) VALUES (%s, %s, NOW(), %s, %s, %s, %s);
                    """,
                    (
                        run_type,
                        started_at,
                        summary.get("processed", 0),
                        summary.get("skipped", 0),
                        summary.get("quarantined", 0),
                        summary.get("failed", 0),
                    ),
                )

    def close(self) -> None:
        """Close all connections across the pool."""
        if hasattr(self, "_pool") and not self._pool.closed:
            self._pool.closeall()
            logger.info("Database connection pool closed.")