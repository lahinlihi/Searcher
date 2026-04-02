"""
공고 첨부파일(RFP) 분석 모듈
- A: 규칙 기반 핵심 정보 추출 (사업목적, 과업범위, 기간, 예산, 자격요건)
- C: Gemini 1.5 Flash API 기반 전체 요약 (무료 티어)
"""
import json
import os
import re
import subprocess
import zlib
import logging
import tempfile
import zipfile
from pathlib import Path
from urllib.parse import urljoin, urlparse, unquote

import requests

logger = logging.getLogger(__name__)

# ── 텍스트 추출 ──────────────────────────────────────────────────────────────

def _extract_text_from_hwpx(filepath):
    """HWPX(= ZIP+XML) 파일에서 텍스트 추출"""
    try:
        texts = []
        with zipfile.ZipFile(filepath, 'r') as zf:
            for name in sorted(zf.namelist()):
                if re.match(r'Contents/section\d+\.xml', name, re.I):
                    with zf.open(name) as f:
                        xml = f.read().decode('utf-8', errors='replace')
                        text = re.sub(r'<[^>]+>', ' ', xml)
                        text = re.sub(r'\s+', ' ', text).strip()
                        if text:
                            texts.append(text)
        return '\n'.join(texts)
    except Exception as e:
        logger.warning(f"HWPX 텍스트 추출 실패: {e}")
        return ''


def _hwp_decompress(raw):
    """HWP BodyText 스트림 압축 해제"""
    try:
        return zlib.decompress(raw, -15)
    except zlib.error:
        try:
            return zlib.decompress(raw)
        except zlib.error:
            return raw


def _hwp_bruteforce_scan(dec):
    """
    압축 해제된 HWP BodyText 스트림에서 텍스트 추출.
    ① 두 바이트 오프셋(0, 1)에서 모두 스캔 — HWP 표 셀 데이터는 홀수/짝수 정렬이 혼재
    ② 한글로 시작하는 블록 (본문 + 표 셀 한글)
    ③ 쉼표 포함 숫자 패턴 (표 셀 수치: 11,340 / 31,680 / 7,920 / 1,610,055)
    """
    _NUM_PAT = re.compile(
        r'[1-9]\d{0,2}(?:,\d{3})+(?:\.\d+)?'             # 천단위 쉼표 숫자
        r'|\b\d{1,3}(?:,\d{3})*(?:\.\d+)?\s*'
        r'(?:팀|개소|개|명|시간|%|점|천원|만원|억원|원)',  # 단위 붙은 숫자
    )
    _KO_PAT = re.compile(
        r'[\uAC00-\uD7A3][\uAC00-\uD7A3\u0020-\u007E,.:;()\[\]%\d\-·\n]{2,}'
    )

    number_set = {}  # 중복 제거용 ordered dict
    korean_chunks = []

    for offset in (0, 1):
        raw_text = dec[offset:].decode('utf-16-le', errors='replace')

        # 숫자 패턴 수집
        for m in _NUM_PAT.findall(raw_text):
            m = m.strip()
            if m and m not in number_set:
                number_set[m] = True

        # 한글 블록 (offset=0만 — offset=1은 텍스트 의미가 흐림)
        if offset == 0:
            for c in _KO_PAT.findall(raw_text):
                c = c.strip()
                if len(c) >= 3 and any('\uAC00' <= ch <= '\uD7A3' for ch in c):
                    korean_chunks.append(c)

    parts = []
    if number_set:
        parts.append('[표·수치 데이터]\n' + ', '.join(number_set.keys()))
    parts.extend(korean_chunks)
    return '\n'.join(parts)


def _extract_text_from_hwp(filepath):
    """HWP(binary) 파일에서 텍스트 추출"""
    # 방법 1: gethwp 라이브러리
    try:
        import gethwp
        text = gethwp.get_text(filepath)
        if text and len(text) > 50:
            return text
    except ImportError:
        pass
    except Exception as e:
        logger.warning(f"gethwp 추출 실패: {e}")

    # 방법 2: olefile
    try:
        import olefile
        with olefile.OleFileIO(filepath) as ole:
            prv_text = ''
            body_text = ''

            # 2-A: PrvText (미리보기, 최대 1,022자 수준)
            if ole.exists('PrvText'):
                try:
                    raw = ole.openstream('PrvText').read()
                    prv = raw.decode('utf-16-le', errors='replace').strip()
                    prv = re.sub(r'<[^>]{0,80}>', ' ', prv)
                    prv = re.sub(r'\s+', ' ', prv).strip()
                    if len(prv) > 50:
                        prv_text = prv
                except Exception:
                    pass

            # 2-B: BodyText/Section* — 레코드 파싱 우선, 실패 시 브루트포스 스캔
            # ※ HWP 표(Table) 내부 텍스트는 중첩 레코드라 레코드 파서가 0개 반환할 수 있음
            #   → 이 경우 브루트포스로 15,000자+ 추출 가능
            section_texts = []
            for entry in ole.listdir():
                path = '/'.join(entry)
                if 'BodyText' not in path or 'Section' not in path:
                    continue
                try:
                    raw = ole.openstream(path).read()
                    dec = _hwp_decompress(raw)

                    # ── 레코드 파싱 (HWPTAG_PARA_TEXT = 67) ──────────────
                    # HWP5 레코드 헤더 비트 레이아웃 (pyhwp 기준):
                    #   bits  0- 9: tag_id  (10 bits)
                    #   bits 10-19: level   (10 bits)
                    #   bits 20-31: size    (12 bits)
                    #   if size == 0xfff: 다음 4바이트가 실제 크기
                    pos, para_texts = 0, []
                    while pos + 4 <= len(dec):
                        rechdr = int.from_bytes(dec[pos:pos + 4], 'little')
                        tag_id = rechdr & 0x3ff
                        size = (rechdr >> 20) & 0xfff
                        pos += 4
                        if size == 0xfff:
                            if pos + 4 > len(dec):
                                break
                            size = int.from_bytes(dec[pos:pos + 4], 'little')
                            pos += 4
                        if pos + size > len(dec):
                            break
                        data = dec[pos:pos + size]
                        pos += size
                        if tag_id == 67 and data:
                            t = data.decode('utf-16-le', errors='replace')
                            t = re.sub(r'[\x00-\x08\x0b-\x1f]', ' ', t).strip()
                            # 한글 또는 숫자 포함 시 수집 (표 셀 수치도 포함)
                            if t and (any('\uAC00' <= c <= '\uD7A3' for c in t)
                                      or re.search(r'\d', t)):
                                para_texts.append(t)

                    if para_texts:
                        section_texts.append('\n'.join(para_texts))
                    else:
                        # 레코드 파싱 실패(표 전용 파일 등) → 브루트포스 스캔
                        bf = _hwp_bruteforce_scan(dec)
                        if bf:
                            section_texts.append(bf)
                except Exception:
                    pass

            body_text = '\n'.join(section_texts)

            # PrvText vs BodyText — 더 긴 쪽 사용 (대개 BodyText가 15~50배 많음)
            result = body_text if len(body_text) > len(prv_text) else prv_text
            if result:
                return result

    except ImportError:
        pass
    except Exception as e:
        logger.warning(f"olefile 추출 실패: {e}")

    return ''


