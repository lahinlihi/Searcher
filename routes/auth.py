from flask import Blueprint, render_template, request, jsonify, session, redirect, g
from werkzeug.security import check_password_hash, generate_password_hash
from database import db, User
from decorators import login_required

bp = Blueprint('auth', __name__)


@bp.route('/login', methods=['GET', 'POST'])
def login_page():
    if g.user:
        return redirect('/')
    error = None
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password_hash, password):
            session.permanent = True
            session['user_id'] = user.id
            session['role'] = user.role
            next_url = request.form.get('next') or request.args.get('next') or '/'
            return redirect(next_url)
        error = '아이디 또는 비밀번호가 올바르지 않습니다.'
    return render_template('login.html', error=error, next=request.args.get('next', '/'))


@bp.route('/logout')
def logout():
    session.clear()
    return redirect('/login')


@bp.route('/api/me/password', methods=['POST'])
@login_required
def api_change_my_password():
    """본인 비밀번호 변경"""
    data = request.json or {}
    current = data.get('current_password', '')
    new_pw = data.get('new_password', '').strip()
    if not check_password_hash(g.user.password_hash, current):
        return jsonify({'error': '현재 비밀번호가 올바르지 않습니다.'}), 400
    if len(new_pw) < 4:
        return jsonify({'error': '새 비밀번호는 4자 이상이어야 합니다.'}), 400
    g.user.password_hash = generate_password_hash(new_pw)
    db.session.commit()
    return jsonify({'message': '비밀번호가 변경되었습니다.'})
