/* 입찰동향 발송 조건 설정
 *
 * 이 화면의 핵심은 "조건을 바꾸면 지금 몇 건이 걸리는지"를 즉시 보여주는 것이다.
 * 적정성 검토가 나머지 모든 작업의 전제이므로, 저장하지 않고도 미리보기가 된다.
 */

const CLASS_INFO = {
    A: { label: '기업이 직접 신청 가능한 지원사업', color: 'bg-green-500' },
    B: { label: '발주기관이 용역업체를 찾는 입찰', color: 'bg-gray-400' },
    C: { label: '행정공시·취소·기타', color: 'bg-gray-300' },
};

let KW = { in: [], ex: [] };
let CLASSES = [];

function esc(s) {
    return String(s ?? '').replace(/[&<>"]/g, c =>
        ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}

let toastTimer;
function toast(msg, isError) {
    const t = document.getElementById('toast');
    t.textContent = msg;
    t.className = t.className.replace(/bg-\w+-\d+/, isError ? 'bg-red-600' : 'bg-gray-900');
    t.classList.remove('hidden');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => t.classList.add('hidden'), 3400);
}

async function api(url, opts) {
    const r = await fetch(url, opts);
    let d = null;
    try { d = await r.json(); } catch (e) { /* 본문 없음 */ }
    if (!r.ok) throw new Error((d && d.error) || `HTTP ${r.status}`);
    return d;
}

/* ── 태그 ─────────────────────────────────────────────── */

function renderTags() {
    for (const k of ['in', 'ex']) {
        const cls = k === 'in'
            ? 'bg-green-100 text-green-800 border-green-200'
            : 'bg-red-100 text-red-800 border-red-200';
        const box = document.getElementById(`tags-${k}`);
        box.innerHTML = KW[k].length
            ? KW[k].map((w, i) =>
                `<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs
                    font-medium border ${cls}">${esc(w)}
                    <button type="button" class="opacity-50 hover:opacity-100 text-sm leading-none"
                            onclick="delTag('${k}',${i})">&times;</button></span>`).join('')
            : '<span class="text-xs text-gray-400 self-center">비어 있음</span>';
    }
}

function addTag(k) {
    const el = document.getElementById(`${k}-input`);
    const v = el.value.trim();
    if (v && !KW[k].includes(v)) KW[k].push(v);
    el.value = '';
    renderTags();
    runPreview();
}

function delTag(k, i) {
    KW[k].splice(i, 1);
    renderTags();
    runPreview();
}

/* ── 분류 옵션 ────────────────────────────────────────── */

function renderClassOpts(counts) {
    const el = document.getElementById('class-opts');
    el.innerHTML = Object.entries(CLASS_INFO).map(([k, v]) => {
        const n = counts ? (counts[k] ?? 0) : null;
        return `<label class="flex items-center gap-2 text-sm cursor-pointer">
            <input type="checkbox" value="${k}" ${CLASSES.includes(k) ? 'checked' : ''}
                   onchange="toggleClass('${k}',this.checked)" class="w-4 h-4">
            <span class="font-semibold text-gray-700 w-4">${k}</span>
            <span class="text-gray-600">${v.label}</span>
            ${n !== null ? `<span class="text-xs text-gray-400">${n}건</span>` : ''}
        </label>`;
    }).join('') +
    `<p class="text-xs text-gray-500 pt-1">
        아무것도 선택하지 않으면 분류를 무시하고 키워드 결과를 모두 사용합니다.</p>`;
}

function toggleClass(k, on) {
    CLASSES = on ? [...new Set([...CLASSES, k])] : CLASSES.filter(x => x !== k);
    runPreview();
}

/* ── 조건 수집 ────────────────────────────────────────── */

function num(id) {
    const v = document.getElementById(id).value;
    return v === '' ? null : Number(v);
}

function config() {
    const minP = num('min-price');
    return {
        include_keywords: KW.in,
        exclude_keywords: KW.ex,
        classes: CLASSES,
        days_ahead: num('days-ahead'),
        min_price: minP === null ? null : Math.round(minP * 1e8),
        max_price: null,
        limit: num('limit') || 8,
    };
}

/* ── 미리보기 ─────────────────────────────────────────── */

let previewTimer;
function runPreview() {
    clearTimeout(previewTimer);
    previewTimer = setTimeout(doPreview, 250);   // 타이핑 중 과도한 호출 방지
}

async function doPreview() {
    const days = Number(document.getElementById('days').value);
    try {
        const pv = await api('/api/brief/preview', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ...config(), days }),
        });
        renderFunnel(pv);
        renderClassOpts(pv.class_counts);
        renderResult(pv);
    } catch (e) {
        toast(e.message, true);
    }
}

