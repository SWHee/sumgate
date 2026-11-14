"""고정 규칙 R1~R4, R6, R8. 순수 함수만 둔다. LLM 호출 없음."""
import hashlib
import json
from collections import deque
from datetime import datetime

LIMIT = 2_000_000
ROUTE_SUPPORT = "영업지원팀 전결"
ROUTE_EXEC = "영업임원 승인"


# R1 관계 ---------------------------------------------------------------
def known(v) -> bool:
    """P4: 값이 없거나 'NONE'인 식별정보는 일치로 세지 않는다."""
    return (v or "").strip() not in ("", "NONE")


def _accounts(agency: dict, deposits: list[dict], use_deposits: bool) -> dict[str, list[str]]:
    """계좌번호 -> 출처 목록('마스터 vN' 또는 입금 DP ID). 값이 없는 계좌는 넣지 않는다."""
    acc = {agency["account"]: [f"마스터 v{agency['version']}"]} if known(agency["account"]) else {}
    if use_deposits:
        for d in deposits:
            if d["agency_id"] == agency["agency_id"] and known(d["bank_account_no"]):
                acc.setdefault(d["bank_account_no"], []).append(d["deposit_id"])
    return acc


def pair_match(a: dict, b: dict, deposits: list[dict], use_deposits: bool) -> tuple[list[str], str]:
    """두 거래처의 일치 항목과 출처 문자열. 계좌 번호 자체는 근거에 적지 않는다."""
    items = []
    if known(a["representative"]) and a["representative"] == b["representative"]:
        items.append("대표자")
    if known(a["address"]) and a["address"] == b["address"]:
        items.append("주소")
    acc_a = _accounts(a, deposits, use_deposits)
    acc_b = _accounts(b, deposits, use_deposits)
    common = sorted(set(acc_a) & set(acc_b))
    src = ""
    if common:
        sa = sorted({s for c in common for s in acc_a[c]})
        sb = sorted({s for c in common for s in acc_b[c]})
        master_only = all(s.startswith("마스터") for s in sa + sb)
        items.append("정산계좌" if master_only else "입금계좌")
        src = f"계좌 출처 {a['agency_id']}: {', '.join(sa)} / {b['agency_id']}: {', '.join(sb)}"
    return items, src


def find_groups(agencies: dict[str, dict], deposits: list[dict], use_deposits: bool):
    """반환: (agency_id -> group_key, {(a, b): 근거 문자열} 다구성원 그룹 안의 모든 쌍).

    2개 이상 일치하면 연결, 연결은 전이적(그래프 연결요소).
    """
    ids = sorted(agencies)
    edges: dict[str, set[str]] = {i: set() for i in ids}
    direct: dict[tuple[str, str], str] = {}
    for i, a in enumerate(ids):  # ponytail: O(n^2) 쌍 비교, 거래처 수천 곳이면 키 색인으로 교체
        for b in ids[i + 1:]:
            items, src = pair_match(agencies[a], agencies[b], deposits, use_deposits)
            if len(items) >= 2:
                edges[a].add(b)
                edges[b].add(a)
                ver = f"마스터 {a} v{agencies[a]['version']}, {b} v{agencies[b]['version']}"
                direct[(a, b)] = f"직접 일치: {' + '.join(items)} ({ver}{'; ' + src if src else ''})"
    group_of, seen = {}, set()
    for i in ids:
        if i in seen:
            continue
        comp, q = [], deque([i])
        seen.add(i)
        while q:
            x = q.popleft()
            comp.append(x)
            for y in edges[x]:
                if y not in seen:
                    seen.add(y)
                    q.append(y)
        key = "+".join(sorted(comp))
        for x in comp:
            group_of[x] = key
    evidence = {}
    for key in set(group_of.values()):
        members = key.split("+")
        for i, a in enumerate(members):
            for b in members[i + 1:]:
                evidence[(a, b)] = direct.get((a, b)) or f"전이 연결(경유: {', '.join(_path(edges, a, b)[1:-1])})"
    return group_of, evidence


def _path(edges, a, b):
    prev, q = {a: None}, deque([a])
    while q:
        x = q.popleft()
        if x == b:
            break
        for y in sorted(edges[x]):
            if y not in prev:
                prev[y] = x
                q.append(y)
    path, x = [], b
    while x is not None:
        path.append(x)
        x = prev[x]
    return path[::-1]


