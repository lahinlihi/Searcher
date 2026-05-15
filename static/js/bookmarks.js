// 관심공고 페이지 JavaScript

const LABEL_OPTIONS = [
    { value: '',           text: '라벨 없음',  bonus: 0,  cls: 'text-gray-400' },
    { value: 'executable', text: '수행 가능',  bonus: 15, cls: 'text-green-700' },
    { value: 'experienced',text: '경험 있음',  bonus: 10, cls: 'text-blue-700'  },
    { value: 'interested', text: '관심사',     bonus: 5,  cls: 'text-purple-700'},
    { value: 'reference',  text: '참고용',     bonus: 0,  cls: 'text-gray-500'  },
];

let currentTab = 'bookmarks';

document.addEventListener('DOMContentLoaded', () => {
    loadBookmarks();
    loadDismissed();
    loadMemos(); // 탭 선택 여부와 무관하게 카운트 표시
});

// 뒤로가기/앞으로가기(bfcache)로 복원될 때 재조회
window.addEventListener('pageshow', function(event) {
    if (event.persisted) {
        loadBookmarks();
        loadDismissed();
        if (currentTab === 'memos') loadMemos();
    }
});

// ── 탭 전환 ───────────────────────────────────────────────────────────────────
function switchTab(tab) {
    currentTab = tab;
    const tabs = ['bookmarks', 'dismissed', 'memos'];
    tabs.forEach(t => {
        const btn = document.getElementById(`tab-${t}`);
        const panel = document.getElementById(`panel-${t}`);
        if (t === tab) {
            btn.classList.add('tab-active', 'border-blue-600', 'text-blue-600');
            btn.classList.remove('border-transparent', 'text-gray-500');
            panel.classList.remove('hidden');
        } else {
            btn.classList.remove('tab-active', 'border-blue-600', 'text-blue-600');
            btn.classList.add('border-transparent', 'text-gray-500');
            panel.classList.add('hidden');
        }
    });
    // 메모 탭은 첫 진입 시 로드
    if (tab === 'memos') loadMemos();
}

function refreshCurrentTab() {
    if (currentTab === 'bookmarks') loadBookmarks();
    else if (currentTab === 'dismissed') loadDismissed();
    else if (currentTab === 'memos') loadMemos();
}

async function loadBookmarks() {
    try {
        const res = await fetch('/api/bookmarks');
        const tenders = await res.json();

        if (!res.ok) {
            throw new Error(tenders.error || `서버 오류 (${res.status})`);
        }

        const countEl = document.getElementById('bookmark-count');
        const container = document.getElementById('bookmarks-list');

        if (!Array.isArray(tenders) || tenders.length === 0) {
            countEl.textContent = '0';
            container.innerHTML = `
                <div class="text-center py-12">
                    <p class="text-gray-400 text-sm mb-2">스크랩한 공고가 없습니다.</p>
                    <p class="text-gray-400 text-xs">대시보드나 검색 결과에서 ★ 버튼을 눌러 관심공고를 추가하세요.</p>
                </div>`;
            return;
        }

        countEl.textContent = tenders.length;
        container.innerHTML = tenders.map(t => renderBookmarkCard(t)).join('');
    } catch (e) {
        console.error('관심공고 로드 실패:', e);
        document.getElementById('bookmarks-list').innerHTML =
            `<p class="text-red-500 text-sm">불러오기 실패: ${e.message}</p>`;
    }
}

// ── 관심없음 목록 ─────────────────────────────────────────────────────────────
async function loadDismissed() {
    try {
        const res = await fetch('/api/dismissed');
        const tenders = await res.json();
        const countEl = document.getElementById('dismissed-count');
        const container = document.getElementById('dismissed-list');

        if (!Array.isArray(tenders) || tenders.length === 0) {
            countEl.textContent = '0';
            container.innerHTML = `
                <div class="text-center py-12">
                    <p class="text-gray-400 text-sm">관심없음으로 숨긴 공고가 없습니다.</p>
                </div>`;
            return;
        }

        countEl.textContent = tenders.length;
        container.innerHTML = tenders.map(t => renderDismissedCard(t)).join('');
    } catch (e) {
        console.error('관심없음 로드 실패:', e);
        document.getElementById('dismissed-list').innerHTML =
            `<p class="text-red-500 text-sm">불러오기 실패: ${e.message}</p>`;
    }
}

