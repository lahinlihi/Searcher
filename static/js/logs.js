// 로그 페이지 JavaScript

// 페이지 로드 시 실행
document.addEventListener('DOMContentLoaded', function() {
    loadLogs();
});

// 로그 목록 로드
async function loadLogs() {
    try {
        const response = await fetch('/api/logs');
        const logs = await response.json();

        const container = document.getElementById('logs-list');

        if (!logs || logs.length === 0) {
            container.innerHTML = '<p class="text-gray-500">크롤링 로그가 없습니다.</p>';
            return;
        }

        const html = logs.map(log => {
            const startTime = new Date(log.started_at).toLocaleString('ko-KR');
            const endTime = log.completed_at
                ? new Date(log.completed_at).toLocaleString('ko-KR')
                : '진행중';

            let statusBadge = '';
            if (log.status === 'completed') {
                statusBadge = '<span class="badge badge-success">완료</span>';
            } else if (log.status === 'failed') {
                statusBadge = '<span class="badge badge-danger">실패</span>';
            } else {
                statusBadge = '<span class="badge badge-warning">진행중</span>';
            }

            const siteResults = log.site_results || {};
            const siteResultsHtml = Object.entries(siteResults).map(([site, result]) => {
                const icon = result.success ? '✓' : '✗';
                const color = result.success ? 'text-green-600' : 'text-red-600';
                return `<span class="${color}">${site}: ${icon}</span>`;
            }).join(' | ');

            return `
                <div class="card">
                    <div class="card-body">
                        <div class="flex justify-between items-start mb-2">
                            <div>
                                <h4 class="font-semibold">${startTime}</h4>
                                ${statusBadge}
                            </div>
                        </div>
                        <div class="text-sm text-gray-600 space-y-1">
                            <p><strong>완료 시간:</strong> ${endTime}</p>
                            <p><strong>수집:</strong> ${log.total_found || 0}건 | <strong>새 공고:</strong> ${log.new_tenders || 0}건</p>
                            ${siteResultsHtml ? `<p><strong>사이트 결과:</strong> ${siteResultsHtml}</p>` : ''}
                            ${log.error_message ? `<p class="text-red-600"><strong>오류:</strong> ${log.error_message}</p>` : ''}
                        </div>
                    </div>
                </div>
            `;
        }).join('');

        container.innerHTML = html;

    } catch (error) {
        console.error('Failed to load logs:', error);
    }
}
