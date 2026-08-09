import Editor, {DiffEditor} from "@monaco-editor/react";
import type {BeforeMount} from "@monaco-editor/react";
import type {ProposedChange} from "../types";
import {diffContentKey, revealFirstDiff} from "../utils/monacoDiff";

function language(path: string): string {
  const extension = path.split(".").pop()?.toLowerCase();
  return ({tsx: "typescript", ts: "typescript", jsx: "javascript", js: "javascript", py: "python", cs: "csharp", cpp: "cpp", h: "cpp", json: "json", css: "css", html: "html", md: "markdown", xml: "xml", xaml: "xml"} as Record<string, string>)[extension ?? ""] ?? "plaintext";
}

const configureThemes: BeforeMount = (monaco) => {
  monaco.editor.defineTheme("aura-dark", {
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
  monaco.editor.defineTheme("aura-light", {
    base: "vs",
    inherit: true,
    rules: [],
    colors: {
      "editor.background": "#ffffff",
      "editor.foreground": "#1f2937",
      "editorLineNumber.foreground": "#94a3b8",
      "editorLineNumber.activeForeground": "#334155",
      "editor.lineHighlightBackground": "#f3f6fa",
      "editor.selectionBackground": "#bfdbfe88",
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

export function EditorPanel({file, content, change, theme}: {file: string; content: string; change: ProposedChange | null; theme: "dark" | "light"}) {
  const path = change?.path ?? file;
  return (
    <section className="editor-panel">
      <div className="editor-tabbar">
        {path ? <div className="editor-tab"><span className={change ? "modified-dot" : "file-dot"}>{change ? "M" : "·"}</span><span className="truncate">{path}</span><span className="tab-close">×</span></div> : <span className="muted">열린 파일 없음</span>}
        {change && <div className="diff-legend"><span className="minus">−{change.deletions}</span><span className="plus">+{change.additions}</span></div>}
      </div>
      <div className={`editor-body ${change ? "diff-view" : ""}`}>
        {!path ? (
          <div className="editor-empty"><span>⌘</span><strong>코드 뷰어</strong><p>왼쪽 파일 탐색기에서 파일을 선택하세요.</p></div>
        ) : change ? (
          <>
            <div className="diff-column-headings" aria-hidden="true"><span className="before">− 변경 전</span><span className="after">+ 변경 후</span></div>
            <div className="diff-editor-wrap"><DiffEditor key={diffContentKey(path, change.original, change.modified)} beforeMount={configureThemes} onMount={revealFirstDiff} height="100%" original={change.original} modified={change.modified} language={language(path)} theme={theme === "light" ? "aura-light" : "aura-dark"} options={{readOnly: true, originalEditable: false, renderSideBySide: true, enableSplitViewResizing: true, renderIndicators: true, ignoreTrimWhitespace: false, diffWordWrap: "on", minimap: {enabled: false}, fontSize: 13, lineHeight: 20, padding: {top: 12}, automaticLayout: true, scrollBeyondLastLine: false}} /></div>
          </>
        ) : (
          <Editor beforeMount={configureThemes} height="100%" value={content} language={language(path)} theme={theme === "light" ? "aura-light" : "aura-dark"} options={{readOnly: true, minimap: {enabled: true}, fontSize: 13, padding: {top: 14}, automaticLayout: true, scrollBeyondLastLine: false}} />
        )}
      </div>
    </section>
  );
}
