// 설정 페이지 JavaScript

let currentSettings = {};

// 페이지 로드 시 실행
document.addEventListener('DOMContentLoaded', function() {
    loadSettings();
    loadDatabaseStats();
});

// 설정 로드
async function loadSettings() {
    try {
        const response = await fetch('/api/settings');
        const settings = await response.json();

        if (response.ok) {
            // sites_config가 비어 있으면 sites 데이터를 sites_config로 복사
            // (settings_manager가 기본값 병합 시 빈 sites_config: {}를 주입하기 때문)
            if (settings.crawl) {
                const sc = settings.crawl.sites_config;
                if (!sc || Object.keys(sc).length === 0) {
                    settings.crawl.sites_config = settings.crawl.sites || {};
                }
            }
            currentSettings = settings;
            populateSettings(settings);
        }
    } catch (error) {
        console.error('Failed to load settings:', error);
    }
}

// 설정 값을 폼에 채우기
function populateSettings(settings) {
    // 크롤링 설정
    const autoCrawlCheckbox = document.getElementById('auto-crawl-enabled');
    if (autoCrawlCheckbox) {
        autoCrawlCheckbox.checked = settings.crawl?.auto_enabled || false;
    }

    // 사이트 목록 렌더링 (loadSettings에서 sites_config가 정규화됨)
    renderSitesList(settings.crawl?.sites_config || {});

    // 이메일 설정
    const emailEnabledCheckbox = document.getElementById('email-enabled');
    if (emailEnabledCheckbox) {
        emailEnabledCheckbox.checked = settings.notification?.email_enabled || false;
    }

    const emailAddress = document.getElementById('email-address');
    if (emailAddress) {
        emailAddress.value = settings.notification?.email_address || '';
    }

    const deadlineAlertCheckbox = document.getElementById('deadline-alert');
    if (deadlineAlertCheckbox) {
        deadlineAlertCheckbox.checked = settings.notification?.deadline_alert || false;
    }
}

// 설정 저장
async function saveSettings() {
    try {
        // 사이트 설정 수집
        const sitesConfig = {};
        const sitesCheckboxes = document.querySelectorAll('[data-site-id]');
        sitesCheckboxes.forEach(checkbox => {
            const siteId = checkbox.getAttribute('data-site-id');
            const siteData = currentSettings.crawl?.sites_config?.[siteId] || currentSettings.crawl?.sites?.[siteId] || {};
            sitesConfig[siteId] = {
                ...siteData,
                enabled: checkbox.checked
            };
        });

        // 폼에서 설정 값 가져오기
        const settings = {
            crawl: {
                auto_enabled: document.getElementById('auto-crawl-enabled')?.checked || false,
                times: currentSettings.crawl?.times || ['09:00', '17:00'],
                sites: sitesConfig, // 하위 호환성을 위해 유지
                sites_config: sitesConfig
            },
            notification: {
                email_enabled: document.getElementById('email-enabled')?.checked || false,
                email_address: document.getElementById('email-address')?.value || '',
                deadline_alert: document.getElementById('deadline-alert')?.checked || false,
                deadline_days: 3
            },
            data: currentSettings.data || {},
            display: currentSettings.display || {},
            // user_preferences 포함 (누락 시 파일 덮어쓰기로 필터 설정 삭제됨)
            // 필터 설정(exclude_keywords, budget_range)은 "필터 저장" 버튼으로만 변경하고,
            // 여기서는 interest_keywords만 현재 상태로 업데이트하고 나머지는 그대로 유지
            user_preferences: {
                ...(currentSettings.user_preferences || {}),
                interest_keywords: currentKeywords
            }
        };

        const response = await fetch('/api/settings', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(settings)
        });

        const data = await response.json();

        if (response.ok) {
            alert('설정이 저장되었습니다.');
            currentSettings = settings;
        } else {
            alert('설정 저장 실패: ' + data.error);
        }

    } catch (error) {
        console.error('Failed to save settings:', error);
        alert('설정 저장 중 오류가 발생했습니다.');
    }
}

