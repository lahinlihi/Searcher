// 검색 페이지 JavaScript

let currentPage = 1;
let currentFilters = {};
let currentKeywords = []; // 현재 검색한 키워드들

// 페이지 로드 시 실행
document.addEventListener('DOMContentLoaded', function() {
    loadFilterPresets();
});

// 필터 프리셋 로드
async function loadFilterPresets() {
    try {
        const response = await fetch('/api/filters');
        const filters = await response.json();

        const select = document.getElementById('filter-preset');
        select.innerHTML = '<option value="">선택하세요</option>';

        filters.forEach(filter => {
            const option = document.createElement('option');
            option.value = filter.id;
            option.textContent = filter.name + (filter.is_default ? ' (기본)' : '');
            select.appendChild(option);
        });

        // 기본 필터가 있으면 자동 선택
        const defaultFilter = filters.find(f => f.is_default);
        if (defaultFilter) {
            select.value = defaultFilter.id;
        }

    } catch (error) {
        console.error('Failed to load filter presets:', error);
    }
}

// 프리셋 적용
async function applyPreset() {
    const filterId = document.getElementById('filter-preset').value;
    if (!filterId) return;

    try {
        const response = await fetch('/api/filters');
        const filters = await response.json();

        const filter = filters.find(f => f.id == filterId);
        if (!filter) return;

        // 필터 값 적용
        document.getElementById('include-keywords').value = filter.include_keywords.join(', ');
        document.getElementById('exclude-keywords').value = filter.exclude_keywords.join(', ');

        // 다른 필터 옵션도 적용 (있는 경우)
        if (filter.min_price !== null) {
            // 가격 필터는 현재 UI에 없지만 나중을 위해 준비
        }
        if (filter.days_before_deadline !== null) {
            // 마감일 필터도 마찬가지
        }

        // 프리셋 적용 후 자동으로 검색 실행
        // 키워드가 자동으로 파싱되고 강조 표시됨
        await searchTenders(1);

    } catch (error) {
        console.error('Failed to apply preset:', error);
    }
}

// 검색 실행
async function searchTenders(page = 1) {
    currentPage = page;

    const includeKeywords = document.getElementById('include-keywords').value;
    const excludeKeywords = document.getElementById('exclude-keywords').value;
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
            deadline_date_to: deadlineDateTo
        });

        const response = await fetch(`/api/tenders?${params}`);
        const data = await response.json();

        if (data.error) {
            console.error('Error:', data.error);
            return;
        }

        // 결과 렌더링
        renderResults(data.tenders);
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
            deadlineDateTo
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

