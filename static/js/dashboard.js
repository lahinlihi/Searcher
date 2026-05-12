// 대시보드 JavaScript

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

// 공통 정렬 함수
function sortItems(items, field, dir) {
    if (!items || !items.length) return items;
    return [...items].sort((a, b) => {
        const ag = t => (t.agency && t.agency.includes('조달청') && t.demand_agency)
            ? t.demand_agency : (t.demand_agency || t.agency || '');
        let va, vb;
        if (field === 'title')  { va = a.title || '';  vb = b.title || '';  return dir === 'asc' ? va.localeCompare(vb,'ko') : vb.localeCompare(va,'ko'); }
        if (field === 'agency') { va = ag(a);           vb = ag(b);          return dir === 'asc' ? va.localeCompare(vb,'ko') : vb.localeCompare(va,'ko'); }
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
    const LABELS = { score:'점수', title:'사업명', agency:'기관', days:'마감일', budget:'금액' };
    const s = dashSort[section];
    document.querySelectorAll(`.dash-sort-btn[data-section="${section}"]`).forEach(btn => {
        const f = btn.dataset.sort;
        if (!LABELS[f]) return;
        const isActive = (s.field === f);
        btn.textContent = LABELS[f] + (isActive ? (s.dir === 'asc' ? ' ↑' : ' ↓') : '');
        btn.classList.toggle('active', isActive);
    });
}

// 특정 섹션만 다시 렌더링
function renderSection(section) {
    if (!dashData) return;
    const { field, dir } = dashSort[section];
    if (section === 'pre') {
        renderKeywordTenders('pre-tenders-list',    sortItems(dashData.pre_tenders,    field, dir), includeKeywords);
    } else if (section === 'urgent') {
        renderKeywordTenders('urgent-tenders-list', sortItems(dashData.urgent_tenders, field, dir), includeKeywords);
    } else if (section === 'recent') {
        renderTenderList('recent-tenders-list',     sortItems(dashData.recent_tenders, field, dir));
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
        loadStats();
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
        const card = btn.closest('.tender-item');
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
async function loadDashboardData() {
    try {
        const response = await fetch('/api/dashboard');
        const data = await response.json();

        if (data.error) {
            console.error('Error:', data.error);
            return;
        }

        // 포함 키워드 저장 및 표시
        includeKeywords = data.include_keywords || [];
        renderActiveKeywords(includeKeywords);

        // 요약 통계 업데이트
        document.getElementById('new-today').textContent = data.summary.new_today + '건';
        document.getElementById('pre-announcement').textContent = data.summary.pre_announcement + '건';
        document.getElementById('deadline-soon').textContent = data.summary.deadline_soon + '건';
        document.getElementById('total-tenders').textContent = data.summary.total + '건';

        // 데이터 저장 후 섹션별 정렬 초기화 및 렌더링
        _lastFetchTime = Date.now();
        dashData = data;
        updateDashSortButtons('pre');
        updateDashSortButtons('urgent');
        updateDashSortButtons('recent');
        renderDashboard();

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
function buildScoreBadge(score, matchedKeywords, businessType) {
    let bg, label;
    if (score >= 70) {
        bg = 'bg-green-100 text-green-800 border border-green-300';
        label = '높음';
    } else if (score >= 40) {
        bg = 'bg-yellow-100 text-yellow-800 border border-yellow-300';
        label = '보통';
    } else {
        bg = 'bg-gray-100 text-gray-600 border border-gray-300';
        label = '낮음';
    }
    const typeText = businessType && businessType !== '기타' ? ` · ${businessType}` : '';
    // 소수점이 있을 때만 1자리 표시 (동점 방지용 소수점 점수 반영)
    const displayScore = Number.isInteger(score) ? score : score.toFixed(1);
    return `<span class="inline-flex items-center gap-1 text-xs font-semibold px-2 py-0.5 rounded ${bg}"
                  title="적합도 점수: 키워드 매칭(45점) + 사업유형(45점) + 긴급도·규모(10점)">
        <span class="font-bold">${displayScore}점</span><span class="font-normal opacity-70">${label}${typeText}</span>
    </span>`;
}

// 키워드 매칭 공고 전용 렌더링 (적합도 점수 표시)
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
        const { highlightedTitle } = highlightKeywordsInTitle(tender.title, keywords);
        const matchedKeywords = tender.matched_keywords || [];
        const score = tender.relevance_score ?? 0;
        const businessType = tender.business_type || '기타';

        const scoreBadge = buildScoreBadge(score, matchedKeywords, businessType);

        const statusBadge = tender.status === '사전규격'
            ? '<span class="tender-status-badge tender-status-pre">사전규격</span>'
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
                <h4 class="font-medium text-gray-900 mt-1">
                    <a href="/tender/${tender.id}" class="text-gray-900 hover:text-blue-600 hover:underline">
                        ${highlightedTitle}
                    </a>
                </h4>
                <div class="flex justify-between items-center text-sm text-gray-600 mt-1">
                    <div class="flex items-center gap-2">
                        <span>${(tender.agency && tender.agency.includes('조달청') && tender.demand_agency) ? `수요: ${tender.demand_agency}` : `발주: ${tender.agency}`}</span>
                        <span class="text-xs px-2 py-0.5 bg-gray-100 rounded">${tender.source_site}</span>
                        ${announcedDate ? `<span class="text-xs text-gray-400">등록: ${announcedDate}</span>` : ''}
                    </div>
                    <span>금액: ${price}</span>
                </div>
                <div class="flex gap-3 mt-1 text-sm">
                    <a href="/tender/${tender.id}" class="text-blue-600 hover:underline">상세보기 →</a>
                    ${tender.url ? `<a href="${tender.url}" target="_blank" class="text-gray-600 hover:underline">원본 공고 →</a>` : ''}
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
            ? '<span class="tender-status-badge tender-status-pre">사전규격</span>'
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

        // 키워드 강조 및 매칭 개수 계산
        const { highlightedTitle, matchCount } = highlightKeywordsInTitle(tender.title, includeKeywords);

        // 매칭된 키워드 목록 (서버에서 계산된 값 사용)
        const matchedKeywords = tender.matched_keywords || [];
        const score = tender.relevance_score ?? null;

        // 키워드 배지 + 적합도 점수 (매칭이 있을 때만 표시)
        const businessType = tender.business_type || '기타';
        let keywordBadge = '';
        if (matchedKeywords.length > 0) {
            const scorePart = score !== null ? buildScoreBadge(score, [], businessType) : '';
            keywordBadge = `<span class="inline-flex items-center flex-wrap gap-1">
                <span class="keyword-match-badge">키워드: ${matchedKeywords.join(', ')}</span>
                ${scorePart}
            </span>`;
        }

        return `
            <div class="tender-item">
                <div class="flex justify-between items-start mb-2">
                    <div class="flex-1">
                        ${statusBadge}
                        ${keywordBadge}
                        <h4 class="font-medium text-gray-900 mt-1">
                            <a href="/tender/${tender.id}" class="text-gray-900 hover:text-blue-600 hover:underline">
                                ${highlightedTitle}
                            </a>
                        </h4>
                    </div>
                    <div class="flex items-center gap-2 ml-2 shrink-0">
                        <span class="font-semibold ${deadlineClass}">${deadlineText}</span>
                        ${starButton(tender.id)}
                    </div>
                </div>
                <div class="flex justify-between items-center text-sm text-gray-600">
                    <div class="flex items-center gap-2">
                        <span>${(tender.agency && tender.agency.includes('조달청') && tender.demand_agency) ? `수요: ${tender.demand_agency}` : `발주: ${tender.agency}`}</span>
                        <span class="text-xs px-2 py-0.5 bg-gray-100 rounded">${tender.source_site}</span>
                    </div>
                    <span>금액: ${price}</span>
                </div>
                <div class="flex gap-3 mt-2 text-sm">
                    <a href="/tender/${tender.id}" class="text-blue-600 hover:underline">상세보기 →</a>
                    ${tender.url ? `<a href="${tender.url}" target="_blank" class="text-gray-600 hover:underline">원본 공고 →</a>` : ''}
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

// 활성화된 키워드 표시 — 한 줄에 들어가는 만큼만 표시, 나머지는 +N개 →
function renderActiveKeywords(keywords) {
    const container = document.getElementById('active-keywords');
    if (!container) return;

    if (!keywords || keywords.length === 0) {
        container.innerHTML = '<span class="text-sm text-blue-700">설정된 키워드가 없습니다. <a href="/filters" class="underline hover:text-blue-900">필터 관리</a>에서 추가하세요.</span>';
        return;
    }

    const TAG_CLS = 'inline-flex items-center px-3 py-1 rounded-full text-sm font-medium bg-blue-100 text-blue-800 shrink-0 whitespace-nowrap';
    const MORE_CLS = 'inline-flex items-center px-3 py-1 rounded-full text-sm font-medium bg-blue-200 text-blue-700 hover:bg-blue-300 transition-colors shrink-0 whitespace-nowrap';

    // 1단계: 전부 nowrap 으로 렌더해서 너비 측정
    container.style.cssText = 'flex-wrap:nowrap;overflow:hidden;';
    container.innerHTML = keywords.map((kw, i) =>
        `<span data-i="${i}" class="${TAG_CLS}">${kw}</span>`
    ).join('');

    // 2단계: 페인트 후 컨테이너 오른쪽 경계를 넘는 첫 항목 탐색
    requestAnimationFrame(() => {
        const cRight = container.getBoundingClientRect().right;
        const spans  = container.querySelectorAll('span[data-i]');
        let cut = spans.length;

        for (let i = 0; i < spans.length; i++) {
            if (spans[i].getBoundingClientRect().right > cRight + 2) {
                cut = i;
                break;
            }
        }

        container.style.cssText = ''; // 원래 flex-wrap 복원

        if (cut >= keywords.length) {
            // 전부 한 줄에 들어감
            container.innerHTML = keywords.map(kw =>
                `<span class="${TAG_CLS}">${kw}</span>`
            ).join('');
        } else {
            // +N개 버튼 공간 확보를 위해 cut-1 개만 표시
            const show = Math.max(1, cut - 1);
            const rest = keywords.length - show;
            container.innerHTML =
                keywords.slice(0, show).map(kw =>
                    `<span class="${TAG_CLS}">${kw}</span>`
                ).join('') +
                `<a href="/filters" class="${MORE_CLS}">+${rest}개 →</a>`;
        }
    });
}
