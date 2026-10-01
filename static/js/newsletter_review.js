/* 뉴스레터 편집실 — 근거 대조 · 직접 편집 · 승인
 *
 * 편집자 모델
 *   문장 고치기 / 순서 바꾸기 / 잘라내기 / 헤드라인은 편집자가 직접 한다.
 *   다시 쓰기는 AI 가 '대안'을 가져오기만 하고, 채택은 편집자가 한다.
 *   AI 가 써온 것을 자동으로 갈아끼우면 편집자는 사후 확인자가 되고
 *   통제권이 사실상 AI 에게 넘어간다.
 *
 * 왜 전체 재렌더를 피하는가
 *   검증 결과·대안 패널은 해당 행의 일부만 교체한다. 카드 전체를 다시 그리면
 *   편집 중이던 textarea 내용이 날아간다.
 *
 * 발송 버튼은 이 화면에 없다. /newsletter/send 로 분리했다.
 */

let RUN_DATE = null;
let ITEMS = [];
const VERIFY = {};     // insight_id → 검증 결과

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
    toastTimer = setTimeout(() => t.classList.add('hidden'), 3600);
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
    await loadRun();
    refreshSummary();
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

function card(it) {
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

    <!-- 근거 대조 바 -->
    <div class="flex flex-wrap items-center gap-2 bg-gray-50 border border-gray-200 rounded px-3 py-2">
      <span class="text-xs font-semibold text-gray-700">근거 대조</span>
      <span class="text-xs text-gray-500" data-vsummary>아직 대조하지 않았습니다</span>
      <div class="ml-auto flex items-center gap-1.5">
        <button type="button" class="btn-secondary text-xs"
                onclick="runVerify(${it.id}, false)">수치·기관 대조</button>
        <button type="button" class="btn-secondary text-xs"
                onclick="runVerify(${it.id}, true)">AI 위치 지목</button>
        <button type="button" class="btn-secondary text-xs"
                onclick="toggleMaterial(${it.id})">재료 전체</button>
      </div>
    </div>
    <div data-material class="hidden"></div>

    <div>
      <label class="block text-xs font-semibold text-gray-600 mb-1">헤드라인</label>
      <input type="text" class="form-input text-sm w-full" data-f="headline"
             value="${esc(it.headline)}">
    </div>

    <div>
      <div class="flex items-center justify-between mb-1">
        <label class="block text-xs font-semibold text-gray-600">사실 항목
          <span class="text-gray-400 font-normal">▲▼ 로 순서를 바꿉니다</span></label>
        <button type="button" class="text-xs text-blue-600" onclick="addPoint(${it.id})">+ 항목 추가</button>
      </div>
      <div class="space-y-2" data-points>
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
    return `<div class="border border-gray-100 rounded p-2" data-point>
      <div class="flex items-start gap-1.5">
        <div class="flex flex-col items-center gap-0.5 pt-1 shrink-0">
          <button type="button" class="text-gray-400 hover:text-gray-700 text-xs leading-none px-1"
                  title="위로" onclick="movePoint(this,-1)">&#9650;</button>
          <span class="text-xs text-gray-500 font-semibold" data-n>${i + 1}</span>
          <button type="button" class="text-gray-400 hover:text-gray-700 text-xs leading-none px-1"
                  title="아래로" onclick="movePoint(this,1)">&#9660;</button>
        </div>
        <textarea class="form-input text-sm flex-1" rows="2">${esc(text)}</textarea>
        <button type="button" class="text-gray-400 hover:text-red-600 text-lg leading-none pt-1.5 px-1 shrink-0"
                title="이 항목 잘라내기" onclick="removePoint(this)">&times;</button>
      </div>
      <div class="flex flex-wrap items-center gap-2 mt-1.5 ml-7" data-vbar>
        <button type="button" class="text-xs text-blue-600" onclick="openRewrite(${id}, this)">다시 쓰기 요청</button>
      </div>
      <div data-rw class="hidden ml-7 mt-2"></div>
    </div>`;
}

