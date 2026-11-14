"""T2: OpenRouter 경로, AI 출력 -> 사람 확인(채택, 수정, 기각) -> 후속 업무 변화. HTTP는 모두 모킹한다."""
import json
import re

import httpx2
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import ai, rules, scenarios as sc, service as sv
from app.models import Doc, EventLog, Task

KEY = "sk-or-v1-test-not-a-real-key"
TEXT = "D-011은 2026-07-01부터 사업장을 이전했습니다. 임대차 계약서를 첨부합니다. 대표자 변경은 아직 확인 중입니다."
GOOD = {"claims": [{"value": "D-011 사업장 이전", "quote": "D-011은 2026-07-01부터 사업장을 이전했습니다."}],
        "evidence": [{"value": "임대차 계약서", "quote": "임대차 계약서를 첨부합니다."}],
        "effective_dates": [{"value": "2026-07-01", "quote": "2026-07-01"}],
        "agencies": [{"value": "D-011", "quote": "D-011"}],
        "unknowns": [{"value": "대표자 변경", "quote": "대표자 변경은 아직 확인 중입니다."}]}


def _resp(status=200, content=None, body=None):
    if body is None:
        body = {"choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": content}}]}
    return httpx2.Response(status, json=body, request=httpx2.Request("POST", ai.OR_URL))


@pytest.fixture
def orouter(monkeypatch):
    """OpenRouter 키를 넣고 httpx2.post를 가로챈다. calls에 요청이 쌓이고, reply로 응답을 바꾼다."""
    monkeypatch.setenv("OPENROUTER_API_KEY", KEY)
    st = {"calls": [], "reply": lambda: _resp(content=json.dumps(GOOD, ensure_ascii=False))}

    def fake_post(url, json=None, headers=None, timeout=None):
        st["calls"].append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        return st["reply"]()
    monkeypatch.setattr(ai.httpx2, "post", fake_post)
    return st


def gcase(s):
    return sc.group_case(s)


# 경로 선택 ---------------------------------------------------------------
@pytest.mark.parametrize("env,want", [
    ({}, (None, "키 미등록: 대체 추출")),
    ({"OPENROUTER_API_KEY": KEY}, ("openrouter", f"OpenRouter({ai.OR_MODEL})")),
    ({"ANTHROPIC_API_KEY": KEY}, ("openrouter", f"OpenRouter({ai.OR_MODEL})")),  # 이름이 잘못된 OpenRouter 키
    ({"ANTHROPIC_API_KEY": "anthropic-test-not-a-key"}, ("anthropic", f"Anthropic({ai.MODEL})")),
    ({"ANTHROPIC_API_KEY": "anthropic-test-not-a-key", "OPENROUTER_API_KEY": KEY}, ("openrouter", f"OpenRouter({ai.OR_MODEL})")),
])
def test_route_and_status(monkeypatch, env, want):
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    assert (ai.route()[0], ai.status()) == want
    assert "sk-" not in ai.status()


# 추출 -----------------------------------------------------------------
def test_openrouter_extract_ok(orouter):
    ext = ai.extract(TEXT)
    assert ext["extractor"] == ai.OR_LABEL and isinstance(ext["ms"], int)
    assert sum(len(v) for v in ext["fields"].values()) == 5 and ext["dropped"] == []
    c = orouter["calls"][0]
    assert c["url"] == "https://openrouter.ai/api/v1/chat/completions" and c["timeout"] == ai.TIMEOUT
    assert c["headers"]["Authorization"] == f"Bearer {KEY}"
    body = c["json"]
    assert body["model"] == "anthropic/claude-haiku-5.5"
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["strict"] is True
    assert body["provider"] == {"require_parameters": True}


@pytest.mark.parametrize("reply,why", [
    (lambda: (_ for _ in ()).throw(httpx2.ReadTimeout("t")), "시간 초과"),
    (lambda: _resp(401, body={"error": {"code": 401, "message": "SECRET-BODY No auth credentials found"}}), "HTTP 401"),
    (lambda: _resp(content="{이건 JSON이 아님"), "응답 형식 오류"),
    (lambda: _resp(content=json.dumps({"claims": []})), "응답 형식 오류"),  # 스키마 불일치
    (lambda: _resp(body={"error": {"code": 502, "message": "SECRET-BODY"}}), "응답 오류"),  # 200 본문 오류
])
def test_openrouter_failures_fall_back(orouter, reply, why):
    orouter["reply"] = reply
    ext = ai.extract(TEXT)
    assert ext["extractor"] == f"{ai.FALLBACK_LABEL}, AI 호출 실패 {why}"
    assert "SECRET" not in json.dumps(ext, ensure_ascii=False) and KEY not in json.dumps(ext)
    assert ext["fields"]["agencies"]  # 대체 추출 결과가 들어 있다


