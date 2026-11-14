"""SumGate 웹 화면. 서버 렌더링 HTML, 목록 화면은 5초 주기 재조회(웹소켓 없음)."""
import json
from contextlib import asynccontextmanager
from urllib.parse import quote, unquote

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from markupsafe import Markup, escape
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm.exc import StaleDataError

from app import ai, loader, rules, scenarios, service as sv
from app.loader import ROOT
from app.models import AgencyVersion, Approval, Case, Doc, EventLog, RebateRequest, Task, SCHEMA, make_sessionmaker

ROLES = ["영업지원", "영업임원", "회계", "모의 외부"]
SM = None


@asynccontextmanager
async def lifespan(_app):
    global SM
    SM = make_sessionmaker()
    with SM() as s:
        try:
            ready = sv.get(s, "init_done") == SCHEMA
        except SQLAlchemyError:  # 옛 버전의 setting 테이블을 읽지 못하면 다시 만든다
            s.rollback()
            ready = False
        if not ready:  # 빈 DB, 초기 적재가 중간에 끊김(R6), 테이블 정의가 바뀐 새 버전이면 처음부터 다시 적재
            sv.reset(s)
            sv.intake_original(s)
    yield


app = FastAPI(title="SumGate", lifespan=lifespan)
T = Jinja2Templates(directory=str(ROOT / "app" / "templates"))
T.env.filters["won"] = lambda v: f"{int(v):,}"
T.env.filters["fromjson"] = json.loads


DEFAULT_ROLE = "영업지원"


def cookie_role(req: Request) -> str:
    r = unquote(req.cookies.get("role", ""))
    return r if r in ROLES else ""


def role_of(req: Request) -> str:
    """화면 표시용 역할. 상태 변경 요청의 역할 판정은 forbid가 쿠키로만 한다(R8)."""
    return cookie_role(req) or DEFAULT_ROLE


def page(req: Request, name: str, s, **ctx):
    resp = T.TemplateResponse(req, name, {"role": role_of(req), "roles": ROLES,
                                          "clock": sv.now(s), "use_deposits": sv.use_deposits(s),
                                          "msg": req.query_params.get("msg", ""), **ctx})
    if not cookie_role(req):  # R8: 처음 연 화면이 기본 역할을 명시적으로 심어 첫 클릭이 막히지 않게 한다
        resp.set_cookie("role", quote(DEFAULT_ROLE))
    return resp


def back(req: Request, msg: str = "", to: str | None = None):
    url = to or req.headers.get("referer") or "/"
    url = url.split("?msg=")[0].split("&msg=")[0]
    if msg:
        url += ("&" if "?" in url else "?") + "msg=" + quote(msg)
    return RedirectResponse(url, status_code=303)


def deny(req: Request, msg: str):
    url = escape((req.headers.get("referer") or "/").split("?msg=")[0].split("&msg=")[0])
    return HTMLResponse(f'<!doctype html><meta charset="utf-8"><title>SumGate 403</title><p>403 처리하지 않음: '
                        f'{escape(msg)}</p><p>상단에서 역할을 바꾼 뒤 다시 하세요. <a href="{url}">돌아가기</a></p>',
                        status_code=403)


def forbid(req: Request, *roles: str):
    """A1, R8: 상태를 바꾸는 모든 요청의 서버 측 역할 검사. 역할 쿠키가 없으면 거부, roles가 비면 모든 역할 허용."""
    r = cookie_role(req)
    if not r:
        return deny(req, "역할이 선택되지 않았습니다. 화면을 열어 역할을 고른 뒤 다시 하세요")
    if not roles or r in roles:
        return None
    return deny(req, f"{' 또는 '.join(roles)} 역할만 할 수 있습니다(현재 역할: {r})")


