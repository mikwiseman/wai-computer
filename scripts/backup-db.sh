#!/bin/bash
# Database backup script for WaiSay
# Usage: Run via cron at 3 AM UTC daily
# Crontab: 0 3 * * * /opt/waisay/scripts/backup-db.sh

set -euo pipefail

PROD_ENV_FILE="${PROD_ENV_FILE:-/etc/waisay/backend.env}"
BACKUP_DIR="/opt/waisay/backups"
RETENTION_DAYS=14
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="${BACKUP_DIR}/waisay_${TIMESTAMP}.sql.gz"

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
docker exec waisay-db pg_dump \
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
find "${BACKUP_DIR}" -name "waisay_*.sql.gz" -mtime +${RETENTION_DAYS} -delete
echo "Cleaned up backups older than ${RETENTION_DAYS} days"