function renderDismissedCard(tender) {
    const daysLeft = tender.days_left;
    const isExpired = daysLeft !== null && daysLeft < 0;
    const deadlineText = daysLeft !== null ? (isExpired ? `마감 (D${daysLeft})` : `D-${daysLeft}`) : '-';
    const deadlineClass = isExpired ? 'text-gray-400 line-through' : (daysLeft <= 2 ? 'text-red-600 font-semibold' : 'text-gray-600');
    const price = tender.estimated_price ? formatPrice(tender.estimated_price) : '미정';
    const dismissedAt = tender.dismissed_at ? tender.dismissed_at.substring(0, 10) : '';
    const statusBadge = tender.status === '사전규격'
        ? '<span class="tender-status-badge tender-status-pre">사전규격</span>'
        : '<span class="tender-status-badge tender-status-normal">일반</span>';

    return `
        <div class="tender-item opacity-60 hover:opacity-90 transition-opacity" id="dismissed-card-${tender.id}">
            <div class="flex justify-between items-start mb-1">
                <div class="flex flex-wrap items-center gap-1">
                    ${statusBadge}
                    ${dismissedAt ? `<span class="text-xs text-gray-400">숨김: ${dismissedAt}</span>` : ''}
                </div>
                <div class="flex items-center gap-2 ml-2 shrink-0">
                    <span class="${deadlineClass} text-sm">${deadlineText}</span>
                    <button onclick="undismissTender(${tender.id})"
                            class="text-xs text-blue-600 hover:text-blue-800 border border-blue-200 hover:border-blue-400 rounded px-2 py-0.5 transition-colors"
                            title="복원 — 다시 대시보드에 표시">복원</button>
                </div>
            </div>
            <h4 class="font-medium text-gray-700 mt-1 line-clamp-1">
                <a href="/tender/${tender.id}" class="hover:text-blue-600 hover:underline">
                    ${escapeHtml(tender.title)}
                </a>
            </h4>
            <div class="flex flex-col gap-1 mt-2">
                <span class="text-sm text-gray-700 font-bold truncate">${(tender.agency && tender.agency.includes('조달청') && tender.demand_agency) ? escapeHtml(tender.demand_agency) : escapeHtml(tender.agency)}</span>
                <span class="text-sm text-blue-600 font-medium">${price}</span>
            </div>
        </div>`;
}

async function undismissTender(tenderId) {
    try {
        const res = await fetch(`/api/tenders/${tenderId}/dismiss`, { method: 'DELETE' });
        if (res.ok) {
            const card = document.getElementById(`dismissed-card-${tenderId}`);
            if (card) {
                card.style.transition = 'opacity 0.3s';
                card.style.opacity = '0';
                setTimeout(() => { card.remove(); loadDismissed(); }, 300);
            }
        }
    } catch (e) { console.error(e); }
}

function buildScoreBadge(score, businessType, labelBonus, breakdown) {
    if (score === 0 && !labelBonus) return '';
    let bg;
    if (score >= 70)      bg = 'bg-green-100 text-green-800 border border-green-300';
    else if (score >= 40) bg = 'bg-yellow-100 text-yellow-800 border border-yellow-300';
    else                  bg = 'bg-gray-100 text-gray-600 border border-gray-300';
    const displayScore = score.toFixed(1);
    const bonusText = labelBonus > 0 ? ` <span class="text-green-600">(+${labelBonus})</span>` : '';
    let tooltip;
    if (breakdown) {
        const bonusPart = labelBonus > 0 ? ` + 라벨 +${labelBonus}` : '';
        tooltip = `${displayScore}점 = 키워드 ${breakdown.keyword.toFixed(1)} + 사업유형 ${breakdown.type.toFixed(1)} + 기관가중치 ${breakdown.agency.toFixed(1)}${bonusPart}`;
    } else {
        tooltip = `적합도 점수: ${displayScore}점`;
    }
    return `<span class="inline-flex items-center gap-1 text-xs font-semibold px-2 py-0.5 rounded ${bg}"
                  title="${tooltip}">
        <span class="font-bold">${displayScore}점${bonusText}</span>
    </span>`;
}

