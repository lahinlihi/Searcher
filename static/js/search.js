// 검색 페이지 JavaScript

// ── 매칭 점수 배지 (dashboard와 동일 형식) ──────────────────────────────────
function buildScoreBadge(score, businessType, breakdown) {
    if (!score) return '<span class="text-xs text-gray-300">-</span>';
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

let currentPage = 1;
let currentFilters = {};
let currentKeywords = []; // 현재 검색한 키워드들
let bookmarkedIds = new Set();
let currentResults = [];  // 현재 검색 결과 (정렬용)
let searchSortField = 'announced';  // 기본: 발주일
let searchSortDir   = 'desc';       // 기본: 최신순
let interestMode    = null;         // 관심 키워드 검색 모드 {keywords, exclude_keywords}

// 공통 정렬 함수
// 마감일 정렬: 일반 공고(요청 방향) → 사전규격(오래 남은 순) 으로 그룹 분리
function sortItems(items) {
    if (!items || !items.length) return items;
    const field = searchSortField, dir = searchSortDir;

    if (field === 'days') {
        const regular = items.filter(t => t.status !== '사전규격');
        const pre     = items.filter(t => t.status === '사전규격');
        const byDays  = (arr, asc) => [...arr].sort((a, b) => {
            const va = a.days_left ?? 99999, vb = b.days_left ?? 99999;
            return asc ? va - vb : vb - va;
        });
        if (dir === 'asc') {
            return [...byDays(regular, true), ...byDays(pre, true)];
        } else {
            return [...byDays(pre, false), ...byDays(regular, false)];
        }
    }

    return [...items].sort((a, b) => {
        const ag = t => (t.agency && t.agency.includes('조달청') && t.demand_agency)
            ? t.demand_agency : (t.demand_agency || t.agency || '');
        if (field === 'title')    { const va = a.title || '', vb = b.title || ''; return dir === 'asc' ? va.localeCompare(vb,'ko') : vb.localeCompare(va,'ko'); }
        if (field === 'agency')   { const va = ag(a), vb = ag(b);                 return dir === 'asc' ? va.localeCompare(vb,'ko') : vb.localeCompare(va,'ko'); }
        if (field === 'announced'){ const va = a.announced_date || '', vb = b.announced_date || ''; return dir === 'asc' ? va.localeCompare(vb) : vb.localeCompare(va); }
        let va, vb;
        if (field === 'budget') { va = a.estimated_price ?? -1; vb = b.estimated_price ?? -1; }
        else if (field === 'memo')  { va = a.memo_count ?? 0; vb = b.memo_count ?? 0; }
        else if (field === 'score') { va = a.relevance_score ?? 0; vb = b.relevance_score ?? 0; }
        else                    { va = 0; vb = 0; }
        return dir === 'asc' ? va - vb : vb - va;
    });
}

// 정렬 헤더 클릭
function setSearchSort(field) {
    if (searchSortField === field) {
        searchSortDir = searchSortDir === 'asc' ? 'desc' : 'asc';
    } else {
        searchSortField = field;
        searchSortDir = (field === 'budget' || field === 'announced' || field === 'memo' || field === 'score') ? 'desc' : 'asc';
    }
    if (currentResults.length) renderResults(sortItems(currentResults));
}

// 페이지 로드 시 실행
document.addEventListener('DOMContentLoaded', function() {
    loadBookmarkedIds();

    const urlParams = new URLSearchParams(window.location.search);
    if (urlParams.get('use_interest') === '1') {
        applyInterestAndSearch();
    } else if (urlParams.get('filter')) {
        applyDashboardFilter(urlParams.get('filter'));
    }
});

async function applyInterestAndSearch() {
    try {
        const res = await fetch('/api/interest-keywords');
        const data = await res.json();
        interestMode = {
            keywords: data.keywords || [],
            exclude_keywords: data.exclude_keywords || []
        };
        searchTenders(1);
    } catch (e) { console.error('관심 키워드 로드 실패:', e); }
}

// 대시보드 카드 클릭 시 필터 자동 적용
function applyDashboardFilter(filter) {
    const today = new Date();
    // 로컬 날짜 기준으로 yyyy-mm-dd 포맷
    const fmt = d => {
        const y = d.getFullYear();
        const m = String(d.getMonth() + 1).padStart(2, '0');
        const day = String(d.getDate()).padStart(2, '0');
        return `${y}-${m}-${day}`;
    };

    if (filter === 'new') {
        // 공고일: 어제(월요일이면 지난 금요일)~오늘
        const from = new Date(today);
        if (today.getDay() === 1) {
            from.setDate(today.getDate() - 3); // 월요일 → 금요일
        } else {
            from.setDate(today.getDate() - 1); // 그 외 → 어제
        }
        document.getElementById('announced-date-from').value = fmt(from);
        document.getElementById('announced-date-to').value   = fmt(today);

    } else if (filter === 'pre') {
        document.getElementById('status-filter').value = '사전규격';

    } else if (filter === 'deadline') {
        // 마감일: 오늘~오늘+3일
        const to = new Date(today);
        to.setDate(today.getDate() + 3);
        document.getElementById('deadline-date-from').value = fmt(today);
        document.getElementById('deadline-date-to').value   = fmt(to);

    }
    // 'all'은 별도 필터 없이 전체 검색
    searchTenders(1);
}

async function loadBookmarkedIds() {
    try {
        const res = await fetch('/api/bookmarks/ids');
        bookmarkedIds = new Set(await res.json());
    } catch (e) {}
}

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
            btn.classList.replace('text-gray-300', 'text-yellow-500');
            btn.title = '관심공고 해제';
        } else {
            bookmarkedIds.delete(tenderId);
            btn.textContent = '☆';
            btn.classList.replace('text-yellow-500', 'text-gray-300');
            btn.title = '관심공고 추가';
        }
    } catch (e) { console.error(e); }
}

