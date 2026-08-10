# AURA

AURA는 React, FastAPI, Monaco Editor, Git CLI와 로컬 Ollama를 연결한 Windows용 로컬 코딩 Agent입니다. 프로젝트를 열고 자연어로 질문하거나 변경을 요청하면 저장소를 검색·읽고, 코드 변경은 실제 프로젝트가 아닌 격리 작업공간에서 만든 뒤 검토 가능한 Diff로 제시합니다.

코드와 프롬프트는 Ollama가 실행되는 로컬 PC 안에서 처리됩니다. 사용자가 변경 제안에서 적용을 선택하기 전에는 실제 프로젝트 파일을 수정하지 않습니다.

## 현재 구현된 기능

### 워크스페이스와 UI

- AURA 로그인 화면, 브라우저 세션 유지, 로그아웃과 developer/non-developer 권한 분리
- HOME AI 채팅 UI와 Hamburger Navigation의 HOME, Code Assistant, Settings 메뉴
- 프로젝트 폴더 열기, 하위 폴더 기본 접힘 파일 탐색기, 읽기 전용 Monaco 코드 뷰어
- Monaco side-by-side DiffEditor와 첫 변경 지점 자동 이동
- 파일 탐색기, 코드, 변경 제안/AI 채팅, 결과 패널 크기 조절
- Settings 모달의 Dark/Light 테마 선택, Save/Cancel과 브라우저 로컬 설정 유지
- 변경 제안과 AI 채팅 탭, 진행 상태, 중지, 프로젝트별 대화 초기화

### 로컬 Agent

- Ollama 설치 모델 및 tool-calling 지원 여부 조회
- 언어·빌드 시스템·매니페스트·진입점을 요약하는 프로젝트 지도
- `rg` 우선 정확 검색, 정규식 검색, 파일 전체/범위 읽기
- 프로젝트 질문에 대한 자동 근거 수집과 근거 기반 한국어 답변
- 하나의 지속형 Ollama 도구 대화와 격리된 `baseline`/`worktree`
- 정확한 문자열 교체 `replace_text`와 문맥 기반 `apply_patch`
- 읽지 않은 파일 수정 차단, 반복 검색·실패 도구 호출 차단, 도구 호출 복구
- 변경 전후 검증 비교, 동일 대화 안의 제한된 Build/Fix 재시도
- 검증 실패·기존 오류·검증 불가 상태도 Diff와 함께 보존
- 프로젝트별 대화 기억: `%LOCALAPPDATA%\AURA\conversations.json`

### 변경 제안

- 파일 생성·수정·삭제 Diff
- 파일별/전체 적용과 폐기
- 검증 실패 변경안의 사용자 확인 후 적용
- 오류를 포함한 원래 요청으로 다시 생성
- 변경안 생성 이후 원본이 달라졌는지 적용 직전 재검사

### Git, 빌드와 터미널

- 열린 경로의 상위 Git Root 자동 검색, Git 저장소·브랜치 표시, 로컬/원격 브랜치 전환
- status, 작업 트리 Diff, 스테이징 파일별 Diff
- 전체 스테이징, 스테이징 해제, 커밋
- 사용자 확인 팝업과 API 확인 플래그를 거치는 Push
- UI와 Agent의 Git 상태·스테이징·커밋·브랜치 작업
- CMD, PowerShell, Git Bash 명령 실행과 현재 작업 경로 추적
- .NET, Node, CMake, Python 빌드/테스트 명령 자동 판별
- 명령 stdout/stderr, 종료 코드, 실행 시간, timeout 표시

현재 Pull Request 생성, pull/fetch, 브랜치 생성, WebSocket/토큰 단위 스트리밍은 구현되어 있지 않습니다.

## 준비 사항

