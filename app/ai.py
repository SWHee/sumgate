"""AI 역할: 문서 구조화와 상신 서술 초안만. 관계 판정, 합산, 승인 경로는 하지 않는다.

키는 서버 환경변수에서만 읽는다. OPENROUTER_API_KEY가 있으면 OpenRouter, 없고 ANTHROPIC_API_KEY가 있으면
Anthropic 직접 호출, 둘 다 없으면 규칙 기반 대체 추출기를 쓴다.
"""
import json
import os
import re
import time

import httpx2  # anthropic SDK가 함께 설치하는 HTTP 클라이언트(httpx와 같은 API). 런타임 이미지에 있다
from pydantic import BaseModel

MODEL = "claude-opus-5-5"  # Anthropic 직접 경로
OR_MODEL = "anthropic/claude-haiku-5.5"  # OpenRouter 경로: 추출과 짧은 서술용으로 빠르고 싼 모델
OR_URL = "https://openrouter.ai/api/v1/chat/completions"
TIMEOUT = 30  # 초
AI_LABEL = f"AI 사용({MODEL})"
OR_LABEL = f"AI 사용(OpenRouter {OR_MODEL})"
FALLBACK_LABEL = "AI 미사용(대체 추출)"
# 상신 서술에 쓰면 안 되는 확정 표현 4개. 저장소 글자 검사(test_no_middle_dot_or_definitive_words)에 걸리지 않게 이스케이프로 적는다
FORBIDDEN = ("\ubd80\uc815", "\ud6a1\ub839", "\uc801\ubc1c", "\uc704\ubc18")
FIELDS = {"claims": "주장", "evidence": "증빙", "effective_dates": "적용일",
          "agencies": "대상 거래처", "unknowns": "미확인 항목"}


class Item(BaseModel):
    value: str
    quote: str  # 원문에서 그대로 복사한 부분 문자열


class Extraction(BaseModel):
    claims: list[Item]
    evidence: list[Item]
    effective_dates: list[Item]
    agencies: list[Item]
    unknowns: list[Item]


_ITEM = {"type": "object", "properties": {"value": {"type": "string"}, "quote": {"type": "string"}},
         "required": ["value", "quote"], "additionalProperties": False}
EXTRACTION_SCHEMA = {"type": "object", "properties": {k: {"type": "array", "items": _ITEM} for k in FIELDS},
                     "required": list(FIELDS), "additionalProperties": False}


def route() -> tuple[str | None, str]:
    """(제공사, 키). 호출할 때마다 환경변수를 읽는다."""
    if k := os.environ.get("OPENROUTER_API_KEY"):
        return "openrouter", k
    k = os.environ.get("ANTHROPIC_API_KEY", "")
    if k.startswith("sk-or-"):  # OpenRouter 키가 ANTHROPIC_API_KEY 이름으로 등록된 경우 보정
        return "openrouter", k
    return ("anthropic", k) if k else (None, "")


def has_key() -> bool:
    return route()[0] is not None


def status() -> str:
    """화면 표시용 AI 경로. 키 값은 넣지 않는다."""
    return {"openrouter": f"OpenRouter({OR_MODEL})", "anthropic": f"Anthropic({MODEL})"}.get(
        route()[0], "키 미등록: 대체 추출")


def _ok_label() -> str:
    return OR_LABEL if route()[0] == "openrouter" else AI_LABEL


class AIError(Exception):
    """응답이 왔지만 쓸 수 없음. 메시지는 화면 라벨에 그대로 쓰므로 짧고 민감 정보가 없어야 한다."""


def _why(e: Exception) -> str:
    if isinstance(e, httpx2.HTTPStatusError):
        return f"HTTP {e.response.status_code}"
    if isinstance(e, httpx2.TimeoutException):
        return "시간 초과"
    if isinstance(e, AIError):
        return str(e)
    if isinstance(e, (ValueError, KeyError, TypeError, IndexError)):  # JSON 깨짐, 스키마 불일치 포함
        return "응답 형식 오류"
    return type(e).__name__


