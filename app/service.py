"""상태 전이. 모든 전이는 이 파일의 함수로만 일어나고 event_log에 남는다."""
import json
from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app import ai, loader, rules
from app.models import AgencyVersion, Approval, Base, Case, DepositObs, Doc, EventLog, RebateRequest, SCHEMA, Setting, Task

START_CLOCK = "2026-07-01 09:00"
HISTORY = "과거 기록"
PRE = ("접수", "확인 필요", "전결 승인 대기", "상위 승인 필요")
APPROVED = ("승인됨", "지급 작업 생성", "지급 완료", "지급 반려(재처리)")
IN_FLIGHT = ("지급 작업 생성", "지급 반려(재처리)")
FROZEN = IN_FLIGHT + ("지급 완료",)
DISSOLVED = "구성 변경(해소)"
NEEDS_CHECK = "확인 필요"  # 요청 상태: 금액이 0 이하라 합산과 지급에서 뺀다(P4)
CONFIRMED_PM = ("원본", "확정(승인 시)")  # 지급 작업은 지급월이 확정된 요청에만 만든다(F7)


# 기본 도구 -------------------------------------------------------------
def get(s: Session, key: str) -> str:
    row = s.get(Setting, key)
    return row.value if row else ""


def put(s: Session, key: str, value: str):
    row = s.get(Setting, key)
    if row:
        row.value = value
    else:
        s.add(Setting(key=key, value=value))


def now(s: Session) -> str:
    return get(s, "clock")


def log(s, actor, actor_type, action, ref, detail="", grade="도출"):
    s.add(EventLog(ts=now(s), actor=actor, actor_type=actor_type, action=action, ref=ref, detail=detail, grade=grade))


def transition(s, c: Case, new: str, actor="시스템", actor_type="시스템", detail=""):
    if c.status != new:
        log(s, actor, actor_type, "상태 전이", f"사건 {c.id}", f"{c.status} -> {new}" + (f": {detail}" if detail else ""))
        c.status = new


def add_task(s, type_, dept, idem_key, case_id=None, request_id="", agency_id="", payload=None, grade="도출"):
    """멱등: 같은 idem_key의 작업이 있으면 새로 만들지 않는다."""
    t = s.scalar(select(Task).where(Task.idem_key == idem_key))
    if t:
        return t, False
    t = Task(type=type_, dept=dept, idem_key=idem_key, case_id=case_id, request_id=request_id, agency_id=agency_id,
             payload=json.dumps(payload or {}, ensure_ascii=False), created_at=now(s), grade=grade)
    s.add(t)
    s.flush()
    log(s, "시스템", "시스템", "작업 생성", f"작업 {t.id}", f"{type_} ({dept})" + (f", 사건 {case_id}" if case_id else ""))
    return t, True


# 초기화와 적재 ---------------------------------------------------------
def reset(s: Session):
    bind = s.get_bind()
    s.close()
    Base.metadata.drop_all(bind)
    Base.metadata.create_all(bind)
    put(s, "clock", START_CLOCK)
    put(s, "use_deposits", "1")
    put(s, "revalidate", "1")
    for a in loader.agencies():
        s.add(AgencyVersion(agency_id=a["agency_id"], version_no=1, name=a["name"], representative=a["representative"],
                            address=a["address"], account=a["account"], effective_at=a["registered"],
                            reason="원본 마스터 적재", grade="원본", source_ref=loader.src_ref(loader.AGENCY_CSV, a["agency_id"])))
    for d in loader.deposits():
        s.add(DepositObs(deposit_id=d["deposit_id"], agency_id=d["agency_id"], bank_account_no=d["bank_account_no"]))
    for r in loader.rebates():
        if r["status"] != "미지급":
            s.add(RebateRequest(rebate_id=r["rebate_id"], agency_id=r["agency_id"], period_ym=r["period_ym"],
                                amount=r["amount"], status=HISTORY, src_status=r["status"], src_approver=r["approver"],
                                src_payment_date=r["payment_date"], grade="원본",
                                source_ref=loader.src_ref(loader.REBATE_CSV, r["rebate_id"])))
    log(s, "시스템", "시스템", "초기화", "DB", "원본 마스터 50, 입금 32, 과거 지급 200건 적재", "원본")
    s.commit()


def intake(s: Session, rows: list[dict], grade: str, source: str, note: str = ""):
    """요청 접수. rebate_id가 이미 있으면 중복으로 보고 무시한다."""
    for r in rows:
        if s.get(RebateRequest, r["rebate_id"]):
            log(s, "시스템", "시스템", "중복 요청 무시", r["rebate_id"], "같은 rebate_id가 이미 접수됨")
            continue
        pm, pm_grade = rules.pay_month_of(r["period_ym"])
        s.add(RebateRequest(rebate_id=r["rebate_id"], agency_id=r["agency_id"], period_ym=r["period_ym"],
                            amount=int(r["amount"]), pay_month=pm, pay_month_grade=pm_grade,
                            pay_month_reason="확정 지급월 없음, 정산월 다음 달로 가정(미확인)", status="진행",
                            grade=grade, source_ref=f"{source}#{r['rebate_id']}", note=r.get("note", note)))
        log(s, "시스템", "시스템", "요청 접수", r["rebate_id"], f"{r['agency_id']} {r['period_ym']} {int(r['amount']):,}원", grade)
    s.flush()
    rejudge(s)
    s.commit()


def intake_original(s: Session):
    rows = [r for r in loader.rebates() if r["status"] == "미지급"]
    intake(s, rows, "원본", loader.REBATE_CSV.name)
    put(s, "init_done", SCHEMA)  # R6: 적재와 접수가 모두 끝난 뒤에만 기록. 없거나 스키마 표식이 다르면 시작 시 다시 적재
    s.commit()