# R2 지급월 -------------------------------------------------------------
def next_month(ym: str) -> str:
    y, m = int(ym[:4]), int(ym[5:7])
    return f"{y + m // 12}-{m % 12 + 1:02d}"


def pay_month_of(period_ym: str, confirmed: str | None = None) -> tuple[str, str]:
    """(지급월, 등급). 확정값이 없으면 정산월 다음 달, 등급 '가정'(화면에는 미확인)."""
    if confirmed:
        return confirmed, "원본"
    return next_month(period_ym), "가정"


# R3, R4 합산과 경로 ----------------------------------------------------
def route_of(total: int) -> str:
    return ROUTE_SUPPORT if total <= LIMIT else ROUTE_EXEC


def already_paid(history: list[dict], members: list[str], pay_month: str) -> int:
    """같은 지급월(payment_date 기준)에 이미 지급된 금액."""
    return sum(int(h["amount"]) for h in history
               if h["agency_id"] in members and h["payment_date"] != "NONE" and h["payment_date"][:7] == pay_month)


def assess(requests: list[dict], agencies: dict, deposits: list[dict], history: list[dict], use_deposits: bool = True):
    """요청 목록을 (그룹, 지급월) 사건으로 묶어 합계와 경로를 계산한다."""
    group_of, evidence = find_groups(agencies, deposits, use_deposits)
    cases: dict[tuple[str, str], dict] = {}
    for r in requests:
        g = group_of.get(r["agency_id"], r["agency_id"])  # 마스터 미등록은 단독 그룹
        c = cases.setdefault((g, r["pay_month"]), {"group_key": g, "pay_month": r["pay_month"], "requests": []})
        c["requests"].append(r)
    for c in cases.values():
        members = c["group_key"].split("+")
        c["paid"] = already_paid(history, members, c["pay_month"])
        c["total"] = sum(int(r["amount"]) for r in c["requests"]) + c["paid"]
        c["route"] = route_of(c["total"])
    return cases, group_of, evidence


def per_agency_routes(requests: list[dict]) -> dict[str, str]:
    """대조 A: 거래처별(관련자 합산 없이) 판정."""
    tot: dict[tuple[str, str], int] = {}
    for r in requests:
        k = (r["agency_id"], r["pay_month"])
        tot[k] = tot.get(k, 0) + int(r["amount"])
    return {f"{a}|{m}": route_of(t) for (a, m), t in sorted(tot.items())}


def observe_history(history: list[dict], group_key: str, months: list[str]) -> list[dict]:
    """과거 관찰. 정산월별 그룹 승인 지급 합계. 판정하지 않고 '관찰'로만 둔다."""
    members = group_key.split("+")
    out = []
    for m in months:
        rows = [h for h in history if h["agency_id"] in members and h["period_ym"] == m and h["status"] == "승인"]
        total = sum(int(h["amount"]) for h in rows)
        out.append({"period_ym": m, "total": total, "count": len(rows),
                    "approver": sorted({h["approver"] for h in rows}), "over_limit": total > LIMIT, "status": "관찰"})
    return out


# R6 승인 근거 스냅샷 ---------------------------------------------------
def basis_hash(basis: dict) -> str:
    return hashlib.sha256(json.dumps(basis, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def _flat(v, path="") -> dict:
    if isinstance(v, dict):
        return {k2: v2 for k, x in v.items() for k2, v2 in _flat(x, f"{path} > {k}" if path else k).items()}
    if isinstance(v, list) and v and isinstance(v[0], dict):
        return {k2: v2 for i, x in enumerate(v) for k2, v2 in _flat(x, f"{path}[{i + 1}]").items()}
    return {path: v}


def basis_diff(old: dict, new: dict) -> list[str]:
    """승인 당시 근거와 현재 근거의 달라진 항목."""
    a, b = _flat(old), _flat(new)
    return [f"{k}: {a.get(k, '(없음)')} -> {b.get(k, '(없음)')}" for k in sorted(set(a) | set(b)) if a.get(k) != b.get(k)]


# R8 회차와 마감 --------------------------------------------------------
def deadline_of(pay_month: str) -> datetime:
    """가정: 회차(지급월) 승인 마감은 그 달 3일 17:00."""
    return datetime(int(pay_month[:4]), int(pay_month[5:7]), 3, 17, 0)


def exec_day_of(pay_month: str) -> str:
    """가정: 지급 실행일은 그 달 6일."""
    return f"{pay_month}-06"
