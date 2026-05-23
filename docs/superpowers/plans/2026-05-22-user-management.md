# 회원관리 시스템 확장 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 셀프 회원가입(관리자 승인), 카카오·구글 소셜로그인, 접속 모니터링, 이메일 인증, 소셜 연결/해제 기능을 Searcher 앱에 추가한다.

**Architecture:** 기존 `User` 모델에 컬럼을 추가하고, `routes/auth.py`에 등록/OAuth 엔드포인트를 붙이고, `routes/admin.py`에 승인/거절 API를 추가한다. authlib OAuth 2.0 라이브러리가 Kakao·Google 인증을 처리하며, Flask-Mail이 이메일 인증 코드를 발송한다.

**Tech Stack:** Flask 3.0, SQLAlchemy 2.x (SQLite), authlib, flask-mail, python-dotenv, Jinja2, Tailwind CDN

---

## Critical Files

- `C:\Users\USER\Searcher\database.py` — User 모델 확장
- `C:\Users\USER\Searcher\routes\auth.py` — 등록·로그인·OAuth·이메일인증 API
- `C:\Users\USER\Searcher\routes\admin.py` — 승인/거절/배지 API
- `C:\Users\USER\Searcher\app.py` — dotenv 로드, Flask-Mail·OAuth 초기화
- `C:\Users\USER\Searcher\templates\login.html` — 소셜 버튼 + 회원가입 링크
- `C:\Users\USER\Searcher\templates\register.html` — 신규 생성
- `C:\Users\USER\Searcher\templates\admin_users.html` — 승인 대기 탭 + 컬럼 추가
- `C:\Users\USER\Searcher\templates\settings.html` — 소셜 연결/해제 + 이메일 변경
- `C:\Users\USER\Searcher\requirements.txt` — authlib, flask-mail, python-dotenv 추가
- `C:\Users\USER\Searcher\.env` — 소셜 API 키 (신규)
- `C:\Users\USER\Searcher\.env.example` — 키 템플릿 (신규, git 추가)

---

## Task 1: 의존성 설치 및 .env 파일 준비

**Files:**
- Modify: `C:\Users\USER\Searcher\requirements.txt`
- Create: `C:\Users\USER\Searcher\.env`
- Create: `C:\Users\USER\Searcher\.env.example`

- [ ] requirements.txt에 새 의존성 추가 (기존 내용 뒤에 append):
```
authlib>=1.3.0
flask-mail>=0.10.0
python-dotenv>=1.0.0
```

- [ ] `.env` 파일 생성 (실제 API 키는 운영자가 채워 넣을 자리 표시자):
```env
# 소셜 로그인 — Kakao
KAKAO_CLIENT_ID=여기에_카카오_REST_API_키
KAKAO_REDIRECT_URI=http://localhost:5002/auth/kakao/callback

# 소셜 로그인 — Google
GOOGLE_CLIENT_ID=여기에_구글_클라이언트_ID
GOOGLE_CLIENT_SECRET=여기에_구글_보안_비밀
GOOGLE_REDIRECT_URI=http://localhost:5002/auth/google/callback

# 이메일 인증 (선택 — 미설정 시 이메일 인증 기능 비활성)
MAIL_SERVER=smtp.gmail.com
MAIL_PORT=587
MAIL_USERNAME=your@gmail.com
MAIL_PASSWORD=gmail_app_password
```

- [ ] `.env.example` 파일 생성 (동일 내용, 값만 공백):
```env
KAKAO_CLIENT_ID=
KAKAO_REDIRECT_URI=http://localhost:5002/auth/kakao/callback

GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
GOOGLE_REDIRECT_URI=http://localhost:5002/auth/google/callback

MAIL_SERVER=smtp.gmail.com
MAIL_PORT=587
MAIL_USERNAME=
MAIL_PASSWORD=
```

- [ ] `.gitignore` 에 `.env` 가 있는지 확인:
```bash
grep -n "\.env" C:/Users/USER/Searcher/.gitignore
```
없으면 추가:
```
.env
```

- [ ] 패키지 설치:
```bash
cd C:/Users/USER/Searcher && pip install authlib flask-mail python-dotenv
```
Expected: `Successfully installed authlib-... flask-mail-... python-dotenv-...`

---

## Task 2: database.py — User 모델 확장 + to_dict() 업데이트

**Files:**
- Modify: `C:\Users\USER\Searcher\database.py`

현재 User 모델 (319–343행):
```python
class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(20), default='user')
    nickname = db.Column(db.String(80), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
```

- [ ] `database.py`의 `class User` 정의를 아래 전체로 교체:

```python
class User(db.Model):
    """사용자 테이블"""
    __tablename__ = 'users'

    id             = db.Column(db.Integer, primary_key=True)
    username       = db.Column(db.String(80), unique=True, nullable=False)
    password_hash  = db.Column(db.String(200), nullable=True)   # 소셜 전용 계정은 NULL
    role           = db.Column(db.String(20), default='user')   # 'admin'|'moderator'|'user'
    nickname       = db.Column(db.String(80), nullable=True)
    created_at     = db.Column(db.DateTime, default=datetime.utcnow)

    # ── 신규 필드 ─────────────────────────────────────────────────
    email               = db.Column(db.String(120), unique=True, nullable=True)
    status              = db.Column(db.String(20), default='active')  # 'pending'|'active'|'suspended'
    last_login_at       = db.Column(db.DateTime, nullable=True)

    # 소셜 로그인 연결
    kakao_id            = db.Column(db.String(100), unique=True, nullable=True)
    google_id           = db.Column(db.String(100), unique=True, nullable=True)

    # 이메일 인증 (임시 저장)
    email_verify_code   = db.Column(db.String(10), nullable=True)
    email_verify_expiry = db.Column(db.DateTime, nullable=True)

    @property
    def display_name(self):
        """닉네임이 있으면 닉네임, 없으면 아이디"""
        return self.nickname or self.username

    def to_dict(self):
        return {
            'id': self.id,
            'username': self.username,
            'nickname': self.nickname or '',
            'display_name': self.display_name,
            'role': self.role,
            'email': self.email or '',
            'status': self.status or 'active',
            'last_login_at': self.last_login_at.isoformat() if self.last_login_at else None,
            'has_password': self.password_hash is not None,
            'has_kakao': self.kakao_id is not None,
            'has_google': self.google_id is not None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
```

---

## Task 3: DB 마이그레이션 스크립트 실행

기존 SQLite DB에 새 컬럼을 추가하고, `password_hash` NOT NULL 제약을 제거하며, 기존 사용자를 `status='active'`로 설정한다.

**Files:**
- Run: one-shot Python script