function step(label, value, tone) {
    const cls = tone === 'good' ? 'text-green-700'
              : tone === 'warn' ? 'text-amber-700' : 'text-gray-700';
    return `<span class="inline-flex items-baseline gap-1">
        <span class="text-xs text-gray-500">${label}</span>
        <b class="text-base ${cls}">${value.toLocaleString()}</b></span>`;
}

function renderFunnel(pv) {
    const arrow = '<span class="text-gray-300">&rarr;</span>';
    document.getElementById('funnel').innerHTML = [
        step(`최근 ${pv.days}일 수집`, pv.total_collected),
        arrow,
        step('키워드 통과', pv.passed_keywords),
        arrow,
        step('분류 부합', pv.items_all, pv.items_all >= 3 ? 'good' : 'warn'),
        arrow,
        step('메일 게재', Math.min(pv.items_all, pv.limit)),
    ].join(' ');

    // 분류 분포 막대
    const c = pv.class_counts || {};
    const total = Object.values(c).reduce((a, b) => a + b, 0) || 1;
    const seg = (k, color) => {
        const n = c[k] || 0;
        if (!n) return '';
        return `<div class="${color} h-full" style="width:${n / total * 100}%"
                     title="${k}: ${n}건"></div>`;
    };
    document.getElementById('class-bar').innerHTML = `
        <div class="flex h-2 rounded overflow-hidden bg-gray-100">
            ${seg('A', 'bg-green-500')}${seg('B', 'bg-gray-400')}
            ${seg('C', 'bg-gray-300')}${seg('미분류', 'bg-amber-300')}
        </div>
        <div class="flex flex-wrap gap-3 mt-1.5 text-xs text-gray-500">
            <span><span class="inline-block w-2 h-2 bg-green-500 rounded-sm"></span> A ${c.A || 0}</span>
            <span><span class="inline-block w-2 h-2 bg-gray-400 rounded-sm"></span> B ${c.B || 0}</span>
            <span><span class="inline-block w-2 h-2 bg-gray-300 rounded-sm"></span> C ${c.C || 0}</span>
            <span><span class="inline-block w-2 h-2 bg-amber-300 rounded-sm"></span> 미분류 ${c['미분류'] || 0}</span>
        </div>`;

    const un = c['미분류'] || 0;
    const warn = document.getElementById('unclassified-warn');
    if (un > 0) {
        warn.classList.remove('hidden');
        document.getElementById('unclassified-msg').textContent =
            `분류되지 않은 공고 ${un}건이 있어 분류 조건이 적용되지 않습니다.`;
    } else {
        warn.classList.add('hidden');
    }
}

function renderResult(pv) {
    document.getElementById('result-count').textContent =
        `조건 부합 ${pv.items_all}건 중 상위 ${pv.items.length}건`;
    const el = document.getElementById('result-list');
    if (!pv.items.length) {
        el.innerHTML = '<p class="text-sm text-gray-400 py-4 text-center">' +
            '조건에 맞는 공고가 없습니다. 키워드를 넓히거나 분류 조건을 풀어보세요.</p>';
        return;
    }
    el.innerHTML = pv.items.map((it, i) => `
        <div class="flex items-start gap-2 pb-2 border-b border-gray-100 last:border-0">
            <span class="text-xs text-gray-400 pt-0.5 w-5 text-right shrink-0">${i + 1}</span>
            <span class="text-xs font-bold px-1.5 py-0.5 rounded shrink-0
                  ${it.class === 'A' ? 'bg-green-100 text-green-800' : 'bg-gray-100 text-gray-600'}">
                  ${it.class || '?'}</span>
            <div class="min-w-0 flex-1">
                <div class="text-sm text-gray-800 leading-snug">
                    ${it.url ? `<a href="${esc(it.url)}" target="_blank" class="hover:underline">${esc(it.title)}</a>`
                             : esc(it.title)}
                </div>
                <div class="text-xs text-gray-500 mt-0.5">
                    ${esc(it.agency)} · ${it.price ? it.price + '억' : '금액 미공개'}
                    · 마감 ${esc(it.deadline || '미정')}
                    ${it.hr_related ? '<span class="text-blue-600 ml-1">HR</span>' : ''}
                </div>
            </div>
        </div>`).join('');
}

