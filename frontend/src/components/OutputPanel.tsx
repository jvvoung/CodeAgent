import {useState} from "react";
import type {CommandAction, CommandResult, GitFileChange, GitInfo} from "../types";
import {repositoryName} from "../utils/git";
import {GitDiffViewer} from "./GitDiffViewer";
import {TerminalPanel} from "./TerminalPanel";

function output(result: CommandResult | null): string {
  if (!result) return "빌드, 테스트 또는 Git 명령을 실행하면 결과가 여기에 표시됩니다.";
  const text = [result.stdout, result.stderr].filter(Boolean).join("\n").trim();
  return text || `명령이 종료 코드 ${result.return_code}(으)로 완료되었습니다.`;
}

export function OutputPanel({tab, result, busy, gitInfo, stagedFiles, theme, projectPath, commitMessage, onCommitMessage, onTab, onRun}: {
  tab: "build" | "git" | "terminal";
  result: CommandResult | null;
  busy: string;
  gitInfo: GitInfo | null;
  stagedFiles: GitFileChange[] | null;
  theme: "dark" | "light";
  projectPath: string;
  commitMessage: string;
  onCommitMessage: (message: string) => void;
  onTab: (tab: "build" | "git" | "terminal") => void;
  onRun: (action: CommandAction) => void;
}) {
  const [confirmPush, setConfirmPush] = useState(false);
  const success = result && result.return_code === 0;
  const runPush = () => { setConfirmPush(false); onRun("push"); };

  return (
    <section className="output-panel">
      <div className="output-toolbar">
        <div className="output-tabs"><button className={tab === "build" ? "active" : ""} onClick={() => onTab("build")}>빌드 · 테스트</button><button className={tab === "git" ? "active" : ""} onClick={() => onTab("git")}>Git 결과</button><button className={tab === "terminal" ? "active" : ""} onClick={() => onTab("terminal")}>터미널</button></div>
        <div className="output-actions">
          {tab === "build"
            ? <><button disabled={!!busy} onClick={() => onRun("build")}>▷ 빌드</button><button disabled={!!busy} onClick={() => onRun("test")}>◇ 테스트</button></>
            : tab === "git" ? <><button disabled={!!busy} onClick={() => onRun("status")}>상태</button><button disabled={!!busy} onClick={() => onRun("diff")}>작업 트리 Diff</button><button className={stagedFiles !== null ? "active-action" : ""} disabled={!!busy} onClick={() => onRun("staged-diff")}>스테이징 Diff</button></> : null}
        </div>
      </div>
      {tab === "git" && <div className="git-controlbar">
        <div className="git-repository"><span className="branch-chip">⑂ {gitInfo?.branch ?? "브랜치 없음"}</span><span className="remote-name" title={gitInfo?.remote || "원격 저장소 없음"}>{repositoryName(gitInfo?.remote ?? "")}</span></div>
        <button disabled={!!busy || !gitInfo?.has_unstaged} onClick={() => onRun("stage")}>전체 스테이징</button>
        <button disabled={!!busy || !gitInfo?.has_staged} onClick={() => onRun("unstage")}>스테이징 해제</button>
        <div className="commit-box"><input aria-label="커밋 메시지" placeholder="커밋 메시지" value={commitMessage} onChange={(event) => onCommitMessage(event.target.value)} onKeyDown={(event) => event.key === "Enter" && commitMessage.trim() && onRun("commit")} /><button className="primary" disabled={!!busy || !gitInfo?.has_staged || !commitMessage.trim()} onClick={() => onRun("commit")}>커밋</button></div>
        <button className="push-button" disabled={!!busy || !gitInfo?.remote} onClick={() => setConfirmPush(true)}>Push</button>
      </div>}
      {tab === "terminal" ? <TerminalPanel projectPath={projectPath} /> : tab === "git" && stagedFiles !== null && !busy ? <GitDiffViewer files={stagedFiles} theme={theme} /> : <div className="terminal-output">
        {busy && <div className="running"><span className="pulse" />명령을 실행하고 있습니다…</div>}
        {!busy && result && <div className={`result-line ${success ? "success" : "failure"}`}><span>{success ? "✓" : "×"}</span>{success ? "명령 실행 성공" : `명령 실행 실패 (${result.return_code})`}<small>{result.duration.toFixed(2)}초</small></div>}
        <pre>{output(result)}</pre>
      </div>}
      {confirmPush && <div className="confirm-backdrop" role="presentation" onMouseDown={() => setConfirmPush(false)}>
        <div className="confirm-dialog" role="dialog" aria-modal="true" aria-labelledby="push-confirm-title" onMouseDown={(event) => event.stopPropagation()}>
          <span className="confirm-icon">↑</span><h3 id="push-confirm-title">원격 저장소로 Push할까요?</h3>
          <p>로컬 커밋이 다음 원격 저장소에 업로드됩니다. 실행 후에는 다른 사용자에게 변경사항이 공개될 수 있습니다.</p>
          <dl><div><dt>브랜치</dt><dd>{gitInfo?.branch}</dd></div><div><dt>원격</dt><dd>{gitInfo?.remote}</dd></div></dl>
          <div className="confirm-actions"><button onClick={() => setConfirmPush(false)}>취소</button><button className="confirm-push" onClick={runPush}>확인하고 Push</button></div>
        </div>
      </div>}
    </section>
  );
}
