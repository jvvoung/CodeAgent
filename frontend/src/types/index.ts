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
  change_type?: "added" | "modified" | "deleted";
  validation_status?: "ready" | "verified" | "baseline_failed" | "failed" | "scope_review_incomplete" | "unavailable" | "not_run";
  validation_error?: string;
  retry_request?: string;
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
  git_result?: CommandResult;
  git_changed?: boolean;
  project_changed?: boolean;
  pending_git_action?: {
    type: "push";
    branch: string;
    remote: string;
  };
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

export type TerminalShell = "cmd" | "powershell" | "git-bash";

export type TerminalResult = CommandResult & {
  shell: TerminalShell;
  cwd: string;
};

export type GitInfo = {
  root: string;
  branch: string;
  branches: string[];
  remote: string;
  has_changes: boolean;
  has_staged: boolean;
  has_unstaged: boolean;
};

export type GitFileChange = {
  path: string;
  old_path: string | null;
  status: "added" | "modified" | "deleted" | "renamed" | "copied";
  additions: number;
  deletions: number;
  original: string;
  modified: string;
  binary: boolean;
  truncated: boolean;
};

export type BranchCheckoutResponse = {
  result: CommandResult;
  tree: TreeNode[];
  git: GitInfo;
};

export type CommandAction = "build" | "test" | "status" | "diff" | "staged-diff" | "stage" | "unstage" | "commit" | "push";
