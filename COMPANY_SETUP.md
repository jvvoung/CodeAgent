# 회사 PC 설치 및 운영 가이드

이 문서는 회사 PC에서 AURA를 내려받아 로컬 Ollama 기반 코딩 Agent로 실행하기 위한 준비 사항과 점검 절차를 설명합니다.

Ollama와 Python 3.10만 설치되어 있다고 바로 실행되는 것은 아닙니다. Python 백엔드 의존성, Node.js 프런트엔드 의존성, Git과 대상 프로젝트의 빌드 도구도 준비해야 합니다.

## 1. 필수 구성

| 구성 | 권장 또는 최소 조건 | 용도 |
|---|---|---|
| Windows | Windows 10/11 | 현재 지원 운영체제 |
| Python | 3.10.x | FastAPI 백엔드와 Python 검증 |
| Node.js | 20 이상 | React/Vite 프런트엔드 |
| npm | Node.js에 포함 | 프런트엔드 의존성 설치와 실행 |
| Ollama | 실행 가능한 로컬 서비스 | 로컬 LLM 추론 |
| Ollama 모델 | tool calling 지원 코딩 모델 | Agent의 검색·읽기·수정 도구 선택 |
| Git for Windows | 최신 사내 승인 버전 | 저장소 다운로드와 AURA Git 기능 |

권장 도구:

- `rg`(ripgrep): 저장소 검색 속도를 높입니다. 없으면 Python 검색으로 대체됩니다.
- Git Bash: AURA 터미널에서 Git Bash를 선택할 때 필요합니다.
- 대상 프로젝트의 빌드 SDK와 컴파일러: Agent 변경안의 자동 검증에 필요합니다.

## 2. 프로젝트 종류별 추가 도구

| 프로젝트 | 필요한 도구 예시 |
|---|---|
| C#/.NET | 프로젝트가 요구하는 .NET SDK |
| C/C++ | CMake, Ninja 또는 Visual Studio Build Tools와 컴파일러 |
| Node/TypeScript | Node.js, npm, 프로젝트 패키지 |
| Python | Python 3.10, 프로젝트 패키지, 테스트 시 pytest |
| Rust | Cargo/Rust toolchain |
| Go | Go toolchain |
| Java | JDK, Maven 또는 Gradle |

코드 검색과 읽기는 빌드 도구 없이도 가능하지만, 빌드 도구가 없으면 변경 제안이 `검증 불가` 상태로 표시될 수 있습니다.

## 3. 저장소 다운로드

```powershell
git clone https://github.com/jvvoung/CodeAgent.git
cd CodeAgent
```

회사에서 GitHub 대신 사내 GitLab, Azure DevOps 또는 별도 미러를 사용한다면 승인된 저장소 주소로 clone하고 `origin`을 설정합니다.

다음 항목은 Git에 포함되지 않으므로 회사 PC에서 다시 준비합니다.

- `.runtime`
- `backend/.venv`
- `frontend/node_modules`
- Ollama 모델
- 개인 Git 인증 정보
- 회사별 프록시 환경 변수와 비밀정보

## 4. Ollama 준비

Ollama 서비스가 실행 중인지 확인합니다.

```powershell
ollama list
```

회사에서 사용하기로 한 tool-calling 코딩 모델이 없다면 설치합니다.

```powershell
ollama pull qwen2.5-coder:14b
```

AURA는 Ollama의 모델 정보에서 `tools` capability가 확인되는 모델만 Agent 모델로 선택할 수 있게 표시합니다. 모델을 설치했는데 UI에서 비활성화된다면 다음을 확인합니다.

1. Ollama가 실행 중인가.
2. `http://localhost:11434`에 접근할 수 있는가.
3. 설치한 모델이 tool calling을 지원하는가.
4. 백엔드를 모델 설치 후 다시 시작했는가.

GPU 사용 여부는 다음 명령으로 확인합니다.

```powershell
ollama ps
nvidia-smi
```

`ollama ps`의 `PROCESSOR`에 GPU 비율이 나타나고 `nvidia-smi`에 `llama-server.exe`가 보이면 GPU를 사용 중입니다. Windows 작업 관리자는 기본 그래프가 3D 엔진을 표시할 수 있으므로 CUDA/Compute 그래프와 전용 GPU 메모리도 함께 확인합니다.

## 5. Python 3.10 백엔드 준비

Python 버전을 먼저 확인합니다.

```powershell
py -3.10 --version
```

저장소 루트에서 가상환경과 백엔드 패키지를 설치합니다.