- Windows 10/11
- Python 3.10.x (현재 검증 버전: 3.10.11)
- Node.js 20 이상과 npm
- [Ollama](https://ollama.com/)와 tool calling을 지원하는 로컬 모델
- 선택 기능에 따라 Git for Windows, ripgrep(`rg`), dotnet, CMake, pytest

Ollama 기본 주소는 `http://localhost:11434`입니다. AURA는 모델의 `capabilities`에 `tools`가 있는 모델만 Agent 모델로 선택할 수 있게 표시합니다.

## 설정 파일

실행 설정은 저장소 루트의 [`config/settings.json`](config/settings.json)에서 관리합니다. 저장소에 포함된 값은 RTX 4090 24GB와 14B급 코딩 모델을 기준으로 한 시작값입니다.

| JSON 키 | 현재값 | 허용 범위 | 환경 변수 재정의 | 용도 |
|---|---:|---:|---|---|
| `ollama.base_url` | `http://localhost:11434` | URL | `OLLAMA_BASE_URL` | Ollama API 주소 |
| `ollama.num_ctx` | `16384` | 4096~131072 | `OLLAMA_NUM_CTX` | Ollama 컨텍스트 토큰 수 |
| `agent.timeout_seconds` | `300` | 60~600 | `AURA_AGENT_TIMEOUT_SECONDS` | 코드 변경 작업 전체 제한 시간 |
| `agent.max_steps` | `24` | 4~30 | `AURA_AGENT_MAX_STEPS` | 변경 Agent의 최대 도구 단계 수 |
| `agent.validation_repair_attempts` | `2` | 0~5 | `AURA_VALIDATION_REPAIR_ATTEMPTS` | 검증 실패 후 동일 대화의 수정 기회 |
| `evidence.max_files` | `8` | 1~12 | `AURA_EVIDENCE_MAX_FILES` | 코드 질문에 전달할 근거 파일 수 |
| `evidence.max_chars` | `30000` | 4000~100000 | `AURA_EVIDENCE_MAX_CHARS` | 코드 질문 근거 전체 문자 수 |
| `evidence.max_file_chars` | `8000` | 1000~20000 | `AURA_EVIDENCE_MAX_FILE_CHARS` | 근거 한 파일의 최대 문자 수 |
| `conversation.history_max_chars` | `30000` | 4000~100000 | `AURA_HISTORY_MAX_CHARS` | 이전 대화 문맥의 최대 문자 수 |

설정 우선순위는 환경 변수, JSON 설정 파일, 코드 내 안전 기본값 순서입니다. 평소에는 JSON만 수정하면 되고, 환경 변수는 CI나 일회 실행에서만 선택적으로 사용합니다. 다른 설정 파일을 쓰려면 `AURA_SETTINGS_FILE`에 절대 경로 또는 저장소 루트 기준 상대 경로를 지정합니다.

설정 파일은 새 요청부터 다시 읽지만, 진행 중 작업에는 적용되지 않으므로 값을 바꾼 뒤 백엔드를 재시작하는 것이 가장 확실합니다. 시간과 단계 수를 늘리면 복잡한 요청에 여유가 생기지만, 작은 모델의 잘못된 도구 선택 자체를 해결하지는 않습니다.

## 최초 설치

저장소 루트에서 Python 3.10 가상환경과 프런트엔드 패키지를 준비합니다.

```powershell
cd backend
py -3.10 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

cd ..\frontend
npm.cmd install
```

저장소의 `.runtime/python310`에 준비된 Python 3.10.11을 사용하는 PC에서는 다음처럼 가상환경을 만들 수도 있습니다.

```powershell
cd backend
..\.runtime\python310\python.exe -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

`.runtime`, `backend/.venv`, `frontend/node_modules`는 Git에 포함되지 않습니다. 새 PC에서는 Python 3.10과 Node.js 의존성을 다시 준비해야 합니다.

## 실행 방법

Ollama 서비스가 먼저 실행 중이어야 하며, 백엔드와 프런트엔드는 서로 다른 PowerShell 창에서 각각 계속 실행해야 합니다. 아래의 `<CodeAgent 저장 경로>`는 clone한 저장소의 절대 경로로 바꿉니다. 현재 PC의 예시는 `D:\1.SW CODE\CodeAgent`입니다.

### 1. FastAPI 백엔드 실행

첫 번째 PowerShell 창에서 실행합니다.

```powershell
Set-Location "<CodeAgent 저장 경로>\backend"
.\.venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000
```

다음 명령이 성공하면 백엔드, Python 버전, 열린 프로젝트와 실제 설정 파일 경로를 확인할 수 있습니다.

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health
```

API 문서는 `http://127.0.0.1:8000/docs`에서 확인할 수 있습니다.

### 2. React/Vite 프런트엔드 실행

두 번째 PowerShell 창에서 실행합니다.

```powershell
Set-Location "<CodeAgent 저장 경로>\frontend"
npm.cmd run dev
```

브라우저에서 `http://127.0.0.1:5173`을 열면 로그인 화면이 표시됩니다. 테스트 계정은 `config/users.json`에서 백엔드가 읽으며 `1 / 1`은 developer, `2 / 2`는 non-developer입니다. 로그인 후 HOME으로 이동하고 developer만 Navigation의 `Code Assistant`에서 프로젝트를 열 수 있습니다. Git 저장소 내부의 하위 폴더를 열어도 상위 Git Root를 자동으로 찾아 Git 기능에 사용합니다.

### 3. 종료와 재시작

- 각 서버를 실행한 PowerShell 창에서 `Ctrl+C`를 누르면 해당 서버가 종료됩니다.
- `config/settings.json` 또는 백엔드 Python 코드를 바꿨다면 백엔드를 `Ctrl+C`로 종료하고 1번 명령을 다시 실행합니다.
- 프런트엔드 개발 서버는 일반적으로 파일 변경을 자동 반영합니다. 반영되지 않으면 `Ctrl+C` 후 2번 명령을 다시 실행합니다.
- 백엔드를 재시작하면 열린 프로젝트와 대기 중 변경 제안은 초기화됩니다. 브라우저에서 프로젝트를 다시 열어야 하며, 디스크에 저장된 프로젝트별 대화 기억은 유지됩니다.
- PowerShell 창 자체를 닫아도 그 창에서 실행한 서버가 함께 종료됩니다.

포트 충돌이 의심되면 다음 명령으로 기존 프로세스를 확인합니다.

```powershell
netstat -ano -p tcp | findstr /C:":8000" /C:":5173"
```

개발 중 자동 재시작이 필요하면 백엔드 명령에 `--reload`를 추가할 수 있습니다.

## 검증

백엔드 단위 테스트:

```powershell
cd backend
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

API와 실행 서버 스모크 테스트:

```powershell
.\.venv\Scripts\python.exe -m tests.smoke_api
.\.venv\Scripts\python.exe -m tests.smoke_server
```

프런트엔드 타입 검사와 production build:

```powershell
cd ..\frontend
npm.cmd run build
```

일부 스모크 테스트는 실행 중인 백엔드나 Ollama 상태에 영향을 받을 수 있습니다.

## 안전 사용 주의사항

- Agent의 파일 변경 도구는 격리 작업공간 안에서만 동작하며 일반 셸 도구를 제공하지 않습니다.
- 수동 터미널은 사용자가 입력한 임의 명령을 실행합니다. 현재 명령 allowlist나 OS sandbox가 없으므로 신뢰할 수 있는 명령만 실행해야 합니다.
- 빌드/테스트는 저장소의 빌드 스크립트를 실행하므로 신뢰하지 않는 프로젝트를 열어 실행하면 안 됩니다.
- Git commit은 저장소에 설정된 Git hook을 실행할 수 있습니다.
- Code Assistant API는 로그인 시 발급한 메모리 토큰과 developer 역할을 확인하지만, 초기 계정 비밀번호는 테스트용 평문이므로 백엔드는 계속 `127.0.0.1`에만 바인딩하는 것을 권장합니다.
- Push는 developer 인증 외에도 UI 확인과 `confirmed: true` 요청 검증을 거칩니다. 이는 Git 원격 인증을 대체하지 않습니다.

회사 PC 설치 절차는 [COMPANY_SETUP.md](COMPANY_SETUP.md)를 참고하세요. 자세한 내부 구조와 정책은 [ARCHITECTURE.md](ARCHITECTURE.md), [AGENT_FLOW.md](AGENT_FLOW.md), [SECURITY.md](SECURITY.md), [TODO.md](TODO.md)에 정리되어 있습니다.
