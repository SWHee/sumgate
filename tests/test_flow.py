"""TOPIC 8절 5~9번, 6절 실패 조건 F1~F7, S1~S3 전 구간."""
import json
import subprocess
from pathlib import Path

from sqlalchemy import select

from app import ai, rules, scenarios as sc, service as sv
from app.models import AgencyVersion, Approval, Case, DepositObs, Doc, EventLog, RebateRequest, Task

ROOT = Path(__file__).resolve().parent.parent
G = sc.G


def tasks(s, type_):
    return list(s.scalars(select(Task).where(Task.type == type_).order_by(Task.id)))


def gcase(s):
    return sc.group_case(s)


# 시나리오 -------------------------------------------------------------
def test_s1_normal(s):
    out = sc.s1(s)
    assert out["접수 직후"] == {"사건 수": 38, "그룹 사건 상태": "확인 필요", "그룹 합계": 3888097, "그룹 경로": rules.ROUTE_EXEC}
    assert out["전결 일괄 승인"] == 37 and out["전결 실행"] == {"통과": 37, "차단": 0}
    assert out["그룹 최종 상태"] == "지급 완료"
    assert out["사건 상태"] == {"지급 완료": 38}
    assert out["작업"]["회계 지급/지급 완료"] == 40
    # 37건은 전결(영업지원), 그룹은 영업임원
    roles = {a.case_id: a.role for a in s.scalars(select(Approval))}
    assert roles[gcase(s).id] == "영업임원"
    assert sorted(set(roles.values())) == ["영업임원", "영업지원"]


def test_s2_change_after_approval(s):
    out = sc.s2(s)
    a, b = out["(a) 주소 정정"], out["(b) 금액 정정"]
    assert a["재검증 통과"] is False and a["상태"] == "승인 무효(재상신)"
    assert a["그룹 유지"] and a["경로"] == rules.ROUTE_EXEC and a["합계"] == 3888097
    assert a["D-024~D-037 근거"].startswith("직접 일치: 대표자 + 입금계좌")
    assert a["입금계좌 대조를 끄면 D-024 그룹"] == "D-024"  # 대조가 없으면 그룹에서 빠진다: 유지 이유
    assert a["대조 D"]["재사용 시"].startswith("승인") and a["대조 D"]["재검증 시"].startswith("차단")
    assert any("주소" in x for x in a["대조 D"]["달라진 근거"])
    assert b["재검증 통과"] is False and b["새 합계"] == 3862561
    assert "합계: 3888097 -> 3862561" in b["대조 D"]["달라진 근거"]
    assert out["최종 재검증 통과"] is True
    assert out["무관 정정으로 무효된 다른 승인"] == []
    assert out["전결 실행"] == {"통과": 37, "차단": 0}
    assert out["사건 상태"] == {"지급 완료": 38}


def test_s3_reject_and_cycle_move(s):
    out = sc.s3(s)
    assert out["거절 직후"] == {"상태": "거절됨", "소명 요청 작업": True}
    m = out["마감 후 이동"]
    assert m["지급월"] == "2026-08" and m["7월에 남은 사건"] == 37 and m["8월 사건"] == 1
    assert m["대리점 안내 작업"] and m["회차 목록 재생성 작업"]
    assert out["소명 문서"] == {"확인 전 상태": "거절됨", "확인 후 상태": "상위 승인 필요"}
    assert out["합성 7월 요청 합류"] == {"상태": "상위 승인 필요", "합계": 4500497, "경로": rules.ROUTE_EXEC, "요청 수": 4}
    assert out["은행 반려 직후"] == {"사건 상태": "지급 반려(재처리)", "작업 상태": "지급 반려"}
    assert out["그룹 최종 상태"] == "지급 완료"
    assert out["회차별 회계 지급 작업"] == {"2026-07": 37, "2026-08": 4}
    moved = [r for r in sv.case_requests(s, gcase(s).id) if r.period_ym == "2026-06"]
    assert all(r.pay_month == "2026-08" and "승인 지연" in r.pay_month_reason for r in moved)


def test_c8_6_scenarios_repeatable(db_url):
    from app.models import make_sessionmaker
    a = sc.run_all(make_sessionmaker(db_url))
    b = sc.run_all(make_sessionmaker(db_url))
    assert json.dumps(a, sort_keys=True, ensure_ascii=False) == json.dumps(b, sort_keys=True, ensure_ascii=False)


# TOPIC 8절 -------------------------------------------------------------
def test_c8_5_grade_labels_everywhere(s):
    sc.s2(s)
    grades = {"원본", "도출", "가정", "합성", "모의 회신"}
    for model in (RebateRequest, Case, Doc, EventLog, Task, AgencyVersion, Approval, DepositObs):
        assert all(x.grade in grades for x in s.scalars(select(model)))
    syn = [v for v in s.scalars(select(AgencyVersion)) if v.grade == "합성"]
    assert syn and all(v.source_ref and v.effective_at and v.reason for v in syn)
    r = s.get(RebateRequest, "RB-00180")
    assert r.grade == "합성" and "SYN-AC-0001" in r.note