```powershell
cd backend
py -3.10 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Windows Python Launcher의 `py -3.10`이 없다면 설치된 Python 3.10 실행 파일의 절대 경로를 사용합니다.

```powershell
& "C:\Python310\python.exe" -m venv .venv
```

생성된 가상환경이 정확한 버전인지 확인합니다.

```powershell
.\.venv\Scripts\python.exe --version
```

출력은 `Python 3.10.x`여야 합니다.

## 6. Node.js 프런트엔드 준비

Node.js와 npm 버전을 확인합니다.

```powershell
node --version
npm.cmd --version
```

프런트엔드 패키지를 설치합니다.

```powershell
cd ..\frontend
npm.cmd install
```

회사 보안 정책상 외부 npm registry 접속이 불가능하다면 사내 npm registry 또는 승인된 오프라인 패키지 캐시가 필요합니다.

## 7. RTX 4090 권장 설정

RTX 4090 24GB 회사 PC에서 14B급 양자화 코딩 모델을 사용할 때의 시작값입니다.

```json
{
  "ollama": {
    "base_url": "http://localhost:11434",
    "num_ctx": 16384
  },
  "agent": {
    "timeout_seconds": 300,
    "max_steps": 24,
    "validation_repair_attempts": 2
  },
  "evidence": {
    "max_files": 8,
    "max_chars": 30000,
    "max_file_chars": 8000
  },
  "conversation": {
    "history_max_chars": 30000
  }
}
```

위 내용은 이미 저장소의 `config/settings.json`에 포함되어 있습니다. 회사 PC 사양에 맞춰 이 파일을 직접 수정하면 PowerShell마다 환경 변수를 다시 입력할 필요가 없습니다. 환경 변수는 JSON 값을 일시적으로 덮어써야 할 때만 사용합니다.

VRAM 부족, 과도한 공유 GPU 메모리 사용 또는 응답 지연이 발생하면 다음 순서로 낮춥니다.

1. `config/settings.json`의 `ollama.num_ctx`를 `8192`로 낮춥니다.
2. 동시에 실행 중인 다른 GPU 프로그램을 종료합니다.
3. 더 작은 양자화 또는 모델을 사용합니다.

시간과 단계 수를 늘리는 것은 복잡한 요청에 여유를 주지만, 모델의 잘못된 도구 선택이나 잘못된 patch 자체를 해결하지는 않습니다.

## 8. 실행

PowerShell 창 두 개와 실행 중인 Ollama 서비스가 필요합니다. 아래 명령은 저장소의 상위 폴더에서 실행하는 예시이며, 다른 위치에 clone했다면 실제 절대 경로를 사용합니다.

터미널 1 — FastAPI 백엔드:

```powershell
cd CodeAgent\backend
.\.venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000
```

설정을 바꿨다면 진행 중인 작업을 중지하고 백엔드를 재시작합니다.

터미널 2 — React/Vite 프런트엔드:

```powershell
cd CodeAgent\frontend
npm.cmd run dev
```

브라우저 접속 주소:

```text
http://127.0.0.1:5173
```

백엔드 API 문서:

```text
http://127.0.0.1:8000/docs
```

PowerShell에서 포그라운드로 실행한 경우 창을 닫으면 해당 서버도 종료됩니다. AURA 사용 중에는 백엔드, 프런트엔드와 Ollama가 모두 실행 중이어야 합니다.

서버 종료는 각 PowerShell 창에서 `Ctrl+C`를 누릅니다. 백엔드 재시작 시 열린 프로젝트와 대기 중 변경 제안은 메모리에서 초기화되므로 브라우저에서 프로젝트를 다시 열어야 합니다. `%LOCALAPPDATA%\AURA\conversations.json`에 저장된 대화 기억은 유지됩니다.

## 9. 설치 확인

백엔드 단위 테스트:

```powershell
cd CodeAgent\backend
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

프런트엔드 production build:

```powershell
cd CodeAgent\frontend
npm.cmd run build
```

