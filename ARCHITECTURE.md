# AURA Architecture

## 시스템 구성

```text
React + TypeScript
├─ App.tsx                    전역 UI 상태와 API orchestration
├─ FileTree                   프로젝트 탐색기
├─ EditorPanel               Monaco 코드/Diff 뷰어
├─ ChatPanel                 질문, 진행 상태, 중지, 기억 초기화
├─ ChangesPanel              변경안 상태와 적용·폐기·재생성
├─ OutputPanel               빌드·테스트, Git, 터미널 탭
├─ GitDiffViewer             스테이징 파일별 side-by-side Diff
└─ TerminalPanel             CMD/PowerShell/Git Bash 명령 UI
                  │ HTTP + NDJSON
FastAPI           ▼
├─ main.py                    API 라우트와 Agent 진행 스트림
├─ agent/agent_loop.py        요청 분류, 질문, Git 직접 경로, 변경 Agent 진입
├─ agent/tool_agent.py        지속형 Ollama 변경 도구 루프와 안전장치
├─ agent/workspace.py         격리 baseline/worktree, 검색·읽기·수정·Diff
├─ agent/retrieval.py         질문 검색어 추출과 저장소 근거 수집
├─ llm/ollama_client.py       로컬 Ollama HTTP client
├─ services/app_settings.py   JSON 설정 로드, 범위 검사, 환경 변수 재정의
├─ services/conversation_store.py 프로젝트별 대화 기억
├─ services/proposal_validator.py 변경 전후 빌드·구문 검증
├─ services/command_runner.py 인수 배열 기반 subprocess와 timeout
├─ tools/file_tools.py        프로젝트 지도, 검색, 제한된 파일 읽기
├─ tools/patch_tools.py       pending Diff, 실제 적용과 폐기
├─ tools/git_tools.py         Git 조회·스테이징·커밋·브랜치·Push
├─ tools/build_tools.py       UI 빌드/테스트 명령 판별
├─ tools/terminal_tools.py    사용자 터미널 명령 실행과 cwd 추적
└─ security/path_guard.py     파일 API의 프로젝트 루트 경계

config/settings.json          Ollama, Agent, 근거, 대화 문맥 실행 설정
```

## 런타임 상태

FastAPI는 현재 로컬 단일 사용자·단일 프로세스 MVP를 전제로 다음 상태를 유지합니다.

| 상태 | 위치 | 수명 |
|---|---|---|
| 열린 프로젝트 루트 | `security.path_guard.guard.root` | 백엔드 프로세스 또는 다음 프로젝트 열기까지 |
| 실행 설정 | `config/settings.json` | 각 설정 조회 시 다시 읽음 |
| 대기 중 변경안 | `tools.patch_tools.pending` | 백엔드 프로세스 또는 적용·폐기·프로젝트 전환까지 |
| 프로젝트별 대화 | `%LOCALAPPDATA%\AURA\conversations.json` | 사용자가 초기화할 때까지 디스크에 유지 |
| UI 테마·터미널 종류 | 브라우저 `localStorage` | 브라우저 저장소를 지울 때까지 |
| 현재 터미널 cwd | `TerminalPanel` React 상태 | 프로젝트 전환 시 새 프로젝트 루트로 초기화 |
| 터미널 출력 기록 | `TerminalPanel` React 상태 | 페이지 새로고침까지 |

새 프로젝트를 열거나 Git 브랜치를 전환하면 기존 pending 변경안은 폐기됩니다. 현재 전역 상태는 다중 사용자, 여러 브라우저 세션, 동시 Agent 작업을 안전하게 분리하지 않습니다.

백엔드를 재시작하면 `guard.root`와 `pending` 같은 프로세스 메모리 상태는 초기화되지만 디스크의 대화 기억과 브라우저 `localStorage`는 유지됩니다. 재시작 후 사용자는 프로젝트를 다시 열어야 합니다.

## 실행 설정

`backend/services/app_settings.py`가 저장소 루트의 `config/settings.json`을 읽고 정수 범위를 검사합니다. 값의 우선순위는 해당 환경 변수, JSON 설정, 코드 내 안전 기본값 순서입니다. `AURA_SETTINGS_FILE`을 지정하면 기본 파일 대신 절대 경로 또는 저장소 루트 기준 상대 경로의 JSON 파일을 사용합니다. 로더는 값을 캐시하지 않으므로 새 요청은 수정된 파일을 읽지만, 이미 실행 중인 Agent 작업에는 변경값이 소급 적용되지 않습니다.

## API 경계

주요 API 그룹은 다음과 같습니다.

- `/api/health`, `/api/ollama/models`: 실행 상태·설정 파일 경로와 Ollama 모델 조회
- `/api/project/*`: 프로젝트 열기, 트리, 파일 읽기
- `/api/conversation`: 프로젝트별 대화 조회와 초기화
- `/api/agent/chat/stream`: NDJSON Agent 진행 이벤트와 최종 응답
- `/api/changes`, `/api/change/*`: pending Diff 조회, 적용, 폐기
- `/api/git/*`: 상태, Diff, 브랜치, 스테이징, 커밋, Push
- `/api/build`, `/api/test`: 프로젝트 표식 기반 명령 실행
- `/api/terminal`: 사용자가 선택한 셸에서 임의 명령 실행

