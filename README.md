# DICOM & PDF Report De-identification Pipeline

A containerized batch processing pipeline designed to securely de-identify medical imaging (DICOM) and clinical PDF reports, index non-PHI technical and demographic metadata into PostgreSQL, and output sanitized assets to target storage.

---

## Architecture Overview

```text
               +----------------------------------+
               |     Input Ingestion (Batch)      |
               |  (DICOM Studies & PDF Reports)   |
               +-----------------+----------------+
                                 |
        +------------------------+------------------------+
        |                                                 |
        v                                                 v
+-----------------------+                         +-----------------------+
|  DICOM De-id Engine   |                         |   PDF De-id Engine    |
| (PS 3.15 Conformance) |                         | (Visual & Stream Red) |
+-----------+-----------+                         +-----------+-----------+
            |                                                 |
            +--------------------+   +------------------------+
                                 |   |
                                 v   v
                +----------------------------------+
                |    Salted Cryptographic Core     |
                |    (HMAC-SHA256 & Date Shift)    |
                +----------------+-----------------+
                                 |
        +------------------------+------------------------+
        |                                                 |
        v                                                 v
+-----------------------+                         +-----------------------+
| Target Storage Output |                         |  PostgreSQL Metadata  |
|  (Sanitized Assets &  |                         | (Patients, Manifests, |
|   Quarantine Zones)   |                         |  Audit Runs, Indexes) |
+-----------------------+                         +-----------------------+

```

### 1. Processing Engines

* DICOM De-identification Engine (`src/pipeline/dicom_deid.py`):


* Conforms to DICOM PS 3.15 Annex E (Basic Application Level Confidentiality Profile).


* **Pseudonymization:** Generates salted HMAC-SHA256 hashes for `PatientID` and derives standards-compliant, valid UIDs (`StudyInstanceUID`, `SeriesInstanceUID`, `SOPInstanceUID`, `FrameOfReferenceUID`) maintaining cross-study linkability.


* **Deterministic Date Shifting:** Computes a per-patient integer offset range of $[-364, 364]$ days applied to `PatientBirthDate`, `StudyDate`, and `SeriesDate` to preserve longitudinal analytical intervals while destroying calendar timestamps.


* **Scrubbing & Sanitization:** Recursively purges direct identification tags across nested sequences (`VR == "SQ"`), strips all unstandardized vendor private tags unconditionally, and injects compliance markers (`PatientIdentityRemoved = "YES"`).


* **Burned-in Annotation Risk:** Detects explicit flags (`BurnedInAnnotation == YES`) or high-risk imaging modalities (e.g., Ultrasound `US`, Secondary Capture `SC`, Other `OT`) and routes files to quarantine without tag alteration.




* PDF De-identification Engine (`src/pipeline/pdf_deid.py`):


* **Ordered Layout Extraction:** Extracts text sorted in visual reading order (`sort=True`) to handle multi-layer clinical report layouts.


* **Boundary Field Localization:** Extracts structured entities (`Patient ID`, `Patient Name`, demographics) using regex pattern matching against known report anchors.


* **True Stream Redaction:** Locates on-page coordinates via `search_for()` and applies physical stream-level redactions (`apply_redactions()` with `garbage=4, deflate=True`) to purge underlying byte streams rather than placing superficial black overlays.


* **Post-Processing Verification:** Re-opens and verifies that identified PHI text cannot be extracted from the output artifact.


* **Extraction Failure Isolation:** Quarantines documents missing mandatory extraction boundaries rather than passing unredacted files.





### 2. Cross-Cutting Systems

* Deterministic Hashing Core (`src/pipeline/hashing.py`):


* Uses a shared 32-byte cryptographic salt across both engines to ensure a single patient's DICOM studies and PDF documents resolve to the exact same `pseudo_patient_id`.




* Crash-Safe Idempotency:


* SHA-256 content hashing (`source_file_hash`) combined with database constraints (`UNIQUE` + `ON CONFLICT DO NOTHING`) ensures repeated or resumed batch executions safely skip already-ingested assets.




* Observability & Health Telemetry:


* Emits line-delimited structured JSON logs with runtime context to standard output.


* Records detailed batch execution summaries (`files_processed`, `files_skipped`, `files_quarantined`, `files_failed`) in the `pipeline_runs` table.





---

## Setup and Execution

### Prerequisites

* Docker (Engine >= 24.0)
* Docker Compose (v2)

### 1. Environment Configuration

Copy the template configuration and generate a 32-byte cryptographic salt:

```bash
cp .env.example .env
openssl rand -hex 32

```

Populate `.env` with your generated salt, database credentials, and host path bindings:

```ini
DEID_SALT=0x_your_generated_32_byte_hex_salt_here
DB_NAME=deid_pipeline
DB_USER=postgres
DB_PASSWORD=deidpassword

# Host directories mounted into the pipeline container
DICOM_INPUT_HOST_DIR=./data/input/dicom
PDF_INPUT_HOST_DIR=./data/input/pdf
DICOM_OUTPUT_HOST_DIR=./data/output/dicom
PDF_OUTPUT_HOST_DIR=./data/output/pdf
QUARANTINE_HOST_DIR=./data/output/quarantine

# Operational tuning
MAX_WORKERS=8
LOG_LEVEL=INFO

```

### 2. Prepare Data Directories

Populate the host input folders with source datasets:

```bash
mkdir -p data/input/dicom data/input/pdf
mkdir -p data/output/dicom data/output/pdf data/output/quarantine/dicom data/output/quarantine/pdf

```

