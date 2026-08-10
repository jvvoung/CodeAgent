# AURA TODO

이 문서는 현재 코드에 구현된 기능과 남은 작업을 구분합니다. 완료 여부는 UI 계획이 아니라 실제 백엔드 API와 테스트 존재 여부를 기준으로 합니다.

## 완료

### 로컬 Agent 코어

- [x] React/FastAPI/Ollama 연결과 tool-calling 모델 조회
- [x] 프로젝트 지도, 정확 검색, 정규식 검색, 제한된 파일 읽기
- [x] 프로젝트 질문의 자동 코드 근거 수집과 근거 기반 답변
- [x] 프로젝트별 대화 기억과 대화 초기화
- [x] `config/settings.json` 기반 실행 설정과 선택적 환경 변수 재정의
- [x] 지속형 Ollama 변경 도구 루프
- [x] 격리된 baseline/worktree와 변경 누적
- [x] exact `replace_text`와 문맥 기반 `apply_patch`
- [x] 읽지 않은 파일 수정, 반복 조회, 반복 실패 도구 호출 차단
- [x] 모델이 도구를 고르지 않을 때 강제 도구 선택과 조회 fallback
- [x] 주석-only 변경 제거와 다중 파일 범위 재검토
- [x] baseline/worktree 검증 비교와 동일 대화 Build/Fix 재시도
- [x] 검증 실패·기존 오류·검증 불가 Diff 보존
- [x] 사용자 중지와 전체 Agent timeout

### UI와 변경 검토

- [x] HOME 기본 화면과 HOME/Code Assistant/Settings Navigation
- [x] AURA 로그인, HOME 채팅 UI, 로그아웃과 역할별 Navigation
- [x] Settings 모달의 Dark/Light 테마 Save/Cancel 및 영구 저장
- [x] 프로젝트를 새로 열 때 파일 탐색기 하위 폴더 기본 접힘
- [x] 프로젝트 탐색기와 읽기 전용 Monaco 코드 뷰어
- [x] Monaco side-by-side Diff와 첫 변경 위치 자동 이동
- [x] 파일별/전체 적용·폐기와 실패 변경안 재생성
- [x] AI 채팅/변경 제안 탭과 변경 알림
- [x] 탐색기·코드·오른쪽 패널·결과 패널 크기 조절
- [x] 다크/화이트 테마
- [x] 한국어 UI와 Agent 진행 상태

### Git, 빌드와 터미널

- [x] 하위 프로젝트 경로에서 상위 Git Root 자동 탐색
- [x] Git 저장소·브랜치·원격 표시
- [x] 로컬/원격 브랜치 checkout
- [x] status, 작업 트리 Diff, 스테이징 파일별 Diff
- [x] 전체 stage/unstage와 commit
- [x] 사용자 확인 기반 Push
- [x] Agent의 Git 상태·stage·commit·branch·Push 요청 경로
- [x] .NET/Node/CMake/Python 빌드·테스트 버튼
- [x] CMD/PowerShell/Git Bash 터미널과 cwd 추적

### 품질 확인

- [x] 백엔드 단위 테스트
- [x] API·서버 스모크 테스트
- [x] 프런트엔드 TypeScript production build

## 우선순위 P0 — 보안과 상태 격리

- [x] JSON 계정 기반 API 인증과 developer 역할용 로컬 세션 토큰
- [ ] 평문 테스트 비밀번호를 bcrypt 해시로 전환
- [ ] 전역 `guard.root`와 `pending`을 브라우저/작업 세션별 상태로 분리
- [ ] 같은 프로젝트의 동시 Agent 실행과 적용에 대한 lock·revision 정책
- [ ] 터미널을 프로젝트 루트로 제한하는 안전 모드와 제한 없는 고급 모드 분리
- [ ] 터미널 위험 명령 정책과 일회/지속 승인 UI
- [ ] 빌드·테스트·Git hook이 저장소 코드를 실행한다는 확인 절차
- [ ] Push 같은 외부 작업에 서버가 발급한 일회 승인 토큰 적용
- [ ] timeout 시 자식 프로세스 트리까지 종료
- [ ] 여러 파일 적용 도중 I/O 실패가 발생할 때 rollback 지원

## 우선순위 P1 — Agent 정확도와 유지보수

- [ ] `_requests_change()` 키워드 판정을 구조화된 intent router로 교체
- [ ] 현재 사용되지 않는 `propose_from_evidence`/review/repair 변경 경로 제거
- [ ] 도구 상태 머신을 명시적인 탐색·수정·검증·범위 검토 단계로 단순화
- [ ] 작은 모델이 만드는 patch 형식 오류에 대한 결정적 보정기 확대
- [ ] 언어·프레임워크 하드코딩 없이 심볼 정의·참조 관계를 더 정확히 수집
- [ ] 사용자 요청 충족 여부를 측정하는 저장소 독립적 Agent eval 세트
- [ ] 중지 요청이 Ollama HTTP 요청과 검증 subprocess까지 즉시 전파되는지 E2E 검증
- [ ] 대형 저장소의 복사·검색·컨텍스트 비용 최적화

## 우선순위 P1 — 상태 복구와 운영

- [ ] pending 변경안의 선택적 디스크 저장과 백엔드 재시작 복구
- [ ] Agent 작업 로그와 도구 trace 다운로드
- [ ] 비밀정보 마스킹과 대화 기억 보존 기간·삭제 정책
- [ ] 프로젝트별 사용자 정의 build/test 명령과 명시적 승인
- [ ] 백엔드/프런트엔드/Ollama를 함께 시작·종료하는 Windows 실행 스크립트 또는 패키징
- [ ] Python·Node·Ollama·Git 의존성 진단 화면

## 우선순위 P2 — Git 협업

- [ ] 브랜치 생성과 삭제
- [ ] fetch/pull과 충돌 안내
- [ ] `gh` CLI 또는 GitHub API 기반 Pull Request 조회·생성
- [ ] PR 대상 브랜치, 제목, 본문 입력과 최종 사용자 확인
- [ ] 원격 인증 상태 진단

## 우선순위 P2 — 스트리밍과 터미널

- [ ] Ollama 토큰 단위 답변 스트리밍
- [ ] 필요성이 확인되면 NDJSON을 WebSocket 또는 SSE로 교체
- [ ] 장기 실행 Agent의 단계별 취소와 재개
- [ ] 실제 PTY 기반 대화형 터미널(xterm.js) 지원
- [ ] 터미널 프로세스 세션 유지와 명령별 중지

## 우선순위 P2 — 테스트

- [ ] React UI 통합/E2E 테스트
- [ ] 실제 Ollama 7B/14B 모델별 성공률·도구 반복·시간 측정
- [ ] C++, C#, Java, Python, TypeScript, UI 없는 프로젝트 fixture 확대
- [ ] 원래 빌드가 깨진 프로젝트와 빌드 환경이 없는 프로젝트 회귀 테스트
- [ ] Git Push 확인, 터미널 경계, 동시 세션 보안 테스트
