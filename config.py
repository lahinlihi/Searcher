import os

# Base directory
BASE_DIR = os.path.abspath(os.path.dirname(__file__))

# Flask configuration


class Config:
    # Flask
    SECRET_KEY = os.environ.get(
        'SECRET_KEY') or 'dev-secret-key-change-in-production'
    DEBUG = False  # 디버그 모드 비활성화 (스케줄러와 충돌 방지)

    # Server
    HOST = '0.0.0.0'
    PORT = 5002

    # Database
    SQLALCHEMY_DATABASE_URI = f'sqlite:///{
        os.path.join(
            BASE_DIR,
            "data",
            "tenders.db")}'
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Scheduler
    SCHEDULER_API_ENABLED = True
    SCHEDULER_TIMEZONE = 'Asia/Seoul'

    # Crawling
    CRAWL_TIMES = ['09:00', '17:00']  # 자동 크롤링 시간
    AUTO_CRAWL_ENABLED = True  # 자동 크롤링 활성화
    CRAWL_TIMEOUT = 300  # 5분

    # Data retention
    DATA_RETENTION_DAYS = 30  # 30일 이상 오래된 공고 삭제

    # Pagination
    ITEMS_PER_PAGE = 20

    # Export
    EXCEL_MAX_ROWS = 10000

    # Site URLs (크롤링 대상)
    CRAWL_SITES = {
        'g2b': {
            'name': '나라장터',
            'url': 'http://www.g2b.go.kr',
            'enabled': True
        },
        'lh': {
            'name': 'LH',
            'url': 'https://www.lh.or.kr',
            'enabled': True
        },
        'kepco': {
            'name': '한국전력',
            'url': 'https://srm.kepco.net',
            'enabled': True
        },
        # 추가 사이트는 나중에 구현
    }

    # Filter defaults
    DEFAULT_FILTER = {
        'include_keywords': ['AI', '웹개발', '소프트웨어'],
        'exclude_keywords': ['철거', '폐기물', '청소'],
        'regions': ['서울', '경기'],
        'min_price': 10000000,  # 1천만원
        'max_price': 500000000,  # 5억원
        'days_before_deadline': 15
    }

    # Notification
    EMAIL_ENABLED = False
    EMAIL_ADDRESS = ''

    # Selenium
    SELENIUM_HEADLESS = True
    SELENIUM_TIMEOUT = 30
