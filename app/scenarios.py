"""시나리오 S1~S3. 각 시나리오는 초기화 후 독립 실행된다.

실행: uv run python -m app.scenarios
같은 입력이면 같은 요약을 낸다(가상 시각, AI 미사용 대체 추출, 정렬된 출력).
"""
import csv
import json

from sqlalchemy import select

from app import ai, rules, service as sv
from app.loader import ROOT
from app.models import Approval, Case, Doc, EventLog, Task, make_sessionmaker

DERIVED = ROOT / "data_derived"
DOCS = DERIVED / "docs"
G = "D-011+D-024+D-037"
GRADES = {"S1": "원본 + 모의 회신", "S2": "합성", "S3": "합성 + 모의 회신"}
USE_AI = False  # 재현성: 시나리오는 항상 대체 추출기와 대체 초안을 쓴다


def doc_text(name: str) -> str:
    return (DOCS / name).read_text(encoding="utf-8")


def derived_csv(name: str) -> list[dict]:
    with open(DERIVED / name, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f, delimiter="|"))


def group_case(s) -> Case:
    return s.scalars(select(Case).where(Case.group_key == G, Case.status != sv.DISSOLVED).order_by(Case.id.desc())).first()


def open_task(s, type_, case_id=None):
    q = select(Task).where(Task.type == type_, Task.status == "열림")
    if case_id:
        q = q.where(Task.case_id == case_id)
    return s.scalars(q.order_by(Task.id)).first()


def counts(s) -> dict:
    cases = list(s.scalars(select(Case)))
    st, tk = {}, {}
    for c in cases:
        st[c.status] = st.get(c.status, 0) + 1
    for t in s.scalars(select(Task)):
        k = f"{t.type}/{t.status}"
        tk[k] = tk.get(k, 0) + 1
    # 회차별 회계 지급 작업 수는 취소된 작업을 뺀 값(R7)
    return {"사건 상태": dict(sorted(st.items())), "작업": dict(sorted(tk.items())),
            "회차별 회계 지급 작업": {m: v["건수"] for m, v in sv.cycle_totals(s).items()}}


def prepare_group_for_exec(s):
    """공통 앞부분: 지급계좌 확인 회신(모의, 유효) -> 임원 상신."""
    c = group_case(s)
    sv.account_reply(s, open_task(s, "지급계좌 확인", c.id).id, True)
    sv.submit(s, c.id, use_ai=USE_AI)
    return group_case(s)


def s1(s) -> dict:
    sv.reset(s)
    sv.intake_original(s)
    c = group_case(s)
    first = {"사건 수": len(list(s.scalars(select(Case)))), "그룹 사건 상태": c.status, "그룹 합계": c.total,
             "그룹 경로": c.route}
    n_ok = sv.approve_all_support(s)
    ex = sv.execute_all(s)
    paid = sv.bank_reply_all(s, "성공")
    c = prepare_group_for_exec(s)
    sv.approve(s, c.id, "영업임원")
    ok = sv.execute(s, c.id)
    sv.bank_reply_all(s, "성공")
    c = group_case(s)
    return {"접수 직후": first, "전결 일괄 승인": n_ok, "전결 실행": ex, "전결 은행 성공": paid,
            "그룹 재검증 통과": ok, "그룹 최종 상태": c.status, **counts(s)}


def s2(s) -> dict:
    sv.reset(s)
    sv.intake_original(s)
    sv.approve_all_support(s)  # 37건 승인, 실행은 정정 입력 뒤로 미룬다
    c = prepare_group_for_exec(s)
    sv.approve(s, c.id, "영업임원")
    approvals_before = {a.id: a.valid for a in s.scalars(select(Approval))}

    # 무관한 거래처(D-005, 장려금 요청 없음) 정정: 어떤 승인도 무효가 되면 안 된다
    d = sv.receive_doc(s, "정정 신고", "D-005", doc_text("COR-02_D-005.txt"),
                       source_ref="data_derived/docs/COR-02_D-005.txt", use_ai=USE_AI)
    sv.confirm_doc(s, d, correction={"agency_id": "D-005", "field": "주소", "value": "인천시 항구로 12"})

    # (a) D-024 주소 이전 신고
    text = doc_text("COR-01_D-024.txt")
    d = sv.receive_doc(s, "정정 신고", "D-024", text, case_id=c.id,
                       source_ref="data_derived/docs/COR-01_D-024.txt", use_ai=USE_AI)
    proposed = ai.propose_correction(text, "성남시 상공로 128")
    sv.confirm_doc(s, d, correction={"agency_id": "D-024", **proposed})
    control_d_a = sv.would_reuse(s, c.id)
    ok_a = sv.execute(s, c.id)
    c = group_case(s)
    ev = json.loads(c.basis_json)["관계 근거"]
    ags = sv.current_agencies(s)
    g_off, _ = rules.find_groups(ags, sv.deposits(s), False)
    a_result = {"재검증 통과": ok_a, "상태": c.status, "제안된 정정": proposed,
                "그룹 유지": c.group_key == G, "경로": c.route, "합계": c.total,
                "D-011~D-024 근거": ev["D-011~D-024"], "D-024~D-037 근거": ev["D-024~D-037"],
                "입금계좌 대조를 끄면 D-024 그룹": g_off["D-024"], "대조 D": control_d_a}

    # 재상신 -> 재승인 -> (b) 금액 정정
    sv.submit(s, c.id, use_ai=USE_AI)
    sv.approve(s, c.id, "영업임원")
    ac = derived_csv("amount_corrections.csv")[0]
    sv.correct_amount(s, ac["rebate_id"], int(ac["new_amount"]), ac["reason"], ac["correction_id"])
    control_d_b = sv.would_reuse(s, c.id)
    ok_b = sv.execute(s, c.id)
    c = group_case(s)
    b_result = {"재검증 통과": ok_b, "상태": c.status, "새 합계": c.total, "경로": c.route, "대조 D": control_d_b}

    sv.submit(s, c.id, use_ai=USE_AI)
    sv.approve(s, c.id, "영업임원")
    ok_final = sv.execute(s, c.id)
    unrelated_invalid = [i for i, v in approvals_before.items() if v and not s.get(Approval, i).valid
                         and s.get(Approval, i).case_id != c.id]
    ex = sv.execute_all(s)  # 무관한 37건은 그대로 통과해야 한다
    sv.bank_reply_all(s, "성공")
    return {"(a) 주소 정정": a_result, "(b) 금액 정정": b_result, "최종 재검증 통과": ok_final,
            "무관 정정으로 무효된 다른 승인": unrelated_invalid, "전결 실행": ex,
            "그룹 최종 상태": group_case(s).status, **counts(s)}