# 조회 ------------------------------------------------------------------
def current_agencies(s: Session) -> dict[str, dict]:
    out = {}
    for v in s.scalars(select(AgencyVersion).order_by(AgencyVersion.agency_id, AgencyVersion.version_no)):
        out[v.agency_id] = {"agency_id": v.agency_id, "name": v.name, "representative": v.representative,
                            "address": v.address, "account": v.account, "version": v.version_no}
    return out


def deposits(s: Session) -> list[dict]:
    return [{"deposit_id": d.deposit_id, "agency_id": d.agency_id, "bank_account_no": d.bank_account_no}
            for d in s.scalars(select(DepositObs).order_by(DepositObs.deposit_id))]


def history(s: Session) -> list[dict]:
    return [{"agency_id": r.agency_id, "period_ym": r.period_ym, "amount": r.amount, "status": r.src_status,
             "approver": r.src_approver, "payment_date": r.src_payment_date}
            for r in s.scalars(select(RebateRequest).where(RebateRequest.status == HISTORY))]


def case_requests(s, case_id) -> list[RebateRequest]:
    return list(s.scalars(select(RebateRequest).where(RebateRequest.case_id == case_id).order_by(RebateRequest.rebate_id)))


def use_deposits(s) -> bool:
    return get(s, "use_deposits") == "1"


def context(s) -> dict:
    ags, deps = current_agencies(s), deposits(s)
    group_of, evidence = rules.find_groups(ags, deps, use_deposits(s))
    return {"ags": ags, "deps": deps, "hist": history(s), "group_of": group_of, "evidence": evidence}


def latest_approval(s, c: Case) -> Approval | None:
    return s.scalar(select(Approval).where(Approval.case_id == c.id, Approval.decision == "승인", Approval.valid)
                    .order_by(Approval.id.desc()))


def case_approvals(s, case_id) -> list[Approval]:
    """R2: 이 사건과 병합 전 사건들의 승인, 거절 기록."""
    ids = [case_id] + [int(x) for x in _case(s, case_id).prev_ids.split(",") if x]
    return list(s.scalars(select(Approval).where(Approval.case_id.in_(ids)).order_by(Approval.id)))


def cycle_totals(s) -> dict:
    """R7: 회차(지급월)별 회계 지급 집계. 취소된 작업은 건수와 금액에서 빼고 따로 센다."""
    out = {}
    for t in s.scalars(select(Task).where(Task.type == "회계 지급").order_by(Task.id)):
        p = json.loads(t.payload)
        cyc = out.setdefault(p["지급월"], {"건수": 0, "금액": 0, "상태": {}, "취소 건수": 0, "취소 금액": 0})
        if t.status == "취소":
            cyc["취소 건수"] += 1
            cyc["취소 금액"] += p["금액"]
        else:
            cyc["건수"] += 1
            cyc["금액"] += p["금액"]
            cyc["상태"][t.status] = cyc["상태"].get(t.status, 0) + 1
    return dict(sorted(out.items()))


# R5 지급계좌 확인 -------------------------------------------------------
def account_state(s, aid: str, ags: dict, deps: list[dict]) -> tuple[str, list[str]]:
    """(상태, 관련 입금 DP ID). 지급계좌는 마스터 정산계좌라는 가정. 회수 입금계좌는 지급에 쓰지 않는다."""
    if aid not in ags:
        return "확인 필요(마스터 미등록)", []
    master = ags[aid]["account"]
    if not rules.known(master):
        return "확인 필요(정산계좌 없음)", []
    diff = [d["deposit_id"] for d in deps if d["agency_id"] == aid and d["bank_account_no"] != master]
    if not diff:
        return "해당 없음", []
    key = f"acct:{aid}:{master}"  # 재확인 시도는 key#재확인N
    done = s.scalar(select(Task).where(Task.type == "지급계좌 확인", Task.status == "완료",
                                       or_(Task.idem_key == key, Task.idem_key.like(f"{key}#%"))))
    return ("확인 완료" if done else "확인 필요"), diff


def relation_info(ag: dict) -> str:
    """R3: 대표자, 주소, 정산계좌 중 알려진 값이 2개 미만이면 관계를 판정할 수 없다."""
    n = sum(rules.known(ag[k]) for k in ("representative", "address", "account"))
    return "충분" if n >= 2 else f"확인 필요(관계 정보 부족: 알려진 값 {n}개)"


