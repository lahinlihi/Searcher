"""
설정 관리 기능
사용자 설정을 JSON 파일로 저장하고 불러옵니다.
"""

import json
import os


class SettingsManager:
    """설정 관리 클래스"""

    def __init__(self, settings_file='data/settings.json'):
        self.settings_file = settings_file
        self.settings = self._load_default_settings()

    def _load_default_settings(self):
        """기본 설정 반환"""
        return {
            'gemini_api_key': '',
            'crawl': {
                'auto_enabled': True,
                'times': ['09:00', '17:00'],
                'sites': {},
                'sites_config': {}
            },
            'notification': {
                'email_enabled': False,
                'email_address': '',
                'sender_email': '',
                'sender_password': '',
                'deadline_alert': True,
                'deadline_days': 3
            },
            'data': {
                'retention_days': 30,
                'auto_cleanup': False
            },
            'display': {
                'items_per_page': 20,
                'theme': 'light'
            }
        }

    def load_settings(self):
        """
        설정 파일 불러오기

        Returns:
            dict: 설정 데이터
        """
        try:
            if os.path.exists(self.settings_file):
                with open(self.settings_file, 'r', encoding='utf-8') as f:
                    loaded_settings = json.load(f)

                # 기본 설정과 병합 (누락된 키 추가)
                self.settings = self._merge_settings(
                    self._load_default_settings(),
                    loaded_settings
                )

                print(f"[설정] 설정 파일 로드 완료: {self.settings_file}")
            else:
                print("[설정] 설정 파일 없음, 기본 설정 사용")
                self.settings = self._load_default_settings()

            return self.settings

        except Exception as e:
            print(f"[설정] 설정 파일 로드 실패: {str(e)}")
            self.settings = self._load_default_settings()
            return self.settings

    def save_settings(self, settings=None):
        """
        설정 파일 저장

        Args:
            settings (dict): 저장할 설정 (None이면 현재 설정 저장)

        Returns:
            bool: 성공 여부
        """
        if settings:
            self.settings = settings

        try:
            # 디렉토리 생성
            os.makedirs(os.path.dirname(self.settings_file), exist_ok=True)

            # 파일 저장
            with open(self.settings_file, 'w', encoding='utf-8') as f:
                json.dump(self.settings, f, indent=2, ensure_ascii=False)

            print(f"[설정] 설정 파일 저장 완료: {self.settings_file}")
            return True

        except Exception as e:
            print(f"[설정] 설정 파일 저장 실패: {str(e)}")
            return False

    def get(self, key, default=None):
        """
        설정 값 가져오기

        Args:
            key (str): 키 (점 구분, 예: 'crawl.auto_enabled')
            default: 기본값

        Returns:
            설정 값
        """
        keys = key.split('.')
        value = self.settings

        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default

        return value

    def set(self, key, value):
        """
        설정 값 변경

        Args:
            key (str): 키 (점 구분, 예: 'crawl.auto_enabled')
            value: 값

        Returns:
            bool: 성공 여부
        """
        keys = key.split('.')
        settings = self.settings

        # 마지막 키 전까지 딕셔너리 탐색
        for k in keys[:-1]:
            if k not in settings:
                settings[k] = {}
            settings = settings[k]

        # 값 설정
        settings[keys[-1]] = value

        # 파일 저장
        return self.save_settings()

    def update(self, updates):
        """
        여러 설정 값 한번에 업데이트

        Args:
            updates (dict): 업데이트할 설정 딕셔너리

        Returns:
            bool: 성공 여부
        """
        self.settings = self._merge_settings(self.settings, updates)
        return self.save_settings()

    def reset_to_default(self):
        """
        기본 설정으로 초기화

        Returns:
            bool: 성공 여부
        """
        self.settings = self._load_default_settings()
        return self.save_settings()

    def export_settings(self):
        """
        설정을 JSON 문자열로 내보내기

        Returns:
            str: JSON 문자열
        """
        return json.dumps(self.settings, indent=2, ensure_ascii=False)

    def import_settings(self, json_str):
        """
        JSON 문자열에서 설정 가져오기

        Args:
            json_str (str): JSON 문자열

        Returns:
            bool: 성공 여부
        """
        try:
            imported = json.loads(json_str)
            self.settings = self._merge_settings(
                self._load_default_settings(),
                imported
            )
            return self.save_settings()

        except Exception as e:
            print(f"[설정] 설정 가져오기 실패: {str(e)}")
            return False

    def _merge_settings(self, base, updates):
        """
        설정 딕셔너리 병합

        Args:
            base (dict): 기본 설정
            updates (dict): 업데이트할 설정

        Returns:
            dict: 병합된 설정
        """
        result = base.copy()

        for key, value in updates.items():
            if key in result and isinstance(
                    result[key],
                    dict) and isinstance(
                    value,
                    dict):
                result[key] = self._merge_settings(result[key], value)
            else:
                result[key] = value

        return result

    def get_crawler_config(self, site_id, site_config=None):
        """
        크롤러 설정 가져오기 (전역 기본값과 병합)

        Args:
            site_id (str): 사이트 ID
            site_config (dict, optional): 사이트별 설정 (없으면 설정파일에서 조회)

        Returns:
            dict: 전역 기본값과 병합된 크롤러 설정
        """
        # 전역 기본값 가져오기
        global_defaults = self.get('crawl.global_defaults', {})

        # 사이트별 설정 가져오기
        if site_config is None:
            # sites와 sites_config 모두 확인
            site_config = self.get(f'crawl.sites.{site_id}')
            if not site_config:
                site_config = self.get(f'crawl.sites_config.{site_id}', {})

        # 병합 (사이트별 설정이 전역 기본값을 덮어씀)
        merged_config = {}

        # 전역 기본값 복사
        for key, value in global_defaults.items():
            merged_config[key] = value

        # 사이트별 설정으로 덮어쓰기
        for key, value in site_config.items():
            merged_config[key] = value

        return merged_config

    def validate_settings(self):
        """
        설정 유효성 검사

        Returns:
            tuple: (is_valid, errors)
        """
        errors = []

        # 크롤링 시간 검사
        times = self.get('crawl.times', [])
        for time_str in times:
            try:
                hour, minute = map(int, time_str.split(':'))
                if not (0 <= hour < 24 and 0 <= minute < 60):
                    errors.append(f"잘못된 시간 형식: {time_str}")
            except BaseException:
                errors.append(f"잘못된 시간 형식: {time_str}")

        # 이메일 설정 검사
        if self.get('notification.email_enabled'):
            email = self.get('notification.email_address')
            if not email or '@' not in email:
                errors.append("올바른 이메일 주소를 입력하세요")

        # 데이터 보관 기간 검사
        retention_days = self.get('data.retention_days', 30)
        if not isinstance(retention_days, int) or retention_days < 1:
            errors.append("데이터 보관 기간은 1일 이상이어야 합니다")

        return len(errors) == 0, errors


# 전역 인스턴스
settings_manager = SettingsManager()
settings_manager.load_settings()  # 초기화시 설정 파일 로드