function render() {
    const el = document.getElementById('insight-list');
    if (!ITEMS.length) {
        el.innerHTML = '<p class="text-gray-400 text-sm text-center py-8">이 날짜에 생성된 시사점이 없습니다.</p>';
        return;
    }
    el.innerHTML = ITEMS.map(card).join('');
    document.getElementById('go-send').href =
        '/newsletter/send' + (RUN_DATE ? `?date=${encodeURIComponent(RUN_DATE)}` : '');
    Object.keys(VERIFY).forEach(id => paintVerify(Number(id)));
}

/* ── 근거 대조 ─────────────────────────────────────────── */

async function runVerify(id, useAi) {
    const c = cardEl(id);
    const sum = c.querySelector('[data-vsummary]');
    sum.textContent = useAi ? 'AI 위치 지목 중... (항목당 10~20초)' : '대조 중...';
    try {
        const res = await api(`/api/newsletter/insight/${id}/verify${useAi ? '?ai=1' : ''}`);
        VERIFY[id] = res;
        paintVerify(id);
    } catch (e) {
        sum.textContent = '';
        toast(e.message, true);
    }
}

function paintVerify(id) {
    const c = cardEl(id);
    const res = VERIFY[id];
    if (!c || !res) return;

    const sum = c.querySelector('[data-vsummary]');
    if (!res.verifiable) {
        sum.innerHTML = res.material_rebuilt
            ? '<span class="text-amber-700">원본 재료가 저장되지 않은 시사점입니다 — 대조 불가. '
              + '토픽으로 재구성한 재료만 참고로 볼 수 있습니다.</span>'
            : '<span class="text-amber-700">재료가 없어 대조할 수 없습니다.</span>';
    } else {
        sum.innerHTML = res.flagged
            ? `<span class="text-amber-800 font-semibold">${res.flagged}개 항목에 확인할 것이 있습니다</span>`
              + `<span class="text-gray-400"> · 재료 ${res.material.length}건`
              + `${res.ai_used ? ' · AI 위치 지목 포함' : ' · 수치·기관만'}</span>`
            : `<span class="text-green-700">표시된 항목 없음</span>`
              + `<span class="text-gray-400"> · 재료 ${res.material.length}건`
              + `${res.ai_used ? ' · AI 위치 지목 포함' : ' · 수치·기관만'}</span>`;
    }

    const rows = c.querySelectorAll('[data-point]');
    (res.items || []).forEach(item => {
        const row = rows[item.i - 1];
        if (!row) return;
        const bar = row.querySelector('[data-vbar]');
        bar.innerHTML = vbarHtml(id, item, res);
        row.className = item.flags.length
            ? 'border border-amber-300 bg-amber-50/40 rounded p-2'
            : 'border border-gray-100 rounded p-2';
    });
}

function vbarHtml(id, item, res) {
    const chips = (item.cited || []).map(n => {
        const m = (res.material || []).find(x => x.n === n);
        return `<button type="button" class="text-xs font-semibold border border-blue-200
                bg-blue-50 text-blue-800 rounded px-1.5" title="${esc(m ? m.title : '')}"
                onclick="toggleMaterial(${id}, ${n})">${n}</button>`;
    }).join(' ');

    const state = !res.verifiable
        ? '<span class="text-xs text-gray-400">대조 불가</span>'
        : item.flags.length
            ? `<span class="text-xs text-amber-800 font-semibold">${item.flags.map(esc).join(' · ')}</span>`
            : '<span class="text-xs text-green-700">대조 통과</span>';

    const quotes = (item.ai || []).map(a => {
        const ok = a.quote_verified;
        const mm = a.subject_mismatch;
        return `<div class="text-xs border rounded px-2 py-1.5 mt-1
            ${ok ? (mm ? 'border-amber-200 bg-amber-50' : 'border-gray-200 bg-gray-50')
                 : 'border-red-200 bg-red-50'}">
          <div class="${ok ? 'text-gray-600' : 'text-red-700 font-semibold'}">
            ${ok ? `재료 [${a.material_n}] 에서 확인` : '재료에 없는 인용 — 믿지 마세요'}
            ${mm ? '<span class="text-amber-800 font-semibold">· 주어 확인 필요</span>' : ''}
          </div>
          <div class="text-gray-700 mt-0.5">"${esc((a.quote || '').slice(0, 180))}"</div>
          ${a.note ? `<div class="text-amber-800 mt-0.5">→ ${esc(a.note)}</div>` : ''}
        </div>`;
    }).join('');

    return `<span class="text-xs text-gray-400">근거</span> ${chips || '<span class="text-xs text-red-600">없음</span>'}
      <span class="text-gray-300">·</span> ${state}
      <button type="button" class="text-xs text-blue-600 ml-auto"
              onclick="openRewrite(${id}, this)">다시 쓰기 요청</button>
      <div class="w-full">${quotes}</div>`;
}

