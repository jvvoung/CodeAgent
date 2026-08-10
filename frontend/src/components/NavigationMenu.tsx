import {useEffect, useRef, useState} from "react";
import type {AppPage, UserRole} from "../auth";

export function NavigationMenu({page, role, onNavigate, onSettings, onLogout}: {
  page: AppPage;
  role: UserRole;
  onNavigate: (page: AppPage) => void;
  onSettings: () => void;
  onLogout: () => void;
}) {
  const [open, setOpen] = useState(false);
  const container = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) return;
    const closeOutside = (event: PointerEvent) => {
      if (!container.current?.contains(event.target as Node)) setOpen(false);
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("pointerdown", closeOutside);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("pointerdown", closeOutside);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [open]);

  const navigate = (next: AppPage) => {
    onNavigate(next);
    setOpen(false);
  };

  return (
    <div className="navigation-menu" ref={container}>
      <button className="navigation-trigger" aria-label="Navigation 메뉴" aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen((current) => !current)}>
        <span /><span /><span />
      </button>
      {open && <div className="navigation-flyout" role="menu" aria-label="AURA Navigation">
        <button role="menuitem" className={page === "home" ? "active" : ""} onClick={() => navigate("home")}><span>⌂</span>HOME</button>
        {role === "developer" && <button role="menuitem" className={page === "assistant" ? "active" : ""} onClick={() => navigate("assistant")}><span>⌘</span>Code Assistant</button>}
        <div className="navigation-divider" />
        <button role="menuitem" onClick={() => { setOpen(false); onSettings(); }}><span>⚙</span>Settings</button>
        <button role="menuitem" onClick={() => { setOpen(false); onLogout(); }}><span>↪</span>로그아웃</button>
      </div>}
    </div>
  );
}
