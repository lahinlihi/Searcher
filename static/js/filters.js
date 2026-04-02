// 필터 관리 페이지 JavaScript

let editingFilterId = null;

// 페이지 로드 시 실행
document.addEventListener('DOMContentLoaded', function() {
    loadFilters();
});

// 필터 목록 로드
async function loadFilters() {
    try {
        const response = await fetch('/api/filters');
        const filters = await response.json();

        const container = document.getElementById('filters-list');

        if (!filters || filters.length === 0) {
            container.innerHTML = '<p class="text-gray-500">저장된 필터가 없습니다.</p>';
            return;
        }

        const html = filters.map(filter => {
            const defaultBadge = filter.is_default
                ? '<span class="badge badge-success ml-2">기본값</span>'
                : '';

            return `
                <div class="card">
                    <div class="card-body">
                        <div class="flex justify-between items-start">
                            <div>
                                <h4 class="font-semibold text-lg">${filter.name}${defaultBadge}</h4>
                                <div class="mt-2 space-y-1 text-sm text-gray-600">
                                    <p><strong>포함 키워드:</strong> ${filter.include_keywords.join(', ') || '없음'}</p>
                                    <p><strong>제외 키워드:</strong> ${filter.exclude_keywords.join(', ') || '없음'}</p>
                                    ${filter.min_price ? `<p><strong>최소 금액:</strong> ${formatPrice(filter.min_price)}</p>` : ''}
                                    ${filter.max_price ? `<p><strong>최대 금액:</strong> ${formatPrice(filter.max_price)}</p>` : ''}
                                </div>
                            </div>
                            <div class="flex gap-2">
                                <button onclick="editFilter(${filter.id})" class="btn-primary">수정</button>
                                <button onclick="deleteFilter(${filter.id})" class="btn-danger">삭제</button>
                            </div>
                        </div>
                    </div>
                </div>
            `;
        }).join('');

        container.innerHTML = html;

    } catch (error) {
        console.error('Failed to load filters:', error);
    }
}

// 필터 생성 모달 표시
function showCreateFilterModal() {
    editingFilterId = null;
    document.getElementById('modal-title').textContent = '새 필터 만들기';
    document.getElementById('modal-filter-name').value = '';
    document.getElementById('modal-include-keywords').value = '';
    document.getElementById('modal-exclude-keywords').value = '';
    document.getElementById('modal-is-default').checked = false;

    document.getElementById('filter-modal').classList.remove('hidden');
}

// 필터 수정
async function editFilter(filterId) {
    editingFilterId = filterId;

    try {
        const response = await fetch('/api/filters');
        const filters = await response.json();

        const filter = filters.find(f => f.id === filterId);
        if (!filter) return;

        document.getElementById('modal-title').textContent = '필터 수정';
        document.getElementById('modal-filter-name').value = filter.name;
        document.getElementById('modal-include-keywords').value = filter.include_keywords.join(', ');
        document.getElementById('modal-exclude-keywords').value = filter.exclude_keywords.join(', ');
        document.getElementById('modal-is-default').checked = filter.is_default;

        document.getElementById('filter-modal').classList.remove('hidden');

    } catch (error) {
        console.error('Failed to load filter:', error);
    }
}

// 필터 저장
async function saveFilter() {
    const name = document.getElementById('modal-filter-name').value.trim();
    const includeKeywords = document.getElementById('modal-include-keywords').value
        .split(',')
        .map(k => k.trim())
        .filter(k => k);
    const excludeKeywords = document.getElementById('modal-exclude-keywords').value
        .split(',')
        .map(k => k.trim())
        .filter(k => k);
    const isDefault = document.getElementById('modal-is-default').checked;

    if (!name) {
        alert('필터 이름을 입력하세요.');
        return;
    }

    const data = {
        name: name,
        include_keywords: includeKeywords,
        exclude_keywords: excludeKeywords,
        is_default: isDefault
    };

    try {
        let response;
        if (editingFilterId) {
            // 수정
            response = await fetch(`/api/filters/${editingFilterId}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(data)
            });
        } else {
            // 생성
            response = await fetch('/api/filters', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(data)
            });
        }

        if (response.ok) {
            closeFilterModal();
            loadFilters();
        } else {
            const error = await response.json();
            alert('저장 실패: ' + error.error);
        }

    } catch (error) {
        console.error('Failed to save filter:', error);
        alert('저장 중 오류가 발생했습니다.');
    }
}

// 필터 삭제
async function deleteFilter(filterId) {
    if (!confirm('정말 이 필터를 삭제하시겠습니까?')) {
        return;
    }

    try {
        const response = await fetch(`/api/filters/${filterId}`, {
            method: 'DELETE'
        });

        if (response.ok) {
            loadFilters();
        } else {
            const error = await response.json();
            alert('삭제 실패: ' + error.error);
        }

    } catch (error) {
        console.error('Failed to delete filter:', error);
        alert('삭제 중 오류가 발생했습니다.');
    }
}

// 모달 닫기
function closeFilterModal() {
    document.getElementById('filter-modal').classList.add('hidden');
}

// 가격 포맷
function formatPrice(price) {
    if (price >= 100000000) {
        return (price / 100000000).toFixed(1) + '억원';
    } else if (price >= 10000000) {
        return (price / 10000000).toFixed(1) + '천만원';
    } else if (price >= 10000) {
        return (price / 10000).toFixed(0) + '만원';
    } else {
        return price.toLocaleString() + '원';
    }
}
