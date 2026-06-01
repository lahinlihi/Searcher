// 대시보드 JavaScript

// ── 공고 종류 배지 헬퍼 ─────────────────────────────────────────────────────
function getNoticeBadgesHtml(title) {
    const t = title || '';
    let html = '';
    if (/\[긴급공고\]|\(긴급공고\)|\[긴급\]|\(긴급\)/.test(t)) {
        html += '<span style="display:inline-flex;align-items:center;border-radius:9999px;padding:1px 8px;font-size:0.7rem;font-weight:700;background:#FEE2E2;color:#B91C1C;border:1px solid #FCA5A5;white-space:nowrap;margin-right:3px;">긴급</span>';
    }
    if (/\[재공고\]|\(재공고\)/.test(t)) {
        html += '<span style="display:inline-flex;align-items:center;border-radius:9999px;padding:1px 8px;font-size:0.7rem;font-weight:700;background:#FFEDD5;color:#C2410C;border:1px solid #FDBA74;white-space:nowrap;margin-right:3px;">재공고</span>';
    }
    return html;
}

function cleanNoticeTitle(title) {
    return (title || '')
        .replace(/\[긴급공고\]/g, '').replace(/\(긴급공고\)/g, '')
        .replace(/\[긴급\]/g, '').replace(/\(긴급\)/g, '')
        .replace(/\[재공고\]/g, '').replace(/\(재공고\)/g, '')
        .trim();
}

let agencyChart = null;
let dailyChart = null;
let includeKeywords = [];
let bookmarkedIds = new Set();
let dismissedIds = new Set();

// 섹션별 독립 정렬 상태
const dashSort = {
    pre:    { field: 'score', dir: 'desc' },
    urgent: { field: 'score', dir: 'desc' },
    recent: { field: 'score', dir: 'desc' },
};
let dashData = null;

// 캐러셀 페이지 상태 (섹션별)
const carouselPage = { pre: 0, urgent: 0, recent: 0 };
const CARDS_PER_PAGE = 8;

// 공통 정렬 함수
function sortItems(items, field, dir) {
    if (!items || !items.length) return items;
    return [...items].sort((a, b) => {
        const ag = t => (t.agency && t.agency.includes('조달청') && t.demand_agency)
            ? t.demand_agency : (t.demand_agency || t.agency || '');
        let va, vb;
        if (field === 'title')    { va = a.title || '';  vb = b.title || '';  return dir === 'asc' ? va.localeCompare(vb,'ko') : vb.localeCompare(va,'ko'); }
        if (field === 'agency')   { va = ag(a);           vb = ag(b);          return dir === 'asc' ? va.localeCompare(vb,'ko') : vb.localeCompare(va,'ko'); }
        if (field === 'announced'){ va = a.announced_date || ''; vb = b.announced_date || ''; return dir === 'asc' ? va.localeCompare(vb) : vb.localeCompare(va); }
        if (field === 'days')        { va = a.days_left        ?? 99999; vb = b.days_left        ?? 99999; }
        else if (field === 'budget') { va = a.estimated_price  ?? -1;    vb = b.estimated_price  ?? -1; }
        else if (field === 'score')  { va = a.relevance_score  ?? 0;     vb = b.relevance_score  ?? 0; }
        return dir === 'asc' ? va - vb : vb - va;
    });
}

// 섹션별 정렬 버튼 클릭
function setDashSort(section, field) {
    const s = dashSort[section];
    if (s.field === field) {
        s.dir = s.dir === 'asc' ? 'desc' : 'asc';
    } else {
        s.field = field;
        s.dir = (field === 'score' || field === 'budget') ? 'desc' : 'asc';
    }
    updateDashSortButtons(section);
    renderSection(section);
}

// 특정 섹션의 버튼 상태만 업데이트
function updateDashSortButtons(section) {
    const LABELS = { score:'점수', title:'사업명', agency:'기관', announced:'공고일', days:'마감일', budget:'금액' };
    const s = dashSort[section];
    document.querySelectorAll(`.dash-sort-btn[data-section="${section}"]`).forEach(btn => {
        const f = btn.dataset.sort;
        if (!LABELS[f]) return;
        const isActive = (s.field === f);
        btn.textContent = LABELS[f] + (isActive ? (s.dir === 'asc' ? ' ↑' : ' ↓') : '');
        btn.classList.toggle('active', isActive);
    });
    // 모바일 select/버튼 동기화
    const sel = document.getElementById(`dash-mobile-sort-${section}`);
    if (sel) sel.value = s.field;
    const dirBtn = document.getElementById(`dash-mobile-dir-${section}`);
    if (dirBtn) dirBtn.textContent = s.dir === 'asc' ? '↑' : '↓';
}

// 모바일 정렬 필드 변경
function onDashMobileSortChange(section, field) {
    const s = dashSort[section];
    s.field = field;
    s.dir = (field === 'score' || field === 'budget') ? 'desc' : 'asc';
    updateDashSortButtons(section);
    renderSection(section);
}

// 모바일 정렬 방향 토글
function toggleDashMobileSortDir(section) {
    const s = dashSort[section];
    s.dir = s.dir === 'asc' ? 'desc' : 'asc';
    updateDashSortButtons(section);
    renderSection(section);
}

