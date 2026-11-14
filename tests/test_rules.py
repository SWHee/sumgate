"""TOPIC 8절 1~4번, 설계서 0절 경계값. 원본만 사용."""
from app import loader, rules

AG = {a["agency_id"]: a for a in loader.agencies()}
DP = loader.deposits()
RB = loader.rebates()
HIST = [r for r in RB if r["status"] != "미지급"]
PENDING = [dict(r, pay_month=rules.pay_month_of(r["period_ym"])[0]) for r in RB if r["status"] == "미지급"]
G = "D-011+D-024+D-037"


def test_c8_1_one_group_and_negative_control():
    group_of, _ = rules.find_groups(AG, DP, True)
    multi = {g for g in group_of.values() if "+" in g}
    assert multi == {G}
    assert group_of["D-034"] != group_of["D-041"]
    assert rules.pair_match(AG["D-034"], AG["D-041"], DP, True)[0] == ["대표자"]


def test_c8_2_deposit_toggle_changes_evidence_not_group():
    g_off, ev_off = rules.find_groups(AG, DP, False)
    g_on, ev_on = rules.find_groups(AG, DP, True)
    assert g_off["D-024"] == g_on["D-024"] == G
    assert ev_off[("D-024", "D-037")] == "전이 연결(경유: D-011)"
    assert ev_on[("D-024", "D-037")].startswith("직접 일치: 대표자 + 입금계좌")
    assert "DP-00013" in ev_on[("D-024", "D-037")] and "DP-00020" in ev_on[("D-024", "D-037")]
    assert ev_off[("D-024", "D-037")] != ev_on[("D-024", "D-037")]
    # 근거 문자열에 회수 입금계좌 번호를 적지 않는다
    assert "412-27-556310" not in ev_on[("D-024", "D-037")]


def test_c8_3_forty_requests_38_groups_one_escalation():
    assert len(PENDING) == 40 and {r["period_ym"] for r in PENDING} == {"2026-06"}
    cases, _, _ = rules.assess(PENDING, AG, DP, HIST)
    assert len(cases) == 38
    up = [c for c in cases.values() if c["route"] == rules.ROUTE_EXEC]
    assert len(up) == 1
    assert sorted((r["rebate_id"], r["amount"]) for r in up[0]["requests"]) == [
        ("RB-00054", 1373515), ("RB-00120", 1189046), ("RB-00180", 1325536)]
    assert up[0]["total"] == 3888097 and up[0]["paid"] == 0
    assert sum(c["route"] == rules.ROUTE_SUPPORT for c in cases.values()) == 37


def test_control_a_per_agency_gives_zero_escalation():
    assert rules.ROUTE_EXEC not in rules.per_agency_routes(PENDING).values()


def test_c8_4_history_observation():
    obs = rules.observe_history(HIST, G, ["2026-01", "2026-02", "2026-03", "2026-04", "2026-05"])
    assert [o["total"] for o in obs] == [4870186, 4540341, 4055114, 4267112, 4505596]
    assert sum(o["total"] for o in obs) == 22238349
    assert all(o["status"] == "관찰" and o["approver"] == ["영업지원팀"] for o in obs)


def test_boundary_2000000():
    assert rules.route_of(2_000_000) == rules.ROUTE_SUPPORT
    assert rules.route_of(2_000_001) == rules.ROUTE_EXEC


def test_pay_month_assumed_next_month():
    assert rules.pay_month_of("2026-06") == ("2026-07", "가정")
    assert rules.pay_month_of("2026-12") == ("2027-01", "가정")
    assert rules.pay_month_of("2026-06", "2026-08") == ("2026-08", "원본")


def test_none_preserved():
    assert {r["payment_date"] for r in RB if r["status"] != "승인"} == {"NONE"}
