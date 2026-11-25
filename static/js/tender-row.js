// 공고 한 줄 — 대시보드·검색·관심공고가 함께 쓴다 (2026-11 디자인 개편, B 목록형).
// 외부에서 온 글자(제목·기관)는 common.js 의 safeHtml/highlightSafe 를 거쳐 넣는다.
// 표시 규칙: docs/superpowers/specs/2026-11-24-hisearch-design-refresh-design.md

// 금액: 1억 이상 "5.5억", 1만원 이상 "3,000만원", 없으면 "금액 미정"
function hsPrice(won) {
    const n = Number(won);
    if (!won || !isFinite(n) || n <= 0) return '금액 미정';
    if (n >= 1e8) {
        const eok = Math.round(n / 1e7) / 10;           // 소수 한 자리
        return (Number.isInteger(eok) ? String(eok) : eok.toFixed(1)) + '억';
    }
    if (n >= 1e4) return Math.round(n / 1e4).toLocaleString('ko-KR') + '만원';
    return n.toLocaleString('ko-KR') + '원';
}

// 마감: days_left(서버 계산) 기준. 오늘~2일 빨강, 3~7일 주황, 그 이상 회색
function hsDday(t) {
    const d = (t && t.days_left !== undefined) ? t.days_left : null;
    if (d === null || d === undefined) return { cls: '', top: '마감일', big: '없음', label: '마감 미정' };
    if (d < 0)  return { cls: '', top: '마감', big: '지남', label: '마감 지남' };
    if (d === 0) return { cls: 'hs-dd-bad', top: '오늘', big: '마감', label: '오늘 마감' };
    if (d <= 2) return { cls: 'hs-dd-bad', top: '마감', big: 'D-' + d, label: 'D-' + d };
    if (d <= 7) return { cls: 'hs-dd-warn', top: '마감', big: 'D-' + d, label: 'D-' + d };
    return { cls: '', top: '마감', big: 'D-' + d, label: 'D-' + d };
}

// 신규: 최근 24시간 안에 새로 수집된 공고. created_at 은 UTC 로 저장된다 (표준시 표기가 없으면 UTC 로 읽는다)
const HS_NEW_HOURS = 24;
function hsCollectedMs(t) {
    if (!t || !t.created_at) return null;
    const s = String(t.created_at);
    const ms = Date.parse(/[zZ]|[+-]\d\d:?\d\d$/.test(s) ? s : s + 'Z');
    return isNaN(ms) ? null : ms;
}
function hsIsNew(t, nowMs) {
    const ms = hsCollectedMs(t);
    if (ms === null) return false;
    const age = (nowMs === undefined ? Date.now() : nowMs) - ms;
    return age >= 0 && age <= HS_NEW_HOURS * 3600 * 1000;
}

// 구분: 사전규격 / 나라장터 입찰 / 기타 채널
function hsKind(t) {
    if ((t.status || '') === '사전규격') return { key: 'pre', label: '사전규격', cls: 'hs-chip-pre' };
    const src = t.source_site || '';
    if (src.indexOf('나라장터') >= 0 || src.indexOf('g2b') >= 0) return { key: 'g2b', label: '나라장터 입찰', cls: 'hs-chip-g2b' };
    return { key: 'other', label: '기타 채널', cls: 'hs-chip-other' };
}

// 기관: 조달청 대행이면 수요기관, 중소벤처24 는 수요기관 우선
function hsAgency(t) {
    if (t.source_site === '중소벤처 24') return t.demand_agency || t.agency || '-';
    if (t.agency && t.agency.indexOf('조달청') >= 0 && t.demand_agency) return t.demand_agency;
    return t.agency || t.demand_agency || '-';
}

function hsStarButton(t, bookmarked) {
    const on = bookmarked && bookmarked.has(t.id);
    return `<button type="button" class="hs-icon-btn hs-star${on ? ' on' : ''}" aria-pressed="${on}" aria-label="${on ? '관심공고에서 빼기' : '관심공고에 담기'}" onclick="hsToggleBookmark(${t.id}, this)">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="${on ? 'currentColor' : 'none'}" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M12 3l2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1L3.2 9.5l6.1-.9z"></path></svg>
    </button>`;
}

// 색은 화면에 나온 공고끼리 견주지 않고 100점 만점 기준으로 정한다 — 같은 점수는 어느 화면에서나 같은 색.
// 30점 이하 빨강 → 60점 노랑 → 90점 이상 녹색
const HS_SCORE_RED = 30, HS_SCORE_GREEN = 90;
function hsScoreHue(score) {
    const t = (score - HS_SCORE_RED) / (HS_SCORE_GREEN - HS_SCORE_RED);
    return Math.round(Math.max(0, Math.min(1, t)) * 130);      // 0 = 빨강, 65 = 노랑, 130 = 녹색
}
function hsScoreStyle(score) {
    if (score === null || score === undefined) return 'background: var(--hs-surface); color: var(--hs-muted)';
    const h = hsScoreHue(Number(score));
    return `background: hsl(${h}, 75%, 89%); color: hsl(${h}, 80%, 23%)`;
}