// 특정 섹션만 다시 렌더링 (PC 카드 + 모바일 리스트 동시)
function renderSection(section) {
    if (!dashData) return;
    const { field, dir } = dashSort[section];
    let tenders;
    if (section === 'pre')         tenders = sortItems(dashData.pre_tenders,    field, dir);
    else if (section === 'urgent') tenders = sortItems(dashData.urgent_tenders, field, dir);
    else                           tenders = sortItems(dashData.recent_tenders, field, dir);
    tenders = tenders || [];
    // PC: 카드 캐러셀
    renderCarouselSection(section, tenders);
    // 모바일: 기존 리스트 뷰
    updateDashSortButtons(section);
    if (section === 'recent') {
        renderMobileTenderList(section, tenders);
    } else {
        renderMobileKeywordTenders(section, tenders);
    }
}

// 전체 섹션 렌더링
function renderDashboard() {
    if (!dashData) return;
    renderSection('pre');
    renderSection('urgent');
    renderSection('recent');
}

// 페이지 로드 시 실행
let _lastFetchTime = 0;

function _reloadDashboard() {
    Promise.all([loadBookmarkedIds(), loadDismissedIds()]).then(() => {
        loadDashboardData();
    });
}

document.addEventListener('DOMContentLoaded', function() {
    _reloadDashboard();
});

// 뒤로가기/앞으로가기(bfcache)로 복원될 때 재조회
window.addEventListener('pageshow', function(event) {
    if (event.persisted) {
        _reloadDashboard();
    }
});

// 다른 탭에서 돌아올 때 60초 이상 지났으면 재조회
document.addEventListener('visibilitychange', function() {
    if (!document.hidden && Date.now() - _lastFetchTime > 60_000) {
        _reloadDashboard();
    }
});

// 북마크 ID 목록 로드
async function loadBookmarkedIds() {
    try {
        const res = await fetch('/api/bookmarks/ids');
        const ids = await res.json();
        bookmarkedIds = new Set(ids);
    } catch (e) { /* 조용히 무시 */ }
}

// 관심없음 ID 목록 로드
async function loadDismissedIds() {
    try {
        const res = await fetch('/api/dismissed/ids');
        const ids = await res.json();
        dismissedIds = new Set(ids);
    } catch (e) { /* 조용히 무시 */ }
}

// 관심없음 버튼 HTML 생성
function dismissButton(tenderId) {
    return `<button onclick="dismissTender(${tenderId}, this)"
                class="text-xs text-gray-400 hover:text-red-500 transition-colors border border-gray-200 hover:border-red-300 rounded px-1.5 py-0.5 leading-none shrink-0"
                title="관심없음 — 대시보드에서 숨깁니다">✕</button>`;
}

// 관심없음 처리
async function dismissTender(tenderId, btn) {
    try {
        const card = btn.closest('.dash-tender-card') || btn.closest('.tender-item');
        // 즉시 시각적 피드백
        if (card) {
            card.style.transition = 'opacity 0.3s';
            card.style.opacity = '0.3';
        }
        const res = await fetch(`/api/tenders/${tenderId}/dismiss`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });
        if (res.ok) {
            dismissedIds.add(tenderId);
            if (card) {
                setTimeout(() => {
                    card.style.transition = 'all 0.3s';
                    card.style.maxHeight = card.scrollHeight + 'px';
                    card.offsetHeight; // reflow
                    card.style.maxHeight = '0';
                    card.style.opacity = '0';
                    card.style.marginBottom = '0';
                    card.style.paddingTop = '0';
                    card.style.paddingBottom = '0';
                    card.style.overflow = 'hidden';
                    setTimeout(() => card.remove(), 300);
                }, 100);
            }
        } else {
            if (card) card.style.opacity = '1';
        }
    } catch (e) {
        console.error(e);
    }
}

// 북마크 토글
async function toggleBookmark(tenderId, btn) {
    try {
        const res = await fetch('/api/bookmarks/toggle', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ tender_id: tenderId })
        });
        const data = await res.json();
        if (data.bookmarked) {
            bookmarkedIds.add(tenderId);
            btn.textContent = '★';
            btn.classList.replace('text-gray-300', 'text-yellow-400');
            btn.title = '관심공고 해제';
        } else {
            bookmarkedIds.delete(tenderId);
            btn.textContent = '☆';
            btn.classList.replace('text-yellow-400', 'text-gray-300');
            btn.title = '관심공고 추가';
        }
    } catch (e) { console.error(e); }
}

// 별 버튼 HTML 생성
function starButton(tenderId) {
    const isBookmarked = bookmarkedIds.has(tenderId);
    const cls = isBookmarked ? 'text-yellow-400' : 'text-gray-300';
    const icon = isBookmarked ? '★' : '☆';
    const title = isBookmarked ? '관심공고 해제' : '관심공고 추가';
    return `<button onclick="toggleBookmark(${tenderId}, this)"
                class="${cls} hover:text-yellow-400 transition-colors text-lg leading-none shrink-0"
                title="${title}">${icon}</button>`;
}

// 대시보드 데이터 로드
const _DASH_CACHE_KEY = 'dashboard_cache_v2';