# 재판정 (R1~R6) ---------------------------------------------------------
def rejudge(s: Session):
    """공통 경로. P4 금액 확인, P3 지급 진행 중 사건 재검증, P2 (그룹, 지급월)당 열린 사건 하나, P1 재합산."""
    ctx = context(s)
    live = list(s.scalars(select(RebateRequest).where(RebateRequest.status != HISTORY)
                          .order_by(RebateRequest.rebate_id)))
    changed = set()
    for r in live:
        if r.status == "진행" and r.amount <= 0:
            log(s, "시스템", "시스템", "요청 확인 필요", r.rebate_id,
                f"금액 {r.amount:,}원: 0 이하라 합산과 지급에서 제외(차감, 상계 기능 없음)")
            changed.add(r.case_id)
            r.status, r.case_id = NEEDS_CHECK, None
        elif r.status == NEEDS_CHECK and r.amount > 0:
            log(s, "시스템", "시스템", "요청 확인 해제", r.rebate_id, f"금액 {r.amount:,}원으로 정정되어 다시 판정")
            r.status = "진행"
    s.flush()
    cases = list(s.scalars(select(Case).order_by(Case.id)))
    if get(s, "revalidate") != "0":
        for c in cases:
            if c.status in IN_FLIGHT:
                gate(s, c, ctx)
    by_id = {c.id: c for c in cases}
    canon = {}
    # P1(R4): 같은 (그룹, 지급월)에서 지급 완료 전 요청은 모두 가장 앞선 열린 사건 하나로 모은다.
    # 지급 진행 중인 사건도 열린 사건이다. 지급 완료된 요청만 제자리에 남고 기지급액으로 합산된다
    for c in cases:
        if c.status not in ("지급 완료", DISSOLVED):
            canon.setdefault((c.group_key, c.pay_month), c)
    moves = {}
    for r in live:
        if r.status != "진행":
            continue
        key = (ctx["group_of"].get(r.agency_id, r.agency_id), r.pay_month)
        cur, c = by_id.get(r.case_id), canon.get(key)
        if c is not None and c is cur:
            continue
        if c is None:
            c = Case(group_key=key[0], pay_month=key[1], status="접수")
            s.add(c)
            s.flush()
            canon[key] = by_id[c.id] = c
            log(s, "시스템", "시스템", "사건 생성", f"사건 {c.id}", f"그룹 {key[0]}, 지급월 {key[1]}")
        if cur:
            merge = (cur.group_key, cur.pay_month) == key
            log(s, "시스템", "시스템", "요청 재배정", r.rebate_id,
                f"사건 {cur.id} -> 사건 {c.id}" + (" (같은 그룹, 지급월 사건 병합)" if merge else ""))
            changed.add(cur.id)
            moves.setdefault(cur.id, []).append(c.id)
        changed.add(c.id)
        r.case_id = c.id
    s.flush()
    for cid in sorted(x for x in changed if x in by_id):
        _composition_changed(s, by_id[cid])
    for src, dsts in sorted(moves.items()):
        _inherit(s, by_id[src], [by_id[d] for d in dict.fromkeys(dsts)])
    for c in by_id.values():
        if c.status not in FROZEN and c.status != DISSOLVED:
            refresh(s, c, ctx)


def cancel_payments(s, case_id) -> list[str]:
    """지급 완료 전 지급 작업과 재처리 작업을 취소한다. 취소된 지급 작업은 멱등 키를 비워
    같은 요청의 새 지급 작업이 생길 수 있게 한다(한 요청의 활성 지급 작업은 DB 유일 키로 하나, R1)."""
    out = []
    for t in s.scalars(select(Task).where(Task.case_id == case_id, Task.type.in_(("회계 지급", "은행 재처리")),
                                          Task.status.in_(("열림", "지급 대기", "지급 반려"))).order_by(Task.id)):
        t.status = "취소"
        if t.type == "회계 지급":
            t.idem_key = f"{t.idem_key}#취소{t.id}"
        out.append(str(t.id))
    return out


def _composition_changed(s, c: Case):
    """접수, 회차 이동, 그룹 변경, 병합으로 사건 구성이 바뀌면 기존 승인은 근거가 바뀌므로 무효.
    지급 완료 전 지급 작업은 취소하고 다시 판정한다(R4: 은행 회신 전 작업은 취소 가능하다는 단순화)."""
    for a in s.scalars(select(Approval).where(Approval.case_id == c.id, Approval.decision == "승인", Approval.valid)
                       .order_by(Approval.id)):  # Postgres는 정렬 없이는 순서를 보장하지 않는다(이력 순서 고정)
        a.valid, a.invalid_reason = False, "사건 구성 변경(접수, 병합, 재배정): 승인 당시 요청 구성과 다름"
        log(s, "시스템", "시스템", "승인 무효", f"사건 {c.id}", f"승인 {a.id}: {a.invalid_reason}")
    cancelled = cancel_payments(s, c.id)
    if c.status in ("승인됨", "실행 전 재검증") + IN_FLIGHT:
        transition(s, c, "접수", detail="사건 구성 변경으로 승인 무효" +
                   (f", 지급 완료 전 작업 취소: {', '.join(cancelled)}" if cancelled else "") + ", 다시 판정")


def _inherit(s, src: Case, dsts: list[Case]):
    """R2: 요청을 넘겨받은 사건은 이전 사건의 이력 연결과 미해결 조건(거절 뒤 소명 요청)을 승계한다."""
    open_q = select(Task).where(Task.case_id == src.id, Task.status == "열림").order_by(Task.id)
    explain = list(s.scalars(open_q.where(Task.type == "소명 요청")))
    for dst in dsts:
        prev = {x for x in f"{dst.prev_ids},{src.prev_ids}".split(",") if x} | {str(src.id)}
        dst.prev_ids = ",".join(sorted(prev - {str(dst.id)}, key=int))
        for t in explain:
            add_task(s, t.type, t.dept, f"{t.idem_key}>{dst.id}", case_id=dst.id,
                     payload=json.loads(t.payload) | {"승계": f"사건 {src.id}의 작업 {t.id}"})
        if explain:
            transition(s, dst, "거절됨", detail=f"사건 {src.id}의 거절과 미확인 소명 요청 승계: 소명 확인 전 재상신 불가")
    if not case_requests(s, src.id):  # 요청이 모두 떠난 사건의 열린 작업은 넘겨받은 사건으로 옮긴다
        for t in s.scalars(open_q):
            if t.type == "소명 요청":
                t.status = "승계"
            else:
                t.case_id = dsts[0].id


