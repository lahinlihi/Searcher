"""테스트 공통 준비물. 운영 DB·app.py(스케줄러가 뜬다)는 쓰지 않고, 임시 sqlite 로 최소 앱을 만든다."""
import itertools
import os
import sys
from datetime import datetime, timedelta

import pytest
from flask import Flask, g, session

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from database import db, Tender, User  # noqa: E402

_seq = itertools.count(1)


@pytest.fixture
def app(tmp_path):
    app = Flask(__name__, root_path=ROOT, template_folder=os.path.join(ROOT, 'templates'),
                static_folder=os.path.join(ROOT, 'static'))
    app.config.update(
        SQLALCHEMY_DATABASE_URI='sqlite:///' + str(tmp_path / 'test.db').replace('\\', '/'),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        SECRET_KEY='test',
        TESTING=True,
    )
    db.init_app(app)

    @app.before_request
    def _load_user():
        uid = session.get('user_id')
        g.user = db.session.get(User, uid) if uid else None

    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()


@pytest.fixture
def make_user(app):
    def _make(role='user'):
        u = User(username=f'u{next(_seq)}', role=role)
        db.session.add(u)
        db.session.commit()
        return u
    return _make


@pytest.fixture
def make_tender(app):
    def _make(**kw):
        now = datetime.now()
        n = next(_seq)
        data = dict(
            title=f'공고 {n}', agency='테스트기관', tender_number=f'T{n:08d}',
            source_site='나라장터 API (용역)', status='일반', bid_method='일반경쟁',
            announced_date=now, deadline_date=now + timedelta(days=10), created_at=now,
        )
        data.update(kw)
        t = Tender(**data)
        db.session.add(t)
        db.session.commit()
        return t
    return _make


@pytest.fixture
def make_prefs(app):
    def _make(user, interest=(), exclude=(), budget_min=None, budget_max=None):
        import json
        from database import UserPreference
        p = UserPreference(user_id=user.id, interest_keywords=json.dumps(list(interest), ensure_ascii=False),
                           exclude_keywords=json.dumps(list(exclude), ensure_ascii=False),
                           budget_min=budget_min, budget_max=budget_max)
        db.session.add(p)
        db.session.commit()
        return p
    return _make


@pytest.fixture
def tenders_app(app):
    """대시보드·신고 API 가 있는 앱 (routes.tenders 블루프린트 등록)."""
    from routes.tenders import bp
    app.register_blueprint(bp)
    return app


class FakeEncoder:
    """실제 모델 대신 쓰는 인코더: 제목에 든 주제어로 축을 고른다 (같은 주제면 거의 같은 벡터)."""
    TOPICS = ('교육', '공공앱', '청소', '건설')

    def encode(self, titles, **kw):
        import numpy as np
        out = np.zeros((len(titles), 768), dtype=np.float32)
        for i, t in enumerate(titles):
            axis = next((k for k, w in enumerate(self.TOPICS) if w in t), len(self.TOPICS))
            out[i, axis] = 1.0
            out[i, 10 + (abs(hash(t)) % 100)] = 0.1
        return out


@pytest.fixture
def fake_model(monkeypatch, tmp_path):
    """임베딩 모델과 벡터 DB 를 가짜·임시로 바꾼다."""
    import scoring
    import tender_vectors
    enc = FakeEncoder()
    monkeypatch.setattr(scoring, '_get_embed_model', lambda block=False: enc)
    monkeypatch.setattr(tender_vectors, 'VEC_DB_PATH', str(tmp_path / 'vectors.db'))
    return enc


@pytest.fixture
def cases_app(tenders_app):
    from routes.cases import bp
    tenders_app.register_blueprint(bp)
    return tenders_app


@pytest.fixture
def vec_db(tmp_path):
    """임시 벡터 DB 연결. tender_vectors.store 로 벡터를 직접 넣어 쓴다."""
    import tender_vectors
    conn = tender_vectors.connect(str(tmp_path / 'vec_fixture.db'))
    yield conn
    conn.close()


@pytest.fixture
def bookmark(app):
    def _bm(user, tender):
        from database import Bookmark
        db.session.add(Bookmark(user_id=user.id, tender_id=tender.id))
        db.session.commit()
    return _bm


@pytest.fixture
def add_mark(app):
    def _add(user, agency_name, mark):
        from database import AgencyWeight
        row = AgencyWeight(user_id=user.id, agency_name=agency_name, mark=mark)
        db.session.add(row)
        db.session.commit()
        return row
    return _add


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def login(client):
    def _login(user):
        with client.session_transaction() as s:
            s['user_id'] = user.id
    return _login
