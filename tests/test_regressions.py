"""수정 1차 회귀 테스트: 교차 검토에서 실행으로 재현된 결함 F1~F7과 역할 검사(A1)."""
import json
import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import rules, service as sv
from app.models import AgencyVersion, Approval, Case, RebateRequest, Task


def tasks(s, type_):
    return list(s.scalars(select(Task).where(Task.type == type_).order_by(Task.id)))


def req(aid, ym, amount, rid):
    return {"rebate_id": rid, "agency_id": aid, "period_ym": ym, "amount": amount}


def case_of(s, rid) -> Case:
    return s.get(Case, s.get(RebateRequest, rid).case_id)


def new_version(s, aid, **fields):
    """확정된 마스터 정정과 같은 효과: 새 버전 행을 넣고 다시 판정한다."""
    cur = sv.current_agencies(s)[aid]
    v = {"representative": cur["representative"], "address": cur["address"], "account": cur["account"]} | fields
    s.add(AgencyVersion(agency_id=aid, version_no=cur["version"] + 1, name=cur["name"], effective_at=sv.now(s),
                        reason="테스트 정정", grade="합성", source_ref="test", **v))
    s.flush()
    sv.rejudge(s)
    s.commit()


def pay_and_complete(s, rid):
    c = case_of(s, rid)
    sv.approve(s, c.id, "영업지원")
    assert sv.execute(s, c.id)
    for t in tasks(s, "회계 지급"):
        if t.request_id == rid:
            sv.bank_reply(s, t.id, "성공")


def test_regress_f1_retry_after_amount_change_passes_gate(s):
    sv.intake(s, [req("D-005", "2026-06", 1_000_000, "SYN-F1")], "합성", "test")
    cid = case_of(s, "SYN-F1").id
    sv.approve(s, cid, "영업지원")
    assert sv.execute(s, cid)
    pay = [t for t in tasks(s, "회계 지급") if t.request_id == "SYN-F1"][0]
    sv.bank_reply(s, pay.id, "반려")
    retry = [t for t in tasks(s, "은행 재처리") if t.request_id == "SYN-F1"][0]
    sv.correct_amount(s, "SYN-F1", 3_000_000, "테스트", "test")
    try:
        sv.retry_payment(s, retry.id)
    except ValueError:
        pass
    sv.bank_reply_all(s, "성공")
    assert s.get(RebateRequest, "SYN-F1").status != "지급 완료"
    assert s.get(Case, cid).status == "승인 무효(재상신)"
    assert not [a for a in s.scalars(select(Approval).where(Approval.case_id == cid)) if a.valid]
    assert not [t for t in tasks(s, "회계 지급") if t.request_id == "SYN-F1" and t.status in ("지급 대기", "지급 완료")]
    # 재상신, 임원 승인 뒤에는 새 금액으로 한 번만 지급된다
    sv.submit(s, cid, use_ai=False)
    sv.approve(s, cid, "영업임원")
    assert sv.execute(s, cid)
    live = [json.loads(t.payload)["금액"] for t in tasks(s, "회계 지급")
            if t.request_id == "SYN-F1" and t.status == "지급 대기"]
    assert live == [3_000_000]
    sv.bank_reply_all(s, "성공")
    assert s.get(Case, cid).status == "지급 완료"


def test_regress_f1_change_while_waiting_for_bank_cancels_task(s):
    sv.intake(s, [req("D-005", "2026-06", 1_000_000, "SYN-F1B")], "합성", "test")
    cid = case_of(s, "SYN-F1B").id
    sv.approve(s, cid, "영업지원")
    assert sv.execute(s, cid)
    pay = [t for t in tasks(s, "회계 지급") if t.request_id == "SYN-F1B"][0]
    sv.correct_amount(s, "SYN-F1B", 3_000_000, "테스트", "test")
    sv.bank_reply(s, pay.id, "성공")  # 취소된 작업에 온 회신은 반영하지 않는다
    assert s.get(Task, pay.id).status == "취소"
    assert s.get(RebateRequest, "SYN-F1B").status != "지급 완료"
    assert s.get(Case, cid).status == "승인 무효(재상신)"


def test_regress_f2_paid_amount_counts_after_group_change(s):
    sv.intake(s, [req("D-005", "2026-06", 1_500_000, "SYN-F2-1")], "합성", "test")
    pay_and_complete(s, "SYN-F2-1")
    d5 = sv.current_agencies(s)["D-005"]
    new_version(s, "D-010", representative=d5["representative"], address=d5["address"])
    sv.intake(s, [req("D-010", "2026-06", 1_000_000, "SYN-F2-2")], "합성", "test")
    c = case_of(s, "SYN-F2-2")
    assert c.group_key == "D-005+D-010"
    assert (c.paid, c.total, c.route, c.status) == (1_500_000, 2_500_000, rules.ROUTE_EXEC, "상위 승인 필요")
    sv.approve_all_support(s)
    assert s.get(Case, c.id).status == "상위 승인 필요"


