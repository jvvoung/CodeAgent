import {useEffect, useRef, useState} from "react";
import type {FormEvent, KeyboardEvent} from "react";
import {api, errorMessage} from "../api/client";
import type {TerminalResult, TerminalShell} from "../types";

type TerminalEntry = TerminalResult & {id: string; promptCwd: string};

const shellNames: Record<TerminalShell, string> = {
  cmd: "CMD",
  powershell: "PowerShell",
  "git-bash": "Git Bash",
};

export function TerminalPanel({projectPath}: {projectPath: string}) {
  const [shell, setShell] = useState<TerminalShell>(() => {
    const saved = localStorage.getItem("terminal.shell");
    return saved === "cmd" || saved === "powershell" || saved === "git-bash" ? saved : "powershell";
  });
  const [command, setCommand] = useState("");
  const [cwd, setCwd] = useState(projectPath);
  const [entries, setEntries] = useState<TerminalEntry[]>([]);
  const [busy, setBusy] = useState(false);
  const [historyIndex, setHistoryIndex] = useState(-1);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    localStorage.setItem("terminal.shell", shell);
  }, [shell]);
  useEffect(() => {
    setCwd(projectPath);
  }, [projectPath]);
  useEffect(() => {
    endRef.current?.scrollIntoView({block: "end"});
  }, [entries, busy]);

  const run = async (event: FormEvent) => {
    event.preventDefault();
    const value = command.trim();
    if (!value || !projectPath || busy) return;
    setCommand("");
    setHistoryIndex(-1);
    setBusy(true);
    const promptCwd = cwd || projectPath;
    try {
      const result = await api.terminal(shell, value, promptCwd);
      setCwd(result.cwd);
      setEntries((current) => [...current, {...result, promptCwd, id: crypto.randomUUID()}]);
    } catch (error) {
      setEntries((current) => [...current, {id: crypto.randomUUID(), shell, cwd: promptCwd, promptCwd, command: value, return_code: -1, stdout: "", stderr: errorMessage(error), duration: 0}]);
    } finally { setBusy(false); }
  };

  const navigateHistory = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "l" && event.ctrlKey) {
      event.preventDefault();
      setEntries([]);
      return;
    }
    if (event.key !== "ArrowUp" && event.key !== "ArrowDown") return;
    const commands = entries.map((entry) => entry.command);
    if (!commands.length) return;
    event.preventDefault();
    const next = event.key === "ArrowUp"
      ? Math.min(historyIndex + 1, commands.length - 1)
      : Math.max(historyIndex - 1, -1);
    setHistoryIndex(next);
    setCommand(next === -1 ? "" : commands[commands.length - 1 - next]);
  };

  return <div className="terminal-page">
    <div className="terminal-controls">
      <label><span>터미널</span><select aria-label="터미널 종류" value={shell} disabled={busy} onChange={(event) => setShell(event.target.value as TerminalShell)}>{Object.entries(shellNames).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
      <span className="terminal-cwd" title={cwd}>{cwd || "프로젝트를 먼저 열어주세요"}</span>
      <button disabled={!entries.length || busy} onClick={() => setEntries([])}>출력 지우기</button>
    </div>
    <div className="terminal-scroll">
      {!entries.length && !busy && <div className="terminal-welcome"><strong>{shellNames[shell]}</strong><span>현재 프로젝트 폴더에서 명령을 실행합니다.</span></div>}
      {entries.map((entry) => <div className="terminal-entry" key={entry.id}>
        <div className="terminal-command"><span>{shellNames[entry.shell]}</span><b>{entry.promptCwd}&gt;</b> {entry.command}</div>
        {entry.stdout && <pre>{entry.stdout}</pre>}
        {entry.stderr && <pre className="terminal-error">{entry.stderr}</pre>}
        <small className={entry.return_code === 0 ? "success" : "failure"}>종료 코드 {entry.return_code} · {entry.duration.toFixed(2)}초</small>
      </div>)}
      {busy && <div className="terminal-running"><span className="pulse" />명령을 실행하고 있습니다…</div>}
      <div ref={endRef} />
    </div>
    <form className="terminal-prompt" onSubmit={run}><span className="terminal-prompt-path" title={cwd}>{shell === "powershell" ? "PS " : ""}{cwd || "프로젝트 없음"}{shell === "git-bash" ? " $" : ">"}</span><input autoFocus aria-label="터미널 명령어" placeholder={projectPath ? "명령어 입력" : "프로젝트를 먼저 열어주세요"} value={command} disabled={!projectPath || busy} onChange={(event) => setCommand(event.target.value)} onKeyDown={navigateHistory} /><button className="primary" disabled={!projectPath || busy || !command.trim()} type="submit">실행</button></form>
  </div>;
}
