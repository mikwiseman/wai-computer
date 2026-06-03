#!/bin/bash
# Database backup script for WaiComputer
# Usage: Run via cron at 3 AM UTC daily

set -euo pipefail

PROD_ENV_FILE="${PROD_ENV_FILE:-}"
BACKUP_DIR="${BACKUP_DIR:-}"
RETENTION_DAYS=14
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="${BACKUP_DIR}/waicomputer_${TIMESTAMP}.sql.gz"

if [[ -z "${PROD_ENV_FILE}" ]]; then
    echo "ERROR: PROD_ENV_FILE is required" >&2
    exit 1
fi
if [[ -z "${BACKUP_DIR}" ]]; then
    echo "ERROR: BACKUP_DIR is required" >&2
    exit 1
fi

# Ensure backup directory exists
mkdir -p "${BACKUP_DIR}"

# Load only DB credentials from the root-owned runtime env file.
if [[ ! -f "${PROD_ENV_FILE}" ]]; then
    echo "ERROR: Missing production env file at ${PROD_ENV_FILE}" >&2
    exit 1
fi

POSTGRES_USER=$(grep '^POSTGRES_USER=' "${PROD_ENV_FILE}" | cut -d= -f2)
POSTGRES_DB=$(grep '^POSTGRES_DB=' "${PROD_ENV_FILE}" | cut -d= -f2)

# Run pg_dump inside the Docker container
docker exec waicomputer-db pg_dump \
    -U "${POSTGRES_USER}" \
    -d "${POSTGRES_DB}" \
    --no-owner \
    --no-privileges \
    | gzip > "${BACKUP_FILE}"

# Verify backup is non-empty
if [ ! -s "${BACKUP_FILE}" ]; then
    echo "ERROR: Backup file is empty: ${BACKUP_FILE}" >&2
    rm -f "${BACKUP_FILE}"
    exit 1
fi

BACKUP_SIZE=$(du -h "${BACKUP_FILE}" | cut -f1)
echo "Backup created: ${BACKUP_FILE} (${BACKUP_SIZE})"

# Remove backups older than retention period
find "${BACKUP_DIR}" -name "waicomputer_*.sql.gz" -mtime +${RETENTION_DAYS} -delete
echo "Cleaned up backups older than ${RETENTION_DAYS} days"
