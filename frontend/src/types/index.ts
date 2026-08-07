export type TreeNode = {
  name: string;
  path: string;
  type: "directory" | "file";
  children: TreeNode[];
};

export type ProposedChange = {
  path: string;
  original: string;
  modified: string;
  additions: number;
  deletions: number;
};

export type AgentEvent = {
  tool: string;
  status: "completed" | "failed";
  detail?: string;
};

export type AgentResponse = {
  message: string;
  events: AgentEvent[];
  relevant_files: string[];
};

export type OllamaModel = {
  name: string;
  capabilities: string[];
  supports_tools: boolean;
};

export type ChatEntry = {
  id: string;
  role: "user" | "agent" | "status" | "error";
  content: string;
};

export type CommandResult = {
  command: string;
  return_code: number;
  stdout: string;
  stderr: string;
  duration: number;
};