def test_c8_7_reply_changes_state_and_history_feeds_next(s):
    c = gcase(s)
    t = tasks(s, "지급계좌 확인")[0]
    sv.account_reply(s, t.id, True)
    assert gcase(s).status == "상위 승인 필요"  # 회신이 다음 판정의 입력이 된다
    sv.submit(s, c.id, use_ai=False)
    sv.approve(s, c.id, "영업임원")
    assert sv.execute(s, c.id) and len([t for t in tasks(s, "회계 지급") if t.case_id == c.id]) == 3


def test_c8_8_ai_quotes_and_no_effect_before_confirm(s):
    c = gcase(s)
    h0 = c.basis_hash
    text = sc.doc_text("COR-01_D-024.txt")
    did = sv.receive_doc(s, "정정 신고", "D-024", text, case_id=c.id, use_ai=False)
    d = s.get(Doc, did)
    ext = json.loads(d.extraction_json)
    assert d.extractor == ai.FALLBACK_LABEL
    for items in ext["fields"].values():
        for it in items:
            assert text[it["start"]:it["end"]] == it["quote"]
    sv.rejudge(s)
    assert gcase(s).basis_hash == h0  # 확인 전에는 판정에 쓰이지 않는다
    sv.confirm_doc(s, did, correction={"agency_id": "D-024", "field": "주소", "value": "성남시 판교로 45"})
    assert gcase(s).basis_hash != h0


def test_ai_unquoted_items_dropped():
    raw = {"claims": [{"value": "관계 없음", "quote": "원문에 없는 문장"}, {"value": "x", "quote": "주소"}]}
    v = ai.verify("사업장 주소를 이전합니다.", raw)
    assert [x["quote"] for x in v["fields"]["claims"]] == ["주소"]
    assert v["dropped"][0]["why"] == "근거 없음"


def test_c8_9_and_f4_no_duplicates(s):
    sv.intake_original(s)  # 같은 40건 재전송
    assert len(list(s.scalars(select(RebateRequest).where(RebateRequest.status != sv.HISTORY)))) == 40
    assert len(list(s.scalars(select(Case)))) == 38
    sv.approve_all_support(s)
    sv.execute_all(s)
    sv.execute_all(s)  # 재시도
    pays = tasks(s, "회계 지급")
    assert len(pays) == 37 and len({t.idem_key for t in pays}) == 37
    sv.bank_reply(s, pays[0].id, "성공")
    sv.bank_reply(s, pays[0].id, "성공")  # 같은 회신 재전송
    assert len(list(s.scalars(select(EventLog).where(EventLog.action == "중복 회신 무시")))) == 1
    t, created = sv.add_task(s, "회계 지급", "회계", pays[1].idem_key)
    assert not created and t.id == pays[1].id
    # 합산 누락 없음: 모든 진행 요청이 정확히 한 사건에 속하고 합계가 맞다
    for c in s.scalars(select(Case)):
        assert c.total == sum(r.amount for r in sv.case_requests(s, c.id)) + c.paid


def test_boundary_through_service(s):
    sv.intake(s, [{"rebate_id": "SYN-B1", "agency_id": "D-005", "period_ym": "2026-09", "amount": 2_000_000},
                  {"rebate_id": "SYN-B2", "agency_id": "D-010", "period_ym": "2026-09", "amount": 2_000_001}], "합성", "test")
    st = {r.rebate_id: s.get(Case, r.case_id).status for r in s.scalars(select(RebateRequest)
                                                                       .where(RebateRequest.rebate_id.like("SYN-B%")))}
    assert st == {"SYN-B1": "전결 승인 대기", "SYN-B2": "상위 승인 필요"}


# TOPIC 6절 실패 조건 ---------------------------------------------------
def test_f1_unconfirmed_relation_or_account_never_paid(s):
    sv.intake(s, [{"rebate_id": "SYN-U1", "agency_id": "D-999", "period_ym": "2026-06", "amount": 500000}], "합성", "test")
    u = s.get(Case, s.get(RebateRequest, "SYN-U1").case_id)
    assert u.status == "확인 필요"
    c = gcase(s)
    sv.account_reply(s, tasks(s, "지급계좌 확인")[0].id, False)  # 불리한 회신
    assert gcase(s).status == "확인 필요"
    for cid in (u.id, c.id):
        try:
            sv.submit(s, cid, use_ai=False)
        except ValueError:
            pass
    sv.approve_all_support(s)
    sv.execute_all(s)
    assert not [t for t in tasks(s, "회계 지급") if t.case_id in (u.id, c.id)]