// 데이터베이스 통계 로드
async function loadDatabaseStats() {
    try {
        const response = await fetch('/api/data/stats');
        const stats = await response.json();

        if (response.ok) {
            displayDatabaseStats(stats);
        }
    } catch (error) {
        console.error('Failed to load database stats:', error);
    }
}

// 데이터베이스 통계 표시
function displayDatabaseStats(stats) {
    // 통계 정보를 화면에 표시 (필요시 구현)
    console.log('Database stats:', stats);
}

// 오래된 공고 삭제
async function deleteOldTenders() {
    if (!confirm('30일 이상 지난 공고를 삭제하시겠습니까?')) {
        return;
    }

    try {
        const response = await fetch('/api/data/delete-old', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ days: 30 })
        });

        const data = await response.json();

        if (response.ok) {
            alert(data.message);
            loadDatabaseStats(); // 통계 새로고침
        } else {
            alert('삭제 실패: ' + data.error);
        }

    } catch (error) {
        console.error('Failed to delete old tenders:', error);
        alert('삭제 중 오류가 발생했습니다.');
    }
}

// 크롤링 데이터(공고)만 초기화
async function clearTenders() {
    if (!confirm('수집된 공고 데이터를 모두 삭제하시겠습니까?\n설정·필터·북마크는 유지됩니다.')) {
        return;
    }

    try {
        const response = await fetch('/api/data/clear-tenders', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });

        const data = await response.json();

        if (response.ok) {
            alert(data.message);
            loadDatabaseStats();
        } else {
            alert('삭제 실패: ' + data.error);
        }

    } catch (error) {
        console.error('Failed to clear tenders:', error);
        alert('삭제 중 오류가 발생했습니다.');
    }
}

// 데이터베이스 초기화
async function resetDatabase() {
    if (!confirm('⚠️ 경고: 모든 데이터가 삭제됩니다.\n정말 계속하시겠습니까?')) {
        return;
    }

    if (!confirm('다시 한 번 확인합니다. 모든 공고, 필터, 로그가 삭제됩니다.')) {
        return;
    }

    try {
        const response = await fetch('/api/data/reset', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ keep_filters: true })
        });

        const data = await response.json();

        if (response.ok) {
            alert(data.message);
            loadDatabaseStats(); // 통계 새로고침
        } else {
            alert('초기화 실패: ' + data.error);
        }

    } catch (error) {
        console.error('Failed to reset database:', error);
        alert('초기화 중 오류가 발생했습니다.');
    }
}

// 사이트 목록 렌더링
function renderSitesList(sitesConfig) {
    const container = document.getElementById('sites-list');
    if (!container) return;

    container.innerHTML = '';

    // 빈 목록이면 안내 메시지 표시
    if (Object.keys(sitesConfig).length === 0) {
        container.innerHTML = '<p class="text-gray-500 text-sm">등록된 사이트가 없습니다. "+ 새 사이트 추가" 버튼을 클릭하여 사이트를 추가하세요.</p>';
        return;
    }

    // 크롤러가 구현된 사이트 목록 (실제 작동 확인됨)
    const implementedCrawlers = [
        // API 기반 크롤러
        'g2b_api', 'g2b_pre_spec', 'lh_api', 'smb24_api', 'mois_predece',
        // 전용 크롤러
        'iris', 'kosmes',
        // 웹 크롤링 기반 (GenericCrawler)
        'sung-dong-gu', 'kist_notice', 'hrdkorea', 'kocca', 'kosac',
        'mohw', 'motie', 'msit', 'moe', 'semas', 'nia',
        'moel', 'mss', 'nipa',
        // RSS 피드
        'gwangjin-gu', 'seongbuk-gu',
        // 비활성화 (내부망 전용, 서버 접속 불가)
        'kist_bid', 'koica_api'
    ];

    for (const [siteId, siteData] of Object.entries(sitesConfig)) {
        const siteDiv = document.createElement('div');
        siteDiv.className = 'flex items-center justify-between p-2 bg-gray-50 rounded';

        const label = document.createElement('label');
        label.className = 'flex items-center flex-1';

        const checkbox = document.createElement('input');
        checkbox.type = 'checkbox';
        checkbox.setAttribute('data-site-id', siteId);
        checkbox.className = 'form-checkbox mr-2';
        checkbox.checked = siteData.enabled !== false;

        const infoDiv = document.createElement('div');

        // 크롤러 구현 여부 표시
        const hasCrawler = implementedCrawlers.includes(siteId);
        const crawlerBadge = hasCrawler
            ? '<span class="text-xs bg-green-100 text-green-800 px-2 py-0.5 rounded ml-2">크롤러 구현됨</span>'
            : '<span class="text-xs bg-yellow-100 text-yellow-800 px-2 py-0.5 rounded ml-2">설정만</span>';

        infoDiv.innerHTML = '<span class="text-sm font-medium">' + siteData.name + '</span>' +
            '<span class="text-xs text-gray-500 ml-2">(' + siteId + ')</span>' +
            crawlerBadge +
            (siteData.url ? '<br><span class="text-xs text-gray-400">' + siteData.url + '</span>' : '');

        label.appendChild(checkbox);
        label.appendChild(infoDiv);

        const deleteBtn = document.createElement('button');
        deleteBtn.className = 'text-red-600 hover:text-red-800 text-sm ml-2';
        deleteBtn.textContent = '삭제';
        deleteBtn.onclick = function() { removeSite(siteId); };

        siteDiv.appendChild(label);
        siteDiv.appendChild(deleteBtn);
        container.appendChild(siteDiv);
    }
}

