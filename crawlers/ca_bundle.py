"""
SSL 검증용 CA 번들 생성

일부 기관 사이트는 TLS 핸드셰이크에서 중간 CA 인증서를 보내지 않아
루트를 신뢰하고 있어도 체인을 연결할 수 없고 검증이 실패한다.

    SSLCertVerificationError: unable to get local issuer certificate

실측 사례: 성동구(www.sd.go.kr)가 2026-09-16 인증서 갱신 시 중간 CA
(Sectigo Public Server Authentication CA DV R36) 대신 리프 인증서를
두 번 전송하도록 잘못 설정 -> 2026-09-18 09:00 크롤링부터 연속 실패.

상대 서버의 설정 오류라 우리 쪽에서 고칠 수 없으므로, 누락되는 중간 CA를
`certs/*.pem` 에 넣어두고 certifi 번들 뒤에 합쳐서 체인을 완성한다.

중간 CA는 이미 신뢰하는 루트가 서명한 것이므로 **새로운 신뢰 지점이
추가되지 않는다** (검증을 끄는 verify=False 와 근본적으로 다르다).

실패 모드 점검 (CLAUDE.md 안정 동작 코드 수정 금지 규칙 3항):
- 네트워크 요청 없음 — 인증서는 저장소에 포함되어 있다
- 프로세스당 1회만 생성하고 메모리에 캐싱한다 (호출마다 파일 I/O 없음)
- 여러 크롤러 동시 실행 시 충돌 없음 — 임시 파일에 쓴 뒤 os.replace 로 원자적 교체
- 어떤 단계에서든 실패하면 기존 동작(certifi 기본 검증)으로 폴백한다
"""

import os
import tempfile
import threading

_CERTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'certs')
_CACHE_NAME = 'ca_bundle_merged.pem'

_lock = threading.Lock()
_cached = None  # None=미생성, True=폴백(certifi 기본), str=번들 경로


def _extra_cert_files():
    """certs/ 안의 추가 CA 인증서 목록 (정렬해 번들 내용을 재현 가능하게 유지)"""
    if not os.path.isdir(_CERTS_DIR):
        return []
    return sorted(
        os.path.join(_CERTS_DIR, f)
        for f in os.listdir(_CERTS_DIR)
        if f.lower().endswith(('.pem', '.crt'))
    )


def _build(cache_path, extras):
    import certifi

    parts = [open(certifi.where(), encoding='ascii', errors='ignore').read()]
    for path in extras:
        with open(path, encoding='ascii', errors='ignore') as fh:
            text = fh.read()
        if 'BEGIN CERTIFICATE' not in text:
            continue
        parts.append(text if text.endswith('\n') else text + '\n')

    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(cache_path), suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='ascii') as out:
            out.write('\n'.join(parts))
        os.replace(tmp, cache_path)  # 원자적 교체 — 동시 실행 시 부분 파일 노출 없음
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def get_ca_bundle():
    """
    requests 의 verify 인자로 넘길 값을 돌려준다.

    Returns:
        str: certifi + certs/ 추가 CA 를 합친 번들 파일 경로
        True: 추가 CA가 없거나 번들 생성에 실패한 경우 (certifi 기본 검증)
    """
    global _cached
    if _cached is not None:
        return _cached

    with _lock:
        if _cached is not None:
            return _cached

        result = True
        try:
            extras = _extra_cert_files()
            if extras:
                cache_dir = os.path.join(
                    os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'cache')
                cache_path = os.path.normpath(os.path.join(cache_dir, _CACHE_NAME))

                import certifi
                sources = extras + [certifi.where()]
                newest = max(os.path.getmtime(p) for p in sources)
                if not os.path.exists(cache_path) or os.path.getmtime(cache_path) < newest:
                    _build(cache_path, extras)

                if os.path.getsize(cache_path) > 0:
                    result = cache_path
        except Exception as e:
            # 번들 생성 실패가 크롤링 전체를 막지 않도록 기존 동작으로 폴백
            print(f'[ca_bundle] 추가 CA 번들 생성 실패 — certifi 기본 검증으로 진행: {e}')
            result = True

        _cached = result
        return _cached
