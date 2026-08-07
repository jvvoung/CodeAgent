import {useEffect, useMemo, useRef, useState} from "react";
import type {CSSProperties, KeyboardEvent as ReactKeyboardEvent, PointerEvent as ReactPointerEvent} from "react";
import {api, errorMessage} from "./api/client";
import {ChangesPanel} from "./components/ChangesPanel";
import {ChatPanel, toolLabel} from "./components/ChatPanel";
import {EditorPanel} from "./components/EditorPanel";
import {FileTree} from "./components/FileTree";
import {OutputPanel} from "./components/OutputPanel";
import type {ChatEntry, CommandResult, OllamaModel, ProposedChange, TreeNode} from "./types";

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

type ResizeTarget = "explorer" | "side" | "output";

export default function App() {
  const [root, setRoot] = useState(() => localStorage.getItem("projectRoot") ?? "");
  const [projectName, setProjectName] = useState("");
  const [tree, setTree] = useState<TreeNode[]>([]);
  const [file, setFile] = useState("");
  const [content, setContent] = useState("");
  const [models, setModels] = useState<OllamaModel[]>([]);
  const [model, setModel] = useState("");
  const [ollamaError, setOllamaError] = useState("");
  const [prompt, setPrompt] = useState("");
  const [messages, setMessages] = useState<ChatEntry[]>([]);
  const [changes, setChanges] = useState<ProposedChange[]>([]);
  const [selected, setSelected] = useState<ProposedChange | null>(null);
  const [agentBusy, setAgentBusy] = useState(false);
  const [commandBusy, setCommandBusy] = useState("");
  const [outputTab, setOutputTab] = useState<"build" | "git">("build");
  const [sideTab, setSideTab] = useState<"chat" | "changes">("chat");
  const [buildResult, setBuildResult] = useState<CommandResult | null>(null);
  const [gitResult, setGitResult] = useState<CommandResult | null>(null);
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
  useEffect(() => () => agentController.current?.abort(), []);

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
      localStorage.setItem("projectRoot", data.path);
      setMessages([{id: id(), role: "status", content: `프로젝트 분석 완료 · ${data.name}`}]);
      flash("프로젝트를 열었습니다.");
    } catch (error) { flash(errorMessage(error)); }
  };

  const openFile = async (path: string) => {
    try {
      setFile(path); setContent(await api.file(path)); setSelected(null);
    } catch (error) { flash(errorMessage(error)); }
  };

  const askAgent = async () => {
    const request = prompt.trim();
    if (!request || !model || !projectOpen || agentBusy) return;
    const controller = new AbortController();
    agentController.current = controller;
    setPrompt(""); setAgentBusy(true);
    setMessages((current) => [...current, {id: id(), role: "user", content: request}]);
    try {
      const response = await api.chatStream(request, model, (event) => {
        setMessages((current) => [...current, {id: id(), role: event.status === "failed" ? "error" : "status", content: toolLabel(event.tool, event.status, event.detail)}]);
      }, controller.signal);
      setMessages((current) => [...current, {id: id(), role: "agent", content: response.message?.trim() || "작업을 완료했습니다. 변경사항을 확인해 주세요."}]);
      const nextChanges = await refreshChanges();
      if (nextChanges.length) setSideTab("changes");
      if (!nextChanges.length && response.relevant_files?.length) await openFile(response.relevant_files[0]);
    } catch (error) {
      if (controller.signal.aborted) {
        setMessages((current) => [...current, {id: id(), role: "status", content: "AI 작업을 사용자가 중지했습니다"}]);
      } else {
        const message = errorMessage(error).trim() || "AI 응답을 받지 못했습니다. 잠시 후 다시 시도해 주세요.";
        setMessages((current) => [...current, {id: id(), role: "error", content: message}]);
      }
    } finally {
      if (agentController.current === controller) agentController.current = null;
      setAgentBusy(false);
    }
  };

  const stopAgent = () => agentController.current?.abort();

  const changeDecision = async (action: "apply" | "reject", paths: string[] | null) => {
    try {
      await api[action](paths);
      const nextTree = action === "apply" ? await api.tree() : tree;
      if (action === "apply") setTree(nextTree);
      await refreshChanges();
      if (action === "apply" && file && (paths === null || paths.includes(file))) setContent(await api.file(file));
      setMessages((current) => [...current, {id: id(), role: "status", content: `${paths?.length ?? changes.length}개 파일 변경안을 ${action === "apply" ? "적용했습니다" : "폐기했습니다"}.`}]);
    } catch (error) { flash(errorMessage(error)); }
  };

  const runCommand = async (action: "build" | "test" | "status" | "diff") => {
    if (!projectOpen) { flash("먼저 프로젝트를 열어주세요."); return; }
    const isGit = action === "status" || action === "diff";
    setOutputTab(isGit ? "git" : "build"); setCommandBusy(action);
    try {
      const result = isGit ? await api.git(action) : await api.run(action);
      if (isGit) setGitResult(result); else setBuildResult(result);
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
        <div className="brand"><strong className="brand-wordmark">AURA</strong></div>
        <div className="project-picker"><span className={`connection-dot ${projectOpen ? "online" : ""}`} /><input aria-label="프로젝트 폴더 경로" placeholder="프로젝트 폴더 경로를 입력하세요" value={root} onChange={(event) => setRoot(event.target.value)} onKeyDown={(event) => event.key === "Enter" && openProject()} /><button className="primary" onClick={openProject}>프로젝트 열기</button></div>
        <div className="model-picker"><label>모델</label><select aria-label="Ollama 모델" value={model} disabled={agentBusy} onChange={(event) => setModel(event.target.value)}><option value="">도구 지원 모델 없음</option>{models.map((item) => <option key={item.name} value={item.name} disabled={!item.supports_tools}>{item.name}{item.supports_tools ? "" : " · 도구 미지원"}</option>)}</select><span className={`model-state ${models.length ? "ready" : ""}`}><i />{models.length ? "연결됨" : "오프라인"}</span></div>
      </header>
      {ollamaError && <div className="service-warning">Ollama에 연결할 수 없습니다. AI 기능을 사용하려면 Ollama를 실행해 주세요.</div>}
      {notice && <div className="toast">{notice}</div>}
      <div className="ide-grid">
        <aside className="explorer-panel">
          <div className="panel-title"><span>파일 탐색기</span><span className="panel-hint">{fileCount ? `${fileCount}개 파일` : "파일 없음"}</span></div>
          {projectOpen ? <><div className="project-heading"><span>⌄</span>{projectName}</div><FileTree nodes={tree} selected={file} onOpen={openFile} /></> : <div className="aside-empty"><span className="empty-icon">⌗</span><strong>열린 프로젝트가 없습니다</strong><p>상단에 로컬 프로젝트 경로를 입력해 주세요.</p></div>}
        </aside>
        <div className="resize-handle vertical" role="separator" aria-label="파일 탐색기 너비 조절" aria-orientation="vertical" tabIndex={0} onPointerDown={(event) => beginResize("explorer", event)} onKeyDown={(event) => resizeWithKeyboard("explorer", event)} />
        <div className="editor-column"><EditorPanel file={file} content={content} change={selected} /></div>
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
              ? <ChatPanel messages={messages} prompt={prompt} busy={agentBusy} disabled={!projectOpen || !model} showHeader={false} onPrompt={setPrompt} onSubmit={askAgent} onStop={stopAgent} />
              : <ChangesPanel changes={changes} selected={selected} busy={agentBusy} showHeader={false} onSelect={setSelected} onApply={(paths) => changeDecision("apply", paths)} onReject={(paths) => changeDecision("reject", paths)} />}
          </div>
        </aside>
      </div>
      <div className="resize-handle horizontal" role="separator" aria-label="결과 패널 높이 조절" aria-orientation="horizontal" tabIndex={0} onPointerDown={(event) => beginResize("output", event)} onKeyDown={(event) => resizeWithKeyboard("output", event)} />
      <OutputPanel tab={outputTab} result={output} busy={commandBusy} onTab={setOutputTab} onRun={runCommand} />
      <footer className="statusbar"><span><i className={projectOpen ? "ok" : ""} />{projectOpen ? projectName : "프로젝트 없음"}</span><span>Ollama {models.length ? "연결됨" : "오프라인"}</span><span>대기 중인 변경 {changes.length}개</span><span className="spacer" /><span>로컬 전용</span><span>UTF-8</span></footer>
    </main>
  );
}
