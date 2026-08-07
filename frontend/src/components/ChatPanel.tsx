import {useEffect, useRef, useState} from "react";
import type {FormEvent, KeyboardEvent} from "react";
import type {ChatEntry} from "../types";

const TOOL_LABELS: Record<string, {success: string; failure: string}> = {
  list_files: {success: "프로젝트 파일 목록을 확인했습니다", failure: "프로젝트 파일 목록을 확인하지 못했습니다"},
  search_code: {success: "관련 코드를 검색했습니다", failure: "관련 코드 검색에 실패했습니다"},
  read_file: {success: "소스 파일을 분석했습니다", failure: "소스 파일을 읽지 못했습니다"},
  propose_changes: {success: "검토 가능한 변경안을 만들었습니다", failure: "변경안 생성에 실패했습니다"},
};

export function toolLabel(tool: string, status: "completed" | "failed" = "completed", detail?: string): string {
  const labels = TOOL_LABELS[tool];
  const label = labels ? (status === "failed" ? labels.failure : labels.success) : `${tool.replace(/_/g, " ")} 도구 ${status === "failed" ? "실패" : "실행 완료"}`;
  return status === "failed" && detail ? `${label}: ${detail}` : label;
}

export function ChatPanel({messages, prompt, busy, disabled, showHeader = true, onPrompt, onSubmit, onStop}: {
  messages: ChatEntry[];
  prompt: string;
  busy: boolean;
  disabled: boolean;
  showHeader?: boolean;
  onPrompt: (value: string) => void;
  onSubmit: () => void;
  onStop: () => void;
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
        <div className="prompt-footer"><span>Enter 전송 · Shift+Enter 줄바꿈</span><div className="prompt-actions"><button type="button" className="stop" disabled={!busy} onClick={onStop}>■ 중지</button><button type="submit" className="primary send" disabled={busy || disabled || !prompt.trim()}>전송 <b>↑</b></button></div></div>
      </form>
    </section>
  );
}
