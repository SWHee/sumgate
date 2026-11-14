"""AI 역할: 문서 구조화와 상신 서술 초안만. 관계 판정, 합산, 승인 경로는 하지 않는다.

키는 서버 환경변수 ANTHROPIC_API_KEY에서만 읽는다. 없으면 규칙 기반 대체 추출기를 쓴다.
"""
import os
import re

from pydantic import BaseModel

MODEL = "claude-opus-5-5"
AI_LABEL = f"AI 사용({MODEL})"
FALLBACK_LABEL = "AI 미사용(대체 추출)"
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


def has_key() -> bool:
    # anthropic.Anthropic()은 로그인 프로필도 찾으므로, 키 환경변수가 있을 때만 API를 쓴다.
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


EXTRACT_SYSTEM = (
    "너는 판매장려금 지급 심사 보조원이다. 대리점이 보낸 소명 또는 정정 회신 문서에서 "
    "주장(claims), 증빙(evidence), 적용일(effective_dates), 대상 거래처 ID(agencies), "
    "아직 확인되지 않은 항목(unknowns)을 뽑는다. 각 항목의 quote는 원문에서 글자 하나 바꾸지 않고 "
    "그대로 복사한 부분 문자열이어야 한다. 원문에 없는 내용은 만들지 않는다. "
    "관계 여부, 합산, 승인 권한, 지급 가능 여부는 판단하지 않는다."
)


def _ai_extract(text: str) -> dict | None:
    import anthropic
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    resp = client.messages.parse(
        model=MODEL, max_tokens=16000, system=EXTRACT_SYSTEM,
        messages=[{"role": "user", "content": f"<문서>\n{text}\n</문서>"}],
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
    raw, label = None, FALLBACK_LABEL
    if use_ai and has_key():
        try:
            raw = _ai_extract(text)
            label = AI_LABEL if raw is not None else FALLBACK_LABEL + ", AI 응답 거절"
        except Exception as e:  # API 실패는 대체 추출로 처리하고 이유를 라벨에 남긴다
            label = f"{FALLBACK_LABEL}, AI 호출 실패 {type(e).__name__}"
    if raw is None:
        raw = fallback_extract(text)
    return verify(text, raw) | {"extractor": label}


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
    "확정 판단 표현을 쓰지 않는다. 승인 여부는 영업임원이 결정한다고 쓴다."
)


def draft(facts: dict, use_ai: bool = True) -> tuple[str, str]:
    label = "AI 미사용(대체 작성)"
    if use_ai and has_key():
        try:
            import json

            import anthropic
            client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
            resp = client.messages.create(
                model=MODEL, max_tokens=4000, system=DRAFT_SYSTEM,
                messages=[{"role": "user", "content": json.dumps(facts, ensure_ascii=False)}],
            )
            txt = "".join(b.text for b in resp.content if b.type == "text").strip()
            if resp.stop_reason != "refusal" and txt:
                return txt, AI_LABEL
            label += ", AI 응답 거절" if resp.stop_reason == "refusal" else ", AI 응답 비어 있음"
        except Exception as e:  # 추출과 같이 대체 작성으로 처리하고 이유를 라벨에 남긴다(R10)
            label += f", AI 호출 실패 {type(e).__name__}"
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
