"""DB 모델. 상태는 모두 DB에 둔다(AXHub: 컨테이너 볼륨 금지). 접근은 SQLAlchemy로만."""
import hashlib
import os

from sqlalchemy import BigInteger, Boolean, Integer, String, Text, UniqueConstraint, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from sqlalchemy.schema import CreateIndex, CreateTable

from app.loader import ROOT

DEFAULT_URL = f"sqlite:///{ROOT / 'app' / 'w07.db'}"


class Base(DeclarativeBase):
    pass


class AgencyVersion(Base):
    __tablename__ = "agency_version"
    __table_args__ = (UniqueConstraint("agency_id", "version_no"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    agency_id: Mapped[str] = mapped_column(String(10), index=True)
    version_no: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(Text)
    representative: Mapped[str] = mapped_column(Text)
    address: Mapped[str] = mapped_column(Text)
    account: Mapped[str] = mapped_column(Text)
    effective_at: Mapped[str] = mapped_column(String(20))
    reason: Mapped[str] = mapped_column(Text)
    grade: Mapped[str] = mapped_column(String(10))
    source_ref: Mapped[str] = mapped_column(Text)


class DepositObs(Base):
    """회수 입금 관측. 관계 판정 보강 전용. 지급계좌로 쓰지 않는다."""
    __tablename__ = "deposit_obs"
    deposit_id: Mapped[str] = mapped_column(String(10), primary_key=True)
    agency_id: Mapped[str] = mapped_column(String(10))
    bank_account_no: Mapped[str] = mapped_column(String(50))
    grade: Mapped[str] = mapped_column(String(10), default="원본")


class RebateRequest(Base):
    __tablename__ = "rebate_request"
    rebate_id: Mapped[str] = mapped_column(String(20), primary_key=True)  # 유일
    agency_id: Mapped[str] = mapped_column(String(10), index=True)
    period_ym: Mapped[str] = mapped_column(String(7))
    amount: Mapped[int] = mapped_column(BigInteger)
    pay_month: Mapped[str] = mapped_column(String(7), default="")
    pay_month_grade: Mapped[str] = mapped_column(String(10), default="")
    pay_month_reason: Mapped[str] = mapped_column(String(100), default="")
    status: Mapped[str] = mapped_column(String(20))  # 과거 기록이면 '과거 기록'
    src_status: Mapped[str] = mapped_column(String(10), default="")  # 원본 approval_status
    src_approver: Mapped[str] = mapped_column(String(20), default="")
    src_payment_date: Mapped[str] = mapped_column(String(10), default="")
    case_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    grade: Mapped[str] = mapped_column(String(10))
    source_ref: Mapped[str] = mapped_column(Text)
    note: Mapped[str] = mapped_column(Text, default="")  # 금액 정정 사유가 계속 덧붙는다


class Case(Base):
    """승인 사건 = (관련자 그룹, 지급월)."""
    __tablename__ = "case"
    id: Mapped[int] = mapped_column(primary_key=True)
    group_key: Mapped[str] = mapped_column(Text)
    pay_month: Mapped[str] = mapped_column(String(7))
    total: Mapped[int] = mapped_column(BigInteger, default=0)
    paid: Mapped[int] = mapped_column(BigInteger, default=0)
    route: Mapped[str] = mapped_column(String(20), default="")
    basis_hash: Mapped[str] = mapped_column(String(64), default="")
    basis_json: Mapped[str] = mapped_column(Text, default="{}")
    status: Mapped[str] = mapped_column(String(20), default="접수")
    submitted_hash: Mapped[str] = mapped_column(String(64), default="")
    grade: Mapped[str] = mapped_column(String(10), default="도출")
    prev_ids: Mapped[str] = mapped_column(Text, default="")  # 병합으로 요청을 넘겨준 이전 사건 ID(쉼표 구분)
    # 낙관적 잠금: 다른 세션이 먼저 바꾼 사건을 옛 상태로 덮어쓰면 StaleDataError(R1)
    version: Mapped[int] = mapped_column(Integer, default=1)
    __mapper_args__ = {"version_id_col": version}


class Approval(Base):
    __tablename__ = "approval"
    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(Integer, index=True)
    role: Mapped[str] = mapped_column(String(20))
    decision: Mapped[str] = mapped_column(String(10))  # 승인 / 거절
    reason: Mapped[str] = mapped_column(Text, default="")
    basis_hash: Mapped[str] = mapped_column(String(64))
    basis_json: Mapped[str] = mapped_column(Text)
    decided_at: Mapped[str] = mapped_column(String(20))
    valid: Mapped[bool] = mapped_column(Boolean, default=True)
    invalid_reason: Mapped[str] = mapped_column(Text, default="")
    grade: Mapped[str] = mapped_column(String(10), default="도출")


class Task(Base):
    __tablename__ = "task"
    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[str] = mapped_column(String(20))
    dept: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="열림")
    case_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    request_id: Mapped[str] = mapped_column(String(20), default="")
    agency_id: Mapped[str] = mapped_column(String(10), default="")
    idem_key: Mapped[str] = mapped_column(String(200), unique=True)
    payload: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[str] = mapped_column(String(20))
    grade: Mapped[str] = mapped_column(String(10), default="도출")


class Doc(Base):
    __tablename__ = "doc"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(20))  # 소명 회신 / 정정 신고 / 상신 초안
    case_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    agency_id: Mapped[str] = mapped_column(String(10), default="")
    text: Mapped[str] = mapped_column(Text)
    extraction_json: Mapped[str] = mapped_column(Text, default="{}")
    extractor: Mapped[str] = mapped_column(String(50), default="")
    confirmed_by: Mapped[str] = mapped_column(String(50), default="")
    status: Mapped[str] = mapped_column(String(20), default="확인 대기")
    grade: Mapped[str] = mapped_column(String(10))
    source_ref: Mapped[str] = mapped_column(Text, default="")


class EventLog(Base):
    __tablename__ = "event_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[str] = mapped_column(String(20))  # 가상 시각
    actor: Mapped[str] = mapped_column(String(30))
    actor_type: Mapped[str] = mapped_column(String(10))  # 시스템 / AI / 사람 / 모의 외부
    action: Mapped[str] = mapped_column(String(50))
    ref: Mapped[str] = mapped_column(String(100))
    detail: Mapped[str] = mapped_column(Text, default="")
    grade: Mapped[str] = mapped_column(String(10), default="도출")


class Setting(Base):
    __tablename__ = "setting"
    key: Mapped[str] = mapped_column(String(30), primary_key=True)
    value: Mapped[str] = mapped_column(Text)


# 테이블 정의가 바뀌면 값이 바뀐다. 저장된 표식과 다르면 시작할 때 테이블을 다시 만들고 원본을 다시 적재한다
SCHEMA = hashlib.sha256("".join(str(CreateTable(t)) + "".join(str(CreateIndex(i)) for i in sorted(t.indexes, key=lambda i: i.name))
                               for t in Base.metadata.sorted_tables).encode()).hexdigest()[:12]


def normalize_url(url: str) -> str:
    """AXHub가 주는 postgres:// 또는 postgresql:// 주소를 psycopg 드라이버로 연결하게 바꾼다."""
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


def make_sessionmaker(url: str | None = None):
    url = normalize_url(url or os.environ.get("DATABASE_URL") or DEFAULT_URL)
    engine = create_engine(url, connect_args={"check_same_thread": False} if url.startswith("sqlite") else {})
    Base.metadata.create_all(engine)
    return sessionmaker(engine, expire_on_commit=False)
