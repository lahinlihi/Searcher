from datetime import datetime, timedelta

import numpy as np

import case_eval
import case_store
import tender_vectors as tv
from database import Tender


class TopicEncoder:
    def encode(self, titles, **kw):
        out = np.zeros((len(titles), tv.DIM), dtype=np.float32)
        for i, t in enumerate(titles):
            out[i, 0 if '교육' in t else 1 if '공공앱' in t else 2] = 1.0
            out[i, 10 + (abs(hash(t)) % 100)] = 0.1
        return out


def _setup(tmp_path):
    conn = tv.connect(str(tmp_path / 'v.db'))
    return conn


def _vectorize_all(conn):
    tv.ensure(conn, Tender.query.all(), encoder=TopicEncoder())


def _answers(u, make_tender, n, title='공공앱 운영 용역', when=None):
    when = when or datetime.now()
    ts = [make_tender(title=f'{title} {i}', created_at=when) for i in range(n)]
    for t in ts:
        case_store.add_case(u.id, t.id, 'report')
    return ts


def test_evaluate_no_answers(app, make_user, tmp_path):
    u = make_user()
    r = case_eval.evaluate(u.id, vec_conn=_setup(tmp_path), encoder=TopicEncoder(), save=False)
    assert r['answers'] == 0
    assert r['filtered']['case']['median'] is None and r['all']['case']['n'] == 0


def test_evaluate_case_beats_current_on_keywordless_answers(app, make_user, make_prefs, make_tender, tmp_path):
    u = make_user(); make_prefs(u, interest=['교육'])
    _answers(u, make_tender, 6)
    for i in range(100):
        make_tender(title=f'교육 운영 {i}')
    conn = _setup(tmp_path); _vectorize_all(conn)
    r = case_eval.evaluate(u.id, vec_conn=conn, encoder=TopicEncoder(), save=False)
    assert r['answers'] == 6 and r['cases'] == 6
    assert r['all']['current']['n'] == 6 and r['all']['case']['n'] == 6
    assert r['all']['case']['median'] < r['all']['current']['median']
    assert r['all']['current']['median'] > 100          # 키워드 없는 정답은 현재 방식에서 0점 → 맨 뒤
    assert r['all']['case']['top100'] == 6
    assert r['filtered']['current']['n'] == 0


def test_evaluate_window(app, make_user, make_prefs, make_tender, tmp_path):
    u = make_user(); make_prefs(u, interest=['교육'])
    _answers(u, make_tender, 6)
    far = datetime.now() - timedelta(days=20)
    for i in range(50):
        make_tender(title=f'교육 운영 {i}', created_at=far)
    conn = _setup(tmp_path); _vectorize_all(conn)
    r = case_eval.evaluate(u.id, vec_conn=conn, encoder=TopicEncoder(), save=False)
    assert r['all']['current']['median'] <= 6           # 20일 떨어진 공고는 후보가 아니다


def test_evaluate_skips_result_notices(app, make_user, make_prefs, make_tender, tmp_path):
    u = make_user(); make_prefs(u, interest=['교육'])
    _answers(u, make_tender, 6)
    for i in range(50):
        make_tender(title=f'교육 운영 결과 {i}', status='결과공고')
    conn = _setup(tmp_path); _vectorize_all(conn)
    r = case_eval.evaluate(u.id, vec_conn=conn, encoder=TopicEncoder(), save=False)
    assert r['all']['current']['median'] <= 6


def test_evaluate_counts_missing_vectors(app, make_user, make_prefs, make_tender, tmp_path):
    u = make_user(); make_prefs(u, interest=['교육'])
    _answers(u, make_tender, 6)
    conn = _setup(tmp_path); _vectorize_all(conn)
    for i in range(4):
        make_tender(title=f'교육 벡터없음 {i}')
    r = case_eval.evaluate(u.id, vec_conn=conn, encoder=TopicEncoder(), save=False)
    assert r['missing_vectors'] == 4


def test_evaluate_filtered_counts_only_passing(app, make_user, make_prefs, make_tender, tmp_path):
    u = make_user(); make_prefs(u, interest=['교육'])
    _answers(u, make_tender, 3, title='교육 과정 위탁')
    _answers(u, make_tender, 3, title='공공앱 운영')
    conn = _setup(tmp_path); _vectorize_all(conn)
    r = case_eval.evaluate(u.id, vec_conn=conn, encoder=TopicEncoder(), save=False)
    assert r['filtered']['current']['n'] == 3 and r['filtered']['case']['n'] == 3
    assert r['all']['current']['n'] == 6


def test_evaluate_saves_run(app, make_user, make_prefs, make_tender, tmp_path):
    u = make_user(); make_prefs(u, interest=['교육'])
    _answers(u, make_tender, 6)
    conn = _setup(tmp_path); _vectorize_all(conn)
    r = case_eval.evaluate(u.id, vec_conn=conn, encoder=TopicEncoder(), save=True)
    assert case_store.latest_eval(u.id)['metrics'] == r
