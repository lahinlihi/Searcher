"""예전 발주처 가중치(0~10, 5 가 기준)를 새 표시(중점 / 후순위)로 옮긴다 (제품 계약서 3부 22.4).

    python tools/agency_mark_migrate.py [--db data/tenders.db]            표만 출력 (아무것도 쓰지 않는다)
    python tools/agency_mark_migrate.py [--db data/tenders.db] --apply    표시가 비어 있는 행에만 쓴다

옮기는 규칙: 5 보다 크면(7.5, 10) 중점, 5 보다 작으면(0, 2.5) 후순위, 5 이거나 값이 없으면 표시 없음.
예전 값(weight)은 지우지 않는다. 사용자가 표를 확인하기 전에는 --apply 를 돌리지 않는다.
"""
import os
import sqlite3
import sys

DEFAULT_DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'tenders.db')
LABEL = {'key': '중점', 'low': '후순위', None: '표시 없음'}


def old_to_mark(weight):
    if weight is None:
        return None
    w = float(weight)
    return 'key' if w > 5 else 'low' if w < 5 else None


def rows(conn):
    """[(행 id, 계정 id, 발주처, 예전 값, 지금 표시)]. mark 칸이 아직 없는 DB 도 읽는다."""
    cols = {r[1] for r in conn.execute('PRAGMA table_info(agency_weights)')}
    mark = 'mark' if 'mark' in cols else 'NULL'
    return conn.execute(f'SELECT id, user_id, agency_name, weight, {mark} FROM agency_weights '
                        'ORDER BY user_id, agency_name').fetchall(), 'mark' in cols


def main(argv):
    path = argv[argv.index('--db') + 1] if '--db' in argv else DEFAULT_DB
    apply = '--apply' in argv
    uri = 'file:%s?mode=%s' % (path.replace('\\', '/'), 'rw' if apply else 'ro')
    conn = sqlite3.connect(uri, uri=True, timeout=30)
    try:
        data, has_column = rows(conn)
        print('계정 | 발주처 | 예전 값 | 새 표시 | 비고')
        todo = []
        for rid, uid, name, weight, mark in data:
            new = old_to_mark(weight)
            note = ''
            if mark is not None:
                note = f'이미 {LABEL.get(mark, mark)} 로 등록됨 — 건드리지 않음'
            elif new is not None:
                todo.append((new, rid))
            old = '없음' if weight is None else f'{weight:g}'
            print(f'{uid} | {name} | {old} | {LABEL[new]} | {note}')
        print(f'\n등록 {len(data)}건, 표시를 쓸 것 {len(todo)}건')
        if not apply:
            print('표만 출력했습니다. 쓰려면 --apply 를 붙입니다.')
            return 0
        if not has_column:
            print('이 DB 에는 아직 mark 칸이 없습니다. 서버를 새 코드로 한 번 띄운 뒤(칸이 자동으로 생깁니다) 다시 돌리세요.')
            return 1
        conn.executemany('UPDATE agency_weights SET mark = ? WHERE id = ? AND mark IS NULL', todo)
        conn.commit()
        print(f'{len(todo)}건에 표시를 썼습니다.')
        return 0
    finally:
        conn.close()


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    sys.exit(main(sys.argv[1:]))
