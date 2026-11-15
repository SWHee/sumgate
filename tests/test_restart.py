"""T6: 재시작 시험. 실제 앱 프로세스(uvicorn)를 내렸다 올린 뒤 견본과 작업 공간 상태를 비교한다.

견본은 시작할 때마다 초기 상태로 새로 만들고, 작업 공간(사건, 승인, 지급 작업, 저장된 대조 E 측정)은 그대로 남아야 한다.
"""
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
from sqlalchemy import select

from app import service as sv
from app.models import Approval, Case, Task
from app.workspace import Spaces

ROOT = Path(__file__).resolve().parent.parent


def start(url: str, port: int) -> subprocess.Popen:
    env = {k: v for k, v in os.environ.items() if k not in ("OPENROUTER_API_KEY", "ANTHROPIC_API_KEY")}
    p = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port)], cwd=ROOT,
                         env=env | {"DATABASE_URL": url}, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(150):
        try:
            if httpx.get(f"http://127.0.0.1:{port}/", timeout=1).status_code == 200:
                return p
        except httpx.HTTPError:
            pass
        assert p.poll() is None, "앱 프로세스가 시작하지 못함"
        time.sleep(0.2)
    p.terminate()
    raise AssertionError("앱 프로세스가 30초 안에 응답하지 않음")


def stop(p: subprocess.Popen):
    p.terminate()
    p.wait(timeout=20)


def state(sm):
    with sm() as s:
        return {"사건": [(c.id, c.status, c.total) for c in s.scalars(select(Case).order_by(Case.id))],
                "승인": [(a.id, a.case_id, a.decision, a.basis_hash) for a in s.scalars(select(Approval).order_by(Approval.id))],
                "작업": [(t.id, t.type, t.status) for t in s.scalars(select(Task).order_by(Task.id))],
                "대조 E": sv.get(s, "e_ai:EXP-01_D-011.txt")}


def test_restart_keeps_workspace_and_rebuilds_template(db_url, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", db_url)
    with socket.socket() as so:
        so.bind(("127.0.0.1", 0))
        port = so.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    p = start(db_url, port)
    try:
        with httpx.Client(base_url=base) as cl:
            cl.get("/role", params={"r": "영업지원"})
            cl.post("/bulk/approve-support")
            cl.get("/role", params={"r": "회계"})
            cl.post("/bulk/execute")
            cl.get("/role", params={"r": "모의 외부"})
            cl.post("/bank/all", data={"result": "성공"})
            ws = cl.cookies["ws"]
        sp = Spaces(db_url)
        template0 = state(sp.sm())
        with sp.sm(ws)() as s:  # 키 없는 시험이라 AI 측정 결과를 작업 공간 DB에 직접 저장해 둔다
            sv.put(s, "e_ai:EXP-01_D-011.txt", json.dumps(
                {"측정 시각": "2026-11-15 10:00:00 KST", "추출기": "AI 사용(시험)", "소요 ms": 1234,
                 "추출": {"fields": {"agencies": [{"value": "D-011", "quote": "D-011", "start": 0, "end": 5}]},
                          "dropped": []}}, ensure_ascii=False))
            s.commit()
        before = state(sp.sm(ws))
        sp.engine.dispose()
        assert before["승인"] and any(t[2] == "지급 완료" for t in before["작업"]) and before["대조 E"]
        assert not template0["승인"]
        stop(p)

        p = start(db_url, port)
        sp = Spaces(db_url)
        assert state(sp.sm(ws)) == before
        assert state(sp.sm()) == template0  # 견본은 다시 만들어도 초기 상태 그대로
        sp.engine.dispose()
        with httpx.Client(base_url=base, cookies={"ws": ws}) as cl:
            page = cl.get("/controls").text
            assert "AI 측정 1/3건" in page and "2026-11-15 10:00:00 KST (실제 시각), AI 사용(시험), 1234ms" in page
        with httpx.Client(base_url=base) as cl:
            assert "AI 측정 0/3건" in cl.get("/controls").text
    finally:
        stop(p)
