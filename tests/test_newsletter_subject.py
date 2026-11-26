"""메일 제목과 보내는 사람 — 누가 보내는지 드러나야 한다 (2026-11-26 사용자 요청).

제목: "[High-Search] 2026.11.26. HR 뉴스 / 입찰동향", 보내는 사람 이름: High-Search.
"""
import newsletter as nl


def _data(news=True, tenders=True):
    return {'run_date': '2026-11-26',
            'sections': [{'headline': '아주 긴 머리기사 제목'}] if news else [],
            'tenders': {'items': [{'id': 1}], 'sections': []} if tenders else None}


def test_subject_names_sender_date_and_contents():
    assert nl.subject_for(_data()) == '[High-Search] 2026.11.26. HR 뉴스 / 입찰동향'


def test_subject_lists_only_what_the_mail_carries():
    assert nl.subject_for(_data(tenders=False)) == '[High-Search] 2026.11.26. HR 뉴스'
    assert nl.subject_for(_data(news=False)) == '[High-Search] 2026.11.26. 입찰동향'
    empty = _data(tenders=False)
    empty['tenders'] = {'items': [], 'sections': []}          # 입찰동향 칸은 있으나 실린 공고가 없다
    assert nl.subject_for(empty) == '[High-Search] 2026.11.26. HR 뉴스'


def test_subject_pads_month_and_day():
    d = _data()
    d['run_date'] = '2027-01-05'
    assert nl.subject_for(d).startswith('[High-Search] 2027.01.05. ')


def test_default_sender_name_is_high_search(monkeypatch):
    monkeypatch.setattr(nl, '_cfg', lambda path, default=None: default)
    assert nl.smtp_config()['from_name'] == 'High-Search'