// 사이트 추가 모달 표시
function showAddSiteModal() {
    document.getElementById('add-site-modal').classList.remove('hidden');
    // 입력 필드 초기화
    document.getElementById('new-site-id').value = '';
    document.getElementById('new-site-name').value = '';
    document.getElementById('new-site-url').value = '';
    document.getElementById('new-site-crawl-url').value = '';
    document.getElementById('new-site-crawl-type').value = 'sample';
    document.getElementById('new-site-enabled').checked = true;
}

// 사이트 추가 모달 숨기기
function hideAddSiteModal() {
    document.getElementById('add-site-modal').classList.add('hidden');
}

// 사이트 추가
function addSite() {
    const siteId = document.getElementById('new-site-id').value.trim();
    const siteName = document.getElementById('new-site-name').value.trim();
    const siteUrl = document.getElementById('new-site-url').value.trim();
    const crawlUrl = document.getElementById('new-site-crawl-url').value.trim();
    const crawlType = document.getElementById('new-site-crawl-type').value;
    const enabled = document.getElementById('new-site-enabled').checked;

    // 유효성 검사
    if (!siteId || !siteName) {
        alert('사이트 ID와 이름은 필수입니다.');
        return;
    }

    if (!/^[a-z0-9-]+$/.test(siteId)) {
        alert('사이트 ID는 영문 소문자, 숫자, 하이픈만 사용 가능합니다.');
        return;
    }

    // 중복 확인
    const sitesConfig = currentSettings.crawl?.sites_config || currentSettings.crawl?.sites || {};
    if (sitesConfig[siteId]) {
        alert('이미 존재하는 사이트 ID입니다.');
        return;
    }

    // 사이트 추가
    sitesConfig[siteId] = {
        name: siteName,
        url: siteUrl,
        enabled: enabled,
        crawl_url: crawlUrl || siteUrl,  // 크롤링 URL (비워두면 메인 URL 사용)
        crawl_type: crawlType  // 'sample' 또는 'list'
    };

    // 현재 설정 업데이트
    if (!currentSettings.crawl) currentSettings.crawl = {};
    currentSettings.crawl.sites_config = sitesConfig;
    currentSettings.crawl.sites = sitesConfig;

    // 목록 다시 렌더링
    renderSitesList(sitesConfig);

    // 모달 닫기
    hideAddSiteModal();

    alert('사이트가 추가되었습니다. "설정 저장" 버튼을 클릭하여 저장하세요.');
}