// 결과 렌더링
function renderResults(tenders) {
    const container = document.getElementById('results-container');

    if (!tenders || tenders.length === 0) {
        container.innerHTML = '<div class="p-6"><p class="text-gray-500 text-sm">검색 결과가 없습니다.</p></div>';
        return;
    }

    const html = `
        <table class="table table-compact">
            <thead>
                <tr>
                    <th style="width: 80px;">상태</th>
                    <th style="min-width: 400px;">공고명</th>
                    <th style="width: 180px;">발주기관</th>
                    <th style="width: 150px;">출처</th>
                    <th style="width: 120px;">금액</th>
                    <th style="width: 80px;">마감</th>
                    <th style="width: 100px;">상세</th>
                </tr>
            </thead>
            <tbody>
                ${tenders.map(tender => {
                    const statusBadge = tender.status === '사전규격'
                        ? '<span class="badge badge-info">사전규격</span>'
                        : '<span class="badge">일반</span>';

                    const daysLeft = tender.days_left;
                    let deadlineClass = 'text-green-600';
                    let deadlineText = `D-${daysLeft}`;

                    if (daysLeft <= 2) {
                        deadlineClass = 'text-red-600 font-semibold';
                    } else if (daysLeft <= 5) {
                        deadlineClass = 'text-orange-600';
                    }

                    const price = tender.estimated_price
                        ? formatPrice(tender.estimated_price)
                        : '미정';

                    // 키워드 강조 적용
                    const highlightedTitle = highlightKeywords(tender.title);

                    return `
                        <tr class="hover:bg-gray-50">
                            <td class="text-center">${statusBadge}</td>
                            <td class="tender-title">
                                <a href="/tender/${tender.id}" class="font-medium text-blue-600 hover:underline">
                                    ${highlightedTitle}
                                </a>
                            </td>
                            <td class="truncate" title="${tender.agency}">${tender.agency}</td>
                            <td class="text-center">
                                <span class="text-xs px-2 py-1 bg-gray-100 rounded whitespace-nowrap">${tender.source_site}</span>
                            </td>
                            <td class="text-right whitespace-nowrap">${price}</td>
                            <td class="text-center ${deadlineClass}">${deadlineText}</td>
                            <td class="text-center">
                                <div class="flex gap-2 justify-center">
                                    <a href="/tender/${tender.id}" class="text-blue-600 hover:underline text-sm">상세</a>
                                    ${tender.url
                                        ? `<a href="${tender.url}" target="_blank" class="text-gray-600 hover:underline text-sm">원본</a>`
                                        : ''
                                    }
                                </div>
                            </td>
                        </tr>
                    `;
                }).join('')}
            </tbody>
        </table>
    `;

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

    // 포함 키워드 (특수문자로 AND/OR 구분)
    if (filters.includeKeywords) {
        // 쉼표로 split → OR 그룹들
        const orGroups = filters.includeKeywords.split(',').map(g => g.trim()).filter(g => g);

        if (orGroups.length > 0) {
            // 각 OR 그룹을 표시
            const groupTexts = orGroups.map(group => {
                // + 기호가 있으면 AND 그룹
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

    // 제외 키워드
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
    } else if (!filters.announcedDateFrom && !filters.announcedDateTo) {
        // 날짜 필터가 전혀 없으면 기본 범위 표시
        html += `
            <span class="inline-flex items-center gap-1 px-3 py-1 bg-gray-100 text-gray-700 text-sm rounded-full">
                <span>📅 기본: 마감일 오늘~30일 이내</span>
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
    }

    // 다시 검색
    searchTenders(1);
}

// 필터 초기화
function resetFilters() {
    document.getElementById('include-keywords').value = '';
    document.getElementById('exclude-keywords').value = '';
    document.getElementById('status-filter').value = '';
    document.getElementById('filter-preset').value = '';
    document.getElementById('announced-date-from').value = '';
    document.getElementById('announced-date-to').value = '';
    document.getElementById('deadline-date-from').value = '';
    document.getElementById('deadline-date-to').value = '';

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

// 실시간 크롤링 시작
async function startCrawling() {
    const statusDiv = document.getElementById('crawl-status');
    statusDiv.classList.remove('hidden');

    try {
        const response = await fetch('/api/search', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({})
        });

        const data = await response.json();

        if (response.ok) {
            // 크롤링 상태 폴링 시작
            pollCrawlStatus();
        } else {
            alert('크롤링 시작 실패: ' + data.error);
            statusDiv.classList.add('hidden');
        }

    } catch (error) {
        console.error('Failed to start crawling:', error);
        alert('크롤링 시작 중 오류가 발생했습니다.');
        statusDiv.classList.add('hidden');
    }
}

// 크롤링 상태 폴링
function pollCrawlStatus() {
    const interval = setInterval(async () => {
        try {
            const response = await fetch('/api/crawl/status');
            const data = await response.json();

            if (data.status === 'completed') {
                // 크롤링 완료
                clearInterval(interval);
                const statusDiv = document.getElementById('crawl-status');
                statusDiv.innerHTML = `
                    <p class="text-green-700 font-medium">크롤링 완료!</p>
                    <p class="text-sm text-green-600 mt-1">
                        총 ${data.total_found}건 수집, 새 공고 ${data.new_tenders}건
                    </p>
                `;

                // 5초 후 자동으로 검색 실행
                setTimeout(() => {
                    statusDiv.classList.add('hidden');
                    searchTenders(1);
                }, 5000);
            } else if (data.status === 'failed') {
                // 크롤링 실패
                clearInterval(interval);
                const statusDiv = document.getElementById('crawl-status');
                statusDiv.innerHTML = `
                    <p class="text-red-700 font-medium">크롤링 실패</p>
                    <p class="text-sm text-red-600 mt-1">${data.error_message || '오류가 발생했습니다.'}</p>
                `;

                setTimeout(() => {
                    statusDiv.classList.add('hidden');
                }, 5000);
            }

        } catch (error) {
            console.error('Failed to poll crawl status:', error);
        }
    }, 3000); // 3초마다 상태 체크
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
