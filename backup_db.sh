#!/bin/bash
# ============================================================
# DB 백업 스크립트
# tenders.db를 안전하게(SQLite 백업 API로 일관성 있게) 스냅샷 뜬 뒤
# 압축해서 전용 Git 브랜치(db-backup)에 매번 덮어쓰기(force-push)로 저장한다.
#
# 중요: git plumbing 명령만 사용해 현재 작업 디렉토리/브랜치를 전혀 건드리지 않는다.
# (scheduler.py가 실행 중에도 자체적으로 git pull/push를 수행하므로,
#  이 스크립트가 `git checkout`으로 브랜치를 전환하면 그 사이에 충돌·손상 위험이 있음)
#
# 히스토리를 쌓지 않고 항상 "최신 백업 1개"만 유지 → 저장소 용량 걱정 없음.
#
# 사용법: cron 등으로 하루 1회 실행
#   0 3 * * * /app/backup_db.sh >> /app/logs/backup.log 2>&1
# ============================================================
set -e

cd "$(dirname "$0")"

DB_PATH="data/tenders.db"
BACKUP_FILE="/tmp/tenders_backup_$$.db"
GZ_FILE="/tmp/tenders_backup_$$.db.gz"
BRANCH="db-backup"

if [ ! -f "$DB_PATH" ]; then
    echo "[백업] DB 파일 없음 - 건너뜀"
    exit 0
fi

echo "[백업] 시작: $(date)"

# SQLite 자체 백업 API 사용 — 크롤링 중 쓰기 작업이 있어도 안전하게 일관된 스냅샷 확보
python3 -c "
import sqlite3
src = sqlite3.connect('$DB_PATH')
dst = sqlite3.connect('$BACKUP_FILE')
src.backup(dst)
src.close()
dst.close()
"

gzip -f "$BACKUP_FILE"
echo "[백업] 압축 완료: $(du -h $GZ_FILE | cut -f1)"

# ── 작업 디렉토리를 전혀 건드리지 않는 git plumbing 방식으로 커밋 생성 ──
BLOB_SHA=$(git hash-object -w "$GZ_FILE")
TREE_SHA=$(printf "100644 blob %s\ttenders_backup.db.gz\n" "$BLOB_SHA" | git mktree)
COMMIT_SHA=$(git commit-tree "$TREE_SHA" -m "backup: $(date '+%Y-%m-%d %H:%M')")

git push origin "${COMMIT_SHA}:refs/heads/${BRANCH}" --force

rm -f "$BACKUP_FILE" "$GZ_FILE"
echo "[백업] 완료: $(date) (브랜치: $BRANCH)"
