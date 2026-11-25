// 공고 상세 화면 (templates/detail.html) 의 동작.
// 서버가 넘겨주는 값은 템플릿의 DETAIL 객체에 있다:
//   tenderId, userId, role, isPreSpecExpired, basePrice, minBidRate, deadlineIso

// ── 공고 제목 펼치기 (모바일) ────────────────────────────────────────────────
function expandDetailTitle() {
    const el = document.getElementById('detail-title-text');
    const btn = document.getElementById('title-expand-btn');
    if (el) el.classList.add('title-expanded');
    if (btn) btn.style.display = 'none';
}
// 잘리지 않으면 버튼 숨김
(function() {
    const el = document.getElementById('detail-title-text');
    const btn = document.getElementById('title-expand-btn');
    if (el && btn && el.scrollHeight <= el.clientHeight + 2) {
        btn.style.display = 'none';
    }
})();

// ── 공유 메모 ─────────────────────────────────────────────────────────────────
const TENDER_ID = DETAIL.tenderId;
const MY_USER_ID = DETAIL.userId;
const MY_ROLE = DETAIL.role;

document.addEventListener('DOMContentLoaded', () => {
    loadMemos();
    loadReasonChips();
    const inp = document.getElementById('new-memo-input');
    if (inp) inp.addEventListener('input', () => {
        document.getElementById('memo-char-count').textContent = inp.value.length + ' / 1000';
    });

    // ── 타임라인 날짜순 정렬 ─────────────────────────────────────────────
    const tl = document.querySelector('.js-timeline');
    if (tl) {
        const items = Array.from(tl.children);
        items.sort((a, b) => (a.dataset.sortDt || '9').localeCompare(b.dataset.sortDt || '9'));
        items.forEach(el => tl.appendChild(el));
    }
});

// ── 이유 칩 (제품 계약서 5부) — 이 공고에 내가 남기는 검토 결과. 누를 때마다 눌린 전체를 저장한다 ──
const REASON_GROUP_LABEL = { ineligible: '자격이 안 됨', other: '그 밖의 이유', eligible: '검토 결과', like: '담는 이유' };
const REASON_GROUP_ORDER = ['eligible', 'ineligible', 'other', 'like'];
let _reasonPressed = new Set();

function _esc(v) {
    return String(v === null || v === undefined ? '' : v)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

async function loadReasonChips() {
    const box = document.getElementById('reason-chips');
    if (!box) return;
    try {
        const [o, mine] = await Promise.all([
            fetch('/api/reasons/options').then(r => { if (!r.ok) throw new Error(r.status); return r.json(); }),
            fetch(`/api/tenders/${TENDER_ID}/reasons`).then(r => { if (!r.ok) throw new Error(r.status); return r.json(); }),
        ]);
        _reasonPressed = new Set(mine.reasons || []);
        box.innerHTML = REASON_GROUP_ORDER.map(g => {
            const chips = o.options.filter(x => x.group === g).map(x =>
                `<button type="button" class="hs-reason-chip" data-reason="${_esc(x.code)}" aria-pressed="${_reasonPressed.has(x.code)}">${_esc(x.label)}</button>`).join('');
            return chips ? `<div class="hs-reason-group"><span class="hs-reason-group-label">${_esc(REASON_GROUP_LABEL[g] || g)}</span>${chips}</div>` : '';
        }).join('');
        box.addEventListener('click', onReasonChipClick);
    } catch (e) {
        box.innerHTML = '<span style="font-size: 13px; color: var(--hs-muted)">이유 칩을 불러오지 못했습니다.</span>';
    }
}

async function onReasonChipClick(e) {
    const chip = e.target.closest('[data-reason]');
    if (!chip) return;
    const code = chip.dataset.reason;
    const next = new Set(_reasonPressed);
    next.has(code) ? next.delete(code) : next.add(code);
    // 저장이 끝날 때까지 칩 전체를 잠근다 — 응답 전에 다른 칩을 누르면 앞의 선택이 덮여 사라진다
    const all = [...document.querySelectorAll('#reason-chips [data-reason]')];
    all.forEach(c => { c.disabled = true; });
    try {
        const res = await fetch(`/api/tenders/${TENDER_ID}/reasons`, {
            method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ reasons: [...next] }) });
        if (!res.ok) throw new Error((await res.json().catch(() => ({}))).error || res.status);
        _reasonPressed = next;
        chip.setAttribute('aria-pressed', String(next.has(code)));
    } catch (err) {
        alert('저장하지 못했습니다: ' + err.message);
    } finally {
        all.forEach(c => { c.disabled = false; });
    }
}

async function loadMemos() {
    try {
        const res = await fetch(`/api/tenders/${TENDER_ID}/memos`);
        const memos = await res.json();
        const container = document.getElementById('memos-list');
        if (!memos.length) {
            container.innerHTML = '';
            return;
        }
        container.innerHTML = memos.map(m => renderMemo(m)).join('');
    } catch (e) {
        // 실패 시 조용히 빈칸 유지
    }
}

function renderMemo(m) {
    const displayDt = m.is_edited ? new Date(m.updated_at) : new Date(m.created_at);
    const dateStr = displayDt.toLocaleString('ko-KR', { year:'numeric', month:'2-digit', day:'2-digit', hour:'2-digit', minute:'2-digit' });
    const editedBadge = m.is_edited ? '<span class="text-xs text-gray-400 ml-1">(수정됨)</span>' : '';
    const roleBadge = m.user_role === 'admin'
        ? '<span class="text-xs bg-blue-100 text-blue-700 px-1.5 py-0.5 rounded font-semibold ml-1">Admin</span>'
        : m.user_role === 'moderator'
        ? '<span class="text-xs bg-orange-100 text-orange-700 px-1.5 py-0.5 rounded font-semibold ml-1">관리자</span>'
        : '';
    const canManage = m.user_id === MY_USER_ID || MY_ROLE === 'admin';
    const actionBtns = canManage ? `
        <div class="flex items-center gap-1">
            <button onclick="startEditMemo(${m.id})" class="text-xs text-gray-400 hover:text-blue-500 transition-colors" title="수정">수정</button>
            <span class="text-gray-300">|</span>
            <button onclick="deleteMemo(${m.id})" class="text-xs text-gray-400 hover:text-red-500 transition-colors" title="삭제">삭제</button>
        </div>` : '';
    const content = (m.content || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/\n/g,'<br>');
    return `<div class="border rounded-lg p-3 bg-gray-50" id="memo-${m.id}">
        <div class="flex justify-between items-center mb-1.5">
            <div class="text-xs text-gray-500">
                <span class="font-semibold text-gray-700">${(m.username||'').replace(/&/g,'&amp;').replace(/</g,'&lt;')}</span>
                ${roleBadge}
                <span class="ml-2">${dateStr}</span>
                ${editedBadge}
            </div>
            ${actionBtns}
        </div>
        <div id="memo-view-${m.id}">
            <p class="text-sm text-gray-800 leading-relaxed">${content}</p>
        </div>
        <div id="memo-edit-${m.id}" class="hidden">
            <textarea id="memo-edit-input-${m.id}" class="form-input w-full text-sm resize-none mt-1" rows="3" maxlength="1000">${(m.content||'').replace(/</g,'&lt;').replace(/>/g,'&gt;')}</textarea>
            <div class="flex justify-end gap-2 mt-1.5">
                <button onclick="cancelEditMemo(${m.id})" class="text-xs text-gray-500 hover:text-gray-700">취소</button>
                <button onclick="saveEditMemo(${m.id})" class="btn-primary text-xs py-1 px-3">저장</button>
            </div>
            <p id="memo-edit-error-${m.id}" class="text-xs text-red-600 mt-1 hidden"></p>
        </div>
    </div>`;
}

function startEditMemo(memoId) {
    document.getElementById(`memo-view-${memoId}`).classList.add('hidden');
    document.getElementById(`memo-edit-${memoId}`).classList.remove('hidden');
    const ta = document.getElementById(`memo-edit-input-${memoId}`);
    ta.focus();
    ta.selectionStart = ta.selectionEnd = ta.value.length;
}

function cancelEditMemo(memoId) {
    document.getElementById(`memo-edit-${memoId}`).classList.add('hidden');
    document.getElementById(`memo-view-${memoId}`).classList.remove('hidden');
}

