import {useEffect, useState} from "react";

export type AuraTheme = "dark" | "light";

export function SettingsDialog({open, theme, onCancel, onSave}: {
  open: boolean;
  theme: AuraTheme;
  onCancel: () => void;
  onSave: (theme: AuraTheme) => void;
}) {
  const [draftTheme, setDraftTheme] = useState<AuraTheme>(theme);

  useEffect(() => {
    if (open) setDraftTheme(theme);
  }, [open, theme]);

  useEffect(() => {
    if (!open) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") onCancel();
    };
    document.addEventListener("keydown", closeOnEscape);
    return () => document.removeEventListener("keydown", closeOnEscape);
  }, [open, onCancel]);

  if (!open) return null;
  return (
    <div className="settings-backdrop" role="presentation" onMouseDown={onCancel}>
      <section className="settings-dialog" role="dialog" aria-modal="true" aria-labelledby="settings-title" onMouseDown={(event) => event.stopPropagation()}>
        <header><div><span>APPLICATION</span><h2 id="settings-title">Settings</h2></div><button className="settings-close" aria-label="Settings 닫기" onClick={onCancel}>×</button></header>
        <div className="settings-content">
          <section className="settings-section" aria-labelledby="theme-section-title">
            <div className="settings-section-heading"><span className="settings-section-icon">◐</span><div><h3 id="theme-section-title">Theme</h3><p>AURA 인터페이스의 색상 모드를 선택합니다.</p></div></div>
            <div className="theme-options" role="radiogroup" aria-labelledby="theme-section-title">
              <label className={draftTheme === "dark" ? "selected" : ""}><input type="radio" name="theme" value="dark" checked={draftTheme === "dark"} onChange={() => setDraftTheme("dark")} /><span className="theme-preview dark-preview"><i /><i /><i /></span><span><strong>Dark Mode</strong><small>어두운 IDE 스타일</small></span><b /></label>
              <label className={draftTheme === "light" ? "selected" : ""}><input type="radio" name="theme" value="light" checked={draftTheme === "light"} onChange={() => setDraftTheme("light")} /><span className="theme-preview light-preview"><i /><i /><i /></span><span><strong>Light Mode</strong><small>밝고 선명한 화면</small></span><b /></label>
            </div>
          </section>
        </div>
        <footer><button onClick={onCancel}>Cancel</button><button className="primary" onClick={() => onSave(draftTheme)}>Save</button></footer>
      </section>
    </div>
  );
}