function labelDropdown(bookmarkId, currentLabel) {
    const cur = LABEL_OPTIONS.find(o => o.value === currentLabel) || LABEL_OPTIONS[0];
    const options = LABEL_OPTIONS.map(o =>
        `<option value="${o.value}" ${o.value === currentLabel ? 'selected' : ''}>${o.text}${o.bonus > 0 ? ' (+'+o.bonus+')' : ''}</option>`
    ).join('');
    return `<select id="label-sel-${bookmarkId}"
                    onchange="saveLabel(${bookmarkId}, this)"
                    class="text-xs border border-gray-200 rounded px-1.5 py-0.5 ${cur.cls} bg-white cursor-pointer focus:outline-none focus:ring-1 focus:ring-blue-300"
                    title="스크랩 라벨: 라벨에 따라 점수 보너스 부여">
                ${options}
            </select>`;
}

// ── 메모 공고 목록 ─────────────────────────────────────────────────────────────
async function loadMemos() {
    try {
        const res = await fetch('/api/memos/tenders');
        const tenders = await res.json();
        const countEl = document.getElementById('memos-count');
        const container = document.getElementById('memos-list');

        if (!Array.isArray(tenders) || tenders.length === 0) {
            countEl.textContent = '0';
            container.innerHTML = `
                <div class="text-center py-12">
                    <p class="text-gray-400 text-sm">메모가 작성된 공고가 없습니다.</p>
                </div>`;
            return;
        }

        countEl.textContent = tenders.length;
        container.innerHTML = tenders.map(t => renderMemoCard(t)).join('');
    } catch (e) {
        console.error('메모 공고 로드 실패:', e);
        document.getElementById('memos-list').innerHTML =
            `<p class="text-red-500 text-sm">불러오기 실패: ${e.message}</p>`;
    }
}

function renderMemoCard(tender) {
    const daysLeft = tender.days_left;
    const isExpired = daysLeft !== null && daysLeft < 0;
    const deadlineText = daysLeft !== null ? (isExpired ? `마감 (D${daysLeft})` : `D-${daysLeft}`) : '-';
    const deadlineClass = isExpired ? 'text-gray-400' : (daysLeft <= 2 ? 'text-red-600 font-semibold' : 'text-gray-600');
    const price = tender.estimated_price ? formatPrice(tender.estimated_price) : '미정';
    const statusBadge = tender.status === '사전규격'
        ? '<span class="tender-status-badge tender-status-pre">사전규격</span>'
        : '<span class="tender-status-badge tender-status-normal">일반</span>';
    const latestMemo = tender.latest_memo;
    const latestMemoAt = tender.latest_memo_at ? new Date(tender.latest_memo_at).toLocaleString('ko-KR', { year:'numeric', month:'2-digit', day:'2-digit', hour:'2-digit', minute:'2-digit' }) : '';

    return `
        <div class="tender-item" id="memo-card-${tender.id}">
            <div class="flex justify-between items-start mb-1">
                <div class="flex flex-wrap items-center gap-1">
                    ${statusBadge}
                    <span class="text-xs bg-purple-100 text-purple-700 border border-purple-200 px-2 py-0.5 rounded font-semibold">✎ 메모 ${tender.memo_count}개</span>
                </div>
                <div class="flex items-center gap-2 ml-2 shrink-0">
                    <span class="${deadlineClass} text-sm">${deadlineText}</span>
                </div>
            </div>
            <h4 class="font-medium text-gray-900 mt-1 line-clamp-1">
                <a href="/tender/${tender.id}" class="text-gray-900 hover:text-blue-600 hover:underline">
                    ${escapeHtml(tender.title)}
                </a>
            </h4>
            <div class="flex flex-col gap-1 mt-2">
                <span class="text-sm text-gray-700 font-bold truncate">${(tender.agency && tender.agency.includes('조달청') && tender.demand_agency) ? escapeHtml(tender.demand_agency) : escapeHtml(tender.agency)}</span>
                <span class="text-sm text-blue-600 font-medium">${price}</span>
            </div>
            ${latestMemo ? `
            <div class="mt-2 px-3 py-2 bg-purple-50 border border-purple-100 rounded-lg text-sm text-gray-700">
                <span class="font-semibold text-purple-700">${escapeHtml(latestMemo.username)}</span>
                <span class="text-gray-400 text-xs ml-1">${latestMemoAt}</span>
                <p class="mt-0.5 text-gray-600 line-clamp-2">${escapeHtml(latestMemo.content)}</p>
            </div>` : ''}
            <div class="flex gap-3 mt-1 text-sm">
                <a href="/tender/${tender.id}#memos" class="text-purple-600 hover:underline">메모 보기 →</a>
                ${tender.url ? `<a href="${tender.url}" target="_blank" class="text-gray-600 hover:underline">공고 원문 →</a>` : ''}
            </div>
        </div>`;
}

