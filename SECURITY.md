# AURA Security

## 신뢰 모델

AURA는 회사 PC 또는 개인 PC에서 `127.0.0.1`로 실행하는 로컬 개발 도구를 전제로 합니다. JSON 계정 로그인과 developer/non-developer 역할 검사는 제공하지만, 프로젝트·변경안 상태는 아직 사용자별로 격리되지 않아 원격 다중 사용자 서비스로 사용하면 안 됩니다.

Ollama 요청과 검색·Diff 데이터는 `config/settings.json`의 `ollama.base_url`로 전송됩니다. 기본값은 로컬 `http://localhost:11434`이지만 사용자가 다른 주소로 바꾸면 코드 근거도 그 주소로 전달될 수 있습니다. `OLLAMA_BASE_URL` 환경 변수가 있으면 JSON 값보다 우선합니다.

## Agent 파일 경계

- 일반 파일 API는 `PathGuard.resolve()`로 최종 경로를 해석하고 열린 프로젝트 루트 하위인지 검사합니다.
- Agent 변경 도구는 실제 프로젝트가 아닌 `.aura-workspaces/task-*`의 격리된 worktree만 수정합니다.
- Agent patch 경로는 절대 경로와 `..`를 거부합니다.
- 기존 파일은 모델이 먼저 `read_file` 또는 `read_file_range`로 읽어야 수정할 수 있습니다.
- `replace_text`는 원문의 실제 출현 개수가 `expected_count`와 정확히 일치해야 합니다.
- `apply_patch`는 변경 전 문맥이 파일에서 고유하게 일치해야 하며, 다중 파일 patch는 실제 쓰기 전에 전체 patch를 먼저 계획합니다.
- 알려진 바이너리 확장자와 NUL이 있는 파일은 읽기·수정에서 제외합니다.
- 파일 읽기와 Python 검색은 기본 1MB 제한을 사용합니다. `rg` 경로는 의존성·빌드 폴더를 glob으로 제외하지만 별도의 1MB 옵션을 전달하지는 않습니다.
- 격리 복사와 검증에서는 의존성, 빌드 결과, 모델·실행 바이너리와 25MB 초과 파일을 제외합니다.

## 변경안 적용 경계

- Agent 변경은 `pending`에 원본과 변경본으로 저장되고 사용자가 적용하기 전까지 실제 프로젝트에 쓰지 않습니다.
- 적용 전에 선택한 모든 기존 파일이 제안 당시 원본과 같은지 검사합니다.
- 새 파일 경로에 다른 파일이 생겼는지 확인합니다.
- 검증 실패 또는 자동 범위 검토 미완료 변경안은 `confirm_unverified=true`가 없으면 적용하지 않습니다.
- UI는 이러한 상태의 변경안을 적용할 때 별도 확인 대화상자를 표시합니다.

검사 이후 실제 파일 쓰기 중 OS I/O 오류가 발생하는 경우를 위한 트랜잭션 rollback은 현재 없습니다. 따라서 여러 파일 적용은 사전 충돌 검사를 수행하지만 파일시스템 수준의 완전한 원자적 트랜잭션은 아닙니다.

## LLM과 명령 실행 경계

- 변경 Agent에는 일반 셸 도구가 제공되지 않습니다.
- LLM이 출력한 임의 명령 문자열을 Agent가 직접 실행하지 않습니다.
- Agent 검증은 서버가 프로젝트 표식으로 선택한 고정 명령만 실행합니다.
- subprocess는 shell 문자열 결합 대신 실행 파일과 인수 배열을 사용하며 stdout/stderr와 timeout을 관리합니다.

다만 고정된 빌드 명령도 저장소의 `CMakeLists.txt`, `package.json`, MSBuild target, Gradle/Maven 구성 등을 실행합니다. 따라서 신뢰하지 않는 프로젝트의 빌드·검증은 임의 코드 실행으로 이어질 수 있습니다. AURA의 격리 작업공간은 파일 변경 격리이며 OS 프로세스 sandbox가 아닙니다.

## Git 경계

- 사용자가 Git 저장소의 하위 폴더를 프로젝트로 열면 Git 명령은 자동으로 찾은 상위 Git Root에서 실행됩니다.
- 따라서 `stage all`, commit, branch checkout과 Push는 열린 하위 프로젝트뿐 아니라 같은 Git 저장소의 다른 경로 변경에도 영향을 줄 수 있습니다. 실행 전 Git 결과 탭에서 전체 변경 범위를 확인해야 합니다.
- Git 명령은 `backend/tools/git_tools.py`에 정의된 인수 배열만 실행합니다.
- 지원 범위는 status, Diff, staged Diff, stage all, unstage all, commit, branch 조회·checkout, Push입니다.
- Push API는 `PushRequest.confirmed=true`를 요구하고 UI에서도 원격·브랜치를 보여주는 확인 팝업을 거칩니다.
- Agent가 Push를 요청해도 프런트엔드 확인 전에는 실행하지 않습니다.