def test_openrouter_unquoted_dropped(orouter):
    bad = dict(GOOD, claims=GOOD["claims"] + [{"value": "관계 없음", "quote": "세 회사는 관계가 없습니다"}])
    orouter["reply"] = lambda: _resp(content=json.dumps(bad, ensure_ascii=False))
    ext = ai.extract(TEXT)
    assert ext["extractor"] == ai.OR_LABEL
    assert [d["quote"] for d in ext["dropped"]] == ["세 회사는 관계가 없습니다"]


def test_labels_fit_db_columns():
    # Doc.extractor는 String(50). Postgres에서는 넘으면 커밋이 실패한다
    for lb in [ai.OR_LABEL, ai.AI_LABEL, f"{ai.FALLBACK_LABEL}, AI 호출 실패 응답 중단(content_filter)",
               "AI 미사용(대체 작성), AI 서술 금지 표현(" + ai.FORBIDDEN[0] + ")"]:
        assert len(lb) <= 50, lb


# 상신 초안 -------------------------------------------------------------
FACTS = {"members": ["D-011", "D-024"], "evidence": {}, "pay_month": "2026-07", "requests": [], "total": 3888097,
         "route": rules.ROUTE_EXEC}


def test_draft_openrouter_ok(orouter):
    orouter["reply"] = lambda: _resp(content="관련자 그룹의 합계는 3,888,097원입니다. 승인 여부는 영업임원이 결정합니다.")
    txt, label = ai.draft(FACTS)
    assert label == ai.OR_LABEL and "3,888,097" in txt
    assert "response_format" not in orouter["calls"][0]["json"]


@pytest.mark.parametrize("w", ai.FORBIDDEN)
def test_draft_forbidden_word_replaced(orouter, w):
    orouter["reply"] = lambda: _resp(content=f"이 그룹은 {w} 정황이 있습니다.")
    txt, label = ai.draft(FACTS)
    assert w not in txt and label == f"AI 미사용(대체 작성), AI 서술 금지 표현({w})"


# 접수 이력, 사람 확인, 후속 변화 ----------------------------------------
def test_receive_doc_logs_extractor_time_and_quotes(s, orouter):
    did = sv.receive_doc(s, "소명 회신", "D-011", TEXT, case_id=gcase(s).id)
    ev = s.scalars(select(EventLog).where(EventLog.ref == f"문서 {did}", EventLog.action == "문서 구조화")).one()
    assert ev.actor_type == "AI"
    assert re.fullmatch(rf"추출 주체 {re.escape(ai.OR_LABEL)}, 소요 \d+ms, 인용 검증 통과 5건, 근거 없음으로 버림 0건",
                        ev.detail)


def _rejected_group(s):
    c = gcase(s)
    t = [t for t in s.scalars(select(Task).where(Task.type == "지급계좌 확인"))][0]
    sv.account_reply(s, t.id, True)
    sv.submit(s, c.id, use_ai=False)
    sv.reject(s, c.id, "소명 필요")
    assert gcase(s).status == "거절됨"
    return gcase(s)


