#!/bin/bash
# MinIO backup using mc mirror
set -e

BACKUP_DIR=${BACKUP_DIR:-/var/backups/autoformfiller/minio}
DATE=$(date +%Y%m%d)
DEST="$BACKUP_DIR/$DATE"

mkdir -p "$DEST"

echo "Mirroring MinIO buckets to $DEST..."
docker run --rm --network autoform_autoform_net minio/mc:latest \
    mirror local/autoformfiller-docs "$DEST/docs"

echo "MinIO backup complete."
