# -*- coding: utf-8 -*-
"""
HR뉴스 수집·토픽 선정기 — NAVER API HUB 검색 API 기반

설계 근거 (전부 실측, 2026-09-22)

  1) sort=sim + sort=date 병합
     sim 단독 489건 → 병합 1,002건 (+105%). date 에서만 나오는 기사가
     검색어당 72~94건. sim 은 품질순, date 는 최신 커버리지로 역할이 다르다.
     sim 순위를 sim_rank 로 보관해 품질 신호로 쓴다.

  2) description = 검색어 매칭 구간 '패시지' (요약이 아님, 115~124자)
     같은 기사에 각도를 바꿔 질의하면 서로 다른 구간이 반환된다.
     6각도 → 고유 조각 합성 342~357자. 쟁점·형량구간·인물까지 확보됨.

  3) 패시지는 내부에 '...' 로 비연속 조각을 이어붙인다.
     따라서 중복 제거는 문자열 전체가 아니라 **조각 단위**가 올바른 granularity.

  4) 매체 수만으로는 보도자료 살포와 실제 이슈를 구분할 수 없다.
     실측: "반도건설 무재해 100일 운동" 이 12개 매체로 1위였으나 전부 전문지.
     실제 뉴스는 통신사·지상파·전국일간이 섞인다 → 매체 등급으로 판별한다.

  5) originallink 로 언론사 원문 URL 확보 (구글 뉴스 RSS는 인코딩되어 불가)

저작권 경계 — 코드로 강제
  패시지는 '분석 재료'로만 쓴다. 발송물에는 제목·출처·링크와 자체 작성 문장만
  싣는다. render_for_newsletter() 가 패시지를 반환하지 않는다.

스케줄러 등록 완료 — 매일 hr_news.time (기본 07:30) 에 run_hr_news_job 실행.
설정은 data/settings.json 의 hr_news 항목: enabled / time / days / deep_topics / queries.
검색어는 settings.json 이 단일 출처이며 코드 상수는 폴백이다.

사용:
    python hr_news.py                      # 수집 (sim+date 병합)
    python hr_news.py --topics             # 토픽 순위만 확인
    python hr_news.py --auto               # 수집 → 토픽 선정 → 상위 자동 심화
    python hr_news.py --deep "중대재해 양형기준"  # 특정 토픽 수동 심화
    python hr_news.py --stats
"""
import argparse
import json
import os
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timedelta, timezone

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env'))
except ImportError:
    pass

HUB = 'https://naverapihub.apigw.ntruss.com'
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'tenders.db')
KST = timezone(timedelta(hours=9))

DEFAULT_QUERIES = [
    '채용 트렌드', '최저임금', '직업훈련', '근로시간 개편', '중대재해',
    '노동정책', '정년연장', '주 4.5일제', '육아휴직', 'AI 채용',
    '인재개발', '직무교육', '고용노동부',
]

# 같은 사건에 붙여 서로 다른 본문 구간을 끌어내는 각도
DEEP_ANGLES = ['', '쟁점', '전망', '시행', '기준', '반응', '영향', '대상']

# ── 매체 등급 ──────────────────────────────────────────────────────────────
# 보도자료 살포와 실제 이슈를 구분하는 유일한 실효 신호 (설계 근거 4)
TIER1 = {  # 통신사·지상파
    'yna.co.kr', 'yonhapnewstv.co.kr', 'newsis.com', 'news1.kr',
    'kbs.co.kr', 'imbc.com', 'sbs.co.kr', 'ytn.co.kr', 'jtbc.co.kr',
    'nocutnews.co.kr', 'tvchosun.com', 'channela.co.kr', 'mbn.co.kr',
}
TIER2 = {  # 전국일간·경제지·노동전문
    'chosun.com', 'joongang.co.kr', 'donga.com', 'hani.co.kr', 'khan.co.kr',
    'seoul.co.kr', 'munhwa.com', 'kmib.co.kr', 'segye.com', 'hankookilbo.com',
    'mk.co.kr', 'hankyung.com', 'mt.co.kr', 'edaily.co.kr', 'fnnews.com',
    'heraldcorp.com', 'sedaily.com', 'etnews.com', 'asiae.co.kr',
    'ajunews.com', 'labortoday.co.kr', 'hankyung.co.kr', 'joins.com',
    'ohmynews.com', 'pressian.com', 'dt.co.kr', 'zdnet.co.kr',
}

NOISE_SOURCE = re.compile(r'vietnam|\.vn$|vn\.', re.I)
NOISE_TITLE = re.compile(r'교도소|위문금|나들이|장보기|브리핑 모음|소식 모음|'
                         r'부고|인사말|주가|증시|코스피|환율')

STOP = set(
    '그리고 그러나 위해 통해 대한 관련 오늘 내년 올해 지난 등 및 새 더 또 만 '
    '년 월 일 이번 특히 대해 따라 대상 기준 방안 계획 추진 확대 지원 개최 '
    '실시 진행 발표 밝혔다 했다 한다 위한 있다 없다 하는 되는 오전 오후'.split())


