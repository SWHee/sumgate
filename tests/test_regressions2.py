"""수정 2차 회귀 테스트: 2차 교차 검토에서 재현된 결함 R1~R10."""
import re
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError

from app import ai, rules, scenarios, service as sv
from app.models import Approval, Case, RebateRequest, Task
from test_regressions import case_of, new_version, req, tasks


def active_pays(s, rid):
    return [t for t in tasks(s, "회계 지급") if t.request_id == rid and t.status != "취소"]


# R1 ---------------------------------------------------------------------
def test_r1_stale_session_cannot_approve_after_other_session_paid(sm, monkeypatch):
    with sm() as s0:
        sv.reset(s0)
        sv.intake_original(s0)
        sv.intake(s0, [req("D-005", "2026-06", 1_500_000, "RACE")], "합성", "test")
        cid = case_of(s0, "RACE").id
    slow = sm()
    orig = sv.rejudge

    def interleave(s):
        # 느린 세션이 승인 대기 사건과 요청을 읽은 직후, 다른 세션이 승인과 실행을 끝낸다
        orig(s)
        if s is slow:
            monkeypatch.setattr(sv, "rejudge", orig)
            with sm() as s2:
                sv.approve(s2, cid, "영업지원")
                assert sv.execute(s2, cid)

    monkeypatch.setattr(sv, "rejudge", interleave)
    with pytest.raises((ValueError, StaleDataError)):
        sv.approve(slow, cid, "영업지원")
    slow.rollback()
    slow.close()
    with sm() as s3:
        with pytest.raises(ValueError):
            sv.execute(s3, cid)
        s3.rollback()
        sv.bank_reply_all(s3, "성공")
        live = active_pays(s3, "RACE")
        assert [t.status for t in live] == ["지급 완료"]
        assert len(list(s3.scalars(select(Approval).where(Approval.case_id == cid, Approval.decision == "승인")))) == 1


def test_r1_one_active_pay_task_per_request_regardless_of_approval(s):
    sv.intake(s, [req("D-005", "2026-06", 1_500_000, "RACE2")], "합성", "test")
    c = case_of(s, "RACE2")
    sv.approve(s, c.id, "영업지원")
    assert sv.execute(s, c.id)
    # 승인 ID가 다른 두 번째 승인이 어떻게든 생겨도 같은 요청의 활성 지급 작업은 하나다
    s.add(Approval(case_id=c.id, role="영업지원", decision="승인", basis_hash=c.basis_hash, basis_json=c.basis_json,
                   decided_at=sv.now(s)))
    c.status = "승인됨"
    s.commit()
    sv.execute(s, c.id)
    assert len(active_pays(s, "RACE2")) == 1
    # 동시 삽입은 DB 제약이 막는다
    s.add(Task(type="회계 지급", dept="회계", idem_key="pay:RACE2", request_id="RACE2", created_at=sv.now(s)))
    with pytest.raises(IntegrityError):
        s.flush()
    s.rollback()


# R2 ---------------------------------------------------------------------
def test_r2_merge_inherits_rejection_and_explanation(s):
    sv.intake(s, [req("D-005", "2026-06", 1_500_000, "SYN-R2-1"), req("D-005", "2026-07", 3_000_000, "SYN-R2-2")],
              "합성", "test")
    b = case_of(s, "SYN-R2-2")
    sv.submit(s, b.id, use_ai=False)
    sv.reject(s, b.id, "증빙 필요")
    sv.advance_clock(s, "2026-07-03 17:00")
    c = case_of(s, "SYN-R2-1")
    assert case_of(s, "SYN-R2-2").id == c.id != b.id
    assert (c.total, c.route, c.status) == (4_500_000, rules.ROUTE_EXEC, "거절됨")
    assert [t for t in tasks(s, "소명 요청") if t.case_id == c.id and t.status == "열림"]
    for fn in (lambda: sv.submit(s, c.id, use_ai=False), lambda: sv.approve(s, c.id, "영업임원"),
               lambda: sv.execute(s, c.id)):
        with pytest.raises(ValueError):
            fn()
        s.rollback()
    assert not active_pays(s, "SYN-R2-1")
    # 병합된 사건에서 이전 사건의 거절 이력을 볼 수 있다
    assert [(a.case_id, a.decision) for a in sv.case_approvals(s, c.id)] == [(b.id, "거절")]
    # 소명 확인 뒤에는 재상신할 수 있다
    d = sv.receive_doc(s, "소명 회신", "D-005", "소명합니다.", case_id=c.id, use_ai=False)
    sv.confirm_doc(s, d)
    sv.submit(s, c.id, use_ai=False)
    assert s.get(Case, c.id).status == "승인 대기"