프런트엔드는 `message`와 `model`만 Agent 요청으로 전송합니다. Monaco에서 현재 열어 둔 파일은 Agent 컨텍스트에 자동 포함되지 않습니다.

## 요청 분기

`backend/agent/agent_loop.py`의 `run_agent()`가 요청을 세 경로로 나눕니다.

1. Git 요청: `_direct_git_intent()`와 `_direct_git_response()`가 전용 Git 함수를 호출합니다.
2. 코드 변경 요청: `_requests_change()`가 키워드로 판정하고 `run_change_agent()`로 전달합니다.
3. 코드 질문·분석: 자동 저장소 근거 수집과 `answer_from_evidence()`, 필요 시 탐색 도구 루프를 사용합니다.

현재 변경 요청 판정은 키워드 기반이므로 설명 질문 속 `변경`, `추가`, `fix` 같은 단어를 변경 의도로 오인할 수 있습니다.

## 코드 변경 데이터 흐름

1. `AgentWorkspace`가 열린 프로젝트를 `.aura-workspaces/task-*`의 `baseline`과 `worktree`로 복사합니다.
2. 하나의 Ollama 대화가 프로젝트 지도, 사용자 요청, 검색·읽기 결과와 도구 결과를 누적합니다.
3. 모델은 `project_map`, `list_files`, `search_code`, `search_regex`, `read_file`, `read_file_range`로 근거를 조사합니다.
4. 단순한 정확 교체는 `replace_text`, 구조적·다중 파일 변경은 `apply_patch`를 사용합니다.
5. Python은 읽지 않은 파일 수정, 범위를 벗어난 경로, 맞지 않는 원문 개수와 patch 문맥을 거부합니다.
6. 모델이 도구를 호출하지 않으면 내장 JSON 파싱, `force_tool_call()`, 근거 기반 조회 fallback으로 복구합니다.
7. baseline과 worktree에 같은 고정 검증 명령을 실행하고 `classify_validation()`이 새로운 오류를 구분합니다.
8. 검증 오류는 별도 repair 모델이 아니라 같은 Ollama 대화로 반환합니다.
9. 실제 Diff가 있으면 성공 여부와 관계없이 검증 상태를 포함해 `pending`에 보존합니다.
10. 사용자가 적용을 누르면 원본 충돌을 다시 검사하고 실제 프로젝트에 기록합니다.

자세한 함수 단위 흐름은 [AGENT_FLOW.md](AGENT_FLOW.md)를 참고하세요.

## 검증 경로

Agent 변경 검증과 UI의 빌드/테스트 버튼은 서로 다른 목적과 명령 선택기를 사용합니다.

### Agent 변경 검증

`services/proposal_validator.py`는 baseline/worktree 비교를 위해 다음 프로젝트를 지원합니다.

- CMake
- .NET solution/project
- Cargo
- Go
- Maven
- Gradle wrapper
- npm build script
- Python `compileall`

### 사용자가 누르는 빌드/테스트

`tools/build_tools.py`는 다음 프로젝트를 지원합니다.

- .NET: `dotnet build` / `dotnet test`
- Node: `npm run build` / `npm test`
- CMake: 기존 `build` 폴더 build / `ctest`
- Python: `compileall` / `pytest`

두 경로 모두 저장소에 포함된 빌드 파일이나 스크립트를 실행할 수 있으므로 신뢰할 수 있는 프로젝트에서만 사용해야 합니다.

## Git과 터미널

Git API는 인수 배열을 사용해 `git`을 실행하며, status/diff 외에도 stage, unstage, commit, branch checkout과 Push를 지원합니다. Push 요청은 `PushRequest.confirmed`가 반드시 `true`여야 하고 UI에도 확인 팝업이 있습니다.

수동 터미널은 Agent 도구와 분리되어 있습니다. Agent가 임의 셸을 호출할 수는 없지만 사용자는 CMD, PowerShell, Git Bash에서 임의 명령을 실행할 수 있습니다. 터미널은 명령 종료 후 cwd를 추출해 다음 명령의 시작 경로로 사용하며, 현재 구현은 프로젝트 밖 디렉터리 이동을 금지하지 않습니다.

## 알려진 구조적 제한

- 프로세스 전역 `guard.root`와 `pending` 때문에 다중 사용자·다중 세션에 적합하지 않습니다.
- 요청 의도 분류가 키워드 기반입니다.
- 진행 이벤트는 NDJSON이지만 Ollama 토큰 단위 스트리밍은 아닙니다.
- 코드 변경 경로에서 사용되지 않는 이전 `propose_from_evidence`/review/repair 코드가 남아 있습니다.
- pending 변경안은 메모리 상태라 백엔드 재시작 시 사라집니다.
- 터미널은 OS sandbox나 명령 allowlist가 없습니다.
- API 사용자 인증과 세션별 권한 관리가 없습니다.
- Pull Request, pull/fetch, 브랜치 생성 기능은 아직 없습니다.
