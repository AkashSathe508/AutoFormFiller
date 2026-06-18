#!/bin/bash
# PostgreSQL backup script
set -e

BACKUP_DIR=${BACKUP_DIR:-/var/backups/autoformfiller}
DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="$BACKUP_DIR/postgres_$DATE.sql.gz"

mkdir -p "$BACKUP_DIR"

echo "Backing up PostgreSQL to $BACKUP_FILE..."
docker exec autoform_postgres pg_dump -U autoform autoformfiller | gzip > "$BACKUP_FILE"

# Keep only last 7 days
find "$BACKUP_DIR" -name 'postgres_*.sql.gz' -mtime +7 -delete

echo "Backup complete: $BACKUP_FILE"
