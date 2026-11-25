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
    assert _run("m.hsScoreTip(83.7, {keyword: 36.9, type: 25, case: 79, agency: 0, base: 88.4})") == \
        '적합도 83.7 = 키워드·유형 88.4 와 담은 공고 닮음 79.0 의 평균'


def test_score_tip_with_plus_adjust():
    assert _run("m.hsScoreTip(98.6, {keyword: 30, type: 25, case: null, agency: 20, base: 78.6})") == \
        '적합도 98.6 = 키워드·유형 78.6 + 발주처 +20'


def test_score_tip_with_minus_adjust():
    assert _run("m.hsScoreTip(48.6, {keyword: 30, type: 25, case: null, agency: -30, base: 78.6})") == \
        '적합도 48.6 = 키워드·유형 78.6 + 발주처 −30'


def test_score_tip_case_and_adjust_together():
    assert _run("m.hsScoreTip(93.7, {keyword: 36.9, type: 25, case: 79, agency: 10, base: 88.4})") == \
        '적합도 93.7 = 키워드·유형 88.4 와 담은 공고 닮음 79.0 의 평균 + 발주처 +10'


def test_score_tip_without_score_or_breakdown():
    assert _run("m.hsScoreTip(null, null)") == '적합도 없음'
    assert _run("m.hsScoreTip(51.2, null)") == '적합도 51.2'
    # 저장해 둔 예전 응답(구성에 base 가 없다)을 그릴 때도 깨지지 않는다
    assert _run("m.hsScoreTip(51.2, {keyword: 7, type: 25, agency: 5})") == '적합도 51.2'


def test_adjust_chip():
    assert _run("m.hsAdjustChip({agency: 20})") == '<span class="hs-chip hs-chip-ok" title="등록한 발주처 가점">발주처 +20</span>'
    assert _run("m.hsAdjustChip({agency: -30})") == '<span class="hs-chip hs-chip-bad" title="등록한 발주처 감점">발주처 −30</span>'
    assert _run("m.hsAdjustChip({agency: 0})") == '' and _run("m.hsAdjustChip(null)") == ''