// keepEmbed=true이면 _embedLoaded 플래그를 리셋하지 않음 (캐시 복원 시 사용)
function _applyDashboardData(data, resetPages, keepEmbed = false) {
    includeKeywords = data.include_keywords || [];
    renderActiveKeywords(includeKeywords);
    document.getElementById('new-today').textContent = data.summary.new_today + '건';
    document.getElementById('pre-announcement').textContent = data.summary.pre_announcement + '건';
    document.getElementById('deadline-soon').textContent = data.summary.deadline_soon + '건';
    document.getElementById('total-tenders').textContent = data.summary.total + '건';
    dashData = data;
    if (resetPages) {
        carouselPage.pre = 0;
        carouselPage.urgent = 0;
        carouselPage.recent = 0;
        if (!keepEmbed) {
            _embedLoaded.pre = false;
            _embedLoaded.urgent = false;
            _embedLoaded.recent = false;
        }
    }
    renderDashboard();
}

async function loadDashboardData() {
    // 캐시된 데이터가 있으면 즉시 표시 (끊김 방지)
    let hadCache = false;
    try {
        const cached = localStorage.getItem(_DASH_CACHE_KEY);
        if (cached) {
            hadCache = true;
            const cachedData = JSON.parse(cached);
            // 캐시에 저장된 embedLoaded 플래그 복원 → fetchEmbedScores 재호출 방지
            if (cachedData._embedLoaded) {
                Object.assign(_embedLoaded, cachedData._embedLoaded);
            }
            // keepEmbed=true: 복원된 _embedLoaded를 리셋하지 않음
            _applyDashboardData(cachedData, true, true);
        }
    } catch (_) {}

    // 백그라운드에서 최신 데이터 요청
    try {
        const response = await fetch('/api/dashboard');
        const data = await response.json();

        if (data.error) {
            console.error('Error:', data.error);
            return;
        }

        _lastFetchTime = Date.now();
        // 이미 임베딩 점수가 계산된 섹션은 새 데이터에도 병합 (점수 깜빡임 방지)
        _mergeEmbedScores(data);
        try { localStorage.setItem(_DASH_CACHE_KEY, JSON.stringify(data)); } catch (_) {}
        _applyDashboardData(data, !hadCache);

    } catch (error) {
        console.error('Failed to load dashboard data:', error);
    }
}

// 통계 데이터 로드
async function loadStats() {
    try {
        const response = await fetch('/api/stats');
        const data = await response.json();

        if (data.error) {
            console.error('Error:', data.error);
            return;
        }

        // 수집 채널별 차트
        renderSourceChart(data.source_stats);

        // 일별 차트
        renderDailyChart(data.daily_stats);

    } catch (error) {
        console.error('Failed to load stats:', error);
    }
}

// 키워드 매칭 개수 계산 및 강조 표시
function highlightKeywordsInTitle(title, keywords) {
    if (!keywords || keywords.length === 0 || !title) {
        return { highlightedTitle: title, matchCount: 0 };
    }

    let matchCount = 0;
    let highlightedTitle = title;
    const titleLower = title.toLowerCase();

    // 각 키워드를 찾아서 매칭 개수 계산
    keywords.forEach(keyword => {
        if (keyword && titleLower.includes(keyword.toLowerCase())) {
            matchCount++;
            // 대소문자 구분 없이 키워드를 찾아서 강조 표시
            const regex = new RegExp(`(${keyword})`, 'gi');
            highlightedTitle = highlightedTitle.replace(regex, '<mark class="keyword-highlight">$1</mark>');
        }
    });

    return { highlightedTitle, matchCount };
}

// 적합도 점수 배지 생성
function buildScoreBadge(score, matchedKeywords, businessType, breakdown) {
    let bg;
    if (score >= 70)      bg = 'bg-green-100 text-green-800 border border-green-300';
    else if (score >= 40) bg = 'bg-yellow-100 text-yellow-800 border border-yellow-300';
    else                  bg = 'bg-gray-100 text-gray-600 border border-gray-300';
    const displayScore = score.toFixed(1);
    let tooltip;
    if (breakdown) {
        tooltip = `${displayScore}점 = 키워드 ${breakdown.keyword.toFixed(1)} + 사업유형 ${breakdown.type.toFixed(1)} + 기관가중치 ${breakdown.agency.toFixed(1)}`;
    } else {
        const typeText = businessType && businessType !== '기타' ? ` · ${businessType}` : '';
        tooltip = `적합도 점수: ${displayScore}점${typeText}`;
    }
    return `<span class="inline-flex items-center text-xs font-bold px-2 py-0.5 rounded ${bg}"
                  title="${tooltip}">
        ${displayScore}
    </span>`;
}

// ── 모바일 리스트 렌더러 (기존 디자인 유지) ───────────────────────────────

function _mobileAgencyName(tender) {
    if (tender.source_site === '중소벤처 24') return tender.demand_agency || tender.agency || '-';
    if (tender.agency && tender.agency.includes('조달청') && tender.demand_agency) return tender.demand_agency;
    return tender.agency || '-';
}

function _mobileDeadline(daysLeft) {
    let cls = 'tender-deadline-normal';
    if (daysLeft !== null && daysLeft <= 2) cls = 'tender-deadline-urgent';
    else if (daysLeft !== null && daysLeft <= 5) cls = 'tender-deadline-soon';
    return { cls, text: daysLeft !== null ? `D-${daysLeft}` : '-' };
}

