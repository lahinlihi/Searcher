from flask import Blueprint, render_template, request, jsonify, g
from werkzeug.security import generate_password_hash
from database import db, User
from decorators import admin_required, moderator_required

bp = Blueprint('admin', __name__)


def _role_label(role):
    return {'admin': 'Admin', 'moderator': '중간관리자', 'user': '일반회원'}.get(role, role)


@bp.route('/api/admin/users', methods=['GET'])
@moderator_required
def api_admin_users():
    """사용자 목록 — admin: 전체, moderator: user 역할만"""
    if g.user.role == 'admin':
        users = User.query.order_by(User.created_at).all()
    else:
        users = User.query.filter_by(role='user').order_by(User.created_at).all()
    return jsonify([u.to_dict() for u in users])


@bp.route('/api/admin/users', methods=['POST'])
@moderator_required
def api_admin_create_user():
    """사용자 생성 — admin: 모든 역할, moderator: user만"""
    data = request.json or {}
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()
    role = data.get('role', 'user')
    if not username or not password:
        return jsonify({'error': '아이디와 비밀번호를 입력하세요.'}), 400
    if role not in ('admin', 'moderator', 'user'):
        return jsonify({'error': '유효하지 않은 역할입니다.'}), 400
    # 중간관리자는 user만 생성 가능
    if g.user.role == 'moderator' and role != 'user':
        return jsonify({'error': '중간관리자는 일반회원만 생성할 수 있습니다.'}), 403
    if User.query.filter_by(username=username).first():
        return jsonify({'error': '이미 존재하는 아이디입니다.'}), 409
    user = User(username=username, password_hash=generate_password_hash(password), role=role)
    db.session.add(user)
    db.session.commit()
    return jsonify(user.to_dict()), 201


@bp.route('/api/admin/users/<int:user_id>', methods=['DELETE'])
@moderator_required
def api_admin_delete_user(user_id):
    """사용자 삭제 — admin: 모두(마지막 admin 보호), moderator: user만"""
    user = User.query.get_or_404(user_id)
    if user.id == g.user.id:
        return jsonify({'error': '자기 자신은 삭제할 수 없습니다.'}), 400
    # 중간관리자는 user만 삭제 가능
    if g.user.role == 'moderator' and user.role != 'user':
        return jsonify({'error': '중간관리자는 일반회원만 삭제할 수 있습니다.'}), 403
    if user.role == 'admin' and User.query.filter_by(role='admin').count() <= 1:
        return jsonify({'error': '마지막 Admin은 삭제할 수 없습니다.'}), 400
    db.session.delete(user)
    db.session.commit()
    return jsonify({'message': '삭제되었습니다.'})


@bp.route('/api/admin/users/<int:user_id>/password', methods=['POST'])
@moderator_required
def api_admin_change_password(user_id):
    """비밀번호 변경 — admin: 모두, moderator: user만"""
    user = User.query.get_or_404(user_id)
    if g.user.role == 'moderator' and user.role != 'user':
        return jsonify({'error': '중간관리자는 일반회원의 비밀번호만 변경할 수 있습니다.'}), 403
    data = request.json or {}
    new_pw = data.get('password', '').strip()
    if len(new_pw) < 4:
        return jsonify({'error': '비밀번호는 4자 이상이어야 합니다.'}), 400
    user.password_hash = generate_password_hash(new_pw)
    db.session.commit()
    return jsonify({'message': '비밀번호가 변경되었습니다.'})


@bp.route('/api/admin/users/<int:user_id>/role', methods=['POST'])
@moderator_required
def api_admin_change_role(user_id):
    """역할 변경 — admin: 자유, moderator: user→moderator 승급만"""
    user = User.query.get_or_404(user_id)
    data = request.json or {}
    new_role = data.get('role', '')
    if new_role not in ('admin', 'moderator', 'user'):
        return jsonify({'error': '유효하지 않은 역할입니다.'}), 400
    # 중간관리자 제한: user→moderator 승급만 허용
    if g.user.role == 'moderator':
        if user.role != 'user' or new_role != 'moderator':
            return jsonify({'error': '중간관리자는 일반회원을 중간관리자로 승급하는 것만 가능합니다.'}), 403
    # 자기 자신의 admin 권한 해제 방지
    if user.id == g.user.id and user.role == 'admin' and new_role != 'admin':
        return jsonify({'error': '자신의 Admin 권한은 해제할 수 없습니다.'}), 400
    # 마지막 admin 보호
    if user.role == 'admin' and new_role != 'admin' and User.query.filter_by(role='admin').count() <= 1:
        return jsonify({'error': '마지막 Admin의 역할은 변경할 수 없습니다.'}), 400
    user.role = new_role
    db.session.commit()
    return jsonify({'message': f'역할이 {_role_label(new_role)}(으)로 변경되었습니다.', 'role': new_role})


@bp.route('/api/admin/users/<int:user_id>/nickname', methods=['POST'])
@moderator_required
def api_admin_change_nickname(user_id):
    """닉네임 변경 — admin: 모두, moderator: user만"""
    user = User.query.get_or_404(user_id)
    if g.user.role == 'moderator' and user.role != 'user':
        return jsonify({'error': '권한 없음'}), 403
    data = request.json or {}
    nickname = (data.get('nickname') or '').strip()
    user.nickname = nickname if nickname else None
    db.session.commit()
    return jsonify(user.to_dict())


@bp.route('/api/admin/users/nicknames', methods=['POST'])
@admin_required
def api_admin_bulk_nicknames():
    """닉네임 일괄 변경 — admin 전용. body: [{id, nickname}, ...]"""
    items = request.json or []
    if not isinstance(items, list):
        return jsonify({'error': '잘못된 형식'}), 400
    updated = 0
    for item in items:
        uid = item.get('id')
        nickname = (item.get('nickname') or '').strip()
        user = User.query.get(uid)
        if user:
            user.nickname = nickname if nickname else None
            updated += 1
    db.session.commit()
    return jsonify({'updated': updated})


@bp.route('/admin/users')
@moderator_required
def admin_users_page():
    """회원 관리 페이지 (admin + moderator 접근 가능)"""
    return render_template('admin_users.html')