def _extract_text_from_pdf(filepath):
    """PDF 파일에서 텍스트 추출 (pdfplumber)"""
    try:
        import pdfplumber
        texts = []
        with pdfplumber.open(filepath) as pdf:
            for page in pdf.pages[:25]:
                t = page.extract_text()
                if t:
                    texts.append(t)
        return '\n'.join(texts)
    except ImportError:
        logger.warning("pdfplumber 미설치: pip install pdfplumber")
        return ''
    except Exception as e:
        logger.warning(f"PDF 텍스트 추출 실패: {e}")
        return ''


# ── kordoc 통합 (Node.js CLI 래퍼) ───────────────────────────────────────────

_KORDOC_AVAILABLE = None          # None=미확인, True/False=확인 완료
_KORDOC_SCRIPT    = None          # 설치된 kordoc 스크립트 경로 (캐시)

def _find_kordoc_script():
    """
    node_modules/.bin/kordoc 위치를 찾아 반환.
    찾지 못하면 None.
    """
    # 1) 프로젝트 로컬 node_modules
    script_dir = Path(__file__).parent / 'node_modules' / '.bin'
    for name in ('kordoc', 'kordoc.cmd', 'kordoc.ps1'):
        p = script_dir / name
        if p.exists():
            return str(p)
    # 2) npx fallback (전역 캐시)
    return None


def _kordoc_available():
    """kordoc CLI가 사용 가능한지 확인 (결과 캐시)"""
    global _KORDOC_AVAILABLE, _KORDOC_SCRIPT
    if _KORDOC_AVAILABLE is not None:
        return _KORDOC_AVAILABLE

    script = _find_kordoc_script()
    try:
        # 로컬 스크립트 우선, 없으면 npx
        cmd = [script, '--version'] if script else ['npx', '--no-install', 'kordoc', '--version']
        r = subprocess.run(cmd, capture_output=True, timeout=10, shell=(os.name == 'nt'))
        _KORDOC_AVAILABLE = r.returncode == 0
        _KORDOC_SCRIPT    = script
        logger.info(f"kordoc 사용 가능: {_KORDOC_AVAILABLE}, script={script}")
    except Exception as e:
        _KORDOC_AVAILABLE = False
        logger.warning(f"kordoc 확인 실패: {e}")
    return _KORDOC_AVAILABLE


def _extract_text_kordoc(filepath):
    """
    kordoc CLI로 HWP/HWPX/PDF에서 마크다운 텍스트 추출.
    표(Table) 구조를 마크다운 표로 변환해 반환.
    실패 시 빈 문자열 반환.
    """
    if not _kordoc_available():
        return ''

    script = _KORDOC_SCRIPT
    if script:
        cmd = [script, filepath, '--format', 'json']
    else:
        cmd = ['npx', 'kordoc', filepath, '--format', 'json']

    # 파일 크기 사전 확인: 50MB 초과 시 스킵 (kordoc 처리 불가 수준)
    try:
        fsize = os.path.getsize(filepath)
        if fsize > 50 * 1024 * 1024:
            logger.warning(f"kordoc 스킵 (파일 너무 큼: {fsize//1024//1024}MB): {Path(filepath).name}")
            return ''
    except OSError:
        pass

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            timeout=30,
            cwd=str(Path(__file__).parent),
            shell=(os.name == 'nt'),
        )
        stdout = result.stdout.decode('utf-8', errors='replace')
        stderr = result.stderr.decode('utf-8', errors='replace')

        if result.returncode != 0:
            logger.warning(f"kordoc 실패 (rc={result.returncode}): {stderr[:200]}")
            return ''

        if not stdout.strip():
            return ''

        data = json.loads(stdout)
        md   = data.get('markdown', '')
        meta = data.get('metadata', {})
        fmt  = meta.get('format', '') or Path(filepath).suffix.upper()
        logger.info(f"kordoc 추출 완료: {Path(filepath).name} ({fmt}) → {len(md)}자")
        return md

    except subprocess.TimeoutExpired:
        logger.warning(f"kordoc 타임아웃: {filepath}")
        return ''
    except json.JSONDecodeError as e:
        logger.warning(f"kordoc JSON 파싱 실패: {e}")
        return ''
    except Exception as e:
        logger.warning(f"kordoc 예외: {e}")
        return ''


def extract_text(filepath):
    """
    파일에서 텍스트 추출.
    우선순위:
      1) kordoc (표 구조 보존, HWP/HWPX/PDF 모두 지원)
      2) 기존 Python 파서 (gethwp → olefile → pdfplumber) — fallback
    """
    ext = Path(filepath).suffix.lower()
    if ext not in ('.hwp', '.hwpx', '.pdf'):
        return ''

    # ── 1순위: kordoc (표 포함 구조적 마크다운 추출) ────────────────────────
    kordoc_text = _extract_text_kordoc(filepath)
    if kordoc_text and len(kordoc_text) >= 100:
        return kordoc_text

    # ── 2순위: 기존 Python 파서 (fallback) ──────────────────────────────────
    logger.info(f"kordoc 결과 부족({len(kordoc_text)}자), Python 파서로 폴백: {Path(filepath).name}")
    if ext == '.hwpx':
        return _extract_text_from_hwpx(filepath)
    elif ext == '.hwp':
        return _extract_text_from_hwp(filepath)
    elif ext == '.pdf':
        return _extract_text_from_pdf(filepath)
    return ''