def test_regress_f3_cycle_move_merges_same_group_and_month(s):
    sv.intake(s, [req("D-005", "2026-06", 1_500_000, "SYN-F3-1"), req("D-005", "2026-07", 1_000_000, "SYN-F3-2")],
              "합성", "test")
    a, b = case_of(s, "SYN-F3-1"), case_of(s, "SYN-F3-2")
    assert (a.pay_month, b.pay_month) == ("2026-07", "2026-08")
    sv.approve(s, b.id, "영업지원")  # 8월 사건은 전결로 먼저 승인
    sv.advance_clock(s, "2026-07-03 17:00")
    live = [c for c in s.scalars(select(Case)) if c.group_key == "D-005" and c.status != sv.DISSOLVED]
    assert len(live) == 1
    c = live[0]
    assert (c.pay_month, c.total, c.route, c.status) == ("2026-08", 2_500_000, rules.ROUTE_EXEC, "상위 승인 필요")
    assert sorted(r.rebate_id for r in sv.case_requests(s, c.id)) == ["SYN-F3-1", "SYN-F3-2"]
    assert not [x for x in s.scalars(select(Approval).where(Approval.case_id.in_([a.id, b.id]))) if x.valid]
    sv.approve_all_support(s)
    assert s.get(Case, c.id).status == "상위 승인 필요"


def test_regress_f4_empty_or_none_identity_never_matches():
    def ag(i, v):
        return {"agency_id": i, "name": i, "representative": v, "address": v, "account": v, "version": 1}
    ags = {"X-1": ag("X-1", ""), "X-2": ag("X-2", ""), "Y-1": ag("Y-1", "NONE"), "Y-2": ag("Y-2", "NONE")}
    deps = [{"deposit_id": "DP-1", "agency_id": "Y-1", "bank_account_no": "NONE"},
            {"deposit_id": "DP-2", "agency_id": "Y-2", "bank_account_no": "NONE"}]
    group_of, evidence = rules.find_groups(ags, deps, True)
    assert len(set(group_of.values())) == 4 and evidence == {}
    assert rules.pair_match(ags["X-1"], ags["X-2"], deps, True)[0] == []
    assert rules.pair_match(ags["Y-1"], ags["Y-2"], deps, True)[0] == []


def test_regress_f5_none_settlement_account_never_paid(s):
    new_version(s, "D-005", account="NONE")
    sv.intake(s, [req("D-005", "2026-06", 500_000, "SYN-F5")], "합성", "test")
    c = case_of(s, "SYN-F5")
    assert c.status == "확인 필요"
    t = [x for x in tasks(s, "지급계좌 확인") if x.agency_id == "D-005"][0]
    with pytest.raises(ValueError):
        sv.account_reply(s, t.id, True)  # 정산계좌가 없으면 '유효' 회신으로 풀 수 없다
    sv.approve_all_support(s)
    sv.execute_all(s)
    assert not [x for x in tasks(s, "회계 지급") if x.agency_id == "D-005"]
    assert not [x for x in tasks(s, "회계 지급") if json.loads(x.payload)["지급계좌(마스터 정산계좌)"] in ("", "NONE")]


def test_regress_f6_non_positive_amount_needs_check(s):
    sv.intake(s, [req("D-005", "2026-06", 3_000_000, "SYN-F6-1"), req("D-005", "2026-06", -2_000_000, "SYN-F6-2"),
                  req("D-005", "2026-06", 0, "SYN-F6-3")], "합성", "test")
    for rid in ("SYN-F6-2", "SYN-F6-3"):
        r = s.get(RebateRequest, rid)
        assert r.status == "확인 필요" and r.case_id is None
    c = case_of(s, "SYN-F6-1")
    assert (c.total, c.route) == (3_000_000, rules.ROUTE_EXEC)
    sv.approve_all_support(s)
    sv.execute_all(s)
    assert not [t for t in tasks(s, "회계 지급") if t.request_id in ("SYN-F6-2", "SYN-F6-3")]


def test_regress_f7_approval_confirms_pay_month(s, monkeypatch):
    c = s.scalars(select(Case).where(Case.status == "전결 승인 대기").order_by(Case.id)).first()
    assert {r.pay_month_grade for r in sv.case_requests(s, c.id)} == {"가정"}
    sv.approve(s, c.id, "영업지원")
    assert {r.pay_month_grade for r in sv.case_requests(s, c.id)} == {"확정(승인 시)"}
    assert sv.execute(s, c.id)  # 승인이 등급을 바꿔도 승인 근거와 현재 근거가 같아야 한다
    # 마지막 방어선: 재검증 게이트를 건너뛰어도 지급월이 확정되지 않은 요청에는 지급 작업이 없다
    c2 = s.scalars(select(Case).where(Case.status == "전결 승인 대기").order_by(Case.id)).first()
    sv.approve(s, c2.id, "영업지원")
    monkeypatch.setattr(sv, "gate", lambda *a: True)
    for r in sv.case_requests(s, c2.id):
        r.pay_month_grade = "가정"
    s.commit()
    assert sv.execute(s, c2.id) is False
    assert not [t for t in tasks(s, "회계 지급") if t.case_id == c2.id]