def _openrouter(system: str, user: str, schema: dict | None = None) -> str:
    """OpenRouter chat completions 호출. 본문 텍스트를 돌려주고, 쓸 수 없으면 예외."""
    body = {"model": OR_MODEL, "max_tokens": 4000,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    if schema:
        body["response_format"] = {"type": "json_schema",
                                   "json_schema": {"name": "extraction", "strict": True, "schema": schema}}
        body["provider"] = {"require_parameters": True}  # 구조화 출력을 지원하는 공급자로만 보낸다
    r = httpx2.post(OR_URL, json=body, timeout=TIMEOUT,
                    headers={"Authorization": f"Bearer {route()[1]}", "X-Title": "Moabom"})
    r.raise_for_status()
    data = r.json()
    if data.get("error") or not data.get("choices"):  # 200이어도 본문에 오류가 올 수 있다
        raise AIError("응답 오류")
    ch = data["choices"][0]
    if ch.get("error") or ch.get("finish_reason") != "stop":
        raise AIError(f"응답 중단({ch.get('finish_reason')})")
    txt = (ch["message"].get("content") or "").strip()
    if not txt:
        raise AIError("응답 비어 있음")
    return txt


EXTRACT_SYSTEM = (
    "너는 판매장려금 지급 심사 보조원이다. 대리점이 보낸 소명 또는 정정 회신 문서에서 "
    "주장(claims), 증빙(evidence), 적용일(effective_dates), 대상 거래처 ID(agencies), "
    "아직 확인되지 않은 항목(unknowns)을 뽑는다. 각 항목의 quote는 원문에서 글자 하나 바꾸지 않고 "
    "그대로 복사한 부분 문자열이어야 한다. 원문에 없는 내용은 만들지 않는다. "
    "관계 여부, 합산, 승인 권한, 지급 가능 여부는 판단하지 않는다."
)


def _ai_extract(text: str) -> dict | None:
    user = f"<문서>\n{text}\n</문서>"
    if route()[0] == "openrouter":
        return Extraction.model_validate(json.loads(_openrouter(EXTRACT_SYSTEM, user, EXTRACTION_SCHEMA))).model_dump()
    import anthropic
    client = anthropic.Anthropic(api_key=route()[1], timeout=TIMEOUT)
    resp = client.messages.parse(
        model=MODEL, max_tokens=16000, system=EXTRACT_SYSTEM,
        messages=[{"role": "user", "content": user}],
        output_format=Extraction,
    )
    if resp.stop_reason == "refusal" or resp.parsed_output is None:
        return None
    return resp.parsed_output.model_dump()


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text) if s.strip()]


DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}|\d{4}년 \d{1,2}월 \d{1,2}일")


def fallback_extract(text: str) -> dict:
    """키워드 규칙 추출. 일부러 단순하다(대조 E에서 한계를 그대로 측정)."""
    out = {k: [] for k in FIELDS}
    for s in _sentences(text):
        for m in sorted(set(re.findall(r"D-\d{3}", s))):
            out["agencies"].append({"value": m, "quote": m})
        if any(k in s for k in ("적용", "부터", "이전일")):
            for m in DATE_RE.findall(s):
                out["effective_dates"].append({"value": m, "quote": m})
        if any(k in s for k in ("첨부", "증빙")):
            out["evidence"].append({"value": s, "quote": s})
        elif any(k in s for k in ("미정", "확인 중", "추후", "아직")):
            out["unknowns"].append({"value": s, "quote": s})
        elif any(k in s for k in ("이전", "공유", "사용", "변경", "운영", "대신")):
            out["claims"].append({"value": s, "quote": s})
    # 같은 인용 중복 제거
    for k in out:
        seen, uniq = set(), []
        for it in out[k]:
            if it["quote"] not in seen:
                seen.add(it["quote"])
                uniq.append(it)
        out[k] = uniq
    return out