# ── 첨부파일 링크 수집 ────────────────────────────────────────────────────────

_HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/120.0.0.0 Safari/537.36'
    )
}

_FILE_EXT_RE = re.compile(r'\.(hwp|hwpx|pdf)(\?|#|$)', re.I)

# 나라장터 사전규격 URL 패턴
_G2B_PRESPEC_RE = re.compile(r'g2b\.go\.kr/link/PRVA\w+/\?bfSpecRegNo=([A-Z0-9]+)', re.I)
# 나라장터 일반입찰 URL 패턴 (link/{path}/?bidPbancNo= 형태)
_G2B_BID_RE = re.compile(r'g2b\.go\.kr/link/[^?#]+\?bidPbancNo=([A-Z0-9]+)', re.I)
# 나라장터 파일 다운로드 기본 URL
_G2B_FILE_BASE = 'https://www.g2b.go.kr/pn/pnz/pnza/UntyAtchFile/downloadFile.do'
# 나라장터 오픈 API 기본 URL
_G2B_API_BASE = 'http://apis.data.go.kr/1230000/ad/BidPublicInfoService'
# 일반입찰 파일 다운로드 fileType 후보 (brute-force)
_G2B_BID_FILE_TYPES = [
    'BIDPBANCATFLNM', 'BIDPBLNCATFLNM', 'NTCEFLNM',
    'BIDDTL', 'BIDNTCE', 'SPEC',
]


def _load_g2b_service_key():
    """settings.json에서 나라장터 API 서비스키 로드"""
    try:
        settings_path = Path(__file__).parent / 'data' / 'settings.json'
        with open(settings_path, encoding='utf-8') as f:
            cfg = json.load(f)
        sites = cfg.get('crawl', {}).get('sites_config', {})
        for name in ('g2b_api', 'g2b_pre_spec'):
            key = sites.get(name, {}).get('service_key', '')
            if key:
                return key
    except Exception as e:
        logger.debug(f"G2B 서비스키 로드 실패: {e}")
    return ''


def _g2b_bid_links(bid_pbancno, bid_pbancord='000'):
    """
    나라장터 일반입찰 첨부파일 링크 수집.
    공공데이터 오픈 API의 ntceSpecDocUrlN / ntceSpecFileNmN 필드를 사용.
    API 조회 실패 시 직접 다운로드 URL 브루트포스로 폴백.
    """
    from datetime import datetime, timedelta
    service_key = _load_g2b_service_key()
    links = []
    seen = set()

    def _decode_fname(raw):
        """latin-1로 인코딩된 한글 파일명 복원"""
        try:
            return raw.encode('latin-1').decode('utf-8')
        except Exception:
            return raw

    def _add_from_url(url, fname=''):
        """URL이 실제 다운로드 가능한 파일인지 HEAD 없이 GET으로 검증 후 추가"""
        if not url or url in seen:
            return
        try:
            r = requests.get(url, headers=_HEADERS, timeout=10,
                             stream=True, allow_redirects=True)
            if r.status_code != 200:
                r.close()
                return
            ct = r.headers.get('content-type', '')
            r.close()
            if 'html' in ct.lower() or 'json' in ct.lower():
                return
            if not fname:
                cd = r.headers.get('content-disposition', '')
                m = re.search(r'filename=([^;]+)', cd)
                fname = _decode_fname(
                    unquote(m.group(1).strip().strip('"').strip("'"))
                ) if m else ('첨부파일.pdf' if 'pdf' in ct else '첨부파일.hwp')
            seen.add(url)
            links.append({'url': url, 'name': fname})
        except Exception as e:
            logger.debug(f"G2B 파일 확인 실패: {e}")

    # ── 1단계: 오픈 API ntceSpecDocUrlN 필드 ──────────────────────────────────
    if service_key:
        eps = [
            '/getBidPblancListInfoServc',
            '/getBidPblancListInfoCnstwk',
            '/getBidPblancListInfoThng',
            '/getBidPblancListInfoFrgcpt',
        ]
        # 최근 60일 범위로 검색 (공고일 모를 경우 폭넓게)
        now = datetime.now()
        for ep in eps:
            try:
                params = {
                    'ServiceKey': service_key,
                    'numOfRows': 1, 'pageNo': 1, 'type': 'json',
                    'inqryDiv': '1',
                    'inqryBgnDt': (now - timedelta(days=60)).strftime('%Y%m%d0000'),
                    'inqryEndDt': now.strftime('%Y%m%d2359'),
                    'bidNtceNo': bid_pbancno,
                }
                r = requests.get(_G2B_API_BASE + ep, params=params, timeout=15)
                if r.status_code != 200:
                    continue
                body = r.json().get('response', {}).get('body', {})
                items = body.get('items', [])
                if isinstance(items, dict) and 'item' in items:
                    items = items['item']
                if isinstance(items, dict):
                    items = [items]
                if not items:
                    continue
                # 공고번호가 일치하는 항목만 사용
                item = next(
                    (i for i in items if i.get('bidNtceNo', '') == bid_pbancno),
                    items[0]
                )
                logger.info(f"G2B 오픈 API 히트: {ep}, 공고번호={item.get('bidNtceNo')}")
                # ntceSpecDocUrl1..10 + ntceSpecFileNm1..10
                for idx in range(1, 11):
                    url = item.get(f'ntceSpecDocUrl{idx}', '')
                    fname_raw = item.get(f'ntceSpecFileNm{idx}', '')
                    fname = _decode_fname(fname_raw) if fname_raw else ''
                    if not url:
                        continue
                    # 파일명이 API에서 제공된 경우: 인증 벽으로 검증이 실패해도 목록에 포함
                    # → 실제 다운로드는 download_file()에서 처리
                    if fname and _FILE_EXT_RE.search(fname):
                        if url not in seen:
                            seen.add(url)
                            links.append({'url': url, 'name': fname})
                            logger.info(f"G2B 파일 추가 (API 직접): {fname}")
                    else:
                        _add_from_url(url, fname)
                # 표준서식 문서 (stdNtceDocUrl)
                std_url = item.get('stdNtceDocUrl', '')
                if std_url and std_url not in seen:
                    _add_from_url(std_url, '표준서식.hwp')
                if links:
                    return links
            except Exception as e:
                logger.debug(f"G2B 오픈 API 실패 ({ep}): {e}")

    # ── 2단계: 폴백 — 직접 다운로드 URL 브루트포스 ───────────────────────────
    logger.info(f"G2B 오픈 API 파일 미발견, 직접 URL 시도: {bid_pbancno}")
    g2b_bid_file_base = ('https://www.g2b.go.kr/pn/pnp/pnpe/UntyAtchFile/downloadFile.do')
    for seq in range(1, 6):
        url = (f'{g2b_bid_file_base}?bidPbancNo={bid_pbancno}'
               f'&bidPbancOrd={bid_pbancord.zfill(3)}&fileType=&fileSeq={seq}&prcmBsneSeCd=03')
        _add_from_url(url)

    return links


