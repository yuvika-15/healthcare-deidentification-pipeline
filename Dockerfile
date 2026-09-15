FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/
COPY config/ ./config/

RUN mkdir -p /data/input/dicom /data/input/pdf /data/output/dicom /data/output/pdf /data/output/quarantine

ENV PYTHONUNBUFFERED=1

ENTRYPOINT ["python", "-m", "src.main"]

ENV PYTHONPATH=/app/src