import os

import pytest

from app import service as sv
from app.models import Base, make_sessionmaker

# DATABASE_URL을 주고 돌리면 그 DB(Postgres)에서, 없으면 테스트마다 새 SQLite 파일에서 돈다.
# monkeypatch보다 먼저 한 번만 읽는다.
PG_URL = os.environ.get("DATABASE_URL", "")


@pytest.fixture(autouse=True)
def no_api_key(monkeypatch):
    # 테스트는 키 없이 돌고 외부로 아무것도 보내지 않는다
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


@pytest.fixture
def db_url(tmp_path):
    """테스트마다 빈 DB 주소. Postgres는 하나를 같이 쓰므로 테스트 시작 전에 테이블을 모두 지운다."""
    if not PG_URL:
        return f"sqlite:///{tmp_path / 't.db'}"
    engine = make_sessionmaker(PG_URL).kw["bind"]
    Base.metadata.drop_all(engine)
    engine.dispose()
    return PG_URL


@pytest.fixture
def sm(db_url):
    return make_sessionmaker(db_url)


@pytest.fixture
def s(sm):
    with sm() as session:
        sv.reset(session)
        sv.intake_original(session)
        yield session