def _g2b_prespec_links(bf_spec_reg_no):
    """
    나라장터 사전규격 첨부파일 링크를 직접 구성.
    fileSeq 1~5를 GET 요청으로 확인 (HEAD는 403 반환하므로 사용 불가).
    실제 파일인지 Content-Type으로 검증.
    """
    links = []
    for seq in range(1, 6):
        url = f'{_G2B_FILE_BASE}?bfSpecRegNo={bf_spec_reg_no}&fileType=BFDTL&fileSeq={seq}'
        try:
            # stream=True로 헤더만 먼저 확인
            r = requests.get(url, headers=_HEADERS, timeout=10,
                             stream=True, allow_redirects=True)
            if r.status_code != 200:
                r.close()
                continue
            ct = r.headers.get('content-type', '')
            # HTML(오류 페이지)이면 파일 없음
            if 'html' in ct.lower() or 'json' in ct.lower():
                r.close()
                continue
            r.close()
            # Content-Disposition에서 파일명 추출
            cd = r.headers.get('content-disposition', '')
            m = re.search(r'filename=([^;]+)', cd)
            if m:
                fname = unquote(m.group(1).strip().strip('"').strip("'"))
                try:
                    fname = fname.encode('latin-1').decode('utf-8')
                except Exception:
                    pass
            else:
                ext = 'pdf' if 'pdf' in ct else 'hwp'
                fname = f'첨부파일{seq}.{ext}'
            links.append({'url': url, 'name': fname})
        except Exception as e:
            logger.debug(f"g2b prespec 확인 실패 seq={seq}: {e}")
    return links


def fetch_attachment_links(page_url):
    """
    공고 페이지에서 HWP/HWPX/PDF 첨부파일 링크 수집.

    나라장터 사전규격: bfSpecRegNo 추출 후 API 직접 구성 (SPA라 HTML 파싱 불가)
    기타 사이트: HTML 스크래핑
    """
    links = []
    seen_urls = set()

    def add_link(url, name=''):
        url = url.strip()
        if not url or url in seen_urls:
            return
        seen_urls.add(url)
        links.append({'url': url, 'name': name or Path(urlparse(url).path).name or url})

    # ── 나라장터 사전규격 전용 처리 ──────────────────────────────────────────
    m = _G2B_PRESPEC_RE.search(page_url)
    if m:
        bf_spec_reg_no = m.group(1)
        logger.info(f"나라장터 사전규격 감지: {bf_spec_reg_no}")
        g2b_links = _g2b_prespec_links(bf_spec_reg_no)
        if g2b_links:
            return g2b_links
        # HEAD 실패 시 첫 번째 URL만 직접 반환 (다운로드에서 검증)
        fallback_url = f'{_G2B_FILE_BASE}?bfSpecRegNo={bf_spec_reg_no}&fileType=BFDTL&fileSeq=1'
        return [{'url': fallback_url, 'name': '첨부파일1'}]

    # ── 나라장터 일반입찰 — 오픈 API + 직접 다운로드 시도 ───────────────────
    m = _G2B_BID_RE.search(page_url)
    if m:
        bid_pbancno = m.group(1)
        ord_m = re.search(r'[&?]bidPbancOrd=(\d+)', page_url)
        bid_pbancord = ord_m.group(1) if ord_m else '000'
        logger.info(f"나라장터 일반입찰 감지: {bid_pbancno} ord={bid_pbancord}")
        return _g2b_bid_links(bid_pbancno, bid_pbancord)

    # ── 일반 HTML 스크래핑 ────────────────────────────────────────────────────
    try:
        resp = requests.get(page_url, headers=_HEADERS, timeout=15)
        resp.raise_for_status()

        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(resp.text, 'html.parser')
        except ImportError:
            logger.warning("beautifulsoup4 미설치: pip install beautifulsoup4")
            for m2 in re.finditer(r'href=["\']([^"\']*\.(?:hwp|hwpx|pdf)[^"\']*)["\']', resp.text, re.I):
                href = m2.group(1)
                if not href.startswith('http'):
                    href = urljoin(page_url, href)
                add_link(href)
            return links

        # 1) href 링크 — 확장자가 있거나 다운로드 서블릿 패턴 URL
        _DL_SERVLET_RE = re.compile(
            r'(?:down|file|attach|atch)[^/]*\.(do|jsp|php|asp|aspx|action)', re.I
        )
        for a in soup.find_all('a', href=True):
            href = a['href']
            if not href or href.startswith(('javascript:', 'mailto:', '#')):
                continue
            # 확장자 포함 링크
            if _FILE_EXT_RE.search(href):
                if not href.startswith('http'):
                    href = urljoin(page_url, href)
                add_link(href, a.get_text(strip=True))
                continue
            # title/text 속성에 파일명 있고, href가 다운로드 URL 패턴
            label = (a.get('title', '') or a.get_text(strip=True) or '').strip()
            if _FILE_EXT_RE.search(label) and _DL_SERVLET_RE.search(href):
                full = href if href.startswith('http') else urljoin(page_url, href)
                add_link(full, label)

        # 2) onclick 패턴
        for el in soup.find_all(attrs={'onclick': True}):
            onclick = el.get('onclick', '')
            for m2 in re.finditer(r"['\"]([^'\"]*\.(?:hwp|hwpx|pdf)[^'\"]*)['\"]", onclick, re.I):
                candidate = m2.group(1)
                if not candidate.startswith('http'):
                    candidate = urljoin(page_url, candidate)
                add_link(candidate, el.get_text(strip=True))

        # 3) form action 패턴
        for form in soup.find_all('form'):
            action = form.get('action', '')
            if re.search(r'file|down|attach', action, re.I):
                full_url = urljoin(page_url, action) if not action.startswith('http') else action
                name_input = form.find('input', {'name': re.compile(r'file.*name|orig.*name', re.I)})
                fname = name_input['value'] if name_input and name_input.get('value') else ''
                if fname and _FILE_EXT_RE.search(fname):
                    add_link(full_url, fname)

    except Exception as e:
        logger.warning(f"첨부파일 링크 수집 실패 ({page_url}): {e}")

    return links


