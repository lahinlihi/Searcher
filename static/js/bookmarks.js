// 관심공고 페이지 JavaScript

document.addEventListener('DOMContentLoaded', loadBookmarks);

async function loadBookmarks() {
    try {
        const res = await fetch('/api/bookmarks');
        const tenders = await res.json();

        const countEl = document.getElementById('bookmark-count');
        const container = document.getElementById('bookmarks-list');

        if (!tenders || tenders.length === 0) {
            countEl.textContent = '0건';
            container.innerHTML = `
                <div class="text-center py-12">
                    <p class="text-gray-400 text-sm mb-2">스크랩한 공고가 없습니다.</p>
                    <p class="text-gray-400 text-xs">대시보드나 검색 결과에서 ★ 버튼을 눌러 관심공고를 추가하세요.</p>
                </div>`;
            return;
        }

        countEl.textContent = `${tenders.length}건`;
        container.innerHTML = tenders.map(t => renderBookmarkCard(t)).join('');
    } catch (e) {
        console.error(e);
        document.getElementById('bookmarks-list').innerHTML =
            '<p class="text-red-500 text-sm">불러오기 실패</p>';
    }
}

function buildScoreBadge(score, businessType) {
    if (score === 0) return '';
    let bg, label;
    if (score >= 70) { bg = 'bg-green-100 text-green-800 border border-green-300'; label = '높음'; }
    else if (score >= 40) { bg = 'bg-yellow-100 text-yellow-800 border border-yellow-300'; label = '보통'; }
    else { bg = 'bg-gray-100 text-gray-600 border border-gray-300'; label = '낮음'; }
    const typeText = businessType && businessType !== '기타' ? ` · ${businessType}` : '';
    const displayScore = Number.isInteger(score) ? score : score.toFixed(1);
    return `<span class="inline-flex items-center gap-1 text-xs font-semibold px-2 py-0.5 rounded ${bg}"
                  title="적합도 점수: 키워드 매칭(45점) + 사업유형(45점) + 긴급도·규모(10점)">
        <span class="font-bold">${displayScore}점</span><span class="font-normal opacity-70">${label}${typeText}</span>
    </span>`;
}

function renderBookmarkCard(tender) {
    const statusBadge = tender.status === '사전규격'
        ? '<span class="tender-status-badge tender-status-pre">사전규격</span>'
        : '<span class="tender-status-badge tender-status-normal">일반</span>';

    const scoreBadge = buildScoreBadge(tender.relevance_score ?? 0, tender.business_type || '기타');

    const daysLeft = tender.days_left;
    let deadlineClass = 'tender-deadline-normal';
    let deadlineText = daysLeft !== null ? `D-${daysLeft}` : '-';
    if (daysLeft !== null && daysLeft <= 2) deadlineClass = 'tender-deadline-urgent';
    else if (daysLeft !== null && daysLeft <= 5) deadlineClass = 'tender-deadline-soon';

    const price = tender.estimated_price ? formatPrice(tender.estimated_price) : '미정';
    const announcedDate = tender.announced_date ? tender.announced_date.substring(0, 10) : '';
    const bookmarkedAt = tender.bookmarked_at ? tender.bookmarked_at.substring(0, 10) : '';

    return `
        <div class="tender-item" id="bookmark-card-${tender.id}">
            <div class="flex justify-between items-start mb-1">
                <div class="flex flex-wrap items-center gap-1">
                    ${statusBadge}
                    ${scoreBadge}
                    ${bookmarkedAt ? `<span class="text-xs text-yellow-600 bg-yellow-50 border border-yellow-200 px-2 py-0.5 rounded">★ ${bookmarkedAt} 스크랩</span>` : ''}
                </div>
                <div class="flex items-center gap-2 ml-2 shrink-0">
                    <span class="font-semibold ${deadlineClass}">${deadlineText}</span>
                    <button onclick="removeBookmark(${tender.id}, ${tender.bookmark_id})"
                            class="text-yellow-400 hover:text-gray-400 transition-colors text-lg leading-none"
                            title="관심공고 해제">★</button>
                </div>
            </div>
            <h4 class="font-medium text-gray-900 mt-1">
                <a href="/tender/${tender.id}" class="text-gray-900 hover:text-blue-600 hover:underline">
                    ${escapeHtml(tender.title)}
                </a>
            </h4>
            <div class="flex justify-between items-center text-sm text-gray-600 mt-1">
                <div class="flex items-center gap-2">
                    <span>발주: ${escapeHtml(tender.agency)}</span>
                    <span class="text-xs px-2 py-0.5 bg-gray-100 rounded">${tender.source_site}</span>
                    ${announcedDate ? `<span class="text-xs text-gray-400">등록: ${announcedDate}</span>` : ''}
                </div>
                <span>금액: ${price}</span>
            </div>
            <div class="flex gap-3 mt-1 text-sm">
                <a href="/tender/${tender.id}" class="text-blue-600 hover:underline">상세보기 →</a>
                ${tender.url ? `<a href="${tender.url}" target="_blank" class="text-gray-600 hover:underline">원본 공고 →</a>` : ''}
            </div>
        </div>`;
}

async function removeBookmark(tenderId, bookmarkId) {
    try {
        const res = await fetch('/api/bookmarks/toggle', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ tender_id: tenderId })
        });
        const data = await res.json();
        if (!data.bookmarked) {
            const card = document.getElementById(`bookmark-card-${tenderId}`);
            if (card) card.remove();
            const remaining = document.querySelectorAll('[id^="bookmark-card-"]').length;
            document.getElementById('bookmark-count').textContent = `${remaining}건`;
            if (remaining === 0) {
                document.getElementById('bookmarks-list').innerHTML = `
                    <div class="text-center py-12">
                        <p class="text-gray-400 text-sm mb-2">스크랩한 공고가 없습니다.</p>
                        <p class="text-gray-400 text-xs">대시보드나 검색 결과에서 ★ 버튼을 눌러 관심공고를 추가하세요.</p>
                    </div>`;
            }
        }
    } catch (e) {
        console.error(e);
    }
}

function formatPrice(price) {
    if (price >= 100000000) return (price / 100000000).toFixed(1) + '억원';
    if (price >= 10000000)  return (price / 10000000).toFixed(1) + '천만원';
    if (price >= 10000)     return (price / 10000).toFixed(0) + '만원';
    return price.toLocaleString() + '원';
}

function escapeHtml(str) {
    if (!str) return '';
    return str.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
