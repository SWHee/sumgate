[codex] Starting Codex task thread.
[codex] Thread ready (01a1d9c2-be47-7060-817f-f1403cde7ecd).
[codex] Turn started (01a1d9c2-c1a0-7b93-9b10-a620908d3e4f).
[codex] Assistant message captured: 검토 결과는 실행 재현과 코드상 위험을 구분해 기록하겠습니다. 파일은 수정하지 않고, 먼저 기준 문서와 F1~F7 회귀 테스트를 확인합니다.
[codex] Running command: /bin/zsh -lc "pwd; rg --files -g 'AGENTS.md' -g 'CLAUDE.md' -g 'TOPIC_W07.md' -g 'W07_DESIGN....
[codex] Command completed: /bin/zsh -lc "pwd; rg --files -g 'AGENTS.md' -g 'CLAUDE.md' -g 'TOPIC_W07.md' -g 'W07_DESIGN.... (exit 0)
[codex] Running command: /bin/zsh -lc 'cat /Users/geonhui/.codex/plugins/cache/skills-harry/review-evidence/0.1.0/skil...
[codex] Command completed: /bin/zsh -lc 'cat /Users/geonhui/.codex/plugins/cache/skills-harry/review-evidence/0.1.0/skil... (exit 0)
[codex] Assistant message captured: `review-evidence` 스킬을 확인했지만, Git 저장소와 보고서 파일 쓰기를 전제로 하므로 이번 읽기 전용 폴더 검토에는 적용하지 않습니다. 요청하신 입력과...
[codex] Running command: /bin/zsh -lc 'cat CLAUDE.md TOPIC_W07.md docs/W07_DESIGN.md tests/test_regressions.py'
[codex] Command completed: /bin/zsh -lc 'cat CLAUDE.md TOPIC_W07.md docs/W07_DESIGN.md tests/test_regressions.py' (exit 0)
[codex] Running command: /bin/zsh -lc 'cat app/models.py app/rules.py'
[codex] Command completed: /bin/zsh -lc 'cat app/models.py app/rules.py' (exit 0)
[codex] Running command: /bin/zsh -lc 'nl -ba app/service.py'
[codex] Command completed: /bin/zsh -lc 'nl -ba app/service.py' (exit 0)
[codex] Running command: /bin/zsh -lc 'cat tests/test_regressions.py'
[codex] Command completed: /bin/zsh -lc 'cat tests/test_regressions.py' (exit 0)
[codex] Running command: /bin/zsh -lc "sed -n '319,610p' app/service.py; cat tests/conftest.py; cat docs/W07_DESIGN.md"
[codex] Command completed: /bin/zsh -lc "sed -n '319,610p' app/service.py; cat tests/conftest.py; cat docs/W07_DESIGN.md" (exit 0)
[codex] Running command: /bin/zsh -lc 'nl -ba app/main.py'
[codex] Command completed: /bin/zsh -lc 'nl -ba app/main.py' (exit 0)
[codex] Running command: /bin/zsh -lc "cat app/ai.py app/scenarios.py Dockerfile pyproject.toml; sed -n '45,180p' docs...
[codex] Command completed: /bin/zsh -lc "cat app/ai.py app/scenarios.py Dockerfile pyproject.toml; sed -n '45,180p' docs... (exit 0)
[codex] Assistant message captured: 회귀 테스트는 F1~F7의 핵심 상태와 지급 작업을 직접 검사하고 있습니다. 다만 합산 코드가 다른 사건의 미실행 요청을 제외하고 있어, 두 사건을 번갈아 승인하는 순...
[codex] Running command: /bin/zsh -lc ".venv/bin/python -B -c 'import os,runpy,inspect; os.environ.pop(\"ANTHROPIC_API...
[codex] Running command: /bin/zsh -lc "cat app/templates/base.html app/templates/tasks.html app/templates/case.html ap...
[codex] Command completed: /bin/zsh -lc "cat app/templates/base.html app/templates/tasks.html app/templates/case.html ap... (exit 0)
[codex] Command completed: /bin/zsh -lc ".venv/bin/python -B -c 'import os,runpy,inspect; os.environ.pop(\"ANTHROPIC_API... (exit 0)
[codex] Running command: /bin/zsh -lc ".venv/bin/python -B -u -c ' import os,runpy,json os.environ.pop(\"ANTHROPIC_API...
[codex] Command completed: /bin/zsh -lc ".venv/bin/python -B -u -c ' import os,runpy,json os.environ.pop(\"ANTHROPIC_API... (exit 0)
[codex] Assistant message captured: F1~F7 회귀 재현 9개는 모두 통과했고, S1~S3 결과도 두 번 동일했습니다. 추가 입력에서는 대표자와 주소가 모두 `NONE`인데 지급이 완료되는 경로, 취소된...
[codex] Running command: /bin/zsh -lc ".venv/bin/python -B -u -c ' import os,runpy,json from pathlib import Path os.en...
[codex] Command completed: /bin/zsh -lc ".venv/bin/python -B -u -c ' import os,runpy,json from pathlib import Path os.en... (exit 0)
[codex] Running command: /bin/zsh -lc "sed -n '1,115p' tests/test_flow.py; nl -ba app/models.py | tail -30; cat .docke...
[codex] Command completed: /bin/zsh -lc "sed -n '1,115p' tests/test_flow.py; nl -ba app/models.py | tail -30; cat .docke... (exit 0)
[codex] Running command: /bin/zsh -lc ".venv/bin/python -B -u -c ' import sys,os from pathlib import Path os.environ.p...
[codex] Running command: /bin/zsh -lc ".venv/bin/python -B -u -c ' import os,runpy os.environ.pop(\"ANTHROPIC_API_KEY\...
[codex] Command completed: /bin/zsh -lc ".venv/bin/python -B -u -c ' import os,runpy os.environ.pop(\"ANTHROPIC_API_KEY\... (exit 0)
[codex] Running command: /bin/zsh -lc ".venv/bin/python -B -u -c ' import runpy,json from sqlalchemy import select fro...
[codex] Command completed: /bin/zsh -lc ".venv/bin/python -B -u -c ' import runpy,json from sqlalchemy import select fro... (exit 0)
[codex] Assistant message captured: 동시 요청을 두 DB 세션으로 교차 실행하자 같은 150만원 요청에 지급 완료 작업이 두 개 생겼습니다. 각각 다른 승인 ID를 사용해 현재 중복 방지 키를 통과했습니...
[codex] Running command: /bin/zsh -lc ".venv/bin/python -B -u -c ' import os,json,runpy os.environ.pop(\"ANTHROPIC_API...
[codex] Running command: /bin/zsh -lc "nl -ba app/service.py | sed -n '190,270p'; nl -ba app/service.py | sed -n '401,...
[codex] Command completed: /bin/zsh -lc "nl -ba app/service.py | sed -n '190,270p'; nl -ba app/service.py | sed -n '401,... (exit 0)
[codex] Command completed: /bin/zsh -lc ".venv/bin/python -B -u -c ' import os,json,runpy os.environ.pop(\"ANTHROPIC_API... (exit 0)
[codex] Running command: /bin/zsh -lc "rg --files docs tests data_derived | sort; rg -n 'F1|F2|F3|F4|F5|F6|F7|교차|검토' d...
[codex] Command completed: /bin/zsh -lc "rg --files docs tests data_derived | sort; rg -n 'F1|F2|F3|F4|F5|F6|F7|교차|검토' d... (exit 0)
[codex] Command completed: /bin/zsh -lc ".venv/bin/python -B -u -c ' import sys,os from pathlib import Path os.environ.p... (exit 0)
[codex] Running command: /bin/zsh -lc "nl -ba tests/test_regressions.py | sed -n '100,174p'; nl -ba app/main.py | sed ...
[codex] Command failed: /bin/zsh -lc "nl -ba tests/test_regressions.py | sed -n '100,174p'; nl -ba app/main.py | sed ... (exit 1)
[codex] Assistant message captured: 전체 테스트 44개는 메모리 DB로 통과했습니다. 추가 검증에서는 초기 적재가 중간에 끊긴 DB가 재시작 후에도 요청 40건을 복구하지 않는 문제와, 외부 DB 드라이...
[codex] Assistant message captured: **먼저 1번 중복 지급 재현을 수정 기준으로 삼으세요.** 기존 테스트 44개는 통과했지만, 두 세션을 교차 실행하면 같은 요청이 두 번 지급 완료됩니다. 파일은 수...
[codex] Turn completed.
**먼저 1번 중복 지급 재현을 수정 기준으로 삼으세요.** 기존 테스트 44개는 통과했지만, 두 세션을 교차 실행하면 같은 요청이 두 번 지급 완료됩니다.