def download_file(url, dest_dir):
    """URL에서 파일 다운로드 → 로컬 경로 반환, 실패 시 None"""
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=30, stream=True)
        resp.raise_for_status()

        # 1순위: Content-Disposition 헤더에서 파일명 추출
        cd = resp.headers.get('content-disposition', '')
        fname = None
        m = re.search(r"filename\*=UTF-8''([^;]+)", cd, re.I)
        if m:
            fname = unquote(m.group(1).strip())
        if not fname:
            m = re.search(r'filename=["\']?([^"\';\r\n]+)', cd, re.I)
            if m:
                raw = m.group(1).strip().strip('"').strip("'")
                try:
                    fname = unquote(raw).encode('latin-1').decode('utf-8')
                except Exception:
                    fname = unquote(raw)

        # 2순위: URL 경로에서 파일명 추출 (쿼리스트링 제외)
        if not fname or not _FILE_EXT_RE.search(fname):
            parsed = urlparse(url)
            url_name = unquote(Path(parsed.path).name)
            if url_name and _FILE_EXT_RE.search(url_name):
                fname = url_name

        # 3순위: Content-Type으로 확장자 결정
        if not fname or not _FILE_EXT_RE.search(str(fname)):
            ct = resp.headers.get('content-type', '')
            ext = 'pdf' if 'pdf' in ct else 'hwp'
            fname = f'attachment.{ext}'

        # 위험 문자 제거 후 저장
        safe_name = re.sub(r'[\\/:*?"<>|]', '_', fname)
        filepath = os.path.join(dest_dir, safe_name)

        with open(filepath, 'wb') as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)
        logger.info(f"다운로드 완료: {safe_name} ({os.path.getsize(filepath)} bytes)")
        return filepath
    except Exception as e:
        logger.warning(f"파일 다운로드 실패 ({url}): {e}")
        return None


# ── A: 규칙 기반 핵심 정보 추출 ───────────────────────────────────────────────

_RULE_PATTERNS = {
    '사업목적': [
        r'(?:사업\s*목적|추진\s*배경|사업\s*개요)[^:\n]{0,15}[:\n]\s*([^\n]{20,300})',
        r'(?:목\s*적)[^:\n]{0,5}[:\n]\s*([^\n]{20,200})',
        r'(?:추진\s*목적)[^:\n]{0,5}[:\n]\s*([^\n]{20,200})',
    ],
    '과업범위': [
        r'(?:과업\s*범위|과업\s*내용|용역\s*내용|사업\s*내용)[^:\n]{0,15}[:\n]\s*([\s\S]{50,600}?)(?=\n\s*\n|\n[가-힣○●①-⑨]{1,8}\s*[.。:])',
        r'(?:업무\s*범위|수행\s*내용|주요\s*내용)[^:\n]{0,15}[:\n]\s*([\s\S]{30,400}?)(?=\n\s*\n|\n[가-힣]{2,8}\s*[.。:])',
    ],
    '계약기간': [
        r'(?:계약\s*기간|용역\s*기간|사업\s*기간|수행\s*기간)[^:\n]{0,10}[:\n]\s*([^\n]{10,100})',
        r'(\d{4}[.\-/년]\s*\d{1,2}[.\-/월]\s*\d{1,2}일?\s*[~∼–-]\s*\d{4}[.\-/년]\s*\d{1,2}[.\-/월]\s*\d{1,2}일?)',
    ],
    '예산': [
        r'(?:예\s*산|추정\s*가격|사업비|계약금액|용역비)[^:\n]{0,10}[:\n]\s*([^\n]{5,100})',
        r'([0-9,]{4,})\s*원',
    ],
    '참가자격': [
        r'(?:참가\s*자격|입찰\s*자격|수행\s*기관\s*자격|자격\s*요건)[^:\n]{0,15}[:\n]\s*([\s\S]{30,400}?)(?=\n\s*\n|\n[가-힣]{2,8}\s*[.。:])',
        r'(?:자격)[^:\n]{0,5}[:\n]\s*([\s\S]{20,200}?)(?=\n\s*\n)',
    ],
}


def rule_based_extract(text):
    """규칙 기반으로 RFP 핵심 정보 추출 → dict"""
    result = {}
    # 예산 필드 유효성 검사: 천단위 쉼표 숫자 또는 단위(천원/억원) 포함해야 유효
    # → "협상기간 15일 이내" 같은 잘못된 매칭 방지
    _MONEY_PAT = re.compile(r'\d{1,3}(?:,\d{3})+|\d+\s*(?:천원|만원|억원)')

    # HWP 인코딩 오류로 생성되는 CJK 한자(깨진 문자) 제거 패턴
    # → "湯湷", "乶乺" 같이 한국어 정부문서에서 한자가 나타나면 거의 깨진 문자임
    _CJK_PAT = re.compile(r'[\u4E00-\u9FFF\u3400-\u4DBF\uF900-\uFAFF]+\s*')

    for field, patterns in _RULE_PATTERNS.items():
        for pattern in patterns:
            m = re.search(pattern, text, re.MULTILINE)
            if m:
                value = m.group(1).strip()
                value = re.sub(r'\s+', ' ', value)
                # 깨진 CJK 문자 제거
                value = _CJK_PAT.sub('', value).strip()
                if len(value) >= 5:
                    # 예산 필드는 실제 금액 숫자가 있어야 유효, 없으면 다음 패턴 시도
                    if field == '예산' and not _MONEY_PAT.search(value):
                        continue
                    result[field] = value[:400]
                    break
    return result


# ── C: Gemini API 4개 섹션 분석 ──────────────────────────────────────────────