def build_basis(s, c: Case, ctx: dict) -> dict:
    """P1: 현재 관련자 그룹 구성원 x 지급월의 유효 요청 전부로 다시 계산한다.

    이 사건 요청(지급 완료 전 요청은 모두 이 사건에 모여 있다) + 다른 사건에서 지급 완료된 요청 + 원본 기지급.
    """
    ags, group_of = ctx["ags"], ctx["group_of"]
    reqs = [r for r in case_requests(s, c.id) if r.status != NEEDS_CHECK]
    members = sorted({m for r in reqs for m in group_of.get(r.agency_id, r.agency_id).split("+")}) \
        or c.group_key.split("+")
    own = {r.rebate_id for r in reqs}
    others = [r for r in s.scalars(select(RebateRequest).where(
        RebateRequest.agency_id.in_(members), RebateRequest.pay_month == c.pay_month,
        RebateRequest.status == "지급 완료").order_by(RebateRequest.rebate_id)) if r.rebate_id not in own]
    paid_hist = rules.already_paid(ctx["hist"], members, c.pay_month)
    paid = paid_hist + sum(r.amount for r in others)
    total = sum(r.amount for r in reqs) + paid
    accounts = {}
    for m in members:
        st, dps = account_state(s, m, ags, ctx["deps"])
        accounts[m] = {"지급계좌(마스터 정산계좌)": ags[m]["account"] if m in ags else "미등록", "확인": st,
                       "다른 입금 관측": dps}
    return {
        "구성원": [{"거래처": m, "마스터 버전": ags[m]["version"], "대표자": ags[m]["representative"],
                  "주소": ags[m]["address"], "관계 정보": relation_info(ags[m])} if m in ags else {"거래처": m, "마스터 버전": "미등록"} for m in members],
        "관계 근거": {f"{x}~{y}": ev for (x, y), ev in sorted(ctx["evidence"].items()) if x in members},
        "요청": [{"요청": r.rebate_id, "거래처": r.agency_id, "정산월": r.period_ym, "금액": r.amount,
                "지급월 등급": r.pay_month_grade} for r in reqs],
        "지급월": c.pay_month,
        "기지급(같은 지급월)": paid,
        "지급 완료된 다른 요청": [{"요청": r.rebate_id, "거래처": r.agency_id, "금액": r.amount}
                                   for r in others],
        "합계": total,
        "경로": rules.route_of(total),
        "지급계좌": accounts,
    }


def _stamp(c: Case, basis: dict):
    c.basis_json, c.basis_hash = json.dumps(basis, ensure_ascii=False, sort_keys=True), rules.basis_hash(basis)
    c.total, c.paid, c.route = basis["합계"], basis["기지급(같은 지급월)"], basis["경로"]


def blocked(basis: dict) -> bool:
    return any(v["확인"].startswith("확인 필요") for v in basis["지급계좌"].values()) or \
        any(m.get("관계 정보", "").startswith("확인 필요") for m in basis["구성원"])


def computed_status(c: Case) -> str:
    b = json.loads(c.basis_json)
    if blocked(b):
        return "확인 필요"
    return "전결 승인 대기" if b["경로"] == rules.ROUTE_SUPPORT else "상위 승인 필요"


def refresh(s, c: Case, ctx: dict):
    reqs = case_requests(s, c.id)
    if not reqs:
        transition(s, c, DISSOLVED, detail="재판정 결과 이 사건에 남은 요청이 없음")
        return
    if all(r.status == "지급 완료" for r in reqs):
        transition(s, c, "지급 완료", detail="남은 미지급 요청 없음")
        return
    prev, old = c.basis_hash, json.loads(c.basis_json)
    basis = build_basis(s, c, ctx)
    _stamp(c, basis)
    h = c.basis_hash
    if prev and h != prev:
        log(s, "시스템", "시스템", "근거 변경", f"사건 {c.id}", "\n".join(rules.basis_diff(old, basis)))
    for m, v in basis["지급계좌"].items():
        if v["확인"].startswith("확인 필요"):
            reason = ("마스터 미등록 거래처: 관계와 지급계좌를 판정할 수 없음" if "미등록" in v["확인"] else
                      "마스터 정산계좌 없음: 마스터 정정 신고로 정산계좌를 등록해야 지급할 수 있음"
                      if "정산계좌 없음" in v["확인"] else
                      f"마스터 정산계좌와 다른 회수 입금 관측({', '.join(v['다른 입금 관측'])}). "
                      "지급계좌는 마스터 정산계좌를 쓴다는 가정이 맞는지 대리점 회신으로 확인")
            add_task(s, "지급계좌 확인", "영업지원", f"acct:{m}:{v['지급계좌(마스터 정산계좌)']}", case_id=c.id,
                     agency_id=m, payload={"사유": reason, "확인 대상 지급계좌": v["지급계좌(마스터 정산계좌)"]})
    for m in basis["구성원"]:
        if m.get("관계 정보", "").startswith("확인 필요"):
            add_task(s, "관계 정보 확인", "영업지원", f"relinfo:{m['거래처']}:v{m['마스터 버전']}", case_id=c.id,
                     agency_id=m["거래처"], payload={"사유": f"{m['관계 정보']}. 대표자, 주소, 정산계좌 중 2개 이상 있어야 "
                                                       "관계를 판정할 수 있음. 마스터 정정 신고로 보완"})
        elif "관계 정보" in m:
            for t in s.scalars(select(Task).where(Task.type == "관계 정보 확인", Task.status == "열림",
                                                  Task.agency_id == m["거래처"])):
                t.status = "완료"
    if c.status in PRE:
        transition(s, c, computed_status(c), detail=f"합계 {c.total:,}원, {c.route}")
    elif c.status == "승인 대기" and h != c.submitted_hash:
        transition(s, c, computed_status(c), detail="상신 후 근거 변경, 다시 상신 필요")