def s3(s) -> dict:
    sv.reset(s)
    sv.intake_original(s)
    sv.approve_all_support(s)
    sv.execute_all(s)
    sv.bank_reply_all(s, "성공")
    c = prepare_group_for_exec(s)
    sv.reject(s, c.id, "공유 계좌 소명 없음")
    after_reject = {"상태": c.status, "소명 요청 작업": bool(open_task(s, "소명 요청", c.id))}

    sv.advance_clock(s, "2026-07-03 17:00")  # 7월 회차 승인 마감
    c = group_case(s)
    moved = {"지급월": c.pay_month, "상태": c.status, "합계": c.total, "경로": c.route,
             "대리점 안내 작업": bool(open_task(s, "대리점 안내", c.id)),
             "회차 목록 재생성 작업": bool(open_task(s, "회차 목록 재생성", c.id)),
             "7월에 남은 사건": len(list(s.scalars(select(Case).where(Case.pay_month == "2026-07")))),
             "8월 사건": len(list(s.scalars(select(Case).where(Case.pay_month == "2026-08"))))}

    d = sv.receive_doc(s, "소명 회신", "D-011", doc_text("EXP-01_D-011.txt"), case_id=c.id,
                       source_ref="data_derived/docs/EXP-01_D-011.txt", use_ai=USE_AI)
    before_confirm = group_case(s).status
    sv.confirm_doc(s, d)
    after_confirm = group_case(s).status
    sv.submit(s, c.id, use_ai=USE_AI)

    req = derived_csv("synthetic_requests.csv")[0]
    sv.advance_clock(s, req["applied_at"])
    sv.intake(s, [req | {"note": req["reason"]}], "합성", "data_derived/synthetic_requests.csv")
    c = group_case(s)
    joined = {"상태": c.status, "합계": c.total, "경로": c.route, "요청 수": len(sv.case_requests(s, c.id))}

    sv.submit(s, c.id, use_ai=USE_AI)
    sv.approve(s, c.id, "영업임원")
    ok = sv.execute(s, c.id)
    pays = list(s.scalars(select(Task).where(Task.case_id == c.id, Task.type == "회계 지급").order_by(Task.id)))
    sv.bank_reply(s, pays[0].id, "반려")
    after_bank_reject = {"사건 상태": group_case(s).status, "작업 상태": s.get(Task, pays[0].id).status}
    for t in pays[1:]:
        sv.bank_reply(s, t.id, "성공")
    sv.retry_payment(s, open_task(s, "은행 재처리", c.id).id)
    sv.bank_reply(s, pays[0].id, "성공")
    return {"거절 직후": after_reject, "마감 후 이동": moved,
            "소명 문서": {"확인 전 상태": before_confirm, "확인 후 상태": after_confirm},
            "합성 7월 요청 합류": joined, "재검증 통과": ok, "은행 반려 직후": after_bank_reject,
            "그룹 최종 상태": group_case(s).status, **counts(s)}


def gold_e() -> dict:
    return json.loads((DOCS / "gold_E.json").read_text(encoding="utf-8"))


def control_e() -> dict:
    out = {}
    for name, g in sorted(gold_e().items()):
        ext = ai.verify(doc_text(name), ai.fallback_extract(doc_text(name)))
        out[name] = ai.score(ext, g)
    return out


def run_all(sm=None) -> dict:
    sm = sm or make_sessionmaker()
    out = {}
    grades = GRADES
    for name, fn in (("S1", s1), ("S2", s2), ("S3", s3)):
        with sm() as s:
            out[name] = fn(s) | {"등급": grades[name]}
            out[name]["이력 건수"] = len(list(s.scalars(select(EventLog))))
            out[name]["상신 초안 문서"] = len(list(s.scalars(select(Doc).where(Doc.kind == "상신 초안"))))
    out["대조 E(대체 추출기, AI는 미측정)"] = control_e() | {"등급": "합성"}
    return out


if __name__ == "__main__":
    print(json.dumps(run_all(), ensure_ascii=False, indent=1, sort_keys=True))
