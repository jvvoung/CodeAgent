# AURA

AURA는 React, FastAPI, Monaco Editor, Git CLI와 로컬 Ollama를 연결한 Windows용 로컬 코딩 Agent입니다. 프로젝트를 열고 자연어로 질문하거나 변경을 요청하면 저장소를 검색·읽고, 코드 변경은 실제 프로젝트가 아닌 격리 작업공간에서 만든 뒤 검토 가능한 Diff로 제시합니다.

코드와 프롬프트는 Ollama가 실행되는 로컬 PC 안에서 처리됩니다. 사용자가 변경 제안에서 적용을 선택하기 전에는 실제 프로젝트 파일을 수정하지 않습니다.

## 현재 구현된 기능

### 워크스페이스와 UI

- 프로젝트 폴더 열기, 파일 탐색기, 읽기 전용 Monaco 코드 뷰어
- Monaco side-by-side DiffEditor와 첫 변경 지점 자동 이동
- 파일 탐색기, 코드, 변경 제안/AI 채팅, 결과 패널 크기 조절
- 다크/화이트 테마와 브라우저 로컬 설정 유지
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

- Git 저장소·브랜치 표시, 로컬/원격 브랜치 전환
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

## 환경 변수

다음 값이 현재 활성 코드 경로에서 사용됩니다.

| 환경 변수 | 기본값 | 허용 범위 | 용도 |
|---|---:|---:|---|
| `OLLAMA_BASE_URL` | `http://localhost:11434` | URL | Ollama API 주소 |
| `OLLAMA_NUM_CTX` | `8192` | 4096~131072 | Ollama 컨텍스트 토큰 수 |
| `AURA_AGENT_TIMEOUT_SECONDS` | `180` | 60~600 | 코드 변경 작업 전체 제한 시간 |
| `AURA_AGENT_MAX_STEPS` | `18` | 4~30 | 변경 Agent의 최대 도구 단계 수 |
| `AURA_VALIDATION_REPAIR_ATTEMPTS` | `2` | 0~5 | 검증 실패 후 동일 대화의 수정 기회 |
| `AURA_EVIDENCE_MAX_FILES` | `5` | 1~12 | 코드 질문에 전달할 근거 파일 수 |
| `AURA_EVIDENCE_MAX_CHARS` | `15000` | 4000~100000 | 코드 질문 근거 전체 문자 수 |
| `AURA_EVIDENCE_MAX_FILE_CHARS` | `4000` | 1000~20000 | 근거 한 파일의 최대 문자 수 |
| `AURA_HISTORY_MAX_CHARS` | `12000` | 4000~100000 | 이전 대화 문맥의 최대 문자 수 |

`AURA_CHANGE_EVIDENCE_*`와 `AURA_PROPOSAL_ATTEMPTS`를 참조하는 이전 변경 생성 코드가 일부 남아 있지만, 현재 코드 변경 요청은 앞에서 `run_change_agent()`로 분기되므로 그 값들은 활성 변경 경로에 영향을 주지 않습니다.

RTX 4090 24GB와 더 큰 코딩 모델을 사용하는 PC의 예시는 다음과 같습니다.

```powershell
$env:OLLAMA_NUM_CTX="16384"
$env:AURA_AGENT_TIMEOUT_SECONDS="300"
$env:AURA_AGENT_MAX_STEPS="24"
$env:AURA_EVIDENCE_MAX_FILES="8"
$env:AURA_EVIDENCE_MAX_CHARS="30000"
$env:AURA_EVIDENCE_MAX_FILE_CHARS="8000"
$env:AURA_HISTORY_MAX_CHARS="30000"
```

시간과 단계 수를 늘리면 복잡한 요청에 여유가 생기지만, 작은 모델의 잘못된 도구 선택 자체를 해결하지는 않습니다.

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

백엔드와 프런트엔드는 각각 실행 중인 프로세스가 필요합니다.

터미널 1 — FastAPI 백엔드:

```powershell
cd backend
.\.venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000
```

터미널 2 — React/Vite 프런트엔드:

```powershell
cd frontend
npm.cmd run dev
```

브라우저에서 `http://127.0.0.1:5173`을 열고 작업할 프로젝트의 절대 경로를 입력합니다. API 문서는 `http://127.0.0.1:8000/docs`에서 확인할 수 있습니다.

두 프로세스를 포그라운드로 실행했다면 해당 PowerShell 창을 닫을 때 서버도 종료됩니다. Ollama 서비스도 별도로 실행 중이어야 합니다.

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
- AURA API에는 사용자 인증이 없으므로 백엔드는 `127.0.0.1`에만 바인딩하는 것을 권장합니다.
- Push는 UI 확인과 `confirmed: true` 요청 검증을 거치지만, 이는 사용자 인증이나 권한 시스템을 대체하지 않습니다.

회사 PC 설치 절차는 [COMPANY_SETUP.md](COMPANY_SETUP.md)를 참고하세요. 자세한 내부 구조와 정책은 [ARCHITECTURE.md](ARCHITECTURE.md), [AGENT_FLOW.md](AGENT_FLOW.md), [SECURITY.md](SECURITY.md), [TODO.md](TODO.md)에 정리되어 있습니다.