// 사이트 삭제
function removeSite(siteId) {
    if (!confirm('"' + siteId + '" 사이트를 삭제하시겠습니까?')) {
        return;
    }

    const sitesConfig = currentSettings.crawl?.sites_config || currentSettings.crawl?.sites || {};
    delete sitesConfig[siteId];

    // 현재 설정 업데이트
    currentSettings.crawl.sites_config = sitesConfig;
    currentSettings.crawl.sites = sitesConfig;

    // 목록 다시 렌더링
    renderSitesList(sitesConfig);

    alert('사이트가 삭제되었습니다. "설정 저장" 버튼을 클릭하여 저장하세요.');
}

// ============= 공고 필터 관리 (관심 키워드 / 제외 키워드 / 금액 범위) =============

let currentKeywords = [];
let currentExcludeKeywords = [];

// 필터 설정 로드
async function loadInterestKeywords() {
    try {
        const response = await fetch('/api/interest-keywords');
        const data = await response.json();

        if (response.ok) {
            currentKeywords = data.keywords || [];
            currentExcludeKeywords = data.exclude_keywords || [];
            const br = data.budget_range || {};
            renderKeywordTags();
            renderExcludeKeywordTags();
            loadBudgetRangeInputs(br);
        }
    } catch (error) {
        console.error('Failed to load interest keywords:', error);
    }
}

// ─ 관심 키워드 태그 렌더링
function renderKeywordTags() {
    const container = document.getElementById('keywords-tags');
    if (!container) return;

    if (currentKeywords.length === 0) {
        container.innerHTML = '<span class="text-xs text-gray-400 italic">설정된 관심 키워드가 없습니다.</span>';
        return;
    }

    container.innerHTML = currentKeywords.map((kw, i) => `
        <span class="inline-flex items-center gap-1 px-2 py-0.5 bg-green-100 text-green-800
                     border border-green-300 rounded-full text-xs font-medium">
            ${escHtml(kw)}
            <button onclick="removeKeyword(${i})" class="ml-0.5 text-green-600 hover:text-green-900
                    leading-none font-bold text-sm" title="삭제">×</button>
        </span>`).join('');
}

// ─ 제외 키워드 태그 렌더링
function renderExcludeKeywordTags() {
    const container = document.getElementById('exclude-keywords-tags');
    if (!container) return;

    if (currentExcludeKeywords.length === 0) {
        container.innerHTML = '<span class="text-xs text-gray-400 italic">설정된 제외 키워드가 없습니다.</span>';
        return;
    }

    container.innerHTML = currentExcludeKeywords.map((kw, i) => `
        <span class="inline-flex items-center gap-1 px-2 py-0.5 bg-red-100 text-red-800
                     border border-red-300 rounded-full text-xs font-medium">
            ${escHtml(kw)}
            <button onclick="removeExcludeKeyword(${i})" class="ml-0.5 text-red-600 hover:text-red-900
                    leading-none font-bold text-sm" title="삭제">×</button>
        </span>`).join('');
}