파일은 수정하지 않았습니다. `.venv/bin/python -B -c`와 메모리 SQLite만 사용했습니다. 1차 보고서 원문은 없어서 **`tests/test_regressions.py`에 보존된 F1~F7 입력**으로 재검증했습니다.

**치명**

1. **동시 승인으로 승인 ID가 달라지면 같은 요청에 지급 작업이 두 개 생깁니다. — 실행 확인**

   위치: [service.py:401](/Users/geonhui/Downloads/삼일PwC_프로젝트폴더/app/service.py:401), [service.py:484](/Users/geonhui/Downloads/삼일PwC_프로젝트폴더/app/service.py:484), [models.py:100](/Users/geonhui/Downloads/삼일PwC_프로젝트폴더/app/models.py:100)

   재현: D-005, 정산월 `2026-06`, 요청 `RACE`, 1,500,000원. 느린 세션이 승인 대기 사건과 요청을 먼저 읽습니다. 다른 세션에서 승인과 실행을 마친 다음, 느린 세션에서 승인합니다. 이후 **새 세션**으로 실행하고 은행 성공을 회신합니다.

   실제 출력:
   ```text
   FRESH_SECOND_EXECUTE True
   ('RACE', '지급 완료', 1500000, 승인 1)
   ('RACE', '지급 완료', 1500000, 승인 2)
   경로: 영업지원팀 전결
   ```
   오래된 ORM 상태를 기준으로 두 번째 승인을 허용합니다. 중복 방지 키가 `요청 ID + 승인 ID`여서 총 300만원 지급도 막지 못합니다. 실제 병렬 HTTP 부하가 아니라 **두 DB 세션의 순서를 통제한 교차 실행 재현**입니다.

   최소 수정: 승인과 실행에 DB 수준 상태 비교 갱신 또는 잠금을 적용하고, 승인 ID와 무관하게 **한 요청의 활성 지급 작업은 하나**라는 제약을 추가하세요. 취소 후 재지급은 별도 시도로 관리해야 합니다.