def act(req: Request, fn, ok_msg: str = "처리했습니다", to: str | None = None):
    with SM() as s:
        try:
            r = fn(s)
            return back(req, r if isinstance(r, str) else ok_msg, to)
        except PermissionError as e:
            s.rollback()
            return deny(req, str(e))
        except (ValueError, KeyError) as e:
            s.rollback()
            return back(req, f"처리하지 않음: {e}", to)
        except (StaleDataError, IntegrityError):  # R1: 다른 요청이 먼저 바꾼 상태를 덮어쓰지 않는다
            s.rollback()
            return back(req, "처리하지 않음: 다른 처리가 먼저 반영되었습니다. 화면을 다시 확인하세요", to)


@app.get("/role")
def set_role(req: Request, r: str):
    resp = back(req)
    if r in ROLES:
        resp.set_cookie("role", quote(r))
    return resp


# 1. 대기열 ---------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def queue(req: Request):
    with SM() as s:
        cases = list(s.scalars(select(Case).order_by(Case.id)))
        grades = {}
        for r in s.scalars(select(RebateRequest).where(RebateRequest.status != sv.HISTORY)):
            grades.setdefault(r.case_id, set()).update({r.grade, r.pay_month_grade})
        checks = list(s.scalars(select(RebateRequest).where(RebateRequest.status == sv.NEEDS_CHECK)
                                .order_by(RebateRequest.rebate_id)))
        return page(req, "queue.html", s, cases=cases, grades=grades, deadline=rules.deadline_of, checks=checks)


@app.post("/bulk/approve-support")
def bulk_approve(req: Request):
    return forbid(req, "영업지원") or act(req, lambda s: f"전결 사건 {sv.approve_all_support(s)}건 승인")


@app.post("/bulk/execute")
def bulk_execute(req: Request):
    def f(s):
        r = sv.execute_all(s)
        return f"실행 전 재검증: 통과 {r['통과']}건, 차단 {r['차단']}건"
    return forbid(req, "회계") or act(req, f)


@app.post("/settings/deposits")
def toggle_deposits(req: Request, on: str = Form(...)):
    return forbid(req, "영업지원") or act(req, lambda s: sv.set_use_deposits(s, on == "1"), "입금계좌 대조 설정을 바꿨습니다")


@app.post("/settings/revalidate")
def toggle_revalidate(req: Request, on: str = Form(...)):
    return forbid(req) or act(req, lambda s: sv.set_revalidate(s, on == "1"), "실행 전 재검증 설정을 바꿨습니다")


# 2. 사건 상세 ------------------------------------------------------------
@app.get("/cases/{cid}", response_class=HTMLResponse)
def case_detail(req: Request, cid: int):
    with SM() as s:
        c = s.get(Case, cid)
        if not c:
            return back(req, "사건 없음", "/")
        basis = json.loads(c.basis_json)
        reqs = sv.case_requests(s, cid)
        per_agency = rules.per_agency_routes([{"agency_id": r.agency_id, "pay_month": r.pay_month, "amount": r.amount}
                                              for r in reqs])
        approvals = sv.case_approvals(s, cid)
        ver_grade = {(v.agency_id, v.version_no): v.grade for v in s.scalars(select(AgencyVersion).where(
            AgencyVersion.agency_id.in_([m["거래처"] for m in basis["구성원"]])))}
        draft = s.scalars(select(Doc).where(Doc.case_id == cid, Doc.kind == "상신 초안").order_by(Doc.id.desc())).first()
        tasks = list(s.scalars(select(Task).where(Task.case_id == cid).order_by(Task.id)))
        events = list(s.scalars(select(EventLog).where(EventLog.ref.in_([f"사건 {cid}"] + [r.rebate_id for r in reqs]))
                                .order_by(EventLog.id)))
        return page(req, "case.html", s, c=c, basis=basis, reqs=reqs, per_agency=per_agency, approvals=approvals,
                    draft=draft, tasks=tasks, events=events, deadline=rules.deadline_of(c.pay_month),
                    ver_grade=ver_grade, ver={m["거래처"]: m["마스터 버전"] for m in basis["구성원"]})


