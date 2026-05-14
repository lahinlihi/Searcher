from functools import wraps
from flask import g, request, session, jsonify, redirect, url_for, render_template
from database import User


def _current_user():
    uid = session.get('user_id')
    if uid is None:
        return None
    return User.query.get(uid)


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if g.user is None:
            if request.is_json or request.path.startswith('/api/'):
                return jsonify({'error': '로그인이 필요합니다.', 'redirect': '/login'}), 401
            return redirect(url_for('auth.login_page', next=request.full_path))
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if g.user is None:
            if request.is_json or request.path.startswith('/api/'):
                return jsonify({'error': '로그인이 필요합니다.', 'redirect': '/login'}), 401
            return redirect(url_for('auth.login_page', next=request.full_path))
        if g.user.role != 'admin':
            if request.is_json or request.path.startswith('/api/'):
                return jsonify({'error': '관리자 권한이 필요합니다.'}), 403
            return render_template('403.html'), 403
        return f(*args, **kwargs)
    return decorated


def moderator_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if g.user is None:
            if request.is_json or request.path.startswith('/api/'):
                return jsonify({'error': '로그인이 필요합니다.', 'redirect': '/login'}), 401
            return redirect(url_for('auth.login_page', next=request.full_path))
        if g.user.role not in ('admin', 'moderator'):
            if request.is_json or request.path.startswith('/api/'):
                return jsonify({'error': '접근 권한이 없습니다.'}), 403
            return render_template('403.html'), 403
        return f(*args, **kwargs)
    return decorated
