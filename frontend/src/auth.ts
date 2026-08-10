export type UserRole = "developer" | "non-developer";
export type AppPage = "home" | "assistant";

export type AuthSession = {
  isAuthenticated: true;
  role: UserRole;
  token: string;
};

const AUTHENTICATED_KEY = "aura.isAuthenticated";
const ROLE_KEY = "aura.role";
const TOKEN_KEY = "aura.authToken";

export function readAuthSession(): AuthSession | null {
  const authenticated = sessionStorage.getItem(AUTHENTICATED_KEY) === "true";
  const role = sessionStorage.getItem(ROLE_KEY);
  const token = sessionStorage.getItem(TOKEN_KEY) ?? "";
  if (!authenticated || (role !== "developer" && role !== "non-developer") || !token) {
    clearAuthSession();
    return null;
  }
  return {isAuthenticated: true, role, token};
}

export function saveAuthSession(role: UserRole, token: string): AuthSession {
  sessionStorage.setItem(AUTHENTICATED_KEY, "true");
  sessionStorage.setItem(ROLE_KEY, role);
  sessionStorage.setItem(TOKEN_KEY, token);
  return {isAuthenticated: true, role, token};
}

export function clearAuthSession(): void {
  sessionStorage.removeItem(AUTHENTICATED_KEY);
  sessionStorage.removeItem(ROLE_KEY);
  sessionStorage.removeItem(TOKEN_KEY);
}

export function canAccessPage(role: UserRole, page: AppPage): boolean {
  return page === "home" || role === "developer";
}

export function pageFromHash(hash: string): AppPage {
  return hash.replace(/^#\/?/, "") === "assistant" ? "assistant" : "home";
}
