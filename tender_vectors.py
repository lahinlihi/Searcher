"""공고 제목 벡터 저장소 (사례로 배우는 점수용).

벡터는 본 DB(data/tenders.db)가 아니라 data/vectors.db 에 따로 둔다.
본 DB 를 두 배 가까이 키우지 않고, 크롤의 쓰기와 같은 파일에서 부딪히지 않게 하려는 것이다.
float16 으로 저장하고(768차원 → 1.5KB), 읽을 때 float32 로 되돌린다. 저장하는 벡터는 길이 1로 정규화돼 있다.

일괄 채우기: python -u tender_vectors.py --backfill [--max-minutes N]
"""
import os
import sqlite3
import sys
import time

import numpy as np

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
VEC_DB_PATH = os.path.join(BASE_DIR, 'data', 'vectors.db')
MAIN_DB_PATH = os.path.join(BASE_DIR, 'data', 'tenders.db')
MODEL_NAME = 'jhgan/ko-sroberta-multitask'
DIM = 768


class EmbeddingUnavailable(RuntimeError):
    """임베딩 모델을 불러오지 못했다."""


def connect(path=None):
    conn = sqlite3.connect(path or VEC_DB_PATH, timeout=30)
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('CREATE TABLE IF NOT EXISTS tender_vecs ('
                 'tender_id INTEGER PRIMARY KEY, model TEXT NOT NULL, vec BLOB NOT NULL)')
    conn.commit()
    return conn


def _model(encoder):
    if encoder is not None:
        return encoder
    import scoring
    m = scoring._get_embed_model(block=True)
    if m is None:
        raise EmbeddingUnavailable('임베딩 모델을 불러오지 못했습니다')
    return m


def encode(titles, encoder=None):
    """제목 목록 → (n, 768) float32, 행마다 길이 1."""
    if not titles:
        return np.zeros((0, DIM), dtype=np.float32)
    m = _model(encoder)
    import scoring
    with scoring.embed_encode_lock:      # 대시보드 요청·크롤 훅·기존 임베딩 점수가 같은 모델을 쓴다
        v = np.asarray(m.encode(list(titles), batch_size=128, show_progress_bar=False), dtype=np.float32)
    norms = np.linalg.norm(v, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return v / norms


def store(conn, ids, vecs):
    rows = [(int(i), MODEL_NAME, np.asarray(v, dtype=np.float16).tobytes()) for i, v in zip(ids, vecs)]
    conn.executemany('INSERT OR REPLACE INTO tender_vecs (tender_id, model, vec) VALUES (?, ?, ?)', rows)
    conn.commit()


def load(conn, ids):
    ids = [int(i) for i in ids]
    out = {}
    for k in range(0, len(ids), 900):          # sqlite 변수 개수 한도 아래로 나눠 읽는다
        chunk = ids[k:k + 900]
        q = 'SELECT tender_id, vec FROM tender_vecs WHERE tender_id IN (%s)' % ','.join('?' * len(chunk))
        for tid, blob in conn.execute(q, chunk):
            out[tid] = np.frombuffer(blob, dtype=np.float16).astype(np.float32)
    return out


def ensure(conn, tenders, encoder=None):
    """공고들의 벡터를 돌려준다. 없는 것만 인코딩해 저장한다. 모델이 없으면 있는 것만 돌려준다."""
    got = load(conn, [t.id for t in tenders])
    missing = [t for t in tenders if t.id not in got]
    if missing:
        try:
            v = encode([t.title or '' for t in missing], encoder=encoder)
        except EmbeddingUnavailable:
            return got
        store(conn, [t.id for t in missing], v)
        got.update({t.id: v[i] for i, t in enumerate(missing)})
    return got


def encode_missing(batch=512, max_seconds=None, path=None, main_path=None, encoder=None, progress=False,
                   newest_first=False):
    """본 DB 에서 벡터가 없는 공고를 채운다. 채운 건수를 돌려준다.
    newest_first=True 면 id 가 큰(최근) 공고부터 — 크롤 훅용. 일괄 채우기 전이라도 방금 들어온 공고부터 벡터가 생긴다."""
    started = time.time()
    conn = connect(path)
    have = {r[0] for r in conn.execute('SELECT tender_id FROM tender_vecs')}
    main = sqlite3.connect('file:%s?mode=ro' % (main_path or MAIN_DB_PATH).replace('\\', '/'), uri=True, timeout=30)
    filled, next_report = 0, 1000
    last_id = 2 ** 62 if newest_first else 0
    sql = ('SELECT id, title FROM tenders WHERE id < ? ORDER BY id DESC LIMIT ?' if newest_first
           else 'SELECT id, title FROM tenders WHERE id > ? ORDER BY id LIMIT ?')
    try:
        while True:
            rows = main.execute(sql, (last_id, batch)).fetchall()
            if not rows:
                break
            last_id = rows[-1][0]
            todo = [(i, t) for i, t in rows if i not in have]
            if todo:
                v = encode([t or '' for _, t in todo], encoder=encoder)
                store(conn, [i for i, _ in todo], v)
                filled += len(todo)
                if progress and filled >= next_report:
                    print(f'[벡터] {filled}건 저장 (id {last_id}까지, {time.time() - started:.0f}초)', flush=True)
                    next_report += 1000
            if max_seconds is not None and time.time() - started > max_seconds:
                break
    finally:
        main.close()
        conn.close()
    return filled


if __name__ == '__main__':
    if '--backfill' not in sys.argv:
        print(__doc__)
        sys.exit(1)
    max_minutes = None
    if '--max-minutes' in sys.argv:
        max_minutes = float(sys.argv[sys.argv.index('--max-minutes') + 1])
    t0 = time.time()
    n = encode_missing(max_seconds=max_minutes * 60 if max_minutes else None, progress=True)
    print(f'[벡터] 일괄 채우기 끝: {n}건, {time.time() - t0:.0f}초', flush=True)
