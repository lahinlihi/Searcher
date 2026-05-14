// 필터 관리 페이지 JavaScript

let editingFilterId = null;

// 페이지 로드 시 실행
document.addEventListener('DOMContentLoaded', function() {
    loadFilters();
    initAgencyWeightSelector();
    loadAgencyWeights();
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

// ── 기관별 가중치 ────────────────────────────────────────────────────────────

const AGENCY_WEIGHT_OPTIONS = [0, 2.5, 5, 7.5, 10];
let selectedAgencyWeight = 5.0;

function initAgencyWeightSelector() {
    const container = document.getElementById('agency-weight-selector');
    if (!container) return;
    container.innerHTML = AGENCY_WEIGHT_OPTIONS.map(w => {
        const isSelected = w === selectedAgencyWeight;
        const label = w === 5.0 ? `${w} (기본)` : String(w);
        return `<button type="button"
            onclick="selectAgencyWeight(${w})"
            id="awbtn-${w.toString().replace('.', '_')}"
            class="text-xs font-semibold px-2.5 py-1 rounded border transition-colors
                   ${isSelected ? 'bg-blue-600 text-white border-blue-600' : 'bg-white text-gray-600 border-gray-300 hover:border-blue-400'}"
        >${label}</button>`;
    }).join('');
}

function selectAgencyWeight(w) {
    selectedAgencyWeight = w;
    AGENCY_WEIGHT_OPTIONS.forEach(opt => {
        const btn = document.getElementById(`awbtn-${opt.toString().replace('.', '_')}`);
        if (!btn) return;
        if (opt === w) {
            btn.className = btn.className.replace('bg-white text-gray-600 border-gray-300 hover:border-blue-400', 'bg-blue-600 text-white border-blue-600');
        } else {
            btn.className = btn.className.replace('bg-blue-600 text-white border-blue-600', 'bg-white text-gray-600 border-gray-300 hover:border-blue-400');
        }
    });
}

async function loadAgencyWeights() {
    try {
        const res = await fetch('/api/agency-weights');
        const list = await res.json();
        renderAgencyWeights(list);
    } catch (e) { console.error('기관별 가중치 로드 실패:', e); }
}

function renderAgencyWeights(list) {
    const container = document.getElementById('agency-weights-list');
    if (!container) return;
    if (!list || list.length === 0) {
        container.innerHTML = '<p class="text-xs text-gray-400">등록된 기관이 없습니다. 기본값(5점)이 적용됩니다.</p>';
        return;
    }
    container.innerHTML = list.map(aw => {
        const weightColor = aw.weight >= 7.5 ? 'text-blue-700 font-bold'
                          : aw.weight >= 5   ? 'text-gray-700'
                          : aw.weight > 0    ? 'text-gray-400'
                          :                    'text-red-400 font-bold';
        return `<div class="flex items-center gap-2 text-sm py-1 px-2 bg-gray-50 rounded">
            <span class="flex-1 truncate font-medium text-gray-800">${aw.agency_name}</span>
            <div class="flex gap-1">
                ${AGENCY_WEIGHT_OPTIONS.map(w => {
                    const active = aw.weight === w;
                    return `<button type="button"
                        onclick="updateAgencyWeight(${aw.id}, ${w})"
                        class="text-xs px-1.5 py-0.5 rounded border transition-colors
                               ${active ? 'bg-blue-600 text-white border-blue-600' : 'bg-white text-gray-500 border-gray-200 hover:border-blue-400'}"
                    >${w}</button>`;
                }).join('')}
            </div>
            <button onclick="deleteAgencyWeight(${aw.id})"
                class="text-gray-300 hover:text-red-500 transition-colors ml-1 text-base leading-none"
                title="삭제">×</button>
        </div>`;
    }).join('');
}

async function addAgencyWeight() {
    const nameInput = document.getElementById('agency-name-input');
    const agency_name = (nameInput.value || '').trim();
    if (!agency_name) { nameInput.focus(); return; }

    const res = await fetch('/api/agency-weights', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ agency_name, weight: selectedAgencyWeight })
    });
    if (res.ok) {
        nameInput.value = '';
        const msg = document.getElementById('agency-save-msg');
        msg.classList.remove('hidden');
        setTimeout(() => msg.classList.add('hidden'), 2000);
        loadAgencyWeights();
    } else {
        const err = await res.json();
        alert(err.error || '등록 실패');
    }
}

async function updateAgencyWeight(id, weight) {
    await fetch(`/api/agency-weights/${id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ weight })
    });
    loadAgencyWeights();
}

async function deleteAgencyWeight(id) {
    await fetch(`/api/agency-weights/${id}`, { method: 'DELETE' });
    loadAgencyWeights();
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
