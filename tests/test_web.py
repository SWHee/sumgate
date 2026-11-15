"""화면 버튼(HTTP)만으로 S1 그룹 흐름을 끝까지 진행할 수 있는지."""
import re

from fastapi.testclient import TestClient


def test_screens_and_s1_by_http(db_url, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", db_url)
    from app.main import app
    with TestClient(app) as cl:
        for p in ["/cases/1"]:  # 메뉴 화면은 test_menu_screens_show_title_and_content가 내용으로 검사
            assert cl.get(p).status_code == 200, p
        q = cl.get("/").text
        assert "모아봄 Moabom" in q and "실제 작동" in q and "미확인" in q
        gid = int(re.search(r'href="/cases/(\d+)">#\d+</a></td>\s*<td>D-011, D-024, D-037', q).group(1))
        assert "3,888,097" in q

        cl.get("/role?r=영업지원")
        cl.post("/bulk/approve-support")
        cl.get("/role?r=회계")
        assert "통과" in cl.post("/bulk/execute").text
        cl.get("/role?r=모의 외부")  # 모의 회신은 모의 외부 역할만(A1)
        tid = int(re.search(r'/tasks/(\d+)/account-reply', cl.get("/tasks").text).group(1))
        cl.post(f"/tasks/{tid}/account-reply", data={"valid": "1"})
        cl.get("/role?r=영업지원")
        cl.post(f"/cases/{gid}/submit")
        cl.get("/role?r=영업임원")
        cl.post(f"/cases/{gid}/approve")
        cl.get("/role?r=회계")
        cl.post(f"/cases/{gid}/execute")
        cl.get("/role?r=모의 외부")
        cl.post("/bank/all", data={"result": "성공"})
        page = cl.get(f"/cases/{gid}").text
        assert "지급 완료" in page and "하나 233-91-004417" in page
        acct = page.split("<h2>지급계좌")[1].split("</section>")[0]
        d024_row = acct.split("<td>D-024</td>")[1].split("</tr>")[0]
        assert "하나 233-91-004417" in d024_row and "412-27-556310" not in d024_row  # 회수 입금계좌를 지급계좌로 표시하지 않음
        assert "지급 완료" in cl.get("/").text and "확인 필요" not in cl.get("/").text


def _role(cl, r):
    cl.get(f"/role?r={r}")


def _group_id(cl):
    q = cl.get("/").text
    return int(re.search(r'href="/cases/(\d+)">#\d+</a></td>\s*<td>D-011, D-024, D-037', q).group(1))


def _to_exec_approval(cl, gid):
    _role(cl, "모의 외부")
    tid = int(re.search(r'/tasks/(\d+)/account-reply', cl.get("/tasks").text).group(1))
    cl.post(f"/tasks/{tid}/account-reply", data={"valid": "1"})
    _role(cl, "영업지원")
    cl.post(f"/cases/{gid}/submit")
    _role(cl, "영업임원")


def test_s3_by_buttons(db_url, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", db_url)
    from app.main import app
    with TestClient(app) as cl:
        gid = _group_id(cl)
        _role(cl, "영업지원")
        cl.post("/bulk/approve-support")
        _role(cl, "회계")
        cl.post("/bulk/execute")
        _role(cl, "모의 외부")
        cl.post("/bank/all", data={"result": "성공"})
        _to_exec_approval(cl, gid)
        assert "거절했습니다" in cl.post(f"/cases/{gid}/reject", data={"reason": "공유 계좌 소명 없음"}).text
        _role(cl, "모의 외부")
        assert "가상 시각을 옮겼습니다" in cl.post("/mock/clock", data={"ts": "2026-07-03 17:00"}).text
        page = cl.get(f"/cases/{gid}").text
        assert "2026-08" in page and "거절됨" in page and "대리점 안내" in page and "회차 목록 재생성" in page
        text = cl.get("/mock?sample=EXP-01_D-011.txt").text
        doc_text = re.search(r'<textarea name="text" rows="8" required>(.*?)</textarea>', text, re.S).group(1)
        r = cl.post("/mock/doc", data={"kind": "소명 회신", "agency_id": "D-011", "text": doc_text, "case_id": str(gid)})
        did = int(re.search(r"/papers/(\d+)", str(r.url)).group(1))
        _role(cl, "영업지원")
        cl.post(f"/papers/{did}/confirm")
        assert "상위 승인 필요" in cl.get(f"/cases/{gid}").text
        cl.post(f"/cases/{gid}/submit")
        _role(cl, "모의 외부")
        cl.post("/mock/clock", data={"ts": "2026-08-01 10:00"})
        cl.post("/mock/request", data={"rebate_id": "SYN-RB-0001", "agency_id": "D-037", "period_ym": "2026-07",
                                       "amount": "612400", "reason": "합성"})
        page = cl.get(f"/cases/{gid}").text
        assert "4,500,497" in page and "상위 승인 필요" in page
        _role(cl, "영업지원")
        cl.post(f"/cases/{gid}/submit")
        _role(cl, "영업임원")
        cl.post(f"/cases/{gid}/approve")
        _role(cl, "회계")
        assert "재검증 통과" in cl.post(f"/cases/{gid}/execute").text
        _role(cl, "모의 외부")
        tids = [int(x) for x in re.findall(r'/tasks/(\d+)/bank"', cl.get("/tasks").text)]
        cl.post(f"/tasks/{tids[0]}/bank", data={"result": "반려"})
        assert "지급 반려(재처리)" in cl.get(f"/cases/{gid}").text
        _role(cl, "회계")
        rid = int(re.search(r'/tasks/(\d+)/retry', cl.get("/tasks").text).group(1))
        cl.post(f"/tasks/{rid}/retry")
        _role(cl, "모의 외부")
        cl.post("/bank/all", data={"result": "성공"})
        assert '<th>상태</th><td class="st">지급 완료' in cl.get(f"/cases/{gid}").text


def test_s2_by_buttons(db_url, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", db_url)
    from app.main import app
    with TestClient(app) as cl:
        gid = _group_id(cl)
        _to_exec_approval(cl, gid)
        cl.post(f"/cases/{gid}/approve")
        _role(cl, "모의 외부")
        text = cl.get("/mock?sample=COR-01_D-024.txt").text
        doc_text = re.search(r'<textarea name="text" rows="8" required>(.*?)</textarea>', text, re.S).group(1)
        r = cl.post("/mock/doc", data={"kind": "정정 신고", "agency_id": "D-024", "text": doc_text})
        did = int(re.search(r"/papers/(\d+)", str(r.url)).group(1))
        _role(cl, "영업지원")
        assert 'value="성남시 판교로 45"' in cl.get(f"/papers/{did}").text
        cl.post(f"/papers/{did}/confirm", data={"agency_id": "D-024", "field": "주소", "value": "성남시 판교로 45"})
        _role(cl, "회계")
        assert "재검증 차단" in cl.post(f"/cases/{gid}/execute").text
        assert "주소: 성남시 상공로 128 -&gt; 성남시 판교로 45" in cl.get(f"/cases/{gid}").text
        _role(cl, "영업지원")
        cl.post(f"/cases/{gid}/submit")
        _role(cl, "영업임원")
        cl.post(f"/cases/{gid}/approve")
        _role(cl, "모의 외부")
        cl.post("/mock/amount", data={"rebate_id": "RB-00180", "amount": "1300000", "reason": "합성 정정"})
        _role(cl, "회계")
        assert "재검증 차단" in cl.post(f"/cases/{gid}/execute").text
        assert "차단(승인 무효, 재상신)" in cl.get("/controls").text


# 상단 메뉴 주소를 열면 그 화면의 제목과 핵심 내용이 나와야 한다(상태 코드만 보면 /docs가 Swagger를 열어도 통과했다)
MENU = {
    "대기열": ("대기열", "승인 사건 대기열"),
    "작업함": ("작업함", "작업 목록"),
    "모의 입력": ("모의 입력", "대리점 회신 문서"),
    "문서": ("문서", "문서 목록"),
    "대조와 과거 관찰": ("대조", "대조 A"),
    "이력": ("이력", "처리 이력"),
    "시나리오 실행과 초기화": ("시나리오", "시나리오 실행과 초기화"),
}


def test_menu_screens_show_title_and_content(db_url, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", db_url)
    from app.main import app
    with TestClient(app) as cl:
        nav = cl.get("/").text.split("<nav>")[1].split("</nav>")[0]
        links = dict((t, h) for h, t in re.findall(r'<a href="([^"]+)">([^<]+)</a>', nav))
        assert set(links) == set(MENU)
        for label, (title, body) in MENU.items():
            html = cl.get(links[label]).text
            assert f"<title>모아봄 {title}</title>" in html, label
            assert body in html and "Swagger" not in html, label
        # 업무 문서 목록은 /papers, FastAPI 기본 문서 경로는 꺼져 있다
        assert links["문서"] == "/papers"
        for p in ["/docs", "/redoc", "/openapi.json"]:
            assert cl.get(p).status_code == 404, p


def test_footer_shows_release_and_schema(db_url, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", db_url)
    from app.main import app
    from app.models import SCHEMA
    with TestClient(app) as cl:
        for p in ("/", "/controls", "/tasks"):
            assert f'<footer class="muted">v1.1 2026-11-15, 스키마 {SCHEMA[:8]}</footer>' in cl.get(p).text
