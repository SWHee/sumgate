"""T3: 방문자별 작업 공간. 견본(초기 상태)은 어떤 요청으로도 바뀌지 않고, 방문자의 변경은 자기 공간에만 반영된다."""
import time

from fastapi.testclient import TestClient
from sqlalchemy import func, select, update

from app import scenarios
from app import service as sv
from app import workspace
from app.models import Approval, Case


def _app(db_url, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", db_url)
    import app.main as m
    return m


def _approvals(m, ws=None) -> int:
    with m.SPACES.sm(ws)() as s:
        return s.scalar(select(func.count()).select_from(Approval))


def _fresh_home(m) -> str:
    return TestClient(m.app).get("/").text  # 쿠키 없는 새 방문자


def test_visitor_a_changes_do_not_reach_b_or_cookieless(db_url, monkeypatch):
    m = _app(db_url, monkeypatch)
    with TestClient(m.app) as a:
        base = _fresh_home(m)
        assert "견본(초기 상태, 읽기 전용)" in base and "역할 전환은 시연용이며 인증이 아닙니다" in base
        b = TestClient(m.app)
        b_home = b.get("/").text
        assert b_home == base

        a.get("/")
        assert "전결 사건 37건 승인" in a.post("/bulk/approve-support").text
        ws_a = a.cookies.get("ws")
        assert ws_a and f"내 작업 공간 {ws_a[:8]}" in a.get("/").text
        assert _approvals(m, ws_a) == 37
        assert b.get("/").text == base and _fresh_home(m) == base and _approvals(m) == 0

        a.post("/scenarios/run", data={"name": "S1"})
        assert "S1" in a.get("/scenarios").text
        assert b.get("/").text == base and _fresh_home(m) == base
        a.post("/scenarios/reset")
        assert _approvals(m, ws_a) == 0
        assert b.get("/").text == base and _fresh_home(m) == base

        # B가 자기 공간에서 승인해도 A가 방금 초기화한 공간과 섞이지 않는다
        assert "전결 사건 37건 승인" in b.post("/bulk/approve-support").text
        assert b.cookies.get("ws") not in (None, ws_a)
        assert _approvals(m, ws_a) == 0 and _approvals(m) == 0
        assert m.SPACES.names() == sorted(["template", ws_a, b.cookies.get("ws")])


def test_get_only_creates_no_workspace_and_first_post_lands_in_new_one(db_url, monkeypatch):
    m = _app(db_url, monkeypatch)
    with TestClient(m.app) as cl:
        paths = ["/", "/tasks", "/mock", "/papers", "/controls", "/log", "/scenarios", "/cases/1", "/role?r=회계"]
        for i in range(100):
            assert cl.get(paths[i % len(paths)]).status_code == 200
        assert m.SPACES.names() == ["template"] and cl.cookies.get("ws") is None
        assert TestClient(m.app).post("/bulk/execute").status_code == 403  # 쿠키 없는 POST도 공간을 만들지 않는다
        assert m.SPACES.names() == ["template"]

        cl.get("/role?r=영업지원")
        assert "전결 사건 37건 승인" in cl.post("/bulk/approve-support").text
        ws = cl.cookies.get("ws")
        assert m.SPACES.names() == sorted(["template", ws])
        assert _approvals(m, ws) == 37 and _approvals(m) == 0
        cl.post("/bulk/approve-support")
        assert m.SPACES.names() == sorted(["template", ws])  # 두 번째 POST는 같은 공간


FORGED = ["../../etc/passwd", "'; DROP SCHEMA public CASCADE; --", "0" * 32, "A" * 32, "template", "ws_template",
          "a" * 33, ""]


def test_forged_workspace_cookie_falls_back_to_template(db_url, monkeypatch):
    m = _app(db_url, monkeypatch)
    with TestClient(m.app) as cl:
        base = _fresh_home(m)
        for v in FORGED:
            cl.cookies.set("ws", v, domain="testserver.local")
            r = cl.get("/")
            assert r.status_code == 200 and r.text == base, v
            assert m.SPACES.names() == ["template"], v
        # 상태를 바꾸는 요청이면 쿠키 값과 무관한 새 무작위 ID로 공간을 만든다
        cl.cookies.set("ws", "'; DROP SCHEMA public CASCADE; --", domain="testserver.local")
        cl.get("/role?r=영업지원")
        cl.post("/bulk/approve-support")
        new = [n for n in m.SPACES.names() if n != "template"]
        assert len(new) == 1 and workspace.ID.fullmatch(new[0]) and cl.cookies.get("ws") == new[0]
        assert _approvals(m) == 0 and _fresh_home(m) == base


def test_settings_switches_gone_and_controls_b_d_are_computed(db_url, monkeypatch):
    m = _app(db_url, monkeypatch)
    with TestClient(m.app) as cl:
        cl.get("/role?r=영업지원")
        for p in ["/settings/revalidate", "/settings/deposits"]:
            assert cl.post(p, data={"on": "0"}).status_code in (404, 405), p
        cl.post("/scenarios/reset")
        ws = cl.cookies.get("ws")
        with m.SPACES.sm(ws)() as s:  # 임원 승인 뒤 금액 정정: 실행 전이라 아직 상태는 승인됨
            c = scenarios.prepare_group_for_exec(s)
            sv.approve(s, c.id, "영업임원")
            sv.correct_amount(s, "RB-00054", 1373516, "테스트", "test")
            gid = c.id
        html = cl.get("/controls").text
        assert "D-011~D-024" in html.split("대조 B")[1]  # 대조 B: 끔과 켬의 근거를 계산으로 비교
        d = html.split("대조 D")[1].split("대조 E")[0]
        assert f"#{gid}" in d and "옛 근거로 지급 작업" in d and "차단(승인 무효, 재상신)" in d
        assert "/settings/" not in html and "항상 켜져" in d
        with m.SPACES.sm(ws)() as s:
            assert s.get(Case, gid).status == "승인됨"  # 계산만 했고 상태는 그대로
        cl.get("/role?r=회계")
        assert "재검증 차단" in cl.post(f"/cases/{gid}/execute").text


def test_cleanup_by_age_and_cap(db_url, monkeypatch):
    m = _app(db_url, monkeypatch)
    monkeypatch.setattr(workspace, "CAP", 2)
    with TestClient(m.app):
        ids = []
        for _ in range(3):
            v = TestClient(m.app)
            v.get("/")
            v.post("/bulk/approve-support")
            ids.append(v.cookies.get("ws"))
            time.sleep(0.01)
        assert m.SPACES.names() == sorted(["template", ids[1], ids[2]])  # 상한을 넘으면 가장 오래된 것부터
        old = TestClient(m.app, cookies={"ws": ids[0]}).get("/").text
        assert "견본(초기 상태, 읽기 전용)" in old

        with m.SPACES.engine.begin() as c:  # ids[1]을 7일 넘게 쓰지 않은 것으로 만든다
            c.execute(update(workspace.registry).where(workspace.registry.c.id == ids[1])
                      .values(last_used=time.time() - workspace.TTL - 1))
        v = TestClient(m.app)
        v.get("/")
        v.post("/bulk/approve-support")
        assert m.SPACES.names() == sorted(["template", ids[2], v.cookies.get("ws")])


def test_workspace_survives_restart(db_url, monkeypatch):
    m = _app(db_url, monkeypatch)
    with TestClient(m.app) as cl:
        cl.get("/")
        cl.post("/bulk/approve-support")
        ws, role = cl.cookies.get("ws"), cl.cookies.get("role")
    with TestClient(m.app, cookies={"ws": ws, "role": role}) as cl:  # lifespan이 다시 돈다(재시작)
        assert f"내 작업 공간 {ws[:8]}" in cl.get("/").text
        assert _approvals(m, ws) == 37 and _approvals(m) == 0
