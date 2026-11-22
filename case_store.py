"""사례로 배우는 점수 — 저장과 조회 (사례, 놓친 공고 신고, 채점 이력, 정렬 설정).

모두 현재 Flask 앱의 db.session 을 쓴다. 테이블 정의는 database.py 에 있다.
"""
import json
from datetime import datetime

from database import db, CaseExample, MissedReport, CaseEvalRun, CaseSortSetting


# ── 사례 ──────────────────────────────────────────────────────────────────────

def add_case(user_id, tender_id, source):
    """좋은 사례로 넣는다. 새로 넣었으면 True, 이미 있었으면 False."""
    if CaseExample.query.filter_by(user_id=user_id, tender_id=tender_id).first():
        return False
    db.session.add(CaseExample(user_id=user_id, tender_id=tender_id, source=source))
    db.session.commit()
    return True


def remove_case(user_id, tender_id):
    n = CaseExample.query.filter_by(user_id=user_id, tender_id=tender_id).delete()
    db.session.commit()
    return n > 0


def case_tender_ids(user_id):
    """신고·[좋음]으로 넣은 공고 id (북마크는 포함하지 않는다)."""
    return {r.tender_id for r in CaseExample.query.filter_by(user_id=user_id).all()}


# ── 놓친 공고 신고 ────────────────────────────────────────────────────────────

def save_report(user_id, query, tender_id, verdict, detail, source_note=None):
    r = MissedReport(user_id=user_id, query=query, tender_id=tender_id, verdict=verdict,
                     detail=json.dumps(detail, ensure_ascii=False, default=str),
                     source_note=source_note)
    db.session.add(r)
    db.session.commit()
    return r.id


def report_counts(user_id):
    rows = (db.session.query(MissedReport.verdict, db.func.count())
            .filter(MissedReport.user_id == user_id)
            .group_by(MissedReport.verdict).all())
    return {v: n for v, n in rows}


# ── 채점 ──────────────────────────────────────────────────────────────────────

def _eval_dict(r):
    return {'id': r.id, 'run_at': r.run_at.isoformat(timespec='seconds'), 'metrics': json.loads(r.metrics)}


def save_eval(user_id, metrics):
    r = CaseEvalRun(user_id=user_id, metrics=json.dumps(metrics, ensure_ascii=False))
    db.session.add(r)
    db.session.commit()
    return r.id


def eval_history(user_id, limit=20):
    rows = (CaseEvalRun.query.filter_by(user_id=user_id)
            .order_by(CaseEvalRun.id.desc()).limit(limit).all())
    return [_eval_dict(r) for r in rows]


def latest_eval(user_id):
    hist = eval_history(user_id, limit=1)
    return hist[0] if hist else None


# ── 정렬 설정 ─────────────────────────────────────────────────────────────────

def get_sort_enabled(user_id):
    s = db.session.get(CaseSortSetting, user_id)
    return bool(s and s.enabled)


def set_sort_enabled(user_id, enabled):
    s = db.session.get(CaseSortSetting, user_id)
    if s is None:
        s = CaseSortSetting(user_id=user_id)
        db.session.add(s)
    s.enabled = bool(enabled)
    s.changed_at = datetime.now()
    db.session.commit()
