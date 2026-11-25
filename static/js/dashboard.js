// 대시보드 (2026-11 디자인 개편, B 목록형)
// 데이터: /api/dashboard (구역 3개 — 점수와 순서는 서버가 준 그대로 쓴다), /api/dashboard/key-agencies (중점 발주처),
//         /api/cases/similar (비슷한 공고)
// 공고 한 줄은 tender-row.js 의 renderTenderRow 가 그린다.

let includeKeywords = [];
let bookmarkedIds = new Set();
let dismissedIds = new Set();
let dashData = null;
let similarData = null;
let keyData = null;
let recentData = null;
let viewedIds = new Set();
let currentTab = 'all';

const SECTION_KEY = { pre: 'pre_tenders', urgent: 'urgent_tenders', recent: 'recent_tenders' };
// 계정마다 따로 둔다 — 같은 브라우저에서 다른 계정으로 들어왔을 때 앞 사람의 점수·표시가 비치지 않게
const _DASH_CACHE_KEY = 'dashboard_cache_v5_u' + HS_USER_ID;
try { ['dashboard_cache_v3', 'dashboard_cache_v4'].forEach(k => localStorage.removeItem(k)); } catch (_) { /* 계정 구분 없던 예전 캐시는 지운다 */ }
const _SORT_KEY = 'dashboard_sort';
let _lastFetchTime = 0;

// ── 불러오기 ────────────────────────────────────────────────────────────────

function _reloadDashboard() {
    Promise.all([loadBookmarkedIds(), loadDismissedIds(), loadViewedIds()]).then(() => {
        loadDashboardData();
        loadKeyAgencies();
        loadSimilar();
        loadRecent();
    });
}

document.addEventListener('DOMContentLoaded', () => {
    // 고른 나열 방식을 기억한다
    try {
        const saved = localStorage.getItem(_SORT_KEY);
        const sel = document.getElementById('dash-sort');
        if (saved && [...sel.options].some(o => o.value === saved)) sel.value = saved;
    } catch (_) { /* 무시 */ }
    // 공고를 열면 목록에서 빠져 '읽은 공고'로 간다 (상세 화면이 열람을 기록한다)
    document.getElementById('hs-list').addEventListener('click', e => {
        const a = e.target.closest('a.hs-row-title');
        const row = a && a.closest('.hs-row');
        if (row) markRead(row);
    });
    _reloadDashboard();
});
window.addEventListener('pageshow', e => { if (e.persisted) _reloadDashboard(); });
document.addEventListener('visibilitychange', () => {
    if (!document.hidden && Date.now() - _lastFetchTime > 60_000) _reloadDashboard();
});

async function loadBookmarkedIds() {
    try { bookmarkedIds = new Set(await (await fetch('/api/bookmarks/ids')).json()); } catch (e) { /* 무시 */ }
}

async function loadViewedIds() {
    try { viewedIds = new Set(await (await fetch('/api/viewed/ids')).json()); } catch (e) { /* 무시 */ }
}

// 최근 본 공고 — 열어 봤지만 담지도 숨기지도 않은, 마감 전 공고 (서버가 14일·24건으로 제한)
async function loadRecent() {
    try {
        const res = await fetch('/api/viewed/recent');
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || res.status);
        recentData = data;
    } catch (e) {
        recentData = { error: true, items: [] };
    }
    updateCounts();
    renderShelf();
    if (currentTab === 'recent_viewed') renderList();
}

async function loadDismissedIds() {
    try { dismissedIds = new Set(await (await fetch('/api/dismissed/ids')).json()); } catch (e) { /* 무시 */ }
}