function starButton(tenderId) {
    const isBookmarked = bookmarkedIds.has(tenderId);
    const cls = isBookmarked ? 'text-yellow-500' : 'text-gray-300';
    const icon = isBookmarked ? '★' : '☆';
    const title = isBookmarked ? '관심공고 해제' : '관심공고 추가';
    return `<button onclick="toggleBookmark(${tenderId}, this)"
                class="${cls} hover:text-yellow-500 transition-colors text-base"
                title="${title}">${icon}</button>`;
}

// 검색 실행
async function searchTenders(page = 1) {
    currentPage = page;

    const includeKeywords = interestMode
        ? (interestMode.keywords || []).join(', ')
        : document.getElementById('include-keywords').value;
    const excludeKeywords = interestMode
        ? (interestMode.exclude_keywords || []).join(', ')
        : document.getElementById('exclude-keywords').value;
    const status = document.getElementById('status-filter').value;

    // 검색 키워드 파싱 및 저장 (강조 표시용)
    currentKeywords = [];
    if (includeKeywords) {
        const orGroups = includeKeywords.split(',').map(g => g.trim()).filter(g => g);
        orGroups.forEach(group => {
            if (group.includes('+')) {
                const andKeywords = group.split('+').map(k => k.trim()).filter(k => k);
                currentKeywords.push(...andKeywords);
            } else {
                currentKeywords.push(group);
            }
        });
    }

    // 날짜 필터 값 가져오기
    const announcedDateFrom = document.getElementById('announced-date-from').value;
    const announcedDateTo = document.getElementById('announced-date-to').value;
    const deadlineDateFrom = document.getElementById('deadline-date-from').value;
    const deadlineDateTo = document.getElementById('deadline-date-to').value;
    const includeExpired = document.getElementById('include-expired').checked;

    try {
        const params = new URLSearchParams({
            page: page,
            per_page: 100,  // 페이지당 100개 표시
            include_keywords: includeKeywords,
            exclude_keywords: excludeKeywords,
            status: status,
            announced_date_from: announcedDateFrom,
            announced_date_to: announcedDateTo,
            deadline_date_from: deadlineDateFrom,
            deadline_date_to: deadlineDateTo,
            include_expired: includeExpired ? '1' : '0'
        });

        const response = await fetch(`/api/tenders?${params}`);
        const data = await response.json();

        if (data.error) {
            console.error('Error:', data.error);
            return;
        }

        // 결과 저장 후 정렬 적용하여 렌더링
        currentResults = data.tenders || [];
        renderResults(sortItems(currentResults));
        renderPagination(data.current_page, data.pages);

        // 결과 수 업데이트
        document.getElementById('result-count').textContent = data.total;

        // 검색 키워드 정보 표시
        const keywordInfo = document.getElementById('keyword-info');
        if (currentKeywords.length > 0) {
            keywordInfo.textContent = `🔍 검색 키워드: ${currentKeywords.join(', ')}`;
            keywordInfo.classList.remove('hidden');
        } else {
            keywordInfo.classList.add('hidden');
        }

        // 적용된 필터 표시
        displayActiveFilters({
            includeKeywords,
            excludeKeywords,
            status,
            announcedDateFrom,
            announcedDateTo,
            deadlineDateFrom,
            deadlineDateTo,
            includeExpired
        });

        // 스크롤을 맨 위로 이동
        document.getElementById('results-wrapper').scrollTop = 0;

    } catch (error) {
        console.error('Failed to search:', error);
    }
}

