// 놓친 공고 화면 (templates/cases.html): 신고·진단, 채점, 사례 점수 정렬.
// 외부에서 온 글자(공고 제목 등)는 반드시 safeHtml() 을 거쳐 넣는다 (common.js).

const SECTION_LABELS = {
    pre_tenders: '사전규격', urgent_tenders: '신규공고(나라장터)', recent_tenders: '신규공고(기타 채널)',
};
const VERDICT_STYLE = {
    '수집 안 됨': 'bg-gray-100 text-gray-700',
    '묶임': 'bg-gray-100 text-gray-700',
    '걸러짐': 'bg-red-50 text-red-700',
    '순위 낮음': 'bg-amber-50 text-amber-800',
    '표시 범위 안': 'bg-green-50 text-green-700',
};

async function api(url, opts = {}) {
    const res = await fetch(url, {
        headers: {'Content-Type': 'application/json'}, ...opts,
        body: opts.body ? JSON.stringify(opts.body) : undefined,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
        const err = new Error(data.error || data.reason || `HTTP ${res.status}`);
        err.status = res.status; err.data = data;
        throw err;
    }
    return data;
}

// ── 놓친 공고 신고 ──────────────────────────────────────────────────────────

let lastQuery = '';

async function lookupMissed(ev) {
    ev.preventDefault();
    const q = document.getElementById('missed-q').value.trim();
    const box = document.getElementById('missed-candidates');
    document.getElementById('missed-result').innerHTML = '';
    if (!q) { box.innerHTML = '<p class="text-sm text-red-600">공고번호·주소·제목을 넣어 주세요.</p>'; return; }
    lastQuery = q;
    box.innerHTML = '<p class="text-sm text-gray-400">찾는 중…</p>';
    try {
        const {candidates} = await api('/api/missed/lookup', {method: 'POST', body: {q}});
        if (!candidates.length) {
            box.innerHTML = `
                <div class="rounded-lg border border-gray-200 p-3 text-sm space-y-2">
                    <p><span class="px-2 py-0.5 rounded ${VERDICT_STYLE['수집 안 됨']}">수집 안 됨</span>
                       우리 DB 에 없는 공고입니다. 어디서 보셨는지 남겨 주시면 수집 사이트를 늘릴 때 참고합니다.</p>
                    <div class="flex gap-2">
                        <input id="source-note" type="text" placeholder="예: OO진흥원 홈페이지 공지사항"
                               class="flex-1 min-w-0 border border-gray-300 rounded-lg px-3 py-1.5">
                        <button onclick="reportNotFound(this)" class="shrink-0 border border-gray-300 rounded-lg px-3 py-1.5 hover:bg-gray-50">기록</button>
                    </div>
                </div>`;
            return;
        }
        box.innerHTML = `<p class="text-xs text-gray-500">어느 공고인가요? (${candidates.length}건)</p>` +
            candidates.map(c => `
                <button onclick="diagnose(${c.id})" class="w-full text-left text-sm border border-gray-200 rounded-lg px-3 py-2 hover:bg-orange-50">
                    <span class="block truncate">${safeHtml(c.title)}</span>
                    <span class="text-xs text-gray-500">${safeHtml(c.source_site)} · ${safeHtml(c.status || '')} · ${safeHtml(c.created_at.replace('T', ' '))} 수집</span>
                </button>`).join('');
    } catch (e) {
        box.innerHTML = `<p class="text-sm text-red-600">${safeHtml(e.message)}</p>`;
    }
}

async function reportNotFound(btn) {
    btn.disabled = true;
    const note = document.getElementById('source-note').value.trim();
    try {
        await api('/api/missed/diagnose', {method: 'POST', body: {q: lastQuery, source_note: note}});
        btn.textContent = '기록됨';
        loadEval();
    } catch (e) {
        btn.disabled = false;
        alert('기록하지 못했습니다: ' + e.message);
    }
}

async function diagnose(tenderId) {
    const out = document.getElementById('missed-result');
    out.innerHTML = '<p class="text-sm text-gray-400">진단하는 중…</p>';
    try {
        const r = await api('/api/missed/diagnose', {method: 'POST', body: {tender_id: tenderId, q: lastQuery}});
        document.getElementById('missed-candidates').innerHTML = '';
        out.innerHTML = renderVerdict(r);
        loadEval();
    } catch (e) {
        out.innerHTML = `<p class="text-sm text-red-600">${safeHtml(e.message)}</p>`;
    }
}

function renderVerdict(r) {
    const style = VERDICT_STYLE[r.verdict] || 'bg-gray-100 text-gray-700';
    const section = r.section ? SECTION_LABELS[r.section] || r.section : '-';
    let detail = '';
    if (r.rank) {
        detail = `<p>${safeHtml(section)} 구역, 같은 시점 관심 키워드 통과 공고 ${r.pool}건 중 <b>${r.rank}등</b> (${Number(r.score).toFixed(1)}점, 대시보드에는 15등까지 나옵니다)</p>
            <table class="text-xs text-gray-600 mt-1"><tbody>
                <tr><td class="pr-3">키워드</td><td class="text-right">${r.breakdown.keyword}</td></tr>
                <tr><td class="pr-3">유형</td><td class="text-right">${r.breakdown.type}</td></tr>
                <tr><td class="pr-3">기관</td><td class="text-right">${r.breakdown.agency}</td></tr>
            </tbody></table>`;
    }
    const reasons = (r.reasons || []).length
        ? `<ul class="list-disc pl-5 text-sm">${r.reasons.map(x => `<li>${safeHtml(x)}</li>`).join('')}</ul>` : '';
    const addBtn = r.is_case
        ? '<span class="text-xs text-green-700">이미 정답 목록에 있습니다</span>'
        : `<button onclick="addCase(${r.tender.id}, this)" class="text-sm bg-[color:var(--hs-brand)] text-white rounded-lg px-3 py-1.5 hover:bg-[#E84E0B]">정답 목록에 넣기</button>`;
    return `
        <div class="rounded-lg border border-gray-200 p-3 space-y-2 text-sm">
            <p class="font-medium truncate"><a href="/tender/${r.tender.id}" target="_blank" rel="noopener" class="hover:underline">${safeHtml(r.tender.title)}</a></p>
            <p class="text-xs text-gray-500">${safeHtml(r.tender.source_site)} · ${safeHtml(r.as_of.replace('T', ' '))} 수집 시점 기준</p>
            <p><span class="px-2 py-0.5 rounded ${style}">${safeHtml(r.verdict)}</span></p>
            ${reasons}${detail}
            <div class="pt-1">${addBtn}</div>
        </div>`;
}

async function addCase(tenderId, btn) {
    btn.disabled = true;
    try {
        const r = await api('/api/cases', {method: 'POST', body: {tender_id: tenderId, source: 'report'}});
        btn.outerHTML = `<span class="text-xs text-green-700">정답 목록에 넣었습니다 (사례 ${r.cases}건)</span>`;
        loadEval();
    } catch (e) {
        btn.disabled = false;
        alert('넣지 못했습니다: ' + e.message);
    }
}

// ── 채점 ────────────────────────────────────────────────────────────────────

function fmtRank(m) {
    return (m && m.median !== null && m.median !== undefined) ? `${Number(m.median).toFixed(0)}등` : '-';
}

function metricTable(title, block) {
    const row = (name, m) => `<tr class="border-t">
        <td class="py-1 pr-3">${name}</td><td class="text-right pr-3">${fmtRank(m)}</td>
        <td class="text-right pr-3">${m ? m.top100 : '-'}</td><td class="text-right pr-3">${m ? m.top500 : '-'}</td>
        <td class="text-right">${m ? m.n : '-'}</td></tr>`;
    return `<div class="overflow-x-auto"><p class="text-xs font-medium text-gray-600 mb-1">${title}</p>
        <table class="w-full text-sm"><thead class="text-xs text-gray-500"><tr>
            <th class="text-left font-normal">방식</th><th class="text-right font-normal pr-3">순위 중앙값</th>
            <th class="text-right font-normal pr-3">100등 안</th><th class="text-right font-normal pr-3">500등 안</th>
            <th class="text-right font-normal">정답 수</th></tr></thead>
        <tbody>${row('현재 방식', block.current)}${row('사례 방식', block.case)}</tbody></table></div>`;
}

async function loadEval() {
    try {
        const d = await api('/api/cases/eval');
        const latest = document.getElementById('eval-latest');
        if (!d.latest) {
            latest.innerHTML = `아직 채점한 적이 없습니다. 지금 사례 ${d.cases}건${d.cases < d.min_cases ? ` (사례 방식은 ${d.min_cases}건부터 계산합니다)` : ''}.`;
        } else {
            const m = d.latest.metrics;
            latest.innerHTML = `<p class="text-xs text-gray-500 mb-2">${safeHtml(d.latest.run_at.replace('T', ' '))} 채점 · 정답 ${m.answers}건${m.missing_vectors ? ` · 비교에서 뺀 공고 ${m.missing_vectors}건(제목 벡터 없음)` : ''}</p>
                <div class="grid gap-4 md:grid-cols-2">
                    ${metricTable('관심 키워드를 통과한 공고 중 (정렬 전환 판정 기준)', m.filtered)}
                    ${metricTable('전체 공고 중 (키워드에 없는 정답은 현재 방식에서 맨 뒤)', m.all)}
                </div>`;
        }
        document.getElementById('eval-history').innerHTML = d.history.length > 1
            ? `<p class="text-xs font-medium text-gray-600 mb-1">지난 채점 (관심 키워드 통과 기준 순위 중앙값)</p>
               <ul class="text-xs text-gray-600 space-y-0.5">${d.history.map(h => `<li>${safeHtml(h.run_at.replace('T', ' '))} — 현재 ${fmtRank(h.metrics.filtered && h.metrics.filtered.current)} / 사례 ${fmtRank(h.metrics.filtered && h.metrics.filtered.case)} (정답 ${h.metrics.answers}건)</li>`).join('')}</ul>`
            : '';
        const counts = Object.entries(d.report_counts || {});
        document.getElementById('report-counts').innerHTML = counts.length
            ? `<p class="text-xs font-medium text-gray-600 mb-1">신고 판정별 건수</p>
               <p class="text-sm">${counts.map(([k, v]) => `${safeHtml(k)} ${v}건`).join(' · ')}</p>`
            : '';
    } catch (e) {
        document.getElementById('eval-latest').textContent = '채점 결과를 불러오지 못했습니다: ' + e.message;
    }
}

async function runEval() {
    const btn = document.getElementById('eval-run');
    btn.disabled = true; btn.textContent = '채점 중… (1분 넘게 걸릴 수 있습니다)';
    try {
        await api('/api/cases/eval', {method: 'POST'});
        await loadEval();
        await loadSort();
    } catch (e) {
        alert('채점하지 못했습니다: ' + e.message);
    } finally {
        btn.disabled = false; btn.textContent = '지금 채점';
    }
}

// ── 사례 점수로 정렬 ────────────────────────────────────────────────────────

function showSort(s) {
    const t = document.getElementById('sort-toggle');
    t.checked = s.enabled;
    t.disabled = !s.enabled && !s.allowed;
    document.getElementById('sort-reason').textContent = s.enabled ? '켜져 있습니다.' : (s.reason || '켤 수 있습니다.');
}

async function loadSort() {
    try { showSort(await api('/api/cases/sort-setting')); }
    catch (e) { document.getElementById('sort-reason').textContent = '설정을 불러오지 못했습니다.'; }
}

async function toggleSort(el) {
    try {
        showSort(await api('/api/cases/sort-setting', {method: 'POST', body: {enabled: el.checked}}));
    } catch (e) {
        el.checked = !el.checked;
        document.getElementById('sort-reason').textContent = e.message;
    }
}

document.addEventListener('DOMContentLoaded', () => { loadEval(); loadSort(); });