async function loadDashboardData() {
    // 저장해 둔 지난 응답을 먼저 보여 주고(끊김 방지), 새 응답이 오면 바꾼다
    try {
        const cached = localStorage.getItem(_DASH_CACHE_KEY);
        if (cached) {
            applyDashboardData(JSON.parse(cached));
        }
    } catch (_) { /* 저장소를 못 쓰면 바로 새 응답 */ }

    try {
        const data = await (await fetch('/api/dashboard?fresh=1')).json();
        if (data.error) { console.error('Error:', data.error); return; }
        _lastFetchTime = Date.now();
        try { localStorage.setItem(_DASH_CACHE_KEY, JSON.stringify(data)); } catch (_) { /* 무시 */ }
        applyDashboardData(data);
    } catch (error) {
        console.error('Failed to load dashboard data:', error);
        if (!dashData) document.getElementById('list-caption').textContent = '공고를 불러오지 못했습니다.';
    }
}

function applyDashboardData(data) {
    dashData = data;
    includeKeywords = data.include_keywords || [];
    const s = data.summary || {};
    const fmt = n => (n === undefined || n === null) ? '-' : Number(n).toLocaleString('ko-KR');
    document.getElementById('new-today').textContent = fmt(s.new_today);
    document.getElementById('keyword-match').textContent = fmt(s.keyword_match);
    document.getElementById('pre-announcement').textContent = fmt(s.pre_announcement);
    document.getElementById('deadline-soon').textContent = fmt(s.deadline_soon);
    document.getElementById('total-tenders').textContent = fmt(s.total);
    renderKeywords();
    renderList();
}

// 중점 발주처 — 중점으로 등록한 발주처의 아직 안 본 공고 (적합도·관심 키워드와 상관없이)
async function loadKeyAgencies() {
    try {
        const res = await fetch('/api/dashboard/key-agencies');
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || res.status);
        keyData = data;
    } catch (e) {
        keyData = { error: true, agencies: [], items: [] };
    }
    updateCounts();
    if (currentTab === 'key') renderList();
}

async function loadSimilar() {
    try {
        const res = await fetch('/api/cases/similar');
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || res.status);
        similarData = data;
    } catch (e) {
        similarData = { error: true };
    }
    updateCounts();
    if (currentTab === 'similar') renderList();
}

// 한 번에 볼 공고는 탭마다 15건 — '진짜 중요한 것만' (쪽 넘기기 없이 세로로 본다)
const MAX_ITEMS = 15;

function resetPageAndRender() { renderList(); }

// ── 읽은 공고 선반 — 열어 본 공고는 목록에서 바로 빠져 여기로 온다 ─────────────
let justReadId = null;

function _readItems() {
    return recentData && recentData.items ? recentData.items.filter(t => !dismissedIds.has(t.id) && !bookmarkedIds.has(t.id)) : [];
}

function renderShelf() {
    const box = document.getElementById('hs-read-shelf');
    const items = _readItems();
    if (!items.length || currentTab === 'recent_viewed') { box.hidden = true; box.innerHTML = ''; return; }
    const chip = t => {
        const title = typeof cleanNoticeTitle === 'function' ? cleanNoticeTitle(t.title || '') : (t.title || '');
        return `<span class="hs-read-chip${t.id === justReadId ? ' flash' : ''}">
            <a href="/tender/${t.id}" target="_blank" rel="noopener" title="${safeHtml(title)}"><b>${hsDday(t).label}</b> ${safeHtml(title)}</a>
            <button type="button" aria-label="읽은 공고에서 지우기" title="읽은 공고에서 지우기" onclick="clearRead(${t.id})">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18"></path></svg>
            </button></span>`;
    };
    const SHOW = 3;
    box.innerHTML = `<span class="hs-read-label"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M5 12l5 5 9-10"></path></svg>읽은 공고</span>`
        + items.slice(0, SHOW).map(chip).join('')
        + `<button type="button" class="hs-read-more" onclick="setTab('recent_viewed')">${items.length > SHOW ? `외 ${items.length - SHOW}건 · ` : ''}모두 보기</button>`;
    box.hidden = false;
}

