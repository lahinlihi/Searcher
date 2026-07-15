#!/bin/bash
# ============================================================
# 입찰 공고 대시보드 - 리눅스 서버 배포/업데이트 스크립트
#
# 사용법:
#   최초 배포: git clone 후 이 스크립트 실행
#   업데이트:  같은 스크립트 재실행 (git pull → 재빌드 → 재시작)
# ============================================================
set -e

cd "$(dirname "$0")"

echo "===================================================="
echo " 입찰 대시보드 배포/업데이트"
echo "===================================================="

echo "[1/3] 최신 코드 받기 (git pull)..."
git pull --ff-only

echo ""
echo "[2/3] Docker 컨테이너 재빌드 및 재시작..."
docker compose down
docker compose up -d --build

echo ""
echo "[3/3] 상태 확인 (최대 20초 대기)..."
for i in $(seq 1 20); do
    status=$(docker compose ps --format json 2>/dev/null | python3 -c "import sys,json; print(json.loads(sys.stdin.readline()).get('State',''))" 2>/dev/null || echo "")
    if [ "$status" = "running" ]; then
        echo "컨테이너 정상 기동 확인"
        break
    fi
    echo "대기 중... ${i}초"
    sleep 1
done

docker compose ps
echo ""
echo "===================================================="
echo " 배포 완료"
echo "===================================================="