- [ ] 마이그레이션 실행 (프로젝트 루트에서):
```bash
cd C:/Users/USER/Searcher
python -c "
import sys; sys.stdout.reconfigure(encoding='utf-8')
from app import app
from database import db
import sqlalchemy as sa

with app.app_context():
    insp = sa.inspect(db.engine)
    existing_cols = [c['name'] for c in insp.get_columns('users')]
    print('기존 컬럼:', existing_cols)

    new_cols = [
        ('email',               \"TEXT\"),
        ('status',              \"TEXT DEFAULT 'active'\"),
        ('last_login_at',       'DATETIME'),
        ('kakao_id',            'TEXT'),
        ('google_id',           'TEXT'),
        ('email_verify_code',   'TEXT'),
        ('email_verify_expiry', 'DATETIME'),
    ]

    with db.engine.connect() as conn:
        for col_name, col_def in new_cols:
            if col_name not in existing_cols:
                conn.execute(sa.text(f'ALTER TABLE users ADD COLUMN {col_name} {col_def}'))
                print(f'  추가: {col_name}')
            else:
                print(f'  이미 존재: {col_name}')

        # 기존 사용자 status 보정 (NULL → active)
        result = conn.execute(sa.text(\"UPDATE users SET status='active' WHERE status IS NULL\"))
        print(f'  status=active 업데이트: {result.rowcount}건')
        conn.commit()

    print('마이그레이션 완료')
"
```

Expected output:
```
기존 컬럼: ['id', 'username', 'password_hash', 'role', 'nickname', 'created_at']
  추가: email
  추가: status
  추가: last_login_at
  추가: kakao_id
  추가: google_id
  추가: email_verify_code
  추가: email_verify_expiry
  status=active 업데이트: N건
마이그레이션 완료
```

- [ ] 결과 확인:
```bash
cd C:/Users/USER/Searcher
python -c "
import sys; sys.stdout.reconfigure(encoding='utf-8')
from app import app
from database import db, User
import sqlalchemy as sa
with app.app_context():
    cols = [c['name'] for c in sa.inspect(db.engine).get_columns('users')]
    print('최종 컬럼:', cols)
    cnt = User.query.count()
    active = User.query.filter_by(status='active').count()
    print(f'전체 {cnt}명, active {active}명')
"
```

---

## Task 4: app.py — dotenv 로드 및 Flask-Mail 초기화

**Files:**
- Modify: `C:\Users\USER\Searcher\app.py`

- [ ] `app.py` 최상단 import 블록 직후에 dotenv 로드 추가 (현재 1행 `from settings_manager ...` 직전에 삽입):

```python
import os
from dotenv import load_dotenv
load_dotenv()   # .env 파일 로드 (없으면 조용히 무시)
```

- [ ] Flask-Mail 초기화 코드를 `init_db(app)` 줄 바로 뒤에 추가:

```python
# Flask-Mail 초기화 (MAIL_SERVER 환경변수 있을 때만 활성)
from flask_mail import Mail
app.config['MAIL_SERVER']   = os.environ.get('MAIL_SERVER', '')
app.config['MAIL_PORT']     = int(os.environ.get('MAIL_PORT', 587))
app.config['MAIL_USE_TLS']  = True
app.config['MAIL_USERNAME'] = os.environ.get('MAIL_USERNAME', '')
app.config['MAIL_PASSWORD'] = os.environ.get('MAIL_PASSWORD', '')
app.config['MAIL_DEFAULT_SENDER'] = os.environ.get('MAIL_USERNAME', '')
mail = Mail(app)
app.extensions['mail'] = mail   # 다른 모듈에서 current_app.extensions['mail']로 접근
```

- [ ] authlib OAuth 초기화 — blueprint import 블록 바로 앞에 삽입:

```python
# OAuth 초기화 (authlib)
from authlib.integrations.flask_client import OAuth
oauth = OAuth(app)

oauth.register(
    name='kakao',
    client_id=os.environ.get('KAKAO_CLIENT_ID', ''),
    client_kwargs={'scope': 'profile_nickname profile_image account_email'},
    access_token_url='https://kauth.kakao.com/oauth/token',
    authorize_url='https://kauth.kakao.com/oauth/authorize',
    api_base_url='https://kapi.kakao.com/',
)

oauth.register(
    name='google',
    client_id=os.environ.get('GOOGLE_CLIENT_ID', ''),
    client_secret=os.environ.get('GOOGLE_CLIENT_SECRET', ''),
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={'scope': 'openid email profile'},
)

app.extensions['oauth'] = oauth
```

---

## Task 5: routes/auth.py — 로그인 업데이트 + 셀프 회원가입 API

**Files:**
- Modify: `C:\Users\USER\Searcher\routes\auth.py`

### 5-1. import 블록 교체

현재 auth.py 상단(1–6행)을 아래로 교체:

```python
import os
import random
import string
from datetime import datetime, timedelta

from flask import (Blueprint, render_template, request, jsonify,
                   session, redirect, g, url_for, current_app)
from werkzeug.security import check_password_hash, generate_password_hash
from flask_mail import Message
from database import db, User
from decorators import login_required

bp = Blueprint('auth', __name__)
```

### 5-2. 로그인 엔드포인트 — status 체크 + last_login_at 갱신

`login_page()` 함수에서 로그인 성공 분기를 수정:

```python
@bp.route('/login', methods=['GET', 'POST'])
def login_page():
    if g.user:
        return redirect('/')
    error = None
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        user = User.query.filter_by(username=username).first()
        # password_hash가 NULL인 경우(소셜 전용 계정)는 비밀번호 로그인 불가
        if user and user.password_hash and check_password_hash(user.password_hash, password):
            if user.status == 'pending':
                error = '계정 승인 대기 중입니다. 관리자 승인 후 이용하실 수 있습니다.'
            elif user.status == 'suspended':
                error = '계정이 정지되었습니다. 관리자에게 문의하세요.'
            else:
                user.last_login_at = datetime.utcnow()
                db.session.commit()
                session.permanent = True
                session['user_id'] = user.id
                session['role'] = user.role
                next_url = request.form.get('next') or request.args.get('next') or '/'
                return redirect(next_url)
        else:
            error = '아이디 또는 비밀번호가 올바르지 않습니다.'
    # URL 파라미터로 오는 오류 메시지 처리
    url_error = request.args.get('error')
    if url_error == 'pending':
        error = '계정 승인 대기 중입니다. 관리자 승인 후 이용하실 수 있습니다.'
    elif url_error == 'suspended':
        error = '계정이 정지되었습니다.'
    elif url_error == 'oauth_failed':
        error = '소셜 로그인 중 오류가 발생했습니다. 다시 시도해주세요.'
    return render_template('login.html', error=error, next=request.args.get('next', '/'))
```

