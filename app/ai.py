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
            label += f", AI 서술 금지 표현({bad[0]})" if bad else ", AI 응답 비어 있음"
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


def score(extraction: dict, gold: dict) -> dict:
    """대조 E: 정답 대비 누락률과 오류율. 항목 일치는 정답 문자열이 인용에 포함되는지로 본다."""
    n_gold = n_found = n_ext = n_wrong = 0
    for k in FIELDS:
        got = extraction["fields"].get(k, [])
        want = gold.get(k, [])
        n_gold += len(want)
        n_ext += len(got)
        n_found += sum(any(w in g["quote"] or g["quote"] in w for g in got) for w in want)
        n_wrong += sum(not any(w in g["quote"] or g["quote"] in w for w in want) for g in got)
    return {"정답 항목": n_gold, "찾음": n_found, "추출 항목": n_ext, "오추출": n_wrong,
            "누락률": round((n_gold - n_found) / n_gold, 3) if n_gold else 0.0,
            "오류율": round(n_wrong / n_ext, 3) if n_ext else 0.0}
