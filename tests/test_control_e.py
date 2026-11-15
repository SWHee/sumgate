"""T6: 대조 E 채점. 필드별 일대일 대응, 값 일치 기준, 인용 검증 건수."""
from app import ai, scenarios as sc


def ext(**fields):
    return {"fields": {k: [{"value": v, "quote": v} for v in fields.get(k, [])] for k in ai.FIELDS},
            "dropped": []}


def test_one_extracted_item_fills_one_gold_item():
    gold = {"agencies": ["D-011", "D-024"], "claims": [{"text": "x", "keywords": ["공동", "계좌"]},
                                                       {"text": "y", "keywords": ["계좌"]}]}
    # 묶인 ID 값은 어느 정답도 못 채우고, 같은 ID 두 번은 정답 하나만 채운다
    r = ai.score(ext(agencies=["D-011, D-024", "D-011", "D 011"], claims=["공동 관리 계좌"]), gold)["필드"]
    assert r["agencies"] == {"정확": 1, "누락": 1, "오류": 2}
    assert r["claims"] == {"정확": 1, "누락": 1, "오류": 0}
    # 최대 대응: 탐욕적으로 첫 정답에 먼저 주면 1건이지만, 바꿔 짝지으면 2건
    r = ai.score(ext(claims=["계좌", "공동 계좌"]), gold)["필드"]["claims"]
    assert r == {"정확": 2, "누락": 0, "오류": 0}


def test_value_rules_by_field():
    assert ai.match("agencies", "D-011", " d‐011 ") and ai.match("agencies", "D-011", "D-011(본점)")
    assert not ai.match("agencies", "D-011", "D-0111") and not ai.match("agencies", "D-011", "금강상사11")
    for v in ("2026-03-01", "2026년 3월 1일", "2026.3.1", "적용일 2026/03/01부터"):
        assert ai.match("effective_dates", "2026-03-01", v), v
    assert not ai.match("effective_dates", "2026-03-01", "2026-03-01 ~ 2026-04-01")
    kw = {"text": "대표자가 같은 별도 법인", "keywords": ["대표자", "별도 법인"]}
    assert ai.match("claims", kw, "대표자 동일, 별도법인") and not ai.match("claims", kw, "별도 법인")


def test_citation_counts_and_total():
    text = "D-011 문서"
    v = ai.verify(text, {"agencies": [{"value": "D-011", "quote": "D-011"}, {"value": "D-024", "quote": "D-024"}]})
    sc_ = ai.score(v, {"agencies": ["D-011", "D-024"]})
    assert sc_["인용"] == {"원문 일치": 1, "근거 없음": 1}
    assert sc_["필드"]["agencies"] == {"정확": 1, "누락": 1, "오류": 0}  # 근거 없는 항목은 정확과 오류에 넣지 않는다
    t = ai.total([sc_, sc_])
    assert t["합계"] == {"정확": 2, "누락": 2, "오류": 0} and t["인용"]["근거 없음"] == 2


def test_fallback_scores_on_synthetic_docs():
    """대체 추출기 기준값. 정답이나 규칙을 바꾸면 여기서 드러난다."""
    t = ai.total(list(sc.control_e().values()))
    assert t["합계"] == {"정확": 16, "누락": 3, "오류": 3}
    assert t["인용"] == {"원문 일치": 19, "근거 없음": 0}
    for name, g in sc.gold_e().items():  # 정답 서술형 항목의 원문과 핵심어는 원문에 있다(합성 문서)
        text = sc.doc_text(name)
        for k in ai.TEXT_FIELDS:
            for it in g[k]:
                assert it["text"] in text and all(w in text for w in it["keywords"]), (name, it)
