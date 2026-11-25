// 관심공고 화면 — 담은 공고 / 관심없음. 공고 한 줄은 tender-row.js 가 그린다.

const LABEL_OPTIONS = [
    { value: '',            text: '라벨 없음', bonus: 0 },
    { value: 'executable',  text: '수행 가능', bonus: 15 },
    { value: 'experienced', text: '경험 있음', bonus: 10 },
    { value: 'interested',  text: '관심사',    bonus: 5 },
    { value: 'reference',   text: '참고용',    bonus: 0 },
];

const EMPTY_BOOKMARKS = '<li class="hs-empty">담은 공고가 없습니다.<br>대시보드나 검색 결과에서 별표를 누르면 여기에 모입니다.</li>';

document.addEventListener('DOMContentLoaded', () => { loadBookmarks(); loadDismissed(); });
window.addEventListener('pageshow', e => { if (e.persisted) { loadBookmarks(); loadDismissed(); } });

function switchTab(tab) {
    ['bookmarks', 'dismissed'].forEach(t => {
        const on = t === tab;
        const btn = document.getElementById(`tab-${t}`);
        btn.classList.toggle('active', on);
        btn.setAttribute('aria-selected', String(on));
        document.getElementById(`panel-${t}`).classList.toggle('hidden', !on);
    });
}

// ── 담은 공고 ───────────────────────────────────────────────────────────────

async function loadBookmarks() {
    const list = document.getElementById('bookmarks-list');
    try {
        const res = await fetch('/api/bookmarks');
        const tenders = await res.json();
        if (!res.ok) throw new Error(tenders.error || `서버 오류 (${res.status})`);
        const n = Array.isArray(tenders) ? tenders.length : 0;
        document.getElementById('bookmark-count').textContent = n;
        if (!n) { list.innerHTML = EMPTY_BOOKMARKS; return; }
        // 진행 중 = 지금 들어갈지 고민하는 공고, 지난 공고 = 앞으로 비슷한 사업을 찾을 때 참고할 관심 이력
        const past = t => t.days_left !== null && t.days_left !== undefined && t.days_left < 0;
        const open = tenders.filter(t => !past(t)).sort((a, b) => (a.days_left ?? 99999) - (b.days_left ?? 99999));
        const closed = tenders.filter(past);
        list.innerHTML =
            `<li class="hs-list-label">진행 중 ${open.length}건 <span class="hs-list-label-note">지금 참여를 검토할 공고 · 마감이 가까운 순</span></li>`
            + (open.length ? open.map(renderBookmarkRow).join('')
                           : '<li class="hs-empty" style="padding: 20px 12px">진행 중인 관심공고가 없습니다.</li>')
            + (closed.length
                ? `<li class="hs-list-label" style="margin-top: 18px">지난 공고 ${closed.length}건 <span class="hs-list-label-note">관심을 가졌던 사업 · 다음에 비슷한 공고를 찾는 기준이 됩니다</span></li>`
                  + closed.map(renderBookmarkRow).join('')
                : '');
    } catch (e) {
        console.error('관심공고 로드 실패:', e);
        list.innerHTML = `<li class="hs-empty" style="color: var(--hs-bad)">불러오기 실패: ${safeHtml(e.message)}</li>`;
    }
}

function labelDropdown(bookmarkId, currentLabel) {
    const options = LABEL_OPTIONS.map(o =>
        `<option value="${o.value}" ${o.value === currentLabel ? 'selected' : ''}>${o.text}${o.bonus > 0 ? ' (+' + o.bonus + ')' : ''}</option>`
    ).join('');
    return `<label class="hs-sr" for="label-sel-${bookmarkId}">라벨</label>
            <select id="label-sel-${bookmarkId}" onchange="saveLabel(${bookmarkId}, this)" class="hs-input hs-label-select"
                    title="라벨에 따라 적합도에 보너스가 붙습니다">${options}</select>`;
}

function renderBookmarkRow(t) {
    const bookmarkedAt = t.bookmarked_at ? t.bookmarked_at.substring(0, 10) : '';
    const bonus = t.label_bonus > 0 ? `<span>라벨 보너스 <b>+${t.label_bonus}</b></span>` : '';
    return renderTenderRow(t, {
        announced: true, origin: true,
        metaHtml: `${labelDropdown(t.bookmark_id, t.bookmark_label || '')}${bonus}`
            + (bookmarkedAt ? `<span>담은 날 ${safeHtml(bookmarkedAt.substring(5))}</span>` : ''),
        actionsHtml: `<button type="button" class="hs-icon-btn hs-star on" aria-pressed="true" aria-label="관심공고에서 빼기" title="관심공고에서 빼기"
                        onclick="removeBookmark(${t.id})">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M12 3l2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1L3.2 9.5l6.1-.9z"></path></svg>
            </button>`,
    });
}

async function saveLabel(bookmarkId, selectEl) {
    try {
        await fetch(`/api/bookmarks/${bookmarkId}/label`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ label: selectEl.value })
        });
    } catch (e) { console.error(e); }
}

async function removeBookmark(tenderId) {
    try {
        const res = await fetch('/api/bookmarks/toggle', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ tender_id: tenderId })
        });
        const data = await res.json();
        if (data.bookmarked) return;
        loadBookmarks();          // 묶음별 건수를 다시 센다
    } catch (e) { console.error(e); }
}

// ── 관심없음 ───────────────────────────────────────────────────────────────

async function loadDismissed() {
    const list = document.getElementById('dismissed-list');
    try {
        const tenders = await (await fetch('/api/dismissed')).json();
        const n = Array.isArray(tenders) ? tenders.length : 0;
        document.getElementById('dismissed-count').textContent = n;
        list.innerHTML = n ? tenders.map(renderDismissedRow).join('')
            : '<li class="hs-empty">관심없음으로 숨긴 공고가 없습니다.</li>';
    } catch (e) {
        console.error('관심없음 로드 실패:', e);
        list.innerHTML = `<li class="hs-empty" style="color: var(--hs-bad)">불러오기 실패: ${safeHtml(e.message)}</li>`;
    }
}

function renderDismissedRow(t) {
    const at = t.dismissed_at ? t.dismissed_at.substring(0, 10) : '';
    return renderTenderRow(t, {
        metaHtml: at ? `<span>숨긴 날 ${safeHtml(at.substring(5))}</span>` : '',
        actionsHtml: `<button type="button" class="hs-btn" style="min-height: 36px; padding: 0 12px" title="다시 대시보드에 표시"
                        onclick="undismissTender(${t.id})">복원</button>`,
    });
}

async function undismissTender(tenderId) {
    try {
        const res = await fetch(`/api/tenders/${tenderId}/dismiss`, { method: 'DELETE' });
        if (res.ok) loadDismissed();
    } catch (e) { console.error(e); }
}
