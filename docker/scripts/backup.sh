#!/bin/sh
# MERAK IDE 数据库自动备份脚本
# 每日凌晨3点执行，保留最近30天

BACKUP_DIR="/backups"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="${BACKUP_DIR}/merak_ide_${TIMESTAMP}.sql.gz"

echo "[$(date)] Starting backup..."

# PostgreSQL 备份
pg_dump -h postgres -U merak -d merak_ide | gzip > "${BACKUP_FILE}"

if [ $? -eq 0 ]; then
    echo "[$(date)] Backup successful: ${BACKUP_FILE}"
    SIZE=$(du -h "${BACKUP_FILE}" | cut -f1)
    echo "[$(date)] Backup size: ${SIZE}"
else
    echo "[$(date)] ERROR: Backup failed!"
    exit 1
fi

# 清理30天前的备份
find ${BACKUP_DIR} -name "merak_ide_*.sql.gz" -mtime +30 -delete
REMAINING=$(ls -1 ${BACKUP_DIR}/merak_ide_*.sql.gz 2>/dev/null | wc -l)
echo "[$(date)] Cleanup done. ${REMAINING} backups remaining."
