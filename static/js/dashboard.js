// 대시보드 JavaScript

let agencyChart = null;
let dailyChart = null;
let includeKeywords = [];
let bookmarkedIds = new Set();

// 페이지 로드 시 실행
document.addEventListener('DOMContentLoaded', function() {
    loadBookmarkedIds().then(() => {
        loadDashboardData();
        loadStats();
    });
});

// 북마크 ID 목록 로드
async function loadBookmarkedIds() {
    try {
        const res = await fetch('/api/bookmarks/ids');
        const ids = await res.json();
        bookmarkedIds = new Set(ids);
    } catch (e) { /* 조용히 무시 */ }
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
        renderActiveKeywords(includeKeywords, data.summary.keyword_match || 0);

        // 요약 통계 업데이트
        document.getElementById('new-today').textContent = data.summary.new_today + '건';
        document.getElementById('pre-announcement').textContent = data.summary.pre_announcement + '건';
        document.getElementById('deadline-soon').textContent = data.summary.deadline_soon + '건';
        document.getElementById('total-tenders').textContent = data.summary.total + '건';

        // 사전규격 공고 목록 렌더링 (키워드 하이라이트 + 적합도 점수)
        renderKeywordTenders('pre-tenders-list', data.pre_tenders, includeKeywords);

        // 나라장터 신규공고 렌더링 (키워드 하이라이트 + 적합도 점수)
        renderKeywordTenders('urgent-tenders-list', data.urgent_tenders, includeKeywords);

        // 기타 채널 신규공고 렌더링
        renderTenderList('recent-tenders-list', data.recent_tenders);

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
                    </div>
                </div>
                <h4 class="font-medium text-gray-900 mt-1">
                    <a href="/tender/${tender.id}" class="text-gray-900 hover:text-blue-600 hover:underline">
                        ${highlightedTitle}
                    </a>
                </h4>
                <div class="flex justify-between items-center text-sm text-gray-600 mt-1">
                    <div class="flex items-center gap-2">
                        <span>발주: ${tender.agency}</span>
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
                        <span>발주: ${tender.agency}</span>
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

// 활성화된 키워드 표시
function renderActiveKeywords(keywords, matchCount) {
    const container = document.getElementById('active-keywords');
    const countEl = document.getElementById('keyword-match-count');

    if (countEl !== null) {
        countEl.textContent = (matchCount || 0) + '건';
    }

    if (!container) return;

    if (!keywords || keywords.length === 0) {
        container.innerHTML = '<span class="text-sm text-gray-600">설정된 관심 키워드가 없습니다. 키워드를 설정하면 매칭 공고를 우선 표시합니다.</span>';
        return;
    }

    const html = keywords.map(keyword => `
        <span class="inline-flex items-center px-3 py-1 rounded-full text-sm font-medium bg-blue-100 text-blue-800">
            ${keyword}
        </span>
    `).join('');

    container.innerHTML = html;
}
