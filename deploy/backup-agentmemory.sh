#!/usr/bin/env bash
# Backup AgentMemory runtime state (Qdrant + SQLite + localjson snapshots)
# plus the .env and runtime config into a dated tarball.
#
# Usage on the server:
#   /opt/agentmemory/deploy/backup-agentmemory.sh               # default /var/backups/agentmemory
#   BACKUP_DIR=/mnt/backups /opt/agentmemory/deploy/backup-agentmemory.sh
#
# Restore (outline):
#   docker compose -f deploy/docker-compose.yml --env-file .env down
#   tar -xzf agentmemory-YYYY-MM-DD.tar.gz -C /
#   docker compose -f deploy/docker-compose.yml --env-file .env up -d --force-recreate
#
# The script is intentionally simple — no dependencies beyond docker and tar.
# Verify the tarball is complete by listing it after creation.

set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-/var/backups/agentmemory}"
PROJECT_DIR="${PROJECT_DIR:-/opt/agentmemory}"
VOLUME_NAME="${VOLUME_NAME:-deploy_agentmemory_data}"
TIMESTAMP="$(date -u +%Y-%m-%dT%H%M%SZ)"
OUTPUT="${BACKUP_DIR}/agentmemory-${TIMESTAMP}.tar.gz"

mkdir -p "${BACKUP_DIR}"

# Freeze a consistent view of the volume: qdrant holds file locks while
# running, so snapshotting through the running container ensures any
# open writes have flushed. Using a throwaway alpine container avoids
# depending on a specific tar version on the host.
echo "== Snapshotting volume ${VOLUME_NAME} =="
docker run --rm \
  -v "${VOLUME_NAME}:/data:ro" \
  -v "${BACKUP_DIR}:/backup" \
  alpine:latest \
  sh -c "cd / && tar -czf /backup/agentmemory-data-${TIMESTAMP}.tar.gz data"

# Config and env live on the host filesystem, outside the volume. Bundle
# them alongside so a restore is self-contained.
echo "== Archiving project env and runtime config =="
tar -czf "${BACKUP_DIR}/agentmemory-config-${TIMESTAMP}.tar.gz" \
  -C "${PROJECT_DIR}" \
  .env \
  deploy/agentmemory.config.json \
  deploy/xray-proxy.json \
  deploy/docker-compose.yml

# Combine into one file for transfer. Intentionally stored unencrypted:
# the tarball contains secrets (API token, OpenRouter key, OAuth client
# secret, xray tunnel credentials). Move it to a private location and
# encrypt at rest (e.g. rclone crypt, age, gpg) if it leaves the host.
echo "== Combining into ${OUTPUT} =="
tar -czf "${OUTPUT}" \
  -C "${BACKUP_DIR}" \
  "agentmemory-data-${TIMESTAMP}.tar.gz" \
  "agentmemory-config-${TIMESTAMP}.tar.gz"

rm -f \
  "${BACKUP_DIR}/agentmemory-data-${TIMESTAMP}.tar.gz" \
  "${BACKUP_DIR}/agentmemory-config-${TIMESTAMP}.tar.gz"

SIZE="$(du -h "${OUTPUT}" | cut -f1)"
echo "Backup written: ${OUTPUT} (${SIZE})"

# Optional: keep only the most recent N backups.
RETAIN="${BACKUP_RETAIN:-14}"
if [ -n "${RETAIN}" ] && [ "${RETAIN}" -gt 0 ]; then
  ls -1t "${BACKUP_DIR}"/agentmemory-*.tar.gz 2>/dev/null \
    | tail -n +$((RETAIN + 1)) \
    | xargs -r rm -f
fi
