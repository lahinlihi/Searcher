/* 발송 전 최종 화면
 *
 * 편집실(/newsletter/review)과 분리된 화면이다. 여기서는 내용을 고칠 수 없다.
 * 편집 중 실수로 발송 버튼을 누르는 경로를 없애기 위한 분리다.
 *
 * 발송 버튼은 점검을 모두 통과하기 전까지 잠겨 있다. 서버도 같은 조건을
 * 다시 보므로(승인분 없으면 build() 가 None) 두 층에서 막힌다.
 */

let RUN_DATE = null;
let STATUS = null;

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
    toastTimer = setTimeout(() => t.classList.add('hidden'), 4000);
}

async function api(url, opts) {
    const r = await fetch(url, opts);
    let d = null;
    try { d = await r.json(); } catch (e) { /* 본문 없음 */ }
    if (!r.ok) throw new Error((d && d.error) || `HTTP ${r.status}`);
    return d;
}

/* ── 점검 ─────────────────────────────────────────────── */

function tile(label, value, ok) {
    const cls = ok === null ? 'border-gray-200 bg-gray-50 text-gray-700'
        : ok ? 'border-green-200 bg-green-50 text-green-800'
            : 'border-red-200 bg-red-50 text-red-800';
    return `<div class="border rounded px-3 py-2 ${cls}">
        <div class="text-xs opacity-70">${esc(label)}</div>
        <div class="text-sm font-semibold mt-0.5">${esc(value)}</div>
    </div>`;
}

function renderStatus(s) {
    STATUS = s;
    const approved = s.counts.approved || 0;
    const pending = s.counts.pending || 0;
    const ready = !s.blockers.length;

    document.getElementById('ready-badge').innerHTML = ready
        ? '<span class="px-2 py-0.5 rounded border border-green-200 bg-green-100 text-green-800">발송 가능</span>'
        : '<span class="px-2 py-0.5 rounded border border-red-200 bg-red-100 text-red-800">발송 불가</span>';

    document.getElementById('blockers').innerHTML = s.blockers.length
        ? `<div class="text-xs rounded border border-red-200 bg-red-50 px-3 py-2 space-y-0.5">
             ${s.blockers.map(b => `<div class="text-red-700">· ${esc(b)}</div>`).join('')}
           </div>` : '';

    const secs = s.sections || [];
    document.getElementById('checklist').innerHTML =
        tile('실리는 시사점', `${approved}건`, approved > 0) +
        tile('아직 검토 대기', `${pending}건`, pending ? null : true) +
        tile('입찰공고', `${s.tenders}건`, null) +
        tile('받는 사람', `${s.subscribers.length}명`, s.subscribers.length > 0);

    document.getElementById('subject-box').innerHTML = `
      <div>제목 <b class="text-gray-800">${esc(s.subject || '— 승인분 없음')}</b></div>
      <div class="mt-1">보내는 계정
        <b class="text-gray-800">${esc(s.mail_user || '미설정')}</b>
        ${s.mail_ready ? '' : ' <a href="/newsletter/settings" class="text-blue-600">설정하기</a>'}
      </div>
      ${secs.length ? `<div class="mt-1.5 space-y-0.5">${secs.map((x, i) =>
        `<div class="text-gray-500">${i + 1}. ${esc(x.headline)}
          <span class="text-gray-400">· 항목 ${x.points} · 관련기사 ${x.articles}</span></div>`
      ).join('')}</div>` : ''}
      ${s.subscribers.length ? `<div class="mt-1.5 text-gray-500">받는 사람:
        ${s.subscribers.slice(0, 6).map(x => esc(x.email)).join(', ')}
        ${s.subscribers.length > 6 ? ` 외 ${s.subscribers.length - 6}명` : ''}</div>` : ''}`;

    // 같은 날짜로 이미 나갔는지 — 중복 발송은 받는 쪽에서 가장 눈에 띄는 사고다
    document.getElementById('sent-warn').innerHTML = s.already_sent
        ? `<div class="text-xs rounded border border-amber-200 bg-amber-50 px-3 py-2 text-amber-800">
             이 발행일(${esc(s.run_date)})은 이미
             ${esc((s.already_sent.sent_at || '').slice(0, 16).replace('T', ' '))}에
             ${s.already_sent.success_count}명에게 발송됐습니다. 다시 보내면 중복 수신됩니다.
           </div>` : '';

    document.getElementById('send-target').textContent = ready
        ? `승인 ${approved}건을 구독자 ${s.subscribers.length}명에게 보냅니다`
        : '점검을 통과해야 발송할 수 있습니다';

    const btn = document.getElementById('btn-send');
    btn.disabled = !ready;
    btn.className = 'text-sm px-4 py-2 rounded font-semibold ml-auto ' + (ready
        ? 'bg-green-600 text-white hover:bg-green-700'
        : 'bg-gray-200 text-gray-400 cursor-not-allowed');
}