**높음**

2. **병합하면 기존 거절과 소명 요구를 건너뛸 수 있습니다. — 실행 확인**

   위치: [service.py:195](/Users/geonhui/Downloads/삼일PwC_프로젝트폴더/app/service.py:195), [service.py:226](/Users/geonhui/Downloads/삼일PwC_프로젝트폴더/app/service.py:226)

   재현: D-005에 A=`2026-06` 정산 150만원, B=`2026-07` 정산 300만원을 접수합니다. B를 상신하고 `증빙 필요`로 거절한 뒤 시각을 `2026-07-03 17:00`으로 이동합니다.

   실제 출력:
   ```text
   사건 1: 4,500,000원, 상위 승인 필요
   사건 2: 구성 변경(해소)
   소명 요청: 사건 2에 열림으로 남음
   소명 없이 사건 1 상신 → 임원 승인 → execute=True
   ```
   요청만 이동하고 거절에 따른 보류 조건과 소명 작업은 따라오지 않습니다. 새 사건 상세에서도 이전 거절 기록이 직접 연결되지 않습니다.

   최소 수정: 병합 시 미해결 소명 조건과 작업을 승계하고, 이전 사건의 승인·거절 이력을 연결하세요. 소명 확인 전에는 재상신을 막아야 합니다.

3. **대표자와 주소가 모두 없어도 관계 확인 없이 지급됩니다. — 실행 확인**

   위치: [service.py:156](/Users/geonhui/Downloads/삼일PwC_프로젝트폴더/app/service.py:156), [service.py:279](/Users/geonhui/Downloads/삼일PwC_프로젝트폴더/app/service.py:279), [service.py:350](/Users/geonhui/Downloads/삼일PwC_프로젝트폴더/app/service.py:350)

   재현: D-005의 대표자와 주소를 모두 `NONE`으로 정정하고 정산계좌는 유지합니다. 150만원을 접수한 뒤 전결 승인, 실행, 은행 성공을 호출합니다.

   실제 출력: `전결 승인 대기 → execute=True → 지급 완료`.

   F4의 “빈 값끼리 일치하지 않는다”는 수정됐지만, **관계를 판단할 정보가 부족하면 확인 필요**라는 조건은 없습니다. 현재 차단 검사는 사실상 계좌 중심입니다.

   최소 수정: 관계 정보 부족 상태를 별도로 계산하고 승인 및 공통 지급 게이트에서 차단하세요.

