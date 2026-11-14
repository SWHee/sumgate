"""원본 CSV 읽기 전용 적재. 구분자는 '|', 'NONE'은 문자열 그대로 둔다."""
import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "01_참가자_배포용" / "04_원본데이터"
AGENCY_CSV = SRC / "01_corevia/master/m_agency_cv.csv"
REBATE_CSV = SRC / "01_corevia/sales/sales_rebate_payment_cv.csv"
DEPOSIT_CSV = SRC / "01_corevia/financials/fin_collection_history_cv.csv"


def read(path: Path) -> list[dict]:
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f, delimiter="|"))


def src_ref(path: Path, row_id: str) -> str:
    return f"{path.name}#{row_id}"


def agencies() -> list[dict]:
    return [{"agency_id": r["agency_id"], "name": r["agency_name"], "representative": r["representative_name"],
             "address": r["address"], "account": r["bank_account_no"], "eligible": r["rebate_eligible"],
             "registered": r["registered_date"], "version": 1} for r in read(AGENCY_CSV)]


def deposits() -> list[dict]:
    return [{"deposit_id": r["deposit_id"], "agency_id": r["agency_id"], "bank_account_no": r["bank_account_no"]}
            for r in read(DEPOSIT_CSV)]


def rebates() -> list[dict]:
    return [{"rebate_id": r["rebate_id"], "agency_id": r["agency_id"], "period_ym": r["period_ym"],
             "amount": int(r["rebate_amount_krw"]), "status": r["approval_status"], "approver": r["approver"],
             "payment_date": r["payment_date"]} for r in read(REBATE_CSV)]
