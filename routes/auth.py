import os
import random
import string
from datetime import datetime, timedelta

from flask import (Blueprint, render_template, request, jsonify,
                   session, redirect, g, url_for, current_app)
from werkzeug.security import check_password_hash, generate_password_hash
from database import db, User
from decorators import login_required

bp = Blueprint('auth', __name__)


def _build_callback_url(endpoint: str) -> str:
    """접속한 호스트·스킴에 맞는 OAuth 콜백 URL을 동적 생성.

    Cloudflare(또는 nginx) 뒤에 있을 때도 올바른 도메인/프로토콜을 사용:
      - X-Forwarded-Proto: https  → scheme = https
      - X-Forwarded-Host / Host   → 실제 도메인 (예: ht-search.com)
    로컬 직접 접속 시: http://localhost:5002/...
    """
    # 1) 스킴: 프록시가 보낸 X-Forwarded-Proto 우선, 없으면 request.scheme
    proto = (request.headers.get('X-Forwarded-Proto')
             or request.headers.get('CF-Visitor')  # Cloudflare 보조
             or request.scheme)
    # CF-Visitor는 JSON 형태("{"scheme":"https"}") 이므로 간단 파싱
    if '{' in proto:
        import json as _j
        try:
            proto = _j.loads(proto).get('scheme', 'https')
        except Exception:
            proto = 'https'

    # 2) 호스트: X-Forwarded-Host 우선, 없으면 Host 헤더(=request.host)
    host = (request.headers.get('X-Forwarded-Host') or request.host)

    # 3) 경로만 url_for로 가져오기 (_external=False)
    path = url_for(endpoint)

    return f"{proto}://{host}{path}"


@bp.route('/me')
@login_required
def my_profile():
    """내 계정 정보 페이지 — 모든 로그인 사용자 접근 가능"""
    success = request.args.get('success')
    error = request.args.get('error')
    return render_template('me.html', success=success, error=error)


@bp.route('/register')
def register_page():
    if g.user:
        return redirect('/')
    return render_template('register.html')


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
                # 소셜 연동 대기 중이면 자동 연결
                pending_social = session.pop('pending_social', None)
                if pending_social:
                    provider = pending_social.get('provider')
                    social_id = pending_social.get('id')
                    if provider == 'google' and not user.google_id:
                        user.google_id = social_id
                    elif provider == 'kakao' and not user.kakao_id:
                        user.kakao_id = social_id
                    elif provider == 'naver' and not user.naver_id:
                        user.naver_id = social_id
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
    elif url_error == 'session_expired':
        error = '1시간 동안 활동이 없어 자동 로그아웃되었습니다.'
    return render_template('login.html', error=error, next=request.args.get('next', '/'))


@bp.route('/logout')
def logout():
    session.clear()
    return redirect('/login')


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

    # 소셜 연동 대기 중이면 함께 저장
    pending_social = session.pop('pending_social', None)
    google_id = None
    kakao_id = None
    naver_id = None
    if pending_social:
        if pending_social.get('provider') == 'google':
            google_id = pending_social.get('id')
        elif pending_social.get('provider') == 'kakao':
            kakao_id = pending_social.get('id')
        elif pending_social.get('provider') == 'naver':
            naver_id = pending_social.get('id')

    user = User(
        username=username,
        password_hash=generate_password_hash(password),
        email=email,
        nickname=nickname,
        status='pending',
        google_id=google_id,
        kakao_id=kakao_id,
        naver_id=naver_id,
    )
    db.session.add(user)
    db.session.commit()
    return jsonify({'message': '가입 신청이 완료되었습니다. 관리자 승인 후 로그인하실 수 있습니다.'}), 201


@bp.route('/api/me/nickname', methods=['POST'])
@login_required
def api_change_my_nickname():
    """본인 닉네임 변경"""
    data = request.json or {}
    nickname = (data.get('nickname') or '').strip() or None
    g.user.nickname = nickname
    db.session.commit()
    return jsonify({'message': '닉네임이 변경되었습니다.'})


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


# ── Kakao OAuth ───────────────────────────────────────────────────────────────

@bp.route('/auth/kakao')
def auth_kakao():
    """카카오 OAuth 로그인 시작. ?link=1 이면 기존 계정에 카카오 연결."""
    link_mode = request.args.get('link') == '1'
    if link_mode and not g.user:
        return redirect('/login')
    session.pop('pending_social', None)  # 이전 소셜 연동 대기 데이터 초기화
    session['oauth_link'] = link_mode
    redirect_uri = _build_callback_url('auth.auth_kakao_callback')
    return current_app.extensions['oauth'].kakao.authorize_redirect(redirect_uri)


@bp.route('/auth/kakao/callback')
def auth_kakao_callback():
    """카카오 OAuth 콜백"""
    try:
        token = current_app.extensions['oauth'].kakao.authorize_access_token()
    except Exception as e:
        import traceback
        print('[카카오 콜백 오류 - 토큰 교환]', str(e))
        traceback.print_exc()
        return redirect('/login?error=oauth_failed')

    try:
        resp = current_app.extensions['oauth'].kakao.get('v2/user/me', token=token)
        profile = resp.json()
    except Exception as e:
        import traceback
        print('[카카오 콜백 오류 - 사용자 정보]', str(e))
        traceback.print_exc()
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
            return redirect('/me?error=kakao_already_linked')
        g.user.kakao_id = kakao_id
        db.session.commit()
        return redirect('/me?success=kakao_linked')

    # ── 로그인 모드: 이미 연결된 계정 ───────────────────────────────
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

    # ── 연결 계정 없음 → 중간 선택 페이지로 ────────────────────────
    session['pending_social'] = {
        'provider': 'kakao',
        'id': kakao_id,
        'email': email,
        'nickname': nickname,
    }
    return redirect('/auth/social-link')