def test_review_adopt_edit_reject_and_effects(s, orouter):
    c = _rejected_group(s)
    did = sv.receive_doc(s, "소명 회신", "D-011", TEXT, case_id=c.id)
    assert gcase(s).status == "거절됨"  # 확인 전에는 판정에 쓰이지 않는다
    sv.confirm_doc(s, did, decisions={"claims:0": ("수정", "D-011 사업장 이전(2026-07-01)"),
                                      "unknowns:0": ("기각", ""), "evidence:0": ("채택", "무시됨")})
    ext = json.loads(s.get(Doc, did).extraction_json)
    assert ext["review"]["채택"] == 3 and ext["review"]["수정"] == 1 and ext["review"]["기각"] == 1
    assert ext["confirmed"]["unknowns"] == []
    assert ext["confirmed"]["claims"][0]["value"] == "D-011 사업장 이전(2026-07-01)"
    assert ext["confirmed"]["evidence"][0]["value"] == "임대차 계약서"  # 채택은 AI 값 그대로
    assert ext["fields"]["claims"][0]["value"] == "D-011 사업장 이전"  # AI 제안 원본은 남는다
    ev = s.scalars(select(EventLog).where(EventLog.action == "AI 제안 검토")).one()
    assert ev.detail.splitlines() == [
        f"추출 주체 {ai.OR_LABEL}. 채택 3, 수정 1, 기각 1",
        "주장 수정: D-011 사업장 이전 -> D-011 사업장 이전(2026-07-01)",
        "미확인 항목 기각: 대표자 변경"]
    # 후속 변화: 거절된 사건이 재상신 가능 상태로
    assert gcase(s).status == "상위 승인 필요"
    assert f"사건 #{c.id} 거절됨 -> 상위 승인 필요 재상신 가능" in ext["effects"]
    case_ev = s.scalars(select(EventLog).where(EventLog.ref == f"사건 {c.id}", EventLog.action == "문서 확인 결과")).one()
    assert f"문서 {did} 확인" in case_ev.detail and "재상신 가능" in case_ev.detail


def test_review_rejects_empty_edit(s):
    did = sv.receive_doc(s, "소명 회신", "D-011", TEXT, case_id=gcase(s).id, use_ai=False)
    with pytest.raises(ValueError):
        sv.confirm_doc(s, did, decisions={"agencies:0": ("수정", " ")})


def test_correction_effects_master_version_and_basis(s):
    c = gcase(s)
    did = sv.receive_doc(s, "정정 신고", "D-024", sc.doc_text("COR-01_D-024.txt"), case_id=c.id, use_ai=False)
    sv.confirm_doc(s, did, correction={"agency_id": "D-024", "field": "주소", "value": "성남시 판교로 45"})
    eff = json.loads(s.get(Doc, did).extraction_json)["effects"]
    assert eff[0] == "마스터 D-024 v2 생성(주소)"
    assert any(e.startswith(f"사건 #{c.id}") for e in eff)


def test_web_review_flow_and_ai_status(db_url, monkeypatch, orouter):
    monkeypatch.setenv("DATABASE_URL", db_url)
    from app.main import app
    with TestClient(app) as cl:
        home = cl.get("/").text
        assert f"AI 경로 <b>OpenRouter({ai.OR_MODEL})</b>" in home and KEY not in home
        assert f"현재 AI 경로: <b>OpenRouter({ai.OR_MODEL})</b>" in cl.get("/controls").text
        cl.get("/role?r=모의 외부")
        r = cl.post("/mock/doc", data={"kind": "소명 회신", "agency_id": "D-011", "text": TEXT, "case_id": "1"},
                    follow_redirects=False)
        did = int(r.headers["location"].rsplit("/", 1)[1])
        cl.get("/role?r=영업지원")
        page = cl.get(f"/papers/{did}").text
        assert ai.OR_LABEL in page and "인용 검증 통과 5건" in page
        assert 'name="d_claims_0"' in page and 'name="v_unknowns_0"' in page
        form = {f"d_{k}_0": "채택" for k in ai.FIELDS} | {f"v_{k}_0": GOOD[k][0]["value"] for k in ai.FIELDS}
        form |= {"d_agencies_0": "수정", "v_agencies_0": "D-011(본점)", "d_unknowns_0": "기각"}
        cl.post(f"/papers/{did}/confirm", data=form)
        page = cl.get(f"/papers/{did}").text
        assert "채택 3, 수정 1, 기각 1" in page and "대상 거래처 수정: D-011 -&gt; D-011(본점)" in page
        assert "이 문서 확인으로 바뀐 것:" in page
        assert "AI 제안 검토" in cl.get("/log").text
        assert "최근 문서 확인으로 바뀐 것:" in cl.get("/cases/1").text


def test_control_e_via_openrouter(db_url, monkeypatch, orouter):
    monkeypatch.setenv("DATABASE_URL", db_url)
    from app.main import app
    with TestClient(app) as cl:
        cl.get("/")
        cl.post("/controls/e/ai")
        assert len(orouter["calls"]) == 3
        assert ai.OR_LABEL in cl.get("/controls").text


def test_scenarios_never_call_ai(s, orouter):
    sc.s2(s)  # 정정 문서 접수와 상신이 들어 있다
    assert orouter["calls"] == []