function renderMobileKeywordTenders(section, tenders) {
    const container = document.getElementById(`${section}-tenders-list-mobile`);
    if (!container) return;

    if (!includeKeywords || includeKeywords.length === 0) {
        container.innerHTML = '<p class="text-gray-500 text-sm">관심 키워드를 <a href="/filters" class="text-blue-600 hover:underline">설정</a>하면 매칭 공고를 표시합니다.</p>';
        return;
    }
    if (!tenders || tenders.length === 0) {
        container.innerHTML = '<p class="text-gray-500 text-sm">매칭 공고가 없습니다.</p>';
        return;
    }

    container.innerHTML = tenders.map(tender => {
        const { highlightedTitle } = highlightKeywordsInTitle(cleanNoticeTitle(tender.title), includeKeywords);
        const noticeBadges = getNoticeBadgesHtml(tender.title);
        const score = tender.relevance_score ?? 0;
        const scoreBadge = buildScoreBadge(score, tender.matched_keywords || [], tender.business_type || '기타', tender.score_breakdown || null);
        const bizType = (tender.business_type && tender.business_type !== '기타') ? tender.business_type : '미분류';
        const { cls: deadlineClass, text: deadlineText } = _mobileDeadline(tender.days_left);
        const price = tender.estimated_price ? formatPrice(tender.estimated_price) : '미정';
        const agencyName = _mobileAgencyName(tender);
        return `
            <div class="tender-item section-${section}">
                <div class="flex justify-between items-start mb-1">
                    <div class="flex flex-wrap items-center gap-1">
                        ${scoreBadge}
                        <span class="mobile-type-badge">유형: ${bizType}</span>
                    </div>
                    <div class="flex items-center gap-2 ml-2 shrink-0">
                        <span class="font-semibold ${deadlineClass}">${deadlineText}</span>
                        ${starButton(tender.id)}${dismissButton(tender.id)}
                    </div>
                </div>
                <h4 class="font-medium text-gray-900 mt-1 line-clamp-2">
                    <a href="/tender/${tender.id}" target="_blank" rel="noopener" class="text-gray-900 hover:text-blue-600 hover:underline">${noticeBadges}${highlightedTitle}</a>
                </h4>
                <div class="flex flex-col gap-1 mt-2">
                    <span class="text-sm text-gray-700 font-bold truncate">${agencyName}</span>
                    <span class="text-sm text-blue-600 font-medium">${price}</span>
                </div>
            </div>`;
    }).join('');
}

function renderMobileTenderList(section, tenders) {
    const container = document.getElementById(`${section}-tenders-list-mobile`);
    if (!container) return;

    if (!tenders || tenders.length === 0) {
        container.innerHTML = '<p class="text-gray-500 text-sm">공고가 없습니다.</p>';
        return;
    }

    container.innerHTML = tenders.map(tender => {
        const { cls: deadlineClass, text: deadlineText } = _mobileDeadline(tender.days_left);
        const price = tender.estimated_price ? formatPrice(tender.estimated_price) : '미정';
        const { highlightedTitle } = highlightKeywordsInTitle(cleanNoticeTitle(tender.title), includeKeywords);
        const noticeBadges = getNoticeBadgesHtml(tender.title);
        const score = tender.relevance_score ?? 0;
        const scoreBadge = score > 0 ? buildScoreBadge(score, [], tender.business_type || '기타', tender.score_breakdown || null) : '';
        const bizType = (tender.business_type && tender.business_type !== '기타') ? tender.business_type : '미분류';
        const agencyName = _mobileAgencyName(tender);
        return `
            <div class="tender-item section-${section}">
                <div class="flex justify-between items-start mb-1">
                    <div class="flex flex-wrap items-center gap-1">
                        ${scoreBadge}
                        <span class="mobile-type-badge">유형: ${bizType}</span>
                    </div>
                    <div class="flex items-center gap-2 ml-2 shrink-0">
                        <span class="font-semibold ${deadlineClass}">${deadlineText}</span>
                        ${starButton(tender.id)}
                    </div>
                </div>
                <h4 class="font-medium text-gray-900 mt-1 line-clamp-2">
                    <a href="/tender/${tender.id}" target="_blank" rel="noopener" class="text-gray-900 hover:text-blue-600 hover:underline">${noticeBadges}${highlightedTitle}</a>
                </h4>
                <div class="flex flex-col gap-1 mt-2">
                    <span class="text-sm text-gray-700 font-bold truncate">${agencyName}</span>
                    <span class="text-sm text-blue-600 font-medium">${price}</span>
                </div>
            </div>`;
    }).join('');
}

// 섹션별 임베딩 점수 로딩 완료 여부 추적
const _embedLoaded = { pre: false, urgent: false, recent: false };

// 기존 dashData의 임베딩 점수를 새 API 데이터에 병합 (API 응답 시 점수 깜빡임 방지)
function _mergeEmbedScores(newData) {
    if (!dashData) return;
    const keyMap = { pre: 'pre_tenders', urgent: 'urgent_tenders', recent: 'recent_tenders' };
    for (const [section, key] of Object.entries(keyMap)) {
        if (!_embedLoaded[section] || !dashData[key] || !newData[key]) continue;
        const scoreMap = {};
        for (const t of dashData[key]) scoreMap[t.id] = t.relevance_score;
        for (const t of newData[key]) {
            if (scoreMap[t.id] != null) t.relevance_score = scoreMap[t.id];
        }
        newData[key].sort((a, b) => (b.relevance_score ?? 0) - (a.relevance_score ?? 0));
    }
}

