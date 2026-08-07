# TODO

## 완료 — MVP

- [x] React/FastAPI 연결과 IDE형 dark UI
- [x] 프로젝트 열기, 안전한 파일 트리와 파일 읽기
- [x] Ollama 모델 조회와 실제 tool-calling Agent loop
- [x] `rg` 코드 검색과 Python fallback
- [x] 구조화된 patch, Monaco diff, 파일별/전체 Apply와 Reject
- [x] Git status/diff
- [x] .NET/Node/CMake/Python build와 test 명령 판별
- [x] 오류 처리, logging, timeout, project root 검증
- [x] 백엔드 단위 테스트와 API/build 스모크 테스트

## Phase 4 — Git 쓰기와 권한

- [ ] Permission Manager와 일회/지속 승인 UI
- [ ] branch/create/checkout, add, commit
- [ ] 승인 기반 push/pull/fetch
- [ ] `gh` 기반 PR 조회/생성

## Phase 5 — 실시간 작업

- [ ] WebSocket Agent progress와 streaming 답변
- [ ] xterm.js terminal과 PowerShell/CMD/Git Bash 세션
- [ ] 위험 명령 필터와 project-root 강제 cwd

## Phase 6 — 자율 복구와 운영 품질

- [ ] 최대 3회 Build & Fix loop
- [ ] 프로젝트별 사용자 build/test 명령 설정
- [ ] 세션별 상태 분리와 취소 기능
- [ ] 통합/E2E 테스트와 대형 저장소 성능 최적화