### 5-3. 셀프 회원가입 API

기존 `api_change_my_password` 함수 바로 앞에 삽입:

```python
@bp.route('/api/register', methods=['POST'])
def api_register():
    """셀프 회원가입 신청 — 관리자 승인 후 활성화"""
    data = request.json or {}
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()
    email = (data.get('email') or '').strip() or None
    nickname = (data.get('nickname') or '').strip() or None

    if not username or not password:
        return jsonify({'error': '아이디와 비밀번호를 입력하세요.'}), 400
    if len(password) < 8:
        return jsonify({'error': '비밀번호는 8자 이상이어야 합니다.'}), 400
    if len(username) < 3:
        return jsonify({'error': '아이디는 3자 이상이어야 합니다.'}), 400
    if User.query.filter_by(username=username).first():
        return jsonify({'error': '이미 사용 중인 아이디입니다.'}), 409
    if email and User.query.filter_by(email=email).first():
        return jsonify({'error': '이미 사용 중인 이메일입니다.'}), 409

    user = User(
        username=username,
        password_hash=generate_password_hash(password),
        email=email,
        nickname=nickname,
        status='pending',
    )
    db.session.add(user)
    db.session.commit()
    return jsonify({'message': '가입 신청이 완료되었습니다. 관리자 승인 후 로그인하실 수 있습니다.'}), 201
```

### 5-4. 비밀번호 변경 — 소셜 전용 계정 허용

`api_change_my_password`를 아래로 교체:

```python
@bp.route('/api/me/password', methods=['POST'])
@login_required
def api_change_my_password():
    """본인 비밀번호 변경. 소셜 전용 계정(password_hash=NULL)은 현재 비밀번호 확인 없이 설정 가능."""
    data = request.json or {}
    new_pw = data.get('new_password', '').strip()
    if len(new_pw) < 8:
        return jsonify({'error': '새 비밀번호는 8자 이상이어야 합니다.'}), 400

    if g.user.password_hash:
        # 일반 계정: 현재 비밀번호 확인 필수
        current = data.get('current_password', '')
        if not check_password_hash(g.user.password_hash, current):
            return jsonify({'error': '현재 비밀번호가 올바르지 않습니다.'}), 400

    g.user.password_hash = generate_password_hash(new_pw)
    db.session.commit()
    return jsonify({'message': '비밀번호가 변경되었습니다.'})
```

---

## Task 6: routes/admin.py — 승인/거절/배지 API + 사용자 목록 업데이트

**Files:**
- Modify: `C:\Users\USER\Searcher\routes\admin.py`

### 6-1. 사용자 목록 — status 파라미터 지원

`api_admin_users()` 함수를 교체:

```python
@bp.route('/api/admin/users', methods=['GET'])
@moderator_required
def api_admin_users():
    """사용자 목록 — ?status=pending|active|all"""
    status_filter = request.args.get('status', 'active')

    if g.user.role == 'admin':
        base_q = User.query
    else:
        base_q = User.query.filter_by(role='user')

    if status_filter == 'pending':
        users = base_q.filter_by(status='pending').order_by(User.created_at).all()
    elif status_filter == 'all':
        users = base_q.order_by(User.created_at).all()
    else:
        users = base_q.filter_by(status='active').order_by(User.created_at).all()

    return jsonify([u.to_dict() for u in users])
```

### 6-2. 승인/거절/배지 API 추가

`admin_users_page()` 라우트 바로 앞에 삽입:

```python
@bp.route('/api/admin/users/pending-count', methods=['GET'])
@moderator_required
def api_admin_pending_count():
    """승인 대기 중인 회원 수"""
    count = User.query.filter_by(status='pending').count()
    return jsonify({'count': count})


@bp.route('/api/admin/users/<int:user_id>/approve', methods=['POST'])
@moderator_required
def api_admin_approve_user(user_id):
    """회원 승인 — pending → active"""
    user = User.query.get_or_404(user_id)
    if user.status != 'pending':
        return jsonify({'error': '승인 대기 중인 계정이 아닙니다.'}), 400
    user.status = 'active'
    db.session.commit()
    return jsonify({'message': f'{user.username} 계정이 승인되었습니다.', 'user': user.to_dict()})


@bp.route('/api/admin/users/<int:user_id>/reject', methods=['POST'])
@moderator_required
def api_admin_reject_user(user_id):
    """회원 거절 — 레코드 삭제"""
    user = User.query.get_or_404(user_id)
    if user.status != 'pending':
        return jsonify({'error': '승인 대기 중인 계정만 거절할 수 있습니다.'}), 400
    username = user.username
    db.session.delete(user)
    db.session.commit()
    return jsonify({'message': f'{username} 가입 신청이 거절되었습니다.'})


@bp.route('/api/admin/users/<int:user_id>/suspend', methods=['POST'])
@moderator_required
def api_admin_suspend_user(user_id):
    """회원 정지/복구 — active ↔ suspended 토글"""
    user = User.query.get_or_404(user_id)
    if g.user.role == 'moderator' and user.role != 'user':
        return jsonify({'error': '권한 없음'}), 403
    if user.id == g.user.id:
        return jsonify({'error': '자기 자신은 정지할 수 없습니다.'}), 400
    user.status = 'suspended' if user.status == 'active' else 'active'
    db.session.commit()
    return jsonify({'message': f'상태가 {user.status}로 변경되었습니다.', 'user': user.to_dict()})
```

---

## Task 7: routes/auth.py — Kakao OAuth

**Files:**
- Modify: `C:\Users\USER\Searcher\routes\auth.py`

`api_change_my_password` 함수 뒤에 아래 코드 블록을 추가:

```python
# ── Kakao OAuth ───────────────────────────────────────────────────────────────

@bp.route('/auth/kakao')
def auth_kakao():
    """카카오 OAuth 로그인 시작. ?link=1 이면 기존 계정에 카카오 연결."""
    link_mode = request.args.get('link') == '1'
    if link_mode and not g.user:
        return redirect('/login')
    session['oauth_link'] = link_mode
    redirect_uri = os.environ.get(
        'KAKAO_REDIRECT_URI',
        url_for('auth.auth_kakao_callback', _external=True)
    )
    return current_app.extensions['oauth'].kakao.authorize_redirect(redirect_uri)


@bp.route('/auth/kakao/callback')
def auth_kakao_callback():
    """카카오 OAuth 콜백"""
    try:
        token = current_app.extensions['oauth'].kakao.authorize_access_token()
    except Exception:
        return redirect('/login?error=oauth_failed')

    try:
        resp = current_app.extensions['oauth'].kakao.get('v2/user/me', token=token)
        profile = resp.json()
    except Exception:
        return redirect('/login?error=oauth_failed')

    kakao_id = str(profile.get('id', ''))
    if not kakao_id:
        return redirect('/login?error=oauth_failed')

    kakao_account = profile.get('kakao_account', {})
    email = kakao_account.get('email') or None
    nickname = (kakao_account.get('profile') or {}).get('nickname') or None

    link_mode = session.pop('oauth_link', False)

    # ── 연결 모드: 기존 로그인 계정에 카카오 추가 ──────────────────
    if link_mode and g.user:
        if User.query.filter(User.kakao_id == kakao_id, User.id != g.user.id).first():
            return redirect('/settings?error=kakao_already_linked')
        g.user.kakao_id = kakao_id
        db.session.commit()
        return redirect('/settings?success=kakao_linked')

    # ── 로그인 모드 ──────────────────────────────────────────────────
    existing = User.query.filter_by(kakao_id=kakao_id).first()
    if existing:
        if existing.status == 'pending':
            return redirect('/login?error=pending')
        if existing.status == 'suspended':
            return redirect('/login?error=suspended')
        existing.last_login_at = datetime.utcnow()
        db.session.commit()
        session.permanent = True
        session['user_id'] = existing.id
        session['role'] = existing.role
        return redirect('/')

    # ── 신규 가입 (pending 상태로 생성) ─────────────────────────────
    base_username = f'kakao_{kakao_id}'
    username = base_username
    if User.query.filter_by(username=username).first():
        username = f'{base_username}_{random.randint(1000, 9999)}'

    # 같은 이메일이 이미 있으면 기존 계정에 kakao_id 연결 시도
    if email:
        email_user = User.query.filter_by(email=email).first()
        if email_user and email_user.kakao_id is None:
            email_user.kakao_id = kakao_id
            db.session.commit()
            if email_user.status == 'active':
                session.permanent = True
                session['user_id'] = email_user.id
                session['role'] = email_user.role
                return redirect('/')
            return redirect('/login?error=pending')

    new_user = User(
        username=username,
        password_hash=None,
        email=email,
        nickname=nickname,
        kakao_id=kakao_id,
        status='pending',
    )
    db.session.add(new_user)
    db.session.commit()
    return redirect('/login?error=pending')
```

---

## Task 8: routes/auth.py — Google OAuth

**Files:**
- Modify: `C:\Users\USER\Searcher\routes\auth.py`

카카오 콜백 함수 바로 뒤에 추가:

```python
# ── Google OAuth ──────────────────────────────────────────────────────────────

@bp.route('/auth/google')
def auth_google():
    """구글 OAuth 로그인 시작. ?link=1 이면 기존 계정에 구글 연결."""
    link_mode = request.args.get('link') == '1'
    if link_mode and not g.user:
        return redirect('/login')
    session['oauth_link_google'] = link_mode
    redirect_uri = os.environ.get(
        'GOOGLE_REDIRECT_URI',
        url_for('auth.auth_google_callback', _external=True)
    )
    return current_app.extensions['oauth'].google.authorize_redirect(redirect_uri)


@bp.route('/auth/google/callback')
def auth_google_callback():
    """구글 OAuth 콜백"""
    try:
        token = current_app.extensions['oauth'].google.authorize_access_token()
    except Exception:
        return redirect('/login?error=oauth_failed')

    userinfo = token.get('userinfo') or {}
    google_id = userinfo.get('sub', '')
    if not google_id:
        return redirect('/login?error=oauth_failed')

    email = userinfo.get('email') or None
    nickname = userinfo.get('name') or None

    link_mode = session.pop('oauth_link_google', False)

    # ── 연결 모드 ────────────────────────────────────────────────────
    if link_mode and g.user:
        if User.query.filter(User.google_id == google_id, User.id != g.user.id).first():
            return redirect('/settings?error=google_already_linked')
        g.user.google_id = google_id
        db.session.commit()
        return redirect('/settings?success=google_linked')

    # ── 로그인 모드 ──────────────────────────────────────────────────
    existing = User.query.filter_by(google_id=google_id).first()
    if existing:
        if existing.status == 'pending':
            return redirect('/login?error=pending')
        if existing.status == 'suspended':
            return redirect('/login?error=suspended')
        existing.last_login_at = datetime.utcnow()
        db.session.commit()
        session.permanent = True
        session['user_id'] = existing.id
        session['role'] = existing.role
        return redirect('/')

    # ── 신규 가입 ─────────────────────────────────────────────────────
    base_username = f'google_{google_id[:20]}'
    username = base_username
    if User.query.filter_by(username=username).first():
        username = f'{base_username}_{random.randint(1000, 9999)}'

    if email:
        email_user = User.query.filter_by(email=email).first()
        if email_user and email_user.google_id is None:
            email_user.google_id = google_id
            db.session.commit()
            if email_user.status == 'active':
                session.permanent = True
                session['user_id'] = email_user.id
                session['role'] = email_user.role
                return redirect('/')
            return redirect('/login?error=pending')

    new_user = User(
        username=username,
        password_hash=None,
        email=email,
        nickname=nickname,
        google_id=google_id,
        status='pending',
    )
    db.session.add(new_user)
    db.session.commit()
    return redirect('/login?error=pending')
```

---

## Task 9: routes/auth.py — 이메일 인증 + 소셜 연결 해제 API

**Files:**
- Modify: `C:\Users\USER\Searcher\routes\auth.py`

구글 콜백 함수 뒤에 추가:

