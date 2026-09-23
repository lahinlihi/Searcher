/* 뉴스레터 검수 — 시사점 확인·수정·승인
 *
 * 승인 게이트 화면. 검사에 걸린 항목은 서버가 승인을 거부하므로
 * 클라이언트에서도 승인 버튼을 잠가 두 층에서 막는다.
 */

let RUN_DATE = null;
let ITEMS = [];

const STATUS_LABEL = {
    pending:  { text: '검토 대기', cls: 'bg-amber-100 text-amber-800 border-amber-200' },
    approved: { text: '승인됨',   cls: 'bg-green-100 text-green-800 border-green-200' },
    skipped:  { text: '제외됨',   cls: 'bg-gray-100 text-gray-600 border-gray-200' },
};

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
    toastTimer = setTimeout(() => t.classList.add('hidden'), 3200);
}

async function api(url, opts) {
    const r = await fetch(url, opts);
    let data = null;
    try { data = await r.json(); } catch (e) { /* 본문 없음 */ }
    if (!r.ok) throw new Error((data && data.error) || `HTTP ${r.status}`);
    return data;
}

/* ── 로딩 ─────────────────────────────────────────────── */

async function loadRuns() {
    const runs = await api('/api/newsletter/runs');
    const sel = document.getElementById('run-select');
    if (!runs.length) {
        sel.innerHTML = '<option value="">생성된 시사점 없음</option>';
        document.getElementById('insight-list').innerHTML =
            '<p class="text-gray-400 text-sm text-center py-8">' +
            '생성된 시사점이 없습니다. [지금 생성]을 누르거나 07:30 자동 생성을 기다리세요.</p>';
        return;
    }
    sel.innerHTML = runs.map(r =>
        `<option value="${r.run_date}">${r.run_date} (${r.total}건)</option>`).join('');
    const r0 = runs[0];
    document.getElementById('run-summary').textContent =
        `대기 ${r0.pending} · 승인 ${r0.approved} · 제외 ${r0.skipped}` +
        (r0.blocked ? ` · 차단 ${r0.blocked}` : '');
    await loadRun();
}

async function loadRun() {
    const date = document.getElementById('run-select').value;
    const data = await api('/api/newsletter/run' + (date ? `?date=${date}` : ''));
    RUN_DATE = data.run_date;
    ITEMS = data.items || [];
    render();
}

/* ── 렌더 ─────────────────────────────────────────────── */

function lintBadges(it) {
    const d = it.lint_detail || {};
    const blocking = d.blocking || [];
    const warning = d.warning || [];
    let html = '';
    if (blocking.length) {
        html += `<div class="mt-2 text-xs rounded border border-red-200 bg-red-50 px-3 py-2">
            <div class="font-semibold text-red-800 mb-1">검사 차단 ${blocking.length}건 — 수정 후 승인 가능</div>
            ${blocking.map(b => `<div class="text-red-700">· ${esc(b.label)}
                ${b.match ? `<span class="text-red-500">"${esc(b.match)}"</span>` : ''}</div>`).join('')}
        </div>`;
    }
    if (warning.length) {
        html += `<div class="mt-2 text-xs rounded border border-amber-200 bg-amber-50 px-3 py-2">
            <div class="font-semibold text-amber-800 mb-1">확인 권고 ${warning.length}건</div>
            ${warning.map(w => `<div class="text-amber-700">· ${esc(w.label)}
                ${w.match ? `<span class="text-amber-600">"${esc(w.match)}"</span>` : ''}</div>`).join('')}
        </div>`;
    }
    return html;
}

function card(it, idx) {
    const st = STATUS_LABEL[it.status] || STATUS_LABEL.pending;
    const blocked = !it.lint_ok;
    const points = it.points || [];

    return `
<div class="card" data-id="${it.id}">
  <div class="card-body space-y-3">

    <div class="flex flex-wrap items-start justify-between gap-2">
      <div class="min-w-0">
        <div class="flex items-center gap-2 flex-wrap">
          <span class="text-xs font-semibold px-2 py-0.5 rounded border ${st.cls}">${st.text}</span>
          <span class="text-xs text-gray-500">${esc(it.category || '')}</span>
          <span class="text-xs text-gray-400">${esc(it.mode === 'interpretation' ? '해석 포함' : '사실 중심')}</span>
          <span class="text-xs text-gray-400">${esc(it.model || '')}</span>
        </div>
        <p class="text-xs text-gray-400 mt-1">토픽: ${esc(it.topic)}</p>
      </div>
      <div class="flex items-center gap-1.5 shrink-0">
        <button type="button" class="btn-secondary text-xs" onclick="save(${it.id})">저장·재검사</button>
        <button type="button" class="btn-secondary text-xs" onclick="setStatus(${it.id},'skipped')">제외</button>
        <button type="button" class="text-xs px-3 py-1.5 rounded font-semibold
                ${blocked ? 'bg-gray-200 text-gray-400 cursor-not-allowed' : 'bg-green-600 text-white hover:bg-green-700'}"
                ${blocked ? 'disabled title="검사 차단 상태에서는 승인할 수 없습니다"' : ''}
                onclick="setStatus(${it.id},'approved')">승인</button>
      </div>
    </div>

    <div>
      <label class="block text-xs font-semibold text-gray-600 mb-1">헤드라인</label>
      <input type="text" class="form-input text-sm w-full" data-f="headline"
             value="${esc(it.headline)}">
    </div>

    <div>
      <div class="flex items-center justify-between mb-1">
        <label class="block text-xs font-semibold text-gray-600">사실 항목 <span class="text-gray-400 font-normal">(× 를 눌러 개별 제외)</span></label>
        <button type="button" class="text-xs text-blue-600" onclick="addPoint(${it.id})">+ 항목 추가</button>
      </div>
      <div class="space-y-1.5" data-points>
        ${points.map((p, i) => pointRow(it.id, i, p)).join('') ||
          '<p class="text-xs text-gray-400">항목이 없습니다.</p>'}
      </div>
    </div>

    ${it.mode === 'interpretation' || it.synthesis ? `
    <div>
      <label class="block text-xs font-semibold text-gray-600 mb-1">종합 판단
        <span class="text-gray-400 font-normal">근거는 위 항목 번호</span></label>
      <textarea class="form-input text-sm w-full" rows="2" data-f="synthesis">${esc(it.synthesis || '')}</textarea>
    </div>` : ''}

    <div>
      <label class="block text-xs font-semibold text-gray-600 mb-1">마무리 — 판단 재료</label>
      <textarea class="form-input text-sm w-full" rows="2" data-f="closing">${esc(it.closing || '')}</textarea>
    </div>

    ${lintBadges(it)}
  </div>
</div>`;
}

