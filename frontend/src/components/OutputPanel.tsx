import type {CommandResult} from "../types";

function output(result: CommandResult | null): string {
  if (!result) return "빌드, 테스트 또는 Git 명령을 실행하면 결과가 여기에 표시됩니다.";
  const text = [result.stdout, result.stderr].filter(Boolean).join("\n").trim();
  return text || `명령이 종료 코드 ${result.return_code}(으)로 완료되었습니다.`;
}

export function OutputPanel({tab, result, busy, onTab, onRun}: {
  tab: "build" | "git";
  result: CommandResult | null;
  busy: string;
  onTab: (tab: "build" | "git") => void;
  onRun: (action: "build" | "test" | "status" | "diff") => void;
}) {
  const success = result && result.return_code === 0;
  return (
    <section className="output-panel">
      <div className="output-toolbar">
        <div className="output-tabs"><button className={tab === "build" ? "active" : ""} onClick={() => onTab("build")}>빌드 · 테스트</button><button className={tab === "git" ? "active" : ""} onClick={() => onTab("git")}>Git 결과</button></div>
        <div className="output-actions">
          {tab === "build" ? <><button disabled={!!busy} onClick={() => onRun("build")}>▷ 빌드</button><button disabled={!!busy} onClick={() => onRun("test")}>◇ 테스트</button></> : <><button disabled={!!busy} onClick={() => onRun("status")}>상태</button><button disabled={!!busy} onClick={() => onRun("diff")}>변경 내역</button></>}
        </div>
      </div>
      <div className="terminal-output">
        {busy && <div className="running"><span className="pulse" />명령을 실행하고 있습니다…</div>}
        {!busy && result && <div className={`result-line ${success ? "success" : "failure"}`}><span>{success ? "✓" : "×"}</span>{success ? "명령 실행 성공" : `명령 실행 실패 (${result.return_code})`}<small>{result.duration.toFixed(2)}초</small></div>}
        <pre>{output(result)}</pre>
      </div>
    </section>
  );
}