_GEMINI_PROMPT = """\
공공 입찰 RFP를 분석하여 JSON만 출력하세요.

규칙:
- 텍스트에 해당 정보가 있으면 반드시 추출 (날짜, 금액, 숫자 포함)
- 해당 항목에 정보가 전혀 없을 때만 "해당 없음"을 문자열 하나로 표시 (dict/list 금지)
- 마크다운 표(|구분|배점|) 형식 사용
- ⚠️ special_notes 에는 절대 [실적], [인력] 태그를 쓰지 말 것. 실적·인력 관련 내용은 proposal_requirements 의 '참가 자격 요건' 또는 '정량 평가 세부 배점' 에만 기재.
- ⚠️ special_notes 의 '사업 구조 특이점' 섹션은 반드시 포함할 것. 특이점이 없으면 각 항목에 '해당 없음' 기재.

공고명: {title}
---
{text}
---

{{
  "summary": "## 전체 요약\\n\\n**사업 목적**\\n아래 3가지 관점에서 각각 개조식 1~2줄로:\\n- **본질적 요구사항**: (이 사업이 궁극적으로 해결하려는 문제·필요)\\n- **대상자 및 기대 결과**: (누구를 대상으로, 어떤 변화·성과를 원하는가)\\n- **수행기관에 바라는 역할**: (발주처가 수탁기관에 기대하는 전문성·역할·역량)\\n\\n**주요 과업 범위**\\n(아래 표 형식으로. 대주제는 사업 핵심 카테고리, 소주제는 세부 항목명)\\n| 대주제 | 소주제 | 핵심 내용 |\\n|--------|--------|-----------|\\n| 대주제명 | 소주제명 | 1~2줄 설명 |\\n\\n**계약 기간**\\n(날짜 형식으로, 예: 계약체결일~2026.12.31)\\n\\n**예산 규모**\\n(금액 명시, 예: 1,610,055천원)",
  "kpi": "## KPI / 수치 목표\\n\\n**교육 과정별 상세**\\n(각 과정을 행으로, 해당 항목 없으면 '-'. ⚠️ 교육 시수·교육 시간·교육 인원 목표치가 문서에 있으면 반드시 추출)\\n| 과정명 | 교육기간 | 교육방식 | 교육시간 | 교육대상 | 목표인원 |\\n|--------|----------|----------|----------|----------|----------|\\n| 과정명 | 기간 | 온라인/오프라인/혼합 | N시간 | 대상자 | N명 |\\n(교육 과정이 없는 사업이면 이 표 생략)\\n\\n**주요 수치 목표**\\n- 항목명: 수치 (단위 포함)\\n(참여기업 수·교육인원·멘토링 횟수·만족도 목표·성과목표 등 문서의 숫자 기반 목표 전부 포함. 없으면 해당 없음)",
  "proposal_requirements": "## 제안 요건\\n\\n**참가 자격 요건**\\n(입찰 참가를 위한 최소 조건 — 정량 평가 배점과 무관한 자격 기준)\\n- 일반 자격: (사업자 등록, 면허, 업종코드 등)\\n- 실적 요건: (참가 자격으로서의 최소 수행실적 조건: 금액·분야·기간 등, 없으면 '해당 없음')\\n- 인력 요건: (참가 자격으로서의 최소 투입인력 조건: 자격증·경력·인원수 등, 없으면 '해당 없음')\\n\\n**정량 평가 세부 배점** ← 가장 중요. 배점표 전체를 빠짐없이 추출.\\n| 평가 항목 | 배점 | 평가 방법 | 만점 기준 | 최저 기준 |\\n|-----------|------|-----------|-----------|-----------|\\n| 항목명 | XX점 | 평가 방식 설명 | 만점을 받기 위한 조건 | 최저 득점 조건 |\\n※ 점수 산정 공식이 있으면 수식 그대로 기입 (예: 실적금액/예산×100점)\\n※ 등급 구간이 있으면 모든 구간 표기 (예: 50%이상=만점, 30%이상=X점 등)",
  "special_notes": "## 특이사항\\n\\n**사업 구조 특이점**\\n※ 일반적인 단년도 공모사업과 다른 구조적 특이점만 기재. 없으면 '해당 없음'.\\n- 다년차 여부: (예: 2024년 1차년도 ~ 2026년 3차년도 연속 사업, 또는 해당 없음)\\n- 연계사업 여부: (예: ○○사업과 연계하여 참여자 모집, 또는 해당 없음)\\n- 운영 형태: (방문형/거점형/혼합형/온라인 등 일반과 다른 운영 방식, 또는 해당 없음)\\n- 기타 구조 특이점: (수익자 부담, 매칭펀드, 위탁 재위탁 구조 등)\\n\\n**공동수급 여부**\\n- 허용/불허, 구성원 수·분담비율 등 (없으면 '해당 없음')\\n\\n**예산 편성 특이점**\\n- 부가세 포함 여부, 선급금, 지출 제한 항목 등 (없으면 '해당 없음')\\n\\n**사업 선정 및 운영시 특이사항**\\n※ 일반적인 공공입찰 절차(전자입찰, 나라장터 제출 등)는 생략. 이 사업에서만 적용되는 사항만 아래 태그로 추출. 해당 없는 태그는 줄 전체 생략:\\n- [제출] 제안서 형식·매체·분량 등 특이한 제출 조건\\n- [발표] 발표자 자격 제한, 발표 방식·시간·순서 결정 방법\\n- [주의] 감점·실격 조건, 사전접촉 제한, 식별정보 금지 등\\n- [운영] 사업 수행 중 지켜야 할 특수 조건 (보고 주기, 현장 점검 등)\\n(위 4개 태그 모두 해당 없으면 '해당 없음')\\n\\n**주요 일정**\\n- 제안서 마감: 일시\\n- 발표평가: 일시\\n- 사업설명회: 일시/장소 (있는 경우)\\n\\n**사업 문의처**\\n- 담당자/연락처 (표지의 총괄책임·실무담당 포함)"
}}
"""


