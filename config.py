import os

# Base directory
BASE_DIR = os.path.abspath(os.path.dirname(__file__))

# Flask configuration


class Config:
    # Flask
    SECRET_KEY = os.environ.get(
        'SECRET_KEY') or 'dev-secret-key-change-in-production'
    DEBUG = False  # 디버그 모드 비활성화 (스케줄러와 충돌 방지)
    TEMPLATES_AUTO_RELOAD = True  # 템플릿 변경 즉시 반영 (서버 재시작 불필요)

    # Server
    HOST = '0.0.0.0'
    PORT = 5002

    # Database
    _DB_PATH = os.path.join(BASE_DIR, "data", "tenders.db")
    SQLALCHEMY_DATABASE_URI = f'sqlite:///{_DB_PATH}'
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Crawling
    AUTO_CRAWL_ENABLED = True  # 자동 크롤링 활성화

    # Pagination
    ITEMS_PER_PAGE = 20
