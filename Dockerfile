# ============================================================
# 입찰 공고 대시보드 - Dockerfile
# ============================================================
FROM python:3.11-slim

# 시스템 패키지 (Chrome/Chromium for Selenium + 한국어 폰트)
RUN apt-get update && apt-get install -y --no-install-recommends \
    chromium \
    chromium-driver \
    fonts-noto-cjk \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 작업 디렉토리
WORKDIR /app

# Python 의존성 먼저 설치 (캐시 활용)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 앱 소스 복사 (data/ 제외 - .dockerignore 에서 처리)
COPY . .

# data 디렉토리 생성 (볼륨 마운트 전 빈 폴더 준비)
RUN mkdir -p /app/data /app/logs

# Selenium에서 Chromium 경로 환경변수 설정
ENV CHROME_BIN=/usr/bin/chromium
ENV CHROMEDRIVER_PATH=/usr/bin/chromedriver

# 타임존
ENV TZ=Asia/Seoul

# 포트
EXPOSE 5002

# 서버 실행
CMD ["python", "-u", "app.py"]