// ── 캐러셀 섹션 렌더링 ─────────────────────────────────────────────────────
function renderCarouselSection(section, tenders, skipEmbed = false) {
    const page = carouselPage[section];
    const totalPages = Math.max(1, Math.ceil(tenders.length / CARDS_PER_PAGE));
    const start = page * CARDS_PER_PAGE;
    const pageItems = tenders.slice(start, start + CARDS_PER_PAGE);

    const container = document.getElementById(`${section}-tenders-list`);
    if (!container) return;

    if (tenders.length === 0) {
        const msg = (section === 'pre' || section === 'urgent') && (!includeKeywords || includeKeywords.length === 0)
            ? '관심 키워드를 <a href="/filters" class="text-blue-600 hover:underline">설정</a>하면 매칭 공고를 표시합니다.'
            : '공고가 없습니다.';
        container.innerHTML = `<p class="col-span-4 text-gray-500 text-sm py-4">${msg}</p>`;
    } else {
        container.innerHTML = pageItems.map(t => renderTenderCard(t)).join('');
        // 섹션 첫 진입 시에만 전체 24건 임베딩 → 정렬 후 재렌더
        if (!skipEmbed && !_embedLoaded[section]) {
            fetchEmbedScores(tenders.map(t => t.id), section);
        }
    }

    const prevBtn   = document.getElementById(`${section}-prev`);
    const nextBtn   = document.getElementById(`${section}-next`);
    const indicator = document.getElementById(`${section}-page-indicator`);
    if (prevBtn)   prevBtn.disabled   = (page === 0);
    if (nextBtn)   nextBtn.disabled   = (page >= totalPages - 1);
    if (indicator) indicator.textContent = `${page + 1} / ${totalPages}`;
}

// 캐러셀 이전/다음 페이지
function prevPage(section) {
    if (carouselPage[section] > 0) {
        carouselPage[section]--;
        renderSection(section);
    }
}

function nextPage(section) {
    const sectionData = {
        pre: dashData?.pre_tenders,
        urgent: dashData?.urgent_tenders,
        recent: dashData?.recent_tenders,
    };
    const tenders = sectionData[section] || [];
    const totalPages = Math.max(1, Math.ceil(tenders.length / CARDS_PER_PAGE));
    if (carouselPage[section] < totalPages - 1) {
        carouselPage[section]++;
        renderSection(section);
    }
}

// 임베딩 점수 on-demand 로딩 — 섹션 전체(최대 24건) 가져와서 재정렬
const _sectionKey = { pre: 'pre_tenders', urgent: 'urgent_tenders', recent: 'recent_tenders' };

async function fetchEmbedScores(tenderIds, section) {
    if (!tenderIds || tenderIds.length === 0) return;
    try {
        const resp = await fetch('/api/embed-scores', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ tender_ids: tenderIds })
        });
        if (!resp.ok) return;
        const data = await resp.json();
        const scores = data.scores || {};

        // dashData의 해당 섹션 점수 업데이트
        const key = _sectionKey[section];
        if (key && dashData?.[key]) {
            for (const tender of dashData[key]) {
                const info = scores[String(tender.id)];
                if (info) tender.relevance_score = info.score;
            }
            // 임베딩 점수 기준으로 재정렬
            dashData[key].sort((a, b) => (b.relevance_score ?? 0) - (a.relevance_score ?? 0));
            _embedLoaded[section] = true;
            // 임베딩 점수 + embedLoaded 플래그를 캐시에 저장 (다음 방문 시 재계산 방지)
            dashData._embedLoaded = { ..._embedLoaded };
            try { localStorage.setItem(_DASH_CACHE_KEY, JSON.stringify(dashData)); } catch (_) {}
            // 현재 페이지 재렌더 (embed 재호출 없이)
            renderCarouselSection(section, dashData[key], true);
        }
    } catch (_) { /* 실패 시 규칙 점수 순서 그대로 유지 */ }
}