서비스 확인:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health
Invoke-RestMethod http://127.0.0.1:8000/api/ollama/models
```

확인할 항목:

- `/api/health`의 `python`이 `3.10.x`인가.
- `/api/health`의 `agent_core`가 `persistent-ollama-tools-v1`인가.
- `/api/health`의 `settings_file`이 clone한 저장소의 `config/settings.json`을 가리키는가.
- `/api/ollama/models`에 설치한 모델이 표시되는가.
- 모델의 `supports_tools`가 `true`인가.
- 프런트엔드에서 프로젝트를 열고 파일 트리가 표시되는가.

## 10. Git 인증

status와 로컬 Diff는 별도 원격 인증 없이 사용할 수 있습니다. Push를 사용하려면 회사 PC에서 저장소 원격에 대한 Git 인증이 필요합니다.

```powershell
git remote -v
git status
```

회사 정책에 따라 다음 중 승인된 방식을 사용합니다.

- Git Credential Manager
- 회사 SSO
- SSH key
- 사내 Git 서비스용 개인 액세스 토큰

AURA의 Push 확인 팝업은 사용자 실수 방지 절차이며 GitHub 또는 사내 Git 인증을 대신하지 않습니다.

## 11. 사내 네트워크와 오프라인 환경

인터넷이 제한되면 다음 항목을 미리 준비하거나 사내 미러를 사용해야 합니다.

- Git 저장소 또는 압축된 소스
- Python wheel 패키지와 사내 PyPI 주소
- npm 패키지와 사내 npm registry
- Ollama 설치 파일과 모델 데이터
- .NET SDK, CMake, 컴파일러 등 빌드 도구
- GitHub 대신 사용할 사내 원격 저장소

프록시 환경에서는 Git, pip, npm, Ollama 모델 다운로드 각각에 별도 프록시 설정이 필요할 수 있습니다. 프록시와 인증정보를 저장소 파일에 커밋하지 않습니다.

## 12. 코드 반출 방지 점검

회사 코드를 로컬 PC 밖으로 보내지 않으려면 다음을 확인합니다.

- `config/settings.json`의 `ollama.base_url`을 기본값 `http://localhost:11434`로 유지합니다.
- 원격 Ollama 주소를 사용하지 않습니다.
- FastAPI를 `127.0.0.1`에만 바인딩합니다.
- 회사 방화벽 정책과 허용된 Git 원격을 확인합니다.
- Push 전 원격 저장소 주소와 현재 브랜치를 확인합니다.
- 대화 기억 파일 `%LOCALAPPDATA%\AURA\conversations.json`의 사내 보존 정책을 확인합니다.
- `.env`, 키, 토큰 같은 비밀정보를 Agent 질문에 직접 포함하지 않습니다.
- `config/settings.json`은 Git에 포함되는 운영 설정이므로 토큰이나 비밀번호를 기록하지 않습니다.

AURA에는 로컬 로그인과 developer 권한 검사가 있지만 초기 `config/users.json`은 평문 테스트 계정입니다. 비밀번호 해시와 세션별 작업 상태 격리가 완료되기 전에는 `--host 0.0.0.0`으로 실행하지 마세요.

## 13. 보안상 주의할 기능

- 수동 터미널은 일반 로컬 셸과 같은 권한으로 임의 명령을 실행합니다.
- 터미널에서 `cd`로 프로젝트 밖 경로로 이동할 수 있습니다.
- 빌드와 테스트는 프로젝트의 빌드 스크립트를 실행하므로 신뢰하지 않는 프로젝트에서 실행하면 안 됩니다.
- Git commit은 저장소의 Git hook을 실행할 수 있습니다.
- Push는 외부 원격 저장소로 코드를 전송합니다.
- Agent의 격리 작업공간은 파일 변경 격리이며 OS 프로세스 sandbox가 아닙니다.

상세 보안 경계는 [SECURITY.md](SECURITY.md)를 참고합니다.

## 14. 최종 체크리스트

- [ ] Python 3.10.x가 설치되어 있다.
- [ ] `backend/.venv`를 Python 3.10으로 생성했다.
- [ ] `requirements.txt` 설치가 완료됐다.
- [ ] Node.js 20 이상과 npm이 설치되어 있다.
- [ ] `frontend/node_modules` 설치가 완료됐다.
- [ ] Ollama가 실행 중이다.
- [ ] tool calling 지원 코딩 모델이 설치되어 있다.
- [ ] `ollama ps`와 `nvidia-smi`에서 GPU 사용을 확인했다.
- [ ] Git for Windows와 원격 인증이 준비됐다.
- [ ] 대상 프로젝트에 필요한 SDK와 빌드 도구가 설치되어 있다.
- [ ] 백엔드가 `127.0.0.1:8000`에서 실행된다.
- [ ] 프런트엔드가 `127.0.0.1:5173`에서 실행된다.
- [ ] 첫 화면에 AURA 로그인이 표시되고 계정별 HOME/Code Assistant 권한이 구분된다.
- [ ] Git 저장소 하위 폴더를 열어도 상위 저장소와 브랜치가 표시된다.
- [ ] `/api/health`와 developer 로그인 후 `/api/ollama/models` 응답을 확인했다.
- [ ] 회사 코드 반출·대화 기록·Git 원격 정책을 확인했다.
