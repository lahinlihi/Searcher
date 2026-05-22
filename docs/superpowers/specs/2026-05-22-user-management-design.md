# 회원관리 시스템 확장 설계 문서

**작성일:** 2026-05-22  
**프로젝트:** Searcher (Flask 3.0 / SQLAlchemy 2.x / SQLite)  
**범위:** 회원정보 관리, 셀프 회원가입(관리자 승인), 소셜로그인(카카오·구글), 접속 모니터링

---

## 1. 배경 및 목표

현재 시스템은 관리자만 계정을 생성할 수 있고, 이메일·소셜로그인·접속 추적 기능이 없다. 일반 이용자가 직접 회원가입을 신청하고, 소셜 계정으로 간편 로그인할 수 있도록 확장한다. 관리자는 가입 신청을 승인/거절하고 회원별 접속 현황을 모니터링할 수 있다.

---

## 2. 데이터 모델

### 2-1. User 모델 확장 (`database.py`)

```python
class User(db.Model):
    # ── 기존 필드 ──────────────────────────────
    id             = db.Column(db.Integer, primary_key=True)
    username       = db.Column(db.String(80), unique=True, nullable=False)
    password_hash  = db.Column(db.String(200), nullable=True)   # 소셜 전용 계정은 NULL 허용
    role           = db.Column(db.String(20), default='user')   # 'admin'|'moderator'|'user'
    nickname       = db.Column(db.String(80), nullable=True)
    created_at     = db.Column(db.DateTime, default=datetime.utcnow)

    # ── 신규 필드 ──────────────────────────────
    email               = db.Column(db.String(120), unique=True, nullable=True)
    status              = db.Column(db.String(20), default='pending')   # 'pending'|'active'|'suspended'
    last_login_at       = db.Column(db.DateTime, nullable=True)

    # 소셜 로그인 연결
    kakao_id            = db.Column(db.String(100), unique=True, nullable=True)
    google_id           = db.Column(db.String(100), unique=True, nullable=True)

    # 이메일 인증 (임시 저장)
    email_verify_code   = db.Column(db.String(10), nullable=True)
    email_verify_expiry = db.Column(db.DateTime, nullable=True)
```

**`password_hash` nullable 변경 이유:** 카카오/구글 전용 계정은 비밀번호 없이 가입 가능. 나중에 비밀번호 설정 가능.

**마이그레이션 규칙:**
- 기존 계정 전체 → `status='active'` (서비스 중단 없음)
- `password_hash` NOT NULL → NULL 허용으로 변경 (SQLite `ALTER TABLE` + 데이터 보존)

### 2-2. `status` 상태 흐름

```
[신규 가입 신청] ──→ pending
                       │
        ┌──────────────┴──────────────┐
        ▼                             ▼
   (관리자 승인)                 (관리자 거절)
   status='active'             레코드 삭제
        │
        ▼
   로그인 가능
```

---

## 3. 회원가입 기능

### 3-1. 이메일/비밀번호 셀프 가입

**엔드포인트:** `POST /api/register`  
**입력:** `username`, `password`, `email`(선택)  
**처리:**
1. username 중복 확인
2. email 중복 확인 (입력 시)
3. `User` 생성, `status='pending'`
4. `201` 응답 + "관리자 승인 대기 중" 메시지

**비밀번호 최소 규칙:** 8자 이상 (현재 4자에서 상향)

### 3-2. 카카오 OAuth 로그인/가입

**라이브러리:** `authlib` (`pip install authlib requests`)  
**필요 환경변수:** `KAKAO_CLIENT_ID`, `KAKAO_REDIRECT_URI`

**흐름:**
```
[로그인 페이지] 카카오 버튼 클릭
    → GET /auth/kakao                       # authlib OAuth 시작
    → (카카오 인증 페이지)
    → GET /auth/kakao/callback?code=...     # 콜백
        → 카카오 토큰 교환 → 사용자 정보(kakao_id, email, nickname) 수신
        → kakao_id로 기존 User 검색
            ├── 존재 + active  → 로그인 처리 (last_login_at 갱신)
            ├── 존재 + pending → "승인 대기 중" 안내
            └── 없음           → User 신규 생성 (status='pending') → "승인 대기 중" 안내
```

