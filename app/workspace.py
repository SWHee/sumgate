"""방문자별 작업 공간. 견본(초기 상태, 요청으로 바뀌지 않음) 하나와, 방문자가 처음 상태를 바꿀 때 만드는 작업 공간.

Postgres는 작업 공간마다 스키마(ws_<ID>, schema_translate_map), SQLite는 작업 공간마다 파일(<DB 이름>_ws/<ID>.db).
작업 공간은 견본과 같은 초기화 루틴(원본 적재 + 미지급 40건 접수)으로 만든다. 같은 입력이라 견본과 같은 상태가 된다.
"""
import os
import re
import secrets
import time
from pathlib import Path

from sqlalchemy import Column, Float, MetaData, String, Table, create_engine, delete, inspect, insert, select, update
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool
from sqlalchemy.schema import CreateSchema, DropSchema

from app import service as sv
from app.models import DEFAULT_URL, SCHEMA, normalize_url

TTL = 7 * 24 * 3600  # 이 기간 상태를 바꾸지 않은 작업 공간은 지운다(초)
CAP = 300  # 작업 공간 개수 상한. 넘으면 가장 오래 쓰지 않은 것부터 지운다
TEMPLATE = "template"
ID = re.compile(r"[0-9a-f]{32}")  # 쿠키 값은 이 형식과 등록부를 모두 통과해야 스키마 이름, 파일 이름에 쓰인다

registry = Table("workspace", MetaData(), Column("id", String(32), primary_key=True),
                 Column("schema_hash", String(12)), Column("last_used", Float))


class Spaces:
    def __init__(self, url: str | None = None):
        url = normalize_url(url or os.environ.get("DATABASE_URL") or DEFAULT_URL)
        self.pg = not url.startswith("sqlite")
        self.engine = create_engine(url, connect_args={} if self.pg else {"check_same_thread": False})
        registry.create(self.engine, checkfirst=True)
        if not self.pg:
            db = Path(make_url(url).database)
            self.dir = db.with_name(db.stem + "_ws")
            self.dir.mkdir(exist_ok=True)
        self._sm = {}

    def sm(self, ws: str | None = None) -> sessionmaker:
        """ws가 None이면 견본."""
        name = ws or TEMPLATE
        if name not in self._sm:
            eng = (self.engine.execution_options(schema_translate_map={None: f"ws_{name}"}) if self.pg else
                   create_engine(f"sqlite:///{self.dir / name}.db", poolclass=NullPool,
                                 connect_args={"check_same_thread": False}))
            self._sm[name] = sessionmaker(eng, expire_on_commit=False)
        return self._sm[name]

    def names(self) -> list[str]:
        """실제로 있는 견본과 작업 공간(스키마 또는 파일)."""
        if self.pg:
            return sorted(n[3:] for n in inspect(self.engine).get_schema_names() if n.startswith("ws_"))
        return sorted(p.stem for p in self.dir.glob("*.db"))

    def _drop(self, name: str):
        if self.pg:
            with self.engine.begin() as c:
                c.execute(DropSchema(f"ws_{name}", cascade=True, if_exists=True))
        else:
            (self.dir / f"{name}.db").unlink(missing_ok=True)
        self._sm.pop(name, None)
        with self.engine.begin() as c:
            c.execute(delete(registry).where(registry.c.id == name))

    def _build(self, name: str):
        self._drop(name)
        if self.pg:
            with self.engine.begin() as c:
                c.execute(CreateSchema(f"ws_{name}"))
        with self.sm(name)() as s:
            sv.reset(s)
            sv.intake_original(s)

    def prepare(self):
        """시작 시: 스키마 표식이 다른 작업 공간과 등록되지 않은 것(만들다 끊긴 것)을 지우고 견본을 새로 만든다."""
        with self.engine.begin() as c:
            c.execute(delete(registry).where(registry.c.schema_hash != SCHEMA))
            keep = set(c.scalars(select(registry.c.id)))
        for n in self.names():
            if n not in keep:
                self._drop(n)
        self._build(TEMPLATE)

    def find(self, cookie: str) -> str | None:
        """쿠키의 작업 공간 ID. 형식이 틀렸거나 등록되지 않았으면 None(견본)."""
        if not ID.fullmatch(cookie or ""):
            return None
        with self.engine.connect() as c:
            return c.scalar(select(registry.c.id).where(registry.c.id == cookie))

    def create(self) -> str:
        self._evict()
        ws = secrets.token_hex(16)
        self._build(ws)
        with self.engine.begin() as c:  # 다 만든 뒤에 등록한다. 중간에 끊기면 다음 시작 때 지워진다
            c.execute(insert(registry).values(id=ws, schema_hash=SCHEMA, last_used=time.time()))
        return ws

    def touch(self, ws: str):
        with self.engine.begin() as c:
            c.execute(update(registry).where(registry.c.id == ws).values(last_used=time.time()))

    def _evict(self):
        with self.engine.connect() as c:
            rows = c.execute(select(registry.c.id, registry.c.last_used).order_by(registry.c.last_used)).all()
        old = [r.id for r in rows if time.time() - r.last_used > TTL]
        live = [r.id for r in rows if r.id not in old]
        for ws in old + live[:max(0, len(live) - CAP + 1)]:  # 새로 하나 만들 자리를 남긴다
            self._drop(ws)