4. **P1과 달리 다른 사건의 지급 예정 요청을 합산에서 제외합니다. — 실행 확인**

   위치: [service.py:235](/Users/geonhui/Downloads/삼일PwC_프로젝트폴더/app/service.py:235), 특히 249행

   재현: D-005의 같은 지급월에 A=150만원을 승인·실행한 뒤, 은행 회신 전에 B=100만원을 접수합니다.

   실제 출력:
   ```text
   A: 합계 1,500,000원, 영업지원팀 전결, gate=True
   B: 합계 2,500,000원, 영업임원 승인
   A 은행 성공: 지급 완료
   ```
   현재 그룹의 유효 요청은 250만원인데 A는 150만원 승인 근거를 계속 사용합니다. 지급 작업이 없는 B는 제외되고, 이후 승인 ID의 작업도 이전 사건에서 제외됩니다. 이는 명시된 P1과 다릅니다.

   최소 수정: 그룹과 지급월의 전체 유효 요청으로 한도를 계산하고, 개별 지급 작업의 실행 스냅샷과 분리하세요. **직렬 호출에서 서로 다른 두 요청 모두를 전결로 지급시키는 재현까지는 얻지 못했습니다.** 확인된 문제는 합산 누락과 이전 승인 유지입니다.

5. **현재 의존성으로는 외부 DB URL만 바꿔 배포할 수 없습니다. — 로컬 실행 확인, 컨테이너 미검증**

   위치: [pyproject.toml:6](/Users/geonhui/Downloads/삼일PwC_프로젝트폴더/pyproject.toml:6), [models.py:139](/Users/geonhui/Downloads/삼일PwC_프로젝트폴더/app/models.py:139), [Dockerfile:5](/Users/geonhui/Downloads/삼일PwC_프로젝트폴더/Dockerfile:5)

   재현과 실제 출력:
   ```text
   postgresql://...       → ModuleNotFoundError: No module named 'psycopg'
   mysql+pymysql://...    → ModuleNotFoundError: No module named 'pymysql'
   ```
   필요한 드라이버가 선언되지 않았습니다. URL을 생략하면 컨테이너 내부 SQLite로 돌아가므로 AXHub 영속 저장 요구도 충족하지 않습니다.

   최소 수정: 실제 AXHub DB의 드라이버를 의존성에 추가하고, 배포 환경에서는 `DATABASE_URL` 누락 시 시작을 중단하세요.

**중간**

6. **지급계좌에 한 번 ‘확인 불가’를 회신하면 같은 계좌를 다시 확인할 수 없습니다. — 실행 확인**

   위치: [service.py:577](/Users/geonhui/Downloads/삼일PwC_프로젝트폴더/app/service.py:577), [service.py:50](/Users/geonhui/Downloads/삼일PwC_프로젝트폴더/app/service.py:50)

   재현: 원본 D-024 계좌 확인 작업에 `valid=False`, 이어서 `valid=True`.

   실제 출력: `열린 지급계좌 확인 작업이 아님`. 작업은 `확인 불가`, 사건은 `확인 필요`로 남습니다. 재판정도 동일 멱등 키의 기존 작업을 반환하므로 새 확인 작업을 만들지 않습니다.

   최소 수정: 재확인 요청으로 새 시도를 만들거나 기존 작업을 명시적으로 다시 여는 경로를 추가하세요.

7. **초기 적재가 중간에 끊기면 재시작 후 미지급 요청이 복구되지 않습니다. — 중단 지점 상태 재현**

   위치: [main.py:25](/Users/geonhui/Downloads/삼일PwC_프로젝트폴더/app/main.py:25), [service.py:85](/Users/geonhui/Downloads/삼일PwC_프로젝트폴더/app/service.py:85)

   재현: 메모리 DB에 `reset()`만 완료한 상태를 만들고 앱 lifespan을 시작했습니다. 이는 원본 적재 커밋 후 `intake_original()` 전에 중단된 상태입니다.

   실제 출력: `요청 200건, 사건 0건, clock=2026-07-01 09:00`. 시각이 있다는 이유로 접수를 생략합니다.

   최소 수정: 초기화 완료 표식을 모든 적재가 끝난 뒤 기록하고, 미완료 상태에서는 기존 데이터를 삭제하지 않고 접수를 재개하세요.

