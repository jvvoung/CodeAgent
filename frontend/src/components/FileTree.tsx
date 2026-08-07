import {useState} from "react";
import type {TreeNode} from "../types";

function icon(name: string): string {
  const extension = name.split(".").pop()?.toLowerCase();
  if (["ts", "tsx", "js", "jsx"].includes(extension ?? "")) return "TS";
  if (extension === "py") return "PY";
  if (["cs", "cpp", "h", "hpp"].includes(extension ?? "")) return "C#";
  if (["json", "yaml", "yml"].includes(extension ?? "")) return "{}";
  if (extension === "md") return "MD";
  return "·";
}

function NodeRow({node, selected, onOpen}: {node: TreeNode; selected: string; onOpen: (path: string) => void}) {
  const [expanded, setExpanded] = useState(true);
  if (node.type === "directory") {
    return (
      <li>
        <button className="tree-row directory" onClick={() => setExpanded((value) => !value)} aria-expanded={expanded}>
          <span className="chevron">{expanded ? "⌄" : "›"}</span><span className="folder">◆</span>{node.name}
        </button>
        {expanded && <FileTree nodes={node.children} selected={selected} onOpen={onOpen} />}
      </li>
    );
  }
  return (
    <li>
      <button className={`tree-row ${selected === node.path ? "active" : ""}`} onClick={() => onOpen(node.path)}>
        <span className="file-icon">{icon(node.name)}</span><span className="truncate">{node.name}</span>
      </button>
    </li>
  );
}

export function FileTree({nodes, selected, onOpen}: {nodes: TreeNode[]; selected: string; onOpen: (path: string) => void}) {
  return <ul className="file-tree">{nodes.map((node) => <NodeRow key={node.path} node={node} selected={selected} onOpen={onOpen} />)}</ul>;
}