### 3. Build and Run

Launch the PostgreSQL database and batch runner container:

```bash
docker compose up --build

```

The pipeline container will wait for PostgreSQL to pass its internal health checks, auto-initialize schemas and indexes, process batches concurrently across worker threads, emit structured logs, and shut down cleanly upon completion.

### 4. Verification and Inspection

* Sanitized File System:


```bash
ls -lh data/output/dicom/
ls -lh data/output/pdf/
ls -lh data/output/quarantine/

```


* PostgreSQL Audit Records:


```bash
# View run summary metrics
docker compose exec postgres psql -U postgres -d deid_pipeline -c "SELECT * FROM pipeline_runs;"

# Inspect indexed patient demographics
docker compose exec postgres psql -U postgres -d deid_pipeline -c "SELECT * FROM patients LIMIT 5;"

# Review DICOM tag processing metrics
docker compose exec postgres psql -U postgres -d deid_pipeline -c "SELECT modality, manufacturer, count(*) FROM dicom_files GROUP BY modality, manufacturer;"

# Review PDF redaction verification status
docker compose exec postgres psql -U postgres -d deid_pipeline -c "SELECT redaction_verified, count(*) FROM pdf_reports GROUP BY redaction_verified;"

```


* **Clean Reset:**
```bash
# Tear down containers and wipe persistent volumes
docker compose down -v

```



---

## Configuration Explanation

Configuration parameters are managed via environment variables and loaded through `pipeline/config.py` with fail-fast initialization.

| Variable | Description | Default |
| --- | --- | --- |
| `DEID_SALT` | Secret key used for HMAC-SHA256 pseudonymization and date offsets (Required).

 | *None* |
| `DB_HOST` | Hostname of the PostgreSQL service.

 | `postgres` |
| `DB_PORT` | Port for database connections.

 | `5432` |
| `DB_NAME` | Target database catalog name.

 | `deid_pipeline` |
| `DB_USER` | Target database user.

 | `postgres` |
| `DB_PASSWORD` | Target database password (Required).

 | *None* |
| `DICOM_INPUT_DIR` | In-container source path for DICOM scans.

 | `/data/input/dicom` |
| `PDF_INPUT_DIR` | In-container source path for clinical PDF reports.

 | `/data/input/pdf` |
| `DICOM_OUTPUT_DIR` | In-container destination for sanitized DICOMs. | `/data/output/dicom` |
| `PDF_OUTPUT_DIR` | In-container destination for redacted PDFs. | `/data/output/pdf` |
| `QUARANTINE_DIR` | Destination root for files flagged for manual review.

 | `/data/output/quarantine` |
| `MAX_WORKERS` | Concurrency limit for the thread pool.

 | `8` |
| `LOG_LEVEL` | Log filtering threshold (`DEBUG`, `INFO`, `WARNING`, `ERROR`).

 | `INFO` |

---

## Design Decisions and Trade-Offs

* Deterministic Pseudonymization vs. Randomized Identifiers:


* *Decision:* Implemented salted HMAC-SHA256 keyed hashing.


* *Trade-Off:* Enables consistent longitudinal linkage across multi-modal assets for the same patient without central identity lookup tables, but requires protecting the cryptographic salt to prevent dictionary confirmation attacks.




* Deterministic Date Shifting vs. Date Nullification:


* *Decision:* Shifted all clinical dates by a consistent patient-specific offset in $[-364, 364]$ days.


* *Trade-Off:* Preserves crucial clinical intervals (e.g., patient age at exam, elapsed duration between follow-up scans) required for ML training while destroying absolute calendar dates.




* Strict Quarantine vs. Best-Effort Sanitization:


* *Decision:* Isolated unverified PDF extractions and modalities carrying burned-in pixel annotation risks into a dedicated quarantine store.


* *Trade-Off:* Prevents releasing partially de-identified data or false-positive sanitization at the expense of requiring manual operator review for flagged cases.




* Layout-Specific Parser vs. Generic NLP/NER:


* *Decision:* Employs deterministic regex bound to visual order coordinates.


* *Trade-Off:* Guarantees high extraction precision, low resource footprint, and immediate quarantine on schema mismatch, but requires parser extensions for newly introduced report templates.




* Database Concurrency & Idempotency:


* *Decision:* Relies on PostgreSQL unique constraints (`source_file_hash`) and thread-safe connection pooling rather than in-memory manifests.


* *Trade-Off:* Introduces database interaction overhead per file, but guarantees crash recovery and concurrent consistency across distributed workers.





---

## Git Workflow Recommendation

**Trunk-Based Development with Short-Lived Feature Branches**

* **Branching Strategy:** Developers branch directly off `main` using descriptive semantic prefixes (`feat/`, `fix/`, `chore/`). Feature branches are kept short-lived (merged within 1–2 days) to avoid drift across the shared hashing, database, and storage interfaces.


* **Automated CI Gating:** Every Pull Request triggers automated CI workflows running static analysis, code linting, test suites with synthetic fixtures, and deterministic hashing checks. Merging into `main` requires a passing CI run and at least one peer review.


* **Immutable Releases:** Production artifacts are built and published as versioned, immutable Docker images tagged directly from release commits on `main`.


* **Rationale:** Eliminates merge friction and migration drift common to long-lived branching strategies (e.g., GitFlow) while ensuring rigorous review gates on all PHI-handling code before deployment.