def _select_text_for_gemini(text, max_chars=10000):
    """
    RFP 전체 텍스트에서 Gemini 분석에 가장 유용한 부분 선택.
    - 앞부분 5,000자: 요약·예산·KPI·문의처
    - 배점표/자격요건 섹션: 나머지 5,000자
    """
    head = text[:5000]

    # 교육과정 상세 / 배점표·자격요건 섹션 마커 (앞 5,000자 이후에서 탐색)
    _SCORE_MARKERS = [
        # 교육 과정 상세 (KPI용)
        '기본과정', '보수과정', '심화과정', '교육 과정', '교육과정', '교육 내용',
        '교육목표', '교육운영', '교육방식',
        # 배점표·자격요건
        '기술평가 항목 및 배점표', '배점표', '낙찰자 선정방식',
        '참가 자격', '참가자격', '입찰참가자격',
    ]
    tail_start = -1
    for marker in _SCORE_MARKERS:
        pos = text.find(marker, 5000)
        if pos > 0:
            tail_start = max(5000, pos - 300)
            break

    if tail_start > 0:
        remaining = max_chars - len(head) - 20  # 구분자 공간
        tail = text[tail_start:tail_start + remaining]
        return head + '\n\n[...중략...]\n\n' + tail
    return text[:max_chars]


def gemini_analyze(text, api_key, tender_title=''):
    """
    Gemini 2.0 Flash API로 RFP를 4개 섹션으로 구조화 분석.

    Returns dict with keys: summary, kpi, proposal_requirements, special_notes
    각 값은 마크다운 문자열.
    """
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        logger.warning("google-genai 미설치: pip install google-genai")
        return None

    import json as _json
    import time as _time

    # 스마트 텍스트 선택: 앞 5,000자 + 배점표 섹션 5,000자 (총 최대 10,000자)
    # DB 캐싱으로 재호출 없으므로 품질 우선
    truncated = _select_text_for_gemini(text, max_chars=15000)
    prompt = _GEMINI_PROMPT.format(title=tender_title, text=truncated)

    def _call(model_name):
        client = genai.Client(api_key=api_key)
        return client.models.generate_content(
            model=model_name,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type='application/json',
            ),
        )

    # 모델 우선순위: flash-lite (무료 1,500 RPD, 30 RPM) → 2.5-flash → flash
    _MODELS = ['gemini-2.0-flash-lite', 'gemini-2.5-flash', 'gemini-2.0-flash']
    last_error = None
    for model_name in _MODELS:
        try:
            response = _call(model_name)

            raw = response.text.strip()
            if raw.startswith('```'):
                raw = re.sub(r'^```[a-z]*\n?', '', raw)
                raw = re.sub(r'\n?```$', '', raw)
            data = _json.loads(raw)

            def _to_md(v, depth=0):
                """중첩 dict/list를 마크다운 문자열로 재귀 변환"""
                _EMPTY = ('해당 없음', '', 'N/A', '없음', 'null', 'None')
                if v is None:
                    return '해당 없음'
                if isinstance(v, str):
                    return v
                if isinstance(v, list):
                    items = [_to_md(i, depth + 1) for i in v]
                    items = [i for i in items if i.strip() not in _EMPTY]
                    if not items:
                        return '해당 없음'
                    # 이미 bullet(-)로 시작하면 그대로, 아니면 추가
                    return '\n'.join(
                        i if i.startswith(('-', '#', '|', '*', '>', ' ')) else f'- {i}'
                        for i in items
                    )
                if isinstance(v, dict):
                    parts = []
                    for k, sub in v.items():
                        sub_md = _to_md(sub, depth + 1)
                        if sub_md.strip() in _EMPTY:
                            continue
                        if '\n' in sub_md:
                            parts.append(f'**{k}**\n{sub_md}')
                        else:
                            parts.append(f'- **{k}**: {sub_md}')
                    if not parts:
                        return '해당 없음'
                    return '\n'.join(parts)
                return str(v)

            sections = {'_model': model_name}
            for key in ('summary', 'kpi', 'proposal_requirements', 'special_notes'):
                val = data.get(key, '해당 없음')
                val = _to_md(val)
                sections[key] = val.strip() or '해당 없음'

            # ── special_notes 후처리 ─────────────────────────────────────────
            # 1) [실적], [인력] 태그 행 제거: 해당 내용은 '정량 평가 세부 배점'에 이미 포함됨
            sn = sections.get('special_notes', '')
            sn_lines = sn.splitlines()
            sn_lines = [
                l for l in sn_lines
                if not re.match(r'^-\s*\[(?:실적|인력)\]', l.strip())
            ]
            sn = '\n'.join(sn_lines)

            # 2) '사업 구조 특이점' 섹션이 없으면 맨 앞에 '해당 없음'으로 삽입
            if '사업 구조 특이점' not in sn:
                struct_block = (
                    "**사업 구조 특이점**\n"
                    "- 다년차 여부: 해당 없음\n"
                    "- 연계사업 여부: 해당 없음\n"
                    "- 운영 형태: 해당 없음\n"
                )
                # '공동수급' 섹션 앞에 삽입, 없으면 맨 앞에
                if '공동수급' in sn:
                    sn = sn.replace('**공동수급', struct_block + '\n**공동수급', 1)
                else:
                    sn = struct_block + '\n' + sn

            sections['special_notes'] = sn.strip()
            # ─────────────────────────────────────────────────────────────────

            logger.info(f"Gemini 분석 완료 ({model_name})")
            return sections

        except Exception as e:
            err_str = str(e)
            if '429' in err_str or '404' in err_str:
                logger.warning(f"Gemini {model_name} 실패({err_str[:50]}), 다음 모델 시도")
                _time.sleep(2)  # RPM 초과 방지 대기
                continue
            logger.error(f"Gemini API 오류 ({model_name}): {e}")
            return {'error': f'[Gemini 오류] {str(e)[:300]}'}

    return {'error': '[Gemini 오류] 일일 무료 할당량이 초과되었습니다. 내일(한국시간 오후 4~5시) 이후 다시 시도하거나, Google AI Studio에서 결제를 설정해 주세요.'}


# ── 통합 분석 함수 ────────────────────────────────────────────────────────────