# R3 ---------------------------------------------------------------------
def test_r3_insufficient_relation_info_needs_check(s):
    new_version(s, "D-005", representative="NONE", address="NONE")
    sv.intake(s, [req("D-005", "2026-06", 1_500_000, "SYN-R3")], "합성", "test")
    c = case_of(s, "SYN-R3")
    assert c.status == "확인 필요"
    with pytest.raises(ValueError):
        sv.approve(s, c.id, "영업지원")
    s.rollback()
    sv.approve_all_support(s)
    sv.execute_all(s)
    assert not active_pays(s, "SYN-R3")
    new_version(s, "D-005", representative="김보완")  # 정정으로 알려진 값이 2개가 되면 다시 판정
    assert case_of(s, "SYN-R3").status == "전결 승인 대기"


# R4 ---------------------------------------------------------------------
def test_r4_join_before_bank_reply_cancels_and_resums(s):
    sv.intake(s, [req("D-005", "2026-06", 1_500_000, "SYN-R4-A")], "합성", "test")
    a = case_of(s, "SYN-R4-A")
    sv.approve(s, a.id, "영업지원")
    assert sv.execute(s, a.id)
    pay = active_pays(s, "SYN-R4-A")[0]
    sv.intake(s, [req("D-005", "2026-06", 1_000_000, "SYN-R4-B")], "합성", "test")
    assert s.get(Task, pay.id).status == "취소"
    c = case_of(s, "SYN-R4-A")
    assert case_of(s, "SYN-R4-B").id == c.id
    assert (c.total, c.route, c.status) == (2_500_000, rules.ROUTE_EXEC, "상위 승인 필요")
    assert not [x for x in sv.case_approvals(s, c.id) if x.valid]
    sv.bank_reply(s, pay.id, "성공")  # 취소된 작업의 회신은 반영하지 않는다
    assert s.get(RebateRequest, "SYN-R4-A").status != "지급 완료"
    sv.approve_all_support(s)
    assert s.get(Case, c.id).status == "상위 승인 필요"
    sv.submit(s, c.id, use_ai=False)
    sv.approve(s, c.id, "영업임원")
    assert sv.execute(s, c.id)
    sv.bank_reply_all(s, "성공")
    assert s.get(Case, c.id).status == "지급 완료"
    assert [len(active_pays(s, r)) for r in ("SYN-R4-A", "SYN-R4-B")] == [1, 1]


# R5 ---------------------------------------------------------------------
def test_r5_account_recheck_after_unconfirmable(s):
    c = scenarios.group_case(s)
    t = scenarios.open_task(s, "지급계좌 확인", c.id)
    sv.account_reply(s, t.id, False)
    assert scenarios.group_case(s).status == "확인 필요"
    t2 = sv.recheck_account(s, t.id)
    assert t2 != t.id and s.get(Task, t2).status == "열림"
    sv.account_reply(s, t2, True)
    assert scenarios.group_case(s).status == "상위 승인 필요"


