import axios, {AxiosError} from "axios";
import type {AgentEvent, AgentResponse, CommandResult, OllamaModel, ProposedChange, TreeNode} from "../types";

const API_BASE = "http://localhost:8000/api";
const http = axios.create({baseURL: API_BASE, timeout: 310_000});

export function errorMessage(error: unknown): string {
  if (error instanceof AxiosError) {
    const detail = error.response?.data?.detail;
    if (typeof detail === "string") return detail;
    if (error.code === "ECONNABORTED") return "요청 시간이 초과되었습니다.";
    if (!error.response) return "백엔드 서버(localhost:8000)에 연결할 수 없습니다.";
    return error.message;
  }
  return error instanceof Error ? error.message : String(error);
}

export const api = {
  async models(): Promise<{models: OllamaModel[]; error?: string}> {
    return (await http.get("/ollama/models")).data;
  },
  async openProject(path: string): Promise<{path: string; name: string; tree: TreeNode[]}> {
    return (await http.post("/project/open", {path})).data;
  },
  async tree(): Promise<TreeNode[]> {
    return (await http.get("/project/tree")).data.tree;
  },
  async file(path: string): Promise<string> {
    return (await http.get("/file", {params: {path}})).data.content;
  },
  async chat(message: string, model: string): Promise<{message: string; events: AgentEvent[]}> {
    return (await http.post("/agent/chat", {message, model})).data;
  },
  async chatStream(message: string, model: string, onStatus: (event: AgentEvent) => void, signal?: AbortSignal): Promise<AgentResponse> {
    const response = await fetch(`${API_BASE}/agent/chat/stream`, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({message, model}),
      signal,
    });
    if (!response.ok) {
      const body = await response.json().catch(() => null) as {detail?: string} | null;
      throw new Error(body?.detail || `요청에 실패했습니다. (${response.status})`);
    }
    if (!response.body) throw new Error("스트리밍 응답을 읽을 수 없습니다.");

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let completed: AgentResponse | null = null;

    const handleLine = (line: string) => {
      if (!line.trim()) return;
      const payload = JSON.parse(line) as {type: string; event?: AgentEvent; result?: AgentResponse; message?: string};
      if (payload.type === "status" && payload.event) onStatus(payload.event);
      if (payload.type === "complete" && payload.result) completed = payload.result;
      if (payload.type === "error") throw new Error(payload.message?.trim() || "AI 응답 처리 중 오류가 발생했습니다.");
    };

    while (true) {
      const {done, value} = await reader.read();
      buffer += decoder.decode(value, {stream: !done});
      const lines = buffer.split("\n");
      buffer = lines.pop() ?? "";
      lines.forEach(handleLine);
      if (done) break;
    }
    if (buffer.trim()) handleLine(buffer);
    if (!completed) throw new Error("AI 응답이 완료되지 않았습니다. 다시 시도해 주세요.");
    return completed;
  },
  async changes(): Promise<ProposedChange[]> {
    return (await http.get("/changes")).data.changes;
  },
  async apply(paths: string[] | null): Promise<void> {
    await http.post("/change/apply", {paths});
  },
  async reject(paths: string[] | null): Promise<void> {
    await http.post("/change/reject", {paths});
  },
  async git(kind: "status" | "diff"): Promise<CommandResult> {
    return (await http.get(`/git/${kind}`)).data;
  },
  async run(kind: "build" | "test"): Promise<CommandResult> {
    return (await http.post(`/${kind}`)).data;
  },
};