@app.post("/cases/{cid}/approve")
def case_approve(req: Request, cid: int):
    return forbid(req, "영업지원", "영업임원") or act(req, lambda s: sv.approve(s, cid, role_of(req)), "승인했습니다")


@app.post("/cases/{cid}/reject")
def case_reject(req: Request, cid: int, reason: str = Form("")):
    return forbid(req, "영업임원") or act(req, lambda s: sv.reject(s, cid, reason), "거절했습니다. 소명 요청 작업을 만들었습니다")


@app.post("/cases/{cid}/submit")
def case_submit(req: Request, cid: int):
    return forbid(req, "영업지원") or act(req, lambda s: sv.submit(s, cid), "상신했습니다")


@app.post("/cases/{cid}/execute")
def case_execute(req: Request, cid: int):
    return forbid(req, "회계") or act(
        req, lambda s: "재검증 통과, 지급 작업 생성" if sv.execute(s, cid) else "재검증 차단 또는 확인 필요: 지급 작업 없음")


# 3. 작업함 ---------------------------------------------------------------
@app.get("/tasks", response_class=HTMLResponse)
def tasks(req: Request):
    with SM() as s:
        ts = list(s.scalars(select(Task).order_by(Task.id)))
        by_dept = {}
        for t in ts:
            by_dept.setdefault(t.dept, []).append(t)
        return page(req, "tasks.html", s, by_dept=dict(sorted(by_dept.items())), cycles=sv.cycle_totals(s))


@app.post("/tasks/{tid}/account-reply")
def account_reply(req: Request, tid: int, valid: str = Form(...)):
    return forbid(req, "모의 외부") or act(req, lambda s: sv.account_reply(s, tid, valid == "1"), "모의 회신을 반영했습니다")


@app.post("/tasks/{tid}/recheck")
def account_recheck(req: Request, tid: int):
    return forbid(req, "영업지원") or act(req, lambda s: f"지급계좌 재확인 작업 {sv.recheck_account(s, tid)}을 만들었습니다")


@app.post("/tasks/{tid}/bank")
def bank(req: Request, tid: int, result: str = Form(...)):
    return forbid(req, "모의 외부") or act(req, lambda s: sv.bank_reply(s, tid, result), f"모의 은행 회신({result})을 반영했습니다")


@app.post("/bank/all")
def bank_all(req: Request, result: str = Form("성공")):
    return forbid(req, "모의 외부") or act(req, lambda s: f"모의 은행 회신 {sv.bank_reply_all(s, result)}건({result})")


@app.post("/tasks/{tid}/retry")
def retry(req: Request, tid: int):
    return forbid(req, "회계") or act(
        req, lambda s: "재처리 요청: 지급 대기로 돌렸습니다" if sv.retry_payment(s, tid) else "재검증 차단: 승인 무효(재상신)")


# 4. 모의 입력 ------------------------------------------------------------
@app.get("/mock", response_class=HTMLResponse)
def mock(req: Request, sample: str = ""):
    with SM() as s:
        samples = sorted(p.name for p in scenarios.DOCS.glob("*.txt"))
        text = (scenarios.DOCS / sample).read_text(encoding="utf-8") if sample in samples else ""
        kind = "정정 신고" if sample.startswith("COR") else "소명 회신"
        agency = sample.split("_")[1].removesuffix(".txt") if sample in samples else ""
        group = scenarios.group_case(s)
        return page(req, "mock.html", s, samples=samples, sample=sample, text=text, kind=kind, agency=agency,
                    group_case=group.id if group else "", syn_req=scenarios.derived_csv("synthetic_requests.csv"),
                    amount_cor=scenarios.derived_csv("amount_corrections.csv"))