async function saveEditMemo(memoId) {
    const ta = document.getElementById(`memo-edit-input-${memoId}`);
    const errEl = document.getElementById(`memo-edit-error-${memoId}`);
    const content = ta.value.trim();
    if (!content) { errEl.textContent = '내용을 입력하세요.'; errEl.classList.remove('hidden'); return; }
    errEl.classList.add('hidden');
    try {
        const res = await fetch(`/api/tenders/${TENDER_ID}/memos/${memoId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ content })
        });
        const data = await res.json();
        if (!res.ok) { errEl.textContent = data.error || '수정 실패'; errEl.classList.remove('hidden'); return; }
        // Replace memo element with updated data
        const el = document.getElementById(`memo-${memoId}`);
        if (el) el.outerHTML = renderMemo(data);
    } catch (e) { errEl.textContent = '서버 오류'; errEl.classList.remove('hidden'); }
}

async function submitMemo() {
    const inp = document.getElementById('new-memo-input');
    const errEl = document.getElementById('memo-error');
    const content = inp.value.trim();
    if (!content) { errEl.textContent = '내용을 입력하세요.'; errEl.classList.remove('hidden'); return; }
    errEl.classList.add('hidden');
    try {
        const res = await fetch(`/api/tenders/${TENDER_ID}/memos`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ content })
        });
        const data = await res.json();
        if (!res.ok) { errEl.textContent = data.error || '등록 실패'; errEl.classList.remove('hidden'); return; }
        inp.value = '';
        document.getElementById('memo-char-count').textContent = '0 / 1000';
        loadMemos();
    } catch (e) { errEl.textContent = '서버 오류'; errEl.classList.remove('hidden'); }
}

async function deleteMemo(memoId) {
    if (!confirm('이 메모를 삭제하시겠습니까?')) return;
    try {
        const res = await fetch(`/api/tenders/${TENDER_ID}/memos/${memoId}`, { method: 'DELETE' });
        if (res.ok) { document.getElementById(`memo-${memoId}`)?.remove(); }
    } catch (e) { alert('삭제 실패'); }
}

// ── 관심공고 (북마크) ─────────────────────────────────────────────────────────
// 버튼 모양: ☆ 관심공고 담기 / ★ 관심공고에 담김
function _showBookmark(on) {
    const btn = document.getElementById('bookmark-btn');
    if (!btn) return;
    btn.classList.toggle('hs-star', true);
    btn.classList.toggle('on', on);
    btn.setAttribute('aria-pressed', String(on));
    const icon = btn.querySelector('.bm-icon');
    const label = btn.querySelector('.bm-label');
    if (icon) icon.textContent = on ? '★' : '☆';
    if (label) label.textContent = on ? '관심공고에 담김' : '관심공고 담기';
    btn.title = on ? '관심공고 해제' : '관심공고 추가';
}

(async function initBookmark() {
    try {
        const ids = await (await fetch('/api/bookmarks/ids')).json();
        _showBookmark(ids.includes(TENDER_ID));
    } catch (e) {
        _showBookmark(false);
    }
})();

async function toggleBookmark() {
    try {
        const res = await fetch('/api/bookmarks/toggle', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ tender_id: TENDER_ID })
        });
        const data = await res.json();
        _showBookmark(!!data.bookmarked);
    } catch (e) { console.error(e); }
}

// ── 연관 공고 로드 ────────────────────────────────────────────────────────────
(async function loadRelated() {
    const tenderId = TENDER_ID;
    const isPreSpecExpired = DETAIL.isPreSpecExpired;
    try {
        const resp = await fetch(`/api/tender/${tenderId}/related`);
        const list = await resp.json();

        // 사전규격 마감 상태일 때: 연관 본공고 확인해서 배너 상태 업데이트
        if (isPreSpecExpired) {
            const bannerTitle = document.getElementById('banner-title');
            const bannerSub   = document.getElementById('banner-sub');
            const bannerIcon  = document.getElementById('banner-icon');
            const banner      = document.getElementById('countdown-banner');
            // 활성 본공고 (사전규격이 아니고 마감 안 된 것)
            const activeBid = list && list.find(t => t.status !== '사전규격' && t.days_left !== null && t.days_left >= 0);
            if (activeBid && banner) {
                // 상태 3-1: 사전규격 → 본공고 입찰중
                banner.className = 'hs-dstatus hs-dstatus-live';
                if (bannerIcon) bannerIcon.textContent = '';
                if (bannerTitle) bannerTitle.textContent = '본 공고가 입찰 중입니다.';
                if (bannerSub) {
                    const dText = activeBid.days_left === 0 ? '오늘 마감' : `마감 D-${activeBid.days_left}`;
                    bannerSub.className = 'hs-dstatus-sub';
                    bannerSub.innerHTML = `${dText} · <a href="/tender/${activeBid.id}" class="hs-link" style="font-weight: 700">본 공고 바로가기 →</a>`;
                }
            } else {
                // 상태 2: 본공고 없음 또는 이미 마감
                if (bannerSub) bannerSub.textContent = '본 입찰 공고가 아직 올라오지 않았습니다.';
            }
        }

        if (!list || list.length === 0) return;  // 연관 공고 없으면 카드 숨김 유지

        const container = document.getElementById('related-list');
        const card      = document.getElementById('related-card');

        // 각 연관 공고를 행으로 표시
        container.innerHTML = list.map(t => {
            // 남은 일수 배지 색상 결정
            let badge = '';
            if (t.days_left === null) {
                badge = '';
            } else if (t.days_left < 0) {
                badge = '<span class="text-xs px-2 py-0.5 rounded-full bg-gray-200 text-gray-600 ml-2">마감기한 지남</span>';
            } else if (t.days_left <= 2) {
                badge = `<span class="text-xs px-2 py-0.5 rounded-full bg-red-100 text-red-700 ml-2">D-${t.days_left}</span>`;
            } else if (t.days_left <= 5) {
                badge = `<span class="text-xs px-2 py-0.5 rounded-full bg-orange-100 text-orange-700 ml-2">D-${t.days_left}</span>`;
            } else {
                badge = `<span class="text-xs px-2 py-0.5 rounded-full bg-green-100 text-green-700 ml-2">D-${t.days_left}</span>`;
            }

            const statusBadge = t.status === '사전규격'
                ? '<span class="text-xs px-2 py-0.5 rounded-full bg-blue-100 text-blue-700 mr-2">사전규격</span>'
                : '<span class="text-xs px-2 py-0.5 rounded-full bg-gray-100 text-gray-700 mr-2">일반</span>';

            const deadline = t.deadline_date
                ? `<span class="text-xs text-gray-400 ml-auto">${t.deadline_date} 마감</span>`
                : '';

            return `
            <a href="/tender/${t.id}"
               class="flex flex-col gap-1 px-3 py-2.5 rounded-lg border border-gray-100
                      hover:bg-blue-50 hover:border-blue-200 transition-colors text-sm">
                <div class="flex items-center gap-1.5 flex-wrap">
                    ${statusBadge}${badge}
                    ${deadline}
                </div>
                <span class="font-medium text-gray-800 leading-snug">${safeHtml(t.title)}</span>
            </a>`;
        }).join('');

        card.classList.remove('hidden');  // 공고가 있으면 카드 표시
    } catch (e) {
        console.debug('연관 공고 로드 실패:', e);
    }
})();

// ── 투찰 비율 계산기 ───────────────────────────────────────────────────────────
(function() {
    // 투찰금액 기준: asignBdgtAmt(부가세 포함, 확인됨) > presmptPrce*1.1(추정) > estimated_price
    var basePrice = DETAIL.basePrice;
    if (!basePrice) return;
    var defaultRate = parseFloat(DETAIL.minBidRate) || 88;

    var slider  = document.getElementById('bid-rate-slider');
    var inp     = document.getElementById('bid-rate-input');
    var aDisp   = document.getElementById('bid-amount-display');
    var approx  = document.getElementById('bid-amount-approx');
    if (!slider) return;

    function formatKorean(n) {
        /* 금액을 한글 단위로: 8억 4천만원, 7억 6천 3백 63만원 */
        var eok  = Math.floor(n / 100000000);
        var man  = Math.floor((n % 100000000) / 10000);
        function manStr(m) {
            var cheon = Math.floor(m / 1000);
            var baek  = Math.floor((m % 1000) / 100);
            var sub   = m % 100;
            var p = [];
            if (cheon) p.push(cheon + '천');
            if (baek)  p.push(baek  + '백');
            if (sub)   p.push(String(sub));
            return p.join(' ') + '만';
        }
        if (eok > 0) return (man > 0) ? eok + '억 ' + manStr(man) + '원' : eok + '억원';
        if (man > 0) return manStr(man) + '원';
        return n.toLocaleString('ko-KR') + '원';
    }

    function calc(rate) {
        rate = Math.max(70, Math.min(100, rate));
        var amount = Math.round(basePrice * rate / 100);
        if (aDisp) aDisp.textContent = amount.toLocaleString('ko-KR') + '원';
        if (approx) approx.textContent = formatKorean(amount);
    }

    slider.value = defaultRate;
    inp.value    = defaultRate.toFixed(1);
    calc(defaultRate);

    slider.addEventListener('input', function() {
        var v = parseFloat(this.value);
        inp.value = v.toFixed(1);
        calc(v);
    });
    inp.addEventListener('change', function() {
        var v = parseFloat(this.value) || defaultRate;
        v = Math.max(70, Math.min(100, v));
        this.value   = v.toFixed(1);
        slider.value = v;
        calc(v);
    });
    inp.addEventListener('input', function() {
        var v = parseFloat(this.value);
        if (!isNaN(v)) { slider.value = Math.min(100, Math.max(70, v)); calc(v); }
    });
})();

// ── 마감 카운트다운 타이머 ─────────────────────────────────────────────────────
(function() {
    const deadlineIso = DETAIL.deadlineIso;
    if (!deadlineIso) return;
    const deadline = new Date(deadlineIso);

    function fmt(ms) {
        if (ms <= 0) return '마감됨';
        const s  = Math.floor(ms / 1000);
        const m  = Math.floor(s  / 60);
        const h  = Math.floor(m  / 60);
        const d  = Math.floor(h  / 24);
        const rh = h  % 24;
        const rm = m  % 60;
        const rs = s  % 60;
        if (d > 0) return `${d}일 ${rh}시간 ${rm}분`;
        if (h > 0) return `${h}시간 ${rm}분 ${rs}초`;
        return `${rm}분 ${rs}초`;
    }

    function tick() {
        const rem = deadline - Date.now();
        const txt = document.getElementById('countdown-text');
        const hrs = document.getElementById('dday-hours');
        if (txt) txt.textContent = rem > 0 ? fmt(rem) : '마감됨';
        if (hrs && rem > 0) {
            const h = Math.floor(rem / 3600000) % 24;
            const m = Math.floor(rem / 60000) % 60;
            hrs.textContent = `· ${h}시간 ${m}분`;
        }
    }
    tick();
    setInterval(tick, 1000);
})();

function copyTenderNumber() {
    const tenderNumber = document.getElementById('tender-number').textContent;
    navigator.clipboard.writeText(tenderNumber).then(() => {
        const button = event.target;
        const originalText = button.textContent;
        button.textContent = '✓ 복사됨';
        button.classList.remove('bg-blue-100', 'text-blue-600');
        button.classList.add('bg-green-100', 'text-green-600');
        setTimeout(() => {
            button.textContent = originalText;
            button.classList.remove('bg-green-100', 'text-green-600');
            button.classList.add('bg-blue-100', 'text-blue-600');
        }, 2000);
    }).catch(err => {
        alert('복사 실패: ' + err);
    });
}

// ── 수행이력 조회 ──────────────────────────────────────────────────────────────
let _historyLoaded = false;
let _historyVisible = false;

function toggleHistory() {
    const card = document.getElementById('history-card');
    _historyVisible = !_historyVisible;
    if (_historyVisible) {
        card.classList.remove('hidden');
        card.scrollIntoView({ behavior: 'smooth', block: 'start' });
        if (!_historyLoaded) loadHistory();
        document.getElementById('history-toggle-btn').textContent = '🔍 수행이력 닫기';
    } else {
        card.classList.add('hidden');
        document.getElementById('history-toggle-btn').textContent = '🔍 수행이력 조회';
    }
}

async function loadHistory(allTypes = false, force = false) {
    const body = document.getElementById('history-body');
    const label = allTypes ? '물품·공사 포함 조회 중...' : '나라장터 공고·개찰·계약 조회 중 (용역)...';
    body.innerHTML = `<div class="text-center py-8"><div class="inline-block animate-spin rounded-full h-7 w-7 border-b-2 border-blue-500 mb-3"></div><p class="text-sm text-gray-500">${label}</p><p class="text-xs text-gray-400 mt-1">최근 5년 × 공고/개찰/계약 병렬 조회 중 (초회 ~1분 소요, 이후 즉시)</p></div>`;

    try {
        const params = new URLSearchParams();
        if (allTypes) params.set('all_types', '1');
        if (force)    params.set('force', '1');
        const url = `/api/tenders/${TENDER_ID}/history` + (params.toString() ? '?' + params.toString() : '');
        const res = await fetch(url);
        let data;
        try {
            data = await res.json();
        } catch (parseErr) {
            // 요청이 오래 걸려 프록시(Cloudflare 등)가 중간에 끊고 HTML 오류 페이지를
            // 돌려준 경우 res.json()이 "Unexpected token '<'"로 실패한다.
            // 원인을 알 수 있는 메시지로 바꿔서 보여주고 재시도 버튼 제공.
            body.innerHTML = `<p class="text-red-500 text-sm">이력 조회가 너무 오래 걸려 중간에 끊겼습니다 (HTTP ${res.status}).</p>` +
                `<p class="text-center mt-3"><button onclick="loadHistory(${allTypes}, true)" class="text-xs text-blue-500 hover:text-blue-700 underline">다시 조회</button></p>`;
            return;
        }
        _historyLoaded = true;

        if (data.error) { body.innerHTML = `<p class="text-red-500 text-sm">${safeHtml(data.error)}</p>`; return; }

        // 검색어 배지
        const badge = document.getElementById('history-query-badge');
        badge.textContent = `검색어: "${data.query}"`;
        badge.classList.remove('hidden');

        if (!data.items || data.items.length === 0) {
            let msg = '<p class="text-gray-400 text-sm text-center py-6">조회된 수행이력이 없습니다.</p>';
            if (!data.pblnc_api_ok) {
                msg += `<p class="text-xs text-amber-500 text-center mt-2">⚠ 입찰공고 API 미응답 — 개찰/낙찰 결과만 표시됩니다.</p>`;
            }
            if (data.errors && data.errors.length) {
                msg += `<p class="text-xs text-red-400 text-center mt-2">API 오류: ${safeHtml(data.errors.join(', '))}</p>`;
            }
            msg += `<p class="text-center mt-3"><button onclick="loadHistory(false, true)" class="text-xs text-blue-500 hover:text-blue-700 underline">다시 조회</button></p>`;
            body.innerHTML = msg;
            return;
        }

        // 상태별 카운트
        const cntMap = { '낙찰': 0, 'fail': 0, '계약': 0, '미공개': 0 };
        data.items.forEach(x => { if (x._status in cntMap) cntMap[x._status]++; });
        const badges = [];
        if (cntMap['낙찰'])   badges.push(`<span class="text-blue-600 font-semibold">${cntMap['낙찰']}건 낙찰</span>`);
        if (cntMap['계약'])   badges.push(`<span class="text-green-600 font-semibold" title="낙찰결과 없는 건에 대해 계약현황 API로 확인된 건">${cntMap['계약']}건 계약(현황)</span>`);
        if (cntMap['fail'])   badges.push(`<span class="text-red-500 font-semibold">${cntMap['fail']}건 유찰</span>`);
        if (cntMap['미공개']) badges.push(`<span class="text-gray-400 font-semibold">${cntMap['미공개']}건 미공개</span>`);
        const badgeStr = badges.length ? ` · ${badges.join(' · ')}` : '';

        let pblncWarn = '';
        if (!data.pblnc_api_ok) {
            pblncWarn = `<p class="text-xs text-amber-500 mt-1">⚠ 입찰공고 API 미응답 — 공고 기반 목록 불완전할 수 있습니다.</p>`;
        }

        const cachedNote = data.cached
            ? ` <span class="text-gray-300" title="1시간 캐시">· 캐시됨</span> <button onclick="loadHistory(false,true)" class="text-xs text-gray-400 hover:text-blue-500 underline ml-1">다시 조회</button>`
            : '';
        let html = `<p class="text-xs text-gray-400 mb-1">총 ${data.items.length}건 조회됨 (최신순)${badgeStr}${cachedNote}</p>${pblncWarn}`;
        html += `<div class="overflow-x-auto mt-2"><table class="w-full text-sm border-collapse">
            <thead>
                <tr class="bg-gray-50 text-xs text-gray-500">
                    <th class="px-3 py-2 text-left border-b font-semibold">개찰일</th>
                    <th class="px-3 py-2 text-left border-b font-semibold">공고명</th>
                    <th class="px-3 py-2 text-left border-b font-semibold">수요기관</th>
                    <th class="px-3 py-2 text-left border-b font-semibold">낙찰/계약 업체</th>
                    <th class="px-3 py-2 text-right border-b font-semibold">사업금액</th>
                    <th class="px-3 py-2 text-center border-b font-semibold">상태</th>
                </tr>
            </thead>
            <tbody>`;

        data.items.forEach((item, i) => {
            const status   = item._status   || '낙찰';
            const failType = item._fail_type || null;
            const fc       = item._followup_contract || null;
            const prtcpt   = item._prtcpt_cnt != null ? item._prtcpt_cnt : (item.prtcptCnum != null ? item.prtcptCnum : null);

            // 날짜
            const rawDt = item.rlOpengDt || item.opengDt || item.fnlSucsfDate || item.bidNtceDt || '';
            const openDt = safeHtml(rawDt.substring(0, 10));

            // 공고명 / 링크
            const nmRaw   = item.bidNtceNm || '';
            const nm      = nmRaw.length > 38 ? nmRaw.substring(0, 38) + '…' : nmRaw;
            const bidNo   = item.bidNtceNo  || '';
            const bidSeq  = (item.bidNtceOrd || '0').toString().padStart(3, '0');

            // 차세대 나라장터(2025.01~) 공고 직접 링크 — 비로그인 시 SSO 로그인 후 이동
            const g2bUrl = bidNo
                ? `https://www.g2b.go.kr/link/PNPE027_01/single/?bidPbancNo=${encodeURIComponent(bidNo)}&bidPbancOrd=${encodeURIComponent(bidSeq)}`
                : '';

            const linkCls =
                status === 'fail'     ? 'text-orange-600 hover:underline' :
                status === '상세없음' ? 'text-gray-500 hover:underline'   :
                status === '계약'     ? 'text-green-700 hover:underline'  :
                'text-blue-600 hover:underline';
            const nmHtml = g2bUrl
                ? `<a href="${safeUrl(g2bUrl)}" target="_blank" class="${linkCls} underline decoration-dotted" title="나라장터 공고 보기 (${safeHtml(bidNo)})">${safeHtml(nm || bidNo)}</a>`
                : `<span class="text-gray-600" title="${safeHtml(nmRaw)}">${safeHtml(nm || bidNo || '-')}</span>`;

            // 기관명
            const org = safeHtml(item.dminsttNm || item.ntceInsttNm || '-');

            // 추정가격 (부가세 포함)
            const presmptRaw = item._presmptPrce ? parseInt(item._presmptPrce) : 0;
            const presmptAmt = presmptRaw > 0 ? formatAmtKr(Math.round(presmptRaw * 1.1)) : null;

            // 참가수 표시
            const cntBadge = prtcpt != null
                ? `<span class="text-xs text-gray-400 ml-1">(${prtcpt}개사 참가)</span>`
                : '';

            let winnerCell, amtCell, statusCell, rowBg;

            if (status === '상세없음') {
                winnerCell = `<span class="text-gray-300 text-xs">-</span>`;
                amtCell    = presmptAmt ? `<span class="text-gray-400">${presmptAmt}</span>` : `<span class="text-gray-300">-</span>`;
                statusCell = `<span class="text-xs font-semibold border px-1.5 py-0.5 rounded bg-gray-50 text-gray-400 border-gray-200">상세없음</span>`;
                rowBg      = 'bg-gray-50';

            } else if (status === '계약') {
                const contractWinner = safeHtml(fc ? (fc.winner || '-') : '-');
                const contractAmt    = fc && fc.amount ? formatAmtKr(parseInt(fc.amount)) : (presmptAmt || '-');
                const prevLabel =
                    failType === 'sole_bidder' ? '단독응찰' :
                    failType === 'no_bidder'   ? '무응찰' : '유찰';
                winnerCell = `<span class="font-medium text-green-700">${contractWinner}</span>${cntBadge}`;
                amtCell    = `<span class="text-green-700 font-semibold">${contractAmt}</span>`;
                statusCell = `<span class="text-xs font-semibold border px-1.5 py-0.5 rounded bg-green-50 text-green-700 border-green-300">계약</span>
                    ${failType ? `<div class="text-xs text-gray-400 mt-0.5">(${prevLabel}후)</div>` : ''}`;
                rowBg = 'bg-green-50';

            } else if (status === 'fail') {
                const { label: fLabel, cls: fCls } =
                    failType === 'sole_bidder' ? { label: '단독응찰', cls: 'bg-red-50 text-red-600 border-red-200' } :
                    failType === 'no_bidder'   ? { label: '무응찰',   cls: 'bg-gray-100 text-gray-500 border-gray-300' } :
                                                  { label: '유찰',    cls: 'bg-orange-50 text-orange-500 border-orange-200' };
                winnerCell = `<span class="text-gray-400 text-xs">-</span>${cntBadge}`;
                amtCell    = presmptAmt ? `<span class="text-orange-600">${presmptAmt}</span>` : `<span class="text-gray-300">-</span>`;
                statusCell = `<span class="text-xs font-semibold border px-1.5 py-0.5 rounded ${fCls}">${fLabel}</span>`;
                rowBg = 'bg-orange-50';

            } else {
                // 낙찰
                const winner = item._winner_nm || item.bidwinnrNm || '-';
                const amt    = (item.sucsfbidAmt ? formatAmtKr(parseInt(item.sucsfbidAmt)) : null) || presmptAmt || '-';
                // 개찰 1순위와 실제 낙찰자가 다른 경우 (적격심사 탈락 등)
                const candidateNote = (item._openg_candidate && item._openg_candidate !== winner)
                    ? `<div class="text-xs text-orange-500 mt-0.5" title="개찰 시 1순위 투찰자가 적격심사에서 탈락하여 차순위로 낙찰된 경우">⚠ 개찰 1순위: ${safeHtml(item._openg_candidate)}</div>`
                    : '';
                winnerCell = `<span class="font-medium text-gray-800">${safeHtml(winner)}</span>${cntBadge}${candidateNote}`;
                amtCell    = `<span class="text-blue-700 font-semibold">${amt}</span>`;
                statusCell = `<span class="text-xs font-semibold border px-1.5 py-0.5 rounded bg-blue-50 text-blue-700 border-blue-200">낙찰</span>`;
                rowBg = i % 2 === 0 ? 'bg-white' : 'bg-gray-50';
            }

            html += `<tr class="${rowBg} hover:bg-blue-50 transition-colors">
                <td class="px-3 py-2 border-b text-gray-500 whitespace-nowrap text-xs">${openDt}</td>
                <td class="px-3 py-2 border-b text-sm">${nmHtml}</td>
                <td class="px-3 py-2 border-b text-gray-500 text-xs">${org}</td>
                <td class="px-3 py-2 border-b">${winnerCell}</td>
                <td class="px-3 py-2 border-b text-right whitespace-nowrap">${amtCell}</td>
                <td class="px-3 py-2 border-b text-center">${statusCell}</td>
            </tr>`;
        });

        html += `</tbody></table></div>`;
        if (data.errors && data.errors.length) {
            html += `<p class="text-xs text-orange-400 mt-3">일부 오류: ${safeHtml(data.errors.join(', '))}</p>`;
        }
        body.innerHTML = html;
    } catch (e) {
        body.innerHTML = `<p class="text-red-500 text-sm">이력 조회 실패: ${safeHtml(e.message)}</p>`;
    }
}

