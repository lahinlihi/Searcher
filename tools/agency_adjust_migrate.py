"""예전 발주처 가중치(0~10, 5 가 기준)를 새 가감점(−30~+30)으로 옮긴다 (제품 계약서 3부 22.4).

    python tools/agency_adjust_migrate.py [--db data/tenders.db]            표만 출력 (아무것도 쓰지 않는다)
    python tools/agency_adjust_migrate.py [--db data/tenders.db] --apply    adjust 가 비어 있는 행에만 쓴다

옮기는 식: 새 가감점 = (예전 값 − 5) × 4   →   0 → −20, 2.5 → −10, 5 → 0, 7.5 → +10, 10 → +20
예전 값(weight)은 지우지 않는다. 사용자가 표를 확인하기 전에는 --apply 를 돌리지 않는다.
"""
import os
import sqlite3
import sys

DEFAULT_DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'tenders.db')


def old_to_new(weight):
    if weight is None:
        return 0.0
    return (float(weight) - 5.0) * 4.0


def rows(conn):
    """[(행 id, 계정 id, 발주처, 예전 값, 지금 가감점)]. adjust 칸이 아직 없는 DB 도 읽는다."""
    cols = {r[1] for r in conn.execute('PRAGMA table_info(agency_weights)')}
    adjust = 'adjust' if 'adjust' in cols else 'NULL'
    return conn.execute(f'SELECT id, user_id, agency_name, weight, {adjust} FROM agency_weights '
                        'ORDER BY user_id, agency_name').fetchall()


def main(argv):
    path = argv[argv.index('--db') + 1] if '--db' in argv else DEFAULT_DB
    apply = '--apply' in argv
    uri = 'file:%s?mode=%s' % (path.replace('\\', '/'), 'rw' if apply else 'ro')
    conn = sqlite3.connect(uri, uri=True, timeout=30)
    try:
        data = rows(conn)
        print('계정 | 발주처 | 예전 값 | 새 가감점 | 비고')
        todo = []
        for rid, uid, name, weight, adjust in data:
            new = old_to_new(weight)
            note = '' if adjust is None else f'이미 {adjust:+g} 로 등록됨 — 건드리지 않음'
            if adjust is None:
                todo.append((new, rid))
            print(f'{uid} | {name} | {weight:g} | {new:+g} | {note}')
        print(f'\n등록 {len(data)}건, 옮길 것 {len(todo)}건')
        if not apply:
            print('표만 출력했습니다. 쓰려면 --apply 를 붙입니다.')
            return 0
        conn.executemany('UPDATE agency_weights SET adjust = ? WHERE id = ? AND adjust IS NULL', todo)
        conn.commit()
        print(f'{len(todo)}건에 가감점을 썼습니다.')
        return 0
    finally:
        conn.close()


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    sys.exit(main(sys.argv[1:]))