# A1 역할 검사 ----------------------------------------------------------
def _role(cl, r):
    cl.get(f"/role?r={r}")


def test_regress_a1_server_side_role_checks(db_url, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", db_url)
    from app.main import app
    with TestClient(app) as cl:
        q = cl.get("/").text
        gid = int(re.search(r'href="/cases/(\d+)">#\d+</a></td>\s*<td>D-011, D-024, D-037', q).group(1))
        sid = 1 if gid != 1 else 2
        _role(cl, "회계")
        r = cl.post("/bulk/approve-support")
        assert r.status_code == 403 and "영업지원" in r.text
        for path, data in [(f"/cases/{gid}/submit", None), (f"/cases/{sid}/approve", None),
                           ("/mock/clock", {"ts": "2026-07-02 10:00"}), ("/tasks/1/account-reply", {"valid": "1"}),
                           ("/bank/all", {"result": "성공"})]:
            assert cl.post(path, data=data).status_code == 403, path
        _role(cl, "영업지원")
        assert cl.post(f"/cases/{sid}/execute").status_code == 403
        assert cl.post(f"/cases/{gid}/reject", data={"reason": "x"}).status_code == 403
        assert "이 승인은 2026-07 회차 지급을 확정합니다" in cl.get(f"/cases/{sid}").text
        _role(cl, "영업임원")
        assert cl.post(f"/cases/{sid}/approve").status_code == 403  # 전결 사건의 승인권자는 영업지원
        _role(cl, "회계")
        assert cl.post("/scenarios/reset").status_code == 200  # 초기화는 모든 역할 허용


def test_regress_f1_retry_gate_by_itself(s):
    """재처리 경로 자체가 게이트를 지나는지: rejudge 없이 근거를 바꾼 뒤 재처리해도 옛 금액으로 지급되지 않는다."""
    sv.intake(s, [req("D-005", "2026-06", 1_000_000, "SYN-F1C")], "합성", "test")
    cid = case_of(s, "SYN-F1C").id
    sv.approve(s, cid, "영업지원")
    assert sv.execute(s, cid)
    pay = [t for t in tasks(s, "회계 지급") if t.request_id == "SYN-F1C"][0]
    sv.bank_reply(s, pay.id, "반려")
    retry = [t for t in tasks(s, "은행 재처리") if t.request_id == "SYN-F1C"][0]
    s.get(RebateRequest, "SYN-F1C").amount = 3_000_000  # 재판정을 거치지 않은 변경
    s.commit()
    assert sv.retry_payment(s, retry.id) is False
    assert not [t for t in tasks(s, "회계 지급") if t.request_id == "SYN-F1C" and t.status == "지급 대기"]
    assert s.get(Case, cid).status == "승인 무효(재상신)"


ALL_ROLES = {"/scenarios/reset", "/scenarios/run", "/controls/e/ai"}
NEED = {"/bulk/approve-support": "영업지원", "/bulk/execute": "회계",
        "/cases/{cid}/approve": "영업지원 영업임원", "/cases/{cid}/reject": "영업임원", "/cases/{cid}/submit": "영업지원",
        "/cases/{cid}/execute": "회계", "/tasks/{tid}/account-reply": "모의 외부", "/tasks/{tid}/recheck": "영업지원", "/tasks/{tid}/bank": "모의 외부",
        "/bank/all": "모의 외부", "/tasks/{tid}/retry": "회계", "/mock/doc": "모의 외부", "/mock/amount": "모의 외부",
        "/mock/request": "모의 외부", "/mock/clock": "모의 외부", "/papers/{did}/confirm": "영업지원"}


def test_regress_a1_every_post_route_is_role_checked(db_url, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", db_url)
    from app.main import ROLES, app
    posts = {r.path for r in app.routes if "POST" in getattr(r, "methods", ())}
    assert posts == set(NEED) | ALL_ROLES  # 새 POST 경로는 역할을 정해야 한다
    form = {"on": "1", "reason": "x", "valid": "1", "result": "성공", "kind": "소명 회신", "agency_id": "D-011",
            "text": "x", "rebate_id": "RB-00180", "amount": "1", "period_ym": "2026-06", "ts": "2026-07-02 10:00"}
    with TestClient(app) as cl:
        for path, allowed in NEED.items():
            url = re.sub(r"\{\w+\}", "1", path)
            for r in ROLES:
                if r not in allowed.split(" ") and not (r == "모의 외부" and "모의" in allowed):
                    _role(cl, r)
                    resp = cl.post(url, data=form)
                    assert resp.status_code == 403 and "역할만 할 수 있습니다" in resp.text, (path, r)
