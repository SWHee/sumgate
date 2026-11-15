"""성능 회귀(T7): 시간이 아니라 SQL 문장 수로 단언한다. 원격 Postgres에서는 왕복 횟수가 곧 응답 시간이다."""
from sqlalchemy import event

from app import service as sv

# 수정 전 6,624문장(사건마다 전체 재판정, N+1). 수정 후 로컬 Postgres 196, SQLite 233
BULK_APPROVE_MAX = 300


def test_bulk_approve_sql_statement_count(s):
    n = [0]

    def count(*_):
        n[0] += 1

    eng = s.get_bind()
    event.listen(eng, "before_cursor_execute", count)
    try:
        assert sv.approve_all_support(s) == 37
    finally:
        event.remove(eng, "before_cursor_execute", count)
    assert n[0] <= BULK_APPROVE_MAX, f"일괄 승인 SQL {n[0]}문장(상한 {BULK_APPROVE_MAX})"
