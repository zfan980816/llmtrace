import { useEffect, useState } from "react";
import { authConfig, fetchMe, login, setToken } from "../api";
import Icon from "../components/Icon";
import { t, useLang } from "../i18n";

export default function Login({ onLogin }) {
  const lang = useLang();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [providers, setProviders] = useState([]);

  useEffect(() => {
    const qp = new URLSearchParams(window.location.search);
    const t = qp.get("token");
    if (t) {
      setToken(t);
      fetchMe().then(onLogin).catch(() => setToken(null));
      window.history.replaceState({}, "", window.location.pathname);
      return;
    }
    authConfig().then((c) => setProviders(c.providers || [])).catch(() => {});
  }, []);

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const user = await login(username, password);
      onLogin(user);
    } catch (err) {
      setError(err.response?.data?.detail || "登录失败，请稍后重试");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="login-wrap">
      <form className="login-card" onSubmit={submit}>
        <div className="logo" style={{ justifyContent: "center" }}>
          <span className="logo-mark"><Icon name="radar" size={16} /></span>
          <span className="logo-name">LLMTrace</span>
        </div>
        <p className="login-sub">{t("login.subtitle")}</p>
        <input placeholder={t("login.username")} value={username} autoFocus
          onChange={(e) => setUsername(e.target.value)} />
        <input placeholder={t("login.password")} type="password" value={password}
          onChange={(e) => setPassword(e.target.value)} />
        {error && <div className="error-text">{error}</div>}
        <button className="btn" disabled={busy || !username || !password}>
          <Icon name="arrow-left" size={13} style={{ transform: "rotate(180deg)" }} />
          {busy ? t("login.submitting") : t("login.submit")}
        </button>
        {providers.length > 0 && (
          <>
            <div className="login-divider"><span>{t("login.or")}</span></div>
            {providers.map((pr) => (
              <button key={pr.name} type="button" className="btn btn-outline feishu-btn"
                onClick={() => { window.location.href = "/api/auth/sso/" + pr.name + "/login"; }}>
                {pr.name === "feishu" ? (
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
                    <path d="M3.9 8.7h7.3l-2.4 4.6h4.9L6.9 23l1.6-6.4H3.6L6 8.7H3.9zm8.6-6h6.6l-2.2 4.1h4.1L9.8 21.9l2.4-7.2H8.1l2.6-5.3H8.7l3.8-6.7z"/>
                  </svg>
                ) : (
                  <Icon name="user" size={14} />
                )}
                {pr.label}
              </button>
            ))}
          </>
        )}
        <p className="login-hint">{t("login.hint")}</p>
      </form>
    </div>
  );
}

