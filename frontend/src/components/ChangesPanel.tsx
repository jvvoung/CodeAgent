import type {ProposedChange} from "../types";

export function ChangesPanel({changes, selected, busy, showHeader = true, onSelect, onApply, onReject}: {
  changes: ProposedChange[];
  selected: ProposedChange | null;
  busy: boolean;
  showHeader?: boolean;
  onSelect: (change: ProposedChange) => void;
  onApply: (paths: string[] | null) => void;
  onReject: (paths: string[] | null) => void;
}) {
  return (
    <section className="changes-panel">
      {showHeader && <div className="panel-title"><span>변경 제안</span><span className="count">{changes.length}</span></div>}
      <div className="change-list">
        {!changes.length && <div className="aside-empty"><span className="empty-icon">◇</span><strong>변경 제안이 없습니다</strong><p>AI가 만든 변경사항이 여기에 표시됩니다.</p></div>}
        {changes.map((change) => (
          <button key={change.path} className={`change-row ${selected?.path === change.path ? "active" : ""}`} onClick={() => onSelect(change)}>
            <span className="status-m">M</span><span className="change-name"><strong>{change.path.split("/").pop()}</strong><small>{change.path}</small></span><span className="change-stats"><b>+{change.additions}</b><i>−{change.deletions}</i></span>
          </button>
        ))}
      </div>
      <div className="change-actions">
        <button disabled={!selected || busy} onClick={() => selected && onReject([selected.path])}>파일 폐기</button>
        <button className="primary" disabled={!selected || busy} onClick={() => selected && onApply([selected.path])}>파일 적용</button>
        <button disabled={!changes.length || busy} onClick={() => onReject(null)}>전체 폐기</button>
        <button className="primary" disabled={!changes.length || busy} onClick={() => onApply(null)}>전체 적용</button>
      </div>
    </section>
  );
}