// 키워드 강조 함수
function highlightKeywords(text) {
    if (!currentKeywords || currentKeywords.length === 0) {
        return text;
    }

    let highlightedText = text;
    currentKeywords.forEach(keyword => {
        if (keyword) {
            // 대소문자 구분 없이 검색
            const regex = new RegExp(`(${keyword})`, 'gi');
            highlightedText = highlightedText.replace(regex, '<mark class="bg-yellow-200 font-semibold px-1 rounded">$1</mark>');
        }
    });
    return highlightedText;
}

// 정렬 화살표 반환
function sortArrow(field) {
    if (searchSortField !== field) return '<span style="opacity:0.25;font-size:0.7em;">↕</span>';
    return `<span style="color:#2563EB;font-size:0.8em;">${searchSortDir === 'asc' ? '↑' : '↓'}</span>`;
}

// 결과 렌더링
function renderResults(tenders) {
    const container = document.getElementById('results-container');

    if (!tenders || tenders.length === 0) {
        container.className = 'p-6';
        container.innerHTML = '<p class="text-gray-500 text-sm">검색 결과가 없습니다.</p>';
        return;
    }

    container.className = '';  // 패딩 제거 (sticky header)

    const th = (field, label, width) => {
        const active = searchSortField === field ? ' sort-active' : '';
        return `<th class="sortable${active}" onclick="setSearchSort('${field}')" style="width:${width};">${label} ${sortArrow(field)}</th>`;
    };

    // 만료 여부 판단: days_left < 0 이면 마감된 공고
    const isExpiredTender = t => t.days_left !== null && t.days_left < 0;

    const makeRow = (tender) => {
        const isPre    = tender.status === '사전규격';
        const isExpired = isExpiredTender(tender);

        let rowClass, statusBadge;
        if (isExpired && isPre) {
            rowClass    = 'expired-pre-row';
            statusBadge = '<span class="badge-expired-pre">사전↓</span>';
        } else if (isExpired) {
            rowClass    = 'expired-row';
            statusBadge = '<span class="badge-expired">마감</span>';
        } else if (isPre) {
            rowClass    = 'pre-row';
            statusBadge = '<span class="badge-pre">사전</span>';
        } else {
            rowClass    = '';
            statusBadge = '<span class="badge-normal">일반</span>';
        }

        const daysLeft = tender.days_left;
        let deadlineClass = 'deadline-normal';
        let deadlineText;
        if (isExpired) {
            deadlineClass = '';
            deadlineText = `<span style="color:#9CA3AF;font-size:0.7rem;">D+${Math.abs(daysLeft)}</span>`;
        } else {
            deadlineText = daysLeft != null ? `D-${daysLeft}` : '-';
            if (daysLeft != null && daysLeft <= 2)      deadlineClass = 'deadline-urgent';
            else if (daysLeft != null && daysLeft <= 5) deadlineClass = 'deadline-soon';
        }

        const price = tender.estimated_price ? formatPrice(tender.estimated_price) : '미정';
        const highlightedTitle = highlightKeywords(cleanNoticeTitle(tender.title));
        const noticeBadges = getNoticeBadgesHtml(tender.title);
        const announcedDate = tender.announced_date ? tender.announced_date.substring(5, 10) : '-';

        let displayAgency, agencyTooltip;
        if (tender.source_site === '중소벤처 24') {
            displayAgency = tender.demand_agency || tender.agency;
            agencyTooltip = `사업수행기관: ${displayAgency}`;
        } else {
            const isJodal = tender.agency && tender.agency.includes('조달청');
            displayAgency = (isJodal && tender.demand_agency) ? tender.demand_agency : tender.agency;
            agencyTooltip = (isJodal && tender.demand_agency)
                ? `수요기관: ${tender.demand_agency} (발주: ${tender.agency})`
                : (tender.agency || '');
        }

        const titleStyle = isExpired ? ' style="color:#9CA3AF;"' : '';

        const memoBadge = (tender.memo_count > 0)
            ? `<span style="font-size:0.6rem;color:#7C3AED;font-weight:700;line-height:1;" title="메모 ${tender.memo_count}개">✎${tender.memo_count}</span>`
            : '';

        const scoreBadge = buildScoreBadge(tender.relevance_score ?? null, tender.business_type || '기타', tender.score_breakdown || null);

        return `
            <tr class="${rowClass}">
                <td style="text-align:center;width:36px;">
                    <div style="display:flex;flex-direction:column;align-items:center;gap:1px;">
                        ${starButton(tender.id)}
                        ${memoBadge}
                    </div>
                </td>
                <td style="text-align:center;width:46px;">${statusBadge}</td>
                <td style="text-align:center;width:72px;">${scoreBadge}</td>
                <td class="title-col">
                    <a href="/tender/${tender.id}" class="title-link"${titleStyle} title="${cleanNoticeTitle(tender.title).replace(/"/g,'&quot;')}">${noticeBadges}${highlightedTitle}</a>
                </td>
                <td class="agency-col" title="${agencyTooltip.replace(/"/g,'&quot;')}">${displayAgency}</td>
                <td style="text-align:right;">${price}</td>
                <td style="text-align:center;font-size:0.75rem;color:#6B7280;">${announcedDate}</td>
                <td style="text-align:center;" class="${deadlineClass}">${deadlineText}</td>
                <td style="text-align:center;">
                    ${tender.url ? `<a href="${tender.url}" target="_blank" class="origin-link">원본</a>` : '-'}
                </td>
            </tr>`;
    };

    const sectionDivider = (label, count) =>
        `<tr class="section-divider"><td colspan="8">🔖 ${label} (${count}건)</td></tr>`;

    // 그룹 분류
    const activeTenders  = tenders.filter(t => !isExpiredTender(t));
    const expiredPre     = tenders.filter(t => isExpiredTender(t) && t.status === '사전규격');
    const expiredGeneral = tenders.filter(t => isExpiredTender(t) && t.status !== '사전규격');
    const hasExpired     = expiredPre.length > 0 || expiredGeneral.length > 0;

    let rows = '';

    // 진행중 공고
    if (activeTenders.length > 0) {
        if (hasExpired) rows += sectionDivider('진행중', activeTenders.length);
        rows += activeTenders.map(makeRow).join('');
    }

    // 마감된 사전규격
    if (expiredPre.length > 0) {
        rows += sectionDivider('마감된 사전규격', expiredPre.length);
        rows += expiredPre.map(makeRow).join('');
    }

    // 마감된 일반공고
    if (expiredGeneral.length > 0) {
        rows += sectionDivider('마감된 일반공고', expiredGeneral.length);
        rows += expiredGeneral.map(makeRow).join('');
    }

    const html = `
        <table class="table table-compact">
            <thead>
                <tr>
                    ${th('memo', '✎', '36px')}
                    <th style="width:46px;">상태</th>
                    ${th('score',    '점수',     '72px')}
                    ${th('title',    '공고명',   'auto')}
                    ${th('agency',   '수요기관', '150px')}
                    ${th('budget',   '금액',     '100px')}
                    ${th('announced','발주일',   '72px')}
                    ${th('days',     '마감',     '66px')}
                    <th style="width:56px;">원본</th>
                </tr>
            </thead>
            <tbody>${rows}</tbody>
        </table>`;

    container.innerHTML = html;
}

