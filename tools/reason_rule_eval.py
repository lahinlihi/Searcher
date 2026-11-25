"""자격 확인 규칙 후보가 얼마나 맞는지 잰다 (제품 계약서 5부 37절). 읽기 전용.

    python tools/reason_rule_eval.py --user N [--db data/tenders.db] [--split YYYY-MM-DD]

같은 자료로 규칙을 만들고 같은 자료에 대면 늘 좋게 나온다. 그래서 시간으로 나눈다:
  --split 보다 먼저 들어온 공고에 남긴 이유로만 규칙 후보를 만들고(반례도 그 공고들 가운데 담았거나 '자격 가능'으로 남긴 것만),
  그 뒤에 들어온 공고에 대어 본다.
나누는 기준은 이유를 붙인 날이 아니라 **공고가 수집된 날**이다 — 예전 메모에 이유를 한자리에서 붙이면
이유를 붙인 날은 전부 같은 날이 되기 때문이다. --split 을 생략하면 판정이 있는 공고의 수집일 가운데 값을 쓴다.

정밀도 = 규칙이 잡은 공고 가운데 실제로 못 하는 공고(자격이 안 됨·사업영역이 다름)의 비율.
  - 할 수 있는 공고 = 담았거나 '자격 가능'으로 남긴 공고.
  - 금액·취소·기타만 남긴 공고는 자격을 모르는 공고라 세지 않는다.
0.8 아래면 reasons.MIN_EVIDENCE 를 올리는 것을 검토한다.
참고: 운영 화면은 관심 키워드와 겹치는 낱말, 진행 중 공고가 너무 많이 걸리는 낱말을 더 걸러 낸다. 이 도구는 그 전 단계를 잰다.
"""
import os
import sqlite3
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import reasons  # noqa: E402

DEFAULT_DB = os.path.join(ROOT, 'data', 'tenders.db')


def evaluate(train, positives_train, test, interest=()):
    """train: [(제목, 이유)], positives_train: [반례 제목], test: [(제목, 못 하는 공고인가)].
    반환: {'rules': [{'reason', 'word', 'evidence', 'caught', 'bad'}], 'caught', 'bad', 'precision'}"""
    docs = {}
    for i, (title, reason) in enumerate(train):
        docs.setdefault(reason, []).append((i, title))
    mined = reasons.mine_words(docs, [reasons.norm(t) for t in positives_train], [reasons.norm(k) for k in interest])
    norms = [(reasons.norm(title), bool(bad)) for title, bad in test]
    rules, hit = [], set()
    for reason, words, evidence in mined:
        ws = [reasons.norm(w) for w in words]
        caught = [i for i, (n, _) in enumerate(norms) if all(w in n for w in ws)]
        hit.update(caught)
        rules.append({'reason': reason, 'word': ' + '.join(words), 'words': words, 'evidence': len(evidence),
                      'caught': len(caught), 'bad': sum(norms[i][1] for i in caught)})
    bad = sum(norms[i][1] for i in hit)
    return {'rules': rules, 'caught': len(hit), 'bad': bad,
            'precision': round(bad / len(hit), 3) if hit else None}


def main(argv):
    def arg(name, default=None):
        return argv[argv.index(name) + 1] if name in argv else default
    if '--user' not in argv:
        print(__doc__)
        return 1
    uid = int(arg('--user'))
    conn = sqlite3.connect('file:%s?mode=ro' % arg('--db', DEFAULT_DB).replace('\\', '/'), uri=True, timeout=30)
    try:
        rows = conn.execute('SELECT r.tender_id, r.reason, substr(t.created_at, 1, 10), t.title FROM tender_reasons r '
                            'JOIN tenders t ON t.id = r.tender_id WHERE r.user_id = ?', (uid,)).fetchall()
        marks = conn.execute('SELECT b.tender_id, substr(t.created_at, 1, 10), t.title FROM bookmarks b '
                             'JOIN tenders t ON t.id = b.tender_id WHERE b.user_id = ?', (uid,)).fetchall()
    except sqlite3.OperationalError as e:
        print(f'자료를 읽지 못했습니다 (이유 칩 표가 아직 없는 DB 일 수 있습니다): {e}')
        return 1
    finally:
        conn.close()
    if not rows:
        print(f'계정 {uid} 가 남긴 이유가 없습니다. 아직 잴 자료가 없습니다.')
        return 0
    # 공고마다: 수집일, 제목, 남긴 판정들
    seen = {}
    for tid, reason, day, title in rows:
        seen.setdefault(tid, [day or '', title or '', set()])[2].add(reason)
    for tid, day, title in marks:
        seen.setdefault(tid, [day or '', title or '', set()])[2].add('bookmarked')

    def verdict(rs):        # True = 못 하는 공고, False = 할 수 있는 공고, None = 자격을 모른다
        if 'eligible' in rs or 'bookmarked' in rs:
            return False
        if any(r in reasons.RULE_REASONS for r in rs):
            return True
        return None

    judged = sorted(day for day, _, rs in seen.values() if verdict(rs) is not None)
    if not judged:
        print('자격을 알 수 있는 판정(자격이 안 됨·사업영역이 다름·자격 가능·담음)이 없습니다. 아직 잴 자료가 없습니다.')
        return 0
    split = arg('--split', judged[len(judged) // 2])
    train = [(title, r) for day, title, rs in seen.values() if day < split and verdict(rs) is True
             for r in rs if r in reasons.RULE_REASONS]
    positives = [title for day, title, rs in seen.values() if day < split and verdict(rs) is False]
    test = [(title, verdict(rs)) for day, title, rs in seen.values() if day >= split and verdict(rs) is not None]
    result = evaluate(train, positives, test)
    print(f'계정 {uid}, 나눈 날(공고 수집일) {split}: 규칙을 만든 이유 {len(train)}건, 반례 {len(positives)}건, 대어 본 공고 {len(test)}건 '
          f'(그중 못 하는 공고 {sum(b for _, b in test)}건)')
    for r in result['rules']:
        label = reasons.REASONS[r['reason']]['label']
        print(f"  \"{r['word']}\" → {label}: 근거 {r['evidence']}건, 잡은 공고 {r['caught']}건 중 못 하는 공고 {r['bad']}건")
    if result['precision'] is None:
        print('규칙이 잡은 공고가 없어 정밀도를 낼 수 없습니다.' if result['rules'] else '규칙 후보가 생기지 않았습니다 (같은 이유 3건 이상이 필요합니다).')
    else:
        print(f"전체: 잡은 공고 {result['caught']}건 중 못 하는 공고 {result['bad']}건 — 정밀도 {result['precision']}")
    return 0


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    sys.exit(main(sys.argv[1:]))