async function clearRead(tenderId) {
    try {
        const res = await fetch(`/api/viewed/${tenderId}`, { method: 'DELETE' });
        if (!res.ok) throw new Error(res.status);
        if (recentData && recentData.items) recentData.items = recentData.items.filter(t => t.id !== tenderId);
        updateCounts();
        renderShelf();
        if (currentTab === 'recent_viewed') renderList();
    } catch (e) { console.error(e); }
}

// 공고를 열었다: 목록에서 바로 빼고 읽은 공고 선반에 올린다. 빈자리는 다음 순위로 채운다
function markRead(row) {
    const id = Number(row.dataset.id);
    if (viewedIds.has(id) && currentTab !== 'recent_viewed') return;
    viewedIds.add(id);
    if (currentTab === 'recent_viewed') return;
    const pool = [...Object.values(SECTION_KEY).flatMap(k => (dashData && dashData[k]) || []),
                  ...((keyData && keyData.items) || []), ...((similarData && similarData.items) || [])];
    const t = pool.find(x => x.id === id);
    if (t) {
        recentData = recentData && recentData.items ? recentData : { items: [], days: 7 };
        recentData.items = [{ ...t, viewed_at: new Date().toISOString() }, ...recentData.items.filter(x => x.id !== id)];
    }
    justReadId = id;
    row.style.transition = 'opacity .25s, transform .25s';
    row.style.opacity = '0';
    row.style.transform = 'translateY(-6px)';
    setTimeout(() => { renderList(); }, 260);
    setTimeout(() => { justReadId = null; loadDashboardData(); loadKeyAgencies(); loadRecent(); }, 2000);   // 상세 화면이 열람을 기록한 뒤 다시 받는다
}

// ── 그리기 ─────────────────────────────────────────────────────────────────

function renderKeywords() {
    const box = document.getElementById('active-keywords');
    if (!includeKeywords.length) {
        box.innerHTML = '<a href="/filters" class="hs-link" style="font-size: 13px">관심 키워드를 설정하세요</a>';
        return;
    }
    const MAX = 14;
    box.innerHTML = includeKeywords.slice(0, MAX).map(k => `<span class="hs-kw">${safeHtml(k)}</span>`).join('')
        + (includeKeywords.length > MAX ? `<a href="/filters" class="hs-kw" style="background: var(--hs-surface); color: var(--hs-muted)">+${includeKeywords.length - MAX}개</a>` : '');
}

function setTab(tab) {
    currentTab = tab;
    document.querySelectorAll('#dash-tabs .hs-tab').forEach(b => {
        const on = b.dataset.tab === tab;
        b.classList.toggle('active', on);
        b.setAttribute('aria-selected', String(on));
    });
    renderList();
}

function _visible(items) {
    const week = document.getElementById('f-week').checked;
    const big = document.getElementById('f-big').checked;
    const noPrice = document.getElementById('f-noprice').checked;
    return items.filter(t => {
        if (dismissedIds.has(t.id) || viewedIds.has(t.id)) return false;
        if (week && !(t.days_left !== null && t.days_left !== undefined && t.days_left <= 7)) return false;
        if (big && !(t.estimated_price >= 1e8)) return false;
        if (noPrice && !t.estimated_price) return false;
        return true;
    });
}

function _sectionItems(sec) {
    return _visible((dashData && dashData[SECTION_KEY[sec]]) || []);
}

function _tabItems(tab) {
    if (tab === 'similar') return similarData && similarData.items ? _visible(similarData.items) : [];
    if (tab === 'key') return keyData && keyData.items ? _visible(keyData.items) : [];
    if (tab !== 'all') return _sectionItems(tab);
    // 전체: 세 구역을 합쳐 서버와 같은 순서로 — 후순위 발주처는 맨 아래, 적합도 순, 같으면 중점 발주처 먼저
    return hsRankSort([..._sectionItems('pre'), ..._sectionItems('urgent'), ..._sectionItems('recent')]);
}

