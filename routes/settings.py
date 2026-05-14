from flask import Blueprint, request, jsonify, g
from database import db, UserPreference
from decorators import login_required, admin_required
from settings_manager import settings_manager
from email_notifier import email_notifier, EmailNotifier
import json

bp = Blueprint('settings_bp', __name__)


@bp.route('/api/supported-crawlers', methods=['GET'])
@admin_required
def api_supported_crawlers():
    """구현된 크롤러 타입 목록 반환 (프론트엔드 동적 배지 표시용)"""
    from scheduler import SUPPORTED_CRAWLER_TYPES, LEGACY_CRAWLERS
    return jsonify({
        'supported_types': list(SUPPORTED_CRAWLER_TYPES),
        'legacy_sites': list(LEGACY_CRAWLERS),
    })


@bp.route('/api/settings', methods=['GET', 'POST'])
@admin_required
def api_settings():
    """설정 조회/저장"""
    if request.method == 'GET':
        try:
            return jsonify(settings_manager.settings)
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    elif request.method == 'POST':
        try:
            new_settings = request.json
            # gemini_api_key는 별도 엔드포인트로 관리 — 폼에 없으면 기존 값 유지
            if 'gemini_api_key' not in new_settings:
                new_settings['gemini_api_key'] = settings_manager.get('gemini_api_key', '')
            success = settings_manager.save_settings(new_settings)

            if success:
                return jsonify({'message': '설정이 저장되었습니다.'})
            else:
                return jsonify({'error': '설정 저장 실패'}), 500
        except Exception as e:
            return jsonify({'error': str(e)}), 500