// 공고 카드 렌더링
function renderTenderCard(tender) {
    const cleanedTitle = cleanNoticeTitle(tender.title);
    const { highlightedTitle } = highlightKeywordsInTitle(cleanedTitle, includeKeywords);
    const score = tender.relevance_score ?? 0;

    // 점수 배지 색상
    let scoreCls;
    if (score >= 70)      scoreCls = 'background:#D1FAE5;color:#065F46;';
    else if (score >= 40) scoreCls = 'background:#FEF3C7;color:#92400E;';
    else                  scoreCls = 'background:#F3F4F6;color:#6B7280;';

    // 금액
    const price = tender.estimated_price ? formatPrice(tender.estimated_price) : '미정';

    // 기관명
    let agencyName;
    if (tender.source_site === '중소벤처 24') {
        agencyName = tender.demand_agency || tender.agency || '-';
    } else if (tender.agency && tender.agency.includes('조달청') && tender.demand_agency) {
        agencyName = tender.demand_agency;
    } else {
        agencyName = tender.agency || '-';
    }

    // 마감일
    const daysLeft = tender.days_left;
    let dlColor = 'color:#16a34a;';
    if (daysLeft !== null && daysLeft <= 2)      dlColor = 'color:#dc2626;';
    else if (daysLeft !== null && daysLeft <= 5) dlColor = 'color:#ea580c;';
    const deadlineText = daysLeft !== null ? `D-${daysLeft}` : '-';

    // 유형
    const bizType = (tender.business_type && tender.business_type !== '기타') ? tender.business_type : '미분류';

    // 공고 앞 인라인 특이사항 배지
    const t = tender.title || '';
    let inlineBadges = '';
    if (/\[긴급공고\]|\(긴급공고\)|\[긴급\]|\(긴급\)/.test(t))
        inlineBadges += '<span class="badge-inline-urgent">긴급</span>';
    if (/\[재공고\]|\(재공고\)/.test(t))
        inlineBadges += '<span class="badge-inline-reopen">재공고</span>';
    if (tender.bid_method && /수의계약/.test(tender.bid_method))
        inlineBadges += '<span class="badge-inline-private">수의계약</span>';

    return `
        <div class="dash-tender-card">
            <div class="dc-top">
                <span class="dc-score" id="score-${tender.id}" style="${scoreCls}">${score.toFixed(1)}</span>
                <span class="dc-type">유형: ${bizType}</span>
                <div class="dc-actions">
                    ${starButton(tender.id)}
                    ${dismissButton(tender.id)}
                </div>
            </div>
            <div class="dc-title">
                <a href="/tender/${tender.id}" target="_blank" rel="noopener" class="dc-title-link">${inlineBadges}${highlightedTitle}</a>
            </div>
            <div class="dc-price">${price}</div>
            <div class="dc-footer">
                <span class="dc-agency">${agencyName}</span>
                <span class="dc-deadline" style="${dlColor}">${deadlineText}</span>
            </div>
        </div>
    `;
}

// 키워드 매칭 공고 전용 렌더링 (하위 호환 — 현재 미사용)
function renderKeywordTenders(elementId, tenders, keywords) {
    const container = document.getElementById(elementId);
    if (!container) return;

    if (!keywords || keywords.length === 0) {
        container.innerHTML = '<p class="text-gray-500 text-sm">관심 키워드를 <a href="/settings" class="text-blue-600 hover:underline">설정</a>하면 매칭 공고를 표시합니다.</p>';
        return;
    }

    if (!tenders || tenders.length === 0) {
        container.innerHTML = '<p class="text-gray-500 text-sm">최근 7일 내 키워드 매칭 공고가 없습니다.</p>';
        return;
    }

    const html = tenders.map(tender => {
        const { highlightedTitle } = highlightKeywordsInTitle(cleanNoticeTitle(tender.title), keywords);
        const noticeBadges = getNoticeBadgesHtml(tender.title);
        const matchedKeywords = tender.matched_keywords || [];
        const score = tender.relevance_score ?? 0;
        const businessType = tender.business_type || '기타';

        const scoreBadge = buildScoreBadge(score, matchedKeywords, businessType, tender.score_breakdown || null);

        const statusBadge = tender.status === '사전규격'
            ? '<span class="tender-status-badge tender-status-pre">사전</span>'
            : '<span class="tender-status-badge tender-status-normal">일반</span>';

        const daysLeft = tender.days_left;
        let deadlineClass = 'tender-deadline-normal';
        if (daysLeft !== null && daysLeft <= 2) deadlineClass = 'tender-deadline-urgent';
        else if (daysLeft !== null && daysLeft <= 5) deadlineClass = 'tender-deadline-soon';
        const deadlineText = daysLeft !== null ? `D-${daysLeft}` : '-';

        const price = tender.estimated_price ? formatPrice(tender.estimated_price) : '미정';
        const announcedDate = tender.announced_date
            ? tender.announced_date.substring(0, 10)
            : '';

        let agencyName;
        if (tender.source_site === '중소벤처 24') {
            agencyName = tender.demand_agency || tender.agency;
        } else if (tender.agency && tender.agency.includes('조달청') && tender.demand_agency) {
            agencyName = tender.demand_agency;
        } else {
            agencyName = tender.agency;
        }

        return `
            <div class="tender-item">
                <div class="flex justify-between items-start mb-1">
                    <div class="flex flex-wrap items-center gap-1">
                        ${statusBadge}
                        ${scoreBadge}
                    </div>
                    <div class="flex items-center gap-2 ml-2 shrink-0">
                        <span class="font-semibold ${deadlineClass}">${deadlineText}</span>
                        ${starButton(tender.id)}
                        ${dismissButton(tender.id)}
                    </div>
                </div>
                <h4 class="font-medium text-gray-900 mt-1 line-clamp-2 sm:line-clamp-1 sm:text-sm">
                    <a href="/tender/${tender.id}" target="_blank" rel="noopener" class="text-gray-900 hover:text-blue-600 hover:underline">
                        ${noticeBadges}${highlightedTitle}
                    </a>
                </h4>
                <div class="sm:hidden flex flex-col gap-1 mt-2">
                    <span class="text-sm text-gray-700 font-bold truncate">${agencyName}</span>
                    <span class="text-sm text-blue-600 font-medium">${price}</span>
                </div>
                <div class="hidden sm:flex items-center gap-3 mt-1.5 text-sm flex-wrap">
                    <span class="font-medium text-gray-800 truncate">${agencyName}</span>
                    <span class="font-medium text-blue-600">${price}</span>
                    <a href="/tender/${tender.id}" target="_blank" rel="noopener" class="text-blue-500 hover:underline">상세보기 →</a>
                    ${tender.url ? `<a href="${tender.url}" target="_blank" class="text-gray-500 hover:underline">원본 공고 →</a>` : ''}
                </div>
            </div>
        `;
    }).join('');

    container.innerHTML = html;
}

