# Local Coding Agent

React, FastAPI, Monaco Editor, Git CLI와 로컬 Ollama를 연결한 코드 작업 Agent입니다. 프로젝트를 열고 자연어로 변경을 요청하면 Agent가 관련 코드를 검색·읽은 뒤, 디스크에 바로 쓰지 않고 검토 가능한 diff를 만듭니다.

## 현재 구현된 기능

- 안전한 프로젝트 폴더 열기, 파일 트리와 읽기 전용 Monaco 뷰어
- Ollama 설치 모델 조회와 tool-calling Agent loop
- `rg` 우선 코드 검색 및 Python fallback
- exact-text patch 제안, Monaco side-by-side diff, 파일별/전체 Apply와 Reject
- 원본 변경·중복 문자열·프로젝트 외부 경로 검증
- Git status/diff
- .NET, Node, CMake, Python build/test 명령 자동 판별
- stdout/stderr, 종료 코드, 실행 시간, timeout 표시

## 준비 사항

- Python 3.10.x (검증 버전: 3.10.11)
- Node.js 20 이상
- [Ollama](https://ollama.com/)와 tool calling을 지원하는 로컬 모델
- 선택 사항: Git CLI, ripgrep(`rg`), dotnet, CMake, pytest

Ollama 기본 주소는 `http://localhost:11434`입니다. 다른 주소는 백엔드 실행 전에 `OLLAMA_BASE_URL` 환경 변수로 설정할 수 있습니다.

현재 작업 폴더에는 Windows용 Python 3.10.11이 `.runtime/python310`에 프로젝트 전용으로 설치되어 있습니다. 이 바이너리 폴더는 Git에 포함되지 않습니다. 새 PC에서는 [Python 3.10.11 공식 배포 페이지](https://www.python.org/downloads/release/python-31011/)에서 Python 3.10을 먼저 설치하세요.

## 실행 방법

터미널 1:

```powershell
cd "D:\1.SW CODE\CodeAgent"
.\.runtime\python310\python.exe -m venv backend\.venv
cd backend
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

터미널 2:

```powershell
cd "D:\1.SW CODE\CodeAgent\frontend"
npm.cmd install
npm.cmd run dev
```

브라우저에서 `http://127.0.0.1:5173`을 열고 작업할 프로젝트 폴더의 절대 경로를 입력합니다. 백엔드 API 문서는 `http://localhost:8000/docs`에서 볼 수 있습니다.

## 검증

```powershell
cd backend
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m tests.smoke_api
.\.venv\Scripts\python.exe -m tests.smoke_server

cd ..\frontend
npm.cmd run build
```

스모크 테스트는 실행 중인 Ollama의 모델 목록도 확인하며, 프런트엔드 production build를 한 번 실행합니다.

## 안전 원칙

Agent는 선택된 프로젝트 루트 안의 텍스트 파일만 읽을 수 있습니다. LLM 문자열을 shell 명령으로 실행하지 않으며, 코드 제안은 메모리에 보관했다가 사용자가 Apply를 누른 후에만 저장합니다. Git push, PR, 범용 terminal과 삭제 기능은 아직 노출하지 않습니다.

상세 구조는 [ARCHITECTURE.md](ARCHITECTURE.md), Agent 흐름은 [AGENT_FLOW.md](AGENT_FLOW.md), 보안 경계는 [SECURITY.md](SECURITY.md), 다음 단계는 [TODO.md](TODO.md)를 참고하세요.