@app.post("/mock/doc")
def mock_doc(req: Request, kind: str = Form(...), agency_id: str = Form(...), text: str = Form(...),
             case_id: str = Form(""), source_ref: str = Form("")):
    if no := forbid(req, "모의 외부"):
        return no

    def f(s):
        did = sv.receive_doc(s, kind, agency_id.strip(), text, int(case_id) if case_id.strip() else None,
                             source_ref=source_ref or "모의 입력 화면")
        return did
    with SM() as s:
        try:
            did = f(s)
        except ValueError as e:
            return back(req, f"처리하지 않음: {e}")
    return RedirectResponse(f"/docs/{did}", status_code=303)


@app.post("/mock/amount")
def mock_amount(req: Request, rebate_id: str = Form(...), amount: int = Form(...), reason: str = Form(...),
                ref: str = Form("모의 입력 화면")):
    return forbid(req, "모의 외부") or act(
        req, lambda s: sv.correct_amount(s, rebate_id.strip(), amount, reason, ref), "금액 정정을 반영했습니다")


@app.post("/mock/request")
def mock_request(req: Request, rebate_id: str = Form(...), agency_id: str = Form(...), period_ym: str = Form(...),
                 amount: int = Form(...), reason: str = Form(...)):
    row = {"rebate_id": rebate_id.strip(), "agency_id": agency_id.strip(), "period_ym": period_ym.strip(),
           "amount": amount, "note": reason}
    return forbid(req, "모의 외부") or act(
        req, lambda s: sv.intake(s, [row], "합성", "data_derived/synthetic_requests.csv"), "합성 요청을 접수했습니다")


@app.post("/mock/clock")
def mock_clock(req: Request, ts: str = Form(...)):
    return forbid(req, "모의 외부") or act(req, lambda s: sv.advance_clock(s, ts.strip()), "가상 시각을 옮겼습니다")


# 5. 문서 -----------------------------------------------------------------
def highlight(text: str, ext: dict) -> Markup:
    spans = sorted((it["start"], it["end"], k) for k, items in ext.get("fields", {}).items() for it in items)
    out, pos = [], 0
    for a, b, k in spans:
        if a < pos:
            continue  # 겹치는 인용은 앞의 것만 표시
        out.append(escape(text[pos:a]))
        out.append(Markup(f'<mark title="{ai.FIELDS[k]}">') + escape(text[a:b]) + Markup("</mark>"))
        pos = b
    out.append(escape(text[pos:]))
    return Markup("").join(out)


@app.get("/docs", response_class=HTMLResponse)
def docs(req: Request):
    with SM() as s:
        return page(req, "docs.html", s, docs=list(s.scalars(select(Doc).order_by(Doc.id.desc()))))


@app.get("/docs/{did}", response_class=HTMLResponse)
def doc_detail(req: Request, did: int):
    with SM() as s:
        d = s.get(Doc, did)
        if not d:
            return back(req, "문서 없음", "/docs")
        ext = json.loads(d.extraction_json or "{}")
        proposal = {}
        if d.kind == "정정 신고":
            cur = sv.current_agencies(s).get(d.agency_id)
            proposal = ai.propose_correction(d.text, cur["address"] if cur else "")
        return page(req, "doc.html", s, d=d, ext=ext, marked=highlight(d.text, ext), fields=ai.FIELDS,
                    proposal=proposal)


@app.post("/docs/{did}/confirm")
def doc_confirm(req: Request, did: int, agency_id: str = Form(""), field: str = Form("주소"), value: str = Form("")):
    corr = {"agency_id": agency_id.strip(), "field": field, "value": value.strip()} if value.strip() else None
    return forbid(req, "영업지원") or act(
        req, lambda s: sv.confirm_doc(s, did, correction=corr), "담당자 확인을 반영했습니다. 코드가 다시 계산했습니다")