# ════════════════════════════════════════════════════════════ 유틸

def _keys():
    kid, key = os.getenv('NCP_API_KEY_ID'), os.getenv('NCP_API_KEY')
    if not (kid and key):
        sys.exit('NCP_API_KEY_ID / NCP_API_KEY 가 .env 에 없습니다. '
                 'check_naver_api.py 로 확인하세요.')
    return {'X-NCP-APIGW-API-KEY-ID': kid, 'X-NCP-APIGW-API-KEY': key}


_ENT = {'&quot;': '"', '&amp;': '&', '&lt;': '<', '&gt;': '>',
        '&apos;': "'", '&#39;': "'", '&nbsp;': ' '}


def clean(s):
    s = re.sub(r'<[^>]+>', '', s or '')
    for a, b in _ENT.items():
        s = s.replace(a, b)
    return re.sub(r'\s+', ' ', s).strip()


def source_of(link):
    try:
        host = urllib.parse.urlparse(link).netloc.lower()
    except Exception:
        return ''
    return re.sub(r'^(www|news|biz|m|n|v|app|star|sports|land|realty)\.', '', host)


def tier_of(source):
    """1=통신사·지상파, 2=전국일간·경제지, 3=전문지·기타"""
    if source in TIER1:
        return 1
    if source in TIER2:
        return 2
    return 3


