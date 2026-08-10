import {FormEvent, useState} from "react";
import {api, errorMessage} from "../api/client";
import type {UserRole} from "../auth";

export function LoginPage({onLogin}: {onLogin: (role: UserRole, token: string) => void}) {
  const [userId, setUserId] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!userId.trim() || !password) {
      setMessage("아이디와 비밀번호를 모두 입력해 주세요.");
      return;
    }
    setBusy(true);
    setMessage("");
    try {
      const result = await api.login(userId.trim(), password);
      onLogin(result.role, result.token);
    } catch (error) {
      setMessage(errorMessage(error));
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="login-page">
      <div className="login-ambient login-ambient-one" />
      <div className="login-ambient login-ambient-two" />
      <section className="login-content" aria-labelledby="login-brand-title">
        <header className="login-brand">
          <h1 id="login-brand-title">AURA</h1>
          <p>LOCAL AI WORKSPACE</p>
        </header>
        <form className="login-card" onSubmit={submit}>
          <div className="login-heading"><span>WELCOME BACK</span><h2>로그인</h2><p>AURA 워크스페이스에 접속하세요.</p></div>
          <label htmlFor="login-id">ID</label>
          <input id="login-id" name="id" autoComplete="username" value={userId} onChange={(event) => setUserId(event.target.value)} disabled={busy} />
          <label htmlFor="login-password">Password</label>
          <input id="login-password" name="password" type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} disabled={busy} />
          {message && <p className="login-message" role="alert">{message}</p>}
          <button className="primary login-submit" type="submit" disabled={busy}>{busy ? "로그인 중..." : "로그인"}</button>
          <button className="login-register" type="button" disabled={busy} onClick={() => setMessage("회원가입 기능은 준비 중입니다.")}>회원가입</button>
        </form>
      </section>
    </main>
  );
}