8. **취소된 지급 작업까지 회차 총액에 더합니다. — 실행 확인**

   위치: [main.py:175](/Users/geonhui/Downloads/삼일PwC_프로젝트폴더/app/main.py:175), [tasks.html:4](/Users/geonhui/Downloads/삼일PwC_프로젝트폴더/app/templates/tasks.html:4)

   재현: 100만원 지급 작업 생성 → 300만원으로 정정하여 취소 → 재상신·재승인·재실행.

   실제 집계: `취소 100만원 + 지급 대기 300만원 = 2건, 400만원`. 실제 활성 지급은 1건, 300만원입니다.

   최소 수정: 회차 지급 집계에서 취소 작업을 제외하고 취소 이력은 별도로 표시하세요.

9. **역할 쿠키가 없으면 영업지원 권한으로 상태를 변경합니다. — HTTP 실행 확인**

   위치: [main.py:37](/Users/geonhui/Downloads/삼일PwC_프로젝트폴더/app/main.py:37)

   재현: 쿠키 없는 클라이언트로 `POST /bulk/approve-support`.

   실제 출력: `303`, 승인 기록 **37개 생성**. 같은 클라이언트의 `/bulk/execute`는 `403`입니다.

   로그인 없는 시연 설계 자체의 문제로 판단한 것은 아닙니다. 다만 “역할 선택 후 서버가 검사한다”는 경계를 원한다면 현재 기본값은 이를 충족하지 않습니다.

   최소 수정: 조회 화면의 기본 역할과 변경 요청의 역할 판정을 분리하고, 변경 요청에는 유효한 역할 선택값을 요구하세요.

10. **합성 정정을 반영한 관계 근거에도 ‘원본’ 라벨이 붙습니다. — HTTP 출력 확인**

    위치: [case.html:22](/Users/geonhui/Downloads/삼일PwC_프로젝트폴더/app/templates/case.html:22)

    재현: S2 실행 후 그룹 사건 상세 조회.

    실제 출력: `D-024 v2`가 포함된 관계 근거 뒤에 `<span ...>원본</span>`이 표시됩니다. 해당 버전은 합성 정정입니다.

    최소 수정: 근거를 `도출`로 표시하고 참조한 원본·합성 버전의 등급을 함께 표시하세요. 테스트는 DB의 등급 값만 검사하므로 이 화면 오류를 놓칩니다.

**F1~F7 재검증 결과**

| 항목 | 보존된 입력으로 확인한 결과 |
|---|---|
| F1 | 확인함, 문제 없음. 금액 변경 후 재처리 차단, 대기 작업 취소, 재승인 후 새 금액 지급까지 통과 |
| F2 | 확인함, 문제 없음. 그룹 변경 후 기지급 150만원과 신규 100만원을 250만원으로 합산 |
| F3 | 기존 입력은 통과. 병합 후 승인 무효와 250만원 합산 확인. 거절·소명 승계는 위 2번 결함 |
| F4 | 빈 값·NONE끼리 불일치 확인함, 문제 없음. 정보 부족 시 지급 차단은 위 3번 결함 |
| F5 | 확인함, 문제 없음. 정산계좌 NONE은 유효 회신으로도 해제되지 않음 |
| F6 | 확인함, 문제 없음. 0원·음수 요청 제외 후 양수 300만원은 임원 경로 유지 |
| F7 | 확인함, 문제 없음. 승인 시 `확정(승인 시)` 변경 및 미확정 지급 차단 |

회귀 단언은 단순히 예외가 없다는 수준은 아닙니다. 금액, 경로, 승인 유효성, 지급 작업 상태를 검사합니다. 다만 **F3은 병합 뒤 정상 지급 완료까지 검사하지 않고, F4는 순수 관계 함수만 검사하며, 동시 세션과 쿠키 없는 요청은 검사하지 않습니다.**

**상태 변경 엔드포인트 전체 역할 검사**

아래 행 번호는 [app/main.py](/Users/geonhui/Downloads/삼일PwC_프로젝트폴더/app/main.py) 기준입니다. 제한된 경로의 비허용 역할 조합 **47개를 호출해 모두 403**을 확인했습니다.