// 수집한 날(현지 날짜) — '신규 먼저'는 날짜 단위로 묶고 그 안에서는 받은 순서(적합도)를 지킨다
function _dayOf(t) {
    const ms = hsCollectedMs(t);
    if (ms === null) return 0;
    const d = new Date(ms);
    return d.getFullYear() * 10000 + (d.getMonth() + 1) * 100 + d.getDate();
}

function _sorted(items) {
    const by = document.getElementById('dash-sort').value;
    try { localStorage.setItem(_SORT_KEY, by); } catch (_) { /* 무시 */ }
    const withIdx = items.map((t, i) => [t, i]);
    const cmp = {
        days: (a, b) => (a.days_left ?? 99999) - (b.days_left ?? 99999),
        price: (a, b) => (b.estimated_price ?? -1) - (a.estimated_price ?? -1),
        new: (a, b) => _dayOf(b) - _dayOf(a),
    }[by];
    if (!cmp) return items;                       // 추천순 = 받은 순서
    return withIdx.sort((x, y) => cmp(x[0], y[0]) || (x[1] - y[1])).map(x => x[0]);
}

function updateCounts() {
    if (dashData) {
        ['pre', 'urgent', 'recent'].forEach(s => { document.getElementById('cnt-' + s).textContent = _sectionItems(s).length; });
        document.getElementById('cnt-all').textContent = Math.min(MAX_ITEMS, _tabItems('all').length);
    }
    const rc = document.getElementById('cnt-recent_viewed');
    rc.textContent = recentData && recentData.items ? _readItems().length : '';
    const key = document.getElementById('cnt-key');
    key.textContent = keyData && keyData.agencies && keyData.agencies.length ? _tabItems('key').length : '';
    const sim = document.getElementById('cnt-similar');
    sim.textContent = similarData && similarData.enabled ? _tabItems('similar').length : '';
}

// 요약 칸 — 사이트의 목적은 "공고가 나자마자 맞는 사업을 찾아 미리 준비"다.
// 그래서 마감이 아니라 새로 들어온 맞는 공고를 알려 준다. 보이는 목록에서 계산한 사실만 쓴다.
function renderToday(items) {
    const box = document.getElementById('hs-today');
    if (currentTab === 'similar' || currentTab === 'key' || currentTab === 'recent_viewed' || !dashData) { box.hidden = true; return; }
    const fresh = items.filter(t => hsIsNew(t));
    const label = '<b class="hs-today-label">새로 나온 공고</b> · ';
    if (!fresh.length) {
        box.innerHTML = label + `최근 ${HS_NEW_HOURS}시간 안에 새로 들어온 맞는 공고가 없습니다.`;
        box.hidden = false;
        return;
    }
    const by = { pre: 0, g2b: 0, other: 0 };
    fresh.forEach(t => { by[hsKind(t).key]++; });
    const parts = [];
    if (by.pre) parts.push(`사전규격 ${by.pre}`);
    if (by.g2b) parts.push(`나라장터 입찰 ${by.g2b}`);
    if (by.other) parts.push(`기타 채널 ${by.other}`);
    const best = hsRankSort(fresh)[0];        // 후순위 발주처의 공고는 '가장 잘 맞는 공고'로 내세우지 않는다
    const title = typeof cleanNoticeTitle === 'function' ? cleanNoticeTitle(best.title || '') : (best.title || '');
    const why = [];
    if (best.relevance_score !== undefined && best.relevance_score !== null) why.push(`적합도 ${Number(best.relevance_score).toFixed(1)}`);
    box.innerHTML = label + `최근 ${HS_NEW_HOURS}시간 안에 새로 들어온 맞는 공고 <b>${fresh.length}건</b>(${parts.join(', ')}). `
        + `가장 잘 맞는 공고는 <a class="hs-link" href="/tender/${best.id}" target="_blank" rel="noopener">${safeHtml(title)}</a>`
        + (why.length ? `(${why.join(', ')})` : '') + '입니다.';
    box.hidden = false;
}