// ─ HTML 이스케이프 (XSS 방지)
function escHtml(s) {
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

// ─ 관심 키워드 추가
function addKeyword() {
    const input = document.getElementById('new-keyword-input');
    if (!input) return;
    const kw = input.value.trim();
    if (!kw) return;
    if (currentKeywords.includes(kw)) { alert('이미 추가된 키워드입니다.'); return; }
    currentKeywords.push(kw);
    input.value = '';
    renderKeywordTags();
}

// ─ 관심 키워드 삭제
function removeKeyword(index) {
    currentKeywords.splice(index, 1);
    renderKeywordTags();
}

// ─ 제외 키워드 추가
function addExcludeKeyword() {
    const input = document.getElementById('new-exclude-keyword-input');
    if (!input) return;
    const kw = input.value.trim();
    if (!kw) return;
    if (currentExcludeKeywords.includes(kw)) { alert('이미 추가된 키워드입니다.'); return; }
    currentExcludeKeywords.push(kw);
    input.value = '';
    renderExcludeKeywordTags();
}

// ─ 제외 키워드 삭제
function removeExcludeKeyword(index) {
    currentExcludeKeywords.splice(index, 1);
    renderExcludeKeywordTags();
}

// ─ 금액 범위 입력창 채우기
function loadBudgetRangeInputs(br) {
    if (!br) return;

    // min 값
    if (br.min != null) {
        const { val, unit } = decomposeAmount(br.min);
        document.getElementById('budget-min').value = val;
        document.getElementById('budget-min-unit').value = String(unit);
    }
    // max 값
    if (br.max != null) {
        const { val, unit } = decomposeAmount(br.max);
        document.getElementById('budget-max').value = val;
        document.getElementById('budget-max-unit').value = String(unit);
    }
    updateBudgetPreview();
}

// ─ 원 단위 금액을 (값, 단위) 로 분해 (억 > 만 > 원 순)
function decomposeAmount(amount) {
    if (amount >= 100000000 && amount % 100000000 === 0) return { val: amount / 100000000, unit: 100000000 };
    if (amount >= 10000 && amount % 10000 === 0) return { val: amount / 10000, unit: 10000 };
    return { val: amount, unit: 1 };
}

// ─ 입력된 금액(원 단위)으로 변환
function readBudgetAmount(inputId, unitId) {
    const v = parseFloat(document.getElementById(inputId).value);
    const u = parseInt(document.getElementById(unitId).value, 10);
    if (isNaN(v) || v <= 0) return null;
    return Math.round(v * u);
}

// ─ 금액 범위 미리보기 업데이트
function updateBudgetPreview() {
    const minAmt = readBudgetAmount('budget-min', 'budget-min-unit');
    const maxAmt = readBudgetAmount('budget-max', 'budget-max-unit');
    const preview = document.getElementById('budget-range-preview');
    if (!preview) return;

    if (minAmt == null && maxAmt == null) {
        preview.classList.add('hidden');
        return;
    }

    const fmt = n => n.toLocaleString('ko-KR') + '원';
    let text = '';
    if (minAmt != null && maxAmt != null) text = `${fmt(minAmt)} ~ ${fmt(maxAmt)}`;
    else if (minAmt != null) text = `${fmt(minAmt)} 이상`;
    else text = `${fmt(maxAmt)} 이하`;

    preview.textContent = '적용 범위: ' + text;
    preview.classList.remove('hidden');
}

// ─ 금액 범위 초기화
function clearBudgetRange() {
    document.getElementById('budget-min').value = '';
    document.getElementById('budget-max').value = '';
    document.getElementById('budget-min-unit').value = '1';
    document.getElementById('budget-max-unit').value = '1';
    updateBudgetPreview();
}

// ─ 필터 저장 (관심 키워드 + 제외 키워드 + 금액 범위)
async function saveKeywordFilters() {
    const minAmt = readBudgetAmount('budget-min', 'budget-min-unit');
    const maxAmt = readBudgetAmount('budget-max', 'budget-max-unit');

    if (minAmt != null && maxAmt != null && minAmt > maxAmt) {
        alert('최소 금액이 최대 금액보다 클 수 없습니다.');
        return;
    }

    const payload = {
        keywords: currentKeywords,
        exclude_keywords: currentExcludeKeywords,
        budget_range: { min: minAmt, max: maxAmt }
    };

    try {
        const response = await fetch('/api/interest-keywords', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const data = await response.json();

        if (response.ok) {
            alert('필터 설정이 저장되었습니다.');
        } else {
            alert('저장 실패: ' + (data.error || '알 수 없는 오류'));
        }
    } catch (error) {
        console.error('Failed to save keyword filters:', error);
        alert('저장 중 오류가 발생했습니다.');
    }
}

// saveKeywords는 saveSettings에서 참조하므로 alias 유지
function saveKeywords() { saveKeywordFilters(); }

// 페이지 로드 시 필터 및 이메일 설정 로드
document.addEventListener('DOMContentLoaded', function() {
    loadInterestKeywords();
    loadEmailSettings();
});

// 금액 단위 변경 시 미리보기 갱신 (HTML onchange에서 직접 연결)
document.addEventListener('DOMContentLoaded', function() {
    ['budget-min', 'budget-min-unit', 'budget-max', 'budget-max-unit'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.addEventListener('input', updateBudgetPreview);
    });
});

// ============= 이메일 설정 관리 =============

// 이메일 서비스별 도움말 정보
const emailServiceHelp = {
    gmail: {
        name: 'Gmail',
        helpHtml: `<strong>Gmail 사용 시:</strong> Gmail 계정의 2단계 인증을 활성화하고 "앱 비밀번호"를 생성해야 합니다.<br>
                   <a href="https://myaccount.google.com/apppasswords" target="_blank" class="underline">앱 비밀번호 생성하기</a>`,
        passwordLabel: 'Gmail 앱 비밀번호',
        passwordHelp: 'Gmail 2단계 인증 후 생성한 앱 비밀번호를 입력하세요',
        passwordPlaceholder: '16자리 앱 비밀번호'
    },
    naver: {
        name: '네이버 메일',
        helpHtml: `<strong>네이버 메일 사용 시:</strong> 네이버 계정의 일반 비밀번호를 사용합니다.<br>
                   <a href="https://mail.naver.com" target="_blank" class="underline">네이버 메일</a>`,
        passwordLabel: '네이버 비밀번호',
        passwordHelp: '네이버 계정 비밀번호를 입력하세요',
        passwordPlaceholder: '네이버 계정 비밀번호'
    },
    daum: {
        name: '다음/카카오 메일',
        helpHtml: `<strong>다음/카카오 메일 사용 시:</strong> 다음 계정의 일반 비밀번호를 사용합니다.<br>
                   <a href="https://mail.daum.net" target="_blank" class="underline">다음 메일</a>`,
        passwordLabel: '다음 비밀번호',
        passwordHelp: '다음 계정 비밀번호를 입력하세요',
        passwordPlaceholder: '다음 계정 비밀번호'
    },
    outlook: {
        name: 'Outlook/Hotmail',
        helpHtml: `<strong>Outlook/Hotmail 사용 시:</strong> Microsoft 계정의 일반 비밀번호를 사용합니다.<br>
                   <a href="https://outlook.live.com" target="_blank" class="underline">Outlook 메일</a>`,
        passwordLabel: 'Microsoft 비밀번호',
        passwordHelp: 'Microsoft 계정 비밀번호를 입력하세요',
        passwordPlaceholder: 'Microsoft 계정 비밀번호'
    }
};

// 이메일 서비스 선택 시 도움말 업데이트
function updateEmailServiceHelp() {
    const service = document.getElementById('email-service').value;
    const helpInfo = emailServiceHelp[service];

    if (helpInfo) {
        document.getElementById('email-service-help').innerHTML =
            `<p class="text-xs text-blue-800">${helpInfo.helpHtml}</p>`;
        document.getElementById('password-label').textContent = helpInfo.passwordLabel;
        document.getElementById('password-help').textContent = helpInfo.passwordHelp;
        document.getElementById('sender-password').placeholder = helpInfo.passwordPlaceholder;
    }
}

// 이메일 설정 로드
async function loadEmailSettings() {
    try {
        const response = await fetch('/api/email-settings');
        const data = await response.json();

        if (response.ok && data.settings) {
            const settings = data.settings;

            // 폼에 값 채우기
            document.getElementById('email-enabled').checked = settings.enabled || false;
            document.getElementById('email-service').value = settings.email_service || 'gmail';
            document.getElementById('sender-email').value = settings.sender_email || '';
            document.getElementById('sender-password').value = settings.sender_password || '';
            document.getElementById('recipient-email').value = settings.recipient_email || '';
            document.getElementById('new-tender-alert').checked = settings.new_tender_alert || false;
            document.getElementById('deadline-alert').checked = settings.deadline_alert || false;
            document.getElementById('keyword-alert').checked = settings.keyword_alert || false;

            // 이메일 서비스 도움말 업데이트
            updateEmailServiceHelp();
        }
    } catch (error) {
        console.error('Failed to load email settings:', error);
    }
}

// 이메일 설정 저장
async function saveEmailSettings() {
    const settings = {
        enabled: document.getElementById('email-enabled').checked,
        email_service: document.getElementById('email-service').value,
        sender_email: document.getElementById('sender-email').value.trim(),
        sender_password: document.getElementById('sender-password').value.trim(),
        recipient_email: document.getElementById('recipient-email').value.trim(),
        new_tender_alert: document.getElementById('new-tender-alert').checked,
        deadline_alert: document.getElementById('deadline-alert').checked,
        keyword_alert: document.getElementById('keyword-alert').checked
    };

    // 유효성 검사
    if (settings.enabled) {
        if (!settings.sender_email || !settings.sender_password || !settings.recipient_email) {
            alert('이메일 알림을 활성화하려면 모든 이메일 정보를 입력해야 합니다.');
            return;
        }

        // 이메일 형식 기본 검증
        if (!settings.sender_email.includes('@') || !settings.recipient_email.includes('@')) {
            alert('올바른 이메일 주소를 입력하세요.');
            return;
        }
    }

    try {
        const response = await fetch('/api/email-settings', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(settings)
        });

        const data = await response.json();

        if (response.ok) {
            alert('이메일 설정이 저장되었습니다.');
        } else {
            alert('저장 실패: ' + (data.error || '알 수 없는 오류'));
        }
    } catch (error) {
        console.error('Failed to save email settings:', error);
        alert('저장 중 오류가 발생했습니다.');
    }
}

