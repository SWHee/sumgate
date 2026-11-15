"""T6: 은행 회신 검증. 성공과 반려만 받고, 나머지는 상태를 바꾸지 않고 거부하며 거부 사유를 이력에 남긴다."""
import json
import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import service as sv
from app.models import Case, EventLog, RebateRequest, Task


def pays(s):
    return list(s.scalars(select(Task).where(Task.type == "회계 지급").order_by(Task.id)))


def snapshot(s):
    s.expire_all()
    return ([(t.id, t.status) for t in s.scalars(select(Task).order_by(Task.id))],
            [(c.id, c.status) for c in s.scalars(select(Case).order_by(Case.id))],
            [(r.rebate_id, r.status) for r in s.scalars(select(RebateRequest).order_by(RebateRequest.rebate_id))])


def rejections(s):
    return list(s.scalars(select(EventLog).where(EventLog.action == "은행 회신 거부").order_by(EventLog.id)))


@pytest.fixture
def waiting(s):
    sv.approve_all_support(s)
    sv.execute_all(s)
    return pays(s)[0]


@pytest.mark.parametrize("bad", ["실패", "", "success", " 성공", "반려 "])
def test_unknown_result_rejected_without_state_change(s, waiting, bad):
    before = snapshot(s)
    with pytest.raises(ValueError, match="성공 또는 반려"):
        sv.bank_reply(s, waiting.id, bad)
    assert snapshot(s) == before  # 반려로 처리되지 않는다
    assert not list(s.scalars(select(Task).where(Task.type == "은행 재처리")))
    assert len(rejections(s)) == 1 and "성공 또는 반려" in rejections(s)[0].detail


def test_bulk_unknown_result_rejected(s, waiting):
    before = snapshot(s)
    with pytest.raises(ValueError, match="성공 또는 반려"):
        sv.bank_reply_all(s, "보류")
    assert snapshot(s) == before and len(rejections(s)) == 1


def test_reply_to_paid_cancelled_or_missing_task_rejected(s, waiting):
    sv.bank_reply(s, waiting.id, "성공")
    before = snapshot(s)
    with pytest.raises(ValueError, match="이미 지급 완료"):
        sv.bank_reply(s, waiting.id, "반려")
    with pytest.raises(ValueError, match="없는 작업"):
        sv.bank_reply(s, 999999, "성공")
    other = pays(s)[1]
    other.status = "취소"
    s.commit()
    before = snapshot(s)
    with pytest.raises(ValueError, match="취소된 작업"):
        sv.bank_reply(s, other.id, "성공")
    assert snapshot(s) == before
    assert [e.ref for e in rejections(s)] == [f"작업 {waiting.id}", "작업 999999", f"작업 {other.id}"]


def test_reject_reason_shown_on_retry_task(s, waiting):
    sv.bank_reply(s, waiting.id, "반려", reason="예금주 불일치")
    t2 = pays(s)[1]
    sv.bank_reply(s, t2.id, "반려")
    retries = list(s.scalars(select(Task).where(Task.type == "은행 재처리").order_by(Task.id)))
    assert [json.loads(r.payload)["반려 사유"] for r in retries] == ["예금주 불일치", "사유 미기재"]


def test_http_bad_result_is_refused_and_logged(db_url, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", db_url)
    from app.main import app
    with TestClient(app) as cl:
        cl.get("/role?r=영업지원")
        cl.post("/bulk/approve-support")
        cl.get("/role?r=회계")
        cl.post("/bulk/execute")
        cl.get("/role?r=모의 외부")
        tid = int(re.search(r'/tasks/(\d+)/bank"', cl.get("/tasks").text).group(1))
        for data in ({"result": "보류"}, {}):
            r = cl.post(f"/tasks/{tid}/bank", data=data)
            assert r.status_code == 200 and "처리하지 않음" in r.text and "성공 또는 반려" in r.text
        r = cl.post(f"/tasks/{tid}/bank", data={"result": "반려", "reason": "계좌 해지"})
        assert "반려 사유: 계좌 해지" in cl.get("/tasks").text
        assert "이미 지급 반려" in cl.post(f"/tasks/{tid}/bank", data={"result": "성공"}).text
        log = cl.get("/log").text
        assert log.count("은행 회신 거부") == 3