# R7 재검증 게이트 -------------------------------------------------------
def gate(s, c: Case, ctx: dict) -> bool:
    """P3: 지급으로 이어지는 모든 경로(실행, 은행 재처리, 지급 진행 중 재판정)가 지나는 단 하나의 재검증.

    근거가 승인 당시와 다르면 승인을 무효로 하고, 지급 완료가 아닌 지급 작업과 재처리 작업을 취소한다.
    """
    a = latest_approval(s, c)
    basis = build_basis(s, c, ctx)
    _stamp(c, basis)
    if a and a.basis_hash == c.basis_hash:
        return True
    diff = rules.basis_diff(json.loads(a.basis_json), basis) if a else ["유효한 승인 없음"]
    if a and get(s, "revalidate") == "0":
        # 대조군 D 전용. 기본값은 켬이며, 끄면 승인 후 변경이 옛 승인으로 실행되는 것을 일부러 보여준다
        log(s, "시스템", "시스템", "재검증 끔(대조군 D): 옛 승인으로 실행", f"사건 {c.id}", "\n".join(diff))
        return True
    if a:
        a.valid, a.invalid_reason = False, "\n".join(diff)
    cancelled = cancel_payments(s, c.id)
    transition(s, c, "승인 무효(재상신)", detail="승인 당시 근거와 현재 근거가 다름")
    log(s, "시스템", "시스템", "재검증 차단", f"사건 {c.id}",
        "\n".join(diff + ([f"지급 완료 전 작업 취소: {', '.join(cancelled)}"] if cancelled else [])))
    add_task(s, "재상신", "영업지원", f"resubmit:{a.id if a else c.id}", case_id=c.id, payload={"달라진 근거": diff})
    return False


def unpayable(r: RebateRequest, ags: dict) -> str:
    """P4, F7: 지급에 필요한 정보가 없으면 그 이유. 지급 작업을 만들기 직전 마지막 방어선."""
    if r.amount <= 0:
        return "금액 0 이하"
    if r.agency_id not in ags:
        return "마스터 미등록"
    if not rules.known(ags[r.agency_id]["account"]):
        return "정산계좌 없음"
    if relation_info(ags[r.agency_id]) != "충분":
        return "관계 정보 부족"
    if r.pay_month_grade not in CONFIRMED_PM:
        return "지급월 미확정"
    return ""


# 사람의 결정 ------------------------------------------------------------
def _case(s, case_id) -> Case:
    c = s.get(Case, case_id)
    if not c:
        raise ValueError(f"사건 {case_id} 없음")
    return c


def facts_of(c: Case) -> dict:
    b = json.loads(c.basis_json)
    return {"members": [m["거래처"] for m in b["구성원"]], "evidence": b["관계 근거"], "pay_month": c.pay_month,
            "requests": b["요청"], "total": c.total, "route": c.route}


def submit(s: Session, case_id: int, actor="영업지원 담당자", use_ai=True):
    """상신(임원 경로) 또는 재상신(전결 경로는 전결 승인 대기로)."""
    rejudge(s)
    c = _case(s, case_id)
    if c.status not in ("상위 승인 필요", "승인 무효(재상신)"):
        raise ValueError(f"상신할 수 없는 상태: {c.status}")
    if blocked(json.loads(c.basis_json)):
        transition(s, c, "확인 필요", actor, "사람", "지급계좌 확인 회신 대기")
    elif c.route == rules.ROUTE_SUPPORT:
        transition(s, c, "전결 승인 대기", actor, "사람", "재상신(전결 경로)")
    else:
        text, label = ai.draft(facts_of(c), use_ai)
        d = Doc(kind="상신 초안", case_id=c.id, text=text, extractor=label, status="초안", grade="도출")
        s.add(d)
        s.flush()
        log(s, "AI" if label.startswith("AI 사용") else "시스템", "AI" if label.startswith("AI 사용") else "시스템",
            "상신 초안 작성", f"문서 {d.id}", label)
        c.submitted_hash = c.basis_hash
        transition(s, c, "승인 대기", actor, "사람", "영업임원에게 상신")
    for t in s.scalars(select(Task).where(Task.case_id == c.id, Task.type == "재상신", Task.status == "열림")):
        t.status = "완료"
    s.commit()


def approve(s: Session, case_id: int, role: str, actor: str | None = None):
    s.expire_all()  # R1: 세션에 남은 옛 객체가 아니라 DB 최신 상태로 판단. 쓰는 순간의 경합은 Case.version이 막는다
    rejudge(s)
    c = _case(s, case_id)
    need = {"전결 승인 대기": "영업지원", "승인 대기": "영업임원"}.get(c.status)
    if need is None:
        raise ValueError(f"승인할 수 없는 상태: {c.status}")
    if role != need:
        raise PermissionError(f"이 사건의 승인권자는 {need}입니다")
    # F7: 승인이 지급 회차를 확정한다. 등급을 바꾼 뒤의 근거로 승인 해시를 고정한다
    for r in case_requests(s, c.id):
        if r.status == "진행" and r.pay_month_grade not in CONFIRMED_PM:
            r.pay_month_grade = "확정(승인 시)"
            r.pay_month_reason = f"{r.pay_month_reason}; {now(s)} 승인으로 {c.pay_month} 회차 확정".lstrip("; ")
    s.flush()
    _stamp(c, build_basis(s, c, context(s)))
    if c.status == "승인 대기":
        c.submitted_hash = c.basis_hash
    a = Approval(case_id=c.id, role=role, decision="승인", basis_hash=c.basis_hash, basis_json=c.basis_json,
                 decided_at=now(s))
    s.add(a)
    s.flush()
    log(s, actor or role, "사람", "승인", f"사건 {c.id}",
        f"승인 {a.id}, 근거 해시 {c.basis_hash[:12]}, {c.pay_month} 회차 지급 확정")
    transition(s, c, "승인됨", actor or role, "사람")
    s.commit()


