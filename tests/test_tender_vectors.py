import numpy as np
import pytest

import scoring
import tender_vectors as tv


class FakeEncoder:
    """제목마다 고정된 난수 벡터. 호출된 제목을 기록한다."""
    def __init__(self):
        self.calls = []

    def encode(self, titles, **kw):
        self.calls.extend(titles)
        out = []
        for t in titles:
            rng = np.random.default_rng(abs(hash(t)) % (2 ** 32))
            out.append(rng.normal(size=tv.DIM).astype(np.float32) * 3)
        return np.array(out)


def test_encode_normalized():
    v = tv.encode(['가', '나'], encoder=FakeEncoder())
    assert v.shape == (2, tv.DIM) and v.dtype == np.float32
    assert np.allclose(np.linalg.norm(v, axis=1), 1.0, atol=1e-5)


def test_store_load_roundtrip(tmp_path):
    conn = tv.connect(str(tmp_path / 'v.db'))
    v = tv.encode(['가', '나'], encoder=FakeEncoder())
    tv.store(conn, [1, 2], v)
    got = tv.load(conn, [1, 2])
    assert np.allclose(got[1], v[0], atol=1e-3) and np.allclose(got[2], v[1], atol=1e-3)


def test_load_missing_ids_absent(tmp_path):
    conn = tv.connect(str(tmp_path / 'v.db'))
    tv.store(conn, [1], tv.encode(['가'], encoder=FakeEncoder()))
    assert set(tv.load(conn, [1, 999])) == {1}


def test_ensure_encodes_only_missing(tmp_path, app, make_tender):
    conn = tv.connect(str(tmp_path / 'v.db'))
    a, b = make_tender(title='있는 공고'), make_tender(title='없는 공고')
    enc = FakeEncoder()
    tv.store(conn, [a.id], tv.encode([a.title], encoder=enc))
    enc.calls.clear()
    got = tv.ensure(conn, [a, b], encoder=enc)
    assert set(got) == {a.id, b.id}
    assert enc.calls == ['없는 공고']
    assert set(tv.load(conn, [b.id])) == {b.id}


def test_ensure_without_model_returns_existing(tmp_path, app, make_tender, monkeypatch):
    conn = tv.connect(str(tmp_path / 'v.db'))
    a, b = make_tender(title='있는 공고'), make_tender(title='없는 공고')
    tv.store(conn, [a.id], tv.encode([a.title], encoder=FakeEncoder()))
    monkeypatch.setattr(scoring, '_get_embed_model', lambda block=False: None)
    got = tv.ensure(conn, [a, b])
    assert set(got) == {a.id}


def test_encode_without_model_raises(monkeypatch):
    monkeypatch.setattr(scoring, '_get_embed_model', lambda block=False: None)
    with pytest.raises(tv.EmbeddingUnavailable):
        tv.encode(['가'])


def test_encode_is_serialized_across_threads():
    """같은 모델을 두 스레드가 동시에 쓰지 않는다 (fast tokenizer 의 'Already borrowed' 방지)."""
    import threading
    import time
    state = {'now': 0, 'max': 0}
    lock = threading.Lock()

    class SlowEncoder(FakeEncoder):
        def encode(self, titles, **kw):
            with lock:
                state['now'] += 1
                state['max'] = max(state['max'], state['now'])
            time.sleep(0.2)
            with lock:
                state['now'] -= 1
            return super().encode(titles)

    enc = SlowEncoder()
    ts = [threading.Thread(target=tv.encode, args=([f'제목{i}'],), kwargs={'encoder': enc}) for i in range(3)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert state['max'] == 1


def test_encode_missing_newest_first(tmp_path):
    """크롤 훅은 방금 들어온 공고부터 채운다 (일괄 채우기 전에도 새 공고에 벡터가 생기게)."""
    import sqlite3
    main = tmp_path / 'main.db'
    c = sqlite3.connect(main)
    c.execute('CREATE TABLE tenders (id INTEGER PRIMARY KEY, title TEXT)')
    c.executemany('INSERT INTO tenders VALUES (?, ?)', [(i, f'제목 {i}') for i in range(1, 11)])
    c.commit(); c.close()
    vpath = str(tmp_path / 'v.db')
    n = tv.encode_missing(batch=2, max_seconds=0, path=vpath, main_path=str(main),
                          encoder=FakeEncoder(), newest_first=True)
    assert n == 2
    assert set(tv.load(tv.connect(vpath), range(1, 11))) == {9, 10}


def test_encode_missing_fills_from_main_db(tmp_path):
    import sqlite3
    main = tmp_path / 'main.db'
    c = sqlite3.connect(main)
    c.execute('CREATE TABLE tenders (id INTEGER PRIMARY KEY, title TEXT)')
    c.executemany('INSERT INTO tenders VALUES (?, ?)', [(i, f'제목 {i}') for i in range(1, 8)])
    c.commit(); c.close()
    vpath = str(tmp_path / 'v.db')
    conn = tv.connect(vpath)
    tv.store(conn, [3], tv.encode(['제목 3'], encoder=FakeEncoder()))
    enc = FakeEncoder()
    n = tv.encode_missing(batch=2, path=vpath, main_path=str(main), encoder=enc)
    assert n == 6
    assert '제목 3' not in enc.calls
    assert set(tv.load(conn, range(1, 8))) == set(range(1, 8))