function toggleMaterial(id, only) {
    const c = cardEl(id);
    const box = c.querySelector('[data-material]');
    const res = VERIFY[id];
    if (!res) { toast('먼저 [수치·기관 대조]를 누르세요.'); return; }
    if (!box.classList.contains('hidden') && box.dataset.only == (only ?? '')) {
        box.classList.add('hidden');
        return;
    }
    const list = (res.material || []).filter(m => only == null || m.n === only);
    box.dataset.only = only ?? '';
    box.innerHTML = `<div class="border border-gray-200 rounded bg-gray-50 p-3 space-y-2">
      <div class="text-xs text-gray-500">
        ${only == null ? `재료 전체 ${list.length}건` : `재료 [${only}]`}
        ${res.material_rebuilt ? ' · <span class="text-amber-700">토픽으로 재구성된 재료 (원본 아님)</span>' : ''}
        · 조각 경계는 <code>⁄</code> 로 표시됩니다. 조각을 이어 읽지 마세요.
      </div>
      ${list.map(m => `<div class="text-xs border-t border-gray-200 pt-2">
        <div class="font-semibold text-gray-700">[${m.n}] ${esc(m.title)}</div>
        <div class="text-gray-400">${esc(m.source)}</div>
        <div class="text-gray-600 mt-1 leading-relaxed">${esc(m.body)}</div>
      </div>`).join('')}
    </div>`;
    box.classList.remove('hidden');
}

/* ── 다시 쓰기 — 대안을 가져오기만 한다 ───────────────── */

function openRewrite(id, btn) {
    const row = btn.closest('[data-point]');
    const box = row.querySelector('[data-rw]');
    if (!box.classList.contains('hidden')) { box.classList.add('hidden'); return; }
    const idx = [...row.parentElement.querySelectorAll('[data-point]')].indexOf(row) + 1;
    box.innerHTML = `<div class="border border-gray-200 rounded bg-gray-50 p-3 space-y-2">
      <div class="text-xs font-semibold text-gray-700">기자에게 다시 쓰기 요청</div>
      <div class="flex gap-1.5">
        <input type="text" class="form-input text-xs flex-1" data-note
               placeholder="무엇이 문제인지 한 줄 (비워도 됩니다)">
        <button type="button" class="btn-secondary text-xs whitespace-nowrap"
                onclick="requestRewrite(${id}, ${idx}, this)">요청</button>
      </div>
      <div data-alts></div>
      <p class="text-xs text-gray-500">채택하기 전에는 아무것도 바뀌지 않습니다.
        교체한 뒤에도 [저장·재검사] 를 누르기 전까지는 저장되지 않습니다.</p>
    </div>`;
    box.classList.remove('hidden');
}

