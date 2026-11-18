"""
설정 관리 기능
사용자 설정을 JSON 파일로 저장하고 불러옵니다.

data/settings.json 을 고쳐 쓰는 경로는 이 모듈 하나다 (modify → _write_file).
다른 모듈이 파일을 직접 열어 쓰면, 서버가 들고 있는 사본과 어긋나 한쪽 변경이
조용히 되돌려진다. 설정을 바꿀 때는 set() 이나 modify() 를 쓴다.
"""

import json
import os
import threading

_DEFAULT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'settings.json')


class SettingsManager:
    """설정 관리 클래스"""

    def __init__(self, settings_file=_DEFAULT_FILE):
        self.settings_file = settings_file
        self._lock = threading.RLock()
        self.settings = self._load_default_settings()

    def _load_default_settings(self):
        """기본 설정 반환"""
        return {
            'gemini_api_key': '',
            'gemini_model_priority': 'quality',  # speed | balanced | quality
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

    def _write_file(self, data):
        """임시 파일에 쓴 뒤 바꿔치기한다. 쓰는 도중 끊겨도 원본이 깨지지 않는다."""
        os.makedirs(os.path.dirname(os.path.abspath(self.settings_file)), exist_ok=True)
        tmp = self.settings_file + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, self.settings_file)

    def modify(self, change):
        """
        설정을 고쳐 저장하는 단일 경로.

        파일을 다시 읽고 → change(settings) 로 고치고 → 저장한 뒤 메모리 사본을 맞춘다.
        메모리 사본이 아니라 파일에서 출발하므로, 서버 밖에서 파일을 고친 내용
        (명령줄 실행, 손으로 편집)을 덮어쓰지 않는다.

        Args:
            change: settings(dict) 를 받아 그 자리에서 고치거나, 새 dict 를 반환하는 함수

        파일이 깨져 읽을 수 없으면 예외를 낸다. 기본값으로 덮어쓰지 않는다.
        """
        with self._lock:
            if os.path.exists(self.settings_file):
                with open(self.settings_file, 'r', encoding='utf-8') as f:
                    current = self._merge_settings(self._load_default_settings(), json.load(f))
            else:
                current = self.settings
            changed = change(current)
            if changed is not None:
                current = changed
            self._write_file(current)
            self.settings = current
            return current

    def save_settings(self, settings=None):
        """
        설정 전체를 파일에 저장 (settings 가 None 이면 현재 메모리 사본)

        일부만 바꿀 때는 set() 이나 modify() 를 쓴다.

        Returns:
            bool: 성공 여부
        """
        try:
            with self._lock:
                if settings:
                    self.settings = settings
                self._write_file(self.settings)
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

        def _apply(settings):
            node = settings
            for k in keys[:-1]:          # 마지막 키 전까지 딕셔너리 탐색
                if k not in node:
                    node[k] = {}
                node = node[k]
            node[keys[-1]] = value

        try:
            self.modify(_apply)
            return True
        except Exception as e:
            print(f"[설정] 설정 파일 저장 실패: {str(e)}")
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