function renderList() {
    if (!dashData) return;
    updateCounts();
    renderShelf();
    const list = document.getElementById('hs-list');
    const cap = document.getElementById('list-caption');

    if (currentTab === 'similar') {
        renderToday([]);
        if (!similarData) { cap.textContent = '불러오는 중…'; list.innerHTML = ''; return; }
        if (similarData.error) { cap.textContent = '비슷한 공고를 불러오지 못했습니다.'; list.innerHTML = ''; return; }
        if (!similarData.enabled) {
            cap.textContent = '';
            list.innerHTML = `<li class="hs-empty">사례를 ${similarData.min_cases}건 이상 모으면 켜집니다 (지금 ${similarData.cases}건).<br>북마크하거나 <a href="/cases" class="hs-link">놓친 공고</a>를 신고하면 사례가 됩니다.</li>`;
            return;
        }
        const items = _sorted(_tabItems('similar')).slice(0, MAX_ITEMS);
        cap.textContent = '관심 키워드에는 걸리지 않았지만, 담아 두신 공고와 비슷한 공고 · 좋음을 누르면 다음부터 이런 공고를 더 찾습니다';
        list.innerHTML = items.length ? items.map(t => renderTenderRow(t, {
            keywords: includeKeywords,
            actionsHtml: `<button type="button" class="hs-btn hs-btn-yes" onclick="markSimilarGood(${t.id}, this)">좋음</button>
                <button type="button" class="hs-btn hs-btn-no" onclick="dismissTender(${t.id}, this)">아님</button>`,
        })).join('') : '<li class="hs-empty">지금은 사례와 충분히 비슷한 공고가 없습니다.</li>';
        return;
    }

    if (currentTab === 'key') {
        renderToday([]);
        if (!keyData) { cap.textContent = '불러오는 중…'; list.innerHTML = ''; return; }
        if (keyData.error) { cap.textContent = '중점 발주처 공고를 불러오지 못했습니다.'; list.innerHTML = ''; return; }
        if (!keyData.agencies.length) {
            cap.textContent = '';
            list.innerHTML = '<li class="hs-empty">발주처를 중점으로 등록하면 그 발주처의 새 공고가 여기에 모입니다.<br><a href="/filters" class="hs-link">필터관리에서 등록</a></li>';
            return;
        }
        // 모든 중점 발주처의 공고를 한데 모아 적합도 높은 순으로 (서버가 준 순서). 점수가 낮아도 빠지지 않는다.
        // 본 목록과 달리 여기서는 발주처 이름이 중요하므로 줄마다 등록한 이름을 칩으로 보여 준다
        const items = _sorted(_tabItems('key')).slice(0, MAX_ITEMS);
        const names = keyData.agencies.slice(0, 4).join(', ') + (keyData.agencies.length > 4 ? ` 외 ${keyData.agencies.length - 4}곳` : '');
        cap.textContent = `${items.length}건 · 중점 발주처(${names})의 아직 안 본 공고 · 관심 키워드와 상관없이 모아 적합도 높은 순으로`;
        list.innerHTML = items.length
            ? items.map(t => renderTenderRow(t, { keywords: includeKeywords, bookmarked: bookmarkedIds, dismiss: true, noAgencyChip: true,
                metaHtml: t.matched_agency ? `<span class="hs-chip hs-chip-key" title="중점으로 등록한 발주처">${safeHtml(t.matched_agency)}</span>` : '' })).join('')
            : '<li class="hs-empty">중점 발주처의 진행 중인 새 공고가 없습니다.</li>';
        return;
    }

    if (currentTab === 'recent_viewed') {
        renderToday([]);
        if (!recentData) { cap.textContent = '불러오는 중…'; list.innerHTML = ''; return; }
        const items = _readItems().slice(0, MAX_ITEMS);
        cap.textContent = `열어 봤지만 아직 담지 않은 공고 · 마감 전, 최근 ${recentData.days || 7}일 · 별표를 누르면 관심공고로 옮겨집니다`;
        list.innerHTML = items.length
            ? items.map(t => renderTenderRow(t, { keywords: includeKeywords, bookmarked: bookmarkedIds,
                metaHtml: `<span>${safeHtml(_agoText(t.viewed_at))} 봄</span>`,
                actionsHtml: hsStarButton(t, bookmarkedIds)
                    + `<button type="button" class="hs-icon-btn" aria-label="읽은 공고에서 지우기" title="읽은 공고에서 지우기" onclick="clearRead(${t.id})">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18"></path></svg></button>` })).join('')
            : '<li class="hs-empty">읽은 공고가 없습니다.<br>공고를 열어 보면 목록에서 빠져 여기에 모이고, 마감이 지나거나 담으면 빠집니다.</li>';
        return;
    }

    const items = _sorted(_tabItems(currentTab)).slice(0, MAX_ITEMS);
    const total = items.length;
    renderToday(items);
    if (!includeKeywords.length && currentTab !== 'recent') {
        cap.textContent = '';
        list.innerHTML = '<li class="hs-empty">관심 키워드를 <a href="/filters" class="hs-link">설정</a>하면 맞는 공고를 보여 드립니다.</li>';
        return;
    }
    cap.textContent = currentTab === 'all' ? `아직 안 본 맞는 공고 중 상위 ${total}건`
        : currentTab === 'pre' ? `${total}건 · 사전규격은 본 공고보다 먼저 나와, 가장 일찍 준비할 수 있는 단계입니다`
        : `${total}건`;
    list.innerHTML = items.length
        ? items.map(t => renderTenderRow(t, { keywords: includeKeywords, bookmarked: bookmarkedIds, dismiss: true })).join('')
        : '<li class="hs-empty">조건에 맞는 공고가 없습니다.</li>';
}