function renderBookmarkCard(tender) {
    const statusBadge = tender.status === '사전규격'
        ? '<span class="tender-status-badge tender-status-pre">사전규격</span>'
        : '<span class="tender-status-badge tender-status-normal">일반</span>';

    const scoreBadge = buildScoreBadge(
        tender.relevance_score ?? 0,
        tender.business_type || '기타',
        tender.label_bonus ?? 0,
        tender.score_breakdown || null
    );

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
                    ${bookmarkedAt ? `<span class="text-xs text-yellow-600 bg-yellow-50 border border-yellow-200 px-2 py-0.5 rounded">★ ${bookmarkedAt}</span>` : ''}
                    ${tender.memo_count > 0 ? `<span class="text-xs bg-purple-100 text-purple-700 border border-purple-200 px-2 py-0.5 rounded font-semibold">✎ ${tender.memo_count}</span>` : ''}
                    ${labelDropdown(tender.bookmark_id, tender.bookmark_label || '')}
                </div>
                <div class="flex items-center gap-2 ml-2 shrink-0">
                    <span class="font-semibold ${deadlineClass}">${deadlineText}</span>
                    <button onclick="removeBookmark(${tender.id}, ${tender.bookmark_id})"
                            class="text-yellow-400 hover:text-gray-400 transition-colors text-lg leading-none"
                            title="관심공고 해제">★</button>
                </div>
            </div>
            <h4 class="font-medium text-gray-900 mt-1 line-clamp-1">
                <a href="/tender/${tender.id}" class="text-gray-900 hover:text-blue-600 hover:underline">
                    ${escapeHtml(tender.title)}
                </a>
            </h4>
            <div class="flex flex-col gap-1 mt-2">
                <span class="text-sm text-gray-700 font-bold truncate">${(tender.agency && tender.agency.includes('조달청') && tender.demand_agency) ? escapeHtml(tender.demand_agency) : escapeHtml(tender.agency)}</span>
                <div class="flex items-center gap-2 text-sm">
                    <span class="text-blue-600 font-medium">${price}</span>
                    ${announcedDate ? `<span class="text-gray-400 text-xs">등록: ${announcedDate}</span>` : ''}
                </div>
            </div>
            <div class="flex gap-3 mt-1 text-sm">
                <a href="/tender/${tender.id}" class="text-blue-600 hover:underline">상세보기 →</a>
                ${tender.url ? `<a href="${tender.url}" target="_blank" class="text-gray-600 hover:underline">공고 원문 →</a>` : ''}
            </div>
        </div>`;
}

async function saveLabel(bookmarkId, selectEl) {
    const label = selectEl.value;
    const opt = LABEL_OPTIONS.find(o => o.value === label) || LABEL_OPTIONS[0];
    // 색상 업데이트
    LABEL_OPTIONS.forEach(o => selectEl.classList.remove(o.cls));
    selectEl.classList.add(opt.cls);
    try {
        await fetch(`/api/bookmarks/${bookmarkId}/label`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ label })
        });
        // 점수 뱃지는 페이지 재로드 없이 보여주기 위해 조용히 성공 처리
    } catch (e) { console.error(e); }
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
            document.getElementById('bookmark-count').textContent = remaining;
            if (remaining === 0) {
                document.getElementById('bookmarks-list').innerHTML = `
                    <div class="text-center py-12">
                        <p class="text-gray-400 text-sm mb-2">스크랩한 공고가 없습니다.</p>
                        <p class="text-gray-400 text-xs">대시보드나 검색 결과에서 ★ 버튼을 눌러 관심공고를 추가하세요.</p>
                    </div>`;
            }
        }
    } catch (e) { console.error(e); }
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
