# Security

## 적용된 경계

- 모든 상대·절대 파일 경로를 `Path.resolve()`한 뒤 열린 project root의 하위인지 확인한다.
- 숨김 폴더, 의존성 폴더, build 결과, 1MB 초과 파일과 알려진 바이너리 형식을 트리/검색/읽기에서 제외한다.
- `rg`는 argument list로 실행하며 shell parsing을 사용하지 않는다. 사용할 수 없으면 Python 텍스트 검색으로 fallback한다.
- LLM은 읽기 도구와 변경 제안 도구만 호출할 수 있다. 임의 명령 실행 도구는 제공하지 않는다.
- patch는 old 문자열이 정확히 한 번 존재할 때만 생성한다.
- Apply는 대상 파일 모두가 제안 당시 원본과 같은지 먼저 확인하므로 일부만 적용되는 상황을 막는다.
- Git은 status/diff만, build/test는 서버가 결정한 고정 명령만 실행한다.
- subprocess는 stdout/stderr를 분리해 캡처하고 timeout 시 종료한다.

## 다음 단계에서 필요한 정책

Git 쓰기와 terminal을 추가할 때 `write`, `commit`, `push/PR`, `delete`, `generic shell`을 별도 권한 등급으로 나누고 일회/지속 승인 UI를 제공해야 합니다. `reset --hard`, `clean -fdx`, 디스크/전원 명령은 승인 여부와 무관하게 기본 차단합니다.