// 페이징 렌더링
function renderPagination(currentPage, totalPages) {
    const container = document.getElementById('pagination');

    if (totalPages <= 1) {
        container.classList.add('hidden');
        return;
    }

    container.classList.remove('hidden');
    let html = '';

    // 이전 버튼
    if (currentPage > 1) {
        html += `<button onclick="searchTenders(${currentPage - 1})" class="px-3 py-1 border rounded hover:bg-gray-100 text-sm">이전</button>`;
    }

    // 페이지 번호 표시 로직
    const maxPagesToShow = 10;
    let startPage = Math.max(1, currentPage - Math.floor(maxPagesToShow / 2));
    let endPage = Math.min(totalPages, startPage + maxPagesToShow - 1);

    // startPage 조정
    if (endPage - startPage < maxPagesToShow - 1) {
        startPage = Math.max(1, endPage - maxPagesToShow + 1);
    }

    // 첫 페이지
    if (startPage > 1) {
        html += `<button onclick="searchTenders(1)" class="px-3 py-1 border rounded hover:bg-gray-100 text-sm">1</button>`;
        if (startPage > 2) {
            html += `<span class="px-2 text-gray-500">...</span>`;
        }
    }

    // 페이지 번호
    for (let i = startPage; i <= endPage; i++) {
        const activeClass = i === currentPage ? 'bg-blue-600 text-white' : 'bg-white hover:bg-gray-100';
        html += `<button onclick="searchTenders(${i})" class="px-3 py-1 border rounded ${activeClass} text-sm">${i}</button>`;
    }

    // 마지막 페이지
    if (endPage < totalPages) {
        if (endPage < totalPages - 1) {
            html += `<span class="px-2 text-gray-500">...</span>`;
        }
        html += `<button onclick="searchTenders(${totalPages})" class="px-3 py-1 border rounded hover:bg-gray-100 text-sm">${totalPages}</button>`;
    }

    // 다음 버튼
    if (currentPage < totalPages) {
        html += `<button onclick="searchTenders(${currentPage + 1})" class="px-3 py-1 border rounded hover:bg-gray-100 text-sm">다음</button>`;
    }

    // 페이지 정보 표시
    html += `<span class="ml-4 text-sm text-gray-600">페이지 ${currentPage} / ${totalPages}</span>`;

    container.innerHTML = html;
}

