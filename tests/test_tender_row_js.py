"""tender-row.js 의 순수 함수 확인 (node 가 있을 때만)."""
import json
import os
import shutil
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
node = shutil.which('node')
pytestmark = pytest.mark.skipif(node is None, reason='node 가 없다')


def _run(expr):
    js = os.path.join(ROOT, 'static', 'js', 'tender-row.js').replace('\\', '/')
    out = subprocess.run([node, '-e', f"const m = require('{js}'); console.log(JSON.stringify({expr}))"],
                         capture_output=True, text=True, encoding='utf-8', timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def test_score_tip_with_case():
    assert _run("m.hsScoreTip(83.7, {keyword: 36.9, type: 25, case: 79, agency: null, base: 88.4})") == \
        '적합도 83.7 = 키워드·유형 88.4 와 담은 공고 닮음 79.0 의 평균'


def test_score_tip_without_case():
    assert _run("m.hsScoreTip(78.6, {keyword: 30, type: 25, case: null, agency: null, base: 78.6})") == \
        '적합도 78.6 = 키워드·유형 78.6'


def test_score_tip_never_mentions_agency():
    """발주처는 점수에 들어가지 않는다 — 구성 설명에도 나오지 않는다."""
    for mark in ('key', 'low'):
        tip = _run(f"m.hsScoreTip(78.6, {{keyword: 30, type: 25, case: null, agency: '{mark}', base: 78.6}})")
        assert tip == '적합도 78.6 = 키워드·유형 78.6'


def test_score_tip_without_score_or_breakdown():
    assert _run("m.hsScoreTip(null, null)") == '적합도 없음'
    assert _run("m.hsScoreTip(51.2, null)") == '적합도 51.2'
    # 저장해 둔 예전 응답(구성에 base 가 없다)을 그릴 때도 깨지지 않는다
    assert _run("m.hsScoreTip(51.2, {keyword: 7, type: 25, agency: 5})") == '적합도 51.2'


def test_agency_chip():
    assert _run("m.hsAgencyChip({agency: 'key'})") == \
        '<span class="hs-chip hs-chip-key" title="중점으로 등록한 발주처 — 적합도에는 들어가지 않습니다">중점 발주처</span>'
    assert _run("m.hsAgencyChip({agency: 'low'})") == \
        '<span class="hs-chip hs-chip-low" title="후순위로 등록한 발주처 — 적합도는 그대로이고 목록 아래에 나옵니다">후순위 발주처</span>'
    for none in ("{agency: null}", "null", "{agency: 20}", "{}"):
        assert _run(f"m.hsAgencyChip({none})") == ''


def test_rank_puts_low_last_and_key_first_on_ties():
    order = _run("""m.hsRankSort([
        {id: 1, relevance_score: 90, score_breakdown: {agency: 'low'}},
        {id: 2, relevance_score: 60, score_breakdown: {agency: null}},
        {id: 3, relevance_score: 60, score_breakdown: {agency: 'key'}},
        {id: 4, relevance_score: 70},
        {id: 5, relevance_score: 95, score_breakdown: {agency: 'low'}},
    ]).map(t => t.id)""")
    assert order == [4, 3, 2, 5, 1]