**카카오 API 키 발급 방법 (운영자 작업):**
1. [developers.kakao.com](https://developers.kakao.com) 로그인
2. 내 애플리케이션 → 애플리케이션 추가
3. 카카오 로그인 → 활성화 ON
4. Redirect URI: `http://localhost:5002/auth/kakao/callback` (운영 시 실제 도메인)
5. REST API 키 복사 → `.env`의 `KAKAO_CLIENT_ID`에 설정

### 3-3. 구글 OAuth 로그인/가입

**라이브러리:** `authlib` (동일)  
**필요 환경변수:** `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI`

**흐름:** 카카오와 동일한 패턴
```
GET /auth/google → (구글 인증) → GET /auth/google/callback
    → google_id(sub), email, name 수신 → 동일한 pending 흐름
```

**구글 API 키 발급 방법 (운영자 작업):**
1. [console.cloud.google.com](https://console.cloud.google.com) → 프로젝트 생성
2. API 및 서비스 → OAuth 동의 화면 설정 (외부, 앱 이름·이메일 입력)
3. 사용자 인증 정보 → OAuth 2.0 클라이언트 ID 생성
4. 승인된 리디렉션 URI: `http://localhost:5002/auth/google/callback`
5. 클라이언트 ID·보안 비밀 복사 → `.env`에 설정

### 3-4. `.env` 파일 구조 (신규 생성)

```env
# 소셜 로그인
KAKAO_CLIENT_ID=여기에_카카오_REST_API_키
KAKAO_REDIRECT_URI=http://localhost:5002/auth/kakao/callback

GOOGLE_CLIENT_ID=여기에_구글_클라이언트_ID
GOOGLE_CLIENT_SECRET=여기에_구글_보안_비밀
GOOGLE_REDIRECT_URI=http://localhost:5002/auth/google/callback

# 이메일 인증 (선택 — 이메일 변경 기능 사용 시)
MAIL_SERVER=smtp.gmail.com
MAIL_PORT=587
MAIL_USERNAME=your@gmail.com
MAIL_PASSWORD=gmail_app_password
```

---

## 4. 회원정보 관리 (마이페이지)

기존 설정 페이지(`/settings`) 내 "계정 정보" 탭 추가.

### 4-1. 닉네임 변경
- 기존 기능 그대로 유지. UI만 정리.

### 4-2. 비밀번호 변경
- **일반 계정:** 현재 비밀번호 확인 → 새 비밀번호 설정
- **소셜 전용 계정** (`password_hash=NULL`): "비밀번호 새로 설정" (현재 비번 확인 없음)

### 4-3. 이메일 변경 (인증 포함)

**흐름:**
```
새 이메일 입력 → POST /api/me/email/request-verify
    → 6자리 숫자 코드 생성 (만료: 10분)
    → user.email_verify_code, user.email_verify_expiry 저장
    → Gmail SMTP로 인증코드 발송 (Flask-Mail)

코드 입력 → POST /api/me/email/confirm
    → 코드 일치 + 만료 안됨 → user.email 업데이트, 코드 초기화
    → 코드 불일치 or 만료 → 오류 반환
```

**Flask-Mail 미설정 시:** 이메일 인증 기능은 숨김 처리 (서버 설정에 따라 graceful degradation)

### 4-4. 소셜 계정 연결/해제

- **연결 추가:** 현재 로그인 상태에서 `/auth/kakao?link=1` 진입 → OAuth 후 기존 계정에 `kakao_id` 연결
- **연결 해제:** `DELETE /api/me/social/kakao` — 단, 비밀번호가 없고 소셜 1개만 연결된 경우 해제 불가 (로그인 불가 방지)

---

## 5. 관리자 — 회원 승인 및 모니터링

### 5-1. 승인 대기 목록

**기존 회원관리 페이지 상단에 "승인 대기" 탭 추가**

| 필드 | 내용 |
|------|------|
| 아이디 | username |
| 닉네임 | nickname |
| 이메일 | email |
| 가입 방법 | 이메일/카카오/구글 아이콘 |
| 신청일 | created_at |
| 버튼 | ✅ 승인 / ❌ 거절 |

**API:**
- `POST /api/admin/users/<id>/approve` → `status='active'`
- `POST /api/admin/users/<id>/reject` → 레코드 삭제

**관리자 화면 배지:** 승인 대기 인원 수를 관리자 메뉴에 숫자 배지로 표시

### 5-2. 접속 모니터링

**기존 회원 목록 테이블에 컬럼 추가:**

| 추가 컬럼 | 내용 |
|-----------|------|
| 최종 접속 | `last_login_at` — "오늘 14:32", "3일 전", "미접속" 형식 |
| 연결 소셜 | 카카오🔵 / 구글🔴 아이콘 (연결된 것만 표시) |
| 상태 | active / pending / suspended 배지 |

**접속시간 기록:** 로그인 성공 시 `user.last_login_at = datetime.now()`  
**열람 권한:** admin + moderator만 조회 가능 (기존 `moderator_required` 데코레이터 활용)

---

## 6. 라우트 및 파일 구조

### 신규/수정 파일

```
신규:
  templates/register.html              # 회원가입 페이지 (이메일폼 + 소셜 버튼)
  .env                                 # 소셜 API 키 환경변수
  .env.example                         # 키 템플릿 (git 추가)

수정:
  database.py                          # User 모델 확장 + 마이그레이션 스크립트
  routes/auth.py                       # 회원가입 API, OAuth 콜백 (카카오·구글)
  routes/admin.py                      # 승인/거절 API, 배지 카운트 API
  templates/login.html                 # 소셜 로그인 버튼, 회원가입 링크 추가
  templates/settings.html              # 계정 정보 탭 추가 (비번·이메일·소셜 연결)
  templates/admin.html                 # 승인 대기 탭, last_login 컬럼
  app.py                               # python-dotenv 로드, Flask-Mail 초기화
  requirements.txt                     # authlib, flask-mail, python-dotenv 추가
```

### 신규 API 엔드포인트 목록

| Method | URL | 설명 | 권한 |
|--------|-----|------|------|
| POST | `/api/register` | 이메일/비번 회원가입 신청 | 누구나 |
| GET | `/auth/kakao` | 카카오 OAuth 시작 | 누구나 |
| GET | `/auth/kakao/callback` | 카카오 OAuth 콜백 | 누구나 |
| GET | `/auth/google` | 구글 OAuth 시작 | 누구나 |
| GET | `/auth/google/callback` | 구글 OAuth 콜백 | 누구나 |
| POST | `/api/me/email/request-verify` | 이메일 인증코드 발송 | 로그인 |
| POST | `/api/me/email/confirm` | 이메일 인증코드 확인 | 로그인 |
| DELETE | `/api/me/social/kakao` | 카카오 연결 해제 | 로그인 |
| DELETE | `/api/me/social/google` | 구글 연결 해제 | 로그인 |
| POST | `/api/admin/users/<id>/approve` | 회원 승인 | admin/moderator |
| POST | `/api/admin/users/<id>/reject` | 회원 거절 | admin/moderator |
| GET | `/api/admin/users/pending-count` | 승인 대기 수 | admin/moderator |

---

## 7. 보안 고려사항

- OAuth state 파라미터 검증 (CSRF 방지) — authlib 자동 처리
- 소셜 로그인 콜백 URL은 `.env`로 관리 (하드코딩 금지)
- 이메일 인증 코드: 6자리, 10분 만료, 1회용 (확인 후 즉시 초기화)
- `password_hash=NULL` + 소셜 1개만 연결된 계정은 소셜 해제 불가
- pending 상태 계정은 로그인 시 "승인 대기 중" 메시지 반환, 세션 미발급
- `.env` 파일은 `.gitignore`에 추가

---

## 8. 구현 순서 (의존성 기준)

1. **DB 마이그레이션** — User 모델 확장, 기존 계정 active 처리
2. **셀프 회원가입 + 관리자 승인** — 가장 핵심, 소셜 없이도 동작
3. **접속 모니터링** — last_login_at 기록 + 관리자 UI
4. **카카오 OAuth** — API 키 발급 후 구현
5. **구글 OAuth** — 카카오와 동일한 패턴
6. **이메일 인증 (선택)** — SMTP 설정 시 활성화
7. **마이페이지 소셜 연결/해제** — 소셜 로그인 완성 후

---

*이 문서는 brainstorming → writing-plans 전환을 위한 승인 스펙입니다.*