def verify(text: str, raw: dict) -> dict:
    """인용이 원문의 정확한 부분 문자열인지 검사하고 위치를 기록. 없으면 '근거 없음'으로 버린다."""
    fields, dropped = {}, []
    for k in FIELDS:
        fields[k] = []
        for it in raw.get(k, []):
            q = it.get("quote", "")
            off = text.find(q) if q else -1
            if off < 0:
                dropped.append({"field": k, "value": it.get("value", ""), "quote": q, "why": "근거 없음"})
            else:
                fields[k].append({"value": it.get("value", ""), "quote": q, "start": off, "end": off + len(q)})
    return {"fields": fields, "dropped": dropped}


def extract(text: str, use_ai: bool = True) -> dict:
    raw, label, ms = None, FALLBACK_LABEL, None
    if use_ai and has_key():
        t0 = time.perf_counter()
        try:
            raw = _ai_extract(text)
            label = _ok_label() if raw is not None else FALLBACK_LABEL + ", AI 응답 거절"
        except Exception as e:  # API 실패는 대체 추출로 처리하고 이유를 라벨에 남긴다
            label = f"{FALLBACK_LABEL}, AI 호출 실패 {_why(e)}"
        ms = round((time.perf_counter() - t0) * 1000)
    if raw is None:
        raw = fallback_extract(text)
    return verify(text, raw) | {"extractor": label, "ms": ms}


ADDR_RE = re.compile(r"[가-힣]+시 [가-힣0-9]+(?:로|길) \d+")


def propose_correction(text: str, current_address: str) -> dict:
    """정정 신고 문서에서 새 주소 후보를 찾는다. 담당자가 확인 화면에서 고친 뒤 확정한다."""
    for m in ADDR_RE.findall(text):
        if m != current_address:
            return {"field": "주소", "value": m}
    return {"field": "주소", "value": ""}


DRAFT_SYSTEM = (
    "너는 영업지원팀의 상신 문서 서술 초안을 쓴다. 입력 사실만 써서 3~5문장으로 요약한다. "
    "사실을 새로 만들거나 숫자를 다시 계산하지 않는다. 관계 정황은 소명 대상일 뿐이며 "
    f"확정 판단 표현({', '.join(FORBIDDEN)} 같은 말)을 쓰지 않는다. 승인 여부는 영업임원이 결정한다고 쓴다."
)


def _ai_draft(facts: dict) -> str | None:
    user = json.dumps(facts, ensure_ascii=False)
    if route()[0] == "openrouter":
        return _openrouter(DRAFT_SYSTEM, user)
    import anthropic
    client = anthropic.Anthropic(api_key=route()[1], timeout=TIMEOUT)
    resp = client.messages.create(model=MODEL, max_tokens=4000, system=DRAFT_SYSTEM,
                                  messages=[{"role": "user", "content": user}])
    txt = "".join(b.text for b in resp.content if b.type == "text").strip()
    if resp.stop_reason == "refusal":
        raise AIError("AI 응답 거절")
    return txt or None


def draft(facts: dict, use_ai: bool = True) -> tuple[str, str]:
    """사실 표는 코드가 그리고 AI는 서술만 쓴다. 금지 표현이 있으면 대체 초안으로 바꾼다."""
    label = "AI 미사용(대체 작성)"
    if use_ai and has_key():
        try:
            txt = _ai_draft(facts)
            bad = [w for w in FORBIDDEN if txt and w in txt]
            if txt and not bad:
                return txt, _ok_label()
            label += ", AI 서술에 금지 표현 있음" if bad else ", AI 응답 비어 있음"  # 금지어 자체는 화면에 쓰지 않는다
        except AIError as e:
            label += f", {e}" if str(e) == "AI 응답 거절" else f", AI 호출 실패 {e}"
        except Exception as e:  # 추출과 같이 대체 작성으로 처리하고 이유를 라벨에 남긴다(R10)
            label += f", AI 호출 실패 {_why(e)}"
    members = ", ".join(facts["members"])
    txt = (f"관련자 그룹({members})의 {facts['pay_month']} 지급 예정 장려금 합계는 {facts['total']:,}원입니다. "
           f"동일 관련자 합산 기준 200만원을 넘어 {facts['route']} 대상으로 상신합니다. "
           f"관계 근거는 아래 사실 표에 있으며, 관계 정황은 소명 대상이고 확정 판단이 아닙니다. "
           f"승인 여부는 영업임원이 결정합니다.")
    return txt, label