// 공고 목록 렌더링
function renderTenderList(elementId, tenders) {
    const container = document.getElementById(elementId);

    if (!tenders || tenders.length === 0) {
        container.innerHTML = '<p class="text-gray-500 text-sm">공고가 없습니다.</p>';
        return;
    }

    const html = tenders.map(tender => {
        const statusBadge = tender.status === '사전규격'
            ? '<span class="tender-status-badge tender-status-pre">사전</span>'
            : '<span class="tender-status-badge tender-status-normal">일반</span>';

        const daysLeft = tender.days_left;
        let deadlineClass = 'tender-deadline-normal';
        let deadlineText = `D-${daysLeft}`;

        if (daysLeft <= 2) {
            deadlineClass = 'tender-deadline-urgent';
        } else if (daysLeft <= 5) {
            deadlineClass = 'tender-deadline-soon';
        }

        const price = tender.estimated_price
            ? formatPrice(tender.estimated_price)
            : '미정';

        const { highlightedTitle, matchCount } = highlightKeywordsInTitle(cleanNoticeTitle(tender.title), includeKeywords);
        const noticeBadges = getNoticeBadgesHtml(tender.title);
        const matchedKeywords = tender.matched_keywords || [];
        const score = tender.relevance_score ?? null;
        const businessType = tender.business_type || '기타';
        let keywordBadge = '';
        if (matchedKeywords.length > 0) {
            const scorePart = score !== null ? buildScoreBadge(score, [], businessType, tender.score_breakdown || null) : '';
            keywordBadge = `<span class="inline-flex items-center flex-wrap gap-1">
                <span class="keyword-match-badge">키워드: ${matchedKeywords.join(', ')}</span>
                ${scorePart}
            </span>`;
        }

        let agencyName;
        if (tender.source_site === '중소벤처 24') {
            agencyName = tender.demand_agency || tender.agency;
        } else if (tender.agency && tender.agency.includes('조달청') && tender.demand_agency) {
            agencyName = tender.demand_agency;
        } else {
            agencyName = tender.agency;
        }

        return `
            <div class="tender-item">
                <div class="flex justify-between items-start mb-1">
                    <div class="flex flex-wrap items-center gap-1">
                        ${statusBadge}
                        ${keywordBadge}
                    </div>
                    <div class="flex items-center gap-2 ml-2 shrink-0">
                        <span class="font-semibold ${deadlineClass}">${deadlineText}</span>
                        ${starButton(tender.id)}
                    </div>
                </div>
                <h4 class="font-medium text-gray-900 mt-1 line-clamp-2 sm:line-clamp-1 sm:text-sm">
                    <a href="/tender/${tender.id}" target="_blank" rel="noopener" class="text-gray-900 hover:text-blue-600 hover:underline">
                        ${noticeBadges}${highlightedTitle}
                    </a>
                </h4>
                <div class="sm:hidden flex flex-col gap-1 mt-2">
                    <span class="text-sm text-gray-700 font-bold truncate">${agencyName}</span>
                    <span class="text-sm text-blue-600 font-medium">${price}</span>
                </div>
                <div class="hidden sm:flex items-center gap-3 mt-1.5 text-sm flex-wrap">
                    <span class="font-medium text-gray-800 truncate">${agencyName}</span>
                    <span class="font-medium text-blue-600">${price}</span>
                    <a href="/tender/${tender.id}" target="_blank" rel="noopener" class="text-blue-500 hover:underline">상세보기 →</a>
                    ${tender.url ? `<a href="${tender.url}" target="_blank" class="text-gray-500 hover:underline">원본 공고 →</a>` : ''}
                </div>
            </div>
        `;
    }).join('');

    container.innerHTML = html;
}

// 수집 채널별 차트 렌더링
function renderSourceChart(stats) {
    if (!stats || stats.length === 0) return;

    const ctx = document.getElementById('source-chart').getContext('2d');

    // 기존 차트 파괴
    if (agencyChart) {
        agencyChart.destroy();
    }

    agencyChart = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: stats.map(s => s.source),
            datasets: [{
                label: '공고 수',
                data: stats.map(s => s.count),
                backgroundColor: '#3B82F6',
                borderColor: '#2563EB',
                borderWidth: 1
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: true,
            plugins: {
                legend: {
                    display: false
                }
            },
            scales: {
                y: {
                    beginAtZero: true,
                    ticks: {
                        stepSize: 1
                    }
                }
            }
        }
    });
}