function formatAmtKr(n) {
    if (!n || isNaN(n)) return '-';
    const uk  = Math.floor(n / 100000000);
    const man = Math.floor((n % 100000000) / 10000);
    if (uk > 0 && man > 0) return `${uk}억 ${man.toLocaleString('ko-KR')}만원`;
    if (uk > 0) return `${uk}억원`;
    if (man > 0) return `${man.toLocaleString('ko-KR')}만원`;
    return n.toLocaleString('ko-KR') + '원';
}

// ── 수행이력 개찰 상세 확장 (inline data — 별도 API 호출 없음) ───────────────

/** 업체명 유사 비교 (법인 형태 접두어, 공백 무시) */

/**
 * 개찰 상세 렌더링 (API 실패 폴백용 — inline 데이터만 사용)
 * extraNote : 추가 안내 HTML (선택)
 */

/**
 * 전체 투찰업체 테이블 렌더링 (개찰결과목록조회 API 응답)
 * bidders : [{rank, name, bizNo, amount, rate, is_winner}, ...]
 * apiWinner : API가 반환한 공식 낙찰자명
 * inlineWinner : 수행이력 inline 데이터의 낙찰자명 (bidwinnrNm)
 */

// ── 탭 전환 ──────────────────────────────────────────────────────────────────
const TABS = ['summary','kpi','proposal','special'];