# R6 ---------------------------------------------------------------------
def test_r6_interrupted_initial_load_recovers(db_url, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", db_url)
    import app.main as m
    with TestClient(m.app):
        pass
    half = "f" * 32  # 작업 공간을 만들다 끊김(등록 전), 견본도 적재 뒤 접수 전에 끊긴 상태
    m.SPACES._build(half)
    for name in ("template", half):
        with m.SPACES.sm(None if name == "template" else name)() as s:
            sv.reset(s)
    with TestClient(m.app):  # 재시작
        assert m.SPACES.names() == ["template"] and m.SPACES.find(half) is None
        with m.SPACES.sm()() as s:
            live = list(s.scalars(select(RebateRequest).where(RebateRequest.status != sv.HISTORY)))
            assert len(live) == 40 and len(list(s.scalars(select(Case)))) == 38


# R7 ---------------------------------------------------------------------
def test_r7_cycle_totals_exclude_cancelled(s):
    sv.intake(s, [req("D-005", "2026-06", 1_000_000, "SYN-R7")], "합성", "test")
    cid = case_of(s, "SYN-R7").id
    sv.approve(s, cid, "영업지원")
    assert sv.execute(s, cid)
    sv.correct_amount(s, "SYN-R7", 3_000_000, "테스트", "test")
    sv.submit(s, cid, use_ai=False)
    sv.approve(s, cid, "영업임원")
    assert sv.execute(s, cid)
    jul = sv.cycle_totals(s)["2026-07"]
    assert (jul["건수"], jul["금액"], jul["취소 건수"], jul["취소 금액"]) == (1, 3_000_000, 1, 1_000_000)


# R8 ---------------------------------------------------------------------
def test_r8_cookieless_post_is_forbidden(db_url, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", db_url)
    from app.main import app
    form = {"on": "0", "reason": "x", "valid": "1", "result": "성공", "kind": "소명 회신", "agency_id": "D-011",
            "text": "x", "rebate_id": "RB-00180", "amount": "1", "period_ym": "2026-06", "ts": "2026-07-02 10:00",
            "name": "S1"}
    with TestClient(app) as cl:
        posts = sorted({r.path for r in app.routes if "POST" in getattr(r, "methods", ())})
        for path in posts:
            resp = cl.post(re.sub(r"\{\w+\}", "1", path), data=form)
            assert resp.status_code == 403 and "역할" in resp.text, path
        m = __import__("app.main", fromlist=["SPACES"])
        assert m.SPACES.names() == ["template"]  # 역할 쿠키 없는 POST는 작업 공간도 만들지 않는다
        with m.SPACES.sm()() as s:
            assert not list(s.scalars(select(Approval)))
        cl.get("/")  # 첫 화면이 기본 역할(영업지원) 쿠키를 심는다
        assert cl.cookies.get("role") == quote("영업지원")
        assert "전결 사건 37건 승인" in cl.post("/bulk/approve-support").text


# R9 ---------------------------------------------------------------------
def test_r9_relation_evidence_shows_derived_and_version_grades(db_url, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", db_url)
    import app.main as m
    with TestClient(m.app) as cl:
        cl.get("/")
        cl.post("/scenarios/run", data={"name": "S2"})
        with m.SPACES.sm(cl.cookies.get("ws"))() as s:
            gid = scenarios.group_case(s).id
        html = cl.get(f"/cases/{gid}").text
        row = re.search(r"<tr><td>D-011~D-024</td>.*?</tr>", html, re.S).group(0)
        assert "g-도출" in row
        assert re.search(r'D-024 v2 <span class="g g-합성">', row)
        assert re.search(r'D-011 v1 <span class="g g-원본">', row)


# R10 --------------------------------------------------------------------
def test_r10_draft_fallback_reason_in_label(monkeypatch):
    import anthropic
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-not-a-key")

    def boom(**_):
        raise TimeoutError

    monkeypatch.setattr(anthropic, "Anthropic", boom)
    facts = {"members": ["D-011"], "evidence": {}, "pay_month": "2026-07", "requests": [], "total": 1,
             "route": rules.ROUTE_EXEC}
    _, label = ai.draft(facts, True)
    assert label == "AI 미사용(대체 작성), AI 호출 실패 TimeoutError"


def test_r10_mock_reply_label_on_task_and_case(db_url, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", db_url)
    from app.main import app
    with TestClient(app) as cl:
        cl.get("/")
        cl.post("/bulk/approve-support")
        cl.get("/role?r=회계")
        cl.post("/bulk/execute")
        cl.get("/role?r=모의 외부")
        cl.post("/bank/all", data={"result": "성공"})
        mock_badge = r'\s*<span class="g g-모의회신">모의 회신</span>'
        assert re.search(r'<td class="st">지급 완료' + mock_badge, cl.get("/tasks").text)
        assert re.search(r'<td class="st">지급 완료' + mock_badge, cl.get("/cases/1").text)
