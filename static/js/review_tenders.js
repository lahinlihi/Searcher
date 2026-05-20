let _allTenders = [];
let _sortBy = 'memo_date'; // memo_date | deadline | memo_count
let _filterMode = 'all';  // all | unread

document.addEventListener('DOMContentLoaded', () => {
    _applyButtonState();
    loadReviewTenders();
    fetch('/api/memos/mark-seen', { method: 'POST' })
        .then(() => {
            document.querySelectorAll('#memo-badge, #memo-badge-mobile').forEach(el => el.classList.add('hidden'));
            sessionStorage.setItem('memoToastDismissed', '1');
        })
        .catch(() => {});
});

async function loadReviewTenders() {
    try {
        const res = await fetch('/api/memos/tenders');
        _allTenders = await res.json();
        if (!Array.isArray(_allTenders)) _allTenders = [];
        renderReviewList();
    } catch (e) {
        document.getElementById('review-list').innerHTML =
            `<p class="text-red-500 text-sm">불러오기 실패: ${e.message}</p>`;
    }
}

function _applyButtonState() {
    // 세그먼트 컨트롤: active = 흰 배경 + 그림자, inactive = 투명
    document.querySelectorAll('.filter-btn').forEach(b => {
        const active = b.dataset.filter === _filterMode;
        b.classList.toggle('bg-white',      active);
        b.classList.toggle('shadow-sm',     active);
        b.classList.toggle('text-gray-900', active);
        b.classList.toggle('font-semibold', active);
        b.classList.toggle('text-gray-500', !active);
        b.classList.toggle('font-medium',   !active);
    });
    // 정렬 버튼: active = 진한 테두리 + 진한 텍스트, inactive = 연한 테두리 + 회색 텍스트
    document.querySelectorAll('.sort-btn').forEach(b => {
        const active = b.dataset.sort === _sortBy;
        b.classList.toggle('border-gray-700', active);
        b.classList.toggle('text-gray-800',   active);
        b.classList.toggle('font-semibold',   active);
        b.classList.toggle('bg-white',        active);
        b.classList.toggle('border-gray-200', !active);
        b.classList.toggle('text-gray-400',   !active);
        b.classList.toggle('bg-transparent',  !active);
    });
}

function _updateFilterCounts() {
    const total = _allTenders.length;
    const unread = _allTenders.filter(t => t.is_unread).length;
    document.querySelectorAll('.filter-btn').forEach(b => {
        if (b.dataset.filter === 'all')    b.textContent = `전체 (${total})`;
        if (b.dataset.filter === 'unread') b.textContent = `미열람 (${unread})`;
    });
}

function setFilter(val) {
    _filterMode = val;
    _applyButtonState();
    renderReviewList();
}

function setSort(val) {
    _sortBy = val;
    _applyButtonState();
    renderReviewList();
}

function renderReviewList() {
    const unreadCount = _allTenders.filter(t => t.is_unread).length;

    const filtered = _filterMode === 'unread'
        ? _allTenders.filter(t => t.is_unread)
        : _allTenders;

    const sorted = [...filtered].sort((a, b) => {
        if (_sortBy === 'deadline') {
            const da = a.days_left ?? 9999, db_ = b.days_left ?? 9999;
            return da - db_;
        }
        if (_sortBy === 'memo_count') return b.memo_count - a.memo_count;
        return new Date(b.latest_memo_at || 0) - new Date(a.latest_memo_at || 0);
    });

    // 필터 버튼에 숫자 반영
    _updateFilterCounts();

    const container = document.getElementById('review-list');
    if (sorted.length === 0) {
        const msg = _filterMode === 'unread'
            ? '미열람 공고가 없습니다.' : '메모가 작성된 공고가 없습니다.';
        container.innerHTML = `<div class="text-center py-12"><p class="text-gray-400 text-sm">${msg}</p></div>`;
        return;
    }
    container.innerHTML = sorted.map(t => renderReviewCard(t)).join('');
}