```python
# ── 이메일 변경 인증 ──────────────────────────────────────────────────────────

@bp.route('/api/me/email/request-verify', methods=['POST'])
@login_required
def api_email_request_verify():
    """새 이메일로 6자리 인증 코드 발송"""
    mail = current_app.extensions.get('mail')
    if not mail or not current_app.config.get('MAIL_SERVER'):
        return jsonify({'error': '이메일 인증 기능이 비활성 상태입니다. 관리자에게 문의하세요.'}), 503

    data = request.json or {}
    new_email = (data.get('email') or '').strip().lower()
    if not new_email or '@' not in new_email:
        return jsonify({'error': '유효한 이메일을 입력하세요.'}), 400
    if User.query.filter(User.email == new_email, User.id != g.user.id).first():
        return jsonify({'error': '이미 사용 중인 이메일입니다.'}), 409

    code = ''.join(random.choices(string.digits, k=6))
    g.user.email_verify_code = code
    g.user.email_verify_expiry = datetime.utcnow() + timedelta(minutes=10)
    # 새 이메일을 임시로 저장 (verify_code와 함께 검증 후 확정)
    session['pending_email'] = new_email
    db.session.commit()

    try:
        msg = Message(
            subject='[HIGH-SEARCH] 이메일 인증 코드',
            recipients=[new_email],
            body=f'인증 코드: {code}\n\n10분 내에 입력해주세요.'
        )
        mail.send(msg)
    except Exception as e:
        return jsonify({'error': f'메일 발송 실패: {str(e)}'}), 500

    return jsonify({'message': f'{new_email}로 인증 코드를 발송했습니다.'})


@bp.route('/api/me/email/confirm', methods=['POST'])
@login_required
def api_email_confirm():
    """인증 코드 확인 후 이메일 확정"""
    data = request.json or {}
    code = (data.get('code') or '').strip()
    new_email = session.get('pending_email', '')

    if not new_email:
        return jsonify({'error': '인증 요청을 먼저 해주세요.'}), 400
    if not g.user.email_verify_code or not g.user.email_verify_expiry:
        return jsonify({'error': '인증 코드가 없습니다. 다시 요청해주세요.'}), 400
    if datetime.utcnow() > g.user.email_verify_expiry:
        g.user.email_verify_code = None
        g.user.email_verify_expiry = None
        db.session.commit()
        return jsonify({'error': '인증 코드가 만료되었습니다. 다시 요청해주세요.'}), 400
    if g.user.email_verify_code != code:
        return jsonify({'error': '인증 코드가 올바르지 않습니다.'}), 400

    g.user.email = new_email
    g.user.email_verify_code = None
    g.user.email_verify_expiry = None
    session.pop('pending_email', None)
    db.session.commit()
    return jsonify({'message': f'이메일이 {new_email}로 변경되었습니다.'})


# ── 소셜 연결 해제 ─────────────────────────────────────────────────────────────

def _can_disconnect_social(user):
    """소셜 해제 가능 여부 확인. 비밀번호 없고 소셜 1개만 연결된 경우 불가."""
    social_count = sum([
        1 if user.kakao_id else 0,
        1 if user.google_id else 0,
    ])
    if user.password_hash is None and social_count <= 1:
        return False, '비밀번호가 없는 계정에서 유일한 소셜 연결은 해제할 수 없습니다. 먼저 비밀번호를 설정하세요.'
    return True, ''


@bp.route('/api/me/social/kakao', methods=['DELETE'])
@login_required
def api_disconnect_kakao():
    """카카오 연결 해제"""
    if not g.user.kakao_id:
        return jsonify({'error': '카카오가 연결되어 있지 않습니다.'}), 400
    ok, msg = _can_disconnect_social(g.user)
    if not ok:
        return jsonify({'error': msg}), 400
    g.user.kakao_id = None
    db.session.commit()
    return jsonify({'message': '카카오 연결이 해제되었습니다.'})


@bp.route('/api/me/social/google', methods=['DELETE'])
@login_required
def api_disconnect_google():
    """구글 연결 해제"""
    if not g.user.google_id:
        return jsonify({'error': '구글이 연결되어 있지 않습니다.'}), 400
    ok, msg = _can_disconnect_social(g.user)
    if not ok:
        return jsonify({'error': msg}), 400
    g.user.google_id = None
    db.session.commit()
    return jsonify({'message': '구글 연결이 해제되었습니다.'})
```

---

## Task 10: templates/register.html — 회원가입 페이지 신규 생성

**Files:**
- Create: `C:\Users\USER\Searcher\templates\register.html`

```html
<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>회원가입 신청 — HIGH-SEARCH</title>
    <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-gray-50 min-h-screen flex items-center justify-center">
    <div class="w-full max-w-sm">
        <div class="text-center mb-8">
            <img src="{{ url_for('static', filename='img/logo.jfif') }}" alt="HIGH-SEARCH" class="h-12 w-auto mx-auto">
            <p class="text-sm text-gray-500 mt-1">회원가입 신청</p>
        </div>
        <div class="bg-white rounded-xl shadow-sm border p-8">
            <div id="msg-box" class="hidden mb-4 px-3 py-2 rounded text-sm"></div>

            <!-- 이메일/비밀번호 가입 폼 -->
            <form id="register-form">
                <div class="mb-4">
                    <label class="block text-sm font-medium text-gray-700 mb-1">아이디 <span class="text-red-500">*</span></label>
                    <input type="text" id="username" required minlength="3"
                           class="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400"
                           placeholder="3자 이상">
                </div>
                <div class="mb-4">
                    <label class="block text-sm font-medium text-gray-700 mb-1">비밀번호 <span class="text-red-500">*</span></label>
                    <input type="password" id="password" required minlength="8"
                           class="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400"
                           placeholder="8자 이상">
                </div>
                <div class="mb-4">
                    <label class="block text-sm font-medium text-gray-700 mb-1">닉네임 <span class="text-gray-400 font-normal">(선택)</span></label>
                    <input type="text" id="nickname"
                           class="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400"
                           placeholder="표시될 이름">
                </div>
                <div class="mb-6">
                    <label class="block text-sm font-medium text-gray-700 mb-1">이메일 <span class="text-gray-400 font-normal">(선택)</span></label>
                    <input type="email" id="email"
                           class="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400"
                           placeholder="example@email.com">
                </div>
                <button type="submit"
                        class="w-full bg-blue-600 hover:bg-blue-700 text-white font-semibold rounded-lg px-4 py-2 text-sm transition-colors">
                    가입 신청
                </button>
            </form>

            <!-- 구분선 -->
            <div class="my-5 flex items-center gap-3">
                <div class="flex-1 border-t border-gray-200"></div>
                <span class="text-xs text-gray-400">또는 소셜로 가입</span>
                <div class="flex-1 border-t border-gray-200"></div>
            </div>

            <!-- 소셜 가입 버튼 -->
            <div class="flex flex-col gap-3">
                <a href="/auth/kakao"
                   class="flex items-center justify-center gap-2 w-full bg-yellow-300 hover:bg-yellow-400 text-gray-900 font-medium rounded-lg px-4 py-2 text-sm transition-colors">
                    <svg class="w-5 h-5" viewBox="0 0 24 24" fill="currentColor"><path d="M12 3C6.477 3 2 6.477 2 11c0 2.899 1.576 5.457 3.984 7.03L5 21l3.29-1.739A10.86 10.86 0 0012 19c5.523 0 10-3.477 10-8S17.523 3 12 3z"/></svg>
                    카카오로 시작하기
                </a>
                <a href="/auth/google"
                   class="flex items-center justify-center gap-2 w-full bg-white hover:bg-gray-50 text-gray-700 font-medium rounded-lg px-4 py-2 text-sm border border-gray-300 transition-colors">
                    <svg class="w-5 h-5" viewBox="0 0 24 24"><path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/><path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/><path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l3.66-2.84z"/><path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/></svg>
                    Google로 시작하기
                </a>
            </div>

            <p class="text-center text-sm text-gray-500 mt-6">
                이미 계정이 있으신가요?
                <a href="/login" class="text-blue-600 hover:underline">로그인</a>
            </p>
            <p class="text-center text-xs text-gray-400 mt-2">
                가입 신청 후 관리자 승인이 필요합니다.
            </p>
        </div>
    </div>
    <script>
    document.getElementById('register-form').addEventListener('submit', async function(e) {
        e.preventDefault();
        const msgBox = document.getElementById('msg-box');
        const btn = e.target.querySelector('button[type=submit]');
        btn.disabled = true;

        const payload = {
            username: document.getElementById('username').value.trim(),
            password: document.getElementById('password').value,
            nickname: document.getElementById('nickname').value.trim() || null,
            email:    document.getElementById('email').value.trim() || null,
        };

        try {
            const res = await fetch('/api/register', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(payload)
            });
            const data = await res.json();
            if (res.ok) {
                msgBox.className = 'mb-4 px-3 py-2 rounded text-sm bg-green-50 border border-green-200 text-green-700';
                msgBox.textContent = data.message;
                msgBox.classList.remove('hidden');
                e.target.reset();
            } else {
                msgBox.className = 'mb-4 px-3 py-2 rounded text-sm bg-red-50 border border-red-200 text-red-700';
                msgBox.textContent = data.error || '오류가 발생했습니다.';
                msgBox.classList.remove('hidden');
            }
        } catch {
            msgBox.className = 'mb-4 px-3 py-2 rounded text-sm bg-red-50 border border-red-200 text-red-700';
            msgBox.textContent = '서버 연결 오류입니다.';
            msgBox.classList.remove('hidden');
        } finally {
            btn.disabled = false;
        }
    });
    </script>
</body>
</html>
```