def parse_date(s):
    for fmt in ('%a, %d %b %Y %H:%M:%S %z', '%a, %d %b %Y %H:%M:%S %Z'):
        try:
            dt = datetime.strptime(s, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(KST)
        except (ValueError, TypeError):
            continue
    return None


def tokens(s):
    return {w for w in re.findall(r'[가-힣A-Za-z0-9]{2,}', s or '')
            if w not in STOP and not w.isdigit()}


def search(query, display=100, sort='sim', start=1, headers=None, retries=2):
    headers = headers or _keys()
    qs = urllib.parse.urlencode({'query': query, 'display': min(display, 100),
                                 'start': start, 'sort': sort, 'format': 'json'})
    url = f'{HUB}/search/v1/news?{qs}'
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(
                    urllib.request.Request(url, headers=headers), timeout=25) as r:
                return json.load(r).get('items', [])
        except urllib.error.HTTPError as e:
            raw = e.read().decode('utf-8', 'ignore')[:160]
            if e.code == 429 and attempt < retries:
                time.sleep(3 * (attempt + 1))
                continue
            print(f'  [{query}/{sort}] HTTP {e.code} {raw}')
            return []
        except Exception as e:
            if attempt < retries:
                time.sleep(2)
                continue
            print(f'  [{query}/{sort}] {type(e).__name__}: {e}')
            return []
    return []


# ════════════════════════════════════════════════════════════ 저장소

SCHEMA = """
CREATE TABLE IF NOT EXISTS hr_news (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    title         TEXT NOT NULL,
    source        TEXT,
    original_link TEXT NOT NULL UNIQUE,
    naver_link    TEXT,
    pub_date      TEXT,
    queries       TEXT NOT NULL DEFAULT '[]',
    passages      TEXT NOT NULL DEFAULT '{}',
    is_noise      INTEGER NOT NULL DEFAULT 0,
    collected_at  TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_hr_news_pub  ON hr_news(pub_date DESC);
CREATE INDEX IF NOT EXISTS idx_hr_news_coll ON hr_news(collected_at DESC);
CREATE INDEX IF NOT EXISTS idx_hr_news_noise ON hr_news(is_noise);
"""

MIGRATIONS = [
    ('sim_rank', 'ALTER TABLE hr_news ADD COLUMN sim_rank INTEGER'),
    ('tier', 'ALTER TABLE hr_news ADD COLUMN tier INTEGER NOT NULL DEFAULT 3'),
]


def connect():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    conn.executescript(SCHEMA)
    cols = {r[1] for r in conn.execute('PRAGMA table_info(hr_news)')}
    for col, ddl in MIGRATIONS:
        if col not in cols:
            conn.execute(ddl)
    conn.commit()
    return conn


def is_noise(title, source):
    return bool(NOISE_SOURCE.search(source or '') or NOISE_TITLE.search(title or ''))


def upsert(conn, rows):
    """original_link 기준 병합. queries/passages 누적, sim_rank 는 최솟값 유지."""
    now = datetime.now(KST).isoformat(timespec='seconds')
    new = updated = 0
    for r in rows:
        link = r['original_link']
        cur = conn.execute(
            'SELECT id, queries, passages, sim_rank FROM hr_news '
            'WHERE original_link = ?', (link,)).fetchone()
        if cur is None:
            conn.execute(
                """INSERT INTO hr_news
                   (title, source, original_link, naver_link, pub_date, queries,
                    passages, is_noise, sim_rank, tier, collected_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (r['title'], r['source'], link, r['naver_link'], r['pub_date'],
                 json.dumps(r['queries'], ensure_ascii=False),
                 json.dumps(r['passages'], ensure_ascii=False),
                 int(is_noise(r['title'], r['source'])), r.get('sim_rank'),
                 tier_of(r['source']), now, now))
            new += 1
        else:
            qs = sorted(set(json.loads(cur['queries'])) | set(r['queries']))
            ps = json.loads(cur['passages'])
            ps.update(r['passages'])
            ranks = [x for x in (cur['sim_rank'], r.get('sim_rank')) if x is not None]
            conn.execute(
                'UPDATE hr_news SET queries=?, passages=?, sim_rank=?, '
                'tier=?, updated_at=? WHERE id=?',
                (json.dumps(qs, ensure_ascii=False),
                 json.dumps(ps, ensure_ascii=False),
                 min(ranks) if ranks else None,
                 tier_of(r['source']), now, cur['id']))
            updated += 1
    conn.commit()
    return new, updated


# ════════════════════════════════════════════════════════════ 패시지 정제

_ELLIPSIS = re.compile(r'\s*(?:\.\.\.+|…+|\.\.)\s*')

# 합성 시 조각 경계를 드러내는 구분자 (원문의 연속 문장이 아님을 표시)
FRAGMENT_SEP = ' ⁄ '


def fragments(passage, min_len=12):
    """패시지를 '...' 기준 조각으로 분해 (설계 근거 3)"""
    return [f.strip() for f in _ELLIPSIS.split(passage or '')
            if len(f.strip()) >= min_len]


def _norm(s):
    return re.sub(r'[^가-힣A-Za-z0-9]', '', s or '')


def _grams(s, n=6):
    return {s[i:i + n] for i in range(max(0, len(s) - n + 1))}


def _near_duplicate(a, b, threshold=0.55):
    na, nb = _norm(a), _norm(b)
    if not na or not nb:
        return False
    if na in nb or nb in na:
        return True
    ga, gb = _grams(na), _grams(nb)
    u = len(ga | gb)
    return bool(u) and len(ga & gb) / u >= threshold


def stems(terms, n=2):
    """
    토픽어에서 앞 n글자 어간 추출.

    정확 토큰 일치는 한국어 복합어에서 실패한다. 실측: 토픽어 '양형기준' 과
    조각의 '양형위원회' 가 일치하지 않아 유효한 조각이 버려졌고
    정제 343자 → 필터 174자로 절반이 날아갔다. 어간 '양형' 으로 비교하면 걸린다.
    """
    out = set()
    for t in terms:
        if len(t) >= n:
            out.add(t[:n])
        if len(t) >= 2:
            out.add(t)
    return out


def is_relevant(fragment, topic_stems, title_stems):
    """
    조각이 토픽과 관련 있는가.

    실측 문제: 양형기준 기사의 패시지에 음주운전 '술타기' 조각이 섞였다.
    기사가 교통범죄 양형기준도 함께 다뤘기 때문으로 API 오류는 아니지만,
    시사점 생성 입력에 들어가면 엉뚱한 근거가 된다.

    판정: 토픽 또는 제목 어간이 조각 문자열에 하나라도 나타나면 관련.
    """
    if not fragment:
        return False
    pool = topic_stems | title_stems
    if not pool:
        return True
    return any(s in fragment for s in pool)


def analysis_material(row, topic=None, max_chars=1800, filter_topic=True):
    """
    시사점 생성용 입력 (내부 분석 전용).

    조각 단위 분해 → 토픽 관련성 필터 → 중복 제거 → 합성.
    이 반환값은 절대 발송물에 실리지 않는다.
    """
    passages = row['passages'] if isinstance(row['passages'], dict) \
        else json.loads(row['passages'] or '{}')
    qs = row['queries'] if isinstance(row['queries'], list) \
        else json.loads(row['queries'] or '[]')

    topic_terms = tokens(topic) if topic else set()
    if not topic_terms:
        for q in qs:
            topic_terms |= tokens(q)
    title_terms = tokens(row['title'])

    cands = []
    for p in passages.values():
        cands.extend(fragments(p))

    if filter_topic and (topic_terms or title_terms):
        ts, tls = stems(topic_terms), stems(title_terms)
        pool = ts | tls
        cands = [f for f in cands if is_relevant(f, ts, tls)]
        # 어휘 필터의 정밀도 한계 — 실측: "10년 내 재범 음주운전 범죄는 형이
        # 감경되더라도 징역형을..." 조각이 토픽어 '징역'을 실제로 포함해 통과한다.
        # 문맥 판별은 어휘로 불가능하므로 하드 배제 대신 관련도 순으로 배치하고,
        # max_chars 절단에서 약한 조각이 자연히 밀려나게 한다.
        # 최종 문맥 판별은 시사점 생성 단계(근거 인용 강제)에 맡긴다.
        cands.sort(key=lambda f: (-sum(1 for s in pool if s in f), -len(f)))
    else:
        cands.sort(key=len, reverse=True)
    uniq = []
    for f in cands:
        if not any(_near_duplicate(f, u) for u in uniq):
            uniq.append(f)
    # 조각 사이를 공백으로 이으면 원문에 없던 인접성이 생긴다.
    # 실측 사고: 기사 리드의 "중대재해 사망사고 발생 시" 와 본문의
    # "중대산업재해치상 기본 징역 1년~2년 6개월" 이 한 문장처럼 붙어,
    # 생성기가 치상의 형량을 치사(사망)에 잘못 귀속시켰다.
    # → 비연속 구간임을 드러내는 구분자로 잇는다. FRAGMENT_SEP 은
    #   프롬프트에서도 같은 의미로 설명한다.
    return FRAGMENT_SEP.join(uniq)[:max_chars]


def render_for_newsletter(row):
    """발송물용 — 제목·출처·링크·발행일만. 패시지 미포함 (저작권 경계)."""
    return {
        'title': row['title'],
        'source': row['source'],
        'link': row['original_link'],
        'pub_date': row['pub_date'],
    }


# ════════════════════════════════════════════════════════════ 수집

def _to_rows(items, query, sort):
    out = {}
    for rank, it in enumerate(items, 1):
        link = it.get('originallink') or it.get('link')
        if not link:
            continue
        title = clean(it.get('title'))
        if len(title) < 8:
            continue
        dt = parse_date(it.get('pubDate'))
        passage = clean(it.get('description'))
        out[link] = {
            'title': title,
            'source': source_of(link),
            'original_link': link,
            'naver_link': it.get('link') or '',
            'pub_date': dt.isoformat(timespec='seconds') if dt else None,
            'queries': [query],
            'passages': {query: passage} if passage else {},
            'sim_rank': rank if sort == 'sim' else None,
        }
    return out


def _merge(dst, src):
    for link, r in src.items():
        if link in dst:
            d = dst[link]
            d['queries'] = sorted(set(d['queries']) | set(r['queries']))
            d['passages'].update(r['passages'])
            ranks = [x for x in (d.get('sim_rank'), r.get('sim_rank')) if x is not None]
            d['sim_rank'] = min(ranks) if ranks else None
        else:
            dst[link] = r


def _within(r, cutoff):
    if not r['pub_date']:
        return True
    return datetime.fromisoformat(r['pub_date']) >= cutoff


SETTINGS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             'data', 'settings.json')


def configured_queries():
    """
    settings.json 의 hr_news.queries 를 우선 사용.

    관리자 화면에서 검색어를 편집하는 것이 이 사업의 핵심 기능이므로
    (실측: 검색어별 수확이 1건~82건으로 극심하게 편중) 코드 상수가 아니라
    설정을 단일 출처로 삼는다. 설정이 없거나 비면 코드 기본값으로 폴백한다.
    """
    try:
        with open(SETTINGS_PATH, encoding='utf-8') as f:
            qs = (json.load(f).get('hr_news') or {}).get('queries')
        if isinstance(qs, list) and qs:
            return [str(q).strip() for q in qs if str(q).strip()]
    except Exception:
        pass
    return DEFAULT_QUERIES


def collect(queries=None, display=100, days=4, sorts=('sim', 'date'), quiet=False):
    """검색어별로 sim·date 양쪽 호출 후 병합 (설계 근거 1)"""
    queries = queries or configured_queries()
    headers = _keys()
    cutoff = datetime.now(KST) - timedelta(days=days)
    merged, calls = {}, 0

    for q in queries:
        per_q = {}
        counts = {}
        for sort in sorts:
            items = search(q, display=display, sort=sort, headers=headers)
            calls += 1
            rows = {k: v for k, v in _to_rows(items, q, sort).items()
                    if _within(v, cutoff)}
            counts[sort] = len(rows)
            _merge(per_q, rows)
            time.sleep(0.15)
        _merge(merged, per_q)
        if not quiet:
            detail = ' '.join(f'{s}{counts.get(s, 0):>3}' for s in sorts)
            print(f'  {q:<14} {detail}  병합 {len(per_q):>3}')
    return merged, calls


def deepen(topic, angles=None, display=50, days=7, quiet=False):
    """다각도 심화 수집 (설계 근거 2)"""
    headers = _keys()
    cutoff = datetime.now(KST) - timedelta(days=days)
    qs = [f'{topic} {a}'.strip() for a in (angles or DEEP_ANGLES)]
    merged, calls = {}, 0
    for q in qs:
        items = search(q, display=display, sort='sim', headers=headers)
        calls += 1
        rows = {k: v for k, v in _to_rows(items, q, 'sim').items()
                if _within(v, cutoff)}
        _merge(merged, rows)
        time.sleep(0.15)
    if not quiet:
        print(f'    질의 {calls}개 → 기사 {len(merged)}건')
    return merged, calls, qs


# ════════════════════════════════════════════════════════════ 토픽 선정

def _overlap_coef(a, b):
    """겹침계수 — 작은 집합 기준. 제목 길이 차가 클 때 자카드보다 안정적."""
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def cluster(rows, threshold=0.22, min_size=3, merge_threshold=0.6):
    """
    제목 토큰 기반 사건 클러스터링 + 병합 후처리.

    1차 배정만 하면 같은 사건이 갈라진다(실측: 중대재해 양형기준이 2개 클러스터로,
    SK하이닉스 해커톤도 2개로 분리). 순차 배정의 순서 의존성 때문이다.
    생성된 클러스터끼리 다시 비교해 겹침계수가 높으면 병합한다.
    """
    clusters = []
    for r in rows:
        tk = tokens(r['title'])
        if not tk:
            continue
        best, bi = 0.0, -1
        for i, c in enumerate(clusters):
            u = len(tk | c['tok'])
            j = len(tk & c['tok']) / u if u else 0.0
            if j > best:
                best, bi = j, i
        if best >= threshold:
            clusters[bi]['rows'].append(r)
            clusters[bi]['tok'] |= tk
        else:
            clusters.append({'tok': set(tk), 'rows': [r]})

    # ── 병합 후처리 (union-find, 핵심어 고정)
    #
    # 반복 병합 중 핵심어를 재계산하면 클러스터가 커질수록 '채용' 같은 일반어만
    # 남아 모든 것을 끌어당긴다. 실측 실패: 81건 54매체가 한 덩어리가 되고
    # 질의는 "AI 해커톤 SK하이닉스" 인데 대표 제목이 "CJ제일제당 채용 컨퍼런스"였다.
    # → 1차 배정 직후의 핵심어를 고정해 쌍 비교만 하고, 그룹화는 union-find 로 한다.
    cores = [_core_terms(c) for c in clusters]
    parent = list(range(len(clusters)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i in range(len(clusters)):
        for j in range(i + 1, len(clusters)):
            inter = cores[i] & cores[j]
            # 공통 핵심어가 2개 이상이어야 같은 사건으로 본다
            # ('채용' 하나만 겹치는 서로 다른 기업 뉴스를 막는 장치)
            if len(inter) >= 2 and _overlap_coef(cores[i], cores[j]) >= merge_threshold:
                ri, rj = find(i), find(j)
                if ri != rj:
                    parent[rj] = ri

    grouped = {}
    for idx, c in enumerate(clusters):
        root = find(idx)
        if root not in grouped:
            grouped[root] = {'tok': set(), 'rows': []}
        grouped[root]['rows'].extend(c['rows'])
        grouped[root]['tok'] |= c['tok']

    return [c for c in grouped.values() if len(c['rows']) >= min_size]


def _core_terms(c, min_share=0.5, cap=6):
    """클러스터 기사 중 절반 이상에 등장하는 어휘 = 사건의 핵심어"""
    n = len(c['rows'])
    cnt = Counter()
    for r in c['rows']:
        for w in tokens(r['title']):
            cnt[w] += 1
    core = {w for w, k in cnt.items() if k >= max(2, n * min_share)}
    if not core:
        core = {w for w, _ in cnt.most_common(cap)}
    return core


# ── 토픽 분류 ──────────────────────────────────────────────────────────────
#
# 처음에는 '보도자료면 배제'라는 이진 분류로 만들었으나 데이터가 반증했다.
# "SK하이닉스, '학력 안 묻는' AI 해커톤 개최" 는 기업 보도자료지만
# 인사담당자에게는 실제 채용 트렌드 신호다. 오리온·코스맥스 공채의
# 'AI 활용 역량 우대'도 그렇다. 배제가 아니라 분류 후 가중이 맞다.
#
# 반면 "반도건설, 8년 연속 중대재해 ZERO 도전" 은 자기자랑이라 가치가 없다.

RE_POLICY_ACTOR = re.compile(
    r'(?:고용노동부|노동부|기획재정부|교육부|중기부|중소벤처기업부|행정안전부|'
    r'국회|정부|대통령|대법원|법원|헌재|양형위|위원회|공단|진흥원|'
    r'국민의힘|더불어민주당|여당|야당|[가-힣]{2,4}(?:시|도|군|구)청?)')
RE_POLICY_TOPIC = re.compile(
    r'(?:법|법안|개정|제정|시행|기준|제도|정책|고시|지침|예산|'
    r'대책|로드맵|가이드라인|의무화|확대\s*적용|입법|공제회|생활임금)')
# '처벌'/'위반' 은 법령 이름에도 들어간다. '중대재해처벌법' 이 감독·처벌로
# 오분류되어 정책 뉴스가 '기타'로 밀렸다 → 법령명 문맥을 부정 전방탐색으로 제외.
RE_ENFORCE = re.compile(
    r'(?:감독|적발|점검|수사|과태료|시정\s*명령|송치|기소|구속|제재|단속|'
    r'처벌(?!법)|위반(?:치사|치상)?(?!\s*범죄\s*양형))')

# 주체가 제목에 없어도 그 자체로 정책 사안인 어휘
RE_POLICY_STRONG = re.compile(
    r'(?:양형기준|법안|법 개정|개정안|입법|제정|고시|시행령|시행규칙|지침|'
    r'생활임금|공제회|최저임금\s*(?:인상|결정|고시)|정년\s*연장|'
    r'주\s*4\.?5일제|근로시간\s*개편|제도\s*개편)')
RE_CORP_CASE = re.compile(
    r'(?:채용|공채|신입사원|인재|해커톤|교육|연수|아카데미|인턴|직무|역량)')
RE_SELFPRAISE = re.compile(
    r'(?:\d+년\s*연속|무재해|ZERO|제로\s*(?:기록|달성|도전)|업계\s*최초|'
    r'국내\s*최초|최대\s*규모|대상\s*수상|인증\s*획득|표창|우수기업\s*선정)')

CATEGORY_WEIGHT = {
    '정책·제도': 1.5,
    '감독·처벌': 1.3,
    '기업 사례': 0.6,
    '홍보': 0.0,
    '기타': 0.8,
}


def classify(titles):
    """클러스터 제목 다수결로 분류. 반환: (분류명, 가중치)"""
    if not titles:
        return '기타', CATEGORY_WEIGHT['기타']
    votes = Counter()
    for t in titles:
        # 순서가 곧 우선순위. 정책 사안을 감독·처벌보다 먼저 판정해
        # 법령명에 걸려 밀리는 일을 막는다.
        if RE_SELFPRAISE.search(t):
            votes['홍보'] += 1
        elif RE_POLICY_STRONG.search(t) or (
                RE_POLICY_ACTOR.search(t) and RE_POLICY_TOPIC.search(t)):
            votes['정책·제도'] += 1
        elif RE_ENFORCE.search(t):
            votes['감독·처벌'] += 1
        elif RE_CORP_CASE.search(t):
            votes['기업 사례'] += 1
        else:
            votes['기타'] += 1
    cat = votes.most_common(1)[0][0]
    return cat, CATEGORY_WEIGHT[cat]


def score_cluster(c):
    """
    토픽 점수.

    설계 근거 4: 매체 수만으로는 보도자료 살포를 구분할 수 없다.
    매체 등급(T1/T2) + 분류 가중치 + sim 순위를 함께 본다.
    주요 매체가 하나도 없으면(T1=T2=0) 전문지 살포로 보고 감점한다.
    """
    rows = c['rows']
    n = len(rows)
    titles = [r['title'] for r in rows]
    sources = {r['source'] for r in rows}
    t1 = sum(1 for s in sources if tier_of(s) == 1)
    t2 = sum(1 for s in sources if tier_of(s) == 2)
    ranks = [r['sim_rank'] for r in rows if r['sim_rank'] is not None]
    best_rank = min(ranks) if ranks else 999

    cat, weight = classify(titles)
    base = n * 1.0 + t1 * 4.0 + t2 * 2.0 + max(0, 30 - best_rank) * 0.3
    if t1 + t2 == 0:          # 주요 매체 부재 — 전문지 살포
        base *= 0.3
    score = base * weight

    return {
        'n': n, 'outlets': len(sources), 't1': t1, 't2': t2,
        'major': t1 + t2, 'best_rank': best_rank,
        'category': cat, 'weight': weight,
        'excluded': (weight == 0.0),
        'score': round(score, 1),
    }


# 검색어로 부적합한 어미·조사·수량 표현
# 실측 반례: "적발 임금체불 앞두고", "플랫폼 공제회 만들겠다", "육아휴직 급여 2배"
BAD_TERM = re.compile(
    r'(?:겠다|었다|았다|한다|된다|하고|되고|두고|이고|에서|으로|까지|부터|'
    r'보다|처럼|만큼|라며|다며|면서|는데|지만|어야|아야|해야|이라|라고|'
    r'했다|밝혀|나서|위해|통해|대해|따라)$')
NUM_ONLY = re.compile(r'^\d+(?:배|건|명|억|만|원|%|년|월|일|차|위|회)?$')


def _is_good_term(w):
    if len(w) < 2 or w in STOP:
        return False
    if NUM_ONLY.match(w) or BAD_TERM.search(w):
        return False
    return True


def topic_query(c, max_terms=3):
    """
    클러스터에서 심화 질의용 대표 검색어 추출.

    빈도만으로 뽑으면 조사·어미가 섞인다(실측: "앞두고", "만들겠다", "2배").
    명사성 어휘만 남기고, 최종 배열은 대표 제목의 등장 순서를 따라
    사람이 읽을 수 있는 검색어가 되도록 한다.
    """
    n = len(c['rows'])
    cnt = Counter()
    for r in c['rows']:
        for w in tokens(r['title']):
            if _is_good_term(w):
                cnt[w] += 1
    if not cnt:
        return ''
    # 다수 공통 어휘 우선, 동률이면 긴 어휘
    ranked = sorted(cnt.items(), key=lambda kv: (-kv[1], -len(kv[0])))
    picked = [w for w, k in ranked[:max_terms] if k >= max(2, n * 0.3)] \
        or [w for w, _ in ranked[:max_terms]]

    # 대표 제목 등장 순서로 재배열
    rep_title = representative(c)['title']
    pos = {w: (rep_title.find(w) if w in rep_title else 10_000) for w in picked}
    return ' '.join(sorted(picked, key=lambda w: pos[w]))


def representative(c):
    """대표 기사 — 상위 등급 + sim 상위"""
    return sorted(c['rows'],
                  key=lambda r: (tier_of(r['source']),
                                 r['sim_rank'] if r['sim_rank'] is not None else 999)
                  )[0]


def rank_topics(conn, days=3, top_n=10):
    cutoff = (datetime.now(KST) - timedelta(days=days)).isoformat(timespec='seconds')
    rows = conn.execute(
        'SELECT title, source, original_link, sim_rank, queries, passages '
        'FROM hr_news WHERE is_noise=0 AND (pub_date IS NULL OR pub_date >= ?) '
        'ORDER BY pub_date DESC', (cutoff,)).fetchall()
    rows = [dict(r) for r in rows]
    out = []
    for c in cluster(rows):
        m = score_cluster(c)
        out.append({'cluster': c, 'metrics': m,
                    'query': topic_query(c), 'rep': representative(c)})
    out.sort(key=lambda x: -x['metrics']['score'])
    return out[:top_n], len(rows)


# ════════════════════════════════════════════════════════════ CLI

def cmd_collect(args):
    print('=' * 74)
    print(f'수집 — sort {"+".join(args.sorts)}, display {args.display}, '
          f'최근 {args.days}일, 검색어 {len(configured_queries())}개')
    print('=' * 74)
    merged, calls = collect(display=args.display, days=args.days, sorts=args.sorts)
    conn = connect()
    new, upd = upsert(conn, list(merged.values()))
    noise = sum(1 for r in merged.values() if is_noise(r['title'], r['source']))
    print()
    print(f'  API 호출 {calls}회 | 고유 {len(merged)}건 (노이즈 {noise}) '
          f'| DB 신규 {new} 갱신 {upd}')
    conn.close()
    return conn


def _print_topics(topics, total):
    print(f'  대상 기사 {total}건 → 토픽 {len(topics)}개')
    print()
    hdr = f"  {'#':>2} {'점수':>6} {'건수':>4} {'매체':>4} {'T1':>3} {'T2':>3} {'분류':<9} {'질의':<18} 대표 제목"
    print(hdr)
    print('  ' + '-' * (len(hdr) + 18))
    for i, t in enumerate(topics, 1):
        m = t['metrics']
        flag = ' ✖제외' if m['excluded'] else ''
        print(f'  {i:>2} {m["score"]:>6.1f} {m["n"]:>4} {m["outlets"]:>4} '
              f'{m["t1"]:>3} {m["t2"]:>3} {m["category"]:<9} {t["query"][:18]:<18} '
              f'{t["rep"]["title"][:34]}{flag}')


def cmd_topics(args):
    conn = connect()
    topics, total = rank_topics(conn, days=args.days, top_n=args.top)
    print('=' * 74)
    print(f'토픽 순위 (최근 {args.days}일)')
    print('=' * 74)
    _print_topics(topics, total)
    print()
    print('  T1=통신사·지상파, T2=전국일간·경제지 (둘 다 0이면 점수 ×0.3)')
    print('  분류 가중치: 정책·제도 ×1.5 | 감독·처벌 ×1.3 | 기타 ×0.8 | 기업 사례 ×0.6 | 홍보 ×0')
    conn.close()


def cmd_auto(args):
    print('=' * 74)
    print('자동 파이프라인 — 수집 → 토픽 선정 → 상위 심화')
    print('=' * 74)
    print()
    print('[1] 수집')
    merged, calls = collect(display=args.display, days=args.days,
                            sorts=args.sorts, quiet=True)
    conn = connect()
    new, upd = upsert(conn, list(merged.values()))
    print(f'  API {calls}회 | 고유 {len(merged)}건 | 신규 {new} 갱신 {upd}')

    print()
    print('[2] 토픽 선정')
    topics, total = rank_topics(conn, days=args.days, top_n=args.top)
    _print_topics(topics, total)

    targets = [t for t in topics if not t['metrics']['excluded']][:args.deep_n]
    print()
    print(f'[3] 상위 {len(targets)}개 토픽 심화')
    dcalls = 0
    for t in targets:
        q = t['query']
        print(f'  ◆ {q}')
        dm, dc, _ = deepen(q, display=args.deep_display, days=args.days + 3, quiet=True)
        dcalls += dc
        n, u = upsert(conn, list(dm.values()))
        print(f'    질의 {dc}개 → 기사 {len(dm)}건 (신규 {n} 갱신 {u})')

    print()
    print('[4] 심화 결과 — 분석재료 확보량')
    for t in targets:
        rep = conn.execute(
            'SELECT title, source, queries, passages FROM hr_news '
            'WHERE original_link = ?', (t['rep']['original_link'],)).fetchone()
        if not rep:
            continue
        ps = json.loads(rep['passages'] or '{}')
        raw = ' '.join(p for p in ps.values() if p)
        mat = analysis_material(dict(rep), topic=t['query'])
        unf = analysis_material(dict(rep), topic=t['query'], filter_topic=False)
        print(f'  ■ {rep["title"][:56]}')
        print(f'    각도 {len(ps)} | 원시 {len(raw)}자 → 정제 {len(unf)}자 '
              f'→ 토픽필터 {len(mat)}자')

    print()
    print(f'총 API 호출 {calls + dcalls}회 (일 한도 25,000회)')
    conn.close()


def cmd_deep(args):
    print('=' * 74)
    print(f'수동 심화 — "{args.deep}"')
    print('=' * 74)
    merged, calls, qs = deepen(args.deep, display=args.deep_display, days=args.days + 3)
    conn = connect()
    new, upd = upsert(conn, list(merged.values()))
    print(f'  각도: {", ".join(a.replace(args.deep, "").strip() or "(기본)" for a in qs)}')
    print(f'  기사 {len(merged)}건 | DB 신규 {new} 갱신 {upd}')
    print()
    top = sorted(merged.values(), key=lambda r: -len(r['passages']))[:3]
    for r in top:
        mat = analysis_material(r, topic=args.deep)
        unf = analysis_material(r, topic=args.deep, filter_topic=False)
        print(f'  ■ {r["title"][:58]}')
        print(f'    {r["source"]} (T{tier_of(r["source"])}) | 각도 {len(r["passages"])} '
              f'| 정제 {len(unf)}자 → 토픽필터 {len(mat)}자')
        print(f'    {mat[:230]}')
        print()
    conn.close()


def cmd_stats(args):
    conn = connect()
    tot = conn.execute('SELECT COUNT(*) FROM hr_news').fetchone()[0]
    noise = conn.execute('SELECT COUNT(*) FROM hr_news WHERE is_noise=1').fetchone()[0]
    print(f'저장 {tot}건 (노이즈 {noise}건)')
    if not tot:
        conn.close(); return
    print()
    print('매체 등급 분포')
    for r in conn.execute('SELECT tier, COUNT(*) c FROM hr_news WHERE is_noise=0 '
                          'GROUP BY tier ORDER BY tier'):
        label = {1: '통신사·지상파', 2: '전국일간·경제지', 3: '전문지·기타'}[r['tier']]
        print(f'  T{r["tier"]} {label:<16} {r["c"]:>5}건')
    print()
    print('각도 분포')
    cnt = Counter()
    for r in conn.execute('SELECT passages FROM hr_news WHERE is_noise=0'):
        cnt[len(json.loads(r['passages'] or '{}'))] += 1
    for k in sorted(cnt):
        print(f'  {k}각도 {cnt[k]:>5}건')
    print()
    print('매체 상위 8')
    for r in conn.execute('SELECT source, tier, COUNT(*) c FROM hr_news '
                          'WHERE is_noise=0 GROUP BY source ORDER BY c DESC LIMIT 8'):
        print(f'  {r["c"]:>4}  T{r["tier"]}  {r["source"]}')
    conn.close()


def main():
    ap = argparse.ArgumentParser(description='HR뉴스 수집·토픽 선정기')
    ap.add_argument('--auto', action='store_true', help='수집→토픽선정→상위 심화')
    ap.add_argument('--topics', action='store_true', help='토픽 순위만 확인')
    ap.add_argument('--deep', metavar='토픽', help='특정 토픽 수동 심화')
    ap.add_argument('--stats', action='store_true')
    ap.add_argument('--display', type=int, default=100, help='검색어당 수신 (최대 100)')
    ap.add_argument('--deep-display', type=int, default=50, dest='deep_display')
    ap.add_argument('--days', type=int, default=4)
    ap.add_argument('--top', type=int, default=10, help='토픽 순위 출력 개수')
    ap.add_argument('--deep-n', type=int, default=3, dest='deep_n',
                    help='자동 심화할 상위 토픽 개수')
    ap.add_argument('--sorts', nargs='+', default=['sim', 'date'],
                    choices=['sim', 'date'])
    args = ap.parse_args()

    if args.stats:
        cmd_stats(args)
    elif args.topics:
        cmd_topics(args)
    elif args.auto:
        cmd_auto(args)
    elif args.deep:
        cmd_deep(args)
    else:
        cmd_collect(args)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