function renderReviewCard(tender) {
    const daysLeft = tender.days_left;
    const isExpired = daysLeft !== null && daysLeft < 0;
    const deadlineText = daysLeft !== null ? (isExpired ? `마감 (D${daysLeft})` : `D-${daysLeft}`) : '-';
    const deadlineClass = isExpired ? 'text-gray-400' : (daysLeft <= 2 ? 'text-red-600 font-semibold' : 'text-gray-600');
    const price = tender.estimated_price ? formatPrice(tender.estimated_price) : '미정';
    const statusBadge = tender.status === '사전규격'
        ? '<span class="tender-status-badge tender-status-pre">사전규격</span>'
        : '<span class="tender-status-badge tender-status-normal">일반</span>';
    const latestMemo = tender.latest_memo;
    const latestMemoAt = tender.latest_memo_at
        ? new Date(tender.latest_memo_at).toLocaleString('ko-KR', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
        : '';
    const agency = (tender.agency && tender.agency.includes('조달청') && tender.demand_agency)
        ? escapeHtml(tender.demand_agency) : escapeHtml(tender.agency);

    const unreadBadge = tender.is_unread
        ? '<span class="text-xs font-bold bg-red-500 text-white px-2 py-0.5 rounded-full">미열람</span>'
        : '<span class="text-xs text-gray-400 bg-gray-100 px-2 py-0.5 rounded-full">열람완료</span>';

    const cardOpacity = tender.is_unread ? '' : 'opacity-60';

    return `
        <div class="tender-item ${cardOpacity} transition-opacity">
            <div class="flex justify-between items-start mb-1">
                <div class="flex flex-wrap items-center gap-1">
                    ${statusBadge}
                    ${unreadBadge}
                    <span class="text-xs bg-purple-100 text-purple-700 border border-purple-200 px-2 py-0.5 rounded font-semibold">✎ ${tender.memo_count}개</span>
                </div>
                <span class="${deadlineClass} text-sm shrink-0 ml-2">${deadlineText}</span>
            </div>
            <h4 class="font-medium ${tender.is_unread ? 'text-gray-900' : 'text-gray-500'} mt-1 line-clamp-1 sm:text-sm">
                <a href="/tender/${tender.id}" class="hover:text-blue-600 hover:underline">
                    ${escapeHtml(tender.title)}
                </a>
            </h4>
            <div class="sm:hidden flex flex-col gap-1 mt-2">
                <span class="text-sm text-gray-700 font-bold truncate">${agency}</span>
                <span class="text-sm text-blue-600 font-medium">${price}</span>
            </div>
            <div class="hidden sm:flex items-center gap-3 mt-1.5 text-sm flex-wrap">
                <span class="font-medium text-gray-800 truncate">${agency}</span>
                <span class="font-medium text-blue-600">${price}</span>
                <a href="/tender/${tender.id}#memos" class="text-purple-500 hover:underline text-xs">의견 보기 →</a>
                ${tender.url ? `<a href="${tender.url}" target="_blank" class="text-gray-500 hover:underline text-xs">공고 원문 →</a>` : ''}
            </div>
            ${latestMemo ? `
            <div class="mt-2 px-3 py-2 bg-purple-50 border border-purple-100 rounded-lg text-sm text-gray-700">
                <span class="font-semibold text-purple-700">${escapeHtml(latestMemo.username)}</span>
                <span class="text-gray-400 text-xs ml-1">${latestMemoAt}</span>
                <p class="mt-0.5 text-gray-600 line-clamp-2">${escapeHtml(latestMemo.content)}</p>
            </div>` : ''}
        </div>`;
}

function formatPrice(price) {
    if (!price) return '미정';
    price = parseInt(price);
    const eok = Math.floor(price / 100000000);
    const man = Math.floor((price % 100000000) / 10000);
    if (eok > 0 && man > 0) return `${eok}억 ${man}만원`;
    if (eok > 0) return `${eok}억원`;
    if (man > 0) return `${man}만원`;
    return price.toLocaleString() + '원';
}

function escapeHtml(s) {
    return String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}
