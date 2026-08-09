import {useEffect, useMemo, useState} from "react";
import {DiffEditor} from "@monaco-editor/react";
import type {BeforeMount} from "@monaco-editor/react";
import type {GitFileChange} from "../types";
import {diffContentKey, revealFirstDiff} from "../utils/monacoDiff";

function language(path: string): string {
  const extension = path.split(".").pop()?.toLowerCase();
  return ({tsx: "typescript", ts: "typescript", jsx: "javascript", js: "javascript", py: "python", cs: "csharp", cpp: "cpp", c: "c", h: "cpp", hpp: "cpp", json: "json", css: "css", html: "html", md: "markdown", xml: "xml", xaml: "xml", yml: "yaml", yaml: "yaml"} as Record<string, string>)[extension ?? ""] ?? "plaintext";
}

const configureTheme: BeforeMount = (monaco) => {
  monaco.editor.defineTheme("aura-git-diff", {
    base: "vs-dark",
    inherit: true,
    rules: [],
    colors: {
      "editor.background": "#090d14",
      "diffEditor.removedLineBackground": "#4a202899",
      "diffEditor.removedTextBackground": "#8b2e3e88",
      "diffEditor.insertedLineBackground": "#173f2a99",
      "diffEditor.insertedTextBackground": "#1f6f3b88",
      "diffEditor.diagonalFill": "#111823",
      "diffEditor.border": "#2b3749",
      "diffEditorOverview.removedForeground": "#ff7888",
      "diffEditorOverview.insertedForeground": "#69da91",
    },
  });
  monaco.editor.defineTheme("aura-git-diff-light", {
    base: "vs",
    inherit: true,
    rules: [],
    colors: {
      "editor.background": "#ffffff",
      "editor.foreground": "#1f2937",
      "editorLineNumber.foreground": "#94a3b8",
      "editorLineNumber.activeForeground": "#334155",
      "editor.lineHighlightBackground": "#f3f6fa",
      "diffEditor.removedLineBackground": "#ffe4e699",
      "diffEditor.removedTextBackground": "#fda4af88",
      "diffEditor.insertedLineBackground": "#dcfce799",
      "diffEditor.insertedTextBackground": "#86efac88",
      "diffEditor.diagonalFill": "#f1f5f9",
      "diffEditor.border": "#cbd5e1",
      "diffEditorOverview.removedForeground": "#dc2626",
      "diffEditorOverview.insertedForeground": "#15803d",
    },
  });
};

const statusLabel: Record<GitFileChange["status"], string> = {
  added: "추가",
  modified: "수정",
  deleted: "삭제",
  renamed: "이름 변경",
  copied: "복사",
};

export function GitDiffViewer({files, theme}: {files: GitFileChange[]; theme: "dark" | "light"}) {
  const [selectedPath, setSelectedPath] = useState(files[0]?.path ?? "");
  useEffect(() => setSelectedPath(files[0]?.path ?? ""), [files]);
  const selected = useMemo(() => files.find((file) => file.path === selectedPath) ?? files[0], [files, selectedPath]);

  if (!selected) {
    return <div className="git-diff-empty"><span>✓</span><strong>스테이징된 변경사항이 없습니다</strong><p>파일을 스테이징한 후 다시 확인해 주세요.</p></div>;
  }

  return <div className="git-diff-viewer">
    <aside className="git-file-changes">
      <div className="git-file-count">스테이징된 파일 <strong>{files.length}</strong></div>
      <div className="git-file-list">{files.map((file) => <button key={file.path} className={file.path === selected.path ? "active" : ""} onClick={() => setSelectedPath(file.path)}>
        <span className={`git-status-badge ${file.status}`}>{statusLabel[file.status]}</span>
        <span className="git-file-name" title={file.path}>{file.path}</span>
        <span className="git-file-stats"><b>+{file.additions}</b><i>−{file.deletions}</i></span>
      </button>)}</div>
    </aside>
    <section className="git-file-diff">
      <div className="git-diff-heading"><div><strong>{selected.path}</strong>{selected.old_path && <small>{selected.old_path}에서 이름 변경</small>}</div><span className={`git-status-text ${selected.status}`}>{statusLabel[selected.status]}</span></div>
      {selected.binary ? <div className="git-preview-message"><strong>바이너리 파일</strong><p>이 파일은 텍스트 코드 비교를 지원하지 않습니다.</p></div>
        : <><div className="git-diff-columns" aria-hidden="true"><span>− 변경 전</span><span>+ 변경 후</span></div>
          {selected.truncated && <div className="git-diff-warning">파일이 커서 앞부분만 표시합니다.</div>}
          <div className="git-monaco-diff"><DiffEditor key={diffContentKey(selected.path, selected.original, selected.modified)} beforeMount={configureTheme} onMount={revealFirstDiff} height="100%" original={selected.original} modified={selected.modified} language={language(selected.path)} theme={theme === "light" ? "aura-git-diff-light" : "aura-git-diff"} options={{readOnly: true, originalEditable: false, renderSideBySide: true, enableSplitViewResizing: true, renderIndicators: true, ignoreTrimWhitespace: false, diffWordWrap: "on", minimap: {enabled: false}, fontSize: 12, lineHeight: 19, padding: {top: 10}, automaticLayout: true, scrollBeyondLastLine: false}} /></div></>}
    </section>
  </div>;
}
