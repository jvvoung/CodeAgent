import {useEffect, useMemo, useRef, useState} from "react";
import type {CSSProperties, KeyboardEvent as ReactKeyboardEvent, PointerEvent as ReactPointerEvent} from "react";
import {api, errorMessage} from "./api/client";
import {ChangesPanel} from "./components/ChangesPanel";
import {ChatPanel, toolLabel} from "./components/ChatPanel";
import {EditorPanel} from "./components/EditorPanel";
import {FileTree} from "./components/FileTree";
import {OutputPanel} from "./components/OutputPanel";
import type {AgentEvent, ChatEntry, CommandAction, CommandResult, GitFileChange, GitInfo, OllamaModel, ProposedChange, TreeNode} from "./types";
import {repositoryName} from "./utils/git";

const id = () => crypto.randomUUID();
const clamp = (value: number, minimum: number, maximum: number) => Math.min(maximum, Math.max(minimum, value));
const savedSize = (key: string, fallback: number) => {
  const value = Number(localStorage.getItem(key));
  return Number.isFinite(value) && value > 0 ? value : fallback;
};

function defaultSourceFile(nodes: TreeNode[]): string {
  const files: string[] = [];
  const collect = (items: TreeNode[]) => items.forEach((item) => item.type === "file" ? files.push(item.path) : collect(item.children));
  collect(nodes);
  const preferred = ["MainWindow.xaml", "App.tsx", "main.tsx", "main.py", "Program.cs", "README.md", "package.json", "pyproject.toml"];
  for (const name of preferred) {
    const match = files.find((path) => path.split("/").pop() === name);
    if (match) return match;
  }
  const sourceExtensions = /\.(tsx?|jsx?|py|cs|cpp|c|h|hpp|xaml|xml|html|css|json|md)$/i;
  return files.find((path) => sourceExtensions.test(path)) ?? files[0] ?? "";
}

function treeHasFile(nodes: TreeNode[], path: string): boolean {
  return nodes.some((node) => node.type === "file" ? node.path === path : treeHasFile(node.children, path));
}

type ResizeTarget = "explorer" | "side" | "output";