// 적용된 필터 표시
function displayActiveFilters(filters) {
    const container = document.getElementById('active-filters');
    const wrapper = document.getElementById('active-filters-container');

    let html = '';
    let hasFilters = false;

    // 포함/제외 키워드
    if (interestMode) {
        // 관심 키워드 모드: 단일 배지로 표시
        html += `
            <span class="inline-flex items-center gap-1 px-3 py-1 bg-blue-100 text-blue-800 text-sm rounded-full">
                <span>🔖 관심 키워드</span>
                <button onclick="resetInterestMode()" class="hover:bg-blue-200 rounded-full p-0.5">
                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
                    </svg>
                </button>
            </span>
        `;
        hasFilters = true;
    } else {
        // 일반 포함 키워드
        if (filters.includeKeywords) {
            const orGroups = filters.includeKeywords.split(',').map(g => g.trim()).filter(g => g);
            if (orGroups.length > 0) {
                const groupTexts = orGroups.map(group => {
                    if (group.includes('+')) {
                        const andKeywords = group.split('+').map(k => k.trim()).filter(k => k);
                        return '(' + andKeywords.join(' <strong>그리고</strong> ') + ')';
                    } else {
                        return group;
                    }
                });
                const keywordText = groupTexts.join(' <strong>또는</strong> ');
                html += `
                    <span class="inline-flex items-center gap-1 px-3 py-1 bg-blue-100 text-blue-800 text-sm rounded-full">
                        <span>포함: ${keywordText}</span>
                        <button onclick="removeFilter('include-all', '')" class="hover:bg-blue-200 rounded-full p-0.5">
                            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
                            </svg>
                        </button>
                    </span>
                `;
                hasFilters = true;
            }
        }

        // 일반 제외 키워드
        if (filters.excludeKeywords) {
            const keywords = filters.excludeKeywords.split(',').map(k => k.trim()).filter(k => k);
            if (keywords.length > 0) {
                const keywordText = keywords.join(', ');
                html += `
                    <span class="inline-flex items-center gap-1 px-3 py-1 bg-red-100 text-red-800 text-sm rounded-full">
                        <span>제외: ${keywordText}</span>
                        <button onclick="removeFilter('exclude-all', '')" class="hover:bg-red-200 rounded-full p-0.5">
                            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
                            </svg>
                        </button>
                    </span>
                `;
                hasFilters = true;
            }
        }
    }

    // 상태 필터
    if (filters.status) {
        html += `
            <span class="inline-flex items-center gap-1 px-3 py-1 bg-purple-100 text-purple-800 text-sm rounded-full">
                <span>상태: ${filters.status}</span>
                <button onclick="removeFilter('status', '')" class="hover:bg-purple-200 rounded-full p-0.5">
                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
                    </svg>
                </button>
            </span>
        `;
        hasFilters = true;
    }

    // 공고일 범위
    if (filters.announcedDateFrom || filters.announcedDateTo) {
        const fromText = filters.announcedDateFrom || '시작';
        const toText = filters.announcedDateTo || '끝';
        html += `
            <span class="inline-flex items-center gap-1 px-3 py-1 bg-green-100 text-green-800 text-sm rounded-full">
                <span>공고일: ${fromText} ~ ${toText}</span>
                <button onclick="removeFilter('announced-date', '')" class="hover:bg-green-200 rounded-full p-0.5">
                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
                    </svg>
                </button>
            </span>
        `;
        hasFilters = true;
    }

    // 마감일 범위
    if (filters.deadlineDateFrom || filters.deadlineDateTo) {
        const fromText = filters.deadlineDateFrom || '시작';
        const toText = filters.deadlineDateTo || '끝';
        html += `
            <span class="inline-flex items-center gap-1 px-3 py-1 bg-orange-100 text-orange-800 text-sm rounded-full">
                <span>마감일: ${fromText} ~ ${toText}</span>
                <button onclick="removeFilter('deadline-date', '')" class="hover:bg-orange-200 rounded-full p-0.5">
                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
                    </svg>
                </button>
            </span>
        `;
        hasFilters = true;
    } else if (!filters.announcedDateFrom && !filters.announcedDateTo && !filters.includeExpired) {
        // 날짜 필터가 전혀 없으면 기본 범위 표시
        html += `
            <span class="inline-flex items-center gap-1 px-3 py-1 bg-gray-100 text-gray-700 text-sm rounded-full">
                <span>📅 기본: 마감일 오늘~30일 이내</span>
            </span>
        `;
        hasFilters = true;
    }

    // 마감 공고 포함
    if (filters.includeExpired) {
        html += `
            <span class="inline-flex items-center gap-1 px-3 py-1 bg-red-100 text-red-800 text-sm rounded-full">
                <span>🔒 마감 공고 포함</span>
                <button onclick="removeFilter('include-expired', '')" class="hover:bg-red-200 rounded-full p-0.5">
                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
                    </svg>
                </button>
            </span>
        `;
        hasFilters = true;
    }

    // 필터가 있으면 표시, 없으면 숨김
    if (hasFilters) {
        container.innerHTML = html;
        wrapper.classList.remove('hidden');
    } else {
        wrapper.classList.add('hidden');
    }
}

