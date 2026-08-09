export function repositoryName(remote: string): string {
  if (!remote) return "연결 안 됨";
  const cleaned = remote.trim().replace(/[\\/]+$/, "").replace(/\.git$/i, "");
  return cleaned.split(/[\\/:]/).filter(Boolean).pop() || remote;
}