- [ ] 페이지 라우트 추가 — `routes/auth.py`에 삽입 (login_page 함수 바로 앞):

```python
@bp.route('/register')
def register_page():
    if g.user:
        return redirect('/')
    return render_template('register.html')
```

---

## Task 11: templates/login.html — 소셜 버튼 + 회원가입 링크 추가

**Files:**
- Modify: `C:\Users\USER\Searcher\templates\login.html`

현재 로그인 버튼(`</form>` 끝) 뒤, `</div>` 닫힘 태그 앞에 아래 내용 삽입:

```html
            <!-- 구분선 -->
            <div class="my-5 flex items-center gap-3">
                <div class="flex-1 border-t border-gray-200"></div>
                <span class="text-xs text-gray-400">또는 소셜 로그인</span>
                <div class="flex-1 border-t border-gray-200"></div>
            </div>

            <!-- 소셜 로그인 버튼 -->
            <div class="flex flex-col gap-3">
                <a href="/auth/kakao"
                   class="flex items-center justify-center gap-2 w-full bg-yellow-300 hover:bg-yellow-400 text-gray-900 font-medium rounded-lg px-4 py-2 text-sm transition-colors">
                    <svg class="w-5 h-5" viewBox="0 0 24 24" fill="currentColor"><path d="M12 3C6.477 3 2 6.477 2 11c0 2.899 1.576 5.457 3.984 7.03L5 21l3.29-1.739A10.86 10.86 0 0012 19c5.523 0 10-3.477 10-8S17.523 3 12 3z"/></svg>
                    카카오로 로그인
                </a>
                <a href="/auth/google"
                   class="flex items-center justify-center gap-2 w-full bg-white hover:bg-gray-50 text-gray-700 font-medium rounded-lg px-4 py-2 text-sm border border-gray-300 transition-colors">
                    <svg class="w-5 h-5" viewBox="0 0 24 24"><path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/><path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/><path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l3.66-2.84z"/><path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84z"/></svg>
                    Google로 로그인
                </a>
            </div>

            <p class="text-center text-sm text-gray-500 mt-6">
                계정이 없으신가요?
                <a href="/register" class="text-blue-600 hover:underline">회원가입 신청</a>
            </p>
```

정확한 삽입 위치는 현재 파일의 `</form>` 태그(35행)와 `</div>` (38행) 사이.

---

## Task 12: admin_users.html — 승인 대기 탭 + 접속 모니터링 컬럼 추가

**Files:**
- Modify: `C:\Users\USER\Searcher\templates\admin_users.html`

이 작업은 기존 `admin_users.html` 파일의 JavaScript를 수정해 두 기능을 추가한다:
1. 탭 UI (전체 회원 / 승인 대기) 
2. 사용자 목록 테이블에 최종 접속·소셜 연결·상태 컬럼

- [ ] `admin_users.html`을 Read해서 현재 구조 파악 후, 아래 로직을 기존 JS에 통합:

**탭 전환 + 승인 대기 배지 JS 코드 (기존 JS 블록 내에 추가):**

```javascript
// ── 탭 및 배지 ──────────────────────────────────────────────────
let currentTab = 'active';

async function loadPendingBadge() {
    try {
        const res = await fetch('/api/admin/users/pending-count');
        const data = await res.json();
        const badge = document.getElementById('pending-badge');
        if (badge) {
            badge.textContent = data.count > 0 ? data.count : '';
            badge.classList.toggle('hidden', data.count === 0);
        }
    } catch {}
}

function switchTab(tab) {
    currentTab = tab;
    document.querySelectorAll('[data-tab]').forEach(el => {
        const active = el.dataset.tab === tab;
        el.classList.toggle('border-blue-600', active);
        el.classList.toggle('text-blue-600', active);
        el.classList.toggle('border-transparent', !active);
        el.classList.toggle('text-gray-500', !active);
    });
    loadUsers();
}

// ── 사용자 목록 로드 ──────────────────────────────────────────────
async function loadUsers() {
    const res = await fetch(`/api/admin/users?status=${currentTab}`);
    const users = await res.json();
    renderUsersTable(users);
}

function formatLastLogin(isoStr) {
    if (!isoStr) return '<span class="text-gray-300">미접속</span>';
    const d = new Date(isoStr);
    const now = new Date();
    const diff = Math.floor((now - d) / 1000);
    if (diff < 3600) return `${Math.floor(diff/60)}분 전`;
    if (diff < 86400) return `오늘 ${d.getHours().toString().padStart(2,'0')}:${d.getMinutes().toString().padStart(2,'0')}`;
    const days = Math.floor(diff / 86400);
    if (days < 30) return `${days}일 전`;
    return d.toLocaleDateString('ko-KR');
}

function statusBadge(status) {
    const map = {
        active:    ['bg-green-100 text-green-700', '활성'],
        pending:   ['bg-yellow-100 text-yellow-700', '대기'],
        suspended: ['bg-red-100 text-red-700', '정지'],
    };
    const [cls, label] = map[status] || ['bg-gray-100 text-gray-600', status];
    return `<span class="px-2 py-0.5 rounded-full text-xs font-medium ${cls}">${label}</span>`;
}

function socialIcons(user) {
    let html = '';
    if (user.has_kakao) html += '<span title="카카오" class="text-yellow-500 text-sm">●K</span>';
    if (user.has_google) html += '<span title="구글" class="ml-1 text-blue-500 text-sm">●G</span>';
    return html || '<span class="text-gray-300 text-xs">없음</span>';
}

function pendingActions(user) {
    return `
        <button onclick="approveUser(${user.id})"
                class="text-xs bg-green-500 hover:bg-green-600 text-white px-2 py-1 rounded mr-1">✅ 승인</button>
        <button onclick="rejectUser(${user.id})"
                class="text-xs bg-red-500 hover:bg-red-600 text-white px-2 py-1 rounded">❌ 거절</button>`;
}

async function approveUser(userId) {
    if (!confirm('승인하시겠습니까?')) return;
    const res = await fetch(`/api/admin/users/${userId}/approve`, {method:'POST'});
    const data = await res.json();
    alert(data.message || data.error);
    loadUsers(); loadPendingBadge();
}

async function rejectUser(userId) {
    if (!confirm('거절하면 계정이 삭제됩니다. 계속하시겠습니까?')) return;
    const res = await fetch(`/api/admin/users/${userId}/reject`, {method:'POST'});
    const data = await res.json();
    alert(data.message || data.error);
    loadUsers(); loadPendingBadge();
}

// 페이지 로드 시
loadPendingBadge();
loadUsers();
setInterval(loadPendingBadge, 60000);  // 1분마다 배지 갱신
```

