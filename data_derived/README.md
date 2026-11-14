# data_derived: 합성 입력

원본(`01_참가자_배포용/04_원본데이터/`)은 읽기만 하고 고치지 않는다. 시나리오 S2, S3와 대조 E에 필요한 입력 중 원본에 없는 것만 여기 둔다.
모든 파일의 데이터 등급은 **합성**이다. 화면과 DB에서도 `합성` 라벨이 붙는다.

| 파일 | ID | 적용 시점(가상) | 생성 이유 | 연결되는 원본 행 |
|---|---|---|---|---|
| `docs/COR-01_D-024.txt` | COR-01 | 2026-07-01 | S2(a): 임원 승인 뒤 D-024 주소 이전 신고가 들어오는 상황. 마스터 새 버전 v2를 만들고 재검증이 승인을 막는지 본다 | `m_agency_cv.csv#D-024` |
| `docs/COR-02_D-005.txt` | COR-02 | 2026-07-01 | S2: 장려금 요청이 없는 무관 거래처의 정정이 어떤 승인도 무효로 만들지 않는지 본다 | `m_agency_cv.csv#D-005` (rebate_eligible False, 장려금 기록 없음) |
| `amount_corrections.csv` | SYN-AC-0001 | 2026-07-01 09:00 | S2(b): 임원 승인 뒤 요청 금액이 정정되는 상황 | `sales_rebate_payment_cv.csv#RB-00180` |
| `docs/EXP-01_D-011.txt` | EXP-01 | S3 마감 이후 | S3: 영업임원 거절 뒤 대리점 소명 회신. 대조 E 문서 1 | `m_agency_cv.csv#D-011`, `fin_collection_history_cv.csv#DP-00006` |
| `docs/EXP-02_D-024.txt` | EXP-02 | 해당 없음 | 대조 E 문서 2 | `m_agency_cv.csv#D-024`, `fin_collection_history_cv.csv#DP-00013`, `#DP-00014` |
| `docs/EXP-03_D-037.txt` | EXP-03 | 해당 없음 | 대조 E 문서 3 | `m_agency_cv.csv#D-037`, `fin_collection_history_cv.csv#DP-00020` |
| `docs/gold_E.json` | 정답 | 해당 없음 | 대조 E 정답. 각 항목은 원문 부분 문자열이다 | EXP-01~03 |
| `synthetic_requests.csv` | SYN-RB-0001 | 2026-08-01 10:00 | S3: 8월 회차로 옮겨진 관련자 그룹에 7월 정산 요청이 새로 들어와 합계가 바뀌는 상황 | 그룹 {D-011, D-024, D-037} |

## 주의
- 소명 문서의 내용(공동 관리 계좌, 대리 송금 등)은 지어낸 시연용 문장이다. 원본 사실이 아니다.
- 은행 회신과 지급계좌 회신은 파일이 아니라 화면 버튼과 시나리오 코드에서 넣는 **모의 회신**이다.
- CSV 구분자는 원본과 같은 `|`다.