# ── Google OAuth ──────────────────────────────────────────────────────────────

@bp.route('/auth/google')
def auth_google():
    """구글 OAuth 로그인 시작. ?link=1 이면 기존 계정에 구글 연결."""
    link_mode = request.args.get('link') == '1'
    if link_mode and not g.user:
        return redirect('/login')
    session.pop('pending_social', None)  # 이전 소셜 연동 대기 데이터 초기화
    session['oauth_link_google'] = link_mode
    redirect_uri = _build_callback_url('auth.auth_google_callback')
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
            return redirect('/me?error=google_already_linked')
        g.user.google_id = google_id
        db.session.commit()
        return redirect('/me?success=google_linked')

    # ── 로그인 모드: 이미 연결된 계정 ───────────────────────────────
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

    # ── 연결 계정 없음 → 중간 선택 페이지로 ────────────────────────
    session['pending_social'] = {
        'provider': 'google',
        'id': google_id,
        'email': email,
        'nickname': nickname,
    }
    return redirect('/auth/social-link')


# ── Naver OAuth ──────────────────────────────────────────────────────────────

@bp.route('/auth/naver')
def auth_naver():
    """네이버 OAuth 로그인 시작. ?link=1 이면 기존 계정에 네이버 연결."""
    link_mode = request.args.get('link') == '1'
    if link_mode and not g.user:
        return redirect('/login')
    session.pop('pending_social', None)  # 이전 소셜 연동 대기 데이터 초기화
    session['oauth_link_naver'] = link_mode
    redirect_uri = _build_callback_url('auth.auth_naver_callback')
    return current_app.extensions['oauth'].naver.authorize_redirect(redirect_uri)


@bp.route('/auth/naver/callback')
def auth_naver_callback():
    """네이버 OAuth 콜백"""
    try:
        token = current_app.extensions['oauth'].naver.authorize_access_token()
    except Exception as e:
        import traceback; traceback.print_exc()
        return redirect('/login?error=oauth_failed')

    try:
        resp = current_app.extensions['oauth'].naver.get('me', token=token)
        profile = resp.json().get('response', {})
    except Exception as e:
        import traceback; traceback.print_exc()
        return redirect('/login?error=oauth_failed')

    naver_id = str(profile.get('id', ''))
    if not naver_id:
        return redirect('/login?error=oauth_failed')

    email    = profile.get('email') or None
    nickname = profile.get('nickname') or profile.get('name') or None

    link_mode = session.pop('oauth_link_naver', False)

    # ── 연결 모드 ────────────────────────────────────────────────────
    if link_mode and g.user:
        if User.query.filter(User.naver_id == naver_id, User.id != g.user.id).first():
            return redirect('/me?error=naver_already_linked')
        g.user.naver_id = naver_id
        db.session.commit()
        return redirect('/me?success=naver_linked')

    # ── 로그인 모드: 이미 연결된 계정 ───────────────────────────────
    existing = User.query.filter_by(naver_id=naver_id).first()
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

    # ── 연결 계정 없음 → 중간 선택 페이지로 ────────────────────────
    session['pending_social'] = {
        'provider': 'naver',
        'id': naver_id,
        'email': email,
        'nickname': nickname,
    }
    return redirect('/auth/social-link')


# ── 소셜 계정 연결 중간 페이지 ───────────────────────────────────────────────

@bp.route('/auth/social-link')
def auth_social_link():
    """연결된 계정 없음 → 로그인 후 연동 or 신규 가입 선택"""
    if g.user:
        # 이미 로그인된 상태라면 바로 연결
        pending = session.pop('pending_social', None)
        if pending:
            provider = pending.get('provider')
            social_id = pending.get('id')
            if provider == 'google' and not g.user.google_id:
                g.user.google_id = social_id
                db.session.commit()
                return redirect('/me?success=google_linked')
            elif provider == 'kakao' and not g.user.kakao_id:
                g.user.kakao_id = social_id
                db.session.commit()
                return redirect('/me?success=kakao_linked')
            elif provider == 'naver' and not g.user.naver_id:
                g.user.naver_id = social_id
                db.session.commit()
                return redirect('/me?success=naver_linked')
        return redirect('/')

    pending = session.get('pending_social')
    if not pending:
        return redirect('/login')

    provider_map = {'google': '구글', 'kakao': '카카오', 'naver': '네이버'}
    provider_name = provider_map.get(pending.get('provider'), '소셜')
    return render_template('social_link.html',
                           provider=pending.get('provider'),
                           provider_name=provider_name,
                           email=pending.get('email'),
                           nickname=pending.get('nickname'))


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
    session['pending_email'] = new_email
    db.session.commit()

    try:
        from flask_mail import Message
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
        1 if user.naver_id else 0,
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


@bp.route('/api/me/social/naver', methods=['DELETE'])
@login_required
def api_disconnect_naver():
    """네이버 연결 해제"""
    if not g.user.naver_id:
        return jsonify({'error': '네이버가 연결되어 있지 않습니다.'}), 400
    ok, msg = _can_disconnect_social(g.user)
    if not ok:
        return jsonify({'error': msg}), 400
    g.user.naver_id = None
    db.session.commit()
    return jsonify({'message': '네이버 연결이 해제되었습니다.'})