/* ── 미리보기 ─────────────────────────────────────────── */

function setWidth(px) {
    const f = document.getElementById('mail-frame');
    f.style.width = px + 'px';
    document.getElementById('width-state').textContent =
        px >= 600 ? '폭 680px — PC 메일' : '폭 380px — 휴대폰';
}

function loadPreview() {
    const q = RUN_DATE ? `?date=${encodeURIComponent(RUN_DATE)}` : '';
    document.getElementById('mail-frame').src = '/newsletter/preview' + q;
    document.getElementById('open-new').href = '/newsletter/preview' + q;
}

/* ── 로딩 ─────────────────────────────────────────────── */

async function loadRuns() {
    const runs = await api('/api/newsletter/runs');
    const sel = document.getElementById('run-select');
    if (!runs.length) {
        sel.innerHTML = '<option value="">생성된 시사점 없음</option>';
        return;
    }
    sel.innerHTML = runs.map(r =>
        `<option value="${r.run_date}">${r.run_date} (승인 ${r.approved || 0}건)</option>`
    ).join('');
    await loadStatus();
}

async function loadStatus() {
    const date = document.getElementById('run-select').value;
    const s = await api('/api/newsletter/send-status' + (date ? `?date=${date}` : ''));
    RUN_DATE = s.run_date;
    renderStatus(s);
    loadPreview();
}

/* ── 발송 ─────────────────────────────────────────────── */

async function sendTest() {
    const btn = document.getElementById('btn-test');
    const to = document.getElementById('test-email').value.trim();
    btn.disabled = true; btn.textContent = '발송 중...';
    try {
        const res = await api('/api/newsletter/send-test', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ to, date: RUN_DATE }),
        });
        toast(`테스트 발송 완료 → ${res.to} (섹션 ${res.sections}개)`);
        loadHistory();
    } catch (e) {
        toast(e.message, true);
    } finally {
        btn.disabled = false; btn.textContent = '테스트 발송';
    }
}

async function sendReal() {
    if (!STATUS || STATUS.blockers.length) { toast('점검을 통과해야 합니다.', true); return; }
    const n = STATUS.subscribers.length;
    const warn = STATUS.already_sent
        ? '\n\n주의: 이 발행일은 이미 발송됐습니다. 중복 수신됩니다.' : '';
    const answer = prompt(
        `승인 ${STATUS.counts.approved || 0}건을 구독자 ${n}명에게 발송합니다.\n`
        + `되돌릴 수 없습니다.${warn}\n\n계속하려면 SEND 를 입력하세요.`);
    if (answer !== 'SEND') { toast('발송을 취소했습니다.'); return; }

    const btn = document.getElementById('btn-send');
    btn.disabled = true; btn.textContent = '발송 중...';
    try {
        const res = await api('/api/newsletter/send', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ confirm: 'SEND', date: RUN_DATE }),
        });
        toast(`발송 완료 — 성공 ${res.success} / 실패 ${res.fail} (총 ${res.total})`,
            res.fail > 0);
        loadHistory();
        loadStatus();
    } catch (e) {
        toast(e.message, true);
    } finally {
        btn.textContent = '구독자에게 발송';
    }
}

async function loadHistory() {
    try {
        const rows = await api('/api/newsletter/history');
        const el = document.getElementById('history');
        if (!rows.length) { el.textContent = '발송 이력 없음'; return; }
        el.innerHTML = rows.slice(0, 6).map(h =>
            `<div>${esc(h.sent_at.slice(0, 16).replace('T', ' '))} ·
             ${h.kind === 'test' ? '테스트' : '실발송'} ·
             성공 ${h.success_count}${h.fail_count ? ` / 실패 ${h.fail_count}` : ''} ·
             ${esc(h.subject)}</div>`).join('');
    } catch (e) { /* 이력 실패는 무시 */ }
}

document.addEventListener('DOMContentLoaded', () => {
    setWidth(680);
    loadRuns().then(loadHistory).catch(e => toast(e.message, true));
});
