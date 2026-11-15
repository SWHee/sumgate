"""T4: 막힌 이유, 다음 담당자, 다음 행동이 사건 상태와 열린 작업에서 도출되고 화면 맨 위에 보이는지."""
import re

from fastapi.testclient import TestClient
from sqlalchemy import select

from app import scenarios, service as sv
from app.models import Doc, Task


def step(s):
    c = scenarios.group_case(s)
    return sv.next_step(c, list(s.scalars(select(Task))), list(s.scalars(select(Doc).where(Doc.status == "확인 대기"))))


def test_s1_next_step_changes_each_stage(s):
    n = step(s)
    assert (n["reason"], n["role"], n["action"]) == (
        "D-024 지급계좌 확인 회신 대기", "모의 외부", "모의 외부 역할로 지급계좌 확인 회신")
    gid = scenarios.group_case(s).id
    sv.account_reply(s, scenarios.open_task(s, "지급계좌 확인", gid).id, True)
    assert (step(s)["reason"], step(s)["role"]) == ("영업임원 상신 전", "영업지원")
    sv.submit(s, gid, use_ai=False)
    assert (step(s)["reason"], step(s)["action"]) == ("영업임원 승인 대기", "영업임원 역할로 승인 또는 거절")
    sv.approve(s, gid, "영업임원")
    assert (step(s)["reason"], step(s)["role"]) == ("지급 실행 요청 전", "회계")
    assert sv.execute(s, gid)
    assert (step(s)["reason"], step(s)["action"]) == ("은행 회신 대기", "모의 외부 역할로 은행 회신")
    sv.bank_reply_all(s, "성공")
    assert step(s) | {"where": ""} == {"reason": "지급 완료", "role": "", "action": "", "where": ""}


def test_s3_next_step_after_reject_and_cycle_move(s):
    c = scenarios.prepare_group_for_exec(s)
    sv.reject(s, c.id, "공유 계좌 소명 없음")
    assert (step(s)["reason"], step(s)["action"]) == ("영업임원 거절, 소명 회신 대기", "모의 외부 역할로 소명 회신 입력")
    sv.advance_clock(s, "2026-07-03 17:00")
    c = scenarios.group_case(s)
    assert c.pay_month == "2026-08" and step(s)["role"] == "모의 외부"  # 대리점 안내 작업은 막힌 이유에 쓰지 않음
    d = sv.receive_doc(s, "소명 회신", "D-011", scenarios.doc_text("EXP-01_D-011.txt"), case_id=c.id, use_ai=False)
    assert step(s) == {"reason": "소명 확인 전", "role": "영업지원", "action": "영업지원 역할로 문서에서 소명 확인",
                       "where": f"/papers/{d}"}
    sv.confirm_doc(s, d)
    assert (step(s)["reason"], step(s)["role"]) == ("영업임원 상신 전", "영업지원")


def test_queue_action_section_and_role_hint(db_url, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", db_url)
    from app.main import app
    with TestClient(app) as cl:
        q = cl.get("/").text
        top = q.split("<h2>승인 사건 대기열: 조치가 필요한 사건")[1].split("</section>")[0]
        assert "D-011, D-024, D-037" in top and "3,888,097" in top
        assert "D-024 지급계좌 확인 회신 대기" in top and "모의 외부 역할로 지급계좌 확인 회신" in top
        assert top.count('href="/cases/') == 1  # 조치 구역에는 그룹 사건 하나뿐(다음 행동 링크는 /tasks)
        assert "전결 승인 대기 37건" in q and '<details id="bulk">' in q
        assert "1. 영업지원: 전결 일괄 승인 (지금 할 단계)" in q and 'href="/scenarios"' in q
        gid = int(re.search(r'href="/cases/(\d+)">#\d+</a></td>\s*<td>D-011, D-024, D-037', top).group(1))

        cl.get("/role?r=영업지원")
        cl.post("/bulk/approve-support")
        assert "2. 모의 외부: 지급계좌 확인 회신 (지금 할 단계)" in cl.get("/").text

        page = cl.get(f"/cases/{gid}").text  # 영업지원으로 보면 역할 전환 안내
        assert "이 단계는 모의 외부 역할이 합니다. 상단에서 역할을 바꾸세요" in page and 'href="/role?r=모의 외부"' in page
        assert page.index("막힌 이유") < page.index("<h2>관계 근거")
        cl.get("/role?r=모의 외부")
        page = cl.get(f"/cases/{gid}").text
        assert "이 단계는" not in page and '<a href="/tasks">이 화면에서 처리하기</a>' in page
