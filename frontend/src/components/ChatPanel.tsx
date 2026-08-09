import {useEffect, useRef, useState} from "react";
import type {FormEvent, KeyboardEvent} from "react";
import type {ChatEntry} from "../types";

const TOOL_LABELS: Record<string, {success: string; failure: string}> = {
  workspace: {success: "격리 작업공간을 준비했습니다", failure: "격리 작업공간을 준비하지 못했습니다"},
  project_map: {success: "프로젝트 구조를 파악했습니다", failure: "프로젝트 구조를 파악하지 못했습니다"},
  list_files: {success: "프로젝트 파일 목록을 확인했습니다", failure: "프로젝트 파일 목록을 확인하지 못했습니다"},
  search_code: {success: "관련 코드를 검색했습니다", failure: "관련 코드 검색에 실패했습니다"},
  search_regex: {success: "이름과 코드 패턴을 확장 검색했습니다", failure: "코드 패턴 검색에 실패했습니다"},
  read_file: {success: "소스 파일을 분석했습니다", failure: "소스 파일을 읽지 못했습니다"},
  read_file_range: {success: "관련 코드 구간을 분석했습니다", failure: "관련 코드 구간을 읽지 못했습니다"},
  replace_text: {success: "정확한 원문을 교체했습니다", failure: "원문 교체에 실패했습니다"},
  apply_patch: {success: "코드 패치를 작업공간에 적용했습니다", failure: "코드 패치 적용에 실패했습니다"},
  revert_file: {success: "불필요한 파일 변경을 되돌렸습니다", failure: "파일 변경을 되돌리지 못했습니다"},
  filter_comment_only: {success: "주석만 변경된 파일을 변경 제안에서 제외했습니다", failure: "주석 변경 필터링에 실패했습니다"},
  validate_changes: {success: "변경안을 격리 환경에서 검증했습니다", failure: "변경안 검증을 실행하지 못했습니다"},
  finish_changes: {success: "최종 변경안을 준비했습니다", failure: "최종 변경안을 준비하지 못했습니다"},
  propose_changes: {success: "검토 가능한 변경안을 만들었습니다", failure: "변경안 생성에 실패했습니다"},
  model_no_tool: {success: "모델 응답을 처리했습니다", failure: "모델이 실행 도구를 선택하지 않았습니다"},
  force_tool_call: {success: "모델의 다음 실행 도구를 복구했습니다", failure: "모델의 실행 도구를 복구하지 못했습니다"},
  reject_inactive_tool: {success: "현재 단계에서 허용되지 않은 과거 도구 호출을 차단했습니다", failure: "도구 단계 검증에 실패했습니다"},
  agent_timeout: {success: "에이전트 제한 시간을 확인했습니다", failure: "에이전트 작업이 제한 시간을 초과했습니다"},
  git_status: {success: "Git 상태를 확인했습니다", failure: "Git 상태를 확인하지 못했습니다"},
  git_diff: {success: "Git 변경 내역을 확인했습니다", failure: "Git 변경 내역을 확인하지 못했습니다"},
  git_stage_all: {success: "모든 변경을 스테이징했습니다", failure: "변경 스테이징에 실패했습니다"},
  git_unstage_all: {success: "스테이징을 해제했습니다", failure: "스테이징 해제에 실패했습니다"},
  git_commit: {success: "Git 커밋을 생성했습니다", failure: "Git 커밋 생성에 실패했습니다"},
  git_branches: {success: "Git 브랜치 목록을 확인했습니다", failure: "Git 브랜치 목록을 확인하지 못했습니다"},
  git_checkout: {success: "Git 브랜치를 전환했습니다", failure: "Git 브랜치 전환에 실패했습니다"},
};

export function toolLabel(tool: string, status: "completed" | "failed" = "completed", detail?: string): string {
  const labels = TOOL_LABELS[tool];
  const label = labels ? (status === "failed" ? labels.failure : labels.success) : `${tool.replace(/_/g, " ")} 도구 ${status === "failed" ? "실패" : "실행 완료"}`;
  if (tool === "propose_changes" && status === "failed") return "변경안 검증에 실패했습니다. 실패 diff는 변경 제안 탭에 보존했습니다";
  return status === "failed" && detail ? `${label}: ${detail}` : label;
}

export function ChatPanel({messages, prompt, busy, disabled, showHeader = true, onPrompt, onSubmit, onStop, onClear}: {
  messages: ChatEntry[];
  prompt: string;
  busy: boolean;
  disabled: boolean;
  showHeader?: boolean;
  onPrompt: (value: string) => void;
  onSubmit: () => void;
  onStop: () => void;
  onClear: () => void;
}) {
  const endRef = useRef<HTMLDivElement>(null);
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => { endRef.current?.scrollIntoView({behavior: "smooth", block: "end"}); }, [messages, busy]);
  useEffect(() => {
    if (!busy) { setElapsed(0); return; }
    const started = Date.now();
    const timer = window.setInterval(() => setElapsed(Math.floor((Date.now() - started) / 1000)), 1000);
    return () => window.clearInterval(timer);
  }, [busy]);
  const submit = (event: FormEvent) => { event.preventDefault(); onSubmit(); };
  const keyboard = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); onSubmit(); }
  };
  return (
    <section className="chat-panel">
      {showHeader && <div className="panel-title"><span>AI 채팅</span><span className="panel-hint">프로젝트 컨텍스트</span></div>}
      <div className="message-list">
        {!messages.length && (
          <div className="welcome">
            <span className="spark">✦</span>
            <h2>어떤 코드를 바꿔드릴까요?</h2>
            <p>요청을 입력하면 프로젝트를 분석하고 관련 코드를 찾아 검토 가능한 변경안을 준비합니다.</p>
            <div className="welcome-steps"><span>1 · 코드 검색</span><span>2 · 변경안 생성</span><span>3 · Diff 검토</span></div>
          </div>
        )}
        {messages.map((message) => (
          <div key={message.id} className={`message ${message.role}`}>
            <span className="message-label">{message.role === "user" ? "나" : message.role === "agent" ? "에이전트" : ""}</span>
            <span>{message.role === "status" ? `✓ ${message.content}` : message.content}</span>
          </div>
        ))}
        {busy && <div className="message thinking"><span className="pulse" /><span>에이전트가 프로젝트를 분석하고 있습니다 · {elapsed}초<small>큰 모델은 첫 응답까지 몇 분 정도 걸릴 수 있습니다.</small></span></div>}
        <div ref={endRef} />
      </div>
      <form className="prompt-box" onSubmit={submit}>
        <textarea
          aria-label="코드 변경 요청"
          value={prompt}
          onChange={(event) => onPrompt(event.target.value)}
          onKeyDown={keyboard}
          placeholder="원하는 코드 변경사항을 자연어로 입력하세요…"
          disabled={busy || disabled}
        />
        <div className="prompt-footer"><span>Enter 전송 · Shift+Enter 줄바꿈</span><div className="prompt-actions">{!!messages.length && <button type="button" className="memory-clear" disabled={busy} onClick={onClear}>대화 초기화</button>}<button type="button" className="stop" disabled={!busy} onClick={onStop}>■ 중지</button><button type="submit" className="primary send" disabled={busy || disabled || !prompt.trim()}>전송 <b>↑</b></button></div></div>
      </form>
    </section>
  );
}
