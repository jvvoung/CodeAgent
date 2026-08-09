import type {ProposedChange} from "../types";

const validationLabel = (change: ProposedChange) => {
  switch (change.validation_status) {
    case "verified": return "검증 성공";
    case "baseline_failed": return "기존 빌드 오류";
    case "failed": return "검증 실패 · 확인 후 적용 가능";
    case "scope_review_incomplete": return "범위 검토 미완료";
    case "unavailable": return "검증 불가";
    case "not_run": return "검증 미실행";
    default: return "";
  }
};

export function ChangesPanel({changes, selected, busy, showHeader = true, onSelect, onApply, onReject, onRetry}: {
  changes: ProposedChange[];
  selected: ProposedChange | null;
  busy: boolean;
  showHeader?: boolean;
  onSelect: (change: ProposedChange) => void;
  onApply: (paths: string[] | null) => void;
  onReject: (paths: string[] | null) => void;
  onRetry: (change: ProposedChange) => void;
}) {
  const selectedFailed = selected?.validation_status === "failed";
  const selectedWarning = selected && ["baseline_failed", "scope_review_incomplete", "unavailable", "not_run"].includes(selected.validation_status ?? "");
  return (
    <section className="changes-panel">
      {showHeader && <div className="panel-title"><span>변경 제안</span><span className="count">{changes.length}</span></div>}
      <div className="change-list">
        {!changes.length && <div className="aside-empty"><span className="empty-icon">◇</span><strong>변경 제안이 없습니다</strong><p>AI가 만든 변경사항이 여기에 표시됩니다.</p></div>}
        {changes.map((change) => (
          <button key={change.path} className={`change-row ${selected?.path === change.path ? "active" : ""} ${change.validation_status === "failed" ? "validation-failed" : ""} ${["baseline_failed", "scope_review_incomplete", "unavailable", "not_run"].includes(change.validation_status ?? "") ? "validation-warning" : ""}`} onClick={() => onSelect(change)}>
            <span className="status-m">{change.change_type === "added" ? "A" : change.change_type === "deleted" ? "D" : "M"}</span><span className="change-name"><strong>{change.path.split("/").pop()}</strong><small>{change.path}</small>{validationLabel(change) && <em className={`validation-badge status-${change.validation_status}`}>{validationLabel(change)}</em>}</span><span className="change-stats"><b>+{change.additions}</b><i>−{change.deletions}</i></span>
          </button>
        ))}
      </div>
      {selectedFailed && <div className="validation-error" role="alert"><strong>검증 실패 — 적용 여부는 사용자가 선택할 수 있습니다.</strong><p>{selected?.validation_error || "빌드 또는 구문 검사에 실패했습니다."}</p></div>}
      {selected && selectedWarning && <div className="validation-error validation-note"><strong>{validationLabel(selected)}</strong><p>{selected.validation_error || "자동 검증 결과를 확인할 수 없습니다. Diff를 직접 검토해 주세요."}</p></div>}
      <div className="change-actions">
        <button disabled={!selected || busy} onClick={() => selected && onReject([selected.path])}>파일 폐기</button>
        <button className="primary" disabled={!selected || busy} onClick={() => selected && onApply([selected.path])}>파일 적용</button>
        {selectedFailed && <button className="retry-change wide" disabled={busy || !selected?.retry_request} onClick={() => selected && onRetry(selected)}>오류를 반영해 다시 생성</button>}
        <button disabled={!changes.length || busy} onClick={() => onReject(null)}>전체 폐기</button>
        <button className="primary" disabled={!changes.length || busy} onClick={() => onApply(null)}>전체 적용</button>
      </div>
    </section>
  );
}