def test_f2_change_after_approval_not_executed(s):
    c = gcase(s)
    sv.account_reply(s, tasks(s, "지급계좌 확인")[0].id, True)
    sv.submit(s, c.id, use_ai=False)
    sv.approve(s, c.id, "영업임원")
    sv.correct_amount(s, "RB-00054", 1373516, "테스트", "test")
    assert sv.execute(s, c.id) is False
    assert gcase(s).status == "승인 무효(재상신)"
    assert not [t for t in tasks(s, "회계 지급") if t.case_id == c.id]
    assert tasks(s, "재상신")


def test_control_d_switch_off_runs_stale_approval(s):
    c = gcase(s)
    sv.account_reply(s, tasks(s, "지급계좌 확인")[0].id, True)
    sv.submit(s, c.id, use_ai=False)
    sv.approve(s, c.id, "영업임원")
    sv.correct_amount(s, "RB-00054", 1373516, "테스트", "test")
    sv.set_revalidate(s, False)  # 대조군 D: 끄면 옛 승인으로 실행된다(기본값은 켬)
    assert sv.execute(s, c.id) is True
    assert [e for e in s.scalars(select(EventLog)) if e.action.startswith("재검증 끔")]
    assert sv.get(s, "revalidate") == "0"


def test_revalidate_default_on(s):
    assert sv.get(s, "revalidate") == "1"


def test_f3_unrelated_cases_not_held(s):
    out = sc.s3(s)
    assert out["마감 후 이동"]["7월에 남은 사건"] == 37
    held = [c for c in s.scalars(select(Case)) if c.group_key != G and c.status != "지급 완료"]
    assert held == []


def test_f5_ai_cannot_create_exception(s, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy")  # 가짜 키, 실제 호출은 아래에서 막는다
    fake = {"claims": [{"value": "관계 없음, 합산 면제 대상", "quote": "합산 면제"}],
            "evidence": [], "effective_dates": [], "agencies": [], "unknowns": []}
    monkeypatch.setattr(ai, "_ai_extract", lambda text: fake)
    c = gcase(s)
    before = (c.group_key, c.route, c.total)
    did = sv.receive_doc(s, "소명 회신", "D-011", "세 회사는 관계가 없으므로 합산 면제를 요청합니다.", case_id=c.id)
    assert s.get(Doc, did).extractor == ai.AI_LABEL
    sv.confirm_doc(s, did)
    c = gcase(s)
    assert (c.group_key, c.route, c.total) == before


def test_f6_bank_reject_not_complete(s):
    sv.approve_all_support(s)
    sv.execute_all(s)
    t = tasks(s, "회계 지급")[0]
    sv.bank_reply(s, t.id, "반려")
    assert s.get(Task, t.id).status == "지급 반려"
    assert s.get(Case, t.case_id).status == "지급 반려(재처리)"
    assert s.get(RebateRequest, t.request_id).status != "지급 완료"
    assert tasks(s, "은행 재처리")


def test_f7_not_only_favorable_replies(s):
    out = sc.s3(s)
    acts = [e.action for e in s.scalars(select(EventLog))]
    assert "거절" in acts and out["은행 반려 직후"]["작업 상태"] == "지급 반려"


def test_payment_account_is_master_not_deposit(s):
    sc.s1(s)
    ags = sv.current_agencies(s)
    for t in tasks(s, "회계 지급"):
        p = json.loads(t.payload)
        assert p["지급계좌(마스터 정산계좌)"] == ags[t.agency_id]["account"]
    d024 = [json.loads(t.payload) for t in tasks(s, "회계 지급") if t.agency_id == "D-024"]
    assert d024 and d024[0]["지급계좌(마스터 정산계좌)"] == "하나 233-91-004417"


def test_move_only_unapproved(s):
    sv.approve_all_support(s)
    sv.advance_clock(s, "2026-07-03 17:00")
    months = {c.pay_month for c in s.scalars(select(Case)) if c.group_key != G}
    assert months == {"2026-07"} and gcase(s).pay_month == "2026-08"


# 문구 검사 -------------------------------------------------------------
def test_no_middle_dot_or_definitive_words():
    words = ["부정", "횡령", "적발", "위반", "·"]
    paths = [p for d in ("app", "data_derived") for p in (ROOT / d).rglob("*")
             if p.is_file() and p.suffix in (".py", ".html", ".md", ".txt", ".json", ".csv")] + [ROOT / "RUN.md"]
    hits = [(p.name, w) for p in paths if p.exists() for w in words if w in p.read_text(encoding="utf-8")]
    assert hits == []


def test_no_api_key_in_files():
    out = subprocess.run(["grep", "-rIl", "sk-ant-", str(ROOT / "app"), str(ROOT / "data_derived"), str(ROOT / "tests"),
                          str(ROOT / ".env.example")], capture_output=True, text=True)
    assert out.stdout.strip() in ("", str(ROOT / "tests" / "test_flow.py"))