| POST 경로 | 행 | 허용 역할 | 실제 검사 |
|---|---:|---|---|
| `/bulk/approve-support` | 103 | 영업지원 | 있음 |
| `/bulk/execute` | 108 | 회계 | 있음 |
| `/settings/deposits` | 116 | 영업지원 | 있음 |
| `/settings/revalidate` | 121 | 모든 역할 | 없음 |
| `/cases/{cid}/approve` | 146 | 영업지원 또는 영업임원 | 있음. 사건 상태별 승인권자도 검사 |
| `/cases/{cid}/reject` | 151 | 영업임원 | 있음 |
| `/cases/{cid}/submit` | 156 | 영업지원 | 있음 |
| `/cases/{cid}/execute` | 161 | 회계 | 있음 |
| `/tasks/{tid}/account-reply` | 186 | 모의 외부 | 있음 |
| `/tasks/{tid}/bank` | 191 | 모의 외부 | 있음 |
| `/bank/all` | 196 | 모의 외부 | 있음 |
| `/tasks/{tid}/retry` | 201 | 회계 | 있음 |
| `/mock/doc` | 221 | 모의 외부 | 있음 |
| `/mock/amount` | 239 | 모의 외부 | 있음 |
| `/mock/request` | 246 | 모의 외부 | 있음 |
| `/mock/clock` | 255 | 모의 외부 | 있음 |
| `/docs/{did}/confirm` | 295 | 영업지원 | 있음 |
| `/controls/e/ai` | 326 | 모든 역할 | 없음 |
| `/scenarios/reset` | 354 | 모든 역할 | 없음 |
| `/scenarios/run` | 362 | 모든 역할 | 없음 |

검사 없는 네 경로는 `RUN.md`에 모든 역할 허용으로 명시돼 있습니다. 따라서 **“모든 POST에 역할 검사”라는 설명은 정확하지 않습니다.** 쿠키 없는 `/settings/revalidate` 호출로 실제 설정이 `0`으로 바뀌는 것도 확인했습니다.

추가로 `GET /role`은 역할 쿠키를 변경합니다. 이는 공개 역할 전환이라는 시연 설계와 일치합니다.

**나머지 확인 결과와 검증 한계**

| 대상 | 결과 |
|---|---|
| AI 확인 전 판정 반영 | 확인함, 문제 없음. 관련 테스트 통과 |
| 원문에 없는 인용 | 확인함, 문제 없음. 추출 항목에서 제거되고 `근거 없음`에 기록 |
| 키 없는 추출 | 확인함, 문제 없음. `AI 미사용(대체 추출)` |
| API 오류 | 추출 TimeoutError 주입 시 대체 처리와 실패 라벨 확인. 초안 경로는 코드상 대체 작성하지만 오류 이유를 숨김 |
| 취소·완료 작업에 중복 회신 | 확인함, 문제 없음. 취소 회신 무시 및 완료 작업 재처리 방지 |
| 취소 후 재승인·재실행 | 직렬 흐름은 확인함, 문제 없음. 100만원 취소 후 300만원 한 건 지급 완료 |
| 회수계좌의 지급 사용 | 확인함, 문제 없음. D-024 지급계좌는 마스터의 하나 계좌 사용 |
| 확정 표현·U+00B7·지급 분할·임의 지급월 변경 | 검사 범위에서 문제 없음. 지급월 이동은 마감 규칙 경로 |
| 정상 재시작 | 확인함, 문제 없음. 요청 240건과 승인 37건 유지, 중복 적재 없음 |
| 문자열·JSON | S3 생성 데이터의 선언 길이 초과 없음. SQLite에서 JSON 저장·복원 정상. 임의 장문 입력 및 실제 외부 DB는 미검증 |
| 모의 처리 표시 | 모의 입력과 회신 버튼에는 표시됨. 완료 후 작업·사건 화면은 모의 출처 표시가 일관되지 않음 |

S1~S3는 두 번 실행한 결과가 같았습니다. S1은 38사건·40지급 완료, S2는 변경 두 번 차단 후 40지급 완료, S3는 7월 37건 유지·8월 4건 지급으로 설계서 3절의 주요 결과와 일치합니다. 다만 S3의 “AI 구조화”는 실제로 `USE_AI=False`인 대체 추출이며, 설계서에 이 차이를 명시할 필요가 있습니다.

Docker 빌드, PostgreSQL/MySQL 실서버, 실제 AI API 호출, 실제 병렬 HTTP 부하는 실행하지 않았습니다. **44개 테스트 통과는 메모리 DB로 교체한 실행 결과이며, 배포 검증 완료를 뜻하지 않습니다.**