async function requestRewrite(id, idx, btn) {
    const box = btn.closest('[data-rw]');
    const note = box.querySelector('[data-note]').value.trim();
    const alts = box.querySelector('[data-alts]');
    btn.disabled = true; btn.textContent = '요청 중...';
    alts.innerHTML = '<p class="text-xs text-gray-400">기자가 쓰는 중... (10~30초)</p>';
    try {
        const res = await api(`/api/newsletter/insight/${id}/rewrite`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ index: idx, note }),
        });
        if (!res.alternatives.length) {
            alts.innerHTML = '<p class="text-xs text-red-600">대안을 받지 못했습니다. 다시 요청해 보세요.</p>';
            return;
        }
        alts.innerHTML = `
          <div class="text-xs border border-gray-200 bg-white rounded px-2 py-1.5">
            <div class="text-gray-400 font-semibold">현재</div>
            <div class="text-gray-600 mt-0.5">${esc(res.current)}</div>
          </div>
          ${res.alternatives.map((a, i) => altHtml(a, i + 1)).join('')}`;
    } catch (e) {
        alts.innerHTML = `<p class="text-xs text-red-600">${esc(e.message)}</p>`;
    } finally {
        btn.disabled = false; btn.textContent = '요청';
    }
}

function altHtml(a, n) {
    const badge = a.ok
        ? '<span class="text-xs px-1.5 rounded bg-green-100 text-green-800">검사 통과</span>'
        : '<span class="text-xs px-1.5 rounded bg-red-100 text-red-800">검사 걸림</span>';
    const why = [
        ...(a.lint.blocking || []).map(b => b.label),
        ...(a.code.missing_numbers || []).map(x => `재료에 없는 수치 ${x}`),
        ...(a.code.missing_orgs || []).map(x => `재료에 없는 기관 ${x}`),
    ];
    return `<div class="text-xs border border-blue-200 bg-white rounded px-2 py-1.5 mt-1.5">
      <div class="flex items-center gap-1.5 flex-wrap">
        <span class="text-xs font-semibold bg-blue-800 text-white rounded px-1.5">대안 ${n}</span>
        <span class="text-gray-400 flex-1 min-w-0">${esc(a.approach)}</span>
        ${badge}
      </div>
      <div class="text-gray-800 mt-1 leading-relaxed" data-alt-text>${esc(a.text)}</div>
      ${why.length ? `<div class="text-red-700 mt-0.5">· ${why.map(esc).join(' · ')}</div>` : ''}
      <div class="flex gap-1.5 mt-1.5">
        <button type="button" class="btn-secondary text-xs" onclick="adoptAlt(this)">이 안으로 교체</button>
      </div>
    </div>`;
}

function adoptAlt(btn) {
    const text = btn.closest('[class*=border-blue]').querySelector('[data-alt-text]').textContent;
    const row = btn.closest('[data-point]');
    const ta = row.querySelector('textarea');
    ta.dataset.prev = ta.value;          // 되돌리기용
    ta.value = text;
    const bar = row.querySelector('[data-vbar]');
    if (!bar.querySelector('[data-undo]')) {
        bar.insertAdjacentHTML('beforeend',
            `<button type="button" data-undo class="text-xs text-gray-500 underline w-full text-left mt-1"
                     onclick="undoAdopt(this)">되돌리기 — 교체 전 문장으로</button>`);
    }
    row.querySelector('[data-rw]').classList.add('hidden');
    toast('교체했습니다. [저장·재검사] 를 눌러야 저장됩니다.');
}

function undoAdopt(btn) {
    const row = btn.closest('[data-point]');
    const ta = row.querySelector('textarea');
    if (ta.dataset.prev !== undefined) ta.value = ta.dataset.prev;
    btn.remove();
    toast('되돌렸습니다.');
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

function movePoint(btn, dir) {
    const row = btn.closest('[data-point]');
    const box = row.parentElement;
    const sib = dir < 0 ? row.previousElementSibling : row.nextElementSibling;
    if (!sib || !sib.hasAttribute('data-point')) return;
    if (dir < 0) box.insertBefore(row, sib);
    else box.insertBefore(sib, row);
    renumber(box);
}

function renumber(box) {
    box.querySelectorAll('[data-point]').forEach((row, i) => {
        const n = row.querySelector('[data-n]');
        if (n) n.textContent = i + 1;
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
        // 문장이 바뀌었으니 이전 대조 결과는 더 이상 유효하지 않다
        delete VERIFY[id];
        render();
        toast(res.lint.ok ? '저장했습니다. 검사 통과. 근거 대조는 다시 눌러주세요.' :
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
