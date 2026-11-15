"""T6: 같은 작업 공간에 실제 스레드로 동시에 보낸 요청. 행 잠금과 버전 비교는 Postgres에서 의미가 있어 Postgres에서만 돈다.

기대: 승인 기록과 활성 지급 작업은 요청당 하나, 한쪽은 충돌 안내(처리하지 않음), 500 오류 없음.
"""
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote, unquote

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app import service as sv
from app.models import Approval, Case, EventLog, Task

pytestmark = pytest.mark.skipif(not os.environ.get("DATABASE_URL", "").startswith("postgres"),
                                reason="동시성 시험은 Postgres(DATABASE_URL)에서만 의미가 있다")
ROUNDS = 10


def race(app, cookies, calls):
    """calls(경로, 폼) 목록을 각자의 클라이언트로 동시에 보낸다. (상태 코드, 안내 문구) 목록."""
    gate = threading.Barrier(len(calls))

    def one(path, data):
        cl = TestClient(app, raise_server_exceptions=False, cookies=cookies, follow_redirects=False)
        gate.wait()
        r = cl.post(path, data=data)
        return r.status_code, unquote(r.headers.get("location", "").partition("msg=")[2]) or r.text[:200]
    with ThreadPoolExecutor(len(calls)) as ex:
        return [f.result() for f in [ex.submit(one, p, d) for p, d in calls]]


@pytest.fixture
def ws_app(db_url, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", db_url)
    from app import main
    with TestClient(main.app) as cl:
        cl.get("/role?r=영업지원")
        cl.post("/scenarios/reset")  # 작업 공간을 먼저 하나 만든다. 그래야 동시 요청이 같은 공간에서 부딪힌다
        ws = cl.cookies["ws"]
        yield main.app, ws, main.SPACES.sm(ws)


def cookies(ws, role):
    return {"ws": ws, "role": quote(role)}


def one_ok_one_conflict(res, ok):
    assert all(code == 303 for code, _ in res), res  # 500 없음
    msgs = sorted(m for _, m in res)
    assert sum(ok in m for m in msgs) == 1 and sum(m.startswith("처리하지 않음") for m in msgs) == 1, msgs


def test_parallel_approve_execute_and_bank(ws_app):
    app, ws, sm = ws_app
    with sm() as s:
        ids = [c.id for c in s.scalars(select(Case).where(Case.status == "전결 승인 대기").order_by(Case.id))][:ROUNDS]
    assert len(ids) == ROUNDS
    for cid in ids:  # (a) 같은 사건 동시 승인
        one_ok_one_conflict(race(app, cookies(ws, "영업지원"), [(f"/cases/{cid}/approve", {})] * 2), "승인했습니다")
    for cid in ids:  # (b) 같은 사건 동시 실행
        one_ok_one_conflict(race(app, cookies(ws, "회계"), [(f"/cases/{cid}/execute", {})] * 2), "지급 작업 생성")
    with sm() as s:
        for cid in ids:
            assert s.scalar(select(func.count()).select_from(Approval).where(
                Approval.case_id == cid, Approval.decision == "승인")) == 1
            pays = list(s.scalars(select(Task).where(Task.case_id == cid, Task.type == "회계 지급", Task.status != "취소")))
            assert len(pays) == len({t.request_id for t in pays}) == len(sv.case_requests(s, cid)) >= 1
        tids = [t.id for t in s.scalars(select(Task).where(Task.case_id.in_(ids), Task.type == "회계 지급")
                                        .order_by(Task.id))]
    for i, tid in enumerate(tids):  # (c) 같은 지급 작업에 은행 회신 두 번(성공 두 번, 성공과 반려)
        second = {"result": "성공"} if i % 2 else {"result": "반려", "reason": "동시 시험"}
        res = race(app, cookies(ws, "모의 외부"), [(f"/tasks/{tid}/bank", {"result": "성공"}),
                                                   (f"/tasks/{tid}/bank", second)])
        one_ok_one_conflict(res, "을 반영했습니다")
    with sm() as s:
        for tid in tids:
            assert s.scalar(select(func.count()).select_from(EventLog).where(
                EventLog.action == "은행 회신", EventLog.ref == f"작업 {tid}")) == 1
            assert s.scalar(select(func.count()).select_from(EventLog).where(
                EventLog.action == "은행 회신 거부", EventLog.ref == f"작업 {tid}")) == 1
            n_retry = s.scalar(select(func.count()).select_from(Task).where(
                Task.type == "은행 재처리", Task.payload.contains(f'"지급 작업": {tid},')))
            assert n_retry == (s.get(Task, tid).status == "지급 반려")  # 반려가 이겼을 때만 재처리 작업 하나