`confirmed=true`는 인증된 developer가 별도로 보내는 사용자 의사 표시 값이며 인증 토큰 자체는 아닙니다. 또한 `git commit`은 저장소의 Git hook을 실행할 수 있고, Push는 외부 원격 저장소로 데이터를 전송합니다.

## 수동 터미널 경계

수동 터미널은 Agent 도구와 별개의 사용자 기능입니다.

- CMD, PowerShell, Git Bash에서 사용자가 입력한 임의 명령을 실행합니다.
- 기본 cwd는 열린 프로젝트지만 `cd` 후 프로젝트 밖 경로도 다음 cwd로 유지할 수 있습니다.
- 명령 allowlist, 위험 명령 차단, 일회 승인, OS sandbox가 없습니다.
- 명령은 최대 300초 후 종료하지만 자식 프로세스 전체 트리를 항상 정리한다고 보장하지 않습니다.

따라서 터미널은 일반 로컬 셸과 같은 권한을 가진 기능으로 취급해야 합니다. 신뢰할 수 없는 명령을 붙여넣거나 AURA를 신뢰하지 않는 사용자에게 노출해서는 안 됩니다.

## 네트워크와 API

- CORS는 `http://localhost:5173`과 `http://127.0.0.1:5173`만 허용합니다.
- CORS는 브라우저 정책이며 API 인증을 대신하지 않습니다.
- `/api/auth/login`은 `config/users.json`을 백엔드에서만 읽고 불투명 세션 토큰을 발급합니다.
- 프런트엔드는 비밀번호를 저장하지 않고 인증 여부·역할·토큰만 `sessionStorage`에 보관합니다.
- `/api/health`와 인증 API 외 Code Assistant API는 developer Bearer 토큰이 필요합니다.
- 초기 `users.json`은 테스트용 평문 비밀번호를 사용합니다. 실제 배포 전 `verify_password()` 경계를 bcrypt 등으로 교체해야 합니다.
- `guard.root`와 `pending`은 프로세스 전역이므로 여러 브라우저가 같은 상태를 공유합니다.
- 백엔드는 `--host 127.0.0.1`로 실행하는 것을 권장합니다. `0.0.0.0`으로 노출하면 같은 네트워크의 다른 장치가 파일, Git, 빌드, 터미널 API에 접근할 위험이 있습니다.

## 로그와 비밀정보

- `config/settings.json`은 Git에 포함되므로 API 키, 토큰, 비밀번호를 저장하지 않아야 합니다.
- 다른 설정 파일을 선택하는 `AURA_SETTINGS_FILE` 역시 비밀정보 저장소가 아닙니다.
- 대화 내용은 `%LOCALAPPDATA%\AURA\conversations.json`에 평문 JSON으로 저장됩니다.
- 프로젝트 코드 일부와 오류 메시지가 Ollama 대화에 포함됩니다.
- 터미널 stdout/stderr와 빌드 결과가 UI에 표시됩니다.
- 현재 비밀정보 탐지·마스킹, 대화 암호화, 보존 기간 정책은 없습니다.

민감한 저장소에서는 `.env`, 키, 토큰, 인증서가 프롬프트·로그·대화 기억에 포함되지 않도록 사용자가 주의해야 합니다.

## 우선 보완 항목

1. bcrypt 비밀번호 해시와 계정 관리 정책 적용
2. 인증 세션별 프로젝트·pending 상태 분리
3. 터미널의 프로젝트 루트 제한 또는 명령별 승인/정책 모드
4. 빌드·테스트·Git hook 실행에 대한 명확한 사용자 승인과 프로세스 sandbox
5. Push를 포함한 외부 네트워크 작업의 일회 승인 토큰
6. 대화 기억과 로그의 비밀정보 마스킹·보존 정책
7. 여러 파일 적용 실패 시 rollback 또는 임시 파일 기반 원자적 교체
8. Windows Job Object 등을 이용한 timeout 자식 프로세스 트리 종료

`reset --hard`, `clean -fdx`, 디스크·전원 명령은 Agent 전용 도구로 제공하지 않는 정책을 유지해야 합니다.