- [ ] 탭 HTML — 기존 회원 목록 테이블 위에 삽입:

```html
<!-- 탭 -->
<div class="flex border-b mb-4">
    <button data-tab="active" onclick="switchTab('active')"
            class="px-4 py-2 text-sm font-medium border-b-2 border-blue-600 text-blue-600 mr-2">
        전체 회원
    </button>
    <button data-tab="pending" onclick="switchTab('pending')"
            class="px-4 py-2 text-sm font-medium border-b-2 border-transparent text-gray-500 relative mr-2">
        승인 대기
        <span id="pending-badge"
              class="hidden absolute -top-1 -right-1 bg-red-500 text-white text-xs rounded-full w-4 h-4 flex items-center justify-center"></span>
    </button>
</div>
```

- [ ] `renderUsersTable()` 함수에서 컬럼 추가 (현재 함수를 찾아 헤더와 행에 아래 컬럼 추가):

헤더에 추가:
```html
<th class="px-4 py-3 text-left text-xs font-medium text-gray-500">최종 접속</th>
<th class="px-4 py-3 text-left text-xs font-medium text-gray-500">소셜</th>
<th class="px-4 py-3 text-left text-xs font-medium text-gray-500">상태</th>
```

행에 추가 (기존 `actions` 컬럼 앞):
```html
<td class="px-4 py-3 text-sm text-gray-600">${formatLastLogin(user.last_login_at)}</td>
<td class="px-4 py-3 text-sm">${socialIcons(user)}</td>
<td class="px-4 py-3">${statusBadge(user.status)}</td>
```

pending 탭일 때는 기존 수정/삭제 버튼 대신 `pendingActions(user)` 렌더링.

---

## Task 13: templates/settings.html — 계정 정보 탭 (소셜 연결/이메일 변경)

**Files:**
- Modify: `C:\Users\USER\Searcher\templates\settings.html`

settings.html에 기존 "닉네임 변경" / "비밀번호 변경" 섹션이 있을 것. 해당 파일을 Read한 뒤, 아래 섹션들을 추가한다.

- [ ] settings.html을 Read해서 현재 구조 파악

- [ ] **이메일 변경 섹션** (메일 서버 설정 있을 때만 표시 — Jinja2 조건부):

```html
{# templates/settings.html 내 계정 정보 탭에 추가 #}

<!-- 이메일 변경 -->
<div class="bg-white rounded-xl border p-6 mb-6">
    <h3 class="text-sm font-semibold text-gray-700 mb-4">이메일 변경</h3>
    <div id="email-section">
        <p class="text-sm text-gray-500 mb-3">현재 이메일: <span id="current-email" class="font-medium">{{ g.user.email or '미설정' }}</span></p>
        <div class="flex gap-2 mb-3">
            <input type="email" id="new-email" placeholder="새 이메일"
                   class="flex-1 border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400">
            <button onclick="requestEmailVerify()"
                    class="bg-blue-600 hover:bg-blue-700 text-white text-sm px-4 py-2 rounded-lg">인증 코드 발송</button>
        </div>
        <div id="verify-code-row" class="hidden flex gap-2">
            <input type="text" id="verify-code" placeholder="6자리 코드" maxlength="6"
                   class="flex-1 border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400">
            <button onclick="confirmEmailVerify()"
                    class="bg-green-600 hover:bg-green-700 text-white text-sm px-4 py-2 rounded-lg">확인</button>
        </div>
        <p id="email-msg" class="text-xs mt-2 hidden"></p>
    </div>
</div>

<!-- 소셜 계정 연결/해제 -->
<div class="bg-white rounded-xl border p-6 mb-6">
    <h3 class="text-sm font-semibold text-gray-700 mb-4">소셜 계정 연결</h3>
    <div class="space-y-3">
        <!-- 카카오 -->
        <div class="flex items-center justify-between">
            <div class="flex items-center gap-2">
                <span class="text-yellow-500 font-bold">K</span>
                <span class="text-sm text-gray-700">카카오</span>
            </div>
            {% if g.user.kakao_id %}
            <button onclick="disconnectSocial('kakao')"
                    class="text-xs bg-gray-100 hover:bg-gray-200 text-gray-700 px-3 py-1 rounded-lg">연결 해제</button>
            {% else %}
            <a href="/auth/kakao?link=1"
               class="text-xs bg-yellow-300 hover:bg-yellow-400 text-gray-900 px-3 py-1 rounded-lg">연결하기</a>
            {% endif %}
        </div>
        <!-- 구글 -->
        <div class="flex items-center justify-between">
            <div class="flex items-center gap-2">
                <span class="text-blue-500 font-bold">G</span>
                <span class="text-sm text-gray-700">Google</span>
            </div>
            {% if g.user.google_id %}
            <button onclick="disconnectSocial('google')"
                    class="text-xs bg-gray-100 hover:bg-gray-200 text-gray-700 px-3 py-1 rounded-lg">연결 해제</button>
            {% else %}
            <a href="/auth/google?link=1"
               class="text-xs bg-white border border-gray-300 hover:bg-gray-50 text-gray-700 px-3 py-1 rounded-lg">연결하기</a>
            {% endif %}
        </div>
    </div>
    <p id="social-msg" class="text-xs mt-3 hidden"></p>
</div>
```

