# 모아봄(Moabom) 진행 상태 (2026-11-14 21:20 기준)

제출 마감: 2026-11-15(일) 23:59. 설계서는 `docs/W07_DESIGN.md`(v2), 주제와 금지사항은 `TOPIC_W07.md`.

## 끝난 것
- 구현(Opus 5.5 / medium): `app/`, `tests/`(56개 통과, SQLite와 Postgres 양쪽), `data_derived/`, `Dockerfile`, `axhub.yaml`, `RUN.md`.
- 교차 검토(Codex GPT-6 Astra / medium) 1차 7건, 2차 10건 발견. 외부 DB 드라이버 포함 전부 수정. 기록은 `docs/reviews/`.
- AXHub: CLI와 Claude Code 플러그인 설치, 로그인 완료(테넌트 lounge). 앱은 아직 만들지 않았다.
- 원본 무변경 확인: `shasum -a 256 -c docs/reviews/original.sha256 | grep -v ': OK$'` 결과가 비어야 한다(프로젝트 루트에서 실행).

## 남은 것 (순서대로)
1. Claude Code 재시작(AXHub 플러그인 적용).
2. git 저장소 생성. 커밋 전 `git check-ignore .claude/settings.local.json .codex/hooks.json .agents/hooks.json`가 3개를 모두 출력하는지 확인. `.venv`, `*.db`, `__pycache__`는 `.git/info/exclude`로 제외(`.gitignore`는 수정 금지).
3. AXHub 첫 배포: 테넌트 lounge, 앱 이름 `sumgate`(주소는 첫 배포 뒤 변경 불가), 공개 범위 「누구나」, `axhub up` 방식 금지. 첫 배포에서 확인할 미확인 항목: PORT 주입 여부, 헬스 체크 경로.
4. `ANTHROPIC_API_KEY`를 `axhub env`로 등록(사용자가 직접 입력). 등록 뒤 실제 AI 호출과 대조 E 측정.
5. Codex 3차 검토: 한도가 2026-11-15 01:13에 풀린다. 프롬프트는 `docs/reviews/codex_round3_prompt.md`. 실행 명령:
   `node ~/.claude/plugins/cache/openai-codex/codex/1.0.6/scripts/codex-companion.mjs task --fresh --model gpt-6-astra --effort medium --prompt-file docs/reviews/codex_round3_prompt.md`
   주의: 같은 폴더에서 다른 Claude 세션(Orca 작업자 포함)이 끝나면 실행 중인 Codex 작업이 끊긴다. 검토 중에는 작업자를 띄우거나 닫지 않는다.
6. 3차에서 치명, 높음 결함이 나오면 수정 후 재배포.
7. 제출물: 시연 영상(5분, 음성 해설, 실제 작동과 모의 처리 구분, 배속 표시), 설계 설명 필수 6 + 선택 1문항(문항당 1,000자), 심사위원 실행 안내. 중간 제출 1회 후 최종 제출.

## 알려진 한계
- 실제 Claude API 호출 미검증(모킹 테스트만). 실제 병렬 HTTP 부하 미검증.
- 은행 회신 전 지급 작업은 취소 가능하다는 모델 단순화. 로그인 없이 역할 쿠키로 전환(시연용).
- 가정: 지급계좌는 마스터 정산계좌, 회계 마감 2026-07-03 17:00, 지급월은 정산월 다음 달.

## 갱신 (2026-11-15 00:30). 위 내용과 다르면 이 절이 우선한다
- 제품 이름은 모아봄(Moabom). 배포 완료: https://moabom-au27.axhub.app (lounge, 앱 이름 `moabom`, Postgres). GitHub: https://github.com/SWHee/sumgate (`main`).
- 제출 원고 초안: `submission/design_answers.md`(Q1~Q7, 각 1,000자 이하), `run_note.md`, `video_outline.md`, `evidence.md`. 제출 절차와 실제 문항은 `SUBMISSION_GUIDE.md`.
- 미해결: (1) 제출 폼의 AXHub 앱 목록이 비어 있음(참가 신청 계정과 AXHub 로그인 계정이 같은지 확인 필요). (2) `ANTHROPIC_API_KEY` 미등록(명령은 `RUN.md`). 등록 뒤 Q6, Q7 4번, run_note 6번, 영상 대본의 AI 문장을 고친다. (3) Q3의 본인 경험 문장은 사용자가 직접 쓴다. (4) Codex 3차 검토 미실행. (5) 사이트 리뷰에서 나온 `/docs` 주소 충돌, 공용 초기화와 재검증 해제 문제 재확인. (6) AXHub 로그인은 2026-11-15 20:20에 만료.
- 제출 폼 입력, 업로드, 제출은 사용자가 직접 한다. 에이전트는 하지 않는다.
