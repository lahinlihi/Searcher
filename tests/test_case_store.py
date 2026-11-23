import case_store


def test_add_case_idempotent(app, make_user, make_tender):
    u, t = make_user(), make_tender(title='AI 교육 운영 용역')
    assert case_store.add_case(u.id, t.id, 'report') is True
    assert case_store.add_case(u.id, t.id, 'similar') is False
    assert case_store.case_tender_ids(u.id) == {t.id}


def test_remove_case(app, make_user, make_tender):
    u, t = make_user(), make_tender()
    case_store.add_case(u.id, t.id, 'report')
    assert case_store.remove_case(u.id, t.id) is True
    assert case_store.case_tender_ids(u.id) == set()
    assert case_store.remove_case(u.id, t.id) is False


def test_cases_are_per_user(app, make_user, make_tender):
    a, b, t = make_user(), make_user(), make_tender()
    case_store.add_case(a.id, t.id, 'report')
    assert case_store.case_tender_ids(b.id) == set()


def test_report_counts(app, make_user):
    u = make_user()
    case_store.save_report(u.id, 'x', 1, '순위 낮음', {'rank': 30})
    case_store.save_report(u.id, 'y', 2, '순위 낮음', {})
    rid = case_store.save_report(u.id, 'Z123', None, '수집 안 됨', {}, source_note='기관 홈페이지')
    assert isinstance(rid, int)
    assert case_store.report_counts(u.id) == {'순위 낮음': 2, '수집 안 됨': 1}


def test_eval_roundtrip(app, make_user):
    u = make_user()
    case_store.save_eval(u.id, {'answers': 1})
    case_store.save_eval(u.id, {'answers': 2})
    latest = case_store.latest_eval(u.id)
    assert latest['metrics'] == {'answers': 2}
    assert isinstance(latest['run_at'], str)
    hist = case_store.eval_history(u.id)
    assert [h['metrics']['answers'] for h in hist] == [2, 1]
    assert case_store.latest_eval(u.id + 999) is None


def test_sort_setting_default_off(app, make_user):
    u = make_user()
    assert case_store.get_sort_enabled(u.id) is False
    case_store.set_sort_enabled(u.id, True)
    assert case_store.get_sort_enabled(u.id) is True
    case_store.set_sort_enabled(u.id, False)
    assert case_store.get_sort_enabled(u.id) is False