/* ── 분류 실행 ────────────────────────────────────────── */

async function classifyNow() {
    const btn = document.getElementById('btn-classify');
    btn.disabled = true;
    btn.textContent = '분류 중... (수십 초)';
    try {
        const days = Number(document.getElementById('days').value);
        const res = await api('/api/brief/classify', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ...config(), days }),
        });
        toast(`${res.classified}건 분류 완료 (API ${res.api_calls}회)`);
        renderFunnel(res.preview);
        renderClassOpts(res.preview.class_counts);
        renderResult(res.preview);
    } catch (e) {
        toast(e.message, true);
    } finally {
        btn.disabled = false;
        btn.textContent = '지금 분류';
    }
}

/* ── 저장·이력 ────────────────────────────────────────── */

async function savePreset() {
    const btn = document.getElementById('btn-save');
    btn.disabled = true;
    try {
        const p = await api('/api/brief/preset', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(config()),
        });
        document.getElementById('saved-info').textContent =
            `최종 저장 ${p.updated_at?.slice(0, 16).replace('T', ' ') || ''}` +
            (p.updated_by ? ` · ${p.updated_by}` : '');
        toast('조건을 저장했습니다.');
        loadHistory();
    } catch (e) {
        toast(e.message, true);
    } finally {
        btn.disabled = false;
    }
}

async function loadHistory() {
    try {
        const rows = await api('/api/brief/history');
        const el = document.getElementById('history');
        if (!rows.length) { el.textContent = '변경 이력 없음'; return; }
        el.innerHTML = rows.slice(0, 8).map(h => {
            const c = h.config || {};
            return `<div>${esc(h.changed_at.slice(0, 16).replace('T', ' '))}
                · ${esc(h.changed_by || '-')}
                · 관심 ${(c.include_keywords || []).length}개
                · 제외 ${(c.exclude_keywords || []).length}개
                · 분류 [${(c.classes || []).join(',') || '전체'}]
                · 게재 ${c.limit ?? '-'}건</div>`;
        }).join('');
    } catch (e) { /* 이력 실패는 무시 */ }
}

/* ── 초기화 ───────────────────────────────────────────── */

async function init() {
    const p = await api('/api/brief/preset');
    KW.in = p.include_keywords || [];
    KW.ex = p.exclude_keywords || [];
    CLASSES = p.classes || [];
    document.getElementById('days-ahead').value = p.days_ahead ?? '';
    document.getElementById('min-price').value =
        p.min_price ? (p.min_price / 1e8) : '';
    document.getElementById('limit').value = p.limit ?? 8;
    document.getElementById('saved-info').textContent =
        `최종 저장 ${p.updated_at?.slice(0, 16).replace('T', ' ') || ''}` +
        (p.updated_by ? ` · ${p.updated_by}` : '');

    renderTags();
    renderClassOpts(null);
    for (const k of ['in', 'ex']) {
        document.getElementById(`${k}-input`).addEventListener('keydown', e => {
            if (e.key === 'Enter') { e.preventDefault(); addTag(k); }
        });
    }
    for (const id of ['days-ahead', 'min-price', 'limit']) {
        document.getElementById(id).addEventListener('input', runPreview);
    }
    await doPreview();
    loadHistory();
}

document.addEventListener('DOMContentLoaded', () => {
    init().catch(e => toast(e.message, true));
});