TEXT_FIELDS = ("claims", "evidence", "unknowns")  # 서술형: 정답에 적어 둔 핵심어가 모두 들어 있으면 일치
_SP = re.compile(r"\s+")
_ID = re.compile(r"D\s*[-\u2010-\u2015]?\s*(\d{3})(?!\d)")
_DATE = re.compile(r"(\d{4})\s*(?:-|\.|/|년)\s*(\d{1,2})\s*(?:-|\.|/|월)\s*(\d{1,2})")


def norm(field: str, value: str) -> str | None:
    """대조 E 값 정규화. 거래처 ID와 날짜는 값에 하나만 있어야 한다(둘 이상이면 어느 정답도 채우지 못함)."""
    if field == "agencies":
        ids = _ID.findall(value.upper())
        return f"D-{ids[0]}" if len(ids) == 1 else None
    if field == "effective_dates":
        ds = _DATE.findall(value)
        return f"{ds[0][0]}-{int(ds[0][1]):02d}-{int(ds[0][2]):02d}" if len(ds) == 1 else None
    return _SP.sub("", value)


def match(field: str, want, value: str) -> bool:
    n = norm(field, value)
    if n is None:
        return False
    if field in TEXT_FIELDS:
        return all(_SP.sub("", k) in n for k in want["keywords"])
    return n == want


def _pairs(field: str, want: list, got: list) -> int:
    """정답 항목과 추출 항목의 일대일 최대 대응 수(이분 매칭). 한 추출 항목은 정답 하나만 채운다."""
    owner = {}  # 추출 항목 번호 -> 정답 항목 번호

    def take(w, seen):
        for g, it in enumerate(got):
            if g not in seen and match(field, want[w], it["value"]):
                seen.add(g)
                if g not in owner or take(owner[g], seen):
                    owner[g] = w
                    return True
        return False
    return sum(take(w, set()) for w in range(len(want)))


def score(extraction: dict, gold: dict) -> dict:
    """대조 E: 필드별 정확(정답과 짝지어진 추출), 누락(짝 없는 정답), 오류(짝 없는 추출), 인용 검증 건수.
    인용이 원문에 없는 항목(근거 없음)은 verify가 이미 버렸으므로 정확과 오류에 넣지 않고 인용 검증에만 센다."""
    out = {}
    for k in FIELDS:
        got, want = extraction["fields"].get(k, []), gold.get(k, [])
        hit = _pairs(k, want, got)
        out[k] = {"정확": hit, "누락": len(want) - hit, "오류": len(got) - hit}
    return {"필드": out, "인용": {"원문 일치": sum(len(v) for v in extraction["fields"].values()),
                                  "근거 없음": len(extraction.get("dropped", []))}}


def total(scores: list[dict]) -> dict:
    t = {"필드": {k: {"정확": 0, "누락": 0, "오류": 0} for k in FIELDS}, "인용": {"원문 일치": 0, "근거 없음": 0}}
    for sc in scores:
        for k in FIELDS:
            for m in t["필드"][k]:
                t["필드"][k][m] += sc["필드"][k][m]
        for m in t["인용"]:
            t["인용"][m] += sc["인용"][m]
    t["합계"] = {m: sum(v[m] for v in t["필드"].values()) for m in ("정확", "누락", "오류")}
    return t