def approve_all_support(s: Session, actor="영업지원 담당자") -> int:
    ids = [c.id for c in s.scalars(select(Case).where(Case.status == "전결 승인 대기").order_by(Case.id))]
    for i in ids:
        approve(s, i, "영업지원", actor)
    return len(ids)


def reject(s: Session, case_id: int, reason: str, actor="영업임원"):
    c = _case(s, case_id)
    if c.status != "승인 대기":
        raise ValueError(f"거절할 수 없는 상태: {c.status}")
    if not reason.strip():
        raise ValueError("거절 사유는 필수입니다")
    a = Approval(case_id=c.id, role="영업임원", decision="거절", reason=reason, basis_hash=c.basis_hash,
                 basis_json=c.basis_json, decided_at=now(s), valid=False)
    s.add(a)
    s.flush()
    log(s, actor, "사람", "거절", f"사건 {c.id}", reason)
    transition(s, c, "거절됨", actor, "사람", reason)
    add_task(s, "소명 요청", "영업", f"explain:{a.id}", case_id=c.id,
             payload={"요청 내용": f"영업임원 거절 사유에 대한 대리점 소명과 증빙 요청: {reason}"})
    s.commit()


# R7 실행 전 재검증 ------------------------------------------------------
def would_reuse(s: Session, case_id: int) -> dict:
    """대조 D: 재검증 없이 옛 승인을 재사용하면 어떻게 됐을지(상태를 바꾸지 않음)."""
    c = _case(s, case_id)
    a = s.scalar(select(Approval).where(Approval.case_id == c.id, Approval.decision == "승인")
                 .order_by(Approval.id.desc()))
    if not a:
        return {}
    old = json.loads(a.basis_json)
    return {"승인": a.id, "재사용 시": f"승인 {a.id}의 옛 근거로 지급 작업 {len(old['요청'])}건 생성, 합계 {old['합계']:,}원",
            "재검증 시": "통과" if a.basis_hash == c.basis_hash else "차단(승인 무효, 재상신)",
            "달라진 근거": rules.basis_diff(old, json.loads(c.basis_json))}


def execute(s: Session, case_id: int, actor="회계") -> bool:
    s.expire_all()  # R1: approve와 같음
    rejudge(s)
    c = _case(s, case_id)
    if c.status != "승인됨":
        raise ValueError(f"실행할 수 없는 상태: {c.status}")
    transition(s, c, "실행 전 재검증", actor, "사람", "지급 실행 요청")
    ctx = context(s)
    if not gate(s, c, ctx):
        s.commit()
        return False
    a = latest_approval(s, c)
    basis = json.loads(c.basis_json)
    if blocked(basis):  # 근거 해시에 포함되므로 여기 올 일은 없지만 지급 전 마지막 방어선
        transition(s, c, "확인 필요", detail="지급계좌 미확인")
        s.commit()
        return False
    if a.basis_hash == c.basis_hash:
        log(s, "시스템", "시스템", "재검증 통과", f"사건 {c.id}", f"승인 {a.id} 근거 해시 일치")
    todo = [r for r in case_requests(s, c.id) if r.status == "진행"]  # 이미 지급 완료된 요청은 다시 지급하지 않는다
    bad = [f"{r.rebate_id}: {why}" for r in todo if (why := unpayable(r, ctx["ags"]))]
    if bad:
        a.valid, a.invalid_reason = False, "지급 정보 부족: " + ", ".join(bad)
        transition(s, c, "확인 필요", detail=a.invalid_reason)
        s.commit()
        return False
    for r in todo:  # 멱등 키 pay:요청ID는 승인 ID와 무관하게 활성 지급 작업을 요청당 하나로 묶는다(R1)
        add_task(s, "회계 지급", "회계", f"pay:{r.rebate_id}", case_id=c.id, request_id=r.rebate_id,
                 agency_id=r.agency_id, payload={"요청": r.rebate_id, "거래처": r.agency_id, "금액": r.amount,
                                                 "지급월": c.pay_month, "지급 실행일(가정)": rules.exec_day_of(c.pay_month),
                                                 "지급계좌(마스터 정산계좌)": ctx["ags"][r.agency_id]["account"], "승인": a.id})
    for t in s.scalars(select(Task).where(Task.case_id == c.id, Task.type == "회계 지급", Task.status == "열림")):
        t.status = "지급 대기"
    transition(s, c, "지급 작업 생성")
    s.commit()
    return True


def execute_all(s: Session, actor="회계") -> dict:
    ids = [c.id for c in s.scalars(select(Case).where(Case.status == "승인됨").order_by(Case.id))]
    res = {i: execute(s, i, actor) for i in ids}
    return {"통과": sum(res.values()), "차단": len(res) - sum(res.values())}


# 은행 회신 (모의) -------------------------------------------------------
def _sync_case_payment(s, case_id):
    c = _case(s, case_id)
    st = [t.status for t in s.scalars(select(Task).where(Task.case_id == case_id, Task.type == "회계 지급",
                                                         Task.status != "취소"))]
    if "지급 반려" in st:
        transition(s, c, "지급 반려(재처리)")
    elif st and all(x == "지급 완료" for x in st):
        transition(s, c, "지급 완료")
    else:
        transition(s, c, "지급 작업 생성")