// 적합도 구성 설명 (숫자 위에 마우스를 올리면 보인다). bd = score_breakdown {keyword, type, case, agency, base}
// 적합도 = 키워드·유형 점수(100점 환산) — 담은 공고가 5건 이상이면 닮음 점수와 평균 — 에 등록한 발주처 가감점을 더한 값.
function hsSigned(n) {
    const v = Number(n);
    return (v > 0 ? '+' : v < 0 ? '−' : '') + String(Math.abs(v));
}
function hsScoreTip(score, bd) {
    if (score === null || score === undefined) return '적합도 없음';
    let tip = '적합도 ' + Number(score).toFixed(1);
    if (!bd || bd.base === undefined || bd.base === null) return tip;
    tip += ' = 키워드·유형 ' + Number(bd.base).toFixed(1);
    if (bd.case !== null && bd.case !== undefined) tip += ' 와 담은 공고 닮음 ' + Number(bd.case).toFixed(1) + ' 의 평균';
    if (bd.agency) tip += ' + 발주처 ' + hsSigned(bd.agency);
    return tip;
}
// 등록한 발주처의 가감점 칩 (가감점이 없으면 빈 문자열)
function hsAdjustChip(bd) {
    if (!bd || !bd.agency) return '';
    const plus = Number(bd.agency) > 0;
    return `<span class="hs-chip ${plus ? 'hs-chip-ok' : 'hs-chip-bad'}" title="등록한 발주처 ${plus ? '가점' : '감점'}">발주처 ${hsSigned(bd.agency)}</span>`;
}

// 공고 한 줄 — 항상 두 줄이다. 앞 칸: 적합도 / 첫 줄: 제목 / 둘째 줄: 구분·기관·금액·유형 … / 오른쪽: 마감·버튼
// opts: { keywords, bookmarked:Set, dismiss:bool, announced:bool(공고일), origin:bool(원문 링크),
//         metaHtml:string(둘째 줄 끝에 붙일, 이미 이스케이프된 HTML), actionsHtml:string }
function renderTenderRow(t, opts) {
    opts = opts || {};
    const dd = hsDday(t);
    const kind = hsKind(t);
    const title = typeof cleanNoticeTitle === 'function' ? cleanNoticeTitle(t.title || '') : (t.title || '');
    const kws = (opts.keywords || []).filter(k => k && title.toLowerCase().indexOf(String(k).toLowerCase()) >= 0);
    const titleHtml = typeof highlightSafe === 'function' ? highlightSafe(title, kws, 'hs-mark') : safeHtml(title);
    const badges = typeof getNoticeBadgesHtml === 'function' ? getNoticeBadgesHtml(t.title || '') : '';
    const score = (t.relevance_score !== undefined && t.relevance_score !== null) ? Number(t.relevance_score) : null;
    const bd = t.score_breakdown;
    const scoreTip = hsScoreTip(score, bd);
    const type = (t.business_type && t.business_type !== '기타') ? t.business_type : '';
    const dismiss = opts.dismiss
        ? `<button type="button" class="hs-icon-btn" aria-label="관심없음 — 목록에서 숨기기" title="관심없음" onclick="dismissTender(${t.id}, this)">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18"></path></svg>
           </button>` : '';
    const expired = t.days_left !== null && t.days_left !== undefined && t.days_left < 0;
    const announced = (opts.announced && t.announced_date) ? `<span>공고 ${safeHtml(String(t.announced_date).substring(5, 10))}</span>` : '';
    const memo = t.memo_count > 0 ? `<span class="hs-chip" title="팀 메모 ${t.memo_count}개">메모 ${t.memo_count}</span>` : '';
    const origin = (opts.origin && t.url && typeof safeUrl === 'function')
        ? `<a class="hs-link" href="${safeUrl(t.url)}" target="_blank" rel="noopener noreferrer">원문</a>` : '';
    return `<li class="hs-row${expired ? ' hs-row-expired' : ''}" data-id="${t.id}">
        <div class="hs-score" style="${hsScoreStyle(score)}" title="${safeHtml(scoreTip)}" aria-label="${safeHtml(scoreTip)}">
            <small>적합도</small><strong data-score="${t.id}">${score === null ? '-' : score.toFixed(1)}</strong>
        </div>
        <div class="hs-row-body">
            <a class="hs-row-title" href="/tender/${t.id}" target="_blank" rel="noopener" title="${safeHtml(title)}">${badges}${titleHtml}</a>
            <div class="hs-row-line2">
                ${hsIsNew(t) ? '<span class="hs-chip hs-chip-new">신규</span>' : ''}
                <span class="hs-chip ${kind.cls}">${kind.label}</span>
                <span class="hs-row-agency">${safeHtml(hsAgency(t))}</span>
                <b class="hs-row-price${t.estimated_price ? '' : ' none'}">${hsPrice(t.estimated_price)}</b>
                ${type ? `<span>${safeHtml(type)}</span>` : ''}
                ${hsAdjustChip(bd)}${announced}${origin}${memo}${opts.metaHtml || ''}
            </div>
        </div>
        <div class="hs-row-side">
            <span class="hs-deadline ${dd.cls}" title="마감까지">${dd.label}</span>
            <div class="hs-row-actions">${opts.actionsHtml !== undefined ? opts.actionsHtml : hsStarButton(t, opts.bookmarked) + dismiss}</div>
        </div>
    </li>`;
}

async function hsToggleBookmark(tenderId, btn) {
    try {
        const res = await fetch('/api/bookmarks/toggle', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ tender_id: tenderId })
        });
        const data = await res.json();
        const on = !!data.bookmarked;
        if (typeof bookmarkedIds !== 'undefined') { on ? bookmarkedIds.add(tenderId) : bookmarkedIds.delete(tenderId); }
        btn.classList.toggle('on', on);
        btn.setAttribute('aria-pressed', String(on));
        btn.setAttribute('aria-label', on ? '관심공고에서 빼기' : '관심공고에 담기');
        const svg = btn.querySelector('svg');
        if (svg) svg.setAttribute('fill', on ? 'currentColor' : 'none');
    } catch (e) { console.error(e); }
}

if (typeof module !== 'undefined') module.exports = { hsPrice, hsDday, hsKind, hsAgency, hsIsNew, hsCollectedMs, hsScoreHue, hsScoreTip, hsAdjustChip };