// '방금' / '3시간 전' / '어제' / '5일 전'
function _agoText(iso) {
    const ms = Date.now() - Date.parse(iso);
    if (isNaN(ms)) return '';
    const h = Math.floor(ms / 3600000);
    if (h < 1) return '방금';
    if (h < 24) return `${h}시간 전`;
    const d = Math.floor(h / 24);
    return d === 1 ? '어제' : `${d}일 전`;
}

// ── 동작 ───────────────────────────────────────────────────────────────────

// 관심없음: 이유를 하나 골라야 제외된다 (5부). X 를 누르면 그 자리에서 이유 칩이 펼쳐지고,
// 칩 밖을 누르면 제외하지 않고 닫힌다.
function dismissTender(tenderId, btn) {
    hsOpenReasonPicker(btn, { title: '왜 제외하나요? (하나 누르면 제외됩니다)', onPick: reasons => _dismissWithReasons(tenderId, btn, reasons) });
}

async function _dismissWithReasons(tenderId, btn, reasons) {
    const row = btn.closest('.hs-row');
    if (row) { row.style.transition = 'opacity .25s'; row.style.opacity = '0.35'; }
    try {
        const res = await fetch(`/api/tenders/${tenderId}/dismiss`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ reasons }) });
        if (!res.ok) throw new Error(res.status);
        dismissedIds.add(tenderId);
        setTimeout(() => { if (row) row.remove(); updateCounts(); }, 200);
    } catch (e) {
        if (row) row.style.opacity = '1';
        console.error(e);
    }
}

async function markSimilarGood(tenderId, btn) {
    const row = btn.closest('.hs-row');
    btn.disabled = true;
    try {
        const res = await fetch('/api/cases', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ tender_id: tenderId, source: 'similar' }),
        });
        if (!res.ok) throw new Error((await res.json()).error || res.status);
        if (similarData && similarData.items) similarData.items = similarData.items.filter(t => t.id !== tenderId);
        if (row) row.remove();
        updateCounts();
    } catch (e) {
        btn.disabled = false;
        alert('사례로 넣지 못했습니다: ' + e.message);
    }
}