def bank_reply(s: Session, task_id: int, result: str, actor="모의 은행"):
    t = s.get(Task, task_id)
    if not t or t.type != "회계 지급":
        raise ValueError("회계 지급 작업이 아님")
    if t.status == "취소":
        log(s, actor, "모의 외부", "취소된 지급 작업 회신 무시", f"작업 {t.id}", f"회신 {result}: 근거 변경으로 취소된 작업",
            "모의 회신")
        s.commit()
        return
    if t.status != "지급 대기":
        log(s, actor, "모의 외부", "중복 회신 무시", f"작업 {t.id}", f"현재 {t.status}, 회신 {result}", "모의 회신")
        s.commit()
        return
    log(s, actor, "모의 외부", "은행 회신", f"작업 {t.id}", f"{t.request_id}: {result}", "모의 회신")
    t.grade = "모의 회신"
    if result == "성공":
        t.status = "지급 완료"
        s.get(RebateRequest, t.request_id).status = "지급 완료"
    else:
        t.status = "지급 반려"
        n = len(list(s.scalars(select(Task).where(Task.type == "은행 재처리", Task.request_id == t.request_id))))
        add_task(s, "은행 재처리", "회계", f"retry:{t.id}:{n + 1}", case_id=t.case_id, request_id=t.request_id,
                 agency_id=t.agency_id, payload={"지급 작업": t.id, "사유": "은행 반려 회신. 지급 완료가 아님"})
    _sync_case_payment(s, t.case_id)
    s.commit()


def bank_reply_all(s: Session, result="성공") -> int:
    ids = [t.id for t in s.scalars(select(Task).where(Task.type == "회계 지급", Task.status == "지급 대기")
                                   .order_by(Task.id))]
    for i in ids:
        bank_reply(s, i, result)
    return len(ids)


def retry_payment(s: Session, retry_task_id: int, actor="회계") -> bool:
    r = s.get(Task, retry_task_id)
    if not r or r.type != "은행 재처리" or r.status != "열림":
        raise ValueError("열린 은행 재처리 작업이 아님" + (": 근거 변경으로 취소됨, 재상신 필요" if r and r.status == "취소" else ""))
    c = _case(s, r.case_id)
    if not gate(s, c, context(s)):  # 재처리도 실행과 같은 재검증 게이트를 지난다
        s.commit()
        return False
    a = latest_approval(s, c)
    if a.basis_hash == c.basis_hash:
        log(s, "시스템", "시스템", "재검증 통과", f"사건 {c.id}", f"승인 {a.id} 근거 해시 일치(은행 재처리)")
    t = s.get(Task, json.loads(r.payload)["지급 작업"])
    r.status = "완료"
    t.status = "지급 대기"
    log(s, actor, "사람", "은행 재처리 요청", f"작업 {t.id}", t.request_id)
    _sync_case_payment(s, t.case_id)
    s.commit()
    return True


# 모의 회신과 문서 -------------------------------------------------------
def account_reply(s: Session, task_id: int, valid: bool, actor="대리점(모의)"):
    t = s.get(Task, task_id)
    if not t or t.type != "지급계좌 확인" or t.status != "열림":
        raise ValueError("열린 지급계좌 확인 작업이 아님")
    if valid and not rules.known(current_agencies(s).get(t.agency_id, {}).get("account")):
        raise ValueError("정산계좌가 없어 '유효' 회신으로 확인할 수 없습니다. 마스터 정정 신고로 정산계좌를 먼저 등록해야 합니다")
    t.status, t.grade = ("완료" if valid else "확인 불가"), "모의 회신"
    log(s, actor, "모의 외부", "지급계좌 회신", f"작업 {t.id}",
        f"{t.agency_id}: {'마스터 정산계좌가 지급계좌임을 확인' if valid else '확인 불가, 보류 유지'}", "모의 회신")
    rejudge(s)
    s.commit()


def recheck_account(s: Session, task_id: int, actor="영업지원 담당자") -> int:
    """R5: '확인 불가'로 끝난 지급계좌 확인을 새 확인 작업으로 다시 요청한다. 같은 작업에서 다시 눌러도 하나만 생긴다."""
    t = s.get(Task, task_id)
    if not t or t.type != "지급계좌 확인" or t.status != "확인 불가":
        raise ValueError("확인 불가로 끝난 지급계좌 확인 작업이 아님")
    nt, new = add_task(s, t.type, t.dept, f"{t.idem_key.split('#')[0]}#재확인{t.id}", case_id=t.case_id,
                       agency_id=t.agency_id, payload=json.loads(t.payload) | {"재확인": f"작업 {t.id} 확인 불가 뒤 다시 요청"})
    if new:
        log(s, actor, "사람", "지급계좌 재확인 요청", f"작업 {nt.id}", f"{t.agency_id}: 작업 {t.id} 확인 불가")
    s.commit()
    return nt.id


def receive_doc(s: Session, kind: str, agency_id: str, text: str, case_id=None, grade="합성", source_ref="",
                use_ai=True) -> int:
    ext = ai.extract(text, use_ai)
    d = Doc(kind=kind, case_id=case_id, agency_id=agency_id, text=text, grade=grade, source_ref=source_ref,
            extraction_json=json.dumps(ext, ensure_ascii=False), extractor=ext["extractor"], status="확인 대기")
    s.add(d)
    s.flush()
    log(s, "대리점(모의)", "모의 외부", "문서 접수", f"문서 {d.id}", f"{kind} {agency_id}", "모의 회신")
    log(s, "AI" if ext["extractor"].startswith("AI 사용") else "시스템",
        "AI" if ext["extractor"].startswith("AI 사용") else "시스템", "문서 구조화", f"문서 {d.id}",
        f"{ext['extractor']}, 인용 확인 {sum(len(v) for v in ext['fields'].values())}건, 근거 없음 {len(ext['dropped'])}건")
    s.commit()
    return d.id


