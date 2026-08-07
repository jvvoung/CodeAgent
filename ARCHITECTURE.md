# Architecture

## 구성

```text
React + TypeScript
├─ Project explorer / Monaco code viewer
├─ AI chat / Agent progress
├─ Monaco DiffEditor / Apply / Reject
└─ Git / Build / Test output
              │ REST API
FastAPI       ▼
├─ agent/agent_loop.py       제한된 tool-calling loop
├─ llm/ollama_client.py      Ollama HTTP client
├─ tools/file_tools.py       tree, read, rg search + fallback
├─ tools/patch_tools.py      검증된 메모리 patch와 적용
├─ tools/git_tools.py        read-only Git 명령
├─ tools/build_tools.py      build/test 판별
├─ services/command_runner.py timeout subprocess wrapper
└─ security/path_guard.py    project root 경계
```

FastAPI 프로세스는 로컬 단일 사용자 MVP를 전제로 현재 project root와 pending patch를 메모리에 유지합니다. 새 프로젝트를 열면 이전 pending patch는 폐기됩니다.

## 변경 데이터 흐름

1. 사용자의 자연어 요청과 도구 스키마를 Ollama에 전달한다.
2. 모델은 `list_files`, `search_code`, `read_file`로 필요한 문맥만 수집한다.
3. 모델이 `propose_changes`를 호출하면 서버가 old 문자열의 존재성과 유일성을 확인한다.
4. 원본/수정본은 메모리에 보관되고 React가 Monaco DiffEditor로 표시한다.
5. Apply 때 모든 대상 파일의 원본을 먼저 재검증한 후에만 디스크에 쓴다.

## 제한

- 현재 상태는 프로세스 전역이며 다중 사용자/다중 세션용이 아니다.
- Agent 진행 이벤트는 REST 응답 완료 후 표시된다. 실시간 WebSocket streaming은 다음 단계다.
- Git 쓰기, 범용 shell, terminal, push/PR은 구현 전이다.

