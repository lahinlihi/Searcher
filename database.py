from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import json

db = SQLAlchemy()


class Tender(db.Model):
    """공고 테이블"""
    __tablename__ = 'tenders'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(500), nullable=False)
    agency = db.Column(db.String(200), nullable=False)
    demand_agency = db.Column(db.String(200), nullable=True)  # 실수요기관 (조달청 위탁 등)
    tender_number = db.Column(db.String(100), unique=True, nullable=False)

    # 날짜
    announced_date = db.Column(db.DateTime)
    deadline_date = db.Column(db.DateTime)
    opening_date = db.Column(db.DateTime)

    # 금액 및 방식
    estimated_price = db.Column(db.BigInteger)  # 추정가격 (원)
    bid_method = db.Column(db.String(100))  # 입찰방식

    # 상태
    status = db.Column(db.String(50), default='일반')  # 일반/사전규격
    is_sme_only = db.Column(db.Boolean, default=False)  # 중소기업 전용

    # 출처
    source_site = db.Column(db.String(50), nullable=False)
    url = db.Column(db.String(500))

    # 메타데이터
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_duplicate = db.Column(db.Boolean, default=False)

    # 관계
    bookmarks = db.relationship(
        'Bookmark',
        backref='tender',
        lazy=True,
        cascade='all, delete-orphan')

    def to_dict(self, interest_keywords=None):
        """딕셔너리로 변환

        Args:
            interest_keywords (list): 관심 키워드 리스트
        """
        days_left = None
        if self.deadline_date:
            delta = self.deadline_date - datetime.now()
            days_left = delta.days

        # 매칭된 키워드 찾기
        matched_keywords = []
        if interest_keywords and self.title:
            title_lower = self.title.lower()
            for keyword in interest_keywords:
                if keyword.lower() in title_lower:
                    matched_keywords.append(keyword)

        return {
            'id': self.id,
            'title': self.title,
            'agency': self.agency,
            'demand_agency': self.demand_agency,
            'tender_number': self.tender_number,
            'announced_date': self.announced_date.isoformat() if self.announced_date else None,
            'deadline_date': self.deadline_date.isoformat() if self.deadline_date else None,
            'opening_date': self.opening_date.isoformat() if self.opening_date else None,
            'estimated_price': self.estimated_price,
            'bid_method': self.bid_method,
            'status': self.status,
            'is_sme_only': self.is_sme_only,
            'source_site': self.source_site,
            'url': self.url,
            'created_at': self.created_at.isoformat(),
            'days_left': days_left,
            'matched_keywords': matched_keywords}


class Filter(db.Model):
    """필터 프리셋 테이블"""
    __tablename__ = 'filters'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    is_default = db.Column(db.Boolean, default=False)

    # 필터 조건 (JSON 저장)
    include_keywords = db.Column(db.Text)  # JSON array
    exclude_keywords = db.Column(db.Text)  # JSON array
    regions = db.Column(db.Text)  # JSON array
    categories = db.Column(db.Text)  # JSON array

    min_price = db.Column(db.BigInteger)
    max_price = db.Column(db.BigInteger)
    days_before_deadline = db.Column(db.Integer)

    priority_pre_announcement = db.Column(db.Boolean, default=True)  # 사전규격 우선
    sme_only = db.Column(db.Boolean, default=False)  # 중소기업만

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        """딕셔너리로 변환"""
        return {
            'id': self.id,
            'name': self.name,
            'is_default': self.is_default,
            'include_keywords': json.loads(
                self.include_keywords) if self.include_keywords else [],
            'exclude_keywords': json.loads(
                self.exclude_keywords) if self.exclude_keywords else [],
            'regions': json.loads(
                self.regions) if self.regions else [],
            'categories': json.loads(
                    self.categories) if self.categories else [],
            'min_price': self.min_price,
            'max_price': self.max_price,
            'days_before_deadline': self.days_before_deadline,
            'priority_pre_announcement': self.priority_pre_announcement,
            'sme_only': self.sme_only,
            'created_at': self.created_at.isoformat()}