def confirm_doc(s: Session, doc_id: int, actor="영업지원 담당자", correction: dict | None = None):
    """담당자 확인. 확인 전 AI 추출은 어떤 판정에도 쓰이지 않는다."""
    d = s.get(Doc, doc_id)
    if not d or d.status != "확인 대기":
        raise ValueError("확인 대기 문서가 아님")
    if d.kind == "정정 신고":
        field = {"주소": "address", "대표자": "representative", "정산계좌": "account"}[correction["field"]]
        aid = correction["agency_id"]
        cur = s.scalars(select(AgencyVersion).where(AgencyVersion.agency_id == aid)
                        .order_by(AgencyVersion.version_no.desc())).first()
        if cur is None:
            raise ValueError(f"마스터에 없는 거래처: {aid}")
        nv = AgencyVersion(agency_id=aid, version_no=cur.version_no + 1, name=cur.name,
                           representative=cur.representative, address=cur.address, account=cur.account,
                           effective_at=now(s), reason=f"정정 신고 문서 {d.id}, 담당자 확정", grade=d.grade,
                           source_ref=f"doc:{d.id}")
        setattr(nv, field, correction["value"])
        s.add(nv)
        log(s, actor, "사람", "정정 확정", aid,
            f"{correction['field']}: {getattr(cur, field)} -> {correction['value']} (마스터 v{nv.version_no})", d.grade)
    else:
        for t in s.scalars(select(Task).where(Task.case_id == d.case_id, Task.type == "소명 요청",
                                              Task.status == "열림")):
            t.status = "완료"
        log(s, actor, "사람", "소명 확인", f"문서 {d.id}", f"사건 {d.case_id} 소명 접수 확인")
    d.status, d.confirmed_by = "확인됨", actor
    s.flush()
    rejudge(s)
    if d.kind == "소명 회신" and d.case_id:
        c = _case(s, d.case_id)
        if c.status == "거절됨":
            transition(s, c, computed_status(c), actor, "사람", "소명 확인 후 재판정")
    s.commit()


def correct_amount(s: Session, rebate_id: str, amount: int, reason: str, source_ref: str, actor="영업지원 담당자"):
    r = s.get(RebateRequest, rebate_id)
    if not r or r.status == HISTORY:
        raise ValueError("진행 중인 요청이 아님")
    if r.status == "지급 완료":
        raise ValueError("이미 지급 완료된 요청은 금액을 정정할 수 없습니다")
    log(s, actor, "사람", "금액 정정", rebate_id, f"{r.amount:,} -> {amount:,}원: {reason}", "합성")
    r.amount, r.grade = amount, "합성"
    r.note = f"{r.note} 금액 정정({source_ref}): {reason}".strip()
    s.flush()
    rejudge(s)
    s.commit()


def set_revalidate(s: Session, on: bool, actor="시연자"):
    put(s, "revalidate", "1" if on else "0")
    log(s, actor, "사람", "설정 변경", "실행 전 재검증(대조군 D)", "켬" if on else "끔")
    s.commit()


def set_use_deposits(s: Session, on: bool, actor="영업지원 담당자"):
    put(s, "use_deposits", "1" if on else "0")
    log(s, actor, "사람", "설정 변경", "입금계좌 대조", "켬" if on else "끔")
    rejudge(s)
    s.commit()


# R8 회차와 마감 ---------------------------------------------------------
def advance_clock(s: Session, ts: str, actor="시연자"):
    if datetime.strptime(ts, "%Y-%m-%d %H:%M") < datetime.strptime(now(s), "%Y-%m-%d %H:%M"):
        raise ValueError("가상 시각은 앞으로만 이동합니다")
    put(s, "clock", ts)
    log(s, actor, "사람", "가상 시각 이동", "시계", ts, "가정")
    t = datetime.strptime(ts, "%Y-%m-%d %H:%M")
    moved = True
    while moved:
        moved = False
        for c in list(s.scalars(select(Case).order_by(Case.id))):
            if c.status in APPROVED or c.status == DISSOLVED or rules.deadline_of(c.pay_month) > t:
                continue
            _move_to_next_cycle(s, c)
            moved = True
    s.commit()


def _move_to_next_cycle(s, c: Case):
    old, new, prev = c.pay_month, rules.next_month(c.pay_month), c.status
    dl = rules.deadline_of(old).strftime("%Y-%m-%d %H:%M")
    transition(s, c, "다음 회차 이동", detail=f"승인 지연: {old} 회차 마감 {dl}까지 승인되지 않음")
    for r in case_requests(s, c.id):
        r.pay_month, r.pay_month_grade = new, "도출"
        r.pay_month_reason = f"승인 지연({old} 회차 마감 {dl} 경과, 마감 규칙에 따라 이동)"
    c.pay_month = new
    for a in s.scalars(select(Approval).where(Approval.case_id == c.id, Approval.valid)):
        a.valid, a.invalid_reason = False, f"회차 이동 {old} -> {new}"
    add_task(s, "대리점 안내", "영업", f"notice:{c.id}:{new}", case_id=c.id,
             payload={"안내": f"그룹 {c.group_key}의 장려금 지급이 {old} 회차에서 {new} 회차로 이동(사유: 승인 지연)",
                      "새 지급 실행일(가정)": rules.exec_day_of(new)})
    pay_old = cycle_totals(s).get(old, {}).get("건수", 0)  # 취소된 작업은 세지 않는다(R7)
    add_task(s, "회차 목록 재생성", "회계", f"cycle:{c.id}:{new}", case_id=c.id,
             payload={"변경": f"사건 {c.id}을 {old} 회차 목록에서 빼고 {new} 회차 목록에 추가",
                      f"{old} 회차 지급 작업 수(유지)": pay_old, "이동 요청 수": len(case_requests(s, c.id))})
    s.flush()
    c.status = prev if prev == "거절됨" else "접수"  # 거절된 사건은 소명 대기 유지, 나머지는 새 지급월로 재판정
    log(s, "시스템", "시스템", "상태 전이", f"사건 {c.id}", f"다음 회차 이동 -> {c.status}: {new} 기준 재판정")
    rejudge(s)