// 테스트 이메일 발송
async function testEmail() {
    const emailService = document.getElementById('email-service').value;
    const senderEmail = document.getElementById('sender-email').value.trim();
    const senderPassword = document.getElementById('sender-password').value.trim();
    const recipientEmail = document.getElementById('recipient-email').value.trim();

    if (!senderEmail || !senderPassword || !recipientEmail) {
        alert('모든 이메일 정보를 입력해야 테스트 이메일을 발송할 수 있습니다.');
        return;
    }

    if (!confirm('테스트 이메일을 발송하시겠습니까?')) {
        return;
    }

    try {
        const response = await fetch('/api/test-email', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                email_service: emailService,
                sender_email: senderEmail,
                sender_password: senderPassword,
                recipient_email: recipientEmail
            })
        });

        const data = await response.json();

        if (response.ok) {
            alert('테스트 이메일이 발송되었습니다. 받은 편지함을 확인하세요.');
        } else {
            alert('이메일 발송 실패: ' + (data.error || '알 수 없는 오류'));
        }
    } catch (error) {
        console.error('Failed to send test email:', error);
        alert('이메일 발송 중 오류가 발생했습니다.');
    }
}

// Gemini API 키 로드
async function loadGeminiKeyStatus() {
    try {
        const resp = await fetch('/api/settings/gemini-key');
        const data = await resp.json();
        const status = document.getElementById('gemini-key-status');
        if (data.has_key) {
            status.innerHTML = `✅ 서버에 로드됨: <strong>${data.masked}</strong>`;
            status.className = 'text-xs text-green-600 mt-1';
        } else {
            status.innerHTML = '❌ 서버에 API 키 없음 — 아래에서 키를 입력하고 저장하세요.';
            status.className = 'text-xs text-red-500 mt-1';
        }
    } catch (e) {
        console.error('Gemini key status load failed:', e);
    }
}

// Gemini API 키 저장
async function saveGeminiKey() {
    const key = document.getElementById('gemini-api-key').value.trim();
    if (!key) {
        alert('API 키를 입력해 주세요.');
        return;
    }
    try {
        const resp = await fetch('/api/settings/gemini-key', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ api_key: key })
        });
        const data = await resp.json();
        if (resp.ok) {
            alert(data.message || 'Gemini API 키가 저장되었습니다.');
            document.getElementById('gemini-api-key').value = '';
            loadGeminiKeyStatus();
        } else {
            alert('저장 실패: ' + (data.error || '알 수 없는 오류'));
        }
    } catch (e) {
        alert('저장 중 오류가 발생했습니다: ' + e.message);
    }
}

// 페이지 로드 시 Gemini 키 상태 로드
document.addEventListener('DOMContentLoaded', function() {
    loadGeminiKeyStatus();
});