class CrawlLog(db.Model):
    """크롤링 로그 테이블"""
    __tablename__ = 'crawl_logs'

    id = db.Column(db.Integer, primary_key=True)
    started_at = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime)

    total_found = db.Column(db.Integer, default=0)
    new_tenders = db.Column(db.Integer, default=0)

    # JSON: {site_name: {success: bool, count: int}}
    site_results = db.Column(db.Text)
    # running/completed/failed
    status = db.Column(db.String(50), default='running')
    error_message = db.Column(db.Text)

    def to_dict(self):
        """딕셔너리로 변환"""
        return {
            'id': self.id,
            'started_at': self.started_at.isoformat(),
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'total_found': self.total_found,
            'new_tenders': self.new_tenders,
            'site_results': json.loads(
                self.site_results) if self.site_results else {},
            'status': self.status,
            'error_message': self.error_message}


class Bookmark(db.Model):
    """즐겨찾기 테이블"""
    __tablename__ = 'bookmarks'

    # 스크랩 라벨 선택지 (안 3)
    LABEL_CHOICES = [
        ('executable',  '수행 가능'),   # +15점 보너스
        ('experienced', '경험 있음'),   # +10점 보너스
        ('interested',  '관심사'),      # +5점 보너스
        ('reference',   '참고용'),      # +0점
    ]
    LABEL_BONUS = {
        'executable':  15,
        'experienced': 10,
        'interested':   5,
        'reference':    0,
    }

    id = db.Column(db.Integer, primary_key=True)
    tender_id = db.Column(
        db.Integer,
        db.ForeignKey('tenders.id'),
        nullable=False)
    user_note = db.Column(db.Text)
    label = db.Column(db.String(20), nullable=True)   # 스크랩 라벨
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        """딕셔너리로 변환"""
        return {
            'id': self.id,
            'tender_id': self.tender_id,
            'user_note': self.user_note,
            'label': self.label,
            'created_at': self.created_at.isoformat()
        }


class TenderAnalysis(db.Model):
    """공고 AI 분석 결과 캐시 테이블"""
    __tablename__ = 'tender_analyses'

    id = db.Column(db.Integer, primary_key=True)
    tender_id = db.Column(
        db.Integer,
        db.ForeignKey('tenders.id'),
        unique=True,
        nullable=False,
    )
    files_found    = db.Column(db.Text, default='[]')   # JSON list
    text_length    = db.Column(db.Integer, default=0)
    rule_extract   = db.Column(db.Text, default='{}')   # JSON dict
    gemini_sections = db.Column(db.Text, default='null') # JSON dict|null
    model_used     = db.Column(db.String(100))
    error          = db.Column(db.Text)
    created_at     = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at     = db.Column(db.DateTime, default=datetime.utcnow)

    tender = db.relationship('Tender', backref=db.backref('analysis', uselist=False))

    def to_dict(self):
        return {
            'files_found':     json.loads(self.files_found  or '[]'),
            'text_length':     self.text_length or 0,
            'rule_extract':    json.loads(self.rule_extract  or '{}'),
            'gemini_sections': json.loads(self.gemini_sections or 'null'),
            'model_used':      self.model_used,
            'error':           self.error,
            'cached':          True,
            'cached_at':       self.updated_at.isoformat() if self.updated_at else None,
        }


def init_db(app):
    """데이터베이스 초기화"""
    db.init_app(app)

    with app.app_context():
        db.create_all()

        # 기본 필터가 없으면 생성
        if Filter.query.filter_by(is_default=True).first() is None:
            default_filter = Filter(
                name='내 기본 필터',
                is_default=True,
                include_keywords=json.dumps(['AI', '웹개발', '소프트웨어']),
                exclude_keywords=json.dumps(['철거', '폐기물', '청소']),
                regions=json.dumps(['서울', '경기']),
                min_price=10000000,
                max_price=500000000,
                days_before_deadline=15,
                priority_pre_announcement=True,
                sme_only=False
            )
            db.session.add(default_filter)
            db.session.commit()
            print("기본 필터가 생성되었습니다.")