- [ ] **settings.html 하단 `<script>` 블록에 추가:**

```javascript
// ── 이메일 변경 ──────────────────────────────────────────────────
async function requestEmailVerify() {
    const email = document.getElementById('new-email').value.trim();
    if (!email) return;
    const res = await fetch('/api/me/email/request-verify', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({email})
    });
    const data = await res.json();
    const msg = document.getElementById('email-msg');
    msg.className = res.ok ? 'text-xs mt-2 text-green-600' : 'text-xs mt-2 text-red-600';
    msg.textContent = data.message || data.error;
    msg.classList.remove('hidden');
    if (res.ok) document.getElementById('verify-code-row').classList.remove('hidden');
}

async function confirmEmailVerify() {
    const code = document.getElementById('verify-code').value.trim();
    if (!code) return;
    const res = await fetch('/api/me/email/confirm', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({code})
    });
    const data = await res.json();
    const msg = document.getElementById('email-msg');
    msg.className = res.ok ? 'text-xs mt-2 text-green-600' : 'text-xs mt-2 text-red-600';
    msg.textContent = data.message || data.error;
    msg.classList.remove('hidden');
    if (res.ok) {
        document.getElementById('current-email').textContent = document.getElementById('new-email').value.trim();
        document.getElementById('verify-code-row').classList.add('hidden');
    }
}

// ── 소셜 연결 해제 ──────────────────────────────────────────────
async function disconnectSocial(provider) {
    if (!confirm(`${provider} 연결을 해제하시겠습니까?`)) return;
    const res = await fetch(`/api/me/social/${provider}`, {method: 'DELETE'});
    const data = await res.json();
    const msg = document.getElementById('social-msg');
    msg.className = res.ok ? 'text-xs mt-3 text-green-600' : 'text-xs mt-3 text-red-600';
    msg.textContent = data.message || data.error;
    msg.classList.remove('hidden');
    if (res.ok) setTimeout(() => location.reload(), 1000);
}
```

---

## Task 14: 비밀번호 변경 UI — 소셜 전용 계정 처리

settings.html의 비밀번호 변경 섹션에서 `현재 비밀번호` 입력 필드를 Jinja2로 조건부 표시:

```html
{% if g.user.password_hash %}
<div class="mb-4">
    <label class="block text-sm font-medium text-gray-700 mb-1">현재 비밀번호</label>
    <input type="password" id="current-password"
           class="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400">
</div>
{% else %}
<p class="text-xs text-gray-500 mb-4 bg-blue-50 border border-blue-100 rounded p-2">
    소셜 로그인 계정입니다. 비밀번호를 새로 설정할 수 있습니다.
</p>
{% endif %}
```

기존 비밀번호 변경 JS fetch body도 수정:
```javascript
const payload = {new_password: newPw};
const currentPwEl = document.getElementById('current-password');
if (currentPwEl) payload.current_password = currentPwEl.value;
```

---

## Task 15: 서버 재시작 및 전체 검증

**Files:**
- Run: server restart + verification

- [ ] 서버 재시작:
```bash
OLD_PID=$(netstat -ano 2>/dev/null | grep ':5002' | grep LISTENING | awk '{print $NF}' | head -1)
[ -n "$OLD_PID" ] && cmd /c "taskkill /PID $OLD_PID /F"
cd C:/Users/USER/Searcher
nohup python app.py > server_restart.log 2>&1 &
sleep 4
curl -s -o /dev/null -w "%{http_code}" http://localhost:5002/
```
Expected: `302` (로그인 리다이렉트)

- [ ] 서버 로그에 오류 없는지 확인:
```bash
tail -20 C:/Users/USER/Searcher/server_restart.log
```
Expected: Flask 기동 메시지, import 오류 없음

- [ ] 회원가입 API 테스트:
```bash
curl -s -X POST http://localhost:5002/api/register \
  -H "Content-Type: application/json" \
  -d '{"username":"testuser99","password":"password123","email":"test99@example.com"}' | python -c "import sys,json; print(json.dumps(json.load(sys.stdin), ensure_ascii=False, indent=2))"
```
Expected: `{"message": "가입 신청이 완료되었습니다..."}`

- [ ] 승인 대기 수 API 테스트 (관리자 세션 쿠키 필요):
```bash
# 먼저 관리자 로그인으로 쿠키 획득 후
curl -s http://localhost:5002/api/admin/users/pending-count -b cookies.txt
```
Expected: `{"count": 1}`

- [ ] 회원가입 페이지 접근 확인:
```bash
curl -s -o /dev/null -w "%{http_code}" http://localhost:5002/register
```
Expected: `200`

- [ ] 브라우저 검증 시나리오:
  1. `http://localhost:5002/register` 접속 → 가입 폼 + 카카오/구글 버튼 확인
  2. 신규 아이디로 가입 신청 → "관리자 승인 대기" 메시지 확인
  3. 관리자로 로그인 → `/admin/users` → 승인 대기 탭 → 숫자 배지 확인
  4. 승인 버튼 클릭 → 사용자 상태 active 확인
  5. 승인된 아이디로 로그인 → 성공
  6. `/settings` → 소셜 계정 연결 섹션 확인
  7. 회원 목록 테이블에 "최종 접속", "소셜", "상태" 컬럼 확인

---

## 검증 시나리오 (전체)

1. **이메일/비번 가입 → 대기 → 관리자 승인 → 로그인 성공**
2. **카카오 버튼 클릭 → 카카오 인증 → pending 안내** (KAKAO_CLIENT_ID 설정 후 테스트)
3. **구글 버튼 클릭 → 구글 인증 → pending 안내** (GOOGLE_CLIENT_ID 설정 후 테스트)
4. **관리자 승인 후 카카오/구글 재로그인 → 대시보드 진입**
5. **설정 > 소셜 연결 → 기존 계정에 카카오/구글 추가**
6. **소셜 해제 불가 조건** — 비밀번호 없고 소셜 1개일 때 해제 시도 → 오류 메시지
7. **비밀번호 변경** — 일반 계정: 현재 비밀번호 필요 / 소셜 전용: 없이 설정
8. **이메일 변경** — MAIL_SERVER 설정 후 코드 발송 → 코드 입력 → 변경 확인
9. **접속 모니터링** — 로그인 후 관리자 회원 목록에서 "오늘 HH:MM" 형식 최종 접속 확인
