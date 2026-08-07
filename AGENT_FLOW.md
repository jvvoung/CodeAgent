# Agent Flow

```text
User request
    ↓
Ollama chat_with_tools
    ├─ list_files ──────┐
    ├─ search_code ─────┤ 읽기 전용, 자동 허용
    └─ read_file ───────┘
    ↓
propose_changes
    ↓ exact old text / unique match / root path 검증
Pending diff in memory
    ↓
React Monaco DiffEditor
    ├─ Reject → pending diff 제거
    └─ Apply  → 원본 전체 재검증 → 파일 저장
```

도구 호출은 요청당 최대 12회입니다. 각 도구 결과는 Ollama 대화에 다시 추가되며 모델이 다음 도구 또는 최종 답변을 결정합니다. 모델의 일반 텍스트는 명령으로 실행되지 않습니다.

Build와 Test는 AI가 생성한 shell 문자열이 아니라 서버가 프로젝트 표식(`*.sln`, `package.json`, `CMakeLists.txt`, `pyproject.toml`)을 보고 선택한 고정 명령만 사용합니다.