def analyze_tender(tender_url, tender_title='', api_key=None, source_site=''):  # noqa: ARG001 (source_site reserved for future site-specific logic)
    """
    공고 URL에서 첨부파일(RFP)을 찾아 분석.

    Returns:
        dict with keys:
          rule_extract    (dict)       — 규칙 기반 추출 결과
          gemini_sections (dict|None)  — Gemini 4개 섹션 분석
          files_found     (list)       — 발견된 파일명 목록
          text_length     (int)        — 추출된 텍스트 길이
          error           (str|None)   — 오류 메시지
    """
    result = {
        'rule_extract': {},
        'gemini_sections': None,
        'files_found': [],
        'text_length': 0,
        'error': None,
    }

    if not tender_url:
        result['error'] = '공고 URL이 없습니다.'
        return result

    # 1. 첨부파일 링크 수집
    links = fetch_attachment_links(tender_url)
    if not links:
        if _G2B_BID_RE.search(tender_url or ''):
            result['error'] = (
                '나라장터 일반입찰 공고의 첨부파일을 자동으로 찾을 수 없습니다.\n'
                '공고 원문(나라장터) 페이지에서 직접 파일을 확인해 주세요.'
            )
        else:
            result['error'] = (
                '첨부파일(HWP/HWPX/PDF)을 자동으로 찾을 수 없습니다.\n'
                '공고 원문 페이지에서 직접 파일을 확인해 주세요.'
            )
        return result

    # files_found는 정렬 후 설정 (아래에서 처리)

    # ─────────────────────────────────────────────────────────────────────────
    # 2. 파일 우선순위 정렬 (방안 A) + 빈 양식 파일 건너뜀 (방안 B)
    # ─────────────────────────────────────────────────────────────────────────

    # ── 최우선 파일: 파일명에 이게 있으면 양식 키워드와 무관하게 항상 가장 먼저 처리
    # (예: "제안요청서(양식).hwp"는 양식 단어가 있어도 반드시 최우선)
    # 제안요청서·과업지시서가 제일 중요한 내용이므로 공고문보다 먼저 처리
    _TOP_PRIORITY = ['제안요청서', '과업지시서', '공고문']

    # [방안 A] 기타 중요 파일 순서
    _PRIORITY = [
        '제안서', '과업내용서', '과업지시서', '사업설명서',
        '공고안내서', '입찰공고', 'rfp',
    ]

    # [방안 B] 이 키워드가 파일명에 있으면 '빈 양식'으로 간주해 맨 뒤로 미룸
    # → 단, _TOP_PRIORITY 키워드가 함께 있으면 최우선으로 처리됨 (아래 _file_priority 참조)
    _SKIP_KEYWORDS = [
        '입찰참가사용양식', '양식', '서약서', '서약', '신청서', '보증서',
        '서식', '확인서', '동의서', '위임장', '하도급',
    ]

    def _file_priority(link):
        """파일 하나의 우선순위 숫자를 반환 (숫자가 작을수록 먼저 처리)"""
        name_lower = link.get('name', '').lower()
        # ① 공고문·제안요청서·과업지시서: 양식 여부와 무관하게 항상 최우선
        for i, kw in enumerate(_TOP_PRIORITY):
            if kw in name_lower:
                return i  # 0, 1, 2
        # ② 양식/서식 파일: 최하위 (①에 해당 안 됐을 때만)
        if any(k in name_lower for k in _SKIP_KEYWORDS):
            return 999
        # ③ 기타 중요 파일 키워드
        for i, kw in enumerate(_PRIORITY):
            if kw in name_lower:
                return len(_TOP_PRIORITY) + i
        # ④ 나머지
        return len(_TOP_PRIORITY) + len(_PRIORITY)

    # 우선순위 기준으로 정렬
    sorted_links = sorted(links, key=_file_priority)

    # 중요 파일(999 미만)과 양식 파일(999)을 분리
    main_links  = [l for l in sorted_links if _file_priority(l) < 999]
    form_links  = [l for l in sorted_links if _file_priority(l) == 999]

    # 중요 파일 먼저, 양식 파일은 뒤에 (중요 파일이 없을 경우 보완용)
    ordered_links = main_links + form_links

    logger.info(f"파일 처리 순서: {[l['name'] for l in ordered_links]}")

    # 발견된 파일 이름 목록: 정렬된 처리 순서로 표시 (실제 읽힌 파일 추적 포함)
    result['files_found'] = [l['name'] for l in ordered_links[:8]]

    texts = []
    files_read = []  # 실제로 텍스트가 성공적으로 추출된 파일 목록
    with tempfile.TemporaryDirectory() as tmpdir:
        # 최대 5개 파일을 처리 (같은 내용의 HWP·PDF 중복 등 고려)
        for link in ordered_links[:5]:
            filepath = download_file(link['url'], tmpdir)
            if not filepath:
                logger.info(f"다운로드 실패: {link.get('name', '')}")
                continue  # 다운로드 실패 시 건너뜀
            text = extract_text(filepath)
            if not text or len(text) < 50:
                logger.info(f"텍스트 추출 실패/너무 짧음: {link.get('name', '')} ({len(text) if text else 0}자)")
                continue  # 텍스트 추출 실패 시 건너뜀
            fname = link.get('name', '')
            # 양식 파일(999)은 앞에서 중요 파일을 이미 읽었으면 스킵
            if _file_priority(link) == 999 and texts:
                logger.info(f"양식 파일 스킵: {fname}")
                continue
            # 어떤 파일에서 온 텍스트인지 표시해서 합산
            texts.append(f'[파일: {fname}]\n{text}')
            files_read.append(fname)
            logger.info(f"파일 읽기 성공: {fname} ({len(text)}자)")

    # 실제로 읽힌 파일을 files_found 앞에 표시 (★ 마킹)
    if files_read:
        result['files_found'] = [f'★ {f}' for f in files_read] + \
            [l['name'] for l in ordered_links[:8] if l['name'] not in files_read][:3]

    # 여러 파일의 텍스트를 하나로 합침
    combined_text = '\n\n'.join(texts)

    if not combined_text or len(combined_text) < 50:
        result['error'] = (
            '파일을 다운로드했으나 텍스트를 추출할 수 없었습니다.\n'
            'HWP 바이너리 파일은 추가 라이브러리(gethwp 또는 olefile)가 필요합니다.'
        )
        return result

    result['text_length'] = len(combined_text)

    # 3. A: 규칙 기반 핵심 정보 추출 (빠른 보조 데이터)
    result['rule_extract'] = rule_based_extract(combined_text)

    # 4. C: Gemini 4개 섹션 분석 (API 키 있을 때만)
    if api_key:
        result['gemini_sections'] = gemini_analyze(combined_text, api_key, tender_title)

    return result
