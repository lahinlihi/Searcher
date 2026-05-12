"""
나라장터 개찰결과 용역 예비가격상세 수집 스크립트
- 서비스: 조달청_나라장터 낙찰정보서비스 (data.go.kr/data/15129397)
- 오퍼레이션: getOpengResultListInfoServcPreparPcDetail
- 해당 공고에 투찰한 전체 업체의 순위/투찰금액/투찰률을 DataFrame으로 반환

※ API 키가 해당 오퍼레이션에 등록되어 있어야 합니다.
   data.go.kr → 마이페이지 → 활용신청 현황 → ScsbidInfoService(15129397)에서 확인

사용법:
    python fetch_bid_rank.py R26BK01406051
    python fetch_bid_rank.py R26BK01406051 000
"""

import sys
import json
import requests
import pandas as pd
from urllib.parse import unquote
from pathlib import Path

# ── 설정 ──────────────────────────────────────────────────────────────────────
SETTINGS_PATH = Path(__file__).parent / 'data' / 'settings.json'

# 엔드포인트: 문서 기준 /as/ScsbidInfoService/, 실제 라우팅은 루트 경로에도 존재
ENDPOINTS = [
    'http://apis.data.go.kr/1230000/as/ScsbidInfoService/getOpengResultListInfoServcPreparPcDetail',
    'http://apis.data.go.kr/1230000/getOpengResultListInfoServcPreparPcDetail',
]


def load_service_key() -> str:
    with open(SETTINGS_PATH, encoding='utf-8') as f:
        s = json.load(f)
    raw = s.get('crawl', {}).get('sites', {}).get('g2b_api', {}).get('service_key', '')
    if not raw:
        raise ValueError('settings.json에 g2b_api.service_key가 없습니다.')
    return unquote(raw)  # 이중 인코딩 방지


def _parse_items(data: dict) -> tuple[list, int]:
    body  = data.get('response', {}).get('body', {})
    total = int(body.get('totalCount') or 0)
    raw   = body.get('items')
    if not raw:
        return [], total
    if isinstance(raw, list):
        return raw, total
    if isinstance(raw, dict):
        inner = raw.get('item', [])
        if isinstance(inner, dict):
            return [inner], total
        return inner or [], total
    return [], total


def _result_code(data: dict) -> tuple[str, str]:
    hdr  = data.get('response', {}).get('header', {})
    code = str(hdr.get('resultCode', '') or '')
    msg  = str(hdr.get('resultMsg',  '') or '')
    return code, msg


def fetch_rank_list(bid_no: str, bid_ord: str = '000', service_key: str = '') -> pd.DataFrame:
    """
    입찰공고번호로 개찰결과 전체 업체 목록을 조회해 DataFrame으로 반환.

    Parameters
    ----------
    bid_no      : 입찰공고번호 (예: R26BK01406051)
    bid_ord     : 공고차수 3자리 (기본값 '000')
    service_key : 공공데이터포털 서비스키 (비워두면 settings.json 자동 로드)

    Returns
    -------
    DataFrame columns: 순위, 업체명, 사업자번호, 투찰금액, 투찰률(%), 낙찰여부,
                       공고번호, 공고차수, 공고명
    """
    if not service_key:
        service_key = load_service_key()

    bid_ord = str(bid_ord).zfill(3)

    for url in ENDPOINTS:
        # 필수 파라미터만 먼저 시도, 실패 시 선택 파라미터 추가
        for params in [
            {
                'ServiceKey': service_key,
                'type':       'json',
                'bidNtceNo':  bid_no,
                'bidNtceOrd': bid_ord,
                'pageNo':     '1',
                'numOfRows':  '200',
            },
            {
                'ServiceKey': service_key,
                'type':       'json',
                'bidNtceNo':  bid_no,
                'pageNo':     '1',
                'numOfRows':  '200',
            },
        ]:
            try:
                resp = requests.get(url, params=params, timeout=20)
            except requests.exceptions.RequestException as e:
                print(f'  네트워크 오류: {e}')
                continue

            if resp.status_code == 404:
                break   # 이 URL은 없음 → 다음 URL 시도
            if resp.status_code == 429:
                raise RuntimeError('API 호출 한도 초과 (429). 잠시 후 재시도하세요.')
            if resp.status_code != 200:
                print(f'  HTTP {resp.status_code}: {resp.text[:80]}')
                continue

            try:
                data = resp.json()
            except Exception:
                print(f'  JSON 파싱 실패: {resp.text[:80]}')
                continue

            code, msg = _result_code(data)
            if code and code != '00':
                # 08=필수파라미터오류 → 파라미터셋 변경 후 재시도
                if code == '08':
                    continue
                raise RuntimeError(f'API 오류 [{code}]: {msg}\n'
                                   '→ data.go.kr 마이페이지에서 해당 오퍼레이션 활용신청 여부 확인')

            items, total = _parse_items(data)
            if total == 0 or not items:
                return pd.DataFrame()   # 결과 없음 (개찰 미완료 또는 해당 없는 번호)

            print(f'  {url.split("/")[-1]} → {total}건 조회 성공')
            return _build_dataframe(items, bid_no, bid_ord)

    return pd.DataFrame()