export default function App() {
  const [theme, setTheme] = useState<"dark" | "light">(() => localStorage.getItem("aura.theme") === "light" ? "light" : "dark");
  const [root, setRoot] = useState(() => localStorage.getItem("projectRoot") ?? "");
  const [projectName, setProjectName] = useState("");
  const [tree, setTree] = useState<TreeNode[]>([]);
  const [file, setFile] = useState("");
  const [content, setContent] = useState("");
  const [models, setModels] = useState<OllamaModel[]>([]);
  const [model, setModel] = useState("");
  const [ollamaError, setOllamaError] = useState("");
  const [backendWarning, setBackendWarning] = useState("");
  const [prompt, setPrompt] = useState("");
  const [messages, setMessages] = useState<ChatEntry[]>([]);
  const [changes, setChanges] = useState<ProposedChange[]>([]);
  const [selected, setSelected] = useState<ProposedChange | null>(null);
  const [agentBusy, setAgentBusy] = useState(false);
  const [commandBusy, setCommandBusy] = useState("");
  const [outputTab, setOutputTab] = useState<"build" | "git" | "terminal">("build");
  const [sideTab, setSideTab] = useState<"chat" | "changes">("chat");
  const [buildResult, setBuildResult] = useState<CommandResult | null>(null);
  const [gitResult, setGitResult] = useState<CommandResult | null>(null);
  const [stagedFiles, setStagedFiles] = useState<GitFileChange[] | null>(null);
  const [gitInfo, setGitInfo] = useState<GitInfo | null>(null);
  const [branchBusy, setBranchBusy] = useState(false);
  const [agentPushRequest, setAgentPushRequest] = useState<{branch: string; remote: string} | null>(null);
  const [commitMessage, setCommitMessage] = useState("");
  const [notice, setNotice] = useState("");
  const [explorerWidth, setExplorerWidth] = useState(() => savedSize("layout.explorerWidth", 250));
  const [sideWidth, setSideWidth] = useState(() => savedSize("layout.sideWidth", 390));
  const [outputHeight, setOutputHeight] = useState(() => savedSize("layout.outputHeight", 170));
  const agentController = useRef<AbortController | null>(null);

  const output = outputTab === "build" ? buildResult : gitResult;
  const projectOpen = !!projectName;
  const fileCount = useMemo(() => {
    const count = (nodes: TreeNode[]): number => nodes.reduce((sum, node) => sum + (node.type === "file" ? 1 : count(node.children)), 0);
    return count(tree);
  }, [tree]);

  useEffect(() => {
    api.health().then((health) => {
      setBackendWarning(health.agent_core === "persistent-ollama-tools-v1" ? "" : "백엔드가 이전 에이전트 코어로 실행 중입니다. 백엔드 PowerShell을 종료하고 다시 실행해 주세요.");
    }).catch(() => setBackendWarning("백엔드 서버(localhost:8000)에 연결할 수 없습니다."));
    api.models().then((data) => {
      setModels(data.models);
      setModel((current) => current && data.models.some((item) => item.name === current && item.supports_tools)
        ? current
        : data.models.find((item) => item.supports_tools)?.name ?? "");
      setOllamaError(data.error ?? "");
    }).catch((error) => setOllamaError(errorMessage(error)));
  }, []);

  useEffect(() => localStorage.setItem("layout.explorerWidth", String(explorerWidth)), [explorerWidth]);
  useEffect(() => localStorage.setItem("layout.sideWidth", String(sideWidth)), [sideWidth]);
  useEffect(() => localStorage.setItem("layout.outputHeight", String(outputHeight)), [outputHeight]);
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("aura.theme", theme);
  }, [theme]);
  useEffect(() => () => agentController.current?.abort(), []);
  useEffect(() => {
    if (!projectOpen) return;
    let active = true;
    const synchronize = () => api.changes().then((next) => {
      if (!active) return;
      setChanges(next);
      setSelected((current) => next.find((item) => item.path === current?.path) ?? next[0] ?? null);
    }).catch(() => undefined);
    synchronize();
    const timer = window.setInterval(synchronize, 2000);
    return () => { active = false; window.clearInterval(timer); };
  }, [projectOpen]);

  const flash = (message: string) => {
    setNotice(message);
    window.setTimeout(() => setNotice(""), 2600);
  };

  const refreshChanges = async (preferredPath?: string) => {
    const next = await api.changes();
    setChanges(next);
    setSelected(next.find((change) => change.path === preferredPath) ?? next[0] ?? null);
    return next;
  };

  const openProject = async () => {
    if (!root.trim()) return;
    try {
      const data = await api.openProject(root.trim());
      setRoot(data.path);
      setProjectName(data.name);
      setTree(data.tree);
      const initialFile = defaultSourceFile(data.tree);
      setFile(initialFile);
      setContent(initialFile ? await api.file(initialFile) : "");
      setChanges([]); setSelected(null);
      setStagedFiles(null);
      setAgentPushRequest(null);
      localStorage.setItem("projectRoot", data.path);
      try {
        const history = await api.conversation();
        setMessages(history.length
          ? history.map((item) => ({id: id(), role: item.role === "user" ? "user" as const : "agent" as const, content: item.content}))
          : [{id: id(), role: "status", content: `프로젝트 분석 완료 · ${data.name}`}]);
      } catch {
        setMessages([{id: id(), role: "status", content: `프로젝트 분석 완료 · ${data.name}`}]);
      }
      try { setGitInfo(await api.gitInfo()); } catch { setGitInfo(null); }
      flash("프로젝트를 열었습니다.");
    } catch (error) { flash(errorMessage(error)); }
  };

  const openFile = async (path: string) => {
    try {
      setFile(path); setContent(await api.file(path)); setSelected(null);
    } catch (error) { flash(errorMessage(error)); }
  };

  const switchBranch = async (branch: string) => {
    if (!projectOpen || !gitInfo || branch === gitInfo.branch || branchBusy || agentBusy) return;
    setBranchBusy(true);
    setOutputTab("git");
    try {
      const data = await api.checkoutBranch(branch);
      setGitInfo(data.git);
      setGitResult(data.result);
      setTree(data.tree);
      setChanges([]);
      setSelected(null);
      setStagedFiles(null);
      setAgentPushRequest(null);
      const nextFile = file && treeHasFile(data.tree, file) ? file : defaultSourceFile(data.tree);
      setFile(nextFile);
      setContent(nextFile ? await api.file(nextFile) : "");
      flash(`${data.git.branch} 브랜치로 전환했습니다.`);
    } catch (error) {
      flash(errorMessage(error));
    } finally {
      setBranchBusy(false);
    }
  };

  const runAgentRequest = async (request: string) => {
    if (!request || !model || !projectOpen || agentBusy) return;
    const controller = new AbortController();
    const deferredErrors: AgentEvent[] = [];
    agentController.current = controller;
    setPrompt(""); setAgentBusy(true);
    setMessages((current) => [...current, {id: id(), role: "user", content: request}]);
    try {
      const response = await api.chatStream(request, model, (event) => {
        if (event.status === "failed") {
          deferredErrors.push(event);
          return;
        }
        setMessages((current) => [...current, {id: id(), role: "status", content: toolLabel(event.tool, event.status, event.detail)}]);
      }, controller.signal);
      if (response.git_result) {
        setGitResult(response.git_result);
        setStagedFiles(null);
        setOutputTab("git");
      }
      if (response.git_changed || response.pending_git_action) {
        try { setGitInfo(await api.gitInfo()); } catch { setGitInfo(null); }
      }
      if (response.project_changed) {
        const nextTree = await api.tree();
        setTree(nextTree);
        setChanges([]);
        setSelected(null);
        const nextFile = file && treeHasFile(nextTree, file) ? file : defaultSourceFile(nextTree);
        setFile(nextFile);
        setContent(nextFile ? await api.file(nextFile) : "");
      }
      if (response.pending_git_action?.type === "push") {
        setAgentPushRequest({branch: response.pending_git_action.branch, remote: response.pending_git_action.remote});
      }
      const nextChanges = await refreshChanges();
      if (nextChanges.length) setSideTab("changes");
      if (!nextChanges.length && response.relevant_files?.length) await openFile(response.relevant_files[0]);
      const errorSummary = !nextChanges.length && deferredErrors.length
        ? [{
            id: id(),
            role: "error" as const,
            content: `변경안 생성 과정에서 도구 오류 ${deferredErrors.length}건이 발생했습니다. ${toolLabel(deferredErrors[deferredErrors.length - 1].tool, "failed")}`,
          }]
        : [];
      setMessages((current) => [
        ...current,
        ...errorSummary,
        {id: id(), role: "agent", content: response.message?.trim() || "작업을 완료했습니다. 변경사항을 확인해 주세요."},
      ]);
    } catch (error) {
      if (controller.signal.aborted) {
        setMessages((current) => [...current, {id: id(), role: "status", content: "AI 작업을 사용자가 중지했습니다"}]);
      } else {
        const message = errorMessage(error).trim() || "AI 응답을 받지 못했습니다. 잠시 후 다시 시도해 주세요.";
        setMessages((current) => [
          ...current,
          ...(deferredErrors.length ? [{
            id: id(), role: "error" as const,
            content: `도구 오류 ${deferredErrors.length}건이 발생했습니다. ${toolLabel(deferredErrors[deferredErrors.length - 1].tool, "failed")}`,
          }] : []),
          {id: id(), role: "error", content: message},
        ]);
      }
    } finally {
      if (agentController.current === controller) agentController.current = null;
      setAgentBusy(false);
    }
  };

  const askAgent = () => runAgentRequest(prompt.trim());

  const retryChange = async (change: ProposedChange) => {
    const request = change.retry_request?.trim();
    if (!request || agentBusy) return;
    const failedPaths = changes
      .filter((item) => item.validation_status === "failed" && item.retry_request === change.retry_request)
      .map((item) => item.path);
    try {
      await api.reject(failedPaths.length ? failedPaths : [change.path]);
      await refreshChanges();
      setSideTab("chat");
      await runAgentRequest(request);
    } catch (error) {
      flash(errorMessage(error));
    }
  };

  const stopAgent = () => agentController.current?.abort();

  const clearConversation = async () => {
    if (!projectOpen || !window.confirm("이 프로젝트의 저장된 대화 기억을 모두 지울까요?")) return;
    try {
      await api.clearConversation();
      setMessages([{id: id(), role: "status", content: `대화 기억 초기화 완료 · ${projectName}`}]);
      flash("저장된 대화 기억을 지웠습니다.");
    } catch (error) { flash(errorMessage(error)); }
  };

  const changeDecision = async (action: "apply" | "reject", paths: string[] | null) => {
    try {
      const selectedChanges = paths === null ? changes : changes.filter((item) => paths.includes(item.path));
      const needsConfirmation = action === "apply" && selectedChanges.some((item) => ["failed", "scope_review_incomplete"].includes(item.validation_status ?? ""));
      if (needsConfirmation && !window.confirm("이 변경안은 자동 검증 또는 범위 검토를 완전히 통과하지 못했습니다. Diff를 확인했으며 그래도 프로젝트에 적용할까요?")) return;
      if (action === "apply") await api.apply(paths, needsConfirmation);
      else await api.reject(paths);
      const nextTree = action === "apply" ? await api.tree() : tree;
      if (action === "apply") setTree(nextTree);
      await refreshChanges();
      if (action === "apply" && file && (paths === null || paths.includes(file))) setContent(await api.file(file));
      setMessages((current) => [...current, {id: id(), role: "status", content: `${paths?.length ?? changes.length}개 파일 변경안을 ${action === "apply" ? "적용했습니다" : "폐기했습니다"}.`}]);
    } catch (error) { flash(errorMessage(error)); }
  };

  const runCommand = async (action: CommandAction) => {
    if (!projectOpen) { flash("먼저 프로젝트를 열어주세요."); return; }
    const isGit = action !== "build" && action !== "test";
    setOutputTab(isGit ? "git" : "build"); setCommandBusy(action);
    if (isGit && action !== "staged-diff") setStagedFiles(null);
    try {
      let result: CommandResult;
      if (!isGit) result = await api.run(action);
      else if (action === "staged-diff") {
        const files = await api.stagedChanges();
        setStagedFiles(files);
        result = {command: "git diff --cached", return_code: 0, stdout: "", stderr: "", duration: 0};
      }
      else if (action === "status" || action === "diff") result = await api.git(action);
      else result = await api.gitAction(action, action === "commit" ? commitMessage : undefined);
      if (isGit) {
        setGitResult(result);
        if (action === "commit" && result.return_code === 0) setCommitMessage("");
        try { setGitInfo(await api.gitInfo()); } catch { setGitInfo(null); }
      } else setBuildResult(result);
    } catch (error) {
      const failed: CommandResult = {command: action, return_code: -1, stdout: "", stderr: errorMessage(error), duration: 0};
      if (isGit) setGitResult(failed); else setBuildResult(failed);
    } finally { setCommandBusy(""); }
  };

  const resizeBy = (target: ResizeTarget, delta: number) => {
    if (target === "explorer") setExplorerWidth((value) => clamp(value + delta, 180, 520));
    if (target === "side") setSideWidth((value) => clamp(value + delta, 300, 680));
    if (target === "output") setOutputHeight((value) => clamp(value + delta, 96, Math.max(160, window.innerHeight - 300)));
  };

  const beginResize = (target: ResizeTarget, event: ReactPointerEvent<HTMLDivElement>) => {
    event.preventDefault();
    const startX = event.clientX;
    const startY = event.clientY;
    const initial = target === "explorer" ? explorerWidth : target === "side" ? sideWidth : outputHeight;
    const move = (moveEvent: PointerEvent) => {
      if (target === "explorer") setExplorerWidth(clamp(initial + moveEvent.clientX - startX, 180, 520));
      if (target === "side") setSideWidth(clamp(initial - moveEvent.clientX + startX, 300, 680));
      if (target === "output") setOutputHeight(clamp(initial - moveEvent.clientY + startY, 96, Math.max(160, window.innerHeight - 300)));
    };
    const finish = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", finish);
      document.body.classList.remove("resizing");
      document.body.style.cursor = "";
    };
    document.body.classList.add("resizing");
    document.body.style.cursor = target === "output" ? "row-resize" : "col-resize";
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", finish, {once: true});
  };

  const resizeWithKeyboard = (target: ResizeTarget, event: ReactKeyboardEvent<HTMLDivElement>) => {
    if (target === "output" && (event.key === "ArrowUp" || event.key === "ArrowDown")) {
      event.preventDefault(); resizeBy(target, event.key === "ArrowUp" ? 24 : -24);
    }
    if (target !== "output" && (event.key === "ArrowLeft" || event.key === "ArrowRight")) {
      event.preventDefault();
      const direction = event.key === "ArrowRight" ? 24 : -24;
      resizeBy(target, target === "side" ? -direction : direction);
    }
  };

  const layoutStyle = {
    "--explorer-width": `${explorerWidth}px`,
    "--side-width": `${sideWidth}px`,
    "--output-height": `${outputHeight}px`,
  } as CSSProperties;

  return (
    <main className="app-shell" style={layoutStyle}>
      <header className="topbar">
        <div className="brand"><strong className="brand-wordmark">AURA</strong><button className="theme-orb" aria-label={theme === "dark" ? "화이트 모드로 변경" : "다크 모드로 변경"} title={theme === "dark" ? "화이트 모드" : "다크 모드"} aria-pressed={theme === "light"} onClick={() => setTheme((current) => current === "dark" ? "light" : "dark")}><span /></button></div>
        <div className="project-picker"><span className={`connection-dot ${projectOpen ? "online" : ""}`} /><input aria-label="프로젝트 폴더 경로" placeholder="프로젝트 폴더 경로를 입력하세요" value={root} onChange={(event) => setRoot(event.target.value)} onKeyDown={(event) => event.key === "Enter" && openProject()} /><button className="primary" onClick={openProject}>프로젝트 열기</button></div>
        <div className="git-context" aria-label="Git 저장소 및 브랜치">
          <div className="git-context-field repository-field"><span>깃 저장소</span><strong title={gitInfo?.remote || "Git 저장소 없음"}>{repositoryName(gitInfo?.remote ?? "")}</strong></div>
          <label className="git-context-field branch-field"><span>깃 브랜치</span><select aria-label="Git 브랜치 선택" value={gitInfo?.branch ?? ""} disabled={!gitInfo || branchBusy || agentBusy} onChange={(event) => switchBranch(event.target.value)}><option value="">브랜치 없음</option>{gitInfo?.branches.map((branch) => <option key={branch} value={branch}>{branch}</option>)}</select>{branchBusy && <i className="branch-spinner" aria-label="브랜치 전환 중" />}</label>
        </div>
        <div className="model-picker"><label>모델</label><select aria-label="Ollama 모델" value={model} disabled={agentBusy} onChange={(event) => setModel(event.target.value)}><option value="">도구 지원 모델 없음</option>{models.map((item) => <option key={item.name} value={item.name} disabled={!item.supports_tools}>{item.name}{item.supports_tools ? "" : " · 도구 미지원"}</option>)}</select><span className={`model-state ${models.length ? "ready" : ""}`}><i />{models.length ? "연결됨" : "오프라인"}</span></div>
      </header>
      {backendWarning && <div className="service-warning">{backendWarning}</div>}
      {ollamaError && <div className="service-warning">Ollama에 연결할 수 없습니다. AI 기능을 사용하려면 Ollama를 실행해 주세요.</div>}
      {notice && <div className="toast">{notice}</div>}
      <div className="ide-grid">
        <aside className="explorer-panel">
          <div className="panel-title"><span>파일 탐색기</span><span className="panel-hint">{fileCount ? `${fileCount}개 파일` : "파일 없음"}</span></div>
          {projectOpen ? <><div className="project-heading"><span>⌄</span>{projectName}</div><FileTree nodes={tree} selected={file} onOpen={openFile} /></> : <div className="aside-empty"><span className="empty-icon">⌗</span><strong>열린 프로젝트가 없습니다</strong><p>상단에 로컬 프로젝트 경로를 입력해 주세요.</p></div>}
        </aside>
        <div className="resize-handle vertical" role="separator" aria-label="파일 탐색기 너비 조절" aria-orientation="vertical" tabIndex={0} onPointerDown={(event) => beginResize("explorer", event)} onKeyDown={(event) => resizeWithKeyboard("explorer", event)} />
        <div className="editor-column"><EditorPanel file={file} content={content} change={selected} theme={theme} /></div>
        <div className="resize-handle vertical" role="separator" aria-label="오른쪽 패널 너비 조절" aria-orientation="vertical" tabIndex={0} onPointerDown={(event) => beginResize("side", event)} onKeyDown={(event) => resizeWithKeyboard("side", event)} />
        <aside className="side-panel">
          <div className="side-tabs" role="tablist" aria-label="에이전트 패널">
            <button role="tab" aria-selected={sideTab === "changes"} className={`${sideTab === "changes" ? "active" : ""} ${changes.length ? "has-updates" : ""}`} onClick={() => setSideTab("changes")}>
              변경 제안 <span className="tab-count">{changes.length}</span>
            </button>
            <button role="tab" aria-selected={sideTab === "chat"} className={sideTab === "chat" ? "active" : ""} onClick={() => setSideTab("chat")}>AI 채팅</button>
          </div>
          <div className="side-content">
            {sideTab === "chat"
              ? <ChatPanel messages={messages} prompt={prompt} busy={agentBusy} disabled={!projectOpen || !model} showHeader={false} onPrompt={setPrompt} onSubmit={askAgent} onStop={stopAgent} onClear={clearConversation} />
              : <ChangesPanel changes={changes} selected={selected} busy={agentBusy} showHeader={false} onSelect={setSelected} onApply={(paths) => changeDecision("apply", paths)} onReject={(paths) => changeDecision("reject", paths)} onRetry={retryChange} />}
          </div>
        </aside>
      </div>
      <div className="resize-handle horizontal" role="separator" aria-label="결과 패널 높이 조절" aria-orientation="horizontal" tabIndex={0} onPointerDown={(event) => beginResize("output", event)} onKeyDown={(event) => resizeWithKeyboard("output", event)} />
      <OutputPanel tab={outputTab} result={output} busy={commandBusy} gitInfo={gitInfo} stagedFiles={stagedFiles} theme={theme} projectPath={projectOpen ? root : ""} commitMessage={commitMessage} onCommitMessage={setCommitMessage} onTab={setOutputTab} onRun={runCommand} />
      {agentPushRequest && <div className="confirm-backdrop" role="presentation" onMouseDown={() => setAgentPushRequest(null)}>
        <div className="confirm-dialog" role="dialog" aria-modal="true" aria-labelledby="agent-push-confirm-title" onMouseDown={(event) => event.stopPropagation()}>
          <span className="confirm-icon">↑</span><h3 id="agent-push-confirm-title">에이전트의 Push 요청을 실행할까요?</h3>
          <p>에이전트는 사용자 확인 없이 Push할 수 없습니다. 아래 대상이 맞는지 확인한 후 실행해 주세요.</p>
          <dl><div><dt>브랜치</dt><dd>{agentPushRequest.branch}</dd></div><div><dt>원격</dt><dd>{agentPushRequest.remote}</dd></div></dl>
          <div className="confirm-actions"><button onClick={() => setAgentPushRequest(null)}>취소</button><button className="confirm-push" disabled={!!commandBusy} onClick={() => { setAgentPushRequest(null); runCommand("push"); }}>확인하고 Push</button></div>
        </div>
      </div>}
      <footer className="statusbar"><span><i className={projectOpen ? "ok" : ""} />{projectOpen ? projectName : "프로젝트 없음"}</span><span>Ollama {models.length ? "연결됨" : "오프라인"}</span><span>대기 중인 변경 {changes.length}개</span><span className="spacer" /><span>로컬 전용</span><span>UTF-8</span></footer>
    </main>
  );
}