@bp.route('/api/settings/validate', methods=['POST'])
@admin_required
def api_validate_settings():
    """설정 유효성 검사"""
    try:
        temp_settings = request.json
        # 임시로 설정 업데이트
        original_settings = settings_manager.settings
        settings_manager.settings = temp_settings

        is_valid, errors = settings_manager.validate_settings()

        # 원래 설정 복원
        settings_manager.settings = original_settings

        return jsonify({
            'valid': is_valid,
            'errors': errors
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp.route('/api/settings/gemini-key', methods=['GET', 'POST'])
@admin_required
def api_gemini_key():
    """Gemini API 키 조회/저장"""
    if request.method == 'GET':
        try:
            key = settings_manager.get('gemini_api_key', '')
            masked = key[:8] + '...' if len(key) > 8 else ('설정됨' if key else '')
            return jsonify({'has_key': bool(key), 'masked': masked})
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    else:
        try:
            data = request.json or {}
            new_key = data.get('api_key', '').strip()
            settings_manager.set('gemini_api_key', new_key)
            return jsonify({'message': 'Gemini API 키가 저장되었습니다.'})
        except Exception as e:
            return jsonify({'error': str(e)}), 500


@bp.route('/api/settings/gemini-model-priority', methods=['GET', 'POST'])
@admin_required
def api_gemini_model_priority():
    """Gemini 분석 모델 우선순위 조회/저장"""
    if request.method == 'GET':
        priority = settings_manager.get('gemini_model_priority', 'quality')
        return jsonify({'priority': priority})
    else:
        try:
            data = request.json or {}
            priority = data.get('priority', 'quality')
            if priority not in ('speed', 'balanced', 'quality'):
                return jsonify({'error': '유효하지 않은 값 (speed/balanced/quality)'}), 400
            settings_manager.set('gemini_model_priority', priority)
            return jsonify({'message': '저장되었습니다.', 'priority': priority})
        except Exception as e:
            return jsonify({'error': str(e)}), 500


@bp.route('/api/email-settings', methods=['GET', 'POST'])
@admin_required
def api_email_settings():
    """이메일 알림 설정 조회/저장"""
    if request.method == 'GET':
        try:
            # 설정 파일 로드
            with open('data/settings.json', 'r', encoding='utf-8') as f:
                settings = json.load(f)

            email_settings = settings.get('email_notification', {})
            return jsonify({'settings': email_settings})
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    elif request.method == 'POST':
        try:
            data = request.json

            # 설정 파일 로드
            with open('data/settings.json', 'r', encoding='utf-8') as f:
                settings = json.load(f)

            # 이메일 설정 업데이트
            settings['email_notification'] = {
                'enabled': data.get('enabled', False),
                'email_service': data.get('email_service', 'gmail'),
                'sender_email': data.get('sender_email', ''),
                'sender_password': data.get('sender_password', ''),
                'recipient_email': data.get('recipient_email', ''),
                'new_tender_alert': data.get('new_tender_alert', False),
                'deadline_alert': data.get('deadline_alert', False),
                'keyword_alert': data.get('keyword_alert', False)
            }

            # 설정 파일 저장
            with open('data/settings.json', 'w', encoding='utf-8') as f:
                json.dump(settings, f, ensure_ascii=False, indent=2)

            # EmailNotifier 설정 업데이트
            if settings['email_notification']['enabled']:
                email_notifier.configure(
                    settings['email_notification']['sender_email'],
                    settings['email_notification']['sender_password'],
                    settings['email_notification']['recipient_email'],
                    settings['email_notification']['email_service']
                )
            else:
                email_notifier.enabled = False

            return jsonify({'message': '이메일 설정이 저장되었습니다.'})
        except Exception as e:
            return jsonify({'error': str(e)}), 500


@bp.route('/api/test-email', methods=['POST'])
@admin_required
def api_test_email():
    """테스트 이메일 발송"""
    try:
        data = request.json
        email_service = data.get('email_service', 'gmail')
        sender_email = data.get('sender_email')
        sender_password = data.get('sender_password')
        recipient_email = data.get('recipient_email')

        if not all([sender_email, sender_password, recipient_email]):
            return jsonify({'error': '모든 이메일 정보를 입력해야 합니다.'}), 400

        # 임시 EmailNotifier 생성
        test_notifier = EmailNotifier()
        test_notifier.configure(
            sender_email,
            sender_password,
            recipient_email,
            email_service)

        # 테스트 이메일 발송
        success = test_notifier.send_test_email()

        if success:
            return jsonify({'message': '테스트 이메일이 발송되었습니다.'})
        else:
            return jsonify({'error': '이메일 발송에 실패했습니다.'}), 500

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp.route('/api/interest-keywords', methods=['GET', 'POST'])
@login_required
def api_interest_keywords():
    """관심 키워드 조회/저장 (사용자별 개인화)"""
    from scoring import load_interest_keywords, load_exclude_keywords, load_budget_range
    if request.method == 'GET':
        try:
            pref = UserPreference.query.filter_by(user_id=g.user.id).first()
            if pref:
                keywords = pref.get_interest_keywords()
                exclude_keywords = pref.get_exclude_keywords()
                budget_range = pref.get_budget_range()
                type_weights = pref.get_type_weights()
            else:
                # settings.json 폴백 (UserPreference 레코드 없을 때, 레거시 마이그레이션)
                keywords = load_interest_keywords(g.user.id)
                exclude_keywords = load_exclude_keywords(g.user.id)
                budget_range = load_budget_range(g.user.id)
                type_weights = {}
            return jsonify({
                'keywords': keywords,
                'exclude_keywords': exclude_keywords,
                'budget_range': budget_range,
                'type_weights': type_weights,
            })
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    elif request.method == 'POST':
        try:
            data = request.json
            keywords = data.get('keywords', [])
            exclude_kws = data.get('exclude_keywords', None)
            budget_range = data.get('budget_range', None)
            type_weights = data.get('type_weights', None)

            pref = UserPreference.query.filter_by(user_id=g.user.id).first()
            if not pref:
                pref = UserPreference(user_id=g.user.id,
                                      interest_keywords='[]',
                                      exclude_keywords='[]')
                db.session.add(pref)

            pref.interest_keywords = json.dumps(keywords, ensure_ascii=False)
            if exclude_kws is not None:
                pref.exclude_keywords = json.dumps(exclude_kws, ensure_ascii=False)
            if budget_range is not None:
                br = budget_range or {}
                pref.budget_min = br.get('min')
                pref.budget_max = br.get('max')
            if type_weights is not None:
                pref.type_weights = json.dumps(type_weights, ensure_ascii=False)

            db.session.commit()

            return jsonify({
                'message': '키워드 필터가 저장되었습니다.',
                'keywords': pref.get_interest_keywords(),
                'exclude_keywords': pref.get_exclude_keywords(),
                'budget_range': pref.get_budget_range(),
                'type_weights': pref.get_type_weights(),
            })
        except Exception as e:
            db.session.rollback()
            print(f"[오류] 키워드 필터 저장 실패: {str(e)}")
            return jsonify({'error': str(e)}), 500