function pointRow(id, i, text) {
    return `<div class="flex items-start gap-1.5" data-point>
      <span class="text-xs text-gray-400 pt-2 w-4 text-right shrink-0">${i + 1}</span>
      <textarea class="form-input text-sm flex-1" rows="2">${esc(text)}</textarea>
      <button type="button" class="text-gray-400 hover:text-red-600 text-lg leading-none pt-1.5 px-1 shrink-0"
              title="이 항목 제외" onclick="removePoint(this)">&times;</button>
    </div>`;
}

function render() {
    const el = document.getElementById('insight-list');
    if (!ITEMS.length) {
        el.innerHTML = '<p class="text-gray-400 text-sm text-center py-8">이 날짜에 생성된 시사점이 없습니다.</p>';
        return;
    }
    el.innerHTML = ITEMS.map(card).join('');
}

/* ── 편집 ─────────────────────────────────────────────── */

function cardEl(id) {
    return document.querySelector(`[data-id="${id}"]`);
}

function addPoint(id) {
    const box = cardEl(id).querySelector('[data-points]');
    const n = box.querySelectorAll('[data-point]').length;
    box.insertAdjacentHTML('beforeend', pointRow(id, n, ''));
    renumber(box);
}

function removePoint(btn) {
    const row = btn.closest('[data-point]');
    const box = row.parentElement;
    row.remove();
    renumber(box);
}

function renumber(box) {
    box.querySelectorAll('[data-point]').forEach((row, i) => {
        row.querySelector('span').textContent = i + 1;
    });
}

function collect(id) {
    const c = cardEl(id);
    const get = f => {
        const el = c.querySelector(`[data-f="${f}"]`);
        return el ? el.value.trim() : null;
    };
    const points = [...c.querySelectorAll('[data-point] textarea')]
        .map(t => t.value.trim()).filter(Boolean);
    return {
        headline: get('headline'),
        points,
        synthesis: get('synthesis'),
        closing: get('closing'),
    };
}

async function save(id) {
    try {
        const res = await api(`/api/newsletter/insight/${id}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(collect(id)),
        });
        const i = ITEMS.findIndex(x => x.id === id);
        if (i >= 0) {
            ITEMS[i] = {
                ...ITEMS[i],
                headline: res.headline,
                points: res.points,
                synthesis: res.synthesis,
                closing: res.closing_material,
                lint_ok: res.lint.ok ? 1 : 0,
                lint_detail: { blocking: res.lint.blocking, warning: res.lint.warning },
            };
        }
        render();
        toast(res.lint.ok ? '저장했습니다. 검사 통과.' :
              `저장했습니다. 검사 차단 ${res.lint.blocking.length}건 남음.`, !res.lint.ok);
    } catch (e) {
        toast(e.message, true);
    }
}

async function setStatus(id, status) {
    try {
        await api(`/api/newsletter/insight/${id}/status`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ status }),
        });
        const it = ITEMS.find(x => x.id === id);
        if (it) it.status = status;
        render();
        toast(status === 'approved' ? '승인했습니다.' : '제외했습니다.');
        refreshSummary();
    } catch (e) {
        toast(e.message, true);
    }
}

async function approveAll() {
    const targets = ITEMS.filter(i => i.lint_ok && i.status !== 'approved');
    if (!targets.length) { toast('승인할 항목이 없습니다.'); return; }
    let done = 0;
    for (const it of targets) {
        try {
            await api(`/api/newsletter/insight/${it.id}/status`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ status: 'approved' }),
            });
            it.status = 'approved';
            done++;
        } catch (e) { /* 개별 실패는 건너뛴다 */ }
    }
    render();
    toast(`${done}건 승인했습니다.`);
    refreshSummary();
}

async function refreshSummary() {
    try {
        const runs = await api('/api/newsletter/runs');
        const r = runs.find(x => x.run_date === RUN_DATE);
        if (r) {
            document.getElementById('run-summary').textContent =
                `대기 ${r.pending} · 승인 ${r.approved} · 제외 ${r.skipped}` +
                (r.blocked ? ` · 차단 ${r.blocked}` : '');
        }
    } catch (e) { /* 요약은 실패해도 무시 */ }
}

async function generateNow() {
    const btn = document.getElementById('btn-gen');
    btn.disabled = true;
    btn.textContent = '생성 중... (1~3분)';
    try {
        const res = await api('/api/newsletter/generate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ days: 3, top_n: 3 }),
        });
        toast(`${res.saved}건 생성 — 통과 ${res.ok}, 차단 ${res.blocked}`);
        await loadRuns();
    } catch (e) {
        toast(e.message, true);
    } finally {
        btn.disabled = false;
        btn.textContent = '지금 생성';
    }
}

document.addEventListener('DOMContentLoaded', () => {
    loadRuns().catch(e => toast(e.message, true));
});