// 일별 차트 렌더링
function renderDailyChart(stats) {
    if (!stats || stats.length === 0) return;

    const ctx = document.getElementById('daily-chart').getContext('2d');

    // 기존 차트 파괴
    if (dailyChart) {
        dailyChart.destroy();
    }

    dailyChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: stats.map(s => formatDate(s.date)),
            datasets: [{
                label: '공고 수',
                data: stats.map(s => s.count),
                borderColor: '#10B981',
                backgroundColor: 'rgba(16, 185, 129, 0.1)',
                tension: 0.4,
                fill: true
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: true,
            plugins: {
                legend: {
                    display: false
                }
            },
            scales: {
                y: {
                    beginAtZero: true,
                    ticks: {
                        stepSize: 1
                    }
                }
            }
        }
    });
}

// 날짜 포맷 (YYYY-MM-DD -> MM/DD)
function formatDate(dateStr) {
    const date = new Date(dateStr);
    return `${date.getMonth() + 1}/${date.getDate()}`;
}

// 가격 포맷 (원 단위)
function formatPrice(price) {
    if (price >= 100000000) {
        return (price / 100000000).toFixed(1) + '억원';
    } else if (price >= 10000000) {
        return (price / 10000000).toFixed(1) + '천만원';
    } else if (price >= 10000) {
        return (price / 10000).toFixed(0) + '만원';
    } else {
        return price.toLocaleString() + '원';
    }
}

// 대시보드 새로고침
function refreshDashboard() {
    loadDashboardData();
    loadStats();
}

// 관심 키워드 렌더링 (PC: 탭 스트립 / 모바일: 버블 카드)
function renderActiveKeywords(keywords) {
    // PC: 키워드 한 줄 표시 (비링크 span, 넘치면 말줄임표)
    const pcContainer = document.getElementById('active-keywords');
    if (pcContainer) {
        if (!keywords || keywords.length === 0) {
            pcContainer.innerHTML = '<span class="text-xs text-gray-400">설정된 키워드가 없습니다.</span>';
            return;
        }
        const TAG = 'keyword-tab';
        // 1단계: 전부 nowrap 렌더 후 너비 측정
        pcContainer.innerHTML = keywords.map((kw, i) =>
            `<span data-i="${i}" class="${TAG}" style="cursor:default;flex-shrink:0;">${kw}</span>`
        ).join('');
        requestAnimationFrame(() => {
            const cRight = pcContainer.getBoundingClientRect().right;
            const spans = pcContainer.querySelectorAll('span[data-i]');
            let cut = spans.length;
            for (let i = 0; i < spans.length; i++) {
                if (spans[i].getBoundingClientRect().right > cRight + 2) { cut = i; break; }
            }
            const SPAN = kw => `<span class="${TAG}" style="cursor:default;flex-shrink:0;">${kw}</span>`;
            if (cut >= keywords.length) {
                pcContainer.innerHTML = keywords.map(SPAN).join('');
            } else {
                const show = Math.max(1, cut - 1);
                const rest = keywords.length - show;
                pcContainer.innerHTML =
                    keywords.slice(0, show).map(SPAN).join('') +
                    `<span class="${TAG}" style="cursor:default;flex-shrink:0;background:#F3F4F6;color:#9CA3AF;border-color:#E5E7EB;">... +${rest}개</span>`;
            }
        });
    }

    // 모바일: 한 줄 키워드 (넘치면 +N개 표시, 전체 클릭 → /filters)
    const mobileContainer = document.getElementById('active-keywords-mobile');
    if (mobileContainer) {
        const TAG = 'text-xs px-2 py-0.5 rounded-full bg-blue-100 text-blue-800 shrink-0 whitespace-nowrap';
        if (!keywords || keywords.length === 0) {
            mobileContainer.innerHTML = '<span class="text-xs text-blue-700">키워드 없음 — 추가하기</span>';
            return;
        }
        // 1단계: 전부 nowrap으로 렌더해서 너비 측정
        mobileContainer.style.cssText = 'display:flex;flex-wrap:nowrap;overflow:hidden;gap:6px;';
        mobileContainer.innerHTML = keywords.map((kw, i) =>
            `<span data-i="${i}" class="${TAG}">${kw}</span>`
        ).join('');
        requestAnimationFrame(() => {
            const cRight = mobileContainer.getBoundingClientRect().right;
            const spans = mobileContainer.querySelectorAll('span[data-i]');
            let cut = spans.length;
            for (let i = 0; i < spans.length; i++) {
                if (spans[i].getBoundingClientRect().right > cRight + 2) { cut = i; break; }
            }
            mobileContainer.style.cssText = 'display:flex;flex-wrap:nowrap;overflow:hidden;gap:6px;align-items:center;';
            if (cut >= keywords.length) {
                mobileContainer.innerHTML = keywords.map(kw => `<span class="${TAG}">${kw}</span>`).join('');
            } else {
                const show = Math.max(1, cut - 1);
                const rest = keywords.length - show;
                mobileContainer.innerHTML =
                    keywords.slice(0, show).map(kw => `<span class="${TAG}">${kw}</span>`).join('') +
                    `<span class="text-xs px-2 py-0.5 rounded-full bg-blue-200 text-blue-700 shrink-0 whitespace-nowrap">+${rest}개</span>`;
            }
        });
    }
}
