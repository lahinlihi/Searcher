/* 발송 계정·구독자 설정
 *
 * 비밀번호는 서버가 화면으로 되돌려 보내지 않는다. 설정 여부만 표시하고,
 * 변경할 때만 입력받는다. 빈 값으로 저장하면 기존 비밀번호가 유지된다.
 */

const HINT = {
    gmail:   '앱 비밀번호가 필요합니다. Google 계정 → 보안 → 2단계 인증 → 앱 비밀번호',
    naver:   '네이버 메일 환경설정에서 SMTP 사용을 켜야 합니다.',
    daum:    '다음 메일 환경설정에서 IMAP/SMTP 사용을 켜야 합니다.',
    outlook: '계정 비밀번호를 사용합니다.',
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
    toastTimer = setTimeout(() => t.classList.add('hidden'), 4200);
}

async function api(url, opts) {
    const r = await fetch(url, opts);
    let d = null;
    try { d = await r.json(); } catch (e) { /* 본문 없음 */ }
    if (!r.ok) throw new Error((d && d.error) || `HTTP ${r.status}`);
    return d;
}

function val(id) { return document.getElementById(id).value.trim(); }

function updateHint() {
    document.getElementById('service-hint').textContent =
        HINT[val('service')] || '';
}

/* ── 계정 ─────────────────────────────────────────────── */

function applySettings(s) {
    document.getElementById('service').value = s.service || 'gmail';
    document.getElementById('user').value = s.user || '';
    document.getElementById('from-name').value = s.from_name || '';
    document.getElementById('base-url').value = s.base_url || '';
    document.getElementById('password').value = '';
    document.getElementById('pw-state').textContent =
        s.password_set ? `— 설정됨 ${s.password_hint}` : '— 미설정';
    document.getElementById('conn-state').innerHTML = s.password_set && s.user
        ? '<span class="text-gray-500">저장됨 · 연결 테스트로 확인하세요</span>'
        : '<span class="text-amber-700">계정 미설정 — 발송할 수 없습니다</span>';
    updateHint();
}

async function loadSettings() {
    applySettings(await api('/api/newsletter/mail-settings'));
}

async function testConn() {
    const btn = document.getElementById('btn-test');
    btn.disabled = true; btn.textContent = '연결 중...';
    try {
        const res = await api('/api/newsletter/test-connection', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                user: val('user'),
                password: val('password'),   // 비우면 저장된 값으로 시험
                service: val('service'),
            }),
        });
        document.getElementById('conn-state').innerHTML =
            `<span class="text-green-700">연결 성공 · ${esc(res.server)}:${res.port}</span>`;
        toast(`연결 성공 — ${res.user}`);
    } catch (e) {
        document.getElementById('conn-state').innerHTML =
            `<span class="text-red-700">연결 실패</span>`;
        toast(e.message, true);
    } finally {
        btn.disabled = false; btn.textContent = '연결 테스트';
    }
}

async function saveSettings() {
    const btn = document.getElementById('btn-save');
    btn.disabled = true;
    try {
        const s = await api('/api/newsletter/mail-settings', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                service: val('service'),
                user: val('user'),
                password: val('password'),   // 빈 값이면 서버가 기존 값 유지
                from_name: val('from-name'),
                base_url: val('base-url'),
            }),
        });
        applySettings(s);
        toast('저장했습니다.');
    } catch (e) {
        toast(e.message, true);
    } finally {
        btn.disabled = false;
    }
}

/* ── 구독자 ───────────────────────────────────────────── */

async function loadSubs() {
    const rows = await api('/api/newsletter/subscribers');
    const active = rows.filter(r => r.status === 'active').length;
    document.getElementById('sub-count').textContent =
        `활성 ${active}명 / 전체 ${rows.length}명`;
    const el = document.getElementById('sub-list');
    if (!rows.length) {
        el.innerHTML = '<p class="text-xs text-gray-400 py-3">등록된 구독자가 없습니다.</p>';
        return;
    }
    el.innerHTML = `<table class="w-full text-xs">
        <thead><tr class="text-gray-500 border-b">
          <th class="text-left py-1.5">상태</th><th class="text-left">이메일</th>
          <th class="text-left">이름</th><th class="text-left">회사</th>
          <th class="text-left">수신동의</th></tr></thead>
        <tbody>${rows.map(r => `<tr class="border-b border-gray-50">
          <td class="py-1.5"><span class="px-1.5 py-0.5 rounded text-xs
            ${r.status === 'active' ? 'bg-green-100 text-green-800' : 'bg-gray-100 text-gray-500'}">
            ${r.status === 'active' ? '활성' : '해지'}</span></td>
          <td>${esc(r.email)}</td><td>${esc(r.name || '')}</td>
          <td>${esc(r.company || '')}</td>
          <td class="text-gray-500">${esc((r.consent_at || '').slice(0, 10))}
            ${esc(r.consent_source || '')}</td></tr>`).join('')}</tbody></table>`;
}

async function addSub() {
    const email = val('sub-email');
    if (!email || !email.includes('@')) { toast('이메일을 입력하세요.', true); return; }
    try {
        await api('/api/newsletter/subscribers', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                email, name: val('sub-name'), company: val('sub-company'),
            }),
        });
        ['sub-email', 'sub-name', 'sub-company']
            .forEach(id => document.getElementById(id).value = '');
        toast('구독자를 등록했습니다.');
        loadSubs();
    } catch (e) {
        toast(e.message, true);
    }
}

document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('service').addEventListener('change', updateHint);
    document.getElementById('sub-email').addEventListener('keydown', e => {
        if (e.key === 'Enter') { e.preventDefault(); addSub(); }
    });
    Promise.all([loadSettings(), loadSubs()])
        .catch(e => toast(e.message, true));
});