function switchTab(key) {
    TABS.forEach(k => {
        const panel = document.getElementById('tab-' + k);
        const btn   = document.getElementById('tab-btn-' + k);
        if (k === key) {
            panel.classList.remove('hidden');
            btn.classList.add('ai-tab-active');
        } else {
            panel.classList.add('hidden');
            btn.classList.remove('ai-tab-active');
        }
    });
}

// ── 계약기간 / 예산 정규화 헬퍼 ──────────────────────────────────────────────

/** Gemini summary 마크다운에서 특정 레이블 뒤 값 추출
 *  **계약 기간** / 계약기간 형태 모두 처리 */
function extractKeyFromSummary(md) {
    if (!md) return { contract: '', budget: '' };
    const result = {};
    // "**계약 기간**\n값" 또는 "계약 기간: 값" 형태
    const cMatch = md.match(/\*\*계약\s*기간\*\*\s*\n?\s*[-·]?\s*([^\n*#\[]{5,120})/);
    if (cMatch) result.contract = cMatch[1].trim();
    // "**예산 규모**\n값" 형태
    const bMatch = md.match(/\*\*예산\s*규모\*\*\s*\n?\s*[-·]?\s*([^\n*#\[]{3,120})/);
    if (bMatch) result.budget = bMatch[1].trim();
    return result;
}

/** 원화 금액(정수)을 한글로 읽기: 300000000 → "3억원" */
function toKoreanAmount(won) {
    const uk  = Math.floor(won / 100000000);
    const man = Math.floor((won % 100000000) / 10000);
    const parts = [];
    if (uk  > 0) parts.push(uk.toLocaleString('ko-KR')  + '억');
    if (man > 0) parts.push(man.toLocaleString('ko-KR') + '만');
    return parts.length ? parts.join(' ') + '원' : '';
}

/** 계약기간 정규화: 한글 날짜 → 숫자 날짜, 조사 정리 */
function normalizeContract(text) {
    if (!text) return text;
    // 앞에 붙은 ": " 또는 "- " 제거 (Gemini가 "**계약 기간**: 값" 형태로 줄 때)
    text = text.replace(/^[\s:·\-]+/, '');
    // HWP 인코딩 오류로 생성되는 CJK 한자 제거 (예: "湯湷", "乶乺" 등)
    text = text.replace(/[\u4E00-\u9FFF\u3400-\u4DBF\uF900-\uFAFF]+\s*/g, '');
    // 한국어 날짜 → 숫자 (2026년 12월 31일 → 2026.12.31)
    text = text.replace(/(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일?/g,
        (_, y, m, d) => `${y}.${String(m).padStart(2,'0')}.${String(d).padStart(2,'0')}`);
    // "계약체결일로부터" / "계약체결일부터" → "계약체결일 ~"
    text = text.replace(/계약\s*체결\s*일?\s*(?:로부터|부터)/g, '계약체결일 ~');
    // "로부터" 단독으로 남은 경우
    text = text.replace(/로부터\s*/g, ' ~ ');
    // "까지" 제거
    text = text.replace(/\s*까지\s*$/, '');
    return text.replace(/\s{2,}/g, ' ').trim();
}

/** 예산 정규화: 한글(억·만원) 우선 표시 + 숫자 원 단위 병기 */
function normalizeBudget(text) {
    if (!text) return text;
    // 천원 단위: "1,610,055천원"
    const chonM = text.match(/([\d,]+)\s*천원/);
    if (chonM) {
        const n   = parseInt(chonM[1].replace(/,/g, ''));
        const won = n * 1000;
        const kor = toKoreanAmount(won);
        return kor
            ? `${kor} (${won.toLocaleString('ko-KR')}원)`
            : `${n.toLocaleString('ko-KR')}천원`;
    }
    // 원 단위: "금300,000,000원" / "300,000,000원"
    const wonM = text.match(/금?\s*([\d,]+)\s*원/);
    if (wonM) {
        const n   = parseInt(wonM[1].replace(/,/g, ''));
        const kor = toKoreanAmount(n);
        return kor
            ? `${kor} (${n.toLocaleString('ko-KR')}원)`
            : `${n.toLocaleString('ko-KR')}원`;
    }
    // 억원 단위: 이미 한글 — 그대로 유지하되 '원' 단위 확인
    const ukM = text.match(/(\d[\d,]*)\s*억\s*(?:([\d,]+)\s*만)?\s*원?/);
    if (ukM) {
        const uk  = parseInt(ukM[1].replace(/,/g,''));
        const man = ukM[2] ? parseInt(ukM[2].replace(/,/g,'')) : 0;
        const won = uk * 100000000 + man * 10000;
        return `${ukM[0].replace(/\s+/g,'').replace(/원?$/, '')}원 (${won.toLocaleString('ko-KR')}원)`;
    }
    // 단위 없는 순수 숫자 (AI가 단위 생략한 경우) → 원 단위로 간주
    const bareM = text.trim().match(/^[\d,]+$/);
    if (bareM) {
        const n = parseInt(text.replace(/,/g, ''));
        if (n >= 10000) {
            const kor = toKoreanAmount(n);
            return kor ? `${kor} (${n.toLocaleString('ko-KR')}원)` : `${n.toLocaleString('ko-KR')}원`;
        }
    }
    return text;
}

// ── 마크다운 → HTML (개선 버전) ───────────────────────────────────────────────
const KPI_VAL_RE = /[\d,]+\s*(시간|명|개소|팀|점|천원|만원|억원|원|%|개|건|회)/;

function escHtml(s) {
    // 공통 함수(common.js)를 쓴다. 사본마다 바꾸는 글자가 달랐다(따옴표 누락 등).
    return safeHtml(s);
}
function inlineMd(text) {
    return escHtml(text)
        .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
        .replace(/_/g, ' ')
        // [태그] → 컬러 배지 (제출/발표/주의/운영)
        .replace(/\[(제출|발표|주의|운영)\]/g,
            (_, t) => `<span class="ai-tag ai-tag-${t}">[${t}]</span>`);
}

/**
 * 반복 key 패턴을 감지해 다열 표로 변환.
 * ex) [과정명, 교육기간, 교육방식, 과정명, 교육기간, 교육방식, ...]
 *     → 열: 과정명 | 교육기간 | 교육방식  /  행: 각 과정
 */
/**
 * 마침표로 구분된 긴 문장을 개별 항목 배열로 분리.
 * "문장1. 문장2. 문장3." → ["문장1", "문장2", "문장3"]
 * 짧거나 단일 문장이면 원본 배열 그대로 반환.
 */
function splitSentences(text) {
    if (!text || text.length < 25) return [text];
    // '. '(마침표+공백) 또는 '.\n' 기준 분리
    // 단, 숫자.숫자 (소수점), 숫자. (순번) 는 제외
    const parts = text
        .split(/(?<![0-9])\.(?:\s+|\n)(?=[^\s])/)
        .map(s => s.trim().replace(/\.$/, ''))
        .filter(s => s.length > 5);
    return parts.length >= 2 ? parts : [text];
}

function buildAutoTable(items, tabType) {
    if (!items.length || !items.every(i => i.type === 'info')) return null;
    const firstKey = items[0].key;
    let groupSize = -1;
    for (let i = 1; i < items.length; i++) {
        if (items[i].key === firstKey) { groupSize = i; break; }
    }
    if (groupSize < 2) return null;
    const headers = items.slice(0, groupSize).map(i => i.key);
    const rows = [];
    for (let s = 0; s < items.length; s += groupSize) {
        rows.push(items.slice(s, s + groupSize).map(i => i.val));
    }
    if (rows.length < 1) return null;
    // 탭별 동일 계열 색상 (명도·채도만 변화)
    const PALETTES = {
        summary:  { c:['#1e40af','#1d4ed8','#2563eb','#3b82f6','#60a5fa'], bg:['#dbeafe','#eff6ff','#e0f2fe','#f0f9ff','#bfdbfe'] },
        kpi:      { c:['#065f46','#047857','#10b981','#34d399','#6ee7b7'], bg:['#d1fae5','#ecfdf5','#a7f3d0','#f0fdf4','#e6fffa'] },
        proposal: { c:['#92400e','#b45309','#d97706','#f59e0b','#fbbf24'], bg:['#fde68a','#fef3c7','#fffbeb','#fff7ed','#fef9c3'] },
        special:  { c:['#4c1d95','#6d28d9','#7c3aed','#8b5cf6','#a78bfa'], bg:['#ede9fe','#f5f3ff','#f3e8ff','#e9d5ff','#ddd6fe'] },
    };
    const pal = PALETTES[tabType] || PALETTES.summary;
    let t = `<div class="ai-table-wrap"><table class="ai-table ai-auto-table"><thead><tr>`;
    t += headers.map(h => `<th>${escHtml(h.replace(/_/g,' '))}</th>`).join('');
    t += `</tr></thead><tbody>`;
    rows.forEach((row, ri) => {
        const ci = ri % pal.c.length;
        t += `<tr>`;
        row.forEach((v, vi) => {
            const style = vi === 0
                ? `style="border-left:4px solid ${pal.c[ci]};background:${pal.bg[ci]};font-weight:700"`
                : `style="background:${pal.bg[ci]}"`;
            t += `<td ${style}>${inlineMd(v)}</td>`;
        });
        t += `</tr>`;
    });
    t += `</tbody></table></div>`;
    return t;
}

function mdToHtml(md, tabType) {
    if (!md || md.trim() === '해당 없음' || md.trim() === '') {
        return '<p class="text-sm text-gray-400 italic py-4 text-center">해당 없음</p>';
    }

    const isKpi = tabType === 'kpi';
    const lines = md.split('\n');
    let html = '';
    let tableRows = [];
    let listItems = [];
    let currentH3 = '';  // 현재 h3 섹션 제목 추적 (섹션별 특별 렌더링용)

    function flushTable() {
        if (!tableRows.length) return;
        const [header, ...rawBody] = tableRows;
        tableRows = [];
        // 열 수가 헤더보다 적은 행 → '-' 로 패딩 (최저기준 없는 행 등)
        const body = rawBody.map(row => {
            if (row.length >= header.length) return row;
            return [...row, ...Array(header.length - row.length).fill('-')];
        });

        // ── 주요 과업 범위: 계층형 번호 목록 (대주제 → 소주제: 핵심내용) ──
        if (tabType === 'summary' && currentH3 === '주요 과업 범위') {
            const groups = [], groupMap = new Map();
            body.forEach(row => {
                const major = (row[0] || '').trim();
                if (!major) return;
                if (!groupMap.has(major)) {
                    const g = { name: major, subs: [] };
                    groupMap.set(major, g);
                    groups.push(g);
                }
                const sub = (row[1] || '').trim();
                const content = (row[2] || '').trim();
                if (sub) groupMap.get(major).subs.push({ sub, content });
            });
            let t = '<div class="ai-scope-wrap">';
            groups.forEach((group, gi) => {
                t += `<div class="ai-scope-major">
                    <div class="ai-scope-major-title">
                        <span class="ai-scope-num">${gi + 1}</span>
                        <span>${escHtml(group.name)}</span>
                    </div>
                    <div class="ai-scope-subs">`;
                group.subs.forEach((sub, si) => {
                    t += `<div class="ai-scope-sub">
                        <span class="ai-scope-sub-num">${gi + 1}-${si + 1}.</span>
                        <span class="ai-scope-sub-name">${escHtml(sub.sub)}</span>
                        ${sub.content ? `<span class="ai-scope-sep"> · </span><span class="ai-scope-sub-content">${inlineMd(sub.content)}</span>` : ''}
                    </div>`;
                });
                t += '</div></div>';
            });
            t += '</div>';
            html += t;
            return;
        }

        // ── 정량 평가 세부 배점: 첫 번째 열 rowspan 그룹핑 ──
        if (tabType === 'proposal' && currentH3 === '정량 평가 세부 배점') {
            let t = `<div class="ai-table-wrap"><table class="ai-table"><thead><tr>`;
            t += header.map(c => `<th>${inlineMd(c)}</th>`).join('');
            t += `</tr></thead><tbody>`;
            // 빈 첫 번째 열은 이전 그룹에 포함 (rowspan 확장)
            const groups = [];
            body.forEach(row => {
                const label = (row[0] || '').trim();
                if (label && (groups.length === 0 || label !== (groups[groups.length-1].label))) {
                    groups.push({ label, rows: [row] });
                } else if (!label && groups.length > 0) {
                    groups[groups.length-1].rows.push(row);
                } else {
                    groups.push({ label, rows: [row] });
                }
            });
            groups.forEach(group => {
                const span = group.rows.length;
                group.rows.forEach((row, idx) => {
                    const isEmpty = (v) => !v || v === '-';
                    if (idx === 0) {
                        t += `<tr><td rowspan="${span}" class="ai-score-major-cell">${inlineMd(group.label)}</td>`;
                        t += row.slice(1).map(c => `<td>${isEmpty(c) ? '<span class="text-gray-300">-</span>' : inlineMd(c)}</td>`).join('');
                        t += `</tr>`;
                    } else {
                        t += `<tr>${row.slice(1).map(c => `<td>${isEmpty(c) ? '<span class="text-gray-300">-</span>' : inlineMd(c)}</td>`).join('')}</tr>`;
                    }
                });
            });
            t += `</tbody></table></div>`;
            html += t;
            return;
        }

        // ── 교육 과정별 상세 → 컴팩트 카드 + 상세 표 (kpi 탭, 표 형식) ──
        if (tabType === 'kpi' && currentH3 === '교육 과정별 상세') {
            const fc = (name) => header.findIndex(h => h.includes(name));
            const iName   = fc('과정명');
            const iHours  = fc('교육시간');
            const iCount  = fc('목표인원');
            const iPeriod = fc('교육기간');
            const iMode   = fc('교육방식');
            const iTarget = fc('교육대상');
            const isNone  = (v) => !v || v.trim() === '-' || v.trim() === '';
            // ① 컴팩트 카드
            html += '<div class="ai-course-grid">';
            body.forEach(row => {
                const name  = iName  >= 0 ? row[iName]  : '과정';
                const hours = iHours >= 0 ? row[iHours] : '-';
                const count = iCount >= 0 ? row[iCount] : '-';
                html += `<div class="ai-course-card">
                    <div class="ai-course-name">${escHtml(name)}</div>
                    <div class="ai-course-stats">
                        <span class="ai-course-stat">
                            <span class="ai-course-stat-icon">👥</span>
                            <span class="ai-course-stat-val">${escHtml(count)}</span>
                            <span class="ai-course-stat-label">명</span>
                        </span>
                        <span class="ai-course-stat-sep">·</span>
                        <span class="ai-course-stat">
                            <span class="ai-course-stat-icon">⏱</span>
                            <span class="ai-course-stat-val">${escHtml(hours)}</span>
                        </span>
                    </div>
                </div>`;
            });
            html += '</div>';
            // ② 상세 표
            const hasDetail = body.some(row =>
                (iPeriod >= 0 && !isNone(row[iPeriod])) ||
                (iMode   >= 0 && !isNone(row[iMode]))   ||
                (iTarget >= 0 && !isNone(row[iTarget]))
            );
            if (hasDetail) {
                html += `<div class="ai-course-detail-table ai-table-wrap"><table class="ai-table">
                    <thead><tr><th>과정명</th><th>교육기간</th><th>교육방식</th><th>교육대상</th></tr></thead><tbody>`;
                body.forEach(row => {
                    const period = iPeriod >= 0 ? row[iPeriod] : '';
                    const mode   = iMode   >= 0 ? row[iMode]   : '';
                    const target = iTarget >= 0 ? row[iTarget] : '';
                    html += `<tr>
                        <td>${escHtml(iName >= 0 ? row[iName] : '')}</td>
                        <td>${isNone(period) ? '<span class="text-gray-300">-</span>' : escHtml(period)}</td>
                        <td>${isNone(mode)   ? '<span class="text-gray-300">-</span>' : escHtml(mode)}</td>
                        <td>${isNone(target) ? '<span class="text-gray-300">-</span>' : escHtml(target)}</td>
                    </tr>`;
                });
                html += '</tbody></table></div>';
            }
            return;
        }

        let t = `<div class="ai-table-wrap"><table class="ai-table"><thead><tr>`;
        t += header.map(c => `<th>${inlineMd(c)}</th>`).join('');
        t += `</tr></thead><tbody>`;
        body.forEach(row => {
            t += `<tr>${row.map(c => `<td>${inlineMd(c)}</td>`).join('')}</tr>`;
        });
        t += `</tbody></table></div>`;
        html += t;
    }

    function flushList() {
        if (!listItems.length) return;
        const items = listItems;
        listItems = [];

        // ── [0] 교육 과정별 상세 → 컴팩트 카드 + 상세 표 (kpi 탭) ───────
        if (isKpi && currentH3 === '교육 과정별 상세') {
            const courses = [];
            let cur = null;
            items.forEach(item => {
                if (item.type !== 'info') return;
                if (item.key === '과정명') {
                    cur = { name: item.val, 교육시간:'-', 목표인원:'-', 교육기간:'', 교육방식:'', 교육대상:'' };
                    courses.push(cur);
                } else if (cur) {
                    if (['교육시간','목표인원','교육기간','교육방식','교육대상'].includes(item.key))
                        cur[item.key] = item.val;
                }
            });
            if (courses.length > 0) {
                const isNone = v => !v || v.trim() === '-' || v.trim() === '';
                // ① 컴팩트 카드: 과정명 + 목표인원 + 교육시간
                html += '<div class="ai-course-grid">';
                courses.forEach(c => {
                    html += `<div class="ai-course-card">
                        <div class="ai-course-name">${escHtml(c.name)}</div>
                        <div class="ai-course-stats">
                            <span class="ai-course-stat">
                                <span class="ai-course-stat-icon">👥</span>
                                <span class="ai-course-stat-val">${escHtml(c.목표인원)}</span>
                                <span class="ai-course-stat-label">명</span>
                            </span>
                            <span class="ai-course-stat-sep">·</span>
                            <span class="ai-course-stat">
                                <span class="ai-course-stat-icon">⏱</span>
                                <span class="ai-course-stat-val">${escHtml(c.교육시간)}</span>
                            </span>
                        </div>
                    </div>`;
                });
                html += '</div>';
                // ② 상세 표: 교육기간·교육방식·교육대상
                const hasDetail = courses.some(c => !isNone(c.교육기간) || !isNone(c.교육방식) || !isNone(c.교육대상));
                if (hasDetail) {
                    html += `<div class="ai-course-detail-table ai-table-wrap"><table class="ai-table">
                        <thead><tr><th>과정명</th><th>교육기간</th><th>교육방식</th><th>교육대상</th></tr></thead><tbody>`;
                    courses.forEach(c => {
                        html += `<tr>
                            <td>${escHtml(c.name)}</td>
                            <td>${isNone(c.교육기간) ? '<span class="text-gray-300">-</span>' : escHtml(c.교육기간)}</td>
                            <td>${isNone(c.교육방식) ? '<span class="text-gray-300">-</span>' : escHtml(c.교육방식)}</td>
                            <td>${isNone(c.교육대상) ? '<span class="text-gray-300">-</span>' : escHtml(c.교육대상)}</td>
                        </tr>`;
                    });
                    html += '</tbody></table></div>';
                }
                return;
            }
        }

        // summary 탭: 계약 기간·예산 규모는 상단 하이라이트 바에 표시됨 → 생략
        if (tabType === 'summary' && (currentH3 === '계약 기간' || currentH3 === '예산 규모')) return;

        // ── [1] 사업 목적 callout 카드 (summary 탭) ──────────────────
        if (tabType === 'summary' && currentH3 === '사업 목적') {
            const configs = [
                { cls:'ai-purpose-req',  icon:'🎯', label:'본질적 요구사항' },
                { cls:'ai-purpose-tgt',  icon:'👥', label:'대상자 및 기대 결과' },
                { cls:'ai-purpose-role', icon:'💼', label:'수행기관에 바라는 역할' },
            ];
            html += '<div class="ai-purpose-grid">';
            items.forEach((item, i) => {
                const cfg = configs[i] || configs[0];
                const lbl = item.type === 'info' ? item.key : cfg.label;
                const val = item.type === 'info' ? item.val : item.text;
                html += `<div class="ai-purpose-card ${cfg.cls}">
                    <div class="ai-purpose-label">${cfg.icon} ${escHtml(lbl)}</div>
                    <div class="ai-purpose-text">${inlineMd(val)}</div>
                </div>`;
            });
            html += '</div>';
            return;
        }

        // ── [2] 사업 구조 특이점 → 표 형식 (special 탭) ─────────────────
        if (tabType === 'special' && currentH3 === '사업 구조 특이점') {
            html += `<div class="ai-table-wrap"><table class="ai-table">
                <thead><tr><th style="width:9rem">항목</th><th>내용</th></tr></thead><tbody>`;
            items.forEach(item => {
                const key = item.type === 'info' ? item.key : '기타';
                const val = item.type === 'info' ? item.val : item.text;
                const isNone = /해당\s*없음/.test(val);
                // 마침표로 구분된 문장은 불릿으로 분리
                const sentences = isNone ? [val] : splitSentences(val);
                const cellHtml = sentences.length >= 2
                    ? `<ul class="ai-ul" style="margin:0;padding-left:1.1rem">${sentences.map(s => `<li>${inlineMd(s)}</li>`).join('')}</ul>`
                    : inlineMd(val);
                html += `<tr>
                    <td class="font-semibold text-gray-700 whitespace-nowrap">${escHtml(key)}</td>
                    <td class="${isNone ? 'ai-struct-none' : ''}">${cellHtml}</td>
                </tr>`;
            });
            html += '</tbody></table></div>';
            return;
        }

        // ── [3] 주요 일정 행 (special 탭) ────────────────────────────
        if (tabType === 'special' && currentH3 === '주요 일정') {
            html += '<ul class="ai-schedule-list">';
            items.forEach(item => {
                const key = item.type === 'info' ? item.key : '';
                const val = item.type === 'info' ? item.val : item.text;
                html += `<li class="ai-schedule-row">
                    <span class="ai-schedule-key">${escHtml(key)}</span>
                    <span class="ai-schedule-val">${inlineMd(val)}</span>
                </li>`;
            });
            html += '</ul>';
            return;
        }

        // ── [4-a] 참가 자격 요건 → 표 형식 (proposal 탭) ──────────────
        if (tabType === 'proposal' && currentH3 === '참가 자격 요건') {
            if (items.some(i => i.type === 'info')) {
                html += `<div class="ai-table-wrap"><table class="ai-table">
                    <thead><tr><th style="width:7rem">구분</th><th>내용</th></tr></thead><tbody>`;
                items.forEach(item => {
                    const key = item.type === 'info' ? item.key : '';
                    const val = item.type === 'info' ? item.val : item.text;
                    const isNone = /해당\s*없음/.test(val);
                    html += `<tr>
                        <td class="font-semibold whitespace-nowrap">${escHtml(key)}</td>
                        <td class="${isNone ? 'text-gray-400 italic' : ''}">${inlineMd(val)}</td>
                    </tr>`;
                });
                html += '</tbody></table></div>';
            } else {
                html += '<ul class="ai-qual-list">';
                items.forEach(item => {
                    html += `<li class="ai-qual-item">
                        <span class="ai-qual-icon">✓</span>
                        <span class="ai-qual-text">${inlineMd(item.text)}</span>
                    </li>`;
                });
                html += '</ul>';
            }
            return;
        }

        // ── [4-b] 실적/인력 요건 체크 리스트 (proposal 탭) ──────────────
        if (tabType === 'proposal' &&
            (currentH3 === '일반 자격' || currentH3 === '실적 요건' || currentH3 === '인력 요건')) {
            html += '<ul class="ai-qual-list">';
            items.forEach(item => {
                const text = item.type === 'info'
                    ? `<strong>${escHtml(item.key)}</strong>: ${inlineMd(item.val)}`
                    : inlineMd(item.text);
                html += `<li class="ai-qual-item">
                    <span class="ai-qual-icon">✓</span>
                    <span class="ai-qual-text">${text}</span>
                </li>`;
            });
            html += '</ul>';
            return;
        }

        // ── [5] KPI 탭: 카드 대신 전체 items를 표/리스트로 렌더링 ──────
        // 카드는 수치 값의 맥락(어떤 과정인지)을 잃게 하므로 사용하지 않음.
        // 반복 key 패턴(과정별 행)이 감지되면 buildAutoTable이 다열 표로 자동 변환.

        // ── [6] 일반 info 행 / 불릿 리스트 (기본 렌더링) ─────────────
        const renderItems = items;
        if (!renderItems.length) return;

        const allInfo = renderItems.every(i => i.type === 'info');
        if (allInfo) {
            // 반복 key 패턴 감지 → 다열 표로 자동 변환 (교육 과정 목록, 평가 배점 등)
            const autoTbl = buildAutoTable(renderItems, tabType);
            if (autoTbl) { html += autoTbl; return; }

            html += '<ul class="ai-info-list">';
            renderItems.forEach(({key, val}) => {
                html += `<li class="ai-info-row">
                    <span class="ai-info-key">${escHtml(key.replace(/_/g,' '))}</span>
                    <span class="ai-info-val">${inlineMd(val)}</span>
                </li>`;
            });
            html += '</ul>';
        } else {
            html += '<ul class="ai-ul">';
            renderItems.forEach(item => {
                if (item.type === 'info') {
                    html += `<li><strong>${escHtml(item.key.replace(/_/g,' '))}</strong>: ${inlineMd(item.val)}</li>`;
                } else {
                    // special 탭: 마침표로 구분된 문장을 개별 불릿으로 분리
                    if (tabType === 'special') {
                        const sentences = splitSentences(item.text);
                        sentences.forEach(s => { html += `<li>${inlineMd(s)}</li>`; });
                    } else {
                        html += `<li>${inlineMd(item.text)}</li>`;
                    }
                }
            });
            html += '</ul>';
        }
    }

    for (const line of lines) {
        // 표 행
        if (/^\s*\|/.test(line)) {
            flushList();
            const cells = line.split('|').slice(1,-1).map(c => c.trim());
            if (!cells.every(c => /^[-:\s]+$/.test(c))) tableRows.push(cells);
            continue;
        }
        if (tableRows.length && !/^\s*\|/.test(line)) flushTable();

        // ## 헤더
        const h2m = line.match(/^##\s+(.+)/);
        if (h2m) { flushList(); currentH3 = ''; html += `<div class="ai-h2">${inlineMd(h2m[1])}</div>`; continue; }

        // **subsection** 단독 줄 → h3 + 섹션 추적
        const h3m = line.match(/^\*\*([^*]+)\*\*\s*$/);
        if (h3m) {
            flushList();
            currentH3 = h3m[1].trim();
            // summary 탭: 계약 기간·예산 규모는 상단 하이라이트 바에 이미 표시됨 → 헤더 생략
            const skipHeader = tabType === 'summary' && (currentH3 === '계약 기간' || currentH3 === '예산 규모');
            if (!skipHeader) {
                html += `<div class="ai-h3">${escHtml(currentH3.replace(/_/g,' '))}</div>`;
            }
            continue;
        }

        // - 리스트 항목
        if (/^-\s+/.test(line)) {
            const content = line.slice(2).trim();
            const kv = content.match(/^\*\*([^*]+)\*\*[:：]\s*(.+)/);
            if (kv) {
                const val = kv[2].trim();
                listItems.push({ type:'info', key:kv[1], val, isKpi: isKpi && KPI_VAL_RE.test(val) });
            } else {
                // "키: 값" 형식 (볼드 없이) → info로 파싱
                const kvPlain = content.match(/^([^:：]+)[:：]\s*(.+)/);
                if (kvPlain && kvPlain[1].length < 20) {
                    listItems.push({ type:'info', key:kvPlain[1].trim(), val:kvPlain[2].trim(), isKpi:false });
                } else {
                    listItems.push({ type:'bullet', text: content });
                }
            }
            continue;
        }

        // 그 외
        flushList();
        if (!line.trim()) continue;
        html += `<p class="mb-1">${inlineMd(line)}</p>`;
    }

    flushTable();
    flushList();
    return html;
}

// ── AI 분석 실행 (비동기 폴링) ────────────────────────────────────────────────
let _pollTimer = null;
let _pollCount = 0;
const _POLL_INTERVAL = 3000;   // 3초마다 상태 확인
const _POLL_MAX      = 250;    // 최대 12.5분 대기 (5개 모델 × 90초 최악 = 7.5분 커버)
let _rpmTimer = null;
const _RPM_COUNTDOWN_SEC = 120; // RPM 타이머 2분
// 폴링 세대 번호: runAnalysis 호출마다 증가. 이전 세대의 in-flight fetch 응답이
// 늦게 도착해도 _showLoading/_showError를 호출하지 않도록 guard한다.
let _pollGeneration = 0;

function _clearRpmTimer() {
    if (_rpmTimer) { clearInterval(_rpmTimer); _rpmTimer = null; }
}

function _startRpmCountdown(tenderId) {
    _clearRpmTimer();
    const timerEl  = document.getElementById('rpm-countdown');
    const fillEl   = document.getElementById('rpm-progress-fill');
    // 절대 마감 시각(deadline) 기준으로 매번 남은 시간을 다시 계산한다.
    // 단순히 매초 1씩 빼는 방식은 백그라운드 탭에서 setInterval이 스로틀링되면
    // (브라우저가 비활성 탭의 타이머 호출 빈도를 줄임) tick()이 늦게/덜 호출되어
    // remaining이 실제 경과 시간을 따라가지 못하고 화면이 멈춘 것처럼 보이는 문제가 있었다.
    const deadline = Date.now() + _RPM_COUNTDOWN_SEC * 1000;

    function tick() {
        const remaining = Math.max(0, Math.round((deadline - Date.now()) / 1000));
        const m = Math.floor(remaining / 60);
        const s = remaining % 60;
        if (timerEl) timerEl.textContent = `${m}:${s.toString().padStart(2,'0')}`;
        const pct = (remaining / _RPM_COUNTDOWN_SEC) * 100;
        if (fillEl) fillEl.style.width = pct + '%';
        if (timerEl) {
            if (remaining <= 10) timerEl.classList.add('ai-rpm-expiring');
            else                 timerEl.classList.remove('ai-rpm-expiring');
        }
        if (remaining <= 0) {
            _clearRpmTimer();
            // 재시도 호출 실패(네트워크 오류 등) 시 조용히 멈추지 않고 에러로 표시
            runAnalysis(tenderId, true).catch(err => {
                console.error('RPM 자동 재시도 실패:', err);
                _showError('자동 재시도 중 오류: ' + err.message, tenderId);
            });
        }
    }
    tick();
    _rpmTimer = setInterval(tick, 1000);
}

function _showError(errMsg, tenderId) {
    // 반드시 타이머 중단 후 두 박스 모두 숨긴 뒤 필요한 것 하나만 표시
    _clearRpmTimer();
    document.getElementById('analysis-loading').classList.add('hidden');
    document.getElementById('analysis-result').classList.add('hidden');
    document.getElementById('rpm-error-box').classList.add('hidden');
    document.getElementById('general-error-box').classList.add('hidden');

    document.getElementById('analysis-error').classList.remove('hidden');
    const isRpm = errMsg.startsWith('[RPM]');
    if (isRpm) {
        // RPM 박스: 타이머 초기화 후 표시
        const timerEl = document.getElementById('rpm-countdown');
        if (timerEl) { timerEl.textContent = '2:00'; timerEl.classList.remove('ai-rpm-expiring'); }
        const fillEl = document.getElementById('rpm-progress-fill');
        if (fillEl) fillEl.style.width = '100%';
        document.getElementById('rpm-error-box').classList.remove('hidden');
        _startRpmCountdown(tenderId);
    } else {
        // 일반 오류 박스만 표시 — 타이머 박스는 건드리지 않음
        document.getElementById('general-error-box').classList.remove('hidden');
        document.getElementById('analysis-error-msg').textContent = errMsg;
    }
}

function _showLoading(msg) {
    _clearRpmTimer();
    document.querySelector('#analysis-loading p.font-medium').textContent = msg || '첨부파일을 다운로드하고 분석 중입니다…';
    document.getElementById('analysis-loading').classList.remove('hidden');
    document.getElementById('analysis-result').classList.add('hidden');
    document.getElementById('analysis-error').classList.add('hidden');
    document.getElementById('rpm-error-box').classList.add('hidden');
    document.getElementById('general-error-box').classList.add('hidden');
}

async function _pollResult(tenderId, generation) {
    try {
        const resp = await fetch(`/api/tender/${tenderId}/analyze`);
        const data = await resp.json();

        // 이전 세대의 stale 응답 무시 (카운트다운 시작 후 오래된 fetch가 돌아오는 경우 방지)
        if (generation !== _pollGeneration) return;

        if (data.status === 'processing') {
            _pollCount++;
            const elapsed = Math.round(_pollCount * _POLL_INTERVAL / 1000);
            _showLoading(`분석 중… (${elapsed}초 경과, 자동으로 결과를 불러옵니다)`);
            if (_pollCount < _POLL_MAX) {
                _pollTimer = setTimeout(() => _pollResult(tenderId, generation), _POLL_INTERVAL);
            } else {
                _showError('분석 시간이 초과됐습니다. 잠시 후 페이지를 새로고침하거나 다시 분석을 눌러주세요.', tenderId);
                _resetBtn(tenderId);
            }
            return;
        }

        // 결과 수신 완료
        clearTimeout(_pollTimer);
        document.getElementById('analysis-loading').classList.add('hidden');
        if (data.error) {
            _showError(data.error, tenderId);
            _resetBtn(tenderId);
            return;
        }
        _renderResult(data, tenderId);

    } catch (err) {
        if (generation !== _pollGeneration) return;
        clearTimeout(_pollTimer);
        _showError('결과 확인 중 오류: ' + err.message, tenderId);
        _resetBtn(tenderId);
    }
}

function _resetBtn(tenderId) {
    const btn = document.getElementById('analyze-btn');
    btn.disabled = false;
    btn.textContent = '다시 분석';
    btn.onclick = () => runAnalysis(tenderId, true);
}

async function runAnalysis(tenderId, force = false) {
    const btn         = document.getElementById('analyze-btn');
    const placeholder = document.getElementById('analysis-placeholder');

    clearTimeout(_pollTimer);
    _pollCount = 0;
    _pollGeneration++;                        // 세대 증가 → 이전 in-flight 응답 무효화
    const myGeneration = _pollGeneration;

    btn.disabled = true;
    btn.textContent = force ? '재분석 요청 중…' : '분석 요청 중…';
    document.getElementById('analysis-body').style.padding = '';
    placeholder.classList.add('hidden');
    _showLoading('분석 요청을 보내는 중입니다…');

    try {
        const url = `/api/tender/${tenderId}/analyze` + (force ? '?force=1' : '');
        const resp = await fetch(url);
        const data = await resp.json();

        if (data.status === 'processing') {
            // 백그라운드 분석 시작됨 → 폴링 개시
            btn.textContent = '분석 중…';
            _showLoading(data.message || '분석 중입니다. 자동으로 결과를 불러옵니다…');
            _pollTimer = setTimeout(() => _pollResult(tenderId, myGeneration), _POLL_INTERVAL);
            return;
        }

        // 즉시 결과 반환 (캐시 hit)
        document.getElementById('analysis-loading').classList.add('hidden');

        if (data.error) {
            _showError(data.error, tenderId);
            _resetBtn(tenderId);
            return;
        }

        _renderResult(data, tenderId);

    } catch (err) {
        document.getElementById('analysis-loading').classList.add('hidden');
        _showError('분석 요청 중 오류: ' + err.message, tenderId);
        _resetBtn(tenderId);
    }
}

function _renderResult(data, tenderId) {
    const resultDiv = document.getElementById('analysis-result');

        // 발견 파일
        if (data.files_found && data.files_found.length > 0) {
            document.getElementById('files-list').innerHTML = data.files_found
                .map(n => `<span class="text-xs bg-gray-100 text-gray-700 px-2 py-1 rounded border">${safeHtml(n)}</span>`)
                .join('');
            document.getElementById('files-section').classList.remove('hidden');
        }

        // 캐시 / 모델 배지
        if (data.cached) {
            const cb = document.getElementById('cache-badge');
            cb.classList.remove('hidden');
            if (data.cached_at) cb.title = '캐시일시: ' + data.cached_at;
        }

        // Gemini 4개 섹션 탭
        const gs = data.gemini_sections;
        if (gs && !gs.error) {
            if (gs._model) {
                const mb = document.getElementById('model-badge');
                mb.textContent = '🤖 ' + gs._model;
                mb.classList.remove('hidden');
            }
            document.getElementById('tab-summary').innerHTML  = mdToHtml(gs.summary  || '', 'summary');
            document.getElementById('tab-kpi').innerHTML      = mdToHtml(gs.kpi      || '', 'kpi');
            document.getElementById('tab-proposal').innerHTML = mdToHtml(gs.proposal_requirements || '', 'proposal');
            document.getElementById('tab-special').innerHTML  = mdToHtml(gs.special_notes || '', 'special');
            document.getElementById('gemini-tabs').classList.remove('hidden');
            switchTab('summary');
        } else if (gs && gs.error) {
            // 구 캐시 레코드처럼 data.error가 없고 gemini_sections.error에만 오류가 있는 경우 대응.
            // _showError를 통해 올바른 박스 표시 + 버튼 활성화 + [RPM]이면 카운트다운 시작
            _showError(gs.error, tenderId);
            _resetBtn(tenderId);
            return;
        } else {
            // gemini_sections가 null — 이전 캐시에 API 키 없이 저장된 경우
            // 사용자가 분석 버튼을 이미 눌렀으므로, force=true로 자동 재분석
            if (data.cached && !data.error) {
                runAnalysis(tenderId, true);
                return;
            }
            document.getElementById('no-gemini-notice').classList.remove('hidden');
        }

        // 계약기간 / 예산 하이라이트 카드
        {
            const re = data.rule_extract || {};
            const fromSummary = extractKeyFromSummary(gs?.summary);
            let showBar = false;

            // fromSummary(Gemini 마크다운)을 우선 사용 — rule_extract는 HWP 원문을 길게 포함해
            // "계약체결일 ~ 날짜까지 라. 소요예산 : ..." 같은 잡음이 붙을 수 있음
            const reContract = re['계약기간'];
            const contractRaw = fromSummary.contract
                || (reContract && reContract.length <= 80 ? reContract : null)
                || reContract;
            if (contractRaw) {
                document.getElementById('key-contract-val').textContent = normalizeContract(contractRaw);
                document.getElementById('key-contract').classList.remove('hidden');
                showBar = true;
            }

            const reBudget = re['예산'];
            const budgetRaw = (reBudget && /\d/.test(reBudget)) ? reBudget : fromSummary.budget;
            if (budgetRaw) {
                document.getElementById('key-budget-val').textContent = normalizeBudget(budgetRaw);
                document.getElementById('key-budget').classList.remove('hidden');
                showBar = true;
            }

            if (showBar) document.getElementById('key-info-bar').classList.remove('hidden');

            const labels = { '사업목적': '사업 목적', '과업범위': '과업 범위', '참가자격': '참가 자격' };
            const rest = Object.entries(re).filter(([k]) => k !== '계약기간' && k !== '예산');
            if (rest.length > 0) {
                document.getElementById('rule-extract').innerHTML = rest
                    .map(([k, v]) =>
                        `<div class="bg-white rounded-lg p-3 border">
                            <p class="text-xs font-semibold text-gray-400 mb-1">${safeHtml(labels[k] || k)}</p>
                            <p class="text-sm text-gray-800">${safeHtml(v)}</p>
                        </div>`)
                    .join('');
                document.getElementById('rule-section').classList.remove('hidden');
            }
        }

        resultDiv.classList.remove('hidden');
        _resetBtn(tenderId);
}