// 개별 필터 제거
function removeFilter(type, value) {
    if (type === 'include-all') {
        // 모든 포함 키워드 제거
        document.getElementById('include-keywords').value = '';
    } else if (type === 'include') {
        const current = document.getElementById('include-keywords').value;
        const keywords = current.split(',').map(k => k.trim()).filter(k => k && k !== value);
        document.getElementById('include-keywords').value = keywords.join(', ');
    } else if (type === 'exclude-all') {
        // 모든 제외 키워드 제거
        document.getElementById('exclude-keywords').value = '';
    } else if (type === 'exclude') {
        const current = document.getElementById('exclude-keywords').value;
        const keywords = current.split(',').map(k => k.trim()).filter(k => k && k !== value);
        document.getElementById('exclude-keywords').value = keywords.join(', ');
    } else if (type === 'status') {
        document.getElementById('status-filter').value = '';
    } else if (type === 'announced-date') {
        document.getElementById('announced-date-from').value = '';
        document.getElementById('announced-date-to').value = '';
    } else if (type === 'deadline-date') {
        document.getElementById('deadline-date-from').value = '';
        document.getElementById('deadline-date-to').value = '';
    } else if (type === 'include-expired') {
        document.getElementById('include-expired').checked = false;
    }

    // 다시 검색
    searchTenders(1);
}

// 관심 키워드 모드 해제 (배지 X 버튼)
function resetInterestMode() {
    interestMode = null;
    searchTenders(1);
}

// 필터 초기화
function resetFilters() {
    interestMode = null;
    document.getElementById('include-keywords').value = '';
    document.getElementById('exclude-keywords').value = '';
    document.getElementById('status-filter').value = '';
    document.getElementById('announced-date-from').value = '';
    document.getElementById('announced-date-to').value = '';
    document.getElementById('deadline-date-from').value = '';
    document.getElementById('deadline-date-to').value = '';
    document.getElementById('include-expired').checked = false;

    // 적용된 필터 표시 숨김
    document.getElementById('active-filters-container').classList.add('hidden');
}

// Excel 내보내기
function exportExcel() {
    // 현재 필터 조건 가져오기
    const includeKeywords = document.getElementById('include-keywords').value;
    const excludeKeywords = document.getElementById('exclude-keywords').value;
    const status = document.getElementById('status-filter').value;

    // CSV 다운로드 URL 생성
    const params = new URLSearchParams();
    if (includeKeywords) params.append('include_keywords', includeKeywords);
    if (excludeKeywords) params.append('exclude_keywords', excludeKeywords);
    if (status) params.append('status', status);

    // CSV 다운로드
    window.location.href = `/api/export/csv?${params.toString()}`;
}

// 가격 포맷
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