def _build_dataframe(items: list, bid_no: str, bid_ord: str) -> pd.DataFrame:
    """API 응답 item 리스트를 DataFrame으로 변환."""
    rows = []
    for it in items:
        # 순위: rnk 또는 bidRnk
        rank = (it.get('rnk') or it.get('bidRnk') or it.get('rank') or '')

        # 업체명: corpNm 또는 bidcorpNm
        name = (it.get('corpNm') or it.get('bidcorpNm') or
                it.get('bidwinnrNm') or '').strip()

        # 사업자번호: bizno 또는 corpRegNo
        bizno = (it.get('bizno') or it.get('corpRegNo') or
                 it.get('bidwinnrBizno') or '').strip()

        # 투찰금액: bidAmt 또는 bidprcAmt
        amt_raw = (it.get('bidAmt') or it.get('bidprcAmt') or
                   it.get('sucsfbidAmt') or 0)
        try:
            amt = int(str(amt_raw).replace(',', ''))
        except (ValueError, TypeError):
            amt = 0

        # 투찰률: bidRate 또는 bidprcRate
        rate = str(it.get('bidRate') or it.get('bidprcRate') or
                   it.get('sucsfbidRate') or '').strip()

        # 낙찰여부: sucsfBidYn 또는 bidwinnrYn
        is_win = str(it.get('sucsfBidYn') or it.get('bidwinnrYn') or '').upper() == 'Y'

        # 공고명
        title = (it.get('bidNtceNm') or '').strip()

        rows.append({
            '순위':       rank,
            '업체명':     name,
            '사업자번호': bizno,
            '투찰금액':   amt,
            '투찰률(%)':  rate,
            '낙찰여부':   '낙찰' if is_win else '',
            '공고번호':   it.get('bidNtceNo', bid_no),
            '공고차수':   it.get('bidNtceOrd', bid_ord),
            '공고명':     title,
        })

    df = pd.DataFrame(rows)

    # 순위 기준 정렬
    def _to_int(v):
        try: return int(v)
        except (ValueError, TypeError): return 9999

    df['_sort_key'] = df['순위'].apply(_to_int)
    df = (df.sort_values('_sort_key')
            .drop(columns='_sort_key')
            .reset_index(drop=True))
    return df


def save_to_excel(df: pd.DataFrame, bid_no: str, out_dir: Path | None = None) -> Path:
    """DataFrame을 엑셀로 저장하고 경로 반환."""
    if out_dir is None:
        out_dir = Path(__file__).parent / 'output'
    out_dir.mkdir(exist_ok=True)

    fname = out_dir / f'개찰순위_{bid_no}.xlsx'
    with pd.ExcelWriter(fname, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='개찰순위')
        ws = writer.sheets['개찰순위']

        # 투찰금액 열 서식: 천 단위 콤마
        for i, col in enumerate(df.columns):
            col_letter = ws.cell(1, i + 1).column_letter
            if col == '투찰금액':
                for cell in ws[col_letter][1:]:
                    cell.number_format = '#,##0'

        # 열 너비 자동 조정
        for col in ws.columns:
            max_len = max((len(str(c.value or '')) for c in col), default=8)
            ws.column_dimensions[col[0].column_letter].width = min(max_len + 4, 50)

    return fname


def main():
    if len(sys.argv) < 2:
        print('사용법: python fetch_bid_rank.py <입찰공고번호> [공고차수=000]')
        print('예시:  python fetch_bid_rank.py R26BK01406051')
        sys.exit(1)

    bid_no  = sys.argv[1].strip()
    bid_ord = sys.argv[2].strip() if len(sys.argv) > 2 else '000'

    print(f'\n[개찰순위 조회] 공고번호={bid_no}  차수={bid_ord}')
    print('-' * 60)

    try:
        df = fetch_rank_list(bid_no, bid_ord)
    except RuntimeError as e:
        print(f'\n오류: {e}')
        sys.exit(1)

    if df.empty:
        print('\n결과 없음. 확인 사항:')
        print('  1. API 키 권한: data.go.kr → 마이페이지 → 활용신청 현황')
        print('     getOpengResultListInfoServcPreparPcDetail 포함 여부 확인')
        print('  2. 해당 공고 개찰 완료 여부')
        print('  3. BD(사전공고) 번호는 결과 없음 → BK(공개입찰) 번호 사용')
        sys.exit(1)

    print(f'\n[결과] 총 {len(df)}개 업체\n')
    print(df[['순위', '업체명', '투찰금액', '투찰률(%)', '낙찰여부']].to_string(index=False))

    path = save_to_excel(df, bid_no)
    print(f'\n[저장] {path}')


if __name__ == '__main__':
    main()