# 6. 대조와 과거 관찰 -----------------------------------------------------
@app.get("/controls", response_class=HTMLResponse)
def controls(req: Request):
    ags = {a["agency_id"]: a for a in loader.agencies()}
    dps = loader.deposits()
    rb = loader.rebates()
    hist = [r for r in rb if r["status"] != "미지급"]
    pend = [dict(r, pay_month=rules.pay_month_of(r["period_ym"])[0]) for r in rb if r["status"] == "미지급"]
    cases, _, _ = rules.assess(pend, ags, dps, hist)
    up = [c for c in cases.values() if c["route"] == rules.ROUTE_EXEC]
    per_agency_up = [k for k, v in rules.per_agency_routes(pend).items() if v == rules.ROUTE_EXEC]
    _, ev_off = rules.find_groups(ags, dps, False)
    _, ev_on = rules.find_groups(ags, dps, True)
    c_items = rules.pair_match(ags["D-034"], ags["D-041"], dps, True)[0]
    obs = rules.observe_history(hist, scenarios.G, [f"2026-0{i}" for i in range(1, 6)])
    with SM() as s:
        d_rows = [a for a in s.scalars(select(Approval).where(Approval.decision == "승인", Approval.invalid_reason != "")
                                       .order_by(Approval.id))]
        e_ai = json.loads(sv.get(s, "e_ai") or "{}")
        return page(req, "controls.html", s, n_cases=len(cases), up=up, per_agency_up=per_agency_up,
                    ev_off=ev_off, ev_on=ev_on, c_items=c_items, obs=obs, obs_sum=sum(o["total"] for o in obs),
                    d_rows=d_rows, revalidate=sv.get(s, "revalidate") != "0", e_fb=scenarios.control_e(), e_ai=e_ai, has_key=ai.has_key())


@app.post("/controls/e/ai")
def control_e_ai(req: Request):
    if no := forbid(req):
        return no
    if not ai.has_key():
        return back(req, "ANTHROPIC_API_KEY가 없어 AI 추출은 미측정입니다")
    gold = json.loads((scenarios.DOCS / "gold_E.json").read_text(encoding="utf-8"))
    res = {}
    for name, g in sorted(gold.items()):
        ext = ai.extract(scenarios.doc_text(name), True)
        res[name] = ai.score(ext, g) | {"추출기": ext["extractor"]}
    return act(req, lambda s: (sv.put(s, "e_ai", json.dumps(res, ensure_ascii=False)), s.commit()) and "AI 추출 측정 완료")


# 7. 이력 -----------------------------------------------------------------
@app.get("/log", response_class=HTMLResponse)
def event_log(req: Request):
    with SM() as s:
        ev = list(s.scalars(select(EventLog).order_by(EventLog.id.desc()).limit(500)))
        versions = list(s.scalars(select(AgencyVersion).where(AgencyVersion.version_no > 1).order_by(AgencyVersion.id)))
        return page(req, "log.html", s, events=ev, versions=versions)


# 8. 시나리오 실행과 초기화 ----------------------------------------------
@app.get("/scenarios", response_class=HTMLResponse)
def scen(req: Request):
    with SM() as s:
        return page(req, "scenarios.html", s, summary=sv.get(s, "last_summary"))


@app.post("/scenarios/reset")
def scen_reset(req: Request):
    def f(s):
        sv.reset(s)
        sv.intake_original(s)
    return forbid(req) or act(req, f, "초기화: 원본 적재 후 미지급 40건 접수")


@app.post("/scenarios/run")
def scen_run(req: Request, name: str = Form(...)):
    fn = {"S1": scenarios.s1, "S2": scenarios.s2, "S3": scenarios.s3}.get(name)
    if no := forbid(req):
        return no
    if not fn:
        return back(req, "처리하지 않음: 알 수 없는 시나리오")

    def f(s):
        out = fn(s) | {"등급": scenarios.GRADES[name]}
        sv.put(s, "last_summary", f"{name}\n" + json.dumps(out, ensure_ascii=False, indent=1, sort_keys=True))
        s.commit()
        return f"{name} 실행 완료"
    return act(req, f)
