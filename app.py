from settings_manager import settings_manager
from data_manager import DataManager
from flask import Flask, jsonify, g
from flask_cors import CORS
from config import Config
from database import db, init_db
from decorators import _current_user
from datetime import datetime, timedelta

app = Flask(__name__)
app.config.from_object(Config)
app.secret_key = settings_manager.get('secret_key') or 'change-me-in-production-please'
app.permanent_session_lifetime = timedelta(days=7)


def _parse_g2b_dt(s):
    """G2B API 날짜 문자열을 datetime으로 파싱"""
    if not s:
        return None
    s = str(s).strip()
    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y%m%d%H%M%S', '%Y%m%d%H%M', '%Y%m%d'):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            pass
    return None


app.jinja_env.globals['now'] = datetime.now
app.jinja_env.globals['parse_g2b_dt'] = _parse_g2b_dt


@app.after_request
def add_no_cache_headers(response):
    if 'text/html' in response.content_type:
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        response.headers['Pragma'] = 'no-cache'
    return response


@app.before_request
def _load_user():
    g.user = _current_user()


@app.template_filter('format_price')
def format_price_filter(price):
    """금액을 한글 단위로 표현: 8억 4천만원, 7억 6천 3백 63만원 등"""
    if not price:
        return '미정'
    price = int(price)
    if price <= 0:
        return '0원'

    eok = price // 100_000_000
    man = (price % 100_000_000) // 10_000

    def _man_str(m):
        """만 단위 숫자를 한글 단위 문자열로 변환. 예: 4000→4천, 7200→7천 2백, 6363→6천 3백 63"""
        cheon = m // 1000
        baek  = (m % 1000) // 100
        sub   = m % 100        # 십·일 자리를 숫자로 그대로 표기
        parts = []
        if cheon: parts.append(f'{cheon}천')
        if baek:  parts.append(f'{baek}백')
        if sub:   parts.append(str(sub))
        return ' '.join(parts) + '만'

    if eok > 0:
        if man == 0:
            return f'{eok}억원'
        return f'{eok}억 {_man_str(man)}원'
    elif man > 0:
        return _man_str(man) + '원'
    else:
        return f'{price:,}원'


@app.errorhandler(404)
def not_found(error):
    return jsonify({'error': 'Not found'}), 404


@app.errorhandler(500)
def internal_error(error):
    db.session.rollback()
    return jsonify({'error': 'Internal server error'}), 500


# Initialize extensions
CORS(app)
init_db(app)
app.data_manager = DataManager(app)

# Register blueprints
from routes.auth import bp as auth_bp
from routes.admin import bp as admin_bp
from routes.pages import bp as pages_bp
from routes.tenders import bp as tenders_bp
from routes.bookmarks import bp as bookmarks_bp
from routes.filters import bp as filters_bp
from routes.settings import bp as settings_bp
from routes.data import bp as data_bp
from routes.analysis import bp as analysis_bp

app.register_blueprint(auth_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(pages_bp)
app.register_blueprint(tenders_bp)
app.register_blueprint(bookmarks_bp)
app.register_blueprint(filters_bp)
app.register_blueprint(settings_bp)
app.register_blueprint(data_bp)
app.register_blueprint(analysis_bp)


def _free_port(port: int) -> None:
    """시작 전 해당 포트를 점유한 프로세스를 안전하게 종료한다."""
    import psutil
    import os
    current_pid = os.getpid()
    targets = []
    try:
        for conn in psutil.net_connections(kind='tcp'):
            if conn.laddr.port == port and conn.status == psutil.CONN_LISTEN:
                if conn.pid and conn.pid != current_pid:
                    targets.append(conn.pid)
    except (psutil.AccessDenied, AttributeError):
        pass

    for pid in set(targets):
        try:
            proc = psutil.Process(pid)
            print(f"[서버] 포트 {port} 점유 프로세스(PID {pid}: {proc.name()}) 종료 중...")
            proc.terminate()          # SIGTERM → 정상 종료 시도
            proc.wait(timeout=5)
        except psutil.NoSuchProcess:
            pass
        except psutil.TimeoutExpired:
            try:
                proc.kill()           # 응답 없으면 SIGKILL
                proc.wait(timeout=3)
            except psutil.NoSuchProcess:
                pass
        except psutil.AccessDenied:
            print(f"[서버] PID {pid} 종료 권한 없음 — 다른 포트를 사용하거나 관리자로 실행하세요.")


if __name__ == '__main__':
    print("=" * 50)
    print("입찰공고 통합 검색 시스템 시작")
    print(f"서버 주소: http://localhost:{Config.PORT}")
    print("=" * 50)

    # 포트 점유 프로세스 정리 (좀비 소켓 방지)
    _free_port(Config.PORT)

    # 설정 파일 로드
    settings_manager.load_settings()

    crawler_scheduler = None
    # 스케줄러 시작
    if Config.AUTO_CRAWL_ENABLED:
        try:
            from scheduler import CrawlScheduler
            crawler_scheduler = CrawlScheduler(app)
            crawler_scheduler.start()
        except Exception as e:
            import traceback
            print(f"[스케줄러] 초기화 실패 — 크롤링 기능이 비활성화됩니다.")
            print(f"[스케줄러] 오류: {e}")
            traceback.print_exc()

    try:
        from waitress import serve
        print(f"[서버] waitress WSGI 서버로 시작합니다 (port {Config.PORT})")
        serve(app, host=Config.HOST, port=Config.PORT, threads=8,
              connection_limit=200, cleanup_interval=30, channel_timeout=120)
    except ImportError:
        print("[서버] waitress 미설치 — Flask 개발 서버로 폴백합니다")
        app.run(host=Config.HOST, port=Config.PORT, debug=False,
                threaded=True, use_reloader=False)
    finally:
        # 서버 종료 시 스케줄러도 중지
        if crawler_scheduler:
            crawler_scheduler.stop()
