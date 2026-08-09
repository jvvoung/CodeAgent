import type {DiffOnMount} from "@monaco-editor/react";

export const revealFirstDiff: DiffOnMount = (editor, monaco) => {
  let revealed = false;
  const reveal = () => {
    if (revealed) return;
    const first = editor.getLineChanges()?.[0];
    if (!first) return;
    revealed = true;
    const originalLine = Math.max(1, first.originalStartLineNumber || first.originalEndLineNumber);
    const modifiedLine = Math.max(1, first.modifiedStartLineNumber || first.modifiedEndLineNumber);
    editor.getOriginalEditor().revealLineInCenter(originalLine, monaco.editor.ScrollType.Immediate);
    editor.getModifiedEditor().revealLineInCenter(modifiedLine, monaco.editor.ScrollType.Immediate);
  };
  editor.onDidUpdateDiff(reveal);
  window.requestAnimationFrame(reveal);
};

export function diffContentKey(path: string, original: string, modified: string): string {
  let hash = 2166136261;
  const content = `${path}\0${original}\0${modified}`;
  for (let index = 0; index < content.length; index += 1) {
    hash ^= content.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return `${path}:${hash >>> 0}`;
}
